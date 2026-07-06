# run_stage2_merge_delay.tcl
#
# Stage 2: Integration E2E Delay Merge Proc
#
# This script is intended to be sourced in PrimeTime after the current
# integration top has been linked.  It parses top and Stage-1-cleaned harden
# SDC files, records set_max_delay/set_min_delay segments without applying
# them to the PT timing database, and emits static end-to-end delay
# constraints in the current integration scope.

###############################################################################
# Single-file runner user settings
###############################################################################
#
# Normal PrimeTime usage:
#   1. Edit only this section.
#   2. source /path/to/run_stage2_merge_delay.tcl
#
# Advanced/library usage:
#   set ::STAGE2_AUTO_RUN false
#   source /path/to/run_stage2_merge_delay.tcl
#   stage2_delay::build ...

if {![info exists ::STAGE2_AUTO_RUN]} {
    set ::STAGE2_AUTO_RUN true
}

# Current integration run directory. Edit this path for normal use.
# This directory should contain top_dc.sdc and harden_list.csv unless TOP_SDC
# / HARDEN_LIST are overridden below.
set ::RUN_DIR [pwd]

# Top integration SDC. Typical target delay segment:
#   set_max_delay <D_ext> -from <S> -to [get_pins <harden_inst>/<input_pin>]
# or:
#   set_max_delay <D_ext> -to [get_pins <harden_inst>/<input_pin>]
set ::TOP_SDC [file join $::RUN_DIR top_dc.sdc]

# Harden list CSV. Required columns:
#   harden_name,inst_path,clean_sdc,delay_candidate_file,netlist,module
set ::HARDEN_LIST [file join $::RUN_DIR harden_list.csv]

# Output directory.
set ::OUT_DIR $::RUN_DIR

# Optional final flattened SDC name. Leave empty to derive from current_design:
#   <top_module_name>_flatten.sdc
set ::OUT_FINAL_SDC ""

# Merge policy.
#   replace  : recommended; consumed delay commands are removed from final SDC.
#   additive : debug mode; keep original delay commands and add E2E commands.
set ::MERGE_MODE replace

# Partial merge policy for harden open_from segments with multiple inferred
# boundary inputs.
set ::PARTIAL_MERGE_POLICY residual_through

# Policy for harden complete segments whose boundary input has no top segment.
set ::UNMATCHED_HARDEN_POLICY review

# Allow top open_from + harden segment to generate -through <boundary> -to <E>.
set ::ALLOW_THROUGH true

# Safety limits.
set ::MAX_ENDPOINTS 1000
set ::MAX_ENUM_OBJECTS 64

# Optional output file overrides. Leave empty to use OUT_DIR defaults.
set ::OUT_E2E_SDC ""
set ::OUT_REPORT ""
set ::OUT_REMOVED_SDC ""
set ::OUT_REVIEW_RPT ""

# Optional post-check after build. Keep disabled until generated SDC is reviewed.
set ::STAGE2_POST_CHECK false

set ::STAGE2_SCRIPT_FILE [file normalize [info script]]

namespace eval stage2_delay {
    variable VERSION "v0.4.1"
    variable TOOL_NAME "run_stage2_merge_delay.tcl"
    variable STAGE_NAME "STA Flatten 2 Set Delay Merge PrimeTime"
    variable AUTHOR "Howard"

    variable options
    variable hardens
    variable top_segments
    variable harden_segments
    variable passthrough_segments
    variable generated_cmds
    variable residual_cmds
    variable consumed_constraints
    variable consumed_segments
    variable review_items
    variable report_items
    variable command_seq
    variable boundary_input_cache

    array set options {
        -top_sdc ""
        -harden_list ""
        -out_e2e_sdc "generated_e2e_delay.sdc"
        -out_final_sdc ""
        -out_report "integration_delay_merge.rpt"
        -out_removed_sdc "merged_delay_removed.sdc"
        -out_review_rpt "unmerged_delay_review.rpt"
        -merge_mode "replace"
        -top_open_from_mode "through"
        -allow_through "true"
        -allow_collapse_single_boundary "false"
        -partial_merge_policy "residual_through"
        -unmatched_harden_policy "review"
        -max_endpoints 1000
        -max_enum_objects 64
        -check_units "true"
        -expect_units ""
        -strict "false"
        -debug "false"
    }
}

proc stage2_delay::reset_state {} {
    variable hardens
    variable top_segments
    variable harden_segments
    variable passthrough_segments
    variable generated_cmds
    variable residual_cmds
    variable consumed_constraints
    variable consumed_segments
    variable review_items
    variable report_items
    variable command_seq
    variable boundary_input_cache

    set hardens {}
    set top_segments {}
    set harden_segments {}
    set passthrough_segments {}
    set generated_cmds {}
    set residual_cmds {}
    array unset consumed_constraints
    array set consumed_constraints {}
    set consumed_segments {}
    set review_items {}
    set report_items {}
    set command_seq 0
    array unset boundary_input_cache
    array set boundary_input_cache {}
}

proc stage2_delay::build {args} {
    variable options

    reset_state
    parse_options {*}$args
    validate_options
    apply_derived_options
    print_author_banner

    read_harden_list $options(-harden_list)
    extract_delay_segments_from_sdc $options(-top_sdc) top ""
    foreach harden $::stage2_delay::hardens {
        array set h $harden
        if {[info exists h(clean_sdc)] && $h(clean_sdc) ne ""} {
            extract_delay_segments_from_sdc $h(clean_sdc) harden $h(inst_path)
        }
        if {[info exists h(delay_candidate_file)] && $h(delay_candidate_file) ne ""} {
            read_harden_delay_candidates $h(delay_candidate_file) $h(inst_path)
        }
        array unset h
    }

    classify_segments
    match_top_to_harden_segments
    write_e2e_sdc $options(-out_e2e_sdc)
    write_removed_sdc $options(-out_removed_sdc)
    write_review_report $options(-out_review_rpt)
    write_report $options(-out_report)
    write_final_sdc $options(-out_final_sdc)
}

proc stage2_delay::author_banner_lines {} {
    variable TOOL_NAME
    variable STAGE_NAME
    variable AUTHOR
    variable VERSION

    return [list \
        "============================================================" \
        "  Script  : $TOOL_NAME" \
        "  Stage   : $STAGE_NAME" \
        "  Author  : $AUTHOR" \
        "  Version : $VERSION" \
        "============================================================" \
    ]
}

proc stage2_delay::print_author_banner {} {
    foreach line [author_banner_lines] {
        puts $line
    }
}

proc stage2_delay::write_author_banner {file_handle {prefix ""}} {
    foreach line [author_banner_lines] {
        puts $file_handle "${prefix}${line}"
    }
}

proc stage2_delay::parse_options {args} {
    variable options
    set valid [array names options]
    set idx 0
    while {$idx < [llength $args]} {
        set key [lindex $args $idx]
        if {[lsearch -exact $valid $key] < 0} {
            error "unknown option: $key"
        }
        incr idx
        if {$idx >= [llength $args]} {
            error "missing value for option: $key"
        }
        set options($key) [lindex $args $idx]
        incr idx
    }
}

proc stage2_delay::validate_options {} {
    variable options
    foreach required {-top_sdc -harden_list} {
        if {$options($required) eq ""} {
            error "$required is required"
        }
    }
    if {$options(-merge_mode) ni {replace additive}} {
        error "-merge_mode must be replace or additive"
    }
    if {$options(-top_open_from_mode) ni {through enumerate_static_startpoints collapse_single_boundary}} {
        error "-top_open_from_mode has invalid value"
    }
    if {$options(-partial_merge_policy) ni {residual_through review}} {
        error "-partial_merge_policy must be residual_through or review"
    }
    if {$options(-unmatched_harden_policy) ni {review conservative_through}} {
        error "-unmatched_harden_policy must be review or conservative_through"
    }
}

proc stage2_delay::apply_derived_options {} {
    variable options
    if {$options(-out_final_sdc) eq ""} {
        set out_dir [file dirname [file normalize $options(-out_e2e_sdc)]]
        set top_name [safe_filename_token [current_scope_name]]
        set options(-out_final_sdc) [file join $out_dir "${top_name}_flatten.sdc"]
    }
}

proc stage2_delay::safe_filename_token {text} {
    set token [string trim $text]
    if {$token eq "" || [string match "<*>" $token]} {
        set token "current_integration_top"
    }
    regsub -all {[^A-Za-z0-9_.-]+} $token "_" token
    regsub -all {^_+|_+$} $token "" token
    if {$token eq ""} {
        set token "current_integration_top"
    }
    return $token
}

