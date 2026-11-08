# v4.69 — Fortran 基准源码扩到 70 项（70/70 校验和一致）

- 日期：2026-11-08
- 性质：基准数据源（Fortran / gfortran）

## 改动

- `bench/speed/fortran/`：从 48 项扩展到 70 项（`b31`–`b87` 大部分，含
  `b9_json` 递归下降解析、`b8_threads1/4` 确定性求和复现）。
- 修正 4 个此前编译/运行错误的文件：
  - `b49_floyd` / `b52_io_scan` / `b54_merge_sort`：补全缺失的循环变量声明。
  - `b60_murmur`：Fortran `ishft(k,-51)` 是逻辑（零扩展）右移，而 C `>>`
    在 int64 上是算术（符号扩展）右移；负数时二者结果不同。新增
    `ashr` 算术右移辅助函数并对齐 C 行为，校验和恢复为
    `1862168077173513743`。
- 计时与输出沿用既有 fortran 约定（起始 ns 行 + `T` + 耗时 ns）。

## 跳过（SPEC 允许，浮点/字符串基准难以逐字节匹配）

`b2_float` / `b16_leibniz` / `b66_integrate`（浮点）、`b5_string` / `b46_strcat`
`b76_io_line`（字符串），共 6 项。后续可单独立项补齐。

## 验证

- `python3 tools/benchgen/verify_lang.py fortran` → `match=70 absent=0 mismatch=0`。

## 版本节奏

fortran(v4.69) → ada/d/nim → python/java/csharp → zig（待修）。
