# STA Flatten 2 Set Delay Merge PrimeTime 脚本

Stage 2 是一个运行在 PrimeTime 中的 Tcl proc，用于把 integration 层的
top delay 段和 harden 内部 delay 段合并成静态 end-to-end
`set_max_delay` / `set_min_delay` 约束。

## 协作备份规则

后续每次涉及规则、代码或文档的改动，都需要在验证后提交并 push 到
git 仓库做备份。提交时只纳入本次 Stage 2 相关文件，避免混入其他目录的
临时文件或未确认改动。

本脚本按本目录中的规则文档实现。当前脚本版本为 v0.9.5。Stage 1 以当前目录为准：

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

## 作者标记

Tcl 主脚本和 Excel 报告脚本都会在 terminal、log、SDC、report 及 summary
索引中打印作者。作者名由分散在脚本既有词汇中的字符锚点按乱序索引在运行时
重建，主脚本中不保存可直接搜索替换的完整姓名常量。这用于提高随手篡改的
门槛，不作为加密、数字签名或法律意义上的作者认证。

作者显示还会通过另一组独立锚点进行二次校验。若生成值与校验值不一致，所有
作者输出统一改为 `Who is your daddy?`，用于提示作者标记被随手修改。

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

Stage 2 现在是单文件脚本，不再需要单独的 `run_stage2.tcl`。
通常只需要修改 `run_stage2_merge_delay.tcl` 顶部的
`Single-file runner user settings` 区，然后在 PT 中 source 这一份文件：

```tcl
source {/path/to/run_stage2_merge_delay.tcl}
```

顶部配置区保留了原 `run_stage2.tcl` 风格的变量设置，常用项如下：

```tcl
set ::RUN_DIR {/your/pt/run/dir}
set ::TOP_SDC [file join $::RUN_DIR top_dc.sdc]
set ::HARDEN_LIST [file join $::RUN_DIR harden_list.csv]
set ::OUT_DIR $::RUN_DIR
set ::TOP_PORT_BOUNDARY_MAP_MODE connectivity
set ::TOP_OPEN_FROM_MODE enumerate_static_startpoints
set ::RECURSIVE_CHAIN_MODE auto
set ::MAX_CHAIN_DEPTH 6
set ::STAGE2_COMPACT_BUS true
set ::STAGE2_COMPACT_BUS_MIN_MEMBERS 4
set ::STAGE2_BATCH_OPEN_TO_QUERY true
set ::STAGE2_VERBOSE_PT_QUERY true
set ::STAGE2_TRACE_FILE [file join $::OUT_DIR stage2_live.log]
set ::WRITE_PATH_SUMMARY true
set ::OUT_SUMMARY_DIR [file join $::OUT_DIR delay_path_summary]
set ::STAGE2_TEXT_ENCODING utf-8
```

如果只是想把主脚本当 proc library 使用，source 前关闭 auto-run：

```tcl
set ::STAGE2_AUTO_RUN false
source {/path/to/run_stage2_merge_delay.tcl}

stage2_delay::build \
  -top_sdc ./top_dc.sdc \
  -harden_list ./harden_list.csv \
  -out_e2e_sdc ./generated_e2e_delay.sdc \
  -out_report ./integration_delay_merge.rpt \
  -out_removed_sdc ./merged_delay_removed.sdc \
  -out_review_rpt ./unmerged_delay_review.rpt \
  -out_trace_file ./stage2_live.log \
  -out_summary_dir ./delay_path_summary \
  -write_path_summary true \
  -merge_mode replace
```

生成后可选执行 post-check：

```tcl
stage2_delay::post_check -e2e_sdc ./generated_e2e_delay.sdc
```

## 单文件参数

通常只需要修改 `run_stage2_merge_delay.tcl` 顶部的用户配置区：

```tcl
set ::STAGE2_AUTO_RUN true
set ::RUN_DIR {/your/pt/run/dir}
set ::TOP_SDC [file join $::RUN_DIR top_dc.sdc]
set ::HARDEN_LIST [file join $::RUN_DIR harden_list.csv]
set ::OUT_DIR $::RUN_DIR
set ::TOP_PORT_BOUNDARY_MAP_MODE connectivity
set ::RECURSIVE_CHAIN_MODE auto
set ::MAX_CHAIN_DEPTH 6
set ::STAGE2_COMPACT_BUS true
set ::STAGE2_COMPACT_BUS_MIN_MEMBERS 4
set ::STAGE2_BATCH_OPEN_TO_QUERY true
set ::STAGE2_VERBOSE_PT_QUERY true
set ::STAGE2_TRACE_FILE [file join $::OUT_DIR stage2_live.log]
set ::WRITE_PATH_SUMMARY true
set ::OUT_SUMMARY_DIR [file join $::OUT_DIR delay_path_summary]
set ::STAGE2_TEXT_ENCODING utf-8
```

最终单文件 SDC 默认按 `TOP_SDC` 的文件名命名：

```text
<TOP_SDC_basename>_flatten.sdc
```

例如 `set ::TOP_SDC ./aie_top.sdc`，则输出：

```text
aie_top_flatten.sdc
```

推荐先保持默认策略：

