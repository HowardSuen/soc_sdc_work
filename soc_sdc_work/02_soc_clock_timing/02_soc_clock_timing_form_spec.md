# 02 Clock Timing SDC Form Specification

本文档记录 02 clock timing budget 的输入表单格式和脚本生成机制。

## 1. 目标

02 clock timing SDC 只对 `01_soc_clocks.sdc` 中已经创建好的 clock object 施加 timing budget。

输出文件按 scenario / stage / corner 拆分：

```text
scenario = common:
  common/02_soc_clock_timing_<stage>_<corner>.sdc

scenario != common:
  scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc
```

放在 02 的约束包括：

- `set_clock_uncertainty`
- `set_clock_latency`
- `set_clock_transition`
- `set_propagated_clock`
- `set_timing_derate` 或 OCV/AOCV/POCV 的 flow hook 说明

不放在 02 的约束包括：

- `create_clock` / `create_generated_clock`
- `set_clock_groups`
- IO delay / pad driving / load
- false path / multicycle / max delay
- harden interface delay

## 2. 表单文件

建议按 stage 独立维护表单，字段结构保持统一。scenario 和 corner 不单独拆表，而是在同一 stage 表单中用 `scenario` / `corner` 列区分；生成 SDC 时必须通过 `-scenario` / `-corner` 选择单一输出目标。第一版先关注 pre-CTS / post-CTS：

```text
02_soc_clock_timing_budget_prects.xlsx
02_soc_clock_timing_budget_postcts.xlsx
```

后续需要时可增加：

```text
02_soc_clock_timing_budget_synth.xlsx
02_soc_clock_timing_budget_postroute.xlsx
```

建议包含 3 个 sheet：

```text
clock_budget
clock_pair_uncertainty
derate_ocv
```

第一版脚本强制支持 `clock_budget`。`clock_pair_uncertainty` 和 `derate_ocv` 先作为预留格式。

## 3. 通用约定

- `clock_name` / `from_clock` / `to_clock` 必须引用 `01_soc_clocks.sdc` 已创建的 clock name。
- 脚本读取 `01_soc_clocks` 生成的 `clock_inventory.csv` 做 clock name 合法性检查。02 只依赖 01 CSV 中真实输出的字段，例如 `clock_name`、`clock_kind`、`direction`、`direct_source`、`final_action`；不应假设存在 01 内部 dataclass 才有的临时字段。
- 02 不直接读取或删除 `00_harden_port_inventory/pending/*.ports`。若某个 vector harden port 的不同 bit 被 01 创建成多个 clock object，02 只看到这些 bit 对应的独立 `clock_name`，例如 `u_x_clk_o_bit0`、`u_x_clk_o_bit1`；不能再用 bus/range 语义推导 budget。
- `scenario` 建议使用 `common`、`func`、`scan`、`mbist`、`gpio_in`、`gpio_out`。
- `scenario = common` 表示所有 mode 都成立的 clock timing budget，只能输出到 `common/`。
- `scenario != common` 表示 scenario 专属 clock timing budget，必须输出到 `scenarios/`。
- `stage` 建议使用 `synth`、`prects`、`postcts`、`postroute`；表单按 stage 独立后，同一份表单内的 `stage` 应保持一致。
- `corner` 使用项目 flow 中的 corner / analysis view 名称，例如 `ss_125`、`ff_m40` 或 `SS_125`。脚本保留用户输入的大小写并用于表单匹配和输出文件名；若项目 MMMC view 名大小写敏感，表单与 assembly 必须使用同一写法。
- SDC 本身没有 corner 条件化能力；同一个输出 SDC 中不能同时平铺多个 corner 的 `set_clock_uncertainty`、`set_clock_latency`、`set_clock_transition`、`set_timing_derate`。
- SDC 也没有 scenario 条件化能力；同一个 common 输出 SDC 中不能混入 `func` / `scan` / `mbist` 等 scenario 专属 timing。
- 02 脚本必须按 `scenario + stage + corner` 生成一个 resolved effective SDC，由 scenario assembly 和 MMMC analysis view 选择性 source。
- 对于 `scenario != common`，生成时按优先级选择胜出行：当前具体 scenario 行优先于 `common` 行；同一 clock/stage/corner 最终只 emit 一个胜出行。
- 如果具体 scenario 行 `apply = no`，它仍然是胜出行，可用于显式压掉较低优先级的 common 默认约束。
- 所有数值使用当前 STA/综合 flow 的 SDC 时间单位；建议项目统一在 flow 文档中声明，例如 ns。脚本生成 SDC 时会把可解析数值规范化为稳定的十进制表示，避免 xlsx 单元格是文本还是数字导致输出精度风格漂移。
- 空白数值表示不生成对应命令。
- `apply = yes` 才生成约束；`apply = no` 表示保留记录但不生成。
- `note` 只用于人工审查，不参与生成。
- `clock_budget` 建议按 `clock_name -> corner -> scenario` 排序，让同一个 clock 在当前 stage 下的不同 scenario/corner 约束相邻，便于人工比较。
- 当前阶段不规定不同 `stage` 下哪些数值列必填、哪些必须留空；这些规则后续随具体项目的 STA methodology、CTS 策略和 MMMC flow 再收敛。

