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

# Optional final flattened SDC name. Leave empty to derive from TOP_SDC basename:
#   <TOP_SDC_basename>_flatten.sdc
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

# For top open_from delay, infer static startpoints from PT all_fanin before
# generating E2E constraints. Set to "through" only for old conservative debug
# behavior.
set ::TOP_OPEN_FROM_MODE enumerate_static_startpoints

# Legacy compatibility knob. Normal Stage 2 output always requires explicit
# -from inferred from the linked PT database; -through may still be emitted as
# path breadcrumbs after -from.
set ::ALLOW_THROUGH false

# Map top-side get_ports endpoints to connected harden boundary pins in the
# linked PrimeTime database.
#   connectivity : use direct net connectivity; recommended for raw DC SDC.
#   off          : keep top get_ports endpoints as passthrough.
set ::TOP_PORT_BOUNDARY_MAP_MODE connectivity

# Automatically chain delay segments through harden output -> harden input
# hops. This is needed for:
#   harden_a/internal_start -> harden_a/output -> harden_b/input -> harden_b/internal_endpoint
set ::RECURSIVE_CHAIN_MODE auto
set ::MAX_CHAIN_DEPTH 6

# Safety limits.
set ::MAX_ENDPOINTS 1000
set ::MAX_ENUM_OBJECTS 64

# Optional output file overrides. Leave empty to use OUT_DIR defaults.
set ::OUT_E2E_SDC ""
set ::OUT_REPORT ""
set ::OUT_REMOVED_SDC ""
set ::OUT_REVIEW_RPT ""
set ::OUT_SUMMARY_DIR ""

# Optional post-check after build. Keep disabled until generated SDC is reviewed.
set ::STAGE2_POST_CHECK false

# Print PrimeTime query actions to terminal. Useful when debugging whether PT
# database objects and connectivity are visible to Stage 2.
set ::STAGE2_VERBOSE_PT_QUERY true

# Write review-friendly CSV sheets under OUT_SUMMARY_DIR.
set ::WRITE_PATH_SUMMARY true

# Text file encoding used by Stage 2 generated reports/SDC/CSV and source SDC
# reads. Keep utf-8 for normal Linux/PT flow. If legacy SDC comments were saved
# in GBK/GB2312 and look garbled, override this before source.
set ::STAGE2_TEXT_ENCODING utf-8

set ::STAGE2_SCRIPT_FILE [file normalize [info script]]

namespace eval stage2_delay {
    variable VERSION "v0.8.7"
    variable TOOL_NAME "run_stage2_merge_delay.tcl"
    variable STAGE_NAME "STA Flatten 2 Set Delay Merge PrimeTime"
    variable AUTHOR "Howard"

    variable options
    variable hardens
    variable top_segments
    variable chain_top_segments
    variable harden_segments
    variable harden_output_segments
    variable all_delay_segments
    variable passthrough_segments
    variable generated_cmds
    variable residual_cmds
    variable path_summary_items
    variable consumed_constraints
    variable consumed_segments
    variable review_items
    variable report_items
    variable command_seq
    variable e2e_seq
    variable boundary_input_cache
    variable top_port_boundary_cache

    array set options {
        -top_sdc ""
        -harden_list ""
        -out_e2e_sdc "generated_e2e_delay.sdc"
        -out_final_sdc ""
        -out_report "integration_delay_merge.rpt"
        -out_removed_sdc "merged_delay_removed.sdc"
        -out_review_rpt "unmerged_delay_review.rpt"
        -out_summary_dir ""
        -merge_mode "replace"
        -top_open_from_mode "enumerate_static_startpoints"
        -allow_through "false"
        -allow_collapse_single_boundary "false"
        -partial_merge_policy "residual_through"
        -unmatched_harden_policy "review"
        -top_port_boundary_map_mode "connectivity"
        -recursive_chain_mode "auto"
        -max_chain_depth 6
        -max_endpoints 1000
        -max_enum_objects 64
        -check_units "true"
        -expect_units ""
        -strict "false"
        -debug "false"
        -verbose_pt_query "true"
        -write_path_summary "true"
        -text_encoding "utf-8"
    }
}

proc stage2_delay::reset_state {} {
    variable hardens
    variable top_segments
    variable chain_top_segments
    variable harden_segments
    variable harden_output_segments
    variable all_delay_segments
    variable passthrough_segments
    variable generated_cmds
    variable residual_cmds
    variable path_summary_items
    variable consumed_constraints
    variable consumed_segments
    variable review_items
    variable report_items
    variable command_seq
    variable e2e_seq
    variable boundary_input_cache
    variable top_port_boundary_cache

    set hardens {}
    set top_segments {}
    set chain_top_segments {}
    set harden_segments {}
    set harden_output_segments {}
    set all_delay_segments {}
    set passthrough_segments {}
    set generated_cmds {}
    set residual_cmds {}
    set path_summary_items {}
    array unset consumed_constraints
    array set consumed_constraints {}
    set consumed_segments {}
    set review_items {}
    set report_items {}
    set command_seq 0
    set e2e_seq 0
    array unset boundary_input_cache
    array set boundary_input_cache {}
    array unset top_port_boundary_cache
    array set top_port_boundary_cache {}
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

    map_top_port_boundary_segments
    classify_segments
    if {$options(-recursive_chain_mode) eq "auto"} {
        match_delay_graph_segments
    } else {
        match_top_to_harden_segments
    }
    write_e2e_sdc $options(-out_e2e_sdc)
    write_removed_sdc $options(-out_removed_sdc)
    write_review_report $options(-out_review_rpt)
    write_report $options(-out_report)
    write_final_sdc $options(-out_final_sdc)
    if {[truthy $options(-write_path_summary)]} {
        write_path_summary $options(-out_summary_dir)
    }
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
    if {$options(-top_port_boundary_map_mode) ni {off connectivity}} {
        error "-top_port_boundary_map_mode must be off or connectivity"
    }
    if {$options(-recursive_chain_mode) ni {off auto}} {
        error "-recursive_chain_mode must be off or auto"
    }
}

