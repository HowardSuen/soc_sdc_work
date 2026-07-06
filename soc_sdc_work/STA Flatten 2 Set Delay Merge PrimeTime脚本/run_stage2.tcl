# run_stage2.tcl
#
# PrimeTime run wrapper for Flatten 2 Integration E2E Delay Merge.
#
# Usage inside pt_shell after read/link current integration design:
#
#   source /path/to/run_stage2.tcl
#
# Edit only the "User settings" section for a normal run.

###############################################################################
# User settings
###############################################################################

# Current integration run directory.
# This directory should contain top_dc.sdc and harden_list.csv unless you
# override TOP_SDC / HARDEN_LIST below.
set RUN_DIR [pwd]

# Top integration SDC. This is the top-side SDC containing delay segments such as:
#   set_max_delay <D_ext> -from <S> -to [get_pins <harden_inst>/<input_pin>]
# or:
#   set_max_delay <D_ext> -to [get_pins <harden_inst>/<input_pin>]
set TOP_SDC [file join $RUN_DIR top_dc.sdc]

# Harden list CSV. Required columns:
#   harden_name,inst_path,clean_sdc,delay_candidate_file,netlist,module
#
# Minimal example:
#   harden_name,inst_path,clean_sdc,delay_candidate_file,netlist,module
#   ucie0,u_ucie_0,./sdc/ucie0_clean.sdc,,./netlist/ucie_flat.v,ucie_uaxi_top
set HARDEN_LIST [file join $RUN_DIR harden_list.csv]

# Output directory.
set OUT_DIR $RUN_DIR

# Final flattened SDC name. In PrimeTime this is derived from current_design,
# for example link_top -> link_top_flatten.sdc. In non-PT/demo execution it
# falls back to current_integration_top_flatten.sdc.
if {![catch {current_design} _stage2_top_design] && $_stage2_top_design ne ""} {
    set TOP_MODULE_NAME $_stage2_top_design
} else {
    set TOP_MODULE_NAME current_integration_top
}
regsub -all {[^A-Za-z0-9_.-]+} $TOP_MODULE_NAME "_" TOP_MODULE_NAME
regsub -all {^_+|_+$} $TOP_MODULE_NAME "" TOP_MODULE_NAME

# Merge policy.
#   replace  : recommended; consumed top/harden delay commands are removed from
#              final source intent and written to merged_delay_removed.sdc.
#   additive : debug mode; keep original delay commands and add E2E commands.
set MERGE_MODE replace

# Partial merge policy for harden open_from segments with multiple inferred
# boundary inputs.
#   residual_through : recommended; generate conservative residual constraints
#                      for unmatched boundary pins.
#   review           : do not merge partially matched open_from groups.
set PARTIAL_MERGE_POLICY residual_through

# Policy for harden complete segments whose boundary input has no top segment.
#   review                : recommended default.
#   conservative_through  : emit residual -through constraint with harden D_int.
set UNMATCHED_HARDEN_POLICY review

# Allow top open_from + harden segment to generate:
#   -through [get_pins <boundary_pin>] -to [get_pins <internal_endpoint>]
set ALLOW_THROUGH true

# Safety limits.
set MAX_ENDPOINTS 1000
set MAX_ENUM_OBJECTS 64

###############################################################################
# Derived output files
###############################################################################

set OUT_E2E_SDC     [file join $OUT_DIR generated_e2e_delay.sdc]
set OUT_REPORT      [file join $OUT_DIR integration_delay_merge.rpt]
set OUT_REMOVED_SDC [file join $OUT_DIR merged_delay_removed.sdc]
set OUT_REVIEW_RPT  [file join $OUT_DIR unmerged_delay_review.rpt]
set OUT_FINAL_SDC   [file join $OUT_DIR ${TOP_MODULE_NAME}_flatten.sdc]

###############################################################################
# Script location
###############################################################################

# This wrapper is expected to live in the same directory as
# integration_delay_merger.pt.tcl. If you copy this wrapper elsewhere, change
# STAGE2_SCRIPT explicitly.
set THIS_SCRIPT [file normalize [info script]]
set THIS_DIR    [file dirname $THIS_SCRIPT]
set STAGE2_SCRIPT [file join $THIS_DIR integration_delay_merger.pt.tcl]

###############################################################################
# Preflight
###############################################################################

foreach required_file [list $STAGE2_SCRIPT $TOP_SDC $HARDEN_LIST] {
    if {![file exists $required_file]} {
        error "Required file not found: $required_file"
    }
}

if {![file isdirectory $OUT_DIR]} {
    file mkdir $OUT_DIR
}

puts "INFO: Stage 2 script      : $STAGE2_SCRIPT"
puts "INFO: Run directory       : $RUN_DIR"
puts "INFO: Top SDC             : $TOP_SDC"
puts "INFO: Harden list         : $HARDEN_LIST"
puts "INFO: Output E2E SDC      : $OUT_E2E_SDC"
puts "INFO: Final flatten SDC   : $OUT_FINAL_SDC"
puts "INFO: Merge mode          : $MERGE_MODE"

###############################################################################
# Build
###############################################################################

source $STAGE2_SCRIPT

stage2_delay::build \
    -top_sdc $TOP_SDC \
    -harden_list $HARDEN_LIST \
    -out_e2e_sdc $OUT_E2E_SDC \
    -out_report $OUT_REPORT \
    -out_removed_sdc $OUT_REMOVED_SDC \
    -out_review_rpt $OUT_REVIEW_RPT \
    -out_final_sdc $OUT_FINAL_SDC \
    -merge_mode $MERGE_MODE \
    -partial_merge_policy $PARTIAL_MERGE_POLICY \
    -unmatched_harden_policy $UNMATCHED_HARDEN_POLICY \
    -allow_through $ALLOW_THROUGH \
    -max_endpoints $MAX_ENDPOINTS \
    -max_enum_objects $MAX_ENUM_OBJECTS

puts "INFO: Stage 2 complete."
puts "INFO: Generated E2E SDC   : $OUT_E2E_SDC"
puts "INFO: Merge report        : $OUT_REPORT"
puts "INFO: Removed constraints : $OUT_REMOVED_SDC"
puts "INFO: Review report       : $OUT_REVIEW_RPT"
puts "INFO: Final flatten SDC   : $OUT_FINAL_SDC"

###############################################################################
# Optional PT post-check
###############################################################################
#
# Uncomment after reviewing generated_e2e_delay.sdc if you want this wrapper to
# source the generated file and run standard PT checks immediately.
#
# stage2_delay::post_check -e2e_sdc $OUT_E2E_SDC
