# v1.73 — HTTP 日期 `std/httpdate`（补上静态文件的 Last-Modified 遗留）

- 日期：2026-10-23
- 任务：`07-gaps` §2 静态文件那行遗留的 **Last-Modified / If-Modified-Since**——
  缺的不是逻辑，是"epoch 秒 ↔ RFC 7231 IMF-fixdate"的换算。
- 影响面：标准库（`std/httpdate.qma`，全部用 Quelmara 写）、测试、文档

## 新增 API

| 函数 | 说明 |
|---|---|
| `httpdate_format(epoch) -> str` | UTC 秒 → `Sun, 06 Nov 1994 08:49:37 GMT` |
| `httpdate_parse(s) -> int` | 反向；格式不对返回 -1 |
| `httpdate_not_modified(mtime, since) -> bool` | `mtime <= since` 即可回 304 |

## 实现要点

- **Howard Hinnant 的 days-from-civil 算法**：纯整数、无查表、无时区，
  闰年/世纪规则自动正确（测试覆盖 2000-02-29、2004-02-29、2008-12-31 23:59:59）。
- **星期用 `(days + 4) % 7`**：1970-01-01 是周四，偏移 4 后 0=周日。
- **没有 str 数组字面量**：`let names = ["Sun", ...]` 会报"数组元素暂只支持数值"，
  所以星期/月份都写成 if 链（与标准库其它模块一致）。
- **四位年份要单独解析**：一开始复用两位解析函数，`len != 2` 直接返回 -1，
  于是 1994 被当成 19 年——解析结果差了 71 万年。测试里的往返用例钉住了这条。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/httpdate.qma` | **新增**：3 个公开函数 + 8 个内部辅助（civil 换算、补零、月份/星期映射） |
| `tests/t112_httpdate.qma` | **新增**：已知时间点、闰日/年末边界、解析与往返（12 组）、If-Modified-Since 四种情形 |
| `tests/run_win_tests.py` | 注册 `t112_httpdate` |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 |
| `docs/03-stdlib.md` | 重新生成：54 个模块 / 363 个公开函数 |
| `docs/07-gaps.md` | §2 静态文件行：Last-Modified 不再缺（`file_mtime` 内建仍缺） |
| `docs/06-status.md` | 回归数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.73.0 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/t112_httpdate.qma` | 30 条断言全过 |
| `python tests/run_win_tests.py` | PASS=215 FAIL=0 SKIP=1（数字含另一条轨同期新增的用例） |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（54 模块 / 363 公开函数） |
| 四道门禁 | 全 PASS |

## 已知边界 / 遗留

- 只认 IMF-fixdate；不认废弃的 RFC 850（`Sunday, 06-Nov-94`）与 asctime 格式
  （浏览器发的是 IMF-fixdate，够用）。
- 不处理闰秒；`epoch < 0` 在格式化时按 0 处理。
- **`static_serve` 还没用上它**：需要 `file_mtime(path)` 内建才能填 Last-Modified，
  那是编译器侧的事（另一条轨）。本版先把换算做扎实。
