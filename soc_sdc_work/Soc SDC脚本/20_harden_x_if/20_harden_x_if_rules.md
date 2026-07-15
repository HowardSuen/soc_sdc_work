# 20_harden_x_if.sdc 规则说明

本 stage 遵守 [Shared Script Runtime Rules](../docs/shared_script_runtime_rules.md)。target runtime 中 channel inventory/form 写入 `20_middle/`，最终 SDC/report 写入 `20_result/`；未指定 `--run-root` 时只进入明确的 legacy cwd 兼容布局，两套状态不得混用。

本文定义 20 的审计职责、可选 budget 输出职责、输入来源、channel 归并方法、表单字段和检查规则。

target 运行入口：

```bash
python3 20_extract_harden_x_if.py \
  --run-root <run_root> \
  --scenario <scenario> \
  --mode audit_only|budget_output \
  [--stage <stage> --corner <corner>] \
  [--no-update-pending]
```

`--scenario` 始终必填。`--stage` / `--corner` 在生成 view-specific budget 时必填。target 默认读取当前 scenario manifest/pending 和 10 inventory；不得与 legacy cwd 状态混用。

## 1. 目标

20 用来管理 SoC 视角下 harden/subsys 普通 interface channel 的归属、销账，以及少量显式 opt-in timing budget。

当前项目的默认方法学是：**普通、非 feedthrough 的 direct functional harden/subsys interface 在 PR floorplan 中物理相邻，SoC 层级不再叠加 channel-specific delay budget**。20 仍默认执行，但只用于建立 channel inventory、排除 clock/pad/feedthrough/exception、记录 harden SDC evidence、生成 coverage report，并对普通 functional channel 完成 `no_soc_budget_required` 销账。默认运行产生的 20 SDC 只是零命令占位产物，不进入实际 SoC SDC source list。

20 的判断依据是约束意图，不是 SDC 命令名字：

- 普通 harden/subsys interface budget 归 20。
- 改变默认 STA 分析语义的 exception 归 30。
- 与 `fti_*` / `fto_*` boundary 相邻的 SoC-visible direct edge 归 10。
- SoC top pad 的外部 IO 环境归 04。

默认模式下，20 SDC 必须只有文件头和“no emitted constraints”说明。只有项目显式切换到 budget 输出模式后，20 才允许生成 reviewed `set_max_delay` / `set_min_delay`；即使在该模式下，也不直接生成 instance pin 上的 `set_input_delay` / `set_output_delay`。

需要特别注意：20 生成的 `set_max_delay` / `set_min_delay` 是 SoC boundary-to-boundary channel datapath budget，约束的是两个 SoC 级 endpoint 之间的 datapath，例如 top-level interconnect / glue logic / wrapper 组合逻辑。它不是 block 级 clock-relative `set_input_delay` / `set_output_delay` 的语义等价替换。

```tcl
set_max_delay <value> -datapath_only -from <src_endpoint> -to <dst_endpoint>
set_min_delay <value> -datapath_only -from <src_endpoint> -to <dst_endpoint>
```

`-datapath_only` 的使用需要按工具确认。第一版规则以 STA/PT 类 signoff 语义为主；若用于 DC/综合，应在 flow 中明确该工具对 `-datapath_only` 的支持和含义，或者生成 synthesis 专用版本。

### 1.1 运行模式

20 统一提供两个 stage-level 运行模式：

```text
audit_only
budget_output
```

脚本接口使用：

```text
--mode audit_only|budget_output
```

未指定时必须默认 `audit_only`。运行模式必须写入 stdout、workbook/report metadata 和 SDC header，不能根据 workbook 中是否碰巧存在 `emit_max = yes` 静默切换。

`audit_only` 是当前项目的正常运行模式：

- 执行 channel inventory、ownership 分类、harden SDC evidence 提取、coverage、终态检查和 pending 销账。
- 普通 direct functional channel 按项目 PR 相邻策略形成 `no_soc_budget_required` 终态。
- `20_harden_x_if.sdc` 必须为零 timing-command 文件，且不加入实际 SoC SDC assembled source list。
- 任一行出现 `channel_disposition = emit_budget`、`budget_required = yes`、`emit_max = yes` 或 `emit_min = yes` 时必须报错并阻断成功结束，不能生成后再依赖下游“不要 source”。

`budget_output` 只在项目明确要求使用 20 channel budget 时显式启用：

- 只有该模式允许 approved `emit_budget` 行生成 `set_max_delay` / `set_min_delay`。
- 该模式的输出必须纳入对应 SoC analysis view 的 source list；“生成但不消费”属于 flow 配置错误。
- 从 `audit_only` 切换到 `budget_output` 必须是项目级显式决定，不能由单个提取到的 block input/output delay 自动触发。

PR 相邻是项目方法学输入，不是 20 根据 netlist、DEF 或 timing report 推断出的结论。`no_soc_budget_required` 只表示不增加 20 channel-specific budget，不表示路径无约束，也不替代正常 clock-based setup/hold STA 或 30 的 exception 分析。

### 1.2 默认 audit_only 执行顺序

默认运行必须按以下顺序完成：

