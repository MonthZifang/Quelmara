# v2.01 — `std/kv` 批量提交（写路径 6.1×）+ 文档口径全面对齐

- 日期：2026-10-24
- 任务：用户要求"优化性能 + 更新实际文档"。性能取 v1.102 自己留下的下一步
  （`07-gaps.md` §2 持久化行的"批量提交"）；文档对齐 v1.102 之后审计出的 7 处漂移，
  并在核对"哪些模块真能用"时发现 10 个标准库模块缺 `pub`（登记为 §7.13，本版不修）。
- 影响面：标准库（`std/kv`）、工具链（`gen_stdlib_doc.py`）、文档

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/kv.qma` | **批量提交**：`Kv` 增 `pending: vec[str]` + `_BATCH = 64`；`kv_put`/`kv_del` 只入缓冲，满 64 条 `_flush` 合并成一次 `WriteFile`；`kv_sync`/`kv_close`/`kv_compact` 前先冲刷；`kv_file_size` 把未落盘字节算进"逻辑日志大小"。磁盘格式、重放、压缩语义**一字未改** |
| `bench/kv_bench.qma` | 口径注释：put 不再是"每条一次 WriteFile"，`put+sync` 一栏注明是单条提交口径 |
| `tools/dev/gen_stdlib_doc.py` | **§1 模块总览表改为生成物**（`<!-- overview:begin/end -->`）：手写那张表曾只列 33 / 60 个模块，而 `--check` 只比 §3，漏了也查不出来。零 `pub` 模块给一行说明而不是空白 |
| `docs/03-stdlib.md` | 重新生成（60 模块 / 406 公开函数 / 535 内部）；§1 总览补齐 27 个漏掉的模块；§2 改掉"import 扁平合并、没有命名空间"（v1.99 已做 per-module mangling）并补"跨模块引用要求 pub" |
| `docs/06-status.md` | §3.16 改成**同机同日 A/B 表**（16.5 → 2.7 µs/条）；§1 文档门禁 58/387/385 → **60/409/406**；§3.8b doc 扫描复测（60 文件 / 5.6 ms）；§6 新增"10 个模块缺 pub"风险行；调试器版本号 v1.79 → **v1.75** |
| `docs/07-gaps.md` | §2 **正则 ❌ → ✅ v1.57**（`std/regex` 早就在，缺口表在低估自己）；持久化边界补批量提交与崩溃窗口；数据结构/路由两行按审计结果改 🟡；§5 增"KV 批量提交 ✅"；**新增 §7.13**（10 个模块缺 pub + 4 个模块解析失败）；§8 标准库剩余项重写（原来列的多半已完成） |
| `docs/05-toolchain.md` | §5.1 夹具计数 139/67/18/23 → **142/67/18/24**；§5.2 补 `tests/kv_test.py`、`tools/dev/link_bench.py`、`tools/dev/selfhost_status.py` |
| `docs/04-compiler.md` | §2 模块表行数全部重测（qlm.py 6009→8005、qlm_native 9892→11563、qlm_dbg 147→**1254**），补 `qlm_index`/`qlm_lsp`/`qlm_cache`/`qlm_dwarf`/`qlm_dbinfo`/`qlm_fuzz` 六行 |
| `docs/01-overview.md` | §4 去掉会漂的计数与行数（88/12/39/10、4.5k/8.7k…），改指 `05-toolchain.md` §5.1 与 `04-compiler.md` §2——**同一事实只留一处权威表述** |
| `docs/versions/v1.80/CHANGELOG.md` | 交叉引用 `v1.79` → `v1.75`（调试器实际版本号；`docs/versions/v1.79` 从来不存在） |
| `tools/stage0/qlm_cli.py` | `VERSION` → `2.01.0`（与最新版本目录同源） |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=275 FAIL=0 SKIP=1**（SKIP = wsl.exe 被沙箱安全策略拦，与 v1.102 同口径） |
| `python tests/kv_test.py` | **KV: PASS=10 FAIL=0**（撕裂尾 / 垃圾尾 / Python 独立解析器对拍磁盘格式） |
| `python tools/stage0/qlm_cli.py run tests/t127_kv.qma --target win` | 退出码 0，打印 `kv ok`（含 `kv_file_size` 与 `kv_compact` 的"压缩前字节数"断言） |
| `python tools/stage0/qlm_cli.py run bench/kv_bench.qma --target win` | 见 `06-status.md` §3.16（3 次取中位） |
| `python tools/dev/gen_stdlib_doc.py --check --require-doc` | **PASS：60 个模块 / 406 个公开函数**，文档与源码一致 |
| `python tools/stage0/qlm_cli.py doc std --missing` | **PASS：60 个模块 / 409 个公开声明**全部有 `///` |
| `python tools/dev/check_docs.py` / `check_names.py` / `check_origin.py` | 全 PASS |

## 已知边界 / 遗留

- **批量提交的崩溃窗口**：进程被强杀时最多丢最后不足 64 条（`WriteFile` 进内核后不丢，
  掉电仍要 `kv_sync`）。已写进 `std/kv.qma` 头注释与 `07-gaps.md` §2。
- **`kv_sync` 没有变快**（384 µs/条）：每次 sync 都要先把缓冲冲刷干净，这是"每条都等落盘"
  的固有代价。真实用法是写一批、sync 一次。
- **`std` 有 10 个模块 0 个 `pub` 导出、4 个模块解析失败**（`http`/`ws`/`sse` 的局部变量
  叫 `rc` 撞关键字；`timer` 用顶层 `let` 存模块状态）。本版只登记（`07-gaps.md` §7.13），
  没修：补 `pub` 要连带 141 个声明的 `///`，是独立一版的工作量。
  `03-stdlib.md` 里这 10 个模块因此不再列签名（它们本来就不是公开 API），改为一行说明。
- **`docs/versions/` 缺号**：v1.46 / v1.49 / v1.52 / v1.54 / v1.79 / v1.86 / v1.88 / v1.89 / v1.90
  没有目录（历史按版本重建时的遗留，其中 v1.79 是笔误、真实版本是 v1.75）。`check_docs.py`
  只校验"已存在的目录里有 CHANGELOG"，不校验"每个版本号都有目录"。
- **与并行轨的交错**：v2.00（1.x 缺口线收口的里程碑，零功能改动）由另一会话在本版之前
  落地。v2.00 日志里"KV 批量提交顺延为 2.x 首个功能版 / §3.16 改为列入后续版本"的措辞，
  由本版取代——批量提交已在 v2.01 实测落地，§3.16 现在是 A/B 表。
- `tests/bad/{derive_enum,derive_f64,refl_dynidx}.qma` 三个失效夹具的删除仍未提交
  （等用户决定去留）；`05-toolchain.md` §5.1 的 67 个负向夹具按工作区口径记。
