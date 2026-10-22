# v1.21 — TLS 1.3 密钥调度 + AEAD 记录层

- 日期：2026-10-22
- 任务：继续 TLS（上一轮结论：密码学零件已齐，缺把它们串起来的胶水层）。
- 影响面：标准库（新增 `std/tls13`）、测试、文档

## 为什么是这一层

TLS 1.3 的骨架分三段：**密码学零件**（SHA-256/HMAC、AES-GCM、X25519，已齐）→
**密钥调度 + 记录层**（本轮）→ **握手状态机 + 证书/签名**（未做）。

中间这层是纯函数：给 secret 和 transcript hash 算出流量密钥，给 key/nonce/aad
算出密文记录。**不需要网络就能用 RFC 向量逐字节验证**——这正是它值得先做的原因。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/tls13.qma` | **新增**（25 个公开函数）：HKDF-Extract/Expand、HKDF-Expand-Label、Derive-Secret、key schedule（early/handshake/master、traffic key/iv、finished_key）、nonce 构造、AEAD 封装/解封、记录与握手消息帧、u16/u24 编码 |
| `tests/t66_tls13.qma` | **新增**：RFC 5869 三个 HKDF 用例、RFC 8448 §3 完整密钥链、nonce 三个序号、AEAD 往返 + 篡改拒绝、帧编码 |
| `tests/run_win_tests.py` | 注册 t66 |
| `tools/dev/gen_stdlib_doc.py` | DESC 补 `std/tls13`，重新生成 API 段 |
| `docs/03-stdlib.md` | 重新生成（28 模块 / 337 公开函数）+ 边界表加 tls13 行 |
| `docs/06-status.md` | 回归/对拍数字更新；TLS 状态改为"记录层就绪" |
| `docs/07-gaps.md` | TLS 缺口收窄为"握手状态机 / X.509 / 签名验证" |

## 实现要点

- **HKDF-Expand-Label 的编码**是这一层最容易写错的地方：
  `uint16 length || uint8 label_len || "tls13 "+label || uint8 ctx_len || context`，
  长度字段是**大端**，且 label 必须带 `tls13 ` 前缀。
- **nonce = IV XOR seq**，seq 按大端放在**最后 8 字节**——写错位置在 seq=0 时
  完全看不出来，只有序号增长后才暴露，所以测试特意覆盖 seq=0/1/256。
- **记录层**：TLS 1.3 把真实内容类型藏在明文末尾，外层类型恒为 23（application_data），
  AAD 用 `23 || 0x0303 || 密文长度(含 tag)`。
- 复用了 `std/sha256` 的 HMAC 与 `std/aes` 的 GCM，没有重写密码学。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=128 FAIL=0 SKIP=1**（127 + t66） |
| `python tests/lexdiff.py` | PASS=113 FAIL=0 |
| `python tests/parsediff.py` | PASS=98 FAIL=0 |
| `python tests/bodydiff.py` | 一致 797 / 分叉 744 / SKIP 不同步 18 |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（28 模块 / 337 函数） |

RFC 向量（逐字节一致）：

| 用例 | 结果 |
|---|---|
| RFC 5869 TC1（22B IKM / L=42） | PRK ✅ OKM ✅ |
| RFC 5869 TC2（80B 输入 / L=82，跨 3 块） | PRK ✅ OKM ✅ |
| RFC 5869 TC3（空 salt / 空 info） | PRK ✅ OKM ✅ |
| RFC 8448 early_secret | ✅ `33ad0a1c…70f92a` |
| RFC 8448 derived（"tls13 derived"） | ✅ `6f2615a1…3611ba` |
| RFC 8448 handshake_secret | ✅ `1dc826e9…3fbeac` |
| RFC 8448 client hs key / iv | ✅ `dbfaa693…258d01` / `5bd3c71b…73265f` |
| RFC 8448 server hs key / iv | ✅ `3fce5160…e403bc` / `5d313eb2…000b30` |

## 已知边界 / 遗留

- **还不能完成一次真实握手**：缺 ClientHello/ServerHello 构造、证书链解析、
  RSA/ECDSA 验签、CertificateVerify 与 Finished 的收发状态机。
  本轮只保证"密钥算对了、记录能加解密"。
- **无 0-RTT / PSK / HelloRetryRequest**：只实现了 (EC)DHE 的 1-RTT 主路径。
- **AEAD 只支持 AES-128-GCM**：TLS 1.3 还允许 ChaCha20-Poly1305 与 AES-256-GCM，
  我们只有 AES-128-GCM。
- **无 transcript 管理**：调用方自己累积握手消息并调 `tls_hash`；
  下一步做状态机时应封装成 `transcript` 结构。
- `substr(s, start, count)` 的第二参是**长度**不是结束位置——本轮踩过一次，
  已记进 `docs/02-language.md` 的陷阱清单。
