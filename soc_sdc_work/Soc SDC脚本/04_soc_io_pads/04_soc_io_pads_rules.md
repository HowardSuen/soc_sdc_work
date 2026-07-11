# 04_soc_io_pads.sdc Rules

本文档记录 `04_soc_io_pads.sdc` 的规则边界、输入来源、建议表单格式和后续脚本机制。

## 1. 目标

`04_soc_io_pads.sdc` 定义 SoC 顶层 IO/pad timing environment。

04 不是单纯搬运下级 iobuffer/module SDC，也不是只维护人工填写的 IO budget。04 的目标是：

- 从集成表单识别 SoC pad 与下级 module/subsys port 的连接关系。
- 从下级 iobuffer/module SDC 中提取已有的 pad 相关约束。
- 把下级约束提升到 SoC 层级对象。
- 通过表单记录约束来源、适用范围、review 结论和最终生成状态。
- 对缺失、冲突、不适用于 SoC 的 IO 约束给出检查报告。
- 生成 `common/04_soc_io_pads.sdc` 以及后续可能的 scenario 专属 IO SDC。

04 依赖：

- 集成表单中的 SoC 架构连接信息。
- 下级 iobuffer/module SDC。
- `01_soc_clocks.sdc` 中已经创建好的 clock object，包括 IO delay 使用的 virtual clock、real clock、generated/forwarded clock。

04 不创建 clock。所有 `create_clock` / `create_generated_clock`，包括 virtual clock，都归属 `01_soc_clocks.sdc`。

## 2. 放什么

04 可以放：

- SoC 顶层 pad/port 分组。
- 固定方向、所有相关 scenario 都成立的 `set_input_delay` / `set_output_delay`。
- input pad 的外部驱动模型，例如 `set_driving_cell` / `set_drive`。
- input pad 的输入 slew，例如 `set_input_transition`。
- output pad 的外部负载，例如 `set_load`。
- 作用于 top IO port 的 IO design rule，例如 `set_max_transition` / `set_max_capacitance`。
- 与 pad 直接相关、经 review 后确认适用于 SoC 的 `set_false_path`。
- 与 pad net 直接相关、经 review 后确认适用于综合的 `set_dont_touch_network`。
- GPIO/inout pad 的方向依赖记录，为 `gpio_in` / `gpio_out` 拆分做准备。

04 不放：

- `create_clock` / `create_generated_clock`。
- clock timing budget，例如 `set_clock_uncertainty` / `set_clock_latency` / `set_clock_transition`。
- clock group。
- harden 内部接口约束。
- harden-to-harden path exception。
- 与 pad 无关的普通内部 false path / multicycle / max delay。
- 全芯片内部 design rule 约束；这类后续如有需要可单独规划。

## 3. 输入来源

### 3.1 集成表单

集成表单用于确定 SoC 层级的 pad 连接关系，例如：

```text
soc_top_port <-> subsys_instance/module_port
```

脚本应从集成表单获取：

- SoC 下有哪些 subsys/module instance。
- 哪些下级 port 是 SoC pad 相关 port。
- SoC top port 名称。
- 下级 instance path。
- module port 名称。
- pad 方向或方向线索。
- inout/GPIO 是否需要 scenario 拆分。

默认自动扫描的 port workbook 应限制为 `port_*.xlsx` 或 `ports_*.xlsx` 这类命名，避免共享目录中的 02/03/04/20 review workbook 被误读为 port 表；其它命名需通过后续显式选项接入。

04 的 coverage 和 pending 消账必须使用 `00_harden_port_inventory` 的 canonical bit key。若 SoC pad bus 或下级 module bus 存在 bit-level 连接，集成表单中的 range 必须先展开为 bit-to-bit 映射，例如 `soc_pad_gpio[3] <-> u_iobuf/gpio_i[3]`。生成 SDC 时可以把相同约束的多个 bit 合并成 port list，但表单覆盖、conflict check、removed log 必须保留 per-bit 明细。脚本解析下级 SDC collection 时必须支持带 bus bit 的 Tcl object，例如 `[get_ports {dq_i[0]}]`，不能被 bit select 中的 `]` 截断。

