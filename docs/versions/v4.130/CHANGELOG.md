# v4.130 — LCG 循环归纳非负证明：解锁无符号 div/mod 快路径

- 日期：2026-11-24
- 任务：在 qlmc 实现窄而健全的 LCG 循环归纳非负证明，让 `v=(v*C+K)%D` 的循环携带变量
  被证明落在 `[0,D-1]`，从而把 `%100` 等常数 div/mod 从全符号魔数链切到无符号快路径。
  只改编译器，不动基准源码。
- 影响面：编译器（stage-1 `bootstrap/qlmc/qlmc.qma` 的 IR 非负分析 + DIVC 标记 + 发射器）

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增 `_nn_lcg_induct`：`_nn_propagate` 之后跑 LCG 归纳，四条前提（入口非负且 ≤D-1 / 体内单定义且形状为 `(v*C+K)%D` / C>0·K≥0·D≥2 / `(D-1)*C+K<2^62`）全满足才写 `nn[v]=1,ub[v]=D-1`；顺带证明 `t1=v*C`、`t2=t1+K` 非负。CFG 闸保证入口定义唯一、不在内层/外层循环被重写、不被跳过 |
| `bootstrap/qlmc/qlmc.qma` | `_opt_divc_unsigned` 的标记循环扩展到非 2 的幂（`imm<2^31`），只标已证非负的 DIVC；2 的幂判据原样保留 |
| `bootstrap/qlmc/qlmc.qma` | 新增 `_divc_umagic_ok` / `_divc_magic` / `_emit_divc_umagic`；`_emit_divc` 对 `SUB_MODU`/`SUB_DIVU` 的非幂除数走无符号魔数链（无符号修正） |
| `VERSION`、`tools/stage0/qlm_cli.py` | 版本号 → 4.130.0（仅版本号，stage-0 无逻辑改动） |

新增逻辑全部独立成 fn，未向 `_emit_ir` 等贴 416 槽上限的大函数加局部变量。

## 判据（soundness 红线）

只标记"被除数已证非负"的 DIVC，绝不碰负数输入。负初值 LCG（`t=-7; t=(t*3+1)%16`）
因入口 `CONST imm<0` 不满足前提①，继续走全符号链。所有新函数一次只放行已证形状，
任一条前提失败即完全不标。

## 验证（本机 Linux x86-64，wine 跑 PE）

| 命令 | 结果 |
|---|---|
| `python3 tools/stage0/qlm_cli.py build bootstrap/qlmc/qlmc.qma --target win -o build/qlmc_lcg.exe` | PASS（5,479,936 字节） |
| 差分夹具 `s_unsigned_mod` / `s_nonneg_sound` / `s25_divmod` | **3/3 stage-0 与新 qlmc 逐字节一致**；第 7 项负 LCG 保持 **496**（v4.123 的 bug 未复现），`s25_divmod` 负数用例 156 行全同 |
| 新旧 qlmc 编全量 76 基准到 ELF 并运行校验和 | **76/76 一致** |
| `python3 tests/qlmc_test.py --qlmc build/qlmc_lcg.exe` | **PASS=134 FAIL=0** |
| `python3 tests/bootstrap_test.py --strict` | **PASS**：stage-2 与 stage-1 逐字节一致（42/42 组）、错误路径退 2、stage-2 == stage-3 不动点成立 |
| `python3 tools/dev/check_docs.py` | PASS |

## 收益（本机，交替 7 轮取 min）

| 基准 | old | new | 比值 new/old |
|---|---|---|---|
| b83_lcg_random | 128.15 ms | 88.43 ms | **0.690（−31%）** |
| b65_random_walk | 27.94 ms | 27.93 ms | 0.9998（中性） |
| b26_maxsub | 360.92 ms | 362.22 ms | 1.0036（中性） |

b65/b26 的循环体内有额外的条件分支 LAB，`_nn_loop_shape` 保守拒绝，归纳不生效——
无回退即可，符合窄而健全的目标。

IR/反汇编证据：新 qlmc 编 b83 的热循环里两条 `DIVC` 的 b 槽都由 `OP_MOD(7)`
变成 `SUB_MODU(107)`；反汇编热循环从基线的 29 条（含 `cqto`/`sar`/`xor`/`sub`
等符号修正）降到 19 条：`%2^31` 为单条 `and $0x7fffffff`，`%100` 为
`mul` + `shr $0x6` + `imul $0x64` + `sub`（无符号魔数链，零符号修正）。

## 已知边界 / 遗留

- 归纳只认最窄的 LCG 形状：`BINI v,MUL,C` + `BINI t,ADD,K` + `DIVC v,...,MOD,D`，
  且要求入口 `CONST ≥0`（或已有带上界证明）并落在 `[0,D-1]`；带内部 LAB / 分叉的
  循环一律放弃（b65/b26 因此中性）。
- 无符号魔数只用于 `imm < 2^31`（qlmc 魔数公式的定义域，已有 `s25_divmod` 钉死）；
  2 的幂路径维持原判据不变。
- 性能为本机 A/B，不代表 CI；CI 权威口径待推送后由用户统一跑。
