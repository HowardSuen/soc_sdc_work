# Stage1 Harden DC SDC Clean 规则

## 1. 定位

Stage1 脚本 `run_stage1_clean_sdc.py` 用于把 harden DC/PT flatten SDC 清理为
SoC STA 可以 source 的 harden-internal SDC。

Stage1 的职责：

1. 删除应由 SoC 顶层、MMMC、RC 或其它 SoC SDC stage 管理的约束。
2. 保留 harden 内部约束，并把对象上升到 SoC instance hierarchy。
3. 处理 local clock 的改名和引用追随。
4. 隔离无法安全转换的 Tcl/SDC 命令。
5. 生成 removed、unsupported、modified details 和 report 供人工复核。

Stage1 输出的 clean harden SDC 与 SoC SDC 01~30 规则共同组成全片 STA 约束。

当前脚本版本：`v2.3.2`，兼容 Python 3.6，仅依赖 Python 标准库。

## 2. 输入和 instance 规则

输入可以是：

- 原始 harden DC flatten SDC。
- `run_stage2_merge_delay.tcl` 生成的 Stage2 flatten SDC。

`--inst` 必须填写当前 harden 在 SoC 顶层下的完整 instance path，并支持多级
hierarchy，例如：

```text
u_b/u_b1
```

对象映射示例：

```tcl
# 输入
[get_ports data_i]
[get_pins u_reg/Q]

# --inst u_b/u_b1 后
[get_pins u_b/u_b1/data_i]
[get_pins u_b/u_b1/u_reg/Q]
```

如果对象已经以 `<inst>/` 开头，脚本不重复添加 instance prefix。

## 3. 基本运行方式

```bash
python3 run_stage1_clean_sdc.py \
  --in input_flatten.sdc \
  --out output_soc.sdc \
  --removed-out output_removed.sdc \
  --unsupported-out output_unsupported.sdc \
  --modified-details output_modified_details.txt \
  --report output_report.txt \
  --inst u_b/u_b1
```

### 3.1 批处理运行方式

批处理 CSV 的必需表头为 `MODULE_NAME,INST_NAME,SDC_PATH`：

```csv
MODULE_NAME,INST_NAME,SDC_PATH
ucie_uaxi_top,u_ucie_uaxi_top,input/ucie_uaxi_top.sdc
b1,u_b/u_b1,./input/b1.sdc
```

`SDC_PATH` 可以是绝对路径；相对路径以 batch CSV 所在目录为基准：

```bash
python3 run_stage1_clean_sdc.py \
  -i modules.csv
```

输出根目录为启动命令时的当前工作目录（`pwd`）。每个实例生成独立输出目录；
`INST_NAME` 中的 `/` 转换为目录名中的 `__`。例如 `u_b/u_b1` 对应
`./u_b__u_b1/`。所有状态非 `INVALID_OUTPUT` 的 `*_clean.sdc` 会复制到公共
`./result/`，并在当前目录生成 `batch_report.csv`。同一批次不允许两个实例映射
到相同输出目录名。长选项 `--batch-file` 与短选项 `-i` 等价。

## 4. 处理流程

1. 检查输入是否为 Stage1 自身输出，防止重复处理。
2. 允许 Stage2 flatten SDC；通用 `SDC_PROCESS_VERSION` 不作为 Stage1 已处理判据。
3. 预处理整行注释，同时保留原始行号关系。
4. 使用 Tcl-like scanner 合并反斜杠续行和多行 command。
5. Pass1 扫描 clock definition，建立 rename map 和 removed clock set。
6. Pass2 对每条命令分类、删除或 hierarchy mapping。
7. Pass3 检查 dangling clock、单位和输出一致性。
8. 分别生成主 SDC、removed、unsupported、modified details 和 report。

## 5. 分类定义

| 分类 | 含义 | 是否进入主 SDC |
| --- | --- | --- |
| `KEEP` | 可直接保留 | 是 |
| `MODIFY` | hierarchy、clock name 或对象已修改 | 是 |
| `REMOVE` | 按项目 ownership 明确去除 | 否，写入 `removed.sdc` |
| `UNSUPPORTED` | 脚本无法证明可安全转换 | 否，写入 `unsupported.sdc` |
| `ERROR` | 单位、结构或一致性错误 | 否，状态为 `INVALID_OUTPUT` |