第一版 04 不在本阶段重新猜测 bus/range bit order。集成表单中的 harden port 和 SoC top pad 必须已经是 scalar 或 exact bit key，例如 `dq_i` 或 `dq_i[0]`。若出现 `dq_i[7:0]`、`dq_i[*]`、或 `dq_i` 同时标注 `width > 1`，脚本应报 error，要求 00/集成阶段先展开。

### 3.2 下级 iobuffer/module SDC

下级 SDC 中可能已经包含 pad 相关约束。04 脚本不能默认这些约束缺失。

如果下级 SDC 中存在以下命令，应先提取到 04 表单中作为 candidate：

```tcl
set_input_delay
set_output_delay
set_load
set_driving_cell
set_drive
set_input_transition
set_false_path
set_dont_touch_network
set_max_transition
set_max_capacitance
```

提取时必须保留原始来源：

- 原始 SDC 文件。
- 原始行号。
- 原始命令。
- 原始 target object。
- 提升后的 SoC target object。

下级 SDC 中的约束可能有三种情况：

- 已经是 SoC pad environment，可提升后复用。
- 是 block signoff 环境，不一定适用于 SoC，需要 review。
- 是内部实现保护或临时 exception，不应进入 SoC 04。

因此，从下级 SDC 提取到的约束默认只作为候选记录；是否最终生成，由表单中的 `apply` / `review_status` 决定。

### 3.3 人工 IO 约束表单

人工表单不是只补缺项，而是 04 的统一约束归集表。

表单中同时记录：

- 从下级 SDC 提取到的已有约束。
- 人工新增或修正的约束。
- 明确不需要的 `NA` 项。
- 被 review 后拒绝生成的约束。

只有扫描完相关下级 SDC 后仍未找到的必要约束，才标记为缺失，等待人工填写或明确标记 `NA`。

## 4. SoC 层级提升规则

下级 SDC 中的 object 不能直接原样进入 SoC SDC，必须根据集成表单提升到 SoC 视角。

### 4.1 SoC top pad port

如果下级 module port 对应 SoC top pad port，则外部 IO environment 应优先作用在 SoC top port 上：

```tcl
set_load 0.05 [get_ports {soc_pad_uart0_sout}]
set_input_transition 0.20 [get_ports {soc_pad_uart0_sin}]
```

### 4.2 下级 instance pin

如果约束描述的是 SoC 内部 module boundary 的一侧，需要提升为 instance pin：

```tcl
set_false_path -from [get_pins {u_iobuf/uart0_sout}] \
               -to   [get_ports {soc_pad_uart0_sout}]
```

具体使用 `get_ports` 还是 `get_pins`，必须由集成表单中的连接关系决定，不能只靠命令文本猜测。

### 4.3 Net 约束

`set_dont_touch_network [get_nets ...]` 需要特别谨慎。

下级 module 内的 net name 在 SoC 层级未必稳定，脚本应：

- 尝试根据连接关系找到 SoC 层级 net。
- 如果无法稳定解析，保留记录但不生成，报告给 reviewer。
- 区分综合使用和 STA 使用；`set_dont_touch_network` 主要服务综合结构保护，不是 timing environment。
- 在 STA-only 输出中默认不生成 `set_dont_touch_network`。
- 未来如果综合结构保护约束变多，可以把这类命令从 04 拆到独立 synthesis constraint 文件；当前放入 04 是为了 SoC 综合/STA 共用规划阶段便于归集 review。

## 5. IO 方向和约束类型

### 5.1 Input pad

input pad 可以使用：

```tcl
set_input_delay
set_driving_cell
set_drive
set_input_transition
```

说明：

- `set_input_delay` 描述外部 launch/capture timing 与 SoC 接收端之间的时序关系。
- `set_driving_cell` / `set_drive` 描述外部驱动模型。
- `set_input_transition` 直接描述输入 slew。
- `set_driving_cell` 和 `set_input_transition` 一般二选一；若 flow 同时使用，必须在表单中明确原因。
- `set_driving_cell` 不建议只用自由文本描述，表单应结构化记录 lib cell、pin、from pin 等关键信息；如果下级 SDC 命令过于复杂，允许按原始命令透传，但必须标记并进入 review。

### 5.2 Output pad

output pad 可以使用：

```tcl
set_output_delay
set_load
```

说明：

