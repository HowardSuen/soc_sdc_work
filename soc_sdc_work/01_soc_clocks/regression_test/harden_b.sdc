# harden_b SoC integration SDC
# clk_i: input clock fed from u_harden_a.clk_pll_o (upstream harden) -> check_only, no create_clock
create_clock -name b_clk_in -period 1.250 [get_ports clk_i]

# clk_o: forwarded/combinational clock out of clk_i (A->B forwarding test)
create_generated_clock -name b_clk_o -source [get_ports clk_i] -combinational [get_ports clk_o]
