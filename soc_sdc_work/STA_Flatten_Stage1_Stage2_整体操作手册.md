# STA Flatten Stage 1 + Stage 2 整体操作手册

- Author: Howard
- Stage 1: Harden DC SDC Clean
- Stage 2: Integration E2E Delay Merge with PrimeTime
- Stage 2 Tcl version: v0.8.9

本文说明从 harden 原生 DC SDC 提纯，到 integration top 最终生成
`<top_name>_flatten.sdc` 和 Excel review 报告的完整流程。

## 1. 流程总览

```text
Harden 原生 DC SDC
        |
        v
Stage 1 提纯及 hierarchy mapping
        |
        +--> harden clean SoC SDC
        |
        v
PrimeTime 读取 library、top/harden 网表及原始输入 SDC
        |
        v
Stage 2 递归推导并合并 E2E delay
        |
        +--> <top_name>_flatten.sdc（最终单文件 SDC）
        +--> delay_path_summary/（Excel 输入）
        +--> integration_delay_merge.rpt（合并报告）
        |
        v
run_stage2_report.py
        |
        +--> <top_name>.xlsx（最终 review 表单）
```

## 2. Stage 1：Harden SDC 提纯

进入 Stage 1 脚本目录：

```bash
cd "Flatten SDC脚本/STA Flatten 1 Harden DC SDC Clean 脚本"
```

执行 harden SDC 提纯：

```bash
python3 proc_harden_sdc.py \
  --in ucie_uaxi_top.sdc \
  --out run_ucie_uaxi_top/ucie_uaxi_top_soc.sdc \
  --removed-out run_ucie_uaxi_top/ucie_uaxi_top_removed.sdc \
  --unsupported-out run_ucie_uaxi_top/ucie_uaxi_top_unsupported.sdc \
  --modified-details run_ucie_uaxi_top/ucie_uaxi_top_modified_details.txt \
  --report run_ucie_uaxi_top/ucie_uaxi_top_report.txt \
  --inst u_soc/u_ucie_uaxi_top
```

部分版本中的入口脚本已改名为 `run_stage1_clean_sdc.py`。如果当前目录没有
`proc_harden_sdc.py`，只替换命令中的脚本名，其余参数保持不变：

```bash
python3 run_stage1_clean_sdc.py \
  --in ucie_uaxi_top.sdc \
  --out run_ucie_uaxi_top/ucie_uaxi_top_soc.sdc \
  --removed-out run_ucie_uaxi_top/ucie_uaxi_top_removed.sdc \
  --unsupported-out run_ucie_uaxi_top/ucie_uaxi_top_unsupported.sdc \
  --modified-details run_ucie_uaxi_top/ucie_uaxi_top_modified_details.txt \
  --report run_ucie_uaxi_top/ucie_uaxi_top_report.txt \
  --inst u_soc/u_ucie_uaxi_top
```

### 2.1 Stage 1 输出检查

重点检查：

1. `ucie_uaxi_top_soc.sdc`：Stage 2 使用的 clean harden SDC。
2. `ucie_uaxi_top_removed.sdc`：按 Stage 1 规则删除的约束。
3. `ucie_uaxi_top_unsupported.sdc`：脚本无法安全转换的命令，必须 review。
4. `ucie_uaxi_top_modified_details.txt`：所有修改项的 before/after。
5. `ucie_uaxi_top_report.txt`：提纯统计和异常汇总。

`--inst` 必须与 integration top 网表中的 harden instance path 完全一致。同一个
harden module 如果例化多次，每个 instance 都需要独立执行 Stage 1 或生成与其
instance path 对应的 clean SDC。

## 3. 准备 harden_list.csv

Stage 2 不需要在 CSV 中填写 top 信息，只填写 integration top 下的 harden：

```csv
harden_name,inst_path,clean_sdc,delay_candidate_file,netlist,module
ucie0,u_soc/u_ucie_uaxi_top,/abs/path/run_ucie_uaxi_top/ucie_uaxi_top_soc.sdc,,/abs/path/ucie_uaxi_top.v,ucie_uaxi_top
```

字段含义：

- `harden_name`：harden 的逻辑名称，用于报告识别。
- `inst_path`：当前 integration top 下的完整 instance path。
- `clean_sdc`：Stage 1 输出的 clean SoC SDC。
- `delay_candidate_file`：可选 delay candidate CSV，没有则留空。
- `netlist`：harden 网表路径，用于记录和检查。
- `module`：harden Verilog module 名称。

建议在内网运行时使用绝对路径，避免 PT 工作目录变化后找不到文件。

## 4. 启动 PrimeTime 并建立干净环境

启动：

```bash
pt_shell
```

按照项目现有 PT flow 设置 library 和网表。以下命令仅作为结构示例，实际 `.db`、
网表和 top module 名称按项目修改：

```tcl
set search_path [list \
  /abs/path/to/netlist \
  /abs/path/to/lib \
  /abs/path/to/sdc \
]

set link_path [list * \
  /abs/path/to/lib/slow.db \
  /abs/path/to/lib/other.db \
]

read_verilog /abs/path/to/top.v
read_verilog /abs/path/to/ucie_uaxi_top.v
read_verilog /abs/path/to/other_harden.v

link_design <top_module_name>
current_design <top_module_name>
```

