# v3.15 — WaitGroup 长等待改 `WaitOnAddress` park：唤醒延迟 1194 → 55 µs（21.7×）

- 日期：2026-10-30
- 任务：用户要求"继续"；承接 `07-gaps.md` §5 登记的「futex / WaitOnAddress park」
- 影响面：标准库（`std/sync`）、测试（新增 `tests/t170_wg_park.qma`）、文档

## 问题：长等待的唤醒晚一个时钟片

v3.14 修完自旋死循环之后，`bench/wg_bench.qma` 终于能跑出真实基线：
退避版 202 ms / 0% CPU。但它的第 3 段退避是 `sleep_ms(1)` —— 本机
（Windows 默认 15.6 ms 时钟片 + VBS）实际约 **15.6–25 ms**，所以
长等待的唤醒会晚一整个时钟片。这正是 `07-gaps.md` §5 那条缺口。

## 改动

### 1. `std/sync` 接入 `WaitOnAddress` / `WakeByAddressAll`

两者在 **KernelBase.dll**（不在 kernel32）。v1.87 的 `@ffi` 支持显式 DLL 名，
所以**不需要动 PE 导入表白名单** —— 这也是本版能只改 `std/` 一个文件的原因。

```quelmara
@ffi("KernelBase.dll", "WaitOnAddress")
fn _WaitOnAddress(addr: int, compare: int, size: int, ms: int) -> bool

@ffi("KernelBase.dll", "WakeByAddressAll")
fn _WakeByAddressAll(addr: int)
```

`wg_wait` 的三段退避保留前两段，第 3 段换成 park：

| 段 | 条件 | 动作 |
|---|---|---|
| 1 | 前 64 轮 | `spin_hint`（≈0.3 µs） |
| 2 | 到 1088 轮 | `thread_yield`（≈5.6 ms） |
| 3 | 之后 | **`WaitOnAddress`**（睡到被唤醒，CPU 归零） |

### 2. 为什么 park 不需要额外的锁

`WaitOnAddress(p, &cmp, 8, ms)` 的语义是「**若 `*p == cmp` 才睡**，否则立即返回」，
内核在同一个临界区里完成「比较 + 入队」。把 `cmp` 设成**刚刚读到的非零计数**：

- 若 `wg_done` 已把计数减到 0 → `*p != cmp` → 立即返回，回头重读、退出循环；
- 若真的睡下了 → `wg_done` 的 `WakeByAddressAll` 一定能把我们叫醒。

两种情况都不丢唤醒，所以循环只要「读值 → 若非零则 park → 回头重读」。

### 3. 负结果一：`mutex_lock` **不能**用 park

第一版把 `mutex_lock` 的长等待也换成 park，实测**大幅变慢**：

| 线程 × 20 万次加锁 | 原 `thread_yield` 版 | 换成 park |
|---|---|---|
| 4 线程 | 27 ms | 151 ms |
| 8 线程 | 97 ms | 542 ms |
| 16 线程 | **281 ms** | **1568 ms（慢 5.6×）** |

加「先 yield 1024 次再 park」的门槛后仍有 855 ms（慢 3×）。

**根因不是 park 慢，而是判据缺信息**：这个基准的临界区只有约 88 ns，
整个基准才 281 ms；每个线程等锁的时间被切成很多小段（每次几十 µs），
而「已经等多久」这个代理判据无法区分「马上就好」与「要等很久」。
一旦跨过门槛就付 ~400 ns 的 `WaitOnAddress` + 解锁侧的 `WakeByAddressAll`，
比「再 yield 一次、通常立刻就能抢到」还亏 —— park 的唤醒要过内核调度器，
而 yield 的对手往往就在同一个核上。

**结论**：`mutex_lock` 保持 `thread_yield`，代码与注释都记下这个负结果。
park 只对「等待时长 ≫ 系统调用开销、且只等一次」的场景有利 ——
WaitGroup 是，锁不是。

### 4. 负结果二：省系统调用的「parked 计数」会**漏唤醒**

第二版为了省掉「没人睡时的 `WakeByAddressAll`（约 300–400 ns）」，
加了一个 parked 计数（`_park` 进入时 +1、退出时 -1，`wg_done` 读到 0 就跳过 Wake）。

**实测漏唤醒**：等待方刚跨过退避门槛、还没把计数加上的那个窗口里，
`wg_done` 读到 0 跳过了 Wake，等待方一直睡到 1000 ms 兜底超时
（实测 lag ≈ **953 ms**）。

这个窗口**关不掉**：`_park` 的「登记」与 `wg_done` 的「检查」是两次独立的
原子操作，要消除它就得把「减计数 + 检查等待者 + Wake」做成一个原子事务，
而 Win32 没有这样的原语（`WaitOnAddress` 只保证「比较 + 入队」原子，
不保证唤醒者的检查与睡眠者的入队之间有序）。

