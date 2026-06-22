#!/usr/bin/env bash
# One-shot regression for 10_extract_harden_x_if.py
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/soc_sdc_10_regression.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

PYTHON_BIN="${PYTHON_BIN:-python3}"
EXTRACT_SCRIPT="$SCRIPT_DIR/../10_extract_harden_x_if.py"

cd "$WORK_DIR"

"$PYTHON_BIN" "$SCRIPT_DIR/build_inputs.py"

set +e
"$PYTHON_BIN" -B "$EXTRACT_SCRIPT" -input clock_inventory.csv > first_run.log 2>&1
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
  echo "expected first run to stop after workbook sync" >&2
  exit 1
fi
test -f 10_harden_x_if.xlsx

"$PYTHON_BIN" "$SCRIPT_DIR/approve.py"
"$PYTHON_BIN" -B "$EXTRACT_SCRIPT" -input clock_inventory.csv --max-diff-threshold 0.1 > normal_run.log 2>&1

grep -q "set_max_delay 1.2 -datapath_only -from \\[get_pins {u_a/data_o}\\] -to \\[get_pins {u_b/data_i}\\]" common/10_harden_x_if.sdc
grep -q "auto-resolved converted_max=1.2" harden_x_if_check_report_common_all_all.txt
grep -q "wrote 3 auto-resolved field(s) back" harden_x_if_check_report_common_all_all.txt
grep -q "CH_u_a_data_o__fabric_fabric_bus: type=harden_to_fabric" harden_x_if_check_report_common_all_all.txt

"$PYTHON_BIN" "$SCRIPT_DIR/approve.py" --async-relation
set +e
"$PYTHON_BIN" -B "$EXTRACT_SCRIPT" -input clock_inventory.csv > async_run.log 2>&1
rc=$?
set -e
if [[ "$rc" -eq 0 ]]; then
  echo "expected async relation to block generation" >&2
  exit 1
fi
grep -q "clock_relation=async blocks normal 10 budget" harden_x_if_check_report_common_all_all.txt

echo "10_harden_x_if regression passed in $WORK_DIR"
