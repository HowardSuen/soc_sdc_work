# 04_soc_io_pads.sdc Rules

本 stage 遵守 [Shared Script Runtime Rules](../docs/shared_script_runtime_rules.md)。04 的 SoC IO/pad 主体功能不变；一个 run root 只有一个场景，04 不接收 scenario，并直接从 port workbook 解析 pad 连接和写销账状态。

## 1. 目标

04 只管理 SoC top IO/pad environment：

```text
set_input_delay
set_output_delay
set_input_transition / set_driving_cell / set_drive
set_load
set_max_transition 等明确 IO electrical rule
```

04 不创建 clock、不定义 clock group、不处理 harden-to-harden normal channel、feedthrough edge 或 exception。

输出：

```text
04_result/04_soc_io_pads[_<stage>_<corner>].sdc
04_result/reports/io_pad_check_report_<stage>_<corner>.txt
04_middle/pad_inventory.csv
04_middle/pad_inventory.meta
04_middle/port_accounting_delta.csv
04_middle/port_accounting_delta.meta
04_middle/stage_completion.meta
04_middle/completion/<stage>_<corner>.meta
```

## 2. 输入来源

### 2.1 Integration forms

04 直接读取：

```text
inputs/run_context.csv
inputs/required_views.csv
inputs/info_all.xlsx
inputs/port_*.xlsx
00_middle/harden_sdc_manifest.csv
00_middle/stage_completion.meta
01_middle/clock_inventory.csv
01_middle/stage_completion.meta
```

00/01 completion 必须存在、为 `complete`、provenance/structure 一致且无 error/sync change；01 completion 声明的 `clock_inventory_digest` 必须匹配实际 `01_middle/clock_inventory.csv`。04 不依赖 03 relation completion。

pad connection 由以下字段建立：

- `From Whom = top.<pad>`：top input/inout pad 驱动 harden input。
- `To Top = top.<pad>` 或 `<pad>`：harden output 驱动 top output pad。
- `Inout Connectivity = top.<pad>`：harden inout 与 top inout pad 相连。

04 必须按 actual HDL bit 展开 range。完整 range、subrange 和 exact-bit harden SDC evidence 均须替换为 exact top/harden bit review row；任一 selected bit 不能唯一映射时整条 evidence fail closed，不得只发布已匹配子集。一个 top pad bit 对应多 destination harden input 时可以 fanout：IO command 每个 exact top bit 只发一次，但每条 direct mapping 在 `pad_inventory` 中单独记录。

04 不读取 00 connection inventory。

### 2.2 Harden SDC

对 manifest 中 `available` 的 harden SDC，04 可提取 boundary IO evidence：

```text
set_input_delay
set_output_delay
set_input_transition
set_driving_cell
set_drive
set_load
```

harden internal pin/net 约束不提升。

### 2.3 Missing SDC

- missing harden 只跳过其 SDC evidence，继续处理其它对象。
- missing 不能解释为 pad 无需约束。
- 可由人工 IO 表单和明确 board/pad basis 独立批准的 rule 可以生成并销账。
- 没有足够 evidence 的 pad bit 保持 Used 状态不变。

### 2.4 Manual IO workbook

```text
04_middle/04_soc_io_pads.xlsx
```

人工值、board/library reference 和 NA basis 均在该 workbook review。

## 3. SoC 层级对象

### 3.1 Top pad port

SDC target 应是 SoC top port：

```tcl
[get_ports {pad_name}]
[get_ports {pad_name[3]}]
```

### 3.2 Harden instance pin

harden boundary pin 只用于 traceability 和 mapping，不应把 IO environment 约束留在 `[get_pins u_harden/...]`，除非项目明确要求 block-boundary exception 且不属于 04。

### 3.3 Net

第一版不以 `get_nets` 作为常规 IO target；无法映射到 top port 时进入 review，不自动扩大 collection。

## 4. 方向和约束类型

### 4.1 Input pad

可能需要：

```text
input_delay max/min
input_transition 或 driving_cell/drive
```

approved row 的 effective direction 必须仍为 `input`，不得通过同时修改 constraint type 和 direction 绕过 integration direction。

### 4.2 Output pad

可能需要：

```text
output_delay max/min
load
max_transition
```

