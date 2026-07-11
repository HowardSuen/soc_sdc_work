#!/usr/bin/env python3
"""Build minimal 04 IO/pad regression inputs in the current directory."""
import csv
from openpyxl import Workbook


def build_info_all(path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "info_all"
    ws.append(["inst_name", "module_name", "owner", "sdc_path"])
    ws.append(["u_io", "io_ring", "alice", "u_io.sdc"])
    wb.save(path)


def build_ports(path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "u_io"  # sheet name must equal inst_name
    ws.append([
        "Input", "Input Width", "Input Used Width", "From Whom",
        "Output", "Output Width", "Output Used Width", "To Top",
        "Inout", "Inout Width", "Inout Connectivity", "Inout Name",
    ])
    # one input, one output, one inout (single row is enough; columns are independent)
    ws.append([
        "uart0_sin", 1, 1, "top.pad_uart0_sin",
        "uart0_sout", 1, 1, "top.pad_uart0_sout",
        "gpio0", 1, "", "top.pad_gpio0",
    ])
    wb.save(path)


def build_sdc(path: str) -> None:
    lines = [
        "# lower-level io_ring SDC (block signoff env)",
        "set_input_delay  -clock [get_clocks v_uart_rx] -max 5.0 [get_ports uart0_sin]",
        "set_input_transition 0.2 [get_ports uart0_sin]",
        "set_driving_cell -lib_cell BUFX2 -pin Y [get_ports uart0_sin]",
        "set_output_delay -clock [get_clocks v_uart_tx] -max 4.0 [get_ports uart0_sout]",
        "set_load 0.05 [get_ports uart0_sout]",
        "set_input_delay  -clock [get_clocks v_uart_rx] -max 3.0 [get_ports gpio0]",
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def build_clock_inventory(path: str) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["clock_name", "direct_source", "producer_object", "final_action", "source_file"])
        w.writerow(["v_uart_rx", "", "", "emit_virtual_clock", "01"])
        w.writerow(["v_uart_tx", "", "", "emit_virtual_clock", "01"])


if __name__ == "__main__":
    build_info_all("info_all.xlsx")
    build_ports("ports_u_io.xlsx")
    build_sdc("u_io.sdc")
    build_clock_inventory("clock_inventory.csv")
    print("inputs built: info_all.xlsx, ports_u_io.xlsx, u_io.sdc, clock_inventory.csv")
