# v1.31 — AES-NI：AES 核心 31×，GCM 端到端 1.37×

- 日期：2026-10-22
- 任务：继续性能优化，目标是 benchmark 里最差的那一行（AES-128-GCM 171 ms/MiB）
- 影响面：编译器（6 条 AES 指令 + CPUID 探测 + 两个 xmm 编码 bug）、标准库（aes 快路径）、测试、文档

## 为什么先做它

`06-status.md` 里 GCM 是 6.1 MB/s——比同表里任何一项都差两个数量级，而它正好是
TLS 数据面的必经之路（握手完成之后每个 record 都要过 GCM）。`07-gaps.md` §5 把
AES-NI 列为"需编码器扩展"，一直没做。

先确认硬件：本机 Xeon E5-2666 v3（Haswell 代）**有 AES-NI**（`cpu_aes()` 实测返回 1）。
文档原来只记了"无 SHA-NI、无 AVX2"，漏了 AES-NI 这一条——这行数字就是被这个漏记拖着的。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 编码器新增 `aesenc` / `aesenclast` / `aesdec` / `aesdeclast` / `aesimc` / `aeskeygenassist`（66 0F 38 DC..DF / 66 0F 3A DF）；新增 `cpu_aes()` 内建（CPUID.1:ECX[25]）及其 IR 发射；**修两个 xmm 编码 bug**（见下） |
| `tools/stage0/qlm_opt.py` | 新指令登记到 `vreg_mentions` / 不可重排集合 / `subst` |
| `std/aes.qma` | 新增 `_aes128_encrypt_block_ni`（单块硬件加密）与 `_gcm_ctr_block_ni`（加密+异或+落盘全在 xmm）；`_ctr_xor` 按 `cpu_aes()` 分流，探测提到循环外 |
| `tests/t48_aes.qma` | 新增两条断言：T-table 路径与 AES-NI 路径都必须对上 FIPS-197 C.1 |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.30.0 → **1.31.0** |
| `docs/02-language.md` | 内建表补 `cpu_aes` / `xmm_load` / `xmm_store` / `aes*` |
| `docs/06-status.md` | GCM 125 ms；新增 CTR 段 2 ms 与 GHASH 段 123 ms 两行 |
| `docs/07-gaps.md` | AES-NI 翻绿；GHASH PCLMUL 提为下一项（附分解数字）；新增 §7.4 误编译记录 |

## 实现要点

- **xmm 槽协议**：0 = 状态/计数器，1 = 轮密钥，2 = 明文块。轮密钥表是
  `aes128_expand` 产出的 176 字节标准字节序，`AESENC` 直接吃，**不需要**
  软件路径里的 `_bswap32`（那是"按大端字读"的补偿）。
- **把异或搬进 xmm**：硬件加密之后，原来 CTR 循环里"16 次 `mem_load8` + 16 次
  `mem_store8`"的异或反而成了瓶颈。改成 `movdqu` + `pxor` + `movdqu` 之后，
  整块 16 字节一条指令搞定。尾块（<16 字节）仍走逐字节路径。
- **两个 xmm 编码 bug（都是 v1.15 埋的，一直没暴露）**：
  1. `xmm_load/xmm_store` 的 `movdqu` 把 SIB 的 index 传了 **0**，编码出来是
     `[base + RAX*1]`——必须传 **4（RSP）** 表示"无索引"。症状是段错误。
  2. xmm 槽参数校验把**前两个实参都当槽**，但 `xmm_load` 的第 2 个实参是地址
     vreg（裸 int，不是 tuple），一取 `v[0]` 就 TypeError。
  这两个 bug 之所以能躺 16 个版本，是因为**没有任何 `.qma` 真的调用过 `xmm_*`**
  ——SHA-NI 那套基础设施写好了但库层没用。这次是第一个真实调用方。
- **降级路径保留**：`cpu_aes() == 0` 时仍走 T-table（v1.28 的 6.1 MB/s），
  `t48` 现在两条路径都断言 FIPS 向量。

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run bench/aes_bench.qma --target win` | **125 ms / MiB**（v1.30 为 171 ms，**1.37×**） |
| 同上，分段实测（`build/_aes_split.qma`，临时件） | CTR **2 ms**（软件 63 ms，**31×**）；GHASH **123 ms** |
| `python tests/run_win_tests.py` | **PASS=141 FAIL=0 SKIP=1** |
| `python tools/stage0/qlm_cli.py run tests/t48_aes.qma --target win` | ok（FIPS-197 三条路径 + GCM NIST 向量 + 篡改检测） |
| `python tools/stage0/qlm_cli.py run tests/t73_ghash.qma --target win` | ok |
| `python tools/stage0/qlm_cli.py run tests/t69_tls_client.qma --target win` | ok（RFC 8448 逐字节） |
| `python tools/dev/check_*.py` | 三禁 PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.31.0` |

## 已知边界 / 遗留

- **GCM 只快了 1.37×，因为瓶颈换人了**：CTR 从 63 ms 降到 2 ms 之后，
  GHASH 的 123 ms 占了端到端的 **98%**。下一步做 GHASH 的 PCLMULQDQ 版
  （预期 GHASH → 1–3 ms，端到端 → ~5 ms，即再快 25×）。这才是 GCM 的真正大头。
- **解密方向没接**：`aesdec/aesdeclast/aesimc` 指令已经能发射，但 `std/aes` 的
  CBC/ECB 解密仍走逐字节实现（GCM 只用加密方向，所以不影响 TLS）。
- **轮密钥扩展仍用软件**：`aeskeygenassist` 能发射但没用——扩展是一次性成本，
  换不来可测收益，而且软件扩展已有 FIPS 覆盖。
- **`cpu_aes()` 只在 x86_64 后端实现**（与 `cpu_sha` 一致）；arm64 编译 `std/aes`
  本来就会在 `load32` 上报错，不是这次引入的限制。
- **新发现一个既有误编译**（§7.4）：`_aes128_encrypt_block_fast` 直接写在 `main`
  里调用会丢最后一个字节，包一层就正常。产品路径未受影响，但这类"少写一个字节"
  比崩溃危险，已登记复现条件与排查方向。
