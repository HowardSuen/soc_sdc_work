# fab SoC integration SDC (shared by u_fab0 and u_fab1)
create_clock -name fab_in -period 5.000 [get_ports fab_clk_i]
create_generated_clock -name fab_out -source [get_ports fab_clk_i] -combinational [get_ports fab_clk_o]
