# Quelmara 能力缺口登记册（GAPS）

> 口径：2026-10-21，工作区代码（v1.2 已发布；v1.4 已提交；v1.3 / v1.5 工作区落地待提交）。
> 本文只登记两类东西：**(1) 现在做不到什么**；**(2) 文档说"已做/没做"但代码不是那样**。
> 每条都附复核方式（命令，或 `文件:行`），不写"应该差不多"。
> 权威分工：`CHANGELOG.md` = 版本特性与回归项数；**本文 = 能力边界**；`HANDOVER.md` = 当前快照与排期。

**实测基线（本轮跑过）**

| 项 | 结果 | 命令 |
|---|---|---|
| Windows PE 回归 | **113 项全绿**（FAIL=0，SKIP=1：WSL 被沙箱拦） | `python tests/run_win_tests.py` |
| 自举进度 | **2/9**，自举 1770 行 / stage-0 18909 行 = **8.6%** | `python tools/dev/selfhost_status.py` |
| 函数体对拍 | dump 一致 **94** / 分叉 **636** / SKIP 不同步 25 | `python tests/bodydiff.py` |
| vec[Struct] | **可用**（`vecagg ok`） | `python tools/stage0/qlm_cli.py run tests/t37_vecagg.qma --target win` |

---

## 0. 先纠正三条过期结论（重要）

外部评估（包括本轮提问）基本是从文档反推代码，而文档比代码落后了 2–3 个版本。三条被引用来论证"能力缺失"的说法，实测不成立：

| 说法 | 出处 | 实测 | 判定 |
|---|---|---|---|
| "`import` 目前只做语法保留" | `docs/ORIGINALITY.md` §3 对照表 | v1.3 已实装扁平合并：递归加载 `std/` 与同目录 `.qma`，顶层 fn/struct/enum/test 合并，名字冲突/循环 import/被导入文件定义 main 一律报错；两遍解析让顶层 `const` 跨模块可见（`tools/stage0/qlm.py:1146` `load_program`）。`std/http.qma` 自己就靠 `import std.net.core` / `std.mem` 组装 | **文档过期** |
| "`vec[Struct]` 不支持，元素仅标量" | `docs/SELFHOST.md` §5、`HANDOVER.md` §1 表、`SPEC.md` §9、`qlm.py:490` 注释（本轮已修） | 元素类型支持 **标量 / struct / enum**（`vec_elem_tag` → `('agg', Name)`，`_vec_ewords` 算槽数，`qlm.py:1428/1444`）；`tests/t37_vecagg.qma` 覆盖 push/get/set/pop/for-in/扩容搬运，实测通过。元素按值拷贝进出，改副本不影响表内元素 | **文档过期**（代码是好的） |
| "str 零结尾、`len` 是 O(n)、无长度前缀" | `README.md` §7、`SPEC.md` §1.3 与 §2 类型表 | v1.5.1 已改长度前缀 ABI：值指向 `[len][bytes][NUL]`，`len`/`s[i]` O(1)（`qlm_native.py:665`）；16KB 逐字节扫描 85.9ms → 22µs | **文档过期** |

结论两句话：

1. **提问清单里"最要命"的两条（vec[Struct]、FFI），只有 FFI 成立。** vec[Struct] 是文档债，不是代码债。
2. **但文档债本身就是缺陷。** 它让评估者（和未来的自己）系统性低估项目，也会让新写的库绕远路（`SELFHOST §5` 教人"用三个平行 vec 硬凑"，而正确写法早就能用了）。本轮已修掉 §0 表格涉及的七份文档（ORIGINALITY / SELFHOST / HANDOVER / SPEC / README / GUIDE / TUTORIAL）+ CHANGELOG 版本说明 + 一处代码注释，并加了常驻门禁 `tools/dev/check_docs.py`（已进 CI），防止同类漂移复发。

---

## 1. 评估口径：三层成熟度严重不匹配

不看文档、只看代码与实测，分层结论是：

