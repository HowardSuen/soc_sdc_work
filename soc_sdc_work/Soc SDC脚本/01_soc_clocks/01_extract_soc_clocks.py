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
import hashlib
import json
import os
import platform
import re
import shlex
import sys
import traceback
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    from dataclasses import dataclass, field
except ImportError:  # pragma: no cover - Python 3.6 compatibility path
    class _CompatField:
        def __init__(self, default_factory=None):
            self.default_factory = default_factory

    def field(default_factory=None):
        return _CompatField(default_factory=default_factory)

    def dataclass(_cls=None, frozen=False):
        def wrap(cls):
            annotations = getattr(cls, "__annotations__", {})
            names = list(annotations.keys())
            defaults = {}
            factories = {}
            for name in names:
                if hasattr(cls, name):
                    value = getattr(cls, name)
                    if isinstance(value, _CompatField):
                        factories[name] = value.default_factory
                        delattr(cls, name)
                    else:
                        defaults[name] = value

            def __init__(self, *args, **kwargs):
                if len(args) > len(names):
                    raise TypeError("too many positional arguments")
                values = {}
                for name, value in zip(names, args):
                    values[name] = value
                for name in names[len(args):]:
                    if name in kwargs:
                        values[name] = kwargs.pop(name)
                    elif name in factories:
                        values[name] = factories[name]()
                    elif name in defaults:
                        values[name] = defaults[name]
                    else:
                        raise TypeError("missing required argument: " + name)
                if kwargs:
                    raise TypeError("unexpected argument: " + sorted(kwargs)[0])
                for name in names:
                    object.__setattr__(self, name, values[name])

            def __eq__(self, other):
                if other.__class__ is not cls:
                    return False
                return all(getattr(self, name) == getattr(other, name) for name in names)

            cls.__init__ = __init__
            cls.__eq__ = __eq__
            if frozen:
                def __hash__(self):
                    return hash(tuple(getattr(self, name) for name in names))
                cls.__hash__ = __hash__
            else:
                cls.__hash__ = None
            return cls

        if _cls is None:
            return wrap
        return wrap(_cls)

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

EMITTED_CLOCK_ACTIONS = {"emit_top_clock", "emit_output_clock", "emit_virtual_clock"}


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
    sdc_availability: str = "unknown"
    sdc_note: str = ""
    sdc_digest: str = ""


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
    source_type: str = ""
    source_file: str = ""
    target_object: str = ""
    final_sdc_digest: str = ""
    run_completeness: str = ""
    missing_instances: str = ""


@dataclass
class VirtualClockSpec:
    clock_name: str
    period: str
    waveform: str = ""
    note: str = ""
    source_file: str = ""


@dataclass(frozen=True)
class PortKey:
    inst_name: str
    direction: str
    port_name: str


@dataclass
class PortLookup:
    direction: str
    canonical_port: str
    declared_port: str
    bit_index: str = ""
    is_range: bool = False
    info: Optional[PortInfo] = None


@dataclass
class ConnectionEdge:
    connection_id: str
    src_instance: str
    src_direction: str
    src_port: str
    dst_instance: str
    dst_direction: str
    dst_port: str
    connection_type: str = ""
    validation_status: str = ""
    schema_version: str = ""
    scenario_scope: str = ""
    source_row: int = 0


@dataclass
class SocClockCommand:
    raw: str
    source_line: int
    command: str
    tokens: List[str]
    clock_name: str
    period: str
    waveform: str
    target_token: str
    target_kind: str
    target_objects: List[str]
    source_token: str
    master_clock: str
    has_add: bool = False


@dataclass
class HardenSdcManifestEntry:
    scenario: str
    inst_name: str
    module_name: str
    sdc_path: str
    availability_status: str
    note: str
    source_row: int


@dataclass
class RunCompleteness:
    status: str
    available_instances: List[str] = field(default_factory=list)
    missing_instances: List[str] = field(default_factory=list)
    not_required_instances: List[str] = field(default_factory=list)
    manifest_path: str = ""
    manifest_digest: str = ""

    @property
    def available_count(self) -> int:
        return len(self.available_instances)

    @property
    def missing_count(self) -> int:
        return len(self.missing_instances)

    @property
    def not_required_count(self) -> int:
        return len(self.not_required_instances)


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


def _author_part_a() -> str:
    return chr(72) + chr(111)


def _author_part_b() -> str:
    return chr(119) + chr(97)


def _author_part_c() -> str:
    return chr(114) + chr(100)


def author_name() -> str:
    return _author_part_a() + _author_part_b() + _author_part_c()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        while True:
            chunk = file_obj.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.tmp.%s" % (path.name, os.getpid()))
    try:
        tmp.write_text(text, encoding=encoding)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


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


