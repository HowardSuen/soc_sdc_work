# 04 阶段问题报告

## 04-F001：`route_to_30` 未发布为 30 可消费的 canonical pad owner inventory

- 状态：已解决
- 严重度：高
- 原发布阻断：是
- 解决日期：2026-07-20

### 原因

04 的 flat runtime 只发布 topology-oriented pad CSV，没有把 review workbook 中的 `route_to_30` 决策、完整 `pad_id`、exact endpoint 和 machine digest 合并到正式 inventory。30 因此得到空的 `related_04_pad_id`，并按 fail-closed 规则拒绝 exception。

### 修复结果

- 每个 exact pad bit 发布一条 canonical owner row；
- `pad_id` 使用 exact direct-edge tuple 的完整 lowercase SHA-256，`connection_id=CONN_<pad_id>`；
- 发布 exact top/harden 与 src/dst endpoint、view、structure/source/machine digest；
- 保留人工 `pad_disposition/apply/review_status/owner/basis/intent/reviewer/review_date`；
- machine identity 变化时使旧审批失效；
- `route_to_30` 可保留 04 electrical command，但不能与 normal IO delay 或 04 exception 共存；
- flat 04 不再生成 `set_false_path`，exception 由 30 使用 `related_04_pad_id` 接管；
- 04 accounting 以 resolved pad disposition 为最终 gate，`route_to_30/pending` 不销账；
- 多 view inventory 保留非当前 required view，移除当前 view stale row，并让所有 required-view completion 认证最终 inventory digest；
- header-only pad inventory 仍累计 authenticated required view，真实 `all/all` view 可被显式选择；
- prior inventory 必须通过 canonical schema、meta provenance 和 SHA-256 校验，禁止把被篡改的旧 CSV 重新签名；
- prior view completion 重新校验实际 SDC 与 00/01 upstream artifact digest，上游变化会使旧 view 失效；
- 当前 view 也要求 00/01 completion 存在、complete 且 provenance/structure/01 clock digest 有效；
- top pad exact bit fanout 时每条 edge 单独发布/accounting，normal timing 会阻止任一 fanout edge 错误 route；
- range/subrange SDC evidence 自动拆成 exact-bit review row，任一 bit 未映射时整条 fail closed；
- input/output direction 必须匹配 integration，inout/GPIO 必须选择本 run 的 input/output effective direction，且 `Inout Name` accounting 不会在重跑时被误当连接。
- inout `route_to_30` 必须显式选择 effective direction；当前仅允许 input-oriented top→harden handoff，output-oriented route fail closed，避免向 30 发布反向 endpoint。

### 回归证据

通过：

```text
04 complex regression: PASS
01-04 preflight matrix: PASS
04->30 pad central matrix: PASS
10 feedthrough latest-runtime regression: PASS
00->30 full-chain complex case: PASS
```

`04->30` 正向 case 已确认：

```text
related_04_pad_id == pad_id
set_false_path -from [get_ports {...}] -to [get_pins {.../...}]
04 route target 未写 Used、未进入 04 accounting delta
```

04 complex regression 另覆盖：header-only 三 required view、显式 `all/all`、top-bit 1→2 fanout、range/subrange exact-bit expansion、unmapped-bit fail closed、inout effective direction与 route orientation、缺失/未完成 upstream completion、mixed-view constrained/route 顺序无关，以及 prior upstream digest 失效/恢复。

统一 `run_preflight_all.py` 中两次 full-chain、byte/Tcl determinism、01-04、04-30、10-20、30 matrix 和 production source integrity 均为 PASS。统一结果仍因独立的 `30-F001` upstream SDC digest gate stress case 为 FAIL；该问题不属于 04-F001。

## 04-INT-001：legacy target 产物契约阻塞 flat full-chain

- 状态：已解决（既有修复保持）
- 结果：flat target 直接读取统一 `inputs/00_middle/01_middle` contract；legacy fixture 仅走兼容入口。
