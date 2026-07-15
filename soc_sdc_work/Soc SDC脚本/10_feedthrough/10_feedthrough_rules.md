# 10_feedthrough.sdc 规则说明

本 stage 遵守 [Shared Script Runtime Rules](../docs/shared_script_runtime_rules.md)。目标迁移后，feedthrough edge inventory/form 写入 `10_middle/`，最终 SDC/report 写入 `10_result/`。

## 1. 目标和层级边界

本流程生成的是 **SoC top 综合使用的 SDC**。10 只处理 SoC top 可见、且与 harden feedthrough boundary port 相连的 direct interconnect edge。

典型连接为：

```text
u_src/out -> u_ft/fti_xxx -> [harden internal] -> u_ft/fto_xxx -> u_dst/in
```

10 的约束对象只有两条 SoC-visible direct edge：

```text
u_src/out    -> u_ft/fti_xxx
u_ft/fto_xxx -> u_dst/in
```

10 对这些 direct edge 生成的 `set_max_delay` / `set_min_delay -datapath_only` 表达的是 SoC interconnect 的物理 datapath budget，不是基于 launch/capture clock relationship 的同步 setup/hold budget。clock 是否同源、异步或互斥，不决定该 direct edge 是否归 10，也不决定一个已经独立批准的物理 budget 是否可以生成。

若经过多个 feedthrough harden，`u_ft1/fto_xxx -> u_ft2/fti_yyy` 也是一条独立的 SoC-visible direct edge，由 10 处理。

`u_ft/fti_xxx -> u_ft/fto_xxx` 位于 harden 内部，不是 SoC top 互联边。SoC 不读取内部 netlist，不负责该段的 timing/exception，也不得为该段生成 SDC。harden 内部约束由 harden owner 在 harden 自身层级完成。

因此：

- 10 的最小 ownership、review、生成和 coverage 对象是 00 `connection_inventory.csv` 中的一条 direct bit edge。
- `fti` / `fto` 配对只允许作为可选的命名检查、链路说明或人工 review 元数据。
- 内部配对是否成功不决定外部 direct edge 能否分类，不触发 pending 删除，也不产生任何 SDC path。
- 10 不把两侧 direct edge 拼成 `u_src/out -> u_dst/in` 的 end-to-end budget 或 exception。

## 2. Feedthrough Boundary 识别

10 识别以下方向前缀：

```text
fti_ = feedthrough input boundary
fto_ = feedthrough output boundary
```

强制方向规则：

- `fti_*` 必须是 harden input。
- `fto_*` 必须是 harden output。
- `inout` 不自动解释为 `fti` 或 `fto`。完成 01/04 ownership precedence 后，疑似归 10 的 boundary 若仍为 `inout`，属于结构输入错误：10 报 error、不建立 terminal row、不生成、不消账，并保留原 pending，直到 wrapper/集成表单拆成明确 input/output。

`fti_` / `fto_` 后缀中的 `<src>2<dst>`、signal name、hop index 都只是推荐可读性信息，不是 direct edge 真源。真实 source、destination、bit mapping 和方向只读取 00 `connection_inventory.csv`。

推荐命名可以继续使用：

```verilog
input  fti_<src>2<dst>_<signal_name>;
output fto_<src>2<dst>_<signal_name>;

input  fti_<index>_<src>2<dst>_<signal_name>;
output fto_<index>_<src>2<dst>_<signal_name>;
```

同一 harden 内 remainder 相同的 `fti` / `fto` 可以形成 `related_pair_id`，多 hop 可以形成 `related_chain_id`。这两个 id 只用于 report：

- 不证明 harden 内部是纯组合、无寄存器或存在可用 timing arc。
- 不允许作为 SoC SDC 的 `-from/-to/-through` 路径依据。
- remainder 不同、bit index 重编号、无法配对或 hop index 不连续，不阻断已由 00 明确的外部 direct edge。

## 3. Direct Edge 分类和 Ownership

10 从 00 bit-level `connection_inventory.csv` 分类 edge。当前 stage 优先级下，clock/pad 先由 01/04 排除；剩余 SoC 内部 functional edge 若满足以下任一条件，归 10：

```text
ingress:              destination 是 fti_* input
egress:               source 是 fto_* output
between_feedthroughs: source 是 fto_* output，destination 是 fti_* input
```

