# v1.72 — multipart/form-data 解析（§2 这条行收口）

- 日期：2026-10-23
- 任务：§2「静态文件 / MIME / cookie / session / multipart」的最后一块——**multipart**。
  这条行从"全缺"到全绿：MIME（v1.67）→ 静态文件（v1.69）→ cookie（v1.70）→
  session（v1.71）→ multipart（本版）。
- 影响面：标准库（`std/multipart.qma`，全部用 Quelmara 写）、测试、文档、`07-gaps` §7.9

## 新增 API

| 函数 | 说明 |
|---|---|
| `multipart_boundary(ctype) -> str` | 从 `multipart/form-data; boundary=…` 取边界（去引号）；非 multipart 返回空串 |
| `multipart_parse(body, boundary) -> vec[Part]` | 解析成 `Part { name, filename, ctype, data }` |
| `multipart_field(body, boundary, name) -> str` | 取表单字段（无 filename 的 part） |
| `multipart_file(body, boundary, name) -> str` | 取上传文件正文（有 filename 的 part） |

- 分隔符按 RFC 7578：`--boundary` 开头、`\r\n--boundary` 分隔、`--boundary--` 结束；
- 头字段**大小写不敏感**（`Content-Disposition` / `content-disposition` 都认）；
- 文件正文里的 CRLF **原样保留**（只按分隔符切，不按行切）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/multipart.qma` | **新增**：`Part` struct + 4 个公开函数 + 3 个内部辅助（`mp_header` / `mp_attr` / 边界处理） |
| `tests/t111_multipart.qma` | **新增**：boundary 三种写法、字段/文件区分、CRLF 正文、小写头、空 body / 错误 boundary / 只有结束标记 / 无尾 CRLF |
| `tests/run_win_tests.py` | 注册 `t111_multipart` |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 |
| `docs/03-stdlib.md` | 重新生成：53 个模块 / 360 个公开函数 |
| `docs/07-gaps.md` | §2 该行标全绿；**新增 §7.9**（结构体字面量里调函数 → 未定义函数） |
| `docs/06-status.md` | 回归数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.72.0 |

## 又踩到一个 Lower 缺陷（§7.9）

```quelmara
struct P { a: str, b: str }
fn helper(x: str) -> str { return x + "!" }
fn build(x: str) -> P {
    return P { a: helper(x), b: "lit" }    // SyntaxError: 未定义函数 helper
}
```

字面量字段值直接写函数调用就报"未定义函数"（先赋给局部变量再进字面量则正常）。
已登记 `07-gaps.md` §7.9 并附最小复现，`std/multipart` 里按绕开写法实现
（注释里标了原因，将来修好可以还原成一行）。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/t111_multipart.qma` | 25 条断言全过 |
| `python tests/run_win_tests.py` | PASS=203 FAIL=0 SKIP=1 |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（53 模块 / 360 公开函数） |
| 四道门禁 | 全 PASS |

## 已知边界 / 遗留

- 不做 `Content-Transfer-Encoding`（base64 / quoted-printable）解码。
- 不做嵌套 `multipart/mixed`（邮件常见，HTTP 表单很少见）。
- 不限制 part 数量与 body 大小——超大上传由调用方（HTTP 层）限制。
- **§7.9 未修**（另一条轨负责 `qlm_native.py`）；修好后 `std/multipart` 可以简化。
