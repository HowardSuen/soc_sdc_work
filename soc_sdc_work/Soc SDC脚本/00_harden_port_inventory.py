#!/usr/bin/env python3
"""Build SoC harden port and direct-connection inventory artifacts.

00 is the only stage that reads the raw integration workbooks. It emits a
stable bit-level connection inventory, one harden SDC manifest for the
requested scenario, and (by default) per-instance pending port files.

The implementation intentionally uses a temporary SQLite index for expanded
ports and edges. This keeps memory use bounded when compact bus rows expand to
large bit-level inventories.
"""

import argparse
import csv
import hashlib
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover - deployment environment guard
    print("ERROR: pandas and an xlsx engine are required to read integration workbooks.", file=sys.stderr)
    raise SystemExit(2) from exc


SCRIPT_NAME = "00_harden_port_inventory.py"
STAGE_NAME = "00_harden_port_inventory"
SCHEMA_VERSION = "1.0"
SCENARIOS = ("common", "func", "scan", "mbist", "gpio_in", "gpio_out")
SCENARIO_ORDER = {name: idx for idx, name in enumerate(SCENARIOS)}
DIRECTION_ORDER = {"input": 0, "output": 1, "inout": 2}
PORT_FILE_RE = re.compile(r"^(?:port_.+|ports_.+|ports)\.xlsx$", re.IGNORECASE)
SIGNAL_RE = re.compile(
    r"^(?P<base>[A-Za-z_][A-Za-z0-9_$]*)(?:\[(?P<left>-?\d+)(?::(?P<right>-?\d+))?\])?$"
)
WIDTH_RANGE_RE = re.compile(r"^\[?\s*(-?\d+)\s*:\s*(-?\d+)\s*\]?$" )
VERILOG_LITERAL_RE = re.compile(
    r"^(?:(?P<width>\d+)\s*)?'(?P<signed>[sS]?)(?P<base>[bBoOdDhH])(?P<digits>[0-9a-fA-F_xXzZ]+)$"
)
NC_TOKENS = {"nc", "n/c", "no_connect", "noconnect", "unconnected", "open", "-"}
FALSE_TOKENS = {"", "n", "no", "false", "0", "none", "nc", "n/c", "no_connect"}
TRUE_TOKENS = {"y", "yes", "true", "1"}
INVENTORY_HEADERS = [
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
]
MANIFEST_HEADERS = [
    "scenario",
    "inst_name",
    "module_name",
    "sdc_path",
    "availability_status",
    "note",
]


def _author_part_a():
    return chr(72) + chr(111)


def _author_part_b():
    return chr(119) + chr(97)


def _author_part_c():
    return chr(114) + chr(100)


def author_name():
    return _author_part_a() + _author_part_b() + _author_part_c()


class Report:
    def __init__(self):
        self.lines = []
        self.warning_count = 0
        self.error_count = 0
        self._message_limit = 1000

    def _append(self, level, message):
        if len(self.lines) < self._message_limit:
            self.lines.append("%s: %s" % (level, message))
        elif len(self.lines) == self._message_limit:
            self.lines.append("WARNING: further messages suppressed")

    def info(self, message):
        self._append("INFO", message)

    def warn(self, message):
        self.warning_count += 1
        self._append("WARNING", message)

    def error(self, message):
        self.error_count += 1
        self._append("ERROR", message)


class SignalShape:
    def __init__(self, raw, base, scalar=False, left=None, right=None, explicit_selector=False):
        self.raw = raw
        self.base = base
        self.scalar = scalar
        self.left = left
        self.right = right
        self.explicit_selector = explicit_selector

    @property
    def count(self):
        if self.scalar:
            return 1
        return abs(self.left - self.right) + 1

    @property
    def step(self):
        if self.scalar:
            return 0
        return 1 if self.right >= self.left else -1

    def iter_indices(self):
        if self.scalar:
            yield None
            return
        stop = self.right + self.step
        for value in range(self.left, stop, self.step):
            yield value

    def canonical(self, bit_index):
        if bit_index is None:
            return self.base
        return "%s[%d]" % (self.base, bit_index)


class EndpointSequence:
    def __init__(self, instance, direction, base, shape=None, rows=None, raw="", soc_raw=""):
        self.instance = instance
        self.direction = direction
        self.base = base
        self.shape = shape
        self.rows = rows
        self.raw = raw
        self.soc_raw = soc_raw

    @property
    def count(self):
        if self.rows is not None:
            return len(self.rows)
        return self.shape.count

    def iter_bits(self):
        if self.rows is not None:
            for port, bit_index in self.rows:
                yield port, bit_index, soc_object(self.instance, port, self.soc_raw)
            return
        for bit_index in self.shape.iter_indices():
            port = self.shape.canonical(bit_index)
            yield port, bit_index, soc_object(self.instance, port, self.soc_raw)


def clean_cell(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text


def normalize_col(value):
    return re.sub(r"[^a-z0-9]+", "", clean_cell(value).lower())


def make_column_map(columns):
    result = {}
    for column in columns:
        key = normalize_col(column)
        if key and key not in result:
            result[key] = column
    return result


def find_column(columns, aliases):
    mapping = make_column_map(columns)
    for alias in aliases:
        key = normalize_col(alias)
        if key in mapping:
            return mapping[key]
    return None


def scenario_column(columns, scenario, stem_aliases):
    candidates = []
    for stem in stem_aliases:
        candidates.extend(("%s_%s" % (stem, scenario), "%s_%s" % (scenario, stem)))
    candidates.extend(stem_aliases)
    return find_column(columns, candidates)


def atomic_write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.tmp.%s" % (path.name, os.getpid()))
    try:
        with tmp.open("w", encoding="utf-8", newline="") as file_obj:
            file_obj.write(text)
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_csv(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.tmp.%s" % (path.name, os.getpid()))
    try:
        with tmp.open("w", encoding="utf-8", newline="") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: clean_cell(row.get(key)) for key in headers})
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            tmp.unlink()


