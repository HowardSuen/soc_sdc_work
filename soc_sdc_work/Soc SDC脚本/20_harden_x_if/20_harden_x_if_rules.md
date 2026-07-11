# 20_harden_x_if.sdc 规则说明

本文定义 `common/20_harden_x_if.sdc` 的职责、输入来源、channel 归并方法、表单字段和生成检查规则。

## 1. 目标

`20_harden_x_if.sdc` 用来表达 SoC 视角下 harden/subsys 边界的普通 interface timing budget。

20 的判断依据是约束意图，不是 SDC 命令名字：

- 普通 harden/subsys interface budget 归 20。
- 改变默认 STA 分析语义的 exception 归 30。
- 结构性 feedthrough 先归 10。
- SoC top pad 的外部 IO 环境归 04。

第一版 20 的最终 SDC 只生成 reviewed `set_max_delay` / `set_min_delay`，不直接生成 instance pin 上的 `set_input_delay` / `set_output_delay`。

需要特别注意：20 生成的 `set_max_delay` / `set_min_delay` 是 SoC boundary-to-boundary channel datapath budget，约束的是两个 SoC 级 endpoint 之间的 datapath，例如 top-level interconnect / glue logic / wrapper 组合逻辑。它不是 block 级 clock-relative `set_input_delay` / `set_output_delay` 的语义等价替换。

```tcl
set_max_delay <value> -datapath_only -from <src_endpoint> -to <dst_endpoint>
set_min_delay <value> -datapath_only -from <src_endpoint> -to <dst_endpoint>
```

`-datapath_only` 的使用需要按工具确认。第一版规则以 STA/PT 类 signoff 语义为主；若用于 DC/综合，应在 flow 中明确该工具对 `-datapath_only` 的支持和含义，或者生成 synthesis 专用版本。

## 2. 核心原则

### 2.1 按 interface channel 归并

20 不是逐条 SDC 命令转换，而是按 interface channel 归并后生成。

一个 channel 表示 SoC 内部一条明确的连接关系：

```text
src instance/output canonical bit endpoint -> dst instance/input canonical bit endpoint
```

例如：

```text
u_harden_a/data_o -> u_harden_b/data_i
u_harden_a/ctrl_o[7] -> u_harden_b/ctrl_i[3]
```

最终只生成一组 reviewed budget：

```tcl
set_max_delay <reviewed_max> -datapath_only \
  -from [get_pins u_harden_a/data_o] \
  -to   [get_pins u_harden_b/data_i]

set_min_delay <reviewed_min> -datapath_only \
  -from [get_pins u_harden_a/data_o] \
  -to   [get_pins u_harden_b/data_i]
```

20 继承 `00_harden_port_inventory` 的 bit-expanded 机器粒度。scalar endpoint 使用 `port`；vector endpoint 使用 `port[index]`。若原始集成表单描述 bus/range 连接，bit-to-bit 配对必须已经由 00 写入 `connection_inventory.csv`；20 只消费该 edge 表生成 per-bit channel，不在本阶段重新猜 bit order。

### 2.2 channel 端点来自 00 connection inventory

harden input 的 `-from` 端点应优先从 00 `connection_inventory.csv` 推断。

harden output 的 `-to` 端点也应优先从 00 `connection_inventory.csv` 推断。

脚本不应只根据单个 harden SDC 中的 `get_ports` 目标端口孤立生成约束；必须结合 00 `connection_inventory.csv` 确认真实连接端点。若缺少对应 `connection_id`，该 channel 只能进入 `needs_review`，不能自行从原始 range 重建。

### 2.3 input/output delay 原值不能默认等价为 channel max

同一 channel 可能同时从两端 SDC 提取到 budget 信息：

```text
u_harden_a/data_o output_delay -max = 1.5
u_harden_b/data_i input_delay  -max = 1.2
```

这些数值只有在明确的 budget 约定下，才能作为 SoC channel 的 datapath budget 候选。

常规 block 级 `set_input_delay` / `set_output_delay` 通常是 clock-relative IO 约束，可能已经包含外部 launch/capture 寄存器、clock-to-Q、setup 需求或板级/接口假设。它与：

