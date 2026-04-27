#!/usr/bin/env python3
"""
gap_fill.py — Backward-compatible wrapper: measure coverage then fill gaps with LLM.

Equivalent to running:
    python3 measure_coverage.py <test_c> <project_dir> <compile_commands> \\
        --output <tmpdir>/coverage_data.json
    python3 fill_gaps.py <tmpdir>/coverage_data.json [--model M] [--max-retries N] [--dry-run]

For more control (e.g. comparing before/after coverage) use the two scripts directly.

Usage (same as before):
    python3 gap_fill.py \\
        <test_autogen.c>         \\
        <project_dir>            \\
        <compile_commands.json>  \\
        [--model MODEL]          \\
        [--max-retries N]        \\
        [--dry-run]
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("test_c",            help="Path to test_autogen.c")
    ap.add_argument("project_dir",       help="Project root directory")
    ap.add_argument("compile_commands",  help="Path to compile_commands.json")
    ap.add_argument("--model",           default=None)
    ap.add_argument("--max-retries",     type=int, default=None, dest="max_retries")
    ap.add_argument("--dry-run",         action="store_true")
    args = ap.parse_args()

    python = sys.executable

    # Stage 1: measure coverage → coverage_data.json in a temp work dir
    with tempfile.TemporaryDirectory(prefix="gap_fill_") as tmpdir:
        cov_json = os.path.join(tmpdir, "coverage_data.json")

        measure_cmd = [
            python,
            str(HERE / "measure_coverage.py"),
            args.test_c,
            args.project_dir,
            args.compile_commands,
            "--output", cov_json,
            "--work-dir", os.path.join(tmpdir, "cov_work"),
        ]
        r = subprocess.run(measure_cmd)
        if r.returncode != 0:
            sys.exit(r.returncode)

        # Stage 2: LLM gap filling
        fill_cmd = [
            python,
            str(HERE / "fill_gaps.py"),
            cov_json,
        ]
        if args.model:
            fill_cmd += ["--model", args.model]
        if args.max_retries is not None:
            fill_cmd += ["--max-retries", str(args.max_retries)]
        if args.dry_run:
            fill_cmd.append("--dry-run")

        r = subprocess.run(fill_cmd)
        sys.exit(r.returncode)


if __name__ == "__main__":
    main()
