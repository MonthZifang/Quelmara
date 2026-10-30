# v3.21 — reactor 双栈：`WSASocketW(2, ...)` → `(23, ...)` + `IPV6_V6ONLY=0`

- 日期：2026-10-30
- 任务：用户要求"继续"；`07-gaps.md` P1 剩「reactor 双栈」（UDP v6 已在 v3.20 做完）
- 影响面：标准库（`std/net/reactor`）、测试（新增 `tests/reactor_dualstack_test.py`）、文档

## 问题：IOCP reactor 只接 IPv4

`std/net/reactor.qma` 的监听 socket 是：

```quelmara
let s = _WSASocketW(2, 1, 0, 0, 0, 1)     // AF_INET = 2
let sinb = mem_alloc(16)                   // sockaddr_in 16 字节
mem_store64(sinb, 0, ((lo | hi) << 16) | 2)
_bind(s, sinb, 16)
```

只接 v4。所有跑在 reactor 上的东西（`std/http` 的路由/中间件、
`examples/http_router.qma`、ws / sse）都继承这个限制。

## 改动

```quelmara
let s = _WSASocketW(23, 1, 0, 0, 0, 1)    // AF_INET6 = 23（Windows 的值）
let v6only = mem_alloc(4)
mem_store64(v6only, 0, 0)
_setsockopt(s, 41, 27, v6only, 4)          // IPPROTO_IPV6 / IPV6_V6ONLY = 0
let sinb = mem_alloc(32)                   // sockaddr_in6 28 字节
mem_store64(sinb, 0, ((lo | hi) << 16) | 23)
_bind(s, sinb, 28)
```

三处关键值都来自 `tcp_listen6`（v2.07 就做对了的那条路）：

| 项 | 值 | 说明 |
|---|---|---|
| `AF_INET6` | **23** | **Windows 是 23，Linux 是 10** —— v3.20 刚在 UDP 上踩过同一个坑 |
| `IPPROTO_IPV6` | 41 | setsockopt 的 level |
| `IPV6_V6ONLY` | 27 | 选项号；**Windows 默认 1（只接 v6）**，必须显式置 0 |
| `sockaddr_in6` | 28 B | family@0-1、port@2-3、flowinfo@4-7、addr@8-23、scope@24-27 |

`sin6_addr` 全零 = `::` 通配地址：双栈 socket 因此同时接所有接口的 v4 与 v6。

**为什么不开两个 socket**（v4 + v6 各一个）：双栈 socket 是 Win32 的标准做法；
两个 socket 要处理端口冲突（`SO_REUSEADDR`）、"哪个先 bind"、以及 IOCP 完成键
要不要区分来源 —— 复杂度远高于收益。

## 验证

**新增夹具 `tests/reactor_dualstack_test.py`**（3 项断言）：

| 组 | 内容 | 判据 |
|---|---|---|
| `[1]` | 服务就绪 | 6 s 内 `127.0.0.1:8092` 可连 |
| `[2]` | **IPv4** | `GET /` → `HTTP/1.1 200 OK`（双栈不破坏 v4） |
| `[3]` | **IPv6** | `GET /` → `HTTP/1.1 200 OK`（本版新增的能力） |

**这个夹具对改造前的代码是红的**（实测）：

```
  [PASS] IPv4 127.0.0.1 -> HTTP/1.1 200 OK
  [FAIL] IPv6 连接失败：[WinError 10061] 由于目标计算机积极拒绝，无法连接。（双栈没生效？）
```

改造后：

```
  [PASS] 服务就绪（8092）
  [PASS] IPv4 127.0.0.1 -> HTTP/1.1 200 OK
  [PASS] IPv6 ::1 -> HTTP/1.1 200 OK
reactor_dualstack ok（3 项断言）
```

| 命令 | 结果 |
|---|---|
| `python tests/http_router_test.py` | **`http_router ok（25 项断言）`** —— 双栈改造没破坏任何路由/中间件/chunked 语义 |
| `python tests/reactor_dualstack_test.py` | `reactor_dualstack ok（3 项断言）` |
| `python tests/run_win_tests.py` | 见下表 |

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `std/net/reactor.qma` | 监听 socket 改 AF_INET6 双栈（`WSASocketW(23)` + `IPV6_V6ONLY=0` + 28B `sockaddr_in6`） |
| `tests/reactor_dualstack_test.py` | 新增：v4 + v6 同端口验证（端口占用返回 2 记 SKIP） |
| `tests/run_win_tests.py` | `[11]` 段新增 `test_reactor_dualstack()` |
| `docs/07-gaps.md` | P1 第 6 条 reactor 双栈 → ✅；IPv6 行更新 |
| `docs/06-status.md` | 新增 §3.71 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.21.0 |

## 已知边界 / 遗留

- **只改了监听侧**。`accept` 出来的连接在对端地址上表现为 `::ffff:a.b.c.d`
  映射形式（双栈 socket 的固有行为）。如果某处代码假设 `getpeername` 给的是
  AF_INET（2），它会看到 family = 23 —— `std/net/addr` 的 `peer_ip` 已经处理
  了映射地址的还原（v2.07），但**没有专门的夹具覆盖"双栈 reactor 下的
  peer_ip"**，本轮也没加。这是一个真实的未验证点。
- **`tcp_listen6` 与 reactor 现在是两套独立的双栈实现**：前者在
  `qlm_native.py` 的发射层（`__tcp_listen6`），后者在 `std/net/reactor.qma`
  （Quelmara 源码）。值（23 / 41 / 27 / 28）在两边各写一遍 ——
  **没有共享常量**，改一处忘另一处就会分叉。这是 v2.12 "reactor 搬进 std"
  的遗留：发射层那份没法被 std 引用。
- **Linux 侧 reactor 仍是 epoll 未做**（`std/net/reactor` 是 `@ffi`，
  只编 Windows PE）。本轮的双栈只对 Windows 生效。
- **没做 `SO_REUSEPORT` 多 acceptor**：`Quelmara.toml [net] reuse_port`
  目前是"声明未用"（`07-gaps.md` §3 记着）。
- **端口 8092 与 `http_router_test.py` 共用**：两段都在主回归的 `[11]` 里，
  串行跑（不并行），所以不会撞。但如果将来有人把 `[11]` 改成并行，
  这两个会互相抢端口。
