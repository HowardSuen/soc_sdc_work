#!/usr/bin/env python3
"""Build minimal regression inputs for extract_soc_01_clocks.py."""
import pandas as pd

REQ_COLS = [
    "Parameter", "Inout", "Inout Width", "Inout Connectivity", "Inout Name",
    "Input", "Input Width", "Input Used Width", "From Whom",
    "Output", "Output Width", "Output Used Width", "To Top",
]


def sheet(rows):
    df = pd.DataFrame(rows)
    for c in REQ_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[REQ_COLS].fillna("")


# ---- info_all.xlsx ----
info = pd.DataFrame([
    {"module_name": "harden_a", "inst_name": "u_harden_a", "owner": "alice", "file_path": ""},
    {"module_name": "harden_b", "inst_name": "u_harden_b", "owner": "alice", "file_path": ""},
    {"module_name": "harden_c", "inst_name": "u_harden_c", "owner": "bob",   "file_path": ""},
])
info.to_excel("info_all.xlsx", index=False)

# ---- port_alice.xlsx : u_harden_a, u_harden_b ----
a = sheet([
    {"Input": "clk_ref", "Input Width": 1, "From Whom": "top.clk_ref_pad"},
    {"Output": "clk_pll_o", "Output Width": 1},
])
b = sheet([
    {"Input": "clk_i", "Input Width": 1, "From Whom": "u_harden_a.clk_pll_o"},
    {"Output": "clk_o", "Output Width": 1},
])
with pd.ExcelWriter("port_alice.xlsx", engine="xlsxwriter") as w:
    a.to_excel(w, sheet_name="u_harden_a", index=False)
    b.to_excel(w, sheet_name="u_harden_b", index=False)

# ---- port_bob.xlsx : u_harden_c ----
# clk_in_c shares the SAME top pad as A's clk_ref -> dedupe + period-mismatch test
c = sheet([
    {"Input": "clk_in_c", "Input Width": 1, "From Whom": "top.clk_ref_pad"},
    {"Output": "clk_gen_c", "Output Width": 1},  # generated clock w/o -source -> error
])
with pd.ExcelWriter("port_bob.xlsx", engine="xlsxwriter") as w:
    c.to_excel(w, sheet_name="u_harden_c", index=False)

print("inputs written")
