#!/usr/bin/env python3
"""Regression smoke tests for proc_harden_sdc.py.

The tests are intentionally small and standard-library only so they can run
under Python 3.6 in the same environment expected for the converter.
"""

from __future__ import print_function

import os
import shutil
import subprocess
import sys


HERE = os.path.abspath(os.path.dirname(__file__))
TOOL = os.path.abspath(os.path.join(HERE, "..", "proc_harden_sdc.py"))
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


def run_tool(case_name, input_text, extra_args=None):
    case_dir = os.path.join(WORK, case_name)
    if os.path.isdir(case_dir):
        shutil.rmtree(case_dir)
    os.makedirs(case_dir)
    input_path = os.path.join(case_dir, "input.sdc")
    out_path = os.path.join(case_dir, "soc.sdc")
    removed_path = os.path.join(case_dir, "removed.sdc")
    unsupported_path = os.path.join(case_dir, "unsupported.sdc")
    modified_path = os.path.join(case_dir, "modified_details.txt")
    report_path = os.path.join(case_dir, "report.txt")
    write_file(input_path, input_text)
    cmd = [
        sys.executable,
        TOOL,
        "--in", input_path,
        "--out", out_path,
        "--removed-out", removed_path,
        "--unsupported-out", unsupported_path,
        "--modified-details", modified_path,
        "--report", report_path,
        "--inst", "u_soc/u_avfs/u_awm3_0",
    ]
    if extra_args:
        cmd.extend(extra_args)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    return {
        "code": proc.returncode,
        "stdout": stdout.decode("utf-8", "replace"),
        "stderr": stderr.decode("utf-8", "replace"),
        "case_dir": case_dir,
        "out": out_path,
        "removed": removed_path,
        "unsupported": unsupported_path,
        "modified": modified_path,
        "report": report_path,
    }


def assert_contains(path, needle):
    text = read_file(path)
    if needle not in text:
        raise AssertionError("Expected %r in %s\n--- file ---\n%s" % (needle, path, text))


def assert_not_contains(path, needle):
    text = read_file(path)
    if needle in text:
        raise AssertionError("Did not expect %r in %s\n--- file ---\n%s" % (needle, path, text))


def assert_command_lines_not_contains(path, needle):
    text = read_file(path)
    offenders = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if needle in line:
            offenders.append(line)
    if offenders:
        raise AssertionError("Did not expect %r in command lines of %s\n%s" % (needle, path, "\n".join(offenders)))


def assert_order(path, first, second):
    text = read_file(path)
    first_index = text.find(first)
    second_index = text.find(second)
    if first_index < 0 or second_index < 0 or first_index >= second_index:
        raise AssertionError("Expected %r before %r in %s\n--- file ---\n%s" % (first, second, path, text))


def test_clean_mapping():
    sdc = """\
# leading comment
set_units -time ns -capacitance pF -resistance ohm -voltage V -current mA
set period_margin 0.05
create_clock -name clk -period 1.0 [get_ports clk]
create_clock -name tclk -period 2.0 [get_pins u_test/clk_gen/Q]
create_generated_clock -name div2_clk \\
  -source [get_ports clk] \\
  -divide_by 2 \\
  [get_pins u_div/u_ff/Q]
set_min_pulse_width 0.5 [get_clocks div2_clk]
set_false_path -from [get_pins u_sync/u_ff1/Q] -to [get_pins u_sync/u_ff2/D]
set_false_path -from [get_ports rst_n] -to [get_pins u_sync/u_ff2/D] # async reset
set_clock_groups -asynchronous -group [get_clocks div2_clk] -group [get_clocks other]
source extra.sdc
"""
    result = run_tool("clean_mapping", sdc)
    if result["code"] != 0:
        raise AssertionError("clean_mapping failed\nstdout=%s\nstderr=%s\nreport=%s" % (
            result["stdout"],
            result["stderr"],
            read_file(result["report"]),
        ))
    assert_contains(result["report"], "Conversion status      : REVIEW_REQUIRED")
    assert_contains(result["out"], "create_clock -name u_soc_u_avfs_u_awm3_0_tclk")
    assert_not_contains(result["removed"], "unused_kept_clock_definition")
    assert_contains(result["out"], "create_generated_clock -name u_soc_u_avfs_u_awm3_0_div2_clk")
    assert_contains(result["out"], "[get_pins u_soc/u_avfs/u_awm3_0/clk]")
    assert_contains(result["out"], "[get_clocks u_soc_u_avfs_u_awm3_0_div2_clk]")
    assert_command_lines_not_contains(result["out"], "get_ports")
    assert_contains(result["removed"], "create_clock_on_block_port")
    assert_contains(result["removed"], "soc_clock_relationship_owned_by_top")
    assert_contains(result["unsupported"], "source_or_scope_command")
    assert_contains(result["modified"], "clock_name_renamed")
    assert_contains(result["report"], "clk ->")
    assert_contains(result["report"], "div2_clk -> u_soc_u_avfs_u_awm3_0_div2_clk")
    assert_not_contains(result["out"], "# !!! REVIEW_REQUIRED COMMANDS BEGIN !!!")
    assert_contains(result["removed"], "boundary_exception_owned_by_30")
    assert_contains(result["report"], "Boundary get_ports constraint removed from cleaned harden SDC")
    out_text = read_file(result["out"])
    review_cmd = "set_false_path -from [get_pins u_soc/u_avfs/u_awm3_0/rst_n] -to [get_pins u_soc/u_avfs/u_awm3_0/u_sync/u_ff2/D]"
    if out_text.count(review_cmd) != 0:
        raise AssertionError("boundary get_ports exception should not appear in main SDC")


