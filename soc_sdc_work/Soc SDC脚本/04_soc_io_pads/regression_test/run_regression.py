#!/usr/bin/env python3
"""Complex regression for 04_extract_soc_io_pads.py.

The test builds fresh inputs under work_complex/ and checks:
  * bit-level get_ports parsing for names containing brackets
  * SoC pad mapping for canonical port keys such as dq_i[0]
  * pending/removed_log consumption after approved 04 generation
"""
from __future__ import print_function

import csv
import shutil
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook


BASE = Path(__file__).resolve().parent
SOC = BASE.parent.parent
EX04 = SOC / "04_soc_io_pads" / "04_extract_soc_io_pads.py"
WORK = BASE / "work_complex"


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


def write_info_all(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "info_all"
    ws.append(["inst_name", "module_name", "owner", "sdc_path"])
    ws.append(["u_io", "io_ring", "alice", "u_io.sdc"])
    wb.save(str(path))


def write_ports(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "u_io"
    ws.append([
        "Input", "Input Width", "Input Used Width", "From Whom",
        "Output", "Output Width", "Output Used Width", "To Top",
        "Inout", "Inout Width", "Inout Connectivity", "Inout Name",
    ])
    ws.append(["dq_i[0]", 1, 1, "top.pad_dq[0]", "", "", "", "", "", "", "", ""])
    ws.append(["pad_fp[0]", 1, 1, "top.pad_fp[0]", "", "", "", "", "", "", "", ""])
    ws.append(["untouched_i", 1, 1, "fabric.debug", "", "", "", "", "", "", "", ""])
    wb.save(str(path))


def write_clock_inventory(path):
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["clock_name", "direct_source", "producer_object", "final_action", "source_file"])
        writer.writerow(["dqs_clk", "", "", "emit_virtual_clock", "01"])


def write_target_clock_inventory(root, scenario, clock_names):
    path = root / "01_middle" / "assembled" / scenario / "clock_inventory.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["clock_name", "direct_source", "producer_object", "final_action", "source_file"])
        for name in clock_names:
            writer.writerow([name, "", "", "emit_virtual_clock", "01"])


def write_target_manifest(root, scenario, rows):
    path = root / "00_middle" / "scenario" / scenario / "harden_sdc_manifest.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=["scenario", "inst_name", "module_name", "sdc_path", "availability_status", "note"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_target_connections(root, include_missing):
    path = root / "00_middle" / "connection_inventory.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ["CONN_PAD_DQ", "top", "input", "pad_dq[0]", "u_io", "input", "dq_i[0]", "matched"],
        ["CONN_PAD_FP", "top", "input", "pad_fp[0]", "u_io", "input", "pad_fp[0]", "matched"],
    ]
    if include_missing:
        rows.append(["CONN_PAD_MISSING", "top", "input", "pad_missing", "u_missing", "input", "missing_i", "matched"])
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow([
            "connection_id", "src_instance", "src_direction", "src_port",
            "dst_instance", "dst_direction", "dst_port", "validation_status",
        ])
        writer.writerows(rows)


