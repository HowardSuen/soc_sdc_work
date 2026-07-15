# Harden SoC Integration SDC Requirements

本文档约定 harden/IP 交付给 SoC 使用的 SDC 要求。目标是让 SoC 侧可以稳定生成和维护 SoC SDC，服务综合、STA；SpyGlass CDC 可主要复用 clock 定义和 async group，STA exception 与 CDC 语义不是 1:1，RDC 信息也不能依赖 SDC 完整表达。

## 0. 集成方式前提

harden 交付的 SoC integration SDC 必须显式声明 harden output clock。

- 凡是 harden output port 会作为 SoC 或其他 harden 的 clock source 使用，harden SoC integration SDC 必须显式声明该 output clock。
- 这条规则不依赖 harden 集成方式；无论 harden 是可见 wrapper/netlist、`.lib` / `.db` timing model，还是 blackbox，都必须遵守。
- 对于 `.lib` / `.db` timing model 或 blackbox harden，SoC 不能假设 clock 自动穿透 harden；显式 output clock 或 forwarded generated clock 是强制要求。

因此，所有会从 harden input clock 转发到 harden output clock 的路径，都应在 harden SoC integration SDC 中明确表达；SoC 侧不依赖工具自动穿透 harden 推断 output clock。

### 0.1 交付时间与 SoC 部分运行

本文定义的是 harden SDC **最终交付质量要求**，不要求所有 harden 在项目同一时刻完成交付。

- 项目推进中，SoC SDC 脚本允许基于已到位 harden SDC 进行 partial-availability 解析。
- 未到位 harden 在 availability manifest 中标记 `missing`，不得用近似文件或其它 scenario SDC 静默代替。
- missing 只表示交付进度，不表示该 harden 无 clock、无 timing contract 或无 exception。相关 SoC pending 项继续保留。
- 到 SoC SDC 正式交付/signoff 冻结时，必须启用 complete gate，并要求所有 required harden SDC 按本文完成交付。

因此 partial run 不降低 harden 最终交付标准；它只是允许 SoC 侧在交付过程中提前生成已具备证据的部分结果。

## 1. 交付文件定位

harden 应交付的是 **SoC integration SDC**，不是 harden 内部 signoff full SDC。

SoC integration SDC 只描述 SoC 集成需要知道的 harden 边界信息，例如：

- harden input clock port 的 clock 需求。
- harden output clock port 的 clock 声明。
- harden 边界上与 SoC 有关的 generated clock 关系。
- mode/test/scan/mbist 相关 clock 约束，按 scenario 拆分。

不建议在 SoC integration SDC 中包含 harden 内部 signoff 使用的大量 internal exception、internal path、internal hierarchy 约束。

## 2. Flatten / Normalized 要求

harden SoC integration SDC 最好是边界扁平化、语义明确的格式，便于 SoC 脚本直接提取。

要求如下：

- SDC 对象应尽量使用 harden port 级对象，例如 `[get_ports clk_in]`、`[get_ports pll_clk_out]`。
- 不依赖 harden 内部不可见层级，例如 `[get_pins u_pll/u_div/u_ff/Q]`。
- 不依赖复杂 Tcl proc、外部 include 链、环境变量或项目私有脚本。
- period、waveform、clock name 等关键信息应在文件内明确给出。
- 如果使用变量，变量应在同一文件或同一交付包的明确入口中定义，并有默认值。
- common、func、scan、mbist、gpio 等不同 scenario 的约束应拆分，避免全部混在一个文件里。
- harden SDC 默认使用 harden 自身 port 名，不写 SoC instance path；SoC 侧脚本负责映射为 `[get_pins u_harden_x/port]`。

这样要求的原因：

- SoC 侧需要把多个 harden 的 SDC 自动提取、重命名、去重并映射到 SoC 实例层级。
- harden 内部层级在 SoC 阶段通常不可见，或者只以 `.lib/.db` timing model 形式存在。
- 复杂 Tcl 和外部变量会让自动提取不稳定，且难以追溯 clock 来源。
- scenario 混写会导致 func/scan/mbist 约束互相污染，影响综合和 STA 判断。

## 3. Clock 声明规则

harden 输出 clock 的声明应按以下规则选择 `create_generated_clock` 或 `create_clock`。

### 3.1 能明确追溯 source/master 的 harden output clock

优先使用 `create_generated_clock`。

适用场景：

