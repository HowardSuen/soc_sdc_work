#!/usr/bin/env python3
"""Regression smoke tests for run_stage2_merge_delay.tcl.

The tests run with plain tclsh plus a small mock of the PrimeTime collection
and direction APIs. They do not replace PrimeTime validation, but they keep
parsing, matching, reporting, and static SDC emission deterministic.
"""

from __future__ import print_function

import os
import shutil
import subprocess
import sys


HERE = os.path.abspath(os.path.dirname(__file__))
TOOL = os.path.abspath(os.path.join(HERE, "..", "run_stage2_merge_delay.tcl"))
WORK = os.path.join(HERE, "work")


DEFAULT_PT_PRELUDE = r'''
array set ::PT_MOCK_DIRECTIONS {
    u_src_reg/Q out
    u_up/data_o out
    u_up/u_reg/Q out
    u_h0/cfg_i in
    u_h0/async_i in
    u_h0/unused_i in
    u_h0/other_i in
    u_h0/u_reg/D in
    u_h0/u_cfg_reg/D in
    u_h0/u_mode_reg/D in
    u_h0/i_niu_rst_n in
    u_h0/o_niu_rst_n out
}

proc current_design {} {
    return current_integration_top
}

proc sizeof_collection {coll} {
    return [llength $coll]
}

proc foreach_in_collection {var coll body} {
    upvar 1 $var item
    foreach item $coll {
        uplevel 1 $body
    }
}

proc get_pins {args} {
    if {[lsearch -exact $args "-of_objects"] >= 0} {
        return {}
    }
    set name [lindex $args end]
    return [list $name]
}

proc get_ports {args} {
    set name [lindex $args end]
    return [list $name]
}

proc get_attribute {obj attr} {
    set name [lindex $obj 0]
    if {$attr eq "full_name"} {
        return $name
    }
    if {$attr eq "direction" && [info exists ::PT_MOCK_DIRECTIONS($name)]} {
        return $::PT_MOCK_DIRECTIONS($name)
    }
    return ""
}
'''


def write_file(path, text):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as fout:
        fout.write(text)


def read_file(path):
    with open(path, "r") as fin:
        return fin.read()


def run_case(case_name, top_sdc, harden_sdc, extra_build_args=None, extra_hardens=None, prelude=""):
    case_dir = os.path.join(WORK, case_name)
    if os.path.isdir(case_dir):
        shutil.rmtree(case_dir)
    os.makedirs(case_dir)
    top_path = os.path.join(case_dir, "top.sdc")
    harden_path = os.path.join(case_dir, "harden.sdc")
    harden_list = os.path.join(case_dir, "harden_list.csv")
    out_sdc = os.path.join(case_dir, "generated_e2e_delay.sdc")
    out_report = os.path.join(case_dir, "integration_delay_merge.rpt")
    out_removed = os.path.join(case_dir, "merged_delay_removed.sdc")
    out_review = os.path.join(case_dir, "unmerged_delay_review.rpt")
    out_final = os.path.join(case_dir, "current_integration_top_flatten.sdc")
    out_summary = os.path.join(case_dir, "delay_path_summary")
    driver = os.path.join(case_dir, "run.tcl")
    write_file(top_path, top_sdc)
    write_file(harden_path, harden_sdc)
    rows = [
        "harden_name,inst_path,clean_sdc,delay_candidate_file,netlist,module",
        "h0,u_h0,%s,,h0.v,harden0" % harden_path.replace("\\", "/"),
    ]
    for item in extra_hardens or []:
        clean_sdc = ""
        module = item[2] if len(item) > 2 else item[0]
        if len(item) > 3:
            clean_sdc = os.path.join(case_dir, "%s_clean.sdc" % item[0])
            write_file(clean_sdc, item[3])
            clean_sdc = clean_sdc.replace("\\", "/")
        rows.append("%s,%s,%s,,,%s" % (item[0], item[1], clean_sdc, module))
    write_file(harden_list, "\n".join(rows) + "\n")
    args = [
        "-top_sdc", top_path.replace("\\", "/"),
        "-harden_list", harden_list.replace("\\", "/"),
        "-out_e2e_sdc", out_sdc.replace("\\", "/"),
        "-out_report", out_report.replace("\\", "/"),
        "-out_removed_sdc", out_removed.replace("\\", "/"),
        "-out_review_rpt", out_review.replace("\\", "/"),
    ]
    if extra_build_args:
        args.extend(extra_build_args)
    complete_prelude = DEFAULT_PT_PRELUDE + "\n" + prelude
    write_file(
        driver,
        '%s\nset ::STAGE2_AUTO_RUN false\nsource "%s"\nstage2_delay::build %s\n' % (
            complete_prelude,
            TOOL.replace("\\", "/"),
            " ".join('"%s"' % arg for arg in args),
        ),
    )
    proc = subprocess.Popen(
        ["tclsh", driver],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=case_dir,
    )
    stdout, stderr = proc.communicate()
    return {
        "code": proc.returncode,
        "stdout": stdout.decode("utf-8", "replace"),
        "stderr": stderr.decode("utf-8", "replace"),
        "case_dir": case_dir,
        "out_sdc": out_sdc,
        "report": out_report,
        "removed": out_removed,
        "review": out_review,
        "final": out_final,
        "summary": out_summary,
        "driver": driver,
    }


