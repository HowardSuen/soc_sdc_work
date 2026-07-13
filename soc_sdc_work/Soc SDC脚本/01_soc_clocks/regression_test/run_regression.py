#!/usr/bin/env python3
"""Complex regression for 01_extract_soc_clocks.py.

The test builds fresh inputs under work_complex/ and checks:
  * normal SoC clock extraction across top, upstream harden, generated, and forwarded clocks
  * dependency ordering in generated SDC
  * -source [get_clocks ...] SoC name remap
  * non-clock command reporting
  * -add out-of-scope warning
  * explicit bit clock targets and 00 connection_inventory source-bit mapping
  * owner sheet fallback/orphan warnings
  * 00 pending consumption and idempotent rerun
  * blocking negative cases with precise report messages
"""
from __future__ import print_function

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd


BASE = Path(__file__).resolve().parent
SOC = BASE.parent.parent
EX01 = SOC / "01_soc_clocks" / "01_extract_soc_clocks.py"
WORK = BASE / "work_complex"

REQ_COLS = [
    "Parameter", "Inout", "Inout Width", "Inout Connectivity", "Inout Name",
    "Input", "Input Width", "Input Used Width", "From Whom",
    "Output", "Output Width", "Output Used Width", "To Top",
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


def port_sheet(rows):
    df = pd.DataFrame(rows)
    for col in REQ_COLS:
        if col not in df.columns:
            df[col] = ""
    return df[REQ_COLS].fillna("")


def write_pending(root, inst_name, lines):
    pending = root / "00_harden_port_inventory" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / (inst_name + ".ports")).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_connection_inventory(root, rows):
    path = root / "00_harden_port_inventory" / "connection_inventory.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "connection_id", "connection_type",
        "src_instance", "src_direction", "src_port", "src_bit_index", "src_endpoint_key",
        "dst_instance", "dst_direction", "dst_port", "dst_bit_index", "dst_endpoint_key",
        "validation_status",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_harden_sdc_manifest(root, rows):
    manifest_dir = root / "00_middle" / "scenario" / "common"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = manifest_dir / "harden_sdc_manifest.csv"
    fields = [
        "scenario", "inst_name", "module_name", "sdc_path",
        "availability_status", "note",
    ]
    with manifest.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            item = dict(row)
            item.setdefault("scenario", "common")
            item.setdefault("sdc_path", "")
            item.setdefault("note", "")
            writer.writerow(item)
    return manifest


