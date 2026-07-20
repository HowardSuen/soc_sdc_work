# 01_soc_clocks.sdc Extraction Rules

本 stage 遵守 [Shared Script Runtime Rules](../docs/shared_script_runtime_rules.md)。一个 run root 只处理一个场景，01 不接收 scenario。本文保留原 clock 提取/生成方法学，只把互联真源和销账改为 `inputs/port_*.xlsx`。

## 1. 目标

target 模式根据 `inputs/info_all.xlsx`、`inputs/port_*.xlsx`、00 harden SDC manifest 和各 available harden SDC 生成：

- `01_result/01_soc_clocks.sdc`
- `01_middle/clock_inventory.csv` 和 meta
- `01_result/reports/clock_check_report.txt`
- 对 port workbook Used 状态列的原地更新

其中 `01_soc_clocks.sdc` 只放 SoC 级 clock 声明，不放 clock timing budget、clock group、false path、multicycle、IO delay、mode case analysis 或 exception。

`01_middle/clock_inventory.csv` 是本 run 唯一 clock universe，02/03/04/10/20/30 只能读取这一份 active inventory。

所有 **SoC-visible clock object** 都归属 `01_soc_clocks.sdc`。target 模式从 harden DC output SDC 和 port workbook 的 direct connectivity 生成 top clock、harden output clock；如果存在 `virtual_clocks.csv`，也会生成 SoC 级 virtual clock。virtual clock 不应放到 `04_soc_io_pads.sdc`。

harden-origin clock 的 ownership 规则：

- target 位于 harden output port 的 `create_clock` / `create_generated_clock`：提升到 01，target 改写为 SoC instance output pin，并进入 `clock_inventory.csv`。
- target 位于 harden input port 的 clock declaration：只作为 top/upstream clock 来源、period/waveform 和连接一致性检查信息；不在 harden instance input pin 上重复创建 clock。
- target 位于 harden internal pin/net 的 local/generated clock：不提升到 01，不进入 clock inventory，由 harden 内部 SDC 保留。
- harden DC output SDC 中无 target 的 private virtual clock：不自动提升到 01；只有项目通过 `virtual_clocks.csv` 显式声明的 SoC 级 virtual clock 才进入 01。

因此，“所有 clock object 归 01”只指 SoC-visible clock，不包括 harden internal/private clock。

解析 `create_generated_clock` 时，脚本必须显式区分 positional target object 和 `-source` 后的 source object；SDC option 顺序是自由的，不能假设 target 一定是最后一个 `[get_ports ...]`。实现上应在 parse 阶段记录 target token 位置，rewrite 阶段只替换这些 target token，不能用“从后往前找 get_ports”的方式推断 target。

## 2. 输入

### 2.1 `info_all.xlsx`

记录 SoC 下 harden/module 的基本实例信息，例如：

- `module_name`
- `inst_name`
- `file_path`
- `owner`
- 子 xlsx 信息，若后续表单加入该字段

脚本根据该表获取 SoC 中有多少个 harden、每个 harden 的 module 名和 instance 名。

target 约定：

- `info_all.xlsx` 固定在 `<run_root>/inputs/`。
- 所有 `port_*.xlsx` 和 harden SDC 也从 `<run_root>/inputs/` 解析。
- 一个 harden/module 可能被例化多次，脚本必须以 `inst_name` 作为 SoC 实例的唯一键。
- `module_name` 只用于匹配同一种 harden 的 SDC；生成 clock name 和 SoC pin path 必须使用 `inst_name`。
- owner 子 xlsx 的 sheet name 应与 `inst_name` 精确一致。脚本可提供大小写/首尾空格不敏感的兜底匹配，但必须 warning；完全无法对应任何 `inst_name` 的孤儿 sheet 也必须 warning。

### 2.2 `port_*.xlsx`

每个 owner 子 xlsx 中，一个 sheet 对应一个 harden instance。脚本读取以下连接信息：

- `Input`
- `Input Width`
- `Input Used Width`
- `From Whom`
- `Output`
- `Output Width`
- `Output Used Width`
- `To Top`
- `Inout`
- `Inout Width`
- `Inout Connectivity`
- `Inout Name`

当前最关键字段是：

