#!/usr/bin/env python3
"""
Generate C unit test code from test_inputs.json (produced by solve.py).

Usage:
    python3 codegen.py test_inputs.json [output_test.c] [include_dir]
"""

import json
import sys
import os
from collections import defaultdict

# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------

UNSIGNED_TYPES = {
    "unsigned int", "unsigned long", "unsigned long long",
    "unsigned short", "unsigned char",
    "size_t", "uint8_t", "uint16_t", "uint32_t", "uint64_t",
}

def is_pointer(type_str):
    return "*" in type_str

def c_literal(value, type_str):
    """Format a value as a C literal appropriate for the type."""
    if value is None:
        return "NULL"
    t = type_str.strip()
    v = int(value)
    if t in UNSIGNED_TYPES or "unsigned" in t or "uint" in t:
        v = max(0, v)
        return f"({t}){v}U" if v != 0 else f"({t})0"
    return str(v)

def pointee_type_str(type_str):
    """Return the base type for a single-level pointer, e.g. 'int *' -> 'int'."""
    t = type_str.strip()
    idx = t.rfind('*')
    return t[:idx].strip() if idx >= 0 else t

def arg_for_param(inp):
    """Return the C argument string for a parameter."""
    val = inp.get("value")
    # String pointer with a concrete string value from Z3
    if isinstance(val, str):
        escaped = val.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    # Non-null pointer sentinel (True): pass address of a local variable
    if val is True:
        return f"&_local_{inp['name']}"
    if not inp.get("is_scalar", True) or is_pointer(inp["type"]):
        return "NULL"
    return c_literal(val, inp["type"])


# ---------------------------------------------------------------------------
# Header map: function -> header file
# ---------------------------------------------------------------------------

FUNCTION_HEADER_MAP = {
    "clamp_int":              "utils.h",
    "ascii_sum":              "utils.h",
    "parse_positive_int":     "utils.h",
    "split_kv":               "utils.h",
    "parse_sensor_line":      "parser.h",
    "classify_record":        "parser.h",
    "parse_payload_packet":   "parser.h",
    "decode_rle_frame":       "decoder.h",
    "tp_rle_decompress":      "third_party_adapter.h",
    "mz_stub_rle_decompress": "miniz_stub.h",
}

def headers_for_functions(func_names, include_dir=None):
    seen = set()
    result = []
    for fn in func_names:
        h = FUNCTION_HEADER_MAP.get(fn)
        if h and h not in seen:
            seen.add(h)
            # Don't prepend include_dir in the #include directive
            # The compiler will find it via -I flags
            result.append(h)
    return result


# ---------------------------------------------------------------------------
# Deduplication: for pointer-param functions keep one path per return value
# ---------------------------------------------------------------------------

def has_pointer_params(path_entry):
    return any(is_pointer(inp["type"]) for inp in path_entry["inputs"])

def all_params_are_pointers(path_entry):
    return all(
        not inp.get("is_scalar", True) or is_pointer(inp["type"])
        for inp in path_entry["inputs"]
    )

def has_meaningful_scalar_constraints(path_entry):
    """
    Returns True if any scalar param has a non-zero value (i.e., Z3 found
    a concrete non-trivial value, meaning there are real constraints).
    """
    for inp in path_entry["inputs"]:
        if inp.get("is_scalar") and not is_pointer(inp["type"]):
            if inp.get("value") not in (None, 0):
                return True
    return False

def effective_args_key(path_entry):
    """Return a hashable key for deduplication — same input args = same test case.
    Does NOT include return_value: for a deterministic function, identical inputs
    must produce the same output, so we keep only the first path per unique arg set.
    """
    parts = []
    for i in path_entry["inputs"]:
        val = i.get("value")
        if isinstance(val, str):
            parts.append(f'"{val}"')
        elif val is True:
            parts.append(f"&{i['name']}")
        elif i.get("is_scalar") and not is_pointer(i["type"]):
            parts.append(str(val))
        else:
            parts.append("NULL")
    return (path_entry["function"], tuple(parts))

def deduplicate(paths):
    """
    Two-stage deduplication:
    1. Remove paths whose effective call (args + return_value) is identical to
       a previously seen path — these would generate duplicate ASSERT_EQ lines.
    2. For paths with only NULL/default inputs (no concrete constraint info),
       keep only one per function (the null-guard -1 path).
    """
    seen_calls = set()
    null_guard_seen = set()
    result = []
    for p in paths:
        # Stage 1: skip exact duplicate calls
        key = effective_args_key(p)
        if key in seen_calls:
            continue
        seen_calls.add(key)

        # Stage 2: for all-null/default paths, keep only the -1 null-guard once
        has_concrete = (
            any(isinstance(inp.get("value"), str) for inp in p["inputs"])  # string literal
            or has_meaningful_scalar_constraints(p)
            or any(inp.get("value") is True for inp in p["inputs"])  # non-null ptr
        )
        if not has_concrete:
            fn = p["function"]
            rv = p.get("return_value")
            if rv == -1 and fn not in null_guard_seen:
                null_guard_seen.add(fn)
                result.append(p)
            # else: skip (can't distinguish from other all-null paths)
        else:
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

