# v1.22 — ECDSA P-256 验签（TLS 证书签名）

- 日期：2026-10-22
- 任务：继续 TLS（上一轮结论：缺握手状态机、X.509、RSA/ECDSA 验签）。
- 影响面：标准库（新增 `std/p256`）、测试与 CI、文档

## 为什么先做它

TLS 1.3 里最常见的证书签名算法是 `ecdsa_secp256r1_sha256`。没有验签，
证书链就只是"读了一堆字节"，无法判断对端是谁。RSA 与 ECDSA 都要做，
但 ECDSA 的域运算可以复用 X25519 那套 limb 思路，先做它性价比更高。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/p256.qma` | **新增**（45 个函数，2 个公开）：8×32 limb 域运算（Montgomery SOS）、Jacobian 点运算（a=−3 专用倍点 + add-2007-bl）、标量乘、`p256_on_curve`、`ecdsa_p256_verify` |
| `tests/t67_ecdsa.qma` | **新增**：2 条合法签名、改 hash、r=n−1、公钥不在曲线上、G 在/不在曲线自检 |
| `tests/ecdsa_p256_test.py` | **新增**：Python 纯 bigint 参考实现 ↔ Quelmara 的 32 组互操作（20 正向 + 12 负向） |
| `tests/run_win_tests.py` | 注册 t67 |
| `.github/workflows/ci.yml` | 加 ECDSA 互操作步骤 |
| `tools/dev/gen_stdlib_doc.py` | DESC 补 `std/p256`，重新生成 API 段 |
| `docs/03-stdlib.md` | 重新生成（29 模块 / 339 公开函数）+ 边界表 |
| `docs/06-status.md` | 回归/对拍数字；性能表加验签 25 ms；TLS 状态改"密码学齐备" |
| `docs/07-gaps.md` | TLS 缺口收窄为"握手状态机 / X.509" |

## 实现要点

- **为什么用 Montgomery 而不是特殊折约**：P-256 的 p = 2^256 − 2^224 + 2^192 + 2^96 − 1
  不是 2^255−19 那种"折一次就完"的形状，通用 SOS 乘法（128 次 32 位乘）更容易写对。
  R² 与 n0′ 都是离线算好后硬编码的（由 Python 生成，注释标明勿手改）。
- **点用扁平 24 limb 表示**（X 0..7 / Y 8..15 / Z 16..23），不用 `vec[vec[int]]`——
  避开嵌套句柄的类型标签问题，也更快。
- **验签必须查公钥在曲线上**：否则无效曲线攻击可以泄露私钥。这条不是可选项。
- 标量乘是最朴素的 double-and-add（256 轮），没有窗口法——先正确再优化。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=129 FAIL=0 SKIP=1**（128 + t67） |
| `python tests/ecdsa_p256_test.py` | **PASS=32 FAIL=0** |
| `python tests/lexdiff.py` | PASS=114 FAIL=0 |
| `python tests/parsediff.py` | PASS=99 FAIL=0 |
| `python tests/bodydiff.py` | 一致 806 / 分叉 744 / SKIP 不同步 18 |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（29 模块 / 339 函数） |

互操作矩阵（Python bigint 与 Quelmara 完全独立）：

| 类别 | 组数 | 结果 |
|---|---|---|
| 合法签名（随机密钥 + 随机消息） | 20 | 全部接受 ✅ |
| 改 hash / 改 r / 改 s / 换公钥 | 4 | 全部拒绝 ✅ |
| r 或 s = 0 / 1 / n / n−1 | 7 | 全部拒绝 ✅ |
| 公钥不在曲线上 | 1 | 拒绝 ✅ |

性能：**单次验签 25 ms**（一次握手只需一次，可接受）。

## 已知边界 / 遗留

- **只验签不签名**：`sign` 需要 CSPRNG 与 RFC 6979 确定性 k，未做。
- **只有 P-256**：无 P-384 / secp256k1；无 RSA 验签（PKCS#1 v1.5 / PSS）。
- **只支持 SHA-256 摘要**：调用方传 32 字节 hash；SHA-384/512 需要换曲线参数。
- **未做 DER 解析**：`ecdsa_p256_verify` 收的是 r/s 裸值，证书里的
  `SEQUENCE { r INTEGER, s INTEGER }` 还要 X.509 层去解。
- **性能**：25 ms 是朴素 double-and-add 的结果；加窗口法/Naf 可降到 ~8 ms，
  但不是现在的瓶颈。
