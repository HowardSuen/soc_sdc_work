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

    rerun = sh([EX01], d)
    require(rerun.returncode == 0, "positive 01 rerun should be idempotent:\n%s\n%s" % (rerun.stdout, rerun.stderr))

    sdc = (d / "common" / "01_soc_clocks.sdc").read_text(encoding="utf-8")
    report = (d / "clock_check_report.txt").read_text(encoding="utf-8")
    removed = (d / "00_harden_port_inventory" / "removed_log" / "01_soc_clocks.removed").read_text(encoding="utf-8")

    require("-source [get_clocks {top_ref_pad}]" in sdc, "get_clocks source was not remapped to SoC clock name")
    require("u_pll_bus_clk_o_bit1" in sdc and "[get_pins {u_pll/bus_clk_o[1]}]" in sdc, "bit output clock was not emitted with canonical bit naming")
    require(sdc.index("u_pll_core_clk_o") < sdc.index("u_fab0_fab_clk_o"), "generated SDC is not dependency ordered")
    require("IGNORED_NON_CLOCK_COMMAND" in report, "non-clock SDC command was not reported")
    require("CLOCK_ADD_OPTION_OUT_OF_SCOPE" in report, "-add warning missing")
    require("matched instance 'u_edge' by case/space-insensitive fallback" in report, "sheet fallback warning missing")
    require("port workbook sheet 'u_orphan' does not match any inst_name; ignored" in report, "orphan sheet warning missing")
    require("not present in pending and no previous_removed" not in report, "pending rerun was not idempotent")
    require("u_pll output core_clk_o" in removed and "u_edge output gen_o" in removed, "removed log missing expected clock ports")
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
    print("01 complex regression: PASS")
    print("  positive artifacts: %s" % positive_dir)
    print("  negative cases: bad_source, multi_target, missing_source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
