# 10_feedthrough.sdc 规则说明

本文记录项目 feedthrough port 命名和识别规则，用于后续 `10_feedthrough.sdc` 规划、脚本筛选 harden 内部 feedthrough ports，以及辅助 20/30 判断。

## 1. 目标

`10_feedthrough.sdc` 用于描述 SoC 中结构性 feedthrough path。

feedthrough path 指某个 harden/subsys 内部不作为该 path 的逻辑 source/destination，只负责把信号从 input port 穿到 output port，例如：

```text
u_src/req_o -> u_ft/fti_xxx -> u_ft/fto_xxx -> u_dst/req_i
```

10 的重点是识别和收口这些穿通段，让 20/30 不把 feedthrough harden 误当成真正的 timing endpoint。

## 2. Port 命名规则

### 2.1 单个 harden feedthrough

如果信号从 source harden 到 destination harden，中间经过一个 feedthrough harden，则 feedthrough harden 的 input/output port 使用：

```verilog
input  fti_<src>2<dst>_<signal_name>;
output fto_<src>2<dst>_<signal_name>;
```

示例：

```verilog
input  fti_mmn2gms_req_xxx;
output fto_mmn2gms_req_xxx;
```

规则：

- `fti_` 表示 feedthrough input。
- `fto_` 表示 feedthrough output。
- `<src>2<dst>` 保留 end-to-end source/destination harden 名称，不写当前 feedthrough harden 名称。
- `req` / `resp` 等方向语义应保留在 signal name 中，方便区分正向/反向链路。

### 2.2 多个 harden feedthrough

如果同一条 end-to-end path 穿过多个 feedthrough harden，则在 `fti_` / `fto_` 后增加 hop index：

```verilog
input  fti_<index>_<src>2<dst>_<signal_name>;
output fto_<index>_<src>2<dst>_<signal_name>;
```

示例：

```verilog
input  fti_0_mmn2gms_req_xxx;
output fto_0_mmn2gms_req_xxx;

input  fti_1_mmn2gms_req_xxx;
output fto_1_mmn2gms_req_xxx;
```

### 2.3 hop index 计数规则

hop index 按每条 end-to-end feedthrough 链路、每个方向独立计数。

计数从第一个接收 feedthrough 信号的 harden 开始，从 0 递增。

示例：

```text
req:  harden_a -> harden_b -> harden_c -> harden_d
resp: harden_d -> harden_c -> harden_b -> harden_a
```

则：

```text
req path:
  harden_b: fti_0_a2d_req_xxx / fto_0_a2d_req_xxx
  harden_c: fti_1_a2d_req_xxx / fto_1_a2d_req_xxx

resp path:
  harden_c: fti_0_d2a_resp_xxx / fto_0_d2a_resp_xxx
  harden_b: fti_1_d2a_resp_xxx / fto_1_d2a_resp_xxx
```

因此，同一个 harden 在不同方向链路中的 index 可能不同。index 不是 harden 的全局编号。

## 3. 脚本识别规则

第一版脚本可用以下模式识别 feedthrough port：

```text
fti_<base>
fto_<base>
fti_<index>_<base>
fto_<index>_<base>
```

其中：

```text
index = 非负整数，可选
base  = <src>2<dst>_<signal_name>
```

建议解析正则：

```text
^fti_(?:(\d+)_)?(.+)$
^fto_(?:(\d+)_)?(.+)$
```

同一 harden 内，feedthrough input/output 先通过 `(index, base)` 识别 name-level 候选：

```text
fti_0_mmn2gms_req_xxx <-> fto_0_mmn2gms_req_xxx
fti_mmn2gms_req_xxx   <-> fto_mmn2gms_req_xxx
```

### 3.1 bit-level 配对

10 继承 `00_harden_port_inventory` 的 canonical bit key。vector feedthrough port 必须在机器处理中展开到 bit：

```text
fti_0_mmn2gms_req_data[0] <-> fto_0_mmn2gms_req_data[0]
fti_0_mmn2gms_req_data[1] <-> fto_0_mmn2gms_req_data[1]
```

因此实际配对 key 是：

```text
(feedthrough_instance, index, base, bit_index)
```

scalar port 的 `bit_index` 为空。若集成表单或 RTL 只给出 `fti_*[7:0]` / `fto_*[7:0]`，脚本必须按 00 range 展开规则建立 8 个 segment；位宽、bit order 或 `fti`/`fto` bit 对应关系不明确时为 error。10 不允许用一个整 bus feedthrough record 代表部分 bit。

## 4. feedthrough inventory

