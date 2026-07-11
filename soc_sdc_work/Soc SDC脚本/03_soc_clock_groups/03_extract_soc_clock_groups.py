#!/usr/bin/env python3
"""
Generate 03 SoC clock group SDC and review reports from a clock group workbook.

The script follows the current SoC SDC policy:
  - default synchronous + explicit async/exclusive groups
  - common + scenario assembled view checks
  - domain closure expansion from 01 clock_inventory.csv
"""

import argparse
import csv
import itertools
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
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.worksheet.table import Table, TableStyleInfo
except ImportError as exc:  # pragma: no cover - user environment guard
    print("ERROR: openpyxl is required to read/write 03 clock group xlsx files.", file=sys.stderr)
    raise SystemExit(2) from exc


SCENARIOS = {"common", "func", "scan", "mbist", "gpio_in", "gpio_out"}
RELATION_TYPES = {"asynchronous", "logically_exclusive", "physically_exclusive"}
RELATION_TYPE_ALIASES = {
    "async": "asynchronous",
    "asynchronous": "asynchronous",
    "logical_exclusive": "logically_exclusive",
    "logically_exclusive": "logically_exclusive",
    "logically exclusive": "logically_exclusive",
    "physical_exclusive": "physically_exclusive",
    "physically_exclusive": "physically_exclusive",
    "physically exclusive": "physically_exclusive",
}
ANALYSIS_STYLES = {"", "normal", "merged_exclusive", "per_scenario_case"}
APPLY_VALUES = {"yes", "no"}
REVIEW_STATUS_VALUES = {"draft", "reviewed", "approved", "rejected"}
YES_NO = {"", "yes", "no"}

ACTIVE_01_ACTIONS = {"emit_top_clock", "emit_output_clock", "emit_virtual_clock"}
CHECK_ONLY_ACTION = "check_only"

DEFAULT_GROUP_COLUMNS = 8
MAX_NON_CLIQUE_WARNINGS = 50

RULE_SHEET = "clock_group_rules"
CANDIDATE_SHEET = "clock_group_candidates"

BASE_RULE_HEADERS = [
    "scenario",
    "group_id",
    "relation_type",
]
TRAILING_RULE_HEADERS = [
    "exclude_descendant_clocks",
    "analysis_style",
    "apply",
    "review_status",
    "owner",
    "basis",
    "cdc_required",
    "note",
]
CANDIDATE_HEADERS = [
    "candidate_id",
    "candidate_type",
    "clock_a",
    "clock_b",
    "tree_root_a",
    "tree_root_b",
    "root_source_a",
    "root_source_b",
    "evidence",
    "suggested_relation",
    "decision",
    "target_group_id",
    "note",
]

HEADER_FILL = PatternFill("solid", fgColor="215967")
TITLE_FILL = PatternFill("solid", fgColor="335C81")
SUBTITLE_FILL = PatternFill("solid", fgColor="EAF3F6")
WARNING_FILL = PatternFill("solid", fgColor="FFF2CC")
ERROR_FILL = PatternFill("solid", fgColor="F4CCCC")
THIN_BORDER = Border(
    left=Side(style="thin", color="B8C6CC"),
    right=Side(style="thin", color="B8C6CC"),
    top=Side(style="thin", color="B8C6CC"),
    bottom=Side(style="thin", color="B8C6CC"),
)


@dataclass
class ClockInfo:
    clock_name: str
    clock_kind: str = ""
    root_source: str = ""
    direct_source: str = ""
    final_action: str = ""
    inst_name: str = ""
    port_name: str = ""
    direction: str = ""
    from_whom: str = ""


@dataclass
class Inventory:
    active: Dict[str, ClockInfo] = field(default_factory=dict)
    all_records: List[ClockInfo] = field(default_factory=list)
    object_to_clock: Dict[str, str] = field(default_factory=dict)
    check_by_object: Dict[str, ClockInfo] = field(default_factory=dict)
    children: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    parent: Dict[str, str] = field(default_factory=dict)
    tree_root: Dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedRule:
    row_idx: int
    scenario: str
    group_id: str
    relation_type: str
    analysis_style: str
    apply: str
    review_status: str
    owner: str
    basis: str
    cdc_required: str
    note: str
    explicit_groups: List[List[str]]
    group_headers: List[str]
    excluded: Set[str]
    effective_groups: List[List[str]] = field(default_factory=list)
    auto_added_by_group: List[List[str]] = field(default_factory=list)


@dataclass(frozen=True)
class PairOccurrence:
    relation_type: str
    group_id: str
    scenario: str
    group_a: str
    group_b: str


class Report:
    def __init__(self) -> None:
        self.lines: List[str] = []
        self.warning_count = 0
        self.error_count = 0
        self.sync_changed = False

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


def canonical_relation_type(value) -> str:
    key = normalize_key(value).replace("-", "_")
    return RELATION_TYPE_ALIASES.get(key, key)


