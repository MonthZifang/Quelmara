# v2.81 — 归纳削减搬进 qlmc：b1_int 热循环 21 → 10 条（本机 2.1×）

- 日期：2026-10-27
- 任务：**编译器优化**（不是后端、不是运行时）
- 影响面：`bootstrap/qlmc/qlmc.qma`（新增 `_opt_mod_ind` / `_lab_index` /
  `_ir_insert` / `_const_before`；`_opt_pure` 补 `OP_BINI`）、
  `tests/selfhost/s27_modind.qma`、`tests/qlmc_test.py`

## 差距在哪

v2.77 的 CI 表第一次把 qlmc 列和 stage-0 列并排，暴露出：qlmc 在 b1_int /
b8_threads1 上比 stage-0 慢 **1.5×**。反汇编一看就清楚：

```
stage-0（9 条）                        qlmc 改前（21 条）
  cmp  r12, n                            cmp  r13, rbx
  jge  end                               jge  end
  mov  rsi, rdi   ; acc += 旧余数         imul r10, r13, 7
  add  rdi, 7     ; m += 7               mov  rcx, r10
  mov  rax, rdi                          mov  r11, rcx ; sar r11, 0x3f
  sub  rax, 0xd                          mov  rax, rcx ; xor/sub   ← 取绝对值
  cmovns rdi, rax ; 回绕                  movabs rdx, 魔数 ; mul rdx
  add  rbx, rsi                          shr  rax, 3 ; xor/sub    ← 符号修正
  add  r12, 1 ; jmp                      imul rax, rax, 0xd ; sub
                                         mov  rax, rcx ; mov r8, rax
```

stage-0 有 `opt_mod_inductive`（把 `(i*C)%D` 换成"递增计数器 + 条件回绕"），
qlmc 没有 —— **每轮一次 64 位 `mul` 的魔数除法**。

以前没搬的原因写在 §3.44：stage-0 那版依赖"`t` 非负"的范围分析
（`analyze_nonneg` + 降级期非负链 `nnv`），qlmc 的优化层没有范围分析。
没有这个证明就套 `cssub` 回绕，**负数取模会算错**（C 语义是截断取模）。

## 换一个更窄但可判定的证明

不搬范围分析，只证一件事：

> `t = i * C`，`i` 在循环外被初始化为常量 `k >= 0`，循环内**唯一**定义是
> `i = i + s`（`s > 0`）→ 每一轮 `i >= k >= 0` → `t >= 0`（要求 `C > 0`）。

再加两条：

- `0 < C*s < D`（`s` 是 `i` 的步长）—— 保证 `r + C*s < 2D`，**一次条件减**就够回绕；
- 守卫是 `i < N` 且 `N` 是常量、`C * N < 2^62` —— 顺带排掉 `t` 溢出
  （溢出会让 `t` 变负，非负前提就没了）。

任一条件不成立就**原样不动**。宁可少优化，不能算错。

守卫有两种形态，都要认：`while i < 20000000` 折成立即数（`OP_JCMPI`），
`while i < n`（`n` 是变量）是 `OP_JCMP` 两个 vreg —— 这时去查 `n` 在循环前的
常量定义（`_const_before`）。

## 变换

```
前导（循环头之前）：v = (k * C) % D          ← 常量，编译期算好
循环体：r = v                                ← 替换原来的 OP_DIVC
        i = i + s 之后：v += C*s；若 v >= D 则 v -= D
```

**`C*s` 那一步差点写错**：第一版按 `C` 前进，`s = 1` 时看不出问题，
`s = 2` 就整个算错。夹具里专门补了 `case_step2`（`i += 2`，`3*2=6 < 13`，能换）
和 `case_step2_too_big`（`7*2=14 >= 13`，不能换）两条 —— 加进去之前
**没跑过 `s != 1` 的循环**，是回头审代码时发现的。

`v` 是新开的变量（`_new_var`，落在 callee-saved 寄存器或帧槽）——
**必须钉成变量**：临时值的活跃区间不覆盖回边，分配器会把槽位复用掉。

## 两个配套改动

1. **`_ir_insert`**：在 IR 中间插指令。可以直接移位 —— 因为**分支的 `imm` 是
   标签 id 而不是指令下标**，移动指令不会破坏跳转；要修的是每个 vreg 的
   `vstart`/`vend`（它们存的是下标，`>= at` 的都要 +1）。
2. **`_opt_pure` 补 `OP_BINI`**。以前没列进来，导致归纳削减把 `t = i*C` 变成
   死代码之后 DCE 删不掉 —— 热循环里白留一条 `imul`。`OP_BINI` 就是
   `dst = a <add|sub|mul|and|or|xor|shl|shr|sar> imm`，全是纯运算。
3. 变换之后再跑一次 `_opt_copy` + `_opt_dce`：新插的 `r = v` 会被拷贝传播
   消掉，`add acc, r` 直接用 `v`。

## 效果

b1_int 热循环 **21 → 10 条**，与 stage-0 的 9 条只差一条（`mov r8, rsi`）。

本机 min of 5，新旧产物交替（同一台机器、同一轮）：

| 基准 | 改前 | 改后 |
|---|---|---|
| b1_int | 40.0 / 49.1 / 43.8 | **21.0 / 22.1 / 21.3** |

校验和不变（`119999988`）。全基准 10 个的校验和也全部一致。

## 没覆盖到的：b8_threads1

b8_threads1 是同一个形状，但它在 `fn work(n)` 里、`n` 是**形参**而不是常量 ——
溢出不可证，所以这版**不换**。要覆盖它得做"循环版本化"（运行时判 `n` 是否
在安全区间，否则走原路径），那是另一个量级的改动，留到下一版。

## 回归

| 套件 | 结果 |
|---|---|
| qlmc 差分（含新增 s27） | **PASS=65 FAIL=0** |
| 解释器差分 | PASS=8 FAIL=0 |
| 主回归 | 见下 |

新增夹具 `tests/selfhost/s27_modind.qma` 专门钉"边界那一圈"：标准形状 /
非零常量起点 / `C >= D` / 负起点 / 上界是参数 / 同时有 `/` 和 `%` /
步长 `s = 2` / `C*s >= D` —— 八种形状的**输出必须与 stage-0 逐字节相同**
（40 字节）。该换的必须换对，不该换的必须不动且结果不变。

主回归 **PASS=298 FAIL=0 SKIP=1**（v2.80 是 297，多的一条就是 s27）。
