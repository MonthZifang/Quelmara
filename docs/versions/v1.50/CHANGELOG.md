# v1.50 — HTTP 客户端：std/httpc + std/httpc_net（标准库）

- 日期：2026-10-23
- 任务：标准库轨第二轮——07-gaps §2「HTTP 客户端」行翻绿：URL 拆分、
  请求构造、响应解析（content-length / chunked / 读到底）、重定向判定，
  加传输层（httpc_get / httpc_get_tls / httpc_get_follow）。
- 影响面：`std/httpc.qma`（新增，纯函数核心）、`std/httpc_net.qma`（新增，
  Windows 传输层）、`tests/t92_httpc.qma`（新增）、`tests/run_win_tests.py`
  （注册）、`docs/03-stdlib.md`（重生成，41→43 模块）、`docs/06-status.md`
  （PASS=158→159）、`docs/07-gaps.md`（§2 HTTP 客户端行）、
  `tools/dev/gen_stdlib_doc.py`（DESC 登记两个新模块）、
  `tools/stage0/qlm_cli.py`（VERSION 1.49.0 → 1.50.0）

## 为什么是它

07-gaps §2 与 HANDOFF §8.4 都把它列为标准库下一顺位（"调用第三方 API"）。
v1.47 的数学是"纯计算开轨"；本轮上真实 I/O 链路。关键设计决定：
**解析核心与传输层分文件**——httpc.qma 零 socket 依赖（Linux/CI 可完整
构建测试），httpc_net.qma 才依赖 tcp_connect 的 getaddrinfo（只编译于
Windows PE）。这样 loopback E2E 之外，纯解析部分在任意平台都可回归。

版本号：v1.48 被语言轨 defer（bb5e35e）占用、v1.49 被其 f64 打印修复
（在途）占用——两轮撞号均顺延；本轮取 v1.50。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/httpc.qma` | **新增**（纯函数，约 300 行）：`httpc_split_url`（scheme/host/port/path，缺省值处理）、`httpc_build_request`（请求行 + Host + User-Agent + Connection + 自定义头 + Content-Length）、`httpc_parse_response`（status/reason/head/body/complete/chunked 六字段；content-length 完整与不足、chunked 多块与扩展、无定长读到底、头未收全返 -1）、`httpc_header`（大小写不敏感）、`httpc_redirect`（3xx + Location 解析：绝对/绝对路径/相对）、`httpc_bad_response`。内部：`_dechunk`（chunked 解码，数据不完整回已到部分）、`_parse_hex`、`_hexval` |
| `std/httpc_net.qma` | **新增**（Windows 传输层）：`httpc_get`（http 走 tcp_connect，https 转 TLS）、`httpc_get_tls`（std/tls_net，seq 从 0 维护）、`httpc_get_follow`（最多 max_hops 跳，超出返回最后 3xx） |
| `tests/t92_httpc.qma` | **新增**（约 60 断言）：URL 拆分 5 组、请求构造 6 组、罐头响应解析 8 组（含 chunked 扩展/不完整/无定长/非法 status line）、头取值大小写、重定向 5 组、**loopback E2E**（spawn 阻塞式服务线程 + tcp_connect 127.0.0.1，定长 + chunked 两条真实响应走完 httpc_get 全链路） |
| `tests/run_win_tests.py` | 注册 `case_selfcheck("t92_httpc", ...)` |
| `docs/03-stdlib.md` | 重生成（43 模块 / 305 公开函数） |
| `docs/06-status.md` | 主回归 PASS=158 → PASS=159 |
| `docs/07-gaps.md` | §2 HTTP 客户端行 ✅ v1.50；遗留登记：连接池/流水线、自动解压、HTTP/2、Linux DNS |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 std/httpc.qma 与 std/httpc_net.qma |
| `tools/stage0/qlm_cli.py` | VERSION 1.49.0 → 1.50.0 |

## 实现要点

- **解析是缓冲区的纯函数**：`httpc_parse_response(buf)` 可反复对增长中的
  buf 调用——不完整时 complete=0 且 body 回已到部分（content-length 不足与
  chunked 数据不足同语义），续收后整体重试自然拼齐。传输层的收包循环因此
  极简：recv → parse → complete 即断。
- **chunked**：支持 chunk 扩展（`5;ext=1`）、多块拼接、0 块收尾；trailer
  忽略；size 行/数据/结尾 CRLF 任一不完整即停并回部分。
- **重定向只解析不跟随**（httpc_redirect）；跟随在传输层
  （httpc_get_follow，GET 语义无 303 歧义）；相对 Location 不解析 `../`
  （简化实现，已登记）。
- **E2E 不碰外网**：t92 用 `spawn` 起阻塞式服务线程（std/net 的
  listen/accept/send/recv），客户端 tcp_connect 127.0.0.1——两条真实响应
  （定长 + chunked）走完整链路，零网络依赖、可重复。
- **踩坑记录**：① vec 下标必须 `.get(i)`（`hdrs[i]` 编译期报"下标只能用
  于定长数组、切片或 str"）；② `s[i]` 不能直接做函数实参
  （`_hexval(s[i])` 报同上），先落 `let ch = s[i]`；③ 非 pub struct 可作
  pub fn 返回类型（TlsClientResult 先例），内部 `_ChunkRes` 同法。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run tests/t92_httpc.qma --target win` | PASS（约 60 断言，含 loopback E2E） |
| `python tests/run_win_tests.py` | PASS=159 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证；本 commit 口径=HEAD 158 + t92。跑分时工作区另有语言轨在途的 t93/neg_str 两个用例，同场全过则为 161） |
| `python tools/dev/check_names.py` | PASS |
| `python tools/dev/check_origin.py` | PASS |
| `python tools/dev/check_docs.py` | PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（重生成后） |

## 已知边界 / 遗留

- **传输层只编译于 Windows**（tcp_connect 依赖 getaddrinfo；Linux 编译期
  报错）。纯解析核心跨平台——CI/Linux 只构建 httpc.qma。
- **TLS 路径的 record seq**：服务器在应用数据前插多条握手消息时 seq 错位
  （std/tls_net v1.25 已知限制，"一次请求一次响应"场景）——生产用法建议
  服务端关掉 session ticket；多记录响应稳健性留待 tls_net 改进。
- 不校验证书链（std/x509 另用）；不自动解压 Content-Encoding（std/gzip
  在调用方侧自选）；连接失败 fail-fast（与 std/net 一致，无错误码）。
- 无连接池/流水线（每次请求新建连接，Connection: close 语义）；
  无 HTTP/2；Linux 侧等 DNS（07-gaps §2）。
- 端口段非十进制 / 状态码非三位数字 fail-fast（与 str.to_int 一致）。
- 下一轮候选（标准库轨）：路由/MIME/cookie（服务端补全）、SHA-512/CRC64/
  BLAKE2、正则引擎、KV 持久化、CLI 子命令。
