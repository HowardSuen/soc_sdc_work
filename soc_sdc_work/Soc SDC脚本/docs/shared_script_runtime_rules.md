# SoC SDC Shared Script Runtime Rules

> 状态：**Target Runtime Contract（目标运行契约）**。现有 Python 尚未全部迁移；stage 完成实现和 regression 前，不得把目标能力误写成当前已支持。

本文是 00~30 的 CLI、路径、scenario、输入和销账权威规则。stage 文档与本文冲突时以本文为准。

## 1. 流程和 Scenario

完整流程：

```text
00 -> 01 -> 02 -> 03 -> 04 -> 10 -> 20 -> 30
```

每个 stage 都显式接收当前 scenario：

```text
--scenario common|func|scan|mbist|gpio_in|gpio_out
```

允许兼容 `-scenario`，但 report/SDC/workbook/inventory 中统一写 canonical scenario。

同一个 `run_root` 可以保存多个 scenario 的 middle/result。规则：

- 00 必须先为目标 scenario 初始化 manifest 和 pending。
- stage 命令行 scenario 必须与所读 manifest/pending/meta 中的 scenario 一致。
- scenario 状态存入独立子目录，禁止跨 scenario 读取 pending 或 removed log。
- 初始化一个 scenario 不得删除或覆盖其它 scenario 的状态。
- common 产物可以复用，但 scenario effective view 必须重新装配和检查。

## 2. 00 是集成信息机器真源

只有 00 直接解析 SoC 集成表单：

```text
inputs/info_all.xlsx
inputs/port_*.xlsx
inputs/ports_*.xlsx
```

00 必须生成：

```text
00_middle/connection_inventory.csv
00_middle/scenario/<scenario>/harden_sdc_manifest.csv
00_middle/scenario/<scenario>/pending/<inst>.ports
00_middle/scenario/<scenario>/removed_log/00_disposition.removed
00_result/reports/inventory_report_<scenario>.txt
```

`connection_inventory.csv` 是 01/04/10/20/30 的 required direct-edge machine input。它必须完成：

```text
canonical scalar/bit port expansion
direct bit-level edge expansion
stable connection_id
src/dst endpoint key
direction/range validation
scenario_scope
pad/clock/feedthrough/constant/NC classification hints
source workbook/sheet/row traceability
```

每行只能表示一条 `source bit -> destination bit` direct edge。fanout 每个 sink 独立成行。下游不得重新展开 bus/range、重算 `connection_id`，也不得在缺少 exact edge 时回退 whole-bus 或按名称猜测。

`scenario_scope` 为 `common`、单个具体 scenario 或稳定排序的 scenario list。下游统一选择：

```text
effective edges = scenario_scope 包含 common 或当前 scenario 的行
```

## 3. Target 与 Legacy 布局

target `--run-root` 模式固定使用 `*_middle` / `*_result` 路径。

legacy cwd 模式允许使用：

```text
00_harden_port_inventory/connection_inventory.csv
00_harden_port_inventory/harden_sdc_manifest.csv
00_harden_port_inventory/pending/
00_harden_port_inventory/removed_log/
```

legacy cwd 一次只承载一个 scenario。target 与 legacy 不得在同一次 flow 中交叉读取或同时修改两套 pending。stage 文档中的 legacy 路径只能放在明确标记的兼容章节，不能作为 target 默认值。

## 4. Harden SDC Manifest 和 Partial Availability

00 为当前 scenario 生成：

```text
00_middle/scenario/<scenario>/harden_sdc_manifest.csv
```

最少字段：

```text
scenario
inst_name
module_name
sdc_path
availability_status
note
```

`availability_status`：

```text
available
missing
not_required
```

规则：

- 每个当前 scenario required harden 恰好一行。
- `available` 路径必须唯一、存在且可读。
- `missing` 表示尚未交付，不表示无 clock、无 timing 或无 exception。
- `not_required` 必须有明确依据。
- 01/04/10/20/30 通过 manifest 读取 available harden SDC。
- 默认 partial mode 继续处理 available harden；missing 相关 evidence 标记 incomplete。
- missing 相关 port 默认保留 pending；只有 stage 规则允许且具有 approved SDC-independent terminal basis 时才可例外销账。
- strict/signoff 模式使用 `--require-complete-harden-sdc`，required missing 时阻断。

