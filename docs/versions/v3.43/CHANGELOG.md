# v3.43 — `tcp_peer_raw` 落地：覆盖率 45 → 46，手写 IR 的三个分配器陷阱

- 日期：2026-10-31
- 任务：用户要求"继续"；v3.42 之后最便宜的单点是 `std/net/addr.qma`（只差一个内建）
- 影响面：`bootstrap/qlmc/qlmc.qma`（`I_GETPEERNAME` 槽位 + 内建）、
  `tests/t187_qlmc_peer.qma`、`tests/peer_e2e_test.py`、`tests/run_win_tests.py`
- 覆盖率：**45 → 46**（基线已上调）
- 回归：PASS=359 → **360** FAIL=0 SKIP=0

## 做了什么

补上 `tcp_peer_raw(fd) -> str`：对端地址的 20 字节原始视图。

```
[0..1] 端口（网络序）  [2] family（2 = IPv4 / 23 = IPv6 / 0 = 未知）
[3]    0               [4..19] 地址（v4 占前 4 字节，其余 0）
```

配套：`I_USER` 20 → 21，新增 `I_GETPEERNAME = 20`。IAT 槽位那段循环
从写死 8 改成 `I_USER - I_WSASTART` 推导 —— 这样加符号时不用再手改数字。

`std/net/addr.qma` 之前**只差这一个内建**（`peer_raw` / `peer_ip` /
`peer_port` 三个公开函数都靠它），补上就通了。

## 三个分配器陷阱（都不是"写错一行"）

这个内建是**手写 IR**（`_lower_builtin` 里生成用户程序的指令序列），
和 v3.42 的 `tcp_send_n` 是同一类东西，但更长。踩了三个坑，
每个都表现为**不崩、不报错、只是结果不对或者挂死**：

### 1. `OP_ARG` + `OP_CALLRT RT_MEMCPY` ≠ memcpy

第一版这么写：

```quelmara
_ir_emit(fc, OP_ARG, 0, rd4, 0, 0)
_ir_emit(fc, OP_ARG, 0, nd4, 0, 1)
_ir_emit(fc, OP_ARG, 0, four, 0, 2)
_ir_emit(fc, OP_CALLRT, 0, 0, 0, RT_MEMCPY)
```

现象：进程**挂死** —— 不崩、不返回、无输出。

原因：`RT_MEMCPY` 的实参搬运**是 `OP_COPY` 自己做的**（它把实参落到
`r8`/`r9` 再 `call`）。用 `OP_ARG` 摆到 `rcx`/`rdx`/`r8` 再 `CALLRT`，
`__memcpy` 拿到的是错指针，往野地址拷 → 挂住。

正解：`_ir_emit(fc, OP_COPY, 0, dst, src, n)`，一行搞定。

### 2. 常量必须定义在分支之前

`dp = raw + 8` 里的 `eight` 一开始定义在 **v6 分支内部**。走 v4 时
那条 `OP_CONST` 根本不执行，`dp` 就是野指针 → `_bi_mem_str` 里
memcpy 到野地址 → 又是挂死。

这条是**手写 IR 特有的**：语言层有 SSA 和支配关系检查，编译器会报
"变量未定义"；手写 IR 没有，`_vnew` 出来的临时值**永远"存在"**，
只是没赋值就是垃圾。

### 3. 临时值不能跨 `OP_CALLRT` 存活

`raw` / `name` 是 `OP_CALLRT RT_ALLOC` 的返回值。分配器会把跨调用的
临时值溢出到帧槽（`cp[]` 前缀和判定），但**手写 IR 的形状稍变就可能
让它漏判** —— 于是 `raw` 留在 `R8`-`R11` 里，被下一次 `RT_ALLOC`
内部 clobber。

实测：只把 `alloc(24)` 改成 `alloc(28)`（别的一个字没动），
`raw` 和 `dp` 的差值就从 8 变成了 `raw=38666648, dp=1375656`。

正解：每个 alloc 之后**立刻把结果用掉或存好**，不让它跨越后续调用。

## 诊断方法（值得复用）

这些坑靠读代码看不出来，靠的是**插桩**：在 `_bi_tcp_peer_raw` 里
按节点插 `OP_PRINT`（打标记 101..107），跑一次就知道停在哪两条之间。

```
before peer_raw
101
102
103
104
105
106        ← 卡在 106 之后
```

106 对应 `OP_CALLRT RT_MEMCPY`，一次定位。**比读代码猜快一个数量级。**

## 验证：字节级差分

`tests/peer_e2e_test.py` 拉起服务端，用 Python 当客户端连接，
**用 `getsockname()` 拿到自己的本地端口**，然后逐字节核对：

```
[PASS] peer_raw 返回 20 字节
[PASS] 端口网络序正确：214 122（本地端口 54906）
[PASS] family == 2（AF_INET）
[PASS] b3 == 0（填充字节）
[PASS] 对端地址 127.0.0.1
=== t187 peer e2e: PASS=7 FAIL=0 ===
```

端口是随机分配的（54906），所以这条断言**真的在算**，不是写死的。

## 自举与回归

```
stage-2 可用且与 stage-1 逐字节等价（不动点成立）
PASS=360 FAIL=0 SKIP=0
parsediff 242 / qlmc_test 68
```

## 剩余缺口

覆盖率 46/70。按性价比排序，下一步候选：

| 内建 | 能解的模块 | 备注 |
|---|---|---|
| `tcp_listen6` | `std/net.qma` | 复用 `tcp_listen` 的结构，只是 AF_INET6 |
| `udp_open` / `udp_sendto` / `udp_sendto6` | `net/dns` / `net/udp` / `net/udp6` | 三个模块 |
| `thread_yield` | `net/reactor.qma` | 一条 `SwitchToThread` 或 `pause` |
| `wall_ms` | `std/log.qma` | `GetSystemTimeAsFileTime` |
| `file_size` | `std/staticfile.qma` | `GetFileSize` 已有 `_GetFileSize` 声明 |

`xmm_load` / `xmm_mov`（卡 aes / tls13 / tls_client）要看 SIMD 支持，
成本高；`args`（卡 cli）、`syscall`（卡 park_linux）各自单点。
