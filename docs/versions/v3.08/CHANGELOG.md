# v3.08 — 带超时的批量接收三件套：`recv_all` 遇半开连接不再永久阻塞

- 日期：2026-10-30
- 任务：补 v3.06 自己登记的边界 —— "`recv_all` 无超时"
- 影响面：**编译器**（新内建 `tcp_recv_to`）、标准库（`std/net` 三个新函数）、测试（新增 `tests/t165_recvtimeout.qma`）、文档

## 问题：`recv_all` 会等到天荒地老

`std/net` 的批量接收只有"读到对端 FIN"一种停止条件：

```quelmara
pub fn recv_all(conn: int, chunk: int) -> str {
    let out = ""
    while true {
        let part = tcp_recv(conn, chunk)
        if len(part) == 0 { break }   // 只有 FIN（或出错）才 break
        out = out + part
    }
    return out
}
```

`tcp_recv` 是阻塞 `recv()`。所以只要对端**发了一半就保持连接**——慢客户端、
把请求体写在半路就卡住的实现、恶意对端、NAT 掉线的半开连接——这个循环
**永远不返回**。

实测（`build/probe_hang.qma`：worker 发 17 字节后 `sleep_ms(60000)` 不关连接）：

```
$ timeout 12 ./build/probe_hang.exe
EXIT=124        # 12 s 被外部杀掉，程序自己一分钟内都没返回
```

这不是"慢"，是**挂死**。TCP 没有"对端还活着吗"的心跳，只有超时能回答这个问题。
与 v3.04 修的 UDP `recvfrom` 挂死是同一类缺陷，只是 TCP 侧没人补。

## 做法：一次接收带超时 + 三个组合子

### 内建 `tcp_recv_to(fd, cap, ms) -> str`（编译器能力）

单次接收，`ms` 毫秒内没数据就返回**空串**——不是 fail-fast。这一点是刻意的：
超时是**可恢复结果**，`recv_all` 这类循环要靠"拿到空串"才能停下来。

实现（`qlm_native.py`，`__tcp_recv_to`）：先 `setsockopt(SO_RCVTIMEO)` 再 `recv()`。

| 平台 | 常量 | optval 形状 |
|---|---|---|
| Windows | `SOL_SOCKET=0xFFFF` / `SO_RCVTIMEO=0x1006` | `DWORD` 毫秒（4 字节） |
| Linux | `SOL_SOCKET=1` / `SO_RCVTIMEO=20` | `struct timeval{sec, usec}`（16 字节，由 `ms` 现算） |

`recv()` 返回 `-1`（`EAGAIN`）时走"空串"出口；真正的连接错误（`ECONNRESET` 等）
也走同一个出口——对循环语义来说"超时"和"断了"都是"别再读了"。

### `std/net` 三个组合子

与 v3.06 的三个函数一一对应，只是每次接收带 `ms`：

| 新函数 | 对应旧函数 | 停止条件 |
|---|---|---|
| `recv_all_to(conn, chunk, ms)` | `recv_all` | 对端关闭 **或** 单次超时 |
| `recv_all_max_to(conn, chunk, maxbytes, ms)` | `recv_all_max` | 同上，另加 `maxbytes` 上限 |
| `recv_exact_to(conn, n, chunk, ms)` | `recv_exact` | 读满 `n` **或** 超时（返回已读部分） |

返回值语义统一为"**已读到的部分**"：超时可能返回空串，也可能返回半截。
调用方用 `len(result) == n` 判断是否读满，不要假定"返回了就是收全了"——
这与 `recv_exact` 的短读语义同口径。

## 验证

### `tests/t165_recvtimeout.qma`（3 场景）

| # | 场景 | 断言 |
|---|---|---|
| 1 | 对端发 16 字节后 `sleep_ms(3000)` 不关连接 | `recv_all_to(c, 4096, 1000)` 返回全部 16 字节，耗时落在 **[900, 5000) ms** |
| 2 | 对端只发 3 字节且保持连接 | `recv_exact_to(c, 100, 8, 800)` 返回 `"abc"`（长度 3，不是 100） |
| 3 | 对端发完立刻关闭 | 正常路径不受影响，读到 `"full-and-closed"` |

第 1 条同时钉住"**真的等了一会儿**"（`el >= 900`）和"**没有挂死**"（`el < 5000`）：
只断言返回值会漏掉"立刻返回空串"这种假通过。

```
$ ./build/nat_recvto.exe
recv timeout ok
EXIT=0        # 整轮 6.3 s（含 worker 的 sleep_ms(3000)）
```

### 文档同源

`std/net.qma` 新增的三个函数都带 `///`，`gen_stdlib_doc.py` 重新生成后
`std/net` 从 11 个公开函数变成 14 个：

```
$ python tools/dev/gen_stdlib_doc.py --check
PASS：67 个模块 / 566 个公开函数（内部 570），文档与源码一致
```

写这版时踩到一个文档规则：说明性的段落原来也用 `///` 写在**两个声明之间**，
生成器判为 `[orphan] doc 块与声明之间有空行`——`///` 必须紧贴声明，脱离就是孤儿。
改成 `//` 普通注释 + 每个函数自己的 `///` 才同源。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 新增内建 `tcp_recv_to` 的降级（`__tcp_recv_to`：two-platform `SO_RCVTIMEO` + `recv`） |
| `std/net.qma` | 新增 `recv_all_to` / `recv_all_max_to` / `recv_exact_to` |
| `tests/t165_recvtimeout.qma` | **新增**（3 场景，含半开连接与短读） |
| `tests/run_native_tests.sh` | 接入 t165（`timeout 90` 兜底） |
| `docs/02-language.md` | 内建表新增 `tcp_recv_to` 行 |
| `docs/03-stdlib.md` | 重新生成（`std/net` 11 → 14 个公开函数） |
| `docs/07-gaps.md` | §2「TCP 批量收发」补超时三件套 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.08.0 |

## 已知边界 / 遗留

- **超时是"每次接收"的，不是"总时长"**。`recv_all_to(c, 4096, 1000)` 在持续
  有数据的情况下可以跑任意久——这是刻意的（否则大文件传输会被总时长砍断）。
  要总时长上限得由调用方自己计时。
- ~~**`ms <= 0` 是"非阻塞探测"**~~ —— **这条是错的，v3.09 实测更正**：
  `SO_RCVTIMEO=0` 在 Windows 与 Linux 上都表示"不限时（等到底）"，不是非阻塞。
  （v3.04 的 `udp_recvfrom_to` 沿用了同一个错误说法。）真正的非阻塞要
  `O_NONBLOCK` / `ioctlsocket`，尚未实现。
- **Linux 侧 `timeval` 由 `ms` 现算**（`div` + `mod` + `mul`），`ms` 极大时不溢出
  （秒数是 `ms/1000`，64 位）。
- **接收侧仍是 O(n²) 字符串拼接**：`out = out + part` 每轮复制已累计的全部数据。
  4 MB 负载按 4 KB 分块收，累计复制约 2 GB，**直接撞 `heap_limit_mb`**
  （实测 `recv_exact` 4 MB / 4 KB = `heap_limit_mb exceeded`，见 v3.09）。
  v3.07 在发送侧修掉了同一类问题，接收侧这次只补了超时、没动累积方式。
- **AArch64 / C 后端**：`tcp_recv_to` 只在 x86-64 的两个平台实现，与 `tcp_recv`
  同边界；C 后端对 `tcp_*` 一直是编译期 fail-fast。
