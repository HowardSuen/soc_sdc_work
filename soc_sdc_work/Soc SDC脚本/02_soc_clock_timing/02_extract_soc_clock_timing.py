#!/usr/bin/env python3
"""
Generate one stage/corner/scenario-specific 02 clock timing SDC from a
stage-specific clock timing budget workbook and 01_soc_clocks
clock_inventory.csv.

The script first synchronizes/checks the workbook against 01 clock inventory.
If clocks are added or stale clocks are found, it updates the workbook and
stops before SDC generation.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    from dataclasses import dataclass
except ImportError:  # pragma: no cover - Python 3.6 compatibility path
    def dataclass(_cls=None):
        def wrap(cls):
            annotations = getattr(cls, "__annotations__", {})
            names = list(annotations.keys())
            defaults = {}
            for name in names:
                if hasattr(cls, name):
                    defaults[name] = getattr(cls, name)

            def __init__(self, *args, **kwargs):
                if len(args) > len(names):
                    raise TypeError("too many positional arguments")
                values = {}
                for name, value in zip(names, args):
                    values[name] = value
                for name in names[len(args):]:
                    if name in kwargs:
                        values[name] = kwargs.pop(name)
                    elif name in defaults:
                        values[name] = defaults[name]
                    else:
                        raise TypeError("missing required argument: " + name)
                if kwargs:
                    raise TypeError("unexpected argument: " + sorted(kwargs)[0])
                for name in names:
                    setattr(self, name, values[name])

            def __eq__(self, other):
                if other.__class__ is not cls:
                    return False
                return all(getattr(self, name) == getattr(other, name) for name in names)

            cls.__init__ = __init__
            cls.__eq__ = __eq__
            cls.__hash__ = None
            return cls

        if _cls is None:
            return wrap
        return wrap(_cls)

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Side, Border
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.worksheet.table import Table, TableStyleInfo
except ImportError as exc:  # pragma: no cover - user environment guard
    print("ERROR: openpyxl is required to read/write 02 clock timing xlsx files.", file=sys.stderr)
    raise SystemExit(2) from exc


STAGES = {"synth", "prects", "postcts", "postroute"}
SCENARIOS = {"common", "func", "scan", "mbist", "gpio_in", "gpio_out"}
ACTIVE_01_ACTIONS = {"emit_top_clock", "emit_output_clock", "emit_virtual_clock"}
YES_NO = {"yes", "no"}
SYNC_OK = {"", "OK"}
SYNC_BLOCKED_MISSING = "BLOCKED_BY_MISSING_SDC"
SYNC_VALUES = {"", "OK", "NEW_FROM_01", "STALE_NOT_IN_01", SYNC_BLOCKED_MISSING}

CLOCK_BUDGET_HEADERS = [
    "scenario",
    "stage",
    "corner",
    "clock_name",
    "setup_uncertainty",
    "hold_uncertainty",
    "source_latency_early",
    "source_latency_late",
    "network_latency_early",
    "network_latency_late",
    "transition_min",
    "transition_max",
    "propagated",
    "apply",
    "sync_status",
    "note",
]

PAIR_HEADERS = [
    "scenario",
    "stage",
    "corner",
    "from_clock",
    "to_clock",
    "setup_uncertainty",
    "hold_uncertainty",
    "apply",
    "note",
]

DERATE_HEADERS = [
    "scenario",
    "stage",
    "corner",
    "derate_scope",
    "object_type",
    "early",
    "late",
    "apply",
    "managed_by_flow",
    "note",
]

NUMERIC_COLUMNS = {
    "setup_uncertainty",
    "hold_uncertainty",
    "source_latency_early",
    "source_latency_late",
    "network_latency_early",
    "network_latency_late",
    "transition_min",
    "transition_max",
}
SOURCE_LATENCY_COLUMNS = {"source_latency_early", "source_latency_late"}
NETWORK_LATENCY_COLUMNS = {"network_latency_early", "network_latency_late"}
TRANSITION_COLUMNS = {"transition_min", "transition_max"}

HEADER_FILL = PatternFill("solid", fgColor="215967")
TITLE_FILL = PatternFill("solid", fgColor="335C81")
SUBTITLE_FILL = PatternFill("solid", fgColor="EAF3F6")
NEW_FILL = PatternFill("solid", fgColor="FFF2CC")
STALE_FILL = PatternFill("solid", fgColor="F4CCCC")
BLOCKED_FILL = PatternFill("solid", fgColor="FCE5CD")
CLEAR_FILL = PatternFill(fill_type=None)
THIN_BORDER = Border(
    left=Side(style="thin", color="B8C6CC"),
    right=Side(style="thin", color="B8C6CC"),
    top=Side(style="thin", color="B8C6CC"),
    bottom=Side(style="thin", color="B8C6CC"),
)


@dataclass
class ClockInfo:
    clock_name: str
    direction: str = ""
    clock_kind: str = ""
    source: str = ""


@dataclass
class InventoryContext:
    path: Path
    clocks: Dict[str, ClockInfo]
    scenario: str = ""
    completeness: str = "complete"
    missing_instances: Tuple[str, ...] = ()
    meta_path: Optional[Path] = None
    final_sdc_path: Optional[Path] = None
    final_sdc_digest: str = ""


@dataclass
class BudgetRow:
    row_idx: int
    values: Dict[str, object]


class Report:
    def __init__(self) -> None:
        self.lines: List[str] = []
        self.warning_count = 0
        self.error_count = 0
        self.sync_changed = False
        self.sync_blocking_changed = False

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


def sha256_clock_set(clock_names: Iterable[str]) -> str:
    payload = "\n".join(sorted(clock_names)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(".%s.tmp.%s" % (path.name, os.getpid()))
    try:
        tmp_path.write_text(content, encoding=encoding)
        os.replace(str(tmp_path), str(path))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def atomic_save_workbook(wb, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(".%s.tmp.%s.xlsx" % (path.stem, os.getpid()))
    try:
        wb.save(str(tmp_path))
        os.replace(str(tmp_path), str(path))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def clean_cell(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text.replace(".", "", 1).isdigit():
        return text[:-2]
    return text


def normalize_key(value) -> str:
    return clean_cell(value).strip().lower()


def safe_filename_token(value: str) -> str:
    text = clean_cell(value)
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    token = "".join(char if char in allowed else "_" for char in text)
    return token or "unknown"


def output_sdc_path(cwd: Path, scenario: str, stage: str, corner_token: str) -> Path:
    if scenario == "common":
        return cwd / f"common/02_soc_clock_timing_{stage}_{corner_token}.sdc"
    return cwd / f"scenarios/{scenario}_clock_timing_{stage}_{corner_token}.sdc"


def tcl_obj(name: str) -> str:
    return "{" + name + "}"


def get_clocks(clock_name: str) -> str:
    return f"[get_clocks {tcl_obj(clock_name)}]"


def format_number(value) -> str:
    number = parse_number(value)
    if number is not None:
        return f"{number:.12g}"
    return clean_cell(value)


def parse_number(value) -> Optional[float]:
    text = clean_cell(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def filled_columns(values: Dict[str, object], columns: Iterable[str]) -> List[str]:
    return [column for column in columns if clean_cell(values.get(column))]


def read_clock_inventory(path: Path, report: Report) -> Dict[str, ClockInfo]:
    if not path.is_file():
        raise RuntimeError(f"01 clock inventory not found: {path}")

    clocks: Dict[str, ClockInfo] = {}
    duplicates: List[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        if not reader.fieldnames or "clock_name" not in reader.fieldnames:
            raise RuntimeError(f"{path} does not contain a clock_name column")
        for row_idx, row in enumerate(reader, start=2):
            action = clean_cell(row.get("final_action"))
            if action not in ACTIVE_01_ACTIONS:
                continue
            clock_name = clean_cell(row.get("clock_name"))
            if not clock_name:
                report.warn(f"{path.name} row {row_idx}: active clock record has empty clock_name")
                continue
            if clock_name in clocks:
                duplicates.append(clock_name)
                continue
            clocks[clock_name] = ClockInfo(
                clock_name=clock_name,
                direction=clean_cell(row.get("direction")),
                clock_kind=clean_cell(row.get("clock_kind")),
                source=clean_cell(row.get("direct_source")),
            )

    if duplicates:
        report.error("duplicate active clock_name in 01 inventory: " + ", ".join(sorted(set(duplicates))))
    report.info(f"loaded {len(clocks)} active clock(s) from {path}")
    return clocks


def read_active_inventory_digests(path: Path) -> Set[str]:
    digests: Set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        for row in reader:
            if clean_cell(row.get("final_action")) not in ACTIVE_01_ACTIONS:
                continue
            value = clean_cell(row.get("final_sdc_digest"))
            if value:
                digests.add(value)
    return digests


def extract_clock_names_from_sdc(path: Path) -> Set[str]:
    text = path.read_text(encoding="utf-8")
    logical_lines: List[str] = []
    pending = ""
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line and not pending:
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        logical_lines.append(pending + line)
        pending = ""
    if pending:
        logical_lines.append(pending)

    names: Set[str] = set()
    name_pattern = re.compile(r'(?:^|\s)-name\s+(?:\{([^}]*)\}|"([^"]*)"|(\S+))')
    for line in logical_lines:
        stripped = line.lstrip()
        if not (stripped.startswith("create_clock ") or stripped.startswith("create_generated_clock ")):
            continue
        match = name_pattern.search(stripped)
        if match:
            names.add(next(group for group in match.groups() if group is not None))
    return names


def load_inventory_context(
    inventory_path: Path,
    report: Report,
    expected_scenario: str,
    meta_path: Optional[Path] = None,
    clock_sdc_path: Optional[Path] = None,
    require_meta: bool = False,
) -> InventoryContext:
    clocks = read_clock_inventory(inventory_path, report)
    context = InventoryContext(path=inventory_path, clocks=clocks, scenario=expected_scenario)

    if meta_path is not None and meta_path.is_file():
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise RuntimeError(f"invalid 01 clock inventory meta {meta_path}: {exc}")
        context.meta_path = meta_path
        context.scenario = clean_cell(payload.get("scenario"))
        context.completeness = normalize_key(payload.get("run_completeness")) or "complete"
        context.missing_instances = tuple(
            sorted(clean_cell(item) for item in payload.get("missing_instances", []) if clean_cell(item))
        )
        final_path_text = clean_cell(payload.get("final_sdc_path"))
        if final_path_text:
            context.final_sdc_path = Path(final_path_text)
        context.final_sdc_digest = clean_cell(payload.get("final_sdc_digest"))

        if context.scenario != expected_scenario:
            report.error(
                f"01 inventory meta scenario mismatch: expected {expected_scenario}, got {context.scenario or '<blank>'}"
            )
        expected_inventory_digest = clean_cell(payload.get("inventory_digest"))
        actual_inventory_digest = sha256_file(inventory_path)
        if expected_inventory_digest != actual_inventory_digest:
            report.error(
                f"stale 01 inventory: meta digest {expected_inventory_digest or '<blank>'} "
                f"does not match {actual_inventory_digest}"
            )
        expected_clock_set_digest = clean_cell(payload.get("clock_set_digest"))
        actual_clock_set_digest = sha256_clock_set(clocks)
        if expected_clock_set_digest != actual_clock_set_digest:
            report.error(
                f"stale 01 inventory: clock set digest {expected_clock_set_digest or '<blank>'} "
                f"does not match {actual_clock_set_digest}"
            )
        expected_clock_count = payload.get("clock_count")
        if expected_clock_count is not None:
            try:
                clock_count = int(expected_clock_count)
            except (TypeError, ValueError):
                report.error(f"01 inventory meta has invalid clock_count: {expected_clock_count}")
            else:
                if clock_count != len(clocks):
                    report.error(f"01 inventory meta clock_count={clock_count}, actual={len(clocks)}")
    elif require_meta:
        raise RuntimeError(f"01 assembled clock inventory meta not found: {meta_path}")
    elif meta_path is not None:
        report.warn(f"01 inventory meta not found; legacy validation only: {meta_path}")

    effective_sdc_path = clock_sdc_path or context.final_sdc_path
    if effective_sdc_path is not None:
        if not effective_sdc_path.is_file():
            raise RuntimeError(f"01 final clock SDC not found: {effective_sdc_path}")
        actual_sdc_digest = sha256_file(effective_sdc_path)
        if context.final_sdc_digest and context.final_sdc_digest != actual_sdc_digest:
            report.error(
                f"stale 01 final SDC: meta digest {context.final_sdc_digest} does not match {actual_sdc_digest}"
            )
        inventory_digests = read_active_inventory_digests(inventory_path)
        if inventory_digests and inventory_digests != {actual_sdc_digest}:
            report.error(
                "stale 01 inventory: active final_sdc_digest value(s) do not match final SDC digest: "
                + ", ".join(sorted(inventory_digests))
            )
        sdc_clock_names = extract_clock_names_from_sdc(effective_sdc_path)
        if sdc_clock_names != set(clocks):
            missing = sorted(set(clocks) - sdc_clock_names)
            extra = sorted(sdc_clock_names - set(clocks))
            report.error(
                f"01 final SDC clock set differs from inventory; missing_in_sdc={missing}; extra_in_sdc={extra}"
            )
        context.final_sdc_path = effective_sdc_path
        context.final_sdc_digest = actual_sdc_digest
        report.info(f"verified 01 final SDC digest and {len(sdc_clock_names)} clock name(s): {effective_sdc_path}")
    elif require_meta:
        report.error("01 assembled meta does not provide final_sdc_path")
    else:
        report.warn("01 final clock SDC was not found; legacy inventory authenticity check was skipped")

    if context.completeness not in {"complete", "partial"}:
        report.error(f"01 inventory meta has invalid run_completeness: {context.completeness}")
    report.info(
        f"01 run completeness: {context.completeness}; missing instances: "
        f"{', '.join(context.missing_instances) or '<none>'}"
    )
    return context


def style_title(ws, title: str, subtitle: str, width_cols: int) -> None:
    ws.sheet_view.showGridLines = False
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width_cols)
    ws.cell(1, 1, title)
    ws.cell(1, 1).fill = TITLE_FILL
    ws.cell(1, 1).font = Font(bold=True, color="FFFFFF", size=14)
    ws.row_dimensions[1].height = 24

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width_cols)
    ws.cell(2, 1, subtitle)
    ws.cell(2, 1).fill = SUBTITLE_FILL
    ws.cell(2, 1).font = Font(color="5C6670")
    ws.cell(2, 1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 32


def write_header(ws, headers: Sequence[str], row: int = 4) -> None:
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row, col_idx, header)
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = THIN_BORDER
    ws.freeze_panes = "A5"


def set_widths(ws, widths: Sequence[int]) -> None:
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width


def add_validation(ws, cell_range: str, values: Sequence[str]) -> None:
    quoted = ",".join(values)
    dv = DataValidation(type="list", formula1=f'"{quoted}"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(cell_range)


def ensure_table(ws, name: str, ref: str) -> None:
    for table in ws.tables.values():
        if table.name == name:
            table.ref = ref
            return
    table = Table(displayName=name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(table)


def style_body_row(ws, row_idx: int, col_count: int, fill: Optional[PatternFill] = None) -> None:
    for col_idx in range(1, col_count + 1):
        cell = ws.cell(row_idx, col_idx)
        cell.border = THIN_BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        if fill is not None:
            cell.fill = fill


def setup_clock_budget_sheet(wb: Workbook, stage: str) -> None:
    ws = wb.active
    ws.title = "clock_budget"
    style_title(
        ws,
        f"02 SoC Clock Timing Budget - {stage} - clock_budget",
        (
            f"Stage-specific form. Rows are grouped by clock_name first for comparison within {stage}; "
            "sync_status must be OK/blank before SDC generation."
        ),
        len(CLOCK_BUDGET_HEADERS),
    )
    write_header(ws, CLOCK_BUDGET_HEADERS)
    set_widths(ws, [12, 10, 11, 22, 16, 16, 22, 22, 23, 23, 15, 15, 13, 10, 16, 38])
    add_validation(ws, "A5:A5000", ["common", "func", "scan", "mbist", "gpio_in", "gpio_out"])
    add_validation(ws, "B5:B5000", sorted(STAGES))
    add_validation(ws, "M5:N5000", ["yes", "no"])
    add_validation(
        ws,
        "O5:O5000",
        ["OK", "NEW_FROM_01", "STALE_NOT_IN_01", SYNC_BLOCKED_MISSING],
    )


def setup_aux_sheet(wb: Workbook, name: str, headers: Sequence[str], stage: str) -> None:
    ws = wb.create_sheet(name)
    style_title(
        ws,
        f"02 SoC Clock Timing Budget - {stage} - {name}",
        "Reserved for later 02 expansion. First 02 script version does not generate SDC from this sheet.",
        len(headers),
    )
    write_header(ws, headers)
    set_widths(ws, [12, 10, 12, 20, 20, 16, 16, 12, 40, 40][: len(headers)])


def create_new_workbook(
    form_path: Path,
    scenario: str,
    stage: str,
    corner: str,
    clocks: Dict[str, ClockInfo],
) -> None:
    wb = Workbook()
    setup_clock_budget_sheet(wb, stage)
    setup_aux_sheet(wb, "clock_pair_uncertainty", PAIR_HEADERS, stage)
    setup_aux_sheet(wb, "derate_ocv", DERATE_HEADERS, stage)

    ws = wb["clock_budget"]
    for clock_name in sorted(clocks):
        append_clock_row(ws, scenario, stage, corner, clock_name, "NEW_FROM_01", NEW_FILL)
    refresh_clock_budget_table(ws)
    atomic_save_workbook(wb, form_path)


def find_header_row(ws, required: str = "clock_name") -> Tuple[int, Dict[str, int]]:
    for row_idx in range(1, min(ws.max_row, 30) + 1):
        mapping: Dict[str, int] = {}
        for col_idx in range(1, ws.max_column + 1):
            value = clean_cell(ws.cell(row_idx, col_idx).value)
            if value:
                mapping[value] = col_idx
        if required in mapping:
            return row_idx, mapping
    raise RuntimeError(f"sheet {ws.title} does not contain a {required} header")


def ensure_clock_budget_headers(ws) -> Tuple[int, Dict[str, int], bool]:
    header_row, mapping = find_header_row(ws)
    changed = False
    for header in CLOCK_BUDGET_HEADERS:
        if header in mapping:
            continue
        insert_at = ws.max_column + 1
        if header == "sync_status" and "note" in mapping:
            insert_at = mapping["note"]
            ws.insert_cols(insert_at)
            mapping = {key: (value + 1 if value >= insert_at else value) for key, value in mapping.items()}
        ws.cell(header_row, insert_at, header)
        mapping[header] = insert_at
        changed = True
    write_header(ws, CLOCK_BUDGET_HEADERS, header_row)
    return header_row, mapping, changed


def append_clock_row(
    ws,
    scenario: str,
    stage: str,
    corner: str,
    clock_name: str,
    sync_status: str,
    fill: PatternFill,
) -> int:
    header_row, mapping = find_header_row(ws)
    row_idx = last_budget_data_row(ws, header_row, mapping) + 1
    values = {
        "scenario": scenario,
        "stage": stage,
        "corner": corner,
        "clock_name": clock_name,
        "apply": "no",
        "sync_status": sync_status,
    }
    for header, value in values.items():
        ws.cell(row_idx, mapping[header], value)
    style_body_row(ws, row_idx, len(CLOCK_BUDGET_HEADERS), fill)
    return row_idx


def last_budget_data_row(ws, header_row: int, mapping: Dict[str, int]) -> int:
    last_row = header_row
    columns = [mapping[header] for header in CLOCK_BUDGET_HEADERS if header in mapping]
    for row_idx in range(header_row + 1, ws.max_row + 1):
        if any(clean_cell(ws.cell(row_idx, col_idx).value) for col_idx in columns):
            last_row = row_idx
    return last_row


def read_budget_rows(ws, header_row: int, mapping: Dict[str, int]) -> List[BudgetRow]:
    rows: List[BudgetRow] = []
    for row_idx in range(header_row + 1, ws.max_row + 1):
        values = {header: ws.cell(row_idx, col_idx).value for header, col_idx in mapping.items()}
        if not any(clean_cell(value) for value in values.values()):
            continue
        rows.append(BudgetRow(row_idx=row_idx, values=values))
    return rows


def row_clock_name(row: BudgetRow) -> str:
    return clean_cell(row.values.get("clock_name"))


def row_scenario_key(row: BudgetRow) -> str:
    return normalize_key(row.values.get("scenario"))


def row_stage_key(row: BudgetRow) -> str:
    return normalize_key(row.values.get("stage"))


def row_corner_key(row: BudgetRow) -> str:
    return clean_cell(row.values.get("corner"))


def scenario_priority(row_scenario: str, target_scenario: str) -> int:
    if row_scenario == target_scenario:
        return 2
    if target_scenario != "common" and row_scenario == "common":
        return 1
    return 0


def resolve_winning_rows(rows: Sequence[BudgetRow], scenario: str, stage: str, corner: str) -> List[BudgetRow]:
    winners: Dict[str, Tuple[int, BudgetRow]] = {}
    for row in rows:
        clock_name = row_clock_name(row)
        if not clock_name:
            continue
        if (row_stage_key(row) or stage) != stage:
            continue
        if row_corner_key(row) != corner:
            continue
        priority = scenario_priority(row_scenario_key(row), scenario)
        if priority == 0:
            continue
        current = winners.get(clock_name)
        if current is None or priority > current[0]:
            winners[clock_name] = (priority, row)
    return [item[1] for item in sorted(winners.values(), key=lambda item: item[1].row_idx)]


def refresh_clock_budget_table(ws) -> None:
    header_row, mapping = find_header_row(ws)
    last_row = max(last_budget_data_row(ws, header_row, mapping), header_row + 1)
    table_columns = [mapping[header] for header in CLOCK_BUDGET_HEADERS if header in mapping]
    first_col = min(table_columns) if table_columns else 1
    last_col = max(table_columns) if table_columns else len(CLOCK_BUDGET_HEADERS)
    ref = f"{get_column_letter(first_col)}{header_row}:{get_column_letter(last_col)}{last_row}"
    ensure_table(ws, "ClockBudget", ref)
    for row_idx in range(header_row + 1, last_row + 1):
        style_body_row(ws, row_idx, len(CLOCK_BUDGET_HEADERS))


def sync_workbook(
    wb,
    form_path: Path,
    scenario: str,
    stage: str,
    corner: str,
    inventory: InventoryContext,
    report: Report,
) -> Tuple[object, int, Dict[str, int], List[BudgetRow]]:
    if "clock_budget" not in wb.sheetnames:
        raise RuntimeError(f"{form_path.name} does not contain sheet clock_budget")
    ws = wb["clock_budget"]
    header_row, mapping, header_changed = ensure_clock_budget_headers(ws)
    if header_changed:
        report.sync_changed = True
        report.sync_blocking_changed = True
        report.warn(f"{form_path.name}: added missing clock_budget header(s)")

    rows = read_budget_rows(ws, header_row, mapping)
    selected_scenario_corner_clocks = {row_clock_name(row) for row in resolve_winning_rows(rows, scenario, stage, corner)}
    inv_clocks = set(inventory.clocks)

    missing = sorted(inv_clocks - selected_scenario_corner_clocks)
    relevant_scenarios = {"common"} if scenario == "common" else {"common", scenario}
    relevant_rows = [
        row
        for row in rows
        if row_scenario_key(row) in relevant_scenarios and (row_stage_key(row) or stage) == stage
    ]
    stale = sorted({row_clock_name(row) for row in relevant_rows if row_clock_name(row)} - inv_clocks)

    for clock_name in missing:
        append_clock_row(ws, scenario, stage, corner, clock_name, "NEW_FROM_01", NEW_FILL)
        report.sync_changed = True
        report.sync_blocking_changed = True
        report.warn(
            f"{form_path.name}: added clock from 01 inventory for scenario {scenario}, "
            f"corner {corner}: {clock_name}"
        )

    rows = read_budget_rows(ws, header_row, mapping)
    for row in rows:
        clock_name = clean_cell(row.values.get("clock_name"))
        if not clock_name:
            continue
        row_is_relevant = row_scenario_key(row) in relevant_scenarios and (row_stage_key(row) or stage) == stage
        if row_is_relevant and clock_name in stale:
            if clock_traces_to_missing_instance(clock_name, inventory.missing_instances):
                if clean_cell(row.values.get("sync_status")) != SYNC_BLOCKED_MISSING:
                    ws.cell(row.row_idx, mapping["sync_status"], SYNC_BLOCKED_MISSING)
                    style_body_row(ws, row.row_idx, len(CLOCK_BUDGET_HEADERS), BLOCKED_FILL)
                    report.sync_changed = True
                report.warn(
                    f"{form_path.name} row {row.row_idx}: {clock_name} is blocked by missing harden SDC; "
                    "other available clocks may still be generated"
                )
            else:
                if clean_cell(row.values.get("sync_status")) != "STALE_NOT_IN_01":
                    ws.cell(row.row_idx, mapping["sync_status"], "STALE_NOT_IN_01")
                    style_body_row(ws, row.row_idx, len(CLOCK_BUDGET_HEADERS), STALE_FILL)
                    report.sync_changed = True
                report.sync_blocking_changed = True
                report.warn(
                    f"{form_path.name} row {row.row_idx}: stale clock not found in 01 inventory: {clock_name}"
                )
            continue

        sync_status = clean_cell(row.values.get("sync_status"))
        if clock_name in inv_clocks and sync_status in {"NEW_FROM_01", "STALE_NOT_IN_01", SYNC_BLOCKED_MISSING}:
            if row_ready_for_sync_ok(row):
                ws.cell(row.row_idx, mapping["sync_status"], "OK")
                style_body_row(ws, row.row_idx, len(CLOCK_BUDGET_HEADERS), CLEAR_FILL)
                report.sync_changed = True
                report.info(
                    f"{form_path.name} row {row.row_idx} {clock_name}: "
                    f"sync_status {sync_status} reset to OK"
                )
            else:
                report.warn(
                    f"{form_path.name} row {row.row_idx} {clock_name}: sync_status {sync_status} "
                    "is still blocking; fill budget fields for apply=yes, or set apply=no with note"
                )

    refresh_clock_budget_table(ws)
    rows = read_budget_rows(ws, header_row, mapping)
    return ws, header_row, mapping, rows


def clock_traces_to_missing_instance(clock_name: str, missing_instances: Sequence[str]) -> bool:
    for inst_name in missing_instances:
        if clock_name == inst_name:
            return True
        for separator in ("_", "/", "."):
            if clock_name.startswith(inst_name + separator):
                return True
    return False


def row_ready_for_sync_ok(row: BudgetRow) -> bool:
    values = row.values
    apply_value = normalize_key(values.get("apply"))
    if apply_value == "yes":
        return row_generates_any_command(values)
    if apply_value == "no":
        return bool(clean_cell(values.get("note")))
    return False


def validate_rows(
    rows: Sequence[BudgetRow],
    mapping: Dict[str, int],
    clocks: Dict[str, ClockInfo],
    scenario: str,
    stage: str,
    corner: str,
    report: Report,
) -> None:
    seen_keys = set()
    winning_row_ids = {row.row_idx for row in resolve_winning_rows(rows, scenario, stage, corner)}
    relevant_scenarios = {"common"} if scenario == "common" else {"common", scenario}
    selected_count = 0
    for row in rows:
        values = row.values
        clock_name = clean_cell(values.get("clock_name"))
        if not clock_name:
            report.error(f"clock_budget row {row.row_idx}: missing clock_name")
            continue

        row_stage = normalize_key(values.get("stage"))
        if not row_stage:
            report.warn(f"clock_budget row {row.row_idx} {clock_name}: stage is blank; expected {stage}")
        elif row_stage != stage:
            report.error(f"clock_budget row {row.row_idx} {clock_name}: stage={row_stage}, expected {stage}")

        row_scenario = normalize_key(values.get("scenario"))
        if not row_scenario:
            report.warn(f"clock_budget row {row.row_idx} {clock_name}: scenario is blank; expected {scenario}")
        elif row_scenario not in SCENARIOS:
            report.error(f"clock_budget row {row.row_idx} {clock_name}: invalid scenario {row_scenario}")

        row_corner = normalize_key(values.get("corner"))
        key = (row_scenario, row_stage or stage, row_corner, clock_name)
        if key in seen_keys:
            report.error(
                f"clock_budget row {row.row_idx} {clock_name}: duplicate scenario/stage/corner/clock_name key {key}"
            )
        seen_keys.add(key)

        apply_value = normalize_key(values.get("apply"))
        propagated_value = normalize_key(values.get("propagated"))
        sync_value = clean_cell(values.get("sync_status"))

        selected = row.row_idx in winning_row_ids
        if sync_value not in SYNC_VALUES:
            report.error(f"clock_budget row {row.row_idx} {clock_name}: invalid sync_status {sync_value}")
        if (
            sync_value == "STALE_NOT_IN_01"
            and row_scenario in relevant_scenarios
            and (row_stage or stage) == stage
        ):
            report.error(f"clock_budget row {row.row_idx} {clock_name}: blocking sync_status {sync_value}")
        if selected and sync_value == "NEW_FROM_01":
            report.error(f"clock_budget row {row.row_idx} {clock_name}: blocking sync_status {sync_value}")

        if apply_value == "yes" and not row_scenario:
            report.error(f"clock_budget row {row.row_idx} {clock_name}: apply=yes but scenario is blank")
        if apply_value == "yes" and not row_corner:
            report.error(f"clock_budget row {row.row_idx} {clock_name}: apply=yes but corner is blank")

        if not selected:
            continue
        selected_count += 1
        if sync_value == SYNC_BLOCKED_MISSING:
            report.warn(
                f"clock_budget row {row.row_idx} {clock_name}: skipped because sync_status={SYNC_BLOCKED_MISSING}"
            )
            continue
        clock_info = clocks.get(clock_name)
        if clock_info:
            warn_clock_kind_budget_mismatch(row, clock_info, report)
        warn_propagated_budget_mismatch(row, report)

        if apply_value and apply_value not in YES_NO:
            report.error(f"clock_budget row {row.row_idx} {clock_name}: apply must be yes/no, got {apply_value}")
        if propagated_value and propagated_value not in YES_NO:
            report.error(
                f"clock_budget row {row.row_idx} {clock_name}: propagated must be yes/no, got {propagated_value}"
            )

        for col in NUMERIC_COLUMNS:
            text = clean_cell(values.get(col))
            number = parse_number(text) if text else None
            if text and number is None:
                report.error(f"clock_budget row {row.row_idx} {clock_name}: {col} must be numeric, got {text}")
            elif number is not None and not math.isfinite(number):
                report.error(f"clock_budget row {row.row_idx} {clock_name}: {col} must be finite, got {text}")

        if apply_value == "yes":
            if not row_generates_any_command(values):
                report.error(
                    f"clock_budget row {row.row_idx} {clock_name}: apply=yes but no timing/propagated fields are set"
                )
    report.info(
        f"resolved {selected_count} winning clock_budget row(s) for scenario={scenario}, "
        f"stage={stage}, corner={corner}"
    )
    if selected_count == 0:
        report.error(f"no winning clock_budget rows found for scenario={scenario}, stage={stage}, corner={corner}")


def row_generates_any_command(values: Dict[str, object]) -> bool:
    if normalize_key(values.get("propagated")) == "yes":
        return True
    return any(clean_cell(values.get(col)) for col in NUMERIC_COLUMNS)


def warn_clock_kind_budget_mismatch(row: BudgetRow, clock_info: ClockInfo, report: Report) -> None:
    values = row.values
    clock_name = row_clock_name(row)
    clock_kind = normalize_key(clock_info.clock_kind)

    if "virtual" in clock_kind:
        filled = filled_columns(values, sorted(NETWORK_LATENCY_COLUMNS | TRANSITION_COLUMNS))
        if filled:
            report.warn(
                f"clock_budget row {row.row_idx} {clock_name}: clock_kind={clock_info.clock_kind} "
                f"has no physical clock network; review filled columns: {', '.join(filled)}"
            )

    if "generated" in clock_kind:
        filled = filled_columns(values, sorted(SOURCE_LATENCY_COLUMNS))
        if filled:
            report.warn(
                f"clock_budget row {row.row_idx} {clock_name}: clock_kind={clock_info.clock_kind} "
                f"usually inherits master source latency; review filled columns: {', '.join(filled)}"
            )


def warn_propagated_budget_mismatch(row: BudgetRow, report: Report) -> None:
    values = row.values
    if normalize_key(values.get("propagated")) != "yes":
        return
    filled = filled_columns(values, sorted(NETWORK_LATENCY_COLUMNS | TRANSITION_COLUMNS))
    if filled:
        report.warn(
            f"clock_budget row {row.row_idx} {row_clock_name(row)}: propagated=yes means actual clock "
            f"network is used; review filled columns that may be ignored: {', '.join(filled)}"
        )


def generate_sdc(
    rows: Sequence[BudgetRow],
    scenario: str,
    stage: str,
    corner: str,
    inventory: InventoryContext,
) -> List[str]:
    lines = [
        "################################################################################",
        (
            "# Auto-generated SoC clock timing constraints for "
            f"scenario: {scenario}, stage: {stage}, corner: {corner}"
        ),
        f"# Author: {author_name()}",
        "# Stage: 02_soc_clock_timing",
        "# Script: 02_extract_soc_clock_timing.py",
        f"# Run completeness: {inventory.completeness}",
        f"# Missing instances: {', '.join(inventory.missing_instances) or '<none>'}",
        f"# Source: 02_soc_clock_timing_budget_{stage}.xlsx clock_budget sheet",
        "# Rows are resolved by scenario priority: selected scenario > common.",
        "################################################################################",
        "",
    ]
    emitted_count = 0
    for row in resolve_winning_rows(rows, scenario, stage, corner):
        values = row.values
        if normalize_key(values.get("apply")) != "yes":
            continue
        if clean_cell(values.get("sync_status")) not in SYNC_OK:
            continue
        clock_name = clean_cell(values.get("clock_name"))
        commands = commands_for_row(values)
        if not commands:
            continue
        row_scenario = clean_cell(values.get("scenario")) or "unknown_scenario"
        row_corner = clean_cell(values.get("corner")) or "unknown_corner"
        lines.append(f"# row {row.row_idx}: {row_scenario} / {row_corner} / {clock_name}")
        lines.extend(commands)
        lines.append("")
        emitted_count += len(commands)
    if emitted_count == 0:
        lines.append("# No clock timing commands emitted for selected scenario/stage/corner.")
    return lines


def commands_for_row(values: Dict[str, object]) -> List[str]:
    clock_name = clean_cell(values.get("clock_name"))
    clock_obj = get_clocks(clock_name)
    commands: List[str] = []

    def add_numeric(column: str, template: str) -> None:
        value = values.get(column)
        if clean_cell(value):
            commands.append(template.format(value=format_number(value), clock=clock_obj))

    add_numeric("setup_uncertainty", "set_clock_uncertainty -setup {value} {clock}")
    add_numeric("hold_uncertainty", "set_clock_uncertainty -hold {value} {clock}")
    add_numeric("source_latency_early", "set_clock_latency -source -early {value} {clock}")
    add_numeric("source_latency_late", "set_clock_latency -source -late {value} {clock}")
    add_numeric("network_latency_early", "set_clock_latency -early {value} {clock}")
    add_numeric("network_latency_late", "set_clock_latency -late {value} {clock}")
    add_numeric("transition_min", "set_clock_transition -min {value} {clock}")
    add_numeric("transition_max", "set_clock_transition -max {value} {clock}")
    if normalize_key(values.get("propagated")) == "yes":
        commands.append(f"set_propagated_clock {clock_obj}")
    return commands


def write_report(
    path: Path,
    report: Report,
    scenario: str,
    stage: str,
    corner: str,
    form_path: Path,
    output_path: Path,
    inventory: Optional[InventoryContext] = None,
) -> None:
    lines = [
        "02_soc_clock_timing extraction report",
        "=====================================",
        "",
        f"Author  : {author_name()}",
        "Stage ID: 02_soc_clock_timing",
        "Script  : 02_extract_soc_clock_timing.py",
        f"Scenario: {scenario}",
        f"Stage   : {stage}",
        f"Corner  : {corner}",
        f"Form    : {form_path}",
        f"Output  : {output_path}",
        f"Warnings: {report.warning_count}",
        f"Errors  : {report.error_count}",
        f"Sync changed: {'yes' if report.sync_changed else 'no'}",
    ]
    if inventory is not None:
        lines.extend([
            f"Run completeness: {inventory.completeness}",
            f"Missing instances: {', '.join(inventory.missing_instances) or '<none>'}",
            f"Inventory: {inventory.path.resolve()}",
            f"Inventory meta: {inventory.meta_path.resolve() if inventory.meta_path else '<none>'}",
            f"Final clock SDC: {inventory.final_sdc_path.resolve() if inventory.final_sdc_path else '<none>'}",
        ])
    lines.extend(["", "Messages:"])
    lines.extend(report.lines or ["INFO: no messages"])
    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")


def write_resolved_manifest(
    path: Path,
    rows: Sequence[BudgetRow],
    scenario: str,
    stage: str,
    corner: str,
    inventory: InventoryContext,
    form_path: Path,
    output_path: Path,
) -> None:
    winners = []
    for row in resolve_winning_rows(rows, scenario, stage, corner):
        values = row.values
        apply_value = normalize_key(values.get("apply"))
        sync_value = clean_cell(values.get("sync_status"))
        emitted = apply_value == "yes" and sync_value in SYNC_OK
        winners.append({
            "row": row.row_idx,
            "clock_name": row_clock_name(row),
            "source_scenario": clean_cell(values.get("scenario")),
            "apply": apply_value,
            "sync_status": sync_value,
            "emitted": emitted,
            "command_count": len(commands_for_row(values)) if emitted else 0,
        })
    payload = {
        "author": author_name(),
        "stage": "02_soc_clock_timing",
        "script": "02_extract_soc_clock_timing.py",
        "scenario": scenario,
        "timing_stage": stage,
        "corner": corner,
        "run_completeness": inventory.completeness,
        "missing_instances": list(inventory.missing_instances),
        "inventory_path": str(inventory.path.resolve()),
        "inventory_digest": sha256_file(inventory.path),
        "inventory_meta_path": str(inventory.meta_path.resolve()) if inventory.meta_path else "",
        "final_sdc_path": str(inventory.final_sdc_path.resolve()) if inventory.final_sdc_path else "",
        "final_sdc_digest": inventory.final_sdc_digest,
        "form_path": str(form_path.resolve()),
        "form_digest": sha256_file(form_path),
        "output_path": str(output_path.resolve()),
        "output_digest": sha256_file(output_path),
        "winning_rows": winners,
    }
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate one scenario/stage/corner 02 clock timing SDC "
            "from a stage-specific timing budget xlsx."
        )
    )
    parser.add_argument(
        "--run-root",
        help="target runtime root; reads 01_middle/assembled and writes 02_middle/02_result",
    )
    parser.add_argument("-scenario", "--scenario", required=True, choices=sorted(SCENARIOS), help="timing scenario")
    parser.add_argument("-stage", "--stage", required=True, choices=sorted(STAGES), help="timing stage")
    parser.add_argument("-corner", "--corner", required=True, help="corner / analysis view name")
    parser.add_argument(
        "-input",
        "--input",
        default=None,
        help="01 clock inventory CSV path",
    )
    parser.add_argument("--inventory-meta", help="01 assembled clock inventory meta JSON path")
    parser.add_argument("--clock-sdc", help="final 01 clock SDC path used for digest and clock-set validation")
    parser.add_argument("--form", help="stage timing budget workbook path")
    parser.add_argument(
        "--report",
        help="output report path; default: clock_timing_check_report_<scenario>_<stage>_<corner>.txt",
    )
    parser.add_argument("--resolved-manifest", help="resolved 02 manifest output path")
    parser.add_argument(
        "--require-complete-harden-sdc",
        action="store_true",
        help="block when the 01 assembled inventory reports partial harden SDC availability",
    )
    return parser.parse_args(argv)


def resolve_path(base: Path, value: Optional[str], default: str) -> Path:
    candidate = Path(value) if value else Path(default)
    if candidate.is_absolute():
        return candidate
    return base / candidate


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    print(f"Author: {author_name()}")
    scenario = args.scenario
    stage = args.stage
    corner = clean_cell(args.corner)
    if not corner:
        print("ERROR: -corner must not be blank", file=sys.stderr)
        return 2
    corner_token = safe_filename_token(corner)
    cwd = Path.cwd()
    target_layout = bool(args.run_root)
    run_root = Path(args.run_root).expanduser().resolve() if target_layout else cwd
    report = Report()
    if corner_token != corner:
        report.warn(f"corner name {corner} is written as filename token {corner_token}")

    if target_layout:
        form_path = resolve_path(
            run_root,
            args.form,
            f"02_middle/02_soc_clock_timing_budget_{stage}.xlsx",
        )
        output_path = output_sdc_path(run_root / "02_result", scenario, stage, corner_token)
        report_path = resolve_path(
            run_root,
            args.report,
            f"02_result/reports/clock_timing_check_report_{scenario}_{stage}_{corner_token}.txt",
        )
        inventory_path = resolve_path(
            run_root,
            args.input,
            f"01_middle/assembled/{scenario}/clock_inventory.csv",
        )
        meta_path: Optional[Path] = resolve_path(
            run_root,
            args.inventory_meta,
            f"01_middle/assembled/{scenario}/clock_inventory.meta",
        )
        clock_sdc_path = resolve_path(run_root, args.clock_sdc, args.clock_sdc) if args.clock_sdc else None
        resolved_manifest_path = resolve_path(
            run_root,
            args.resolved_manifest,
            f"02_middle/resolved/{scenario}_{stage}_{corner_token}.manifest",
        )
    else:
        form_path = resolve_path(cwd, args.form, f"02_soc_clock_timing_budget_{stage}.xlsx")
        output_path = output_sdc_path(cwd, scenario, stage, corner_token)
        report_path = resolve_path(
            cwd,
            args.report,
            f"clock_timing_check_report_{scenario}_{stage}_{corner_token}.txt",
        )
        inventory_path = resolve_path(cwd, args.input, "../01_soc_clocks/clock_inventory.csv")
        if args.inventory_meta:
            meta_path = resolve_path(cwd, args.inventory_meta, args.inventory_meta)
        else:
            candidate_meta = inventory_path.with_suffix(".meta")
            meta_path = candidate_meta if candidate_meta.is_file() else None
        if args.clock_sdc:
            clock_sdc_path = resolve_path(cwd, args.clock_sdc, args.clock_sdc)
        else:
            candidate_sdc = cwd / "../01_soc_clocks/common/01_soc_clocks.sdc"
            clock_sdc_path = candidate_sdc if candidate_sdc.is_file() else None
        resolved_manifest_path = (
            resolve_path(cwd, args.resolved_manifest, args.resolved_manifest)
            if args.resolved_manifest
            else None
        )

    report.info(f"resolved run root: {run_root.resolve()}")
    report.info(f"resolved inventory: {inventory_path.resolve()}")
    report.info(f"resolved inventory meta: {meta_path.resolve() if meta_path else '<none>'}")
    report.info(f"resolved final clock SDC: {clock_sdc_path.resolve() if clock_sdc_path else '<from meta or unavailable>'}")
    report.info(f"resolved timing form: {form_path.resolve()}")
    report.info(f"resolved output SDC: {output_path.resolve()}")
    report.info(f"resolved report: {report_path.resolve()}")

    try:
        inventory = load_inventory_context(
            inventory_path,
            report,
            expected_scenario=scenario,
            meta_path=meta_path,
            clock_sdc_path=clock_sdc_path,
            require_meta=target_layout,
        )
    except Exception as exc:
        report.error(str(exc))
        write_report(report_path, report, scenario, stage, corner, form_path, output_path)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if report.error_count:
        write_report(report_path, report, scenario, stage, corner, form_path, output_path, inventory)
        print(f"ERROR: failed to load clean 01 clock inventory. Report: {report_path}", file=sys.stderr)
        return 1
    if args.require_complete_harden_sdc and inventory.completeness != "complete":
        report.error(
            "01 assembled inventory is partial and --require-complete-harden-sdc was requested"
        )
        write_report(report_path, report, scenario, stage, corner, form_path, output_path, inventory)
        print(f"ERROR: incomplete harden SDC availability. Report: {report_path}", file=sys.stderr)
        return 1

    if not form_path.is_file():
        create_new_workbook(form_path, scenario, stage, corner, inventory.clocks)
        report.sync_changed = True
        report.warn(f"created new stage workbook: {form_path}")
        report.warn("fill timing budget values and set sync_status to OK before generating SDC")
        write_report(report_path, report, scenario, stage, corner, form_path, output_path, inventory)
        print(f"Created new workbook: {form_path}")
        print(f"Report: {report_path}")
        print("SDC was not generated because the workbook needs review.")
        return 1

    try:
        wb = load_workbook(form_path)
        ws, header_row, mapping, rows = sync_workbook(
            wb, form_path, scenario, stage, corner, inventory, report
        )
        if report.sync_changed:
            atomic_save_workbook(wb, form_path)
            if report.sync_blocking_changed:
                write_report(report_path, report, scenario, stage, corner, form_path, output_path, inventory)
                print(f"Updated workbook: {form_path}")
                print(f"Report: {report_path}")
                print("SDC was not generated because clock list sync changed the workbook.")
                return 1
            rows = read_budget_rows(ws, header_row, mapping)

        validate_rows(rows, mapping, inventory.clocks, scenario, stage, corner, report)
        if report.error_count:
            write_report(report_path, report, scenario, stage, corner, form_path, output_path, inventory)
            print(f"ERROR: validation failed. Report: {report_path}", file=sys.stderr)
            return 1

        lines = generate_sdc(rows, scenario, stage, corner, inventory)
        atomic_write_text(output_path, "\n".join(lines).rstrip() + "\n")
        report.info(f"wrote SDC: {output_path}")
        if resolved_manifest_path is not None:
            write_resolved_manifest(
                resolved_manifest_path,
                rows,
                scenario,
                stage,
                corner,
                inventory,
                form_path,
                output_path,
            )
            report.info(f"wrote resolved manifest: {resolved_manifest_path}")
        write_report(report_path, report, scenario, stage, corner, form_path, output_path, inventory)
    except Exception as exc:
        report.error(str(exc))
        write_report(report_path, report, scenario, stage, corner, form_path, output_path, inventory)
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"Report: {report_path}", file=sys.stderr)
        return 2

    print(f"Scenario: {scenario}")
    print(f"Stage : {stage}")
    print(f"Corner: {corner}")
    print(f"Form  : {form_path}")
    print(f"SDC   : {output_path}")
    print(f"Report: {report_path}")
    if resolved_manifest_path is not None and resolved_manifest_path.is_file():
        print(f"Manifest: {resolved_manifest_path}")
    print(f"Warnings: {report.warning_count}")
    print(f"Errors  : {report.error_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
