# v2.74 — `opt_flag_loop` 认反转后的守卫形态（b9 −12.5%）

- 日期：2026-10-27
- 任务：修 v2.72 引入的**优化回退**
- 影响面：`tools/stage0/qlm_opt.py`（`opt_flag_loop`）

## 一个自己造成的回退

v2.69 让 `opt_flag_loop` 把 `while go == 1 && p < n` 的标志位换成 break，
b9 掉了 11~14%。**v2.72 加了分支反转之后，这个优化又失效了** ——
反转把守卫形态从

```
L:  jcc e  go, 1, L2      ← 条件为"继续"
    jmp E
L2: jcc ge p, n, B
```

变成了

```
L:  jcc ne go, 1, E       ← 条件为"退出"
    label and.4           ← 两条守卫之间还落了一个 label
    jcc ge p, n, E
```

而 `opt_flag_loop` 仍按旧形态匹配，于是 b9 的三个扫描循环**每字节又白付
一次 `cmp go,1` + 一个分支**。反汇编里一眼就能看到（`cmp r14,1; jne`）。

**这是"改一个 pass 破坏了另一个 pass 的形态匹配"的典型** —— v2.72 当时
全量回归是绿的（功能正确），性能回退只能靠反汇编发现。

## 改法

`opt_flag_loop` 同时认两种形态：

- **形态 A**：`jcc <cc> go,k,L2` + `jmp E` + `label L2` → 触发 = 继续
- **形态 B**：`jcc <cc> go,k,E` + [label] + `jcc cc2,a,b,E` → 触发 = 退出

由 `cc`/`k` 推出"继续值"与"退出值"（`e` 表示 `g == k` 时触发、`ne` 表示
`g != k` 时触发），再按原有的四条前提校验，最后把 `go = 退出值` 换成
`jmp E` 并删掉守卫。

形态 B 下两条守卫之间允许有 label（`while a && b` 的 `and` 汇合点）。

## 效果

b9 的 `jws` 循环 **20 → 18 条**，守卫从 `cmp/jne/cmp/jge` 四条降到
`cmp/jge` 两条。

本机 min of 5，两轮交替 A/B（基线 = v2.73 的 HEAD）：

| 基准 | v2.73 | v2.74 |
|---|---|---|
| b9_json | 27.8 / 28.0 | **24.5 / 24.4**（−12.5%） |
| b7_sort | 33.3 / 33.2 | 33.5 / 33.3（噪声） |
| b4_array | 12.9 / 12.3 | 12.5 / 12.5（噪声） |

## 回归

`tests/run_win_tests.py`：见本轮实测（基线 297）。
