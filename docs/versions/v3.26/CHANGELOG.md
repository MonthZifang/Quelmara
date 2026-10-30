# v3.26 — 标准库有 6 个模块外部一个函数都调不到，其中 2 个连解析都过不去

- 日期：2026-10-30
- 任务：用户要求"继续"；复核 `07-gaps.md` §7.13 那条挂了很久的审计
- 影响面：**标准库**（`std/ws`、`std/sse`、`std/core`、`std/gen`、
  `std/serialize`、`std/time`、`std/sha1`），新增门禁
  `tools/dev/check_std_import.py`
- 版本：按 `00-convention.md` §5.1 建版本目录

## 起点：一条挂了 24 个版本的审计

`07-gaps.md` §7.13 写着"6 个标准库模块没有 `pub` 导出，其中 2 个连解析都过不去"，
标注是 v2.01 审计、v2.08 重测。此后一直挂着。

这次重新跑了一遍完整审计（70 个模块逐个 import + 构建），结果：

```
共 70 个模块，失败 2 个
  FAIL std.sse: line 133: 期望 NAME，得到 'rc'
  FAIL std.ws:  line 180: 期望 NAME，得到 'rc'
```

## 病因一：`rc` 是关键字

`std/sse.qma:133` 和 `std/ws.qma:180` 都写了：

```quelmara
let rc = h(fd)
```

而 **`rc` 是语言关键字**（`rc[T]` 是结果类型）。`std/http.qma:243` 的注释
早就记过这件事：

```quelmara
let code = h(fd)      // 注意：rc 是关键字（rc[T]），别用作变量名
```

`http` 的作者踩过并留了注释，`ws`/`sse` 的作者没有 —— 于是这两个模块
**连解析都过不去**。改名 `rc` → `hr`（5 处）。

## 病因二：跨模块调了非 pub 函数

`std/ws` 握手要算 `Sec-WebSocket-Accept`：

```quelmara
let dig = sha1_str(key + WS_GUID)
let accept = b64_encode(dig, 20)
```

它要的是**原始 20 字节摘要**，而 `std/sha1` 只导出了 `sha1_hex`（40 位十六进制）。
`sha1_str` 当时没有 `pub`，于是报"引用了非 pub 声明"。

给 `sha1_str` 加 `pub` —— 它本来就是模块核心，`sha1_hex` 只是它的十六进制包装。

## 病因三（最隐蔽）：模块一个 `pub` 都没有

修完前两条，70 个模块**全部能编译**了。但能编译 ≠ 能用：

`std/ws` 有 11 个顶层函数、`std/sse` 有 14 个，**没有一个带 `pub`**。
`03-stdlib.md` 里它们标着可用，实际外部一个也调不到。

补 `pub` 的过程中，门禁又扫出 4 个同样问题的模块：

| 模块 | 顶层函数 | 说明 |
|---|---|---|
| `std/core` | 4 | `abs` / `max2` / `min2` / `pow2k` |
| `std/gen` | 9 | `gen_min` / `gen_max` / `gen_clamp` … 泛型版 |
| `std/serialize` | 10 | `varint_put` / `put_u16le` … |
| `std/time` | 2 | `now_ms` / `ms_str` |

实测确认它们真的调不到：

```
p3.qma: 引用了非 pub 声明（1 处）：'now_ms' <- time.qma
```

`std/gen` 是泛型库，函数形如 `fn gen_min[T: Ord](a: T, b: T) -> T`，
普通正则匹配不到 `[` 前面的部分，得单独处理。

## 顺带修掉一个运行期崩溃

给 `ws`/`sse` 写夹具时发现：**起服务之前**调 `ws_accepted()` 会崩（`0xC0000005`）。

原因是所有统计函数都走 `_wst()`：

```quelmara
fn _wst() -> int {
    return mem_load64(static_word(0), 0)   // 起服务前是 0
}
```

