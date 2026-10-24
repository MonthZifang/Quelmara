# v2.20 — 聚合形参与返回值（ABI 打通），子集 S6

- 日期：2026-10-24
- 任务：打通"聚合不能作形参/返回值"这条最大结构性限制
- 影响面：自举层（qlmc 后端 ABI）/ 测试 / 文档

## 主事件：聚合按值传参 + sret 返回

之前 `fn f(p: Point)` 与 `fn g() -> Point` 都是 fail-fast，`vec[Struct]`、`map[str]Struct`
这类都没法写。这一版把 ABI 补上：

| 场景 | 做法 |
|---|---|
| 聚合**形参** | 调用方把值（已经是地址）当**指针**传；被调方在入口 `__memcpy` 进自己的帧区域 → **按值语义**（改副本不影响调用方） |
| 聚合**返回值** | 隐藏 `sret` 指针占第 0 个实参寄存器（RCX），其余实参顺延到 RDX/R8/R9；被调方把结果 memcpy 到 `[sret]`，`rax` 返回该指针；调用方在**自己的帧里**开结果区域 |
| `return P { ... }` | 字面量不能当右值：先写进隐藏临时，再整块交给 sret |
| 实参上限 | 4 个寄存器（聚合返回占一个），超了 fail-fast |

**踩到的坑（值得记）**：被调方按值拷贝形参时，`OP_ADDRV`/`OP_COPY` 的**临时值会落在
R8-R11**，而 R8/R9 正好是第 3/4 个实参寄存器。于是"拷贝第一个聚合形参"会把还没读的
第二个实参覆盖掉——现象是 `add(a, b)` 里 `b` 读成了 `a`（结果 `a+a`）。

修法：**两遍收参**——第一遍把所有入参寄存器落进变量（pinned，不会被临时值占用），
第二遍再做按值拷贝。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=25**（11 组用例 + 并行确定性 2 条；新增 `s7_aggfn`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s7_aggfn.qma` | 9 行输出与 stage-0 逐字节相同：`3 / 11 / 22 / 99 / 300 / 3 / 0 / 7 / 8` |

`s7_aggfn` 覆盖：struct 形参、struct 返回、两个 struct 形参 + struct 返回、
enum 形参与 enum 返回、按值语义（被调方改副本不影响调用方）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | ABI：`sret` 隐藏指针（`C_SRET` 单元格）、聚合形参两遍收参、`OP_RETAGG`/`OP_RETSRET`、`_out_arg_reg` 扩到 R8/R9、`_ty_of_expr` 支持 `E_CALL`、`return` 聚合字面量走临时 |
| `tests/selfhost/s7_aggfn.qma` | **新增**：聚合形参/返回值的差分夹具（9 行输出） |
| `tests/qlmc_test.py` | 用例 10 → 11 |
| `docs/05-toolchain.md` | §1.11 覆盖表改 S6；坑表补「按值拷贝会踩实参寄存器」 |
| `docs/06-status.md` | §3.25 数字更新 |
| `docs/07-gaps.md` | §3 stage-1 行改 S6 |

## 已知边界

- 实参最多 4 个寄存器（聚合返回占一个），且**源码层仍是 ≤2 个实参**（parser 只解析两个）。
- 聚合实参必须是**变量/字段/下标/调用结果**；直接传字面量（`f(P{x:1})`）仍 fail-fast。
- 仍缺：map、f64、切片、泛型、闭包、`defer`、`import`、宏/反射、`@ffi`、接口、`rc`。
