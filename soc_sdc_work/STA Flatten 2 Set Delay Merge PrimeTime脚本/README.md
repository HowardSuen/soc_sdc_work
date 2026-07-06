# STA Flatten 2 Set Delay Merge PrimeTime 脚本

Stage 2 是一个运行在 PrimeTime 中的 Tcl proc，用于把 integration 层的
top delay 段和 harden 内部 delay 段合并成静态 end-to-end
`set_max_delay` / `set_min_delay` 约束。

本脚本按本目录中的 v0.3 规则文档实现。Stage 1 以当前目录为准：

```text
../STA Flatten 1 Harden DC SDC Clean 脚本/
```

Stage 1 已经支持静态 `-through` 对象的 hierarchy mapping，因此 Stage 2
只需要保证输出是 Stage 1 可再次处理的静态对象，例如：

```tcl
[get_pins {u_harden/cfg_i}]
[get_cells {u_harden/u_logic}]
[get_nets {u_harden/n1}]
```

不要输出变量、`all_fanin`、`all_fanout` 或运行时 collection 表达式。

## 使用入口

Stage 2 必须在 PrimeTime linked design 环境中运行。也就是说，运行
Stage 2 之前，项目 PT setup 需要已经完成：

```tcl
set search_path [list ./netlist ./lib ./sdc]

set link_path [list * \
  ./lib/slow.db \
  ./lib/fast.db \
]

read_verilog <top_netlist>
read_verilog <harden_flatten_netlist_0>
read_verilog <harden_flatten_netlist_1>

link_design <current_integration_top>
current_design <current_integration_top>
```

如果项目使用 multi-scenario / multi-corner flow，`.db`、operating condition、
RC、SPEF、base clock SDC 等 setup 应沿用项目现有 PT flow。Stage 2
脚本本身不负责读 `.lib` / `.db`，它假设当前 PrimeTime database 已经 link
完成，并且可以查询 pin/cell/net/attribute。

最简单的执行方式是使用本目录下的 wrapper：

```tcl
source {/Users/howard/Documents/33_vcspyglass sdc处理/soc_sdc_work/STA Flatten 2 Set Delay Merge PrimeTime脚本/run_stage2.tcl}
```

也可以直接 source 主脚本并调用 `stage2_delay::build`：

```tcl
source integration_delay_merger.pt.tcl

stage2_delay::build \
  -top_sdc ./top_dc.sdc \
  -harden_list ./harden_list.csv \
  -out_e2e_sdc ./generated_e2e_delay.sdc \
  -out_report ./integration_delay_merge.rpt \
  -out_removed_sdc ./merged_delay_removed.sdc \
  -out_review_rpt ./unmerged_delay_review.rpt \
  -merge_mode replace
```

生成后可选执行 post-check：

```tcl
stage2_delay::post_check -e2e_sdc ./generated_e2e_delay.sdc
```

## run_stage2.tcl 参数

通常只需要修改 [run_stage2.tcl](run_stage2.tcl) 顶部的用户配置区：

```tcl
set RUN_DIR /your/pt/run/dir
set TOP_SDC [file join $RUN_DIR top_dc.sdc]
set HARDEN_LIST [file join $RUN_DIR harden_list.csv]
set OUT_DIR $RUN_DIR
```

最终单文件 SDC 默认按当前 PT `current_design` 命名：

```text
<top_module_name>_flatten.sdc
```

例如当前设计是 `link_top`，则输出：

```text
link_top_flatten.sdc
```

推荐先保持默认策略：

```tcl
set MERGE_MODE replace
set PARTIAL_MERGE_POLICY residual_through
set UNMATCHED_HARDEN_POLICY review
set ALLOW_THROUGH true
set MAX_ENDPOINTS 1000
set MAX_ENUM_OBJECTS 64
```

这些默认值含义如下：

- `MERGE_MODE=replace`：成功 merge 的原始 top/harden delay 不再作为最终约束
  source，原文写入 `merged_delay_removed.sdc` 备查。
- `PARTIAL_MERGE_POLICY=residual_through`：harden `open_from` 有多个 boundary
  input 但只部分匹配 top delay 时，对未匹配 boundary 生成保守 residual
  `-through` 约束。
- `UNMATCHED_HARDEN_POLICY=review`：harden complete 段找不到 top 段时进入
  review，不自动生成 residual。
- `ALLOW_THROUGH=true`：允许 top `open_from` 场景生成
  `-through [get_pins <boundary>] -to <endpoint>`。

## 输入文件

### `top_sdc`

当前 integration top 的 SDC 文本。Stage 2 只解析：

```tcl
set_max_delay
set_min_delay
```

解析时脚本会把原始命令记录成 segment，不会把这些原始 delay 约束提前写入
PrimeTime timing exception database。

典型 top external segment：

```tcl
set_max_delay 2.0 -from [get_pins {u_src/Q}] -to [get_pins {u_h0/cfg_i}]
set_max_delay 2.0 -to [get_pins {u_h0/cfg_i}]
```

### `harden_list.csv`

推荐列：

```csv
harden_name,inst_path,clean_sdc,delay_candidate_file,netlist,module
ucie0,u_ucie_0,./sdc/ucie0_clean.sdc,./sdc/ucie0_delay.csv,./netlist/ucie_flat.v,ucie_uaxi_top
dd0,u_dd_0,./sdc/dd0_clean.sdc,,./netlist/dd_flat.v,dd_top
```

