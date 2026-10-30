# v3.16 — 把 park 拆成 `std/park`：修掉 v3.15 引入的跨平台回归

- 日期：2026-10-30
- 任务：用户要求"继续"；本意是接着做 Linux futex，第一步验证 v3.15 的
  跨平台状态时**发现 v3.15 已经破坏了 native/arm64 编译**
- 影响面：标准库（新增 `std/park`，`std/sync` 改为注入式）、
  基准（`bench/wg_bench.qma` 注入 park）、测试（`t170` 注入 park）、文档

## 问题：v3.15 把 `std/sync` 钉死在 Windows PE 上了

v3.15 为做 `WaitOnAddress` park，把三条 `@ffi` 声明直接写进了 `std/sync.qma`。
而 `@ffi` 只在 **Windows PE** 后端实现（ELF 后端产静态可执行文件、无
`PT_INTERP`/动态链接器，外部符号无处解析），于是：

```
$ python tools/stage0/qlm_cli.py build tests/t122_syncport.qma --target native
SyntaxError: 函数 _WaitOnAddress 声明为 @ffi("KernelBase.dll", "WaitOnAddress")：
@ffi 只在 Windows PE 后端实现……请用 --target win 构建
```

`--target arm64` 同样报错。**`std/sync` 在这之前是能在这两个后端编译的。**

这不只是"少了个平台"，它**直接打红 CI**：`tests/run_native_tests.sh` 的
`[7]` 段会编 `t122_syncport.qma` 到 AArch64 并在模拟器里执行：

```
$NAT2 build tests/t122_syncport.qma -o build/t122_a64
out=$(timeout 600 python3 tests/a64_emu.py build/t122_a64)
[ "$out" = "sync port ok" ] && ok "a64 t122 std/sync => sync port ok" || bad ...
```

v3.15 提交时**没有跑这条**（它只在 Linux CI job 里），而我当时的验证全在
Windows 主回归上 —— 主回归 333 项全绿，CI 会红。这是"本机能过 ≠ CI 能过"
的又一次实例，与 v3.11 记的「端到端没进主回归」是同一类问题：
**验证矩阵里少了一格，那一格就会烂掉。**

## 改动

### 1. 新增 `std/park`（含 `@ffi`，只编 Windows PE）

把 v3.15 写在 `std/sync` 里的三条 `@ffi` 与 `_park` 整体搬出来，成为独立模块：

| 函数 | 说明 |
|---|---|
| `park_available()` | 恒为 1（能编到这里的后端一定支持） |
| `park_on(p, want, ms)` | park 到 `*p != want` 或超时；返回 1=被唤醒 / 0=超时 |
| `wake_all(p)` | 唤醒所有等待者（无等待者时是安全的空操作） |
| `wake_one(p)` | 唤醒一个（仅在"唤醒一个就够"时用） |

### 2. `std/sync` 改为**注入式**，零 `@ffi`

`std/sync` 不能 `import std.park` —— 那会把 `@ffi` 的声明期失败传染回来。
改成两个 `static_word` 存函数指针，由调用方显式注入：

```quelmara
pub fn sync_set_park(park_fn: int, wake_fn: int)   // 传 0 = 恢复纯退避
pub fn sync_has_park() -> int
```

函数值在 Quelmara 里就是代码地址（`02-language.md` §4：函数名作值 /
`let` 绑定 / 通过值调用走 `callr`），所以存进 `static_word` 再 `f(...)` 调用即可。

`wg_wait` 第 3 段因此变成：

```quelmara
if sync_has_park() == 1 {
    _park(w, cur, 1000)
} else {
    sleep_ms(1)          // 退回 v1.98 的三段退避
}
```

**不注入时语义仍然正确**，只是长等待的唤醒晚一个时钟片（本机 15.6–25 ms）。
`wg_done` 的 `_wake_all(w)` 在未注入时是空操作，代价为零。

### 3. 调用方显式注入

| 文件 | 改动 |
|---|---|
| `bench/wg_bench.qma` | `import std.park` + `sync_set_park(park_on, wake_all)` |
| `tests/t170_wg_park.qma` | 同上，并加 `[0]` 组断言注入成功 |

