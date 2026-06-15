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
  10_harden_x_if.sdc
  20_harden_to_harden_exception.sdc
  30_feedthrough.sdc

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

当前已建立独立工作目录：

```text
01_soc_clocks/
  01_soc_clocks_extraction_rules.md
  extract_soc_01_clocks.py

02_soc_clock_timing/
  02_soc_clock_timing_form_spec.md
  extract_soc_02_clock_timing.py
  02_soc_clock_timing_budget_prects_demo.xlsx
  02_soc_clock_timing_budget_postcts_demo.xlsx
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

注意：clock mux、test clock、scan clock、mbist clock 相关关系要谨慎，不能为了消除 warning 随意 common 化。

主要功能：

- 定义所有 mode 下都成立的 asynchronous clock group。
- 定义所有 mode 下都成立的 logically exclusive / physically exclusive clock group。
- 收敛 SoC 级跨 clock domain 的默认 STA 分析边界。
- 只表达 clock relationship，不表达 clock 自身属性。

不放：

- 依赖 scan/test/mbist/gpio mode 的 clock group。
- 仅为了屏蔽 timing violation 而没有架构依据的 clock group。
- harden-to-harden 特定 path exception。
- `set_clock_uncertainty` / `set_clock_latency` / `set_clock_transition`，这些放 `02_soc_clock_timing_<stage>_<corner>.sdc` 或对应 scenario/stage/corner 文件。

### 2.4 `common/04_soc_io_pads.sdc`

定义 SoC 顶层 IO/pad timing environment。

pad 本身可以 common，但真正的 input/output delay 可能依赖 scenario。GPIO/inout pad 后续可能拆到 `gpio_in.sdc` / `gpio_out.sdc`。

主要功能：

- 定义 SoC 顶层 pad/port 分组。
- 引用 `01_soc_clocks.sdc` 中定义的 virtual clock。
- 定义 common 的 pad/input/output delay，例如固定方向、固定协议、所有 func mode 都成立的 `set_input_delay` / `set_output_delay`。
- 定义 common 的外部输入驱动模型，例如 `set_driving_cell` / `set_drive`。
- 定义 common 的输出负载，例如 `set_load`。
- 定义 common 的输入 transition/slew，例如 `set_input_transition`。
- 定义 IO 侧 design rule 约束，例如作用于 top IO port 的 `set_max_transition` / `set_max_capacitance`。
- 记录 GPIO/inout pad 的方向依赖关系，为后续 `gpio_in.sdc` / `gpio_out.sdc` 拆分做准备。

不放：

- harden 内部接口约束。
- harden-to-harden exception。
- `create_clock` / `create_generated_clock`，包括 IO virtual clock；所有 clock object 都放 `01_soc_clocks.sdc`。
- 依赖 GPIO 方向、DFT、MBIST 的 IO delay、driving model、load 或 transition。
- 全芯片内部 design rule 约束；这类后续如有需要可单独规划。

注意：

- `set_driving_cell`、`set_drive`、`set_input_transition` 都是在描述 input port 的外部驱动/输入 slew，不应对同一组 input port 无规则重复设置。
- 若 flow 同时需要 driving cell 和 input transition，必须在 04 的实现规则中明确优先级和适用端口集合。

### 2.5 `common/10_harden_x_if.sdc`

定义 SoC 视角的 harden interface 约束。

它不是直接 source harden 内部 full SDC，而是接收 harden SoC integration SDC 中对 SoC 有意义的边界约束。

主要功能：

- 汇总 harden 边界 pin group，例如输入接口、输出接口、控制 pin、模式 pin。
- 放置所有 mode 都成立的 harden interface timing 约束。
- 放置 harden integration SDC 中可直接提升到 SoC 级的边界约束。
- 作为 harden owner 交付信息和 SoC 约束体系之间的转换层。

不放：

- harden 内部 full SDC。
- harden 内部 signoff exception。
- mode-specific scan/mbist/test constraint。
- harden-to-harden 跨模块 exception，这类放 `20_harden_to_harden_exception.sdc`。

### 2.6 `common/20_harden_to_harden_exception.sdc`

定义 harden-to-harden path 相关 exception。

这是高风险文件。只放所有 mode 都成立、且有架构依据的 exception；mode-specific exception 下沉到对应 scenario。

主要功能：

- 定义 harden A output 到 harden B input 之间的 common exception。
- 收敛所有 mode 都成立的 false path、multicycle path、max delay/min delay。
- 记录每条 exception 的设计依据、owner 和适用范围。

不放：

- 没有设计依据、只为清 timing 的 exception。
- 依赖 func/scan/mbist/gpio mode 的 exception。
- clock group，这类放 `03_soc_clock_groups.sdc`。
- feedthrough 结构约束，这类优先放 `30_feedthrough.sdc`。

### 2.7 `common/30_feedthrough.sdc`

定义 feedthrough 相关约束，例如 harden-to-pad、pad-to-harden、harden-to-harden 的纯穿通路径。

如果 feedthrough 在某些 mode 下经过 mux/isolation 改变，需要下沉到 scenario。

主要功能：

- 定义 SoC 中结构性 feedthrough path 的约束。
- 处理 pad-to-pad、pad-to-harden、harden-to-pad、harden-to-harden 的纯穿通路径。
- 对不经过寄存器、只作为连接通路的 path 做统一收口。

不放：

- 普通同步 timing path 的 exception。
- mode-specific mux/isolation 后才成立的 feedthrough 约束。
- clock 定义和 clock group。

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
  scenarios/<scenario>_io_pads.sdc

Stage 6: harden/interface/feedthrough
  common/10_harden_x_if.sdc
  common/30_feedthrough.sdc
  scenarios/<scenario>_harden_if.sdc
  scenarios/<scenario>_feedthrough.sdc

Stage 7: path exception
  common/20_harden_to_harden_exception.sdc
  scenarios/<scenario>_exceptions.sdc
```