def assert_contains(path, needle):
    text = read_file(path)
    if needle not in text:
        raise AssertionError("Expected %r in %s\n--- file ---\n%s" % (needle, path, text))


def assert_exists(path):
    if not os.path.exists(path):
        raise AssertionError("Expected path to exist: %s" % path)


def assert_not_contains(path, needle):
    text = read_file(path)
    if needle in text:
        raise AssertionError("Did not expect %r in %s\n--- file ---\n%s" % (needle, path, text))


def assert_text_contains(text, needle):
    if needle not in text:
        raise AssertionError("Expected %r in text\n--- text ---\n%s" % (needle, text))


def require_ok(result):
    if result["code"] != 0:
        raise AssertionError(
            "case failed\nstdout=%s\nstderr=%s\ndriver=%s"
            % (result["stdout"], result["stderr"], read_file(result["driver"]))
        )


def test_complete_complete_merge():
    result = run_case(
        "complete_complete",
        "set_max_delay 2.0 -from [get_pins u_src_reg/Q] -to [get_pins u_h0/cfg_i]\n",
        "set_max_delay 5.0 -from [get_pins u_h0/cfg_i] -to [get_pins u_h0/u_reg/D]\n",
    )
    require_ok(result)
    assert_contains(result["out_sdc"], "E2E_DELAY_MERGE_VERSION")
    assert_contains(result["out_sdc"], "set_max_delay 7 -from [get_pins {u_src_reg/Q}] -to [get_pins {u_h0/u_reg/D}]")
    assert_contains(result["removed"], "set_max_delay 2.0")
    assert_contains(result["removed"], "set_max_delay 5.0")
    assert_contains(result["report"], "Merged constraints              : 1")


def test_top_open_from_generates_through():
    result = run_case(
        "top_open_from",
        "set_min_delay 0.2 -to [get_pins u_h0/cfg_i]\n",
        "set_min_delay 0.8 -from [get_pins u_h0/cfg_i] -to [get_pins u_h0/u_reg/D]\n",
    )
    require_ok(result)
    assert_contains(result["out_sdc"], "set_min_delay 1 -through [get_pins {u_h0/cfg_i}] -to [get_pins {u_h0/u_reg/D}]")


def test_harden_open_from_with_explicit_through():
    result = run_case(
        "harden_open_from",
        "set_max_delay 1.5 -from [get_pins u_src_reg/Q] -to [get_pins u_h0/cfg_i]\n",
        "set_max_delay 4.5 -through [get_pins u_h0/cfg_i] -to [get_pins u_h0/u_reg/D]\n",
    )
    require_ok(result)
    assert_contains(result["out_sdc"], "set_max_delay 6 -from [get_pins {u_src_reg/Q}] -to [get_pins {u_h0/u_reg/D}]")


def test_multi_hop_review():
    result = run_case(
        "multi_hop_review",
        "set_max_delay 2.0 -from [get_pins u_up/data_o] -to [get_pins u_h0/cfg_i]\n",
        "set_max_delay 5.0 -from [get_pins u_h0/cfg_i] -to [get_pins u_h0/u_reg/D]\n",
        extra_hardens=[("up", "u_up", "upstream")],
    )
    require_ok(result)
    assert_not_contains(result["out_sdc"], "set_max_delay 7")
    assert_contains(result["review"], "NO_RECURSIVE_CHAIN_MATCHED")


