# v3.62 — 模块作用域：同名私有声明按模块隔离；覆盖率 64 → 67

- 日期：2026-11-01
- 任务：用户要求"继续优化或执行"。v3.61 把跨模块 struct **类型**打通之后，
  剩下三个模块卡在**同名声明**上（`_Ck` / `_fail` / `_get`），本版收口。
- 影响面：`bootstrap/qlmc/qlmc.qma`（模块作用域）、
  `tests/selfhost/s38_modscope.qma` + `mod_dup_a/b.qma`、
  `tests/t197_qlmc_thread.qma`（修偶发）、`tests/qlmc_test.py`、
  `tools/dev/qlmc_coverage.py`（`BASELINE` 64 → 67）
- 覆盖率：**64 → 67**（一次解开 `std/httpc_net` + `std/http` + `std/logfile`）
- qlmc 差分：39 → **40**

## 问题：同名私有声明被当成同一个

v3.61 之后这三个模块的报错变成：

```
std/httpc_net.qma: line 193: struct 重复声明 _Ck
std/http.qma:      line 413: 函数重复定义 _fail
std/logfile.qma:   line 48:  函数重复定义 _get
```

**根因**：qlmc 完全不做 `pub` 可见性检查（`pub` 当无操作），于是不同模块里
同名的私有声明被当成同一个名字。stage-0 从 v1.99 起就有 per-module mangling
（只在真重名时给导入方加 `<模块>__` 前缀），qlmc 没有。

## 关键判断：不能"允许重复、取第一个"

第一反应是"既然签名一样，放行就行"。**但这个想法在这三个模块上全是错的**：

| 名字 | 模块 A | 模块 B | 后果（若取第一个） |
|---|---|---|---|
| `struct _Ck` | `std/httpc`：**3 字段** | `std/httpc_net`：**7 字段** | 字段偏移全错 |
| `fn _fail` | `std/http`：`(int) -> int` | `std/net/reactor`：`(str)` → void | `str` 当 `int` 传 |
| `fn _get` | `std/log` | `std/logfile` | 这一对**恰好完全相同** |

前两个是**静默错编**的形状：不崩、不报错，只是结果错。这正是
`docs/08-handoff.md` §4.3 记的最难抓的那类缺陷。所以必须真的按模块隔离，
不能靠"签名碰巧一致"。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `stt` 尾部加三个模块号区 + `_cur_mod`/`_set_mod`；`_struct_index`/`_enum_index`/`_fn_index` 按模块解析；三处重复检查改成"同模块才重复" |
| `tests/selfhost/mod_dup_a.qma` | 新夹具模块：`_tag(int)->int`、`_Box` 2 字段 |
| `tests/selfhost/mod_dup_b.qma` | 新夹具模块：`_tag(str)->int`、`_Box` 3 字段 |
| `tests/selfhost/s38_modscope.qma` | 新差分夹具：交替调用两套同名声明 |
| `tests/t197_qlmc_thread.qma` | **修偶发**：固定次数 `thread_yield` 改成轮询到条件成立 |
| `tests/qlmc_test.py` | 注册 `s38_modscope` |
| `tools/dev/qlmc_coverage.py` | `BASELINE` 64 → 67 |
| `docs/07-gaps.md` | §7.43 从"待修"改成"已修" |

### 解析规则（两趟）

```quelmara
// 1. 先找"同模块 + 同名" —— 私有声明只在自己的模块里可见
// 2. 再找"同名且全局唯一" —— 跨模块引用没有重名的声明时走这条
//    （std/tls_net 用 std/tls_client 的 TlsClientResult 就是这种）
// 第 2 趟**必须判"唯一"**：同名声明出现在两个模块里时不能猜，
// 返回 -1 让调用方报错。猜错就是静默错编。
```

## 踩到的坑：给 `Fn` 加第 8 个字段 → 读出来是垃圾

第一版实现是给 `Fn` struct 加一个 `mod: int` 字段、给 `P` 加
`mod_id` / `smod` / `emod` 三个字段。**结果 `fe.mod` 和 `p.mod_id` 都读出
一个巨大的地址值**（`131151930794504`），而且同一函数里两次读还不一样。

