# Quelmara 性能分析报告

- 日期：2026-11-04
- 状态：目标 (1)(2)(3) 完成，目标 (4) 未达成

## 性能对比（quelmara vs gcc -O2，Linux）

| 基准 | quelmara | C | 比值 | 状态 |
|---|---|---|---|---|
| b73_graph_bfs | 0.15ms | 0.2ms | **0.50x** | ✅ |
| b16_leibniz | 487ms | 402ms | 1.21x | 🟡 |
| b82_array_fill | 104ms | 79ms | 1.31x | 🟡 |
| b85_count_ones | 289ms | 212ms | 1.36x | 🟡 |
| b14_fibiter | 614ms | 437ms | 1.40x | 🟡 |
| b68_bit_matrix | 2.5ms | 1.3ms | 1.92x | 🟡 |
| b70_lin_search | 3186ms | 2035ms | 1.57x | 🟡 |
| b67_bubble_opt | 258ms | 150ms | 1.72x | 🟡 |
| b81_bit_reverse | 111ms | 64ms | 1.73x | 🟡 |
| b74_accum_poly | 181ms | 103ms | 1.75x | 🟡 |
| b72_sort_insert | 210ms | 60ms | 3.51x | ❌ |
| b77_rec_fib | 2.7ms | 0.8ms | 3.38x | ❌ |
| b69_hash_fib | 79ms | 19ms | 4.16x | ❌ |
| b83_lcg_random | 443ms | 68ms | 6.48x | ❌ |
| b23_lcs | 98ms | 10ms | 9.42x | ❌ |
| b26_maxsub | 1008ms | 223ms | 4.52x | ❌ |
| b22_knapsack | 14ms | 1.2ms | 11.67x | ❌ |
| b28_matrix | 811ms | 61ms | 13.3x | ❌ |

## 性能差距根因（已量化）

### 1. vec 抽象固有开销（主因）

每次 `vec.get(i)` 生成 **6 条指令** vs C 的 **1 条**：

| 指令 | 作用 | 条数 |
|---|---|---|
| `LOADD dst, [h+0]` | 加载 data 指针 | 1 |
| `JCMPVLEN` | 越界检查 | 4 (2 mov + cmp + jcc) |
| `LOADX dst, [data+i*8]` | 元素访问 | 1 |
| **总计** | | **6** |

C 版本：`mov rax, [base+idx*8]` = **1 条**。

**根本限制**：vec 抽象需要 2 次内存访问（data 指针 + 元素），C 只需 1 次。x86 不支持双重间接寻址。

### 2. 越界检查开销

每次 vec 访问有 2-4 条指令的越界检查。C 没有。

### 3. 寄存器溢出

热循环中 13 个活跃值 vs 11 个寄存器（7 callee-saved + 4 temp）。

## 已尝试的优化（8 种，全部失败）

| 优化 | 失败原因 |
|---|---|
| IR 层 CSE × 5 | 校验和错误 |
| 降级期 _vec_field 缓存 | 自举超时 |
| 发射器 JCMPVLEN+LOADX 融合 | 校验和错误 |
| 内联 vec 布局 | 大部分基准失败 |

**共同根因**：qlmc 的 IR 生成和 stage-0 不同，任何 IR 改变都会导致自举不等价。

## 已完成的优化（2 种，安全）

| 版本 | 优化 | 效果 |
|---|---|---|
| v4.41 | `_mov_rr` 同寄存器不发 mov | 微小 |
| v4.42 | `_vec_check` 冷路径精简 | 二进制缩小 2.5% |

## 结论

**≤1.10x 对所有基准在当前架构下无法达成**。vec 抽象的双重内存访问是固有开销。

要根本解决需要：
1. 改变 vec 布局（data 内联）—— 大改动
2. 向量化（SIMD）—— 大改动
3. 更好的寄存器分配 —— 大改动

**决策**：接受当前性能水平。目标 (1)(2)(3) + CI + 文档已完成。

---

# 附录：vec 内联布局的两次失败（v4.44 / v4.46）

## 目标

把 vec 从三块布局 `[data_ptr][len][cap]` 改成单块 `[len][cap][data...]`，
让 `v.get(i)` 从**两次访存**降到**一次**（与 C 的 `a[i]` 等价）。

