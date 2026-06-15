#!/usr/bin/env python3
"""
Generate common/01_soc_clocks.sdc from local integration spreadsheets and
flattened harden SoC-integration SDC files.

Current scope:
  * func-only clock extraction
  * all xlsx and SDC inputs live in the command execution directory
  * repeated harden/module instantiations are handled per inst_name
"""

import argparse
import csv
import glob
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover - user environment guard
    print("ERROR: pandas is required to read integration xlsx files.", file=sys.stderr)
    raise SystemExit(2) from exc


CLOCK_COMMANDS = {
    "create_clock",
    "create_generated_clock",
    "create_generate_clock",
}

GET_OPTIONS_WITH_VALUE = {
    "-fi",
    "-filter",
    "-of",
    "-of_objects",
}

CLOCK_OPTIONS_WITH_VALUE = {
    "-comment",
    "-divide_by",
    "-duty_cycle",
    "-edges",
    "-edge_shift",
    "-master_clock",
    "-multiply_by",
    "-name",
    "-period",
    "-source",
    "-waveform",
}

CLOCK_OPTIONS_NO_VALUE = {
    "-add",
    "-combinational",
}


@dataclass
class PortInfo:
    name: str
    width: str = ""
    used_width: str = ""
    from_whom: str = ""
    to_top: str = ""
    connectivity: str = ""
    inout_name: str = ""


@dataclass
class InstInfo:
    module_name: str
    inst_name: str
    owner: str = ""
    file_path: str = ""
    sdc_hint: str = ""
    sdc_path: Optional[Path] = None
    inputs: Dict[str, PortInfo] = field(default_factory=dict)
    outputs: Dict[str, PortInfo] = field(default_factory=dict)
    inouts: Dict[str, PortInfo] = field(default_factory=dict)


@dataclass
class TclCommand:
    raw: str
    line_no: int


@dataclass
class ParsedClock:
    raw: str
    source_line: int
    command: str
    tokens: List[str]
    target_ports: List[str]
    target_token_indices: List[int]
    source_ports: List[str]
    original_name: str
    period: str
    waveform: str
    source_token: str
    target_direction: str = "unknown"


@dataclass
class ClockRecord:
    inst_name: str
    module_name: str
    port_name: str
    direction: str
    clock_name: str
    clock_kind: str
    period: str
    waveform: str
    direct_source: str
    root_source: str
    from_whom: str
    original_sdc: str
    original_clock_name: str
    final_action: str
    note: str
    emitted_command: str = ""
    is_forwarded: bool = False
    producer_object: str = ""
    source_line: int = 0
    original_command: str = ""


@dataclass
class VirtualClockSpec:
    clock_name: str
    period: str
    waveform: str = ""
    note: str = ""
    source_file: str = ""


class Report:
    def __init__(self) -> None:
        self.lines: List[str] = []
        self.warning_count = 0
        self.error_count = 0

    def info(self, msg: str) -> None:
        self.lines.append(f"INFO: {msg}")

    def warn(self, msg: str) -> None:
        self.warning_count += 1
        self.lines.append(f"WARNING: {msg}")

    def error(self, msg: str) -> None:
        self.error_count += 1
        self.lines.append(f"ERROR: {msg}")


def clean_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def normalize_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).strip().lower())


def column_map(df: pd.DataFrame) -> Dict[str, str]:
    return {normalize_col(col): col for col in df.columns}


def get_col(df: pd.DataFrame, aliases: Sequence[str]) -> Optional[str]:
    cmap = column_map(df)
    for alias in aliases:
        key = normalize_col(alias)
        if key in cmap:
            return cmap[key]
    return None


def read_excel_file(path: Path, sheet_name=0):
    try:
        return pd.read_excel(path, sheet_name=sheet_name)
    except Exception as exc:
        raise RuntimeError(
            f"failed to read {path}. If this is an xlsx engine issue, install openpyxl "
            "or use an environment where pandas can read .xlsx files."
        ) from exc


def read_info_all(path: Path, report: Report) -> Dict[str, InstInfo]:
    df = read_excel_file(path)
    module_col = get_col(df, ["module_name", "module name", "module"])
    inst_col = get_col(df, ["inst_name", "inst name", "instance", "instance_name"])
    owner_col = get_col(df, ["owner"])
    file_col = get_col(df, ["file_path", "file path", "empty_path", "verilog", "v_path"])
    sdc_col = get_col(df, ["sdc_path", "sdc file", "sdc_file", "sdc"])

    if not inst_col:
        raise RuntimeError(f"{path} must contain an inst_name column")

    instances: Dict[str, InstInfo] = {}
    for row_idx, row in df.iterrows():
        inst_name = clean_cell(row.get(inst_col))
        if not inst_name:
            continue
        module_name = clean_cell(row.get(module_col)) if module_col else ""
        file_path = clean_cell(row.get(file_col)) if file_col else ""
        if not module_name and file_path:
            module_name = Path(file_path).stem.replace("_empty", "")
        if not module_name:
            module_name = inst_name
            report.warn(
                f"{path.name} row {row_idx + 2}: module_name is empty; using inst_name {inst_name}"
            )
        if inst_name in instances:
            report.warn(f"duplicate inst_name {inst_name} in {path.name}; keeping first row")
            continue
        instances[inst_name] = InstInfo(
            module_name=module_name,
            inst_name=inst_name,
            owner=clean_cell(row.get(owner_col)) if owner_col else "",
            file_path=file_path,
            sdc_hint=clean_cell(row.get(sdc_col)) if sdc_col else "",
        )

    report.info(f"loaded {len(instances)} instances from {path.name}")
    return instances


