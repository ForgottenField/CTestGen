#!/bin/bash
# run_klee_testgen.sh — KLEE-based test generation and coverage measurement
#
# Generates KLEE harnesses for each source file, runs KLEE symbolic execution,
# replays test cases with klee-replay + gcov, and reports branch/line coverage.
#
# Usage:
#   ./run_klee_testgen.sh <project_dir> [output_dir]
#
# Prerequisites:
#   - KLEE built with LLVM 18 at /home/yanghq/klee/build-llvm18/
#   - klee-uclibc at /home/yanghq/klee/klee-uclibc/
#   - clang-18 at /home/yanghq/llvm/llvm-project/build/bin/clang

set -e

# ---------------------------------------------------------------------------
# Tool paths
# ---------------------------------------------------------------------------
KLEE_BIN="/home/yanghq/klee/build-llvm18/bin/klee"
KLEE_REPLAY="/home/yanghq/klee/build-llvm18/bin/klee-replay"
KLEE_LIB="/home/yanghq/klee/build-llvm18/lib"
KLEE_INCLUDE="/home/yanghq/klee/klee/include"
CLANG18="/usr/lib/llvm-18/bin/clang"
LLVM_LINK="/usr/lib/llvm-18/bin/llvm-link"

GEN_HARNESS_PY="/home/yanghq/csa-testgen/generate_klee_harness.py"
PYTHON="/home/yanghq/csa-testgen/venv/bin/python3"

# KLEE options
KLEE_MAX_TIME="${KLEE_MAX_TIME:-120s}"   # per-harness time limit (override via env)

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------
if [ ! -f "$KLEE_BIN" ]; then
    echo "ERROR: KLEE not found at $KLEE_BIN"
    echo "Please build KLEE with LLVM 18 first. See klee_setup.md."
    exit 1
fi

