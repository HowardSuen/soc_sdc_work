#!/usr/bin/env python3
"""Regression for the edge-centric 10 feedthrough runtime."""

from __future__ import print_function

import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook


BASE = Path(__file__).resolve().parent
EX10 = BASE.parent / "10_extract_feedthrough.py"
WORK = BASE / "work_complex"

CONNECTION_HEADERS = [
    "schema_version",
    "scenario_scope",
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


def clean_dir(path):
    if path.exists():
        shutil.rmtree(str(path))
    path.mkdir(parents=True)


def sh(args, cwd):
    return subprocess.run(
        [sys.executable, str(EX10)] + [str(arg) for arg in args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def read_csv_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        return list(csv.DictReader(file_obj))


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def soc_object(inst, port):
    return port if inst == "top" else "%s/%s" % (inst, port)


def pending_snapshot(root, scenario="common"):
    pending = root / "00_middle" / "scenario" / scenario / "pending"
    result = {}
    for path in sorted(pending.glob("*.ports")):
        result[path.name] = tuple(
            line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        )
    return result


def command_endpoint_pairs(sdc_text_value):
    pairs = []
    for line in sdc_text_value.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("set_max_delay ", "set_min_delay ")):
            continue
        require(" -from " in stripped and " -to " in stripped, "malformed delay command: %s" % stripped)
        tail = stripped.split(" -from ", 1)[1]
        source, destination = tail.split(" -to ", 1)
        pairs.append((source.strip(), destination.strip()))
    return pairs


def delay_command_lines(sdc_text_value):
    return [
        line.strip()
        for line in sdc_text_value.splitlines()
        if line.strip().startswith(("set_max_delay ", "set_min_delay "))
    ]


def base_edges():
    return [
        ("CONN_IN_B0", "harden_to_harden", "u_src", "output", "data_o[0]", "u_ft1", "input", "fti_local[4]"),
        ("CONN_IN_B1", "harden_to_harden", "u_src", "output", "data_o[1]", "u_ft1", "input", "fti_local[5]"),
        ("CONN_MID_B0", "harden_to_harden", "u_ft1", "output", "fto_local[4]", "u_ft2", "input", "fti_transport[10]"),
        ("CONN_MID_B1", "harden_to_harden", "u_ft1", "output", "fto_local[5]", "u_ft2", "input", "fti_transport[9]"),
        ("CONN_OUT_B0", "harden_to_harden", "u_ft2", "output", "fto_transport[10]", "u_dst", "input", "data_i[0]"),
        ("CONN_OUT_B1", "harden_to_harden", "u_ft2", "output", "fto_transport[9]", "u_dst", "input", "data_i[1]"),
        ("CONN_NORMAL", "harden_to_harden", "u_src", "output", "normal_o", "u_dst", "input", "normal_i"),
    ]


def write_connections(root, edges=None, scenario_scope="common"):
    path = root / "00_middle" / "connection_inventory.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=CONNECTION_HEADERS)
        writer.writeheader()
        for connection_id, connection_type, src_i, src_d, src_p, dst_i, dst_d, dst_p in (edges or base_edges()):
            src_bit = src_p.split("[")[-1].rstrip("]") if "[" in src_p else ""
            dst_bit = dst_p.split("[")[-1].rstrip("]") if "[" in dst_p else ""
            writer.writerow(
                {
                    "schema_version": "1",
                    "scenario_scope": scenario_scope,
                    "connection_id": connection_id,
                    "connection_type": connection_type,
                    "src_instance": src_i,
                    "src_direction": src_d,
                    "src_port": src_p,
                    "src_bit_index": src_bit,
                    "src_endpoint_key": "%s:%s:%s" % (src_i, src_d, src_p),
                    "src_soc_object": soc_object(src_i, src_p),
                    "dst_instance": dst_i,
                    "dst_direction": dst_d,
                    "dst_port": dst_p,
                    "dst_bit_index": dst_bit,
                    "dst_endpoint_key": "%s:%s:%s" % (dst_i, dst_d, dst_p),
                    "dst_soc_object": soc_object(dst_i, dst_p),
                    "validation_status": "matched",
                    "note": "",
                }
            )


def update_connection_rows(root, updates):
    path = root / "00_middle" / "connection_inventory.csv"
    rows = read_csv_rows(path)
    found = set()
    for row in rows:
        values = updates.get(row["connection_id"])
        if not values:
            continue
        row.update(values)
        found.add(row["connection_id"])
    require(found == set(updates), "connection update target missing")
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=CONNECTION_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def update_manifest_rows(root, updates, scenario="common"):
    path = root / "00_middle" / "scenario" / scenario / "harden_sdc_manifest.csv"
    rows = read_csv_rows(path)
    found = set()
    for row in rows:
        values = updates.get(row["inst_name"])
        if not values:
            continue
        row.update(values)
        found.add(row["inst_name"])
    require(found == set(updates), "manifest update target missing")
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def remove_pending_entry(root, inst_name, direction, port_name, scenario="common"):
    path = root / "00_middle" / "scenario" / scenario / "pending" / (inst_name + ".ports")
    target = "%s %s" % (direction, port_name)
    lines = path.read_text(encoding="utf-8").splitlines()
    require(target in lines, "pending removal fixture target missing: %s" % target)
    path.write_text("\n".join(line for line in lines if line != target) + "\n", encoding="utf-8")


def report_text(root, scenario="common"):
    return (
        root / "10_result" / "reports" / ("feedthrough_check_report_%s.txt" % scenario)
    ).read_text(encoding="utf-8")


def sdc_text(inst):
    if inst == "u_src":
        return (
            "set_output_delay -max 2.0 -clock [get_clocks {clk_a}] [get_ports {data_o[1:0]}]\n"
            "set_output_delay -max 3.0 -clock [get_clocks {clk_a}] [get_ports {normal_o}]\n"
        )
    if inst == "u_ft1":
        return (
            "set_input_delay -max 1.8 -clock [get_clocks {clk_a}] [get_ports {\n"
            "  fti_local[4]\n"
            "  fti_local[5]\n"
            "}]\n"
            "set_output_delay -max 1.5 -clock [get_clocks {clk_b}] [get_ports {fto_local[4:5]}]\n"
        )
    if inst == "u_ft2":
        return (
            "set_input_delay -max 1.3 -clock [get_clocks {clk_b}] [get_ports {fti_transport[10:9]}]\n"
            "set_output_delay -max 1.1 -clock [get_clocks {clk_b}] [get_ports {fto_transport[10:9]}]\n"
        )
    return (
        "set_input_delay -max 0.9 -clock [get_clocks {clk_b}] [get_ports {data_i[1:0]}]\n"
        "set_input_delay -max 2.5 -clock [get_clocks {clk_b}] [get_ports {normal_i}]\n"
    )


def write_manifest_and_sdcs(root, scenario="common", missing=None):
    missing = set(missing or [])
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    manifest = root / "00_middle" / "scenario" / scenario / "harden_sdc_manifest.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=["scenario", "inst_name", "module_name", "sdc_path", "availability_status", "note"],
        )
        writer.writeheader()
        for inst in ("u_src", "u_ft1", "u_ft2", "u_dst"):
            is_missing = inst in missing
            sdc_path = "" if is_missing else "inputs/%s.sdc" % inst
            writer.writerow(
                {
                    "scenario": scenario,
                    "inst_name": inst,
                    "module_name": "harden_" + inst[2:],
                    "sdc_path": sdc_path,
                    "availability_status": "missing" if is_missing else "available",
                    "note": "not delivered" if is_missing else "",
                }
            )
            if not is_missing:
                (inputs / (inst + ".sdc")).write_text(sdc_text(inst), encoding="utf-8")


def write_relation_input(root, scenario="common", relation_type="synchronous", row_scenario=None):
    clock_path = root / "01_middle" / "assembled" / scenario / "clock_inventory.csv"
    clock_meta_path = clock_path.with_suffix(".meta")
    clock_meta = json.loads(clock_meta_path.read_text(encoding="utf-8"))
    clock_digest = clock_meta["clock_set_digest"]
    assembled_digest = sha256_text(
        "%s|%s|%s" % (scenario, clock_digest, relation_type)
    )
    relation_path = root / "03_middle" / "relation_map" / (scenario + ".csv")
    relation_path.parent.mkdir(parents=True, exist_ok=True)
    relation_path.write_text(
        "schema_version,scenario,clock_a,clock_b,relation_type,relation_source,source_rule_ids,clock_universe_digest,assembled_view_digest\n"
        "1,%s,soc_clk_a,soc_clk_b,%s,explicit_rule,CG_TEST,%s,%s\n"
        % (row_scenario or scenario, relation_type, clock_digest, assembled_digest),
        encoding="utf-8",
    )
    relation_meta = {
        "schema_version": "1",
        "scenario": scenario,
        "run_completeness": "complete",
        "clock_universe_digest": clock_digest,
        "assembled_view_digest": assembled_digest,
        "inventory_path": str(clock_path.resolve()),
        "inventory_digest": sha256_file(clock_path),
        "inventory_meta_path": str(clock_meta_path.resolve()),
        "inventory_meta_digest": sha256_file(clock_meta_path),
        "final_clock_sdc_path": clock_meta["final_sdc_path"],
        "final_clock_sdc_digest": clock_meta["final_sdc_digest"],
        "relation_map_path": str(relation_path.resolve()),
        "relation_map_digest": sha256_file(relation_path),
    }
    relation_path.with_suffix(".meta").write_text(
        json.dumps(relation_meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_clock_inputs(root, scenario="common"):
    clock_path = root / "01_middle" / "assembled" / scenario / "clock_inventory.csv"
    clock_path.parent.mkdir(parents=True, exist_ok=True)
    clock_path.write_text(
        "inst_name,port_name,clock_name,original_clock_name,direct_source,root_source,from_whom,final_action,target_object\n"
        "u_src,clk_a_o,soc_clk_a,clk_a,u_src/clk_a_o,u_src/clk_a_o,,emit_output_clock,u_src/clk_a_o\n"
        "u_ft1,clk_b_o,soc_clk_b,clk_b,u_ft1/clk_b_o,u_ft1/clk_b_o,,emit_output_clock,u_ft1/clk_b_o\n"
        "u_ft1,clk_a_i,u_ft1_clk_a_i,clk_a,u_ft1/clk_a_i,u_src/clk_a_o,u_src.clk_a_o,check_only,\n"
        "u_ft2,clk_b_i,u_ft2_clk_b_i,clk_b,u_ft2/clk_b_i,u_ft1/clk_b_o,u_ft1.clk_b_o,check_only,\n"
        "u_dst,clk_b_i,u_dst_clk_b_i,clk_b,u_dst/clk_b_i,u_ft1/clk_b_o,u_ft1.clk_b_o,check_only,\n",
        encoding="utf-8",
    )
    clock_sdc_path = root / "01_result" / "common" / "01_soc_clocks.sdc"
    clock_sdc_path.parent.mkdir(parents=True, exist_ok=True)
    clock_sdc_path.write_text("# regression clock fixture\n", encoding="utf-8")
    active_names = ["soc_clk_a", "soc_clk_b"]
    clock_meta = {
        "scenario": scenario,
        "stage": "01_soc_clocks",
        "final_sdc_path": str(clock_sdc_path.resolve()),
        "final_sdc_digest": sha256_file(clock_sdc_path),
        "inventory_path": str(clock_path.resolve()),
        "inventory_digest": sha256_file(clock_path),
        "clock_set_digest": sha256_text("\n".join(active_names)),
        "clock_count": len(active_names),
        "run_completeness": "complete",
        "available_harden_count": 4,
        "missing_harden_count": 0,
        "not_required_harden_count": 0,
        "missing_instances": [],
    }
    clock_path.with_suffix(".meta").write_text(
        json.dumps(clock_meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_relation_input(root, scenario)


def write_pending(root, scenario="common"):
    pending = root / "00_middle" / "scenario" / scenario / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "u_src.ports").write_text(
        "output data_o[0]\noutput data_o[1]\noutput normal_o\n", encoding="utf-8"
    )
    (pending / "u_ft1.ports").write_text(
        "input fti_local[4]\ninput fti_local[5]\noutput fto_local[4]\noutput fto_local[5]\n",
        encoding="utf-8",
    )
    (pending / "u_ft2.ports").write_text(
        "input fti_transport[9]\ninput fti_transport[10]\noutput fto_transport[9]\noutput fto_transport[10]\n",
        encoding="utf-8",
    )
    (pending / "u_dst.ports").write_text(
        "input data_i[0]\ninput data_i[1]\ninput normal_i\n", encoding="utf-8"
    )


def build_root(root, scenario="common", missing=None, edges=None):
    clean_dir(root)
    write_connections(root, edges)
    write_manifest_and_sdcs(root, scenario, missing)
    write_clock_inputs(root, scenario)
    write_pending(root, scenario)


def workbook_headers(sheet):
    return {cell.value: cell.column for cell in sheet[1] if cell.value}


def update_review_rows(form, updates, scenario=None, stage=None, corner=None):
    workbook = load_workbook(str(form))
    sheet = workbook["feedthrough_edges"]
    columns = workbook_headers(sheet)
    found = set()
    for row_idx in range(2, sheet.max_row + 1):
        if scenario is not None and sheet.cell(row_idx, columns["scenario"]).value != scenario:
            continue
        if stage is not None and sheet.cell(row_idx, columns["stage"]).value != stage:
            continue
        if corner is not None and sheet.cell(row_idx, columns["corner"]).value != corner:
            continue
        connection_id = sheet.cell(row_idx, columns["connection_id"]).value
        values = updates.get(connection_id)
        if not values:
            continue
        found.add(connection_id)
        for key, value in values.items():
            sheet.cell(row_idx, columns[key], value)
    require(found == set(updates), "review update target missing: %s" % sorted(set(updates) - found))
    workbook.save(str(form))


def workbook_row_values(form, connection_id, scenario="common", stage="all", corner="all"):
    workbook = load_workbook(str(form), data_only=False)
    sheet = workbook["feedthrough_edges"]
    columns = workbook_headers(sheet)
    for row_idx in range(2, sheet.max_row + 1):
        if (
            sheet.cell(row_idx, columns["connection_id"]).value == connection_id
            and sheet.cell(row_idx, columns["scenario"]).value == scenario
            and sheet.cell(row_idx, columns["stage"]).value == stage
            and sheet.cell(row_idx, columns["corner"]).value == corner
        ):
            return {
                header: sheet.cell(row_idx, column).value
                for header, column in columns.items()
            }
    raise AssertionError("workbook row missing: %s" % connection_id)


def approved_emit(value):
    return {
        "channel_disposition": "emit_budget",
        "budget_model": "manual_budget",
        "budget_required": "yes",
        "converted_max": value,
        "emit_max": "yes",
        "emit_min": "no",
        "datapath_only": "yes",
        "tool_surface": "dc",
        "apply": "yes",
        "review_status": "approved",
        "disposition_basis": "reviewed direct interconnect budget",
    }


def approved_no_budget():
    return {
        "channel_disposition": "no_soc_budget_required",
        "budget_required": "no",
        "emit_max": "no",
        "emit_min": "no",
        "apply": "yes",
        "review_status": "approved",
        "owner": "soc_policy_owner",
        "reviewer": "timing_reviewer",
        "review_date": "2026-07-14",
        "disposition_basis": "project_feedthrough_no_soc_budget_v1",
    }


def approved_na():
    return {
        "channel_disposition": "not_applicable",
        "budget_required": "no",
        "emit_max": "no",
        "emit_min": "no",
        "apply": "yes",
        "review_status": "approved",
        "owner": "soc",
        "reviewer": "timing",
        "review_date": "2026-07-13",
        "disposition_basis": "reviewed not applicable",
    }


def approved_route_to_30():
    return {
        "channel_disposition": "route_to_30",
        "budget_required": "no",
        "emit_max": "no",
        "emit_min": "no",
        "apply": "yes",
        "review_status": "approved",
        "owner": "exception_owner",
        "reviewer": "timing_reviewer",
        "review_date": "2026-07-14",
        "disposition_basis": "reviewed protocol exception evidence routes this edge to 30",
    }


def run_direct_edge_lifecycle():
    root = WORK / "lifecycle"
    build_root(root)
    first = sh(["--run-root", root, "--scenario", "common"], root)
    require(first.returncode == 1, "first sync should stop for review:\n%s\n%s" % (first.stdout, first.stderr))
    require(first.stdout.count("Author: Howard") == 1, "author stdout missing or duplicated")

    connection_path = (root / "00_middle" / "connection_inventory.csv").resolve()
    manifest_path = (
        root / "00_middle" / "scenario" / "common" / "harden_sdc_manifest.csv"
    ).resolve()
    for metadata in (
        "Scenario: common",
        "Run completeness: complete",
        "Port accounting: enabled",
        "Connection inventory: %s" % connection_path,
        "Harden SDC manifest: %s" % manifest_path,
    ):
        require(metadata in first.stdout, "stdout metadata missing: %s" % metadata)

    form = root / "10_middle" / "10_feedthrough.xlsx"
    inventory = root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv"
    output = root / "10_result" / "common" / "10_feedthrough.sdc"
    require(form.is_file(), "review workbook missing")
    require(inventory.is_file(), "first sync must still write structural inventory")
    require(not output.exists(), "first sync must not write formal SDC")
    initial_report = report_text(root)
    for metadata in (
        "Author: Howard",
        "Scenario: common",
        "Run completeness: complete",
        "Port accounting: enabled",
        "Connection inventory: %s" % connection_path,
        "Harden SDC manifest: %s" % manifest_path,
    ):
        require(metadata in initial_report, "report metadata missing: %s" % metadata)
    rows = read_csv_rows(inventory)
    require(len(rows) == 6, "inventory must contain exactly six feedthrough-owned bit edges")
    require("CONN_NORMAL" not in {row["connection_id"] for row in rows}, "ordinary edge leaked into 10")
    expected_sides = {
        "CONN_IN_B0": "ingress",
        "CONN_IN_B1": "ingress",
        "CONN_MID_B0": "between_feedthroughs",
        "CONN_MID_B1": "between_feedthroughs",
        "CONN_OUT_B0": "egress",
        "CONN_OUT_B1": "egress",
    }
    require(
        {row["connection_id"]: row["feedthrough_side"] for row in rows} == expected_sides,
        "connection-to-side classification is wrong",
    )
    for row in rows:
        require(row["schema_version"] == "1", "inventory schema version missing")
        require(row["scenario_scope"] == "common", "inventory scenario scope missing")
        require(row["feedthrough_edge_id"] == "FTE_" + row["connection_id"], "FTE/connection mapping is not stable")
        require(row["run_completeness"] == "complete", "inventory completeness status missing")
        require(row["available_harden_count"] == "4", "inventory available count missing")
        require(row["missing_harden_count"] == "0", "inventory missing count is wrong")
        require(row["port_accounting"] == "enabled", "inventory port-accounting metadata missing")
        require(row["connection_inventory_path"] == str(connection_path), "inventory source path metadata missing")
        require(row["harden_sdc_manifest_path"] == str(manifest_path), "manifest path metadata missing")
    ingress_rows = {row["connection_id"]: row for row in rows if row["feedthrough_side"] == "ingress"}
    require(
        ingress_rows["CONN_IN_B0"]["dst_input_delay_max"] == "1.8"
        and ingress_rows["CONN_IN_B1"]["dst_input_delay_max"] == "1.8",
        "multiline get_ports delay evidence was not expanded to both bits",
    )
    row_by_connection = {row["connection_id"]: row for row in rows}
    form_row = workbook_row_values(form, "CONN_IN_B0")
    require(form_row["schema_version"] == "1", "workbook schema version missing")
    require(form_row["scenario_scope"] == "common", "workbook scenario scope missing")
    require(form_row["port_accounting"] == "enabled", "workbook port-accounting metadata missing")
    require(
        form_row["connection_inventory_path"] == str(connection_path),
        "workbook connection path metadata missing",
    )
    require(
        form_row["harden_sdc_manifest_path"] == str(manifest_path),
        "workbook manifest path metadata missing",
    )
    require(
        row_by_connection["CONN_IN_B0"]["src_clock"] == "soc_clk_a"
        and row_by_connection["CONN_IN_B0"]["dst_clock"] == "soc_clk_a",
        "local clk_a aliases were not resolved to the final 01 clock",
    )
    require(
        row_by_connection["CONN_OUT_B0"]["src_clock"] == "soc_clk_b"
        and row_by_connection["CONN_OUT_B0"]["dst_clock"] == "soc_clk_b",
        "check-only clk_b aliases were not resolved to the final 01 clock",
    )

    update_review_rows(
        form,
        {
            "CONN_IN_B0": approved_emit("1.1"),
            "CONN_MID_B0": {
                "channel_disposition": "route_to_30",
                "apply": "yes",
                "review_status": "approved",
                "owner": "exception_owner",
                "reviewer": "timing_reviewer",
                "review_date": "2026-07-14",
                "disposition_basis": "reviewed protocol exception evidence routes this edge to 30",
            },
            "CONN_MID_B1": approved_no_budget(),
            "CONN_OUT_B0": approved_na(),
            "CONN_OUT_B1": approved_emit("0.9"),
        },
    )
    second = sh(["--run-root", root, "--scenario", "common"], root)
    require(second.returncode == 0, "reviewed run failed:\n%s\n%s" % (second.stdout, second.stderr))
    sdc = output.read_text(encoding="utf-8")
    require("set_max_delay 1.1 -datapath_only -from [get_pins {u_src/data_o[0]}] -to [get_pins {u_ft1/fti_local[4]}]" in sdc, "ingress direct-edge command missing")
    require("set_max_delay 0.9 -datapath_only -from [get_pins {u_ft2/fto_transport[9]}] -to [get_pins {u_dst/data_i[1]}]" in sdc, "egress direct-edge command missing")
    require("Author: Howard" in sdc, "SDC author header missing")
    require("# Scenario: common" in sdc, "SDC scenario header missing")
    require("# Run completeness: complete" in sdc, "SDC completeness header missing")
    require("# Port accounting: enabled" in sdc, "SDC port-accounting header missing")
    require("# Connection inventory: %s" % connection_path in sdc, "SDC connection path header missing")
    require("# Harden SDC manifest: %s" % manifest_path in sdc, "SDC manifest path header missing")
    require("# Harden SDC available: 4" in sdc, "SDC completeness counts missing")
    inventory_rows = {row["connection_id"]: row for row in read_csv_rows(inventory)}
    allowed_pairs = {
        (row["src_soc_object"], row["dst_soc_object"])
        for row in inventory_rows.values()
    }
    command_pairs = command_endpoint_pairs(sdc)
    require(len(command_pairs) == 2, "unexpected number of emitted max/min commands")
    require(all(pair in allowed_pairs for pair in command_pairs), "internal or synthetic command endpoint emitted")

    require(
        pending_snapshot(root) == {
            "u_dst.ports": ("input normal_i",),
            "u_ft1.ports": ("input fti_local[5]", "output fto_local[4]"),
            "u_ft2.ports": ("input fti_transport[10]",),
            "u_src.ports": ("output data_o[1]", "output normal_o"),
        },
        "pending files do not match terminal/route/pending dispositions",
    )
    removed = (root / "10_middle" / "scenario" / "common" / "removed_log" / "10_feedthrough.removed").read_text(encoding="utf-8")
    require("feedthrough_edge_id=FTE_CONN_IN_B0" in removed, "removed log missing FTE id")
    require("connection_id=CONN_OUT_B1" in removed, "removed log missing connection id")
    require("channel_disposition=emit_budget" in removed, "removed log missing disposition")
    require("connection_id=CONN_MID_B1" in removed and "channel_disposition=no_soc_budget_required" in removed, "no-budget removal missing")
    require("connection_id=CONN_OUT_B0" in removed and "channel_disposition=not_applicable" in removed, "not-applicable removal missing")
    require("CONN_IN_B1" not in removed and "CONN_MID_B0" not in removed, "pending/route edge was consumed")

    before = removed
    rerun = sh(["--run-root", root, "--scenario", "common"], root)
    require(rerun.returncode == 0, "idempotent rerun failed")
    require((root / "10_middle" / "scenario" / "common" / "removed_log" / "10_feedthrough.removed").read_text(encoding="utf-8") == before, "removed log is not idempotent")

    stable_sdc = output.read_text(encoding="utf-8")
    source_sdc = root / "inputs" / "u_src.sdc"
    source_sdc.write_text(
        source_sdc.read_text(encoding="utf-8").replace("-max 2.0", "-max 2.2"),
        encoding="utf-8",
    )
    stale = sh(["--run-root", root, "--scenario", "common"], root)
    require(stale.returncode == 1, "material evidence refresh should require re-review")
    require(output.read_text(encoding="utf-8") == stable_sdc, "evidence refresh overwrote formal SDC")
    workbook = load_workbook(str(form), data_only=False)
    sheet = workbook["feedthrough_edges"]
    columns = workbook_headers(sheet)
    stale_row = next(
        row_idx for row_idx in range(2, sheet.max_row + 1)
        if sheet.cell(row_idx, columns["connection_id"]).value == "CONN_IN_B0"
        and sheet.cell(row_idx, columns["scenario"]).value == "common"
    )
    require(sheet.cell(stale_row, columns["apply"]).value == "no", "material refresh did not reset apply")
    require(sheet.cell(stale_row, columns["review_status"]).value == "pending", "material refresh did not reset review status")
    require(
        sheet.cell(stale_row, columns["approved_machine_digest"]).value
        != sheet.cell(stale_row, columns["machine_digest"]).value,
        "stale approval digest was silently advanced",
    )
    stale_rerun = sh(["--run-root", root, "--scenario", "common"], root)
    require(stale_rerun.returncode == 1, "stale approval should remain blocked without reviewer action")
    require(output.read_text(encoding="utf-8") == stable_sdc, "stale rerun overwrote formal SDC")
    update_review_rows(form, {"CONN_IN_B0": approved_emit("1.1")}, scenario="common")
    reapproved = sh(["--run-root", root, "--scenario", "common"], root)
    require(reapproved.returncode == 0, "re-approved refreshed evidence failed")
    require(output.read_text(encoding="utf-8") == stable_sdc, "reapproval changed reviewed direct-edge command")


def run_partial_and_strict():
    root = WORK / "partial"
    build_root(root, missing={"u_dst"})
    first = sh(["--run-root", root, "--scenario", "common"], root)
    require(first.returncode == 1, "partial first sync should stop for review")
    inventory = root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv"
    rows = {row["connection_id"]: row for row in read_csv_rows(inventory)}
    require(rows["CONN_OUT_B0"]["dst_sdc_status"] == "missing", "missing endpoint status absent")
    require(rows["CONN_OUT_B0"]["evidence_status"] == "incomplete_missing_sdc", "missing evidence status absent")
    require(rows["CONN_OUT_B0"]["missing_harden_count"] == "1", "partial inventory missing count absent")
    require(rows["CONN_OUT_B0"]["missing_instances"] == "u_dst", "partial inventory missing instance absent")
    require(len(rows) == 6, "partial mode must retain structural rows")

    form = root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(form, {"CONN_IN_B0": approved_no_budget()})
    second = sh(["--run-root", root, "--scenario", "common"], root)
    require(second.returncode == 0, "available-only edge should complete in partial mode")
    second_pending = pending_snapshot(root)
    require("output data_o[0]" not in second_pending["u_src.ports"], "available source endpoint was not removed")
    require("input fti_local[4]" not in second_pending["u_ft1.ports"], "available feedthrough endpoint was not removed")
    require("input data_i[0]" in second_pending["u_dst.ports"], "missing-SDC endpoint was consumed")

    update_review_rows(form, {"CONN_OUT_B0": approved_no_budget()})
    output = root / "10_result" / "common" / "10_feedthrough.sdc"
    sentinel = output.read_text(encoding="utf-8")
    pending_before_error = pending_snapshot(root)
    removed_path = root / "10_middle" / "scenario" / "common" / "removed_log" / "10_feedthrough.removed"
    removed_before_error = removed_path.read_text(encoding="utf-8")
    inventory_before_error = inventory.read_text(encoding="utf-8")
    invalid = sh(["--run-root", root, "--scenario", "common"], root)
    require(invalid.returncode == 1, "missing SDC terminal row without independent basis should fail")
    require(output.read_text(encoding="utf-8") == sentinel, "error run overwrote formal SDC")
    require(pending_snapshot(root) == pending_before_error, "error run changed pending")
    require(removed_path.read_text(encoding="utf-8") == removed_before_error, "error run changed removed log")
    require(inventory.read_text(encoding="utf-8") == inventory_before_error, "error run changed inventory")

    update_review_rows(
        form,
        {"CONN_OUT_B0": {"sdc_independent_basis": "integration owner approved without destination SDC"}},
    )
    independent = sh(["--run-root", root, "--scenario", "common"], root)
    require(independent.returncode == 0, "approved SDC-independent terminal disposition should pass")
    sentinel = output.read_text(encoding="utf-8")
    strict_pending = pending_snapshot(root)
    strict_removed = removed_path.read_text(encoding="utf-8")
    strict_inventory = inventory.read_text(encoding="utf-8")

    strict = sh(["--run-root", root, "--scenario", "common", "--require-complete-harden-sdc"], root)
    require(strict.returncode == 1, "strict missing-SDC run should fail")
    require(output.read_text(encoding="utf-8") == sentinel, "strict error run overwrote formal SDC")
    require(pending_snapshot(root) == strict_pending, "strict run changed pending")
    require(removed_path.read_text(encoding="utf-8") == strict_removed, "strict run changed removed log")
    require(inventory.read_text(encoding="utf-8") == strict_inventory, "strict run changed inventory")


def run_scenario_isolation():
    root = WORK / "scenario"
    build_root(root, scenario="common")
    common = sh(["--run-root", root, "--scenario", "common"], root)
    require(common.returncode == 1, "common first sync should stop")
    form = root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(form, {"CONN_IN_B0": approved_no_budget()}, scenario="common")
    common_second = sh(["--run-root", root, "--scenario", "common"], root)
    require(common_second.returncode == 0, "approved common view should complete")
    common_pending = pending_snapshot(root, "common")
    require("output data_o[0]" not in common_pending["u_src.ports"], "common terminal edge was not consumed")
    common_removed_path = root / "10_middle" / "scenario" / "common" / "removed_log" / "10_feedthrough.removed"
    common_removed = common_removed_path.read_text(encoding="utf-8")
    require("connection_id=CONN_IN_B0" in common_removed, "common removal evidence missing")

    write_manifest_and_sdcs(root, "func")
    write_clock_inputs(root, "func")
    write_pending(root, "func")
    func = sh(["--run-root", root, "--scenario", "func"], root)
    require(func.returncode == 1, "func first sync should independently stop")
    require((root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv").is_file(), "common inventory missing")
    require((root / "10_middle" / "scenario" / "func" / "feedthrough_edge_inventory.csv").is_file(), "func inventory missing")
    func_pending = (root / "00_middle" / "scenario" / "func" / "pending" / "u_ft1.ports").read_text(encoding="utf-8")
    require("fti_local[4]" in func_pending, "common disposition/removal replayed into func")
    require(common_removed_path.read_text(encoding="utf-8") == common_removed, "func sync changed common removed log")
    common_ids = {
        row["connection_id"]: row["feedthrough_edge_id"]
        for row in read_csv_rows(root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv")
    }
    func_ids = {
        row["connection_id"]: row["feedthrough_edge_id"]
        for row in read_csv_rows(root / "10_middle" / "scenario" / "func" / "feedthrough_edge_inventory.csv")
    }
    require(common_ids == func_ids, "feedthrough edge IDs are not stable across scenarios")
    update_review_rows(form, {"CONN_IN_B0": approved_no_budget()}, scenario="func")
    func_second = sh(["--run-root", root, "--scenario", "func"], root)
    require(func_second.returncode == 0, "approved func view should generate independently")
    require((root / "10_result" / "scenarios" / "func_feedthrough.sdc").is_file(), "func SDC path missing")
    require((root / "10_middle" / "scenario" / "func" / "removed_log" / "10_feedthrough.removed").is_file(), "func removed log missing")
    require(common_removed_path.read_text(encoding="utf-8") == common_removed, "func terminal run changed common removed log")


def run_stage_corner_isolation():
    root = WORK / "stage_corner"
    build_root(root)
    all_sync = sh(["--run-root", root, "--scenario", "common"], root)
    require(all_sync.returncode == 1, "all/all first sync should stop")

    specific_sync = sh(
        ["--run-root", root, "--scenario", "common", "--stage", "synth", "--corner", "ss"],
        root,
    )
    require(specific_sync.returncode == 1, "synth/ss first sync should stop for review")
    specific_report = (root / "10_result" / "reports" / "feedthrough_check_report_common.txt").read_text(encoding="utf-8")
    require("Errors: 0" in specific_report, "all/all rows conflicted with the synth/ss exact view")

    form = root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(
        form,
        {"CONN_IN_B0": approved_no_budget()},
        scenario="common",
        stage="synth",
        corner="ss",
    )
    specific = sh(
        ["--run-root", root, "--scenario", "common", "--stage", "synth", "--corner", "ss"],
        root,
    )
    require(specific.returncode == 0, "approved synth/ss view failed:\n%s\n%s" % (specific.stdout, specific.stderr))
    require(
        (root / "10_result" / "common" / "10_feedthrough_synth_ss.sdc").is_file(),
        "stage/corner-specific SDC path missing",
    )
    inventory_rows = read_csv_rows(
        root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv"
    )
    require(len(inventory_rows) == 12, "inventory did not preserve independent all/all and synth/ss rows")


def run_optional_clock_relation_diagnostics():
    missing_root = WORK / "optional_diagnostics_missing"
    build_root(missing_root)
    shutil.rmtree(str(missing_root / "01_middle"))
    shutil.rmtree(str(missing_root / "03_middle"))
    first = sh(["--run-root", missing_root, "--scenario", "common"], missing_root)
    require(first.returncode == 1, "missing optional diagnostics first sync should stop only for review")
    report_path = missing_root / "10_result" / "reports" / "feedthrough_check_report_common.txt"
    report = report_path.read_text(encoding="utf-8")
    require("Errors: 0" in report, "missing optional 01/03 diagnostics incorrectly caused an error")
    require("WARNING:" in report, "missing optional 01/03 diagnostics were not reported as warnings")
    require(
        "clock" in report.lower() and "relation" in report.lower(),
        "missing optional diagnostic warning lacks clock/relation context",
    )
    missing_inventory = {
        row["connection_id"]: row
        for row in read_csv_rows(
            missing_root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv"
        )
    }
    require(
        missing_inventory["CONN_IN_B0"]["src_clock"] == "unresolved:clk_a"
        and missing_inventory["CONN_IN_B0"]["dst_clock"] == "unresolved:clk_a"
        and missing_inventory["CONN_IN_B0"]["clock_relation"] == "unknown",
        "same local clock names were incorrectly treated as a synchronous SoC clock",
    )
    form = missing_root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(form, {"CONN_IN_B0": approved_emit("1.0")})
    approved = sh(["--run-root", missing_root, "--scenario", "common"], missing_root)
    require(approved.returncode == 0, "missing optional diagnostics blocked an approved physical budget")
    output = missing_root / "10_result" / "common" / "10_feedthrough.sdc"
    require(
        "set_max_delay 1 -datapath_only" in output.read_text(encoding="utf-8"),
        "approved physical budget was not emitted without optional diagnostics",
    )

    relation_root = WORK / "clock_relation_diagnostic"
    build_root(relation_root)
    ft1_sdc = relation_root / "inputs" / "u_ft1.sdc"
    ft1_sdc.write_text(
        ft1_sdc.read_text(encoding="utf-8").replace(
            "set_input_delay -max 1.8 -clock [get_clocks {clk_a}]",
            "set_input_delay -max 1.8 -clock [get_clocks {clk_b}]",
            1,
        ),
        encoding="utf-8",
    )
    write_relation_input(relation_root, relation_type="asynchronous")
    relation_sync = sh(["--run-root", relation_root, "--scenario", "common"], relation_root)
    require(relation_sync.returncode == 1, "async diagnostic first sync should stop only for review")
    inventory = relation_root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv"
    inventory_rows = {row["connection_id"]: row for row in read_csv_rows(inventory)}
    require(
        inventory_rows["CONN_IN_B0"]["clock_relation"] == "asynchronous",
        "cross-clock async relation was not recorded as diagnostic metadata",
    )
    relation_form = relation_root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(relation_form, {"CONN_IN_B0": approved_emit("1.0")})
    async_emit = sh(["--run-root", relation_root, "--scenario", "common"], relation_root)
    require(async_emit.returncode == 0, "async clock diagnostic incorrectly required a relationship override")
    before = workbook_row_values(relation_form, "CONN_IN_B0")
    require(not before.get("relationship_override_basis"), "test fixture unexpectedly supplied an override")
    relation_output = relation_root / "10_result" / "common" / "10_feedthrough.sdc"
    stable_sdc = relation_output.read_text(encoding="utf-8")

    write_relation_input(relation_root, relation_type="not_a_relation")
    invalid = sh(["--run-root", relation_root, "--scenario", "common"], relation_root)
    require(invalid.returncode == 0, "invalid optional relation enum blocked an approved physical budget")
    invalid_report = (
        relation_root / "10_result" / "reports" / "feedthrough_check_report_common.txt"
    ).read_text(encoding="utf-8")
    require("Errors: 0" in invalid_report, "invalid optional relation enum was promoted to an error")
    require(
        "invalid" in invalid_report.lower() and "relation" in invalid_report.lower(),
        "invalid optional relation enum warning was not reported",
    )
    after = workbook_row_values(relation_form, "CONN_IN_B0")
    require(after["apply"] == "yes" and after["review_status"] == "approved", "clock diagnostic reset approval")
    require(after["machine_digest"] == before["machine_digest"], "clock diagnostic changed machine digest")
    require(
        after["approved_machine_digest"] == before["approved_machine_digest"],
        "clock diagnostic changed approved machine digest",
    )
    require(relation_output.read_text(encoding="utf-8") == stable_sdc, "clock diagnostic changed physical SDC")

    write_relation_input(relation_root, relation_type="asynchronous")
    final_clock_sdc = relation_root / "01_result" / "common" / "01_soc_clocks.sdc"
    final_clock_sdc.write_text(
        final_clock_sdc.read_text(encoding="utf-8") + "# stale diagnostic mutation\n",
        encoding="utf-8",
    )
    stale_clock = sh(["--run-root", relation_root, "--scenario", "common"], relation_root)
    require(stale_clock.returncode == 0, "stale optional clock SDC blocked physical budget")
    stale_report = (
        relation_root / "10_result" / "reports" / "feedthrough_check_report_common.txt"
    ).read_text(encoding="utf-8")
    require("clock diagnostic stale" in stale_report.lower(), "stale final clock SDC was not diagnosed")
    stale_row = workbook_row_values(relation_form, "CONN_IN_B0")
    require(
        stale_row["apply"] == "yes"
        and stale_row["review_status"] == "approved"
        and stale_row["machine_digest"] == before["machine_digest"],
        "stale clock diagnostic invalidated physical budget approval",
    )
    require(relation_output.read_text(encoding="utf-8") == stable_sdc, "stale clock diagnostic changed physical SDC")


def run_bus_compaction():
    root = WORK / "bus_compaction"
    build_root(root)
    first = sh(["--run-root", root, "--scenario", "common"], root)
    require(first.returncode == 1, "bus compaction first sync should stop for review")
    form = root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(
        form,
        {
            "CONN_IN_B0": approved_emit("1.1"),
            "CONN_IN_B1": approved_emit("1.1"),
        },
    )
    merged_run = sh(["--run-root", root, "--scenario", "common"], root)
    require(merged_run.returncode == 0, "homogeneous bus budget failed")
    output = root / "10_result" / "common" / "10_feedthrough.sdc"
    merged_sdc = output.read_text(encoding="utf-8")
    merged_command = (
        "set_max_delay 1.1 -datapath_only "
        "-from [get_pins {u_src/data_o[0] u_src/data_o[1]}] "
        "-to [get_pins {u_ft1/fti_local[4] u_ft1/fti_local[5]}]"
    )
    require(delay_command_lines(merged_sdc) == [merged_command], "homogeneous bus was not compacted exactly once")
    require(
        "FTE_CONN_IN_B0" in merged_sdc
        and "FTE_CONN_IN_B1" in merged_sdc
        and "CONN_IN_B0" in merged_sdc
        and "CONN_IN_B1" in merged_sdc,
        "merged command comment does not preserve all bit-level IDs",
    )
    require("*" not in merged_command and ":" not in merged_command, "merged command used wildcard/range selection")
    inventory = root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv"
    inventory_ids = [row["connection_id"] for row in read_csv_rows(inventory)]
    require(inventory_ids.count("CONN_IN_B0") == 1 and inventory_ids.count("CONN_IN_B1") == 1, "bus merge changed bit inventory")
    removed_path = root / "10_middle" / "scenario" / "common" / "removed_log" / "10_feedthrough.removed"
    removed = removed_path.read_text(encoding="utf-8")
    require("connection_id=CONN_IN_B0" in removed and "connection_id=CONN_IN_B1" in removed, "bus merge lost per-bit removal evidence")
    pending = pending_snapshot(root)
    require("output data_o[0]" not in pending["u_src.ports"] and "output data_o[1]" not in pending["u_src.ports"], "bus merge did not consume source bits independently")
    require("input fti_local[4]" not in pending["u_ft1.ports"] and "input fti_local[5]" not in pending["u_ft1.ports"], "bus merge did not consume destination bits independently")
    stable_sdc = merged_sdc
    rerun = sh(["--run-root", root, "--scenario", "common"], root)
    require(rerun.returncode == 0 and output.read_text(encoding="utf-8") == stable_sdc, "bus merge is not deterministic")

    update_review_rows(form, {"CONN_IN_B1": approved_emit("1.2")})
    split = sh(["--run-root", root, "--scenario", "common"], root)
    require(split.returncode == 0, "heterogeneous bus fallback failed")
    split_commands = delay_command_lines(output.read_text(encoding="utf-8"))
    require(len(split_commands) == 2, "different per-bit values were incorrectly merged")
    require(
        any("set_max_delay 1.1" in line and "u_src/data_o[0]" in line for line in split_commands)
        and any("set_max_delay 1.2" in line and "u_src/data_o[1]" in line for line in split_commands),
        "different per-bit values did not fall back to canonical bit commands",
    )

    reverse_root = WORK / "bus_reverse_mapping"
    build_root(reverse_root)
    reverse_sync = sh(["--run-root", reverse_root, "--scenario", "common"], reverse_root)
    require(reverse_sync.returncode == 1, "reverse-map first sync should stop for review")
    reverse_form = reverse_root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(
        reverse_form,
        {
            "CONN_MID_B0": approved_emit("0.8"),
            "CONN_MID_B1": approved_emit("0.8"),
        },
    )
    reverse_run = sh(["--run-root", reverse_root, "--scenario", "common"], reverse_root)
    require(reverse_run.returncode == 0, "reverse-map per-bit generation failed")
    reverse_sdc = (
        reverse_root / "10_result" / "common" / "10_feedthrough.sdc"
    ).read_text(encoding="utf-8")
    reverse_commands = delay_command_lines(reverse_sdc)
    require(len(reverse_commands) == 2, "reverse bit mapping was incorrectly compacted")
    require(
        any("fto_local[4]" in line and "fti_transport[10]" in line for line in reverse_commands)
        and any("fto_local[5]" in line and "fti_transport[9]" in line for line in reverse_commands),
        "reverse bit mapping did not preserve exact per-bit endpoints",
    )

    fanout_root = WORK / "bus_fanout"
    fanout_edges = base_edges() + [
        (
            "CONN_FANOUT_B0", "harden_to_harden",
            "u_src", "output", "data_o[0]",
            "u_dst", "input", "fan_i",
        )
    ]
    build_root(fanout_root, edges=fanout_edges)
    fanout_sync = sh(["--run-root", fanout_root, "--scenario", "common"], fanout_root)
    require(fanout_sync.returncode == 1, "fanout first sync should stop for review")
    fanout_form = fanout_root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(
        fanout_form,
        {
            "CONN_IN_B0": approved_emit("1.1"),
            "CONN_IN_B1": approved_emit("1.1"),
        },
    )
    fanout_run = sh(["--run-root", fanout_root, "--scenario", "common"], fanout_root)
    require(fanout_run.returncode == 0, "fanout per-bit generation failed")
    fanout_commands = delay_command_lines(
        (fanout_root / "10_result" / "common" / "10_feedthrough.sdc").read_text(encoding="utf-8")
    )
    require(len(fanout_commands) == 2, "source fanout was incorrectly compacted into a bus command")


def run_scenario_scope_contract():
    root = WORK / "scenario_scope"
    build_root(root, scenario="func")
    update_connection_rows(
        root,
        {
            "CONN_IN_B1": {"scenario_scope": "func"},
            "CONN_MID_B0": {"scenario_scope": "func,scan"},
            "CONN_MID_B1": {
                "scenario_scope": "scan",
                "connection_type": "foreign_schema_typo",
                "src_soc_object": "",
            },
        },
    )
    result = sh(["--run-root", root, "--scenario", "func"], root)
    require(result.returncode == 1, "scenario-scope first sync should stop for review")
    report = report_text(root, "func")
    require("Errors: 0" in report, "valid scenario scopes caused an error")
    rows = {
        row["connection_id"]: row
        for row in read_csv_rows(
            root / "10_middle" / "scenario" / "func" / "feedthrough_edge_inventory.csv"
        )
    }
    require("CONN_IN_B0" in rows, "common-scoped edge missing from func effective view")
    require("CONN_IN_B1" in rows, "current-scenario edge missing from func effective view")
    require("CONN_MID_B0" in rows, "current scenario-list edge missing from func effective view")
    require("CONN_MID_B1" not in rows, "foreign-scenario edge leaked into func effective view")
    require(rows["CONN_IN_B1"]["scenario_scope"] == "func", "single scenario scope was not preserved")
    require(
        rows["CONN_MID_B0"]["scenario_scope"] == "func,scan",
        "stable scenario-list scope was not preserved",
    )

    unstable_root = WORK / "scenario_scope_unstable"
    build_root(unstable_root, scenario="func")
    update_connection_rows(
        unstable_root,
        {"CONN_IN_B0": {"scenario_scope": "scan,func"}},
    )
    unstable = sh(["--run-root", unstable_root, "--scenario", "func"], unstable_root)
    require(unstable.returncode == 1, "unstable scenario scope should fail")
    unstable_report = report_text(unstable_root, "func")
    require(
        "scenario_scope" in unstable_report and "invalid or unstable" in unstable_report,
        "unstable scenario-scope diagnostic missing",
    )

    empty_root = WORK / "scenario_scope_empty"
    build_root(empty_root, scenario="func")
    update_connection_rows(empty_root, {"CONN_IN_B0": {"scenario_scope": ""}})
    empty = sh(["--run-root", empty_root, "--scenario", "func"], empty_root)
    require(empty.returncode == 1, "empty target scenario scope should fail")
    require(
        "scenario_scope" in report_text(empty_root, "func"),
        "empty scenario-scope diagnostic missing",
    )

    missing_root = WORK / "scenario_scope_missing_column"
    build_root(missing_root, scenario="func")
    path = missing_root / "00_middle" / "connection_inventory.csv"
    missing_rows = read_csv_rows(path)
    missing_headers = [header for header in CONNECTION_HEADERS if header != "scenario_scope"]
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=missing_headers)
        writer.writeheader()
        for row in missing_rows:
            writer.writerow({header: row[header] for header in missing_headers})
    missing = sh(["--run-root", missing_root, "--scenario", "func"], missing_root)
    require(missing.returncode == 1, "missing target scenario_scope column should fail")
    missing_report = report_text(missing_root, "func")
    require(
        "missing field(s)" in missing_report and "scenario_scope" in missing_report,
        "missing scenario-scope schema diagnostic absent",
    )

    version_root = WORK / "connection_schema_version"
    build_root(version_root)
    update_connection_rows(version_root, {"CONN_IN_B0": {"schema_version": "2"}})
    version = sh(["--run-root", version_root, "--scenario", "common"], version_root)
    require(version.returncode == 1, "unsupported connection inventory version should fail")
    version_report = report_text(version_root)
    require(
        "unsupported schema_version=2" in version_report,
        "unsupported connection schema-version diagnostic missing",
    )


def run_target_cli_contract():
    no_scenario_root = WORK / "cli_scenario_required"
    build_root(no_scenario_root)
    no_scenario = sh(["--run-root", no_scenario_root], no_scenario_root)
    require(no_scenario.returncode != 0, "target mode accepted an omitted --scenario")
    require("scenario" in (no_scenario.stdout + no_scenario.stderr).lower(), "required scenario diagnostic missing")
    require(not (no_scenario_root / "10_middle" / "10_feedthrough.xlsx").exists(), "missing-scenario run mutated target artifacts")

    override_flags = (
        "--connection-inventory",
        "--harden-sdc-manifest",
        "--clock-inventory",
        "--clock-inventory-meta",
        "--relation-map",
        "--relation-map-meta",
        "--form",
        "--inventory",
        "--output",
        "--report",
        "--pending-root",
        "--20-channel-inventory",
    )
    for index, flag in enumerate(override_flags):
        root = WORK / ("cli_fixed_path_%02d" % index)
        build_root(root)
        result = sh(
            ["--run-root", root, "--scenario", "common", flag, root / "override_artifact"],
            root,
        )
        require(result.returncode != 0, "target mode accepted path override %s" % flag)
        require(
            not (root / "10_middle" / "10_feedthrough.xlsx").exists(),
            "rejected target override %s still mutated the fixed workbook" % flag,
        )

    force_root = WORK / "cli_force_removed"
    build_root(force_root)
    force = sh(
        ["--run-root", force_root, "--scenario", "common", "--force-generate-after-sync"],
        force_root,
    )
    require(force.returncode != 0, "removed force-generate option was still accepted")
    require(
        "force-generate-after-sync" in (force.stdout + force.stderr),
        "removed force option diagnostic missing",
    )
    require(
        not (force_root / "10_result" / "common" / "10_feedthrough.sdc").exists(),
        "removed force option bypassed mandatory review",
    )


def run_legacy_manifest_contract():
    root = WORK / "legacy_fixed_manifest"
    build_root(root)
    legacy = root / "00_harden_port_inventory"
    legacy.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        str(root / "00_middle" / "connection_inventory.csv"),
        str(legacy / "connection_inventory.csv"),
    )
    shutil.copy2(
        str(
            root
            / "00_middle"
            / "scenario"
            / "common"
            / "harden_sdc_manifest.csv"
        ),
        str(legacy / "harden_sdc_manifest.csv"),
    )
    shutil.copytree(
        str(root / "00_middle" / "scenario" / "common" / "pending"),
        str(legacy / "pending"),
    )
    shutil.rmtree(str(root / "00_middle"))
    result = sh(["--scenario", "common"], root)
    require(result.returncode == 1, "legacy fixed-manifest first sync should stop for review")
    report = (root / "feedthrough_check_report_common.txt").read_text(encoding="utf-8")
    manifest_path = (legacy / "harden_sdc_manifest.csv").resolve()
    require("Errors: 0" in report, "valid legacy fixed manifest caused an error")
    require(
        "Harden SDC manifest: %s" % manifest_path in report,
        "legacy mode did not report the fixed manifest path",
    )
    require("legacy inference" not in report.lower(), "legacy mode still inferred SDC paths by instance name")
    rows = read_csv_rows(root / "feedthrough_edge_inventory.csv")
    require(rows and all(row["src_sdc_status"] != "missing" for row in rows), "legacy fixed manifest was not used")


def run_review_gate_contract():
    cases = []

    empty_surface = approved_emit("1.0")
    empty_surface["tool_surface"] = ""
    cases.append(("empty_tool_surface", empty_surface, ("emit_budget", "tool_surface")))

    blank_no_budget_emit = approved_no_budget()
    blank_no_budget_emit["emit_max"] = ""
    blank_no_budget_emit["emit_min"] = ""
    cases.append(("blank_no_budget_emit", blank_no_budget_emit, ("no-budget", "emit_max")))

    unversioned_basis = approved_no_budget()
    unversioned_basis["disposition_basis"] = "project feedthrough policy approval"
    cases.append(("unversioned_no_budget_basis", unversioned_basis, ("versioned", "policy")))

    route_without_evidence = approved_route_to_30()
    route_without_evidence["reviewer"] = ""
    route_without_evidence["disposition_basis"] = ""
    cases.append(("route_missing_review", route_without_evidence, ("route_to_30", "reviewer")))

    for name, values, expected_tokens in cases:
        root = WORK / name
        build_root(root)
        first = sh(["--run-root", root, "--scenario", "common"], root)
        require(first.returncode == 1, "%s first sync should stop for review" % name)
        form = root / "10_middle" / "10_feedthrough.xlsx"
        update_review_rows(form, {"CONN_IN_B0": values})
        result = sh(["--run-root", root, "--scenario", "common"], root)
        require(result.returncode == 1, "%s invalid approval should fail" % name)
        report = report_text(root).lower()
        require(
            all(token.lower() in report for token in expected_tokens),
            "%s approval diagnostic missing: %s" % (name, expected_tokens),
        )
        require(
            not (root / "10_result" / "common" / "10_feedthrough.sdc").exists(),
            "%s invalid approval wrote formal SDC" % name,
        )


def run_manifest_contract():
    duplicate_root = WORK / "manifest_duplicate_path"
    build_root(duplicate_root)
    update_manifest_rows(
        duplicate_root,
        {"u_ft1": {"sdc_path": "inputs/u_src.sdc"}},
    )
    duplicate = sh(["--run-root", duplicate_root, "--scenario", "common"], duplicate_root)
    require(duplicate.returncode == 1, "duplicate available SDC path should fail")
    duplicate_report = report_text(duplicate_root)
    require(
        "available SDC path is shared" in duplicate_report,
        "duplicate available SDC path diagnostic missing",
    )

    no_basis_root = WORK / "manifest_not_required_basis"
    build_root(no_basis_root)
    update_manifest_rows(
        no_basis_root,
        {
            "u_dst": {
                "availability_status": "not_required",
                "sdc_path": "",
                "note": "",
            }
        },
    )
    no_basis = sh(["--run-root", no_basis_root, "--scenario", "common"], no_basis_root)
    require(no_basis.returncode == 1, "not_required manifest row without basis should fail")
    no_basis_report = report_text(no_basis_root)
    require(
        "not_required" in no_basis_report and "explicit note/basis" in no_basis_report,
        "not_required basis diagnostic missing",
    )

    schema_root = WORK / "manifest_required_columns"
    build_root(schema_root)
    path = schema_root / "00_middle" / "scenario" / "common" / "harden_sdc_manifest.csv"
    rows = read_csv_rows(path)
    headers = [header for header in rows[0] if header != "note"]
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row[header] for header in headers})
    schema = sh(["--run-root", schema_root, "--scenario", "common"], schema_root)
    require(schema.returncode == 1, "manifest missing required note column should fail")
    schema_report = report_text(schema_root)
    require(
        "HARDEN_SDC_MANIFEST_SCHEMA_ERROR" in schema_report and "note" in schema_report,
        "manifest required-column diagnostic missing",
    )


def run_pending_contract():
    malformed_root = WORK / "pending_malformed_without_terminal"
    build_root(malformed_root)
    malformed_file = (
        malformed_root / "00_middle" / "scenario" / "common" / "pending" / "u_dst.ports"
    )
    malformed_file.write_text(
        "input data_i[0]\n"
        "input data_i[0]\n"
        "sideways data_i[1]\n"
        "input data_i[1:0]\n"
        "malformed\n",
        encoding="utf-8",
    )
    malformed = sh(["--run-root", malformed_root, "--scenario", "common"], malformed_root)
    require(malformed.returncode == 1, "malformed pending should fail before terminal review")
    malformed_report = report_text(malformed_root).lower()
    require("errors: 0" not in malformed_report, "malformed pending produced no formal error")
    require("pending" in malformed_report, "malformed pending diagnostic missing")
    require("duplicate" in malformed_report, "duplicate pending-line diagnostic missing")
    require(
        "direction" in malformed_report or "sideways" in malformed_report,
        "invalid pending direction diagnostic missing",
    )
    require(
        "canonical" in malformed_report or "range" in malformed_report,
        "non-canonical pending port diagnostic missing",
    )
    require(
        not (malformed_root / "10_result" / "common" / "10_feedthrough.sdc").exists(),
        "malformed pending run wrote formal SDC",
    )

    missing_root = WORK / "pending_manifest_file_missing"
    build_root(missing_root)
    (
        missing_root / "00_middle" / "scenario" / "common" / "pending" / "u_dst.ports"
    ).unlink()
    missing = sh(["--run-root", missing_root, "--scenario", "common"], missing_root)
    require(missing.returncode == 1, "missing manifest harden pending file should fail")
    missing_report = report_text(missing_root).lower()
    require(
        "pending" in missing_report and "u_dst" in missing_report and "missing" in missing_report,
        "missing manifest pending-file diagnostic absent",
    )

    disabled_root = WORK / "pending_accounting_disabled"
    build_root(disabled_root)
    shutil.rmtree(str(disabled_root / "00_middle" / "scenario" / "common" / "pending"))
    first = sh(
        ["--run-root", disabled_root, "--scenario", "common", "--no-update-pending"],
        disabled_root,
    )
    require(first.returncode == 1, "accounting-disabled first sync should stop only for review")
    disabled_phrase = "Port accounting: disabled by explicit option"
    require(disabled_phrase in first.stdout, "accounting-disabled stdout metadata missing")
    first_report = report_text(disabled_root)
    require("Errors: 0" in first_report, "missing pending blocked explicit accounting-disabled run")
    require(disabled_phrase in first_report, "accounting-disabled report metadata missing")
    form = disabled_root / "10_middle" / "10_feedthrough.xlsx"
    form_row = workbook_row_values(form, "CONN_IN_B0")
    require(
        form_row["port_accounting"] == "disabled by explicit option",
        "accounting-disabled workbook metadata missing",
    )
    update_review_rows(form, {"CONN_IN_B0": approved_emit("1.0")})
    second = sh(
        ["--run-root", disabled_root, "--scenario", "common", "--no-update-pending"],
        disabled_root,
    )
    require(second.returncode == 0, "accounting-disabled approved generation failed")
    output = disabled_root / "10_result" / "common" / "10_feedthrough.sdc"
    sdc = output.read_text(encoding="utf-8")
    require("# " + disabled_phrase in sdc, "accounting-disabled SDC metadata missing")
    rows = read_csv_rows(
        disabled_root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv"
    )
    require(
        all(row["port_accounting"] == "disabled by explicit option" for row in rows),
        "accounting-disabled inventory metadata missing",
    )
    require(
        not (
            disabled_root
            / "10_middle"
            / "scenario"
            / "common"
            / "removed_log"
            / "10_feedthrough.removed"
        ).exists(),
        "accounting-disabled run wrote a removal log",
    )


def run_assembled_view_contract():
    root = WORK / "assembled_common_scenario"
    build_root(root, scenario="common")
    first_common = sh(
        ["--run-root", root, "--scenario", "common", "--no-update-pending"],
        root,
    )
    require(first_common.returncode == 1, "common assembled-view first sync should stop")
    form = root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(form, {"CONN_IN_B0": approved_emit("1.0")}, scenario="common")
    common = sh(
        ["--run-root", root, "--scenario", "common", "--no-update-pending"],
        root,
    )
    require(common.returncode == 0, "approved common overlay failed")

    write_manifest_and_sdcs(root, "func")
    write_clock_inputs(root, "func")
    write_pending(root, "func")
    first_func = sh(
        ["--run-root", root, "--scenario", "func", "--no-update-pending"],
        root,
    )
    require(first_func.returncode == 1, "func assembled-view first sync should stop")
    update_review_rows(form, {"CONN_IN_B0": approved_emit("1.2")}, scenario="func")
    conflict = sh(
        ["--run-root", root, "--scenario", "func", "--no-update-pending"],
        root,
    )
    require(conflict.returncode == 1, "conflicting common/func direct-edge commands should fail")
    conflict_report = report_text(root, "func").lower()
    require(
        "common" in conflict_report and "conflict" in conflict_report and "conn_in_b0" in conflict_report,
        "assembled common/scenario conflict diagnostic missing",
    )
    func_output = root / "10_result" / "scenarios" / "func_feedthrough.sdc"
    require(not func_output.exists(), "conflicting scenario overlay wrote formal SDC")

    update_review_rows(form, {"CONN_IN_B0": approved_emit("1.0")}, scenario="func")
    identical = sh(
        ["--run-root", root, "--scenario", "func", "--no-update-pending"],
        root,
    )
    require(identical.returncode == 0, "identical common/func command should assemble cleanly")
    require(
        not delay_command_lines(func_output.read_text(encoding="utf-8")),
        "identical common command was redundantly emitted in the scenario overlay",
    )


def run_previous_owner_contract():
    unrelated_root = WORK / "previous_owner_unrelated"
    build_root(unrelated_root)
    first = sh(["--run-root", unrelated_root, "--scenario", "common"], unrelated_root)
    require(first.returncode == 1, "previous-owner unrelated first sync should stop")
    remove_pending_entry(unrelated_root, "u_src", "output", "normal_o")
    prior_path = (
        unrelated_root
        / "04_middle"
        / "scenario"
        / "common"
        / "removed_log"
        / "04_soc_io_pads.removed"
    )
    prior_path.parent.mkdir(parents=True, exist_ok=True)
    prior_path.write_text(
        "u_src output normal_o covered_by=04_soc_io_pads reason=regression\n",
        encoding="utf-8",
    )
    form = unrelated_root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(form, {"CONN_IN_B0": approved_no_budget()})
    unrelated = sh(["--run-root", unrelated_root, "--scenario", "common"], unrelated_root)
    require(unrelated.returncode == 0, "unrelated prior owner incorrectly blocked 10")

    conflict_root = WORK / "previous_owner_conflict"
    build_root(conflict_root)
    first = sh(["--run-root", conflict_root, "--scenario", "common"], conflict_root)
    require(first.returncode == 1, "previous-owner conflict first sync should stop")
    form = conflict_root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(form, {"CONN_IN_B0": approved_no_budget()})
    remove_pending_entry(conflict_root, "u_src", "output", "data_o[0]")
    prior_path = (
        conflict_root
        / "04_middle"
        / "scenario"
        / "common"
        / "removed_log"
        / "04_soc_io_pads.removed"
    )
    prior_path.parent.mkdir(parents=True, exist_ok=True)
    prior_path.write_text(
        "u_src output data_o[0] covered_by=04_soc_io_pads reason=regression\n",
        encoding="utf-8",
    )
    retained = sh(["--run-root", conflict_root, "--scenario", "common"], conflict_root)
    require(retained.returncode == 0, "fixed prior owner incorrectly changed edge classification")
    retained_report = report_text(conflict_root).lower()
    require(
        "04_soc_io_pads" in retained_report
        and "retained previous port-level removal owner" in retained_report,
        "retained previous port-owner diagnostic missing",
    )
    removed_path = (
        conflict_root
        / "10_middle"
        / "scenario"
        / "common"
        / "removed_log"
        / "10_feedthrough.removed"
    )
    removed = removed_path.read_text(encoding="utf-8")
    require(
        "u_src output data_o[0]" not in removed,
        "10 removal log duplicated a fixed earlier port owner",
    )
    require(
        "u_ft1 input fti_local[4]" in removed,
        "unowned endpoint of a terminal edge was not accounted by 10",
    )


def run_direction_and_ownership_errors():
    wrong_root = WORK / "wrong_direction"
    wrong_edges = base_edges()
    first = list(wrong_edges[0])
    first[6] = "output"
    wrong_edges[0] = tuple(first)
    build_root(wrong_root, edges=wrong_edges)
    wrong = sh(["--run-root", wrong_root, "--scenario", "common"], wrong_root)
    require(wrong.returncode == 1, "wrong fti direction should fail")
    report = (wrong_root / "10_result" / "reports" / "feedthrough_check_report_common.txt").read_text(encoding="utf-8")
    require("fti_* feedthrough boundary must be input" in report, "wrong direction diagnostic missing")
    require(not (wrong_root / "10_middle" / "10_feedthrough.xlsx").exists(), "structural error should not create workbook")

    inout_root = WORK / "inout_boundary"
    inout_edges = base_edges()
    inout_edge = list(inout_edges[0])
    inout_edge[6] = "inout"
    inout_edges[0] = tuple(inout_edge)
    build_root(inout_root, edges=inout_edges)
    inout = sh(["--run-root", inout_root, "--scenario", "common"], inout_root)
    require(inout.returncode == 1, "inout feedthrough boundary should fail")
    inout_report = (
        inout_root / "10_result" / "reports" / "feedthrough_check_report_common.txt"
    ).read_text(encoding="utf-8")
    require(
        "fti_* feedthrough boundary must be input, got inout" in inout_report,
        "inout structural diagnostic missing",
    )
    require(not (inout_root / "10_middle" / "10_feedthrough.xlsx").exists(), "inout boundary created terminal workbook rows")

    owner_root = WORK / "pseudo_boundary_owner"
    owner_edges = base_edges()
    owner_edge = list(owner_edges[0])
    owner_edge[1] = "harden_to_fabric"
    owner_edge[5] = "fabric"
    owner_edges[0] = tuple(owner_edge)
    build_root(owner_root, edges=owner_edges)
    bad_owner = sh(["--run-root", owner_root, "--scenario", "common"], owner_root)
    require(bad_owner.returncode == 1, "pseudo instance should not own a feedthrough boundary")
    owner_report = (
        owner_root / "10_result" / "reports" / "feedthrough_check_report_common.txt"
    ).read_text(encoding="utf-8")
    require(
        "fabric" in owner_report.lower()
        and "feedthrough" in owner_report.lower()
        and ("harden" in owner_report.lower() or "manifest" in owner_report.lower()),
        "pseudo boundary ownership diagnostic missing",
    )
    require(not (owner_root / "10_middle" / "10_feedthrough.xlsx").exists(), "invalid boundary owner created workbook rows")

    ctype_root = WORK / "connection_type_typo"
    ctype_edges = base_edges()
    ctype_edge = list(ctype_edges[0])
    ctype_edge[1] = "clok_connection"
    ctype_edges[0] = tuple(ctype_edge)
    build_root(ctype_root, edges=ctype_edges)
    bad_ctype = sh(["--run-root", ctype_root, "--scenario", "common"], ctype_root)
    require(bad_ctype.returncode == 1, "schema-external connection_type typo should fail")
    ctype_report = (
        ctype_root / "10_result" / "reports" / "feedthrough_check_report_common.txt"
    ).read_text(encoding="utf-8")
    require(
        "connection_type" in ctype_report and "clok_connection" in ctype_report,
        "connection_type enum diagnostic missing",
    )
    require(not (ctype_root / "10_middle" / "10_feedthrough.xlsx").exists(), "invalid connection_type created workbook rows")

    no_soc_root = WORK / "no_soc_policy_owner"
    build_root(no_soc_root)
    no_soc_sync = sh(["--run-root", no_soc_root, "--scenario", "common"], no_soc_root)
    require(no_soc_sync.returncode == 1, "no-soc policy test first sync should stop")
    no_soc_form = no_soc_root / "10_middle" / "10_feedthrough.xlsx"
    incomplete_policy = approved_no_budget()
    incomplete_policy["owner"] = ""
    update_review_rows(no_soc_form, {"CONN_IN_B0": incomplete_policy})
    no_soc = sh(["--run-root", no_soc_root, "--scenario", "common"], no_soc_root)
    require(no_soc.returncode == 1, "no_soc_budget_required without policy owner should fail")
    no_soc_report = (
        no_soc_root / "10_result" / "reports" / "feedthrough_check_report_common.txt"
    ).read_text(encoding="utf-8")
    require(
        "no-budget" in no_soc_report.lower() and "owner" in no_soc_report.lower(),
        "no-soc policy owner diagnostic missing",
    )

    excluded_root = WORK / "excluded_ownership"
    excluded_edges = base_edges() + [
        ("CONN_PAD_SKIP", "top_pad_to_harden", "top", "output", "pad_sig", "u_ft1", "output", "fti_pad")
    ]
    build_root(excluded_root, edges=excluded_edges)
    excluded = sh(["--run-root", excluded_root, "--scenario", "common"], excluded_root)
    require(excluded.returncode == 1, "excluded ownership first sync should stop only for review")
    excluded_report = (excluded_root / "10_result" / "reports" / "feedthrough_check_report_common.txt").read_text(encoding="utf-8")
    require("Errors: 0" in excluded_report, "01/04-owned row incorrectly blocked 10")
    excluded_ids = {
        row["connection_id"]
        for row in read_csv_rows(excluded_root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv")
    }
    require("CONN_PAD_SKIP" not in excluded_ids, "01/04-owned edge leaked into 10")

    object_root = WORK / "object_mismatch"
    build_root(object_root)
    update_connection_rows(
        object_root,
        {"CONN_IN_B0": {"src_soc_object": "[get_pins {u_dst/data_i[0]}]"}},
    )
    object_run = sh(["--run-root", object_root, "--scenario", "common"], object_root)
    require(object_run.returncode == 1, "mismatched SoC endpoint object should fail")
    object_report = (object_root / "10_result" / "reports" / "feedthrough_check_report_common.txt").read_text(encoding="utf-8")
    require("does not match canonical direct endpoint" in object_report, "SoC endpoint mismatch diagnostic missing")

    parse_root = WORK / "sdc_parse_error"
    build_root(parse_root)
    (parse_root / "inputs" / "u_ft1.sdc").write_text(
        "set_input_delay -max 1.0 -clock [get_clocks {clk_a}] [get_ports {fti_local[4]}\n",
        encoding="utf-8",
    )
    parse_run = sh(["--run-root", parse_root, "--scenario", "common"], parse_root)
    require(parse_run.returncode == 1, "unterminated harden SDC command should fail")
    parse_report = (parse_root / "10_result" / "reports" / "feedthrough_check_report_common.txt").read_text(encoding="utf-8")
    require("unterminated Tcl command" in parse_report, "SDC parse error diagnostic missing")

    relation_root = WORK / "relation_scenario"
    build_root(relation_root)
    relation_path = relation_root / "03_middle" / "relation_map" / "common.csv"
    relation_path.write_text(
        relation_path.read_text(encoding="utf-8").replace(",common,", ",func,"),
        encoding="utf-8",
    )
    relation_run = sh(["--run-root", relation_root, "--scenario", "common"], relation_root)
    require(relation_run.returncode == 1, "wrong-scenario relation first sync should stop only for review")
    relation_report = (relation_root / "10_result" / "reports" / "feedthrough_check_report_common.txt").read_text(encoding="utf-8")
    require("Errors: 0" in relation_report, "wrong-scenario optional relation map caused an error")
    require(
        "scenario" in relation_report.lower()
        and ("stale" in relation_report.lower() or "mismatch" in relation_report.lower()),
        "relation scenario warning missing",
    )
    relation_form = relation_root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(relation_form, {"CONN_IN_B0": approved_emit("1.0")})
    relation_approved = sh(["--run-root", relation_root, "--scenario", "common"], relation_root)
    require(relation_approved.returncode == 0, "wrong-scenario optional relation blocked physical budget")

    id_root = WORK / "literal_id"
    id_edges = base_edges()
    first_id = list(id_edges[0])
    first_id[0] = "CONN-IN-B0"
    id_edges[0] = tuple(first_id)
    build_root(id_root, edges=id_edges)
    id_sync = sh(["--run-root", id_root, "--scenario", "common"], id_root)
    require(id_sync.returncode == 1, "literal ID first sync should stop for review")
    id_rows = read_csv_rows(id_root / "10_middle" / "scenario" / "common" / "feedthrough_edge_inventory.csv")
    literal_row = next(row for row in id_rows if row["connection_id"] == "CONN-IN-B0")
    require(literal_row["feedthrough_edge_id"] == "FTE_CONN-IN-B0", "connection_id was rewritten in FTE ID")

    excluded_future_root = WORK / "no_connect_and_future_20"
    excluded_future_edges = base_edges() + [
        (
            "CONN_NC_SKIP",
            "no_connect",
            "no_connect",
            "output",
            "nc_sig",
            "u_ft1",
            "output",
            "fti_nc",
        )
    ]
    build_root(excluded_future_root, edges=excluded_future_edges)
    future_20_path = (
        excluded_future_root
        / "20_middle"
        / "scenario"
        / "common"
        / "channel_inventory.csv"
    )
    future_20_path.parent.mkdir(parents=True, exist_ok=True)
    future_20_path.write_text("malformed_future_stage_artifact\n", encoding="utf-8")
    excluded_future = sh(
        ["--run-root", excluded_future_root, "--scenario", "common"],
        excluded_future_root,
    )
    require(excluded_future.returncode == 1, "no-connect/future-20 first sync should stop only for review")
    excluded_future_report = report_text(excluded_future_root)
    require("Errors: 0" in excluded_future_report, "legal no_connect or future 20 artifact blocked 10")
    excluded_future_ids = {
        row["connection_id"]
        for row in read_csv_rows(
            excluded_future_root
            / "10_middle"
            / "scenario"
            / "common"
            / "feedthrough_edge_inventory.csv"
        )
    }
    require("CONN_NC_SKIP" not in excluded_future_ids, "no_connect edge leaked into 10 ownership")

    datapath_root = WORK / "datapath_gate"
    build_root(datapath_root)
    datapath_sync = sh(["--run-root", datapath_root, "--scenario", "common"], datapath_root)
    require(datapath_sync.returncode == 1, "datapath gate first sync should stop")
    datapath_form = datapath_root / "10_middle" / "10_feedthrough.xlsx"
    bad_datapath = approved_emit("1.0")
    bad_datapath["datapath_only"] = "no"
    update_review_rows(datapath_form, {"CONN_IN_B0": bad_datapath})
    datapath_run = sh(["--run-root", datapath_root, "--scenario", "common"], datapath_root)
    require(datapath_run.returncode == 1, "emit_budget without datapath_only should fail")
    datapath_report = (datapath_root / "10_result" / "reports" / "feedthrough_check_report_common.txt").read_text(encoding="utf-8")
    require("emit_budget requires datapath_only=yes" in datapath_report, "datapath gate diagnostic missing")

    missing_pending_root = WORK / "missing_pending"
    build_root(missing_pending_root)
    pending_sync = sh(["--run-root", missing_pending_root, "--scenario", "common"], missing_pending_root)
    require(pending_sync.returncode == 1, "missing-pending first sync should stop")
    pending_form = missing_pending_root / "10_middle" / "10_feedthrough.xlsx"
    update_review_rows(pending_form, {"CONN_IN_B0": approved_no_budget()})
    shutil.rmtree(str(missing_pending_root / "00_middle" / "scenario" / "common" / "pending"))
    missing_pending = sh(["--run-root", missing_pending_root, "--scenario", "common"], missing_pending_root)
    require(missing_pending.returncode == 1, "missing required pending directory should fail")
    missing_pending_report = (missing_pending_root / "10_result" / "reports" / "feedthrough_check_report_common.txt").read_text(encoding="utf-8")
    require("pending directory not found" in missing_pending_report, "missing pending diagnostic absent")
    require(not (missing_pending_root / "10_result" / "common" / "10_feedthrough.sdc").exists(), "missing-pending run wrote formal SDC")


def main():
    clean_dir(WORK)
    run_direct_edge_lifecycle()
    run_partial_and_strict()
    run_scenario_isolation()
    run_stage_corner_isolation()
    run_optional_clock_relation_diagnostics()
    run_bus_compaction()
    run_scenario_scope_contract()
    run_target_cli_contract()
    run_legacy_manifest_contract()
    run_review_gate_contract()
    run_manifest_contract()
    run_pending_contract()
    run_assembled_view_contract()
    run_previous_owner_contract()
    run_direction_and_ownership_errors()
    print("10 feedthrough edge-centric regression: PASS")
    print(
        "  cases: lifecycle, partial_strict, scenario_isolation, stage_corner, "
        "optional_clock_diagnostics, bus_compaction, scenario_scope, target_cli, legacy_manifest, "
        "review_gates, manifest, pending, assembled_view, previous_owner, ownership_errors"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
