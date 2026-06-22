# 03_soc_clock_groups.sdc Rules

本文档记录 `03_soc_clock_groups.sdc` 的规则边界、建议表单格式和后续脚本机制。

## 1. 目标

`03_soc_clock_groups.sdc` 定义 SoC 级 clock relationship，即 clock domain 之间的 STA 分析关系。

03 只表达 clock 之间的关系，不定义 clock 自身，也不表达 path-level exception。

03 主要生成：

```tcl
set_clock_groups -asynchronous
set_clock_groups -logically_exclusive
set_clock_groups -physically_exclusive
```

03 依赖 `01_soc_clocks.sdc` 已经创建好的 clock object，也依赖 `01_soc_clocks` 生成的 `clock_inventory.csv` 做 clock name 检查和候选关系辅助分析。

### 1.1 默认 STA 姿态

当前 03 规则采用 **默认 synchronous + 显式枚举 async/exclusive** 的姿态：

- 未被 `set_clock_groups` 覆盖的 clock pair，在 STA 中保持默认 synchronous 分析。
- 表单主要枚举需要切断或互斥处理的 async / logically exclusive / physically exclusive 关系。
- coverage report 中的 `uncovered_cross_root_pairs` 表示这些跨 03 genealogy `tree_root` clock pair 仍按默认 synchronous 分析，供 reviewer 判断是否应新增 group 或保留默认。

如果项目决定采用 **默认 async + 显式声明 synchronous 例外** 的反向姿态，需要单独规划 03 表单语义、检查规则和 coverage report 读法；不能与当前规则混用。

## 2. 放什么

03 可以放：

- 架构上确认的 asynchronous clock group。
- 架构上确认的 logically exclusive clock group。
- 架构上确认的 physically exclusive clock group。
- scenario 专属 clock relationship，例如 scan/test/mbist/gpio mode 下才成立的 exclusive group。

03 不放：

- `create_clock` / `create_generated_clock`，这些放 `01_soc_clocks.sdc`。
- `set_clock_uncertainty` / `set_clock_latency` / `set_clock_transition` / `set_propagated_clock`，这些放 02。
- IO delay / driving / load / input transition，这些放 04。
- `set_false_path` / `set_multicycle_path` / `set_max_delay` / `set_min_delay`。
- harden-to-harden 特定 path exception，这些放 20。

## 3. 与 01 的关系

01 能提供 clock genealogy，例如：

- clock name。
- `clock_kind`：primary / generated / virtual。
- direct source / root source。
- generated clock 的 source/master 关系。
- harden output clock 与下游 harden input clock 的连接证据。

这些信息主要有两个用途：

- 生成 clock group candidate，辅助人工 review。
- 对已批准的 clock group 做 domain closure 展开和完整性检查，避免只把 master clock 放进 group、漏掉 generated/forwarded 子时钟。

01 信息不能直接决定两个 domain 是否 async/exclusive，但可以判断一个已确认 domain 内还包含哪些派生 clock。

重要原则：

- 同 root source 不必然同步。
- 不同 root source 不必然异步。
- generated clock 不必然需要切异步；很多 PLL/divider generated clock 仍应做同步 timing。
- clock mux 输入是否 exclusive，必须结合 mux select、mode、case analysis 和硬件结构确认。
- test/scan/mbist/bypass clock 的关系通常 scenario-dependent，不能仅凭名字放进 common。
- `set_clock_groups` 的 group 成员应按 clock domain closure 检查：如果某个 master/root/forwarded clock 被放入 group，它在 01 genealogy 中可追溯的 generated/forwarded descendants 也应进入同一 group，或有显式排除说明。
- 不应默认依赖工具自动把 master clock 的 group 关系继承给 generated clock；这类行为存在工具/版本差异，03 输出应显式覆盖有效成员。

因此，03 脚本后续可以从 01 自动生成候选关系，但最终输出必须来自人工确认的表单行。

### 3.1 Domain Closure 展开

