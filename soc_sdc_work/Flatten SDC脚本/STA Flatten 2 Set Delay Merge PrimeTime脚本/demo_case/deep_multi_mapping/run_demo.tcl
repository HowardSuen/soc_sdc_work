# Deep demo runner for Stage 2 without PrimeTime.
# It demonstrates multi-object pair expansion, many-to-many merge, partial
# leftover rewriting, and output-boundary review behavior.

set DEMO_DIR [file dirname [file normalize [info script]]]
set STAGE2_DIR [file normalize [file join $DEMO_DIR ../..]]

# Minimal PrimeTime-like query mock for running this demo with plain tclsh.
# In real PrimeTime these procs already exist, so the demo does not override
# the live STA database.
if {[info commands current_design] eq ""} {
    proc current_design {} {
        return deep_multi_mapping
    }
}

if {[info commands sizeof_collection] eq ""} {
    proc sizeof_collection {coll} {
        return [llength $coll]
    }
}

if {[info commands foreach_in_collection] eq ""} {
    proc foreach_in_collection {var coll body} {
        upvar 1 $var item
        foreach item $coll {
            uplevel 1 $body
        }
    }
}

if {[info commands get_pins] eq ""} {
    proc get_pins {args} {
        if {[lsearch -exact $args "-of_objects"] >= 0} {
            return {}
        }
        return [list [lindex $args end]]
    }
}

if {[info commands get_attribute] eq ""} {
    array set ::DEMO_PT_DIRECTIONS {
        u_src0/Q out
        u_src1/Q out
        u_src2/Q out
        u_h0/cfg_i in
        u_h0/mode_i in
        u_h0/unused_i in
        u_h0/no_top_i in
        u_h0/pass_i in
        u_h0/pass_o out
        u_h0/u_cfg_reg/D in
        u_h0/u_cfg_shadow_reg/D in
        u_h0/u_mode_reg/D in
        u_h0/u_hold_reg/D in
    }

    proc get_attribute {obj attr} {
        set name [lindex $obj 0]
        if {$attr eq "full_name"} {
            return $name
        }
        if {$attr eq "direction" && [info exists ::DEMO_PT_DIRECTIONS($name)]} {
            return $::DEMO_PT_DIRECTIONS($name)
        }
        return ""
    }
}

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
