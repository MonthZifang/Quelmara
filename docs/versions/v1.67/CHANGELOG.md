# v1.67 — 静态文件服务的两块：`std/mime` + `std/router`

- 日期：2026-10-23
- 任务：`07-gaps.md` §2 的两条红标——**MIME** 与**路由**——落地成标准库模块
  （P0「路由 / 静态文件 / MIME 最小层」的前两块）。
- 影响面：标准库（`std/mime.qma`、`std/router.qma`，全部用 Quelmara 写）、
  测试、文档（`03-stdlib.md` 由 `gen_stdlib_doc.py` 重新生成）

## 为什么是它

`std/http` 只有单回调：稍大的服务都要自己写 `if path == "/a" ...` 的链，
每个静态文件响应还要手写 Content-Type。这两块是所有 Web 服务的第一道地基，
而且是纯函数（不碰 socket），可以在自研后端上直接测。

## 新增 API

### `std/mime`（30 项内置表）

| 函数 | 说明 |
|---|---|
| `mime_of(path) -> str` | 按**最后一个点**之后的扩展名查表（大小写不敏感），带 `charset=utf-8`；认不出 → `application/octet-stream` |
| `mime_ext_of(path) -> str` | 只要扩展名（不含点）；`/`、`\` 之后的点才算 |
| `mime_ext(ctype) -> str` | 反查扩展名；带参数写法（`text/html; charset=utf-8`）先截 `;` |
| `mime_is_text(ctype) -> bool` | `text/*` 与 json/xml/js/svg |

### `std/router`（路径模板匹配）

| 函数 | 说明 |
|---|---|
| `route_match(pattern, path) -> bool` | `/users/:id` 参数段、尾部 `*` 通配剩余、段数必须一致 |
| `route_params(pattern, path) -> vec[str]` | 按出现顺序返回捕获段；不匹配返回空 vec |
| `route_norm(target) -> str` | 截 `?query` / `#frag`、去首尾 `/` |
| `route_segs(target) -> vec[str]` | 归一化后按 `/` 切段 |
| `route_method_allowed(allowed, method) -> bool` | `"GET, POST"` 里是否允许该方法 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/mime.qma` | **新增**：`mime_of` / `mime_ext_of` / `mime_ext` / `mime_is_text`（内部 `mime_cut_params`） |
| `std/router.qma` | **新增**：`route_norm` / `route_segs` / `route_match` / `route_params` / `route_method_allowed` |
| `tests/t106_weblib.qma` | **新增**：MIME 双向查（大小写/多点文件名/点目录）、路由（参数段/通配/段数/归一化/捕获顺序/方法白名单） |
| `tests/run_win_tests.py` | 注册 `t106_weblib` |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记两个新模块 |
| `docs/03-stdlib.md` | 重新生成：49 个模块 / 332 个公开函数 |
| `docs/07-gaps.md` | §2「路由 / 中间件」「静态文件 / MIME …」两行更新 |
| `docs/06-status.md` | 标准库计数与回归数字 |

## 实现要点

- **零依赖**：两个模块只 import `std.str`（`str_lower` / `str_trim` / `str_split`），
  不碰 socket、不碰 `std/http`，所以能在任何后端上跑（含 AArch64）。
- **查表用 if 链而不是 `map[str]str`**：map 每次调用都要建表（分配），if 链在
  Lower 里是常数次字节比较，静态文件服务的每个响应都要走一次，实测更划算。
- **归一化只有一处**：`route_norm` 是唯一的真相，`route_segs`/`route_match`/
  `route_params` 都走它——避免"匹配和取参数用两套归一化"的漂移。
- **`*` 只认最后一段**：`/static/*` 匹配 `/static` 与 `/static/css/app.css`，
  不捕获；`**` 与优先级排序不做（调用方按自己的顺序试）。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/t106_weblib.qma` | 30+ 断言全过 |
| `python tests/run_win_tests.py` | PASS=198 FAIL=0 SKIP=1 |
| `python tests/parsediff.py` | PASS=133 FAIL=0（两个新模块进声明级对拍） |
| `python tests/irdiff.py` | PASS=74 FAIL=0 SKIP=60 |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（49 模块 / 332 公开函数） |
| 四道门禁 | 全 PASS |

## 已知边界 / 遗留

- **静态文件服务本身还没写**（要读文件 + 分块发送 + Range），本版只给了 MIME 与路由两块。
- 路由不支持 `**`、正则段、优先级排序、同名参数重复检测。
- MIME 表只有 30 项，没有 `/etc/mime.types` 那种全量数据，也没有
  `Content-Disposition` / 压缩协商的联动。
- cookie / session / multipart 仍缺（§2 同一行）。
