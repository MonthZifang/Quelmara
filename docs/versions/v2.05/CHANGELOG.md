# v2.05 — `std/ds` 补成公开模块：RingBuf / MinHeap 从"引用即编译失败"到可用（数据结构行 🟡 → ✅）

- 日期：2026-10-24
- 任务：用户要求"扫描目录、按文档规范来，把数据结构这条一次性补成绿色，同步文档，测一下性能"。
  §7.13 的清单是 **10 个模块 141 个声明**补 `pub` + `///`，按"一次只补一个模块"的口径，
  本版只做 `std/ds`（RingBuf / MinHeap），其余如实记账留给后续版本。
- 影响面：标准库（`std/ds`）、测试、基准、文档

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/ds.qma` | **10 个函数补 `pub` + 每个补 `///`**（doc 门禁要求公开声明必须有文档）；新增 `rb_clear` / `rb_free` / `heap_len`，公开面 10 → **13**；`heap_push` / `heap_pop` 改**"挖洞"**（上浮/下沉时元素只搬一次：末元素取出 → 逐层让位 → 最后落位，每层从"读 4 写 4"降到"读 2 写 1"）；头注释写清**选型**（vs `std/deque`、`std/lru`）、布局、复杂度、`-1` 哨兵与元素值同域、非线程安全 |
| `tests/t129_ds.qma` | 新增回归，15 组断言：RingBuf 的 FIFO / 绕回（head 非 0）/ 满不覆盖最老 / 空哨兵 / `clear` 复用 / 负值 / 1000 条整轮；MinHeap 的升降序 / 重复 key / 负 key / 初始 2 槽扩到 300 / 交错 push-pop / 1000 条伪随机全弹出有序 / **key 打包句柄**（`due*1024+id`）这一推荐用法 |
| `bench/ds_bench.qma` | 新增基准：RingBuf 稳态 push+pop（cap 4096，每轮跨绕回）/ `peek`；`vec[int]` 与 `std/deque` 两个同形状对照；MinHeap 两种规模（20 万 = 1.6 MB 超 L2 / 1 万 = 80 KB 装得进 L2）；`sort_int` 一次性排序对照 |
| `tests/run_win_tests.py` | 注册 `t129_ds`（`case_selfcheck`） |
| `docs/03-stdlib.md` | 重新生成：`std/ds` 从 `0 / 10` 变 **`13 / 13`** 并列出全部签名（此前的"本模块的顶层函数都未 pub 导出"占位说明随之消失） |
| `docs/07-gaps.md` | §2 **数据结构 🟡 → ✅**（边界栏写清 key-only / 哨兵同域 / 非线程安全）；§5 新增"`std/ds` 堆下沉挖洞"行；§7.13 按当前源码重测（10 模块 141 声明 → **7 模块 73 声明**，4 个解析失败 → **3 个**）；§8 标准库序列补 `std/ds` |
| `docs/06-status.md` | 新增 **§3.18**（ds 单价 + 唯一可信的同进程 A/B）；§1 PE 回归 275 → **276**、两处门禁计数改为实测值；§6 风险行 10 模块 → 7 模块 |
| `docs/05-toolchain.md` | §5.1 夹具计数 142 / 18 / 24 → **145 / 19 / 26**（含同期另一条轨新增的 `t129_net6` / `t130_router_dispatch` / `http_router` / `http_router_bench`） |
| `docs/02-language.md` | §7.2 内建表 `mem_free(p)` → **`mem_free(p, n)`**（写 `rb_free` 时踩到：`SyntaxError: mem_free(ptr, n) 需要两个实参`，`qlm_native.py:2918`）。文档从 v1.x 起就少写了一个参数 |
| `tools/stage0/qlm_cli.py` | `VERSION` → `2.05.0`（本版）；随后 `docs/versions/v2.06/` 由同期另一条轨落地，按"版本号同源"门禁再推进到 `2.06.0` |

## 实测（`06-status.md` §3.18，同机同日，同一条命令 10 次取中位）