```tcl
set_max_delay <value> -datapath_only -from <src_endpoint> -to <dst_endpoint>
```

不是量纲等价关系。若直接把 clock-relative delay 原值写成 `-datapath_only` max delay，会丢掉周期、launch/capture clock 关系、uncertainty/skew 等信息。

因此 20 必须为每条 channel 明确 `budget_model`。

### 2.4 budget_model

第一版 `budget_model` 建议：

```text
interconnect_budget
clock_relative_io_delay
manual_budget
unknown
```

含义：

- `interconnect_budget`：harden/subsys owner 明确声明该 input/output delay 数值是给 harden 边界外 SoC channel 预留的 datapath budget。只有这种情况下，脚本才能用原始 max 值自动归并为 `converted_max`。
- `clock_relative_io_delay`：原始值是常规 clock-relative input/output delay。脚本只记录为证据，不自动转换为 `set_max_delay -datapath_only`；需要根据架构 budget、clock period、02 中的 uncertainty/latency 策略等重新推导，或由 reviewer 手工给出 `converted_max`。
- `manual_budget`：`converted_max` / `converted_min` 来自 SoC 架构预算或人工裁决，不直接来自 block SDC 原值。
- `unknown`：预算语义不明确，不允许 emit。

当且仅当 `budget_model = interconnect_budget`，且两端都提供 max 候选时，第一版自动归并规则为：

```text
converted_max = min(output_delay_max, input_delay_max)
```

也就是取更紧的 max budget。

如果两端 max 差异超过项目阈值，脚本应 warning，要求 reviewer 确认差异原因。

如果 `budget_model = clock_relative_io_delay` 或 `unknown`，脚本不得自动执行上述 `min()` 转换。

若 approved 行满足自动归并条件且 `converted_max` 为空，脚本可以在当次运行中填入内存值并回写 `converted_max` / `max_source` / `derivation_basis` 到表单。该类确定性回写不视为新增待 review 行，不阻塞当次 SDC 生成。

### 2.5 min budget 必须 review 后 emit

`set_input_delay -min` 和 `set_output_delay -min` 在 block 级 SDC 中经常承载 hold/sign convention。尤其 `set_output_delay -min` 可能是负值，不能无脑转换为 SoC top 的 `set_min_delay`。

第一版规则：

- 脚本可以提取原始 min 值并给出候选。
- 只有在表单中 `emit_min = yes` 且 `review_status = approved` 时，才生成 `set_min_delay`。
- 如果两端 min 都已由 reviewer 归一为同一语义的 channel minimum datapath delay，则更紧规则为：

```text
converted_min = max(normalized_output_min, normalized_input_min)
```

## 3. 输入来源

### 3.1 00 connection inventory

20 用 00 `connection_inventory.csv` 建立 SoC 连接关系，包括：

- SoC 下有多少个 harden/subsys。
- 每个 harden/subsys 的 instance name。
- 每个 input bit 来源于哪个 instance/output bit 或 SoC top pad bit。
- 每个 output bit 去向哪些 instance/input bit 或 SoC top pad bit。
- 一个 harden 可能被例化多次，所有规则按 instance 生效。
- bus/range 连接的 bit-to-bit 展开结果；20 不在本阶段重新猜测 bit order。

20 脚本必须先根据 00 `connection_inventory.csv` 建立 channel inventory，再把 SDC 候选约束归并到 channel 上。原始集成表单只作为诊断引用，不是 20 direct channel 的机器真源。

### 3.2 harden/subsys SDC

20 主要提取 harden/subsys SDC 中的非 pad interface delay：

```tcl
set_input_delay  ...
set_output_delay ...
```

这些命令只作为 interface contract 候选，不直接原样搬到 SoC top。

### 3.3 01 clock inventory

20 需要引用 01 的 clock inventory 做辅助检查：

- 判断端口是否是 clock port。
- 检查原始 delay 引用的 clock 是否能映射到 SoC clock。
- 检查 channel 两端是否属于预期 clock domain。

20 不创建 clock object。