`REMOVE` 和 `UNSUPPORTED` 含义不同。`REMOVE` 是规则明确删除；`UNSUPPORTED`
是脚本暂时无法安全处理，不代表该约束在 STA 中不需要。

## 6. 对象映射规则

### 6.1 支持的对象

- `get_ports <name>` -> `get_pins <inst>/<name>`。
- `get_pins`、`get_cells/get_cell`、`get_nets/get_net` 增加 `<inst>/`。
- `get_clocks` 根据 clock rename map、clock mapping file 或 allowlist 处理。
- safe `[list [get_ports/get_pins ...] ...]` wrapper 支持递归映射。
- bus bit、brace、escape 和 wildcard 尽量保持原写法。

### 6.2 不安全 collection

以下对象不能直接映射到主 SDC：

- 裸 `get_ports`。
- `get_ports *` 或危险全选 glob。
- `all_inputs`、`all_outputs`、`all_registers`、`all_fanin`、`all_fanout`、
  `all_clocks`，除非命令本身属于固定 REMOVE 规则。
- 无法安全解析的 nested collection、变量和复杂 filter。

这类命令通常进入 `unsupported.sdc`，而不是静默保留。

## 7. Clock 规则

### 7.1 `create_clock`

| 情况 | 处理 |
| --- | --- |
| target 为 block `get_ports` | `REMOVE`，SoC primary clock 由顶层负责 |
| target 为 `[list [get_ports A] [get_ports B]]` | `REMOVE`，并将每个 port 名登记为 removed clock name |
| target 为 internal object | 默认 `MODIFY` 保留，并增加 hierarchy |
| 无 target 的 virtual clock | 默认 `MODIFY` 保留 |
| 指定 `--drop-internal-create-clock` | 删除 internal `create_clock` |

### 7.2 `create_generated_clock`

- 默认保留并映射 hierarchy。
- `create_generate_clock` 拼写变体按 generated clock 处理。
- 指定 `--drop-generated-clock` 时删除。

### 7.3 Clock 命名

默认命名规则：

```text
<instance_prefix>_<old_clock_name>
```

例如：

```text
--inst u_b/u_b1
refclk -> u_b_u_b1_refclk
```

所有受支持的 `get_clocks` 引用同步追随 rename map。

### 7.4 未使用 clock

保留的 `create_clock` / `create_generated_clock` 不会因为最终主 SDC 中暂时没有
其它约束引用该 clock 而删除。

### 7.5 Dangling clock

如果约束引用了已删除的 clock definition：

- 默认：该引用约束 `REMOVE`。
- `--strict`：该引用约束为 `ERROR`。
- 可通过 `--clock-mapping-file` 映射到 SoC clock。
- 可通过 `--allow-soc-clock` 放行已有 SoC clock 名称。

## 8. 固定 REMOVE 约束

### 8.1 Block boundary IO delay

- `set_input_delay`
- `set_output_delay`

原因：SoC interface timing 由顶层/接口规则负责。

### 8.2 SoC clock relationship 和 budget

- `set_clock_groups`
- `set_clock_uncertainty`
- `set_clock_transition`
- `set_propagated_clock`

原因：clock relationship、budget 和 propagation policy 由 SoC 顶层负责。

### 8.3 Synthesis network assumption

- `set_ideal_network`
- `set_ideal_latency`
- `set_ideal_transition`
- `set_dont_touch_network`

### 8.4 RC 和 back annotation

- `set_wire_load_model`
- `set_wire_load_mode`
- `set_resistance`
- `set_capacitance`
- `set_annotated_delay`
- `set_annotated_transition`
- `set_annotated_check`
- `read_parasitics`
- `read_spef`

原因：RC、SPEF 和 back annotation 由 SoC STA flow 负责。

### 8.5 MMMC、library 和 report policy

- `set_timing_derate`
- `set_dont_use`
- `group_path`

## 9. Port electrical 约束

以下命令直接涉及 `get_ports` 时 `REMOVE`：

- `set_drive`
- `set_driving_cell`
- `set_input_transition`
- `set_load`
- `set_fanout_load`
- `set_max_transition`
- `set_max_capacitance`
- `set_max_fanout`

原因：这些是 block boundary electrical assumption，不能直接带到 SoC instance pin。