def build_positive_case(d):
    clean_dir(d)
    pd.DataFrame([
        {"module_name": "fab", "inst_name": "u_fab0", "owner": "alice", "file_path": ""},
        {"module_name": "pll_top", "inst_name": "u_pll", "owner": "alice", "file_path": ""},
        {"module_name": "edge_mod", "inst_name": "u_edge", "owner": "bob", "file_path": ""},
    ]).to_excel(d / "info_all.xlsx", index=False)

    with pd.ExcelWriter(str(d / "port_alice.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Input": "fab_clk_i", "Input Width": 1, "From Whom": "u_pll.core_clk_o"},
            {"Input": "fab_bus_clk_i", "Input Width": 2, "From Whom": "u_pll.bus_clk_o"},
            {"Output": "fab_clk_o", "Output Width": 1},
            {"Output": "data_o", "Output Width": 1},
        ]).to_excel(writer, sheet_name="u_fab0", index=False)
        port_sheet([
            {"Input": "ref_clk_in", "Input Width": 1, "From Whom": "top.sys_clk_pad"},
            {"Output": "core_clk_o", "Output Width": 1},
            {"Output": "bus_clk_o", "Output Width": 2},
            {"Input": "cfg_i", "Input Width": 1},
        ]).to_excel(writer, sheet_name="u_pll", index=False)

    with pd.ExcelWriter(str(d / "port_bob.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Input": "ref_i", "Input Width": 1, "From Whom": "top.ref_pad"},
            {"Output": "gen_o", "Output Width": 1},
            {"Output": "add_o", "Output Width": 1},
            {"Output": "manual_o", "Output Width": 1},
            {"Input": "cfg_i", "Input Width": 1},
        ]).to_excel(writer, sheet_name="U_EDGE", index=False)
        port_sheet([
            {"Input": "unused_i", "Input Width": 1, "From Whom": "top.unused_pad"},
        ]).to_excel(writer, sheet_name="u_orphan", index=False)

    (d / "pll_top.sdc").write_text(
        "create_clock -name pll_ref -period 20.000 [get_ports ref_clk_in]\n"
        "create_generated_clock -name pll_core -source [get_ports ref_clk_in] -multiply_by 4 [get_ports core_clk_o]\n"
        "create_generated_clock -name pll_bus0 -source [get_ports ref_clk_in] -multiply_by 2 [get_ports {bus_clk_o[0]}]\n"
        "create_generated_clock -name pll_bus1 -source [get_ports ref_clk_in] -multiply_by 2 [get_ports {bus_clk_o[1]}]\n"
        "set_false_path -from [get_ports ref_clk_in]\n",
        encoding="utf-8",
    )
    (d / "fab.sdc").write_text(
        "create_clock -name fab_in -period 5.000 [get_ports fab_clk_i]\n"
        "create_clock -name fab_bus_in0 -period 10.000 [get_ports {fab_bus_clk_i[0]}]\n"
        "create_generated_clock -name fab_out -source [get_ports fab_clk_i] -combinational [get_ports fab_clk_o]\n",
        encoding="utf-8",
    )
    (d / "edge_mod.sdc").write_text(
        "create_clock -name local_ref -period 10.000 [get_ports ref_i]\n"
        "create_generated_clock -name gen_clk -source [get_clocks local_ref] -divide_by 2 [get_ports gen_o]\n"
        "create_generated_clock -add -name add_clk -source [get_ports ref_i] -divide_by 4 [get_ports add_o]\n",
        encoding="utf-8",
    )
    (d / "virtual_clocks.csv").write_text(
        "clock_name,period,waveform,note\n"
        "v_ref_a,10.000,,board ref A\n"
        "v_ref_a,12.000,,duplicate virtual warning\n",
        encoding="utf-8",
    )
    (d / "01_soc_clocks_manual.sdc").write_text(
        "create_generated_clock -name u_edge_manual_o "
        "-source [get_pins u_edge/ref_i] -divide_by 8 [get_pins u_edge/manual_o]\n",
        encoding="utf-8",
    )

    write_pending(d, "u_fab0", [
        "input fab_clk_i",
        "input fab_bus_clk_i[0]",
        "input fab_bus_clk_i[1]",
        "output fab_clk_o",
        "output data_o",
    ])
    write_pending(d, "u_pll", [
        "input ref_clk_in",
        "output core_clk_o",
        "output bus_clk_o[0]",
        "output bus_clk_o[1]",
        "input cfg_i",
    ])
    write_pending(d, "u_edge", [
        "input ref_i",
        "output gen_o",
        "output add_o",
        "output manual_o",
        "input cfg_i",
    ])

    write_connection_inventory(d, [
        {
            "connection_id": "CONN_u_pll_bus_clk_o_bit1__u_fab0_fab_bus_clk_i_bit0",
            "connection_type": "clock_connection",
            "src_instance": "u_pll",
            "src_direction": "output",
            "src_port": "bus_clk_o[1]",
            "src_bit_index": "1",
            "src_endpoint_key": "u_pll:output:bus_clk_o[1]",
            "dst_instance": "u_fab0",
            "dst_direction": "input",
            "dst_port": "fab_bus_clk_i[0]",
            "dst_bit_index": "0",
            "dst_endpoint_key": "u_fab0:input:fab_bus_clk_i[0]",
            "validation_status": "matched",
        },
    ])


