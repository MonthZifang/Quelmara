# v2.23 — defer（块级清理），子集 S9

- 日期：2026-10-25
- 任务：defer（剩余 9 项里的第 2 项）
- 影响面：自举层（qlmc 前后端）/ 测试 / 文档

## 主事件：`defer`

| 口径 | 实现 |
|---|---|
| 登记 | `defer <表达式语句 / 赋值 / print>`：**只登记不执行**，节点进 per-function 的 defer 栈 |
| 生效时机 | 所在**块**退出时（正常走完 / `return` / `break` / `continue`），**LIFO** |
| `return` 的顺序 | **先定下返回值，再跑 defer**（stage-0 口径）：返回值先求值并 pin 进变量，然后跑 defer，最后才 `ret` |
| 块作用域 | 每块记录自己的 defer 栈起点，退出时只跑本块登记的；`if`/`while`/`for` 体都是独立块 |
| 循环体 | 每轮迭代都登记、都执行（不是"循环结束才跑一次"） |

`defer` 栈放进了 `FnCtx.df`（第 23 个字段——`05-toolchain` 记着"字段数 > ~24 会误编译"，
所以先试着加一个；编译与全部回归都通过）。

## 踩到的坑

1. **parser 分支插错函数**：我把 `defer` 的分支插到了 `_primary`（表达式解析）而不是
   `_stmt`，于是 `defer x = x + 1` 被当成"表达式语句包着一个 S_DEFER"，lowering 里
   报"不支持的表达式节点 24"。教训：`_primary` 和 `_stmt` 里都有 `K_MATCH` 分支，
   锚点选错就会插错地方——改完先 `grep -n` 确认分支落在哪个函数里。
2. **`return` 与 defer 的顺序**：第一版先跑 defer 再求返回值，`return v` 就读到了被
   defer 改过的值（stage-0 是 `0`，我给出 `11`）。改成"先求值 → 跑 defer → ret"。
3. **聚合字面量返回**：`return P { ... }` 里我用 `_addr_of(nd.a)` 取地址，但字面量
   不能取地址（它还没落进区域）。改成先 `_lower_into` 到隐藏临时，再用 `OP_ADDRV`
   取那个临时的地址。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=31**（14 组用例 + 并行确定性 2 条；新增 `s10_defer`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s10_defer.qma` | 6 行输出与 stage-0 逐字节相同（`0/1/8/0/6/0`） |

`s10_defer` 覆盖：LIFO 顺序、`return` 前跑但返回值先定、`if` 块作用域、
循环体每轮执行、defer 里调函数。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `defer` 关键字与 `S_DEFER`、`FnCtx.df` defer 栈、`_emit_defers`、`_lower_block` 的块退出发射、`return` 的"先求值后 defer"、聚合字面量返回取址 |
| `tests/selfhost/s10_defer.qma` | **新增**：defer 差分夹具 |
| `tests/qlmc_test.py` | 用例 13 → 14 |
| `docs/05-toolchain.md` | §1.11 改 S9；坑表补「parser 分支别插错函数」 |
| `docs/06-status.md` / `07-gaps.md` | 数字与 stage-1 行更新 |

## 已知边界

- `defer` 体只支持**表达式语句 / 赋值 / print**（不支持 `if`/`while`/`match` 等复合语句）。
- 没有 `Drop`/RAII（那是接口 + 析构表的事，属后面接口/rc 那一批）。
- 仍缺：f64、泛型、闭包、`import`、宏/反射、`@ffi`、接口、`rc`；vec/map 固定容量。
