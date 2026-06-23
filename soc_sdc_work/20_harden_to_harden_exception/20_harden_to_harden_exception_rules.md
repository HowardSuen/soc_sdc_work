# 20_harden_to_harden_exception.sdc 规则草案

本文定义 `common/20_harden_to_harden_exception.sdc` 的职责、分类方法、输入来源、表单字段和生成检查规则。

20 是高风险约束文件。它不负责普通接口 timing budget，也不负责补齐漏约束；它只表达 harden/subsys 之间确有架构依据、协议依据或 mode 依据的 path-level exception / override。

## 1. 目标

`20_harden_to_harden_exception.sdc` 用来表达 SoC 视角下 harden/subsys 之间的 path exception。

20 的判断依据是约束意图，不是 SDC 命令名字：

- 普通 harden/subsys interface timing budget 归 10。
- 改变默认 STA 分析语义的 path exception / override 归 20。
- top pad 外部 IO timing environment 归 04。
- clock relationship 归 03。
- 结构性 feedthrough 归 30。

20 第一版支持的 SDC 命令建议限制在：

```tcl
set_false_path
set_multicycle_path
set_max_delay      ;# 仅 exception/override 性质
set_min_delay      ;# 仅 exception/override 性质
```

暂不自动生成：

```tcl
set_disable_timing
set_data_check
remove_* exception
```

这些命令破坏性或工具差异更大，后续如确实需要，应单独加规则和 review 门槛。

## 2. 核心原则

### 2.1 missing timing 只是候选信号

harden port 上没有 `set_input_delay` / `set_output_delay`，只能说明该连接缺少普通 interface timing contract 的证据。

它不是自动生成 20 exception 的充分条件。

也就是说：

```text
no port timing != false path
no port timing != multicycle
no port timing != async path
```

一条 harden-to-harden interconnect 进入 20，需要同时满足：

```text
没有普通 10 timing budget 语义
+ 有明确 exception/override 语义
+ 有可审查依据
```

如果只发现“没有 port timing”，但没有协议、CDC、架构、mode 或 harden owner 说明，脚本只能生成 `needs_review` candidate，不能 emit 20 SDC。

### 2.2 先分类，再生成

20 不是逐条搬运 harden SDC exception。

脚本应先根据集成表单建立 harden-to-harden channel，再把 harden SDC、10 channel、03 clock relationship 和人工协议标签归并到同一个 candidate 上，最后由表单 review 决定是否生成。

推荐分类顺序：

```text
1. top pad related
   -> 04

2. clock creation / clock relationship
   -> 01 / 03

3. structural feedthrough
   -> 30

4. 有普通 interface timing budget 语义
   -> 10

5. 有明确 path exception / override 语义
   -> 20

6. 无 timing contract 且无 exception 依据
   -> needs_review，不生成
```

### 2.3 20 不替代 10

如果某个 channel 已经在 10 中生成普通 interface budget，则 20 不能在同一 check 维度上覆盖它，除非表单明确说明 20 是为了覆盖 10 的某个特殊子路径，并且 10 对应 channel 已经拆分或禁用。

常见错误：

```tcl
set_max_delay 1.2 -datapath_only -from A -to B   ;# 10 normal budget
set_false_path                 -from A -to B   ;# 20 又切掉同一路径
```

这种组合会让 10 budget 失效或语义自相矛盾，应作为 error 阻断。

但不同 check 维度可以共存，例如 active 10 max 与 20 min_delay_override 可以同时给同一路径定义上限和下限；这类组合必须有 `basis` 说明 min/hold floor 的来源。

### 2.4 20 不替代 03

如果两个 clock domain 在所有相关路径上都应被视为 asynchronous / exclusive，优先用 03 的 clock group 表达。

20 适用于更窄的 path-level 语义，例如：

- 同 clock 或 related clock 下的配置路径，不要求单周期收敛。
- 只对某个控制通道成立的 false path。
- 某个 handshake/status/config path 的协议级 multicycle。
- 某个 async crossing 中只需要切特定同步器前一级路径，而不是整个 clock domain。

03 async/exclusive 与 20 exception 的关系必须按命令语义区分：

- `set_false_path` vs 03 async：通常冗余。若 03 已经切掉两端 clock 的常规 setup/hold，再对同一 broad endpoint pair 打 false path 一般没有额外价值，应 warning。
- `set_max_delay -datapath_only` vs 03 async：可以是互补关系。异步 handshake、gray code、CDC 数据稳定窗口等路径，常见做法是先用 03 `set_clock_groups -asynchronous` 去掉常规 setup/hold，再用 20 `set_max_delay -datapath_only` 约束数据路径传播上限或 skew。
- `set_min_delay -datapath_only` vs 03 async：也可能是 CDC/协议要求的一部分，但必须有明确 hold/skew/协议依据。

因此，20 脚本不能把所有“03 已声明 async/exclusive + 20 path 约束”统一判为冗余或冲突。只有 `false_path` 这类切 timing 的命令与 03 async 高度重叠；`max/min_delay_override` 在有 CDC/协议依据时应允许。

同时要注意：单独的 `set_max_delay -datapath_only` 不会自动去掉常规 setup/hold 检查。异步路径若没有 03 async/exclusive 或其它 clock relation 处理，只打 20 max delay 并不能表示“该路径已安全建模”。这类情况应 warning 或 error，要求补 03/CDC 依据。

CDC / 异步 handshake 的数据稳定窗口建议采用成对范式：

