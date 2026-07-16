# 02 Clock Timing SDC Form Specification

本 stage 遵守 [Shared Script Runtime Rules](../docs/shared_script_runtime_rules.md)。02 的 clock timing 主体功能不变；一个 run root 只有一个场景，02 不接收 scenario，也不做 port accounting。

## 1. 目标

02 管理已经由 01 创建的 clock object 的 timing 属性，例如：

```text
set_clock_uncertainty
set_clock_latency
set_clock_transition
set_propagated_clock
set_timing_derate / OCV placeholder
```

02 不创建 clock，不定义 clock relationship，不生成 IO delay，不处理 harden interface budget 或 exception。

输出按 `stage + corner` 拆分：

```text
02_result/02_soc_clock_timing_<stage>_<corner>.sdc
```

## 2. 输入

必需：

```text
inputs/run_context.csv
inputs/required_views.csv
01_middle/clock_inventory.csv
01_middle/clock_inventory.meta
01_middle/stage_completion.meta
```

inventory 必须对应最终 `01_result/01_soc_clocks.sdc` digest。02 不读取 00 connection artifact，不读取或修改 port workbook Used 状态。

## 3. 表单文件

建议按 timing stage 独立维护：

```text
02_middle/02_soc_clock_timing_budget_prects.xlsx
02_middle/02_soc_clock_timing_budget_postcts.xlsx
```

workbook 建议包含：

```text
runtime_metadata
clock_budget
clock_pair_uncertainty
derate_ocv
```

`runtime_metadata` 记录最近同步的 Author、stage、corner、run completeness、01 inventory path/digest 和 port-accounting 状态。02 的 port-accounting 固定为 `not_applicable`。

02 只允许正式生成 `required_views.csv` 中 `require_02=yes` 的 stage/corner；非 required view 只能显式 diagnostic 运行。

## 4. 通用约定

- `stage` 常用 `prects`、`postcts`，项目可扩展稳定枚举。
- `corner` 使用项目 analysis view/corner 名，大小写敏感。
- 数值使用 ns。
- 空白表示未填写，不等价于 0。
- `apply` 统一使用 `yes` / `no`。
- 同一 `stage/corner/clock_name` 最终最多一条有效记录。
- 02 只装配当前命令行 `stage + corner` 的行；其它 view 行不参与本次生成或 stale 判断。

## 5. Sheet: `clock_budget`

一行描述一个 clock 在某个 `stage/corner` 下的基础 timing budget。

建议字段：

```text
stage
corner
clock_name
clock_kind
period
source_latency_early
source_latency_late
network_latency_early
network_latency_late
setup_uncertainty
hold_uncertainty
transition_min
transition_max
propagated
apply
sync_status
source_inventory_digest
note
```

字段规则：

- `clock_name` 必须存在于 01 inventory。
- `clock_kind`、`period` 可由 01 同步，属于 machine context。
- `propagated` 使用 `yes` / `no` / blank。
- `sync_status` 使用 `OK`、`NEW_FROM_01`、`STALE_NOT_IN_01`、`BLOCKED_BY_MISSING_SDC`。
- `apply=yes` 时必须有足够字段生成至少一条受支持命令。
- `apply=no` 时 `note` 应说明该 view 不生成的原因。

示例：

```text
stage,corner,clock_name,setup_uncertainty,hold_uncertainty,transition_max,propagated,apply,sync_status,note
prects,ss_125,u_pll_core_clk_o,0.05,0.02,0.20,no,yes,OK,pre-CTS budget
postcts,ff_m40,u_pll_core_clk_o,0.03,0.01,,yes,yes,OK,post-CTS propagated
```

## 6. Sheet: `clock_pair_uncertainty`

预留用于 clock pair uncertainty：

```text
stage
corner
from_clock
to_clock
setup_uncertainty
hold_uncertainty
apply
note
```

`from_clock` / `to_clock` 必须存在于 01 inventory。第一版可以只校验和保留表单，不生成命令；一旦实现，仍按当前 `stage + corner` 选择。

## 7. Sheet: `derate_ocv`

预留字段：

```text
stage
corner
derate_scope
object_type
early
late
apply
managed_by_flow
note
```

若项目 OCV/derate 已由 MMMC flow 管理，`managed_by_flow=yes`，02 不重复生成。

## 8. 脚本机制

### 8.1 命令行

```bash
python3 02_extract_soc_clock_timing.py \
  --run-root <run_root> \
  --stage prects \
  --corner ss_125
```

不接受 scenario 选择。

### 8.2 第一次运行 / 同步

1. 读取 01 clock inventory/meta。
2. 创建或加载当前 stage workbook。
3. 为当前 `stage/corner` 缺失的 clock 添加 `NEW_FROM_01` 行。
4. 对当前 view 中已不存在于 01 的 clock 标记 `STALE_NOT_IN_01`。
5. 保留其它 corner 的 review 行，不与本次 view 交叉比较。
6. workbook 发生同步变化时中断生成，等待 review。

### 8.3 生成门槛

只有满足以下条件才生成：

- 01 inventory/meta 存在且 digest 一致。
- 当前 `stage/corner` 有效 clock 集合与 01 active clock 一致。
- 无真实 stale row。
- 当前 view 所有 `apply=yes` 行字段合法。
- duplicate key 为 0。
- workbook 本次没有同步变化。

## 9. SDC 生成

根据非空字段生成：

```tcl
set_clock_uncertainty -setup <value> [get_clocks <clock_name>]
set_clock_uncertainty -hold  <value> [get_clocks <clock_name>]
set_clock_latency -source -early <value> [get_clocks <clock_name>]
set_clock_latency -source -late  <value> [get_clocks <clock_name>]
set_clock_latency -early <value> [get_clocks <clock_name>]
set_clock_latency -late  <value> [get_clocks <clock_name>]
set_clock_transition -min <value> [get_clocks <clock_name>]
set_clock_transition -max <value> [get_clocks <clock_name>]
set_propagated_clock [get_clocks <clock_name>]
```

输出：

```text
02_result/02_soc_clock_timing_<stage>_<corner>.sdc
02_middle/resolved/<stage>_<corner>.manifest
02_middle/completion/<stage>_<corner>.meta
02_result/reports/clock_timing_check_report_<stage>_<corner>.txt
```

completion meta 必须记录 run provenance、required-view ID、structure digest、01 completion/inventory digest、workbook semantic digest、output SDC digest、`error_count=0`、`sync_changed=no` 和 `Port accounting: not_applicable; added_bits=0`。review-required、stale 或 diagnose-only 不得标 complete。

## 10. 检查项

### Error

- 01 inventory/meta 缺失或 stale。
- current view clock 集合不一致。
- duplicate `stage/corner/clock_name`。
- `apply`、`propagated` 或数值字段非法。
- `apply=yes` 但不能生成任何支持的命令。
- current view 存在未处理的 stale row。

### Warning

- missing harden SDC 导致 01 completeness 为 partial。
- latency/uncertainty 值超出项目建议范围。
- propagated strategy 与 stage 常规做法不一致。
- derate 已由外部 flow 管理。

## 11. Port Accounting

02 永远不修改：

```text
Input Used Width
Output Used Width
Inout Name
```

clock timing property 不能单独成为 harden port 销账依据。
