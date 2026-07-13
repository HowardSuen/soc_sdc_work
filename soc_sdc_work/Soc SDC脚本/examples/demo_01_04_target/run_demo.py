#!/usr/bin/env python3
"""Rebuild and run the complete target-layout 01 -> 04 demo."""

from __future__ import print_function

import csv
import subprocess
import sys
from pathlib import Path

from build_case import RUN_ROOT, build_case
from fill_reviews import fill_02, fill_03, fill_04


BASE = Path(__file__).resolve().parent
SCRIPTS = BASE.parent.parent
EX01 = SCRIPTS / "01_soc_clocks/01_extract_soc_clocks.py"
EX02 = SCRIPTS / "02_soc_clock_timing/02_extract_soc_clock_timing.py"
EX03 = SCRIPTS / "03_soc_clock_groups/03_extract_soc_clock_groups.py"
EX04 = SCRIPTS / "04_soc_io_pads/04_extract_soc_io_pads.py"


def run(command):
    print("Running: %s" % " ".join(str(item) for item in command), flush=True)
    return subprocess.run([str(item) for item in command], cwd=str(BASE))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_ok(command, stage):
    result = run(command)
    require(result.returncode == 0, "%s failed with exit code %s" % (stage, result.returncode))


def run_review_gate(command, stage):
    result = run(command)
    require(result.returncode == 1, "%s first run should create/sync its review workbook" % stage)


def active_clock_names(path):
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        rows = list(csv.DictReader(file_obj))
    return sorted(
        row["clock_name"]
        for row in rows
        if row.get("final_action") in {"emit_top_clock", "emit_output_clock", "emit_virtual_clock"}
    )


def nonempty_lines(path):
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_assembled_preview(paths):
    path = RUN_ROOT / "assembled/common_prects_ss_125.sdc"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 01 -> 04 assembled source preview",
        "# Source order follows the SoC SDC stage order.",
        "",
    ]
    for item in paths:
        lines.append("source %s" % item.relative_to(RUN_ROOT).as_posix())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    build_case()

    run_ok([sys.executable, EX01, "--run-root", RUN_ROOT, "--scenario", "common"], "01")

    command02 = [
        sys.executable, EX02, "--run-root", RUN_ROOT,
        "--scenario", "common", "--stage", "prects", "--corner", "ss_125",
    ]
    run_review_gate(command02, "02")
    fill_02()
    run_ok(command02, "02")

    command03 = [sys.executable, EX03, "--run-root", RUN_ROOT, "--scenario", "common"]
    run_review_gate(command03, "03")
    fill_03()
    run_ok(command03, "03")

    command04 = [sys.executable, EX04, "--run-root", RUN_ROOT, "--scenario", "common"]
    run_review_gate(command04, "04")
    fill_04()
    run_ok(command04, "04")

    clock_sdc = RUN_ROOT / "01_result/common/01_soc_clocks.sdc"
    clock_inventory = RUN_ROOT / "01_middle/assembled/common/clock_inventory.csv"
    timing_sdc = RUN_ROOT / "02_result/common/02_soc_clock_timing_prects_ss_125.sdc"
    group_sdc = RUN_ROOT / "03_result/common/03_soc_clock_groups.sdc"
    relation_map = RUN_ROOT / "03_middle/relation_map/common.csv"
    io_sdc = RUN_ROOT / "04_result/common/04_soc_io_pads.sdc"
    io_report = RUN_ROOT / "04_result/reports/io_pad_check_report_common_all_all.txt"
    final_paths = [clock_sdc, timing_sdc, group_sdc, io_sdc]
    for path in final_paths + [clock_inventory, relation_map, io_report]:
        require(path.is_file(), "expected artifact missing: %s" % path)

    group_text = group_sdc.read_text(encoding="utf-8")
    io_text = io_sdc.read_text(encoding="utf-8")
    require("set_clock_groups -asynchronous" in group_text, "03 async clock group missing")
    for command in ("set_input_delay", "set_output_delay", "set_input_transition", "set_load"):
        require(command in io_text, "04 command missing: %s" % command)
    require("Errors  : 0" in io_report.read_text(encoding="utf-8"), "04 report contains errors")

    pending_root = RUN_ROOT / "00_middle/scenario/common/pending"
    pending_a = nonempty_lines(pending_root / "u_harden_a.ports")
    pending_b = nonempty_lines(pending_root / "u_harden_b.ports")
    require(not pending_a and not pending_b, "01/04 did not fully consume the demo pending ports")

    preview = write_assembled_preview(final_paths)
    clocks = active_clock_names(clock_inventory)
    summary = RUN_ROOT / "chain_summary.txt"
    summary.write_text(
        "01 -> 04 target runtime demo: PASS\n"
        "Active clocks: %s\n"
        "03 relation: system clock tree asynchronous to v_gpio_ref_clk\n"
        "04 pads: uart_rx_pad, uart_tx_pad\n"
        "Pending u_harden_a: empty\n"
        "Pending u_harden_b: empty\n"
        "Assembled preview: %s\n"
        % (", ".join(clocks), preview.relative_to(RUN_ROOT).as_posix()),
        encoding="utf-8",
    )

    print("\n01 -> 04 chain completed")
    print("Run root          : %s" % RUN_ROOT)
    print("Active clocks     : %s" % ", ".join(clocks))
    print("03 relation map   : %s" % relation_map)
    print("04 IO SDC         : %s" % io_sdc)
    print("Assembled preview : %s" % preview)
    print("Pending ports     : all consumed")
    print("Summary           : %s" % summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