确认 link 成功后，读取原始输入约束：

```tcl
read_sdc /abs/path/to/top_dc.sdc
read_sdc /abs/path/run_ucie_uaxi_top/ucie_uaxi_top_soc.sdc
read_sdc /abs/path/to/other_harden_soc.sdc
```

这里的 PT database 只允许包含：

- top 网表和 harden 网表；
- 项目所需 `.db`、corner、RC/SPEF 和基础 STA setup；
- top 原生 DC SDC；
- Stage 1 输出的 harden clean SDC。

严禁在运行 Stage 2 之前加载：

```text
generated_e2e_delay.sdc
*_flatten.sdc
以前运行 Stage 2 生成的任何 delay SDC
```

不要使用不加筛选的 `read_sdc *.sdc`，否则旧输出可能被重新读入 PT，污染
`all_fanin` / `all_fanout -endpoints_only` 的推导结果。

### 4.1 基础状态确认

```tcl
current_design
check_timing
```

并抽查 top/harden 对象能够被 PT 找到：

```tcl
sizeof_collection [get_cells -quiet -hierarchical {u_soc/u_ucie_uaxi_top}]
sizeof_collection [get_pins -quiet {u_soc/u_ucie_uaxi_top/*}]
```

返回对象数量大于 `0`，才具备运行 Stage 2 的基础条件。

## 5. 修改 Stage 2 配置

打开：

```text
Flatten SDC脚本/STA Flatten 2 Set Delay Merge PrimeTime脚本/run_stage2_merge_delay.tcl
```

当前 v0.8.9 中重点配置位于 L31、L37、L41 附近。升级脚本后行号可能变化，
应以变量名为准：

```tcl
# L31：本次运行和输出目录
set ::RUN_DIR {/abs/path/to/pt_stage2_run}

# L37：top 原生 DC SDC
set ::TOP_SDC {/abs/path/to/top_dc.sdc}

# L41：harden_list.csv
set ::HARDEN_LIST {/abs/path/to/harden_list.csv}

# 输出目录
set ::OUT_DIR $::RUN_DIR
```

保持推荐设置：

```tcl
set ::MERGE_MODE replace
set ::TOP_PORT_BOUNDARY_MAP_MODE connectivity
set ::TOP_OPEN_FROM_MODE enumerate_static_startpoints
set ::RECURSIVE_CHAIN_MODE auto
set ::MAX_CHAIN_DEPTH 6
set ::STAGE2_POST_CHECK false
set ::STAGE2_VERBOSE_PT_QUERY true
set ::WRITE_PATH_SUMMARY true
set ::STAGE2_TEXT_ENCODING utf-8
```

`TOP_SDC` 的 basename 决定默认最终输出名：

```text
top_dc.sdc  -> top_dc_flatten.sdc
aie_top.sdc -> aie_top_flatten.sdc
```

## 6. 在 PT 中运行 Stage 2

确认当前 PT session 是干净环境后执行：

```tcl
source {/abs/path/to/Flatten SDC脚本/STA Flatten 2 Set Delay Merge PrimeTime脚本/run_stage2_merge_delay.tcl}
```

脚本会打印作者、版本、输入路径、输出路径和 PT query 动作。等待 terminal 出现
最终 `INFO` 汇总后再检查输出，不要在执行中重复 source 脚本。

主要输出：

```text
<top_name>_flatten.sdc
generated_e2e_delay.sdc
integration_delay_merge.rpt
merged_delay_removed.sdc
unmerged_delay_review.rpt
delay_path_summary/
```

含义：

- `<top_name>_flatten.sdc`：最终单文件 SDC。
- `generated_e2e_delay.sdc`：Stage 2 生成的 E2E delay 中间结果。
- `integration_delay_merge.rpt`：合并数量、策略和详细推导记录。
- `merged_delay_removed.sdc`：被 E2E 替换的原始 delay 审计文件，禁止 source。
- `unmerged_delay_review.rpt`：无法自动处理、需要人工确认的 delay。
- `delay_path_summary/`：Excel 报告的 CSV 输入目录。

## 7. 生成 Stage 2 Excel 报告

进入 Stage 2 输出目录：

```bash
cd /abs/path/to/pt_stage2_run
```

运行：

```bash
python3 "/abs/path/to/Flatten SDC脚本/STA Flatten 2 Set Delay Merge PrimeTime脚本/run_stage2_report.py" ./delay_path_summary
```

如果脚本就在当前目录：

```bash
python3 run_stage2_report.py ./delay_path_summary
```

默认输出：

```text
<TOP_SDC_basename>.xlsx
```

例如 `TOP_SDC=aie_top.sdc`，则报告为：

```text
aie_top.xlsx
```

报告中：

- top 和每个 harden instance 各占一张 sheet；
- 黄色区域表示当前 sheet 对应的 delay stage；
- 红色 `NOT FOUND` 表示该 stage 没有原生 delay，按 `0` 参与 E2E 推导；
- `Max Delay Used: N/M` 表示该 SDC 原生 max delay 中被 Stage 2 使用的数量；
- `E2E ID` 与最终 flatten SDC 中的注释编号对应。