def test_dangling_reference_removed():
    sdc = """\
create_clock -name clk -period 1.0 [get_ports clk]
set_min_pulse_width 0.5 [get_clocks clk]
"""
    result = run_tool("dangling_reference", sdc)
    if result["code"] != 0:
        raise AssertionError("dangling_reference should be REVIEW_REQUIRED/CLEAN, not invalid")
    assert_contains(result["removed"], "dangling_clock_reference_related:clk")
    assert_not_contains(result["out"], "set_min_pulse_width")
    assert_contains(result["report"], "[DANGLING_CLOCK_REFERENCES]")


def test_clock_mapping_allows_removed_port_clock():
    sdc = """\
create_clock -name clk -period 1.0 [get_ports clk]
set_min_pulse_width 0.5 [get_clocks clk]
"""
    mapping = os.path.join(WORK, "clock_mapping.csv")
    write_file(mapping, "block_clock_name,soc_clock_name\nclk,soc_core_clk\n")
    result = run_tool("clock_mapping", sdc, ["--clock-mapping-file", mapping])
    if result["code"] != 0:
        raise AssertionError("clock_mapping failed")
    assert_contains(result["out"], "[get_clocks soc_core_clk]")
    assert_not_contains(result["out"], "[get_clocks clk]")


def test_list_wrapper_mapping():
    sdc = """\
set_false_path -from [list [get_ports rst_n] [get_pins u_a/Q]] -to [list [get_pins u_b/D]]
"""
    result = run_tool("list_wrapper_mapping", sdc)
    if result["code"] != 0:
        raise AssertionError("list_wrapper_mapping failed")
    assert_not_contains(result["out"], "set_false_path")
    assert_contains(result["removed"], "boundary_exception_owned_by_30")
    assert_not_contains(result["unsupported"], "set_false_path")


def test_single_boundary_delay_salvage():
    sdc = """\
set_max_delay 0.8 -from [get_ports A] -to [get_pins u_sink/D]
set_min_delay 0.1 -from [get_pins u_src/Q] -to [get_ports B]
set_max_delay 0.7 -from [get_ports A] -to [get_ports B]
set_false_path -from [get_ports rst_n] -to [get_pins u_sync/D]
"""
    result = run_tool("single_boundary_delay_salvage", sdc)
    if result["code"] != 0:
        raise AssertionError("single_boundary_delay_salvage failed")
    assert_contains(result["out"], "set_max_delay 0.8 -from [get_pins u_soc/u_avfs/u_awm3_0/A] -to [get_pins u_soc/u_avfs/u_awm3_0/u_sink/D]")
    assert_contains(result["out"], "set_min_delay 0.1 -from [get_pins u_soc/u_avfs/u_awm3_0/u_src/Q] -to [get_pins u_soc/u_avfs/u_awm3_0/B]")
    assert_not_contains(result["out"], "[get_ports")
    assert_contains(result["out"], "# REVIEW_REQUIRED command_id=000001")
    assert_contains(result["out"], "# REVIEW_REQUIRED command_id=000002")
    assert_contains(result["out"], "Boundary from side was mapped get_ports -> get_pins with instance hierarchy for set_max_delay")
    assert_contains(result["out"], "Boundary to side was mapped get_ports -> get_pins with instance hierarchy for set_min_delay")
    assert_contains(result["modified"], "boundary_from_mapped_keep_path")
    assert_contains(result["modified"], "boundary_to_mapped_keep_path")
    assert_contains(result["removed"], "boundary_delay_owned_by_10_20_30")
    assert_contains(result["removed"], "boundary_exception_owned_by_30")


