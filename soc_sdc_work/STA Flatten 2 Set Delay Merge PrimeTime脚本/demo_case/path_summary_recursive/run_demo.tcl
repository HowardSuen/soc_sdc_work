# Recursive path-summary demo runner for Stage 2 without PrimeTime.

set DEMO_DIR [file dirname [file normalize [info script]]]
set STAGE2_DIR [file normalize [file join $DEMO_DIR ../..]]

if {[info commands current_design] eq ""} {
    proc current_design {} {
        return path_summary_recursive
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
        u_up/u_reg/Q out
        u_up/data_o out
        u_h0/cfg_i in
        u_h0/u_reg/D in
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
    -out_final_sdc [file join $DEMO_DIR path_summary_recursive_flatten.sdc] \
    -merge_mode replace \
    -recursive_chain_mode auto \
    -max_chain_depth 6 \
    -allow_through true