如果同时存在 `scenario = common` 和具体 scenario 的同一 clock/stage/corner 记录，脚本必须在生成阶段 resolve 出唯一胜出行。不能同时 emit common 行和具体 scenario 行，再依赖 source 顺序覆盖。

## 4. Sheet: `clock_budget`

一行描述一个 clock 在某个 scenario/stage/corner 下的基础 timing budget。

字段：

```text
scenario
stage
corner
clock_name
setup_uncertainty
hold_uncertainty
source_latency_early
source_latency_late
network_latency_early
network_latency_late
transition_min
transition_max
propagated
apply
sync_status
note
```

字段含义：

```text
scenario                 适用场景，common 表示所有 scenario 共用；func/scan 等表示专属 scenario
stage                    适用阶段，例如 prects / postcts
corner                   适用 corner / analysis view
clock_name               01 中定义的 clock name
setup_uncertainty        生成 set_clock_uncertainty -setup
hold_uncertainty         生成 set_clock_uncertainty -hold
source_latency_early     生成 set_clock_latency -source -early
source_latency_late      生成 set_clock_latency -source -late
network_latency_early    生成 set_clock_latency -early
network_latency_late     生成 set_clock_latency -late
transition_min           生成 set_clock_transition -min
transition_max           生成 set_clock_transition -max
propagated               yes/no；yes 时生成 set_propagated_clock
apply                    yes/no
sync_status              脚本同步状态，人工不建议手填；OK / NEW_FROM_01 / STALE_NOT_IN_01
note                     人工说明
```

`sync_status` 由脚本维护，不应作为人工 review 状态使用：

- `NEW_FROM_01`：脚本发现 01 中新增 clock 后自动追加的行。用户补齐该行 budget 后，脚本在下一轮 sync 自动复位为 `OK`。
- `STALE_NOT_IN_01`：脚本发现该 clock 已不在 01 inventory 中。若后续 clock 又回到 01 inventory，且该行仍有明确约束意图，脚本自动复位为 `OK`。
- `OK` / 空白：可参与生成。

自动复位到 `OK` 的条件：

- `apply = yes` 且至少会生成一条 timing/propagated 命令。
- 或 `apply = no` 且 `note` 非空，用于显式说明该 clock 在当前 scenario/corner 不生成 02 约束。

因此用户通常只需要填写 `apply`、数值字段和 `note`，不需要手动改 `sync_status`。

示例：

```text
scenario | stage   | corner | clock_name     | setup_uncertainty | hold_uncertainty | source_latency_early | source_latency_late | network_latency_early | network_latency_late | transition_min | transition_max | propagated | apply | sync_status | note
common   | prects  | ss_125 | u_pll_core_clk | 0.110             | 0.035            | 0.100                | 0.240               | 0.280                 | 0.650                | 0.030          | 0.110          | no         | yes   | OK          | common default
func     | prects  | ss_125 | u_pll_core_clk | 0.120             | 0.040            | 0.100                | 0.250               | 0.300                 | 0.700                | 0.030          | 0.120          | no         | yes   | OK          | func override
func     | postcts | ss_125 | u_pll_core_clk | 0.070             | 0.025            |                      |                     |                       |                      |                |                | yes        | yes   | OK          | CTS propagated
```

对应生成示例：

