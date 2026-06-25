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
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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
SYNC_VALUES = {"", "OK", "NEW_FROM_01", "STALE_NOT_IN_01"}

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
    add_validation(ws, "O5:O5000", ["OK", "NEW_FROM_01", "STALE_NOT_IN_01"])


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
    form_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(form_path)


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
    clocks: Dict[str, ClockInfo],
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
    form_clocks = {clean_cell(row.values.get("clock_name")) for row in rows if clean_cell(row.values.get("clock_name"))}
    selected_scenario_corner_clocks = {row_clock_name(row) for row in resolve_winning_rows(rows, scenario, stage, corner)}
    inv_clocks = set(clocks)

    missing = sorted(inv_clocks - selected_scenario_corner_clocks)
    stale = sorted(form_clocks - inv_clocks)

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
        if clock_name in stale:
            ws.cell(row.row_idx, mapping["sync_status"], "STALE_NOT_IN_01")
            style_body_row(ws, row.row_idx, len(CLOCK_BUDGET_HEADERS), STALE_FILL)
            report.sync_changed = True
            report.sync_blocking_changed = True
            report.warn(
                f"{form_path.name} row {row.row_idx}: stale clock not found in 01 inventory: {clock_name}"
            )
            continue

        sync_status = clean_cell(row.values.get("sync_status"))
        if sync_status in {"NEW_FROM_01", "STALE_NOT_IN_01"}:
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
        if sync_value == "STALE_NOT_IN_01":
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
            if text and parse_number(text) is None:
                report.error(f"clock_budget row {row.row_idx} {clock_name}: {col} must be numeric, got {text}")

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


def generate_sdc(rows: Sequence[BudgetRow], scenario: str, stage: str, corner: str) -> List[str]:
    lines = [
        "################################################################################",
        (
            "# Auto-generated SoC clock timing constraints for "
            f"scenario: {scenario}, stage: {stage}, corner: {corner}"
        ),
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
) -> None:
    lines = [
        "02_soc_clock_timing extraction report",
        "=====================================",
        "",
        f"Scenario: {scenario}",
        f"Stage   : {stage}",
        f"Corner  : {corner}",
        f"Form    : {form_path}",
        f"Output  : {output_path}",
        f"Warnings: {report.warning_count}",
        f"Errors  : {report.error_count}",
        f"Sync changed: {'yes' if report.sync_changed else 'no'}",
        "",
        "Messages:",
    ]
    lines.extend(report.lines or ["INFO: no messages"])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate one scenario/stage/corner 02 clock timing SDC "
            "from a stage-specific timing budget xlsx."
        )
    )
    parser.add_argument("-scenario", "--scenario", required=True, choices=sorted(SCENARIOS), help="timing scenario")
    parser.add_argument("-stage", "--stage", required=True, choices=sorted(STAGES), help="timing stage")
    parser.add_argument("-corner", "--corner", required=True, help="corner / analysis view name")
    parser.add_argument(
        "-input",
        "--input",
        default="../01_soc_clocks/clock_inventory.csv",
        help="01 clock inventory CSV path",
    )
    parser.add_argument(
        "--report",
        help="output report path; default: clock_timing_check_report_<scenario>_<stage>_<corner>.txt",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    scenario = args.scenario
    stage = args.stage
    corner = clean_cell(args.corner)
    if not corner:
        print("ERROR: -corner must not be blank", file=sys.stderr)
        return 2
    corner_token = safe_filename_token(corner)
    cwd = Path.cwd()
    report = Report()
    if corner_token != corner:
        report.warn(f"corner name {corner} is written as filename token {corner_token}")

    form_path = cwd / f"02_soc_clock_timing_budget_{stage}.xlsx"
    output_path = output_sdc_path(cwd, scenario, stage, corner_token)
    report_path = cwd / (args.report or f"clock_timing_check_report_{scenario}_{stage}_{corner_token}.txt")
    inventory_path = cwd / args.input

    try:
        clocks = read_clock_inventory(inventory_path, report)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if report.error_count:
        write_report(report_path, report, scenario, stage, corner, form_path, output_path)
        print(f"ERROR: failed to load clean 01 clock inventory. Report: {report_path}", file=sys.stderr)
        return 1

    if not form_path.is_file():
        create_new_workbook(form_path, scenario, stage, corner, clocks)
        report.sync_changed = True
        report.warn(f"created new stage workbook: {form_path}")
        report.warn("fill timing budget values and set sync_status to OK before generating SDC")
        write_report(report_path, report, scenario, stage, corner, form_path, output_path)
        print(f"Created new workbook: {form_path}")
        print(f"Report: {report_path}")
        print("SDC was not generated because the workbook needs review.")
        return 1

    try:
        wb = load_workbook(form_path)
        ws, header_row, mapping, rows = sync_workbook(
            wb, form_path, scenario, stage, corner, clocks, report
        )
        if report.sync_changed:
            wb.save(form_path)
            if report.sync_blocking_changed:
                write_report(report_path, report, scenario, stage, corner, form_path, output_path)
                print(f"Updated workbook: {form_path}")
                print(f"Report: {report_path}")
                print("SDC was not generated because clock list sync changed the workbook.")
                return 1
            rows = read_budget_rows(ws, header_row, mapping)

        validate_rows(rows, mapping, clocks, scenario, stage, corner, report)
        if report.error_count:
            write_report(report_path, report, scenario, stage, corner, form_path, output_path)
            print(f"ERROR: validation failed. Report: {report_path}", file=sys.stderr)
            return 1

        lines = generate_sdc(rows, scenario, stage, corner)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        report.info(f"wrote SDC: {output_path}")
        write_report(report_path, report, scenario, stage, corner, form_path, output_path)
    except Exception as exc:
        report.error(str(exc))
        write_report(report_path, report, scenario, stage, corner, form_path, output_path)
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"Report: {report_path}", file=sys.stderr)
        return 2

    print(f"Scenario: {scenario}")
    print(f"Stage : {stage}")
    print(f"Corner: {corner}")
    print(f"Form  : {form_path}")
    print(f"SDC   : {output_path}")
    print(f"Report: {report_path}")
    print(f"Warnings: {report.warning_count}")
    print(f"Errors  : {report.error_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
