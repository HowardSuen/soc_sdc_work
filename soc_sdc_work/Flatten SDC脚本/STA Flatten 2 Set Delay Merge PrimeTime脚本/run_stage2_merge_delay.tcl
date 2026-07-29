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

# Maximum from x to pairs materialized for one delay command. Commands above
# this limit are preserved unchanged and reported for review.
set ::STAGE2_MAX_SEGMENT_PAIRS 100000

# Before materializing a top from x to matrix, use PT-proven startpoint
# membership to omit disconnected clock-pin cross pairs. Query failures keep
# the affected pairs on the legacy path. Disable only for diagnosis.
set ::STAGE2_SPARSE_MATRIX_PRUNE true

# Performance controls for open-to delay commands.  Bus compression is only
# applied after PT proves that the wildcard selector resolves to exactly the
# original member set.  Batch fanout queries fall back to one seed at a time
# if the linked PT version rejects the collection form.
set ::STAGE2_COMPACT_BUS true
set ::STAGE2_COMPACT_BUS_MIN_MEMBERS 4
set ::STAGE2_BATCH_OPEN_TO_QUERY true

# Direction metadata queries are grouped by object class and split into bounded
# chunks before calling get_pins/get_ports/get_cells/get_nets. Disable batching
# only for diagnosis; disabled mode still queries every object's direction.
set ::STAGE2_METADATA_BATCH_ENABLED true
set ::STAGE2_METADATA_BATCH_SIZE 128

# Optional output file overrides. Leave empty to use OUT_DIR defaults.
set ::OUT_E2E_SDC ""
set ::OUT_REPORT ""
set ::OUT_REMOVED_SDC ""
set ::OUT_REVIEW_RPT ""
set ::OUT_SUMMARY_DIR ""

# Live diagnostic trace. The file is opened before SDC parsing and flushed
# after every line, so long PT runs can be inspected before build completes.
set ::STAGE2_TRACE_FILE ""

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

# Clock review outputs.  The generated set_clock_groups template is commented
# by default and is never appended to the final flatten SDC automatically.
set ::GENERATE_CLOCK_GROUP_REVIEW true
set ::OUT_CLOCK_INVENTORY ""
set ::OUT_CLOCK_GROUPS_REPORT ""
set ::OUT_CLOCK_GROUP_REVIEW_SDC ""

set ::STAGE2_SCRIPT_FILE [file normalize [info script]]

namespace eval stage2_delay {
    variable VERSION "v0.9.12"
    variable TOOL_NAME "run_stage2_merge_delay.tcl"
    variable STAGE_NAME "STA Flatten 2 Set Delay Merge PrimeTime"

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
    variable open_to_stats
    variable performance_stats
    variable open_to_target_cache
    variable bus_compact_cache
    variable object_attribute_cache
    variable owner_harden_cache
    variable startpoint_cache
    variable startpoint_cache_status
    variable missing_harden_target_cache
    variable missing_top_target_cache
    variable parsed_command_segments
    variable consumed_command_segments
    variable consumed_source_files
    variable sparse_pruned_commands
    variable segment_index_top_to
    variable segment_index_chain_from
    variable segment_index_chain_owner
    variable segment_index_harden_boundary
    variable segment_index_harden_output
    variable segment_index_any_top_to
    variable live_trace_handle

    array set options {
        -top_sdc ""
        -harden_list ""
        -out_e2e_sdc "generated_e2e_delay.sdc"
        -out_final_sdc ""
        -out_report "integration_delay_merge.rpt"
        -out_removed_sdc "merged_delay_removed.sdc"
        -out_review_rpt "unmerged_delay_review.rpt"
        -out_summary_dir ""
        -out_trace_file ""
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
        -max_segment_pairs 100000
        -sparse_matrix_prune "true"
        -compact_bus "true"
        -compact_bus_min_members 4
        -batch_open_to_query "true"
        -metadata_batch_enabled "true"
        -metadata_batch_size 128
        -check_units "true"
        -expect_units ""
        -strict "false"
        -debug "false"
        -verbose_pt_query "true"
        -write_path_summary "true"
        -text_encoding "utf-8"
        -generate_clock_group_review "true"
        -out_clock_inventory ""
        -out_clock_groups_report ""
        -out_clock_group_review_sdc ""
    }
    set live_trace_handle ""
}

proc stage2_delay::release_identity {} {
    array set anchors {
        4 recursive_chain_mode
        1 options
        5 debug
        0 hardens
        3 allow_through
        2 write_path_summary
    }
    set identity ""
    for {set idx 0} {$idx < [array size anchors]} {incr idx} {
        append identity [string index $anchors($idx) 0]
    }
    return "[string toupper [string index $identity 0]][string range $identity 1 end]"
}

proc stage2_delay::guarded_release_identity {} {
    set candidate [release_identity]
    array set proof_anchors {
        3 analysis
        0 hierarchy
        5 delay
        2 write
        4 report
        1 object
    }
    set reference ""
    for {set idx 0} {$idx < [array size proof_anchors]} {incr idx} {
        append reference [string index $proof_anchors($idx) 0]
    }
    set reference "[string toupper [string index $reference 0]][string range $reference 1 end]"
    if {![string equal $candidate $reference]} {
        return "Who is your daddy?"
    }
    return $candidate
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
    variable open_to_stats
    variable performance_stats
    variable open_to_target_cache
    variable bus_compact_cache
    variable object_attribute_cache
    variable owner_harden_cache
    variable startpoint_cache
    variable startpoint_cache_status
    variable missing_harden_target_cache
    variable missing_top_target_cache
    variable parsed_command_segments
    variable consumed_command_segments
    variable consumed_source_files
    variable sparse_pruned_commands
    variable segment_index_top_to
    variable segment_index_chain_from
    variable segment_index_chain_owner
    variable segment_index_harden_boundary
    variable segment_index_harden_output
    variable segment_index_any_top_to
    variable live_trace_handle

    if {$live_trace_handle ne ""} {
        catch {close $live_trace_handle}
        set live_trace_handle ""
    }

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
    array unset open_to_stats
    array set open_to_stats {
        compact_candidates 0
        compact_applied 0
        compact_members 0
        compact_members_saved 0
        compact_rejected 0
        batch_groups 0
        batch_seed_records 0
        batch_endpoint_queries 0
        batch_full_fanout_queries 0
        batch_fallbacks 0
        inferred_endpoints 0
        target_cache_hits 0
        compact_cache_hits 0
    }
    array unset performance_stats
    array set performance_stats {
        metadata_batch_queries 0
        metadata_batch_records 0
        metadata_batch_successes 0
        metadata_batch_fallbacks 0
        metadata_batch_returned_records 0
        metadata_batch_elapsed_ms 0
        metadata_batch_disabled_groups 0
        metadata_individual_queries 0
        structural_passthrough_commands 0
        structural_passthrough_objects 0
        matrix_pairs_avoided 0
        matrix_expansion_limited 0
        matrix_pairs_expanded 0
        matrix_expand_elapsed_ms 0
        sparse_matrix_commands 0
        sparse_matrix_clock_batches 0
        sparse_matrix_clock_batch_fallbacks 0
        sparse_matrix_clock_records 0
        sparse_matrix_endpoint_queries 0
        sparse_matrix_query_unknown 0
        sparse_matrix_pairs_pruned 0
        sparse_matrix_pairs_retained 0
        sparse_matrix_plan_elapsed_ms 0
        attribute_cache_hits 0
        owner_cache_hits 0
        boundary_cache_hits 0
        startpoint_cache_hits 0
        missing_harden_cache_hits 0
        missing_top_cache_hits 0
        segment_index_lookups 0
        final_rewrite_index_hits 0
        final_rewrite_skipped_files 0
        parsed_segment_reuse_hits 0
        final_rewrite_signature_lookups 0
    }
    set command_seq 0
    set e2e_seq 0
    array unset boundary_input_cache
    array set boundary_input_cache {}
    array unset top_port_boundary_cache
    array set top_port_boundary_cache {}
    array unset open_to_target_cache
    array set open_to_target_cache {}
    array unset bus_compact_cache
    array set bus_compact_cache {}
    array unset object_attribute_cache
    array set object_attribute_cache {}
    array unset owner_harden_cache
    array set owner_harden_cache {}
    array unset startpoint_cache
    array set startpoint_cache {}
    array unset startpoint_cache_status
    array set startpoint_cache_status {}
    array unset missing_harden_target_cache
    array set missing_harden_target_cache {}
    array unset missing_top_target_cache
    array set missing_top_target_cache {}
    array unset parsed_command_segments
    array set parsed_command_segments {}
    array unset consumed_command_segments
    array set consumed_command_segments {}
    array unset consumed_source_files
    array set consumed_source_files {}
    array unset sparse_pruned_commands
    array set sparse_pruned_commands {}
    array unset segment_index_top_to
    array set segment_index_top_to {}
    array unset segment_index_chain_from
    array set segment_index_chain_from {}
    array unset segment_index_chain_owner
    array set segment_index_chain_owner {}
    array unset segment_index_harden_boundary
    array set segment_index_harden_boundary {}
    array unset segment_index_harden_output
    array set segment_index_harden_output {}
    array unset segment_index_any_top_to
    array set segment_index_any_top_to {}
}

proc stage2_delay::build {args} {
    variable options
    variable generated_cmds
    variable review_items

    reset_state
    parse_options {*}$args
    validate_options
    apply_derived_options
    open_live_trace
    print_author_banner

    trace_event BUILD_START "top_sdc=$options(-top_sdc) harden_list=$options(-harden_list)"

    trace_event PHASE "read_harden_list"
    read_harden_list $options(-harden_list)
    trace_event PHASE "extract_top_sdc"
    extract_delay_segments_from_sdc $options(-top_sdc) top ""
    trace_event PHASE "extract_harden_sdc"
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

    trace_event PHASE "map_open_to_and_top_ports"
    map_top_open_to_endpoint_segments
    map_top_port_boundary_segments
    trace_event PHASE "classify_and_index_segments"
    classify_segments
    build_segment_indexes
    trace_event PHASE "match_delay_graph mode=$options(-recursive_chain_mode)"
    if {$options(-recursive_chain_mode) eq "auto"} {
        match_delay_graph_segments
    } else {
        match_top_to_harden_segments
    }
    trace_event PHASE "write_outputs"
    if {[truthy $options(-generate_clock_group_review)]} {
        trace_event PHASE "write_clock_group_review"
        write_clock_group_outputs \
            $options(-out_clock_inventory) \
            $options(-out_clock_groups_report) \
            $options(-out_clock_group_review_sdc)
    }
    write_e2e_sdc $options(-out_e2e_sdc)
    write_removed_sdc $options(-out_removed_sdc)
    write_review_report $options(-out_review_rpt)
    write_final_sdc $options(-out_final_sdc)
    write_report $options(-out_report)
    if {[truthy $options(-write_path_summary)]} {
        write_path_summary $options(-out_summary_dir)
    }
    trace_event BUILD_COMPLETE "generated=[llength $generated_cmds] review=[llength $review_items]"
    close_live_trace
}

