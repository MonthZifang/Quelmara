# v1.25 — 自研 HTTPS 客户端：tcp_connect + 系统 DNS + TLS 联网

- 日期：2026-10-22
- 任务：把 v1.24 的离线握手接到 Quelmara 自己的网络栈上——加 `tcp_connect` 内建，跑通"自己连、自己握手、自己发 HTTP"。
- 影响面：编译器内建（`tcp_connect`）、标准库（`std/net`、新增 `std/tls_net`）、示例、文档、版本号

## 为什么先做它

v1.24 的握手核心已经能验证真实服务器，但 socket 由 Python 提供。缺的正是
"从 Quelmara 程序里打开一条 TCP" 这一格。补上后，https 客户端不再依赖外部传输。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 新增 `tcp_connect(host, port)` 内建与 `__tcp_connect` 运行时（Windows `getaddrinfo` + `connect`；Linux 编译期明确报错） |
| `tools/stage0/qlm_pe.py` | ws2_32 白名单加 `getaddrinfo` / `freeaddrinfo` / `connect` |
| `std/net.qma` | 新增 `connect(host, port)`（6 → 7 公开函数） |
| `std/tls_net.qma` | **新增**（5 个公开函数）：`tls_connect` 建连并握手、`tls_send_app` / `tls_read_app` 收发应用数据、`tls_random`、`tls_recv_exact` |
| `std/tls13.qma` | 新增 `tls_open_record_raw`（保留内容类型字节，用于跳过 NewSessionTicket）——28 → 29 公开函数 |
| `std/tls_client.qma` | `TlsClientResult` 增加 `fd` / `c_ap_key` / `c_ap_iv` / `s_ap_key` / `s_ap_iv`，供网络层直接用应用密钥 |
| `examples/https_get.qma` | **新增**：自研 TCP + TLS 握手 + HTTPS GET，打印状态行（第 18 个示例） |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 `std/tls_net` |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.24.0 → **1.25.0** |
| `docs/03-stdlib.md` | 32 模块 / 366 公开函数；补 `std/tls_net` 与 `std/net.connect` 的边界 |
| `docs/06-status.md` | 新增"自研 HTTPS GET"实测行；TLS 平台状态改"客户端可用（Windows）" |
| `docs/07-gaps.md` | TLS 缺口收窄为"证书策略层 + Linux 网络层"；DNS / HTTP 客户端行同步 |
| `docs/01-overview.md` | 示例数 17 → 18 |

## 实现要点

- **`getaddrinfo` 结构布局**：hints 48 B（`ai_family`@4、`ai_socktype`@8、`ai_protocol`@12），
  返回的 `ADDRINFOA` 里 `ai_addr` 在 +32。把 16 B `sockaddr_in` 拷到自己的缓冲后，
  覆写字节 2/3 为端口大端——这样 service 传 NULL 也能连任意端口。
- **逐记录读 flight**：读 5 B 记录头 → 读长度 → 追加，然后重新跑
  `tls_client_handshake`；返回 `no-finished` 说明还没收完，继续读（最多 16 条）。
- **应用数据**：`tls_read_app` 用 `tls_open_record_raw` 拿到内容类型，跳过
  NewSessionTicket（握手类型 22），只返回 23（应用数据）。
- **随机**：`tls_random` 用 xorshift64* 混 `now_ns`，**不是 CSPRNG**；握手临时密钥够用，
  对外服务前要换。
- **端口字节**：`sockaddr_in.sin_port` 是大端，直接写 `port>>8` / `port&0xFF`，
  不需要 `htons`。

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run examples/https_get.qma --target win` | **handshake ok (cv=1)；sent 78 B；got 923 B；HTTP/1.1 200 OK** |
| `python tools/stage0/qlm_cli.py run build/tcp_probe.qma --target win` | 明文 HTTP 到 example.com:80：`sent=56 got=928 HTTP/1.1 200 OK` |
| `python tools/stage0/qlm_cli.py run tests/t69_tls_client.qma --target win` | ok（RFC 8448 仍全过） |
| `python tests/run_win_tests.py` | **PASS=131 FAIL=0 SKIP=1** |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（32 模块 / 366 函数） |
| `python tools/dev/check_*.py` | 三禁 PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.25.0` |

## 已知边界 / 遗留

- **Linux 没有 `tcp_connect`**：编译期明确报错（DNS 未实现），Linux 只能继续做服务端。
- **无 IPv6**：`getaddrinfo` 只请求 `AF_INET`。
- **没有证书策略**：不验证链 / 有效期 / 域名；`cv=1` 只证明签名有效，不证明"这是 example.com"。
- **RSA 证书返回 -1**；只支持 TLS 1.3 + AES-128-GCM-SHA256 + x25519。
- **seq 由调用方维护**，`tls_read_app` 跳过的握手记录数不返回——适合单次请求/响应，
  多轮读写需要连接对象（下一步）。
- 没有 HTTP 封装（重定向 / chunked / 连接池）、没有 ALPN。
