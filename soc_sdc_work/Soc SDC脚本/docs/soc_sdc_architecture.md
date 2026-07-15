# SoC SDC Architecture

[Shared Script Runtime Rules](shared_script_runtime_rules.md) 是路径、CLI、scenario 和 accounting 权威。本架构定义 00~30 的业务边界和装配关系。

## 1. 总目标

本流程从 SoC 集成表单和当前 scenario 的 harden DC output SDC，生成 **SoC top 综合使用的 SDC**。

流程不读取 SoC netlist、`.lib/.db`、STA database 或 timing report 推断 coverage，也不生成 harden 内部约束。harden 内部 `fti -> fto`、internal exception 和 signoff 约束由 harden owner 完成。

## 2. 总体数据流

```text
inputs integration forms
        |
        v
00 bit-level connection inventory + scenario manifest/pending
        |
        +--> 01 clocks ------------------------------+
        |                                            |
        |       02 clock timing                      |
        |       03 clock relationships --------------+
        |       04 IO/pad                            |
        |       10 feedthrough-adjacent direct edge  |
        |       20 other functional direct channel   |
        |       30 path exception/override <---------+
        v
scenario SDC assembly
```

每个 stage 都显式输入 scenario。一个 run root 可以保存多个 scenario 子目录，但 pending、removed log、manifest 和 scenario machine artifact 必须隔离。

## 3. 数据权威

### 3.1 Integration

00 是 instance、port、range、connection 和 stable `connection_id` 的机器权威。01/04/10/20/30 只消费：

```text
00_middle/connection_inventory.csv
```

下游不得重新解析原始 integration range 或重新配 bit。

### 3.2 Harden SDC

00 为每个 scenario 生成：

```text
00_middle/scenario/<scenario>/harden_sdc_manifest.csv
```

01/04/10/20/30 根据 manifest 读取 available harden SDC。missing 不阻断其它 harden，但相关 evidence 保持 incomplete；strict gate 为 `--require-complete-harden-sdc`。

### 3.3 Stage Machine Artifacts

```text
01 assembled clock inventory -> 02/03/04/20/30
03 relation map              -> 30；20 budget_output；10 optional diagnostic
10 feedthrough edge inventory -> 20/30
20 channel inventory          -> 30
```

这些 artifact 是 stage 间业务接口，不替代 00 connection inventory。

## 4. Scenario 和 Common

现有 stage 采用 common + scenario overlay：

```text
effective view = common + current scenario
```

01/03/04/10/20/30 生成 common 和 scenario 文件，并在生成阶段检查 assembled-view 冲突。02 采用 resolved-single-file：具体 scenario 行优先于 common fallback，最终只 source 当前 scenario 的 resolved 02 文件。

project-owned `scenarios/<scenario>_pre.sdc` 在 SDC 装配最前面执行，用于 `set_case_analysis` 等 mode setup，不由 00~30 自动生成。

## 5. Accounting

port accounting 默认开启。00 初始化当前 scenario pending；01/04/10/20/30 在 approved terminal disposition 后删除 exact canonical bit 并写 stage-local removed log。02/03 不销账。

显式诊断选项可以关闭 mutation，但必须在 report 中标记且不得声称 closure 完成。

pending 是 port-level closure 视图，不是 connection 真源。fanout/path-level 完整性仍由 10/20/30 edge/candidate coverage 负责。

## 6. Stage 定位

### 6.1 00_harden_port_inventory

- 解析 integration forms。
- 展开 bit-level direct edge。
- 生成 stable `connection_id` 和 `scenario_scope`。
- 生成 scenario harden SDC manifest。
- 默认初始化 pending。
- 维护 `00_disposition`。

00 不生成 SDC。

### 6.2 01_soc_clocks

- 从 available harden SDC 提取 SoC-visible `create_clock` / `create_generated_clock`。
- 用 00 exact edge 将 harden boundary clock 提升到 SoC object。
- 合并 virtual/manual clock。
- 生成 common、scenario 和 assembled clock inventory/meta。

01 不生成 uncertainty、latency、transition、clock group 或 data exception。

### 6.3 02_soc_clock_timing

- 读取 01 assembled clock inventory。
- 生成 uncertainty、latency、transition、propagated 和 derate hook。
- 按 scenario/stage/corner resolve 唯一胜出行。
- 不参与 port accounting。

### 6.4 03_soc_clock_groups

- 表达 asynchronous/logically-exclusive/physically-exclusive clock relationships。
- 对当前 assembled clock universe 做 domain closure 和 conflict check。
- 生成完整无序 clock-pair relation map；未显式覆盖的 pair 记录 default synchronous。
- 不参与 port accounting。

relation map 只做下游语义检查，不决定 port owner，也不自动生成 exception。

