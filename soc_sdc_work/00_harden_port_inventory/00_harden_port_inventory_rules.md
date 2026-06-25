# 00_harden_port_inventory 规则说明

本文定义 SoC SDC flow 中 harden port pending list 的生成、消费和检查规则。

00 不是 SDC 文件。它维护两个基础视图：每个 harden/subsys instance 尚未被 SoC SDC flow 覆盖的 pending port 文本清单，以及 direct channel 使用的 bit-to-bit `connection_inventory.csv` 边表。后续 01/04/10/20/30 每完成一类约束，就从对应 harden 的 pending port 文件中删除已覆盖 port。最终剩下的行就是需要继续 review 的未约束 port。

## 1. 目标

00 的目标是把 harden port 覆盖情况和 bit-level 连接配对变成直观、可 diff、可自动检查的文本机制：

- 从集成表单生成每个 harden 的 pending port 文件。
- 从集成表单生成 direct bit-to-bit `connection_inventory.csv`。
- 每个 harden 一个文本文件，避免几千个 port 混在一个大表里。
- 被某个 SDC stage 覆盖后，从 pending 文件中删除对应 port。
- 最终通过 pending 文件剩余内容直接识别漏约束 port。
- 每个 stage 同时输出 removed log，记录本阶段删除了哪些 port 和删除原因。

## 2. 目录结构

建议目录如下：

```text
00_harden_port_inventory/
  pending/
    u_dpg.ports
    u_gms.ports
    u_mmn.ports
  removed_log/
    00_disposition.removed
    01_soc_clocks.removed
    04_soc_io_pads.removed
    10_feedthrough.removed
    20_harden_x_if.removed
    30_harden_to_harden_exception.removed
  connection_inventory.csv
  inventory_report.txt
```

`pending/*.ports` 是主审查入口，保持尽量简洁。

`removed_log/*.removed` 是追溯入口，避免误删后只能靠猜。

`connection_inventory.csv` 是 SoC 集成连接的 bit-to-bit 边表，是 direct channel 的连接真源。

## 3. Pending Port 文件格式

每个 harden instance 一个 `.ports` 文本文件。

第一版采用一行一个 **canonical port key**：

```text
input clk_i
input rst_n
input fti_0_mmn2gms_req_valid
output fto_0_mmn2gms_req_valid
output data_o
output ctrl_o[0]
output ctrl_o[1]
inout gpio0
```

规则：

- 第一列为方向：`input` / `output` / `inout`。
- 第二列为 harden/subsys canonical port key。
- scalar port 直接写 port 名，例如 `clk_i`。
- bus/vector port 必须展开成单 bit key，格式为 `port[index]`，例如 `ctrl_o[0]`、`ctrl_o[31]`。
- 文件按 direction + canonical port key 稳定排序，便于 git diff。
- 不在 pending 文件中放复杂状态列；pending 文件只表达“还没消账”。
- 机器可读 pending 不使用 `ctrl_o[31:0]`、`ctrl_o[*]` 或整 bus 行表达覆盖状态；这些紧凑写法只允许出现在人工 summary/report 中。
- 集成表单中的 range 连接必须在 00 阶段展开成 bit-to-bit 关系，并写入 `connection_inventory.csv`。例如 `u_a.ctrl_o[7:4] -> u_b.ctrl_i[3:0]` 必须展开成 4 条明确 edge；位宽不一致、方向不明确或 bit order 无法判定时为 error。
- 常量、tie-off、NC、mode inactive 等不生成 SDC 的 bit 仍先进入 pending，再由 `00_disposition` 按 exact bit key 消账。
- SDC/Tcl 中引用 bit port 时应使用 brace 保护，例如 `[get_pins {u_x/ctrl_o[3]}]`、`[get_ports {pad_gpio[0]}]`。
- 所有后续 stage 只能删除 exact canonical key。若 stage 只覆盖 bus 的一部分 bit，只能删除对应 bit 行；若它试图删除整 bus，必须报错。

## 4. Removed Log 格式

每个消费 stage 输出一个 removed log，例如：

```text
u_pll output core_clk_o covered_by=01_soc_clocks reason=generated_clock clock=u_pll_core_clk_o
u_iobuf input pad_i covered_by=04_soc_io_pads reason=pad_related soc_pad=PAD_GPIO0
u_dpg input fti_0_mmn2gms_req_valid covered_by=10_feedthrough reason=fti_fto_pair pair=fto_0_mmn2gms_req_valid
u_a output data_o[7] covered_by=20_harden_x_if reason=normal_channel_budget channel=CH_u_a_data_o_bit7__u_b_data_i_bit7
u_cfg input cfg_mode_i[0] covered_by=30_harden_to_harden_exception reason=false_path rule=EXC_CFG_001
u_scan input scan_en covered_by=00_disposition reason=no_constraint_required basis=func_case_analysis owner=dft reviewer=dft_owner review_date=2026-06-23
u_dbg input unused_i covered_by=00_disposition reason=no_connect basis=integration_nc_list owner=soc_integration reviewer=soc_owner review_date=2026-06-23
```