注意：Stage 3 与其它 stage 的装配模型不同。

- 03/04/10/20/30 等 stage 采用 **common + scenario 叠加**：scenario 文件只追加该 scenario 专属约束，不覆盖 common 已声明的同一对象，因此 common 和 scenario 文件按顺序都 source。
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

# Stage 6: harden/interface/feedthrough
source common/10_harden_x_if.sdc
source common/30_feedthrough.sdc

# Stage 7: exceptions last
source common/20_harden_to_harden_exception.sdc
source scenarios/func_exceptions.sdc
```

如果暂时不拆 `func_pre.sdc` / `func_exceptions.sdc`，也可以先由 `scenarios/func.sdc` 内部分段组织，但仍应保留上述 stage 顺序。

### 3.3 `set_case_analysis` 注入点

`set_case_analysis` 属于 scenario setup，不建议放在 common 文件里。

推荐注入位置：

- clock mux select：必须在依赖 mux 选择的 generated clock 和 clock group 前注入。
- PLL bypass/config mode：必须在相关 clock creation 或 scenario clock overlay 前注入。
- scan/test/mbist/gpio direction：放在对应 scenario 的 pre-setup 阶段。

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
   common/10_harden_x_if.sdc
   common/30_feedthrough.sdc

3. common path exception
   common/20_harden_to_harden_exception.sdc

4. scenario-specific exception
   scenarios/<scenario>_exceptions.sdc
```

注意：

- `set_clock_groups` 是 clock relationship，不放到 path exception 文件里。
- `false_path`、`multicycle_path`、`max_delay`、`min_delay` 之间不要靠 source 先后来“覆盖”冲突。
- 如果一条 path 同时命中多个 exception，应在 review/report 中显式标记，优先修正约束归属。
- mode-specific exception 不进入 common，必须下沉到对应 scenario。

## 4. 相关文档

- [Project Context](00_project_context.md)：当前工作状态、关键决策、脚本状态和新会话接力信息。
- [Harden SoC Integration SDC Requirements](harden_sdc_requirements.md)：harden/IP 交付给 SoC 使用的 SDC 要求，包括 flatten/normalized 规则和 clock 声明规则。
- [01_soc_clocks](01_soc_clocks/01_soc_clocks_extraction_rules.md)：`common/01_soc_clocks.sdc` 的提取规则和脚本说明。
- [02_soc_clock_timing](02_soc_clock_timing/02_soc_clock_timing_form_spec.md)：`02` clock timing budget 表单、生成机制和检查规则。