ownership 还必须满足：

- 使 edge 归 10 的 `fti_*` / `fto_*` endpoint instance 必须是 harden-SDC manifest 中的 harden；`top` / `fabric` / `unknown` / `constant` 等 pseudo instance 上仅出现同名前缀，不能证明 10 ownership。`between_feedthroughs` 的两侧都必须满足此条件。
- `connection_type` 必须通过 00 schema 的 canonical enum 校验，并且已明确排除 01 clock 和 04 pad ownership。空值或 schema 外字符串（包括拼写错误）是 error；合法的 `unknown` 保持 `needs_review`，两者都不得进入 terminal disposition。
- canonical `no_connect` 是合法的 00 类型，不是拼写错误；它以及 `nc` / `no_connect` pseudo instance 表示没有 SoC-visible direct connection，必须在 10 candidate 分类前排除，不生成 inventory terminal row、SDC 或 10 removal。无关的合法 `no_connect` 行不得导致 10 全局失败。
- `fti/fto` 方向检查只对完成 01/04 ownership precedence 后的 10 candidate 执行；已经归 01/04 的 edge 不由 10 重复裁决方向。

示例：

```text
u_src/out         -> u_ft1/fti_a       # ingress
u_ft1/fto_a       -> u_ft2/fti_b       # between_feedthroughs
u_ft2/fto_b       -> u_dst/in          # egress
```

这三条 edge 都由 10 独立分类、review 和终结。20 必须读取当前 scenario 的 10 inventory，并按 `connection_id` 排除它们，不得把它们重新归类为普通 functional channel，也不得拼成一条 source-to-destination channel。由于 10 先于 20 运行且 fixed downstream reads 不包含任何 20 产物，10 不读取或猜测未来的 20 inventory；10/20 ownership overlap 由 20 在 assembled ownership 检查中报 error。

不涉及 `fti_*` / `fto_*` boundary 的普通 functional direct edge 归 20。exception-only edge 仍先由其 normal timing owner 分类：feedthrough-related edge 由 10 标记 `route_to_30`，其它普通 edge 由 20 标记 `route_to_30`。

## 4. Feedthrough Edge Inventory

10 必须输出 bit-level `feedthrough_edge_inventory.csv`。每行对应一个且仅一个 00 `connection_id`，建议字段至少包括：

```text
schema_version
port_accounting
connection_inventory_path
harden_sdc_manifest_path
scenario_scope
run_completeness
available_harden_count
missing_harden_count
not_required_harden_count
missing_instances
scenario
stage
corner
feedthrough_edge_id
connection_id
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
feedthrough_instance
feedthrough_port
feedthrough_side
channel_disposition
budget_scope
budget_model
budget_required
converted_max
converted_min
emit_max
emit_min
datapath_only
tool_surface
src_sdc_status
dst_sdc_status
evidence_status
src_clock
dst_clock
clock_relation
machine_digest
apply
review_status
owner
reviewer
review_date
approved_machine_digest
disposition_basis
sdc_independent_basis
relationship_override_basis
min_sign_review
related_pair_id
related_chain_id
validation_status
note
```

字段规则：

