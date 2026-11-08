# v4.70 — Nim 基准源码（3/3 校验和一致）

- 日期：2026-11-08
- 性质：基准数据源（Nim / ldc2 兼容）

## 改动

- `bench/speed/nim/`：提交 3 个核心基准（`b1_int` / `b8_threads4` / `b28_matrix`），
  算法与 C 逐字等价，输出格式对齐（起始 ns 行 + `T` + 耗时 ns）。
- 覆盖尚小（Nim 在 posix CI 矩阵中仅作点缀，缺失项由 runner 跳过），
  后续版本可继续扩到全 76。

## 验证

- `python3 tools/benchgen/verify_lang.py nim` → `match=3 absent=0 mismatch=0`。
