# 10_feedthrough.sdc Rules

本 stage 遵守 [Shared Script Runtime Rules](../docs/shared_script_runtime_rules.md)。10 的 feedthrough boundary 主体功能不变；一个 run root 只有一个场景，10 不接收 scenario，并直接从 port workbook 建 edge 和写销账状态。

## 1. 目标和层级边界

10 只处理 SoC top 可见、与 feedthrough harden boundary 相邻的 direct edge：

```text
ingress: u_src/out -> u_ft/fti
egress : u_ft/fto -> u_dst/in
```

10 不处理：

```text
u_ft/fti -> u_ft/fto             # harden internal
u_src/out -> u_dst/in stitched   # synthetic end-to-end across harden
```

feedthrough harden 内部 timing 由 harden 自己完成；SoC 既看不到，也不需要重复约束。

## 2. 输入和互联识别

10 直接读取：

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
03_middle/relation_map.csv         # 只用于 timing 语义诊断
03_middle/stage_completion.meta
04_middle/pad_inventory.csv
04_middle/pad_inventory.meta
04_middle/port_accounting_delta.meta
04_middle/stage_completion.meta
04_middle/completion/*.meta
inputs/*.sdc                       # available harden evidence
```

direct edge 来自 destination row 的 `From Whom`，并按 source/sink actual HDL range 展开。10 不读取 00 connection inventory。

feedthrough boundary 识别至少使用：

- destination port 是明确的 `fti_*`，或 source port 是明确的 `fto_*`。
- instance/module 有项目确认的 feedthrough classification。
- port workbook 中有结构/owner 字段或 review workbook 明确确认。

名称 token 只能生成 candidate，不能单独成为 timing/销账终态。

## 3. Direct Edge Ownership

最小 ownership 对象是一条 exact direct bit edge。每条 edge 只能属于一个 owner stage。

10 排除：

- clock-related edge，归 01/03。
- pad-related edge，归 04。
- 普通非 feedthrough functional edge，归 20。
- harden internal `fti -> fto`，不属于任何 SoC timing stage。
- NC/tie-off/unresolved edge。

## 4. Feedthrough Edge Inventory

输出：

```text
10_middle/feedthrough_edge_inventory.csv
10_middle/feedthrough_edge_inventory.meta
```

建议字段：

```text
schema_version
feedthrough_edge_id
connection_id
edge_role
src_instance
src_direction
src_port
src_bit_index
src_endpoint
dst_instance
dst_direction
dst_port
dst_bit_index
dst_endpoint
source_workbook
source_sheet
source_row
structure_digest
accounting_digest_before
accounting_digest_after
src_sdc_status
dst_sdc_status
evidence_status
channel_disposition
budget_model
apply
review_status
emit_max
emit_min
converted_max
converted_min
owner
basis
note
```

ID 使用共享 canonical tuple 的完整 SHA-256；不依赖 00 预生成 ID。inventory 必须能回到原 workbook/sheet/row/bit，且 structure digest 必须与 00/01/04 一致。

## 5. Channel Disposition

统一使用：

```text
emit_budget
no_soc_budget_required
route_to_30
not_applicable
pending
```

- `emit_budget`：10 生成当前 direct edge 的 max/min budget。
- `no_soc_budget_required`：项目确认该 direct edge 不需额外 SoC budget。
- `route_to_30`：exception-only，由 30 完成；10 不生成、不销账。
- `not_applicable`：结构上不适用 timing，需完整 review basis。
- `pending`：证据或 review 未完成。

## 6. Timing Policy

10 可以从两侧 harden boundary input/output delay 提取 evidence，但不能默认把 delay 原值等价为 SoC interconnect budget。

`emit_budget` 必须有明确 budget model，例如：

```text
manual_budget
interconnect_budget
reviewed_two_side_budget
```

命令只作用于 direct edge：

```tcl
set_max_delay <value> -datapath_only \
  -from [get_pins {u_src/out[0]}] \
  -to   [get_pins {u_ft/fti_path[3]}]
```

或：

```tcl
set_max_delay <value> -datapath_only \
  -from [get_pins {u_ft/fto_path[3]}] \
  -to   [get_pins {u_dst/in[0]}]
```

禁止通过 `-through` 或端点拼接跨越 harden 内部。

min budget 必须有 sign/datapath review；复杂 delay option 不能静默丢弃。

## 7. Clock Relation

03 relation map 只用于检查 budget 语义：

- synchronous relation 可以继续 normal budget review。
- async/exclusive 不自动变成 `route_to_30`，但 normal synchronous budget 必须有 override basis。
- unknown relation 不能自动当 synchronous。

03 不决定 port owner。

## 8. Harden SDC 渐进交付

- available side 正常解析 evidence。
- missing side 标记 `incomplete_missing_sdc`，不阻断其它完整 edge。
- 依赖 missing SDC 的 `emit_budget` 必须有 `sdc_independent_basis`。
- 不完整 evidence 不能自动 `no_soc_budget_required` 或销账。

## 9. Review Workbook

```text
10_middle/10_feedthrough.xlsx
```

建议 sheets：

```text
feedthrough_edges
extraction_log
run_metadata
```

workbook 同步变化时不生成正式 SDC。只对 `apply=yes + review_status=approved` 的 terminal row 生成/销账。

## 10. Port Accounting

10 对以下 terminal edge 的两个 harden endpoint exact bit 做 union：

```text
emit_budget
no_soc_budget_required
not_applicable
```

写入列按 endpoint direction 选择：

```text
input  -> Input Used Width
output -> Output Used Width
inout  -> Inout Name
```

`route_to_30`、`pending`、unresolved、conflict edge 不销账。

一个 endpoint 已由 01/04 合法销账时，10 不抢 owner；若 edge 仍需 timing command，可生成 path-level rule，但 report 必须说明 accounting 已由早期 stage 覆盖。

不再生成 pending/removed log。每次写回 report 记录 added/final used bits。

10 必须通过共享 multi-workbook transaction 提交，并输出：

```text
10_middle/port_accounting_delta.csv
10_middle/port_accounting_delta.meta
10_middle/stage_completion.meta
```

delta owner ID 引用 `feedthrough_edge_id`。10 completion 只允许在所有 required 04 view complete、无 error/sync change、SDC/inventory/delta 均发布且 accounting digest 链连续后标 complete。

## 11. 输出

```text
10_result/10_feedthrough.sdc
10_result/reports/feedthrough_check_report.txt
10_middle/feedthrough_edge_inventory.csv
10_middle/feedthrough_edge_inventory.meta
10_middle/port_accounting_delta.csv
10_middle/port_accounting_delta.meta
10_middle/stage_completion.meta
```

SDC 可以为空，但 inventory、coverage 和 report 必须完整。

## 12. 命令级合并

多个 bit 只有在以下全部一致时才可 compact：

- source/destination bus pairing 连续且方向一致。
- disposition、budget value、datapath strategy、tool surface、review/basis 一致。
- compact collection 在目标工具中仍精确匹配 intended bits。

否则逐 bit 生成。accounting 始终逐 bit union，不因 SDC compact 而写 range token。

## 13. 检查规则

### Error

- port workbook/direct edge 无法解析。
- width/range mismatch 或 destination bit 多 driver。
- 把内部 `fti -> fto` 当 SoC edge。
- 拼接 synthetic end-to-end path。
- 10 inventory 出现 clock/pad/普通 20 edge。
- terminal row 缺 owner/basis/review。
- emit row value/datapath/min-sign 不完整。
- Used 状态包含越界 bit或 workbook 并发修改。
- 04 pad inventory/completion 缺失或 pad edge 未排除。
- structure/accounting digest、transaction/delta/completion 校验失败。

### Warning

- feedthrough classification 只来自名字。
- harden SDC partial。
- clock relation unknown/async 与 normal budget intent 不一致。
- bus 只有部分 bit terminal。
- edge route_to_30 但缺 exception follow-up basis。

## 14. 与其它 Stage 的边界

- 01/03：clock owner/relation。
- 04：pad-related edge。
- 20：读取 10 inventory，排除所有 10-owned edge。
- 30：只接收 10 明确 `route_to_30` 的 exact bit edge，并检查 10 没有 active normal budget。

## 15. 命令行

```bash
python3 10_extract_feedthrough.py \
  --run-root <run_root>
```

不接受 scenario 选择。