| 负载 | 中位 | 口径 |
|---|---|---|
| RingBuf push+pop 配对（跨绕回） | **32 ns/对** | 100 万对 |
| RingBuf `peek` | **1.5 ns/次** | 100 万次 |
| `vec[int]` push+pop 配对（对照） | 12 ns/对 | 100 万对 |
| `std/deque` push_back+pop_front（对照） | 41 ns/对 | 100 万对 |
| MinHeap push / pop（20 万） | **59 / 462 ns** | 堆 1.6 MB |
| MinHeap push / pop（1 万） | 52 / **271 ns** | 堆 80 KB |
| `sort_int` 20 万（对照） | 260 ns/元素 | — |
| `heap_pop` 挖洞前 → 后（**同进程交错 A/B**） | **700 → 458 ns/次（1.5×）** | 20 万，3 轮 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py`（隔离 worktree `HEAD(v2.01)+本版改动`） | **PASS=276 FAIL=0 SKIP=1**（SKIP = WSL 被沙箱拦；276 = 基线 275 + `t129_ds`） |
| `python tools/stage0/qlm_cli.py run tests/t129_ds.qma --target win` | 退出码 0，打印 `ds ok` |
| `python tools/stage0/qlm_cli.py run bench/ds_bench.qma --target win` | 见 `06-status.md` §3.18（10 次取中位） |
| `python tools/dev/gen_stdlib_doc.py --check --require-doc` | **PASS：61 个模块 / 499 个公开函数**，文档与源码一致 |
| `python tools/stage0/qlm_cli.py doc std --missing` | **PASS：61 个模块 / 502 个公开声明**全部有 `///` |
| `python tools/dev/check_docs.py` / `check_names.py` / `check_origin.py` | 全 PASS |

## 已知边界 / 遗留

- **只补了 `std/ds` 一个模块**。`07-gaps.md` §7.13 剩 **7 个模块 73 个声明**（`core` / `gen` /
  `serialize` / `sse` / `time` / `timer` / `ws`）与 **3 个解析失败**（`sse`/`ws` 的 `let rc`、
  `timer` 的四个顶层 `let`）。顺序已写进 §7.13：先改 `rc` → 再收 `timer` 的模块状态 →
  再逐模块补 `pub` + `///` → 最后把示例与 `std/timer` 的冒烟构建纳入回归。
  `std/http` 与 `std/net/core` 的 `pub` 由**同期另一条轨**补齐，本版只按当前源码重测记账。
- **`std/ds` 的能力边界**：只存 `int`；`MinHeap` 是 key-only（句柄打包进 key 低位，或外部
  维护平行 `vec`）；空/满哨兵 `-1` 与元素值同域（存 `-1` 就分不清，需要就自己包一层）；
  没有迭代器；非线程安全。
- **`heap_pop` 的剩余成本是访存不是调用**：20 万元素的堆 1.6 MB，每层跨一条缓存行，
  17.6 层 → 462 ns/次。1 万（80 KB）只要 271 ns，比值 1.7 倍 > 树高比 1.32 倍，差的就是
  缓存未命中。换 mem 块承载也救不了，只有 4 叉堆或 B 树布局才动得了——已写进 §5，本版不做。
- **全量取空时堆比一次性排序慢约 1.8 倍**（92 ms vs 52 ms）：优先队列的价值在"增量插入 +
  只取前 k 个"，要排序结果就直接用 `sort_int`。这条也写进了 `bench/ds_bench.qma` 头注释。
- **测量噪声**：本机 VBS ±50%，且测量期间另一条轨在跑编译，跨进程数字只能看中位与区间；
  唯一可信的是同进程交错的 A/B（§3.18 最后一行）。
- **版本号**：v2.02 已由另一条轨落目录，2.03 `.qla` / 2.04 在代码注释里被预占，本版取
  **v2.05**；收尾时另一条轨又落了 **v2.06**（HTTP 路由 / 中间件），`VERSION` 按
  "与最新版本目录同源"推进到 `2.06.0`（`check_docs.py` 校验）。
