# v1.68 — 静态文件服务：安全解析层 `std/staticfile`

- 日期：2026-10-23
- 任务：`07-gaps.md` §2「静态文件 / MIME / cookie / session / multipart」里的
  **静态文件**一块——把"URL → 磁盘路径"这段最容易出安全事故的逻辑做成可测的纯函数层。
- 影响面：标准库（`std/staticfile.qma`，全部用 Quelmara 写）、测试、文档

## 为什么是它

v1.67 给了 MIME 与路由，但真要把文件发出去还差三件事：路径安全、缓存头、Range。
这三件都是**纯函数**（不碰 socket、不读文件），可以在自研后端上直接跑测试——
比先写 I/O 再接起来更划算，也把最容易出错的部分先钉死。

## 新增 API

| 函数 | 说明 |
|---|---|
| `static_url_decode(s)` | `%XX` 解码；非法序列原样保留；无 `%` 走快路径 |
| `static_path_safe(url)` | **先解码再判**：拒绝 `..` / `.` 段、反斜杠、NUL |
| `static_resolve(root, url)` | `root + '/' + 相对路径`；root 尾斜杠合并；不安全返回 `""` |
| `static_index_for(path)` | 目录（含空路径）补 `index.html` |
| `static_content_type(path)` | 委托 `std/mime` |
| `static_cache_control(path)` | HTML → `no-cache`；其余 → 一年 `immutable` |
| `static_etag(size, mtime)` | `"<size>-<mtime>"`，可直接当 ETag 头 |
| `static_range(hdr, size)` | 解析 `bytes=a-b` / `a-` / `-n`；多段、越界、非法 → 空 vec |

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/staticfile.qma` | **新增**：上面 8 个公开函数 + 3 个内部辅助（`sf_is_digit` / `sf_all_digits` / `sf_hex`） |
| `tests/t107_staticfile.qma` | **新增**：解码（含 UTF-8 三字节、非法 `%zz`）、穿越（`..`、`%2e%2e`、反斜杠、`.`、`..b` 反例）、路径拼接、index 补全、Cache-Control、ETag、Range 十种形态 |
| `tests/run_win_tests.py` | 注册 `t107_staticfile` |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 |
| `docs/03-stdlib.md` | 重新生成：50 个模块 / 340 个公开函数 |
| `docs/07-gaps.md` | §2 该行：静态文件从"全缺"改成"解析层 ✅，I/O 接线待做" |
| `docs/06-status.md` | 标准库计数与回归数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.68.0 |

## 实现要点

- **先解码再判**是关键顺序：`%2e%2e%2f` 解码后才是 `../`，只查原始串会漏。
  测试里 `static_path_safe("/a/%2e%2e/etc")` 必须为 false。
- **`str.to_int()` 是 fail-fast 的**（非法输入直接退出进程），而 Range 头是
  攻击者可控的——所以先用 `sf_all_digits` 校验，再转 int。
- **`..b` 不是 `..`**：按 `/` 切段后逐段比，不做子串匹配（`str_find` 会把
  `..b` 误判）。
- **Range 非法一律返回空 vec**，由调用方决定回 200 全量还是 416——
  库层不替调用方做 HTTP 状态决策。
- 字节拼接走 `vec[int]` + `str_from_bytes`（与 `std/hex` 同款，一次分配）。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/t107_staticfile.qma` | 40+ 断言全过 |
| `python tests/run_win_tests.py` | PASS=199 FAIL=0 SKIP=1 |
| `python tests/lexdiff.py` | PASS=182 FAIL=0（185 个源文件） |
| `python tests/parsediff.py` | PASS=134 FAIL=0（新模块进声明级对拍） |
| `python tests/irdiff.py` | PASS=74 FAIL=0 SKIP=61 |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（50 模块 / 340 公开函数） |
| 四道门禁 | 全 PASS |

## 已知边界 / 遗留

- **I/O 接线还没做**：真正的服务要 `read_text(path)` 读文件 + 拼状态行/头 + 分块发送，
  而且 `read_text` 失败是 fail-fast（文件不存在会直接退出进程）——需要先补一个
  `file_exists(path)` 之类的内建，否则 404 无法优雅返回。已登记 §2。
- 不做符号链接逃逸检查、不做 `If-None-Match`/`If-Modified-Since` 的比对逻辑
  （只生成 ETag，比对由调用方做）、不做 gzip 预压缩协商。
- `Last-Modified` 的 HTTP 日期格式化（IMF-fixdate）未做——需要时间格式化工具。