- `set_output_delay` 描述 SoC 输出到外部接收端之间的时序要求。
- `set_load` 描述外部负载，例如封装、PCB trace、接收端输入电容。
- 即使某些 async/untimed output 使用 `set_false_path` 不做常规 setup/hold，`set_load` 仍可能影响 slew、cap、功耗和综合优化质量。

### 5.3 Inout / GPIO pad

inout/GPIO pad 的方向通常依赖 scenario。

建议拆分：

```text
scenarios/gpio_in.sdc
scenarios/gpio_out.sdc
```

规则：

- `gpio_in` 场景使用 input timing 约束，例如 input delay。
- `gpio_out` 场景使用 output timing 约束，例如 output delay。
- `set_load`、`set_input_transition`、`set_driving_cell` 等电气环境不完全等同于 input/output timing delay。某些物理负载、板级 cap 或输入 slew 在不同方向场景中仍有意义，可以放 common 或 view-specific 04，但必须在表单中说明适用方向和依据。
- 如果方向由 `set_case_analysis` 或 mode select 决定，该 case analysis 应在 scenario pre-setup 阶段注入。
- 不要把方向相关的 input/output 约束都放进 common。

## 6. Timed / Async / Untimed 分类

每个 pad/interface 应在表单中明确 timing classification。

建议取值：

```text
timed
async
untimed
config
```

### 6.1 `timed`

需要 STA 分析的外部接口，例如同步 SPI、SDIO、DDR-like interface 或其它有明确 timing budget 的接口。

要求：

- 应有 `set_input_delay` 或 `set_output_delay`。
- delay 命令引用的 clock 必须在 01 中存在。
- 不应被下级 SDC 中的 broad `set_false_path` 静默切掉。
- 如果下级 SDC 同时给出 false path 和 delay，必须报冲突，人工确认。

### 6.2 `async`

异步接口，例如常见 UART、异步 GPIO、外部中断等。

规则：

- 可以使用 `set_false_path` 切断普通同步 STA。
- 可以没有 input/output delay，但必须在表单中明确 `timing_class = async` 并写明依据。
- 仍建议根据综合/DRC 需要填写 input transition、driving model 或 output load；若不需要，标记 `NA`。

### 6.3 `untimed`

不参与 STA timing 的结构性 pad、模拟 pad、strap、test-only pad 等。

规则：

- 可以没有 input/output delay。
- 必须有明确用途说明。
- 若保留 `set_false_path`，必须说明适用范围，不能作为清 timing violation 的临时手段。

### 6.4 `config`

配置类 pad 或控制信号。

规则：

- 若在某 scenario 中被固定，应由 scenario pre-setup 的 `set_case_analysis` 表达。
- 若只是异步配置输入，可按 `async` 或 `untimed` 处理，但必须写明依据。

## 7. Common 与 Scenario

04 采用 common + scenario 叠加模型。

输出建议：

```text
common/04_soc_io_pads.sdc
scenarios/<scenario>_io_pads.sdc
```

归属规则：

- `scenario = common`：只放所有相关 mode 都成立的 IO/pad 约束。
- `scenario != common`：只放该 scenario 下才成立的 IO/pad 约束。
- GPIO/inout 方向相关约束应下沉到 `gpio_in` / `gpio_out` 等 scenario。
- scan/mbist/test 专属 IO 约束应下沉到对应 scenario。
- 如果某条 common IO 约束在某个 scenario 下不成立，说明它不应在 common。

04 不采用 02 的 resolved-single-file 模型；scenario 04 文件用于追加 scenario 专属约束，不应依赖后 source 覆盖 common 中的同一对象。

### 7.1 Stage / Corner / View 维度

04 需要显式保留 stage/corner 维度，但不要求所有 IO 约束都强制按 stage/corner 拆分。

原因：

- `set_input_delay` / `set_output_delay` 多数来自板级 timing budget 或接口协议，通常可以视为 corner-independent。
- `set_load`、`set_driving_cell`、`set_drive`、`set_input_transition`、`set_max_transition`、`set_max_capacitance` 属于电气/DRC 环境，在 signoff MMMC 下可能随 PVT/corner、library view 或综合/STA stage 变化。
- SDC 本身没有 corner 条件化能力；如果同一 scenario 下同一 pad 的电气约束在不同 corner 有不同取值，不能平铺到同一个 04 SDC 文件中。