1. 固定 `mode = audit_only`、`sdc_consumption = disabled` 和 policy ID。
2. 读取 `00_middle/connection_inventory.csv`、当前 scenario manifest、01 assembled clock inventory 和 10 feedthrough edge inventory。
3. 建立普通 direct channel inventory，并排除 pad、clock、feedthrough、NC/tie-off 和 unresolved edge。
4. 从 available harden SDC 提取 input/output delay 与已知 exception evidence；missing SDC 记录 incomplete，不做否定推断。
5. 已知 exception candidate 记录 `route_to_30`；普通 direct channel 按 PR 相邻 policy 记录 `no_soc_budget_required`；其它不完整对象保持 `pending`。
6. 校验不存在任何 emit intent，生成 timing-command 数量为 0 的占位 SDC。
7. 生成 workbook、channel inventory、coverage/check report，并仅对 approved terminal disposition 更新 pending/removed log。
8. 报告中分别给出 port-level budget policy closure 和 path-level exception evidence completeness，二者不得混为同一覆盖率。

## 2. 核心原则

### 2.1 按 interface channel 归并

20 不是逐条 SDC 命令转换，而是按 interface channel 归并后完成分类、审计和销账；只有 `budget_output` 才进一步生成 timing command。

一个 channel 表示 SoC 内部一条明确的连接关系：

```text
src instance/output canonical bit endpoint -> dst instance/input canonical bit endpoint
```

例如：

```text
u_harden_a/data_o -> u_harden_b/data_i
u_harden_a/ctrl_o[7] -> u_harden_b/ctrl_i[3]
```

在 `budget_output` 模式下，最终只生成一组 reviewed budget：

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

脚本不应只根据单个 harden SDC 中的 `get_ports` 目标端口孤立生成约束；必须结合 00 `connection_inventory.csv` 确认真实连接端点。若缺少对应 `connection_id`，该 channel 只能保持 `pending`，不能自行从原始 range 重建。

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

因此 20 必须先为每条 channel 明确 `channel_disposition`，再对确实需要生成数值约束的 channel 明确 `budget_model`。

### 2.4 channel disposition 与 budget_model

#### 2.4.1 channel_disposition

20 只处理普通 functional interface 的 timing contract / budget 分类和 port-level 消账。非 clock、非 pad、非 feedthrough、非 exception 的 direct channel 默认不需要额外生成 SDC，但必须在 20 中形成明确终态。harden port 原始 SDC 中的 false path、multicycle、exception max/min 或其它 exception/override 语义归 30；20 只记录转交证据，不生成、不消账该 exception-only endpoint。

第一版 `channel_disposition` 统一使用：

```text
emit_budget
no_soc_budget_required
route_to_30
not_applicable
pending
```

含义：

- `emit_budget`：该 channel 需要显式 `set_max_delay` / `set_min_delay`，只允许在 `budget_output` 模式继续按 `budget_model` 和生成门槛处理；在 `audit_only` 模式出现该状态属于配置错误。
- `no_soc_budget_required`：该 direct functional channel 命中当前项目“非 feedthrough harden/subsys interface 在 PR 中物理相邻，不增加 SoC channel-specific delay”的默认策略。20 不 emit SDC，但允许按 channel/bit 消账。该状态只表达本 SoC SDC 生成方法学的 budget 决策，不宣称路径已经通过 STA 验证。
- `route_to_30`：该 path 实际属于 exception/override，20 不生成、不消账，转 30 完成。
- 若 20 已从当前 harden SDC 识别到明确 exception evidence，自动 route 必须记录为 `apply=yes + review_status=approved` 的正式 owner decision；它仍不生成 20 timing command，也不由 20 消账。
- `not_applicable`：该 channel 经 review 确认不适用 20/30 timing constraint，并有明确依据；允许由 20 消账，不应作为跳过分析的快捷方式。
- `pending`：信息或 review 未完成，不生成、不消账。

20 不需要预先读取 30 workbook/intent 才能运行。归属裁决以当前输入中已知的 harden SDC evidence、SoC 集成表单分类和 20 review 结果为准：

- 已识别为 exception-only 的 channel 必须 `route_to_30`，20 不消账。
- `audit_only` 模式下，普通 timing channel 默认形成 `no_soc_budget_required`；`budget_output` 模式下才允许形成 `emit_budget`。
- `not_applicable` 只用于确实不适用 20/30 的特殊 channel，不得替代项目默认的 `no_soc_budget_required`。
- 后续在 30 中对已有普通 timing 归属的 port 添加更窄 path-level exception 时，30 可生成 exception，但不重复抢占或改写该 port 的 pending owner；20/30 只检查同一 path/check 维度是否冲突。

`no_soc_budget_required` 必须同时满足：

- `apply = yes`、`review_status = approved`，且 `disposition_basis` 非空。
- channel 来自 SoC 集成表单/00 connection inventory 的明确 direct functional edge，不是 pad、clock、feedthrough、NC/tie-off 或 unresolved connection。
- available 的 harden DC output SDC 中没有把该 channel 识别为需要立即转 30 的 false path、multicycle、exception max/min、async/handshake 或其它 exception candidate。
- `audit_only` 的 PR 相邻 no-budget 决策不依赖 block SDC 中是否存在 input/output delay。任一端 SDC 为 `missing` 时，脚本仍必须记录 `evidence_status = incomplete_missing_sdc`，不能声称“未发现 exception”；但可以使用项目级 approved `sdc_independent_basis = project_pr_adjacent_policy_independent_of_block_sdc_v1` 完成 port-level no-budget 销账。后续 SDC 到位后仍须由 30 独立完成 path-level exception 发现和处理。
- `budget_output` 模式下，任一 required harden SDC 为 `missing` 时默认保持 `pending`；只有表单给出其它 approved `sdc_independent_basis` 和独立预算依据时才可例外生成。
- `budget_required = no`，`emit_max = no`，`emit_min = no`。
- `disposition_basis` 引用当前项目批准的默认策略 `project_default_pr_adjacent_no_harden_if_delay_v1`。脚本可以按该项目策略自动填入 approved 终态，不要求逐 channel 人工证明 STA coverage。

