# v2.67 — 就地更新折叠 + push 容量检查内联

- 日期：2026-10-27
- 任务：继续压循环体与 vec 热路径
- 影响面：`tools/stage0/qlm_opt.py`（新 pass `opt_store_back`）、
  `tools/stage0/qlm_native.py`（`__vec_push` / `__vec_push_n`）
- 夹具：`tests/t149_store_back.qma`

## 一、`opt_store_back`：`t = a OP b; a = t` → `a = a OP b`

Quelmara 的 `acc = acc + x` / `i = i + 1` 降级成"临时值算出来、再 mov 回变量"
两条 IR。发射器对 `dst != a` 只能走 **mat → 运算 → commit** 三条指令
（dst 的寄存器里还躺着 a 的旧值）：

```
mov r8, r12 ; add r8, rsi ; mov r12, r8     →  add r12, rsi
mov rsi, r13; add rsi, 1  ; mov r13, rsi    →  add r13, 1
```

折成就地更新后 `dst == a`，直接命中既有的二地址路径。b1_int 热循环
**15 → 11 条**，b2_float 的累加链少一条 `movaps`（`fbin` 版同样处理）。

**安全性**：只在 `t` 是**纯临时值**时合并 —— 全函数内 `t` 恰好出现两次
（这里定义一次、紧邻的 mov 用一次），且 `t != a`、`t != b`。这样"覆盖 a 的
旧值"发生在"a 作为本指令操作数被读完之后"，与原语义逐位等价。

**与 v2.61 那次失败的"分配器级拷贝合并"的区别**：那次是**改寄存器分配**，
打破了发射器 `safe_dst_reg` 的全套假设（30+ 误编译，见 `07-gaps.md`）；
这次是**改 IR**，发射器看到的仍是它熟悉的 `dst == a` 形态，走既有路径。

**为什么它还能起作用**：直线代码里 `x = x + y` 早被 `opt_copy_prop` 折掉了；
这个 pass 的战场是**循环携带变量**（copy_prop 推不动），以及
`m = (m + 7) % 13` 这类先被不可传播的运算更新、再累加副本的形态（b1_int）。

## 二、`__vec_push` 容量检查内联

以前是"每次 push 都 `call __vec_grow`"，而它在容量够时只做
`load data; ret` —— b4_array 的 200 万次 push 就是 200 万次白白的
call/ret + 序言（约 15–20 周期/次）。

现在检查内联，只在真需要扩容时才调：

```
load ln, h, 1
load cp, h, 2
cmpset l b, ln, cp
jnz  b, ok            # 容量够 → 跳过
call __vec_grow
ok: load data, h, 0
    store data[ln] = v
```

**注意 v2.60 曾试过同一件事并"测不出收益"** —— 那次是在 `quelmara` 列
（qlmc 的产物）上量的，改的却是 stage-0。本轮的 A/B 全部在
`--langs quelmara0` 上做。

## 效果（本机 min of 5，两轮交替 A/B）

| 基准 | 改前 | 改后 |
|---|---|---|
| b4_array（push 内联） | 25.9 / 23.2 | 19.0 / 21.0 |
| b1_int（store_back） | 27.9 / 27.5 | 27.6 / 25.7 |
| b7_sort（store_back） | 51.5 / 49.2 | 50.4 / 44.1 |
| b2_float（store_back） | 23.4 / 23.4 | 23.2 / 22.3 |

本机 VBS 噪声大（b1 同一天量到过 25.7–27.9），方向一致但幅度要打折看。
**b1 的收益小于指令数降幅**（−27% 指令、−1~7% 时间）—— 它卡在
`(m+7)%13` 的 4 周期串行依赖链上，砍指令不影响那条链。

全基准（本机 min of 7）：b4 17.9 ms（改前 20.3）、b8_threads1 221.9（改前
274.9）、b2 23.2 / C 23.3 = **1.00×**、b5 49.2 / C 71.8 = **0.69×**。

## 回归

`tests/run_win_tests.py`：**PASS=296 FAIL=0 SKIP=1**（含 t149）。

夹具 `t149_store_back` 的口径是**每条都跟手工算出的期望值对拍**（不是只跟
另一条路径比 —— 两条路径可能一起错），覆盖自反（`x - x`、`x / x`、`x ^ x`）、
操作数顺序敏感（`sub`/`div`/`mod`/`shr`/`shl`）、循环累加/递减/自乘、
int64 两端、以及浮点的 `fbin` 版本。验证过它确实走到这条 pass
（b1 形态的循环 28 → 12 条）。
