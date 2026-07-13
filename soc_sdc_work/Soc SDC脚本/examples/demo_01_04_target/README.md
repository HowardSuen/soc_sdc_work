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

当前示例最终允许 04 报告保留 3 个方法学 warning：

- UART `set_input_transition` 和 `set_load` 使用 `stage=all/corner=all`，需要项目确认是否所有 view 共用。
- `clk_ref_pad` 已由 01 建 clock，但示例没有在 04 中继续设置外部 drive/slew；真实项目应补电气模型或明确 NA/basis。

这些 warning 不阻断生成；最终 report 的 error 数为 0。