建议第一版采用两类输出：

```text
View-independent:
  common/04_soc_io_pads.sdc
  scenarios/<scenario>_io_pads.sdc

View-specific, when needed:
  common/04_soc_io_pads_<stage>_<corner>.sdc
  scenarios/<scenario>_io_pads_<stage>_<corner>.sdc
```

归属规则：

- 板级 delay 若项目确认 corner/stage 无关，可放入 view-independent 04。
- 电气类约束若项目确认所有 view 共用，也可以放入 view-independent 04，但必须在表单中显式标记 `stage = all`、`corner = all` 或等价取值。
- 电气类约束若随 stage/corner/view 变化，必须输出到带 `<stage>_<corner>` 的 04 文件。
- 同一个 assembled view 中不能同时存在 view-independent 和 view-specific 的同类冲突约束；必须通过表单裁决，不能靠 source 顺序覆盖。

Stage 5 装配时，建议按当前 scenario/stage/corner 选择性 source：

```tcl
source common/04_soc_io_pads.sdc
source common/04_soc_io_pads_<stage>_<corner>.sdc          ;# if exists
source scenarios/<scenario>_io_pads.sdc                    ;# if exists
source scenarios/<scenario>_io_pads_<stage>_<corner>.sdc    ;# if exists
```

### 7.2 Assembled-view 检查

04 虽然采用 common + scenario 叠加模型，但每个具体 STA/综合 view 都必须形成一个可检查的 assembled view：

```text
assembled_04_view = common rows
                  + common stage/corner rows
                  + current scenario rows
                  + current scenario stage/corner rows
```

脚本必须按 `scenario + stage + corner` 建立 assembled view，并做跨层冲突和覆盖检查。

以下情况不能静默通过：

- common 与 scenario 对同一 pad、同一 constraint_type 生成互相冲突的 approved 约束。
- view-independent 与 view-specific 对同一 pad、同一 constraint_type 生成互相冲突的 approved 约束。
- scenario 约束试图靠后 source 覆盖 common 约束。
- 同一个 pad 的 timed delay 与 false path 在 assembled view 中同时生效，且没有显式裁决。
- `apply = yes` 且 `review_status = approved` 的当前输出行必须能实际 emit 至少一条 SDC 命令；例如 `false_path` 缺少可透传的 `rewritten_command` / `original_command`、或 `set_load` 缺少 value 时，应报 error，不能静默跳过。

coverage report 也应按 assembled view 输出，而不是只基于静态 pad inventory。

### 7.3 Pending 消账

04 完成生成后可以从 `00_harden_port_inventory/pending/*.ports` 删除已被 04 覆盖的 pad-related harden port，并写入：

```text
00_harden_port_inventory/removed_log/04_soc_io_pads.removed
```

脚本默认可提供：

```text
--pending-root 00_harden_port_inventory
--no-update-pending
```

删除规则：

- 只删除 assembled view 中已有 approved 04 记录的 pad 对应 harden port，或有 approved `source_type = na` 明确说明的 pad。
- 纯粹出现在 `pad_inventory`、但缺少必要 timing/electrical/NA review 记录的 port 不能删除。
- 删除必须使用 exact canonical key，例如 `input dq_i[0]`；不能用整 bus、range 或 pattern 删除。
- 若 port 已被更早 stage 删除，脚本可通过 previous removed log 豁免重复删除；若既不在 pending、也没有 previous removed 记录，应报 error。

## 8. 建议表单

建议第一版使用一个 workbook：

```text
04_soc_io_pads.xlsx
```

建议包含以下 sheet：

```text
io_constraints
pad_inventory
extraction_log
```

第一版脚本可以强制支持 `io_constraints`，其它 sheet 作为 review 辅助。

### 8.1 Sheet: `io_constraints`

一行描述一条候选或最终 IO/pad 约束。

建议字段：

```text
scenario
stage
corner
pad_name
soc_object
subsys_instance
subsys_port
direction
timing_class
constraint_type
clock_name
value
min_value
max_value
rise_value
fall_value
delay_edge
delay_polarity
add_delay
drive_lib_cell
drive_pin
drive_from_pin
drive_input_transition_rise
drive_input_transition_fall
object_granularity
unit_time
unit_cap
extra_options
source_type
source_sdc_file
source_line
source_digest
extraction_time
original_command
original_object
apply
review_status
owner
basis
note
```

