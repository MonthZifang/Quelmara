# v4.126 — OP_BINI 发射器级 peephole：`and r,0xffff` → `movzx`；`shl r,3` → `lea`

- 日期：2026-11-23
- 任务：实现并验证一个低风险发射器级优化，目标 b34_bitops（Windows CI 上 qlm ~18.7ms vs C ~4.1ms）。
- 影响面：编译器（stage-1 发射器，不改 IR / 优化 pass / vloc 分配，不动点安全）

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增独立函数 `_emit_bini_peephole`（~12242 行），在 `OP_BINI` 分支仅当源 vreg（`aloc>0`）与目的 vreg（`dloc>0`）都在寄存器时：`and r,0xffff` 发 `movzx r32,r16`（`REX 0F B7 /r`），`shl r,3` 发 `lea r,[src*8]`（`REX.W 8D /r` + SIB scale=8/base=none + disp32=0）；其它情形原样返回走旧路径。不新增 `_emit_ir` 局部变量（帧上限 416，§4.1）。 |
| `VERSION`、`tools/stage0/qlm_cli.py` | 4.125.0 → 4.126.0（版本号同源，过 `check_docs.py`） |
| `docs/06-status.md` | §7 末尾追加 v4.126 本地验证更新（不代表 CI 数据） |
| `docs/versions/v4.126/CHANGELOG.md` | 本文件 |

编码已用 gcc+objdump 交叉核对：`movzx %r9w,%r9d = 45 0F B7 C9`、`movzx %ax,%r10d = 44 0F B7 D0`、`lea (,%rax,8),%rax = 48 8D 04 C5 00 00 00 00`、`lea (,%r9,8),%r10 = 4E 8D 14 CD 00 00 00 00`。SIB.index 高位用 REX.X（bit1），movzx 的 rm 高位用 REX.B（bit0），均已核对含 R12–R15 / R8–R11 的编码。

## 验证

| 命令 | 结果 |
|---|---|
| `gcc -c enc_check.s && objdump -d enc_check.o`（两条编码） | 字节与实现逐项一致 |
| `python3 tools/stage0/qlm_cli.py build bootstrap/qlmc/qlmc.qma --target win -o build/qlmc_new.exe` | EXIT=0，5401600 字节，重编 898057 ms |
| 新旧 qlmc 编 b34/b35/b1/b78/b83/b74/b81 到 ELF 并运行 | 7/7 校验和一致；b34 ELF 4846→4844 字节（−2），热循环变为 `lea 0x0(,%r14,8),%r8` + `movzwl %r9w,%r9d` |
| 全量 76 基准（新旧 qlmc 各编 ELF、运行比对校验和） | **76/76 校验和一致，零 MISMATCH**；11 项 ELF 字节变化（`b34_bitops −2`，其余 +1），其余 65 项逐字节不变 |
| 差分夹具：`tests/s_unsigned_mod.qma`、`tests/selfhost/s25_divmod.qma`、`tests/selfhost/s15_bitops.qma` | 3/3 stage-0 vs 新 qlmc 输出逐字节相同、rc=0 |
| `python3 tests/qlmc_test.py --qlmc build/qlmc_new.exe` | **PASS=134 FAIL=0**（含 s32_thread 本轮通过；并行确定性 -j1/-j4 一致） |
| b34 本地交替 9 轮取最小（新旧 ELF，进程内 ns） | min old=101093999ns，new=101467368ns，比值 **1.0037（+0.37%）**；首轮 101210084/101179497，比值 0.9997（−0.03%）——本机在噪声范围内，无 >5% 回退 |

## 收益与已知边界

- b34 热循环的 2 条冗余指令确实被替换（`shl r,3` → `lea`、`and $0xffff` → `movzx`，ELF −2 字节）；但本机（Linux x86-64，非 Windows CI）进程内计时比值约 0.9997–1.0037，**未观察到显著收益**，属噪声范围。保留理由是语义等价、零校验和偏差、低风险；真实收益需以 Windows CI 数据为准。
- 只处理 `imm==0xFFFF` 的 `OP_AND` 与 `imm==3` 的 `OP_SHL`，且源/目的均须在寄存器；栈槽情形与其它立即数、子操作码完全走旧路径，行为不变。
- `movzx r32,r16` 写 32 位自动清高 32 位，与 `and r64,0xffff` 的 64 位结果在 [0,65535] 内等价；`lea r,[src*8]` 在 mod 2^64 下与 `shl r,3` 等价。
- 本机计时波动较大（早期轮次出现 0.80–1.22 的异常比值，系统负载所致），结论以最小值为准，不代表 CI 数据。
