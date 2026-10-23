# v1.76 — 路径处理 `std/path`

- 日期：2026-10-23
- 任务：标准库补路径工具。之前 `std/staticfile` 手拼 `root + "/" + p`、
  `std/mime` 自己找最后一个点、`std/httpc` 自己切目录——规则散在三处。
- 影响面：标准库（`std/path.qma`，全部用 Quelmara 写）、测试、文档
- 注：v1.75 被另一条轨（源码级调试器）占用，本版顺延为 1.76

## 新增 API

| 函数 | 说明 |
|---|---|
| `path_join(a, b)` | `b` 是绝对路径则直接返回；否则接缝处只留一个 `/` |
| `path_clean(p)` | 消解 `.` 与 `..`；绝对路径不越过根，相对路径保留前导 `..` |
| `path_dir(p)` | 父目录（无目录返回 `.`，根下返回 `/`） |
| `path_base(p)` | 文件名 |
| `path_ext(p)` | 扩展名（**不含点**，与 `std/mime` 口径一致）；`.gitignore` 没有扩展名 |
| `path_stem(p)` | 去掉扩展名 |
| `path_is_abs(p)` | `/` 开头或 `C:` 盘符开头 |

`/` 与 `\` 都当分隔符（Windows 路径可直接用），输出统一 `/`。

## 实现要点

- **clean 用栈**：按 `/` 切段，`..` 弹栈；绝对路径弹空后不再压 `..`（`/..` → `/`），
  相对路径保留（`a/../../b` → `../b`）。空输入返回 `.`（POSIX 口径）。
- **ext 只认最后一个点且点不能在开头**：`a/b.tar.gz` → `gz`，`.gitignore` → 空，
  `a/b.` → 空。
- **join 先判绝对**：`path_join("/srv", "/etc/passwd")` 返回 `/etc/passwd`，
  而不是拼成 `/srv/etc/passwd`——这是最容易踩的一条。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/path.qma` | **新增**：7 个公开函数 + 2 个内部辅助（`pth_is_sep` / `pth_with_sep`） |
| `tests/t114_path.qma` | **新增**：join 五种、clean 八种（含 `/..`、`a/../../b`、空串）、dir/base、ext/stem 六种、is_abs、反斜杠 |
| `tests/run_win_tests.py` | 注册 `t114_path` |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 |
| `docs/03-stdlib.md` | 重新生成：56 个模块 / 374 个公开函数 |
| `docs/06-status.md` | 回归数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.76.0 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/t114_path.qma` | 30 条断言全过 |
| `python tests/run_win_tests.py` | PASS=217 FAIL=0 SKIP=1 |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（56 模块 / 374 公开函数） |
| 四道门禁 | 全 PASS |

## 已知边界 / 遗留

- 不解析符号链接、不展开 `~`、不做大小写不敏感比较（Windows 盘符除外）。
- `path_clean` 输出统一用 `/`，Windows 侧若需要 `\` 请调用方自行替换。
- `std/staticfile` 与 `std/mime` **还没有改用本模块**（它们各自的实现已通过测试，
  改造留到下次动它们时一起做，避免这版改动面扩散）。