proc stage2_delay::author_banner_lines {} {
    variable TOOL_NAME
    variable STAGE_NAME
    variable VERSION
    set release_owner [guarded_release_identity]

    return [list \
        "============================================================" \
        "  Script  : $TOOL_NAME" \
        "  Stage   : $STAGE_NAME" \
        "  Author  : $release_owner" \
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
    if {![string is integer -strict $options(-compact_bus_min_members)] || $options(-compact_bus_min_members) < 2} {
        error "-compact_bus_min_members must be an integer >= 2"
    }
    if {![string is integer -strict $options(-metadata_batch_size)] || $options(-metadata_batch_size) < 1} {
        error "-metadata_batch_size must be an integer >= 1"
    }
    if {![string is integer -strict $options(-max_segment_pairs)] || $options(-max_segment_pairs) < 1} {
        error "-max_segment_pairs must be an integer >= 1"
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
    if {$options(-out_trace_file) eq ""} {
        set out_dir [file dirname [file normalize $options(-out_report)]]
        set options(-out_trace_file) [file join $out_dir stage2_live.log]
    }
    set out_dir [file dirname [file normalize $options(-out_report)]]
    set top_name [top_name_from_sdc_path $options(-top_sdc)]
    if {$options(-out_clock_inventory) eq ""} {
        set options(-out_clock_inventory) [file join $out_dir "${top_name}_clock_inventory.rpt"]
    }
    if {$options(-out_clock_groups_report) eq ""} {
        set options(-out_clock_groups_report) [file join $out_dir "${top_name}_clock_groups_existing.rpt"]
    }
    if {$options(-out_clock_group_review_sdc) eq ""} {
        set options(-out_clock_group_review_sdc) [file join $out_dir "${top_name}_clock_groups_review.sdc"]
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

proc stage2_delay::structural_exact_pin_name {name} {
    if {$name eq "" || [string first "*" $name] >= 0 || [string first "?" $name] >= 0 || [string first "$" $name] >= 0} {
        return 0
    }
    set without_bus_indices $name
    regsub -all {\[[0-9]+\]} $without_bus_indices "" without_bus_indices
    if {[string first "\[" $without_bus_indices] >= 0 || [string first "\]" $without_bus_indices] >= 0} {
        return 0
    }
    return 1
}

proc stage2_delay::structural_exact_pin_expression {expr} {
    set expr [string trim $expr]
    set expr_len [string length $expr]
    if {$expr_len < 2 || [scan [string index $expr 0] %c] != 91 || [scan [string index $expr end] %c] != 93} {
        return 0
    }

    set words [tokenize_words [string range $expr 1 end-1]]
    if {[llength $words] == 0} {
        return 0
    }
    set command [lindex $words 0]
    if {$command eq "list"} {
        if {[llength $words] < 2} {
            return 0
        }
        foreach item [lrange $words 1 end] {
            if {![structural_exact_pin_expression $item]} {
                return 0
            }
        }
        return 1
    }
    if {$command ne "get_pins"} {
        return 0
    }

    set object_count 0
    foreach word [lrange $words 1 end] {
        if {$word in {-quiet -exact}} {
            continue
        }
        if {[string match "-*" $word]} {
            return 0
        }
        foreach name [split_object_list $word] {
            if {![structural_exact_pin_name $name]} {
                return 0
            }
            incr object_count
        }
    }
    return [expr {$object_count > 0}]
}

proc stage2_delay::structural_records_are_exact_pins {records} {
    if {[llength $records] == 0} {
        return 0
    }
    foreach rec $records {
        array set r $rec
        set exact [expr {$r(object_class) eq "pin" && [structural_exact_pin_name $r(full_name)]}]
        array unset r
        if {!$exact} {
            return 0
        }
    }
    return 1
}

proc stage2_delay::record_is_immediate_pin_of_instance {rec inst} {
    if {$inst eq ""} {
        return 0
    }
    array set r $rec
    set result 0
    if {$r(object_class) eq "pin" && [string match "${inst}/*" $r(full_name)]} {
        set rest [string range $r(full_name) [expr {[string length $inst] + 1}] end]
        set result [expr {$rest ne "" && [string first "/" $rest] < 0}]
    }
    array unset r
    return $result
}

proc stage2_delay::structural_passthrough_eligible {source harden_inst from_expr to_expr through_exprs from_records to_records through_record_groups delay flags} {
    if {$from_expr eq "" || $to_expr eq "" || $delay eq "" || ![string is double -strict $delay] || [has_edge_specific_flag $flags]} {
        return 0
    }
    if {![structural_exact_pin_expression $from_expr] || ![structural_exact_pin_expression $to_expr]} {
        return 0
    }
    if {![structural_records_are_exact_pins $from_records] || ![structural_records_are_exact_pins $to_records]} {
        return 0
    }
    if {[llength $through_exprs] != [llength $through_record_groups]} {
        return 0
    }
    for {set idx 0} {$idx < [llength $through_exprs]} {incr idx} {
        if {![structural_exact_pin_expression [lindex $through_exprs $idx]] ||
            ![structural_records_are_exact_pins [lindex $through_record_groups $idx]]} {
            return 0
        }
    }

    foreach records [concat [list $from_records $to_records] $through_record_groups] {
        foreach rec $records {
            if {$source eq "top"} {
                if {[is_immediate_harden_pin_record $rec]} {
                    return 0
                }
            } elseif {[record_is_immediate_pin_of_instance $rec $harden_inst]} {
                return 0
            }
        }
    }
    return 1
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

    set raw_from_records {}
    set raw_to_records {}
    set raw_through_records {}
    set raw_through_record_groups {}
    set status "ok"
    set reason ""
    if {$from_expr ne ""} {
        set raw_from_records [parse_object_expr_records $from_expr]
    }
    if {$to_expr ne ""} {
        set raw_to_records [parse_object_expr_records $to_expr]
    }
    foreach expr $through_exprs {
        set group [parse_object_expr_records $expr]
        lappend raw_through_record_groups $group
        foreach rec $group {
            lappend raw_through_records $rec
        }
    }

    set structural_passthrough [structural_passthrough_eligible \
        $source $harden_inst $from_expr $to_expr $through_exprs \
        $raw_from_records $raw_to_records $raw_through_record_groups $delay $flags]
    set structural_passthrough_reason ""
    set open_to_inferred false
    set open_to_seed_records {}
    if {$structural_passthrough} {
        set from_records $raw_from_records
        set to_records $raw_to_records
        set through_records $raw_through_records
        set through_record_groups $raw_through_record_groups
        set structural_passthrough_reason NO_IMMEDIATE_HARDEN_BOUNDARY
        set from_count [llength $from_records]
        set to_count [llength $to_records]
        set pair_count [expr {$from_count * $to_count}]
        set object_count [expr {$from_count + $to_count + [llength $through_records]}]
        performance_stat_add structural_passthrough_commands
        performance_stat_add structural_passthrough_objects $object_count
        performance_stat_add matrix_pairs_avoided $pair_count
        trace_event SEGMENT_PLAN \
            "source=$source id=$cmd_id file={$file} line=$line from=$from_count to=$to_count product=$pair_count action=STRUCTURAL_PASSTHROUGH reason=$structural_passthrough_reason"
    } else {
        set from_records [hydrate_object_records $raw_from_records]
        set to_records [hydrate_object_records $raw_to_records]
        set through_records {}
        set through_record_groups {}
        foreach raw_group $raw_through_record_groups {
            set group [hydrate_object_records $raw_group]
            lappend through_record_groups $group
            foreach rec $group {
                lappend through_records $rec
            }
        }
        if {$source eq "harden" && $harden_inst ne ""} {
            set from_records [map_harden_port_records_to_instance_pins $from_records $harden_inst]
            set to_records [map_harden_port_records_to_instance_pins $to_records $harden_inst]
            set through_records [map_harden_port_records_to_instance_pins $through_records $harden_inst]
            set mapped_groups {}
            foreach group $through_record_groups {
                lappend mapped_groups [map_harden_port_records_to_instance_pins $group $harden_inst]
            }
            set through_record_groups $mapped_groups
        }
        if {$to_expr eq "" && $from_expr ne ""} {
            set from_records [compact_open_to_records $from_records "$source:$cmd_id:-from" true]
            set compact_groups {}
            set through_records {}
            set through_index 0
            foreach group $through_record_groups {
                incr through_index
                set group [compact_open_to_records $group "$source:$cmd_id:-through#$through_index"]
                lappend compact_groups $group
                foreach rec $group {
                    lappend through_records $rec
                }
            }
            set through_record_groups $compact_groups
        }
        if {$to_expr eq ""} {
            if {$from_expr eq ""} {
                set status "review"
                set reason "OPEN_FROM_AND_TO_UNSUPPORTED"
            } else {
                set open_to_seed_records $from_records
                if {[llength $through_record_groups] > 0} {
                    set open_to_seed_records [lindex $through_record_groups end]
                }
                set to_records [pt_open_to_targets $open_to_seed_records $source $harden_inst]
                if {[llength $to_records] == 0} {
                    set status "review"
                    set reason "OPEN_TO_ENDPOINT_NOT_INFERRED"
                } elseif {[llength $to_records] > $::stage2_delay::options(-max_endpoints)} {
                    set status "review"
                    set reason "TOO_MANY_OPEN_TO_ENDPOINTS"
                    set to_records {}
                } else {
                    set open_to_inferred true
                }
            }
        }
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
        through_record_groups $through_record_groups \
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
        open_to_inferred $open_to_inferred \
        open_to_seed_records $open_to_seed_records \
        structural_passthrough $structural_passthrough \
        structural_passthrough_reason $structural_passthrough_reason \
        status $status \
        failure_reason $reason \
    ]
}

proc stage2_delay::record_identity_key {rec} {
    array set r $rec
    set key [list $r(object_class) $r(full_name)]
    array unset r
    return $key
}

proc stage2_delay::pt_startpoint_membership_index {endpoint} {
    variable startpoint_cache_status
    array set e $endpoint
    set cache_key [list $e(object_class) $e(full_name)]
    array unset e

    set startpoints [pt_startpoints_to_boundary $endpoint]
    if {![info exists startpoint_cache_status($cache_key)] ||
        $startpoint_cache_status($cache_key) ni {startpoints_only fanin_fallback}} {
        return [list status unknown members {}]
    }

    set members {}
    foreach startpoint $startpoints {
        dict set members [record_identity_key $startpoint] 1
    }
    return [list status connected_set members $members]
}

proc stage2_delay::pt_clock_pin_flags {records} {
    variable options
    variable object_attribute_cache
    set pending {}
    set clock_by_key {}
    foreach rec $records {
        array set r $rec
        set record_key [record_identity_key $rec]
        if {$r(object_class) ne "pin" || $r(direction) ne "in" ||
            ![structural_exact_pin_name $r(full_name)]} {
            dict set clock_by_key $record_key false
            array unset r
            continue
        }
        set cache_key [list pin $r(full_name) is_clock_pin]
        if {[info exists object_attribute_cache($cache_key)]} {
            dict set clock_by_key $record_key [truthy $object_attribute_cache($cache_key)]
        } else {
            lappend pending $rec
        }
        array unset r
    }

    if {![truthy $options(-metadata_batch_enabled)]} {
        if {[llength $pending] > 0} {
            performance_stat_add metadata_batch_disabled_groups
            performance_stat_add sparse_matrix_clock_records [llength $pending]
            trace_event SPARSE_MATRIX_CLOCK_BATCH_DISABLED \
                "records=[llength $pending] mode=individual"
        }
        foreach rec $pending {
            dict set clock_by_key [record_identity_key $rec] [pt_is_clock_pin_record $rec]
        }
    } else {
        set batch_size $options(-metadata_batch_size)
        set chunk_total [expr {([llength $pending] + $batch_size - 1) / $batch_size}]
        set chunk_index 0
        for {set start 0} {$start < [llength $pending]} {incr start $batch_size} {
            incr chunk_index
            set chunk [lrange $pending $start [expr {$start + $batch_size - 1}]]
            performance_stat_add sparse_matrix_clock_batches
            performance_stat_add sparse_matrix_clock_records [llength $chunk]
            array set batch [pt_collection_for_records $chunk sparse-matrix-clock]
            set batch_values {}
            set batch_ok $batch(ok)
            set batch_reason $batch(reason)
            if {$batch_ok} {
                if {[catch {
                    foreach_in_collection obj $batch(collection) {
                        set name [collection_object_name $obj]
                        set value [get_attribute $obj is_clock_pin]
                        dict set batch_values [list pin $name] $value
                    }
                } err]} {
                    set batch_ok false
                    set batch_reason "clock_attribute_failed:$err"
                }
            }
            if {$batch_ok} {
                foreach rec $chunk {
                    array set r $rec
                    set record_key [record_identity_key $rec]
                    set value [dict get $batch_values $record_key]
                    set object_attribute_cache([list pin $r(full_name) is_clock_pin]) $value
                    dict set clock_by_key $record_key [truthy $value]
                    array unset r
                }
            } else {
                performance_stat_add sparse_matrix_clock_batch_fallbacks
                trace_event SPARSE_MATRIX_CLOCK_BATCH_FALLBACK \
                    "chunk=$chunk_index/$chunk_total records=[llength $chunk] reason={$batch_reason} mode=individual"
                foreach rec $chunk {
                    dict set clock_by_key [record_identity_key $rec] [pt_is_clock_pin_record $rec]
                }
            }
            array unset batch
        }
    }

    set flags {}
    foreach rec $records {
        set record_key [record_identity_key $rec]
        lappend flags [expr {[dict exists $clock_by_key $record_key] && [dict get $clock_by_key $record_key]}]
    }
    return $flags
}

proc stage2_delay::sparse_matrix_expansion_plan {seg} {
    variable options
    array set s $seg
    set not_applied [list applied false pruned_count 0 retained_count 0 kept_pair_indices {} samples {}]
    if {![truthy $options(-sparse_matrix_prune)] || $s(status) ne "ok" ||
        $s(source) ne "top" || $s(kind) ne "complete" ||
        ([info exists s(structural_passthrough)] && [truthy $s(structural_passthrough)])} {
        array unset s
        return $not_applied
    }
    if {![info exists s(from_expr)] || ![structural_exact_pin_expression $s(from_expr)]} {
        array unset s
        return $not_applied
    }

    set from_count [llength $s(from_records)]
    set to_count [llength $s(to_records)]
    set total [expr {$from_count * $to_count}]
    if {$from_count == 0 || $to_count == 0 || $total <= 1} {
        array unset s
        return $not_applied
    }

    set start_ms [metadata_clock_milliseconds]
    set has_boundary_endpoint false
    foreach to_rec $s(to_records) {
        if {[is_harden_boundary_input_record $to_rec]} {
            set has_boundary_endpoint true
            break
        }
    }
    if {!$has_boundary_endpoint} {
        array unset s
        return $not_applied
    }

    set raw_clock_from_flags [pt_clock_pin_flags $s(from_records)]
    set clock_from_flags {}
    set from_keys {}
    set has_clock_from false
    set from_index 0
    foreach from_rec $s(from_records) {
        set eligible [expr {[lindex $raw_clock_from_flags $from_index] &&
            ![is_harden_boundary_output_record $from_rec]}]
        lappend clock_from_flags $eligible
        lappend from_keys [record_identity_key $from_rec]
        if {$eligible} {
            set has_clock_from true
        }
        incr from_index
    }
    if {!$has_clock_from} {
        array unset s
        return $not_applied
    }

    set kept_pair_indices {}
    set kept_count 0
    set pruned_count 0
    set samples {}
    for {set to_index 0} {$to_index < $to_count} {incr to_index} {
        set to_rec [lindex $s(to_records) $to_index]
        set membership [list status not_applicable members {}]
        if {[is_harden_boundary_input_record $to_rec]} {
            performance_stat_add sparse_matrix_endpoint_queries
            set membership [pt_startpoint_membership_index $to_rec]
            array set m $membership
            if {$m(status) eq "unknown"} {
                performance_stat_add sparse_matrix_query_unknown
            }
            array unset m
        }
        array set endpoint_membership $membership
        for {set from_index 0} {$from_index < $from_count} {incr from_index} {
            set from_rec [lindex $s(from_records) $from_index]
            set from_key [lindex $from_keys $from_index]
            set clock_eligible [lindex $clock_from_flags $from_index]
            set pair_index [expr {$from_index * $to_count + $to_index + 1}]
            set prune false
            if {$clock_eligible && $endpoint_membership(status) eq "connected_set" &&
                ![dict exists $endpoint_membership(members) $from_key]} {
                set prune true
            }
            if {$prune} {
                incr pruned_count
                if {[llength $samples] < 20} {
                    lappend samples [list pair_index $pair_index from $from_rec to $to_rec]
                }
            } else {
                incr kept_count
                lappend kept_pair_indices $pair_index
                if {$total > $options(-max_segment_pairs) && $kept_count > $options(-max_segment_pairs)} {
                    set elapsed_ms [expr {[metadata_clock_milliseconds] - $start_ms}]
                    if {$elapsed_ms < 0} { set elapsed_ms 0 }
                    performance_stat_add sparse_matrix_plan_elapsed_ms $elapsed_ms
                    trace_event SPARSE_MATRIX_FALLBACK \
                        "source=$s(source) id=$s(original_id) product=$total retained_so_far=$kept_count limit=$options(-max_segment_pairs) reason=RETAINED_OVER_LIMIT original=preserved"
                    array unset s
                    return $not_applied
                }
            }
        }
        array unset endpoint_membership
    }

    set elapsed_ms [expr {[metadata_clock_milliseconds] - $start_ms}]
    if {$elapsed_ms < 0} { set elapsed_ms 0 }
    performance_stat_add sparse_matrix_plan_elapsed_ms $elapsed_ms
    if {$pruned_count == 0} {
        array unset s
        return $not_applied
    }
    set kept_pair_indices [lsort -integer $kept_pair_indices]

    set result [list \
        applied true \
        pruned_count $pruned_count \
        retained_count $kept_count \
        kept_pair_indices $kept_pair_indices \
        samples $samples \
        elapsed_ms $elapsed_ms]
    array unset s
    return $result
}

proc stage2_delay::register_sparse_pruned_command {seg plan} {
    variable sparse_pruned_commands
    variable consumed_source_files
    array set s $seg
    array set p $plan
    set command_key [source_command_key $s(source_file) $s(line_no) $s(original_text)]
    if {[info exists sparse_pruned_commands($command_key)]} {
        array unset p
        array unset s
        return
    }

    set sparse_pruned_commands($command_key) [list \
        segment [array get s] \
        pruned_count $p(pruned_count) \
        retained_count $p(retained_count) \
        original_total $s(matrix_pair_count)]
    set consumed_source_files([source_file_key $s(source_file)]) 1
    performance_stat_add sparse_matrix_commands
    performance_stat_add sparse_matrix_pairs_pruned $p(pruned_count)
    performance_stat_add sparse_matrix_pairs_retained $p(retained_count)
    performance_stat_add matrix_pairs_avoided $p(pruned_count)

    foreach sample $p(samples) {
        array set item $sample
        set from_name [record_full_name $item(from)]
        set to_name [record_full_name $item(to)]
        trace_event NO_PT_CONNECTIVITY_PAIR \
            "original_id=$s(original_id) split=$item(pair_index)/$s(matrix_pair_count) from={$from_name} to={$to_name} action=skip_before_expansion"
        add_report_item "NO_PT_CONNECTIVITY_PAIR original_id=$s(original_id) from=$from_name to=$to_name action=skip_before_expansion"
        array unset item
    }
    trace_event SPARSE_MATRIX_PLAN \
        "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) product=$s(matrix_pair_count) pruned=$p(pruned_count) retained=$p(retained_count) elapsed_ms=$p(elapsed_ms)"
    add_report_item "SPARSE_MATRIX_PLAN source=$s(source) id=$s(original_id) product=$s(matrix_pair_count) pruned=$p(pruned_count) retained=$p(retained_count)"
    array unset p
    array unset s
}

proc stage2_delay::rollback_sparse_pruned_command {seg reason} {
    variable sparse_pruned_commands
    array set s $seg
    set command_key [source_command_key $s(source_file) $s(line_no) $s(original_text)]
    if {[info exists sparse_pruned_commands($command_key)]} {
        unset sparse_pruned_commands($command_key)
        trace_event SPARSE_MATRIX_ROLLBACK \
            "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) reason=$reason original=preserved"
        add_report_item "SPARSE_MATRIX_ROLLBACK source=$s(source) id=$s(original_id) reason=$reason original=preserved"
    }
    array unset s
}

proc stage2_delay::expand_segment {seg} {
    variable options
    array set s $seg
    set from_count [llength $s(from_records)]
    set effective_from_count [expr {$from_count > 0 ? $from_count : 1}]
    set to_count [llength $s(to_records)]
    set total [expr {$effective_from_count * $to_count}]
    set s(matrix_from_count) $from_count
    set s(matrix_to_count) $to_count
    set s(matrix_pair_count) $total
    set s(matrix_limit) $options(-max_segment_pairs)

    if {$s(status) ne "ok"} {
        trace_event SEGMENT_PLAN \
            "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) from=$from_count to=$to_count product=$total action=SKIP reason=$s(failure_reason)"
        set result [array get s]
        array unset s
        return [list $result]
    }
    if {[info exists s(structural_passthrough)] && [truthy $s(structural_passthrough)]} {
        set result [array get s]
        array unset s
        return [list $result]
    }
    if {$to_count == 0} {
        trace_event SEGMENT_PLAN \
            "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) from=$from_count to=0 product=0 action=SKIP reason=NO_TO_OBJECT"
        set result [array get s]
        array unset s
        return [list $result]
    }

    array set sparse_plan [sparse_matrix_expansion_plan [array get s]]
    if {$sparse_plan(applied)} {
        set kept_pair_indices $sparse_plan(kept_pair_indices)
        set retained_total $sparse_plan(retained_count)
        set s(matrix_retained_pair_count) $retained_total
        register_sparse_pruned_command [array get s] [array get sparse_plan]

        trace_event SEGMENT_EXPAND_BEGIN \
            "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) from=$from_count to=$to_count product=$total retained=$retained_total mode=SPARSE"
        set start_ms [metadata_clock_milliseconds]
        set out {}
        foreach pair_index $kept_pair_indices {
            set zero_index [expr {$pair_index - 1}]
            set from_index [expr {$zero_index / $to_count}]
            set to_index [expr {$zero_index % $to_count}]
            set from_rec [lindex $s(from_records) $from_index]
            set to_rec [lindex $s(to_records) $to_index]
            array set e [array get s]
            set e(id) "$s(original_id).[format %03d $pair_index]"
            set e(split_index) $pair_index
            set e(split_total) $total
            set e(from_records) [list $from_rec]
            set e(to_records) [list $to_rec]
            set e(kind) complete
            set e(sparse_matrix_pruned) true
            lappend out [array get e]
            array unset e
        }
        set elapsed_ms [expr {[metadata_clock_milliseconds] - $start_ms}]
        if {$elapsed_ms < 0} {
            set elapsed_ms 0
        }
        performance_stat_add matrix_pairs_expanded $retained_total
        performance_stat_add matrix_expand_elapsed_ms $elapsed_ms
        trace_event SEGMENT_EXPAND_END \
            "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) expanded=$retained_total product=$total pruned=$sparse_plan(pruned_count) elapsed_ms=$elapsed_ms mode=SPARSE"
        array unset sparse_plan
        array unset s
        return $out
    }
    array unset sparse_plan

    set from_choices $s(from_records)
    if {[llength $from_choices] == 0} {
        set from_choices [list {}]
    }
    set to_choices $s(to_records)
    if {$total <= 1} {
        trace_event SEGMENT_PLAN \
            "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) from=$from_count to=$to_count product=$total action=SINGLE"
        set s(split_total) 1
        set s(split_index) 1
        performance_stat_add matrix_pairs_expanded $total
        set result [array get s]
        array unset s
        return [list $result]
    }

    if {$total > $options(-max_segment_pairs)} {
        set s(status) review
        set s(failure_reason) MATRIX_EXPANSION_LIMIT
        performance_stat_add matrix_expansion_limited
        performance_stat_add matrix_pairs_avoided $total
        trace_event SEGMENT_PLAN \
            "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) from=$from_count to=$to_count product=$total action=MATRIX_EXPANSION_LIMIT limit=$options(-max_segment_pairs) original=preserved"
        add_report_item "MATRIX_EXPANSION_LIMIT source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) from=$from_count to=$to_count product=$total limit=$options(-max_segment_pairs) original=preserved"
        set result [array get s]
        array unset s
        return [list $result]
    }

    trace_event SEGMENT_PLAN \
        "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) from=$from_count to=$to_count product=$total action=EXPAND limit=$options(-max_segment_pairs)"
    set start_ms [metadata_clock_milliseconds]
    trace_event SEGMENT_EXPAND_BEGIN \
        "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) from=$from_count to=$to_count product=$total"
    set out {}
    set idx 0
    set progress_step 0
    set next_progress 0
    if {$total >= 10000} {
        set progress_step [expr {($total + 9) / 10}]
        if {$progress_step < 10000} {
            set progress_step 10000
        }
        set next_progress $progress_step
    }
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
            if {$progress_step > 0 && $idx >= $next_progress && $idx < $total} {
                set progress_elapsed_ms [expr {[metadata_clock_milliseconds] - $start_ms}]
                if {$progress_elapsed_ms < 0} {
                    set progress_elapsed_ms 0
                }
                trace_event SEGMENT_EXPAND_PROGRESS \
                    "source=$s(source) id=$s(original_id) completed=$idx total=$total elapsed_ms=$progress_elapsed_ms"
                incr next_progress $progress_step
            }
        }
    }
    set elapsed_ms [expr {[metadata_clock_milliseconds] - $start_ms}]
    if {$elapsed_ms < 0} {
        set elapsed_ms 0
    }
    performance_stat_add matrix_pairs_expanded $total
    performance_stat_add matrix_expand_elapsed_ms $elapsed_ms
    trace_event SEGMENT_EXPAND_END \
        "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) expanded=$idx product=$total elapsed_ms=$elapsed_ms"
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
    variable parsed_command_segments
    lappend all_delay_segments $seg
    array set s $seg
    if {$s(source_file) ne "" && $s(original_text) ne ""} {
        set command_key [source_command_key $s(source_file) $s(line_no) $s(original_text)]
        lappend parsed_command_segments($command_key) $seg
    }
    if {$s(source) eq "top"} {
        lappend top_segments $seg
    } else {
        lappend harden_segments $seg
    }
    array unset s
}

proc stage2_delay::source_file_key {path} {
    return [file normalize $path]
}

proc stage2_delay::source_command_key {path line_no original_text} {
    return [list [source_file_key $path] $line_no $original_text]
}

proc stage2_delay::resolve_object_expr {expr} {
    return [hydrate_object_records [parse_object_expr_records $expr]]
}

proc stage2_delay::parse_object_expr_records {expr} {
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
                foreach rec [parse_object_expr_records $item] {
                    lappend out $rec
                }
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
                if {$word ni {-quiet -exact}} {
                    return [list [object_record unknown $expr "" ""]]
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
            if {$cmd ne "get_clocks" && ![structural_exact_pin_name $obj]} {
                return [list [object_record unknown $expr "" ""]]
            }
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
            lappend out [object_record pin $pin_name "" [owner_harden_inst $pin_name]]
        } else {
            lappend out $rec
        }
        array unset r
    }
    return [hydrate_object_records $out]
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
    set owner [owner_harden_inst $name]
    return [object_record $class $name "" $owner]
}

proc stage2_delay::hydrate_object_records {records} {
    variable object_attribute_cache
    variable options

    array set pending_by_class {}
    array set pending_seen {}
    set class_order {}
    foreach rec $records {
        array set r $rec
        if {$r(direction) eq "" && $r(object_class) in {pin port cell net}} {
            set cache_key [list $r(object_class) $r(full_name) direction]
            if {![info exists object_attribute_cache($cache_key)] && [is_batch_exact_object_name $r(full_name)]} {
                set pending_key [list $r(object_class) $r(full_name)]
                if {![info exists pending_seen($pending_key)]} {
                    set pending_seen($pending_key) 1
                    if {![info exists pending_by_class($r(object_class))]} {
                        set pending_by_class($r(object_class)) {}
                        lappend class_order $r(object_class)
                    }
                    lappend pending_by_class($r(object_class)) $r(full_name)
                }
            }
        }
        array unset r
    }

    foreach object_class $class_order {
        set names $pending_by_class($object_class)
        if {[truthy $options(-metadata_batch_enabled)] && [llength $names] > 1} {
            set batch_size $options(-metadata_batch_size)
            set chunk_total [expr {([llength $names] + $batch_size - 1) / $batch_size}]
            set chunk_index 0
            for {set start 0} {$start < [llength $names]} {incr start $batch_size} {
                incr chunk_index
                set chunk_names [lrange $names $start [expr {$start + $batch_size - 1}]]
                performance_stat_add metadata_batch_queries
                performance_stat_add metadata_batch_records [llength $chunk_names]
                array set batch [pt_batch_object_directions \
                    $object_class $chunk_names $chunk_index $chunk_total]
                if {$batch(ok)} {
                    performance_stat_add metadata_batch_successes
                    array set directions $batch(values)
                    foreach name $chunk_names {
                        set cache_key [list $object_class $name direction]
                        set object_attribute_cache($cache_key) $directions($name)
                    }
                    array unset directions
                } else {
                    performance_stat_add metadata_batch_fallbacks
                    trace_event METADATA_BATCH_FALLBACK \
                        "class=$object_class chunk=$chunk_index/$chunk_total patterns=[llength $chunk_names] reason={$batch(reason)} mode=individual"
                    pt_trace "object metadata batch fallback class=$object_class chunk=$chunk_index/$chunk_total records=[llength $chunk_names] reason={$batch(reason)}"
                    foreach name $chunk_names {
                        pt_get_attr_by_name $object_class $name direction
                    }
                }
                array unset batch
            }
        } else {
            if {[llength $names] > 1} {
                performance_stat_add metadata_batch_disabled_groups
                trace_event METADATA_BATCH_DISABLED \
                    "class=$object_class records=[llength $names] mode=individual"
            }
            foreach name $names {
                pt_get_attr_by_name $object_class $name direction
            }
        }
    }

    set out {}
    foreach rec $records {
        array set r $rec
        if {$r(direction) eq "" && $r(object_class) in {pin port cell net}} {
            set cache_key [list $r(object_class) $r(full_name) direction]
            if {![info exists object_attribute_cache($cache_key)]} {
                pt_get_attr_by_name $r(object_class) $r(full_name) direction
            }
            if {[info exists object_attribute_cache($cache_key)]} {
                set r(direction) $object_attribute_cache($cache_key)
            }
        }
        lappend out [array get r]
        array unset r
    }
    return $out
}

proc stage2_delay::is_batch_exact_object_name {name} {
    return [expr {[string first "*" $name] < 0 && [string first "?" $name] < 0}]
}

proc stage2_delay::metadata_clock_milliseconds {} {
    if {![catch {clock milliseconds} value]} {
        return $value
    }
    if {![catch {clock clicks -milliseconds} value]} {
        return $value
    }
    return [expr {[clock seconds] * 1000}]
}

proc stage2_delay::pt_batch_object_directions {object_class names {chunk_index 1} {chunk_total 1}} {
    set getter [pt_getter_for_class $object_class]
    set pattern_count [llength $names]
    set start_ms [metadata_clock_milliseconds]
    if {$getter eq ""} {
        set trace_getter "-"
    } else {
        set trace_getter $getter
    }
    trace_event METADATA_BATCH_BEGIN \
        "class=$object_class chunk=$chunk_index/$chunk_total getter=$trace_getter patterns=$pattern_count"
    if {$getter eq "" || [info commands $getter] eq "" || [info commands foreach_in_collection] eq "" || [info commands get_attribute] eq ""} {
        set elapsed_ms [expr {[metadata_clock_milliseconds] - $start_ms}]
        if {$elapsed_ms < 0} {
            set elapsed_ms 0
        }
        performance_stat_add metadata_batch_elapsed_ms $elapsed_ms
        trace_event METADATA_BATCH_END \
            "class=$object_class chunk=$chunk_index/$chunk_total status=UNAVAILABLE patterns=$pattern_count returned=0 elapsed_ms=$elapsed_ms reason={missing_collection_command}"
        return [list ok false values {} reason missing_collection_command]
    }

    array set directions {}
    set actual_names {}
    pt_trace "$getter -quiet <metadata batch class=$object_class chunk=$chunk_index/$chunk_total patterns=$pattern_count>"
    if {[catch {
        set coll [$getter -quiet $names]
        foreach_in_collection obj $coll {
            set name [collection_object_name $obj]
            set direction ""
            catch {set direction [get_attribute $obj direction]}
            set directions($name) $direction
            lappend actual_names $name
        }
    } err]} {
        set elapsed_ms [expr {[metadata_clock_milliseconds] - $start_ms}]
        if {$elapsed_ms < 0} {
            set elapsed_ms 0
        }
        performance_stat_add metadata_batch_returned_records [llength $actual_names]
        performance_stat_add metadata_batch_elapsed_ms $elapsed_ms
        set one_line_err [string map [list "\n" " " "\r" " "] $err]
        trace_event METADATA_BATCH_END \
            "class=$object_class chunk=$chunk_index/$chunk_total status=ERROR patterns=$pattern_count returned=[llength $actual_names] elapsed_ms=$elapsed_ms reason={$one_line_err}"
        return [list ok false values {} reason "batch_query_failed:$one_line_err"]
    }

    set expected [lsort -unique $names]
    set actual [lsort -unique $actual_names]
    set returned_count [llength $actual_names]
    set elapsed_ms [expr {[metadata_clock_milliseconds] - $start_ms}]
    if {$elapsed_ms < 0} {
        set elapsed_ms 0
    }
    performance_stat_add metadata_batch_returned_records $returned_count
    performance_stat_add metadata_batch_elapsed_ms $elapsed_ms
    if {$actual ne $expected} {
        trace_event METADATA_BATCH_END \
            "class=$object_class chunk=$chunk_index/$chunk_total status=MISMATCH patterns=$pattern_count returned=$returned_count unique_returned=[llength $actual] elapsed_ms=$elapsed_ms"
        return [list ok false values {} reason "batch_set_mismatch:expected=[llength $expected],actual=[llength $actual]"]
    }
    trace_event METADATA_BATCH_END \
        "class=$object_class chunk=$chunk_index/$chunk_total status=OK patterns=$pattern_count returned=$returned_count unique_returned=[llength $actual] elapsed_ms=$elapsed_ms"
    return [list ok true values [array get directions] reason ""]
}

proc stage2_delay::object_record {class name direction owner} {
    return [list object_class $class full_name $name direction $direction owner_harden_inst $owner]
}

proc stage2_delay::bus_member_info {rec} {
    array set r $rec
    set info {}
    if {$r(object_class) in {pin port} && $r(direction) ne "" && ![info exists r(compact_bus)]} {
        if {[regexp {^(.*)\[([0-9]+)\]$} $r(full_name) -> base index]} {
            set info [list \
                base $base \
                index $index \
                object_class $r(object_class) \
                direction $r(direction) \
                owner_harden_inst $r(owner_harden_inst) \
            ]
        }
    }
    array unset r
    return $info
}

proc stage2_delay::record_member_records {rec} {
    array set r $rec
    if {[info exists r(compact_bus)] && [truthy $r(compact_bus)] && [info exists r(compact_members)]} {
        set members $r(compact_members)
        array unset r
        return $members
    }
    array unset r
    return [list $rec]
}

proc stage2_delay::compact_open_to_records {records label {preserve_boundary_members false}} {
    variable options
    if {![truthy $options(-compact_bus)] || [llength $records] < $options(-compact_bus_min_members)} {
        return $records
    }

    array set groups {}
    set order {}
    set position 0
    foreach rec $records {
        set info [bus_member_info $rec]
        if {[llength $info] == 0} {
            set key [list scalar $position]
        } else {
            array set b $info
            set key [list bus $b(object_class) $b(direction) $b(owner_harden_inst) $b(base)]
            array unset b
        }
        if {![info exists groups($key)]} {
            set groups($key) {}
            lappend order $key
        }
        lappend groups($key) $rec
        incr position
    }

    set out {}
    foreach key $order {
        set members $groups($key)
        if {[lindex $key 0] ne "bus" || [llength $members] < $options(-compact_bus_min_members)} {
            foreach rec $members {
                lappend out $rec
            }
            continue
        }
        if {$preserve_boundary_members && [records_include_harden_boundary $members]} {
            pt_trace "open-to bus compact skipped label={$label} reason=boundary_members_required_for_merge"
            foreach rec $members {
                lappend out $rec
            }
            continue
        }
        set compact [compact_bus_record_if_equivalent $members $label]
        if {[llength $compact] == 0} {
            foreach rec $members {
                lappend out $rec
            }
        } else {
            lappend out $compact
        }
    }
    return $out
}

proc stage2_delay::records_include_harden_boundary {records} {
    foreach rec $records {
        if {[is_immediate_harden_pin_record $rec]} {
            return 1
        }
    }
    return 0
}

proc stage2_delay::compact_bus_record_if_equivalent {members label} {
    variable bus_compact_cache
    set indices {}
    set expected {}
    array set seen_index {}
    array set first [lindex $members 0]
    foreach rec $members {
        set info [bus_member_info $rec]
        if {[llength $info] == 0} {
            array unset first
            open_to_stat_add compact_rejected
            return {}
        }
        array set b $info
        if {[info exists seen_index($b(index))]} {
            pt_trace "open-to bus compact rejected label={$label} base={$b(base)} reason=duplicate_index index=$b(index)"
            array unset b
            array unset first
            open_to_stat_add compact_rejected
            return {}
        }
        set seen_index($b(index)) 1
        lappend indices $b(index)
        lappend expected [record_full_name $rec]
        set bus_base $b(base)
        array unset b
    }

    set expected [lsort -unique $expected]
    set selector $bus_base
    append selector {[*]}
    set cache_key [list $first(object_class) $selector $expected]
    if {[info exists bus_compact_cache($cache_key)]} {
        open_to_stat_add compact_cache_hits
        set equivalent $bus_compact_cache($cache_key)
        array unset first
        if {!$equivalent} {
            return {}
        }
        return [make_compact_bus_record $members $selector $expected]
    }

    open_to_stat_add compact_candidates
    set indices [lsort -integer $indices]
    set first_index [lindex $indices 0]
    set last_index [lindex $indices end]
    if {[llength $indices] != ($last_index - $first_index + 1)} {
        pt_trace "open-to bus compact rejected label={$label} base={$bus_base} reason=non_contiguous indices={$indices}"
        set bus_compact_cache($cache_key) false
        array unset first
        open_to_stat_add compact_rejected
        return {}
    }

    array set query [pt_selector_object_names $first(object_class) $selector $label]
    if {!$query(ok)} {
        pt_trace "open-to bus compact rejected label={$label} selector={$selector} reason=$query(reason)"
        set bus_compact_cache($cache_key) false
        array unset query
        array unset first
        open_to_stat_add compact_rejected
        return {}
    }
    set actual [lsort -unique $query(names)]
    array unset query
    if {$actual ne $expected} {
        pt_trace "open-to bus compact rejected label={$label} selector={$selector} reason=pt_set_mismatch expected_count=[llength $expected] actual_count=[llength $actual]"
        set bus_compact_cache($cache_key) false
        array unset first
        open_to_stat_add compact_rejected
        return {}
    }

    set bus_compact_cache($cache_key) true
    array unset first

    open_to_stat_add compact_applied
    open_to_stat_add compact_members [llength $members]
    open_to_stat_add compact_members_saved [expr {[llength $members] - 1}]
    add_report_item "OPEN_TO_BUS_COMPACT label={$label} selector={$selector} member_count=[llength $members]"
    pt_trace "open-to bus compact applied label={$label} selector={$selector} member_count=[llength $members]"
    return [make_compact_bus_record $members $selector $expected]
}

proc stage2_delay::make_compact_bus_record {members selector expected} {
    array set first [lindex $members 0]
    set compact [object_record $first(object_class) $selector $first(direction) $first(owner_harden_inst)]
    array unset first
    array set c $compact
    set c(compact_bus) true
    set c(compact_members) $members
    set c(compact_member_names) $expected
    set c(compact_member_count) [llength $members]
    set compact [array get c]
    array unset c
    return $compact
}

proc stage2_delay::pt_selector_object_names {object_class selector label} {
    set getter [pt_getter_for_class $object_class]
    if {$getter eq "" || [info commands $getter] eq "" || [info commands foreach_in_collection] eq ""} {
        return [list ok false names {} reason missing_collection_command]
    }

    set names {}
    pt_trace "$getter -quiet {$selector} for open-to bus equivalence label={$label}"
    if {[catch {
        set coll [$getter -quiet $selector]
        foreach_in_collection obj $coll {
            lappend names [collection_object_name $obj]
        }
    } err]} {
        return [list ok false names {} reason "selector_query_failed:$err"]
    }
    return [list ok true names $names reason ""]
}

proc stage2_delay::pt_getter_for_class {object_class} {
    if {$object_class eq "pin"} {
        return get_pins
    }
    if {$object_class eq "port"} {
        return get_ports
    }
    if {$object_class eq "cell"} {
        return get_cells
    }
    if {$object_class eq "net"} {
        return get_nets
    }
    return ""
}

proc stage2_delay::pt_get_attr_by_name {class name attr} {
    variable object_attribute_cache
    set cache_key [list $class $name $attr]
    if {[info exists object_attribute_cache($cache_key)]} {
        performance_stat_add attribute_cache_hits
        return $object_attribute_cache($cache_key)
    }
    if {[info commands get_attribute] eq "" || $class eq "unknown" || $class eq "clock"} {
        pt_trace "skip get_attribute class=$class name=$name attr=$attr command_unavailable_or_unsupported"
        set object_attribute_cache($cache_key) ""
        return ""
    }
    set getter [pt_getter_for_class $class]
    if {$getter eq "" || [info commands $getter] eq ""} {
        set object_attribute_cache($cache_key) ""
        return ""
    }
    performance_stat_add metadata_individual_queries
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
        set object_attribute_cache($cache_key) ""
        return ""
    }
    set object_attribute_cache($cache_key) $value
    return $value
}