def files_equal(left, right):
    if not left.is_file() or not right.is_file():
        return False
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_obj, right.open("rb") as right_obj:
        while True:
            left_chunk = left_obj.read(1024 * 1024)
            right_chunk = right_obj.read(1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_width(value, location):
    text = clean_cell(value)
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        width = int(text)
        if width <= 0:
            raise ValueError("%s: width must be positive, got %s" % (location, text))
        return ("count", width)
    match = WIDTH_RANGE_RE.fullmatch(text)
    if match:
        return ("range", int(match.group(1)), int(match.group(2)))
    raise ValueError("%s: unsupported width/range expression %r" % (location, text))


def parse_signal_token(value, location):
    text = clean_cell(value)
    match = SIGNAL_RE.fullmatch(text)
    if not match:
        raise ValueError("%s: unsupported port expression %r" % (location, text))
    base = match.group("base")
    left = match.group("left")
    right = match.group("right")
    if left is None:
        return base, None, None, False
    if right is None:
        return base, int(left), int(left), True
    return base, int(left), int(right), True


def declaration_shape(value, width_value, used_width_value, location):
    text = clean_cell(value)
    base, left, right, explicit = parse_signal_token(text, location)
    width = parse_width(width_value, location + " width")
    if explicit:
        shape = SignalShape(text, base, scalar=False, left=left, right=right, explicit_selector=True)
        if width is not None:
            declared_count = width[1] if width[0] == "count" else abs(width[1] - width[2]) + 1
            if declared_count != shape.count:
                raise ValueError(
                    "%s: port selector has %d bit(s), but width says %d"
                    % (location, shape.count, declared_count)
                )
    elif width is None or (width[0] == "count" and width[1] == 1):
        shape = SignalShape(text, base, scalar=True)
    elif width[0] == "count":
        shape = SignalShape(text, base, scalar=False, left=width[1] - 1, right=0)
    else:
        shape = SignalShape(text, base, scalar=False, left=width[1], right=width[2])

    used = parse_width(used_width_value, location + " used width")
    if used is not None:
        used_count = used[1] if used[0] == "count" else abs(used[1] - used[2]) + 1
        if used_count != shape.count:
            raise ValueError(
                "%s: used width %d does not identify an exact %d-bit destination; explicit slicing is required"
                % (location, used_count, shape.count)
            )
    return shape


def reference_shape(value, location):
    text = clean_cell(value)
    base, left, right, explicit = parse_signal_token(text, location)
    if not explicit:
        return base, None
    return base, SignalShape(text, base, scalar=False, left=left, right=right, explicit_selector=True)


def canonical_scope(value, location, report):
    text = clean_cell(value).lower()
    if not text or text == "all":
        return "common"
    items = []
    for item in re.split(r"[\s,;|]+", text):
        if not item:
            continue
        if item not in SCENARIOS:
            report.error("%s: invalid scenario_scope %r" % (location, item))
            continue
        if item not in items:
            items.append(item)
    if not items:
        return "common"
    items.sort(key=lambda item: SCENARIO_ORDER[item])
    return "|".join(items)


def bit_index_text(value):
    return "" if value is None else str(value)


def endpoint_key(instance, direction, port):
    return "%s:%s:%s" % (instance, direction, port)


def soc_object(instance, port, raw=""):
    if instance == "top":
        return port
    if instance in ("constant", "nc"):
        return raw
    if instance == "fabric":
        return raw or port
    return "%s/%s" % (instance, port)


def id_token(value):
    def replace_bit(match):
        bit_value = int(match.group(1))
        return "_bitm%d" % abs(bit_value) if bit_value < 0 else "_bit%d" % bit_value

    text = re.sub(r"\[(-?\d+)\]", replace_bit, value)
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    return text or "unnamed"


def connection_id(src_instance, src_port, dst_instance, dst_port):
    value = "CONN_%s_%s__%s_%s" % (
        id_token(src_instance),
        id_token(src_port),
        id_token(dst_instance),
        id_token(dst_port),
    )
    if len(value) <= 240:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return value[:220].rstrip("_") + "_" + digest


def clock_like(port):
    base = port.split("[", 1)[0].lower()
    return bool(
        re.search(r"(?:^|_)(?:clk|clock|aclk|hclk|pclk|refclk)(?:_|$)", base)
        or base.endswith(("clki", "clko"))
    )


def feedthrough_like(port):
    base = port.split("[", 1)[0].lower()
    return base.startswith("fti_") or base.startswith("fto_")


def classify_connection(src_instance, src_port, dst_instance, dst_port):
    if src_instance == "constant":
        return "constant_tie", "00_disposition"
    if src_instance == "nc":
        return "no_connect", "00_disposition"
    if clock_like(src_port) or clock_like(dst_port):
        return "clock_connection", "01_soc_clocks"
    if feedthrough_like(src_port) or feedthrough_like(dst_port):
        return "feedthrough_candidate", "10_feedthrough"
    if src_instance == "top" and dst_instance == "top":
        return "pad_to_pad", "04_soc_io_pads"
    if src_instance == "top" and dst_instance not in ("top", "fabric"):
        return "top_pad_to_harden", "04_soc_io_pads"
    if dst_instance == "top" and src_instance not in ("top", "fabric"):
        return "harden_to_top_pad", "04_soc_io_pads"
    if src_instance == "fabric" and dst_instance != "fabric":
        return "fabric_to_harden", "20_harden_x_if"
    if dst_instance == "fabric" and src_instance != "fabric":
        return "harden_to_fabric", "20_harden_x_if"
    if src_instance not in ("top", "fabric") and dst_instance not in ("top", "fabric"):
        return "harden_to_harden", "20_harden_x_if"
    return "unknown", "review"


def pair_order(src_sequence, dst_sequence):
    src_shape = src_sequence.shape
    dst_shape = dst_sequence.shape
    if src_shape is None or dst_shape is None or src_sequence.count <= 1:
        return "explicit_map"
    if src_shape.step < 0 and dst_shape.step < 0:
        return "msb_to_msb"
    if src_shape.step > 0 and dst_shape.step > 0:
        return "lsb_to_lsb"
    return "explicit_map"


def read_excel(path, sheet_name=0):
    try:
        return pd.read_excel(path, sheet_name=sheet_name)
    except Exception as exc:
        raise RuntimeError("failed to read %s: %s" % (path, exc))


def read_instances(path, scenario, report):
    if not path.is_file():
        report.error("required integration workbook not found: %s" % path)
        return {}
    try:
        frame = read_excel(path)
    except Exception as exc:
        report.error(str(exc))
        return {}
    inst_col = find_column(frame.columns, ("inst_name", "inst name", "instance", "instance_name"))
    module_col = find_column(frame.columns, ("module_name", "module name", "module"))
    owner_col = find_column(frame.columns, ("owner",))
    file_col = find_column(frame.columns, ("file_path", "file path", "empty_path"))
    sdc_col = scenario_column(frame.columns, scenario, ("sdc_path", "sdc_file", "sdc"))
    status_col = scenario_column(
        frame.columns, scenario, ("availability_status", "sdc_status", "availability")
    )
    note_col = scenario_column(frame.columns, scenario, ("sdc_note", "note"))
    if not inst_col or not module_col:
        report.error("%s must contain unique inst_name and module_name columns" % path)
        return {}

    instances = {}
    for row_idx, row in frame.iterrows():
        inst_name = clean_cell(row.get(inst_col))
        module_name = clean_cell(row.get(module_col))
        if not inst_name and not module_name:
            continue
        location = "%s row %d" % (path.name, row_idx + 2)
        if not inst_name or not module_name:
            report.error("%s: inst_name and module_name are both required" % location)
            continue
        if inst_name in instances:
            report.error("%s: duplicate inst_name %s" % (location, inst_name))
            continue
        instances[inst_name] = {
            "inst_name": inst_name,
            "module_name": module_name,
            "owner": clean_cell(row.get(owner_col)) if owner_col else "",
            "file_path": clean_cell(row.get(file_col)) if file_col else "",
            "sdc_hint": clean_cell(row.get(sdc_col)).replace("{scenario}", scenario) if sdc_col else "",
            "status_hint": clean_cell(row.get(status_col)).lower() if status_col else "",
            "sdc_note": clean_cell(row.get(note_col)) if note_col else "",
            "source_row": row_idx + 2,
        }
    report.info("loaded %d instance(s) from %s" % (len(instances), path.name))
    return instances


def discover_port_workbooks(input_root, info_path, explicit_paths, report):
    if explicit_paths:
        paths = []
        for value in explicit_paths:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = input_root / path
            paths.append(path.resolve())
    else:
        paths = []
        if input_root.is_dir():
            for path in input_root.iterdir():
                if not path.is_file() or path.name.startswith("~$"):
                    continue
                if path.resolve() == info_path.resolve():
                    continue
                if PORT_FILE_RE.match(path.name):
                    paths.append(path.resolve())
    paths = sorted(set(paths), key=lambda path: str(path))
    if not paths:
        report.error(
            "no port workbook found; expected inputs/ports.xlsx, port_*.xlsx, ports_*.xlsx, or --port-files"
        )
    for path in paths:
        if not path.is_file():
            report.error("port workbook not found: %s" % path)
    return paths


def create_work_db(path):
    connection = sqlite3.connect(str(path))
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=FILE")
    connection.executescript(
        """
        CREATE TABLE ports (
            inst TEXT NOT NULL,
            direction TEXT NOT NULL,
            port TEXT NOT NULL,
            base TEXT NOT NULL,
            bit_index INTEGER,
            source_workbook TEXT NOT NULL,
            source_sheet TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            PRIMARY KEY (inst, port)
        );
        CREATE INDEX ports_by_base ON ports(inst, base, bit_index);
        CREATE TABLE specs (
            kind TEXT NOT NULL,
            inst TEXT NOT NULL,
            port_expr TEXT NOT NULL,
            width_expr TEXT,
            used_width_expr TEXT,
            peer_expr TEXT,
            inout_name TEXT,
            scenario_scope TEXT NOT NULL,
            source_workbook TEXT NOT NULL,
            source_sheet TEXT NOT NULL,
            source_row INTEGER NOT NULL
        );
        CREATE TABLE edges (
            connection_id TEXT PRIMARY KEY,
            scenario_scope TEXT NOT NULL,
            connection_type TEXT NOT NULL,
            src_instance TEXT NOT NULL,
            src_direction TEXT NOT NULL,
            src_port TEXT NOT NULL,
            src_bit_index TEXT,
            src_endpoint_key TEXT NOT NULL,
            src_soc_object TEXT,
            dst_instance TEXT NOT NULL,
            dst_direction TEXT NOT NULL,
            dst_port TEXT NOT NULL,
            dst_bit_index TEXT,
            dst_endpoint_key TEXT NOT NULL,
            dst_soc_object TEXT,
            range_source_expr TEXT,
            range_sink_expr TEXT,
            bit_pair_order TEXT NOT NULL,
            source_workbook TEXT NOT NULL,
            source_sheet TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            validation_status TEXT NOT NULL,
            owner_hint TEXT,
            note TEXT,
            UNIQUE(src_endpoint_key, dst_endpoint_key)
        );
        CREATE TABLE drivers (
            dst_endpoint_key TEXT PRIMARY KEY,
            src_endpoint_key TEXT NOT NULL,
            connection_id TEXT NOT NULL
        );
        """
    )
    return connection


def add_port_shape(db, base_meta, inst, direction, shape, workbook, sheet, row_idx, report):
    key = (inst, shape.base)
    kind = "scalar" if shape.scalar else "vector"
    if key in base_meta:
        old_direction, old_kind, old_location = base_meta[key]
        if old_direction != direction:
            report.error(
                "%s:%s row %d: port base %s/%s direction conflicts with %s at %s"
                % (workbook, sheet, row_idx, inst, shape.base, old_direction, old_location)
            )
        if old_kind != kind:
            report.error(
                "%s:%s row %d: scalar/vector conflict for %s/%s"
                % (workbook, sheet, row_idx, inst, shape.base)
            )
    else:
        base_meta[key] = (direction, kind, "%s:%s:%d" % (workbook, sheet, row_idx))

    for bit_index in shape.iter_indices():
        port = shape.canonical(bit_index)
        try:
            db.execute(
                "INSERT INTO ports VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (inst, direction, port, shape.base, bit_index, workbook, sheet, row_idx),
            )
        except sqlite3.IntegrityError:
            existing = db.execute(
                "SELECT direction, source_workbook, source_sheet, source_row FROM ports WHERE inst=? AND port=?",
                (inst, port),
            ).fetchone()
            report.error(
                "%s:%s row %d: duplicate canonical port %s %s/%s; first declared at %s:%s:%s"
                % (
                    workbook,
                    sheet,
                    row_idx,
                    direction,
                    inst,
                    port,
                    existing[1],
                    existing[2],
                    existing[3],
                )
            )


def ingest_port_workbooks(paths, input_root, instances, db, report):
    base_meta = {}
    claimed_sheets = {}
    for path in paths:
        try:
            book = pd.ExcelFile(path)
        except Exception as exc:
            report.error("failed to open port workbook %s: %s" % (path, exc))
            continue
        try:
            workbook_name = str(path.relative_to(input_root))
        except ValueError:
            workbook_name = str(path)
        for sheet_name in book.sheet_names:
            if sheet_name in claimed_sheets:
                report.error(
                    "instance sheet %s appears in both %s and %s"
                    % (sheet_name, claimed_sheets[sheet_name], workbook_name)
                )
                continue
            claimed_sheets[sheet_name] = workbook_name
            if sheet_name not in instances:
                report.error("%s:%s does not match any info_all inst_name" % (workbook_name, sheet_name))
                continue
            try:
                frame = read_excel(path, sheet_name=sheet_name)
            except Exception as exc:
                report.error(str(exc))
                continue
            columns = frame.columns
            scope_col = find_column(columns, ("Scenario Scope", "scenario_scope", "scenario"))
            definitions = (
                (
                    "input",
                    find_column(columns, ("Input",)),
                    find_column(columns, ("Input Width",)),
                    find_column(columns, ("Input Used Width",)),
                    find_column(columns, ("From Whom",)),
                    None,
                ),
                (
                    "output",
                    find_column(columns, ("Output",)),
                    find_column(columns, ("Output Width",)),
                    find_column(columns, ("Output Used Width",)),
                    find_column(columns, ("To Top",)),
                    None,
                ),
                (
                    "inout",
                    find_column(columns, ("Inout",)),
                    find_column(columns, ("Inout Width",)),
                    None,
                    find_column(columns, ("Inout Connectivity",)),
                    find_column(columns, ("Inout Name",)),
                ),
            )
            if not any(item[1] for item in definitions):
                report.error("%s:%s has none of Input/Output/Inout columns" % (workbook_name, sheet_name))
                continue
            for frame_idx, row in frame.iterrows():
                excel_row = frame_idx + 2
                scope = canonical_scope(
                    clean_cell(row.get(scope_col)) if scope_col else "common",
                    "%s:%s row %d" % (workbook_name, sheet_name, excel_row),
                    report,
                )
                for direction, port_col, width_col, used_col, peer_col, inout_name_col in definitions:
                    if not port_col:
                        continue
                    port_expr = clean_cell(row.get(port_col))
                    if not port_expr:
                        continue
                    width_expr = clean_cell(row.get(width_col)) if width_col else ""
                    used_expr = clean_cell(row.get(used_col)) if used_col else ""
                    peer_expr = clean_cell(row.get(peer_col)) if peer_col else ""
                    inout_name = clean_cell(row.get(inout_name_col)) if inout_name_col else ""
                    location = "%s:%s row %d %s" % (
                        workbook_name,
                        sheet_name,
                        excel_row,
                        direction,
                    )
                    try:
                        shape = declaration_shape(port_expr, width_expr, used_expr, location)
                    except ValueError as exc:
                        report.error(str(exc))
                        continue
                    add_port_shape(
                        db,
                        base_meta,
                        sheet_name,
                        direction,
                        shape,
                        workbook_name,
                        sheet_name,
                        excel_row,
                        report,
                    )
                    create_spec = False
                    kind_name = direction
                    if direction == "input":
                        if peer_expr:
                            create_spec = True
                        else:
                            report.warn("%s: input has empty From Whom and remains unconnected/pending" % location)
                    elif direction == "output":
                        if peer_expr.lower() not in FALSE_TOKENS:
                            create_spec = True
                            kind_name = "output_to"
                    elif peer_expr:
                        create_spec = True
                    else:
                        report.warn("%s: inout has empty Inout Connectivity" % location)
                    if create_spec:
                        db.execute(
                            "INSERT INTO specs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                kind_name,
                                sheet_name,
                                port_expr,
                                width_expr,
                                used_expr,
                                peer_expr,
                                inout_name,
                                scope,
                                workbook_name,
                                sheet_name,
                                excel_row,
                            ),
                        )
            db.commit()

    for inst_name in sorted(instances):
        if inst_name not in claimed_sheets:
            report.error("no port workbook sheet found for instance %s" % inst_name)
            continue
        count = db.execute("SELECT COUNT(*) FROM ports WHERE inst=?", (inst_name,)).fetchone()[0]
        if count == 0:
            report.error("instance %s has no parsed ports" % inst_name)
    port_count = db.execute("SELECT COUNT(*) FROM ports").fetchone()[0]
    report.info("loaded %d canonical port bit(s) from %d workbook(s)" % (port_count, len(paths)))
    return base_meta


