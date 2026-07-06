# Deep demo runner for Stage 2 without PrimeTime.
# It demonstrates multi-object pair expansion, many-to-many merge, partial
# leftover rewriting, and output-boundary review behavior.

set DEMO_DIR [file dirname [file normalize [info script]]]
set STAGE2_DIR [file normalize [file join $DEMO_DIR ../..]]

set ::STAGE2_AUTO_RUN false
source [file join $STAGE2_DIR run_stage2_merge_delay.tcl]

stage2_delay::build \
    -top_sdc [file join $DEMO_DIR top_dc.sdc] \
    -harden_list [file join $DEMO_DIR harden_list.csv] \
    -out_e2e_sdc [file join $DEMO_DIR generated_e2e_delay.sdc] \
    -out_report [file join $DEMO_DIR integration_delay_merge.rpt] \
    -out_removed_sdc [file join $DEMO_DIR merged_delay_removed.sdc] \
    -out_review_rpt [file join $DEMO_DIR unmerged_delay_review.rpt] \
    -out_final_sdc [file join $DEMO_DIR deep_multi_mapping_flatten.sdc] \
    -merge_mode replace \
    -partial_merge_policy residual_through \
    -unmatched_harden_policy review \
    -allow_through true