| 层 | 成熟度 | 证据 |
|---|---|---|
| **后端/代码生成** | 像 1.0 | 手写 x86_64 ModRM/REX 编码 + ELF64/PE32+ 写出 + IOCP reactor + 7 项优化（有基准）+ 96 项 PE 回归 + 4 套对拍脚本（lex/parse/IR/emit）+ 函数体 bodydiff。这块比多数 hobby 编译器扎实一个数量级 |
| **语言表达力** | 像 0.4 | 无用户泛型 / trait / 真整数宽度 / FFI / 闭包；`map` 值只能标量；模块是扁平合并；`let` 不能写类型标注 |
| **生态与工程化** | 像 0.1 | 标准库只有协议栈（HTTP/WS/SSE/SHA-1/base64/槽位层），业务胶水（JSON/字符串/URL/压缩/TLS/FS/时间/随机）几乎为零；无包管理、无调试信息、无 LSP、自举 2/9 |

**这是当前最大的结构性风险**：后端继续投入的边际收益，已经低于补语言与标准库的边际收益。一个能扛十万连接的 reactor，配上不能解析 JSON、不能写日志时间戳、不能读目录的库，仍然交付不了一个真实服务。

另一个真实短板是**文档与代码的同步机制缺失**：现在靠人肉记忆，一次功能落地就制造 4 处漂移。本文把"每条断言附复核命令"作为纪律，理由就在这。

---

## 2. 语言与类型系统

| 能力 | 现状（证据） | 影响 | 现有绕过 | 优先级 |
|---|---|---|---|---|
| **用户自定义泛型** | ❌ 只有 `option[T]` / `result[T,E]` 两个硬编码白名单（`qlm.py:722-746`），T/E 限 int/i8..u64/bool/str | 写不了通用容器/算法，每种类型复制一遍 | 复制粘贴 + 命名前缀 | P2 |
| **trait / interface / 多态** | 🟡 **v1.8 有 `interface` + `impl`**：契约声明、实现完整性/签名检查、方法调用语法，**静态分发**（`tests/t52_iface.qma`）。**动态分发未实现**：`let s: Shape = Circle{..}` 不支持，无 vtable，`vec[Shape]` 不行 | 有抽象**契约**，但没有**多态**；跨类型容器仍要函数指针手搓 | 函数值 + `static_word` 手搓分派 | **P0（语言层最大缺口）** |
| **真实整数宽度** | ✅ **v1.8 已实现**：`let x: u8` / 形参 / 返回值 / 赋值四个边界截断（uN 零扩展、iN 符号扩展），表达式内部按 C 提升。`tests/t49_width.qma` 覆盖 14 条断言。**仍缺**：struct 字段存值不截断、`vec[u8]` 仍是 8 字节槽（`docs/LANG.md §1.2`） | 协议/二进制格式/哈希/编码器可以直接写宽度类型 | — | ✅ |
| **局部类型标注** | 🟡 **v1.8 支持 `let x: T`**，但只有宽度类型参与语义（截断）；非宽度标注只作可读性，不做类型检查 | 仍不是完整类型检查器，写错类型不会报错 | 注释 / 单测 | **P1**（接 typeck） |
| **闭包 / 函数值** | 🟡 函数名可作值，`callr` 间接调用（v1.4）。限制：**最多 6 个实参**、实参不能是 struct/slice（只能标量/str）、返回值按标量处理、**无捕获**（`qlm_native.py:2314-2330`） | 回调只能固定签名（`net_serve` 的 handler 就是被这条逼出来的形状） | 全局 `static_word` 传状态 | **P1**（放宽到 8 参 + 允许 struct 指针） |
| **`match` 表达式** | 🟡 语言层 ✅（enum 解构/穷尽性/块臂）；**自举 parser Phase 1 未覆盖**：语句级直接 SKIP，表达式位置（`return match s {..}`）被当标识符，是 bodydiff 636 条分叉的一类（`bootstrap/parser/qlm_parse.qma:933`） | 自举 parser 自己还吃不下自己 | 该函数整体 SKIP | P1（自举主线） |
| **`vec` 容器** | 🟡 元素 = 标量 / struct / enum ✅；**不支持 `vec[vec[T]]`、`vec[map]`**；struct 内嵌套聚合按 1 槽占位（`_vec_ewords` 注释）；句柄语义，无所有权 | 嵌套数据结构（AST 子节点、JSON 数组套数组）建模困难 | 扁平化 + 索引 | **P1** |
| **`map` 容器** | 🟡 K ∈ int/bool/str，**V ∈ int/str**（`map_kv_tag`）；不能 `map[str]Struct` | 配置表/符号表/索引结构受限 | 平行 map / 下标编码 | **P1** |
| **所有权 + 借用检查** | 🟡 **v1.8 只对 `rc[T]` 句柄**做线性检查：use-after-drop / double-free / move-then-use 三类编译错误 + 泄漏编译警告（`tests/bad/own_*.qma`）。**不检查** struct/数组/str 的别名与生命周期，也不查并发数据竞争 | `rc` 之外仍是纪律；不能对外宣称"Rust 那套借用检查" | 文档约定 + 代码评审 | **P1**（扩到 vec/引用） |
| **错误处理** | 🟡 `result[T,E]` 只两变体、载荷限标量；`?` 只接受两个单载荷变体。库层错误只能 **fail-fast 退出进程** 或返回 -1/空串 | 库无法把 errno + 上下文交给调用方；HTTP 服务端只能手写 400/431/501 兜住已知畸形请求，未覆盖路径一律进程退出 | 返回 int 码 + 全局错误字 | **P1** |
| **模块系统** | 🟡 `import` = 扁平合并，**无命名空间 / 可见性 / 版本**。后果已经可见：`std` 全部靠 `http_` / `ws_` / `sse_` / `b64_` 前缀防冲突，`join` 被任务句柄占用后字符串 join 只能改名 | 第三方库无法共存；库作者被迫用命名前缀 | 前缀约定 | **P1** |
| **作用域清理** | ❌ 无 `defer` / RAII / `Drop`；只有 `arena { }` 整块回卷 | fd、锁、缓冲的释放全靠手写；错误路径易漏 | 手写 close + arena | P2 |
| **标准语法便利** | ❌ 无字符串插值/格式化；无 `for` 自定义迭代协议（只有 range / map / vec）；无 `switch`；无位域；无 `?` 之外的错误捕获 | 业务代码冗长 | 手工 `+` 拼接（O(n²)，已有 `str_from_bytes` 对症） | P1（format） |