def harden_endpoint(db, instances, instance, signal_text, expected_directions, location):
    base, selector_shape = reference_shape(signal_text, location)
    directions = [row[0] for row in db.execute(
        "SELECT DISTINCT direction FROM ports WHERE inst=? AND base=?", (instance, base)
    ).fetchall()]
    if not directions:
        raise ValueError("%s: endpoint %s.%s is not declared in the port inventory" % (location, instance, base))
    if len(directions) != 1 or directions[0] not in expected_directions:
        raise ValueError(
            "%s: endpoint %s.%s direction %s is not one of %s"
            % (location, instance, base, ",".join(directions), ",".join(sorted(expected_directions)))
        )
    direction = directions[0]
    if selector_shape is None:
        rows = db.execute(
            "SELECT port, bit_index FROM ports WHERE inst=? AND base=? "
            "ORDER BY CASE WHEN bit_index IS NULL THEN 0 ELSE 1 END, bit_index DESC, port",
            (instance, base),
        ).fetchall()
        return EndpointSequence(instance, direction, base, rows=rows, raw=signal_text)

    if selector_shape.count == 1:
        bit_value = next(selector_shape.iter_indices())
        canonical = selector_shape.canonical(bit_value)
        found = db.execute(
            "SELECT 1 FROM ports WHERE inst=? AND direction=? AND port=?",
            (instance, direction, canonical),
        ).fetchone()
        if not found:
            raise ValueError("%s: selected endpoint %s.%s is not declared" % (location, instance, canonical))
    else:
        low = min(selector_shape.left, selector_shape.right)
        high = max(selector_shape.left, selector_shape.right)
        count = db.execute(
            "SELECT COUNT(*) FROM ports WHERE inst=? AND direction=? AND base=? "
            "AND bit_index BETWEEN ? AND ?",
            (instance, direction, base, low, high),
        ).fetchone()[0]
        if count != selector_shape.count:
            raise ValueError(
                "%s: selected range %s.%s has %d declared bit(s), expected %d"
                % (location, instance, signal_text, count, selector_shape.count)
            )
    return EndpointSequence(instance, direction, base, shape=selector_shape, raw=signal_text)


