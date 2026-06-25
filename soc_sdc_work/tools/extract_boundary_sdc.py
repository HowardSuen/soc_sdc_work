#!/usr/bin/env python3
"""
Stream-extract the SDC commands consumed by the SoC SDC flow.

This prefilter is intended for very large harden SDC files. It reads input SDCs
line by line, keeps Tcl command boundaries, and writes only the boundary-related
commands that later 01/04/20/30 scripts can parse.
"""

from __future__ import print_function

import argparse
import re
import sys
from pathlib import Path


DEFAULT_COMMANDS = {
    "create_clock",
    "create_generated_clock",
    "create_generate_clock",
    "set_input_delay",
    "set_output_delay",
    "set_load",
    "set_driving_cell",
    "set_drive",
    "set_input_transition",
    "set_false_path",
    "set_dont_touch_network",
    "set_max_transition",
    "set_max_capacitance",
    "set_multicycle_path",
    "set_max_delay",
    "set_min_delay",
}


def is_escaped(text, index):
    count = 0
    pos = index - 1
    while pos >= 0 and text[pos] == "\\":
        count += 1
        pos -= 1
    return count % 2 == 1


def strip_inline_comment(line):
    quote = False
    brace_depth = 0
    bracket_depth = 0
    for idx, char in enumerate(line):
        if char == "\\":
            continue
        if char == '"' and not is_escaped(line, idx) and brace_depth == 0:
            quote = not quote
        elif not quote:
            if char == "{":
                brace_depth += 1
            elif char == "}" and brace_depth:
                brace_depth -= 1
            elif char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth:
                bracket_depth -= 1
            elif char == "#" and brace_depth == 0 and bracket_depth == 0:
                if idx == 0 or line[idx - 1].isspace() or line[idx - 1] == ";":
                    return line[:idx].rstrip()
    return line.rstrip()


def split_semicolon_commands(text):
    parts = []
    start = 0
    quote = False
    brace_depth = 0
    bracket_depth = 0
    for idx, char in enumerate(text):
        if char == "\\":
            continue
        if char == '"' and not is_escaped(text, idx) and brace_depth == 0:
            quote = not quote
        elif not quote:
            if char == "{":
                brace_depth += 1
            elif char == "}" and brace_depth:
                brace_depth -= 1
            elif char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth:
                bracket_depth -= 1
            elif char == ";" and brace_depth == 0 and bracket_depth == 0:
                parts.append(text[start:idx])
                start = idx + 1
    parts.append(text[start:])
    return parts


def iter_tcl_commands_from_file(path):
    buf = ""
    start_line = 0
    with path.open("r", encoding="utf-8-sig", errors="replace") as file_obj:
        for line_no, raw_line in enumerate(file_obj, start=1):
            line = strip_inline_comment(raw_line.rstrip("\n"))
            if not line.strip():
                continue
            if not buf:
                start_line = line_no
            stripped = line.rstrip()
            continued = stripped.endswith("\\") and not is_escaped(stripped, len(stripped) - 1)
            if continued:
                stripped = stripped[:-1].rstrip()
                buf += stripped + " "
                continue
            buf += stripped
            for cmd in split_semicolon_commands(buf):
                cleaned = cmd.strip().rstrip(";").strip()
                if cleaned:
                    yield start_line, cleaned
            buf = ""
            start_line = 0
    if buf.strip():
        for cmd in split_semicolon_commands(buf):
            cleaned = cmd.strip().rstrip(";").strip()
            if cleaned:
                yield start_line, cleaned


def command_name(command):
    match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\b", command)
    return match.group(1) if match else ""


def is_boundary_command(command, include_internal):
    if include_internal:
        return True
    if "[get_ports" in command:
        return True
    if " get_ports" in command:
        return True
    return False


def parse_command_set(value):
    if not value:
        return set(DEFAULT_COMMANDS)
    result = set()
    for part in re.split(r"[,\s]+", value):
        part = part.strip()
        if part:
            result.add(part)
    return result


def output_path_for_input(path, output_dir=None, suffix="_extract"):
    path = Path(path)
    base_dir = Path(output_dir) if output_dir else path.parent
    return base_dir / ("%s%s%s" % (path.stem, suffix, path.suffix))


