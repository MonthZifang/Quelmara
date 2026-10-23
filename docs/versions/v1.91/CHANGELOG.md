# v1.91 — 语言服务器：语义索引 + 补全 / 跳转 / 重命名（工具链红标 → 绿）

- 日期：2026-10-24
- 任务：把 `07-gaps.md` §3 的 `LSP / 补全 ❌` 一次补完（语义索引、补全、跳转、
  引用、重命名、悬停、大纲），同步文档并给出性能口径；**只动工具链**
- 影响面：工具链（新增两个模块 + CLI 子命令 + 测试 + 夹具）、文档

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_index.py` | **新增**。位置感知词法（与 `qlm.tokenize` 同构，多记偏移）+ 容错结构索引（顶层/成员/局部/引用四层）+ 查询 API（补全/定义/引用/重命名/大纲/诊断）+ 工作区跨文件解析（import → pub 符号） |
| `tools/stage0/qlm_lsp.py` | **新增**。LSP 3.17 子集服务（stdio JSON-RPC）：completion / hover / definition / references / prepareRename / rename / documentSymbol / documentHighlight / workspace symbol / publishDiagnostics；离线子模式 `--index` `--symbols` `--at` `--completions` `--check` |
| `tools/stage0/qlm_cli.py` | 新增 `lsp` 子命令（参数转发给 `qlm_lsp`）；`version` 的工具列表补 `lsp` |
| `tests/lsp_test.py` | **新增**。五段回归：词法对拍（全仓库）/ 容错索引 / 索引语义 / 真 JSON-RPC 协议 / 性能阈值 |
| `tests/run_win_tests.py` | 主回归新增 `[10]` 段，把 `lsp_test.py` 汇总成一项 |
| `fixtures/lspdemo/` | **新增**端到端夹具（`main.qma` + 被导入的 `util.qma`），同时是一份**能编译运行**的工程 |
| `docs/05-toolchain.md` | 新增 §1.4 语言服务器；CLI 表、脚本表、夹具表补行 |
| `docs/06-status.md` | §1 补语言服务器回归行；新增 §3.10 索引与补全性能 |
| `docs/07-gaps.md` | §3 的 LSP 行红 → 绿（写明边界）；§6 P2 / §8 顺序同步 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/lsp_test.py` | `PASS=38 FAIL=0`（含 321 个源文件 / 213208 个记号的词法对拍，分叉 0） |
| `python tests/run_win_tests.py` | 见 `06-status.md` §1（本版新增 `[10]` 一段，其余各段不变） |
| `python tools/dev/check_docs.py` | PASS（完成时 `VERSION` 与 `v1.91` 对齐） |
| `python tools/dev/check_names.py` / `check_origin.py` | PASS |

## 已知边界 / 遗留

- **版本号由并行轨持有**：本版完成时 `VERSION = 1.91.0`、门禁同源通过；随后并行轨
  推进到 1.92/1.93/1.94 并接管 `VERSION`（`versions/v1.87`、`v1.92` 的日志里也记了
  这件事）。按 `00-convention.md` §5.1 的口径，`VERSION` 以**最新版本目录**为准，
  两边不要各留一半。

- **诊断只到词法/结构层**：非法字符、未闭合字符串、括号不配对、顶层重名。
  类型错误、未定义函数不报——那需要完整前端，而 `qlm.Parser` 在编辑器场景
  不可用（一个语法错误就整篇失效，见 `05-toolchain.md` §1.3）。
- **索引不做类型检查**：`.` 之后的成员靠语法推断（形参/`let` 标注/字面量/
  构造器/返回值），推不出来就是"未知"，补全退化为本文件成员、不猜。
- **增量索引没做**：`didChange` 整篇重建（1.7k 行文件 ~100 ms）。再大的文件
  要上增量或 debounce，登记在 `07-gaps.md` §3。
- **重命名只改解析得到的引用**：接收者类型未知的 `.field` 只有在"该字段名
  在本文件唯一"时才一并改；跨文件时按需索引工作区（首次较慢）。
- **不发 PDB、不做代码格式化/语义高亮**（`fmt` 已有独立命令，语义高亮需
  客户端 token 主题，未做）。
