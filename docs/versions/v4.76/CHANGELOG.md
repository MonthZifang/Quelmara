# v4.76 — C# 基准源码扩到全 76 项（CI windows 真跑）

- 日期：2026-11-08
- 性质：基准数据源（C# / dotnet，windows 矩阵）

## 改动

- `bench/speed/csharp/`：补齐扩展集 `b31`–`b87`，覆盖全部 76 个规范基准，统一用
  top-level statements（`using System;` + `var sw = Stopwatch.StartNew();`），掩码与
  移位对齐 C（如 `b60_murmur` 用 `0x1FFFFFFFFFFFL`，52 位 + `L` 后缀）。
- 注：本机无 `dotnet`，无法本地校验和；C# 仅在 CI windows 矩阵真跑，
  `run.py` 在无 SDK 时自动跳过并记入 notes（同 v4.72 的 C# 口径）。

## 验证

- 本地 `dotnet` 缺失，CI windows 矩阵真跑后由 `run.py` 记录；掩码/算法经人工核对与 C 对齐。
- `check_docs.py` PASS。

## 版本节奏

csharp(v4.76) → d(v4.77) → python(v4.75，待本地校验完成后提交)。
