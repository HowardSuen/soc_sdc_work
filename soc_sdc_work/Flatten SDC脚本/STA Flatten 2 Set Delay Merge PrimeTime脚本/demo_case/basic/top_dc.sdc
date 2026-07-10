# Demo top integration delay segments.

# Case 1: top complete + harden complete -> E2E -from/-to.
set_max_delay 2.0 -from [get_pins u_src_reg/Q] -to [get_pins u_h0/cfg_i]

# Case 2: top open_from + harden complete -> E2E -through/-to.
set_min_delay 0.2 -to [get_pins u_h0/cfg_i]

# Case 3: multi-hop unsupported.
# u_up is also listed as a harden instance, so this top -from is an upstream
# harden boundary output pin and must go to review.
set_max_delay 1.0 -from [get_pins u_up/data_o] -to [get_pins u_h0/async_i]
