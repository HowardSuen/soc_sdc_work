# 00 Environment Initialization Rules

## 1. 定位

00 是 SoC SDC flow 的基础环境初始化 stage，不生成 SDC，也不拥有任何 clock、pad、interface 或 exception timing 语义。

本版 00 不再生成：

```text
connection_inventory.csv
pending port files
removed log
独立销账账本
```

端口连接和销账真源始终是 `inputs/port_*.xlsx`。

00 可以直接终结表单中显式声明的 NC、tie-off 和 open bit；这是结构性默认终态，不是 timing constraint，也不恢复独立销账账本。

## 2. 单场景运行

一个 run root 只对应一个外部选定场景。00 和后续 stage 都不接收 scenario 参数。

不同场景必须使用：

```text
不同 run root
不同的干净 port workbook 副本
该场景有效的 harden SDC 集合
```

不得在同一 run root 中初始化多个 scenario，也不得复用已被另一个场景写入 Used 状态的 workbook。

## 3. 命令行

目标入口：

```bash
python3 00_harden_port_inventory.py \
  --run-root <run_root>
```

建议支持：

```text
--resume-accounting
--require-complete-harden-sdc
--debug
```

- 默认是 fresh run，Used 状态列必须为空。
- `--resume-accounting` 只允许同一 run 的失败恢复；00 校验已有 token，不清空、不推断 owner。
- `--require-complete-harden-sdc` 把 missing SDC 提升为错误。

## 4. Required Inputs

```text
<run_root>/inputs/info_all.xlsx
<run_root>/inputs/port_*.xlsx
<run_root>/inputs/*.sdc                 # 允许部分缺失
<run_root>/inputs/run_context.csv
<run_root>/inputs/required_views.csv
```

`run_context.csv` 的 `run_id/mode_label/design_revision` 只用于交付追溯，不用于选择约束。`required_views.csv` 定义 02/04/20/30 必须完成的 stage/corner 组合。

### 4.1 `info_all.xlsx`

至少包含：

```text
module_name
inst_name
owner
```

项目可增加 SDC file/status mapping 字段。00 必须把 instance、module、owner 和当前 run 中的 SDC 文件对应起来。

### 4.2 `port_*.xlsx`

每个 instance sheet 使用 12 列：

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

连接字段：

- input driver：`From Whom`
- output top destination：`To Top`
- inout connection：`Inout Connectivity`

销账字段：

- input：`Input Used Width`
- output：`Output Used Width`
- inout：`Inout Name`

`Inout Name` 不再保存 connection。

## 5. 表单结构检查

00 必须检查：

1. 所有必需列存在，列名 normalization 后不重复。
2. instance sheet 能唯一映射到 `info_all.xlsx`。
3. port 名和 range 合法，width 与 range 一致。
4. 同一 instance/direction/canonical bit 不重复声明。
5. `From Whom` / `To Top` / `Inout Connectivity` 的基本语法可解析。
6. `Inout Name` 没有遗留真实 connection 字符串；若发现，应报错并要求迁移到 `Inout Connectivity`。
7. Used 状态列为空或符合共享编码。

00 可以报告互联引用问题，但不把互联展开或发布为 machine inventory。

## 6. Structural Default Accounting

00 对以下显式 connectivity token 默认视为已约束，并直接 union 对应 legal bits：

```text
NC / N/C / NO_CONNECT / UNCONNECTED
OPEN
TIE0 / TIE1
合法 Verilog 常量 literal
```

规则：

- input 使用 `From Whom`；output 使用 `To Top`；inout 使用 `Inout Connectivity`。
- 空白不等价于 OPEN，不得因为没有找到 fanout 就自动关闭 output。
- `NC/OPEN/TIE0/TIE1` 对该 row 当前方向的全部 legal bits 生效。
- sized Verilog literal 必须与 destination range 宽度一致并逐 bit 映射；宽度不一致时 error。
- 每个 structural terminal 写入 `00_middle/port_accounting_delta.csv/.meta`，reason 使用 `structural_nc`、`structural_open` 或 `structural_tie_off`，owner ID 使用 `STRUCT_<sha256>`。
- 00 不为这些 bit 生成任何 SDC 命令。