if [ $# -lt 1 ]; then
    echo "Usage: $0 <project_dir> [output_dir]"
    echo ""
    echo "Example:"
    echo "  $0 test/cproject/sample_project"
    echo "  $0 test/cproject/sample_project klee_output/"
    exit 1
fi

PROJECT_DIR="$(cd "$1" && pwd)"
OUTPUT_DIR="${2:-$PROJECT_DIR/klee_output}"
OUTPUT_DIR="$(mkdir -p "$OUTPUT_DIR" && cd "$OUTPUT_DIR" && pwd)"

COMPILE_COMMANDS="$PROJECT_DIR/compile_commands.json"

echo "=== KLEE Test Generation Pipeline ==="
echo "Project: $PROJECT_DIR"
echo "Output:  $OUTPUT_DIR"
echo "KLEE:    $KLEE_BIN"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Discover source files from compile_commands.json
# ---------------------------------------------------------------------------
echo "[1/4] Discovering source files..."

if [ ! -f "$COMPILE_COMMANDS" ]; then
    echo "ERROR: compile_commands.json not found at $COMPILE_COMMANDS"
    exit 1
fi

SOURCE_FILES=$("$PYTHON" -c "
import json
with open('$COMPILE_COMMANDS') as f:
    data = json.load(f)
for entry in data:
    if 'vendor' not in entry['file'] and 'third_party' not in entry['file']:
        print(entry['file'])
")

if [ -z "$SOURCE_FILES" ]; then
    echo "ERROR: No source files found in compile_commands.json"
    exit 1
fi

echo "$SOURCE_FILES" | while read -r f; do echo "  $f"; done

# ---------------------------------------------------------------------------
# Step 2: For each source file — generate harness, compile to bitcode, run KLEE
# ---------------------------------------------------------------------------
echo ""
echo "[2/4] Generating harnesses and running KLEE..."

INCLUDE_DIR="$PROJECT_DIR/include"

# Pre-compile ALL project source files (including vendor) to bitcode
# so harnesses for individual files can call cross-file functions symbolically
echo "  Pre-compiling all project sources to bitcode..."
ALL_SRCS_BC=""
ALL_PROJECT_SRCS=$("$PYTHON" -c "
import json
with open('$COMPILE_COMMANDS') as f:
    data = json.load(f)
for entry in data:
    print(entry['file'])
")
for ASRC in $ALL_PROJECT_SRCS; do
    ABASE=$(basename "$ASRC" .c)
    ASRC_BC="$OUTPUT_DIR/allsrc_${ABASE}.bc"

    AIFLAGS=$("$PYTHON" -c "
import json, os
with open('$COMPILE_COMMANDS') as f:
    data = json.load(f)
for entry in data:
    if entry['file'] == '$ASRC':
        work_dir = entry.get('directory', os.getcwd())
        args = entry.get('arguments', [])
        flags = []
        for a in args:
            if a.startswith('-I'):
                ipath = a[2:]
                if ipath and not os.path.isabs(ipath):
                    ipath = os.path.join(work_dir, ipath)
                flags.append('-I' + ipath)
            elif a.startswith('-D'):
                flags.append(a)
        print(' '.join(flags))
        break
")
    # shellcheck disable=SC2086
    env -i HOME="$HOME" PATH="/usr/lib/llvm-18/bin:/usr/bin:/bin" \
        "$CLANG18" -g -O0 -emit-llvm -c \
        $AIFLAGS \
        -fno-discard-value-names \
        "$ASRC" -o "$ASRC_BC" 2>/dev/null && \
        ALL_SRCS_BC="$ALL_SRCS_BC $ASRC_BC" || \
        echo "  WARNING: pre-compile failed for $ASRC"
done
echo "  Pre-compiled: $(echo $ALL_SRCS_BC | wc -w) source bitcodes"

for SRC in $SOURCE_FILES; do
    BASENAME=$(basename "$SRC" .c)
    HARNESS_C="$OUTPUT_DIR/${BASENAME}_klee_harness.c"
    HARNESS_BC="$OUTPUT_DIR/${BASENAME}_harness.bc"
    LINKED_BC="$OUTPUT_DIR/${BASENAME}_linked.bc"
    KLEE_OUT="$OUTPUT_DIR/klee_out_${BASENAME}"

    echo ""
    echo "  --- $SRC ---"

    # 2a. Generate KLEE harness
    echo "  Generating harness..."
    "$PYTHON" "$GEN_HARNESS_PY" "$SRC" "$HARNESS_C" "$INCLUDE_DIR"

    # Extract include/define flags from compile_commands.json
    # Relative -I paths are resolved against the entry's working directory
    IFLAGS=$("$PYTHON" -c "
import json, os
with open('$COMPILE_COMMANDS') as f:
    data = json.load(f)
for entry in data:
    if entry['file'] == '$SRC':
        work_dir = entry.get('directory', os.getcwd())
        args = entry.get('arguments', [])
        flags = []
        for a in args:
            if a.startswith('-I'):
                ipath = a[2:]
                if ipath and not os.path.isabs(ipath):
                    ipath = os.path.join(work_dir, ipath)
                flags.append('-I' + ipath)
            elif a.startswith('-D'):
                flags.append(a)
        print(' '.join(flags))
        break
")

    # 2b. Compile harness to LLVM bitcode
    echo "  Compiling harness to bitcode..."
    # shellcheck disable=SC2086
    env -i HOME="$HOME" PATH="/usr/lib/llvm-18/bin:/usr/bin:/bin" \
        "$CLANG18" -g -O0 -emit-llvm -c \
        -I"$KLEE_INCLUDE" \
        $IFLAGS \
        -fno-discard-value-names \
        "$HARNESS_C" -o "$HARNESS_BC" 2>&1 || {
        echo "  WARNING: Failed to compile harness — skipping"
        continue
    }

    # 2c. Link harness + all project source bitcodes
    echo "  Linking bitcode (harness + all project sources)..."
    # shellcheck disable=SC2086
    "$LLVM_LINK" "$HARNESS_BC" $ALL_SRCS_BC -o "$LINKED_BC" 2>&1

    # 2d. Run KLEE
    echo "  Running KLEE (max-time=$KLEE_MAX_TIME)..."
    rm -rf "$KLEE_OUT"
    "$KLEE_BIN" \
        --libc=uclibc \
        --posix-runtime \
        --max-time="$KLEE_MAX_TIME" \
        --output-dir="$KLEE_OUT" \
        "$LINKED_BC" 2>&1 | grep -v "^KLEE: NOTE" || true

    NTESTS=$(find "$KLEE_OUT" -name "*.ktest" 2>/dev/null | wc -l)
    echo "  Generated $NTESTS test case(s)"
done

# ---------------------------------------------------------------------------
# Step 3: Replay ktest files with klee-replay and measure coverage
# ---------------------------------------------------------------------------
echo ""
echo "[3/4] Replaying test cases and measuring coverage..."

# Temporary directory for coverage data files
COV_DIR="$OUTPUT_DIR/cov_work"
mkdir -p "$COV_DIR"

# Associative array: source_file -> (lines_total, lines_covered, branches_total, branches_covered)
declare -A LINES_TOTAL LINES_COV BRANCH_TOTAL BRANCH_COV

for SRC in $SOURCE_FILES; do
    BASENAME=$(basename "$SRC" .c)
    HARNESS_C="$OUTPUT_DIR/${BASENAME}_klee_harness.c"
    KLEE_OUT="$OUTPUT_DIR/klee_out_${BASENAME}"

    if [ ! -d "$KLEE_OUT" ] || [ ! -f "$HARNESS_C" ]; then
        echo "  Skipping $BASENAME (no KLEE output or harness)"
        continue
    fi

    NTESTS=$(find "$KLEE_OUT" -name "*.ktest" 2>/dev/null | wc -l)
    if [ "$NTESTS" -eq 0 ]; then
        echo "  $BASENAME: no .ktest files — skipping coverage"
        continue
    fi

    echo ""
    echo "  --- $BASENAME ($NTESTS test cases) ---"

    # Extract include flags
    IFLAGS=$("$PYTHON" -c "
import json, os
with open('$COMPILE_COMMANDS') as f:
    data = json.load(f)
for entry in data:
    if entry['file'] == '$SRC':
        work_dir = entry.get('directory', os.getcwd())
        args = entry.get('arguments', [])
        flags = []
        for a in args:
            if a.startswith('-I'):
                ipath = a[2:]
                if ipath and not os.path.isabs(ipath):
                    ipath = os.path.join(work_dir, ipath)
                flags.append('-I' + ipath)
            elif a.startswith('-D'):
                flags.append(a)
        print(' '.join(flags))
        break
")

    # 3a. Collect all project source files (excluding vendor) for the coverage binary
    ALL_SRCS=$("$PYTHON" -c "
import json, os
with open('$COMPILE_COMMANDS') as f:
    data = json.load(f)
srcs = []
for entry in data:
    f = entry['file']
    if 'vendor' not in f and 'third_party' not in f:
        srcs.append(f)
print(' '.join(srcs))
")
    # Also add vendor/third_party sources that are referenced (e.g. third_party_adapter)
    THIRD_PARTY_SRCS=$("$PYTHON" -c "
import json, os
with open('$COMPILE_COMMANDS') as f:
    data = json.load(f)
srcs = []
for entry in data:
    fp = entry['file']
    if 'vendor' in fp or 'third_party' in fp:
        srcs.append(fp)
print(' '.join(srcs))
")

    COV_BIN="$COV_DIR/${BASENAME}_cov"
    echo "  Compiling coverage binary..."
    # shellcheck disable=SC2086
    gcc --coverage -fno-inline -O0 -g \
        -I"$KLEE_INCLUDE" \
        $IFLAGS \
        "$HARNESS_C" $ALL_SRCS $THIRD_PARTY_SRCS \
        -L"$KLEE_LIB" -lkleeRuntest \
        -Wl,-rpath,"$KLEE_LIB" \
        -o "$COV_BIN" 2>&1 || {
        echo "  WARNING: Failed to compile coverage binary — skipping"
        continue
    }

    # 3b. Replay each ktest file using KTEST_FILE env var (klee-replay does not set it)
    # Limit to first 500 ktests — coverage saturates quickly
    echo "  Replaying up to 500 of $NTESTS test cases..."
    find "$KLEE_OUT" -name "*.ktest" | head -500 | while read -r KTEST; do
        KTEST_FILE="$KTEST" LD_LIBRARY_PATH="$KLEE_LIB" \
            "$COV_BIN" 2>/dev/null || true
    done

    # 3c. Run gcov to collect coverage data
    # gcno files are named <binary_base>-<source_base>.gcno
    GCOV_OUT=$("$PYTHON" -c "
import subprocess, re, os, glob

src = '$SRC'
src_base = os.path.splitext(os.path.basename(src))[0]
cov_dir = '$COV_DIR'
cov_bin_base = '${BASENAME}_cov'

# Look for exactly <cov_bin_base>-<src_base>.gcno
gcno_name = f'{cov_bin_base}-{src_base}.gcno'
gcno_path = os.path.join(cov_dir, gcno_name)
if not os.path.exists(gcno_path):
    print(f'# no gcno found: {gcno_name}', flush=True)
else:
    result = subprocess.run(
        ['gcov', '-b', '-c', '-n', gcno_name],
        capture_output=True, text=True,
        cwd=cov_dir,
    )
    print(result.stdout + result.stderr)
" 2>&1)

    # 3e. Parse gcov output for coverage stats
    STATS=$("$PYTHON" -c "
import re, sys

text = '''$GCOV_OUT'''
# Look for lines like 'Lines executed:85.71% of 14'
# and 'Branches executed:72.22% of 18'
lines_match = re.search(r'Lines executed:(\d+\.?\d*)% of (\d+)', text)
branch_match = re.search(r'Branches executed:(\d+\.?\d*)% of (\d+)', text)
taken_match  = re.search(r'Taken at least once:(\d+\.?\d*)% of (\d+)', text)

if lines_match:
    pct  = float(lines_match.group(1))
    total = int(lines_match.group(2))
    covered = round(pct * total / 100)
    print(f'LINES {covered} {total}')
if branch_match and taken_match:
    total = int(branch_match.group(2))
    pct   = float(taken_match.group(1))
    covered = round(pct * total / 100)
    print(f'BRANCHES {covered} {total}')
")

    echo "  Coverage stats: $STATS"
    LINES_COV["$BASENAME"]=$(echo "$STATS" | awk '/^LINES/{print $2}')
    LINES_TOTAL["$BASENAME"]=$(echo "$STATS" | awk '/^LINES/{print $3}')
    BRANCH_COV["$BASENAME"]=$(echo "$STATS" | awk '/^BRANCHES/{print $2}')
    BRANCH_TOTAL["$BASENAME"]=$(echo "$STATS" | awk '/^BRANCHES/{print $3}')
done

# ---------------------------------------------------------------------------
# Step 4: Print coverage report
# ---------------------------------------------------------------------------
echo ""
echo "[4/4] Coverage Report"
echo "======================================"
printf "%-28s  %10s  %12s\n" "Source file" "Line cov" "Branch cov"
echo "----------------------------------------------------------------------"

TOTAL_LC=0; TOTAL_LT=0; TOTAL_BC=0; TOTAL_BT=0

for SRC in $SOURCE_FILES; do
    BASENAME=$(basename "$SRC" .c)
    LC=${LINES_COV[$BASENAME]:-0}
    LT=${LINES_TOTAL[$BASENAME]:-0}
    BC=${BRANCH_COV[$BASENAME]:-0}
    BT=${BRANCH_TOTAL[$BASENAME]:-0}

    if [ "$LT" -gt 0 ]; then
        LP=$(python3 -c "print(f'{$LC/$LT*100:.1f}%')")
    else
        LP="N/A"
    fi
    if [ "$BT" -gt 0 ]; then
        BP=$(python3 -c "print(f'{$BC/$BT*100:.1f}%')")
    else
        BP="N/A"
    fi

    printf "%-28s  %4s/%4s %-4s  %4s/%4s %-4s\n" \
        "${BASENAME}.c" "$LC" "$LT" "($LP)" "$BC" "$BT" "($BP)"

    TOTAL_LC=$((TOTAL_LC + LC))
    TOTAL_LT=$((TOTAL_LT + LT))
    TOTAL_BC=$((TOTAL_BC + BC))
    TOTAL_BT=$((TOTAL_BT + BT))
done

echo "----------------------------------------------------------------------"
if [ "$TOTAL_LT" -gt 0 ]; then
    TOTAL_LP=$(python3 -c "print(f'{$TOTAL_LC/$TOTAL_LT*100:.1f}%')")
else
    TOTAL_LP="N/A"
fi
if [ "$TOTAL_BT" -gt 0 ]; then
    TOTAL_BP=$(python3 -c "print(f'{$TOTAL_BC/$TOTAL_BT*100:.1f}%')")
else
    TOTAL_BP="N/A"
fi
printf "%-28s  %4s/%4s %-4s  %4s/%4s %-4s\n" \
    "TOTAL" "$TOTAL_LC" "$TOTAL_LT" "($TOTAL_LP)" "$TOTAL_BC" "$TOTAL_BT" "($TOTAL_BP)"
echo ""
echo "KLEE output: $OUTPUT_DIR"
echo ""
echo "To compare with CSA tool coverage, run:"
echo "  python3 /home/yanghq/csa-testgen/report_coverage.py \\"
echo "      $PROJECT_DIR/testgen_output/coverage_before.json"
