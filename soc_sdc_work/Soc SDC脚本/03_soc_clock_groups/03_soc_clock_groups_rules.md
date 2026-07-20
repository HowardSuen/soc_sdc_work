# 03_soc_clock_groups.sdc Rules

本 stage 遵守 [Shared Script Runtime Rules](../docs/shared_script_runtime_rules.md)。03 的 clock relationship 主体功能不变；一个 run root 只有一个场景，03 不接收 scenario，也不做 port accounting。

## 1. 目标

03 生成 SoC clock relationship：

```text
asynchronous
logically_exclusive
physically_exclusive
```

输出：

```text
03_result/03_soc_clock_groups.sdc
03_middle/relation_map.csv
03_middle/relation_map.meta
03_middle/stage_completion.meta
03_result/reports/clock_group_check_report.txt
03_result/reports/clock_group_coverage_report.xlsx
```

03 不创建 clock，不设置 clock timing budget，不处理 IO delay、data interface budget 或 path exception。

## 2. Clock Universe

唯一输入 clock universe：

```text
inputs/run_context.csv
inputs/required_views.csv
01_middle/clock_inventory.csv
01_middle/clock_inventory.meta
01_middle/stage_completion.meta
```

inventory 必须与最终 `01_result/01_soc_clocks.sdc` digest 和 active clock set 一致。manual overlay、SoC top clock、SoC virtual clock 和 SoC-visible harden output clock 只有进入 01 inventory 后才能被 03 引用。

以下对象不进入 03：

- harden boundary input 上的重复 clock declaration。
- harden internal/local clock。
- private virtual clock。
- 不在当前 run 01 inventory 中的 mode clock。

03 不读取 port connectivity，也不修改 Used 状态列。

## 3. 默认 STA 姿态

没有显式 rule 的 clock pair 默认保持 synchronous。03 不根据 clock 名称自动异步，也不因为 pair 没有普通数据 path 就自动切断。

共享 relation enum：

```text
synchronous
asynchronous
logically_exclusive
physically_exclusive
unknown
```

03 输出前三种非默认 relation；`synchronous` 和 `unknown` 主要进入 relation map / coverage。

## 4. Relation 语义

### 4.1 `asynchronous`

用于没有固定 setup/hold 相位关系的 clock domain。命令示例：

```tcl
set_clock_groups -asynchronous \
  -group [get_clocks {clk_a}] \
  -group [get_clocks {clk_b}]
```

若 A/B/C 需要 pairwise async，必须明确生成足以覆盖所有 pair 的 group 语义，不能只写三组到一个命令后误以为每组内部也互相异步。

### 4.2 `logically_exclusive`

用于逻辑 mux 等结构中不会同时传播/有效的 clock。必须有 mux/功能依据。

如果当前 run 的 pre-setup 已经通过 `set_case_analysis` 选定单腿，通常不再对同一 mux leg 追加 logically exclusive；项目应在 `per_run_case` 与 `merged_exclusive` 两种方法学中选择一种。

### 4.3 `physically_exclusive`

用于物理上不能同时存在的 clock source，要求更强的硬件依据。不能把普通逻辑互斥升级为 physical exclusive。

## 5. Domain Closure

表单允许先定义 domain membership，再用 domain 建 group rule。一个 domain 的 closure 至少包括：

```text
root clock
所有应继承该 relationship 的 generated/forwarded descendants
manual 声明的附加成员
明确排除的 member
```

`exclude_descendant_clocks=yes` 只有在架构确认 descendants 不继承关系时使用。

同一 active clock 默认只能属于一个 active domain；重复 membership 必须 error 或有明确 override 机制。

## 6. Review Workbook

```text
03_middle/03_soc_clock_groups.xlsx
```

建议包含：

```text
clock_domain_membership
clock_group_rules
clock_group_candidates
run_metadata
```

### 6.1 `clock_domain_membership`

建议字段：

