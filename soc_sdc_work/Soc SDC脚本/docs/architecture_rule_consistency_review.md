# SoC SDC Architecture / Stage Rule Consistency Review

状态：待逐项讨论确认

原则：本文件只记录当前架构、阶段规则和实现之间的疑点与可选决策，不代表已经决定修改任何规则或脚本。后续按编号逐项确认，确认后的结论再回写到正式文档和实现。

## 总体判断

目前 `01/02/03/04` 的主要职责、文件命名、common/scenario/view-specific 装配关系总体已经对齐。上一轮复核发现的优先问题主要集中在：

1. `20` 对“常规 STA 已覆盖、无需额外 budget”的终结语义还没有完全闭环。
2. cleaned harden SDC 中保留的内部 clock 与“所有 clock object 归 `01`”之间存在边界冲突。
3. `.lib/.db` timing model、blackbox 和可见 netlist 的 `20` 适用范围需要重新分层。

建议先讨论 `S1-1` 至 `S1-3`，再处理场景交付、fanout 消账和命名/文档问题。

## S1-1: `20` 的 normal-STA-covered 终结语义不闭环

### 现状

- `00` 规则允许普通 interface channel 在已经由可见 netlist/timing model 常规 STA 覆盖、且不需要额外 `20` budget 时从 pending 中消账；同一节也允许 `not_applicable` 作为有依据的终结结论。
- `20` 规则又规定，只有某条 `interface_budget` 实际生成 `set_max_delay` 或 `set_min_delay` 后，才能删除对应 pending port。
- `20` 的 `budget_model`/状态枚举中没有清晰、统一的 `normal_sta_covered` 或 `no_extra_budget_required` 终态字段。

### 风险

在“harden 间互联很短、两端 timing arc 对 SoC STA 可见、正常 reg-to-reg STA 已覆盖、因此不额外生成 20 约束”的方法下，port 既不能由 `20` 删除，也没有统一的机器可读终结状态。pending 可能永远不为空，或者只能依赖与规则字段不一致的人工处理。

### 待确认选项

- 选项 A：在 `20` 中增加明确的 `normal_sta_covered` / `no_extra_budget_required` disposition，并允许它按 channel/bit 消账。
- 选项 B：统一归入 `00_disposition`，由 `00` 记录“常规 STA 已覆盖”及证据，`20` 只处理实际生成的 budget。
- 选项 C：规定所有 harden-to-harden channel 都必须经过 `20` 表单，即使最终只填 `not_applicable`，以保持 `20` ownership 单一。

### 当前结论

待确认。没有确认前，不应把 pending 为空作为“所有普通 STA channel 已完成”的可靠证明。

## S1-2: 完整 `.lib/.db` timing model 与 blackbox 被混在一起

### 现状

`20` 规则把 `.lib/.db timing model` 与 `blackbox/abstract model` 一起列为需要 interface budget 的主要场景；但架构文档同时规定：如果边界两端寄存器、clock path 和 timing arc 对 SoC STA 可见，普通 synchronous reg-to-reg path 应优先由常规 STA 分析，`20` 不应额外叠加 `set_max_delay -datapath_only`。

### 风险

完整的 Liberty timing model 通常包含足够的 input/output timing arc，可让 SoC STA 分析 harden 边界的正常时序。若不区分完整 model、抽象 model 和纯 blackbox，可能把本来由正常 STA 覆盖的 channel 错误地要求生成额外 budget，造成重复约束或过约束。

### 待确认选项

- 选项 A：把 `visible_netlist`、`complete_lib/db` 归为 normal STA covered；只有 pure/incomplete blackbox、abstract model 或明确架构 budget 才进入 `20`。
- 选项 B：无论 model 完整性如何，只要接口是 harden boundary，就要求显式 `20` channel budget。
- 选项 C：由 harden owner 在表单中增加 `budget_required` 和证据字段，逐 channel 决定，而不是仅凭 `timing_model` 自动推断。

### 当前结论

待确认。建议至少把“完整 timing model”和“不可进行边界时序分析的 blackbox/abstract”拆成不同语义，避免名称相同但约束责任不同。

## S1-3: cleaned harden 内部 clock 与 `01` clock ownership/order 冲突

### 现状

- 架构和 `01` 规则把 SoC-visible 的 `create_clock` / `create_generated_clock` 统一归属 `01`，并要求 01 建立所有供后续阶段引用的 clock object。
- architecture 的 cleaned harden SDC 部分又允许保留 harden 内部 generated/local/virtual clock，条件是不与 01 重复，并在 cleaned 文件中改名。
- cleaned harden SDC 在装配顺序中位于 01/02/03 之后，因此这些保留 clock 无法参与 01 inventory、02 budget 或 03 relation 的正常前置处理。

### 风险

同一个“clock definition”同时存在两套 ownership：如果它实际上被 SoC-visible 约束引用，放在 cleaned SDC 会绕过 01 的命名、period、source、genealogy 和 clock-group 检查；如果它只是 harden 内部私有 clock，又必须明确禁止 SoC-level 约束引用它。

### 待确认选项

- 选项 A：所有会被 SoC 级约束引用的 clock 一律提升到 01；cleaned SDC 不保留任何被 SoC 级 timing/group/exception 引用的 clock definition。
- 选项 B：允许 cleaned SDC 保留 private clock，但定义 private clock 的命名空间、不可被 02/03/20/30 引用的规则，以及必要的本地检查。
- 选项 C：cleaned SDC 只保留硬核内部 timing 约束，所有 clock definition 一律由 01 生成。

### 当前结论

待确认。这里需要先明确“内部 clock”是否可能成为 SoC-visible object，再决定文件归属。

