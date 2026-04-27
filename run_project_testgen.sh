#!/bin/bash
# CSA Test Generation Tool - Multi-file Project Support (Driver Method)
# Usage: ./run_project_testgen.sh <project_dir> [output_dir]
#
# Driver method: for each source file, generate a driver that calls each
# function with scanf-read inputs, so CSA sees conjured (conj_$N) symbols.
# Driver and target are compiled in the same TU for proper symbol tracking.

set -e

CLANG_BIN="/home/yanghq/llvm/llvm-project/build/bin/clang"
SOLVE_PY="/home/yanghq/csa-testgen/solve.py"
CODEGEN_PY="/home/yanghq/csa-testgen/codegen.py"
GEN_DRIVER_PY="/home/yanghq/csa-testgen/generate_driver.py"
GEN_COMPILE_COMMANDS="/home/yanghq/csa-testgen/generate_compile_commands.py"
MEASURE_COV_PY="/home/yanghq/csa-testgen/measure_coverage.py"
FILL_GAPS_PY="/home/yanghq/csa-testgen/fill_gaps.py"
REPORT_COV_PY="/home/yanghq/csa-testgen/report_coverage.py"
PYTHON="/home/yanghq/csa-testgen/venv/bin/python3"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <project_dir> [output_dir]"
    echo ""
    echo "Example:"
    echo "  $0 test/cproject/sample_project"
    echo "  $0 test/cproject/sample_project output/"
    exit 1
fi

PROJECT_DIR="$(cd "$1" && pwd)"
OUTPUT_DIR="${2:-$PROJECT_DIR/testgen_output}"
OUTPUT_DIR="$(mkdir -p "$OUTPUT_DIR" && cd "$OUTPUT_DIR" && pwd)"

echo "=== CSA Multi-File Test Generation Pipeline (Driver Method) ==="
echo "Project: $PROJECT_DIR"
echo "Output:  $OUTPUT_DIR"
echo ""

# Step 1: Generate compile_commands.json if not present
COMPILE_COMMANDS="$PROJECT_DIR/compile_commands.json"
if [ ! -f "$COMPILE_COMMANDS" ]; then
    echo "[1/5] Generating compile_commands.json..."
    "$PYTHON" "$GEN_COMPILE_COMMANDS" "$PROJECT_DIR"
else
    echo "[1/5] Using existing compile_commands.json"
fi

# Step 2: Parse source files from compile_commands.json
echo ""
echo "[2/5] Discovering source files..."

