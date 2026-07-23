# Harden DC SDC to SoC SDC

独立脚本目录，按 `Harden_DC_SDC_to_SoC_SDC_v2.3.1_final.docx` 规则开发。

## 入口

```bash
python3 run_stage1_clean_sdc.py \
  --in  <input_dc_sdc> \
  --out <output_soc_sdc> \
  --removed-out <removed_sdc> \
  --unsupported-out <unsupported_sdc> \
  --modified-details <modified_details> \
  --report <report_file> \
  --inst <harden_instance_name>
```

脚本只依赖 Python 标准库，按 Python 3.6 语法约束实现。

## 输出

- `<output_soc_sdc>`：SoC STA 可 source 的 clean SDC；若转换为 `INVALID_OUTPUT`，主 SDC body 会被抑制。需要人工复核但仍可 source 的 `REVIEW_REQUIRED` 约束会放在 header 后、普通约束前的醒目 `REVIEW_REQUIRED COMMANDS BEGIN/END` 区块中。
- `<removed_sdc>`：明确按规则删除的命令。
- `<unsupported_sdc>`：脚本无法安全转换、需要人工 review 的命令。
- `<modified_details>`：所有 `MODIFY` 命令的 before/after 全量追溯。
- `<report_file>`：summary、clock rename map、dangling clock、unit check、consistency violation 等。

## 默认 policy

- `create_clock` on `get_ports`：REMOVE。
- `create_clock` on internal object：MODIFY，并强制 clock rename，格式为 `<instance_prefix>_<old_clock_name>`。
- `create_generated_clock` / `create_generate_clock`：MODIFY，并强制 clock rename，格式为 `<instance_prefix>_<old_clock_name>`。
- 保留的 `create_clock` / `create_generated_clock` 不再因为最终主 SDC 中暂时没有其它 `get_clocks` 引用而删除；是否与 SoC 顶层 clock 重复由 report 和 STA post-check review。
- `get_ports <name>`：映射为 `get_pins <inst>/<name>`。
- 裸 `get_ports`、`get_ports *`、危险 `all_*`：不进入主 SDC。
- `set_max_delay` / `set_min_delay` 涉及 harden boundary `get_ports`：保留整条 path 约束，将 boundary `get_ports` 映射为 SoC scope 下的 `get_pins <inst>/<port>`，内部对象同步上升 hierarchy，并放入 `REVIEW_REQUIRED` 区块；`-from get_ports -to get_ports` 两端都映射后保留。
- `set_multicycle_path` 涉及 harden boundary `get_ports`：保留并映射为 `get_pins <inst>/<port>`，其它内部对象同步上升 hierarchy，同时放入 `REVIEW_REQUIRED` 区块确认 timing exception 语义。
- `set_false_path` / `set_case_analysis` 只要直接涉及 harden boundary `get_ports`：不进入 cleaned harden SDC，转交 scenario pre、30 或 SoC 级 review。
- `set_input_delay` / `set_output_delay`、clock group、clock budget、RC/SPEF/derate、global library/report constraint：REMOVE。
- `set_units`：匹配 `--expect-units` 时 REMOVE；mismatch 为 fatal `INVALID_OUTPUT`。
- `source`、`current_design`、`current_instance`、复杂 Tcl / collection 操作、未分类命令：UNSUPPORTED。
- 命中 removed clock definition 的 `get_clocks` 引用：默认 REMOVE；`--strict` 下 ERROR。
- 整行注释会在 Tcl 解析前丢弃并保留行号，避免 DC 输出的大型注释约束拖慢转换。
- 单条有效命令超过 `--oversize-command-chars` 阈值时，跳过深度递归检查，改用浅层对象映射：只处理明确的 bracket get command，例如 `[get_pins u_a/Q]`、`[get_ports A]`，以及 safe `[list [get_pins ...] ...]` wrapper；无法安全浅层映射的变量、通配、`get_clocks`、非 safe 嵌套 collection 或复杂 option 进入 `unsupported.sdc`。
- unsupported count > 0：`REVIEW_REQUIRED`；`--strict` 下 `INVALID_OUTPUT`。
- Stage1 幂等保护只识别本脚本 `run_stage1_clean_sdc.py`（兼容旧名 `proc_harden_sdc.py`）生成的明确文件头；允许 `run_stage2_merge_delay.tcl` 生成的 Stage2 flatten SDC 作为输入。通用的 `SDC_PROCESS_VERSION` 不再单独作为“已被 Stage1 处理”的判据。

