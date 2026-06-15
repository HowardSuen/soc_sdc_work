# harden_a SoC integration SDC
# clk_ref: primary input clock from top pad
create_clock -name ref_clk -period 10.000 [get_ports clk_ref]

# clk_pll_o: generated clock, TARGET written BEFORE -source (out-of-order target test)
create_generated_clock [get_ports clk_pll_o] -source [get_ports clk_ref] -multiply_by 8 -name pll_clk
