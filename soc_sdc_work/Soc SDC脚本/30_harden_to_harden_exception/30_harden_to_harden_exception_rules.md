# 30_harden_to_harden_exception.sdc 规则草案

本 stage 遵守 [Shared Script Runtime Rules](../docs/shared_script_runtime_rules.md)。目标迁移后，candidate/form 写入 `30_middle/`，最终 SDC/report 写入 `30_result/`。

本文定义 `30_result/common/30_harden_to_harden_exception.sdc` 及 scenario overlay 的职责、分类方法、输入来源、表单字段和生成检查规则。

30 是高风险约束文件。它不负责普通接口 timing budget，也不负责补齐漏约束；它只表达 harden/subsys 之间确有架构依据、协议依据或 mode 依据的 path-level exception / override。

target 运行入口：

```bash
python3 30_extract_harden_to_harden_exception.py \
  --run-root <run_root> \
  --scenario <scenario> \
  [--stage <stage> --corner <corner>] \
  [--no-update-pending]
```

`--scenario` 始终必填。`--stage` / `--corner` 在生成数值型 view-specific override 时必填。

## 1. 目标

`30_harden_to_harden_exception.sdc` 用来表达 SoC 视角下 harden/subsys 之间的 path exception。

30 的判断依据是约束意图，不是 SDC 命令名字：

- 普通 harden/subsys interface timing budget 归 20。
- 改变默认 STA 分析语义的 path exception / override 归 30。
- top pad 外部 IO timing environment 归 04。
- clock relationship 归 03。
- 与 `fti_*` / `fto_*` boundary 相邻的 direct edge 先由 10 分类；若为 exception-only，再 `route_to_30`。

30 第一版支持的 SDC 命令建议限制在：

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

它不是自动生成 30 exception 的充分条件。

也就是说：

```text
no port timing != false path
no port timing != multicycle
no port timing != async path
```

一条 harden-to-harden interconnect 进入 30，需要同时满足：

```text
没有普通 20 timing budget 语义
+ 有明确 exception/override 语义
+ 有可审查依据
```

如果只发现“没有 port timing”，但没有协议、CDC、架构、mode 或 harden owner 说明，脚本只能生成 `needs_review` candidate，不能 emit 30 SDC。

### 2.2 先分类，再生成

30 不是逐条搬运 harden SDC exception。

脚本应先根据 00 `connection_inventory.csv` 或 10/20 direct-edge inventory 建立 harden-to-harden candidate，再把 harden SDC、10/20 normal timing 状态、03 clock relationship 和人工协议标签归并到同一个 candidate 上，最后由表单 review 决定是否生成。

推荐分类顺序：

```text
1. top pad related
   -> 04

2. clock creation / clock relationship
   -> 01 / 03

3. feedthrough-related direct edge 的普通 timing/disposition
   -> 10；exception-only 则由 10 route_to_30

4. 有普通 interface timing budget 语义
   -> 20

5. 有明确 path exception / override 语义
   -> 30

6. 无 timing contract 且无 exception 依据
   -> needs_review，不生成
```

### 2.3 30 不替代 10/20 normal timing

如果某个 direct edge/channel 已经在 10 或 20 中生成普通 interface budget，则 30 不能在同一 check 维度上覆盖它，除非表单明确说明 30 是为了覆盖某个特殊子路径，并且对应 10/20 budget 已经拆分或禁用。

20 和 30 的关系分为两层：

- port-level pending owner：一个 canonical port 只由一个 stage 最终消账。原始 harden SDC 已显示为 exception-only 的 endpoint 不由 20 消账，留给 30。
- path-level constraint owner：同一个已由 10/20 归类的 port 上可以存在更窄的 30 exception path。此时 30 只记录和生成 path exception，不重复删除 port，也不改写 10/20 的 port owner。

因此不要求 30 先于 20 生成 intent inventory。20 按已知 harden SDC evidence 和集成分类处理普通 timing；30 后续处理 exception。两者的最终一致性以 path/check 维度 overlap 检查为准，不以“30 是否也删除了 port”为准。

常见错误：

```tcl
set_max_delay 1.2 -datapath_only -from A -to B   ;# 10/20 normal budget
set_false_path                 -from A -to B   ;# 30 又切掉同一路径
```

这种组合会让 10/20 normal budget 失效或语义自相矛盾，应作为 error 阻断。

但不同 check 维度可以共存，例如 active normal max 与 30 min_delay_override 可以同时给同一路径定义上限和下限；这类组合必须有 `basis` 说明 min/hold floor 的来源。

### 2.4 30 不替代 03

如果两个 clock domain 在所有相关路径上都应被视为 asynchronous / exclusive，优先用 03 的 clock group 表达。

30 适用于更窄的 path-level 语义，例如：

- 同 clock 或 related clock 下的配置路径，不要求单周期收敛。
- 只对某个控制通道成立的 false path。
- 某个 handshake/status/config path 的协议级 multicycle。
- 某个 async crossing 中只需要切特定同步器前一级路径，而不是整个 clock domain。

03 asynchronous/logically_exclusive/physically_exclusive 与 30 exception 的关系必须按命令语义区分：

- `set_false_path` vs 03 asynchronous：通常冗余。若 03 已经切掉两端 clock 的常规 setup/hold，再对同一 broad endpoint pair 打 false path 一般没有额外价值，应 warning。
- `set_max_delay -datapath_only` vs 03 asynchronous：可以是互补关系。异步 handshake、gray code、CDC 数据稳定窗口等路径，常见做法是先用 03 `set_clock_groups -asynchronous` 去掉常规 setup/hold，再用 30 `set_max_delay -datapath_only` 约束数据路径传播上限或 skew。
- `set_min_delay -datapath_only` vs 03 asynchronous：也可能是 CDC/协议要求的一部分，但必须有明确 hold/skew/协议依据。