### 3.4 02 / 03 约束信息

20 的 budget 推导可能依赖 clock period、uncertainty、latency、stage/corner 策略，这些信息归 02 管理。20 不应在脚本内部私自散落 hard-coded uncertainty 或 corner 假设；若 `converted_max` 不是直接来自 `interconnect_budget` 约定，必须在 `budget_basis` 中说明其与 01/02 clock setup 的关系。

20 需要与 03 的 clock relationship 信息保持一致。若 channel 两端 clock 在当前 assembled view 中被声明为 `asynchronous` / `logically_exclusive` / `physically_exclusive`，则该 channel 默认不能生成普通同步 interface budget；应转 30 或由 reviewer 明确给出 override basis。

第一版脚本先在 `interface_budget.clock_relation` 中保留人工/review 入口，并据此阻断非 `synchronous` / 非 `unknown` 的 channel 生成普通 20 budget。后续可再扩展为自动读取 03 assembled view 并注入该字段。

## 4. 与其它 SDC 的边界

### 4.1 与 04_soc_io_pads.sdc

如果 harden/subsys port 连接到 SoC top pad，该约束不进 20。

- pad input/output delay、load、driving cell、input transition 归 04。
- 20 只处理 SoC 内部 harden/subsys interface channel。

### 4.2 与 30_harden_to_harden_exception.sdc

普通 interface budget 归 20。

exception 性质的路径归 30，例如：

- false path。
- multicycle path。
- asynchronous handshake path。
- configuration path。
- reset/test/mode-specific override。
- 为了偏离普通同步接口预算而设置的 `set_max_delay` / `set_min_delay` override。

### 4.3 与 10_feedthrough.sdc

如果路径是结构性 feedthrough，例如 harden 内部不锁存、只从 input 纯穿到 output，则优先归 10。

20 只表达普通 harden/subsys 边界 timing budget。结构性 feedthrough 由 10 先识别和建模，20 基于 10 的 feedthrough inventory 还原真正的 end-to-end source/destination。

20 脚本会读取 10 的 `feedthrough_inventory.csv`。对于 00 direct edge 中进入 `fti_*`、离开 `fto_*` 的穿通段，20 不把 feedthrough harden 当作普通 timing endpoint；若 10 inventory 中对应 segment 为 `matched`，20 会按同一 `chain_id + bit_index` 拼出真正的 end-to-end channel，例如：

```text
u_a/data_o[0] -> u_ft/fti_0_a2c_data[0]
u_ft/fto_0_a2c_data[0] -> u_c/data_i[0]

20 channel:
u_a/data_o[0] -> u_c/data_i[0]
```

若 10 inventory 缺失、segment 不是 `matched`、或无法唯一找到进入/离开 edge，该 feedthrough path 只能留在 report / pending review，不能由 20 自行猜测 endpoint。

### 4.4 与 module/block signoff SDC

block 自身 signoff 时，`set_input_delay` / `set_output_delay` 仍然可以作用于 block top port。

SoC top 使用 20 时，不直接把这些命令改成：

```tcl
set_input_delay  ... [get_pins u_harden/in]
set_output_delay ... [get_pins u_harden/out]
```

因为在 SoC top DC/STA 视角下，instance pin 上的 input/output delay 语义不如 boundary `set_max_delay` / `set_min_delay` 清楚。

### 4.5 与常规时钟 STA

如果 harden/subsys 以可见 wrapper/netlist 方式集成，且边界两端寄存器、clock path 和 timing arc 都可被 SoC STA 正常看到，那么普通 synchronous path 应优先由常规 clock STA 分析。此时 20 默认不再额外叠加 `set_max_delay -datapath_only`，否则可能与周期关系、skew/uncertainty 建模重复或冲突。

20 的 channel budget 主要适用于以下情况：

- harden/subsys 以 `.lib` / `.db` timing model 或 blackbox/abstract model 集成，边界内部细节不可见。
- SoC 架构明确要求对两个 boundary pin 之间的 interconnect/glue logic 给出显式 budget。
- block owner 交付的 SoC integration SDC 明确把某些 input/output delay 定义为边界外 `interconnect_budget`。
- 某些 fabric/harden 接口在当前阶段缺少完整 reg-to-reg 可见性，需要临时或正式的 reviewed channel budget。