proc stage2_delay::read_harden_list {path} {
    variable hardens
    set base_dir [file dirname [file normalize $path]]
    set rows [read_csv_dicts $path]
    set hardens {}
    foreach row $rows {
        array set r $row
        set inst [dict_get_default r inst_path ""]
        if {$inst eq ""} {
            error "harden_list row missing inst_path"
        }
        foreach path_key {clean_sdc delay_candidate_file netlist} {
            if {[info exists r($path_key)] && $r($path_key) ne "" && [file pathtype $r($path_key)] ne "absolute"} {
                set r($path_key) [file normalize [file join $base_dir $r($path_key)]]
            }
        }
        lappend hardens [array get r]
        array unset r
    }
}

proc stage2_delay::read_csv_dicts {path} {
    set fin [open $path r]
    set text [read $fin]
    close $fin
    set lines [split $text "\n"]
    set header {}
    set rows {}
    foreach raw $lines {
        set line [string trim $raw]
        if {$line eq ""} {
            continue
        }
        set fields [csv_split_line $line]
        if {[llength $header] == 0} {
            set header $fields
            continue
        }
        set row {}
        for {set idx 0} {$idx < [llength $header]} {incr idx} {
            set key [string trim [lindex $header $idx]]
            set value ""
            if {$idx < [llength $fields]} {
                set value [string trim [lindex $fields $idx]]
            }
            lappend row $key $value
        }
        lappend rows $row
    }
    return $rows
}

proc stage2_delay::csv_split_line {line} {
    set out {}
    set cur ""
    set in_quote 0
    set len [string length $line]
    for {set idx 0} {$idx < $len} {incr idx} {
        set ch [string index $line $idx]
        if {$ch eq "\""} {
            if {$in_quote && $idx + 1 < $len && [string index $line [expr {$idx + 1}]] eq "\""} {
                append cur "\""
                incr idx
            } else {
                set in_quote [expr {!$in_quote}]
            }
        } elseif {$ch eq "," && !$in_quote} {
            lappend out $cur
            set cur ""
        } else {
            append cur $ch
        }
    }
    lappend out $cur
    return $out
}

proc stage2_delay::dict_get_default {array_name key default} {
    upvar 1 $array_name arr
    if {[info exists arr($key)]} {
        return $arr($key)
    }
    return $default
}

proc stage2_delay::extract_delay_segments_from_sdc {path source harden_inst} {
    set fin [open $path r]
    set text [read $fin]
    close $fin
    set commands [scan_tcl_commands $text]
    foreach item $commands {
        array set cmd $item
        set words [tokenize_words $cmd(text)]
        if {[llength $words] == 0} {
            array unset cmd
            continue
        }
        set command [lindex $words 0]
        if {$command ni {set_max_delay set_min_delay}} {
            array unset cmd
            continue
        }
        set seg [segment_from_words $words $source $path $cmd(line) $cmd(id) $cmd(text) $harden_inst]
        foreach expanded [expand_segment $seg] {
            add_segment $expanded
        }
        array unset cmd
    }
}

proc stage2_delay::scan_tcl_commands {text} {
    variable command_seq
    set out {}
    set buf ""
    set start_line 0
    set line_no 0
    foreach raw [split $text "\n"] {
        incr line_no
        set line [strip_inline_comment $raw]
        if {[string trim $line] eq ""} {
            continue
        }
        if {$buf eq ""} {
            set start_line $line_no
        }
        set trimmed [string trimright $line]
        if {[string length $trimmed] > 0 && [string index $trimmed end] eq "\\" && ![is_escaped $trimmed [expr {[string length $trimmed] - 1}]]} {
            append buf [string range $trimmed 0 end-1] " "
            continue
        }
        append buf $trimmed
        foreach cmd [split_semicolon_commands $buf] {
            set text_cmd [string trimright [string trim $cmd] ";"]
            if {$text_cmd eq ""} {
                continue
            }
            incr command_seq
            lappend out [list id [format "CMD%06d" $command_seq] line $start_line end_line $line_no text $text_cmd]
        }
        set buf ""
        set start_line 0
    }
    if {[string trim $buf] ne ""} {
        foreach cmd [split_semicolon_commands $buf] {
            set text_cmd [string trimright [string trim $cmd] ";"]
            if {$text_cmd eq ""} {
                continue
            }
            incr command_seq
            lappend out [list id [format "CMD%06d" $command_seq] line $start_line end_line $line_no text $text_cmd]
        }
    }
    return $out
}

proc stage2_delay::is_escaped {text idx} {
    set count 0
    incr idx -1
    while {$idx >= 0 && [string index $text $idx] eq "\\"} {
        incr count
        incr idx -1
    }
    return [expr {$count % 2 == 1}]
}

proc stage2_delay::strip_inline_comment {line} {
    set quote 0
    set brace_depth 0
    set bracket_depth 0
    set len [string length $line]
    for {set idx 0} {$idx < $len} {incr idx} {
        set ch [string index $line $idx]
        set code [scan $ch %c]
        if {$ch eq "\\"} {
            incr idx
            continue
        }
        if {$ch eq "\"" && !$brace_depth && ![is_escaped $line $idx]} {
            set quote [expr {!$quote}]
        } elseif {!$quote} {
            if {$code == 123} {
                incr brace_depth
            } elseif {$code == 125 && $brace_depth > 0} {
                incr brace_depth -1
            } elseif {$code == 91} {
                incr bracket_depth
            } elseif {$code == 93 && $bracket_depth > 0} {
                incr bracket_depth -1
            } elseif {$ch eq "#" && $brace_depth == 0 && $bracket_depth == 0} {
                if {$idx == 0 || [string is space [string index $line [expr {$idx - 1}]]] || [string index $line [expr {$idx - 1}]] eq ";"} {
                    return [string trimright [string range $line 0 [expr {$idx - 1}]]]
                }
            }
        }
    }
    return [string trimright $line]
}

proc stage2_delay::split_semicolon_commands {text} {
    set out {}
    set quote 0
    set brace_depth 0
    set bracket_depth 0
    set start 0
    set len [string length $text]
    for {set idx 0} {$idx < $len} {incr idx} {
        set ch [string index $text $idx]
        set code [scan $ch %c]
        if {$ch eq "\\"} {
            incr idx
            continue
        }
        if {$ch eq "\"" && !$brace_depth && ![is_escaped $text $idx]} {
            set quote [expr {!$quote}]
        } elseif {!$quote} {
            if {$code == 123} {
                incr brace_depth
            } elseif {$code == 125 && $brace_depth > 0} {
                incr brace_depth -1
            } elseif {$code == 91} {
                incr bracket_depth
            } elseif {$code == 93 && $bracket_depth > 0} {
                incr bracket_depth -1
            } elseif {$ch eq ";" && $brace_depth == 0 && $bracket_depth == 0} {
                lappend out [string range $text $start [expr {$idx - 1}]]
                set start [expr {$idx + 1}]
            }
        }
    }
    lappend out [string range $text $start end]
    return $out
}

proc stage2_delay::tokenize_words {text} {
    set out {}
    set idx 0
    set len [string length $text]
    while {$idx < $len} {
        while {$idx < $len && [string is space [string index $text $idx]]} {
            incr idx
        }
        if {$idx >= $len} {
            break
        }
        set start $idx
        set ch [string index $text $idx]
        set ch_code [scan $ch %c]
        if {$ch_code == 123} {
            set end [find_matching $text $idx 123 125]
            if {$end < 0} {
                lappend out [string range $text $start end]
                break
            }
            lappend out [string range $text $start $end]
            set idx [expr {$end + 1}]
        } elseif {$ch eq "\""} {
            incr idx
            while {$idx < $len} {
                set c [string index $text $idx]
                if {$c eq "\\"} {
                    incr idx 2
                    continue
                }
                if {$c eq "\""} {
                    incr idx
                    break
                }
                incr idx
            }
            lappend out [string range $text $start [expr {$idx - 1}]]
        } else {
            set pieces ""
            while {$idx < $len && ![string is space [string index $text $idx]]} {
                set c [string index $text $idx]
                if {$c eq "\\"} {
                    append pieces [string range $text $idx [expr {$idx + 1}]]
                    incr idx 2
                } elseif {[scan $c %c] == 91} {
                    set end [find_matching $text $idx 91 93]
                    if {$end < 0} {
                        append pieces [string range $text $idx end]
                        set idx $len
                    } else {
                        append pieces [string range $text $idx $end]
                        set idx [expr {$end + 1}]
                    }
                } else {
                    append pieces $c
                    incr idx
                }
            }
            lappend out $pieces
        }
    }
    return $out
}

