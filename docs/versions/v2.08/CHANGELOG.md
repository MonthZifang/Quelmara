# v2.08 — `std/timer` 重写：轮询式定时器从"编译不过"到可用（标准库「定时器」新增行 → ✅）

- 日期：2026-10-24
- 任务：延续"一次只把一个模块补成绿色"的口径。上一版（v2.05）补完 `std/ds`，本版补它的
  唯一消费者 `std/timer`——这一项同时压在 `07-gaps.md` §7.13 的 **A（解析失败）** 和
  **B（0 个 `pub`）** 两栏里，是"补一个模块清两条账"的最短路径。
- 影响面：标准库（`std/timer`）、测试（含 LSP 负向期望）、基准、文档

## 主事件

`std/timer` 之前**从来没有编译过**，三个独立的阻断：

1. **四个顶层 `let`**（`_heap` / `_due` / `_alive` / `_stamp0`）——parser 只认顶层
   `fn/struct/test/module/import`，`import` 就报 `顶层期望 fn/struct/test/module/import`。
2. **调不存在的内建 `now_ms()`**——语言只有 `now_ns()`（单调纳秒）与 `wall_ms()`（墙钟毫秒）。
3. **0 个 `pub`**——即使前两条修好，用户代码一引用仍然 `引用了非 pub 声明`。

修法：

- **状态从 `vec` 搬到 mem 块**：`vec` 句柄存进 `static_word` 再取回来会丢类型标签
  （`v.push` 报"不支持方法"），所以堆与存活表都落在裸内存里，句柄就是一个 `int`——
  与 `std/http` 的连接状态、`std/gzip` 的 CRC 表同一套路。
  - 堆块：`[cap, len]` + `keys[cap]` + `ids[cap]`（16 + 16·cap 字节），指针在 `static_word(13)`
  - 存活块：`[cap, len]` + `alive[cap]`（16 + 8·cap 字节），指针在 `static_word(14)`，
    `alive` 按 **id-1** 索引（id 从 1 递增、永不复用）
  - 两个块都按 2 倍扩容（`mem_copy` 旧内容 + `mem_free`）
- **排序键 = (到期时刻, id)**：同一时刻到期的按创建顺序出堆——测试与调试可复现。
- **`timer_poll` 从 O(n) 变 O(log n)**：原实现每次弹堆后线性扫 `_due` 找 id；现在 id 与
  到期时刻一起进堆，弹到即返回。取消只清存活位（O(1) 不搬堆），到期时静默丢弃。
- **上浮/下沉用"挖洞"**（与 v2.05 的 `std/ds` 同一写法）：每层"读 2 写 1"。
- **API 4 → 5**：新增 `timer_clear()`（释放两块、id 从 1 重来），`timer_after` /
  `timer_cancel` / `timer_poll` / `timer_pending` 全部补 `pub` + `///`。
- **顺手修掉一个真实的静态字冲突**：`timer` 原来用 `static_word(12)`，与 `std/aes` 的
  sbox 表指针撞车——同时用 HTTPS 与定时器的进程会把 sbox 指针踩成堆指针。改用 13/14，
  并在 `02-language.md` 补了一张**静态字占用表**（0–2 协议库 / 6 gzip / 8 rand / 9 log /
  11 全局锁 / 12 aes / 13·14 timer）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/timer.qma` | 全文重写（137 → 274 行）：mem 块状态 + `static_word(13)/(14)`、`now_ns()`、5 个 `pub` + `///`、堆存 (due, id)、挖洞上浮/下沉、O(1) 取消、`timer_clear` |
