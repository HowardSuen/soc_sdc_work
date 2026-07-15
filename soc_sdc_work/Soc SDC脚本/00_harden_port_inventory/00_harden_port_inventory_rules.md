# 00_harden_port_inventory 规则说明

本文定义 SoC SDC flow 中 00 的端口/连接清单、scenario 初始化和默认销账规则。00 不生成 SDC；它把 SoC 集成表单解析成 01~30 可以稳定消费的机器产物，并初始化每个 scenario 的 pending 状态。

本文按现有 01~30 的运行方式定义：

- 00 正式输出 bit-level `connection_inventory.csv`，下游不再自行展开原始 bus/range。
- 00、01、02、03、04、10、20、30 均由命令行接收当前 scenario。
- port accounting 默认开启；01/04/10/20/30 默认更新 pending 和 removed log。
- 允许 harden SDC 分批交付；missing SDC 不阻断其它 available harden。
- 10 只处理 SoC-visible feedthrough-adjacent direct edge，不约束 harden 内部 `fti -> fto`。

## 1. 00 的职责

00 负责：

- 从 SoC 集成表单建立 instance、port、direction、range 和 connection 的统一解析结果。
- 把所有 direct connection 展开成逐 bit edge，并生成稳定的 `connection_id`。
- 为当前 scenario 选择 harden SDC，生成 availability manifest。
- 为当前 scenario 初始化每个 harden instance 的 pending port 文件。
- 维护 `00_disposition`，终结确认无需由 01~30 生成约束的 port。
- 输出可审查、可 diff 的 inventory/report。

00 不负责：

- 生成任何 SoC SDC。
- 解析 harden SDC 中的 clock、IO、timing budget 或 exception 语义。
- 根据 `fti_*` / `fto_*` 名字推断 harden 内部结构或 timing arc。
- 代替 01~30 做 constraint ownership 和 terminal disposition 裁决。

## 2. Scenario 和命令行

target 运行入口：

```bash
python3 00_harden_port_inventory.py \
  --run-root <run_root> \
  --scenario <scenario>
```

scenario canonical enum：

```text
common
func
scan
mbist
gpio_in
gpio_out
```

规则：

- 00 和每个下游 stage 都必须显式接收 scenario；下游不能依赖 00 context 隐式获得 scenario。
- 每个 stage 必须把命令行 scenario 写入 SDC、inventory、workbook 和 report header。
- 下游读取的 manifest、pending 和 removed log scenario 必须与命令行 scenario 一致；不一致时阻断。
- 同一个 target run root 可以保存多个 scenario 子目录。00 初始化一个 scenario 时不得删除或覆盖其它 scenario 的状态。
- `connection_inventory.csv` 描述 SoC 物理 direct edge，默认在 run root 内共享。若不同 scenario 使用不同有效连接，通过 `scenario_scope` 标识，不能为同一物理 edge 生成不同的 `connection_id`。
- 已存在的 connection inventory 与当前集成表单语义不一致时，00 必须阻断并要求显式重建，不能静默刷新后继续复用旧 scenario pending。

port accounting 默认开启。仅在明确的诊断运行中允许：

```bash
--no-port-accounting
```

使用该选项时不创建/更新 pending，report 必须明确标记 `Port accounting: disabled by explicit option`，且本次运行不能宣称完成 port closure。

## 3. 输入来源

00 读取：

```text
<run_root>/inputs/info_all.xlsx
<run_root>/inputs/port_*.xlsx
<run_root>/inputs/ports_*.xlsx
<run_root>/inputs/ 下 harden SDC 及 scenario 映射字段/表单
```

集成表单是 00 的原始输入。01~30 使用 00 生成的 canonical port/connection 产物，不再各自从原始 range 猜测 bit order 或重新计算 `connection_id`。

00 的统一 parser 至少完成：

```text
instance/module mapping
port direction validation
canonical scalar/bit port expansion
direct bit-level edge expansion
stable connection_id
src/dst endpoint key
top/pad/clock/feedthrough/constant/NC classification hints
source workbook/sheet/row traceability
```

## 4. 目录和固定产物

### 4.1 Target `--run-root` 布局

固定输入产物：

