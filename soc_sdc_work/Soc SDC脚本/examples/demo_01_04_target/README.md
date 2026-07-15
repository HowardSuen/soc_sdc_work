# 01 -> 04 Target Runtime 串联示例

本示例在同一个 target-layout run root 中串联运行：

```text
01_soc_clocks
  -> 01 assembled clock inventory + clock SDC
02_soc_clock_timing
  -> pre-CTS clock uncertainty/latency/transition SDC
03_soc_clock_groups
  -> system clock tree 与 GPIO virtual clock asynchronous 关系
04_soc_io_pads
  -> UART RX/TX input/output delay、input slew 和 output load
```

示例拓扑：

```text
clk_ref_pad -> u_harden_a/clk_ref -> PLL -> u_harden_a/clk_pll_o
                                        -> u_harden_b/clk_i -> clk_o

uart_rx_pad -> u_harden_b/uart_rx_i
uart_tx_pad <- u_harden_b/uart_tx_o
```

运行：

```bash
python3 run_demo.py
```

脚本会重建 `run/`，自动完成 02/03/04 首次表单生成、示例审核填写和第二次正式生成。最终装配预览位于：

```text
run/assembled/common_prects_ss_125.sdc
```

该 preview 按顺序 source 01、02、03、04 的最终 SDC。`run/chain_summary.txt` 汇总 clock、clock relation、IO 命令和 pending 消账结果。

当前示例最终允许 04 报告保留 2 个方法学 warning：

- UART `set_input_transition` 和 `set_load` 使用 `stage=all/corner=all`，需要项目确认是否所有 view 共用。

这些 warning 不阻断生成；最终 report 的 error 数为 0。

## 01 -> 10 串联扩展

`run_demo_01_to_10.py` 在同一个 target run root 上增加一组 bit-level feedthrough direct edge：

```text
u_harden_a/data_o[0] -> u_harden_b/fti_payload[3]
u_harden_b/fto_payload[3] -> u_harden_a/data_i[0]
```

它依次运行 01、02、03、04、10，自动完成各 review gate，并检查 10 只生成 ingress/egress direct-edge max/min，不生成 harden 内部 `fti -> fto` 或 synthetic end-to-end path：

```bash
python3 run_demo_01_to_10.py
```