---

## 3. 标准库（用户重点）

### 3.1 现有的全部（实测清单，9 个模块）

| 模块 | 函数 | 备注 |
|---|---|---|
| `std/core.qma` | `abs` `max2` `min2` `pow2k` | 只有 4 个函数 |
| `std/mem.qma` | `slab_*`（6）`fdtab_*`（7）`buf_*`（13） | 槽位/开放寻址/缓冲；`buf_put_str`、`buf_str` 可当字符串构造器用 |
| `std/sha1.qma` | `sha1_str` `sha1_hex` | **仅 SHA-1**（WS 握手用） |
| `std/b64.qma` | `b64_encode` `b64_decode_into` `b64_dec_max` | 无 base64url、无 hex |
| `std/net.qma` | `listen` `accept` `send` `recv` `close_conn` `serve` | 阻塞过程式；`serve` = `net_serve`（仅 Windows IOCP） |
| `std/net/core.qma` | `conn_*`（18） | 640 B/连接槽位层 |
| `std/http.qma` | 服务端 30+：`http_serve` `http_respond*` `http_method/path/header/body*` `http_text/html/json` | **服务端 only**，无客户端 |
| `std/ws.qma` | `ws_serve*` `ws_send*` `ws_ping` `ws_close` | RFC 6455 服务端 |
| `std/sse.qma` | `sse_serve*` `sse_event*` `sse_broadcast*` `sse_retry` `sse_comment` | W3C event-stream |

> **命名陷阱**：`http_json(fd, status, body)` **不是** JSON 序列化——它只是把 `Content-Type` 设成 `application/json`（`std/http.qma:582`）。这是"看起来有、其实没有"的典型，读文档的人极易误判。

### 3.2 "HTTP 服务能对外交付"的五件套 —— 四件已交付、TLS 走完 Phase A 的 2/3

