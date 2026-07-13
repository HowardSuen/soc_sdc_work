################################################################################
# Auto-generated SoC clock group constraints for scenario: common
# Author: Howard
# Stage: 03_soc_clock_groups
# Script: 03_extract_soc_clock_groups.py
# Run completeness: complete
# Harden SDC available: 0
# Harden SDC missing: 0
# Harden SDC not_required: 0
# Missing instances: <none>
# Clock universe digest: 53289f7b9c8dc2b88550014c04917baad0cd6aa0b2f1d5edee32f5f672c2071f
# Form digest: ef14f6b2862bcef92174802d75deb08076359afcd95851aa0a9836e91ff0be4c
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
