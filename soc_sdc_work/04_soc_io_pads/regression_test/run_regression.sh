#!/usr/bin/env bash
# One-shot regression for 04_extract_soc_io_pads.py
# Rebuilds inputs, drives sync -> review -> generate across views, and asserts
# exit codes + key SDC lines. Run from this directory.
set -u
cd "$(dirname "$0")"

TOOL="../04_extract_soc_io_pads.py"
INV="clock_inventory.csv"
PASS=0
FAIL=0

ok()   { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

assert_exit() { # want got label
  [ "$1" = "$2" ] && ok "$3 (exit=$2)" || bad "$3 (want exit $1, got $2)"
}
assert_grep() { # file pattern label
  grep -qE "$2" "$1" 2>/dev/null && ok "$3" || bad "$3 (missing /$2/ in $1)"
}
assert_no_grep() { # file pattern label
  grep -qE "$2" "$1" 2>/dev/null && bad "$3 (unexpected /$2/ in $1)" || ok "$3"
}
gen() { python3 "$TOOL" "$@" -input "$INV" >/dev/null 2>&1; echo $?; }

echo "== clean & build inputs =="
rm -rf common scenarios 04_soc_io_pads.xlsx io_pad_check_report_*.txt "$INV" \
       info_all.xlsx ports_u_io.xlsx u_io.sdc __pycache__
python3 build_inputs.py >/dev/null

echo "== [1] first run: sync must stop for review (exit 1) =="
ec=$(gen -scenario common)
assert_exit 1 "$ec" "sync stops with exit 1"
[ -f 04_soc_io_pads.xlsx ] && ok "workbook created" || bad "workbook created"

echo "== [2] apply review + targeted cases =="
python3 approve.py    >/dev/null
python3 add_cases.py  >/dev/null

echo "== [3] generate common all/all =="
ec=$(gen -scenario common)
assert_exit 0 "$ec" "common generation"
C=common/04_soc_io_pads.sdc
assert_grep "$C" 'set_input_delay -clock \[get_clocks \{v_uart_rx\}\] -max 5 \[get_ports \{pad_uart0_sin\}\]' "uart sin input_delay"
assert_grep "$C" 'set_output_delay -clock \[get_clocks \{v_uart_tx\}\] -max 4 \[get_ports \{pad_uart0_sout\}\]' "uart sout output_delay"
assert_grep "$C" 'set_load 0.05 \[get_ports \{pad_uart0_sout\}\]' "uart sout load"
# B1: multi-edge add_delay is command-level -> only the base -min lacks -add_delay
assert_grep    "$C" 'set_input_delay -clock \[get_clocks \{dqs_clk\}\] -min 0.1 \[get_ports \{pad_dq0\}\]' "dq0 base -min present"
assert_no_grep "$C" 'min 0.1 -add_delay|-add_delay -min 0.1' "dq0 base -min has NO -add_delay"
assert_grep    "$C" '\-max -add_delay 0.8' "dq0 -max carries -add_delay"
assert_grep    "$C" '\-rise -add_delay 0.05' "dq0 -rise carries -add_delay"
assert_grep    "$C" '\-fall -add_delay 0.06' "dq0 -fall carries -add_delay"
assert_no_grep "$C" 'pad_gpio0' "gpio0 NOT in common (direction-split)"

echo "== [4] generate gpio_in scenario =="
ec=$(gen -scenario gpio_in)
assert_exit 0 "$ec" "gpio_in generation"
assert_grep scenarios/gpio_in_io_pads.sdc 'set_input_delay .* \[get_ports \{pad_gpio0\}\]' "gpio0 routed to gpio_in"

echo "== [5] generate view-specific prects/ss_125 (clean) =="
ec=$(gen -scenario common -stage prects -corner ss_125)
assert_exit 0 "$ec" "prects/ss_125 generation"
V=common/04_soc_io_pads_prects_ss_125.sdc
assert_grep    "$V" 'set_load 0.03 \[get_ports \{pad_ddr_dqs\}\]' "view-specific dqs load"
assert_no_grep "$V" 'pad_uart0|pad_dq0' "view-specific file excludes all/all rows"
cp "$V" /tmp/_04_view_prev.sdc

echo "== [6] inject view-indep vs view-specific conflict -> error, no regen =="
python3 inject_conflict.py >/dev/null
ec=$(gen -scenario common -stage prects -corner ss_125)
assert_exit 1 "$ec" "conflict blocks prects/ss_125 generation"
assert_grep io_pad_check_report_common_prects_ss_125.txt \
  'ERROR: assembled view duplicate/conflict for pad=pad_ddr_dqs constraint_type=load' "conflict reported"
diff -q /tmp/_04_view_prev.sdc "$V" >/dev/null && ok "view-specific SDC unchanged after error" \
  || bad "view-specific SDC unchanged after error"

echo "== [7] all/all run stays clean despite the view conflict =="
ec=$(gen -scenario common)
assert_exit 0 "$ec" "all/all unaffected by view-specific conflict"

echo
echo "================ RESULT: $PASS passed, $FAIL failed ================"
[ "$FAIL" -eq 0 ]