| 件 | 现状 | 为什么是硬需求 | 最小 API 草案（适配当前语言能力） |
|---|---|---|---|
| **JSON** | ✅ **v1.6 已交付** (`std/json.qma`) | 现代 HTTP API 的数据交换基本盘 | 已实现 DOM 式：`json_parse/json_ok/json_error_pos`、`json_obj_get/json_arr_at`、`json_str/json_int/json_num_raw`、builder（`json_begin_obj/json_key_*/json_end_obj/json_done`）。**仍不能**做 `to_json<T>`（无泛型/反射），见 `docs/P0_LIBS.md §5` |
| **字符串工具** | ✅ **v1.6 已交付** (`std/str.qma`，26 个函数) | 业务代码 80% 是字符串处理 | `str_find/rfind/contains/count`、`str_starts_with/ends_with/eq_ci`、`str_trim*`、`str_split/split_n/lines`、`str_join/replace/replace_first`、`str_upper/lower/repeat/pad_left`、`str_slice/left/right/strip_prefix/suffix`。仍是 ASCII 字节语义，`str_format` 未做（无可变参数） |
| **URL** | ✅ **v1.6 已交付** (`std/url.qma`) | HTTP 服务端必备：路由、query 取值、重定向拼接 | `url_scheme/host/port/path/query/fragment`、`url_query_get`、`url_decode(_path)`、`url_encode(_query)`、`url_join_query`；IPv6 字面量已覆盖 |
| **gzip / deflate** | ✅ **v1.6 已交付** (`std/gzip.qma`) | `Content-Encoding` 事实标准 | `crc32` / `deflate_raw`（LZ77 + 固定 Huffman）/ `gzip_encode` / `gzip_hex`；HTTP 侧 `http_accepts_gzip` / `http_respond_gzip` / `http_respond_auto`。**解码（inflate）未做**；1 MiB 重复文本 137×、~9 MB/s |
| **TLS** | 🟡 **Phase A 2/3**：SHA-256+HMAC ✅、AES-128-GCM ✅、X25519 ❌；握手/记录层/X.509 ❌ | 没有 https/wss 进不了现代 Web | 见 `docs/TLS.md`。X25519 的前置是 255 位域算术（先做 `std/u128` 的 limb 运算）；握手要 X.509 最小子集 + 状态机 |

### 3.3 其余缺口（按"真实应用会撞到"的顺序）

| 类别 | 缺什么 | 撞到什么场景 | 现有替代 |
|---|---|---|---|
| **时间** | 只有 `now_ns()`（单调纳秒，`qlm_native.py:1968`）。**无** wall clock、无日期格式化、无时区、**无 `sleep`**（全仓无 sleep 内建） | 日志时间戳、缓存过期、重试退避、定时任务、限流窗口 | 无。连"睡 100ms"都做不到 |
| **文件系统** | 只有 `read_text` / `write_text`。**无** `stat` / `exists` / `mkdir` / `listdir` / `remove` / `rename` / `append` / `seek` | 配置目录扫描、日志轮转、静态文件服务、临时文件、断点续传 | 无 |
| **进程 / 环境** | 只有 `args()` / `arg(i)`。**无** `getenv`、无子进程、无退出码获取、无 stdin 读取 | CLI 工具、读取 `PORT`/`HOME`、调用外部命令（git/ffmpeg）、管道 | 无 |
| **随机数** | ❌ 零。无 PRNG、无 CSPRNG | 会话 ID、CSRF token、抽样、测试数据、退避抖动 | 只能用 `now_ns()` 当弱种子（不安全，不可用于 token） |
| **排序 / 查找** | ❌ 零。无 `sort`、无 `bsearch`、无通用比较器 | 排行榜、去重、按 key 输出、二分 | 手写冒泡/插入排序 |
| **日志** | 只有 `eprint`。无级别、无 tag、无时间戳、无结构化 | 生产可观测性；出问题只能靠 `print` 猜 | 手工拼前缀 |
| **正则** | ❌ 零 | 文本清洗、路由匹配、日志解析 | 手写字符扫描（`std/mem` 的 `buf_find` 只能找子串） |
| **编码** | 无 UTF-8 解码（一切按字节）、无 hex 编解码、无 base64url、无 URL 编码 | 中文长度/截断、`\uXXXX`、JWT、哈希十六进制输出（现靠手写） | 手写循环 |
| **数学** | `float` 只有四则/比较/`to_int`/`to_str`。**无** `sqrt` / `pow` / `sin` / `log` / `floor` | 图形、统计、物理、任何几何计算 | 手写牛顿迭代 |
| **哈希 / 校验** | 只有 SHA-1。无 SHA-256、MD5、CRC32、FNV | ETag、签名、去重、完整性校验 | 无 |
| **数据结构** | `vec` / `map` 之外全无：无 `set`、`stack`、`queue`、`deque`、`heap`、LRU | 去重、任务队列、优先调度、缓存 | 用 map 模拟 set，其余手写 |
| **持久化** | 无 SQLite / 无键值存储 / 无序列化格式 | 任何要存数据的应用 | 手写文本 + `read_text` |
| **CLI 参数** | 有 `args()`，无 flag 解析（`-x` / `--long` / `--k=v` / 子命令） | 工具类应用的入口 | 手写 `if s == "-v"` 链 |
| **国际化** | 无 locale、无 Unicode 分类、无大小写折叠 | 多语言输出 | 无 |

