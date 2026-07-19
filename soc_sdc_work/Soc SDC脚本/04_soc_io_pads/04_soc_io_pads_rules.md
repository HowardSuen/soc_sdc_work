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
03_middle/stage_completion.meta
```

pad connection 由以下字段建立：

- `From Whom = top.<pad>`：top input/inout pad 驱动 harden input。
- `To Top = top.<pad>` 或 `<pad>`：harden output 驱动 top output pad。
- `Inout Connectivity = top.<pad>`：harden inout 与 top inout pad 相连。

04 必须按 actual HDL bit 展开 range。一个 top pad bit 对应多 destination harden input 时可以 fanout，但每条 direct mapping 单独记录。

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

### 4.2 Output pad

可能需要：

```text
output_delay max/min
load
max_transition
```

### 4.3 Inout / GPIO

inout 必须明确当前 run 的方向和 case 条件。实际连接来自 `Inout Connectivity`；`Inout Name` 是销账状态列。

- 当前 run 作为 input：按 input rule 生成。
- 当前 run 作为 output：按 output rule 生成。
- 方向未确定：保持 review，不生成 broad 双向约束。
- `bidirectional` 不属于单场景 runtime 的合法 effective direction；若硬件需要同一分析中双向计时，必须拆成独立 run。本规则只要求当前 run 的 input 或 output 一类覆盖。

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

一个 run 可有多个 timing stage/corner row。生成时按 `--stage` / `--corner` 选择当前 view；不再按 scenario 分层。

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

该 sheet 是 04 owner inventory，不替代原始 port workbook。多 view row 按 `pad_id/view_id` 共存，resolved CSV 不得在后续 view 运行时删除其它已 committed view。

04 必须把该 sheet 的 resolved machine view 发布为：

```text
04_middle/pad_inventory.csv
04_middle/pad_inventory.meta
```

除上述字段外，machine view 还必须记录 `pad_disposition`、`apply/review_status`、`related_exception_intent`、structure digest、source digest 和当前 exact endpoint。`pad_id` 使用 canonical pad tuple 的完整 SHA-256，不得使用易碰撞的可读字符串替换。

`pad_disposition` 使用：

```text
constrained
not_applicable
route_to_30
pending
```

- async/config pad path 需要 exception 时必须是 `route_to_30`；04 不为该 path 销账。
- `route_to_30` 必须 `apply=yes + review_status=approved`，并保留 pad electrical owner 状态供 30 引用。

### 7.3 `extraction_log`

记录每条 harden SDC evidence 的原命令、解析状态、映射 pad 和忽略原因。

## 8. 生成规则

- 只生成 `apply=yes + review_status=approved` 的 row。
- `clock_name` 必须存在于 `01_middle/clock_inventory.csv`，virtual clock 也必须由 01 创建。
- max/min 配对按 constraint_type 明确，不能把 blank 当 0。
- numeric value 必须 finite。
- `set_driving_cell` 必须有 library cell/pin 信息。
- 每条命令 target 必须是 exact top port/bit；不允许未 review 的 wildcard/range 扩大。
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
- 已批准 `untimed/not_applicable`，且 owner/basis/reviewer 完整。
- missing SDC 情况下存在独立的 board/pad architecture basis。

不销账：

- pending/rejected row。
- 仅存在 candidate 或自动名称分类。
- async/config 但 exception 尚未由 30 批准。
- mapping unresolved 或 direction 未确定。

`route_to_30` intent 即使已 approved 也不由 04 销账；30 正式 exception 成功后负责该 exception-only endpoint。

写回采用 exact bit union，不再生成 pending/removed log。若 top pad fanout 到多个 harden sink，每个 sink bit 分别更新。04 必须通过共享 transaction 提交，并输出：

```text
04_middle/port_accounting_delta.csv
04_middle/port_accounting_delta.meta
04_middle/completion/<stage>_<corner>.meta
```

delta 的 owner ID 必须引用 `pad_id`。completion 只允许在 required view、无 error/sync change、SDC/pad inventory/delta 全部发布后标 complete。

所有 required 04 view complete 后，04 发布 run-wide `04_middle/stage_completion.meta`，证明 pad inventory resolved view 已稳定。即使本 run 没有 active IO timing view，04 仍须执行 pad classification/audit 并发布空或 reviewed pad inventory，供 10/20/30 排除 pad edge。

## 10. 检查规则

### Error

- port workbook 缺失或 direct pad mapping 不可解析。
- top port/direction 与表单冲突。
- duplicate pad mapping 语义冲突。
- rule 引用未知 clock。
- apply row 缺 value/owner/basis/review。
- inout 仍把 connection 放在 `Inout Name`。
- Used 状态包含非法/越界 bit。
- workbook 在写回期间被外部修改。
- required view、structure/accounting digest、transaction/delta/completion 校验失败。
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
  --corner <corner>
```

`stage/corner` 可按项目需要默认 `all/all`。不接受 scenario 选择。