```tcl
set MERGE_MODE replace
set PARTIAL_MERGE_POLICY residual_through
set UNMATCHED_HARDEN_POLICY review
set ALLOW_THROUGH false
set TOP_PORT_BOUNDARY_MAP_MODE connectivity
set TOP_OPEN_FROM_MODE enumerate_static_startpoints
set RECURSIVE_CHAIN_MODE auto
set MAX_CHAIN_DEPTH 6
set STAGE2_VERBOSE_PT_QUERY true
set STAGE2_TRACE_FILE [file join $OUT_DIR stage2_live.log]
set WRITE_PATH_SUMMARY true
set OUT_SUMMARY_DIR [file join $OUT_DIR delay_path_summary]
set STAGE2_TEXT_ENCODING utf-8
set MAX_ENDPOINTS 1000
set MAX_ENUM_OBJECTS 64
set STAGE2_COMPACT_BUS true
set STAGE2_COMPACT_BUS_MIN_MEMBERS 4
set STAGE2_BATCH_OPEN_TO_QUERY true
```

这些默认值含义如下：

- `MERGE_MODE=replace`：成功 merge 的原始 top/harden delay 不再作为最终约束
  source，原文写入 `merged_delay_removed.sdc` 备查。
- `PARTIAL_MERGE_POLICY=residual_through`：harden `open_from` 有多个 boundary
  input 但只部分匹配 top delay 时，对未匹配 boundary 尝试生成保守 residual
  约束。residual 也必须能由 PT 推导出合法 `-from`；否则进入 review。
- `UNMATCHED_HARDEN_POLICY=review`：harden complete 段找不到 top 段时进入
  review，不自动生成 residual。
- `ALLOW_THROUGH=false`：普通生成不允许 top `open_from` 静默退化成缺少
  `-from` 的 through-only 约束。脚本会优先通过 PT `all_fanin` 推导真实
  startpoint；推导不到则进入 review。
- `TOP_PORT_BOUNDARY_MAP_MODE=connectivity`：当 top SDC 是 DC 原始吐出的
  block SDC，`-to` 仍然是 `[get_ports ...]` 时，脚本会在已 link 的 PT
  database 中通过 direct net connectivity 找到连接到该 top port 的 harden
  boundary input pin，再参与 merge。若设成 `off`，这些 top port delay 会
  保持 passthrough。
- `TOP_OPEN_FROM_MODE=enumerate_static_startpoints`：当 top delay 没有 `-from`
  时，脚本默认用 PT `all_fanin -flat -startpoints_only -to <boundary>` 推导
  静态 startpoint。最终生成的 E2E / residual delay 约束一定包含 `-from`；
  同时允许包含一个或多个 `-through` 来标识中间 boundary/path 点。若 PT
  返回的是寄存器 `CP` 这类 input pin，脚本会把它作为 PT timing startpoint
  接受；这个放行只适用于 PT `all_fanin -startpoints_only` 推导结果，不会
  放宽原始 SDC 手写 `-from` 的合法性检查。
- 当 top 或 harden delay 有 `-from`、但没有 `-to`（`open_to`）时，脚本会
  从最后一级 `-through` 开始调用 PT `all_fanout -flat -endpoints_only`；没有
  `-through` 时从 `-from` 开始。进入 `harden_list.csv` 所列 harden 的 endpoint
  会先通过非 flat `all_fanin` 恢复唯一 input boundary，再进入既有递归 delay
  累加。最终生成的 E2E 约束必须同时包含显式 `-from` 和 `-to`。
- `STAGE2_COMPACT_BUS=true`：仅对 `open_to` 的 `-from` 和各级 `-through`
  尝试 bus collection 压缩。对象必须属于同一 class、direction、owner 和
  bus basename，index 连续且无重复；默认至少 4 个成员才尝试。脚本会在当前
  linked PT database 中查询 `[get_pins {bus[*]}]` 或
  `[get_ports {bus[*]}]`，只有实际返回对象名集合与原始成员集合完全一致时才
  使用 `[*]`。缺 bit、额外匹配、对象被优化掉或查询失败时保留原 list。
- harden immediate boundary 的 `-from` 不做 bus 合并，因为 Stage 2 仍需逐成员
  匹配跨层 delay 和重写未消费约束；它们仍会参与下面的批量 PT 查询。
- `STAGE2_BATCH_OPEN_TO_QUERY=true`：同一 open_to seed 按 pin/port/cell/net
  class 组成 collection，每个 class 只执行一次 endpoint fanout；harden
  open_to 的 full fanout 也只执行一次。若当前 PT 版本不接受 multi-pattern
  getter、返回集合不完整或命令报错，脚本自动回退为逐 seed 查询，不丢原约束。
- bus 等价查询和 open_to endpoint 查询在一次 build 内缓存，避免最终 SDC
  残留重写时重复访问 PT。压缩数、节省成员数、batch 数、fallback 数和 endpoint
  数会写入 `integration_delay_merge.rpt` 的 `[SUMMARY]`。
- v0.9.2 会把显式对象 list 按 pin/port/cell/net 分组，一次查询同类对象的
  `direction`。只有 PT 返回的 `full_name` 集合与原始对象集合完全相等时才采用
  批量结果；getter 不支持 multi-pattern、查询报错、少返回或多返回对象时，
  自动回退逐对象查询。该优化只减少 PT metadata query 次数，不改变对象集合。
