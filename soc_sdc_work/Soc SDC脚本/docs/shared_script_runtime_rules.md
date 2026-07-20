# SoC SDC 00-30 Shared Runtime Rules

## 1. 适用范围和优先级

本文定义 00、01、02、03、04、10、20、30 的共享运行、互联解析和 port 销账契约。各 stage 规则继续定义各自的 SDC 主体功能；当 stage 文档中的旧路径、scenario、`connection_inventory.csv`、pending 或 removed log 描述与本文冲突时，以本文为准。

本文描述目标规则契约。现有 Python 和 regression 在完成下一轮迁移前可能仍实现旧 runtime；stage 使用说明必须显式区分“目标规则”和“当前实现”，不能把本文路径当成已经全部可运行。

本版目标是生成一个 SoC top 综合/STA 使用的完整 SDC 组合，stage 顺序保持：

```text
00
 -> 01
 -> all required 02 views
 -> 03
 -> all required 04 views
 -> 10
 -> all required 20 views
 -> all required 30 views
 -> 30 final accounting gate
```

## 2. 单 run 只承载一个场景

- 00-30 的一个 run root 只表示一个外部选定的场景。
- stage CLI、workbook、CSV、meta、report 和 SDC 不再包含或选择 `scenario`。
- 不再定义 common/scenario overlay，也不在同一 run root 保存多个场景。
- 需要 func、scan、mbist、gpio 等不同场景时，操作者必须为每个场景准备独立 run root 和一份干净的 `inputs/port_*.xlsx`，再从 00 完整重跑到 30。
- 已被某个场景写入销账结果的 port workbook 不能直接作为另一个场景的输入模板。

`stage`、`corner` 仍是 02、04、20、30 的 timing view 维度，不等价于 scenario，继续由对应 stage 的规则管理。

view 文件命名统一为：`stage=all, corner=all` 使用不带后缀的基础文件名；其它 view 使用 `_<stage>_<corner>` 后缀。一次 SDC 装配只 source 当前选中的 view 文件。

场景不参与 stage 选择，但必须保留交付追溯。`inputs/run_context.csv` 使用一行记录：

```text
run_id,mode_label,design_revision,note
```

- `run_id` 必填，在项目内唯一。
- `mode_label` 必填，例如 `func`、`scan`、`mbist`，只用于 provenance，任何 stage 不得据此选择或过滤约束。
- 所有 SDC、CSV、meta、workbook metadata 和 report 都必须复制 `run_id/mode_label/design_revision`。

## 3. Target run-root 布局

```text
<run_root>/
  inputs/
    run_context.csv
    required_views.csv
    info_all.xlsx
    port_*.xlsx
    *.sdc
    virtual_clocks.csv                 # optional
    stage-specific manual inputs       # optional

  00_middle/
    harden_sdc_manifest.csv
    input_snapshot.meta
    port_accounting_delta.csv
    port_accounting_delta.meta
    stage_completion.meta
  00_result/reports/
    environment_report.txt

  01_middle/clock_inventory.csv
  01_middle/clock_inventory.meta
  01_middle/port_accounting_delta.csv
  01_middle/port_accounting_delta.meta
  01_middle/stage_completion.meta
  01_result/01_soc_clocks.sdc

  02_middle/...
  02_middle/completion/<stage>_<corner>.meta
  02_result/...

  03_middle/relation_map.csv
  03_middle/relation_map.meta
  03_middle/stage_completion.meta
  03_result/03_soc_clock_groups.sdc

  04_middle/...
  04_middle/pad_inventory.csv
  04_middle/pad_inventory.meta
  04_middle/port_accounting_delta.csv
  04_middle/port_accounting_delta.meta
  04_middle/stage_completion.meta
  04_middle/completion/<stage>_<corner>.meta
  04_result/04_soc_io_pads[_<stage>_<corner>].sdc

  10_middle/feedthrough_edge_inventory.csv
  10_middle/feedthrough_edge_inventory.meta
  10_middle/port_accounting_delta.csv
  10_middle/port_accounting_delta.meta
  10_middle/stage_completion.meta
  10_result/10_feedthrough.sdc

  20_middle/channel_inventory.csv
  20_middle/channel_inventory.meta
  20_middle/port_accounting_delta.csv
  20_middle/port_accounting_delta.meta
  20_middle/stage_completion.meta
  20_middle/completion/<stage>_<corner>.meta
  20_result/20_harden_x_if[_<stage>_<corner>].sdc

  30_middle/exception_candidates.csv
  30_middle/port_accounting_delta.csv
  30_middle/port_accounting_delta.meta
  30_middle/stage_completion.meta
  30_middle/completion/<stage>_<corner>.meta
  30_result/30_harden_to_harden_exception[_<stage>_<corner>].sdc
  30_result/reports/port_accounting_final_report.txt
```