如果命令只作用于 internal object，当前脚本将其放入 `unsupported.sdc`，不会直接
按 port electrical 规则删除。

## 10. Timing exception 和 mode 规则

| 命令 | internal object | 涉及 boundary `get_ports` |
| --- | --- | --- |
| `set_false_path` | hierarchy mapping 后保留 | `REMOVE`，交给 Stage30/SoC 层 |
| `set_multicycle_path` | hierarchy mapping 后保留 | 映射为 instance `get_pins`，`REVIEW_REQUIRED` |
| `set_max_delay` | hierarchy mapping 后保留 | 见 §10.1 |
| `set_min_delay` | hierarchy mapping 后保留 | 见 §10.1 |
| `set_case_analysis` | hierarchy mapping 后保留 | `REMOVE`，交给 scenario pre/SoC 层 |
| `set_disable_timing` | hierarchy mapping 后保留 | 无专门 boundary port 放行规则 |
| `set_data_check` | hierarchy mapping 后保留 | 无专门 boundary port ownership 规则 |
| `set_clock_gating_check` | hierarchy/clock mapping 后保留 | 无专门 boundary port ownership 规则 |
| `set_min_pulse_width` | hierarchy/clock mapping 后保留 | 无专门 boundary port ownership 规则 |
| `set_max_skew` | hierarchy/clock mapping 后保留 | 无专门 boundary port ownership 规则 |

### 10.1 `set_max_delay` / `set_min_delay`

以下标准 endpoint 组合会保留整条 path：

- `-from get_ports -to get_pins`
- `-from get_pins -to get_ports`
- `-from get_ports -to get_ports`

处理方式：

1. `get_ports` 改为 `get_pins <inst>/<port>`。
2. internal object 同步增加 `<inst>/`。
3. 完整命令进入主 SDC 顶部 `REVIEW_REQUIRED` 区块。
4. 不删除 `-from` 或 `-to`，保留原 path 结构。

如果命令含 boundary `get_ports`，但缺少完整 `-from/-to`，或 endpoint 组合无法被
脚本识别，则进入 boundary delay REMOVE 路径，交给 10/20/30 或 SoC 级复核。

### 10.2 `set_multicycle_path`

Stage1 不因 boundary port 删除 `set_multicycle_path`。`-from`、`-to`、`-through`
中的安全 `get_ports` 都映射为 instance `get_pins`，同时标记 `REVIEW_REQUIRED`。

## 11. Sense 规则

- 有明确 object access 的 `set_clock_sense` / `set_sense`：hierarchy mapping 后保留。
- 使用 `all_clocks`：`REMOVE`，原因是 SoC-level clock sense policy。
- 无 object access 或不支持的变体：`UNSUPPORTED`。

## 12. `set_units`

- 单位与 `--expect-units` 一致：检查完成后 `REMOVE`。
- 单位不一致：`ERROR`，转换状态为 `INVALID_OUTPUT`。
- 缺少单位值：`ERROR`。

默认期望：

```text
time=ns,capacitance=pF,resistance=ohm,voltage=V,current=mA
```

## 13. Tcl 和 unsupported 规则

以下命令默认不进入主 SDC，而是写入 `unsupported.sdc`：

- `source`
- `current_design`
- `current_instance`
- 带 object access 的 `proc/foreach/for/while/if/switch/eval/uplevel/regexp/regsub`
- `add_to_collection`
- `remove_from_collection`
- `filter_collection`
- `foreach_in_collection`
- `sizeof_collection`
- `get_object_name`
- 含 object access 的 Tcl `set` 变量赋值
- 未分类命令
- 无法安全映射的超长命令

纯控制 Tcl 且不含 object access 时，当前实现允许 `KEEP`，但会在 report 中警告。

## 14. 超长命令规则

默认单条命令阈值为 `1000000` 字符。超过阈值后不执行完整深度递归分析，而使用
shallow mapping：

- 处理明确的 `[get_pins ...]`、`[get_ports ...]` 等 bracket get command。
- 处理 safe `[list ...]` wrapper。
- 不安全 nested collection、复杂 Tcl、`get_clocks` 或 clock definition 进入
  `unsupported.sdc`。

该阈值可通过 `--oversize-command-chars` 调整。

## 15. REVIEW_REQUIRED 区块

需要人工复核但仍可 source 的命令放在主 SDC header 和 clock definition 之后、
普通约束之前：

