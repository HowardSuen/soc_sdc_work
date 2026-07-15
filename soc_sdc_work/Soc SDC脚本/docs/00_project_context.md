# SoC SDC Project Context

本文用于会话接力和快速恢复上下文。统一运行契约见 [Shared Script Runtime Rules](shared_script_runtime_rules.md)，业务边界见 [SoC SDC Architecture](soc_sdc_architecture.md)。

## 1. 项目目标

从 harden DC output SDC 和 SoC 集成互联表单生成 **SoC top 综合使用的 SDC**。

流程不生成 harden 内部约束，不从 SoC netlist、`.lib/.db`、STA database 或 timing report 推断 coverage。SpyGlass CDC 可以复用 clock/clock-group 信息，但 STA exception 不与 CDC/RDC 规则一一等价。

## 2. 当前统一运行契约

- 00 直接解析 `inputs/info_all.xlsx` 和 `inputs/port_*.xlsx` / `ports_*.xlsx`。
- 00 正式生成 bit-level `00_middle/connection_inventory.csv`。
- 每条 direct bit edge 有稳定 `connection_id`；下游不重新展开 range。
- 00~30 每个 stage 都显式输入 scenario。
- 同一个 run root 可以保存多个 scenario 子目录。
- manifest、pending、removed log 和 scenario machine artifact 按 scenario 隔离。
- port accounting 默认开启；01/04/10/20/30 默认销账，02/03 不销账。
- harden SDC 默认允许 partial availability；strict/signoff 使用 `--require-complete-harden-sdc`。
- target `--run-root` 与 legacy cwd 布局不能混用。

scenario canonical enum：

```text
common
func
scan
mbist
gpio_in
gpio_out
```

## 3. 00 Machine Artifacts

```text
00_middle/connection_inventory.csv
00_middle/scenario/<scenario>/harden_sdc_manifest.csv
00_middle/scenario/<scenario>/pending/<inst>.ports
00_middle/scenario/<scenario>/removed_log/00_disposition.removed
```

connection inventory：

- 一行一个 source-bit -> destination-bit direct edge。
- fanout 每个 sink 独立成行。
- 记录 `scenario_scope`；下游只选择 common/current scenario edge。
- 记录 canonical endpoint、SoC object、range source trace、validation 和 owner hint。
- 不包含 harden 内部 `fti -> fto` synthetic edge。

## 4. Common/Scenario 模型

01/03/04/10/20/30 使用：

```text
effective view = common + current scenario
```

02 使用 resolved-single-file：具体 scenario 行优先于 common fallback，装配时只 source 当前 resolved 02 文件。

01 生成 `assembled/<scenario>/clock_inventory.csv/.meta`；02/03/04/10/20/30 统一消费该 effective clock universe。

03 生成 `relation_map/<scenario>.csv/.meta`，用于下游 clock-domain 语义检查，不决定 port owner，也不自动生成 exception。

## 5. Stage 职责

### 5.1 01_soc_clocks

- 从 available harden SDC 提取 SoC-visible clock。
- 通过 00 exact bit edge 解析 clock source/target。
- 支持 virtual/manual clock。
- 输出 common/scenario SDC 和 assembled inventory/meta。
- 终结已创建或确认的 clock port。

### 5.2 02_soc_clock_timing

- 生成 uncertainty、latency、transition、propagated 和 derate hook。
- 按 scenario/stage/corner resolve 唯一输出。
- 不创建 clock、不做 clock group、不销账。

### 5.3 03_soc_clock_groups

- 生成 asynchronous/logically-exclusive/physically-exclusive group。
- 做 domain closure 和 assembled conflict check。
- 输出完整 pair relation map。
- 不做 path exception、不销账。

### 5.4 04_soc_io_pads

- 从 00 edge 识别 top pad/harden boundary。
- 从 available harden SDC 提取 IO/pad timing/electrical candidate。
- 处理 GPIO/inout scenario 方向。
- 输出 common/scenario 04 SDC并终结 approved pad port。

### 5.5 10_feedthrough

只处理 SoC-visible feedthrough-adjacent direct edge：

```text
u_src/out -> u_ft/fti
u_ft/fto  -> u_dst/in
u_ft1/fto -> u_ft2/fti
```

不处理 harden 内部 `fti -> fto`，不拼 end-to-end channel。exception-only edge 使用 `route_to_30`。

### 5.6 20_harden_x_if

处理其它普通 functional direct channel。

默认 `audit_only`：输出 scenario channel inventory、coverage 和 removed log，不输出 timing command，空占位 SDC 不进入 source list。

只有项目显式启用 `budget_output` 且 budget 经过 review，才生成 max/min。已识别 exception-only channel `route_to_30`，20 不销账。

正式 machine interface：

```text
20_middle/scenario/<scenario>/channel_inventory.csv
20_middle/scenario/<scenario>/channel_inventory.meta
```

### 5.7 30_harden_to_harden_exception

只处理有架构/协议/CDC/RDC/waiver 依据的 exception/override。

30 正式生成前必须读取 current-scenario 10/20 inventory 并完成 overlap 检查。缺少 20 inventory 时只生成 candidate-only workbook/CSV，不生成正式 SDC、不销账。

正式 candidate artifact：

```text
30_middle/scenario/<scenario>/exception_candidates.csv
```

## 6. Accounting

target pending：

```text
00_middle/scenario/<scenario>/pending/<inst>.ports
```

stage removed log：

```text
01_middle/scenario/<scenario>/removed_log/01_soc_clocks.removed
04_middle/scenario/<scenario>/removed_log/04_soc_io_pads.removed
10_middle/scenario/<scenario>/removed_log/10_feedthrough.removed
20_middle/scenario/<scenario>/removed_log/20_harden_x_if.removed
30_middle/scenario/<scenario>/removed_log/30_harden_to_harden_exception.removed
```

所有 key 逐 bit。previous-owner 只在当前 scenario 内检查。30 可在已有 port owner 后新增更窄 path exception，但不能重复删除 port。

## 7. Harden SDC 分批交付

- `available`：正常解析。
- `missing`：标记 incomplete，不能解释为无 clock/timing/exception。
- `not_required`：必须有依据。
- missing 相关 port 默认保留 pending。
- 具有 approved SDC-independent terminal basis 的 stage 例外按对应规则处理。
- strict/signoff mode 对 required missing 全局阻断。

## 8. 推荐装配顺序

```text
scenario pre-setup
01 clocks: common + scenario
02 clock timing: one resolved file
03 clock groups: common + scenario
04 IO/pad: common + scenario + optional view-specific
10 direct feedthrough edge: common + scenario
20 functional budget: only budget_output
30 exception: common + scenario, last
```

## 9. 当前实现状态

规则目标已收口，Python 尚未全部迁移：

- 00 initializer/connection inventory 需要实现或收口。
- 01 target scenario CLI、required 00 inventory 和 scenario pending 需要实现。
- 10 脚本需要完全迁移到 external direct-edge 模型。
- 20 需要输出 scenario channel inventory CSV。
- 30 需要强制 10/20 machine interface、scenario candidate CSV 和 target accounting。
- 所有 target regression 完成后重新生成内网包；旧包作废。

## 10. 文档维护

规则变更至少同步：

- `shared_script_runtime_rules.md`
- `soc_sdc_architecture.md`
- `00_project_context.md`
- 对应 stage rules/spec
- `architecture_rule_consistency_review.md`