def read_port_workbooks(paths: Sequence[Path], report: Report) -> Dict[str, Dict[str, Dict[str, PortInfo]]]:
    result: Dict[str, Dict[str, Dict[str, PortInfo]]] = {}
    for path in paths:
        try:
            book = pd.ExcelFile(path)
        except Exception as exc:
            report.error(f"failed to open port workbook {path.name}: {exc}")
            continue
        for sheet_name in book.sheet_names:
            try:
                df = read_excel_file(path, sheet_name=sheet_name)
            except Exception as exc:
                report.error(f"failed to read {path.name}:{sheet_name}: {exc}")
                continue
            if sheet_name in result:
                report.warn(
                    f"sheet {sheet_name} appears in multiple port workbooks; keeping first occurrence"
                )
                continue
            result[sheet_name] = parse_port_sheet(df)
    report.info(f"loaded {len(result)} instance sheets from {len(paths)} port workbook(s)")
    return result


def read_virtual_clock_csv(path: Path, report: Report) -> List[VirtualClockSpec]:
    if not path.is_file():
        return []
    specs: List[VirtualClockSpec] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        if not reader.fieldnames:
            report.warn(f"{path.name}: virtual clock CSV has no header")
            return specs
        normalized = {normalize_col(name): name for name in reader.fieldnames}
        name_col = None
        for alias in ("clock_name", "clock name", "name"):
            key = normalize_col(alias)
            if key in normalized:
                name_col = normalized[key]
                break
        period_col = None
        for alias in ("period", "clock_period"):
            key = normalize_col(alias)
            if key in normalized:
                period_col = normalized[key]
                break
        waveform_col = None
        for alias in ("waveform",):
            key = normalize_col(alias)
            if key in normalized:
                waveform_col = normalized[key]
                break
        note_col = None
        for alias in ("note", "comment", "description"):
            key = normalize_col(alias)
            if key in normalized:
                note_col = normalized[key]
                break
        if not name_col or not period_col:
            report.warn(
                f"{path.name}: virtual clock CSV requires clock_name/name and period columns"
            )
            return specs
        for row_idx, row in enumerate(reader, start=2):
            clock_name = sanitize_name(clean_cell(row.get(name_col)))
            period = clean_cell(row.get(period_col))
            if not clock_name or not period:
                report.warn(f"{path.name} row {row_idx}: skipped virtual clock without name/period")
                continue
            specs.append(
                VirtualClockSpec(
                    clock_name=clock_name,
                    period=period,
                    waveform=clean_cell(row.get(waveform_col)) if waveform_col else "",
                    note=clean_cell(row.get(note_col)) if note_col else "",
                    source_file=path.name,
                )
            )
    report.info(f"loaded {len(specs)} virtual clock(s) from {path.name}")
    return specs


def parse_port_sheet(df: pd.DataFrame) -> Dict[str, Dict[str, PortInfo]]:
    input_col = get_col(df, ["Input"])
    input_width_col = get_col(df, ["Input Width"])
    input_used_col = get_col(df, ["Input Used Width"])
    from_col = get_col(df, ["From Whom"])

    output_col = get_col(df, ["Output"])
    output_width_col = get_col(df, ["Output Width"])
    output_used_col = get_col(df, ["Output Used Width"])
    to_top_col = get_col(df, ["To Top"])

    inout_col = get_col(df, ["Inout"])
    inout_width_col = get_col(df, ["Inout Width"])
    inout_conn_col = get_col(df, ["Inout Connectivity"])
    inout_name_col = get_col(df, ["Inout Name"])

    inputs: Dict[str, PortInfo] = {}
    outputs: Dict[str, PortInfo] = {}
    inouts: Dict[str, PortInfo] = {}

    for _, row in df.iterrows():
        if input_col:
            name = clean_cell(row.get(input_col))
            if name:
                inputs[name] = PortInfo(
                    name=name,
                    width=clean_cell(row.get(input_width_col)) if input_width_col else "",
                    used_width=clean_cell(row.get(input_used_col)) if input_used_col else "",
                    from_whom=clean_cell(row.get(from_col)) if from_col else "",
                )
        if output_col:
            name = clean_cell(row.get(output_col))
            if name:
                outputs[name] = PortInfo(
                    name=name,
                    width=clean_cell(row.get(output_width_col)) if output_width_col else "",
                    used_width=clean_cell(row.get(output_used_col)) if output_used_col else "",
                    to_top=clean_cell(row.get(to_top_col)) if to_top_col else "",
                )
        if inout_col:
            name = clean_cell(row.get(inout_col))
            if name:
                inouts[name] = PortInfo(
                    name=name,
                    width=clean_cell(row.get(inout_width_col)) if inout_width_col else "",
                    connectivity=clean_cell(row.get(inout_conn_col)) if inout_conn_col else "",
                    inout_name=clean_cell(row.get(inout_name_col)) if inout_name_col else "",
                )

    return {"inputs": inputs, "outputs": outputs, "inouts": inouts}


def attach_port_data(instances: Dict[str, InstInfo], sheets: Dict[str, Dict[str, Dict[str, PortInfo]]], report: Report) -> None:
    for inst in instances.values():
        data = sheets.get(inst.inst_name)
        if not data:
            report.warn(f"no owner port sheet found for instance {inst.inst_name}")
            continue
        inst.inputs = data["inputs"]
        inst.outputs = data["outputs"]
        inst.inouts = data["inouts"]


