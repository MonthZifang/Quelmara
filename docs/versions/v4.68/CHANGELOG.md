# v4.68 — Rust 基准源码扩到全 76 项（76/76 校验和一致）

- 日期：2026-11-08
- 性质：基准数据源（Rust）

## 改动

- `bench/speed/rust/`：补齐扩展集 `b31`–`b87`，覆盖全部 76 个规范基准。
- 修正 `b74_accum_poly.rs`：原稿在内层循环对累加值取模，与 C（先求
  `s % M` 再累加、最后才取模）的溢出/取模口径不一致导致校验和偏差；
  改为逐字复刻 C 的累加逻辑（`acc += s % 1000003`，不中途取模），
  最终 `acc % 1000003` 输出。

## 验证

- `python3 tools/benchgen/verify_lang.py rust` → `match=76 absent=0 mismatch=0`。

## 版本节奏

rust(v4.68) → fortran(v4.69) → ada/d/nim → python/java/csharp → zig（待修）。
