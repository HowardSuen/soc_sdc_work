#!/usr/bin/env python3
"""Demo: build 01 inputs (clean run, exit 0)."""
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

pd.DataFrame([
    {"module_name":"harden_a","inst_name":"u_harden_a","owner":"alice","file_path":""},
    {"module_name":"harden_b","inst_name":"u_harden_b","owner":"alice","file_path":""},
]).to_excel("info_all.xlsx", index=False)

a = sheet([
    {"Input":"clk_ref","Input Width":1,"From Whom":"top.clk_ref_pad"},
    {"Output":"clk_pll_o","Output Width":1},
])
b = sheet([
    {"Input":"clk_i","Input Width":1,"From Whom":"u_harden_a.clk_pll_o"},
    {"Output":"clk_o","Output Width":1},
])
with pd.ExcelWriter("port_alice.xlsx", engine="xlsxwriter") as w:
    a.to_excel(w, sheet_name="u_harden_a", index=False)
    b.to_excel(w, sheet_name="u_harden_b", index=False)

print("01 inputs written")