- `scenario_scope` 原样记录 00 direct edge 的 canonical scope；`scenario` 记录本次实际装配的 canonical scenario。`port_accounting`、`connection_inventory_path` 和 `harden_sdc_manifest_path` 必须记录本次运行的实际状态和 resolved machine-input 路径。
- `feedthrough_edge_id` 必须稳定、bit-specific，并一一引用 `connection_id`。当前格式固定为 `FTE_<connection_id>`，不得重写或拼接内部 segment id。
- `src_soc_object` / `dst_soc_object` 必须与同一行的 `instance + canonical port` 一致。10 自行生成 brace-protected `get_pins/get_ports` collection，不接受表单用任意 Tcl collection 改写 direct edge endpoint。
- `feedthrough_side` 使用 `ingress` / `egress` / `between_feedthroughs`。
- `feedthrough_instance` / `feedthrough_port` 记录使该 edge 归 10 的 boundary；`between_feedthroughs` 可使用逗号分隔的有序两端值或拆成明确 src/dst feedthrough 字段。
- `budget_scope` 第一版固定为 `direct_edge`。不得填写或自动推导 `end_to_end`。
- `related_pair_id` / `related_chain_id` 可以为空，只用于 report/review；不得作为 ownership、生成或消账 gate。
- `machine_digest` 覆盖 direct endpoint、SDC evidence/digest 和 validation 等会影响物理 budget 的 material machine fields。approved row 记录匹配的 `approved_machine_digest`；material machine field 刷新后自动退回 `apply=no/review_status=pending`，在重新批准前持续阻断正式输出更新。不得提供 force/bypass 选项跳过该重新 review gate。`src_clock` / `dst_clock` / `clock_relation` 只是 diagnostic metadata，单独变化不得改变 `machine_digest`、重置 approval 或阻断物理 budget。
- `validation_status` 至少区分 `matched` / `needs_review`。它验证的是 00 direct edge 和 SoC-visible endpoint，不验证 harden 内部实现。
- vector/range 必须继承 00 的 canonical bit 展开。一个 inventory 行和一个 `feedthrough_edge_id` 不得代表多个 bit。
- `relationship_override_basis` 保留为 legacy/可选说明字段，不是 10 `emit_budget` 的生成门槛；新 review 应使用 `disposition_basis` 说明物理 budget 和终态依据。

10 不再生产表示 harden 内部 `fti -> fto` segment 的 `feedthrough_id`。30 若处理 feedthrough-related exception，引用 `related_10_feedthrough_edge_id`，其值必须指向这里的 direct edge id。

## 5. Timing Policy 和 SDC 生成

10 与 20 使用相同的 direct-edge command form 和 budget evidence model，但 clock-relation policy 以本节为准；不能据此假设 10 与 20 的所有审核门槛完全相同。第一版 `channel_disposition` 统一使用：

```text
emit_budget
no_soc_budget_required
route_to_30
not_applicable
pending
```

含义：

- `emit_budget`：对当前 direct edge 生成 reviewed `set_max_delay` / `set_min_delay`。
- `no_soc_budget_required`：项目 policy 明确该 direct edge 不需要额外 SoC channel budget；不生成 SDC，但可按 approved 终态消账。
- `route_to_30`：有明确 exception、CDC/protocol override 或其它 path-level evidence，且 review 决定该 direct edge 应由 30 处理；10 不生成、不消账。仅有 async/exclusive/unknown clock relation 不能自动触发该终态。
- `not_applicable`：经 review 确认不适用 timing constraint，且有完整 owner/basis；不生成 SDC，但可消账。
- `pending`：输入或 review 不完整，不生成、不消账。

当前项目默认的普通 channel no-budget policy若同样适用于 feedthrough-related direct edge，可以由 policy owner 批准 `no_soc_budget_required`。该终态必须满足 `apply=yes`、`review_status=approved`、`budget_required=no`、`emit_max=no`、`emit_min=no`、`approved_machine_digest` 匹配，并填写 policy owner、reviewer、review date 和明确的版本化 policy/basis。不能仅凭 port 名为 `fti_*` / `fto_*` 自动应用该终态。

正式生成、routing 和消账统一遵守以下 review gate：

- 只有 `apply=yes` 且 `review_status=approved` 的 terminal row 才有效；它必须有 `validation_status=matched`、非空且匹配当前 `machine_digest` 的 `approved_machine_digest`。`pending` 不得同时标记为 approved/applied。
- approved `emit_budget` 必须有非空 `tool_surface=dc|sta|both`、`budget_required=yes`、`datapath_only=yes`、明确的 `interconnect_budget|manual_budget`、至少一个 `emit_max/emit_min=yes`、对应有限数值和 `disposition_basis`；生成 min 时还必须完成 `min_sign_review`。
- approved `no_soc_budget_required` 必须显式填写 `budget_required=no`、`emit_max=no`、`emit_min=no`，并具备 owner、reviewer、review date 和可识别版本号的 policy/basis；空白 emit flag 不能等价为 `no`。
- approved `route_to_30` 必须具备 owner、reviewer、review date 和明确的 exception/CDC/protocol/path-level `disposition_basis`。clock relation 本身不能作为该 evidence。
- approved `not_applicable` 必须具备 owner、reviewer 和明确的 `disposition_basis`。
- machine evidence 同步或 refresh 后，只要 material field 变化，旧 approval 必须失效并重新 review；不得通过命令行 force 选项继续沿用旧 approval 或生成正式 SDC。`--force-generate-after-sync` 不属于受支持 CLI，必须拒绝。

