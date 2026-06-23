################################################################################
# Auto-generated SoC harden/subsys interface budget constraints for scenario: common, stage: all, corner: all
# Source: 10_harden_x_if.xlsx interface_budget sheet
# Only apply=yes and review_status=approved rows are emitted.
################################################################################

# row 3: CH_u_a_data_o__u_b_data_i
# Budget basis: interconnect budget from block owners
# Derivation: min(src_output_delay_max,dst_input_delay_max)
# Source SDC: u_a.sdc:1; u_b.sdc:1
set_max_delay 1.2 -datapath_only -from [get_pins {u_a/data_o}] -to [get_pins {u_b/data_i}]