proc stage2_delay::apply_derived_options {} {
    variable options
    if {$options(-out_final_sdc) eq ""} {
        set out_dir [file dirname [file normalize $options(-out_e2e_sdc)]]
        set top_name [top_name_from_sdc_path $options(-top_sdc)]
        set options(-out_final_sdc) [file join $out_dir "${top_name}_flatten.sdc"]
    }
    if {$options(-out_summary_dir) eq ""} {
        set out_dir [file dirname [file normalize $options(-out_report)]]
        set options(-out_summary_dir) [file join $out_dir delay_path_summary]
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

proc stage2_delay::top_name_from_sdc_path {path} {
    set base [file tail [file rootname $path]]
    return [safe_filename_token $base]
}

proc stage2_delay::open_text {path mode} {
    variable options
    set fh [open $path $mode]
    set encoding "utf-8"
    if {[info exists options(-text_encoding)] && $options(-text_encoding) ne ""} {
        set encoding $options(-text_encoding)
    }
    if {$encoding ne ""} {
        fconfigure $fh -encoding $encoding
    }
    fconfigure $fh -translation lf
    return $fh
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
    set fin [open_text $path r]
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
    set fin [open_text $path r]
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
    if {$source eq "harden" && $harden_inst ne ""} {
        set from_records [map_harden_port_records_to_instance_pins $from_records $harden_inst]
        set to_records [map_harden_port_records_to_instance_pins $to_records $harden_inst]
        set through_records [map_harden_port_records_to_instance_pins $through_records $harden_inst]
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
    variable all_delay_segments
    lappend all_delay_segments $seg
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

proc stage2_delay::map_harden_port_records_to_instance_pins {records harden_inst} {
    set out {}
    foreach rec $records {
        array set r $rec
        if {$r(object_class) eq "port"} {
            set pin_name "${harden_inst}/$r(full_name)"
            set direction [pt_get_attr_by_name pin $pin_name direction]
            lappend out [object_record pin $pin_name $direction [owner_harden_inst $pin_name]]
        } else {
            lappend out $rec
        }
        array unset r
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
        pt_trace "skip get_attribute class=$class name=$name attr=$attr command_unavailable_or_unsupported"
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
    set value ""
    pt_trace "$getter -quiet {$name}"
    if {[catch {
        set coll [$getter -quiet $name]
        set count [sizeof_collection $coll]
        pt_trace "$getter result name={$name} count=$count"
        if {$count > 0} {
            pt_trace "get_attribute {$name} $attr"
            set value [get_attribute $coll $attr]
            pt_trace "get_attribute result name={$name} attr=$attr value={$value}"
        }
    } err]} {
        pt_trace "$getter/get_attribute failed name={$name} attr=$attr error={$err}"
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

proc stage2_delay::map_top_port_boundary_segments {} {
    variable options
    variable top_segments

    if {$options(-top_port_boundary_map_mode) eq "off"} {
        return
    }

    set mapped {}
    foreach seg $top_segments {
        set mapped [concat $mapped [map_top_port_boundary_segment $seg]]
    }
    set top_segments $mapped
}

proc stage2_delay::map_top_port_boundary_segment {seg} {
    variable options
    array set s $seg
    if {$s(status) ne "ok" || [llength $s(to_records)] != 1} {
        array unset s
        return [list $seg]
    }

    array set to [lindex $s(to_records) 0]
    if {$to(object_class) ne "port" || $to(owner_harden_inst) ne ""} {
        array unset to
        array unset s
        return [list $seg]
    }

    set connected [pt_harden_pins_connected_to_port $to(full_name)]
    set input_boundaries [filter_harden_boundary_input_records $connected]
    if {[llength $input_boundaries] == 0} {
        array unset to
        array unset s
        return [list $seg]
    }

    set out {}
    set idx 0
    set total [llength $input_boundaries]
    set group_key "$s(source_file)|$s(id)|$to(full_name)"
    foreach boundary $input_boundaries {
        incr idx
        array set e [array get s]
        set e(id) "$s(id).P[format %03d $idx]"
        set e(to_records) [list $boundary]
        set e(rewrite_to_records) [list [array get to]]
        set e(top_port_map_group) $group_key
        set e(top_port_map_total) $total
        set e(mapped_from_top_port) $to(full_name)
        set e(mapped_boundary_index) $idx
        set e(mapped_boundary_name) [record_full_name $boundary]
        lappend out [array get e]
        add_report_item "TOP_PORT_BOUNDARY_MAP top_id=$e(id) mode=$options(-top_port_boundary_map_mode) port=$to(full_name) boundary=[record_full_name $boundary] total=$total"
        array unset e
    }

    array unset to
    array unset s
    return $out
}

proc stage2_delay::filter_harden_boundary_input_records {records} {
    set out {}
    foreach rec $records {
        if {[is_harden_boundary_input_record $rec]} {
            lappend out $rec
        }
    }
    return [unique_records_by_name $out]
}

proc stage2_delay::filter_harden_boundary_unknown_direction_records {records} {
    set out {}
    foreach rec $records {
        array set r $rec
        if {[is_immediate_harden_pin_record $rec] && $r(direction) eq ""} {
            lappend out $rec
        }
        array unset r
    }
    return [unique_records_by_name $out]
}

proc stage2_delay::pt_harden_pins_connected_to_port {port_name} {
    variable top_port_boundary_cache

    if {[info exists top_port_boundary_cache($port_name)]} {
        pt_trace "top port connectivity cache hit port={$port_name} pins=[llength $top_port_boundary_cache($port_name)]"
        return $top_port_boundary_cache($port_name)
    }
    set top_port_boundary_cache($port_name) {}

    foreach required {get_ports get_nets get_pins get_attribute sizeof_collection foreach_in_collection} {
        if {[info commands $required] eq ""} {
            pt_trace "top port connectivity skip port={$port_name} missing_command=$required"
            return {}
        }
    }

    set value {}
    pt_trace "get_ports -quiet {$port_name}"
    if {[catch {
        set ports [get_ports -quiet $port_name]
        set port_count [sizeof_collection $ports]
        pt_trace "get_ports result port={$port_name} count=$port_count"
        if {$port_count > 0} {
            pt_trace "get_nets -quiet -of_objects <ports:{$port_name}>"
            set nets [get_nets -quiet -of_objects $ports]
            pt_trace "get_nets result port={$port_name} count=[sizeof_collection $nets]"
            foreach_in_collection net $nets {
                set net_name [collection_object_name $net]
                pt_trace "get_pins -quiet -of_objects <net:{$net_name}>"
                set pins [get_pins -quiet -of_objects $net]
                pt_trace "get_pins result net={$net_name} count=[sizeof_collection $pins]"
                foreach_in_collection pin $pins {
                    set name [collection_object_name $pin]
                    set owner [owner_harden_inst $name]
                    if {$owner eq ""} {
                        pt_trace "connected pin ignored pin={$name} owner_not_in_harden_list"
                        continue
                    }
                    set direction ""
                    catch {set direction [get_attribute $pin direction]}
                    pt_trace "connected harden pin pin={$name} direction={$direction} owner={$owner}"
                    lappend value [object_record pin $name $direction $owner]
                }
            }
        }
    } err]} {
        pt_trace "top port connectivity failed port={$port_name} error={$err}"
        set value {}
    }

    set value [unique_records_by_name $value]
    pt_trace "top port connectivity summary port={$port_name} harden_pins=[llength $value]"
    set top_port_boundary_cache($port_name) $value
    return $value
}

proc stage2_delay::collection_object_name {obj} {
    if {[info commands get_attribute] ne ""} {
        if {![catch {set name [get_attribute $obj full_name]}] && $name ne ""} {
            return $name
        }
    }
    if {[info commands get_object_name] ne ""} {
        if {![catch {set name [get_object_name $obj]}] && $name ne ""} {
            return $name
        }
    }
    return $obj
}

proc stage2_delay::classify_segments {} {
    variable top_segments
    variable chain_top_segments
    variable harden_segments
    variable harden_output_segments
    variable passthrough_segments
    variable review_items

    set new_top {}
    set new_chain_top {}
    foreach seg $top_segments {
        array set s $seg
        set class [classify_top_segment [array get s]]
        set s(class) $class
        set updated [array get s]
        if {$class eq "merge_candidate"} {
            lappend new_top $updated
        } elseif {$class eq "chain_top_candidate"} {
            lappend new_chain_top $updated
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
    set chain_top_segments $new_chain_top

    set new_harden {}
    set new_harden_output {}
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
            if {[harden_segment_to_is_output_boundary $updated]} {
                lappend new_harden_output $updated
            }
        } elseif {$class eq "harden_output_source"} {
            lappend new_harden_output $updated
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
    set harden_output_segments $new_harden_output
}

proc stage2_delay::top_passthrough_reason {seg} {
    variable options
    array set s $seg
    set reason "TOP_PASSTHROUGH_UNKNOWN"
    if {[llength $s(to_records)] == 1} {
        array set to [lindex $s(to_records) 0]
        if {$to(owner_harden_inst) eq ""} {
            set connected {}
            if {$to(object_class) eq "port"} {
                set connected [pt_harden_pins_connected_to_port $to(full_name)]
            }
            set input_boundaries [filter_harden_boundary_input_records $connected]
            set unknown_boundaries [filter_harden_boundary_unknown_direction_records $connected]
            if {$to(object_class) eq "port" && [llength $unknown_boundaries] > 0 && [llength $input_boundaries] == 0} {
                set reason "TOP_PORT_CONNECTED_TO_HARDEN_BOUNDARY_WITH_UNKNOWN_DIRECTION map_mode=$options(-top_port_boundary_map_mode) to=[record_debug [array get to]] connected=[records_debug_list $connected]"
            } elseif {$to(object_class) eq "port" && [llength $connected] > 0 && [llength $input_boundaries] == 0} {
                set reason "TOP_PORT_CONNECTED_TO_NON_INPUT_HARDEN_BOUNDARY map_mode=$options(-top_port_boundary_map_mode) to=[record_debug [array get to]] connected=[records_debug_list $connected]"
            } elseif {$to(object_class) eq "port" && [llength $input_boundaries] > 0 && $options(-top_port_boundary_map_mode) eq "off"} {
                set reason "TOP_PORT_BOUNDARY_MAP_DISABLED to=[record_debug [array get to]] input_boundaries=[records_debug_list $input_boundaries]"
            } else {
                set reason "TOP_TO_NOT_UNDER_HARDEN_LIST to=[record_debug [array get to]] harden_insts=[harden_inst_list_for_debug]"
            }
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
        } elseif {$to(direction) eq ""} {
            set reason "HARDEN_TO_DIRECTION_UNKNOWN to=[record_debug [array get to]] expected_harden=$s(harden_inst)"
        } elseif {$s(kind) eq "complete" && [llength $s(from_records)] == 1} {
            array set from [lindex $s(from_records) 0]
            if {$from(direction) eq ""} {
                set reason "HARDEN_FROM_DIRECTION_UNKNOWN from=[record_debug [array get from]] expected_harden=$s(harden_inst)"
            } elseif {![is_harden_boundary_input_record [array get from]] || $from(owner_harden_inst) ne $s(harden_inst)} {
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
        if {[top_from_is_harden_boundary_output [array get s]] && [validate_endpoint_record [array get to]]} {
            array unset to
            array unset s
            return "chain_top_candidate"
        }
        array unset to
        array unset s
        return "passthrough"
    }
    if {$to(direction) eq ""} {
        array unset to
        array unset s
        return "TOP_TO_DIRECTION_UNKNOWN"
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
        if {[llength $s(from_records)] == 1} {
            array set from [lindex $s(from_records) 0]
            if {[is_harden_boundary_output_record [array get from]]} {
                array unset from
                array unset to
                array unset s
                return "chain_top_candidate"
            }
            array unset from
        }
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
    if {$to(direction) eq ""} {
        array unset to
        array unset s
        return "HARDEN_TO_DIRECTION_UNKNOWN"
    }
    if {$s(kind) eq "complete"} {
        if {[llength $s(from_records)] != 1} {
            array unset to
            array unset s
            return "MULTI_OBJECT_FROM"
        }
        array set from [lindex $s(from_records) 0]
        if {$from(owner_harden_inst) eq $s(harden_inst) && $from(direction) eq ""} {
            array unset from
            array unset to
            array unset s
            return "HARDEN_FROM_DIRECTION_UNKNOWN"
        }
        if {[is_harden_boundary_input_record [array get from]] && $from(owner_harden_inst) eq $s(harden_inst)} {
            array unset from
            array unset to
            array unset s
            return "merge_candidate"
        }
        if {[is_harden_boundary_output_record [array get to]] && [validate_startpoint_record [array get from]]} {
            array unset from
            array unset to
            array unset s
            return "harden_output_source"
        }
        array unset from
        array unset to
        array unset s
        return "passthrough"
    }
    if {[is_harden_boundary_output_record [array get to]]} {
        array unset to
        array unset s
        return "OUTPUT_DIRECTION_NOT_SUPPORTED"
    }
    array unset to
    array unset s
    return "merge_candidate"
}

proc stage2_delay::harden_segment_to_is_output_boundary {seg} {
    array set s $seg
    set result 0
    if {[llength $s(to_records)] == 1} {
        set result [is_harden_boundary_output_record [lindex $s(to_records) 0]]
    }
    array unset s
    return $result
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
    set result [expr {[is_immediate_harden_pin_record $rec] && $r(direction) eq "in"}]
    array unset r
    return $result
}

proc stage2_delay::is_harden_boundary_output_record {rec} {
    array set r $rec
    set result [expr {[is_immediate_harden_pin_record $rec] && $r(direction) eq "out"}]
    array unset r
    return $result
}

proc stage2_delay::is_immediate_harden_pin_record {rec} {
    array set r $rec
    set result 0
    if {$r(object_class) eq "pin" && $r(owner_harden_inst) ne "" && [string match "$r(owner_harden_inst)/*" $r(full_name)]} {
        set rest [string range $r(full_name) [expr {[string length $r(owner_harden_inst)] + 1}] end]
        set result [expr {$rest ne "" && [string first "/" $rest] < 0}]
    }
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
        pt_trace "fanin boundary inference skip harden={$harden_inst} endpoint={$endpoint} missing_command"
        return {}
    }
    set value {}
    pt_trace "get_pins -quiet {$endpoint}"
    if {[catch {
        set ep [get_pins -quiet $endpoint]
        pt_trace "get_pins endpoint result endpoint={$endpoint} count=[sizeof_collection $ep]"
        pt_trace "get_cells -quiet {$harden_inst}"
        set hcell [get_cells -quiet $harden_inst]
        pt_trace "get_cells result harden={$harden_inst} count=[sizeof_collection $hcell]"
        if {[sizeof_collection $ep] > 0 && [sizeof_collection $hcell] > 0} {
            pt_trace "all_fanin -to {$endpoint}"
            set cone [all_fanin -to $ep]
            pt_trace "all_fanin result endpoint={$endpoint} count=[sizeof_collection $cone]"
            pt_trace "get_pins -quiet -of_objects <cell:{$harden_inst}>"
            set hpins [get_pins -quiet -of_objects $hcell]
            pt_trace "get_pins harden pins result harden={$harden_inst} count=[sizeof_collection $hpins]"
            pt_trace "filter_collection <harden_pins:{$harden_inst}> {direction == in}"
            set hin [filter_collection $hpins "direction == in"]
            pt_trace "filter_collection result harden={$harden_inst} input_count=[sizeof_collection $hin]"
            set out {}
            foreach_in_collection pin $hin {
                set name [get_attribute $pin full_name]
                if {[collection_contains_name $cone $name]} {
                    pt_trace "fanin boundary matched harden={$harden_inst} endpoint={$endpoint} boundary={$name}"
                    lappend out [object_record pin $name [get_attribute $pin direction] $harden_inst]
                }
            }
            set value $out
        }
    } err]} {
        pt_trace "fanin boundary inference failed harden={$harden_inst} endpoint={$endpoint} error={$err}"
        return {}
    }
    pt_trace "fanin boundary inference summary harden={$harden_inst} endpoint={$endpoint} boundary_count=[llength $value]"
    return $value
}

proc stage2_delay::pt_boundary_inputs_by_fanout {harden_inst endpoint} {
    if {[info commands all_fanout] eq "" || [info commands get_pins] eq "" || [info commands get_cells] eq ""} {
        pt_trace "fanout boundary inference skip harden={$harden_inst} endpoint={$endpoint} missing_command"
        return {}
    }
    set value {}
    if {[catch {
        set ep_name $endpoint
        pt_trace "get_cells -quiet {$harden_inst}"
        set hcell [get_cells -quiet $harden_inst]
        pt_trace "get_cells result harden={$harden_inst} count=[sizeof_collection $hcell]"
        if {[sizeof_collection $hcell] > 0} {
            pt_trace "get_pins -quiet -of_objects <cell:{$harden_inst}>"
            set hpins [get_pins -quiet -of_objects $hcell]
            pt_trace "get_pins harden pins result harden={$harden_inst} count=[sizeof_collection $hpins]"
            pt_trace "filter_collection <harden_pins:{$harden_inst}> {direction == in}"
            set hin [filter_collection $hpins "direction == in"]
            pt_trace "filter_collection result harden={$harden_inst} input_count=[sizeof_collection $hin]"
            set out {}
            foreach_in_collection pin $hin {
                set name [get_attribute $pin full_name]
                pt_trace "all_fanout -flat -from {$name}"
                set fanout [all_fanout -flat -from $pin]
                pt_trace "all_fanout result from={$name} count=[sizeof_collection $fanout]"
                if {[collection_contains_name $fanout $ep_name]} {
                    pt_trace "fanout boundary matched harden={$harden_inst} endpoint={$endpoint} boundary={$name}"
                    lappend out [object_record pin $name [get_attribute $pin direction] $harden_inst]
                }
            }
            set value $out
        }
    } err]} {
        pt_trace "fanout boundary inference failed harden={$harden_inst} endpoint={$endpoint} error={$err}"
        return {}
    }
    pt_trace "fanout boundary inference summary harden={$harden_inst} endpoint={$endpoint} boundary_count=[llength $value]"
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

proc stage2_delay::segment_summary_step {seg} {
    array set s $seg
    set source_inst "-"
    set sheet "top"
    if {$s(source) eq "harden"} {
        set source_inst $s(harden_inst)
        set sheet $s(harden_inst)
    }
    set delay [format_delay_maybe $s(delay)]
    if {[info exists s(missing_sdc)] && [truthy $s(missing_sdc)]} {
        set delay "-"
    }
    set step [list \
        sheet $sheet \
        source $s(source) \
        source_inst $source_inst \
        source_file $s(source_file) \
        line_no $s(line_no) \
        cmd_id $s(id) \
        original_id $s(original_id) \
        type $s(type) \
        delay $delay \
        from [records_summary_text $s(from_records)] \
        through [records_summary_text $s(through_records)] \
        to [records_summary_text $s(to_records)] \
        from_records $s(from_records) \
        through_records $s(through_records) \
        to_records $s(to_records) \
    ]
    array unset s
    return $step
}

proc stage2_delay::format_delay_maybe {value} {
    if {$value eq ""} {
        return "-"
    }
    if {[string is double -strict $value]} {
        return [format_delay $value]
    }
    return $value
}

proc stage2_delay::records_summary_text {records} {
    if {[llength $records] == 0} {
        return "-"
    }
    set parts {}
    foreach rec $records {
        lappend parts [format_record_collection $rec]
    }
    return [join $parts " ; "]
}

proc stage2_delay::records_summary_name_text {records} {
    if {[llength $records] == 0} {
        return "-"
    }
    set parts {}
    foreach rec $records {
        lappend parts [record_summary_name $rec]
    }
    return [join $parts " ; "]
}

proc stage2_delay::record_summary_name {rec} {
    array set r $rec
    set name $r(full_name)
    array unset r
    return $name
}

proc stage2_delay::next_e2e_id {} {
    variable e2e_seq
    incr e2e_seq
    return [format "E2E%06d" $e2e_seq]
}

proc stage2_delay::record_generated_path_summary {e2e_id path_id path_steps final_delay final_from_records through_records final_to_record generated_cmd} {
    append_path_summary_items "MERGED" $e2e_id $path_id $path_steps $final_delay $final_from_records $through_records $final_to_record $generated_cmd "-"
}

proc stage2_delay::record_residual_path_summary {e2e_id hseg boundary reason generated_cmd {final_from_records {}}} {
    array set h $hseg
    set to_rec [lindex $h(to_records) 0]
    set path_steps [list [segment_summary_step [array get h]]]
    set path_id "RESIDUAL:[summary_steps_path_id $path_steps]"
    append_path_summary_items "RESIDUAL" $e2e_id $path_id $path_steps $h(delay) $final_from_records [list $boundary] $to_rec $generated_cmd $reason
    array unset h
}

proc stage2_delay::record_review_path_summary {top_seg harden_seg reason action} {
    set path_steps {}
    if {$top_seg ne ""} {
        lappend path_steps [review_segment_summary_step $top_seg]
    }
    if {$harden_seg ne ""} {
        lappend path_steps [review_segment_summary_step $harden_seg]
    }
    if {[llength $path_steps] == 0} {
        return
    }
    set path_id "REVIEW:[summary_steps_path_id $path_steps]"
    append_path_summary_items "REVIEW" "-" $path_id $path_steps "-" {} {} "" "-" "$reason | $action"
}

proc stage2_delay::review_segment_summary_step {seg} {
    array set s $seg
    if {$s(source) eq "top" && [llength $s(from_records)] == 0 && [llength $s(to_records)] == 1} {
        set inferred [pt_startpoints_to_boundary [lindex $s(to_records) 0]]
        if {[llength $inferred] > 0} {
            set s(from_records) $inferred
            add_report_item "REVIEW_TOP_OPEN_FROM_STARTPOINT_INFERRED top_id=$s(id) to=[records_summary_name_text $s(to_records)] count=[llength $inferred]"
        } else {
            add_report_item "REVIEW_TOP_OPEN_FROM_STARTPOINT_NOT_FOUND top_id=$s(id) to=[records_summary_name_text $s(to_records)]"
        }
    }
    set step [segment_summary_step [array get s]]
    array unset s
    return $step
}

proc stage2_delay::append_path_summary_items {merge_status e2e_id path_id path_steps final_delay final_from_records through_records final_to_record generated_cmd review_reason} {
    variable path_summary_items
    set through_records [unique_records_by_name $through_records]
    set final_from [records_summary_name_text $final_from_records]
    if {$final_to_record eq ""} {
        set final_to "-"
    } else {
        set final_to [record_summary_name $final_to_record]
    }
    set through_texts {}
    foreach rec $through_records {
        lappend through_texts [record_summary_name $rec]
    }
    set stage_delays {}
    set stage_from_texts {}
    set stage_to_texts {}
    set start_sdc_delay "-"
    set start_from "-"
    set start_to "-"
    set end_sdc_delay "-"
    set end_from "-"
    set end_to "-"
    if {[llength $path_steps] > 0} {
        array set first_step [lindex $path_steps 0]
        set start_sdc_delay $first_step(delay)
        set start_from [records_summary_name_text $first_step(from_records)]
        set start_to [records_summary_name_text $first_step(to_records)]
        array unset first_step

        array set last_step [lindex $path_steps end]
        set end_sdc_delay $last_step(delay)
        set end_from [records_summary_name_text $last_step(from_records)]
        set end_to [records_summary_name_text $last_step(to_records)]
        array unset last_step
    }
    if {$start_from eq "-" && $final_from ne "-"} {
        set start_from $final_from
    }
    foreach step $path_steps {
        array set st $step
        lappend stage_delays $st(delay)
        lappend stage_from_texts [records_summary_name_text $st(from_records)]
        lappend stage_to_texts [records_summary_name_text $st(to_records)]
        array unset st
    }
    foreach step $path_steps {
        array set st $step
        lappend path_summary_items [list \
            e2e_id $e2e_id \
            sheet $st(sheet) \
            merge_status $merge_status \
            path_id $path_id \
            source $st(source) \
            source_inst $st(source_inst) \
            source_file $st(source_file) \
            line_no $st(line_no) \
            cmd_id $st(cmd_id) \
            original_id $st(original_id) \
            delay_type $st(type) \
            native_delay $st(delay) \
            native_from $st(from) \
            native_through $st(through) \
            native_to $st(to) \
            final_delay [format_delay_maybe $final_delay] \
            final_from $final_from \
            start_sdc_delay $start_sdc_delay \
            start_from $start_from \
            start_to $start_to \
            stage_delays $stage_delays \
            stage_from_texts $stage_from_texts \
            stage_to_texts $stage_to_texts \
            through_records $through_texts \
            final_to $final_to \
            end_sdc_delay $end_sdc_delay \
            end_from $end_from \
            end_to $end_to \
            generated_cmd $generated_cmd \
            review_reason $review_reason \
            path_steps $path_steps \
        ]
        array unset st
    }
}

proc stage2_delay::summary_steps_path_id {path_steps} {
    set ids {}
    foreach step $path_steps {
        array set st $step
        lappend ids $st(cmd_id)
        array unset st
    }
    if {[llength $ids] == 0} {
        return "PATH"
    }
    return [join $ids "+"]
}

proc stage2_delay::summary_through_records_from_steps {path_steps final_to_record explicit_through_records} {
    set out $explicit_through_records
    set final_name ""
    if {$final_to_record ne ""} {
        set final_name [record_full_name $final_to_record]
    }
    foreach step $path_steps {
        array set st $step
        foreach rec $st(through_records) {
            lappend out $rec
        }
        foreach rec $st(to_records) {
            if {$final_name eq "" || [record_full_name $rec] ne $final_name} {
                lappend out $rec
            }
        }
        array unset st
    }
    return [unique_records_by_name $out]
}

proc stage2_delay::match_delay_graph_segments {} {
    variable options
    variable top_segments
    variable chain_top_segments
    variable harden_segments
    variable harden_output_segments

    array set used_top {}
    array set used_harden {}
    array set emitted {}
    set queue {}

    foreach tseg $top_segments {
        array set t $tseg
        if {[llength $t(to_records)] == 1} {
            foreach path [paths_from_top_segment [array get t]] {
                lappend queue $path
            }
        }
        array unset t
    }

    foreach hseg $harden_output_segments {
        array set h $hseg
        if {[harden_output_source_has_legal_start [array get h]]} {
            lappend queue [path_from_harden_output_source [array get h]]
        } else {
            foreach path [paths_from_missing_top_to_harden_feedthrough [array get h]] {
                lappend queue $path
            }
        }
        array unset h
    }

    foreach tseg $chain_top_segments {
        array set t $tseg
        if {[llength $t(from_records)] == 1} {
            set from_rec [lindex $t(from_records) 0]
            if {[is_harden_boundary_output_record $from_rec] && ![harden_output_source_exists_for_boundary $from_rec $t(type)]} {
                foreach path [paths_from_missing_harden_output_boundary $from_rec $t(type)] {
                    lappend queue $path
                }
            }
        }
        array unset t
    }

    set idx 0
    array set visited {}
    while {$idx < [llength $queue]} {
        set path [lindex $queue $idx]
        incr idx
        array set p $path
        if {$p(depth) > $options(-max_chain_depth)} {
            array unset p
            continue
        }
        set psig [path_signature [array get p]]
        if {[info exists visited($psig)]} {
            array unset p
            continue
        }
        set visited($psig) 1

        set end_rec $p(end_record)
        if {[validate_endpoint_record $end_rec]} {
            set emitted_sig "TERMINAL:[path_signature [array get p]]"
            if {![info exists emitted($emitted_sig)]} {
                set emitted($emitted_sig) 1
                set generated [emit_graph_terminal_cmd [array get p]]
                if {$generated ne ""} {
                    mark_path_used [array get p] used_top used_harden
                    add_report_item "RECURSIVE_MERGED_TERMINAL path=[path_id_string [array get p]] endpoint=[record_full_name $end_rec] total=$p(delay)"
                }
            }
            array unset p
            continue
        }
        if {[is_harden_boundary_output_record $end_rec]} {
            set matched_chain_top 0
            foreach tseg [matching_chain_top_segments $end_rec $p(type)] {
                array set t $tseg
                set next [extend_path_with_top_segment [array get p] [array get t]]
                if {$next ne ""} {
                    lappend queue $next
                    set matched_chain_top 1
                }
                array unset t
            }
            if {!$matched_chain_top} {
                foreach target [missing_top_targets_from_harden_output_boundary $end_rec $p(type)] {
                    set missing_tseg [synthetic_missing_top_segment $end_rec $target $p(type)]
                    set next [extend_path_with_top_segment [array get p] $missing_tseg]
                    if {$next ne ""} {
                        lappend queue $next
                        add_report_item "MISSING_SDC_ASSUMED_ZERO source=top from=[record_full_name $end_rec] to=[record_full_name $target] reason=PT_FANOUT_BRIDGE"
                    }
                }
            }
        }

        if {[is_harden_boundary_input_record $end_rec]} {
            set matched_hsegs [matching_harden_segments_for_boundary $end_rec $p(type)]
            if {[llength $matched_hsegs] == 0} {
                set bridged 0
                foreach tseg [missing_harden_bridge_top_segments $end_rec $p(type)] {
                    array set t $tseg
                    set out_rec [lindex $t(from_records) 0]
                    set missing_hseg [synthetic_missing_harden_segment $end_rec $out_rec $p(type)]
                    set next [extend_path_with_harden_segment [array get p] $missing_hseg]
                    if {$next ne ""} {
                        lappend queue $next
                        set bridged 1
                        add_report_item "MISSING_SDC_ASSUMED_ZERO harden=[record_owner_name $end_rec] from=[record_full_name $end_rec] to=[record_full_name $out_rec] reason=BRIDGE_TO_NEXT_TOP_SEGMENT"
                    }
                    array unset t
                }
                if {!$bridged} {
                    set terminal_targets [missing_harden_targets_from_boundary $end_rec $p(type)]
                    foreach target $terminal_targets {
                        set missing_hseg [synthetic_missing_harden_segment $end_rec $target $p(type)]
                        if {[is_harden_boundary_output_record $target]} {
                            set next [extend_path_with_harden_segment [array get p] $missing_hseg]
                            if {$next ne ""} {
                                lappend queue $next
                                set bridged 1
                            }
                            continue
                        }
                        set emitted_sig [recursive_emit_signature [array get p] $missing_hseg]
                        if {[info exists emitted($emitted_sig)]} {
                            continue
                        }
                        set emitted($emitted_sig) 1
                        set generated [emit_graph_delay_cmd [array get p] $missing_hseg $end_rec]
                        if {$generated ne ""} {
                            mark_path_used [array get p] used_top used_harden
                            add_report_item "RECURSIVE_MERGED_MISSING_SDC path=[path_id_string [array get p]] + [summary_steps_path_id [list [segment_summary_step $missing_hseg]]] boundary=[record_full_name $end_rec] assumed_delay=0 total=$p(delay)"
                        }
                    }
                } else {
                    set terminal_targets {}
                }
                if {!$bridged && [llength $terminal_targets] == 0} {
                    set missing_hseg [synthetic_missing_harden_segment $end_rec $end_rec $p(type)]
                    add_review "" $missing_hseg "MISSING_HARDEN_SDC_ENDPOINT_NOT_FOUND" "missing harden SDC stage has no PT-inferred legal endpoint or output boundary"
                }
            }
            foreach hseg $matched_hsegs {
                array set h $hseg
                set emitted_sig [recursive_emit_signature [array get p] [array get h]]
                if {[info exists emitted($emitted_sig)]} {
                    array unset h
                    continue
                }
                set emitted($emitted_sig) 1
                set generated [emit_graph_delay_cmd [array get p] [array get h] $end_rec]
                if {$generated ne ""} {
                    mark_path_used [array get p] used_top used_harden
                    set used_harden($h(id)) 1
                    consume_segment [array get h]
                    add_report_item "RECURSIVE_MERGED path=[path_id_string [array get p]] + $h(id) boundary=[record_full_name $end_rec] total=[expr {$p(delay) + $h(delay)}]"
                    set to_rec [lindex $h(to_records) 0]
                    if {[is_harden_boundary_output_record $to_rec]} {
                        set next [extend_path_with_harden_segment [array get p] [array get h]]
                        if {$next ne ""} {
                            lappend queue $next
                        }
                    }
                }
                array unset h
            }
        }
        array unset p
    }

    foreach tseg $top_segments {
        array set t $tseg
        if {![info exists used_top($t(id))]} {
            add_review [array get t] "" "NO_HARDEN_SEGMENT_MATCHED" "top delay segment did not match any harden segment"
        }
        array unset t
    }
    foreach tseg $chain_top_segments {
        array set t $tseg
        if {![info exists used_top($t(id))]} {
            add_review [array get t] "" "NO_RECURSIVE_CHAIN_MATCHED" "top harden-output to harden-input segment did not find a complete recursive chain"
        }
        array unset t
    }
    foreach hseg $harden_segments {
        array set h $hseg
        if {![info exists used_harden($h(id))]} {
            add_review "" [array get h] "NO_TOP_SEGMENT_MATCHED" "no top or recursive delay path matched harden boundary"
        }
        array unset h
    }
}

proc stage2_delay::path_from_top_segment {tseg} {
    array set t $tseg
    set end_rec [lindex $t(to_records) 0]
    set from_records $t(from_records)
    set through_records {}
    if {[llength $from_records] == 0} {
        set through_records [list $end_rec]
    }
    set path [list \
        type $t(type) \
        delay $t(delay) \
        from_records $from_records \
        through_records $through_records \
        end_record $end_rec \
        top_ids [list $t(id)] \
        harden_ids {} \
        top_segments [list [array get t]] \
        harden_segments {} \
        path_steps [list [segment_summary_step [array get t]]] \
        depth 1 \
    ]
    array unset t
    return $path
}

proc stage2_delay::paths_from_top_segment {tseg} {
    variable options
    array set t $tseg
    if {[llength $t(from_records)] > 0 || $options(-top_open_from_mode) eq "through"} {
        set path [path_from_top_segment [array get t]]
        array unset t
        return [list $path]
    }

    set boundary [lindex $t(to_records) 0]
    set startpoints [pt_startpoints_to_boundary $boundary]
    if {[llength $startpoints] == 0} {
        add_review [array get t] "" "NO_TOP_STARTPOINT_INFERRED" "top open_from delay has no PT-inferred legal startpoint"
        array unset t
        return {}
    }
    if {[llength $startpoints] > $options(-max_endpoints)} {
        add_review [array get t] "" "TOO_MANY_TOP_STARTPOINTS" "top open_from inferred startpoints exceeded -max_endpoints"
        array unset t
        return {}
    }

    set out {}
    foreach startpoint $startpoints {
        lappend out [path_from_top_segment_with_startpoint [array get t] $startpoint]
    }
    array unset t
    return $out
}

proc stage2_delay::path_from_top_segment_with_startpoint {tseg startpoint} {
    array set t $tseg
    set end_rec [lindex $t(to_records) 0]
    set path [list \
        type $t(type) \
        delay $t(delay) \
        from_records [list $startpoint] \
        through_records {} \
        end_record $end_rec \
        top_ids [list $t(id)] \
        harden_ids {} \
        top_segments [list [array get t]] \
        harden_segments {} \
        path_steps [list [segment_summary_step [array get t]]] \
        depth 1 \
    ]
    array unset t
    return $path
}

proc stage2_delay::path_from_harden_output_source {hseg} {
    array set h $hseg
    set from_rec [lindex $h(from_records) 0]
    set to_rec [lindex $h(to_records) 0]
    set path [list \
        type $h(type) \
        delay $h(delay) \
        from_records [list $from_rec] \
        through_records {} \
        end_record $to_rec \
        top_ids {} \
        harden_ids [list $h(id)] \
        top_segments {} \
        harden_segments [list [array get h]] \
        path_steps [list [segment_summary_step [array get h]]] \
        depth 1 \
    ]
    array unset h
    return $path
}

proc stage2_delay::paths_from_missing_top_to_harden_feedthrough {hseg} {
    array set h $hseg
    set out {}
    if {$h(kind) ne "complete" || [llength $h(from_records)] != 1 || [llength $h(to_records)] != 1} {
        array unset h
        return {}
    }
    set input_rec [lindex $h(from_records) 0]
    set output_rec [lindex $h(to_records) 0]
    if {![is_harden_boundary_input_record $input_rec] || ![is_harden_boundary_output_record $output_rec]} {
        array unset h
        return {}
    }
    if {[top_or_chain_segment_exists_to_boundary $input_rec $h(type)]} {
        array unset h
        return {}
    }

    set startpoints [pt_startpoints_to_boundary $input_rec]
    if {[llength $startpoints] == 0} {
        add_report_item "MISSING_TOP_TO_FEEDTHROUGH_STARTPOINT_NOT_FOUND harden=$h(harden_inst) boundary=[record_full_name $input_rec] harden_id=$h(id)"
        array unset h
        return {}
    }

    foreach startpoint $startpoints {
        set missing_tseg [synthetic_missing_top_segment $startpoint $input_rec $h(type)]
        set path [path_from_top_segment $missing_tseg]
        set next [extend_path_with_harden_segment $path [array get h]]
        lappend out $next
        add_report_item "MISSING_SDC_ASSUMED_ZERO source=top from=[record_full_name $startpoint] to=[record_full_name $input_rec] reason=PT_FANIN_TO_FEEDTHROUGH_INPUT harden=$h(harden_inst) harden_id=$h(id)"
    }
    array unset h
    return $out
}

proc stage2_delay::top_or_chain_segment_exists_to_boundary {boundary type} {
    variable top_segments
    variable chain_top_segments
    set bname [record_full_name $boundary]
    foreach tseg [concat $top_segments $chain_top_segments] {
        array set t $tseg
        set matched 0
        if {$t(type) eq $type && [llength $t(to_records)] == 1 && [record_full_name [lindex $t(to_records) 0]] eq $bname} {
            set matched 1
        }
        array unset t
        if {$matched} {
            return 1
        }
    }
    return 0
}

proc stage2_delay::paths_from_missing_harden_output_boundary {boundary type} {
    set startpoints [pt_startpoints_to_boundary $boundary]
    if {[llength $startpoints] == 0} {
        add_report_item "MISSING_HARDEN_OUTPUT_SOURCE_STARTPOINT_NOT_FOUND boundary=[record_full_name $boundary] type=$type"
        return {}
    }

    set out {}
    foreach startpoint $startpoints {
        set missing_hseg [synthetic_missing_harden_segment $startpoint $boundary $type]
        array set h $missing_hseg
        set from_rec [lindex $h(from_records) 0]
        set to_rec [lindex $h(to_records) 0]
        set path [list \
            type $type \
            delay 0 \
            from_records [list $from_rec] \
            through_records {} \
            end_record $to_rec \
            top_ids {} \
            harden_ids [list $h(id)] \
            top_segments {} \
            harden_segments [list [array get h]] \
            path_steps [list [segment_summary_step [array get h]]] \
            depth 1 \
        ]
        lappend out $path
        add_report_item "MISSING_SDC_ASSUMED_ZERO harden=[record_owner_name $boundary] from=[record_full_name $startpoint] to=[record_full_name $boundary] reason=PT_FANIN_TO_OUTPUT_BOUNDARY"
        array unset h
    }
    return $out
}

proc stage2_delay::synthetic_missing_harden_segment {from_rec to_rec type} {
    array set f $from_rec
    array set t $to_rec
    set harden_inst $f(owner_harden_inst)
    if {$harden_inst eq ""} {
        set harden_inst $t(owner_harden_inst)
    }
    set id "MISSING_SDC_[safe_filename_token $harden_inst]_[safe_filename_token $f(full_name)]_TO_[safe_filename_token $t(full_name)]"
    set seg [list \
        id $id \
        type $type \
        kind complete \
        delay 0 \
        from_expr "" \
        to_expr "" \
        through_exprs {} \
        from_records [list $from_rec] \
        to_records [list $to_rec] \
        through_records {} \
        flags {} \
        source harden \
        source_file "NOT FOUND" \
        line_no "-" \
        original_text "" \
        original_id $id \
        split_index 1 \
        split_total 1 \
        harden_inst $harden_inst \
        class missing_sdc \
        boundary_pins {} \
        status ok \
        failure_reason "" \
        missing_sdc true \
    ]
    array unset f
    array unset t
    return $seg
}

proc stage2_delay::synthetic_missing_top_segment {from_rec to_rec type} {
    array set f $from_rec
    array set t $to_rec
    set id "MISSING_TOP_SDC_[safe_filename_token $f(full_name)]_TO_[safe_filename_token $t(full_name)]"
    set seg [list \
        id $id \
        type $type \
        kind complete \
        delay 0 \
        from_expr "" \
        to_expr "" \
        through_exprs {} \
        from_records [list $from_rec] \
        to_records [list $to_rec] \
        through_records {} \
        flags {} \
        source top \
        source_file "NOT FOUND" \
        line_no "-" \
        original_text "" \
        original_id $id \
        split_index 1 \
        split_total 1 \
        harden_inst "" \
        class missing_sdc \
        boundary_pins {} \
        status ok \
        failure_reason "" \
        missing_sdc true \
    ]
    array unset f
    array unset t
    return $seg
}

proc stage2_delay::harden_output_source_has_legal_start {hseg} {
    array set h $hseg
    set result 0
    if {$h(kind) eq "complete" && [llength $h(from_records)] == 1 && [llength $h(to_records)] == 1} {
        set from_rec [lindex $h(from_records) 0]
        set to_rec [lindex $h(to_records) 0]
        set result [expr {[validate_startpoint_record $from_rec] && [is_harden_boundary_output_record $to_rec]}]
    }
    array unset h
    return $result
}

proc stage2_delay::harden_output_source_exists_for_boundary {boundary type} {
    variable harden_output_segments
    set bname [record_full_name $boundary]
    foreach hseg $harden_output_segments {
        array set h $hseg
        if {$h(type) eq $type && [llength $h(to_records)] == 1 && [record_full_name [lindex $h(to_records) 0]] eq $bname && [harden_output_source_has_legal_start [array get h]]} {
            array unset h
            return 1
        }
        array unset h
    }
    return 0
}

proc stage2_delay::matching_chain_top_segments {from_boundary type} {
    variable chain_top_segments
    set out {}
    set bname [record_full_name $from_boundary]
    foreach tseg $chain_top_segments {
        array set t $tseg
        if {$t(type) eq $type && [llength $t(from_records)] == 1 && [record_full_name [lindex $t(from_records) 0]] eq $bname} {
            lappend out [array get t]
        }
        array unset t
    }
    return $out
}

proc stage2_delay::matching_harden_segments_for_boundary {boundary type} {
    variable harden_segments
    set out {}
    set bname [record_full_name $boundary]
    foreach hseg $harden_segments {
        array set h $hseg
        if {$h(type) ne $type} {
            array unset h
            continue
        }
        foreach candidate [harden_boundary_records [array get h]] {
            if {[record_full_name $candidate] eq $bname} {
                lappend out [array get h]
                break
            }
        }
        array unset h
    }
    return $out
}

proc stage2_delay::missing_harden_bridge_top_segments {boundary type} {
    variable chain_top_segments
    set out {}
    array set b $boundary
    set owner $b(owner_harden_inst)
    array unset b
    if {$owner eq ""} {
        return {}
    }
    foreach tseg $chain_top_segments {
        array set t $tseg
        if {$t(type) ne $type || [llength $t(from_records)] != 1} {
            array unset t
            continue
        }
        set from_rec [lindex $t(from_records) 0]
        array set f $from_rec
        if {$f(owner_harden_inst) eq $owner && [is_harden_boundary_output_record $from_rec]} {
            lappend out [array get t]
        }
        array unset f
        array unset t
    }
    return $out
}

proc stage2_delay::missing_harden_targets_from_boundary {boundary type} {
    set out {}
    foreach rec [pt_harden_fanout_targets_from_boundary $boundary] {
        if {[validate_endpoint_record $rec] || [is_harden_boundary_output_record $rec]} {
            lappend out $rec
        }
    }
    return [unique_records_by_name $out]
}

proc stage2_delay::missing_top_targets_from_harden_output_boundary {boundary type} {
    set boundary_targets {}
    foreach rec [pt_top_fanout_targets_from_harden_output_boundary $boundary] {
        if {[is_harden_boundary_input_record $rec] || [validate_endpoint_record $rec]} {
            lappend boundary_targets $rec
        }
    }
    return [unique_records_by_name $boundary_targets]
}

proc stage2_delay::pt_harden_fanout_targets_from_boundary {boundary} {
    array set b $boundary
    set boundary_name $b(full_name)
    set harden_inst $b(owner_harden_inst)
    array unset b

    if {$harden_inst eq ""} {
        return {}
    }
    if {[info commands all_fanout] eq "" || [info commands get_pins] eq "" || [info commands foreach_in_collection] eq ""} {
        pt_trace "missing-sdc fanout target skip boundary={$boundary_name} missing_command"
        return {}
    }

    set value {}
    pt_trace "get_pins -quiet {$boundary_name}"
    if {[catch {
        set start [get_pins -quiet $boundary_name]
        pt_trace "get_pins missing-sdc boundary result boundary={$boundary_name} count=[sizeof_collection $start]"
        if {[sizeof_collection $start] > 0} {
            foreach rec [pt_endpoint_fanout_records $start $boundary_name "missing-sdc"] {
                array set e $rec
                if {$e(owner_harden_inst) eq $harden_inst && $e(full_name) ne $boundary_name} {
                    lappend value $rec
                }
                array unset e
            }
            pt_trace "all_fanout -flat -from {$boundary_name}"
            set fanout [all_fanout -flat -from $start]
            pt_trace "all_fanout missing-sdc result boundary={$boundary_name} count=[sizeof_collection $fanout]"
            foreach_in_collection obj $fanout {
                set name [collection_object_name $obj]
                set owner [owner_harden_inst $name]
                if {$owner ne $harden_inst || $name eq $boundary_name} {
                    continue
                }
                set direction [pt_get_attr_by_name pin $name direction]
                set rec [object_record pin $name $direction $owner]
                if {[is_harden_boundary_output_record $rec]} {
                    lappend value $rec
                }
            }
        }
    } err]} {
        pt_trace "missing-sdc fanout target failed boundary={$boundary_name} error={$err}"
        return {}
    }
    set value [unique_records_by_name $value]
    pt_trace "missing-sdc fanout target summary boundary={$boundary_name} target_count=[llength $value]"
    return $value
}

proc stage2_delay::pt_top_fanout_targets_from_harden_output_boundary {boundary} {
    array set b $boundary
    set boundary_name $b(full_name)
    set owner_harden $b(owner_harden_inst)
    array unset b

    if {$owner_harden eq ""} {
        return {}
    }
    if {[info commands all_fanout] eq "" || [info commands get_pins] eq "" || [info commands foreach_in_collection] eq ""} {
        pt_trace "missing-top fanout target skip boundary={$boundary_name} missing_command"
        return {}
    }

    set value {}
    pt_trace "get_pins -quiet {$boundary_name}"
    if {[catch {
        set start [get_pins -quiet $boundary_name]
        pt_trace "get_pins missing-top boundary result boundary={$boundary_name} count=[sizeof_collection $start]"
        if {[sizeof_collection $start] > 0} {
            foreach rec [pt_endpoint_fanout_records $start $boundary_name "missing-top"] {
                array set e $rec
                if {$e(full_name) ne $boundary_name && $e(owner_harden_inst) ne $owner_harden} {
                    lappend value $rec
                }
                array unset e
            }
            pt_trace "all_fanout -flat -from {$boundary_name}"
            set fanout [all_fanout -flat -from $start]
            pt_trace "all_fanout missing-top result boundary={$boundary_name} count=[sizeof_collection $fanout]"
            foreach_in_collection obj $fanout {
                set rec [pt_object_record_from_collection $obj]
                array set r $rec
                set name $r(full_name)
                set owner $r(owner_harden_inst)
                array unset r
                if {$name eq $boundary_name || $owner eq $owner_harden} {
                    continue
                }
                if {[is_harden_boundary_input_record $rec] || [is_harden_boundary_output_record $rec]} {
                    lappend value $rec
                }
            }
        }
    } err]} {
        pt_trace "missing-top fanout target failed boundary={$boundary_name} error={$err}"
        return {}
    }
    set value [unique_records_by_name $value]
    pt_trace "missing-top fanout target summary boundary={$boundary_name} target_count=[llength $value]"
    return $value
}

proc stage2_delay::pt_endpoint_fanout_records {start boundary_name label} {
    if {[info commands all_fanout] eq "" || [info commands foreach_in_collection] eq "" || [info commands sizeof_collection] eq ""} {
        pt_trace "$label endpoint fanout skip boundary={$boundary_name} missing_command"
        return {}
    }
    set value {}
    if {[catch {
        pt_trace "all_fanout -flat -endpoints_only -from {$boundary_name}"
        set endpoints [all_fanout -flat -endpoints_only -from $start]
        pt_trace "all_fanout endpoints result boundary={$boundary_name} count=[sizeof_collection $endpoints]"
        foreach_in_collection obj $endpoints {
            set rec [mark_pt_endpoint_record [pt_object_record_from_collection $obj]]
            if {[validate_endpoint_record $rec]} {
                lappend value $rec
            }
        }
    } err]} {
        pt_trace "$label endpoint fanout failed boundary={$boundary_name} error={$err}"
        return {}
    }
    return [unique_records_by_name $value]
}

proc stage2_delay::pt_startpoints_to_boundary {boundary} {
    array set b $boundary
    set boundary_name $b(full_name)
    set boundary_class $b(object_class)
    array unset b

    if {[info commands all_fanin] eq "" || [info commands foreach_in_collection] eq "" || [info commands sizeof_collection] eq ""} {
        pt_trace "top startpoint inference skip boundary={$boundary_name} missing_command"
        return {}
    }

    set getter get_pins
    if {$boundary_class eq "port"} {
        set getter get_ports
    }
    if {[info commands $getter] eq ""} {
        pt_trace "top startpoint inference skip boundary={$boundary_name} missing_getter=$getter"
        return {}
    }

    set value {}
    pt_trace "$getter -quiet {$boundary_name}"
    if {[catch {
        set target [$getter -quiet $boundary_name]
        pt_trace "$getter top-open-from boundary result boundary={$boundary_name} count=[sizeof_collection $target]"
        if {[sizeof_collection $target] > 0} {
            set fanin {}
            if {[catch {
                pt_trace "all_fanin -flat -startpoints_only -to {$boundary_name}"
                set fanin [all_fanin -flat -startpoints_only -to $target]
            } err_startpoints]} {
                pt_trace "all_fanin startpoints_only failed boundary={$boundary_name} error={$err_startpoints}"
                pt_trace "all_fanin -flat -to {$boundary_name}"
                set fanin [all_fanin -flat -to $target]
            }
            pt_trace "all_fanin top-open-from result boundary={$boundary_name} count=[sizeof_collection $fanin]"
            foreach_in_collection obj $fanin {
                set rec [pt_object_record_from_collection $obj]
                set rec [mark_pt_startpoint_record $rec]
                if {[validate_startpoint_record $rec]} {
                    lappend value $rec
                }
            }
        }
    } err]} {
        pt_trace "top startpoint inference failed boundary={$boundary_name} error={$err}"
        return {}
    }
    set value [unique_records_by_name $value]
    pt_trace "top startpoint inference summary boundary={$boundary_name} startpoint_count=[llength $value]"
    return $value
}

proc stage2_delay::mark_pt_startpoint_record {rec} {
    array set r $rec
    set r(pt_startpoint) true
    set out [array get r]
    array unset r
    return $out
}

proc stage2_delay::mark_pt_endpoint_record {rec} {
    array set r $rec
    set r(pt_endpoint) true
    set out [array get r]
    array unset r
    return $out
}

proc stage2_delay::pt_object_record_from_collection {obj} {
    set name [collection_object_name $obj]
    set direction ""
    catch {set direction [get_attribute $obj direction]}
    set class ""
    catch {set class [get_attribute $obj object_class]}
    set class [normalize_pt_object_class $class $name]
    if {$direction eq ""} {
        set direction [pt_get_attr_by_name $class $name direction]
    }
    return [object_record $class $name $direction [owner_harden_inst $name]]
}

proc stage2_delay::normalize_pt_object_class {class name} {
    set class [string tolower $class]
    if {$class in {pin port cell net}} {
        return $class
    }
    if {[string first "/" $name] >= 0} {
        return pin
    }
    if {[info commands get_ports] ne ""} {
        if {![catch {set ports [get_ports -quiet $name]}] && [sizeof_collection $ports] > 0} {
            return port
        }
    }
    return pin
}

proc stage2_delay::extend_path_with_top_segment {path tseg} {
    array set p $path
    array set t $tseg
    if {[llength $t(to_records)] != 1} {
        array unset p
        array unset t
        return ""
    }
    set end_rec [lindex $t(to_records) 0]
    set through_records $p(through_records)
    if {[llength $p(from_records)] == 0} {
        lappend through_records [lindex $t(from_records) 0] $end_rec
    }
    set next [list \
        type $p(type) \
        delay [format_delay [expr {$p(delay) + $t(delay)}]] \
        from_records $p(from_records) \
        through_records $through_records \
        end_record $end_rec \
        top_ids [concat $p(top_ids) [list $t(id)]] \
        harden_ids $p(harden_ids) \
        top_segments [concat $p(top_segments) [list [array get t]]] \
        harden_segments $p(harden_segments) \
        path_steps [concat $p(path_steps) [list [segment_summary_step [array get t]]]] \
        depth [expr {$p(depth) + 1}] \
    ]
    array unset p
    array unset t
    return $next
}

proc stage2_delay::extend_path_with_harden_segment {path hseg} {
    array set p $path
    array set h $hseg
    set to_rec [lindex $h(to_records) 0]
    set through_records $p(through_records)
    if {[llength $p(from_records)] == 0} {
        lappend through_records $to_rec
    }
    set next [list \
        type $p(type) \
        delay [format_delay [expr {$p(delay) + $h(delay)}]] \
        from_records $p(from_records) \
        through_records $through_records \
        end_record $to_rec \
        top_ids $p(top_ids) \
        harden_ids [concat $p(harden_ids) [list $h(id)]] \
        top_segments $p(top_segments) \
        harden_segments [concat $p(harden_segments) [list [array get h]]] \
        path_steps [concat $p(path_steps) [list [segment_summary_step [array get h]]]] \
        depth [expr {$p(depth) + 1}] \
    ]
    array unset p
    array unset h
    return $next
}

proc stage2_delay::emit_graph_delay_cmd {path hseg boundary} {
    variable generated_cmds
    variable options
    array set p $path
    array set h $hseg
    set to_rec [lindex $h(to_records) 0]
    if {![boundary_and_endpoint_same_harden $boundary $to_rec]} {
        add_review "" [array get h] "BOUNDARY_ENDPOINT_OWNER_MISMATCH" "boundary and endpoint do not belong to same harden instance"
        array unset p
        array unset h
        return ""
    }
    if {![validate_endpoint_record $to_rec] && ![is_harden_boundary_output_record $to_rec]} {
        add_review "" [array get h] "INVALID_ENDPOINT" "generated -to object is not a legal endpoint"
        array unset p
        array unset h
        return ""
    }
    set total [format_delay [expr {$p(delay) + $h(delay)}]]
    set cmd_name [expr {$p(type) eq "max" ? "set_max_delay" : "set_min_delay"}]

    set start_records $p(from_records)
    if {[llength $start_records] == 0} {
        set start_records [pt_startpoints_to_boundary $boundary]
        if {[llength $start_records] == 0} {
            add_review "" [array get h] "NO_FINAL_STARTPOINT_INFERRED" "generated path has no -from and PT all_fanin could not infer a legal startpoint"
            array unset p
            array unset h
            return ""
        }
        if {[llength $start_records] > $options(-max_endpoints)} {
            add_review "" [array get h] "TOO_MANY_FINAL_STARTPOINTS" "generated path inferred startpoints exceeded -max_endpoints"
            array unset p
            array unset h
            return ""
        }
        add_report_item "TOP_OPEN_FROM_STARTPOINT_INFERRED boundary=[record_full_name $boundary] count=[llength $start_records]"
    }

    set summary_steps [concat $p(path_steps) [list [segment_summary_step [array get h]]]]
    set summary_through [summary_through_records_from_steps $summary_steps $to_rec $p(through_records)]
    set emitted_cmds {}
    foreach from_rec $start_records {
        if {![validate_startpoint_record $from_rec]} {
            add_review "" [array get h] "INVALID_STARTPOINT" "generated -from object is not a legal startpoint"
            continue
        }
        set cmd "$cmd_name $total"
        append cmd " -from [format_record_collection $from_rec]"
        foreach through_rec [command_through_records $summary_through $from_rec $to_rec] {
            append cmd " -through [format_record_collection $through_rec]"
        }
        append cmd " -to [format_record_collection $to_rec]"
        set e2e_id [next_e2e_id]
        lappend generated_cmds [list e2e_id $e2e_id command $cmd top_id [join $p(top_ids) "+"] harden_id [join [concat $p(harden_ids) [list $h(id)]] "+"] boundary [record_full_name $boundary] total $total]
        record_generated_path_summary $e2e_id [summary_steps_path_id $summary_steps] $summary_steps $total [list $from_rec] $summary_through $to_rec $cmd
        lappend emitted_cmds $cmd
    }

    if {[llength $emitted_cmds] > 0} {
        consume_graph_path [array get p]
        foreach seg $p(harden_segments) {
            add_missing_sdc_report_for_segment $seg $total
        }
        add_missing_sdc_report_for_segment [array get h] $total
    }
    array unset p
    array unset h
    return [join $emitted_cmds "\n"]
}

proc stage2_delay::emit_graph_terminal_cmd {path} {
    variable generated_cmds
    variable options
    array set p $path
    set to_rec $p(end_record)
    if {![validate_endpoint_record $to_rec]} {
        add_review "" "" "INVALID_TERMINAL_ENDPOINT" "recursive path terminal object is not a legal endpoint"
        array unset p
        return ""
    }
    set total [format_delay $p(delay)]
    set cmd_name [expr {$p(type) eq "max" ? "set_max_delay" : "set_min_delay"}]
    set start_records $p(from_records)
    if {[llength $start_records] == 0} {
        set start_records [pt_startpoints_to_boundary $to_rec]
        if {[llength $start_records] == 0} {
            add_review "" "" "NO_FINAL_STARTPOINT_INFERRED" "terminal recursive path has no -from and PT all_fanin could not infer a legal startpoint"
            array unset p
            return ""
        }
        if {[llength $start_records] > $options(-max_endpoints)} {
            add_review "" "" "TOO_MANY_FINAL_STARTPOINTS" "terminal recursive path inferred startpoints exceeded -max_endpoints"
            array unset p
            return ""
        }
    }

    set summary_steps $p(path_steps)
    set summary_through [summary_through_records_from_steps $summary_steps $to_rec $p(through_records)]
    set emitted_cmds {}
    foreach from_rec $start_records {
        if {![validate_startpoint_record $from_rec]} {
            add_review "" "" "INVALID_STARTPOINT" "terminal generated -from object is not a legal startpoint"
            continue
        }
        set cmd "$cmd_name $total"
        append cmd " -from [format_record_collection $from_rec]"
        foreach through_rec [command_through_records $summary_through $from_rec $to_rec] {
            append cmd " -through [format_record_collection $through_rec]"
        }
        append cmd " -to [format_record_collection $to_rec]"
        set e2e_id [next_e2e_id]
        lappend generated_cmds [list e2e_id $e2e_id command $cmd top_id [join $p(top_ids) "+"] harden_id [join $p(harden_ids) "+"] boundary [record_full_name $to_rec] total $total]
        record_generated_path_summary $e2e_id [summary_steps_path_id $summary_steps] $summary_steps $total [list $from_rec] $summary_through $to_rec $cmd
        lappend emitted_cmds $cmd
    }

    if {[llength $emitted_cmds] > 0} {
        consume_graph_path [array get p]
        foreach seg $p(top_segments) {
            add_missing_sdc_report_for_segment $seg $total
        }
        foreach seg $p(harden_segments) {
            add_missing_sdc_report_for_segment $seg $total
        }
    }
    array unset p
    return [join $emitted_cmds "\n"]
}

proc stage2_delay::add_missing_sdc_report_for_segment {seg total} {
    array set s $seg
    if {[info exists s(missing_sdc)] && [truthy $s(missing_sdc)]} {
        if {$s(source) eq "top"} {
            add_report_item "MISSING_SDC_ASSUMED_ZERO source=top from=[records_summary_name_text $s(from_records)] to=[records_summary_name_text $s(to_records)] generated_total=$total"
        } else {
            add_report_item "MISSING_SDC_ASSUMED_ZERO harden=$s(harden_inst) from=[records_summary_name_text $s(from_records)] to=[records_summary_name_text $s(to_records)] generated_total=$total"
        }
    }
    array unset s
}

proc stage2_delay::consume_graph_path {path} {
    array set p $path
    foreach seg $p(top_segments) {
        consume_segment $seg
    }
    foreach seg $p(harden_segments) {
        consume_segment $seg
    }
    array unset p
}

proc stage2_delay::mark_path_used {path used_top_name used_harden_name} {
    upvar 1 $used_top_name used_top
    upvar 1 $used_harden_name used_harden
    array set p $path
    foreach id $p(top_ids) {
        set used_top($id) 1
    }
    foreach id $p(harden_ids) {
        set used_harden($id) 1
    }
    array unset p
}

proc stage2_delay::path_signature {path} {
    array set p $path
    set sig [list type $p(type) delay [format_delay $p(delay)] from [records_signature $p(from_records)] through [records_signature $p(through_records)] end [record_full_name $p(end_record)] depth $p(depth)]
    array unset p
    return $sig
}

proc stage2_delay::recursive_emit_signature {path hseg} {
    array set p $path
    array set h $hseg
    set sig [list type $p(type) from [records_signature $p(from_records)] through [records_signature $p(through_records)] to [record_full_name [lindex $h(to_records) 0]] total [format_delay [expr {$p(delay) + $h(delay)}]] path [path_id_string [array get p]] harden $h(id)]
    array unset p
    array unset h
    return $sig
}

proc stage2_delay::path_id_string {path} {
    array set p $path
    set ids {}
    foreach id $p(harden_ids) {
        lappend ids $id
    }
    foreach id $p(top_ids) {
        lappend ids $id
    }
    array unset p
    return [join $ids "+"]
}

proc stage2_delay::match_top_to_harden_segments {} {
    variable top_segments
    variable harden_segments
    variable options

    array set matched_top {}
    array set matched_top_segment {}
    array set generated_pair {}
    array set mapped_group_total {}
    array set mapped_group_rep {}
    foreach tseg $top_segments {
        array set t $tseg
        if {[info exists t(top_port_map_group)]} {
            incr mapped_group_total($t(top_port_map_group))
            if {![info exists mapped_group_rep($t(top_port_map_group))]} {
                set mapped_group_rep($t(top_port_map_group)) [array get t]
            }
        }
        array unset t
    }

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
                    consume_segment [array get h]
                    set generated_pair($pair_key) 1
                    set matched_top($t(id)) 1
                    set matched_top_segment($t(id)) [array get t]
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

    array set mapped_group_matched {}
    foreach id [array names matched_top_segment] {
        array set t $matched_top_segment($id)
        if {[info exists t(top_port_map_group)]} {
            set mapped_group_matched([list $t(top_port_map_group) $id]) 1
        } else {
            consume_segment [array get t]
        }
        array unset t
    }

    array set mapped_group_matched_count {}
    foreach key [array names mapped_group_matched] {
        set group [lindex $key 0]
        incr mapped_group_matched_count($group)
    }
    foreach group [array names mapped_group_total] {
        set matched_count 0
        if {[info exists mapped_group_matched_count($group)]} {
            set matched_count $mapped_group_matched_count($group)
        }
        if {$matched_count == $mapped_group_total($group)} {
            consume_segment $mapped_group_rep($group)
            add_report_item "TOP_PORT_BOUNDARY_MAP_CONSUMED group=$group matched=$matched_count total=$mapped_group_total($group)"
        } elseif {$matched_count > 0} {
            add_report_item "TOP_PORT_BOUNDARY_MAP_KEEP_ORIGINAL group=$group matched=$matched_count total=$mapped_group_total($group)"
        }
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

proc stage2_delay::record_owner_name {rec} {
    array set r $rec
    set owner $r(owner_harden_inst)
    array unset r
    return $owner
}

proc stage2_delay::command_through_records {records from_rec to_rec} {
    set skip {}
    if {$from_rec ne ""} {
        lappend skip [record_full_name $from_rec]
    }
    if {$to_rec ne ""} {
        lappend skip [record_full_name $to_rec]
    }
    set out {}
    foreach rec [unique_records_by_name $records] {
        set name [record_full_name $rec]
        if {[lsearch -exact $skip $name] < 0} {
            lappend out $rec
        }
    }
    return $out
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
        if {![validate_endpoint_record $to_rec] && ![is_harden_boundary_output_record $to_rec]} {
            add_review [array get t] [array get h] "INVALID_ENDPOINT" "generated -to object is not a legal endpoint"
            array unset t
            array unset h
            return ""
        }
        set cmd "$cmd_name $total -from [format_record_collection $from_rec]"
        foreach through_rec [command_through_records [list $boundary] $from_rec $to_rec] {
            append cmd " -through [format_record_collection $through_rec]"
        }
        append cmd " -to [format_record_collection $to_rec]"
    } else {
        set start_records [pt_startpoints_to_boundary $boundary]
        if {[llength $start_records] == 0} {
            add_review [array get t] [array get h] "NO_FINAL_STARTPOINT_INFERRED" "top open_from has no -from and PT all_fanin could not infer a legal startpoint"
            array unset t
            array unset h
            return ""
        } elseif {[llength $start_records] > $options(-max_endpoints)} {
            add_review [array get t] [array get h] "TOO_MANY_FINAL_STARTPOINTS" "top open_from inferred startpoints exceeded -max_endpoints"
            array unset t
            array unset h
            return ""
        } elseif {![validate_endpoint_record $to_rec] && ![is_harden_boundary_output_record $to_rec]} {
            add_review [array get t] [array get h] "INVALID_ENDPOINT" "generated -to object is not a legal endpoint"
            array unset t
            array unset h
            return ""
        } else {
            set emitted_cmds {}
            foreach from_rec $start_records {
                if {![validate_startpoint_record $from_rec]} {
                    add_review [array get t] [array get h] "INVALID_STARTPOINT" "generated -from object is not a legal startpoint"
                    continue
                }
                set one_cmd "$cmd_name $total -from [format_record_collection $from_rec]"
                foreach through_rec [command_through_records [list $boundary] $from_rec $to_rec] {
                    append one_cmd " -through [format_record_collection $through_rec]"
                }
                append one_cmd " -to [format_record_collection $to_rec]"
                set e2e_id [next_e2e_id]
                lappend generated_cmds [list e2e_id $e2e_id command $one_cmd top_id $t(id) harden_id $h(id) boundary [record_full_name $boundary] total $total]
                set summary_steps [list [segment_summary_step [array get t]] [segment_summary_step [array get h]]]
                set summary_through [summary_through_records_from_steps $summary_steps $to_rec [list $boundary]]
                record_generated_path_summary $e2e_id [summary_steps_path_id $summary_steps] $summary_steps $total [list $from_rec] $summary_through $to_rec $one_cmd
                lappend emitted_cmds $one_cmd
            }
            array unset t
            array unset h
            return [join $emitted_cmds "\n"]
        }
    }
    set e2e_id [next_e2e_id]
    lappend generated_cmds [list e2e_id $e2e_id command $cmd top_id $t(id) harden_id $h(id) boundary [record_full_name $boundary] total $total]
    set summary_steps [list [segment_summary_step [array get t]] [segment_summary_step [array get h]]]
    set final_from_records {}
    if {$t(kind) eq "complete"} {
        set final_from_records [list [lindex $t(from_records) 0]]
    }
    set summary_through [summary_through_records_from_steps $summary_steps $to_rec [list $boundary]]
    record_generated_path_summary $e2e_id [summary_steps_path_id $summary_steps] $summary_steps $total $final_from_records $summary_through $to_rec $cmd
    array unset t
    array unset h
    return $cmd
}

proc stage2_delay::emit_residual_through_cmd {hseg boundary reason} {
    variable residual_cmds
    variable options
    array set h $hseg
    set to_rec [lindex $h(to_records) 0]
    if {![validate_endpoint_record $to_rec] && ![is_harden_boundary_output_record $to_rec]} {
        add_review "" [array get h] "INVALID_ENDPOINT" "residual -to object is not a legal endpoint"
        array unset h
        return
    }
    set start_records [pt_startpoints_to_boundary $boundary]
    if {[llength $start_records] == 0} {
        add_review "" [array get h] "NO_FINAL_STARTPOINT_INFERRED" "residual path has no -from and PT all_fanin could not infer a legal startpoint"
        array unset h
        return
    }
    if {[llength $start_records] > $options(-max_endpoints)} {
        add_review "" [array get h] "TOO_MANY_FINAL_STARTPOINTS" "residual path inferred startpoints exceeded -max_endpoints"
        array unset h
        return
    }
    set cmd_name [expr {$h(type) eq "max" ? "set_max_delay" : "set_min_delay"}]
    foreach from_rec $start_records {
        if {![validate_startpoint_record $from_rec]} {
            add_review "" [array get h] "INVALID_STARTPOINT" "residual -from object is not a legal startpoint"
            continue
        }
        set cmd "$cmd_name [format_delay $h(delay)] -from [format_record_collection $from_rec]"
        foreach through_rec [command_through_records [list $boundary] $from_rec $to_rec] {
            append cmd " -through [format_record_collection $through_rec]"
        }
        append cmd " -to [format_record_collection $to_rec]"
        set e2e_id [next_e2e_id]
        lappend residual_cmds [list e2e_id $e2e_id command $cmd harden_id $h(id) boundary [record_full_name $boundary] reason $reason]
        record_residual_path_summary $e2e_id [array get h] $boundary $reason $cmd [list $from_rec]
        add_report_item "RESIDUAL_CONSERVATIVE $h(id) boundary=[record_full_name $boundary] reason=$reason"
    }
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
    if {[info exists r(pt_startpoint)] && [truthy $r(pt_startpoint)] && $r(object_class) in {pin port cell}} {
        set ok 1
    } elseif {$r(object_class) eq "port" && $r(direction) in {in inout}} {
        set ok 1
    } elseif {$r(object_class) eq "pin" && $r(direction) in {out inout}} {
        set ok 1
    }
    array unset r
    return $ok
}

proc stage2_delay::validate_endpoint_record {rec} {
    array set r $rec
    set ok 0
    if {[info exists r(pt_endpoint)] && [truthy $r(pt_endpoint)] && $r(object_class) in {pin port cell} && ![is_harden_boundary_input_record $rec]} {
        set ok 1
    } elseif {$r(object_class) eq "port" && $r(direction) in {out inout}} {
        set ok 1
    } elseif {$r(object_class) eq "pin" && $r(direction) in {in inout} && ![is_harden_boundary_input_record $rec]} {
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

proc stage2_delay::pt_trace {message} {
    variable options
    if {[info exists options(-verbose_pt_query)] && [truthy $options(-verbose_pt_query)]} {
        puts "PT_QUERY: $message"
    }
}

proc stage2_delay::consume_segment {seg} {
    variable consumed_constraints
    variable consumed_segments
    array set s $seg
    if {[info exists s(missing_sdc)] && [truthy $s(missing_sdc)]} {
        array unset s
        return
    }
    set key "$s(source_file)|$s(id)"
    if {![info exists consumed_constraints($key)]} {
        set consumed_constraints($key) $s(original_text)
        lappend consumed_segments [array get s]
    }
    array unset s
}

proc stage2_delay::add_review {top_seg harden_seg reason action} {
    variable review_items
    record_review_path_summary $top_seg $harden_seg $reason $action
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
    set fout [open_text $path w]
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
        puts $fout "# MERGED id=$g(e2e_id) top=$g(top_id) harden=$g(harden_id) boundary=$g(boundary)"
        puts $fout $g(command)
        puts $fout ""
        array unset g
    }
    foreach item $residual_cmds {
        array set r $item
        puts $fout "# RESIDUAL_CONSERVATIVE id=$r(e2e_id) harden=$r(harden_id) boundary=$r(boundary) reason=$r(reason)"
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
    set fout [open_text $path w]
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
    set fout [open_text $path w]
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
    variable chain_top_segments
    variable harden_segments
    variable harden_output_segments
    variable passthrough_segments
    variable generated_cmds
    variable residual_cmds
    variable review_items
    variable report_items

    set fout [open_text $path w]
    write_author_banner $fout
    puts $fout ""
    puts $fout "\[SUMMARY\]"
    puts $fout "Top SDC                         : $options(-top_sdc)"
    puts $fout "Harden list                     : $options(-harden_list)"
    puts $fout "Generated E2E SDC               : $options(-out_e2e_sdc)"
    puts $fout "Final flatten SDC               : $options(-out_final_sdc)"
    puts $fout "Path summary dir                : $options(-out_summary_dir)"
    puts $fout "Write path summary              : $options(-write_path_summary)"
    puts $fout "Total top merge candidates      : [llength $top_segments]"
    puts $fout "Total top chain candidates      : [llength $chain_top_segments]"
    puts $fout "Total harden merge candidates   : [llength $harden_segments]"
    puts $fout "Total harden output sources     : [llength $harden_output_segments]"
    puts $fout "Merged constraints              : [llength $generated_cmds]"
    puts $fout "Passthrough constraints         : [llength $passthrough_segments]"
    puts $fout "Residual conservative constraints: [llength $residual_cmds]"
    puts $fout "Review required constraints     : [llength $review_items]"
    puts $fout "Merge mode                      : $options(-merge_mode)"
    puts $fout "Top open_from mode              : $options(-top_open_from_mode)"
    puts $fout "Top port boundary map mode      : $options(-top_port_boundary_map_mode)"
    puts $fout "Recursive chain mode            : $options(-recursive_chain_mode)"
    puts $fout "Max chain depth                 : $options(-max_chain_depth)"
    puts $fout "Verbose PT query                : $options(-verbose_pt_query)"
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

    set fout [open_text $path w]
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
        puts $fout "# MERGED id=$g(e2e_id) top=$g(top_id) harden=$g(harden_id) boundary=$g(boundary)"
        puts $fout $g(command)
        puts $fout ""
        array unset g
    }
    foreach item $residual_cmds {
        array set r $item
        puts $fout "# RESIDUAL_CONSERVATIVE id=$r(e2e_id) harden=$r(harden_id) boundary=$r(boundary) reason=$r(reason)"
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

proc stage2_delay::write_path_summary {dir} {
    variable TOOL_NAME
    variable VERSION
    variable AUTHOR
    variable hardens
    variable path_summary_items

    if {$dir eq ""} {
        return
    }
    if {![file isdirectory $dir]} {
        file mkdir $dir
    }

    set sheet_order {top}
    foreach harden $hardens {
        array set h $harden
        if {[info exists h(inst_path)] && $h(inst_path) ne "" && [lsearch -exact $sheet_order $h(inst_path)] < 0} {
            lappend sheet_order $h(inst_path)
        }
        array unset h
    }

    array set rows_by_sheet {}
    foreach sheet $sheet_order {
        set rows_by_sheet($sheet) {}
    }
    foreach item $path_summary_items {
        set sheet [summary_item_get $item sheet top]
        if {![info exists rows_by_sheet($sheet)]} {
            set rows_by_sheet($sheet) {}
            lappend sheet_order $sheet
        }
        lappend rows_by_sheet($sheet) $item
    }

    array set sheet_file {}
    array set used_file {}
    foreach sheet $sheet_order {
        if {$sheet eq "top"} {
            set token "top"
        } else {
            set token [safe_filename_token $sheet]
        }
        if {$token eq ""} {
            set token "sheet"
        }
        set base $token
        set filename "${base}.csv"
        set suffix 1
        while {[info exists used_file($filename)]} {
            incr suffix
            set filename "${base}_${suffix}.csv"
        }
        set used_file($filename) 1
        set sheet_file($sheet) $filename
    }

    set index_path [file join $dir 00_index.csv]
    set fout [open_text $index_path w]
    csv_write_row $fout {tool version author sheet file row_count merged_rows residual_rows review_rows max_delay_used max_delay_total max_delay_usage missing_sdc_stages}
    foreach sheet $sheet_order {
        set rows $rows_by_sheet($sheet)
        set max_stats [max_delay_usage_stats_for_sheet $sheet]
        set max_used [lindex $max_stats 0]
        set max_total [lindex $max_stats 1]
        set max_usage [format "%d/%d" $max_used $max_total]
        set missing_stages [missing_sdc_stage_count $rows]
        csv_write_row $fout [list \
            $TOOL_NAME \
            $VERSION \
            $AUTHOR \
            $sheet \
            $sheet_file($sheet) \
            [llength $rows] \
            [summary_count_status $rows MERGED] \
            [summary_count_status $rows RESIDUAL] \
            [summary_count_status $rows REVIEW] \
            $max_used \
            $max_total \
            $max_usage \
            $missing_stages \
        ]
    }
    close $fout

    foreach sheet $sheet_order {
        write_path_summary_sheet [file join $dir $sheet_file($sheet)] $rows_by_sheet($sheet)
    }
    puts "INFO: Path summary CSV    : $dir"
}

proc stage2_delay::missing_sdc_stage_count {rows} {
    array set seen {}
    foreach item $rows {
        set cmd_id [summary_item_get $item cmd_id ""]
        if {[string match "MISSING_*" $cmd_id]} {
            set seen($cmd_id) 1
        }
    }
    return [array size seen]
}

proc stage2_delay::segment_sheet {seg} {
    array set s $seg
    set sheet "top"
    if {[info exists s(source)] && $s(source) eq "harden"} {
        set sheet $s(harden_inst)
    }
    array unset s
    return $sheet
}

proc stage2_delay::max_delay_usage_stats_for_sheet {sheet} {
    variable all_delay_segments
    variable consumed_segments

    array set total_seen {}
    array set used_seen {}
    foreach seg $all_delay_segments {
        array set s $seg
        if {$s(type) eq "max" && [segment_sheet [array get s]] eq $sheet} {
            set total_seen([list $s(source_file) $s(original_id)]) 1
        }
        array unset s
    }
    foreach seg $consumed_segments {
        array set s $seg
        if {$s(type) eq "max" && [segment_sheet [array get s]] eq $sheet} {
            set key [list $s(source_file) $s(original_id)]
            if {[info exists total_seen($key)]} {
                set used_seen($key) 1
            }
        }
        array unset s
    }
    return [list [array size used_seen] [array size total_seen]]
}

proc stage2_delay::summary_count_status {rows status} {
    set count 0
    foreach item $rows {
        if {[summary_item_get $item merge_status ""] eq $status} {
            incr count
        }
    }
    return $count
}

proc stage2_delay::summary_item_get {item key {default "-"}} {
    array set r $item
    if {[info exists r($key)]} {
        set value $r($key)
    } else {
        set value $default
    }
    array unset r
    return $value
}

proc stage2_delay::write_path_summary_sheet {path rows} {
    set max_through 0
    set max_steps 0
    foreach item $rows {
        array set r $item
        if {[info exists r(through_records)] && [llength $r(through_records)] > $max_through} {
            set max_through [llength $r(through_records)]
        }
        if {[info exists r(path_steps)] && [llength $r(path_steps)] > $max_steps} {
            set max_steps [llength $r(path_steps)]
        }
        array unset r
    }

    set max_path_cols [expr {$max_steps > $max_through ? $max_steps : $max_through}]
    set header [list e2e_id sheet merge_status path_id source source_inst source_file line_no cmd_id original_id delay_type native_delay native_from native_through native_to final_delay "Start Point" start_sdc_delay start_from start_to]
    for {set idx 1} {$idx <= $max_path_cols} {incr idx} {
        lappend header "stage_${idx}_sdc_delay"
        lappend header "stage_${idx}_from"
        lappend header "stage_${idx}_to"
        if {$idx <= $max_through} {
            lappend header "through_$idx"
        }
    }
    lappend header "End Point" end_sdc_delay end_from end_to generated_cmd review_reason
    for {set idx 1} {$idx <= $max_steps} {incr idx} {
        lappend header "seg_${idx}_source" "seg_${idx}_inst" "seg_${idx}_cmd_id" "seg_${idx}_sdc_delay" "seg_${idx}_from" "seg_${idx}_through" "seg_${idx}_to"
    }

    set fout [open_text $path w]
    csv_write_row $fout $header
    foreach item $rows {
        array set r $item
        set row {}
        foreach key {e2e_id sheet merge_status path_id source source_inst source_file line_no cmd_id original_id delay_type native_delay native_from native_through native_to final_delay final_from start_sdc_delay start_from start_to} {
            lappend row [summary_item_get $item $key]
        }
        set stage_delays [summary_item_get $item stage_delays {}]
        set stage_from_texts [summary_item_get $item stage_from_texts {}]
        set stage_to_texts [summary_item_get $item stage_to_texts {}]
        set through_records [summary_item_get $item through_records {}]
        for {set idx 0} {$idx < $max_path_cols} {incr idx} {
            if {$idx < [llength $stage_delays]} {
                lappend row [lindex $stage_delays $idx]
            } else {
                lappend row "-"
            }
            if {$idx < [llength $stage_from_texts]} {
                lappend row [lindex $stage_from_texts $idx]
            } else {
                lappend row "-"
            }
            if {$idx < [llength $stage_to_texts]} {
                lappend row [lindex $stage_to_texts $idx]
            } else {
                lappend row "-"
            }
            if {$idx < $max_through} {
                if {$idx < [llength $through_records]} {
                    lappend row [lindex $through_records $idx]
                } else {
                    lappend row "-"
                }
            }
        }
        foreach key {final_to end_sdc_delay end_from end_to generated_cmd review_reason} {
            lappend row [summary_item_get $item $key]
        }
        set path_steps [summary_item_get $item path_steps {}]
        for {set idx 0} {$idx < $max_steps} {incr idx} {
            if {$idx < [llength $path_steps]} {
                array set st [lindex $path_steps $idx]
                lappend row $st(source) $st(source_inst) $st(cmd_id) $st(delay) $st(from) $st(through) $st(to)
                array unset st
            } else {
                lappend row "-" "-" "-" "-" "-" "-" "-"
            }
        }
        csv_write_row $fout $row
        array unset r
    }
    close $fout
}

proc stage2_delay::csv_write_row {file_handle fields} {
    set escaped {}
    foreach field $fields {
        lappend escaped [csv_quote $field]
    }
    puts $file_handle [join $escaped ","]
}

proc stage2_delay::csv_quote {value} {
    set value [string map [list "\r" " " "\n" " "] $value]
    regsub -all {"} $value {""} value
    return "\"$value\""
}

proc stage2_delay::remaining_sdc_text {path} {
    variable consumed_segments

    set fin [open_text $path r]
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
    set from_records $s(from_records)
    set through_records $s(through_records)
    set to_records $s(to_records)
    if {[info exists s(rewrite_from_records)]} {
        set from_records $s(rewrite_from_records)
    }
    if {[info exists s(rewrite_through_records)]} {
        set through_records $s(rewrite_through_records)
    }
    if {[info exists s(rewrite_to_records)]} {
        set to_records $s(rewrite_to_records)
    }
    set signature [list \
        type $s(type) \
        delay [format_delay $s(delay)] \
        from [records_signature $from_records] \
        through [records_signature $through_records] \
        to [records_signature $to_records] \
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
        set top_module [top_name_from_sdc_path $top_sdc]
    }
    set top_module [safe_filename_token $top_module]

    set out_e2e_sdc [file normalize [global_setting OUT_E2E_SDC [file join $out_dir generated_e2e_delay.sdc]]]
    set out_report [file normalize [global_setting OUT_REPORT [file join $out_dir integration_delay_merge.rpt]]]
    set out_removed_sdc [file normalize [global_setting OUT_REMOVED_SDC [file join $out_dir merged_delay_removed.sdc]]]
    set out_review_rpt [file normalize [global_setting OUT_REVIEW_RPT [file join $out_dir unmerged_delay_review.rpt]]]
    set out_final_sdc [file normalize [global_setting OUT_FINAL_SDC [file join $out_dir ${top_module}_flatten.sdc]]]
    set out_summary_dir [file normalize [global_setting OUT_SUMMARY_DIR [file join $out_dir delay_path_summary]]]

    set merge_mode [global_setting MERGE_MODE replace]
    set partial_merge_policy [global_setting PARTIAL_MERGE_POLICY residual_through]
    set unmatched_harden_policy [global_setting UNMATCHED_HARDEN_POLICY review]
    set top_open_from_mode [global_setting TOP_OPEN_FROM_MODE enumerate_static_startpoints]
    set allow_through [global_setting ALLOW_THROUGH false]
    set top_port_boundary_map_mode [global_setting TOP_PORT_BOUNDARY_MAP_MODE connectivity]
    set recursive_chain_mode [global_setting RECURSIVE_CHAIN_MODE auto]
    set max_chain_depth [global_setting MAX_CHAIN_DEPTH 6]
    set max_endpoints [global_setting MAX_ENDPOINTS 1000]
    set max_enum_objects [global_setting MAX_ENUM_OBJECTS 64]
    set verbose_pt_query [global_setting STAGE2_VERBOSE_PT_QUERY true]
    set write_path_summary [global_setting WRITE_PATH_SUMMARY true]
    set text_encoding [global_setting STAGE2_TEXT_ENCODING utf-8]

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
    set_global_setting OUT_SUMMARY_DIR $out_summary_dir
    set_global_setting TOP_MODULE_NAME $top_module
    set_global_setting TOP_OPEN_FROM_MODE $top_open_from_mode
    set_global_setting TOP_PORT_BOUNDARY_MAP_MODE $top_port_boundary_map_mode
    set_global_setting RECURSIVE_CHAIN_MODE $recursive_chain_mode
    set_global_setting MAX_CHAIN_DEPTH $max_chain_depth
    set_global_setting STAGE2_VERBOSE_PT_QUERY $verbose_pt_query
    set_global_setting WRITE_PATH_SUMMARY $write_path_summary
    set_global_setting STAGE2_TEXT_ENCODING $text_encoding

    puts "INFO: Stage 2 script      : [global_setting STAGE2_SCRIPT_FILE run_stage2_merge_delay.tcl]"
    puts "INFO: Run directory       : $run_dir"
    puts "INFO: Top SDC             : $top_sdc"
    puts "INFO: Harden list         : $harden_list"
    puts "INFO: Output E2E SDC      : $out_e2e_sdc"
    puts "INFO: Final flatten SDC   : $out_final_sdc"
    puts "INFO: Path summary dir    : $out_summary_dir"
    puts "INFO: Write path summary  : $write_path_summary"
    puts "INFO: Merge mode          : $merge_mode"
    puts "INFO: Top open_from mode  : $top_open_from_mode"
    puts "INFO: Top port map mode   : $top_port_boundary_map_mode"
    puts "INFO: Recursive mode      : $recursive_chain_mode"
    puts "INFO: Verbose PT query    : $verbose_pt_query"
    puts "INFO: Text encoding       : $text_encoding"

    stage2_delay::build \
        -top_sdc $top_sdc \
        -harden_list $harden_list \
        -out_e2e_sdc $out_e2e_sdc \
        -out_report $out_report \
        -out_removed_sdc $out_removed_sdc \
        -out_review_rpt $out_review_rpt \
        -out_final_sdc $out_final_sdc \
        -out_summary_dir $out_summary_dir \
        -merge_mode $merge_mode \
        -partial_merge_policy $partial_merge_policy \
        -unmatched_harden_policy $unmatched_harden_policy \
        -top_open_from_mode $top_open_from_mode \
        -top_port_boundary_map_mode $top_port_boundary_map_mode \
        -recursive_chain_mode $recursive_chain_mode \
        -max_chain_depth $max_chain_depth \
        -verbose_pt_query $verbose_pt_query \
        -write_path_summary $write_path_summary \
        -text_encoding $text_encoding \
        -allow_through $allow_through \
        -max_endpoints $max_endpoints \
        -max_enum_objects $max_enum_objects

    puts "INFO: Stage 2 complete."
    puts "INFO: Generated E2E SDC   : $out_e2e_sdc"
    puts "INFO: Merge report        : $out_report"
    puts "INFO: Removed constraints : $out_removed_sdc"
    puts "INFO: Review report       : $out_review_rpt"
    puts "INFO: Final flatten SDC   : $out_final_sdc"
    if {[truthy $write_path_summary]} {
        puts "INFO: Path summary CSV    : $out_summary_dir"
    }

    if {[truthy [global_setting STAGE2_POST_CHECK false]]} {
        post_check -e2e_sdc $out_e2e_sdc
    }
}

if {[info exists ::STAGE2_AUTO_RUN] && [stage2_delay::truthy $::STAGE2_AUTO_RUN]} {
    stage2_delay::run_from_user_settings
}