只有 `emit_budget` 才生成：

```tcl
set_max_delay <value> -datapath_only -from <src_soc_object> -to <dst_soc_object>
set_min_delay <value> -datapath_only -from <src_soc_object> -to <dst_soc_object>
```

这里的 `-datapath_only` 明确剥离 clock latency/skew 语义；命令约束的是当前 00 direct edge 的数据传播上下限。它不是 synchronous budget，也不要求 source/destination clock 被证明为 synchronous。

数值来源、min review 和 command form 沿用 20 的 direct interface budget 基础规则；clock handling 使用下面的 10-specific 规则：

- input/output delay 只是候选 evidence，不能机械等价转换成 boundary-to-boundary datapath budget。
- 只有明确的 `interconnect_budget` 或人工 `manual_budget` 才能产生 `converted_max/min`。
- min/sign/hold 语义必须单独 review。
- `-datapath_only` 在 DC/目标工具上的支持和含义必须由项目 flow 确认。
- 第一版只有 `datapath_only = yes` 的 approved `emit_budget` 行可以生成命令；不能通过留空或填写 `no` 静默改变 direct-edge budget 语义。
- 01-owned clock edge 依据 00 canonical `connection_type` 和 stage ownership precedence 排除。可选的 01 assembled clock inventory 只用于 corroboration，并把 harden input/output-delay evidence 引用的本地 clock 显示为 diagnostic metadata；它不参与 max/min generation gate。
- 03 relation map 对 10 是可选 diagnostic input。`synchronous` / `asynchronous` / `logically_exclusive` / `physically_exclusive` / `unknown` 均不能自动放行、阻断或改写 `channel_disposition`，也不能自动把 edge 提升为 30 exception。
- 本地 clock 名相同不能证明它们映射到同一个 active SoC clock。无法通过 `(inst_name, original_clock_name)` 和 `check_only` upstream object 唯一解析时，diagnostic relation 记录为 `unknown/unresolved`；但该状态不阻断独立批准的物理 budget。
- 如果读取 relation map，CSV 与 meta 必须配对并匹配当前 scenario、assembled clock universe 和 digest。缺失、partial、stale、非法 relation enum 或 digest 不匹配时，report 记录 `unavailable/incomplete/stale/invalid`；这些 diagnostic 状态本身不得阻断 10 SDC、pending 消账或重置 approval。
- 只有当人工 budget basis 明确采用 clock period、clock-relative I/O delay 或其它 clock-domain 假设推导数值时，clock mapping/relation 才属于该数值推导的 review evidence；这仍是 `disposition_basis` 的完整性检查，不是普通 physical interconnect budget 的 relation gate。
- exception、false/multicycle 或 CDC/protocol-specific max/min override 由 30 读取 authoritative 03 relation 后裁决；30 不得继承 10 的 informational `clock_relation` 作为真源。
- 10 生成 physical budget 不代表它已经证明最终 assembled SDC 中该命令未被 clock-group/false-path 等更高优先级约束遮蔽；项目 flow 仍需执行 constraint precedence/coverage 检查。该检查结果用于 signoff report，不反向改变 10 的 direct-edge ownership。

### 5.1 多 bit 命令级合并

inventory、ownership、approval、digest、coverage 和 pending 消账始终保持 bit-level。为了便于最终 SDC review，可以把多条 bit row 合并成一条 Tcl 命令，但这只是确定性的输出展示优化，必须同时满足：

- 所有 bit 具有相同 scenario/stage/corner、tool surface、command type、`converted_max/min`、`datapath_only`、budget model、disposition 和 approved 状态。
- 所有 bit 来自同一个 source bus、到达同一个 destination bus，并由 00 证明为无 fanout、无缺口、无重复的一一对应 direct edge。允许保持位序的单调常量 offset 映射，例如 `src[0] -> dst[4]`、`src[1] -> dst[5]`；组内每个 bit 必须满足同一个 `dst_bit_index - src_bit_index`，且 source/destination 序列方向一致。reverse、permutation、非线性映射，或任一 bit 存在独立 override/多重 edge 时不得合并。
- 合并后的 `-from` / `-to` collection 不得扩大逐 bit 命令实际约束的 path 集合。collection 必须显式只选择这组已批准 canonical bit，不得用可能覆盖未审核 bit 的宽泛 wildcard/range。
- SDC comment/report 必须列出被合并的全部 `feedthrough_edge_id` / `connection_id`。任一 bit 后续发生 material change 时，该 bit 按自身 digest 退回 review，原合并组自动拆分；未变化 bit 保留各自 approval，之后仍同质的 bit 可重新确定性分组。

