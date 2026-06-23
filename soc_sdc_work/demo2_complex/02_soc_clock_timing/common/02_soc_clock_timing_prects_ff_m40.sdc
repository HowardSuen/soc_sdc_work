################################################################################
# Auto-generated SoC clock timing constraints for scenario: common, stage: prects, corner: ff_m40
# Source: 02_soc_clock_timing_budget_<stage>.xlsx clock_budget sheet
# Rows are resolved by scenario priority: selected scenario > common.
################################################################################

# row 15: common / ff_m40 / top_sys_clk_pad
set_clock_uncertainty -setup 0.06 [get_clocks {top_sys_clk_pad}]
set_clock_uncertainty -hold 0.018 [get_clocks {top_sys_clk_pad}]
set_clock_latency -source -early 0.06 [get_clocks {top_sys_clk_pad}]
set_clock_latency -source -late 0.144 [get_clocks {top_sys_clk_pad}]
set_clock_latency -early 0.168 [get_clocks {top_sys_clk_pad}]
set_clock_latency -late 0.39 [get_clocks {top_sys_clk_pad}]
set_clock_transition -min 0.03 [get_clocks {top_sys_clk_pad}]
set_clock_transition -max 0.066 [get_clocks {top_sys_clk_pad}]

# row 16: common / ff_m40 / top_aux_clk_pad
set_clock_uncertainty -setup 0.06 [get_clocks {top_aux_clk_pad}]
set_clock_uncertainty -hold 0.018 [get_clocks {top_aux_clk_pad}]
set_clock_latency -source -early 0.06 [get_clocks {top_aux_clk_pad}]
set_clock_latency -source -late 0.144 [get_clocks {top_aux_clk_pad}]
set_clock_latency -early 0.168 [get_clocks {top_aux_clk_pad}]
set_clock_latency -late 0.39 [get_clocks {top_aux_clk_pad}]
set_clock_transition -min 0.03 [get_clocks {top_aux_clk_pad}]
set_clock_transition -max 0.066 [get_clocks {top_aux_clk_pad}]

# row 17: common / ff_m40 / top_scan_clk_pad
set_clock_uncertainty -setup 0.06 [get_clocks {top_scan_clk_pad}]
set_clock_uncertainty -hold 0.018 [get_clocks {top_scan_clk_pad}]
set_clock_latency -source -early 0.06 [get_clocks {top_scan_clk_pad}]
set_clock_latency -source -late 0.144 [get_clocks {top_scan_clk_pad}]
set_clock_latency -early 0.168 [get_clocks {top_scan_clk_pad}]
set_clock_latency -late 0.39 [get_clocks {top_scan_clk_pad}]
set_clock_transition -min 0.03 [get_clocks {top_scan_clk_pad}]
set_clock_transition -max 0.066 [get_clocks {top_scan_clk_pad}]

# row 18: common / ff_m40 / u_pll_core_clk_o
set_clock_uncertainty -setup 0.072 [get_clocks {u_pll_core_clk_o}]
set_clock_uncertainty -hold 0.024 [get_clocks {u_pll_core_clk_o}]
set_clock_latency -early 0.18 [get_clocks {u_pll_core_clk_o}]
set_clock_latency -late 0.42 [get_clocks {u_pll_core_clk_o}]
set_clock_transition -min 0.03 [get_clocks {u_pll_core_clk_o}]
set_clock_transition -max 0.072 [get_clocks {u_pll_core_clk_o}]

# row 19: common / ff_m40 / u_pll_bus_clk_o
set_clock_uncertainty -setup 0.072 [get_clocks {u_pll_bus_clk_o}]
set_clock_uncertainty -hold 0.024 [get_clocks {u_pll_bus_clk_o}]
set_clock_latency -early 0.18 [get_clocks {u_pll_bus_clk_o}]
set_clock_latency -late 0.42 [get_clocks {u_pll_bus_clk_o}]
set_clock_transition -min 0.03 [get_clocks {u_pll_bus_clk_o}]
set_clock_transition -max 0.072 [get_clocks {u_pll_bus_clk_o}]

# row 20: common / ff_m40 / u_fab0_fab_clk_o
set_clock_uncertainty -setup 0.066 [get_clocks {u_fab0_fab_clk_o}]
set_clock_uncertainty -hold 0.021 [get_clocks {u_fab0_fab_clk_o}]
set_clock_latency -early 0.15 [get_clocks {u_fab0_fab_clk_o}]
set_clock_latency -late 0.36 [get_clocks {u_fab0_fab_clk_o}]

# row 21: common / ff_m40 / u_fab1_fab_clk_o
set_clock_uncertainty -setup 0.066 [get_clocks {u_fab1_fab_clk_o}]
set_clock_uncertainty -hold 0.021 [get_clocks {u_fab1_fab_clk_o}]
set_clock_latency -early 0.15 [get_clocks {u_fab1_fab_clk_o}]
set_clock_latency -late 0.36 [get_clocks {u_fab1_fab_clk_o}]

# row 22: common / ff_m40 / u_periph_clk_o
set_clock_uncertainty -setup 0.066 [get_clocks {u_periph_clk_o}]
set_clock_uncertainty -hold 0.021 [get_clocks {u_periph_clk_o}]
set_clock_latency -early 0.15 [get_clocks {u_periph_clk_o}]
set_clock_latency -late 0.36 [get_clocks {u_periph_clk_o}]

# row 23: common / ff_m40 / v_ddr_ref
set_clock_uncertainty -setup 0.03 [get_clocks {v_ddr_ref}]
set_clock_uncertainty -hold 0.02 [get_clocks {v_ddr_ref}]
set_clock_latency -late 0.4 [get_clocks {v_ddr_ref}]

# row 24: common / ff_m40 / v_pcie_ref
set_clock_uncertainty -setup 0.03 [get_clocks {v_pcie_ref}]
set_clock_uncertainty -hold 0.02 [get_clocks {v_pcie_ref}]
