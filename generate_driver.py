#!/usr/bin/env python3
"""
Generate driver files for CSA analysis.

For each function in the source file, generate a driver that:
1. Declares / allocates variables for each parameter
2. Uses scanf to mark scalar and pointer-pointee values as external symbolic inputs
3. Calls the target function
4. Frees any malloc'd pointers to avoid memory leaks

Pointer handling strategy:
  - const char * / char *  : malloc a string buffer, read via scanf %s
  - T * (scalar pointee)   : malloc sizeof(T), read the value via scanf
  - void * / other ptr     : malloc a fixed-size anonymous buffer, zero-initialised
  - T ** (double pointer)  : malloc one pointer slot pointing to a malloc'd T buffer

IMPORTANT: Driver and target must be in the same compilation unit so CSA
can track conjured symbols (conj_$N) through the call. This script embeds
the original source file content via #include.

Usage:
    python3 generate_driver.py <source.c> <output_driver.c> [include_dir]
"""

import sys
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Type helpers
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
    """Return scanf format for a plain scalar type string, or None."""
    t = t.strip()
    # strip const / static / etc.
    t = re.sub(r'\b(const|volatile|static|extern|register)\b', '', t).strip()
    for key, fmt in SCALAR_FMT.items():
        if t == key:
            return fmt
    return None


def strip_const(t):
    return re.sub(r'\b(const|volatile)\b', '', t).strip()


def pointer_depth(t):
    """Count the number of * in a type string."""
    return t.count('*')


def pointee_type(t):
    """Remove one level of pointer from a type: 'int *' -> 'int'."""
    # remove last * (possibly with spaces around it)
    t2 = t.rstrip()
    idx = t2.rfind('*')
    if idx < 0:
        return t
    return t2[:idx].strip()


# ---------------------------------------------------------------------------
# Param classification
# ---------------------------------------------------------------------------

class ParamKind:
    SCALAR       = 'scalar'        # plain int / long / size_t / float …
    STRING_PTR   = 'string_ptr'    # char * or const char *  (read as string)
    SCALAR_PTR   = 'scalar_ptr'    # int *, size_t *, long *, …
    OPAQUE_PTR   = 'opaque_ptr'    # void * or unknown struct *
    DOUBLE_PTR   = 'double_ptr'    # T ** (output-pointer pattern)
    UNSUPPORTED  = 'unsupported'   # function pointers, etc.


def classify(ptype):
    t = ptype.strip()
    depth = pointer_depth(t)

    if depth == 0:
        if scalar_fmt(t) is not None:
            return ParamKind.SCALAR
        return ParamKind.UNSUPPORTED

    if depth >= 2:
        return ParamKind.DOUBLE_PTR

    # depth == 1
    base = strip_const(pointee_type(t))
    if base == 'char' or base == '':
        return ParamKind.STRING_PTR
    if base == 'void':
        return ParamKind.OPAQUE_PTR
    if scalar_fmt(base) is not None:
        return ParamKind.SCALAR_PTR
    return ParamKind.OPAQUE_PTR


# ---------------------------------------------------------------------------
# Driver code generation
# ---------------------------------------------------------------------------

STRING_BUF_SIZE = 256   # fixed capacity for string / opaque buffers