字段含义：

```text
scenario          common / func / scan / mbist / gpio_in / gpio_out
stage             all / synth / prects / postcts / postroute；view-independent 行建议填 all
corner            all 或项目 corner/view 名，例如 ss_125 / ff_m40；view-independent 行建议填 all
pad_name          稳定 pad 名，建议使用 SoC top pad 名或项目 pad ID
soc_object        生成 SDC 时使用的 SoC 层级 object，例如 get_ports/get_pins 的 object 名
subsys_instance   下级 subsys/module instance path
subsys_port       下级 module canonical port key；bus bit 使用 port[index]
direction         input / output / inout / unknown
timing_class      timed / async / untimed / config
constraint_type   input_delay / output_delay / load / driving_cell / drive / input_transition / false_path / dont_touch_network / max_transition / max_capacitance
clock_name        约束引用的 clock；必须引用 01 已创建的 clock，非 clock 约束可为空；不限 virtual clock
value             单值约束，例如 load、input_transition、drive
min_value         min delay / min transition 等
max_value         max delay / max transition 等
rise_value        rise 数据边沿特定值
fall_value        fall 数据边沿特定值
delay_edge        data_rise / data_fall / both；用于 input/output delay 的 -rise / -fall
delay_polarity    clock_rise / clock_fall；clock_fall 生成 -clock_fall
add_delay         yes/no；yes 时生成 -add_delay
drive_lib_cell    set_driving_cell 使用的 -lib_cell
drive_pin         set_driving_cell 使用的 -pin
drive_from_pin    set_driving_cell 使用的 -from_pin
drive_input_transition_rise  set_driving_cell 可选输入 rise transition
drive_input_transition_fall  set_driving_cell 可选输入 fall transition
object_granularity  single_pad / port_list / pattern；表单建议 single_pad，生成时可合并
unit_time         原始约束时间单位，例如 ns；用于检查与 SoC flow 单位一致
unit_cap          原始约束电容单位，例如 pF；用于检查与 SoC flow 单位一致
extra_options     只放暂未结构化支持的额外 SDC 选项；不能承载已定义字段的语义
source_type       extracted / manual / na
source_sdc_file   从下级 SDC 提取时的原始文件
source_line       从下级 SDC 提取时的原始行号
source_digest     原始 SDC 文件 hash/digest；用于判断重抽后记录是否失效
extraction_time   提取时间戳
original_command  原始 SDC 命令文本
original_object   原始命令中的 target/source object
apply             yes / no
review_status     pending / approved / rejected
owner             约束 owner 或确认人
basis             约束依据，例如 IO spec、board spec、subsys owner review、CDC/STA methodology
note              人工备注
```

### 8.2 Sheet: `pad_inventory`

记录从集成表单推导出的 pad 清单。

建议字段：

```text
pad_name
soc_top_port
subsys_instance
subsys_port
direction_from_integration
is_gpio_or_inout
related_scenarios
note
```

该 sheet 用于检查哪些 SoC pad 已有约束、哪些 pad 完全没有记录。

### 8.3 Sheet: `extraction_log`

记录脚本从下级 SDC 中提取到的原始命令和解析状态。

建议字段：

```text
source_sdc_file
source_line
command_type
original_command
parse_status
mapped_soc_object
source_digest
extraction_time
message
```

该 sheet 用于 debug 和人工追溯，不直接生成 SDC。

## 9. 生成规则

脚本生成 SDC 时只使用：

- `apply = yes`
- `review_status = approved`
- `source_type != na`

如果项目希望 draft 阶段允许 `pending` 行生成，必须通过脚本选项显式打开，不能作为默认行为。

生成时先按当前目标文件筛选：

- view-independent 文件只生成 `stage = all` 且 `corner = all` 的行。
- view-specific 文件只生成当前 `stage + corner` 的行。
- scenario 文件只生成对应 scenario 的行。
- `scenario = common` 只输出到 `common/`。
- `scenario != common` 只输出到 `scenarios/`。

