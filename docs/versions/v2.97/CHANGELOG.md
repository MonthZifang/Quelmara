# v2.97 — 内置 TLS 根证书库：`std/x509roots`，两条真实公网链验到表内锚

- 日期：2026-10-28
- 任务：补库 —— gaps §2 TLS 行的"根证书库（信任锚管理）"（P0 第一项）
- 结论：语言从 v1.26 起就能验链，但锚要调用方自己喂——"能验链、不知道该信谁"。
  本版把 12 个主流根编进库，配 `x509_verify_stored` 一键验证；两条当天抓的
  真实链（pypi.org / www.apple.com）在 native 后端**执行级**验通。

## 为什么锚必须进库：一个被参数位置掩盖的缺口

`x509_verify_chain(leaf, inter, anchor, host, now)` 的签名一直把 `anchor`
留给调用方。对测试（tests/x509_chain_test.py 用 Python 自造三级链）这是对的；
对真实 HTTPS 客户端这是**结构性缺口**——tls_client 的握手路径里没有任何东西
能提供一个锚。gaps 把"根证书库"挂在 TLS 行下两年，缺的一直是这个表而不是验签。

## 数据与生成

12 个根（ISRG X1/X2、Amazon 1/3、DigiCert Global Root G2、GlobalSign R3、
USERTrust RSA/ECC、GTS Root R4、SSL.com TLS ECC Root 2022、
Sectigo Public Server Authentication Root E46、Certum Trusted Network CA），
2026-10-28 从 Debian bookworm `ca-certificates` 包提取（与 openssl 信任库同源），
DER 原样十六进制内联进 `std/x509roots.qma`——**运行时不读磁盘、不读环境变量**，
换根 = 改文件重编译。

API 是四个小函数：`x509_roots_count` / `x509_root_at` /
`x509_root_find(subject_dn)`（按主题 DN 逐字节配对，与 std/x509 现有口径一致）/
`x509_trusted_anchor(cert)`（查 issuer 命中的根）。
`x509_verify_stored(leaf, inter, host, now)` = 链尾 issuer 查锚 + 委托
`x509_verify_chain`——**多锚候选没有做循环重试**：链尾证书的 issuer DN 至多
命中一个根，跨签名桥由调用方放进 intermediates。

配套改动：`x509_subject` / `x509_issuer` / `x509_is_ca` 转 `pub`
（建链配对的必需面，文档注明"逐字节 DER 比较、不做 RFC 4514 规范化"的口径）；
`std/tls_client.qma` 里"当前没有内置根证书库"的过时注释更新为指向本模块。

## 普查：验证器的真实覆盖面（2026-10-28，五个主流站点）

写这个库之前先把"链到了锚之后，现有栈到底验得动什么"数了一遍——
**根证书库只解决锚；每一环签名算法必须落在 {RSA-SHA256, P-256-ECDSA-SHA256}
里才验得动**：

| 站点 | 链 | 每一环签名 | 现有栈 |
|---|---|---|---|
| pypi.org | GlobalSign Atlas R3 → R3 根 | 全 RSA-SHA256 | **通** |
| www.apple.com | Apple CA → DigiCert G2 | 全 RSA-SHA256 | **通** |
| deno.com | LE YE2 → Root YE → ISRG X2 | 全 **ECDSA-SHA384/P-384** | ✗ |
| cloudflare.com | GTS WE1 → GTS R4 | ECDSA-SHA384 起步 | ✗ |
| microsoft.com | MS G2 RSA CA → DigiCert G2 | 全 **SHA-384-RSA** | ✗ |
| example.com | SSL.com 链 → AAA 桥 | 环上 ECDSA-SHA384 + 桥锚不在表 | ✗ |

所以本版**不吹"HTTPS 全自动"**：t159 用两条 RSA-SHA256 链把路径钉死；
SHA-384/P-384 缺口登记进 gaps TLS 行（"12 根里 7 个 + Let's Encrypt/Google/
Sectigo 现役链都是 SHA-384 族"是 v2.98 的靶子，普查表就是它的验收清单）。
根自验证同理：12 个里 5 个能闭 SHA-256 环（ISRG X1 / Amazon 1 / Amazon 3 /
DigiCert G2 / GlobalSign R3），`x509_root_selfcheck` 对其余 7 个如实返回 0。

## 诚实的边界

| 项 | 现状 |
|---|---|
| 信任 = 人工契约 | 根的"可信"不是密码学能证的，只能自证签名闭合（selfcheck 就是它）；表的审计即本文件的 code review |
| 12 ≠ Mozilla bundle | 140+ 根的完整集、导入策略、TTL、更新通道不做——那是 qpm 的活 |
| DN 逐字节配对 | issuer/subject DER 完全相等才算命中；"同一实体不同编码"会漏（实测表内无此情况） |
| SHA-384/P-384 | 见上表；补齐前这些链整体不可用 |
| examples/https_get.qma | 没改默认锚来源——example.com 链的桥锚（AAA）不在表内，硬改会制造一个"验不过的示例"；待 v2.98 有 EC 链端到端能力后一起收口 |

## 验证

| 项 | 结果 |
|---|---|
| `tests/t159_roots.qma`（native 执行） | **roots ok**：12 根全在、两条真实链 `verify_stored=1`、域名不符/篡改叶证书=0、selfcheck pass=5 |
| win / arm64 交叉编译 t159 | PASS（三后端同一份夹具） |
| `run_native_tests.sh` 新增 `[26]` | 待完整跑（见下） |
| stdlib 文档 | `x509roots` 登记进 DESC；65 模块 / 543 公开函数，门禁一致 |
| 五道门禁 | check_names / check_origin / check_docs PASS |
