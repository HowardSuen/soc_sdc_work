################################################################################
# Auto-generated SoC func clock constraints
# Source: local info_all.xlsx, port_*.xlsx and harden SoC integration SDC files
################################################################################

# virtual clock v_pcie_ref_clk from virtual_clocks.csv
# Note: PCIe external reference clock
create_clock -name v_pcie_ref_clk -period 10.000 -waveform {0 5}

# virtual clock v_gpio_ref_clk from virtual_clocks.csv
# Note: GPIO reference
create_clock -name v_gpio_ref_clk -period 20.000

# u_harden_a/clk_ref from harden_a.sdc
# From Whom: top.clk_ref_pad
create_clock -name top_clk_ref_pad -period 10.000 [get_ports {clk_ref_pad}]

# u_harden_a/clk_pll_o from harden_a.sdc
create_generated_clock [get_pins {u_harden_a/clk_pll_o}] -source [get_pins {u_harden_a/clk_ref}] -multiply_by 8 -name u_harden_a_clk_pll_o

# u_harden_b/clk_o from harden_b.sdc
create_generated_clock -name u_harden_b_clk_o -source [get_pins {u_harden_b/clk_i}] -combinational [get_pins {u_harden_b/clk_o}]
