# v3.46 — `thread_yield` / `wall_ms` 落地；`file_size` 未成（如实记录）

- 日期：2026-10-31
- 任务：用户要求"继续"；换方向避开 `udp_sendto`，做单点内建
- 影响面：`bootstrap/qlmc/qlmc.qma`（2 个 kernel32 IAT 槽 + 2 个内建）、
  `tests/t189_qlmc_time.qma`、`tests/run_win_tests.py`
- 覆盖率：46 / 70（**没涨** —— 原因见下）
- 回归：PASS=362 → **363** FAIL=0 SKIP=0

## 做了什么

**两个内建落地并通过性质断言**：

| 内建 | 实现 | 验证 |
|---|---|---|
| `thread_yield()` | `SwitchToThread`（kernel32） | 单次 + 循环 5 次，不崩不卡 |
| `wall_ms()` | `GetSystemTimeAsFileTime` → 减 1601→1970 差值 → `/10000` | 落在 2020–2100 区间、连续调用单调不减 |

配套：`I_YIELD = 12`、`I_FILETIME = 13`（kernel32 组），ws2_32 整体后移到
15..26，`I_USER` 26 → 27。新增 `_reg_k32b` 登记函数（独立函数，避免
`build_rdata` 帧槽超限）。

```
[PASS] yield single ok / yield loop ok
[PASS] wall_ms after 2020 / before 2100 / monotonic
=== t189 ok ===
```

## 顺带修了 `irdump` 的一个真 bug

`_op_name` 的名字表**整体错位 1**（v3.45 手工填表时漏了一项）：
`OP_ARG(16)` 显示成 `JNZ`、`OP_CALLIAT(36)` 显示成 `RTADDR`。

这个 bug 很阴：v3.45 我用它排查 `udp_sendto` 时，把 `ARG` 读成了 `JNZ`，
差点又走错方向。

修复方式改了：**不再手填表**，改成从源码里的 `const OP_* = N` 直接生成
（`_rebuild_names.py` 用正则抓 `^const (OP_\w+) = (\d+)`）。这样加新
opcode 时表自动跟上，不会再错位。

## 未完成：`file_size(path)`（失败，已回退）

尝试了三个版本，全部返回 `4294967295`（`0xFFFFFFFF`）：

1. `CreateFileA` + `GetFileSize` + `CloseHandle` —— 直接 `cmp rax, -1`
   → 漏检（Win64 的 `INVALID_HANDLE_VALUE` 是 `0x00000000FFFFFFFF`）；
2. 加 `shl 32 / sar 32` 符号扩展 —— 仍然 `0xFFFFFFFF`；
3. `GetFileSize` 的第 2 参从 `NULL` 改成真实 8 字节缓冲（怕它写寄存器）
   —— 仍然 `0xFFFFFFFF`；
4. 把 7 个实参里的重复 `zero` 改成独立 vreg（怕 `_pin` 钉多次）
   —— 仍然 `0xFFFFFFFF`。

**用 irdump 看到的关键现象**：`CreateFileA` 的 7 个实参在 IR 里是

```
STKARG a=36 imm=32    ← 第 5
STKARG a=33 imm=40    ← 第 6
STKARG a=33 imm=48    ← 第 7
ARG a=32 imm=0 / a=34 imm=1 / a=37 imm=2 / a=38 imm=3
```

第 6/7 个实参拿到的是同一个 vreg（`33`），而我在源码里 `av.push(zero)`
三次引用的也是同一个 `zero` —— 看起来一致，但第 4 个实参却是 `38`。
**说明 `_emit_call_args` 的 `_pin` 对同一个 vreg 多次出现时行为不一致**，
或者优化器把重复常量折叠成了不同落点。

这条已登记 `07-gaps.md` §7.37，重启条件：先用 irdump 对比
`@ffi` 7 参（已知可用）与内建 7 参的 IR 差异，重点看
**同一个 vreg 在多个实参位置出现时 `_pin` 的行为**。

## 为什么覆盖率没涨

三个目标模块各有**别的**缺口：

* `std/log.qma` —— 补了 `wall_ms` 后缺 `f`（函数值调用）；
* `std/net/reactor.qma` —— 补了 `thread_yield` 后缺 `cb`（同样是函数值调用）；
* `std/staticfile.qma` —— 缺 `read_text`（本轮试过，让 qlmc 编译期崩溃，已回退）。

**函数值调用**（把函数当参数传、再 `f(...)` 调用）是这三个模块的共同卡点，
也是 qlmc 子集的真实缺口。这比单点内建的性价比高得多，值得单独立项。

## 回归与自举

```
PASS=363 FAIL=0 SKIP=0
自举五级链：stage-2 可用且与 stage-1 逐字节等价（30/30 组，不动点成立）
```