approved row 的 effective direction 必须仍为 `output`。

### 4.3 Inout / GPIO

inout 必须明确当前 run 的方向和 case 条件。实际连接只来自 `Inout Connectivity`；`Inout Name` 是销账状态列，后续重跑不得把其中的 Used bit 当成 top pad 名。

- 当前 run 作为 input：按 input rule 生成。
- 当前 run 作为 output：按 output rule 生成。
- approved row 必须把 effective direction 显式改为 `input` 或 `output`；保留 `inout`、blank 或 `bidirectional` 时保持 review，不生成 broad 双向约束。
- `bidirectional` 不属于单场景 runtime 的合法 effective direction；若硬件需要同一分析中双向计时，必须拆成独立 run。本规则只要求当前 run 的 input 或 output 一类覆盖。
- inout `route_to_30` 还必须在 pad review row 填写 `effective_direction`。当前 30 oriented edge contract 只支持 `input`（top→harden）handoff；`output`（harden→top）必须 fail closed，待 30 发布反向 edge contract 后再开放，不能输出方向错误的 canonical endpoint。

## 5. Timing 分类

建议 `io_class`：

```text
timed
async
untimed
config
```

- `timed`：有 clock/reference 和 input/output delay。
- `async`：不走普通 synchronous IO delay；若需要 false path/CDC rule，交 30。
- `untimed`：必须有 approved NA basis。
- `config`：根据协议决定 timing 或 exception owner。

分类不能只靠名字。

## 6. Stage / Corner

一个 run 可有多个 timing stage/corner row。生成时按 `--stage` / `--corner` 选择当前 view；不再按 scenario 分层。若 required views 中存在真实 `all/all` view，显式 `--stage all --corner all` 必须选择该 view；仅当不存在真实 `all/all` required view 时，默认 `all/all` 才可回落到首个 required 04 view。

04 只允许正式生成 `required_views.csv` 中 `require_04=yes` 的 view；非 required view 只能显式 diagnostic 运行。

view-independent electrical rule（如 load、input_transition）如果重复出现在多个 view，assembled 结果必须唯一且数值一致。

## 7. Review Workbook

建议 sheets：

```text
io_constraints
pad_inventory
extraction_log
run_metadata
```

### 7.1 `io_constraints`

建议字段：

```text
constraint_id
stage
corner
pad_name
direction
io_class
constraint_type
clock_name
min_value
max_value
value
from_collection
to_collection
apply
review_status
owner
basis
source_type
source_file
source_line
source_digest
note
```

### 7.2 `pad_inventory`

每个 exact pad bit 一行，记录：

```text
pad_id
view_id
stage
corner
top_port
direction
source_workbook
source_sheet
source_row
harden_instance
harden_port
harden_bit_index
connection_status
sdc_status
coverage_status
note
```

该 sheet 是 04 owner inventory，不替代原始 port workbook。多 view row 按 `pad_id/view_id` 共存，resolved CSV 不得在后续 view 运行时删除其它已 committed view。当前 view 已不存在的 machine row 必须在同步阶段移除并要求重新 review，不能继续作为 stale owner 发布。

即使 inventory 只有 header、没有 pad row，`pad_inventory.meta.view_ids` 也必须累计所有已认证 required view，不能因空 inventory 丢失 prior view completion。

04 必须把该 sheet 的 resolved machine view 发布为：

```text
04_middle/pad_inventory.csv
04_middle/pad_inventory.meta
```

除上述字段外，machine view 还必须记录 `pad_disposition`、`effective_direction`、`apply/review_status`、`related_exception_intent`、structure digest、source digest 和当前 exact endpoint。04/30 跨阶段 owner identity 与 exact direct edge 使用同一 canonical tuple：

```text
[schema_version,
 src_instance,src_direction,src_port_base,src_bit_index,
 dst_instance,dst_direction,dst_port_base,dst_bit_index]
```

对该 UTF-8 canonical JSON array 计算完整 lowercase SHA-256：

```text
pad_id        = <64-lowercase-hex>
connection_id = CONN_<same-64-lowercase-hex>
```

`pad_id` 不带 `PAD_` 前缀；view、stage/corner、review 状态、workbook 行号和 digest 均不进入 identity。这样 30 的 `related_04_pad_id` 可直接引用同一 exact edge owner，且不得使用易碰撞的可读字符串替换。

