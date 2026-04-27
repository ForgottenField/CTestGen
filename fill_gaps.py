#!/usr/bin/env python3
"""
fill_gaps.py — LLM-based test gap filling driven by coverage_data.json.

Strategy: function-granularity prompts + outer measure→fill→remeasure loop.
  - One LLM call per function (covering all uncovered branches in that function).
  - After each round, coverage is re-measured; unchanged coverage stops the loop.
  - Terminates when: all branches covered | no progress | max_iter reached.

Usage:
    python3 fill_gaps.py \\
        <coverage_data.json>   \\
        [--model MODEL]        \\
        [--max-retries N]      \\
        [--max-iter N]         \\
        [--dry-run]

Environment:
    ANTHROPIC_API_KEY   Required (skipped in --dry-run mode)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import _cov_utils as cov
from llm_client import LLMClient


DEFAULT_MODEL  = "claude-sonnet-4-6"
MAX_RETRIES    = 3
MAX_ITER       = 3


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert C unit-test engineer. Your job is to generate test inputs \
that cover MULTIPLE uncovered branches in the provided C function.

Rules:
1. Respond ONLY with a JSON object — no prose, no markdown fences.
2. The JSON must have "test_cases": a list. Each element:
   - "target_line": the line number (int) this test is designed to reach
   - "inputs": list of parameter objects, each with:
       "name": parameter name (string)
       "type": C type (string)
       "value": concrete value
         * scalar (int, size_t, …): a JSON number
         * char* / const char*: a JSON string (content only, no quotes)
         * pointer to scalar: null (NULL) or true (non-null, use &local)
   - "expected_return": integer the function returns, or null if void
3. Generate ONE test case per listed uncovered branch.
   You may generate fewer only if a branch is truly unreachable.
4. Each test MUST cause execution to reach its target_line.
5. Your entire response must be valid JSON parseable by json.loads().
   No text outside the JSON object.

Example response:
{"test_cases": [
  {"target_line": 31, "inputs": [{"name": "s", "type": "const char *", "value": null}], "expected_return": -1},
  {"target_line": 40, "inputs": [{"name": "s", "type": "const char *", "value": "1000001"}, {"name": "out_value", "type": "int *", "value": true}], "expected_return": -3}
]}
"""


def collect_callee_sources(func_name, func_source, all_source_files):
    """
    Find the source bodies of functions called inside func_source.

    Scans func_source for identifiers that look like function calls, then
    searches all_source_files for matching function definitions.  Returns a
    dict {callee_name: callee_source_text}, excluding func_name itself.
    """
    call_names = set(re.findall(r'\b([a-zA-Z_]\w*)\s*\(', func_source))
    call_names.discard(func_name)  # exclude self-reference

    callee_map = {}
    for src_path in all_source_files:
        try:
            src_text = Path(src_path).read_text()
        except OSError:
            continue
        for fname, _start, _end, fsrc in cov.extract_functions(src_text):
            if fname in call_names and fname not in callee_map:
                callee_map[fname] = fsrc

    return callee_map


def build_prompt(func_name, func_source, branches, existing_tests, callee_sources=None):
    """
    Build a multi-branch prompt for one function.
    branches: list of {"line": int, "source_line": str}
    callee_sources: dict {name: source} of functions called by func_source
    """
    parts = [
        f"Function under test: {func_name}",
        "",
        "Source:",
        "```c",
        func_source,
        "```",
        "",
    ]

    if callee_sources:
        parts += [
            "Called functions (for context — you must understand these to construct "
            "inputs that reach the target branches):",
            "",
        ]
        for cname, csrc in callee_sources.items():
            parts += [
                f"// {cname}",
                "```c",
                csrc,
                "```",
                "",
            ]

    parts += [
        "Uncovered branches — generate one test input per branch:",
    ]
    for b in branches:
        parts.append(f"  - Line {b['line']}: `{b['source_line']}`")
    parts.append("")
    if existing_tests:
        parts += [
            "Existing test cases for this function (for reference):",
            existing_tests,
            "",
        ]
    parts.append(
        'Return JSON: {"test_cases": [{"target_line": N, "inputs": [...], '
        '"expected_return": int|null}, ...]}'
    )
    return "\n".join(parts)


def call_llm(prompt, client: LLMClient) -> str:
    """Call the LLM and return raw text response."""
    return client.chat(system=SYSTEM_PROMPT, user=prompt)