```tcl
set_max_delay <max_window> -datapath_only -from <src> -to <dst>
set_min_delay <min_window> -datapath_only -from <src> -to <dst>
```

其中 03 负责去掉跨异步 clock 的常规 setup/hold，20 的 max/min 只约束数据路径传播上限和下限。若只生成 max、不生成 min，必须在 `basis` 中说明为什么不需要下限/skew 窗口约束。

注意：03 async 与 20 max/min 是否能在同一 path 上同时生效，取决于目标 STA 工具和项目 flow 的 exception priority 处理。有些工具/flow 会把 `set_clock_groups -asynchronous` 等效为高优先级 false path，从而遮蔽后续 path-level max/min。采用该范式前，必须用目标工具验证 `report_timing` / exception report 中 max/min 仍实际生效；若被 clock group 遮蔽，应采用项目确认的等效写法，而不是假设两者天然叠加。

### 2.5 common 与 scenario 分层

common 20 只放所有 mode/scenario 都成立的 exception。

以下约束必须下沉到 scenario：

- scan / mbist / dft mode only。
- test bypass mode only。
- GPIO 方向依赖。
- PLL bypass / boot mode / low power mode only。
- 依赖 `set_case_analysis` 选择后的 mux 单腿路径。

如果 exception 只有在某个 `set_case_analysis` 成立后才有效，它应放在对应 scenario exception 文件，而不是 common 20。

### 2.6 数值型 exception 需要 view 维度

`set_false_path`、`set_multicycle_path` 通常不随 corner 变化。

但 20 中的 `set_max_delay` / `set_min_delay` override 是数值约束，可能随 stage/corner/view 变化。第一版表单保留 `stage` / `corner` 字段：

```text
common/20_harden_to_harden_exception.sdc
common/20_harden_to_harden_exception_<stage>_<corner>.sdc    # 如存在 view-specific override
scenarios/<scenario>_exceptions.sdc
scenarios/<scenario>_exceptions_<stage>_<corner>.sdc         # 如存在 scenario + view-specific override
```

不能把多个 corner 的 `set_max_delay` / `set_min_delay` override 平铺进同一个 SDC。

### 2.7 20 必须是 object-level exception

20 只表达具体 SoC object 之间的 path-level exception。第一版禁止 clock-level exception。

不允许在 20 中生成：

```tcl
set_false_path -from [get_clocks clk_a] -to [get_clocks clk_b]
set_max_delay  5.0 -from [get_clocks clk_a] -to [get_clocks clk_b]
```

这类 clock-to-clock 约束本质上是 clock relationship，应回到 03 clock group 或收窄到具体 pin/port object。20 的 `from_collection`、`to_collection`、`through_collection` 应优先使用 SoC 可见的 `get_pins` / `get_ports`；net 只作为经过 review 的 through 辅助锚点。

## 3. 输入来源

### 3.1 集成表单

集成表单用于建立 SoC 连接关系：

- harden/subsys instance。
- input port 来源。
- output port 去向。
- fanout 关系。
- 端口是否连接 top pad、clock、feedthrough、fabric。
- 可选的 signal/protocol 标签，例如 `data`、`config`、`status`、`reset`、`test_mode`、`handshake`、`debug`。

20 必须基于 SoC 真实连接关系生成，不能只根据某个 harden SDC 中的 port 名字孤立生成 exception。

### 3.2 harden/subsys SDC

20 从 harden/subsys SoC integration SDC 中提取两类信息：

1. port timing contract 证据：

```tcl
set_input_delay
set_output_delay
```

这些信息帮助判断该 channel 是否应优先归 10。

2. port-level exception 证据：

```tcl
set_false_path
set_multicycle_path
set_max_delay
set_min_delay
```

只有当这些命令作用在 SoC 可见的 boundary port/port group，并且能映射到集成表单 channel 时，才可进入 20 candidate。

harden 内部 full signoff exception 不应直接提升到 SoC 20。如果命令引用 harden 内部 cell/pin，而 SoC top 视角不可见，脚本只能记录为 evidence，不生成 SoC 20。

提升 harden boundary exception 前，还必须确认 clock context 一致：

- harden SDC 中 exception 依据的 source/capture clock，在 SoC 01/03 视角下有等价映射。
- harden 内部 `create_clock` / `create_generated_clock` 提升到 SoC 后，clock name、master/source 关系或 generated clock 语义没有改变该 exception 的成立条件。
- 若 SoC 集成改变了 clock mux、PLL source、generated clock 关系或 clock group，该 harden exception 只能作为 evidence，不能直接生成。

`harden_clock_context_status` 为 `mismatch` 或 `unknown` 时，`extracted_harden_exception` 不得自动提升为 approved 20 rule。

### 3.3 10 channel inventory / budget 表

20 应读取或引用 10 的 channel inventory / interface budget 结果：

- 判断该 channel 是否已有普通 10 budget。
- 识别 10 中被标记为 `exception_path` 或 `clock_relation=async/exclusive` 的 channel。
- 避免 10 budget 与 20 exception 在同一 assembled view 中冲突。

这里的 active 10 budget 必须按 10 的 `interface_budget` 表生成状态判断，而不是只看 channel 是否存在。

第一版定义：

```text
active 10 budget =
  与当前 scenario/stage/corner assembled view 匹配
  + apply = yes
  + review_status = approved
  + budget 类型属于普通 interface budget
  + emit_max = yes 或 emit_min = yes
  + 对应 converted_max / converted_min 非空并会实际生成 SDC
```

仅存在于 `channel_inventory`、pending/rejected 的 10 行、或不 emit max/min 的记录，不应被当成 active 10 budget。

