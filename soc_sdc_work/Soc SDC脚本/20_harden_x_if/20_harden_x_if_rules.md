# 20_harden_x_if.sdc Rules

本 stage 遵守 [Shared Script Runtime Rules](../docs/shared_script_runtime_rules.md)。20 的 normal functional harden interface 主体功能不变；一个 run root 只有一个场景，20 不接收 scenario，并直接从 port workbook 建 channel 和写销账状态。

## 1. 目标

20 处理排除以下对象后的普通 SoC-visible functional direct channel：

```text
clock
pad/IO
feedthrough-adjacent edge
NC/tie-off/unresolved
exception-only path
```

20 支持两种模式：

```text
audit_only
budget_output
```

- `audit_only`：按项目默认 policy 对普通 direct channel 做 owner/disposition/coverage，不消费 harden input/output delay，也不生成 timing command。
- `budget_output`：解析 harden SDC evidence，经人工 review 后可生成明确的 SoC interconnect max/min budget。

正式 20 view 必须存在于 `required_views.csv` 且 `require_20=yes`；非 required view 只能 diagnostic。

## 2. 输入

```text
inputs/run_context.csv
inputs/required_views.csv
inputs/info_all.xlsx
inputs/port_*.xlsx
00_middle/harden_sdc_manifest.csv
00_middle/port_accounting_delta.meta
00_middle/stage_completion.meta
01_middle/clock_inventory.csv
01_middle/port_accounting_delta.meta
01_middle/stage_completion.meta
03_middle/relation_map.csv
03_middle/stage_completion.meta
04_middle/pad_inventory.csv
04_middle/pad_inventory.meta
04_middle/port_accounting_delta.meta
04_middle/stage_completion.meta
04_middle/completion/*.meta
10_middle/feedthrough_edge_inventory.csv
10_middle/feedthrough_edge_inventory.meta
10_middle/port_accounting_delta.meta
10_middle/stage_completion.meta
inputs/*.sdc                         # budget_output evidence
```

20 不读取 00 connection inventory。direct channel 来自 destination row 的 `From Whom`，按 actual HDL range exact bit 配对；fanout 通过扫描全部 destination row 得到。

## 3. Channel Endpoint 和 ID

一条 20 channel 对应一条 exact direct bit edge：

```text
u_src/output_bit -> u_dst/input_bit
```

canonical endpoint：

```text
[get_pins {u_src/out[7]}]
[get_pins {u_dst/in[3]}]
```

稳定 ID 根据共享 canonical tuple 的完整 SHA-256 生成：

```text
CONN_<64-lowercase-hex>
CH_<same-connection-hash>
```

每条记录必须能回到 source workbook/sheet/row/bit；ID 不受 row reorder 或 Used 值影响。

## 4. Ownership 排除

20 在构建 channel 前必须排除：

- 01 clock inventory 对应的 clock edge。
- 04 pad/top-related edge。
- 10 feedthrough edge inventory 中的所有 exact edge。
- harden internal `fti -> fto` 或任何 synthetic stitched path。
- constant、NC、unresolved、非法 direction edge。

10 inventory 缺失时，20 不能正式发布可能与 feedthrough 重叠的 channel；可以生成 candidate/report 等待 10。

## 5. Channel Disposition

```text
emit_budget
no_soc_budget_required
route_to_30
not_applicable
pending
```

### 5.1 `emit_budget`

仅 `budget_output` 使用。要求明确 budget model、数值、tool/datapath strategy、owner 和 review。

### 5.2 `no_soc_budget_required`

表示项目确认普通 functional direct channel 不需要额外 SoC channel-specific delay。它是 SoC SDC ownership 决策，不代表 STA 自动通过。

### 5.3 `route_to_30`

表示 harden SDC evidence 或协议/架构 review 确认该 path 属于 exception/override。20 不生成 normal budget，也不销账，由 30 完成。

20 不需要预先读取 30 workbook。若从当前 harden SDC 识别到明确 exception evidence，自动 route 应记录 reviewed evidence；30 最终 rule 仍需自己的生成门槛。

### 5.4 `not_applicable`

只用于确实不属于 20/30 timing owner 的特殊 edge，必须有 owner/basis/reviewer/date；不能作为跳过分析的快捷方式。

### 5.5 `pending`

证据、owner 或 review 未完成，不生成、不销账。

## 6. Budget Model

支持：

```text
manual_budget
interconnect_budget
reviewed_two_side_budget
clock_relative_io_delay            # evidence only unless project approves conversion
unknown
```

harden boundary `set_input_delay` / `set_output_delay` 原值通常包含 block internal/external timing contract，不能默认等于 SoC interconnect max/min。

### 6.1 两端归并

src output delay 与 dst input delay 可以作为 evidence 放在同一 channel row，但自动转换只有在项目公式明确、单位/view/clock context 一致且 review 完整时允许。

不能默认使用：

```text
min(src_output_delay, dst_input_delay)
max(src_output_delay, dst_input_delay)
src + dst
```

作为 interconnect budget。

### 6.2 Min Budget

`emit_min=yes` 必须：

- `converted_min` finite。
- `min_sign_review` approved/waived。
- 明确是否 `-datapath_only`。
- 解释负 min、hold strategy 和 source。

复杂 SDC option 不得静默丢弃。

## 7. Clock Relation

03 relation map 只用于 budget 语义检查，不决定 port owner：

- synchronous：可继续 normal budget review。
- asynchronous/exclusive：normal 20 budget 默认阻断，除非有明确等效/override basis。
- unknown：不能当 synchronous。

## 8. Harden SDC 渐进交付