def parse_endpoint_key(value: str) -> Tuple[str, str, str]:
    value = clean_cell(value)
    if not value:
        return "", "", ""
    parts = value.split(":", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return "", "", ""


def scenario_scope_matches(value: str, scenario: str) -> bool:
    scopes = {
        item
        for item in re.split(r"[,;|\s]+", clean_cell(value).lower())
        if item
    }
    return "common" in scopes or scenario.lower() in scopes


def read_connection_inventory(
    path: Path,
    report: Report,
    scenario: str = "common",
    strict_target: bool = False,
) -> Dict[Tuple[str, str], ConnectionEdge]:
    edges: Dict[Tuple[str, str], ConnectionEdge] = {}
    seen_connection_ids: Dict[str, int] = {}
    if not path.is_file():
        return edges
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        if not reader.fieldnames:
            message = f"{path}: CONNECTION_INVENTORY_NO_HEADER"
            (report.error if strict_target else report.warn)(message)
            return edges
        if strict_target:
            required = {
                "schema_version",
                "connection_id",
                "scenario_scope",
                "connection_type",
                "src_instance",
                "src_direction",
                "src_port",
                "src_bit_index",
                "src_endpoint_key",
                "src_soc_object",
                "dst_instance",
                "dst_direction",
                "dst_port",
                "dst_bit_index",
                "dst_endpoint_key",
                "dst_soc_object",
                "fanout_index",
                "range_source_expr",
                "range_sink_expr",
                "bit_pair_order",
                "source_workbook",
                "source_sheet",
                "source_row",
                "validation_status",
                "owner_hint",
                "note",
            }
            missing_fields = sorted(required - set(reader.fieldnames))
            if missing_fields:
                report.error(
                    f"{path}: CONNECTION_INVENTORY_SCHEMA_UNSUPPORTED: missing field(s): "
                    + ", ".join(missing_fields)
                )
        for row_idx, row in enumerate(reader, start=2):
            schema_version = clean_cell(row.get("schema_version"))
            connection_id = clean_cell(row.get("connection_id"))
            if strict_target:
                if schema_version != "1":
                    report.error(
                        f"{path.name} row {row_idx}: CONNECTION_SCHEMA_VERSION_UNSUPPORTED: "
                        f"{schema_version or '<empty>'}"
                    )
                    continue
                if not connection_id:
                    report.error(f"{path.name} row {row_idx}: CONNECTION_ID_MISSING")
                    continue
                if connection_id in seen_connection_ids:
                    report.error(
                        f"{path.name} row {row_idx}: CONNECTION_ID_DUPLICATE: {connection_id}; "
                        f"first row={seen_connection_ids[connection_id]}"
                    )
                    continue
                seen_connection_ids[connection_id] = row_idx
            scenario_scope = clean_cell(row.get("scenario_scope"))
            if strict_target:
                if not scenario_scope:
                    report.error(
                        f"{path.name} row {row_idx}: CONNECTION_SCENARIO_SCOPE_MISSING"
                    )
                    continue
                if not scenario_scope_matches(scenario_scope, scenario):
                    continue
            dst_inst = clean_cell(row.get("dst_instance"))
            dst_dir = clean_cell(row.get("dst_direction"))
            dst_port = clean_cell(row.get("dst_port"))
            src_inst = clean_cell(row.get("src_instance"))
            src_dir = clean_cell(row.get("src_direction"))
            src_port = clean_cell(row.get("src_port"))
            if not (dst_inst and dst_port):
                key_inst, key_dir, key_port = parse_endpoint_key(clean_cell(row.get("dst_endpoint_key")))
                dst_inst = dst_inst or key_inst
                dst_dir = dst_dir or key_dir
                dst_port = dst_port or key_port
            if not (src_inst and src_port):
                key_inst, key_dir, key_port = parse_endpoint_key(clean_cell(row.get("src_endpoint_key")))
                src_inst = src_inst or key_inst
                src_dir = src_dir or key_dir
                src_port = src_port or key_port
            if not (dst_inst and dst_port and src_port):
                message = f"{path.name} row {row_idx}: CONNECTION_ENDPOINT_INCOMPLETE"
                (report.error if strict_target else report.warn)(message)
                continue
            if strict_target:
                if re.search(r"[\*:]", src_port) or re.search(r"[\*:]", dst_port):
                    report.error(
                        f"{path.name} row {row_idx}: CONNECTION_ENDPOINT_NOT_CANONICAL_BIT: "
                        f"{src_inst}/{src_port} -> {dst_inst}/{dst_port}"
                    )
                    continue
                validation_status = clean_cell(row.get("validation_status")).lower()
                if validation_status not in {"matched", "ok", "valid"}:
                    report.warn(
                        f"{path.name} row {row_idx}: CONNECTION_EDGE_NOT_MATCHED: "
                        f"status={validation_status or '<empty>'}; edge ignored"
                    )
                    continue
            key = (dst_inst, dst_port)
            edge = ConnectionEdge(
                connection_id=connection_id,
                src_instance=src_inst,
                src_direction=src_dir,
                src_port=src_port,
                dst_instance=dst_inst,
                dst_direction=dst_dir,
                dst_port=dst_port,
                connection_type=clean_cell(row.get("connection_type")),
                validation_status=clean_cell(row.get("validation_status")),
                schema_version=schema_version,
                scenario_scope=scenario_scope,
                source_row=row_idx,
            )
            if key in edges:
                message = (
                    f"{path.name} row {row_idx}: CONNECTION_DESTINATION_MULTI_DRIVER: "
                    f"duplicate dst edge for {dst_inst}/{dst_port}; first="
                    f"{edges[key].connection_id or '<unnamed>'}, second={edge.connection_id or '<unnamed>'}"
                )
                (report.error if strict_target else report.warn)(message)
                continue
            edges[key] = edge
    report.info(
        f"loaded {len(edges)} connection edge(s) from {path} for scenario={scenario}"
    )
    return edges


def attach_target_port(
    instances: Dict[str, InstInfo],
    inst_name: str,
    direction: str,
    port: str,
    report: Report,
    source: str,
) -> None:
    if inst_name not in instances:
        return
    maps = {
        "input": instances[inst_name].inputs,
        "output": instances[inst_name].outputs,
        "inout": instances[inst_name].inouts,
    }
    if direction not in maps:
        report.error(
            f"{source}: TARGET_PORT_DIRECTION_INVALID: {inst_name}/{port} direction={direction or '<empty>'}"
        )
        return
    for other_direction, port_map in maps.items():
        if other_direction != direction and port in port_map:
            report.error(
                f"{source}: TARGET_PORT_DIRECTION_CONFLICT: {inst_name}/{port} "
                f"appears as {other_direction} and {direction}"
            )
            return
    maps[direction].setdefault(port, PortInfo(name=port, width="1", used_width="1"))


def attach_ports_from_connections(
    instances: Dict[str, InstInfo],
    edges: Dict[Tuple[str, str], ConnectionEdge],
    report: Report,
) -> None:
    for edge in edges.values():
        source = f"connection_inventory.csv row {edge.source_row}"
        attach_target_port(
            instances, edge.src_instance, edge.src_direction, edge.src_port, report, source
        )
        attach_target_port(
            instances, edge.dst_instance, edge.dst_direction, edge.dst_port, report, source
        )


def read_target_pending_ports(
    pending_dir: Path,
    instances: Dict[str, InstInfo],
    report: Report,
    required: bool,
) -> None:
    if not pending_dir.is_dir():
        if required:
            report.error(f"{pending_dir}: TARGET_UPSTREAM_PENDING_MISSING")
        else:
            report.warn(
                f"{pending_dir}: TARGET_PENDING_UNAVAILABLE_FOR_PORT_VALIDATION: "
                "only ports present in connection inventory can be validated"
            )
        return
    for inst_name in sorted(instances):
        path = pending_dir / f"{inst_name}.ports"
        if not path.is_file():
            if required:
                report.error(f"{path}: TARGET_PENDING_INSTANCE_FILE_MISSING")
            continue
        seen: Set[Tuple[str, str]] = set()
        for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                report.error(f"{path.name}:{line_no}: TARGET_PENDING_LINE_INVALID: {line}")
                continue
            direction, port = parts[0], parts[1]
            if direction not in {"input", "output", "inout"}:
                report.error(
                    f"{path.name}:{line_no}: TARGET_PENDING_DIRECTION_INVALID: {direction}"
                )
                continue
            if re.search(r"[\*:]", port):
                report.error(
                    f"{path.name}:{line_no}: TARGET_PENDING_PORT_NOT_CANONICAL_BIT: {port}"
                )
                continue
            key = (direction, port)
            if key in seen:
                report.error(
                    f"{path.name}:{line_no}: TARGET_PENDING_DUPLICATE_PORT: {direction} {port}"
                )
                continue
            seen.add(key)
            attach_target_port(
                instances, inst_name, direction, port, report, f"{path.name}:{line_no}"
            )


def attach_ports_from_previous_01_removed(
    log_dir: Path,
    instances: Dict[str, InstInfo],
    report: Report,
) -> None:
    if not log_dir.is_dir():
        return
    for path in sorted(log_dir.glob("*.removed")):
        for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            key = removed_line_key(raw_line)
            if key is None or key.inst_name not in instances:
                continue
            attach_target_port(
                instances,
                key.inst_name,
                key.direction,
                key.port_name,
                report,
                f"{path.name}:{line_no}",
            )


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
    sheet_names_by_norm: Dict[str, List[str]] = {}
    for sheet_name in sheets:
        sheet_names_by_norm.setdefault(sheet_name.strip().lower(), []).append(sheet_name)
    claimed_sheets: Set[str] = set()

    for inst in instances.values():
        data = sheets.get(inst.inst_name)
        matched_sheet = inst.inst_name if data else ""
        if not data:
            candidates = sheet_names_by_norm.get(inst.inst_name.strip().lower(), [])
            if len(candidates) == 1:
                matched_sheet = candidates[0]
                data = sheets[matched_sheet]
                report.warn(
                    f"port sheet {matched_sheet!r} matched instance {inst.inst_name!r} "
                    "by case/space-insensitive fallback"
                )
            elif len(candidates) > 1:
                report.error(
                    f"multiple port sheets match instance {inst.inst_name!r} by case/space-insensitive fallback: "
                    f"{', '.join(repr(name) for name in candidates)}"
                )
        if not data:
            report.warn(f"no owner port sheet found for instance {inst.inst_name}")
            continue
        claimed_sheets.add(matched_sheet)
        inst.inputs = data["inputs"]
        inst.outputs = data["outputs"]
        inst.inouts = data["inouts"]

    for sheet_name in sorted(set(sheets) - claimed_sheets):
        report.warn(f"port workbook sheet {sheet_name!r} does not match any inst_name; ignored")


def resolve_manifest_path(run_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else run_root / path


def apply_harden_sdc_manifest(
    instances: Dict[str, InstInfo],
    manifest_path: Path,
    run_root: Path,
    scenario: str,
    require_complete: bool,
    report: Report,
    authoritative: bool = False,
) -> RunCompleteness:
    if not manifest_path.is_file():
        report.error(f"{manifest_path}: HARDEN_SDC_MANIFEST_MISSING: required target runtime manifest is absent")
        return RunCompleteness(status="invalid", manifest_path=str(manifest_path.resolve()))

    required_fields = {"scenario", "inst_name", "module_name", "availability_status"}
    entries: Dict[str, HardenSdcManifestEntry] = {}
    manifest_digest = sha256_file(manifest_path)
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        fields = set(reader.fieldnames or [])
        missing_fields = sorted(required_fields - fields)
        if missing_fields:
            report.error(
                f"{manifest_path}: HARDEN_SDC_MANIFEST_SCHEMA_ERROR: missing field(s): {', '.join(missing_fields)}"
            )
        if "sdc_path" not in fields and "resolved_sdc_path" not in fields:
            report.error(
                f"{manifest_path}: HARDEN_SDC_MANIFEST_SCHEMA_ERROR: missing sdc_path "
                "(legacy resolved_sdc_path is also accepted)"
            )
        for row_idx, row in enumerate(reader, start=2):
            row_scenario = clean_cell(row.get("scenario"))
            inst_name = clean_cell(row.get("inst_name"))
            if not inst_name:
                report.error(f"{manifest_path.name} row {row_idx}: HARDEN_SDC_MANIFEST_EMPTY_INSTANCE")
                continue
            if row_scenario != scenario:
                report.error(
                    f"{manifest_path.name} row {row_idx}: HARDEN_SDC_MANIFEST_SCENARIO_MISMATCH: "
                    f"row scenario={row_scenario or '<empty>'}, requested={scenario}"
                )
                continue
            if inst_name in entries:
                report.error(
                    f"{manifest_path.name} row {row_idx}: HARDEN_SDC_MANIFEST_DUPLICATE_INSTANCE: "
                    f"duplicate ({inst_name}, {scenario}) mapping"
                )
                continue
            entry = HardenSdcManifestEntry(
                scenario=row_scenario,
                inst_name=inst_name,
                module_name=clean_cell(row.get("module_name")),
                sdc_path=(
                    clean_cell(row.get("sdc_path"))
                    or clean_cell(row.get("resolved_sdc_path"))
                    or clean_cell(row.get("requested_sdc_path"))
                ),
                availability_status=clean_cell(row.get("availability_status")).lower(),
                note=clean_cell(row.get("note")),
                source_row=row_idx,
            )
            entries[inst_name] = entry

    if authoritative:
        for inst_name, entry in sorted(entries.items()):
            if not entry.module_name:
                report.error(
                    f"{manifest_path.name} row {entry.source_row}: HARDEN_SDC_MANIFEST_MODULE_EMPTY: {inst_name}"
                )
            instances[inst_name] = InstInfo(
                module_name=entry.module_name or inst_name,
                inst_name=inst_name,
            )
        report.info(f"loaded {len(instances)} target instance(s) from {manifest_path.name}")
    else:
        for inst_name in sorted(set(entries) - set(instances)):
            report.error(
                f"{manifest_path.name} row {entries[inst_name].source_row}: HARDEN_SDC_MANIFEST_ORPHAN_INSTANCE: "
                f"{inst_name} is not present in info_all.xlsx"
            )

    available: List[str] = []
    missing: List[str] = []
    not_required: List[str] = []
    for inst_name, inst in sorted(instances.items()):
        entry = entries.get(inst_name)
        if entry is None:
            report.error(
                f"{manifest_path.name}: HARDEN_SDC_MANIFEST_INSTANCE_MISSING: "
                f"no ({inst_name}, {scenario}) row"
            )
            inst.sdc_availability = "invalid"
            continue
        inst.sdc_availability = entry.availability_status
        inst.sdc_note = entry.note
        if entry.module_name and entry.module_name != inst.module_name:
            report.error(
                f"{manifest_path.name} row {entry.source_row}: HARDEN_SDC_MANIFEST_MODULE_MISMATCH: "
                f"{inst_name} module={entry.module_name}, info_all={inst.module_name}"
            )
        if entry.availability_status == "available":
            available.append(inst_name)
            if not entry.sdc_path:
                report.error(
                    f"{manifest_path.name} row {entry.source_row}: HARDEN_SDC_MANIFEST_AVAILABLE_PATH_EMPTY: {inst_name}"
                )
                continue
            sdc_path = resolve_manifest_path(run_root, entry.sdc_path)
            if not sdc_path.is_file():
                report.error(
                    f"{manifest_path.name} row {entry.source_row}: HARDEN_SDC_MANIFEST_AVAILABLE_FILE_MISSING: "
                    f"{inst_name} resolved path does not exist: {sdc_path}"
                )
                continue
            actual_digest = sha256_file(sdc_path)
            inst.sdc_path = sdc_path
            inst.sdc_digest = actual_digest
            report.info(
                f"manifest selected {inst_name}: status=available path={sdc_path.resolve()} digest={actual_digest}"
            )
        elif entry.availability_status == "missing":
            missing.append(inst_name)
            requested = entry.sdc_path or "<unspecified>"
            report.warn(
                f"{manifest_path.name} row {entry.source_row}: HARDEN_SDC_MISSING: "
                f"{inst_name} requested={requested}; pending ports are preserved"
            )
        elif entry.availability_status == "not_required":
            not_required.append(inst_name)
            report.info(f"manifest marks {inst_name} as not_required: {entry.note or '<no note>'}")
        else:
            report.error(
                f"{manifest_path.name} row {entry.source_row}: HARDEN_SDC_MANIFEST_STATUS_INVALID: "
                f"{inst_name} status={entry.availability_status or '<empty>'}"
            )

    completeness_status = "partial" if missing else "complete"
    completeness = RunCompleteness(
        status=completeness_status,
        available_instances=available,
        missing_instances=missing,
        not_required_instances=not_required,
        manifest_path=str(manifest_path.resolve()),
        manifest_digest=manifest_digest,
    )

    if require_complete and missing:
        report.error(
            "HARDEN_SDC_COMPLETENESS_REQUIRED: missing required harden SDC instance(s): "
            + ", ".join(missing)
        )
    report.info(
        f"Run completeness: {completeness.status}; available={len(available)} "
        f"missing={len(missing)} not_required={len(not_required)}"
    )
    return completeness


def resolve_sdc_paths(instances: Dict[str, InstInfo], cwd: Path, report: Report) -> RunCompleteness:
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
            inst.sdc_availability = "available"
            inst.sdc_digest = sha256_file(inst.sdc_path)
        elif len(unique_matches) > 1:
            inst.sdc_path = unique_matches[0]
            inst.sdc_availability = "available"
            inst.sdc_digest = sha256_file(inst.sdc_path)
            report.warn(
                f"multiple SDC candidates for {inst.inst_name}: "
                f"{', '.join(p.name for p in unique_matches)}; using {inst.sdc_path.name}"
            )
        else:
            inst.sdc_availability = "missing"
            report.warn(
                f"HARDEN_SDC_MISSING: no SDC found for {inst.inst_name}; tried: {', '.join(candidates)}; "
                "continuing in partial mode and preserving pending ports"
            )
    available = sorted(inst.inst_name for inst in instances.values() if inst.sdc_availability == "available")
    missing = sorted(inst.inst_name for inst in instances.values() if inst.sdc_availability == "missing")
    status = "partial" if missing else "complete"
    report.info(f"Run completeness: {status}; available={len(available)} missing={len(missing)} legacy_sdc_resolution=true")
    return RunCompleteness(status=status, available_instances=available, missing_instances=missing)


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


def parse_soc_clock_commands(text: str, report: Report, source_name: str) -> List[SocClockCommand]:
    commands: List[SocClockCommand] = []
    for tcl_cmd in iter_tcl_commands_with_line(text):
        tokens = tokenize_tcl_words(tcl_cmd.raw)
        if not tokens:
            continue
        command = tokens[0]
        if command not in CLOCK_COMMANDS:
            report.error(
                f"{clock_location(source_name, tcl_cmd.line_no)}: CLOCK_MANUAL_UNSUPPORTED_COMMAND: "
                f"manual/final clock SDC only permits create_clock/create_generated_clock; "
                f"command: {compact_command(tcl_cmd.raw)}"
            )
            continue
        target_tokens: List[str] = []
        source_token = ""
        idx = 1
        while idx < len(tokens):
            tok = tokens[idx]
            if tok == "-source":
                if idx + 1 < len(tokens):
                    source_token = tokens[idx + 1]
                idx += 2
                continue
            if tok in CLOCK_OPTIONS_WITH_VALUE:
                idx += 2
                continue
            if tok.startswith("-") or tok in CLOCK_OPTIONS_NO_VALUE:
                idx += 1
                continue
            obj_kind, _ = parse_get_object(tok)
            if obj_kind in {"get_ports", "get_pins"}:
                target_tokens.append(tok)
            idx += 1
        if len(target_tokens) > 1:
            report.error(
                f"{clock_location(source_name, tcl_cmd.line_no)}: CLOCK_MULTI_TARGET_NOT_SUPPORTED: "
                f"SoC clock command has multiple positional targets; command: {compact_command(tcl_cmd.raw)}"
            )
            continue
        target_token = target_tokens[0] if target_tokens else ""
        target_kind, target_objects = parse_get_object(target_token) if target_token else ("", [])
        if len(target_objects) > 1:
            report.error(
                f"{clock_location(source_name, tcl_cmd.line_no)}: CLOCK_MULTI_TARGET_NOT_SUPPORTED: "
                f"SoC clock target expands to multiple objects; command: {compact_command(tcl_cmd.raw)}"
            )
            continue
        clock_name = get_option(tokens, "-name")
        if not clock_name:
            clock_name = sanitize_name(target_objects[0]) if target_objects else ""
        commands.append(
            SocClockCommand(
                raw=tcl_cmd.raw,
                source_line=tcl_cmd.line_no,
                command="create_generated_clock" if command == "create_generate_clock" else command,
                tokens=tokens,
                clock_name=clock_name,
                period=get_option(tokens, "-period"),
                waveform=get_option(tokens, "-waveform"),
                target_token=target_token,
                target_kind=target_kind,
                target_objects=target_objects,
                source_token=source_token,
                master_clock=get_option(tokens, "-master_clock"),
                has_add="-add" in tokens,
            )
        )
    return commands


def decimal_equal(left: str, right: str) -> bool:
    try:
        return Decimal(left) == Decimal(right)
    except (InvalidOperation, ValueError):
        return left == right


def waveform_equal(left: str, right: str) -> bool:
    left_parts = split_object_list(left)
    right_parts = split_object_list(right)
    if len(left_parts) != len(right_parts):
        return False
    return all(decimal_equal(a, b) for a, b in zip(left_parts, right_parts))


def parse_clock_commands(text: str, report: Report, sdc_name: str) -> List[ParsedClock]:
    parsed: List[ParsedClock] = []
    for tcl_cmd in iter_tcl_commands_with_line(text):
        raw = tcl_cmd.raw
        tokens = tokenize_tcl_words(raw)
        if not tokens:
            continue
        command = tokens[0]
        if command not in CLOCK_COMMANDS:
            report.info(
                f"{clock_location(sdc_name, tcl_cmd.line_no)}: IGNORED_NON_CLOCK_COMMAND: "
                f"skipped non-clock SDC command {command}; command: {compact_command(raw)}"
            )
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
    return lookup_port(inst, port).direction


def from_whom_for(inst: InstInfo, port: str, direction: str) -> str:
    lookup = lookup_port(inst, port)
    info = lookup.info
    if direction == "input" and info is not None:
        return info.from_whom
    if direction == "inout" and info is not None:
        return info.connectivity
    return ""


def from_whom_with_connections(
    inst: InstInfo,
    port: str,
    direction: str,
    connection_by_dst: Dict[Tuple[str, str], ConnectionEdge],
) -> str:
    lookup = lookup_port(inst, port)
    if lookup.direction == "input":
        edge = connection_by_dst.get((inst.inst_name, lookup.canonical_port))
        if edge:
            if edge.src_instance in {"", "top"}:
                return "top." + edge.src_port
            return edge.src_instance + "." + edge.src_port
    return from_whom_for(inst, port, direction)


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


def split_port_key(port: str) -> Tuple[str, str, bool]:
    port = clean_cell(port)
    range_match = re.match(r"^(.+)\[(\d+)\s*:\s*(\d+)\]$", port)
    if range_match:
        return range_match.group(1), "", True
    bit_match = re.match(r"^(.+)\[(\d+)\]$", port)
    if bit_match:
        return bit_match.group(1), bit_match.group(2), False
    return port, "", False


def port_maps_by_direction(inst: InstInfo) -> List[Tuple[str, Dict[str, PortInfo]]]:
    return [
        ("output", inst.outputs),
        ("input", inst.inputs),
        ("inout", inst.inouts),
    ]


def lookup_port(inst: InstInfo, port: str) -> PortLookup:
    port = clean_cell(port)
    for direction, mapping in port_maps_by_direction(inst):
        if port in mapping:
            return PortLookup(direction, port, port, "", False, mapping[port])
    base, bit_index, is_range = split_port_key(port)
    for direction, mapping in port_maps_by_direction(inst):
        if base in mapping:
            return PortLookup(direction, port, base, bit_index, is_range, mapping[base])
    return PortLookup("unknown", port, base, bit_index, is_range, None)


def parse_width_bounds(text: str) -> Optional[Tuple[int, int]]:
    text = clean_cell(text)
    if not text:
        return None
    range_match = re.match(r"^\[?\s*(\d+)\s*:\s*(\d+)\s*\]?$", text)
    if range_match:
        a = int(range_match.group(1))
        b = int(range_match.group(2))
        return min(a, b), max(a, b)
    if re.fullmatch(r"\d+", text):
        width = int(text)
        if width <= 0:
            return None
        return 0, width - 1
    return None


def port_declared_vector(info: Optional[PortInfo]) -> bool:
    if info is None:
        return False
    for text in (info.used_width, info.width):
        bounds = parse_width_bounds(text)
        if bounds is not None:
            return bounds[1] > bounds[0]
    return False


def port_bit_in_declared_width(info: Optional[PortInfo], bit_index: str) -> bool:
    if info is None or not bit_index:
        return True
    for text in (info.used_width, info.width):
        bounds = parse_width_bounds(text)
        if bounds is None:
            continue
        bit = int(bit_index)
        return bounds[0] <= bit <= bounds[1]
    return True


def clock_name_for(inst_name: str, port: str) -> str:
    base, bit_index, _ = split_port_key(port)
    if bit_index:
        return sanitize_name(f"{inst_name}_{base}_bit{bit_index}")
    return sanitize_name(f"{inst_name}_{port}")


def top_clock_name(port: str) -> str:
    base, bit_index, _ = split_port_key(port)
    if bit_index:
        return sanitize_name(f"top_{base}_bit{bit_index}")
    return sanitize_name(f"top_{port}")


def clock_port_reference_error(inst: InstInfo, port: str, role: str) -> Tuple[str, str]:
    lookup = lookup_port(inst, port)
    role_upper = role.upper()
    if lookup.is_range:
        return (
            f"CLOCK_{role_upper}_RANGE_NOT_SUPPORTED",
            f"{role} port {port} is a range; 01 requires scalar or explicit bit target/source",
        )
    if lookup.direction == "unknown":
        rule_id = "CLOCK_TARGET_NOT_IN_OWNER_SHEET"
        if role == "source":
            rule_id = "CLOCK_GENERATED_SOURCE_NOT_IN_OWNER_SHEET"
        return (
            rule_id,
            f"{role} port {port} is not listed as Input/Output/Inout in owner sheet",
        )
    if lookup.bit_index and not port_bit_in_declared_width(lookup.info, lookup.bit_index):
        return (
            f"CLOCK_{role_upper}_BIT_OUT_OF_RANGE",
            f"{role} port {port} is outside declared width for {lookup.declared_port}",
        )
    if not lookup.bit_index and lookup.canonical_port == lookup.declared_port and port_declared_vector(lookup.info):
        return (
            f"CLOCK_{role_upper}_VECTOR_REQUIRES_BIT",
            f"{role} port {port} is a vector; 01 requires explicit bit target/source such as {port}[0]",
        )
    return "", ""


def rewrite_object_token_for_inst(
    token: str,
    inst: InstInfo,
    report: Report,
    sdc_name: str,
    parsed: Optional[ParsedClock] = None,
    name_map: Optional[Dict[str, str]] = None,
) -> str:
    cmd, objects = parse_get_object(token)
    if cmd == "get_ports":
        return get_pins_obj([f"{inst.inst_name}/{obj}" for obj in objects])
    if cmd == "get_clocks":
        mapped: List[str] = []
        unmapped: List[str] = []
        name_map = name_map or {}
        for obj in objects:
            if obj in name_map:
                new_obj = name_map[obj]
            else:
                new_obj = obj
                unmapped.append(obj)
            mapped.append(new_obj)
        if unmapped:
            message = (
                f"source references get_clocks name(s) without SoC rename mapping: "
                f"{', '.join(unmapped)}; keeping unmapped name(s)"
            )
            if parsed:
                report.warn(harden_clock_issue(inst, parsed, "CLOCK_SOURCE_GET_CLOCKS_UNMAPPED", message))
            else:
                report.warn(f"{sdc_name}: CLOCK_SOURCE_GET_CLOCKS_UNMAPPED: {message}")
        return get_clocks_obj(mapped)
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
                name_map,
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
    return sorted(tokens & {"scan", "mbist", "bist", "jtag", "test", "gpio"})


def process_instance(
    inst: InstInfo,
    report: Report,
    connection_by_dst: Dict[Tuple[str, str], ConnectionEdge],
    strict_connections: bool = False,
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
        if len(cmd.target_ports) != 1:
            continue
        port = cmd.target_ports[0]
        rule_id, _ = clock_port_reference_error(inst, port, "target")
        if rule_id:
            continue
        direction = port_direction(inst, port)
        from_whom = from_whom_with_connections(inst, port, direction, connection_by_dst)
        src_kind, src_obj = parse_connection(from_whom)
        if direction in {"output", "inout"}:
            name_map[cmd.original_name] = clock_name_for(inst.inst_name, port)
        elif direction == "input" and src_kind == "top":
            name_map[cmd.original_name] = top_clock_name(src_obj)
        elif direction == "input":
            name_map[cmd.original_name] = clock_name_for(inst.inst_name, port)

    records: List[ClockRecord] = []
    for cmd in parsed_cmds:
        if len(cmd.target_ports) > 1:
            note = (
                "clock command targets multiple ports; 01 v1 requires one target port per clock command "
                "to keep SoC clock naming and pending coverage unambiguous"
            )
            for target_port in cmd.target_ports:
                direction = port_direction(inst, target_port)
                records.append(
                    ClockRecord(
                        inst_name=inst.inst_name,
                        module_name=inst.module_name,
                        port_name=target_port,
                        direction=direction,
                        clock_name=clock_name_for(inst.inst_name, target_port),
                        clock_kind=command_kind(cmd),
                        period=cmd.period,
                        waveform=cmd.waveform,
                        direct_source="",
                        root_source="",
                            from_whom=from_whom_with_connections(inst, target_port, direction, connection_by_dst),
                        original_sdc=inst.sdc_path.name,
                        original_clock_name=cmd.original_name,
                        final_action="skipped",
                        note=note,
                        source_line=cmd.source_line,
                        original_command=cmd.raw,
                    )
                )
            report.error(harden_clock_issue(inst, cmd, "CLOCK_MULTI_TARGET_NOT_SUPPORTED", note))
            continue
        port = cmd.target_ports[0]
        direction = port_direction(inst, port)
        target_rule_id, target_message = clock_port_reference_error(inst, port, "target")
        if target_rule_id:
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
                    note=target_message,
                    source_line=cmd.source_line,
                    original_command=cmd.raw,
                )
            )
            issue = harden_clock_issue(inst, cmd, target_rule_id, target_message)
            report.error(issue)
            continue

        if strict_connections and direction == "input":
            canonical_port = lookup_port(inst, port).canonical_port
            if (inst.inst_name, canonical_port) not in connection_by_dst:
                note = (
                    "target mode requires one matched exact 00 connection edge for every boundary input clock"
                )
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
                        note=note,
                        source_line=cmd.source_line,
                        original_command=cmd.raw,
                    )
                )
                report.error(
                    harden_clock_issue(
                        inst,
                        cmd,
                        "CLOCK_INPUT_EXACT_EDGE_MISSING",
                        note,
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
        if "-add" in cmd.tokens:
            report.warn(
                harden_clock_issue(
                    inst,
                    cmd,
                    "CLOCK_ADD_OPTION_OUT_OF_SCOPE",
                    "-add multi-clock target semantics are out of scope for 01 v1; command is emitted as-is and needs review",
                )
            )
        if command_kind(cmd) == "create_clock" and not cmd.period:
            report.warn(
                harden_clock_issue(
                    inst,
                    cmd,
                    "CLOCK_CREATE_CLOCK_MISSING_PERIOD",
                    "create_clock has no -period; emitted command may be invalid",
                )
            )

        from_whom = from_whom_with_connections(inst, port, direction, connection_by_dst)
        if is_generated_clock(cmd):
            source_errors: List[Tuple[str, str]] = []
            for source_port in cmd.source_ports:
                rule_id, message = clock_port_reference_error(inst, source_port, "source")
                if rule_id:
                    source_errors.append((rule_id, message))
            source_kind, _ = parse_get_object(cmd.source_token) if cmd.source_token else ("", [])
            if source_kind == "get_pins":
                source_errors.append(
                    (
                        "CLOCK_GENERATED_SOURCE_INTERNAL_PIN",
                        "generated clock source uses harden-local get_pins; provide a boundary get_ports source",
                    )
                )
            if source_errors:
                note = "; ".join(message for _, message in source_errors)
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
                report.error(harden_clock_issue(inst, cmd, source_errors[0][0], note))
                continue
        source_obj = source_object_from_cmd(cmd, inst, name_map)
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
    for rec in records:
        if not rec.source_type:
            if rec.final_action in {"emit_top_clock", "duplicate_top_clock", "check_only"}:
                rec.source_type = "auto_top"
            else:
                rec.source_type = "auto_harden_output"
        if not rec.source_file:
            rec.source_file = rec.original_sdc
        if not rec.target_object and rec.port_name:
            if rec.direction == "output":
                rec.target_object = f"{rec.inst_name}/{rec.port_name}"
            elif rec.direction in {"input", "inout"} and rec.from_whom:
                kind, value = parse_connection(rec.from_whom)
                if kind == "top":
                    rec.target_object = f"top/{value}"
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
                source_type="virtual_spec",
                source_file=spec.source_file,
                target_object="",
            )
        )
    return records


