# v3.47 — 函数名作值 + int 间接调用；覆盖率 46 → 48

- 日期：2026-10-31
- 任务：用户要求"继续"；按 v3.46 结论做「函数值调用」这个共同卡点
- 影响面：`bootstrap/qlmc/qlmc.qma`（2 个新 opcode + 2 个原子例程 +
  6 个内建）、`tests/t190_qlmc_intcall.qma`、`tests/run_win_tests.py`
- 覆盖率：**46 → 48**（`std/sync` + `std/log` 通过）
- 回归：PASS=363 → **364** FAIL=0 SKIP=0

## 核心：函数值语义补全（两条，缺一不可）

`02-language.md` §4 写着「函数值就是代码地址」。qlmc 以前**两条都没实现**：

| 语义 | 以前 | 现在 |
|---|---|---|
| `let f = twice`（函数名作值） | `未定义变量 twice` | `OP_LEAFN` 取地址 |
| `let f = <int>; f(...)`（int 存地址后调用） | `未定义函数 f` | 新 opcode `OP_CALLV` |

**第一条**在 `E_VAR` 的 lowering 里加分支：先试变量（词法作用域优先，
局部变量可遮蔽同名函数），没有变量再看是不是函数，是就发 `OP_LEAFN`。
`_ty_of_expr` 的 `E_VAR` 分支同步改（函数名 → `TY_INT`）。

**第二条**新增 `OP_CALLV = 79`：`dst = call a`，`a` **就是**代码地址。
与 `OP_CALLR` 的区别是后者做 `r11 = [a]; call r11`（a 是闭包值的地址）。

为什么必须有它：`std/sync` 的 park 注入是
`let f = mem_load64(static_word(SLOT), 0)` 然后 `f(p, want, ms)` ——
`f` 是 **TY_INT**，走不了闭包那条路。

`OP_CALLV` 同时登记进 `cp[]` 的调用屏障（否则跨它的临时值会被
caller-saved 冲掉）。

```
[PASS] 函数名有非零地址
[PASS] 单参间接调用（21 -> 42）
[PASS] 三参间接调用（10+20+12 = 42）
[PASS] static_word 槽往返后地址不变
[PASS] 通过槽里读出的地址调用（5 -> 10）
=== t190 ok ===
```

## 顺带补的 6 个内建（都是 std/sync / log 的依赖）

| 内建 | 实现 | 备注 |
|---|---|---|
| `atomic_add(addr, v)` | `lock xadd [rcx], rdx` | 返回旧值 |
| `atomic_cas(addr, exp, new)` | `lock cmpxchg [rcx], rdx` | 实参约定：rcx=地址、rdx=新值、r8=expect |
| `spin_hint()` | `pause`（`F3 90`） | 新 opcode `OP_SPIN = 80` |
| `sleep_ms(ms)` | `Sleep` | 与 thread_yield 区分：yield 让时间片，sleep 至少等 |
| `mem_load_acq(addr)` | 普通 `mov` | x86 TSO 下零成本 |
| `mem_store_rel(addr, v)` | 普通 `mov` | 同上；AArch64 才需要 LDAR/STLR |
| `net_config(key)` | 编译期常量 | 见下 |

两个原子例程是**手写机器码**（`_gen_atomic_add` / `_gen_atomic_cas`），
比 stage-0 的 LL-SC 循环简单得多 —— x86 有硬件 lock 前缀。

## `net_config` 的取舍

stage-0 的 `net_config(key)` 读根目录 `Quelmara.toml` 的 `[net]` 节。
qlmc **没有 TOML 解析器**，所以这里用与 `Quelmara.toml` **当前值一致**的
默认值（max_conns=1000000 / recv_buffer=4096 / io_threads=1 /
tcp_nodelay=1）。

理由：配置解析要一个 TOML 子集解析器 + 文件 I/O，而它唯一的消费者就是
这四个数字。等真有需求再做成 `-D key=value` 命令行开关。这条限制写在
内建的注释里。

## 覆盖率 46 → 48

`std/sync.qma`（7168 字节）和 `std/log.qma`（16384 字节）现在都能编过。

**还剩 `std/net/reactor.qma`**，卡在 `thread_start`（OS 线程入口 ABI，
要 `CreateThread` + 参数块传递，成本明显高于本版所有其它内建）。

## 回归与自举

```
PASS=364 FAIL=0 SKIP=0
自举五级链：stage-2 可用且与 stage-1 逐字节等价（30/30 组，不动点成立）
```