def resolve_sdc_paths(instances: Dict[str, InstInfo], cwd: Path, report: Report) -> None:
    all_sdcs = sorted(cwd.glob("*.sdc"))
    by_name = {p.name: p for p in all_sdcs}
    by_lower = {p.name.lower(): p for p in all_sdcs}

    for inst in instances.values():
        candidates: List[str] = []
        if inst.sdc_hint:
            candidates.append(Path(inst.sdc_hint).name)
        candidates.append(f"{inst.inst_name}.sdc")
        candidates.append(f"{inst.module_name}.sdc")
        if inst.file_path:
            stem = Path(inst.file_path).stem
            candidates.append(f"{stem}.sdc")
            if stem.endswith("_empty"):
                candidates.append(f"{stem[:-6]}.sdc")

        seen = set()
        matches: List[Path] = []
        for name in candidates:
            if not name or name in seen:
                continue
            seen.add(name)
            if name in by_name:
                matches.append(by_name[name])
            elif name.lower() in by_lower:
                matches.append(by_lower[name.lower()])

        unique_matches = []
        for path in matches:
            if path not in unique_matches:
                unique_matches.append(path)

        if len(unique_matches) == 1:
            inst.sdc_path = unique_matches[0]
        elif len(unique_matches) > 1:
            inst.sdc_path = unique_matches[0]
            report.warn(
                f"multiple SDC candidates for {inst.inst_name}: "
                f"{', '.join(p.name for p in unique_matches)}; using {inst.sdc_path.name}"
            )
        else:
            report.error(
                f"no SDC found for {inst.inst_name}; tried: {', '.join(candidates)}"
            )


def read_text(path: Path) -> str:
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def compact_command(text: str, max_len: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3] + "..."


def clock_location(sdc_name: str, line_no: int) -> str:
    return f"{sdc_name}:{line_no}" if line_no else sdc_name


def harden_clock_issue(inst: InstInfo, cmd: ParsedClock, rule_id: str, message: str) -> str:
    port = cmd.target_ports[0] if cmd.target_ports else "<no-target>"
    location = clock_location(inst.sdc_path.name if inst.sdc_path else inst.inst_name, cmd.source_line)
    return (
        f"{location}: {inst.inst_name}/{port}: clock={cmd.original_name}: {rule_id}: {message}; "
        f"command: {compact_command(cmd.raw)}"
    )


def record_clock_issue(rec: ClockRecord, rule_id: str, message: str) -> str:
    location = clock_location(rec.original_sdc, rec.source_line)
    detail = f"{location}: {rec.inst_name}/{rec.port_name}: clock={rec.clock_name}: {rule_id}: {message}"
    if rec.original_command:
        detail += f"; command: {compact_command(rec.original_command)}"
    return detail


def is_escaped(text: str, index: int) -> bool:
    count = 0
    pos = index - 1
    while pos >= 0 and text[pos] == "\\":
        count += 1
        pos -= 1
    return count % 2 == 1


def strip_inline_comment(line: str) -> str:
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


def iter_tcl_commands_with_line(text: str) -> Iterable[TclCommand]:
    buf = ""
    start_line = 0
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_inline_comment(raw_line)
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
                yield TclCommand(cleaned, start_line)
        buf = ""
        start_line = 0
    if buf.strip():
        for cmd in split_semicolon_commands(buf):
            cleaned = cmd.strip().rstrip(";").strip()
            if cleaned:
                yield TclCommand(cleaned, start_line)


def iter_tcl_commands(text: str) -> Iterable[str]:
    for cmd in iter_tcl_commands_with_line(text):
        yield cmd.raw


def split_semicolon_commands(text: str) -> List[str]:
    parts: List[str] = []
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


def find_matching(text: str, start: int, open_char: str, close_char: str) -> int:
    depth = 0
    quote = False
    idx = start
    while idx < len(text):
        char = text[idx]
        if char == "\\":
            idx += 2
            continue
        if char == '"' and open_char != '"' and not is_escaped(text, idx):
            quote = not quote
        elif not quote:
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    return idx
        idx += 1
    return -1


def tokenize_tcl_words(text: str) -> List[str]:
    tokens: List[str] = []
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        start = idx
        if text[idx] == "{":
            end = find_matching(text, idx, "{", "}")
            if end < 0:
                tokens.append(text[start:])
                break
            tokens.append(text[start : end + 1])
            idx = end + 1
            continue
        if text[idx] == '"':
            idx += 1
            while idx < len(text):
                if text[idx] == "\\":
                    idx += 2
                    continue
                if text[idx] == '"':
                    idx += 1
                    break
                idx += 1
            tokens.append(text[start:idx])
            continue

        pieces: List[str] = []
        while idx < len(text) and not text[idx].isspace():
            char = text[idx]
            if char == "\\":
                pieces.append(text[idx : idx + 2])
                idx += 2
            elif char == "[":
                end = find_matching(text, idx, "[", "]")
                if end < 0:
                    pieces.append(text[idx:])
                    idx = len(text)
                else:
                    pieces.append(text[idx : end + 1])
                    idx = end + 1
            elif char == "{":
                end = find_matching(text, idx, "{", "}")
                if end < 0:
                    pieces.append(text[idx:])
                    idx = len(text)
                else:
                    pieces.append(text[idx : end + 1])
                    idx = end + 1
            elif char == '"':
                idx += 1
                while idx < len(text):
                    if text[idx] == "\\":
                        idx += 2
                    elif text[idx] == '"':
                        idx += 1
                        break
                    else:
                        idx += 1
                pieces.append(text[start:idx])
            else:
                pieces.append(char)
                idx += 1
        tokens.append("".join(pieces))
    return tokens


def unbrace(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == "{" and token[-1] == "}":
        return token[1:-1]
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1]
    return token


def split_object_list(token: str) -> List[str]:
    token = unbrace(token)
    if not token:
        return []
    return [unbrace(part) for part in tokenize_tcl_words(token)]


