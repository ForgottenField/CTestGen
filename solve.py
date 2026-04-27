#!/usr/bin/env python3
"""
Read path constraints from testgen_constraints.json (produced by TestGenAnalyzer
with -analyzer-constraints=z3) and solve them with Z3 to produce concrete test inputs.

Usage:
    TESTGEN_OUTPUT=/path/to/out.json \\
      clang --analyze -Xclang -analyzer-checker=testgen.TestGenAnalyzer \\
             -Xclang -analyzer-constraints=z3 foo.c
    python3 solve.py [testgen_constraints.json]
"""

import sys
import re
import json
import subprocess
import tempfile
import os

# ---------------------------------------------------------------------------
# Load paths from JSON file
# ---------------------------------------------------------------------------

def load_paths(json_path):
    with open(json_path) as f:
        data = json.load(f)
    return data.get("paths", [])


# ---------------------------------------------------------------------------
# Extract constraints list from a path entry
# ---------------------------------------------------------------------------

def get_constraints(path):
    """Return the constraints list. Supports both new format (state_json as
    parsed JSON object) and legacy format (state_json as raw string)."""
    state_json = path.get("state_json")
    if state_json is None:
        return []
    # New format: state_json is already a dict
    if isinstance(state_json, dict):
        return state_json.get("program_state", {}).get("constraints") or []
    # Legacy fallback: state_json is a raw string starting with "program_state": ...
    # CSA sometimes emits unescaped control characters (e.g. newlines) inside
    # JSON string values, which breaks strict parsing.  Replace all control
    # characters with a space before attempting to parse.
    sanitized = re.sub(r'[\x00-\x1f]', ' ', state_json)
    try:
        state = json.loads("{" + sanitized + "}")
        return state.get("program_state", {}).get("constraints") or []
    except json.JSONDecodeError:
        return []


# ---------------------------------------------------------------------------
# Symbol name helpers
# ---------------------------------------------------------------------------

# "conj_$2{int, LC1, S13485, #1}" -> "conj_$2"
CONJ_FULL_RE = re.compile(r'conj_\$(\d+)\{[^}]+\}')
# bare "conj_$2" or "derived_$2" as they appear in SMT expressions
CONJ_BARE_RE  = re.compile(r'conj_\$\d+')
ALL_SYM_RE    = re.compile(r'(?:conj|derived)_\$\d+')

# Width inference patterns
# ((_ sign_extend K) sym) → sym is BitVec (32 - K)
SIGN_EXTEND_RE = re.compile(r'\(_ sign_extend (\d+)\)\s+((?:conj|derived)_\$\d+)')
# derived_$N{...,OFFSET S\d+b,char} → derived_$N is at byte OFFSET in a string
DERIVED_OFFSET_RE = re.compile(r'(derived_\$\d+).*?(\d+) S\d+b,char\}')


def param_sym_id(sym_str):
    """Extract the bare symbol name (e.g. 'conj_$2') from a full sym string."""
    m = CONJ_FULL_RE.search(sym_str)
    return f"conj_${m.group(1)}" if m else None


def collect_all_symbols(smt_exprs):
    """Return the set of all conj_$N and derived_$N names in a list of SMT strings."""
    syms = set()
    for expr in smt_exprs:
        syms.update(ALL_SYM_RE.findall(expr))
    return syms


def infer_bitvec_widths(smt_exprs):
    """Return dict {sym: width} inferred from SMT expression context.

    Rules:
    - ((_ sign_extend K) sym) → sym is BitVec (32 - K), e.g. chars are BitVec 8
    - sym adjacent to a 16-hex-char literal (#x...) → sym is BitVec 64 (pointer)
    - Default: BitVec 32
    """
    widths = {}
    for expr in smt_exprs:
        # sign_extend: determine sub-expression bit-width
        for m in SIGN_EXTEND_RE.finditer(expr):
            extend_bits = int(m.group(1))
            sym = m.group(2)
            sym_width = 32 - extend_bits
            if sym not in widths:
                widths[sym] = sym_width
        # 64-bit pointer literals: sym next to #x<16 hex chars>
        for m in re.finditer(r'((?:conj|derived)_\$\d+)\s+#x([0-9a-fA-F]+)', expr):
            sym, hexval = m.group(1), m.group(2)
            if len(hexval) > 8 and sym not in widths:
                widths[sym] = 64
        for m in re.finditer(r'#x([0-9a-fA-F]+)\s+((?:conj|derived)_\$\d+)', expr):
            hexval, sym = m.group(1), m.group(2)
            if len(hexval) > 8 and sym not in widths:
                widths[sym] = 64
    return widths


# ---------------------------------------------------------------------------
# Build and run an SMT-LIB query via the z3 CLI
# ---------------------------------------------------------------------------

