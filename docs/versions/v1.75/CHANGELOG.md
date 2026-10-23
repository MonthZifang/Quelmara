# v1.75 — 源码级调试器：`.qlmdbg` 调试节 + `quelmara debug`（工具链黄标 → 绿）

- 日期：2026-10-23
- 任务：`07-gaps.md` §3 工具链「调试器」行 🟡 → ✅——把"无 DWARF/PDB、无源码断点、
  无变量查看，靠 `capstone` / `--dump-ir` / `readelf`"补成**自研全链路**：
  编译器随 PE 发射自研 `.qlmdbg` 调试节（行表 + 变量位置表 + 结构体布局），
  `quelmara debug` 在 Windows 调试 API 上提供源码断点 / 单步 / 变量查看 /
  调用栈。零外部依赖（无 gdb / 无 capstone / 无 WinDbg / 无 SDK）。
- 影响面：编译器（`tools/stage0/qlm_native.py`、`qlm_opt.py`、`qlm_pe.py`）、
  工具链新模块（`qlm_dbinfo.py`）、调试器重写（`qlm_dbg.py`）、CLI
  （`qlm_cli.py` `debug` 子命令 + `--dbg-info`）、测试
  （`tests/debugger_test.py` + `fixtures/dbgdemo/main.qma`）、文档

## 为什么是它

§8 推进顺序里工具链排在语言层之后，但"调试器"是工具链里唯一挡住日常开发的一项：
此前定位后端问题只能 `--dump-ir` 猜、`readelf` 扒节、`capstone` 反汇编心译。
本版把三件事一次做通：**源码行号进编译器**（语句级标记穿过优化器）、
**变量位置可计算**（vreg → 线性扫描分配结果 → 寄存器号或帧槽）、
**调试器前端**（int3 软断点 + RBP 帧链 + 脚本化会话）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_dbinfo.py` | **新增**：调试信息模块。① 行号钩子——给 `qlm.Parser.parse_stmt` 包一层，语句元组追加 `("__line__", n)`（钩子成对安装/卸载，**不改共享 parser 文件**，语言轨在途重写 `qlm.py` 期间零冲突）；② `load_program_dbg`：带行号程序加载 + 主文件函数名集（import 的库函数行号属于别的文件，不配）；③ `serialize_dbg`：调试表 → JSON（`.qlmdbg` 节体） |
| `tools/stage0/qlm_native.py` | `Lower` 加 `dbg` 开关：语句边界发射 `('line', n)`、let 绑定发射 `('dbgvar', name, vreg)`、形参发射 `('dbgparam', name, vreg)`；`_map_ins`/内联把 `dbgparam` 降级为 `dbgvar`（内联参数在调用点诞生，不泄漏成调用方全函数可见）；`Codegen` 收集行表/变量表（loc = 分配结果，last = vreg 末次提及，push = 序言压栈数）；`lower_and_optimize` 加 `prog` 参数；`lower_fn` 记录 `dbg_file`（路径规范化为正斜杠） |
| `tools/stage0/qlm_opt.py` | `vreg_mentions` 登记 `line`/`dbgvar`/`dbgparam`；`_EFF` 副作用表加入三种标记——列表调度会把无依赖指令浮到基本块尾部，行号标记若可浮动，断点会落在语句第一条指令**之后**（值已变）；`_subst_vregs` 让 dbgvar/dbgparam 的 vreg 跟 copy_prop 别名替换走（否则绑定指向被塌缩掉的 vreg，`print f` 直接失效） |
| `tools/stage0/qlm_pe.py` | `build_pe` 加 `.qlmdbg` 节（`SCN_DBG` 只读数据；**不挂 DEBUG_DIRECTORY**——那是 CODEVIEW 目录，挂非标准格式会让标准工具误读）；`transpile_win(dbg=)`；`WinCodegen.gen_all_pe` 补函数 RVA |
| `tools/stage0/qlm_dbg.py` | **重写**为源码级调试器：PE 节解析 + `.qlmdbg` 加载；Windows 调试 API（CreateProcess DEBUG_ONLY_THIS_PROCESS / WaitForDebugEvent / int3 软断点 + 单步重贴 / Get·SetThreadContext）；命令：`break FILE:LINE`/`break FUNC`/`run`/`step`/`next`/`finish`/`print a.b.c`/`locals`/`bt`/`list`/`info break`/`delete`/`quit`；`--script` 无人值守（测试用） |
| `tools/stage0/qlm_cli.py` | `debug` 子命令（.qma → `--dbg-info` 构建后调试；产物直接调试）；`build/run` 加 `--dbg-info`；`version` 能力行加 debug |
| `tests/debugger_test.py` | **新增**：脚本化调试会话断言 18 项（断点行号与源码文本、int/bool/f64/str/struct 求值、`a.b` 字段访问、step/next 行推进、bt 帧链、退出码 0）+ 调试构建与非调试构建**输出逐字节相同** |
| `fixtures/dbgdemo/main.qma` | **新增**：调试器固定靶（行号即断点坐标；int/str/bool/f64/struct；递归 fact 供 bt） |
| `docs/05-toolchain.md` | 新增「源码级调试器」节：用法、命令表、`.qlmdbg` 格式、自研边界 |
| `docs/06-status.md` | §1 加调试器测试行 |
| `docs/07-gaps.md` | §3 调试器行 🟡 → ✅（边界：ELF 后端未接节写出、内联帧按物理帧走） |

## 实现要点（踩过的坑，都写进了代码注释）

- **CONTEXT 布局是本机实测校准的，不是照抄资料**：调试事件自带异常地址（=真实
  RIP），在 GetThreadContext 缓冲区里反查落点，再写 16 个魔数 Set+Get 回显
  逐一定位。实测结论：GPR `0x78..0xF0`、Rip `0xF8`、EFlags `0x44`——与部分
  资料所写（`0x88`/`0x108`）差 0x10。按错的布局 SetThreadContext 会把"回退
  RIP"写进真实 R14，线程从 int3 之后继续执行、跳过一条指令，**静默算错不崩**。
  因此每次断点命中都校验读到的 Rip == bp+1，不符即 fail-fast。
- **CONTEXT_FLAGS 只要 整数+控制**：请求 DEBUG_REGISTERS 会让内核把 Dr0-Dr7
  写到结构体尾部之外（实测布局里调试寄存器在 Rip 之后）——堆溢出（Python
  段错误）+ SetThreadContext 把缓冲区垃圾写进线程硬件断点（被调试进程
  `0xC0000005`）。本调试器用 int3 软断点，不需要硬件断点。
- **断点回退是 `Rip = addr` 不是 `addr-1`**：int3 只覆盖目标指令首字节，
  陷阱保存的 RIP = addr+1，重执行原指令必须回到 addr。
- **帧链不能假设 `[rbp+8]`**：序言先压 used_callee 个被调用者保存寄存器再
  `push rbp`，返回地址在 `[rbp + 8*push]`（push 数由 `.qlmdbg` 每函数登记）。
  不修正则从第一个调用帧就断链，bt 只剩一帧。
- **行号标记必须登记进 `_EFF`**：调度器按依赖图重排基本块，无依赖标记会浮到
  块尾，断点落在语句执行后。
- **可用性语义**：let 绑定在 `bind ≤ PC` 时可用（在自己那条行上 PC 在绑定
  mov 之前 → 报"尚未初始化"，不显示错值）；生命周期之外（PC > last）不显示
  被复用的过期值。
- **默认构建零影响（可证明）**：标记发射整段在 `if self.dbg:` 门内，
  `--dbg-info` 不开时 IR 里**没有任何标记指令**——优化器看到的 IR 与改动前
  完全一致；`qlm_opt`/`qlm_native` 的新增分支全是新指令形态的恒等case
  （既有指令一条路径都没碰）。带 `--dbg-info` 时标记计入指令数，循环展开/
  内联/调度决策会变（实测 loop_sum 调试构建 .text 小 111 B）——与 `gcc -g`
  同理，属调试构建的正常代价；行为不变由 `tests/debugger_test.py` §3 把关
  （调试/非调试构建输出逐字节相同）。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/debugger_test.py` | **PASS**（18 项期望输出全命中 + 行为不变） |