### 9.1 数值字段优先级

生成器必须按以下规则解释数值字段：

- 对 delay 类约束，`min_value` / `max_value` 优先于 `value`。
- 如果 `min_value` 非空，生成一条 `-min` delay。
- 如果 `max_value` 非空，生成一条 `-max` delay。
- 如果 `min_value` 和 `max_value` 都为空、`value` 非空，生成不带 `-min/-max` 的单值命令；是否允许该用法由项目 flow 决定，默认 warning。
- `value` 不应与 `min_value` / `max_value` 同时填写；同时填写时应 warning 或 error。
- `rise_value` / `fall_value` 用于 data edge 特定值。若填写 rise/fall，应结合 `delay_edge` 生成 `-rise` / `-fall` 命令；不能再把同一语义写进 `extra_options`。
- `rise_value` / `fall_value` 不应与 `value` / `min_value` / `max_value` 在同一行混填；需要同时表达 rise/fall 和 min/max 时，应拆成多行。

### 9.2 多边沿 / source-synchronous delay

真实 source-synchronous 或 DDR-like 接口允许同一 pad 多行表达不同边沿和 min/max：

```text
pad_name | constraint_type | clock_name | delay_edge | delay_polarity | add_delay | min_value | max_value
dq0      | input_delay     | dqs_clk    | data_rise  | clock_rise     | no        | 0.10      |
dq0      | input_delay     | dqs_clk    | data_rise  | clock_rise     | yes       |           | 0.80
dq0      | input_delay     | dqs_clk    | data_fall  | clock_fall     | yes       | 0.12      |
dq0      | input_delay     | dqs_clk    | data_fall  | clock_fall     | yes       |           | 0.85
```

生成时：

- `delay_edge = data_rise` 生成 `-rise`。
- `delay_edge = data_fall` 生成 `-fall`。
- `delay_edge = both` 或空值不生成 data edge option。
- `delay_polarity = clock_fall` 生成 `-clock_fall`。
- 对每个 `(pad_name, constraint_type, clock_name)` emit group，第一条实际生成的 delay 命令必须作为 base delay，不带 `-add_delay`；之后所有 delay 命令都必须带 `-add_delay`。
- 如果一行会生成多条 delay 命令，例如同时填写 `rise_value` 和 `fall_value`，或同时填写 `min_value` 和 `max_value`，则该行内也按命令级处理：该 group 的第一条命令不带 `-add_delay`，同一行的后续命令强制带 `-add_delay`。
- 如果表单中该 group 的所有行都填了 `add_delay = yes`，生成器应把第一条实际 emit 命令作为 base delay，不带 `-add_delay`，并在 report 中 warning。
- 如果表单中多条行都填了 `add_delay = no`，生成器应报 warning 或 error，要求 reviewer 明确哪一条是 base delay。
- 同一 pad 上多条 delay 行是合法表达，不应被当成重复冲突；冲突判断应把 `constraint_type + clock_name + min/max + delay_edge + delay_polarity + add_delay` 一起纳入 key。

### 9.3 `set_driving_cell`

`set_driving_cell` 应优先由结构化字段生成：

```tcl
set_driving_cell -lib_cell <drive_lib_cell> \
                 -pin <drive_pin> \
                 -from_pin <drive_from_pin> \
                 [get_ports {...}]
```

`drive_pin`、`drive_from_pin` 按 tool 支持情况可为空。若使用 rise/fall input transition 选项，应来自 `drive_input_transition_rise` / `drive_input_transition_fall`。

如果下级 SDC 的 `set_driving_cell` 命令包含项目第一版暂不支持的复杂选项，可以：

- 把原始命令放入 `original_command`。
- `constraint_type = driving_cell`。
- `source_type = extracted`。
- 在 `note` 中标记 `passthrough_required`。
- 生成器只在人工 review approved 后做受控透传；不能把复杂选项拆进自由文本后无检查拼接。

### 9.4 Object 粒度

表单建议按 single pad 拆行，便于 coverage 和冲突检查。

允许 `soc_object` 表示 port list 或 pattern，但必须设置：

```text
object_granularity = port_list / pattern
```

生成器可以在输出 SDC 时把多个等价 single-pad 行合并为一个 port list，以提高可读性；coverage report 仍应按单个 pad 展开。