`audit_only` 模式下，无论提取到多少 input/output delay evidence，`20_harden_x_if.sdc` 都必须只包含文件头和“no emitted constraints”说明；`channel_inventory`、coverage report 和 removed log 仍必须生成。

#### 2.4.2 budget_model

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

### 2.5 budget_output 的 min budget 必须 review 后 emit

`set_input_delay -min` 和 `set_output_delay -min` 在 block 级 SDC 中经常承载 hold/sign convention。尤其 `set_output_delay -min` 可能是负值，不能无脑转换为 SoC top 的 `set_min_delay`。

第一版规则：

- 脚本可以提取原始 min 值并给出候选。
- 只有在表单中 `emit_min = yes` 且 `review_status = approved` 时，才生成 `set_min_delay`。
- 如果两端 min 都已由 reviewer 归一为同一语义的 channel minimum datapath delay，则更紧规则为：

```text
converted_min = max(normalized_output_min, normalized_input_min)
```

## 3. 输入来源

### 3.0 外部原始输入边界

10~30 的外部原始输入只有：

- 各下级 harden/subsys 的 DC output SDC。
- SoC 集成表单。

00 `connection_inventory.csv`、01 clock inventory、10 feedthrough edge inventory 等属于本流程从上述原始输入生成的内部中间产物，不是额外交付输入。20 不读取 harden `.lib/.db`、netlist、STA database 或 `report_timing/check_timing` 结果，也不以 STA coverage 作为默认销账前提。

### 3.1 00 connection inventory

target 固定读取：

```text
00_middle/connection_inventory.csv
00_middle/scenario/<scenario>/harden_sdc_manifest.csv
00_middle/scenario/<scenario>/pending/                    # unless --no-update-pending
10_middle/scenario/<scenario>/feedthrough_edge_inventory.csv
```

20 用 00 `connection_inventory.csv` 建立 SoC 连接关系，包括：

- SoC 下有多少个 harden/subsys。
- 每个 harden/subsys 的 instance name。
- 每个 input bit 来源于哪个 instance/output bit 或 SoC top pad bit。
- 每个 output bit 去向哪些 instance/input bit 或 SoC top pad bit。
- 一个 harden 可能被例化多次，所有规则按 instance 生效。
- bus/range 连接的 bit-to-bit 展开结果；20 不在本阶段重新猜测 bit order。

20 必须先按 `scenario_scope = common 或当前 --scenario` 过滤 00 edge，再建立 channel inventory。foreign-scenario edge 不得进入 20 inventory、SDC 或销账。原始集成表单只作为 00 source trace，不是 20 direct channel 的机器真源。

### 3.2 harden/subsys DC output SDC

20 主要提取 harden/subsys DC output SDC 中的非 pad interface delay：

```tcl
set_input_delay  ...
set_output_delay ...
```

这些命令只作为 evidence/candidate 记录，不直接原样搬到 SoC top，也不因出现 input/output delay 就自动要求生成 20 budget。在默认 `audit_only` 模式下，普通 direct functional channel 仍归 `no_soc_budget_required`；项目只有先显式切换为 `budget_output`，才允许把某条 channel 标为 `budget_required = yes` 并进入 budget review。

harden SDC 可部分到位。20 必须把 source/destination 两端的 availability 带入 `channel_inventory` / `interface_budget`，例如 `src_sdc_status` / `dst_sdc_status`。available 一端的 delay/exception evidence 正常提取；missing 一端不产生“没有 delay/exception”结论。

受 missing SDC 影响的 channel 必须先记录：

```text
evidence_status = incomplete_missing_sdc
emit_max = no
emit_min = no
```

之后按运行模式处理：

- `audit_only`：若 channel 是 00/10 已确认的普通、非 feedthrough direct functional edge，可按项目 PR 相邻 policy 自动填写 `sdc_independent_basis = project_pr_adjacent_policy_independent_of_block_sdc_v1`，形成 `no_soc_budget_required` 并完成 port-level 销账；report 必须继续显示 exception evidence 不完整。
- `budget_output`：默认 `channel_disposition = pending`、`pending removal = no`。只有人工给出独立架构 budget 或其它明确 `sdc_independent_basis`，且满足正常 approved 门槛时，才能不等待缺失 SDC 而生成/销账。

其它 available harden/channel 继续处理。任何模式都不得把 missing SDC 解释成“没有 delay”或“没有 exception”。

### 3.3 01 clock inventory

20 在 target runtime 中引用 `01_middle/assembled/<scenario>/clock_inventory.csv` 做辅助分类检查：

- 判断端口是否是 clock port。
- 检查原始 delay 引用的 clock 是否能映射到 SoC clock。
- 检查 channel 两端是否属于预期 clock domain。

20 不创建 clock object。

当前实现已固定读取当前 scenario 的 assembled clock CSV/meta，并校验 scenario、CSV digest、active clock-set digest 和最终 clock SDC digest。target 中缺失、损坏或 stale 的 assembled clock interface 会阻断 20。

### 3.4 02 / 03 内部约束信息

默认 `audit_only` / `no_soc_budget_required` 分支不依赖 02/03。只有后续显式切换到 `budget_output` 并 opt-in `emit_budget` 时，budget 推导才可能依赖 clock period、uncertainty、latency、stage/corner 策略；这些信息归 02 管理，20 不应私自 hard-code。

20 只在计划生成 `emit_budget` 时参考 03 clock relationship。若 channel 两端 clock 在当前 assembled view 中被声明为 `asynchronous` / `logically_exclusive` / `physically_exclusive`，则不能默认生成普通同步 interface budget；必须取消该 budget、改为有明确依据的异步/CDC 建模，或由 reviewer 提供 `relationship_override_basis`。

