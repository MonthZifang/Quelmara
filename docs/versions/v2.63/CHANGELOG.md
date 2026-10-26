# v2.63 — 归纳变量"只增不减"就够（bounds_elim 的宽松路径）

- 日期：2026-10-26
- 任务：继续攻 b9_json 的越界检查（v2.62 停在"需要范围分析"）
- 影响面：`tools/stage0/qlm_opt.py`（`_monotone_incr` / `_find_guard` / `opt_bounds_elim`）

## 思路：不需要完整的范围分析

v2.62 的结论是"要证明 `0 <= p < n` 在所有分支成立，需要块级区间传播"。
但 `opt_bounds_elim` 的条件其实可以放宽到**单调性**：

> 循环 guard 建立"进入时 `0 <= ivar < hi`"。只要 body 里 ivar
> **只增不减**，这个上界在整个循环体内一直成立。

`ivar` 在循环体里递增是扫描循环的常态（`if 是数字 { p += 1 } else { ... }`），
不需要 CFG 传播就能证明。

**(A) `_monotone_incr(body, ivar)`**：body 内对 ivar 的每次重定义必须是

* `('bin','add', ivar, ivar, ('imm', k))`，`k >= 0`；或
* `('bin','add', t, ivar, ('imm', k))` 紧跟 `('mov', ivar, t)`。

其他任何定义（减、赋常量、来自未知值）一律拒绝。

**(B) `_find_guard(fn, h, b)`**：`opt_bounds_elim` 以前只走 `_loop_shape`，
而 `_loop_shape` 要求 step 在末尾（`unroll` 要用它）。`while a && b` 的 step
在 if/else 分支里，`_loop_shape` 返回 None，宽松路径根本没机会走。现在
`shape is None` 时自己找 guard（`h+1`，或跳过标志位后的 `h+4`），整个
region 当 body。

## 结果：还是没消掉，但原因换了

`bfail` 标记仍是 24 个。**新原因是下界**：`_const_before(fn, h, ivar)` 要求
ivar 的初值是**编译期常量**，而 b9 的 `p` 从 `p0` 开始（函数参数，运行期
值，可能为负）——下界不可证。

**这个检查是必要的**：`s[p0]` 在 `p0 < 0` 时确实越界，不能删。C 版没有这个
检查是因为它用 `const char *` 指针，不是"下标 + 长度"。

所以 b9_json 的 5.8× **不是"编译器少做了优化"**，是两种内存模型下**必须做的
工作不一样**。要缩短差距只能从别处下手（每 token 一次函数调用、jval 的
24 个溢出槽）。

## 回归

`tests/run_win_tests.py`：**PASS=293 FAIL=0 SKIP=1**。
`_monotone_incr` 放宽的是"拒绝条件"，被它放过的循环必须真的单调 ——
全量回归覆盖了 `t146_const_div`（除法/取模）与全部 vec/str 下标用例。
