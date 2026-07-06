# Deep demo top integration delay segments.
#
# This case intentionally uses multi-object -from/-to lists to exercise
# Stage 2 v0.4 pair expansion and partial leftover rewriting.

# Case A:
# Two legal top startpoints drive three harden input boundary pins.
# cfg_i and mode_i have matching harden internal delay segments.
# unused_i does not, so those two top pairs must remain in final SDC.
set_max_delay 2.0 \
    -from [list [get_pins u_src0/Q] [get_pins u_src1/Q]] \
    -to [list [get_pins u_h0/cfg_i] [get_pins u_h0/mode_i] [get_pins u_h0/unused_i]]

# Case B:
# Top open_from to two boundary pins. Matching harden min delay should produce
# two conservative -through E2E constraints.
set_min_delay 0.3 \
    -to [list [get_pins u_h0/cfg_i] [get_pins u_h0/mode_i]]

# Case C:
# This top segment points to a harden input whose harden-side delay exits the
# harden through an output boundary. Stage 2 should review it, not merge it.
set_max_delay 1.0 \
    -from [get_pins u_src2/Q] \
    -to [get_pins u_h0/pass_i]
