#!/usr/bin/env python3
"""Demo2: complex 01 topology.

Topology:
  top.sys_clk_pad -> u_pll/ref_clk_in
    u_pll/core_clk_o  (generated x4)
    u_pll/bus_clk_o   (generated x2)
  u_pll.core_clk_o -> u_fab0/fab_clk_i -> u_fab0/fab_clk_o (forwarded)   # fab instanced twice
  u_pll.core_clk_o -> u_fab1/fab_clk_i -> u_fab1/fab_clk_o (forwarded)
  u_fab0.fab_clk_o -> u_periph/clk_i   -> u_periph/clk_o   (forwarded, multi-hop root)
  top.aux_clk_pad  -> u_periph/ref2_i                       (2nd top clock)
  top.scan_clk_pad -> u_periph/scan_mode_clk                (test-like advisory)
  virtual: v_ddr_ref, v_pcie_ref
"""
import pandas as pd

REQ = ["Parameter","Inout","Inout Width","Inout Connectivity","Inout Name",
       "Input","Input Width","Input Used Width","From Whom",
       "Output","Output Width","Output Used Width","To Top"]

def sheet(rows):
    df = pd.DataFrame(rows)
    for c in REQ:
        if c not in df.columns:
            df[c] = ""
    return df[REQ].fillna("")

# module pll_top -> u_pll ; module fab -> u_fab0,u_fab1 ; module periph -> u_periph
pd.DataFrame([
    {"module_name":"pll_top","inst_name":"u_pll",   "owner":"alice","file_path":""},
    {"module_name":"fab",    "inst_name":"u_fab0",  "owner":"alice","file_path":""},
    {"module_name":"fab",    "inst_name":"u_fab1",  "owner":"alice","file_path":""},
    {"module_name":"periph", "inst_name":"u_periph","owner":"bob",  "file_path":""},
]).to_excel("info_all.xlsx", index=False)

u_pll = sheet([
    {"Input":"ref_clk_in","Input Width":1,"From Whom":"top.sys_clk_pad"},
    {"Output":"core_clk_o","Output Width":1},
    {"Output":"bus_clk_o", "Output Width":1},
])
u_fab0 = sheet([
    {"Input":"fab_clk_i","Input Width":1,"From Whom":"u_pll.core_clk_o"},
    {"Output":"fab_clk_o","Output Width":1},
])
u_fab1 = sheet([
    {"Input":"fab_clk_i","Input Width":1,"From Whom":"u_pll.core_clk_o"},
    {"Output":"fab_clk_o","Output Width":1},
])
with pd.ExcelWriter("port_alice.xlsx", engine="xlsxwriter") as w:
    u_pll.to_excel(w, sheet_name="u_pll", index=False)
    u_fab0.to_excel(w, sheet_name="u_fab0", index=False)
    u_fab1.to_excel(w, sheet_name="u_fab1", index=False)

u_periph = sheet([
    {"Input":"clk_i","Input Width":1,"From Whom":"u_fab0.fab_clk_o"},
    {"Input":"ref2_i","Input Width":1,"From Whom":"top.aux_clk_pad"},
    {"Input":"scan_mode_clk","Input Width":1,"From Whom":"top.scan_clk_pad"},
    {"Output":"clk_o","Output Width":1},
])
with pd.ExcelWriter("port_bob.xlsx", engine="xlsxwriter") as w:
    u_periph.to_excel(w, sheet_name="u_periph", index=False)

print("complex 01 inputs written")
