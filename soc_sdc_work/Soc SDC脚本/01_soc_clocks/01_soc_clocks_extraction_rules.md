# 01_soc_clocks.sdc Extraction Rules

本文档记录 `common/01_soc_clocks.sdc` 的自动提取/生成规则草案。当前阶段仅考虑 **func 单一模式**，scan/mbist/gpio 场景先不参与第一版生成。

## 1. 目标

脚本目标是根据 SoC 集成表单和各 harden 的 flattened SoC integration SDC，生成：

- `common/01_soc_clocks.sdc`
- `clock_inventory.csv`
- `clock_check_report.txt`
- `00_harden_port_inventory/removed_log/01_soc_clocks.removed`（当执行目录存在 `00_harden_port_inventory/pending` 时）

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
- owner 子 xlsx 的 sheet name 应与 `inst_name` 精确一致。脚本可提供大小写/首尾空格不敏感的兜底匹配，但必须 warning；完全无法对应任何 `inst_name` 的孤儿 sheet 也必须 warning。

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
- `Inout Width`
- `Inout Connectivity`
- `Inout Name`

当前最关键字段是：

- `From Whom = top.xxx`：表示该 input 来源于 SoC 顶层 port/pad。
- `From Whom = u_harden.port`：表示该 input 来源于另一个 harden 的 output port。
- `From Whom = 1'b0/1'b1/...`：表示 tie 常量，不作为 clock source。

owner 子 xlsx 中的 port/range 必须与 `00_harden_port_inventory` 的 canonical bit key 规则对齐。scalar port 直接使用 `port`；vector port 在机器处理中展开为 `port[index]`。例如 `output [1:0] clk_o` 若两个 bit 都是 clock source，应作为 `clk_o[0]`、`clk_o[1]` 两个独立 target 处理、进入 clock inventory，并分别从 pending 中删除。

`From Whom` 是 input clock 来源的兜底来源。若执行目录下存在 00 `connection_inventory.csv`，并且其中有当前 input bit 的 exact edge，脚本优先使用该 edge 的 source bit；只有缺少 exact edge 时才回退到 owner 子 xlsx 的 `From Whom`。

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

### 2.5 00 `connection_inventory.csv`

可选输入文件，默认路径：

```text
00_harden_port_inventory/connection_inventory.csv
```

用途：

- 为 harden input clock 提供权威 bit-to-bit source edge。
- 解决 bus/range 重编号，例如 `u_a.clk_o[1] -> u_b.clk_i[0]`。
- 避免 01 仅根据 owner `From Whom = u_a.clk_o` 自行猜测 source bit。

优先级：

```text
00 connection_inventory exact edge
  > owner 子 xlsx From Whom
  > unresolved / warning
```

第一版只在文件存在时读取；若文件不存在，脚本保持旧行为，继续使用 owner 子 xlsx 的 `From Whom`。

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

如果一个 output port 上需要多个 clock，例如 mux 输出同时存在多个 mode clock，第一版 func-only 暂不展开；后续 scenario 版本再扩展命名规则。

若 clock target 是 bus bit，clock name 必须稳定编码 bit index，避免 `[]` 进入 clock name。例如：

```text
u_harden_a_clk_o_bit0
u_harden_a_clk_o_bit1
```

第一版不允许一条 clock 命令用整 bus/range target 隐式创建多个 clock。harden SDC 应拆成 scalar/explicit bit target；01 脚本不自行展开整 bus/range target，遇到这类命令必须报 error，不得静默只取第一个 bit。

## 4. Input Clock 处理规则

harden input clock 约束需要读取，但不一定输出到 `01_soc_clocks.sdc`。

input clock 的 source 解析顺序为：

```text
1. 若 00 connection_inventory.csv 中存在当前 input canonical bit key 的 edge，使用该 edge 的 src_instance/src_port。
2. 否则使用 owner 子 xlsx 的 From Whom。
3. 若两者都无法解析为 top 或 upstream harden output，当前 input clock 不生成，并在 report 中记录。
```

因此，对于 vector clock input，`connection_inventory.csv` 是 source bit 配对的权威来源；`From Whom` 只能作为无 edge 表时的兜底。

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