`pad_disposition` 使用：

```text
constrained
not_applicable
route_to_30
pending
```

- async/config pad path 需要 exception 时必须是 `route_to_30`；flat 04 不生成 `set_false_path`，也不为该 exception path 销账。
- `route_to_30` 必须 `apply=yes + review_status=approved`，并保留 pad electrical owner 状态供 30 引用。它可以与 04 的 `load/drive/input_transition/max_transition/max_capacitance` electrical command 共存，但不得与 active input/output delay 或 04 exception 共存。
- inout route 还必须与 active electrical row 使用相同 effective direction；当前 output-oriented inout route 不得发布给 30。

### 7.3 `extraction_log`

记录每条 harden SDC evidence 的原命令、解析状态、映射 pad 和忽略原因。

## 8. 生成规则

- 只生成 `apply=yes + review_status=approved` 的 row。
- target runtime 支持 `--tool sta|synth|both`，默认为 `sta`。`sta` 不生成 synthesis-only `set_dont_touch_network`；`synth` 和 `both` 必须生成该命令。
- 选定的 tool surface 必须一致用于 row validation、SDC generation、resolved pad inventory、port accounting、report 和 completion provenance，不得在 flat 路径内回落为固定 STA。
- `clock_name` 必须存在于 `01_middle/clock_inventory.csv`，virtual clock 也必须由 01 创建。
- max/min 配对按 constraint_type 明确，不能把 blank 当 0。
- numeric value 必须 finite。
- `set_driving_cell` 必须有 library cell/pin 信息。
- 每条命令 target 必须是 exact top port/bit。自动提取的 range/subrange evidence 必须先拆成 `object_granularity=single_pad` exact-bit row；flat formal generation 不接受 `port_list/pattern` approval，也不允许 wildcard/range 扩大。
- 同一 top bit 的 reviewed IO command 覆盖该 bit 的全部 fanout direct edge；normal input/output delay 与任一 fanout edge 的 `route_to_30` 冲突，electrical-only command 可与逐 edge `route_to_30` 共存。
- 同一 assembled view 的重复 rule 必须数值一致，否则 error。

## 9. Port Accounting

04 对 approved terminal pad bit 更新对应 harden row：

```text
input  -> Input Used Width
output -> Output Used Width
inout  -> Inout Name
```

允许 terminal：

- 已生成所需 IO timing/electrical constraint。
- 对 `synth/both` surface，已批准且已生成的 `set_dont_touch_network` 是 active 04 owner，可以将该 exact pad bit 解析为 `constrained`；同一 row 在 `sta` surface 不 active，不得因此销账。
- 已批准 `untimed/not_applicable`，且 owner/basis/reviewer/review_date 完整。
- missing SDC 情况下存在独立的 board/pad architecture basis。

不销账：

- pending/rejected row。
- 仅存在 candidate 或自动名称分类。
- async/config 但 exception 尚未由 30 批准。
- mapping unresolved 或 direction 未确定。

销账必须以 resolved `pad_inventory` 状态为最终 gate：

- `constrained + timing_active=yes`：04 销账；
- approved `not_applicable`：04 销账；
- `route_to_30` 或 `pending`：04 不销账。

`route_to_30` intent 即使已 approved，或同一 pad 另有 approved NA review row，也不由 04 销账；30 正式 exception 成功后负责该 exception-only endpoint。

若该 exact pad edge 已被既往 04 transaction 以 `constrained/not_applicable` 写入非空 `added_bits`，仅当所有已发布 required 04 view 都不再为该 edge 保留 `constrained/not_applicable` owner 时，才禁止在同一 run root 内改成 `route_to_30`。另一 required view 仍正常拥有该 edge 时允许 mixed-view `constrained/route_to_30`，且执行顺序不得改变结果；当最后一个 04 normal owner 也转移给 30 时，union-only accounting 无法撤销旧 owner，脚本必须 fail closed 并要求 fresh run root。

写回采用 exact bit union，不再生成 pending/removed log。若 top pad fanout 到多个 harden sink，top-port command 的 resolved coverage 必须传播到全部 direct edge，每个 constrained/NA sink bit 分别更新；`route_to_30/pending` edge 不更新。04 必须通过共享 transaction 提交，并输出：