```text
domain_id
clock_name
membership_type
root_clock
apply
review_status
basis
note
```

`clock_name` 必须存在于 01 inventory。

### 6.2 `clock_group_rules`

建议字段：

```text
group_id
relation_type
group_1_domains
group_2_domains
exclude_descendant_clocks
analysis_style
apply
review_status
owner
basis
note
```

`analysis_style` 可使用：

```text
normal
merged_exclusive
per_run_case
```

`per_run_case` 通常 `apply=no`，只记录当前 run 已由 pre-setup case-select。

### 6.3 `clock_group_candidates`

脚本可根据 root source、harden SDC evidence、命名和 topology 生成候选，但 candidate 不能直接生成 SDC。candidate 至少记录 reason、evidence 和 recommended action。

## 7. 脚本机制

### 7.1 命令行

```bash
python3 03_extract_soc_clock_groups.py \
  --run-root <run_root>
```

不接受 scenario 选择。

### 7.2 同步和 review gate

1. 读取 01 inventory/meta。
2. 创建或更新 review workbook 的 machine context。
3. 新 clock 添加 candidate/membership 待 review。
4. 01 已删除的 clock 标记 stale。
5. workbook 同步变化时不生成正式 SDC。
6. 只对 `apply=yes + review_status=approved` 的 rule 生成。

## 8. Relation Map

`03_middle/relation_map.csv` 是 10/20/30 的机器接口。每行表示一个 canonical unordered clock pair：

```text
schema_version
clock_a
clock_b
relation_type
relation_source
source_rule_ids
clock_universe_digest
assembled_view_digest
```

规则：

- `clock_a < clock_b` 使用稳定字典序。
- 所有 active clock pair 都应有记录，未显式分组的 pair 记为 `synchronous/default_synchronous`。
- 同一 pair 不能有多个冲突 relation。
- `unknown` 只用于 evidence 不完整，不能自动降级为 synchronous。
- `assembled_view_digest` 覆盖当前 run 的 active rule、effective group、relation 和 01 universe digest。

`relation_map.meta` 至少记录 01 inventory/meta digest、03 workbook semantic/file digest、03 SDC digest 和 relation-map digest。

`03_middle/stage_completion.meta` 必须记录 run provenance、structure digest、01 completion/inventory digest、03 workbook/relation-map/SDC digest、`error_count=0`、`sync_changed=no` 和 `Port accounting: not_applicable; added_bits=0`。review-required、stale 或 diagnose-only 不得标 complete。

## 9. Coverage Report

coverage workbook 至少包含：

```text
clock participation
explicit relation coverage
default synchronous pairs
unknown/incomplete pairs
stale/invalid rules
pair_relation_map review view
```

coverage workbook 的 pair map 和 `relation_map.csv` 必须来自同一计算结果。

## 10. 检查项

### Error

- 01 inventory/meta 缺失或 stale。
- rule/member 引用未知 clock。
- duplicate domain membership 或 group id。
- relation_type 非法。
- active rule 缺 owner/basis/review。
- 同一 pair 出现冲突 relation。
- `per_run_case` 仍 `apply=yes` 生成 exclusive。
- generated descendant 漏入/漏出导致 domain closure 不一致。

### Warning

- async/exclusive 依据不足。
- clock 名看似 test/scan/mbist，但当前 run 输入没有清晰说明。
- relation map 存在 unknown pair。
- partial harden SDC 可能导致 candidate 不完整。

## 11. 与 CDC / Exception 的边界

- 03 只描述 clock-domain relation，不生成 path-level false path/MCP/max/min。
- CDC 数据稳定窗口若需要 max/min override，由 30 处理并验证 03/30 exception priority。
- 局部 violating path 不能用 clock group 掩盖。

## 12. Port Accounting

03 永远不修改：

```text
Input Used Width
Output Used Width
Inout Name
```

clock relationship 不能单独成为 harden port 销账依据。
