#!/usr/bin/env python3
"""
One-shot regression for the SoC SDC 01 -> 02 -> 03 chain.

Layout (recreated under work/ each run):
  work/01_soc_clocks/        run 01, produce clock_inventory.csv + 01 sdc
  work/02_soc_clock_timing/  fill budgets, run 02 across stage/scenario/corner
  work/03_soc_clock_groups/  fill rules, run 03 + coverage

It collects deterministic TEXT artifacts (sdc / csv / normalized reports /
coverage extracts) into work/artifacts and diffs them against expected/.

Usage:
  python3 run_regression.py            # compare against expected/ (fail on diff)
  python3 run_regression.py --update   # (re)write expected/ baseline
"""
import argparse
import csv
import io
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

BASE = Path(__file__).resolve().parent
SOC = BASE.parent
EX01 = SOC / "01_soc_clocks" / "extract_soc_01_clocks.py"
EX02 = SOC / "02_soc_clock_timing" / "extract_soc_02_clock_timing.py"
EX03 = SOC / "03_soc_clock_groups" / "extract_soc_03_clock_groups.py"
WORK = BASE / "work"
EXP = BASE / "expected"
ART = WORK / "artifacts"

REQ = ["Parameter", "Inout", "Inout Width", "Inout Connectivity", "Inout Name",
       "Input", "Input Width", "Input Used Width", "From Whom",
       "Output", "Output Width", "Output Used Width", "To Top"]


def sh(cmd, cwd):
    return subprocess.run([sys.executable, *cmd], cwd=str(cwd),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)


def port_sheet(rows):
    df = pd.DataFrame(rows)
    for c in REQ:
        if c not in df.columns:
            df[c] = ""
    return df[REQ].fillna("")


# ----------------------------------------------------------------------------
# 01: build the demo2 complex topology and run extraction
# ----------------------------------------------------------------------------
def run_01(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"module_name": "pll_top", "inst_name": "u_pll",   "owner": "alice", "file_path": ""},
        {"module_name": "fab",     "inst_name": "u_fab0",  "owner": "alice", "file_path": ""},
        {"module_name": "fab",     "inst_name": "u_fab1",  "owner": "alice", "file_path": ""},
        {"module_name": "periph",  "inst_name": "u_periph", "owner": "bob",  "file_path": ""},
    ]).to_excel(d / "info_all.xlsx", index=False)

    with pd.ExcelWriter(d / "port_alice.xlsx", engine="xlsxwriter") as w:
        port_sheet([
            {"Input": "ref_clk_in", "Input Width": 1, "From Whom": "top.sys_clk_pad"},
            {"Output": "core_clk_o", "Output Width": 1},
            {"Output": "bus_clk_o", "Output Width": 1},
        ]).to_excel(w, sheet_name="u_pll", index=False)
        for inst in ("u_fab0", "u_fab1"):
            port_sheet([
                {"Input": "fab_clk_i", "Input Width": 1, "From Whom": "u_pll.core_clk_o"},
                {"Output": "fab_clk_o", "Output Width": 1},
            ]).to_excel(w, sheet_name=inst, index=False)
    with pd.ExcelWriter(d / "port_bob.xlsx", engine="xlsxwriter") as w:
        port_sheet([
            {"Input": "clk_i", "Input Width": 1, "From Whom": "u_fab0.fab_clk_o"},
            {"Input": "ref2_i", "Input Width": 1, "From Whom": "top.aux_clk_pad"},
            {"Input": "scan_mode_clk", "Input Width": 1, "From Whom": "top.scan_clk_pad"},
            {"Output": "clk_o", "Output Width": 1},
        ]).to_excel(w, sheet_name="u_periph", index=False)

    (d / "pll_top.sdc").write_text(
        "create_clock -name pll_ref -period 20.000 [get_ports ref_clk_in]\n"
        "create_generated_clock -name pll_core -source [get_ports ref_clk_in] -multiply_by 4 [get_ports core_clk_o]\n"
        "create_generated_clock -name pll_bus  -source [get_ports ref_clk_in] -multiply_by 2 [get_ports bus_clk_o]\n")
    (d / "fab.sdc").write_text(
        "create_clock -name fab_in -period 5.000 [get_ports fab_clk_i]\n"
        "create_generated_clock -name fab_out -source [get_ports fab_clk_i] -combinational [get_ports fab_clk_o]\n")
    (d / "periph.sdc").write_text(
        "create_clock -name periph_in   -period 5.000  [get_ports clk_i]\n"
        "create_clock -name periph_ref2 -period 40.000 [get_ports ref2_i]\n"
        "create_clock -name scan_clk    -period 50.000 [get_ports scan_mode_clk]\n"
        "create_generated_clock -name periph_out -source [get_ports clk_i] -combinational [get_ports clk_o]\n")
    (d / "virtual_clocks.csv").write_text(
        "clock_name,period,waveform,note\n"
        "v_ddr_ref,2.500,,DDR external reference\n"
        "v_pcie_ref,10.000,{0 5},PCIe external reference\n")

    r = sh([str(EX01)], cwd=d)
    assert r.returncode == 0, f"01 failed:\n{r.stdout}\n{r.stderr}"


