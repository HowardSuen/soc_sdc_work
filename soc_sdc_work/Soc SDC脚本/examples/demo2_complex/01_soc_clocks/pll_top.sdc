# pll_top SoC integration SDC (inst u_pll)
create_clock -name pll_ref -period 20.000 [get_ports ref_clk_in]
create_generated_clock -name pll_core -source [get_ports ref_clk_in] -multiply_by 4 [get_ports core_clk_o]
create_generated_clock -name pll_bus  -source [get_ports ref_clk_in] -multiply_by 2 [get_ports bus_clk_o]
