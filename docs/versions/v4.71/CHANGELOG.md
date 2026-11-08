# v4.71 — Ada 基准源码（5/5 校验和一致）

- 日期：2026-11-08
- 性质：基准数据源（Ada / gnatmake）

## 改动

- `bench/speed/ada/`：提交 5 个基准（`b1_int` / `b3_recursion` / `b10_ackermann`
  `b11_nqueens` / `b12_gcd`），算法与 C 逐字等价。
- 修正 `b12_gcd.adb`：Ada 的 `X mod Y` 结果符号随除数，而 C 的 `X % Y`
  符号随被除数；对 `1000000 - I`（I>1000000 时为负）的取模结果不同。
  改为 C 语义余数 `X - (X / Y) * Y`（Ada `/` 向零截断），对齐 C。
- 输出用 `Trim(..., Left)` 去掉 `Long_Long_Integer'Image` 的前导空格，
  保证校验和与 C 逐字节一致。

## 验证

- `python3 tools/benchgen/verify_lang.py ada` → `match=5 absent=0 mismatch=0`。
