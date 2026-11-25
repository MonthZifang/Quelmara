# v4.137 — 零比较惯用法扩展：`_cmp_imm0` 也改发 `test r,r`（全部 76 项产物变小）

- 日期：2026-11-25
- 任务：v4.136 只把 `_cmp_imm`（`OP_CMPI` / `OP_JCMPI` 共用）的零比较改成了
  `test r,r`，但**另一个零比较发射点 `_cmp_imm0`** 仍发 `cmp r64,0`。
  `_cmp_imm0` 覆盖 `OP_NOT` / `OP_NZ` / `OP_JZ` / `OP_JNZ` 以及
  `__print_bool` 运行库，是基准与编译器自身里最高频的零比较路径
  （v4.136 产物里仍残留 129 处 `cmp r,0`）。
- 影响面：编译器（stage-1 发射器 `_cmp_imm0`，不动 IR / pass / vloc）

## 等价性（与 v4.136 同一论证）

对任意 64 位 `r`：`cmp r,0`（算 `r-0`）与 `test r,r`（算 `r&r`）产生的
ZF/SF/PF 完全相同，CF/OF 都为 0；AF 未定义但**没有任何 Jcc/setcc/cmov 读 AF**。
两者都带 REX.W（64 位），逐位等价。

## 改动

`_cmp_imm0(code, reg)` 由手写 `REX.W 83 /7 00`（4 字节）改为调用
`_test_rr(code, reg, reg)`（`REX.W 85 /r`，3 字节）。

## 收益

| 项 | 结果 |
|---|---|
| 全量 76 基准 ELF 体积 | **76/76 全部变小，合计 −130 字节**（v4.136 亦为 −34B，本版再叠加） |
| 最大单项 | b73_graph_bfs −6、b22_knapsack −4、b28_matrix −4、b23_lcs −3 |
| 本机 min-of-7 计时 | b44 0.9804、b28 0.9982、b23 0.9944、b22 1.0006、b78 1.0027、b73 1.0085（**噪声内**） |

诚实结论：体积收益确定（每处零比较 −1 字节，76 项全变小），热循环占比低，
**本机测不出速度收益**；保留理由是语义等价、产物统一变小、零风险。

## 验证

| 项 | 结果 |
|---|---|
| 新旧 qlmc 编全量 76 基准到 ELF 并运行 | **76/76 校验和一致**（b37_swap 一次 wine IPC 抖动，重编后一致；b37 与 C 同为 2264） |
| `python3 tests/qlmc_test.py --qlmc build/qlmc_v4137.exe` | **PASS=136 FAIL=0** |
| `python3 tests/bootstrap_test.py --strict` | **PASS**：stage-2 与 stage-1 逐字节等价（42/42 组）、stage-2 == stage-3 不动点成立 |
| `python3 tools/dev/check_docs.py` | PASS |
| 反汇编抽查 b44 | `cmp r,0` 2→**0** 处，ELF 5379→5377 |

## 已知边界 / 遗留

- 至此 `cmp r,0` 的两个发射点（`_cmp_imm` / `_cmp_imm0`）都已统一为 `test r,r`。
- 本机计时无显著收益；CI 权威基准待推送后实测（预计同为体积收益为主）。
