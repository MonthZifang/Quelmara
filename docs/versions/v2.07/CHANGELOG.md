# v2.07 — IPv6：TCP 全链路 + 双栈监听（标准库「IPv6」❌ → ✅）

- 日期：2026-10-24
- 任务：用户要求按 `07-gaps.md` §2 的**一条**一次性补成绿——「IPv6」那一行的缺口写的是
  "socket 家族改造（AF_INET6 + sockaddr_in6 + 字面量解析）"。本版把这一条从"要做"做到
  "TCP 全链路可用"：监听、连接、对端地址、文本解析/格式化，一次补齐，同步文档并实测。
- 影响面：运行时（`qlm_native.py` / `qlm_pe.py`）、标准库（`std/net`、新增 `std/net/addr`）、
  测试、基准、文档

## 主事件

**1. 运行时：三条内建 + 一次家族放宽。** 全部只在 x86-64 Windows PE 上（ELF 后端没有
动态链接器，`@ffi` 与 ws2_32 都不可用，与 `tcp_connect` 既有边界一致）。

| 内建 | 做了什么 |
|---|---|
| `tcp_listen6(port)` | `socket(AF_INET6=23, SOCK_STREAM)` + `sockaddr_in6`（28 B：`family\|htons(port)<<16` 写在 w0，`flowinfo`/`addr`/`scope_id` 全 0 = 绑 `::`）+ **`setsockopt(IPPROTO_IPV6=41, IPV6_V6ONLY=27, 0)`**。Windows 默认 `V6ONLY=1`，不关掉就只接 v6；关掉后同一个 socket 同时接 IPv4（内核映射成 `::ffff:a.b.c.d`） |
| `tcp_connect`（改造） | `hints.ai_family` 从 `AF_INET` 放宽到 **`AF_UNSPEC`**；`socket()` 的家族/类型/协议改取 `ai_family`/`ai_socktype`/`ai_protocol`；`sockaddr` 缓冲按 **`ai_addrlen`** 整段 `__memcpy`（v4 16 B / v6 28 B）而不是固定拷 16 B。**失败沿 `ai_next` 回退**——`localhost` 常先给 `::1`，服务端只监听 v4 时若不回溯，等于把原来可用的路径弄丢（t140 第 4 段专测这条） |
| `tcp_peer_raw(fd)` | `getpeername` 的字节视图，固定 20 B：`[0..1]` 端口网络序、`[2]` family（2/23/0）、`[3]` 保留、`[4..19]` 地址。失败时缓冲保持全 0 → family=0，库层按"未知"处理，不在发射器里开失败分支 |

配套：`qlm_pe.py` 的 ws2_32 白名单补 `getpeername` / `getsockname`。

**2. `std/net/addr`（新模块，11 个 API）。** 文本化放在库层而不是发射器——IPv6 要
8 组十六进制 + "::" 压缩，写汇编不值当，也不该占运行时体积。

| 方向 | API |
|---|---|
| 文本 → 字节 | `ip_family(s)`（4 / 6 / 0，域名一律 0）、`ip6_parse(s)`（`::` 压缩最多一处、允许末尾点分四段、组数/组宽严格校验）、`strip_brackets`（`[::1]` → `::1`） |
| 字节 → 文本 | `ip6_format(b)`（RFC 5952：小写、无前导零、最长连续 0 段压 `::`、等长取最左）、`ip4_format(b)` |
| fd 对端 | `peer_raw` / `peer_ip` / `peer_port` / `addr_family` / `addr_port` / `addr_text`（`::ffff:a.b.c.d` 还原成点分——双栈 socket 上 v4 客户端就是这个形态，日志里没人想看映射前缀） |

`std/net` 同步：新增 `listen6`，`connect` 从非 `pub` 改为 `pub`（此前用户在库外根本
调不到客户端连接，只能直接用 `tcp_connect` 内建）。

