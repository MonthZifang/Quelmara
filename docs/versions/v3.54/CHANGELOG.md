# v3.54 — `tcp_connect` + 两个 `_to` 变体；覆盖率 54 → 56

- 日期：2026-10-31
- 任务：用户要求"继续"；补 `tcp_connect` 系列内建
- 影响面：`bootstrap/qlmc/qlmc.qma`（3 个新 IAT 槽 + 3 个内建 + `_sext32`）、
  `tests/t198_qlmc_tcp_connect.qma`、`tests/tcp_connect_e2e_test.py`、
  `tests/run_win_tests.py`、`tools/dev/qlmc_coverage.py`（`BASELINE` 54 → 56）
- 覆盖率：**54 → 56**（`std/net` + `std/net/udp6`）
- 回归：PASS=368 → **369** FAIL=0 SKIP=0

## 三个内建，一条链

`std/net` 和 `std/net/udp6` 的缺口是**串起来的**，补一个就前移到下一个：

```
tcp_connect → tcp_send_n_to → tcp_recv_to → ✓
```

所以这一版一次补三个。前两个是新的，第三个是既有模式的复制。

## 新增的 IAT 槽

`I_USER` 从 30 推到 **33**：

| 常量 | 值 | 符号 |
|---|---|---|
| `I_GETADDRINFO` | 30 | `getaddrinfo` |
| `I_FREEADDRINFO` | 31 | `freeaddrinfo` |
| `I_CONNECT` | 32 | `connect` |

**必须紧接 `I_SETSOCKOPT`(29)**：`build_rdata` 里那条
`while wi < I_USER - I_WSASTART` 的循环靠 18..32 连续来推槽位。

`IAT_NAME_N` 也同步 30 → 33（`irdump` 显示符号名用）。

## `tcp_connect`：DNS + 链表遍历

比 `tcp_listen` 复杂得多。算法逐句对齐 stage-0 的 `__tcp_connect`：

```
WSAStartup(0x202, &wsa)
hints = alloc(48)，清零
  hints[4]  = 0   (AF_UNSPEC —— v4/v6 都要)
  hints[8]  = 1   (SOCK_STREAM)
  hints[12] = 6   (IPPROTO_TCP)
res = alloc(8); *res = 0
getaddrinfo(host, 0, hints, res)
head = *res; ai = head
循环:
  fam=ai[4] sty=ai[8] pro=ai[12] alen=ai[16]
  sin = alloc(32); memcpy(sin, ai[32], alen)
  sin[2] = port>>8; sin[3] = port&255      ← 覆盖端口（网络序）
  cs = socket(fam, sty, pro)
  if cs == -1: goto retry
  if connect(cs, sin, alen) == -1: closesocket(cs); goto retry
  freeaddrinfo(head); return cs
retry:
  ai = ai[40]                              ← ai_next
  if ai == 0: fail
  goto 循环
```

**为什么要沿 `ai_next` 回退**：Windows 对 `"localhost"` 常先给 `::1`。
若服务端只监听 v4，不回溯就等于把原来能用的路径弄丢。

### 两个 Win64 陷阱

1. **`int` 返回值必须符号扩展**。`SOCKET_ERROR` 是 -1，但 `int` 返回只写
   `eax`，在 64 位寄存器里表现为 `0x00000000FFFFFFFF` —— 直接和 -1 比
   **永远不等**。新增 `_sext32`（`shl 32` / `sar 32`）统一处理。
2. **`getaddrinfo` 成功是 0、失败是 EAI_\* 正数**，判 `!= 0` 而不是 `< 0`。

## 两个 `_to` 变体

`tcp_send_n_to(fd, ptr, n, ms)` 与 `tcp_recv_to(fd, cap, ms)` 都是
`setsockopt(超时)` + 原内建：

| 内建 | 选项 | 值 |
|---|---|---|
| `tcp_send_n_to` | `SO_SNDTIMEO` | `0x1005` |
| `tcp_recv_to` | `SO_RCVTIMEO` | `0x1006` |

**差 1，写错就静默变成"设了接收超时"，发送照样无限阻塞。**

两者语义不同（与 stage-0 同口径）：

* `tcp_send_n_to` 失败 **fail-fast**（发不出去是调用方的 bug）；
* `tcp_recv_to` 超时/出错**返回空串**（"对端暂时没发"是可恢复结果，
  服务端事件循环靠它继续转）。

`tcp_recv_to` 是 v3.08 的健壮性修复：没有它时对端不发东西会让 `recv`
无限阻塞，实测 12 秒都不返回（退出码 124）。

## 测试

`tests/t198_qlmc_tcp_connect.qma` + `tests/tcp_connect_e2e_test.py`，
注册为 `case_tcp_connect_e2e()`。PASS=7。

Python 端**同时监听 v4 与 v6** —— 只监听 v4 会让 `localhost` 走回退路径，
那是另一个测试点，不该混进这条（第一版就是这么写的，结果 exe 在
`tcp_send` 上 exit 7，排查了一会儿才发现是测试夹具的问题，不是实现的）。

| 断言 | 抓什么 |
|---|---|
| `v4_ok=1` | IPv4 字面量直连 |
| `v4_echo=echo:ping` | `tcp_send_n_to` + `tcp_recv_to` 收发 |
| `v4_timeout_empty=1` | `tcp_recv_to` 对端不发时返回空串（不挂死） |
| `dns_ok=1` | `localhost` 走 DNS + `ai_next` 回退 |
| `dns_echo=echo:pong` | DNS 连接收发 |
| `badhost_neg=1` | 不存在的域名被拦下 |

## 覆盖率

`std/` **54 → 56**：`std/net.qma` 与 `std/net/udp6.qma` 解锁。
`BASELINE` 已上调到 56。

剩余 14 个模块的缺口分布：

```
2  缺内建: xmm_load           (std/aes, std/tls13)
2  未知类型 TlsClientResult   (std/httpc_net, std/tls_net)
1  缺内建: args               (std/cli)
1  vec[vec[T]] §7.18          (std/csv)
1  泛型 [T: Ord]              (std/gen)
1  函数重复定义 _fail         (std/http)
1  函数重复定义 _get          (std/logfile)
1  for k in map §7.40         (std/kv)
1  map 方法不全               (std/set)
1  缺内建: syscall            (std/park_linux)
1  结构体字面量含方法调用      (std/session)
1  缺内建: xmm_mov            (std/tls_client)
```

下一个最大单点是 `xmm_load`（挡 2 个），但那需要 SIMD 加载支持，
与前面几个内建不是同一量级的改动。

## 自举

30/30 组等价 + 不动点成立。stage-2 产物 633344 B（v3.53 是 601600 B），
仍在 `ARENA_CAP = 4 MB` 的余量内。