每个 stage 可以继续生成自己的 review workbook、debug bundle 和 coverage report，但不得重新建立 scenario 子目录。

`inputs/required_views.csv` 是 finalization 的机器真源，每行定义一个 required timing view：

```text
view_id,stage,corner,require_02,require_04,require_20,require_30,note
```

flag 使用 `yes/no`。00 必须校验 `view_id`、`stage/corner` 唯一且字段完整；01/03/10 是 run-wide stage，不按 view 重复。

## 4. 输入表单职责

### 4.1 `info_all.xlsx`

`info_all.xlsx` 是 harden instance、module、owner 和 SDC 交付映射的真源。至少应能解析：

```text
module_name
inst_name
owner
SDC file/status mapping fields
```

### 4.2 `port_*.xlsx`

每个 sheet 对应一个 harden instance。标准 12 列为：

```text
Input
Input Width
Input Used Width
From Whom
Output
Output Width
Output Used Width
To Top
Inout
Inout Width
Inout Connectivity
Inout Name
```

其中端口和互联真源为：

- input port：`Input`、`Input Width`，driver 来自 `From Whom`。
- output port：`Output`、`Output Width`；若连接 SoC top，top endpoint 来自 `To Top`。harden-to-harden fanout 通过扫描其它 sheet 的 `From Whom` 反向建立。
- inout port：`Inout`、`Inout Width`，互联来自 `Inout Connectivity`。

以下三列不再表示 width/name，而被本 flow 专门复用为销账状态列：

| 方向 | 销账状态列 |
|---|---|
| input | `Input Used Width` |
| output | `Output Used Width` |
| inout | `Inout Name` |

输入表单不得再把实际 inout connection 放在 `Inout Name`；必须使用 `Inout Connectivity`。

一个 run 内每个 inout bit 必须在 04 review 中解析为且仅解析为 `input` 或 `output`。本 flow 不支持同一 run 内同时双向计时；`bidirectional/unknown` 不得销账。只要当前 run 的单一有效方向达到 terminal，即认为该 inout bit 已覆盖。

## 5. 00 的职责

00 是环境初始化和输入检查 stage，不生成 SoC SDC，也不再生成：

```text
connection_inventory.csv
pending/*.ports
removed_log/*.removed
任何独立销账账本
```

00 只负责：

1. 检查 run-root 和 `inputs/` 布局。
2. 解析 `info_all.xlsx` 与所有 `port_*.xlsx` 的 sheet/列结构。
3. 检查 instance、module、sheet 名和 SDC 映射的一致性。
4. 检查三列销账状态是否为空或符合本文编码；fresh run 默认要求为空。
5. 对表单中显式声明的 NC、tie-off、open bit 直接写入 Used 状态，并输出 00 accounting delta。
6. 扫描当前 run 的 harden SDC，生成 `harden_sdc_manifest.csv`。
7. 记录输入文件 digest 和运行环境到 `input_snapshot.meta` / report。

00 不把表单互联复制成中间 CSV。01、04、10、20、30 必须在运行时直接读取同一批 `inputs/port_*.xlsx`。

结构性默认终态只接受显式 token：

```text
NC / N/C / NO_CONNECT / UNCONNECTED
OPEN
TIE0 / TIE1 / 合法 Verilog 常量 literal
```

空白 connectivity 不等价于 OPEN。00 对这些 exact bit 记录 `structural_nc`、`structural_open` 或 `structural_tie_off`，不生成 timing SDC；它们默认视为已约束。

## 6. Harden SDC 渐进交付

`harden_sdc_manifest.csv` 至少包含：

```text
inst_name
module_name
sdc_path
availability_status
note
```