```tcl
set_clock_uncertainty -setup 0.120 [get_clocks {u_pll_core_clk}]
set_clock_uncertainty -hold 0.040 [get_clocks {u_pll_core_clk}]

set_clock_latency -source -early 0.100 [get_clocks {u_pll_core_clk}]
set_clock_latency -source -late 0.250 [get_clocks {u_pll_core_clk}]
set_clock_latency -early 0.300 [get_clocks {u_pll_core_clk}]
set_clock_latency -late 0.700 [get_clocks {u_pll_core_clk}]

set_clock_transition -min 0.030 [get_clocks {u_pll_core_clk}]
set_clock_transition -max 0.120 [get_clocks {u_pll_core_clk}]
```

若 `propagated = yes`：

```tcl
set_propagated_clock [get_clocks {u_pll_core_clk}]
```

## 5. Sheet: `clock_pair_uncertainty`

用于少数 from/to clock pair 的特殊 uncertainty。第一版不建议大量使用该 sheet，优先使用 `clock_budget` 中的 per-clock uncertainty。

字段：

```text
scenario
stage
corner
from_clock
to_clock
setup_uncertainty
hold_uncertainty
apply
note
```

示例：

```text
scenario | stage  | corner | from_clock     | to_clock      | setup_uncertainty | hold_uncertainty | apply | note
func     | prects | ss_125 | u_pll_core_clk | u_pll_bus_clk | 0.150             | 0.050            | yes   | related PLL outputs
```

对应生成示例：

```tcl
set_clock_uncertainty -setup 0.150 \
  -from [get_clocks {u_pll_core_clk}] \
  -to [get_clocks {u_pll_bus_clk}]

set_clock_uncertainty -hold 0.050 \
  -from [get_clocks {u_pll_core_clk}] \
  -to [get_clocks {u_pll_bus_clk}]
```

## 6. Sheet: `derate_ocv`

用于记录简单 OCV derate 或 AOCV/POCV 的 flow 管理入口。

字段：

```text
scenario
stage
corner
derate_scope
object_type
early
late
apply
managed_by_flow
note
```

字段含义：

```text
derate_scope      clock / data / aocv / pocv
object_type       delay / cell_delay / net_delay；具体取值可按项目 STA tool 规范收敛
early             early derate value
late              late derate value
apply             yes/no
managed_by_flow   yes/no；yes 表示由 MMMC/corner flow 管理，02 只保留记录或 hook
note              人工说明
```

示例：

```text
scenario | stage   | corner | derate_scope | object_type | early | late | apply | managed_by_flow | note
func     | prects  | ss_125 | clock        | delay       | 0.95  | 1.05 | yes   | no              | simple OCV
func     | prects  | ss_125 | data         | delay       | 0.93  | 1.07 | yes   | no              | simple OCV
func     | postcts | ss_125 | aocv         |             |       |      | no    | yes             | handled by MMMC corner setup
```

简单 OCV 可生成类似命令，具体 option 需按项目 STA tool 校准：

```tcl
set_timing_derate -clock -early 0.95
set_timing_derate -clock -late 1.05
set_timing_derate -data -early 0.93
set_timing_derate -data -late 1.07
```

如果 `managed_by_flow = yes`，未来脚本不应重复生成 derate 命令，只应在 report 中记录该 corner/stage 的 OCV 由 flow 管理。

## 7. 02 脚本机制

02 脚本采用 **先同步检查，后生成 SDC** 的机制。只要当前 `-scenario/-corner` 的 clock 列表和 01 clock inventory 不一致，或表单中存在 stale clock，脚本应更新表单并中断，不生成 SDC。

### 7.1 命令行入口

脚本必须支持 `-scenario`、`-stage` 和 `-corner`，用于确认当前执行环境要处理的 scenario、timing stage 和 corner / analysis view：

```bash
python3 02_extract_soc_clock_timing.py -scenario common -stage prects -corner ss_125
python3 02_extract_soc_clock_timing.py -scenario func   -stage prects -corner ss_125
python3 02_extract_soc_clock_timing.py -scenario scan   -stage postcts -corner ff_m40
```

`-scenario` 合法值建议为：

```text
common
func
scan
mbist
gpio_in
gpio_out
```

`-stage` 合法值建议为：

```text
synth
prects
postcts
postroute
```

脚本根据 `-stage` 寻找当前目录下匹配的表单：

```text
02_soc_clock_timing_budget_<stage>.xlsx
```

例如：

```text
02_soc_clock_timing_budget_prects.xlsx
02_soc_clock_timing_budget_postcts.xlsx
```

### 7.2 读取 01 clock 信息

脚本默认从上层 `01_soc_clocks` 工作目录读取 01 生成的中间文件：

