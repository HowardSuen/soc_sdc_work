# 04 阶段问题报告

## 04-INT-001：legacy target 产物契约阻塞 flat full-chain

**状态：** 已解决

**现象：**

旧版 04 target 回归要求以下 legacy 路径：

```text
00_middle/scenario/<scenario>/
01_middle/assembled/<scenario>/
```

当前 00、01 的单场景 runtime 输出为 flat 路径。旧版 04 直接执行时会报告缺少 manifest、connection inventory、assembled clock inventory 和 pending 产物。

**证据：**

- 旧入口固定读取 `00_middle/scenario/<scenario>/`、`01_middle/assembled/<scenario>/` 和 `00_middle/connection_inventory.csv`。
- full-chain 曾通过 `write_04_compatibility_artifacts()` 生成兼容产物。
- 旧 fixture 继续保留，用于验证 legacy target 兼容入口。

**影响：**

04 不能直接接入统一 flat contract，必须额外生成兼容的 legacy 产物。

**建议归属：**

04 主入口已迁移为直接读取：

```text
inputs/run_context.csv
inputs/required_views.csv
inputs/info_all.xlsx
inputs/port_*.xlsx
00_middle/harden_sdc_manifest.csv
01_middle/clock_inventory.csv
```

flat target 不再依赖 `connection_inventory.csv`、scenario 目录、pending 或 removed log，并发布 flat SDC、pad inventory、accounting delta、run-wide completion 和 required-view completion。旧目录 fixture 只进入显式检测到的 legacy 兼容路径。

验证：04 独立 regression 通过；00→04 flat 串联成功并被 10 upstream gate 接受。