生成命令示例：

```tcl
set_input_delay -clock [get_clocks {v_uart_rx}] -max 5.000 [get_ports {pad_uart0_sin}]
set_output_delay -clock [get_clocks {v_uart_tx}] -max 4.000 [get_ports {pad_uart0_sout}]
set_load 0.050 [get_ports {pad_uart0_sout}]
set_input_transition 0.200 [get_ports {pad_uart0_sin}]
```

对于 `false_path` 和 `dont_touch_network`：

```tcl
set_false_path -from [get_pins {u_iobuf/uart0_sout}] -to [get_ports {pad_uart0_sout}]
set_dont_touch_network [get_nets {pad_uart0_sout}]
```

生成时必须在输出 SDC 中保留简短注释，说明约束来自 extracted 还是 manual，以及来源文件/行号或表单依据，便于 review。

## 10. 检查规则

### 10.1 结构完整性检查

以下情况应报 error：

- `apply = yes` 但 `scenario` 为空。
- `apply = yes` 但 `pad_name` 或 `soc_object` 为空。
- `apply = yes` 但 `constraint_type` 为空。
- 集成表单中的 `subsys_port` / top pad 不是 canonical scalar 或 bit key，例如出现 bus/range/pattern，或 width 为多 bit 却未按 bit 展开。
- `apply = yes` 且 `review_status = approved` 的当前输出行无法生成任何 SDC 命令，例如 `false_path` 既无 `rewritten_command` 也无 `set_false_path` 原始命令，或电气约束缺少 `value`。
- `constraint_type = input_delay/output_delay` 但 `clock_name` 为空。
- `clock_name` 不存在于 `01_soc_clocks` 输出的 `clock_inventory.csv` 或对应 scenario clock inventory。
- `scenario = common` 的 04 约束引用了 scenario-only clock；common 04 只能引用 common 01 中创建的 clock。
- scenario 04 引用 scenario-only clock 时，没有对应 scenario clock inventory 证据。
- `timing_class = timed` 但既没有 input/output delay，也没有明确说明该接口由其它机制约束。
- assembled view 中同一个 pad/constraint_type 出现多个互相冲突的 approved 约束。
- assembled view 中 timed IO 同时存在 approved delay 和 approved false path，且没有显式冲突裁决。
- `value` 与 `min_value` / `max_value` 同时填写且语义冲突。
- `rise_value` / `fall_value` 与 `value` / `min_value` / `max_value` 同时填写且语义冲突。
- `extra_options` 中重复表达了已经结构化的 `delay_edge`、`delay_polarity`、`add_delay` 或 driving cell 字段。

### 10.2 方法学检查

以下情况应报 warning 或 error，具体严重程度可由项目配置：

- input pad 同时 approved `set_driving_cell` 和 `set_input_transition`，但没有 basis 说明。
- output pad 在 assembled view 中缺少 `set_load`，且没有标记 `NA` 或说明。
- input pad 在 assembled view 中缺少 `set_driving_cell` / `set_drive` / `set_input_transition`，且没有标记 `NA` 或说明。
- timed pad 只有 `-max` delay、没有对应 `-min` delay，且没有 `NA` 或 basis 说明；这通常意味着 hold 侧外部约束缺失。
- async/untimed IO 缺少 timing_class 依据。
- 从下级 SDC 提取到的 `set_false_path` 作用于 timed IO。
- 从下级 SDC 提取到的 `set_dont_touch_network` 无法稳定映射到 SoC 层级 net。
- GPIO/inout pad 的 input/output 方向约束被放入 common。
- `set_input_delay` / `set_output_delay` 的 target pad 本身是 01 中的 clock source/clock target port；clock pad 通常应由 01 建 clock，不应当成普通 data IO 加 delay，除非 basis 明确说明。
- 电气类约束使用 `stage = all` / `corner = all`，但项目 signoff methodology 要求按 view 区分外部 driver/load/slew。
- `unit_time` / `unit_cap` 与 SoC flow 当前单位不一致或为空且无法推断。
- `source_digest` 与当前下级 SDC 文件 digest 不一致，说明 extracted 记录可能已经失效，需要重抽或人工确认。
- `object_granularity = pattern` 的行应提示 reviewer 确认 pattern 展开结果，避免误约束非 pad port。
- `set_dont_touch_network` 行应标记为 synthesis-only；STA-only 输出中默认不生成。
- 若命令行提供 expected unit，例如 `--time-unit ns` 或 `--cap-unit pF`，对应 `unit_time` / `unit_cap` 为空也应 warning，不能只检查“不一致”的情况。