10/20 overlap 需要按 check 维度判断，不能一刀切：

```text
active 10 max + 20 false_path(setup/both) -> error
active 10 min + 20 false_path(hold/both)  -> error
active 10 max + 20 max_delay_override     -> error 或显式裁决
active 10 min + 20 min_delay_override     -> error 或显式裁决
active 10 max + 20 min_delay_override     -> 可允许，但必须有 basis 说明 min/hold 来源
active 10 min + 20 max_delay_override     -> 可允许，但必须有 basis 说明 max/setup 来源
```

也就是说，同类型或语义重叠才阻断；max 上限和 min 下限本身可以在同一路径上合法共存。

若 10 尚未生成表单，20 脚本也可以独立从集成表单重建 channel，但最终 report 应提示缺少 10 对照信息。

### 3.4 03 clock relationship

20 应参考 03 的 clock relationship：

- async / logically exclusive / physically exclusive clock pair 默认不应再生成普通同步 max/min override。
- 如果 max/min override 是 CDC/handshake skew 或传播上限约束，并带 `-datapath_only` 与明确 CDC/协议依据，它可以和 03 async 配套存在。
- 如果 entire domain relationship 已由 03 表达，20 path-level false path 通常冗余。
- 如果 20 只作用于 domain 内的特定子路径，必须在 `basis` 中说明为什么不用 03。

第一版可以先通过表单字段 `clock_relation` 人工填入；后续脚本再自动读取 03 assembled view。

### 3.5 人工协议/架构信息

以下信息通常需要人工或架构表单提供：

- path 是否为 config/static/status。
- path 是否为 async handshake。
- path 是否为 reset/test/debug。
- multicycle 具体 setup/hold cycle。
- max/min override 的数值和推导依据。
- CDC/RDC/STA waiver 或 signoff 记录。
- owner/reviewer。

没有这些依据，不允许把候选 path 直接生成到 20。

## 4. 与其它 SDC 的边界

### 4.1 与 10_harden_x_if.sdc

10 表达普通 harden/subsys interface timing budget。

20 表达 path exception / override。

同一个 harden-to-harden channel 的 `set_max_delay` / `set_min_delay` 归属按语义判断：

```text
正常 boundary-to-boundary datapath budget -> 10
偏离默认 STA 语义的 exception/override -> 20
```

示例：

```text
u_a/data_o -> u_b/data_i
```

如果两端 SDC 给出 input/output delay，且 owner 声明它是 interconnect budget，则归 10。

如果这是一个 config bus，只有 boot/config 阶段更新，功能运行时静态保持，并且架构确认无需单周期 timing，则可能归 20。

如果只是没有任何 delay 约束，但也没有 config/static/async/multicycle 依据，则不能归 20，只能报 needs_review。

### 4.2 与 03_soc_clock_groups.sdc

03 是 clock relationship，20 是 path-level exception。

如果 A/B 两个 clock domain 整体异步，使用 03。

如果只有 A->B 的某几根控制线是 async handshake 或 false path，而同一对 clock 下其它数据线仍需正常 STA，使用 20。

### 4.3 与 04_soc_io_pads.sdc

连接 SoC top pad 的路径不进 20。

- pad 外部环境、IO delay、driving、load、transition 归 04。
- pad-related false path 若确实存在，也应先在 04 的 IO/pad 表单中 review，而不是进入 harden-to-harden 20。

### 4.4 与 30_feedthrough.sdc

如果路径是结构性 feedthrough，例如 harden input 到 harden output 纯穿通，应优先归 30。

如果 feedthrough 上还需要 false path 或 max/min override，应先确认 30 的结构建模，再决定是否需要 20 追加 exception。不能用 20 掩盖 feedthrough 归属不清。

经过 feedthrough harden 的路径不是简单 endpoint pair，而是多跳路径，例如：

```text
u_a/data_o -> u_ft/in -> u_ft/out -> u_b/data_i
```

20 处理这类路径前，必须先确认 30 已经对 `u_ft/in -> u_ft/out` 穿通段建模，并在 20 表单中引用对应 `related_30_feedthrough_id`。20 的 exception 应显式锚定穿通段，通常通过 `through_collection` 指向 feedthrough input/output pin，不能只用隐式 `u_a -> u_b` endpoint pair 让脚本猜测路径经过哪里。

30 的 feedthrough 识别优先基于项目约定的 `fti_` / `fto_` port 命名，包括多 hop feedthrough 中的 `fti_<index>_` / `fto_<index>_` 规则。

若 30 尚未建模或 feedthrough segment 不明确，该 20 candidate 必须保持 `needs_review`，不得生成。

### 4.5 与 scenario pre-setup

如果某条 path 在某 scenario 下已经被 `set_case_analysis` 失活，通常不需要再对它打 20 exception。

若 exception 依赖 case value，它应放在对应 scenario exception 文件，并在表单中记录依赖的 case condition。

## 5. exception 分类

### 5.1 exception_type

第一版建议枚举：

```text
false_path
multicycle_path
max_delay_override
min_delay_override
max_min_delay_override
needs_review
not_exception
```

含义：

- `false_path`：该 path 不参与 STA timing check。
- `multicycle_path`：该 path 仍参与 STA，但 setup/hold cycle 与默认单周期不同。
- `max_delay_override`：该 path 需要一个 override max delay，不是普通 10 budget。
- `min_delay_override`：该 path 需要一个 override min delay，不是普通 10 budget。
- `max_min_delay_override`：max/min override 成对出现。
- `needs_review`：候选信息不足，不生成。
- `not_exception`：review 后确认不属于 20。