## M1-1: scenario pre 与 cleaned transfer 缺少正式 owner/consumer 契约

### 现状

- 架构装配从 `scenarios/<scenario>_pre.sdc` 开始，用于 `set_case_analysis`、clock mux、test/scan/bist 等模式选择。
- `03/04/30` 以及 `00` 的某些 coverage/disposition 语义依赖这些 scenario 前置条件。
- cleaned harden SDC 会把 boundary case、delay 或 exception 交给 scenario/10/20/30 review，但现有阶段规则主要描述“直接读取 harden integration SDC”和各自表单，没有统一定义 transfer report 的输入格式、owner、消费阶段、冲突检查和 coverage。

### 风险

同一条约束可能已经在 cleaned transfer 中被标记为“转交”，但下游阶段没有可机器消费的记录；或者 scenario pre 已改变 active clock/path 集合，后续 stage 仍按未 case 的全集判断 coverage。

### 待确认选项

- 为 cleaned transfer 建立结构化中间文件和明确 consumer。
- 第一版只把 transfer 当人工 review evidence，禁止脚本据此自动消账或自动生成。
- 先限定 scenario pre 只影响装配和人工 review，后续再接入 03/04/30 的机器检查。

### 当前结论

待确认。

## M1-2: port-level pending 无法证明 fanout edge/path 全部闭环

### 现状

`00` 的 pending 是 port/node 视图，`connection_inventory.csv` 是 edge 视图。对于：

```text
u_a/out -> u_b/in
        -> u_c/in
```

一个 source port 可能被多个 channel 共享。`20` 规则要求每个 sink channel 独立 review，但 port 消账若只按“某一条 channel 已完成”处理，就可能提前删除共享 source。

### 风险

pending 为空只能说明 port key 被某个 stage 删除，不能证明该 port 相关的所有 connection edge、fanout sink 和 view-specific channel 都已完成。node closure 与 edge closure 可能出现不一致。

### 待确认选项

- 规定 port 只有在所有相关 edge/channel 都达到 terminal 状态后才能删除。
- 以 `connection_inventory` 的 edge coverage 作为主完成条件，pending 只作为人工入口和摘要。
- 保留当前 port 删除语义，但增加 fanout 未闭环检查，禁止 source 提前消账。

### 当前结论

待确认。建议把“端口消账”和“连接边消账”分别定义为两个可检查的完成条件。

## M2-1: 10 的 feedthrough 命名是规范，但 malformed name 目前只 warning

### 现状

10 要求 `fti_/fto_` 后保留 `<src>2<dst>` 的 end-to-end source/destination harden 名称，并用 00 connection edge 验证 feedthrough segment。当前规则对 base 缺少明显 `<src>2<dst>` 结构主要定义为 warning。

### 风险

如果一个格式错误的端口仍能被 fti/fto 配对，并被判为 `matched`，它可能生成 feedthrough inventory/SDC 并消账，导致命名不合规的路径绕过人工确认。仅凭名字也无法证明 `<src>`/`<dst>` 与真实连接一致。

### 待确认选项

- 名字无法解析为 `<src>2<dst>` 时直接 error，禁止生成。
- 保留 warning，但强制 `validation_status=needs_review`，禁止 pending 消账和 SDC emit。
- 允许项目登记例外命名，但必须有结构化 source/destination 字段和 reviewer 依据。

### 当前结论

待确认。无论采用哪项，名字不应在未验证时直接成为消账依据。

## N1-1: scenario canonical name 不统一

### 现状

架构场景文件名使用 `dft_scan`，而 02/03/04 的场景字段和输出示例使用 `scan`；20 的示例又出现 `dft_scan_harden_x_if.sdc`。

### 风险

脚本若按 normalize 后的字符串匹配，可能暂时不报错，但装配文件名、表单值和 coverage key 会出现多个等价名字；在大小写或下划线严格的 flow 中会导致文件找不到或场景重复。

### 待确认选项

- 选择一个 canonical enum，例如统一为 `scan`，所有文件名和表单均使用该值。
- 保留 `dft_scan` 作为 canonical，`scan` 只作为输入 alias，并在脚本回写/输出时统一 canonical。
- 建立共享 scenario vocabulary 文件，由所有阶段引用。

### 当前结论

待确认。

## N1-2: 文档与实现的 contract/hygiene 问题

### 现状

- `00` 说明 `removed_log` 不是 downstream input，但各 stage 为幂等重跑会读取 `previous_removed`；这里实际存在“追溯文件也是流程输入”的例外。
- architecture 已移动到 `docs/` 后，文档内若仍以仓库根或旧目录为基准引用 stage rule，部分相对链接会失效。
- architecture 的目录清单和示例中仍有若干旧 demo/form 文件名，未完全反映当前新目录结构。

### 风险

新用户按文档运行时可能找不到规则文件；维护者也可能误以为 removed log 可以删除或不必纳入输入快照，从而破坏幂等检查。

### 待确认选项

- 明确 `removed_log` 是“非业务语义输入、但为幂等校验读取的流程证据”，并纳入运行快照/版本管理要求。
- 对 docs 中的内部链接和目录树做一次统一校正。
- 将过时 demo/form 名称标记为 archive，避免被当作当前入口。

### 当前结论

待确认。

## 建议讨论顺序

1. `S1-1`：先决定“常规 STA 覆盖但不生成 20 约束”如何消账。
2. `S1-2`：再决定完整 `.lib/.db` 与 blackbox/abstract 的责任边界。
3. `S1-3`：最后确定 cleaned harden 内部 clock 的 ownership。
4. `M1-1` / `M1-2`：补齐 scenario transfer 与 fanout/edge closure。
5. `M2-1`、`N1-1`、`N1-2`：处理命名和文档一致性。