- v0.9.2 会缓存对象属性、owner harden、harden endpoint 到 input boundary、
  boundary 到 startpoint，以及 missing-SDC fanin/fanout 推导结果。缓存 key
  包含实际对象名和必要的 harden scope，空结果也会缓存，避免同一失败查询反复
  扫描 PT database。
- v0.9.2 在 segment 分类完成后建立 boundary 索引，并在生成最终 flatten SDC
  时复用第一次解析得到的 segment。完全没有 consumed delay 的 SDC 文件直接
  原样写出，不再逐条重新扫描；若索引条目意外缺失，仍保留原解析 fallback。
- v0.9.3 将解析 object list、展开 through group、bus compact fallback、top port
  boundary mapping 和 open_to target 汇总中的重复 `concat` 改为增量 `lappend`，
  避免长 list 在循环中反复整表复制。该改动只影响 Tcl 内部构造成本，不改变
  object 顺序、分组或最终 SDC collection。
- v0.9.3 将 final SDC partial rewrite 的 consumed segment 匹配改为
  signature-count hash，并复用递归路径已经计算的 signature；同一 signature
  出现多次时仍按计数逐条消费，不会把重复约束错误合并。
- v0.9.3 的 path summary 在一次遍历中建立 sheet、status、missing-SDC、最大列数
  和 max-delay 使用统计；每行 key/value 数据只解析一次。CSV 列顺序、行顺序和
  `00_index.csv` 统计口径保持不变。
- v0.9.4 新增实时 `stage2_live.log`。文件在 SDC 解析前创建，每写一行立即
  `flush`，长时间运行时可以直接观察当前阶段、PT query、review 和最终计数。
- v0.9.4 对每个 `INVALID_STARTPOINT` 立即记录实际候选 `from/to` 的 class、
  full name、direction、owner，以及 path、top ID 和 harden ID。该版本只增强
  诊断，不自动放宽 startpoint 合法性规则。
- v0.9.5 修复 PT 认可的 input clock pin 被误报 `INVALID_STARTPOINT`。当
  候选 `-from` 不满足静态 direction 规则时，脚本仅在它被最终
  endpoint 的 `all_fanin -flat -startpoints_only` 精确返回时放行，并记录
  `STARTPOINT_PT_CONFIRMED`。普通组合逻辑 input pin 仍会进入 review。
- `integration_delay_merge.rpt` 和 terminal 的 `Stage2 performance statistics`
  会记录 metadata batch/fallback、单对象查询、缓存命中、segment index lookup、
  final rewrite 命中、signature lookup 与跳过文件数，便于定位大型设计中的实际热点。
- `RECURSIVE_CHAIN_MODE=auto`：自动沿 harden output -> harden input 的 top
  delay 继续递归串接，不需要用户手工调用单跳输出。
- `MAX_CHAIN_DEPTH=6`：递归串接最大深度，用于防止异常环路。
- `STAGE2_VERBOSE_PT_QUERY=true`：默认打印每个关键 PT query，terminal 会显示
  `PT_QUERY:` 前缀的查询动作，方便确认对象、方向、fanin/fanout 和 connectivity
  是否被 PT database 正确返回。若日志太长，可临时设为 `false`。
- `STAGE2_TRACE_FILE`：实时 trace 文件，默认是 `$OUT_DIR/stage2_live.log`；
  文件会持续写入并立即 flush。显式设置绝对路径可以覆盖默认位置。
- `WRITE_PATH_SUMMARY=true`：默认生成 review-friendly CSV bundle。
- `OUT_SUMMARY_DIR`：CSV bundle 输出目录，默认是
  `$OUT_DIR/delay_path_summary`。
- `STAGE2_TEXT_ENCODING=utf-8`：Stage 2 读写 SDC/report/CSV 的文本编码。
  如果 legacy SDC 注释是在 Windows GBK/GB2312 下保存，且最终
  `<TOP_SDC_basename>_flatten.sdc` 打开后中文注释乱码，可以在 source 前临时
  改成 `gb2312` 或 `cp936` 后重新跑；正常 Linux/PT flow 推荐保持 `utf-8`。

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

如果 `top_sdc` 直接来自 DC `write_sdc`，常见形态会是：

```tcl
set_max_delay 2.0 -from [get_pins {u_src/Q}] -to [get_ports {cfg_top}]
```

这种情况下，只要 PT link 后能证明 `cfg_top` 的 direct connected net 上有
当前 `harden_list.csv` 里的 harden input boundary pin，例如
`u_h0/cfg_i`，默认 `TOP_PORT_BOUNDARY_MAP_MODE=connectivity` 会先映射为
`u_h0/cfg_i` 再参与 Stage 2 merge。映射记录会写在
`integration_delay_merge.rpt` 的 `[DETAIL]` 区，格式类似：

```text
TOP_PORT_BOUNDARY_MAP top_id=CMD000001.P001 mode=connectivity port=cfg_top boundary=u_h0/cfg_i total=1
```