`availability_status` 使用：

```text
available
missing
not_required
```

- 默认允许部分 harden SDC 为 `missing`，流程继续处理已到位 SDC 和不依赖缺失 SDC 的 approved 规则。
- `missing` 不能解释为“没有 timing/clock/exception”。依赖该 SDC 的 port bit 保持未销账。
- `not_required` 必须有明确项目依据。
- 如需强制完整交付，可提供显式 strict 选项；strict 只改变缺失 SDC 的退出门槛，不改变解析或销账语义。

## 7. 互联解析契约

### 7.1 Canonical endpoint

所有 stage 使用同一套 canonical 表达：

```text
<inst>:<direction>:<port>
<inst>:<direction>:<port>[<actual_hdl_index>]
top:<direction>:<port>
```

vector 必须按实际 HDL index 展开。`data[7:4]` 的合法 bit 是 7、6、5、4，不得转换为位置 3、2、1、0。

合法 bit 集合按以下顺序确定：

1. port 文本含显式 `[msb:lsb]`：使用该 range 的实际 index 集合，width 必须一致。
2. port 文本含显式 `[n]`：合法集合为 `{n}`，width 必须为 1。
3. port 文本无 selector 且 width = 1：scalar 合法集合为 `{0}`。
4. port 文本无 selector 且 width = N>1：按表单约定解释为 `[N-1:0]`；report 必须记录该 implicit range。

width 缺失、非正整数或与显式 range 不一致时不得销账。

### 7.2 Direct edge 构建

- input row 的 `From Whom` 是 harden input direct driver 的权威来源。
- `To Top` 只描述 harden output 到 SoC top port。
- `Inout Connectivity` 描述 inout 对端或 top pad。
- compact range 必须按 source/sink 声明方向逐 bit 配对；宽度不一致、非法 range、未知 instance/port 或一个 destination bit 多 driver 必须 error。
- fanout 通过扫描所有 destination row 得到；同一 source bit 可以驱动多个 destination bit，每条 direct edge 单独处理。
- NC/open/constant/tie-off 使用明确分类，不能伪造成普通 harden-to-harden timing edge。
- SoC 看不到 harden 内部 `fti -> fto`，任何 stage 都不得从命名规则拼出该内部 segment。

### 7.3 Stable ID

需要 machine inventory 的 stage 先构造 UTF-8 canonical JSON tuple，不含空白、不含 workbook 行号或 digest：

```text
[schema_version,src_instance,src_direction,src_port_base,src_bit_index,
 dst_instance,dst_direction,dst_port_base,dst_bit_index]
```

canonical normalization：schema version 使用字符串；direction 转小写枚举；instance/port/top object 去首尾空白但保持 HDL 大小写；bit index 使用十进制整数；字符串按 UTF-8 JSON array 序列化，禁止对象/map 和实现相关 pretty-print。

其它 tuple：

```text
pad tuple = [schema_version,top_port_base,top_bit_index,top_direction,
             harden_instance,harden_direction,harden_port_base,harden_bit_index]

structural tuple = [schema_version,instance,direction,port_base,bit_index,structural_reason]
```

然后计算完整 SHA-256：

```text
connection_id = CONN_<64-lowercase-hex>
feedthrough_edge_id = FTE_<same-connection-hash>
channel_id = CH_<same-connection-hash>
pad_id = PAD_<sha256(canonical-pad-tuple)>
```

完整 hash 不截断，避免 `data_bit0` 与 `data[0]` 等可读字符串编码碰撞。inventory 另存 human-readable exact endpoints、source workbook、sheet 和 row。ID 不再由 00 预生成，也不随 row reorder 或 Used 状态变化。

### 7.4 Digest 分层

所有 stage 统一使用三类 digest：

```text
structure_digest
accounting_state_digest
workbook_file_digest
```

- `structure_digest`：对 `run_context.csv`、`required_views.csv`、`info_all.xlsx` 和 port workbook 的结构/互联字段做 canonical semantic hash；明确排除 `Input Used Width`、`Output Used Width`、`Inout Name` 的销账值及所有样式。整个 run 必须保持不变。
- `accounting_state_digest`：对全部 workbook/sheet/row/direction/port 的 canonical used-bit 集合做 hash。`ALL USED` 和等价的完整 bit list 得到同一逻辑 digest；红绿样式不参与。
- `workbook_file_digest`：原始 xlsx bytes hash，仅用于诊断、并发写检测和事务恢复，不用于结构 stale 判断。

