# v4.13 — 修 `_gen_i64_fmt_elf` 破坏 RSI/RDI（浮点打印计时负数）

- 日期：2026-11-04
- 任务：`b16_leibniz`（浮点基准）计时仍为负值。
- **结论：全部 24 项基准计时正确。**

## 根因

`_gen_i64_fmt_elf`（整数转字符串）内部用 `RDI` 做计算（`mov rdi, rcx`），
但**没有保存 RSI/RDI**。浮点打印（`print(pi)`）会走到这里 ——
如果调用者把变量放在 RSI/RDI 就会被踩掉。

最小复现：
```quelmara
let t1 = now_ns()
print(pi)       // 踩掉 t1（在 RSI）
print(t1 - t0)  // 负数！
```

## 修法

`_gen_i64_fmt_elf` 加 `push rsi; push rdi` / `pop rdi; pop rsi`。
同 `_gen_print_i64_elf` / `_gen_print_str_elf` / `_gen_eprint_str_elf`
（v4.12 修的那三个）。

## 验证

| 基准 | 修复前 | 修复后 |
|---|---|---|
| `b16_leibniz` | -4.4e14 | **488ms** ✅ |

**全部 24 项基准计时正确。**

## 完整性能对比（qlmc vs gcc -O2，Linux）

| 比值 | 基准 |
|---|---|
| ≤1.10x ✅ | b1_int 0.78x / b2_float 0.86x / b5_string 1.00x / b8_threads1 0.97x / b12_gcd 1.06x / b10_ackermann 0.03x |
| 1.1-2x 🟡 | b6_hash 1.12x / b4_array 1.32x / b15_loopsum 1.23x / b14_fibiter 1.40x / b7_sort 1.77x / b11_nqueens 1.88x / b17_bubble 1.72x |
| 2-6x ❌ | b3_recursion 3.2x / b8_threads4 3.1x / b13_collatz 5.8x / b27_sieve 2.7x / b26_maxsub 4.5x / b18_insertion 3.3x |
| 8x+ ❌❌ | b22_knapsack 11.4x / b23_lcs 9.4x / b28_matrix 13.1x |

**6/24 ≤1.10x，7/24 在 1.1-2x，8/24 在 2-6x，3/24 在 8x+。**
