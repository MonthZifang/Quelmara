# v4.10 — 修 `now_ns` ELF 的 `ADDRV` 帧槽编码

- 日期：2026-11-04
- 任务：ELF 后端多个基准的**计时是负数**（`b1_int`、`b5_string`、
  `b12_gcd`、`b13_collatz`、`b15_loopsum`、`b16_leibniz`）。
- 结论：找到根因（帧槽编码错误），修复后 `b28_matrix` / `b23_lcs`
  计时正常，但简单循环基准仍显示负值（另一处问题待查）。

## 根因

v4.03 的 `now_ns` 用 `_st_units(fc, 4)` 分配帧槽，然后：

```quelmara
_ir_emit(fc, OP_ADDRV, raw, 0, 0, 0 - slot - 1)   // ← 错！
```

`OP_ADDRV` 的 `imm` 是**槽号本身**（0, 1, 2, ...），不是负偏移编码。
`_slot_disp(imm) = -8*(imm+1)` 才是负偏移。

写成 `0 - slot - 1` 时：`_slot_disp(-1) = 0` → `lea reg, [rbp]`，
指向**保存的 RBP 和返回地址**。`clock_gettime` 直接覆盖它们
—— 这就是计时负数和 SIGSEGV 的根因。

修正：`imm = slot` → `_slot_disp(0) = -8` → `lea reg, [rbp-8]`（正确帧槽）。

## 验证

| 基准 | 修复前 | 修复后 |
|---|---|---|
| `b28_matrix` | 正确 | **960991321 T 892ms** ✅ |
| `b23_lcs` | 正确 | **1498 T 128ms** ✅ |
| `b1_int` | 负数 | **仍负数** ❌ |

## 残留

简单循环基准（`b1_int` 等）仍显示负值。这些基准只有一个 `while` 循环，
而 `b28_matrix` / `b23_lcs` 有嵌套循环。可能与寄存器分配或
另一个 `_bi_now_ns_pe` / `_bi_now_ns_elf` 的问题有关。待查。
