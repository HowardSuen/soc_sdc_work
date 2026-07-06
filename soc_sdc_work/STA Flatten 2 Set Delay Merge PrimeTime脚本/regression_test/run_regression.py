#!/usr/bin/env python3
"""Regression smoke tests for run_stage2_merge_delay.tcl.

The tests run with plain tclsh and use the script's non-PT fallback paths.
They do not replace PrimeTime validation, but they keep parsing, matching,
reporting, and static SDC emission deterministic.
"""

from __future__ import print_function

import os
import shutil
import subprocess
import sys


HERE = os.path.abspath(os.path.dirname(__file__))
TOOL = os.path.abspath(os.path.join(HERE, "..", "run_stage2_merge_delay.tcl"))
WORK = os.path.join(HERE, "work")


def write_file(path, text):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as fout:
        fout.write(text)


def read_file(path):
    with open(path, "r") as fin:
        return fin.read()


def run_case(case_name, top_sdc, harden_sdc, extra_build_args=None, extra_hardens=None):
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
    driver = os.path.join(case_dir, "run.tcl")
    write_file(top_path, top_sdc)
    write_file(harden_path, harden_sdc)
    rows = [
        "harden_name,inst_path,clean_sdc,delay_candidate_file,netlist,module",
        "h0,u_h0,%s,,h0.v,harden0" % harden_path.replace("\\", "/"),
    ]
    for item in extra_hardens or []:
        rows.append("%s,%s,,,,%s" % (item[0], item[1], item[2] if len(item) > 2 else item[0]))
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
    write_file(
        driver,
        'set ::STAGE2_AUTO_RUN false\nsource "%s"\nstage2_delay::build %s\n' % (
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
        "driver": driver,
    }


def assert_contains(path, needle):
    text = read_file(path)
    if needle not in text:
        raise AssertionError("Expected %r in %s\n--- file ---\n%s" % (needle, path, text))


def assert_not_contains(path, needle):
    text = read_file(path)
    if needle in text:
        raise AssertionError("Did not expect %r in %s\n--- file ---\n%s" % (needle, path, text))


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
    assert_contains(result["review"], "MULTI_HOP_NOT_SUPPORTED")


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


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    tests = [
        test_complete_complete_merge,
        test_top_open_from_generates_through,
        test_harden_open_from_with_explicit_through,
        test_multi_hop_review,
        test_edge_specific_review,
        test_multi_object_lists_expand_and_rewrite_remaining,
        test_one_top_boundary_reused_for_multiple_harden_endpoints,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    shutil.rmtree(WORK)
    print("All Stage 2 regression tests passed.")


if __name__ == "__main__":
    main()