无法证明命令语义与逐 bit 生成完全等价时保持逐 bit 命令。不得为了缩短 SDC 而把多个 bit-level edge 合并成一个 inventory row 或 synthetic connection。

严禁生成：

```tcl
# 禁止：harden 内部 endpoint pair
set_max_delay ... -from [get_pins u_ft/fti_xxx] -to [get_pins u_ft/fto_xxx]

# 禁止：跨不可见 harden 内部拼接的普通 budget
set_max_delay ... -from [get_pins u_src/out] -to [get_pins u_dst/in]
```

## 6. Harden SDC 渐进交付

10 只能通过当前 scenario 的 harden SDC manifest 发现 harden 和 SDC，不得扫描目录或按 `<inst>.sdc` 猜路径。manifest validation 在 edge 分类前完成：

- 必须包含 `scenario,inst_name,module_name,sdc_path,availability_status,note` 全部字段；`sdc_path` / `note` 即使某行允许为空，也不能缺列。
- manifest scenario 必须与命令行 scenario 一致；同一 `inst_name` 恰好一行，实例名和 status 不得为空。
- `availability_status` 只允许 `available` / `missing` / `not_required`。
- 每个 `available` 的 `sdc_path` 必须非空、唯一、存在且可读；两个 harden 不得复用同一 resolved SDC path。
- `missing` 只表示尚未交付，不表示没有 timing/exception evidence。
- `not_required` 必须在 `note` 中给出明确依据，不能靠空路径推断。

edge 的结构分类只依赖 SoC 集成表单和 00 connection inventory，因此即使相关 harden SDC 缺失，10 仍应输出 inventory 行。

但 timing/exception evidence 可能依赖 source/destination harden SDC。默认 partial-availability mode 下：

- available 一端正常提取 evidence。
- harden SDC 的 Tcl command 必须按 brace/bracket 完整性解析，支持无反斜杠的多行 `get_ports/get_pins` collection；已读取文件存在未闭合 command 时按 parse error 阻断，不能降级为 no evidence。
- missing 一端记录 `src_sdc_status` / `dst_sdc_status = missing` 和 `evidence_status = incomplete_missing_sdc`。
- 不得把 missing 解读为“没有 timing budget”或“没有 exception”。
- 受影响 edge 默认 `channel_disposition = pending`，不生成、不消账。
- 只有 approved `sdc_independent_basis` 明确说明结论不依赖缺失 SDC 时，才允许 `emit_budget` / `no_soc_budget_required` / `not_applicable`。

其它 available edge 继续处理。启用 `--require-complete-harden-sdc` 后，manifest 中仍有 required missing SDC 才全局阻断。

## 7. Pending 和 Scenario 规则

10 只能在某条 SoC-visible direct edge 达到以下终态后，删除该 edge 对应的 harden canonical endpoint，并写 `10_feedthrough.removed`：

- `emit_budget` 且实际生成至少一个 reviewed max/min command。
- approved `no_soc_budget_required`，且 policy owner、reviewer、review date 和版本化 policy/basis 完整。
- approved `not_applicable`，且 owner/reviewer/basis 完整。

`route_to_30` / `pending` 不能由 10 消账。

port accounting 默认开启。target 模式未使用 `--no-update-pending` 时，`00_middle/scenario/<scenario>/pending/` 是 required upstream；目录缺失或损坏必须阻断正式 SDC 和消账。正式处理任何 row 前，即使当前没有 terminal row，也必须完整验证 pending：