def missing_sdc_records(
    instances: Dict[str, InstInfo],
    completeness: RunCompleteness,
) -> List[ClockRecord]:
    records: List[ClockRecord] = []
    for inst_name in completeness.missing_instances:
        inst = instances[inst_name]
        records.append(
            ClockRecord(
                inst_name=inst.inst_name,
                module_name=inst.module_name,
                port_name="",
                direction="instance",
                clock_name="",
                clock_kind="missing_sdc_evidence",
                period="",
                waveform="",
                direct_source="",
                root_source="",
                from_whom="",
                original_sdc="",
                original_clock_name="",
                final_action="missing_sdc",
                note=(
                    "harden SDC is unavailable; clock evidence is incomplete and all pending ports are preserved"
                    + (f"; {inst.sdc_note}" if inst.sdc_note else "")
                ),
                source_type="missing_sdc",
                source_file=(Path(completeness.manifest_path).name if completeness.manifest_path else "legacy_sdc_resolution"),
            )
        )
    return records


def known_top_ports(
    instances: Dict[str, InstInfo],
    connection_by_dst: Dict[Tuple[str, str], ConnectionEdge],
) -> Set[str]:
    result: Set[str] = set()
    for inst in instances.values():
        for info in list(inst.inputs.values()) + list(inst.inouts.values()):
            kind, value = parse_connection(info.from_whom or info.connectivity)
            if kind == "top" and value:
                result.add(value)
    for edge in connection_by_dst.values():
        if edge.src_instance in {"", "top"} and edge.src_port:
            result.add(edge.src_port)
    return result


