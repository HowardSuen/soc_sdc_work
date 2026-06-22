################################################################################
# Auto-generated SoC IO/pad constraints for scenario: common, stage: all, corner: all, tool: sta
# Source: 04_soc_io_pads.xlsx io_constraints sheet
# Only apply=yes and review_status=approved rows are emitted.
################################################################################

# row 2: pad_uart0_sin input_delay
# Basis: UART RX board budget
# Extracted from: u_io.sdc:2
set_input_delay -clock [get_clocks {v_uart_rx}] -max 5 [get_ports {pad_uart0_sin}]

# row 3: pad_uart0_sin input_transition
# Basis: IO spec input slew
# Extracted from: u_io.sdc:3
set_input_transition 0.2 [get_ports {pad_uart0_sin}]

# row 5: pad_uart0_sout output_delay
# Basis: UART TX board budget
# Extracted from: u_io.sdc:5
set_output_delay -clock [get_clocks {v_uart_tx}] -max 4 [get_ports {pad_uart0_sout}]

# row 6: pad_uart0_sout load
# Basis: package + PCB load
# Extracted from: u_io.sdc:6
set_load 0.05 [get_ports {pad_uart0_sout}]

# row 8: pad_dq0 input_delay
# Basis: DDR read min/max (single row)
set_input_delay -clock [get_clocks {dqs_clk}] -min 0.1 [get_ports {pad_dq0}]
set_input_delay -clock [get_clocks {dqs_clk}] -max -add_delay 0.8 [get_ports {pad_dq0}]

# row 9: pad_dq0 input_delay
# Basis: DDR read rise/fall (second row)
set_input_delay -clock [get_clocks {dqs_clk}] -rise -add_delay 0.05 [get_ports {pad_dq0}]
set_input_delay -clock [get_clocks {dqs_clk}] -fall -add_delay 0.06 [get_ports {pad_dq0}]

# row 11: pad_ddr_dqs load
# Basis: view-independent load conflicting with prects/ss_125
set_load 0.05 [get_ports {pad_ddr_dqs}]