03 表单中的 `group_N_clocks` 可以理解为人工确认的 domain seed/member clock。脚本生成 SDC 前，应基于 01 `clock_inventory.csv` 计算每个 group 的 effective members：

```text
effective_group = explicit_group_clocks
                + descendants(explicit_group_clocks)
                - explicitly_excluded_descendants
```

descendants 至少包括：

- 由该 clock 作为 source/master 派生出来的 `create_generated_clock`。
- `create_generated_clock -combinational` 形成的 forwarded clock。
- 经 harden output -> harden input -> harden output 转发后仍可由 01 genealogy 追溯到该 clock/domain 的 forwarded descendants。

注意：

- 不建议用“同 root_source 的所有 clock”无条件合并为一个 domain；同一个 root 下也可能存在需要单独分析的 generated clock。更安全的做法是从人工写入 group 的 clock 出发向下展开 descendants，并要求例外显式记录。
- 如果某个 descendant 不应进入同一 group，必须在表单中明确排除并写明 `basis` / `note`，不能静默漏掉。
- 对 `logically_exclusive` 组，descendant 展开必须特别 review。mux 两条输入腿可能在 mux 输出处重新汇合成同一个下游 clock；01 genealogy 可能因为 harden SDC 的 `-source` 只能把该 mux output clock 归到其中一条腿。脚本不能把这类汇合点 clock 静默塞进某一条 exclusive group，必须在 report 中突出显示，要求人工确认归属或显式排除。
- 脚本应在 report 中列出每条 rule 自动加入的 descendants，便于 review。

## 4. Common 与 Scenario

03 采用 common + scenario 叠加模型，不采用 02 的 resolved-single-file 模型。

输出建议：

```text
common/03_soc_clock_groups.sdc
scenarios/<scenario>_clock_groups.sdc
```

归属规则：

- `scenario = common`：只放所有 mode 都成立的 clock relationship。
- `scenario != common`：只放该 scenario 下才成立的额外 clock relationship。
- scenario 文件可以追加 common 中没有的 group，但不应与 common group 语义冲突。
- 如果某条 common group 在某个 scenario 下不成立，说明它不应该在 common，应下沉到对应 scenario。

## 5. Relation Type 语义

### 5.1 `asynchronous`

用于两个或多个 clock domain 之间没有固定相位/频率关系，普通同步 STA 不应分析跨域 setup/hold。

使用条件：

- 有架构依据说明这些 domain 异步。
- CDC/RDC signoff 有对应同步器、握手或协议检查。
- 不是为了消除 timing violation 临时添加。
- 如果 A/B/C 三个或更多 domain 是两两异步，应在同一条 `set_clock_groups -asynchronous` rule 中列出多个 `-group`。不要只拆成 `(A,B)`、`(A,C)` 两条 rule，否则 B/C 仍保持默认 synchronous。

多域建模示例：

```tcl
# Correct: A/B/C are pairwise asynchronous.
set_clock_groups -asynchronous \
  -group [get_clocks {clk_a}] \
  -group [get_clocks {clk_b}] \
  -group [get_clocks {clk_c}]

# Risky if A/B/C are intended pairwise async:
# This leaves clk_b <-> clk_c uncovered and still default synchronous.
set_clock_groups -asynchronous \
  -group [get_clocks {clk_a}] \
  -group [get_clocks {clk_b}]
set_clock_groups -asynchronous \
  -group [get_clocks {clk_a}] \
  -group [get_clocks {clk_c}]
```

风险：

- `set_clock_groups -asynchronous` 很强，会切断 group 间所有 timing path。
- 不能替代 CDC signoff。
- 不能滥用于某几个 violating path；局部 path exception 应放 20 或 scenario exception。

### 5.2 `logically_exclusive`

用于同一个 STA view 中多个 clock 逻辑上互斥、但又没有通过 `set_case_analysis` 预先裁掉某一路的情况。

典型例子是 all-mode / merged STA view 中保留 clock mux 的多条输入腿，并用 `set_clock_groups -logically_exclusive` 告诉工具这些 clock 不会同时活动。