| `python tests/run_win_tests.py` | PASS=n FAIL=0 SKIP=1（SKIP=WSL 交叉验证，本机沙箱拦；数字见 06-status.md） |
| `python tools/dev/check_docs.py` | PASS（含 VERSION=1.78.0 ↔ 最新版本目录 v1.78（语言轨最新）；本版目录 v1.75 历史在档） |
| `python tools/dev/check_names.py` / `check_origin.py` | PASS / PASS |
| `python tools/stage0/qlm_cli.py debug fixtures/dbgdemo/main.qma` | 交互/脚本会话全对（r=21 程序输出不变） |

性能：本版不触碰任何运行时代码（无新指令、无新调用），默认构建的代码
生成路径与改动前一致（见"实现要点"最后一条的论证）；调试构建的行为不变由
测试 §3 把关。进程级跑分只做纵向比较（VBS ±50%），无回归空间。

## 自研边界（写进文档的承诺）

- 调试信息是自研 `.qlmdbg` 节（JSON：行表 + 变量位置表 + 结构体布局），
  **不是 DWARF/PDB**；只支持 Windows PE 产物（ELF 后端未接节写出）。
- 语言轨在本版调试表之上另叠了一层标准 DWARF v4 编码（`qlm_dwarf.py`，
  其 v1.80，本版已带其文档），供外部工具消费；自研调试器读 `.qlmdbg`，两者同源同表。
- 内联帧：行表可能落在被内联函数的行上，`bt` 按物理帧（RBP 链）走。
- 库函数帧无源码行号（行号属于被导入文件），显示 `<library>`。

## 同版并入：语言轨 / 标准库轨 v1.61–v1.74（工作区在途，随本提交一起入库）

> 与 v1.60 一样两轨合并提交。版本号连续共享：本工具链线的调试器工作从
> v1.62 起算，语言轨同期已推进到 v1.78 并把 v1.75 留给本线，调试器定版 **v1.75**。

- **v1.61 类型约束（trait bound）红标 → 绿**：`[T: Ord]` 从文档约定变成编译器
  强制，违反在调用点编译失败；单态化后完全擦除（bound_bench 同速）。
- **v1.62 泛型 struct 的方法（impl 泛型 struct）**、**v1.63 泛型 enum**：
  泛型三件套收口（该行 → ✅）。
- **v1.64–v1.78**：MIME / 静态文件 / cookie / session / multipart /
  httpdate / CSV 等标准库逐块（§2 相关行收口）。
- **在途未编号**：`qlm_dwarf.py`（同一份调试表的标准 DWARF v4 叠加层）。
- 测试与文档随各子版本更新（`tests/t100–t10x`、`docs/versions/v1.6x–v1.78`）。

## 已知边界 / 遗留

- ELF（native/arm64）后端不发射 `.qlmdbg`，`--dbg-info` 对非 win 目标
  fail-fast；ELF 调试节 + ptrace 前端未做。
- `print` 支持变量与 `a.b.c` 字段路径；数组下标、表达式求值未做。
- 硬件断点（Dr 寄存器）未用；watchpoint 未做。
- 入口停点（初始断点）处内核返回的整数上下文不完整（Rip=0），
  step/print/bt 在该点一律要求先 `run` 到真实断点。