```tcl
# !!! REVIEW_REQUIRED COMMANDS BEGIN !!!
# REVIEW_REQUIRED command_id=... line=... type=... reason=...
# REVIEW_NOTE: ...
<mapped command>
# !!! REVIEW_REQUIRED COMMANDS END !!!
```

典型来源：

- boundary max/min delay mapping。
- boundary multicycle path mapping。
- scoped/hierarchical collection mapping。
- shallow-mapped oversize command。

## 16. 输出文件

| 文件 | 用途 | 是否可 source |
| --- | --- | --- |
| `--out` | clean SoC-callable harden SDC | 是，状态非 `INVALID_OUTPUT` 时 |
| `--removed-out` | 明确删除的原始命令和原因 | 否 |
| `--unsupported-out` | 无法安全转换的命令 | 否 |
| `--modified-details` | MODIFY before/after 全量追溯 | 否 |
| `--report` | summary、计数、clock map、错误和一致性检查 | 否 |

## 17. 转换状态

### `CLEAN`

没有 unsupported、error 或 review-required 命令。

### `REVIEW_REQUIRED`

存在以下任一情况：

- `unsupported.sdc` 非空。
- 主 SDC 中存在 `REVIEW_REQUIRED` 命令。

默认情况下主 SDC 仍会生成并可用于 review STA。

### `INVALID_OUTPUT`

以下情况会抑制主 SDC body：

- `set_units` mismatch 或缺值。
- Tcl command boundary 结构错误。
- dangling clock consistency error。
- 其它 Pass3 consistency violation。
- `--strict` 下存在 unsupported command。
- 输入被识别为 Stage1 自身输出且未指定 `--force-reprocess`。

## 18. 关键运行选项

| 选项 | 作用 |
| --- | --- |
| `--inst` | SoC 下完整 harden instance path，支持多级 hierarchy |
| `--expect-units` | 指定预期单位 |
| `--drop-generated-clock` | 删除 generated clock |
| `--drop-internal-create-clock` | 删除 internal create_clock |
| `--no-prefix-clock-name` | 不增加 clock name instance prefix，不建议常规使用 |
| `--clock-mapping-file` | block clock -> SoC clock CSV mapping |
| `--allow-soc-clock` | 放行已有 SoC clock 名称，可重复指定 |
| `--strict` | unsupported 或一致性问题升级为 invalid/error |
| `--force-reprocess` | 明确允许再次处理 Stage1 输出 |
| `--full-detail` | report 输出完整明细 |
| `--detail-limit` | 非 full-detail 模式下的明细数量限制 |
| `--oversize-command-chars` | 超长命令 shallow mapping 阈值 |
| `-i` / `--batch-file` | 批处理 CSV，必需列为 `MODULE_NAME,INST_NAME,SDC_PATH` |

## 19. 当前实现注意项

以下内容是当前 `v2.3.2` 实现行为，不应在评审时忽略：

1. `set_clock_latency` 已有 reason 和 `--keep-kept-clock-source-latency` 相关代码，
   但当前没有加入固定 REMOVE command set。因此它实际进入 `unsupported.sdc`，
   `--keep-kept-clock-source-latency` 当前不会按设计生效。
2. `--map-port-case-analysis` / `--drop-port-case-analysis` 参数已被解析，但当前
   boundary `set_case_analysis ... [get_ports ...]` 始终按 REMOVE 规则处理；这两个
   参数目前不会改变分类结果。
3. Stage1 只做文本级 Tcl/SDC 解析和 mapping，不连接 netlist/STA database 验证
   instance、pin、clock 或 collection 是否真实存在。

## 20. STA signoff 检查

Stage1 完成后至少检查：

1. `Conversion status` 不是 `INVALID_OUTPUT`。
2. `unsupported.sdc` 中每条命令都有人工结论。
3. 主 SDC 顶部 `REVIEW_REQUIRED` 区块已逐条复核。
4. `removed.sdc` 中没有误删 harden-internal constraint。
5. clock rename map 与 SoC clock architecture 一致。
6. 没有 dangling clock reference。
7. `--inst` 对应真实完整 SoC instance path。
8. 在 linked PrimeTime design 中 source 主 SDC，并检查 object resolution、warning、
   exception coverage 和 clock propagation。