def parse_llm_response(text):
    """Return list of test-case dicts, or None on parse failure."""
    text = re.sub(r'^```[a-z]*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n?```$',       '', text, flags=re.MULTILINE)
    text = text.strip()

    def _extract(s):
        try:
            data = json.loads(s)
            if "test_cases" in data and isinstance(data["test_cases"], list):
                return data["test_cases"]
        except json.JSONDecodeError:
            pass
        return None

    result = _extract(text)
    if result is not None:
        return result
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        return _extract(m.group(0))
    return None


# ---------------------------------------------------------------------------
# Existing test extraction
# ---------------------------------------------------------------------------

def extract_existing_tests(test_c_text, func_name):
    pattern = re.compile(
        rf'static void test_{re.escape(func_name)}\s*\(void\)\s*\{{(.*?)\n\}}',
        re.DOTALL
    )
    m = pattern.search(test_c_text)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# C argument helpers
# ---------------------------------------------------------------------------

def _c_arg(inp):
    val  = inp.get("value")
    typ  = inp.get("type", "int")
    name = inp.get("name", "x")
    if val is None:
        return "NULL"
    if val is True or isinstance(val, dict):
        return f"&_probe_{name}"
    if isinstance(val, list):
        return f"_probe_{name}"
    if isinstance(val, str):
        escaped = val.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    if "unsigned" in typ or typ in ("size_t", "uint8_t", "uint16_t",
                                     "uint32_t", "uint64_t"):
        return f"({typ}){int(val)}U"
    return str(int(val))


def _local_decl(inp):
    val  = inp.get("value")
    typ  = inp.get("type", "int")
    name = inp.get("name", "x")
    if val is True or isinstance(val, dict):
        base = typ.rstrip().rstrip('*').strip()
        return f"{base} _probe_{name} = {{0}};"
    if isinstance(val, list):
        # e.g. uint8_t _probe_compressed[] = {2, 65, 1, 10};
        base = typ.rstrip().rstrip('*').strip()
        elems = ", ".join(str(int(x)) for x in val)
        return f"{base} _probe_{name}[] = {{{elems}}};"
    return None


def _args_summary(llm_data):
    parts = []
    for inp in llm_data.get("inputs", []):
        v = inp.get("value")
        if isinstance(v, str):
            parts.append(f'"{v}"')
        elif v is None:
            parts.append("NULL")
        elif v is True:
            parts.append(f"&{inp['name']}")
        elif isinstance(v, list):
            parts.append(f"{{{', '.join(str(x) for x in v)}}}")
        else:
            parts.append(str(v))
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Probe compilation & validation
# ---------------------------------------------------------------------------

def _resolve_list_sizes(inputs):
    """
    When a parameter value is a list (e.g. uint8_t[] byte array), the
    adjacent *_len / *_size parameter should match len(list).  If the LLM
    left that parameter as 0 or didn't give the right value, fix it here.

    Strategy: for each list-valued param at index k, look forward/backward
    for the nearest size_t param whose name contains "len", "size", or "cap"
    and whose current value is 0 or doesn't match; update it to len(list).
    """
    inputs = [dict(i) for i in inputs]  # shallow copy so we don't mutate caller's data
    for k, inp in enumerate(inputs):
        val = inp.get("value")
        if not isinstance(val, list):
            continue
        array_len = len(val)
        # Search neighbors for a matching size parameter
        for j in range(len(inputs)):
            if j == k:
                continue
            other = inputs[j]
            oname = other.get("name", "").lower()
            otyp  = other.get("type", "").lower()
            if ("len" in oname or "size" in oname or "cap" in oname or
                    "count" in oname) and "size_t" in otyp:
                if other.get("value") in (0, None, True):
                    other["value"] = array_len
                    break
    return inputs


PROBE_TEMPLATE = """\
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>

{includes}

int main(void) {{
    {local_decls}
    {call_expr};
    return 0;
}}
"""

RETVAL_TEMPLATE = """\
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>

{includes}

int main(void) {{
    {local_decls}
    long long _r = (long long){func}({args});
    printf("%lld\\n", _r);
    return 0;
}}
"""


def _build_probe(func_name, llm_data, header_includes):
    inputs = _resolve_list_sizes(llm_data.get("inputs", []))
    local_decls = [d for d in (_local_decl(i) for i in inputs) if d]
    args = ", ".join(_c_arg(i) for i in inputs)
    ret  = llm_data.get("expected_return")
    call_expr = f"(void){func_name}({args})" if ret is not None else f"{func_name}({args})"
    includes_str = "\n".join(f'#include "{h}"' for h in header_includes)
    return PROBE_TEMPLATE.format(
        includes=includes_str,
        local_decls="\n    ".join(local_decls) if local_decls else "",
        call_expr=call_expr,
    )