- `From Whom = top.xxx`：表示该 input 来源于 SoC 顶层 port/pad。
- `From Whom = u_harden.port`：表示该 input 来源于另一个 harden 的 output port。
- `From Whom = 1'b0/1'b1/...`：表示 tie 常量，不作为 clock source。

port/range 使用共享 canonical bit 规则。scalar canonical index 为 0；vector 按实际 HDL index 展开。例如 `output [1:0] clk_o` 的两个 bit 分别进入 clock inventory，并在 `Output Used Width` 中 union `0,1`。

input clock 来源直接由 destination row 的 `From Whom` 解析。compact range 必须精确配对；缺少 source、重复 driver、未知 endpoint 或宽度不匹配时必须 error/保持 unresolved，不能猜测 source bit。

`Input Used Width`、`Output Used Width` 和 `Inout Name` 是销账状态列，不得作为结构 width/name 输入。

### 2.3 harden DC output SDC

对 harden-SDC manifest 中 `available` 的 harden DC output SDC，脚本只从其中识别可提升到 SoC 层级的 boundary clock declaration，并提取：

- `create_clock`
- `create_generated_clock`
- `create_generate_clock`

其他 harden 内部约束暂不进入 `01_soc_clocks.sdc`，只记录到 skipped/ignored report。

#### 2.3.1 Harden SDC 缺失时

01 默认允许部分 harden SDC 尚未交付。target runtime 必须从 `00_middle/harden_sdc_manifest.csv` 读取文件状态：

- `available`：正常解析 boundary clock declaration。
- `missing`：记录 warning/incomplete，跳过该 harden SDC，继续处理其它 available harden。
- `not_required`：只用于明确不需要 harden SDC 的非 harden/特殊对象，不能为了消除 missing warning 滥用。

missing SDC 对应的 clock input/output bit 保持 Used 状态不变，不生成 clock，也不因为未提取到 clock command 而判定“该 port 不是 clock”。若集成表单已明确该 output 是 clock source，report 应生成 `CLOCK_SOURCE_SDC_MISSING` 待办项。只有受控 manual overlay 或其它不依赖该 harden SDC 的 approved clock declaration 可以独立生成并销账。

输出 SDC、inventory/meta 和 report 必须记录 `Run completeness: partial` 和 missing instance。开启 `--require-complete-harden-sdc` 后，任一 required harden SDC 缺失才升为全局 error。

01 接受以下 manifest 参数：

```text
--harden-sdc-manifest <path>
--require-complete-harden-sdc
```

target runtime 默认读取：

```text
00_middle/harden_sdc_manifest.csv
```

manifest 使用最小字段：

```text
clock_record_id
inst_name
module_name
sdc_path
availability_status
note
```

`note` 可选。相对 `sdc_path` 统一相对 `--run-root` 解析，不扫描其它目录兜底。01 只检查 available 文件是否存在并直接读取当前内容；不要求 `file_digest`、`mapping_source` 或 manifest meta，也不使用 digest 阻断运行。

harden SDC 更新后的推荐确认方式是从同一份干净 port workbook 初始化两个独立 run root，分别完整运行相关 stage，再对 `*_result/`、`*_middle/` 和 Used 状态列做 diff。SHA-256 仍可由 `--debug` 自动记录，用于定位输入版本。

### 2.4 `virtual_clocks.csv`

可选输入文件，放在脚本执行目录。用于生成 IO delay 等外部接口参考 virtual clock。

最小字段：

```text
clock_name,period
v_pcie_ref_clk,10.000
v_gpio_ref_clk,20.000
```

可选字段：

```text
waveform,note
{0 5},PCIe external reference clock
```

生成示例：

```tcl
create_clock -name v_pcie_ref_clk -period 10.000
```

如果同名 virtual clock 重复出现，脚本只输出第一条，并在 report 中记录重复项。

### 2.5 Direct connectivity

01 直接扫描所有 port workbook，并从 `From Whom` 建立 input clock 的 exact bit edge。range 重编号必须按 source/sink 声明方向配对，例如 `u_a.clk_o[1] -> u_b.clk_i[0]`。01 可以在 debug artifact 中发布本 stage 的解析结果，但该结果不是 00 machine input，也不能替代原始表单。

### 2.6 `01_soc_clocks_manual.sdc`

