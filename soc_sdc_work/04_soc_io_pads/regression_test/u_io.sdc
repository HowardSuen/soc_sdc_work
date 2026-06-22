# lower-level io_ring SDC (block signoff env)
set_input_delay  -clock [get_clocks v_uart_rx] -max 5.0 [get_ports uart0_sin]
set_input_transition 0.2 [get_ports uart0_sin]
set_driving_cell -lib_cell BUFX2 -pin Y [get_ports uart0_sin]
set_output_delay -clock [get_clocks v_uart_tx] -max 4.0 [get_ports uart0_sout]
set_load 0.05 [get_ports uart0_sout]
set_input_delay  -clock [get_clocks v_uart_rx] -max 3.0 [get_ports gpio0]