target runtime 中，20 必须从 `03_middle/relation_map/<scenario>.csv` 和配套 meta 读取该关系，不得各自解析 03 workbook。当前实现仅在 `budget_output` 中读取并校验该接口；`audit_only` 不依赖 03，也不因 stale/缺失 03 产物阻断 no-budget 审计。

03 relation map 只是 budget 语义检查输入：它不判定 port owner，也不因 clock pair 是 async/exclusive 就自动把 channel 改为 `route_to_30`。是否属于 30 仍需要 harden exception evidence 或明确的协议/架构依据。

若 03 relation-map meta 为 partial，且 channel 的 src/dst clock 因 missing harden SDC 不在当前 clock universe/pair map 中，20 必须把 `clock_relation` 视为 `unknown/incomplete`，不得因 pair 缺行就按 default synchronous 生成 `emit_budget`。

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

20 只处理不涉及 feedthrough boundary 的普通 functional direct edge。以下 edge 归 10：

```text
u_src/out       -> u_ft/fti_xxx
u_ft/fto_xxx    -> u_dst/in
u_ft1/fto_xxx   -> u_ft2/fti_yyy
```

20 读取当前 scenario 的 `10_middle/scenario/<scenario>/feedthrough_edge_inventory.csv` 只做 ownership 排除：

- 任何已由 10 inventory 引用的 00 `connection_id` 都不得进入 20 channel inventory 或 20 pending removal。
- 20 不读取 `related_pair_id` / `related_chain_id` 推导新 endpoint。
- 20 不把进入 `fti` 和离开 `fto` 的两条 direct edge 拼成 end-to-end channel。
- harden 内部 `fti -> fto` 不是 SoC direct edge，不属于 10 或 20 的 SDC 生成对象。

10 inventory 缺失时，20 仍可直接根据 00 endpoint 命名识别 feedthrough-adjacent candidate，但只能阻断并保持 `pending`，不能把它回退为普通 20 channel。

### 4.4 与 module/block signoff SDC

block 自身 signoff 时，`set_input_delay` / `set_output_delay` 仍然可以作用于 block top port。

SoC top 使用 20 时，不直接把这些命令改成：

```tcl
set_input_delay  ... [get_pins u_harden/in]
set_output_delay ... [get_pins u_harden/out]
```

因为在 SoC top DC/STA 视角下，instance pin 上的 input/output delay 语义不如 boundary `set_max_delay` / `set_min_delay` 清楚。

### 4.5 与常规时钟 STA

当前 01~30 流程不读取 SoC STA netlist、DEF、`.lib/.db` 或 timing report，因此 20 不负责测量 physical distance，也不负责证明普通 path 是否被 STA 覆盖。项目方法学在 flow 外部批准“普通、非 feedthrough direct functional harden/subsys interface 在 PR 中物理相邻”，据此规定默认不叠加 `set_max_delay -datapath_only`。20 在 `audit_only` 模式只记录 `no_soc_budget_required` 并完成销账；正常 synchronous path 仍由常规 clock-based STA 分析。

后续若出现以下显式需求，必须先把 stage 切换到 `budget_output`，再把特定 channel 从默认终态改为 `emit_budget`：

- SoC 架构明确要求对两个 boundary pin 之间的 interconnect/glue logic 给出显式 budget。
- harden owner 或 SoC integration owner 明确把某些 input/output delay 定义为边界外 `interconnect_budget`。
- 实际综合/STA bring-up 后发现某些 channel 需要临时或正式的 reviewed budget。

