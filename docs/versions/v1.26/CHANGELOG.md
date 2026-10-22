# v1.26 — 证书链 / 有效期 / 域名校验（+ 三个编译器 bug）

- 日期：2026-10-22
- 任务：把 v1.25 的 `cv=1`（只证明签名有效）推进到"链、时间、域名都对"；顺带修掉挡路的三个运行时 bug。
- 影响面：标准库（`std/x509`、`std/tls_client`）、编译器运行时（`now_ns`）、测试与 CI、文档、版本号

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/x509.qma` | 新增 9 个公开函数：`x509_issuer` / `x509_subject` / `x509_validity`（UTCTime+GeneralizedTime → Unix 秒）/ `x509_time_valid` / `x509_is_ca`（basicConstraints）/ `x509_san` / `x509_host_ok`（通配符只匹配一级）/ `x509_verify_chain`（leaf→intermediates→anchor）/ `x509_validity_raw` |
| `std/tls_client.qma` | 保存完整 Certificate 消息体；新增 `tls_cert_count` / `tls_cert` / `tls_verify_chain`（用调用方给的锚证书验链 + SAN） |
| `tests/x509_chain_test.py` | **新增**：Python 手工构造 root→intermediate→leaf 三级 P-256 链，10 项断言（正向/通配符/跨级/过期/缺中间/篡改/根自签/有效期解析/SAN 数量） |
| `tests/t70_times.qma` | **新增**：`now_ns` + `wall_ms` + `rand` 同时使用的回归（对应下面的 bug） |
| `tests/run_win_tests.py` | 注册 t70（主回归 131 → 132） |
| `tools/stage0/qlm_native.py` | 修 3 个运行时 bug（见下） |
| `.github/workflows/ci.yml` | 加证书链测试步骤 |
| `docs/03-stdlib.md` | 32 模块 / 378 公开函数；x509 与 tls_client 的边界重写 |
| `docs/05-toolchain.md` | 脚本表补 `x509_chain_test.py` |
| `docs/06-status.md` | 回归 132 / lex 118 / parse 103 / bodydiff 873-755；新增链测试行；TLS 行补"无内置根证书库" |
| `docs/07-gaps.md` | TLS 缺口收窄为"根证书库 + RSA 验签" |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.25.0 → **1.26.0** |

## 实现要点

- **TBS 字段定位**：`_x509_skip(cert, n)` 从 serial 之后逐字段步进（signature/issuer/validity/subject/SPKI/extensions），
  避免给每个字段写一套偏移。
- **时间**：UTCTime（`YYMMDDHHMMSSZ`，YY<50 → 20xx）与 GeneralizedTime 都支持；
  `_x509_days` 用 Howard Hinnant 的 civil→days 算法，不依赖 libc。
- **SAN / 通配符**：只认 `dNSName`（tag 0x82）；`*.example.com` 只匹配一级标签，
  `a.b.example.com` 必须拒绝。
- **链**：每节校验 `child.issuer == issuer.subject`、issuer 的 CA 位、child 有效期、
  以及用 issuer 公钥验 child 的 TBS 签名；最后一节对锚证书。
- **两个真实的坑**：
  1. `now_ns()` 与 `wall_ms()` 同时使用时编译失败（`KeyError '__now_ns'`）——
     运行时块复用了变量 `f`，`__now_ns` 的函数体被后写的 `__wall_ms` 覆盖。
     修法：在 `__now_ns` 块结束时立刻 `self.out.append(f)`。
  2. Windows `__now_ns` 里 `cnt * 1e9` 溢出 int64（QPC 计数 ~1e12）→ 时间变成固定负数/常数，
     `sleep_ms(50)` 测出 0 ms（t58 回归抓住）。改成"秒 + 余数"两段计算。
  3. 修溢出时又踩到 IR 的 `bin sub dst, a, dst`（dst==src2）别名问题——结果恒 0；
     换成独立 vreg 后正常。**RosIR 的原地更新只保证 dst==src1，不要依赖 dst==src2**。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/x509_chain_test.py` | **PASS=10 FAIL=0** |
| `python tests/run_win_tests.py` | **PASS=132 FAIL=0 SKIP=1** |
| `python tests/lexdiff.py` | **PASS=118 FAIL=0** |
| `python tests/parsediff.py` | **PASS=103 FAIL=0** |
| `python tests/bodydiff.py` | 一致 **873** / 分叉 **755** / SKIP 18-18 |
| `python tools/stage0/qlm_cli.py run examples/https_get.qma --target win` | handshake ok (cv=1)；**cert chain=2 host_ok=1 time_ok=1**；HTTP/1.1 200 OK |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（32 模块 / 378 函数） |
| `python tools/dev/check_*.py` | 三禁 PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.26.0` |

## 已知边界 / 遗留

- **没有内置根证书库**：`x509_verify_chain` 必须由调用方给锚证书，公网 https 还无法自动信任。
- **不校验** keyUsage / EKU / CRL / OCSP / 证书策略 / name constraints；无 pathLen 检查；
  无 CN 回退（只认 SAN）。
- **RSA / Ed25519 证书**仍不支持（CV 返回 -1）。
- 链顺序按调用方给的 `leaf→root` 排列，不做自动链构建。
- Linux 仍无 `tcp_connect`/DNS；`std/tls_net` 只在 Windows 可用。