### 3.4 结论

**五件套 4/5 已交付（JSON / 字符串 / URL / gzip），TLS 完成密码学地基的 2/3。** 服务端已经能收发 JSON、处理 query、按 `Accept-Encoding` 压缩响应；**唯一还卡对外交付的是 https/wss**：TLS 缺 X25519 与记录层/握手，而这两块都在密码学与协议实现侧，不在语言侧。

---

## 4. 网络 / 协议层

| 层 | 现状 | 缺什么 / 边界 | 证据 |
|---|---|---|---|
| TCP（阻塞 API） | ✅ v1.3 | **只支持 IPv4 字面量**：`inet_addr` 解析，导入表里没有 `gethostbyname`/`getaddrinfo` ⇒ **不支持域名**（提问里的推测成立，已确证）。无 IPv6 | `qlm_pe.py:149-151` `WS2_32_FUNCS` |
| IOCP reactor | ✅ v1.4，**仅 Windows PE** | 非 Windows 目标**显式拒绝**（`net_serve` 报"当前只在 Windows PE 后端实现"）。Linux 侧仍只有 C 后端的 epoll/io_uring demo，自研后端无 epoll | `qlm_native.py:2136-2147` |
| Reactor 并发模型 | 🟡 单 acceptor + N 个 IOCP 工作线程（`io_threads`，0 = 核数） | **不是多 reactor**；Windows 路径**只对已连接 socket 设了 TCP_NODELAY**，监听 socket 没有 `SO_REUSEADDR`/`SO_REUSEPORT`（`Quelmara.toml` 的 `reuse_port` 只对 C 后端 epoll 生效，`qlm.py:2433`）⇒ 端口处于 TIME_WAIT 时重启会 bind 失败；多队列/多端口/CPU 亲和未做 | `qlm_native.py:4776-4786`、`:5052-5055`（唯一 setsockopt） |
| 槽位层 | ✅ 640 B/连接，十万连接 64 MB；rec 惰性分配，短连接 O(1) 复用 | 百万**长**连接需 `recv_buffer=512` → 总账 ≈1.2 GB；`slot_words` 紧凑档未进 API（PERF §4 待办） | `docs/PERF.md §3` |
| HTTP/1.1 服务端 | ✅ v1.5：keep-alive + 流水线 + Content-Length | `Transfer-Encoding: chunked` 请求体 → **501**；无路由/中间件（只有 `on_request` 单回调，path 匹配要自己写 if 链）；无静态文件服务/MIME/cookie/session/multipart | `std/http.qma:68`、CHANGELOG v1.5 |
| HTTP 客户端 | ❌ | 出站 https 明确"另排"（TLS.md Phase C） | `docs/TLS.md:59-61` |
| WebSocket / SSE | ✅ 服务端（RFC 6455 / W3C） | 客户端 ❌；无 permessage-deflate（依赖 gzip） | `std/ws.qma`、`std/sse.qma` |
| TLS | 🟡 | Phase A 2/3（sha256/hmac + aes-gcm）；X25519、记录层、握手、X.509 未做 | `docs/TLS.md` |
| DNS | ❌ | 无解析器、无 getaddrinfo，无 UDP 承载 | 同上 |
| UDP | ❌ | 无 `SOCK_DGRAM` 路径（只有 TCP 的 send/recv） | `qlm_native.py:2087` |
| HTTP/2、QUIC | ❌ | 无 | — |
| 压测 | 🟡 keep-alive 流水线 2000 请求 / 0.001s（沙箱口径，绝对值不可信）；短连接基线被沙箱注入污染 | 百万连接全量压测未做（需干净环境 + 多源 IP） | `docs/PERF.md §3-4` |
| 协议库回归 | ❌ 未进 CI | 本轮互操作是 Python 客户端手跑；`tests/netlibs_test.py` 待写 | `HANDOVER.md` §4 |

