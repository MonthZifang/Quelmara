# v2.95 — chunked 请求体落地：std/http 不再回 501

- 日期：2026-10-28
- 任务：补库 —— `docs/07-gaps.md` §2 的 "chunked 请求体 | 回 501" 一行
- 结论：请求体侧的 `Transfer-Encoding: chunked` 现在是**真解码**（就地压缩），
  新增纯内存模块 `std/http_chunk`，三后端同一份夹具。501 只剩"TE 是其它编码"。

## 为什么拆成独立模块

`std/http` 的解析器跑在 IOCP reactor 的 worker 线程上，只能在 Windows 做
执行级验证。把 chunked 的**扫描与解包**抽成"输入只是一段字节缓冲区 + 区间"
的纯函数，它就能编进任何后端：

- native/ELF：`tests/t158_chunk.qma` 在 Linux CI 上**真跑断言**（本版主要验证通道）；
- win：`run_win_tests.py` 的 `case_selfcheck` 执行同一份夹具；
- arm64：编译级 + 对拍。

这与 `std/httpc`（纯函数客户端解析）的拆法同源。

## 设计：就地向前压缩，写游标永远追不上读游标

解包把 `[start, end)` 的流压实到 `[start, start+len)`。每个 chunk 在流里占
`hex行长 + 2 + size + 2`，而写游标只前进 `size`，所以

```
src − (dst + size) ≥ (前序 chunk 的 hex行长 + 4) + (本 chunk 的 hex行长 + 2) ≥ 6
```

写区永远落在读区之前（`__memcpy` 是前向逐字拷贝，dst ≤ src 时无重叠语义问题）。
头块 `[0, start)` 全程不碰 —— `http_method` / `http_header` 照常工作。
这条不变量在字节模型上逐块验证过（含 size=10 > hex 行的重叠压力形状）。

## 语义口径（RFC 7230 §3.3.3 + §4.1）

| 规则 | 行为 |
|---|---|
| chunk-ext（`4;a=1`）| `;` 起整段丢到行尾 |
| trailer | `0\r\n` 后的字段行逐行扫过即弃，转发给 handler 的体里没有它们 |
| **TE 与 Content-Length 同时出现** | **以 TE 为准，CL 忽略**——守卫做了双向：单遍扫描里 CL 行可能排在 TE 行**之后**，不判 flags 就会把刚清掉的 `HP_BLEN` 重新写回去（E2E R12 正反两种头序都覆盖） |
| 病态流（非 hex size / 空 size 行 / >8 位 hex / 数据后缺 CRLF）| 400 并关闭，绝不"尽力解出前半段"交给 handler |
| size 上限 8 位 hex | 防 int64 溢出 |

handler 侧**零感知**：`http_body` / `http_body_len` 读到的就是解包后的体；
`http_body_len` 的 `///` 已改口径（chunked = 解包后真实体长）。

标志位 `HP_F_TE`（bit10）挤在 `HP_STATE` 高位——协议私有槽 w6..w15 已被
HP_* 十字段占满；解包成功立刻清位，keep-alive 的下一请求不会把已压实的
字节再 pack 一遍。

## 顺带修的 C 后端缺陷：字符串字面量漏转义 `\r`

`Codegen.cstr()` 转义了 `\`、`"`、`\n`、`\t`，**没转义 `\r`**——任何含 CR 的
字符串字面量生成出的 C 直接非法（`missing terminating " character`）。
写 t158 的 C 链验证时撞到（`"5\r\nhello..."` 是最典型的 chunked 夹具字符串）。已补。

> 这类"转义表少一行"的缺陷与 v2.90 的 `args()`、v2.91 的 `structlit` 同族：
> 两条实现路径（自研后端 / C 后端）各写一份，一份跟上、一份没跟上。

## 验证

| 项 | 结果 |
|---|---|
| `tests/t158_chunk.qma`（native 执行） | **chunk ok**（12 组形状：两块 / ext / trailer / 大写 hex / 零块 / 体内 CRLF / 保留头部 / 6 种 -1 / 5 种 -2 / 三块连压 / 恰界 8 位）|
| `run_native_tests.sh` | **PASS=108 FAIL=0**（新增 `[25]` 两条）|
| `lexdiff` / `parsediff` | **310/313** / **214/214**（新文件全部通过自举词法器与声明级 parser）|
| `examples/http_router.qma` win 编译 | PASS（std/http 全链路进 PE）|
| 五道门禁 | PASS（`gen_stdlib_doc.py` 重生成：64 模块 / 534 公开函数）|
| E2E `tests/http_router_test.py` | 新增 R9–R12 共 6 条断言（20→26）；**Windows-only 通道，本轮未在真机执行** |

## 边界（如实登记）

| 项 | 现状 |
|---|---|
| TE 为 `gzip` 等其它编码 | 仍 501（响应侧压缩协商是另一回事，已支持） |
| 响应侧分块发送（chunked write） | 未做；`http_send` 仍是 Content-Length 整块 |
| chunked 体的增量解码 | 未做——流没收全时 `chunk_scan` 每次 on_data **从头重扫**本请求体。recv 缓冲上限 1 MB，最坏 O(n·段数)；要做增量需给槽位加"体扫描位置"（w15 已被头部扫描占用） |
| C 后端 | `mem_alloc`/`mem_copy` 等内存内建未实现（v2.91 已登记），t158 在 C 链路上编不过——不新增 FAIL，`run_tests.sh` 的清单没扩到 t158 |
| trailer 转发 | 丢弃；目前没有"handler 需要读 trailer"的库（`std/aws-sig-v4` 式流签名除外，届时再说） |
