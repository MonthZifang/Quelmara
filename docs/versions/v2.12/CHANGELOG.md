# v2.12 — 服务端运行时全部用本语言写：IOCP reactor 从 stage-0 搬进 `std/net/reactor.qma`

- 日期：2026-10-24
- 任务：把服务端后端整体用 Quelmara 实现，多核默认，网络 I/O 一并走多核
- 影响面：标准库（新模块 `std/net/reactor`）/ 编译器（删 400 行手写 IR，新增两个内建）/ 文档

## 主事件

服务端链路的最后一处"不是本语言写的"东西是 **reactor**：`std/http`、`std/ws`、
`std/sse`、`std/router` 早就是 `.qma`，但事件循环一直是 `qlm_native.py` 里
`__net_serve` 一段 **400 行 emit 调用**（IOCP + rec 池 + accept 循环 + 完成包派发）。

本版把这段整体搬进 `std/net/reactor.qma`（Quelmara 源码，~330 行，含全部注释与
布局说明），stage-0 只留三个原语：

| 原语 | 为什么必须留在编译器里 |
|---|---|
| `@ffi`（v1.87，已有） | 11 个 Win32/Winsock 符号的导入表声明 |
| `thread_start(fn, arg)`（新） | OS 线程入口的 Win64 ABI（`winargs` + callee-saved 序言）；**且不受 `multicore=false` 降级**——`spawn` 在单核配置下内联执行，主线程就再也回不到 accept |
| `net_config(key)`（新） | 编译期读 `Quelmara.toml [net]`，保持"根配置是唯一开关" |

顺带把活跃连接计数从自旋锁改成 `atomic_add`（关闭路径不再抢全局锁）。

## 多核

- worker 数 = `[net] io_threads`（`0` → `core.threads` → 物理核数），**多核默认**。
- 完成端口**共用一个**（canonical IOCP 多 worker）。**per-reactor（每线程一个端口）**
  也实现并测过：4 连接 p50 146 → 175 µs、32 连接无差别 → 按数据回退，理由写进
  `std/net/reactor.qma` 文件头与 `06-status.md` §3.23。
- 多核标定（handler 烧固定 CPU）：`io_threads` 1 → 4 吞吐 **4.3×**（p50 1,904 → 473 µs），
  4 → 20 的收益被压测客户端吃掉（已登记缺口）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/net/reactor.qma` | **新增**：IOCP reactor（`net_serve` / `serve`）、rec 池、accept 循环、GQCS 派发、关闭路径、fail-fast |
| `tools/stage0/qlm_native.py` | 删 `__net_serve` / `__net_worker` / `__net_rec_alloc` / `__net_rec_free` / `__net_active_*` / `__net_recv_post` / `__net_serve_fail` 整块（400 行）；`uses_net_serve` → `uses_threads`；新增 `thread_start` / `net_config` 内建；`net_serve` 内建改为迁移诊断 |
| `std/net.qma` | 删 `serve()`，留一段"reactor 在 `std/net/reactor.qma`"的分层说明（本模块不含 `@ffi`，别把 IOCP 绑定钉进来） |
| `std/http.qma` / `std/ws.qma` / `std/sse.qma` | `import std.net.reactor` |
| `examples/echo_reactor.qma` | 同上 |
| `bench/echo_bench.qma` | **新增**：无日志 echo 服务端（量 reactor 本身） |
| `bench/net_cpu_bench.qma` | **新增**：handler 烧固定 CPU，用于多核标定 |
| `tools/dev/net_bench.py` | **新增**：echo/http/cpu 三模式压测客户端，`--threads` 多客户端线程 |
| `tests/bad/net_serve_builtin.qma` | **新增**负向夹具：不 import 直接调 `net_serve` 必须给出迁移诊断 |
| `tests/run_win_tests.py` | 注册上面的负向夹具 |
| `docs/02-language.md` | `thread_start` / `net_config` 进内建表；`net_serve` 移出内建；静态字 15 登记 |
| `docs/04-compiler.md` | §2 行数、§6.2 reactor 归属、§7 运行时表 |
| `docs/05-toolchain.md` | 新增 §1.9（reactor 在哪、分层、怎么测）；夹具/脚本计数与新增工具 |
| `docs/06-status.md` | §1 主回归 284；新增 §3.23（往返/吞吐/多核标定三张表）；§4 自举行数按当前树重算 |
| `docs/07-gaps.md` | §3 新增「服务端运行时自举 ✅ v2.12」 |
| `docs/01-overview.md` | 仓库结构与关键文件表补 `std/net/reactor.qma` |
| `docs/03-stdlib.md` | 重新生成（新模块的公开 API） |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=284 FAIL=0 SKIP=1（SKIP 是 WSL 交叉验证，被沙箱拦） |
| `python tests/http_router_test.py` | 20/20（真实 socket E2E：路由 / 参数 / 404·405 / 鉴权中间件 / 请求体 / gzip / keep-alive / 流水线） |
| `python tools/dev/net_bench.py echo --conns 4 --reqs 300` | 5,580–6,454 req/s，p50 146–154 µs（基线 5,382–6,427 / 148–155 µs） |
| `python tools/dev/net_bench.py echo --conns 32 --reqs 200 --threads 4` | 19.5–20.1k req/s（基线 19.0–20.0k） |
| `python tools/dev/net_bench.py cpu --conns 20 --reqs 60 --threads 5` | io_threads 1/4/20 = 2,203 / 9,517 / 9,822 req/s |
| 五道门禁 | `check_names` / `check_origin` / `check_docs` / `doc std --missing` / `gen_stdlib_doc --check --require-doc` 全 PASS |

## 已知边界 / 遗留

- **仍只有 Windows**：Linux 的 epoll / io_uring reactor 未做（`07-gaps.md` §4）。
- **accept 在主线程单点**：没有多 acceptor + `SO_REUSEPORT`（`[net] reuse_port` 仍是
  声明未用）；高连接建立速率下 acceptor 可能成为瓶颈，未测。
- `max_conns` 的拒绝发生在 accept 之后（内核已经接受过一次连接），与 v1.4 行为一致。
- 压测客户端在 32 连接 / 4 线程就到顶（Python GIL），服务端真实上限没测出来；
  要多进程压测才能给绝对吞吐。
- `thread_start` 目前只有 x86-64（与 `spawn` 同口径），AArch64 仍无线程。