表单中使用 `budget_required` 和 `budget_basis` 记录该 opt-in 决策；不使用 `timing_model` 自动推断。若项目仍决定不消费 20 SDC，则不得切换到 `budget_output`，应继续使用 `audit_only` 并把新增 budget 请求作为阻断项上报。

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
feedthrough_candidate
exception_path
constant_tie
no_connect
unknown
```

其中 `top_pad_to_harden` / `harden_to_top_pad` / `pad_to_pad` 归 04；`clock_connection` 归 01/02/03；`feedthrough` / `feedthrough_candidate` 归 10；`constant_tie` / `no_connect` 由 00 disposition 终结；`exception_path` 归 30。

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

## 6. budget_output：从 input/output delay 到 channel budget

本节只定义 `budget_output` 模式的数值转换。`audit_only` 仍提取并保存相同 evidence，但不计算用于生成的 channel budget，也不因普通 input/output delay evidence 创建逐 channel budget review 任务。

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

以下情况第一版不自动转换；在 `budget_output` 中进入表单 pending review，在 `audit_only` 中只记录 evidence/diagnostic：

- `-rise` / `-fall`。
- `-clock_fall`。
- `-add_delay`。
- 同一 port 多 clock。
- source-synchronous / DDR 接口。pad 侧 source-sync 约束归 04；harden/subsys 内部 interface source-sync 留到后续 20 扩展。
- 原始命令目标是 bus/pattern 且展开不明确。
- 原始 delay 引用的 clock 无法映射到 SoC clock。
- 原始 delay 同时带复杂 collection，例如多个 `get_ports`、多层 list 或变量。

## 7. 输出文件和 view 维度

无论 `audit_only` 还是 `budget_output`，20 都必须输出：

```text
20_middle/20_harden_x_if.xlsx
20_middle/scenario/<scenario>/channel_inventory.csv
20_middle/scenario/<scenario>/channel_inventory.meta
20_middle/scenario/<scenario>/removed_log/20_harden_x_if.removed
20_result/reports/harden_x_if_check_report_<scenario>.txt
```

`channel_inventory.csv` 是 30 的固定 machine interface，不能只存在于 workbook sheet。

workbook、CSV/meta、SDC、report、pending 和 removed log 均须先完成全量校验，再通过同目录临时文件加原子替换发布。尤其 pending 必须先构造完整 `PendingPlan`；任一 instance 文件缺失、重复 key 或 owner 冲突时，不得留下部分 instance 已删除、部分未删除的状态。

`audit_only` 模式只写一个零 timing-command 占位文件：

```text
20_result/common/20_harden_x_if.sdc
```

该文件用于说明 20 已运行、当前模式和 no-budget policy，不进入实际 SoC SDC source list。它至少包含 author/stage/script、命令行 scenario、`Mode: audit_only`、policy ID、run completeness、port-accounting 状态和 `No timing constraints emitted`。scenario-specific channel/disposition 计数只写对应 report/CSV，不写入这个共用占位 SDC；不得因为 scenario/stage/corner 不同重复生成内容等价的空 overlay SDC。

`budget_output` 模式下，20 的 interface budget 是时序数值，可能随 stage/corner/view 变化。表单必须保留 `stage` / `corner` 字段，生成时不能把多个 corner 的数值平铺进同一个 SDC。

如果项目确认某些 interface budget view-independent，可以生成：

```text
20_result/common/20_harden_x_if.sdc
```

如果 budget 依赖 stage/corner，应生成 view-specific 文件：

```text
20_result/common/20_harden_x_if_<stage>_<corner>.sdc
```

例如：

```text
20_result/common/20_harden_x_if_prects_ss_125.sdc
20_result/common/20_harden_x_if_postcts_ff_m40.sdc
```

同一个 view 内，所有 common harden/subsys interface channel budget 仍归集到一个 20 文件。

### 7.1 assembled view

`audit_only` 模式没有 20 timing assembled view：占位 SDC 不加入 source list，coverage/report 仍按 scenario 检查 channel ownership 和 disposition。

`budget_output` 模式的检查和生成按 assembled view 进行。assembled view 是当前生成目标下实际会被 source 到同一个 analysis view 的 20 约束集合：

```text
view-independent common 20
+ 当前 stage/corner 的 common 20 view-specific 行
+ 当前 scenario 的 20 overlay 行
+ 当前 scenario/stage/corner 的 20 view-specific overlay 行
```

同一 assembled view 内，同一 channel 的普通 interface budget 不能依赖 source 顺序覆盖。若 view-independent 与 view-specific、common 与 scenario 对同一 channel 给出冲突的 approved budget，脚本必须报错或要求表单显式裁决。

mode-specific interface budget 使用 scenario overlay：

```text
20_result/scenarios/func_harden_x_if.sdc
20_result/scenarios/scan_harden_x_if.sdc
20_result/scenarios/mbist_harden_x_if.sdc
20_result/scenarios/<scenario>_harden_x_if_<stage>_<corner>.sdc
```

只有 `budget_output` 模式的 20 文件进入装配，顺序位于 10 feedthrough 之后、30 exception 之前。30 可以在最后覆盖 exception 性质的路径语义，但不应覆盖普通 20 budget 来清 timing。`audit_only` 占位文件不得为了维持编号连续而被隐式 source。

## 8. 表单建议

建议表单至少包含两个 sheet：

```text
channel_inventory
interface_budget
```

此外，workbook metadata（可使用独立 `run_metadata` sheet）必须记录：

```text
mode                    audit_only|budget_output
policy_id               project_default_pr_adjacent_no_harden_if_delay_v1
sdc_consumption         disabled|enabled
run_completeness        complete|partial
available_harden_count
missing_harden_count
missing_instances
```

`audit_only` 必须对应 `sdc_consumption = disabled`，`budget_output` 必须对应 `sdc_consumption = enabled`。二者不一致时阻断成功结束。

### 8.1 channel_inventory

用于记录 00 `connection_inventory.csv` 推导出的 channel。

同一份内容必须确定性写入：

```text
20_middle/scenario/<scenario>/channel_inventory.csv
20_middle/scenario/<scenario>/channel_inventory.meta
```

CSV 至少包含 `schema_version`、`author`、`scenario`、`connection_inventory_digest`、`connection_id`、`channel_id`、src/dst canonical endpoint、`owner_stage`、`channel_disposition`、`apply`、`review_status`、`emit_max`、`emit_min`、`converted_max`、`converted_min`、`budget_type`、`budget_model`、`mode`、`run_completeness` 和 source harden SDC status。`owner_stage` 的 machine enum 固定为 `20`；完整 stage 名写在 meta 的 `stage = 20_harden_x_if`。`budget_type` 只区分 `none` / `channel_datapath_budget`，`budget_model` 才记录 `interconnect_budget` / `manual_budget` 等数值语义。排序必须稳定，一行对应一个 00 bit edge。

CSV 与 workbook `channel_inventory` sheet 必须来自同一个 in-memory resolved view；不得分别计算。配套 `channel_inventory.meta` 至少记录 author、stage/script、scenario/mode、run completeness、00 connection digest、CSV path/digest 和 channel count。30 读取时必须校验 scenario、schema、00 connection digest 和 CSV digest/meta，stale 或 scenario 不匹配时阻断正式生成。

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
src_sdc_status
dst_sdc_status
evidence_status
budget_required
clock_relation
note
```

### 8.2 interface_budget

