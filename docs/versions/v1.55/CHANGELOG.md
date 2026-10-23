# v1.55 — BLAKE2b（RFC 7693）：哈希族收口（标准库）

- 日期：2026-10-23
- 任务：标准库轨第四轮——07-gaps §2「哈希」行最后一项：BLAKE2b（v1.53 补了
  SHA-512/CRC-64 后仅剩它）。含 keyed 模式与变长输出。
- 影响面：`std/blake2b.qma`（新增）、`tests/t97_blake2b.qma`（新增）、
  `tests/run_win_tests.py`（注册）、`docs/03-stdlib.md`（重生成，45→46 模块）、
  `docs/06-status.md`（PASS=162→163）、`docs/07-gaps.md`（§2 哈希行翻绿收口）、
  `tools/dev/gen_stdlib_doc.py`（DESC 登记）、`tools/stage0/qlm_cli.py`
  （VERSION 1.54.0 → 1.55.0）

## 为什么是它

07-gaps §2 哈希行自 v1.35 起挂着"无 SHA-512、无 CRC64、无 BLAKE2"——v1.53
清掉前两项，本轮清掉最后一项，整行翻绿收口。BLAKE2b 是现代 KDF/签名/MAC 的
事实标准，原生支持 keyed 与 1..64 字节变长输出，比 SHA-2 快。选在此时：纯
计算、RFC 7693 附录 A 有权威向量、与语言轨（切片别名截断在途）零文件重叠。

版本号：v1.54 被语言轨切片别名截断轮（在途）占用，本轮顺延 v1.55。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/blake2b.qma` | **新增**（约 260 行）：顺序模式 BLAKE2b——`_b2b_compress`（12 轮 × 8 G，列步+对角步）、`_b2b_g1`/`_b2b_g2`（G 函数拆两个 6 参半边）、`_b2b_sigma_tab`（160 字节 σ 置换表）、`_b2b_hash`（key 块/整块/末块三段流，t 计数器按参考实现语义）；公开 `blake2b_hex` / `blake2b_hex_n`（变长）/ `blake2b_keyed_hex` / `blake2b_str` |
| `tests/t97_blake2b.qma` | **新增**（12 断言）：RFC 7693 A.1 标准向量（"abc" 逐字节匹配）、空消息、43B、1000B 多块、变长输出 32/20/1、keyed 三态（64B key / 短 key / **keyed 空消息**）、摘要缓冲 API 首字节 |
| `tests/run_win_tests.py` | 注册 `case_selfcheck("t97_blake2b", ...)` |
| `docs/03-stdlib.md` | 重生成（46 模块 / 316 公开函数） |
| `docs/06-status.md` | 主回归 PASS=162 → PASS=163 |
| `docs/07-gaps.md` | §2 哈希行收口（遗留仅：SHA-512/224、SHA-3） |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 std/blake2b.qma |
| `tools/stage0/qlm_cli.py` | VERSION 1.54.0 → 1.55.0 |

## 实现要点

- **G 函数拆两半**：完整 G 要 7 个形参（v,a,b,c,d,x,y），超 Quelmara 的 6 参
  上限——拆成 `_g1`（a+=b+x; d=rotr32(d^a); c+=d; b=rotr24(b^c)）与
  `_g2`（a+=b+y; d=rotr16; c+=d; b=rotr63），每 G 两次调用（12 轮 × 8 G =
  192 次/块；后续可合并优化，登记性能跟进项）。
- **t 计数器语义对齐参考实现**（本轮唯一的语义坑）：整块压缩前 t += 128；
  **末块 t = 已处理总量含本块实际字节数（空消息 t=0）**——不是 +128；
  **keyed 空消息的 key 块即最后一块**（last=1，不再压零块）——前两版实现
  在这里错，t97 的 keyed-empty 向量当场抓住。
- **σ 置换表堆上建一次**（160 字节），12 轮取 `r % 10` 的行偏移；
  64 位右移一律 `>>>`（IV/掩码高位为负，`>>` 会灌符号位）。
- 参数块：`h[0] ^= 0x01010000 ^ (keylen << 8) ^ outlen`（顺序模式、无树）。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run tests/t97_blake2b.qma --target win` | PASS（12 断言；keyed-empty 向量抓出并修正 t 语义后全过） |
| `python tests/run_win_tests.py` | PASS=163 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证；本 commit 口径=HEAD 162 + t97。跑分时另有语言轨在途 t94_slice_narrow，同场全过则 164） |
| `python tools/dev/check_names.py` | PASS |
| `python tools/dev/check_origin.py` | PASS |
| `python tools/dev/check_docs.py` | PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（重生成后） |

## 已知边界 / 遗留

- **性能未优化**：G 函数 192 次调用/块（6 参上限逼出来的拆分）——后续可把
  列步/对角步按常量展开内联（同 sha256 v1.34 路线），或等函数形参上限放宽。
- 只做顺序模式；树模式（node offset / last node 组织）未做。
- BLAKE2s（32 位字版）、BLAKE2bp/Xof 未做；SHA-3 未做（07-gaps §2 遗留）。
- 哈希行至此收口：SHA-1 / SHA-256 / SHA-512 / SHA-384 / MD5 / FNV-1a /
  CRC-32 / CRC-64 / BLAKE2b 全家在位。
