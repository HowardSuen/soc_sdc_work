# 01_soc_clocks.sdc Extraction Rules

本文档记录 `common/01_soc_clocks.sdc` 的自动提取/生成规则草案。当前阶段仅考虑 **func 单一模式**，scan/mbist/gpio 场景先不参与第一版生成。

## 1. 目标

脚本目标是根据 SoC 集成表单和各 harden 的 flattened SoC integration SDC，生成：

- `common/01_soc_clocks.sdc`
- `clock_inventory.csv`
- `clock_check_report.txt`

其中 `01_soc_clocks.sdc` 只放 SoC 级 clock 声明，不放 clock timing budget、clock group、false path、multicycle、IO delay、mode case analysis 或 exception。

所有 clock object 都归属 `01_soc_clocks.sdc`，包括 IO delay 使用的 virtual clock。第一版脚本从 harden SDC 和集成表单生成 top/harden clock；如果执行目录存在 `virtual_clocks.csv`，也会从该文件生成 virtual clock。virtual clock 不应放到 `04_soc_io_pads.sdc`。

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

约定：

- `info_all.xlsx` 放在脚本执行目录。
- 所有 owner 子 xlsx 和 harden SDC 也放在脚本执行目录。
- 脚本不跨目录搜索输入文件。
- 一个 harden/module 可能被例化多次，脚本必须以 `inst_name` 作为 SoC 实例的唯一键。
- `module_name` 只用于匹配同一种 harden 的 SDC；生成 clock name 和 SoC pin path 必须使用 `inst_name`。

### 2.2 owner 子 xlsx

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
- `Inout Connectivity`
- `Inout Name`

当前最关键字段是：

- `From Whom = top.xxx`：表示该 input 来源于 SoC 顶层 port/pad。
- `From Whom = u_harden.port`：表示该 input 来源于另一个 harden 的 output port。
- `From Whom = 1'b0/1'b1/...`：表示 tie 常量，不作为 clock source。

### 2.3 harden flattened SoC integration SDC

每个 harden 应提供边界扁平化、语义明确的 SoC integration SDC。脚本从中提取：

- `create_clock`
- `create_generated_clock`
- `create_generate_clock`

其他 harden 内部约束暂不进入 `01_soc_clocks.sdc`，只记录到 skipped/ignored report。

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

SDC 匹配约定：

- 若 `info_all.xlsx` 提供 `sdc_path` / `sdc_file` 字段，则优先使用该字段对应的本地文件名。
- 否则脚本在执行目录中按 `<inst_name>.sdc`、`<module_name>.sdc`、`<file_path stem>.sdc` 顺序匹配。
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

如果一个 output port 上需要多个 clock，例如 mux 输出同时存在多个 mode clock，第一版 func-only 暂不展开；后续 scenario 版本再扩展命名规则。

## 4. Input Clock 处理规则

harden input clock 约束需要读取，但不一定输出到 `01_soc_clocks.sdc`。

### 4.1 input clock 来源于 top/pad

如果 harden input clock 的 `From Whom` 是：

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

如果 harden input clock 的 `From Whom` 是：

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

如果 clock input 的 `From Whom` 是 tie 常量、空白或无法解析对象，脚本不生成 clock，并在 `clock_check_report.txt` 中报 warning/error。

## 5. Output Clock 处理规则

harden output clock 是 `01_soc_clocks.sdc` 的主要生成来源。

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
- 当前 func scenario 只需要明确 period，不声明与输入 ref clock 的关系。

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

如果该 output clock 在当前 scenario 下应作为独立 root，harden SDC 应使用 `create_clock`，而不是交付缺少 `-source` 的 `create_generated_clock`。

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

- `info_all.xlsx` 中的 harden instance 是否都有对应 harden SDC。
- 子 xlsx 中的 sheet 是否能对应到 `inst_name`。
- harden input clock 是否都有 `From Whom`。
- `From Whom = u_xxx.port` 的上游 output clock 是否存在。
- input clock 期望 period 是否与上游 output clock period 一致。
- 同名 clock 是否冲突。
- `create_generated_clock` 是否带可解析 `-source`；缺失或无法解析时为 error，并跳过该 clock。
- `create_generated_clock -source` 是否能映射到当前 harden port 或已知 SoC 对象。
- harden SDC 中是否出现内部层级对象，若出现则 warning。
- scan/mbist/test/gpio 相关 clock 是否被误放入 func-only 生成结果。
- clock name/port 中出现 scan/mbist/bist/jtag/test 等 token 时，只能产生 warning，不能自动 skip；scenario 分类和删除必须依赖显式表单/场景规则。

检查报告应给出可交付给 harden owner 的定位信息：

- harden SDC 文件名与命令起始行号。
- SoC instance、port、clock name。
- 明确的 rule id，例如 `CLOCK_GENERATED_MISSING_SOURCE`、`CLOCK_TARGET_NOT_IN_OWNER_SHEET`。
- 原始 SDC 命令的单行化文本。
- 对应 action，例如 `skipped`、`check_only`、`emit_output_clock`。

## 8. 输出文件

### 8.1 `common/01_soc_clocks.sdc`

生成 SoC 级 func clock 声明。

第一版脚本入口：

```bash
python3 /path/to/soc_sdc_work/01_soc_clocks/extract_soc_01_clocks.py
```

默认从执行目录读取：

```text
info_all.xlsx
port_*.xlsx
*.sdc
virtual_clocks.csv   # optional
```

默认输出：

```text
common/01_soc_clocks.sdc
clock_inventory.csv
clock_check_report.txt
```

### 8.2 `clock_inventory.csv`

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
note
```

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

## 9. 当前阶段限制

第一版仅支持 func 单一模式。

暂不处理：

- scan/mbist/gpio scenario clock。
- 同一 target pin 上多 clock/mux 的 `-add` 复杂场景。
- 复杂 Tcl proc 或外部 include。
- 从 harden 内部 pin 自动推断边界 clock。
- 根据名字自动猜测 clock 类型并据此删除/跳过 clock。
