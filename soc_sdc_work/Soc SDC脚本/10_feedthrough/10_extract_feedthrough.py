#!/usr/bin/env python3
"""
Build 10 feedthrough inventory/SDC from integration port sheets and the
00_harden_port_inventory connection inventory.

Current scope:
  * identify project-standard fti_/fto_ feedthrough port pairs
  * expand vector feedthrough ports to canonical bit keys
  * emit feedthrough_inventory.csv for 20/30 consumption
  * emit a structural 10_feedthrough.sdc manifest
  * remove fully matched fti/fto ports from 00 pending lists
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
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


FEEDTHROUGH_RE = re.compile(r"^(fti|fto)_(?:(\d+)_)?(.+)$")
PORT_BIT_RE = re.compile(r"^[^\s\[\]]+(?:\[\d+\])?$")
PORT_RANGE_RE = re.compile(r"^(.+)\[(\d+)\s*:\s*(\d+)\]$")
PORT_EXACT_BIT_RE = re.compile(r"^(.+)\[(\d+)\]$")
VALID_DIRECTIONS = {"input", "output", "inout"}
MATCHED_STATUSES = {"", "matched", "ok", "valid"}


INVENTORY_HEADERS = [
    "feedthrough_id",
    "scenario",
    "feedthrough_instance",
    "feedthrough_module",
    "hop_index",
    "base",
    "src_name",
    "dst_name",
    "signal_name",
    "fti_port",
    "fto_port",
    "fti_endpoint",
    "fto_endpoint",
    "bit_index",
    "chain_id",
    "hop_order",
    "upstream_endpoint",
    "downstream_endpoint",
    "validation_status",
    "basis",
    "note",
]


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
    inputs: Dict[str, PortInfo] = field(default_factory=dict)
    outputs: Dict[str, PortInfo] = field(default_factory=dict)
    inouts: Dict[str, PortInfo] = field(default_factory=dict)


@dataclass(frozen=True)
class PortKey:
    inst_name: str
    direction: str
    port_name: str


@dataclass
class ConnectionEdge:
    connection_id: str
    connection_type: str
    src_instance: str
    src_direction: str
    src_port: str
    src_endpoint_key: str = ""
    src_soc_object: str = ""
    dst_instance: str = ""
    dst_direction: str = ""
    dst_port: str = ""
    dst_endpoint_key: str = ""
    dst_soc_object: str = ""
    validation_status: str = ""
    note: str = ""


@dataclass
class ConnectionIndex:
    by_dst: Dict[Tuple[str, str], List[ConnectionEdge]] = field(default_factory=lambda: defaultdict(list))
    by_src: Dict[Tuple[str, str], List[ConnectionEdge]] = field(default_factory=lambda: defaultdict(list))
    count: int = 0


@dataclass
class FeedthroughPort:
    inst_name: str
    module_name: str
    direction: str
    declared_port: str
    canonical_port: str
    prefix: str
    hop_index: str
    base: str
    bit_index: str


@dataclass
class FeedthroughSegment:
    feedthrough_id: str
    scenario: str
    feedthrough_instance: str
    feedthrough_module: str
    hop_index: str
    base: str
    src_name: str
    dst_name: str
    signal_name: str
    fti_port: str
    fto_port: str
    fti_endpoint: str
    fto_endpoint: str
    bit_index: str
    chain_id: str
    hop_order: str
    upstream_endpoint: str
    downstream_endpoint: str
    validation_status: str
    basis: str
    note: str


class Report:
    def __init__(self) -> None:
        self.lines: List[str] = []
        self.warning_count = 0
        self.error_count = 0

    def info(self, msg: str) -> None:
        self.lines.append("INFO: " + msg)

    def warn(self, msg: str) -> None:
        self.warning_count += 1
        self.lines.append("WARNING: " + msg)

    def error(self, msg: str) -> None:
        self.error_count += 1
        self.lines.append("ERROR: " + msg)


def clean_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text.replace(".", "", 1).isdigit():
        return text[:-2]
    return text


def normalize_key(value) -> str:
    return clean_cell(value).strip().lower()


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
        raise RuntimeError("failed to read {0}: {1}".format(path, exc))


def sanitize_id(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", clean_cell(value)).strip("_")
    return token or "unknown"


def brace_list(names: Sequence[str]) -> str:
    return "{" + " ".join(clean_cell(name) for name in names if clean_cell(name)) + "}"


def get_collection(kind: str, objects: Sequence[str]) -> str:
    return "[{0} {1}]".format(kind, brace_list(objects))


def read_info_all(path: Path, report: Report) -> Dict[str, InstInfo]:
    df = read_excel_file(path)
    module_col = get_col(df, ["module_name", "module name", "module"])
    inst_col = get_col(df, ["inst_name", "inst name", "instance", "instance_name"])
    owner_col = get_col(df, ["owner"])
    file_col = get_col(df, ["file_path", "file path", "empty_path", "verilog", "v_path"])

    if not inst_col:
        raise RuntimeError("{0} must contain an inst_name column".format(path))

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
            report.warn("{0} row {1}: module_name is empty; using inst_name".format(path.name, row_idx + 2))
        if inst_name in instances:
            report.warn("duplicate inst_name {0} in {1}; keeping first row".format(inst_name, path.name))
            continue
        instances[inst_name] = InstInfo(
            module_name=module_name,
            inst_name=inst_name,
            owner=clean_cell(row.get(owner_col)) if owner_col else "",
            file_path=file_path,
        )
    report.info("loaded {0} instance(s) from {1}".format(len(instances), path.name))
    return instances


def parse_port_sheet(df: pd.DataFrame) -> Dict[str, Dict[str, PortInfo]]:
    input_col = get_col(df, ["Input"])
    input_width_col = get_col(df, ["Input Width"])
    input_used_col = get_col(df, ["Input Used Width"])
    from_col = get_col(df, ["From Whom"])

    output_col = get_col(df, ["Output"])
    output_width_col = get_col(df, ["Output Width"])
    output_used_col = get_col(df, ["Output Used Width"])
    to_top_col = get_col(df, ["To Top", "To Whom", "To"])

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


def read_port_workbooks(paths: Sequence[Path], report: Report) -> Dict[str, Dict[str, Dict[str, PortInfo]]]:
    sheets: Dict[str, Dict[str, Dict[str, PortInfo]]] = {}
    for path in paths:
        try:
            book = pd.ExcelFile(path)
        except Exception as exc:
            report.error("failed to open port workbook {0}: {1}".format(path.name, exc))
            continue
        for sheet_name in book.sheet_names:
            if sheet_name in sheets:
                report.warn("duplicate port sheet {0}; keeping first occurrence".format(sheet_name))
                continue
            try:
                sheets[sheet_name] = parse_port_sheet(read_excel_file(path, sheet_name))
            except Exception as exc:
                report.error("failed to read {0}:{1}: {2}".format(path.name, sheet_name, exc))
    report.info("loaded {0} instance port sheet(s) from {1} workbook(s)".format(len(sheets), len(paths)))
    return sheets


def default_port_workbooks(cwd: Path, info_name: str, report: Report) -> List[Path]:
    candidates: List[Path] = []
    skipped: List[str] = []
    for path in sorted(cwd.glob("*.xlsx")):
        if path.name == info_name or path.name.startswith("~$"):
            continue
        if path.name.startswith(("port_", "ports_")):
            candidates.append(path)
        else:
            skipped.append(path.name)
    if skipped:
        report.warn("ignored non-port workbook(s) in 10 input directory: " + ", ".join(skipped[:10]))
    return candidates


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
                    "port sheet {0!r} matched instance {1!r} by case/space-insensitive fallback".format(
                        matched_sheet, inst.inst_name
                    )
                )
            elif len(candidates) > 1:
                report.error(
                    "multiple port sheets match instance {0!r} by case/space-insensitive fallback: {1}".format(
                        inst.inst_name, ", ".join(repr(name) for name in candidates)
                    )
                )
        if not data:
            report.warn("no owner port sheet found for instance {0}".format(inst.inst_name))
            continue
        claimed_sheets.add(matched_sheet)
        inst.inputs = data["inputs"]
        inst.outputs = data["outputs"]
        inst.inouts = data["inouts"]

    for sheet_name in sorted(set(sheets) - claimed_sheets):
        report.warn("port workbook sheet {0!r} does not match any inst_name; ignored".format(sheet_name))


def parse_endpoint_key(value: str) -> Tuple[str, str, str]:
    text = clean_cell(value)
    if not text:
        return "", "", ""
    parts = text.split(":", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return "", "", ""


def read_connection_inventory(path: Path, report: Report) -> ConnectionIndex:
    index = ConnectionIndex()
    if not path.is_file():
        report.warn("{0}: connection_inventory.csv not found; feedthrough edge validation will be limited".format(path))
        return index
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        if not reader.fieldnames:
            report.warn("{0}: connection_inventory.csv has no header".format(path))
            return index
        for row_idx, row in enumerate(reader, start=2):
            src_inst = clean_cell(row.get("src_instance"))
            src_dir = clean_cell(row.get("src_direction"))
            src_port = clean_cell(row.get("src_port"))
            dst_inst = clean_cell(row.get("dst_instance"))
            dst_dir = clean_cell(row.get("dst_direction"))
            dst_port = clean_cell(row.get("dst_port"))

            if not (src_inst and src_port):
                key_inst, key_dir, key_port = parse_endpoint_key(clean_cell(row.get("src_endpoint_key")))
                src_inst = src_inst or key_inst
                src_dir = src_dir or key_dir
                src_port = src_port or key_port
            if not (dst_inst and dst_port):
                key_inst, key_dir, key_port = parse_endpoint_key(clean_cell(row.get("dst_endpoint_key")))
                dst_inst = dst_inst or key_inst
                dst_dir = dst_dir or key_dir
                dst_port = dst_port or key_port
            if not (src_inst and src_port and dst_inst and dst_port):
                report.warn("{0} row {1}: skipped connection edge with incomplete src/dst endpoint".format(path.name, row_idx))
                continue

            edge = ConnectionEdge(
                connection_id=clean_cell(row.get("connection_id")),
                connection_type=clean_cell(row.get("connection_type")),
                src_instance=src_inst,
                src_direction=src_dir,
                src_port=src_port,
                src_endpoint_key=clean_cell(row.get("src_endpoint_key")),
                src_soc_object=clean_cell(row.get("src_soc_object")),
                dst_instance=dst_inst,
                dst_direction=dst_dir,
                dst_port=dst_port,
                dst_endpoint_key=clean_cell(row.get("dst_endpoint_key")),
                dst_soc_object=clean_cell(row.get("dst_soc_object")),
                validation_status=clean_cell(row.get("validation_status")),
                note=clean_cell(row.get("note")),
            )
            index.by_dst[(dst_inst, dst_port)].append(edge)
            index.by_src[(src_inst, src_port)].append(edge)
            index.count += 1
    report.info("loaded {0} connection edge(s) from {1}".format(index.count, path))
    return index


def parse_width_range(text: str) -> Optional[Tuple[int, int]]:
    text = clean_cell(text)
    if not text:
        return None
    match = re.fullmatch(r"\[?\s*(\d+)\s*:\s*(\d+)\s*\]?", text)
    if match:
        a = int(match.group(1))
        b = int(match.group(2))
        return min(a, b), max(a, b)
    return None


def parse_width_count(text: str) -> Optional[int]:
    text = clean_cell(text)
    if re.fullmatch(r"\d+", text):
        return int(text)
    return None


def split_port_key(port: str) -> Tuple[str, str, Optional[Tuple[int, int]], bool]:
    port = clean_cell(port)
    range_match = PORT_RANGE_RE.fullmatch(port)
    if range_match:
        a = int(range_match.group(2))
        b = int(range_match.group(3))
        return range_match.group(1), "", (min(a, b), max(a, b)), False
    bit_match = PORT_EXACT_BIT_RE.fullmatch(port)
    if bit_match:
        return bit_match.group(1), bit_match.group(2), None, False
    if "[" in port or "]" in port:
        return port, "", None, True
    return port, "", None, False


def bit_indices_for_port(port: PortInfo) -> Tuple[str, List[str], bool]:
    base, bit_index, explicit_range, malformed = split_port_key(port.name)
    if malformed:
        return base, [], True
    if bit_index:
        return base, [bit_index], False
    if explicit_range is not None:
        lo, hi = explicit_range
        return base, [str(bit) for bit in range(lo, hi + 1)], False

    for width_text in (port.width, port.used_width):
        width_range = parse_width_range(width_text)
        if width_range is not None:
            lo, hi = width_range
            if hi > lo:
                return base, [str(bit) for bit in range(lo, hi + 1)], False
    for width_text in (port.used_width, port.width):
        width = parse_width_count(width_text)
        if width is not None and width > 1:
            return base, [str(bit) for bit in range(0, width)], False
    return base, [""], False


def parse_feedthrough_name(base_port: str) -> Optional[Tuple[str, str, str]]:
    match = FEEDTHROUGH_RE.fullmatch(base_port)
    if not match:
        return None
    prefix, index, base = match.groups()
    return prefix, index if index is not None else "single", base


def canonical_port(base_port: str, bit_index: str) -> str:
    if bit_index:
        return "{0}[{1}]".format(base_port, bit_index)
    return base_port


def iter_feedthrough_ports(instances: Dict[str, InstInfo], report: Report) -> List[FeedthroughPort]:
    found: List[FeedthroughPort] = []

    def visit(inst: InstInfo, direction: str, port: PortInfo) -> None:
        base_port, bits, malformed = bit_indices_for_port(port)
        if malformed:
            if port.name.startswith(("fti_", "fto_")):
                report.error(
                    "{0}: {1} port {2} is not an expandable canonical feedthrough key".format(
                        inst.inst_name, direction, port.name
                    )
                )
            return
        parsed = parse_feedthrough_name(base_port)
        if not parsed:
            return
        prefix, hop_index, base = parsed
        expected_direction = "input" if prefix == "fti" else "output"
        if direction != expected_direction:
            extra = ""
            if direction == "inout":
                extra = "; inout feedthrough ports must be split into explicit directional fti/fto ports before 10 can consume them"
            report.error(
                "{0}: {1}_{2} is listed as {3}, but {4}_* feedthrough ports must be {5}{6}".format(
                    inst.inst_name, prefix, base, direction, prefix, expected_direction, extra
                )
            )
            return
        if not bits:
            report.error("{0}: feedthrough port {1} could not be expanded to scalar/bit keys".format(inst.inst_name, port.name))
            return
        for bit_index in bits:
            found.append(
                FeedthroughPort(
                    inst_name=inst.inst_name,
                    module_name=inst.module_name,
                    direction=direction,
                    declared_port=port.name,
                    canonical_port=canonical_port(base_port, bit_index),
                    prefix=prefix,
                    hop_index=hop_index,
                    base=base,
                    bit_index=bit_index,
                )
            )

    for inst in instances.values():
        for port in inst.inputs.values():
            visit(inst, "input", port)
        for port in inst.outputs.values():
            visit(inst, "output", port)
        for port in inst.inouts.values():
            visit(inst, "inout", port)

    report.info("identified {0} feedthrough port endpoint(s)".format(len(found)))
    return found


def endpoint_collection(inst_name: str, port_name: str) -> str:
    if not inst_name or not port_name:
        return ""
    return get_collection("get_pins", ["{0}/{1}".format(inst_name, port_name)])


def format_soc_object(inst_name: str, port_name: str, soc_object: str, endpoint_key: str) -> str:
    obj = clean_cell(soc_object)
    if obj:
        if obj.startswith("["):
            return obj
        if "/" in obj:
            return get_collection("get_pins", [obj])
        if normalize_key(inst_name) == "top":
            return get_collection("get_ports", [obj])
        return obj
    key_inst, _, key_port = parse_endpoint_key(endpoint_key)
    inst = inst_name or key_inst
    port = port_name or key_port
    if not inst or not port:
        return ""
    if normalize_key(inst) == "top":
        return get_collection("get_ports", [port])
    if normalize_key(inst) in {"fabric", "constant", "const", "unknown"}:
        return "{0}:{1}".format(inst, port)
    return endpoint_collection(inst, port)


def edge_src_endpoint(edge: ConnectionEdge) -> str:
    return format_soc_object(edge.src_instance, edge.src_port, edge.src_soc_object, edge.src_endpoint_key)


def edge_dst_endpoint(edge: ConnectionEdge) -> str:
    return format_soc_object(edge.dst_instance, edge.dst_port, edge.dst_soc_object, edge.dst_endpoint_key)


def parse_base_parts(base: str) -> Tuple[str, str, str]:
    match = re.match(r"^(.+?)2(.+?)_(.+)$", base)
    if not match:
        return "", "", ""
    return match.group(1), match.group(2), match.group(3)


def build_feedthrough_id(inst_name: str, hop_index: str, base: str, bit_index: str) -> str:
    ft_id = "FT_{0}_{1}_{2}".format(sanitize_id(inst_name), sanitize_id(hop_index), sanitize_id(base))
    if bit_index:
        ft_id += "_bit{0}".format(sanitize_id(bit_index))
    return ft_id


def segment_sort_key(seg: FeedthroughSegment) -> Tuple[str, str, int, str]:
    try:
        order = int(seg.hop_order)
    except ValueError:
        order = 0
    return seg.base, seg.bit_index, order, seg.feedthrough_instance


def edge_status_ok(edge: ConnectionEdge) -> bool:
    return normalize_key(edge.validation_status) in MATCHED_STATUSES


def build_segments(
    ports: Sequence[FeedthroughPort],
    connections: ConnectionIndex,
    scenario: str,
    report: Report,
) -> List[FeedthroughSegment]:
    groups: Dict[Tuple[str, str, str, str], Dict[str, List[FeedthroughPort]]] = defaultdict(lambda: {"fti": [], "fto": []})
    for port in ports:
        groups[(port.inst_name, port.hop_index, port.base, port.bit_index)][port.prefix].append(port)

    segments: List[FeedthroughSegment] = []
    for key in sorted(groups):
        inst_name, hop_index, base, bit_index = key
        pair = groups[key]
        fti_ports = pair["fti"]
        fto_ports = pair["fto"]
        label = "{0}/{1}/{2}/{3}".format(inst_name, hop_index, base, bit_index or "scalar")
        if not fti_ports:
            for fto in fto_ports:
                report.error(
                    "{0}: fto port {1} has no matching fti_{2}{3}".format(
                        inst_name, fto.canonical_port, "" if hop_index == "single" else hop_index + "_", base
                    )
                )
            continue
        if not fto_ports:
            for fti in fti_ports:
                report.error(
                    "{0}: fti port {1} has no matching fto_{2}{3}".format(
                        inst_name, fti.canonical_port, "" if hop_index == "single" else hop_index + "_", base
                    )
                )
            continue
        if len(fti_ports) != 1 or len(fto_ports) != 1:
            report.error("{0}: feedthrough pair is not unique ({1} fti, {2} fto)".format(label, len(fti_ports), len(fto_ports)))
            continue

        fti = fti_ports[0]
        fto = fto_ports[0]
        src_name, dst_name, signal_name = parse_base_parts(base)
        notes: List[str] = []
        status = "matched"
        if not src_name or not dst_name:
            report.warn(
                "{0}: feedthrough base {1} does not clearly match <src>2<dst>_<signal>".format(inst_name, base)
            )
            notes.append("base lacks explicit src2dst structure")

        incoming = connections.by_dst.get((inst_name, fti.canonical_port), [])
        outgoing = connections.by_src.get((inst_name, fto.canonical_port), [])
        if not incoming:
            status = "needs_review"
            report.warn("{0}: no 00 connection edge enters {1}/{2}".format(label, inst_name, fti.canonical_port))
            notes.append("missing upstream edge")
        if len(incoming) > 1:
            status = "needs_review"
            report.warn("{0}: multiple 00 connection edges enter {1}/{2}".format(label, inst_name, fti.canonical_port))
            notes.append("multiple upstream edges")
        if not outgoing:
            status = "needs_review"
            report.warn("{0}: no 00 connection edge leaves {1}/{2}".format(label, inst_name, fto.canonical_port))
            notes.append("missing downstream edge")
        if len(outgoing) > 1:
            status = "needs_review"
            report.warn("{0}: multiple 00 connection edges leave {1}/{2}".format(label, inst_name, fto.canonical_port))
            notes.append("multiple downstream edges")
        for edge in incoming + outgoing:
            if not edge_status_ok(edge):
                status = "needs_review"
                report.warn(
                    "{0}: 00 connection {1} validation_status={2}".format(
                        label, edge.connection_id or "-", edge.validation_status or "-"
                    )
                )
                notes.append("connection status needs review")

        upstream = edge_src_endpoint(incoming[0]) if incoming else ""
        downstream = edge_dst_endpoint(outgoing[0]) if outgoing else ""
        hop_order = hop_index if hop_index != "single" else "0"
        segment = FeedthroughSegment(
            feedthrough_id=build_feedthrough_id(inst_name, hop_index, base, bit_index),
            scenario=scenario,
            feedthrough_instance=inst_name,
            feedthrough_module=fti.module_name,
            hop_index=hop_index,
            base=base,
            src_name=src_name,
            dst_name=dst_name,
            signal_name=signal_name,
            fti_port=fti.canonical_port,
            fto_port=fto.canonical_port,
            fti_endpoint=endpoint_collection(inst_name, fti.canonical_port),
            fto_endpoint=endpoint_collection(inst_name, fto.canonical_port),
            bit_index=bit_index,
            chain_id="CHAIN_{0}".format(sanitize_id(base)),
            hop_order=hop_order,
            upstream_endpoint=upstream,
            downstream_endpoint=downstream,
            validation_status=status,
            basis="paired_by_fti_fto_name",
            note="; ".join(sorted(set(notes))),
        )
        segments.append(segment)

    validate_segment_ids(segments, report)
    validate_chain_order(segments, connections, report)
    return segments


def validate_segment_ids(segments: Sequence[FeedthroughSegment], report: Report) -> None:
    by_id: Dict[str, FeedthroughSegment] = {}
    for seg in segments:
        if seg.feedthrough_id in by_id:
            prev = by_id[seg.feedthrough_id]
            report.error(
                "feedthrough_id {0} is not unique: {1}/{2} and {3}/{4}".format(
                    seg.feedthrough_id,
                    prev.feedthrough_instance,
                    prev.fti_port,
                    seg.feedthrough_instance,
                    seg.fti_port,
                )
            )
        else:
            by_id[seg.feedthrough_id] = seg


def validate_chain_order(segments: Sequence[FeedthroughSegment], connections: ConnectionIndex, report: Report) -> None:
    by_chain: Dict[Tuple[str, str], List[FeedthroughSegment]] = defaultdict(list)
    for seg in segments:
        by_chain[(seg.base, seg.bit_index)].append(seg)

    for (base, bit_index), chain_segments in sorted(by_chain.items()):
        numeric = [seg for seg in chain_segments if seg.hop_index != "single"]
        singles = [seg for seg in chain_segments if seg.hop_index == "single"]
        label = "{0}/{1}".format(base, bit_index or "scalar")
        if len(singles) > 1:
            report.warn(
                "{0}: multiple feedthrough hardens use unindexed fti_/fto_; multi-hop paths should use numeric indexes".format(
                    label
                )
            )
        if singles and numeric:
            report.warn("{0}: mixes unindexed and indexed feedthrough segments".format(label))
        if len(numeric) == 1:
            only = numeric[0]
            if only.hop_index != "0":
                report.warn(
                    "{0}: single indexed feedthrough path uses index {1}; expected 0 when an index is used".format(
                        label, only.hop_index
                    )
                )
        if len(numeric) <= 1:
            continue
        orders = sorted(int(seg.hop_index) for seg in numeric if seg.hop_index.isdigit())
        expected = list(range(0, max(orders) + 1)) if orders else []
        if orders != expected:
            report.error("{0}: feedthrough indexes are not contiguous from 0: got {1}".format(label, orders))
            continue
        by_order = {int(seg.hop_index): seg for seg in numeric}
        for order in range(0, max(orders)):
            cur = by_order[order]
            nxt = by_order[order + 1]
            outgoing = connections.by_src.get((cur.feedthrough_instance, cur.fto_port), [])
            if not outgoing:
                report.warn(
                    "{0}: cannot validate index order {1}->{2}; no outgoing connection from {3}/{4}".format(
                        label, order, order + 1, cur.feedthrough_instance, cur.fto_port
                    )
                )
                continue
            if not any(edge.dst_instance == nxt.feedthrough_instance and edge.dst_port == nxt.fti_port for edge in outgoing):
                report.error(
                    "{0}: connection order does not match feedthrough index order; "
                    "{1}/{2} does not drive {3}/{4}".format(
                        label, cur.feedthrough_instance, cur.fto_port, nxt.feedthrough_instance, nxt.fti_port
                    )
                )


def segment_row(seg: FeedthroughSegment) -> Dict[str, str]:
    return {
        "feedthrough_id": seg.feedthrough_id,
        "scenario": seg.scenario,
        "feedthrough_instance": seg.feedthrough_instance,
        "feedthrough_module": seg.feedthrough_module,
        "hop_index": seg.hop_index,
        "base": seg.base,
        "src_name": seg.src_name,
        "dst_name": seg.dst_name,
        "signal_name": seg.signal_name,
        "fti_port": seg.fti_port,
        "fto_port": seg.fto_port,
        "fti_endpoint": seg.fti_endpoint,
        "fto_endpoint": seg.fto_endpoint,
        "bit_index": seg.bit_index,
        "chain_id": seg.chain_id,
        "hop_order": seg.hop_order,
        "upstream_endpoint": seg.upstream_endpoint,
        "downstream_endpoint": seg.downstream_endpoint,
        "validation_status": seg.validation_status,
        "basis": seg.basis,
        "note": seg.note,
    }


def write_inventory(path: Path, segments: Sequence[FeedthroughSegment]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=INVENTORY_HEADERS)
        writer.writeheader()
        for seg in sorted(segments, key=segment_sort_key):
            writer.writerow(segment_row(seg))


def sdc_lines(segments: Sequence[FeedthroughSegment], scenario: str, inventory_label: str) -> List[str]:
    lines = [
        "# Auto-generated by 10_extract_feedthrough.py",
        "# Scenario: {0}".format(scenario),
        "# Structural feedthrough manifest only.",
        "# Timing budgets are handled by 20; path exceptions/overrides are handled by 30.",
        "# Feedthrough inventory: {0}".format(inventory_label),
        "",
    ]
    for seg in sorted(segments, key=segment_sort_key):
        lines.append("# {0} status={1}".format(seg.feedthrough_id, seg.validation_status))
        lines.append("#   fti {0}".format(seg.fti_endpoint))
        lines.append("#   fto {0}".format(seg.fto_endpoint))
        if seg.upstream_endpoint:
            lines.append("#   upstream {0}".format(seg.upstream_endpoint))
        if seg.downstream_endpoint:
            lines.append("#   downstream {0}".format(seg.downstream_endpoint))
    return lines


def write_sdc(path: Path, segments: Sequence[FeedthroughSegment], scenario: str, inventory_path: Path) -> None:
    inventory_label = inventory_path.name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sdc_lines(segments, scenario, inventory_label)).rstrip() + "\n", encoding="utf-8")


def pending_line_key(line: str) -> Optional[Tuple[str, str]]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = stripped.split()
    if len(parts) < 2:
        return None
    direction, port = parts[0], parts[1]
    if direction not in VALID_DIRECTIONS:
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
    if direction not in VALID_DIRECTIONS:
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


def segment_port_keys(seg: FeedthroughSegment) -> List[PortKey]:
    return [
        PortKey(seg.feedthrough_instance, "input", seg.fti_port),
        PortKey(seg.feedthrough_instance, "output", seg.fto_port),
    ]


def removed_log_line_10(seg: FeedthroughSegment, key: PortKey) -> str:
    fields = [
        key.inst_name,
        key.direction,
        key.port_name,
        "covered_by=10_feedthrough",
        "reason=fti_fto_pair",
        "feedthrough_id={0}".format(seg.feedthrough_id),
        "pair={0}".format(seg.fto_port if key.direction == "input" else seg.fti_port),
        "scenario={0}".format(seg.scenario),
        "status={0}".format(seg.validation_status),
    ]
    if seg.bit_index:
        fields.append("bit_index={0}".format(seg.bit_index))
    return " ".join(fields)


def matched_segments_for_pending(segments: Sequence[FeedthroughSegment]) -> List[FeedthroughSegment]:
    return [seg for seg in segments if normalize_key(seg.validation_status) == "matched"]


def update_pending_for_10(cwd: Path, pending_root: Path, segments: Sequence[FeedthroughSegment], report: Report) -> None:
    pending_dir = pending_root / "pending"
    if not pending_dir.exists():
        return
    if not pending_dir.is_dir():
        report.error("{0}: pending path exists but is not a directory".format(pending_dir))
        return

    removable = matched_segments_for_pending(segments)
    if not removable:
        return

    log_dir = pending_root / "removed_log"
    previous_removed = read_removed_keys(log_dir)
    by_inst: Dict[str, List[Tuple[FeedthroughSegment, PortKey]]] = defaultdict(list)
    for seg in removable:
        for key in segment_port_keys(seg):
            by_inst[key.inst_name].append((seg, key))

    removed_items: List[Tuple[FeedthroughSegment, PortKey]] = []
    for inst_name, inst_items in sorted(by_inst.items()):
        pending_file = pending_dir / "{0}.ports".format(inst_name)
        if not pending_file.is_file():
            for seg, key in inst_items:
                if key in previous_removed:
                    continue
                report.error(
                    "{0}: missing pending file for 10 feedthrough port {1}/{2}".format(
                        pending_file, key.inst_name, key.port_name
                    )
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
            report.error("{0}: duplicate pending port line {1} {2}".format(pending_file, direction, port))

        remove_line_indices: Set[int] = set()
        for seg, port_key in inst_items:
            key = (port_key.direction, port_key.port_name)
            if key not in index:
                if port_key in previous_removed:
                    continue
                report.error(
                    "{0}: 10 wants to remove {1} {2}, but it is not present in pending "
                    "and no previous_removed record exists".format(
                        pending_file, port_key.direction, port_key.port_name
                    )
                )
                continue
            remove_line_indices.add(index[key])
            removed_items.append((seg, port_key))

        if remove_line_indices:
            kept = [line for idx, line in enumerate(lines) if idx not in remove_line_indices]
            pending_file.write_text("\n".join(kept).rstrip() + ("\n" if kept else ""), encoding="utf-8")

    if removed_items:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "10_feedthrough.removed"
        existing_lines = log_path.read_text(encoding="utf-8").splitlines() if log_path.is_file() else []
        existing_keys = set(
            key for key in (removed_line_key(line) for line in existing_lines) if key is not None
        )
        new_lines = []
        for seg, key in sorted(removed_items, key=lambda item: (item[1].inst_name, item[1].direction, item[1].port_name)):
            if key not in existing_keys:
                new_lines.append(removed_log_line_10(seg, key))
                existing_keys.add(key)
        if new_lines:
            log_lines = [line for line in existing_lines if line.strip()] + new_lines
            log_path.write_text("\n".join(log_lines).rstrip() + "\n", encoding="utf-8")
        try:
            display_path = log_path.relative_to(cwd)
        except ValueError:
            display_path = log_path
        report.info("removed {0} feedthrough port endpoint(s) from pending; log={1}".format(len(removed_items), display_path))


def report_path(cwd: Path, scenario: str) -> Path:
    return cwd / "feedthrough_check_report_{0}.txt".format(sanitize_id(scenario))


def output_sdc_path(cwd: Path, scenario: str) -> Path:
    return cwd / "common" / "10_feedthrough.sdc"


def build_coverage_lines(segments: Sequence[FeedthroughSegment], ports: Sequence[FeedthroughPort]) -> List[str]:
    lines: List[str] = []
    status_counts: Dict[str, int] = defaultdict(int)
    for seg in segments:
        status_counts[seg.validation_status] += 1
    lines.append("Coverage")
    lines.append("  feedthrough port endpoints identified: {0}".format(len(ports)))
    lines.append("  feedthrough segments emitted: {0}".format(len(segments)))
    for status in sorted(status_counts):
        lines.append("  segments with validation_status={0}: {1}".format(status, status_counts[status]))
    if segments:
        lines.append("")
        lines.append("Segments")
        for seg in sorted(segments, key=segment_sort_key):
            lines.append(
                "  {0}: {1}/{2} -> {3}/{4} status={5}".format(
                    seg.feedthrough_id,
                    seg.feedthrough_instance,
                    seg.fti_port,
                    seg.feedthrough_instance,
                    seg.fto_port,
                    seg.validation_status,
                )
            )
    return lines


def write_report(
    path: Path,
    report: Report,
    scenario: str,
    inventory_path: Path,
    sdc_path: Path,
    coverage_lines: Sequence[str],
) -> None:
    lines = [
        "10_feedthrough extraction report",
        "scenario: {0}".format(scenario),
        "inventory: {0}".format(inventory_path),
        "sdc: {0}".format(sdc_path),
        "warnings: {0}".format(report.warning_count),
        "errors: {0}".format(report.error_count),
        "",
        "Messages",
    ]
    lines.extend(report.lines or ["INFO: no messages"])
    lines.append("")
    lines.extend(coverage_lines)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate 10 feedthrough inventory/SDC")
    parser.add_argument("--info-all", default="info_all.xlsx", help="integration info_all workbook")
    parser.add_argument(
        "--port-workbook",
        action="append",
        default=[],
        help="port workbook path; may be repeated. Defaults to port_*.xlsx and ports_*.xlsx",
    )
    parser.add_argument(
        "--connection-inventory",
        default="00_harden_port_inventory/connection_inventory.csv",
        help="00 bit-to-bit connection inventory",
    )
    parser.add_argument("--pending-root", default="00_harden_port_inventory", help="00 pending inventory root")
    parser.add_argument("--inventory", default="feedthrough_inventory.csv", help="output feedthrough inventory CSV")
    parser.add_argument("--output", default="", help="output SDC path")
    parser.add_argument("--report", default="", help="report path")
    parser.add_argument("-scenario", "--scenario", default="common", help="scenario name")
    parser.add_argument("--no-update-pending", action="store_true", help="do not remove matched ports from pending")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    cwd = Path.cwd()
    report = Report()

    scenario = normalize_key(args.scenario) or "common"
    if scenario != "common":
        report.error(
            "10_feedthrough v1 supports only scenario=common; "
            "mode-specific feedthrough is out of scope and must stay pending/needs_review"
        )
    info_all = cwd / args.info_all
    if not info_all.is_file():
        raise RuntimeError("integration file not found: {0}".format(info_all))

    instances = read_info_all(info_all, report)
    port_paths = [cwd / path for path in args.port_workbook]
    if not port_paths:
        port_paths = default_port_workbooks(cwd, Path(args.info_all).name, report)
    port_sheets = read_port_workbooks(port_paths, report)
    attach_port_data(instances, port_sheets, report)

    connections = read_connection_inventory(cwd / args.connection_inventory, report)
    ft_ports = iter_feedthrough_ports(instances, report)
    segments = build_segments(ft_ports, connections, scenario, report)

    inventory_path = cwd / args.inventory
    sdc_path = cwd / args.output if args.output else output_sdc_path(cwd, scenario)
    rpt_path = cwd / args.report if args.report else report_path(cwd, scenario)

    generated = False
    if report.error_count == 0:
        write_inventory(inventory_path, segments)
        write_sdc(sdc_path, segments, scenario, inventory_path)
        report.info("wrote {0}".format(inventory_path))
        report.info("wrote {0}".format(sdc_path))
        generated = True
    else:
        report.warn("feedthrough inventory/SDC generation skipped because errors were reported")

    if generated and not args.no_update_pending and args.pending_root:
        update_pending_for_10(cwd, cwd / args.pending_root, segments, report)

    coverage_lines = build_coverage_lines(segments, ft_ports)
    write_report(rpt_path, report, scenario, inventory_path, sdc_path, coverage_lines)
    print("Report: {0}".format(rpt_path))
    print("Warnings: {0}  Errors: {1}".format(report.warning_count, report.error_count))
    if report.error_count:
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr)
        raise SystemExit(2)