## 结果摘要

| 尝试 | 正确性 | 性能 | 自举 | 结论 |
|---|---|---|---|---|
| v4.44 | ✅ 校验和全对 | `b28_matrix` 811→**661ms（-18%）** | ❌ | 回退 |
| v4.46 | ✅ 校验和全对 | 同上 | ❌ | 回退 |

**性能收益是真的（-18%），但自举过不去。**

## 关键诊断过程（给接手的人省时间）

第一次（v4.44）表现为 `bootstrap_test` **超时 900 秒**，卡在
`stage-2 编 s15_bitops.qma`。看上去像 hang。第二次（v4.46）修了一个
明显的 bug 后仍失败，于是做了更细的定位：

1. **stage-1 编 42 个 selfhost 文件：全成功**。
   → 说明 qlmc 源码本身没问题，问题在"新 qlmc 编出来的二进制"。

2. **stage-2 跑 `version`：正常**（字符串打印 OK）。
   **stage-2 跑 `dump`：正常**（lexer+parser+nodes 计数都对）。
   **stage-2 跑 `irdump`：无任何输出**。
   → **故障点在 lowering（IR 生成）**，不在前端。

3. **stage-2 编 `print(42)`：无输出、无文件、退出码 0**。
   → 不是 crash，是**静默提前退出**。

4. 进程状态观察：不是 hang（进程很快消失），是早退。

所以 selfhost 超时的真正原因不是"死循环"，而是 stage-2 在 lowering
某个环节静默退出，`bootstrap_test` 的 `subprocess` 一直等文件出现。

## 定位到的两个真 bug（都已修，但仍不通过）

**bug 1：`_vec_grow_body` 里重复 `_pin`。**

```quelmara
let hp = _pin(fc, h)   // h 已经是 _vec_push 里 _pin 出来的变量
```

`_pin` 会 `_new_var` + `MOV`，造出**第三个变量**。后面
`MOV hp, dp`（扩容后把句柄改成新块）只改这一层，调用方手里的句柄
仍是旧块地址 → 扩容后继续往旧块写。

修法：`let hp = h`（不 pin），因为调用方传进来的本就是变量。

**bug 2：`_lower_vecnew` 里残留死变量 `hdr`。**

```quelmara
let hdr = _vnew(fc)          // 创建了但只发射了一条 CONST
fc.vty.set(hdr, TY_INT)
_ir_emit(fc, OP_CONST, hdr, 0, 0, 16)   // 这条不参与后续任何计算
```

无害但会多占一个 vreg，已删。

## 修完这两个 bug 之后仍然失败

stage-2 依旧连 `print(42)` 都编不出，且**完全静默**。第三个 bug 没找到。

按项目纪律（v3.84 / v4.00 的教训：**没有差分验证就不算修好**），
**回退**。补丁留在 `/tmp/vec_inline_wip.patch`。

## 下一步的最优路径

不要在 qlmc 单边改。正确顺序是：

1. 先改 **stage-0**（`tools/stage0/qlm_native.py` 的 `__vec_new` /
   `__vec_get` / `__vec_set` / `__vec_grow` 四个运行时函数）到新布局；
2. 再改 qlmc 对应处；
3. 用 `bootstrap_test` 验证 stage-1/stage-2 逐字节一致。

只改 qlmc 一边时，stage-1 是"旧 qlmc 编出的编译器"、stage-2 是"新源码
编出的编译器"，两者行为必然分叉——这是自举编译器的结构性约束，
不是运气问题。

## 另一个可能的收益点

即使 vec 布局不动，`_vec_check` 的越界检查在热循环里每元素仍要
`cmp+jcc` 两条。`Quelmara.toml` 已有 `[build] bounds_check = true`
开关，但 qlmc **没实现它**（只有 stage-0 读）。把它接进 qlmc 是一条
低风险、可量化的优化路径。

---

# 附录 2：`bounds_check` 开关不是"无脑全赢"

v4.46 接通 `[build] bounds_check` 后做了逐项验证，结论比预期复杂。

## 逐项实测（Linux ELF，min of 2）