### 10.3 覆盖率检查

脚本应基于 `pad_inventory` 和 assembled view 输出 coverage report：

- 每个 SoC pad 是否在 04 表单中有记录。
- 每个 timed pad 是否有对应 delay 约束。
- 每个 output pad 是否有 load 或明确 `NA`。
- 每个 input pad 是否有 driving/input transition 或明确 `NA`。
- 每个 async/untimed pad 是否有 timing_class 依据。
- 每个 inout/GPIO pad 在相关 scenario 中是否有方向匹配的 timing 约束，以及是否有必要的物理/电气约束。
- common + scenario 叠加后有哪些约束来自 common、哪些来自 scenario、哪些来自 stage/corner view-specific 文件。
- 下级 SDC 中提取到但未被生成的约束列表和原因。

## 11. 与其它 SDC 的关系

### 11.1 与 01

04 只引用已经由 01 或 scenario clock overlay 创建好的 clock。

- IO virtual clock 必须在 01 创建。
- common 04 中的 delay 只能引用 common 01 `clock_inventory.csv` 中存在的 clock。
- scenario 04 中的 delay 可以引用 common 01 clock，也可以引用该 scenario clock overlay 产生的 scenario clock inventory。
- 如果某条 IO delay 引用 scenario-only clock，该约束必须下沉到对应 scenario 04，不能放在 common 04。
- 04 不扫描其它 SDC 创建 clock，也不在本文件补 create_clock。

### 11.2 与 02

02 描述 clock timing budget。

04 描述 IO/pad environment。

不要把 `set_clock_uncertainty` / `set_clock_latency` / `set_clock_transition` 放进 04。

### 11.3 与 03

03 描述 clock relationship。

04 中的 `set_false_path` 只应处理 pad/IO path 相关 exception，不处理 clock domain 关系。跨 clock domain 的 broad async/exclusive 关系应放 03。

### 11.4 与 10

10 描述结构性 harden feedthrough segment。

04 与 10/20 的边界：

- 04 = SoC top pad 对外部世界的环境，包括 board delay、external driver/load/slew、top pad 相关 IO DRC。
- 10 = harden/subsys 内部只负责穿通的 `fti_*` / `fto_*` feedthrough segment。
- 20 = harden/subsys/iobuffer 边界 pin 的普通内部 interface timing budget，包括 harden integration SDC 中对 SoC 可见的非 pad 边界约束。

如果 IO buffer / pad ring 本身是 harden：

- top pad port 对外的 `set_input_delay` / `set_output_delay` / `set_load` / `set_input_transition` 属于 04。
- harden IO buffer 内部侧 pin 到 SoC core/subsys 的普通边界 timing 属于 20。
- IO buffer 内部纯穿通段属于 10。
- 一条约束不能同时在 04、10、20 生成；脚本应在 report 中标记可能重复的 boundary constraint。

### 11.5 与 20 / 30

20 放普通 harden/subsys interface timing budget。

30 放 harden-to-harden path exception / override。

如果某条 false path 实际描述的是 harden-to-harden exception 或 feedthrough，而不是 IO/pad environment，应放入 30 或先由 10 建模后再由 30 review，不应混入 04。

## 12. 当前结论

04 的核心机制是：

```text
集成表单识别 pad 连接
  + 下级 SDC 提取已有 pad 约束
  + 表单记录 extracted/manual/NA
  + review 决定 apply
  + 检查缺失与冲突
  -> 生成 SoC 级 04 IO/pad SDC
```

因此，04 不应假设下级 subsys 的 pad 约束都缺失；如果下级 SDC 已经提供 `set_input_delay`、`set_output_delay`、`set_load`、`set_driving_cell` 或 `set_input_transition`，必须提取并记录到表单中。只有确认下级 SDC 没有、或者已有约束不适用于 SoC 时，才由人工补齐或标记 `NA`。
