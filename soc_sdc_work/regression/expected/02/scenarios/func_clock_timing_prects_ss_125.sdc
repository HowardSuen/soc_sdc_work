################################################################################
# Auto-generated SoC clock timing constraints for scenario: func, stage: prects, corner: ss_125
# Source: 02_soc_clock_timing_budget_<stage>.xlsx clock_budget sheet
# Rows are resolved by scenario priority: selected scenario > common.
################################################################################

# row 5: common / ss_125 / top_aux_clk_pad
set_clock_uncertainty -setup 0.1 [get_clocks {top_aux_clk_pad}]
set_clock_uncertainty -hold 0.03 [get_clocks {top_aux_clk_pad}]
set_clock_latency -source -early 0.1 [get_clocks {top_aux_clk_pad}]
set_clock_latency -source -late 0.24 [get_clocks {top_aux_clk_pad}]
set_clock_latency -early 0.28 [get_clocks {top_aux_clk_pad}]
set_clock_latency -late 0.65 [get_clocks {top_aux_clk_pad}]
set_clock_transition -min 0.03 [get_clocks {top_aux_clk_pad}]
set_clock_transition -max 0.11 [get_clocks {top_aux_clk_pad}]

# row 6: common / ss_125 / top_scan_clk_pad
set_clock_uncertainty -setup 0.1 [get_clocks {top_scan_clk_pad}]
set_clock_uncertainty -hold 0.03 [get_clocks {top_scan_clk_pad}]
set_clock_latency -source -early 0.1 [get_clocks {top_scan_clk_pad}]
set_clock_latency -source -late 0.24 [get_clocks {top_scan_clk_pad}]
set_clock_latency -early 0.28 [get_clocks {top_scan_clk_pad}]
set_clock_latency -late 0.65 [get_clocks {top_scan_clk_pad}]
set_clock_transition -min 0.03 [get_clocks {top_scan_clk_pad}]
set_clock_transition -max 0.11 [get_clocks {top_scan_clk_pad}]

# row 7: common / ss_125 / top_sys_clk_pad
set_clock_uncertainty -setup 0.1 [get_clocks {top_sys_clk_pad}]
set_clock_uncertainty -hold 0.03 [get_clocks {top_sys_clk_pad}]
set_clock_latency -source -early 0.1 [get_clocks {top_sys_clk_pad}]
set_clock_latency -source -late 0.24 [get_clocks {top_sys_clk_pad}]
set_clock_latency -early 0.28 [get_clocks {top_sys_clk_pad}]
set_clock_latency -late 0.65 [get_clocks {top_sys_clk_pad}]
set_clock_transition -min 0.03 [get_clocks {top_sys_clk_pad}]
set_clock_transition -max 0.11 [get_clocks {top_sys_clk_pad}]

# row 8: common / ss_125 / u_fab0_fab_clk_o
set_clock_uncertainty -setup 0.11 [get_clocks {u_fab0_fab_clk_o}]
set_clock_uncertainty -hold 0.035 [get_clocks {u_fab0_fab_clk_o}]
set_clock_latency -early 0.25 [get_clocks {u_fab0_fab_clk_o}]
set_clock_latency -late 0.6 [get_clocks {u_fab0_fab_clk_o}]

# row 9: common / ss_125 / u_fab1_fab_clk_o
set_clock_uncertainty -setup 0.11 [get_clocks {u_fab1_fab_clk_o}]
set_clock_uncertainty -hold 0.035 [get_clocks {u_fab1_fab_clk_o}]
set_clock_latency -early 0.25 [get_clocks {u_fab1_fab_clk_o}]
set_clock_latency -late 0.6 [get_clocks {u_fab1_fab_clk_o}]

# row 10: common / ss_125 / u_periph_clk_o
set_clock_uncertainty -setup 0.11 [get_clocks {u_periph_clk_o}]
set_clock_uncertainty -hold 0.035 [get_clocks {u_periph_clk_o}]
set_clock_latency -early 0.25 [get_clocks {u_periph_clk_o}]
set_clock_latency -late 0.6 [get_clocks {u_periph_clk_o}]

# row 11: common / ss_125 / u_pll_bus_clk_o
set_clock_uncertainty -setup 0.12 [get_clocks {u_pll_bus_clk_o}]
set_clock_uncertainty -hold 0.04 [get_clocks {u_pll_bus_clk_o}]
set_clock_latency -early 0.3 [get_clocks {u_pll_bus_clk_o}]
set_clock_latency -late 0.7 [get_clocks {u_pll_bus_clk_o}]
set_clock_transition -min 0.03 [get_clocks {u_pll_bus_clk_o}]
set_clock_transition -max 0.12 [get_clocks {u_pll_bus_clk_o}]

# row 13: common / ss_125 / v_ddr_ref
set_clock_uncertainty -setup 0.05 [get_clocks {v_ddr_ref}]
set_clock_uncertainty -hold 0.02 [get_clocks {v_ddr_ref}]

# row 14: common / ss_125 / v_pcie_ref
set_clock_uncertainty -setup 0.05 [get_clocks {v_pcie_ref}]
set_clock_uncertainty -hold 0.02 [get_clocks {v_pcie_ref}]

# row 15: func / ss_125 / u_pll_core_clk_o
set_clock_uncertainty -setup 0.15 [get_clocks {u_pll_core_clk_o}]
set_clock_uncertainty -hold 0.05 [get_clocks {u_pll_core_clk_o}]
set_clock_latency -early 0.3 [get_clocks {u_pll_core_clk_o}]
set_clock_latency -late 0.7 [get_clocks {u_pll_core_clk_o}]
set_clock_transition -min 0.03 [get_clocks {u_pll_core_clk_o}]
set_clock_transition -max 0.12 [get_clocks {u_pll_core_clk_o}]
