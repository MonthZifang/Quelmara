# v4.129 — 零常量零惯用法：`mov r,0` → `xor r32,r32`（产物变小）

- 日期：2026-11-24
- 任务：通用发射器微优化。清零是极常见操作（初始化累加器/循环变量、syscall 实参），
  `mov r,0`（5–10 字节、对 r 旧值有数据依赖）换成 `xor r32,r32`（2–3 字节、
  零惯用法、打破假依赖）。这是 x86 标准优化，对所有含零常量的基准生效。
- 影响面：编译器（stage-1 发射器 `_mov_imm`，不动 IR / pass / vloc）

## 实现

`_mov_imm(code, dst, 0)` 走专用路径：

```
dst < 8:  31 C0 | (dst<<3) | dst        （2 字节，无 REX）
dst >= 8: 45 31 C0 | ((dst&7)<<3) | (dst&7)  （3 字节，REX.R|B=1）
```

32 位写自动清高 32 位，所以 `xor r32d,r32d` 与"写 64 位 0"逐位等价。
Qlm 的 IR 比较一律显式发 `CMP/CMPI` 再 setcc/jcc，`xor` 改标志位不影响任何判断。

**踩过的坑（已修，重启必读）**：首版对 dst>=8 只置 REX.B（0x41），
`xor`  opcode 0x31 是 `XOR r/m, reg` —— reg 字段（源）由 REX.R 扩展、
r/m 字段（目的）由 REX.B 扩展。只置 B 会把 `xor r12d,r12d` 编成
`xor r12d,esp`，**静默算错**（tiny 测试 10→0、b34 校验和错）。
必须同时置 R 和 B（REX=0x45）。已用 gcc+objdump 核对两种寄存器类别：
`xor %eax,%eax = 31 c0`、`xor %r12d,%r12d = 45 31 e4`。

## 收益（本机）

| 项 | 结果 |
|---|---|
| ELF 体积 | 8 项变化，合计 **−165 字节**（b13 −21、b17 −27、b11 −27 …），约 −0.4% |
| 运行时间 | b34 0.999、b1 1.000、b78 1.005（min-of-7，**噪声内、无可分辨收益**） |

诚实结论：本机**没有可测的速度收益**（零惯用法打破假依赖、体积变小，
但这两个基准的热循环里没有清零），保留理由是语义等价、体积变小、
教科书式通用改进；真实收益需 CI 确认。

## 验证

| 项 | 结果 |
|---|---|
| 新旧 qlmc 编全量 76 基准到 ELF 并运行 | **76/76 校验和一致**（其中 b61 一次 wine IPC 抖动重编后一致） |
| 差分夹具 s_unsigned_mod / s_unsigned_scope / s_nonneg_sound / s_ref / s25_divmod | 5/5 stage-0 与新 qlmc 逐字节一致 |
| `python3 tests/qlmc_test.py --qlmc build/qlmc_v4129b.exe` | **PASS=134 FAIL=0**（首次 133/1 是 stage-0 侧 `s22_f64print` 的 wine `Exec format error` 抖动，重跑全过） |
| `python3 tests/bootstrap_test.py --strict` | **PASS**：stage-2 与 stage-1 逐字节等价（42/42 组）、stage-2 == stage-3 不动点成立 |
| `python3 tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- 只动**寄存器目的** `mov_imm`；写帧槽走 `_mov_imm_mem`（需要寄存器中转，不适用）。
- 只处理 `v == 0`；其它常量原样发 `mov`。
## CI 实测（run 45336012139，推送后权威口径）

三个 job 全绿（含 macOS），76/76 校验和零 MISMATCH。但**本轮 CI 噪声异常大，
无法给出可信的性能结论**：

| 平台 | 指标 | v4.128 | v4.129 |
|---|---|---|---|
| Windows | 几何平均 qlm/C | 2.008 | 2.078（表观回退） |
| Ubuntu | 几何平均 qlm/C | 1.436 | 1.554（表观回退） |
| Windows | C 参照中位数变化 | — | **0.763×**（同一份 C 代码快了 31%） |
| Ubuntu | C 参照中位数变化 | — | **1.535×**（同一份 C 代码慢了 54%） |

同一份 C 基准在两个平台分别快 31%/慢 54%，证明是 runner 负载/CPU 差异
（Windows runner CPU 本轮也换了），不是本改动造成。qlm 侧某些项出现 2× 反向
摆动（b81 Ubuntu 10→24ms、Windows 20→18ms），与"只改 165 字节、热循环无清零"
矛盾，同属噪声。**本轮性能判为中性**（本机 7 轮也中性）；保留改动是因语义
等价、产物更小、零风险，不声称任何 CI 性能收益。