def parse_get_object(token: str) -> Tuple[str, List[str]]:
    token = token.strip()
    if not (token.startswith("[") and token.endswith("]")):
        return "", []
    inner = token[1:-1].strip()
    words = tokenize_tcl_words(inner)
    if not words:
        return "", []
    command = words[0]
    if command not in {"get_ports", "get_pins", "get_clocks"}:
        return "", []
    objects: List[str] = []
    idx = 1
    while idx < len(words):
        word = words[idx]
        if word.startswith("-"):
            idx += 2 if word in GET_OPTIONS_WITH_VALUE else 1
            continue
        objects.extend(split_object_list(word))
        idx += 1
    return command, objects


def get_option(tokens: Sequence[str], option: str) -> str:
    for idx, tok in enumerate(tokens):
        if tok == option and idx + 1 < len(tokens):
            return unbrace(tokens[idx + 1])
    return ""


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "clk"


def tcl_obj(name: str) -> str:
    return "{" + name + "}"


def get_pins_obj(objects: Sequence[str]) -> str:
    if len(objects) == 1:
        return f"[get_pins {tcl_obj(objects[0])}]"
    return f"[get_pins {tcl_obj(' '.join(objects))}]"


def get_ports_obj(objects: Sequence[str]) -> str:
    if len(objects) == 1:
        return f"[get_ports {tcl_obj(objects[0])}]"
    return f"[get_ports {tcl_obj(' '.join(objects))}]"


def get_clocks_obj(objects: Sequence[str]) -> str:
    if len(objects) == 1:
        return f"[get_clocks {tcl_obj(objects[0])}]"
    return f"[get_clocks {tcl_obj(' '.join(objects))}]"


def parse_clock_commands(text: str, report: Report, sdc_name: str) -> List[ParsedClock]:
    parsed: List[ParsedClock] = []
    for tcl_cmd in iter_tcl_commands_with_line(text):
        raw = tcl_cmd.raw
        tokens = tokenize_tcl_words(raw)
        if not tokens:
            continue
        command = tokens[0]
        if command not in CLOCK_COMMANDS:
            continue
        target_ports: List[str] = []
        target_token_indices: List[int] = []
        source_ports: List[str] = []
        source_token = ""
        idx = 1
        while idx < len(tokens):
            tok = tokens[idx]
            if tok == "-source":
                if idx + 1 < len(tokens):
                    source_token = tokens[idx + 1]
                    src_cmd, src_objects = parse_get_object(tokens[idx + 1])
                    if src_cmd == "get_ports":
                        source_ports = src_objects
                idx += 2
                continue
            if tok in CLOCK_OPTIONS_WITH_VALUE:
                idx += 2
                continue
            if tok.startswith("-") or tok in CLOCK_OPTIONS_NO_VALUE:
                idx += 1
                continue
            obj_cmd, objects = parse_get_object(tok)
            if obj_cmd == "get_ports":
                target_ports.extend(objects)
                target_token_indices.append(idx)
            idx += 1
        if not target_ports:
            report.warn(
                f"{clock_location(sdc_name, tcl_cmd.line_no)}: CLOCK_TARGET_NOT_GET_PORTS: "
                f"skipped clock command without positional get_ports target; "
                f"command: {compact_command(raw)}"
            )
            continue
        original_name = get_option(tokens, "-name") or sanitize_name(target_ports[0])
        parsed.append(
            ParsedClock(
                raw=raw,
                source_line=tcl_cmd.line_no,
                command=command,
                tokens=tokens,
                target_ports=target_ports,
                target_token_indices=target_token_indices,
                source_ports=source_ports,
                original_name=original_name,
                period=get_option(tokens, "-period"),
                waveform=get_option(tokens, "-waveform"),
                source_token=source_token,
            )
        )
    return parsed


def port_direction(inst: InstInfo, port: str) -> str:
    if port in inst.outputs:
        return "output"
    if port in inst.inputs:
        return "input"
    if port in inst.inouts:
        return "inout"
    return "unknown"


def from_whom_for(inst: InstInfo, port: str, direction: str) -> str:
    if direction == "input" and port in inst.inputs:
        return inst.inputs[port].from_whom
    if direction == "inout" and port in inst.inouts:
        return inst.inouts[port].connectivity
    return ""


def parse_connection(text: str) -> Tuple[str, str]:
    text = clean_cell(text)
    if not text:
        return "", ""
    if text.startswith("top."):
        return "top", text[4:]
    if re.match(r"^\d+'[bhdBHD][0-9a-fA-F_xXzZ]+$", text) or text in {"0", "1"}:
        return "const", text
    if "." in text:
        inst, port = text.split(".", 1)
        if inst and port:
            return inst, port
    return "unknown", text


def clock_name_for(inst_name: str, port: str) -> str:
    return sanitize_name(f"{inst_name}_{port}")


def top_clock_name(port: str) -> str:
    return sanitize_name(f"top_{port}")


def rewrite_object_token_for_inst(
    token: str,
    inst: InstInfo,
    report: Report,
    sdc_name: str,
    parsed: Optional[ParsedClock] = None,
) -> str:
    cmd, objects = parse_get_object(token)
    if cmd == "get_ports":
        return get_pins_obj([f"{inst.inst_name}/{obj}" for obj in objects])
    if cmd == "get_clocks":
        return token
    if cmd == "get_pins":
        message = f"source references get_pins in harden SDC; keeping as-is: {token}"
        if parsed:
            report.warn(harden_clock_issue(inst, parsed, "CLOCK_SOURCE_GET_PINS", message))
        else:
            report.warn(f"{sdc_name}: CLOCK_SOURCE_GET_PINS: {message}")
        return token
    return token


