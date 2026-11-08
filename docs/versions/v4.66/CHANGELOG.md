# v4.66 — Go 基准源码扩到 75 项全集（76/76 校验和一致）

- 日期：2026-11-08
- 性质：基准数据源（Go）

## 改动

- `bench/speed/go/`：在原有 24 项核心基准之上，补齐扩展集
  `b31`–`b87`，使 Go 覆盖全部 76 个规范基准（benchmark 列表见
  `bench/speed/run.py` 的 `BENCHES`）。
- 算法与 C 逐字等价（含 `b8_threads4` / `b53_thread_sim` 用 goroutine
  复现确定性求和），输出格式沿用既有 go 约定（起始 ns 行 + `T` + 耗时 ns）。

## 验证

- `python3 tools/benchgen/verify_lang.py go` → `match=76 absent=0 mismatch=0`。
- 浮点基准（`b2_float` / `b16_leibniz`）沿用既有 go 文件，仍逐项一致。

## 版本节奏

每个语言源码覆盖独立成版本：go(v4.66) → cpp → rust → python → ada/nim/d →
fortran → zig → java → csharp。
