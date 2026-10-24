# v2.13 — 引导层第一步：原生驱动器 + 两个静默误编译修复

- 日期：2026-10-24
- 任务：Python 引导层也换成我们自己的语言并优化速度（目标：编几 KB 的东西比 C 快 5 倍）
- 影响面：编译器（`vec` 下标、`exit` 退出码）/ 自举层（新 `bootstrap/driver/`）/ 文档

## 主事件

### 1. 先量清楚"Python 引导层"的账

| 步骤 | 本机实测（min of 3–5） |
|---|---|
| `python -c pass` | **561 ms** |
| `import qlm_native` | **1740 ms** |
| `qlm_cli version` | 911 ms |
| `build examples/hello.qma`（冷） | **2136 ms** |
| 同上（缓存命中） | 1071 ms |
| `hello.exe`（9 KB 产物） | 9216 字节 |

**关键发现**：本机对**任何**进程创建都要收 ~370 ms（`C:\Windows\System32\hostname.exe`
实测 380 ms、裸 Quelmara `hello.exe` 372 ms）。也就是说这台机器上"端到端比 C 快 5 倍"
**测不出来**——任何编译器的墙钟都被这 370 ms 淹没。能比的只有"编译器自己的活"。

### 2. 原生驱动器（`bootstrap/driver/qlm_drv.qma`）

`quelmara build x.qma` 的第一步是启动 Python；源码没变时编译器其实无事可做。
驱动器把**入口**换成 Quelmara：原生算"输入有没有变"（源文件 + import 闭包 +
编译器 5 个核心 .py + `Quelmara.toml` 的 mtime），没变就复用产物，变了才委托 stage-0。

| 路径 | 之前 | 现在 |
|---|---|---|
| 输入未变（`qlm build`） | 1071 ms | **3.8–6.6 ms 判定**（进程创建另计 ~370 ms） |
| 输入未变（`qlm run`） | 2136 ms | 同上 + 程序本身 |
| 输入变了 | 2136 ms | 2136 ms（委托 stage-0，未变慢） |

判定耗时是驱动器**自己**报的（`now_ns()` 前后差，排除进程创建）：`examples/hello.qma`
8 个输入 → 3.8 ms；`std/http.qma` 14 个输入 → 12.8 ms。冷路径不引入任何额外开销。

**它不是编译器**：代码生成仍在 stage-0（自举 2/9）。它自举的是驱动器——找根目录、
解析 import 闭包、判新鲜度、调子进程、传退出码。这是"把引导层换成自己语言"的第一块，
因为它不碰语义。

### 3. 两个静默误编译（写驱动器时踩出来的）

**① `vec[T][i]` 根本编不过**（`下标只能用于定长数组、切片或 str`）
文档一直写 `v[i]`，但 `eval` 的下标分支只有"定长数组 / 切片 / str"三条路，vec 句柄
落到最后直接报错——局部变量和形参都不行。后果：**`std/sort.qma` 整篇 `v[i]` 快排
编不出来**（没人发现是因为没有测试 import 它）。修法：补第四条路，降级同 `.get(i)`
（`__vec_get` 自带越界 fail-fast，元素标签照 `.get` 的三条重挂路径）。

**② `exit(变量)` 静默退 0**
`emit_exit` 把裸 int 当立即数，而 **vreg 号也是 int**——`let c = 3; exit(c)` 传的是
vreg 号（0），于是退 0。内部调用点（assert / 越界 / panic）传的都是字面量 1，
所以只有"退出码是运行期算出来的"这一条路坏，回归从来没覆盖到。修法：裸 int 一律按
vreg 解释，内部 14 个调用点改成显式 `("imm", 1)`。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/driver/qlm_drv.qma` | **新增**（~330 行）：`run` / `build` / `stat` / `version`；根目录探测、import 闭包、mtime 新鲜度、`system()` 委托、退出码传播 |
| `tools/stage0/qlm_native.py` | `eval` 的 `index` 分支补 `vec` 第四条路；`emit_exit` 把裸 int 按 vreg 处理（14 个内部调用点改显式 imm） |
| `tests/t141_vecindex.qma` | **新增**：局部 / 形参 / 嵌套 / str / 聚合 / 表达式位置六种 vec 下标形态 |
| `tests/t142_exitcode.qma` | **新增**：`exit(运行期值)` 必须成为真实退出码（期望 42） |
| `tests/run_win_tests.py` | 注册 t141（自校验）+ `test_exitcode()` 三条断言 |
| `docs/07-gaps.md` | §7.15 / §7.16 两个已修项；§1 `vec[T]` 行补下标说明 |
| `docs/02-language.md` | `vec` 下标与 `exit(code)` 的语义澄清 |
| `docs/05-toolchain.md` | 新增 §1.10（原生驱动器的用法、判定规则、边界） |
| `docs/06-status.md` | 新增 §3.24（引导层耗时分解 + 驱动器判定耗时 + 进程创建税）；§1 主回归计数 |
| `docs/01-overview.md` | 仓库结构补 `bootstrap/driver/` |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=288 FAIL=0 SKIP=1（新增 t141 + `test_exitcode` 三条） |
| `qlm stat examples/hello.qma` | 8 个输入、判定 3.8–6.6 ms（进程内） |
| `qlm build`（未变） | 无输出、退出码 0；改源码后自动重新委托并生效（rc 7 → 8 实测） |
| `qlm run <exit(7)>` | 退出码 7（修复前是 0） |
| `python tools/stage0/qlm_cli.py run tests/t141_vecindex.qma` | `vecindex ok`（6 组断言） |

## 已知边界 / 遗留

- **驱动器只自举了入口**：类型推断 / 降级 / 优化 / 编码 / PE 写出仍在 stage-0（自举 2/9）。
  要做到"编几 KB 比 C 快 5 倍"，缺的是**原生后端**（下一条），不是驱动器。
- **本机测不出"比 C 快 5 倍"**：任何进程创建 ~370 ms（系统 `hostname.exe` 同价）。
  这个数字只能在正常机器或 CI 上测；本版只报进程内耗时。
- 闭包解析只认 `std.*` 与同目录兄弟模块；解析不了的（`src/` 根、第三方包）一律
  **强制重编**（fail-safe，不会给旧产物）。
- 判定读每个文件找 `import` 行，文件多时线性增长（14 个输入 12.8 ms）；闭包缓存
  可以做成 sidecar，未做。
- `thread_start` / `net_config` 之外，stage-0 仍有 34k 行 Python。