如果 top port 只连到 harden output pin，或者没有连到任何 harden input
boundary，它不会被当前 Stage 2 自动合并，report 的 `[PASSTHROUGH]` 会说明
具体原因。

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
- `stage2_live.log`：运行过程中实时更新的阶段、PT query、review 和关键对象诊断。
- `delay_path_summary/`：delay 推导汇总 CSV bundle，包含 `00_index.csv`、
  `top.csv` 和每个 harden instance 一张 CSV。
- `<TOP_SDC_basename>_flatten.sdc`：最终单文件 SDC，包含 top 剩余约束、Stage 2
  生成的 E2E delay、各 harden 剩余约束，以及 review 摘要。若直接调用
  `stage2_delay::build`，也可以用 `-out_final_sdc` 显式指定其它文件名。

建议检查顺序：

```text
stage2_live.log
integration_delay_merge.rpt
unmerged_delay_review.rpt
delay_path_summary/00_index.csv
generated_e2e_delay.sdc
merged_delay_removed.sdc
<TOP_SDC_basename>_flatten.sdc
```

长时间运行时可以在另一个 Linux terminal 中实时查看：

```bash
tail -f stage2_live.log
```

遇到 `INVALID_STARTPOINT` 时，实时文件会立即出现类似记录：

```text
INVALID_STARTPOINT top_id=CMD000001 harden_id=CMD000002 \
from={class=pin,name=u_h0/async_i,direction=in,owner=u_h0} \
to={class=pin,name=u_h0/u_reg/D,direction=in,owner=u_h0} \
path={RECURSIVE:CMD000001}
```

这里打印的是脚本实际准备写入最终 `-from` 的 object，而不是事后从 endpoint
重新执行 `all_fanin` 得到的其它 startpoint，因此可直接定位递归链保留了哪个对象。

### Delay 推导汇总 CSV

`delay_path_summary/00_index.csv` 是索引，记录每张 sheet CSV 的文件名、
MERGED / RESIDUAL / REVIEW 行数，以及每个 sheet 中原生 `set_max_delay`
的使用统计：

```text
max_delay_used/max_delay_total/max_delay_usage/missing_sdc_stages
```

例如 `max_delay_usage=3/4` 表示该 sheet 对应的原始 SDC 中共有 4 条
`set_max_delay`，其中 3 条至少参与了一条最终生成的 E2E delay。若原始
命令因为 from/to list 被展开成多个 pair，统计时仍按同一个 `original_id`
归并，只算 1 条原始约束。
若某个 sheet 原始 SDC 中没有 `set_max_delay`，但 Stage 2 推导路径经过了该
模块并合成了 missing SDC stage，则 `max_delay_usage=0/0`，同时
`missing_sdc_stages` 会记录合成缺失段数量。Excel 中这种情况会显示为
`Max Delay Used: N/A`，避免把 `0/0` 误读成异常比例。

每张 sheet CSV 对应一个 SDC 来源：

- `top.csv`：top SDC 中的原生 delay 段。
- `<harden_inst>.csv`：该 harden clean SDC 中的原生 delay 段。

核心列含义：

- `native_delay/native_from/native_through/native_to`：本 sheet 对应 module SDC
  中的原生 delay 片段。
- `e2e_id`：最终生成约束编号，例如 `E2E000001`。同一条 E2E 约束在
  top / harden 各 sheet 中使用相同编号，并会写入最终 SDC 的注释。
- `final_delay/Start Point/start_sdc_delay/start_from/start_to/stage_N_sdc_delay/stage_N_from/stage_N_to/through_N/End Point/end_sdc_delay/end_from/end_to`：
  Stage 2 推导出的 integration top scope 完整路径。`Start Point` 和
  `End Point` 也有各自所属首段/末段的原生 SDC delay、from、to，方便首尾
  review。`stage_N_from` / `stage_N_to` 是第 N 段原生 SDC delay 的单段
  `-from/-to` 对象；`through_N` 是快速串线用的边界点。这里都只写裸 object
  名称，例如 `u_h0/cfg_i`；如果对象是 top port，则直接写 port 名称。
- `stage_N_sdc_delay`：完整路径中第 N 段原生 SDC delay 数值；短路径填 `-`。
  若该段在对应 harden clean SDC 中缺失，Stage 2 会在计算总 delay 时按 0
  处理，但 summary CSV 仍填 `-`，后续 Excel 会显示为 `NOT FOUND` 红底。
  缺失段只影响 delay 数值和 review 标记，不会把 harden input boundary
  放宽成最终 endpoint。
- `generated_cmd`：最终写入 `generated_e2e_delay.sdc` 或 final flatten SDC
  的静态约束命令。REVIEW 行填 `-`。
- `review_reason`：MERGED 行为 `-`，RESIDUAL / REVIEW 行记录原因。
- `seg_1_* ... seg_N_*`：完整推导链中每一段原生 delay 的来源、cmd id、
  delay、from/through/to，便于从 CSV 反查原始 SDC。

对于 top SDC 中没有 `-from`、且最终仍进入 REVIEW 的 delay，Stage 2 也会
尝试使用 PT `all_fanin -flat -startpoints_only` 推导 startpoint，并把推导
结果填入 CSV/Excel 的 `Start Point From`。若仍显示 `NOT FOUND`，通常表示
当前 PT database 对该 boundary pin 没有返回合法 startpoint，terminal 的
`PT_QUERY:` 日志会显示对应 `startpoint_count=0`。

