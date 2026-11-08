# v4.67 — C++ 基准源码扩到全 76 项（76/76 校验和一致）

- 日期：2026-11-08
- 性质：基准数据源（C++）

## 改动

- `bench/speed/cpp/`：补齐扩展集 `b31`–`b87`，复用 C 的 `bench.h` 计时宏，
  覆盖全部 76 个规范基准。
- 修正 `b87_memcopy_big.cpp` 缺 `#include <cstring>` 导致的编译失败
  （该文件此前在校验门禁中被发现 `memcpy` 未声明）。

## 验证

- `python3 tools/benchgen/verify_lang.py cpp` → `match=76 absent=0 mismatch=0`。

## 版本节奏

每语言独立成版本：go(v4.66) → cpp(v4.67) → rust/fortran/nim → ada/d →
python/java/csharp → zig（待修）。
