#!/usr/bin/env python3
"""Rebuild and run the complete target-layout 01 -> 02 demo."""

import json
import subprocess
import sys
from pathlib import Path

from build_case import RUN_ROOT, build_case
from fill_budget import fill_budget


BASE = Path(__file__).resolve().parent
SCRIPTS = BASE.parent.parent
EX01 = SCRIPTS / "01_soc_clocks/01_extract_soc_clocks.py"
EX02 = SCRIPTS / "02_soc_clock_timing/02_extract_soc_clock_timing.py"


def run(command):
    print("Running: %s" % " ".join(str(item) for item in command), flush=True)
    return subprocess.run([str(item) for item in command], cwd=str(BASE))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    build_case()

    stage01 = run([sys.executable, EX01, "--run-root", RUN_ROOT, "--scenario", "common"])
    require(stage01.returncode == 0, "01 stage failed with exit code %s" % stage01.returncode)

    stage02_first = run(
        [
            sys.executable,
            EX02,
            "--run-root",
            RUN_ROOT,
            "-scenario",
            "common",
            "-stage",
            "prects",
            "-corner",
            "ss_125",
        ]
    )
    require(stage02_first.returncode == 1, "02 first run should create the review workbook and stop")
    fill_budget()

    stage02_final = run(
        [
            sys.executable,
            EX02,
            "--run-root",
            RUN_ROOT,
            "-scenario",
            "common",
            "-stage",
            "prects",
            "-corner",
            "ss_125",
        ]
    )
    require(stage02_final.returncode == 0, "02 final generation failed with exit code %s" % stage02_final.returncode)

    clock_sdc = RUN_ROOT / "01_result/common/01_soc_clocks.sdc"
    inventory = RUN_ROOT / "01_middle/assembled/common/clock_inventory.csv"
    inventory_meta = RUN_ROOT / "01_middle/assembled/common/clock_inventory.meta"
    timing_form = RUN_ROOT / "02_middle/02_soc_clock_timing_budget_prects.xlsx"
    timing_sdc = RUN_ROOT / "02_result/common/02_soc_clock_timing_prects_ss_125.sdc"
    timing_report = RUN_ROOT / "02_result/reports/clock_timing_check_report_common_prects_ss_125.txt"
    resolved = RUN_ROOT / "02_middle/resolved/common_prects_ss_125.manifest"
    for path in (clock_sdc, inventory, inventory_meta, timing_form, timing_sdc, timing_report, resolved):
        require(path.is_file(), "expected artifact missing: %s" % path)

    payload = json.loads(resolved.read_text(encoding="utf-8"))
    emitted = [row["clock_name"] for row in payload["winning_rows"] if row["emitted"]]
    print("\n01 -> 02 chain completed")
    print("Run root       : %s" % RUN_ROOT)
    print("01 clock SDC   : %s" % clock_sdc)
    print("01 inventory   : %s" % inventory)
    print("02 timing form : %s" % timing_form)
    print("02 timing SDC  : %s" % timing_sdc)
    print("02 report      : %s" % timing_report)
    print("Resolved clocks: %s" % ", ".join(emitted))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