def run_positive_case():
    d = WORK / "positive"
    build_positive_case(d)
    first = sh([EX01], d)
    require(first.returncode == 0, "positive 01 run failed:\n%s\n%s" % (first.stdout, first.stderr))
    require(first.stdout.count("Author: Howard") == 1, "stdout author marker missing or duplicated")

    rerun = sh([EX01], d)
    require(rerun.returncode == 0, "positive 01 rerun should be idempotent:\n%s\n%s" % (rerun.stdout, rerun.stderr))

    sdc = (d / "common" / "01_soc_clocks.sdc").read_text(encoding="utf-8")
    report = (d / "clock_check_report.txt").read_text(encoding="utf-8")
    removed = (d / "00_harden_port_inventory" / "removed_log" / "01_soc_clocks.removed").read_text(encoding="utf-8")
    rows = list(csv.DictReader((d / "clock_inventory.csv").open(encoding="utf-8-sig")))
    by_name = {row["clock_name"]: row for row in rows}

    require("-source [get_clocks {top_ref_pad}]" in sdc, "get_clocks source was not remapped to SoC clock name")
    require("u_pll_bus_clk_o_bit1" in sdc and "[get_pins {u_pll/bus_clk_o[1]}]" in sdc, "bit output clock was not emitted with canonical bit naming")
    require(sdc.index("u_pll_core_clk_o") < sdc.index("u_fab0_fab_clk_o"), "generated SDC is not dependency ordered")
    require("IGNORED_NON_CLOCK_COMMAND" in report, "non-clock SDC command was not reported")
    require("CLOCK_ADD_OPTION_OUT_OF_SCOPE" in report, "-add warning missing")
    require("CLOCK_DUPLICATE_VIRTUAL_CLOCK" in report, "duplicate virtual clock warning missing")
    require("Author: Howard" in sdc and "Author: Howard" in report, "artifact author metadata missing")
    require("u_edge_manual_o" in sdc, "manual overlay clock was not assembled into final SDC")
    require(by_name["u_edge_manual_o"]["source_type"] == "manual_overlay", "manual inventory source_type missing")
    require(by_name["u_edge_manual_o"]["final_sdc_digest"], "final SDC digest missing from active inventory")
    require(by_name["u_pll_core_clk_o"]["root_source"] == "top/sys_clk_pad", "generated root source was not traced to top")
    require("matched instance 'u_edge' by case/space-insensitive fallback" in report, "sheet fallback warning missing")
    require("port workbook sheet 'u_orphan' does not match any inst_name; ignored" in report, "orphan sheet warning missing")
    require("not present in pending and no previous_removed" not in report, "pending rerun was not idempotent")
    require("u_pll output core_clk_o" in removed and "u_edge output gen_o" in removed, "removed log missing expected clock ports")
    require("u_edge output manual_o" in removed, "manual output clock did not consume pending")
    require("u_pll output bus_clk_o[1]" in removed and "u_fab0 input fab_bus_clk_i[0]" in removed, "bit-level removed log missing expected clock ports")
    require((d / "00_harden_port_inventory" / "pending" / "u_pll.ports").read_text(encoding="utf-8") == "input cfg_i\n", "u_pll pending did not retain only non-clock port")
    require((d / "00_harden_port_inventory" / "pending" / "u_fab0.ports").read_text(encoding="utf-8") == "input fab_bus_clk_i[1]\noutput data_o\n", "u_fab0 pending did not retain only uncovered bit/non-clock ports")
    return d


def build_bad_source_case(d):
    clean_dir(d)
    pd.DataFrame([
        {"module_name": "bad_src_mod", "inst_name": "u_bad_src", "owner": "eve", "file_path": ""},
    ]).to_excel(d / "info_all.xlsx", index=False)
    with pd.ExcelWriter(str(d / "port_eve.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Input": "ref_i", "Input Width": 1, "From Whom": "top.ref_pad"},
            {"Output": "gen_o", "Output Width": 1},
        ]).to_excel(writer, sheet_name="u_bad_src", index=False)
    (d / "bad_src_mod.sdc").write_text(
        "create_clock -name local_ref -period 10.000 [get_ports ref_i]\n"
        "create_generated_clock -name bad_gen -source [get_ports ref_typo] -divide_by 2 [get_ports gen_o]\n",
        encoding="utf-8",
    )


