################################################################################
# Auto-generated SoC IO/pad constraints for scenario: gpio_in, stage: all, corner: all, tool: sta
# Source: 04_soc_io_pads.xlsx io_constraints sheet
# Only apply=yes and review_status=approved rows are emitted.
################################################################################

# row 7: pad_gpio0 input_delay
# Basis: GPIO input direction budget
# Extracted from: u_io.sdc:7
set_input_delay -clock [get_clocks {v_uart_rx}] -max 3 [get_ports {pad_gpio0}]
