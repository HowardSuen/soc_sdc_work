# periph SoC integration SDC (inst u_periph)
create_clock -name periph_in   -period 5.000  [get_ports clk_i]
create_clock -name periph_ref2 -period 40.000 [get_ports ref2_i]
create_clock -name scan_clk    -period 50.000 [get_ports scan_mode_clk]
create_generated_clock -name periph_out -source [get_ports clk_i] -combinational [get_ports clk_o]