proc stage2_delay::find_matching {text start open_code close_code} {
    set depth 0
    set quote 0
    set len [string length $text]
    for {set idx $start} {$idx < $len} {incr idx} {
        set ch [string index $text $idx]
        set code [scan $ch %c]
        if {$ch eq "\\"} {
            incr idx
            continue
        }
        if {$ch eq "\"" && $open_code != 34 && ![is_escaped $text $idx]} {
            set quote [expr {!$quote}]
        } elseif {!$quote} {
            if {$code == $open_code} {
                incr depth
            } elseif {$code == $close_code} {
                incr depth -1
                if {$depth == 0} {
                    return $idx
                }
            }
        }
    }
    return -1
}

proc stage2_delay::segment_from_words {words source file line cmd_id original harden_inst} {
    set command [lindex $words 0]
    set type [expr {$command eq "set_max_delay" ? "max" : "min"}]
    set delay ""
    set from_expr ""
    set to_expr ""
    set through_exprs {}
    set flags {}
    set idx 1
    while {$idx < [llength $words]} {
        set word [lindex $words $idx]
        if {$word eq "-from"} {
            incr idx
            set from_expr [lindex $words $idx]
        } elseif {$word eq "-to"} {
            incr idx
            set to_expr [lindex $words $idx]
        } elseif {$word eq "-through"} {
            incr idx
            lappend through_exprs [lindex $words $idx]
        } elseif {$word in {-rise_from -fall_from -rise_to -fall_to -rise_through -fall_through -rise -fall}} {
            lappend flags $word
            incr idx
            if {$idx < [llength $words] && ![string match "-*" [lindex $words $idx]]} {
                lappend flags [lindex $words $idx]
            } else {
                incr idx -1
            }
        } elseif {[string match "-*" $word]} {
            lappend flags $word
            if {$word ni {-datapath_only -ignore_clock_latency -network_latency_included -source_latency_included}} {
                if {$idx + 1 < [llength $words] && ![string match "-*" [lindex $words [expr {$idx + 1}]]]} {
                    incr idx
                    lappend flags [lindex $words $idx]
                }
            }
        } elseif {$delay eq ""} {
            set delay [strip_braces $word]
        }
        incr idx
    }

    set from_records {}
    set to_records {}
    set through_records {}
    set status "ok"
    set reason ""
    if {$from_expr ne ""} {
        set from_records [resolve_object_expr $from_expr]
    }
    if {$to_expr ne ""} {
        set to_records [resolve_object_expr $to_expr]
    }
    foreach expr $through_exprs {
        set through_records [concat $through_records [resolve_object_expr $expr]]
    }
    if {$to_expr eq ""} {
        set status "review"
        set reason "NO_TO_OBJECT"
    }
    if {$delay eq "" || ![string is double -strict $delay]} {
        set status "review"
        set reason "NON_NUMERIC_DELAY"
    }
    if {[has_clock_or_unknown $from_records] || [has_clock_or_unknown $to_records] || [has_clock_or_unknown $through_records]} {
        set status "review"
        set reason "CLOCK_OR_UNKNOWN_OBJECT"
    }
    if {[has_edge_specific_flag $flags]} {
        set status "review"
        set reason "EDGE_SPECIFIC_OPTION"
    }
    set kind [expr {$from_expr eq "" ? "open_from" : "complete"}]
    return [list \
        id $cmd_id \
        type $type \
        kind $kind \
        delay $delay \
        from_expr $from_expr \
        to_expr $to_expr \
        through_exprs $through_exprs \
        from_records $from_records \
        to_records $to_records \
        through_records $through_records \
        flags $flags \
        source $source \
        source_file $file \
        line_no $line \
        original_text $original \
        original_id $cmd_id \
        split_index 1 \
        split_total 1 \
        harden_inst $harden_inst \
        class "" \
        boundary_pins {} \
        status $status \
        failure_reason $reason \
    ]
}

proc stage2_delay::expand_segment {seg} {
    array set s $seg
    if {$s(status) ne "ok"} {
        array unset s
        return [list $seg]
    }
    if {[llength $s(to_records)] == 0} {
        array unset s
        return [list $seg]
    }

    set from_choices $s(from_records)
    if {[llength $from_choices] == 0} {
        set from_choices [list {}]
    }
    set to_choices $s(to_records)
    set total [expr {[llength $from_choices] * [llength $to_choices]}]
    if {$total <= 1} {
        set s(split_total) 1
        set s(split_index) 1
        set result [array get s]
        array unset s
        return [list $result]
    }

    set out {}
    set idx 0
    foreach from_rec $from_choices {
        foreach to_rec $to_choices {
            incr idx
            array set e [array get s]
            set e(id) "$s(original_id).[format %03d $idx]"
            set e(split_index) $idx
            set e(split_total) $total
            if {[llength $from_rec] == 0} {
                set e(from_records) {}
                set e(kind) open_from
            } else {
                set e(from_records) [list $from_rec]
                set e(kind) complete
            }
            set e(to_records) [list $to_rec]
            lappend out [array get e]
            array unset e
        }
    }
    array unset s
    return $out
}

proc stage2_delay::strip_braces {text} {
    set text [string trim $text]
    if {[string length $text] >= 2} {
        set first [string index $text 0]
        set last [string index $text end]
        set first_code [scan $first %c]
        set last_code [scan $last %c]
        if {($first_code == 123 && $last_code == 125) || ($first eq "\"" && $last eq "\"")} {
            return [string trim [string range $text 1 end-1]]
        }
    }
    return $text
}

proc stage2_delay::has_edge_specific_flag {flags} {
    foreach flag $flags {
        if {$flag in {-rise_from -fall_from -rise_to -fall_to -rise_through -fall_through -rise -fall}} {
            return 1
        }
    }
    return 0
}

proc stage2_delay::has_clock_or_unknown {records} {
    foreach rec $records {
        array set r $rec
        if {$r(object_class) in {clock unknown}} {
            array unset r
            return 1
        }
        array unset r
    }
    return 0
}

proc stage2_delay::add_segment {seg} {
    variable top_segments
    variable harden_segments
    array set s $seg
    if {$s(source) eq "top"} {
        lappend top_segments $seg
    } else {
        lappend harden_segments $seg
    }
    array unset s
}

proc stage2_delay::resolve_object_expr {expr} {
    set expr [string trim $expr]
    if {$expr eq ""} {
        return {}
    }
    set expr_len [string length $expr]
    set first_code -1
    set last_code -1
    if {$expr_len > 0} {
        set first_code [scan [string index $expr 0] %c]
        set last_code [scan [string index $expr end] %c]
    }
    if {$expr_len >= 2 && $first_code == 91 && $last_code == 93} {
        set inner [string range $expr 1 end-1]
        set words [tokenize_words $inner]
        if {[llength $words] == 0} {
            return [list [object_record unknown $expr "" ""]]
        }
        set cmd [lindex $words 0]
        if {$cmd eq "list"} {
            set out {}
            foreach item [lrange $words 1 end] {
                set out [concat $out [resolve_object_expr $item]]
            }
            return $out
        }
        if {$cmd ni {get_pins get_ports get_cells get_nets get_clocks}} {
            return [list [object_record unknown $expr "" ""]]
        }
        set objects {}
        set idx 1
        while {$idx < [llength $words]} {
            set word [lindex $words $idx]
            if {[string match "-*" $word]} {
                incr idx
                if {$word in {-filter -of_objects -of -regexp -exact -hierarchical -hier -quiet -nocase}} {
                    if {$idx < [llength $words] && ![string match "-*" [lindex $words $idx]] && $word in {-filter -of_objects -of}} {
                        incr idx
                    } else {
                        incr idx -1
                    }
                }
            } else {
                foreach obj [split_object_list $word] {
                    lappend objects $obj
                }
            }
            incr idx
        }
        set out {}
        foreach obj $objects {
            lappend out [object_record_from_get $cmd $obj]
        }
        return $out
    }
    set out {}
    foreach obj [split_object_list $expr] {
        lappend out [object_record unknown $obj "" ""]
    }
    return $out
}

proc stage2_delay::split_object_list {text} {
    set text [strip_braces $text]
    set out {}
    foreach item $text {
        if {[string trim $item] ne ""} {
            lappend out [string trim $item]
        }
    }
    if {[llength $out] == 0 && $text ne ""} {
        foreach item [split $text] {
            if {[string trim $item] ne ""} {
                lappend out [string trim $item]
            }
        }
    }
    return $out
}

proc stage2_delay::object_record_from_get {cmd name} {
    set class unknown
    if {$cmd eq "get_pins"} {
        set class pin
    } elseif {$cmd eq "get_ports"} {
        set class port
    } elseif {$cmd eq "get_cells"} {
        set class cell
    } elseif {$cmd eq "get_nets"} {
        set class net
    } elseif {$cmd eq "get_clocks"} {
        set class clock
    }
    set direction [pt_get_attr_by_name $class $name direction]
    set owner [owner_harden_inst $name]
    return [object_record $class $name $direction $owner]
}