def external_endpoint(instance, direction, signal_text, mirror_shape, location):
    base, selector_shape = reference_shape(signal_text, location)
    shape = selector_shape
    if shape is None:
        if mirror_shape.scalar:
            shape = SignalShape(signal_text, base, scalar=True)
        else:
            shape = SignalShape(
                signal_text,
                base,
                scalar=False,
                left=mirror_shape.left,
                right=mirror_shape.right,
            )
    return EndpointSequence(instance, direction, base, shape=shape, raw=signal_text, soc_raw=signal_text)


def constant_endpoint(value, dest_shape, location):
    text = clean_cell(value).replace(" ", "")
    if text in ("0", "1"):
        literal_width = None
        token = "const_%s" % text
    else:
        match = VERILOG_LITERAL_RE.fullmatch(text)
        if not match:
            return None
        literal_width = int(match.group("width")) if match.group("width") else None
        token = "const_%s" % id_token(text.replace("'", "_"))
    if literal_width is not None and literal_width != dest_shape.count:
        raise ValueError(
            "%s: constant width %d does not match destination width %d"
            % (location, literal_width, dest_shape.count)
        )
    if literal_width and literal_width > 1:
        shape = SignalShape(text, token, scalar=False, left=literal_width - 1, right=0)
    else:
        shape = SignalShape(text, token, scalar=True)
    if shape.count == dest_shape.count:
        return EndpointSequence("constant", "output", token, shape=shape, raw=text, soc_raw=text)
    rows = [(token, None) for _ in range(dest_shape.count)]
    return EndpointSequence("constant", "output", token, rows=rows, raw=text, soc_raw=text)


