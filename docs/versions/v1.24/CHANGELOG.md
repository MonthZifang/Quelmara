# v1.24 — TLS 1.3 客户端握手核心（RFC 8448 逐字节 + 真实服务器实测）

- 日期：2026-10-22
- 任务：把 v1.23 遗留的"握手状态机"从缺口变成可验证的离线核心——ClientHello 构造、服务器 flight 解密、Finished / CertificateVerify 验证、客户端 Finished 生成。
- 影响面：标准库（新增 `std/tls_client`，`std/tls13` 扩解析层）、测试与工具、文档、版本号

## 为什么先做它

TLS 的密码学零件（SHA-256 / AES-GCM / X25519 / HKDF / ECDSA）与证书解析都已就绪，
缺的是"按 RFC 8446 的顺序把它们串起来"。这一步不依赖 Quelmara 的网络栈，
可以先用 RFC 8448 的完整握手轨迹逐字节对拍，再用 Python 提供 socket 对真实服务器
跑一遍——两层验证都比直接接 socket 调试可靠。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/tls_client.qma` | **新增**（9 个函数，6 公开）：`tls_client_hello` 构造 ClientHello；`tls_client_handshake` 完成握手核心；`tls_cert_verify_hash` / `tls_verify_cert_verify` 验签；`tls_ecdsa_sig_raw` 把 DER 签名转 64 字节 r‖s；`TlsClientResult` 结构体返回全部中间结果 |
| `std/tls13.qma` | 新增 `tls_record_parse` / `tls_hs_parse`（记录与握手消息解析）、`tls_ext`（扩展构造）——25 → 28 个公开函数 |
| `tests/t69_tls_client.qma` | **新增**：RFC 8448 §3 完整轨迹对拍 + 自建 ClientHello 结构自检 + 篡改拒绝 + DER 签名向量 |
| `tools/dev/tls_probe.py` | **新增**：真实服务器握手探针（Python 提供 socket，手动运行，不进 CI） |
| `tests/run_win_tests.py` | 注册 t69（主回归 130 → 131） |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 `std/tls_client` |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.23.0 → **1.24.0** |
| `docs/03-stdlib.md` | 31 模块 / 359 公开函数；模块表与边界表补 `std/tls_client` |
| `docs/05-toolchain.md` | 脚本表补真实握手探针 |
| `docs/06-status.md` | 回归 131 / lex 116 / parse 101 / bodydiff 848-755；新增 RFC 8448 与真实握手两行 |
| `docs/07-gaps.md` | TLS 缺口收窄为"接网络的握手（`tcp_connect` + DNS）+ 证书策略层" |

## 实现要点

- **transcript 只装握手消息**（不含记录头）。顺序：CH → SH → EE → Certificate →
  CertificateVerify → Finished，每验一条再追加。
- **逐记录解密、逐消息解析**：见到服务器 Finished 立即停止，不把后续
  NewSessionTicket（应用密钥加密）误当握手记录解密。
- **Finished 验证用"追加前"的 transcript**：`HMAC(finished_key, Transcript-Hash)`，
  通过后才把 Finished 追加进 transcript，再派生应用流量密钥。
- **CertificateVerify**：待签名内容是 `64×0x20 || "TLS 1.3, server CertificateVerify" || 0x00 || Transcript-Hash`。
  TLS 1.3 的 ECDSA 签名是 **DER `SEQUENCE { INTEGER r, INTEGER s }`**，不是裸 r‖s——
  必须先去前导 0、右对齐到 32 字节（`tls_ecdsa_sig_raw`）。只支持 0x0403，
  RSA（0x0804）返回 **-1**，格式错返回 0。
- **两个踩坑**：
  1. ServerHello 的 `supported_versions` 扩展体是 **2 字节选中版本、没有内层长度字节**
     （ClientHello 里才有）。首版按 CH 格式读 `ep+1/ep+2`，fail-fast 越界。
  2. **DER 签名**：首版按 64 字节裸签名处理，RFC 轨迹（RSA 证书）发现不了；
     真实服务器实测 `ok=1 cv=0` 才暴露，`cv=1` 是修复后的结果。
     教训：离线向量覆盖不到的算法分支，必须用真实对端补一枪。

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run tests/t69_tls_client.qma --target win` | **ok t69_tls_client**（RFC 8448 全项一致） |
| `python tools/dev/tls_probe.py cloudflare.com` | **ok=1 cv=1**（ECDSA-P256 证书验签通过） |
| `python tools/dev/tls_probe.py example.com` | **ok=1 cv=1** |
| `python tools/dev/tls_probe.py www.cloudflare.com` | **ok=1 cv=1** |
| `python tests/run_win_tests.py` | **PASS=131 FAIL=0 SKIP=1**（SKIP 为 WSL，沙箱拦截） |
| `python tests/lexdiff.py` | **PASS=116 FAIL=0**（+t69） |
| `python tests/parsediff.py` | **PASS=101 FAIL=0**（+t69） |
| `python tests/bodydiff.py` | 一致 **848** / 分叉 **755** / SKIP 18-18（+t69） |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（31 模块 / 359 函数） |
| `python tools/dev/check_*.py` | 三禁 PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.24.0` |

RFC 8448 逐字节一致的项：X25519 共享密钥、`c/s hs traffic`、四个 handshake key/iv、
`c/s ap traffic`、服务器 Finished、**客户端 Finished 记录（58 B）**、服务器 Finished
之后的 transcript hash。

## 已知边界 / 遗留

- **Quelmara 自己还不能联网**：`tcp_connect` / DNS 未实现。`tls_probe.py` 的 socket
  由 Python 提供，只用于验证握手核心；真实 https 客户端还差网络层（下一轮主线）。
- **只支持** TLS 1.3 + `TLS_AES_128_GCM_SHA256` + x25519；无 HelloRetryRequest、
  无 PSK / 0-RTT、无 key update、无 post-handshake 消息。
- **CertificateVerify 只验 ECDSA-P256**；RSA 证书返回 -1。`ok=1` 只代表握手密码学
  校验通过，**不代表服务器身份可信**。
- **不校验证书链 / 有效期 / 域名 / 用途**；调用方必须自己决定是否信任 `cert_pub`。
- 服务器 flight 必须能读到 Finished；探针用"空闲 1 s"判断收完，生产实现需要按记录
  长度循环读。
