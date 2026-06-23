################################################################################
# Auto-generated SoC func clock constraints
# Source: local info_all.xlsx, port_*.xlsx and harden SoC integration SDC files
################################################################################

# virtual clock v_ddr_ref from virtual_clocks.csv
# Note: DDR external reference
create_clock -name v_ddr_ref -period 2.500

# virtual clock v_pcie_ref from virtual_clocks.csv
# Note: PCIe external reference
create_clock -name v_pcie_ref -period 10.000 -waveform {0 5}

# virtual clock v_uart_rx from virtual_clocks.csv
# Note: UART RX board reference
create_clock -name v_uart_rx -period 20.000

# virtual clock v_uart_tx from virtual_clocks.csv
# Note: UART TX board reference
create_clock -name v_uart_tx -period 20.000

# virtual clock dqs_clk from virtual_clocks.csv
# Note: DDR DQS source-sync reference
create_clock -name dqs_clk -period 2.500

# u_fab0/fab_clk_o from fab.sdc
create_generated_clock -name u_fab0_fab_clk_o -source [get_pins {u_fab0/fab_clk_i}] -combinational [get_pins {u_fab0/fab_clk_o}]

# u_fab1/fab_clk_o from fab.sdc
create_generated_clock -name u_fab1_fab_clk_o -source [get_pins {u_fab1/fab_clk_i}] -combinational [get_pins {u_fab1/fab_clk_o}]

# u_periph/ref2_i from periph.sdc
# From Whom: top.aux_clk_pad
create_clock -name top_aux_clk_pad -period 40.000 [get_ports {aux_clk_pad}]

# u_periph/scan_mode_clk from periph.sdc
# From Whom: top.scan_clk_pad
create_clock -name top_scan_clk_pad -period 50.000 [get_ports {scan_clk_pad}]

# u_periph/clk_o from periph.sdc
create_generated_clock -name u_periph_clk_o -source [get_pins {u_periph/clk_i}] -combinational [get_pins {u_periph/clk_o}]

# u_pll/ref_clk_in from pll_top.sdc
# From Whom: top.sys_clk_pad
create_clock -name top_sys_clk_pad -period 20.000 [get_ports {sys_clk_pad}]

# u_pll/core_clk_o from pll_top.sdc
create_generated_clock -name u_pll_core_clk_o -source [get_pins {u_pll/ref_clk_in}] -multiply_by 4 [get_pins {u_pll/core_clk_o}]

# u_pll/bus_clk_o from pll_top.sdc
create_generated_clock -name u_pll_bus_clk_o -source [get_pins {u_pll/ref_clk_in}] -multiply_by 2 [get_pins {u_pll/bus_clk_o}]