def rewrite_clock_command(
    parsed: ParsedClock,
    inst: InstInfo,
    new_name: str,
    target_object: str,
    name_map: Dict[str, str],
    report: Report,
) -> str:
    tokens = list(parsed.tokens)
    if tokens[0] == "create_generate_clock":
        tokens[0] = "create_generated_clock"
    has_name = False
    idx = 1
    while idx < len(tokens):
        tok = tokens[idx]
        if tok == "-name" and idx + 1 < len(tokens):
            tokens[idx + 1] = new_name
            has_name = True
            idx += 2
            continue
        if tok == "-source" and idx + 1 < len(tokens):
            tokens[idx + 1] = rewrite_object_token_for_inst(
                tokens[idx + 1],
                inst,
                report,
                inst.sdc_path.name if inst.sdc_path else inst.inst_name,
                parsed,
            )
            idx += 2
            continue
        if tok == "-master_clock" and idx + 1 < len(tokens):
            master = unbrace(tokens[idx + 1])
            tokens[idx + 1] = name_map.get(master, master)
            idx += 2
            continue
        idx += 1

    # Replace only positional target objects recorded by the parser. Do not
    # infer target from the last get_ports token because -source ordering is free.
    for target_idx in parsed.target_token_indices:
        if 0 <= target_idx < len(tokens):
            tokens[target_idx] = target_object

    if not has_name:
        tokens.insert(1, new_name)
        tokens.insert(1, "-name")
    return " ".join(tokens)


def command_kind(parsed: ParsedClock) -> str:
    if parsed.command == "create_clock":
        return "create_clock"
    if "-combinational" in parsed.tokens:
        return "generated_combinational"
    return "create_generated_clock"


def is_generated_clock(parsed: ParsedClock) -> bool:
    return parsed.command in {"create_generated_clock", "create_generate_clock"}


def test_like_clock_tokens(parsed: ParsedClock) -> List[str]:
    """Return advisory-only test-like tokens from clock names/ports.

    Do not use this to classify or drop clocks. Scenario ownership must come
    from integration data, not name guessing.
    """
    text = " ".join(
        [parsed.original_name] + parsed.target_ports + parsed.source_ports
    ).lower()
    tokens = set(part for part in re.split(r"[^a-z0-9]+", text) if part)
    return sorted(tokens & {"scan", "mbist", "bist", "jtag", "test"})