每个写表 stage 必须记录：

```text
structure_digest
accounting_digest_before
accounting_digest_after
workbook_file_digest_before[]
workbook_file_digest_after[]
```

下游只用 `structure_digest` 判断互联/表单是否 stale；用前一写表 stage 的 `accounting_digest_after == 当前 accounting_digest_before` 检查销账链连续性。不得因为合法 Used 列或样式变化重建 connection/channel ID。

## 8. 原地销账协议

### 8.1 中间状态编码

00、01、04、10、20、30 直接更新对应 row 的销账状态列。中间状态只记录已被终结的实际 HDL bit index，使用逗号分隔的升序集合：

```text
0
0,1,4
2,3,4,5
```

规则：

- scalar 的 canonical index 为 `0`。
- 空白表示尚无 bit 被销账。
- 重复写入同一 bit 是幂等操作，最终只保留一次。
- 写入前必须验证 bit 属于该 row 声明的合法 bit 集合。
- stage 只能 union 新的 terminal bit，不能删除其它 stage 已写入的 bit。
- 01-20 不写 `ALL USED` 或 `UNUSED`；这些终态只由 30 生成。
- 状态单元格按文本处理，禁止 Excel 把 `0,1` 转换成数字或日期。
- 30 finalization 后，01/04/10/20 若遇到 `ALL USED` 或 `USED/UNUSED` 必须阻断，提示该 workbook 已结束本轮 flow；不能把 final token 当普通中间 bit list 继续追加。

Used 状态表示“该 port bit 已有明确 SoC SDC owner/terminal disposition”，不是 per-stage/per-corner coverage matrix。`stage/corner` 的数值完整性仍由各 stage review workbook 和 coverage report 管理；同一 bit 不因多个 view 重复写入。只有对本 run 整体成立的 owner 决策才能销账。

### 8.2 哪些 stage 写表单

| Stage | 是否写销账列 | 终结范围 |
|---|---:|---|
| 00 | 是 | 显式 NC、tie-off、open structural bit |
| 01 | 是 | 已生成或确认的 SoC-visible clock port bit |
| 02 | 否 | clock timing 属性不拥有 harden data port |
| 03 | 否 | clock relationship 不拥有 harden data port |
| 04 | 是 | 已批准的 SoC top pad / IO port bit |
| 10 | 是 | approved terminal feedthrough-adjacent direct edge endpoint |
| 20 | 是 | approved terminal normal functional direct channel endpoint |
| 30 | 是 | approved exception-only endpoint，并执行最终统计 |

10/20 中的 `pending` 或 `route_to_30` 不销账。30 对已有合法早期 owner 的 endpoint 只生成 path-level exception，不重复修改 bit 集合。

### 8.3 Stage Accounting Delta

00、01、04、10、20、30 每次成功运行都必须输出本 stage 的：

```text
<stage>_middle/port_accounting_delta.csv
<stage>_middle/port_accounting_delta.meta
```

CSV 每行记录本 stage 新增销账的一个 port row/direction：

```text
schema_version
run_id
mode_label
stage_name
transaction_id
view_id
stage
corner
structure_digest
accounting_digest_before
accounting_digest_after
workbook
sheet
row
direction
port
legal_bits
added_bits
final_used_bits
owner_object_id
reason
evidence_status
```

- `added_bits` 只包含本次新加入的 exact bits；幂等重跑可以为空。
- `owner_object_id` 引用该 stage 的 clock/pad/edge/channel/exception ID；00 structural disposition 使用稳定 `STRUCT_<sha256>` ID。
- meta 记录 delta CSV digest、before/after digest、transaction ID 和 completion status。
- 同一 stage 多次运行时，delta CSV 是本 run 的累积 resolved view；既有 committed transaction row 不得删除或改写，新 transaction 按提交顺序追加。meta 记录有序 transaction ID/digest chain。
- delta 是各 stage 自己的 owner 证明，不是 00 生成的全局销账账本。
- 02、03 不生成 delta，但 report/completion meta 必须写 `Port accounting: not_applicable; added_bits=0`。

