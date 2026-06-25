#!/usr/bin/env python3
"""Complex regression for 02_extract_soc_clock_timing.py.

The test builds fresh inputs under work_complex/ and checks:
  * first-run workbook creation gate
  * common clock timing SDC generation
  * scenario resolved-effective generation with common fallback and scenario override
  * explicit apply=no suppression of a common fallback row
  * warnings for virtual/generated/propagated methodology risks
  * blocking negative cases: stale clock, invalid numeric value, duplicate key
"""
from __future__ import print_function

import csv
import shutil
import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook


BASE = Path(__file__).resolve().parent
SOC = BASE.parent.parent
EX02 = SOC / "02_soc_clock_timing" / "02_extract_soc_clock_timing.py"
WORK = BASE / "work_complex"

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


def clean_dir(path):
    if path.exists():
        shutil.rmtree(str(path))
    path.mkdir(parents=True)


def sh(args, cwd):
    return subprocess.run(
        [sys.executable] + [str(arg) for arg in args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def write_inventory(path, clocks):
    path.parent.mkdir(parents=True, exist_ok=True)
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
        for clock in clocks:
            row = dict((field, "") for field in fields)
            row.update(clock)
            writer.writerow(row)


def base_clocks():
    return [
        {
            "inst_name": "u_pll",
            "port_name": "ref_clk_in",
            "direction": "input",
            "clock_name": "top_sys_clk_pad",
            "clock_kind": "create_clock",
            "direct_source": "top/sys_clk_pad",
            "final_action": "emit_top_clock",
        },
        {
            "inst_name": "u_pll",
            "port_name": "core_clk_o",
            "direction": "output",
            "clock_name": "u_pll_core_clk_o",
            "clock_kind": "create_generated_clock",
            "direct_source": "u_pll/ref_clk_in",
            "final_action": "emit_output_clock",
        },
        {
            "inst_name": "u_periph",
            "port_name": "clk_o",
            "direction": "output",
            "clock_name": "u_periph_clk_o",
            "clock_kind": "generated_combinational",
            "direct_source": "u_pll_core_clk_o",
            "final_action": "emit_output_clock",
        },
        {
            "clock_name": "v_ddr_ref",
            "direction": "virtual",
            "clock_kind": "virtual_clock",
            "direct_source": "virtual/v_ddr_ref",
            "final_action": "emit_virtual_clock",
        },
    ]


def run_initial_gate(d):
    clean_dir(d)
    write_inventory(d / "clock_inventory.csv", base_clocks())
    result = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(result.returncode == 1, "first 02 run should create workbook and stop")
    require((d / "02_soc_clock_timing_budget_prects.xlsx").is_file(), "stage workbook was not created")
    report = (d / "clock_timing_check_report_common_prects_ss_125.txt").read_text(encoding="utf-8")
    require("created new stage workbook" in report, "first-run report missing workbook creation warning")


def open_budget(d, stage="prects"):
    return load_workbook(str(d / ("02_soc_clock_timing_budget_%s.xlsx" % stage)))


def header_map(ws):
    for row_idx in range(1, min(ws.max_row, 30) + 1):
        mapping = {}
        for col_idx in range(1, ws.max_column + 1):
            value = ws.cell(row_idx, col_idx).value
            if value:
                mapping[str(value).strip()] = col_idx
        if "clock_name" in mapping:
            return row_idx, mapping
    raise AssertionError("clock_budget header not found")


def last_data_row(ws, header_row, mapping):
    last = header_row
    columns = list(mapping.values())
    for row_idx in range(header_row + 1, ws.max_row + 1):
        if any(ws.cell(row_idx, col_idx).value not in (None, "") for col_idx in columns):
            last = row_idx
    return last


def set_row(ws, row_idx, mapping, values):
    for key, value in values.items():
        ws.cell(row_idx, mapping[key], value)


def append_row(ws, mapping, values):
    header_row, _ = header_map(ws)
    row_idx = last_data_row(ws, header_row, mapping) + 1
    set_row(ws, row_idx, mapping, values)
    return row_idx


def fill_positive_workbook(d):
    wb = open_budget(d)
    ws = wb["clock_budget"]
    header_row, mapping = header_map(ws)
    common_values = {
        "top_sys_clk_pad": {
            "setup_uncertainty": "0.120",
            "hold_uncertainty": 0.03,
            "source_latency_early": 0.05,
            "source_latency_late": 0.20,
            "network_latency_early": 0.20,
            "network_latency_late": 0.60,
            "transition_min": 0.03,
            "transition_max": 0.12,
            "apply": "yes",
        },
        "u_pll_core_clk_o": {
            "setup_uncertainty": 0.12,
            "hold_uncertainty": 0.04,
            "source_latency_early": 0.01,
            "source_latency_late": 0.02,
            "network_latency_early": 0.25,
            "network_latency_late": 0.70,
            "transition_min": 0.03,
            "transition_max": 0.13,
            "apply": "yes",
        },
        "u_periph_clk_o": {
            "setup_uncertainty": 0.11,
            "hold_uncertainty": 0.035,
            "network_latency_early": 0.24,
            "network_latency_late": 0.68,
            "transition_min": 0.03,
            "transition_max": 0.12,
            "apply": "yes",
        },
        "v_ddr_ref": {
            "setup_uncertainty": 0.05,
            "hold_uncertainty": 0.02,
            "network_latency_early": 0.10,
            "network_latency_late": 0.20,
            "apply": "yes",
        },
    }
    for row_idx in range(header_row + 1, ws.max_row + 1):
        clock_name = ws.cell(row_idx, mapping["clock_name"]).value
        if clock_name in common_values:
            set_row(ws, row_idx, mapping, common_values[clock_name])

    append_row(ws, mapping, {
        "scenario": "func",
        "stage": "prects",
        "corner": "ss_125",
        "clock_name": "u_pll_core_clk_o",
        "setup_uncertainty": 0.18,
        "hold_uncertainty": 0.06,
        "network_latency_early": 0.30,
        "network_latency_late": 0.80,
        "transition_min": 0.04,
        "transition_max": 0.15,
        "apply": "yes",
        "sync_status": "NEW_FROM_01",
        "note": "func override",
    })
    append_row(ws, mapping, {
        "scenario": "func",
        "stage": "prects",
        "corner": "ss_125",
        "clock_name": "v_ddr_ref",
        "apply": "no",
        "sync_status": "NEW_FROM_01",
        "note": "explicitly suppress virtual DDR ref in func",
    })
    wb.save(str(d / "02_soc_clock_timing_budget_prects.xlsx"))


def run_positive_generation():
    d = WORK / "positive"
    run_initial_gate(d)
    fill_positive_workbook(d)

    common = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(common.returncode == 0, "common 02 generation failed:\n%s\n%s" % (common.stdout, common.stderr))
    common_sdc = (d / "common" / "02_soc_clock_timing_prects_ss_125.sdc").read_text(encoding="utf-8")
    common_report = (d / "clock_timing_check_report_common_prects_ss_125.txt").read_text(encoding="utf-8")
    require("set_clock_uncertainty -setup 0.12 [get_clocks {top_sys_clk_pad}]" in common_sdc, "common setup uncertainty missing or not normalized")
    require("set_clock_transition -max 0.12 [get_clocks {top_sys_clk_pad}]" in common_sdc, "common transition missing")
    require("sync_status NEW_FROM_01 reset to OK" in common_report, "NEW_FROM_01 auto-reset message missing")
    require("clock_kind=virtual_clock" in common_report, "virtual clock warning missing")
    require("clock_kind=create_generated_clock" in common_report, "generated clock source latency warning missing")

    func = sh([EX02, "-scenario", "func", "-stage", "prects", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(func.returncode == 0, "func 02 generation failed:\n%s\n%s" % (func.stdout, func.stderr))
    func_sdc = (d / "scenarios" / "func_clock_timing_prects_ss_125.sdc").read_text(encoding="utf-8")
    require("row" in func_sdc and "func / ss_125 / u_pll_core_clk_o" in func_sdc, "func override row missing")
    require("set_clock_uncertainty -setup 0.18 [get_clocks {u_pll_core_clk_o}]" in func_sdc, "func override value missing")
    require("set_clock_uncertainty -setup 0.12 [get_clocks {u_pll_core_clk_o}]" not in func_sdc, "common value leaked into func override")
    require("[get_clocks {v_ddr_ref}]" not in func_sdc, "apply=no func row did not suppress common fallback")
    return d


def build_postcts_case(d):
    clean_dir(d)
    write_inventory(d / "clock_inventory.csv", base_clocks())
    first = sh([EX02, "-scenario", "common", "-stage", "postcts", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(first.returncode == 1, "postcts first run should create workbook")
    wb = open_budget(d, "postcts")
    ws = wb["clock_budget"]
    header_row, mapping = header_map(ws)
    for row_idx in range(header_row + 1, ws.max_row + 1):
        if not ws.cell(row_idx, mapping["clock_name"]).value:
            continue
        set_row(ws, row_idx, mapping, {
            "propagated": "yes",
            "network_latency_early": 0.10,
            "network_latency_late": 0.20,
            "apply": "yes",
            "sync_status": "OK",
        })
    wb.save(str(d / "02_soc_clock_timing_budget_postcts.xlsx"))
    result = sh([EX02, "-scenario", "common", "-stage", "postcts", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(result.returncode == 0, "postcts generation failed:\n%s\n%s" % (result.stdout, result.stderr))
    sdc = (d / "common" / "02_soc_clock_timing_postcts_ss_125.sdc").read_text(encoding="utf-8")
    report = (d / "clock_timing_check_report_common_postcts_ss_125.txt").read_text(encoding="utf-8")
    require("set_propagated_clock [get_clocks {top_sys_clk_pad}]" in sdc, "propagated clock command missing")
    require("propagated=yes means actual clock network is used" in report, "propagated mismatch warning missing")


def run_uppercase_corner_case():
    d = WORK / "uppercase_corner"
    clean_dir(d)
    write_inventory(d / "clock_inventory.csv", base_clocks())
    first = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "SS_125", "-input", "clock_inventory.csv"], d)
    require(first.returncode == 1, "uppercase corner first run should create workbook")
    wb = open_budget(d)
    ws = wb["clock_budget"]
    header_row, mapping = header_map(ws)
    for row_idx in range(header_row + 1, ws.max_row + 1):
        clock_name = ws.cell(row_idx, mapping["clock_name"]).value
        if not clock_name:
            continue
        if clock_name == "top_sys_clk_pad":
            set_row(ws, row_idx, mapping, {
                "setup_uncertainty": 0.07,
                "apply": "yes",
            })
        else:
            set_row(ws, row_idx, mapping, {
                "apply": "no",
                "note": "not used in uppercase corner smoke test",
            })
        require(ws.cell(row_idx, mapping["corner"]).value == "SS_125", "corner case was not preserved in form")
    wb.save(str(d / "02_soc_clock_timing_budget_prects.xlsx"))
    result = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "SS_125", "-input", "clock_inventory.csv"], d)
    require(result.returncode == 0, "uppercase corner generation failed:\n%s\n%s" % (result.stdout, result.stderr))
    output = d / "common" / "02_soc_clock_timing_prects_SS_125.sdc"
    require(output.is_file(), "uppercase corner output filename was not preserved")
    sdc = output.read_text(encoding="utf-8")
    require("corner: SS_125" in sdc, "uppercase corner not preserved in SDC header")
    require("set_clock_uncertainty -setup 0.07 [get_clocks {top_sys_clk_pad}]" in sdc, "uppercase corner command missing")


def run_bit_clock_name_case():
    d = WORK / "bit_clock_name"
    clean_dir(d)
    write_inventory(d / "clock_inventory.csv", [{
        "inst_name": "u_busclk",
        "port_name": "clk_o[1]",
        "direction": "output",
        "clock_name": "u_busclk_clk_o_bit1",
        "clock_kind": "create_generated_clock",
        "direct_source": "u_busclk/ref_clk_i[1]",
        "final_action": "emit_output_clock",
    }])
    first = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(first.returncode == 1, "bit clock first run should create workbook")

    wb = open_budget(d)
    ws = wb["clock_budget"]
    header_row, mapping = header_map(ws)
    matched = False
    for row_idx in range(header_row + 1, ws.max_row + 1):
        if ws.cell(row_idx, mapping["clock_name"]).value != "u_busclk_clk_o_bit1":
            continue
        matched = True
        set_row(ws, row_idx, mapping, {
            "setup_uncertainty": 0.08,
            "hold_uncertainty": 0.025,
            "transition_max": 0.11,
            "apply": "yes",
        })
    require(matched, "bit-level clock_name row was not added to workbook")
    wb.save(str(d / "02_soc_clock_timing_budget_prects.xlsx"))

    result = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(result.returncode == 0, "bit clock generation failed:\n%s\n%s" % (result.stdout, result.stderr))
    sdc = (d / "common" / "02_soc_clock_timing_prects_ss_125.sdc").read_text(encoding="utf-8")
    report = (d / "clock_timing_check_report_common_prects_ss_125.txt").read_text(encoding="utf-8")
    require("set_clock_uncertainty -setup 0.08 [get_clocks {u_busclk_clk_o_bit1}]" in sdc, "bit clock setup command missing")
    require("set_clock_transition -max 0.11 [get_clocks {u_busclk_clk_o_bit1}]" in sdc, "bit clock transition command missing")
    require("sync_status NEW_FROM_01 reset to OK" in report, "bit clock sync_status was not auto-reset")


def build_clean_workbook(d):
    run_initial_gate(d)
    fill_positive_workbook(d)


def run_stale_case():
    d = WORK / "stale"
    build_clean_workbook(d)
    wb = open_budget(d)
    ws = wb["clock_budget"]
    _, mapping = header_map(ws)
    append_row(ws, mapping, {
        "scenario": "common",
        "stage": "prects",
        "corner": "ss_125",
        "clock_name": "stale_clk",
        "setup_uncertainty": 0.1,
        "apply": "yes",
        "sync_status": "OK",
    })
    wb.save(str(d / "02_soc_clock_timing_budget_prects.xlsx"))
    result = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(result.returncode == 1, "stale case should fail")
    report = (d / "clock_timing_check_report_common_prects_ss_125.txt").read_text(encoding="utf-8")
    require("stale clock not found in 01 inventory: stale_clk" in report, "stale case report missing stale clock message")
    require("Sync changed: yes" in report, "stale case should stop at sync gate")


def run_stale_recovery_case():
    d = WORK / "stale_recovery"
    build_clean_workbook(d)
    wb = open_budget(d)
    ws = wb["clock_budget"]
    _, mapping = header_map(ws)
    append_row(ws, mapping, {
        "scenario": "common",
        "stage": "prects",
        "corner": "ss_125",
        "clock_name": "restored_clk",
        "setup_uncertainty": 0.09,
        "hold_uncertainty": 0.025,
        "apply": "yes",
        "sync_status": "OK",
    })
    wb.save(str(d / "02_soc_clock_timing_budget_prects.xlsx"))

    first = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(first.returncode == 1, "stale recovery first run should mark restored_clk stale")
    report = (d / "clock_timing_check_report_common_prects_ss_125.txt").read_text(encoding="utf-8")
    require("stale clock not found in 01 inventory: restored_clk" in report, "stale recovery did not mark restored clock stale")

    restored = base_clocks() + [{
        "inst_name": "u_restore",
        "port_name": "clk_i",
        "direction": "input",
        "clock_name": "restored_clk",
        "clock_kind": "create_clock",
        "direct_source": "top/restored_clk",
        "final_action": "emit_top_clock",
    }]
    write_inventory(d / "clock_inventory.csv", restored)
    second = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(second.returncode == 0, "stale recovery second run should auto-clear stale status:\n%s\n%s" % (second.stdout, second.stderr))
    report = (d / "clock_timing_check_report_common_prects_ss_125.txt").read_text(encoding="utf-8")
    sdc = (d / "common" / "02_soc_clock_timing_prects_ss_125.sdc").read_text(encoding="utf-8")
    require("sync_status STALE_NOT_IN_01 reset to OK" in report, "stale status was not auto-reset")
    require("set_clock_uncertainty -setup 0.09 [get_clocks {restored_clk}]" in sdc, "restored clock was not generated")


def run_invalid_numeric_case():
    d = WORK / "invalid_numeric"
    build_clean_workbook(d)
    wb = open_budget(d)
    ws = wb["clock_budget"]
    header_row, mapping = header_map(ws)
    for row_idx in range(header_row + 1, ws.max_row + 1):
        if ws.cell(row_idx, mapping["clock_name"]).value == "top_sys_clk_pad":
            ws.cell(row_idx, mapping["setup_uncertainty"], "not_a_number")
            break
    wb.save(str(d / "02_soc_clock_timing_budget_prects.xlsx"))
    result = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(result.returncode == 1, "invalid numeric case should fail")
    report = (d / "clock_timing_check_report_common_prects_ss_125.txt").read_text(encoding="utf-8")
    require("setup_uncertainty must be numeric" in report, "invalid numeric error missing")


def run_duplicate_key_case():
    d = WORK / "duplicate_key"
    build_clean_workbook(d)
    wb = open_budget(d)
    ws = wb["clock_budget"]
    _, mapping = header_map(ws)
    append_row(ws, mapping, {
        "scenario": "common",
        "stage": "prects",
        "corner": "ss_125",
        "clock_name": "top_sys_clk_pad",
        "setup_uncertainty": 0.11,
        "apply": "yes",
        "sync_status": "OK",
    })
    wb.save(str(d / "02_soc_clock_timing_budget_prects.xlsx"))
    result = sh([EX02, "-scenario", "common", "-stage", "prects", "-corner", "ss_125", "-input", "clock_inventory.csv"], d)
    require(result.returncode == 1, "duplicate key case should fail")
    report = (d / "clock_timing_check_report_common_prects_ss_125.txt").read_text(encoding="utf-8")
    require("duplicate scenario/stage/corner/clock_name key" in report, "duplicate key error missing")


def main():
    clean_dir(WORK)
    positive_dir = run_positive_generation()
    build_postcts_case(WORK / "postcts")
    run_uppercase_corner_case()
    run_bit_clock_name_case()
    run_stale_case()
    run_stale_recovery_case()
    run_invalid_numeric_case()
    run_duplicate_key_case()
    print("02 complex regression: PASS")
    print("  positive artifacts: %s" % positive_dir)
    print("  extra cases: postcts, uppercase_corner, bit_clock_name, stale, stale_recovery, invalid_numeric, duplicate_key")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
