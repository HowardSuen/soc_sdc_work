# harden_c SoC integration SDC
# clk_in_c: shares the SAME top pad (top.clk_ref_pad) as harden_a/clk_ref,
# but with a DIFFERENT period -> dedupe + period-mismatch test
create_clock -name c_in -period 20.000 [get_ports clk_in_c]

# clk_gen_c: generated clock with NO -source -> CLOCK_GENERATED_MISSING_SOURCE error
create_generated_clock -name c_gen [get_ports clk_gen_c]
