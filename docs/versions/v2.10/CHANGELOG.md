# v2.10 — HTTP 服务端：路由表 + 中间件（标准库「路由 / 中间件」🟡 → ✅）

- 日期：2026-10-24
- 任务：用户要求按 `07-gaps.md` §2 的**一条**一次性补成绿——「路由 / 中间件」那一行的
  黄标是"`std/router` 可用，但 `std/http` 仍是单回调、无中间件链，**且当前不可导入**"。
  本版把 `std/http` 修到能 `import`、补上路由表与中间件链，同步文档并实测性能。
- 影响面：标准库（`std/http`、`std/net/core`、`std/router`）、示例、测试、基准、文档

## 主事件

**1. `std/http` 从"不可导入"到可用。** 三处阻断：

| 阻断 | 现象 | 处理 |
|---|---|---|
| `let rc = h(fd)` | `SyntaxError: line 180: 期望 NAME，得到 'rc'`（`rc` 是 `rc[T]` 类型构造的关键字） | 改名 `code`，并在原地留注释 |
| 0 个 `pub` 导出（40 个顶层函数） | 用户代码一引用就 `引用了非 pub 声明` | 原有 40 个顶层函数里 29 个补 `pub` + `///`（11 个内部函数——`_parse_head` / `_find_head_end` / `_hdr_*` / reactor 回调——保持私有；本版新增的 10 个路由/中间件 API 全部公开、4 个内部函数不导出，终态 54 个顶层函数 / 39 个公开） |
| 跨模块读 `ST_H0` / `ST_MSGS` / `SLOT_RECVLEN` | `const` **不能** `pub`（语法只允许 `fn/struct/enum/interface`） | `std/net/core` 补 4 个访问器：`conn_recvlen` / `conn_msg_inc` / `conn_h0` / `conn_set_h0`；顺带把该模块 18 个函数全部 `pub` + `///` |

**2. 路由表 + 中间件链（新增，`std/http` 尾部一节）。** reactor 的回调只传 `(fd, data)`，
没有 user-data 通道；handler 必须是**裸函数名**（`callr` 间接调用），闭包（两字聚合）传不
进去。所以表放在 `static_word(2)` 指向的预分配块里，注册在 `http_serve` 之前完成（单线程、
无锁）：

```quela
fn main() {
    http_use(log_mw)                        // 执行顺序 = 注册顺序
    http_use(auth_mw)
    http_route("GET", "/users/:id", user_get)
    http_route("GET", "/files/*", files)
    http_serve(8080, 512, http_dispatch)    // 把内置派发器当 handler
}
```

新增 8 个 API：`http_route` / `http_use` / `http_dispatch` / `http_param` /
`http_param_count` / `http_route_index`（纯查询，便于单测）/ `http_routes_reset` /
`http_route_count` / `http_mw_count`，外加 `http_query`（取 `?` 之后的串）。

返回约定分两条路，文档里写死了：**单回调**模式沿用 `1 = 继续 / 0 = 关连接`；**路由表**
模式里 handler 返回值被忽略（要关连接调 `http_set_close`），中间件 `1 = 继续 / 0 = 终止
链路（视为已响应）`。

**3. `std/router` 加零拷贝字节级 API。** 路径字节本来就在连接缓冲里，原来的 `route_match`
会 `str_split` 两次（每段一次分配）。新增 `route_match_bytes` / `route_match_norm`（两边
已归一化）/ `route_param_at` / `route_param_count` / `route_eff_len` / `route_seg_count`，
**str 版改为转调字节版**——语义只有一份实现，`t106` 的既有断言原样通过。

**4. 顺手修掉两个真 bug**（都是"原来没人能 import，所以没人发现"）：

- `http_header` 返回值被**折叠成小写**：它复用了给 `Connection` 值比较写的
  `_hdr_val_str`，于是 `Authorization: Bearer s3cret` 取出来是 `bearer s3cret`。
  鉴权中间件按原样比较必然失败。新增 `_hdr_val_raw`（只去首尾空格、保留大小写）。
- `http_reason` 缺 401/429 两个原因短语（本版中间件要发 401）。

**5. 路由表快路径（注册期预处理）。** 每条目 8 字：方法指针/长度、模板指针/长度、handler、
特征位（含 `:` / 含 `*`）、段数、字面前缀长度。模板在注册时就存成**归一化形态**
（去 query / 尾斜杠 / 首个 `/`），派发期：

- 纯字面段路由 → 长度比较 + 一次 `mem_diff`（8 字节字比较）；
- 含 `:` 的路由 → 段数不符直接排除，再比字面前缀（一次 `mem_diff`），最后才逐段走；
- 含 `*` 的路由 → 只有它必须逐段走（`*` 能吃零段，前缀过滤不安全）。

## 逐文件改动