def active_clocks(inv_csv: Path):
    out = {}
    for row in csv.DictReader(inv_csv.open(encoding="utf-8-sig")):
        if row["final_action"].startswith("emit_"):
            out[row["clock_name"]] = row["clock_kind"]
    return out


# ----------------------------------------------------------------------------
# 02: fill budgets and run the stage/scenario/corner matrix
# ----------------------------------------------------------------------------
def budget_values(kind, corner):
    k = 1.0 if corner == "ss_125" else 0.6
    if "virtual" in kind:
        return dict(setup_uncertainty=round(0.05 * k, 3), hold_uncertainty=0.02)
    if "generated_combinational" in kind:
        return dict(setup_uncertainty=round(0.11 * k, 3), hold_uncertainty=round(0.035 * k, 3),
                    network_latency_early=round(0.25 * k, 3), network_latency_late=round(0.60 * k, 3))
    if "generated" in kind:
        return dict(setup_uncertainty=round(0.12 * k, 3), hold_uncertainty=round(0.04 * k, 3),
                    network_latency_early=round(0.30 * k, 3), network_latency_late=round(0.70 * k, 3),
                    transition_min=0.03, transition_max=round(0.12 * k, 3))
    return dict(setup_uncertainty=round(0.10 * k, 3), hold_uncertainty=round(0.03 * k, 3),
                source_latency_early=round(0.10 * k, 3), source_latency_late=round(0.24 * k, 3),
                network_latency_early=round(0.28 * k, 3), network_latency_late=round(0.65 * k, 3),
                transition_min=0.03, transition_max=round(0.11 * k, 3))


def fill_budget(form: Path, stage: str, clocks: dict, propagated: bool):
    wb = load_workbook(form)
    ws = wb["clock_budget"]
    hdr, col = None, {}
    for r in range(1, 8):
        names = {ws.cell(r, c).value: c for c in range(1, ws.max_column + 1) if ws.cell(r, c).value}
        if "clock_name" in names:
            hdr, col = r, names
            break

    def setc(r, **kv):
        for k, v in kv.items():
            ws.cell(r, col[k], v)

    # fill auto-created common/ss_125 rows
    for r in range(hdr + 1, ws.max_row + 1):
        cn = ws.cell(r, col["clock_name"]).value
        if cn in clocks:
            if propagated:
                setc(r, apply="yes", sync_status="OK", propagated="yes",
                     setup_uncertainty=0.05, hold_uncertainty=0.02)
            else:
                setc(r, apply="yes", sync_status="OK", **budget_values(clocks[cn], "ss_125"))

    def last():
        lr = hdr
        for r in range(hdr + 1, ws.max_row + 1):
            if any(ws.cell(r, c).value not in (None, "") for c in col.values()):
                lr = r
        return lr

    if not propagated:
        # func override on the PLL core clock
        r = last() + 1
        setc(r, scenario="func", stage=stage, corner="ss_125", clock_name="u_pll_core_clk_o",
             setup_uncertainty=0.15, hold_uncertainty=0.05,
             network_latency_early=0.30, network_latency_late=0.70,
             transition_min=0.03, transition_max=0.12, apply="yes", sync_status="OK")
    wb.save(form)


