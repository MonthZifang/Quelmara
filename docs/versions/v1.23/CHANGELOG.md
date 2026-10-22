# v1.23 — X.509 证书解析（TLS 证书层）

- 日期：2026-10-22
- 任务：把 TLS 最后一段的前置补上——从 DER 证书里取出可验签的三元组，并把上一轮已写好但未入账的 X.509 工作正式纳入回归、CI 与文档。
- 影响面：标准库（新增 `std/x509`）、测试与 CI、文档、版本号

## 为什么先做它

TLS 1.3 的 Certificate 消息是 DER 编码。v1.22 的 `ecdsa_p256_verify` 只吃裸 `r/s`，
拿到证书字节仍然无从下手。X.509 层负责把"一坨字节"变成
`TBS 原始字节 + 公钥 + (r,s)`，这是握手状态机（下一轮）的直接前置。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/x509.qma` | **新增**（12 个函数，11 公开）：DER TLV（长度 ≤3 字节）、`x509_tbs` / `x509_pubkey` / `x509_sig` / OID 提取、`x509_verify_self_p256` / `x509_verify_with_p256` |
| `tests/t68_x509.qma` | **新增**：v3 证书端到端（长度 / 公钥 / 签名 / 两个 OID / TBS / 自签验证 / 篡改 / 截断） |
| `tests/x509_test.py` | **新增**：Python 手工构造 DER + 纯 bigint 签名 ↔ Quelmara 解析与验签，7 组（4 正向 + 3 负向） |
| `tests/run_win_tests.py` | 注册 t68（主回归 129 → 130） |
| `.github/workflows/ci.yml` | 新增 X.509 互操作步骤 |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 `std/x509`；新增"`std/` 下的模块必须登记，否则 FAIL"的检查 |
| `tools/dev/check_docs.py` | 新增第 6 项门禁：`VERSION` 必须与最新 `docs/versions/vX.Y/` 同源 |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.19.0 → **1.23.0**（v1.20–v1.22 三个版本漏升） |
| `docs/03-stdlib.md` | 30 模块 / 350 公开函数；模块表与边界表补 `std/x509`；`std/tls13` 的"无 X.509"改为"无握手状态机" |
| `docs/05-toolchain.md` | 脚本表补 ECDSA / X.509 互操作；门禁与 CI 步骤同步 |
| `docs/06-status.md` | 回归 130 / lex 115 / parse 100；新增 ECDSA、X.509 互操作两行；TLS 状态改"密码学 + 证书解析齐备"；**自举比例修正 8.0% → 8.7%**（1846/21128） |
| `docs/07-gaps.md` | TLS 缺口收窄为"握手状态机 + 证书策略层"；`version` 口径改为由门禁校验 |
| `.gitignore` | 忽略 `fixtures/qpm-demo/.git/`（演示时重建） |

## 实现要点

- **DER INTEGER 归一化**：去掉前导 `0` 后右对齐到 32 字节；超过 32 字节（负数或异常）
  填 0 → 验签必然失败，不抛错、不崩。
- **只认未压缩点**（`0x04`）与 P-256。`x509_pubkey` 只校验 BIT STRING 的形状，
  **不核对曲线 OID**——调用方需要自己比对 `x509_curve_oid(cert) == 2a8648ce3d030107`。
- **不做策略**：有效期、域名、用途、链构建、CRL/OCSP 全部不查。这是解析器，不是验证器。
- **链式验证**用 `x509_verify_with_p256(cert, issuer_pub)`；自签（根证书）用
  `x509_verify_self_p256`。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=130 FAIL=0 SKIP=1**（SKIP 为 WSL 交叉验证，沙箱拦截） |
| `python tests/x509_test.py` | **PASS=7 FAIL=0** |
| `python tests/ecdsa_p256_test.py` | PASS=32 FAIL=0 |
| `python tests/lexdiff.py` | **PASS=115 FAIL=0**（+t68） |
| `python tests/parsediff.py` | **PASS=100 FAIL=0**（+t68） |
| `python tests/bodydiff.py` | 一致 818 / 分叉 750 / SKIP 同步 18 / SKIP 不同步 18（+t68） |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（30 模块 / 350 函数） |
| `python tools/dev/check_*.py` | 三禁 PASS（含新增的版本号同源检查） |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.23.0` |

## 已知边界 / 遗留

- **只解析、不建链**：无有效期/域名/用途校验，无 CRL/OCSP，无信任锚管理。
- **只有 ECDSA-P256 + SHA-256 + 未压缩点**；RSA、Ed25519、压缩点未做。
- 长格式长度只支持 ≤3 字节（证书实际不会超过 16 MB，够用）。
- `x509_pubkey` 不校验算法/曲线 OID，安全用法必须同时核对 `x509_curve_oid`。
- **下一步**：TLS 握手状态机（ClientHello → ServerHello → EncryptedExtensions →
  Certificate → CertificateVerify → Finished），X.509 策略层随后。
