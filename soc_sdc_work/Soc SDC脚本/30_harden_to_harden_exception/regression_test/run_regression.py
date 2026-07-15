#!/usr/bin/env python3
"""Regression for the target-runtime 30 harden exception flow."""

import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook


BASE = Path(__file__).resolve().parent
SOC = BASE.parent.parent
EX30 = SOC / "30_harden_to_harden_exception" / "30_extract_harden_to_harden_exception.py"
WORK = BASE / "work_target"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sh(args, root):
    args = list(args)
    if "--scenario" not in args and "-scenario" not in args:
        args = ["--scenario", "common"] + args
    return subprocess.run(
        [sys.executable, str(EX30), "--run-root", str(root)] + args,
        cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def write_csv(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def write_inputs(root, missing_c=False):
    if root.exists():
        shutil.rmtree(str(root))
    (root / "inputs" / "sdc").mkdir(parents=True)
    pd.DataFrame([
        {"module_name": "ha", "inst_name": "u_a", "owner": "alice"},
        {"module_name": "hft", "inst_name": "u_ft", "owner": "frank"},
        {"module_name": "hc", "inst_name": "u_c", "owner": "carol"},
    ]).to_excel(root / "inputs" / "info_all.xlsx", index=False)
    with pd.ExcelWriter(root / "inputs" / "ports.xlsx", engine="xlsxwriter") as writer:
        pd.DataFrame({"Output": ["cfg_o"], "Output Width": [2]}).to_excel(writer, sheet_name="u_a", index=False)
        pd.DataFrame({"Input": ["fti_0_cfg"], "Input Width": [1], "Output": ["fto_0_cfg"], "Output Width": [1]}).to_excel(writer, sheet_name="u_ft", index=False)
        pd.DataFrame({"Input": ["cfg_i"], "Input Width": [2]}).to_excel(writer, sheet_name="u_c", index=False)
    (root / "inputs" / "sdc" / "u_a.sdc").write_text("# no ordinary port timing\n", encoding="utf-8")
    (root / "inputs" / "sdc" / "u_ft.sdc").write_text("# feedthrough owner SDC\n", encoding="utf-8")
    if not missing_c:
        (root / "inputs" / "sdc" / "u_c.sdc").write_text("# no ordinary port timing\n", encoding="utf-8")

    edges = [
        {"connection_id": "CONN_DIRECT_B0", "connection_type": "harden_to_harden", "scenario_scope": "common", "src_instance": "u_a", "src_direction": "output", "src_port": "cfg_o[0]", "src_bit_index": "0", "src_endpoint_key": "u_a:output:cfg_o[0]", "src_soc_object": "u_a/cfg_o[0]", "dst_instance": "u_c", "dst_direction": "input", "dst_port": "cfg_i[0]", "dst_bit_index": "0", "dst_endpoint_key": "u_c:input:cfg_i[0]", "dst_soc_object": "u_c/cfg_i[0]", "validation_status": "matched", "note": ""},
        {"connection_id": "CONN_FT_IN_B1", "connection_type": "feedthrough", "scenario_scope": "common", "src_instance": "u_a", "src_direction": "output", "src_port": "cfg_o[1]", "src_bit_index": "1", "src_endpoint_key": "u_a:output:cfg_o[1]", "src_soc_object": "u_a/cfg_o[1]", "dst_instance": "u_ft", "dst_direction": "input", "dst_port": "fti_0_cfg[1]", "dst_bit_index": "1", "dst_endpoint_key": "u_ft:input:fti_0_cfg[1]", "dst_soc_object": "u_ft/fti_0_cfg[1]", "validation_status": "matched", "note": ""},
        {"connection_id": "CONN_FT_OUT_B1", "connection_type": "feedthrough", "scenario_scope": "common", "src_instance": "u_ft", "src_direction": "output", "src_port": "fto_0_cfg[1]", "src_bit_index": "1", "src_endpoint_key": "u_ft:output:fto_0_cfg[1]", "src_soc_object": "u_ft/fto_0_cfg[1]", "dst_instance": "u_c", "dst_direction": "input", "dst_port": "cfg_i[1]", "dst_bit_index": "1", "dst_endpoint_key": "u_c:input:cfg_i[1]", "dst_soc_object": "u_c/cfg_i[1]", "validation_status": "matched", "note": ""},
        {"connection_id": "CONN_FOREIGN_SCAN", "connection_type": "harden_to_harden", "scenario_scope": "scan", "src_instance": "u_a", "src_direction": "output", "src_port": "cfg_o[0]", "src_bit_index": "0", "src_endpoint_key": "u_a:output:cfg_o[0]", "src_soc_object": "u_a/cfg_o[0]", "dst_instance": "u_c", "dst_direction": "input", "dst_port": "cfg_i[1]", "dst_bit_index": "1", "dst_endpoint_key": "u_c:input:cfg_i[1]", "dst_soc_object": "u_c/cfg_i[1]", "validation_status": "matched", "note": "foreign scenario edge"},
    ]
    connection_path = root / "00_middle" / "connection_inventory.csv"
    write_csv(connection_path, list(edges[0]), edges)
    connection_digest = hashlib.sha256(connection_path.read_bytes()).hexdigest()
    manifest = []
    for inst, module in (("u_a", "ha"), ("u_ft", "hft"), ("u_c", "hc")):
        missing = inst == "u_c" and missing_c
        manifest.append({"scenario": "common", "inst_name": inst, "module_name": module,
                         "sdc_path": "" if missing else "inputs/sdc/%s.sdc" % inst,
                         "availability_status": "missing" if missing else "available", "note": "not delivered" if missing else ""})
    write_csv(root / "00_middle" / "scenario" / "common" / "harden_sdc_manifest.csv", list(manifest[0]), manifest)

    for inst, lines in {
        "u_a": ["output cfg_o[0]", "output cfg_o[1]"],
        "u_ft": ["input fti_0_cfg[1]", "output fto_0_cfg[1]"],
        "u_c": ["input cfg_i[0]", "input cfg_i[1]"],
    }.items():
        path = root / "00_middle" / "scenario" / "common" / "pending" / (inst + ".ports")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    clock_headers = ["clock_name", "original_clock_name", "inst_name", "final_action"]
    write_csv(root / "01_middle" / "assembled" / "common" / "clock_inventory.csv", clock_headers, [])
    run_completeness = "partial" if missing_c else "complete"
    (root / "01_middle" / "assembled" / "common" / "clock_inventory.meta").write_text(json.dumps({"scenario": "common", "run_completeness": run_completeness, "clock_universe_digest": "clock-digest"}), encoding="utf-8")
    relation_headers = ["schema_version", "scenario", "clock_a", "clock_b", "relation_type", "relation_source", "source_rule_ids", "clock_universe_digest", "assembled_view_digest"]
    write_csv(root / "03_middle" / "relation_map" / "common.csv", relation_headers, [])
    (root / "03_middle" / "relation_map" / "common.meta").write_text(json.dumps({"scenario": "common", "run_completeness": run_completeness, "clock_universe_digest": "clock-digest", "assembled_view_digest": "view-digest"}), encoding="utf-8")

    edge_headers = ["feedthrough_edge_id", "connection_id", "scenario", "run_completeness", "stage", "corner", "src_instance", "src_direction", "src_port", "src_bit_index", "src_endpoint_key", "src_soc_object", "dst_instance", "dst_direction", "dst_port", "dst_bit_index", "dst_endpoint_key", "dst_soc_object", "channel_disposition", "emit_max", "emit_min", "review_status", "apply", "validation_status"]
    edge_rows = [
        {"feedthrough_edge_id": "FTE_CONN_FT_IN_B1", "connection_id": "CONN_FT_IN_B1", "scenario": "common", "run_completeness": run_completeness, "stage": "all", "corner": "all", "src_instance": "u_a", "src_direction": "output", "src_port": "cfg_o[1]", "src_bit_index": "1", "src_endpoint_key": "u_a:output:cfg_o[1]", "src_soc_object": "[get_pins {u_a/cfg_o[1]}]", "dst_instance": "u_ft", "dst_direction": "input", "dst_port": "fti_0_cfg[1]", "dst_bit_index": "1", "dst_endpoint_key": "u_ft:input:fti_0_cfg[1]", "dst_soc_object": "[get_pins {u_ft/fti_0_cfg[1]}]", "channel_disposition": "route_to_30", "emit_max": "no", "emit_min": "no", "review_status": "approved", "apply": "yes", "validation_status": "matched"},
        {"feedthrough_edge_id": "FTE_CONN_FT_OUT_B1", "connection_id": "CONN_FT_OUT_B1", "scenario": "common", "run_completeness": run_completeness, "stage": "all", "corner": "all", "src_instance": "u_ft", "src_direction": "output", "src_port": "fto_0_cfg[1]", "src_bit_index": "1", "src_endpoint_key": "u_ft:output:fto_0_cfg[1]", "src_soc_object": "[get_pins {u_ft/fto_0_cfg[1]}]", "dst_instance": "u_c", "dst_direction": "input", "dst_port": "cfg_i[1]", "dst_bit_index": "1", "dst_endpoint_key": "u_c:input:cfg_i[1]", "dst_soc_object": "[get_pins {u_c/cfg_i[1]}]", "channel_disposition": "no_soc_budget_required", "emit_max": "no", "emit_min": "no", "review_status": "approved", "apply": "yes", "validation_status": "matched"},
    ]
    write_csv(root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv", edge_headers, edge_rows)
    twenty_headers = ["schema_version", "scenario", "stage", "corner", "connection_inventory_digest", "connection_id", "channel_id", "src_endpoint", "dst_endpoint", "owner_stage", "channel_disposition", "apply", "review_status", "emit_max", "emit_min", "converted_max", "converted_min", "budget_type", "mode", "run_completeness"]
    twenty_rows = [{
        "schema_version": "1", "scenario": "common", "stage": "all", "corner": "all",
        "connection_inventory_digest": connection_digest, "connection_id": "CONN_DIRECT_B0",
        "channel_id": "CH_u_a_cfg_o_bit0__u_c_cfg_i_bit0",
        "src_endpoint": "[get_pins {u_a/cfg_o[0]}]", "dst_endpoint": "[get_pins {u_c/cfg_i[0]}]",
        "owner_stage": "20", "channel_disposition": "route_to_30", "apply": "yes",
        "review_status": "approved", "emit_max": "no", "emit_min": "no",
        "converted_max": "", "converted_min": "", "budget_type": "exception",
        "mode": "audit_only", "run_completeness": "partial" if missing_c else "complete",
    }]
    write_csv(root / "20_middle" / "scenario" / "common" / "channel_inventory.csv", twenty_headers, twenty_rows)


def workbook_columns(ws):
    return {cell.value: cell.column for cell in ws[1]}


def setv(ws, columns, row, name, value):
    ws.cell(row=row, column=columns[name], value=value)


def approve_rules(root, partial=False):
    path = root / "30_middle" / "30_harden_to_harden_exception.xlsx"
    wb = load_workbook(str(path))
    ws = wb["exception_rule"]
    columns = workbook_columns(ws)
    found = set()
    for row in range(2, ws.max_row + 1):
        channel = ws.cell(row=row, column=columns["channel_id"]).value
        if channel == "CH_u_a_cfg_o_bit0__u_c_cfg_i_bit0":
            found.add("direct")
            setv(ws, columns, row, "scenario", "common")
            setv(ws, columns, row, "apply", "yes")
            setv(ws, columns, row, "review_status", "approved")
            setv(ws, columns, row, "owner", "alice")
            setv(ws, columns, row, "exception_type", "false_path")
            setv(ws, columns, row, "path_category", "config")
            setv(ws, columns, row, "source_type", "manual_entry")
            setv(ws, columns, row, "basis", "architecture confirms this static configuration path is not timed")
            if partial:
                setv(ws, columns, row, "sdc_independent_basis", "architecture review is independent of the missing destination SDC")
        elif channel == "CH_u_a_cfg_o_bit1__u_ft_fti_0_cfg_bit1":
            found.add("feedthrough")
            setv(ws, columns, row, "scenario", "common")
            setv(ws, columns, row, "stage", "prects")
            setv(ws, columns, row, "corner", "ss_125")
            setv(ws, columns, row, "apply", "yes")
            setv(ws, columns, row, "review_status", "approved")
            setv(ws, columns, row, "owner", "frank")
            setv(ws, columns, row, "exception_type", "max_min_delay_override")
            setv(ws, columns, row, "path_category", "control")
            setv(ws, columns, row, "source_type", "manual_entry")
            setv(ws, columns, row, "max_value", "12")
            setv(ws, columns, row, "min_value", "1")
            setv(ws, columns, row, "basis", "approved protocol propagation window for this direct ingress edge")
    wb.save(str(path))
    require(found == {"direct", "feedthrough"}, "expected direct and feedthrough rules were not seeded")


def test_target_generation():
    root = WORK / "target"
    write_inputs(root)
    first = sh([], root)
    require(first.returncode == 1, "first target run must stop after workbook sync")
    require("Author: Howard" in first.stdout and "Scenario: common" in first.stdout and "Port accounting: enabled" in first.stdout, "stdout run metadata missing")
    require((root / "30_middle" / "exception_candidates.csv").is_file(), "candidate CSV missing")
    candidate_text = (root / "30_middle" / "exception_candidates.csv").read_text(encoding="utf-8")
    require("Howard" in candidate_text and "enabled" in candidate_text, "candidate CSV run metadata missing")
    require("CONN_FOREIGN_SCAN" not in candidate_text and "CH_u_a_cfg_o_bit0__u_c_cfg_i_bit1" not in candidate_text, "foreign scenario edge leaked into common candidates")
    metadata_wb = load_workbook(str(root / "30_middle" / "30_harden_to_harden_exception.xlsx"), data_only=True)
    metadata_ws = metadata_wb["run_metadata"]
    metadata = {metadata_ws.cell(row=row, column=1).value: metadata_ws.cell(row=row, column=2).value for row in range(2, metadata_ws.max_row + 1)}
    require(metadata.get("Author") == "Howard" and metadata.get("Scenario") == "common", "workbook run metadata missing")
    approve_rules(root)

    common = sh([], root)
    require(common.returncode == 0, "common generation failed:\n%s\n%s" % (common.stdout, common.stderr))
    common_sdc = (root / "30_result" / "common" / "30_harden_to_harden_exception.sdc").read_text(encoding="utf-8")
    require("set_false_path -from [get_pins {u_a/cfg_o[0]}] -to [get_pins {u_c/cfg_i[0]}]" in common_sdc, "direct false path missing")
    require("Author: Howard" in common_sdc and "Run completeness: complete" in common_sdc, "target SDC metadata missing")

    prects = sh(["--stage", "prects", "--corner", "ss_125"], root)
    require(prects.returncode == 0, "view-specific generation failed:\n%s\n%s" % (prects.stdout, prects.stderr))
    view_sdc = (root / "30_result" / "common" / "30_harden_to_harden_exception_prects_ss_125.sdc").read_text(encoding="utf-8")
    require("set_max_delay 12 -from [get_pins {u_a/cfg_o[1]}] -to [get_pins {u_ft/fti_0_cfg[1]}]" in view_sdc, "direct feedthrough max override missing")
    require("set_min_delay 1 -from [get_pins {u_a/cfg_o[1]}] -to [get_pins {u_ft/fti_0_cfg[1]}]" in view_sdc, "direct feedthrough min override missing")
    require("-through" not in view_sdc and "fto_0_cfg" not in view_sdc, "30 stitched an internal feedthrough path")

    pending = root / "00_middle" / "scenario" / "common" / "pending"
    require("cfg_o[0]" not in (pending / "u_a.ports").read_text(encoding="utf-8"), "direct source pending endpoint not removed")
    require("cfg_o[1]" not in (pending / "u_a.ports").read_text(encoding="utf-8"), "feedthrough ingress source pending endpoint not removed")
    require("fti_0_cfg[1]" not in (pending / "u_ft.ports").read_text(encoding="utf-8"), "feedthrough ingress destination pending endpoint not removed")
    require("fto_0_cfg[1]" in (pending / "u_ft.ports").read_text(encoding="utf-8"), "internal feedthrough output was wrongly removed")
    require("cfg_i[1]" in (pending / "u_c.ports").read_text(encoding="utf-8"), "synthetic end-to-end destination was wrongly removed")
    removed = root / "30_middle" / "scenario" / "common" / "removed_log" / "30_harden_to_harden_exception.removed"
    require(removed.is_file(), "30 removed log was not written under 30_middle")


def test_partial_manifest_gate():
    root = WORK / "partial"
    write_inputs(root, missing_c=True)
    strict = sh(["--require-complete-harden-sdc"], root)
    require(strict.returncode == 1, "strict missing-SDC run must fail")
    partial = sh([], root)
    require(partial.returncode == 1, "partial first run must stop for review")
    approve_rules(root, partial=True)
    generated = sh([], root)
    require(generated.returncode == 0, "SDC-independent approved partial rule should generate:\n%s\n%s" % (generated.stdout, generated.stderr))
    sdc = (root / "30_result" / "common" / "30_harden_to_harden_exception.sdc").read_text(encoding="utf-8")
    require("Run completeness: partial" in sdc, "partial completeness missing from SDC")
    require("set_false_path" in sdc, "approved partial manual rule missing")


def test_scenario_is_required():
    root = WORK / "scenario_required"
    write_inputs(root)
    result = subprocess.run(
        [sys.executable, str(EX30), "--run-root", str(root)],
        cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    require(result.returncode == 2, "target run without --scenario must fail")
    require("--scenario is required" in result.stderr, "missing scenario diagnostic is unclear")
    forced = sh(["--force-generate-after-sync"], root)
    require(forced.returncode == 2, "target mode must reject force generation after sync")
    require("not allowed in target mode" in forced.stderr, "force-generation rejection diagnostic missing")


def test_candidate_only_modes():
    missing_root = WORK / "missing_owners"
    write_inputs(missing_root)
    (missing_root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv").unlink()
    (missing_root / "20_middle" / "scenario" / "common" / "channel_inventory.csv").unlink()
    missing = sh([], missing_root)
    require(missing.returncode == 1, "missing 10/20 must block formal generation")
    require((missing_root / "30_middle" / "30_harden_to_harden_exception.xlsx").is_file(), "candidate workbook missing when 10/20 are absent")
    require((missing_root / "30_middle" / "exception_candidates.csv").is_file(), "candidate CSV missing when 10/20 are absent")
    require(not (missing_root / "30_result" / "common" / "30_harden_to_harden_exception.sdc").exists(), "formal SDC generated without 10/20 owner inventories")

    diagnostic_root = WORK / "no_pending_update"
    write_inputs(diagnostic_root)
    first = sh([], diagnostic_root)
    require(first.returncode == 1, "diagnostic setup sync failed")
    diagnostic = sh(["--no-update-pending"], diagnostic_root)
    require(diagnostic.returncode == 0, "--no-update-pending diagnostic run failed")
    require(not (diagnostic_root / "30_result" / "common" / "30_harden_to_harden_exception.sdc").exists(), "diagnostic run wrote formal SDC")
    report = (diagnostic_root / "30_result" / "reports" / "harden_to_harden_exception_check_report_common_all_all.txt").read_text(encoding="utf-8")
    require("Accounting closure: incomplete" in report and "diagnostic/candidate-only" in report, "diagnostic report claimed accounting closure")
    candidate_text = (diagnostic_root / "30_middle" / "exception_candidates.csv").read_text(encoding="utf-8")
    require("disabled" in candidate_text, "diagnostic candidate CSV did not record disabled port accounting")


def test_stale_candidate_tracking():
    root = WORK / "stale"
    write_inputs(root)
    sdc_path = root / "inputs" / "sdc" / "u_a.sdc"
    sdc_path.write_text("set_false_path -from [get_ports cfg_o]\n", encoding="utf-8")
    first = sh([], root)
    require(first.returncode == 1, "stale setup first sync failed")
    sdc_path.write_text("# exception removed\n", encoding="utf-8")
    second = sh([], root)
    require(second.returncode == 1, "removing source evidence must trigger workbook review")
    wb = load_workbook(str(root / "30_middle" / "30_harden_to_harden_exception.xlsx"))
    ws = wb["exception_candidate"]
    columns = workbook_columns(ws)
    stale = [
        ws.cell(row=row, column=columns["candidate_id"]).value
        for row in range(2, ws.max_row + 1)
        if ws.cell(row=row, column=columns["candidate_status"]).value == "stale"
    ]
    require(stale, "removed source SDC evidence was not marked stale")
    report = (root / "30_result" / "reports" / "harden_to_harden_exception_check_report_common_all_all.txt").read_text(encoding="utf-8")
    require("stale candidates:" in report, "coverage report omitted stale candidates")


def test_generation_guards():
    endpoint_root = WORK / "bad_endpoint"
    write_inputs(endpoint_root)
    require(sh([], endpoint_root).returncode == 1, "bad endpoint setup sync failed")
    approve_rules(endpoint_root)
    path = endpoint_root / "30_middle" / "30_harden_to_harden_exception.xlsx"
    wb = load_workbook(str(path))
    ws = wb["exception_rule"]
    columns = workbook_columns(ws)
    for row in range(2, ws.max_row + 1):
        if ws.cell(row=row, column=columns["channel_id"]).value == "CH_u_a_cfg_o_bit0__u_c_cfg_i_bit0":
            setv(ws, columns, row, "src_endpoint", "[get_pins {u_a/wrong[0]}]")
            setv(ws, columns, row, "source_type", "extracted_harden_exception")
            setv(ws, columns, row, "source_command", "set_false_path -from [get_pins {u_internal/cfg_o}]")
            setv(ws, columns, row, "harden_clock_context_status", "matched")
        if ws.cell(row=row, column=columns["channel_id"]).value == "CH_u_a_cfg_o_bit1__u_ft_fti_0_cfg_bit1":
            setv(ws, columns, row, "max_value", "nan")
    wb.save(str(path))
    bad = sh([], endpoint_root)
    require(bad.returncode == 1, "bad endpoint/numeric rule was not blocked")
    report = (endpoint_root / "30_result" / "reports" / "harden_to_harden_exception_check_report_common_all_all.txt").read_text(encoding="utf-8")
    require("machine endpoint/bit fields do not match" in report and "max_value must be a finite number" in report and "harden-internal get_pins" in report, "generation guard diagnostics missing")
    require(not (endpoint_root / "30_result" / "common" / "30_harden_to_harden_exception.sdc").exists(), "invalid rule generated SDC")

    mcp_root = WORK / "bad_mcp"
    write_inputs(mcp_root)
    require(sh([], mcp_root).returncode == 1, "bad MCP setup sync failed")
    approve_rules(mcp_root)
    path = mcp_root / "30_middle" / "30_harden_to_harden_exception.xlsx"
    wb = load_workbook(str(path))
    ws = wb["exception_rule"]
    columns = workbook_columns(ws)
    for row in range(2, ws.max_row + 1):
        if ws.cell(row=row, column=columns["channel_id"]).value == "CH_u_a_cfg_o_bit0__u_c_cfg_i_bit0":
            setv(ws, columns, row, "exception_type", "multicycle_path")
            setv(ws, columns, row, "setup_cycles", "3.5")
            setv(ws, columns, row, "hold_cycles", "2")
            setv(ws, columns, row, "src_clock", "clk_a")
            setv(ws, columns, row, "dst_clock", "clk_a")
            setv(ws, columns, row, "mcp_reference", "")
    wb.save(str(path))
    bad_mcp = sh([], mcp_root)
    require(bad_mcp.returncode == 1, "invalid MCP rule was not blocked")
    report = (mcp_root / "30_result" / "reports" / "harden_to_harden_exception_check_report_common_all_all.txt").read_text(encoding="utf-8")
    require("setup_cycles must be a valid integer" in report and "same-clock multicycle requires" in report, "MCP diagnostics missing")

    pending_root = WORK / "missing_pending"
    write_inputs(pending_root)
    require(sh([], pending_root).returncode == 1, "missing pending setup sync failed")
    approve_rules(pending_root)
    shutil.rmtree(str(pending_root / "00_middle" / "scenario" / "common" / "pending"))
    missing_pending = sh([], pending_root)
    require(missing_pending.returncode == 1, "missing pending directory did not block generation")
    require(not (pending_root / "30_result" / "common" / "30_harden_to_harden_exception.sdc").exists(), "SDC was written before pending validation")


def main():
    test_target_generation()
    test_partial_manifest_gate()
    test_scenario_is_required()
    test_candidate_only_modes()
    test_stale_candidate_tracking()
    test_generation_guards()
    print("30_harden_to_harden_exception regression: PASS")


if __name__ == "__main__":
    main()
