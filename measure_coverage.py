#!/usr/bin/env python3
"""
measure_coverage.py — Compile tests with gcov instrumentation, run them, and
                       collect coverage data into a structured JSON file.

Usage:
    python3 measure_coverage.py \\
        <test_autogen.c>             \\
        <project_dir>                \\
        <compile_commands.json>      \\
        [--output coverage_data.json] \\
        [--work-dir DIR]             \\
        [--verbose]

Output (coverage_data.json):
    {
      "test_c":            "/abs/path/test_autogen.c",
      "project_dir":       "/abs/path/project",
      "compile_commands":  "/abs/path/compile_commands.json",
      "work_dir":          "/abs/path/cov_work",
      "includes_flags":    [...],
      "extra_flags":       [...],
      "link_sources":      [...],
      "analysis_sources":  [...],
      "header_includes":   [...],
      "header_dirs":       [...],
      "uncovered_branches": [...],
      "coverage_summary":  { "<source_file>": { lines_total, lines_covered, ... } }
    }

The work_dir is kept on disk so that fill_gaps.py can compile probe binaries there.
Run report_coverage.py to display a human-readable summary.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import _cov_utils as cov


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("test_c",            help="Path to test_autogen.c")
    ap.add_argument("project_dir",       help="Project root directory")
    ap.add_argument("compile_commands",  help="Path to compile_commands.json")
    ap.add_argument("--output", default=None,
                    help="Output JSON path (default: <test_c_dir>/coverage_data.json)")
    ap.add_argument("--work-dir", default=None, dest="work_dir",
                    help="Directory for gcov artefacts (default: <output_dir>/cov_work)")
    ap.add_argument("--verbose", action="store_true",
                    help="Print test binary stdout")
    args = ap.parse_args()

    test_c           = os.path.abspath(args.test_c)
    project_dir      = os.path.abspath(args.project_dir)
    compile_commands = os.path.abspath(args.compile_commands)

    for p, label in [(test_c, "test_c"), (compile_commands, "compile_commands")]:
        if not os.path.exists(p):
            print(f"[measure] Error: {label} not found: {p}", file=sys.stderr)
            sys.exit(1)

    # Determine output paths
    output_json = args.output or os.path.join(
        os.path.dirname(test_c), "coverage_data.json"
    )
    output_json = os.path.abspath(output_json)

    work_dir = args.work_dir or os.path.join(
        os.path.dirname(output_json), "cov_work"
    )
    work_dir = os.path.abspath(work_dir)
    os.makedirs(work_dir, exist_ok=True)

    # --- Parse compile_commands ---
    includes_flags, extra_flags = cov.flags_and_includes(compile_commands, project_dir)
    all_sources      = cov.collect_source_files(compile_commands, project_dir)
    link_sources     = all_sources
    analysis_sources = [s for s in all_sources if "/vendor/" not in s]

    # Header info (used by fill_gaps.py for probe compilation)
    test_c_text  = Path(test_c).read_text()
    header_includes = cov.header_includes_from_test_c(test_c_text)
    header_dirs     = [f[2:] for f in includes_flags if f.startswith("-I")]

    print("[measure] Compiling with coverage instrumentation...")
    bin_path = cov.compile_with_coverage(
        test_c, link_sources, includes_flags, extra_flags, work_dir
    )
    if bin_path is None:
        print("[measure] Compilation failed.", file=sys.stderr)
        sys.exit(1)

    print("[measure] Running test binary...")
    stdout, _ = cov.run_binary(bin_path, work_dir)
    if stdout:
        print(stdout.strip())

    # --- Run gcov and collect data ---
    print("[measure] Collecting coverage data...")
    uncovered_branches = []
    coverage_summary   = {}

    for src in analysis_sources:
        gcov_text = cov.run_gcov(src, work_dir)
        if gcov_text is None:
            print(f"  [warn] No gcov data for {Path(src).name}", file=sys.stderr)
            continue
        uncovered = cov.parse_uncovered_branches(gcov_text, src)
        stats     = cov.parse_coverage_stats(gcov_text)
        uncovered_branches.extend(uncovered)
        coverage_summary[src] = stats

    # --- Write JSON ---
    data = {
        "test_c":             test_c,
        "project_dir":        project_dir,
        "compile_commands":   compile_commands,
        "work_dir":           work_dir,
        "includes_flags":     includes_flags,
        "extra_flags":        extra_flags,
        "link_sources":       link_sources,
        "analysis_sources":   analysis_sources,
        "header_includes":    header_includes,
        "header_dirs":        header_dirs,
        "uncovered_branches": uncovered_branches,
        "coverage_summary":   coverage_summary,
    }
    with open(output_json, "w") as f:
        json.dump(data, f, indent=2)

    # --- Print summary ---
    print(f"\n[measure] Coverage data written to: {output_json}")
    _print_summary(coverage_summary, uncovered_branches, analysis_sources)


def _print_summary(coverage_summary, uncovered_branches, analysis_sources):
    """Print a concise per-file coverage table to stdout."""
    total_lt = total_lc = total_bt = total_bc = 0
    col = 36

    print(f"\n{'Source':<{col}}  {'Lines':>14}  {'Branches':>14}")
    print("-" * (col + 34))
    for src in analysis_sources:
        s = coverage_summary.get(src)
        if s is None:
            continue
        lt, lc = s["lines_total"], s["lines_covered"]
        bt, bc = s["branches_total"], s["branches_covered"]
        total_lt += lt; total_lc += lc
        total_bt += bt; total_bc += bc
        lpct = f"{lc}/{lt} ({100*lc//lt if lt else 0}%)"
        bpct = f"{bc}/{bt} ({100*bc//bt if bt else 0}%)"
        name = Path(src).name
        print(f"  {name:<{col-2}}  {lpct:>14}  {bpct:>14}")

    print("-" * (col + 34))
    lpct = f"{total_lc}/{total_lt} ({100*total_lc//total_lt if total_lt else 0}%)"
    bpct = f"{total_bc}/{total_bt} ({100*total_bc//total_bt if total_bt else 0}%)"
    print(f"  {'TOTAL':<{col-2}}  {lpct:>14}  {bpct:>14}")

    if uncovered_branches:
        print(f"\n  {len(uncovered_branches)} uncovered branch(es):")
        for ub in uncovered_branches:
            name = Path(ub["source_file"]).name
            print(f"    {name}:{ub['line']}  {ub['source_line']}")
    else:
        print("\n  All branches covered!")
    print()


if __name__ == "__main__":
    main()
