# v1.100 — 增量 / 并行编译：单元级内容寻址缓存 + 多源并行构建（工具链 ❌ → ✅）

- 日期：2026-10-24
- 任务：把工具链缺口表里唯一一条"每次全量"的 ❌ 做成绿的——
  改一个文件不要重编整个工程；一次编多个单元要能用上多核。
- 影响面：工具链（`qlm_cli.py`、新增 `qlm_cache.py`）、文档、回归

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_cache.py` | **新增**。单元级内容寻址缓存：键 = `schema` + 编译器指纹（`tools/stage0/*.py` 全部内容哈希）+ `target` + 优化/调试开关 + 主文件内容 + **源根目录清单**（`std/`、`[src].lib`、`[src].ref` 的 `.qma` 名字+大小，堵"新增遮蔽文件"）+ `QLM_*` 环境快照。命中另需过两道校验：闭包内逐文件 sha256、产物 sha256。闭包用 `sys.addaudithook` **观测**编译器真正 open 过的文件（不重新实现 import 解析）。闭包为空则不写缓存。附 `stats/prune/clear` |
| `tools/stage0/qlm_cli.py` | ① `build` 返回 `(out, size, cfg, info)`，新增缓存命中/重编状态行；② `build` 支持**多源**（`src...`）+ `-j` 并行（进程池，输出按输入顺序）；③ `test` 加 `-j`（并行编译+执行）与 `--no-cache`，单文件逻辑抽成模块级 `_test_unit`；④ 新 `cache` 子命令（`--stat` / `--clear` / `--prune DAYS`）；⑤ **懒加载编译器**：去掉模块级 `from qlm import ...`，`import qlm` 的 1.3 s 不再算在每条命令头上（缓存命中路径因此才可能快） |
| `tests/cache_test.py` | **新增**回归 24 条：冷/热、改主文件、改被 import 的模块、**改回原样命中旧条目**、闭包内容（含/不含未 import 的文件）、开关隔离、`--no-cache`/`QLM_NO_CACHE`、产物截断判损坏、`--stat`/`--clear`、**串行与并行输出逐行一致** |
| `tests/run_win_tests.py` | `[8]` 组注册 `cache_test.py`（与 cov/fuzz 同一形状：子进程跑、末行计数） |
| `tools/dev/incr_bench.py` | **新增**性能探针：单单元冷/热（墙钟 + 编译阶段两个口径）、多源 `build -j`、`test -j`、进程创建基线 |
| `.gitignore` | 忽略 `.qlmcache/` |
| `docs/05-toolchain.md` | 新增 §1.7（缓存键六项、闭包怎么来的、并行粒度、边界）；命令表加 `cache` 行与 `build`/`test` 的新参数 |
| `docs/06-status.md` | 新增 §3.14 实测（单单元 6.1–43.7×、16 单元并行 2.2×/2.9×、进程创建基线） |
| `docs/07-gaps.md` | §3 表 `增量 / 并行编译` ❌ → **✅ v1.100**（含边界）；`.qla` 行改成"无法**函数级**增量"；§8 推进顺序更新 |
| `docs/04-compiler.md` | §1 流水线后补一段：整条链路可被 CLI 层缓存跳过，闭包是观测出来的 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=267 FAIL=0 SKIP=1**（SKIP = WSL 交叉验证，本机被安全策略拦；`cache_test` 已注册进 `[8]` 调试链路组） |
| `python tests/cache_test.py` | **CACHE: PASS=24 FAIL=0** |
| `python tools/dev/incr_bench.py` | 见 `06-status.md` §3.14 |
| `python tools/dev/check_docs.py` | PASS |
| `python tools/dev/check_names.py` / `check_origin.py` | PASS |

## 已知边界 / 遗留

- **不是目标文件格式**：没有 `.qla` 就没有函数级增量，也不能"只重编变了的模块
  再链接"。这里省掉的是**整个单元**的编译；跨单元复用不做。
- **单文件内部不并行**：并行粒度是单元。一个超大文件仍然单进程串行。
- **并行收益受进程创建限制**：本机 `python -c pass` 就要 1.23 s，8 并发的
  天花板约 3.3×；轻单元下"串行 + 缓存"反而更快，所以默认并发上限取 8 而不是核数。
- **源根目录清单变化会让全部条目失效**：故意的（新增同名文件会改变 import 解析）。
- **`-j` 只在 `build`（多源）与 `test` 上**：`run`/`debug`/`cov` 是单单元命令，
  加并发没有意义。
- 版本号取 v1.100 是为了让 `VERSION` 与最新版本目录同源（此前 `VERSION` 已到
  1.99 而 `docs/versions/` 只到 v1.82，门禁是红的）。语言层那条轨若继续追加版本，
  合并方按同源规则再对齐一次即可。