10 必须输出结构化 `feedthrough_inventory.csv`，作为 20/30 的共享输入。30 中的 `related_10_feedthrough_id` 必须引用这里产生的稳定 id，不能由 30 自己重新猜。10 的输入侧/输出侧 direct edge 来自 00 `connection_inventory.csv`；10 只补充 feedthrough harden 内部 `fti -> fto` segment，不替代 00 direct edge 表。

### 4.1 feedthrough_id schema

每个 harden 内的一对 `fti` / `fto` 形成一个 feedthrough segment，并生成一个稳定 id：

```text
FT_<feedthrough_instance>_<hop_index>_<base>
```

规则：

- `<feedthrough_instance>` 使用 SoC 集成层 instance 名，例如 `u_dpg`；层级分隔符 `/`、`.` 和其它非 `[A-Za-z0-9_]` 字符归一成 `_`。
- `<hop_index>` 使用解析到的数字 index；单 hop 且未显式写 index 时使用 `single`，不要留空。
- `<base>` 使用 `fti_` / `fto_` 后解析出的 base，同样做字符归一。
- vector bit 信息必须进入 id 后缀，例如 `_bit7`；同一个 id 不应同时代表全 bus 和部分 bit。

示例：

```text
u_dpg/fti_0_mmn2gms_req_xxx + u_dpg/fto_0_mmn2gms_req_xxx
  -> FT_u_dpg_0_mmn2gms_req_xxx

u_dpg/fti_mmn2gms_req_xxx + u_dpg/fto_mmn2gms_req_xxx
  -> FT_u_dpg_single_mmn2gms_req_xxx

u_dpg/fti_0_mmn2gms_req_data[7] + u_dpg/fto_0_mmn2gms_req_data[7]
  -> FT_u_dpg_0_mmn2gms_req_data_bit7
```

### 4.2 inventory columns

`feedthrough_inventory.csv` 建议至少包含：

```text
feedthrough_id
scenario
feedthrough_instance
feedthrough_module
hop_index
base
src_name
dst_name
signal_name
fti_port
fto_port
fti_endpoint
fto_endpoint
bit_index
chain_id
hop_order
upstream_endpoint
downstream_endpoint
validation_status
basis
note
```

说明：

- `feedthrough_id` 是 30 的 `related_10_feedthrough_id` 的唯一生产者。
- `fti_port` / `fto_port` 使用 00 canonical key；vector bit 写 `port[index]`。
- `bit_index` 记录当前 segment 对应的 bit；scalar 留空。
- `chain_id` 用于描述同一 end-to-end feedthrough 链路，例如 `CHAIN_mmn2gms_req_xxx`；多 hop path 可用 `chain_id + hop_order` 校验顺序。
- `upstream_endpoint` / `downstream_endpoint` 来自集成表单，用于把穿通段接回真实 source/destination。
- `validation_status` 至少区分 `matched` / `unpaired` / `order_mismatch` / `needs_review`。

如果 30 的 exception path 经过多个 feedthrough segment，`related_10_feedthrough_id` 应填写按 path 顺序排列的 id 列表，例如：

```text
FT_u_b_0_a2d_req_xxx,FT_u_c_1_a2d_req_xxx
```

30 同时必须用 `through_collection` 锚定对应穿通 pin；id 负责指向 10 inventory，through 负责约束实际对象。

### 4.3 脚本输入和输出

第一版脚本为 `10_extract_feedthrough.py`，默认在运行目录读取：

```text
info_all.xlsx
port_*.xlsx / ports_*.xlsx
00_harden_port_inventory/connection_inventory.csv
00_harden_port_inventory/pending/*.ports
```

默认输出：

```text
feedthrough_inventory.csv
common/10_feedthrough.sdc
feedthrough_check_report_common.txt
00_harden_port_inventory/removed_log/10_feedthrough.removed
```

`common/10_feedthrough.sdc` 第一版只作为结构性 feedthrough manifest，不生成 timing budget 或 exception 命令。普通 interface budget 仍归 20；feedthrough path 上的 false path / max-min override 仍归 30。

10 v1 只支持 `scenario = common`。feedthrough 是结构性穿通描述，通常 mode-independent；经过 mux/isolation/clock gating 后才成立的 mode-specific feedthrough 已列为第一版暂不处理。若运行时指定非 common scenario，脚本应报 error，不生成 `scenarios/<scenario>_feedthrough.sdc`。`feedthrough_inventory.csv` 中的 `scenario` 列第一版固定为 `common`。

10 的识别是确定性的命名和连接检查流程，第一版不维护单独的 approval workbook。脚本会把所有可配对 segment 写入 `feedthrough_inventory.csv`，其中：