可选手工 overlay，用于补充无法从 harden output boundary declaration 自动提取、但 SoC 层级必须显式创建的 clock。典型场景是 harden DC output SDC 只在内部逻辑 pin 上声明 clock，没有在 output port 上交付对应 `create_clock` / `create_generated_clock`，而 SoC 集成表单确认该 output port 会作为 SoC-visible clock source。

手工 clock 不应直接编辑生成后的 `01_result/01_soc_clocks.sdc`，避免下次生成被覆盖。统一写入：

```text
01_soc_clocks_manual.sdc
```

01 按以下顺序装配：

```text
自动提取的 top/output clocks
+ virtual_clocks.csv 生成的 SoC virtual clocks
+ 01_soc_clocks_manual.sdc
= 01_result/01_soc_clocks.sdc
```

manual overlay 只允许 SoC-visible `create_clock` / `create_generated_clock`。target 必须是明确的 SoC top port 或 harden instance output pin，例如：

```tcl
create_generated_clock \
  -name u_harden_clk_o \
  -source [get_pins u_harden/clk_i] \
  -divide_by 2 \
  [get_pins u_harden/clk_o]
```

若 internal source 无法在 SoC 层级解析，应由 owner 给出可解析的 input/output source，或明确把 output clock 声明为独立 root；01 不从 harden 内部 clock definition 自动推导边界 clock。

manual 与 auto/virtual clock 之间必须检查：

- clock name 冲突。
- target object 冲突。
- 同一 target 上多 clock 是否显式使用并 review `-add`。
- generated clock 的 source/master 是否存在于最终 01 clock universe。
- manual target 是否与 SoC 集成表单中的 top port 或 harden output canonical bit 对应。

manual clock 通过检查并进入最终 01 后，应和自动 output clock 一样进入 final inventory、更新 Used bit，并可被 02/03 引用。

### 2.6 SDC 匹配约定

- 若 `info_all.xlsx` 提供 `sdc_path` / `sdc_file` 字段，则优先使用该字段对应的本地文件名。
- 否则脚本在执行目录中按 `<inst_name>.sdc`、`<module_name>.sdc`、`<file_path stem>.sdc` 顺序匹配。
- 若实际文件名带 `_empty.sdc` 后缀，脚本可把去掉 `_empty` 后的 stem 作为兜底匹配名，例如 `foo_empty.sdc` 可匹配 `foo`。
- 多个 `inst_name` 可以共享同一个 `<module_name>.sdc`，但输出 clock 必须按各自 `inst_name` 独立生成。

## 3. 基本生成原则

### 3.1 层级上升

harden SDC 默认使用 harden 自身 port 级对象：

```tcl
[get_ports clk_i]
[get_ports clk_o]
```

SoC 级输出时，脚本映射为：

```tcl
[get_pins u_harden/clk_i]
[get_pins u_harden/clk_o]
```

### 3.2 Clock 命名

SoC clock name 建议统一使用 harden instance + port name：

```text
<inst_name>_<port_name>
```

例如：

```text
u_harden_a_clk_pll
u_harden_b_clk_o
```

理由：

- 避免不同 harden 交付相同 clock name 导致重名。
- clock name 能直接反映 SoC 实例和端口位置。
- 后续 clock group、exception、report 更容易追溯。

如果一个 output port 上需要多个 clock，例如 mux 输出同时存在多个 mode clock，第一版不自动展开；应在当前 run 的 manual overlay 中显式声明并 review `-add` 语义。

若 clock target 是 bus bit，clock name 必须稳定编码 bit index，避免 `[]` 进入 clock name。例如：

```text
u_harden_a_clk_o_bit0
u_harden_a_clk_o_bit1
```

第一版不允许一条 clock 命令用整 bus/range target 隐式创建多个 clock。harden SDC 应拆成 scalar/explicit bit target；01 脚本不自行展开整 bus/range target，遇到这类命令必须报 error，不得静默只取第一个 bit。

## 4. Input Clock 处理规则

harden input clock 约束需要读取，但不一定输出到 `01_soc_clocks.sdc`。

input boundary clock declaration 永远不是 harden clock producer。它只能触发 `emit_top_clock`、`duplicate_top_clock` 或 `check_only` 等 SoC 来源处理，不允许直接生成 `[get_pins <inst>/<input_port>]` 上的新 primary clock。

input clock 的 source 解析顺序为：

