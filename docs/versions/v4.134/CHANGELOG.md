# v4.134 — 消除 f64 复制的 XMM→GP→XMM 往返（b16 热循环 −29%）

- 日期：2026-11-24
- 任务：消除 b16_leibniz 热循环里 `let d = to_float(...)` 产生的无用
  `movq xmm,r` / `movq r,xmm` 往返搬运：f64 值被复制到 GP 寄存器后又在两个
  除法分支里搬回 XMM。
- 影响面：编译器（qlmc 优化管线，不改语言/标准库）

## 根因

b16 降级的 IR 里 `T=ITOF(...)` 后紧跟 `MOV d=T`（use=2，两条分支各读一次）：
既有 `_opt_copy` 要求 `use[dst]==1`，所以不转发；`d` 落到 GP 寄存器，
两个 `FBIN` 各发一条 `movq xmm1,r14` 把位模式搬回 XMM 再 `divsd`。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增独立 pass `_opt_copy_f64`，接在 `_opt` 流水线的 `_opt_copy` 之后（以及重算 use/ndef 后的位置不变）。当 `MOV d=T,f64` 且 d/T 都是 TY_F64 单定义、非聚合、T 非变量（`vpin==0`）、d 的**全部**使用都是 OP_FBIN/OP_FCMP 的 b 槽、MOV 前无 d 的读、MOV 到最远使用点之间无 T 的第二个定义时：把所有 `b:d` 换成 `b:T`、MOV 改 NOP，并延长 `vend[T]`、补回 `use[T]`。d 是 `let` 变量槽（`vpin==1`）也放行——它只被这一次 MOV 定义、且所有读取都在受控的 b 槽里。 |

## 验证

| 命令 / 判据 | 结果 |
|---|---|
| `python3 tools/stage0/qlm_cli.py build bootstrap/qlmc/qlmc.qma --target win -o build/qlmc_fmov.exe` | PASS（新编译器 5,513,216 字节） |
| `qlmc irdump bench/speed/quelmara/b16_leibniz.qma main` | IR 31 `MOV→NOP`，36/40 `FBIN b:23→b:28`；反汇编热循环 `movq xmm1,r14` 往返消失，`cvtsi2sd` 结果留在 xmm0 直接 `divsd` |
| 差分夹具（stage0 vs qlmc，过滤 `[qlm]` 行）s21_f64 / s22_f64print / s15_bitops / s_unsigned_mod / s25_divmod | 5/5 逐字节一致 |
| 全量 76 基准新旧 qlmc 各编 ELF 运行 | 76/76 校验和一致（b16=3.141593、b2=16.002164、b66=999992） |
| 本地 A/B 交替 7 轮取 min | b16 454.97→323.51ms（**0.7111，−29%**）；b2 80.99→80.96ms（0.9995）；b66 19.22→19.19ms（0.9985）；无 >5% 回退 |
| `python3 tests/qlmc_test.py --qlmc build/qlmc_fmov.exe` | PASS=136 FAIL=0（首轮 s9_slice 遇 wine 抖动 stage0 侧 rc=1，重跑全过） |
| `python3 tests/bootstrap_test.py --strict` | PASS（42/42 组产物一致、不动点 stage-2==stage-3） |
| `python3 tools/dev/check_docs.py` | PASS |

> 上述耗时为本机 min-of-7，微架构/负载与 CI runner 不同，不代表 CI 数字。

## 已知边界 / 遗留

- 只转发 b 槽，不碰 a 槽、不碰 OP_FBIN/OP_FCMP 之外的 opcode（保守）。
- 若 d 在 MOV 之前还有读取（循环回边/另一分支）或 MOV 与最远使用之间有 T 的
  第二个定义，pass 主动拒绝，形状不变。
- 收益集中在"一个 f64 值被两个分支共用"的形状（b16）；b2_float / b66_integrate
  这类单使用者形状本就被 `_opt_copy` 覆盖，无变化。
