# harden_b SoC integration SDC
create_clock -name b_clk_in -period 1.250 [get_ports clk_i]
create_generated_clock -name b_clk_o -source [get_ports clk_i] -combinational [get_ports clk_o]
