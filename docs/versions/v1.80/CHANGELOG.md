# v1.80 — DWARF v4 + 调试构建语义：`--dbg-info` 补标准调试信息、断点不再静默失效

- 日期：2026-10-23
- 任务：`07-gaps.md` §3「调试器」行的**第一句缺口**——"无 DWARF/PDB"。v1.79 把
  自研 `.qlmdbg` 与调试器做通了，但调试信息只有自研格式，外部工具（IDE /
  objdump / llvm-dwarfdump）读不到；同时实测发现两个**会让调试器静默骗人**的
  缺陷：`--dbg-info` 在 CLI 层直接崩（`_build_win` 不认 `dbg`），以及内联让
  源码断点永不命中。本版一次补齐：DWARF v4 发射 + 调试构建不内联 + 单步语义
  与性能修正。
- 影响面：编译器（`qlm_pe.py`、`qlm_native.py` 一行门禁）、工具链新模块
  （`qlm_dwarf.py`）、调试器（`qlm_dbg.py` 单步/断点机制）、CLI、测试、文档

## 为什么是它

v1.79 交付后按"自己先用一遍"的标准跑了一遍，三个问题都属"看起来能用、实际在骗人"：

1. `quelmara build --dbg-info` 直接抛 `TypeError`——`qlm_cli.build()` 把 `dbg=`
   传给 `_build_win`，而 `_build_win` 的签名里没有这个参数。链路从入口就是断的。
2. `work()` 被内联进 `main` 后，`break main.qma:12`（work 体内的一行）**永不命中**，
   `bt` 也看不到 work 帧——独立函数体成了死代码。断点不报错、不命中，是最坏的形态。
3. 缺口表原文写"无 DWARF/PDB"，而自研 JSON 只能自己读。要让 IDE 和
   `llvm-dwarfdump` 这类工具看见，就得发标准 DWARF。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_dwarf.py` | **新增**：DWARF v4 编码器（约 430 行）。一个 CU：基础类型 → 结构体布局（含 `slice` 合成类型）→ 每个主文件函数的 `DW_TAG_subprogram` + 形参/局部变量；`.debug_line` 每个函数一条 `set_address` 后按 `advance_pc`/`advance_line`/`copy` 走；`.debug_loc` 用 `[bind,last)` 区间 + `DW_OP_fbreg`/`DW_OP_regN` 表达式 |
| `tools/stage0/qlm_pe.py` | `build_pe` 支持任意附加节 + **COFF 长节名**（`/N` + 节尾字符串表，`.debug_abbrev` 这类名字放不下 8 字节）；新增 `SCN_DWARF`；`transpile_win` 在 `dbg=True` 时同时产出 `.qlmdbg` 与四个 `.debug_*` 节 |
| `tools/stage0/qlm_cli.py` | `_build_win(..., dbg=False)`——修掉 `--dbg-info` 的 `TypeError`（链路的断点就在这一行） |
| `tools/stage0/qlm_native.py` | `lower_and_optimize`：**调试构建（`prog is not None`）默认不内联**，`QLM_NO_INLINE=1` 仍可显式关。内联会让被调函数变死代码、断点静默不命中 |
| `tools/stage0/qlm_dbg.py` | ① 线程句柄按 tid 缓存（单步每步 4~6 次 OpenThread 是主要开销）；② `next`/`finish` 跨调用改成**返回地址临时断点**（原来逐指令穿过 `print` 要走 51 万步 / 231 秒）；③ 单步正好落在断点地址上时"吸收"该命中（否则 `finish` 会原地停回同一行）；④ `finish` 用 `left_fn + 深度` 双条件（尾声先 `leave` 后 `ret`，只看深度会停在 `return` 那行）；⑤ 单步护栏 `MAX_STEPS`；⑥ 停在 `<entry>`/库帧时 `next` 退化为 `continue`；⑦ `print` 区分"尚未初始化 / 已超出生命周期 / 未知"三种不可读语义 |
| `tests/dwarf_test.py` | **新增**：独立 DWARF 读取器（不 import `qlm_dwarf`，只按规范解字节），20 项断言逐条对照 `.qlmdbg` |
| `tests/dbg_test.py` | **新增**：调试器端到端命令链，40 项断言（断点编号/命中计数/三种不可读语义/next/finish/bt/删除断点/程序输出/退出码） |
| `tests/run_win_tests.py` | 新增 `[8] 调试链路` 组，把上面两个脚本纳入主回归 |
| `fixtures/dbgdemo/loop.qma` | **新增**：性能探针靶（5000 次循环，断点在循环体内） |
| `tools/dev/dbg_bench.py` | **新增**：调试链路性能探针（构建开销 / 体积占比 / 每命中 / 每步） |
| `docs/05-toolchain.md` | §1.1 补"两种调试信息一份数据源"、DWARF 三条口径、更新自研边界；§5.2 登记四个新脚本 |
| `docs/04-compiler.md` | §6.2.1 调试信息发射：六个阶段各改哪个文件 + 新增语句形态的注意事项 |
| `docs/06-status.md` | §1 回归数字 + 两行调试链路；**新增 §3.8 调试链路性能** |
| `docs/07-gaps.md` | §3 调试器行补 DWARF/PDB 口径；§6 P2 与 §8 推进顺序同步 |

## 实现要点（都是踩过的坑）

- **DWARF 地址一律写 RVA**：PE 的调试节是 DISCARDABLE、不映射、也不参与基址
  重定位；写绝对地址就得给调试节造重定位表。RVA 与调试器的 `PC - image_base`
  同口径，外部工具加 image base 即可。
- **寄存器号必须翻译**：codegen 内部编号是 `Rax/Rcx/Rdx/Rbx/Rsp/Rbp/Rsi/Rdi`
  的声明顺序，DWARF x86-64 是 `rax/rdx/rcx/rbx/rsi/rdi/rbp/rsp`——第 1/2 位和
  第 4/5/6 位都不同。照抄会读到**另一个寄存器**（`a` 显示成 `b` 的值，不报错）。
- **`file_names[0]` 就是源文件**：DWARF 4 的 `DW_AT_decl_file` 从 1 开始编号，
  1 指向 `file_names[0]`。先塞一个空项的话，所有 `decl_file` 都指向空名字。
- **`.debug_loc` 要用区间而不是单个表达式**：变量在 `last` 之后寄存器/帧槽可能
  被复用，单一 `DW_AT_location` 会让外部工具在过期区间显示脏值。
- **COFF 长节名**：节名超过 8 字节要写成 `/<字符串表偏移>`，真名放节尾字符串表
  （4 字节总长 + NUL 结尾串）。漏掉这一步会让节头错位 6 字节，整张节表读成垃圾。
- **`next` 不能逐指令穿过被调函数**：`next` 在 `print(...)` 上会走进运行库，
  一次 51 万条指令、231 秒。标准做法是"步过调用"——在返回地址放临时断点，
  命中即静默摘除、恢复单步。
- **断点重贴不能丢**：单步正好落在断点地址上时若只恢复原字节而不安排重贴，
  那条断点会永久消失（`TF` 已被 CPU 清掉）。`pending_rearm` 里带 `repatch` 标志，
  `resume` 前若队列非空则强制打开 `TF`。
- **调试构建不内联是语义选择，不是性能妥协**：断点必须命中用户写的行。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/dwarf_test.py` | **PASS=20 FAIL=0** |
| `python tests/dbg_test.py` | **PASS=40 FAIL=0** |
| `python tests/debugger_test.py` | **PASS**（v1.79 的 18 项 + 调试/非调试输出逐字节相同，改动后仍全绿） |
| `python tests/run_win_tests.py` | **PASS=221 FAIL=0 SKIP=1**（SKIP=WSL 交叉验证，本机沙箱拦） |
| `python tools/dev/check_docs.py` | PASS |
| `python tools/dev/dbg_bench.py` | 见下方性能 |

