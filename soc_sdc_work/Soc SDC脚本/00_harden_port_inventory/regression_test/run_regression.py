#!/usr/bin/env python3
"""Regression tests for 00_harden_port_inventory.py."""

import argparse
import csv
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd


BASE = Path(__file__).resolve().parent
EX00 = BASE.parent.parent / "00_harden_port_inventory.py"
PORT_COLUMNS = [
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


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def row(**values):
    result = {column: "" for column in PORT_COLUMNS}
    result.update(values)
    return result


def run_00(root, scenario, *extra):
    command = [
        sys.executable,
        str(EX00),
        "--run-root",
        str(root),
        "--scenario",
        scenario,
    ] + list(extra)
    return subprocess.run(
        command,
        cwd=str(BASE.parent.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def run_legacy(root, scenario, *extra):
    command = [sys.executable, str(EX00), "--scenario", scenario] + list(extra)
    return subprocess.run(
        command,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path):
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        return list(csv.DictReader(file_obj))


def write_case(root):
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    pd.DataFrame(
        [
            {"module_name": "srcmod", "inst_name": "u_src", "owner": "src"},
            {"module_name": "dstmod", "inst_name": "u_dst", "owner": "dst"},
            {"module_name": "fanmod", "inst_name": "u_fan", "owner": "fan"},
            {
                "module_name": "nrmod",
                "inst_name": "u_nr",
                "owner": "nr",
                "func_availability_status": "not_required",
                "func_sdc_note": "approved structural shell",
            },
        ]
    ).to_excel(inputs / "info_all.xlsx", index=False)

    sheets = {
        "u_src": [
            row(Output="data_o[7:4]", **{"Output Width": 4}),
            row(Output="reverse_o[0:3]", **{"Output Width": 4}),
            row(Output="scalar_o", **{"Output Width": 1}),
        ],
        "u_dst": [
            row(Input="data_i[3:0]", **{"Input Width": 4, "From Whom": "u_src.data_o[7:4]"}),
            row(Input="reverse_i[7:4]", **{"Input Width": 4, "From Whom": "u_src.reverse_o[0:3]"}),
            row(Input="scalar_i", **{"Input Width": 1, "From Whom": "u_src.scalar_o"}),
            row(Input="tie_i[3:0]", **{"Input Width": 4, "From Whom": "4'b1010"}),
            row(Input="top_bus_i[3:0]", **{"Input Width": 4, "From Whom": "top.pad_bus[7:4]"}),
            row(Output="result_o", **{"Output Width": 1, "To Top": "result_pad"}),
        ],
        "u_fan": [
            row(Input="data_i[3:0]", **{"Input Width": 4, "From Whom": "u_src.data_o[7:4]"}),
        ],
        "u_nr": [
            row(Input="unused_i", **{"Input Width": 1, "From Whom": "NC"}),
        ],
    }
    with pd.ExcelWriter(inputs / "ports.xlsx", engine="xlsxwriter") as writer:
        for sheet_name, rows in sheets.items():
            pd.DataFrame(rows, columns=PORT_COLUMNS).to_excel(
                writer, sheet_name=sheet_name, index=False
            )
    (inputs / "u_src_func.sdc").write_text("# func source SDC\n", encoding="utf-8")
    (inputs / "dstmod.sdc").write_text("# shared destination SDC\n", encoding="utf-8")


def test_main_flow(work):
    root = work / "main"
    write_case(root)
    first = run_00(root, "func")
    require(first.returncode == 0, "first func run failed:\n%s\n%s" % (first.stdout, first.stderr))
    require(first.stdout.count("Author: Howard") == 1, "stdout author marker missing or duplicated")

    connection = root / "00_middle" / "connection_inventory.csv"
    manifest = root / "00_middle" / "scenario" / "func" / "harden_sdc_manifest.csv"
    pending = root / "00_middle" / "scenario" / "func" / "pending"
    report = root / "00_result" / "reports" / "inventory_report_func.txt"
    require(connection.is_file() and manifest.is_file() and report.is_file(), "required target artifact missing")
    edges = read_csv(connection)
    require(len(edges) == 23, "expected 23 bit edges, got %d" % len(edges))
    require({item["schema_version"] for item in edges} == {"1.0"}, "schema_version mismatch")
    require({item["scenario_scope"] for item in edges} == {"common"}, "default scenario_scope mismatch")

    mapped = {
        (item["src_port"], item["dst_port"])
        for item in edges
        if item["src_instance"] == "u_src" and item["dst_instance"] == "u_dst"
    }
    require(("data_o[7]", "data_i[3]") in mapped, "descending range mapping missing")
    require(("data_o[4]", "data_i[0]") in mapped, "range tail mapping missing")
    require(("reverse_o[0]", "reverse_i[7]") in mapped, "ascending-to-descending mapping missing")
    require(
        any(item["connection_type"] == "constant_tie" and item["dst_port"] == "tie_i[3]" for item in edges),
        "constant_tie classification missing",
    )
    require(
        any(item["connection_type"] == "no_connect" and item["dst_instance"] == "u_nr" for item in edges),
        "no_connect classification missing",
    )
    require(
        any(item["range_source_expr"] == "u_src.data_o[7:4]" for item in edges),
        "source range traceability missing",
    )
    fanout = sorted(
        int(item["fanout_index"])
        for item in edges
        if item["src_endpoint_key"] == "u_src:output:data_o[7]"
    )
    require(fanout == [0, 1], "fanout_index is not stable: %r" % fanout)

    manifests = {row["inst_name"]: row for row in read_csv(manifest)}
    require(manifests["u_src"]["availability_status"] == "available", "scenario SDC match failed")
    require(manifests["u_dst"]["availability_status"] == "available", "module SDC match failed")
    require(manifests["u_fan"]["availability_status"] == "missing", "missing SDC status failed")
    require(manifests["u_nr"]["availability_status"] == "not_required", "not_required status failed")
    require("Run completeness: partial" in report.read_text(encoding="utf-8"), "partial report metadata missing")

    pending_src = pending / "u_src.ports"
    src_lines = pending_src.read_text(encoding="utf-8").splitlines()
    require("output data_o[7]" in src_lines and "output data_o[4]" in src_lines, "pending bit expansion failed")
    pending_src.write_text(
        "\n".join(line for line in src_lines if line != "output data_o[7]") + "\n",
        encoding="utf-8",
    )
    second = run_00(root, "func")
    require(second.returncode == 0, "idempotent rerun failed: %s" % second.stderr)
    require("output data_o[7]" not in pending_src.read_text(encoding="utf-8"), "rerun restored consumed pending")

    scan = run_00(root, "scan")
    require(scan.returncode == 0, "scan scenario initialization failed: %s" % scan.stderr)
    require((root / "00_middle/scenario/scan/pending/u_src.ports").is_file(), "scan pending missing")
    require(
        "output data_o[7]" in (root / "00_middle/scenario/scan/pending/u_src.ports").read_text(encoding="utf-8"),
        "scan pending incorrectly reused func state",
    )
    scan_manifest = read_csv(root / "00_middle/scenario/scan/harden_sdc_manifest.csv")
    require(all(row["scenario"] == "scan" for row in scan_manifest), "scan manifest scenario mismatch")

    strict = run_00(root, "scan", "--require-complete-harden-sdc")
    require(strict.returncode == 2, "strict missing-SDC run should fail")
    require("--require-complete-harden-sdc" in strict.stderr, "strict failure reason missing")


def test_accounting_disabled(work):
    root = work / "no_accounting"
    write_case(root)
    result = run_00(root, "func", "--no-port-accounting")
    require(result.returncode == 0, "no-accounting run failed: %s" % result.stderr)
    require(not (root / "00_middle/scenario/func/pending").exists(), "no-accounting run created pending")
    report = (root / "00_result/reports/inventory_report_func.txt").read_text(encoding="utf-8")
    require("Port accounting: disabled by explicit option" in report, "disabled accounting metadata missing")
    require("Port closure status: not_tracked" in report, "disabled run claimed closure")


def test_changed_inventory_guard(work):
    root = work / "changed"
    write_case(root)
    first = run_00(root, "func")
    require(first.returncode == 0, "guard setup failed")
    connection = root / "00_middle/connection_inventory.csv"
    original_digest = sha256(connection)

    workbook = root / "inputs/ports.xlsx"
    sheets = pd.read_excel(workbook, sheet_name=None)
    sheets["u_dst"].loc[len(sheets["u_dst"])] = row(
        Input="new_i", **{"Input Width": 1, "From Whom": "u_src.scalar_o"}
    )
    with pd.ExcelWriter(workbook, engine="xlsxwriter") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    blocked = run_00(root, "func")
    require(blocked.returncode == 2, "changed inventory was not blocked")
    require(sha256(connection) == original_digest, "blocked run modified official connection inventory")
    rebuild_blocked = run_00(root, "func", "--rebuild-connection-inventory")
    require(rebuild_blocked.returncode == 2, "rebuild without reset should be blocked")
    rebuilt = run_00(
        root,
        "func",
        "--rebuild-connection-inventory",
        "--reset-scenario",
    )
    require(rebuilt.returncode == 0, "explicit rebuild/reset failed: %s" % rebuilt.stderr)
    require(sha256(connection) != original_digest, "explicit rebuild did not update inventory")


def test_width_mismatch(work):
    root = work / "mismatch"
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    pd.DataFrame(
        [
            {"module_name": "a", "inst_name": "u_a"},
            {"module_name": "b", "inst_name": "u_b"},
        ]
    ).to_excel(inputs / "info_all.xlsx", index=False)
    with pd.ExcelWriter(inputs / "port_owner.xlsx", engine="xlsxwriter") as writer:
        pd.DataFrame(
            [row(Output="data_o[3:0]", **{"Output Width": 4})], columns=PORT_COLUMNS
        ).to_excel(writer, sheet_name="u_a", index=False)
        pd.DataFrame(
            [row(Input="data_i[2:0]", **{"Input Width": 3, "From Whom": "u_a.data_o[3:0]"})],
            columns=PORT_COLUMNS,
        ).to_excel(writer, sheet_name="u_b", index=False)
    result = run_00(root, "common")
    require(result.returncode == 2, "width mismatch should fail")
    require("source data_o[3:0] has 4 bit(s)" in result.stderr, "width mismatch reason missing")
    require(not (root / "00_middle/connection_inventory.csv").exists(), "invalid run published inventory")


def test_legacy_layout(work):
    target_root = work / "legacy_source"
    write_case(target_root)
    legacy_root = work / "legacy"
    legacy_root.mkdir()
    for path in (target_root / "inputs").iterdir():
        shutil.copy2(str(path), str(legacy_root / path.name))
    result = run_legacy(legacy_root, "func")
    require(result.returncode == 0, "legacy cwd run failed: %s" % result.stderr)
    inventory_root = legacy_root / "00_harden_port_inventory"
    require((inventory_root / "connection_inventory.csv").is_file(), "legacy connection inventory missing")
    require((inventory_root / "harden_sdc_manifest.csv").is_file(), "legacy manifest missing")
    require((inventory_root / "pending/u_src.ports").is_file(), "legacy pending missing")
    report = (inventory_root / "inventory_report.txt").read_text(encoding="utf-8")
    require("Runtime layout: legacy" in report, "legacy report metadata missing")


def test_scale(work, bit_count):
    if bit_count <= 0:
        return
    root = work / "scale"
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    pd.DataFrame(
        [
            {"module_name": "a", "inst_name": "u_a"},
            {"module_name": "b", "inst_name": "u_b"},
        ]
    ).to_excel(inputs / "info_all.xlsx", index=False)
    with pd.ExcelWriter(inputs / "ports_scale.xlsx", engine="xlsxwriter") as writer:
        pd.DataFrame(
            [row(Output="data_o", **{"Output Width": bit_count})], columns=PORT_COLUMNS
        ).to_excel(writer, sheet_name="u_a", index=False)
        pd.DataFrame(
            [row(Input="data_i", **{"Input Width": bit_count, "From Whom": "u_a.data_o"})],
            columns=PORT_COLUMNS,
        ).to_excel(writer, sheet_name="u_b", index=False)
    started = time.time()
    result = run_00(root, "common", "--no-port-accounting")
    elapsed = time.time() - started
    require(result.returncode == 0, "scale run failed: %s" % result.stderr)
    line_count = sum(1 for _ in (root / "00_middle/connection_inventory.csv").open("r", encoding="utf-8"))
    require(line_count == bit_count + 1, "scale edge count mismatch: %d" % line_count)
    print("scale: %d bit edges in %.2fs" % (bit_count, elapsed))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale-bits", type=int, default=0)
    args = parser.parse_args()
    require(EX00.is_file(), "00 script not found: %s" % EX00)
    work = Path(tempfile.mkdtemp(prefix="soc_sdc_00_regression_"))
    try:
        test_main_flow(work)
        test_accounting_disabled(work)
        test_changed_inventory_guard(work)
        test_width_mismatch(work)
        test_legacy_layout(work)
        test_scale(work, args.scale_bits)
    finally:
        shutil.rmtree(str(work))
    print("00_harden_port_inventory regression: PASS")


if __name__ == "__main__":
    main()
