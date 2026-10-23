# v1.98 — 并发行转绿：A64 原子原语 + MPMC 栈 + WaitGroup 退避

- 日期：2026-10-24
- 任务：把语言层「并发」这一行（🟡）一次做完翻绿——`chan`/栈 pop 的 ABA、
  WaitGroup 自旋烧核、AArch64 未接 atomic 三件事一起收口，同步文档并实测性能
- 影响面：语言 / 标准库 / 编译器（x86-64 + AArch64 发射层）/ 文档

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_arm64.py` | 编码器新增 `LDAXR`/`STLXR`/`CLREX`/`LDAR`/`STLR`/`DMB ISH`/`YIELD`/`MRS CNTVCT_EL0`；发射层接上 `xchg`/`atomic add`/`atomic cas`/`ldar`/`stlr`/`mfence`/`pause`/`rdtsc` 八种 IR 指令；新增 `fetch_fixed()` 保证 LL-SC 序列的四个操作数互不重叠 |
| `tools/stage0/qlm_native.py` | 去掉 `atomic_add`/`atomic_cas`/`atomic_fence`/`mem_xchg`/`now_cycle` 的"仅 x86_64"拦截；新增内建 `mem_load_acq`/`mem_store_rel`（acquire/release 访存）、`thread_yield()`、`cpu_ns()`（进程 CPU 时间）与运行时 `__cpu_ns`；x86 发射层补 `ldar`/`stlr`（TSO 下就是 `mov`，零额外指令） |
| `tools/stage0/qlm_opt.py` | `vreg_mentions` / `_EFF` / copy-prop 三处登记 `ldar`/`stlr`——顺序语义是它们存在的理由，调度器不许跨越 |
| `tests/a64_emu.py` | 模拟器新增 8 条指令的解码（LL/SC 带状态字、监视器、`CNTVCT` 计数），使 A64 原子路径可执行级验证 |
| `std/sync.qma` | `stack_pop` 改为 **MPMC 安全**（每栈一把消费者锁再 CAS head，结构性消除 ABA）；新增 `stack_pop_single`（单消费者快路径）；`mutex_unlock` 改 release 存储；`mutex_lock`/`wg_wait` 改三段退避（`pause` → `thread_yield` → `sleep_ms(1)`） |
| `tests/t97_a64atomic.qma` | 已在库中，本版起真正双后端通过（此前 A64 侧 lowering 直接报"仅 x86_64"） |
| `tests/t121_syncmpmc.qma` | 新增：2 生产者 / 2 消费者 MPMC 压测（计数 + 和 + 异或三重校验）、`stack_pop_single` 语义、WaitGroup 长等待 |
| `tests/t122_syncport.qma` | 新增：`std/sync` 双后端可移植性（无 `spawn` 的无争用路径），A64 走模拟器执行 |
| `bench/sync_bench.qma` | 扩到 7 个形状（加 `stack_pop_single` / `chan` / `wg_wait` 检查成本） |
| `bench/wg_bench.qma` | 新增：自旋 vs 退避的 CPU 成本对照（`now_ns` + `cpu_ns`） |
| `bench/chan_bench.qma` | 新增：chan 双线程 ping-pong 往返延迟 |
| `docs/02-language.md` | §7.3 重写为双后端对照表（含新内建与边界）、§7.4 加 `cpu_ns`、§8.5 并发模型表重写 + chan 抢锁策略的实测结论；内建函数计数 69 → 73 |
| `docs/03-stdlib.md` | 重新生成（58 个模块 / 385 个公开函数） |
| `docs/06-status.md` | §1 更新 PE 回归与 irdiff 数字；§3.5 换成同环境 A/B 表，新增 §3.5b（WaitGroup CPU）与 §3.5c（chan 抢锁 A/B 否决记录） |
| `docs/07-gaps.md` | §1「并发」行 🟡 → ✅（写清边界）；§4 AArch64 行去掉 atomic；§5 登记"chan 先自旋无收益（已回滚）"与"futex park 待做"；§8 推进顺序标记完成 |
| `tests/run_win_tests.py` / `tests/run_native_tests.sh` | 注册 `t97_atomic` / `t121_syncmpmc` / `t122_syncport`，A64 段加 t97 与 t122 的执行级检查 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=266 FAIL=0 SKIP=1**（SKIP 为 WSL 交叉验证被沙箱拦） |
| `python tests/irdiff.py` | **PASS=89 FAIL=0 SKIP=68**（t97 / t122 从 SKIP 转 PASS） |
| `python tools/dev/check_names.py` / `check_origin.py` | PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（58 模块 / 385 公开函数） |
| `python tests/a64_emu.py build/t97_a64` | `a64 atomic ok`（LL/SC 序列执行级） |
| `python tests/a64_emu.py build/t122_a64` | `sync port ok`（`std/sync` 在 A64 上跑通） |
| 三个并发基准 | 数字见 `docs/06-status.md` §3.5 / §3.5b / §3.5c |

编码器独立核对：8 条新指令的机器码用 capstone 反汇编逐条验证（`ldaxr x0,[x17]` /
`stlxr w3,x2,[x17]` / `clrex` / `dmb ish` / `yield` / `mrs x0,cntvct_el0` / `ldar` / `stlr`），
与模拟器是两套独立实现；产物反汇编确认 `atomic_add` = `ldaxr`+`add`+`stlxr`+`cbnz` 回边、
`atomic_cas` = `ldaxr`+`cmp`+`b.ne`+`stlxr`+`cbnz`+`clrex`。

## 已知边界 / 遗留

- **AArch64 仍无线程**（`spawn`/`parfor` 未接），所以 A64 上的并发原语只能单线程用；
  `std/sync` 在 A64 能编译能跑，但没有并发语义可验证。
- **`wg_wait` 不是 futex park**：长等待唤醒粒度 = 一个 `sleep_ms(1)`（本机约 25 ms）。
  想同时要低延迟与低 CPU 得上 `futex`/`WaitOnAddress`，已登记 `07-gaps.md` §5。
- **ABA 的表述要修正**：旧 `stack_pop` 的正确性其实依赖"节点地址永不复用"
  （库不 free 节点，所以 2P/2C 压测跑 10 次也不复现）。v1.98 把这条隐含前提变成
  显式保证，代价 19 cycles/pop——**这不是"修了一个能复现的 bug"，是"拆掉一个定时炸弹"**。
- `chan` 抢锁"先自旋"实验无收益，已回滚（§3.5c）。
- `VERSION` 与并行轨的版本号可能再次交错：本版把 `VERSION` 提到 `1.98.0`。