def resolve_peer_endpoint(db, instances, peer_expr, dest_shape, expected_directions, location):
    peer = clean_cell(peer_expr)
    constant = constant_endpoint(peer, dest_shape, location)
    if constant is not None:
        return constant
    if peer.lower() in NC_TOKENS:
        rows = [("no_connect", None) for _ in range(dest_shape.count)]
        return EndpointSequence("nc", "output", "no_connect", rows=rows, raw=peer, soc_raw=peer)
    if "." not in peer:
        raise ValueError(
            "%s: connection %r must be top.port, inst.port, fabric.port, a constant, or NC"
            % (location, peer)
        )
    instance, signal_text = peer.split(".", 1)
    if not instance or not signal_text:
        raise ValueError("%s: malformed endpoint %r" % (location, peer))
    if instance in instances:
        return harden_endpoint(db, instances, instance, signal_text, expected_directions, location)
    if instance == "top":
        direction = "inout" if "inout" in expected_directions and "output" not in expected_directions else "input"
        return external_endpoint("top", direction, signal_text, dest_shape, location)
    if instance.lower() in ("fabric", "soc", "logic"):
        direction = "inout" if "inout" in expected_directions and "output" not in expected_directions else "output"
        return external_endpoint("fabric", direction, signal_text, dest_shape, location)
    raise ValueError("%s: connection references unknown instance %s" % (location, instance))


def add_edge(db, src, src_bit, dst, dst_bit, spec, order, report):
    src_port, src_index, src_object = src_bit
    dst_port, dst_index, dst_object = dst_bit
    src_key = endpoint_key(src.instance, src.direction, src_port)
    dst_key = endpoint_key(dst.instance, dst.direction, dst_port)
    conn_id = connection_id(src.instance, src_port, dst.instance, dst_port)
    connection_type, owner_hint = classify_connection(
        src.instance, src_port, dst.instance, dst_port
    )
    existing_driver = db.execute(
        "SELECT src_endpoint_key, connection_id FROM drivers WHERE dst_endpoint_key=?", (dst_key,)
    ).fetchone()
    if existing_driver and existing_driver[0] != src_key:
        report.error(
            "%s:%s row %s: destination %s has multiple drivers: %s and %s"
            % (
                spec[8],
                spec[9],
                spec[10],
                dst_key,
                existing_driver[0],
                src_key,
            )
        )
        return
    range_source_expr = spec[5] if spec[0] in ("input", "inout") else spec[2]
    try:
        db.execute(
            "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conn_id,
                spec[7],
                connection_type,
                src.instance,
                src.direction,
                src_port,
                bit_index_text(src_index),
                src_key,
                src_object,
                dst.instance,
                dst.direction,
                dst_port,
                bit_index_text(dst_index),
                dst_key,
                dst_object,
                range_source_expr,
                "%s.%s" % (dst.instance, dst.raw),
                order,
                spec[8],
                spec[9],
                spec[10],
                "matched",
                owner_hint,
                "",
            ),
        )
        if not existing_driver:
            db.execute("INSERT INTO drivers VALUES (?, ?, ?)", (dst_key, src_key, conn_id))
    except sqlite3.IntegrityError as exc:
        report.error(
            "%s:%s row %s: duplicate/conflicting edge %s (%s)"
            % (spec[8], spec[9], spec[10], conn_id, exc)
        )


