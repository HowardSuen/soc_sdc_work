# SoC SDC Project Context

本文档用于会话接力和快速恢复上下文。新开会话时建议先读本文件，再读 `soc_sdc_architecture.md` 和当前正在讨论的子目录规则文档。

## 1. 当前目标

建立一套面向 SoC 集成的 SDC 规划和生成脚本，优先服务综合、STA；SpyGlass CDC 主要复用 clock 定义和 clock group 信息，STA exception 语义不直接等同于 CDC/RDC 规则。

当前已展开：

- `01_soc_clocks`：从 harden SoC integration SDC 和集成表单中提取 SoC clock 定义。
- `02_soc_clock_timing`：从 stage 表单生成 resolved clock timing budget SDC。
- `03_soc_clock_groups`：已建立 clock relationship / clock group 规则，并实现第一版生成脚本。
- `04_soc_io_pads`：已建立 IO/pad 约束归集规则，并实现第一版生成脚本。
- `10_harden_x_if`：已建立 harden/subsys interface channel budget 规则，并实现第一版生成脚本。
- `20_harden_to_harden_exception`：已建立 harden-to-harden exception 规则草案，待后续脚本实现。
- `30_feedthrough`：已记录项目 feedthrough port 命名/识别规则草案，待后续完整展开。

后续待展开：

- `30_feedthrough` 完整 SDC 生成规则和脚本

## 2. 仓库和目录

本地工作目录：

```text
/Users/howard/Documents/33_vcspyglass sdc处理/soc_sdc_work
```

Git 远端：

```text
git@github.com:HowardSuen/soc_sdc_work.git
```

当前主要文件：

```text
soc_sdc_architecture.md
harden_sdc_requirements.md
01_soc_clocks/
  01_soc_clocks_extraction_rules.md
  01_extract_soc_clocks.py
02_soc_clock_timing/
  02_soc_clock_timing_form_spec.md
  02_extract_soc_clock_timing.py
03_soc_clock_groups/
  03_soc_clock_groups_rules.md
  03_extract_soc_clock_groups.py
04_soc_io_pads/
  04_soc_io_pads_rules.md
  04_extract_soc_io_pads.py
10_harden_x_if/
  10_harden_x_if_rules.md
  10_extract_harden_x_if.py
20_harden_to_harden_exception/
  20_harden_to_harden_exception_rules.md
30_feedthrough/
  30_feedthrough_rules.md
demo_01_02/
  # 01/02 demo 和验证材料
```

## 3. SoC SDC 架构约定

当前结构：

```text
common/
  01_soc_clocks.sdc
  02_soc_clock_timing_<stage>_<corner>.sdc
  03_soc_clock_groups.sdc
  04_soc_io_pads.sdc
  10_harden_x_if.sdc
  20_harden_to_harden_exception.sdc
  30_feedthrough.sdc

scenarios/
  func.sdc
  <scenario>_clock_timing_<stage>_<corner>.sdc
  dft_scan.sdc
  mbist.sdc
  gpio_in.sdc
  gpio_out.sdc
```

当前第一阶段按 `func` 单一模式推进，但文档和 02 脚本已经按 `scenario/stage/corner` 预留。

## 4. Harden SDC 交付前提

harden output clock 强制显式声明：

- 只要 harden output port 会作为 SoC 或其他 harden 的 clock source 使用，harden SoC integration SDC 必须声明对应 output clock。
- 不依赖 SoC 工具自动穿透 harden 推断 output clock。
- harden SDC 最好是 flatten/normalized 形式，便于 SoC 脚本直接提取。

clock 声明建议：

- 能追溯 source/master 的 output clock：优先 `create_generated_clock`。
- PLL 配置或相位关系未定、或需作为独立 root：暂用 `create_clock`。
- 仅转发/穿透 clock：`create_generated_clock -combinational`。

## 5. 01_soc_clocks 当前规则

`01_soc_clocks` 只负责创建 SoC clock object：

- 所有 `create_clock` / `create_generated_clock`，包括 virtual clock，归属 01。
- 不放 clock timing budget、clock group、IO delay、exception。
- harden input clock 只有来自 top/pad 或 virtual source 时才作为 SoC root 保留。
- harden output clock 会提升到 SoC instance 层级。
- clock name 采用稳定命名，避免不同 harden instance 重名。

