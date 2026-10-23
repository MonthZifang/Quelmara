# v1.58 — `const fn`：编译期求值（编译期求值行翻绿）

- 日期：2026-10-23
- 任务：07-gaps §1「编译期求值」行 🟡→✅——`const fn` 落地：解析期解释执行，
  与运行时的同一个函数**结果逐位一致**（有符号 64 位回卷）。
- 影响面：`tools/stage0/qlm.py`（Parser：`const fn` 声明 + 编译期解释器）、
  `tests/t98_constfn.qma`（新增）、`tests/bad/constfn_str.qma` /
  `tests/bad/constfn_call.qma`（新增负向）、`tests/run_win_tests.py`（注册）、
  `docs/02-language.md`（§4.6 重写）、`docs/07-gaps.md`（§1 行 + §8）、
  `docs/06-status.md`、`tools/stage0/qlm_cli.py`（VERSION）

## 为什么是它

语言层黄标里，这一项是**唯一不需要新运行时设施**就能翻绿的：没有新指令、没有新
内存布局、没有 ABI 改动，全部发生在解析期。同时它是库层的前置——常量表、缓冲区
尺寸、位掩码、校验和常量现在都能在编译期算完，而不是靠人肉算好写死。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | ① `const fn` 声明：`const` 后跟 `fn` → 走 `parse_fn`，标记 `const_fn`，**同时进 fns 列表**（运行时可调、照常发射）与 `const_fns` 表（编译期可调）；② 编译期解释器（约 230 行）：`_const_invoke/_const_run/_const_eval/_const_binop`，语句级 `let/赋值/if/while/return/表达式`，表达式级字面量/变量/算术/比较/逻辑/位运算/调用 const fn；③ `_const_int_expr` 的 `factor` 支持调用（`fact(5) + 1` 这类算术嵌调用）；④ 步数上限 200000、递归深度上限 64、除零/移位越界/未知语句全部 fail-fast |
| `tests/t98_constfn.qma` | **新增**：18 条断言——循环（fact / sum_to）、递归（fib 20）、位运算（popcount）、bool 返回、提前 return（clamp）、算术嵌调用、嵌套调用、溢出回卷、运行时==编译期 |
| `tests/bad/constfn_str.qma` | **新增负向**：`str` 形参必须编译期拒绝 |
| `tests/bad/constfn_call.qma` | **新增负向**：`const` 右值里调普通函数必须编译期拒绝 |
| `docs/02-language.md` | §4.6 从「常量（编译期算术）」重写为「常量与 `const fn`（编译期求值）」，含支持子集表 |

## 实现要点

- **求值口径必须与运行时一致**：解释器把每个算术结果按有符号 64 位回卷
  （`_wrap64`）。否则 `const X = fact(25)` 得到数学整数 1.5e25，而运行时
  `fact(25)` 得到 `7034535277573963776`——同一函数两个值，是最难查的那类 bug。
  测试里 `BIG == fact(25)` 专门咬这条。
- **const fn 是普通函数**：不是"只在编译期存在"的宏。它照常进 fns 列表、照常发射、
  运行时可调（DCE 会掉没用的）。这样"编译期算一遍、运行期算一遍"是同一条代码路径，
  语义不会分叉。
- **支持子集小是刻意的**：没有 str（编译期没有长度前缀对象）、没有浮点（IEEE 细节
  与运行时 f64 库要一致，风险大于收益）、没有泛型、没有跨文件。每一条都在
  `_const_check_fn` / `_const_eval` 里 fail-fast，不静默降级。
- **`const` 名字后跟 `.` 不内联**是既有规则（`F5.to_str()` 不成立）——本版没改，
  已在边界里登记。

## 验证（本轮全部现跑）

<!-- verify:begin -->
- `tests/t98_constfn.qma`：18 条断言全过（循环/递归/位运算/提前 return/
  算术嵌调用/溢出回卷/运行时==编译期），输出 `const fn ok`。
- 负向 ×2：`tests/bad/constfn_str.qma` -> `SyntaxError: const fn f: 形参 s
  的类型暂不支持（只支持 int / bool）`；`tests/bad/constfn_call.qma` ->
  `SyntaxError: line 10: const X 调用了非 const fn 的 'runtime_only'`。
- 主回归 **PASS=167 FAIL=0 SKIP=1**（合并工作区口径，数字见 06-status.md）。
<!-- verify:end -->

## 已知边界 / 遗留

- **只支持 int / bool**：`str` 形参/返回值、浮点、struct/enum 一律编译期拒绝。
- **没有泛型 const fn**：`const fn f[T]` 报错（单态化在 Lower 之后，编译期求值更早）。
- **没有跨文件种子**：`const fn` 只在声明它的文件内可见（`consts` 有两遍解析的
  跨文件种子，`const_fns` 没有）。要跨文件得把 `_consts_of` 那套两遍解析扩到函数体。
- **`const` 名字后跟 `.` / `(` 不内联**：`const N = 5` 写 `N.to_str()` 会当成标识符；
  用 `print(N)` 或先 `let x = N`。这是 v1.11 起的既有规则，本版未动。
- **`pub const fn` 不支持**（`pub` 分支只认 fn/struct/enum）；const 本就全局共享，
  不需要 pub。
- 步数上限 200000 是防御性的：正常常量计算远低于它，踩到说明写了死循环。