def generate_driver(ret_type, func_name, params):
    """
    Return a string containing the complete driver_<func_name> function.

    Layout:
        static void driver_<name>(void) {
            /* --- declarations --- */
            /* --- scanf calls    --- */
            /* --- function call  --- */
            /* --- free calls     --- */
        }
    """
    decls       = []   # variable declarations / mallocs (before scanf)
    post_decls  = []   # declarations that depend on scanf result (e.g. malloc from read string)
    scanfs      = []   # scanf lines (scalar fmt, addr)
    frees       = []   # free() calls
    args        = []   # argument expressions for the target call

    for ptype, pname in params:
        kind = classify(ptype)

        if kind == ParamKind.SCALAR:
            fmt = scalar_fmt(strip_const(ptype))
            decls.append(f"    {ptype} {pname};")
            scanfs.append((fmt, f"&{pname}"))
            args.append(pname)

        elif kind == ParamKind.STRING_PTR:
            # Read string input first (stack buffer), then heap-copy it.
            # The heap copy gives CSA a proper MemRegion to reason about,
            # and the scanf call makes the contents externally controlled.
            buf_var = f"{pname}_buf"
            # Step 1: stack buffer + scanf (tracked via scanfs list, emitted together)
            decls.append(f"    char {buf_var}[{STRING_BUF_SIZE}] = {{0}};")
            scanfs.append((f"%{STRING_BUF_SIZE - 1}s", buf_var))
            # Step 2: heap-copy after scanf — tagged with a sentinel so we can
            # reorder the emit: we record these as "post_scanf_decls"
            post_decls.append(f"    char *{pname} = (char *)malloc(strlen({buf_var}) + 1);")
            post_decls.append(f"    if ({pname}) strcpy({pname}, {buf_var});")
            frees.append(f"    free({pname});")
            args.append(pname)

        elif kind == ParamKind.SCALAR_PTR:
            # malloc one element; read its value via scanf; pass the pointer.
            base = strip_const(pointee_type(ptype))
            fmt  = scalar_fmt(base)
            val_var = f"{pname}_val"
            decls.append(f"    {base} {val_var};")
            scanfs.append((fmt, f"&{val_var}"))
            # post_decls: malloc + assign after scanf so *ptr = read value
            post_decls.append(f"    {base} *{pname} = ({base} *)malloc(sizeof({base}));")
            post_decls.append(f"    if ({pname}) *{pname} = {val_var};")
            frees.append(f"    free({pname});")
            args.append(pname)

        elif kind == ParamKind.DOUBLE_PTR:
            # T ** : allocate a T*, point it at a malloc'd T, pass &inner_ptr.
            inner_base = strip_const(pointee_type(pointee_type(ptype)))
            if not inner_base or inner_base == 'void':
                inner_base = 'void'
                decls.append(f"    void *{pname}_inner = malloc({STRING_BUF_SIZE});")
                decls.append(f"    void *{pname}_ptr   = {pname}_inner;")
                decls.append(f"    void **{pname}      = &{pname}_ptr;")
                frees.append(f"    free({pname}_inner);")
            else:
                fmt = scalar_fmt(inner_base)
                if fmt:
                    val_var = f"{pname}_val"
                    decls.append(f"    {inner_base} {val_var};")
                    scanfs.append((fmt, f"&{val_var}"))
                    decls.append(f"    {inner_base} *{pname}_inner = ({inner_base} *)malloc(sizeof({inner_base}));")
                    decls.append(f"    if ({pname}_inner) *{pname}_inner = {val_var};")
                    decls.append(f"    {inner_base} **{pname} = &{pname}_inner;")
                    frees.append(f"    free({pname}_inner);")
                else:
                    # opaque inner type: zero-initialised buffer
                    decls.append(f"    {inner_base} *{pname}_inner = ({inner_base} *)calloc(1, sizeof({inner_base}));")
                    decls.append(f"    {inner_base} **{pname} = &{pname}_inner;")
                    frees.append(f"    free({pname}_inner);")
            args.append(pname)

        elif kind == ParamKind.OPAQUE_PTR:
            # Unknown pointee: provide a zero-initialised heap buffer.
            base = strip_const(pointee_type(ptype))
            if base and base != 'void':
                decls.append(f"    {base} *{pname} = ({base} *)calloc(1, sizeof({base}));")
            else:
                decls.append(f"    void *{pname} = calloc(1, {STRING_BUF_SIZE});")
            frees.append(f"    free({pname});")
            args.append(pname)

        else:  # UNSUPPORTED (function pointers, etc.)
            args.append("NULL")

    # ---- assemble function body ----
    lines = [f"static void driver_{func_name}(void) {{"]

    lines.extend(decls)

    if scanfs:
        fmt_str = ' '.join(s[0] for s in scanfs)
        addr_list = ', '.join(s[1] for s in scanfs)
        lines.append(f'    scanf("{fmt_str}", {addr_list});')

    lines.extend(post_decls)

    call_args = ', '.join(args)
    if ret_type.strip() not in ('void', ''):
        lines.append(f"    {ret_type} _r = {func_name}({call_args});")
        lines.append(f"    (void)_r;")
    else:
        lines.append(f"    {func_name}({call_args});")

    lines.extend(frees)
    lines.append("}")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Function signature parser
# ---------------------------------------------------------------------------

def parse_function_signatures(source_code):
    """Extract top-level function definitions. Returns list of (ret_type, name, params)."""
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
# File-level generation
# ---------------------------------------------------------------------------

def generate_driver_file(source_path, output_path, include_dir=None):
    source_path = Path(source_path)
    with open(source_path) as f:
        source_code = f.read()

    functions = parse_function_signatures(source_code)
    if not functions:
        print(f"[warn] No functions found in {source_path}", file=sys.stderr)
        return False

    abs_src = source_path.resolve()
    # Locate the stubs header relative to this script's directory.
    stubs_path = (Path(__file__).parent / "stubs" / "lib_stubs.h").resolve()

    lines = []
    lines.append("#include <stdio.h>")
    lines.append("#include <stdlib.h>")   # malloc / free / calloc
    lines.append("#include <string.h>")   # strlen / strcpy
    lines.append("#include <stddef.h>")
    lines.append("#include <stdint.h>")
    lines.append("#include <ctype.h>")    # pull in system ctype first so stubs can #undef macros
    lines.append("")
    # Inject library function summaries (active only under __clang_analyzer__).
    # Must come AFTER system headers (so the macros exist to #undef) and BEFORE
    # the target source so calls inside it resolve to our explicit stubs.
    if stubs_path.exists():
        lines.append(f'#include "{stubs_path}"')
        lines.append("")
    # Embed original source in the same TU so CSA sees both driver and target.
    lines.append(f'#include "{abs_src}"')
    lines.append("")

    for ret_type, func_name, params in functions:
        lines.append(generate_driver(ret_type, func_name, params))
        lines.append("")

    lines.append("int main(void) {")
    for _, func_name, _ in functions:
        lines.append(f"    driver_{func_name}();")
    lines.append("    return 0;")
    lines.append("}")
    lines.append("")

    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))

    func_names = ', '.join(f[1] for f in functions)
    print(f"[driver] {source_path.name} -> {Path(output_path).name}  ({func_names})")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Usage: generate_driver.py <source.c> <output_driver.c> [include_dir]")
        sys.exit(1)
    ok = generate_driver_file(sys.argv[1], sys.argv[2],
                              sys.argv[3] if len(sys.argv) > 3 else None)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
