#!/usr/bin/env python3
"""
Generate KLEE harness files for symbolic execution.

For each public function in the source file, generate a klee_test_<func>()
driver that makes parameters symbolic with klee_make_symbolic.  All drivers
are placed in a single harness file; main() uses a symbolic 'choice' variable
to fork into each driver independently, avoiding inter-function state explosion.

Parameter handling:
  SCALAR       : klee_make_symbolic(&val, sizeof(val), "name")
  STRING_PTR   : char buf[64]; klee_make_symbolic(buf, 64, "name");
                 klee_assume(buf[63] == '\\0')          (null termination)
  SCALAR_PTR   : local variable, pass &local            (output param pattern)
  OPAQUE_PTR   : zero-initialised local struct, pass &obj
  DOUBLE_PTR   : inner pointer + outer pointer

The harness does NOT #include the source file; source.bc and harness.bc are
compiled separately and merged with llvm-link.  This keeps the coverage binary
simple (just gcc harness.c source.c ...).

Usage:
    python3 generate_klee_harness.py <source.c> <output_harness.c> [include_dir]
"""

import sys
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Re-use type helpers from generate_driver.py
# ---------------------------------------------------------------------------

SCALAR_FMT = {
    'long long':          '%lld',
    'unsigned long long': '%llu',
    'long':               '%ld',
    'unsigned long':      '%lu',
    'short':              '%hd',
    'unsigned short':     '%hu',
    'int':                '%d',
    'unsigned int':       '%u',
    'unsigned':           '%u',
    'size_t':             '%zu',
    'ptrdiff_t':          '%td',
    'float':              '%f',
    'double':             '%lf',
    'char':               '%c',
}


def scalar_fmt(t):
    t = t.strip()
    t = re.sub(r'\b(const|volatile|static|extern|register)\b', '', t).strip()
    for key, fmt in SCALAR_FMT.items():
        if t == key:
            return fmt
    return None


def strip_const(t):
    return re.sub(r'\b(const|volatile)\b', '', t).strip()


def pointer_depth(t):
    return t.count('*')


def pointee_type(t):
    t2 = t.rstrip()
    idx = t2.rfind('*')
    if idx < 0:
        return t
    return t2[:idx].strip()


class ParamKind:
    SCALAR      = 'scalar'
    STRING_PTR  = 'string_ptr'
    SCALAR_PTR  = 'scalar_ptr'
    OPAQUE_PTR  = 'opaque_ptr'
    DOUBLE_PTR  = 'double_ptr'
    UNSUPPORTED = 'unsupported'


def classify(ptype):
    t = ptype.strip()
    depth = pointer_depth(t)
    if depth == 0:
        if scalar_fmt(t) is not None:
            return ParamKind.SCALAR
        return ParamKind.UNSUPPORTED
    if depth >= 2:
        return ParamKind.DOUBLE_PTR
    base = strip_const(pointee_type(t))
    if base == 'char' or base == '':
        return ParamKind.STRING_PTR
    if base == 'void':
        return ParamKind.OPAQUE_PTR
    if scalar_fmt(base) is not None:
        return ParamKind.SCALAR_PTR
    return ParamKind.OPAQUE_PTR


# ---------------------------------------------------------------------------
# Function signature parser (identical to generate_driver.py)
# ---------------------------------------------------------------------------

def parse_function_signatures(source_code):
    pattern = (
        r'^\s*'
        r'((?:const\s+)?(?:unsigned\s+)?'
        r'(?:long\s+long|long|short|int|char|float|double|void|size_t|'
        r'ptrdiff_t|uint\w*|int\w*|ssize_t)\s*\*?)'
        r'\s+(\w+)\s*\(([^)]*)\)\s*\{'
    )
    functions = []
    seen = set()
    KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'else', 'do', 'main'}
    for m in re.finditer(pattern, source_code, re.MULTILINE):
        ret_type   = m.group(1).strip()
        func_name  = m.group(2).strip()
        params_str = m.group(3).strip()
        if func_name in KEYWORDS or func_name in seen:
            continue
        seen.add(func_name)
        params = []
        if params_str and params_str != 'void':
            for param in params_str.split(','):
                param = param.strip()
                if not param:
                    continue
                parts = param.split()
                if len(parts) >= 2:
                    raw_name   = parts[-1]
                    param_name = raw_name.lstrip('*')
                    stars      = '*' * (len(raw_name) - len(param_name))
                    param_type = ' '.join(parts[:-1]) + stars
                    params.append((param_type.strip(), param_name))
        functions.append((ret_type, func_name, params))
    return functions


# ---------------------------------------------------------------------------
# KLEE driver generation
# ---------------------------------------------------------------------------

STRING_BUF_SIZE = 64   # symbolic string buffer length (must fit in CSA/KLEE)