用于记录从 harden/subsys DC output SDC 提取的 evidence、channel 终态，以及后续可能显式 opt-in 的 budget。

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
budget_required
clock_relation
channel_disposition
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
disposition_basis
sdc_independent_basis
relationship_override_basis
apply
emit_max
emit_min
review_status
owner
reviewer
review_date
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
- `connection_id`：来自 00 `connection_inventory.csv`，并一一标识当前 direct edge。20 不允许构造由多条 00 edge 拼接出的 synthetic connection id。
- `src_direction` / `dst_direction`：用于 pending 消账，必须能回到 `pending/<inst>.ports` 中的第一列方向。
- `src_endpoint` / `dst_endpoint` 必须对应 `channel_id` 指向的 bit-level endpoint；若使用 bus/range collection 作为人工 override，仍必须能回溯到具体 canonical bit channel。
- `is_pad_related` / `is_clock_related` / `is_feedthrough`：从 channel inventory 带入 budget 行，用于阻断错误归属；这些行不应生成 20。
- `src_sdc_status` / `dst_sdc_status`：来自 harden-SDC manifest 的 `available` / `missing` / `not_required`。
- `evidence_status`：至少区分 `complete` / `incomplete_missing_sdc`，不能把 missing 当作未发现 delay/exception。
- `clock_relation`：记录该 channel 在 03/人工 review 中的关系，例如 `synchronous`、`asynchronous`、`logically_exclusive`、`physically_exclusive`、`unknown`；非 `synchronous` / 非 `unknown` 默认阻断普通 20 budget。
- `channel_disposition`：记录该 channel 的 20 终态；统一使用 `emit_budget`、`no_soc_budget_required`、`route_to_30`、`not_applicable`、`pending`。其中 `emit_budget` 只允许在 `budget_output` 模式使用。
- `budget_model`：说明原始 delay 数值的语义，例如 `interconnect_budget`、`clock_relative_io_delay`、`manual_budget`、`unknown`。
- `converted_max`：最终用于 `set_max_delay` 的 channel datapath budget；只有 `interconnect_budget` 可自动取更紧 max，常规 clock-relative delay 必须重新推导或人工填写。
- `converted_min`：review 后的 normalized min 候选。
- `max_source` / `min_source`：记录最终值来自哪一侧或人工 override。
- `derivation_basis`：说明 `converted_max` / `converted_min` 如何推导，例如 `min_interconnect_budget`、`manual_arch_budget`、`period_based_budget`。
- `complex_options`：记录无法自动转换的 SDC 选项。
- `tool_surface`：说明生成目标，例如 `sta`、`dc`、`both`。
- `datapath_only`：说明是否生成 `-datapath_only`，以及该工具是否支持该语义。20 的普通 interface budget 表达的是 channel datapath budget，脚本生成时空值按 `yes` 处理；若项目确认该行不应使用 `-datapath_only`，必须显式填写 `no`。
- `min_sign_review`：说明 min 值是否完成 sign/hold 语义 review。
- `budget_basis`：`emit_budget` 行必须说明 budget 来源，例如 block signoff assumption、架构预算、接口协议、人工裁决；`no_soc_budget_required` 使用 `disposition_basis`，不要求伪造 budget basis。
- `disposition_basis`：记录非 emit 终态的依据；`no_soc_budget_required` 默认引用项目级 no-budget policy，`not_applicable` 记录具体原因。
- `sdc_independent_basis`：只在 required harden SDC 缺失时使用，说明为什么当前 budget/disposition 可以不依赖该 SDC 仍安全裁决。`audit_only` 的普通 direct channel 可由项目 policy 自动填写 `project_pr_adjacent_policy_independent_of_block_sdc_v1`；其它情况空白时必须保持 `pending`。
- `review_status`：统一使用 `pending`、`approved`、`rejected`，不再使用其它同义状态。
- `reviewer`、`review_date`：记录人工终态批准人和日期；项目级 policy 自动批准的 `no_soc_budget_required` 可由 policy owner/date 统一填入。
- `relationship_override_basis`：当 03 中已有非同步关系但仍要求生成 20 budget 时，必须说明裁决依据；正常情况下该 channel 应转 30。

## 9. 输出门槛

`audit_only` 的输出门槛为：

```text
mode = audit_only
sdc_consumption = disabled
所有纳入 20 的普通 direct channel 已形成 approved terminal disposition，或明确保持 pending
不存在 emit_budget / budget_required=yes / emit_max=yes / emit_min=yes
输出 SDC 中 set_max_delay/set_min_delay 及其它 timing command 数量为 0
```

`audit_only` 只生成 inventory、workbook、coverage/check report、removed log 和零命令占位 SDC。pending 行可以保留并在 report 中阻断 completeness，但不能导致任何 timing command 输出。

只有 `budget_output` 模式中 `channel_disposition = emit_budget` 的 channel 才进入 SDC timing-command 生成门槛，并且必须同时满足：

```text
mode = budget_output
sdc_consumption = enabled
apply = yes
review_status = approved
channel_disposition = emit_budget
scenario/stage/corner 与当前生成 view 匹配
src_endpoint 非空
dst_endpoint 非空
channel_type 属于 20 支持范围
不是 pad-related
不是 clock-related
不是 feedthrough
不是 exception path
budget_required = yes
budget_model 非空且不为 unknown
若 budget_model = clock_relative_io_delay，必须有人工或公式化 derivation_basis，不能直接使用原始 input/output delay 原值
emit_max = yes 且 converted_max 非空，才生成 set_max_delay
emit_min = yes 且 converted_min 非空且 min_sign_review 完成，才生成 set_min_delay
tool_surface / datapath_only 策略已确认
budget_basis 非空
```

