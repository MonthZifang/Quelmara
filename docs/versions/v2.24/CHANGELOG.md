# v2.24 — import 多文件，子集 S10

- 日期：2026-10-25
- 任务：import（剩余 8 项里的第 3 项；纯工具链改动，不动 ABI）
- 影响面：自举层（qlmc 前端与驱动）/ 测试 / 文档

## 主事件：`import` 装载同目录模块

| 能力 | 做法 |
|---|---|
| `import foo` | 从**主文件所在目录**读 `foo.qma`，词法+语法后把声明并进同一套表（nodes/names/strs/fns/struct/enum 表） |
| `import a.b.c` | 路径按 `a/b/c.qma` 解析 |
| 传递依赖 | 装载过程中收集到的新 import 继续排队；**同一模块只装一次**（`loaded` 表去重） |
| `pub` | 当无操作跳过（本版不做可见性检查，全部导出） |
| 重复定义 | 新增**函数重名检查**（fail-fast）——多文件合并后最容易踩的就是这个 |

**没有做的**（都 fail-fast 或直接不支持，不静默）：限定调用 `mod.fn()`（要先做命名空间）、
`pub` 可见性、模块版本约束（`import foo ">=1.2"` 里的版本串被跳过不校验）、
同名类型的模块前缀 mangling。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=33**（15 组用例 + 并行确定性 2 条；新增 `s11_import`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s11_import.qma` | 5 行输出与 stage-0 逐字节相同（`7/42/45/11/16`） |

`s11_import` 覆盖：`import mod_util`、跨模块调用（含 `for` 循环与聚合形参）、
模块函数与本地函数混用。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `parse()` 多带一个 `imports` 收集器；`import` 解析（点分路径 + 跳过版本串）；`pub` 当无操作；`_fn` 加函数重名检查；驱动里新增 `_dir_of` 与装载循环（去重、递归收集） |
| `tests/selfhost/mod_util.qma` | **新增**：被 import 的模块（pub 函数） |
| `tests/selfhost/s11_import.qma` | **新增**：import 差分夹具 |
| `tests/qlmc_test.py` | 用例 14 → 15 |
| `docs/05-toolchain.md` | §1.11 改 S10 |
| `docs/06-status.md` / `07-gaps.md` | 数字与 stage-1 行更新 |

## 已知边界

- 只支持**同目录**（`import` 路径相对主文件），没有 `std/` 搜索路径。
- 没有限定调用 `mod.fn()`、没有 `pub` 可见性、没有同名冲突的模块前缀。
- 仍缺：f64、泛型、闭包、宏/反射、`@ffi`、接口、`rc`/`Drop`；vec/map 固定容量。
