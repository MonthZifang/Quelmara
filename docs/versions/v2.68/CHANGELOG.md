# v2.68 — 死跳转消除（`jmp L` 紧跟 `label L`）

- 日期：2026-10-27
- 任务：压 b9_json 的条件判断开销
- 影响面：`tools/stage0/qlm_opt.py`（新 pass `opt_drop_dead_jump`）

## 根因：`||` 链每段都带一条废跳转

`_lower_cond` 把 `a || b || c || d` 降级成

```
jcc e c, 32, L_true ; jmp next1
next1: jcc e c, 9, L_true ; jmp next2
next2: jcc e c, 10, L_true ; jmp next3
next3: jcc e c, 13, L_true ; jmp L_false
```

每个 `jmp nextN` 的目标就是**紧邻的下一条 label** —— 跳过去和不跳走的是
同一条路，纯粹白做。b9_json 的 `jws`（跳过空白）因此是

**12 条指令 / 8 个分支**，其中 4 条 `jmp` 全是废的（1/3 的指令、3/8 的分支）。

## 改法

一个纯控制流 peephole：

```
jmp L            →  (删掉)
label L
```

```
jcc cc, a, b, L  →  (删掉；真/假都落到 L，条件本身没有意义)
label L
```

跑两次：收敛循环的开头（让后面的 pass 看到更干净的 CFG），以及
展开 / 越界消除之后（那两个阶段会再造出这种形态）。

## 效果

b9_json 的 `jws` 循环 **26 → 23 条**，空白判断那一段
**12 条 / 8 分支 → 9 条 / 5 分支**。

本机 min of 5，两轮交替 A/B：

| 基准 | 无 | 有 |
|---|---|---|
| b9_json | 33.7 / 34.6 | 33.0 / 31.2 |
| b7_sort | 39.0 / 39.7 | 38.0 / 42.2（噪声） |
| b4_array | 14.0 / 12.9 | 12.3 / 14.0（噪声） |

b9 一致变快（−2 ~ −10%），b4/b7 在噪声内。这个 pass 对**任何带
`&&`/`||` 的条件**都生效，不止 b9。

## 回归

`tests/run_win_tests.py`：见本轮实测（基线 296）。