## 5. Port Accounting 默认开启

00 默认生成当前 scenario pending。01/04/10/20/30 默认更新 pending 并写 removed log；02/03 永不销账。

诊断运行可显式关闭：

```text
00: --no-port-accounting
01/04/10/20/30: --no-update-pending
```

显式关闭时必须在 report/SDC header 记录 `Port accounting: disabled by explicit option`，且不得宣称 port closure 完成。

target pending：

```text
00_middle/scenario/<scenario>/pending/<inst>.ports
```

target removed log：

```text
00_middle/scenario/<scenario>/removed_log/00_disposition.removed
01_middle/scenario/<scenario>/removed_log/01_soc_clocks.removed
04_middle/scenario/<scenario>/removed_log/04_soc_io_pads.removed
10_middle/scenario/<scenario>/removed_log/10_feedthrough.removed
20_middle/scenario/<scenario>/removed_log/20_harden_x_if.removed
30_middle/scenario/<scenario>/removed_log/30_harden_to_harden_exception.removed
```

规则：

- pending 和 removed log 使用 exact canonical scalar/bit key。
- 不得使用 bus range、wildcard 或 pattern 删除。
- target accounting 开启时，pending 缺失或损坏必须阻断。
- previous-owner 检查只读取当前 scenario 的固定早期 removed log。
- 一个 canonical port 只能有一个 port-level removal owner。
- 30 可以在已有早期 port owner 后生成更窄 path exception，但不能重复删除 port。
- accounting 状态不得反向改变 constraint classification 或 SDC 生成语义。

## 6. Common/Scenario 装配模型

review workbook 可以包含 `scenario=common` 和具体 scenario 行。当前 scenario view 使用：

```text
active rows = common rows + current scenario rows
```

不同 stage 的输出模型：

- 01：生成 common clock SDC、scenario clock overlay，并生成 `assembled/<scenario>` clock inventory/meta。
- 02：生成 resolved effective 单文件；具体 scenario 行优先于 common fallback，装配时只 source 当前 resolved 02 文件。
- 03/04/10/20/30：保留 common + scenario overlay 文件；脚本必须检查 assembled view 冲突，不能依靠 source priority 静默覆盖。

`scenario=common` 时只生成/使用 common view。其它 scenario 行不参与当前运行。

项目维护的 scenario pre-setup，例如 `scenarios/<scenario>_pre.sdc`，负责 `set_case_analysis` 等 mode 设置，不由 00~30 自动生成。03/04/30 若依赖 case 条件，必须在规则/basis 中记录。

## 7. Stage Artifact Contract

### 7.1 01

```text
01_result/common/01_soc_clocks.sdc
01_result/scenarios/<scenario>_clocks.sdc
01_middle/common/clock_inventory.csv
01_middle/scenario/<scenario>/clock_inventory.csv
01_middle/assembled/<scenario>/clock_inventory.csv
01_middle/assembled/<scenario>/clock_inventory.meta
01_middle/scenario/<scenario>/removed_log/01_soc_clocks.removed
01_result/reports/clock_check_report_<scenario>.txt
```

### 7.2 02

```text
02_middle/02_soc_clock_timing_budget_<stage>.xlsx
02_middle/resolved/<scenario>_<stage>_<corner>.manifest
02_result/common/02_soc_clock_timing_<stage>_<corner>.sdc
02_result/scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc
02_result/reports/
```

### 7.3 03

```text
03_middle/03_soc_clock_groups.xlsx
03_middle/relation_map/<scenario>.csv
03_middle/relation_map/<scenario>.meta
03_result/common/03_soc_clock_groups.sdc
03_result/scenarios/<scenario>_clock_groups.sdc
03_result/reports/
```

### 7.4 04

```text
04_middle/04_soc_io_pads.xlsx
04_middle/scenario/<scenario>/removed_log/04_soc_io_pads.removed
04_result/common/04_soc_io_pads.sdc
04_result/common/04_soc_io_pads_<stage>_<corner>.sdc
04_result/scenarios/<scenario>_io_pads.sdc
04_result/scenarios/<scenario>_io_pads_<stage>_<corner>.sdc
04_result/reports/
```