```text
../01_soc_clocks/clock_inventory.csv
```

该文件用于获得 SoC 当前有效 clock 列表。脚本保留 `-input` 参数覆盖路径：

```bash
-input /path/to/clock_inventory.csv
```

stage 表单和输出 SDC 路径不单独提供命令行选项，统一由 `-scenario` / `-stage` / `-corner` 推导：

```text
02_soc_clock_timing_budget_<stage>.xlsx

scenario = common:
  common/02_soc_clock_timing_<stage>_<corner>.sdc

scenario != common:
  scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc
  # resolved effective file: selected scenario wins, common is fallback

clock_timing_check_report_<scenario>_<stage>_<corner>.txt
```

第一版建议只使用 `clock_inventory.csv` 中最终有效的 clock record，例如：

```text
emit_top_clock
emit_output_clock
emit_virtual_clock
```

### 7.3 本地无 stage 表单

若当前目录下不存在 `02_soc_clock_timing_budget_<stage>.xlsx`：

1. 脚本根据 01 clock inventory 自动生成新表单。
2. 在 `clock_budget` 中为当前 `-scenario/-corner` 缺少有效胜出行的 clock 加一行。
3. `scenario` 填当前 `-scenario`。
4. `stage` 填当前 `-stage`。
5. `corner` 填当前 `-corner`。
6. `clock_name` 来自 01 clock inventory。
7. `apply` 默认填 `no`。
8. `sync_status` 填 `NEW_FROM_01`。
9. 新增行用黄色背景标记。
10. 脚本打印提醒并中断，不生成 SDC。

这样做是为了让用户先补齐 timing budget，再显式 review。

### 7.4 本地已有 stage 表单

若当前目录下已存在 `02_soc_clock_timing_budget_<stage>.xlsx`，脚本先比较：

```text
01 clock_inventory.csv 中的 clock_name
vs
stage 表单 clock_budget 中当前 -scenario/-corner 的有效胜出 clock_name
```

若 01 中有、当前 scenario/corner 没有有效胜出行：

1. 脚本自动追加该 clock。
2. `scenario` 填当前 `-scenario`。
3. `stage` 填当前 `-stage`。
4. `corner` 填当前 `-corner`。
5. `apply` 默认填 `no`。
6. `sync_status` 填 `NEW_FROM_01`。
7. 新增行用黄色背景标记。
8. 脚本打印提醒并中断，不生成 SDC。

若表单任意 scenario/corner 中有、01 中没有：

1. 脚本保留该行。
2. `sync_status` 填 `STALE_NOT_IN_01`。
3. 该行用红色背景标记。
4. 脚本打印提醒并中断，不生成 SDC。

若当前 scenario/corner 的有效胜出 clock 与 01 完全一致，且不存在 stale clock：

1. 脚本应将已具备明确约束意图的 `NEW_FROM_01` / 已恢复的 `STALE_NOT_IN_01` 行自动复位为 `OK`，并清除旧的黄色/红色标记。
2. `sync_status = OK` 或空白在生成时视为可用。
3. 进入字段合法性检查。

### 7.5 中断条件

以下情况必须中断，不生成 SDC：

- 新生成了 stage 表单，用户尚未填写 budget。
- 当前 `-scenario/-corner` 有尚未补齐约束意图、无法自动复位为 `OK` 的 `NEW_FROM_01` 行。
- 任意 scenario/corner 有仍不在 01 inventory 中的 `STALE_NOT_IN_01` 行。
- 当前 `-scenario/-corner` 的有效胜出 clock 与 01 clock inventory 不一致。
- 当前 `-scenario/-corner` 的 `apply`、`propagated` 等枚举字段非法。
- 当前 `-scenario/-corner` 的数值字段填写了非数字内容。
- 当前 `-scenario/-corner` 中 `apply = yes` 的行缺少生成该命令所需的关键信息。
- 全表任意 `apply = yes` 行若缺少 `scenario` 或 `corner`，视为结构完整性错误并中断；这类行无法安全参与 scenario/corner resolve，不按当前目标过滤。

当前阶段暂不强制区分不同 stage 哪些数值列必填或必须留空；只检查“用户填了的值是否合法”以及“要生成某条具体 SDC 命令时，所需字段是否存在”。除 `apply = yes` 的结构完整性检查外，命令生成相关检查只阻塞当前 `-scenario/-stage/-corner`；其它 scenario/corner 中尚未填写的数值不阻塞当前输出。

