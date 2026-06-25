# SoC SDC Architecture

本文档记录 SoC SDC 的整体层级规划和当前实现状态。目标是服务综合、STA；SpyGlass CDC 可主要复用 `01_soc_clocks.sdc` 和 `03_soc_clock_groups.sdc` 中的 clock 定义/async group，但 STA exception 与 CDC 语义不是 1:1，RDC 信息也不能依赖 SDC 完整表达。

## 0. 集成方式前提

本架构对 harden output clock 采用强制显式声明规则：**凡是 harden output port 会作为 SoC 或其他 harden 的 clock source 使用，harden SoC integration SDC 必须显式声明该 output clock**。

这条规则不依赖 harden 的集成方式。无论 harden 是可见 wrapper/netlist、`.lib` / `.db` timing model，还是 blackbox，只要 output port 被当作 clock 使用，就必须在 harden SDC 中出现对应的 `create_clock` 或 `create_generated_clock`。

### 0.1 可见 netlist / 非阻断 harden

即使 SoC STA/综合可以看到 harden wrapper/netlist 中的 clock path，仍要求 harden output clock 显式交付。

原因：

- 让 `01_soc_clocks.sdc` 可以稳定从 harden SDC 自动提取。
- 避免不同工具/不同抽象层级下 clock propagation 行为不一致。
- 让 harden output clock 的名称、period、source/master 关系可审查。

例如，若存在：

```text
u_harden_a/clk_o -> u_harden_b/clk_i
```

则 `u_harden_a/clk_o` 必须在 harden A 的 SoC integration SDC 中显式声明为 output clock。`u_harden_b/clk_i` 作为 sink 参与检查，不重复创建 primary clock。

### 0.2 `.lib` / `.db` 黑盒 harden

如果 harden 在 SoC 中以 `.lib` / `.db` timing model 或 blackbox 形式集成，SoC 通常看不到 harden 内部 clock path，不能假设 clock 会自动穿透 harden。

这种情况下，显式 output clock / forwarded generated clock 更是强制要求。例如：

```tcl
create_generated_clock \
  -name forwarded_clk \
  -source [get_ports clk_i] \
  -combinational \
  [get_ports clk_o]
```

SoC 侧脚本再把它提升为：

```tcl
create_generated_clock \
  -name u_harden_b_clk_o \
  -source [get_pins u_harden_b/clk_i] \
  -combinational \
  [get_pins u_harden_b/clk_o]
```

因此，本架构不依赖 SoC 工具自动穿透 harden 推断 output clock；harden output clock 一律由 harden SoC integration SDC 显式交付。

## 1. SoC SDC 层级规划

当前约定的 SoC SDC 内容结构如下：

```text
common/
  01_soc_clocks.sdc
  02_soc_clock_timing_<stage>_<corner>.sdc
  03_soc_clock_groups.sdc
  04_soc_io_pads.sdc
  10_feedthrough.sdc
  20_harden_x_if.sdc
  30_harden_to_harden_exception.sdc

scenarios/
  func.sdc
  <scenario>_clock_timing_<stage>_<corner>.sdc
  dft_scan.sdc
  mbist.sdc
  gpio_in.sdc
  gpio_out.sdc
```

当前阶段先按 **func 单一模式** 推进。第一版已开始生成和评审：

```text
common/01_soc_clocks.sdc
common/02_soc_clock_timing_<stage>_<corner>.sdc
scenarios/func_clock_timing_<stage>_<corner>.sdc
```

`dft_scan.sdc`、`mbist.sdc`、`gpio_in.sdc`、`gpio_out.sdc` 先作为预留场景，后续需要时再展开。

## 2. 各文件定位

### 2.0 `00_harden_port_inventory`

`00_harden_port_inventory` 不是 SDC 文件，而是 harden port coverage 的 pending list 和 direct connection edge inventory 机制。

它从集成表单生成两类基础产物：每个 harden/subsys instance 的待约束 port 文本文件，以及 SoC direct 连接的 bit-to-bit `connection_inventory.csv` 边表。每个后续 stage 完成一类约束后，就从对应 harden 的 pending `.ports` 文件中删除已覆盖 port，并输出 removed log。若某些 port 经 review 后确认合理无需约束，则由 `00_disposition` 独立消账。最终 pending 文件中剩余的行才是需要继续 review 的未约束 port。

