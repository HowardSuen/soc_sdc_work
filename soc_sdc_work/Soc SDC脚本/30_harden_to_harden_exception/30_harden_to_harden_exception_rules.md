# 30_harden_to_harden_exception.sdc Rules

本 stage 遵守 [Shared Script Runtime Rules](../docs/shared_script_runtime_rules.md)。30 的 exception/override 主体功能不变；一个 run root 只有一个场景，30 不接收 scenario。30 是最后执行的 stage，并负责最终 port accounting 统计和 Excel 着色。

## 1. 目标

30 只生成有明确架构、协议、CDC/RDC、tool report 或 waiver 依据的 SoC-visible object-level exception/override：

```text
set_false_path
set_multicycle_path
set_max_delay override
set_min_delay override
paired max/min CDC window
```

missing timing、没有 input/output delay、端口剩余未销账，都只能成为 candidate，不能单独证明需要 exception。

## 2. 执行位置

固定顺序：

```text
00 -> 01 -> all 02 -> 03 -> all 04 -> 10 -> all 20 -> all 30 -> final accounting
```

30 必须在 10/20 owner inventory 已稳定后生成正式 exception，并在完成自身销账后扫描全部 port workbook 生成最终 closure。

正式 30 view 必须存在于 `required_views.csv` 且 `require_30=yes`；非 required view 只能 diagnostic。

如果本 run 需要多个 stage/corner view，应先完成所有 required view 的 02/04/20/30 rule review，再执行 final accounting。Used 状态记录 port owner 终态，不替代 per-view coverage。

## 3. 输入

```text
inputs/run_context.csv
inputs/required_views.csv
inputs/info_all.xlsx
inputs/port_*.xlsx
00_middle/harden_sdc_manifest.csv
00_middle/port_accounting_delta.csv/.meta
00_middle/stage_completion.meta
01_middle/clock_inventory.csv
01_middle/port_accounting_delta.csv/.meta
01_middle/stage_completion.meta
02_middle/completion/*.meta
03_middle/relation_map.csv
03_middle/stage_completion.meta
04_middle/pad_inventory.csv/.meta
04_middle/port_accounting_delta.csv/.meta
04_middle/stage_completion.meta
04_middle/completion/*.meta
10_middle/feedthrough_edge_inventory.csv
10_middle/port_accounting_delta.csv/.meta
10_middle/stage_completion.meta
20_middle/channel_inventory.csv
20_middle/port_accounting_delta.csv/.meta
20_middle/stage_completion.meta
20_middle/completion/*.meta
30_middle/completion/*.meta            # prior completed 30 views
inputs/*.sdc
manual protocol/architecture/waiver evidence
```

30 不读取 00 connection inventory。candidate channel 直接从 destination row 的 `From Whom` / `To Top` / `Inout Connectivity` 按 exact bit 解析。

## 4. 核心原则

### 4.1 先分类，再生成

candidate 必须先归类：

```text
normal_timed_channel
clock_relationship
pad_related
feedthrough_normal
static/config
multicycle_protocol
cdc_window
reset/RDC
not_applicable
needs_review
```

只有 exception class 才进入正式 rule。

### 4.2 不替代 10/20 normal timing

- active 10/20 normal max/min 与 30 同 path/check 维度冲突时必须阻断。
- feedthrough-related rule 必须引用 10 exact edge，并且 10 disposition 为 `route_to_30`。
- 普通 non-feedthrough rule 必须引用当前 20 channel state，并确认 20 没有 active conflict budget。
- pad-related async/config rule 必须引用 `related_04_pad_id`；对应 04 pad disposition 必须是 approved `route_to_30`，且 04 没有 active conflicting IO timing。

### 4.3 不替代 03

clock-domain relation 由 03 管理。30 只做 path-level exception/override；不能用大量 false path 代替缺失 clock group。

### 4.4 Object-level

30 endpoint 必须是 SoC-visible exact collection：

```text
[get_pins {u_src/out[0]}]
[get_pins {u_dst/in[0]}]
[get_ports {top_port[0]}]              # 只有明确非 04 ownership 时
```

不允许：

- harden internal pin/net。
- 整 bus/wildcard 未 review collection。
- `get_clocks` 作为 from/to path endpoint。
- 通过 `-through` 拼接 `fti -> fto` 内部 segment。

`get_ports` pad endpoint 只有两种合法来源：完全不属于 04 的 reviewed non-pad object，或 04 inventory 明确 `route_to_30` 且 rule 引用相同 `related_04_pad_id`。

## 5. Harden SDC 渐进交付

- available SDC 正常提取 delay/exception evidence。
- missing SDC 产生 `incomplete_missing_sdc` candidate，不阻断其它完整 channel。
- 依赖 missing SDC 的正式 rule 必须有 `sdc_independent_basis`。
- missing 不能解释为没有 exception 或 normal timing。