proc stage2_delay::object_record {class name direction owner} {
    return [list object_class $class full_name $name direction $direction owner_harden_inst $owner]
}

proc stage2_delay::pt_get_attr_by_name {class name attr} {
    if {[info commands get_attribute] eq "" || $class eq "unknown" || $class eq "clock"} {
        if {$attr eq "direction"} {
            if {[regexp {/(D|DATA|CD|SD|A|B|I|IN)$} $name]} {
                return in
            }
            if {[regexp {/(Q|ZN|Z|OUT|Y)$} $name]} {
                return out
            }
        }
        return ""
    }
    set getter ""
    if {$class eq "pin"} {
        set getter get_pins
    } elseif {$class eq "port"} {
        set getter get_ports
    } elseif {$class eq "cell"} {
        set getter get_cells
    } elseif {$class eq "net"} {
        set getter get_nets
    } else {
        return ""
    }
    if {[catch {
        set coll [$getter -quiet $name]
        if {[sizeof_collection $coll] == 0} {
            return ""
        }
        return [get_attribute $coll $attr]
    } value]} {
        return ""
    }
    return $value
}

proc stage2_delay::owner_harden_inst {name} {
    variable hardens
    if {![info exists hardens]} {
        set hardens {}
    }
    set best ""
    foreach harden $hardens {
        array set h $harden
        set inst $h(inst_path)
        if {$name eq $inst || [string match "${inst}/*" $name]} {
            if {[string length $inst] > [string length $best]} {
                set best $inst
            }
        }
        array unset h
    }
    return $best
}

proc stage2_delay::classify_segments {} {
    variable top_segments
    variable harden_segments
    variable passthrough_segments
    variable review_items

    set new_top {}
    foreach seg $top_segments {
        array set s $seg
        set class [classify_top_segment [array get s]]
        set s(class) $class
        set updated [array get s]
        if {$class eq "merge_candidate"} {
            lappend new_top $updated
        } elseif {$class eq "passthrough"} {
            set s(passthrough_reason) [top_passthrough_reason [array get s]]
            set updated [array get s]
            lappend passthrough_segments $updated
        } else {
            add_review $updated "" $class "top segment not mergeable"
        }
        array unset s
    }
    set top_segments $new_top

    set new_harden {}
    foreach seg $harden_segments {
        array set s $seg
        set class [classify_harden_segment [array get s]]
        set s(class) $class
        set updated [array get s]
        if {$class eq "merge_candidate"} {
            if {$s(kind) eq "open_from"} {
                set s(boundary_pins) [find_boundary_inputs_to_endpoint [array get s]]
                set updated [array get s]
            }
            lappend new_harden $updated
        } elseif {$class eq "passthrough"} {
            set s(passthrough_reason) [harden_passthrough_reason [array get s]]
            set updated [array get s]
            lappend passthrough_segments $updated
        } else {
            add_review "" $updated $class "harden segment not mergeable"
        }
        array unset s
    }
    set harden_segments $new_harden
}

proc stage2_delay::top_passthrough_reason {seg} {
    array set s $seg
    set reason "TOP_PASSTHROUGH_UNKNOWN"
    if {[llength $s(to_records)] == 1} {
        array set to [lindex $s(to_records) 0]
        if {$to(owner_harden_inst) eq ""} {
            set reason "TOP_TO_NOT_UNDER_HARDEN_LIST to=[record_debug [array get to]] harden_insts=[harden_inst_list_for_debug]"
        } elseif {![is_harden_boundary_input_record [array get to]]} {
            set reason "TOP_TO_NOT_INPUT_BOUNDARY to=[record_debug [array get to]]"
        }
        array unset to
    } else {
        set reason "TOP_TO_OBJECT_COUNT_[llength $s(to_records)]"
    }
    array unset s
    return $reason
}

proc stage2_delay::harden_passthrough_reason {seg} {
    array set s $seg
    set reason "HARDEN_PASSTHROUGH_UNKNOWN"
    if {[llength $s(to_records)] == 1} {
        array set to [lindex $s(to_records) 0]
        if {$to(owner_harden_inst) ne $s(harden_inst)} {
            set reason "HARDEN_TO_NOT_UNDER_OWN_INSTANCE to=[record_debug [array get to]] expected_harden=$s(harden_inst)"
        } elseif {$s(kind) eq "complete" && [llength $s(from_records)] == 1} {
            array set from [lindex $s(from_records) 0]
            if {![is_harden_boundary_input_record [array get from]] || $from(owner_harden_inst) ne $s(harden_inst)} {
                set reason "HARDEN_FROM_NOT_INPUT_BOUNDARY from=[record_debug [array get from]] expected_harden=$s(harden_inst)"
            }
            array unset from
        } elseif {$s(kind) eq "complete"} {
            set reason "HARDEN_FROM_OBJECT_COUNT_[llength $s(from_records)]"
        }
        array unset to
    } else {
        set reason "HARDEN_TO_OBJECT_COUNT_[llength $s(to_records)]"
    }
    array unset s
    return $reason
}

proc stage2_delay::harden_inst_list_for_debug {} {
    variable hardens
    set names {}
    foreach harden $hardens {
        array set h $harden
        lappend names $h(inst_path)
        array unset h
    }
    return [join $names ","]
}

proc stage2_delay::record_debug {rec} {
    array set r $rec
    set text "class=$r(object_class),name=$r(full_name),direction=$r(direction),owner=$r(owner_harden_inst)"
    array unset r
    return $text
}

proc stage2_delay::classify_top_segment {seg} {
    array set s $seg
    if {$s(status) ne "ok"} {
        set result $s(failure_reason)
        array unset s
        return $result
    }
    if {[llength $s(to_records)] == 0} {
        array unset s
        return "NO_TO_OBJECT"
    }
    if {[llength $s(to_records)] != 1} {
        array unset s
        return "MULTI_OBJECT_TO"
    }
    array set to [lindex $s(to_records) 0]
    set owner $to(owner_harden_inst)
    if {$owner eq ""} {
        array unset to
        array unset s
        return "passthrough"
    }
    if {![is_harden_boundary_input_record [array get to]]} {
        if {[is_harden_boundary_output_record [array get to]] || [top_from_is_harden_boundary_output [array get s]]} {
            array unset to
            array unset s
            return "MULTI_HOP_NOT_SUPPORTED"
        }
        array unset to
        array unset s
        return "passthrough"
    }
    if {[top_from_is_harden_boundary_output [array get s]]} {
        array unset to
        array unset s
        return "MULTI_HOP_NOT_SUPPORTED"
    }
    array unset to
    array unset s
    return "merge_candidate"
}

proc stage2_delay::classify_harden_segment {seg} {
    array set s $seg
    if {$s(status) ne "ok"} {
        set result $s(failure_reason)
        array unset s
        return $result
    }
    if {[llength $s(to_records)] == 0} {
        array unset s
        return "NO_TO_OBJECT"
    }
    if {[llength $s(to_records)] != 1} {
        array unset s
        return "MULTI_OBJECT_TO"
    }
    array set to [lindex $s(to_records) 0]
    if {$to(owner_harden_inst) ne $s(harden_inst)} {
        array unset to
        array unset s
        return "passthrough"
    }
    if {[is_harden_boundary_output_record [array get to]]} {
        array unset to
        array unset s
        return "OUTPUT_DIRECTION_NOT_SUPPORTED"
    }
    if {$s(kind) eq "complete"} {
        if {[llength $s(from_records)] != 1} {
            array unset to
            array unset s
            return "MULTI_OBJECT_FROM"
        }
        array set from [lindex $s(from_records) 0]
        if {[is_harden_boundary_input_record [array get from]] && $from(owner_harden_inst) eq $s(harden_inst)} {
            array unset from
            array unset to
            array unset s
            return "merge_candidate"
        }
        array unset from
        array unset to
        array unset s
        return "passthrough"
    }
    array unset to
    array unset s
    return "merge_candidate"
}

proc stage2_delay::top_from_is_harden_boundary_output {seg} {
    array set s $seg
    foreach rec $s(from_records) {
        if {[is_harden_boundary_output_record $rec]} {
            array unset s
            return 1
        }
    }
    array unset s
    return 0
}

proc stage2_delay::is_harden_boundary_input_record {rec} {
    array set r $rec
    set result [expr {$r(object_class) eq "pin" && $r(owner_harden_inst) ne "" && ($r(direction) eq "in" || [regexp {/(.*_i|.*_in|.*in)$} $r(full_name)])}]
    array unset r
    return $result
}

proc stage2_delay::is_harden_boundary_output_record {rec} {
    array set r $rec
    set result [expr {$r(object_class) eq "pin" && $r(owner_harden_inst) ne "" && ($r(direction) eq "out" || [regexp {/(.*_o|.*_out|.*out)$} $r(full_name)])}]
    array unset r
    return $result
}