### 5.2 path_category

建议记录 path 语义分类：

```text
data
control
config
status
reset
test
debug
handshake
interrupt
cdc_sync
rdc_sync
static
unknown
```

`data` 不是不能进 20，但普通 data path 进入 20 必须有更强依据，例如协议明确 multicycle 或 architectural waiver。

`unknown` 不允许生成。

`reset` 路径进入 20 必须特别谨慎。对 reset path 打 `set_false_path` 可能同时关闭 recovery/removal 检查，隐藏异步复位释放时序风险。因此：

- `path_category = reset` 且 `exception_type = false_path` 应标为 high risk。
- `basis` 必须说明 recovery/removal 如何由其它约束、复位同步器、RDC signoff 或 STA waiver 保证。
- 若只想切 setup 或只想切 hold，应使用 `check_type` 精确表达，并确认目标工具对 recovery/removal 的映射语义。不能默认认为 `-setup` 一定保留所有 removal/recovery 检查。
- 若没有 recovery/removal 处理依据，不允许生成。

### 5.3 timing_contract_status

用于结合 harden SDC port timing 判断分类：

```text
both_sides_timed
src_timed_only
dst_timed_only
no_port_timing
clock_relative_only
interconnect_budget
unknown
```

解释：

- `both_sides_timed` / `src_timed_only` / `dst_timed_only`：存在普通 timing contract 证据，优先进入 10 review。
- `no_port_timing`：没有普通 timing contract 证据，只能触发 20 candidate review，不能直接生成。
- `clock_relative_only`：有 clock-relative block delay，但不能直接变成 20。默认应回到 10 做 interface budget / period-based budget review；若 reviewer 确认它不是普通 budget 且存在 exception 语义，再转 20。否则保持 `needs_review`。
- `interconnect_budget`：通常归 10，不归 20。

### 5.4 source_type

建议枚举：

```text
extracted_harden_exception
missing_timing_candidate
integration_tag
clock_relation_candidate
manual_entry
ten_rejected_as_exception
```

含义：

- `extracted_harden_exception`：来自 harden SDC 中可映射到 boundary port 的 exception。
- `missing_timing_candidate`：来自“harden-to-harden channel 缺少普通 port timing”的候选。
- `integration_tag`：来自集成表单的 signal/protocol 标签。
- `clock_relation_candidate`：来自 03 clock relation 的提示。
- `manual_entry`：人工新增。
- `ten_rejected_as_exception`：10 表单中已明确标记不属于普通 budget，应进入 20 review。

### 5.5 datapath_only 策略

`datapath_only` 不是单纯的 tool option，而是 timing 语义的一部分。`tool_surface` 只负责确认目标工具是否支持该选项；是否应使用 `-datapath_only` 应由 `path_category`、`clock_relation` 和 exception 意图共同决定。

第一版策略：

```text
CDC / async handshake / async data stability window:
  exception_type = max_delay_override / min_delay_override / max_min_delay_override
  clock_relation = async / logically_exclusive / physically_exclusive
  path_category = handshake / cdc_sync / status / control / data
  -> 默认必须 datapath_only = yes

同 clock / related clock 的功能性 override:
  exception_type = max_delay_override / min_delay_override / max_min_delay_override
  clock_relation = sync / related / same_clock / unknown
  -> 默认 datapath_only = no

其它情况:
  -> 必须由 basis 明确说明是否剥离 clock latency/skew
```

原因：

- CDC/异步 handshake 的 max/min 通常只想约束数据路径传播窗口，应该剥掉两端 clock network latency。
- 同 clock / related clock 的功能性 override 往往仍希望保留 clock skew/latency 影响，误加 `-datapath_only` 可能让约束失真。
- 若使用 `datapath_only = yes` 偏离上述默认策略，必须在 `basis` 中说明。

## 6. 表单建议

建议表单至少包含两个 sheet：

```text
exception_candidate
exception_rule
```

### 6.1 exception_candidate

用于记录脚本发现的候选路径，不直接生成 SDC。

```text
candidate_id
scenario
stage
corner
channel_id
source_type
path_category
timing_contract_status
src_instance
src_module
src_port
src_endpoint
dst_instance
dst_module
dst_port
dst_endpoint
src_clock
dst_clock
clock_relation
has_src_output_delay
has_dst_input_delay
related_10_channel_id
related_10_status
related_30_feedthrough_id
harden_clock_context_status
source_sdc_file
source_line
source_command
source_digest
extraction_time
candidate_reason
recommended_action
note
```

### 6.2 exception_rule

用于记录 review 后允许生成的 20 规则。

```text
exception_id
scenario
stage
corner
apply
review_status
owner
exception_type
path_category
channel_id
related_10_channel_id
related_30_feedthrough_id
src_endpoint
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
case_condition
source_type
source_sdc_file
source_line
source_command
source_digest
cdc_rdc_ref
sta_waiver_ref
protocol_ref
basis
risk_level
expiry_or_review_date
note
```

字段含义：