def build_multi_target_case(d):
    clean_dir(d)
    pd.DataFrame([
        {"module_name": "multi_mod", "inst_name": "u_multi", "owner": "eve", "file_path": ""},
    ]).to_excel(d / "info_all.xlsx", index=False)
    with pd.ExcelWriter(str(d / "port_eve.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Input": "clk_a", "Input Width": 1, "From Whom": "top.clk_a_pad"},
            {"Input": "clk_b", "Input Width": 1, "From Whom": "top.clk_b_pad"},
        ]).to_excel(writer, sheet_name="u_multi", index=False)
    (d / "multi_mod.sdc").write_text(
        "create_clock -period 10.000 [get_ports {clk_a clk_b}]\n",
        encoding="utf-8",
    )


def build_missing_source_case(d):
    clean_dir(d)
    pd.DataFrame([
        {"module_name": "missing_src_mod", "inst_name": "u_missing", "owner": "eve", "file_path": ""},
    ]).to_excel(d / "info_all.xlsx", index=False)
    with pd.ExcelWriter(str(d / "port_eve.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Output": "gen_o", "Output Width": 1},
        ]).to_excel(writer, sheet_name="u_missing", index=False)
    (d / "missing_src_mod.sdc").write_text(
        "create_generated_clock -name no_source [get_ports gen_o]\n",
        encoding="utf-8",
    )


def build_internal_pin_source_case(d):
    clean_dir(d)
    pd.DataFrame([
        {"module_name": "internal_src_mod", "inst_name": "u_internal", "owner": "eve", "file_path": ""},
    ]).to_excel(d / "info_all.xlsx", index=False)
    with pd.ExcelWriter(str(d / "port_eve.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Input": "ref_i", "Input Width": 1, "From Whom": "top.ref_pad"},
            {"Output": "gen_o", "Output Width": 1},
        ]).to_excel(writer, sheet_name="u_internal", index=False)
    (d / "internal_src_mod.sdc").write_text(
        "create_generated_clock -name internal_gen -source [get_pins internal/clk] -divide_by 2 [get_ports gen_o]\n",
        encoding="utf-8",
    )


def build_unknown_target_case(d):
    clean_dir(d)
    pd.DataFrame([
        {"module_name": "unknown_target_mod", "inst_name": "u_unknown", "owner": "eve", "file_path": ""},
    ]).to_excel(d / "info_all.xlsx", index=False)
    with pd.ExcelWriter(str(d / "port_eve.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Input": "ref_i", "Input Width": 1, "From Whom": "top.ref_pad"},
        ]).to_excel(writer, sheet_name="u_unknown", index=False)
    (d / "unknown_target_mod.sdc").write_text(
        "create_clock -name typo -period 10.000 [get_ports typo_o]\n",
        encoding="utf-8",
    )


def build_manual_missing_reference_case(d):
    clean_dir(d)
    pd.DataFrame([
        {"module_name": "manual_mod", "inst_name": "u_manual", "owner": "eve", "file_path": ""},
    ]).to_excel(d / "info_all.xlsx", index=False)
    with pd.ExcelWriter(str(d / "port_eve.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Input": "ref_i", "Input Width": 1, "From Whom": "top.ref_pad"},
            {"Output": "manual_o", "Output Width": 1},
        ]).to_excel(writer, sheet_name="u_manual", index=False)
    (d / "manual_mod.sdc").write_text(
        "create_clock -name local_ref -period 10.000 [get_ports ref_i]\n",
        encoding="utf-8",
    )
    (d / "01_soc_clocks_manual.sdc").write_text(
        "create_generated_clock -name u_manual_manual_o -source [get_clocks missing_clock] "
        "-divide_by 2 [get_pins u_manual/manual_o]\n",
        encoding="utf-8",
    )