proc stage2_delay::find_boundary_inputs_to_endpoint {hseg} {
    variable options
    array set s $hseg
    array set to [lindex $s(to_records) 0]
    set endpoint $to(full_name)
    set harden_inst $s(harden_inst)

    set inferred {}
    if {[llength $s(through_records)] > 0} {
        foreach rec $s(through_records) {
            if {[is_harden_boundary_input_record $rec]} {
                lappend inferred $rec
            }
        }
        array unset to
        array unset s
        return [unique_records_by_name $inferred]
    }

    set inferred [pt_boundary_inputs_by_fanin $harden_inst $endpoint]
    if {[llength $inferred] == 0} {
        set inferred [pt_boundary_inputs_by_fanout $harden_inst $endpoint]
    }
    if {[llength $inferred] > $options(-max_endpoints)} {
        add_review "" [array get s] "TOO_MANY_BOUNDARY_INPUTS" "open_from endpoint exceeded -max_endpoints"
        set inferred {}
    }
    array unset to
    array unset s
    return [unique_records_by_name $inferred]
}

proc stage2_delay::pt_boundary_inputs_by_fanin {harden_inst endpoint} {
    if {[info commands all_fanin] eq "" || [info commands get_pins] eq "" || [info commands get_cells] eq ""} {
        return {}
    }
    if {[catch {
        set ep [get_pins -quiet $endpoint]
        if {[sizeof_collection $ep] == 0} {
            return {}
        }
        set cone [all_fanin -to $ep]
        set hcell [get_cells -quiet $harden_inst]
        if {[sizeof_collection $hcell] == 0} {
            return {}
        }
        set hpins [get_pins -quiet -of_objects $hcell]
        set hin [filter_collection $hpins "direction == in"]
        set out {}
        foreach_in_collection pin $hin {
            set name [get_attribute $pin full_name]
            if {[collection_contains_name $cone $name]} {
                lappend out [object_record pin $name [get_attribute $pin direction] $harden_inst]
            }
        }
        return $out
    } value]} {
        return {}
    }
    return $value
}

proc stage2_delay::pt_boundary_inputs_by_fanout {harden_inst endpoint} {
    if {[info commands all_fanout] eq "" || [info commands get_pins] eq "" || [info commands get_cells] eq ""} {
        return {}
    }
    if {[catch {
        set ep_name $endpoint
        set hcell [get_cells -quiet $harden_inst]
        if {[sizeof_collection $hcell] == 0} {
            return {}
        }
        set hpins [get_pins -quiet -of_objects $hcell]
        set hin [filter_collection $hpins "direction == in"]
        set out {}
        foreach_in_collection pin $hin {
            set name [get_attribute $pin full_name]
            set fanout [all_fanout -flat -from $pin]
            if {[collection_contains_name $fanout $ep_name]} {
                lappend out [object_record pin $name [get_attribute $pin direction] $harden_inst]
            }
        }
        return $out
    } value]} {
        return {}
    }
    return $value
}

proc stage2_delay::collection_contains_name {coll name} {
    if {[info commands foreach_in_collection] eq ""} {
        return 0
    }
    set found 0
    foreach_in_collection obj $coll {
        if {[catch {set obj_name [get_attribute $obj full_name]}]} {
            set obj_name [get_object_name $obj]
        }
        if {$obj_name eq $name} {
            set found 1
            break
        }
    }
    return $found
}

proc stage2_delay::unique_records_by_name {records} {
    set out {}
    array set seen {}
    foreach rec $records {
        array set r $rec
        if {![info exists seen($r(full_name))]} {
            set seen($r(full_name)) 1
            lappend out $rec
        }
        array unset r
    }
    return $out
}

proc stage2_delay::match_top_to_harden_segments {} {
    variable top_segments
    variable harden_segments
    variable options

    array set matched_top {}
    array set generated_pair {}
    foreach hseg $harden_segments {
        array set h $hseg
        set boundaries [harden_boundary_records [array get h]]
        if {[llength $boundaries] == 0} {
            add_review "" [array get h] "NO_BOUNDARY_INPUT" "harden open_from endpoint has no inferred boundary input"
            array unset h
            continue
        }
        set matched_boundaries {}
        foreach boundary $boundaries {
            set candidates [matching_top_segments $boundary $h(type)]
            if {[llength $candidates] == 0} {
                continue
            }
            foreach tseg $candidates {
                array set t $tseg
                set pair_key "$t(id)|$h(id)"
                if {[info exists generated_pair($pair_key)]} {
                    array unset t
                    continue
                }
                set generated [emit_generated_delay_cmd [array get t] [array get h] $boundary]
                if {$generated ne ""} {
                    consume_segment [array get t]
                    consume_segment [array get h]
                    set generated_pair($pair_key) 1
                    set matched_top($t(id)) 1
                    lappend matched_boundaries [record_full_name $boundary]
                    add_report_item "MERGED $t(id) + $h(id) boundary=[record_full_name $boundary] total=[expr {$t(delay) + $h(delay)}]"
                }
                array unset t
            }
        }
        set missing [missing_boundaries $boundaries $matched_boundaries]
        if {[llength $missing] > 0} {
            if {$h(kind) eq "open_from" && $options(-partial_merge_policy) eq "residual_through" && [llength $matched_boundaries] > 0} {
                foreach boundary $missing {
                    emit_residual_through_cmd [array get h] $boundary "PARTIAL_MERGE"
                }
                consume_segment [array get h]
            } elseif {$h(kind) eq "complete" && $options(-unmatched_harden_policy) eq "conservative_through" && [llength $matched_boundaries] == 0} {
                foreach boundary $boundaries {
                    emit_residual_through_cmd [array get h] $boundary "NO_TOP_SEGMENT_MATCHED"
                }
                consume_segment [array get h]
            } elseif {[llength $matched_boundaries] == 0} {
                add_review "" [array get h] "NO_TOP_SEGMENT_MATCHED" "no top delay segment matched harden boundary"
            } else {
                add_review "" [array get h] "PARTIAL_MERGE_REVIEW" "not all inferred boundary inputs matched top delay"
            }
        }
        array unset h
    }

    foreach tseg $top_segments {
        array set t $tseg
        if {![info exists matched_top($t(id))]} {
            add_review [array get t] "" "NO_HARDEN_SEGMENT_MATCHED" "top delay segment did not match any harden segment"
        }
        array unset t
    }
}

proc stage2_delay::harden_boundary_records {hseg} {
    array set h $hseg
    if {$h(kind) eq "complete"} {
        set result $h(from_records)
    } else {
        set result $h(boundary_pins)
    }
    array unset h
    return $result
}

proc stage2_delay::matching_top_segments {boundary type} {
    variable top_segments
    set out {}
    set bname [record_full_name $boundary]
    foreach tseg $top_segments {
        array set t $tseg
        if {$t(type) ne $type} {
            array unset t
            continue
        }
        if {[llength $t(to_records)] == 1 && [record_full_name [lindex $t(to_records) 0]] eq $bname} {
            lappend out [array get t]
        }
        array unset t
    }
    return $out
}

proc stage2_delay::missing_boundaries {boundaries matched_names} {
    set out {}
    foreach boundary $boundaries {
        if {[lsearch -exact $matched_names [record_full_name $boundary]] < 0} {
            lappend out $boundary
        }
    }
    return $out
}

proc stage2_delay::record_full_name {rec} {
    array set r $rec
    set name $r(full_name)
    array unset r
    return $name
}

proc stage2_delay::emit_generated_delay_cmd {tseg hseg boundary} {
    variable generated_cmds
    variable options
    array set t $tseg
    array set h $hseg
    set total [format_delay [expr {$t(delay) + $h(delay)}]]
    set to_rec [lindex $h(to_records) 0]
    if {![boundary_and_endpoint_same_harden $boundary $to_rec]} {
        add_review [array get t] [array get h] "BOUNDARY_ENDPOINT_OWNER_MISMATCH" "boundary and endpoint do not belong to same harden instance"
        array unset t
        array unset h
        return ""
    }
    set cmd_name [expr {$t(type) eq "max" ? "set_max_delay" : "set_min_delay"}]
    set cmd ""
    if {$t(kind) eq "complete"} {
        set from_rec [lindex $t(from_records) 0]
        if {![validate_startpoint_record $from_rec]} {
            add_review [array get t] [array get h] "INVALID_STARTPOINT" "generated -from object is not a legal startpoint"
            array unset t
            array unset h
            return ""
        }
        if {![validate_endpoint_record $to_rec]} {
            add_review [array get t] [array get h] "INVALID_ENDPOINT" "generated -to object is not a legal endpoint"
            array unset t
            array unset h
            return ""
        }
        set cmd "$cmd_name $total -from [format_record_collection $from_rec] -to [format_record_collection $to_rec]"
    } else {
        if {![truthy $options(-allow_through)]} {
            add_review [array get t] [array get h] "THROUGH_DISABLED" "top open_from requires -through but -allow_through is false"
            array unset t
            array unset h
            return ""
        }
        if {![validate_endpoint_record $to_rec]} {
            add_review [array get t] [array get h] "INVALID_ENDPOINT" "generated -to object is not a legal endpoint"
            array unset t
            array unset h
            return ""
        }
        set cmd "$cmd_name $total -through [format_record_collection $boundary] -to [format_record_collection $to_rec]"
    }
    lappend generated_cmds [list command $cmd top_id $t(id) harden_id $h(id) boundary [record_full_name $boundary] total $total]
    array unset t
    array unset h
    return $cmd
}

