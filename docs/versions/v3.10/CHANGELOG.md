# v3.10 — 发送超时：`send_all_to` / `send_to`，对端不收不再永久阻塞

- 日期：2026-10-30
- 任务：补 v3.08 自己登记的边界 —— "发送侧仍是阻塞 `tcp_send_n`"
- 影响面：**编译器**（新内建 `tcp_send_n_to` + `select`/`poll` 发射 + `ws2_32` 导入白名单）、
  标准库（`std/net` 三个发送函数）、测试（新增 `tests/t167_sendtimeout.qma`）、文档

## 问题：`send_all` 会一直等对端收

`send_all` 内部的 `tcp_send_n` 是阻塞 `send()`。对端不读（慢消费者、卡住的
客户端、只发不收的协议实现）时，内核发送缓冲区一满，`send()` 就再也不返回：

```
$ timeout 12 ./build/probe_sendloop.exe      # 循环 send_all 1 MB，对端全程不读
EXIT=124                                     # 12 s 被外部杀掉，程序自己不会返回
```

与 v3.08 的接收侧完全对称：那边卡在"等对端发"，这边卡在"等对端收"。TCP 的
背压是**正确行为**，但库层必须给调用方一个"等到什么时候就算了"的开关。

## 第一版写错了：`SO_SNDTIMEO` 在 Win32 上不生效

最直觉的做法是照抄接收侧的 `SO_RCVTIMEO`：`setsockopt(SO_SNDTIMEO)` + `send()`。
**实测不行**：

| 实验 | 结果 |
|---|---|
| `SO_SNDTIMEO = 200 ms`，窗口满后 send | 挂住，不返回 |
| `SO_SNDTIMEO = 5000 ms` | 挂 **40 s+** 仍未返回（外部超时杀掉） |
| 对照：`SO_RCVTIMEO = 1000 ms` 收数据 | 1.0 s 按时返回（v3.08 已验证） |

不是参数写错（`SOL_SOCKET=0xFFFF` / `SO_SNDTIMEO=0x1007` / `DWORD` 毫秒都按
文档传的，且同一份发射代码在接收侧工作正常）。**Win32 的传输层在零窗口挂起后
会自己重试，不看这个选项**——这是已知行为，接收侧不受影响是因为 recv 的超时
由 Winsock 自己实现。

结论：`SO_SNDTIMEO` 这条路要**整条废掉**，不能留一个"看着像超时、其实不超时"的 API。

## 正确做法：先等可写，再发

每轮先问内核"现在能写吗"，能写再 `send`：

```
while total < n {
    等可写(ms)            // Windows: select(写集) / Linux: poll(POLLOUT)
    if 超时: break        // 返回已写出的字节数
    k = send(剩余)        // 阻塞 socket，但此刻至少能写 1 字节 -> 立刻返回
    if k <= 0: break
    total += k
}
```

为什么这样不会又卡住：`send()` 在阻塞 socket 上**只在连 1 字节都写不进去时**才
阻塞；`select`/`poll` 刚说"可写"，就保证至少 1 字节能进去，于是 `send` 写一部分
就返回。既不需要把 socket 临时改成非阻塞（那要复原，漏一条错误路径就会污染
后续所有收发），也不会有"窗口在 select 与 send 之间刚好关上"之外的理论竞态。

### 两个平台的布局差异（都踩过）

| | Windows | Linux x86_64 |
|---|---|---|
| 等待原语 | `select(0, NULL, &wset, NULL, &timeval)` | `poll(&pollfd, 1, ms)` |
| 结构 | `fd_set{u_int count; SOCKET fd_array[64]}`，count 在偏移 0，数组从偏移 8 | `pollfd{int fd; short events; short revents}`，8 字节 |
| 超时 | `struct timeval` 是**两个 4 字节 long**（8 字节） | 直接吃毫秒数，`-1` = 无限 |
| 不限时 | 超时指针传 `NULL` | 传 `-1` |
| 写入方式 | 两个 32 位值拼进一个 8 字节字（`sec \| usec<<32`） | fd 与 `events=POLLOUT` 拼进一个 8 字节字 |

原生后端的 `store` 是**8 字节字、偏移按字计**，所以这些"结构体"都是拼字写进去的。
`select` 还得在 `qlm_pe.py` 的 `ws2_32` 白名单里登记——它不属于 kernel32，
漏登记就是加载期 `ENTRYPOINT_NOT_FOUND`（v2.97 那次 `WSAGetLastError` 的老坑）。

### 架构闸门

`tcp_send_n_to` 只在 x86_64 实现：arm64 内核**没有 7 号 `poll` 系统调用**
（只有 `ppoll`），照抄会静默返回 `ENOSYS`。所以在编译期就 fail-fast 并说明原因，
而不是发一条"永远超时"的指令。

## 标准库侧

| 函数 | 语义 |
|---|---|
| `send_all_to(conn, data, ms)` | 发全为止；每次 `send` 最多等 `ms`；返回**已写出字节数**，短了就是"对端吃不下" |
| `send_to(conn, data, ms)` | 单次发送（可能短写），超时返回 `0` |
| `send_all(conn, data)` | 不变（无超时），但实现收进 `_send_buf`，与带超时的版本共用一段推进逻辑 |

`_send_buf` 把两条路径收在一个循环里，避免 v3.07/v3.08 那种"同一个循环抄两份、
改一份忘一份"——接收侧那六个函数就是因为抄了两份，O(n²) 才在发送侧修掉之后
又活了三个版本。

