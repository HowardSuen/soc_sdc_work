# SoC SDC Shared Script Runtime Rules

> 状态：**Target Runtime Contract（目标运行契约）**。当前各 stage Python 脚本仍以 legacy cwd/相对路径模式为主；本文中的 `--run-root`、flat script layout、`<stage>_middle` / `<stage>_result` 和固定 downstream path 在对应 stage 完成迁移并通过 regression 前，不得当作已实现功能对外使用。

本文定义 00~30 所有 SoC SDC 脚本共同遵守的运行、作者标记和目录契约。各 stage 规则只定义业务语义；若 stage 文档中的旧路径示例与本文冲突，以本文的 target layout 为准。

## 1. 适用范围

适用于：

```text
00_harden_port_inventory
01_soc_clocks
02_soc_clock_timing
03_soc_clock_groups
04_soc_io_pads
10_feedthrough
20_harden_x_if
30_harden_to_harden_exception
```

当前脚本尚未全部迁移到该目录结构；本文定义后续统一迁移的目标契约。迁移完成前，legacy regression 可以继续使用各 stage 原目录，但不得再新增另一套路径约定。

## 1.1 Harden SDC 渐进交付模型

SoC 集成互联表单通常早于全部 harden DC output SDC 交付完成。因此所有需要读取 harden SDC 的 stage 默认支持 **partial-availability mode**：

- SoC 集成表单中的 harden instance、port、scenario mapping 和 connection 仍必须完整。
- 某些 harden SDC 尚未交付或映射路径尚不存在时，脚本必须记录为 `missing`，但继续处理其它 `available` harden。
- 缺失是显式状态，不允许通过 glob、近似文件名或回退到其它 scenario SDC 静默补齐。
- 多个候选、同一 `(inst_name, scenario)` 有冲突映射、或一份已读取 SDC 解析失败，仍是 error；只有“文件尚未到位”可以按 partial 处理。
- 受 missing SDC 影响的候选、clock、channel 或 exception evidence 必须显式标记 `missing_sdc` / `incomplete_evidence`，不能因缺少证据而被推断为“无 clock”、“无 exception”或“无需约束”。
- 缺失 SDC 对应的 pending canonical port 默认保留；只有不依赖该 SDC 的独立证据/人工 approved rule 满足对应 stage 生成门槛时，才能生成或消账。
- 所有 SDC/report/inventory header 必须记录 `Run completeness: complete|partial`、available/missing harden 数量和 missing instance 列表。

统一可选 strict 开关为：

```text
--require-complete-harden-sdc
```

默认不开启，用于项目进行中的渐进解析。在 SoC SDC 正式交付、signoff 冻结或 CI completeness gate 中开启；任一 required harden SDC 为 `missing` 时整体阻断。

每个需读取 harden SDC 的 stage regression 至少覆盖：

- 全部 SDC available：`Run completeness: complete`。
- 部分 SDC missing：available harden 仍产出正确结果，missing 对象标记 incomplete 并保留 pending。
- 部分 SDC missing + `--require-complete-harden-sdc`：阻断。
- missing SDC 不会被误判为“无 clock”、“无 exception”、`no_soc_budget_required` 或 `not_applicable`。
- missing SDC 后续到位时，更新 manifest 状态并从干净 pending 重新运行受影响 stage，使 blocked/pending 记录恢复正常 review 流程；前后产物通过独立 run root 做 diff。

## 2. 作者标记

### 2.1 运行时输出

每个 stage 脚本启动后必须在 stdout 打印一次：

```text
Author: Howard
```

生成的 SDC header、check report header 和 coverage/report metadata 也应记录：

```text
Author: Howard
Stage: <stage_id>
Script: <script_name>
```

### 2.2 源码拼装

源码中不直接保存一个连续、单点定义的 `Howard` literal。统一 author helper 应满足：

- 从多个分散、非连续的 getter/字符片段中取得字符。
- 可以使用脚本私有的随机选择，从多个等价片段来源中选择后拼装。
- 无论随机分支如何选择，最终结果必须恒定为 `Howard`；作者打印不能随运行变化。
- 不能调用网络、环境变量或外部文件获取作者名，避免离线内网运行失败。
- 不能修改 Python 全局 random seed 或影响业务逻辑、输出排序和 regression 可重复性；若使用随机选择，应使用 helper 私有 RNG。
- 必须兼容内网 Python 3.6.8。

该机制只是轻量 provenance/提高简单搜索替换的成本，不是加密签名或不可篡改保证。需要追溯时，report 可额外记录脚本文件 SHA-256；作者打印本身不能替代版本管理和代码 review。

### 2.3 回归要求

每个 stage regression 至少检查：

- stdout 中恰好出现可识别的 `Author: Howard`。
- 生成 SDC/report header 中作者值正确。
- 多次运行或不同随机分支下作者值恒定。
- author helper 不改变业务输出和排序。

## 3. Flat Script Layout

未来所有 stage Python 脚本统一放在同一个工具目录，不再依赖脚本所在 stage 子目录推导输入输出：