pending / rejected 行不生成。

任何模式下，`channel_disposition = no_soc_budget_required` / `not_applicable` 的 approved 行都不生成 timing command；满足本规则的终态检查后，只影响 inventory、coverage 和 removed log。`route_to_30` / `pending` 行既不生成，也不能由 20 消账。

## 10. 检查规则

### 10.1 error

以下情况应阻断成功结束：

- `mode` 不在 `audit_only` / `budget_output` 中，或未记录 mode。
- `audit_only` 与 `sdc_consumption = enabled` 组合，或 `budget_output` 与 `sdc_consumption = disabled` 组合。
- `audit_only` 中存在 `channel_disposition = emit_budget`、`budget_required = yes`、`emit_max = yes` 或 `emit_min = yes`。
- `audit_only` 输出 SDC 中出现 `set_max_delay`、`set_min_delay` 或其它 timing command。
- `budget_output` 已生成 timing command，但 flow metadata 未确认对应输出会进入 analysis view source list。
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
- `channel_disposition` 不在 canonical enum 中。
- `channel_disposition = no_soc_budget_required`，但 channel 是 pad、clock、feedthrough、unresolved connection 或已识别的 exception candidate。
- `channel_disposition = no_soc_budget_required` / `not_applicable`，但 source/destination 任一 required harden SDC 为 `missing`，且没有 approved `sdc_independent_basis`。
- `channel_disposition = no_soc_budget_required`，但 `apply != yes`、`review_status != approved`、`budget_required != no`、缺少 `disposition_basis`，或仍要求 `emit_max` / `emit_min`。
- `channel_disposition = emit_budget`，但 `budget_required != yes`。
- `channel_disposition = route_to_30` / `pending`，却要求 20 消账。
- `channel_disposition = not_applicable`，但 `apply != yes`、`review_status != approved`，或缺少 owner、reviewer、review_date 和明确 basis。
- `budget_model = unknown` 却要求生成。
- `budget_model = clock_relative_io_delay` 且没有 `derivation_basis` / `budget_basis` 说明，却直接把原始 delay 值作为 `converted_max`。
- channel 两端 clock 在当前 03 assembled view 中被声明 `asynchronous` / `logically_exclusive` / `physically_exclusive`，但仍生成普通 synchronous interface budget，且没有 `relationship_override_basis`。
- `emit_max = yes` 但 `converted_max` 为空。
- `emit_min = yes` 但 `converted_min` 为空。
- `emit_min = yes` 但 `min_sign_review` 为空或未通过。
- `tool_surface` 包含 DC/综合，但 `-datapath_only` 策略未确认。
- `channel_disposition = emit_budget` 且 `review_status = approved`，但 `budget_basis` 为空。
- 原始 SDC 命令无法归属到任何 channel，却被要求生成。

### 10.2 warning

以下情况应 warning，要求 reviewer 关注：

- `audit_only` 运行存在 missing harden SDC；no-budget policy 可以独立终结 port ownership，但 exception evidence 仍不完整。
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

上述 budget 数值类 warning 只对 `budget_output` 或已经明确提出 budget request 的 channel 升级为 reviewer action。`audit_only` 中提取到的普通 input/output delay 只作为 evidence 汇总，不应制造逐 channel budget review 工作。

### 10.3 coverage report

20 脚本应输出 coverage report：

- 本次 `mode`、policy ID 和 `sdc_consumption`。
- 输出 SDC timing-command 计数；`audit_only` 必须为 0。
- 所有 SoC 内部 harden/subsys channel 列表。
- channel 列表必须是 bit-level；coverage 可附 bus summary，但生成/消账使用 per-bit channel。
- 每条 channel 的 scenario/stage/corner view。
- 每条 channel 的 `budget_required`、`budget_model`。
- 每条 channel 的 `channel_disposition`、review 状态和终态证据。
- 每条 channel 是否找到 source output delay。
- 每条 channel 是否找到 destination input delay。
- 每条 channel 的最终 `converted_max` / `converted_min`。
- 每条 channel 是否生成 `set_max_delay` / `set_min_delay`。
- 未生成原因，例如 `no_soc_budget_required`、`not_applicable`、pad-related、clock-related、route-to-30、missing budget、budget_model unknown、pending review。
- 两端 budget 差异较大的 channel 清单。
- clock-relative delay 被提取但未转换的 channel 清单。
- `audit_only` 中按 PR 相邻 policy 终结的 channel/port 数量。
- missing SDC 导致 exception evidence 不完整、但按 SDC-independent PR policy 完成 no-budget 销账的 channel 清单。

### 10.4 pending 消账

target 模式在以下任一终态成立后，可以从 `00_middle/scenario/<scenario>/pending` 删除该 channel 对应的 harden canonical bit key，并写入：

```text
20_middle/scenario/<scenario>/removed_log/20_harden_x_if.removed
```

legacy cwd 才使用 `00_harden_port_inventory/pending` 和集中式 `removed_log/20_harden_x_if.removed`。

- `channel_disposition = emit_budget`，且该行实际生成了 `set_max_delay` 或 `set_min_delay`。
- `channel_disposition = no_soc_budget_required`，且已满足 §2.4.1 的项目 PR 相邻 policy 和 approved 终态门槛；这是 `audit_only` 的默认销账路径。
- `channel_disposition = not_applicable`，且 owner/reviewer/basis 齐全并 approved。

`route_to_30` / `pending` 不能由 20 消账。

target 模式未使用 `--no-update-pending` 时，pending 缺失必须阻断。`--no-update-pending` 仅用于诊断，必须写入 report，且不得宣称 accounting closure 完成。

