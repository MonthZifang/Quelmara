# v1.83 — 覆盖率补齐：分支覆盖 + 函数/文件级 + 增量合并，外加 fuzz

- 日期：2026-10-24
- 任务：`07-gaps.md` §3「覆盖率 / fuzz」🟡 → ✅。把 v1.82 只做行覆盖的链路
  一次补全：**分支覆盖**、**函数级 / 文件级汇总**、**多次运行的增量合并**、**fuzz**。
- 影响面：工具链（编译器调试信息、调试器采集、两个 Quelmara 写的工具、CLI）、
  测试、文档
- 注：本版号取 v1.82（行覆盖）之后的第一个空位。语言轨同时在推进 v1.84–v1.96
  （所有权视图 / `@simd` int 点积 / FFI / `Drop` / LSP），两轨共享连续版本号，
  工具链轨从 v1.82 接着走。

## 为什么一次做完

行覆盖单独存在时会给出**假绿**：`if` 只走一条支，行覆盖照样能到 100%。
分母不可信，`--min` 门禁就没有意义。所以这一版把"分母"一次补齐：

| 维度 | v1.82 | v1.83 |
|---|---|---|
| 行 | ✅ 唯一行号 | ✅ 不变 |
| 分支 | ❌ | ✅ 每条 `jcc` 两条边（跳 / 不跳） |
| 汇总粒度 | 单文件 | 整体 + 函数级 + 文件级 |
| 多次运行 | 每次覆盖写 | `--append` 按 rva/边累加 |
| fuzz | ❌ | ✅ 前端模糊测试（变异器用 Quelmara 写） |

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 发射 `jcc` 时登记分支表（`off, 目标标签, 条件码, 源码行`）；`_dbg_resolve_branches()` 把标签解析成偏移，并**只保留跳转目标为语句入口的源码级分支** |
| `tools/stage0/qlm_pe.py` | `gen_all_pe()` 里接上分支表解析（PE 走的是自己的 `gen_all`，不走 `qlm_native.gen_all`） |
| `tools/stage0/qlm_dbg.py` | `coverage()` 重写：行入口 + `jcc` 合成一个断点集合；命中时按 EFLAGS 判定跳没跳，写 `L`/`E` 两种记录（TSV v2）；新增 `cc_taken()` 与 `--cov-lines-only` |
| `tools/qlm_cov.qma` | 重写（Quelmara 写）：行 + 分支 + 函数级 + 文件级 + 未覆盖行/分支清单；`--min` / `--min-branch` / `--merge-out` / `--no-branch`；多份命中日志求和；兼容 v1.82 的 `rva<TAB>hits` 旧格式 |
| `tools/qlm_fuzz.qma` | **新增**（Quelmara 写，约 200 行）：确定性 LCG 变异器，7 种算子，只改 ASCII 字节；写 `case_NNNN.qma` |
| `tools/stage0/qlm_fuzz.py` | **新增**：调变异器 → 进程内编译每个用例 → 五分类（built/rejected/deep/bug/slow）→ 报告 + 复现命令；`bug` 退出码 1 |
| `tools/stage0/qlm_cli.py` | `cov` 加 `--min-branch` / `--append` / `--lines-only` / 程序参数透传；新增 `fuzz` 子命令；工具 exe 按 mtime 复用（不再每次重编） |
| `tests/cov_test.py` | 重写：23 条断言（行/分支/函数级/两种门禁/增量合并/`--lines-only`） |
| `tests/fuzz_test.py` | **新增**：12 条断言（同 seed 逐字节一致、变异生效、合法 UTF-8、五分类口径、端到端） |
| `tests/run_win_tests.py` | `[8] 调试链路` 组加"模糊测试"一项，覆盖率项改名为"行+分支覆盖率" |
| `fixtures/dbgdemo/cov2.qma` | **新增**：增量合并夹具（分支由命令行参数决定） |
| `tools/dev/cov_bench.py` | **新增**：覆盖率/fuzz 性能探针（分支表体积、采集开销、汇总耗时、fuzz 吞吐） |
| `docs/05-toolchain.md` | §1 命令表加 `fuzz`、`cov` 参数补全；§1.3 重写为"行 + 分支"（分支口径/合并/边界）；**新增 §1.4 模糊测试**；§5.2 登记两个脚本；§7 加 fuzz 到开发循环；顺手修掉重复的 `### 1.3` 编号 |
| `docs/06-status.md` | §1 覆盖率行更新、新增 fuzz 行；**新增 §3.12 覆盖率与 fuzz 的性能口径** |
| `docs/07-gaps.md` | §3「覆盖率 / fuzz」🟡 → ✅；§8 推进顺序同步；**新增 §7.11**（fuzz 发现的非 UTF-8 缺陷） |

## 实现要点（踩到的坑）

- **`substr(s, lo, cnt)` 的第三参是长度，不是结束下标**。第一版变异器按"结束
  下标"写，`substr(s, i+1, n)` 直接 fail-fast（`substr() range out of bounds`）。
  这个坑值得记：报错位置在 let 初始化处，看不出是实参语义错。
- **`int3` 不改 EFLAGS**，所以分支判定不需要单步：断点打在 `jcc` 首字节，
  命中时读到的 EFLAGS 就是这条 `jcc` 将要判定的那份。比"命中后再单步看 RIP"
  少一半事件（实测每次分支命中 ~0.67 ms，含 int3 回填那一步）。