def build_smt(smt_assertions, sym_widths):
    """
    Produce a complete SMT-LIB 2 script.

    sym_widths: dict {sym_name: bit_width}
    Symbols are quoted with |...| because names contain '$'.
    """
    lines = ["(set-logic QF_BV)"]
    for sym in sorted(sym_widths.keys()):
        width = sym_widths[sym]
        lines.append(f"(declare-fun |{sym}| () (_ BitVec {width}))")
    for expr in smt_assertions:
        # Quote ALL symbol names (conj_$N and derived_$N)
        quoted = ALL_SYM_RE.sub(lambda m: f"|{m.group(0)}|", expr)
        lines.append(f"(assert {quoted})")
    lines += ["(check-sat)", "(get-model)"]
    return "\n".join(lines)


def run_z3(smt_text):
    """Write smt_text to a temp file, invoke z3, return stdout."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".smt2", delete=False) as f:
        f.write(smt_text)
        tmp = f.name
    try:
        result = subprocess.run(
            ["z3", tmp],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()
    finally:
        os.unlink(tmp)


# ---------------------------------------------------------------------------
# Parse z3 model output to extract variable values
# ---------------------------------------------------------------------------

# Matches:  (define-fun |conj_$2| () (_ BitVec 32) #x0000000b)
# or derived symbols with any bit-width
MODEL_RE = re.compile(
    r'\(define-fun\s+\|?((?:conj|derived)_\$\d+)\|?\s+\(\)\s+\(_\s+BitVec\s+(\d+)\)\s+(.*?)\)',
    re.DOTALL
)

def parse_hex(h):
    """Convert a BitVec hex literal like #x0000000b to a signed int32."""
    val = int(h[2:], 16)          # strip '#x', parse as unsigned
    return val if val < (1 << 31) else val - (1 << 32)

def parse_model_value(val_str):
    """
    Parse a z3 model value for a BitVec 32 variable.
    Handles: #xHHHHHHHH  and  (- #xHHHHHHHH) (z3 sometimes emits negation)
    """
    val_str = val_str.strip()
    if val_str.startswith("#x"):
        return parse_hex(val_str)
    # (bvneg #x...) or (- #x...) — treat as negation
    m = re.search(r'#x([0-9a-fA-F]+)', val_str)
    if m:
        raw = int(m.group(1), 16)
        # z3 may emit the two's-complement value directly; just sign-extend
        return raw if raw < (1 << 31) else raw - (1 << 32)
    return None


def extract_model(z3_output):
    """Return dict {sym_name: int_value} from z3 model output."""
    values = {}
    for m in MODEL_RE.finditer(z3_output):
        sym   = m.group(1)          # e.g. "conj_$2" or "derived_$56"
        width = int(m.group(2))     # BitVec width
        val   = parse_model_value(m.group(3))
        if val is not None:
            # Mask to unsigned value for the given width
            mask = (1 << width) - 1
            values[sym] = val & mask
    return values


# ---------------------------------------------------------------------------
# String value reconstruction from solved char symbols
# ---------------------------------------------------------------------------

# Matches "HeapSymRegion{conj_$N" in store cluster values
HEAP_SYM_RE = re.compile(r'HeapSymRegion\{(conj_\$\d+)')


def find_param_malloc_sym(state_json, param_name):
    """Return the conj_$N symbol that is the malloc result for a pointer param.

    Looks in the store section for a cluster whose name matches param_name,
    then extracts the HeapSymRegion conj symbol from the stored value.
    For example:
      cluster "out_value" → "&Element{HeapSymRegion{conj_$20{...}},0 S64b,int}"
      → returns "conj_$20"
    Supports both dict (new format) and sanitized-string (legacy format).
    Returns None if the mapping cannot be found.
    """
    if isinstance(state_json, str):
        # Legacy: sanitize and parse the raw string
        try:
            sanitized = re.sub(r'[\x00-\x1f]', ' ', state_json)
            state_json = json.loads("{" + sanitized + "}")
        except json.JSONDecodeError:
            return None
    if not isinstance(state_json, dict):
        return None
    store = state_json.get("program_state", {}).get("store", {})
    for cluster in store.get("items", []):
        if cluster.get("cluster") == param_name:
            for item in cluster.get("items", []):
                val = str(item.get("value", ""))
                m = HEAP_SYM_RE.search(val)
                if m:
                    return m.group(1)
    return None