def source_object_from_soc_command(command: SocClockCommand) -> str:
    kind, objects = parse_get_object(command.source_token) if command.source_token else ("", [])
    if kind == "get_ports" and len(objects) == 1:
        return "top/" + objects[0]
    if kind == "get_pins" and len(objects) == 1:
        return objects[0]
    if kind == "get_clocks" and objects:
        return "clock:" + " ".join(objects)
    return ""


def manual_clock_records(
    path: Path,
    instances: Dict[str, InstInfo],
    connection_by_dst: Dict[Tuple[str, str], ConnectionEdge],
    report: Report,
) -> List[ClockRecord]:
    if not path.is_file():
        return []
    try:
        text = read_text(path)
    except Exception as exc:
        report.error(f"{path}: failed to read manual clock overlay: {exc}")
        return []
    top_ports = known_top_ports(instances, connection_by_dst)
    commands = parse_soc_clock_commands(text, report, path.name)
    records: List[ClockRecord] = []
    for command in commands:
        note = "manual SoC-visible clock overlay"
        inst_name = ""
        module_name = ""
        port_name = ""
        direction = ""
        producer_object = ""
        final_action = "skipped"
        target_valid = True

        if not command.clock_name or not get_option(command.tokens, "-name"):
            report.error(
                f"{clock_location(path.name, command.source_line)}: CLOCK_MANUAL_MISSING_NAME: "
                f"manual clock must use an explicit -name; command: {compact_command(command.raw)}"
            )
            target_valid = False
        if not command.target_token or len(command.target_objects) != 1:
            report.error(
                f"{clock_location(path.name, command.source_line)}: CLOCK_MANUAL_TARGET_REQUIRED: "
                f"manual clock must target one SoC top port or harden output pin; "
                f"command: {compact_command(command.raw)}"
            )
            target_valid = False
        elif command.target_kind == "get_ports":
            port_name = command.target_objects[0]
            direction = "top"
            producer_object = "top/" + port_name
            if port_name not in top_ports:
                report.error(
                    f"{clock_location(path.name, command.source_line)}: CLOCK_MANUAL_TOP_PORT_NOT_IN_INTEGRATION: "
                    f"top port {port_name} is not referenced by owner sheets/connection inventory"
                )
                target_valid = False
            else:
                final_action = "emit_top_clock"
        elif command.target_kind == "get_pins":
            target = command.target_objects[0]
            if "/" not in target:
                report.error(
                    f"{clock_location(path.name, command.source_line)}: CLOCK_MANUAL_TARGET_NOT_SOC_PIN: "
                    f"manual pin target must be <inst>/<output_port>: {target}"
                )
                target_valid = False
            else:
                inst_name, port_name = target.split("/", 1)
                inst = instances.get(inst_name)
                if not inst:
                    report.error(
                        f"{clock_location(path.name, command.source_line)}: CLOCK_MANUAL_TARGET_INSTANCE_UNKNOWN: "
                        f"instance {inst_name} is not present in info_all.xlsx"
                    )
                    target_valid = False
                else:
                    lookup = lookup_port(inst, port_name)
                    module_name = inst.module_name
                    direction = lookup.direction
                    rule_id, message = clock_port_reference_error(inst, port_name, "target")
                    if rule_id or lookup.direction != "output":
                        report.error(
                            f"{clock_location(path.name, command.source_line)}: CLOCK_MANUAL_TARGET_NOT_OUTPUT: "
                            f"{message or 'manual harden pin target must be an exact output canonical bit'}"
                        )
                        target_valid = False
                    else:
                        producer_object = target
                        final_action = "emit_output_clock"
        else:
            target_valid = False

        direct_source = source_object_from_soc_command(command)
        if command.command == "create_generated_clock" and not direct_source:
            report.error(
                f"{clock_location(path.name, command.source_line)}: CLOCK_GENERATED_MISSING_SOURCE: "
                f"manual generated clock has no parseable -source; command: {compact_command(command.raw)}"
            )
            target_valid = False
        source_kind, source_objects = parse_get_object(command.source_token) if command.source_token else ("", [])
        if source_kind == "get_ports" and (len(source_objects) != 1 or source_objects[0] not in top_ports):
            report.error(
                f"{clock_location(path.name, command.source_line)}: CLOCK_MANUAL_SOURCE_TOP_PORT_UNKNOWN: "
                f"manual source top port is not present in integration data"
            )
            target_valid = False
        elif source_kind == "get_pins" and len(source_objects) == 1:
            source_pin = source_objects[0]
            if "/" not in source_pin:
                report.error(
                    f"{clock_location(path.name, command.source_line)}: CLOCK_MANUAL_SOURCE_PIN_UNKNOWN: "
                    f"manual source pin must be <inst>/<port>: {source_pin}"
                )
                target_valid = False
            else:
                source_inst_name, source_port = source_pin.split("/", 1)
                source_inst = instances.get(source_inst_name)
                source_rule_id = ""
                source_message = ""
                if source_inst:
                    source_rule_id, source_message = clock_port_reference_error(source_inst, source_port, "source")
                if not source_inst or source_rule_id:
                    report.error(
                        f"{clock_location(path.name, command.source_line)}: CLOCK_MANUAL_SOURCE_PIN_UNKNOWN: "
                        f"{source_message or ('manual source pin ' + source_pin + ' is not an exact integration port')}"
                    )
                    target_valid = False

        if not target_valid:
            final_action = "skipped"
        records.append(
            ClockRecord(
                inst_name=inst_name,
                module_name=module_name,
                port_name=port_name,
                direction=direction or "unknown",
                clock_name=command.clock_name or "<unnamed>",
                clock_kind="create_generated_clock" if command.command == "create_generated_clock" else "create_clock",
                period=command.period,
                waveform=command.waveform,
                direct_source=direct_source,
                root_source=producer_object if command.command == "create_clock" else "",
                from_whom="",
                original_sdc=path.name,
                original_clock_name=command.clock_name,
                final_action=final_action,
                note=note if target_valid else "manual clock failed validation",
                emitted_command=command.raw if target_valid else "",
                is_forwarded="-combinational" in command.tokens,
                producer_object=producer_object,
                source_line=command.source_line,
                original_command=command.raw,
                source_type="manual_overlay",
                source_file=path.name,
                target_object=producer_object,
            )
        )
    report.info(f"loaded {len(commands)} manual clock command(s) from {path.name}")
    return records


