# v4.77 — D 基准源码（2/2 校验和一致）

- 日期：2026-11-08
- 性质：基准数据源（D / dmd/ldc2，子集）

## 改动

- `bench/speed/d/`：补齐 `b1_int`、`b87_memcopy_big` 两项（D 仅覆盖整数与内存拷贝
  两类友好形态，作为参考子集）。
- 校验和逐字节对齐 C。

## 验证

- `python3 tools/benchgen/verify_lang.py d` → `match=2 absent=0 mismatch=0 timeout=0`。

## 版本节奏

d(v4.77) → python(v4.75，待本地校验完成后提交)。
