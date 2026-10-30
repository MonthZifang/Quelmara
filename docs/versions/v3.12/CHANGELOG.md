# v3.12 — HTTP 客户端接收大响应：两层 O(n²) 合成一个，2 MB 堆爆 → 8 MB 45 ms

- 日期：2026-10-30
- 任务：用户要求"继续推进进度以及优化它的性能"；承接 v3.09/v3.11 登记的
  同类缺口 —— "接收侧 O(n²) 在 `std/net` 修完了，别处还有没有"
- 影响面：标准库（`std/httpc` 的 chunked 解码器 + `std/httpc_net` 的接收循环）、
  测试（新增 `tests/t168_httpc_bulk.qma` 并接进主回归）、文档

## 问题：`std/net` 修过的坑，HTTP 客户端一层都没跟上

v3.09 把 `std/net` 六个接收函数的 `out = out + part` 改成缓冲区累积（O(n²)→O(n)），
v3.11 又把那批用例接进主回归。但**同一个形状在 `std/httpc_net` 里原封不动地留着**：

```quelmara
while guard < 4096 {
    let part = tcp_recv(fd, 8192)
    if len(part) == 0 { break }
    buf = buf + part                        // ① 每轮复制已收到的全部字节
    if str_find(buf, "\r\n\r\n") >= 0 {
        let r = httpc_parse_response(buf)   // ② 每轮把整段缓冲区从头重解析
        if r.complete == 1 { break }
    }
    guard = guard + 1
}
```

而且它是**两层**的 O(n²)，比 `std/net` 那次更糟：

| 层 | 位置 | 代价 |
|---|---|---|
| ① 字节累积 | `buf = buf + part` | 每轮复制已收全部字节，累计 ≈ n²/(2·chunk) |
| ② 整段重解析 | `httpc_parse_response(buf)` | 每轮重新找头块 + `_dechunk` 从头重解所有块 |

`_dechunk` 自己还有第三层：每块都 `r.body = r.body + slice(...)`，也是复制全部已累计数据。

**实测（本机 Windows PE，`build/probe_httpc_one.qma`，Content-Length 响应）：**

| 响应大小 | 改前 | 改后 |
|---|---|---|
| 512 KB | 21 ms | 5 ms |
| 1 MB | 70 ms | 6 ms |
| 1.5 MB | 141 ms | — |
| **2 MB** | **`heap_limit_mb exceeded`（退出码 1，跑不完）** | **28 ms** |
| 4 MB | — | 35 ms |
| 8 MB | — | 45 ms |

1 MB → 2 MB 耗时 70 → 141 ms 是**翻倍**，1.5 MB 已经开始指数抬头 —— 典型的二次曲线。
2 MB 直接撞 512 MB 堆上限（累计复制约 256 MB，加上扩容瞬间的新旧缓冲并存）。

**为什么 4 个版本没人发现**：老用例 `t92_httpc` 的响应是 **12 字节**（"hello httpc!"）
和 10 字节（chunked），轮数根本不够暴露累积成本。这与 v3.11 记的教训是同一个：
**"写在某个脚本里"不等于"被验证"；而"被验证"还要看**用例形状够不够极端**。**

## 改动

### 1. `std/httpc`：chunked 解码器改增量状态机

`_dechunk(s)` 原来是「对整段缓冲区做纯函数解析」——续收后必须从头再来一遍。
现在拆成 `_ck_size_line`（读一个 size 行）+ `_ck_feed`（把新增字节搬进输出缓冲）：

- 扫描游标 `pos` 是**当前块的下一个未搬字节**，续收从断点继续，不重扫；
- 块数据 `mem_copy` 进按倍数扩容的原始内存，末尾 `mem_str` 一次成串；
- 总拷贝 O(n)，峰值内存 ≤ 2n（扩容瞬间新旧缓冲并存）。

**踩到的坑（第一版写错了）**：第一版把 `pos` 当成"下一个 size 行起点"，块数据没到齐时
反复 `return` 同一个 pos，于是每次续收都把**已搬过的数据再搬一遍**。小于一个 recv 缓冲
的块（t92 的 7 字节）看不出来，8 KB 块（> 半个 16 KB 缓冲）立刻错。
小用例全绿 ≠ 状态机对 —— 必须用**跨 recv 边界的大块**验。这是 v3.09 那条
"验证 O(n²) 要用最坏形状"的镜像版本：**验证增量状态机要用跨边界的形状**。

### 2. `std/httpc_net`：接收循环重写

- 字节累积走可扩容原始内存（`_bappend`，几何扩容 + `mem_copy`），总拷贝 O(n)；
- 头块只在**第一次凑齐 `\r\n\r\n`** 时解析一次（`_parse_head` → `_RespHead`），
  之后复用；头块扫描游标 `scanned` 保证不每轮从头找；
- chunked 直接喂原始内存指针给 `_ck_feed`，**从不把整个缓冲区成串**；
- content-length 够了就 `mem_str` 一次成串；
- 新增 `HTTPC_MAX_BYTES = 64 MB` 上限保护（老实现完全没有上限，对端一直发就堆爆）。

