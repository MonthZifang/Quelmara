# v1.53 — 哈希族补全：SHA-512 / SHA-384 / HMAC-SHA512 / CRC-64（标准库）

- 日期：2026-10-23
- 任务：标准库轨第三轮——07-gaps §2「哈希」行点名空缺（"无 SHA-512、无 CRC64、
  无 BLAKE2"）的前两项：SHA-512 家族（含 SHA-384 变体与 HMAC）+ CRC-64/XZ。
- 影响面：`std/sha512.qma`（新增）、`std/crc64.qma`（新增）、
  `tests/t95_hash512.qma`（新增）、`tests/run_win_tests.py`（注册）、
  `docs/03-stdlib.md`（重生成，43→45 模块）、`docs/06-status.md`（PASS=161→162）、
  `docs/07-gaps.md`（§2 哈希行）、`tools/dev/gen_stdlib_doc.py`（DESC 登记两个
  新模块）、`tools/stage0/qlm_cli.py`（VERSION 1.52.0 → 1.53.0）

## 为什么是它

07-gaps §2 哈希行自 v1.35（MD5 收尾红标）起就挂着"无 SHA-512、无 CRC64"——
SHA-384 是 TLS 1.3 备用 PRF、长消息签名的刚需；CRC-64 是 xz/zlib 容器校验的
64 位表亲。选它：纯计算、FIPS 180-4 / RFC 4231 / ECMA-182 有权威测试向量、
与语言轨（切片窄标签在途）和工具链轨零文件重叠。BLAKE2 留到下一轮（它要另起
32/64 位两套 G 函数，独立成轮更干净）。

版本号：v1.51 被语言轨 f64 打印修复（a388dc9）占用、v1.52 被其切片窄标签
（在途）占用，且测试号 t94 亦被其占用——本轮顺延 v1.53 / t95。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/sha512.qma` | **新增**（约 390 行）：SHA-512 全函数（80 轮常量由脚本从素数立方根生成，K0/K79 与 FIPS 180-4 抽查一致）+ `sha512_str`/`sha512_hex`；SHA-384 变体（variant=1 换 IV、截断 48 字节，复用同一压缩函数）+ `sha384_hex`；HMAC-SHA512（RFC 2104，块长 128）+ `hmac_sha512_str`/`hmac_sha512_hex`。内部：`_sha512_core(buf, n, variant)` 单一核心（填充+IV 选择+块循环+大端输出），SHA-512/384/HMAC 三用 |
| `std/crc64.qma` | **新增**（约 75 行）：CRC-64/XZ（poly 0x42F0E1EBA9EA3693 反射式、init/xorout 全 1）+ `crc64`/`crc64_hex`，表驱动 256×8 |
| `tests/t95_hash512.qma` | **新增**（26 断言）：SHA-512 六向量（空 / abc / 112B / 128B / 43B / **1000B 多块**）、SHA-384 三向量、HMAC-SHA512 五例（RFC 4231 TC1/2/3/6/7，含 131 字节长 key 先压摘要路径）、CRC-64 五例 + **公开 check 值锚定**（"123456789" → 995dc9bbdf1939fa）、摘要缓冲 API 首尾字节直读 |
| `tests/run_win_tests.py` | 注册 `case_selfcheck("t95_hash512", ...)` |
| `docs/03-stdlib.md` | 重生成（45 模块 / 312 公开函数） |
| `docs/06-status.md` | 主回归 PASS=161 → PASS=162 |
| `docs/07-gaps.md` | §2 哈希行 ✅ v1.53（遗留：BLAKE2、SHA-512/224、SHA-3） |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 std/crc64.qma、std/sha512.qma |
| `tools/stage0/qlm_cli.py` | VERSION 1.52.0 → 1.53.0 |

## 实现要点

- **64 位字宽原生落地**：int 即 64 位，SHA-512 的 uint64 加法回绕免费、无需
  掩码；**右移一律 `>>>`（逻辑右移）**——轮常量与全 1 init 以补码存储为负值，
  `>>` 会灌符号位（GHASH 教训）；循环右移 = `(x >>> n) | (x << (64-n))`，
  64 位原生宽度不截断；按位非 = `x ^ 0xFFFFFFFFFFFFFFFF`（无一元 `~`）。
- **单一核心三用**：`_sha512_core(buf, n, variant)` 收掉填充/IV/块循环/输出，
  SHA-512（variant 0）、SHA-384（variant 1，换 IV 截断）、HMAC 内外两步全走它
  ——比 sha256 模块的"每个变体一份"少约 80 行重复。
- **80 个轮常量脚本生成**：从素数立方根小数部分现算（`build/probe/gen_sha512.py`），
  不手抄——FIPS 表 80 个 64 位常量手抄必错。
- **常量表堆上建一次**：`_sha512_ktab` 把 80 个 K 写进堆表，每轮一次
  `mem_load64`（sha256 v1.34 同款优化，规避 80 轮 × 常量的立即数编码膨胀）。
- **踩坑**：`len()` 不接受指针——摘要缓冲 API 的验证改成 `mem_load8` 读首尾
  字节（比查长度更实）；CRC64 的 `(crc ^ b) & 0xFF` 下标前必须掩码（64 位
  crc 与字节异或后取低 8 位）。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run tests/t95_hash512.qma --target win` | PASS（26 断言，首次即过） |
| `python tests/run_win_tests.py` | PASS=162 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证；本 commit 口径=HEAD 161 + t95。跑分时另有语言轨在途 t94_slice_narrow，同场全过则 163） |
| `python tools/dev/check_names.py` | PASS |
| `python tools/dev/check_origin.py` | PASS |
| `python tools/dev/check_docs.py` | PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（重生成后） |

## 已知边界 / 遗留

- SHA-512/224/256 截断变体未做（IV 不同，core 已支持 variant 扩展即可加）。
- BLAKE2b/2s 未做（下一轮候选）；SHA-3/Keccak 未做。
- CRC-64 只做 XZ 参数族；ECMA 非反射 / ISO 等其他参数族未做（表重建即可，
  未纳入 API）。
- 长消息（>2^61 字节）位长字段溢出未处理（double 级消息不现实，登记边界）。
- 性能未单独 bench（纯计算路径，sha256 71ms/MiB 为同族参照；SHA-512 每字节
  轮数更少，预期不慢于 sha256——未实测，不写数）。