def source_object_from_cmd(cmd: ParsedClock, inst: InstInfo, name_map: Optional[Dict[str, str]] = None) -> str:
    name_map = name_map or {}
    if cmd.source_ports:
        return f"{inst.inst_name}/{cmd.source_ports[0]}"
    if cmd.source_token:
        get_cmd, objects = parse_get_object(cmd.source_token)
        if get_cmd == "get_pins" and objects:
            return objects[0]
        if get_cmd == "get_clocks" and objects:
            mapped = [name_map.get(obj, obj) for obj in objects]
            return "clock:" + " ".join(mapped)
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
        if first.period and rec.period and not decimal_equal(first.period, rec.period):
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
        report.warn(
            f"virtual clock {key}: CLOCK_DUPLICATE_VIRTUAL_CLOCK: duplicate declaration ignored; "
            f"first emitted from {first.original_sdc}"
        )
        if first.period and rec.period and not decimal_equal(first.period, rec.period):
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


def resolve_source_connection(
    obj: str,
    instances: Dict[str, InstInfo],
    connection_by_dst: Dict[Tuple[str, str], ConnectionEdge],
) -> str:
    if not obj or obj.startswith("top/") or obj.startswith("clock:"):
        return obj
    if "/" not in obj:
        return obj
    inst_name, port = obj.split("/", 1)
    inst = instances.get(inst_name)
    if not inst:
        return obj
    direction = port_direction(inst, port)
    if direction == "input":
        from_whom = from_whom_with_connections(inst, port, direction, connection_by_dst)
        kind, value = parse_connection(from_whom)
        if kind == "top":
            return f"top/{value}"
        if kind not in {"", "unknown", "const"}:
            return f"{kind}/{value}"
    return obj


def compute_root_sources(
    records: List[ClockRecord],
    instances: Dict[str, InstInfo],
    connection_by_dst: Dict[Tuple[str, str], ConnectionEdge],
) -> None:
    producers = build_producer_map(records)

    def root_for_object(obj: str, seen: Optional[set] = None) -> str:
        if not obj:
            return ""
        if seen is None:
            seen = set()
        if obj in seen:
            return obj
        seen.add(obj)
        if obj.startswith("clock:"):
            names = [name for name in obj[len("clock:"):].split() if name]
            if len(names) == 1:
                by_name = {
                    rec.clock_name: rec
                    for rec in records
                    if rec.final_action in EMITTED_CLOCK_ACTIONS
                }
                source_clock = by_name.get(names[0])
                if source_clock:
                    if source_clock.root_source:
                        return source_clock.root_source
                    if source_clock.direct_source:
                        return root_for_object(source_clock.direct_source, seen)
                    return source_clock.producer_object or obj
            return obj
        connected = resolve_source_connection(obj, instances, connection_by_dst)
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
            rec.root_source = root_for_object(rec.direct_source) if rec.direct_source else rec.producer_object
        elif rec.final_action == "emit_top_clock":
            rec.root_source = root_for_object(rec.direct_source) if rec.direct_source else rec.producer_object
        elif rec.final_action == "check_only":
            rec.root_source = root_for_object(rec.direct_source)


def validate_clock_universe(records: List[ClockRecord], report: Report) -> None:
    active_names = {
        rec.clock_name
        for rec in records
        if rec.final_action in EMITTED_CLOCK_ACTIONS and rec.emitted_command
    }
    for rec in records:
        if rec.source_type != "manual_overlay" or rec.final_action not in EMITTED_CLOCK_ACTIONS:
            continue
        tokens = tokenize_tcl_words(rec.emitted_command)
        source_token = get_option(tokens, "-source")
        source_kind, source_objects = parse_get_object(source_token) if source_token else ("", [])
        missing_names: List[str] = []
        if source_kind == "get_clocks":
            missing_names.extend(name for name in source_objects if name not in active_names)
        master_clock = get_option(tokens, "-master_clock")
        if master_clock and master_clock not in active_names:
            missing_names.append(master_clock)
        if missing_names:
            report.error(
                record_clock_issue(
                    rec,
                    "CLOCK_MANUAL_REFERENCE_NOT_IN_UNIVERSE",
                    "manual source/master clock is absent from final clock universe: "
                    + ", ".join(sorted(set(missing_names))),
                )
            )
            rec.final_action = "skipped"
            rec.emitted_command = ""
            rec.note = "manual clock source/master is absent from final clock universe"

    first_by_target: Dict[str, ClockRecord] = {}
    for rec in records:
        if rec.final_action not in EMITTED_CLOCK_ACTIONS or not rec.emitted_command or not rec.target_object:
            continue
        first = first_by_target.get(rec.target_object)
        if first is None:
            first_by_target[rec.target_object] = rec
            continue
        tokens = tokenize_tcl_words(rec.emitted_command)
        if "-add" not in tokens:
            report.error(
                record_clock_issue(
                    rec,
                    "CLOCK_TARGET_CONFLICT",
                    f"target {rec.target_object} already has clock {first.clock_name}; additional clock requires -add and review",
                )
            )
            if rec.source_type == "manual_overlay":
                rec.final_action = "skipped"
                rec.emitted_command = ""
                rec.note = "manual target conflicts with an existing clock"
        else:
            report.warn(
                record_clock_issue(
                    rec,
                    "CLOCK_TARGET_MULTI_CLOCK_REVIEW",
                    f"target {rec.target_object} has multiple clocks with explicit -add; review mux/mode semantics",
                )
            )


def run_checks(
    records: List[ClockRecord],
    instances: Dict[str, InstInfo],
    report: Report,
    missing_instances: Optional[Set[str]] = None,
) -> None:
    missing_instances = missing_instances or set()
    emitted_by_name: Dict[str, List[ClockRecord]] = {}
    for rec in records:
        if rec.final_action in EMITTED_CLOCK_ACTIONS:
            emitted_by_name.setdefault(rec.clock_name, []).append(rec)
    for clock_name, group in sorted(emitted_by_name.items()):
        if len(group) <= 1:
            continue
        details = ", ".join(
            f"{rec.inst_name or '<virtual>'}/{rec.port_name or rec.clock_name}"
            f"({clock_location(rec.original_sdc, rec.source_line)})"
            for rec in group
        )
        report.error(
            f"clock_name {clock_name}: CLOCK_NAME_CONFLICT: multiple emitted clocks use the same name: {details}"
        )

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
            rule_id = "CLOCK_SOURCE_SDC_MISSING" if kind in missing_instances else "CLOCK_UPSTREAM_NOT_EMITTED"
            detail = (
                f"upstream harden {kind} SDC is missing; clock source {upstream_obj} remains incomplete"
                if rule_id == "CLOCK_SOURCE_SDC_MISSING"
                else f"upstream clock {upstream_obj} was not emitted"
            )
            report.warn(
                record_clock_issue(
                    rec,
                    rule_id,
                    detail,
                )
            )
            if rule_id == "CLOCK_SOURCE_SDC_MISSING":
                rec.final_action = "incomplete_missing_sdc"
                rec.note = (
                    f"clock sink depends on missing upstream harden SDC {kind}; "
                    "pending port is preserved"
                )
            continue
        if rec.period and upstream.period and not decimal_equal(rec.period, upstream.period):
            report.warn(
                record_clock_issue(
                    rec,
                    "CLOCK_PERIOD_MISMATCH",
                    f"period {rec.period} differs from upstream {upstream_obj} period {upstream.period}",
                )
            )
        if rec.waveform and upstream.waveform and not waveform_equal(rec.waveform, upstream.waveform):
            report.warn(
                record_clock_issue(
                    rec,
                    "CLOCK_WAVEFORM_MISMATCH",
                    f"waveform {rec.waveform} differs from upstream {upstream_obj} waveform {upstream.waveform}",
                )
            )


def clock_dependency_names(rec: ClockRecord, by_object: Dict[str, ClockRecord]) -> List[str]:
    deps: List[str] = []
    for source in (rec.direct_source, rec.root_source):
        if not source:
            continue
        if source.startswith("clock:"):
            deps.extend(name for name in source[len("clock:"):].split() if name)
            continue
        producer = by_object.get(source)
        if producer:
            deps.append(producer.clock_name)
    return deps


