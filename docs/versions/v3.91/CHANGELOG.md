# v3.91 — 窄整数类型（收 §7.46）：qlmc 不再"完全不支持 `u8`/`i16`/`u32`"

- 日期：2026-11-03
- 任务：收 §7.46 —— qlmc 以前完全不认 6 种窄整数类型。
- 结论：**已支持**。`tests/t49_width.qma` 从"未知类型 u8"变成逐字节等价。
- 影响面：`bootstrap/qlmc/qlmc.qma`（类型码 + 截断操作码 + 4 类存储点）、
  `tests/qlmc_test.py`（登记 t49_width）、`docs/07-gaps.md`、`docs/06-status.md`

## 语义（与 stage-0 的 `NARROW_BITS` 一致）

| 类型 | 位宽 | 截断方式 |
|---|---|---|
| `u8` / `u16` | 8 / 16 | `movzx`（零扩展） |
| `u32` | 32 | `mov r32, r32`（写 32 位自动清高） |
| `i8` / `i16` | 8 / 16 | `movsx`（符号扩展） |
| `i32` | 32 | `movsxd` |

**值仍按 64 位寄存器承载，只在存储点截断；表达式内部按 C 提升不截断。**
所以 `let h: u8 = 200; h + 100 == 300`（不截断），而
`let i: u8 = h + 100` → 44（存储点截断）。

## 实现

* 类型码 `TY_NARROW=6` 起 7 个槽（`TY_U8`…`TY_I32`），全部 `< TY_STRUCT`，
  所以 `_ty_is_agg` 自然返回 false，**不进聚合路径** —— 这是选这个区间的原因。
  `TY_BYTE=4` 不能复用，它已经被 `str` 下标读写占着。
* 新操作码 `OP_TRUNC`（`imm = (bits<<1) | signed`），编码与 stage-0 的
  `trunc_reg` 逐条对应。发射抽成 `_emit_trunc`（帧敏感区，见下）。
* 4 类存储点：**let 标注 / 赋值**（统一走 `_lower_into` 包装）、
  **形参入口**（寄存器 + 栈两条路径）、**返回值出口**（看函数 `ret_t`）。

## 踩到的三个坑

### ① `_lower_into_raw` 会把变量类型改成表达式类型

`E_BIN` 分支里有 `fc.vty.set(dst, t)`。于是 `let a: u8 = 300` 之后
`a` 的 `vty` 变成 int，截断查不到窄类型（打 300 而不是 44）。

第一版试图**无条件**不覆盖 —— 结果把 `s24_varreg`（`len() 只支持 str 与 vec`）
和 `s43_boolprint`（`true/false` 变 `1/0`）弄红了。因为 `let x = <聚合表达式>`
这类地方**依赖"vty 跟着表达式走"**。

正确做法：**只对窄类型变量保留声明类型**。为此新增 `vdecl` 表专门记声明类型，
与会被覆盖的 `vty` 分开。

### ② 赋值走的是 `S_ASSIGN` 但被 `BINI` 抢了

`f = f + 1` 降级成 `BINI dst=1 a=1 imm=1`，之后没有 `TRUNC`。根因就是 ①。

### ③ `_emit_ir` 的帧又顶爆了

加窄类型支持后，`_emit_ir` 需要 **417 个槽**（上限 416），stage-2 编不过自己。
v3.90 已经踩过一次同样的坑（那次是 `OP_CSUBNS`）。

这次把 `OP_ADD`/`OP_SUB`/`OP_MUL` 整段抽成 `_emit_binop` —— 那是 `_emit_ir`
里最大的一块（53 行、5 个局部变量），搬走后帧回落，编自己恢复正常。

**`_emit_ir` / `_emit_f64` / `_emit_csubns` / `_emit_trunc` / `_emit_binop`
这条线是帧敏感区**：往 `_emit_ir` 里加任何局部变量都必须先看它的槽余量。

## 验证

| 项 | 结果 |
|---|---|
| `tests/qlmc_test.py` | **PASS=108 FAIL=0**（含新增 t49_width） |
| `tests/bootstrap_test.py` | **5 级全 PASS**（含不动点） |
| `tools/dev/qlmc_coverage.py` | 69 / 69 达标 |
| `tests/t49_width.qma` | 13 条断言全过，与 stage-0 逐字节一致 |

## 还没做的（明确边界）

§7.46 的检查清单里还有两类存储点**没接**，因为现有夹具没覆盖到：

* `struct` 字段 / `enum` 载荷的窄类型写入；
* `vec` 元素 / 定长数组 / 切片别名写入的窄类型截断。

`tests/t85_narrowstore.qma` 正是钉这些的，但它同时撞上**两个与窄类型无关的
既有缺口**（qlmc 不认 `and` 关键字、数组字面量只能出现在 let/赋值/字段初始化里），
所以现在还跑不了。这两条登记为独立待做项，不混进 §7.46。
