# v2.66 — 越界检查收成一条无符号比较（这次真的进了代码）

- 日期：2026-10-27
- 任务：继续压 b7/b9/b4 的每次下标访问成本
- 影响面：`tools/stage0/qlm_native.py`（`emit_bounds` + `__vec_get/get_n/set/set_n`）

## 先纠正一条记录

`versions/v2.60/CHANGELOG.md` 写了"越界检查收成一条无符号比较"，
但**那次改动没有进提交**：做 A/B 的脚本 `build/licm/bounds_ab.py`
最后一轮跑的是 `off`，把源码留在了旧形态，之后直接提交了。
本轮重新实现，并这次用正确的基准列（`--langs quelmara0`）量过。

## 改法

```
旧（每次下标）                          新
jcc ge  idx, n  -> fail                jcc b   idx, n -> ok
jcc ge  idx, 0  -> ok                  (fallthrough) fail
                                       label ok
```

```
旧（vec.get/set 内联体）                新
cmpset l  b, idx, 0                    cmpset b b, idx, len
jnz      b, fail                       jz       b, fail
cmpset ge b, idx, len
jnz      b, fail
```

**为什么对**：负下标的无符号解释是巨大值（`2^64 - k`），必然 `>= n`，
与"idx 越上界"走同一条失败路径。所以"idx >= 0"那次比较是多余的 ——
它只是把两种越界分成两条分支，语义上并不需要。

四处 `__vec_*` 与 `emit_bounds` 都改了；`qlm_arm64.COND` 在 v2.60 就补过
`b/ae/a/be`（A64 的 LO/HS/HI/LS），本轮不用再动。

## 效果（本机 min of 5，两轮交替 A/B）

| 基准 | 旧 | 新 | 变化 |
|---|---|---|---|
| b4_array | 20.2 / 20.1 | 19.3 / 18.1 | −5 ~ −10% |
| b7_sort | 45.5 / 45.5 | 43.1 / 39.3 | −5 ~ −14% |
| b9_json | 36.8 / 42.1 | 34.9 / 38.6 | −5 ~ −8% |

省的是**每次下标访问 2 条指令 + 1 个分支**。b7/b9/b4 都是下标密集型，
所以三个都降；整数/浮点计算类基准（b1/b2/b3/b5/b6）没有下标访问，不受影响。

负下标仍然 fail-fast（`vec index out of bounds`），已单独验证。

## 连带修的一处：A64 模拟器不认识无符号条件码

改成 `cmpset b` 之后，arm64 后端会发 `cset <LO>`（0x3），而
`tests/a64_emu.py` 的 `cond_holds` / `CSET` 反查表**只认 6 个有符号条件码** ——
`KeyError: 2`，`AArch64 接口 vtable 执行级` 直接 5/7 失败。

补上 HS(0x2)/LO(0x3)/HI(0x8)/LS(0x9) 的判定与取反（`C` 标志就是无符号
借位：`set_flags_sub` 里 `C = 1 if a >= b else 0`）。修完
`tests/a64_iface_test.py` 回到 **PASS=7 FAIL=0**。

**教训**：改 IR 的条件码，要同时检查**后端**（`qlm_arm64.COND`）与
**模拟器**（`tests/a64_emu.py` 的两张表）—— v2.60 只改了前者，所以这次
一用上就炸。

## 回归

`tests/run_win_tests.py`：**PASS=295 FAIL=0 SKIP=1**（含 t148）。
中途那一版只挂了 `AArch64 接口 vtable 执行级`（模拟器缺条件码，与编译器
本身无关），补完后单独复跑 `tests/a64_iface_test.py` 全绿。
