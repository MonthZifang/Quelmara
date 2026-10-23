# v1.48 — `defer`：块级清理（语言层黄标翻绿）

- 日期：2026-10-23
- 任务：语言层 §1「`defer` / RAII / `Drop`」行 🟡——**`defer` 语句落地**（接 v1.45
  起另一会话留下的在途实现并收口：补语义缺口、C 后端 fail-fast、自举词法对齐、
  测试、文档）。`Drop`/析构仍缺，故整行停在 🟡（清理要显式写，但不必再手抄一遍）。
- 影响面：`tools/stage0/qlm.py`（关键字 + parse_stmt + C 后端拒绝 + walk_stmts）、
  `tools/stage0/qlm_native.py`（Lower 的 defer 帧/标志位/退出点）、
  `bootstrap/lexer/qlm_lex.qma`（关键字表两侧对齐）、`tests/t91_defer.qma`（新增）、
  `tests/bad/defer_let.qma`（新增负向）、`tests/run_win_tests.py`（注册）、
  `docs/02-language.md`（§2.1 / §5 / §8.6）、`docs/07-gaps.md`（§1 行 + §8）、
  `docs/06-status.md`、`tools/stage0/qlm_cli.py`（VERSION）

## 为什么是它

`defer` 是 07-gaps §8 语言层黄标的第一顺位，也是**接口装箱不释放**（黄标）的前置：
没有"块退出一定跑"的清理钩子，`rc`/fd/锁的释放只能靠每条 return 前手写一遍，
漏一条就是泄漏。语言层先有 defer，后面才有 RAII 与 `Drop` 的落点。

v1.45 之后的在途实现只到"编译期登记、块尾按 LIFO 发射"，缺三处会静默出错的语义：
① `break`/`continue` 早于 defer 的路径会误跑清理；② `return expr` 根本不跑清理；
③ `return x` 求值拿的是 x 的槽，defer 里改 x 会把返回值改掉。本轮把三处补齐并逐条测试。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | `KEYWORDS` 加 `defer`（硬关键字，与 `break`/`continue` 同档）；`parse_stmt` 新增 defer 分支（只收表达式/赋值四形态，其余 fail-fast）；C 后端 `gen_stmt` 显式拒绝（不静默丢清理）；`walk_stmts` 把 defer 内部语句计入引用/赋值（否则只在 defer 里用到的变量会被 DCE 当未使用） |
| `tools/stage0/qlm_native.py` | 每块一帧 `{"slots": [登记标志], "entries": [(stmt, env, flag)], "cursor": n}`；块入口给块内每条 defer 预分配标志位（初值 0）、执行到 defer 置 1，退出点 `jcc flag==0 → skip`；`return`（含标量/聚合/切片/数组/void 五条路径）统一在 ret 前发射清理；`break`/`continue` 只跑到循环体帧（`loop_stack` 第三元存帧深度）；标量 return 在有 defer 时先落副本，避免 defer 改写返回槽 |
| `bootstrap/lexer/qlm_lex.qma` | 关键字表补 `defer`——自举词法与 stage-0 必须逐字节一致（lexdiff 会咬） |
| `tests/t91_defer.qma` | **新增**：13 组断言——块尾 LIFO / return 路径 / 退出时取值 / 嵌套块 / break 早于 defer 不跑 / continue 路径 / 未取到的分支 / 聚合返回 / 赋值形态 / break 不跑函数级 defer / match 分支 / 字段赋值 / foreach 逐轮 |
| `tests/bad/defer_let.qma` | **新增负向**：`defer let ...` 必须编译期拒绝 |
| `docs/02-language.md` | §2.1 关键字 31→32；§5 语句加 defer；新增 §8.6（作用域/顺序/触发点/登记/取值/返回值/拒绝清单） |
| `docs/07-gaps.md` | §1 defer 行 ❌→🟡（defer ✅，Drop 仍缺）；§8 路线图打勾 |

## 实现要点

- **标志位是语义，不是优化**：defer 是**语句**，执行到才登记。`if c { break }` 写在
  defer 之前时，那条路径上 defer 从未登记，块退出不能跑它——没有标志位就只能靠
  "defer 必须写在块首"的约定，那是静默陷阱。代价是每条 defer 一次 store + 一次
  test（实测见验证表）。
- **break/continue 的帧下界**：`loop_stack` 存 `(continue_label, break_label, defer_depth)`，
  break 只发射 `defer_stack[defer_depth:]`——循环体帧跑、函数帧留到 return/函数尾。
  否则循环里 break 会把函数级清理提前跑掉。