def write_missing_ports(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "u_missing"
    ws.append([
        "Input", "Input Width", "Input Used Width", "From Whom",
        "Output", "Output Width", "Output Used Width", "To Top",
        "Inout", "Inout Width", "Inout Connectivity", "Inout Name",
    ])
    ws.append(["missing_i", 1, 1, "top.pad_missing", "", "", "", "", "", "", "", ""])
    wb.save(str(path))


def build_target_inputs(root, scenario="common", clock_name="dqs_clk", include_missing=False):
    clean_dir(root)
    inputs = root / "inputs"
    inputs.mkdir(parents=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "info_all"
    ws.append(["inst_name", "module_name", "owner", "sdc_path"])
    ws.append(["u_io", "io_ring", "alice", "u_io.sdc"])
    if include_missing:
        ws.append(["u_missing", "missing_ring", "bob", "missing.sdc"])
    wb.save(str(inputs / "info_all.xlsx"))
    write_ports(inputs / "ports_u_io.xlsx")
    if include_missing:
        write_missing_ports(inputs / "ports_u_missing.xlsx")

    (inputs / "u_io.sdc").write_text(
        "set_input_delay -clock [get_clocks %s] -max 1.25 [get_ports {dq_i[0]}]\n" % clock_name
        + "set_false_path -from [get_ports {pad_fp[0]}]\n",
        encoding="utf-8",
    )
    if scenario == "common":
        write_target_clock_inventory(root, "common", [clock_name])
    else:
        write_target_clock_inventory(root, "common", ["common_clk"])
        write_target_clock_inventory(root, scenario, ["common_clk", clock_name])

    manifest_rows = [
        {
            "scenario": scenario,
            "inst_name": "u_io",
            "module_name": "io_ring",
            "sdc_path": "inputs/u_io.sdc",
            "availability_status": "available",
            "note": "delivered",
        }
    ]
    if include_missing:
        manifest_rows.append(
            {
                "scenario": scenario,
                "inst_name": "u_missing",
                "module_name": "missing_ring",
                "sdc_path": "inputs/missing.sdc",
                "availability_status": "missing",
                "note": "owner delivery pending",
            }
        )
    write_target_manifest(root, scenario, manifest_rows)
    write_target_connections(root, include_missing)

    pending = root / "00_middle" / "scenario" / scenario / "pending"
    pending.mkdir(parents=True)
    (pending / "u_io.ports").write_text("input dq_i[0]\ninput pad_fp[0]\n", encoding="utf-8")
    if include_missing:
        (pending / "u_missing.ports").write_text("input missing_i\n", encoding="utf-8")


def build_inputs(d):
    clean_dir(d)
    write_info_all(d / "info_all.xlsx")
    write_ports(d / "ports_u_io.xlsx")
    write_clock_inventory(d / "clock_inventory.csv")
    (d / "u_io.sdc").write_text(
        "set_input_delay -clock [get_clocks dqs_clk] -max 1.25 [get_ports {dq_i[0]}]\n"
        "set_false_path -from [get_ports {pad_fp[0]}]\n",
        encoding="utf-8",
    )
    pending = d / "00_harden_port_inventory" / "pending"
    pending.mkdir(parents=True)
    (pending / "u_io.ports").write_text(
        "input dq_i[0]\n"
        "input pad_fp[0]\n"
        "input untouched_i\n",
        encoding="utf-8",
    )


def header_map(ws):
    return {cell.value: cell.column for cell in ws[1] if cell.value}


def approve_bit_row(form):
    wb = load_workbook(str(form))
    ws = wb["io_constraints"]
    col = header_map(ws)
    matched_delay = False
    matched_false_path = False
    for row in range(2, ws.max_row + 1):
        pad = ws.cell(row, col["pad_name"]).value
        ctype = ws.cell(row, col["constraint_type"]).value
        if pad == "pad_dq[0]" and ctype == "input_delay":
            matched_delay = True
            ws.cell(row, col["apply"], "yes")
            ws.cell(row, col["review_status"], "approved")
            ws.cell(row, col["timing_class"], "timed")
            ws.cell(row, col["basis"], "bit-level DDR input budget")
        if pad == "pad_fp[0]" and ctype == "false_path":
            matched_false_path = True
            ws.cell(row, col["apply"], "yes")
            ws.cell(row, col["review_status"], "approved")
            ws.cell(row, col["timing_class"], "async")
            ws.cell(row, col["basis"], "bit-level false path passthrough")
    require(matched_delay, "bit-level input_delay candidate was not extracted")
    require(matched_false_path, "bit-level false_path candidate was not extracted")
    wb.save(str(form))


def run_bit_pending_case():
    d = WORK / "bit_pending"
    build_inputs(d)

    first = sh([EX04, "-scenario", "common", "-input", "clock_inventory.csv"], d)
    require(first.returncode == 1, "first 04 run should create/sync workbook and stop")
    require((d / "04_soc_io_pads.xlsx").is_file(), "04 workbook was not created")

    approve_bit_row(d / "04_soc_io_pads.xlsx")
    second = sh([EX04, "-scenario", "common", "-input", "clock_inventory.csv"], d)
    require(second.returncode == 0, "04 bit generation failed:\n%s\n%s" % (second.stdout, second.stderr))

    sdc = (d / "common" / "04_soc_io_pads.sdc").read_text(encoding="utf-8")
    report = (d / "io_pad_check_report_common_all_all.txt").read_text(encoding="utf-8")
    pending = (d / "00_harden_port_inventory" / "pending" / "u_io.ports").read_text(encoding="utf-8")
    removed = (d / "00_harden_port_inventory" / "removed_log" / "04_soc_io_pads.removed").read_text(encoding="utf-8")

    require("set_input_delay -clock [get_clocks {dqs_clk}] -max 1.25 [get_ports {pad_dq[0]}]" in sdc, "bit-level SDC command missing")
    require("set_false_path -from [get_ports {pad_fp[0]}]" in sdc, "identity-rewritten false_path was not emitted")
    require("input dq_i[0]" not in pending, "covered bit-level pad port was not removed from pending")
    require("input pad_fp[0]" not in pending, "covered bit-level false_path port was not removed from pending")
    require("input untouched_i" in pending, "uncovered pending port was incorrectly removed")
    require("u_io input dq_i[0] covered_by=04_soc_io_pads" in removed, "removed log missing bit-level pad key")
    require("u_io input pad_fp[0] covered_by=04_soc_io_pads" in removed, "removed log missing false_path bit key")
    require("removed 2 harden pad port(s) from pending" in report, "pending removal was not reported")


def run_empty_command_error_case():
    d = WORK / "empty_command"
    build_inputs(d)
    first = sh([EX04, "-scenario", "common", "-input", "clock_inventory.csv"], d)
    require(first.returncode == 1, "empty-command first 04 run should sync workbook")
    wb = load_workbook(str(d / "04_soc_io_pads.xlsx"))
    ws = wb["io_constraints"]
    col = header_map(ws)
    row = ws.max_row + 1
    values = {
        "scenario": "common",
        "stage": "all",
        "corner": "all",
        "pad_name": "pad_dq[0]",
        "soc_object": "[get_ports {pad_dq[0]}]",
        "subsys_instance": "u_io",
        "subsys_port": "dq_i[0]",
        "direction": "input",
        "timing_class": "async",
        "constraint_type": "false_path",
        "source_type": "manual",
        "apply": "yes",
        "review_status": "approved",
        "basis": "manual row intentionally lacks rewritten/original command",
    }
    for key, value in values.items():
        ws.cell(row, col[key], value)
    wb.save(str(d / "04_soc_io_pads.xlsx"))
    result = sh([EX04, "-scenario", "common", "-input", "clock_inventory.csv"], d)
    require(result.returncode == 1, "approved empty false_path row should fail")
    report = (d / "io_pad_check_report_common_all_all.txt").read_text(encoding="utf-8")
    require("approved row cannot emit an SDC command" in report, "empty command error missing")


def run_noncanonical_port_error_case():
    d = WORK / "noncanonical_port"
    build_inputs(d)
    wb = load_workbook(str(d / "ports_u_io.xlsx"))
    ws = wb["u_io"]
    ws.append(["dq_bus", 2, 2, "top.pad_dq[1:0]", "", "", "", "", "", "", "", ""])
    wb.save(str(d / "ports_u_io.xlsx"))
    result = sh([EX04, "-scenario", "common", "-input", "clock_inventory.csv"], d)
    require(result.returncode == 1, "non-canonical bus/range input should fail")
    report = (d / "io_pad_check_report_common_all_all.txt").read_text(encoding="utf-8")
    require("dq_bus has width=2 used_width=2 but is not bit-expanded" in report, "bus scalar width error missing")
    require("non-canonical top pad pad_dq[1:0]" in report, "top range canonical error missing")


def run_target_complete_case():
    root = WORK / "target_complete"
    build_target_inputs(root)
    first = sh([EX04, "--run-root", root, "-scenario", "common"], BASE)
    require(first.returncode == 1, "target first run should create/sync workbook")
    require(first.stdout.count("Author: Howard") == 1, "target stdout author marker missing or duplicated")
    form = root / "04_middle" / "04_soc_io_pads.xlsx"
    require(form.is_file(), "target 04_middle workbook missing")
    approve_bit_row(form)

    second = sh([EX04, "--run-root", root, "-scenario", "common"], BASE)
    require(second.returncode == 0, "target complete generation failed:\n%s\n%s" % (second.stdout, second.stderr))
    sdc = (root / "04_result" / "common" / "04_soc_io_pads.sdc").read_text(encoding="utf-8")
    report = (root / "04_result" / "reports" / "io_pad_check_report_common_all_all.txt").read_text(encoding="utf-8")
    removed = root / "04_middle" / "scenario" / "common" / "removed_log" / "04_soc_io_pads.removed"
    require("# Author: Howard" in sdc, "target SDC author metadata missing")
    require("# Run completeness: complete" in sdc, "target complete metadata missing")
    require("Author  : Howard" in report, "target report author metadata missing")
    require("Run completeness: complete" in report, "target report completeness missing")
    require(removed.is_file(), "target 04 removed log missing")
    require((root / "00_middle" / "scenario" / "common" / "pending" / "u_io.ports").read_text(encoding="utf-8") == "", "target covered pending ports were not consumed")


def run_target_partial_strict_case():
    root = WORK / "target_partial"
    build_target_inputs(root, include_missing=True)
    first = sh([EX04, "--run-root", root, "-scenario", "common"], BASE)
    require(first.returncode == 1, "partial target first run should sync workbook")
    form = root / "04_middle" / "04_soc_io_pads.xlsx"
    approve_bit_row(form)

    partial = sh([EX04, "--run-root", root, "-scenario", "common"], BASE)
    require(partial.returncode == 0, "partial target generation should continue for available SDC")
    sdc_path = root / "04_result" / "common" / "04_soc_io_pads.sdc"
    report_path = root / "04_result" / "reports" / "io_pad_check_report_common_all_all.txt"
    sdc = sdc_path.read_text(encoding="utf-8")
    report = report_path.read_text(encoding="utf-8")
    require("# Run completeness: partial" in sdc, "partial SDC completeness metadata missing")
    require("u_missing" in report and "HARDEN_SDC_MISSING" in report, "missing SDC evidence not reported")
    missing_pending = root / "00_middle" / "scenario" / "common" / "pending" / "u_missing.ports"
    require(missing_pending.read_text(encoding="utf-8") == "input missing_i\n", "missing SDC pending port was consumed")
    wb = load_workbook(str(form), data_only=False)
    pad_ws = wb["pad_inventory"]
    col = header_map(pad_ws)
    statuses = {
        pad_ws.cell(row, col["pad_name"]).value: pad_ws.cell(row, col["source_sdc_status"]).value
        for row in range(2, pad_ws.max_row + 1)
    }
    require(statuses.get("pad_missing") == "missing", "missing SDC pad status absent from pad inventory")

    before = sdc_path.read_text(encoding="utf-8")
    strict = sh([
        EX04, "--run-root", root, "-scenario", "common", "--require-complete-harden-sdc",
    ], BASE)
    require(strict.returncode == 1, "strict target mode must block partial harden SDC availability")
    strict_report = report_path.read_text(encoding="utf-8")
    require("HARDEN_SDC_COMPLETENESS_REQUIRED" in strict_report, "strict completeness error missing")
    require("Run completeness: partial" in strict_report, "strict report must preserve partial completeness state")
    require(sdc_path.read_text(encoding="utf-8") == before, "strict error run modified official SDC")
    require(missing_pending.read_text(encoding="utf-8") == "input missing_i\n", "strict error run modified missing pending")


def run_target_scenario_clock_case():
    root = WORK / "target_func"
    build_target_inputs(root, scenario="func", clock_name="func_io_clk")
    first = sh([EX04, "--run-root", root, "-scenario", "func"], BASE)
    require(first.returncode == 1, "scenario target first run should sync workbook")
    form = root / "04_middle" / "04_soc_io_pads.xlsx"
    approve_bit_row(form)
    second = sh([EX04, "--run-root", root, "-scenario", "func"], BASE)
    require(second.returncode == 0, "scenario assembled clock generation failed:\n%s\n%s" % (second.stdout, second.stderr))
    sdc = (root / "04_result" / "scenarios" / "func_io_pads.sdc").read_text(encoding="utf-8")
    report = (root / "04_result" / "reports" / "io_pad_check_report_func_all_all.txt").read_text(encoding="utf-8")
    require("[get_clocks {func_io_clk}]" in sdc, "scenario-only assembled clock was not accepted")
    require("01_middle/assembled/func/clock_inventory.csv" in report, "scenario assembled inventory path not reported")


def main():
    clean_dir(WORK)
    run_bit_pending_case()
    run_empty_command_error_case()
    run_noncanonical_port_error_case()
    run_target_complete_case()
    run_target_partial_strict_case()
    run_target_scenario_clock_case()
    print("04 complex regression: PASS")
    print("  legacy cases: bit_pending, empty_command, noncanonical_port")
    print("  target cases: complete, partial+strict, scenario assembled clock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
