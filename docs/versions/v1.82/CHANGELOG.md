# v1.82 — 行覆盖率：`quelmara cov`，汇总工具用 Quelmara 自己写

- 日期：2026-10-23
- 任务：`07-gaps.md` §3「覆盖率 / fuzz」❌ → 🟡。同时也是**工具链自举**的一步：
  汇总工具不写 Python，用自研语言写（`tools/qlm_cov.qma`）。
- 影响面：工具链（`tools/qlm_cov.qma` 新增、`qlm_dbg.py` 采集模式、`qlm_cli.py`
  `cov` 子命令）、测试、文档
- 注：v1.81 被另一条轨（自举 parser 的 `@derive`）占用，本版顺延为 1.82

## 为什么用 Quelmara 写

覆盖率工具要同时吃**二进制**（PE 节表）和 **JSON**（`.qlmdbg`）——正好是检验
"自研语言能不能干工具链的活"的最小样本。跑通之后，工具链里所有"只读分析"类
工具（依赖图、符号表、体积分析、覆盖率）都能照这个形状写，不用再往 Python 里堆。

只有"采集"那一段必须留在 Python：它要 Windows 调试 API（`CreateProcess` /
`WaitForDebugEvent` / `GetThreadContext`），自研后端还没有 FFI。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/qlm_cov.qma` | **新增（Quelmara 写，约 200 行）**：读 PE → 找 `.qlmdbg` → `std/json` 解析行表 → 读命中 TSV → 按**唯一行号**算覆盖率 → 打印报告 + 未覆盖行；`--min` 不达标退出码 1 |
| `tools/stage0/qlm_dbg.py` | 新增 `coverage()` + `--cov TSV`：每个源码行入口下一个断点（静默），跑到退出，写 `rva<TAB>hits` 文本 |
| `tools/stage0/qlm_cli.py` | 新增 `cov` 子命令：`--dbg-info` 构建 → 采集 → 调 Quelmara 工具汇总（三段一条命令） |
| `tests/cov_test.py` | **新增**：未覆盖行检出（`cov.qma` 的 `return 1` 那行）、100% 场景、`--min` 不达标退出码 1 |
| `fixtures/dbgdemo/cov.qma` | **新增**：覆盖率固定靶（`if n > 10` 只走 else 支） |
| `tests/run_win_tests.py` | `[8] 调试链路` 组加第三项（行覆盖率） |
| `docs/05-toolchain.md` | §1 命令行加 `cov`；**新增 §1.2 行覆盖率**（三段分工 + 口径 + 为什么用自研语言）；§5.2 登记 `cov_test.py` |
| `docs/07-gaps.md` | §3「覆盖率 / fuzz」❌ → 🟡（行覆盖 ✅，分支/合并/fuzz 仍缺）；§8 推进顺序同步 |

## 实现要点（Quelmara 侧踩的坑）

- **`vec` 不能用 `[]` 下标**：`args()` 返回的是切片（支持 `a[i]`），但
  `str_split` 返回的是 `vec[str]`，只能 `.get(i)`。写错会得到
  "下标只能用于定长数组、切片或 str"，位置在 let 初始化处，不容易一眼看出。
- **Windows 文本行尾是 `\r\n`**：按 `\n` 切完还剩 `\r`，`to_int` 直接 fail-fast。
  工具里加了 `chomp()` 去尾字节——这类"平台差异"在自研语言里同样要显式处理。
- **PE 解析只用到 4 个字段**：`e_lfanew`(0x3C) → COFF → `NumberOfSections` /
  `SizeOfOptionalHeader` → 节表每 40 字节取 `VirtualSize`/`VirtualAddress`/
  `PointerToRawData`。长节名（`/N`）不处理：`.qlmdbg` 只有 7 字节。
- **分母只算行表里的行**：空行/注释行/纯声明行没有行表项，不该拉低覆盖率。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/cov_test.py` | **PASS=8 FAIL=0**（4/5 + 未覆盖行 9 + 100% + 阈值退出码 1） |
| `python tests/run_win_tests.py` | **PASS=222 FAIL=0 SKIP=1**（SKIP=WSL 交叉验证，本机沙箱拦） |
| `python tools/stage0/qlm_cli.py cov fixtures/dbgdemo/cov.qma` | `行: 4/5 (80.0%)`，`未覆盖行: 9` |
| `python tools/dev/check_docs.py` 等四道门禁 | PASS |

## 性能

采集开销 = 每次断点命中（见 `06-status.md` §3.8，约 140–160 µs）+ 行数 × 一次
断点设置。`cov.qma`（5 行）整条命令约 2.2 s，其中构建占 ~2 s、调试会话 ~0.15 s；
汇总工具本身（读 14 KB PE + 解析 JSON + 计数）在 10 ms 量级——**不是瓶颈**。

> 大文件（数千行）会线性变慢：断点数量 = 行表项数，每命中一次就是一次调试事件
> 往返。真要大项目跑覆盖率，得换成"编译期插桩 + 共享内存计数"（不经过调试器），
> 那是另一个量级的工作，本版没做。

## 已知边界 / 遗留

- **不是分支覆盖**：只走一条分支也能到 100%。分支/条件覆盖需要 CFG，没有。
- **不做增量合并**：多次运行的命中不能累加（每次覆盖写 TSV）。
- **只统计主文件**：`.qlmdbg` 只收主文件；库函数行号属于别的文件。
- 大文件慢（见上）；没有函数级/目录级汇总，只有单文件。
- fuzz 仍未做。