对于 `direction=in` 的 pin，Stage 2 不会根据方向直接放行。只有当该候选
对象出现在最终 endpoint 的 PT `all_fanin -flat -startpoints_only` 结果中，
才会被标记为 `pt_startpoint=true` 并写入最终 `-from`。确认成功会在
`stage2_live.log` 中记录 `STARTPOINT_PT_CONFIRMED`。

例如递归链：

```text
harden_a.internal_start -> harden_a.output -> harden_b.input -> harden_b.endpoint
```

会在相关 harden sheet 中看到同一条 `generated_cmd`，并通过
`through_1/through_2` 展示中间 boundary pin。

### Excel 汇总报告

如果希望把 `delay_path_summary/*.csv` 进一步整理成 Excel，可以运行：

```bash
python3 run_stage2_report.py ./delay_path_summary
```

默认输出文件名按 `TOP_SDC` 的文件名命名：

```text
<TOP_SDC_basename>.xlsx
```

输出名会按以下优先级推断：

- 命令行 `--top_module`
- `integration_delay_merge.rpt` 中的 `Top SDC` 文件名
- `integration_delay_merge.rpt` 中的 `Final flatten SDC` 文件名
- `integration_delay_merge.rpt` 中的 `Current PT design`
- `generated_e2e_delay.sdc` 中的 `Scope`
- `delay_path_summary` 的父目录名

也可以显式指定输出路径：

```bash
python3 run_stage2_report.py ./delay_path_summary \
  --top_module aie_top \
  -o ./aie_top.xlsx
```

Excel 每个 CSV sheet 对应一个 worksheet。每个 worksheet 只保留路径 review
需要的内容：

```text
E2E ID | Start Point | through_1 | through_2 | ... | End Point
```

每个标题下面固定三列：

```text
From | To | Delay
```

本 worksheet 对应的原生 delay stage 会用黄色背景标出；缺少 delay/from/to
约束信息的位置会填 `NOT FOUND` 并使用红色背景。
每张 worksheet 的 A1 会显示该 sheet 的 `Max Delay Used: x/y`，用于快速
确认当前 top 或 harden 的原生 `set_max_delay` 被 Stage 2 使用的覆盖情况。
如果该 sheet 原始 SDC 没有 `set_max_delay`，A1 会显示：

```text
Max Delay Used: N/A
Native max_delay: 0
Missing SDC Stage: <N>
```

这里的 `Missing SDC Stage` 表示 Stage 2 为了继续完整 E2E path 推导而合成
的 assumed-zero 缺失段数量。
若同一条 `E2E ID` 在同一个 worksheet 中涉及多个原生 stage，Excel 会合并成
一行显示，并同时高亮这些 stage；未生成最终 SDC 的 REVIEW 行会在第一列显示
`REVIEW:...`，避免和真实生成约束编号混淆。

生成的 SDC 也会在每条约束前写同一个编号，方便从 Excel 反查最终约束：

```tcl
# MERGED id=E2E000001 top=CMD000001 harden=CMD000002 boundary=u_h0/cfg_i
set_max_delay 7 -from [get_pins {u_src/Q}] -through [get_pins {u_h0/cfg_i}] -to [get_pins {u_h0/u_reg/D}]
```

## v0.9 支持范围

v0.9 自动合并 input 方向单跳、harden input-to-output feedthrough，以及
harden output -> harden input 的递归 chain：

```text
S(top legal startpoint) -> B(harden boundary input) -> E(harden internal endpoint)
S(top legal startpoint) -> B_in(harden boundary input) -> B_out(harden boundary output)
A_internal_start -> A_output -> B_input -> B_internal_endpoint
```

支持四类组合：

- Top complete + harden complete
- Top complete + harden open_from
- Top open_from + harden complete
- Top open_from + harden open_from，前提是能推导 boundary input
- Top open_to：有 `-from`、缺 `-to`，由 PT 推导全部合法 endpoint 后展开
- Harden open_to：有 `-from`、缺 `-to`，由 PT 推导 harden 内部 endpoint
  或 harden output boundary 后展开
- harden complete feedthrough：`B_in -> B_out`，前提是 top 侧能匹配到
  `B_in`。
- recursive chain：若 top delay 是 `harden_a.output -> harden_b.input`，
  并且能找到 `harden_a.internal_start -> harden_a.output` 与
  `harden_b.input -> harden_b.endpoint`，则自动生成
  `harden_a.internal_start -> harden_b.endpoint`。
- missing top bridge SDC：若递归 path 到达 `harden_a.output` 后，top SDC
  中没有对应的 `harden_a.output -> harden_b.input` delay 段，脚本会用 PT
  `all_fanout` 查找下游 harden input boundary。PT 能证明该连接时，这段
  top bridge 按 assumed-zero 继续扩展，并在 top sheet 中显示 `NOT FOUND`。