## 6. Exception Type

支持：

```text
false_path
multicycle_path
max_delay_override
min_delay_override
max_min_delay_override
```

### 6.1 `false_path`

必须有静态配置、协议/RDC/waiver 等依据。若只是两个 clock async，应由 03 处理；若 reset path，必须有 recovery/removal/RDC basis。

### 6.2 `multicycle_path`

需要：

```text
check_type
setup_cycles
hold_cycles
src_clock
dst_clock
mcp_reference
cross_clock_mcp_review
protocol_ref
```

同 clock 常用 `hold = setup - 1`；偏离时需 basis。跨 clock MCP 必须明确 `-start/-end` reference、周期比和边沿选择。

### 6.3 Max/Min Override

需要 finite value、stage/corner、clock relation、datapath strategy 和 tool effectiveness basis。

CDC 数据稳定窗口推荐成对：

```tcl
set_max_delay <max> -datapath_only -from <src> -to <dst>
set_min_delay <min> -datapath_only -from <src> -to <dst>
```

必须用目标 STA 工具确认 03 asynchronous group 没有按 exception priority 遮蔽 30 max/min；记录 `report_timing` / exception report 或项目等效策略。

## 7. Path Category / Evidence

建议 `path_category`：

```text
static
config
handshake
cdc
reset
test_control
other_reviewed
```

建议 `source_type`：

```text
extracted_harden_exception
manual_entry
protocol_spec
cdc_rdc_report
waiver
missing_timing_candidate
```

`missing_timing_candidate` 不能直接生成。

## 8. Review Workbook

```text
30_middle/30_harden_to_harden_exception.xlsx
```

建议 sheets：

```text
exception_candidate
exception_rule
run_metadata
```

### 8.1 `exception_candidate`

记录 machine candidate：

```text
candidate_id
channel_id
related_04_pad_id
related_20_channel_id
related_10_feedthrough_edge_id
src/dst canonical endpoint fields
source workbook/sheet/row
structure digest
accounting digest before
timing/evidence status
source SDC file/line/command/digest
candidate_status
candidate_reason
recommended_action
note
```

### 8.2 `exception_rule`

关键字段：

```text
exception_id
stage
corner
apply
review_status
owner
exception_type
path_category
channel_id
related_04_pad_id
related_20_channel_id
related_10_feedthrough_edge_id
src_bit_index
src_endpoint
dst_bit_index
dst_endpoint
from_collection
to_collection
through_collection
src_clock
dst_clock
clock_relation
timing_contract_status
harden_clock_context_status
check_type
max_value
min_value
setup_cycles
hold_cycles
mcp_reference
cross_clock_mcp_review
datapath_only
tool_surface
source_type
basis
protocol_ref
cdc_rdc_ref
sta_waiver_ref
sdc_independent_basis
expiry_or_review_date
risk_level
note
```

workbook 同步变化时不生成正式 SDC。

## 9. Machine Outputs

```text
30_middle/exception_candidates.csv
30_middle/port_accounting_delta.csv
30_middle/port_accounting_delta.meta
30_middle/stage_completion.meta
30_middle/completion/<stage>_<corner>.meta
30_result/30_harden_to_harden_exception[_<stage>_<corner>].sdc
30_result/reports/harden_to_harden_exception_check_report_<stage>_<corner>.txt
30_result/reports/port_accounting_final_report.txt
```

每个 required 30 view 独立发布 completion meta。当前 invocation 只有在 `error_count=0`、`sync_changed=no`、SDC/exception candidate/accounting delta digest 均已确定后，才能作为 in-memory complete 参与 final gate；事务提交后再正式发布 meta。deferred finalization 不影响该 view 的 timing completion，但 meta 必须记录 `final_accounting=deferred`。

## 10. 生成门槛

一条 rule 只有同时满足以下条件才能生成：

```text
apply = yes
review_status = approved
stage/corner 与当前 view 匹配
exception_type 支持
exact SoC-visible endpoint
path_category 非 unknown
owner + basis 完整
不是 pad/clock relationship/harden internal path
10/20 owner inventory 存在且无 active conflict
pad path 的 04 inventory 为 approved route_to_30
feedthrough edge 已由 10 route_to_30
MCP cycle/clock/reference 完整
max/min value 与 datapath strategy 完整
missing SDC 有独立 basis
source digest 未 stale
required upstream completion 与 structure/accounting digest 链完整
```

`pending`、`needs_review`、`rejected` 不生成。

## 11. Port Accounting

30 只对 approved exception-only endpoint exact bit 做 union。若 endpoint 已由 01/04/10/20 合法销账，30 只记录 path exception，不重复 claim accounting owner。

