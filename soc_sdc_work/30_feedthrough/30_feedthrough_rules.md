# 30_feedthrough.sdc 规则草案

本文先记录项目 feedthrough port 命名和识别规则，用于后续 `30_feedthrough.sdc` 规划、脚本筛选 harden 内部 feedthrough ports，以及辅助 20 exception 判断。

## 1. 目标

`30_feedthrough.sdc` 用于描述 SoC 中结构性 feedthrough path。

feedthrough path 指某个 harden/subsys 内部不作为该 path 的逻辑 source/destination，只负责把信号从 input port 穿到 output port，例如：

```text
u_src/req_o -> u_ft/fti_xxx -> u_ft/fto_xxx -> u_dst/req_i
```

30 的重点是识别和收口这些穿通段，让 10/20 不把 feedthrough harden 误当成真正的 timing endpoint。

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

同一 harden 内，feedthrough input/output 通过 `(index, base)` 配对：

```text
fti_0_mmn2gms_req_xxx <-> fto_0_mmn2gms_req_xxx
fti_mmn2gms_req_xxx   <-> fto_mmn2gms_req_xxx
```

## 4. 检查规则

### 4.1 error

以下情况应阻断自动生成 30：

- `fti_*` port 不是 input。
- `fto_*` port 不是 output。
- 同一 harden 内存在 `fti_<index>_<base>`，但找不到对应 `fto_<index>_<base>`。
- 同一 harden 内存在 `fto_<index>_<base>`，但找不到对应 `fti_<index>_<base>`。
- 同一 `(index, base)` 在同一 harden 内匹配到多个 input/output，且无法唯一配对。
- 多 harden feedthrough 链路中，index 未从第一个接收 harden 开始按 0、1、2 连续递增。
- 集成表单显示的连接顺序与 feedthrough index 顺序不一致。

### 4.2 warning

以下情况应 warning，要求 reviewer 确认：

- port 名以 `fti_` / `fto_` 开头，但 base 中没有明显 `<src>2<dst>` 结构。
- 多 harden feedthrough path 未使用数字 index。
- 单 harden feedthrough path 使用了数字 index，但 index 不是 0。
- req/resp 等反向路径的 index 与各自方向的接收顺序不匹配。
- base name 相同但 signal width / bus bit 展开不一致。
- 集成表单中出现疑似 feedthrough 连接，但 harden port 未按 `fti_` / `fto_` 命名。

## 5. 与其它 SDC 的边界

### 5.1 与 10_harden_x_if.sdc

10 处理普通 harden/subsys interface budget。

如果某个 harden 只是 feedthrough，不应把 feedthrough harden 当成真正 source/destination endpoint 生成普通 10 budget。10 应基于 30 的 feedthrough inventory，把 end-to-end source/destination 关系还原出来。

### 5.2 与 20_harden_to_harden_exception.sdc

20 处理 path exception / override。

如果 exception path 经过 feedthrough harden，20 必须引用 30 的 feedthrough 记录，并用 `through_collection` 显式锚定穿通段。不能只用隐式 endpoint pair 让脚本猜测路径是否经过 feedthrough。

### 5.3 与 04_soc_io_pads.sdc

连接 SoC top pad 的 feedthrough 需要先确认它是 pad-related 还是 harden-to-harden feedthrough。

pad 外部环境仍归 04；结构性穿通段归 30。

## 6. 暂不处理

第一版暂不自动处理：

- 不符合 `fti_` / `fto_` 命名规则的任意组合逻辑 feedthrough 自动推断。
- 经过 mux/isolation/clock gating 后才成立的 mode-specific feedthrough。
- 无法从集成表单确认连接顺序的多 hop feedthrough 自动 index 校验。
- feedthrough path 上的 exception 生成；这类仍由 20 表单 review。
