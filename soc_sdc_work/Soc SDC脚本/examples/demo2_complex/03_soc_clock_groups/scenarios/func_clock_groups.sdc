################################################################################
# Auto-generated SoC clock group constraints for scenario: func
# Source: 03_soc_clock_groups.xlsx clock_group_rules sheet
# Policy: default synchronous + explicit async/exclusive groups
################################################################################

# row 6: CG_EXCL_PLL_CORE_BUS_FUNC_001 (logically_exclusive, merged_exclusive)
# Basis: all-mode merged view, mux select not case-fixed; demo logically exclusive PLL outputs
set_clock_groups -logically_exclusive \
  -group [get_clocks {u_pll_core_clk_o u_fab0_fab_clk_o u_fab1_fab_clk_o u_periph_clk_o}] \
  -group [get_clocks {u_pll_bus_clk_o}]