使用条件：

- 有明确的 mux/select/mode 证据。
- 对于 **merged view**，即不通过 `set_case_analysis` 预先选定 mux 单腿的合并视图，可以用 `logically_exclusive` 告诉工具这些 clock 不会同时活动。
- 对于 **per-scenario view**，如果 scenario pre-setup 已经用 `set_case_analysis` 选定 mux 单腿，未选中的 clock leg 通常不会传播，此时不应再对同一个 mux/clock pair 追加 `logically_exclusive`。
- 如果 mux select 是 mode-specific，且该 scenario 已经通过 `set_case_analysis` 固定单腿，该 exclusive 关系不应进入该 scenario 的 03。

方法学选择：

- merged view：保留多条 mux clock leg，不打单腿 `set_case_analysis`，用 `logically_exclusive` 表达互斥。
- per-scenario view：先在 `scenarios/<scenario>_pre.sdc` 用 `set_case_analysis` 选定单腿，再让 clock propagation/clock creation 只保留该 scenario 生效的 clock；不再对同一个 mux 额外打 exclusive。
- 对同一个 mux，项目应先选择 `per_scenario_case` 或 `merged_exclusive` 方法学，再决定 03 是否生成 `logically_exclusive`。这不是两条约束的叠加问题，而是同一硬件关系的两种 STA 建模方式。

硬规则：

- 同一个 mux/clock pair 不要同时用 `set_case_analysis` 和 `logically_exclusive` 表达同一层互斥语义。
- 如果 `set_case_analysis` 已经让某条 clock leg 在该 scenario 中不传播，相关 exclusive 约束应视为冗余，不能作为掩盖约束方法学问题的手段。
- scan/mbist/test clock mux 必须先确认采用 per-scenario 单腿 case 还是 all-mode merged exclusive，再决定 03 是否生成对应 `logically_exclusive`。
- per-scenario signoff run 中，如果 pre-setup 已经 case-select 了 scan/func/mbist mux，不应再用 scenario 03 对同一 mux leg 生成 `logically_exclusive`。

### 5.3 `physically_exclusive`

用于物理上不可能同时存在的 clock，例如不同 package/config/strap/physical source 互斥。

使用条件：

- 有物理配置、strap、power domain、package option 或 mode 依据。
- 若只在特定 mode/config 成立，应下沉到 scenario 或后续 config-specific 机制。

## 6. 建议表单

建议第一版使用一个 workbook：

```text
03_soc_clock_groups.xlsx
```

建议包含两个 sheet：

```text
clock_group_rules
clock_group_candidates
```

第一版脚本只生成 `clock_group_rules` 中 `apply = yes` 的行；`clock_group_candidates` 只作为 01 自动分析后的人工 review 辅助。

### 6.1 Sheet: `clock_group_rules`

一行描述一条 `set_clock_groups` 约束。

建议字段：

```text
scenario
group_id
relation_type
group_1_clocks
group_2_clocks
...
group_N_clocks
exclude_descendant_clocks
analysis_style
apply
review_status
owner
basis
cdc_required
note
```

字段含义：

```text
scenario          common / func / scan / mbist / gpio_in / gpio_out
group_id          规则 ID，建议稳定且可 review，例如 CG_ASYNC_CPU_AON_001
relation_type     asynchronous / logically_exclusive / physically_exclusive
group_N_clocks    该 group 中的 clock name 列表，空格或换行分隔
exclude_descendant_clocks  不随 domain closure 自动加入的 descendant clock；非空时必须在 basis/note 解释
analysis_style    normal / merged_exclusive / per_scenario_case；per_scenario_case 通常只作记录/检查，不生成 logically_exclusive
apply             yes/no
review_status     draft / reviewed / approved / rejected
owner             约束 owner 或确认人
basis             架构依据，例如 CDC spec、clock tree spec、mux select、DFT mode 说明
cdc_required      yes/no；asynchronous group 通常应有 CDC/RDC signoff 依据
note              人工备注
```

