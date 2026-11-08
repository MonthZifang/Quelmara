# v4.73 — Zig 基准源码扩到全 76 项（76/76 校验和一致）

- 日期：2026-11-08
- 性质：基准数据源（Zig / zig 0.14）

## 改动

- `bench/speed/zig/`：补齐扩展集 `b31`–`b87`，覆盖全部 76 个规范基准，统一以
  `pub fn main() !void` 入口、`std.time.nanoTimestamp()` 计时。
- 修正 `b60_murmur.zig`：原实现用有符号 `i64` 直接做 `key << 13` / `key >> 51` 与
  `int64` 乘法回绕。Zig 在循环趟数可由编译期证出（如 `while (i < 1000000)`）时，会按
  "有符号不溢出" 假设优化，导致与 C 的 2 补码回绕语义分叉（结果恰为相反数
  `-1862168077173513743` vs C 的 `1862168077173513743`）。改为全程走 `u64`
  （`*%` / `+%` 回绕）并用 `ashr()` 手动做符号扩展右移（Zig 的 `>>` 对 `u64` 是逻辑
  右移，需补回符号位），从而与 C 的 `int64` 位模式逐位一致，且该写法不受 comptime
  循环趟数优化影响。其余 75 项经复核为陈旧构建造成的误判，重跑后已一致。

## 验证

- `python3 tools/benchgen/verify_lang.py zig` → `match=76 absent=0 mismatch=0 timeout=0`。
- `gh auth setup-git` 已在本次会话恢复；CI posix 矩阵会真跑 zig。

## 版本节奏

zig(v4.73) → verify_lang.py 超时处理（v4.74，python 校验前置）→ python(v4.75) →
csharp(v4.75 同轮说明，CI windows 真跑) → d(v4.76)。
