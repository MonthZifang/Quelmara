# v3.09 — 批量接收改成 O(n)：4 MB / 4 KB 分块从堆爆到 73 ms

- 日期：2026-10-30
- 任务：用户要求"继续推进 + 优化性能"；入口是 v3.08 自己登记的边界 ——
  "接收侧仍是 O(n²) 字符串拼接"
- 影响面：标准库（`std/net` 六个接收函数的累积方式）、**编译器诊断**（死循环告警的
  误报判据）、测试（新增 `tests/t166_recvbulk.qma`、修 `tests/http_router_test.py`
  的 R10 用例）、文档

## 问题：接收侧的 O(n²) 比发送侧更隐蔽

v3.06 的三个批量接收函数都是这个形状：

```quelmara
let out = ""
while len(out) < n {
    let part = tcp_recv(conn, cap)
    if len(part) == 0 { break }
    out = out + part          // ← 每轮把**已累计的全部数据**复制一遍
}
```

`out = out + part` 每次分配 `len(out)+len(part)` 并复制两者。总拷贝量
= Σ(cap·k) ≈ n²/(2·cap)。4 MB 按 4 KB 分块 = 1024 轮 → **约 2 GB 拷贝**，
直接超过 512 MB 堆上限：

```
$ ./build/probe_recv.exe          # recv_exact(c, 4MB, 4096)
quelmara: heap_limit_mb exceeded (fail-fast)
EXIT=1
```

v3.07 在发送侧（`send_all`）踩过同一个坑，用 `str_ptr` + `tcp_send_n` 零拷贝修掉了；
**接收侧没跟上**——因为 `t164` 用的分块是 65536，只有 64 轮、累计复制 128 MB，
在 512 MB 上限下"看起来没问题"。分块越小越糟，而 v3.08 新加的三个 `*_to`
默认分块正好是 4096。

## 做法：一次分配 + 翻倍扩容 + 原地 `mem_copy`

六个函数收进一个私有核心 `_recv_buf(conn, limit, chunk, timed, ms)`：

```quelmara
let mut buf = mem_alloc(cap)
while limit <= 0 || got < limit {
    if got == cap {                       // 满了翻倍（不越过 limit）
        let nb = mem_alloc(ncap)
        mem_copy(nb, buf, got)
        mem_free(buf, cap)
        buf = nb
    }
    let part = tcp_recv_to(conn, cap - got, ms)
    if len(part) == 0 { break }
    mem_copy(mem_ptr(buf, got), str_ptr(part), len(part))   // 原地追加
    got = got + len(part)
}
let out = mem_str(buf, got)               // 只有这一次成串拷贝
mem_free(buf, cap)
```

| 参数 | 语义 |
|---|---|
| `limit <= 0` | 不限长（`recv_all`） |
| `limit > 0` | 最多 `limit` 字节（`recv_exact` / `recv_all_max`），扩容不越过它 |
| `timed != 0` | 每次接收走 `tcp_recv_to`（带毫秒超时），否则走阻塞 `tcp_recv` |

总拷贝量变成 O(n)（几何级数的和），峰值内存 = 当前缓冲 + 扩容瞬间的新缓冲（≤ 2 倍），
不再是"累计垃圾"。六个公开函数都退化成一行调用，语义一字未改。

## 实测（本机 Windows PE，`build/probe_recv*.qma`，取 3–5 次）

| 形状 | 改前 | 改后 |
|---|---|---|
| 4 MB / **4 KB** 分块 | **`heap_limit_mb exceeded`（跑不完）** | **57–80 ms**（中位 75） |
| 4 MB / 64 KB 分块 | 187 / 191 / 225 ms（中位 191） | 72 / 83 / 80 / 90 / 78 ms（中位 80） |
| 13 MB 全链（`t166` 5 场景串行） | — | **0.45 s** 整轮，退出码 0 |

64 KB 那行是同一形状的公平对照：**2.4×**。4 KB 那行不是"慢"，是**跑不完**——
这也是为什么这条要先修正确性再谈性能。

## 顺带修掉的两个"证据型"缺陷

### 1. 死循环告警对"复合条件"误报

`_recv_buf` 的循环条件是 `limit <= 0 || got < limit`，编译后 header 后是
**多条** `jcc`（中间夹 `or` 标签）。而 `check_suspicious_loops` 只看 header 后
第一条 `jcc` 的操作数当 guard 变量 —— `limit` 本来就不该在循环体里被赋值，
于是**每个把短路条件写在前面**的循环都会误报：

```
warning: possible infinite loop in 'recv_exact' (loop #2): guard variable never updated in body
```

判据改成"**所有** guard 比较变量都没被写过"：把 header 后连续的 `jcc` 序列
（允许中间夹 `label`，最多 8 条）里的 vreg 全收集起来再查。修完两个方向都验过：

| 探针 | 期望 | 实测 |
|---|---|---|
| `while i < 10 { s = s + 1 }`（`i` 从形参来，不被常量折叠） | 报 | **报** |
| `while limit <= 0 \|\| got < limit`（复合条件，`cap` 在体内被写） | 不报 | **不报** |