- `info_all.xlsx` 中的 harden instance 是否都有对应 harden SDC。
- 子 xlsx 中的 sheet 是否能对应到 `inst_name`，包括 inst->sheet 和 sheet->inst 两个方向；大小写/首尾空格兜底匹配必须 warning。
- 若 00 `connection_inventory.csv` 存在，是否能读取其中的 bit-to-bit edge；不完整或重复 dst edge 应 warning。
- harden input clock 是否能通过 00 `connection_inventory.csv` 或 owner `From Whom` 解析来源。
- 解析后来源为 `u_xxx.port` 的上游 output clock 是否存在。
- input clock 期望 period 是否与上游 output clock period 一致。
- `create_clock` 是否填写 `-period`；缺失时 warning。
- 同名 clock 是否冲突。
- `create_generated_clock` 是否带可解析 `-source`；缺失或无法解析时为 error，并跳过该 clock。
- `create_generated_clock -source` 是否能映射到当前 harden port 或已知 SoC 对象；若 `-source [get_ports ...]` 中的 port 不在 owner sheet 的 Input/Output/Inout 中，应报 error 并跳过该 clock。
- 单条 clock 命令是否作用于多个 target port；第一版不自动拆分，多 target 应报 error 并跳过，要求 harden SDC 拆成一端口一条 clock 命令。
- clock target/source 是否符合 00 canonical bit key。整 bus/range target/source 第一版不由 01 自行展开；必须拆成 scalar/explicit bit，或由 00 edge 表给出 input source bit。否则 error。
- clock 命令是否带 `-add`；第一版不语义展开同一 target pin 多 clock/mux 场景，遇到 `-add` 必须 warning，例如 `CLOCK_ADD_OPTION_OUT_OF_SCOPE`。
- harden SDC 中是否出现内部层级对象，若出现则 warning。
- scan/mbist/test/gpio 相关 clock 是否被误放入 func-only 生成结果。
- clock name/port 中出现 scan/mbist/bist/jtag/test/gpio 等 token 时，只能产生 warning，不能自动 skip；scenario 分类和删除必须依赖显式表单/场景规则。

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
python3 "/path/to/soc_sdc_work/Soc SDC脚本/01_soc_clocks/01_extract_soc_clocks.py"
```

默认从执行目录读取：

```text
info_all.xlsx
port_*.xlsx
*.sdc
virtual_clocks.csv   # optional
00_harden_port_inventory/connection_inventory.csv   # optional
```

默认输出：

```text
common/01_soc_clocks.sdc
clock_inventory.csv
clock_check_report.txt
```

`01_soc_clocks.sdc` 的输出顺序应尽量按 clock 依赖拓扑排序：被 `-source [get_clocks ...]`、`-source [get_ports ...]` 上溯到的已 emitted clock，或 `root_source` 对应的已 emitted clock，应先于依赖它的 generated/forwarded clock 输出。无法解析的依赖保持原稳定顺序；检测到排序环时 warning 并保留剩余原顺序。

若执行目录存在 `00_harden_port_inventory/pending`，01 只按 exact canonical bit key 删除 clock port，并在 `removed_log/01_soc_clocks.removed` 记录同一个 key。对于 vector clock，不能用 `clk_o` 或 `clk_o[1:0]` 删除 `clk_o[0]` / `clk_o[1]`；必须逐 bit 删除。

如果执行目录下存在 `00_harden_port_inventory/pending`，脚本还会按 00 规则消费已由 01 覆盖的 harden clock port，并写：

```text
00_harden_port_inventory/removed_log/01_soc_clocks.removed
```

相关参数：

```bash
--connection-inventory 00_harden_port_inventory/connection_inventory.csv
--pending-root 00_harden_port_inventory
--no-update-pending
```

默认只有在 `<pending-root>/pending` 已存在时才更新 pending；若该目录不存在，01 仍按旧 flow 只生成 clock SDC/inventory/report。`--connection-inventory` 指向的文件若不存在，01 不报错，改用 owner 子 xlsx 的 `From Whom` 解析 input clock 来源。

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

### 8.4 `removed_log/01_soc_clocks.removed`

当 00 pending 机制启用时，01 可以从 pending 中删除：

- `emit_top_clock`：harden input/inout clock 已提升为 SoC top clock。
- `duplicate_top_clock`：多个 harden input 共用同一个 top clock，后续用户不重复 emit，但该 port 已由 top clock 覆盖。
- `check_only`：harden input clock 来自上游 harden output，01 已完成 upstream clock sink 检查。
- `emit_output_clock`：harden output clock / forwarded clock 已显式生成。

不删除：

- `emit_virtual_clock` / `duplicate_virtual_clock`，因为它们不是 harden port。
- `skipped` 或有 error 的 clock port。
- 非 clock data/control/reset port。

removed log 示例：

```text
u_pll output core_clk_o covered_by=01_soc_clocks reason=generated_clock clock=u_pll_core_clk_o action=emit_output_clock source=pll_top.sdc:2
u_fab0 input fab_clk_i covered_by=01_soc_clocks reason=upstream_clock_sink clock=u_fab0_fab_clk_i action=check_only from_whom=u_pll.core_clk_o source=fab.sdc:1
u_periph input ref2_i covered_by=01_soc_clocks reason=top_clock clock=top_aux_clk_pad action=emit_top_clock from_whom=top.aux_clk_pad source=periph.sdc:2
```

pending 消账必须是幂等的。若 01 试图删除的 port 已不在 pending 中，但 `00_harden_port_inventory/removed_log/*.removed` 中已有对应 `previous_removed` 记录，则不应报错；只有既不在 pending、也无 previous_removed 记录时才是流程错误。01 重写自己的 removed log 时应保留既有记录，只追加新的删除项。

## 9. 当前阶段限制

第一版仅支持 func 单一模式。

暂不处理：

- scan/mbist/gpio scenario clock。
- 同一 target pin 上多 clock/mux 的 `-add` 复杂场景；脚本只保留原命令并报告 out-of-scope warning，不做自动裁决。
- 单条 clock 命令作用于多个 target port 的批量定义；应在 harden SDC 中拆成多条单 target 命令。
- 复杂 Tcl proc 或外部 include。
- 从 harden 内部 pin 自动推断边界 clock。
- 根据名字自动猜测 clock 类型并据此删除/跳过 clock。
