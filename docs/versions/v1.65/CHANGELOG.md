# v1.65 — 两处 Lower 缺陷：枚举装箱 + `match` 的浮点标记

- 日期：2026-10-23
- 任务：修掉 v1.64 实测发现、当时只登记未修的两个 Lower 缺陷——
  ① 枚举不能装箱成接口值；② 枚举的 `f64` 载荷 / `match` 的 `f64` 结果被当成整数。
- 影响面：Lower（`tools/stage0/qlm_native.py`）、测试、文档

## 为什么是它

这两个都是"静默错"或"整类写法不可用"，而且修法都是一两行——比继续加新特性优先：

| 症状 | 根因 |
|---|---|
| `let s: Show = some_enum` → `SyntaxError: 未声明的结构体 Color` | `box_iface` 用 `struct_size` 取装箱宽度，枚举不在 `structs` 表里 |
| `match e { Num.F(v) => print(v.to_str()) }` → `4609434218613702656` | 绑定载荷时只给 `str`/`bool` 打标记，f64 丢了浮点标记 |
| `let d = match e { Num.F(v) => v * 2.0 ... }` → 结果仍是位模式 | `match` 作表达式时，结果 vreg 只继承 `str`/`bool` 标记，同样漏了浮点 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | ① `box_iface`：`struct_size(sname)` → `agg_size(sname)`（struct/enum 通吃）。② `lower_match` 载荷绑定：按字段声明类型补 `_mark_float`（`f64`/`float`/`f32`）。③ `lower_match` 结果写回：臂表达式是浮点时给结果 vreg 补 `_mark_float` |
| `tests/t103_generic_enum.qma` | 新增 `Opt[f64]` 用例：`to_str` 与 `v * 2.0` 两条路径 |
| `tests/t104_generic_enum_impl.qma` | 新增动态派发段：`let s: Show = o`、`vec[Show]` 里放枚举值 |
| `docs/07-gaps.md` | §1 interface 行去掉"enum 不能装箱"；§7.7 从"待查"改成"已修（v1.65）"并记根因 |
| `docs/06-status.md` | 回归/对拍数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.65.0 |

## 实现要点

- **`agg_size` 就是为这个场景准备的**（`struct_size` 或 `enum_size`），只是 `box_iface`
  写死成了 struct——典型"两条路径只改了一条"：`vec[Shape].push(enum)` 走的是同一函数，
  所以此前枚举进异构容器也必然失败。
- **浮点标记要跟着值走**：这套 Lower 用 vreg 上的标记区分 float/str/bool，任何"搬字"
  的位置（载荷绑定、match 结果、赋值）都必须显式传递，否则下游按整数处理。
  这与 v1.19 的浮点比较 bug 是同一类：**表达式路径对了，另一条路径漏了**。
- 两处修改都是纯 Lower 层，IR/优化器/后端零改动；`--target c` 与 AArch64 不受影响。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=196 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证，沙箱拦） |
| `python tests/lexdiff.py` | PASS=179 FAIL=0（182 个源文件） |
| `python tests/parsediff.py` | PASS=131 FAIL=0（跳过 9 个） |
| `python tests/irdiff.py` | PASS=73 FAIL=0 SKIP=59（t103 新增 f64 载荷算术，A64 未接 f64 二元运算，转 SKIP） |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| 四道门禁 | 全 PASS |

## 已知边界 / 遗留

- 装箱仍然**不释放**（无 rc/drop 路径），热点循环里频繁装箱会涨堆——这是 §1 interface
  行的既有黄标，不是本版范围。
- `f32` 载荷的标记按 `f32` 打，但语言里 `f32` 的算术仍按 f64 提升（既有口径）。
- 另一条轨已把 `str` 字典序比较接进 `arith`，但**条件路径 `branch` 仍未接**
  （`if s1 < s2` 仍按指针比较）——v1.19 同款双路径坑，等对方收口。