- manifest 中每个 harden 必须有可读的 `<inst>.ports`。
- 每条非空、非整行注释必须严格解析为 `<input|output|inout> <canonical scalar-or-bit port>`。
- port 不得是 bus range、wildcard 或 pattern；同一文件内 `(direction, port)` 不得重复。
- 任一文件缺失、不可读、非法行、非法 direction、非 canonical key 或 duplicate 都是 error；不能只验证本次准备删除的行。

10 的 previous-owner 检查只读取当前 scenario 的固定早期日志：

```text
00_middle/scenario/<scenario>/removed_log/00_disposition.removed
01_middle/scenario/<scenario>/removed_log/01_soc_clocks.removed
04_middle/scenario/<scenario>/removed_log/04_soc_io_pads.removed
```

已由早期 stage 拥有的 canonical port 不得再次由 10 删除或写入 `10_feedthrough.removed`；accounting ownership 不得反向改变 direct-edge constraint classification。禁止读取其它 scenario、未来 20/30 或 legacy removed log 来补齐 target previous-owner 状态。

`--no-update-pending` 只用于显式 diagnostic 运行；此时不要求 pending 存在，不读取、不修改 pending/removed log，也不得宣称 port closure 完成。stdout、SDC header、workbook/inventory 和 report 必须记录 `Port accounting: disabled by explicit option`。

删除的依据必须记录 `feedthrough_edge_id`、`connection_id`、`channel_disposition` 和 scenario。`fti_*` / `fto_*` 只能因为其相邻 direct edge 已形成终态而删除，不能因为找到了同 harden 的配对 port 而删除。非 feedthrough 一端也属于同一条 10-owned edge；若其 port-level owner 由 10 终结，按相同规则删除。

feedthrough 身份和 edge 分类通常是 common structural metadata，但 timing evidence、exception 和 disposition 是 scenario/view 相关结论。因此：

- `feedthrough_edge_inventory` 按 scenario 生成或装配。
- 每个 scenario 使用自己的 pending/removed log。
- 不再把 common 10 removal 无条件重放到其它 scenario。
- 可以复用 common edge classification，但必须在目标 scenario 重新裁决 terminal disposition 后才能删除 pending。
- workbook 中 `(scenario, stage, corner, connection_id)` 是精确 view key；`stage=all` / `corner=all` 是独立 all-view，不作为其它 named stage/corner 的隐式 fallback。
- `scenario=common` 只装配 common row。其它 scenario 的 active review view 是 `common row + 当前 scenario row`，foreign-scenario row 不参与。
- common 与当前 scenario row 若对同一 connection/view 形成不同的 approved terminal effect 或不同命令，assembled view 必须报 error；不得依靠 source order 静默覆盖。命令完全相同时，scenario overlay 不重复生成同一命令，但当前 scenario row 仍可独立完成本 scenario 的 pending 终态裁决。

## 8. 输入和输出

target 运行入口：

```bash
python3 10_extract_feedthrough.py \
  --run-root <run_root> \
  --scenario <scenario> \
  --stage <stage> \
  --corner <corner>
```

`--stage` / `--corner` 可按是否生成 view-specific budget 决定是否必填；`--scenario` 始终必填。

`--run-root` 进入 target 模式后，下面列出的 input、workbook、inventory、SDC、report 和 removed-log 路径全部固定。任何 legacy/custom input/output path override 都必须拒绝，不能一边读取 target manifest/pending、一边写 legacy cwd。target 10 只读取本节 required inputs 和 01/03 optional diagnostic inputs；不得读取 `20_middle` 或用 20 inventory 反推 ownership。

目标运行 required 输入：

```text
00_middle/connection_inventory.csv
00_middle/scenario/<scenario>/harden_sdc_manifest.csv
00_middle/scenario/<scenario>/pending/                 # accounting enabled 时 required
```

可选 diagnostic 输入：

```text
01_middle/assembled/<scenario>/clock_inventory.csv
01_middle/assembled/<scenario>/clock_inventory.meta
03_middle/relation_map/<scenario>.csv
03_middle/relation_map/<scenario>.meta
```

optional diagnostic artifact 缺失或不完整不得阻断 10 inventory、已批准物理 SDC 或 pending 消账。只要其中任一 CSV 被读取，就必须同时读取对应 meta 并校验 scenario/digest；校验失败只降低 diagnostic status，不得把缺失 pair 或本地同名解释为 synchronous。