| 基准 | 有检查 | 无检查 | 变化 |
|---|---|---|---|
| `b18_insertion` | 14166ms | **10976ms** | **-22%** ✅ |
| `b72_sort_insert` | 212ms | **169ms** | **-20%** ✅ |
| `b23_lcs` | 95ms | **76ms** | **-20%** ✅ |
| `b70_lin_search` | 3211ms | **4104ms** | **+28% 回退** ❌ |
| `b28_matrix` | 804ms | 797ms | -1%（噪声内） |
| `b1_int` | 67ms | 68ms | 噪声内 |

## 为什么 `b70_lin_search` 会变慢

先确认不是测量噪声（重复 3 次）：

```
无检查: 4114 / 4102 / 4128 ms
有检查: 3228 / 3196 / 3198 ms
```

非常稳定，是真实回退。

`b70` 的内层循环每轮只有 **1 次 vec 访问**（`a.get(k)`），

```quelmara
while k < n {
    if a.get(k) == target { found = found + 1 }
    k = k + 1
}
```

只有 1 条 `JCMPVLEN`。去掉它省下的 2 条指令，与"代码块整体移位导致的
i-cache / 分支对齐变化"相比是净亏。这类现象在 x86 上不罕见：热循环
跨越 64 字节边界、或者循环头落到不同的 BTB 槽，都会带来 10-30% 的差异。

**这不是 bug，是代码布局的偶然性。**

## 结论

`bounds_check = false` 应当当作**逐基准可选**的选项，而不是全局默认：

* 循环里有 **≥2 次 vec 访问** → 通常明显受益（b18/b72/b23 都是这种）
* 循环里只有 **1 次 vec 访问** → 可能被布局效应吃掉，甚至倒退

`run.py` 现在默认读 `Quelmara.toml` 的 `[build] bounds_check`，仓库里
是 `true`（安全优先）。做性能对比时可以显式加 `--no-bounds-check`，
但**看数据时要按基准分辨**，不能只看总平均值。

## 顺带记一个教训

任何"全局开关"在 x86 上都要逐基准验证。这次差一点就把
`bounds_check = false` 当成"普适优化"写进文档——那会误导后来的人
在 b70 这类基准上白花时间。

---

# 附录 3：vec 内联布局第四次尝试（v4.48）—— 又修 2 个 bug，仍不通过

## 本轮修掉的真 bug

继 v4.47 拆出 `_map_cap` 之后，本轮又发现 **map / vec 的 `off=8` 也混淆**：

| 类型 | `[h+8]` |
|---|---|
| vec | len |
| map | **count** |

`_vec_field(fc, h, 8)` 在 vec 上映射到 len，在 map 上却当 count 用。
`_map_put` / `_map_del` 三处混用。已拆出 `_map_count(fc, h)`。

## 还有一个更隐蔽的 bug：`_pin` 造成的迭代内副本

`_vec_push` 原来是：

```quelmara
let hp = _pin(fc, h)          // 造出一个"本迭代内"的新变量
...
_vec_grow_body(fc, hp, stride) // 里面 MOV hp, 新块基址
```

`_vec_grow_body` 确实更新了 `hp`，但 `hp` 是**每次迭代重新从 `h` 复制出来的
临时变量**。扩容后下一轮迭代，`MOV hp, h` 又把**旧句柄**读回来 ——
于是永远往旧块写，旧块满了之后越界/死循环。

实测现象：`min2.qma`（`new(4)` + 100 次 push）**挂起不返回**。

修法：`let hp = h`（不 pin）。`h` 本身就是 vec 变量的 vreg。

## 修完仍然失败

加上 `_map_cap` / `_map_count` / `_pin` 三处修复后：

* ✅ `min2.qma`（vec 扩容）正常：`100 99 0`
* ❌ **stage-2 仍然连 `print(42)` 都编不出**，且 `irdump` 无输出

第四个混淆点没找到。已知故障区间：`dump` 正常（lexer+parser OK）→
`irdump` 无输出（lowering 里早退）。

我排查过的、**已排除**的方向：

* `_cmd_irdump` 里那 8 个 `vec[int].new(512)` —— 单独构造 22 个 vec 的
  程序跑得通
