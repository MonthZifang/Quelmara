# v1.92 — 文档生成：`///` doc comment 从语法到门禁（工具链红标 → 绿）

- 日期：2026-10-24
- 任务：把 `07-gaps.md` §3 的 `文档生成 ❌ 无 doc comment 语法` 一次补完——语言层定义
  `///`、前端把文档挂到声明上、`quelmara doc` 生成 Markdown/JSON、std 全库补齐文档、
  覆盖率与漂移门禁进 CI，同步文档并给出性能口径。**主要改动在工具链。**
- 影响面：语言层（前端新增行扫描，**不改记号流**）、工具链（新模块 + CLI 子命令 + 测试 + 门禁）、
  标准库（58 个模块的文档注释）、文档

## 为什么是它

`tools/dev/qlm_doc.py` 早在 v1.47 就存在，但它只是个**旁挂脚本**：语法没进语言参考、
编译器不认识 `///`、覆盖率没有门禁——所以缺口表一直挂 ❌。本轮把"脚本"补成"链路"：

```
/// 语法（一条实现）→ 前端挂载（AST 可读）→ quelmara doc（唯一消费方）→ 门禁（缺文档/漂移）
```

链路上每一段都有测试（`tests/doc_test.py` 31 项），不是"能生成就算完"。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | 新增 §1b：`scan_doc_comments`（`///` / `//!` / `////` / 脱离检测）与 `iter_decls`；`Parser(src=...)` 按行号把文档挂成 `f["doc"]` / `type_docs` / `module_doc`；`parse_source(with_docs=True)` 多返回 `(type_docs, module_doc)`，默认返回值不变。**记号流零改动**（`lexdiff` / `parsediff` 契约不动） |
| `tools/stage0/qlm_doc.py` | 新增（原 `tools/dev/qlm_doc.py` 迁入并重写）：签名/声明块截取、Markdown/JSON 渲染、`--check` 漂移、`--missing` 覆盖门禁、脱离块报告 |
| `tools/stage0/qlm_cli.py` | 新增 `doc` 子命令（退出码透传，可直接当门禁）；`VERSION` → 1.92.0 |
| `tools/dev/qlm_doc.py` | 删除（实现迁到 `stage0`，避免两套口径） |
| `tools/dev/gen_stdlib_doc.py` | 改为复用 `stage0/qlm_doc.py`；新增 `--require-doc`（公开声明缺文档即失败）；公开面改成"顶层 pub 声明"（含没写文档的，才能统计覆盖率） |
| `tools/dev/doc_bench.py` | 新增：全库扫描吞吐、词法基线占比、真实构建占比（`06-status.md` §3.8b 的数字出处） |
| `tests/doc_test.py` | 新增：语法规则 10 项 / 前端挂载 6 项 / 工具链 14 项 / 产物逐字节相同 1 项 |
| `tests/t119_doc.qma` | 新增夹具：`//!` + `///` + `////` + 非 pub 声明，自身是可运行程序（`test "doc"`） |
| `std/*.qma`（58 个模块） | 补齐 **387 个公开声明**的 `///`：171 处把原本紧贴声明的 `//` 说明改写成文档，其余按实现补写（参数/返回/边界）。只增删注释行，代码零改动 |
| `docs/03-stdlib.md` | 重生成：385 个公开函数全部带文档（原为 296 个函数、仅 8 个模块有文档） |
| `.github/workflows/ci.yml` | 两个 job 各加一步"文档生成门禁" |
| `docs/02-language.md` | §2.4 改写成「注释与 doc comment」：三种写法、五条细节、前端怎么认、产物无关 |
| `docs/05-toolchain.md` | CLI 表加 `doc`；新增 §1.2 文档生成（用法/输出形态/两个门禁模式/四条边界）；§5.2 加测试与探针；§5.3 与 §6 加门禁 |
| `docs/06-status.md` | §1 加 doc 链路与文档门禁两行、门禁改"五道"；新增 §3.8b 文档生成性能 |
| `docs/07-gaps.md` | §3「文档生成」❌ → ✅ v1.92（含边界）；§6 P2 路线里划掉该站 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=265 FAIL=0 SKIP=1**（SKIP 为 WSL 交叉验证，本机被沙箱拦）——doc comment 的插入没有引起任何失败 |
| `python tests/doc_test.py` | **PASS=31 FAIL=0** |
| `python tools/stage0/qlm_cli.py doc std --missing` | **PASS**：58 个模块 / 387 个公开声明全部有 `///`，0 个脱离块 |
| `python tools/dev/gen_stdlib_doc.py --check --require-doc` | **PASS**：58 个模块 / 385 个公开函数，`03-stdlib.md` 与源码一致 |
| `python tests/lexdiff.py` | **PASS=236 FAIL=0**（240 个源文件，4 个 SKIP；记号流没变） |
| `python tests/parsediff.py` | **PASS=150 FAIL=2**（152 个源文件；两个失败是并行轨在途的 interface/impl 夹具 `t118_iface_own` / `t116_iface_multi`，与本轮无关；本轮新增的 `t119_doc` 通过） |
| 全库词法自检（58 个 std 模块） | 58/58 通过（`tokenize` 无异常——注释插入没有破坏任何文件） |
| 代表性构建 | `examples/https_get.qma` / `tests/t69_tls_client.qma`（TLS 全链路）/ `fixtures/dbgdemo/main.qma` 全部构建成功 |
| `python tools/dev/check_docs.py` / `check_names.py` / `check_origin.py` | 三道门禁全 PASS |
| `python tools/dev/doc_bench.py` | 见 `06-status.md` §3.8b（全库 12–15 ms，词法的 2.5%，产物 +0 B） |

产物无关的强证据在 `tests/doc_test.py` 的最后一节：同一程序带与不带 doc comment，
编译出的 PE **逐字节相同**（`sha256` 相等）。

## 已知边界 / 遗留

- **只收顶层声明**：`impl` 内的方法文档没做（缩进的 `///` 按普通注释处理，不报错也不导出）。
  要做需要给 `impl` 块加文档归属，属下一轮。
- **不做交叉引用/链接检查**：文档正文里的 `[foo]` 就是普通文本，不解析、不校验目标存在。
- **不渲染 Markdown**：正文原样透出；标题层级（`##` 模块 / `###` 声明）由工具给。
- **全量不增量**：每次扫全库（12–15 ms，不值得做增量）。
- **`03-stdlib.md` 仍由 `gen_stdlib_doc.py` 生成**（模块顺序与一句话简介要人工登记），
  但扫描/解析与 `quelmara doc` 共用同一份实现，不会出现两套口径。
- 版本号：v1.89–v1.91 已被并行轨占用，本版取 **v1.92**；`VERSION` 与 `docs/versions/`
  最新目录同源（`check_docs.py` 强制）。
