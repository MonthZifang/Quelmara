# v4.138 — 删除紧邻函数尾声的冗余 `jmp`（104 处、−520B）

- 日期：2026-11-25
- 任务：`OP_RET` 无条件发 `jmp <尾声标签>`。但当 RET 是函数体的**最后一条**
  实际指令时，紧跟着的就是尾声（`_lower_fn` 在最后 `_ir_emit(OP_LAB,...,ep)`），
  这条 `jmp` 的目标就是下一条要发射的指令 —— 完全多余。
- 影响面：编译器（stage-1 发射器 `OP_RET` 分支，不动 IR / pass / 寄存器分配）

## 等价性与安全性

- `OP_LAB` / `OP_NOP` **不发射任何字节**（`OP_LAB` 只 `_setlab` 记录位置），
  所以"RET 后有若干 NOP/LAB 且出现尾声标签 `ep`"意味着 `jmp ep` 的目标
  **恰好等于**顺序执行的下一条指令。
- 跳过去与直接顺序执行逐位相同：只会多一次 5 字节 `jmp` 的取指与分支。
- RET 终止控制流，后面不存在"其它代码跳进这条 jmp 中间"的情况；
  抬头检查只扫描 `i+1` 起的 NOP/LAB，遇到任何非 NOP/LAB 就停，绝不越界。
- 其余 RET（函数中间的多 return）照旧发 `jmp`。

## 实现

`_emit_ir` 的 `OP_RET` 分支：先求返回值到 RAX，再向前看 `i+1` 起跳过
`OP_NOP`/`OP_LAB`；若期间出现 `imm == C_EP` 的 `OP_LAB`，则直接 `return`
（不发 `jmp`）；否则原样 `_jmp` + `_addfix(...C_EP...)`。

## 收益

| 项 | 结果 |
|---|---|
| 受影响 ELF | **74/76**（b1_int、b78 等无尾部 RET 的除外） |
| 删除的冗余 jmp | **104 处** |
| 总体积 | **−520 字节**（v4.136 −34B、v4.137 −130B，本版再叠加） |
| 反汇编抽查 b10_ackermann | 冗余 jmp 2→**0**，校验和不变（19） |

## 验证

| 项 | 结果 |
|---|---|
| 新旧 qlmc 编全量 76 基准到 ELF 并运行 | **76/76 校验和一致** |
| `python3 tests/qlmc_test.py --qlmc build/qlmc_v4138.exe` | **PASS=136 FAIL=0**（首次 s26_alias 是 stage-0 侧 `Exec format error` 抖动，重跑全过） |
| `python3 tests/bootstrap_test.py --strict` | **PASS**：stage-2 与 stage-1 逐字节等价（42/42 组）、stage-2 == stage-3 不动点成立 |
| `python3 tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- 只处理"RET 之后到尾声之间只有 NOP/LAB"的情形；中间有实际指令的 RET
  仍发 jmp（正确性优先）。
- 本机未做专门计时（省一条 `jmp` 是确定的指令数收益，属体积+取指优化）；
  CI 权威基准待推送后实测。

## CI 实测（run 45619094861，推送后权威口径）

三个 job 全绿（含 macOS），**两平台 76/76 跨语言校验和全部一致、零 mismatch**。

| 平台 | 几何平均 qlm/C | >1.5× 项数 |
|---|---|---|
| Windows | 1.973 | 41/76 |
| Ubuntu | 1.538 | 36/76 |

本版是**指令数与体积优化**（104 处冗余 jmp、−520 字节）；跨 run 的几何平均
差异落在 runner 噪声与 CPU 差异范围内，**不声称比值收益**。正确性由
76/76 校验和 + 本机 `qlmc_test` 136/0 + `bootstrap_test --strict` 不动点共同保证。