注意第一版探针写的是 `let mut i = 0` —— 复制传播把 `i < 10` 折成
`jcc ge imm0, imm10`，两个操作数都成了立即数，**根本进不了这条判据**。
"用来验证诊断的探针本身要先确认它没被优化掉"，和 §3.50 那条测量纪律同源。

### 2. `http_router_test.py` 的 R10 用例数据自相矛盾

`tests/http_router_test.py` 一直有一项红（`chunked 分片: 400 Bad Request`），
且**不在主回归里**，所以从 v2.95 起没人发现。查下去不是实现错：

```python
b"7\r\nQuelm"      # 声明 7 字节，给了 5
b"ara\r\n0\r\n\r\n"  # 补 3 字节 → 实际 8 字节，与声明的 7 不符
```

服务端按 RFC 7230 §4.1 校验"每个 chunk 的数据段必须正好 `size` 字节 + CRLF"，
第 8 个字节落在 CRLF 位置上 → 400。**判得对，是用例数据错了**（注释自己都写着
"补齐 2"）。改成 `b"ar\r\n0\r\n\r\n"` 后全绿：

```
http_router ok（26 项断言）
```

## 验证

| 命令 | 结果 |
|---|---|
| `./build/t166.exe`（新用例，5 场景） | `recv bulk ok`，退出码 0，整轮 0.45 s |
| `./build/t163/t164/t165.exe` | `recv batch ok` / `send batch ok` / `recv timeout ok` |
| `python tests/http_router_test.py` | `http_router ok（26 项断言）`（修 R10 前是 1 项红） |
| `python tests/run_win_tests.py` | 见 `06-status.md` §1 |

`t166` 的五个场景：

| # | 形状 | 断言 |
|---|---|---|
| 1 | `recv_exact` 4 MB / **4 KB** | 长度 = 4194304，1 KB 抽样内容全对，< 20 s |
| 2 | `recv_all` 4 MB / 64 KB | 同上（不限长扩容路径） |
| 3 | `recv_all_max` 要 4 MB 只给 2 MB | 正好 2 MB，前缀内容对（截断 + 扩容不越界） |
| 4 | `recv_all_to` 1 MB / 2 s | 长度与内容都对（带超时走同一套累积） |
| 5 | `n <= 0` / `maxbytes <= 0` | 返回空串，不分配 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/net.qma` | 新增私有 `_recv_buf`（缓冲区累积）；六个公开接收函数改成一行调用 |
| `tools/stage0/qlm_opt.py` | `check_suspicious_loops` 按整段 guard 判据（修复合条件误报） |
| `tools/stage0/qlm_native.py` | 修正 `tcp_recv_to` / `udp_recvfrom_to` 注释里"`ms <= 0` 是非阻塞"的错误口径 |
| `tests/t166_recvbulk.qma` | **新增**（5 场景，含 4 MB / 4 KB 回归） |
| `tests/http_router_test.py` | 修 R10 用例数据（声明 7 却发 8 字节） |
| `tests/run_native_tests.sh` | 接入 t166（`timeout 180` 兜底） |
| `docs/02-language.md` | `tcp_recv_to` / `udp_recvfrom_to` 两行的 `ms` 语义更正 |
| `docs/03-stdlib.md` | 重新生成（`recv_*` 六个函数的 doc 更新） |
| `docs/06-status.md` | 新增 §3.64（实测对照表） |
| `docs/07-gaps.md` | §2 TCP 行、§5 性能专项各补一条 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.09.0 |

## 已知边界 / 遗留

- **上限仍是 512 MB 堆**（`[memory] heap_limit_mb`）。`_recv_buf` 只保证 O(n) 拷贝，
  不保证装得下——`recv_all` 不限长，对端一直发就会一直扩容到堆上限后 fail-fast。
  要真正的流式处理得有"边收边处理"的回调式 API，现在没有。
- **峰值内存仍是 ≤ 2 倍**（扩容瞬间的旧缓冲 + 新缓冲）。要 1 倍就得分段预分配
  （`limit > 0` 且调用方如实给出上界时可以直接一次分配）。
- **`ms = 0` 是"不限时"，不是非阻塞**。v3.04 / v3.08 的文档都写错了，本版更正；
  真正的非阻塞探测要 `ioctlsocket(FIONBIO)` / `O_NONBLOCK`，未实现。
- **`http_router_test.py` 仍未进主回归**。它需要先编译 `examples/http_router.qma`
  并占端口 8092，`run_win_tests.py` 没接它——所以这项红了整整 4 个版本没人发现。
  接进主回归要处理"端口占用 / 起停时序"，单独一轮做。
- **`tests/gzip_http_test.py` 需要手工先起服务**（`examples/http_gzip.qma`，
  端口 18080），不是自包含的；本版没动它。gzip 协商的端到端覆盖由
  `http_router_test.py` 的 R6 保证。