- `validation_status = matched`：`fti` / `fto` 已按 bit 配对，且进入/离开 feedthrough harden 的 00 connection edge 可确认。
- `validation_status = needs_review`：`fti` / `fto` 名字可配对，但上游/下游 connection edge 缺失、多重 fanout、或 00 edge 自身不是 matched 状态。

只有 `validation_status = matched` 的 segment 可以从 pending 中删除对应 `fti` / `fto` canonical bit key，并写入 `10_feedthrough.removed`。`needs_review` segment 虽然进入 inventory/report，但不能消账，相关 port 必须继续留在 pending，直到 00 connection 或人工裁决补齐。

## 5. 检查规则

### 5.1 error

以下情况应阻断自动生成 10：

- `fti_*` port 不是 input。
- `fto_*` port 不是 output。
- `fti_*` / `fto_*` 被登记为 inout。10 v1 不自动把 inout 解释成某一方向；这类端口必须先在集成表单/RTL wrapper 中拆成明确的 directional `fti` input 和 `fto` output，或保持 pending/needs_review。
- 运行 10 时指定 `scenario != common`。
- 同一 harden 内存在 `fti_<index>_<base>`，但找不到对应 `fto_<index>_<base>`。
- 同一 harden 内存在 `fto_<index>_<base>`，但找不到对应 `fti_<index>_<base>`。
- 同一 `(index, base, bit_index)` 在同一 harden 内匹配到多个 input/output，且无法唯一配对。
- vector feedthrough 的 `fti` / `fto` 位宽、bit index 或 bit order 不一致。
- 生成整 bus `feedthrough_id` 试图代表多个 bit，或 30 可引用的 id 缺少必要 bit 后缀。
- 多 harden feedthrough 链路中，index 未从第一个接收 harden 开始按 0、1、2 连续递增。
- 集成表单显示的连接顺序与 feedthrough index 顺序不一致。
- 生成的 `feedthrough_id` 不唯一。
- inventory 中同一个 `feedthrough_id` 对应多个不同 `(instance, index, base, bit_index)`。
- 脚本试图删除 pending 中不存在的 `fti` / `fto` canonical bit key，且 `removed_log` 中没有 previous_removed 记录说明该 bit 已被早期 stage 消费。

### 5.2 warning

以下情况应 warning，要求 reviewer 确认：

- port 名以 `fti_` / `fto_` 开头，但 base 中没有明显 `<src>2<dst>` 结构。
- 多 harden feedthrough path 未使用数字 index。
- 单 harden feedthrough path 使用了数字 index，但 index 不是 0。
- req/resp 等反向路径的 index 与各自方向的接收顺序不匹配。
- base name 相同但 signal width / bus bit 展开不一致。
- 集成表单中出现疑似 feedthrough 连接，但 harden port 未按 `fti_` / `fto_` 命名。
- `fti` / `fto` 名字可配对，但 00 `connection_inventory.csv` 缺少进入 `fti` 或离开 `fto` 的 edge；该 segment 应标为 `needs_review`，不能从 pending 消账。
- 相关 00 connection edge 的 `validation_status` 不是 `matched` / `ok` / `valid`，或同一 `fti` / `fto` 出现多条进入/离开 edge。
- 30 引用的 `related_10_feedthrough_id` 不在当前 10 inventory 中；这应在 30 侧升为 error。

## 6. 与其它 SDC 的边界

### 6.1 与 20_harden_x_if.sdc

20 处理普通 harden/subsys interface budget。

如果某个 harden 只是 feedthrough，不应把 feedthrough harden 当成真正 source/destination endpoint 生成普通 20 budget。20 应基于 10 的 bit-level feedthrough inventory，把 end-to-end source/destination 关系还原出来。

### 6.2 与 30_harden_to_harden_exception.sdc

30 处理 path exception / override。

如果 exception path 经过 feedthrough harden，30 必须引用 10 的 `feedthrough_inventory.csv` 中的 bit-level `feedthrough_id`，并用 `through_collection` 显式锚定穿通段。不能只用隐式 endpoint pair 让脚本猜测路径是否经过 feedthrough。

### 6.3 与 04_soc_io_pads.sdc

连接 SoC top pad 的 feedthrough 需要先确认它是 pad-related 还是 harden-to-harden feedthrough。

pad 外部环境仍归 04；结构性穿通段归 10。

## 7. 暂不处理

第一版暂不自动处理：

- 不符合 `fti_` / `fto_` 命名规则的任意组合逻辑 feedthrough 自动推断。
- 经过 mux/isolation/clock gating 后才成立的 mode-specific feedthrough。
- 无法从集成表单确认连接顺序的多 hop feedthrough 自动 index 校验。
- feedthrough path 上的 exception 生成；这类仍由 30 表单 review。