写入列：

```text
input  -> Input Used Width
output -> Output Used Width
inout  -> Inout Name
```

candidate、pending、rejected、conflict 或 broad-scope rule 不销账。

30 必须先读取 00/01/04/10/20 的 accounting delta/meta，验证 delta union 能完全解释当前 Used 状态；NC/tie-off/open bit 必须由 00 structural delta 证明。无法解释的预置 bit、owner object 缺失或 digest 断链均阻断正式 30 和 finalization。

30 自身销账通过共享 transaction 提交，并输出 `30_middle/port_accounting_delta.csv/.meta`；delta owner ID 引用 exception ID。final token/着色不改变 logical accounting digest。

## 12. 最终统计和 Excel 状态

完成 30 自身写回后，必须扫描每个 `port_*.xlsx` row：

```text
legal_bits  = 实际 HDL bit 集合
used_bits   = Used 状态集合
unused_bits = legal_bits - used_bits
```

### 12.1 All Used

若 used 覆盖全部合法 bit，例如 6-bit signal 已记录 `0,5,2,1,4,3`，归一化为：

```text
ALL USED
```

状态单元格样式：

```text
fill #C6EFCE
font #006100
```

### 12.2 Incomplete

若存在 unused bit，归一化为：

```text
USED:0,2,3,5; UNUSED:1,4
```

没有任何 used bit：

```text
USED:-; UNUSED:0,1,2,3
```

状态单元格样式：

```text
fill #FFC7CE
font #9C0006
```

只修改 Used 状态单元格，保留 port/name/width/connection 的格式。

30 重跑时必须能解析已有 final token：`ALL USED` 等价于全部 legal bits；`USED/UNUSED` 的两组 bit 必须互斥且完整覆盖 legal bits。校验通过后重写相同值和样式，保证幂等。

### 12.3 Final Report

`port_accounting_final_report.txt` 至少包含：

- workbook/sheet/instance/direction/port/legal-used-unused bits。
- per-instance 和全局 total/used/unused bit 数。
- all-used/incomplete row 数。
- missing SDC 相关 unused bit。
- final workbook digest。
- run_id/mode_label/design_revision、required view completion matrix。
- 每个 Used bit 的 owner stage/object，由各 stage delta 归并得到。
- `Accounting closure: complete|incomplete`。

incomplete 默认不删除已合法生成的 SDC，但必须显著报告；strict closure 选项可将其提升为 error。

## 13. 原子写回

30 必须使用共享 multi-workbook transaction：锁内备份全部 original、生成并验证全部 candidate、写 PREPARED/APPLYING manifest、逐文件替换、发布 delta/completion，最后写 COMMITTED marker。着色失败、任一 workbook 半写、delta/completion 发布失败都必须通过 transaction original 备份恢复全部 workbook，并阻断 final closure。

30 启动时必须先恢复任何未完成事务；恢复状态和 transaction ID 写入 final report。没有 COMMITTED marker 不得发布 final accounting report。

final accounting transaction 和 final report 均成功后，30 才发布 run-wide `30_middle/stage_completion.meta`；incomplete accounting 可以记录 `completion_status=complete, accounting_closure=incomplete`，strict closure 下则不得 complete。

## 14. 检查规则

### Error

- raw channel 无法从 port workbook exact 解析。
- formal 30 缺 10/20 owner inventory。
- pad rule 缺 04 pad inventory/approved route_to_30，或与 active 04 timing 冲突。
- endpoint 与 current raw form/inventory 不一致。
- active 10/20 normal budget overlap。
- feedthrough edge 未 route_to_30。
- false path/MCP/max-min 关键 evidence 不完整。
- internal/broad/clock/pad object 被错误使用。
- Used 状态包含越界 bit。
- workbook 并发修改或 final write/format 失败。
- required view completion 缺失/stale，或 structure/accounting/delta 链不连续。

### Warning

- bit-level exception 只覆盖 bus 一部分。
- missing harden SDC。
- CDC max/min priority 需要工具复核。
- reset exception 需要 recovery/removal/RDC 复核。
- final accounting 有 unused bit。

## 15. 命令行

```bash
python3 30_extract_harden_to_harden_exception.py \
  --run-root <run_root> \
  --stage <stage> \
  --corner <corner>
```

可支持：

```text
--strict-port-closure
--defer-final-accounting
--diagnose-only
```

默认在当前调用结束时尝试 final accounting：required view 尚未全部 complete 时自动 deferred，不写 final token/颜色；全部 complete 时才执行。多 view flow 也可在前序调用显式使用 `--defer-final-accounting`。30 不接受 scenario 选择；诊断模式不修改 workbook，也不能宣称 final accounting closure。
