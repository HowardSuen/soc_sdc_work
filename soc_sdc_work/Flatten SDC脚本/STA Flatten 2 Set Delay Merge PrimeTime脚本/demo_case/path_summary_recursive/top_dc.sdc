# Recursive path-summary demo top delay.
#
# This top segment connects upstream harden output to downstream harden input.
set_max_delay 2.0 \
    -from [get_pins u_up/data_o] \
    -to [get_pins u_h0/cfg_i]
