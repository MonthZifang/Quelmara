# v1.28 — AES T-table + GHASH 4-bit 表（GCM 8×）

- 日期：2026-10-22
- 任务：性能专项第一项（07-gaps §5）：把 AES-GCM 从 0.77 MB/s 拉到可用水平。
- 影响面：标准库（`std/aes`）、基准、测试、文档、版本号

## 为什么先做它

v1.25 起 TLS 已经在用 `std/aes` 的 GCM，但 1 MiB 要 **1369 ms**（0.77 MB/s）——
握手能用，传数据没法看。07-gaps 把 GHASH 表列为 15–20× 收益，实测先确认瓶颈：
GHASH 表单独只带来 1.44×，**AES 轮函数才是主瓶颈**（逐字节 SubBytes/MixColumns），
所以先做 T-table，再叠 GHASH 表。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/aes.qma` | 表区从 512 B 扩到 4608 B（sbox + inv_sbox + Te0..Te3）；新增 `_aes128_encrypt_block_fast`（T-table，每轮 16 次 32 位查表）；GCM 的 CTR 路径改走它；GHASH 增加 4-bit 表（32 nibble × 16 项 × 16 B，≥16 块时启用） |
| `bench/aes_bench.qma` | **新增**：1 MiB GCM 加解密吞吐（min of 3） |
| `tests/t73_ghash.qma` | **新增**：NIST GHASH 向量（逐位 vs 表）+ 4 KiB GCM 往返 |
| `tests/run_win_tests.py` | 注册 t73（主回归 134 → 135） |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.27.0 → **1.28.0** |
| `docs/03-stdlib.md` | aes 6/33；内部函数数更新 |
| `docs/06-status.md` | 回归 135；性能表加 AES-GCM 171 ms |
| `docs/07-gaps.md` | §5 GHASH 标 ✅；AES-NI 说明更新；新增 §7 推进顺序 |

## 实现要点

- **T-table**：`Te0[x] = [2s, s, s, 3s]`（大端语义），Te1..3 是字节旋转；
  状态用 4 个 32 位字，轮密钥用 `bswap(mem_load32)` 取大端字。
  每轮 16 次查表 + 4 次轮密钥异或，替代原来 16 次 SubBytes + 16 次 `_gmul`。
- **GHASH 表**：`T[i][j] = j·H·x^(4i)`，第 0 列是最高 nibble；
  `T[i] = x^4·T[i-1]`，建表 32×16 项（8 KiB），小输入（<16 块）仍走逐位算法。
- **三个坑（都是"看起来对、结果不对"）**：
  1. GCM 的 GF(2^128) 以**最高位为 x^0**：乘 x 是**右移** + 0xE1，不是左移。
  2. nibble 的位序是大端：`j` 的 MSB 对应 x^0，建表前要把 j 的 4 位反转。
  3. 状态字是大端语义，`_put32` 写小端，输出前必须 `bswap`。
  这三个都只影响 ≥16 块的输入，FIPS 小块向量测不出来——靠 t69（RFC 8448 657 B flight）暴露。

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run bench/aes_bench.qma --target win` | **171 ms / MiB**（前 1369 ms，**8.0×**） |
| `python tests/run_win_tests.py` | **PASS=135 FAIL=0 SKIP=1** |
| `python tools/stage0/qlm_cli.py run tests/t69_tls_client.qma --target win` | ok（RFC 8448 仍全过） |
| `python tools/stage0/qlm_cli.py run tests/t48_aes.qma --target win` | ok（FIPS 向量） |
| `python tools/stage0/qlm_cli.py run examples/https_get.qma --target win` | 200 OK（真实 TLS 记录解密正常） |
| `python tools/dev/check_*.py` | 三禁 PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.28.0` |

分项：AES T-table 约 6×；GHASH 4-bit 表 1.44×（关表 237 ms → 开表 171 ms）。

## 已知边界 / 遗留

- **没有 AES-NI**：软件 T-table 的天花板；AES-NI + PCLMUL 才能到 GB/s 级（与 SHA-NI 同批，需要编码器扩展）。
- AES **解密**仍走逐字节实现（GCM 只用加密方向，CBC 解密未优化）。
- GHASH 表每次 `ghash` 调用重建（8 KiB）；连续大记录可缓存到连接级（下一步）。
- T-table 有缓存侧信道风险（查表依赖密钥）；当前定位是自研栈性能，不是常量时间实现。