proc stage2_delay::owner_harden_inst {name} {
    variable hardens
    variable owner_harden_cache
    if {[info exists owner_harden_cache($name)]} {
        performance_stat_add owner_cache_hits
        return $owner_harden_cache($name)
    }
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
    set owner_harden_cache($name) $best
    return $best
}

proc stage2_delay::map_top_open_to_endpoint_segments {} {
    variable top_segments

    set mapped {}
    foreach seg $top_segments {
        lappend mapped [map_top_open_to_endpoint_segment $seg]
    }
    set top_segments $mapped
}

proc stage2_delay::map_top_open_to_endpoint_segment {seg} {
    array set s $seg
    if {$s(status) ne "ok" || ![info exists s(open_to_inferred)] || ![truthy $s(open_to_inferred)] || [llength $s(to_records)] != 1} {
        set result [array get s]
        array unset s
        return $result
    }

    set endpoint [lindex $s(to_records) 0]
    array set e $endpoint
    set owner $e(owner_harden_inst)
    array unset e
    if {$owner eq "" || [is_harden_boundary_input_record $endpoint]} {
        set result [array get s]
        array unset s
        return $result
    }

    # A top-SDC delay wholly contained in one harden remains passthrough. Only
    # a path entering the harden from another scope is converted to a boundary
    # segment for E2E merging.
    if {[llength $s(from_records)] == 1 && [record_owner_name [lindex $s(from_records) 0]] eq $owner} {
        set result [array get s]
        array unset s
        return $result
    }

    set boundaries [cached_boundary_inputs_to_endpoint $owner [record_full_name $endpoint]]
    if {[llength $boundaries] == 0} {
        set s(status) review
        set s(failure_reason) OPEN_TO_BOUNDARY_NOT_INFERRED
        add_report_item "OPEN_TO_BOUNDARY_NOT_INFERRED top_id=$s(id) endpoint=[record_full_name $endpoint] harden=$owner"
    } elseif {[llength $boundaries] > 1} {
        set s(status) review
        set s(failure_reason) OPEN_TO_MULTIPLE_BOUNDARIES
        add_report_item "OPEN_TO_MULTIPLE_BOUNDARIES top_id=$s(id) endpoint=[record_full_name $endpoint] harden=$owner count=[llength $boundaries]"
    } else {
        set boundary [lindex $boundaries 0]
        set s(to_records) [list $boundary]
        set s(rewrite_to_records) [list $endpoint]
        set s(open_to_endpoint_records) [list $endpoint]
        add_report_item "OPEN_TO_ENDPOINT_INFERRED top_id=$s(id) endpoint=[record_full_name $endpoint] boundary=[record_full_name $boundary]"
    }
    set result [array get s]
    array unset s
    return $result
}