排查过程（值得记）：

1. 先怀疑 struct 布局 —— 用 8 字段 / 16 字段 / `vec[Struct]` 分别验证，
   **全部正常**；
2. 再怀疑形参个数 —— 15 个形参的函数，**正常**；
3. 最后加调试打印，发现 `fe.name=0` 但 `mod` 是地址 ——
   说明**不是字段值错，是整个 `Fn` 记录错位**。

**结论：`P` 和 `Fn` 都是 qlmc 自身的高频核心 struct，加字段的代价远超预期。**
换成"不动任何既有 struct、把模块号放进 `stt` 尾部扩展区"之后一次通过。

**教训：在自举编译器里，给核心 struct 加字段是最贵的改动形态之一。
优先考虑"塞进已有容器的空余区"，而不是"加一个字段"。**

### 为什么是 `stt` 尾部，不是 `static_word`

第一版试过 `static_word`（进程级静态字），也能工作，但只适合
"当前模块号"这一个单值。三个平行表（struct / enum / 函数）需要三个区，
而且 lowering 期是**并行**的（`_compile_range` 按函数分片），
进程级单值会串味。`stt` 是只读共享，天然并行安全。

## 顺带修：`t197_qlmc_thread` 的偶发失败

跑全量差分时 `s32_thread` 失败：

```
stage-0: cnt=3  cnt2=4
qlmc   : cnt=2  cnt2=5
```

**先确认是不是本版引入的回归** —— 用 v3.61 的二进制连跑 4 次：

```
run1: bits=15 cnt=4 cnt2=3
run2: bits=15 cnt=4 cnt2=3
run3: bits=15 cnt=4 cnt2=1     ← 已经偶发
run4: bits=15 cnt=4 cnt2=3
```

**v3.61 基线本身就偶发**，所以与本版无关。

根因在夹具：它用 `while i < 400 { thread_yield() }` 来"等线程跑完"。
**那是"让出 400 次"，不是同步** —— 调度慢一点就跑不满。
改成**轮询到条件成立**（上限 200000 次只防死循环）。改后连跑 6 次全稳。

**教训：用固定次数的 yield 当同步，等于赌调度。**
这是 v3.14「一条从不影响退出码的告警迟早等于消失」的同类问题 ——
一个偶发失败的测试，迟早会被人当成噪声忽略。

## 验证

| 命令 | 结果 |
|---|---|
| 差分夹具 `s38_modscope`（8 行输出） | **stage-0 与 qlmc 逐字节一致** |
| 跨模块同名隔离（手写探针） | `a_tag(3)=3000` / `b_tag("abcd")=4` / `a_box(7,2)=72` / `b_box(1,2,3)=123` —— **各自绑对** |
| qlmc 差分全量 | **40/40 PASS**（39 → 40） |
| `std/` 覆盖率 | **64 → 67**（`std/httpc_net` + `std/http` + `std/logfile`） |
| 自举等价性（stage-1 vs stage-2） | **32/32 逐字节相同**（30 → 32，含两个新夹具） |
| `t197_qlmc_thread` 连跑 6 次 | 全稳（改前偶发） |

### 不动点仍然在 wine 下测不出来

与 v3.61 相同：stage-2 编自己退出码 1 且无诊断，而**原始代码在 wine 下
同样失败**（v3.61 CHANGELOG 已留证据）。本版继续用**等价性 32/32**
作为可用判据，不动点的最终确认交给 CI 的 `bootstrap_test.py --strict`。

## 剩余 3 个模块（67 → 70）

| 模块 | 缺口 | 难度 |
|---|---|---|
| `std/csv` | `vec[vec[T]]` 类型码撞区间（§7.18） | **高** —— 架构性 |
| `std/gen` | 泛型 `[T: Ord]` | **高** —— 需要单态化 |
| `std/park_linux` | `syscall` 内建 | 低，但 **Linux 专用** |

前两个是真正的架构性工作，各值得一个专门版本。