示例：

```text
scenario | group_id              | relation_type        | group_1_clocks        | group_2_clocks       | exclude_descendant_clocks | apply | review_status | basis
common   | CG_ASYNC_CPU_AON_001  | asynchronous         | cpu_clk               | aon_clk              |                          | yes   | approved      | CDC spec section 3.2
common   | CG_EXCL_PLL_MERGED_001| logically_exclusive  | pll_func_clk          | pll_bypass_clk       |                          | yes   | approved      | all-mode merged view, mux select not case-fixed
```

`group_N_clocks` 不建议固定上限。脚本应识别所有满足 `group_<number>_clocks` 命名的列；demo 表单可以先预留 8 或 16 组，但规则本身不限制为 4 组。

对应生成示例：

```tcl
set_clock_groups -asynchronous \
  -group [get_clocks {cpu_clk}] \
  -group [get_clocks {aon_clk}]

set_clock_groups -logically_exclusive \
  -group [get_clocks {pll_func_clk}] \
  -group [get_clocks {pll_bypass_clk}]
```

如果采用 per-scenario 单腿 case 方法学，则不应把同一 mux 写成 `logically_exclusive` 规则。例如：

```tcl
# scenarios/func_pre.sdc
set_case_analysis 1 [get_pins u_pll_clk_mux/func_sel]

# 此时不再为 pll_func_clk / pll_bypass_clk 生成 logically_exclusive。
```

如果表单中为了 review 记录这一类 mux 关系，建议 `analysis_style = per_scenario_case` 且 `apply = no`；真正生效的约束放在 `scenarios/<scenario>_pre.sdc` 的 `set_case_analysis`。

### 6.2 Sheet: `clock_group_candidates`

候选 sheet 只用于辅助 review，不直接生成 SDC。

建议字段：

```text
candidate_id
candidate_type
clock_a
clock_b
tree_root_a
tree_root_b
root_source_a
root_source_b
evidence
suggested_relation
decision
target_group_id
note
```

候选来源可以包括：

- 03 genealogy `tree_root` 不同的 clock pair；01 `root_source` 仅作为参考字段保留。
- 01 中明确经过 mux/bypass/test source 的 clock。
- integration 表中跨 harden 的 clock domain 边界。
- 用户手工导入的 clock relationship review list。

注意：candidate 不能自动生成 `set_clock_groups`，必须转成 `clock_group_rules` 且 `review_status = approved` 后才可生成。

## 7. 脚本机制建议

第一版脚本：

```bash
python3 03_extract_soc_clock_groups.py -scenario common
python3 03_extract_soc_clock_groups.py -scenario func
```

选项：

```text
-scenario / --scenario        必填；common / func / scan / mbist / gpio_in / gpio_out
-input / --input              01 clock inventory CSV；默认 ../01_soc_clocks/clock_inventory.csv
--report                      check report 路径；默认 clock_group_check_report_<scenario>.txt
--max-candidate-pairs         首次创建 workbook 时写入 candidate sheet 的最大 cross-tree pair 数量；默认 500
```

默认输入：

```text
../01_soc_clocks/clock_inventory.csv
03_soc_clock_groups.xlsx
```

输出：

```text
scenario = common:
  common/03_soc_clock_groups.sdc

scenario != common:
  scenarios/<scenario>_clock_groups.sdc

reports:
  clock_group_check_report_<scenario>.txt
  clock_group_coverage_report_<scenario>.xlsx
```

生成规则：

- 只读取 `clock_group_rules`。
- 只生成 `scenario = 当前 -scenario` 的行。
- 只生成 `apply = yes` 且 `review_status = approved` 的行。
- `group_1_clocks`、`group_2_clocks` 至少两个 group 非空。
- 自动识别所有 `group_<number>_clocks` 列，不把有效 group 数量限制在 4 组。
- 每个 group 内至少一个 clock。
- 每个 clock 必须存在于 01 `clock_inventory.csv` 的有效 clock list。
- 对每个 group 做 domain closure 展开，自动加入 01 中可追溯的 generated/forwarded descendants。
- 输出 SDC 使用展开后的 effective group，而不是只使用表单中手写的 explicit group。
- report 中列出每条 rule 的 explicit group、auto-added descendants、excluded descendants 和最终 effective group。
- 同一个 `group_id` 不允许重复。