因此，30 脚本不能把所有“03 已声明 asynchronous/logically_exclusive/physically_exclusive + 30 path 约束”统一判为冗余或冲突。只有 `false_path` 这类切 timing 的命令与 03 asynchronous 高度重叠；`max/min_delay_override` 在有 CDC/协议依据时应允许。

同时要注意：单独的 `set_max_delay -datapath_only` 不会自动去掉常规 setup/hold 检查。异步路径若没有 03 asynchronous/logically_exclusive/physically_exclusive 或其它 clock relation 处理，只打 30 max delay 并不能表示“该路径已安全建模”。这类情况应 warning 或 error，要求补 03/CDC 依据。

CDC / 异步 handshake 的数据稳定窗口建议采用成对范式：

```tcl
set_max_delay <max_window> -datapath_only -from <src> -to <dst>
set_min_delay <min_window> -datapath_only -from <src> -to <dst>
```

其中 03 负责去掉跨异步 clock 的常规 setup/hold，30 的 max/min 只约束数据路径传播上限和下限。若只生成 max、不生成 min，必须在 `basis` 中说明为什么不需要下限/skew 窗口约束。

注意：03 asynchronous 与 30 max/min 是否能在同一 path 上同时生效，取决于目标 STA 工具和项目 flow 的 exception priority 处理。有些工具/flow 会把 `set_clock_groups -asynchronous` 等效为高优先级 false path，从而遮蔽后续 path-level max/min。采用该范式前，必须用目标工具验证 `report_timing` / exception report 中 max/min 仍实际生效；若被 clock group 遮蔽，应采用项目确认的等效写法，而不是假设两者天然叠加。

### 2.5 common 与 scenario 分层

common 30 只放所有 mode/scenario 都成立的 exception。

以下约束必须下沉到 scenario：

- scan / mbist / dft mode only。
- test bypass mode only。
- GPIO 方向依赖。
- PLL bypass / boot mode / low power mode only。
- 依赖 `set_case_analysis` 选择后的 mux 单腿路径。

如果 exception 只有在某个 `set_case_analysis` 成立后才有效，它应放在对应 scenario exception 文件，而不是 common 30。

### 2.6 数值型 exception 需要 view 维度

`set_false_path`、`set_multicycle_path` 通常不随 corner 变化。

但 30 中的 `set_max_delay` / `set_min_delay` override 是数值约束，可能随 stage/corner/view 变化。第一版表单保留 `stage` / `corner` 字段：

```text
30_result/common/30_harden_to_harden_exception.sdc
30_result/common/30_harden_to_harden_exception_<stage>_<corner>.sdc
30_result/scenarios/<scenario>_exceptions.sdc
30_result/scenarios/<scenario>_exceptions_<stage>_<corner>.sdc
```

不能把多个 corner 的 `set_max_delay` / `set_min_delay` override 平铺进同一个 SDC。

### 2.7 30 必须是 object-level exception

30 只表达具体 SoC object 之间的 path-level exception。第一版禁止 clock-level exception。

不允许在 30 中生成：

```tcl
set_false_path -from [get_clocks clk_a] -to [get_clocks clk_b]
set_max_delay  5.0 -from [get_clocks clk_a] -to [get_clocks clk_b]
```

这类 clock-to-clock 约束本质上是 clock relationship，应回到 03 clock group 或收窄到具体 pin/port object。30 的 `from_collection`、`to_collection`、`through_collection` 应优先使用 SoC 可见的 `get_pins` / `get_ports`；net 只作为经过 review 的 through 辅助锚点。

## 3. 输入来源

### 3.1 00 connection inventory

00 `connection_inventory.csv` 用于建立 SoC direct 连接关系：

- harden/subsys instance。
- input bit 来源。
- output bit 去向。
- fanout 关系。
- 端口是否连接 top pad、clock、feedthrough、fabric。
- 可选的 signal/protocol 标签，例如 `data`、`config`、`status`、`reset`、`test_mode`、`handshake`、`debug`。

30 必须基于 00 edge 表中的 SoC 真实连接关系生成，不能只根据某个 harden SDC 中的 port 名字孤立生成 exception。原始集成表单只作为 00 edge 的来源追溯，不作为 30 重新展开 bus/range 的机器输入。

30 必须按 `scenario_scope = common 或当前 --scenario` 过滤 00 edge。foreign-scenario edge 不得进入 candidate、rule、SDC 或销账。

30 继承 `00_harden_port_inventory` 的 canonical bit key。candidate/rule 的机器 endpoint 必须能解析到具体 bit endpoint：scalar 写 `port`，vector bit 写 `port[index]`。direct path 的 src/dst bit 配对必须来自 00 `connection_inventory.csv` 或 10/20 edge inventory。若 exception 覆盖 bus 的一部分 bit，必须展开到对应 bit candidate/rule；若确认为 whole-bus exception，也必须在 coverage/removed log 中列出被消账的每个 bit，不能只删除整 bus。

### 3.2 harden/subsys SDC

30 从 harden/subsys SoC integration SDC 中提取两类信息：

1. port timing contract 证据：

```tcl
set_input_delay
set_output_delay
```

这些信息帮助判断该 channel 是否应优先归 20。