建议目录：

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
```

pending 文件采用一行一个 canonical port key 的文本格式。scalar 直接写 port 名；bus/vector 必须展开成 `port[index]`：

```text
input clk_i
input fti_0_mmn2gms_req_valid
output fto_0_mmn2gms_req_valid
output data_o[0]
output data_o[1]
```

主要功能：

- 从集成表单建立每个 harden 的待约束 port 清单。
- 从集成表单建立 bit-to-bit `connection_inventory.csv`，作为 direct channel 的唯一连接真源。
- 让 01/04/10/20/30 通过删除 pending 行完成 port 消账。
- 让 `00_disposition` 消账合理无需约束的 port，例如 tie-off、NC、mode-inactive、func 下被 case 掉的 test/scan/mbist 控制 port。
- 让最终漏约束 port 以文本剩余行的形式直接暴露。
- 通过 removed log 保留每个 stage 删除了哪些 port 及删除原因。

注意：

- pending 文件只表达“还没消账”，不放复杂状态列。
- 02/03 不直接删除任何 harden port；只由 03 clock group 解释的 port 仍需走 20/30 或 `00_disposition`。
- 00 是 harden port 粒度的唯一 source of truth：机器可读 pending / removed log / downstream channel 都使用 `(inst_name, direction, port_bit)`；bus bit 的 canonical 写法是 `port[index]`。
- 集成表单中的 bus/range 连接必须在 00 展开成明确 bit-to-bit edge，并写入 `connection_inventory.csv`；位宽、方向或 bit order 无法判定时应报错，不允许后续 stage 猜测。
- 20/30 direct channel 必须消费 `connection_inventory.csv` 或其派生的 20 channel inventory；不能重新从原始集成表单展开 range。
- 整 bus 或 range 只允许出现在人工 summary/report 中，不能作为 pending 删除粒度。
- 默认 ownership 顺序为 `01 clock > 04 pad > 10 feedthrough > 20 interface budget > 30 exception > 00_disposition`。
- 删除是对 pending list 的消费，不是删除源集成表单信息。
- 如果某 port 只是被识别为候选，但尚未生成或确认约束，不能从 pending 中删除。

### 2.1 `common/01_soc_clocks.sdc`

定义 SoC 级 clock object，包括：

- SoC 顶层 pad/ref/test 输入 clock。
- harden output clock。
- harden generated/forwarded clock。
- virtual clock，例如 IO delay 使用的外部参考 clock。

主要功能：

- 建立 STA/综合需要认识的所有 func clock。
- 统一创建所有 clock object；所有 `create_clock` / `create_generated_clock` 都归属本文件，包括 virtual clock。
- 把 harden SDC 中的 clock 声明提升到 SoC instance 层级。
- 统一 clock name，避免多个 harden 或多个 instance 之间 clock 重名。
- 为后续 `03_soc_clock_groups.sdc`、`02_soc_clock_timing_<stage>_<corner>.sdc`、exception、IO delay 提供稳定 clock object。

不放：

- clock group。
- clock timing budget，例如 `set_clock_uncertainty`、`set_clock_latency`、`set_clock_transition`。
- false path / multicycle / max delay。
- IO delay。
- scan/mbist/gpio scenario 专属 clock。

当前规则/目录状态：

```text
01_soc_clocks/
  01_soc_clocks_extraction_rules.md
  01_extract_soc_clocks.py

02_soc_clock_timing/
  02_soc_clock_timing_form_spec.md
  02_extract_soc_clock_timing.py
  02_soc_clock_timing_budget_prects_demo.xlsx
  02_soc_clock_timing_budget_postcts_demo.xlsx

03_soc_clock_groups/
  03_soc_clock_groups_rules.md
  03_extract_soc_clock_groups.py

04_soc_io_pads/
  04_soc_io_pads_rules.md
  04_extract_soc_io_pads.py

00_harden_port_inventory/
  00_harden_port_inventory_rules.md

10_feedthrough/
  10_feedthrough_rules.md
20_harden_x_if/
  20_harden_x_if_rules.md
  20_extract_harden_x_if.py
30_harden_to_harden_exception/
  30_harden_to_harden_exception_rules.md
