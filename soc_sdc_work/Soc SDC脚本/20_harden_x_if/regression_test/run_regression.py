#!/usr/bin/env python3
"""Target-runtime regression for 20_extract_harden_x_if.py."""

from __future__ import print_function

import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from openpyxl import load_workbook


BASE = Path(__file__).resolve().parent
SCRIPT = BASE.parent / "20_extract_harden_x_if.py"
NORMAL_CHANNEL = "CH_u_a_data_o_bit0__u_c_data_i_bit0"
EXCEPTION_CHANNEL = "CH_u_a_cfg_o__u_c_cfg_i"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_csv(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def edge(connection_id, src_i, src_d, src_p, dst_i, dst_d, dst_p, scope="common"):
    def bit(port):
        return port.split("[")[-1].rstrip("]") if "[" in port else ""

    return {
        "schema_version": "1",
        "connection_id": connection_id,
        "connection_type": "harden_to_harden",
        "scenario_scope": scope,
        "src_instance": src_i,
        "src_direction": src_d,
        "src_port": src_p,
        "src_bit_index": bit(src_p),
        "src_endpoint_key": "%s:%s:%s" % (src_i, src_d, src_p),
        "src_soc_object": "%s/%s" % (src_i, src_p),
        "dst_instance": dst_i,
        "dst_direction": dst_d,
        "dst_port": dst_p,
        "dst_bit_index": bit(dst_p),
        "dst_endpoint_key": "%s:%s:%s" % (dst_i, dst_d, dst_p),
        "dst_soc_object": "%s/%s" % (dst_i, dst_p),
        "validation_status": "matched",
        "note": "",
    }


def build_target(root, missing_dst=False, include_feedthrough_inventory=True, create_pending=True):
    if root.exists():
        shutil.rmtree(str(root))
    root.mkdir(parents=True)

    connection_headers = [
        "schema_version", "connection_id", "connection_type", "scenario_scope",
        "src_instance", "src_direction", "src_port", "src_bit_index",
        "src_endpoint_key", "src_soc_object",
        "dst_instance", "dst_direction", "dst_port", "dst_bit_index",
        "dst_endpoint_key", "dst_soc_object", "validation_status", "note",
    ]
    rows = [
        edge("CONN_NORMAL", "u_a", "output", "data_o[0]", "u_c", "input", "data_i[0]"),
        edge("CONN_FT_IN", "u_a", "output", "ft_src_o[0]", "u_b", "input", "fti_0_path[0]"),
        edge("CONN_FT_OUT", "u_b", "output", "fto_0_path[0]", "u_c", "input", "ft_dst_i[0]"),
        edge("CONN_EXCEPTION", "u_a", "output", "cfg_o", "u_c", "input", "cfg_i"),
        edge("CONN_CLOCK", "u_a", "output", "clk_o", "u_c", "input", "clk_i"),
        edge("CONN_SCAN_ONLY", "u_a", "output", "scan_o", "u_c", "input", "scan_i", "scan"),
    ]
    write_csv(root / "00_middle/connection_inventory.csv", connection_headers, rows)

    write_text(
        root / "inputs/u_a.sdc",
        "set_output_delay -max 2.0 -clock [get_clocks {clk_a}] [get_ports {data_o[0]}]\n"
        "set_output_delay -max 3.0 -clock [get_clocks {clk_a}] [get_ports {ft_src_o[0]}]\n"
        "set_output_delay -max 0.8 -clock [get_clocks {clk_a}] [get_ports {cfg_o}]\n"
        "set_false_path -from [\n"
        "  get_ports {cfg_o}\n"
        "]\n",
    )
    write_text(root / "inputs/u_b.sdc", "")
    if not missing_dst:
        write_text(
            root / "inputs/u_c.sdc",
            "set_input_delay -max 1.5 -clock [get_clocks {clk_c}] [get_ports {data_i[0]}]\n"
            "set_input_delay -max 2.5 -clock [get_clocks {clk_c}] [get_ports {ft_dst_i[0]}]\n"
            "set_input_delay -max 0.7 -clock [get_clocks {clk_c}] [get_ports {cfg_i}]\n",
        )

    manifest_rows = [
        {"scenario": "common", "inst_name": "u_a", "module_name": "harden_a", "sdc_path": "inputs/u_a.sdc", "availability_status": "available", "note": ""},
        {"scenario": "common", "inst_name": "u_b", "module_name": "harden_b", "sdc_path": "inputs/u_b.sdc", "availability_status": "available", "note": ""},
        {
            "scenario": "common",
            "inst_name": "u_c",
            "module_name": "harden_c",
            "sdc_path": "inputs/u_c.sdc",
            "availability_status": "missing" if missing_dst else "available",
            "note": "awaiting delivery" if missing_dst else "",
        },
    ]
    write_csv(
        root / "00_middle/scenario/common/harden_sdc_manifest.csv",
        ["scenario", "inst_name", "module_name", "sdc_path", "availability_status", "note"],
        manifest_rows,
    )

    if create_pending:
        write_text(
            root / "00_middle/scenario/common/pending/u_a.ports",
            "output data_o[0]\noutput ft_src_o[0]\noutput cfg_o\noutput clk_o\noutput scan_o\n",
        )
        write_text(
            root / "00_middle/scenario/common/pending/u_b.ports",
            "input fti_0_path[0]\noutput fto_0_path[0]\n",
        )
        write_text(
            root / "00_middle/scenario/common/pending/u_c.ports",
            "input data_i[0]\ninput ft_dst_i[0]\ninput cfg_i\ninput clk_i\ninput scan_i\n",
        )

    final_clock_sdc = root / "01_result/common/01_soc_clocks.sdc"
    write_text(final_clock_sdc, "# clock fixture\n")
    clock_csv = root / "01_middle/assembled/common/clock_inventory.csv"
    clock_headers = [
        "clock_name", "inst_name", "original_clock_name", "port_name",
        "target_object", "direct_source", "producer_object", "final_action",
    ]
    clock_rows = [
        {"clock_name": "soc_clk_a", "inst_name": "u_a", "original_clock_name": "clk_a", "port_name": "clk_o", "target_object": "u_a/clk_o", "direct_source": "", "producer_object": "", "final_action": "emit_virtual_clock"},
        {"clock_name": "soc_clk_c", "inst_name": "u_c", "original_clock_name": "clk_c", "port_name": "", "target_object": "", "direct_source": "", "producer_object": "", "final_action": "emit_virtual_clock"},
    ]
    write_csv(clock_csv, clock_headers, clock_rows)
    clock_meta = root / "01_middle/assembled/common/clock_inventory.meta"
    write_json(
        clock_meta,
        {
            "author": "Howard",
            "scenario": "common",
            "run_completeness": "partial" if missing_dst else "complete",
            "inventory_digest": sha(clock_csv),
            "clock_count": 2,
            "clock_set_digest": hashlib.sha256("soc_clk_a\nsoc_clk_c".encode("utf-8")).hexdigest(),
            "final_sdc_path": str(final_clock_sdc),
            "final_sdc_digest": sha(final_clock_sdc),
        },
    )

    relation_csv = root / "03_middle/relation_map/common.csv"
    write_csv(
        relation_csv,
        ["schema_version", "scenario", "clock_a", "clock_b", "relation_type", "relation_source", "source_rule_ids", "clock_universe_digest", "assembled_view_digest"],
        [{
            "schema_version": "1", "scenario": "common", "clock_a": "soc_clk_a", "clock_b": "soc_clk_c",
            "relation_type": "synchronous", "relation_source": "default_synchronous", "source_rule_ids": "",
            "clock_universe_digest": hashlib.sha256("soc_clk_a\nsoc_clk_c".encode("utf-8")).hexdigest(),
            "assembled_view_digest": "fixture_view",
        }],
    )
    write_json(
        root / "03_middle/relation_map/common.meta",
        {
            "author": "Howard",
            "schema_version": "1",
            "scenario": "common",
            "run_completeness": "partial" if missing_dst else "complete",
            "relation_map_digest": sha(relation_csv),
            "inventory_digest": sha(clock_csv),
            "inventory_meta_digest": sha(clock_meta),
            "clock_universe_digest": hashlib.sha256("soc_clk_a\nsoc_clk_c".encode("utf-8")).hexdigest(),
            "assembled_view_digest": "fixture_view",
        },
    )

    ft_path = root / "10_middle/scenario/common/feedthrough_edge_inventory.csv"
    if include_feedthrough_inventory:
        write_csv(
            ft_path,
            ["schema_version", "scenario", "feedthrough_edge_id", "connection_id"],
            [
                {"schema_version": "1", "scenario": "common", "feedthrough_edge_id": "FTE_CONN_FT_IN", "connection_id": "CONN_FT_IN"},
                {"schema_version": "1", "scenario": "common", "feedthrough_edge_id": "FTE_CONN_FT_OUT", "connection_id": "CONN_FT_OUT"},
            ],
        )


def run_stage(root, mode=None, extra=None):
    args = [
        sys.executable,
        str(SCRIPT),
        "--run-root",
        str(root),
        "--scenario",
        "common",
    ]
    if mode:
        args.extend(["--mode", mode])
    args.extend(extra or [])
    return subprocess.run(
        args,
        cwd=str(BASE.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def run_legacy(root, extra=None):
    args = [sys.executable, str(SCRIPT), "--scenario", "common"]
    args.extend(extra or [])
    return subprocess.run(
        args,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def read_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        return list(csv.DictReader(file_obj))


def executable_tcl_lines(path):
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def workbook_row(form, channel_id):
    workbook = load_workbook(str(form))
    sheet = workbook["interface_budget"]
    headers = {cell.value: cell.column for cell in sheet[1] if cell.value}
    for row_idx in range(2, sheet.max_row + 1):
        if sheet.cell(row_idx, headers["channel_id"]).value == channel_id:
            return workbook, sheet, headers, row_idx
    raise AssertionError("channel not found in workbook: " + channel_id)


def mutate_row(form, channel_id, updates):
    workbook, sheet, headers, row_idx = workbook_row(form, channel_id)
    for key, value in updates.items():
        sheet.cell(row_idx, headers[key], value)
    workbook.save(str(form))


def test_default_audit(root):
    build_target(root)
    result = run_stage(root)
    require(result.returncode == 0, "audit_only failed:\n%s\n%s" % (result.stdout, result.stderr))
    require(result.stdout.count("Author: Howard") == 1, "author stdout count is not exactly one")

    inventory = root / "20_middle/scenario/common/channel_inventory.csv"
    rows = read_rows(inventory)
    require({row["connection_id"] for row in rows} == {"CONN_NORMAL", "CONN_EXCEPTION"}, "20 ownership/filtering mismatch")
    require(all(row["mode"] == "audit_only" for row in rows), "inventory mode mismatch")
    require(all(row["owner_stage"] == "20" for row in rows), "20->30 owner_stage enum mismatch")
    normal = next(row for row in rows if row["connection_id"] == "CONN_NORMAL")
    exception = next(row for row in rows if row["connection_id"] == "CONN_EXCEPTION")
    require(normal["channel_disposition"] == "no_soc_budget_required", "normal channel did not auto-close")
    require(exception["channel_disposition"] == "route_to_30", "known exception did not route to 30")
    require(exception["apply"] == "yes" and exception["review_status"] == "approved", "known exception route is not a formal 20 owner decision")
    require("CONN_FT" not in inventory.read_text(encoding="utf-8"), "feedthrough direct edge leaked into 20")
    require("CONN_CLOCK" not in inventory.read_text(encoding="utf-8"), "clock edge leaked into 20")
    workbook = load_workbook(str(root / "20_middle/20_harden_x_if.xlsx"), data_only=True)
    metadata = {workbook["run_metadata"].cell(row, 1).value: workbook["run_metadata"].cell(row, 2).value for row in range(2, workbook["run_metadata"].max_row + 1)}
    require(metadata.get("author") == "Howard", "author missing from workbook metadata")
    require(metadata.get("sdc_consumption") == "disabled", "workbook consumption metadata mismatch")
    channel_sheet = workbook["channel_inventory"]
    channel_headers = [cell.value for cell in channel_sheet[1]]
    workbook_connections = {
        channel_sheet.cell(row_idx, channel_headers.index("connection_id") + 1).value
        for row_idx in range(2, channel_sheet.max_row + 1)
    }
    require(workbook_connections == {row["connection_id"] for row in rows}, "workbook/CSV resolved views differ")
    inventory_meta = json.loads((root / "20_middle/scenario/common/channel_inventory.meta").read_text(encoding="utf-8"))
    require(inventory_meta["scenario"] == "common", "inventory meta scenario mismatch")
    require(inventory_meta["channel_inventory_digest"] == sha(inventory), "inventory meta digest mismatch")

    sdc = root / "20_result/common/20_harden_x_if.sdc"
    require(executable_tcl_lines(sdc) == [], "audit SDC contains executable Tcl")
    require("Author: Howard" in sdc.read_text(encoding="utf-8"), "author missing from SDC")
    report = root / "20_result/reports/harden_x_if_check_report_common.txt"
    report_text = report.read_text(encoding="utf-8")
    require("timing-command count: 0" in report_text, "audit report command count mismatch")
    require("SDC consumption: disabled" in report_text, "audit report consumption mismatch")

    require("data_o[0]" not in (root / "00_middle/scenario/common/pending/u_a.ports").read_text(encoding="utf-8"), "source direct bit not removed")
    require("data_i[0]" not in (root / "00_middle/scenario/common/pending/u_c.ports").read_text(encoding="utf-8"), "destination direct bit not removed")
    require("fti_0_path[0]" in (root / "00_middle/scenario/common/pending/u_b.ports").read_text(encoding="utf-8"), "feedthrough endpoint was removed by 20")
    require("cfg_o" in (root / "00_middle/scenario/common/pending/u_a.ports").read_text(encoding="utf-8"), "route_to_30 endpoint was removed")

    removed = root / "20_middle/scenario/common/removed_log/20_harden_x_if.removed"
    before_pending = (root / "00_middle/scenario/common/pending/u_a.ports").read_bytes()
    before_removed = removed.read_bytes()
    write_text(root / "03_middle/relation_map/common.meta", "stale audit-only diagnostic\n")
    rerun = run_stage(root)
    require(rerun.returncode == 0, "audit idempotent rerun failed or incorrectly depended on 03")
    require(before_pending == (root / "00_middle/scenario/common/pending/u_a.ports").read_bytes(), "pending changed on idempotent rerun")
    require(before_removed == removed.read_bytes(), "removed log changed on idempotent rerun")


def test_audit_emit_gates(base):
    cases = [
        ("disposition", {"channel_disposition": "emit_budget"}),
        ("budget_required", {"budget_required": "yes"}),
        ("emit_max", {"emit_max": "yes"}),
        ("emit_min", {"emit_min": "yes"}),
    ]
    for name, updates in cases:
        root = base / name
        build_target(root)
        initial = run_stage(root)
        require(initial.returncode == 0, "initial audit failed for gate " + name)
        form = root / "20_middle/20_harden_x_if.xlsx"
        mutate_row(form, NORMAL_CHANNEL, updates)
        sdc = root / "20_result/common/20_harden_x_if.sdc"
        pending = root / "00_middle/scenario/common/pending/u_a.ports"
        before_sdc = sdc.read_bytes()
        before_pending = pending.read_bytes()
        result = run_stage(root)
        require(result.returncode != 0, "audit gate accepted " + name)
        report = (root / "20_result/reports/harden_x_if_check_report_common.txt").read_text(encoding="utf-8")
        require("audit_only forbids emit intent" in report, "missing audit gate diagnostic for " + name)
        require(before_sdc == sdc.read_bytes(), "failed audit overwrote formal SDC for " + name)
        require(before_pending == pending.read_bytes(), "failed audit changed pending for " + name)


def test_budget_output(root):
    build_target(root)
    first = run_stage(root, "budget_output")
    require(first.returncode != 0, "first budget run should stop after workbook sync")
    report_text = (root / "20_result/reports/harden_x_if_check_report_common.txt").read_text(encoding="utf-8")
    require("Errors  : 0" in report_text, "first budget run failed for reasons other than sync")
    form = root / "20_middle/20_harden_x_if.xlsx"
    mutate_row(
        form,
        NORMAL_CHANNEL,
        {
            "channel_disposition": "emit_budget",
            "budget_required": "yes",
            "budget_model": "interconnect_budget",
            "converted_max": "",
            "max_source": "",
            "derivation_basis": "",
            "tool_surface": "sta",
            "datapath_only": "yes",
            "budget_basis": "interconnect budget approved by both block owners",
            "apply": "yes",
            "emit_max": "yes",
            "emit_min": "no",
            "review_status": "approved",
        },
    )
    second = run_stage(root, "budget_output")
    require(second.returncode == 0, "approved budget run failed:\n%s\n%s" % (second.stdout, second.stderr))
    sdc = root / "20_result/common/20_harden_x_if.sdc"
    commands = executable_tcl_lines(sdc)
    require(commands == ["set_max_delay 1.5 -datapath_only -from [get_pins {u_a/data_o[0]}] -to [get_pins {u_c/data_i[0]}]"], "budget output command mismatch: %r" % commands)
    require("CONN_FT" not in sdc.read_text(encoding="utf-8"), "budget output contains feedthrough command")


def test_view_specific_budget(root):
    build_target(root)
    view = ["--stage", "prects", "--corner", "ss_125"]
    first = run_stage(root, "budget_output", view)
    require(first.returncode != 0, "view-specific first run should sync workbook")
    form = root / "20_middle/20_harden_x_if.xlsx"
    _, sheet, headers, row_idx = workbook_row(form, NORMAL_CHANNEL)
    require(sheet.cell(row_idx, headers["stage"]).value == "prects", "view-specific stage was not seeded")
    require(sheet.cell(row_idx, headers["corner"]).value == "ss_125", "view-specific corner was not seeded")
    mutate_row(
        form,
        NORMAL_CHANNEL,
        {
            "channel_disposition": "emit_budget",
            "budget_required": "yes",
            "budget_model": "manual_budget",
            "converted_max": "1.0",
            "tool_surface": "sta",
            "datapath_only": "yes",
            "budget_basis": "view-specific manual interconnect budget",
            "derivation_basis": "architecture review",
            "apply": "yes",
            "emit_max": "yes",
            "emit_min": "no",
            "review_status": "approved",
        },
    )
    second = run_stage(root, "budget_output", view)
    require(second.returncode == 0, "view-specific approved run failed")
    output = root / "20_result/common/20_harden_x_if_prects_ss_125.sdc"
    require(len(executable_tcl_lines(output)) == 1, "view-specific SDC command missing")
    audit = run_stage(root)
    require(audit.returncode == 0, "all/all audit after view-specific budget failed")
    workbook = load_workbook(str(form), data_only=True)
    sheet = workbook["interface_budget"]
    headers = {cell.value: cell.column for cell in sheet[1] if cell.value}
    views = {
        (sheet.cell(row_idx, headers["stage"]).value, sheet.cell(row_idx, headers["corner"]).value)
        for row_idx in range(2, sheet.max_row + 1)
        if sheet.cell(row_idx, headers["channel_id"]).value == NORMAL_CHANNEL
    }
    require({("all", "all"), ("prects", "ss_125")}.issubset(views), "cross-view workbook rows were deleted")


def test_stale_budget_review(root):
    build_target(root)
    first = run_stage(root, "budget_output")
    require(first.returncode != 0, "stale-review fixture did not create workbook")
    form = root / "20_middle/20_harden_x_if.xlsx"
    mutate_row(
        form,
        NORMAL_CHANNEL,
        {
            "channel_disposition": "emit_budget",
            "budget_required": "yes",
            "budget_model": "manual_budget",
            "converted_max": "1.0",
            "tool_surface": "sta",
            "datapath_only": "yes",
            "budget_basis": "manual interconnect budget",
            "derivation_basis": "architecture review",
            "apply": "yes",
            "emit_max": "yes",
            "emit_min": "no",
            "review_status": "approved",
        },
    )
    source = root / "inputs/u_a.sdc"
    write_text(source, source.read_text(encoding="utf-8").replace("-max 2.0", "-max 2.2", 1))
    pending = root / "00_middle/scenario/common/pending/u_a.ports"
    before = pending.read_bytes()
    result = run_stage(root, "budget_output")
    require(result.returncode != 0, "changed SDC retained stale budget approval")
    _, sheet, headers, row_idx = workbook_row(form, NORMAL_CHANNEL)
    require(sheet.cell(row_idx, headers["review_status"]).value == "pending", "material change did not reset review")
    require(sheet.cell(row_idx, headers["emit_max"]).value == "no", "material change did not disable emit")
    require(before == pending.read_bytes(), "stale review failure changed pending")
    require(not (root / "20_result/common/20_harden_x_if.sdc").exists(), "stale review wrote formal SDC")


def test_async_relation_gate(root):
    build_target(root)
    first = run_stage(root, "budget_output")
    require(first.returncode != 0, "async fixture did not create workbook")
    form = root / "20_middle/20_harden_x_if.xlsx"
    mutate_row(
        form,
        NORMAL_CHANNEL,
        {
            "channel_disposition": "emit_budget",
            "budget_required": "yes",
            "budget_model": "manual_budget",
            "converted_max": "1.0",
            "tool_surface": "sta",
            "datapath_only": "yes",
            "budget_basis": "manual interconnect budget",
            "derivation_basis": "architecture review",
            "apply": "yes",
            "emit_max": "yes",
            "emit_min": "no",
            "review_status": "approved",
        },
    )
    relation = root / "03_middle/relation_map/common.csv"
    rows = read_rows(relation)
    headers = list(rows[0].keys())
    rows[0]["relation_type"] = "asynchronous"
    write_csv(relation, headers, rows)
    meta_path = root / "03_middle/relation_map/common.meta"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["relation_map_digest"] = sha(relation)
    write_json(meta_path, meta)
    result = run_stage(root, "budget_output")
    require(result.returncode != 0, "asynchronous relation allowed normal 20 budget")
    report = (root / "20_result/reports/harden_x_if_check_report_common.txt").read_text(encoding="utf-8")
    require("clock_relation=asynchronous blocks normal 20 budget" in report, "async relation diagnostic missing")
    require(not (root / "20_result/common/20_harden_x_if.sdc").exists(), "async relation wrote formal SDC")


def test_partial_and_strict(base):
    partial = base / "partial"
    build_target(partial, missing_dst=True)
    result = run_stage(partial)
    require(result.returncode == 0, "partial audit failed")
    normal = next(row for row in read_rows(partial / "20_middle/scenario/common/channel_inventory.csv") if row["connection_id"] == "CONN_NORMAL")
    require(normal["run_completeness"] == "partial", "partial completeness missing")
    require(normal["dst_sdc_status"] == "missing", "missing destination status lost")
    require(normal["evidence_status"] == "incomplete_missing_sdc", "missing evidence status lost")
    require(normal["sdc_independent_basis"] == "project_pr_adjacent_policy_independent_of_block_sdc_v1", "SDC-independent policy missing")
    report = (partial / "20_result/reports/harden_x_if_check_report_common.txt").read_text(encoding="utf-8")
    require("incomplete exception evidence rows" in report, "partial exception coverage not reported")

    strict = base / "strict"
    build_target(strict, missing_dst=True)
    pending = strict / "00_middle/scenario/common/pending/u_a.ports"
    before = pending.read_bytes()
    result = run_stage(strict, extra=["--require-complete-harden-sdc"])
    require(result.returncode != 0, "strict missing SDC gate did not fail")
    require(before == pending.read_bytes(), "strict failure changed pending")
    strict_report = (strict / "20_result/reports/harden_x_if_check_report_common.txt").read_text(encoding="utf-8")
    require("HARDEN_SDC_COMPLETENESS_REQUIRED" in strict_report, "strict diagnostic missing")
    require(not (strict / "20_result/common/20_harden_x_if.sdc").exists(), "strict failure wrote formal SDC")


def test_missing_10_inventory(root):
    build_target(root, include_feedthrough_inventory=False)
    before = (root / "00_middle/scenario/common/pending/u_a.ports").read_bytes()
    result = run_stage(root)
    require(result.returncode != 0, "missing 10 inventory did not block")
    require(before == (root / "00_middle/scenario/common/pending/u_a.ports").read_bytes(), "missing 10 failure changed pending")
    report = (root / "20_result/reports/harden_x_if_check_report_common.txt").read_text(encoding="utf-8")
    require("feedthrough edge inventory not found" in report, "missing 10 diagnostic absent")


def test_no_update_pending(root):
    build_target(root, create_pending=False)
    result = run_stage(root, extra=["--no-update-pending"])
    require(result.returncode == 0, "--no-update-pending diagnostic run failed")
    report = (root / "20_result/reports/harden_x_if_check_report_common.txt").read_text(encoding="utf-8")
    require("Port accounting: disabled by explicit option" in report, "disabled accounting missing from report")
    sdc = (root / "20_result/common/20_harden_x_if.sdc").read_text(encoding="utf-8")
    require("Port accounting: disabled by explicit option" in sdc, "disabled accounting missing from SDC header")


def test_noncanonical_edge(root):
    build_target(root)
    path = root / "00_middle/connection_inventory.csv"
    rows = read_rows(path)
    headers = list(rows[0].keys())
    for row in rows:
        if row["connection_id"] == "CONN_NORMAL":
            row["src_port"] = "data_o[1:0]"
            row["src_bit_index"] = ""
            row["src_endpoint_key"] = "u_a:output:data_o[1:0]"
            row["src_soc_object"] = "u_a/data_o[1:0]"
    write_csv(path, headers, rows)
    result = run_stage(root)
    require(result.returncode != 0, "noncanonical range edge did not block")
    report = (root / "20_result/reports/harden_x_if_check_report_common.txt").read_text(encoding="utf-8")
    require("not a canonical scalar/bit key" in report, "noncanonical diagnostic missing")


def test_unbalanced_tcl_blocks_accounting(root):
    build_target(root)
    source = root / "inputs/u_a.sdc"
    write_text(source, source.read_text(encoding="utf-8") + "set_false_path -from [get_ports {data_o[0]}\n")
    pending = root / "00_middle/scenario/common/pending/u_a.ports"
    before = pending.read_bytes()
    result = run_stage(root)
    require(result.returncode != 0, "unbalanced Tcl did not block audit")
    require(before == pending.read_bytes(), "unbalanced Tcl changed pending")
    report = (root / "20_result/reports/harden_x_if_check_report_common.txt").read_text(encoding="utf-8")
    require("unbalanced Tcl brace/bracket/quote" in report, "unbalanced Tcl diagnostic missing")
    require(not (root / "20_result/common/20_harden_x_if.sdc").exists(), "unbalanced Tcl wrote formal SDC")


def test_delay_value_parser():
    spec = importlib.util.spec_from_file_location("stage20_parser", str(SCRIPT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = [
        ("set_input_delay 0.2 -min -clock [get_clocks {clk}] [get_ports {data}]", ("0.2", "", "")),
        ("set_output_delay -0.2 -min -clock [get_clocks {clk}] [get_ports {data}]", ("-0.2", "", "")),
        ("set_input_delay -max 1.5 -min -0.1 -clock [get_clocks {clk}] [get_ports {data}]", ("-0.1", "1.5", "")),
        ("set_input_delay 0.4 -clock [get_clocks {clk}] [get_ports {data}]", ("0.4", "0.4", "")),
    ]
    for command, expected in cases:
        actual = module.parse_delay_values(module.tokenize_tcl_words(command))
        require(actual == expected, "delay parser mismatch for %s: %r" % (command, actual))
    for value in ("abc", "nan", "inf", "-inf"):
        require(module.parse_number(value) is None, "non-finite/non-numeric value accepted: " + value)


def test_legacy_layout(root):
    build_target(root)
    legacy_00 = root / "00_harden_port_inventory"
    legacy_00.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(root / "00_middle/connection_inventory.csv"), str(legacy_00 / "connection_inventory.csv"))
    shutil.copytree(str(root / "00_middle/scenario/common/pending"), str(legacy_00 / "pending"))
    for name in ("u_a.sdc", "u_b.sdc", "u_c.sdc"):
        shutil.copy2(str(root / "inputs" / name), str(root / name))
    shutil.copy2(str(root / "01_middle/assembled/common/clock_inventory.csv"), str(root / "clock_inventory.csv"))
    shutil.copy2(str(root / "10_middle/scenario/common/feedthrough_edge_inventory.csv"), str(root / "feedthrough_edge_inventory.csv"))
    for name in ("00_middle", "01_middle", "01_result", "03_middle", "10_middle"):
        shutil.rmtree(str(root / name))
    result = run_legacy(root)
    require(result.returncode == 0, "legacy compatibility run failed:\n%s\n%s" % (result.stdout, result.stderr))
    require(executable_tcl_lines(root / "common/20_harden_x_if.sdc") == [], "legacy audit SDC contains Tcl")
    require((root / "channel_inventory.csv").is_file(), "legacy machine inventory missing")
    require(not (root / "20_middle").exists(), "legacy run mixed target 20_middle state")


def test_scenario_required(root):
    root.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-root", str(root)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    require(result.returncode == 2, "missing --scenario did not fail CLI parsing")
    require("--scenario" in result.stderr and "required" in result.stderr, "missing scenario diagnostic absent")


def main():
    with tempfile.TemporaryDirectory(prefix="soc_sdc_20_regression.") as tmp:
        base = Path(tmp)
        test_default_audit(base / "audit")
        test_audit_emit_gates(base / "gates")
        test_budget_output(base / "budget")
        test_view_specific_budget(base / "view_budget")
        test_stale_budget_review(base / "stale_review")
        test_async_relation_gate(base / "async_relation")
        test_partial_and_strict(base / "missing")
        test_missing_10_inventory(base / "missing_10")
        test_no_update_pending(base / "no_accounting")
        test_noncanonical_edge(base / "noncanonical")
        test_unbalanced_tcl_blocks_accounting(base / "unbalanced_tcl")
        test_delay_value_parser()
        test_legacy_layout(base / "legacy")
        test_scenario_required(base / "scenario_required")
    print("20_harden_x_if target regression passed")


if __name__ == "__main__":
    main()