2. port-level exception 证据：

```tcl
set_false_path
set_multicycle_path
set_max_delay
set_min_delay
```

只有当这些命令作用在 SoC 可见的 boundary port/port group，并且能映射到集成表单 channel 时，才可进入 30 candidate。

harden 内部 full signoff exception 不应直接提升到 SoC 30。如果命令引用 harden 内部 cell/pin，而 SoC top 视角不可见，脚本只能记录为 evidence，不生成 SoC 30。

#### 3.2.1 Harden SDC 缺失时

30 必须允许部分 harden SDC 为 `missing`，并继续从 00 connection inventory、10 feedthrough edge inventory、20 channel inventory 和已到位 SDC 建立其它 candidate。

- missing SDC 不能被解释为 `no_port_timing`、“无 exception”或 `not_applicable`；受影响 channel 的 `timing_contract_status` / `harden_clock_context_status` 应标记 `incomplete_missing_sdc`。
- 依赖 harden SDC 提取的 exception candidate/rule 保持 pending，不生成、不消账。
- 人工新增的 30 rule 若有完整协议/架构依据，且明确标记其判断不依赖缺失 harden SDC，可以按正常 approved 门槛生成。
- report/coverage 必须区分 `missing SDC, evidence unavailable` 和 `available SDC scanned, evidence not found`。

partial mode 下其它 available channel 继续生成；开启 `--require-complete-harden-sdc` 后 missing 才全局阻断。

提升 harden boundary exception 前，还必须确认 clock context 一致：

- harden SDC 中 exception 依据的 source/capture clock，在 SoC 01/03 视角下有等价映射。
- harden 内部 `create_clock` / `create_generated_clock` 提升到 SoC 后，clock name、master/source 关系或 generated clock 语义没有改变该 exception 的成立条件。
- 若 SoC 集成改变了 clock mux、PLL source、generated clock 关系或 clock group，该 harden exception 只能作为 evidence，不能直接生成。

`harden_clock_context_status` 为 `mismatch` 或 `unknown` 时，`extracted_harden_exception` 不得自动提升为 approved 30 rule。

### 3.3 10/20 normal timing inventory / budget 表

30 应读取或引用当前 scenario 的 10 feedthrough edge inventory 和 20 channel inventory / interface budget 结果：

- 判断该 direct edge/channel 是否已有普通 10/20 budget。
- 识别 10/20 中的 `route_to_30`、exception evidence 或 `clock_relation=asynchronous/logically_exclusive/physically_exclusive` 状态。
- 避免 10/20 normal budget 与 30 exception 在同一 assembled view 中冲突。

active normal budget 必须按 10/20 的实际生成状态判断，而不是只看 inventory 行是否存在。

第一版定义：

```text
active normal budget =
  owner_stage 属于 10 或 20
  与当前 scenario/stage/corner assembled view 匹配
  + apply = yes
  + review_status = approved
  + budget 类型属于普通 interface budget
  + emit_max = yes 或 emit_min = yes
  + 对应 converted_max / converted_min 非空并会实际生成 SDC
```

仅存在于 10/20 inventory、pending/rejected/route_to_30 行、或不 emit max/min 的记录，不应被当成 active normal budget。

10/20 normal budget 与 30 overlap 需要按 check 维度判断，不能一刀切：

```text
active normal max + 30 false_path(setup/both) -> error
active normal min + 30 false_path(hold/both)  -> error
active normal max + 30 max_delay_override     -> error 或显式裁决
active normal min + 30 min_delay_override     -> error 或显式裁决
active normal max + 30 min_delay_override     -> 可允许，但必须有 basis 说明 min/hold 来源
active normal min + 30 max_delay_override     -> 可允许，但必须有 basis 说明 max/setup 来源
```

也就是说，同类型或语义重叠才阻断；max 上限和 min 下限本身可以在同一路径上合法共存。

若 10 或 20 尚未生成 inventory/form，30 可以独立从 00 `connection_inventory.csv` 建立 candidate-only workbook/CSV，但不得生成正式 30 SDC，也不得销账。feedthrough-related candidate 还必须等待 10 `route_to_30` 结果。正式生成前，10/20 inventory 必须存在、scenario/digest 匹配，并完成 normal owner/overlap 检查。

### 3.4 03 clock relationship

30 应从 `03_middle/relation_map/<scenario>.csv` 参考当前 assembled view 的 clock relationship：

relation map 中的 clock name 必须来自同一 `01_middle/assembled/<scenario>/clock_inventory.csv`。30 不得将 common-only clock inventory 与 scenario relation map 混用；digest 或 scenario 不一致时必须阻断。

- asynchronous / logically_exclusive / physically_exclusive clock pair 默认不应再生成普通同步 max/min override。
- 如果 max/min override 是 CDC/handshake skew 或传播上限约束，并带 `-datapath_only` 与明确 CDC/协议依据，它可以和 03 asynchronous 配套存在。
- 如果 entire domain relationship 已由 03 表达，30 path-level false path 通常冗余。
- 如果 30 只作用于 domain 内的特定子路径，必须在 `basis` 中说明为什么不用 03。

relation map 只用于检查 30 命令是否与 clock-domain 语义一致，不用于自动生成 exception，也不用于判定 pending owner。例如：

- pair 已 asynchronous 时，再打 broad false path 通常冗余。
- pair 已 asynchronous 时，带协议/CDC 依据的 `set_max_delay -datapath_only` / `set_min_delay -datapath_only` 可能是合理配套。
- pair 仍 default synchronous 时，只生成 datapath-only max/min 不会自动关闭常规 setup/hold，需要 review clock relation 是否缺失。

