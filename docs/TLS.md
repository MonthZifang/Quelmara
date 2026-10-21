# TLS（https / wss）路线图

> 状态：**Phase A 进行中**（2026-10-21）。ws/http/sse 明文栈已全部落地并实测；
> TLS 是它们通向 https/wss 的最后一层。本文是路线的唯一权威记录。
>
> **已落地**：`std/sha256.qma`（SHA-256 + HMAC，FIPS 180-4 / RFC 4231 向量全过）、
> `std/aes.qma`（AES-128 分组 + **GCM**，FIPS-197 + NIST SP 800-38D case 2/3 全过）。
> **仍缺**：X25519（Phase A 第三件）、记录层/握手/X.509（Phase B）、https/wss 接线（Phase C）。

## 1. 现状与边界

明文协议栈（TCP → 帧层 → 语义层）已经闭环：

| 层 | 状态 | 说明 |
|---|---|---|
| TCP | ✅ v1.3 | tcp_* 内建（Windows ws2_32 / Linux raw syscall） |
| IOCP reactor | ✅ v1.4 | net_serve + 回调派发，十万连接槽位层 |
| HTTP/1.1 | ✅ v1.5 | std/http.qma，keep-alive + 流水线 |
| WebSocket | ✅ v1.5 | std/ws.qma，RFC 6455 全量帧层 |
| SSE | ✅ v1.5 | std/sse.qma，W3C event-stream |
| 密码学 | 🟡 | SHA-1 ✅、**SHA-256 + HMAC ✅**、**AES-128-GCM ✅**；X25519/RSA/X.509 ❌ |
| **TLS** | ❌ | 本文主题 |

## 2. 为什么 TLS 是独立的里程碑

一个可对话 TLS 1.2/1.3 的服务端至少需要：

1. **SHA-256 + HMAC**（TLS 1.2 PRF / TLS 1.3 全程）——工作量小，
   SHA-1 的实现骨架可直接复用；
2. **AES-128-GCM**（TLS 1.3 唯一强制套件）——需要 GHASH（GF(2^128)
   乘法）与 AEAD 组装，中等；
3. **X25519 或 P-256 ECDHE**（密钥交换）——域算术，中等偏大；
4. **ECDSA P-256 或 RSA 证书验证**——大（RSA 需要大数运算库）；
5. **握手状态机 + 记录层**（分块/重协商/告警）——中等；
6. **X.509 解析**（ASN.1/DER）——大而琐碎。

全部用 Quelmara 自实现是**总目标**（与项目"一切用自家语言"的纪律一致），
但这是一整个版本的量，不该混进协议库版本里半途而废。

## 3. 分阶段落地

### Phase A — 密码学地基（可先行，无 TLS 也能用）

- [x] `std/sha256.qma`：SHA-256 + HMAC-SHA256。FIPS 180-4 与 RFC 4231（case 1/2/6，
      含 131 字节超块长 key）全过；1 MiB 71 ms（14.7 MB/s，标量实现）。
      测试：`tests/t43_sha256.qma`。
- [x] `std/aes.qma`：AES-128 分组加解密 + **GCM**（CTR + GHASH + tag 校验）。
      向量：FIPS-197 C.1、NIST GCM case 2（全零）与 case 3（带 AAD）；
      另有往返、篡改检测、AAD 不匹配必须失败。测试：`tests/t48_aes.qma`。
      S-box 不写字面量表（`\xNN` 高位有已知误编译），改为运行时 GF(2^8) 求逆生成 + 缓存。
- [ ] `std/ecdh.qma`：X25519。**前置是 255 位域算术**（语言只有 64 位 int），
      计划用 5×51-bit limb；先做 `std/u128.qma`（加减/乘法 hi-lo/比较）作为地基，
      再做 GF(2^255-19) 的 mul/add/invert。

Phase A 完成后即可独立发布：SHA-256/HMAC 是通用件（签名、ETag、令牌），
AES-GCM 可直接用于自研协议的加密帧。

**性能现状（诚实口径）**：GCM 的 GF(2^128) 乘法是逐位实现（128 次/块），
SHA-256 是标量实现——两者都只到"能用"，没到"能打"。
TLS 握手/大量数据传输前需要先做：AES 查表化（T-tables）、GHASH 4-bit 表、
SHA-256 轮展开。否则 TLS 吞吐会是明文栈的 1/50 量级。

### Phase B — TLS 1.3 记录层 + 握手（服务端优先）

- [ ] 记录层：分块、AEAD 加解密、序号
- [ ] ClientHello/ServerHello/EncryptedExtensions/Certificate/Finished
- [ ] 自签证书链的最小 X.509 生成与解析（DER 只实现需要的子集）
- [ ] `std/tls.qma`：对上层暴露"透明传输"接口——
      `tls_serve(port, ..., on_data)` 与 `net_serve` 同形，
      http/ws/sse 的 handler 无需改动（TLS 只是换传输）。

### Phase C — 接线

- [ ] `https_serve` = tls 传输 + std/http handler
- [ ] `wss_serve` = tls 传输 + std/ws（握手照旧，密钥计算不变）
- [ ] 客户端侧（https/wss 出站）在服务端稳定后另排

## 4. 兼容性承诺（已预留的缝）

- ws/http/sse 的回调签名不变：TLS 就位后只换 serve 入口。
- 槽位层（std/net/core.qma）与 TLS 无关，十万连接的内存账不变
  （每连接额外 ~200 B 密钥材料，在 Phase B 实测定稿）。
- SHA-1/SHA-256 的 API 风格保持一致（`*_str` / `*_hex`）。

## 5. 验收口径

- 与 OpenSSL s_client / curl 互通（这是唯一权威互操作测试）
- 握手吞吐与本机明文栈对照（目标：TLS 开销 < 2× 明文握手）
- 十万连接常驻内存增量可算（槽位层账本不变）