顺带把 `send_all` 换掉了 `tcp_send`：老代码 `tcp_send(fd, req)` 是**单次**写，
请求头超过内核缓冲时会短写 —— 只是老用例的请求太小没暴露。

### 3. 两个新的公开函数

| 函数 | 为什么要 |
|---|---|
| `httpc_make_response(status, reason, head, body, complete, chunked)` | **限定 struct 字面量不做**（`02-language.md` §1），`httpc_net` 没法写 `HttpResponse { ... }`。传输层不再整段重解析，就得有个按部件组装的入口 |
| `httpc_header_raw(head, name)`（原私有，改为 `pub`） | 传输层要自己判 framing（content-length / chunked），而它只拿到头块文本 |

### 4. `tests/t168_httpc_bulk.qma`（新增，接进主回归）

5 个场景，全是**老实现跑不完或跑错**的形状：

| # | 场景 | 老实现 |
|---|---|---|
| 1 | content-length 1 MB | 70 ms（改后 6 ms） |
| 2 | content-length 4 MB | 跑不完（2 MB 就堆爆） |
| 3 | chunked 1 MB / 8 KB 块 | 跑不完 |
| 4 | chunked 4 MB / 8 KB 块 | 跑不完 |
| 5 | content-length 不足（对端提前关） | complete=0 且 body 是已收部分 |

抽样比对按 1 KB 步长 + 末字节单独查（4 MB 全字节比要 400 万次 `mem_load8`，太慢；
1 KB 步长足以发现错位 / 截断 / 重复 / 丢块）。

**这个夹具对老代码是红的**：把 `std/httpc.qma` 与 `std/httpc_net.qma` stash 掉重编，
`win_t168_old.exe` 直接 `heap_limit_mb exceeded`、退出码 1。这不是"跑通就行"的用例。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=327 FAIL=0 SKIP=0**（v3.11 是 326；+1 新夹具） |
| 单独跑 `t168_httpc_bulk` | `httpc bulk ok`，退出码 0 |
| 单独跑 `t92_httpc`（老用例） | `ok t92_httpc`，退出码 0 —— **对外语义没变** |
| 老代码跑 t168 | `heap_limit_mb exceeded`，退出码 1（证明夹具有效） |
| `python tools/dev/check_docs.py` | PASS（199 个 Markdown） |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（67 模块 / 570 公开函数） |
| `python tools/dev/check_names.py` / `check_origin.py` | 均 PASS |
| `examples/https_get.qma`（真实公网 TLS） | `handshake ok (cv=1)` / `cert chain=4` / `HTTP/1.1 200 OK`，退出码 0 |

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `std/httpc.qma` | chunked 解码器改增量状态机（`_Ck` / `_ck_size_line` / `_ck_feed`）；`_dechunk` 走它；新增 `httpc_make_response`；`httpc_header_raw` 改 `pub` |
| `std/httpc_net.qma` | 接收循环重写（可扩容缓冲 + 头块只解析一次 + 增量 chunk + 64 MB 上限）；`send_all` 替代 `tcp_send` |
| `tests/t168_httpc_bulk.qma` | 新增：5 个场景的大响应回归 |
| `tests/run_win_tests.py` | 接入 `t168_httpc_bulk`（`case_selfcheck_to`，180 s 短超时） |
| `docs/06-status.md` | §1 主回归口径 → 327；新增 §3.66 |
| `docs/07-gaps.md` | §5 新增「HTTP 客户端接收 O(n²)」→ ✅ v3.12；§2 HTTP 客户端行的边界更新 |
| `docs/03-stdlib.md` | `gen_stdlib_doc.py` 重生成（570 个公开函数） |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.12.0 |

## 已知边界 / 遗留

- **`std/tls_net.tls_recv_exact` 里还有同一个形状**（`out = out + part`，第 40 行）。
  它的 `n` 是 TLS 记录长度（≤ 16 KB + 256），最多两三轮，实际代价可以忽略 ——
  但形状是同一个，下次谁把记录上限调大就会踩。已登记 `07-gaps.md` §5。
- **`std/tls_net.tls_connect` 的 `buf = buf + hdr + body`（第 74 行）同理**：
  握手报文只有几 KB、最多 16 轮，收益不值得动；但它是 O(n²) 家族的最后两个成员。
- **TLS 路径的大响应没有执行级覆盖**：`httpc_get_tls` 走同一个 `_recv_loop`，
  但要用真服务器才能测，主回归里没有自建 TLS 服务端。目前靠 `examples/https_get.qma`
  手工验（本次已跑，200 OK / 923 字节）。
- **`_ck_feed` 的 `done` 字段目前只写不读**（留着给将来的"进度回调"用）。
  不用就删——按项目纪律不该留死字段，但它与 `pend` 配对表达"当前块已搬多少"，
  删掉会让状态机读起来缺一块，先留着。
- **64 MB 上限是拍的**：老实现完全没有上限（对端一直发就堆爆），给个上限是净改善，
  但 64 MB 这个数没有实测依据。要更严谨得做成可配置（`Quelmara.toml [net]` 或函数参数）。
