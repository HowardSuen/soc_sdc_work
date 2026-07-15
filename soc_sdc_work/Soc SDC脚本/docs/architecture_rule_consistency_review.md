# SoC SDC Architecture / Stage Rule Consistency Review

状态：规则目标已对齐；实现迁移待完成

## 已确认规则

- 00 是 integration port/connection machine artifact 的唯一生成 stage。
- `connection_inventory.csv` 按 bit 展开，01/04/10/20/30 不重新展开 range。
- 00~30 每个 stage 都显式输入 scenario。
- 同一 run root 可保存多个 scenario；manifest/pending/removed/machine artifact 按 scenario 隔离。
- accounting 默认开启；01/04/10/20/30 默认销账，02/03 不销账。
- harden SDC 支持 partial availability，strict gate 单独开启。
- 01 生成 common/scenario/assembled clock inventory；02/03/04/10/20/30 消费 assembled view。
- 03 输出 `relation_map/<scenario>.csv/.meta`，只做 clock-domain 语义检查。
- 10 只处理 feedthrough-adjacent SoC-visible direct edge；harden 内部 `fti -> fto` 不进入 SoC SDC。
- 10/20 按 00 `connection_id` 互斥，禁止 pair/chain end-to-end stitching。
- 20 默认 audit_only；只有 budget_output 需要 03 relation map 和正式 timing SDC。
- 20 输出 `20_middle/scenario/<scenario>/channel_inventory.csv` 及配套 digest/meta。
- 20 已完成 target runtime、audit/budget mode、partial/strict、10 ownership 排除和 scenario machine interface 回归。
- 30 正式生成前必须读取 current-scenario 10/20 inventory；缺少时只允许 candidate-only。
- feedthrough-related exception 只作用于 10 已 `route_to_30` 的同一 direct edge。

## 实现 Backlog

- 00 initializer/shared parser 与 target paths。
- 其余尚未完成 stage 的 scenario CLI 和 fixed target paths。
- 01/04 target 模式停止直接解析 integration range。
- 30 scenario candidate CSV。
- default accounting、partial SDC、multi-scenario 与 full-chain regression。
- regression 通过后重建内网包；旧包作废。

当前没有未裁决的规则决策。后续发现新的规则冲突时，应先在正式规则中修复，再更新本文件。