当前 legacy 实现仍依赖表单 `clock_relation` 人工填入，尚未实现 relation-map CSV 自动注入。

若 relation-map meta 为 partial，且 rule 的 src/dst clock 因 missing harden SDC 不在当前 pair map 中，30 必须把 clock relation 视为 `unknown/incomplete`，不得将 pair 缺行解释为 default synchronous。依赖 CDC/async clock relation 的 rule 保持 pending，除非存在明确且不依赖缺失 SDC 的 approved 依据。

### 3.5 人工协议/架构信息

以下信息通常需要人工或架构表单提供：

- path 是否为 config/static/status。
- path 是否为 async handshake。
- path 是否为 reset/test/debug。
- multicycle 具体 setup/hold cycle。
- max/min override 的数值和推导依据。
- CDC/RDC/STA waiver 或 signoff 记录。
- owner/reviewer。

没有这些依据，不允许把候选 path 直接生成到 30。

## 4. 与其它 SDC 的边界

### 4.1 与 20_harden_x_if.sdc

20 表达普通 harden/subsys interface timing budget。

30 表达 path exception / override。

同一个 harden-to-harden channel 的 `set_max_delay` / `set_min_delay` 归属按语义判断：

```text
正常 boundary-to-boundary datapath budget -> 20
偏离默认 STA 语义的 exception/override -> 30
```

示例：

```text
u_a/data_o -> u_b/data_i
```

如果两端 SDC 给出 input/output delay，且 owner 声明它是 interconnect budget，则归 20。

如果这是一个 config bus，只有 boot/config 阶段更新，功能运行时静态保持，并且架构确认无需单周期 timing，则可能归 30。

如果只是没有任何 delay 约束，但也没有 config/static/async/multicycle 依据，则不能归 30，只能报 needs_review。

### 4.2 与 03_soc_clock_groups.sdc

03 是 clock relationship，30 是 path-level exception。

如果 A/B 两个 clock domain 整体异步，使用 03。

如果只有 A->B 的某几根控制线是 async handshake 或 false path，而同一对 clock 下其它数据线仍需正常 STA，使用 30。

### 4.3 与 04_soc_io_pads.sdc

连接 SoC top pad 的路径不进 30。

- pad 外部环境、IO delay、driving、load、transition 归 04。
- pad-related false path 若确实存在，也应先在 04 的 IO/pad 表单中 review，而不是进入 harden-to-harden 30。

### 4.4 与 10_feedthrough.sdc

10 处理与 feedthrough boundary 相邻的普通 timing/disposition；30 只接收 10 明确 `route_to_30` 的 exception-only direct edge。例如：

```text
u_a/data_o      -> u_ft/fti_data   # 一条 direct edge
u_ft/fto_data   -> u_b/data_i      # 另一条 direct edge
```

30 必须按 direct edge 分别建模，不得构造跨越 `[harden internal]` 的 `u_a/data_o -> u_b/data_i` synthetic path。`u_ft/fti_data -> u_ft/fto_data` 是 harden 内部路径，其 exception 由 harden owner 处理，SoC 30 不生成。

feedthrough-related rule 必须填写 bit-level `related_10_feedthrough_edge_id`，并满足：

- id 存在于当前 scenario 的 10 `feedthrough_edge_inventory.csv`。
- 对应 00 `connection_id`、src/dst endpoint 与 30 rule 完全一致。
- 10 行的 `channel_disposition = route_to_30`。
- vector/range 按 00 canonical bit edge 分别引用，不能用一个 id 覆盖多个 bit。

`through_collection` 仍可用于 SoC top 可见的 glue logic 或其它明确对象，但不得用它把 `fti` 和 `fto` 锚成一条穿越 harden 内部的 path。若 10 尚未分类该 direct edge，30 candidate 保持 `needs_review`，不得生成。

### 4.5 与 scenario pre-setup

如果某条 path 在某 scenario 下已经被 `set_case_analysis` 失活，通常不需要再对它打 30 exception。

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
- `max_delay_override`：该 path 需要一个 override max delay，不是普通 20 budget。
- `min_delay_override`：该 path 需要一个 override min delay，不是普通 20 budget。
- `max_min_delay_override`：max/min override 成对出现。
- `needs_review`：候选信息不足，不生成。
- `not_exception`：review 后确认不属于 30。

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

`data` 不是不能进 30，但普通 data path 进入 30 必须有更强依据，例如协议明确 multicycle 或 architectural waiver。

`unknown` 不允许生成。

`reset` 路径进入 30 必须特别谨慎。对 reset path 打 `set_false_path` 可能同时关闭 recovery/removal 检查，隐藏异步复位释放时序风险。因此：

- `path_category = reset` 且 `exception_type = false_path` 应标为 high risk。
- `basis` 必须说明 recovery/removal 如何由其它约束、复位同步器、RDC signoff 或 STA waiver 保证。
- 若只想切 setup 或只想切 hold，应使用 `check_type` 精确表达，并确认目标工具对 recovery/removal 的映射语义。不能默认认为 `-setup` 一定保留所有 removal/recovery 检查。
- 若没有 recovery/removal 处理依据，不允许生成。
- reset false path 的替代保证依据建议优先填在结构化字段中，例如 `cdc_rdc_ref` / `sta_waiver_ref`，并在 `basis` 中说明 recovery/removal、RDC signoff、复位同步器或 waiver 的覆盖方式。脚本会识别英文关键词（如 `recovery` / `removal` / `RDC` / `waiver` / `sync`）和常见中文说明（如“复位同步器”“恢复/移除”“同步器”），但正式 review 仍应以结构化 ref 为准。

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