## 性能（`tools/dev/dbg_bench.py`，min of 3，VBS 噪声 ±50%，只做纵向比较）

| 项 | 数值 |
|---|---|
| 默认构建 → `--dbg-info` | 2163 ms → 2211 ms（+48 ms，×1.02） |
| 产物 14901 B | `.text` 6353 B / `.qlmdbg` 2742 B（18.4%）/ `.debug_*` 1008 B（6.8%） |
| 每次断点命中 | 139–159 µs |
| 每次源码行单步 | 0.96–1.05 ms（**改动前 3.8 ms**，线程句柄缓存 + 跳过被调函数） |
| 单步穿一次 `print` 调用 | 231 s（51 万步）→ 数毫秒 |

构建开销几乎为零：调试构建不内联省下的时间，正好抵消多编码一份 DWARF 的开销。
默认构建逐字节不变（DWARF 只在 `dbg=True` 分支生成，节表与字符串表都不动）。

## 已知边界 / 遗留

- **不发 PDB**：Windows 原生链路要 MSF 容器 + CodeView 记录，与 DWARF 是两套；
  本机没有 MSVC 工具链可验证，宁可不做。
- **DWARF 只有 Windows PE**：ELF 后端不写调试节（`--dbg-info` 对 native/arm64/c
  fail-fast）。
- **变量可见区间止于最后一次使用**：之后报"已超出生命周期"。想要"整函数可见"
  得证明帧槽/寄存器没被复用，否则就是在显示脏值——按项目口径宁缺勿错。
- **`.debug_info` 没有 `DW_TAG_inlined_subroutine`**：调试构建不内联，所以用不上；
  将来若给发布构建也发调试信息，需要补这一层。
- 覆盖率 / fuzz 仍未做（§3）；LSP、`.qla`、增量编译同理，都是独立版本的事。
