# 01 -> 02 Target Runtime Demo

This example runs the two stages through one target-layout run root:

```text
01_soc_clocks
  -> 01_middle/assembled/common/clock_inventory.csv + meta
  -> 01_result/common/01_soc_clocks.sdc
02_soc_clock_timing
  -> 02_middle/02_soc_clock_timing_budget_prects.xlsx
  -> 02_middle/resolved/common_prects_ss_125.manifest
  -> 02_result/common/02_soc_clock_timing_prects_ss_125.sdc
```

Run:

```bash
python3 run_demo.py
```

The first 02 invocation intentionally exits with code 1 after creating the review workbook. `fill_budget.py` fills the budget, then the second 02 invocation validates the 01 inventory/meta/final SDC and generates the final clock timing SDC.
