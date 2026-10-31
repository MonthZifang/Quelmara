# v3.49 — `udp_sendto` / `udp_sendto6` 落地（收 §7.36）；覆盖率 49 → 51

- 日期：2026-10-31
- 任务：用户要求"继续"；收口 v3.44 遗留的 `udp_sendto` `0xC0000005`（§7.36）
- 影响面：`bootstrap/qlmc/qlmc.qma`（`_bi_udp_sendto` 重写 + 词法器 `\xNN`
  + `_iat_names_str` / `_iat_name`）、`tests/t192_qlmc_udp_send.qma`、
  `tests/udp_send_e2e_test.py`、`tests/t193_qlmc_udp6_send.qma`、
  `tests/udp6_send_e2e_test.py`、`tests/run_win_tests.py`、
  `tools/dev/qlmc_coverage.py`（`BASELINE` 49 → 51）
- 覆盖率：**49 → 51**（`std/net/udp` 与 `std/net/udp6` 同时解锁）
- 回归：PASS=365 → **367** FAIL=0 SKIP=0

## 三个缺陷，一个症状

v3.44 的 `udp_sendto` 一调用就 `0xC0000005`，当时查了约 40 轮没定位。
这版找到的是**三个互相独立的缺陷**，前两个叠在一起产生那个 AV。

### 缺陷 1：`OP_ADDRF` 把普通整数当指针 —— 这才是 `0xC0000005`

`OP_ADDRF` 的语义是 `dst = a 的**值** + imm`（把 `a` 当基址）。v3.44 的
v4 分支写的是：

```quelmara
_ir_emit(fc, OP_ADDRF, s4, ip, 0, 0)     // ip 是普通 u32
_ir_emit(fc, OP_COPY, 0, d4, s4, 4)      // 从地址 0x0100007F 读 4 字节
```

`sinp` 是 `RT_ALLOC` 出来的指针，所以 `ADDRF sinp, 4` 是对的；但 `ip` 是
**值**（`127 | (1 << 24)` = `0x0100007F`），`ADDRF ip, 0` 生成
`lea rX, [rIp]` = 地址 `0x0100007F`，随后 `COPY` 从那里读就必然 AV。

这解释了 v3.44 的一个困惑："崩在 `_emit_call_args` 之前、连函数体第一条
`OP_PRINT` 都打不出来" —— 崩溃点其实在构造 `sockaddr` 的**地址段**，
比 `sendto` 调用更早。当时一直盯着 `CALLIAT`/`STKFREE` 看，方向反了。

修法：

```quelmara
_ir_emit(fc, OP_ADDRF, d4, sinp, 0, 4)   // base 必须是**变量**
_ir_emit(fc, OP_STORE, 0, d4, ip, 8)     // ip 当值写进去
```

写 8 字节无害：`sockaddr_in` 的 8..11 本来就是必须为 0 的填充区，
而 u32 地址的高 32 位恒为 0。

### 缺陷 2：端口写错偏移 + 字节序拆反 —— 不崩，只是静默发错端口

第一版两个端口字节都写到偏移 `+2`（`[3]` 恒为 0），`39482 = 0x9A3A`
变成 `0x9A00 = 39424`。第二版改对了偏移，却把 `hbe` 拆成
`[2] = hbe>>8`、`[3] = hbe&255` —— 但 `hbe = htons(port)` **已经**是
"按小端存下去正好是网络序"的 u16（`0x9A3A → 0x3A9A`），再拆就反转成
`0x3A 0x9A` = 14986。

**这条最危险**：`sendto` 照样返回发送字节数（`n=3`），程序不崩、返回值
正确，唯一症状是"包根本没到对端"。**没有差分对端就永远抓不到。**

修法：整字 `STORE` 到偏移 2，不拆字节。

### 缺陷 3：词法器不认 `\xNN`（v6 测试暴露的）

qlmc 的词法器原来只认 `\" \\ \n \t`，`\xNN` 落进 `else` 分支只取
`chr(e)` —— `\` 被吞掉只剩 `x`，`"\x00"` 变成 `"x00"`（3 个字符）。
16 字节 IPv6 地址字面量因此膨胀成 48 字符（`rawlen=48`），
`udp_sendto6` 收到垃圾地址。

按 stage-0 的 `qlm_index.py` 补上：`\xNN` 取两个十六进制数字作原始字节，
任一非法就退回字面量 `x`（与 stage-0 的 `except ValueError: pass` 同口径）。

## 诊断工具：`irdump` 补上 IAT 符号名

v3.45 建的 `irdump` 只显示 `CALLIAT imm=21`，得自己数槽位才知道是
`sendto`。这版新增 `_iat_names_str()` / `_iat_name(n)`（30 条），
`CALLIAT` 现在显示成：

```
CALLIAT  dst=118(r8)  a=0  b=0  imm=27(sendto)
```

**一加上就直接看见了铁证**：`ADDRF dst=112(s3) a=78` 里的 `78` 是
`CONST 16777343`（`0x0100007F`），而不是一个 alloc 出来的指针。
缺陷 1 是靠这一眼定位的，不是靠猜。

## 测试

### `tests/t192_qlmc_udp_send.qma` + `tests/udp_send_e2e_test.py`

PASS=10 FAIL=0。覆盖：

- 裸内建 `udp_sendto` 发三个 datagram，Python 端（标准库 socket，
  独立实现）逐字节比对内容；
- 同一 fd 复用（不是一次性）；
- 库层 `std/net/udp` 的 `udp_send_str`（文本地址 → `udp_parse_ip` → 发送）；
- 地址非法时返回 -1（不崩、也不是 0）；
- Python 端回一个，exe 用 `udp_recvfrom_to` 收 —— 证明同一 fd 双向可用。

### `tests/t193_qlmc_udp6_send.qma` + `tests/udp6_send_e2e_test.py`

PASS=7 FAIL=0。v6 与 v4 共用 `_bi_udp_sendto`，只有 family(23)、
sockaddr 28 字节、地址 16 字节整块拷贝三处不同。这条顺带钉住缺陷 3
（`rawlen=16`）。

**注意**：t193 不 `import std.net.udp6` —— 它依赖 `std.net`，而
`std.net` 里的 `tcp_connect` 内建 qlmc 还没实现（§7.39）。直接调裸内建，
与 t188 同口径，不让无关缺口挡住。

## 覆盖率

`std/` **49 → 51**：

- `std/net/udp.qma`（`udp_send_str` 里的 `udp_sendto` 调用点）
- `std/net/udp6.qma`（`udp_send6` 里的 `udp_sendto6` 调用点）

`tools/dev/qlmc_coverage.py` 的 `BASELINE` 同步上调到 51。

## 方法教训

1. **诊断工具必须建在假设之前**。v3.45 写了 `irdump`，但只做到"能看 IR"；
   这版补上符号名和"能看到实际发射的 imm"才真正有用。重编 qlmc 要 2 分钟，
   40 轮 ≈ 80 分钟纯等待。
2. **返回值正确的 bug 比崩溃更难抓**。缺陷 2 不崩、返回 3，只有独立实现的
   对端逐字节比对才暴露。差分测试不是锦上添花。
3. **`OP_ADDRF` / `OP_STORE` / `OP_COPY` 的 base 操作数必须是指针**。
   IR 层面完全合法（`ADDRF dst, a, 0`），只有运行时才炸，且炸在离出错点
   很远的地方。这是 v3.49 之后要反复检查的一类错误。