### 6.5 04_soc_io_pads

- 从 00 edge 识别 top pad 与 harden boundary。
- 从 available harden SDC 提取并 review IO delay、driver、transition、load 和 pad-specific exception。
- 对 GPIO/inout 使用当前 scenario 方向状态。
- 生成 common/scenario IO SDC。

top pad environment 归 04，优先于 10/20/30。

### 6.6 10_feedthrough

对于：

```text
u_src/out -> u_ft/fti -> [harden internal] -> u_ft/fto -> u_dst/in
```

10 只处理：

```text
u_src/out -> u_ft/fti
u_ft/fto  -> u_dst/in
u_ft1/fto -> u_ft2/fti
```

每条都是独立 SoC-visible direct edge。10 不生成内部 `fti -> fto`，不拼 end-to-end channel。exception-only edge 使用 `route_to_30`。

### 6.7 20_harden_x_if

20 处理不属于 clock/pad/10 的普通 functional direct channel。

默认 `audit_only`：建立 inventory、检查 ownership、记录 approved no-budget disposition，不输出 timing command，空占位 SDC 不进入 source list。

明确启用 `budget_output` 且有 reviewed physical interconnect budget 时，才生成 `set_max_delay` / `set_min_delay`。20 使用 10 inventory 按 `connection_id` 排除 10-owned edge，禁止通过 pair/chain 拼接 end-to-end channel。

已识别 exception-only channel 必须 `route_to_30`，20 不销账。

### 6.8 30_harden_to_harden_exception

30 只表达有架构/协议/CDC/RDC/waiver 依据的 path-level exception/override：

```text
set_false_path
set_multicycle_path
exception max/min override
```

30 用 10/20 inventory 检查 normal owner 和 overlap。缺少 20 inventory 时只生成 candidate/report，不得生成正式 30 SDC。feedthrough-related exception 只能作用于 10 已 `route_to_30` 的同一 direct edge。

## 7. Direct Edge Ownership

```text
clock -> 01
top pad / IO -> 04
feedthrough-adjacent direct edge -> 10
other normal functional direct edge -> 20
exception/override for classified edge/path -> 30
```

10/20 以 00 stable `connection_id` 互斥。30 是 path-level owner，不允许与 active 10/20 normal budget 在同一 check 维度冲突。

## 8. 推荐装配顺序

```tcl
# 1. Mode setup
source scenarios/<scenario>_pre.sdc

# 2. Clock creation
source 01_result/common/01_soc_clocks.sdc
source 01_result/scenarios/<scenario>_clocks.sdc              ;# scenario != common

# 3. Resolved clock timing: only one file
source 02_result/common/02_soc_clock_timing_<stage>_<corner>.sdc              ;# scenario=common
source 02_result/scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc      ;# scenario!=common

# 4. Clock relationships
source 03_result/common/03_soc_clock_groups.sdc
source 03_result/scenarios/<scenario>_clock_groups.sdc

# 5. IO/pad
source 04_result/common/04_soc_io_pads.sdc
source 04_result/common/04_soc_io_pads_<stage>_<corner>.sdc    ;# if exists
source 04_result/scenarios/<scenario>_io_pads.sdc
source 04_result/scenarios/<scenario>_io_pads_<stage>_<corner>.sdc ;# if exists

# 6. Direct-edge physical budget
source 10_result/common/10_feedthrough.sdc
source 10_result/scenarios/<scenario>_feedthrough.sdc
# 20 only when mode=budget_output
source 20_result/common/20_harden_x_if.sdc
source 20_result/scenarios/<scenario>_harden_x_if.sdc

# 7. Exceptions last
source 30_result/common/30_harden_to_harden_exception.sdc
source 30_result/scenarios/<scenario>_exceptions.sdc
```

`scenario=common` 时只 source common 文件。view-specific 文件仅在当前 stage/corner 存在时追加。每个 stage 必须在输出前完成 assembled conflict check。

## 9. 当前实现状态

本文定义目标规则，不表示 Python 已全部实现。迁移重点：

- 00 initializer/connection inventory 需要实现或收口。
- 01/10/20/30 需要补齐 scenario CLI 和 target 固定路径。
- 01/04 需要停止在 target 模式直接解析 integration range。
- 20 必须生成 scenario `channel_inventory.csv`，30 必须强制消费后才能正式输出。
- 30 需要生成 scenario candidate CSV 和 target removed log。
- 完成 regression 后重新生成内网包；旧包作废。

## 10. 相关文档

- [Shared Script Runtime Rules](shared_script_runtime_rules.md)
- [Harden SDC Requirements](harden_sdc_requirements.md)
- [00 Project Context](00_project_context.md)