### 7.6 SDC 生成

只有当当前 `-scenario/-corner` 的有效胜出 clock 与 01 clock inventory 完全一致、不存在 stale clock，且胜出行字段合法时，脚本才生成 02 SDC。

第一版只处理 `clock_budget` sheet 中：

```text
scenario = 当前 -scenario
stage = 当前 -stage
corner = 当前 -corner
apply = yes
sync_status = OK 或空白
```

生成前先按以下优先级 resolve：

```text
scenario = common:
  只看 common 行

scenario != common:
  1. 当前具体 scenario 行
  2. common 行 fallback
```

同一 clock/stage/corner 只 emit 一个胜出行。

生成文件建议为：

```text
scenario = common:
  common/02_soc_clock_timing_<stage>_<corner>.sdc

scenario != common:
  scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc
  # 不再同时 source common/02_soc_clock_timing_<stage>_<corner>.sdc
```

例如：

```text
common/02_soc_clock_timing_prects_ss_125.sdc
scenarios/func_clock_timing_prects_ss_125.sdc
scenarios/scan_clock_timing_postcts_ff_m40.sdc
```

生成命令包括：

```text
set_clock_uncertainty
set_clock_latency
set_clock_transition
set_propagated_clock
```

`clock_pair_uncertainty`、`derate_ocv` 第一版只做格式预留，后续再实现生成。后续实现时也必须遵守同样的 `scenario + stage + corner` resolve 规则。

## 8. 脚本检查项

02 生成脚本至少检查：

- 当前 `-scenario/-stage/-corner` resolve 后的有效胜出 clock 是否覆盖 01 的 `clock_inventory.csv`。
- 表单任意 scenario/corner 中是否存在 01 已不存在的 stale clock。
- 同一 `scenario/stage/corner/clock_name` 是否重复定义。
- `apply`、`propagated` 是否为合法 yes/no（`clock_budget` sheet）。
- `sync_status` 是否为合法状态：空白、`OK`、`NEW_FROM_01`、`STALE_NOT_IN_01`。
- 是否存在会阻止生成的同步状态：当前 `-scenario/-corner` 的 `NEW_FROM_01`，或任意 scenario/corner 的 `STALE_NOT_IN_01`。
- 基于 01 `clock_inventory.csv` 中的 `clock_kind` 做 warning 级检查：
- `clock_kind = virtual_clock` 的胜出行若填写 `network_latency_*` 或 `transition_*`，脚本应 warning，因为 virtual clock 没有物理 clock network。
- `clock_kind` 为 generated 类 clock 的胜出行若填写 `source_latency_*`，脚本应 warning，因为 generated clock 通常继承 master/source clock 的 source latency，重复设置容易双重计算。
- `propagated = yes` 的胜出行若同时填写 `network_latency_*` 或 `transition_*`，脚本应 warning，因为 propagated clock 的实际网络由工具传播/提取，这些估算值通常不会生效。

第一版脚本只处理 `clock_budget` sheet，不读取 `clock_pair_uncertainty` / `derate_ocv`。以下检查与这两个 sheet 的生成能力一起延后实现：

- `clock_pair_uncertainty` 中 from/to clock 是否都存在。
- `derate_ocv` 中 `managed_by_flow` 是否为合法 yes/no，以及 `managed_by_flow = yes` 时是否误填 `apply = yes` 并生成重复 derate。

暂不在第一版检查中强制区分 pre-CTS / post-CTS 哪些列必填或必须留空。后续项目规则明确后，可以增加 stage-specific 检查，例如：

- pre-CTS 是否缺少项目要求的 latency/transition/uncertainty。
- post-CTS 若 `propagated = yes`，是否仍残留项目 flow 不允许的 estimated network latency。

## 9. 当前约定

当前先按 stage 独立表单讨论和落地：

```text
02_soc_clock_timing_budget_prects.xlsx
02_soc_clock_timing_budget_postcts.xlsx
```

第一版 02 脚本先只支持：

```text
clock_budget
```

并只生成：

```text
set_clock_uncertainty
set_clock_latency
set_clock_transition
set_propagated_clock
```

输出 SDC 按 `scenario + stage + corner` 拆分，例如：

```text
common/02_soc_clock_timing_prects_ss_125.sdc
scenarios/func_clock_timing_prects_ss_125.sdc
```

`clock_pair_uncertainty`、`derate_ocv` 等 02 扩展能力后续再实现。