def dependency_ordered_emitted(records: List[ClockRecord], report: Report) -> List[ClockRecord]:
    emitted = [
        rec
        for rec in records
        if rec.final_action in {"emit_top_clock", "emit_output_clock", "emit_virtual_clock"}
        and rec.emitted_command
    ]
    by_clock: Dict[str, ClockRecord] = {}
    for rec in emitted:
        if rec.clock_name not in by_clock:
            by_clock[rec.clock_name] = rec
    by_object = build_producer_map(emitted)
    index_by_id = {id(rec): idx for idx, rec in enumerate(emitted)}
    deps_by_index: Dict[int, Set[int]] = {}
    for idx, rec in enumerate(emitted):
        deps_by_index[idx] = set()
        for dep_name in clock_dependency_names(rec, by_object):
            dep = by_clock.get(dep_name)
            if not dep:
                continue
            dep_idx = index_by_id[id(dep)]
            if dep_idx != idx:
                deps_by_index[idx].add(dep_idx)

    remaining: Set[int] = set(range(len(emitted)))
    ordered: List[ClockRecord] = []
    while remaining:
        ready = sorted(idx for idx in remaining if not (deps_by_index[idx] & remaining))
        if not ready:
            report.warn("CLOCK_DEPENDENCY_ORDER_CYCLE: unable to fully topologically order emitted clocks; keeping remaining original order")
            ordered.extend(emitted[idx] for idx in sorted(remaining))
            break
        for idx in ready:
            ordered.append(emitted[idx])
            remaining.remove(idx)
    return ordered


def completeness_lines(
    completeness: RunCompleteness,
    prefix: str = "",
) -> List[str]:
    missing = ",".join(completeness.missing_instances) or "<none>"
    return [
        f"{prefix}Run completeness: {completeness.status}",
        f"{prefix}Harden SDC available: {completeness.available_count}",
        f"{prefix}Harden SDC missing: {completeness.missing_count}",
        f"{prefix}Harden SDC not_required: {completeness.not_required_count}",
        f"{prefix}Missing instances: {missing}",
    ]


def write_sdc(
    path: Path,
    records: List[ClockRecord],
    report: Report,
    completeness: RunCompleteness,
    scenario: str,
    target_layout: bool,
) -> None:
    emitted = dependency_ordered_emitted(records, report)
    lines = [
        "################################################################################",
        "# Auto-generated SoC func clock constraints",
        f"# Author: {author_name()}",
        "# Stage: 01_soc_clocks",
        "# Script: 01_extract_soc_clocks.py",
        f"# Scenario: {scenario}",
    ]
    lines.extend(completeness_lines(completeness, "# "))
    lines.extend([
        (
            "# Source: 00 manifest/connection inventory and harden SoC integration SDC files"
            if target_layout
            else "# Source: local info_all.xlsx, port_*.xlsx and harden SoC integration SDC files"
        ),
        "################################################################################",
        "",
    ])
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
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")
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
        "source_type",
        "source_file",
        "target_object",
        "final_sdc_digest",
        "run_completeness",
        "missing_instances",
        "note",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.tmp.%s" % (path.name, os.getpid()))
    with tmp.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fields)
        writer.writeheader()
        for rec in records:
            writer.writerow({field: getattr(rec, field) for field in fields})
    tmp.replace(path)


def write_report(
    path: Path,
    report: Report,
    records: List[ClockRecord],
    completeness: RunCompleteness,
    scenario: str,
    port_accounting_enabled: bool,
) -> None:
    action_counts: Dict[str, int] = {}
    for rec in records:
        action_counts[rec.final_action] = action_counts.get(rec.final_action, 0) + 1
    lines = [
        "01_soc_clocks extraction report",
        "================================",
        "",
        f"Author: {author_name()}",
        "Stage: 01_soc_clocks",
        "Script: 01_extract_soc_clocks.py",
        f"Scenario: {scenario}",
        (
            "Port accounting: enabled"
            if port_accounting_enabled
            else "Port accounting: disabled by explicit option"
        ),
        "",
    ]
    lines.extend(completeness_lines(completeness))
    lines.extend([
        "",
        f"Warnings: {report.warning_count}",
        f"Errors  : {report.error_count}",
        "",
        "Action counts:",
    ])
    for action in sorted(action_counts):
        lines.append(f"  {action}: {action_counts[action]}")
    lines.extend(["", "Messages:"])
    lines.extend(report.lines or ["INFO: no messages"])
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")


def soc_clock_fingerprint(command: SocClockCommand) -> Tuple[str, str, str, str, str]:
    target = ""
    if command.target_kind and command.target_objects:
        target = command.target_kind + ":" + " ".join(command.target_objects)
    source_kind, source_objects = parse_get_object(command.source_token) if command.source_token else ("", [])
    source = source_kind + ":" + " ".join(source_objects) if source_kind else command.source_token
    return command.command, command.clock_name, target, source, command.master_clock


def reconcile_final_sdc(path: Path, records: List[ClockRecord], report: Report) -> None:
    final_commands = parse_soc_clock_commands(read_text(path), report, path.name)
    expected_commands: List[SocClockCommand] = []
    for rec in records:
        if rec.final_action not in EMITTED_CLOCK_ACTIONS or not rec.emitted_command:
            continue
        parsed = parse_soc_clock_commands(rec.emitted_command, report, rec.source_file or rec.original_sdc)
        expected_commands.extend(parsed)
    final_set = Counter(soc_clock_fingerprint(command) for command in final_commands)
    expected_set = Counter(soc_clock_fingerprint(command) for command in expected_commands)
    if final_set != expected_set:
        missing = list((expected_set - final_set).elements())
        extra = list((final_set - expected_set).elements())
        report.error(
            f"{path}: CLOCK_FINAL_RECONCILE_MISMATCH: final SDC and active inventory records differ; "
            f"missing={missing}; extra={extra}"
        )
    else:
        report.info(f"reconciled {len(final_commands)} final clock command(s) against active inventory")


def write_inventory_meta(
    path: Path,
    scenario: str,
    sdc_path: Path,
    inventory_path: Path,
    records: Sequence[ClockRecord],
    completeness: RunCompleteness,
) -> None:
    active_names = sorted(
        rec.clock_name
        for rec in records
        if rec.final_action in EMITTED_CLOCK_ACTIONS and rec.emitted_command
    )
    clock_set_digest = hashlib.sha256("\n".join(active_names).encode("utf-8")).hexdigest()
    payload = {
        "author": author_name(),
        "stage": "01_soc_clocks",
        "script": "01_extract_soc_clocks.py",
        "scenario": scenario,
        "final_sdc_path": str(sdc_path.resolve()),
        "final_sdc_digest": sha256_file(sdc_path),
        "inventory_path": str(inventory_path.resolve()),
        "inventory_digest": sha256_file(inventory_path),
        "clock_set_digest": clock_set_digest,
        "clock_count": len(active_names),
        "run_completeness": completeness.status,
        "available_harden_count": completeness.available_count,
        "missing_harden_count": completeness.missing_count,
        "not_required_harden_count": completeness.not_required_count,
        "missing_instances": completeness.missing_instances,
    }
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def record_debug_dict(rec: ClockRecord) -> Dict[str, object]:
    return {
        "inst_name": rec.inst_name,
        "module_name": rec.module_name,
        "port_name": rec.port_name,
        "direction": rec.direction,
        "clock_name": rec.clock_name,
        "clock_kind": rec.clock_kind,
        "period": rec.period,
        "waveform": rec.waveform,
        "direct_source": rec.direct_source,
        "root_source": rec.root_source,
        "from_whom": rec.from_whom,
        "producer_object": rec.producer_object,
        "target_object": rec.target_object,
        "original_sdc": rec.original_sdc,
        "source_line": rec.source_line,
        "original_clock_name": rec.original_clock_name,
        "original_command": rec.original_command,
        "emitted_command": rec.emitted_command,
        "final_action": rec.final_action,
        "source_type": rec.source_type,
        "source_file": rec.source_file,
        "note": rec.note,
    }


def write_debug_bundle(
    debug_dir: Path,
    argv: Sequence[str],
    resolved_paths: Dict[str, Path],
    input_paths: Sequence[Path],
    instances: Dict[str, InstInfo],
    records: List[ClockRecord],
    completeness: RunCompleteness,
    report: Report,
) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    inputs = []
    seen_paths: Set[str] = set()
    for path in input_paths:
        resolved = str(path.resolve())
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        inputs.append(
            {
                "path": resolved,
                "exists": path.is_file(),
                "sha256": sha256_file(path) if path.is_file() else "",
                "size": path.stat().st_size if path.is_file() else 0,
            }
        )
    instance_rows = []
    for inst in sorted(instances.values(), key=lambda item: item.inst_name):
        instance_rows.append(
            {
                "inst_name": inst.inst_name,
                "module_name": inst.module_name,
                "sdc_availability": inst.sdc_availability,
                "sdc_path": str(inst.sdc_path.resolve()) if inst.sdc_path else "",
                "sdc_digest": inst.sdc_digest,
                "sdc_note": inst.sdc_note,
                "input_count": len(inst.inputs),
                "output_count": len(inst.outputs),
                "inout_count": len(inst.inouts),
            }
        )
    payload = {
        "author": author_name(),
        "stage": "01_soc_clocks",
        "script": str(Path(__file__).resolve()),
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": str(Path.cwd().resolve()),
        "argv": list(argv),
        "repro_command": " ".join([shlex.quote(sys.executable), shlex.quote(str(Path(__file__).resolve()))] + [shlex.quote(arg) for arg in argv]),
        "resolved_paths": {name: str(path.resolve()) for name, path in sorted(resolved_paths.items())},
        "run_completeness": completeness.status,
        "available_instances": completeness.available_instances,
        "missing_instances": completeness.missing_instances,
        "not_required_instances": completeness.not_required_instances,
        "manifest_path": completeness.manifest_path,
        "manifest_digest": completeness.manifest_digest,
        "warnings": report.warning_count,
        "errors": report.error_count,
        "inputs": inputs,
        "instances": instance_rows,
        "records": [record_debug_dict(rec) for rec in records],
    }
    atomic_write_text(debug_dir / "run_context.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")
    atomic_write_text(debug_dir / "repro_command.txt", payload["repro_command"] + "\n")
    atomic_write_text(debug_dir / "messages.log", "\n".join(report.lines).rstrip() + "\n")
    write_inventory(debug_dir / "clock_records_debug.csv", records)

    fields = [
        "inst_name",
        "module_name",
        "availability",
        "sdc_path",
        "sdc_digest",
        "note",
    ]
    tmp = debug_dir / (".manifest_decisions.csv.tmp.%s" % os.getpid())
    with tmp.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fields)
        writer.writeheader()
        for inst in sorted(instances.values(), key=lambda item: item.inst_name):
            writer.writerow(
                {
                    "inst_name": inst.inst_name,
                    "module_name": inst.module_name,
                    "availability": inst.sdc_availability,
                    "sdc_path": str(inst.sdc_path.resolve()) if inst.sdc_path else "",
                    "sdc_digest": inst.sdc_digest,
                    "note": inst.sdc_note,
                }
            )
    tmp.replace(debug_dir / "manifest_decisions.csv")