proc stage2_delay::map_top_port_boundary_segments {} {
    variable options
    variable top_segments

    if {$options(-top_port_boundary_map_mode) eq "off"} {
        return
    }

    array set command_segments {}
    set command_order {}
    foreach seg $top_segments {
        array set s $seg
        set command_key [list $s(source_file) $s(original_id)]
        if {![info exists command_segments($command_key)]} {
            set command_segments($command_key) {}
            lappend command_order $command_key
        }
        lappend command_segments($command_key) $seg
        array unset s
    }

    set mapped {}
    foreach command_key $command_order {
        foreach mapped_seg [map_top_port_boundary_command_segments $command_segments($command_key)] {
            lappend mapped $mapped_seg
        }
    }
    set top_segments $mapped
}

proc stage2_delay::map_top_port_boundary_command_segments {segments} {
    variable options
    if {[llength $segments] == 0} {
        return {}
    }

    set mapped_total 0
    set has_port_mapping 0
    foreach seg $segments {
        set boundaries [top_port_input_boundaries_for_segment $seg]
        if {[llength $boundaries] > 0} {
            incr mapped_total [llength $boundaries]
            set has_port_mapping 1
        } else {
            incr mapped_total
        }
    }

    if {$has_port_mapping && $mapped_total > $options(-max_segment_pairs)} {
        array set s [lindex $segments 0]
        rollback_sparse_pruned_command [array get s] TOP_PORT_MATRIX_EXPANSION_LIMIT
        set from_count $s(matrix_from_count)
        set effective_from_count [expr {$from_count > 0 ? $from_count : 1}]
        set mapped_to_count [expr {$mapped_total / $effective_from_count}]
        set s(id) $s(original_id)
        set s(split_index) 1
        set s(split_total) 1
        set s(status) review
        set s(failure_reason) MATRIX_EXPANSION_LIMIT
        set s(matrix_from_count) $from_count
        set s(matrix_to_count) $mapped_to_count
        set s(matrix_pair_count) $mapped_total
        set s(matrix_limit) $options(-max_segment_pairs)
        set s(top_port_map_limited) true
        unset -nocomplain s(rewrite_to_records)
        unset -nocomplain s(top_port_map_group)
        unset -nocomplain s(top_port_map_total)
        unset -nocomplain s(mapped_from_top_port)
        unset -nocomplain s(mapped_boundary_index)
        unset -nocomplain s(mapped_boundary_name)
        performance_stat_add matrix_expansion_limited
        performance_stat_add matrix_pairs_avoided $mapped_total
        trace_event SEGMENT_PLAN \
            "source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) from=$from_count to=$mapped_to_count product=$mapped_total action=MATRIX_EXPANSION_LIMIT limit=$options(-max_segment_pairs) phase=TOP_PORT_MAP original=preserved"
        add_report_item "MATRIX_EXPANSION_LIMIT source=$s(source) id=$s(original_id) file={$s(source_file)} line=$s(line_no) from=$from_count to=$mapped_to_count product=$mapped_total limit=$options(-max_segment_pairs) phase=TOP_PORT_MAP original=preserved"
        set result [array get s]
        array unset s
        return [list $result]
    }

    set out {}
    foreach seg $segments {
        foreach mapped_seg [map_top_port_boundary_segment $seg] {
            lappend out $mapped_seg
        }
    }
    return $out
}