### 回归抓到的连带 bug：`KeyError: '__free'`

给 `__tcp_recv_to` 加"timeval 用完即还"之后，主回归在 4 分钟处直接崩了：

```
  File "tools/stage0/qlm_native.py", line 700, in resolve
    target = self.labels[label]
KeyError: '__free'
```

原因：`__free` 只在 `self.uses_free` 时发射，而**网络运行库只要 `uses_net` 就无条件
发射** `__tcp_recv_to` / `__tcp_send_n_to`（不看程序有没有真的调 `*_to`）。于是
"导入 `std.net` 但只用 `send` / `recv`"的程序会引用一个不存在的函数。

手写用例（`t167`）过不了这一关：它自己调了 `tcp_send_n_to`，`uses_free` 顺手就被
置上了。**这正是主回归存在的意义**——单点用例只覆盖它自己那条路径。

修法是把条件放宽到 `uses_free or uses_net`（代价是网络程序多带一个 ~20 条的
`__free`，可忽略）。复现件：只用 `send`/`recv` 的最小网络程序。

## 验证

### `tests/t167_sendtimeout.qma`（4 组）

| # | 场景 | 断言 |
|---|---|---|
| 1 | 对端正常读 1 MB | `send_all_to` 返回 1048576；对端回 `len=1048576 bad=0`（抽样校验内容） |
| 2 | 对端全程不读，循环发 1 MB / 300 ms | 某次**短写**；耗时 ∈ [250, 5000) ms |
| 3 | 窗口已满时单次 `send_to` | 返回 **0**；耗时 ∈ [250, 5000) ms |
| 4 | 小负载 / 空串 | `"hello"` 发全；空串返回 0（不碰 socket） |

```
$ ./build/t167.exe
send timeout ok
EXIT=0        # 整轮 3.3 s（含 deaf worker 的 sleep_ms(3000)）
```

第 2 条同时钉住"**真的等够了 ms**"和"**没有挂死**"：只断言返回值会漏掉
"立刻返回短写"这种假通过（那种实现等于把背压变成静默丢数据）。

单次实测（`build/probe_sendloop_to.qma`，1 MB × 200 ms 超时）：

```
iters=1  total=1048576  short=1  ms=200
```

### 回归

| 命令 | 结果 |
|---|---|
| `./build/t167.exe`（native，连跑 3 次） | `send timeout ok` ×3 |
| `t163 / t164 / t165 / t166` | 全过（接收侧四个用例不受影响） |
| `python tools/stage0/qlm_native.py build tests/t167_sendtimeout.qma` | ELF 分支编译通过（Linux 路径走 `poll`） |
| `python tests/run_win_tests.py` | `PASS=302 FAIL=0 SKIP=1`（首轮在 `KeyError: '__free'` 处崩，已修，见下） |

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 新内建 `tcp_send_n_to`：`__tcp_send_n_to` = 等可写（`select`/`poll`）+ `send` 循环；`SYSCALLS["x86_64"]` 加 `poll: 7`；`__tcp_recv_to` 的 timeval 改用完即 `__free` |
| `tools/stage0/qlm_pe.py` | `WS2_32_FUNCS` 加 `select` |
| `std/net.qma` | 新增 `_send_buf` / `send_all_to` / `send_to`；`send_all` 收进 `_send_buf` |
| `tests/t167_sendtimeout.qma` | **新增**（4 组，含零窗口短写与 `send_to` 返回 0） |
| `tests/run_native_tests.sh` | 接入 t167（`timeout 120` 兜底） |
| `docs/02-language.md` | 内建表新增 `tcp_send_n_to` 行 |
| `docs/03-stdlib.md` | 重新生成（`std/net` 15 → 17 个公开函数） |
| `docs/06-status.md` | 新增 §3.65（含 `SO_SNDTIMEO` 的负结果） |
| `docs/07-gaps.md` | §2 TCP 行、§5 补条目 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.10.0 |

## 已知边界 / 遗留

- **没有"发送侧接收超时"的副作用隔离**：`select`/`poll` 只查询可写性，不改 socket
  状态，所以不存在"忘了复原"的问题——这是相对 `FIONBIO` 方案的主要好处。
- **`ms` 是"每次 `send`"的预算，不是总时长**。持续被读的对端可以让
  `send_all_to` 跑任意久（大文件传输不该被总时长砍断）。
- **`ms = 0` / 负数 = 不限时**（Windows `NULL`、Linux `-1`），与 `tcp_recv_to` 一致。
- **`select` 有 64 个 socket 的 `FD_SETSIZE` 上限**——这里每次只放 1 个，不受影响。
- **AArch64 编译期 fail-fast**（缺 `poll` 系统调用）。要支持得写 `ppoll` 那条路。
- **发送侧仍不检查"对端是否已关闭"**：对端 RST 后 `send` 返回 -1 → 本函数返回
  已写出的字节数（不 fail-fast），调用方靠 `!= len(data)` 发现。这是刻意的：
  "对端断了"与"对端一时不收"在循环语义上都是"停"。
- **`t167` 依赖零窗口才能触发短写**，而窗口大小随系统/驱动变（本机约 1 MB）。
  用例因此写成"循环到某次发不全"，不假定第几次；分块 1 MB 也是为此选的。