```text
1. 读取当前 destination row 的 From Whom。
2. 按 source/sink range 方向展开为 exact bit edge。
3. 若无法解析为 top 或 upstream harden output，当前 input clock 不生成，并在 report 中记录。
```

因此，对于 vector clock input，`From Whom` 和 row 的 port/range 是 source bit 配对的权威来源。

### 4.1 input clock 来源于 top/pad

如果解析后的 input clock source 是：

```text
top.xxx
```

则该 clock 是 SoC 外部进入的 primary clock。脚本应在 `01_soc_clocks.sdc` 中生成或保留 `create_clock`。

对象映射规则需要后续按 pad 建模方式确认：

- 若 SoC STA 在顶层 port 建 clock，使用 `[get_ports xxx]`。
- 若 SoC STA 要在接收 harden/pad instance pin 建 clock，使用 `[get_pins u_harden/clk_i]`。

第一版推荐优先生成到 SoC 顶层 port：

```tcl
create_clock \
  -name <top_clock_name> \
  -period <period> \
  [get_ports xxx]
```

### 4.2 input clock 来源于其他 harden output

如果解析后的 input clock source 是：

```text
u_harden_a.clk_o
```

则该 input clock 不重复生成 `create_clock`。上游 harden output 必须已经在对应 harden SoC integration SDC 中显式声明为 output clock，并由脚本作为 clock producer 建 clock。

SoC 侧不依赖工具自动穿透 harden 推断 output clock；如果当前 harden 会把该 input clock 再输出给 SoC 或其他 harden，当前 harden SDC 也必须显式交付 output/forwarded generated clock。

该 input clock 仍用于：

- 校验上游 output clock 是否存在。
- 校验 period/waveform 是否与当前 input clock 期望一致。
- 作为当前 harden output `create_generated_clock -source` 的直接 source 对象。

示例：

```text
u_harden_a/clk_o -> u_harden_b/clk_i -> u_harden_b/clk_o
```

`u_harden_b/clk_i` 不生成 `create_clock`，但可以作为：

```tcl
-source [get_pins u_harden_b/clk_i]
```

### 4.3 input clock 来源于常量或非法来源

如果 clock input 的解析来源是 tie 常量、空白或无法解析对象，脚本不生成 clock，并在 `clock_check_report.txt` 中报 warning/error。

## 5. Output Clock 处理规则

harden output clock 是 `01_soc_clocks.sdc` 的主要生成来源。

只要 `create_clock` / `create_generated_clock` 的 positional target 能明确解析为 owner harden 的 output canonical port/bit，就应作为 01 output clock 候选提取。SoC 集成表单用于确认该 output 的方向、bit key、连接去向和 clock 使用情况；target 不是 output，或 port/bit 无法在 owner sheet 中确认时，不得按 output clock emit。

internal pin/net target 和 private virtual clock 不进入本节流程，应在 report 中记录为 skipped（例如归类为 internal/private 或 `CLOCK_TARGET_NOT_GET_PORTS`），但不写入 `01_soc_clocks.sdc` / `clock_inventory.csv`。

### 5.1 harden output 是 `create_clock`

如果 harden SDC 中 output port 使用 `create_clock`，SoC 级也生成 `create_clock` 到该 harden instance output pin：

```tcl
create_clock \
  -name u_harden_a_clk_o \
  -period <period> \
  [get_pins u_harden_a/clk_o]
```

适用情况：

- PLL 配置/相位关系未定。
- harden 文档要求该 output clock 作为独立 root。
- 当前 run 的架构只需要明确 period，不声明与输入 ref clock 的关系。

### 5.2 harden output 是 `create_generated_clock`

如果 harden SDC 中 output port 使用 `create_generated_clock`，SoC 级保持 generated clock 形式，并做对象上升：

```tcl
create_generated_clock \
  -name u_harden_a_clk_o \
  -source [get_pins u_harden_a/clk_i] \
  [get_pins u_harden_a/clk_o]
```

规则：

- target output port 映射为当前 harden instance output pin。
- `-source` 若是当前 harden input port，映射为当前 harden instance input pin。
- `create_generated_clock` 必须带可解析的 `-source`；若缺失或无法解析，脚本报 `ERROR`，该 clock 不写入 `01_soc_clocks.sdc`。
- `-source` 若是当前 harden output/internal 不可见对象，脚本记录 warning，需要 harden SDC 修正为边界 port 级。
- 已明确的 `-multiply_by`、`-divide_by`、`-combinational`、`-edges`、`-waveform` 等选项应保留。

