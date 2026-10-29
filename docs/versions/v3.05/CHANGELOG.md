# v3.05 — DNS 多 nameserver 轮询：第一个挂了不再等于整个解析不可用

- 日期：2026-10-29
- 任务：补 v3.03/v3.04 登记的边界 —— 单 nameserver、单次尝试
- 影响面：标准库（`std/net/dns`）、测试（`tests/dns_test.py` 31 → 38 项）、文档

## 问题：只认第一个 nameserver 是真实的可用性缺陷

v3.03 的 `dns_resolve` 读 `/etc/resolv.conf` 只取**第一个** nameserver。
这在很多真实环境里直接不工作：

| 环境 | resolv.conf 里的第一个 | 实际情况 |
|---|---|---|
| systemd-resolved | `127.0.0.53` | 本地 stub，它自己再转发上游 |
| Docker 容器 | `127.0.0.11` | 内嵌 DNS，宿主机换了网络可能失效 |
| 企业网 | 内网 DNS | 内网 DNS 挂了要回退到公网 |
| 多网卡 | 按网卡顺序 | 某张网卡的 DNS 不可达 |

stub 没起来、内网 DNS 挂了、某个地址被防火墙黑洞——只要第一个不可用，
**整个解析就不可用**，哪怕后面还有三个好的。glibc 的默认行为是依次尝试，
本版对齐它。

## 实现

### 新增 `dns_resolv_all(text) -> vec[str]`

与 `dns_resolv_ns` 共用同一套行扫描规则（注释行 / 前导空白 / 行尾注释），
只是收集**全部** `nameserver` 而不是提前返回第一个。`dns_resolv_ns` 保留
（有"只要一个"的调用方），两者不互相调用——重复那 20 行比抽公共函数更清楚，
因为两者的终止条件不同（一个是 `return`，一个是 `push` 后继续）。

### 新增 `dns_query_ns(ns, q, ms) -> int`

向**单个** nameserver 发查询并解析，返回网络序 u32；超时/失败返回 0。

**每次调用新开 socket 并在结束时关闭**：DNS 是低频操作，复用 fd 省下的开销
抵不上"`SO_RCVTIMEO` 会串到下一次查询"的风险——上次给 300 ms、下次想要
3000 ms 时，复用 fd 就得多设一次，容易漏。

### 新增 `dns_resolve_ex(name, ms_per_ns) -> str`

依次向每个 nameserver 发同一个查询，**第一个成功的胜出**；全部失败返回空串。

**`ms_per_ns` 是每个 nameserver 的超时，不是总预算**。这一点是刻意的：

- 若按总预算摊薄（3 个 ns 共享 3 s，每个 1 s），每个都会在自己的窗口里
  超时，轮询等于没做；
- 按每 ns 独立（3 个 × 3 s，最坏 9 s），每个都有公平机会，代价是最坏
  情况变长。DNS 查询正常在 20–80 ms 返回，最坏路径很少走到。

### `dns_resolve` 改成薄包装

```quelmara
pub fn dns_resolve(name: str) -> str {
    return dns_resolve_ex(name, 3000)
}
```

保留原签名与语义（调用方不用改），内部走轮询版。需要自定义超时用
`dns_resolve_ex`。

## 验证

### 故障切换（真实网络，不可达地址 `192.0.2.1` = TEST-NET-1）

```
dns_query_ns("192.0.2.1", q, 300)  -> 0         （超时）
实测耗时                            -> 305 ms
dns_query_ns("8.8.8.8", q, 3000)   -> 104.20.23.154  （可用）
```

即"第一个挂了 → 返回 0 → 循环继续 → 第二个成功"这条路径是通的。

### 顺序与解析

```
dns_resolv_all("nameserver 192.0.2.1\nnameserver 8.8.8.8\nnameserver 1.1.1.1\n")
  -> 3 个，顺序 192.0.2.1 / 8.8.8.8 / 1.1.1.1
dns_resolve_ex("example.com", 500)  -> 172.66.147.243
dns_resolve("example.com")          -> 172.66.147.243
dns_resolv_all("")                  -> 0 个
dns_resolv_all("# only comment\n")  -> 0 个
```

### 差分测试扩到 38 项

`tests/dns_test.py` 新增 7 项 `dns_resolv_all` 覆盖，全部与 Python 独立
实现逐项对拍：

| 用例 | 内容 |
|---|---|
| multi | 三个 nameserver + 其它指令 |
| one | 单个 + tab 分隔 |
| none | 全注释 |
| empty | 空串 |
| blank | 纯空白行 |
| trailcomment | 行尾 `# primary` 截断 |
| mixed | 注释 + nameserver + search 交错 |

**PASS=38 FAIL=0**

### 回归

| 命令 | 结果 |
|---|---|
| `python tests/dns_test.py` | **PASS=38 FAIL=0** |
| `bash tests/run_native_tests.sh` | 见 `06-status.md` §1 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/net/dns.qma` | 新增 `dns_resolv_all` / `dns_query_ns` / `dns_resolve_ex`；`dns_resolve` 改为轮询薄包装 |
| `tests/dns_test.py` | 新增 `py_resolv_all` 参考实现 + 7 项 `resolvall` 用例 |
| `docs/07-gaps.md` | DNS 行：单 ns → 多 ns 轮询；测试项数 31 → 38 |

## 已知边界 / 遗留

- **只查 A 记录**。AAAA 仍未做——POSIX 的 `tcp_listen6` 也还没接，只做 AAAA
  会得到一个连不上的地址，两条要一起做。
- **无 search domain / ndots**：必须是 FQDN。
- **不做并发查询**：严格串行（一个超时了才试下一个）。glibc 在部分版本里
  并发发首轮，能把最坏延迟从"n × timeout"压到"timeout"。要做得引入
  多 fd + 非阻塞收，是另一个量级的工程。
- **无 EDNS(0) / 无 TCP 回退 / 无 DNSSEC**：协议扩展，当前用途不需要。
- **Windows 侧未实测**：容器里只有 Linux。`dns_query_ns` 走的是
  `udp_recvfrom_to`，那条路径的 Windows 分支已在 v3.04 实现但同样未实测。
