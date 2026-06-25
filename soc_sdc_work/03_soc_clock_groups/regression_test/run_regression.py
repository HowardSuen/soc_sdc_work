#!/usr/bin/env python3
"""Complex regression for 03_extract_soc_clock_groups.py.

The test builds fresh inputs under work_complex/ and checks:
  * first-run workbook creation gate
  * bit-level clock_name handling from 01 clock_inventory.csv
  * domain closure expansion through a bit-level source object
  * relation_type alias normalization to the canonical enum
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
EX03 = SOC / "03_soc_clock_groups" / "03_extract_soc_clock_groups.py"
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


def write_inventory(path):
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
    rows = [
        {
            "inst_name": "u_busclk",
            "port_name": "ref_clk_i[1]",
            "direction": "input",
            "clock_name": "top_ref_clk_pad_bit1",
            "clock_kind": "create_clock",
            "direct_source": "top/ref_clk_pad[1]",
            "root_source": "top/ref_clk_pad[1]",
            "final_action": "emit_top_clock",
        },
        {
            "inst_name": "u_busclk",
            "port_name": "clk_o[1]",
            "direction": "output",
            "clock_name": "u_busclk_clk_o_bit1",
            "clock_kind": "create_generated_clock",
            "direct_source": "u_busclk/ref_clk_i[1]",
            "root_source": "top/ref_clk_pad[1]",
            "final_action": "emit_output_clock",
        },
        {
            "inst_name": "u_aux",
            "port_name": "aux_clk_i",
            "direction": "input",
            "clock_name": "top_aux_clk_pad",
            "clock_kind": "create_clock",
            "direct_source": "top/aux_clk_pad",
            "root_source": "top/aux_clk_pad",
            "final_action": "emit_top_clock",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            full = dict((field, "") for field in fields)
            full.update(row)
            writer.writerow(full)


def header_map(ws):
    for row_idx in range(1, min(ws.max_row, 30) + 1):
        mapping = {}
        for col_idx in range(1, ws.max_column + 1):
            value = ws.cell(row_idx, col_idx).value
            if value:
                mapping[str(value).strip()] = col_idx
        if "group_id" in mapping:
            return row_idx, mapping
    raise AssertionError("clock_group_rules header not found")


def set_row(ws, row_idx, mapping, values):
    for key, value in values.items():
        ws.cell(row_idx, mapping[key], value)


def run_bit_closure_case():
    d = WORK / "bit_closure"
    clean_dir(d)
    write_inventory(d / "clock_inventory.csv")

    first = sh([EX03, "-scenario", "common", "-input", "clock_inventory.csv"], d)
    require(first.returncode == 1, "first 03 run should create workbook and stop")
    require((d / "03_soc_clock_groups.xlsx").is_file(), "03 workbook was not created")

    wb = load_workbook(str(d / "03_soc_clock_groups.xlsx"))
    ws = wb["clock_group_rules"]
    header_row, mapping = header_map(ws)
    set_row(ws, header_row + 1, mapping, {
        "scenario": "common",
        "group_id": "CG_ASYNC_BIT_AUX",
        "relation_type": "async",
        "group_1_clocks": "top_ref_clk_pad_bit1",
        "group_2_clocks": "top_aux_clk_pad",
        "analysis_style": "normal",
        "apply": "yes",
        "review_status": "approved",
        "owner": "sta",
        "basis": "CDC bit clock domain async to aux",
        "cdc_required": "yes",
    })
    wb.save(str(d / "03_soc_clock_groups.xlsx"))

    result = sh([EX03, "-scenario", "common", "-input", "clock_inventory.csv"], d)
    require(result.returncode == 0, "03 bit closure generation failed:\n%s\n%s" % (result.stdout, result.stderr))
    sdc = (d / "common" / "03_soc_clock_groups.sdc").read_text(encoding="utf-8")
    report = (d / "clock_group_check_report_common.txt").read_text(encoding="utf-8")
    require("set_clock_groups -asynchronous" in sdc, "relation_type alias was not canonicalized")
    require(
        "-group [get_clocks {top_ref_clk_pad_bit1 u_busclk_clk_o_bit1}]" in sdc,
        "bit-level descendant was not auto-added to the effective group",
    )
    require("group_1 auto-added descendant clock(s): u_busclk_clk_o_bit1" in report, "auto-added bit descendant not reported")
    require("relation_type async normalized to asynchronous" in report, "canonical relation_type rewrite was not reported")

    rewritten = load_workbook(str(d / "03_soc_clock_groups.xlsx"))["clock_group_rules"]
    _, rewritten_mapping = header_map(rewritten)
    require(
        rewritten.cell(header_row + 1, rewritten_mapping["relation_type"]).value == "asynchronous",
        "relation_type alias was not written back to the workbook",
    )


def main():
    clean_dir(WORK)
    run_bit_closure_case()
    print("03 complex regression: PASS")
    print("  extra cases: bit_closure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