如果该 output clock 在当前 run 下应作为独立 root，harden SDC 应使用 `create_clock`，而不是交付缺少 `-source` 的 `create_generated_clock`。

### 5.3 harden output 是转发 clock

如果 harden SDC 使用：

```tcl
create_generated_clock -combinational
```

SoC 级也保留 `-combinational`：

```tcl
create_generated_clock \
  -name u_harden_b_clk_o \
  -source [get_pins u_harden_b/clk_i] \
  -combinational \
  [get_pins u_harden_b/clk_o]
```

## 6. Source 追溯规则

脚本需要维护 clock source 追溯表，但 **不强制把 `create_generated_clock -source` 上升到最源头**。

### 6.1 SDC 中的 `-source`

`01_soc_clocks.sdc` 中的 `-source` 推荐保持为当前 harden 的直接 source pin。

示例：

```text
LVDS -> u_harden_a/clk_pll -> u_harden_b/clk_i -> u_harden_b/clk_o
```

推荐输出：

```tcl
create_generated_clock \
  -name u_harden_b_clk_o \
  -source [get_pins u_harden_b/clk_i] \
  -combinational \
  [get_pins u_harden_b/clk_o]
```

而不是强行写成：

```tcl
-source [get_pins u_harden_a/clk_pll]
```

理由：

- `-source` 应描述当前 generated clock 在本级生成/转发点的直接来源。
- 保留局部拓扑更利于 STA 和人工 review 理解 clock path。
- 强制上升到最源头可能丢失中间 harden 的转发关系。

如果 harden SDC 使用 `-source [get_clocks <name>]`，脚本必须按同一 harden 内的 clock `name_map` 把 `<name>` 重映射到 SoC 级 clock name。无法映射的 clock name 不应静默通过，必须 warning，例如 `CLOCK_SOURCE_GET_CLOCKS_UNMAPPED`。

### 6.2 报告中的 root source

脚本内部应追溯每个 clock 的 root source，用于检查和报告。

示例：

```text
clock_name, direct_source, root_source
u_harden_b_clk_o, u_harden_b/clk_i, u_harden_a/clk_pll
u_harden_c_clk_o, u_harden_c/clk_i, u_harden_a/clk_pll
```

## 7. 检查项

脚本至少生成以下检查：

- `info_all.xlsx` 中的 harden instance 是否都在 harden-SDC manifest 中有唯一记录。`missing` 在默认 partial mode 下是 warning/incomplete，不阻断其它 harden；manifest 缺行、冲突映射或 strict mode 下 missing 才是 error。
- 子 xlsx 中的 sheet 是否能对应到 `inst_name`，包括 inst->sheet 和 sheet->inst 两个方向；大小写/首尾空格兜底匹配必须 warning。
- 是否能从 `From Whom` 和 source/sink range 建立 exact bit-to-bit edge；不完整或重复 dst edge 应 error。
- harden input clock 是否能通过 port workbook 解析来源。
- 解析后来源为 `u_xxx.port` 的上游 output clock 是否存在。
- input clock 期望 period 是否与上游 output clock period 一致。
- `create_clock` 是否填写 `-period`；缺失时 warning。
- 同名 clock 是否冲突。
- `create_generated_clock` 是否带可解析 `-source`；缺失或无法解析时为 error，并跳过该 clock。
- `create_generated_clock -source` 是否能映射到当前 harden port 或已知 SoC 对象；若 `-source [get_ports ...]` 中的 port 不在 owner sheet 的 Input/Output/Inout 中，应报 error 并跳过该 clock。
- 单条 clock 命令是否作用于多个 target port；第一版不自动拆分，多 target 应报 error 并跳过，要求 harden SDC 拆成一端口一条 clock 命令。
- clock target/source 是否符合共享 canonical bit key。整 bus/range clock command target/source 第一版不自动拆为多个 clock；必须在 harden SDC 中拆成 scalar/explicit bit。表单 connectivity range 仍必须正常展开。否则 error。
- clock 命令是否带 `-add`；第一版不语义展开同一 target pin 多 clock/mux 场景，遇到 `-add` 必须 warning，例如 `CLOCK_ADD_OPTION_OUT_OF_SCOPE`。
- clock target 若为 harden internal pin/net 或 private virtual clock，应在 report 中记录 skipped，不得进入 01 inventory；若该命令同时被其它 SoC-visible clock 引用但无法解析 ownership，应 warning/error。
- clock target 若为 harden boundary input port，不得作为 output clock emit；只允许进入 input source/check-only 流程。
- clock target 若为 harden boundary output port，必须能映射到 owner sheet 的 exact output canonical bit；否则 error。
- scan/mbist/test/gpio 相关 clock 是否与当前 run 的输入集合一致。
- clock name/port 中出现 scan/mbist/bist/jtag/test/gpio 等 token 时，只能产生 warning，不能自动 skip；是否有效由当前 run 的输入表单和 SDC 决定。