- LVDS/ref clock 进入 harden 后，由 PLL/divider/mux 产生 output clock。
- clock 经过 harden 内部固定分频、倍频、相位变换后输出。
- source/master clock 在 harden 边界上能明确对应到某个 input port。

示例：

```tcl
create_generated_clock \
  -name pll_work_clk \
  -source [get_ports lvds_clk_p] \
  [get_ports pll_work_clk_out]
```

如果当前 scenario 下倍频/分频关系确定，可以写明：

```tcl
create_generated_clock \
  -name pll_work_clk \
  -source [get_ports lvds_clk_p] \
  -multiply_by 8 \
  [get_ports pll_work_clk_out]
```

理由：

- `period` 只说明 clock 多快；`source/master` 关系说明该 clock 从哪里来。
- STA 需要 clock relationship 来判断两个 clock 是否 related，以及是否应进行跨 clock timing check。
- SoC 侧生成 `01_soc_clocks.sdc` 时，可以把 harden output clock 作为 clock producer 映射到 SoC 实例输出 pin。

要求：

- `create_generated_clock` 必须带可解析的 `-source`，且 source 应尽量指向 harden 边界 input port。
- 若 PLL 配置/相位关系未定，或该 output clock 在 SoC 当前 scenario 下应作为独立 root，应使用 `create_clock`，不要交付缺少 `-source` 的 `create_generated_clock`。

### 3.2 PLL 配置/相位关系未定，或集成文档要求作为独立 root

暂用 `create_clock`。

适用场景：

- PLL 倍频/分频比例可配置，当前 SoC scenario 尚未确定。
- PLL output 和 ref clock 的确定相位关系不参与 SoC STA 分析。
- harden 交付文档或 timing model 明确要求 SoC 在 output pin 上创建 primary clock。

示例：

```tcl
create_clock \
  -name pll_work_clk \
  -period 1.000 \
  [get_ports pll_work_clk_out]
```

理由：

- 不应把硬件支持的最大倍频比率写成通用 `-multiply_by`。
- `-multiply_by` 表示当前 scenario 下真实 clock relationship，不表示 PLL 能力上限。
- 在配置未定时，先用 `create_clock -period` 可以给综合/STA 一个明确 timing 目标，后续再升级为 `create_generated_clock`。

### 3.3 仅穿透/转发 clock

使用 `create_generated_clock -combinational`。

适用场景：

- clock 进入 harden 后不变频、不分频，只经过 buffer、mux 的固定通路或简单转发后输出。
- harden output clock 和 input clock 本质上是同一个 clock path 的边界延续。

示例：

```tcl
create_generated_clock \
  -name forwarded_clk \
  -source [get_ports work_clk_in] \
  -combinational \
  [get_ports work_clk_out]
```

理由：

- SoC STA 需要知道 output clock 与 input clock 是同源转发关系。
- 直接在 output 端重新 `create_clock` 会把 forwarded clock 误建成新的 primary clock root，可能破坏 clock relationship。

## 4. SoC 侧使用原则

SoC 侧生成 `01_result/common/01_soc_clocks.sdc` 和对应 scenario overlay 时，按 clock producer 建 clock：

- SoC 顶层 pad/ref/test 输入 clock：在 SoC 顶层 port 或明确 clock root 上 `create_clock`。
- harden output clock：主要从 harden SoC integration SDC 提取，并映射到 SoC 实例 output pin。
- harden input clock：主要用于校验连接来源和 period 是否匹配，一般不在每个 input pin 上重复 `create_clock`。

对于连接表中描述的：

```text
Harden A clock output -> Harden B clock input
```

SoC 侧在 A 的 output 端建 clock，B 的 input clock 声明用于一致性检查，不在 B input 上重复创建 primary clock。

如果 B 会把 input clock 再输出给 SoC 或其他 harden，B 的 SoC integration SDC 也必须显式交付对应 output/forwarded generated clock。

## 5. Harden 需要提供的 clock 信息

每个 harden 至少应提供：

- input clock port 列表：port name、clock name、period/waveform、用途。
- output clock port 列表：port name、clock name、period/waveform、是否供 SoC 或其他 harden 使用。
- output clock 的 source/master：对应哪个 input clock，或说明其为独立 clock root。
- PLL/divider/mux/bypass 信息：不同 scenario 下的选择和配置。
- scan/mbist/test clock 信息：建议拆成单独 scenario SDC。
- 对每个 output clock 说明推荐使用 `create_generated_clock` 还是 `create_clock`，以及理由。
