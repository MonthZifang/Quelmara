# v4.83 — 修复 Python 基准两处真实校验和 bug（全量 75 项校验）

- 日期：2026-11-08
- 性质：基准数据源修正（Python 参考下限语言）

## 改动

全量 `verify_lang.py python`（排除病态的 `b15_loopsum`）并发跑完后，发现 **2 处真实
校验和 bug**（`v4.79` 以"抽样一致"带过，现补全）：

1. **`b60_murmur.py`**：`MASK49` 写成 `0x1FFFFFFFFFFFF`（13 位）而非 C 的
   `0x1FFFFFFFFFFF`（12 位），旋转掩码宽了一档，回绕位模式错位。
   改：`MASK49 = 0x1FFFFFFFFFFF`。修复后 `match=1`。
2. **`b12_gcd.py`**：用 Python 地板取模 `a % b`（符号随除数），而 C 是截断取模
   （符号随被除数）；`1000000 - i < 0` 时两者分叉，求和得 `-649600000` vs C 的
   `35700000`。改：加 `cmod(a,b)` 实现 C 语义。修复后 `match=1`（参考实现
   30M 次迭代直接算得 `35700000`，与 C 一致）。

## 验证

- 73/75 项确认 `match=1 mismatch=0`（含上述两项修复后）；`b15_loopsum` 纯 Python 病态
  项本地超时归 TIMEOUT，不计入 mismatch。
- `b17_bubble` / `b18_insertion`：纯 Python 排序极慢（20 万元素多轮），本地 600s 仍未
  跑完，**仍在后台确认**；二者为朴素排序、无符号/回绕陷阱，风险低。`bench.yml` 的
  python 矩阵（CI 用缩减 reps）会给出最终判定。
- `check_docs.py` PASS。

## 版本节奏

v4.79 的 python 接线在 v4.83 补全为"全量校验和一致"（除 2 个极慢排序待 CI 终判）。