def test_recursive_harden_output_to_harden_input_chain():
    result = run_case(
        "recursive_harden_output_to_input",
        "set_max_delay 2.0 -from [get_pins u_up/data_o] -to [get_pins u_h0/cfg_i]\n",
        "set_max_delay 5.0 -from [get_pins u_h0/cfg_i] -to [get_pins u_h0/u_reg/D]\n",
        extra_hardens=[
            (
                "up",
                "u_up",
                "upstream",
                "set_max_delay 1.0 -from [get_pins u_up/u_reg/Q] -to [get_pins u_up/data_o]\n",
            )
        ],
    )
    require_ok(result)
    assert_contains(result["out_sdc"], "set_max_delay 8 -from [get_pins {u_up/u_reg/Q}] -to [get_pins {u_h0/u_reg/D}]")
    assert_contains(result["report"], "RECURSIVE_MERGED")
    assert_exists(os.path.join(result["summary"], "00_index.csv"))
    assert_exists(os.path.join(result["summary"], "top.csv"))
    assert_exists(os.path.join(result["summary"], "u_up.csv"))
    assert_exists(os.path.join(result["summary"], "u_h0.csv"))
    assert_contains(os.path.join(result["summary"], "00_index.csv"), "u_up.csv")
    assert_contains(os.path.join(result["summary"], "top.csv"), "through_1")
    assert_contains(os.path.join(result["summary"], "top.csv"), "Start Point")
    assert_contains(os.path.join(result["summary"], "top.csv"), "End Point")
    assert_contains(os.path.join(result["summary"], "top.csv"), "start_sdc_delay")
    assert_contains(os.path.join(result["summary"], "top.csv"), "start_from")
    assert_contains(os.path.join(result["summary"], "top.csv"), "start_to")
    assert_contains(os.path.join(result["summary"], "top.csv"), "end_sdc_delay")
    assert_contains(os.path.join(result["summary"], "top.csv"), "end_from")
    assert_contains(os.path.join(result["summary"], "top.csv"), "end_to")
    assert_contains(os.path.join(result["summary"], "top.csv"), "stage_1_sdc_delay")
    assert_contains(os.path.join(result["summary"], "top.csv"), "stage_1_from")
    assert_contains(os.path.join(result["summary"], "top.csv"), "stage_1_to")
    assert_contains(os.path.join(result["summary"], "top.csv"), '"8","u_up/u_reg/Q","1","u_up/u_reg/Q","u_up/data_o","1","u_up/u_reg/Q","u_up/data_o","u_up/data_o","2","u_up/data_o","u_h0/cfg_i","u_h0/cfg_i","5","u_h0/cfg_i","u_h0/u_reg/D","u_h0/u_reg/D","5","u_h0/cfg_i","u_h0/u_reg/D"')
    assert_contains(os.path.join(result["summary"], "u_up.csv"), "set_max_delay 8 -from [get_pins {u_up/u_reg/Q}] -to [get_pins {u_h0/u_reg/D}]")
    assert_contains(os.path.join(result["summary"], "u_h0.csv"), "u_h0/u_reg/D")


def test_edge_specific_review():
    result = run_case(
        "edge_specific_review",
        "set_max_delay 2.0 -rise_from [get_pins u_src_reg/Q] -to [get_pins u_h0/cfg_i]\n",
        "set_max_delay 5.0 -from [get_pins u_h0/cfg_i] -to [get_pins u_h0/u_reg/D]\n",
    )
    require_ok(result)
    assert_contains(result["review"], "EDGE_SPECIFIC_OPTION")


def test_multi_object_lists_expand_and_rewrite_remaining():
    result = run_case(
        "multi_object_lists",
        "set_max_delay 2.0 -from [get_pins u_src_reg/Q] -to [list [get_pins u_h0/cfg_i] [get_pins u_h0/unused_i]]\n",
        "set_max_delay 5.0 -from [list [get_pins u_h0/cfg_i] [get_pins u_h0/other_i]] -to [get_pins u_h0/u_reg/D]\n",
    )
    require_ok(result)
    assert_contains(result["out_sdc"], "set_max_delay 7 -from [get_pins {u_src_reg/Q}] -to [get_pins {u_h0/u_reg/D}]")
    assert_contains(result["report"], "Merged constraints              : 1")
    assert_contains(result["report"], "Review required constraints     : 2")
    assert_contains(result["removed"], "split=1/2")
    assert_contains(result["removed"], "set_max_delay 2 -from [get_pins {u_src_reg/Q}] -to [get_pins {u_h0/cfg_i}]")
    assert_contains(result["final"], "STAGE2_REWRITTEN CMD000001")
    assert_contains(result["final"], "set_max_delay 2 -from [get_pins {u_src_reg/Q}] -to [get_pins {u_h0/unused_i}]")
    assert_contains(result["final"], "STAGE2_REWRITTEN CMD000002")
    assert_contains(result["final"], "set_max_delay 5 -from [get_pins {u_h0/other_i}] -to [get_pins {u_h0/u_reg/D}]")