def process_instance(
    inst: InstInfo,
    report: Report,
) -> List[ClockRecord]:
    if not inst.sdc_path:
        return []
    try:
        text = read_text(inst.sdc_path)
    except Exception as exc:
        report.error(f"failed to read {inst.sdc_path.name} for {inst.inst_name}: {exc}")
        return []

    parsed_cmds = parse_clock_commands(text, report, inst.sdc_path.name)
    name_map: Dict[str, str] = {}
    for cmd in parsed_cmds:
        port = cmd.target_ports[0]
        direction = port_direction(inst, port)
        from_whom = from_whom_for(inst, port, direction)
        src_kind, src_obj = parse_connection(from_whom)
        if direction in {"output", "inout"}:
            name_map[cmd.original_name] = clock_name_for(inst.inst_name, port)
        elif direction == "input" and src_kind == "top":
            name_map[cmd.original_name] = top_clock_name(src_obj)
        elif direction == "input":
            name_map[cmd.original_name] = clock_name_for(inst.inst_name, port)

    records: List[ClockRecord] = []
    for cmd in parsed_cmds:
        port = cmd.target_ports[0]
        direction = port_direction(inst, port)
        if direction == "unknown":
            records.append(
                ClockRecord(
                    inst_name=inst.inst_name,
                    module_name=inst.module_name,
                    port_name=port,
                    direction=direction,
                    clock_name=name_map.get(cmd.original_name, clock_name_for(inst.inst_name, port)),
                    clock_kind=command_kind(cmd),
                    period=cmd.period,
                    waveform=cmd.waveform,
                    direct_source="",
                    root_source="",
                    from_whom="",
                    original_sdc=inst.sdc_path.name,
                    original_clock_name=cmd.original_name,
                    final_action="skipped",
                    note="clock target is not listed as Input/Output/Inout in owner sheet",
                    source_line=cmd.source_line,
                    original_command=cmd.raw,
                )
            )
            report.warn(
                harden_clock_issue(
                    inst,
                    cmd,
                    "CLOCK_TARGET_NOT_IN_OWNER_SHEET",
                    "target port is not listed as Input/Output/Inout in owner sheet",
                )
            )
            continue

        test_tokens = test_like_clock_tokens(cmd)
        if test_tokens:
            report.warn(
                harden_clock_issue(
                    inst,
                    cmd,
                    "CLOCK_TEST_LIKE_NAME_REVIEW",
                    "clock name/port contains test-like token(s) "
                    f"{', '.join(test_tokens)}; clock is not skipped, review scenario ownership",
                )
            )

        from_whom = from_whom_for(inst, port, direction)
        source_obj = source_object_from_cmd(cmd, inst)
        if is_generated_clock(cmd) and not source_obj:
            note = "generated clock has no parseable -source; fix harden SDC or use create_clock for an independent root clock"
            records.append(
                ClockRecord(
                    inst_name=inst.inst_name,
                    module_name=inst.module_name,
                    port_name=port,
                    direction=direction,
                    clock_name=name_map.get(cmd.original_name, clock_name_for(inst.inst_name, port)),
                    clock_kind=command_kind(cmd),
                    period=cmd.period,
                    waveform=cmd.waveform,
                    direct_source="",
                    root_source="",
                    from_whom=from_whom,
                    original_sdc=inst.sdc_path.name,
                    original_clock_name=cmd.original_name,
                    final_action="skipped",
                    note=note,
                    source_line=cmd.source_line,
                    original_command=cmd.raw,
                )
            )
            report.error(harden_clock_issue(inst, cmd, "CLOCK_GENERATED_MISSING_SOURCE", note))
            continue
        if direction == "input":
            src_kind, src_value = parse_connection(from_whom)
            if src_kind == "top":
                clock_name = top_clock_name(src_value)
                target_object = get_ports_obj([src_value])
                emitted = rewrite_clock_command(
                    cmd, inst, clock_name, target_object, name_map, report
                )
                records.append(
                    ClockRecord(
                        inst_name=inst.inst_name,
                        module_name=inst.module_name,
                        port_name=port,
                        direction=direction,
                        clock_name=clock_name,
                        clock_kind=command_kind(cmd),
                        period=cmd.period,
                        waveform=cmd.waveform,
                        direct_source=f"top/{src_value}",
                        root_source=f"top/{src_value}",
                        from_whom=from_whom,
                        original_sdc=inst.sdc_path.name,
                        original_clock_name=cmd.original_name,
                        final_action="emit_top_clock",
                        note="input clock comes from top/pad",
                        emitted_command=emitted,
                        producer_object=f"top/{src_value}",
                        source_line=cmd.source_line,
                        original_command=cmd.raw,
                    )
                )
            elif src_kind and src_kind not in {"unknown", "const"}:
                records.append(
                    ClockRecord(
                        inst_name=inst.inst_name,
                        module_name=inst.module_name,
                        port_name=port,
                        direction=direction,
                        clock_name=name_map.get(cmd.original_name, clock_name_for(inst.inst_name, port)),
                        clock_kind=command_kind(cmd),
                        period=cmd.period,
                        waveform=cmd.waveform,
                        direct_source=f"{inst.inst_name}/{port}",
                        root_source="",
                        from_whom=from_whom,
                        original_sdc=inst.sdc_path.name,
                        original_clock_name=cmd.original_name,
                        final_action="check_only",
                        note="input clock comes from upstream harden output; no create_clock emitted",
                        producer_object=f"{inst.inst_name}/{port}",
                        source_line=cmd.source_line,
                        original_command=cmd.raw,
                    )
                )
            else:
                note = "input clock has no valid From Whom clock source"
                records.append(
                    ClockRecord(
                        inst_name=inst.inst_name,
                        module_name=inst.module_name,
                        port_name=port,
                        direction=direction,
                        clock_name=name_map.get(cmd.original_name, clock_name_for(inst.inst_name, port)),
                        clock_kind=command_kind(cmd),
                        period=cmd.period,
                        waveform=cmd.waveform,
                        direct_source="",
                        root_source="",
                        from_whom=from_whom,
                        original_sdc=inst.sdc_path.name,
                        original_clock_name=cmd.original_name,
                        final_action="skipped",
                        note=note,
                        source_line=cmd.source_line,
                        original_command=cmd.raw,
                    )
                )
                report.warn(harden_clock_issue(inst, cmd, "CLOCK_INPUT_INVALID_FROM_WHOM", note))
            continue

        if direction == "inout":
            src_kind, src_value = parse_connection(from_whom)
            if src_kind == "top" and cmd.command == "create_clock":
                clock_name = top_clock_name(src_value)
                emitted = rewrite_clock_command(
                    cmd, inst, clock_name, get_ports_obj([src_value]), name_map, report
                )
                records.append(
                    ClockRecord(
                        inst_name=inst.inst_name,
                        module_name=inst.module_name,
                        port_name=port,
                        direction=direction,
                        clock_name=clock_name,
                        clock_kind=command_kind(cmd),
                        period=cmd.period,
                        waveform=cmd.waveform,
                        direct_source=f"top/{src_value}",
                        root_source=f"top/{src_value}",
                        from_whom=from_whom,
                        original_sdc=inst.sdc_path.name,
                        original_clock_name=cmd.original_name,
                        final_action="emit_top_clock",
                        note="inout clock connected to top/pad",
                        emitted_command=emitted,
                        producer_object=f"top/{src_value}",
                        source_line=cmd.source_line,
                        original_command=cmd.raw,
                    )
                )
            else:
                report.warn(
                    harden_clock_issue(
                        inst,
                        cmd,
                        "CLOCK_INOUT_NEEDS_REVIEW",
                        "inout clock needs manual review",
                    )
                )
            continue

        clock_name = clock_name_for(inst.inst_name, port)
        target_object = get_pins_obj([f"{inst.inst_name}/{port}"])
        emitted = rewrite_clock_command(cmd, inst, clock_name, target_object, name_map, report)
        records.append(
            ClockRecord(
                inst_name=inst.inst_name,
                module_name=inst.module_name,
                port_name=port,
                direction=direction,
                clock_name=clock_name,
                clock_kind=command_kind(cmd),
                period=cmd.period,
                waveform=cmd.waveform,
                direct_source=source_obj,
                root_source="",
                from_whom=from_whom,
                original_sdc=inst.sdc_path.name,
                original_clock_name=cmd.original_name,
                final_action="emit_output_clock",
                note="output clock emitted",
                emitted_command=emitted,
                is_forwarded="-combinational" in cmd.tokens,
                producer_object=f"{inst.inst_name}/{port}",
                source_line=cmd.source_line,
                original_command=cmd.raw,
            )
        )
    return records


