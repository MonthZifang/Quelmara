# v2.18 — qlmc 扩到子集 S4：enum / match（并揪出 stage-0 一个结构体尺寸的误编译）

- 日期：2026-10-24
- 任务：语法面继续扩（上一轮卡在多函数崩溃，本轮定位并修掉）
- 影响面：自举层（`bootstrap/qlmc/qlmc.qma` 前后端）/ 测试 / 文档

## 主事件 1：enum / match

| 能力 | 做法 |
|---|---|
| `enum E { A, B, C(x: int) }` | 声明期建表（复用 `stt` 这根 vec，enum 区从固定偏移 1200 起，每 enum 26 字）；≤8 变体、单载荷、载荷限 int/bool/str |
| 布局 | `[tag:8][载荷:8]` = 16 字节；聚合值仍按"值 = 区域地址"表示 |
| 构造 | `E.A` / `E.B(3)` / `E.C(x: 3)`（载荷可带字段名，与 stage-0 语法一致） |
| `match` 表达式 | 读 tag → 逐臂 `cmp/jne` → 命中臂把值写进一个隐藏结果变量；`_` 通配 |
| `match` 语句 | 同上，臂体是 `{ ... }` 块 |
| 载荷绑定 | 绑定进**臂内作用域**（绑定栈，出臂即失效）——这条是必须的：`Cmd.Tag(s)` 里的 `s` 不能盖住外层的同名变量 |

## 主事件 2：上一轮"多函数必崩"的根因

上一轮（v2.18 未发布）的现象：单函数程序正常，**两个以上函数编译期 segfault**，
`--no-opt` 同样崩，二分到 `_lower_expr` 入口、连函数体第一条语句都没执行。

根因不是我的逻辑，是 **stage-0 在"按值传的结构体字段数偏大"时的误编译**：
`FnCtx` 从 24 字段（v2.17，能跑）涨到 28 字段后，按值传递时调用方/被调方对
参数区的理解出现偏移，`fc.nodes` 这类字段读到垃圾指针。把 6 个计数器
（`st`/`nv`/`ep`/`ldepth`/`bdepth`/`addrty`）收进一个 `cells` 数组、结构体压回
22 字段后，一切正常。

已登记到 `07-gaps.md` §7（与既有的 §7.4/§7.5「分配器布局敏感」疑似同源）。
**给 qlmc 的硬约束**：`FnCtx` 不许再随便加字段，要加就并进 `cells`。

## 主事件 3：顺带修掉的两个静默错码通道

| 问题 | 后果 | 修法 |
|---|---|---|
| `E_*` 与 `S_*` 节点常量撞号 | 我新加的 `E_ARM=15` 撞了 `S_PRINT=15`：`print` 被当成 match 臂 | `E_*` 整体挪到 40 段（AST 节点共用一个数字空间） |
| `_fn` 的形参/返回类型一直用 `_ty_id` | `_ty_id` 只认 int/bool/str，`l: Light`、`p: Point` 被**静默当成 int**（v2.14 就埋下的） | 改用完整的 `_type`，并在 `_lower_fn` 对聚合形参/返回值 fail-fast |

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 前端：`enum` 声明、`E.V` 构造、`match`（表达式/语句、`=>`、`_`）、`=>` 记号；后端：enum 类型编码（`0x2000+ei`）与 16 字节布局、`_lower_match`、臂内绑定栈 `bind/bdepth`、`FnCtx` 瘦身（28 → 22 字段，计数器并入 `cells`） |
| `tests/selfhost/s5_enum.qma` | **新增**：enum 声明/构造/match/载荷绑定/循环内 match 的差分夹具（8 行输出） |
| `tests/qlmc_test.py` | 用例 8 → 9 |
| `docs/05-toolchain.md` | §1.11 覆盖表改 S4；坑表补 3 条（节点常量撞号、`_ty_id` 静默降级、`FnCtx` 字段数上限） |
| `docs/06-status.md` | §3.25 数字更新 |
| `docs/07-gaps.md` | §3 stage-1 行改 S4；§7 新增「结构体按值传的字段数上限」 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=290 FAIL=0 SKIP=1 |
| `python tests/qlmc_test.py` | PASS=21 FAIL=0（9 组差分 + 并行确定性 2 条） |
| `python tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- 仍是子集 S4。缺：vec/map、f64、切片、泛型、闭包、`defer`、`import`、宏/反射、
  `@ffi`、接口、`rc`。
- **聚合形参/返回值仍不支持**（ABI 只传标量），现在会明确报错而不是静默按 int 处理。
- enum 载荷只支持 int/bool/str（不支持嵌套聚合载荷），变体 ≤8、每个变体 ≤1 个载荷字段。
- `match` **不检查穷尽性**（stage-0 会报错，qlmc 暂不检查）——缺 `_` 时落到 match 末尾，
  结果变量保持初值。
- 结构体/数组/enum 的局部区域都从帧里分配（0..255 个 8 字节槽），超了 fail-fast。
