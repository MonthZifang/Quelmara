# v3.58 — SIMD（XMM）基础四件；qlmc 差分 80 → 82

- 日期：2026-11-01
- 任务：用户要求"继续"；开 SIMD 轨道的第一版（基础设施验证）
- 影响面：`bootstrap/qlmc/qlmc.qma`（3 个新 IR 节点 + `_emit_xmm` +
  4 个内建 + SSE 前缀扩展）、`tests/t202_qlmc_simd.qma`、`tests/qlmc_test.py`
- 覆盖率：**60 / 70（不变）** —— 本版是基础设施，`std/aes` 还差 8 个内建
- 回归：PASS=370 FAIL=0 SKIP=0；qlmc 差分 80 → **82**

## 为什么只做四件

`std/aes` 需要 **12 个** SIMD 内建：

```
xmm_load, xmm_store, xmm_mov, xmm_pxor, pand, por, pshufb,
pclmulqdq, aesenc, aesenclast, cpu_aes, cpu_pclmul
```

一次全做风险太大。这四件（load / store / mov / pxor）是其余 8 个的**公共
基础** —— 它们验证「XMM 通路 + 指令编码」是否打通，后续按同一模式扩。

## 关键设计：槽号是编译期常量

`xmm_load(0, addr)` 里的 `0` 直接就是 **XMM0**，不需要寄存器分配。

这是 SIMD 内建和普通值最大的不同：普通 vreg 要经过线性扫描分配，而 XMM
槽是程序员显式指定的。所以 IR 里槽号放 `imm`，地址放 vreg。

**槽号限制 0..7** —— stage-0 的报错信息写着 "xmm 槽参数必须是 0-7 的编译期
常量"。虽然 XMM 有 16 个，但 8..15 是 Win64 的**非易失**寄存器，跨调用要
保存 —— 而 SIMD 内建不参与寄存器分配，没法保证这一点。限制在 0..7 既与
基准同口径，也避免静默破坏调用方的 XMM8..15。

## 三个新 IR 节点

```
OP_XMMLD = 81   a = 地址 vreg，imm = 槽号     → movdqu xmm[s], [a]   F3 0F 6F /r
OP_XMMST = 82   a = 地址 vreg，imm = 槽号     → movdqu [a], xmm[s]   F3 0F 7F /r
OP_XMMRR = 83   imm 打包四个值                → 槽间运算
```

`OP_XMMRR` 的 `imm` 打包：`(pf << 24) | (opc << 16) | (dst << 8) | src`。

**为什么全塞进 `imm`**：`_ir_emit` 里 `if a > 0 { fc.vend.set(a, i) }` ——
`a` 和 `b` 位置必须是**合法 vreg 或 0**，塞槽号/操作码会越界。这是
v3.58 实测踩到的（`a = 239` 直接 `vec index out of bounds`）。

## SSE 前缀扩展

原来 `_sse_rr` / `_sse_mem` / `_sse_mem0` 的 `pf` 只有 0（`66`）和 1（`F2`）。
`movdqu` 需要 **`F3`**，所以加 `pf == 2` 分支。

## 一个编码陷阱

`xmm_mov` 第一版传 `pf = 2`，想发 `movaps`（`0F 28`）—— 结果发出 `F3 0F 28`，
不是 movaps 的编码，运行时崩 `0xC000005D`。

改用 **`pf = 0` → `66 0F 28` = `movapd`**：同样是整 128 位搬、效果等价，
而且能走现成的 pf=0 路径。

## 测试

`tests/t202_qlmc_simd.qma`，加进 `tests/qlmc_test.py` 的 `CASES` 作为
**差分用例**（`s35_simd`），10 行输出与 stage-0 逐字节一致（70 字节）。

| 判据 | 抓什么 |
|---|---|
| `copy=1` | load + store 整块拷贝 |
| `xor_self=1` / `xor_ab=1` | pxor 语义 |
| `mov=1` | 槽间 128 位搬 |
| `b0=1` / `b7=8` / `b8=9` / `b15=16` | **跨 64 位边界** —— 只看 b0 的话"只搬了低 64 位"也会通过 |
| `hi_slot=1` | 槽号 7 也能用 |

`b7` / `b8` 这两条最关键：`movsd` 只写低 64 位，`movapd` / `movdqu` 才是
128 位。v2.55 在 CI 上就因为误用 `movsd` 出过性能与正确性问题。

## 覆盖率

**60 / 70（本版没涨）**。`std/aes` 还差 8 个内建：

```
pand, por, pshufb, pclmulqdq,
aesenc, aesenclast, cpu_aes, cpu_pclmul
```

其中 `aesenc` / `aesenclast` 是 AES-NI（`66 0F 38 DC/DD`），
`pclmulqdq` 是 PCLMUL（`66 0F 3A 44`），`pshufb` 是 SSSE3（`66 0F 38 00`）——
都需要新的编码路径（0F 38 / 0F 3A 三字节 opcode map）。

下一版可以一次补齐，预计解开 `std/aes` → `std/tls13`（60 → 62）。

## 自举

30/30 组等价 + 不动点成立。stage-2 产物 650752 B，仍在 `ARENA_CAP = 4 MB`
余量内。

## 方法教训

这一版**先建诊断再动手**，但诊断粒度不够细：前两次探针（`_emit_xmm` 入口、
`_bi_xmm_rr` 入口）都打出来了，崩溃却在两者之间 —— 直到在 `_bi_xmm_rr`
**内部逐句打点**才定位到 `_ir_emit` 的 `a` 参数越界。

**教训**：怀疑某个函数时，直接在函数体内逐句打点，不要只在入口/出口打 ——
入口打点只能证明"进来了"，证明不了"哪一句炸的"。
