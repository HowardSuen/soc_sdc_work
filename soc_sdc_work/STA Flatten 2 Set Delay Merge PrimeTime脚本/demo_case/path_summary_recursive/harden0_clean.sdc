# Downstream harden clean SDC.
set_max_delay 5.0 \
    -from [get_pins u_h0/cfg_i] \
    -to [get_pins u_h0/u_reg/D]