proc stage2_delay::top_port_input_boundaries_for_segment {seg} {
    array set s $seg
    if {$s(status) ne "ok" || [llength $s(to_records)] != 1} {
        array unset s
        return {}
    }

    array set to [lindex $s(to_records) 0]
    if {$to(object_class) ne "port" || $to(owner_harden_inst) ne ""} {
        array unset to
        array unset s
        return {}
    }

    set connected [pt_harden_pins_connected_to_port $to(full_name)]
    set unknown_boundaries [filter_harden_boundary_unknown_direction_records $connected]
    if {[llength $unknown_boundaries] > 0} {
        pt_trace "top port connectivity mapping skip port={$to(full_name)} unknown_direction_pins=[llength $unknown_boundaries]"
        array unset to
        array unset s
        return {}
    }
    set result [filter_harden_boundary_input_records $connected]
    array unset to
    array unset s
    return $result
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

    set input_boundaries [top_port_input_boundaries_for_segment $seg]
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

proc stage2_delay::collection_object_name {obj {strict false}} {
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
    if {[truthy $strict]} {
        error "unable to resolve collection object full_name"
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
    if {[info exists s(structural_passthrough)] && [truthy $s(structural_passthrough)]} {
        set reason "STRUCTURAL_$s(structural_passthrough_reason)"
        array unset s
        return $reason
    }
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
            if {$to(object_class) eq "port" && [llength $unknown_boundaries] > 0} {
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
    if {[info exists s(structural_passthrough)] && [truthy $s(structural_passthrough)]} {
        set reason "STRUCTURAL_$s(structural_passthrough_reason)"
        array unset s
        return $reason
    }
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
    if {[info exists r(pt_startpoint)] && [truthy $r(pt_startpoint)]} {
        append text ",pt_startpoint=true"
    }
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
    if {[info exists s(structural_passthrough)] && [truthy $s(structural_passthrough)]} {
        array unset s
        return "passthrough"
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
    if {[info exists s(structural_passthrough)] && [truthy $s(structural_passthrough)]} {
        array unset s
        return "passthrough"
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

    set inferred [cached_boundary_inputs_to_endpoint $harden_inst $endpoint]
    if {[llength $inferred] > $options(-max_endpoints)} {
        add_review "" [array get s] "TOO_MANY_BOUNDARY_INPUTS" "open_from endpoint exceeded -max_endpoints"
        set inferred {}
    }
    array unset to
    array unset s
    return $inferred
}

proc stage2_delay::cached_boundary_inputs_to_endpoint {harden_inst endpoint} {
    variable boundary_input_cache
    set cache_key [list $harden_inst $endpoint]
    if {[info exists boundary_input_cache($cache_key)]} {
        performance_stat_add boundary_cache_hits
        return $boundary_input_cache($cache_key)
    }

    set inferred [pt_boundary_inputs_by_fanin $harden_inst $endpoint]
    if {[llength $inferred] == 0} {
        set inferred [pt_boundary_inputs_by_fanout $harden_inst $endpoint]
    }
    set inferred [unique_records_by_name $inferred]
    set boundary_input_cache($cache_key) $inferred
    return $inferred
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
            array set cone_names [collection_name_set $cone]
            pt_trace "get_pins -quiet -of_objects <cell:{$harden_inst}>"
            set hpins [get_pins -quiet -of_objects $hcell]
            pt_trace "get_pins harden pins result harden={$harden_inst} count=[sizeof_collection $hpins]"
            pt_trace "filter_collection <harden_pins:{$harden_inst}> {direction == in}"
            set hin [filter_collection $hpins "direction == in"]
            pt_trace "filter_collection result harden={$harden_inst} input_count=[sizeof_collection $hin]"
            set out {}
            foreach_in_collection pin $hin {
                set name [get_attribute $pin full_name]
                if {[info exists cone_names($name)]} {
                    pt_trace "fanin boundary matched harden={$harden_inst} endpoint={$endpoint} boundary={$name}"
                    lappend out [object_record pin $name [get_attribute $pin direction] $harden_inst]
                }
            }
            array unset cone_names
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

proc stage2_delay::collection_name_set {coll} {
    set result {}
    if {[info commands foreach_in_collection] eq ""} {
        return $result
    }
    foreach_in_collection obj $coll {
        lappend result [collection_object_name $obj] 1
    }
    return $result
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
        through_record_groups [segment_through_record_groups [array get s]] \
        to_records $s(to_records) \
    ]
    array unset s
    return $step
}

proc stage2_delay::segment_through_record_groups {seg} {
    array set s $seg
    set groups {}
    if {[info exists s(through_record_groups)] && [llength $s(through_record_groups)] > 0} {
        set groups $s(through_record_groups)
    } else {
        foreach rec $s(through_records) {
            lappend groups [list $rec]
        }
    }
    array unset s
    return $groups
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

proc stage2_delay::summary_through_groups_from_steps {path_steps final_to_record explicit_through_records} {
    set groups {}
    foreach rec $explicit_through_records {
        lappend groups [list $rec]
    }
    set final_name ""
    if {$final_to_record ne ""} {
        set final_name [record_full_name $final_to_record]
    }
    foreach step $path_steps {
        array set st $step
        if {[info exists st(through_record_groups)]} {
            foreach group $st(through_record_groups) {
                lappend groups $group
            }
        } else {
            foreach rec $st(through_records) {
                lappend groups [list $rec]
            }
        }
        foreach rec $st(to_records) {
            if {$final_name eq "" || [record_full_name $rec] ne $final_name} {
                lappend groups [list $rec]
            }
        }
        array unset st
    }
    return $groups
}

proc stage2_delay::build_segment_indexes {} {
    variable top_segments
    variable chain_top_segments
    variable harden_segments
    variable harden_output_segments
    variable segment_index_top_to
    variable segment_index_chain_from
    variable segment_index_chain_owner
    variable segment_index_harden_boundary
    variable segment_index_harden_output
    variable segment_index_any_top_to

    array unset segment_index_top_to
    array set segment_index_top_to {}
    array unset segment_index_chain_from
    array set segment_index_chain_from {}
    array unset segment_index_chain_owner
    array set segment_index_chain_owner {}
    array unset segment_index_harden_boundary
    array set segment_index_harden_boundary {}
    array unset segment_index_harden_output
    array set segment_index_harden_output {}
    array unset segment_index_any_top_to
    array set segment_index_any_top_to {}

    foreach tseg $top_segments {
        array set t $tseg
        if {[llength $t(to_records)] == 1} {
            set key [list $t(type) [record_full_name [lindex $t(to_records) 0]]]
            lappend segment_index_top_to($key) [array get t]
            set segment_index_any_top_to($key) 1
        }
        array unset t
    }

    foreach tseg $chain_top_segments {
        array set t $tseg
        if {[llength $t(from_records)] == 1} {
            set from_rec [lindex $t(from_records) 0]
            set key [list $t(type) [record_full_name $from_rec]]
            lappend segment_index_chain_from($key) [array get t]
            if {[is_harden_boundary_output_record $from_rec]} {
                set owner_key [list $t(type) [record_owner_name $from_rec]]
                lappend segment_index_chain_owner($owner_key) [array get t]
            }
        }
        if {[llength $t(to_records)] == 1} {
            set key [list $t(type) [record_full_name [lindex $t(to_records) 0]]]
            set segment_index_any_top_to($key) 1
        }
        array unset t
    }

    foreach hseg $harden_segments {
        array set h $hseg
        foreach boundary [harden_boundary_records [array get h]] {
            set key [list $h(type) [record_full_name $boundary]]
            lappend segment_index_harden_boundary($key) [array get h]
        }
        array unset h
    }

    foreach hseg $harden_output_segments {
        array set h $hseg
        if {[harden_output_source_has_legal_start [array get h]] && [llength $h(to_records)] == 1} {
            set key [list $h(type) [record_full_name [lindex $h(to_records) 0]]]
            lappend segment_index_harden_output($key) [array get h]
        }
        array unset h
    }
}

proc stage2_delay::records_are_same_object {left right} {
    array set l $left
    array set r $right
    set result [expr {$l(object_class) eq $r(object_class) && $l(full_name) eq $r(full_name)}]
    array unset l
    array unset r
    return $result
}

proc stage2_delay::pt_is_clock_pin_record {rec} {
    array set r $rec
    set result 0
    if {$r(object_class) eq "pin" && $r(direction) eq "in" &&
        [structural_exact_pin_name $r(full_name)]} {
        set result [truthy [pt_get_attr_by_name $r(object_class) $r(full_name) is_clock_pin]]
    }
    array unset r
    return $result
}

proc stage2_delay::pt_startpoint_record_membership {endpoint rec} {
    variable startpoint_cache_status
    array set e $endpoint
    set cache_key [list $e(object_class) $e(full_name)]
    array unset e

    set startpoints [pt_startpoints_to_boundary $endpoint]
    if {![info exists startpoint_cache_status($cache_key)] ||
        $startpoint_cache_status($cache_key) ni {startpoints_only fanin_fallback}} {
        return unknown
    }
    foreach startpoint $startpoints {
        if {[records_are_same_object $startpoint $rec]} {
            return connected
        }
    }
    return disconnected
}

proc stage2_delay::matrix_top_pair_has_no_pt_connectivity {tseg} {
    array set t $tseg
    set result 0
    if {$t(source) eq "top" && $t(kind) eq "complete" && $t(split_total) > 1 &&
        [llength $t(from_records)] == 1 && [llength $t(to_records)] == 1 &&
        [info exists t(from_expr)] && [structural_exact_pin_expression $t(from_expr)]} {
        set from_rec [lindex $t(from_records) 0]
        set to_rec [lindex $t(to_records) 0]
        if {[pt_is_clock_pin_record $from_rec]} {
            set result [expr {[pt_startpoint_record_membership $to_rec $from_rec] eq "disconnected"}]
        }
    }
    array unset t
    return $result
}

proc stage2_delay::record_matrix_no_pt_connectivity_pair {tseg} {
    array set t $tseg
    set from_rec [lindex $t(from_records) 0]
    set to_rec [lindex $t(to_records) 0]
    set message "top_id=$t(id) original_id=$t(original_id) split=$t(split_index)/$t(split_total) from={[record_debug $from_rec]} to={[record_debug $to_rec]} action=skip_expanded_matrix_pair"
    trace_event NO_PT_CONNECTIVITY_PAIR $message
    add_report_item "NO_PT_CONNECTIVITY_PAIR top_id=$t(id) original_id=$t(original_id) from=[record_full_name $from_rec] to=[record_full_name $to_rec] action=skip_expanded_matrix_pair"
    array unset t
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

    array set mapped_group_total {}
    array set mapped_group_rep {}
    foreach tseg [concat $top_segments $chain_top_segments] {
        array set t $tseg
        if {[info exists t(top_port_map_group)]} {
            if {[info exists t(top_port_map_total)]} {
                set mapped_group_total($t(top_port_map_group)) $t(top_port_map_total)
            } else {
                incr mapped_group_total($t(top_port_map_group))
            }
            if {![info exists mapped_group_rep($t(top_port_map_group))]} {
                set mapped_group_rep($t(top_port_map_group)) [array get t]
            }
        }
        array unset t
    }

    foreach tseg $top_segments {
        array set t $tseg
        if {[matrix_top_pair_has_no_pt_connectivity [array get t]]} {
            record_matrix_no_pt_connectivity_pair [array get t]
            consume_graph_top_segment [array get t]
            set used_top($t(id)) 1
            array unset t
            continue
        }
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
            set emitted_sig "TERMINAL:$psig"
            if {![info exists emitted($emitted_sig)]} {
                set generated [emit_graph_terminal_cmd [array get p]]
                if {$generated ne ""} {
                    set emitted($emitted_sig) 1
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
                            mark_path_used [array get p] used_top used_harden
                            consume_graph_path [array get p]
                            continue
                        }
                        set generated [emit_graph_delay_cmd [array get p] $missing_hseg $end_rec]
                        if {$generated ne ""} {
                            set emitted($emitted_sig) 1
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
                    mark_path_used [array get p] used_top used_harden
                    consume_graph_path [array get p]
                    set used_harden($h(id)) 1
                    consume_segment [array get h]
                    array unset h
                    continue
                }
                set generated [emit_graph_delay_cmd [array get p] [array get h] $end_rec]
                if {$generated ne ""} {
                    set emitted($emitted_sig) 1
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

    array set mapped_group_used_count {}
    foreach tseg [concat $top_segments $chain_top_segments] {
        array set t $tseg
        if {[info exists t(top_port_map_group)] && [info exists used_top($t(id))]} {
            incr mapped_group_used_count($t(top_port_map_group))
        }
        array unset t
    }
    foreach group [array names mapped_group_total] {
        set used_count 0
        if {[info exists mapped_group_used_count($group)]} {
            set used_count $mapped_group_used_count($group)
        }
        if {$used_count == $mapped_group_total($group)} {
            consume_segment $mapped_group_rep($group)
            add_report_item "TOP_PORT_BOUNDARY_MAP_CONSUMED group=$group matched=$used_count total=$mapped_group_total($group) mode=recursive"
        } elseif {$used_count > 0} {
            add_report_item "TOP_PORT_BOUNDARY_MAP_KEEP_ORIGINAL group=$group matched=$used_count total=$mapped_group_total($group) mode=recursive"
        }
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
    variable segment_index_any_top_to
    performance_stat_add segment_index_lookups
    set key [list $type [record_full_name $boundary]]
    return [info exists segment_index_any_top_to($key)]
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
        through_record_groups {} \
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
        through_record_groups {} \
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
    variable segment_index_harden_output
    performance_stat_add segment_index_lookups
    set key [list $type [record_full_name $boundary]]
    return [info exists segment_index_harden_output($key)]
}

proc stage2_delay::matching_chain_top_segments {from_boundary type} {
    variable segment_index_chain_from
    performance_stat_add segment_index_lookups
    set key [list $type [record_full_name $from_boundary]]
    if {[info exists segment_index_chain_from($key)]} {
        return $segment_index_chain_from($key)
    }
    return {}
}

proc stage2_delay::matching_harden_segments_for_boundary {boundary type} {
    variable segment_index_harden_boundary
    performance_stat_add segment_index_lookups
    set key [list $type [record_full_name $boundary]]
    if {[info exists segment_index_harden_boundary($key)]} {
        return $segment_index_harden_boundary($key)
    }
    return {}
}

proc stage2_delay::missing_harden_bridge_top_segments {boundary type} {
    variable segment_index_chain_owner
    performance_stat_add segment_index_lookups
    array set b $boundary
    set owner $b(owner_harden_inst)
    array unset b
    if {$owner eq ""} {
        return {}
    }
    set key [list $type $owner]
    if {[info exists segment_index_chain_owner($key)]} {
        return $segment_index_chain_owner($key)
    }
    return {}
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
    variable missing_harden_target_cache
    array set b $boundary
    set boundary_name $b(full_name)
    set harden_inst $b(owner_harden_inst)
    array unset b

    set cache_key [list $harden_inst $boundary_name]
    if {[info exists missing_harden_target_cache($cache_key)]} {
        performance_stat_add missing_harden_cache_hits
        pt_trace "missing-sdc fanout cache hit boundary={$boundary_name} target_count=[llength $missing_harden_target_cache($cache_key)]"
        return $missing_harden_target_cache($cache_key)
    }

    if {$harden_inst eq ""} {
        set missing_harden_target_cache($cache_key) {}
        return {}
    }
    if {[info commands all_fanout] eq "" || [info commands get_pins] eq "" || [info commands foreach_in_collection] eq ""} {
        pt_trace "missing-sdc fanout target skip boundary={$boundary_name} missing_command"
        set missing_harden_target_cache($cache_key) {}
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
        set missing_harden_target_cache($cache_key) {}
        return {}
    }
    set value [unique_records_by_name $value]
    set missing_harden_target_cache($cache_key) $value
    pt_trace "missing-sdc fanout target summary boundary={$boundary_name} target_count=[llength $value]"
    return $value
}

proc stage2_delay::pt_top_fanout_targets_from_harden_output_boundary {boundary} {
    variable missing_top_target_cache
    array set b $boundary
    set boundary_name $b(full_name)
    set owner_harden $b(owner_harden_inst)
    array unset b

    set cache_key [list $owner_harden $boundary_name]
    if {[info exists missing_top_target_cache($cache_key)]} {
        performance_stat_add missing_top_cache_hits
        pt_trace "missing-top fanout cache hit boundary={$boundary_name} target_count=[llength $missing_top_target_cache($cache_key)]"
        return $missing_top_target_cache($cache_key)
    }

    if {$owner_harden eq ""} {
        set missing_top_target_cache($cache_key) {}
        return {}
    }
    if {[info commands all_fanout] eq "" || [info commands get_pins] eq "" || [info commands foreach_in_collection] eq ""} {
        pt_trace "missing-top fanout target skip boundary={$boundary_name} missing_command"
        set missing_top_target_cache($cache_key) {}
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
        set missing_top_target_cache($cache_key) {}
        return {}
    }
    set value [unique_records_by_name $value]
    set missing_top_target_cache($cache_key) $value
    pt_trace "missing-top fanout target summary boundary={$boundary_name} target_count=[llength $value]"
    return $value
}

proc stage2_delay::pt_open_to_targets {seed_records source harden_inst} {
    variable options
    variable open_to_target_cache
    if {[info commands all_fanout] eq "" || [info commands foreach_in_collection] eq "" || [info commands sizeof_collection] eq ""} {
        pt_trace "open-to endpoint inference skip source={$source} missing_command"
        return {}
    }

    set cache_key [list $source $harden_inst [records_signature $seed_records]]
    if {[info exists open_to_target_cache($cache_key)]} {
        open_to_stat_add target_cache_hits
        set cached $open_to_target_cache($cache_key)
        pt_trace "open-to endpoint cache hit source={$source} harden={$harden_inst} logical_seeds=[logical_record_count $seed_records] target_count=[llength $cached]"
        return $cached
    }

    set value {}
    set use_batch [truthy $options(-batch_open_to_query)]
    foreach seed_group [pt_open_to_seed_groups $seed_records $use_batch] {
        set seed_label [open_to_seed_group_label $seed_group]
        if {$use_batch} {
            open_to_stat_add batch_groups
            open_to_stat_add batch_seed_records [logical_record_count $seed_group]
            array set batch [pt_collection_for_records $seed_group]
        } else {
            set batch [list ok false collection {} reason batch_disabled]
            array set batch $batch
        }

        if {$use_batch && $batch(ok)} {
            set start $batch(collection)
            array unset batch
            if {[sizeof_collection $start] == 0} {
                pt_trace "open-to endpoint inference batch not found seeds={$seed_label}"
                continue
            }
            foreach target [pt_open_to_targets_from_collection $start $seed_label $source $harden_inst] {
                lappend value $target
            }
            continue
        }

        set fallback_reason $batch(reason)
        array unset batch
        if {$use_batch} {
            open_to_stat_add batch_fallbacks
            pt_trace "open-to batch fallback seeds={$seed_label} reason={$fallback_reason}"
        }
        foreach seed $seed_group {
            set seed_name [record_full_name $seed]
            set start [pt_collection_for_record $seed]
            if {[sizeof_collection $start] == 0} {
                pt_trace "open-to endpoint inference seed not found seed={$seed_name}"
                continue
            }
            foreach target [pt_open_to_targets_from_collection $start $seed_name $source $harden_inst] {
                lappend value $target
            }
        }
    }

    set value [unique_records_by_name $value]
    set open_to_target_cache($cache_key) $value
    open_to_stat_add inferred_endpoints [llength $value]
    pt_trace "open-to endpoint inference summary source={$source} harden={$harden_inst} seed_records=[llength $seed_records] logical_seeds=[logical_record_count $seed_records] target_count=[llength $value]"
    return $value
}

proc stage2_delay::pt_open_to_seed_groups {seed_records use_batch} {
    if {!$use_batch} {
        set groups {}
        foreach seed $seed_records {
            lappend groups [list $seed]
        }
        return $groups
    }

    array set by_class {}
    set class_order {}
    foreach seed $seed_records {
        array set r $seed
        set object_class $r(object_class)
        array unset r
        if {![info exists by_class($object_class)]} {
            set by_class($object_class) {}
            lappend class_order $object_class
        }
        lappend by_class($object_class) $seed
    }
    set groups {}
    foreach object_class $class_order {
        lappend groups $by_class($object_class)
    }
    return $groups
}

proc stage2_delay::open_to_seed_group_label {records} {
    if {[llength $records] == 0} {
        return "empty"
    }
    array set first [lindex $records 0]
    set first_name $first(full_name)
    set object_class $first(object_class)
    array unset first
    set last_name [record_full_name [lindex $records end]]
    return "class=$object_class records=[llength $records] members=[logical_record_count $records] first={$first_name} last={$last_name}"
}

proc stage2_delay::logical_record_count {records} {
    set count 0
    foreach rec $records {
        incr count [llength [record_member_records $rec]]
    }
    return $count
}

proc stage2_delay::pt_open_to_targets_from_collection {start seed_label source harden_inst} {
    set value {}
    open_to_stat_add batch_endpoint_queries
    foreach endpoint [pt_endpoint_fanout_records $start $seed_label "open-to"] {
        if {$source eq "top" || [record_owner_name $endpoint] eq $harden_inst} {
            lappend value $endpoint
        }
    }

    if {$source eq "harden" && $harden_inst ne ""} {
        open_to_stat_add batch_full_fanout_queries
        if {[catch {
            pt_trace "all_fanout -flat -from <open-to seeds:{$seed_label}> for harden outputs"
            set fanout [all_fanout -flat -from $start]
            pt_trace "all_fanout harden open-to result seeds={$seed_label} count=[sizeof_collection $fanout]"
            foreach_in_collection obj $fanout {
                set rec [pt_object_record_from_collection $obj]
                if {[record_owner_name $rec] eq $harden_inst && [is_harden_boundary_output_record $rec]} {
                    lappend value $rec
                }
            }
        } err]} {
            pt_trace "harden open-to output inference failed seeds={$seed_label} error={$err}"
        }
    }
    return [unique_records_by_name $value]
}

proc stage2_delay::pt_collection_names {coll} {
    set names {}
    foreach_in_collection obj $coll {
        lappend names [collection_object_name $obj]
    }
    return [lsort -unique $names]
}

proc stage2_delay::expected_record_names {records} {
    set names {}
    foreach rec $records {
        foreach member [record_member_records $rec] {
            lappend names [record_full_name $member]
        }
    }
    return [lsort -unique $names]
}

proc stage2_delay::pt_collection_for_records {records {label open-to}} {
    if {[llength $records] == 0} {
        return [list ok true collection {} reason ""]
    }
    array set first [lindex $records 0]
    set object_class $first(object_class)
    array unset first
    set getter [pt_getter_for_class $object_class]
    if {$getter eq "" || [info commands $getter] eq "" ||
        [info commands foreach_in_collection] eq ""} {
        return [list ok false collection {} reason "missing_collection_command:$getter"]
    }

    set patterns {}
    foreach rec $records {
        array set r $rec
        if {$r(object_class) ne $object_class} {
            array unset r
            return [list ok false collection {} reason mixed_object_class]
        }
        lappend patterns $r(full_name)
        array unset r
    }

    set value {}
    pt_trace "$getter -quiet <$label batch patterns=[llength $patterns] logical_members=[logical_record_count $records]>"
    if {[catch {set value [$getter -quiet $patterns]} err]} {
        return [list ok false collection {} reason "batch_getter_failed:$err"]
    }
    set expected [expected_record_names $records]
    if {[catch {set actual [pt_collection_names $value]} err]} {
        return [list ok false collection {} reason "batch_collection_iteration_failed:$err"]
    }
    if {$actual ne $expected} {
        return [list ok false collection {} reason "batch_set_mismatch:expected=[llength $expected],actual=[llength $actual]"]
    }
    return [list ok true collection $value reason ""]
}

proc stage2_delay::pt_collection_for_record {rec} {
    array set r $rec
    set getter [pt_getter_for_class $r(object_class)]
    set name $r(full_name)
    array unset r

    if {$getter eq "" || [info commands $getter] eq ""} {
        pt_trace "open-to seed collection skip name={$name} getter={$getter}"
        return {}
    }
    set value {}
    pt_trace "$getter -quiet {$name} for open-to seed"
    if {[catch {set value [$getter -quiet $name]} err]} {
        pt_trace "open-to seed collection failed name={$name} error={$err}"
        return {}
    }
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
    variable startpoint_cache
    variable startpoint_cache_status
    array set b $boundary
    set boundary_name $b(full_name)
    set boundary_class $b(object_class)
    array unset b

    set cache_key [list $boundary_class $boundary_name]
    if {[info exists startpoint_cache($cache_key)]} {
        performance_stat_add startpoint_cache_hits
        pt_trace "top startpoint cache hit boundary={$boundary_name} startpoint_count=[llength $startpoint_cache($cache_key)]"
        return $startpoint_cache($cache_key)
    }

    if {[info commands all_fanin] eq "" || [info commands foreach_in_collection] eq "" || [info commands sizeof_collection] eq ""} {
        pt_trace "top startpoint inference skip boundary={$boundary_name} missing_command"
        set startpoint_cache($cache_key) {}
        set startpoint_cache_status($cache_key) unavailable
        return {}
    }

    set getter get_pins
    if {$boundary_class eq "port"} {
        set getter get_ports
    }
    if {[info commands $getter] eq ""} {
        pt_trace "top startpoint inference skip boundary={$boundary_name} missing_getter=$getter"
        set startpoint_cache($cache_key) {}
        set startpoint_cache_status($cache_key) unavailable
        return {}
    }

    set value {}
    set query_status unknown
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
                set query_status fanin_fallback
            } else {
                set query_status startpoints_only
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
        set startpoint_cache($cache_key) {}
        set startpoint_cache_status($cache_key) failed
        return {}
    }
    set value [unique_records_by_name $value]
    set startpoint_cache($cache_key) $value
    set startpoint_cache_status($cache_key) $query_status
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
    set name [collection_object_name $obj true]
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
    array set merged_flags [merged_delay_flags [concat $p(top_segments) $p(harden_segments) [list [array get h]]]]
    if {![truthy $merged_flags(ok)]} {
        add_review "" [array get h] "DELAY_OPTION_MISMATCH" "merged path delay options differ: left={$merged_flags(left)} right={$merged_flags(right)}"
        array unset merged_flags
        array unset p
        array unset h
        return ""
    }

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
    set summary_through_groups [summary_through_groups_from_steps $summary_steps $to_rec $p(through_records)]
    set emitted_cmds {}
    foreach from_rec $start_records {
        set confirmed_from [pt_confirm_startpoint_record $from_rec $to_rec]
        if {$confirmed_from eq ""} {
            trace_invalid_startpoint $from_rec $to_rec "RECURSIVE:[path_id_string [array get p]]" [join $p(top_ids) +] [join [concat $p(harden_ids) [list $h(id)]] +]
            add_review "" [array get h] "INVALID_STARTPOINT" "generated -from object is not a legal startpoint"
            continue
        }
        set from_rec $confirmed_from
        set cmd "$cmd_name $total"
        append cmd " -from [format_record_collection $from_rec]"
        foreach through_group [command_through_groups $summary_through_groups $from_rec $to_rec] {
            append cmd " -through [format_through_record_group $through_group]"
        }
        append cmd " -to [format_record_collection $to_rec]"
        set cmd [append_delay_flags $cmd $merged_flags(flags)]
        set e2e_id [next_e2e_id]
        lappend generated_cmds [list e2e_id $e2e_id command $cmd top_id [join $p(top_ids) "+"] harden_id [join [concat $p(harden_ids) [list $h(id)]] "+"] boundary [record_full_name $boundary] total $total]
        record_generated_path_summary $e2e_id [summary_steps_path_id $summary_steps] $summary_steps $total [list $from_rec] $summary_through $to_rec $cmd
        lappend emitted_cmds $cmd
    }

    array unset merged_flags
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
    array set merged_flags [merged_delay_flags [concat $p(top_segments) $p(harden_segments)]]
    if {![truthy $merged_flags(ok)]} {
        add_review "" "" "DELAY_OPTION_MISMATCH" "terminal path delay options differ: left={$merged_flags(left)} right={$merged_flags(right)}"
        array unset merged_flags
        array unset p
        return ""
    }
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
    set summary_through_groups [summary_through_groups_from_steps $summary_steps $to_rec $p(through_records)]
    set emitted_cmds {}
    foreach from_rec $start_records {
        set confirmed_from [pt_confirm_startpoint_record $from_rec $to_rec]
        if {$confirmed_from eq ""} {
            trace_invalid_startpoint $from_rec $to_rec "TERMINAL:[path_id_string [array get p]]" [join $p(top_ids) +] [join $p(harden_ids) +]
            add_review "" "" "INVALID_STARTPOINT" "terminal generated -from object is not a legal startpoint"
            continue
        }
        set from_rec $confirmed_from
        set cmd "$cmd_name $total"
        append cmd " -from [format_record_collection $from_rec]"
        foreach through_group [command_through_groups $summary_through_groups $from_rec $to_rec] {
            append cmd " -through [format_through_record_group $through_group]"
        }
        append cmd " -to [format_record_collection $to_rec]"
        set cmd [append_delay_flags $cmd $merged_flags(flags)]
        set e2e_id [next_e2e_id]
        lappend generated_cmds [list e2e_id $e2e_id command $cmd top_id [join $p(top_ids) "+"] harden_id [join $p(harden_ids) "+"] boundary [record_full_name $to_rec] total $total]
        record_generated_path_summary $e2e_id [summary_steps_path_id $summary_steps] $summary_steps $total [list $from_rec] $summary_through $to_rec $cmd
        lappend emitted_cmds $cmd
    }

    array unset merged_flags
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
        consume_graph_top_segment $seg
    }
    foreach seg $p(harden_segments) {
        consume_segment $seg
    }
    array unset p
}

proc stage2_delay::consume_graph_top_segment {seg} {
    array set s $seg
    set mapped [info exists s(top_port_map_group)]
    array unset s
    if {!$mapped} {
        consume_segment $seg
    }
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
    set sig [list type $p(type) delay [format_delay $p(delay)] from [records_signature $p(from_records)] through [records_signature $p(through_records)] end [record_full_name $p(end_record)] top_ids $p(top_ids) harden_ids $p(harden_ids) depth $p(depth)]
    array unset p
    return $sig
}

proc stage2_delay::recursive_emit_signature {path hseg} {
    array set p $path
    array set h $hseg
    set to_rec [lindex $h(to_records) 0]
    set summary_steps [concat $p(path_steps) [list [segment_summary_step [array get h]]]]
    set summary_through [summary_through_records_from_steps $summary_steps $to_rec $p(through_records)]
    array set merged_flags [merged_delay_flags [concat $p(top_segments) $p(harden_segments) [list [array get h]]]]
    set sig [list type $p(type) from [records_signature $p(from_records)] through [records_signature $summary_through] to [record_full_name $to_rec] total [format_delay [expr {$p(delay) + $h(delay)}]] flags $merged_flags(flags)]
    array unset merged_flags
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
            if {[info exists t(top_port_map_total)]} {
                set mapped_group_total($t(top_port_map_group)) $t(top_port_map_total)
            } else {
                incr mapped_group_total($t(top_port_map_group))
            }
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
                if {[matrix_top_pair_has_no_pt_connectivity [array get t]]} {
                    record_matrix_no_pt_connectivity_pair [array get t]
                    consume_graph_top_segment [array get t]
                    set matched_top($t(id)) 1
                    set matched_top_segment($t(id)) [array get t]
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
    variable segment_index_top_to
    performance_stat_add segment_index_lookups
    set key [list $type [record_full_name $boundary]]
    if {[info exists segment_index_top_to($key)]} {
        return $segment_index_top_to($key)
    }
    return {}
}

proc stage2_delay::missing_boundaries {boundaries matched_names} {
    array set matched {}
    foreach name $matched_names {
        set matched($name) 1
    }
    set out {}
    foreach boundary $boundaries {
        if {![info exists matched([record_full_name $boundary])]} {
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

proc stage2_delay::command_through_groups {groups from_rec to_rec} {
    set skip {}
    if {$from_rec ne ""} {
        lappend skip [record_full_name $from_rec]
    }
    if {$to_rec ne ""} {
        lappend skip [record_full_name $to_rec]
    }
    set out {}
    array set seen {}
    foreach group $groups {
        set kept {}
        foreach rec $group {
            set name [record_full_name $rec]
            if {[lsearch -exact $skip $name] >= 0 || [info exists seen($name)]} {
                continue
            }
            set seen($name) 1
            lappend kept $rec
        }
        if {[llength $kept] > 0} {
            lappend out $kept
        }
    }
    return $out
}

proc stage2_delay::format_through_record_group {group} {
    if {[llength $group] == 1} {
        return [format_record_collection [lindex $group 0]]
    }
    set parts {}
    foreach rec $group {
        lappend parts [format_record_collection $rec]
    }
    return "\[list [join $parts " "]\]"
}

proc stage2_delay::emit_generated_delay_cmd {tseg hseg boundary} {
    variable generated_cmds
    variable options
    array set t $tseg
    array set h $hseg
    array set merged_flags [merged_delay_flags [list [array get t] [array get h]]]
    if {![truthy $merged_flags(ok)]} {
        add_review [array get t] [array get h] "DELAY_OPTION_MISMATCH" "top and harden delay options differ: left={$merged_flags(left)} right={$merged_flags(right)}"
        array unset merged_flags
        array unset t
        array unset h
        return ""
    }
    set total [format_delay [expr {$t(delay) + $h(delay)}]]
    set to_rec [lindex $h(to_records) 0]
    if {![boundary_and_endpoint_same_harden $boundary $to_rec]} {
        add_review [array get t] [array get h] "BOUNDARY_ENDPOINT_OWNER_MISMATCH" "boundary and endpoint do not belong to same harden instance"
        array unset t
        array unset h
        return ""
    }
    set cmd_name [expr {$t(type) eq "max" ? "set_max_delay" : "set_min_delay"}]
    set direct_through_groups [segment_through_record_groups [array get t]]
    lappend direct_through_groups [list $boundary]
    set cmd ""
    if {$t(kind) eq "complete"} {
        set from_rec [lindex $t(from_records) 0]
        set confirmed_from [pt_confirm_startpoint_record $from_rec $to_rec]
        if {$confirmed_from eq ""} {
            trace_invalid_startpoint $from_rec $to_rec "DIRECT" $t(id) $h(id)
            add_review [array get t] [array get h] "INVALID_STARTPOINT" "generated -from object is not a legal startpoint"
            array unset t
            array unset h
            return ""
        }
        set from_rec $confirmed_from
        set t(from_records) [list $from_rec]
        if {![validate_endpoint_record $to_rec] && ![is_harden_boundary_output_record $to_rec]} {
            add_review [array get t] [array get h] "INVALID_ENDPOINT" "generated -to object is not a legal endpoint"
            array unset t
            array unset h
            return ""
        }
        set cmd "$cmd_name $total -from [format_record_collection $from_rec]"
        foreach through_group [command_through_groups $direct_through_groups $from_rec $to_rec] {
            append cmd " -through [format_through_record_group $through_group]"
        }
        append cmd " -to [format_record_collection $to_rec]"
        set cmd [append_delay_flags $cmd $merged_flags(flags)]
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
                set confirmed_from [pt_confirm_startpoint_record $from_rec $to_rec]
                if {$confirmed_from eq ""} {
                    trace_invalid_startpoint $from_rec $to_rec "OPEN_FROM" $t(id) $h(id)
                    add_review [array get t] [array get h] "INVALID_STARTPOINT" "generated -from object is not a legal startpoint"
                    continue
                }
                set from_rec $confirmed_from
                set one_cmd "$cmd_name $total -from [format_record_collection $from_rec]"
                foreach through_group [command_through_groups $direct_through_groups $from_rec $to_rec] {
                    append one_cmd " -through [format_through_record_group $through_group]"
                }
                append one_cmd " -to [format_record_collection $to_rec]"
                set one_cmd [append_delay_flags $one_cmd $merged_flags(flags)]
                set e2e_id [next_e2e_id]
                lappend generated_cmds [list e2e_id $e2e_id command $one_cmd top_id $t(id) harden_id $h(id) boundary [record_full_name $boundary] total $total]
                set summary_steps [list [segment_summary_step [array get t]] [segment_summary_step [array get h]]]
                set summary_through [summary_through_records_from_steps $summary_steps $to_rec [list $boundary]]
                record_generated_path_summary $e2e_id [summary_steps_path_id $summary_steps] $summary_steps $total [list $from_rec] $summary_through $to_rec $one_cmd
                lappend emitted_cmds $one_cmd
            }
            array unset merged_flags
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
    array unset merged_flags
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
    set residual_through_groups [segment_through_record_groups [array get h]]
    lappend residual_through_groups [list $boundary]
    foreach from_rec $start_records {
        set confirmed_from [pt_confirm_startpoint_record $from_rec $to_rec]
        if {$confirmed_from eq ""} {
            trace_invalid_startpoint $from_rec $to_rec "RESIDUAL" "-" $h(id)
            add_review "" [array get h] "INVALID_STARTPOINT" "residual -from object is not a legal startpoint"
            continue
        }
        set from_rec $confirmed_from
        set cmd "$cmd_name [format_delay $h(delay)] -from [format_record_collection $from_rec]"
        foreach through_group [command_through_groups $residual_through_groups $from_rec $to_rec] {
            append cmd " -through [format_through_record_group $through_group]"
        }
        append cmd " -to [format_record_collection $to_rec]"
        set cmd [append_delay_flags $cmd $h(flags)]
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

proc stage2_delay::pt_confirm_startpoint_record {rec endpoint} {
    if {[validate_startpoint_record $rec]} {
        return $rec
    }

    array set requested $rec
    if {$requested(object_class) ni {pin port cell}} {
        array unset requested
        return ""
    }
    set requested_class $requested(object_class)
    set requested_name $requested(full_name)
    array unset requested

    foreach inferred [pt_startpoints_to_boundary $endpoint] {
        array set candidate $inferred
        set same_object [expr {
            $candidate(object_class) eq $requested_class &&
            $candidate(full_name) eq $requested_name
        }]
        array unset candidate
        if {$same_object} {
            set confirmed [mark_pt_startpoint_record $rec]
            trace_event STARTPOINT_PT_CONFIRMED "from={[record_debug $confirmed]} to={[record_debug $endpoint]}"
            return $confirmed
        }
    }
    return ""
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

proc stage2_delay::merged_delay_flags {segments} {
    set initialized false
    set baseline {}
    foreach seg $segments {
        array set s $seg
        if {[info exists s(missing_sdc)] && [truthy $s(missing_sdc)]} {
            array unset s
            continue
        }
        if {!$initialized} {
            set baseline $s(flags)
            set initialized true
        } elseif {$s(flags) ne $baseline} {
            set left $baseline
            set right $s(flags)
            array unset s
            return [list ok false flags {} left $left right $right]
        }
        array unset s
    }
    return [list ok true flags $baseline left $baseline right $baseline]
}

proc stage2_delay::append_delay_flags {cmd flags} {
    foreach flag $flags {
        append cmd " $flag"
    }
    return $cmd
}

proc stage2_delay::truthy {value} {
    return [expr {[string tolower $value] in {1 true yes y on}}]
}

proc stage2_delay::pt_trace {message} {
    variable options
    if {[info exists options(-verbose_pt_query)] && [truthy $options(-verbose_pt_query)]} {
        puts "PT_QUERY: $message"
    }
    live_trace_event PT_QUERY $message
}

proc stage2_delay::trace_event {kind message} {
    variable live_trace_handle
    set line "[clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}] $kind $message"
    puts "STAGE2_TRACE: $line"
    live_trace_event $kind $message
}

proc stage2_delay::live_trace_event {kind message} {
    variable live_trace_handle
    set line "[clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}] $kind $message"
    if {$live_trace_handle ne ""} {
        puts $live_trace_handle $line
        flush $live_trace_handle
    }
}

proc stage2_delay::trace_invalid_startpoint {from_rec to_rec {path_text "-"} {top_id "-"} {harden_id "-"}} {
    set from_text "-"
    set to_text "-"
    if {$from_rec ne ""} {
        set from_text [record_debug $from_rec]
    }
    if {$to_rec ne ""} {
        set to_text [record_debug $to_rec]
    }
    trace_event INVALID_STARTPOINT "top_id=$top_id harden_id=$harden_id from={$from_text} to={$to_text} path={$path_text}"
}

proc stage2_delay::open_live_trace {} {
    variable options
    variable live_trace_handle
    if {$options(-out_trace_file) eq ""} {
        return
    }
    set trace_dir [file dirname [file normalize $options(-out_trace_file)]]
    if {![file isdirectory $trace_dir]} {
        file mkdir $trace_dir
    }
    set live_trace_handle [open_text $options(-out_trace_file) w]
    fconfigure $live_trace_handle -buffering line
    puts $live_trace_handle "============================================================"
    puts $live_trace_handle "Stage 2 live trace"
    puts $live_trace_handle "Tool    : $::stage2_delay::TOOL_NAME"
    puts $live_trace_handle "Version : $::stage2_delay::VERSION"
    puts $live_trace_handle "Author  : [guarded_release_identity]"
    puts $live_trace_handle "============================================================"
    flush $live_trace_handle
}

proc stage2_delay::close_live_trace {} {
    variable live_trace_handle
    if {$live_trace_handle ne ""} {
        flush $live_trace_handle
        catch {close $live_trace_handle}
        set live_trace_handle ""
    }
}

proc stage2_delay::open_to_stat_add {name {delta 1}} {
    variable open_to_stats
    if {![info exists open_to_stats($name)]} {
        set open_to_stats($name) 0
    }
    incr open_to_stats($name) $delta
}

proc stage2_delay::open_to_stats_summary {} {
    variable open_to_stats
    set names {
        compact_candidates compact_applied compact_members compact_members_saved
        compact_rejected batch_groups batch_seed_records batch_endpoint_queries
        batch_full_fanout_queries batch_fallbacks inferred_endpoints
        target_cache_hits compact_cache_hits
    }
    set parts {}
    foreach name $names {
        set value 0
        if {[info exists open_to_stats($name)]} {
            set value $open_to_stats($name)
        }
        lappend parts "$name=$value"
    }
    return [join $parts ","]
}

proc stage2_delay::performance_stat_add {name {delta 1}} {
    variable performance_stats
    if {![info exists performance_stats($name)]} {
        set performance_stats($name) 0
    }
    incr performance_stats($name) $delta
}

proc stage2_delay::performance_stats_summary {} {
    variable performance_stats
    set names {
        metadata_batch_queries metadata_batch_records metadata_batch_successes
        metadata_batch_fallbacks metadata_batch_returned_records
        metadata_batch_elapsed_ms metadata_batch_disabled_groups
        metadata_individual_queries structural_passthrough_commands
        structural_passthrough_objects matrix_pairs_avoided
        matrix_expansion_limited matrix_pairs_expanded matrix_expand_elapsed_ms
        sparse_matrix_commands sparse_matrix_endpoint_queries
        sparse_matrix_clock_batches sparse_matrix_clock_batch_fallbacks
        sparse_matrix_clock_records
        sparse_matrix_query_unknown sparse_matrix_pairs_pruned
        sparse_matrix_pairs_retained sparse_matrix_plan_elapsed_ms
        attribute_cache_hits owner_cache_hits
        boundary_cache_hits startpoint_cache_hits missing_harden_cache_hits
        missing_top_cache_hits segment_index_lookups final_rewrite_index_hits
        final_rewrite_skipped_files parsed_segment_reuse_hits
        final_rewrite_signature_lookups
    }
    set parts {}
    foreach name $names {
        set value 0
        if {[info exists performance_stats($name)]} {
            set value $performance_stats($name)
        }
        lappend parts "$name=$value"
    }
    return [join $parts ","]
}

proc stage2_delay::consume_segment {seg} {
    variable consumed_constraints
    variable consumed_segments
    variable consumed_command_segments
    variable consumed_source_files
    array set s $seg
    if {[info exists s(structural_passthrough)] && [truthy $s(structural_passthrough)]} {
        set segment_id $s(id)
        array unset s
        error "internal error: structural passthrough segment cannot be consumed: $segment_id"
    }
    if {[info exists s(missing_sdc)] && [truthy $s(missing_sdc)]} {
        array unset s
        return
    }
    set key "$s(source_file)|$s(id)"
    if {![info exists consumed_constraints($key)]} {
        set consumed_constraints($key) $s(original_text)
        lappend consumed_segments [array get s]
        set source_key [source_file_key $s(source_file)]
        set command_key [source_command_key $s(source_file) $s(line_no) $s(original_text)]
        lappend consumed_command_segments($command_key) [array get s]
        set consumed_source_files($source_key) 1
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
    if {$reason eq "MATRIX_EXPANSION_LIMIT"} {
        foreach candidate [list $top_seg $harden_seg] {
            if {$candidate eq ""} {
                continue
            }
            array set matrix $candidate
            if {[info exists matrix(matrix_pair_count)] && $matrix(matrix_pair_count) > 0} {
                lappend item \
                    matrix_from_count $matrix(matrix_from_count) \
                    matrix_to_count $matrix(matrix_to_count) \
                    matrix_pair_count $matrix(matrix_pair_count) \
                    matrix_limit $matrix(matrix_limit)
                array unset matrix
                break
            }
            array unset matrix
        }
    }
    lappend review_items $item
    live_trace_event REVIEW [join_kv $item]
}

proc stage2_delay::review_severity {reason} {
    set error_reasons {
        INVALID_STARTPOINT INVALID_ENDPOINT INVALID_TERMINAL_ENDPOINT
        NO_FINAL_STARTPOINT_INFERRED NO_TOP_STARTPOINT_INFERRED
        NO_BOUNDARY_INPUT MISSING_HARDEN_SDC_ENDPOINT_NOT_FOUND
        DELAY_OPTION_MISMATCH BOUNDARY_ENDPOINT_OWNER_MISMATCH
        TOO_MANY_BOUNDARY_INPUTS TOO_MANY_FINAL_STARTPOINTS TOO_MANY_TOP_STARTPOINTS
        OPEN_FROM_AND_TO_UNSUPPORTED OPEN_TO_ENDPOINT_NOT_INFERRED
        TOO_MANY_OPEN_TO_ENDPOINTS NON_NUMERIC_DELAY CLOCK_OR_UNKNOWN_OBJECT
        EDGE_SPECIFIC_OPTION NO_TO_OBJECT MULTI_OBJECT_FROM MULTI_OBJECT_TO
        TOP_TO_DIRECTION_UNKNOWN HARDEN_TO_DIRECTION_UNKNOWN
        HARDEN_FROM_DIRECTION_UNKNOWN
    }
    if {[lsearch -exact $error_reasons $reason] >= 0 ||
        [string match "INVALID_*" $reason] ||
        [string match "*DIRECTION_UNKNOWN" $reason]} {
        return ERROR
    }
    if {$reason in {
        NO_HARDEN_SEGMENT_MATCHED NO_TOP_SEGMENT_MATCHED
        NO_RECURSIVE_CHAIN_MATCHED PARTIAL_MERGE_REVIEW
        MULTI_HOP_NOT_SUPPORTED OUTPUT_DIRECTION_NOT_SUPPORTED
        TOP_PASSTHROUGH_UNKNOWN HARDEN_PASSTHROUGH_UNKNOWN
    } || [string match "PASSTHROUGH_*" $reason]} {
        return WARNING
    }
    return WARNING
}

proc stage2_delay::review_action {reason} {
    switch -- $reason {
        INVALID_STARTPOINT - INVALID_ENDPOINT - INVALID_TERMINAL_ENDPOINT {
            return "检查 stage2_live.log 中实际 from/to，并用 PT 验证 timing path"
        }
        NO_FINAL_STARTPOINT_INFERRED - NO_TOP_STARTPOINT_INFERRED {
            return "检查 endpoint/boundary 的 all_fanin startpoint 查询和 PT 时钟关系"
        }
        NO_BOUNDARY_INPUT - MISSING_HARDEN_SDC_ENDPOINT_NOT_FOUND {
            return "检查 harden SDC endpoint、boundary 输入和对应 harden 网表"
        }
        DELAY_OPTION_MISMATCH {
            return "检查参与合并的 top/harden delay option 是否一致"
        }
        BOUNDARY_ENDPOINT_OWNER_MISMATCH {
            return "检查 boundary 和 endpoint 是否属于同一 harden instance"
        }
        NO_HARDEN_SEGMENT_MATCHED {
            return "检查 harden delay 是否存在；优先追踪同一路径最早的 ERROR"
        }
        NO_TOP_SEGMENT_MATCHED {
            return "检查 top delay 是否覆盖该 harden boundary；优先追踪同一路径最早的 ERROR"
        }
        NO_RECURSIVE_CHAIN_MATCHED {
            return "检查中间 harden boundary、missing-SDC 段和 MAX_CHAIN_DEPTH"
        }
        PARTIAL_MERGE_REVIEW {
            return "检查未匹配的 boundary；确认 residual_through 或改为人工 review"
        }
        MATRIX_EXPANSION_LIMIT {
            return "原约束已保留；检查矩阵对象集合，确认后提高 STAGE2_MAX_SEGMENT_PAIRS 或拆分约束"
        }
        default {
            if {[string match "TOO_MANY_*" $reason]} {
                return "检查对象展开数量和 max_endpoints/max_enum_objects 设置"
            }
            return "检查 integration_delay_merge.rpt 和 stage2_live.log 的对应 PT 查询"
        }
    }
}

proc stage2_delay::add_report_item {text} {
    variable report_items
    lappend report_items $text
}

proc stage2_delay::clock_object_names {} {
    if {[info commands get_clocks] eq ""} {
        pt_trace "get_clocks unavailable; clock review outputs will be empty"
        return {}
    }
    pt_trace "get_clocks -quiet *"
    if {[catch {set clocks [get_clocks -quiet *]} err]} {
        pt_trace "get_clocks failed error={$err}"
        return {}
    }
    set names {}
    if {[info commands foreach_in_collection] ne ""} {
        foreach_in_collection clock $clocks {
            set name [collection_object_name $clock]
            if {$name ne ""} {
                lappend names $name
            }
        }
    } else {
        foreach clock $clocks {
            set name [collection_object_name $clock]
            if {$name ne ""} {
                lappend names $name
            }
        }
    }
    set names [lsort -dictionary -unique $names]
    pt_trace "get_clocks result count=[llength $names]"
    return $names
}

proc stage2_delay::clock_attribute_text {clock_name attribute {default "-"}} {
    if {[info commands get_clocks] eq "" || [info commands get_attribute] eq ""} {
        return $default
    }
    if {[catch {set clock [get_clocks -quiet $clock_name]}] || $clock eq ""} {
        return $default
    }
    if {[catch {set value [get_attribute $clock $attribute]}] || $value eq ""} {
        return $default
    }
    return $value
}

proc stage2_delay::clock_attribute_object_names {clock_name attributes} {
    if {[info commands get_clocks] eq "" || [info commands get_attribute] eq ""} {
        return "-"
    }
    if {[catch {set clock [get_clocks -quiet $clock_name]}] || $clock eq ""} {
        return "-"
    }
    foreach attribute $attributes {
        if {[catch {set value [get_attribute $clock $attribute]}] || $value eq ""} {
            continue
        }
        if {[info commands get_object_name] ne ""} {
            if {![catch {set names [get_object_name $value]}] && $names ne ""} {
                return [join $names ","]
            }
        }
        return [join $value ","]
    }
    return "-"
}

proc stage2_delay::capture_pt_report {command temp_path} {
    catch {file delete -force $temp_path}
    set error_text ""
    if {[info commands redirect] ne ""} {
        pt_trace "redirect -file {$temp_path} {$command}"
        if {[catch {redirect -file $temp_path $command} err]} {
            set error_text $err
            pt_trace "PT report redirect failed command={$command} error={$err}"
        } elseif {[file exists $temp_path]} {
            set fin [open_text $temp_path r]
            set text [read $fin]
            close $fin
            catch {file delete -force $temp_path}
            return $text
        }
    }
    set report_command [lindex $command 0]
    if {[info commands $report_command] ne ""} {
        pt_trace "fallback direct PT report command={$command}"
        if {![catch {set text [uplevel #0 $command]} err] && $text ne ""} {
            return $text
        }
        if {$error_text eq "" && [info exists err]} {
            set error_text $err
        }
    }
    if {$error_text eq ""} {
        set error_text "command unavailable or returned no capturable text"
    }
    return "# PT report unavailable: $error_text"
}

proc stage2_delay::write_clock_inventory_report {path clock_names raw_report} {
    set fout [open_text $path w]
    write_author_banner $fout
    puts $fout ""
    puts $fout "# Clock inventory generated by run_stage2_merge_delay.tcl"
    puts $fout "# Current PT design: [current_scope_name]"
    puts $fout "# Clock count      : [llength $clock_names]"
    puts $fout ""
    puts $fout "\[CLOCK_INVENTORY\]"
    if {[llength $clock_names] == 0} {
        puts $fout "No clocks found in the linked PrimeTime design."
    } else {
        foreach clock_name $clock_names {
            set period [clock_attribute_text $clock_name period]
            set is_generated [clock_attribute_text $clock_name is_generated]
            set master_clock [clock_attribute_object_names $clock_name {master_clock master}]
            set sources [clock_attribute_object_names $clock_name {sources source}]
            puts $fout [join_kv [list \
                clock_name $clock_name \
                period $period \
                is_generated $is_generated \
                master_clock $master_clock \
                sources $sources]]
        }
    }
    puts $fout ""
    puts $fout "\[REPORT_CLOCK_RAW\]"
    puts $fout $raw_report
    close $fout
}

proc stage2_delay::write_existing_clock_groups_report {path raw_report} {
    set fout [open_text $path w]
    write_author_banner $fout
    puts $fout ""
    puts $fout "# Existing PrimeTime clock groups generated by report_clock -groups"
    puts $fout "# Current PT design: [current_scope_name]"
    puts $fout ""
    puts $fout $raw_report
    close $fout
}

proc stage2_delay::write_clock_group_review_sdc {path clock_names inventory_path groups_path} {
    set fout [open_text $path w]
    write_author_banner $fout "# "
    puts $fout "#"
    puts $fout "# Clock-group review template generated by run_stage2_merge_delay.tcl"
    puts $fout "# Clock inventory       : $inventory_path"
    puts $fout "# Existing groups report: $groups_path"
    puts $fout "#"
    puts $fout "# REVIEW ONLY: every command in this file is commented out."
    puts $fout "# Stage 2 does not source this file and does not append it to the final flatten SDC."
    puts $fout "# One clock per group makes every group asynchronous to every other group."
    puts $fout "# Merge clocks that are synchronous or share intentional timing relationships before enabling."
    puts $fout ""
    puts $fout "# Detected clocks: [llength $clock_names]"
    foreach clock_name $clock_names {
        puts $fout "#   $clock_name"
    }
    puts $fout ""
    if {[llength $clock_names] < 2} {
        puts $fout "# No set_clock_groups proposal generated because fewer than two clocks were found."
        close $fout
        return
    }
    puts $fout "# Proposed manual-review template:"
    puts $fout "# set_clock_groups -asynchronous \\"
    set last_idx [expr {[llength $clock_names] - 1}]
    for {set idx 0} {$idx <= $last_idx} {incr idx} {
        set clock_name [lindex $clock_names $idx]
        set suffix " \\"
        if {$idx == $last_idx} {
            set suffix ""
        }
        puts $fout "#     -group \[get_clocks [brace_name $clock_name]\]$suffix"
    }
    close $fout
}

proc stage2_delay::write_clock_group_outputs {inventory_path groups_path review_sdc_path} {
    set clock_names [clock_object_names]
    set temp_dir [file dirname [file normalize $inventory_path]]
    if {![file isdirectory $temp_dir]} {
        file mkdir $temp_dir
    }
    set raw_clock [capture_pt_report [list report_clock] [file join $temp_dir .stage2_report_clock.tmp]]
    set raw_groups [capture_pt_report [list report_clock -groups] [file join $temp_dir .stage2_report_clock_groups.tmp]]
    write_clock_inventory_report $inventory_path $clock_names $raw_clock
    write_existing_clock_groups_report $groups_path $raw_groups
    write_clock_group_review_sdc $review_sdc_path $clock_names $inventory_path $groups_path
    trace_event CLOCK_REVIEW "clocks=[llength $clock_names] inventory={$inventory_path} existing_groups={$groups_path} review_sdc={$review_sdc_path} active_constraints_added=0"
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
    variable sparse_pruned_commands
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
    foreach command_key [lsort [array names sparse_pruned_commands]] {
        array set p $sparse_pruned_commands($command_key)
        array set s $p(segment)
        puts $fout "# PT_DISCONNECTED_MATRIX_PAIRS $s(source_file)|$s(original_id) pruned=$p(pruned_count) retained=$p(retained_count) product=$p(original_total)"
        puts $fout "# ORIGINAL: [compact_spaces $s(original_text)]"
        puts $fout ""
        array unset s
        array unset p
    }
    close $fout
}

proc stage2_delay::write_review_report {path} {
    variable review_items
    set fout [open_text $path w]
    write_author_banner $fout
    puts $fout ""
    puts $fout "# unmerged_delay_review.rpt generated by run_stage2_merge_delay.tcl"
    array set reason_counts {}
    array set severity_counts {ERROR 0 WARNING 0 INFO 0}
    foreach item $review_items {
        array set r $item
        set severity [review_severity $r(reason)]
        incr reason_counts($r(reason))
        incr severity_counts($severity)
        array unset r
    }
    set overall_result PASS
    set highest NONE
    if {$severity_counts(ERROR) > 0} {
        set overall_result REVIEW_REQUIRED
        set highest ERROR
    } elseif {$severity_counts(WARNING) > 0} {
        set overall_result PASS_WITH_WARNING
        set highest WARNING
    } elseif {$severity_counts(INFO) > 0} {
        set overall_result PASS_WITH_INFO
        set highest INFO
    }
    puts $fout ""
    puts $fout "\[RUN_CONCLUSION\]"
    puts $fout "Overall result    : $overall_result"
    puts $fout "Highest severity  : $highest"
    puts $fout "Total reviews     : [llength $review_items]"
    puts $fout ""
    puts $fout "Severity summary:"
    puts $fout "  ERROR           : $severity_counts(ERROR)"
    puts $fout "  WARNING         : $severity_counts(WARNING)"
    puts $fout "  INFO            : $severity_counts(INFO)"
    puts $fout ""
    puts $fout "Severity definition:"
    puts $fout "  ERROR   : E2E 约束无法可靠生成，必须人工确认"
    puts $fout "  WARNING : 存在未匹配或部分处理，需要 review，但原约束未静默丢失"
    puts $fout "  INFO    : 预期行为或已安全处理，不阻止 final SDC 使用"
    puts $fout ""
    puts $fout "\[REASON_SUMMARY\]"
    if {[llength [array names reason_counts]] == 0} {
        puts $fout "No review reason."
    } else {
        puts $fout [format "%-9s %-40s %5s  %s" Severity Reason Count Conclusion]
        puts $fout [format "%-9s %-40s %5s  %s" -------- ------ ----- -----------]
        foreach severity {ERROR WARNING INFO} {
            foreach reason [lsort [array names reason_counts]] {
                if {[review_severity $reason] ne $severity} {
                    continue
                }
                puts $fout [format "%-9s %-40s %5d  %s" \
                    $severity $reason $reason_counts($reason) [review_action $reason]]
            }
        }
    }
    puts $fout ""
    puts $fout "\[REASON_ACTION\]"
    foreach reason [lsort [array names reason_counts]] {
        puts $fout "[review_severity $reason] $reason: [review_action $reason]"
    }
    puts $fout ""
    array unset reason_counts
    array unset severity_counts
    puts $fout "\[DETAIL\]"
    foreach item $review_items {
        array set r $item
        puts $fout "\[[review_severity $r(reason)]\] [join_kv $item]"
        array unset r
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
    puts $fout "Live trace file                 : $options(-out_trace_file)"
    puts $fout "Clock review enabled            : $options(-generate_clock_group_review)"
    puts $fout "Clock inventory report          : $options(-out_clock_inventory)"
    puts $fout "Existing clock groups report    : $options(-out_clock_groups_report)"
    puts $fout "Clock groups review SDC         : $options(-out_clock_group_review_sdc)"
    puts $fout "Active clock groups added       : 0"
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
    puts $fout "Bus compression                 : $options(-compact_bus)"
    puts $fout "Bus compression minimum members : $options(-compact_bus_min_members)"
    puts $fout "Batch open-to PT query          : $options(-batch_open_to_query)"
    puts $fout "Metadata batch enabled          : $options(-metadata_batch_enabled)"
    puts $fout "Metadata batch size             : $options(-metadata_batch_size)"
    puts $fout "Max segment pairs               : $options(-max_segment_pairs)"
    puts $fout "Sparse matrix pruning           : $options(-sparse_matrix_prune)"
    puts $fout "Open-to optimization statistics : [open_to_stats_summary]"
    puts $fout "Stage2 performance statistics   : [performance_stats_summary]"
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
    if {[info exists s(structural_passthrough)] && [truthy $s(structural_passthrough)]} {
        set line [list \
            source $s(source) \
            id $s(id) \
            file $s(source_file) \
            line $s(line_no) \
            reason $reason \
            from_count $s(matrix_from_count) \
            to_count $s(matrix_to_count) \
            pair_count $s(matrix_pair_count) \
        ]
    } else {
        set line [list \
            source $s(source) \
            id $s(id) \
            file $s(source_file) \
            line $s(line_no) \
            reason $reason \
            from [records_debug_list $s(from_records)] \
            to [records_debug_list $s(to_records)] \
        ]
    }
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
    variable hardens
    variable path_summary_items
    set release_owner [guarded_release_identity]

    if {$dir eq ""} {
        return
    }
    if {![file isdirectory $dir]} {
        file mkdir $dir
    }

    set sheet_order {top}
    array set sheet_seen {top 1}
    foreach harden $hardens {
        array set h $harden
        if {[info exists h(inst_path)] && $h(inst_path) ne "" && ![info exists sheet_seen($h(inst_path))]} {
            set sheet_seen($h(inst_path)) 1
            lappend sheet_order $h(inst_path)
        }
        array unset h
    }

    array set rows_by_sheet {}
    array set status_count {}
    array set missing_sdc_seen {}
    array set missing_sdc_count {}
    array set sheet_max_through {}
    array set sheet_max_steps {}
    foreach sheet $sheet_order {
        set rows_by_sheet($sheet) {}
        set sheet_max_through($sheet) 0
        set sheet_max_steps($sheet) 0
    }
    foreach item $path_summary_items {
        array set r $item
        set sheet top
        if {[info exists r(sheet)]} {
            set sheet $r(sheet)
        }
        if {![info exists rows_by_sheet($sheet)]} {
            set rows_by_sheet($sheet) {}
            set sheet_seen($sheet) 1
            set sheet_max_through($sheet) 0
            set sheet_max_steps($sheet) 0
            lappend sheet_order $sheet
        }
        lappend rows_by_sheet($sheet) $item
        if {[info exists r(merge_status)]} {
            incr status_count([list $sheet $r(merge_status)])
        }
        if {[info exists r(cmd_id)] && [string match "MISSING_*" $r(cmd_id)]} {
            set missing_key [list $sheet $r(cmd_id)]
            if {![info exists missing_sdc_seen($missing_key)]} {
                set missing_sdc_seen($missing_key) 1
                incr missing_sdc_count($sheet)
            }
        }
        if {[info exists r(through_records)] && [llength $r(through_records)] > $sheet_max_through($sheet)} {
            set sheet_max_through($sheet) [llength $r(through_records)]
        }
        if {[info exists r(path_steps)] && [llength $r(path_steps)] > $sheet_max_steps($sheet)} {
            set sheet_max_steps($sheet) [llength $r(path_steps)]
        }
        array unset r
    }

    array set max_delay_total {}
    array set max_delay_used {}
    build_max_delay_usage_stats max_delay_total max_delay_used

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
        set max_used 0
        set max_total 0
        if {[info exists max_delay_used($sheet)]} {
            set max_used $max_delay_used($sheet)
        }
        if {[info exists max_delay_total($sheet)]} {
            set max_total $max_delay_total($sheet)
        }
        set max_usage [format "%d/%d" $max_used $max_total]
        set merged_rows 0
        set residual_rows 0
        set review_rows 0
        set missing_stages 0
        foreach status {MERGED RESIDUAL REVIEW} counter {merged_rows residual_rows review_rows} {
            set key [list $sheet $status]
            if {[info exists status_count($key)]} {
                set $counter $status_count($key)
            }
        }
        if {[info exists missing_sdc_count($sheet)]} {
            set missing_stages $missing_sdc_count($sheet)
        }
        csv_write_row $fout [list \
            $TOOL_NAME \
            $VERSION \
            $release_owner \
            $sheet \
            $sheet_file($sheet) \
            [llength $rows] \
            $merged_rows \
            $residual_rows \
            $review_rows \
            $max_used \
            $max_total \
            $max_usage \
            $missing_stages \
        ]
    }
    close $fout

    foreach sheet $sheet_order {
        write_path_summary_sheet \
            [file join $dir $sheet_file($sheet)] \
            $rows_by_sheet($sheet) \
            $sheet_max_through($sheet) \
            $sheet_max_steps($sheet)
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

proc stage2_delay::build_max_delay_usage_stats {total_name used_name} {
    variable all_delay_segments
    variable path_summary_items
    variable sparse_pruned_commands
    upvar 1 $total_name total_by_sheet
    upvar 1 $used_name used_by_sheet

    array set total_seen {}
    array set used_seen {}
    foreach seg $all_delay_segments {
        array set s $seg
        if {$s(type) eq "max"} {
            set sheet [expr {$s(source) eq "harden" ? $s(harden_inst) : "top"}]
            set key [list $sheet $s(source_file) $s(original_id)]
            if {![info exists total_seen($key)]} {
                set total_seen($key) 1
                incr total_by_sheet($sheet)
            }
        }
        array unset s
    }
    foreach command_key [array names sparse_pruned_commands] {
        array set p $sparse_pruned_commands($command_key)
        array set s $p(segment)
        if {$s(type) eq "max"} {
            set sheet [expr {$s(source) eq "harden" ? $s(harden_inst) : "top"}]
            set key [list $sheet $s(source_file) $s(original_id)]
            if {![info exists total_seen($key)]} {
                set total_seen($key) 1
                incr total_by_sheet($sheet)
            }
        }
        array unset s
        array unset p
    }
    foreach item $path_summary_items {
        array set r $item
        if {$r(delay_type) eq "max" && $r(merge_status) in {MERGED RESIDUAL}} {
            set key [list $r(sheet) $r(source_file) $r(original_id)]
            if {[info exists total_seen($key)] && ![info exists used_seen($key)]} {
                set used_seen($key) 1
                incr used_by_sheet($r(sheet))
            }
        }
        array unset r
    }
}

proc stage2_delay::max_delay_usage_stats_for_sheet {sheet} {
    array set total_by_sheet {}
    array set used_by_sheet {}
    build_max_delay_usage_stats total_by_sheet used_by_sheet
    set total 0
    set used 0
    if {[info exists total_by_sheet($sheet)]} {
        set total $total_by_sheet($sheet)
    }
    if {[info exists used_by_sheet($sheet)]} {
        set used $used_by_sheet($sheet)
    }
    return [list $used $total]
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

proc stage2_delay::write_path_summary_sheet {path rows {max_through -1} {max_steps -1}} {
    if {$max_through < 0 || $max_steps < 0} {
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
            set value "-"
            if {[info exists r($key)]} {
                set value $r($key)
            }
            lappend row $value
        }
        foreach key {stage_delays stage_from_texts stage_to_texts through_records path_steps} {
            set $key {}
            if {[info exists r($key)]} {
                set $key $r($key)
            }
        }
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
            set value "-"
            if {[info exists r($key)]} {
                set value $r($key)
            }
            lappend row $value
        }
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
    variable consumed_source_files

    set fin [open_text $path r]
    set text [read $fin]
    close $fin

    set source_key [source_file_key $path]
    if {![info exists consumed_source_files($source_key)]} {
        performance_stat_add final_rewrite_skipped_files
        return [string trimright $text]
    }

    set commands [scan_tcl_commands $text]
    set remaining $text
    foreach item [lsort -decreasing -integer -command stage2_delay::command_start_compare [commands_with_offsets $text $commands]] {
        array set cmd $item
        set consumed_for_cmd [consumed_segments_for_command $path $cmd(line) $cmd(text)]
        set sparse_pruned_info [sparse_pruned_info_for_command $path $cmd(line) $cmd(text)]
        if {[llength $consumed_for_cmd] > 0 || $sparse_pruned_info ne ""} {
            set before [string range $remaining 0 [expr {$cmd(start) - 1}]]
            set after [string range $remaining $cmd(end) end]
            set replacement [remaining_replacement_for_command \
                $path $cmd(line) $cmd(text) $consumed_for_cmd $sparse_pruned_info]
            set remaining "${before}${replacement}${after}"
        }
        array unset cmd
    }
    return [string trimright $remaining]
}

proc stage2_delay::consumed_segments_for_command {path line_no original_text} {
    variable consumed_command_segments
    set command_key [source_command_key $path $line_no $original_text]
    if {[info exists consumed_command_segments($command_key)]} {
        performance_stat_add final_rewrite_index_hits
        return $consumed_command_segments($command_key)
    }
    return {}
}

proc stage2_delay::sparse_pruned_info_for_command {path line_no original_text} {
    variable sparse_pruned_commands
    set command_key [source_command_key $path $line_no $original_text]
    if {[info exists sparse_pruned_commands($command_key)]} {
        return $sparse_pruned_commands($command_key)
    }
    return ""
}

proc stage2_delay::remaining_replacement_for_command {path line_no original_text consumed_for_cmd {sparse_pruned_info ""}} {
    variable parsed_command_segments
    if {[llength $consumed_for_cmd] > 0} {
        array set first [lindex $consumed_for_cmd 0]
    } elseif {$sparse_pruned_info ne ""} {
        array set sparse $sparse_pruned_info
        array set first $sparse(segment)
        array unset sparse
    } else {
        error "internal error: remaining replacement has no consumed or sparse-pruned segment"
    }
    set command_key [source_command_key $path $line_no $original_text]
    if {[info exists parsed_command_segments($command_key)]} {
        performance_stat_add parsed_segment_reuse_hits
        set expanded $parsed_command_segments($command_key)
    } elseif {$sparse_pruned_info ne ""} {
        set expanded {}
    } else {
        set words [tokenize_words $original_text]
        set base [segment_from_words $words $first(source) $path $first(line_no) $first(original_id) $original_text $first(harden_inst)]
        set expanded [expand_segment $base]
    }

    array set consumed_sig_count {}
    foreach seg $consumed_for_cmd {
        incr consumed_sig_count([segment_signature $seg])
    }

    set leftovers {}
    foreach seg $expanded {
        set sig [segment_signature $seg]
        performance_stat_add final_rewrite_signature_lookups
        if {[info exists consumed_sig_count($sig)] && $consumed_sig_count($sig) > 0} {
            incr consumed_sig_count($sig) -1
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
    foreach group [segment_through_record_groups [array get s]] {
        append cmd " -through [format_through_record_group $group]"
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
            lappend out [list id $cmd(id) line $cmd(line) end_line $cmd(end_line) text $target start $start end $end]
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
    set out_trace_file [file normalize [global_setting STAGE2_TRACE_FILE [file join $out_dir stage2_live.log]]]
    set generate_clock_group_review [global_setting GENERATE_CLOCK_GROUP_REVIEW true]
    set out_clock_inventory [file normalize [global_setting OUT_CLOCK_INVENTORY [file join $out_dir ${top_module}_clock_inventory.rpt]]]
    set out_clock_groups_report [file normalize [global_setting OUT_CLOCK_GROUPS_REPORT [file join $out_dir ${top_module}_clock_groups_existing.rpt]]]
    set out_clock_group_review_sdc [file normalize [global_setting OUT_CLOCK_GROUP_REVIEW_SDC [file join $out_dir ${top_module}_clock_groups_review.sdc]]]

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
    set max_segment_pairs [global_setting STAGE2_MAX_SEGMENT_PAIRS 100000]
    set sparse_matrix_prune [global_setting STAGE2_SPARSE_MATRIX_PRUNE true]
    set compact_bus [global_setting STAGE2_COMPACT_BUS true]
    set compact_bus_min_members [global_setting STAGE2_COMPACT_BUS_MIN_MEMBERS 4]
    set batch_open_to_query [global_setting STAGE2_BATCH_OPEN_TO_QUERY true]
    set metadata_batch_enabled [global_setting STAGE2_METADATA_BATCH_ENABLED true]
    set metadata_batch_size [global_setting STAGE2_METADATA_BATCH_SIZE 128]
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
    set_global_setting STAGE2_TRACE_FILE $out_trace_file
    set_global_setting GENERATE_CLOCK_GROUP_REVIEW $generate_clock_group_review
    set_global_setting OUT_CLOCK_INVENTORY $out_clock_inventory
    set_global_setting OUT_CLOCK_GROUPS_REPORT $out_clock_groups_report
    set_global_setting OUT_CLOCK_GROUP_REVIEW_SDC $out_clock_group_review_sdc
    set_global_setting TOP_MODULE_NAME $top_module
    set_global_setting TOP_OPEN_FROM_MODE $top_open_from_mode
    set_global_setting TOP_PORT_BOUNDARY_MAP_MODE $top_port_boundary_map_mode
    set_global_setting RECURSIVE_CHAIN_MODE $recursive_chain_mode
    set_global_setting MAX_CHAIN_DEPTH $max_chain_depth
    set_global_setting STAGE2_COMPACT_BUS $compact_bus
    set_global_setting STAGE2_COMPACT_BUS_MIN_MEMBERS $compact_bus_min_members
    set_global_setting STAGE2_BATCH_OPEN_TO_QUERY $batch_open_to_query
    set_global_setting STAGE2_METADATA_BATCH_ENABLED $metadata_batch_enabled
    set_global_setting STAGE2_METADATA_BATCH_SIZE $metadata_batch_size
    set_global_setting STAGE2_MAX_SEGMENT_PAIRS $max_segment_pairs
    set_global_setting STAGE2_SPARSE_MATRIX_PRUNE $sparse_matrix_prune
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
    puts "INFO: Live trace file     : $out_trace_file"
    puts "INFO: Clock review        : $generate_clock_group_review"
    puts "INFO: Clock inventory     : $out_clock_inventory"
    puts "INFO: Existing clock grps : $out_clock_groups_report"
    puts "INFO: Clock review SDC    : $out_clock_group_review_sdc"
    puts "INFO: Write path summary  : $write_path_summary"
    puts "INFO: Merge mode          : $merge_mode"
    puts "INFO: Top open_from mode  : $top_open_from_mode"
    puts "INFO: Top port map mode   : $top_port_boundary_map_mode"
    puts "INFO: Recursive mode      : $recursive_chain_mode"
    puts "INFO: Bus compression     : $compact_bus (min members=$compact_bus_min_members)"
    puts "INFO: Batch open-to query : $batch_open_to_query"
    puts "INFO: Metadata batch      : $metadata_batch_enabled (size=$metadata_batch_size)"
    puts "INFO: Max segment pairs   : $max_segment_pairs"
    puts "INFO: Sparse matrix prune : $sparse_matrix_prune"
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
        -out_trace_file $out_trace_file \
        -generate_clock_group_review $generate_clock_group_review \
        -out_clock_inventory $out_clock_inventory \
        -out_clock_groups_report $out_clock_groups_report \
        -out_clock_group_review_sdc $out_clock_group_review_sdc \
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
        -max_enum_objects $max_enum_objects \
        -max_segment_pairs $max_segment_pairs \
        -sparse_matrix_prune $sparse_matrix_prune \
        -compact_bus $compact_bus \
        -compact_bus_min_members $compact_bus_min_members \
        -batch_open_to_query $batch_open_to_query \
        -metadata_batch_enabled $metadata_batch_enabled \
        -metadata_batch_size $metadata_batch_size

    puts "INFO: Stage 2 complete."
    puts "INFO: Generated E2E SDC   : $out_e2e_sdc"
    puts "INFO: Merge report        : $out_report"
    puts "INFO: Removed constraints : $out_removed_sdc"
    puts "INFO: Review report       : $out_review_rpt"
    puts "INFO: Final flatten SDC   : $out_final_sdc"
    puts "INFO: Clock inventory     : $out_clock_inventory"
    puts "INFO: Existing clock grps : $out_clock_groups_report"
    puts "INFO: Clock review SDC    : $out_clock_group_review_sdc"
    puts "INFO: Open-to optimization: [stage2_delay::open_to_stats_summary]"
    puts "INFO: Performance stats   : [stage2_delay::performance_stats_summary]"
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
