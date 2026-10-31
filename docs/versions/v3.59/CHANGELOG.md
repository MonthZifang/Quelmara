# v3.59 — AES-NI / PCLMULQDQ / SSSE3 / SSE 移位；覆盖率 60 → 63

- 日期：2026-11-01
- 任务：用户要求"继续"；补齐 SIMD 轨道（v3.58 只做了基础四件）
- 影响面：`bootstrap/qlmc/qlmc.qma`（14 个内建 + 2 个 IR 节点 +
  2 个编码函数 + 1 个运行时例程 + `_lower_simd_extra`）、
  `tests/t203_qlmc_aes.qma`、`tests/qlmc_test.py`、
  `tools/dev/qlmc_coverage.py`（`BASELINE` 60 → 63）、`HANDOFF.md`（新增）
- 覆盖率：**60 → 63**（`std/aes` + `std/tls13` + 另一个卡在同一处的模块）
- 回归：PASS=370 FAIL=0 SKIP=0；qlmc 差分 82 → **84**

## 14 个新内建

| 内建 | 编码 | 类型 |
|---|---|---|
| `pand` | `66 0F DB /r` | 两字节 |
| `por` | `66 0F EB /r` | 两字节 |
| `pshufb` | `66 0F 38 00 /r` | 三字节（SSSE3） |
| `aesenc` | `66 0F 38 DC /r` | 三字节（AES-NI） |
| `aesenclast` | `66 0F 38 DD /r` | 三字节（AES-NI） |
| `pclmulqdq` | `66 0F 3A 44 /r ib` | 三字节 + imm8 |
| `psrlw` | `66 0F 71 /2 ib` | 立即数移位 |
| `psllw` | `66 0F 71 /6 ib` | 立即数移位 |
| `psrlq` | `66 0F 73 /2 ib` | 立即数移位 |
| `psllq` | `66 0F 73 /6 ib` | 立即数移位 |
| `pslldq` | `66 0F 73 /7 ib` | 立即数移位 |
| `psrldq` | `66 0F 73 /3 ib` | 立即数移位 |
| `cpu_aes` | CPUID.1:ECX[25] | 特征探测 |
| `cpu_pclmul` | CPUID.1:ECX[1] | 特征探测 |

## 两种新编码形态

### 三字节 opcode map（`_sse_rr3`）

AES-NI / PCLMULQDQ / SSSE3 都在 `0F 38` 或 `0F 3A` map 里：

```
66 REX 0F 38 opc /r          无 imm8（aesenc / aesenclast / pshufb）
66 REX 0F 3A opc /r ib       带 imm8（pclmulqdq）
```

**没有扩展 `_sse_rr`**：那个函数在 f64 热路径上，加两个分支 + 一个参数
会让它更臃肿；而且三字节 map 的指令全是 WIG（忽略 REX.W），语义不同。

### 立即数移位（`_sse_shift_imm`）

```
66 REX 0F 71 /group ib
66 REX 0F 73 /group ib
```

**这类指令没有 reg 字段** —— `/group` 是 modrm 的 reg 位当操作码扩展用，
唯一的 xmm 操作数在 `rm` 位。所以不能复用 `_sse_rr3`（那是 reg,rm 形态）。

`group`：`psrlw`=2、`psllw`=6（配 `0F 71`）；
`psrlq`=2、`psllq`=6、`pslldq`=7、`psrldq`=3（配 `0F 73`）。

## 两个新 IR 节点

```
OP_XMMRI = 84   三字节 map + imm8
                imm = (pf<<32) | (imm8<<24) | (opc<<16) | (dst<<8) | src
OP_XMMSH = 85   立即数移位
                imm = (opc<<24) | (imm8<<16) | (group<<8) | slot
```

**为什么 `OP_XMMRI` 要单独一个节点**：`OP_XMMRR` 的 `imm` 已经塞了 5 个
字段（pf/opc/dst/src），再加 imm8 就要跨 32 位。分开更清楚，也避免
`pf << 32` 这种依赖（虽然 Quelmara 的 int 是 64 位、放得下）。

## CPUID 特征探测

`cpu_aes()` / `cpu_pclmul()` 都查 **CPUID leaf 1 的 ECX**，所以一个运行时
例程 `RT_CPUID1ECX = 29` 够两个内建用。

**必须保存 RBX**：`cpuid` 指令会写 RBX，而 RBX 是 Win64 的**非易失**
寄存器 —— 被调方必须保存。不保存的话调用方的 RBX（qlmc 的变量寄存器）
会被悄悄改掉，表现为"调一次 `cpu_aes()` 之后某个变量变成随机值"，极难定位。

**绝不谎报 1**：库层靠这个值决定走 AES-NI 快路径还是 T-table 软件实现，
谎报会让不支持 AES-NI 的 CPU 直接非法指令崩溃。

## 踩到的坑：帧槽 416 上限（第 5 次）

14 个新内建的分支直接塞进 `_lower_builtin`，把它从 416 槽顶到 **417** ——
自举 stage-2 立刻报"需要 417 个槽（已用 416，本次要 1）"。

修法：抽出 `_lower_simd_extra` 独立函数，`_lower_builtin` 里只留三行委托。

**这个陷阱本项目已经踩过 5 次**（v3.42 / v3.45 / v3.49 / v3.55 / v3.59），
规律是：`_lower_builtin`、`_emit_ir`、`build_rdata`、`main` 这几个大函数
**贴着上限**，往里加任何逻辑前都要先抽函数。

## 测试

`tests/t203_qlmc_aes.qma`，加进 `tests/qlmc_test.py` 的 `CASES` 作为
**差分用例**（`s36_aes`），18 行输出与 stage-0 逐字节一致（208 字节）。

**每条指令都做已知答案的数值验证**，不是"能跑就算过"：

| 判据 | 期望 | 抓什么 |
|---|---|---|
| `pand=15` | `255 & 15` | 两字节 map |
| `por=255` | `255 \| 15` | 两字节 map |
| `pshufb=255` | 掩码全 0 → 全取 byte0 | **map 写成 `0F 3A` 会变另一条指令** |
| `psrlw0=255` / `psrlw1=0` | 16 位字右移 8 | `/group` 位写错就变另一条移位 |
| `pslldq0=0` / `pslldq1=15` | 左移 1 字节 | 字节移位方向 |
| `psrldq0=15` | 右移 2 字节 | 同上 |
| `psllq0=0` / `psllw0=0` | 64 位 / 16 位左移 | group 号 |
| `consistent=1` | `cpu_aes == cpu_pclmul` | CPUID 位取错 |
| `aesenc_changed=1` | 输出 ≠ 输入 | AES-NI 编码 |

**`aesenc` 不写死期望值** —— 那是 Intel 的 S-box 结果，写死等于把实现
细节固化进测试。只验"跑完了、输出不是全 0、也不是输入原样"。

**一个自我纠错**：`psrlw` 的注释我第一版写反了（以为 `psrlw0=0`），
实测是 `psrlw0=255` —— **实现是对的、注释错了**。已改正并在注释里标明。

## 顺带：新增 `HANDOFF.md`

交接文档，写清了：
- 当前状态（已提交 60/70、工作区 63/70）
- 立刻要做的收尾步骤
- 剩余 7 个模块的缺口与难度
- **五个反复出现的坑**（帧槽 / 编号撞车 / 静默错编 / `_ir_emit` 的 a/b / 诊断粒度）
- 工作流约定与推送方式
- 当前基线数字

## 自举

30/30 组等价 + 不动点成立。stage-2 产物 658432 B，仍在 `ARENA_CAP = 4 MB`
余量内。
