# SoC SDC Project Context

本文档用于会话接力和快速恢复上下文。新开会话时建议先读本文件，再读 `soc_sdc_architecture.md` 和当前正在讨论的子目录规则文档。

## 1. 当前目标

建立一套面向 SoC 集成的 SDC 规划和生成脚本，优先服务综合、STA；SpyGlass CDC 主要复用 clock 定义和 clock group 信息，STA exception 语义不直接等同于 CDC/RDC 规则。

当前已展开：

- `01_soc_clocks`：从 harden SoC integration SDC 和集成表单中提取 SoC clock 定义。
- `02_soc_clock_timing`：从 stage 表单生成 resolved clock timing budget SDC。

后续待展开：

- `03_soc_clock_groups`
- `04_soc_io_pads`
- `10_harden_x_if`
- `20_harden_to_harden_exception`
- `30_feedthrough`

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
  extract_soc_01_clocks.py
02_soc_clock_timing/
  02_soc_clock_timing_form_spec.md
  extract_soc_02_clock_timing.py
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
python3 01_soc_clocks/extract_soc_01_clocks.py
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
python3 02_soc_clock_timing/extract_soc_02_clock_timing.py \
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

## 8. 当前验证状态

已做过的本地验证：

- 01 regression：从 demo harden SDC/表单生成 `common/01_soc_clocks.sdc` 和 `clock_inventory.csv`。
- 02 workbook 创建：缺表时自动创建 xlsx 并以 `NEW_FROM_01` 中断。
- 02 clock sync：缺 clock 自动补黄色行，stale clock 标红并中断。
- 02 scenario/stage/corner 输出：common 和 func 输出路径分离。
- 02 resolve：func 无专属行时使用 common fallback；func 有专属行时只 emit func 胜出行。
- 02 warnings：virtual/generated/propagated 相关误填均为 warning，不阻断。

## 9. 后续工作建议

优先顺序建议：

1. 继续 review/固化 `02_soc_clock_timing` 表单字段和脚本边界。
2. 规划 `03_soc_clock_groups.sdc` 的输入表单和生成机制。
3. 规划 `04_soc_io_pads.sdc`，明确 delay / drive / load / input transition 的归属和 scenario 拆分。
4. 再进入 harden interface、exception、feedthrough 等高风险文件。

每次重要规则变更后，应同步更新：

- `00_project_context.md`
- 对应子目录 spec/rules md
- `soc_sdc_architecture.md` 中的全局约定

