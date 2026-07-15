# 00 -> 30 Complex Full-Chain Case

入口：

```bash
python3 regression/run_full_chain_complex.py
```

脚本每次都会重建：

```text
regression/work/full_chain_00_to_30_complex/
```

## Case 拓扑

该 case 包含 5 个 harden：

```text
u_clkgen
u_dma
u_dpg
u_periph
u_ctrl
```

主要连接包括：

```text
ref/scan/peripheral clock pads -> u_clkgen -> 各 harden clock input

u_dma/data_o[*] -> u_dpg/fti_0_dma2periph_data[*]
[u_dpg harden internal, 不属于 SoC SDC]
u_dpg/fto_0_dma2periph_data[*] -> u_periph/data_i[*]

u_dma/async_req_o[*] -> u_dpg/fti_0_dma2periph_async_req[*]
[u_dpg harden internal, 不属于 SoC SDC]
u_dpg/fto_0_dma2periph_async_req[*] -> u_periph/async_req_i[*]

u_periph/resp_o[*] -> u_dma/resp_i[*]
u_dma/cfg_o[*] -> u_periph/cfg_i[*]
u_ctrl/ctrl_cfg_o[*] -> u_dpg/cfg_shadow_i[*]
```

## Stage 覆盖

- 00：解析集成表单，生成 bit-level connection inventory、当前 scenario harden SDC manifest 和 pending port 初始状态。
- 01：3 个 top clock、4 个 output/generated/forwarded clock、2 个 virtual clock。
- 02：`prects/ss_125` clock uncertainty、latency、transition budget。
- 03：core/bus 与 peripheral domain 的 asynchronous relationship，以及完整 relation map。
- 04：input/output pad environment、input transition 和 output load。
- 10：16 条 feedthrough-adjacent bit-level direct edge；data bit 0 ingress/egress 生成 max/min，其余多数使用 approved no-budget disposition，async egress bit 1 路由到 30。
- 20：`u_periph/resp_o[0] -> u_dma/resp_i[0]` 普通 direct functional budget。
- 30：
  - `u_dma/cfg_o[0] -> u_periph/cfg_i[0]` false path。
  - `u_ctrl/ctrl_cfg_o[0] -> u_dpg/cfg_shadow_i[0]` setup=2、hold=1 multicycle。
  - `u_dpg/fto_...async_req[1] -> u_periph/async_req_i[1]` direct-edge max/min override。

case 会阻断以下错误行为：

- 10 生成 harden 内部 `fti -> fto` constraint。
- 10/20 把两侧 direct edge 拼成 synthetic end-to-end channel。
- 20 输出或发布 10-owned edge。
- 30 使用 `-through` 穿越 harden 内部。
- 30 exception 与 active 10/20 normal budget 在同一 check 维度冲突。

## 关键产物

```text
01_result/common/01_soc_clocks.sdc
02_result/common/02_soc_clock_timing_prects_ss_125.sdc
03_result/common/03_soc_clock_groups.sdc
04_result/common/04_soc_io_pads.sdc
10_result/common/10_feedthrough.sdc
20_result/common/20_harden_x_if.sdc
30_result/common/30_harden_to_harden_exception.sdc

assembled/common_prects_ss_125_01_to_30.sdc
full_chain_summary.json
```

`assembled/common_prects_ss_125_01_to_30.sdc` 是按 01、02、03、04、10、20、30 顺序生成的 source preview。

## Runtime 契约

case 中的 00、01、02、03、04、10、20、30 都直接使用 `--run-root` target runtime。01–30 的拓扑和 owner 真源来自 00 及前序 stage 的机器产物，命令行不再重复传入原始集成表单；最终 assembled preview 按顺序 source 01–30 生成的 SDC，00 只负责初始化和机器接口，不生成需 source 的 SDC。

## Pending 说明

case 只批准一组有代表性的 budget/exception，不会为了让 pending 清零而给所有端口制造约束。最终 `full_chain_summary.json` 中保留的 pending 端口用于验证未决项仍然可见。