def test_one_top_boundary_reused_for_multiple_harden_endpoints():
    result = run_case(
        "reuse_top_boundary_for_multi_to",
        "set_max_delay 2.0 -from [get_pins u_src_reg/Q] -to [get_pins u_h0/cfg_i]\n",
        "set_max_delay 5.0 -from [get_pins u_h0/cfg_i] -to [list [get_pins u_h0/u_cfg_reg/D] [get_pins u_h0/u_mode_reg/D]]\n",
    )
    require_ok(result)
    assert_contains(result["out_sdc"], "set_max_delay 7 -from [get_pins {u_src_reg/Q}] -to [get_pins {u_h0/u_cfg_reg/D}]")
    assert_contains(result["out_sdc"], "set_max_delay 7 -from [get_pins {u_src_reg/Q}] -to [get_pins {u_h0/u_mode_reg/D}]")
    assert_contains(result["report"], "Merged constraints              : 2")


def test_top_port_maps_to_connected_harden_input():
    prelude = r'''
proc current_design {} {
    return current_integration_top
}

proc sizeof_collection {coll} {
    return [llength $coll]
}

proc foreach_in_collection {var coll body} {
    upvar 1 $var item
    foreach item $coll {
        uplevel 1 $body
    }
}

proc get_ports {args} {
    set name [lindex $args end]
    if {$name eq "cfg_top"} {
        return [list cfg_top]
    }
    return {}
}

proc get_nets {args} {
    set obj [lindex $args end]
    if {$obj eq "cfg_top"} {
        return [list cfg_net]
    }
    return {}
}

proc get_pins {args} {
    if {[lsearch -exact $args "-of_objects"] >= 0} {
        set obj [lindex $args end]
        if {$obj eq "cfg_net"} {
            return [list u_h0/cfg_i]
        }
        return {}
    }
    set name [lindex $args end]
    if {$name in {u_src_reg/Q u_h0/cfg_i u_h0/u_reg/D}} {
        return [list $name]
    }
    return {}
}

proc get_attribute {obj attr} {
    set name [lindex $obj 0]
    if {$attr eq "full_name"} {
        return $name
    }
    if {$attr eq "direction"} {
        if {$name eq "cfg_top"} {
            return out
        }
        if {$name eq "u_src_reg/Q"} {
            return out
        }
        if {$name in {u_h0/cfg_i u_h0/u_reg/D}} {
            return in
        }
    }
    return ""
}
'''
    result = run_case(
        "top_port_boundary_map",
        "set_max_delay 2.0 -from [get_pins u_src_reg/Q] -to [get_ports cfg_top]\n",
        "set_max_delay 5.0 -from [get_pins u_h0/cfg_i] -to [get_pins u_h0/u_reg/D]\n",
        extra_build_args=["-verbose_pt_query", "true"],
        prelude=prelude,
    )
    require_ok(result)
    assert_contains(result["out_sdc"], "set_max_delay 7 -from [get_pins {u_src_reg/Q}] -to [get_pins {u_h0/u_reg/D}]")
    assert_contains(result["report"], "TOP_PORT_BOUNDARY_MAP")
    assert_contains(result["report"], "Top port boundary map mode      : connectivity")
    assert_contains(result["report"], "Verbose PT query                : true")
    assert_contains(result["final"], "STAGE2_CONSUMED CMD000001")
    assert_text_contains(result["stdout"], "PT_QUERY: get_ports -quiet {cfg_top}")


def test_harden_input_to_output_boundary_merges():
    result = run_case(
        "harden_input_to_output_boundary_merge",
        "set_max_delay 1.0 -from [get_pins u_src_reg/Q] -to [get_pins u_h0/i_niu_rst_n]\n",
        "set_max_delay 5.0 -from [get_ports i_niu_rst_n] -to [get_ports o_niu_rst_n]\n",
    )
    require_ok(result)
    assert_contains(result["out_sdc"], "set_max_delay 6 -from [get_pins {u_src_reg/Q}] -to [get_pins {u_h0/o_niu_rst_n}]")
    assert_contains(result["report"], "Merged constraints              : 1")
    assert_not_contains(result["report"], "OUTPUT_DIRECTION_NOT_SUPPORTED")


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    tests = [
        test_complete_complete_merge,
        test_top_open_from_generates_through,
        test_harden_open_from_with_explicit_through,
        test_multi_hop_review,
        test_recursive_harden_output_to_harden_input_chain,
        test_edge_specific_review,
        test_multi_object_lists_expand_and_rewrite_remaining,
        test_one_top_boundary_reused_for_multiple_harden_endpoints,
        test_top_port_maps_to_connected_harden_input,
        test_harden_input_to_output_boundary_merges,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    shutil.rmtree(WORK)
    print("All Stage 2 regression tests passed.")


if __name__ == "__main__":
    main()
