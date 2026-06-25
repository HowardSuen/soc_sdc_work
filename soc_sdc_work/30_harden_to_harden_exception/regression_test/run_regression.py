#!/usr/bin/env python3
import csv
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook


BASE = Path(__file__).resolve().parent
SOC = BASE.parent.parent
EX30 = SOC / "30_harden_to_harden_exception" / "30_extract_harden_to_harden_exception.py"
WORK = BASE / "work_complex"

REQ = [
    "Parameter",
    "Inout",
    "Inout Width",
    "Inout Connectivity",
    "Inout Name",
    "Input",
    "Input Width",
    "Input Used Width",
    "From Whom",
    "Output",
    "Output Width",
    "Output Used Width",
    "To Top",
]


def sh(cmd, cwd):
    return subprocess.run(
        [sys.executable] + [str(part) for part in cmd],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def port_sheet(rows):
    df = pd.DataFrame(rows)
    for col in REQ:
        if col not in df.columns:
            df[col] = ""
    return df[REQ].fillna("")


def write_info_and_ports(d):
    pd.DataFrame(
        [
            {"module_name": "ha", "inst_name": "u_a", "owner": "alice"},
            {"module_name": "hft", "inst_name": "u_b", "owner": "bob"},
            {"module_name": "hc", "inst_name": "u_c", "owner": "carol"},
        ]
    ).to_excel(d / "info_all.xlsx", index=False)

    with pd.ExcelWriter(d / "ports.xlsx", engine="xlsxwriter") as writer:
        port_sheet([
            {"Output": "cfg_o", "Output Width": 2},
        ]).to_excel(writer, sheet_name="u_a", index=False)
        port_sheet([
            {"Input": "fti_0_a2c_cfg", "Input Width": 2},
            {"Output": "fto_0_a2c_cfg", "Output Width": 2},
        ]).to_excel(writer, sheet_name="u_b", index=False)
        port_sheet([
            {"Input": "cfg_i", "Input Width": 2},
        ]).to_excel(writer, sheet_name="u_c", index=False)


def write_sdcs(d):
    (d / "ha.sdc").write_text(
        "set_false_path -from [get_ports cfg_o]\n",
        encoding="utf-8",
    )
    (d / "hft.sdc").write_text("", encoding="utf-8")
    (d / "hc.sdc").write_text("", encoding="utf-8")


def write_connection_inventory(d):
    root = d / "00_harden_port_inventory"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "connection_inventory.csv"
    headers = [
        "connection_id",
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
        "validation_status",
        "note",
    ]
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=headers)
        writer.writeheader()

        def add(cid, src_i, src_d, src_p, dst_i, dst_d, dst_p):
            src_bit = src_p.split("[")[-1].rstrip("]") if "[" in src_p else ""
            dst_bit = dst_p.split("[")[-1].rstrip("]") if "[" in dst_p else ""
            writer.writerow(
                {
                    "connection_id": cid,
                    "connection_type": "harden_to_harden",
                    "src_instance": src_i,
                    "src_direction": src_d,
                    "src_port": src_p,
                    "src_bit_index": src_bit,
                    "src_endpoint_key": "%s:%s:%s" % (src_i, src_d, src_p),
                    "src_soc_object": "%s/%s" % (src_i, src_p),
                    "dst_instance": dst_i,
                    "dst_direction": dst_d,
                    "dst_port": dst_p,
                    "dst_bit_index": dst_bit,
                    "dst_endpoint_key": "%s:%s:%s" % (dst_i, dst_d, dst_p),
                    "dst_soc_object": "%s/%s" % (dst_i, dst_p),
                    "validation_status": "matched",
                    "note": "",
                }
            )

        add("CONN_direct_bit0", "u_a", "output", "cfg_o[0]", "u_c", "input", "cfg_i[0]")
        add("CONN_to_ft_bit1", "u_a", "output", "cfg_o[1]", "u_b", "input", "fti_0_a2c_cfg[1]")
        add("CONN_from_ft_bit1", "u_b", "output", "fto_0_a2c_cfg[1]", "u_c", "input", "cfg_i[1]")