```text
<tool_root>/
  00_harden_port_inventory.py
  01_extract_soc_clocks.py
  02_extract_soc_clock_timing.py
  03_extract_soc_clock_groups.py
  04_extract_soc_io_pads.py
  10_extract_feedthrough.py
  20_extract_harden_x_if.py
  30_extract_harden_to_harden_exception.py
```

所有脚本必须接受统一 `--run-root <path>`。未指定时默认使用当前工作目录；不得使用脚本文件所在目录作为隐式 run root。

## 4. Run Root Layout

统一运行目录：

```text
<run_root>/
  inputs/
  00_middle/
  00_result/
  01_middle/
  01_result/
  02_middle/
  02_result/
  03_middle/
  03_result/
  04_middle/
  04_result/
  10_middle/
  10_result/
  20_middle/
  20_result/
  30_middle/
  30_result/
```

语义：

- `<stage>_middle/`：机器可读 inventory、candidate/form、manifest、sync state、pending/removed-log 等 downstream 或重跑会读取的中间产物。
- `<stage>_result/`：该 stage 对用户/flow 交付的 SDC、check report、coverage report 和摘要。
- `inputs/`：SoC 集成表单、port 表单、按 scenario 选择的 harden DC output SDC、manual overlay 等外部输入。
- regression 临时文件不得写进 result；统一放在 regression 自己的 work root。

每个 stage 必须自行创建所需目录。写文件时先写临时文件再原子替换，避免下游读到半成品。

## 5. Stage Artifact Contract

### 5.1 00

```text
00_middle/connection_inventory.csv
00_middle/scenario/<scenario>/harden_sdc_manifest.csv
00_middle/scenario/<scenario>/pending/<inst>.ports
00_middle/scenario/<scenario>/disposition/
00_result/reports/inventory_report.txt
```

`harden_sdc_manifest.csv` 是所有需读取 harden SDC 的 stage 的唯一文件选择接口，最少字段为：

```text
scenario
inst_name
module_name
sdc_path
availability_status
note
```

`availability_status` 使用 `available` / `missing` / `not_required`。`available` 必须提供明确 `sdc_path`；`missing` 可保留预期路径，路径尚未确定时可留空；`not_required` 的路径应为空。`note` 可选，但 `(inst_name, scenario)` manifest 行不能缺失。

manifest 只负责“明确选哪个文件”和“当前是否交付”，不强制保存 `file_digest`、`mapping_source` 或 meta。脚本直接读取 `sdc_path` 当前内容。项目采用“输入更新后从干净状态完整重跑，并对比前后产物”的确认模型。SHA-256 可以写入 debug bundle 方便排查，但不作为正常运行 gate，也不进入正式 SDC 造成无意义 diff。

### 5.2 01

```text
01_middle/common/clock_inventory.csv
01_middle/common/clock_inventory.meta
01_middle/scenario/<scenario>/clock_inventory.csv
01_middle/scenario/<scenario>/clock_inventory.meta
01_middle/assembled/<scenario>/clock_inventory.csv
01_middle/assembled/<scenario>/clock_inventory.meta
01_middle/scenario/<scenario>/removed_log/01_soc_clocks.removed
01_result/common/01_soc_clocks.sdc
01_result/scenarios/<scenario>_clocks.sdc
01_result/reports/clock_check_report.txt
```

`common` inventory 记录 common 01 SDC 的有效 clock；`scenario/<scenario>` inventory 只记录该 scenario overlay 新增或明确改写的 clock。`assembled/<scenario>` 是 downstream 唯一允许读取的 effective clock universe：

```text
scenario = common:
  assembled = common

scenario != common:
  assembled = common + scenario overlay
```

`assembled/<scenario>/clock_inventory.meta` 至少记录 common/scenario 最终 SDC path/digest、assembled clock set digest 和 scenario。02/03/04/20/30 不允许读取 auto-only 临时 inventory，也不允许自行合并 common/scenario clock。当前 legacy 01 尚未生成这些分层产物；在迁移完成前只能将 `common`/func-only 用法视为已实现范围。

### 5.3 02

```text
02_middle/02_soc_clock_timing_budget_<stage>.xlsx
02_middle/resolved/<scenario>_<stage>_<corner>.manifest
02_result/common/02_soc_clock_timing_<stage>_<corner>.sdc
02_result/scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc
02_result/reports/
```

### 5.4 03

```text
03_middle/03_soc_clock_groups.xlsx
03_middle/relation_map/<scenario>.csv
03_middle/relation_map/<scenario>.meta
03_result/common/03_soc_clock_groups.sdc
03_result/scenarios/<scenario>_clock_groups.sdc
03_result/reports/
```

`relation_map/<scenario>.csv` 必须是当前 assembled clock universe 的完整无序 clock-pair map，包括未命中显式 clock-group rule 而仍按默认 synchronous 分析的 pair。最少字段为 `schema_version,scenario,clock_a,clock_b,relation_type,relation_source,source_rule_ids,clock_universe_digest,assembled_view_digest`。`relation_source` 区分 `explicit_rule` 与 `default_synchronous`。`<scenario>.meta` 记录 01 assembled inventory digest、03 form digest、common/scenario SDC digest 和 CSV digest。

