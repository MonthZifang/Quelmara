# v4.16 — ELF 下 EXIT 改用 syscall（不走 CALL）

- 日期：2026-11-04
- 任务：`OP_EXIT` 被发射为 `CALL I_EXIT`（指令 9561），是寄存器分配屏障。
- 结论：自举 42/42 全过，性能略有改善。

## 改动

ELF target 下 `OP_EXIT` 改用 `syscall exit_group(231)`，不再走 `CALL`。
PE 路径不变（仍用 `CALL ExitProcess`）。

## 效果

自举 42/42 + 不动点全过。b28_matrix 807ms / b23_lcs 96ms / b22_knapsack 14ms。