def write_feedthrough_inventory(d):
    with (d / "feedthrough_inventory.csv").open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=[
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
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "feedthrough_id": "FT_u_b_0_a2c_cfg_bit1",
                "scenario": "common",
                "feedthrough_instance": "u_b",
                "feedthrough_module": "hft",
                "hop_index": "0",
                "base": "a2c_cfg",
                "src_name": "a",
                "dst_name": "c",
                "signal_name": "cfg",
                "fti_port": "fti_0_a2c_cfg[1]",
                "fto_port": "fto_0_a2c_cfg[1]",
                "fti_endpoint": "[get_pins {u_b/fti_0_a2c_cfg[1]}]",
                "fto_endpoint": "[get_pins {u_b/fto_0_a2c_cfg[1]}]",
                "bit_index": "1",
                "chain_id": "CHAIN_a2c_cfg",
                "hop_order": "0",
                "upstream_endpoint": "[get_pins {u_a/cfg_o[1]}]",
                "downstream_endpoint": "[get_pins {u_c/cfg_i[1]}]",
                "validation_status": "matched",
                "basis": "regression feedthrough naming",
                "note": "",
            }
        )


def write_pending(d):
    pending = d / "00_harden_port_inventory" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "u_a.ports").write_text("output cfg_o[0]\noutput cfg_o[1]\n", encoding="utf-8")
    (pending / "u_b.ports").write_text(
        "input fti_0_a2c_cfg[1]\noutput fto_0_a2c_cfg[1]\n",
        encoding="utf-8",
    )
    (pending / "u_c.ports").write_text("input cfg_i[0]\ninput cfg_i[1]\n", encoding="utf-8")


def build_inputs(d):
    if d.exists():
        shutil.rmtree(str(d))
    d.mkdir(parents=True)
    write_info_and_ports(d)
    write_sdcs(d)
    write_connection_inventory(d)
    write_feedthrough_inventory(d)
    write_pending(d)


def channel_id_for_ports(src, dst):
    def tok(port):
        return port.replace("[", "_bit").replace("]", "")
    return "CH_%s__%s" % (
        ("u_a_%s" % tok(src)).replace("/", "_"),
        ("u_c_%s" % tok(dst)).replace("/", "_"),
    )


def approve_clean_rules(d):
    wb = load_workbook(str(d / "30_harden_to_harden_exception.xlsx"))
    ws = wb["exception_rule"]
    headers = {cell.value: idx for idx, cell in enumerate(ws[1], start=1)}

    def setv(row, header, value):
        ws.cell(row=row, column=headers[header], value=value)

    for row in range(2, ws.max_row + 1):
        channel_id = ws.cell(row=row, column=headers["channel_id"]).value or ""
        if "cfg_o_bit0" in channel_id and "cfg_i_bit0" in channel_id:
            setv(row, "scenario", "func")
            setv(row, "stage", "all")
            setv(row, "corner", "all")
            setv(row, "apply", "yes")
            setv(row, "review_status", "approved")
            setv(row, "owner", "alice")
            setv(row, "exception_type", "false_path")
            setv(row, "path_category", "static")
            setv(row, "source_type", "manual_entry")
            setv(row, "harden_clock_context_status", "not_applicable")
            setv(row, "basis", "func scenario static config is stable after boot")
        if "cfg_o_bit1" in channel_id and "cfg_i_bit1" in channel_id:
            setv(row, "scenario", "common")
            setv(row, "stage", "prects")
            setv(row, "corner", "ss_125")
            setv(row, "apply", "yes")
            setv(row, "review_status", "approved")
            setv(row, "owner", "alice")
            setv(row, "exception_type", "max_min_delay_override")
            setv(row, "path_category", "handshake")
            setv(row, "clock_relation", "asynchronous")
            setv(row, "datapath_only", "yes")
            setv(row, "max_value", "12.0")
            setv(row, "min_value", "1.0")
            setv(row, "source_type", "manual_entry")
            setv(row, "harden_clock_context_status", "not_applicable")
            setv(row, "basis", "cdc handshake skew window, tool report confirms path max/min not shadowed")
            setv(row, "cdc_rdc_ref", "CDC-123")
            setv(row, "protocol_ref", "HANDSHAKE-IF")
    wb.save(str(d / "30_harden_to_harden_exception.xlsx"))