proc stage2_delay::emit_residual_through_cmd {hseg boundary reason} {
    variable residual_cmds
    array set h $hseg
    set to_rec [lindex $h(to_records) 0]
    set cmd_name [expr {$h(type) eq "max" ? "set_max_delay" : "set_min_delay"}]
    set cmd "$cmd_name [format_delay $h(delay)] -through [format_record_collection $boundary] -to [format_record_collection $to_rec]"
    lappend residual_cmds [list command $cmd harden_id $h(id) boundary [record_full_name $boundary] reason $reason]
    add_report_item "RESIDUAL_CONSERVATIVE $h(id) boundary=[record_full_name $boundary] reason=$reason"
    array unset h
}

proc stage2_delay::boundary_and_endpoint_same_harden {boundary endpoint} {
    array set b $boundary
    array set e $endpoint
    set result [expr {$b(owner_harden_inst) ne "" && $b(owner_harden_inst) eq $e(owner_harden_inst)}]
    array unset b
    array unset e
    return $result
}

proc stage2_delay::validate_startpoint_record {rec} {
    array set r $rec
    set ok 0
    if {$r(object_class) eq "port" && ($r(direction) eq "in" || $r(direction) eq "")} {
        set ok 1
    } elseif {$r(object_class) eq "pin" && $r(owner_harden_inst) eq ""} {
        set ok 1
    } elseif {$r(object_class) eq "pin" && [regexp {/(Q|QN|Z|ZN|CP|CK|CLK)$} $r(full_name)]} {
        set ok 1
    }
    array unset r
    return $ok
}

proc stage2_delay::validate_endpoint_record {rec} {
    array set r $rec
    set ok 0
    if {$r(object_class) eq "port" && ($r(direction) eq "out" || $r(direction) eq "")} {
        set ok 1
    } elseif {$r(object_class) eq "pin" && [regexp {/(D|DATA|CD|SD|A|B|I|IN)$} $r(full_name)]} {
        set ok 1
    } elseif {$r(object_class) eq "pin" && $r(direction) eq "in" && $r(owner_harden_inst) ne "" && ![is_harden_boundary_input_record $rec]} {
        set ok 1
    }
    array unset r
    return $ok
}

proc stage2_delay::format_record_collection {rec} {
    array set r $rec
    set name [brace_name $r(full_name)]
    if {$r(object_class) eq "pin"} {
        set out "\[get_pins $name\]"
    } elseif {$r(object_class) eq "port"} {
        set out "\[get_ports $name\]"
    } elseif {$r(object_class) eq "cell"} {
        set out "\[get_cells $name\]"
    } elseif {$r(object_class) eq "net"} {
        set out "\[get_nets $name\]"
    } else {
        set out $name
    }
    array unset r
    return $out
}

proc stage2_delay::brace_name {name} {
    if {[regexp {[\[\]\s]} $name]} {
        return "{$name}"
    }
    return "{$name}"
}

proc stage2_delay::format_delay {value} {
    set formatted [format %.12g $value]
    return $formatted
}

proc stage2_delay::truthy {value} {
    return [expr {[string tolower $value] in {1 true yes y on}}]
}

proc stage2_delay::consume_segment {seg} {
    variable consumed_constraints
    variable consumed_segments
    array set s $seg
    set key "$s(source_file)|$s(id)"
    if {![info exists consumed_constraints($key)]} {
        set consumed_constraints($key) $s(original_text)
        lappend consumed_segments [array get s]
    }
    array unset s
}

proc stage2_delay::add_review {top_seg harden_seg reason action} {
    variable review_items
    set item [list reason $reason required_action $action]
    if {$top_seg ne ""} {
        array set t $top_seg
        lappend item top_id $t(id) top_file $t(source_file) top_line $t(line_no)
        array unset t
    }
    if {$harden_seg ne ""} {
        array set h $harden_seg
        lappend item harden_id $h(id) harden_file $h(source_file) harden_line $h(line_no)
        array unset h
    }
    lappend review_items $item
}

proc stage2_delay::add_report_item {text} {
    variable report_items
    lappend report_items $text
}

proc stage2_delay::write_e2e_sdc {path} {
    variable VERSION
    variable TOOL_NAME
    variable generated_cmds
    variable residual_cmds
    set fout [open $path w]
    puts $fout "################################################################################"
    puts $fout "# Auto-generated integration E2E delay SDC"
    puts $fout "#"
    write_author_banner $fout "# "
    puts $fout "#"
    puts $fout "# Generated by             : $TOOL_NAME"
    puts $fout "# E2E_DELAY_MERGE_VERSION  : $VERSION"
    puts $fout "# Scope                    : [current_scope_name]"
    puts $fout "#"
    puts $fout "# This file is generated for the current integration top scope."
    puts $fout "# If this integration top is later consumed as a harden by an upper-level SoC,"
    puts $fout "# this file shall be reprocessed by Stage 1 hierarchy mapper."
    puts $fout "################################################################################"
    puts $fout ""
    foreach item $generated_cmds {
        array set g $item
        puts $fout "# MERGED top=$g(top_id) harden=$g(harden_id) boundary=$g(boundary)"
        puts $fout $g(command)
        puts $fout ""
        array unset g
    }
    foreach item $residual_cmds {
        array set r $item
        puts $fout "# RESIDUAL_CONSERVATIVE harden=$r(harden_id) boundary=$r(boundary) reason=$r(reason)"
        puts $fout $r(command)
        puts $fout ""
        array unset r
    }
    if {[llength $generated_cmds] == 0 && [llength $residual_cmds] == 0} {
        puts $fout "# No E2E delay constraints generated."
    }
    close $fout
}

proc stage2_delay::current_scope_name {} {
    if {[info commands current_design] ne ""} {
        if {![catch {current_design} design]} {
            return $design
        }
    }
    return "<current_integration_top>"
}

proc stage2_delay::write_removed_sdc {path} {
    variable consumed_segments
    set fout [open $path w]
    write_author_banner $fout "# "
    puts $fout "#"
    puts $fout "# merged_delay_removed.sdc generated by run_stage2_merge_delay.tcl"
    foreach seg $consumed_segments {
        array set s $seg
        puts $fout "# CONSUMED $s(source_file)|$s(id) original_id=$s(original_id) split=$s(split_index)/$s(split_total)"
        if {$s(split_total) == 1} {
            puts $fout $s(original_text)
        } else {
            puts $fout "# ORIGINAL: [compact_spaces $s(original_text)]"
            puts $fout [format_segment_delay_cmd [array get s]]
        }
        puts $fout ""
        array unset s
    }
    close $fout
}

proc stage2_delay::write_review_report {path} {
    variable review_items
    set fout [open $path w]
    write_author_banner $fout
    puts $fout ""
    puts $fout "# unmerged_delay_review.rpt generated by run_stage2_merge_delay.tcl"
    foreach item $review_items {
        puts $fout [join_kv $item]
    }
    close $fout
}