def run_target_layout_case():
    root = WORK / "target_layout"
    inputs = root / "inputs"
    build_positive_case(inputs)
    legacy_00 = inputs / "00_harden_port_inventory"
    target_00 = root / "00_middle"
    target_00.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy_00 / "connection_inventory.csv"), str(target_00 / "connection_inventory.csv"))
    pending = target_00 / "scenario" / "common" / "pending"
    pending.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy_00 / "pending"), str(pending))
    shutil.rmtree(str(legacy_00))
    write_harden_sdc_manifest(root, [
        {
            "inst_name": "u_fab0", "module_name": "fab",
            "sdc_path": "inputs/fab.sdc", "availability_status": "available",
        },
        {
            "inst_name": "u_pll", "module_name": "pll_top",
            "sdc_path": "inputs/pll_top.sdc", "availability_status": "available",
        },
        {
            "inst_name": "u_edge", "module_name": "edge_mod",
            "sdc_path": "inputs/edge_mod.sdc", "availability_status": "available",
        },
    ])
    result = sh([EX01, "--run-root", root, "--debug"], BASE)
    require(result.returncode == 0, "target layout run failed:\n%s\n%s" % (result.stdout, result.stderr))
    require(result.stdout.count("Author: Howard") == 1, "target stdout author marker missing or duplicated")
    sdc = root / "01_result" / "common" / "01_soc_clocks.sdc"
    inventory = root / "01_middle" / "common" / "clock_inventory.csv"
    assembled = root / "01_middle" / "assembled" / "common" / "clock_inventory.csv"
    meta = root / "01_middle" / "assembled" / "common" / "clock_inventory.meta"
    report = root / "01_result" / "reports" / "clock_check_report.txt"
    for path in (sdc, inventory, assembled, meta, report):
        require(path.is_file(), "target artifact missing: %s" % path)
    payload = json.loads(meta.read_text(encoding="utf-8"))
    require(payload["scenario"] == "common" and payload["clock_count"] > 0, "assembled metadata invalid")
    require(payload["run_completeness"] == "complete", "complete target metadata missing")
    require((root / "01_middle" / "scenario" / "common" / "removed_log" / "01_soc_clocks.removed").is_file(), "target removed log missing")
    debug = root / "01_middle" / "debug" / "01_soc_clocks"
    for name in ("run_context.json", "manifest_decisions.csv", "clock_records_debug.csv", "messages.log", "repro_command.txt"):
        require((debug / name).is_file(), "debug artifact missing: %s" % name)
    debug_payload = json.loads((debug / "run_context.json").read_text(encoding="utf-8"))
    require(debug_payload["run_completeness"] == "complete", "debug completeness missing")


def build_partial_target_case(root):
    clean_dir(root)
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    pd.DataFrame([
        {"module_name": "src_mod", "inst_name": "u_src", "owner": "eve", "file_path": ""},
        {"module_name": "sink_mod", "inst_name": "u_sink", "owner": "eve", "file_path": ""},
    ]).to_excel(inputs / "info_all.xlsx", index=False)
    with pd.ExcelWriter(str(inputs / "port_eve.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Output": "clk_o", "Output Width": 1},
        ]).to_excel(writer, sheet_name="u_src", index=False)
        port_sheet([
            {"Input": "clk_i", "Input Width": 1, "From Whom": "u_src.clk_o"},
        ]).to_excel(writer, sheet_name="u_sink", index=False)
    (inputs / "sink_mod.sdc").write_text(
        "create_clock -name sink_clk -period 10.000 [get_ports clk_i]\n",
        encoding="utf-8",
    )
    conn = root / "00_middle" / "connection_inventory.csv"
    conn.parent.mkdir(parents=True, exist_ok=True)
    conn.write_text(
        "connection_id,connection_type,src_instance,src_direction,src_port,src_bit_index,src_endpoint_key,"
        "dst_instance,dst_direction,dst_port,dst_bit_index,dst_endpoint_key,validation_status\n"
        "CONN_SRC_SINK,clock_connection,u_src,output,clk_o,,u_src:output:clk_o,"
        "u_sink,input,clk_i,,u_sink:input:clk_i,matched\n",
        encoding="utf-8",
    )
    pending = root / "00_middle" / "scenario" / "common" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "u_src.ports").write_text("output clk_o\n", encoding="utf-8")
    (pending / "u_sink.ports").write_text("input clk_i\n", encoding="utf-8")
    write_harden_sdc_manifest(root, [
        {
            "inst_name": "u_src", "module_name": "src_mod",
            "sdc_path": "inputs/src_mod.sdc", "availability_status": "missing",
            "note": "owner delivery pending",
        },
        {
            "inst_name": "u_sink", "module_name": "sink_mod",
            "sdc_path": "inputs/sink_mod.sdc", "availability_status": "available",
        },
    ])