---

## 5. 工具链 / 工程化

| 项 | 状态 | 说明 |
|---|---|---|
| **包管理 / 依赖** | ❌ | `Quelmara.toml` 无 `[deps]`；`import` 只查 `std/` 与同目录 ⇒ 第三方库无从获取、无法锁版本、无法离线复现 |
| **库归档 `.qla`** | 🚧 规划中 | `docs/EXTENSIONS.md:17` 写明"`quelmara lib`（规划中）"；无目标文件格式 ⇒ 无法增量编译/分发二进制库 |
| **调试器** | 🟡 很弱 | `tools/stage0/qlm_dbg.py` 是 Windows ctypes 调试小工具（打印加载基址/线程/异常码/RVA），**不是语言级调试器**；无 DWARF/PDB、无源码断点、无变量查看；平时靠 `readelf`/`capstone`/`--dump-ir` |
| **LSP / 编辑器支持** | ❌ | 无补全、无跳转、无内联诊断（只有 `qlm_fmt` 格式化器） |
| **文档生成** | ❌ | 无 doc comment 语法、无 API 文档生成 |
| **自举闭环** | 🟡 2/9 | 词法 ✅、声明级 parser ✅；函数体 94/636 分叉；类型推断/优化/编码器/ELF/PE/A64 仍是 stage-0 骨架；三轮固定点闭环未开始 |
| **LICM** | 🟡 默认禁用 | x64 线性扫描分配器布局敏感段错误未根修（`QLM_ENABLE_LICM=1` 可开；A64 模拟器同程序全绿，纯 x64 分配器问题）。**这是优化器里唯一"已知会崩"的开关** |
| **CI** | ✅ | `.github/workflows/ci.yml`：Linux（门禁 + 四套对拍 + 五套回归 + A64 模拟器 + io_uring）+ Windows（门禁 + PE 回归 + 对拍 + `test --targets all`） |
| **平台覆盖** | 🟡 | Windows PE ✅ / Linux ELF（构建级，本机无 WSL 无法执行）/ AArch64 模拟器 🟡 / macOS-Mach-O ❌ / wasm ❌ / Android ❌ |
| **Windows C 后端执行验证** | ❌ | 本机无 gcc/clang，C 链只能验证"生成" |
| **版本语义** | 🟡 | `CHANGELOG.md` 里 **两个"未发布"节并存**（v1.5 在前、v1.3 在后），v1.4 已提交但 v1.3 未提交 ⇒ 版本号与提交线不连续，读的人会误判当前版本 |

---

## 6. 优先级：把"分水岭"拆成可执行顺序

排序原则：**先让"一个真实服务能上线"，再让"语言能撑住中型程序"，最后才是生态。**

### P0 — v1.6「能对外交付一个 JSON API」

