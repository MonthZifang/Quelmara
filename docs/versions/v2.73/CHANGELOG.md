# v2.73 — 常量折叠 + 分配器溢出启发式（b5 取位循环 22 → 15 条）

- 日期：2026-10-27
- 任务：解决 b5_string 的寄存器饥饿
- 影响面：`tools/stage0/qlm_opt.py`（新 pass `opt_const_imm`）、
  `tools/stage0/qlm_native.py`（`allocate` 的溢出选择 + `_emit_divmod10c`）

## 现象

b5 的取位循环（`__str_from_i64` 内联进 main 后）是 **22 条指令、8 次内存往返**：
每个临时值（`q`、`q*10`、`c`）都被赶进栈、下一条指令立刻读回来。

## 三个原因，逐个修

**(A) 常量占着寄存器**。`let n = 500000` 让 `n` 整整一个循环占一个寄存器。
新 pass `opt_const_imm`：`mov v, imm` 且 `v` **恰好出现两次**（这里定义、
那里用一次）→ 把立即数折进使用处、删掉 mov。

顺带：`cmp r12, 500000` 省一条 `mov`，`load d, base, ('imm',k)` 还能走
v2.70 的位移路径。**基址位置（load/store 的 base）不折** —— 换成立即数会
变成绝对地址访问。

**(B) 溢出选错了对象**。原来的线性扫描在"没有空闲寄存器"时**无条件溢出
当前值**，于是短命临时值反而被赶进栈。改成经典的
"spill the interval with the furthest end"：溢出**区间结束得最晚**的那个，
把寄存器让给当前值（当前值的区间更短，马上就会死）。

**(C) 临时值多了一个**。`_emit_divmod10c` 直接算 `ch = (v + base) - q*10`，
而不是"先算余数、再 `+base`" —— 取位循环同时活着的临时值从 4 个降到 3 个。

## 效果

取位循环 **22 → 15 条，零溢出**：

```
12a4 mov rax, r15              ; v
12a7 movabs r11, 0xcccccccccccccccd
12b1 mul r11
12b4 mov r9, rdx
12b7 shr r9, 3                 ; q = v/10
12bb lea r11, [r9 + r9]
12c0 lea rbx, [r11 + r9*8]     ; q*10
12c5 mov r12, r15
12c8 add r12, 0x30             ; v + '0'
12cc sub r12, rbx              ; 字符
12cf mov [rsi + rdi], r12b
12d7 mov r15, r9               ; v = q
12da sub rdi, 1
12de test r15, r15
12e1 jne
```

本机 min of 5，两轮交替 A/B：b5_string 24.6 / 24.8 → **21.8 / 21.0**
（−12 ~ −15%）。b1 / b2 / b9 不变（它们没有寄存器饥饿）。

## 回归

`tests/run_win_tests.py`：见本轮实测（基线 297）。
分配器是全局改动，**必须**跑全量回归 —— 溢出对象换了，每个函数的寄存器
分配都会变。