- `apply`：是否参与生成。
- `review_status`：`pending` / `approved` / `rejected` / `needs_review`。
- `exception_type`：决定生成哪类 SDC 命令。
- `path_category`：记录路径语义，辅助检查。
- `related_10_channel_id`：若该 path 与 10 channel 对应，必须填入，便于检查冲突。
- `related_30_feedthrough_id`：若 path 经过 30 feedthrough segment，必须填入对应 feedthrough 记录。
- `from_collection` / `to_collection` / `through_collection`：允许 reviewer 对 endpoint 做更细粒度裁剪。若为空，默认使用 `src_endpoint` / `dst_endpoint`。
- `clock_relation`：记录该 path 两端 clock 在 03/review 中的关系。
- `timing_contract_status`：记录 harden port timing 证据状态。
- `harden_clock_context_status`：若规则来自 harden SDC exception，记录 harden 视角 clock 与 SoC 视角 clock 是否等价，例如 `matched` / `remapped_equivalent` / `mismatch` / `unknown`。
- `check_type`：用于 `false_path` / `multicycle_path` 的检查粒度，建议枚举 `setup` / `hold` / `both`。缺省按 `both` 处理。
- `setup_cycles` / `hold_cycles`：用于 `set_multicycle_path`。
- `mcp_reference`：用于 `set_multicycle_path` 的 edge reference，建议枚举 `start` / `end` / `same_clock_default`。跨 clock multicycle 必须明确，不应依赖工具默认。
- `cross_clock_mcp_review`：跨 clock multicycle 的人工确认，例如 `approved` / `not_applicable` / `pending`。
- `datapath_only`：仅用于 max/min override。是否使用由 5.5 的方法学规则决定，`tool_surface` 只确认目标工具是否支持该选项。
- `case_condition`：若 exception 依赖 scenario case，应记录对应 mode/case 条件。
- `cdc_rdc_ref` / `sta_waiver_ref` / `protocol_ref`：外部依据引用。
- `basis`：必填，说明为什么这条 path 可以作为 exception。
- `risk_level`：`low` / `medium` / `high`，辅助 review。
- `expiry_or_review_date`：临时 waiver 或 early-stage exception 的复审日期。

## 7. 输出文件和 assembled view

### 7.1 输出文件

common view-independent exception：

```text
common/20_harden_to_harden_exception.sdc
```

common view-specific max/min override：

```text
common/20_harden_to_harden_exception_<stage>_<corner>.sdc
```

scenario view-independent exception：

```text
scenarios/<scenario>_exceptions.sdc
```

scenario view-specific max/min override：

```text
scenarios/<scenario>_exceptions_<stage>_<corner>.sdc
```

第一版如果没有数值型 view-specific override，可以只生成 view-independent 文件。

### 7.2 assembled view

20 的检查和生成按 assembled view 进行。assembled view 是当前 analysis view 中实际会被 source 的 20 约束集合：

```text
view-independent common 20
+ 当前 stage/corner 的 common 20 view-specific 行
+ 当前 scenario 的 20 overlay 行
+ 当前 scenario/stage/corner 的 20 view-specific overlay 行
```

同一 assembled view 内，不允许同一 path 同时存在互相冲突的 exception。例如：

```text
同一 path 同时 false_path 和 multicycle_path
同一 path 同时 false_path 和 max_delay_override
同一 path 多条 max_delay_override 但数值不同
```

这些冲突必须在表单中拆分 endpoint、拆 scenario，或显式裁决，不能靠 source 顺序覆盖。

原因是 STA 工具可能按 exception priority 静默裁决，而不是报错。例如 PrimeTime / Synopsys 类语义中，常见优先级可理解为：

```text
set_false_path > set_max_delay / set_min_delay > set_multicycle_path
```

如果同一路径同时命中 false path 和 multicycle，工具可能直接按 false path 处理，multicycle 被静默遮蔽；同理 max/min override 也可能遮蔽 multicycle。20 规则把这类 overlap 提前报错，是为了避免 reviewer 误以为所有 exception 都同时生效。

## 8. 生成规则

### 8.1 set_false_path

生成示例：

```tcl
set_false_path \
  -from [get_pins u_a/cfg_valid_o] \
  -to   [get_pins u_b/cfg_valid_i]
```

如果使用 through：

```tcl
set_false_path \
  -from [get_pins u_a/cfg_valid_o] \
  -through [get_pins u_cfg_bridge/cfg_valid_i] \
  -to [get_pins u_b/cfg_valid_i]
```

要求：

- `basis` 必须说明为什么 path 不需要 STA timing check。
- `path_category` 不能是 `unknown`。
- 不能仅因 `timing_contract_status = no_port_timing` 生成。
- 若同 path 同 check 维度已有 active 10 budget，必须先关闭/拆分 10 或给出裁决依据。
- `check_type` 控制切除粒度：`both` 生成普通 false path，`setup` 只切 setup 类检查，`hold` 只切 hold 类检查。缺省按 `both` 处理。
- `through_collection` 优先使用 SoC 可见的 pin/port。`get_nets` 或 net pattern 在综合/PnR 后名称不稳定，只有确无 pin/port 锚点时才允许使用，并必须在 report 中 warning。

示例：

```tcl
set_false_path -setup \
  -from [get_pins u_a/cfg_valid_o] \
  -to   [get_pins u_b/cfg_valid_i]
```

对于 reset/RDC 路径，是否使用 `-setup` / `-hold` 以及它们对 recovery/removal 的影响必须按目标工具确认。

### 8.2 set_multicycle_path

生成示例：

```tcl
set_multicycle_path 3 -setup \
  -from [get_pins u_a/data_o] \
  -to   [get_pins u_b/data_i]

set_multicycle_path 2 -hold \
  -from [get_pins u_a/data_o] \
  -to   [get_pins u_b/data_i]
```

上例是同 clock 或已确认同参照 clock 下常见的 setup=3、hold=2 写法，不应直接照搬到跨 clock path。