- `both_sides_timed` / `src_timed_only` / `dst_timed_only`：存在普通 timing contract 证据，优先进入 20 review。
- `no_port_timing`：没有普通 timing contract 证据，只能触发 30 candidate review，不能直接生成。
- `clock_relative_only`：有 clock-relative block delay，但不能直接变成 30。默认应回到 20 做 interface budget / period-based budget review；若 reviewer 确认它不是普通 budget 且存在 exception 语义，再转 30。否则保持 `needs_review`。
- `interconnect_budget`：通常归 20，不归 30。

### 5.4 source_type

建议枚举：

```text
extracted_harden_exception
missing_timing_candidate
integration_tag
clock_relation_candidate
manual_entry
from_20_exception_path
```

含义：

- `extracted_harden_exception`：来自 harden SDC 中可映射到 boundary port 的 exception。
- `missing_timing_candidate`：来自“harden-to-harden channel 缺少普通 port timing”的候选。
- `integration_tag`：来自集成表单的 signal/protocol 标签。
- `clock_relation_candidate`：来自 03 clock relation 的提示。
- `manual_entry`：人工新增。
- `from_20_exception_path`：来自 20 中已明确标记为 `channel_type=exception_path` 的 channel，应进入 30 review。

### 5.5 datapath_only 策略

`datapath_only` 不是单纯的 tool option，而是 timing 语义的一部分。`tool_surface` 只负责确认目标工具是否支持该选项；是否应使用 `-datapath_only` 应由 `path_category`、`clock_relation` 和 exception 意图共同决定。

第一版策略：

```text
CDC / async handshake / async data stability window:
  exception_type = max_delay_override / min_delay_override / max_min_delay_override
  clock_relation = asynchronous / logically_exclusive / physically_exclusive
  path_category = handshake / cdc_sync / status / control / data
  -> 默认必须 datapath_only = yes

同 clock / related clock 的功能性 override:
  exception_type = max_delay_override / min_delay_override / max_min_delay_override
  clock_relation = synchronous / unknown
  -> 默认 datapath_only = no

其它情况:
  -> 必须由 basis 明确说明是否剥离 clock latency/skew
```

原因：

- CDC/异步 handshake 的 max/min 通常只想约束数据路径传播窗口，应该剥掉两端 clock network latency。
- 同 clock / related clock 的功能性 override 往往仍希望保留 clock skew/latency 影响，误加 `-datapath_only` 可能让约束失真。
- 若使用 `datapath_only = yes` 偏离上述默认策略，必须在 `basis` 中说明。
- 30 脚本生成时只有 `datapath_only = yes` 才会带 `-datapath_only`；字段为空按 `no` 处理。CDC/异步窗口类 max/min override 若需要该语义，必须显式填写 `yes`，不能依赖空值默认。

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
src_bit_index
src_endpoint
dst_instance
dst_module
dst_port
dst_bit_index
dst_endpoint
src_clock
dst_clock
clock_relation
has_src_output_delay
has_dst_input_delay
related_20_channel_id
related_20_status
related_10_feedthrough_edge_id
harden_clock_context_status
sdc_evidence_status
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