def process_connection_specs(db, instances, report):
    query = (
        "SELECT kind, inst, port_expr, width_expr, used_width_expr, peer_expr, inout_name, "
        "scenario_scope, source_workbook, source_sheet, source_row FROM specs "
        "ORDER BY source_workbook, source_sheet, source_row, kind"
    )
    for spec in db.execute(query):
        kind, inst, port_expr, width_expr, used_expr, peer_expr, inout_name = spec[:7]
        location = "%s:%s row %s %s" % (spec[8], spec[9], spec[10], kind)
        try:
            local_shape = declaration_shape(port_expr, width_expr, used_expr, location)
            local_direction = "output" if kind == "output_to" else kind
            local_endpoint = EndpointSequence(
                inst, local_direction, local_shape.base, shape=local_shape, raw=port_expr
            )
            if kind == "input":
                src = resolve_peer_endpoint(
                    db, instances, peer_expr, local_shape, {"output", "inout"}, location
                )
                dst = local_endpoint
            elif kind == "inout":
                peer_value = peer_expr
                if "." not in peer_value:
                    peer_value = "fabric.%s" % (inout_name or peer_value)
                src = resolve_peer_endpoint(db, instances, peer_value, local_shape, {"inout"}, location)
                dst = local_endpoint
            else:
                target = clean_cell(peer_expr)
                if target.lower() in TRUE_TOKENS:
                    target = port_expr
                target_instance = "top"
                target_signal = target
                if target.startswith("top."):
                    target_signal = target[4:]
                elif "." in target:
                    target_instance, target_signal = target.split(".", 1)
                    if target_instance.lower() in ("fabric", "soc", "logic"):
                        target_instance = "fabric"
                    elif target_instance == "top":
                        target_instance = "top"
                    else:
                        raise ValueError("%s: To Top references unsupported target %r" % (location, target))
                dst = external_endpoint(
                    target_instance,
                    "input" if target_instance == "fabric" else "output",
                    target_signal,
                    local_shape,
                    location,
                )
                src = local_endpoint

            if src.count != dst.count:
                raise ValueError(
                    "%s: source %s has %d bit(s), destination %s has %d bit(s)"
                    % (location, src.raw, src.count, dst.raw, dst.count)
                )
            order = pair_order(src, dst)
            cross_bit = False
            for src_bit, dst_bit in zip(src.iter_bits(), dst.iter_bits()):
                if src_bit[1] is not None and dst_bit[1] is not None and src_bit[1] != dst_bit[1]:
                    cross_bit = True
                add_edge(db, src, src_bit, dst, dst_bit, spec, order, report)
            if cross_bit:
                report.warn("%s: explicit cross-bit/range renumbering requires review" % location)
        except ValueError as exc:
            report.error(str(exc))
    db.commit()
    edge_count = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    fanout_sources = db.execute(
        "SELECT COUNT(*) FROM (SELECT src_endpoint_key FROM edges GROUP BY src_endpoint_key HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    if fanout_sources:
        report.warn("%d source bit(s) have fanout and require review" % fanout_sources)
    unknown_count = db.execute(
        "SELECT COUNT(*) FROM edges WHERE connection_type='unknown'"
    ).fetchone()[0]
    if unknown_count:
        report.warn("%d edge(s) have connection_type=unknown" % unknown_count)
    report.info("generated %d direct bit-level edge(s)" % edge_count)


def write_inventory_temp(db, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.candidate.%s" % (path.name, os.getpid()))
    query = (
        "SELECT connection_id, scenario_scope, connection_type, src_instance, src_direction, src_port, "
        "src_bit_index, src_endpoint_key, src_soc_object, dst_instance, dst_direction, dst_port, "
        "dst_bit_index, dst_endpoint_key, dst_soc_object, range_source_expr, range_sink_expr, "
        "bit_pair_order, source_workbook, source_sheet, source_row, validation_status, owner_hint, note "
        "FROM edges ORDER BY src_endpoint_key, dst_endpoint_key, connection_id"
    )
    with tmp.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=INVENTORY_HEADERS)
        writer.writeheader()
        previous_source = None
        fanout_index = -1
        for row in db.execute(query):
            values = dict(zip([key for key in INVENTORY_HEADERS if key not in ("schema_version", "fanout_index")], row))
            source_key = values["src_endpoint_key"]
            if source_key != previous_source:
                fanout_index = 0
                previous_source = source_key
            else:
                fanout_index += 1
            values["schema_version"] = SCHEMA_VERSION
            values["fanout_index"] = fanout_index
            writer.writerow({key: clean_cell(values.get(key)) for key in INVENTORY_HEADERS})
    return tmp


def active_pending_dirs(middle_root, legacy_layout):
    if legacy_layout:
        path = middle_root / "pending"
        return [path] if path.is_dir() and any(path.glob("*.ports")) else []
    scenario_root = middle_root / "scenario"
    if not scenario_root.is_dir():
        return []
    result = []
    for path in sorted(scenario_root.glob("*/pending")):
        if path.is_dir() and any(path.glob("*.ports")):
            result.append(path)
    return result


def publish_connection_inventory(candidate, destination, rebuild, reset_scenario, current_pending, middle_root, legacy_layout, report):
    if not destination.exists():
        os.replace(str(candidate), str(destination))
        report.info("created connection inventory %s" % destination)
        return True
    if files_equal(candidate, destination):
        candidate.unlink()
        report.info("existing connection inventory matches current integration forms")
        return True
    if not rebuild:
        candidate.unlink()
        report.error(
            "existing connection inventory differs from current integration forms; rerun with "
            "--rebuild-connection-inventory after preparing a clean scenario state"
        )
        return False
    active = active_pending_dirs(middle_root, legacy_layout)
    unsafe = [path for path in active if path != current_pending or not reset_scenario]
    if unsafe:
        candidate.unlink()
        report.error(
            "cannot rebuild shared connection inventory while scenario pending state exists: %s"
            % ", ".join(str(path) for path in unsafe)
        )
        return False
    os.replace(str(candidate), str(destination))
    report.warn("rebuilt connection inventory by explicit option")
    return True


def port_inventory_digest(db):
    digest = hashlib.sha256()
    query = (
        "SELECT inst, direction, port FROM ports ORDER BY inst, "
        "CASE direction WHEN 'input' THEN 0 WHEN 'output' THEN 1 ELSE 2 END, port"
    )
    for inst, direction, port in db.execute(query):
        digest.update(("%s\0%s\0%s\n" % (inst, direction, port)).encode("utf-8"))
    return digest.hexdigest()


def pending_meta_text(scenario, port_digest, connection_digest, accounting_text):
    return (
        "schema_version=%s\n"
        "author=%s\n"
        "scenario=%s\n"
        "port_accounting=%s\n"
        "port_inventory_digest=%s\n"
        "connection_inventory_digest=%s\n"
        % (
            SCHEMA_VERSION,
            author_name(),
            scenario,
            accounting_text,
            port_digest,
            connection_digest,
        )
    )


def read_key_value_file(path):
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def validate_existing_pending(db, pending_dir, instances, scenario, meta_path, port_digest, report):
    expected_files = {"%s.ports" % inst for inst in instances}
    actual_files = {path.name for path in pending_dir.glob("*.ports")}
    for name in sorted(expected_files - actual_files):
        report.error("existing pending is missing %s" % (pending_dir / name))
    for name in sorted(actual_files - expected_files):
        report.error("existing pending contains unknown instance file %s" % (pending_dir / name))
    for name in sorted(expected_files & actual_files):
        inst = name[:-6]
        seen = set()
        path = pending_dir / name
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            report.error("failed to read pending file %s: %s" % (path, exc))
            continue
        for row_idx, line in enumerate(lines, start=1):
            parts = line.split(None, 1)
            if len(parts) != 2 or parts[0] not in DIRECTION_ORDER:
                report.error("%s row %d: malformed pending line %r" % (path, row_idx, line))
                continue
            key = (parts[0], parts[1])
            if key in seen:
                report.error("%s row %d: duplicate pending key %s %s" % (path, row_idx, key[0], key[1]))
                continue
            seen.add(key)
            exists = db.execute(
                "SELECT 1 FROM ports WHERE inst=? AND direction=? AND port=?",
                (inst, key[0], key[1]),
            ).fetchone()
            if not exists:
                report.error("%s row %d: pending key is not in current port inventory: %s %s" % (path, row_idx, key[0], key[1]))
    meta = read_key_value_file(meta_path)
    if meta:
        if meta.get("scenario") != scenario:
            report.error("%s scenario mismatch: %s != %s" % (meta_path, meta.get("scenario"), scenario))
        if meta.get("port_inventory_digest") != port_digest:
            report.error(
                "current port inventory differs from initialized pending; use --reset-scenario in a clean downstream state"
            )
    else:
        report.warn("existing pending has no pending.meta; structural validation was used")


def build_pending_directory(db, destination, instances):
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / (".pending.tmp.%s" % os.getpid())
    if tmp.exists():
        shutil.rmtree(str(tmp))
    tmp.mkdir(parents=True)
    try:
        for inst in sorted(instances):
            path = tmp / ("%s.ports" % inst)
            with path.open("w", encoding="utf-8", newline="") as file_obj:
                query = (
                    "SELECT direction, port FROM ports WHERE inst=? ORDER BY "
                    "CASE direction WHEN 'input' THEN 0 WHEN 'output' THEN 1 ELSE 2 END, port"
                )
                for direction, port in db.execute(query, (inst,)):
                    file_obj.write("%s %s\n" % (direction, port))
        if destination.exists():
            backup = parent / (".pending.backup.%s" % os.getpid())
            if backup.exists():
                shutil.rmtree(str(backup))
            os.replace(str(destination), str(backup))
            try:
                os.replace(str(tmp), str(destination))
            except Exception:
                os.replace(str(backup), str(destination))
                raise
            shutil.rmtree(str(backup))
        else:
            os.replace(str(tmp), str(destination))
    finally:
        if tmp.exists():
            shutil.rmtree(str(tmp))


def initialize_or_validate_pending(db, pending_dir, meta_path, disposition_log, instances, scenario, reset, connection_path, report):
    digest = port_inventory_digest(db)
    connection_digest = sha256_file(connection_path)
    if pending_dir.exists() and not reset:
        validate_existing_pending(db, pending_dir, instances, scenario, meta_path, digest, report)
        report.info("preserved existing scenario pending state")
        return
    build_pending_directory(db, pending_dir, instances)
    atomic_write_text(meta_path, pending_meta_text(scenario, digest, connection_digest, "enabled"))
    if reset or not disposition_log.exists():
        atomic_write_text(disposition_log, "")
    report.info(
        "%s pending for scenario %s"
        % ("reset" if reset else "initialized", scenario)
    )


def path_for_manifest(path, run_root):
    try:
        return str(path.resolve().relative_to(run_root.resolve()))
    except ValueError:
        return str(path.resolve())


def can_read_file(path):
    try:
        with path.open("rb") as file_obj:
            file_obj.read(1)
        return True
    except OSError:
        return False


def sdc_candidates(input_root, scenario):
    result = []
    for path in input_root.rglob("*.sdc"):
        if not path.is_file() or path.name.startswith("."):
            continue
        result.append(path.resolve())
    return sorted(set(result), key=lambda path: str(path))


def choose_sdc(inst, input_root, run_root, scenario, all_sdc, report):
    status_hint = inst.get("status_hint", "")
    if status_hint == "not_required":
        note = inst.get("sdc_note") or "explicit not_required in info_all"
        return {"path": "", "status": "not_required", "note": note}
    if status_hint and status_hint not in ("available", "missing", "not_required"):
        report.error(
            "info_all row %s: invalid availability status %r for %s"
            % (inst["source_row"], status_hint, inst["inst_name"])
        )

    hint = inst.get("sdc_hint", "")
    if hint:
        hinted = Path(hint).expanduser()
        if not hinted.is_absolute():
            hinted = input_root / hinted
        hinted = hinted.resolve()
        if hinted.is_file():
            if not can_read_file(hinted):
                report.error("SDC is not readable for %s: %s" % (inst["inst_name"], hinted))
                return {"path": path_for_manifest(hinted, run_root), "status": "missing", "note": "mapped path is unreadable"}
            return {
                "path": path_for_manifest(hinted, run_root),
                "status": "available",
                "note": inst.get("sdc_note") or "matched_by=info_all_sdc_path",
            }
        return {
            "path": path_for_manifest(hinted, run_root),
            "status": "missing",
            "note": inst.get("sdc_note") or "mapped SDC has not been delivered",
        }

    inst_name = inst["inst_name"].lower()
    module_name = inst["module_name"].lower()
    canonical_dirs = set(SCENARIOS)

    def path_scope(path):
        try:
            parts = [item.lower() for item in path.relative_to(input_root).parts[:-1]]
        except ValueError:
            parts = [item.lower() for item in path.parts[:-1]]
        if scenario in parts:
            return "current"
        if any(item in canonical_dirs and item != "common" for item in parts):
            return "other"
        return "common"

    groups = [[], [], [], []]
    inst_scenario_stems = {"%s_%s" % (inst_name, scenario), "%s_%s" % (scenario, inst_name)}
    module_scenario_stems = {"%s_%s" % (module_name, scenario), "%s_%s" % (scenario, module_name)}
    for path in all_sdc:
        stem = path.stem.lower()
        scope = path_scope(path)
        if scope == "other":
            continue
        current_specific = scope == "current"
        if stem in inst_scenario_stems or (current_specific and stem == inst_name):
            groups[0].append(path)
        elif stem in module_scenario_stems or (current_specific and stem == module_name):
            groups[1].append(path)
        elif stem == inst_name:
            groups[2].append(path)
        elif stem == module_name:
            groups[3].append(path)

    labels = (
        "scenario-specific inst_name",
        "scenario-specific module_name",
        "inst_name",
        "module_name",
    )
    for index, group in enumerate(groups):
        unique = sorted(set(group), key=lambda path: str(path))
        if not unique:
            continue
        if len(unique) > 1:
            report.error(
                "multiple %s SDC candidates for (%s, %s): %s"
                % (labels[index], inst["inst_name"], scenario, ", ".join(str(path) for path in unique))
            )
            return {"path": "", "status": "missing", "note": "conflicting SDC candidates"}
        selected = unique[0]
        if not can_read_file(selected):
            report.error("SDC is not readable for %s: %s" % (inst["inst_name"], selected))
            return {"path": path_for_manifest(selected, run_root), "status": "missing", "note": "matched SDC is unreadable"}
        return {
            "path": path_for_manifest(selected, run_root),
            "status": "available",
            "note": inst.get("sdc_note") or "matched_by=%s" % labels[index].replace(" ", "_"),
        }
    return {"path": "", "status": "missing", "note": inst.get("sdc_note") or "no exact SDC filename match"}


def build_manifest(instances, input_root, run_root, scenario, report):
    all_sdc = sdc_candidates(input_root, scenario)
    rows = []
    counts = {"available": 0, "missing": 0, "not_required": 0}
    for inst_name in sorted(instances):
        inst = instances[inst_name]
        selected = choose_sdc(inst, input_root, run_root, scenario, all_sdc, report)
        status = selected["status"]
        counts[status] = counts.get(status, 0) + 1
        if status == "missing":
            report.warn("harden SDC missing for (%s, %s)" % (inst_name, scenario))
        rows.append(
            {
                "scenario": scenario,
                "inst_name": inst_name,
                "module_name": inst["module_name"],
                "sdc_path": selected["path"],
                "availability_status": status,
                "note": selected["note"],
            }
        )
    completeness = "partial" if counts["missing"] else "complete"
    report.info(
        "harden SDC availability: available=%d missing=%d not_required=%d"
        % (counts["available"], counts["missing"], counts["not_required"])
    )
    return rows, counts, completeness


def render_report(args, target_layout, paths, instances, db, port_workbooks, counts, completeness, report):
    port_count = db.execute("SELECT COUNT(*) FROM ports").fetchone()[0]
    edge_count = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    accounting = "disabled by explicit option" if args.no_port_accounting else "enabled"
    lines = [
        "SoC SDC 00 Inventory Report",
        "Author: %s" % author_name(),
        "Stage: %s" % STAGE_NAME,
        "Script: %s" % SCRIPT_NAME,
        "Scenario: %s" % args.scenario,
        "Run completeness: %s" % completeness,
        "Port accounting: %s" % accounting,
        "Runtime layout: %s" % ("target" if target_layout else "legacy"),
        "Connection inventory: %s" % paths["connection"].resolve(),
        "Harden SDC manifest: %s" % paths["manifest"].resolve(),
        "Info workbook: %s" % paths["info"].resolve(),
        "Port workbooks: %s" % ", ".join(str(path.resolve()) for path in port_workbooks),
        "",
        "Summary",
        "Instances: %d" % len(instances),
        "Canonical port bits: %d" % port_count,
        "Direct bit edges: %d" % edge_count,
        "Available harden SDC: %d" % counts.get("available", 0),
        "Missing harden SDC: %d" % counts.get("missing", 0),
        "Not-required harden SDC: %d" % counts.get("not_required", 0),
        "Warnings: %d" % report.warning_count,
        "Errors: %d" % report.error_count,
        "",
        "Messages",
    ]
    lines.extend(report.lines or ["INFO: no messages"])
    lines.append("")
    if args.no_port_accounting:
        lines.append("Port closure status: not_tracked")
    else:
        lines.append("Port closure status: initialized_or_preserved; downstream stages must complete accounting")
    return "\n".join(lines) + "\n"


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Generate SoC harden port and connection inventory artifacts.")
    parser.add_argument("--run-root", help="target runtime root; omit only for legacy cwd mode")
    parser.add_argument("--scenario", "-scenario", required=True, choices=SCENARIOS)
    parser.add_argument("--info-all", help="integration summary workbook; target default: inputs/info_all.xlsx")
    parser.add_argument("--port-files", nargs="*", help="explicit port workbook paths relative to inputs")
    parser.add_argument("--no-port-accounting", action="store_true", help="diagnostic run without pending creation/update")
    parser.add_argument(
        "--require-complete-harden-sdc",
        action="store_true",
        help="fail when any required harden SDC is missing",
    )
    parser.add_argument(
        "--rebuild-connection-inventory",
        action="store_true",
        help="replace a changed connection inventory only when scenario pending state is clean",
    )
    parser.add_argument(
        "--reset-scenario",
        action="store_true",
        help="reinitialize the current scenario pending and 00 disposition log",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    print("Author: %s" % author_name())
    report = Report()
    target_layout = bool(args.run_root)
    cwd = Path.cwd()
    run_root = Path(args.run_root).expanduser().resolve() if target_layout else cwd.resolve()
    input_root = run_root / "inputs" if target_layout else run_root
    legacy_layout = not target_layout
    if target_layout:
        middle_root = run_root / "00_middle"
        scenario_root = middle_root / "scenario" / args.scenario
        connection_path = middle_root / "connection_inventory.csv"
        manifest_path = scenario_root / "harden_sdc_manifest.csv"
        pending_dir = scenario_root / "pending"
        disposition_log = scenario_root / "removed_log" / "00_disposition.removed"
        report_path = run_root / "00_result" / "reports" / ("inventory_report_%s.txt" % args.scenario)
        pending_meta = scenario_root / "pending.meta"
    else:
        middle_root = run_root / "00_harden_port_inventory"
        scenario_root = middle_root
        connection_path = middle_root / "connection_inventory.csv"
        manifest_path = middle_root / "harden_sdc_manifest.csv"
        pending_dir = middle_root / "pending"
        disposition_log = middle_root / "removed_log" / "00_disposition.removed"
        report_path = middle_root / "inventory_report.txt"
        pending_meta = middle_root / "pending.meta"

    info_path = Path(args.info_all).expanduser() if args.info_all else input_root / "info_all.xlsx"
    if not info_path.is_absolute():
        info_path = input_root / info_path
    info_path = info_path.resolve()
    paths = {"connection": connection_path, "manifest": manifest_path, "info": info_path}
    report.info("resolved run root: %s" % run_root)
    report.info("resolved input root: %s" % input_root)
    report.info("scenario: %s" % args.scenario)
    if args.no_port_accounting:
        report.info("Port accounting: disabled by explicit option")
    else:
        report.info("Port accounting: enabled")

    middle_root.mkdir(parents=True, exist_ok=True)
    work_db_path = middle_root / (".00_inventory_work.%s.sqlite" % os.getpid())
    if work_db_path.exists():
        work_db_path.unlink()
    db = None
    port_workbooks = []
    instances = {}
    manifest_rows = []
    manifest_counts = {"available": 0, "missing": 0, "not_required": 0}
    completeness = "partial"
    try:
        db = create_work_db(work_db_path)
        instances = read_instances(info_path, args.scenario, report)
        port_workbooks = discover_port_workbooks(
            input_root, info_path, args.port_files, report
        )
        if instances and port_workbooks and report.error_count == 0:
            ingest_port_workbooks(port_workbooks, input_root, instances, db, report)
        if report.error_count == 0:
            process_connection_specs(db, instances, report)
        manifest_rows, manifest_counts, completeness = build_manifest(
            instances, input_root, run_root, args.scenario, report
        )

        inventory_published = False
        if report.error_count == 0:
            candidate = write_inventory_temp(db, connection_path)
            inventory_published = publish_connection_inventory(
                candidate,
                connection_path,
                args.rebuild_connection_inventory,
                args.reset_scenario,
                pending_dir,
                middle_root,
                legacy_layout,
                report,
            )
        if inventory_published:
            atomic_write_csv(manifest_path, MANIFEST_HEADERS, manifest_rows)
            if not args.no_port_accounting:
                initialize_or_validate_pending(
                    db,
                    pending_dir,
                    pending_meta,
                    disposition_log,
                    instances,
                    args.scenario,
                    args.reset_scenario,
                    connection_path,
                    report,
                )
        if args.require_complete_harden_sdc and manifest_counts.get("missing", 0):
            report.error(
                "--require-complete-harden-sdc: %d required harden SDC file(s) are missing"
                % manifest_counts["missing"]
            )
        report_text = render_report(
            args,
            target_layout,
            paths,
            instances,
            db,
            port_workbooks,
            manifest_counts,
            completeness,
            report,
        )
        atomic_write_text(report_path, report_text)
    except Exception as exc:
        report.error("unhandled failure: %s" % exc)
        try:
            if db is not None:
                report_text = render_report(
                    args,
                    target_layout,
                    paths,
                    instances,
                    db,
                    port_workbooks,
                    manifest_counts,
                    completeness,
                    report,
                )
                atomic_write_text(report_path, report_text)
        except Exception:
            pass
    finally:
        if db is not None:
            db.close()
        if work_db_path.exists():
            work_db_path.unlink()

    for line in report.lines:
        if line.startswith("ERROR:"):
            print(line, file=sys.stderr)
    print(
        "Scenario: %s | completeness: %s | warnings: %d | errors: %d"
        % (args.scenario, completeness, report.warning_count, report.error_count)
    )
    if report.error_count:
        print("Report: %s" % report_path, file=sys.stderr)
        return 2
    print("Connection inventory: %s" % connection_path)
    print("Harden SDC manifest: %s" % manifest_path)
    print("Report: %s" % report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