表单中应记录 `timing_model` 或 `budget_required`，用于说明为什么该 channel 需要 20 budget。

## 5. channel 建模

### 5.1 channel 类型

第一版 channel 类型：

```text
harden_to_harden
fabric_to_harden
harden_to_fabric
```

不进入 20 的连接类型：

```text
top_pad_to_harden
harden_to_top_pad
pad_to_pad
clock_connection
feedthrough
exception_path
unknown
```

其中 `top_pad_to_harden` / `harden_to_top_pad` / `pad_to_pad` 归 04；`clock_connection` 归 01/02/03；`feedthrough` 归 10；`exception_path` 归 30。

### 5.2 channel endpoint

对 harden/subsys instance port，SoC endpoint 使用 instance pin：

```tcl
[get_pins u_inst/port_name]
[get_pins {u_inst/port_name[3]}]
```

对于 `fabric_to_harden` / `harden_to_fabric`，如果 00 `connection_inventory.csv` 不能给出具体 fabric endpoint，脚本应保留 channel 候选但不自动生成 SDC；需要人工补齐 endpoint 或改用项目约定的 endpoint collection。

`src_port` / `dst_port` 字段使用 00 canonical key。`channel_inventory` 必须保留 00 `connection_id`，用于证明该 bit pairing 来自同一个 edge 真源。`channel_id` 必须 bit-stable，建议将 `[]` 归一为 `_bitN`，例如：

```text
CH_u_a_ctrl_o_bit7__u_b_ctrl_i_bit3
```

同一个整 bus 上多个 bit 使用多个 channel_id；report 可以额外提供 bus summary，但不能替代 bit channel。

### 5.3 一对多连接

如果一个 output port fanout 到多个 harden input，每条 sink 连接建立独立 channel：

```text
u_a/out -> u_b/in0
u_a/out -> u_c/in1
```

每条 channel 独立 review 和生成 budget。

如果一个 bus 的不同 bit fanout 到不同 sink，仍按 bit 展开：

```text
u_a/ctrl_o[0] -> u_b/ctrl_i[0]
u_a/ctrl_o[1] -> u_c/ctrl_i[0]
```

这两条 channel 独立消账，不能因为 `ctrl_o` 其中一部分已处理就删除整个 bus。

## 6. 从 input/output delay 到 channel budget

### 6.1 harden input delay

block SDC：

```tcl
set_input_delay -max 1.2 -clock clk [get_ports data_i]
set_input_delay -min 0.1 -clock clk [get_ports data_i]
```

如果集成表单确认：

```text
u_src/data_o -> u_dst/data_i
```

则 20 先记录为 destination input delay 候选。只有当该原始 delay 被确认是 `interconnect_budget`，或 reviewer 设置 `budget_model = manual_budget` 并给出 `derivation_basis`（例如 `period_based_budget`）后，才能形成 20 SDC 候选：

```tcl
set_max_delay 1.2 -datapath_only \
  -from [get_pins u_src/data_o] \
  -to   [get_pins u_dst/data_i]

set_min_delay 0.1 -datapath_only \
  -from [get_pins u_src/data_o] \
  -to   [get_pins u_dst/data_i]
```

其中 `set_min_delay` 必须 review 后生成。

如果该 `set_input_delay` 是常规 clock-relative block signoff delay，则不得直接生成上述 `set_max_delay 1.2`。

### 6.2 harden output delay

block SDC：

```tcl
set_output_delay -max 1.5 -clock clk [get_ports data_o]
set_output_delay -min -0.2 -clock clk [get_ports data_o]
```

如果集成表单确认：

```text
u_src/data_o -> u_dst/data_i
```

则 20 先记录为 source output delay 候选。只有当该原始 delay 被确认是 `interconnect_budget`，或 reviewer 设置 `budget_model = manual_budget` 并给出 `derivation_basis`（例如 `period_based_budget`）后，才能形成 20 SDC 候选：

