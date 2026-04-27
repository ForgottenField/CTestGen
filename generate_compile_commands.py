#!/usr/bin/env python3
"""
Generate compile_commands.json for a C project from Makefile-style source lists.
This allows CSA to analyze multi-file projects with proper include paths.
"""

import json
import sys
import os

def generate_compile_commands(project_dir, sources, includes, cflags):
    """
    Generate compile_commands.json for a list of source files.

    Args:
        project_dir: Absolute path to project root
        sources: List of source file paths (relative to project_dir)
        includes: List of include directories (e.g., ["-Iinclude", "-Ivendor/miniz/include"])
        cflags: Additional compiler flags (e.g., ["-std=c11", "-Wall"])
    """
    commands = []

    for src in sources:
        src_path = os.path.join(project_dir, src)
        if not os.path.exists(src_path):
            print(f"Warning: {src_path} does not exist", file=sys.stderr)
            continue

        command = {
            "directory": project_dir,
            "file": src_path,
            "arguments": ["clang"] + cflags + includes + ["-c", src_path]
        }
        commands.append(command)

    return commands


def main():
    if len(sys.argv) < 2:
        print("Usage: generate_compile_commands.py <project_dir>")
        sys.exit(1)

    project_dir = os.path.abspath(sys.argv[1])

    # Configuration for sample_project
    sources = [
        "src/utils.c",
        "src/decoder.c",
        "src/third_party_adapter.c",
        "src/parser.c",
        "vendor/miniz/src/miniz_stub.c"
    ]

    includes = ["-Iinclude", "-Ivendor/miniz/include"]
    cflags = ["-std=c11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-O0", "-g"]

    commands = generate_compile_commands(project_dir, sources, includes, cflags)

    output_path = os.path.join(project_dir, "compile_commands.json")
    with open(output_path, "w") as f:
        json.dump(commands, f, indent=2)

    print(f"Generated {output_path} with {len(commands)} entries")


if __name__ == "__main__":
    main()
