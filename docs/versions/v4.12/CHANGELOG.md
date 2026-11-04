# v4.12 — 修 `print` 运行库破坏 RSI/RDI（计时负数的真正根因）

- 日期：2026-11-04
- 任务：ELF 后端简单循环基准的计时负值。
- **结论：找到并修好了根因。** 6 项基准中 5 项计时恢复正常。

## 根因

`_gen_print_i64_elf` / `_gen_print_str_elf` / `_gen_eprint_str_elf` 用
`write(fd, buf, len)` syscall —— 它把 fd 放 RDI、buf 放 RSI。
但这些运行库**没有保存 RSI/RDI**！

RSI/RDI 是变量寄存器池的第 6/7 个 —— 调用者可能把变量放在那里。
不保存就是**静默改掉别人的变量**。

症状极具迷惑性：`print(x)` 之后再用某个变量，值变成 write 的返回值
（字节数）或 buf 指针。所以 `print(acc)` 在 `print(t1-t0)` 之前
就会把 `t1`（住 RSI）踩掉 —— 换个打印顺序就正常。

最小复现：
```quelmara
let t1 = now_ns()
print(acc)       // 踩掉 t1（在 RSI）
print(t1 - t0)   // 负数！
```

## 修法

三个运行库入口都加 `push rsi; push rdi` / `pop rdi; pop rsi`。
同 `_gen_cgt_elf` / `_gen_syscall_elf` 的处理方式（v4.03 修的那两个）。

## 验证

| 基准 | 修复前 | 修复后 |
|---|---|---|
| `b1_int` | -5.7e14 | **67ms** ✅ |
| `b13_collatz` | -5.7e14 | **670ms** ✅ |
| `b15_loopsum` | -5.7e14 | **1017ms** ✅ |
| `b12_gcd` | -5.7e14 | **11141ms** ✅ |
| `b28_matrix` | 808ms | **805ms** ✅ |
| `b23_lcs` | 99ms | **98ms** ✅ |
| `b16_leibniz` | 负值 | **仍负值** ❌ |

## 残留

`b16_leibniz` 仍为负值。它用浮点运算（XMM 寄存器），可能有类似问题
（`_gen_i64_fmt_elf` 或 SSE 指令破坏其他寄存器）。待查。

## 这是第三轮"print/运行库破坏变量"了

* v4.03：`_gen_cgt_elf` / `_gen_syscall_elf` 破坏 RSI/RDI
* v4.11：帧槽方向错误（`[buf+8]` 落到保存的 RBP）
* **v4.12**：`print` 运行库破坏 RSI/RDI

共同教训：**自写的运行库必须保存所有 callee-saved 寄存器**，
否则调用者放了变量的地方会被静默踩掉。
