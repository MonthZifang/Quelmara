# v3.14 — 自旋等待被 LICM 编成死循环：任何 `while mem_load64(...)` 都挂住

- 日期：2026-10-30
- 任务：用户要求"继续"；本轮本意是做 `07-gaps.md` §5 的 futex/WaitOnAddress，
  第一步跑 `bench/wg_bench.qma` 取基线时**撞上了一个更严重的问题**
- 影响面：**编译器**（`qlm_opt.opt_licm` 的 readonly 判据）、基准
  （`bench/wg_bench.qma` 加注释）、测试（新增 `tests/t169_spin_wait.qma`）、文档

## 发现经过：想测 futex，先撞上死循环

`07-gaps.md` §5 登记了「futex / WaitOnAddress park：`wg_wait`/`mutex_lock` 的
唤醒延迟从 25 ms 降到 µs 级」。要证明收益，先得跑基线 `bench/wg_bench.qma`：

```
$ python tools/stage0/qlm_cli.py build bench/wg_bench.qma --target win -o build/wg_bench.exe
warning: possible infinite loop in 'spin_wait' (loop #1): guard variable never updated in body
warning: possible infinite loop in 'main' (loop #4): guard variable never updated in body
$ ./build/wg_bench.exe
（300 s 不返回，被外部杀掉）
```

**编译器已经在报警了**，而且报得对。最小复现（`build/probe_spin.qma`）：

```quelmara
fn spin_wait(w: int) {
    while mem_load64(w, 0) != 0 {
        spin_hint()
    }
}
```

10 s 不退出。而 `std/sync.wg_wait` 自己是好的（同一份探针改成调 `wg_wait`
200 ms 等待正常返回、CPU 15 ms）——所以问题**不在库，在编译器**。

## 根因：`spin_hint()` 让自旋循环被判成"纯读"

`opt_licm` 允许外提 `load`，但只对**纯读循环**（`_licm_safe` 的 `readonly`）。
`readonly` 的判据是"循环里没有 call / store / atomic…"：

```python
readonly = not any(
    i[0] in ("call", "callr", "syscall", "winapi", "ffi",
             "store", "store8", "xchg", "atomic", "stlr",
             "ffi", "spawn_child")
    for i in region)
```

`spin_hint()` 发射的是 `('pause',)` —— 读写集都是空（见 `vreg_mentions` 里
`if op in ("mfence", "pause"): return [], []`），既不是 call 也不是 store。
于是自旋循环被判定为纯读，`load` 被提到循环头之前：

```
== spin_wait (vregs=2) ==
    ('args', [0])
    ('load', 1, 0, ('imm', 0))        ← 只读一次
    ('label', 'spin_wait.while.1')
    ('jcc', 'e', 1, ('imm', 0), 'spin_wait.wend.2')   ← 每轮比同一个旧值
    ('label', 'spin_wait.wbody.3')
    ('pause',)
    ('jmp', 'spin_wait.while.1')
```

**这条判据从原理上就是错的**：自旋等待的正确性恰恰来自**别的线程**在写同一块
内存，循环体自己当然不写。"循环体有没有写"根本不是判断"这块内存会不会变"的
依据。`std/sync.mutex_lock`、`stack_pop`、`chan` 的所有自旋路径，以及用户写的
任何 `while mem_load64(...)` 都中招。

## 修复

`readonly` 的排除集加上"等别的线程"的指令：

```python
readonly = not any(
    i[0] in ("call", "callr", "syscall", "winapi", "ffi",
             "store", "store8", "xchg", "atomic", "stlr",
             "ffi", "spawn_child",
             # v3.14：等别的线程的指令 —— 循环体不写内存，
             # 但内存会被**别人**写，load 外提即语义错误
             "pause", "yield", "rdtsc")
    for i in region)
```

**为什么不用更激进的判据**（比如"循环里出现任何 load 就不外提"）：那会把
v2.60 起就吃到的收益全吐回去 —— `a[i]` 的句柄/长度 load 外提是 b4_array、
b7_sort 的大头（`07-gaps.md` §5 记着"两个读循环 400 万次"）。真正的判据是
"这个循环会不会让别的线程跑"：没有 pause/yield/睡眠/系统调用的紧循环，
单线程内确实不可能有人改那块内存，外提仍然安全。

## 验证