### 7.1 Assembled View 与 Pair Relation Map

03 的检查不能只看单条 rule，还必须检查某个 scenario 最终 source 后的 assembled view。

assembled view 定义：

```text
scenario = common:
  active_rules = common approved rules

scenario != common:
  active_rules = common approved rules + current scenario approved rules
```

脚本应在 domain closure 展开后，为 assembled view 建立 clock-pair relation map：

```text
pair(clock_a, clock_b) -> relation_type, group_id, scenario
```

建图规则：

- 对每条 `set_clock_groups` rule，只有不同 `-group` 之间的 clock pair 会得到该 rule 的 `relation_type`。
- 同一个 `-group` 内部的 clock pair 不会被该 rule 切断，但它们代表同一侧 domain 成员；如果它们在另一条 active rule 中被分到不同 group，应作为一致性风险检查。
- pair key 使用无序 clock pair，例如 `{clk_a, clk_b}`，避免 A/B 顺序造成重复。

### 7.2 Coverage Report

第一版脚本应生成 `clock_group_coverage_report_<scenario>.xlsx`，用于 review 而不是直接生成 SDC。

建议 sheet：

```text
clock_participation
pair_relation_map
uncovered_cross_root_pairs
root_pair_summary
```

建议内容：

- `clock_participation`：每个 01 有效 clock 的 `clock_name`、`clock_kind`、03 genealogy `tree_root`、01 `root_source`、参与的 `group_id`、所在 effective group、relation type。
- `pair_relation_map`：assembled view 中每个被 `set_clock_groups` 覆盖的 clock pair、relation type、来源 rule。
- `uncovered_cross_root_pairs`：03 genealogy `tree_root` 不同、但未被任何 active clock group 覆盖的 clock pair；这些 pair 在 STA 中仍按默认 synchronous 分析。01 `root_source` 仅作为诊断参考列。
- `root_pair_summary`：按 `tree_root_a/tree_root_b` 聚合 uncovered pair 数量和样例，避免大 SoC 中 pair 清单过长难以 review。

注意：

- `uncovered_cross_root_pairs` 只是 review 抓手，不表示这些 pair 一定应该 async/exclusive。
- 脚本不能因为 01 `root_source` 字符串不同就自动生成 asynchronous group；报告使用 03 基于 parent map 计算的 genealogy `tree_root` 判断独立时钟树，只报告“当前仍默认同步”的跨 tree pair，等待架构/CDC owner 决策。
- 已知限制：coverage report 不建模 `set_case_analysis`；被 scenario case 掉的时钟参与的 pair 可能仍显示为 uncovered，实际在该 scenario 中并不分析。后续可让 03 读取 scenario pre-setup 的 case_analysis 列表再过滤。

## 8. 检查项

第一版脚本至少做 rule-local、assembled-view 和 coverage 三类检查。

### 8.1 Rule-local 检查

