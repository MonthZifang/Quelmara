# v1.69 — 静态文件服务端到端：`static_serve` 直接产出 HTTP 响应

- 日期：2026-10-23
- 任务：把 v1.68 的解析层接到真实 I/O，做出**可直接写回 fd** 的完整 HTTP 响应
  （200 / 206 / 403 / 404），P0「路由 / 静态文件 / MIME 最小层」这条链打通。
- 影响面：标准库（`std/staticfile.qma`）、测试、文档

## 为什么是它

v1.68 只做到"URL → 磁盘路径 + 头字段"，还差最后一跳：读文件、判 404、拼响应。
上一版以为缺 `file_exists` 内建，实测**它早就有了**（v1.16，连同 `file_size` /
`fs_mkdir` / `fs_remove`），所以这一版直接接线。

## 新增 API

```quelmara
pub fn static_serve(root: str, url: str, range: str) -> str
```

| 输入 | 输出 |
|---|---|
| 正常文件 | `200 OK` + Content-Type / Content-Length / Cache-Control / ETag / Accept-Ranges |
| 带 `Range: bytes=a-b` | `206 Partial Content` + Content-Range + 片段正文 |
| 目录（`/`、`/sub`、`/sub/`） | 补 `index.html` 后按 200 返回 |
| 文件不存在 | `404 Not Found`（先探测再读，不会让 `read_text` fail-fast 退出进程） |
| 目录穿越（`..`、`%2e%2e`） | `403 Forbidden` |

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/staticfile.qma` | 新增 `static_serve` + 两个内部拼装函数 `sf_head` / `sf_error`；目录探测从 `file_exists` 改成 `file_size >= 0`（目录在 Windows 上 `CreateFileA` 会失败，`file_exists` 却为真） |
| `tests/t108_staticserve.qma` | **新增**：200/206/404/403 四类响应、目录三种写法、二进制正文（含 NUL 不被截断）、Range 开区间 |
| `tests/run_win_tests.py` | 注册 `t108_staticserve` |
| `docs/03-stdlib.md` | 重新生成（50 个模块 / 341 个公开函数） |
| `docs/07-gaps.md` | §2 静态文件行：I/O 接线完成，剩 If-None-Match / Last-Modified |
| `docs/06-status.md` | 回归数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.69.0 |

## 实现要点

- **`file_exists` 对目录也为真**：这是接线时踩的第一个坑——`/sub` 命中目录后直接
  `read_text` 会把进程打死。改用 `file_size(path) < 0` 判"不是可读文件"，
  再退到 `path + "/index.html"`。
- **404 不会炸进程**：`read_text` 是 fail-fast 的，所以必须**先探测再读**；
  测试里 `/nope.txt` 走的就是这条路。
- **二进制安全**：`str` 是长度前缀字节串，`read_text` 原样返回，`len()` 是字节数，
  所以 `Content-Length` 直接用 `len(body)`；测试用 `"a\x00b"` 验证 NUL 不被截断。
- **ETag 用 `size-0`**：没有 mtime 内建（`file_size` 只给长度），先用长度做弱校验；
  接 `If-None-Match` 之前需要补 `file_mtime`。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/t108_staticserve.qma` | 25 条断言全过（含 NUL 正文、206 开区间） |
| `python tests/run_win_tests.py` | PASS=200 FAIL=0 SKIP=1 |
| `python tests/lexdiff.py` | PASS=183 FAIL=0（186 个源文件） |
| `python tests/parsediff.py` | PASS=135 FAIL=0 |
| `python tests/irdiff.py` | PASS=74 FAIL=0 SKIP=62 |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（50 模块 / 341 公开函数） |
| 四道门禁 | 全 PASS |

## 已知边界 / 遗留

- **Linux 下不带尾斜杠的目录**仍可能踩到 `read_text` 失败（`file_size` 对目录的行为
  在两平台不一致）；Windows 上已正确。彻底修需要 `file_is_dir(path)` 内建。
- 没有 `If-None-Match` / `If-Modified-Since` 比对（只发 ETag，不处理条件请求）。
- 没有 gzip 预压缩协商、没有 `Last-Modified`（需要 HTTP 日期格式化）。
- 大文件仍是**整文件读入内存**（`read_text` 一次分配），没有分块发送。