## REVIEW_REQUIRED 主 SDC 区块

主 SDC 中如果存在需要人工复核但脚本仍判定可 source 的命令，例如 scoped `get_cells -hierarchical` 被 instance prefix 后的内部约束，脚本会把这些命令输出到独立区块。为了保证 source 顺序安全，必要的 local clock definition 会先输出，随后才是 `REVIEW_REQUIRED` 区块：

```tcl
# !!! REVIEW_REQUIRED COMMANDS BEGIN !!!
# REVIEW_REQUIRED command_id=000008 line=12 type=set_false_path reason=get_cells_mapped
# REVIEW_NOTE: get_cells -hierarchical pattern was instance-prefixed: u_async/*
set_false_path -from [get_cells -hierarchical u_soc/u_blk/u_async/*] -to [get_pins u_soc/u_blk/u_sync/u_ff2/D]
# !!! REVIEW_REQUIRED COMMANDS END !!!
```

这些命令不会在后续普通 body 中重复输出。直接涉及 harden boundary `get_ports` 的 `set_false_path` / `set_case_analysis` 会进入 `removed.sdc`，不会进入该区块。

`set_max_delay` / `set_min_delay` 如果 endpoint 涉及 boundary `get_ports`，脚本会保留整条 path，并把 boundary `get_ports` 映射为 SoC scope 下的 harden instance pin。保留后的命令会进入 `REVIEW_REQUIRED` 区块。例如：

```tcl
# 原始
set_max_delay 0.8 -from [get_ports A] -to [get_pins u_sink/D]

# cleaned harden SDC
set_max_delay 0.8 -from [get_pins u_soc/u_blk/A] -to [get_pins u_soc/u_blk/u_sink/D]
```

`-from get_ports -to get_ports` 两端都会映射：

```tcl
# 原始
set_max_delay 0.7 -from [get_ports A] -to [get_ports B]

# cleaned harden SDC
set_max_delay 0.7 -from [get_pins u_soc/u_blk/A] -to [get_pins u_soc/u_blk/B]
```

该保留表示 harden boundary pin 相关原 path 语义被尽量保留；仍需人工确认其是否属于 cleaned harden SDC，而不是 SoC interface timing。

`set_multicycle_path` 不做 Stage1 删除。涉及 boundary `get_ports` 时同样映射为 SoC scope 下的 harden instance pin，并进入 `REVIEW_REQUIRED` 区块。例如：

```tcl
# 原始
set_multicycle_path 2 -setup -from [get_ports A] -to [get_pins u_dst/D]

# cleaned harden SDC
set_multicycle_path 2 -setup -from [get_pins u_soc/u_blk/A] -to [get_pins u_soc/u_blk/u_dst/D]
```

## Clock mapping

如果 block port clock 被删除，但内部 exception 仍需引用 SoC 顶层同源 clock，推荐使用 mapping file：

```csv
block_clock_name,soc_clock_name
clk,soc_core_clk
scan_clk,soc_scan_clk
```

运行时添加：

```bash
--clock-mapping-file clock_mapping.csv
```

或临时使用：

```bash
--allow-soc-clock <clock_name>
```

## 回归

```bash
python3 regression_test/run_regression.py
```

当前 regression 覆盖：

- port primary clock 删除。
- internal/generated clock 改名和 hierarchy mapping。
- 未被其它保留约束引用的 internal/virtual/generated clock definition 仍保留。
- `get_clocks` rename 追随。
- dangling clock reference 删除。
- clock mapping file 放行。
- `set_units` mismatch fatal。
- command boundary structural failure fatal。
- 主 SDC 顶部 `REVIEW_REQUIRED` 醒目区块。
- boundary `get_ports` 的 `set_max_delay` / `set_min_delay` 映射并进入 `REVIEW_REQUIRED`，包含 `-from get_ports -to get_ports`。
- boundary `get_ports` 的 `set_multicycle_path` 映射并进入 `REVIEW_REQUIRED`。
- boundary `get_ports` 的 `set_false_path` / `set_case_analysis` 从 cleaned harden SDC 移除。
- 整行注释预处理与超长命令 shallow mapping。
- Stage2 flatten SDC 文件头可正常输入，Stage1 自身输出重复输入仍会被拦截。

## 实现边界

本脚本采用保守策略：没有明确实现语义的命令先进入 `unsupported.sdc`，不进入主 SDC。后续遇到新的真实 SDC 命令类型，应先通过 report 确认语义，再升级为 REMOVE 或 MODIFY 规则。