脚本：

```bash
python3 01_soc_clocks/01_extract_soc_clocks.py
```

已实现的关键防护：

- 不根据名字自动 skip scan/mbist/test clock，只 warning。
- 不假设 clock target 是最后一个 `get_ports`，区分 target 和 `-source`。
- generated clock 缺少可解析 `-source` 时 error。
- 输出 `clock_inventory.csv`，供 02 使用。

## 6. 02_soc_clock_timing 当前规则

02 只负责 clock timing budget：

- `set_clock_uncertainty`
- `set_clock_latency`
- `set_clock_transition`
- `set_propagated_clock`
- derate/OCV hook 记录或后续生成入口

02 不创建 clock，也不放 clock group、IO、exception。

表单按 stage 独立：

```text
02_soc_clock_timing_budget_<stage>.xlsx
```

脚本按三维选择生成：

```bash
python3 02_soc_clock_timing/02_extract_soc_clock_timing.py \
  -scenario func \
  -stage prects \
  -corner ss_125
```

输出规则：

```text
scenario = common:
  common/02_soc_clock_timing_<stage>_<corner>.sdc

scenario != common:
  scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc
```

核心原则：

- SDC 没有 corner 条件化能力，不能把多个 corner 拍进同一个 02 SDC。
- SDC 没有 scenario 条件化能力，不能把 func/scan 等 scenario timing 混进 common。
- `scenario != common` 时，脚本在生成阶段 resolve 唯一胜出行：
  - 当前具体 scenario 行优先。
  - 没有具体 scenario 行时使用 common fallback。
  - 同一 clock/stage/corner 最终只 emit 一个胜出行。
  - 具体 scenario 行 `apply = no` 也算胜出，可显式压掉 common 默认。
- Stage 3 只 source 一个 resolved effective 02 文件，不能再 common + scenario 双 source 覆盖。

第一版 warning 检查：

- `virtual_clock` 胜出行填写 `network_latency_*` 或 `transition_*`：warning。
- generated 类 clock 胜出行填写 `source_latency_*`：warning。
- `propagated = yes` 同时填写 `network_latency_*` 或 `transition_*`：warning。

## 7. SDC 装配顺序

推荐装配阶段：

```text
Stage 1: scenario pre-setup
Stage 2: clock creation
Stage 3: clock timing budget
Stage 4: clock relationship
Stage 5: IO/pad environment
Stage 6: harden/interface/feedthrough
Stage 7: path exception
```

Stage 3 特别规则：

- `scenario = common`：只 source `common/02_soc_clock_timing_<stage>_<corner>.sdc`。
- `scenario != common`：只 source `scenarios/<scenario>_clock_timing_<stage>_<corner>.sdc`。
- 不要在 scenario run 中再叠加 source common 02。

其它 stage 暂按 common + scenario 叠加模型规划，但不能依赖 source 顺序覆盖冲突。

## 8. 03_soc_clock_groups 当前规则

03 只表达 clock relationship，不定义 clock，也不做 path exception。

主要生成：

```tcl
set_clock_groups -asynchronous
set_clock_groups -logically_exclusive
set_clock_groups -physically_exclusive
```

核心原则：

