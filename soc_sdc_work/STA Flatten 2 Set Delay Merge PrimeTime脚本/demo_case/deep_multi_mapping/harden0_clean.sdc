# Deep demo Stage-1-cleaned harden delay segments for u_h0.

# Case A1 harden side:
# cfg_i matches a top boundary pin. no_top_i intentionally has no matching top
# segment, so only those pair leftovers should remain. cfg_i fans to two
# endpoints, so the same top boundary pair must be reused for multiple
# generated E2E constraints.
set_max_delay 5.0 \
    -from [list [get_pins u_h0/cfg_i] [get_pins u_h0/no_top_i]] \
    -to [list [get_pins u_h0/u_cfg_reg/D] [get_pins u_h0/u_cfg_shadow_reg/D]]

# Case A2 harden side:
# mode_i has a different delay and a different endpoint, so generated E2E
# commands stay visually distinct from cfg_i.
set_max_delay 6.0 \
    -from [get_pins u_h0/mode_i] \
    -to [get_pins u_h0/u_mode_reg/D]

# Case B harden side:
# Matches top open_from min delay on both cfg_i and mode_i.
set_min_delay 0.7 \
    -from [list [get_pins u_h0/cfg_i] [get_pins u_h0/mode_i]] \
    -to [get_pins u_h0/u_hold_reg/D]

# Case C harden side:
# Boundary input to boundary output is an output-direction / pass-through path.
# Current Stage 2 rules require review instead of automatic E2E merge.
set_max_delay 4.0 \
    -from [get_pins u_h0/pass_i] \
    -to [get_pins u_h0/pass_o]
