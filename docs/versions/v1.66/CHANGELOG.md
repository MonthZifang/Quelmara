# v1.66 — 字符串有序比较：`arith` + `branch` 两条路径收口

- 日期：2026-10-23
- 任务：把 `str` 的 `<` `<=` `>` `>=` 从"地址比较"改成**字节字典序**，
  并把 `Ord` 能力约束扩到 `str`。
- 影响面：Lower（`qlm_native.py` 的条件路径）、能力表（`qlm.py`）、测试、文档

## 为什么是它

`str` 的 `<` 一直是**指针比较**（`"zzz" < "aaa"` 可能为真），是 `07-gaps` §7.6 登记的
静默错之一。另一条轨已经把 `__str_cmp` 和**表达式路径**接上了，但条件路径
（`if s1 < s2` / `while s1 < s2`）仍走 `jcc` 直接比指针——这正是 v1.19 浮点比较
bug 的同款"双路径只改一条"。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | `branch()` 增加 str 有序比较分支：`<` `<=` `>` `>=` 走 `__str_cmp` 后与 0 比较（与 `arith()` 同口径） |
| `tools/stage0/qlm.py` | `Ord` 能力约束覆盖 `str`（此前因为 `<` 是地址比较而排除）；注释与 `_cap_desc` 同步 |
| `tests/t105_strorder.qma` | **新增**：表达式路径、`if` / `while` 条件路径、四个运算符、前缀/空串/大写/≥0x80 字节、`std/gen` 的 `gen_min[str]`/`gen_max[str]`/`gen_clamp[str]` |
| `tests/run_win_tests.py` | 注册 `t105_strorder` |
| `docs/02-language.md` | §4.5.1 能力表 `Ord` 加 `str`；§9 陷阱 12 改写（str 已修，只剩聚合） |
| `docs/07-gaps.md` | §7.6 标注"str 的有序比较 v1.66 已修"并记回归 |
| `docs/06-status.md` | 回归数字 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=198 FAIL=0 SKIP=1（与 v1.67 同批验证） |
| `python tests/lexdiff.py` | PASS=181 FAIL=0（184 个源文件） |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| 四道门禁 | 全 PASS |

## 已知边界 / 遗留

- 聚合（struct/enum）的 `==` 仍是地址比较（§7.6 剩余部分），`Eq` 仍不含聚合。
- `str` 比较是**字节序**，不是 Unicode 码点序（无规范化，见 §2 编码行）。
- `str_cmp` 每次比较要读两个长度前缀；排序 1e5 条短串时是 O(n log n) 次调用，
  目前没有 Schwartzian 变换之类的优化。