```tcl
set_max_delay 1.5 -datapath_only \
  -from [get_pins u_src/data_o] \
  -to   [get_pins u_dst/data_i]
```

`set_output_delay -min` 不自动转换为 `set_min_delay`。脚本应记录原始值、原始命令和 sign 风险，要求 reviewer 给出 `normalized_min` 后才能 emit。

### 6.3 两端归并

同一 channel 上可能有：

- source harden output port 的 output delay。
- destination harden input port 的 input delay。

若这些 max 候选均已确认属于同一 `interconnect_budget` 语义，第一版归并规则：

```text
converted_max = min(all_available_max_candidates)
```

若任一候选仍是 `clock_relative_io_delay` 或 `unknown`，该候选不能参与自动 `min()` 归并；必须先由 reviewer 给出 normalized channel datapath budget。

min 规则：

```text
converted_min = max(all_reviewed_normalized_min_candidates)
```

如果没有 approved `converted_min`，不生成 `set_min_delay`。

### 6.4 复杂 input/output delay

以下情况第一版不自动转换，进入表单 pending review：

- `-rise` / `-fall`。
- `-clock_fall`。
- `-add_delay`。
- 同一 port 多 clock。
- source-synchronous / DDR 接口。pad 侧 source-sync 约束归 04；harden/subsys 内部 interface source-sync 留到后续 20 扩展。
- 原始命令目标是 bus/pattern 且展开不明确。
- 原始 delay 引用的 clock 无法映射到 SoC clock。
- 原始 delay 同时带复杂 collection，例如多个 `get_ports`、多层 list 或变量。

## 7. 输出文件和 view 维度

20 的 interface budget 是时序数值，可能随 stage/corner/view 变化。第一版表单必须保留 `stage` / `corner` 字段，生成时不能把多个 corner 的数值平铺进同一个 SDC。

如果项目确认某些 interface budget view-independent，可以生成：

```text
common/20_harden_x_if.sdc
```

如果 budget 依赖 stage/corner，应生成 view-specific 文件：

```text
common/20_harden_x_if_<stage>_<corner>.sdc
```

例如：

```text
common/20_harden_x_if_prects_ss_125.sdc
common/20_harden_x_if_postcts_ff_m40.sdc
```

同一个 view 内，所有 common harden/subsys interface channel budget 仍归集到一个 20 文件。

### 7.1 assembled view

20 的检查和生成按 assembled view 进行。assembled view 是当前生成目标下实际会被 source 到同一个 analysis view 的 20 约束集合：

```text
view-independent common 20
+ 当前 stage/corner 的 common 20 view-specific 行
+ 当前 scenario 的 20 overlay 行
+ 当前 scenario/stage/corner 的 20 view-specific overlay 行
```

同一 assembled view 内，同一 channel 的普通 interface budget 不能依赖 source 顺序覆盖。若 view-independent 与 view-specific、common 与 scenario 对同一 channel 给出冲突的 approved budget，脚本必须报错或要求表单显式裁决。

未来若存在 mode-specific interface budget，再扩展 scenario overlay：

```text
scenarios/func_harden_x_if.sdc
scenarios/dft_scan_harden_x_if.sdc
scenarios/mbist_harden_x_if.sdc
scenarios/<scenario>_harden_x_if_<stage>_<corner>.sdc
```

20 文件在装配顺序中位于 10 feedthrough 之后、30 exception 之前。30 可以在最后覆盖 exception 性质的路径语义，但不应覆盖普通 20 budget 来清 timing。

## 8. 表单建议

建议表单至少包含两个 sheet：

```text
channel_inventory
interface_budget
```

### 8.1 channel_inventory

用于记录 00 `connection_inventory.csv` 推导出的 channel。

```text
channel_id
connection_id
scenario
stage
corner
channel_type
src_instance
src_module
src_direction
src_port
src_bit_index
src_endpoint
dst_instance
dst_module
dst_direction
dst_port
dst_bit_index
dst_endpoint
connection_source
is_pad_related
is_clock_related
is_feedthrough
timing_model
budget_required
clock_relation
note
```