然后直接 `conn_accepted(0)` —— 解引用空指针。外部调用方在起服务前查一下统计
是很自然的事，不该崩。改成惰性建一个空状态块，语义就是"还没连过"。

## 结果

| 项 | 前 | 后 |
|---|---|---|
| 能编译的模块 | 68 / 70 | **70 / 70** |
| 有 pub 导出的模块 | 64 / 70 | **70 / 70** |
| 公开函数总数 | 584 | **635** |

新增 51 个真正可用的 API。

## 门禁

`tools/dev/check_std_import.py`：逐个模块生成只 `import` 它的空程序编译一次，
再检查"有顶层函数却一个 `pub` 都没有"。已挂进 `run_win_tests.py`
（`case_std_import`）。

这道门禁的价值在于**第二判据**：编译通过不等于能用。v2.01 的审计只看了
"能不能构建"，所以 `ws`/`sse` 那种"能编译但全私有"的情况一直没被抓住。

## 夹具

`tests/t177_ws_sse.qma`：

- 验证 ws / sse 的公开函数**确实可调**（不 pub 时编译期就报错）；
- 用 RFC 6455 的标准样例验证握手摘要：
  key `dGhlIHNhbXBsZSBub25jZQ==` → accept `s3pPLMBiTxaQ9kYGzzhZRbK+xOo=`。

## 回归

第一次跑回归时**红了 2 类 3 条**，都是修好这两个模块的副作用，值得记下来：

### 1. 51 个新 `pub` 缺 `///` 文档

`doc --missing` 门禁要求公开声明必须有文档注释。这 51 个函数原本是模块内部
用的，写的是普通 `//` 注释（或干脆没有），加 `pub` 之后就有文档义务了。

批量把紧邻的 `//` 升级成 `///`（27 行），剩下的手工补 —— 有些函数是
"组注释"覆盖多个函数（`/// put_u16le / put_u32le / put_u64le：小端定长写入`），
门禁只认紧邻那一个，得给每个函数单独写。

最终 638 个公开声明全部有文档。

### 2. 语言服务器测试**依赖这两个模块是坏的**

`tests/lsp_test.py` 的"容错索引"用例，负向样本正是 `std/sse.qma` 与 `std/ws.qma`：

```python
neg = [("std/sse.qma", "`rc` 当变量名（关键字）"),
       ("std/ws.qma", "`rc` 当变量名（关键字）")]
...
want(not parsed, f"容错索引：{rel} 确实过不了 qlm.Parser（{why}）")
```

我修好了它们，`parsed` 变成 `True`，断言就红了。**这是测试设计问题**：
用标准库的真实缺陷当负向样本，等于把"缺陷存在"变成回归的前提 ——
修好缺陷反而打红。

改成**现场构造**一个坏文件（含 `let rc = a`）作负向样本，并把
`std/sse` / `std/ws` 挪进正向用例（"已能过前端"）。这样：
容错能力仍被验证，且不再依赖标准库的缺陷状态。

### 3. 起服务前查统计会崩

写 `t177` 夹具时发现的：`ws_accepted()` 在 `ws_serve()` 之前调用会
`0xC0000005`。原因是 `_wst()` 读 `static_word(0)` 拿到 0，再传给
`conn_accepted(0)` —— 解引用空指针。

改成惰性建一个空状态块，语义就是"还没连过"。外部调用方在起服务前
查统计是很自然的事。

## 回归

全量 Windows 回归 PASS=342 FAIL=0 SKIP=0（v3.25 是 340，新增 2 条：
ws_sse 与 std_import）。
LSP 44 项（原 40，负向样本改造后多了 4 条正向钉住）。

## 遗留

`07-gaps.md` §7.13 那条可以关掉了，但同一节里还有别的审计项没复核完
（例如 `vec[vec[T]]` 类型码区间 §7.18、stage-0 类型推断丢失 §7.28、
qlmc 第 5 个及以后 f64 形参 §7.33）。那几条都在 qlmc / stage-0 的
类型系统深处，不属于"标准库可用性"范畴，留待后续。