def validate_candidate(func_name, llm_data, source_file, header_includes,
                        includes_flags, extra_flags, work_dir, target_line):
    """Compile + run a probe; re-run gcov; return True if target_line is now covered."""
    probe_src = _build_probe(func_name, llm_data, header_includes)
    probe_c   = os.path.join(work_dir, "probe.c")
    probe_bin = os.path.join(work_dir, "probe_bin")

    Path(probe_c).write_text(probe_src)

    r = subprocess.run(
        ["gcc", "--coverage", "-fno-inline", "-O0", "-g",
         *extra_flags, *includes_flags,
         probe_c, source_file, "-o", probe_bin],
        capture_output=True, text=True, cwd=work_dir,
    )
    if r.returncode != 0:
        return False

    subprocess.run([probe_bin], capture_output=True, cwd=work_dir)

    stem = Path(source_file).stem
    gcno_candidates = list(Path(work_dir).glob(f"*-{stem}.gcno"))
    if not gcno_candidates:
        gcno_candidates = list(Path(work_dir).glob(f"{stem}.gcno"))
    gcno_arg = gcno_candidates[0].name if gcno_candidates else source_file
    subprocess.run(["gcov", "-b", "-c", gcno_arg],
                   capture_output=True, cwd=work_dir)

    gcov_file = Path(work_dir) / (Path(source_file).name + ".gcov")
    if not gcov_file.exists():
        alt = Path(work_dir) / (stem + ".c.gcov")
        gcov_file = alt if alt.exists() else None
    if gcov_file is None:
        return False

    for line in gcov_file.read_text().splitlines():
        m = re.match(rf'^\s*(\d+):\s*{target_line}:', line)
        if m and int(m.group(1)) > 0:
            return True
    return False