检查报告应给出可交付给 harden owner 的定位信息：

- harden SDC 文件名与命令起始行号。
- SoC instance、port、clock name。
- 明确的 rule id，例如 `CLOCK_GENERATED_MISSING_SOURCE`、`CLOCK_TARGET_NOT_IN_OWNER_SHEET`。
- 原始 SDC 命令的单行化文本。
- 对应 action，例如 `skipped`、`check_only`、`emit_output_clock`。

## 8. 输出文件

### 8.1 `01_result/01_soc_clocks.sdc`

生成 SoC 级 func clock 声明。

第一版脚本入口：

```bash
python3 "/path/to/soc_sdc_work/Soc SDC脚本/01_soc_clocks/01_extract_soc_clocks.py"
```

target layout 入口：

```bash
python3 "/path/to/01_extract_soc_clocks.py" \
  --run-root "/path/to/run_root"
```

target 默认读取：

```text
inputs/info_all.xlsx
inputs/port_*.xlsx
inputs/run_context.csv
inputs/required_views.csv
00_middle/harden_sdc_manifest.csv
00_middle/port_accounting_delta.meta
00_middle/stage_completion.meta
inputs/virtual_clocks.csv                                  # optional
inputs/01_soc_clocks_manual.sdc                            # optional
```

target 输出：

```text
01_result/01_soc_clocks.sdc
01_middle/clock_inventory.csv
01_middle/clock_inventory.meta
01_middle/port_accounting_delta.csv
01_middle/port_accounting_delta.meta
01_middle/stage_completion.meta
01_result/reports/clock_check_report.txt
```

`01_soc_clocks.sdc` 的输出顺序应尽量按 clock 依赖拓扑排序：被 `-source [get_clocks ...]`、`-source [get_ports ...]` 上溯到的已 emitted clock，或 `root_source` 对应的已 emitted clock，应先于依赖它的 generated/forwarded clock 输出。无法解析的依赖保持原稳定顺序；检测到排序环时 warning 并保留剩余原顺序。

最终 `01_result/01_soc_clocks.sdc` 定义本 run 的 SoC-visible clock object。01 必须在 auto + virtual + manual 装配完成后，对 final SDC 做回读/reconcile，再生成 `clock_inventory.csv`。不能先生成 auto-only inventory，再追加 manual SDC。

01 只按 exact canonical bit 更新 Used 状态。对于 vector clock，不能用 `clk_o` 或 `clk_o[1:0]` 笼统销账；必须逐 bit union 到对应 row 的 `Input Used Width`、`Output Used Width` 或 `Inout Name`。诊断模式不写 workbook，并在 report 标记 accounting 未执行。

### 8.2 `clock_inventory.csv`

`01_middle/clock_inventory.csv` 是最终 `01_result/01_soc_clocks.sdc` 的机器可读 manifest，不是自动提取阶段的中间文件。每个最终有效 clock 都必须有一条 active record，包括 manual overlay clock；downstream 只读这一份 inventory。

建议字段：

```text
inst_name
module_name
port_name
direction
clock_name
clock_kind
period
waveform
direct_source
root_source
from_whom
original_sdc
source_line
original_clock_name
original_command
final_action
source_type
source_file
final_sdc_digest
structure_digest
accounting_digest_before
accounting_digest_after
accounting_action
accounting_added_bits
note
```