关键字段：

- `inst_path`：当前 integration top 下的 harden instance path。
- `clean_sdc`：Stage 1 输出的 clean harden SDC。
- `delay_candidate_file`：可选；没有就留空。

同一个 harden module 如果例化多次，每个 instance 必须写独立行，不能跨
instance 复用 delay candidate。

### Harden clean SDC / candidate CSV

Stage 2 可以直接解析每个 harden 的 `clean_sdc`，也可以额外读取
delay candidate CSV。

candidate CSV 当前支持的核心字段：

```csv
command_id,type,delay,from,to,line_no,input_delay_overlap
```

如果某行 `input_delay_overlap=yes`，Stage 2 会强制该段进入 review，并标记：

```text
BUDGET_SEMANTICS_UNRESOLVED
```

## 输出文件

- `generated_e2e_delay.sdc`：新生成的 E2E delay 约束，以及 partial merge
  时生成的 residual conservative 约束。
- `integration_delay_merge.rpt`：summary、成功 merge、residual、review 的详细记录。
- `merged_delay_removed.sdc`：`replace` 模式下被 consume 的原始 top/harden
  delay 命令。
- `unmerged_delay_review.rpt`：不能自动 merge、需要人工 review 的约束。
- `<top_module_name>_flatten.sdc`：最终单文件 SDC，包含 top 剩余约束、Stage 2
  生成的 E2E delay、各 harden 剩余约束，以及 review 摘要。若直接调用
  `stage2_delay::build`，也可以用 `-out_final_sdc` 显式指定其它文件名。

建议检查顺序：

```text
integration_delay_merge.rpt
unmerged_delay_review.rpt
generated_e2e_delay.sdc
merged_delay_removed.sdc
<top_module_name>_flatten.sdc
```

## v0.3 支持范围

v0.3 只自动合并 input 方向单跳：

```text
S(top legal startpoint) -> B(harden boundary input) -> E(harden internal endpoint)
```

支持四类组合：

- Top complete + harden complete
- Top complete + harden open_from
- Top open_from + harden complete
- Top open_from + harden open_from，前提是能推导 boundary input

输出示例：

```tcl
set_max_delay 7 -from [get_pins {u_src/Q}] -to [get_pins {u_h0/u_reg/D}]
set_max_delay 7 -through [get_pins {u_h0/cfg_i}] -to [get_pins {u_h0/u_reg/D}]
```

delay 数值规则：

```text
D_total_max = D_top_max + D_harden_max
D_total_min = D_top_min + D_harden_min
```

不允许混合 `top max + harden min` 或 `top min + harden max`。

## 不自动合并的情况

以下情况会进入 review 或 passthrough：

- output 方向路径。
- harden-to-harden 多跳链，例如 top `-from` 是上游 harden boundary output pin。
- delay 命令没有 `-to`。
- max/min 类型不一致。
- `-from`、`-to`、`-through` 中出现 clock 或未知对象。
- edge-specific option，例如 `-rise_from`、`-fall_to`、`-rise`、`-fall`。
- 生成后的 `-from` 不是合法 startpoint。
- 生成后的 `-to` 不是合法 endpoint。
- candidate 标记 `input_delay_overlap=yes`。
- harden instance 不存在、未 link，或内部 endpoint 在当前 PT database 中不可见。

passthrough segment 只在 report 中计数，不会塞进人工 review 报告。例如 harden
内部对象到内部对象的纯内部 delay，或者 top 内部 delay，默认都不是 Stage 2
merge candidate。

## PrimeTime API 假设

脚本依赖以下 PrimeTime collection / query API：

- `get_pins`、`get_ports`、`get_cells`、`get_nets`
- `get_attribute`
- `sizeof_collection`
- `foreach_in_collection`
- `filter_collection`
- `all_fanin`
- `all_fanout`

对 harden `open_from` endpoint 推导 boundary input 时，脚本遵守规则文档要求：

- 不使用 `all_fanin -flat` 与 harden boundary hierarchical pin 求交。
- 优先使用非 flat `all_fanin -to <E>`，再与当前 harden instance 的 input pin
  collection 求交。
- 若非 flat fanin 不可用，再 fallback 到从每个 boundary input 做
  `all_fanout -flat -from <B>`，检查是否能到达 leaf endpoint `E`。

## 默认参数

```text
-merge_mode replace
-top_open_from_mode through
-allow_through true
-allow_collapse_single_boundary false
-partial_merge_policy residual_through
-unmatched_harden_policy review
-max_endpoints 1000
-max_enum_objects 64
```

## 回归测试

本目录包含一个 smoke regression，可以在没有 PrimeTime license 的环境下用
普通 `tclsh` 跑。它验证的是解析、匹配、report 和静态 SDC 输出，不替代
真正的 PT linked design 验证。

```bash
python3 regression_test/run_regression.py
```

当前覆盖：

- complete + complete merge
- top open_from 生成 `-through`
- harden open_from 显式 `-through`
- 多跳 harden output start 进入 review
- edge-specific option 进入 review

生产使用前仍必须在 PrimeTime linked design 中做验证，因为 boundary 推导、
startpoint/endpoint 合法性和 ignored exception 检查都依赖真实 STA database。
