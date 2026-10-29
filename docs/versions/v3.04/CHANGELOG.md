# v3.04 — `udp_recvfrom_to`：给 DNS 加接收超时，nameserver 不响应不再挂死

- 日期：2026-10-29
- 任务：修 v3.03 自己登记的边界 —— `dns_resolve` 无超时，DNS 不响应时永久阻塞
- 影响面：运行时（新增 `udp_recvfrom_to` 内建）、标准库（`std/net/dns`）、文档

## 问题：v3.03 的 DNS 会挂死

v3.03 交付 `std/net/dns` 时，我在「已知边界」里如实写了这一条：

> **单 nameserver、单次尝试、无超时**。`udp_recvfrom` 是阻塞的，DNS 服务器
> 不响应时 `dns_resolve` 会一直挂着。

这不是理论风险。UDP 是无连接的：nameserver 挂了、被防火墙丢包、或者
resolv.conf 里那个地址根本不存在，`recvfrom` 都会**无限等下去**。
一个解析调用把整个进程钉死，这在任何生产场景都不可接受。

所以这是"刚交付的代码里的健壮性缺陷"，优先级高于新功能。

## 为什么不是简单加个 if

`udp_recvfrom` 的阻塞发生在**内核里**——用户态没有任何办法"等一会儿就放弃"。
要让内核带超时返回，只有三条路：

| 方案 | 问题 |
|---|---|
| `poll`/`select` 等 fd 可读 | 要新增两个 syscall 封装 + 一个 fd_set 结构，代码量大 |
| 另起线程 + 超时后 `close(fd)` | 要线程同步，且关 fd 会让另一线程的 `recvfrom` 返回错误——语义脏 |
| **`setsockopt(SO_RCVTIMEO)`** | 一行设置，内核自己带超时返回 `EAGAIN`。**最小侵入** |

选第三条。

## 实现：`udp_recvfrom_to(fd, cap, ms)`（新内建）

```
udp_recvfrom_to(fd, cap, ms) -> str
    收到：正常返回数据报
    超时：返回**空串**（len == 0）
    ms <= 0：非阻塞探测
```

**为什么超时返回空串而不是 fail-fast**：「这个 nameserver 没响应」是可恢复
结果，调用方（DNS）要能拿到它并决定回退，不是进程终止条件。这与库里
"能返回就返回、不能返回才 fail-fast"的口径一致。

### 两个平台的差别（都在一个函数里）

| | Linux | Windows |
|---|---|---|
| 调用 | `syscall 54` | `winapi setsockopt` |
| level | `SOL_SOCKET = 1` | `SOL_SOCKET = 0xFFFF` |
| optname | `SO_RCVTIMEO = 20` | `SO_RCVTIMEO = 0x1006` |
| optval | `struct timeval{sec, usec}`（16 B） | `DWORD` 毫秒（4 B） |

Linux 的 `timeval` 两个字段各 8 字节，所以 `ms` 要拆成
`sec = ms/1000`、`usec = (ms%1000)*1000`；Windows 直接就是毫秒。

**只设一次，不改回**：超时对同一 fd 的后续接收持续有效，与调用方预期一致
（DNS 用完就 `close`，没有"恢复阻塞"的需求）。

## 接入 DNS

`std/net/dns` 的 `dns_resolve` 从 `udp_recvfrom(fd, 2048)` 改成
`udp_recvfrom_to(fd, 2048, 3000)`：3 秒超时。

3 秒是权衡：公网 DNS 正常在 20–80 ms 返回，3 秒足够覆盖慢链路；
而最坏情况（nameserver 黑洞）进程最多多等 3 秒，不会挂死。

## 验证

### 超时行为（本机，不可达地址 `192.0.2.1` = TEST-NET-1）

```
udp_send_str(fd, "192.0.2.1", 53, q)   -> 发出
udp_recvfrom_to(fd, 2048, 500)         -> 长度 0（空串）
实测耗时                                -> 502 ms
进程退出码                              -> 0（没有挂死）
```

500 ms 的超时，实测 502 ms 返回 —— 内核超时生效，误差在调度粒度内。

### 正常解析仍然工作

```
dns_resolve("example.com")  -> 172.66.147.243
```

### 回归

| 命令 | 结果 |
|---|---|
| `python tests/dns_test.py` | **PASS=31 FAIL=0**（报文层未受影响） |
| `bash tests/run_native_tests.sh` | 见 `06-status.md` §1 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 新增内建 `udp_recvfrom_to` 的派发 + 运行时 `__udp_recvfrom_to`（约 90 行） |
| `std/net/dns.qma` | `dns_resolve` 改用 `udp_recvfrom_to(fd, 2048, 3000)` |
| `docs/02-language.md` | 内建表新增 `udp_recvfrom_to` 行 |
| `docs/03-stdlib.md` | `std/net/dns` 一句话补"带超时" |
| `docs/07-gaps.md` | DNS 行的「无超时」边界改为「v3.04 已带超时」 |

## 已知边界 / 遗留

- **超时是 per-fd 的，不是 per-call 的**。设了 3 秒之后同一 fd 的每次接收
  都是 3 秒。要"每次调用不同超时"得每次都 `setsockopt`——本实现就是每次都设，
  所以其实支持；只是没有"改回阻塞"的接口（不需要）。
- **Windows 侧未实测**：容器里只有 Linux。代码路径与已有的
  `tcp_listen6` 的 `setsockopt` 用法同源（同样的 level/optname 写法），
  但**没有在 Windows 上跑过**，按"没测过就不算验证"的纪律，这里如实标注。
- **没有重试**：超时后 `dns_resolve` 直接返回空串，不换第二个 nameserver。
  多 nameserver 轮询是独立的一块（要解析 resolv.conf 的全部条目 + 超时预算
  分配），留给后续版本。
