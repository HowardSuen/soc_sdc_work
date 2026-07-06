# Demo Stage-1-cleaned harden delay segments for u_h0.

# Matches top max segment on u_h0/cfg_i.
set_max_delay 5.0 -from [get_pins u_h0/cfg_i] -to [get_pins u_h0/u_cfg_reg/D]

# Matches top open_from min segment on u_h0/cfg_i.
set_min_delay 0.8 -from [get_pins u_h0/cfg_i] -to [get_pins u_h0/u_hold_reg/D]

# Would match the multi-hop top segment, but v0.3 intentionally reviews it.
set_max_delay 3.0 -from [get_pins u_h0/async_i] -to [get_pins u_h0/u_async_reg/D]