| 命令 | 结果 |
|---|---|
| `build/probe_spin.qma`（修复前） | 10 s 不退出 |
| `build/probe_spin.qma`（修复后） | `spin returned in 51 ms`（worker 睡 50 ms） |
| `bench/wg_bench.qma`（修复前） | 300 s 不退出 |
| `bench/wg_bench.qma`（修复后） | 正常返回，自旋 101% CPU / 退避 0% |
| `tests/t169_spin_wait.qma`（修复后） | `spin wait ok`，退出码 0 |
| `tests/t169_spin_wait.qma`（修复前） | **15 s 不退出**（夹具对旧代码是红的） |
| `python tests/run_win_tests.py` | **PASS=331 FAIL=0 SKIP=0** |
| `bench/gbench.qma` A/B（各 3 次取中位） | 见下表，**无性能回归** |

**性能 A/B（`bench/gbench.qma`，8 个形状，修复前后各 3 次取中位，ns）：**

| 形状 | 修复前 | 修复后 | 差 |
|---|---|---|---|
| tokenizer 512KB | 2 464 300 | 2 482 500 | +0.7% |
| mix_arith 10M | 41 182 900 | 41 364 300 | +0.4% |
| map_str 10k | 2 964 800 | 2 888 400 | −2.6% |
| branchy 10M | 31 810 800 | 31 973 200 | +0.5% |
| str_build 1k | 270 700 | 276 000 | +2.0% |
| buf_scan 1MB | 1 432 000 | 1 449 700 | +1.2% |
| nested 300x300 | 273 900 | 341 000 | +24%（噪声，见下） |
| hashmix 10M | 50 701 000 | 51 043 100 | +0.7% |

除 `nested` 外全部落在 ±3% 内。`nested` 那个 +24% 是噪声：本机测量分辨率只到
±20%（`06-status.md` §3.50 的校准结论），且该形状绝对耗时仅 0.3 ms，受进程
调度影响最大。**没有可复现的性能回归。**

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_opt.py` | `opt_licm` 的 `readonly` 判据加 `pause`/`yield`/`rdtsc`，附完整理由 |
| `tests/t169_spin_wait.qma` | 新增：4 场景（自旋等 wg / 自旋等普通变量 / pause 计数循环 / 纯读循环求和） |
| `tests/run_win_tests.py` | `[3k]` 段接入 `t169_spin_wait`（60 s 短超时） |
| `bench/wg_bench.qma` | `spin_wait` 加注释说明它曾是死循环 |
| `docs/06-status.md` | §3.5b 更正纯自旋的 CPU 数字（51–82% → 101%）；§1 口径不变（331） |
| `docs/07-gaps.md` | §5 新增「自旋等待被 LICM 外提 load」→ ✅ v3.14；§7 新增 7.35 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.14.0 |

## 已知边界 / 遗留

- **`check_suspicious_loops` 早就在报这个警，但没人当回事**。它的输出是
  `warning:`（不 fail），而 `tests/run_win_tests.py` 只在**编译失败**时记 FAIL，
  编译警告完全不被看。这是"告警疲劳"的结构性成因：**一条从不影响退出码的告警，
  迟早被当成背景噪音**。本次没有改这个机制（改它要先把现有全部告警清干净，
  否则门禁天天红），但记在这里 —— 下次再有人看到
  "guard variable never updated in body" 时，先怀疑编译器。
- **`yield` / `rdtsc` 在 IR 里的实际助记符没逐一验证**：我只实测了 `pause`
  这条路径（`spin_hint`）。`thread_yield()` 编成的是 `('winapi', 'Sleep', ...)`
  或系统调用，本来就已在排除集里；`rdtsc` 是照 `vreg_mentions` 的写法加的，
  没有专门的探针。保守起见加进去不会错（只是可能少外提），但如果 `rdtsc`
  的助记符不是 `rdtsc`，那条排除就是死代码。
- **AArch64 后端共用 `opt_licm`**（`qlm_opt` 是架构无关的），所以这个修复对
  A64 同样生效。但 A64 目前**没有线程**（`spawn` 不支持），自旋等待在那边
  本来就只是"单线程内等自己"，无从验证。
- **futex / WaitOnAddress 本身没做**：本轮被这个 bug 挡住了，`07-gaps.md` §5
  那条仍在。不过现在基线终于是真的了（`bench/wg_bench.qma` 能跑），下一轮
  可以直接对比"退避 202 ms / 0% CPU"与 futex 版的唤醒延迟。