def run_partial_target_cases():
    root = WORK / "target_partial"
    build_partial_target_case(root)
    result = sh([EX01, "--run-root", root, "--debug"], BASE)
    require(result.returncode == 0, "partial target run failed:\n%s\n%s" % (result.stdout, result.stderr))
    report = (root / "01_result" / "reports" / "clock_check_report.txt").read_text(encoding="utf-8")
    require("Run completeness: partial" in report, "partial completeness missing from report")
    require("CLOCK_SOURCE_SDC_MISSING" in report, "missing upstream clock todo missing")
    rows = list(csv.DictReader((root / "01_middle" / "common" / "clock_inventory.csv").open(encoding="utf-8-sig")))
    require(any(row["final_action"] == "missing_sdc" and row["inst_name"] == "u_src" for row in rows), "missing instance evidence record absent")
    require(any(row["final_action"] == "incomplete_missing_sdc" and row["inst_name"] == "u_sink" for row in rows), "dependent sink was not marked incomplete")
    require((root / "00_middle" / "scenario" / "common" / "pending" / "u_src.ports").read_text(encoding="utf-8") == "output clk_o\n", "missing source pending was consumed")
    require((root / "00_middle" / "scenario" / "common" / "pending" / "u_sink.ports").read_text(encoding="utf-8") == "input clk_i\n", "incomplete sink pending was consumed")

    strict_root = WORK / "target_partial_strict"
    build_partial_target_case(strict_root)
    strict = sh([EX01, "--run-root", strict_root, "--require-complete-harden-sdc"], BASE)
    require(strict.returncode == 1, "strict partial target should fail")
    strict_report = (strict_root / "01_result" / "reports" / "clock_check_report.txt").read_text(encoding="utf-8")
    require("HARDEN_SDC_COMPLETENESS_REQUIRED" in strict_report, "strict completeness error missing")
    require("PENDING_UPDATE_SKIPPED_DUE_TO_ERRORS" in strict_report, "strict run did not protect pending")
    require((strict_root / "00_middle" / "scenario" / "common" / "pending" / "u_sink.ports").read_text(encoding="utf-8") == "input clk_i\n", "strict error run modified pending")


def run_missing_manifest_case():
    root = WORK / "target_missing_manifest"
    build_partial_target_case(root)
    manifest_dir = root / "00_middle" / "scenario" / "common"
    (manifest_dir / "harden_sdc_manifest.csv").unlink()
    result = sh([EX01, "--run-root", root, "--no-update-pending"], BASE)
    require(result.returncode == 1, "missing target manifest should fail")
    report = (root / "01_result" / "reports" / "clock_check_report.txt").read_text(encoding="utf-8")
    require("HARDEN_SDC_MANIFEST_MISSING" in report, "missing manifest error absent")


def build_sdc_update_case(root, period):
    clean_dir(root)
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    pd.DataFrame([
        {"module_name": "clk_mod", "inst_name": "u_clk", "owner": "eve", "file_path": ""},
    ]).to_excel(inputs / "info_all.xlsx", index=False)
    with pd.ExcelWriter(str(inputs / "port_eve.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Input": "ref_i", "Input Width": 1, "From Whom": "top.ref_pad"},
        ]).to_excel(writer, sheet_name="u_clk", index=False)
    (inputs / "clk_mod.sdc").write_text(
        "create_clock -name ref_clk -period %s [get_ports ref_i]\n" % period,
        encoding="utf-8",
    )
    conn = root / "00_middle" / "connection_inventory.csv"
    conn.parent.mkdir(parents=True, exist_ok=True)
    conn.write_text(
        "connection_id,connection_type,src_instance,src_direction,src_port,src_bit_index,src_endpoint_key,"
        "dst_instance,dst_direction,dst_port,dst_bit_index,dst_endpoint_key,validation_status\n"
        "CONN_REF,clock_connection,top,input,ref_pad,,top:input:ref_pad,u_clk,input,ref_i,,u_clk:input:ref_i,matched\n",
        encoding="utf-8",
    )
    pending = root / "00_middle" / "scenario" / "common" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "u_clk.ports").write_text("input ref_i\n", encoding="utf-8")
    write_harden_sdc_manifest(root, [
        {
            "inst_name": "u_clk", "module_name": "clk_mod",
            "sdc_path": "inputs/clk_mod.sdc", "availability_status": "available",
        },
    ])


