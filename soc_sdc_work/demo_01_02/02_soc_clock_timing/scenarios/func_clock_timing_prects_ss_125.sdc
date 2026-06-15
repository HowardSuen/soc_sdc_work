################################################################################
# Auto-generated SoC clock timing constraints for scenario: func, stage: prects, corner: ss_125
# Source: 02_soc_clock_timing_budget_<stage>.xlsx clock_budget sheet
# Rows are resolved by scenario priority: selected scenario > common.
################################################################################

# row 5: common / ss_125 / top_clk_ref_pad
set_clock_uncertainty -setup 0.1 [get_clocks {top_clk_ref_pad}]
set_clock_uncertainty -hold 0.03 [get_clocks {top_clk_ref_pad}]
set_clock_latency -source -early 0.1 [get_clocks {top_clk_ref_pad}]
set_clock_latency -source -late 0.24 [get_clocks {top_clk_ref_pad}]
set_clock_latency -early 0.28 [get_clocks {top_clk_ref_pad}]
set_clock_latency -late 0.65 [get_clocks {top_clk_ref_pad}]
set_clock_transition -min 0.03 [get_clocks {top_clk_ref_pad}]
set_clock_transition -max 0.11 [get_clocks {top_clk_ref_pad}]

# row 7: common / ss_125 / u_harden_b_clk_o
set_clock_uncertainty -setup 0.11 [get_clocks {u_harden_b_clk_o}]
set_clock_uncertainty -hold 0.035 [get_clocks {u_harden_b_clk_o}]
set_clock_latency -early 0.25 [get_clocks {u_harden_b_clk_o}]
set_clock_latency -late 0.6 [get_clocks {u_harden_b_clk_o}]

# row 8: common / ss_125 / v_gpio_ref_clk
set_clock_uncertainty -setup 0.06 [get_clocks {v_gpio_ref_clk}]
set_clock_uncertainty -hold 0.02 [get_clocks {v_gpio_ref_clk}]

# row 9: common / ss_125 / v_pcie_ref_clk
set_clock_uncertainty -setup 0.05 [get_clocks {v_pcie_ref_clk}]
set_clock_uncertainty -hold 0.02 [get_clocks {v_pcie_ref_clk}]

# row 10: func / ss_125 / u_harden_a_clk_pll_o
set_clock_uncertainty -setup 0.15 [get_clocks {u_harden_a_clk_pll_o}]
set_clock_uncertainty -hold 0.05 [get_clocks {u_harden_a_clk_pll_o}]
set_clock_latency -source -early 0.1 [get_clocks {u_harden_a_clk_pll_o}]
set_clock_latency -early 0.3 [get_clocks {u_harden_a_clk_pll_o}]
set_clock_latency -late 0.7 [get_clocks {u_harden_a_clk_pll_o}]
set_clock_transition -min 0.03 [get_clocks {u_harden_a_clk_pll_o}]
set_clock_transition -max 0.12 [get_clocks {u_harden_a_clk_pll_o}]