1. `std/sha256.qma`（SHA-256 + HMAC-SHA256）——TLS 第一步，也可独立用于 ETag/签名；骨架照抄 `std/sha1.qma`，对拍 Python `hashlib`
2. `std/json.qma`——DOM 式 parse + emit（object/array/string/number/bool/null），明确"无泛型编解码"
3. `std/str.qma`——`str_split/join/trim/find/replace/starts_with/ends_with/upper/lower/repeat/format`，全部 `str_` 前缀
4. `std/url.qma`——parse + encode/decode + query 取值
5. `std/gzip.qma`——`crc32` + `deflate_raw`（固定 Huffman）+ gzip 包装；`std/http.qma` 加 `Accept-Encoding` 协商与 `Content-Encoding`
6. **文件系统最小集**——`fs_exists/fs_size/fs_mkdir/fs_listdir/fs_remove/fs_rename/fs_append`
7. **时间最小集**——`now_ms()`（wall clock）、`sleep_ms(n)`、`time_iso8601(ms)`
8. 验收：`examples/api_demo.qma` —— 一个带路由、JSON 请求/响应、gzip、静态文件、日志时间戳的 200 行服务，Python 客户端全绿 + 回归项入 CI

### P1 — v1.7「语言能撑住中型程序」

- **真整数宽度**（`u8/u16/u32` 截断与回绕）——协议/编码/哈希的前提；同时补 `let x: T` 局部标注
- **容器扩展**：`map[str]Struct`、`vec[vec[T]]`、嵌套聚合真实布局（去掉"1 槽占位"）
- **函数值放宽**：允许 struct/slice 实参、8 参、允许把函数值存进 struct 字段（回调表）
- **错误处理**：`result` 允许 struct 载荷 + 库层错误对象（`errno` + 消息），停止"库函数只能退出进程"
- **命名空间**：至少 `mod` 前缀 + `pub`，止住 `http_`/`ws_` 前缀膨胀
- **TLS Phase B**（记录层 + TLS 1.3 握手 + 自签 X.509 子集）→ `https_serve` / `wss_serve`
- **HTTP 客户端 + DNS + UDP**（三者互相依赖：DNS 需要 UDP）
- **包管理最小可用**：`[deps]` + 目录式依赖 + `.qla` 打包
- `tests/netlibs_test.py` 入 CI；百万连接压测（干净环境 + 多源 IP）

### P2 — v2.0「生态」

- 用户自定义泛型 → trait/interface → 所有权/借用检查（顺序不能反：泛型是 trait 的前置，借用检查是泛型容器的前置）
- **FFI**：`@extern("C")` 打通自研后端。已有基础：PE 导入表已支持多 DLL 分组（kernel32/ws2_32），把白名单机制推广到"用户声明库 + 符号白名单"是可行路径；Linux 侧需要 `.dynamic` + PLT/GOT 或 `dlopen` 路径
- 调试信息（DWARF/PDB）→ LSP → 文档生成
- 自举 9/9 + 三轮固定点闭环
- macOS Mach-O + kqueue

---

## 6.5 误编译：v1.8 修掉的三个（已转正为回归）

这三条曾经都是**必现**的代码 bug，v1.8 全部修掉并与 `tests/t53_regress.qma` 绑定。
留档的目的不是自夸，而是**记录根因与排查手法**——同类问题还会再来。

| # | 症状 | 根因（真实） | 修法 |
|---|---|---|---|
| 1 | 循环内 `substr` 的长度来自函数调用结果、结果又 push 进 `vec[str]` → 越界/错串（`--no-opt` 正常） | **内联路径把栈偏移当寄存器号**：`a_reg` 在溢出时是 `[rbp-8]` 的偏移 `8`，与 `R8` 的编号 `8` 相等，于是「a 已在 dst 寄存器」判断误判为真、跳过 fetch | `qlm_native.py::gen_bin` 区分 `("r", n)` 与 `("m", off)` |
| 2 | `"\xNN"`（≥0x80）被当 Unicode 码点，再按 UTF-8 编码（`"\xe4"` → 2 字节） | 词法器 `chr(b)` 造出 U+00E4，发射时 `encode("utf-8")` 又编一次 | 词法器用 surrogateescape 区（U+DC80..U+DCFF）承载原始字节，发射端 `encode("utf-8", "surrogateescape")` |
| 3 | 循环内**一个表达式里两次调用 + 下标** → 结果整体偏移 | 同 #1（两个调用点让 dst 恰好分到同一个寄存器号） | 同 #1 |