proc stage2_delay::write_report {path} {
    variable options
    variable top_segments
    variable harden_segments
    variable passthrough_segments
    variable generated_cmds
    variable residual_cmds
    variable review_items
    variable report_items

    set fout [open $path w]
    write_author_banner $fout
    puts $fout ""
    puts $fout "\[SUMMARY\]"
    puts $fout "Top SDC                         : $options(-top_sdc)"
    puts $fout "Harden list                     : $options(-harden_list)"
    puts $fout "Generated E2E SDC               : $options(-out_e2e_sdc)"
    puts $fout "Final flatten SDC               : $options(-out_final_sdc)"
    puts $fout "Total top merge candidates      : [llength $top_segments]"
    puts $fout "Total harden merge candidates   : [llength $harden_segments]"
    puts $fout "Merged constraints              : [llength $generated_cmds]"
    puts $fout "Passthrough constraints         : [llength $passthrough_segments]"
    puts $fout "Residual conservative constraints: [llength $residual_cmds]"
    puts $fout "Review required constraints     : [llength $review_items]"
    puts $fout "Merge mode                      : $options(-merge_mode)"
    puts $fout "Top open_from mode              : $options(-top_open_from_mode)"
    puts $fout "Partial merge policy            : $options(-partial_merge_policy)"
    puts $fout "Current PT design               : [current_scope_name]"
    puts $fout ""
    puts $fout "\[DETAIL\]"
    foreach line $report_items {
        puts $fout $line
    }
    puts $fout ""
    puts $fout "\[PASSTHROUGH\]"
    foreach seg $passthrough_segments {
        puts $fout [passthrough_report_line $seg]
    }
    puts $fout ""
    puts $fout "\[REVIEW\]"
    foreach item $review_items {
        puts $fout [join_kv $item]
    }
    close $fout
}

proc stage2_delay::passthrough_report_line {seg} {
    array set s $seg
    set reason ""
    if {[info exists s(passthrough_reason)]} {
        set reason $s(passthrough_reason)
    }
    set line [list \
        source $s(source) \
        id $s(id) \
        file $s(source_file) \
        line $s(line_no) \
        reason $reason \
        from [records_debug_list $s(from_records)] \
        to [records_debug_list $s(to_records)] \
    ]
    array unset s
    return [join_kv $line]
}

proc stage2_delay::records_debug_list {records} {
    set items {}
    foreach rec $records {
        lappend items [record_debug $rec]
    }
    return [join $items ";"]
}

proc stage2_delay::write_final_sdc {path} {
    variable options
    variable hardens
    variable generated_cmds
    variable residual_cmds
    variable review_items

    set fout [open $path w]
    write_author_banner $fout "# "
    puts $fout "#"
    puts $fout "# [file tail $path] generated by run_stage2_merge_delay.tcl"
    puts $fout "#"
    puts $fout "# This file is a flattened Stage 2 final SDC for the current integration scope."
    puts $fout "# It contains:"
    puts $fout "#   1. top SDC content after removing consumed delay constraints"
    puts $fout "#   2. Stage 2 generated E2E delay constraints"
    puts $fout "#   3. each harden clean SDC after removing consumed delay constraints"
    puts $fout "#"
    puts $fout "# Do not source merged_delay_removed.sdc. It is only an audit file."
    puts $fout ""

    write_final_section_header $fout "TOP_REMAINING_SDC" $options(-top_sdc)
    puts $fout [remaining_sdc_text $options(-top_sdc)]
    puts $fout ""

    write_final_section_header $fout "GENERATED_E2E_DELAY_SDC" $options(-out_e2e_sdc)
    foreach item $generated_cmds {
        array set g $item
        puts $fout "# MERGED top=$g(top_id) harden=$g(harden_id) boundary=$g(boundary)"
        puts $fout $g(command)
        puts $fout ""
        array unset g
    }
    foreach item $residual_cmds {
        array set r $item
        puts $fout "# RESIDUAL_CONSERVATIVE harden=$r(harden_id) boundary=$r(boundary) reason=$r(reason)"
        puts $fout $r(command)
        puts $fout ""
        array unset r
    }
    if {[llength $generated_cmds] == 0 && [llength $residual_cmds] == 0} {
        puts $fout "# No E2E delay constraints generated."
    }
    puts $fout ""

    foreach harden $hardens {
        array set h $harden
        if {[info exists h(clean_sdc)] && $h(clean_sdc) ne ""} {
            write_final_section_header $fout "HARDEN_REMAINING_SDC inst=$h(inst_path)" $h(clean_sdc)
            puts $fout [remaining_sdc_text $h(clean_sdc)]
            puts $fout ""
        }
        array unset h
    }

    if {[llength $review_items] > 0} {
        write_final_section_header $fout "STAGE2_REVIEW_REQUIRED" $options(-out_review_rpt)
        puts $fout "# Review report: $options(-out_review_rpt)"
        puts $fout "# The following constraints were not automatically merged:"
        foreach item $review_items {
            puts $fout "# [join_kv $item]"
        }
    }
    close $fout
}

proc stage2_delay::write_final_section_header {file_handle title source} {
    puts $file_handle "################################################################################"
    puts $file_handle "# $title"
    puts $file_handle "# Source: $source"
    puts $file_handle "################################################################################"
}

proc stage2_delay::remaining_sdc_text {path} {
    variable consumed_segments

    set fin [open $path r]
    set text [read $fin]
    close $fin

    set commands [scan_tcl_commands $text]
    set remaining $text
    foreach item [lsort -decreasing -integer -command stage2_delay::command_start_compare [commands_with_offsets $text $commands]] {
        array set cmd $item
        set consumed_for_cmd [consumed_segments_for_command $path $cmd(text)]
        if {[llength $consumed_for_cmd] > 0} {
            set before [string range $remaining 0 [expr {$cmd(start) - 1}]]
            set after [string range $remaining $cmd(end) end]
            set replacement [remaining_replacement_for_command $path $cmd(text) $consumed_for_cmd]
            set remaining "${before}${replacement}${after}"
        }
        array unset cmd
    }
    return [string trimright $remaining]
}

proc stage2_delay::consumed_segments_for_command {path original_text} {
    variable consumed_segments
    set out {}
    set norm_path [file normalize $path]
    foreach seg $consumed_segments {
        array set s $seg
        if {[file normalize $s(source_file)] eq $norm_path && $s(original_text) eq $original_text} {
            lappend out [array get s]
        }
        array unset s
    }
    return $out
}

proc stage2_delay::remaining_replacement_for_command {path original_text consumed_for_cmd} {
    array set first [lindex $consumed_for_cmd 0]
    set words [tokenize_words $original_text]
    set base [segment_from_words $words $first(source) $path $first(line_no) $first(original_id) $original_text $first(harden_inst)]
    set expanded [expand_segment $base]

    set consumed_sigs {}
    foreach seg $consumed_for_cmd {
        lappend consumed_sigs [segment_signature $seg]
    }

    set leftovers {}
    foreach seg $expanded {
        set sig [segment_signature $seg]
        set idx [lsearch -exact $consumed_sigs $sig]
        if {$idx >= 0} {
            set consumed_sigs [lreplace $consumed_sigs $idx $idx]
        } else {
            lappend leftovers $seg
        }
    }

    if {[llength $leftovers] == 0} {
        set replacement "# STAGE2_CONSUMED $first(original_id): original delay moved to merged_delay_removed.sdc\n"
        array unset first
        return $replacement
    }

    set lines {}
    lappend lines "# STAGE2_REWRITTEN $first(original_id): original multi-object delay kept only for unmerged pairs"
    lappend lines "# STAGE2_ORIGINAL: [compact_spaces $original_text]"
    foreach seg $leftovers {
        lappend lines [format_segment_delay_cmd $seg]
    }
    set replacement [join $lines "\n"]
    array unset first
    return "$replacement\n"
}

proc stage2_delay::segment_signature {seg} {
    array set s $seg
    set signature [list \
        type $s(type) \
        delay [format_delay $s(delay)] \
        from [records_signature $s(from_records)] \
        through [records_signature $s(through_records)] \
        to [records_signature $s(to_records)] \
    ]
    array unset s
    return $signature
}

proc stage2_delay::records_signature {records} {
    set out {}
    foreach rec $records {
        array set r $rec
        lappend out "$r(object_class):$r(full_name)"
        array unset r
    }
    return [join $out "|"]
}

proc stage2_delay::format_segment_delay_cmd {seg} {
    array set s $seg
    set cmd_name [expr {$s(type) eq "max" ? "set_max_delay" : "set_min_delay"}]
    set cmd "$cmd_name [format_delay $s(delay)]"
    if {[llength $s(from_records)] > 0} {
        append cmd " -from [format_record_list_for_option $s(from_records)]"
    }
    foreach rec $s(through_records) {
        append cmd " -through [format_record_collection $rec]"
    }
    if {[llength $s(to_records)] > 0} {
        append cmd " -to [format_record_list_for_option $s(to_records)]"
    }
    foreach flag $s(flags) {
        append cmd " $flag"
    }
    array unset s
    return $cmd
}

proc stage2_delay::format_record_list_for_option {records} {
    if {[llength $records] == 1} {
        return [format_record_collection [lindex $records 0]]
    }
    set parts {}
    foreach rec $records {
        lappend parts [format_record_collection $rec]
    }
    return "\[list [join $parts " "]\]"
}