def safe_filename_token(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    token = "".join(char if char in allowed else "_" for char in clean_cell(value))
    return token or "unknown"


def tcl_obj_list(names: Sequence[str]) -> str:
    return "{" + " ".join(names) + "}"


def get_clocks(names: Sequence[str]) -> str:
    return f"[get_clocks {tcl_obj_list(names)}]"


def output_sdc_path(cwd: Path, scenario: str) -> Path:
    if scenario == "common":
        return cwd / "common/03_soc_clock_groups.sdc"
    return cwd / f"scenarios/{scenario}_clock_groups.sdc"


def parse_clock_list(value) -> List[str]:
    text = clean_cell(value)
    if not text:
        return []
    text = text.replace("{", " ").replace("}", " ")
    tokens = [token.strip() for token in re.split(r"[\s,;]+", text) if token.strip()]
    result: List[str] = []
    seen: Set[str] = set()
    for token in tokens:
        if token not in seen:
            result.append(token)
            seen.add(token)
    return result


def clock_object(info: ClockInfo) -> str:
    if info.inst_name and info.port_name:
        return f"{info.inst_name}/{info.port_name}"
    return info.direct_source


def from_whom_to_object(value: str) -> str:
    text = clean_cell(value)
    if not text or text.startswith("top."):
        return text.replace(".", "/", 1) if text else ""
    if "." in text:
        inst, port = text.split(".", 1)
        return f"{inst}/{port}"
    return text


def read_clock_inventory(path: Path, report: Report) -> Inventory:
    if not path.is_file():
        raise RuntimeError(f"01 clock inventory not found: {path}")

    inventory = Inventory()
    duplicates: List[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        if not reader.fieldnames or "clock_name" not in reader.fieldnames:
            raise RuntimeError(f"{path} does not contain a clock_name column")
        for row_idx, row in enumerate(reader, start=2):
            clock_name = clean_cell(row.get("clock_name"))
            final_action = clean_cell(row.get("final_action"))
            if not clock_name:
                report.warn(f"{path.name} row {row_idx}: record has empty clock_name")
                continue
            info = ClockInfo(
                clock_name=clock_name,
                clock_kind=clean_cell(row.get("clock_kind")),
                root_source=clean_cell(row.get("root_source")),
                direct_source=clean_cell(row.get("direct_source")),
                final_action=final_action,
                inst_name=clean_cell(row.get("inst_name")),
                port_name=clean_cell(row.get("port_name")),
                direction=clean_cell(row.get("direction")),
                from_whom=clean_cell(row.get("from_whom")),
            )
            inventory.all_records.append(info)
            obj = clock_object(info)
            if final_action == CHECK_ONLY_ACTION and obj:
                inventory.check_by_object[obj] = info
            if final_action not in ACTIVE_01_ACTIONS:
                continue
            if clock_name in inventory.active:
                duplicates.append(clock_name)
                continue
            inventory.active[clock_name] = info
            for alias in active_clock_aliases(info):
                inventory.object_to_clock.setdefault(alias, clock_name)

    if duplicates:
        report.error("duplicate active clock_name in 01 inventory: " + ", ".join(sorted(set(duplicates))))
    build_clock_genealogy(inventory)
    report.info(f"loaded {len(inventory.active)} active clock(s) from {path}")
    return inventory


def active_clock_aliases(info: ClockInfo) -> List[str]:
    aliases: List[str] = [info.clock_name]
    obj = clock_object(info)
    if obj:
        aliases.append(obj)

    # For top/virtual clocks, the direct_source is the clock object or an alias
    # of the SoC top source. For generated output clocks, direct_source is the
    # parent source pin, so it must not alias to the generated output clock.
    if info.final_action in {"emit_top_clock", "emit_virtual_clock"} and info.direct_source:
        aliases.append(info.direct_source)
    if info.final_action in {"emit_top_clock", "emit_virtual_clock"} and info.root_source == info.direct_source:
        aliases.append(info.root_source)
    return [alias for idx, alias in enumerate(aliases) if alias and alias not in aliases[:idx]]


def resolve_source_clock(source_obj: str, inventory: Inventory, seen: Optional[Set[str]] = None) -> str:
    if not source_obj:
        return ""
    if seen is None:
        seen = set()
    if source_obj in seen:
        return ""
    seen.add(source_obj)

    direct = inventory.object_to_clock.get(source_obj)
    if direct:
        return direct

    check = inventory.check_by_object.get(source_obj)
    if not check:
        return ""

    upstream_obj = from_whom_to_object(check.from_whom)
    if upstream_obj:
        upstream_clock = resolve_source_clock(upstream_obj, inventory, seen)
        if upstream_clock:
            return upstream_clock

    if check.root_source:
        root_clock = resolve_source_clock(check.root_source, inventory, seen)
        if root_clock:
            return root_clock
    return ""


def build_clock_genealogy(inventory: Inventory) -> None:
    for clock_name, info in inventory.active.items():
        if "generated" not in normalize_key(info.clock_kind):
            continue
        parent = resolve_source_clock(info.direct_source, inventory)
        if parent and parent != clock_name:
            inventory.parent[clock_name] = parent
            inventory.children[parent].add(clock_name)
    for clock_name in inventory.active:
        inventory.tree_root[clock_name] = tree_root_of(clock_name, inventory)


def tree_root_of(clock_name: str, inventory: Inventory) -> str:
    if not clock_name:
        return ""
    seen: Set[str] = set()
    current = clock_name
    while current and current not in seen:
        seen.add(current)
        parent = inventory.parent.get(current)
        if not parent:
            return current
        current = parent
    return current or clock_name


def descendants_of(clock_name: str, inventory: Inventory) -> List[str]:
    result: List[str] = []
    seen = {clock_name}
    stack = sorted(inventory.children.get(clock_name, set()))
    while stack:
        child = stack.pop(0)
        if child in seen:
            continue
        seen.add(child)
        result.append(child)
        for grandchild in sorted(inventory.children.get(child, set())):
            if grandchild not in seen:
                stack.append(grandchild)
    return result


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
    ws.row_dimensions[2].height = 36


def write_header(ws, headers: Sequence[str], row: int = 4) -> None:
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row, col_idx, header)
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = THIN_BORDER
    ws.freeze_panes = f"A{row + 1}"


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


def default_rule_headers() -> List[str]:
    groups = [f"group_{idx}_clocks" for idx in range(1, DEFAULT_GROUP_COLUMNS + 1)]
    return BASE_RULE_HEADERS + groups + TRAILING_RULE_HEADERS


def setup_rules_sheet(wb: Workbook) -> None:
    ws = wb.active
    ws.title = RULE_SHEET
    headers = default_rule_headers()
    style_title(
        ws,
        "03 SoC Clock Groups - clock_group_rules",
        (
            "Default policy: synchronous unless explicitly listed here. "
            "Only apply=yes and review_status=approved rows generate SDC."
        ),
        len(headers),
    )
    write_header(ws, headers)
    widths = [12, 28, 22] + [24] * DEFAULT_GROUP_COLUMNS + [28, 20, 10, 16, 18, 42, 14, 42]
    set_widths(ws, widths)
    add_validation(ws, "A5:A5000", sorted(SCENARIOS))
    add_validation(ws, "C5:C5000", sorted(RELATION_TYPES))
    analysis_col = get_column_letter(headers.index("analysis_style") + 1)
    apply_col = get_column_letter(headers.index("apply") + 1)
    review_col = get_column_letter(headers.index("review_status") + 1)
    cdc_col = get_column_letter(headers.index("cdc_required") + 1)
    add_validation(ws, f"{analysis_col}5:{analysis_col}5000", ["normal", "merged_exclusive", "per_scenario_case"])
    add_validation(ws, f"{apply_col}5:{apply_col}5000", ["yes", "no"])
    add_validation(ws, f"{review_col}5:{review_col}5000", ["draft", "reviewed", "approved", "rejected"])
    add_validation(ws, f"{cdc_col}5:{cdc_col}5000", ["yes", "no"])
    ensure_table(ws, "ClockGroupRules", f"A4:{get_column_letter(len(headers))}5")


def setup_candidates_sheet(wb: Workbook, inventory: Inventory, max_pairs: int) -> None:
    ws = wb.create_sheet(CANDIDATE_SHEET)
    style_title(
        ws,
        "03 SoC Clock Groups - clock_group_candidates",
        "Candidate rows are for review only. They never generate SDC until moved into clock_group_rules.",
        len(CANDIDATE_HEADERS),
    )
    write_header(ws, CANDIDATE_HEADERS)
    set_widths(ws, [18, 24, 24, 24, 28, 28, 28, 28, 46, 22, 16, 22, 42])
    active = sorted(inventory.active.values(), key=lambda item: item.clock_name)
    row_idx = 5
    candidate_idx = 1
    for a, b in itertools.combinations(active, 2):
        tree_a = inventory.tree_root.get(a.clock_name, a.clock_name)
        tree_b = inventory.tree_root.get(b.clock_name, b.clock_name)
        if not tree_a or not tree_b or tree_a == tree_b:
            continue
        ws.cell(row_idx, 1, f"CG_CAND_{candidate_idx:04d}")
        ws.cell(row_idx, 2, "cross_tree_pair")
        ws.cell(row_idx, 3, a.clock_name)
        ws.cell(row_idx, 4, b.clock_name)
        ws.cell(row_idx, 5, tree_a)
        ws.cell(row_idx, 6, tree_b)
        ws.cell(row_idx, 7, a.root_source)
        ws.cell(row_idx, 8, b.root_source)
        ws.cell(row_idx, 9, "genealogy tree_root differs; review CDC/STA architecture before deciding")
        ws.cell(row_idx, 10, "")
        ws.cell(row_idx, 11, "draft")
        style_body_row(ws, row_idx, len(CANDIDATE_HEADERS))
        row_idx += 1
        candidate_idx += 1
        if candidate_idx > max_pairs:
            break
    if candidate_idx > max_pairs:
        ws.cell(row_idx, 1, "INFO")
        ws.cell(row_idx, len(CANDIDATE_HEADERS), f"candidate list capped at {max_pairs} cross-tree pairs")
        style_body_row(ws, row_idx, len(CANDIDATE_HEADERS), WARNING_FILL)
        row_idx += 1
    last_row = max(row_idx - 1, 5)
    ensure_table(ws, "ClockGroupCandidates", f"A4:{get_column_letter(len(CANDIDATE_HEADERS))}{last_row}")


def create_new_workbook(form_path: Path, inventory: Inventory, max_candidate_pairs: int) -> None:
    wb = Workbook()
    setup_rules_sheet(wb)
    setup_candidates_sheet(wb, inventory, max_candidate_pairs)
    form_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(form_path)


def find_header_row(ws, required: str) -> Tuple[int, Dict[str, int]]:
    for row_idx in range(1, min(ws.max_row, 30) + 1):
        mapping: Dict[str, int] = {}
        for col_idx in range(1, ws.max_column + 1):
            value = clean_cell(ws.cell(row_idx, col_idx).value)
            if value:
                mapping[value] = col_idx
        if required in mapping:
            return row_idx, mapping
    raise RuntimeError(f"sheet {ws.title} does not contain a {required} header")


def group_headers(mapping: Dict[str, int]) -> List[str]:
    groups: List[Tuple[int, str]] = []
    for header in mapping:
        match = re.fullmatch(r"group_(\d+)_clocks", header)
        if match:
            groups.append((int(match.group(1)), header))
    return [header for _, header in sorted(groups)]


def ensure_rule_headers(ws) -> Tuple[int, Dict[str, int], bool]:
    header_row, mapping = find_header_row(ws, "group_id")
    changed = False
    if not group_headers(mapping):
        for idx in range(1, DEFAULT_GROUP_COLUMNS + 1):
            header = f"group_{idx}_clocks"
            ws.cell(header_row, ws.max_column + 1, header)
            changed = True
        header_row, mapping = find_header_row(ws, "group_id")
    for header in BASE_RULE_HEADERS + TRAILING_RULE_HEADERS:
        if header not in mapping:
            ws.cell(header_row, ws.max_column + 1, header)
            changed = True
    header_row, mapping = find_header_row(ws, "group_id")
    headers = [clean_cell(ws.cell(header_row, col_idx).value) for col_idx in range(1, ws.max_column + 1)]
    write_header(ws, headers, header_row)
    return header_row, mapping, changed


def rewrite_relation_type_cells(ws, header_row: int, mapping: Dict[str, int], report: Report) -> bool:
    relation_col = mapping.get("relation_type")
    if not relation_col:
        return False
    changed = False
    for row_idx in range(header_row + 1, ws.max_row + 1):
        original = clean_cell(ws.cell(row_idx, relation_col).value)
        if not original:
            continue
        canonical = canonical_relation_type(original)
        if canonical not in RELATION_TYPES or original == canonical:
            continue
        ws.cell(row_idx, relation_col, canonical)
        changed = True
        report.info(
            f"clock_group_rules row {row_idx}: relation_type {original} normalized to {canonical}"
        )
    return changed


def read_rule_rows(ws, header_row: int, mapping: Dict[str, int]) -> List[ParsedRule]:
    groups = group_headers(mapping)
    rows: List[ParsedRule] = []
    relevant_cols = list(mapping.values())
    for row_idx in range(header_row + 1, ws.max_row + 1):
        if not any(clean_cell(ws.cell(row_idx, col_idx).value) for col_idx in relevant_cols):
            continue
        explicit_groups: List[List[str]] = []
        used_group_headers: List[str] = []
        for header in groups:
            clocks = parse_clock_list(ws.cell(row_idx, mapping[header]).value)
            if not clocks:
                continue
            explicit_groups.append(clocks)
            used_group_headers.append(header)
        rows.append(
            ParsedRule(
                row_idx=row_idx,
                scenario=normalize_key(ws.cell(row_idx, mapping.get("scenario", 0)).value),
                group_id=clean_cell(ws.cell(row_idx, mapping.get("group_id", 0)).value),
                relation_type=canonical_relation_type(ws.cell(row_idx, mapping.get("relation_type", 0)).value),
                analysis_style=normalize_key(ws.cell(row_idx, mapping.get("analysis_style", 0)).value),
                apply=normalize_key(ws.cell(row_idx, mapping.get("apply", 0)).value),
                review_status=normalize_key(ws.cell(row_idx, mapping.get("review_status", 0)).value),
                owner=clean_cell(ws.cell(row_idx, mapping.get("owner", 0)).value),
                basis=clean_cell(ws.cell(row_idx, mapping.get("basis", 0)).value),
                cdc_required=normalize_key(ws.cell(row_idx, mapping.get("cdc_required", 0)).value),
                note=clean_cell(ws.cell(row_idx, mapping.get("note", 0)).value),
                explicit_groups=explicit_groups,
                group_headers=used_group_headers,
                excluded=set(parse_clock_list(ws.cell(row_idx, mapping.get("exclude_descendant_clocks", 0)).value)),
            )
        )
    return rows


def active_rule(rule: ParsedRule) -> bool:
    return rule.apply == "yes" and rule.review_status == "approved"


def assembled_rules(rows: Sequence[ParsedRule], scenario: str) -> List[ParsedRule]:
    result = []
    for rule in rows:
        if not active_rule(rule):
            continue
        if rule.scenario == "common" or rule.scenario == scenario:
            result.append(rule)
    return result


def output_rules(rows: Sequence[ParsedRule], scenario: str) -> List[ParsedRule]:
    return [rule for rule in rows if active_rule(rule) and rule.scenario == scenario]


def validate_and_expand_rules(
    rows: Sequence[ParsedRule],
    scenario: str,
    inventory: Inventory,
    report: Report,
) -> List[ParsedRule]:
    seen_ids: Set[str] = set()
    active_rows: List[ParsedRule] = []
    active_clock_names = set(inventory.active)

    for rule in rows:
        if rule.group_id:
            if rule.group_id in seen_ids:
                report.error(f"clock_group_rules row {rule.row_idx}: duplicate group_id {rule.group_id}")
            seen_ids.add(rule.group_id)

        if rule.scenario and rule.scenario not in SCENARIOS:
            report.error(f"clock_group_rules row {rule.row_idx}: invalid scenario {rule.scenario}")
        if rule.relation_type and rule.relation_type not in RELATION_TYPES:
            report.error(f"clock_group_rules row {rule.row_idx}: invalid relation_type {rule.relation_type}")
        if rule.analysis_style not in ANALYSIS_STYLES:
            report.error(f"clock_group_rules row {rule.row_idx}: invalid analysis_style {rule.analysis_style}")
        if rule.apply and rule.apply not in APPLY_VALUES:
            report.error(f"clock_group_rules row {rule.row_idx}: apply must be yes/no, got {rule.apply}")
        if rule.review_status and rule.review_status not in REVIEW_STATUS_VALUES:
            report.error(
                f"clock_group_rules row {rule.row_idx}: invalid review_status {rule.review_status}"
            )
        if rule.cdc_required not in YES_NO:
            report.error(f"clock_group_rules row {rule.row_idx}: cdc_required must be yes/no, got {rule.cdc_required}")

        if not active_rule(rule):
            if rule.apply == "yes" and rule.review_status != "approved":
                report.error(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: "
                    "apply=yes requires review_status=approved"
                )
            continue

        if rule.scenario not in {"common", scenario}:
            continue
        active_rows.append(rule)

        if not rule.group_id:
            report.error(f"clock_group_rules row {rule.row_idx}: active rule has empty group_id")
        if not rule.scenario:
            report.error(f"clock_group_rules row {rule.row_idx} {rule.group_id}: active rule has empty scenario")
        if not rule.relation_type:
            report.error(f"clock_group_rules row {rule.row_idx} {rule.group_id}: active rule has empty relation_type")
        if rule.scenario == "common" and not rule.basis:
            report.error(f"clock_group_rules row {rule.row_idx} {rule.group_id}: common rule basis is required")
        if len(rule.explicit_groups) < 2:
            report.error(f"clock_group_rules row {rule.row_idx} {rule.group_id}: at least two non-empty groups required")
        if rule.relation_type == "asynchronous" and rule.cdc_required != "yes":
            report.warn(
                f"clock_group_rules row {rule.row_idx} {rule.group_id}: asynchronous rule should set cdc_required=yes"
            )
        if rule.relation_type == "logically_exclusive":
            if not rule.analysis_style:
                report.error(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: "
                    "logically_exclusive requires explicit analysis_style"
                )
            basis_lower = rule.basis.lower()
            if not any(token in basis_lower for token in ["mux", "select", "mode", "merged", "exclusive"]):
                report.warn(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: logically_exclusive basis should "
                    "mention mux/select/mode evidence"
                )
            if rule.analysis_style == "per_scenario_case":
                report.error(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: "
                    "logically_exclusive with analysis_style=per_scenario_case must not apply=yes"
                )
            if rule.analysis_style == "merged_exclusive" and not basis_says_no_single_leg_case(rule.basis):
                report.warn(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: merged_exclusive basis should state "
                    "that the view does not single-leg case the mux select"
                )

        expand_rule_groups(rule, active_clock_names, inventory, report)

    report.info(f"loaded {len(rows)} clock_group_rules row(s); {len(active_rows)} active row(s) in assembled view")
    return active_rows


def basis_says_no_single_leg_case(basis: str) -> bool:
    text = basis.lower()
    if "case" not in text:
        return False
    negations = ["no", "not", "without", "none", "未", "不", "无"]
    return any(token in text for token in negations) or "not case-fixed" in text


def expand_rule_groups(
    rule: ParsedRule,
    active_clock_names: Set[str],
    inventory: Inventory,
    report: Report,
) -> None:
    rule.effective_groups = []
    rule.auto_added_by_group = []
    all_explicit: Set[str] = set()
    descendant_pool: Set[str] = set()

    for group_idx, clocks in enumerate(rule.explicit_groups, start=1):
        explicit_seen: Set[str] = set()
        for clock in clocks:
            if clock in explicit_seen:
                report.warn(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: duplicate clock {clock} "
                    f"in group_{group_idx}"
                )
            explicit_seen.add(clock)
            if clock not in active_clock_names:
                report.error(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: clock not found in active 01 "
                    f"clock inventory: {clock}"
                )
            if clock in all_explicit:
                report.error(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: clock appears in multiple groups: {clock}"
                )
            all_explicit.add(clock)

        effective: List[str] = []
        auto_added: List[str] = []
        for clock in clocks:
            if clock not in effective:
                effective.append(clock)
            for descendant in descendants_of(clock, inventory):
                descendant_pool.add(descendant)
                if descendant in rule.excluded:
                    continue
                if descendant not in effective:
                    effective.append(descendant)
                    auto_added.append(descendant)

        for excluded in rule.excluded:
            if excluded in clocks:
                report.error(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: explicit clock cannot be excluded: {excluded}"
                )
            if excluded in active_clock_names and excluded in effective:
                effective = [clock for clock in effective if clock != excluded]

        if not effective:
            report.error(
                f"clock_group_rules row {rule.row_idx} {rule.group_id}: group_{group_idx} is empty after exclusions"
            )
        if auto_added:
            report.info(
                f"clock_group_rules row {rule.row_idx} {rule.group_id}: group_{group_idx} auto-added "
                f"descendant clock(s): {', '.join(auto_added)}"
            )
            if rule.relation_type == "logically_exclusive":
                report.warn(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: logically_exclusive group_{group_idx} "
                    f"auto-added descendant clock(s) requiring mux-merge review: {', '.join(auto_added)}"
                )
        rule.effective_groups.append(effective)
        rule.auto_added_by_group.append(auto_added)

    for excluded in sorted(rule.excluded):
        if excluded not in active_clock_names:
            report.error(
                f"clock_group_rules row {rule.row_idx} {rule.group_id}: excluded clock not found in active 01 "
                f"clock inventory: {excluded}"
            )
        elif excluded not in descendant_pool:
            report.warn(
                f"clock_group_rules row {rule.row_idx} {rule.group_id}: excluded clock is not a descendant of "
                f"any explicit group clock: {excluded}"
            )
        if excluded and not (rule.basis or rule.note):
            report.error(
                f"clock_group_rules row {rule.row_idx} {rule.group_id}: exclude_descendant_clocks requires "
                "basis or note"
            )

    seen_effective: Dict[str, int] = {}
    for group_idx, group in enumerate(rule.effective_groups, start=1):
        for clock in group:
            previous_group = seen_effective.get(clock)
            if previous_group is not None and previous_group != group_idx:
                report.error(
                    f"clock_group_rules row {rule.row_idx} {rule.group_id}: effective clock {clock} "
                    f"appears in both group_{previous_group} and group_{group_idx}"
                )
            seen_effective[clock] = group_idx


def pair_key(clock_a: str, clock_b: str) -> Tuple[str, str]:
    return tuple(sorted((clock_a, clock_b)))


def build_pair_maps(
    rules: Sequence[ParsedRule],
) -> Tuple[Dict[Tuple[str, str], List[PairOccurrence]], Dict[Tuple[str, str], List[str]], Dict[str, List[str]]]:
    relation_pairs: Dict[Tuple[str, str], List[PairOccurrence]] = defaultdict(list)
    same_group_pairs: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    participation: Dict[str, List[str]] = defaultdict(list)

    for rule in rules:
        for group_idx, group in enumerate(rule.effective_groups, start=1):
            label = f"{rule.group_id}:group_{group_idx}:{rule.relation_type}:{rule.scenario}"
            for clock in group:
                participation[clock].append(label)
            for a, b in itertools.combinations(group, 2):
                same_group_pairs[pair_key(a, b)].append(label)

        for idx_a in range(len(rule.effective_groups)):
            for idx_b in range(idx_a + 1, len(rule.effective_groups)):
                group_a = rule.effective_groups[idx_a]
                group_b = rule.effective_groups[idx_b]
                occurrence = PairOccurrence(
                    relation_type=rule.relation_type,
                    group_id=rule.group_id,
                    scenario=rule.scenario,
                    group_a=f"group_{idx_a + 1}",
                    group_b=f"group_{idx_b + 1}",
                )
                for clock_a in group_a:
                    for clock_b in group_b:
                        if clock_a == clock_b:
                            continue
                        relation_pairs[pair_key(clock_a, clock_b)].append(occurrence)
    return relation_pairs, same_group_pairs, participation


def check_assembled_view(
    rules: Sequence[ParsedRule],
    relation_pairs: Dict[Tuple[str, str], List[PairOccurrence]],
    same_group_pairs: Dict[Tuple[str, str], List[str]],
    inventory: Inventory,
    report: Report,
) -> None:
    for pair, occurrences in sorted(relation_pairs.items()):
        relation_types = {occ.relation_type for occ in occurrences}
        scenarios = {occ.scenario for occ in occurrences}
        labels = [f"{occ.group_id}/{occ.relation_type}/{occ.scenario}" for occ in occurrences]
        if len(relation_types) > 1:
            report.error(
                f"assembled view conflict for pair {pair[0]} <-> {pair[1]}: "
                f"multiple relation_type values: {', '.join(labels)}"
            )
        elif len(occurrences) > 1:
            if "common" in scenarios and len(scenarios) > 1:
                report.warn(
                    f"assembled view duplicate common+scenario relation for pair {pair[0]} <-> {pair[1]}: "
                    f"{', '.join(labels)}"
                )
            else:
                report.warn(
                    f"assembled view duplicate relation for pair {pair[0]} <-> {pair[1]}: {', '.join(labels)}"
                )
        if pair in same_group_pairs:
            report.error(
                f"assembled view conflict for pair {pair[0]} <-> {pair[1]}: same effective group in "
                f"{'; '.join(same_group_pairs[pair])}, but also related by {', '.join(labels)}"
            )

    warn_non_clique_relations(relation_pairs, same_group_pairs, inventory, report)


def warn_non_clique_relations(
    relation_pairs: Dict[Tuple[str, str], List[PairOccurrence]],
    same_group_pairs: Dict[Tuple[str, str], List[str]],
    inventory: Inventory,
    report: Report,
) -> None:
    warned = 0
    for relation_type in sorted(RELATION_TYPES):
        edges = {pair for pair, occs in relation_pairs.items() if any(occ.relation_type == relation_type for occ in occs)}
        neighbors: Dict[str, Set[str]] = defaultdict(set)
        for a, b in edges:
            neighbors[a].add(b)
            neighbors[b].add(a)
        for a in sorted(neighbors):
            neigh = sorted(neighbors[a])
            for b, c in itertools.combinations(neigh, 2):
                b_c_pair = pair_key(b, c)
                if b_c_pair in same_group_pairs:
                    continue
                if same_tree(b, c, inventory):
                    continue
                if b_c_pair not in edges:
                    report.warn(
                        f"assembled view {relation_type} relation has {a}<->{b} and {a}<->{c}, "
                        f"but {b}<->{c} is uncovered; if intended pairwise, merge into one multi-group rule "
                        "or add the missing pair"
                    )
                    warned += 1
                    if warned >= MAX_NON_CLIQUE_WARNINGS:
                        report.warn(
                            f"assembled view non-clique warning limit reached ({MAX_NON_CLIQUE_WARNINGS}); "
                            "see coverage report for remaining uncovered pairs"
                        )
                        return


def same_tree(clock_a: str, clock_b: str, inventory: Inventory) -> bool:
    root_a = inventory.tree_root.get(clock_a, clock_a)
    root_b = inventory.tree_root.get(clock_b, clock_b)
    return bool(root_a and root_b and root_a == root_b)


def generate_sdc(rules: Sequence[ParsedRule], scenario: str) -> List[str]:
    lines = [
        "################################################################################",
        f"# Auto-generated SoC clock group constraints for scenario: {scenario}",
        "# Source: 03_soc_clock_groups.xlsx clock_group_rules sheet",
        "# Policy: default synchronous + explicit async/exclusive groups",
        "################################################################################",
        "",
    ]
    emitted = 0
    for rule in rules:
        if not rule.effective_groups:
            continue
        analysis_style = rule.analysis_style or "normal"
        lines.append(f"# row {rule.row_idx}: {rule.group_id} ({rule.relation_type}, {analysis_style})")
        if rule.basis:
            lines.append(f"# Basis: {rule.basis}")
        lines.append(f"set_clock_groups -{rule.relation_type} \\")
        for group_idx, group in enumerate(rule.effective_groups):
            suffix = " \\" if group_idx != len(rule.effective_groups) - 1 else ""
            lines.append(f"  -group {get_clocks(group)}{suffix}")
        lines.append("")
        emitted += 1
    if emitted == 0:
        lines.append("# No clock group commands emitted for selected scenario.")
    return lines


def write_check_report(
    path: Path,
    report: Report,
    scenario: str,
    form_path: Path,
    inventory_path: Path,
    output_path: Path,
    coverage_path: Path,
) -> None:
    lines = [
        "03_soc_clock_groups extraction report",
        "=====================================",
        "",
        f"Scenario: {scenario}",
        f"Form    : {form_path}",
        f"Input   : {inventory_path}",
        f"Output  : {output_path}",
        f"Coverage: {coverage_path}",
        f"Warnings: {report.warning_count}",
        f"Errors  : {report.error_count}",
        f"Sync changed: {'yes' if report.sync_changed else 'no'}",
        "",
        "Messages:",
    ]
    lines.extend(report.lines or ["INFO: no messages"])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_coverage_report(
    path: Path,
    inventory: Inventory,
    rules: Sequence[ParsedRule],
    relation_pairs: Dict[Tuple[str, str], List[PairOccurrence]],
    participation: Dict[str, List[str]],
) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "clock_participation"
    write_coverage_sheet_title(
        ws,
        "03 Clock Group Coverage - clock_participation",
        "Lists every active 01 clock and the clock groups it participates in.",
        8,
    )
    headers = [
        "clock_name",
        "clock_kind",
        "tree_root",
        "root_source",
        "direct_source",
        "final_action",
        "group_count",
        "groups",
    ]
    write_header(ws, headers)
    row_idx = 5
    for clock_name in sorted(inventory.active):
        info = inventory.active[clock_name]
        groups = participation.get(clock_name, [])
        ws.cell(row_idx, 1, clock_name)
        ws.cell(row_idx, 2, info.clock_kind)
        ws.cell(row_idx, 3, inventory.tree_root.get(clock_name, clock_name))
        ws.cell(row_idx, 4, info.root_source)
        ws.cell(row_idx, 5, info.direct_source)
        ws.cell(row_idx, 6, info.final_action)
        ws.cell(row_idx, 7, len(groups))
        ws.cell(row_idx, 8, "\n".join(groups))
        style_body_row(ws, row_idx, len(headers), WARNING_FILL if not groups else None)
        row_idx += 1
    set_widths(ws, [28, 24, 28, 32, 32, 18, 12, 70])
    ensure_table(ws, "ClockParticipation", f"A4:H{max(row_idx - 1, 5)}")

    write_pair_relation_sheet(wb, relation_pairs)
    write_uncovered_pairs_sheet(wb, inventory, relation_pairs)
    write_root_pair_summary_sheet(wb, inventory, relation_pairs)
    write_rule_effective_groups_sheet(wb, rules)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_coverage_sheet_title(ws, title: str, subtitle: str, width_cols: int) -> None:
    style_title(ws, title, subtitle, width_cols)


def write_pair_relation_sheet(wb: Workbook, relation_pairs: Dict[Tuple[str, str], List[PairOccurrence]]) -> None:
    ws = wb.create_sheet("pair_relation_map")
    headers = ["clock_a", "clock_b", "relation_type", "group_id", "scenario", "group_a", "group_b"]
    write_coverage_sheet_title(
        ws,
        "03 Clock Group Coverage - pair_relation_map",
        "Every clock pair covered by active set_clock_groups in the assembled view.",
        len(headers),
    )
    write_header(ws, headers)
    row_idx = 5
    for (clock_a, clock_b), occurrences in sorted(relation_pairs.items()):
        for occ in occurrences:
            values = [clock_a, clock_b, occ.relation_type, occ.group_id, occ.scenario, occ.group_a, occ.group_b]
            for col_idx, value in enumerate(values, start=1):
                ws.cell(row_idx, col_idx, value)
            style_body_row(ws, row_idx, len(headers))
            row_idx += 1
    set_widths(ws, [28, 28, 22, 30, 14, 12, 12])
    ensure_table(ws, "PairRelationMap", f"A4:G{max(row_idx - 1, 5)}")


def write_uncovered_pairs_sheet(
    wb: Workbook,
    inventory: Inventory,
    relation_pairs: Dict[Tuple[str, str], List[PairOccurrence]],
) -> None:
    ws = wb.create_sheet("uncovered_cross_root_pairs")
    headers = [
        "clock_a",
        "clock_b",
        "tree_root_a",
        "tree_root_b",
        "root_source_a",
        "root_source_b",
        "clock_kind_a",
        "clock_kind_b",
        "note",
    ]
    write_coverage_sheet_title(
        ws,
        "03 Clock Group Coverage - uncovered_cross_root_pairs",
        "Cross genealogy-tree active clock pairs not covered by active clock groups. They remain default synchronous.",
        len(headers),
    )
    write_header(ws, headers)
    row_idx = 5
    active = sorted(inventory.active.values(), key=lambda item: item.clock_name)
    for a, b in itertools.combinations(active, 2):
        tree_a = inventory.tree_root.get(a.clock_name, a.clock_name)
        tree_b = inventory.tree_root.get(b.clock_name, b.clock_name)
        if not tree_a or not tree_b or tree_a == tree_b:
            continue
        if pair_key(a.clock_name, b.clock_name) in relation_pairs:
            continue
        values = [
            a.clock_name,
            b.clock_name,
            tree_a,
            tree_b,
            a.root_source,
            b.root_source,
            a.clock_kind,
            b.clock_kind,
            "default synchronous; coverage uses genealogy tree_root and does not model set_case_analysis",
        ]
        for col_idx, value in enumerate(values, start=1):
            ws.cell(row_idx, col_idx, value)
        style_body_row(ws, row_idx, len(headers), WARNING_FILL)
        row_idx += 1
    set_widths(ws, [28, 28, 28, 28, 32, 32, 24, 24, 70])
    ensure_table(ws, "UncoveredCrossRootPairs", f"A4:I{max(row_idx - 1, 5)}")


def write_root_pair_summary_sheet(
    wb: Workbook,
    inventory: Inventory,
    relation_pairs: Dict[Tuple[str, str], List[PairOccurrence]],
) -> None:
    ws = wb.create_sheet("root_pair_summary")
    headers = [
        "tree_root_a",
        "tree_root_b",
        "covered_pairs",
        "uncovered_pairs",
        "relation_types",
        "sample_uncovered_pairs",
    ]
    write_coverage_sheet_title(
        ws,
        "03 Clock Group Coverage - root_pair_summary",
        "Aggregated view of covered/uncovered clock pairs by genealogy tree_root pair.",
        len(headers),
    )
    write_header(ws, headers)
    summary: Dict[Tuple[str, str], Dict[str, object]] = {}
    active = sorted(inventory.active.values(), key=lambda item: item.clock_name)
    for a, b in itertools.combinations(active, 2):
        tree_a = inventory.tree_root.get(a.clock_name, a.clock_name)
        tree_b = inventory.tree_root.get(b.clock_name, b.clock_name)
        if not tree_a or not tree_b or tree_a == tree_b:
            continue
        roots = pair_key(tree_a, tree_b)
        item = summary.setdefault(
            roots,
            {"covered": 0, "uncovered": 0, "relation_types": set(), "samples": []},
        )
        pair = pair_key(a.clock_name, b.clock_name)
        occurrences = relation_pairs.get(pair, [])
        if occurrences:
            item["covered"] = int(item["covered"]) + 1
            item["relation_types"].update(occ.relation_type for occ in occurrences)
        else:
            item["uncovered"] = int(item["uncovered"]) + 1
            samples = item["samples"]
            if len(samples) < 5:
                samples.append(f"{a.clock_name}<->{b.clock_name}")
    row_idx = 5
    for (root_a, root_b), item in sorted(summary.items()):
        values = [
            root_a,
            root_b,
            item["covered"],
            item["uncovered"],
            ", ".join(sorted(item["relation_types"])),
            "\n".join(item["samples"]),
        ]
        for col_idx, value in enumerate(values, start=1):
            ws.cell(row_idx, col_idx, value)
        fill = WARNING_FILL if item["uncovered"] else None
        style_body_row(ws, row_idx, len(headers), fill)
        row_idx += 1
    set_widths(ws, [32, 32, 15, 17, 28, 70])
    ensure_table(ws, "RootPairSummary", f"A4:F{max(row_idx - 1, 5)}")


def write_rule_effective_groups_sheet(wb: Workbook, rules: Sequence[ParsedRule]) -> None:
    ws = wb.create_sheet("rule_effective_groups")
    headers = [
        "scenario",
        "group_id",
        "relation_type",
        "group_index",
        "explicit_clocks",
        "auto_added_descendants",
        "excluded_descendants",
        "effective_clocks",
        "review_note",
    ]
    write_coverage_sheet_title(
        ws,
        "03 Clock Group Coverage - rule_effective_groups",
        "Shows explicit groups, domain-closure additions, exclusions, and final effective groups.",
        len(headers),
    )
    write_header(ws, headers)
    row_idx = 5
    for rule in rules:
        for group_idx, effective in enumerate(rule.effective_groups, start=1):
            explicit = rule.explicit_groups[group_idx - 1] if group_idx - 1 < len(rule.explicit_groups) else []
            auto_added = rule.auto_added_by_group[group_idx - 1] if group_idx - 1 < len(rule.auto_added_by_group) else []
            review_note = ""
            fill = None
            if rule.relation_type == "logically_exclusive" and auto_added:
                review_note = "review auto-added descendants for mux merge/shared downstream risk"
                fill = WARNING_FILL
            values = [
                rule.scenario,
                rule.group_id,
                rule.relation_type,
                group_idx,
                "\n".join(explicit),
                "\n".join(auto_added),
                "\n".join(sorted(rule.excluded)),
                "\n".join(effective),
                review_note,
            ]
            for col_idx, value in enumerate(values, start=1):
                ws.cell(row_idx, col_idx, value)
            style_body_row(ws, row_idx, len(headers), fill)
            row_idx += 1
    set_widths(ws, [12, 30, 22, 12, 40, 40, 34, 50, 55])
    ensure_table(ws, "RuleEffectiveGroups", f"A4:I{max(row_idx - 1, 5)}")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate 03 clock group SDC and coverage reports from 03_soc_clock_groups.xlsx."
    )
    parser.add_argument("-scenario", "--scenario", required=True, choices=sorted(SCENARIOS), help="timing scenario")
    parser.add_argument(
        "-input",
        "--input",
        default="../01_soc_clocks/clock_inventory.csv",
        help="01 clock inventory CSV path",
    )
    parser.add_argument(
        "--report",
        help="output check report path; default: clock_group_check_report_<scenario>.txt",
    )
    parser.add_argument(
        "--max-candidate-pairs",
        type=int,
        default=500,
        help="maximum cross-root candidate pairs written when creating a new workbook",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    scenario = args.scenario
    cwd = Path.cwd()
    form_path = cwd / "03_soc_clock_groups.xlsx"
    inventory_path = cwd / args.input
    output_path = output_sdc_path(cwd, scenario)
    report_path = cwd / (args.report or f"clock_group_check_report_{safe_filename_token(scenario)}.txt")
    coverage_path = cwd / f"clock_group_coverage_report_{safe_filename_token(scenario)}.xlsx"
    report = Report()

    try:
        inventory = read_clock_inventory(inventory_path, report)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if report.error_count:
        write_check_report(report_path, report, scenario, form_path, inventory_path, output_path, coverage_path)
        print(f"ERROR: failed to load clean 01 clock inventory. Report: {report_path}", file=sys.stderr)
        return 1

    if not form_path.is_file():
        create_new_workbook(form_path, inventory, args.max_candidate_pairs)
        report.sync_changed = True
        report.warn(f"created new workbook: {form_path}")
        report.warn("fill clock_group_rules and approve rows before generating SDC")
        write_check_report(report_path, report, scenario, form_path, inventory_path, output_path, coverage_path)
        print(f"Created new workbook: {form_path}")
        print(f"Report: {report_path}")
        print("SDC was not generated because the workbook needs review.")
        return 1

    try:
        wb = load_workbook(form_path)
        if RULE_SHEET not in wb.sheetnames:
            raise RuntimeError(f"{form_path.name} does not contain sheet {RULE_SHEET}")
        ws = wb[RULE_SHEET]
        header_row, mapping, header_changed = ensure_rule_headers(ws)
        if header_changed:
            report.sync_changed = True
            report.warn(f"{form_path.name}: added missing clock_group_rules header(s)")
            wb.save(form_path)
            write_check_report(report_path, report, scenario, form_path, inventory_path, output_path, coverage_path)
            print(f"Updated workbook: {form_path}")
            print(f"Report: {report_path}")
            print("SDC was not generated because workbook headers changed.")
            return 1

        if rewrite_relation_type_cells(ws, header_row, mapping, report):
            report.sync_changed = True
            wb.save(form_path)

        rows = read_rule_rows(ws, header_row, mapping)
        assembled = validate_and_expand_rules(rows, scenario, inventory, report)
        relation_pairs, same_group_pairs, participation = build_pair_maps(assembled)
        check_assembled_view(assembled, relation_pairs, same_group_pairs, inventory, report)
        write_coverage_report(coverage_path, inventory, assembled, relation_pairs, participation)
        report.info(f"wrote coverage report: {coverage_path}")

        if report.error_count:
            write_check_report(report_path, report, scenario, form_path, inventory_path, output_path, coverage_path)
            print(f"ERROR: validation failed. Report: {report_path}", file=sys.stderr)
            print(f"Coverage: {coverage_path}", file=sys.stderr)
            return 1

        lines = generate_sdc(output_rules(rows, scenario), scenario)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        report.info(f"wrote SDC: {output_path}")
        write_check_report(report_path, report, scenario, form_path, inventory_path, output_path, coverage_path)
    except Exception as exc:
        report.error(str(exc))
        write_check_report(report_path, report, scenario, form_path, inventory_path, output_path, coverage_path)
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"Report: {report_path}", file=sys.stderr)
        return 2

    print(f"Scenario: {scenario}")
    print(f"Form    : {form_path}")
    print(f"SDC     : {output_path}")
    print(f"Report  : {report_path}")
    print(f"Coverage: {coverage_path}")
    print(f"Warnings: {report.warning_count}")
    print(f"Errors  : {report.error_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