删除规则：

- 只删除 exact canonical bit key，例如 `output data_o[7]`、`input data_i[3]`。
- `top` / `fabric` 端没有 harden pending 文件，不删除。
- 20 只删除当前 20-owned direct edge 的 endpoint。任何 `fti_*` / `fto_*` 相邻 edge 及其 endpoint 均由 10/30 按各自终态处理，20 不删除。
- pending 消账只表达 port 已归属 20 的 budget policy/disposition，不证明网表级完整 fanout path closure。同一 source port 可按自身 20 终态销账；其它 sink/path 仍由各自 port 状态和 30 candidate/rule 独立处理。
- missing SDC 下使用项目级 `sdc_independent_basis` 销账，只终结“是否需要 20 channel delay”这一 port-level 问题；不得据此关闭 30 的 path-level exception completeness 检查。
- 若同一 canonical port 已因普通 timing channel 由 20 消账，后续 30 可对经过该 port 的更窄 path 生成 exception，但 30 不得再写第二份 port removal ownership。30 report 应分别记录 `port_owner=20_harden_x_if` 与 `path_constraint_owner=30_harden_to_harden_exception`。
- 若待删除 key 不在 pending 中，但 previous removed log 已说明该 key 被早期 stage 消费，则视为幂等重跑；否则报 error。

## 11. 示例

### 11.1 budget_output：明确 interconnect_budget 的 harden-to-harden channel

集成关系：

```text
u_a/data_o -> u_b/data_i
```

前提：项目已显式设置 `mode = budget_output`、`sdc_consumption = enabled`，且 `u_a` / `u_b` owner 明确声明下面的 max delay 是为 SoC boundary-to-boundary channel 预留的 interconnect budget，而不是常规 clock-relative IO delay。

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
mode              budget_output
src_endpoint      [get_pins u_a/data_o]
dst_endpoint      [get_pins u_b/data_i]
budget_required   yes
channel_disposition emit_budget
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

### 11.2 budget_output：常规 clock-relative delay 不自动转换

集成关系：

```text
u_a/data_o -> u_b/data_i
```

`u_b` SDC：

```tcl
set_input_delay -max 1.2 -clock clk_b [get_ports data_i]
```

在 `budget_output` 模式下，如果 harden owner 说明该值是常规 block signoff input delay，含外部 launch 假设或 clock-relative arrival，而不是 SoC channel interconnect budget，则表单应记录：

```text
budget_model      clock_relative_io_delay
channel_disposition pending
converted_max     <blank>
apply             no
review_status     pending
note              requires period/02 budget/manual derivation before set_max_delay emit
```

不生成：

```tcl
# 不允许直接生成
set_max_delay 1.2 -datapath_only -from [get_pins u_a/data_o] -to [get_pins u_b/data_i]
```

### 11.3 audit_only：项目默认不做 SoC interface budget

集成关系：

```text
u_a/status_o -> u_b/status_i
```

若该连接是 SoC 集成表单中的明确 direct functional channel，且不属于 clock、pad、feedthrough、NC/tie-off 或已识别的 exception candidate，则在默认 `audit_only` 模式按项目 PR 相邻 policy 记录：

```text
channel_id             CH_u_a_status_o__u_b_status_i
mode                   audit_only
src_endpoint           [get_pins u_a/status_o]
dst_endpoint           [get_pins u_b/status_i]
budget_required        no
channel_disposition    no_soc_budget_required
budget_model           unknown
disposition_basis      project_default_pr_adjacent_no_harden_if_delay_v1
apply                  yes
emit_max               no
emit_min               no
review_status          approved
owner                  soc_sdc_methodology
reviewer               policy_owner
review_date            2026-07-11
```

该行不生成 `set_max_delay` / `set_min_delay`。20 coverage report 记录 `no_soc_budget_required`，并写 removed log、删除对应 pending bit。该终态只记录当前 SoC SDC budget policy，不代表脚本已经读取 netlist/DEF/lib、测量实际物理距离、推断完整 fanout path 或完成 STA coverage 验证。`audit_only` 输出 SDC 必须为零命令占位文件：

```tcl
# 20_harden_x_if.sdc
# Mode: audit_only
# Policy: project_default_pr_adjacent_no_harden_if_delay_v1
# SDC consumption: disabled
# No timing constraints emitted.
```

该文件不加入实际 SoC SDC source list；inventory、coverage report 和 removed log 才是默认模式需要消费的 20 产物。

### 11.4 pad-related channel

集成关系：

```text
top.pad_rx -> u_b/data_i
```

即使 `u_b` SDC 中有：

```tcl
set_input_delay -max 2.0 -clock v_pad [get_ports data_i]
```

该约束也不进 20，应归 04 作为 SoC IO/pad environment 处理。

### 11.5 exception path

集成关系：

```text
u_cfg/data_o -> u_core/cfg_i
```

如果该路径是 configuration handshake，架构要求不按普通同步接口 budget 分析，则 20 记录 `channel_disposition = route_to_30`，不生成、不消账，由 30 完成 exception review 和终结。

## 12. 暂不处理

第一版暂不处理：

- 自动识别所有 exception path。
- 自动解析 DDR/source-synchronous 多边沿 input/output delay。
- 自动转换复杂 `set_output_delay -min` sign 语义。
- 自动推断 fabric 内部非 harden endpoint。
- 自动根据名字猜测 test/scan/mbist interface。
- 跨 feedthrough harden 内部拼接 end-to-end channel；该行为在 SoC top 层级明确禁止。

这些内容必须进入表单 review 或留给后续 scenario/20/30 机制处理。