**为什么是显式注入而不是"自动启用"**：自动启用只能靠 `import`，而 `import`
正是要避免的传染路径。显式注入把"要不要 park"的决定权交回调用方 ——
这也符合项目一贯的"能力边界写在调用点"的取向。

## 验证

| 命令 | 结果 |
|---|---|
| `build tests/t122_syncport.qma --target native` | **编过**（v3.15 是 SyntaxError） |
| `build tests/t122_syncport.qma --target arm64` | **编过** |
| `python tests/a64_emu.py build/t122_a64.elf` | `sync port ok`（**CI 的 `[7]` 段恢复**） |
| `python tests/run_win_tests.py` | **PASS=333 FAIL=0 SKIP=0**（无回归） |
| `tests/t170_wg_park.qma` | `wg park ok`（含注入断言） |
| `bench/wg_bench.qma` | 自旋 101% CPU / 退避 0%，wall 200 ms（v3.15 是 202 ms） |

**park 收益仍在**（`build/probe_wake3b.qma`，200 ms 忙等，交替各 7 次）：

| 模式 | min | median | max |
|---|---|---|---|
| 不注入（纯退避） | 64 µs | **622 µs** | 1488 µs |
| 注入 park | 30 µs | **44 µs** | 102 µs |

**中位 622 → 44 µs（14×）**。数字比 v3.15 记的 21.7× 小，因为这次对照组是
**不注入的 `wg_wait`**（自旋 → 让出 → sleep 片），而 v3.15 的对照组是
手写的 `wg_wait_old`。两者的 sleep 段行为相同，差异在噪声范围内
（`06-status.md` §3.50：本机测量分辨率 ±20%）。**量级结论不变。**

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `std/park.qma` | **新增**：`@ffi` + `park_on` / `wake_all` / `wake_one` / `park_available` |
| `std/sync.qma` | 删掉全部 `@ffi` 与 `_park`；新增 `sync_set_park` / `sync_has_park`；`_park`/`_wake_all` 改走注入的函数指针；`wg_wait` 无注入时退回 `sleep_ms(1)` |
| `bench/wg_bench.qma` | 注入 park |
| `tests/t170_wg_park.qma` | 注入 park + `[0]` 断言组 |
| `docs/06-status.md` | §3.5b.1 补注入式说明与新 A/B 数字 |
| `docs/07-gaps.md` | §4 Linux 行改为"v3.16 已恢复跨平台编译"；§5 补 `std/park` 拆分说明 |
| `docs/03-stdlib.md` | `gen_stdlib_doc.py` 重生成（新增 `std/park` 模块） |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.16.0 |

## 已知边界 / 遗留

- **Linux 的 futex 仍未做**。`std/park` 现在只编 Windows PE；Linux 侧要么
  在 `std/park` 里加 `syscall 202`（futex）分支，要么另开 `std/park_linux`。
  前者更对，但 `@ffi` 与 syscall 的混合需要后端支持"按目标选实现"——
  语言层目前没有这个机制（`07-gaps.md` §4 记着）。
- **注入是全局状态**（`static_word`），一个进程只能有一套 park 实现。
  对当前用途（进程级 park 原语）够了；将来若要"同一进程里混用两套"
  就得把函数指针塞进同步对象里。
- **未注入时 `wg_done` 仍会调 `_wake_all`**（读一个 0 然后返回），
  每次约几 ns。可以加 `if` 省掉，但那是给热路径加分支，收益不明，
  没做。
- **`wake_one` 已导出但无调用方**：它的语义有陷阱（被唤醒者可能立刻
  又睡回去，其余等待者就收不到），只在"单等待者"时安全。留着是因为
  `WaitOnAddress` 的对称 API 缺一个会让人以为没实现；文档里写明了边界。
- **CI 的 `[7]` 段这次是本机用 `a64_emu.py` 复现的，不是真跑 CI**。
  判据一致（同一条命令），但真正的确认要等下一次 CI。