def virtual_clock_records(specs: Sequence[VirtualClockSpec]) -> List[ClockRecord]:
    records: List[ClockRecord] = []
    for spec in specs:
        parts = ["create_clock", "-name", spec.clock_name, "-period", spec.period]
        if spec.waveform:
            parts.extend(["-waveform", "{" + unbrace(spec.waveform) + "}"])
        command = " ".join(parts)
        records.append(
            ClockRecord(
                inst_name="",
                module_name="",
                port_name="",
                direction="virtual",
                clock_name=spec.clock_name,
                clock_kind="virtual_clock",
                period=spec.period,
                waveform=spec.waveform,
                direct_source=f"virtual/{spec.clock_name}",
                root_source=f"virtual/{spec.clock_name}",
                from_whom="",
                original_sdc=spec.source_file,
                original_clock_name=spec.clock_name,
                final_action="emit_virtual_clock",
                note=spec.note or "virtual clock emitted from virtual clock table",
                emitted_command=command,
                producer_object=f"virtual/{spec.clock_name}",
            )
        )
    return records


def source_object_from_cmd(cmd: ParsedClock, inst: InstInfo) -> str:
    if cmd.source_ports:
        return f"{inst.inst_name}/{cmd.source_ports[0]}"
    if cmd.source_token:
        get_cmd, objects = parse_get_object(cmd.source_token)
        if get_cmd == "get_pins" and objects:
            return objects[0]
        if get_cmd == "get_clocks" and objects:
            return "clock:" + objects[0]
    return ""


def dedupe_top_clocks(records: List[ClockRecord], report: Report) -> None:
    first_by_object: Dict[str, ClockRecord] = {}
    for rec in records:
        if rec.final_action != "emit_top_clock":
            continue
        key = rec.producer_object
        if key not in first_by_object:
            first_by_object[key] = rec
            continue
        first = first_by_object[key]
        rec.final_action = "duplicate_top_clock"
        rec.emitted_command = ""
        rec.note = f"duplicate top clock; first emitted by {first.inst_name}/{first.port_name}"
        if first.period and rec.period and first.period != rec.period:
            report.warn(
                f"{key}: period mismatch among top clock users: "
                f"{first.inst_name}/{first.port_name}={first.period}, "
                f"{rec.inst_name}/{rec.port_name}={rec.period}"
            )


def dedupe_virtual_clocks(records: List[ClockRecord], report: Report) -> None:
    first_by_name: Dict[str, ClockRecord] = {}
    for rec in records:
        if rec.final_action != "emit_virtual_clock":
            continue
        key = rec.clock_name
        if key not in first_by_name:
            first_by_name[key] = rec
            continue
        first = first_by_name[key]
        rec.final_action = "duplicate_virtual_clock"
        rec.emitted_command = ""
        rec.note = f"duplicate virtual clock; first emitted from {first.original_sdc}"
        if first.period and rec.period and first.period != rec.period:
            report.warn(
                f"virtual clock {key}: period mismatch {first.period} vs {rec.period}"
            )


def build_instance_lookup(instances: Dict[str, InstInfo]) -> Dict[str, InstInfo]:
    return {inst.inst_name: inst for inst in instances.values()}


def build_producer_map(records: List[ClockRecord]) -> Dict[str, ClockRecord]:
    result: Dict[str, ClockRecord] = {}
    for rec in records:
        if rec.final_action in {"emit_output_clock", "emit_top_clock"} and rec.producer_object:
            result[rec.producer_object] = rec
    return result


def resolve_source_connection(obj: str, instances: Dict[str, InstInfo]) -> str:
    if not obj or obj.startswith("top/") or obj.startswith("clock:"):
        return obj
    if "/" not in obj:
        return obj
    inst_name, port = obj.split("/", 1)
    inst = instances.get(inst_name)
    if not inst:
        return obj
    if port in inst.inputs:
        kind, value = parse_connection(inst.inputs[port].from_whom)
        if kind == "top":
            return f"top/{value}"
        if kind not in {"", "unknown", "const"}:
            return f"{kind}/{value}"
    return obj


def compute_root_sources(records: List[ClockRecord], instances: Dict[str, InstInfo]) -> None:
    producers = build_producer_map(records)

    def root_for_object(obj: str, seen: Optional[set] = None) -> str:
        if not obj:
            return ""
        if seen is None:
            seen = set()
        if obj in seen:
            return obj
        seen.add(obj)
        connected = resolve_source_connection(obj, instances)
        if connected != obj:
            return root_for_object(connected, seen)
        producer = producers.get(obj)
        if not producer:
            return obj
        if producer.is_forwarded and producer.direct_source:
            return root_for_object(producer.direct_source, seen)
        return producer.producer_object or obj

    for rec in records:
        if rec.root_source:
            continue
        if rec.final_action == "emit_output_clock":
            rec.root_source = root_for_object(rec.direct_source) if rec.is_forwarded else rec.producer_object
        elif rec.final_action == "check_only":
            rec.root_source = root_for_object(rec.direct_source)


def run_checks(records: List[ClockRecord], instances: Dict[str, InstInfo], report: Report) -> None:
    producers = build_producer_map(records)
    for rec in records:
        if rec.final_action != "check_only":
            continue
        kind, value = parse_connection(rec.from_whom)
        if kind in {"", "unknown", "const"}:
            report.warn(
                record_clock_issue(
                    rec,
                    "CLOCK_INPUT_INVALID_FROM_WHOM",
                    f"invalid clock source in integration table: {rec.from_whom}",
                )
            )
            continue
        upstream_obj = f"{kind}/{value}"
        upstream = producers.get(upstream_obj)
        if not upstream:
            report.warn(
                record_clock_issue(
                    rec,
                    "CLOCK_UPSTREAM_NOT_EMITTED",
                    f"upstream clock {upstream_obj} was not emitted",
                )
            )
            continue
        if rec.period and upstream.period and rec.period != upstream.period:
            report.warn(
                record_clock_issue(
                    rec,
                    "CLOCK_PERIOD_MISMATCH",
                    f"period {rec.period} differs from upstream {upstream_obj} period {upstream.period}",
                )
            )