用于记录 review 后允许生成的 30 规则。

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
sdc_evidence_status
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
sdc_independent_basis
risk_level
expiry_or_review_date
note
```

字段含义：

- `apply`：是否参与生成。
- `review_status`：`pending` / `approved` / `rejected` / `needs_review`。
- `exception_type`：决定生成哪类 SDC 命令。
- `path_category`：记录路径语义，辅助检查。
- `related_20_channel_id`：若该 path 与 20 channel 对应，必须填入，便于检查冲突。
- `related_10_feedthrough_edge_id`：仅用于 feedthrough-related direct edge，必须填入当前 scenario 10 `feedthrough_edge_inventory.csv` 中对应的 bit-level id；一个 30 rule 不得用 id 列表拼接多条 direct edge。
- `exception_candidate.src_port` / `exception_candidate.dst_port` 使用 00 canonical bit key；`exception_rule.src_endpoint` / `exception_rule.dst_endpoint` 必须能回溯到同一组 canonical bit key。`src_bit_index` / `dst_bit_index` 便于 report 聚合，scalar 留空。
- `from_collection` / `to_collection` / `through_collection`：允许 reviewer 对 endpoint 做更细粒度裁剪。若为空，默认使用 `src_endpoint` / `dst_endpoint`。若 collection 使用 bus/range/wildcard，必须能展开回具体 canonical bit endpoint。
- `clock_relation`：记录该 path 两端 clock 在 03/review 中的 canonical 关系：`synchronous` / `asynchronous` / `logically_exclusive` / `physically_exclusive` / `unknown`。
- `timing_contract_status`：记录 harden port timing 证据状态。
- `harden_clock_context_status`：若规则来自 harden SDC exception，记录 harden 视角 clock 与 SoC 视角 clock 是否等价，例如 `matched` / `remapped_equivalent` / `mismatch` / `unknown`。
- `sdc_evidence_status`：记录相关 source/destination harden SDC 证据是 `complete` 还是 `incomplete_missing_sdc`。
- `check_type`：用于 `false_path` / `multicycle_path` 的检查粒度，建议枚举 `setup` / `hold` / `both`。缺省按 `both` 处理。
- `setup_cycles` / `hold_cycles`：用于 `set_multicycle_path`。
- `mcp_reference`：用于 `set_multicycle_path` 的 edge reference，建议枚举 `start` / `end` / `same_clock_default`。跨 clock multicycle 必须明确，不应依赖工具默认。
- `cross_clock_mcp_review`：跨 clock multicycle 的人工确认，例如 `approved` / `not_applicable` / `pending`。
- `datapath_only`：仅用于 max/min override。是否使用由 5.5 的方法学规则决定，`tool_surface` 只确认目标工具是否支持该选项。30 中该字段为空时脚本按 `no` 处理；需要 `-datapath_only` 时必须显式填写 `yes`。
- `case_condition`：若 exception 依赖 scenario case，应记录对应 mode/case 条件。
- `cdc_rdc_ref` / `sta_waiver_ref` / `protocol_ref`：外部依据引用。
- `basis`：必填，说明为什么这条 path 可以作为 exception。
- `sdc_independent_basis`：当 `sdc_evidence_status=incomplete_missing_sdc` 但人工 rule 仍要求生成时必填，说明该结论为什么不依赖缺失 SDC。
- `risk_level`：`low` / `medium` / `high`，辅助 review。
- `expiry_or_review_date`：临时 waiver 或 early-stage exception 的复审日期。

## 7. 输出文件和 assembled view

### 7.1 输出文件

每次 target 运行都必须输出：

```text
30_middle/30_harden_to_harden_exception.xlsx
30_middle/scenario/<scenario>/exception_candidates.csv
30_middle/scenario/<scenario>/removed_log/30_harden_to_harden_exception.removed
30_result/reports/harden_to_harden_exception_check_report_<scenario>.txt
```

`exception_candidates.csv` 一行对应一个 current-scenario bit-level candidate，至少记录 schema/scenario、00 `connection_id`、10/20 owner reference、src/dst canonical endpoint、candidate type、clock relation、harden SDC evidence/completeness、review/apply 状态和输入 digest。CSV 与 workbook candidate sheet 必须来自同一个 in-memory resolved view。

common view-independent exception：

```text
30_result/common/30_harden_to_harden_exception.sdc
```

common view-specific max/min override：

```text
30_result/common/30_harden_to_harden_exception_<stage>_<corner>.sdc
```

scenario view-independent exception：

```text
30_result/scenarios/<scenario>_exceptions.sdc
```

scenario view-specific max/min override：

```text
30_result/scenarios/<scenario>_exceptions_<stage>_<corner>.sdc
```

第一版如果没有数值型 view-specific override，可以只生成 view-independent 文件。

### 7.2 assembled view

30 的检查和生成按 assembled view 进行。assembled view 是当前 analysis view 中实际会被 source 的 30 约束集合：

```text
view-independent common 30
+ 当前 stage/corner 的 common 30 view-specific 行
+ 当前 scenario 的 30 overlay 行
+ 当前 scenario/stage/corner 的 30 view-specific overlay 行
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

如果同一路径同时命中 false path 和 multicycle，工具可能直接按 false path 处理，multicycle 被静默遮蔽；同理 max/min override 也可能遮蔽 multicycle。30 规则把这类 overlap 提前报错，是为了避免 reviewer 误以为所有 exception 都同时生效。

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
- 若同 path 同 check 维度已有 active 10/20 normal budget，必须先关闭/拆分对应 budget 或给出裁决依据。
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

30 中的 max/min delay 只用于 exception/override，不用于普通 channel budget。

生成示例：

```tcl
set_max_delay 12.0 -datapath_only \
  -from [get_pins u_a/handshake_req_o] \
  -to   [get_pins u_b/handshake_req_i]
```

规则：

- 若它表达普通 boundary-to-boundary budget，应改归 20。
- 若它表达非默认协议 budget、handshake timeout、config path override 等，才归 30。
- `basis` 必须说明 override 数值的来源。
- `stage` / `corner` 必须处理清楚，不能把多个 corner 的数值写入同一个 SDC。
- `datapath_only` 是否使用必须按 5.5 方法学策略审核；`tool_surface` 只确认目标工具支持情况。
- 对异步 CDC/handshake 路径，`set_max_delay -datapath_only` 通常应与 03 asynchronous/logically_exclusive/physically_exclusive 或明确 CDC clock relation 配套。只写 30 max delay 不会自动关闭常规 setup/hold。
- 对 `clock_relation = asynchronous/logically_exclusive/physically_exclusive` 且 `path_category = handshake/cdc_sync/status/control/data` 的 CDC/异步窗口约束，`datapath_only` 默认必须为 `yes`。
- 对同 clock / related clock 的功能性 override，`datapath_only` 默认应为 `no`；如果确实要剥掉 clock latency/skew，必须在 `basis` 中说明原因。
- CDC 数据稳定窗口优先使用 `max_min_delay_override` 成对生成 `set_max_delay -datapath_only` 与 `set_min_delay -datapath_only`。若只生成 max 或只生成 min，必须说明另一侧为何不适用。

### 8.3.1 CDC 数据稳定窗口范式

对异步 CDC 或异步 handshake 路径，推荐范式是：

1. 03 用 `set_clock_groups -asynchronous` 切掉常规 setup/hold。
2. 30 用 `set_max_delay -datapath_only` 约束传播上限。
3. 30 用 `set_min_delay -datapath_only` 约束最小传播下限/稳定窗口。

这类规则本质上是在表达数据路径的允许 skew 窗口，而不是普通同步 budget。通常应优先用 `max_min_delay_override` 成对建模；若只需要 max 或只需要 min，必须在 `basis` 中明确说明另一侧为何不适用。