def write_active20_workbook(d):
    wb = Workbook()
    ws = wb.active
    ws.title = "interface_budget"
    headers = [
        "channel_id",
        "scenario",
        "stage",
        "corner",
        "apply",
        "review_status",
        "budget_model",
        "emit_max",
        "emit_min",
        "converted_max",
        "converted_min",
    ]
    ws.append(headers)
    ws.append([
        "CH_u_a_cfg_o_bit0__u_c_cfg_i_bit0",
        "common",
        "all",
        "all",
        "yes",
        "approved",
        "interconnect_budget",
        "yes",
        "no",
        "1.0",
        "",
    ])
    wb.save(str(d / "20_harden_x_if.xlsx"))


def approve_conflicting_false_path(d):
    wb = load_workbook(str(d / "30_harden_to_harden_exception.xlsx"))
    ws = wb["exception_rule"]
    headers = {cell.value: idx for idx, cell in enumerate(ws[1], start=1)}
    for row in range(2, ws.max_row + 1):
        channel_id = ws.cell(row=row, column=headers["channel_id"]).value or ""
        if "cfg_o_bit0" in channel_id and "cfg_i_bit0" in channel_id:
            for header, value in {
                "scenario": "common",
                "stage": "all",
                "corner": "all",
                "apply": "yes",
                "review_status": "approved",
                "owner": "alice",
                "exception_type": "false_path",
                "path_category": "static",
                "source_type": "manual_entry",
                "harden_clock_context_status": "not_applicable",
                "basis": "intentional conflict test",
            }.items():
                ws.cell(row=row, column=headers[header], value=value)
            break
    wb.save(str(d / "30_harden_to_harden_exception.xlsx"))


def approve_feedthrough_without_id(d):
    wb = load_workbook(str(d / "30_harden_to_harden_exception.xlsx"))
    ws = wb["exception_rule"]
    headers = {cell.value: idx for idx, cell in enumerate(ws[1], start=1)}
    for row in range(2, ws.max_row + 1):
        channel_id = ws.cell(row=row, column=headers["channel_id"]).value or ""
        if "cfg_o_bit1" in channel_id and "cfg_i_bit1" in channel_id:
            for header, value in {
                "scenario": "common",
                "stage": "prects",
                "corner": "ss_125",
                "apply": "yes",
                "review_status": "approved",
                "owner": "alice",
                "exception_type": "max_min_delay_override",
                "path_category": "handshake",
                "clock_relation": "asynchronous",
                "datapath_only": "yes",
                "max_value": "12.0",
                "min_value": "1.0",
                "source_type": "manual_entry",
                "harden_clock_context_status": "not_applicable",
                "basis": "cdc handshake skew window",
                "related_10_feedthrough_id": "",
            }.items():
                ws.cell(row=row, column=headers[header], value=value)
            break
    wb.save(str(d / "30_harden_to_harden_exception.xlsx"))


def approve_reset_with_chinese_basis(d):
    wb = load_workbook(str(d / "30_harden_to_harden_exception.xlsx"))
    ws = wb["exception_rule"]
    headers = {cell.value: idx for idx, cell in enumerate(ws[1], start=1)}
    for row in range(2, ws.max_row + 1):
        channel_id = ws.cell(row=row, column=headers["channel_id"]).value or ""
        if "cfg_o_bit0" in channel_id and "cfg_i_bit0" in channel_id:
            for header, value in {
                "scenario": "func",
                "stage": "all",
                "corner": "all",
                "apply": "yes",
                "review_status": "approved",
                "owner": "alice",
                "exception_type": "false_path",
                "path_category": "reset",
                "source_type": "manual_entry",
                "harden_clock_context_status": "not_applicable",
                "basis": "复位同步器保证恢复/移除检查由RDC签核覆盖",
                "cdc_rdc_ref": "RDC-RESET-001",
            }.items():
                ws.cell(row=row, column=headers[header], value=value)
            break
    wb.save(str(d / "30_harden_to_harden_exception.xlsx"))