### 5.5 04

```text
04_middle/04_soc_io_pads.xlsx
04_middle/scenario/<scenario>/removed_log/04_soc_io_pads.removed
04_result/common/04_soc_io_pads.sdc
04_result/common/04_soc_io_pads_<stage>_<corner>.sdc
04_result/scenarios/
04_result/reports/
```

### 5.6 10

```text
10_middle/feedthrough_inventory.csv
10_middle/scenario/common/removed_log/10_feedthrough.removed
10_result/common/10_feedthrough.sdc
10_result/reports/feedthrough_check_report_common.txt
```

### 5.7 20

```text
20_middle/20_harden_x_if.xlsx
20_middle/channel_inventory.csv
20_middle/scenario/<scenario>/removed_log/20_harden_x_if.removed
20_result/common/20_harden_x_if.sdc
20_result/common/20_harden_x_if_<stage>_<corner>.sdc
20_result/scenarios/
20_result/reports/
```

### 5.8 30

```text
30_middle/30_harden_to_harden_exception.xlsx
30_middle/exception_candidates.csv
30_middle/scenario/<scenario>/removed_log/30_harden_to_harden_exception.removed
30_result/common/30_harden_to_harden_exception.sdc
30_result/common/30_harden_to_harden_exception_<stage>_<corner>.sdc
30_result/scenarios/
30_result/reports/
```

## 6. Fixed Downstream Reads

默认依赖路径固定为：

```text
01 <- 00_middle/connection_inventory.csv
01 <- 00_middle/scenario/<scenario>/harden_sdc_manifest.csv
01 <- 00_middle/scenario/<scenario>/pending/

02 <- 01_middle/assembled/<scenario>/clock_inventory.csv
02 <- 01_middle/assembled/<scenario>/clock_inventory.meta

03 <- 01_middle/assembled/<scenario>/clock_inventory.csv
03 <- 01_middle/assembled/<scenario>/clock_inventory.meta

04 <- 00_middle/connection_inventory.csv
04 <- 00_middle/scenario/<scenario>/harden_sdc_manifest.csv
04 <- 01_middle/assembled/<scenario>/clock_inventory.csv
04 <- 00_middle/scenario/<scenario>/pending/

10 <- 00_middle/connection_inventory.csv
10 <- 00_middle/scenario/common/pending/

20 <- 00_middle/connection_inventory.csv
20 <- 00_middle/scenario/<scenario>/harden_sdc_manifest.csv
20 <- 01_middle/assembled/<scenario>/clock_inventory.csv
20 <- 03_middle/relation_map/<scenario>.csv
20 <- 10_middle/feedthrough_inventory.csv

30 <- 00_middle/connection_inventory.csv
30 <- 00_middle/scenario/<scenario>/harden_sdc_manifest.csv
30 <- 01_middle/assembled/<scenario>/clock_inventory.csv
30 <- 03_middle/relation_map/<scenario>.csv
30 <- 10_middle/feedthrough_inventory.csv
30 <- 20_middle/channel_inventory.csv
```

规则：

- downstream 不得用 `glob("*.csv")`、扫描 cwd 或猜测最近文件来选择 upstream artifact。
- 默认路径按 `--run-root` 解析；允许 CLI 显式 override，但 report 必须打印 resolved absolute path。
- upstream 必需文件缺失或 scenario/stage/corner 不匹配时必须阻断，不允许静默 fallback。需要 stale 检查的已生成 machine artifact 可继续使用其自身 meta/digest 契约；harden SDC manifest 不使用 digest gate。
- 上一条的“upstream 文件缺失”不包括 manifest 中已显式记录的 `availability_status=missing` harden SDC：该情况按 partial-availability mode 继续。manifest 本身缺失、available 行路径不存在、或开启 `--require-complete-harden-sdc` 后仍有 missing 才阻断。
- stage result 可以被 flow source；stage middle 只供脚本/审核消费，不能直接作为 SDC source。
- 20/30 读取 03 relation map 只用于约束语义一致性检查：防止在 async/exclusive pair 上误生成普通同步 budget，并识别 30 false-path 冗余或 CDC max/min 配套。clock relation 不决定 pending owner，也不能自动把 channel 提升为 30 exception。
- 10 v1 只在 common 结构视图中运行。其 `validation_status=matched` 的 common structural removed log 必须重放到所有已初始化的 scenario pending 视图；`needs_review` 或未来 scenario-specific feedthrough 不得重放。

## 7. Migration Rule

脚本迁移到 flat layout 时应按 stage 分批完成：

1. 先增加 `--run-root` 和新目录写入能力。
2. regression 同时验证新路径和 legacy 输入兼容期。
3. downstream 全部切换到固定路径后，删除 legacy cwd glob/fallback。
4. 最后更新打包脚本，只打包 flat Python scripts；规则、测试和文档继续不进入内网脚本包。
