################################################################################
# Auto-generated SoC clock timing constraints for scenario: common, stage: postcts, corner: ss_125
# Source: 02_soc_clock_timing_budget_<stage>.xlsx clock_budget sheet
# Rows are resolved by scenario priority: selected scenario > common.
################################################################################

# row 5: common / ss_125 / dqs_clk
set_clock_uncertainty -setup 0.05 [get_clocks {dqs_clk}]
set_clock_uncertainty -hold 0.02 [get_clocks {dqs_clk}]
set_propagated_clock [get_clocks {dqs_clk}]

# row 6: common / ss_125 / top_aux_clk_pad
set_clock_uncertainty -setup 0.05 [get_clocks {top_aux_clk_pad}]
set_clock_uncertainty -hold 0.02 [get_clocks {top_aux_clk_pad}]
set_propagated_clock [get_clocks {top_aux_clk_pad}]

# row 7: common / ss_125 / top_scan_clk_pad
set_clock_uncertainty -setup 0.05 [get_clocks {top_scan_clk_pad}]
set_clock_uncertainty -hold 0.02 [get_clocks {top_scan_clk_pad}]
set_propagated_clock [get_clocks {top_scan_clk_pad}]

# row 8: common / ss_125 / top_sys_clk_pad
set_clock_uncertainty -setup 0.05 [get_clocks {top_sys_clk_pad}]
set_clock_uncertainty -hold 0.02 [get_clocks {top_sys_clk_pad}]
set_propagated_clock [get_clocks {top_sys_clk_pad}]

# row 9: common / ss_125 / u_fab0_fab_clk_o
set_clock_uncertainty -setup 0.05 [get_clocks {u_fab0_fab_clk_o}]
set_clock_uncertainty -hold 0.02 [get_clocks {u_fab0_fab_clk_o}]
set_propagated_clock [get_clocks {u_fab0_fab_clk_o}]

# row 10: common / ss_125 / u_fab1_fab_clk_o
set_clock_uncertainty -setup 0.05 [get_clocks {u_fab1_fab_clk_o}]
set_clock_uncertainty -hold 0.02 [get_clocks {u_fab1_fab_clk_o}]
set_propagated_clock [get_clocks {u_fab1_fab_clk_o}]

# row 11: common / ss_125 / u_periph_clk_o
set_clock_uncertainty -setup 0.05 [get_clocks {u_periph_clk_o}]
set_clock_uncertainty -hold 0.02 [get_clocks {u_periph_clk_o}]
set_propagated_clock [get_clocks {u_periph_clk_o}]

# row 12: common / ss_125 / u_pll_bus_clk_o
set_clock_uncertainty -setup 0.05 [get_clocks {u_pll_bus_clk_o}]
set_clock_uncertainty -hold 0.02 [get_clocks {u_pll_bus_clk_o}]
set_propagated_clock [get_clocks {u_pll_bus_clk_o}]

# row 13: common / ss_125 / u_pll_core_clk_o
set_clock_uncertainty -setup 0.05 [get_clocks {u_pll_core_clk_o}]
set_clock_uncertainty -hold 0.02 [get_clocks {u_pll_core_clk_o}]
set_propagated_clock [get_clocks {u_pll_core_clk_o}]

# row 14: common / ss_125 / v_ddr_ref
set_clock_uncertainty -setup 0.05 [get_clocks {v_ddr_ref}]
set_clock_uncertainty -hold 0.02 [get_clocks {v_ddr_ref}]
set_propagated_clock [get_clocks {v_ddr_ref}]

# row 15: common / ss_125 / v_pcie_ref
set_clock_uncertainty -setup 0.05 [get_clocks {v_pcie_ref}]
set_clock_uncertainty -hold 0.02 [get_clocks {v_pcie_ref}]
set_propagated_clock [get_clocks {v_pcie_ref}]

# row 16: common / ss_125 / v_uart_rx
set_clock_uncertainty -setup 0.05 [get_clocks {v_uart_rx}]
set_clock_uncertainty -hold 0.02 [get_clocks {v_uart_rx}]
set_propagated_clock [get_clocks {v_uart_rx}]

# row 17: common / ss_125 / v_uart_tx
set_clock_uncertainty -setup 0.05 [get_clocks {v_uart_tx}]
set_clock_uncertainty -hold 0.02 [get_clocks {v_uart_tx}]
set_propagated_clock [get_clocks {v_uart_tx}]