def find_sdc_files(path, recursive=False, suffix="_extract"):
    path = Path(path)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise RuntimeError("input path is not a file or directory: %s" % path)
    pattern = "**/*.sdc" if recursive else "*.sdc"
    result = []
    for item in sorted(path.glob(pattern)):
        if not item.is_file():
            continue
        if item.stem.endswith(suffix):
            continue
        result.append(item)
    return result


def write_header(out, inputs, commands, include_internal):
    out.write("# Auto-extracted boundary SDC for SoC SDC flow\n")
    out.write("# Inputs:\n")
    for path in inputs:
        out.write("#   %s\n" % path)
    out.write("# Commands: %s\n" % " ".join(sorted(commands)))
    out.write("# Boundary filter: %s\n\n" % ("disabled" if include_internal else "commands containing get_ports"))


def extract_one(input_path, output, commands, include_internal, with_source_comments):
    kept = 0
    scanned = 0
    per_command = {}
    with output.open("w", encoding="utf-8") as out:
        write_header(out, [input_path], commands, include_internal)
        path = Path(input_path)
        if not path.is_file():
            raise RuntimeError("input SDC not found: %s" % path)
        for line_no, cmd in iter_tcl_commands_from_file(path):
            scanned += 1
            name = command_name(cmd)
            if name not in commands:
                continue
            if not is_boundary_command(cmd, include_internal):
                continue
            if with_source_comments:
                out.write("# source: %s:%s\n" % (path, line_no))
            out.write(cmd)
            out.write("\n")
            kept += 1
            per_command[name] = per_command.get(name, 0) + 1
    return scanned, kept, per_command


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Stream-filter huge harden SDC files into small boundary SDC files for the SoC SDC flow."
    )
    parser.add_argument(
        "input",
        help="Input harden SDC file or directory. Directory mode processes all *.sdc files.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output filtered SDC file for single-file mode. Not allowed in directory mode.",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory for *_extract.sdc outputs. Defaults to each input file's directory.",
    )
    parser.add_argument(
        "--suffix",
        default="_extract",
        help="Output filename suffix before .sdc. Default: _extract.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Directory mode: recursively process *.sdc files.",
    )
    parser.add_argument(
        "--commands",
        default="",
        help="Optional comma/space separated command allow-list. Defaults to all commands consumed by 01/04/20/30.",
    )
    parser.add_argument(
        "--include-internal",
        action="store_true",
        help="Keep selected commands even when they do not reference get_ports. Default keeps boundary get_ports commands only.",
    )
    parser.add_argument(
        "--no-source-comments",
        action="store_true",
        help="Do not write source file/line comments before extracted commands.",
    )
    args = parser.parse_args(argv)

    commands = parse_command_set(args.commands)
    input_path = Path(args.input)
    try:
        if input_path.is_dir() and args.output:
            raise RuntimeError("-o/--output is only valid for single-file mode; use --output-dir for directory mode")
        files = find_sdc_files(input_path, args.recursive, args.suffix)
        if not files:
            raise RuntimeError("no input .sdc file found under %s" % input_path)
        total_scanned = 0
        total_kept = 0
        total_per_command = {}
        for item in files:
            output = Path(args.output) if args.output and len(files) == 1 else output_path_for_input(item, args.output_dir, args.suffix)
            output.parent.mkdir(parents=True, exist_ok=True)
            if item.resolve() == output.resolve():
                raise RuntimeError("refusing to overwrite input file: %s" % item)
            scanned, kept, per_command = extract_one(
                item,
                output,
                commands,
                args.include_internal,
                not args.no_source_comments,
            )
            total_scanned += scanned
            total_kept += kept
            for name, count in per_command.items():
                total_per_command[name] = total_per_command.get(name, 0) + count
            print("wrote: %s  scanned=%d kept=%d" % (output, scanned, kept))
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2

    print("processed_files: %d" % len(files))
    print("scanned_commands: %d" % total_scanned)
    print("kept_commands: %d" % total_kept)
    for name in sorted(total_per_command):
        print("  %s: %d" % (name, total_per_command[name]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