如果需要指定参照 clock，应显式生成 `-start` 或 `-end`：

```tcl
set_multicycle_path 3 -setup -end \
  -from [get_pins u_a/data_o] \
  -to   [get_pins u_b/data_i]

set_multicycle_path 2 -hold -start \
  -from [get_pins u_a/data_o] \
  -to   [get_pins u_b/data_i]
```

规则：

- `check_type = both` 或缺省时，`setup_cycles` 与 `hold_cycles` 必须成对填写，或由项目策略明确推导。
- `check_type = setup` 时，`setup_cycles` 必须填写，且 `basis` 必须说明为什么不需要配套 hold MCP。
- `check_type = hold` 时，`hold_cycles` 必须填写，且 `basis` 必须说明为什么只调整 hold。
- 只发 `set_multicycle_path N -setup` 不发对应 hold 是经典风险。它会改变默认 hold 检查关系，常见后果是把应检查的 hold 窗口推开，隐藏真实 hold 风险。因此 setup-only 必须显式设置 `check_type = setup` 并给出依据。
- 第一版建议不自动使用 `setup_cycles - 1` 作为 hold，除非表单或项目配置明确允许。
- `check_type` 可用于表达只生成 setup MCP、只生成 hold MCP 或 setup/hold 成对生成；但第一版默认要求 setup/hold 成对。
- `mcp_reference` 必须明确记录 `-start` / `-end` / 同 clock 默认参照。
- 若 `src_clock != dst_clock`，第一版默认将 multicycle 视为 high risk；除非 `mcp_reference` 明确、`cross_clock_mcp_review = approved`、且 `basis` 说明周期比/边沿选择/hold 推导，否则不得生成。
- `basis` 必须引用协议、架构预算或 owner signoff。

上面的 `-start` / `-end` 示例仅用于说明跨 clock MCP 的 edge reference 写法。同 clock MCP 通常不需要显式写 `-start` / `-end`，但仍必须明确 hold 策略。

### 8.3 set_max_delay / set_min_delay override

20 中的 max/min delay 只用于 exception/override，不用于普通 channel budget。

生成示例：

```tcl
set_max_delay 12.0 -datapath_only \
  -from [get_pins u_a/handshake_req_o] \
  -to   [get_pins u_b/handshake_req_i]
```

规则：

- 若它表达普通 boundary-to-boundary budget，应改归 10。
- 若它表达非默认协议 budget、handshake timeout、config path override 等，才归 20。
- `basis` 必须说明 override 数值的来源。
- `stage` / `corner` 必须处理清楚，不能把多个 corner 的数值写入同一个 SDC。
- `datapath_only` 是否使用必须按 5.5 方法学策略审核；`tool_surface` 只确认目标工具支持情况。
- 对异步 CDC/handshake 路径，`set_max_delay -datapath_only` 通常应与 03 async/exclusive 或明确 CDC clock relation 配套。只写 20 max delay 不会自动关闭常规 setup/hold。
- 对 `clock_relation = async/logically_exclusive/physically_exclusive` 且 `path_category = handshake/cdc_sync/status/control/data` 的 CDC/异步窗口约束，`datapath_only` 默认必须为 `yes`。
- 对同 clock / related clock 的功能性 override，`datapath_only` 默认应为 `no`；如果确实要剥掉 clock latency/skew，必须在 `basis` 中说明原因。
- CDC 数据稳定窗口优先使用 `max_min_delay_override` 成对生成 `set_max_delay -datapath_only` 与 `set_min_delay -datapath_only`。若只生成 max 或只生成 min，必须说明另一侧为何不适用。

### 8.3.1 CDC 数据稳定窗口范式

对异步 CDC 或异步 handshake 路径，推荐范式是：

1. 03 用 `set_clock_groups -asynchronous` 切掉常规 setup/hold。
2. 20 用 `set_max_delay -datapath_only` 约束传播上限。
3. 20 用 `set_min_delay -datapath_only` 约束最小传播下限/稳定窗口。

这类规则本质上是在表达数据路径的允许 skew 窗口，而不是普通同步 budget。通常应优先用 `max_min_delay_override` 成对建模；若只需要 max 或只需要 min，必须在 `basis` 中明确说明另一侧为何不适用。

采用该范式时还必须记录工具生效性依据：确认 03 的 async clock group 没有遮蔽 20 的 path-level max/min，或者记录项目 flow 使用的等效约束策略。

## 9. 生成门槛

一条 20 rule 只有同时满足以下条件，才允许生成：

```text
apply = yes
review_status = approved
scenario/stage/corner 与当前生成 view 匹配
exception_type 属于支持列表
src_endpoint/from_collection 或 dst_endpoint/to_collection 足够明确
若只指定单边 endpoint，basis 必须说明 broad scope 是有意设计
path_category 非 unknown
basis 非空
owner 非空
不是 pad-related
不是 clock creation / clock relationship
不是 feedthrough
不是普通 10 interface budget
若 related_10_channel_id 存在，必须确认 10 不会生成冲突 budget
若 exception_type = multicycle_path，cycle 字段与 check_type 匹配
若 multicycle_path 跨 clock，mcp_reference 与 cross_clock_mcp_review 完整
若 exception_type = max/min override，对应 value 完整且 view 维度清楚
若 exception_type = max_min_delay_override，max/min value 均完整
若为 CDC/异步窗口约束，datapath_only 策略与 max/min 成对策略已确认
若依赖 mode/case，scenario 与 case_condition 明确
```

`pending` / `needs_review` / `rejected` 行不生成。

## 10. 检查规则