```text
00_middle/connection_inventory.csv
00_middle/scenario/<scenario>/harden_sdc_manifest.csv
00_middle/scenario/<scenario>/pending/<inst>.ports
00_middle/scenario/<scenario>/removed_log/00_disposition.removed
00_result/reports/inventory_report_<scenario>.txt
```

其中：

- `connection_inventory.csv` 是所有下游 stage 的 required machine input。
- manifest 和 pending 按 scenario 独立。
- 00 只创建当前 scenario 的 pending 和 `00_disposition` log；01/04/10/20/30 的 removed log 由对应 stage 写入其规则指定的 scenario middle 目录。
- 后续 stage 做 previous-owner/idempotency 检查时，必须读取当前 scenario 的所有早期 removed log，不能读取其它 scenario 的日志。

### 4.2 Legacy cwd 布局

为兼容现有 01/20/30 cwd 入口，允许使用：

```text
00_harden_port_inventory/connection_inventory.csv
00_harden_port_inventory/harden_sdc_manifest.csv
00_harden_port_inventory/pending/<inst>.ports
00_harden_port_inventory/removed_log/*.removed
00_harden_port_inventory/inventory_report.txt
```

legacy cwd 一次只承载一个 scenario。其 scenario 仍必须由每个 stage 显式输入并写入 report。target 与 legacy 是两套运行布局，同一次 flow 不得交叉读取或同时修改两套 pending。

## 5. Connection Inventory

`connection_inventory.csv` 是 SoC direct connection 的 bit-level 机器真源。每行表示一个且仅一个：

```text
source canonical bit endpoint -> destination canonical bit endpoint
```

### 5.1 Bus/range 展开

例如集成表单描述：

```text
u_a.ctrl_o[7:4] -> u_b.ctrl_i[3:0]
```

00 必须展开为：

```text
u_a output ctrl_o[7] -> u_b input ctrl_i[3]
u_a output ctrl_o[6] -> u_b input ctrl_i[2]
u_a output ctrl_o[5] -> u_b input ctrl_i[1]
u_a output ctrl_o[4] -> u_b input ctrl_i[0]
```

规则：

- scalar connection 生成一行。
- vector/range connection 必须逐 bit 展开。
- fanout 的每个 `source bit -> destination bit` 分别生成一行和独立 `connection_id`。
- range 方向、位宽或 mapping 不明确时为 error，不得按名字、MSB/LSB 或常见写法猜测。
- 01/04/10/20/30 不得重新展开 range，也不得在找不到 edge 时回退到不精确的 whole-bus mapping。
- Tcl 中使用 bit object 时必须 brace 保护，例如 `[get_pins {u_a/ctrl_o[7]}]`。

### 5.2 最少字段

```text
schema_version
connection_id
scenario_scope
connection_type
src_instance
src_direction
src_port
src_bit_index
src_endpoint_key
src_soc_object
dst_instance
dst_direction
dst_port
dst_bit_index
dst_endpoint_key
dst_soc_object
fanout_index
range_source_expr
range_sink_expr
bit_pair_order
source_workbook
source_sheet
source_row
validation_status
owner_hint
note
```

字段规则：

- `connection_id` 必须稳定且 bit-specific，例如 `CONN_u_a_ctrl_o_bit7__u_b_ctrl_i_bit3`。
- `scenario_scope` 使用 `common`、单个 canonical scenario，或稳定排序的 scenario list；下游按当前 scenario 选择 `common + current scenario` edge。
- `connection_type` canonical enum 至少包括：

```text
harden_to_harden
fabric_to_harden
harden_to_fabric
top_pad_to_harden
harden_to_top_pad
pad_to_pad
clock_connection
feedthrough_candidate
constant_tie
no_connect
unknown
```

- `src_port` / `dst_port` 使用 canonical scalar/bit key；scalar 不带 index，vector 必须写 `port[index]`。
- `src_endpoint_key` / `dst_endpoint_key` 使用固定格式，并能回到 pending 中的 `(instance, direction, canonical port bit)`。
- `src_soc_object` / `dst_soc_object` 是 SoC SDC 可见对象；top/fabric/constant/NC pseudo endpoint 不生成 harden pending key。
- `range_source_expr` / `range_sink_expr` 保留表单原始 range，供审查重编号。
- `bit_pair_order` 记录 `msb_to_msb`、`lsb_to_lsb` 或 `explicit_map`；不明确时 `validation_status` 不能为 `matched`。
- `owner_hint` 只辅助 01/04/10/20/30 分类，不能替代 stage ownership 检查。