- 当前 03 采用默认 synchronous + 显式枚举 async/exclusive；未被 clock group 覆盖的 clock pair 仍按默认同步分析。
- 01 的 `clock_inventory.csv` 可提供 clock genealogy 和候选证据，但不能直接自动生成 clock group。
- 同 root source 不必然同步，不同 root source 不必然异步。
- common 03 只放所有 mode 都成立的关系。
- scenario 03 只追加该 scenario 下才成立的关系。
- 如果 common group 在某个 scenario 不成立，应下沉到 scenario，而不是靠 scenario 覆盖。
- async group 必须有架构依据和 CDC/RDC signoff 依据，不能用于消 timing violation。
- clock mux 互斥关系必须先选方法学：per-scenario view 用 `set_case_analysis` 单腿传播；all-mode/merged view 不打单腿 case，才用 `logically_exclusive`。
- 同一个 mux/clock pair 不应同时用 `set_case_analysis` 和 `logically_exclusive` 表达同一层互斥语义。
- group 成员必须按 domain closure 检查：表单中的 clock 作为 seed/member，脚本用 01 genealogy 展开 generated/forwarded descendants，输出 effective group。
- 不默认依赖工具自动让 generated clock 继承 master 的 group 关系；descendant 若不进入同 group，必须显式排除并说明。
- `logically_exclusive` 的 descendant 展开要特别 review；mux 汇合点 clock 可能被 01 genealogy 归到单条腿，脚本必须报告并要求人工确认或排除。
- 03 脚本需要按 `common + 当前 scenario` 建立 assembled-view pair relation map，做跨 rule/跨 scenario 冲突检测。
- 03 必须输出 coverage report：每个 clock 的 group 参与情况、03 genealogy `tree_root` pair 覆盖情况、未覆盖且仍默认 synchronous 的跨 tree clock pair 清单。01 `root_source` 仅作诊断参考。
- coverage report 第一版不建模 `set_case_analysis`；被 scenario case 掉的 clock 可能仍显示为 uncovered，后续可结合 pre-setup 过滤。
- 多个 domain 两两 async/exclusive 时应放在同一条多 group rule；拆成 A/B、A/C 不会自动覆盖 B/C。
- 03 表单的 group 列应采用可变 `group_<number>_clocks`，脚本自动识别，不固定为 4 组上限。

当前文件：

```text
03_soc_clock_groups/03_soc_clock_groups_rules.md
03_soc_clock_groups/03_extract_soc_clock_groups.py
```

## 9. 10_harden_x_if 当前规则

10 表达 SoC 视角下 harden/subsys 边界的普通 interface timing budget。

核心原则：

- 10 不按 SDC 命令名字划分，而按约束意图划分；普通 interface budget 归 10，exception 性质的语义改写归 20。
- 10 不是逐条 SDC 转换，而是按集成表单建立 interface channel 后归并生成。
- harden input 的 `-from` 和 harden output 的 `-to` 优先从集成表单推断。
- 第一版 10 只生成 reviewed `set_max_delay` / `set_min_delay`，不直接生成 instance pin 上的 `set_input_delay` / `set_output_delay`。
- 10 生成的 max/min 是 boundary-to-boundary channel datapath budget，不是常规 clock-relative input/output delay 的等价替换。
- 只有 `budget_model = interconnect_budget` 或 reviewer 重新推导/人工给出 `converted_max` 时，才允许生成；同一 channel 两端 interconnect max 不一致时取更紧值 `min(all_available_max_candidates)`。
- `set_min_delay` 需要 min/sign 语义 review 后才能 emit；若两端 min 已归一为同一语义，取更紧的 `max(all_reviewed_normalized_min_candidates)`。
- 若可见 netlist/timing model 已让普通 STA 覆盖 reg-to-reg path，10 默认不额外生成 `set_max_delay -datapath_only`。
- 接 SoC top pad 的约束归 04；clock 相关归 01/02/03；exception 归 20；feedthrough 归 30。

当前文件：

```text
10_harden_x_if/10_harden_x_if_rules.md
```

## 10. 20_harden_to_harden_exception 当前规则草案

20 表达 harden/subsys 之间的 path-level exception / override，不表达普通 interface budget。

核心原则：

