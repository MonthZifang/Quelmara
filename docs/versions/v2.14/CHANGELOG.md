# v2.14 — stage-1 编译器 `qlmc`：`.qma` → PE32+ 全链路，第一次原生编出 exe

- 日期：2026-10-24
- 任务：前端（函数体 parser）→ IR + 寄存器分配 → x86-64 编码 + PE 写出，一次性写完
- 影响面：自举层（新 `bootstrap/qlmc/`）/ 测试（新差分回归）/ 文档

## 主事件

`bootstrap/qlmc/qlmc.qma`（~1900 行 Quelmara）是一个**能出 exe** 的编译器：
读 `.qma`，写 PE32+，全程本语言——不经过 Python、不链接 CRT、不依赖第三方。
它自己先用 stage-0 编出来（`build/qlmc.exe`，234 KB），之后用它编别的程序。

```
$ build/qlmc.exe build examples/fib.qma -o build/fib.exe
[qlmc] examples/fib.qma -> build/fib.exe  (1536 字节, 子集 S1)  编译 3300 us（进程内）
$ build/fib.exe
75025
```

**验证方式是差分，不是"能跑"**：`tests/qlmc_test.py` 把同一份源码分别交给 stage-0
与 qlmc 编，跑两个 exe，比较 stdout 与退出码**逐字节相同**（3 组用例 / 7 条断言，
含 `examples/fib.qma` 递归、`examples/loop_sum.qma` 2 亿次 while、
`tests/selfhost/s1_basics.qma` 算术/比较/逻辑/else/递归/字符串/exit）。

**只覆盖子集 S1**（这是"能出 exe 的最小闭环"，不是"能编整个仓库"）：

| 层 | 做法 |
|---|---|
| 词法 | 只认 S1 记号集；不认识的字符 fail-fast |
| 语法 | 递归下降 + 优先级爬升；**平坦 AST**（节点表 + `nx` 链），块用链不用区间 |
| 分配 | **全溢出**：局部/临时都落帧槽，表达式用 RAX/RCX 双累加器（线性扫描留给下一版） |
| 编码 | x86-64 手写（REX/ModRM/SIB、rel32 回填） |
| 文件 | 两节（`.text`/`.rdata`）、导入表（kernel32 + user32）、PE32+ 头 |
| 运行库 | `wsprintfA("%I64d\n")` + `WriteFile`，不引 CRT |

支持：`fn`（int/bool）、`let`/`mut`、赋值、`if`/`else`、`while`、`return`、`exit`、
`print(int)` / `print("字面量")`、递归与互调用、`+ - * / %`、比较、`&& || !`（短路）、
一元负号、数字分隔符、单行注释。
不支持：str 变量/形参、struct/enum/match、泛型、闭包、vec/map、f64、`import`、
全局常量、宏/反射、`@ffi`、错误信息带列号、寄存器分配、常量折叠。

## 关于"比 C 快 5 倍"

**没有在本机测，也不下结论**。两个硬约束：本机没有 gcc/clang（`07-gaps.md` §4），
且任何进程创建要 ~370 ms（`06-status.md` §3.24，系统自带 `hostname.exe` 同价），
足以淹没任何编译器的墙钟。本版能给的硬数字是"编一个 1 KB 源码、3.5 KB 产物的
程序，编译器自身 3.3–5.2 ms"（`06-status.md` §3.25）。C 侧的对照要在 CI 上补。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | **新增**（~1900 行）：词法 / 递归下降解析 / 平坦 AST / x86-64 编码器 / PE32+ 写出 / 导入表 / print 运行库 / CLI（`build` `dump` `version`） |
| `tests/selfhost/s1_basics.qma` | **新增**：S1 差分夹具（算术/比较/逻辑/else/递归/字符串/exit，16 行输出） |
| `tests/qlmc_test.py` | **新增**：差分回归——两个编译器编同一份源码，比 stdout/退出码 + 产物 PE 结构；`--time` 报两侧墙钟 |
| `tests/run_win_tests.py` | 新增 `[9b]` 段挂上 qlmc 差分 |
| `docs/05-toolchain.md` | 新增 §1.11（qlmc 用法 / 分层 / S1 边界 / 5 个踩过的坑）；§5.2 脚本表 |
| `docs/06-status.md` | 新增 §3.25（编译耗时 / 产物体积 / "比 C 快 5 倍"为何没测）；§1 主回归 289 |
| `docs/07-gaps.md` | §3 新增「stage-1 编译器 🚧 v2.14」行（覆盖什么、缺什么、**别当成自举 3/9**） |
| `docs/01-overview.md` | 仓库结构与关键文件表补 `bootstrap/qlmc/` |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=289 FAIL=0 SKIP=1（新增 `[9b]` qlmc 差分 7 条） |
| `python tests/qlmc_test.py` | PASS=7 FAIL=0（3 用例逐字节相同 + PE32+/AMD64 结构断言） |
| `build/qlmc.exe build examples/fib.qma` → 运行 | `75025`（与 stage-0 产物输出相同） |
| `build/qlmc.exe build examples/loop_sum.qma` → 运行 | `1199999988`（2 亿次循环，3.1 s） |
| 五道门禁 | 全 PASS |

## 已知边界 / 遗留

- **子集 S1**：见上表"不支持"那一栏。下一个增量按 `07-gaps.md` §3 的顺序做
  （str 变量与形参 → struct/enum/match → 寄存器分配与常量折叠 → 多文件）。
- **没有寄存器分配**：所有值走帧槽，`loop_sum` 的 3.1 s 比 stage-0 慢一个量级
  （stage-0 有线性扫描 + 优化管线）。这是下一版最直接的收益点。
- **没有优化**：常量折叠、CSE、强度削减全无；`_emit_expr` 每次二元运算都写读一次栈。
- **PE 只有两节、无重定位**：DllCharacteristics 只开 NX，加载器按首选基址映射
  （不做 ASLR）。
- **错误信息不带列号**，也没有源码行显示（只有 `line N`）。
- `print(bool)` 的口径跟着 stage-0 走：比较产生 int（打印 `1`/`0`），`&&`/`||`
  产生 bool（打印 `true`/`false`）——差分要求逐字节相同，所以照抄，不"修正"。