- **返回值先算后清理**：`return x` 先求值；有 defer 时把值搬进新临时槽再跑清理，
  否则 `defer x = 99` 会把返回值从 1 改成 99（测试 c4 咬这条）。
- **C 后端 fail-fast**：C99 无 RAII，要支持得给每个退出点复制清理代码 + goto 标签。
  收益不抵风险，直接报错并说明边界；defer 类测试只进 PE / A64 原生后端。
- **A64 零改动**：defer 全部降成已有 IR（mov/jcc/label/call），`irdiff` 里 t91 直接 PASS。

## 验证（本轮全部现跑）

<!-- verify:begin -->
| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=158 FAIL=0 SKIP=1**（SKIP 为 WSL 交叉验证，本机沙箱拦，正常） |
| `python tests/lexdiff.py` | **PASS=142 FAIL=0**（142 个源文件；补 bootstrap 关键字后由 FAIL=2 转绿） |
| `python tests/parsediff.py` | **PASS=121 FAIL=0** |
| `python tests/bodydiff.py` | 一致 1277 / 分叉 1080 / SKIP 同步 25 / SKIP 不同步 31（诊断项，非门禁；分叉随源文件增长） |
| `python tests/irdiff.py` | **PASS=68 FAIL=0 SKIP=49**——t91 的 defer 在 A64 直接 PASS（defer 全部降成已有 IR） |
| `python tests/emitdiff.py` | **PASS=10 FAIL=0** |
| 三道门禁 | check_names / check_origin / check_docs 全 PASS |
| **性能（双向对照）** | `git worktree add ../quelmara-base 581b47b` 建基线，两树各构建 8 个 bench：**`.qex` 逐字节相同**（p0_bench 150528 B / gbench 42496 B / bench_str 17408 B / find_bench 35328 B / simd_bench 100352 B / sync_bench 14336 B / gzip_bench 84480 B / bench_mod 10752 B）——不用 defer 的程序**零指令变化**，比跑分更硬 |
| **性能（defer 自身开销）** | 3M 次函数调用自测：无 defer 4–7 ms / 有 defer 5–8 ms，**约 0.3 ns/次（≈1 周期）**——一次标志 store + 一次 `jcc` 判定；VBS 噪声 ±50%，只作量级参考 |
<!-- verify:end -->

## 顺带修复（v1.47 提交遗漏，HEAD 上是红的）

1. `tools/dev/qlm_doc.py` 未入库：`gen_stdlib_doc.py` 已改为 `import qlm_doc`，
   HEAD 上跑 `gen_stdlib_doc.py --check` 直接 ImportError。本次补入。
2. `std/hash.qma` 的 `///` 未入库：`docs/03-stdlib.md` 已按带文档的版本重生成，
   源码没进来则两边漂移（`--check` 必红）。本次补入。
3. `fixtures/srcproj/src/lib/ws/ws_core.qma` 缺 `pub`（v1.43 遗留）：v1.43 提交后
   `fixtures/srcproj/main.qma` 引用非 pub 的 `ws_greet`，**HEAD 上主回归直接编译失败**
   （本机工作区一直带着这行未提交的修复，所以看不出来）。本次补入。

> 版本号：v1.46 原为 defer 预留，但标准库轨 v1.47 先落地造成撞号；门禁要求
> `VERSION` 与最新版本目录同源，故 defer 顺延为 **v1.48**（v1.46 空号，v1.47 的
> CHANGELOG 已同步说明）。

## 已知边界 / 遗留

- **无 `Drop`/析构**：defer 只是"显式清理的可靠执行点"，不是 RAII。结构体出作用域
  不会自动调清理函数；接口装箱仍不释放（07-gaps §1 两行都还没翻绿）。
- **defer 只收表达式/赋值**：`defer let x = ...`、`defer if ...`、`defer while ...`
  一律编译期拒绝——带作用域的语句到块尾执行时绑定已失效，等于块对象问题。
- **硬关键字**：`defer` 不能再用作标识符（std/tests/fixtures 全库无同名，门禁
  `check_names` 覆盖；第三方代码需自查）。
- **C 后端不支持**：defer 类测试不进 C 交叉验证；`run_tests.sh` 的 C 列表不要加。
- **每块预扫描只认块内顶层 defer**：写在嵌套 if 里的 defer 属于那个 if 的块帧
  （语义正确，代价是每条 defer 一个标志位 + 一个跳转标签）。