HARNESS = """\
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>

/* ---- project headers ---- */
{includes}

/* ---- minimal test harness ---- */
static int g_pass = 0, g_fail = 0;

#define ASSERT_EQ(got, expected, id) do {{ \\
    long long _g = (long long)(got); \\
    long long _e = (long long)(expected); \\
    if (_g == _e) {{ \\
        g_pass++; \\
    }} else {{ \\
        fprintf(stderr, "FAIL test %d: got %lld, expected %lld\\n", (id), _g, _e); \\
        g_fail++; \\
    }} \\
}} while(0)

"""

def gen_test_call(path_entry, test_index):
    fn = path_entry["function"]
    inputs = path_entry["inputs"]
    ret = path_entry.get("return_value")

    # Declare local variables for non-null pointer params (value=True sentinel).
    # Wrap in a block scope so repeated declarations don't clash.
    local_decls = []
    for i in inputs:
        if i.get("value") is True:
            base = pointee_type_str(i["type"])
            local_decls.append(f"        {base} _local_{i['name']} = {{0}};")

    args = ", ".join(arg_for_param(i) for i in inputs)
    comment_args = ", ".join(
        (f'"{i["value"]}"' if isinstance(i.get("value"), str)
         else f"&{i['name']}" if i.get("value") is True
         else str(i["value"]) if i.get("is_scalar") and not is_pointer(i["type"])
         else "NULL")
        for i in inputs
    )
    comment = f"/* path {path_entry['path']}: {fn}({comment_args})"
    if ret is not None:
        comment += f" -> {ret}"
    comment += " */"

    if local_decls:
        # Use a block scope to allow repeated declarations across test calls
        lines = [f"    {comment}", "    {"]
        lines.extend(local_decls)
        if ret is not None:
            lines.append(f"        ASSERT_EQ({fn}({args}), {ret}, {test_index});")
        else:
            lines.append(f"        (void){fn}({args}); /* no return value captured */")
        lines.append("    }")
    else:
        lines = [f"    {comment}"]
        if ret is not None:
            lines.append(f"    ASSERT_EQ({fn}({args}), {ret}, {test_index});")
        else:
            lines.append(f"    (void){fn}({args}); /* no return value captured */")
    return "\n".join(lines)


def is_public_function(func_name):
    """
    Return True if func_name should have tests generated for it.

    Two categories are excluded:
      1. Names starting with '__' — C reserved identifiers and our __csa_*
         stub helpers.  These are defined only under __clang_analyzer__ and
         do not exist in normal compilation.
      2. Names absent from FUNCTION_HEADER_MAP (when the map is non-empty) —
         these are typically static / file-scope helpers (e.g. parse_field)
         that CSA analyses because they share the driver's translation unit
         but cannot be called from an external test file.
    """
    if func_name.startswith("__"):
        return False
    if FUNCTION_HEADER_MAP and func_name not in FUNCTION_HEADER_MAP:
        return False
    return True


def generate(test_inputs, include_dir=None):
    paths = deduplicate(test_inputs)

    by_func = defaultdict(list)
    skipped = set()
    for p in paths:
        fn = p["function"]
        if not is_public_function(fn):
            skipped.add(fn)
            continue
        by_func[fn].append(p)

    if skipped:
        import sys
        print(f"[codegen] Skipped {len(skipped)} non-public function(s): "
              f"{', '.join(sorted(skipped))}", file=sys.stderr)

    headers = headers_for_functions(list(by_func.keys()), include_dir)
    include_lines = "\n".join(f'#include "{h}"' for h in headers)

    out = [HARNESS.format(includes=include_lines)]

    for fn, fn_paths in by_func.items():
        out.append(f"static void test_{fn}(void) {{")
        out.append(f"    /* {len(fn_paths)} path(s) for {fn} */")
        for p in fn_paths:
            out.append(gen_test_call(p, p["path"]))
        out.append("}")
        out.append("")

    out.append("int main(void) {")
    for fn in by_func:
        out.append(f"    test_{fn}();")
    out.append('    printf("Results: %d passed, %d failed\\n", g_pass, g_fail);')
    out.append("    return g_fail > 0 ? 1 : 0;")
    out.append("}")
    out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: codegen.py <test_inputs.json> [output.c] [include_dir]")
        sys.exit(1)

    json_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "test_autogen.c"
    include_dir = sys.argv[3] if len(sys.argv) > 3 else None

    with open(json_path) as f:
        test_inputs = json.load(f)

    if not test_inputs:
        print("[warn] No test inputs found", file=sys.stderr)
        sys.exit(1)

    deduped = deduplicate(test_inputs)
    code = generate(test_inputs, include_dir)

    with open(output_path, "w") as f:
        f.write(code)

    print(f"Generated {output_path} ({len(test_inputs)} paths -> {len(deduped)} after dedup)")


if __name__ == "__main__":
    main()