### 8.2 interface_budget

用于记录从 harden/subsys SDC 提取并归并后的 budget。

```text
channel_id
scenario
stage
corner
channel_type
is_pad_related
is_clock_related
is_feedthrough
src_endpoint
dst_endpoint
timing_model
budget_required
clock_relation
budget_model
src_output_delay_max
src_output_delay_min
dst_input_delay_max
dst_input_delay_min
converted_max
converted_min
max_source
min_source
derivation_basis
original_src_clock
original_dst_clock
soc_clock
complex_options
tool_surface
datapath_only
min_sign_review
budget_basis
relationship_override_basis
apply
emit_max
emit_min
review_status
owner
source_sdc_file
source_line
source_command
source_digest
extraction_time
note
```

字段含义：

- `src_output_delay_*`：来自 source harden output port 的 `set_output_delay`。
- `dst_input_delay_*`：来自 destination harden input port 的 `set_input_delay`。
- `connection_id`：来自 00 `connection_inventory.csv`；经 10 feedthrough 拼接出的 end-to-end channel 可记录 direct edge id 与 `feedthrough_id` 的组合。
- `src_direction` / `dst_direction`：用于 pending 消账，必须能回到 `pending/<inst>.ports` 中的第一列方向。
- `src_endpoint` / `dst_endpoint` 必须对应 `channel_id` 指向的 bit-level endpoint；若使用 bus/range collection 作为人工 override，仍必须能回溯到具体 canonical bit channel。
- `timing_model`：说明 SoC STA 是否能看到普通 reg-to-reg path，例如 `visible_netlist`、`lib_blackbox`、`abstract_model`、`unknown`。
- `is_pad_related` / `is_clock_related` / `is_feedthrough`：从 channel inventory 带入 budget 行，用于阻断错误归属；这些行不应生成 20。
- `clock_relation`：记录该 channel 在 03/人工 review 中的关系，例如 `synchronous`、`asynchronous`、`logically_exclusive`、`physically_exclusive`、`unknown`；非 `synchronous` / 非 `unknown` 默认阻断普通 20 budget。
- `budget_model`：说明原始 delay 数值的语义，例如 `interconnect_budget`、`clock_relative_io_delay`、`manual_budget`、`unknown`。
- `converted_max`：最终用于 `set_max_delay` 的 channel datapath budget；只有 `interconnect_budget` 可自动取更紧 max，常规 clock-relative delay 必须重新推导或人工填写。
- `converted_min`：review 后的 normalized min 候选。
- `max_source` / `min_source`：记录最终值来自哪一侧或人工 override。
- `derivation_basis`：说明 `converted_max` / `converted_min` 如何推导，例如 `min_interconnect_budget`、`manual_arch_budget`、`period_based_budget`。
- `complex_options`：记录无法自动转换的 SDC 选项。
- `tool_surface`：说明生成目标，例如 `sta`、`dc`、`both`。
- `datapath_only`：说明是否生成 `-datapath_only`，以及该工具是否支持该语义。20 的普通 interface budget 表达的是 channel datapath budget，脚本生成时空值按 `yes` 处理；若项目确认该行不应使用 `-datapath_only`，必须显式填写 `no`。
- `min_sign_review`：说明 min 值是否完成 sign/hold 语义 review。
- `budget_basis`：必须说明 budget 来源，例如 block signoff assumption、架构预算、接口协议、人工裁决。
- `relationship_override_basis`：当 03 中已有非同步关系但仍要求生成 20 budget 时，必须说明裁决依据；正常情况下该 channel 应转 30。

## 9. 生成门槛

一条 channel 只有同时满足以下条件，才允许生成 SDC：

```text
apply = yes
review_status = approved
scenario/stage/corner 与当前生成 view 匹配
src_endpoint 非空
dst_endpoint 非空
channel_type 属于 20 支持范围
不是 pad-related
不是 clock-related
不是 feedthrough
不是 exception path
timing_model 非空，且说明该 channel 需要 20 budget
budget_model 非空且不为 unknown
若 budget_model = clock_relative_io_delay，必须有人工或公式化 derivation_basis，不能直接使用原始 input/output delay 原值
emit_max = yes 且 converted_max 非空，才生成 set_max_delay
emit_min = yes 且 converted_min 非空且 min_sign_review 完成，才生成 set_min_delay
tool_surface / datapath_only 策略已确认
budget_basis 非空
```