00 connection inventory 必须具有受支持的 `schema_version` 和非空 `scenario_scope`。scope 只允许 `common`、单个具体 scenario，或无重复、稳定排序的 scenario list；缺列、空值、非法 token、重复或非稳定顺序都是 error。10 先保留 scope 包含 `common` 或当前 `--scenario` 的行，再对 active row 执行 10-specific endpoint/ownership validation；合法的 foreign-scenario row 不得进入 10 inventory、workbook active view、SDC 或销账，也不得因其不属于当前 view 的其它字段触发 10 candidate error。

目标运行输出：

```text
10_middle/10_feedthrough.xlsx
10_middle/scenario/<scenario>/feedthrough_edge_inventory.csv
10_middle/scenario/<scenario>/removed_log/10_feedthrough.removed
10_result/common/10_feedthrough.sdc
10_result/common/10_feedthrough_<stage>_<corner>.sdc
10_result/scenarios/<scenario>_feedthrough.sdc
10_result/scenarios/<scenario>_feedthrough_<stage>_<corner>.sdc
10_result/reports/feedthrough_check_report_<scenario>.txt
```

`10_extract_feedthrough.py` 应实现上述 edge-centric target runtime，并可保留 legacy cwd 路径兼容入口。target 模式通过 `--run-root` 使用固定的 00/10 required 路径和可选 01/03 diagnostic 路径；内部 `fti -> fto` pair/chain 不得作为 inventory、生成或 pending 消账依据。

legacy cwd 兼容模式默认使用共享契约的 `00_harden_port_inventory/connection_inventory.csv`、`00_harden_port_inventory/harden_sdc_manifest.csv`、`00_harden_port_inventory/pending/` 和 `00_harden_port_inventory/removed_log/`；legacy-only 调试可显式覆盖 cwd 输入/输出，但不得与 target 状态交叉读写。无论是否覆盖路径，都不得扫描 cwd 并按 `<inst>.sdc` 推断 manifest 内容；一次 legacy 运行只承载一个显式 scenario。

每次运行的 stdout、SDC header、workbook/inventory 和 report 至少记录：

```text
Author: Howard
Scenario: <command-line scenario>
Run completeness: complete|partial
Port accounting: enabled|disabled by explicit option
Connection inventory: <resolved path>
Harden SDC manifest: <resolved path>
```

这些 metadata 必须反映实际 resolved input 和选项；accounting disabled 时必须使用完整字面值 `Port accounting: disabled by explicit option`，不能只写 `disabled`。

## 9. 检查规则

以下情况应 error：

- target 省略 `--scenario`、使用任意 path override、跨 target/legacy 读写，或读取 fixed downstream contract 之外的 20 产物。
- 00 inventory 缺少/不支持 `schema_version`，或 `scenario_scope` 缺失、为空、非法、重复、非稳定排序。
- current-scenario manifest 缺列、scenario 不匹配、instance 重复、status 非法、`available` path 不唯一/不存在/不可读，或 `not_required` 没有 note basis。
- accounting enabled 时 pending 目录/manifest instance 文件缺失或不可读，存在非法 direction、非 canonical scalar/bit、range/wildcard/pattern、malformed line 或 duplicate；该检查即使没有 terminal row 也不能跳过。
- 已完成 01/04 ownership precedence 的 10 candidate 中，`fti_*` 不是 input、`fto_*` 不是 output，或 boundary 仍为 `inout`。
- 使 edge 归 10 的 `fti_*` / `fto_*` endpoint instance 不是 manifest 中的 harden。
- `connection_type` 为空或属于 00 schema 外字符串；合法的 `unknown` 虽不直接 error，但不得进入 terminal disposition、生成或消账。
- 归 10 的 edge 不存在唯一、bit-level 00 `connection_id`。
- 20 assembled ownership check 发现同一个 `connection_id` 同时被 10 和 20 拥有；该 error 由 20 读取 10 inventory 后执行，不由 10 读取未来 20 产物执行。
- `feedthrough_edge_id` 不唯一或指向多个 `connection_id`。
- `budget_scope != direct_edge` 却要求生成。
- active direct edge 缺少 canonical `src_soc_object` / `dst_soc_object`，或 object 与 `instance + canonical port` 不一致。
- 生成命令的 `-from/-to` 不是当前 inventory 行的 SoC-visible direct edge 两端。
- 生成或消账依据是内部 `fti/fto` pair，而不是 direct edge terminal disposition。
- 试图生成 `fti -> fto` harden 内部约束。
- 试图跨一个或多个 harden 内部段拼接普通 end-to-end budget。
- `route_to_30` / `pending` 行被 10 消账。
- required harden SDC missing，却把“未发现 evidence”作为终态依据。
- clock/pad edge 未先按 01/04 ownership 排除。
- approved/applied terminal row 的 validation/digest/review gate 不完整，`pending` 被 approved/applied，或 material refresh 后通过 force/bypass 沿用旧 approval。
- `emit_budget` 的 `tool_surface` 为空/非法、没有实际 max/min command、数值/basis 不完整，或不满足 `datapath_only=yes`。
- `no_soc_budget_required` 缺少 policy owner、reviewer、review date、匹配的 approved machine digest 或明确版本化 policy/basis，或 `budget_required/emit_max/emit_min` 不是显式 `no`。
- `route_to_30` 缺少 owner、reviewer、review date 或明确 exception/path-level basis。
- common 与当前 scenario 对同一 connection/view 形成冲突的 approved effect/command，却依赖 overlay 顺序覆盖。
- 10 试图重复删除已由 00/01/04 拥有的 canonical port，或 target previous-owner 检查读取其它 scenario/legacy/future-stage log。
- 合并多 bit SDC command 时包含未批准 bit、material policy 不一致的 bit、reverse/permutation/nonlinear mapping、非常量 offset，或使用会额外选择对象的 wildcard/range。
- required stdout/SDC/workbook/inventory/report metadata 缺失，或 accounting disabled 时没有记录完整的 `Port accounting: disabled by explicit option`。