def run_sdc_update_rerun_case():
    before = WORK / "target_sdc_before"
    after = WORK / "target_sdc_after"
    build_sdc_update_case(before, "10.000")
    build_sdc_update_case(after, "12.000")
    before_result = sh([EX01, "--run-root", before], BASE)
    after_result = sh([EX01, "--run-root", after], BASE)
    require(before_result.returncode == 0 and after_result.returncode == 0, "SDC update rerun case failed")
    before_sdc = (before / "01_result" / "common" / "01_soc_clocks.sdc").read_text(encoding="utf-8")
    after_sdc = (after / "01_result" / "common" / "01_soc_clocks.sdc").read_text(encoding="utf-8")
    require("-period 10.000" in before_sdc and "-period 12.000" in after_sdc, "updated SDC period not reflected")
    require(before_sdc != after_sdc, "independent rerun did not expose SDC output difference")


def run_diagnose_only_case():
    root = WORK / "target_diagnose_only"
    build_partial_target_case(root)
    result = sh([EX01, "--run-root", root, "--diagnose-only", "--debug-verbose"], BASE)
    require(result.returncode == 0, "diagnose-only run failed:\n%s\n%s" % (result.stdout, result.stderr))
    require(not (root / "01_result" / "common" / "01_soc_clocks.sdc").exists(), "diagnose-only wrote official SDC")
    require((root / "01_result" / "reports" / "clock_check_report.txt").is_file(), "diagnose-only report missing")
    require((root / "01_middle" / "debug" / "01_soc_clocks" / "run_context.json").is_file(), "diagnose-only debug bundle missing")
    require("DEBUG_CLOCK:" in result.stdout, "debug-verbose clock trace missing")


def run_legacy_partial_case():
    root = WORK / "legacy_partial"
    clean_dir(root)
    pd.DataFrame([
        {"module_name": "available_mod", "inst_name": "u_available", "owner": "eve", "file_path": ""},
        {"module_name": "missing_mod", "inst_name": "u_missing_legacy", "owner": "eve", "file_path": ""},
    ]).to_excel(root / "info_all.xlsx", index=False)
    with pd.ExcelWriter(str(root / "port_eve.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Input": "ref_i", "Input Width": 1, "From Whom": "top.ref_pad"},
        ]).to_excel(writer, sheet_name="u_available", index=False)
        port_sheet([
            {"Output": "clk_o", "Output Width": 1},
        ]).to_excel(writer, sheet_name="u_missing_legacy", index=False)
    (root / "available_mod.sdc").write_text(
        "create_clock -name ref_clk -period 10.000 [get_ports ref_i]\n",
        encoding="utf-8",
    )
    result = sh([EX01, "--no-update-pending"], root)
    require(result.returncode == 0, "legacy partial run should continue")
    report = (root / "clock_check_report.txt").read_text(encoding="utf-8")
    require("Run completeness: partial" in report and "HARDEN_SDC_MISSING" in report, "legacy partial evidence missing")
    strict = sh([EX01, "--no-update-pending", "--require-complete-harden-sdc"], root)
    require(strict.returncode == 1, "legacy strict partial should fail")


