# v4.131 — LCG 归纳扩展到带分支循环（b65 −24%、b26 −34%）

- 日期：2026-11-24
- 任务：v4.130 的 `_nn_lcg_induct` 要求整个循环体无分支，b65_random_walk /
  b26_maxsub 因 LCG 更新之后有条件分支被保守拒绝，`%2^31` 等仍走 13 条
  有符号符号修正链。本版把判据放宽到"LCG 三连原子、循环内可有分支"。
- 影响面：编译器（stage-1 优化 pass，不动调用约定 / IR 语义）

## 核心论证（soundness 全部分量）

**定理**：若 `v` 全函数恰好写两次（入口 CONST + 唯一 LCG 更新，`ndef[v]==2`），
入口 `v0 ∈ [0,D-1]`，且更新 `v ↦ (v*C+K) % D` 满足 `C>0, K≥0, D≥2`、
`(D-1)*C+K < 2^62`（先不溢出，C99 截断余数对非负数落在 `[0,D-1]`），
则 **任何执行路径上 v 恒 ∈ [0,D-1]**，与循环内的分支/跳转/跳过模式无关：
- 执行更新 → 新值仍在 `[0,D-1]`（区间闭合性）；
- 跳过更新 → v 保持原值，仍在 `[0,D-1]`。

所以 v4.130 的 `_nn_loop_shape`（要求整个循环体无分支）对 LCG 归纳是**过度保守**。
本版只需保证 LCG 三连 `BINI v,MUL,C` → `BINI t,ADD,K` → `DIVC v,..,MOD,D`
**原子执行**（`_nn_lcg_prefix`：三连区间 `[p1,j]` 内无 LAB、无跳转，且全函数无
跳转落进 `(p1,j]`，避免中间量 t1/t2 的 nn/ub 标注张冠李戴）；循环守卫等
`[h,p1]` 段的有条件跳转不影响不变式。入口非负、≤D-1、ndef==2、溢出闸、
CFG 入口闸全部保留 —— 负初值 LCG（t=-7）仍走有符号链。

## 实现

- `bootstrap/qlmc/qlmc.qma` 新增 `_nn_lcg_prefix(ir,h,e,j,p1,p2)`，替换
  `_nn_lcg_induct` 里的 `_nn_loop_shape` 闸；其余判据原样保留。
- 顺带修复了子代理遗留的调用点参数个数 bug（少传 `e`，会导致编译失败）。
- 新增差分夹具 `tests/s_lcg_branch_sound.qma`（8 组：负初值、负初值+分支、
  近溢出、K=0、条件跳过更新、嵌套循环改 v、D=2 等），全部与 stage-0 一致。

## 收益（本机 min-of-7，与 v4.126 基线 ELF 对比）

| 基准 | 基线 | 本版 | 比值 |
|---|---|---|---|
| b26_maxsub | 362.89ms | **240.71ms** | **0.663（−34%）** |
| b83_lcg_random | 128.09ms | 88.53ms | 0.691（−31%，v4.130 收益保持） |
| b65_random_walk | 27.68ms | 21.01ms | **0.759（−24%）** |
| b18_insertion | 8946.97ms | 8893.67ms | 0.994（噪声内） |

irdump 确认 b65/b26 的两条 `DIVC` b 槽由 `OP_MOD(7)` 变为 `SUB_MODU(107)`，
反汇编走单条 `and` / 无符号魔数链，零符号修正。

## 验证

| 项 | 结果 |
|---|---|
| soundness 夹具 `s_unsigned_mod`（第7项负 LCG=496）、`s_nonneg_sound`、`s25_divmod`、`s_lcg_branch_sound`（8 组） | 逐字节一致（含额外的自定义"分支跳过更新"压力测试） |
| 全量 76 基准新旧 qlmc 各编 ELF 运行 | **76/76 校验和一致，零 MISMATCH** |
| `python3 tests/qlmc_test.py --qlmc build/qlmc_v4131.exe` | **PASS=134 FAIL=0** |
| `python3 tests/bootstrap_test.py --strict` | **PASS**：stage-2 与 stage-1 逐字节等价（42/42 组）、stage-2 == stage-3 不动点成立 |
| `python3 tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- 归纳仍只认"v 全函数恰好写两次 + 入口可证非负且 ≤D-1"的最窄形状；
  多次更新（如 v 在循环内被两处 LCG 改写）依然拒绝，保持保守。
- `_nn_lcg_prefix` 只放行三连原子段；跨三连的跳转一律拒绝。
## CI 实测（run 45361314099，推送后权威口径）

Windows / Ubuntu job success（macOS job 为已知 b75 计时抖动，无 Quelmara 列），
76/76 校验和零 MISMATCH。C 参照中位数本轮又上浮 1.46×（同 CPU 的 Ubuntu），
绝对时间不可跨 run 比；只看同 run 内 qlm/C 比值：

| 基准 | 平台 | v4.130 | v4.131 | 变化 |
|---|---|---|---|---|
| **b26_maxsub** | Ubuntu | 1.73× | **0.92×** | **反超 C**（qlm 44.64 vs C 48.44ms，五轮稳定） |
| **b26_maxsub** | Windows | 1.95× | **1.02×** | 基本持平 C |
| b65_random_walk | Ubuntu | 1.91× | **1.28×** | qlm 4.26ms，五轮稳定 |
| b65_random_walk | Windows | 1.93× | **1.22×** | — |
| b83_lcg_random | Ubuntu | 1.01× | 1.13× | 噪声（runner 负载上浮，本机 A/B 保持 0.69） |
| >1.5× 项数 | Windows | 45 | **41** | 4 项跨过阈值 |
| >1.5× 项数 | Ubuntu | 32 | 34 | 与 C 侧整体变慢的噪声同向 |

本机 A/B（同负载）b26 0.663 / b65 0.759 / b83 0.691，与 CI 同 run 比值方向一致。
**这是继 b83 之后第二个反超/持平 C 的计算密集基准（b26）。**