- 20 的判断依据是约束意图，不是命令名字；`set_max_delay` / `set_min_delay` 若表达普通 boundary budget 归 10，若表达 exception/override 语义才归 20。
- harden port 上没有 `set_input_delay` / `set_output_delay` 只是候选信号，不是自动生成 20 exception 的充分条件。
- 一条 path 进入 20，需要同时满足：没有普通 10 timing budget 语义、有明确 exception/override 语义、有可审查依据。
- 20 应参考集成表单、harden SDC port timing/exception 证据、10 channel inventory/budget 状态、03 clock relationship 和人工协议/架构信息。
- 20 不替代 03；整个 clock domain 的 async/exclusive 关系优先放 03，20 只表达更窄的 path-level exception。
- 20 必须是 object-level exception；clock-to-clock 约束归 03，不应在 20 中直接用 `[get_clocks ...]`。
- 03 async 与 20 `set_false_path` 通常冗余；但 03 async 与 20 `set_max_delay -datapath_only` 可以是 CDC/handshake 建模的互补关系。
- 单独的 `set_max_delay -datapath_only` 不会去掉常规 setup/hold；异步路径通常需要 03 async/exclusive 或其它 CDC clock relation 配套。
- CDC/异步 handshake 的传播窗口约束通常使用 `set_max_delay -datapath_only` 与 `set_min_delay -datapath_only` 成对表达；同 clock / related clock 的功能性 override 默认不使用 `-datapath_only`。
- 03 async 与 20 max/min 是否能同时生效必须用目标 STA 工具验证；若 `set_clock_groups -asynchronous` 遮蔽 path-level max/min，需要采用项目确认的等效写法。
- 20 不替代 10；同一 assembled view 中同一路径的 active 10 普通 budget 与 20 exception 不能在同一 check 维度上冲突。active 10 要按 10 `interface_budget` 中 apply/approved/emit/value 的实际生成状态判断，不是只看 channel 是否存在。
- 10/20 overlap 要按 check 维度判断；10 max 与 20 min 可以带依据共存，10 max 与 20 max 或 false_path 覆盖才是冲突。
- 跨 clock multicycle 必须明确 `-start` / `-end` 参照、周期比、边沿关系和 hold 推导；multicycle 默认要求 setup/hold 成对。
- 经过 feedthrough harden 的多跳路径必须先由 30 建模，20 只在明确 through/related_30 锚点后追加 exception。
- 同一路径多个 exception 不能依赖工具 priority 静默裁决；false path、max/min、multicycle overlap 必须拆分或报错。
- reset false path 必须说明 recovery/removal 如何另行保证。
- common 20 只放所有 mode 都成立的 exception；scan/mbist/test/gpio/case-dependent exception 下沉 scenario。
- 第一版脚本应保守：只归集 candidate，approved 规则才生成，不能自动把 missing timing candidate 提升为 exception。

当前文件：

```text
20_harden_to_harden_exception/20_harden_to_harden_exception_rules.md
```

## 11. 30_feedthrough 当前规则草案

30 当前先记录项目 feedthrough port 命名和识别规则，用于后续脚本筛选 harden 内部 feedthrough ports。

核心原则：

- feedthrough input 使用 `fti_` 前缀，feedthrough output 使用 `fto_` 前缀。
- 单 hop 示例：`fti_mmn2gms_req_xxx` / `fto_mmn2gms_req_xxx`。
- 多 hop 示例：`fti_0_mmn2gms_req_xxx` / `fto_0_mmn2gms_req_xxx`，`fti_1_mmn2gms_req_xxx` / `fto_1_mmn2gms_req_xxx`。
- index 按每条 end-to-end feedthrough 链路、每个方向独立计数，从第一个接收 feedthrough 信号的 harden 开始从 0 递增。
- req/resp 反向路径各自独立编号；同一个 harden 在不同方向链路中的 index 可能不同。
- 同一 harden 内通过 `(index, base)` 配对 `fti` / `fto`。
- 20 若经过 feedthrough harden，必须引用 30 的 feedthrough 记录，并用 `through_collection` 锚定穿通段。

当前文件：

```text
30_feedthrough/30_feedthrough_rules.md
```

## 12. 当前验证状态

已做过的本地验证：

- 01 regression：从 demo harden SDC/表单生成 `common/01_soc_clocks.sdc` 和 `clock_inventory.csv`。
- 02 workbook 创建：缺表时自动创建 xlsx 并以 `NEW_FROM_01` 中断。
- 02 clock sync：缺 clock 自动补黄色行，stale clock 标红并中断。
- 02 scenario/stage/corner 输出：common 和 func 输出路径分离。
- 02 resolve：func 无专属行时使用 common fallback；func 有专属行时只 emit func 胜出行。
- 02 warnings：virtual/generated/propagated 相关误填均为 warning，不阻断。
- 01->02->03->04->10 complex regression 已串联通过：覆盖 clock 提取、clock timing budget、clock group、IO pad common/scenario/view-specific、10 interface auto-resolve、harden_to_fabric coverage 和 async 阻断。

## 13. 后续工作建议

优先顺序建议：

1. 进入 `30_feedthrough.sdc` 等剩余高风险文件的规则规划。
2. 后续将 20/30 纳入同一套 complex regression。
3. 后续按项目反馈继续收敛 01/02/03/04 脚本检查项。

每次重要规则变更后，应同步更新：

- `00_project_context.md`
- 对应子目录 spec/rules md
- `soc_sdc_architecture.md` 中的全局约定