def test_oversize_shallow_mapping():
    sdc = """\
# set_multicycle_path 9 -from [get_pins should_not_parse/Q] -to [get_pins should_not_parse/D]
set_multicycle_path 2 -setup -from [get_pins u_src_reg/Q] -through [list [get_pins u_mid0_reg/Q] [get_pins u_mid1_reg/Q]] -to [get_pins u_dst_reg/D]
"""
    result = run_tool("oversize_shallow_mapping", sdc, ["--oversize-command-chars", "80"])
    if result["code"] != 0:
        raise AssertionError("oversize_shallow_mapping failed")
    assert_contains(result["out"], "set_multicycle_path 2 -setup -from [get_pins u_soc/u_avfs/u_awm3_0/u_src_reg/Q] -through [list [get_pins u_soc/u_avfs/u_awm3_0/u_mid0_reg/Q] [get_pins u_soc/u_avfs/u_awm3_0/u_mid1_reg/Q]] -to [get_pins u_soc/u_avfs/u_awm3_0/u_dst_reg/D]")
    assert_contains(result["out"], "oversize_shallow_mapped")
    assert_contains(result["out"], "Oversize command used shallow object mapping only")
    assert_not_contains(result["out"], "should_not_parse")
    assert_command_lines_not_contains(result["out"], "get_ports")


def test_review_block_after_clock_definitions():
    sdc = """\
create_generated_clock -name div2_clk -source [get_pins u_clk/Q] -divide_by 2 [get_pins u_div/Q]
set_min_pulse_width 0.5 [get_clocks div2_clk]
set_false_path -from [get_cells -hierarchical u_async/*] -to [get_pins u_b/D]
"""
    result = run_tool("review_after_clock", sdc)
    if result["code"] != 0:
        raise AssertionError("review_after_clock failed")
    assert_contains(result["out"], "# !!! REVIEW_REQUIRED COMMANDS BEGIN !!!")
    assert_contains(result["out"], "# REVIEW_NOTE: get_cells -hierarchical pattern was instance-prefixed: u_async/*")
    assert_order(result["out"], "create_generated_clock -name u_soc_u_avfs_u_awm3_0_div2_clk", "# !!! REVIEW_REQUIRED COMMANDS BEGIN !!!")
    assert_order(result["out"], "# !!! REVIEW_REQUIRED COMMANDS END !!!", "set_min_pulse_width 0.5 [get_clocks u_soc_u_avfs_u_awm3_0_div2_clk]")


def test_virtual_create_clock_renamed():
    sdc = """\
create_clock -name refclk -period 5 -waveform {0 2.5}
set_min_pulse_width 0.5 [get_clocks refclk]
"""
    result = run_tool("virtual_create_clock", sdc)
    if result["code"] != 0:
        raise AssertionError("virtual_create_clock failed")
    assert_contains(result["out"], "create_clock -name u_soc_u_avfs_u_awm3_0_refclk")
    assert_contains(result["out"], "[get_clocks u_soc_u_avfs_u_awm3_0_refclk]")
    assert_contains(result["report"], "refclk -> u_soc_u_avfs_u_awm3_0_refclk")
    assert_not_contains(result["unsupported"], "create_clock")


def test_unused_virtual_create_clock_kept():
    sdc = """\
create_clock -name refclk -period 5 -waveform {0 2.5}
set_false_path -from [get_pins u_a/Q] -to [get_pins u_b/D]
"""
    result = run_tool("unused_virtual_create_clock", sdc)
    if result["code"] != 0:
        raise AssertionError("unused_virtual_create_clock failed")
    assert_contains(result["out"], "create_clock -name u_soc_u_avfs_u_awm3_0_refclk")
    assert_not_contains(result["removed"], "unused_kept_clock_definition")
    assert_contains(result["report"], "Unused kept create_clock/create_generated_clock definitions are preserved by policy.")


def test_units_mismatch_fatal():
    sdc = """\
set_units -time ps
set_false_path -from [get_pins u_a/Q] -to [get_pins u_b/D]
"""
    result = run_tool("units_mismatch", sdc)
    if result["code"] == 0:
        raise AssertionError("units_mismatch should fail")
    assert_contains(result["report"], "Conversion status      : INVALID_OUTPUT")
    assert_contains(result["report"], "set_units_mismatch")
    assert_contains(result["out"], "Main SDC body suppressed")


def test_structural_error_fatal():
    sdc = "set_false_path -from [get_pins u_a/Q -to [get_pins u_b/D]\n"
    result = run_tool("structural_error", sdc)
    if result["code"] == 0:
        raise AssertionError("structural_error should fail")
    assert_contains(result["report"], "[NORMALIZATION_ERROR]")
    assert_contains(result["out"], "Main SDC body suppressed")


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    tests = [
        test_clean_mapping,
        test_dangling_reference_removed,
        test_clock_mapping_allows_removed_port_clock,
        test_list_wrapper_mapping,
        test_single_boundary_delay_salvage,
        test_oversize_shallow_mapping,
        test_review_block_after_clock_definitions,
        test_virtual_create_clock_renamed,
        test_unused_virtual_create_clock_kept,
        test_units_mismatch_fatal,
        test_structural_error_fatal,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("All regression tests passed.")


if __name__ == "__main__":
    main()