def run_02(d: Path, inv: Path, clocks: dict):
    d.mkdir(parents=True, exist_ok=True)
    # prects: gate -> fill -> generate common + func
    sh([str(EX02), "-scenario", "common", "-stage", "prects", "-corner", "ss_125"], cwd=d)
    fill_budget(d / "02_soc_clock_timing_budget_prects.xlsx", "prects", clocks, propagated=False)
    for scen in ("common", "func"):
        r = sh([str(EX02), "-scenario", scen, "-stage", "prects", "-corner", "ss_125"], cwd=d)
        assert r.returncode == 0, f"02 prects {scen} failed:\n{r.stdout}\n{r.stderr}"
    # postcts: gate -> fill (propagated) -> generate common
    sh([str(EX02), "-scenario", "common", "-stage", "postcts", "-corner", "ss_125"], cwd=d)
    fill_budget(d / "02_soc_clock_timing_budget_postcts.xlsx", "postcts", clocks, propagated=True)
    r = sh([str(EX02), "-scenario", "common", "-stage", "postcts", "-corner", "ss_125"], cwd=d)
    assert r.returncode == 0, f"02 postcts failed:\n{r.stdout}\n{r.stderr}"


# ----------------------------------------------------------------------------
# 03: fill clock-group rules and run common
# ----------------------------------------------------------------------------
def run_03(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    sh([str(EX03), "-scenario", "common"], cwd=d)  # gate creates form
    form = d / "03_soc_clock_groups.xlsx"
    wb = load_workbook(form)
    ws = wb["clock_group_rules"]
    hdr, col = None, {}
    for r in range(1, 8):
        names = {ws.cell(r, c).value: c for c in range(1, ws.max_column + 1) if ws.cell(r, c).value}
        if "group_id" in names:
            hdr, col = r, names
            break

    def add(row, **kv):
        for k, v in kv.items():
            ws.cell(row, col[k], v)

    add(hdr + 1, scenario="common", group_id="CG_ASYNC_CORE_AUX", relation_type="asynchronous",
        group_1_clocks="u_pll_core_clk_o", group_2_clocks="top_aux_clk_pad",
        apply="yes", review_status="approved", cdc_required="yes",
        basis="CDC: core domain async to aux")
    add(hdr + 2, scenario="common", group_id="CG_ASYNC_BUS_AUX", relation_type="asynchronous",
        group_1_clocks="u_pll_bus_clk_o", group_2_clocks="top_aux_clk_pad",
        apply="yes", review_status="approved", cdc_required="yes",
        basis="CDC: bus async to aux")
    wb.save(form)
    r = sh([str(EX03), "-scenario", "common"], cwd=d)
    assert r.returncode == 0, f"03 failed:\n{r.stdout}\n{r.stderr}"


# ----------------------------------------------------------------------------
# artifact collection + normalization
# ----------------------------------------------------------------------------
def norm(text: str) -> str:
    return text.replace(str(WORK), "<WORK>")


def xlsx_sheet_to_csv(path: Path, sheet: str, cols, start_row=5) -> str:
    ws = load_workbook(path)[sheet]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    rows = []
    for r in range(start_row, ws.max_row + 1):
        vals = [ws.cell(r, c).value for c in range(1, len(cols) + 1)]
        if all(v in (None, "") for v in vals):
            continue
        rows.append(["" if v is None else str(v).replace("\n", " ") for v in vals])
    rows.sort()
    for row in rows:
        w.writerow(row)
    return buf.getvalue()


def collect(name: str, text: str):
    p = ART / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def collect_artifacts(w01, w02, w03):
    if ART.exists():
        shutil.rmtree(ART)
    ART.mkdir(parents=True)
    # 01
    collect("01/01_soc_clocks.sdc", (w01 / "common/01_soc_clocks.sdc").read_text())
    collect("01/clock_inventory.csv", (w01 / "clock_inventory.csv").read_text())
    collect("01/clock_check_report.txt", norm((w01 / "clock_check_report.txt").read_text()))
    # 02
    for rel in ["common/02_soc_clock_timing_prects_ss_125.sdc",
                "scenarios/func_clock_timing_prects_ss_125.sdc",
                "common/02_soc_clock_timing_postcts_ss_125.sdc"]:
        collect(f"02/{rel}", (w02 / rel).read_text())
    for rep in ["clock_timing_check_report_common_prects_ss_125.txt",
                "clock_timing_check_report_func_prects_ss_125.txt",
                "clock_timing_check_report_common_postcts_ss_125.txt"]:
        collect(f"02/{rep}", norm((w02 / rep).read_text()))
    # 03
    collect("03/03_soc_clock_groups.sdc", (w03 / "common/03_soc_clock_groups.sdc").read_text())
    collect("03/clock_group_check_report_common.txt",
            norm((w03 / "clock_group_check_report_common.txt").read_text()))
    cov = w03 / "clock_group_coverage_report_common.xlsx"
    collect("03/cov_uncovered.csv", xlsx_sheet_to_csv(
        cov, "uncovered_cross_root_pairs",
        ["clock_a", "clock_b", "tree_root_a", "tree_root_b", "root_source_a", "root_source_b", "clock_kind_a"]))
    collect("03/cov_rule_effective_groups.csv", xlsx_sheet_to_csv(
        cov, "rule_effective_groups",
        ["scenario", "group_id", "relation_type", "group_index", "explicit_clocks",
         "auto_added_descendants", "excluded_descendants", "effective_clocks", "review_note"]))
    collect("03/cov_participation.csv", xlsx_sheet_to_csv(
        cov, "clock_participation",
        ["clock_name", "clock_kind", "tree_root", "root_source", "direct_source", "final_action", "group_count"]))


# ----------------------------------------------------------------------------
# diff
# ----------------------------------------------------------------------------
def compare():
    art_files = sorted(p.relative_to(ART).as_posix() for p in ART.rglob("*") if p.is_file())
    exp_files = sorted(p.relative_to(EXP).as_posix() for p in EXP.rglob("*") if p.is_file()) if EXP.exists() else []
    fails = []
    for rel in art_files:
        a = (ART / rel).read_text()
        e_path = EXP / rel
        if not e_path.is_file():
            fails.append((rel, "MISSING in expected/"))
            continue
        if a != e_path.read_text():
            import difflib
            diff = list(difflib.unified_diff(
                e_path.read_text().splitlines(), a.splitlines(),
                fromfile=f"expected/{rel}", tofile=f"work/{rel}", lineterm=""))
            fails.append((rel, "\n".join(diff[:24])))
    for rel in exp_files:
        if rel not in art_files:
            fails.append((rel, "MISSING in work artifacts"))
    return art_files, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="(re)write expected/ baseline")
    args = ap.parse_args()

    if WORK.exists():
        shutil.rmtree(WORK)
    w01, w02, w03 = WORK / "01_soc_clocks", WORK / "02_soc_clock_timing", WORK / "03_soc_clock_groups"

    run_01(w01)
    clocks = active_clocks(w01 / "clock_inventory.csv")
    run_02(w02, w01 / "clock_inventory.csv", clocks)
    run_03(w03)
    collect_artifacts(w01, w02, w03)

    art_files, _ = compare()

    if args.update or not EXP.exists():
        if EXP.exists():
            shutil.rmtree(EXP)
        shutil.copytree(ART, EXP)
        print(f"baseline written: {len(art_files)} artifact(s) -> {EXP}")
        for f in art_files:
            print(f"  + {f}")
        return 0

    _, fails = compare()
    print(f"01->02->03 regression: {len(art_files)} artifact(s) checked")
    if not fails:
        print("RESULT: PASS (all artifacts match expected/)")
        return 0
    print(f"RESULT: FAIL ({len(fails)} mismatch)")
    for rel, detail in fails:
        print(f"\n--- {rel} ---\n{detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