- `audit_only` 可以在不消费 SDC 的项目 policy 下继续分类完整的表单 edge。
- `budget_output` 对 missing side 标记 `incomplete_missing_sdc`。
- 依赖 missing SDC 的 emit/no-budget terminal 需要独立 architecture basis。
- missing 不能解释为没有 timing/exception。

## 9. Channel Inventory

输出：

```text
20_middle/channel_inventory.csv
20_middle/channel_inventory.meta
```

建议字段：

```text
schema_version
mode
run_completeness
channel_id
connection_id
channel_type
owner_stage
src_instance
src_direction
src_port
src_bit_index
src_endpoint
src_sdc_status
dst_instance
dst_direction
dst_port
dst_bit_index
dst_endpoint
dst_sdc_status
source_workbook
source_sheet
source_row
structure_digest
accounting_digest_before
accounting_digest_after
is_pad_related
is_clock_related
is_feedthrough
evidence_status
channel_disposition
budget_model
apply
review_status
emit_max
emit_min
converted_max
converted_min
disposition_basis
sdc_independent_basis
note
```

## 10. Review Workbook

```text
20_middle/20_harden_x_if.xlsx
```

建议 sheets：

```text
interface_budget
channel_inventory
extraction_log
run_metadata
```

`interface_budget` 关键字段：

```text
channel_id
stage
corner
timing_model
channel_disposition
budget_required
clock_relation
budget_model
original_src_clock
original_dst_clock
original_src_max/min
original_dst_max/min
converted_max/min
max_source/min_source
derivation_basis
tool_surface
datapath_only
min_sign_review
budget_basis
source_type
apply
emit_max
emit_min
review_status
owner
reviewer
review_date
disposition_basis
sdc_independent_basis
note
```

workbook sync 发生变化时不生成正式 SDC。

## 11. 输出门槛

### `emit_budget`

必须同时满足：

```text
mode = budget_output
apply = yes
review_status = approved
budget_required = yes
emit_max or emit_min = yes
exact canonical endpoints
reviewed budget_model
finite values
tool_surface/datapath_only complete
owner + basis complete
no 10/04/01 ownership overlap
```

命令示例：

```tcl
set_max_delay 1.4 -datapath_only \
  -from [get_pins {u_src/data_o[0]}] \
  -to   [get_pins {u_dst/data_i[0]}]
```

`no_soc_budget_required` / `not_applicable` approved row 不生成 timing command。`route_to_30` / `pending` 也不生成。

## 12. Port Accounting

20 对以下 approved terminal channel 的 source/destination exact bit 做 union：

```text
emit_budget
no_soc_budget_required
not_applicable
```

写入：

```text
input  -> Input Used Width
output -> Output Used Width
inout  -> Inout Name
```

`route_to_30`、`pending`、active conflict、unresolved channel 不销账。

已由 01/04/10 合法销账的 endpoint 不由 20 重复 claim；若 20 path timing 仍需生成，report 记录 accounting owner 已存在。写回采用 exact bit union，不生成 pending/removed log。

20 必须通过共享 multi-workbook transaction 提交，并输出 `20_middle/port_accounting_delta.csv/.meta`。delta owner ID 引用 `channel_id`。

## 13. 输出

```text
20_result/20_harden_x_if[_<stage>_<corner>].sdc
20_result/reports/harden_x_if_check_report_<stage>_<corner>.txt
20_middle/channel_inventory.csv
20_middle/channel_inventory.meta
20_middle/port_accounting_delta.csv
20_middle/port_accounting_delta.meta
20_middle/stage_completion.meta
20_middle/completion/<stage>_<corner>.meta
```

SDC 可以为空，但 inventory/report/coverage 必须完整。

20 只允许正式生成 `required_views.csv` 中 `require_20=yes` 的 view。completion 只允许在 00/01/03/04/10 required upstream complete、无 error/sync change、SDC/inventory/delta 均发布且 accounting digest 链连续后标 complete。

所有 required 20 view complete 后，20 发布 run-wide `20_middle/stage_completion.meta`，证明 channel inventory resolved view 已稳定。即使没有 active budget view，也必须执行 audit classification 并发布 channel inventory，供 30 检查 normal owner/overlap。

## 14. 检查规则

### Error

- direct channel 无法从 port workbook 精确解析。
- width/range mismatch 或 destination 多 driver。
- 20 包含 clock/pad/feedthrough edge。
- 与 10 inventory 的 connection ID/endpoints 重叠。
- known exception evidence 没有 route_to_30。
- terminal row 缺 owner/basis/review。
- emit row 缺 value/model/tool/datapath/min review。
- active channel 重复/冲突。
- Used 状态越界或 workbook 并发修改。
- 04/10 owner inventory 或 required completion 缺失/stale。
- structure/accounting digest、transaction/delta/completion 校验失败。

### Warning

- harden SDC partial。
- delay evidence 只有一侧。
- clock relation unknown/async。
- complex SDC option 需要 manual review。
- bus 只有部分 bit terminal。

## 15. 与其它 Stage 的边界

- 01/03：clock owner/relation。
- 04：pad owner。
- 10：feedthrough-adjacent edge owner；20 必须按 10 inventory 排除。
- 30：读取 20 inventory 检查 active normal budget 和 route_to_30；30 不改写 20 owner decision。

## 16. 命令行

```bash
python3 20_extract_harden_x_if.py \
  --run-root <run_root> \
  --mode audit_only
```

或：

```bash
python3 20_extract_harden_x_if.py \
  --run-root <run_root> \
  --mode budget_output \
  --stage <stage> \
  --corner <corner>
```

不接受 scenario 选择。