### 10.1 error

以下情况应阻断生成：

- `apply = yes` 但 `review_status != approved`。
- `exception_type` 为空或不在支持列表。
- `basis` 为空。
- `owner` 为空。
- `path_category = unknown` 却要求生成。
- 仅以 `no_port_timing` / `missing_timing_candidate` 作为依据生成 exception。
- endpoint 无法解析到 SoC 可见对象。
- `from_collection` / `to_collection` / `through_collection` 直接引用 `[get_clocks ...]`，即 clock-level exception 进入 20。
- 目标 path 是 top pad related，却进入 20。
- 目标 path 是 clock creation / clock relationship，却进入 20。
- 纯 feedthrough segment 未经 30 建模、或没有额外 exception basis，却进入 20。
- path 经过 feedthrough segment，但没有对应 `related_30_feedthrough_id` 或没有明确 `through_collection` 锚定穿通段。
- 同一 assembled view 中，同一 path 同时存在 active 10 budget 和 20 exception，且二者 check 维度重叠，例如 10 max 与 20 false_path(setup/both)、10 max 与 20 max_delay_override、10 min 与 20 min_delay_override，且无显式拆分、禁用 10 或裁决依据。
- 同一 assembled view 中，同一 path 同时出现 `false_path` 与 `multicycle_path`。
- 同一 assembled view 中，同一 path 同时出现 `false_path` 与 max/min override。
- 同一 assembled view 中，同一 path 出现多条冲突 max/min override。
- `multicycle_path` 的 `setup_cycles` / `hold_cycles` 与 `check_type` 不匹配，例如 `check_type=setup` 但缺少 `setup_cycles`，或 `check_type=both` 但缺少任一侧且项目未配置自动推导策略。
- `multicycle_path` 跨 clock，但缺少 `mcp_reference`、`cross_clock_mcp_review` 或周期/边沿依据。
- `max_delay_override` 缺少 `max_value`。
- `min_delay_override` 缺少 `min_value`。
- `max_min_delay_override` 缺少 `max_value` 或 `min_value`。
- `exception_type = false_path` 或 `multicycle_path`，但 `datapath_only = yes`。
- CDC/异步窗口类 max/min override 要求 `datapath_only = yes`，但表单未填写 yes。
- `path_category = reset` 且 `exception_type = false_path`，但 `basis` 未说明 recovery/removal 的替代保证方式。
- `source_type = extracted_harden_exception` 且 `harden_clock_context_status` 不是 `matched` 或 `remapped_equivalent`。
- `apply = yes` 且 `expiry_or_review_date` 早于当前生成日期。
- 数值型 override 混入多个 stage/corner。
- common 20 中出现明显 mode-specific case，例如 scan/test/mbist/gpio direction，且未下沉 scenario。
- source harden SDC exception 引用 SoC 不可见内部 object，却要求原样生成。
- `tool_surface` 包含 DC/综合，但目标工具对对应 exception 命令或 `-datapath_only` 选项的支持未确认。

### 10.2 warning

以下情况应 warning，要求 reviewer 关注：

- harden-to-harden channel 没有 port timing，也没有 10 budget，也没有 20 decision。
- harden SDC 提取到 exception，但无法映射到集成表单 channel。
- harden SDC 提取到 port-level exception，但同 port 又存在普通 input/output delay。
- exception 覆盖 bus 的一部分 bit，需确认是否有意。
- endpoint 使用 wildcard/pattern，覆盖范围可能过宽。
- exception 只指定单边 endpoint，例如只有 `-from` 或只有 `-to`，覆盖范围可能过宽，需 reviewer 显式确认是否有意。
- `through_collection` 使用 `get_nets` 或 net pattern，跨综合/PnR stage 需复核命中对象。
- common 20 使用了看起来像 test/reset/debug/mode 的 signal，需要确认是否 mode-independent。
- 03 已经声明两端 clock async/exclusive，20 又对同 broad endpoint pair 打 false path，可能冗余。
- 03 已经声明两端 clock async/exclusive，20 又生成 `set_max_delay -datapath_only` / `set_min_delay -datapath_only`：这是可能合理的 CDC/handshake skew 约束，不应按冗余处理，但需要 `basis` / CDC 依据完整。
- 03 未声明 async/exclusive，但 20 basis 声称 async/CDC，或 20 使用 CDC max/min override，需要确认 03 是否也要更新；否则常规 setup/hold 仍可能存在。
- CDC/异步窗口只生成 `max_delay_override` 或只生成 `min_delay_override`，未采用 `max_min_delay_override` 成对约束，需要确认另一侧窗口为何不适用。
- active 10 max 与 20 min_delay_override、或 active 10 min 与 20 max_delay_override 共存；这是可能合法的上下界组合，但需要 `basis` 说明补充约束来源。
- 同 clock / related clock 的功能性 max/min override 使用了 `datapath_only = yes`，需要确认是否有意剥离 clock latency/skew。
- multicycle 的 `hold_cycles` 不等于项目默认策略，需要确认。
- `path_category = reset` 进入 20，需要确认 recovery/removal / RDC signoff 覆盖。
- max/min override 数值与 10 budget 候选差异很大。
- source SDC digest 与上次提取不一致。
- 临时 waiver 接近 `expiry_or_review_date`。

### 10.3 coverage report

20 脚本应输出 coverage report：

