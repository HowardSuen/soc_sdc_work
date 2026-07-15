#!/usr/bin/env python3
"""Build the self-contained target-layout 01 -> 04 demo inputs."""

from __future__ import print_function

import csv
import shutil
from pathlib import Path

import pandas as pd


BASE = Path(__file__).resolve().parent
RUN_ROOT = BASE / "run"
INPUTS = RUN_ROOT / "inputs"

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


def soc_object(instance, port):
    return port if instance == "top" else "%s/%s" % (instance, port)


def port_sheet(rows):
    frame = pd.DataFrame(rows)
    for column in PORT_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[PORT_COLUMNS].fillna("")


def write_connection_inventory():
    path = RUN_ROOT / "00_middle/connection_inventory.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "schema_version",
        "connection_id",
        "scenario_scope",
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
        "fanout_index",
        "range_source_expr",
        "range_sink_expr",
        "bit_pair_order",
        "source_workbook",
        "source_sheet",
        "source_row",
        "validation_status",
        "owner_hint",
        "note",
    ]
    rows = [
        {
            "connection_id": "CONN_TOP_REF__PLL_REF",
            "connection_type": "clock_connection",
            "src_instance": "top",
            "src_direction": "input",
            "src_port": "clk_ref_pad",
            "src_endpoint_key": "top:input:clk_ref_pad",
            "dst_instance": "u_harden_a",
            "dst_direction": "input",
            "dst_port": "clk_ref",
            "dst_endpoint_key": "u_harden_a:input:clk_ref",
            "validation_status": "matched",
        },
        {
            "connection_id": "CONN_PLL_OUT__B_CLK",
            "connection_type": "clock_connection",
            "src_instance": "u_harden_a",
            "src_direction": "output",
            "src_port": "clk_pll_o",
            "src_endpoint_key": "u_harden_a:output:clk_pll_o",
            "dst_instance": "u_harden_b",
            "dst_direction": "input",
            "dst_port": "clk_i",
            "dst_endpoint_key": "u_harden_b:input:clk_i",
            "validation_status": "matched",
        },
        {
            "connection_id": "CONN_UART_RX",
            "connection_type": "top_pad_to_harden",
            "src_instance": "top",
            "src_direction": "input",
            "src_port": "uart_rx_pad",
            "src_endpoint_key": "top:input:uart_rx_pad",
            "dst_instance": "u_harden_b",
            "dst_direction": "input",
            "dst_port": "uart_rx_i",
            "dst_endpoint_key": "u_harden_b:input:uart_rx_i",
            "validation_status": "matched",
        },
        {
            "connection_id": "CONN_UART_TX",
            "connection_type": "harden_to_top_pad",
            "src_instance": "u_harden_b",
            "src_direction": "output",
            "src_port": "uart_tx_o",
            "src_endpoint_key": "u_harden_b:output:uart_tx_o",
            "dst_instance": "top",
            "dst_direction": "output",
            "dst_port": "uart_tx_pad",
            "dst_endpoint_key": "top:output:uart_tx_pad",
            "validation_status": "matched",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fields)
        writer.writeheader()
        for row_idx, row in enumerate(rows, start=2):
            item = dict(row)
            item["schema_version"] = "1"
            item["scenario_scope"] = "common"
            item.setdefault("src_soc_object", soc_object(item["src_instance"], item["src_port"]))
            item.setdefault("dst_soc_object", soc_object(item["dst_instance"], item["dst_port"]))
            item.setdefault("fanout_index", "0")
            item.setdefault("range_source_expr", item["src_port"])
            item.setdefault("range_sink_expr", item["dst_port"])
            item.setdefault("bit_pair_order", "explicit_map")
            item.setdefault("source_workbook", "demo")
            item.setdefault("source_sheet", "connections")
            item.setdefault("source_row", str(row_idx))
            item.setdefault("owner_hint", "")
            item.setdefault("note", "")
            writer.writerow(item)


def write_manifest():
    path = RUN_ROOT / "00_middle/scenario/common/harden_sdc_manifest.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["scenario", "inst_name", "module_name", "sdc_path", "availability_status", "note"]
    rows = [
        {
            "scenario": "common",
            "inst_name": "u_harden_a",
            "module_name": "harden_a",
            "sdc_path": "inputs/harden_a.sdc",
            "availability_status": "available",
            "note": "PLL harden SDC delivered",
        },
        {
            "scenario": "common",
            "inst_name": "u_harden_b",
            "module_name": "harden_b",
            "sdc_path": "inputs/harden_b.sdc",
            "availability_status": "available",
            "note": "clock and UART IO SDC delivered",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_pending():
    pending = RUN_ROOT / "00_middle/scenario/common/pending"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "u_harden_a.ports").write_text(
        "input clk_ref\noutput clk_pll_o\n", encoding="utf-8"
    )
    (pending / "u_harden_b.ports").write_text(
        "input clk_i\ninput uart_rx_i\noutput clk_o\noutput uart_tx_o\n", encoding="utf-8"
    )


def build_case():
    if RUN_ROOT.exists():
        shutil.rmtree(str(RUN_ROOT))
    INPUTS.mkdir(parents=True)

    pd.DataFrame(
        [
            {"module_name": "harden_a", "inst_name": "u_harden_a", "owner": "clock_owner"},
            {"module_name": "harden_b", "inst_name": "u_harden_b", "owner": "io_owner"},
        ]
    ).to_excel(INPUTS / "info_all.xlsx", index=False)

    with pd.ExcelWriter(str(INPUTS / "port_demo.xlsx"), engine="xlsxwriter") as writer:
        port_sheet(
            [
                {"Input": "clk_ref", "Input Width": 1, "From Whom": "top.clk_ref_pad"},
                {"Output": "clk_pll_o", "Output Width": 1},
            ]
        ).to_excel(writer, sheet_name="u_harden_a", index=False)
        port_sheet(
            [
                {"Input": "clk_i", "Input Width": 1, "From Whom": "u_harden_a.clk_pll_o"},
                {"Input": "uart_rx_i", "Input Width": 1, "From Whom": "top.uart_rx_pad"},
                {"Output": "clk_o", "Output Width": 1},
                {"Output": "uart_tx_o", "Output Width": 1, "To Top": "top.uart_tx_pad"},
            ]
        ).to_excel(writer, sheet_name="u_harden_b", index=False)

    (INPUTS / "harden_a.sdc").write_text(
        "create_clock -name ref_clk -period 10.000 [get_ports clk_ref]\n"
        "create_generated_clock -name pll_clk -source [get_ports clk_ref] "
        "-multiply_by 8 [get_ports clk_pll_o]\n",
        encoding="utf-8",
    )
    (INPUTS / "harden_b.sdc").write_text(
        "create_clock -name b_clk_in -period 1.250 [get_ports clk_i]\n"
        "create_generated_clock -name b_clk_o -source [get_ports clk_i] "
        "-combinational [get_ports clk_o]\n"
        "set_input_delay -clock [get_clocks v_gpio_ref_clk] -min 0.20 [get_ports uart_rx_i]\n"
        "set_input_delay -clock [get_clocks v_gpio_ref_clk] -max 2.50 [get_ports uart_rx_i]\n"
        "set_input_transition 0.18 [get_ports uart_rx_i]\n"
        "set_output_delay -clock [get_clocks v_gpio_ref_clk] -min -0.10 [get_ports uart_tx_o]\n"
        "set_output_delay -clock [get_clocks v_gpio_ref_clk] -max 2.00 [get_ports uart_tx_o]\n"
        "set_load 0.06 [get_ports uart_tx_o]\n",
        encoding="utf-8",
    )
    (INPUTS / "virtual_clocks.csv").write_text(
        "clock_name,period,waveform,note\n"
        "v_pcie_ref_clk,10.000,{0 5},PCIe external reference\n"
        "v_gpio_ref_clk,20.000,,UART board timing reference\n",
        encoding="utf-8",
    )

    write_connection_inventory()
    write_manifest()
    write_pending()
    print("Demo run root built: %s" % RUN_ROOT, flush=True)


if __name__ == "__main__":
    build_case()
