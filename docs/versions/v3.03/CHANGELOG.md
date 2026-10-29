# v3.03 — Linux DNS：自研 A 记录解析器（纯 Quelmara），域名解析不再依赖 glibc

- 日期：2026-10-29
- 任务：补库 —— 清掉 `07-gaps.md` §2「DNS」行里的"Linux 无解析器"
- 影响面：标准库（新增 `std/net/dns`）、测试（新增 `tests/dns_test.py`）、文档

## 缺口的真实形状

Linux 上 `tcp_connect` 一直只能吃 IPv4 点分字面量，域名会 fail-fast
（v2.92 定下的边界）。当时的理由是：

> Linux 的解析要走 nsswitch → dlopen 插件 → `/etc/resolv.conf` 状态机，
> 手写一遍等于把 glibc 的 resolver 抄进来。

这个判断**一半对一半错**。对的是"不要抄 glibc"，错的是把两件事混成了一件：

| 层次 | 内容 | 能不能自己做 |
|---|---|---|
| **DNS 协议** | 拼报文、解析报文、名字压缩、记录类型 | ✅ 纯协议，与 libc 无关 |
| **平台策略** | nsswitch 顺序、hosts 文件、mDNS、systemd-resolved、NSS 插件 | ❌ 抄不动，也不该抄 |

所以正确的做法是：**协议自己做，策略交给调用方**。而策略里真正覆盖 99% 场景的
只有一件事——读 `/etc/resolv.conf` 拿 nameserver，那是十几行字符串处理。

## 实现：`std/net/dns.qma`（纯 Quelmara）

跑在已有的 UDP 内建（`udp_open`/`udp_sendto`/`udp_recvfrom`）上，
没有新增任何编译器内建、没有碰 stage-0 的 IR。

| 函数 | 职责 |
|---|---|
| `dns_build_query(name)` | 拼 A 记录查询：12 字节头 + QNAME 标签编码 + QTYPE/QCLASS |
| `dns_parse_a(msg)` | 解应答：校验 ID/QR/RCODE/ANCOUNT，跳过 Question，扫 Answer 找 TYPE=1 且 RDLENGTH=4 |
| `dns_skip_name(msg, off, len)` | 跳过名字（含 `0xC0` 压缩指针），所有越界返回 -1 |
| `dns_ip4_str(ip)` | 网络序 u32 → 点分字符串 |
| `dns_resolv_ns(text)` | 从 resolv.conf **内容**取第一个 `nameserver` |
| `dns_resolve(name)` | 端到端：字面量快路径 → 读 resolv.conf → UDP 查 53 → 解出 IP |

### 为什么 `dns_resolv_ns` 吃文本而不是自己读文件

文件读取（`openat` + `read`）在不同后端不一样，而**解析**是纯函数。
把它做成"吃文本"就能在测试里喂固定夹具，也让它能被 Windows 侧复用。
读文件的那一步放在 `dns_resolve` 里（用内建 `read_text`）。

### 安全：不信任报文里的任何长度

所有偏移都按报文实际长度校验，任何越界返回 0（解析失败）。名字压缩指针
只跟一跳（`dns_skip_name` 遇到 `>= 0xC0` 直接返回 `p+2`）——这既防了
"指针环"导致的死循环，也够用：Answer 段的 name 通常是 `0xC00C` 指回 Question。

## 验证：差分对拍 + 真实查询

### 差分测试 `tests/dns_test.py`（PASS=31 FAIL=0）

Python 侧**完全独立**地拼报文、解报文（不调用任何 Quelmara 代码），两侧对
同一批输入产出可比的结论：

| 组 | 用例 | 结果 |
|---|---|---|
| `dns_build_query` 合法名 | `example.com` / `a.b` / 单标签 / 5 层 / 63 字符长标签 | 逐字节一致 |
| `dns_build_query` 非法名 | 空名 / `.` / `a..b` / `.a.b` / 超长 / 64 字符标签 | 两侧都判非法 |
| `dns_parse_a` 正向 | 单 A（压缩指针）/ CNAME+A / 两条 A 取第一条 / 两个 Question | 值一致 |
| `dns_parse_a` 负向 | 截断 / ID 不符 / QR=0 / RCODE≠0 / ANCOUNT=0 / RDLENGTH=3 / TXT 记录 / 空串 | 两侧都返回 0 |
| `dns_ip4_str` | `127.0.0.1` / `192.168.1.1` / `255.255.255.255` / 0 | 一致 |
| `dns_resolv_ns` | 多 nameserver 取第一个 / tab 分隔 / 全注释 | 一致 |

### 真实公网查询（容器内 `--network host`）

```
dns_resolve("1.2.3.4")       -> 1.2.3.4          （字面量快路径，不查网）
dns_resolve("example.com")   -> 104.20.23.154    （真实 A 记录）
dns_resolve("cloudflare.com")-> 104.16.132.229
dns_resolve("")              -> （空串）
```

原始报文层面：查询 29 字节发出、应答 61 字节收回、`dns_parse_a` 解出
`2585203816` = `104.20.23.154`（网络序）。

## 顺带的两处改动

| 文件 | 改动 | 为什么 |
|---|---|---|
| `std/net/udp.qma` | `udp_parse_ip` 从私有改成 `pub` + 补 `///` | `dns_resolve` 的快路径要复用它；此前它只在模块内可用 |
| `std/net/dns.qma` | 顶部 `import std.net.udp` | 同上 |

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `std/net/dns.qma` | **新增**（约 330 行 Quelmara，6 个公开函数） |
| `std/net/udp.qma` | `udp_parse_ip` → `pub` + `///` |
| `tests/dns_test.py` | **新增**（31 项差分对拍） |
| `docs/03-stdlib.md` | 模块表新增 `std/net/dns` 行 |
| `docs/07-gaps.md` | §2 DNS 行 ❌ → ✅；§6 P0 第 2 项收口 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/dns_test.py` | **PASS=31 FAIL=0** |
| `dns_resolve("example.com")`（真实公网） | `104.20.23.154` |
| `python tools/stage0/qlm_cli.py doc std --missing` | PASS（67 模块 / 559 公开声明） |
| `python tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- **只查 A 记录（IPv4）**。AAAA 未做——`tcp_listen6` 在 POSIX 上也还没接，
  v6 客户端要两条一起做才有意义（只做 AAAA 会得到一个连不上的地址）。
- **单 nameserver、单次尝试、无超时**。`udp_recvfrom` 是阻塞的，DNS 服务器
  不响应时 `dns_resolve` 会一直挂着。要修得先给 `udp_recvfrom` 加带超时的
  变体（`SO_RCVTIMEO` 或 `poll`），那是运行时层的活。
- **无 search domain / ndots**：传入的必须是完整 FQDN。`ping example` 那种
  短名解析不做。
- **无 EDNS(0) / 无 TCP 回退 / 无 DNSSEC**：都是协议扩展，当前用途不需要。
- **不做 hosts 文件**：`/etc/hosts` 是平台策略层，与 resolv.conf 同属"交给
  调用方"的部分。需要的话在 `dns_resolve` 外面先查一次 hosts 即可。