Python 环境需要安装 `openpyxl`。如果提示缺少模块，在项目允许的 Python 环境中
安装后重新执行。

## 8. 最终 SDC 组成和使用方式

`<top_name>_flatten.sdc` 的内容顺序为：

```text
TOP_REMAINING_SDC
GENERATED_E2E_DELAY_SDC
HARDEN_REMAINING_SDC inst=<harden_1>
HARDEN_REMAINING_SDC inst=<harden_2>
...
STAGE2_REVIEW_REQUIRED
```

默认 `MERGE_MODE=replace` 下：

1. top SDC 中未被 consume 的内容保留。
2. 各 harden clean SDC 中未被 consume 的内容保留。
3. 成功 merge 的原始 delay 从 top/harden 区块移除。
4. `generated_e2e_delay.sdc` 中的 E2E delay 被直接写入最终 flatten SDC。
5. 未成功 merge 的 passthrough/review delay 仍保留在原 top/harden 区块。
6. 多对象 delay 仅部分 merge 时，未 merge pair 会展开后保留。
7. 最后追加 review 摘要注释。

因此，最终 STA 不应同时 source top SDC、harden clean SDC、
`generated_e2e_delay.sdc` 和 `<top_name>_flatten.sdc`。正确方式是在重新建立的
干净 PT validation session 中，仅加载最终 flatten SDC：

```tcl
read_sdc /abs/path/to/<top_name>_flatten.sdc
```

然后执行项目要求的：

```tcl
check_timing
report_exceptions
report_exceptions -ignored
report_analysis_coverage
```

## 9. 推荐 Review 顺序

```text
1. integration_delay_merge.rpt
2. unmerged_delay_review.rpt
3. <top_name>.xlsx
4. generated_e2e_delay.sdc
5. merged_delay_removed.sdc
6. <top_name>_flatten.sdc
```

重点确认：

- `Review required constraints` 是否为预期数量；
- Excel 是否存在异常红色 `NOT FOUND`；
- 每条生成约束是否都有明确 `-from` 和合法 `-to`；
- `E2E ID` 是否能在 Excel 与 flatten SDC 之间一一对应；
- `report_exceptions -ignored` 是否出现 `p non-existent path`、`t invalid endpoint`
  或其它异常原因；
- 最终 SDC 中是否仍存在不应重复生效的原始 delay。

## 10. 常见问题

### 10.1 组合逻辑 pin 被识别成 endpoint

先在未加载任何 Stage 2 输出的干净 PT session 中执行：

```tcl
redirect -file clean_endpoint_list.rpt {
    foreach_in_collection ep [all_fanout -flat -endpoints_only \
        -from [get_pins {<harden_inst>/<input_pin>}]] {
        puts [get_object_name $ep]
    }
}
```

如果干净环境中没有异常组合 pin，而旧 session 中存在，通常是旧
`generated_e2e_delay.sdc` 或 `*_flatten.sdc` 已被 source，造成 endpoint
自污染。重新启动 PT，并只加载原始输入后再运行 Stage 2。

### 10.2 generated_e2e_delay.sdc 为空

检查：

1. `harden_list.csv` 的 `inst_path`、`clean_sdc` 是否正确；
2. PT 是否能找到 harden boundary pin 和内部 endpoint；
3. `integration_delay_merge.rpt` 的 `[PASSTHROUGH]` 和 `[REVIEW]`；
4. terminal 中 `PT_QUERY` 的 collection count 是否为 `0`；
5. top/harden delay 的 max/min 类型和 boundary 是否能够形成完整链条。

### 10.3 输出中文注释乱码

默认：

```tcl
set ::STAGE2_TEXT_ENCODING utf-8
```

旧 SDC 如果使用 GBK/GB2312，可在确认文件编码后改为：

```tcl
set ::STAGE2_TEXT_ENCODING gb2312
```

### 10.4 重复运行 Stage 2

不要在已经 source 过生成 SDC 的 PT session 中直接重复运行。推荐每次重新 link
并只加载原始 top SDC 和 harden clean SDC，然后执行一次 Stage 2。

## 11. 最简执行清单

```text
[ ] Stage 1 对每个 harden 生成 clean SoC SDC
[ ] Review removed / unsupported / modified / report
[ ] 准备 harden_list.csv，不填写 top 行
[ ] 启动干净 PT，读取 library 和 top/harden 网表
[ ] link_design / current_design 成功
[ ] 只读取 top 原生 SDC 和 harden clean SDC
[ ] 确认没有读取旧 generated/flatten SDC
[ ] 修改 RUN_DIR、TOP_SDC、HARDEN_LIST
[ ] 保持 STAGE2_POST_CHECK=false
[ ] source run_stage2_merge_delay.tcl 并等待完成
[ ] 运行 run_stage2_report.py ./delay_path_summary
[ ] Review rpt、xlsx、generated、removed 和最终 flatten SDC
[ ] 在新的干净 PT session 中只加载最终 flatten SDC 做 signoff 检查
```