removed log 只用于审查和 debug，不作为下一阶段的输入。

## 5. Connection Inventory 格式

`pending/*.ports` 只记录单边 port key，不能表达 `src bit -> dst bit` 的配对。为了避免 20/30 重新猜 bus/range bit order，00 必须从集成表单同时生成 `connection_inventory.csv`。

### 5.1 作用

`connection_inventory.csv` 是 direct SoC channel 的单一真源。例如：

```text
u_a.ctrl_o[7:4] -> u_b.ctrl_i[3:0]
```

必须展开为：

```text
u_a output ctrl_o[7] -> u_b input ctrl_i[3]
u_a output ctrl_o[6] -> u_b input ctrl_i[2]
u_a output ctrl_o[5] -> u_b input ctrl_i[1]
u_a output ctrl_o[4] -> u_b input ctrl_i[0]
```

20/30 不应从原始集成表单再次展开 range，也不应自行判断 MSB/LSB 配对。若 `connection_inventory.csv` 缺失或某条 direct channel 缺少对应 edge，20/30 应报错或保持 `needs_review`，不能自行补猜。

### 5.2 建议字段

```text
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

字段说明：

- `connection_id` 必须稳定且 bit-specific，例如 `CONN_u_a_ctrl_o_bit7__u_b_ctrl_i_bit3`。
- `connection_type` 建议复用后续 stage 的分类：`harden_to_harden`、`fabric_to_harden`、`harden_to_fabric`、`top_pad_to_harden`、`harden_to_top_pad`、`pad_to_pad`、`clock_connection`、`feedthrough_candidate`、`constant_tie`、`unknown`。
- `src_endpoint_key` / `dst_endpoint_key` 使用 `inst:direction:port[index]` 或项目固定格式，必须能回到 `pending/<inst>.ports` 中的 canonical key。
- `src_port` / `dst_port` 使用 00 canonical port key；scalar 不带 `[index]`。
- `src_soc_object` / `dst_soc_object` 是 SoC SDC 可用对象，例如 `u_a/ctrl_o[7]`；生成 SDC 时仍应 brace 保护。
- `range_source_expr` / `range_sink_expr` 保留原始集成表单 range，便于审查 `7:4 -> 3:0` 这类重编号。
- `bit_pair_order` 记录展开规则，例如 `msb_to_msb`、`lsb_to_lsb`、`explicit_map`；不明确时 `validation_status` 不能为 `matched`。
- `owner_hint` 只给下游分类参考，不替代 stage ownership 检查。

### 5.3 与其它 inventory 的关系

`connection_inventory.csv` 记录 SoC direct edge。10 的 `feedthrough_inventory.csv` 记录某个 feedthrough harden 内部的 `fti -> fto` segment，两者不是替代关系。

典型用法：

- 10 用 `connection_inventory.csv` 找到进入/离开 feedthrough harden 的 bit edge，再结合 `fti_*` / `fto_*` 命名生成 `feedthrough_inventory.csv`。
- 20 用 `connection_inventory.csv` 中 `harden_to_harden` / `fabric_to_harden` / `harden_to_fabric` direct edge 建立 normal channel。
- 30 用 `connection_inventory.csv` 或 20 channel inventory 锚定 exception endpoint；经过 feedthrough 时额外引用 10 `feedthrough_inventory.csv`。

## 6. 终结态和 ownership

### 6.1 `00_disposition` 人工终结

有些 harden port 合理地不需要生成任何 SoC SDC 约束，但仍必须从 pending list 中消账。这类 port 不应被迫塞进 20 或 30。

00 提供独立的人工终结机制：`00_disposition`。它不是 SDC stage，只负责把“确认无需约束”的 port 从 pending 中删除，并写入 `removed_log/00_disposition.removed`。

允许的 disposition 建议包括：

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

`not_applicable` 在 00 中只用于从未进入 20/30 表单的 port。若该 port 已经进入 20 或 30 review，并由对应 stage 得出 `not_applicable` 结论，应由 20/30 自己删除 pending 并写本 stage 的 removed log，避免同一个 reason 在多个 ownership 层级混用。

典型场景：

- func-only scenario 下被 `set_case_analysis` 固定掉的 `scan_en` / `test_mode` / `mbist_en`。
- tie-off / NC / 未使用 port。
- 只作为 mode strap、debug strap、configuration static signal，且项目确认当前 run 不需要 timing constraint。
- clock relationship 已由 03 处理，但 port 本身不需要 port-level budget 或 exception 的情况。

每条 `00_disposition` 删除都必须带：

```text
instance
direction
port
reason
owner
basis
reviewer 或 review_date
expiry_or_review_date  # 仅 waiver 必填
```

`waived` 表示已知风险或临时放行，必须有复审日期；`no_constraint_required` 表示方法学上确认无需约束，不应滥用为清空 pending 的快捷方式。

### 6.2 Stage ownership 优先级

每个 port 只能由一个最终 owner 消账。若多个 stage 都可能处理同一 port，按以下顺序判定归属：

```text
01_soc_clocks
04_soc_io_pads
10_feedthrough
20_harden_x_if
30_harden_to_harden_exception
00_disposition
```

解释：

- clock port 优先归 01。
- top pad / IO buffer 相关 port 优先归 04。
- 符合 `fti_*` / `fto_*` 或集成表单 feedthrough 结构的 port 优先归 10。
- 普通 harden/subsys interface timing budget 归 20。
- 只有确有 exception / override 语义的 path endpoint 才归 30。
- 以上都不适用、且 reviewer 明确确认无需约束时，才归 00_disposition。

如果低优先级 stage 试图删除高优先级 stage 应拥有的 port，脚本应阻断并报告建议 owner。若项目确实需要覆盖默认归属，必须提供 `owner_override_basis`，并在 removed log 中记录。

## 7. Stage 消费规则

所有 `00_disposition` 删除也按 canonical key 生效。对于 bus 中只有部分 bit 无需约束的情况，只删除这些 bit；其余 bit 必须继续留在 pending 或由其它 stage 消账。

### 7.1 01_soc_clocks

01 处理 harden clock port。

可从 pending 中删除：

- 被提升为 SoC top/input clock 的 harden input clock port。
- 被识别为 upstream clock sink、且 01 已完成合法性检查的 harden input clock port。
- 被显式生成 output clock / forwarded generated clock 的 harden output clock port。

01 只能删除 clock 相关 canonical key，不能删除普通 data/control/reset port。若 clock 是 vector output/input，每个被创建 clock object 的 bit 独立删除，例如 `clk_o[0]` 与 `clk_o[1]` 必须分别有 clock 记录和 removed log。

### 7.2 02/03 不直接消账

02 和 03 不直接删除任何 harden port：

- 02 只处理 clock timing budget，例如 latency / uncertainty / transition / propagated / derate。
- 03 只处理 clock relationship，例如 `asynchronous` / `logically_exclusive` / `physically_exclusive`。

如果某个 data/reset/control port 的唯一相关信息是 03 clock group，不能因此直接从 pending 删除。该 port 仍必须走 20、30 或 `00_disposition`，否则会留在 pending 中作为待审项。

### 7.3 04_soc_io_pads

04 处理 SoC top pad / IO buffer / pad-related port。

可从 pending 中删除：

- 集成表单确认连接到 SoC top pad 的 harden port。
- 经 04 生成或确认的 pad-related input/output delay、load、driving、transition、pad false path、pad synthesis-only protection 所覆盖的 port。

04 消费也按 canonical bit key 进行；bus pad 或 GPIO 若不同 bit 方向/约束不同，必须逐 bit 建模并逐 bit 删除。若某 port 只是物理连接到 pad，但 04 表单仍缺少必要 timing/electrical 约束，不能删除；应保留在 pending 或进入 warning。

### 7.4 10_feedthrough

10 处理项目命名规则明确的 harden feedthrough port。

可从 pending 中删除：

- 同一 harden 内按 `(index, base, bit_index)` 成功配对的 `fti_*` / `fto_*` canonical bit key。
- 多 hop 链路中 index 顺序与集成表单连接顺序一致的 feedthrough port。
- 已由 10 生成 feedthrough inventory/SDC 或明确记录为结构性穿通段的 port。

10 删除表示 feedthrough segment 已按 bit 建模，不代表 end-to-end timing budget 或 exception 已完成。若端到端普通 timing 仍需 budget，应继续由 20 处理；若端到端为 exception，应继续由 30 处理。

### 7.5 20_harden_x_if

20 处理普通 harden/subsys interface timing budget。

可从 pending 中删除：

- 已生成 reviewed normal channel `set_max_delay` / `set_min_delay` 的 source/destination port。
- 已确认由可见 netlist/timing model 常规 STA 覆盖、且不需要额外 20 budget 的 channel port。
- 已被 20 表单明确标记为 not_applicable 并有依据的普通 interface port。

20 只删除 channel 两端对应的 canonical bit key。一个 bus fanout/range 展开成多条 bit channel；某些 bit 有 20 budget 不代表整个 bus 已消账。20 channel 的 src/dst bit 配对必须来自 `connection_inventory.csv` 或 10 feedthrough 还原后的 edge，不能由 20 自行重新展开 range。20 不能删除 exception-only path，除非该 path 同时有普通 timing 覆盖依据。

### 7.6 30_harden_to_harden_exception

30 处理 harden/subsys 间 path-level exception / override。

可从 pending 中删除：

- 已生成 approved false path / multicycle / exception max-min override 的端点 port。
- 已有明确 waiver 或 not_applicable 结论、且 30 report 中记录依据的 port。

30 删除必须有 rule id 或 waiver id，并按 exact endpoint bit 删除。direct path 的 src/dst bit 配对必须来自 `connection_inventory.csv` 或 20 channel inventory；经过 feedthrough 的 path 还必须引用 10 bit-level `feedthrough_id`。不能因为“没有 timing”就删除。

## 8. 检查规则

### 8.1 Error

以下情况应阻断更新 pending list：

- 集成表单中的 harden instance 没有对应 `.ports` 文件。
- `.ports` 文件存在重复 port 行。
- pending 中出现非 canonical bus/range key，例如 `data[7:0]`、`data[*]` 或同时存在 `data` 与 `data[0]`。
- 集成表单 range 连接无法展开为明确 bit-to-bit 关系，或展开后 bit 宽/顺序不一致。
- `connection_inventory.csv` 缺失、存在重复 `connection_id`，或同一 direct bit pair 产生多个冲突 edge。
- `connection_inventory.csv` 中的 endpoint 无法回到对应 instance 的 pending canonical key。
- `connection_inventory.csv` 的 `range_source_expr` / `range_sink_expr` 与展开后的 bit pair 不一致。
- stage 试图删除不存在于 pending 的 port，且没有 previous_removed 记录说明它已被早期 stage 消费。
- stage 试图删除方向不匹配的 port。
- 01/04/10/20/30 对同一 port 给出互相矛盾的删除原因。
- 同一 port 同时命中多个 owner，且没有按 ownership 优先级裁决。
- stage 试图用整 bus、range 或 wildcard 删除 pending，而不是删除 exact canonical bit key。
- `00_disposition` 缺少 reason / owner / basis，或 reviewer 与 review_date 均为空。
- `waived` 缺少 expiry_or_review_date，或 expiry_or_review_date 已过期。
- 脚本发现 pending 文件被人工改坏，无法解析。

### 8.2 Warning

以下情况应 warning：

- 某 harden pending 文件剩余 port 数量超过项目阈值。
- port 名疑似 clock/pad/feedthrough，但直到后续 stage 仍未被消费。
- `fti_*` / `fto_*` 只剩一边，另一边已删除或不存在。
- 同一 channel 的一端 port 已消账，另一端仍 pending。
- `connection_inventory.csv` 中存在 `connection_type = unknown` 或 `validation_status != matched` 的 edge。
- removed log 中记录的 stage 与实际生成 SDC 不一致。
- 某 port 只由 03 clock group 相关信息解释，但尚未进入 20/30/00_disposition。
- report 中为了可读性合并显示 bus，但没有保留对应 bit-level removed log 明细。

## 9. 运行模型

00 pending list 和 `connection_inventory.csv` 应可从集成表单重新生成。

推荐流程：

```text
1. 从集成表单生成 pending/*.ports。
2. 从集成表单生成 connection_inventory.csv。
3. 01 运行后更新 pending，并写 01 removed log。
4. 04 运行后更新 pending，并写 04 removed log。
5. 10 运行后读取 connection_inventory.csv，生成 feedthrough inventory/SDC，更新 pending，并写 10 removed log。
6. 20 运行后读取 connection_inventory.csv 和 feedthrough inventory，更新 pending，并写 20 removed log。
7. 30 运行后读取 connection_inventory.csv、20 channel inventory 和 10 feedthrough inventory，更新 pending，并写 30 removed log。
8. 对合理无需约束的剩余 port 做 00_disposition review，并写 00_disposition removed log。
9. 最终检查 pending/*.ports 剩余内容。
```

pending 文件是 node review 主视图；`connection_inventory.csv` 是 edge review 主视图；removed log 是追溯视图。

## 10. 暂不处理

第一版暂不做：

- 自动从 RTL 推断所有未出现在集成表单中的 harden port。
- 自动判断某个 data/control port 应归 20 还是 30。
- 自动合并 bus bit 成紧凑 bus 表达。
- 自动修复人工编辑导致的 pending 文件冲突。