**一条被误判的（教训值得反复看）**：曾以为 `len(f(x))`（f 返回 `vec[T]`）会段错误，
最小化后不复现。真实原因是库代码把 `mem_load64` 的**字节偏移当槽索引**（应 ×8），
写到 88 字节块之外、污染了堆，崩溃点随机漂移。教训：
**看到「随机位置段错误」，先怀疑自己越界写，再怀疑编译器。**

排查手法（本轮验证有效，按顺序用）：
1. `--no-opt` 对照 —— 区分「优化器错」与「codegen 错」；
2. `QLM_SKIP_PASSES=<pass>` 逐 pass 跳过 —— 单 pass 不背锅时，指向分配器；
3. `QLM_NO_INLINE=1` —— 排除内联；
4. `eprint` 二分插桩 —— 定位到具体语句（注意插桩本身会改变寄存器布局，可能「修好」症状）；
5. 最小化到 30 行以内仍复现，才算编译器 bug；否则先查自己的缓冲区边界。

### 6.5.1 仍存在的约束（不是 bug，是没做的优化）

- **LICM 默认关闭**：x64 分配器布局敏感的段错误未根修（`QLM_ENABLE_LICM=1` 可开）；
- `@simd` 只覆盖单一归约形状，不是向量化器；
- 新增 IR 指令（`trunc` / `vsum`）必须同时登记到 `vreg_mentions`、`_map_ins`、`_EFF`
  —— 漏一处就是「开优化才错」的静默误编译。本轮 `vsum` 被调度器挪到数组初始化之前、
  归约少一个元素，就是这么来的。

---

## 7. 复核方法（任何人可重跑）

```bash
# 回归与自举口径
python tests/run_win_tests.py            # 期望 PASS=96 FAIL=0 SKIP=1
python tools/dev/selfhost_status.py      # 期望 组件自举 2/9，1770/18909 行
python tests/bodydiff.py                 # 期望 dump 一致 94 / 分叉 636
python tests/lexdiff.py                  # 期望 92/92
python tests/parsediff.py                # 期望 87/87

# vec[Struct] 到底支不支持
python tools/stage0/qlm_cli.py run tests/t37_vecagg.qma --target win   # vecagg ok

# 整数宽度到底有没有语义（当前：没有）
printf 'fn f(x: u8) -> int { return x + 300 }\nfn main() { print(f(300)) }\n' > /tmp/w.qma
python tools/stage0/qlm_cli.py run /tmp/w.qma --target win             # 打印 600（u8 应为 44）

# 域名解析到底有没有（当前：没有）
grep -n "WS2_32_FUNCS" -A 3 tools/stage0/qlm_pe.py                     # 无 gethostbyname/getaddrinfo

# 标准库到底有什么
for f in std/*.qma std/net/*.qma; do echo "== $f"; grep -c "^fn " "$f"; done

# 文档漂移门禁（过期断言 / GAPS.md 是否被入口文档链接）
python tools/dev/check_docs.py
```

---

## 8. 维护约定

1. **改代码必须同步改本文**：任何"支持/不支持"的翻转，同一次提交里更新对应行 + 复核命令；否则下一个人会重新踩一遍文档债。
2. **文档里的能力断言必须可验证**：写"支持 X"就附 `文件:行` 或一条命令；写不出证据的，标 🚧（规范已定、实现未做），不要写 ✅。
3. **`docs/TLS.md` 与本文 §4 是同一件事的两面**：TLS 状态变化先改 TLS.md，再改本文 §4/§6。
4. **数字口径**：回归项数、自举行数、对拍分叉数随版本变化，本文给出的是 2026-10-21 实测值；版本特性的权威记录仍在 `CHANGELOG.md`。
5. **门禁**：`python tools/dev/check_docs.py` 已进 CI（两个平台都跑）。它拦住 §0 那类过期断言（`import 只做语法保留` / `元素仅标量` / `vec[Struct] 暂不支持` / `没有长度前缀`），并强制 README / HANDOVER / SPEC 链接本文。新发现一种漂移，就把短语加进脚本的 `STALE` 表——**别只改文档不改门禁**。