### 5.3 下游使用

- 01 使用 exact edge 解析 harden input clock 的 upstream bit。
- 04 使用 pad-related edge 建立 top pad 与 harden boundary 的映射。
- 10 使用 destination=`fti_*` 或 source=`fto_*` 的 SoC-visible direct edge。
- 20 使用未被 01/04/10 拥有的普通 functional direct edge。
- 30 使用 00 edge 或 10/20 inventory 锚定 exception endpoint。

`connection_inventory.csv` 不表达 harden 内部 `fti -> fto` segment。10/30 不得利用同一 harden 的 `fti`/`fto` 命名拼出跨内部段的 synthetic edge。

## 6. Harden SDC Manifest 和渐进交付

00 为当前 scenario 生成：

```text
00_middle/scenario/<scenario>/harden_sdc_manifest.csv
```

最少字段：

```text
scenario
inst_name
module_name
sdc_path
availability_status
note
```

`availability_status`：

```text
available
missing
not_required
```

规则：

- 每个当前 scenario required harden 必须恰好一行。
- `available` 路径必须唯一、存在且可读。
- `missing` 表示尚未交付，允许 partial run；不得解释为无 clock、无 timing 或无 exception。
- `not_required` 必须有明确依据，不能用来消除 missing warning。
- 01/04/10/20/30 根据 manifest 读取 available SDC，并把 missing 相关 evidence 标为 incomplete。
- missing harden 的相关 port 默认保留 pending；只有对应 stage 规则允许且具有 approved SDC-independent terminal basis 时才可例外销账。
- strict/signoff 运行可使用 `--require-complete-harden-sdc`，此时 required missing 阻断。

## 7. Pending Port

port accounting 默认开启。00 为当前 scenario 的每个 harden instance 生成一个 `.ports` 文件，一行一个 canonical port bit：

```text
input clk_i
input rst_n
input data_i[0]
output data_o[7]
inout gpio0
```

规则：

- 第一列只能是 `input` / `output` / `inout`。
- scalar 直接写 port name。
- vector/bus 必须展开为 `port[index]`。
- 文件按 direction + canonical key 稳定排序。
- pending 只表达“当前尚未由 port owner 终结”，不存放复杂状态列。
- 常量、tie-off、NC、mode-inactive 等 bit 仍先进入 pending，再由 `00_disposition` 精确销账。
- 所有 stage 只能删除 exact key；不得用整 bus、range、wildcard 或 pattern 删除。
- stage 默认更新 pending。显式 `--no-update-pending` 只用于诊断运行，必须写入 report，且不得宣称 accounting closure 完成。

## 8. Removed Log 和幂等性

removed log 每行至少记录：

```text
scenario
instance
direction
port
covered_by
reason
object_id
owner
reviewer
review_date
basis
```

示例：

```text
scenario=func instance=u_pll direction=output port=core_clk_o covered_by=01_soc_clocks reason=generated_clock object_id=u_pll_core_clk_o
scenario=func instance=u_iobuf direction=input port=pad_i covered_by=04_soc_io_pads reason=pad_related object_id=PAD_GPIO0
scenario=func instance=u_ft direction=input port=fti_a[0] covered_by=10_feedthrough reason=no_soc_budget_required object_id=FTE_CONN_001
scenario=func instance=u_a direction=output port=data_o[7] covered_by=20_harden_x_if reason=no_soc_budget_required object_id=CH_CONN_002
scenario=func instance=u_cfg direction=input port=cfg_mode_i[0] covered_by=30_harden_to_harden_exception reason=false_path object_id=EXC_CFG_001
```

规则：

- removed log 是审计和幂等证据，不是 connection source-of-truth。
- 删除前必须确认 exact key 当前仍在 pending。
- key 已不在 pending、但当前 scenario 的合法 previous removed log 已记录相同 owner/object 时，视为幂等重跑。
- key 已不在 pending 且无 previous owner 时为 error。
- 不得读取其它 scenario removed log 解释当前 scenario 的缺 key。
- 一个 canonical port 只能有一个 port-level removal owner；30 可以在已有 owner 后生成更窄 path exception，但不能写第二份 port removal owner。

