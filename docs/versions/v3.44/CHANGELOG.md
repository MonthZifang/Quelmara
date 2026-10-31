# v3.44 — UDP 接收侧四个内建落地；`udp_sendto` 未完成（如实记录）

- 日期：2026-10-31
- 任务：用户要求"继续"；v3.43 之后按性价比选 UDP（一次能解三个模块）
- 影响面：`bootstrap/qlmc/qlmc.qma`（4 个 UDP IAT 槽位 + 7 个内建）、
  `tests/t188_qlmc_udp.qma`、`tests/udp_e2e_test.py`、`tests/run_win_tests.py`
- 覆盖率：**46 / 70（没涨）** —— 原因见下，不掩饰
- 回归：PASS=360 → **361** FAIL=0 SKIP=0

## 这一版的实际产出

**7 个内建落地并通过端到端验证**：

| 内建 | 状态 | 验证方式 |
|---|---|---|
| `udp_open()` | ✅ | e2e 拿到有效 fd |
| `udp_open6()` | ✅ | 编译通过（未跑 v6 端到端） |
| `udp_bind(fd, port)` | ✅ | e2e 绑 39480 成功 |
| `udp_recvfrom(fd, cap)` | ✅ | e2e 收到 `alpha` |
| `udp_recvfrom6(fd, cap)` | ✅ | 编译通过 |
| `udp_recvfrom_to(fd, cap, ms)` | ✅ | e2e 收到 `bravo` + 超时返回空串 |
| `udp_recvfrom6_to(fd, cap, ms)` | ✅ | 编译通过 |

配套：`I_USER` 21 → 24，新增 `I_SENDTO=21` / `I_RECVFROM=22` /
`I_SETSOCKOPT=23`，`_reg_ws2` 加 3 个符号。

`udp_recvfrom_to` 的超时语义是这一版最有价值的部分：`setsockopt(SO_RCVTIMEO)`
设上之后，对端不发东西时**返回空串而不是永久阻塞** —— 这正是 `dns`
查询循环能停下来的前提。

```
[PASS] udp_recvfrom 收到第 1 个 datagram（alpha）
[PASS] udp_recvfrom_to 收到第 2 个 datagram（bravo）
[PASS] 超时（300ms）返回空串 —— 不挂死
=== t188 udp e2e: PASS=5 FAIL=0 ===
```

## 未完成：`udp_sendto` / `udp_sendto6` 崩溃（未解决）

**症状**：调用即 `0xC0000005`，而且**连函数体第一条指令都执行不到**
（插桩标记 301 打不出来）。

**已排除的原因**（每条都做了对照实验）：

| 假设 | 实验 | 结论 |
|---|---|---|
| IAT 槽位错 | dump 导入表 | ❌ 槽位正确，`sendto` 在第 9 个 |
| 栈实参偏移错 | 试 32/40、0/8、改用 `_emit_call_args` | ❌ 三种都崩 |
| 寄存器冲突 | 所有实参 `_pin` 成变量 | ❌ 仍崩 |
| 帧不够大 | 函数开头加 dummy alloc 撑帧 | ❌ 仍崩 |
| `OP_LEN` 算长度有问题 | 换成常量 3 | ❌ 仍崩 |
| 字面量 vs 拼接串 | 两种都试 | ❌ 都崩 |
| 实参求值顺序 | 逐条 lowering + pin | ❌ 仍崩 |

**关键对照**（说明不是机制问题）：

* 同一份 `.qma`，stage-0 编出来 **PASS=5 FAIL=0**，qlmc 编出来崩；
* qlmc 的 **6 参数用户函数调用完全正常**（`f6(11,22,33,44,55,66)` → 231）；
* `udp_recvfrom_to` 内部**同时有 5 参 `setsockopt` 和 6 参 `recvfrom`**，
  两者都工作 —— 同样是 `_emit_call_args` + `OP_CALLIAT`，只有 `sendto` 崩；
* 二分到函数体内：alloc/清零/构造 sockaddr 全段都正常，崩在
  `_emit_call_args` + `CALLIAT` 那一段，但同样的写法在 `recvfrom` 里没事。

**结论**：这是 qlmc 的一个**未定位的代码生成缺陷**，靠黑盒二分已经到极限。
下一步需要 **IR dump 工具**（把 qlmc 生成的 IR 序列与 stage-0 的逐条对照），
那是独立的一件事，不适合塞在补内建的版本里。

已登记到 `docs/07-gaps.md` §7.20。

## 为什么覆盖率没涨

`std/net/udp.qma` 的 `udp_send_str` 里有 `udp_sendto` 调用点，所以
**只要 import 这个模块就编不过**。接收侧四个内建虽然全通，但没有模块
只靠它们就能过。

这是如实记录：**这一版买了 7 个可用内建 + 一条精确的缺陷定位，
没买到覆盖率数字。**

## 一个方法教训

这次在 `udp_sendto` 上花了约 40 轮，全程靠"猜假设 → 改代码 → 重编 2 分钟
→ 跑一次"的循环。重编 qlmc 要 2 分钟，40 轮就是 80 分钟的纯等待。

**更早该做的是**：先花 20 分钟写 IR dump（`fc.ir` 直接打出来），
一次就能看到 `sendto` 那段生成的指令序列长什么样，和 `recvfrom`
逐条对比。工具的投入产出比在这类问题上远高于反复试错。

这条已写进 `docs/00-convention.md` §6（调试方法）。

## 回归与自举

```
PASS=361 FAIL=0 SKIP=0
自举五级链：stage-2 可用且与 stage-1 逐字节等价（不动点成立）
parsediff 243
```