**处置**：`wg_done` 无条件 `WakeByAddressAll`。代价是每次多约 300–400 ns，
对一个「每个任务调一次」的屏障原语可以接受；**漏唤醒不可接受**。

## 验证

**唤醒延迟（`build/probe_wake2.qma`，200 ms 忙等，交替各 7 次）：**

| 实现 | min | median | max |
|---|---|---|---|
| 旧（`sleep_ms(1)` 片） | 292 µs | **1194 µs** | 1824 µs |
| 新（`WaitOnAddress`） | 24 µs | **55 µs** | 74 µs |

**中位 1194 → 55 µs，21.7×**；最大抖动 1824 → 74 µs。CPU 两者都归零。

> 探针本身也踩过一次坑：第一版让 worker `sleep_ms(ms)`，再算 `wall - ms`，
> 测出来 park 反而"慢 2 倍"。真因是 **Windows 的 sleep 粒度 15.6 ms 把被测的
> 唤醒延迟整个淹掉了** —— 测的是 sleep 抖动，不是唤醒延迟。改成 worker
> **忙等**到精确时刻、把 `wg_done` 前的 `now_ns()` 记下来再相减，才量到真值。
> 教训：**测 µs 级的东西，夹具里不能出现 ms 级的定时器。**

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=332 FAIL=0 SKIP=0**（+1 新夹具见下） |
| `tests/t121_syncmpmc.qma` | `sync mpmc ok` |
| `tests/t170_wg_park.qma`（新增） | `wg park ok` |
| `bench/wg_bench.qma` | 自旋 101% CPU / 退避 0%，与 v3.14 一致 |
| 16 线程 × 20 万次加锁 | 248–324 ms（与改动前的 281 ms 持平，**无回归**） |

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `std/sync.qma` | 新增 `_WaitOnAddress`/`_WakeByAddressAll`/`_WakeByAddressSingle` 的 `@ffi` 声明与 `_park`；`wg_wait` 第 3 段改 park；`wg_done` 无条件 Wake；`mutex_lock` 保持 yield 并记录负结果 |
| `tests/t170_wg_park.qma` | 新增：4 组（唤醒及时性 / 内存可见性 / 多 worker / 反复 spawn-join） |
| `tests/run_win_tests.py` | `[3k]` 段接入 `t170_wg_park`（120 s） |
| `docs/06-status.md` | §3.5b 补 park 的实测数字与两段负结果 |
| `docs/07-gaps.md` | §5「futex / WaitOnAddress park」→ ✅ v3.15 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.15.0 |

## 已知边界 / 遗留

- **只做了 Windows**。Linux 的 `futex(FUTEX_WAIT/FUTEX_WAKE)`（syscall 202）
  没做：`std/sync` 现在含 `@ffi`，在非 PE 后端是**声明期硬失败**，
  与 `std/fs` / `std/logfile` 同口径。Linux 侧要接得先有 epoll/futex 那条线。
  影响面如实说：`std/sync` 之前能在 native 目标编译（只用内建），现在不能了。
  已在 `07-gaps.md` §4 记明。
- **AArch64 无线程**，park 无从验证（`spawn` 不支持）。
- **`WakeByAddressSingle` 已声明但未使用**：`mutex_lock` 不用 park，
  `wg_done` 用 All（计数可能被多个等待者等）。留着是给将来的
  「单等待者屏障」，不用就删。
- **惊群**：`wg_done` 唤醒**所有**在该 wg 上 park 的线程。同一个 wg 通常只有
  一个等待者（fork-join 语义），所以实际不构成问题；但如果将来有人拿一个 wg
  给几十个线程同时 `wg_wait`，会有惊群。要避免得记等待者数量并做
  「Wake 指定数量」——Win32 没有这个原语，只能逐个 `WakeByAddressSingle`。
- **`_park` 的 1000 ms 兜底超时**：正常路径永远用不到（`wg_done` 无条件 Wake），
  它只是防止「将来有人新增一条减计数的路径却忘了 wake」导致永久挂死。
  但这也意味着**真的漏唤醒时表现为「慢 1 秒」而不是「卡死」**，
  排查时容易误判成性能问题。
- **探针未入库**：`build/probe_wake2.qma` 等留在 `build/`（已 gitignore）。
  唤醒延迟的长期基线靠 `tests/t170_wg_park.qma` 的 `BUDGET_US = 500000`
  兜底，它只防「退化成兜底超时」，不测「55 µs 还是 500 µs」——
  µs 级数字在共享 runner 上不可靠（`06-status.md` §3.50 的 ±20% 校准）。
