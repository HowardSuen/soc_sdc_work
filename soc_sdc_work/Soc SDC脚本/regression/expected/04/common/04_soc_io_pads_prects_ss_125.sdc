################################################################################
# Auto-generated SoC IO/pad constraints for scenario: common, stage: prects, corner: ss_125, tool: sta
# Source: 04_soc_io_pads.xlsx io_constraints sheet
# Only apply=yes and review_status=approved rows are emitted.
################################################################################

# row 8: pad_ddr_dqs load
# Basis: pre-CTS board/package estimate
set_load 0.03 [get_ports {pad_ddr_dqs}]
