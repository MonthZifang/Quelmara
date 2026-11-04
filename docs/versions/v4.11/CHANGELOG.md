# v4.11 — now_ns 帧槽方向修正（timesec 字段落进保存的 RBP）

- 日期：2026-11-04
- 任务：修 now_ns 计时负值的残留问题。
- 结论：**帧槽向负方向增长**，`[buf+8]` 会越过缓冲区落到保存的 RBP。
  修正后 `b28_matrix` / `b23_lcs` 计时正常，简单循环基准仍显示负值。

## 根因

帧槽布局：`_slot_disp(slot) = -8*(slot+1)`，即 slot N 在 `[rbp - 8*(N+1)]`。
帧槽**向负方向增长**（slot 0 最靠近 RBP）。

timespec 是 16 字节（sec 在 `+0`、nsec 在 `+8`）。如果 `buf` 指向 slot 0
（`[rbp-8]`），则 `[buf+8] = [rbp]` = **保存的 RBP**！`clock_gettime` 写入的
nsec 落到 slot 0，但读取时读到的是保存的 RBP。

修正：`buf` 指向**第二个槽**（`slot+1`），让 `[buf+8]` 落到 slot 0。
`_st_units(fc, 4)` 已分配 4 个槽（够放 2 个 int64），不会越界。

## 验证

| 基准 | 结果 |
|---|---|
| `b23_lcs` | **1498 T 99ms** ✅ |
| `b28_matrix` | **960991321 T 808ms** ✅ |
| `b1_int` | 119999988 T **负值** ❌ |

自举五级全 PASS、110 差分全过。

## 残留

简单循环基准（`b1_int` / `b13_collatz` / `b15_loopsum` / `b12_gcd` /
`b16_leibniz`）仍显示负值。这些基准只有单层 `while` 循环，而
`b28_matrix` / `b23_lcs` 有嵌套循环且计时正常。
根因未明 —— IR 层面 sec/nsec 的读写地址都正确。