pending / needs_review / rejected 行不生成。

## 10. 检查规则

### 10.1 error

以下情况应阻断生成：

- channel 缺少 `src_endpoint` 或 `dst_endpoint`。
- channel endpoint 不是 00 canonical bit endpoint，或用整 bus/range 代表多个 bit。
- channel 缺少 00 `connection_id`，且不是 reviewer 明确补齐的 fabric/manual endpoint。
- 00 `connection_inventory.csv` 中 bus/range 连接未展开为 per-bit edge，或展开后 width/order 不一致。
- 同一个 `channel_id` 对应多个不同 bit endpoint，或同一 bit endpoint pair 产生多个不同 `channel_id`。
- channel 标记为 pad-related 却进入 20。
- channel 标记为 clock-related 却进入 20。
- channel 标记为 feedthrough 却进入 20。
- channel 标记为 exception path 却进入 20。
- 同一 assembled view 中，同一 channel 出现多条 approved 且 `converted_max` / `converted_min` 不一致的生成行，且没有显式裁决。
- 同一输出 SDC 中混入多个 corner/stage 的 view-specific budget。
- `timing_model = visible_netlist` 且 `budget_required != yes`，却要求生成 20 budget。
- `budget_model = unknown` 却要求生成。
- `budget_model = clock_relative_io_delay` 且没有 `derivation_basis` / `budget_basis` 说明，却直接把原始 delay 值作为 `converted_max`。
- channel 两端 clock 在当前 03 assembled view 中被声明 `asynchronous` / `logically_exclusive` / `physically_exclusive`，但仍生成普通 synchronous interface budget，且没有 `relationship_override_basis`。
- `emit_max = yes` 但 `converted_max` 为空。
- `emit_min = yes` 但 `converted_min` 为空。
- `emit_min = yes` 但 `min_sign_review` 为空或未通过。
- `tool_surface` 包含 DC/综合，但 `-datapath_only` 策略未确认。
- `review_status = approved` 但 `budget_basis` 为空。
- 原始 SDC 命令无法归属到任何 channel，却被要求生成。

### 10.2 warning

以下情况应 warning，要求 reviewer 关注：

- source output delay max 与 destination input delay max 差异超过阈值。
- 只有一端提供 max budget，另一端缺失。
- 原始 min 值为负数。
- 原始 input/output delay 带 `-rise` / `-fall` / `-clock_fall` / `-add_delay`。
- 原始 delay 引用的 clock 与 channel 两端 SoC clock domain 不一致。
- 同一 output fanout 多个 sink，但所有 sink 共用了同一个人工 budget，需确认是否合理。
- harden SDC 中存在非 pad input/output delay，但 00 `connection_inventory.csv` / 20 channel inventory 没有对应 channel。
- 00 `connection_inventory.csv` 有 channel edge，但两端 harden SDC 都没有 interface budget。
- `budget_model = manual_budget`，但没有引用架构预算、接口协议或 owner signoff 依据。
- `budget_model = interconnect_budget` 但 harden 交付文档没有明确说明该 input/output delay 是边界外 SoC channel budget。

### 10.3 coverage report

20 脚本应输出 coverage report：

- 所有 SoC 内部 harden/subsys channel 列表。
- channel 列表必须是 bit-level；coverage 可附 bus summary，但生成/消账使用 per-bit channel。
- 每条 channel 的 scenario/stage/corner view。
- 每条 channel 的 `timing_model`、`budget_required`、`budget_model`。
- 每条 channel 是否找到 source output delay。
- 每条 channel 是否找到 destination input delay。
- 每条 channel 的最终 `converted_max` / `converted_min`。
- 每条 channel 是否生成 `set_max_delay` / `set_min_delay`。
- 未生成原因，例如常规 STA 已覆盖、pad-related、clock-related、exception、missing budget、budget_model unknown、pending review。
- 两端 budget 差异较大的 channel 清单。
- clock-relative delay 被提取但未转换的 channel 清单。

