# harden_a SoC integration SDC
create_clock -name ref_clk -period 10.000 [get_ports clk_ref]
create_generated_clock [get_ports clk_pll_o] -source [get_ports clk_ref] -multiply_by 8 -name pll_clk