### 7.5 10

```text
10_middle/10_feedthrough.xlsx
10_middle/scenario/<scenario>/feedthrough_edge_inventory.csv
10_middle/scenario/<scenario>/removed_log/10_feedthrough.removed
10_result/common/10_feedthrough.sdc
10_result/common/10_feedthrough_<stage>_<corner>.sdc
10_result/scenarios/<scenario>_feedthrough.sdc
10_result/scenarios/<scenario>_feedthrough_<stage>_<corner>.sdc
10_result/reports/
```

### 7.6 20

```text
20_middle/20_harden_x_if.xlsx
20_middle/scenario/<scenario>/channel_inventory.csv
20_middle/scenario/<scenario>/channel_inventory.meta
20_middle/scenario/<scenario>/removed_log/20_harden_x_if.removed
20_result/common/20_harden_x_if.sdc
20_result/common/20_harden_x_if_<stage>_<corner>.sdc
20_result/scenarios/<scenario>_harden_x_if.sdc                    # budget_output only
20_result/scenarios/<scenario>_harden_x_if_<stage>_<corner>.sdc   # budget_output only
20_result/reports/
```

### 7.7 30

```text
30_middle/30_harden_to_harden_exception.xlsx
30_middle/scenario/<scenario>/exception_candidates.csv
30_middle/scenario/<scenario>/removed_log/30_harden_to_harden_exception.removed
30_result/common/30_harden_to_harden_exception.sdc
30_result/common/30_harden_to_harden_exception_<stage>_<corner>.sdc
30_result/scenarios/<scenario>_exceptions.sdc
30_result/scenarios/<scenario>_exceptions_<stage>_<corner>.sdc
30_result/reports/
```

## 8. Fixed Downstream Reads

```text
01 <- 00 connection inventory
01 <- current-scenario harden SDC manifest

02 <- 01 assembled current-scenario clock inventory + meta

03 <- 01 assembled current-scenario clock inventory + meta

04 <- 00 connection inventory
04 <- current-scenario harden SDC manifest
04 <- 01 assembled clock inventory + meta

10 <- 00 connection inventory
10 <- current-scenario harden SDC manifest
10 <- 01 assembled clock inventory + meta              [optional diagnostic]
10 <- 03 current-scenario relation map + meta           [optional diagnostic]

20 <- 00 connection inventory
20 <- current-scenario harden SDC manifest
20 <- 01 assembled clock inventory + meta
20 <- 10 current-scenario feedthrough edge inventory
20 <- 03 current-scenario relation map + meta           [required only for budget_output/clock-derived basis]

30 <- 00 connection inventory
30 <- current-scenario harden SDC manifest
30 <- 01 assembled clock inventory + meta
30 <- 03 current-scenario relation map + meta
30 <- 10 current-scenario feedthrough edge inventory
30 <- 20 current-scenario channel inventory
```

30 在缺少 20 inventory 时可以生成 candidate-only report/workbook，但不得生成正式 30 SDC。feedthrough-related candidate 在缺少 10 `route_to_30` 结果时同样不得生成。

## 9. Report Metadata

每个 stage stdout、SDC、inventory/workbook 和 report 至少记录：

```text
Author: Howard
Scenario: <command-line scenario>
Run completeness: complete|partial
Port accounting: enabled|disabled by explicit option
Connection inventory: <resolved path>
Harden SDC manifest: <resolved path, when used>
```

## 10. Packaging 和 Migration

脚本/共享 parser 必须离线、确定性、兼容 Python 3.6.8。

内网包只包含 flat Python scripts/shared parser 和必要输入/表单模板；不包含 rules、tests、examples、result、cache 或 macOS metadata。

迁移完成条件：

1. 00 正式生成 bit-level connection inventory、scenario manifest 和默认 pending。
2. 01/04/10/20/30 只用 00 machine artifact 获取 port/connection 信息。
3. 00~30 均接收并校验 scenario CLI。
4. 所有 target path 使用本文固定路径，不混用 legacy cwd。
5. accounting enabled/disabled、partial SDC 和至少两个 scenario 完成 regression。
6. 03/10/20/30 machine interface digest/scenario 检查通过。
7. 全部完成后重新生成内网包；旧包作废。