以下情况应 warning/review：

- `connection_type` 为合法的 `unknown`，尚不能证明 01/04 ownership 已排除；该 edge 保持 `needs_review`，不得进入 terminal disposition。
- 集成表单中出现疑似 feedthrough boundary，但 port 未按 `fti_` / `fto_` 命名。
- `fti` / `fto` 找不到可选 pair，或 remainder/hop index 不一致；这只影响 chain report，不阻断明确的 direct edge。
- 同一 feedthrough boundary 出现 fanout、多重 edge，或 bit mapping 不是保持位序的常量 offset；必须逐个 `connection_id` 显示且不得做命令级 bus 合并。
- optional clock/relation diagnostic 缺失、unresolved、partial、stale、invalid 或 digest 不一致；仅记录 warning，不改变 10 physical budget 终态。
- 人工 `disposition_basis` 明确引用 clock period/clock-relative evidence，但对应 clock mapping/relation 与推导假设不一致。
- `through_collection` 或任何规则试图借助 pair/chain 穿越 harden 内部。

## 10. 与其它 Stage 的边界

- 01：clock port/clock connection 优先处理；10 按 00 canonical ownership 结果排除这些 edge。assembled clock inventory 对 10 只提供可选 corroboration/evidence annotation，不参与 physical max/min gate。
- 04：top pad/IO external environment 优先处理。
- 20：只处理未被 10 拥有的普通 functional direct edge；20 必须读取当前 scenario 的 10 inventory，按 `connection_id` 排除并执行 10/20 overlap error，禁止 end-to-end stitching。10 不读取 20 inventory。
- 30：处理 exception/override。feedthrough-related direct edge 只有在存在明确 exception/protocol evidence 并经 review 后才由 10 `route_to_30`；clock relation 本身不能触发 routing。30 引用 `related_10_feedthrough_edge_id` 并约束同一条 SoC-visible direct edge，同时直接从 03 获取 authoritative clock relation。
- harden owner：负责所有 harden 内部 `fti -> fto` timing arc、internal exception 和 signoff 约束。

## 11. 暂不处理

第一版不自动处理：

- 从 RTL/netlist 推断未出现在集成表单中的连接。
- 从 `fti/fto` 命名推断 harden 内部组合逻辑或 timing arc。
- 生成穿越 harden 内部的 end-to-end budget/exception。
- 自动把 optional pair/chain metadata 提升为 SDC rule。
- 经过 mux/isolation/case 条件后才成立、但集成表单未明确拆分的 mode-specific 连接。