- `scenario` 合法。
- `relation_type` 合法。
- `analysis_style` 合法。
- `apply` 合法。
- `review_status` 合法。
- `apply = yes` 时 `review_status` 必须为 `approved`。
- `group_id` 非空且唯一。
- 至少两个 non-empty group。
- 所有 clock name 存在于 01 clock inventory。
- 同一条 rule 中同一个 clock 不应同时出现在多个 group。
- 同一条 rule 的 effective group 之间不应出现同一个 clock。
- 若 explicit group 中的 clock 在 01 中存在 generated/forwarded descendants，则这些 descendants 必须进入同一 effective group，或出现在 `exclude_descendant_clocks` 并有明确 `basis` / `note`；否则至少 strong warning，signoff 模式建议 error。
- `exclude_descendant_clocks` 中的 clock 必须确实是某个 explicit group clock 的 descendant，否则 warning。
- `relation_type = logically_exclusive` 时，auto-added descendants 必须在 report 中单独标记为需要 review；若 suspected mux merge / shared downstream clock 无法自动判定归属，应 warning，并要求人工放入正确 group 或加入 `exclude_descendant_clocks`。
- common rule 的 `basis` 不能为空。
- asynchronous rule 建议 `cdc_required = yes`，否则 warning。
- relation_type 与 basis 不匹配时 warning，例如 logically_exclusive 但 basis 未提 mux/select/mode。
- `relation_type = logically_exclusive` 且 `apply = yes` 时必须显式填写 `analysis_style`，不能依赖空值默认为 normal。
- `relation_type = logically_exclusive` 且 `analysis_style = per_scenario_case` 且 `apply = yes` 时应 error，因为该方法学应依赖 `set_case_analysis` 单腿传播，不应再生成 exclusive。
- `relation_type = logically_exclusive` 且 `analysis_style = merged_exclusive` 时，basis 必须说明该 view 未对同一 mux select 打单腿 `set_case_analysis`。

### 8.2 Assembled-view 一致性检查

对 `common + 当前 scenario` 的 active rules，至少检查：

- 同一个 clock pair 在 assembled view 中不应同时出现多个不同 `relation_type`；例如 common 说 A/B asynchronous，scenario 又说 A/B logically_exclusive，应 error。
- scenario rule 不应与 common rule 对同一 clock pair 表达不同语义；若 scenario 需要不同关系，说明 common rule 归属错误，应下沉或拆分。
- 同一个 clock pair 被多条 rule 重复声明相同 `relation_type` 时，建议 warning 并在 report 中列出来源 rule，方便去重。
- 如果两个 clock 在某条 active rule 的同一个 effective group 内，但又在另一条 active rule 中被分到不同 group 并赋予 async/exclusive/physical exclusive 关系，应 warning 或 error。
- 对同一种 `relation_type`，若 assembled view 中存在 A/B 和 A/C 关系、但 B/C 未覆盖，应 warning 提醒 reviewer 确认是否需要 B/C 也同属该关系；若 A/B/C 本意是两两异步或两两互斥，应合并到同一条多 group rule 或补齐缺失 pair。
- scenario 03 只能追加该 scenario 专属关系，不能靠 source 顺序覆盖 common 03。

### 8.3 Coverage 检查

基于 01 的有效 clock list 和 assembled view，至少输出：

- 每个 clock 的 group 参与情况；没有参与任何 clock group 的 clock 应在 `clock_participation` 中标出。
- 每个 genealogy `tree_root` pair 的覆盖情况：covered pair 数量、uncovered pair 数量、relation type 分布。
- genealogy `tree_root` 不同且未被任何 active clock group 覆盖的 clock pair 清单；这些 pair 仍是默认 synchronous。
- 对 coverage report 不直接报错；是否要求某些 cross-tree pair 必须被标注，由项目 CDC/STA review 决定。

## 9. 与 CDC / SpyGlass 的边界

03 对 SpyGlass CDC 有复用价值，但不是 CDC signoff 的完整输入。

- 01 clock 定义和 03 async group 可以辅助 CDC clock setup。
- `set_clock_groups -asynchronous` 说明 STA 不做同步 timing，不代表 CDC 已经安全。
- CDC/RDC 需要额外的 synchronizer、reset、protocol、waiver 信息，不能只靠 SDC 表达。

## 10. 第一版暂不处理

第一版暂不自动推断并生成 clock group：

- 不根据 clock 名字自动判断 test/scan/mbist。
- 不根据 01 `root_source` 或 03 genealogy `tree_root` 不同自动生成 asynchronous。
- 不根据 generated/master 关系自动生成 synchronous 或 exclusive。
- 不做 path-level exception 替代。

这些信息只能进入 candidate/report，等待人工 review。