| `tests/t132_timer.qma` | 新增回归（7 组）：id 序列 / 到期顺序 / 同 due 按 id 兜底 / cancel 幂等与越界 / 2000 个定时器（触发多次扩容）/ clear 复位 / 全弹空哨兵 |
| `bench/timer_bench.qma` | 新增基准：10 万个 push / pending 扫描 / 到期后 drain / 2 万个 cancel / 全取消后 drain（跳过路径） |
| `tests/lsp_test.py` | 容错索引的**负向期望**里去掉 `std/timer.qma`（它现在能过 `qlm.Parser`），改成与 `std/http.qma` 同款**正向钉住**；B 段说明同步（并行轨随后把这四条整理成 `neg`/`pos` 两组，断言 38 → 42） |
| `tests/run_win_tests.py` | 注册 `t129_ds`（v2.05）与 `t132_timer` |
| `docs/03-stdlib.md` | 重新生成：62 个模块 / **528 个公开函数**；`std/timer` 从 `0 / 4` 变 **`5 / 9`** 并列出全部签名 |
| `docs/07-gaps.md` | §2 **新增「定时器」行 ✅ v2.08**、数据结构行回到 ✅ v2.05（被并行轨整份重写时覆盖，本版重新落盘）；§5 新增两条（ds 挖洞 / timer poll 扫描）；§7.13 按源码重测：10 模块 141 声明 → **6 模块 69 声明**，解析失败 4 → **2**；§8 补 ds/timer |
| `docs/06-status.md` | 新增 **§3.19**（ds 单价 + 同进程 A/B）与 **§3.20**（timer 单价）；§6 风险行 10 模块 → 6 模块 |
| `docs/02-language.md` | 新增**静态字占用表** + 撞车记录；`mem_free(p)` → `mem_free(p, n)`（v2.05 修，写 `rb_free` 时踩到） |
| `docs/05-toolchain.md` | §5.1 夹具计数 144/18/24 → **148/19/30** |
| `docs/versions/v2.05/CHANGELOG.md` | v2.05（`std/ds`）日志，与本版一起待提交 |

## 实测（`06-status.md` §3.20，10 万个定时器，同一条命令 8 次中位）

| 负载 | 中位 | 区间 |
|---|---|---|
| `timer_after`（含 3 次 2 倍扩容） | **130 ns/次** | 112–139 |
| `timer_poll`（全部到期后弹空） | **454 ns/次** | 367–520 |
| `timer_cancel` | **7 ns/次** | 2–12 |
| `timer_pending`（O(n) 扫描 10 万项） | **168 µs** | 133–228 |
| 全取消后 drain（每项跳过） | **236 ns/项** | 196–297 |

> `poll` 454 ns 与 `std/ds` 的 `heap_pop` 462 ns 几乎相同——两个模块的堆下沉是同一套
> 挖洞写法，瓶颈也同一处：17.6 层 × 每层跨一条缓存行。`after` 130 ns 是因为随机到期
> 时刻上浮平均 1.4 层就停。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=281 FAIL=2 SKIP=1**（本版新增 `t129_ds` / `t132_timer` 均通过；2 个 FAIL 都不是本版代码：`cache_test` 在并行轨同时构建时抢 `build/` 目录（单独跑 24/0），`qla_test` 撞沙箱批量删除策略） |
| `python tools/stage0/qlm_cli.py run tests/t132_timer.qma --target win` | 退出码 0，打印 `timer ok`（连跑 5 次稳定） |
| `python tools/stage0/qlm_cli.py run bench/timer_bench.qma --target win` | 见 `06-status.md` §3.20 |
| `python tests/lsp_test.py` | **PASS=42 FAIL=0**（负向 `sse`/`ws` + 正向 `http`/`timer` 四条钉住） |
| `python tools/dev/gen_stdlib_doc.py --check --require-doc` | PASS（62 个模块 / 528 个公开函数） |
| `python tools/stage0/qlm_cli.py doc std --missing` | PASS（全部公开声明有 `///`） |
| `python tools/dev/check_docs.py` / `check_names.py` / `check_origin.py` | 全 PASS |

## 已知边界 / 遗留

- **轮询式**：没人调 `timer_poll` 就不会触发（没有后台线程、没有回调）。这是刻意设计
  （游戏帧循环 / 服务器事件循环友好），不是缺陷；要异步就得配线程 + chan。
- `timer_pending` 是 **O(n) 扫描**（诊断用）。要 O(1) 得再维护一个计数器，等真有调用方再说。
- 取消不搬堆：被取消的项留在堆里，到期时弹出来丢掉（drain 时 236 ns/项）。换来取消 O(1)。
- 非线程安全；进程退出不清理（`timer_clear` 要自己调）。
- **`std/timer` 与 `std/ds` 现在是两套独立的堆实现**：timer 要 mem 块（状态得跨调用存活），
  ds 的堆是 `vec` 句柄（调用方持有）。等语言层支持"vec 句柄进静态字"或"泛型容器"再合并。
- `§7.13` 剩 **6 个模块 69 个声明 + 2 个解析失败**（`sse`/`ws` 的 `let rc`）。下一版按
  §7.13 的顺序先做 `std/core`（4 个声明，一次解开 `log`/`rand`/`sse`/`ws` 的引用）。
- **文档并行轨冲突**：本版与 v2.05 的 `07-gaps.md` / `06-status.md` / `tests/run_win_tests.py`
  改动曾被同期另一条轨整份重写覆盖过一次，本版已重新落盘；提交前请以工作区为准复核这三处。