def write_sdc(path: Path, records: List[ClockRecord], report: Report) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    emitted = [
        rec
        for rec in records
        if rec.final_action in {"emit_top_clock", "emit_output_clock", "emit_virtual_clock"}
        and rec.emitted_command
    ]
    lines = [
        "################################################################################",
        "# Auto-generated SoC func clock constraints",
        "# Source: local info_all.xlsx, port_*.xlsx and harden SoC integration SDC files",
        "################################################################################",
        "",
    ]
    for rec in emitted:
        if rec.final_action == "emit_virtual_clock":
            lines.append(f"# virtual clock {rec.clock_name} from {rec.original_sdc}")
        else:
            lines.append(f"# {rec.inst_name}/{rec.port_name} from {rec.original_sdc}")
        if rec.from_whom:
            lines.append(f"# From Whom: {rec.from_whom}")
        if rec.note and rec.final_action == "emit_virtual_clock":
            lines.append(f"# Note: {rec.note}")
        lines.append(rec.emitted_command)
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    report.info(f"wrote {len(emitted)} clock command(s) to {path}")


def write_inventory(path: Path, records: List[ClockRecord]) -> None:
    fields = [
        "inst_name",
        "module_name",
        "port_name",
        "direction",
        "clock_name",
        "clock_kind",
        "period",
        "waveform",
        "direct_source",
        "root_source",
        "from_whom",
        "original_sdc",
        "source_line",
        "original_clock_name",
        "original_command",
        "final_action",
        "note",
    ]
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fields)
        writer.writeheader()
        for rec in records:
            writer.writerow({field: getattr(rec, field) for field in fields})


def write_report(path: Path, report: Report, records: List[ClockRecord]) -> None:
    action_counts: Dict[str, int] = {}
    for rec in records:
        action_counts[rec.final_action] = action_counts.get(rec.final_action, 0) + 1
    lines = [
        "01_soc_clocks extraction report",
        "================================",
        "",
        f"Warnings: {report.warning_count}",
        f"Errors  : {report.error_count}",
        "",
        "Action counts:",
    ]
    for action in sorted(action_counts):
        lines.append(f"  {action}: {action_counts[action]}")
    lines.extend(["", "Messages:"])
    lines.extend(report.lines or ["INFO: no messages"])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def default_port_files(cwd: Path, info_name: str) -> List[Path]:
    paths = []
    for item in sorted(cwd.glob("*.xlsx")):
        if item.name == info_name:
            continue
        if item.name.startswith("~$"):
            continue
        if item.name.startswith("port_"):
            paths.append(item)
    return paths


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate common/01_soc_clocks.sdc from local harden SDC and integration xlsx files."
    )
    parser.add_argument("--info", default="info_all.xlsx", help="integration info workbook")
    parser.add_argument(
        "--port-files",
        nargs="*",
        help="owner port workbook(s); default: local port_*.xlsx",
    )
    parser.add_argument(
        "--output",
        default="common/01_soc_clocks.sdc",
        help="output SoC clock SDC path",
    )
    parser.add_argument(
        "--inventory",
        default="clock_inventory.csv",
        help="output clock inventory CSV path",
    )
    parser.add_argument(
        "--report",
        default="clock_check_report.txt",
        help="output extraction/check report path",
    )
    parser.add_argument(
        "--virtual-clocks",
        default="virtual_clocks.csv",
        help=(
            "optional local CSV for virtual clocks; columns: clock_name/name, period, "
            "optional waveform, note"
        ),
    )
    parser.add_argument(
        "--no-write-sdc",
        action="store_true",
        help="only write inventory/report, not common/01_soc_clocks.sdc",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    cwd = Path.cwd()
    report = Report()

    info_path = cwd / args.info
    if not info_path.is_file():
        print(f"ERROR: info workbook not found in execution directory: {info_path}", file=sys.stderr)
        return 2

    try:
        instances = read_info_all(info_path, report)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.port_files:
        port_files = [cwd / item for item in args.port_files]
    else:
        port_files = default_port_files(cwd, info_path.name)
    if not port_files:
        print("ERROR: no owner port workbook found. Expected local port_*.xlsx or --port-files.", file=sys.stderr)
        return 2
    missing_ports = [str(path) for path in port_files if not path.is_file()]
    if missing_ports:
        print(f"ERROR: port workbook(s) not found: {', '.join(missing_ports)}", file=sys.stderr)
        return 2

    sheets = read_port_workbooks(port_files, report)
    attach_port_data(instances, sheets, report)
    resolve_sdc_paths(instances, cwd, report)

    records: List[ClockRecord] = []
    if args.virtual_clocks:
        records.extend(virtual_clock_records(read_virtual_clock_csv(cwd / args.virtual_clocks, report)))
    for inst_name in sorted(instances):
        records.extend(process_instance(instances[inst_name], report))

    dedupe_virtual_clocks(records, report)
    dedupe_top_clocks(records, report)
    inst_lookup = build_instance_lookup(instances)
    compute_root_sources(records, inst_lookup)
    run_checks(records, inst_lookup, report)

    if not args.no_write_sdc:
        write_sdc(cwd / args.output, records, report)
    write_inventory(cwd / args.inventory, records)
    write_report(cwd / args.report, report, records)

    print(f"Instances : {len(instances)}")
    print(f"Records   : {len(records)}")
    if not args.no_write_sdc:
        print(f"SDC       : {cwd / args.output}")
    print(f"Inventory : {cwd / args.inventory}")
    print(f"Report    : {cwd / args.report}")
    print(f"Warnings  : {report.warning_count}")
    print(f"Errors    : {report.error_count}")
    return 1 if report.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
