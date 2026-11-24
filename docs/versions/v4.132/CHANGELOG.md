# v4.132 — 计数循环归纳变量非负/上界证明（b66_integrate −16%）

- 日期：2026-11-24
- 任务：v4.130/v4.131 的 LCG 归纳只覆盖 `(v*C+K)%D` 形态；普通计数循环
  `while i<hi { ... i=i+step }` 的归纳变量 i 仍未证明非负，循环内 `i%const`
  继续走 13 条有符号符号修正链。本版仿 stage-0 `analyze_ranges` 实现窄而
  健全的计数循环归纳证明，解锁 b66_integrate 等基准。
- 影响面：编译器（stage-1 优化 pass，不动调用约定 / IR 语义）

## 判据与 soundness

`_nn_loop_induct` 只在**全部**满足时给 ivar 标 nn=1 / ub=hi-1+step：

1. 回边指向循环头 h，守卫在 h 附近且是严格 `<` 形态
   （JCMPI cc=0x8C/JL 进体或 0x8D/JGE 退出；**拒绝 `<=` 的 0x8E/0x8F**，
   因为 `ub=hi-1+step` 对 `<=` 会低估上界 → 派生值溢出误判）；
2. ivar 全函数恰好写两次：入口 `CONST lo`（0≤lo<hi）+ 循环内唯一
   `ivar=ivar+step`（step>0，BINI ADD imm 或常量 ADD）；
3. hi 是常量或循环前唯一 CONST 定义且循环内不改；
4. 溢出闸 `hi-1+step < 2^62`（保证派生 i*i 等不回绕）；
5. 回边唯一、入口定义不被任何回边区间覆盖、跳转不落进 `(guard,step]`、
   ivar 未被取址（`_nn_escaped`）。

由于 ivar 恒在 `[0,hi-1+step]`，且循环内**单定义**派生值的上界可递归推出，
`_nn_loop_derive_all` 在循环 `[h,e]` 内用 CONST/MOV/ADD/MUL/BINI(ADD|MUL|AND|
shift) 推上界（深度 ≤8、乘法带 2^62 溢出闸、未知形态一律放弃），让 b66 的
`i*i+3*i+5` 也能标记成无符号。多写/负初值/负 step/hi 循环内变/取址/超大 hi/
`<=` 守卫 —— 全部拒绝，保持截断有符号语义。

## 收益（本机 min-of-7）

| 基准 | v4.131 | v4.132 | 比值 |
|---|---|---|---|
| **b66_integrate** | 22.75ms | **19.11ms** | **0.840（−16%）** |

irdump：b66 的第一条 `%1000003` DIVC b 槽由 `OP_MOD(7)` → `SUB_MODU(107)`
（走无符号魔数链）；第二条是累加器 `acc`（多定义），保守保持有符号。
b76_io_line / b23_lcs 的取模操作数来自 vec load，非归纳变量派生，未触发 ——
没有强行扩大判据，避免 soundness 风险。

## 验证

| 项 | 结果 |
|---|---|
| soundness 夹具 `s_loop_induct_sound`（9 组：正例/负初值/负 step/多定义/取址/hi 变/超大 hi/`<=` 守卫/step=3）、`s_unsigned_mod`（负 LCG=496）、`s_lcg_branch_sound`、`s_nonneg_sound`、`s25_divmod` | 逐字节一致 |
| 全量 76 基准新旧 qlmc 各编 ELF 运行 | **76/76 校验和一致，零 MISMATCH** |
| `python3 tests/qlmc_test.py --qlmc build/qlmc_v4132.exe` | **PASS=136 FAIL=0**（新增 loop_induct_sound 用例） |
| `python3 tests/bootstrap_test.py --strict` | **PASS**：stage-2 与 stage-1 逐字节等价（42/42 组）、stage-2 == stage-3 不动点成立 |
| `python3 tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- 只认严格 `<` 守卫 + 入口 CONST + 唯一 step 的最窄形状；`<=`、负初值、
  多定义、取址、hi 循环内变化一律拒绝。
- 派生值传播只覆盖纯运算且深度 ≤8；带分支/调用/访存的派生值放弃，保守留慢路。
- CI 权威基准待推送后实测；本机数字只作粗判，不代表 CI 口径。