- **分支表要在 PE 后端解析**：`qlm_native.gen_all()` 只服务 ELF；PE 走
  `qlm_pe.WinCodegen.gen_all_pe()`。第一版只改了前者，覆盖率一直显示旧表
  （分支数不变），排查了半天。
- **只收源码级分支**：目标必须是语句入口。否则 `assert` 失败块、定长数组越界
  检查的 panic 块、`args()` 展开的拷贝循环、`@simd` 内联循环都会被算进分母。
  实测 `tests/t64_math.qma` 49 条 jcc 里 41 条是源码分支；`tools/qlm_cov.qma`
  119 条里只剩 37 条（工具代码越重，机械跳转越多）。
- **变异只落在 ASCII 字节上**：种子文件里的中文注释被切一半就变成
  `UnicodeDecodeError`，第一版 16 例里 11 例全是这个，真信号被淹掉。
- **`os.remove` 在本机被沙箱改写成回收站操作**（`SHFileOperationW` 失败），
  变异器改成"覆盖写、不清旧用例"，用例集合由本次生成的路径表决定。
- 增量缓存（`qlm_cache`）会跟随编译器源码变化，`--dbg-info` 构建命中时只要
  188 ms——所以 `cov` 的重复跑并不慢，慢的是调试会话本身。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/cov_test.py` | **PASS=23 FAIL=0** |
| `python tests/fuzz_test.py` | **PASS=12 FAIL=0** |
| `python tests/run_win_tests.py` | **PASS=266 FAIL=0 SKIP=1**（SKIP=WSL 交叉验证，本机被沙箱拦；总数含语言轨同期新增的 3 项） |
| 调试链路组（`test_debug_chain()`：DWARF 20 + 调试器 40 + 覆盖率 23 + fuzz 12） | **PASS=4 FAIL=0** |
| `python tests/emitdiff.py` | **PASS=10 FAIL=0**（发射层确定性不受分支表影响） |
| `python tools/stage0/qlm_cli.py test tests/selftest.qma --target win` | PASS=1 FAIL=0 |
| `python tools/stage0/qlm_cli.py cov fixtures/dbgdemo/cov.qma` | 行 4/5 (80.0%)、分支 1/2 (50.0%)、未覆盖分支 `8->9` |
| `python tools/stage0/qlm_cli.py cov fixtures/dbgdemo/cov2.qma --hits h.tsv --append -- 20` | 两次运行合并后 行 8/8、分支 4/4 |
| `python tools/stage0/qlm_cli.py fuzz tests/t64_math.qma --cases 40 --seed 11..15` | 200 例，崩溃 0 |
| `python tools/dev/cov_bench.py` | 见 `06-status.md` §3.12 |
| `check_names.py` / `check_origin.py` / `check_docs.py` | PASS（校验时 `VERSION`=1.98.0 与 `v1.98` 对齐；此后语言轨把 `VERSION` 顶到 1.99 而目录尚未建，属其在途状态） |

> 全量回归跑了两遍：第一遍卡在 `[3j] IOCP reactor`（固定端口 19531，同一工作区里
> 语言轨并行跑同一套回归把端口占了，客户端等不到回声且没有超时），换时机重跑后
> 一次通过 266 项。

## 性能

数字与口径见 `06-status.md` §3.12（本机 VBS 噪声 ±50%，只做纵向比较）。要点：

- 分支表的体积代价可忽略：`main.qma` 的 `.qlmdbg` 3111 B 里分支表 241 B。
- 采集成本与"命中次数"成正比：`loop.qma`（5000 次循环）会话 11.8 s，
  其中分支断点贡献 ~0.8 s / 1251 次命中。
- 汇总工具本身很快（净 70–140 ms），整条链路的成本在**调试会话**，不在统计。

## 已知边界 / 遗留

- **不做条件级 MC/DC**：`&&` / `||` 的子条件按各自的 `jcc` 自然计数，
  没有"每个条件都取过 true 和 false"这种独立分母。
- **`assert(cond)` 算一条分支**（成立边=正常路径，不成立边=中止块），所以
  assert 密集的测试文件分支覆盖率停在 ~50%：`tests/t64_math.qma` 41/82。
  与 gcov / llvm-cov 同口径，门禁要按文件分级设阈值。
- **大文件线性慢**：断点数量 = 行表项数 + 分支数，每命中一次一个调试事件往返。
  真要给大项目跑覆盖率，得换"编译期插桩 + 共享内存计数"，本版没做。
- **fuzz 默认只跑前端**（`--emit` 才连后端），且不是覆盖率引导的（无 AFL 式
  feedback loop），靠用例数量堆概率。
- **单例死循环无法在进程内中断**（Python 无线程级 kill）：靠 `--max-seconds`
  与测试侧 `subprocess` 超时兜底。
- **非 UTF-8 源文件**抛 `UnicodeDecodeError` 而不是干净诊断——fuzz 发现的既有
  缺陷，已登记 `07-gaps.md` §7.11，本版不动语言轨正在改的文件。
- 命中计数**不保证等于执行次数**（每次命中后要单步回填 int3，密集断点会少计）；
  覆盖率是二值判断，不受影响，但别把 `hits` 当执行次数用。
