# v2.62 — 两处循环识别缺陷（b9 的 5.8× 还没吃下来）

- 日期：2026-10-26
- 任务：按 v2.61 给出的第一条路径攻 b9_json（stage-0 最大的差距，5.8×）
- 影响面：`tools/stage0/qlm_opt.py`（`_loop_shape` / `opt_strlen_hoist`）

## 做了什么

目标是让 `opt_bounds_elim` 的**循环级证明**在 b9 上成立，从而删掉每次
`s[p]` 的越界检查（2 条指令 + 1 分支，每字节一次）。链条是：

```
len(s) 外提 → guard 的 hi 在循环内不变 → 证明 0 <= p < n → 删越界检查
```

沿着这条链挖出**三处**识别缺陷，修好两处半：

**(A) `opt_strlen_hoist` 只认 `call __str_len`**

`len(s)` 在降级/内联之后变成两种新形态：

* 形态 2：`('bin','sub', t, p, ('imm',8))` + `('load', d, t, ('imm',0))` 相邻；
* 形态 3：`('bin','sub', t, p, ('imm',8))` 在**循环外**，循环内只剩那条 `load`。

现在三种形态都认，并加了**支配检查**（v2.61 两次实现都让 b9 段错误的原因）：

* `p` 定义在函数入口块（第一个 label 之前，如 `args`）—— 支配全函数；
* 或者与循环头同一基本块（h 前最后一个 label 之后），且循环头没有其他前驱。

**(B) `_loop_shape` 把 `while a && b` 的**标志位**当成归纳变量**

`while go == 1 && p < n` 降级成两组 `jcc + jmp`、共享同一个出口：

```
L: jcc e go, ('imm',1), L2 ; jmp End
L2: jcc l p, n, Body ; jmp End
Body: ...
```

以前只取 `ins[h+1]`，于是 `ivar = go` —— 后面的"body 内不重定义归纳变量"
单调性检查、以及 `bounds_elim` 的循环级证明全部失效。现在跳过"与立即数
比较"的标志位条件，用真正带 vreg 上界的那条当 guard。

**(C) `_loop_shape` 假设 step 紧贴回边**

`while a && b` 的循环体末尾会先落一个分支汇合 label（`go = 0` 之后
`label iend ; jmp L`），step 在它前面。以前 `ins[b-1]` 取到 label 就
`return None`。现在先跳过尾部 label 再找 step。

顺带修了一个 `IndexError`（`ins[gi]` 不是 `jcc` 时仍去取 `[3]`）。

**⚠ 第一版有个偏移错误（v2.63 修）**：把 `h+2/h+3/h+4` 机械替换成
`gi+2/gi+3/gi+4`，多偏了 1（`gi` 是 `h+1`，jmp 在 `gi+1`）—— body 少第一条，
`opt_mod_inductive` 的归纳削减匹配不上，`b1_int` 的 `%13` 退回 6 条魔数除法，
**循环体 9 → 21 条、时间 +27%**（25.9 → 32.8 ms）。已修并验证回到 26.3 ms。

## 结果：只通到一半

修完之后 `_loop_shape` 对 **jstr** 返回了正确的 `('jcc','l',6,3,...)`，
但 jnum/jws 仍然是 `None` —— 因为它们的 `p` 在 **if/else 分支里**更新
（`if 是数字 { p += 1 } else { go = 0 }`），不是末尾的规范 step。

而 `opt_bounds_elim` 的单调性检查**正确地拒绝了**这种循环：

```python
if any(ivar in vreg_mentions(p)[0] for p in body):
    continue        # body 内重定义归纳变量，单调性失效
```

**这是对的**——`p` 确实在循环体内被重定义。要证明 `0 <= p < n` 在
**所有分支**上都成立，需要的是**范围分析**（在每个基本块的入口/出口传播
区间），不是"识别循环形态"能解决的。

**数据**：b9_json 38.8 ms（改前 39.8），`bfail` 标记 24 个（未变）——
差异在噪声内。**这一轮没有可测收益。**

## 为什么仍然保留

这三处是**识别缺陷**，不是性能开关：

* `_loop_shape` 现在能认 `while a && b` 与"step 不在末尾"的循环 ——
  `opt_loop_unroll` / `analyze_ranges` / `opt_bounds_elim` 都吃它，
  覆盖面变大；
* `opt_strlen_hoist` 的形态 2/3 让 `len(s)` 在循环内只读一次（省 1-2 条
  指令），支配检查保证不会把 load 提到定义之前。

它们本身是对的，只是**单靠它们兑现不了 b9 的 5.8×**。

## 下一步（范围分析，这才是 b9 的解）

`opt_bounds_elim` 需要一个**块级区间传播**：

1. 对每个基本块，从循环 guard 建立 `p ∈ [0, n)` 的初始约束；
2. 沿 CFG 传播，遇到 `p = p + 1` 就更新上界、遇到 `p = k`（常量）就重置；
3. 汇合点取**交集**（两个分支都满足才成立）；
4. 在 `s[p]` 处查询 `p` 的区间，覆盖 `[0, n)` 就删检查。

这是 v2.61 CHANGELOG 里说的"另一个量级的工程"，也是 b9 唯一的路。
`tests/t146_const_div.qma` 那类"常量除法"的路子在这里帮不上忙 ——
瓶颈是指令条数与分支，不是除法。

## 回归

`tests/run_win_tests.py`：**PASS=293 FAIL=0 SKIP=1**（含 t146）。
`_loop_shape` 被 unroll / ranges / bounds_elim 三个 pass 共用，改动后全绿。