采用该范式时还必须记录工具生效性依据：确认 03 的 asynchronous clock group 没有遮蔽 30 的 path-level max/min，或者记录项目 flow 使用的等效约束策略。

## 9. 生成门槛

一条 30 rule 只有同时满足以下条件，才允许生成：

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
不是 harden 内部 `fti -> fto` path
若为 feedthrough-related direct edge，related_10_feedthrough_edge_id 有效且 10 disposition = route_to_30
不是普通 10/20 interface budget
若 related_20_channel_id 存在，必须确认 20 不会生成冲突 budget
若 related_10_feedthrough_edge_id 存在，必须确认 10 disposition = route_to_30 且不会生成 active budget
若 exception_type = multicycle_path，cycle 字段与 check_type 匹配
若 multicycle_path 跨 clock，mcp_reference 与 cross_clock_mcp_review 完整
若 exception_type = max/min override，对应 value 完整且 view 维度清楚
若 exception_type = max_min_delay_override，max/min value 均完整
若为 CDC/异步窗口约束，datapath_only 策略与 max/min 成对策略已确认
若依赖 mode/case，scenario 与 case_condition 明确
```

`pending` / `needs_review` / `rejected` 行不生成。

30 生成 approved path exception 后的 pending 处理：

target pending/log 固定为：

```text
00_middle/scenario/<scenario>/pending/
30_middle/scenario/<scenario>/removed_log/30_harden_to_harden_exception.removed
```

- endpoint 仍在 pending，且它的所有已知 SoC 约束意图都属于 exception-only：由 30 删除并记录 port owner。
- endpoint 已被 01/04/10/20 等早期 stage 合法消账：30 仍可生成更窄 path exception，但不新增第二份 port removal record；report 记录 previous port owner 和当前 path exception id。
- endpoint 不在 pending 且无任何 previous owner 记录：error，防止状态丢失。

target 模式未使用 `--no-update-pending` 时，pending 缺失必须阻断。`--no-update-pending` 只用于 candidate/diagnostic 运行，必须写入 report，且不得宣称 accounting closure 完成。

## 10. 检查规则

### 10.1 error

以下情况应阻断生成：

- `apply = yes` 但 `review_status != approved`。
- `exception_type` 为空或不在支持列表。
- `basis` 为空。
- `owner` 为空。
- `path_category = unknown` 却要求生成。
- 仅以 `no_port_timing` / `missing_timing_candidate` 作为依据生成 exception。
- 仅因 harden SDC 缺失而把 channel 当作 `no_port_timing`、无 exception 或 `not_applicable`。
- rule 依赖缺失 harden SDC 中的 timing/exception/clock-context 证据，却要求 `apply=yes`，且没有明确的 SDC-independent protocol/architecture basis。
- endpoint 无法解析到 SoC 可见对象。
- endpoint 无法映射到 00 canonical bit key，或用整 bus/range 直接消账而未展开对应 bit。
- partial-bit exception 的 endpoint/rule 未列出具体 bit，或 whole-bus exception 未在 removed log 中逐 bit 记录。
- `from_collection` / `to_collection` / `through_collection` 直接引用 `[get_clocks ...]`，即 clock-level exception 进入 30。
- 目标 path 是 top pad related，却进入 30。
- 目标 path 是 clock creation / clock relationship，却进入 30。
- harden 内部 `fti -> fto` path 进入 SoC 30，或 rule 跨该内部路径拼接两条外部 direct edge。
- feedthrough-related direct edge 缺少 bit-level `related_10_feedthrough_edge_id`、所填 id 不存在于当前 scenario 10 inventory、id 对应的 `connection_id`/endpoint 与 rule 不一致，或 10 disposition 不是 `route_to_30`。
- `through_collection` 被用来锚定/穿越同一 harden 的 `fti` 与 `fto`，从而把内部段纳入 SoC exception。
- 同一 assembled view 中，同一 path 同时存在 active 10/20 normal budget 和 30 exception，且二者 check 维度重叠，例如 normal max 与 30 false_path(setup/both)、normal max 与 30 max_delay_override、normal min 与 30 min_delay_override，且无显式拆分、禁用 normal budget 或裁决依据。
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
- common 30 中出现明显 mode-specific case，例如 scan/test/mbist/gpio direction，且未下沉 scenario。
- source harden SDC exception 引用 SoC 不可见内部 object，却要求原样生成。
- `tool_surface` 包含 DC/综合，但目标工具对对应 exception 命令或 `-datapath_only` 选项的支持未确认。

### 10.2 warning

以下情况应 warning，要求 reviewer 关注：

- harden-to-harden channel 没有 port timing，也没有 10/20 normal budget/disposition，也没有 30 decision。
- harden SDC 提取到 exception，但无法映射到集成表单 channel。
- harden SDC 提取到 port-level exception，但同 port 又存在普通 input/output delay。
- exception 覆盖 bus 的一部分 bit，需确认是否有意；确认后仍必须按 canonical bit endpoint 生成和消账。
- endpoint 使用 wildcard/pattern，覆盖范围可能过宽。
- exception 只指定单边 endpoint，例如只有 `-from` 或只有 `-to`，覆盖范围可能过宽，需 reviewer 显式确认是否有意。
- `through_collection` 使用 `get_nets` 或 net pattern，跨综合/PnR stage 需复核命中对象。
- common 30 使用了看起来像 test/reset/debug/mode 的 signal，需要确认是否 mode-independent。
- 03 已经声明两端 clock asynchronous/logically_exclusive/physically_exclusive，30 又对同 broad endpoint pair 打 false path，可能冗余。
- 03 已经声明两端 clock asynchronous/logically_exclusive/physically_exclusive，30 又生成 `set_max_delay -datapath_only` / `set_min_delay -datapath_only`：这是可能合理的 CDC/handshake skew 约束，不应按冗余处理，但需要 `basis` / CDC 依据完整。
- 03 未声明 asynchronous/logically_exclusive/physically_exclusive，但 30 basis 声称 async/CDC，或 30 使用 CDC max/min override，需要确认 03 是否也要更新；否则常规 setup/hold 仍可能存在。
- CDC/异步窗口只生成 `max_delay_override` 或只生成 `min_delay_override`，未采用 `max_min_delay_override` 成对约束，需要确认另一侧窗口为何不适用。
- active 10/20 normal max 与 30 min_delay_override、或 active normal min 与 30 max_delay_override 共存；这是可能合法的上下界组合，但需要 `basis` 说明补充约束来源。
- 同 clock / related clock 的功能性 max/min override 使用了 `datapath_only = yes`，需要确认是否有意剥离 clock latency/skew。
- multicycle 的 `hold_cycles` 不等于项目默认策略，需要确认。
- `path_category = reset` 进入 30，需要确认 recovery/removal / RDC signoff 覆盖。
- max/min override 数值与 10/20 normal budget 候选差异很大。
- source SDC digest 与上次提取不一致。
- 临时 waiver 接近 `expiry_or_review_date`。

### 10.3 coverage report

30 脚本应输出 coverage report：

- 所有 harden-to-harden channel 的分类结果：10 / 20 / 30 / 04 / clock / needs_review / unclassified。
- 所有 no-port-timing channel 清单及处理状态。
- 所有提取到的 harden exception 清单及是否生成。
- 所有 active 30 rule 清单，按 scenario/stage/corner/exception_type 分组。
- 所有 10/20 normal budget 与 30 overlap 或潜在冲突清单。
- 所有 03 与 30 overlap 清单，并区分 false path 冗余、max/min CDC 配套和潜在冲突。
- 所有 pending / needs_review / rejected candidate 及未生成原因。
- 所有 source SDC stale candidate。

## 11. 示例

### 11.1 不是 30：普通 timed data channel

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

这类路径优先进入 20 review。若 owner 确认它是 interconnect budget，可以生成 20 的 `set_max_delay`；不能因为它是 harden-to-harden 连接就放入 30。

### 11.2 也不是 30：只有缺约束

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

### 11.3 可能是 30：静态配置路径 false path

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

如果该静态假设只在 func 成立，不能放 common 30。

### 11.4 可能是 30：协议 multicycle

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

### 11.5 可能是 30：handshake max delay override

集成关系：

```text
u_a/req_o -> u_b/req_i
```

如果该 path 不是普通 synchronous data path，而是异步握手控制信号，且协议要求在某个 timeout 内到达，可以使用 30 的 max delay override：

```tcl
set_max_delay 12.0 -datapath_only \
  -from [get_pins u_a/req_o] \
  -to   [get_pins u_b/req_i]
