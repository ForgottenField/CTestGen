#!/usr/bin/env python3
"""
report_coverage.py — Display a human-readable coverage report.

Usage:
    # Show single snapshot
    python3 report_coverage.py <coverage_data.json>

    # Compare before and after (e.g. before/after LLM gap filling)
    python3 report_coverage.py <before.json> <after.json>

The JSON files are produced by measure_coverage.py.
"""

import argparse
import json
import sys
from pathlib import Path


def load(path):
    with open(path) as f:
        return json.load(f)


def pct(covered, total):
    if total == 0:
        return "N/A"
    return f"{100 * covered // total}%"


def _fmt_stat(covered, total):
    return f"{covered:>4}/{total:<4} ({pct(covered, total):>4})"


# ---------------------------------------------------------------------------
# Single-snapshot report
# ---------------------------------------------------------------------------

def report_single(data, title="Coverage Report"):
    summary   = data.get("coverage_summary", {})
    uncovered = data.get("uncovered_branches", [])
    sources   = data.get("analysis_sources", list(summary.keys()))

    col = 36
    print(f"\n{'=' * (col + 34)}")
    print(f"  {title}")
    print(f"{'=' * (col + 34)}")
    print(f"\n  {'Source':<{col}}  {'Lines':>16}  {'Branches':>16}")
    print(f"  {'-' * (col + 36)}")

    total_lt = total_lc = total_bt = total_bc = 0
    for src in sources:
        s = summary.get(src)
        if s is None:
            continue
        lt, lc = s["lines_total"],    s["lines_covered"]
        bt, bc = s["branches_total"], s["branches_covered"]
        total_lt += lt; total_lc += lc
        total_bt += bt; total_bc += bc
        name = Path(src).name
        print(f"  {name:<{col}}  {_fmt_stat(lc, lt):>16}  {_fmt_stat(bc, bt):>16}")

    print(f"  {'-' * (col + 36)}")
    print(f"  {'TOTAL':<{col}}  {_fmt_stat(total_lc, total_lt):>16}  "
          f"{_fmt_stat(total_bc, total_bt):>16}")

    print(f"\n  Uncovered branches: {len(uncovered)}")
    if uncovered:
        print()
        for ub in uncovered:
            name = Path(ub["source_file"]).name
            print(f"    {name}:{ub['line']:<5}  {ub['source_line']}")
    print()


# ---------------------------------------------------------------------------
# Before/after comparison report
# ---------------------------------------------------------------------------

def report_compare(before, after):
    sb = before.get("coverage_summary", {})
    sa = after.get("coverage_summary",  {})
    ub_before = before.get("uncovered_branches", [])
    ub_after  = after.get("uncovered_branches",  [])
    sources   = before.get("analysis_sources", list(sb.keys()))

    col = 34
    w   = 22

    print(f"\n{'=' * (col + 2 * w + 6)}")
    print(f"  Coverage Comparison: Before vs After LLM Gap Filling")
    print(f"{'=' * (col + 2 * w + 6)}")
    print(f"\n  {'Source':<{col}}  {'Before':^{w}}  {'After':^{w}}  Delta")
    print(f"  {'-' * (col + 2 * w + 10)}")

    total_before_lc = total_before_lt = 0
    total_after_lc  = total_after_lt  = 0
    total_before_bc = total_before_bt = 0
    total_after_bc  = total_after_bt  = 0

    for src in sources:
        sbf = sb.get(src, {})
        saf = sa.get(src, {})
        if not sbf and not saf:
            continue
        name = Path(src).name

        lt_b = sbf.get("lines_total",      0)
        lc_b = sbf.get("lines_covered",    0)
        bt_b = sbf.get("branches_total",   0)
        bc_b = sbf.get("branches_covered", 0)

        lt_a = saf.get("lines_total",      0)
        lc_a = saf.get("lines_covered",    0)
        bt_a = saf.get("branches_total",   0)
        bc_a = saf.get("branches_covered", 0)

        total_before_lt += lt_b; total_before_lc += lc_b
        total_after_lt  += lt_a; total_after_lc  += lc_a
        total_before_bt += bt_b; total_before_bc += bc_b
        total_after_bt  += bt_a; total_after_bc  += bc_a

        # Show branch coverage as the primary metric
        before_str = f"br {_fmt_stat(bc_b, bt_b)}"
        after_str  = f"br {_fmt_stat(bc_a, bt_a)}"
        delta_bc   = bc_a - bc_b
        delta_str  = (f"+{delta_bc}" if delta_bc > 0 else str(delta_bc)) if delta_bc != 0 else "—"
        print(f"  {name:<{col}}  {before_str:^{w}}  {after_str:^{w}}  {delta_str}")

    print(f"  {'-' * (col + 2 * w + 10)}")
    tb_str = f"br {_fmt_stat(total_before_bc, total_before_bt)}"
    ta_str = f"br {_fmt_stat(total_after_bc,  total_after_bt)}"
    total_delta = total_after_bc - total_before_bc
    td_str = (f"+{total_delta}" if total_delta > 0 else str(total_delta)) if total_delta != 0 else "—"
    print(f"  {'TOTAL':<{col}}  {tb_str:^{w}}  {ta_str:^{w}}  {td_str}")

    nb = len(ub_before)
    na = len(ub_after)
    newly_covered = nb - na

    print(f"\n  Uncovered branches:  {nb} → {na}  "
          f"({'−' + str(newly_covered) if newly_covered > 0 else 'no change'})")

    if nb > na:
        before_lines = {(u["source_file"], u["line"]) for u in ub_before}
        after_lines  = {(u["source_file"], u["line"]) for u in ub_after}
        filled = before_lines - after_lines
        if filled:
            print("  Newly covered branches:")
            for src, line in sorted(filled, key=lambda x: (Path(x[0]).name, x[1])):
                print(f"    {Path(src).name}:{line}")

    if ub_after:
        print(f"\n  Still uncovered ({len(ub_after)}):")
        for ub in ub_after:
            name = Path(ub["source_file"]).name
            print(f"    {name}:{ub['line']:<5}  {ub['source_line']}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before_json", help="coverage_data.json (before LLM fill)")
    ap.add_argument("after_json",  nargs="?",
                    help="coverage_data.json after LLM fill (optional, enables diff mode)")
    args = ap.parse_args()

    before = load(args.before_json)

    if args.after_json:
        after = load(args.after_json)
        report_single(before, title=f"Before  ({args.before_json})")
        report_single(after,  title=f"After   ({args.after_json})")
        report_compare(before, after)
    else:
        report_single(before, title=f"Coverage Report  ({args.before_json})")


if __name__ == "__main__":
    main()