- missing harden SDC stage：若递归 path 上某个 harden 的对应 clean SDC
  delay 段不存在，Stage 2 不再停止扩展。脚本会合成一个 assumed-zero
  stage 继续生成完整 E2E 约束，`integration_delay_merge.rpt` 中记录
  `MISSING_SDC_ASSUMED_ZERO`，CSV/Excel 中该 stage 的 delay 显示为
  `NOT FOUND` 供人工 review。若缺失的是末端 harden stage，脚本仍要求 PT
  从该 harden input boundary 推导到合法 endpoint；找不到合法 endpoint 时，
  不会生成停在 harden input boundary 的 `set_max_delay` / `set_min_delay`，
  而是进入 `MISSING_HARDEN_SDC_ENDPOINT_NOT_FOUND` review。这类 review 不应
  作为正常业务结果接受，通常表示 PT database、link/netlist、方向属性或 fanout
  查询条件还没有满足 Stage 2 自动推导要求。
- missing harden output source：若 top SDC 中存在
  `harden_a/output -> harden_b/input`，但 `harden_a` clean SDC 中没有
  `internal_start -> harden_a/output` 约束，Stage 2 会对
  `harden_a/output` 调用 PT `all_fanin -flat -startpoints_only`，把 PT
  返回的真实 startpoint 与 `harden_a/output` 组成 assumed-zero missing
  stage。例如：

```text
PT: harden_a/u_cell/Q -> harden_a/output_a
top SDC: harden_a/output_a -> harden_b/input_b
harden_b SDC: harden_b/input_b -> harden_b/u_cell2/D

生成路径:
harden_a/u_cell/Q -> harden_a/output_a -> harden_b/input_b -> harden_b/u_cell2/D
```

  其中 `harden_a/u_cell/Q -> harden_a/output_a` 若没有原生 SDC delay，
  计算值按 0，Excel 对应 harden sheet 标 `NOT FOUND`。如果 PT 也无法为
  `harden_a/output_a` 推导出 startpoint，则不再用
  `harden_a/output_a -> harden_a/output_a` 伪段凑路径，而是进入 review。
- missing upstream top for harden feedthrough：若 harden clean SDC 中存在
  `harden_a/input_a -> harden_a/output_a` feedthrough 约束，但 top SDC
  没有写 `top/startpoint -> harden_a/input_a` 这一段，Stage 2 会对
  `harden_a/input_a` 调用 PT `all_fanin -flat -startpoints_only`，把 PT
  返回的真实 startpoint 与 `harden_a/input_a` 组成 assumed-zero missing
  top stage，再继续串接 harden feedthrough 和下游 top/harden stage。例如：

```text
PT: top_reg/Q -> harden_a/input_a
harden_a SDC: harden_a/input_a -> harden_a/output_a
top SDC: harden_a/output_a -> harden_b/input_b
harden_b SDC: harden_b/input_b -> harden_b/u_cell2/D

生成路径:
top_reg/Q -> harden_a/input_a -> harden_a/output_a -> harden_b/input_b -> harden_b/u_cell2/D
```

  其中 `top_reg/Q -> harden_a/input_a` 若没有原生 top SDC delay，计算值按 0，
  Excel 的 top sheet 标 `NOT FOUND`。若已有 top/chain top segment 到
  `harden_a/input_a`，脚本不会再启用这条 PT missing-top fallback，避免重复
  生成或绕过中间 boundary。
- terminal top endpoint after harden output：若 harden output 下游不是另一个
  harden input，而是 top output port 或其它 PT 可识别的合法 endpoint，
  Stage 2 会把 `harden_output -> top_endpoint` 当作最后一段 top missing SDC
  或显式 top chain stage，然后直接 emit 最终 E2E 约束。例如：

```text
PT: top_reg/Q -> harden_a/input_a
harden_a SDC: harden_a/input_a -> harden_a/output_a
PT/top: harden_a/output_a -> top_output

生成路径:
top_reg/Q -> harden_a/input_a -> harden_a/output_a -> top_output
```

  若 `harden_a/output_a -> top_output` 没有原生 top SDC delay，计算值按 0，
  Excel top sheet 标 `NOT FOUND`。
  自动推导 terminal endpoint 时，Stage 2 只接受 PT
  `all_fanout -flat -endpoints_only` 返回的对象；普通
  `all_fanout -flat` 中出现的组合逻辑 input pin 只作为中间 fanout 节点，
  不会被当成最终 endpoint。

`open_to` 的覆盖规则：

1. 有 `-through` 时，从最后一个 `-through` option 的 object collection 向后
   推导；没有 `-through` 时从 `-from` 向后推导。
2. PT 返回多个 endpoint 时逐 endpoint 展开；同一 harden boundary 下的多个
   endpoint 都必须完成记账，相同的最终静态 SDC 只输出一次。
3. top open_to 的 endpoint 若位于已暴露 harden 内，必须先恢复唯一 harden
   input boundary，不能直接绕过 harden clean SDC。
4. endpoint 推导为空、超过 `MAX_ENDPOINTS`、boundary 推导为空或不唯一时，
   不 consume 原命令，并进入 review。
5. 与 harden merge 无关的 top terminal endpoint 可以保持 passthrough；若同一
   原命令只有部分 endpoint 被 consume，final SDC 会把其余 endpoint 改写成
   显式 `-to` 的静态残留约束。