def validate_return_value(func_name, llm_data, source_file, header_includes,
                           includes_flags, extra_flags, work_dir):
    """Compile + run a probe that captures the actual return value."""
    inputs = _resolve_list_sizes(llm_data.get("inputs", []))
    local_decls = [d for d in (_local_decl(i) for i in inputs) if d]
    args = ", ".join(_c_arg(i) for i in inputs)
    includes_str = "\n".join(f'#include "{h}"' for h in header_includes)

    probe_src = RETVAL_TEMPLATE.format(
        includes=includes_str,
        local_decls="  ".join(local_decls) if local_decls else "",
        func=func_name,
        args=args,
    )
    probe_c   = os.path.join(work_dir, "ret_probe.c")
    probe_bin = os.path.join(work_dir, "ret_probe_bin")
    Path(probe_c).write_text(probe_src)

    r = subprocess.run(
        ["gcc", "-O0", "-g", *extra_flags, *includes_flags,
         probe_c, source_file, "-o", probe_bin],
        capture_output=True, text=True, cwd=work_dir,
    )
    if r.returncode != 0:
        return None
    r2 = subprocess.run([probe_bin], capture_output=True, text=True)
    try:
        return int(r2.stdout.strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Append validated test cases to test_autogen.c
# ---------------------------------------------------------------------------

def _next_llm_test_id(test_c_path):
    """Return the next available LLM test ID (>= 90000), avoiding collisions."""
    text = Path(test_c_path).read_text()
    # Match the trailing test-ID argument: ASSERT_EQ(..., 9XXXX);
    ids = [int(m) for m in re.findall(r',\s*(9\d{4,})\s*\)\s*;', text)]
    return max(ids, default=89999) + 1


def append_llm_tests(test_c_path, func_name, new_cases):
    """
    Insert LLM-generated ASSERT_EQ lines into the test_<func_name>() function.
    new_cases: list of (llm_data dict, expected_return int|None)
    """
    text = Path(test_c_path).read_text()
    next_id = _next_llm_test_id(test_c_path)
    additions = []

    for idx, (llm_data, ret) in enumerate(new_cases):
        inputs = _resolve_list_sizes(llm_data.get("inputs", []))
        local_decls = [f"        {d}" for d in
                       (_local_decl(i) for i in inputs) if d]
        args = ", ".join(_c_arg(i) for i in inputs)
        comment_args = ", ".join(
            f'"{i["value"]}"'    if isinstance(i.get("value"), str)
            else "NULL"          if i.get("value") is None
            else f"&{i['name']}" if i.get("value") is True
            else str(i["value"])
            for i in inputs
        )
        comment = f"    /* [llm] {func_name}({comment_args})"
        if ret is not None:
            comment += f" -> {ret}"
        comment += " */"
        test_id = next_id + idx

        if local_decls:
            block = [comment, "    {"]
            block.extend(local_decls)
            if ret is not None:
                block.append(f'        ASSERT_EQ({func_name}({args}), {ret}, {test_id});')
            else:
                block.append(f"        (void){func_name}({args});")
            block.append("    }")
        else:
            block = [comment]
            if ret is not None:
                block.append(f'    ASSERT_EQ({func_name}({args}), {ret}, {test_id});')
            else:
                block.append(f"    (void){func_name}({args});")
        additions.extend(block)

    if not additions:
        return

    pattern = re.compile(
        r'(static void test_' + re.escape(func_name) + r'\s*\(void\)\s*\{.*?)\n(\})',
        re.DOTALL
    )
    insert_block = "\n".join(additions)

    def replacer(m):
        return m.group(1) + "\n" + insert_block + "\n" + m.group(2)

    Path(test_c_path).write_text(pattern.sub(replacer, text, count=1))


# ---------------------------------------------------------------------------
# Re-measure coverage in-process (no subprocess, uses _cov_utils directly)
# ---------------------------------------------------------------------------

def _remeasure(data):
    """
    Re-compile test_autogen.c with gcov and re-parse uncovered branches.
    Returns (uncovered_branches, branches_covered_total) or (None, 0) on failure.
    branches_covered_total is used for convergence detection.
    """
    # Remove probe artefacts so run_gcov picks test_cov-*.gcno, not probe_bin-*.gcno
    work = Path(data["work_dir"])
    for pattern in ("probe*", "ret_probe*"):
        for f in work.glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass

    bin_path = cov.compile_with_coverage(
        data["test_c"], data["link_sources"],
        data["includes_flags"], data["extra_flags"],
        data["work_dir"],
    )
    if bin_path is None:
        return None, 0
    cov.run_binary(bin_path, data["work_dir"])

    uncovered = []
    branches_covered = 0
    for src in data["analysis_sources"]:
        gcov_text = cov.run_gcov(src, data["work_dir"])
        if gcov_text:
            uncovered.extend(cov.parse_uncovered_branches(gcov_text, src))
            stats = cov.parse_coverage_stats(gcov_text)
            branches_covered += stats["branches_covered"]
    return uncovered, branches_covered


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("coverage_json",
                    help="coverage_data.json produced by measure_coverage.py")
    ap.add_argument("--model",       default=DEFAULT_MODEL,
                    help=f"Claude model ID (default: {DEFAULT_MODEL})")
    ap.add_argument("--max-iter",    type=int, default=MAX_ITER,    dest="max_iter",
                    help="Maximum measure→fill rounds (default: 3)")
    ap.add_argument("--dry-run",     action="store_true",
                    help="Report uncovered branches only; skip LLM calls")
    args = ap.parse_args()

    with open(args.coverage_json) as f:
        data = json.load(f)

    test_c             = data["test_c"]
    includes_flags     = data["includes_flags"]
    extra_flags        = data["extra_flags"]
    work_dir           = data["work_dir"]
    header_includes    = data["header_includes"]
    header_dirs        = data["header_dirs"]
    uncovered_branches = data["uncovered_branches"]
    all_source_files   = data.get("link_sources", [])

    if not uncovered_branches:
        print("[fill_gaps] No uncovered branches — nothing to do.")
        return

    full_headers = [cov.find_header(h, header_dirs) for h in header_includes]

    # --- LLM client ---
    client = None
    if not args.dry_run:
        try:
            model_override = args.model if args.model != DEFAULT_MODEL else None
            client = LLMClient(
                **({"model": model_override} if model_override else {}),
            )
            # Eagerly validate key / dependencies before the loop starts
            client._get_client()
        except RuntimeError as e:
            print(f"[fill_gaps] {e}", file=sys.stderr)
            sys.exit(1)

    os.makedirs(work_dir, exist_ok=True)

    total_added              = 0
    total_skipped            = 0
    prev_covered             = -1   # branches_covered from previous round (-1 = none yet)
    branches_covered_this_round = 0

    # -----------------------------------------------------------------------
    # Outer loop: measure → fill → re-measure, until convergence or max_iter
    # -----------------------------------------------------------------------
    for iteration in range(1, args.max_iter + 1):
        n = len(uncovered_branches)

        # Convergence check (skip on first iteration)
        if iteration > 1:
            if n == 0:
                print("[fill_gaps] All branches covered — done.")
                break
            if branches_covered_this_round <= prev_covered:
                print(f"[fill_gaps] No improvement in branch coverage after round "
                      f"{iteration - 1} ({branches_covered_this_round} covered, "
                      f"was {prev_covered}) — stopping.")
                break

        prev_covered = branches_covered_this_round
        print(f"\n[fill_gaps] === Round {iteration}/{args.max_iter} "
              f"— {n} uncovered branch(es) ===")

        if args.dry_run:
            for ub in uncovered_branches:
                name = Path(ub["source_file"]).name
                print(f"  [dry-run] {name}:{ub['line']}  {ub['source_line']}")
            break

        # Read current test file state
        test_c_text = Path(test_c).read_text()

        # Group by source file → by function
        by_src = {}
        for ub in uncovered_branches:
            by_src.setdefault(ub["source_file"], []).append(ub)

        round_added = 0

        for src_path, branches in by_src.items():
            src_text = Path(src_path).read_text()
            funcs    = cov.extract_functions(src_text)

            by_func = {}
            for branch in branches:
                fname, fsrc = cov.find_owning_function(branch["line"], funcs)
                if fname is None:
                    continue
                by_func.setdefault(fname, []).append((branch, fsrc))

            for func_name, func_branches in by_func.items():
                branch_list = [b for b, _ in func_branches]
                func_src    = func_branches[0][1]
                existing    = extract_existing_tests(test_c_text, func_name)

                print(f"\n[fill_gaps] {func_name}() in {Path(src_path).name}: "
                      f"{len(branch_list)} uncovered branch(es)")
                for b in branch_list:
                    print(f"    line {b['line']}: {b['source_line']}")

                # Collect callee sources for richer LLM context
                callee_srcs = collect_callee_sources(func_name, func_src, all_source_files)
                if callee_srcs:
                    print(f"  Context: {list(callee_srcs.keys())}")

                print("  Calling LLM...")
                prompt = build_prompt(
                    func_name, func_src, branch_list, existing,
                    callee_sources=callee_srcs,
                )
                new_cases = []
                try:
                    raw = call_llm(prompt, client)
                except Exception as e:
                    print(f"  LLM error: {e}", file=sys.stderr)
                    total_skipped += 1
                    continue

                test_cases = parse_llm_response(raw)
                if test_cases is None:
                    print("  Could not parse LLM response")
                    total_skipped += 1
                    continue

                # Validate each test case returned by LLM
                for tc in test_cases:
                    target_line = tc.get("target_line")
                    if target_line is None:
                        continue
                    llm_data = {
                        "inputs":          tc.get("inputs", []),
                        "expected_return": tc.get("expected_return"),
                    }
                    hit = validate_candidate(
                        func_name, llm_data, src_path, full_headers,
                        includes_flags, extra_flags, work_dir, target_line,
                    )
                    if hit:
                        actual_ret = validate_return_value(
                            func_name, llm_data, src_path, full_headers,
                            includes_flags, extra_flags, work_dir,
                        )
                        if actual_ret is not None:
                            llm_data["expected_return"] = actual_ret
                        new_cases.append((llm_data, llm_data.get("expected_return")))
                        print(f"  ✓ line {target_line}: "
                              f"{func_name}({_args_summary(llm_data)}) "
                              f"→ {llm_data.get('expected_return')}")
                    else:
                        print(f"  ✗ line {target_line}: candidate did not reach target")

                if not new_cases:
                    total_skipped += 1

                if new_cases:
                    append_llm_tests(test_c, func_name, new_cases)
                    test_c_text = Path(test_c).read_text()
                    round_added += len(new_cases)

        total_added += round_added
        print(f"\n[fill_gaps] Round {iteration} complete — "
              f"{round_added} test(s) added this round")

        # Re-measure coverage; use branches_covered for convergence check
        print(f"[fill_gaps] Re-measuring coverage...")
        new_uncovered, branches_covered_this_round = _remeasure(data)
        if new_uncovered is None:
            print("[fill_gaps] Re-measure failed (compile error) — stopping",
                  file=sys.stderr)
            break
        uncovered_branches = new_uncovered
        print(f"[fill_gaps] {len(uncovered_branches)} branch(es) still uncovered "
              f"({branches_covered_this_round} covered)")

    print(f"\n[fill_gaps] Done — {total_added} test(s) added total, "
          f"{total_skipped} function(s) could not be covered")
    if total_added > 0:
        print(f"[fill_gaps] Updated: {test_c}")


if __name__ == "__main__":
    main()
