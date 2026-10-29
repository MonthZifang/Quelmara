# v3.06 — TCP 批量收发：`recv_all` / `recv_all_max` / `recv_exact`

- 日期：2026-10-29
- 任务：补库 —— 清掉 `07-gaps.md` §2「TCP 批量收发」行（只有单次 `tcp_send/recv`）
- 影响面：标准库（`std/net`）、测试（新增 `tests/t163_recvbatch.qma`）、文档

## 问题：`recv(conn, cap)` 不是"读完"

`std/net` 之前只有：

```quelmara
pub fn recv(conn: int, cap: int) -> str {
    return tcp_recv(conn, cap)
}
```

这是**一次** `recv()` 系统调用：内核缓冲区里有多少就返回多少，**可能远少于
`cap`**。把它当"读完"用会在三种常见情况下截断：

| 场景 | 后果 |
|---|---|
| 响应体 > 内核缓冲（默认 64–128 KB） | 只拿到第一块 |
| 慢链路 / 大包分片到达 | 拿到半个包 |
| 对端分多次 `send` | 只拿到第一次 |

HTTP/1.1 的 `Content-Length`、TLS 记录层、任何二进制协议都需要**精确读**
或**读到关闭**。这三件事要三个不同的语义，不能用一个函数凑。

## 实现：三个函数（纯 Quelmara，`std/net.qma`）

| 函数 | 语义 | 用在哪 |
|---|---|---|
| `recv_all(conn, chunk)` | 读到**对端关闭**（FIN），返回全部 | 无长度前缀的协议、`Connection: close` 响应 |
| `recv_all_max(conn, chunk, maxbytes)` | 同上，但到 `maxbytes` 就停 | 有上限的读取，防对端无限发 |
| `recv_exact(conn, n, chunk)` | 精确读 `n` 字节；提前关闭返回**已读到的部分** | `Content-Length`、TLS 记录 |

三者都用 `chunk` 控制单次 `tcp_recv` 的上限（建议 4096–65536），
`chunk <= 0` 时兜底 4096。

### `recv_exact` 的返回值语义是刻意的

读不满时**返回已读到的部分**，而不是空串或 fail-fast：

- 返回空串 → 调用方分不清"对端立刻关了"和"读了 3 字节后关了"；
- fail-fast → 短读在协议里是可恢复的（比如 HTTP 响应被截断，调用方要报
  "意外的 EOF"并带上已收到的字节数），不该杀进程。

调用方用 `len(result) == n` 判断是否读满。这与 `read()` 系统调用的
"短读"语义一致。

### 为什么不放到编译器内建里

这三个都是**纯控制流**（循环 + 累加），没有任何需要碰 syscall 的东西。
放进 `std/net.qma` 的好处：改语义不用重编编译器、能被 `doc std` 自动收录、
能在 AArch64 / C 后端上跟着走（内建要走两套发射层）。

## 验证

### 真实 socket 4 场景（`tests/t163_recvbatch.qma`）

每个场景都是"服务端 `accept` + 工作线程 `connect` 发数据 + 关闭"：

| # | 场景 | 断言 |
|---|---|---|
| 1 | `recv_exact(c, 20, 7)`，对端发 20 字节 | 读满 20，内容逐字节一致 |
| 2 | `recv_all(c, 5)`，对端发 23 字节 | 读全 23，内容一致（每次只读 5 也能读全） |
| 3 | `recv_all_max(c, 4, 6)`，对端发 16 字节 | 截断到 6 |
| 4 | `recv_exact(c, 100, 8)`，对端只发 3 字节 | 返回 3（**不挂死**） |

```
$ ./build/t163
recv batch ok
EXIT: 0
```

场景 2 是关键：`chunk = 5` 意味着一次只读 5 字节，而负载 23 字节——
如果实现只调一次 `tcp_recv` 就只能拿到 5 字节，循环才对。

场景 4 是防挂死的回归：`recv_exact` 要 100 字节但对端发 3 字节就关了，
必须靠 `tcp_recv` 返回空串退出循环，而不是等满 100。

### 回归

| 命令 | 结果 |
|---|---|
| `./build/t163`（native 后端） | `recv batch ok`，退出码 0 |
| `bash tests/run_native_tests.sh` | 见 `06-status.md` §1 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/net.qma` | 新增 `recv_all` / `recv_all_max` / `recv_exact`（各带 `///`） |
| `tests/t163_recvbatch.qma` | **新增**（4 场景真实 socket） |
| `docs/07-gaps.md` | §2「TCP 批量收发」❌ → ✅；§6 P1 第 6 项同步 |

## 已知边界 / 遗留

- **只做了接收侧**。发送侧仍是单次 `tcp_send`——真正的"批量发"要循环写
  直到写完全部字节（`send` 也可能短写）。这条没做，因为当前没有调用方
  需要（HTTP 请求都小），但缺口属实，已在文档里写明。
- **没有超时**。三个函数都靠 `tcp_recv` 阻塞。对端不发也不关时，
  `recv_all` 会一直等。要加超时得先给 `tcp_recv` 做 `SO_RCVTIMEO` 变体
  （`udp_recvfrom_to` 的做法可以照搬，但 TCP 侧要单独验证）。
- **`recv_all` 无总长上限**：对端一直发就一直读，内存会涨。需要上限用
  `recv_all_max`。
- **字符串拼接是 O(n²) 风险**：`out = out + part` 每次都重新分配。当前
  实现依赖 v1.3 起的"`+` 链融合成单次分配"优化；如果是很多次循环拼接，
  仍会有累积成本。大流量场景应改成 `vec[int]` 批量构造 + `str_from_bytes`
  （`std/hex` 就是这么做的）。这里保持简单是因为接收场景的循环次数少
  （每次 part 通常 4–64 KB）。