30 finalization 前必须按 00→01→04→10→20→30 顺序读取所有 delta/meta，验证 structure digest 一致、accounting digest 连续、owner object 存在，并确认 delta union 与当前 Used 状态完全一致。缺失、stale、断链或无法解释的预置 bit 必须阻断 finalization。

### 8.4 多 Workbook Transaction 和并发

- 修改 xlsx 时必须保留所有非销账单元格、sheet 顺序、公式、样式、列宽和已有批注。
- 00、01、04、10、20、30 不允许并发修改同一批 workbook，必须持有 `inputs/.port_accounting.lock`。
- 单文件 rename 不能代表多 workbook 原子事务。每次写表 stage 必须创建：

```text
<run_root>/.accounting_txn/<stage_name>_<transaction_id>/
  transaction.json
  original/<workbook copies>
  candidate/<workbook copies>
```

事务流程：

1. 在锁内检查没有未恢复事务，并核对 current file/structure/accounting digest。
2. 备份所有将修改的原 workbook；在 candidate 中完成全部值、样式和格式修改。
3. 对所有 candidate 做 schema、bit、style、digest 和 accounting delta 校验。
4. 原子写 `transaction.json`，状态为 `PREPARED`，列出每个 original/candidate digest。
5. 将状态改为 `APPLYING`，逐个原子替换目标 workbook；每完成一个就在 manifest 记录。
6. 全部替换成功后发布 accounting delta/meta 和 stage completion meta，再写 `COMMITTED` marker。
7. 只有 `COMMITTED` 后才清理 backup/candidate；transaction ID 保留在 delta meta。

启动恢复：

- 发现 `PREPARED/APPLYING` 且无 `COMMITTED`：从 original backup 恢复全部 workbook，验证原 digest，标记 `ROLLED_BACK` 后才能继续。
- 发现 `COMMITTED` 但临时目录未清理：验证 target/delta digest 后只做清理，不回滚。
- backup 缺失、digest 不匹配或恢复失败：阻断所有后续写表 stage，禁止猜测继续。

transaction 目录只服务 crash recovery，不是业务销账账本。每个 stage report 仍必须列出 workbook、sheet、row、direction、port、added_bits 和 final_used_bits。

### 8.5 Fresh run、resume 和重跑

- fresh run：00 要求三列销账状态为空。
- 同一 run 中 stage 失败后重跑：保留合法 bit 集合，当前 stage 以 union 方式幂等恢复。
- 30 自身重跑：允许读取 final token；`ALL USED` 展开为全部 legal bits，`USED/UNUSED` 必须验证两者互斥且并集等于 legal bits，然后幂等重写相同终态和样式。
- 不同 scenario：必须从未销账的干净 port workbook 新建 run root，不能清洗后原地复用旧 run 作为默认流程。
- 若项目需要 resume，00 只验证现有 token 合法、structure digest 一致且 accounting delta chain 可解释当前 Used 状态，不推断缺失的 stage owner。

### 8.6 Stage Completion Meta

每个 run-wide stage 和每个 required view 都必须发布 completion meta，至少包含：

```text
run_id
mode_label
stage_name
stage
corner
completion_status
error_count
sync_changed
structure_digest
accounting_digest_before
accounting_digest_after
upstream_artifact_digests
output_sdc_digest
accounting_delta_digest
```

`completion_status=complete` 只允许在 `error_count=0`、`sync_changed=no`、正式输出和 digest 均已发布后写入。candidate-only、diagnose-only、review-required 或 transaction rollback 不能标 complete。

04 和 20 还必须在所有 required view completion 完整后发布 run-wide `stage_completion.meta`，证明 pad/channel inventory 已稳定；即使没有 required timing view，也必须运行 classification/audit 并发布空或 reviewed machine inventory。10 依赖 04 run-wide completion，30 依赖 20 run-wide completion。30 只在 final accounting 成功后发布自己的 run-wide completion。

## 9. 30 最终统计和着色

30 必须按 `required_views.csv` 验证 00/01/03/04/10/20 run-wide completion，以及每个 required view 的 02/04/20/30 completion。所有 meta 必须 `complete`、run/structure digest 一致、upstream/output digest 可复核，才能执行 finalization。