```

前提：

- `basis` 说明 timeout / protocol 来源。
- `clock_relation` 与 03/CDC review 一致；若两端 clock 异步，通常需要 03 asynchronous/logically_exclusive/physically_exclusive 先去掉常规 setup/hold，再由此处的 `set_max_delay -datapath_only` 约束传播上限。
- 该 channel 没有 active 10/20 normal budget 冲突。
- `stage/corner` 维度已确认。

## 12. 第一版脚本机制建议

第一版脚本建议偏保守，主要做候选归集和 approved 生成。

输入：

```text
00_middle/connection_inventory.csv
00_middle/scenario/<scenario>/harden_sdc_manifest.csv
00_middle/scenario/<scenario>/pending/                    # unless --no-update-pending
01_middle/assembled/<scenario>/clock_inventory.csv
01_middle/assembled/<scenario>/clock_inventory.meta
10_middle/scenario/<scenario>/feedthrough_edge_inventory.csv
20_middle/scenario/<scenario>/channel_inventory.csv
03_middle/relation_map/<scenario>.csv
03_middle/relation_map/<scenario>.meta
30_middle/30_harden_to_harden_exception.xlsx
```

上述 `*_middle` 路径是 target runtime 契约。legacy cwd 可继续使用 `00_harden_port_inventory/connection_inventory.csv`、cwd 01 inventory、20 workbook 和人工 `clock_relation`，但不得与 target pending/middle 混用。

流程：

1. 根据 00 `connection_inventory.csv` 建立 harden-to-harden candidate/channel inventory。
2. 提取 harden SDC 中的 port timing，标记 `has_src_output_delay` / `has_dst_input_delay`。
3. 提取 harden SDC 中可映射到 boundary port 的 exception 命令，作为 `extracted_harden_exception` candidate。
4. 对没有普通 port timing、也没有 10/20 normal budget 的 channel，生成 `missing_timing_candidate`。
5. 合并 10 feedthrough edge 与 20 channel/budget 状态，标记可能冲突或已 `route_to_30` 的 channel。
6. 合并 03 clock relation 信息：对 false path 标记可能冗余，对 CDC/handshake max/min override 标记是否有 asynchronous/logically_exclusive/physically_exclusive 配套。
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
- 自动解决 10/20 normal budget 与 30 冲突。

这些都必须通过表单和 reviewer 显式确认。