def generate_klee_driver(ret_type, func_name, params):
    """Return a 'static void klee_test_<func>(void) { ... }' function."""
    lines = [f"static void klee_test_{func_name}(void) {{"]
    args  = []

    for ptype, pname in params:
        kind = classify(ptype)

        if kind == ParamKind.SCALAR:
            base = strip_const(ptype)
            lines.append(f"    {base} {pname};")
            lines.append(f"    klee_make_symbolic(&{pname}, sizeof({pname}), \"{pname}\");")
            args.append(pname)

        elif kind == ParamKind.STRING_PTR:
            buf = f"_buf_{pname}"
            if 'const' in ptype:
                # Input string: make symbolic so KLEE explores character branches
                lines.append(f"    char {buf}[{STRING_BUF_SIZE}];")
                lines.append(f"    klee_make_symbolic({buf}, sizeof({buf}), \"{pname}\");")
                lines.append(f"    klee_assume({buf}[{STRING_BUF_SIZE - 1}] == '\\0');")
                lines.append(f"    const char *{pname} = {buf};")
            else:
                # Non-const char*: output buffer — allocate writable, zero-init
                lines.append(f"    char {buf}[{STRING_BUF_SIZE}];")
                lines.append(f"    memset({buf}, 0, sizeof({buf}));")
                lines.append(f"    char *{pname} = {buf};")
            args.append(pname)

        elif kind == ParamKind.SCALAR_PTR:
            # Treat as output parameter: provide a writable local, not symbolic
            base = strip_const(pointee_type(ptype))
            lv   = f"_local_{pname}"
            lines.append(f"    {base} {lv} = 0;")
            lines.append(f"    {ptype} {pname} = &{lv};")
            args.append(pname)

        elif kind == ParamKind.DOUBLE_PTR:
            inner_base = strip_const(pointee_type(pointee_type(ptype)))
            if not inner_base or inner_base == 'void':
                lines.append(f"    void *_inner_{pname} = NULL;")
                lines.append(f"    void **{pname} = &_inner_{pname};")
            else:
                lines.append(f"    {inner_base} _innerval_{pname} = 0;")
                lines.append(f"    {inner_base} *_inner_{pname} = &_innerval_{pname};")
                lines.append(f"    {inner_base} **{pname} = &_inner_{pname};")
            args.append(pname)

        elif kind == ParamKind.OPAQUE_PTR:
            base = strip_const(pointee_type(ptype))
            if base and base != 'void':
                lines.append(f"    {base} _obj_{pname};")
                lines.append(f"    memset(&_obj_{pname}, 0, sizeof(_obj_{pname}));")
                lines.append(f"    {ptype} {pname} = &_obj_{pname};")
            else:
                lines.append(f"    void *{pname} = NULL;")
            args.append(pname)

        else:  # UNSUPPORTED
            args.append("NULL")

    call_args = ", ".join(args)
    if ret_type.strip() not in ('void', ''):
        lines.append(f"    {ret_type} _r = {func_name}({call_args});")
        lines.append(f"    (void)_r;")
    else:
        lines.append(f"    {func_name}({call_args});")
    lines.append("}")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# File-level generation
# ---------------------------------------------------------------------------

def generate_harness_file(source_path, output_path, include_dir=None):
    source_path = Path(source_path).resolve()
    klee_include = Path(__file__).parent.parent / "klee" / "klee" / "include"
    if not klee_include.exists():
        # Try common alternative
        klee_include = Path("/home/yanghq/klee/klee/include")

    with open(source_path) as f:
        source_code = f.read()

    functions = parse_function_signatures(source_code)
    if not functions:
        print(f"[warn] No functions found in {source_path}", file=sys.stderr)
        return False

    # Collect project header files referenced by the source
    # (look for local includes inside the source)
    local_headers = re.findall(r'#include\s+"([^"]+)"', source_code)

    lines = []
    lines.append(f"/* KLEE harness — auto-generated from {source_path.name} */")
    lines.append(f'#include "{klee_include}/klee/klee.h"')
    lines.append("#include <stdio.h>")
    lines.append("#include <stdlib.h>")
    lines.append("#include <string.h>")
    lines.append("#include <stddef.h>")
    lines.append("#include <stdint.h>")
    lines.append("")

    # Include project headers so function declarations are visible
    if include_dir:
        inc_dir = Path(include_dir).resolve()
        lines.append(f"/* Project headers */")
        for h in local_headers:
            hpath = inc_dir / Path(h).name
            if hpath.exists():
                lines.append(f'#include "{hpath}"')
            else:
                lines.append(f'#include "{inc_dir / h}"')
    else:
        # Fall back: include headers relative to source directory
        src_dir = source_path.parent
        inc_sibling = src_dir.parent / "include"
        for h in local_headers:
            for base in (src_dir, inc_sibling, src_dir.parent):
                candidate = base / h
                if candidate.exists():
                    lines.append(f'#include "{candidate}"')
                    break

    lines.append("")

    # Generate one klee_test_* function per function found in source
    n_funcs = len(functions)
    for ret_type, func_name, params in functions:
        lines.append(generate_klee_driver(ret_type, func_name, params))
        lines.append("")

    # main(): use symbolic choice to fork into each driver independently
    lines.append("int main(void) {")
    lines.append(f"    unsigned klee_choice;")
    lines.append(f"    klee_make_symbolic(&klee_choice, sizeof(klee_choice), \"choice\");")
    lines.append(f"    klee_assume(klee_choice < {n_funcs}u);")
    lines.append(f"    switch (klee_choice) {{")
    for i, (_, func_name, _) in enumerate(functions):
        lines.append(f"        case {i}: klee_test_{func_name}(); break;")
    lines.append(f"        default: break;")
    lines.append(f"    }}")
    lines.append("    return 0;")
    lines.append("}")
    lines.append("")

    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))

    func_names = ', '.join(f[1] for f in functions)
    print(f"[klee-harness] {source_path.name} -> {Path(output_path).name}  ({func_names})")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Usage: generate_klee_harness.py <source.c> <output_harness.c> [include_dir]")
        sys.exit(1)
    ok = generate_harness_file(sys.argv[1], sys.argv[2],
                               sys.argv[3] if len(sys.argv) > 3 else None)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
