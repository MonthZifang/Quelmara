# v1.27 — RSA 验签（PKCS#1 v1.5 + PSS）与证书链 RSA 支持

- 日期：2026-10-22
- 任务：补上证书链里最常见的缺失零件——RSA 验签，让"EC 叶子 + RSA 根/中间"的链能验通。
- 影响面：标准库（新增 `std/rsa`，`std/x509`、`std/tls_client` 扩展）、测试、文档、版本号

## 为什么先做它

v1.26 的链引擎只认 P-256。真实证书链大量是 RSA：`example.com` 的根、Cloudflare 的根、
Microsoft/Amazon 的整条链都是 RSA。没有 RSA 验签，链验证在最后一节必然失败，
TLS 1.3 的 RSA `CertificateVerify`（0x0804）也永远只能返回 -1。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/rsa.qma` | **新增**（12 函数 / 2 公开）：32 位 limb 大整数 + Montgomery CIOS 乘法 + 平方-乘模幂；`rsa_verify_pkcs1_sha256`、`rsa_verify_pss_sha256`（MGF1）；模数长度不限（1024/2048/4096） |
| `std/x509.qma` | 新增 `x509_rsa_pub` / `x509_rsa_exp` / `x509_sig_bits`；`_x509_link` 在颁发者是 RSA 时走 PKCS#1 v1.5；`x509_pubkey` 增加曲线 OID 校验（只认 prime256v1）；修链顺序（intermediates 按 leaf→root 正序） |
| `std/tls_client.qma` | CertificateVerify 支持 0x0804（RSA-PSS，salt=32）；ClientHello 的 `signature_algorithms` 增加 0x0804 / 0x0401 |
| `tests/t71_rsa.qma` | **新增**：Python 生成的 1024 位向量——PKCS#1 正/负、PSS 正/负、错误指数 |
| `tests/t72_rsa2048.qma` | **新增**：2048 位 PKCS#1 向量（真实根证书的典型长度） |
| `tests/x509_chain_test.py` | 增加 RSA 根混合链（leaf/inter EC + root RSA PKCS#1）：10 → **13 项** |
| `tests/t69_tls_client.qma` | RFC 8448 的 RSA-PSS CertificateVerify 现在 **cv=1**（此前 -1） |
| `tests/run_win_tests.py` | 注册 t71 / t72（主回归 132 → 134） |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 `std/rsa` |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.26.0 → **1.27.0** |
| `docs/03-stdlib.md` | 33 模块 / 383 公开函数；补 `std/rsa` 与 RSA 边界 |
| `docs/06-status.md` | 回归 134 / lex 120 / parse 105 / bodydiff 895-755；新增 RSA 行；链测试 13 |
| `docs/07-gaps.md` | TLS 缺口收窄为"根证书库 + P-384/SHA-384" |

## 实现要点

- **Montgomery CIOS**：`uv = t[j] + a[j]*b[i] + c` 会超过有符号 64 位，但按位模式
  用 `& 0xFFFFFFFF` 取低 32 位、`>>> 32` 取高 32 位仍然正确（无符号语义）。
- **R² mod n**：不实现除法，用"从 1 开始倍增 64L 次"算 2^(64L) mod n。
- **指数**：65537 只有 2 个置位，平方-乘实际只做 17 次平方 + 1 次乘法，
  2048 位验签是毫秒级（不是 2048 次乘法）。
- **PSS**：EM = maskedDB || H || 0xbc，MGF1-SHA256，salt 固定 32；
  只接受标准形式（top bit 清零、PS 全 0、0x01 分隔）。
- **踩坑**：
  1. TLS 1.3 的 `CertificateEntry` 在 cert_data 之后还有 **2 字节 extensions 长度**，
     首版漏了它 → 第二张证书长度读成 0（真实链 3-4 张时才发现）。
  2. `x509_verify_chain` 的 intermediates 顺序写反了（用了倒序），单中间证书时看不出来，
     真实三张链才暴露。
  3. `x509_pubkey` 之前不校验曲线 OID，P-384 证书会被当成 P-256 截断 64 字节。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=134 FAIL=0 SKIP=1** |
| `python tests/x509_chain_test.py` | **PASS=13 FAIL=0**（含 RSA 根混合链） |
| `python tools/stage0/qlm_cli.py run tests/t69_tls_client.qma --target win` | ok（RFC 8448 **cv=1**，RSA-PSS） |
| `python tests/lexdiff.py` | **PASS=120 FAIL=0** |
| `python tests/parsediff.py` | **PASS=105 FAIL=0** |
| `python tests/bodydiff.py` | 一致 **895** / 分叉 **755** / SKIP 18-18 |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（33 模块 / 383 函数） |
| `python tools/dev/check_*.py` | 三禁 PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.27.0` |

真实站点手工探针（`build/` 下的一次性脚本，未入库）：

| 站点 | 结果 |
|---|---|
| www.amazon.com | 链 3 张全 RSA-SHA256；**leaf←inter、inter←root 两节验签均通过**；只差锚证书（Amazon Root CA 1 不在本机信任库） |
| www.microsoft.com | 链 3 张 RSA，但签名是 **SHA-384**（未支持） |
| github.com / example.com / cloudflare.com | 链里含 **P-384** 中间证书（未支持） |

## 已知边界 / 遗留

- **只有 SHA-256**：SHA-384/512 的证书签名与 `TLS_AES_256_GCM_SHA384` 都不支持。
- **只有 P-256**：P-384/P-521 曲线未实现。
- **只验签**：无 RSA 签名、无密钥生成、无 RSA-PSS 签名。
- **没有根证书库**：仍要调用方给锚证书；下一步做系统证书库枚举（Windows `CertOpenSystemStore`）。
- RSA 指数按 32 位处理（65537 够用）；不支持多质数、CRT（验签不需要）。
