#!/bin/bash
# CSA Test Generation Tool - Convenience Script
# Usage: ./run_testgen.sh <source.c> [output.json]

set -e

# Configuration
CLANG_BIN="/home/yanghq/llvm/llvm-project/build/bin/clang"
SOLVE_PY="/home/yanghq/csa-testgen/solve.py"
PYTHON="/home/yanghq/csa-testgen/venv/bin/python3"

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 <source.c> [output.json]"
    echo ""
    echo "Example:"
    echo "  $0 test.c"
    echo "  $0 test.c results.json"
    exit 1
fi

SOURCE_FILE="$1"
OUTPUT_FILE="${2:-testgen_results.json}"

# Check if source file exists
if [ ! -f "$SOURCE_FILE" ]; then
    echo "Error: Source file '$SOURCE_FILE' not found"
    exit 1
fi

# Temporary file for constraints
CONSTRAINTS_FILE=$(mktemp /tmp/testgen_constraints.XXXXXX.json)
trap "rm -f $CONSTRAINTS_FILE" EXIT

echo "=== CSA Test Generation Pipeline ==="
echo "Source: $SOURCE_FILE"
echo "Output: $OUTPUT_FILE"
echo ""

# Step 1: Run CSA with Z3 backend
echo "[1/2] Running Clang Static Analyzer..."
TESTGEN_OUTPUT="$CONSTRAINTS_FILE" \
  "$CLANG_BIN" --analyze \
    -Xclang -analyzer-checker=testgen.TestGenAnalyzer \
    -Xclang -analyzer-constraints=z3 \
    "$SOURCE_FILE" 2>&1 | grep -E "\[TestGenAnalyzer\]|error:"

if [ ! -f "$CONSTRAINTS_FILE" ]; then
    echo "Error: Constraint file not generated"
    exit 1
fi

# Step 2: Solve constraints with Z3
echo ""
echo "[2/2] Solving constraints with Z3..."
"$PYTHON" "$SOLVE_PY" "$CONSTRAINTS_FILE" > "$OUTPUT_FILE" 2>&1

# Check if successful
if [ $? -eq 0 ]; then
    NUM_PATHS=$(cat "$OUTPUT_FILE" | "$PYTHON" -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    echo ""
    echo "=== Success ==="
    echo "Generated $NUM_PATHS test cases"
    echo "Results saved to: $OUTPUT_FILE"
    echo ""
    echo "Preview:"
    cat "$OUTPUT_FILE" | "$PYTHON" -m json.tool | head -30
    if [ $(cat "$OUTPUT_FILE" | wc -l) -gt 30 ]; then
        echo "... (truncated, see $OUTPUT_FILE for full output)"
    fi
else
    echo "Error: Failed to solve constraints"
    exit 1
fi