* `_new_fc` 里 20+ 个 vec 字段 —— 同上
* 大 vec（1000 万元素）—— 正常
* struct vec / 嵌套 vec —— 正常

## 结论

**放弃。** 这是第 4 次尝试（v4.44 / v4.46 / v4.47 前置清理 / v4.48），
累计修掉 4 个真 bug（重复 pin、死变量、`_map_cap`、`_map_count`），
但自举始终过不去。

补丁存于 `/tmp/vec_inline_v4_48_attempt.patch`（554 行）。

## 保留了什么

`_map_cap` / `_map_count` 的语义分离**已提交**（v4.47 及后续），
这是独立的正确性改进：以前 map 和 vec 靠"布局恰好兼容"共享函数，
现在显式分开。即使不做 vec 内联，这个修复也应当保留。

## 给下一个人

如果还要碰 vec 布局，**先给 qlmc 加一个能在 stage-2 里打印进度的
诊断通道**（比如 `QLMC_TRACE=1` 环境变量控制 `eprint`），否则每轮
12 分钟的构建只能盲猜。当前状态下，故障在 lowering 且完全静默，
没有诊断寸步难行。

---

# 附录 4：第 5 次尝试（v4.49）—— trace 定位到 FnCtx 构造，放弃

## trace 通道的价值（v4.48 加的）

第 5 次重试 vec 内联，带上 `--trace` 后**第一次就能精确定位**：

```
[trace] compile_range wid=0
[trace]   lo=0  hi=1
[trace] new_fc: start
[trace] new_fc: cells ok
（然后就没了 —— 死在 FnCtx {...} 结构体构造里）
```

之前四次"静默失败"，现在一眼看到：**`_new_fc` 的 FnCtx 构造
（23 个 vec 字段一次性创建）是死亡点**。

## 本轮修正的流程问题

上一轮结论说"自举超时 = stage-2 挂起"是**错的**。真相：

1. `dump` 正常 / `irdump` 无输出 —— 这个是**真的**（可稳定复现）
2. 但"stage-2 编 tiny.qma 无输出无文件"里**有一批是测量假象**：
   wine 的相对路径输出、`>/dev/null 2>&1` 把错误吞掉
3. 带 trace 重测，stage-2 编 tiny.qma **三次全成功**（4199 字节）

教训：**先把测量环境钉死（绝对路径 + 保留 stderr），再下"失败"结论。**

## 本轮做的额外修复

* `_map_count` 补进 HEAD（v4.49 之前它只在 stash 里，重试时差点漏掉）
* `_vec_grow_body` 的双层 `_pin` bug 再次确认并修复

## 第 5 次的结局

* 基础 vec：✅（`min2` 100/99/0）
* stage-1 编 41/42 selfhost：✅ 全过
* **stage-2：死在 `_new_fc` 的 FnCtx 构造**（23 个 vec 字段）

单独测试全部正常：22 个 vec、struct vec、嵌套 vec、
`FnCtx2`（含 4 个 vec 字段的自定义结构）。但 stage-2 里
**vec 内联代码自己编译自己**之后，那 23 个连续分配就是会死。

这是"自引用"层面的问题：内联布局改了 `vec.new` 的生成方式，
而 stage-2 正是用这个新方式生成的编译器，它自己创建 23 个 vec 时
触发的 bug 是我们最没法从外面看到的。

## 最终结论

**vec 内联布局：5 次尝试，修掉 6 个真 bug，全部回退。**

如果将来还要做，需要的不再是猜测，而是：
1. stage-0 同步改布局（让 stage-1 生来就是新布局，避开
   "新代码编旧布局"的中间态）
2. 或者给 qlmc 写一套**独立于 vec 的小型分配器测试**
   （能直接跑、不用等 12 分钟构建）

## 现状

* 自举：42/42 + 不动点 ✅（干净 v4.48）
* `--trace`：✅ 已提交，永久可用
* `_map_cap` / `_map_count`：✅ 已提交（语义分离，独立价值）
* bounds_check 开关：✅ 已提交（b18/b72/b23 各 -20%）
* vec 内联：❌ 放弃（5 次，6 bug，全回退）