def run_not_required_target_case():
    root = WORK / "target_not_required"
    clean_dir(root)
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    pd.DataFrame([
        {"module_name": "special_obj", "inst_name": "u_special", "owner": "eve", "file_path": ""},
    ]).to_excel(inputs / "info_all.xlsx", index=False)
    with pd.ExcelWriter(str(inputs / "port_eve.xlsx"), engine="xlsxwriter") as writer:
        port_sheet([
            {"Output": "status_o", "Output Width": 1},
        ]).to_excel(writer, sheet_name="u_special", index=False)
    conn = root / "00_middle" / "connection_inventory.csv"
    conn.parent.mkdir(parents=True, exist_ok=True)
    conn.write_text(
        "connection_id,connection_type,src_instance,src_direction,src_port,src_bit_index,src_endpoint_key,"
        "dst_instance,dst_direction,dst_port,dst_bit_index,dst_endpoint_key,validation_status\n",
        encoding="utf-8",
    )
    pending = root / "00_middle" / "scenario" / "common" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "u_special.ports").write_text("output status_o\n", encoding="utf-8")
    write_harden_sdc_manifest(root, [
        {
            "inst_name": "u_special", "module_name": "special_obj",
            "availability_status": "not_required", "note": "non-harden integration object",
        },
    ])
    result = sh([EX01, "--run-root", root], BASE)
    require(result.returncode == 0, "not_required target run failed")
    report = (root / "01_result" / "reports" / "clock_check_report.txt").read_text(encoding="utf-8")
    require("Run completeness: complete" in report and "Harden SDC not_required: 1" in report, "not_required completeness incorrect")
    require((pending / "u_special.ports").read_text(encoding="utf-8") == "output status_o\n", "not_required pending was consumed")


def run_negative_case(name, builder, expected_message, check_inventory=False):
    d = WORK / name
    builder(d)
    result = sh([EX01, "--no-update-pending"], d)
    require(result.returncode == 1, "%s should fail but returned %s" % (name, result.returncode))
    report = (d / "clock_check_report.txt").read_text(encoding="utf-8")
    require(expected_message in report, "%s report missing %s" % (name, expected_message))
    if check_inventory:
        rows = list(csv.DictReader((d / "clock_inventory.csv").open(encoding="utf-8-sig")))
        skipped_ports = sorted(row["port_name"] for row in rows if row["final_action"] == "skipped")
        require(skipped_ports == ["clk_a", "clk_b"], "multi-target skipped inventory is wrong: %s" % skipped_ports)


def main():
    clean_dir(WORK)
    positive_dir = run_positive_case()
    run_negative_case(
        "bad_source",
        build_bad_source_case,
        "CLOCK_GENERATED_SOURCE_NOT_IN_OWNER_SHEET",
    )
    run_negative_case(
        "multi_target",
        build_multi_target_case,
        "CLOCK_MULTI_TARGET_NOT_SUPPORTED",
        check_inventory=True,
    )
    run_negative_case(
        "missing_source",
        build_missing_source_case,
        "CLOCK_GENERATED_MISSING_SOURCE",
    )
    run_negative_case(
        "internal_pin_source",
        build_internal_pin_source_case,
        "CLOCK_GENERATED_SOURCE_INTERNAL_PIN",
    )
    run_negative_case(
        "unknown_target",
        build_unknown_target_case,
        "CLOCK_TARGET_NOT_IN_OWNER_SHEET",
    )
    run_negative_case(
        "manual_missing_reference",
        build_manual_missing_reference_case,
        "CLOCK_MANUAL_REFERENCE_NOT_IN_UNIVERSE",
    )
    run_target_layout_case()
    run_partial_target_cases()
    run_missing_manifest_case()
    run_sdc_update_rerun_case()
    run_diagnose_only_case()
    run_legacy_partial_case()
    run_not_required_target_case()
    print("01 complex regression: PASS")
    print("  positive artifacts: %s" % positive_dir)
    print("  negative cases: bad_source, multi_target, missing_source, internal_pin_source, unknown_target, manual_missing_reference")
    print("  target layout: PASS")
    print("  partial/strict/manifest/rerun-diff/debug target cases: PASS")
    print("  legacy partial/strict cases: PASS")
    print("  target not_required case: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
