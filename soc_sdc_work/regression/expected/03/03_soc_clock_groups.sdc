################################################################################
# Auto-generated SoC clock group constraints for scenario: common
# Source: 03_soc_clock_groups.xlsx clock_group_rules sheet
# Policy: default synchronous + explicit async/exclusive groups
################################################################################

# row 5: CG_ASYNC_CORE_AUX (asynchronous, normal)
# Basis: CDC: core domain async to aux
set_clock_groups -asynchronous \
  -group [get_clocks {u_pll_core_clk_o u_fab0_fab_clk_o u_fab1_fab_clk_o u_periph_clk_o}] \
  -group [get_clocks {top_aux_clk_pad}]

# row 6: CG_ASYNC_BUS_AUX (asynchronous, normal)
# Basis: CDC: bus async to aux
set_clock_groups -asynchronous \
  -group [get_clocks {u_pll_bus_clk_o}] \
  -group [get_clocks {top_aux_clk_pad}]
