# Upstream harden clean SDC.
set_max_delay 1.0 \
    -from [get_pins u_up/u_reg/Q] \
    -to [get_pins u_up/data_o]