def test_clean_generation():
    d = WORK / "clean"
    build_inputs(d)
    first = sh([EX30], d)
    require(first.returncode == 1, "first 30 run should stop for workbook review")
    approve_clean_rules(d)

    func = sh([EX30, "-scenario", "func"], d)
    require(func.returncode == 0, "func 30 generation failed:\n%s\n%s" % (func.stdout, func.stderr))
    sdc = (d / "scenarios" / "func_exceptions.sdc").read_text(encoding="utf-8")
    require("set_false_path -from [get_pins {u_a/cfg_o[0]}] -to [get_pins {u_c/cfg_i[0]}]" in sdc, "direct false_path missing")

    view = sh([EX30, "-stage", "prects", "-corner", "ss_125"], d)
    require(view.returncode == 0, "view-specific 30 generation failed:\n%s\n%s" % (view.stdout, view.stderr))
    view_sdc = (d / "common" / "30_harden_to_harden_exception_prects_ss_125.sdc").read_text(encoding="utf-8")
    require("set_max_delay 12 -datapath_only -from [get_pins {u_a/cfg_o[1]}]" in view_sdc, "feedthrough max delay missing")
    require("-through [get_pins {u_b/fti_0_a2c_cfg[1]}] -through [get_pins {u_b/fto_0_a2c_cfg[1]}]" in view_sdc, "feedthrough through anchors missing")
    require("set_min_delay 1 -datapath_only" in view_sdc, "feedthrough min delay missing")

    pending_a = (d / "00_harden_port_inventory" / "pending" / "u_a.ports").read_text(encoding="utf-8")
    pending_b = (d / "00_harden_port_inventory" / "pending" / "u_b.ports").read_text(encoding="utf-8")
    pending_c = (d / "00_harden_port_inventory" / "pending" / "u_c.ports").read_text(encoding="utf-8")
    require("cfg_o[0]" not in pending_a and "cfg_o[1]" not in pending_a, "u_a pending not consumed by 30")
    require("cfg_i[0]" not in pending_c and "cfg_i[1]" not in pending_c, "u_c pending not consumed by 30")
    require("fti_0_a2c_cfg[1]" in pending_b and "fto_0_a2c_cfg[1]" in pending_b, "30 must not consume intermediate feedthrough ports")

    rerun = sh([EX30, "-stage", "prects", "-corner", "ss_125"], d)
    require(rerun.returncode == 0, "30 pending update should be idempotent:\n%s\n%s" % (rerun.stdout, rerun.stderr))
    report = (d / "harden_to_harden_exception_check_report_common_prects_ss_125.txt").read_text(encoding="utf-8")
    require("no previous_removed record exists" not in report, "30 pending update is not idempotent")


def test_active20_conflict():
    d = WORK / "active20_conflict"
    build_inputs(d)
    first = sh([EX30], d)
    require(first.returncode == 1, "first sync should request review")
    write_active20_workbook(d)
    approve_conflicting_false_path(d)
    result = sh([EX30, "--no-update-pending"], d)
    require(result.returncode == 1, "30 should reject active 20 max + false_path overlap")
    report = (d / "harden_to_harden_exception_check_report_common_all_all.txt").read_text(encoding="utf-8")
    require("active 20 max budget overlaps" in report, "active 20 overlap error missing")


def test_feedthrough_id_required():
    d = WORK / "missing_ft_id"
    build_inputs(d)
    first = sh([EX30], d)
    require(first.returncode == 1, "first sync should request review")
    approve_feedthrough_without_id(d)
    result = sh([EX30, "-stage", "prects", "-corner", "ss_125", "--no-update-pending"], d)
    require(result.returncode == 1, "30 should reject feedthrough path without related_10_feedthrough_id")
    report = (d / "harden_to_harden_exception_check_report_common_prects_ss_125.txt").read_text(encoding="utf-8")
    require("path passes feedthrough but related_10_feedthrough_id is blank" in report, "missing feedthrough id error absent")


def test_reset_chinese_basis():
    d = WORK / "reset_chinese_basis"
    build_inputs(d)
    first = sh([EX30], d)
    require(first.returncode == 1, "first sync should request review")
    approve_reset_with_chinese_basis(d)
    result = sh([EX30, "-scenario", "func", "--no-update-pending"], d)
    require(result.returncode == 0, "30 should accept Chinese reset/RDC basis:\n%s\n%s" % (result.stdout, result.stderr))
    report = (d / "harden_to_harden_exception_check_report_func_all_all.txt").read_text(encoding="utf-8")
    require("reset false_path requires recovery/removal" not in report, "Chinese reset basis was not accepted")


def main():
    if WORK.exists():
        shutil.rmtree(str(WORK))
    test_clean_generation()
    test_active20_conflict()
    test_feedthrough_id_required()
    test_reset_chinese_basis()
    print("30_harden_to_harden_exception regression: PASS")


if __name__ == "__main__":
    main()