- `clock_record_id = CLK_<full-sha256>`，hash 输入为 canonical clock name/kind/target tuple，不含 workbook row、Used 值或 file digest。
- `source_type` 至少区分 `auto_harden_output` / `auto_top` / `virtual_spec` / `manual_overlay`。
- `source_file` 记录原始 harden SDC、`virtual_clocks.csv` 或 `01_soc_clocks_manual.sdc`。
- `final_sdc_digest` 记录最终 01 SDC digest；02/03 用它检查 stale inventory。
- `structure_digest` 必须与 00 snapshot 一致；accounting before 必须等于 00 accounting after。
- inventory 中 active clock name/target/source 集合必须与最终 01 SDC 一致。最终 SDC 中存在 inventory 未记录的 clock，或 inventory 存在最终 SDC 已删除的 clock，均为 error。

### 8.3 `clock_check_report.txt`

记录 warning/error/skipped 约束，例如：

- 找不到对应 SDC。
- 找不到上游 clock source。
- period 不一致。
- harden SDC 使用内部层级。
- 无法解析 Tcl。
- 被忽略的非 clock SDC 命令。

报告中的 harden SDC 问题应采用类似格式：

```text
ERROR: blk.sdc:12: u_blk/clk_o: clock=out_clk: CLOCK_GENERATED_MISSING_SOURCE: generated clock has no parseable -source; command: create_generated_clock ...
```

### 8.4 Port accounting

01 可以销账：

- `emit_top_clock`：harden input/inout clock 已提升为 SoC top clock。
- `duplicate_top_clock`：多个 harden input 共用同一个 top clock，后续用户不重复 emit，但该 port 已由 top clock 覆盖。
- `check_only`：harden input clock 来自上游 harden output，01 已完成 upstream clock sink 检查。
- `emit_output_clock`：harden output clock / forwarded clock 已显式生成。

不销账：

- `emit_virtual_clock` / `duplicate_virtual_clock`，因为它们不是 harden port。
- `skipped` 或有 error 的 clock port。
- 非 clock data/control/reset port。

每次写回采用 bit-set union，因此重跑幂等。01 必须通过共享 multi-workbook transaction 提交，并输出 `01_middle/port_accounting_delta.csv/.meta`；每个 delta row 的 `owner_object_id` 引用 clock inventory 中的 clock/record ID。report 必须记录 workbook、sheet、row、port、added bits 和 final used bits。

事务、clock inventory、delta 和正式 SDC 全部成功且无 sync/error 后，01 才发布 `01_middle/stage_completion.meta`。diagnose-only 不得发布 complete 状态。

### 8.5 离线 Debug

脚本在内网运行时不依赖网络、远程日志或外部服务。可使用：

```bash
python3 01_extract_soc_clocks.py \
  --run-root /path/to/run_root \
  --diagnose-only \
  --debug \
  --debug-verbose
```

参数语义：

- `--debug`：生成结构化离线 debug bundle。
- `--debug-dir <path>`：指定 debug 目录，同时启用 debug。
- `--debug-verbose`：在 stdout 打印 report message 和每条 clock 的 action/target/direct source/root source。
- `--diagnose-only`：不写正式 SDC、不修改 port workbook，但仍生成 inventory、report 和 debug bundle。

target 默认 debug 目录为：

```text
01_middle/debug/01_soc_clocks/
```

主要文件：

```text
run_context.json          # resolved path、输入 digest、completeness、instance/clock 全量状态
manifest_decisions.csv    # 每个 instance 的 available/missing/not_required 和最终 SDC 选择
clock_records_debug.csv   # 包含 active、skipped、check_only、missing/incomplete 的完整记录
messages.log              # 原始 INFO/WARNING/ERROR message
repro_command.txt         # 可直接复现本次执行的命令
fatal_traceback.txt       # 仅未捕获异常时生成
fatal_repro_command.txt   # 未捕获异常对应复现命令
```

## 9. 当前阶段限制

一个 run 只支持一套外部准备好的模式输入，不在 01 内切换模式。

暂不处理：

- 同一 run 中同时装配 func/scan/mbist/gpio 多套模式 clock。
- 同一 target pin 上多 clock/mux 的 `-add` 复杂场景；脚本只保留原命令并报告 out-of-scope warning，不做自动裁决。
- 单条 clock 命令作用于多个 target port 的批量定义；应在 harden SDC 中拆成多条单 target 命令。
- 复杂 Tcl proc 或外部 include。
- 从 harden 内部 pin 自动推断边界 clock。
- 根据名字自动猜测 clock 类型并据此删除/跳过 clock。