def removable_clock_records(records: Sequence[ClockRecord]) -> List[ClockRecord]:
    actions = {
        "emit_top_clock",
        "duplicate_top_clock",
        "check_only",
        "emit_output_clock",
    }
    removable: List[ClockRecord] = []
    seen: Set[PortKey] = set()
    for rec in records:
        if rec.final_action not in actions:
            continue
        if not rec.inst_name or not rec.port_name or rec.direction not in {"input", "output", "inout"}:
            continue
        key = PortKey(rec.inst_name, rec.direction, rec.port_name)
        if key in seen:
            continue
        seen.add(key)
        removable.append(rec)
    return removable


def pending_line_key(line: str) -> Optional[Tuple[str, str]]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = stripped.split()
    if len(parts) < 2:
        return None
    direction, port = parts[0], parts[1]
    if direction not in {"input", "output", "inout"}:
        return None
    return direction, port


def removed_line_key(line: str) -> Optional[PortKey]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = stripped.split()
    if len(parts) < 3:
        return None
    inst_name, direction, port = parts[:3]
    if direction not in {"input", "output", "inout"}:
        return None
    return PortKey(inst_name, direction, port)


def read_removed_keys(log_dir: Path) -> Set[PortKey]:
    keys: Set[PortKey] = set()
    if not log_dir.is_dir():
        return keys
    for path in sorted(log_dir.glob("*.removed")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            key = removed_line_key(line)
            if key is not None:
                keys.add(key)
    return keys


def clock_removed_reason(rec: ClockRecord) -> str:
    if rec.final_action == "check_only":
        return "upstream_clock_sink"
    if rec.final_action == "duplicate_top_clock":
        return "duplicate_top_clock_user"
    if rec.final_action == "emit_top_clock":
        return "top_clock"
    if rec.is_forwarded:
        return "forwarded_clock"
    if rec.clock_kind in {"create_generated_clock", "generated_combinational"}:
        return "generated_clock"
    return "output_clock"


def removed_log_line(rec: ClockRecord) -> str:
    fields = [
        rec.inst_name,
        rec.direction,
        rec.port_name,
        "covered_by=01_soc_clocks",
        f"reason={clock_removed_reason(rec)}",
        f"clock={rec.clock_name}",
        f"action={rec.final_action}",
    ]
    if rec.from_whom:
        fields.append(f"from_whom={rec.from_whom}")
    if rec.original_sdc:
        fields.append(f"source={clock_location(rec.original_sdc, rec.source_line)}")
    return " ".join(fields)


def update_pending_for_01(
    cwd: Path,
    pending_dir: Path,
    log_dir: Path,
    records: Sequence[ClockRecord],
    report: Report,
) -> None:
    if not pending_dir.exists():
        return
    if not pending_dir.is_dir():
        report.error(f"{pending_dir}: pending path exists but is not a directory")
        return

    removable = removable_clock_records(records)
    if not removable:
        return

    previous_removed = read_removed_keys(log_dir)

    by_inst: Dict[str, List[ClockRecord]] = {}
    for rec in removable:
        by_inst.setdefault(rec.inst_name, []).append(rec)

    removed_records: List[ClockRecord] = []
    for inst_name, inst_records in sorted(by_inst.items()):
        pending_file = pending_dir / f"{inst_name}.ports"
        if not pending_file.is_file():
            for rec in inst_records:
                if PortKey(rec.inst_name, rec.direction, rec.port_name) in previous_removed:
                    continue
                report.error(
                    f"{pending_file}: missing pending file for 01 clock port "
                    f"{rec.inst_name}/{rec.port_name}"
                )
            continue

        lines = pending_file.read_text(encoding="utf-8").splitlines()
        index: Dict[Tuple[str, str], int] = {}
        duplicate_keys: Set[Tuple[str, str]] = set()
        for idx, line in enumerate(lines):
            key = pending_line_key(line)
            if key is None:
                continue
            if key in index:
                duplicate_keys.add(key)
            else:
                index[key] = idx
        for direction, port in sorted(duplicate_keys):
            report.error(f"{pending_file}: duplicate pending port line {direction} {port}")

        remove_line_indices: Set[int] = set()
        for rec in inst_records:
            key = (rec.direction, rec.port_name)
            if key not in index:
                if PortKey(rec.inst_name, rec.direction, rec.port_name) in previous_removed:
                    continue
                report.error(
                    f"{pending_file}: 01 wants to remove {rec.direction} {rec.port_name}, "
                    "but it is not present in pending and no previous_removed record exists"
                )
                continue
            remove_line_indices.add(index[key])
            removed_records.append(rec)

        if remove_line_indices:
            kept = [line for idx, line in enumerate(lines) if idx not in remove_line_indices]
            atomic_write_text(pending_file, "\n".join(kept).rstrip() + ("\n" if kept else ""))

    if removed_records:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "01_soc_clocks.removed"
        existing_lines = log_path.read_text(encoding="utf-8").splitlines() if log_path.is_file() else []
        existing_keys: Set[PortKey] = set()
        for line in existing_lines:
            key = removed_line_key(line)
            if key is not None:
                existing_keys.add(key)
        new_lines = []
        for rec in sorted(removed_records, key=lambda r: (r.inst_name, r.direction, r.port_name)):
            key = PortKey(rec.inst_name, rec.direction, rec.port_name)
            if key not in existing_keys:
                new_lines.append(removed_log_line(rec))
                existing_keys.add(key)
        if new_lines:
            log_lines = [line for line in existing_lines if line.strip()] + new_lines
            atomic_write_text(log_path, "\n".join(log_lines).rstrip() + "\n")
        try:
            display_path = log_path.relative_to(cwd)
        except ValueError:
            display_path = log_path
        report.info(f"removed {len(removed_records)} harden clock port(s) from pending; log={display_path}")


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
    parser.add_argument(
        "--run-root",
        help="target runtime root; when set, inputs are read from <run-root>/inputs and outputs use 01_middle/01_result",
    )
    parser.add_argument("--scenario", default="common", help="clock scenario; current func-only implementation accepts common")
    parser.add_argument(
        "--harden-sdc-manifest",
        help="00 harden SDC manifest; target default: 00_middle/scenario/<scenario>/harden_sdc_manifest.csv",
    )
    parser.add_argument(
        "--require-complete-harden-sdc",
        action="store_true",
        help="treat any manifest/inferred missing harden SDC as an error",
    )
    parser.add_argument("--info", help="integration info workbook")
    parser.add_argument(
        "--port-files",
        nargs="*",
        help="owner port workbook(s); default: local port_*.xlsx",
    )
    parser.add_argument(
        "--output",
        help="output SoC clock SDC path",
    )
    parser.add_argument(
        "--inventory",
        help="output clock inventory CSV path",
    )
    parser.add_argument(
        "--report",
        help="output extraction/check report path",
    )
    parser.add_argument(
        "--virtual-clocks",
        help=(
            "optional local CSV for virtual clocks; columns: clock_name/name, period, "
            "optional waveform, note"
        ),
    )
    parser.add_argument(
        "--manual-clocks",
        help="optional manual SoC-visible clock overlay; default: 01_soc_clocks_manual.sdc",
    )
    parser.add_argument(
        "--connection-inventory",
        help=(
            "00 bit-to-bit connection inventory. Required in target runtime; legacy mode "
            "falls back to owner From Whom when absent"
        ),
    )
    parser.add_argument(
        "--no-write-sdc",
        action="store_true",
        help="only write inventory/report, not common/01_soc_clocks.sdc",
    )
    parser.add_argument(
        "--pending-root",
        help=(
            "legacy 00 harden port inventory root. Target runtime uses the fixed scenario pending path; "
            "01 removes covered clock ports and writes its removed log"
        ),
    )
    parser.add_argument(
        "--no-update-pending",
        action="store_true",
        help="do not consume 00_harden_port_inventory/pending even if it exists",
    )
    parser.add_argument(
        "--diagnose-only",
        action="store_true",
        help="parse and check inputs without writing the official SDC or updating pending",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="write an offline debug bundle with resolved paths, digests, manifest decisions and clock records",
    )
    parser.add_argument(
        "--debug-dir",
        help="debug bundle directory; implies --debug",
    )
    parser.add_argument(
        "--debug-verbose",
        action="store_true",
        help="print report messages and clock source decisions to stdout; implies --debug",
    )
    return parser.parse_args(argv)


def _main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    cwd = Path.cwd()
    report = Report()
    print(f"Author: {author_name()}")
    if args.diagnose_only:
        args.no_write_sdc = True
        args.no_update_pending = True
    debug_enabled = args.debug or bool(args.debug_dir) or args.debug_verbose
    if args.no_update_pending:
        report.info(
            "Port accounting: disabled by explicit option; pending closure is not claimed"
        )

    if args.scenario != "common":
        print("ERROR: current 01 implementation supports only --scenario common", file=sys.stderr)
        return 2

    target_layout = bool(args.run_root)
    run_root = Path(args.run_root).expanduser().resolve() if target_layout else cwd
    input_root = run_root / "inputs" if target_layout else cwd

    def resolve_path(base: Path, value: Optional[str], default: str) -> Path:
        path = Path(value) if value else Path(default)
        return path if path.is_absolute() else base / path

    info_path = resolve_path(input_root, args.info, "info_all.xlsx")
    output_path = resolve_path(
        run_root if target_layout else cwd,
        args.output,
        "01_result/common/01_soc_clocks.sdc" if target_layout else "common/01_soc_clocks.sdc",
    )
    inventory_path = resolve_path(
        run_root if target_layout else cwd,
        args.inventory,
        "01_middle/common/clock_inventory.csv" if target_layout else "clock_inventory.csv",
    )
    report_path = resolve_path(
        run_root if target_layout else cwd,
        args.report,
        f"01_result/reports/clock_check_report_{args.scenario}.txt" if target_layout else "clock_check_report.txt",
    )
    virtual_path = resolve_path(input_root, args.virtual_clocks, "virtual_clocks.csv")
    manual_path = resolve_path(input_root, args.manual_clocks, "01_soc_clocks_manual.sdc")
    connection_path = resolve_path(
        run_root if target_layout else cwd,
        args.connection_inventory,
        "00_middle/connection_inventory.csv" if target_layout else "00_harden_port_inventory/connection_inventory.csv",
    )
    manifest_path: Optional[Path]
    if target_layout:
        manifest_path = resolve_path(
            run_root,
            args.harden_sdc_manifest,
            f"00_middle/scenario/{args.scenario}/harden_sdc_manifest.csv",
        )
    elif args.harden_sdc_manifest:
        manifest_path = resolve_path(cwd, args.harden_sdc_manifest, args.harden_sdc_manifest)
    else:
        manifest_path = None
    if target_layout:
        if args.pending_root:
            pending_base = resolve_path(run_root, args.pending_root, args.pending_root)
            pending_dir = pending_base / "pending"
        else:
            pending_dir = run_root / f"00_middle/scenario/{args.scenario}/pending"
        removed_log_dir = run_root / f"01_middle/scenario/{args.scenario}/removed_log"
        common_meta_path: Optional[Path] = run_root / "01_middle/common/clock_inventory.meta"
        scenario_inventory_path: Optional[Path] = run_root / f"01_middle/scenario/{args.scenario}/clock_inventory.csv"
        scenario_meta_path: Optional[Path] = run_root / f"01_middle/scenario/{args.scenario}/clock_inventory.meta"
        assembled_inventory_path: Optional[Path] = run_root / "01_middle/assembled/common/clock_inventory.csv"
        assembled_meta_path: Optional[Path] = run_root / "01_middle/assembled/common/clock_inventory.meta"
    else:
        pending_base = resolve_path(cwd, args.pending_root, "00_harden_port_inventory")
        pending_dir = pending_base / "pending"
        removed_log_dir = pending_base / "removed_log"
        common_meta_path = None
        scenario_inventory_path = None
        scenario_meta_path = None
        assembled_inventory_path = None
        assembled_meta_path = None

    debug_dir = resolve_path(
        run_root if target_layout else cwd,
        args.debug_dir,
        "01_middle/debug/01_soc_clocks" if target_layout else "debug/01_soc_clocks",
    )

    report.info(f"scenario: {args.scenario}")
    report.info(f"runtime layout: {'target' if target_layout else 'legacy'}")
    report.info(f"resolved input root: {input_root.resolve()}")
    if not target_layout:
        report.info(f"resolved info workbook: {info_path.resolve()}")
    report.info(f"resolved connection inventory: {connection_path.resolve()}")
    report.info(f"resolved output SDC: {output_path.resolve()}")
    report.info(f"resolved output inventory: {inventory_path.resolve()}")
    report.info(f"resolved output report: {report_path.resolve()}")
    if manifest_path is not None:
        report.info(f"resolved harden SDC manifest: {manifest_path.resolve()}")
    if debug_enabled:
        report.info(f"resolved debug directory: {debug_dir.resolve()}")
    port_files: List[Path] = []
    if target_layout:
        instances: Dict[str, InstInfo] = {}
        assert manifest_path is not None
        completeness = apply_harden_sdc_manifest(
            instances,
            manifest_path,
            run_root,
            args.scenario,
            args.require_complete_harden_sdc,
            report,
            authoritative=True,
        )
        if not connection_path.is_file():
            report.error(
                f"{connection_path}: TARGET_UPSTREAM_CONNECTION_INVENTORY_MISSING: "
                "target runtime requires the fixed 00 connection inventory"
            )
        connection_by_dst = read_connection_inventory(
            connection_path,
            report,
            scenario=args.scenario,
            strict_target=True,
        )
        attach_ports_from_connections(instances, connection_by_dst, report)
        read_target_pending_ports(
            pending_dir,
            instances,
            report,
            required=not args.no_update_pending,
        )
        attach_ports_from_previous_01_removed(removed_log_dir, instances, report)
    else:
        if not info_path.is_file():
            print(f"ERROR: info workbook not found in execution directory: {info_path}", file=sys.stderr)
            return 2
        try:
            instances = read_info_all(info_path, report)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        if args.port_files:
            port_files = [resolve_path(input_root, item, item) for item in args.port_files]
        else:
            port_files = default_port_files(input_root, info_path.name)
        if not port_files:
            print("ERROR: no owner port workbook found. Expected local port_*.xlsx or --port-files.", file=sys.stderr)
            return 2
        missing_ports = [str(path) for path in port_files if not path.is_file()]
        if missing_ports:
            print(f"ERROR: port workbook(s) not found: {', '.join(missing_ports)}", file=sys.stderr)
            return 2
        sheets = read_port_workbooks(port_files, report)
        attach_port_data(instances, sheets, report)
        completeness = resolve_sdc_paths(instances, input_root, report)
        if args.require_complete_harden_sdc and completeness.missing_instances:
            report.error(
                "HARDEN_SDC_COMPLETENESS_REQUIRED: missing harden SDC instance(s): "
                + ", ".join(completeness.missing_instances)
            )

        connection_by_dst = read_connection_inventory(
            connection_path, report, scenario=args.scenario, strict_target=False
        )

    records: List[ClockRecord] = missing_sdc_records(instances, completeness)
    for inst_name in sorted(instances):
        records.extend(
            process_instance(
                instances[inst_name],
                report,
                connection_by_dst,
                strict_connections=target_layout,
            )
        )
    dedupe_top_clocks(records, report)
    records.extend(virtual_clock_records(read_virtual_clock_csv(virtual_path, report)))
    dedupe_virtual_clocks(records, report)
    records.extend(manual_clock_records(manual_path, instances, connection_by_dst, report))
    validate_clock_universe(records, report)
    inst_lookup = build_instance_lookup(instances)
    compute_root_sources(records, inst_lookup, connection_by_dst)
    run_checks(records, inst_lookup, report, set(completeness.missing_instances))

    missing_text = ";".join(completeness.missing_instances)
    for rec in records:
        rec.run_completeness = completeness.status
        rec.missing_instances = missing_text

    if not args.no_write_sdc:
        write_sdc(
            output_path,
            records,
            report,
            completeness,
            args.scenario,
            target_layout,
        )
        final_digest = sha256_file(output_path)
        for rec in records:
            if rec.final_action in EMITTED_CLOCK_ACTIONS and rec.emitted_command:
                rec.final_sdc_digest = final_digest
        reconcile_final_sdc(output_path, records, report)
    write_inventory(inventory_path, records)
    if not args.no_update_pending:
        if report.error_count:
            report.warn(
                "PENDING_UPDATE_SKIPPED_DUE_TO_ERRORS: pending files were not modified because validation errors exist"
            )
        else:
            update_pending_for_01(run_root, pending_dir, removed_log_dir, records, report)
    if target_layout and not args.no_write_sdc:
        assert common_meta_path is not None
        assert scenario_inventory_path is not None
        assert scenario_meta_path is not None
        assert assembled_inventory_path is not None
        assert assembled_meta_path is not None
        write_inventory_meta(common_meta_path, args.scenario, output_path, inventory_path, records, completeness)
        write_inventory(scenario_inventory_path, records)
        write_inventory_meta(
            scenario_meta_path,
            args.scenario,
            output_path,
            scenario_inventory_path,
            records,
            completeness,
        )
        write_inventory(assembled_inventory_path, records)
        write_inventory_meta(
            assembled_meta_path,
            args.scenario,
            output_path,
            assembled_inventory_path,
            records,
            completeness,
        )
    if debug_enabled:
        report.info(f"writing offline debug bundle to {debug_dir.resolve()}")
    write_report(
        report_path,
        report,
        records,
        completeness,
        args.scenario,
        port_accounting_enabled=not args.no_update_pending,
    )

    if debug_enabled:
        resolved_paths = {
            "run_root": run_root,
            "input_root": input_root,
            "connection_inventory": connection_path,
            "pending_dir": pending_dir,
            "removed_log_dir": removed_log_dir,
            "output_sdc": output_path,
            "output_inventory": inventory_path,
            "output_report": report_path,
            "debug_dir": debug_dir,
        }
        if not target_layout:
            resolved_paths["info"] = info_path
        if manifest_path is not None:
            resolved_paths["harden_sdc_manifest"] = manifest_path
        input_paths: List[Path] = [connection_path, virtual_path, manual_path]
        if not target_layout:
            input_paths.append(info_path)
            input_paths.extend(port_files)
        input_paths.extend(
            inst.sdc_path for inst in instances.values() if inst.sdc_path is not None
        )
        if manifest_path is not None:
            input_paths.append(manifest_path)
        write_debug_bundle(
            debug_dir,
            argv,
            resolved_paths,
            input_paths,
            instances,
            records,
            completeness,
            report,
        )
        if args.debug_verbose:
            for line in report.lines:
                print("DEBUG: " + line)
            for rec in records:
                print(
                    "DEBUG_CLOCK: name=%s action=%s target=%s direct=%s root=%s source=%s:%s"
                    % (
                        rec.clock_name or "<none>",
                        rec.final_action,
                        rec.target_object or "<none>",
                        rec.direct_source or "<none>",
                        rec.root_source or "<none>",
                        rec.original_sdc or "<none>",
                        rec.source_line,
                    )
                )

    print(f"Instances : {len(instances)}")
    print(f"Records   : {len(records)}")
    if not args.no_write_sdc:
        print(f"SDC       : {output_path}")
    print(f"Inventory : {inventory_path}")
    print(f"Report    : {report_path}")
    print(f"Completeness: {completeness.status}")
    print(f"Available : {completeness.available_count}")
    print(f"Missing   : {completeness.missing_count}")
    if debug_enabled:
        print(f"Debug     : {debug_dir}")
    print(f"Warnings  : {report.warning_count}")
    print(f"Errors    : {report.error_count}")
    return 1 if report.error_count else 0


def debug_dir_from_argv(argv: Sequence[str]) -> Optional[Path]:
    debug_requested = any(
        arg in {"--debug", "--debug-verbose"} or arg.startswith("--debug-dir=")
        for arg in argv
    )
    debug_dir_value = ""
    run_root_value = ""
    for idx, arg in enumerate(argv):
        if arg == "--debug-dir" and idx + 1 < len(argv):
            debug_requested = True
            debug_dir_value = argv[idx + 1]
        elif arg.startswith("--debug-dir="):
            debug_dir_value = arg.split("=", 1)[1]
        elif arg == "--run-root" and idx + 1 < len(argv):
            run_root_value = argv[idx + 1]
        elif arg.startswith("--run-root="):
            run_root_value = arg.split("=", 1)[1]
    if not debug_requested:
        return None
    if debug_dir_value:
        path = Path(debug_dir_value).expanduser()
        if path.is_absolute():
            return path
        base = Path(run_root_value).expanduser() if run_root_value else Path.cwd()
        return base / path
    if run_root_value:
        return Path(run_root_value).expanduser() / "01_middle/debug/01_soc_clocks"
    return Path.cwd() / "debug/01_soc_clocks"


def main(argv: Sequence[str]) -> int:
    try:
        return _main(argv)
    except Exception:
        trace = traceback.format_exc()
        print(trace, file=sys.stderr)
        debug_dir = debug_dir_from_argv(argv)
        if debug_dir is not None:
            try:
                atomic_write_text(debug_dir / "fatal_traceback.txt", trace)
                atomic_write_text(
                    debug_dir / "fatal_repro_command.txt",
                    " ".join(
                        [shlex.quote(sys.executable), shlex.quote(str(Path(__file__).resolve()))]
                        + [shlex.quote(arg) for arg in argv]
                    )
                    + "\n",
                )
                print(f"Fatal debug: {debug_dir}", file=sys.stderr)
            except Exception:
                print("WARNING: failed to write fatal debug bundle", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
