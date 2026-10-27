# v2.72 — 分支反转 + 终结符后死码消除

- 日期：2026-10-27
- 任务：压 `if` 的跳转开销（b9 / b7 的主项）
- 影响面：`tools/stage0/qlm_opt.py`（新 pass `opt_invert_branch` / `opt_dead_after_term`）

## 一、分支反转：让热路径直落

`_lower_cond` 的 `if` 形态是

```
jcc cc, a, b, L_then
jmp L_else
L_then: ...
```

then 分支紧跟在跳转后面 —— 于是**每次条件为假**都要多走一条 `jmp`。
反转条件码后：

```
jcc !cc, a, b, L_else
L_then: ...
```

条件为真时直落（0 条跳转），为假时一次条件跳转（与原来相同）。
`if` 的条件通常一边倒（`if i < n`、`if c == 34`），平均省半条指令。

`INV_CC` 覆盖 e/ne/l/ge/g/le/b/ae/a/be 十个条件码 —— **改 IR 条件码必须
同步后端 `COND`/`INV_COND` 与 `tests/a64_emu.py` 的两张表**（v2.66 的教训，
那次漏了模拟器直接 KeyError）。

## 二、终结符后死码

`if 条件 { return x } else { ... }` 的 then 分支里，`ret` 后面还挂着一条
跳去汇合点的 `jmp`，永远走不到。`opt_dead_after_term` 把 `ret`/`jmp` 之后
到下一个 label 之间的指令全删。

## 效果

fib 的机器码从「`jl` + `jmp` + 两条死 `jmp`」变成 `jge` + 直落：

```
1016 push rbx / push r12 / push rbp / mov rbp,rsp / mov rbx,rdi
1020 cmp rbx, 2
1024 jge 0x1035          ← 反转：n<2 时直落 base case
102a mov rax, rbx
...
```

本机 min of 5，两轮交替 A/B：

| 基准 | 旧 | 新 |
|---|---|---|
| b9_json | 34.5 / 31.2 | **27.6 / 27.8**（−11 ~ −21%） |
| b7_sort | 38.2 / 37.4 | **34.9 / 35.2**（−7 ~ −8%） |
| b3_recursion | 6.6 / 6.4 | 6.4 / 6.5（噪声内） |

b3 没动是因为它是**调用延迟链**，砍 1 条跳转不影响那条链。

## 一个必须让步的地方：覆盖率构建不做反转

第一版让 `cov_test.py` 挂了 2 个用例：

- `cov.qma：第 8 行的 then 边（8->9）被列出` —— 找不到 `未覆盖分支: 8->9`
- `main.qma：全部分支覆盖` —— 找不到 `分支: 2/2 (100.0%)`

原因：覆盖率是靠 `jcc` 的**跳转目标**记"分支边"的。反转之后 then 分支
变成直落、不再是任何跳转的目标，这条边就观测不到了 —— 报告从"有 1 条
未覆盖分支"变成"没有未覆盖分支"，是**假绿**。

处置：`opt_all(fn, unroll=..., invert=...)`，调试/覆盖率构建
（`prog is not None`）传 `invert=False`，保留规范的 `if` 形态。
诊断构建以可观测性优先，不追这几个百分点。

## 回归

`tests/run_win_tests.py`：**PASS=297 FAIL=0 SKIP=1**。
`tests/cov_test.py`：**PASS=23 FAIL=0**（修复后）。