## 9. Ownership 和销账顺序

默认 port-level owner 顺序：

```text
01_soc_clocks
04_soc_io_pads
10_feedthrough
20_harden_x_if
30_harden_to_harden_exception
00_disposition
```

### 9.1 01

01 终结已创建或确认的 SoC-visible harden clock port。vector clock 必须逐 bit 记录 clock 和销账。

### 9.2 02/03

02/03 不删除任何 harden port。clock timing budget 或 clock group 不能单独作为 data/reset/control port 的销账依据。

### 9.3 04

04 终结已完成 IO/pad timing/electrical environment 或 approved NA 的 pad-related harden port。

### 9.4 10

10 只处理 SoC-visible feedthrough-adjacent direct edge：

```text
u_src/out -> u_ft/fti
u_ft/fto  -> u_dst/in
u_ft1/fto -> u_ft2/fti
```

只有 edge 达到 `emit_budget` / `no_soc_budget_required` / `not_applicable` approved terminal disposition 后，10 才能删除相邻 endpoint。`route_to_30` / `pending` 不销账。

同一 harden 的 `fti -> fto` 是 harden 内部路径，不进入 SoC connection inventory，不生成 SoC SDC，也不能作为 pending 删除依据。

### 9.5 20

20 处理普通 functional direct channel。只有 `emit_budget` / `no_soc_budget_required` / `not_applicable` approved terminal disposition 可以销账。已识别的 exception-only channel 必须 `route_to_30`，20 不删除。

### 9.6 30

30 只处理有架构/协议/CDC/RDC/waiver 依据的 exception/override。exception-only endpoint 仍在 pending 时，由 approved 30 rule 终结；已有合法早期 port owner 时，只记录 path exception owner。

### 9.7 00_disposition

确认无需由 01~30 生成约束的 port，使用 `00_disposition`：

```text
no_constraint_required
waived
not_applicable
tie_off
no_connect
mode_inactive
unused
covered_by_methodology
```

每条 disposition 必须包含 scenario、exact canonical key、reason、owner、basis、reviewer 和 review date。`waived` 还必须有复审/失效日期。

## 10. 检查规则

以下情况必须 error：

- instance 重复、instance/module mapping 不唯一。
- port direction 非法或同一 canonical port direction 冲突。
- bus width/range 非法、bit mapping 不明确或位宽不匹配。
- 同一 destination bit 存在非预期多个 driver。
- `connection_id` 重复、一个 id 对应多个 bit edge，或相同 bit edge 生成多个 id。
- target stage 缺少 required `00_middle/connection_inventory.csv`。
- stage 命令行 scenario 与 manifest/pending scenario 不一致。
- 默认 accounting 运行中 pending 缺失或无法解析。
- stage 删除 range/wildcard、未批准对象、`pending` 或 `route_to_30` 对象。
- 同一个 port 出现冲突 port owner。
- missing SDC 被解释为没有 timing/exception 并据此自动销账。
- 10/30 试图建立或约束 harden 内部 `fti -> fto`。

以下情况 warning/review：

- `connection_type=unknown`。
- top/fabric/pad/clock/feedthrough 分类证据不足。
- fanout、cross-bit remap 或 range 重编号需要人工确认。
- harden SDC missing 导致 evidence incomplete。
- 最终 pending 数量超过项目阈值。

## 11. Regression

至少覆盖：

- scalar connection 生成一条 edge。
- bus/range 正向、反向和显式重编号逐 bit 展开正确。
- fanout 每个 sink 有独立稳定 `connection_id`。
- 01/04/10/20/30 对同一 00 edge 使用相同 endpoint 和 `connection_id`。
- func/scan 使用独立 scenario manifest、pending 和 removed log。
- accounting 默认开启；显式关闭时 report 不宣称 closure。
- available/missing/not_required manifest 行为正确。
- missing SDC 不阻断无关 available harden。
- 10 只拥有 feedthrough-adjacent direct edge，不生成内部 `fti -> fto`。
- 20 `route_to_30` 不删除 pending，30 approved exception 可以终结 exception-only endpoint。
- 重跑时 previous removed log 幂等，跨 scenario removed log 不得互相豁免。