6. 所有参与数值累加的真实 delay segment option 必须一致，例如
   `-ignore_clock_latency`。一致时 option 写入最终命令；不一致时进入
   `DELAY_OPTION_MISMATCH` review，原命令不 consume。

若 harden clean SDC 中仍保留 `[get_ports <port>]`，Stage 2 在解析 harden
文件时会把它映射到当前 instance 的 `[get_pins <inst>/<port>]`，再使用 PT
`get_attribute direction` 判断 input/output。这个映射只对 harden SDC
生效；top SDC 的 `[get_ports ...]` 仍按 direct connectivity 处理。

`-from` / `-to` 中允许出现多 object list，例如：

```tcl
set_max_delay 2.0 \
  -from [list [get_pins u_src0/Q] [get_pins u_src1/Q]] \
  -to [list [get_pins u_h0/cfg_i] [get_pins u_h0/async_i]]
```

脚本会先按 SDC 语义展开为单个 `from/to` pair，再逐 pair merge。若一个
原始多 object delay 只有部分 pair 被 Stage 2 consume，最终
`<TOP_SDC_basename>_flatten.sdc` 会把未 consume 的 pair 重写成单条静态
`set_max_delay` / `set_min_delay`，避免已 merge 的 pair 又从原始 list 中
重复生效。

`-through [list ...]` 保持为同一个 through stage 的多对象 collection，不会
错误拆成多个连续 `-through`。多个独立 `-through` option 才表示连续路径阶段。

输出示例：

```tcl
set_max_delay 7 -from [get_pins {u_src/Q}] -through [get_pins {u_h0/cfg_i}] -to [get_pins {u_h0/u_reg/D}]
set_max_delay 7 -from [get_pins {u_src/Q}] -through [get_pins {u_h0/cfg_i}] -to [get_pins {u_h0/u_reg2/D}]
set_max_delay 7 -from [get_pins {u_src/Q}] -through [get_pins {u_h0/cfg_i}] -to [get_pins {u_h0/data_o}]
set_max_delay 8 -from [get_pins {u_up/u_reg/Q}] -through [get_pins {u_up/data_o}] -through [get_pins {u_h0/cfg_i}] -to [get_pins {u_h0/u_reg/D}]
```

delay 数值规则：

```text
D_total_max = D_top_max + D_harden_max
D_total_min = D_top_min + D_harden_min
```

不允许混合 `top max + harden min` 或 `top min + harden max`。
若某个 harden stage 缺少 clean SDC delay 约束，该 stage 的计算值按 0
累加，但不会在报告中伪装成真实 0；报告里仍用 `NOT FOUND` 标识。缺失末端
stage 时，只有 PT 能继续推导出合法 endpoint 才会生成最终约束。

## 不自动合并的情况

以下情况会进入 review 或 passthrough：

- output 方向路径。
- harden `-to` 是 harden output boundary pin，但 `-from` 不是同一个 harden
  的 input boundary，或 top 侧找不到匹配到该 input boundary 的 delay 段。
- harden-to-harden 多跳链在 `RECURSIVE_CHAIN_MODE=auto` 时会尝试自动递归；
  缺少某个 top bridge 或 harden clean SDC stage 时按 assumed-zero 继续扩展
  并进入 report review 标识；若缺失 bridge/stage 无法由 PT 推导，末端缺失
  stage 无法由 PT 推到合法 endpoint，或方向未知、对象非法、超过
  `MAX_CHAIN_DEPTH`，则停止并进入 review。
- delay 同时缺少 `-from` 和 `-to`。
- open_to 无法从 PT 推导 endpoint、endpoint 数量超过 `MAX_ENDPOINTS`，或进入
  harden 后无法恢复唯一 input boundary。
- max/min 类型不一致。
- 参与同一 E2E 数值累加的 delay option 不一致，例如只有部分 segment 带
  `-ignore_clock_latency`。
- `-from`、`-to`、`-through` 中出现 clock 或未知对象。
- edge-specific option，例如 `-rise_from`、`-fall_to`、`-rise`、`-fall`。
- 生成后的 `-from` 不是合法 startpoint。
- 生成后的 `-to` 不是合法 endpoint。
- candidate 标记 `input_delay_overlap=yes`。
- harden instance 不存在、未 link，或内部 endpoint 在当前 PT database 中不可见。
- top `get_ports` endpoint 无法通过 direct connectivity 映射到 harden input
  boundary pin，或只映射到 harden output boundary pin。
- PT `get_attribute <object> direction` 返回空，导致脚本无法 golden 判断
  input/output 方向。

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
- harden boundary pin 必须是 `inst_path/pin_name` 这种 immediate pin；
  `inst_path/u_cell/D` 这类内部 leaf pin 不会被当作 boundary。
- input/output 方向只以 PrimeTime `get_attribute <pin_or_port> direction`
  返回值为准，不根据 `i_`、`_i`、`o_`、`_o` 等命名规则推断。

对 `open_to` endpoint 推导：

- 从最后一级 `-through` collection 开始；无 `-through` 时从 `-from` 开始。
- 使用 `all_fanout -flat -endpoints_only`，只接受 PT 返回并通过 endpoint
  合法性检查的对象。