proc stage2_delay::commands_with_offsets {text commands} {
    set out {}
    set search_start 0
    set line_offsets [line_start_offsets $text]
    foreach item $commands {
        array set cmd $item
        set target $cmd(text)
        set start [string first $target $text $search_start]
        set end -1
        if {$start < 0} {
            if {[info exists cmd(line)] && [info exists cmd(end_line)]} {
                set start [offset_for_line $line_offsets $cmd(line)]
                set end [offset_after_line $text $line_offsets $cmd(end_line)]
            }
        }
        if {$start >= 0} {
            if {$end < 0} {
                set end [expr {$start + [string length $target]}]
                if {$end < [string length $text] && [string index $text $end] eq "\n"} {
                    incr end
                }
            }
            lappend out [list id $cmd(id) text $target start $start end $end]
            set search_start $end
        }
        array unset cmd
    }
    return $out
}

proc stage2_delay::line_start_offsets {text} {
    set offsets {0}
    set len [string length $text]
    for {set idx 0} {$idx < $len} {incr idx} {
        if {[string index $text $idx] eq "\n"} {
            lappend offsets [expr {$idx + 1}]
        }
    }
    return $offsets
}

proc stage2_delay::offset_for_line {offsets line_no} {
    set idx [expr {$line_no - 1}]
    if {$idx < 0} {
        return 0
    }
    if {$idx < [llength $offsets]} {
        return [lindex $offsets $idx]
    }
    return [lindex $offsets end]
}

proc stage2_delay::offset_after_line {text offsets line_no} {
    if {$line_no < [llength $offsets]} {
        return [lindex $offsets $line_no]
    }
    return [string length $text]
}

proc stage2_delay::command_start_compare {a b} {
    array set aa $a
    array set bb $b
    set result [expr {$aa(start) < $bb(start) ? -1 : ($aa(start) > $bb(start) ? 1 : 0)}]
    array unset aa
    array unset bb
    return $result
}

proc stage2_delay::compact_spaces {text} {
    regsub -all {\s+} $text { } out
    return [string trim $out]
}

proc stage2_delay::join_kv {pairs} {
    set out {}
    foreach {k v} $pairs {
        lappend out "$k=$v"
    }
    return [join $out " "]
}

proc stage2_delay::read_harden_delay_candidates {path harden_inst} {
    set rows [read_csv_dicts $path]
    foreach row $rows {
        array set r $row
        set type [string tolower [dict_get_default r type [dict_get_default r delay_type ""]]]
        if {$type ni {max min}} {
            array unset r
            continue
        }
        set delay [dict_get_default r delay [dict_get_default r value ""]]
        set from [dict_get_default r from [dict_get_default r from_expr ""]]
        set to [dict_get_default r to [dict_get_default r to_expr ""]]
        set cmd [expr {$type eq "max" ? "set_max_delay" : "set_min_delay"}]
        if {$from ne ""} {
            append cmd " $delay -from $from"
        } else {
            append cmd " $delay"
        }
        append cmd " -to $to"
        set words [tokenize_words $cmd]
        set seg [segment_from_words $words harden $path [dict_get_default r line_no ""] [dict_get_default r command_id "CSV"] $cmd $harden_inst]
        if {[string tolower [dict_get_default r input_delay_overlap ""]] in {yes true 1}} {
            array set s $seg
            set s(status) review
            set s(failure_reason) BUDGET_SEMANTICS_UNRESOLVED
            set seg [array get s]
            array unset s
        }
        foreach expanded [expand_segment $seg] {
            add_segment $expanded
        }
        array unset r
    }
}

proc stage2_delay::post_check {args} {
    set e2e_sdc ""
    if {[llength $args] >= 2 && [lindex $args 0] eq "-e2e_sdc"} {
        set e2e_sdc [lindex $args 1]
    }
    if {$e2e_sdc ne ""} {
        source $e2e_sdc
    }
    if {[info commands check_timing] ne ""} {
        check_timing
    }
    if {[info commands report_exceptions] ne ""} {
        report_exceptions
    }
    if {[info commands report_analysis_coverage] ne ""} {
        report_analysis_coverage
    }
    if {[info commands report_unconstrained_paths] ne ""} {
        report_unconstrained_paths
    }
}

proc stage2_delay::global_setting {name default} {
    upvar #0 $name value
    if {[info exists value] && $value ne ""} {
        return $value
    }
    return $default
}

proc stage2_delay::set_global_setting {name value} {
    upvar #0 $name target
    set target $value
}

proc stage2_delay::run_from_user_settings {} {
    set run_dir [file normalize [global_setting RUN_DIR [pwd]]]
    set top_sdc [file normalize [global_setting TOP_SDC [file join $run_dir top_dc.sdc]]]
    set harden_list [file normalize [global_setting HARDEN_LIST [file join $run_dir harden_list.csv]]]
    set out_dir [file normalize [global_setting OUT_DIR $run_dir]]

    set top_module [global_setting TOP_MODULE_NAME ""]
    if {$top_module eq ""} {
        if {![catch {current_design} current_top] && $current_top ne ""} {
            set top_module $current_top
        } else {
            set top_module current_integration_top
        }
    }
    set top_module [safe_filename_token $top_module]

    set out_e2e_sdc [file normalize [global_setting OUT_E2E_SDC [file join $out_dir generated_e2e_delay.sdc]]]
    set out_report [file normalize [global_setting OUT_REPORT [file join $out_dir integration_delay_merge.rpt]]]
    set out_removed_sdc [file normalize [global_setting OUT_REMOVED_SDC [file join $out_dir merged_delay_removed.sdc]]]
    set out_review_rpt [file normalize [global_setting OUT_REVIEW_RPT [file join $out_dir unmerged_delay_review.rpt]]]
    set out_final_sdc [file normalize [global_setting OUT_FINAL_SDC [file join $out_dir ${top_module}_flatten.sdc]]]

    set merge_mode [global_setting MERGE_MODE replace]
    set partial_merge_policy [global_setting PARTIAL_MERGE_POLICY residual_through]
    set unmatched_harden_policy [global_setting UNMATCHED_HARDEN_POLICY review]
    set allow_through [global_setting ALLOW_THROUGH true]
    set max_endpoints [global_setting MAX_ENDPOINTS 1000]
    set max_enum_objects [global_setting MAX_ENUM_OBJECTS 64]

    foreach required_file [list $top_sdc $harden_list] {
        if {![file exists $required_file]} {
            error "Required file not found: $required_file"
        }
    }
    if {![file isdirectory $out_dir]} {
        file mkdir $out_dir
    }

    set_global_setting RUN_DIR $run_dir
    set_global_setting TOP_SDC $top_sdc
    set_global_setting HARDEN_LIST $harden_list
    set_global_setting OUT_DIR $out_dir
    set_global_setting OUT_E2E_SDC $out_e2e_sdc
    set_global_setting OUT_REPORT $out_report
    set_global_setting OUT_REMOVED_SDC $out_removed_sdc
    set_global_setting OUT_REVIEW_RPT $out_review_rpt
    set_global_setting OUT_FINAL_SDC $out_final_sdc
    set_global_setting TOP_MODULE_NAME $top_module

    puts "INFO: Stage 2 script      : [global_setting STAGE2_SCRIPT_FILE run_stage2_merge_delay.tcl]"
    puts "INFO: Run directory       : $run_dir"
    puts "INFO: Top SDC             : $top_sdc"
    puts "INFO: Harden list         : $harden_list"
    puts "INFO: Output E2E SDC      : $out_e2e_sdc"
    puts "INFO: Final flatten SDC   : $out_final_sdc"
    puts "INFO: Merge mode          : $merge_mode"

    stage2_delay::build \
        -top_sdc $top_sdc \
        -harden_list $harden_list \
        -out_e2e_sdc $out_e2e_sdc \
        -out_report $out_report \
        -out_removed_sdc $out_removed_sdc \
        -out_review_rpt $out_review_rpt \
        -out_final_sdc $out_final_sdc \
        -merge_mode $merge_mode \
        -partial_merge_policy $partial_merge_policy \
        -unmatched_harden_policy $unmatched_harden_policy \
        -allow_through $allow_through \
        -max_endpoints $max_endpoints \
        -max_enum_objects $max_enum_objects

    puts "INFO: Stage 2 complete."
    puts "INFO: Generated E2E SDC   : $out_e2e_sdc"
    puts "INFO: Merge report        : $out_report"
    puts "INFO: Removed constraints : $out_removed_sdc"
    puts "INFO: Review report       : $out_review_rpt"
    puts "INFO: Final flatten SDC   : $out_final_sdc"

    if {[truthy [global_setting STAGE2_POST_CHECK false]]} {
        post_check -e2e_sdc $out_e2e_sdc
    }
}

if {[info exists ::STAGE2_AUTO_RUN] && [stage2_delay::truthy $::STAGE2_AUTO_RUN]} {
    stage2_delay::run_from_user_settings
}