def reconstruct_string_value(model, constraints):
    """Build a concrete string from solved derived_$N char symbols.

    The 'symbol' field in each constraint entry encodes which derived_$N
    symbol corresponds to which byte offset in the string, e.g.:
      derived_$56{...,Element{...,0 S64b,char}} -> offset 0
    We read these mappings, look up solved values in the model, and
    assemble a printable ASCII string up to the first null byte.

    Returns the string (possibly empty ""), or None if no char symbols found.
    """
    positions = {}  # {derived_sym: byte_offset}
    for c in constraints:
        sym_text = c.get("symbol", "")
        for m in DERIVED_OFFSET_RE.finditer(sym_text):
            sym    = m.group(1)
            offset = int(m.group(2))
            if sym not in positions:
                positions[sym] = offset

    if not positions:
        return None

    # Build {offset: char_value} from model
    chars = {}
    for sym, offset in positions.items():
        if sym in model:
            chars[offset] = model[sym] & 0xFF

    if not chars:
        return None

    # Reconstruct string up to null terminator, replacing non-printable with 'A'
    result = []
    for i in sorted(chars.keys()):
        val = chars[i]
        if val == 0:
            break
        result.append(chr(val) if 32 <= val <= 126 else 'A')
    return ''.join(result)


# ---------------------------------------------------------------------------
# Solve a single path
# ---------------------------------------------------------------------------

def solve_path(path):
    state_json = path.get("state_json", {})
    constraints = get_constraints(path)
    smt_exprs = [c["range"] for c in constraints]

    # Collect all symbols (conj_$N for scalars, derived_$N for string chars)
    all_syms = collect_all_symbols(smt_exprs)

    # Infer per-symbol bit-widths from expression context
    inferred_widths = infer_bitvec_widths(smt_exprs)

    # A param is scalar (Z3-solvable) iff it has a "sym" field
    scalar_params = []
    for p in path["params"]:
        if p.get("sym"):
            sym = param_sym_id(p["sym"])
            if sym:
                all_syms.add(sym)
                scalar_params.append((p, sym))

    # If no solvable symbols, emit the path with default values
    # (pointer-only functions: return value is the useful info)
    if not all_syms:
        result = {
            "path": path["path"],
            "function": path["function"],
            "return_value": path.get("return_value"),
            "inputs": []
        }
        for p in path["params"]:
            is_scalar = bool(p.get("sym"))
            result["inputs"].append({
                "name": p["name"],
                "type": p["type"],
                "value": 0 if is_scalar else None,
                "is_scalar": is_scalar,
            })
        return result

    # Build final sym→width dict (inferred, default 32 for unknowns)
    sym_widths = {s: inferred_widths.get(s, 32) for s in all_syms}

    smt_text = build_smt(smt_exprs, sym_widths)
    z3_out = run_z3(smt_text)

    if not z3_out.startswith("sat"):
        return None

    model = extract_model(z3_out)

    result = {
        "path": path["path"],
        "function": path["function"],
        "return_value": path.get("return_value"),
        "inputs": []
    }

    for p in path["params"]:
        is_scalar = bool(p.get("sym"))
        ptype = p["type"]

        if is_scalar:
            sym = param_sym_id(p["sym"])
            value = model.get(sym, 0)
        elif 'char' in ptype and '*' in ptype:
            # String pointer: reconstruct concrete string from char symbol values.
            # Returns "" for empty string, None when pointer itself is NULL.
            value = reconstruct_string_value(model, constraints)
            if value is None:
                # No derived char symbols → check if pointer should be non-null
                malloc_sym = find_param_malloc_sym(state_json, p["name"])
                if malloc_sym is not None and malloc_sym in model and model[malloc_sym] != 0:
                    value = ""  # non-null but no char constraints: use empty string
        else:
            # Non-string pointer (e.g. int *, struct *):
            # Use the store to find which conj_$N is the malloc result for this
            # param, then check the model to determine if malloc returned 0 (NULL)
            # or non-zero (a valid pointer).
            malloc_sym = find_param_malloc_sym(state_json, p["name"])
            if malloc_sym is not None and malloc_sym in model:
                # True = non-null sentinel; None = NULL
                value = None if model[malloc_sym] == 0 else True
            else:
                value = None  # can't determine → default to NULL

        result["inputs"].append({
            "name": p["name"],
            "type": ptype,
            "value": value,
            "is_scalar": is_scalar,
        })

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else "testgen_constraints.json"

    try:
        paths = load_paths(json_path)
    except FileNotFoundError:
        print(f"[error] File not found: {json_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[error] Invalid JSON in {json_path}: {e}", file=sys.stderr)
        sys.exit(1)

    if not paths:
        print(f"[warn] No paths found in {json_path}", file=sys.stderr)
        sys.exit(1)

    # print(paths)
    
    all_results = []
    for path in paths:
        result = solve_path(path)
        if result:
            all_results.append(result)
        else:
            print(f"[warn] path {path['path']} ({path['function']}) is UNSAT",
                  file=sys.stderr)

    print(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