SOURCE_FILES=$("$PYTHON" -c "
import json
with open('$COMPILE_COMMANDS') as f:
    data = json.load(f)
for entry in data:
    if 'vendor' not in entry['file'] and 'third_party' not in entry['file']:
        print(entry['file'])
")

if [ -z "$SOURCE_FILES" ]; then
    echo "Error: No source files found in compile_commands.json"
    exit 1
fi

echo "$SOURCE_FILES" | while read -r f; do echo "  $f"; done

# Step 3: For each source file, generate a driver and run CSA on it
echo ""
echo "[3/5] Generating drivers and running CSA..."

ALL_CONSTRAINTS="$OUTPUT_DIR/all_constraints.json"
rm -f "$ALL_CONSTRAINTS"

FILE_COUNT=0
for SRC in $SOURCE_FILES; do
    FILE_COUNT=$((FILE_COUNT + 1))
    BASENAME=$(basename "$SRC" .c)
    DRIVER_FILE="$OUTPUT_DIR/${BASENAME}_driver.c"
    CONSTRAINTS_FILE="$OUTPUT_DIR/${BASENAME}_constraints.json"

    # Extract compiler flags and working directory
    COMPILE_INFO=$("$PYTHON" -c "
import json
with open('$COMPILE_COMMANDS') as f:
    data = json.load(f)
for entry in data:
    if entry['file'] == '$SRC':
        args = entry['arguments'][1:]
        args = [a for a in args if a != '-c' and a != '$SRC']
        print(entry['directory'])
        print(' '.join(args))
        break
")
    WORK_DIR=$(echo "$COMPILE_INFO" | head -1)
    CFLAGS=$(echo "$COMPILE_INFO" | tail -1)

    echo "  [$FILE_COUNT] $SRC"

    # Generate driver file (embeds source via #include for same-TU analysis)
    "$PYTHON" "$GEN_DRIVER_PY" "$SRC" "$DRIVER_FILE"

    # Run CSA on the driver (not the original source)
    (cd "$WORK_DIR" && \
      TESTGEN_OUTPUT="$CONSTRAINTS_FILE" \
      "$CLANG_BIN" --analyze \
        -Xclang -analyzer-checker=testgen.TestGenAnalyzer \
        -Xclang -analyzer-constraints=z3 \
        $CFLAGS \
        "$DRIVER_FILE" 2>&1 | grep -E "\[TestGenAnalyzer\]|error:" || true)
done

# Step 4: Merge all constraint files
echo ""
echo "[4/5] Merging constraints..."

"$PYTHON" -c "
import json, glob, os

all_paths = []
files = sorted(glob.glob('$OUTPUT_DIR/*_constraints.json'))
for f in files:
    try:
        with open(f) as fp:
            data = json.load(fp)
            paths = data.get('paths', [])
            basename = os.path.basename(f).replace('_constraints.json', '')
            for p in paths:
                p['source_file'] = basename + '.c'
            all_paths.extend(paths)
    except Exception as e:
        print(f'Warning: Failed to read {f}: {e}')

for i, p in enumerate(all_paths, 1):
    p['path'] = i

with open('$ALL_CONSTRAINTS', 'w') as f:
    json.dump({'paths': all_paths}, f, indent=2)

print(f'Merged {len(all_paths)} paths from {len(files)} files')
"

if [ ! -f "$ALL_CONSTRAINTS" ]; then
    echo "Error: Failed to merge constraints"
    exit 1
fi

# Step 5: Solve with Z3 and generate test code
echo ""
echo "[5/5] Solving constraints and generating tests..."

TEST_INPUTS="$OUTPUT_DIR/test_inputs.json"
"$PYTHON" "$SOLVE_PY" "$ALL_CONSTRAINTS" > "$TEST_INPUTS"

NUM_INPUTS=$("$PYTHON" -c "import json,sys; print(len(json.load(open('$TEST_INPUTS'))))" 2>/dev/null || echo "0")
echo "Solved $NUM_INPUTS path inputs"

TEST_C="$OUTPUT_DIR/test_autogen.c"
"$PYTHON" "$CODEGEN_PY" "$TEST_INPUTS" "$TEST_C"

echo ""
echo "=== Done ==="
echo "Constraints: $ALL_CONSTRAINTS"
echo "Test inputs: $TEST_INPUTS"
echo "Test code:   $TEST_C"
echo ""

# Step 6: Measure coverage (before LLM gap filling)
COV_BEFORE="$OUTPUT_DIR/coverage_before.json"
COV_AFTER="$OUTPUT_DIR/coverage_after.json"
COV_WORK="$OUTPUT_DIR/cov_work"

echo "[6/8] Measuring coverage (before LLM gap filling)..."
"$PYTHON" "$MEASURE_COV_PY" \
    "$TEST_C" \
    "$PROJECT_DIR" \
    "$COMPILE_COMMANDS" \
    --output "$COV_BEFORE" \
    --work-dir "$COV_WORK"

# Step 7: LLM-based coverage gap filling
# Requires ANTHROPIC_API_KEY (env var or config.ini); skipped gracefully if missing.
echo ""
echo "[7/8] LLM coverage gap filling..."

# If env var is not set, try to read from config.ini next to fill_gaps.py
_CONFIG_INI="$(dirname "$FILL_GAPS_PY")/config.ini"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$_CONFIG_INI" ]; then
    _KEY=$(python3 -c "
import configparser, sys
c = configparser.ConfigParser()
c.read('$_CONFIG_INI')
k = c.get('anthropic', 'api_key', fallback='').strip().strip('\"').strip(\"'\")
if k and k != 'YOUR_API_KEY_HERE':
    print(k)
" 2>/dev/null)
    if [ -n "$_KEY" ]; then
        export ANTHROPIC_API_KEY="$_KEY"
    fi
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "  ANTHROPIC_API_KEY not set — skipping gap fill"
    echo "  To run manually:"
    echo "    python3 $FILL_GAPS_PY $COV_BEFORE"
else
    "$PYTHON" "$FILL_GAPS_PY" "$COV_BEFORE"

    # Step 8: Measure coverage again (after LLM gap filling) and compare
    echo ""
    echo "[8/8] Measuring coverage (after LLM gap filling)..."
    "$PYTHON" "$MEASURE_COV_PY" \
        "$TEST_C" \
        "$PROJECT_DIR" \
        "$COMPILE_COMMANDS" \
        --output "$COV_AFTER" \
        --work-dir "$COV_WORK"

    echo ""
    echo "=== Coverage Comparison ==="
    "$PYTHON" "$REPORT_COV_PY" "$COV_BEFORE" "$COV_AFTER"
fi

echo ""
echo "To compile and run:"
echo "  gcc -std=c11 -D_GNU_SOURCE -I<include_dir> <sources> $TEST_C -o test_autogen"
echo "  ./test_autogen"
