# v1.33 — GHASH 硬件化（PCLMULQDQ）：GCM 36 → 19 ms，累计 72×

- 日期：2026-10-22
- 任务：性能专项收尾——GCM 里最后一块（GHASH 占端到端 95%）
- 影响面：编译器（12 条 SSE 指令 + CPUID 探测）、标准库（aes 硬件 GHASH）、测试、文档

## 做法：先在 Python 里算对，再写进后端

GHASH 的 128 位乘法是 GF(2^128) 上的进位无乘法，且 GCM 用的是**位反射**表示
（byte0 的 MSB 是 x^0）。直接在汇编里试错代价太高，所以先写了
`build/_pclmul_proto.py`：把 pshufb / pand / por / psllq / psrlq / pslldq /
psrldq / pclmulqdq 全部按 16 字节数组模拟，与逐位参考实现对拍。

- 第一版参考实现写错了（用了小端整数当反射值），SSE 版反而是对的；
  修正参考实现后 **NIST 向量 + 200 组随机输入全部一致**。
- 有了这个原型，翻译成 QuIR 就是机械劳动，第一次运行就只剩一处操作数顺序错。

## 关键数学

把 xmm 里的 16 字节看成小端整数 V，则 GCM 的多项式系数整数 = `bitrev8each(V)`
（只需**每字节内位反序**，不需要整段字节反序——这一步省掉一半工作）。

序列：
1. `A' = bitrev8each(A)`，`H' = bitrev8each(H)`（H' 每次调用只算一次，常驻槽 3）
2. 4 × `pclmulqdq`（0x00/0x11/0x10/0x01）拼成 256 位 `(hi:lo)`
3. 归约 `R = lo ^ hi ^ hi·x ^ hi·x² ^ hi·x⁷`，溢出位（≤7 位）再折叠一次
4. `bitrev8each(R)` 写回

`bitrev8each` = 半字节查表（`pshufb`）+ 高低半字节交换，7 条指令。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 编码器新增 `movdqa/pand/por/pshufb/pclmulqdq/psrlw/psllw/psrlq/psllq/pslldq/psrldq`（含立即数组形式）+ `cpu_pclmul()`（CPUID.1:ECX[1]） |
| `tools/stage0/qlm_opt.py` | 新指令登记；**特别处理**：SSE 族没有 vreg 操作数，不能沿用 `xmm_*` 那条"正整数当 vreg"的规则（立即数 0-255 会被误当成 vreg 号） |
| `std/aes.qma` | 新增 `_rev0` / `_gmul_ni` / `_ghash_ni`；`ghash` 按 `cpu_pclmul()` 分流，4-bit 表与逐位算法作为降级保留 |
| `tests/t79_sse.qma` | **新增**：12 条 SSE 指令逐条对拍（含 pclmul 的 0x00/0x10/0x11 三种选取） |
| `tests/run_win_tests.py` | 注册 t79（主回归 141 → 142） |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.32.0 → **1.33.0** |
| `docs/02-language.md` | 内建表补 `cpu_pclmul` / SSE 族 |
| `docs/06-status.md` | GCM 19 ms；GHASH 17 ms；回归 142 |
| `docs/07-gaps.md` | GHASH PCLMUL 翻绿；新增 §7.5 优化器吃指令的问题 |

## 踩到的两个坑

1. **`pshufb` 的操作数顺序**：语义是 `dest[i] = dest[ctrl[i]]`——**表必须在目标槽**、
   待反转的半字节在源槽。第一版把两者写反，结果全错。
   t79 只测了指令本身（用反序掩码当控制），测不出"用法错"，是 `_ghash_ab` 的
   单块对拍（表实现 vs 硬件实现）抓到的。
2. **`xmm_pxor(7,7)` 清零被优化器当死代码删掉**：单写探针是对的，放进
   `_gmul_ni` 就错。xmm 指令没有 vreg 结果，`xmm_load/store` 因为读写内存才侥幸
   留下。已退回"内存零块 + load"的清零方式，并登记 §7.5。

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run bench/aes_bench.qma --target win` | **19 ms / MiB**（v1.32 36 ms，**1.9×**；相对 v1.28 的 1369 ms 是 **72×**） |
| `build/_ghash_ab.qma`（单块对拍，临时件） | 表实现与硬件实现逐字节一致（NIST 向量 `5e2ec746…`） |
| `python tests/run_win_tests.py` | **PASS=142 FAIL=0 SKIP=1** |
| `python tools/stage0/qlm_cli.py run tests/t48_aes.qma --target win` | ok（GCM tag `ab6e47d4…` 正确，说明 GHASH 与 NIST 一致） |
| `python tools/stage0/qlm_cli.py run tests/t73_ghash.qma --target win` | ok（4 KiB GCM 往返） |
| `python tools/stage0/qlm_cli.py run tests/t79_sse.qma --target win` | ok（12 条指令逐条） |
| `python tools/dev/check_*.py` | 三禁 PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.33.0` |

## 已知边界 / 遗留

- **归约不是常数版**：用的是"移位折叠"（3 次移位 + 溢出折叠），比教科书里
  `0xC2` 常数 + 3 次 pclmul 的写法多几条指令。已经够用（GHASH 17 ms/MiB），
  再压这点要重写归约，收益小于风险。
- **没有 4 路聚合**：GHASH 是串行依赖（每块依赖上一块），4 路聚合能再快 2–3×，
  但要重排 CTR/GHASH 交织，收益已不大。
- **AAD 与非整块尾仍走软件路径**：`_ghash_ni` 只处理 16 字节对齐的块序列。
- **`cpu_pclmul()` 只在 x86_64 后端**（与 `cpu_aes` 一致）。
- **§7.5 未修**：优化器会删掉"没有 vreg 结果"的 xmm 指令，这是编译器级隐患，
  目前只有清零那一处踩到。