```text
04_middle/port_accounting_delta.csv
04_middle/port_accounting_delta.meta
04_middle/completion/<stage>_<corner>.meta
```

delta 的 owner ID 必须引用 `pad_id`。completion 只允许在 required view、无 error/sync change、SDC/pad inventory/delta 全部发布后标 complete。

所有 required 04 view complete 后，04 发布 run-wide `04_middle/stage_completion.meta`，证明 pad inventory resolved view 已稳定。每次累计 inventory 改变时，所有已完成 required view 的 completion 都必须刷新 `pad_inventory_digest`，run-wide `required_view_completions` 必须引用这些最终 completion 文件。复用 prior view completion 时必须重新核对其 output SDC 以及已声明的 `00_stage_completion`、`01_clock_inventory` digest；上游 artifact 变化时 prior view 必须被排除并重跑。即使本 run 没有 active IO timing view，04 仍须执行 pad classification/audit 并发布 header-only 或 reviewed pad inventory，供 10/20/30 排除 pad edge。

一个 run root 的全部 required 04 view 必须使用同一 tool surface。`pad_inventory.meta`、`port_accounting_delta.meta`、per-view completion 和 run-wide completion 都必须记录 `tool`并在 resume 时核对；不同 surface 不得混用 prior inventory/completion/accounting。由于 accounting 是 append-only union，需要切换 surface 时必须使用 fresh run root。旧 flat 产物没有 `tool` 字段时只能按其历史实际行为解释为 `sta`。

已有 `port_accounting_delta.meta` 必须保留显式、非空的 append-only `transactions` 列表；每个 transaction 必须是 object，并含非空且唯一的 `transaction_id`。meta 的 `delta_csv_digest` 必须认证当前 CSV；CSV 中每个非空 transaction ID 都必须能在 meta transaction history 中找到，且按 ID 分组后的 rows 必须匹配该 transaction 的 `delta_rows_digest`。真实的 empty-delta transaction 以空 rows digest 验证；任一历史 row 被删除、篡改或失去 provenance 时，脚本必须 fail closed 且不得改写正式 SDC、completion、accounting 或 review workbook。

## 10. 检查规则

### Error

- port workbook 缺失或 direct pad mapping 不可解析。
- top port/direction 与表单冲突。
- inout approved row 未选择本 run 的 input/output effective direction。
- range/subrange evidence 存在未映射、重复映射 bit，或 flat row 使用 wildcard/port_list/pattern。
- duplicate pad mapping 语义冲突。
- rule 引用未知 clock。
- apply row 缺 value/owner/basis/review。
- inout 仍把 connection 放在 `Inout Name`。
- Used 状态包含非法/越界 bit。
- workbook 在写回期间被外部修改。
- 00/01 upstream completion 缺失、无效、未完成或 provenance/structure/clock inventory digest 不一致。
- required view、structure/accounting/upstream artifact digest、transaction/delta/completion 校验失败。
- `route_to_30` row 缺 pad_id、owner/basis/review，或仍由 04 销账。

### Warning

- missing harden SDC。
- pad 缺 electrical environment 或 delay intent。
- input 只给 delay 没给 transition/drive，或 output 只给 delay 没给 load。
- bit-level rule 只覆盖 bus 的一部分。
- async/config classification 需要 30 follow-up。

## 11. 与其它 Stage 的边界

- 01 创建 IO delay 引用的 clock。
- 02 设置 clock 自身 timing property，不拥有 pad。
- 03 定义 clock relation，不拥有 pad。
- 10/20 排除所有 pad-related direct edge。
- 30 处理 04 明确 `route_to_30` 的 async/config pad path exception，并必须引用 `related_04_pad_id`；04 仍拥有 pad electrical/IO 环境。其它 active 04 timing 不得被 30 冲突覆盖。

## 12. 命令行

```bash
python3 04_extract_soc_io_pads.py \
  --run-root <run_root> \
  --stage <stage> \
  --corner <corner> \
  --tool <sta|synth|both>
```

`stage/corner` 可按项目需要默认 `all/all`，`tool` 默认 `sta`。不接受 scenario 选择。