| 文件 | 改了什么 |
|---|---|
| `std/http.qma` | `rc` → `code`；29 个 API 补 `pub` + `///`；跨模块 const 改访问器；新增「路由 + 中间件」一节（表布局 / 8 个 API / 快路径）；`http_query`；`_hdr_val_raw` 修大小写折叠；`http_reason` 补 401/429；头注释改成"两种用法"（单回调 / 路由表） |
| `std/net/core.qma` | 18 个函数补 `pub` + `///`；新增 `conn_recvlen` / `conn_msg_inc` / `conn_h0` / `conn_set_h0`（公开面 18 → 22） |
| `std/router.qma` | 新增 `route_match_bytes` / `route_match_norm` / `route_param_at` / `route_param_count` / `route_eff_len` / `route_seg_count`；`route_match` / `route_params` 改为转调字节版（删掉两份重复实现） |
| `examples/http_router.qma` | 新增：7 条路由（字面 / 参数 / 两段参数 / 通配 / 任意方法 / gzip）+ 2 个中间件（访问日志 / `/admin` Bearer 鉴权）+ `--quiet` 开关（控制台 WriteFile 几十微秒，压测必须静音）；`/admin/stats` 顺带暴露 `cpu_ns` 当服务端成本口径 |
| `tests/t130_router_dispatch.qma` | 新增：字节版与 str 版**逐例对拍**（7 模板 × 10 路径）、参数捕获、注册/计数/reset/表满/超长模板、404 与 405 的区分、顺序语义、中间件上限 |
| `tests/http_router_test.py` | 新增：编译并启动示例，真实 socket 发请求，20 项断言（命中 / 归一化 / 404 / 405 / 鉴权 / 请求体 / gzip / keep-alive / 流水线）；`--bench` 追加吞吐与服务端 CPU |
| `bench/http_router_bench.qma` | 新增：1/4/16/64 条路由的查表单价、参数捕获、str 版 vs 字节版匹配 |
| `tests/run_win_tests.py` | 新增 `[3j2]` 段：`t130_router_dispatch`（自校验）+ `http_router_test.py`（E2E） |
| `docs/07-gaps.md` | §2「路由 / 中间件」🟡 → ✅；§7.13 按当前源码重测（解析失败 4 → 3 个，0 pub 模块 10 → 5 个）；§8 标准库序列补一行 |
| `docs/03-stdlib.md` | 重新生成：`std/http` 从 `0 / 40` 变 **`29 / 40`**、`std/net/core` 从 `0 / 18` 变 **`22 / 22`**、`std/router` 6 → **12**，全部带签名 |
| `docs/06-status.md` | 新增 **§3.19**（路由查表单价 + 端到端三段对照）；§1 PE 回归与文档门禁计数按实测更新 |
| `docs/05-toolchain.md` | §5.1 夹具计数跟随（+1 `.qma` / +1 `.py`） |
| `tools/stage0/qlm_cli.py` | `VERSION` → `2.10.0`（随后由并行轨推进到 `2.11.0`） |

## 验证

- `tests/t130_router_dispatch.qma`：全部断言通过（含 70 组字节版/str 版对拍）。
- `tests/http_router_test.py`：**20 项断言全过**（R1 命中 4 / R2 归一化 3 / R3 404·405 3 /
  R4 中间件 4 / R5 请求体 1 / R6 gzip 1 / R7 keep-alive 1 / R8 流水线 1 + 服务就绪）。
- `t106_weblib`（既有 router 断言）原样通过——`route_match` 改实现但语义不变。
- 主回归（隔离副本 `HEAD + 本版改动`）：见 `06-status.md` §1 主行。
- 门禁：`check_names` / `check_origin` / `check_docs` + `gen_stdlib_doc --check --require-doc`
  + `doc --missing` 全 PASS。

## 实测（详见 `06-status.md` §3.19）

进程内查表（命中末条，3 轮取最小）：1 条 **109 ns**、4 条 **142 ns**、16 条 **240 ns**、
64 条 **609 ns**；参数捕获 `route_param_at` **172 ns**；`route_match` 188 ns vs
`route_match_bytes` 205 ns（同量级，字节版**不分配**）。

端到端（同机同日、同一 Python 客户端、各 3 次取最小）：

| 服务 | µs/往返 |
|---|---|
| echo reactor（基线，无 HTTP） | 147.1 |
| `http_demo`（单回调，无路由/中间件） | 183.4 |
| `http_router`（7 条路由 + 2 个中间件 + 参数捕获） | 178.5 |

→ 路由 + 中间件 + 参数捕获的端到端成本**落在噪声内**（差值 −5 µs，符号不可信）；
4 连接并发 11.5k req/s（86.9 µs/往返）。

## 边界（写进 `07-gaps.md` §2 的"撞到什么场景"栏）

- 路由表 **64 条**、中间件链 **16 个**（超了返回 -1，不静默丢弃）；注册必须在 `http_serve`
  **之前**完成（表无锁，靠"单线程启动期"这个前提）。
- 先注册先匹配，**不按具体度排序**：`/u/:id` 在 `/u/me` 前面注册时前者会赢。
- 不做正则路由、不做 `**`、不做参数类型转换（`http_param` 一律给 str）。
- 中间件只有 **before 语义**（没有 `next()` / 响应后回调）；想要"响应后"就在 handler 里做。
- handler 必须是**裸函数名**：reactor 用 `callr` 调 `int` 代码地址，闭包是两字聚合传不进去
  （语言层 §6.5 的已知边界）。
- `http_param` 每次调用**重匹配一次**（不占槽位、不存每连接状态）；一个 handler 里取
  k 个参数就是 k 次查表，约 `k × 0.2 µs`。
- 405 不带 `Allow` 头；`http_dispatch` 永远返回 1（连接按 keep-alive 走），要关连接必须
  显式 `http_set_close`。
- `std/sse` / `std/ws` / `std/timer` 仍然不可导入（`rc` 撞关键字 / 顶层 `let`），
  §7.13 如实记账，不在本版范围。
