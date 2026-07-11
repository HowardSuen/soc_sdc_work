################################################################################
# Auto-generated SoC clock group constraints for scenario: common
# Source: 03_soc_clock_groups.xlsx clock_group_rules sheet
# Policy: default synchronous + explicit async/exclusive groups
################################################################################

# row 5: CG_ASYNC_CORE_AUX_001 (asynchronous, normal)
# Basis: CDC spec: core domain async to aux always-on domain
set_clock_groups -asynchronous \
  -group [get_clocks {u_pll_core_clk_o u_fab0_fab_clk_o u_fab1_fab_clk_o u_periph_clk_o}] \
  -group [get_clocks {top_aux_clk_pad}] \
  -group [get_clocks {top_scan_clk_pad}]