```

### 2.2 `common/02_soc_clock_timing_<stage>_<corner>.sdc`

定义所有 scenario 都成立的 SoC clock timing budget。

该文件是 **stage-dependent** 且 **corner-dependent**：pre-CTS、post-CTS、post-route 等阶段可以使用不同取值，不同 PVT/corner/analysis view 也必须使用不同 SDC 文件。

对应输入表单格式见 `02_soc_clock_timing/02_soc_clock_timing_form_spec.md`。02 表单按 stage 独立维护，例如 pre-CTS 和 post-CTS 分别使用不同 xlsx；同一 stage 表单中可以包含多个 scenario/corner，但生成 SDC 时必须按指定 scenario/corner 单独输出。

主要功能：

- 定义 common 的 clock uncertainty，例如 `set_clock_uncertainty`。
- 定义 common 的 clock latency，例如 `set_clock_latency`。
- 定义 common 的 clock transition，例如 `set_clock_transition`。
- 定义 stage 切换相关 clock 状态，例如 `set_propagated_clock`。
- 定义 timing derate / OCV budget，例如 `set_timing_derate`；AOCV/POCV 若由 flow/corner setup 管理，也应在本阶段统一挂接或记录。
- 承载综合/STA 早期阶段的 clock budget 假设。
- 在 CTS 前后、corner 切换时提供 timing budget 的清晰入口。

不放：

- `create_clock` / `create_generated_clock`，这些放 `01_soc_clocks.sdc`。
- clock group，这些放 `03_soc_clock_groups.sdc`。
- IO/pad transition 或外部 driving model，这些放 `04_soc_io_pads.sdc`。
- false path / multicycle / max delay。

注意：

- pre-CTS 常需要估算 source/network latency、uncertainty、transition。
- post-CTS/post-route 可能由工具提取的实际 clock network 替代部分 latency/transition 假设，并配合 `set_propagated_clock` 切换 clock propagation 状态。
- `set_propagated_clock` 可以由 flow Tcl 执行，不一定写入 SDC 文件；但归属仍属于 02 的 stage 切换策略，必须和 latency/uncertainty/transition 一起评审。
- `set_timing_derate`、AOCV、POCV 属于 corner/stage 相关 timing budget；若实际由 MMMC/corner flow 统一设置，02 中至少应保留引用入口或说明，避免散落到 IO、exception 或 harden interface 文件。
- SDC 本身没有 corner 条件化能力；不能把 `ss_125`、`ff_m40` 等多个 corner 的 uncertainty/derate 平铺进同一个 02 SDC，否则后 source 的同类命令会覆盖前者。
- 不同 stage/corner 的 `02` 必须采用不同文件名并由 MMMC analysis view 选择性 source，例如 `02_soc_clock_timing_prects_ss_125.sdc`、`02_soc_clock_timing_prects_ff_m40.sdc`、`02_soc_clock_timing_postcts_ss_125.sdc`。
- `scenario = common` 的 timing budget 只能输出到 `common/02_soc_clock_timing_<stage>_<corner>.sdc`。
- `scenario != common` 时，脚本必须在生成阶段按优先级 resolve：当前具体 scenario 行优先于 `common` 行；同一 clock/stage/corner 最终只允许 emit 一个胜出行。
- `scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc` 是该 scenario 的 resolved effective 02 文件，可能包含 common fallback 的胜出行；装配时不能再同时 source `common/02_soc_clock_timing_<stage>_<corner>.sdc` 来靠顺序覆盖。

### 2.3 `common/03_soc_clock_groups.sdc`

定义架构上确定的 clock group 关系，例如异步、逻辑互斥、物理互斥 clock。

当前架构采用 **默认 synchronous + 显式枚举 asynchronous / logically_exclusive / physically_exclusive** 的姿态：未被 03 clock group 覆盖的 clock pair，在 STA 中保持默认 synchronous 分析。若项目改用“默认 asynchronous + 显式同步例外”的反向姿态，需要单独规划 03 表单和 coverage report 语义，不能与本机制混用。

03 是 downstream clock relation 的权威来源。跨 20/30 共享的 canonical enum 为 `synchronous` / `asynchronous` / `logically_exclusive` / `physically_exclusive` / `unknown`。表单可接受 `async`、`sync` 等旧别名作为输入，但脚本必须归一成 canonical enum 后再检查、报告和回写。

注意：clock mux、test clock、scan clock、mbist clock 相关关系要谨慎，不能为了消除 warning 随意 common 化。

对于 clock mux 互斥关系，必须先选择 STA 建模方法：

- per-scenario signoff view：在 Stage 1 用 `set_case_analysis` 选定 mux 单腿，未选中的 clock leg 不应传播；此时 03 不再对同一个 mux/clock pair 生成 `logically_exclusive`。
- all-mode / merged view：不打单腿 `set_case_analysis`，保留多条 mux clock leg；此时才用 03 的 `set_clock_groups -logically_exclusive` 表达互斥。

同一个 mux/clock pair 不应同时用 `set_case_analysis` 和 `logically_exclusive` 表达同一层互斥语义。

clock group 成员应按 domain closure 检查和展开。表单中写入的 clock 可以作为 domain seed/member；生成 03 前，脚本应根据 01 `clock_inventory.csv` 的 source/master/root genealogy，把该 seed 下可追溯的 generated / forwarded descendants 加入同一 effective group，或要求表单显式排除并说明原因。不能默认依赖 STA 工具自动把 master clock 的 group 关系继承给 generated clock。

对 `logically_exclusive` 的 group，domain closure 需要特别 review：mux 两条输入腿在 mux 输出处可能重新汇合成同一个下游 clock，而 01 genealogy 可能只把这个输出 clock 归到其中一条腿。脚本不应静默把这类汇合点 clock 塞进某一条 exclusive group，必须报告出来让 reviewer 确认归属或显式排除。

03 还必须生成 assembled-view 检查结果。对每个 scenario，应按 `common + 当前 scenario` 建立最终 clock-pair relation map，检查 common 与 scenario 是否冲突，并输出 coverage report：每个 clock 的 group 参与情况、每个 03 genealogy `tree_root` pair 的覆盖情况，以及未被 clock group 覆盖的跨 tree clock pair。这些未覆盖 pair 在 STA 中仍按默认 synchronous 分析，供 reviewer 决定是否需要新增 group 或保留默认分析。01 `root_source` 字符串只作为诊断参考，不作为独立时钟树判断依据。

第一版 coverage report 不建模 `set_case_analysis`。如果 scenario pre-setup 已 case 掉某些 mux leg，对应 clock pair 可能仍显示为 uncovered；实际是否分析应以该 scenario 的 case 后 active clock set 为准。后续可让 03 读取 `scenarios/<scenario>_pre.sdc` 或结构化 case 表单来过滤。

如果多个 domain 是两两 `asynchronous` / `logically_exclusive` / `physically_exclusive`，应在同一条 `set_clock_groups` rule 中列出多个 `-group`。拆成共享一个 clock 的多条二元 rule 只覆盖已列 pair，不会自动覆盖其它 domain pair，例如 A/B 与 A/C 不会覆盖 B/C。

主要功能：

- 定义所有 mode 下都成立的 asynchronous clock group。
- 定义所有 mode 下都成立的 `logically_exclusive` / `physically_exclusive` clock group。
- 收敛 SoC 级跨 clock domain 的默认 STA 分析边界。
- 只表达 clock relationship，不表达 clock 自身属性。
- 基于 01 genealogy 检查和展开 clock group 的 generated/forwarded descendants，避免漏切派生 clock。
- 对 `common + scenario` assembled view 做跨 rule/跨 scenario 冲突检测。
- 输出 clock group coverage report，辅助 reviewer 识别仍默认同步的跨 03 genealogy `tree_root` clock pair。

不放：

- 依赖 scan/test/mbist/gpio mode 的 clock group。
- 仅为了屏蔽 timing violation 而没有架构依据的 clock group。
- harden-to-harden 特定 path exception。
- `set_clock_uncertainty` / `set_clock_latency` / `set_clock_transition`，这些放 `02_soc_clock_timing_<stage>_<corner>.sdc` 或对应 scenario/stage/corner 文件。

### 2.4 `common/04_soc_io_pads.sdc`

定义 SoC 顶层 IO/pad timing environment。

IO/pad 约束的归属取决于接口属性、scenario 和 stage/corner view：所有模式都成立的约束可以放 common；依赖 GPIO/inout 方向、DFT/MBIST/test mode 或特定 view 的约束应下沉到对应 scenario 或 `<stage>_<corner>` 文件。

04 的详细归集、表单和检查规则见 `04_soc_io_pads/04_soc_io_pads_rules.md`。04 不是单纯人工补缺文件，而是先从下级 iobuffer/module SDC 提取已有 pad 约束，再通过表单 review、补缺、裁剪冲突，最后生成 SoC 级 IO/pad SDC。

主要功能：

- 定义 SoC 顶层 pad/port 分组。
- 引用 `01_soc_clocks.sdc` 中已经创建的 clock object，包括 virtual clock、real clock、generated/forwarded clock；common 04 只能引用 common 01 clock，引用 scenario-only clock 的 IO 约束必须下沉到 scenario 04。
- 定义 common 的 pad/input/output delay，例如固定方向、固定协议、所有 func mode 都成立的 `set_input_delay` / `set_output_delay`。
- 定义 common 的外部输入驱动模型，例如 `set_driving_cell` / `set_drive`。
- 定义 common 的输出负载，例如 `set_load`。
- 定义 common 的输入 transition/slew，例如 `set_input_transition`。
- 定义 IO 侧 design rule 约束，例如作用于 top IO port 的 `set_max_transition` / `set_max_capacitance`。
- 定义与 pad 直接相关、经 review 后确认适用于 SoC 的 `set_false_path`。
- 归集与 pad net 直接相关、经 review 后确认适用于综合的 `set_dont_touch_network`；该命令主要是 synthesis-only 结构保护，不是 STA timing environment。
- 记录 GPIO/inout pad 的方向依赖关系，为后续 `gpio_in.sdc` / `gpio_out.sdc` 拆分做准备。
- 对 common + scenario + stage/corner 的 assembled view 做冲突/覆盖检查，避免靠后 source 覆盖 common 约束。

不放：

- harden 内部接口约束。
- harden IO buffer 内部侧边界 pin timing；这类放 `20_harden_x_if.sdc`。
- harden-to-harden exception。
- `create_clock` / `create_generated_clock`，包括 IO virtual clock；所有 clock object 都放 `01_soc_clocks.sdc`。
- 依赖 GPIO 方向、DFT、MBIST 的 IO delay、driving model、load 或 transition。
- 全芯片内部 design rule 约束；这类后续如有需要可单独规划。

注意：

- `set_driving_cell`、`set_drive`、`set_input_transition` 都是在描述 input port 的外部驱动/输入 slew，不应对同一组 input port 无规则重复设置。
- 若 flow 同时需要 driving cell 和 input transition，必须在 04 的实现规则中明确优先级和适用端口集合。
- `set_load`、`set_driving_cell`、`set_input_transition`、IO design rule 等电气类约束可能随 stage/corner/view 变化；若项目不能确认它们 view-independent，应使用 `04_soc_io_pads_<stage>_<corner>.sdc` 或 scenario 对应文件拆分。
- `set_input_delay` / `set_output_delay` 多数来自板级或接口 timing budget，若项目确认 corner-independent，可保留在 view-independent 04。

### 2.5 `common/10_feedthrough.sdc`

定义 SoC 中结构性 harden feedthrough path。

10 是 harden 相关阶段的第一步。由于项目已约定 feedthrough port 使用 `fti_` / `fto_` 命名，10 可以先识别和收口一部分 harden 间穿通结构，避免后续 20/30 把 feedthrough harden 误当成真正 timing endpoint。

feedthrough path 指某个 harden/subsys 内部不作为该 path 的逻辑 source/destination，只负责把信号从 input port 穿到 output port，例如：

```text
u_src/req_o -> u_ft/fti_0_src2dst_req -> u_ft/fto_0_src2dst_req -> u_dst/req_i
```

主要功能：

- 识别项目约定的 `fti_` / `fto_` feedthrough port 命名。
- 同一 harden 内先按 `(index, base)` 识别 feedthrough input/output 候选，再按 `(index, base, bit_index)` 形成最终 bit-level segment。
- 多 hop feedthrough 使用 `fti_<index>_` / `fto_<index>_`，index 按每条 end-to-end 链路方向从第一个接收 harden 开始计数。
- 校验 feedthrough index 与集成表单连接顺序是否一致。
- 对 vector feedthrough 按 `(index, base, bit_index)` 配对，生成 bit-level segment。
- 输出 `feedthrough_inventory.csv`，并为每个穿通 segment 生成稳定 `feedthrough_id`，例如 `FT_<feedthrough_instance>_<hop_index>_<base>_bit7`；这是 30 `related_10_feedthrough_id` 的唯一生产者。
- 生成 feedthrough inventory / SDC 后，从 `00_harden_port_inventory/pending/*.ports` 删除对应 `fti_*` / `fto_*` canonical bit key。
- 读取 00 `connection_inventory.csv` 来确认进入/离开 feedthrough harden 的 bit edge，并为 20 普通 interface budget 和 30 exception 提供 end-to-end source/destination 还原依据。
- 10 v1 只产出 common 结构性 feedthrough manifest，不产出 scenario-specific feedthrough SDC；mode-specific feedthrough 暂不自动处理。

不放：

- 普通 harden/subsys interface timing budget；这类放 `20_harden_x_if.sdc`。
- harden-to-harden path exception / override；这类放 `30_harden_to_harden_exception.sdc`。
- 接 SoC top pad 的 IO 外部环境约束；这类放 `04_soc_io_pads.sdc`。
- 不符合 `fti_` / `fto_` 命名规则的任意组合逻辑 feedthrough 自动推断。
- feedthrough path 上的 exception 生成；这类仍由 30 表单 review。

### 2.6 `common/20_harden_x_if.sdc`

定义 SoC 视角的 harden/subsys interface timing budget。

它不是直接 source harden 内部 full SDC，而是接收 harden SoC integration SDC 中对 SoC 有意义的边界 timing contract。20 的判断依据是约束意图，不是命令名字：凡是表达 harden/subsys 边界正常 timing budget 的约束，归 20；凡是改变默认 STA 分析语义的 exception，归 30。

对于 subsys/harden SDC 中非 SoC top pad 相关的 `set_input_delay` / `set_output_delay`，20 可以将其作为接口 contract 候选信息提取到表单；在 SoC top 层默认不直接把它们机械改写成 instance pin 上的 `set_input_delay` / `set_output_delay`。

20 v1 的 SoC 输出以 reviewed `set_max_delay` / `set_min_delay` 为主，但该数值必须是 boundary-to-boundary channel datapath budget。常规 clock-relative input/output delay 原值不能直接当作 `set_max_delay -datapath_only` 的数值；只有 harden owner 明确声明其为 SoC 边界外 interconnect budget，或 reviewer 基于 01/02 clock setup、架构预算、接口协议重新推导后，才能生成。

如果 harden/subsys 以可见 wrapper/netlist 方式集成，且普通 reg-to-reg path 已被 SoC STA 覆盖，20 默认不再额外叠加 `set_max_delay -datapath_only`。20 更适合 `.lib` / `.db` blackbox、abstract model、或架构明确要求显式 channel budget 的场景。

主要功能：

- 汇总 harden 边界 pin group，例如输入接口、输出接口、控制 pin、模式 pin。
- 放置所有 mode 都成立的 harden/subsys interface timing budget。
- 提取 harden integration SDC 中可用于 SoC 的非 pad 边界 timing contract，并完成 SoC 层级提升、clock 映射、连接关系过滤和 review。
- 对需要显式 budget 的普通接口生成 reviewed `set_max_delay` / `set_min_delay` 等边界预算约束。
- 按 00 canonical bit key 和 `connection_inventory.csv` 建立 channel；bus fanout/range 已在 00 展开为 per-bit edge，20 只消费该边表并生成 bit-stable `channel_id`。
- 生成或确认普通 channel budget 后，从 `00_harden_port_inventory/pending/*.ports` 删除对应 source/destination canonical bit key。
- 作为 harden owner 交付信息和 SoC 约束体系之间的转换层。

不放：

- harden 内部 full SDC。
- harden 内部 signoff exception。
- mode-specific scan/mbist/test constraint。
- harden-to-harden 跨模块 exception，例如 false path、multicycle path、async/handshake path、mode-specific override；这类放 `30_harden_to_harden_exception.sdc`。
- 接 SoC top pad 的 IO 外部环境约束；这类放 `04_soc_io_pads.sdc`。
- feedthrough 穿通段建模；这类先放 `10_feedthrough.sdc`。
- 已由可见 netlist / timing model 正常覆盖的普通同步 reg-to-reg path。

### 2.7 `common/30_harden_to_harden_exception.sdc`

定义 harden-to-harden path 相关 exception。

这是高风险文件。只放所有 mode 都成立、且有架构依据的 exception；mode-specific exception 下沉到对应 scenario。30 的判断依据同样是约束意图：它只表达对默认 STA 语义的特殊改写，不承接普通 harden interface budget。

30 支持的第一版命令限制为 `set_false_path`、`set_multicycle_path`、exception 性质的 `set_max_delay` / `set_min_delay`。其中 `set_max_delay` / `set_min_delay` 只有在表达 path-level override、CDC/handshake skew 或非默认协议约束时才归 30；普通 boundary-to-boundary interface budget 仍归 20。

harden port 缺少 `set_input_delay` / `set_output_delay` 只能作为 30 candidate 信号，不是自动生成 exception 的依据。30 采用 candidate/rule 两层 review：脚本可以发现 missing timing、harden SDC exception、integration tag、03/20 关系等 candidate，但只有 `exception_rule` 中 approved 的规则才允许生成。

主要功能：

- 定义 harden A output 到 harden B input 之间的 common exception。
- 收敛所有 mode 都成立的 false path、multicycle path。
- 收敛 exception 性质的 `set_max_delay` / `set_min_delay` override，例如 async handshake、configuration path、非单周期协议或其它需要偏离普通同步接口 budget 的路径。
- 记录每条 exception 的设计依据、owner 和适用范围。
- exception endpoint 按 00 canonical bit key 建模；direct path 的 bit 配对来自 00 `connection_inventory.csv` 或 20 channel inventory，partial-bit exception 必须明确展开到具体 bit endpoint。
- 生成 approved exception / override 后，从 `00_harden_port_inventory/pending/*.ports` 删除对应端点 canonical bit key。
- 对 common + scenario + stage/corner 的 assembled view 做冲突检查，避免同一路径同时存在 active 20 普通 budget 与 30 exception，或 30 内部 false path/multicycle/max/min 互相覆盖。

不放：

- 没有设计依据、只为清 timing 的 exception。
- 从 subsys `set_input_delay` / `set_output_delay` 转换而来的普通 interface budget；这类放 `20_harden_x_if.sdc`。
- 依赖 func/scan/mbist/gpio mode 的 exception。
- clock group，这类放 `03_soc_clock_groups.sdc`。
- feedthrough 结构约束，这类优先放 `10_feedthrough.sdc`。

注意：

- `set_false_path` 与 03 asynchronous/logically_exclusive/physically_exclusive 通常冗余；但 `set_max_delay -datapath_only` 与 03 asynchronous 可以是 CDC/handshake 建模中的互补约束。
- 30 必须是 object-level exception；clock-to-clock 约束归 03，不应在 30 中用 `[get_clocks ...]` 直接作为 from/to/through。
- 单独的 `set_max_delay -datapath_only` 不会去掉常规 setup/hold 检查。异步路径若需要 max delay 上限，通常还需要 03 asynchronous/logically_exclusive/physically_exclusive 或其它 CDC clock relation 处理。
- CDC/异步 handshake 的传播窗口约束通常应使用 `set_max_delay -datapath_only` 与 `set_min_delay -datapath_only` 成对表达；同 clock / related clock 的功能性 override 默认不应使用 `-datapath_only`，除非有明确依据。
- 03 asynchronous 与 30 max/min 是否能同时生效必须用目标 STA 工具验证；若 `set_clock_groups -asynchronous` 在项目 flow 中遮蔽 path-level max/min，应采用项目确认的等效写法。
- `set_multicycle_path` 需要明确 setup/hold cycle；跨 clock multicycle 还必须明确 `-start` / `-end` 参照、周期比和 hold 推导。
- 30 与 active 20 的 overlap 必须按 check 维度判断；20 max 与 30 min 可以带依据共存，但同类型或 false_path 覆盖应报错。
- 经过 feedthrough harden 的多跳路径必须先由 10 建模，并在 30 中用 `through_collection` 和 `related_10_feedthrough_id` 锚定穿通段；`related_10_feedthrough_id` 必须引用 10 `feedthrough_inventory.csv` 中的 `feedthrough_id`，多 hop 时按路径顺序列出多个 id。
- 若 path 经过 vector feedthrough，`related_10_feedthrough_id` 必须引用对应 bit-level id；不能用一个整 bus id 代表部分 bit。
- 同一路径不能依赖工具 exception priority 静默裁决；例如 false path、max/min override、multicycle overlap 必须在 30 表单中拆分或报错。
- reset path 的 false path 高风险，必须说明 recovery/removal 如何另行保证。
- 数值型 30 override 可能随 stage/corner/view 变化，必要时使用 `common/30_harden_to_harden_exception_<stage>_<corner>.sdc` 或 scenario 对应 view-specific 文件。

### 2.8 `scenarios/*.sdc`

定义 mode/scenario 专属约束：

- `func.sdc`：功能模式。
- `dft_scan.sdc`：scan shift/capture/test mode。
- `mbist.sdc`：MBIST/BIST mode。
- `gpio_in.sdc`：GPIO input 方向。
- `gpio_out.sdc`：GPIO output 方向。

第一阶段只按 func 单一模式实现。

主要功能：

- 放置只在特定 scenario 成立的 `set_case_analysis`。
- 放置该 scenario 专属 clock mux select、PLL bypass、test mode、scan enable、BIST enable 等配置。
- 放置该 scenario 专属 clock、clock attribute、clock group、IO delay、exception。
- 放置该 scenario 专属 clock timing budget，例如 `scenarios/func_clock_timing_prects_ss_125.sdc`。

不放：

- 所有 mode 都成立的 common clock 定义。
- 所有 mode 都成立的 common exception。
- harden 内部 full SDC。

## 3. SDC 装配顺序

SDC 是顺序敏感的。SoC 约束不应只约定“每个文件放什么”，还必须约定 common 和 scenario 的 source 顺序。

### 3.1 基本原则

- clock object 必须先于引用它的 clock timing、clock group、IO delay 和 exception。
- mode/case 约束应在依赖 mode 选择的 generated clock、clock mux、exception 之前注入。
- clock timing budget 应在 clock object 创建之后注入。
- broad clock relationship 应早于 path-level exception。
- harden interface/feedthrough/path exception 应尽量靠后。
- 不应依赖“后 source 覆盖前 source”来解决冲突；有冲突时应拆 scenario 或修正约束归属。

### 3.2 推荐装配阶段

推荐把每个 scenario 的入口文件写成分阶段 source，而不是直接把 common 文件顺序硬堆。

```text
Stage 0: design/elab/link 已完成

Stage 1: scenario pre-setup
  scenarios/<scenario>_pre.sdc
    - set_case_analysis
    - mode select
    - clock mux select
    - PLL bypass/config mode
    - scan_en/test_mode/bist_en/gpio direction

Stage 2: clock creation
  common/01_soc_clocks.sdc
  scenarios/<scenario>_clocks.sdc      # 如该 scenario 有专属 clock/mux clock

Stage 3: clock timing budget                                      # 二选一，不与 common/02 叠加
  common/02_soc_clock_timing_<stage>_<corner>.sdc                  # scenario = common
  or
  scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc           # scenario != common, resolved effective file

Stage 4: clock relationship
  common/03_soc_clock_groups.sdc
  scenarios/<scenario>_clock_groups.sdc

Stage 5: IO/pad environment
  common/04_soc_io_pads.sdc
  common/04_soc_io_pads_<stage>_<corner>.sdc                  # 如存在 view-specific IO 电气约束
  scenarios/<scenario>_io_pads.sdc
  scenarios/<scenario>_io_pads_<stage>_<corner>.sdc           # 如存在 scenario + view-specific IO 约束

Stage 6: harden feedthrough / interface
  common/10_feedthrough.sdc
  common/20_harden_x_if.sdc
  common/20_harden_x_if_<stage>_<corner>.sdc                  # 如存在 view-specific interface budget
  scenarios/<scenario>_harden_x_if.sdc
  scenarios/<scenario>_harden_x_if_<stage>_<corner>.sdc       # 如存在 scenario + view-specific interface budget

Stage 7: path exception
  common/30_harden_to_harden_exception.sdc
  common/30_harden_to_harden_exception_<stage>_<corner>.sdc      # 如存在 view-specific max/min override
  scenarios/<scenario>_exceptions.sdc
  scenarios/<scenario>_exceptions_<stage>_<corner>.sdc           # 如存在 scenario + view-specific override
```

注意：Stage 3 与其它 stage 的装配模型不同。

- 03/04/20/30 等 stage 采用 **common + scenario 叠加**：scenario 文件只追加该 scenario 专属约束，不覆盖 common 已声明的同一对象，因此 common 和 scenario 文件按顺序都 source。10 v1 是 common-only structural manifest，不叠加 scenario-specific feedthrough 文件。04/20/30 还可能同时存在 view-independent 与 view-specific 文件；同一对象/constraint_type 在 common、scenario、view-independent、view-specific 之间也必须通过 assembled-view 检查避免冲突，不能靠 source 顺序覆盖。
- Stage 3 的 02 clock timing 采用 **resolve-single-file**：02 脚本已按 `scenario + stage + corner` 把 common 默认 resolve 进 scenario 专属文件，scenario 行优先、common 兜底，同一 clock 只保留一个胜出行。因此：
  - `scenario = common` 装配：只 source `common/02_soc_clock_timing_<stage>_<corner>.sdc`。
  - `scenario != common` 装配：只 source `scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc`，**不要再叠加 source `common/02_soc_clock_timing_<stage>_<corner>.sdc`**，否则 common budget 被重复 source，且退回到靠 source 顺序覆盖，违反 3.1 原则。

当前第一阶段只做 func 单一模式，因此可以先简化为：

```tcl
# scenarios/func.sdc, concept only

# Stage 1: func mode setup
source scenarios/func_pre.sdc

# Stage 2: clocks
source common/01_soc_clocks.sdc

# Stage 3: clock timing budget
# func scenario sources one resolved effective 02 file
source scenarios/func_clock_timing_prects_ss_125.sdc

# Stage 4: clock relationships
source common/03_soc_clock_groups.sdc

# Stage 5: IO/pad environment
source common/04_soc_io_pads.sdc
# optional, if view-specific IO electrical constraints exist
source common/04_soc_io_pads_prects_ss_125.sdc
source scenarios/func_io_pads.sdc

# Stage 6: harden feedthrough / interface
source common/10_feedthrough.sdc
source common/20_harden_x_if.sdc
# optional, if view-specific interface budget exists
source common/20_harden_x_if_prects_ss_125.sdc

# Stage 7: exceptions last
source common/30_harden_to_harden_exception.sdc
# optional, if view-specific exception/override exists
source common/30_harden_to_harden_exception_prects_ss_125.sdc
source scenarios/func_exceptions.sdc
# optional, if scenario + view-specific exception/override exists
source scenarios/func_exceptions_prects_ss_125.sdc
```

如果暂时不拆 `func_pre.sdc` / `func_exceptions.sdc`，也可以先由 `scenarios/func.sdc` 内部分段组织，但仍应保留上述 stage 顺序。

### 3.3 `set_case_analysis` 注入点

`set_case_analysis` 属于 scenario setup，不建议放在 common 文件里。

推荐注入位置：

- clock mux select：必须在依赖 mux 选择的 generated clock 和 clock group 前注入。
- PLL bypass/config mode：必须在相关 clock creation 或 scenario clock overlay 前注入。
- scan/test/mbist/gpio direction：放在对应 scenario 的 pre-setup 阶段。

如果该 scenario 已经用 `set_case_analysis` 固定了某个 clock mux 单腿，则不要再在 `03_soc_clock_groups.sdc` 或 `scenarios/<scenario>_clock_groups.sdc` 中为同一 mux leg 添加 `logically_exclusive`。`logically_exclusive` 主要服务于没有单腿 case 的 all-mode / merged STA view。

示例：

```tcl
# scenarios/func_pre.sdc
set_case_analysis 0 [get_ports scan_en]
set_case_analysis 0 [get_ports mbist_en]
set_case_analysis 1 [get_pins u_clk_mux/func_sel]
```

然后再 source：

```tcl
source common/01_soc_clocks.sdc
source scenarios/func_clocks.sdc
```

### 3.4 Exception 排序原则

exception 尽量在 clock、clock timing、clock group、IO 和 interface 之后 source。

推荐顺序：

```text
1. clock relationship
   common/03_soc_clock_groups.sdc

2. structural/path environment
   common/10_feedthrough.sdc
   common/20_harden_x_if.sdc

3. common path exception
   common/30_harden_to_harden_exception.sdc
   common/30_harden_to_harden_exception_<stage>_<corner>.sdc      # 如存在 view-specific max/min override

4. scenario-specific exception
   scenarios/<scenario>_exceptions.sdc
   scenarios/<scenario>_exceptions_<stage>_<corner>.sdc           # 如存在 scenario + view-specific override
```

注意：

- `set_clock_groups` 是 clock relationship，不放到 path exception 文件里。
- `false_path`、`multicycle_path`、`max_delay`、`min_delay` 之间不要靠 source 先后来“覆盖”冲突。
- 如果一条 path 同时命中多个 exception，应在 review/report 中显式标记，优先修正约束归属。
- mode-specific exception 不进入 common，必须下沉到对应 scenario。

## 4. 相关文档

- [Project Context](00_project_context.md)：当前工作状态、关键决策、脚本状态和新会话接力信息。
- [Harden SoC Integration SDC Requirements](harden_sdc_requirements.md)：harden/IP 交付给 SoC 使用的 SDC 要求，包括 flatten/normalized 规则和 clock 声明规则。
- [00_harden_port_inventory](00_harden_port_inventory/00_harden_port_inventory_rules.md)：harden port pending 文本清单、删除消账和 removed log 规则。
- [01_soc_clocks](01_soc_clocks/01_soc_clocks_extraction_rules.md)：`common/01_soc_clocks.sdc` 的提取规则和脚本说明。
- [02_soc_clock_timing](02_soc_clock_timing/02_soc_clock_timing_form_spec.md)：`02` clock timing budget 表单、生成机制和检查规则。
- [03_soc_clock_groups](03_soc_clock_groups/03_soc_clock_groups_rules.md)：`03` clock relationship / clock group 规则、表单建议和检查项。
- [04_soc_io_pads](04_soc_io_pads/04_soc_io_pads_rules.md)：`04` IO/pad 约束归集、表单建议和检查项。
- [10_feedthrough](10_feedthrough/10_feedthrough_rules.md)：`10` feedthrough port 命名、识别和检查规则草案。
- [20_harden_x_if](20_harden_x_if/20_harden_x_if_rules.md)：`20` harden/subsys interface channel budget 归并、转换和检查规则。
- [30_harden_to_harden_exception](30_harden_to_harden_exception/30_harden_to_harden_exception_rules.md)：`30` harden-to-harden path exception / override 规则草案。