### 10.4 pending 消账

20 只有在某条 `interface_budget` 行实际生成了 `set_max_delay` 或 `set_min_delay` 后，才可以从 `00_harden_port_inventory/pending` 删除该 channel 两端对应的 harden canonical bit key，并写入 `removed_log/20_harden_x_if.removed`。

删除规则：

- 只删除 exact canonical bit key，例如 `output data_o[7]`、`input data_i[3]`。
- `top` / `fabric` 端没有 harden pending 文件，不删除。
- 经过 10 feedthrough stitched 出来的 end-to-end channel，只删除真实 source/destination harden endpoint；不删除中间 `fti_*` / `fto_*`，这些端口应由 10 消账。
- 若待删除 key 不在 pending 中，但 previous removed log 已说明该 key 被早期 stage 消费，则视为幂等重跑；否则报 error。

## 11. 示例

### 11.1 明确 interconnect_budget 的 harden-to-harden channel

集成关系：

```text
u_a/data_o -> u_b/data_i
```

前提：`u_a` / `u_b` owner 明确声明下面的 max delay 是为 SoC boundary-to-boundary channel 预留的 interconnect budget，而不是常规 clock-relative IO delay。

`u_a` SDC：

```tcl
set_output_delay -max 1.5 -clock clk_a [get_ports data_o]
```

`u_b` SDC：

```tcl
set_input_delay -max 1.2 -clock clk_b [get_ports data_i]
```

20 表单归并：

```text
channel_id        CH_u_a_data_o__u_b_data_i
src_endpoint      [get_pins u_a/data_o]
dst_endpoint      [get_pins u_b/data_i]
timing_model      lib_blackbox
budget_required   yes
budget_model      interconnect_budget
src_output_max    1.5
dst_input_max     1.2
converted_max     1.2
max_source        min(src_output_max, dst_input_max)
derivation_basis  min_interconnect_budget
budget_basis      both owners define delay as SoC channel interconnect budget
apply             yes
emit_max          yes
review_status     approved
```

生成：

```tcl
set_max_delay 1.2 -datapath_only \
  -from [get_pins u_a/data_o] \
  -to   [get_pins u_b/data_i]
```

### 11.2 常规 clock-relative delay 不自动转换

集成关系：

```text
u_a/data_o -> u_b/data_i
```

`u_b` SDC：

```tcl
set_input_delay -max 1.2 -clock clk_b [get_ports data_i]
```

如果 harden owner 说明该值是常规 block signoff input delay，含外部 launch 假设或 clock-relative arrival，而不是 SoC channel interconnect budget，则表单应记录：

```text
budget_model      clock_relative_io_delay
converted_max     <blank>
apply             no
review_status     needs_review
note              requires period/02 budget/manual derivation before set_max_delay emit
```

不生成：

```tcl
# 不允许直接生成
set_max_delay 1.2 -datapath_only -from [get_pins u_a/data_o] -to [get_pins u_b/data_i]
```

### 11.3 pad-related channel

集成关系：

```text
top.pad_rx -> u_b/data_i
```

即使 `u_b` SDC 中有：

```tcl
set_input_delay -max 2.0 -clock v_pad [get_ports data_i]
```

该约束也不进 20，应归 04 作为 SoC IO/pad environment 处理。

### 11.4 exception path

集成关系：

```text
u_cfg/data_o -> u_core/cfg_i
```

如果该路径是 configuration handshake，架构要求不按普通同步接口 budget 分析，则不进 20，归 30。

## 12. 暂不处理

第一版暂不处理：

- 自动识别所有 exception path。
- 自动解析 DDR/source-synchronous 多边沿 input/output delay。
- 自动转换复杂 `set_output_delay -min` sign 语义。
- 自动推断 fabric 内部非 harden endpoint。
- 自动根据名字猜测 test/scan/mbist interface。

这些内容必须进入表单 review 或留给后续 scenario/20/30 机制处理。