- 所有 harden-to-harden channel 的分类结果：10 / 20 / 30 / 04 / clock / needs_review / unclassified。
- 所有 no-port-timing channel 清单及处理状态。
- 所有提取到的 harden exception 清单及是否生成。
- 所有 active 20 rule 清单，按 scenario/stage/corner/exception_type 分组。
- 所有 10 与 20 overlap 或潜在冲突清单。
- 所有 03 与 20 overlap 清单，并区分 false path 冗余、max/min CDC 配套和潜在冲突。
- 所有 pending / needs_review / rejected candidate 及未生成原因。
- 所有 source SDC stale candidate。

## 11. 示例

### 11.1 不是 20：普通 timed data channel

集成关系：

```text
u_a/data_o -> u_b/data_i
```

`u_a` SDC：

```tcl
set_output_delay -max 1.5 -clock clk [get_ports data_o]
```

`u_b` SDC：

```tcl
set_input_delay -max 1.2 -clock clk [get_ports data_i]
```

这类路径优先进入 10 review。若 owner 确认它是 interconnect budget，可以生成 10 的 `set_max_delay`；不能因为它是 harden-to-harden 连接就放入 20。

### 11.2 也不是 20：只有缺约束

集成关系：

```text
u_a/status_o -> u_b/status_i
```

两端 SDC 都没有 port timing。

如果没有任何协议说明，则只能生成 candidate：

```text
source_type = missing_timing_candidate
timing_contract_status = no_port_timing
review_status = needs_review
recommended_action = ask_owner_for_contract_or_exception_basis
```

不生成 SDC。

### 11.3 可能是 20：静态配置路径 false path

集成关系：

```text
u_cfg/cfg_mode_o -> u_core/cfg_mode_i
```

架构依据：

```text
cfg_mode_o 只在 reset/boot 阶段改变，func run 阶段静态保持。
func scenario 下已通过 case/reset sequence 保证稳定。
```

review 后可在 `scenarios/func_exceptions.sdc` 生成：

```tcl
set_false_path \
  -from [get_pins u_cfg/cfg_mode_o] \
  -to   [get_pins u_core/cfg_mode_i]
```

如果该静态假设只在 func 成立，不能放 common 20。

### 11.4 可能是 20：协议 multicycle

集成关系：

```text
u_dma/cmd_o -> u_noc/cmd_i
```

协议依据：

```text
cmd_i 只在 valid/ready 握手完成后的第 3 个 cycle 被采样。
```

若该 path 为同 clock 或已确认同参照 clock，review 后可生成：

```tcl
set_multicycle_path 3 -setup \
  -from [get_pins u_dma/cmd_o] \
  -to   [get_pins u_noc/cmd_i]

set_multicycle_path 2 -hold \
  -from [get_pins u_dma/cmd_o] \
  -to   [get_pins u_noc/cmd_i]
```

setup/hold cycle 必须由协议或 STA owner 明确确认。

若 `u_dma` 与 `u_noc` 使用不同 clock，必须额外明确 `mcp_reference`、周期比、边沿关系和 hold 推导，不能直接套用上面的同 clock 示例。

### 11.5 可能是 20：handshake max delay override

集成关系：

```text
u_a/req_o -> u_b/req_i
```

如果该 path 不是普通 synchronous data path，而是异步握手控制信号，且协议要求在某个 timeout 内到达，可以使用 20 的 max delay override：

```tcl
set_max_delay 12.0 -datapath_only \
  -from [get_pins u_a/req_o] \
  -to   [get_pins u_b/req_i]
```

前提：

- `basis` 说明 timeout / protocol 来源。
- `clock_relation` 与 03/CDC review 一致；若两端 clock 异步，通常需要 03 async/exclusive 先去掉常规 setup/hold，再由此处的 `set_max_delay -datapath_only` 约束传播上限。
- 该 channel 没有 active 10 普通 budget 冲突。
- `stage/corner` 维度已确认。

## 12. 第一版脚本机制建议

第一版脚本建议偏保守，主要做候选归集和 approved 生成。

输入：

```text
info_all.xlsx
子 xlsx
harden/subsys SDC
01 clock_inventory.csv
10_harden_x_if.xlsx 或 10 channel inventory
03 clock group report / 人工 clock_relation 字段
20_harden_to_harden_exception.xlsx
```

流程：

1. 根据集成表单建立 harden-to-harden channel inventory。
2. 提取 harden SDC 中的 port timing，标记 `has_src_output_delay` / `has_dst_input_delay`。
3. 提取 harden SDC 中可映射到 boundary port 的 exception 命令，作为 `extracted_harden_exception` candidate。
4. 对没有普通 port timing、也没有 10 budget 的 channel，生成 `missing_timing_candidate`。
5. 合并 10 channel/budget 状态，标记可能冲突或应转 20 的 channel。
6. 合并 03 clock relation 信息：对 false path 标记可能冗余，对 CDC/handshake max/min override 标记是否有 async/exclusive 配套。
7. 同步 workbook：新增 candidate 用黄色标记，stale candidate 用红色/灰色标记。
8. 只对 `exception_rule` 中 `apply=yes + review_status=approved` 的行生成 SDC。
9. 输出 report 和 coverage。

第一版不建议自动把 candidate 提升为 approved rule。

## 13. 暂不处理

第一版暂不自动处理：

- 从 signal name 自动猜测 false path。
- 从缺少 input/output delay 自动推断 exception。
- 自动生成 `set_disable_timing`。
- 自动解析复杂 Tcl 变量/过程生成的 exception。
- 自动判断 CDC/RDC 正确性。
- 自动从 03 推断所有 path-level exception。
- 自动解决 10 与 20 冲突。

这些都必须通过表单和 reviewer 显式确认。