00 的 Used 写回必须使用共享 multi-workbook transaction；事务成功后才发布 delta 和 `00_middle/stage_completion.meta`。

## 7. Used 状态检查

### 7.1 Fresh run

默认要求：

```text
Input Used Width  = blank
Output Used Width = blank
Inout Name        = blank
```

发现以下终态表示 workbook 已被旧 run 使用，必须阻断 fresh 初始化：

```text
ALL USED
USED:...; UNUSED:...
```

### 7.2 Resume

resume 时允许：

```text
blank
0
0,1,4
2,3,4,5
```

00 必须验证所有 bit 属于对应 port 的合法实际 HDL index，去除重复后不改变语义。若已有 Used bit，还必须读取已提交的 stage accounting delta/meta，验证 structure digest 一致、digest chain 连续且 delta union 能解释全部 bit；缺失 owner 证据时阻断 resume。00 不负责把中间状态归一化为 final 状态。

## 8. Harden SDC Manifest

输出：

```text
00_middle/harden_sdc_manifest.csv
```

字段至少包含：

```text
inst_name
module_name
sdc_path
availability_status
sdc_digest
note
```

`availability_status`：

```text
available
missing
not_required
```

规则：

- 每个 instance 恰好一行。
- `available` 的 path 必须存在且 digest 匹配。
- `missing` 默认允许，后续 stage 继续处理其它完整对象。
- `not_required` 必须有明确依据。
- 00 不因 missing SDC 修改任何 Used 状态。

## 9. Input Snapshot

输出：

```text
00_middle/input_snapshot.meta
```

至少记录：

```text
run_id / mode_label / design_revision
run_context digest
required_views digest
structure_digest
accounting_digest_before
accounting_digest_after
每个 port workbook file digest before/after
每个 harden SDC digest/status
run-root absolute path
script version
timestamp
fresh/resume mode
```

`structure_digest` 排除 Used 列和样式；`accounting_state_digest` 只覆盖 canonical used-bit 集合；raw xlsx file digest 只用于并发/事务恢复。snapshot 不是连接表或销账账本。

00 还必须输出：

```text
00_middle/port_accounting_delta.csv
00_middle/port_accounting_delta.meta
00_middle/stage_completion.meta
```

## 10. Report

输出：

```text
00_result/reports/environment_report.txt
```

至少包含：

- instance/sheet/port/bit 数量。
- run_id/mode_label/design_revision 和 required view 清单。
- available/missing/not_required SDC 数量与清单。
- Used 状态列 fresh/resume 检查结果。
- NC/tie-off/open structural terminal 和 added bits。
- 表单结构、range、width、连接语法问题。
- structure/accounting/file digest、transaction ID 和运行模式。

## 11. Error / Warning

### Error

- 缺少 `run_context.csv`、`required_views.csv`、`info_all.xlsx` 或 port workbook。
- run_id/mode_label 空白，或 required view key/flag 非法。
- 必需列缺失/重复。
- instance/sheet 映射不唯一。
- port/range/width 非法。
- fresh run 的 Used 状态非空。
- Used 状态包含越界 bit 或 final token。
- inout connection 仍写在 `Inout Name`。
- structural token/literal 非法或 constant width 不匹配。
- accounting transaction 无法恢复、delta digest 不一致或 completion 无法发布。
- strict 模式存在 missing SDC。

### Warning

- 默认模式存在 missing SDC。
- connection 引用未知 instance/port；由实际消费该 edge 的 stage 再做精确阻断。
- optional manual input 缺失。

## 12. 与下游 Stage 的接口

下游读取：

```text
inputs/info_all.xlsx
inputs/port_*.xlsx
00_middle/harden_sdc_manifest.csv
00_middle/input_snapshot.meta
00_middle/port_accounting_delta.csv
00_middle/port_accounting_delta.meta
00_middle/stage_completion.meta
```

下游不得再要求 00 提供 connection inventory、pending 或 removed log。01、04、10、20、30 的销账直接写回 `port_*.xlsx` 并输出自己的 accounting delta；02、03 只读。

详细互联、used-bit、原子写回和 30 最终着色规则见：

```text
docs/shared_script_runtime_rules.md
```