**3. 顺手逮到一个编译器缺陷（登记不改）。** 写 `std/net/addr` 时把
`str_find_from(s, from, needle)` 的实参写反成 `(s, ".", start)`——`str` 落到 `int`
形参上，编译器**一句不报**，程序当场 SIGSEGV。最小复现已写进 `07-gaps.md` §7.14
（调用点只校验实参**个数**，没有形参类型比对；`str`/`int` 在 IR 里都是 1 个 8 字节槽）。
改类型检查属语言轨，本版只登记。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 内建注册：`tcp_listen6` / `tcp_peer_raw`（+ `uses_peer` 守卫，未用到时零体积）；`__tcp_connect` 重写为 AF_UNSPEC + `ai_addrlen` + `ai_next` 回退（`head` 单独留给 `freeaddrinfo`，中间节点不能直接 free）；新增 `__tcp_listen6`（28 B sockaddr_in6 + 双栈 setsockopt）与 `__tcp_peer_raw`（getpeername + 按 family 分两支拷 4 B / 16 B，`__str_from_mem` 出串）。**清零用 4/3 条 `store` 而不是 `__memset`**——`__memset` 是按需发射的，只用到 `listen6` 的程序会缺符号 |
| `tools/stage0/qlm_pe.py` | ws2_32 白名单 + `getpeername` / `getsockname` |
| `std/net/addr.qma` | **新增**（11 pub / 15 声明，全部带 `///`） |
| `std/net.qma` | 新增 `pub fn listen6`；`connect` 转 `pub` 并补文档（域名 / v4 / v6 字面量都行） |
| `tests/t140_net6.qma` | **新增**：字面量判定 21 组 + 解析/格式化往返 13 组 + 双栈环回 E2E（`::1` 与 `127.0.0.1` 两种客户端、服务端回报 `peer_ip`/`peer_port`）+ `localhost` 家族回退 |
| `tests/run_win_tests.py` | 登记 `t140_net6`（编号避开同期另一条轨已占的 `t129` / `t130`） |
| `bench/net6_bench.qma` | **新增**：connect+close 与 send+recv 往返，v4 / v6 / localhost 三行 |
| `docs/07-gaps.md` | §2 **IPv6 ❌ → ✅ v2.07**（边界：UDP 无 v6、reactor 只绑 v4、Linux 编译期报错、无 zone id）；DNS 行补 `AF_UNSPEC`；§7 新增 **7.14**（实参类型不匹配不报错）；§8 红标清单去掉 IPv6 |
| `docs/03-stdlib.md` | 重新生成（62 模块 / 528 公开函数 / 531 声明，含并行轨同期新增模块）；缺口表补 `std/net/addr` 行，`std/net` 与 `std/net/udp` 两行按新边界改 |
| `docs/06-status.md` | 新增 **§3.19**（IPv6 / 双栈 socket，每行配同机 CPython 基线）；§1 文档门禁口径改 v2.07 |
| `docs/02-language.md` | §7.5 内建表：拆出 `tcp_listen6` / `tcp_connect` / `tcp_peer_raw` 三行，改掉"IPv4 字面量、无域名解析"这条 v1.25 起就过期的说明 |
| `docs/05-toolchain.md` | §5.1 夹具计数（bench 26 → **28**，正向夹具口径改 v2.07 并改名 `t140_net6`） |
| `tools/stage0/qlm_cli.py` | `VERSION` → `2.07.0`（取号时 2.06 已被并行轨占用；那条轨随后又落了 2.08 / 2.09，`VERSION` 现在跟着最新目录走，见文件第 60 行） |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=278 FAIL=1 SKIP=1**（SKIP 仍是 wsl.exe 被沙箱拦；本版新增项 `t140_net6` 通过。**FAIL 是并行轨的收尾项**：`std/timer.qma` 被那条轨重写到能过前端，`tests/lsp_test.py` 的"timer 必须解析失败"期望因此过期——与本版改动无关，已在 `06-status.md` §1 记账） |
| `python tools/stage0/qlm_cli.py run tests/t140_net6.qma --target win` | 退出码 0，打印 `ok t140_net6`（含双栈两家族 + 回退三段） |
| `python tools/stage0/qlm_cli.py run bench/net6_bench.qma --target win` | 见 `06-status.md` §3.19（3 次取中位 + 同机 CPython 基线） |
| `python tools/dev/gen_stdlib_doc.py --check --require-doc` | **PASS：62 个模块 / 528 个公开函数**（含并行轨同期新增的模块） |
| `python tools/stage0/qlm_cli.py doc std --missing` | **PASS：62 个模块 / 531 个公开声明**全部有 `///` |
| `python tools/dev/check_docs.py` / `check_names.py` / `check_origin.py` | 全 PASS |

## 已知边界 / 遗留

- **UDP 没有 v6**：`udp_sendto(fd, ip, port, data)` 的地址是 `u32` 网络序（v1.17 的设计），
  带 v6 要改成 16 字节双字 API（`udp_sendto6(fd, hi, lo, port, data)` 或直接收
  `std/net/addr` 的 16 B 原始串），是一次独立的接口变更，本版不动。
- **`net_serve`（IOCP reactor）仍只绑 v4**：它自己建监听 socket（`AF_INET` + 0.0.0.0），
  与 `tcp_listen6` 是两条独立路径；要双栈得给 `[net]` 加家族开关。
- **Linux 侧仍是编译期报错**：`tcp_connect` / `tcp_listen6` / `tcp_peer_raw` 都只在
  Windows PE 后端实现（ELF 后端无动态链接器）。Linux 的 raw syscall 版本是另一条工作线。
- **`localhost` 回退的代价**：先解析到 `::1` 而服务端只监听 v4 时，要多付一次被拒连接
  （本沙箱 ~2 s，是 WFP 丢 SYN；正常机器 <1 ms）。基准因此不跑这一路，只由测试断言正确性。
- **`tcp_connect` 每次调用都做一次 `WSAStartup` + `getaddrinfo`**：数字字面量 7 µs、
  域名 ~1.3 ms（见 §3.19），还没有连接池/地址缓存；热点客户端要自己缓存 fd 或等
  连接池（§2 的 HTTP 客户端行）。
- **与并行轨的交错**：v2.06（HTTP 服务端 + 中间件，另一条轨）在本版之前落地；本版取号
  时 `VERSION` 已是 2.06.0，故顺延到 **2.07**。`tests/t129_net6.qma` 因与那条轨的
  `t129_ds` 撞号，改名为 `t140_net6.qma`（131–139 留空）。
- **主回归那一条 FAIL 不是本版的**：`std/timer.qma` 被并行轨重写后已能过前端，但
  `tests/lsp_test.py` 的 B 段仍断言"timer 必须解析失败"。修法是那条轨把这一条改成
  正向（`std/http.qma` 他们已经这么改过），本版不越界动它的文件。
- `tests/bad/{derive_enum,derive_f64,refl_dynidx}.qma` 三个失效夹具的删除仍未提交
  （等用户决定去留，与 v2.01 同口径）。
