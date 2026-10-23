# v1.74 — CSV 解析与生成 `std/csv`

- 日期：2026-10-23
- 任务：标准库补 CSV（RFC 4180）。导数据、读配置、测试夹具都靠它，
  之前每个示例自己 `split(",")`，一遇到引号里的逗号或换行就错。
- 影响面：标准库（`std/csv.qma`，全部用 Quelmara 写）、测试、文档

## 新增 API

| 函数 | 说明 |
|---|---|
| `csv_parse(text) -> vec[vec[str]]` | 解析成二维表；CRLF / LF 都接受；空行跳过 |
| `csv_build(rows) -> str` | 生成；只给含 `,` `"` CR LF 的字段加引号；行间 CRLF |
| `csv_col(row, i) -> str` | 取第 i 列（越界/负下标返回空串） |
| `csv_find_row(rows, col, value) -> int` | 按某列找行号；找不到 -1 |

## 实现要点

- **状态机**：`inq`（在引号内）+ `pending`（当前行已有内容）。后者专门处理
  `"a,,c"` 这种中间空字段——只靠"buffer 非空"会把空字段吞掉。
- **`""` 转义**在引号态里特判：遇到 `"` 时先看下一个字符是不是 `"`。
- **CRLF 与 LF 都认**，且 CRLF 只跳一次（不是把 `\r` 和 `\n` 各当一次行尾，
  否则会产生空行）。
- **生成侧只给需要的字段加引号**，避免 `a,b` 变成 `"a","b"`；行间用 CRLF
  与 Excel 一致。
- `vec` 有 `clear()`（map 没有），所以逐字段复用同一个字节缓冲。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/csv.qma` | **新增**：4 个公开函数 + 2 个内部辅助（`csv_need_quote` / `csv_quote`） |
| `tests/t113_csv.qma` | **新增**：基本解析、引号内逗号、`""` 转义、字段内换行、空字段、末行无换行、空输入、生成与往返、`csv_col` 越界、`csv_find_row` |
| `tests/run_win_tests.py` | 注册 `t113_csv` |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 |
| `docs/03-stdlib.md` | 重新生成：55 个模块 / 367 个公开函数 |
| `docs/06-status.md` | 回归数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.74.0 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/t113_csv.qma` | 28 条断言全过 |
| `python tests/run_win_tests.py` | PASS=216 FAIL=0 SKIP=1 |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（55 模块 / 367 公开函数） |
| 四道门禁 | 全 PASS |

## 已知边界 / 遗留

- 不做列数校验（各行可以不等长）——真实 CSV 里常见，强行校验反而挡路。
- 只认 `,` 分隔；`;` / `\t` 变体不做（TSV 需要的话再加参数）。
- 不剥离 UTF-8 BOM（会出现在第一个字段里，调用方自己 trim）。
- 不处理 `\r` 单独作行尾的老 Mac 格式（会当成行内字符）。