当前 30 invocation 必须先完成自身 rule validation、SDC 生成和 accounting transaction 的全部 candidate 校验，再把当前 view 作为 in-memory complete 状态参与 final gate。任何 error、sync change、candidate-only、defer、缺失 view 或 stale meta 都禁止写 `ALL USED/UNUSED` 和最终颜色。

通过 final gate 并完成自身 approved exception 销账后，30 扫描全部 `port_*.xlsx` 的 input/output/inout row，计算：

30 默认尝试执行 finalization。若 required view 尚未全部完成，本次正式 SDC/completion 可以发布，但 final accounting 自动保持 deferred；显式 strict/finalize 选项下应返回 review-required/error。只允许最后一个满足完整 gate 的调用归一化/着色。

```text
legal_bits = 该 row 端口声明的实际 HDL bit 集合
used_bits  = 销账状态列中解析出的 bit 集合
unused_bits = legal_bits - used_bits
```

### 9.1 全部使用

若 `unused_bits` 为空，例如 6-bit signal 最终记录已覆盖 0、5、2、1、4、3，则把销账状态单元格归一化为：

```text
ALL USED
```

并设置：

```text
fill: #C6EFCE
font: #006100
```

### 9.2 未全部使用

若存在未覆盖 bit，则把销账状态单元格归一化为：

```text
USED:<sorted_used_bits>; UNUSED:<sorted_unused_bits>
```

例如：

```text
USED:0,2,3,5; UNUSED:1,4
USED:-; UNUSED:0,1,2,3
```

并设置：

```text
fill: #FFC7CE
font: #9C0006
```

只修改销账状态单元格，不覆盖端口名、width 或互联字段的原有样式。

### 9.3 最终报告

`port_accounting_final_report.txt` 至少包含：

- workbook/sheet/instance/direction/port 粒度的 legal、used、unused bits。
- 每个 instance 和全局的 total/used/unused bit 数。
- `ALL USED` row 数和 incomplete row 数。
- missing SDC 相关未覆盖 bit 的单独清单。
- final workbook digest。

存在 unused bit 时，30 的 timing SDC 可以保留，但 report 必须标记 `Accounting closure: incomplete`。项目可通过 strict closure 选项把 incomplete 提升为阻断错误。

## 10. Stage ownership 不变

- 01：SoC-visible clock creation/extraction。
- 02：clock timing 属性、uncertainty、latency、transition、derate。
- 03：clock relationship / clock groups 和 relation map。
- 04：SoC top IO/pad electrical 与 delay 环境。
- 10：SoC 可见、与 feedthrough boundary 相邻的 direct edge；不处理内部 `fti -> fto`。
- 20：其它普通 functional harden-to-harden direct channel timing/disposition。
- 30：有明确架构、协议、CDC/RDC 或 waiver 依据的 exception/override，并负责最终 port accounting closure。

## 11. 下游 machine artifacts

移除 00 connection inventory 不等于移除所有 stage machine artifacts：

- 01 继续输出 `clock_inventory.csv`。
- 03 继续输出 `relation_map.csv/.meta`。
- 04 必须输出 `pad_inventory.csv/.meta`，包含 `route_to_30` pad owner 状态。
- 10 继续输出 `feedthrough_edge_inventory.csv/.meta`。
- 20 继续输出 `channel_inventory.csv/.meta`。
- 30 继续输出 exception candidate/rule/coverage 产物。
- 00/01/04/10/20/30 分别输出自己的 `port_accounting_delta.csv/.meta`；所有 stage 输出 completion meta。

这些 artifact 记录各 stage 的 owner 决策和 digest，不能替代 `inputs/port_*.xlsx` 的连接真源或销账状态。

## 12. 最小 CLI 契约

所有 stage 的 target 入口至少支持：

```bash
python3 <stage_script>.py --run-root <run_root>
```

不再要求或接受 `--scenario` 作为 target runtime 的选择条件。02/04/20/30 可按自身功能继续接受 `--stage`、`--corner`、mode 或 review 相关参数。

诊断模式可以禁止正式 SDC 和 xlsx 写回，但必须在 report 中明确：

```text
Port accounting: diagnostic/read-only
Accounting closure: not evaluated
```
