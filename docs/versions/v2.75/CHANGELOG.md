# v2.75 — 分支反转挪到最后（修 v2.72 打断归纳削减的回归，b1 −27%）

- 日期：2026-10-27
- 任务：修 v2.72 引入的**性能回归**
- 影响面：`tools/stage0/qlm_opt.py`（`opt_all` 的 pass 顺序）

## 回归是什么

CI 上 b1_int 的**对 C 比值**：v2.69 是 2.94×，v2.72 变成 3.52×，v2.74 变成
**4.85×**。本机 b1 从 26 ms 涨到 35 ms。

反汇编一看就明白：

```
v2.67 的循环（10~11 条，归纳削减生效）
    cmp r12, 0x1312d00 ; jge end
    mov rsi, rdi ; add rdi, 7
    mov rax, rdi ; sub rax, 0xd ; cmovns rdi, rax     ← cssub，(m+7)%13

v2.74 的循环（16 条，退回每轮一次魔数除法）
    cmp r12, 0x1312d00 ; jge end
    lea r11, [r12+r12*2] ; lea rsi, [r12+r11*2]       ← i*7
    movabs r11, 0x4ec4ec4ec4ec4ec5 ; mul r11
    mov rdi, rdx ; sar rdi, 2                          ← /13
    lea r11, [rdi+rdi*2] ; lea r8, [rdi+r11*4]         ← q*13
    mov rdi, rsi ; sub rdi, r8                         ← 余数
```

**根因：`opt_invert_branch` 把 while 的守卫也反转了。**
`while i < n` 的降级是 `jcc l i,n,BODY ; jmp END ; BODY:` —— 正好匹配
"then 分支紧跟跳转"的反转条件，于是变成 `jcc ge i,n,END ; BODY:`。

而 `opt_mod_inductive` / `_loop_shape` / `opt_loop_unroll` **都靠
"守卫 + 回边"的规范形态识别循环**。守卫被反转、`jmp` 被吃掉之后，
循环形态认不出来，归纳削减整个失效 —— `(i*7)%13` 从"递增计数器 + cssub"
退回"每轮一次除法"。

## 改法

把 `opt_invert_branch` 从收敛循环里摘出来，**挪到 `opt_flag_loop` 之后**
（所有依赖循环形态的 pass 都跑完了）。`if` 语句照样反转，只是晚一点。

`opt_flag_loop` 同时认"反转前/反转后"两种守卫形态（v2.74 已做），所以
顺序调整不影响它。

## 效果

b1 循环 **16 → 10 条**（比 v2.67 的 11 条还少一条：`n` 被
`opt_const_imm` 折成立即数，省掉 `cmp r12, rbx` 的寄存器）。

本机 min of 5，两轮交替 A/B：

| 基准 | v2.74 | v2.75 |
|---|---|---|
| b1_int | 34.9 / 34.8 | **25.4 / 24.1**（−27 ~ −31%） |
| b8_threads1 | 279.3 / 276.1 | **207.0 / 223.1**（−20 ~ −26%） |
| b9_json | 26.5 / 23.9 | 24.0 / 25.3（噪声内） |

## 教训

**pass 之间靠"形态匹配"耦合，顺序就是契约。** 这一轮三次踩同一类坑：

1. v2.72 的分支反转 → 打断 `opt_mod_inductive`（本次修）
2. v2.72 的分支反转 → 打断 `opt_flag_loop`（v2.74 修）
3. v2.66 加无符号比较 → 打断 A64 模拟器的条件码表（v2.66 修）

**加新 pass 之前，先把所有"按形态匹配"的老 pass 列一遍，看新 pass 会
不会改变它们看到的东西。** 全量回归只能证明功能正确，证明不了性能 ——
性能回归只能靠反汇编 + 同机 A/B 发现。