- top endpoint 位于 harden 内时，再用非 flat `all_fanin -to <endpoint>` 与
  harden immediate input pin 求交，恢复 Stage 2 merge boundary。
- harden open_to 只接受同一 harden 内 endpoint 或该 harden 的 immediate
  output boundary，不把下游其它 scope 的 endpoint 错算成 harden 内部段。

若需要观察脚本实际向 PT 查询了什么，可打开：

```tcl
set ::STAGE2_VERBOSE_PT_QUERY true
```

terminal 会打印类似：

```text
PT_QUERY: get_ports -quiet {cfg_top}
PT_QUERY: get_nets -quiet -of_objects <ports:{cfg_top}>
PT_QUERY: get_pins -quiet -of_objects <net:{cfg_net}>
PT_QUERY: all_fanin -to {u_h0/u_reg/D}
```

对 top `get_ports` endpoint 的处理只使用 direct connectivity：

- `get_ports <P>` -> `get_nets -of_objects <P>` -> `get_pins -of_objects <net>`。
- 只接受属于 `harden_list.csv` 中 instance 的 harden input boundary pin。
- 不靠名字猜 `inst_path/port_name`，所以多个 harden 有同名 port 时也不会误配。
- 若同一个 top port 映射到多个 harden input boundary，脚本会展开成多条
  top merge candidate；只有这些映射全部成功 merge 时，`replace` 模式才会
  删除原始 top port delay，否则原始 top delay 保留并在 report 中提示。

## 默认参数

```text
-merge_mode replace
-top_open_from_mode enumerate_static_startpoints
-allow_through false
-allow_collapse_single_boundary false
-partial_merge_policy residual_through
-unmatched_harden_policy review
-top_port_boundary_map_mode connectivity
-recursive_chain_mode auto
-max_chain_depth 6
-compact_bus true
-compact_bus_min_members 4
-batch_open_to_query true
-verbose_pt_query true
-write_path_summary true
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
- top open_from 通过 PT `all_fanin` 推导 startpoint，并生成显式 `-from`
- top/harden open_to 通过 PT `all_fanout -flat -endpoints_only` 推导并生成显式
  `-to`
- 连续完整 bus 的 `-from` / `-through` 经 PT 集合等价验证后压缩为 `[*]`，并
  验证 top open_to 只执行一次批量 endpoint fanout
- bus 缺 bit、wildcard 额外匹配时拒绝压缩并保留精确成员
- multi-pattern getter 报错时自动回退逐 seed 查询，确认所有约束仍完整生成
- 64 个显式 pin 的 direction metadata 批量查询，以及批量返回集合不完整时的
  逐对象安全回退
- harden boundary/startpoint 和 missing-SDC fanin/fanout 查询缓存，确认同一
  logical key 不重复调用 PT
- segment boundary 索引、首次解析结果复用，以及未消费 SDC 文件直接写出
- harden open_to 的多 boundary seed 只执行一次 endpoint fanout 和一次 full
  fanout
- 多 object `-from`、多 endpoint 和 `-through [list ...]` 分组语义
- 同一 harden boundary 下多个 open_to endpoint 的完整 consume 与最终命令去重
- open_to PT 推导失败和 delay option 不一致时保留原命令并进入 review
- harden open_from 显式 `-through`
- 多跳 harden output start 缺少上游 harden SDC source 时 assumed-zero 继续扩展
- edge-specific option 进入 review
- 多 object `-from` / `-to` 展开 merge，并在 final SDC 中重写未 consume pair
- DC 原始 top SDC 的 `get_ports` endpoint 通过 PT connectivity 映射到
  harden input boundary 后 merge
- harden `[get_ports input] -> [get_ports output]` feedthrough 映射成
  instance boundary pin 后参与 delay 累加
- harden output -> harden input 多跳递归 chain
- delay path summary CSV bundle，包含 top / harden sheet、through 链、
  segment delay 和 generated command
- 缺失 top bridge / harden SDC stage assumed-zero，并在 Excel 报告中显示
  `NOT FOUND`
- 实时 trace 文件创建、阶段进度，以及非法 startpoint 的 from/to/path/command ID
  诊断内容
- PT 证明的 `direction=in` clock pin 可在 direct/recursive 发射路径中作为
  最终 `-from`，而未被 PT startpoint 集合返回的普通 input pin 仍被拒绝

当前共 36 个 mock-Tcl 回归 case；同时包含生成 SDC 的静态 source 校验。
这些 case 证明脚本解析、匹配、回退和输出行为稳定，但不能替代真实 PrimeTime
linked design 下的 collection、timing path 和 exception 验证。

v0.9.3 另使用 2048 个显式对象的固定 mock case 做参考基准：生成 2048 条
E2E 约束，`top.csv` 与 harden CSV 各 2048 行；同一环境下耗时由 v0.9.2
改动前的 `6.808s` 降至 `6.309s`，约减少 7.3%。该结果只反映 Tcl 解析、匹配、
重写和 CSV 汇总成本，不代表真实 PrimeTime database 查询的加速比例。

生产使用前仍必须在 PrimeTime linked design 中做验证，因为 boundary 推导、
startpoint/endpoint 合法性和 ignored exception 检查都依赖真实 STA database。
