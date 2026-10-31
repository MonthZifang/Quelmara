# v3.50 — 语法补全三件：字符串 const / 位运算复合赋值 / `for k in vec`

- 日期：2026-10-31
- 任务：用户要求"继续"；推进 qlmc 对 `std/` 的覆盖率
- 影响面：`bootstrap/qlmc/qlmc.qma`、`tests/t194_qlmc_syntax.qma`、
  `tests/qlmc_test.py`（`CASES` 加 `s29_syntax`）
- 覆盖率：**51 / 70（本版没涨）**，但 3 个模块的**障碍全部前移**
- 回归：PASS=367 → **367** FAIL=0 SKIP=0；qlmc 差分 68 → **70**

## 为什么覆盖率没涨

本版三项改动都是**语法层**的，而它们解锁的三个模块（`std/http`、`std/kv`、
`std/ws`）各自撞上了**更靠后的**新障碍。这是进展而不是回退 —— 障碍从
"看不懂的语法错误"变成了"明确的缺失能力"：

| 模块 | 改前 | 改后 |
|---|---|---|
| `std/http.qma` | `const 初值必须是编译期可求值的整型表达式` | `line 131: 函数重复定义 _fail` |
| `std/kv.qma` | 同上 | `for k in ... 目前只支持遍历 vec`（§7.40） |
| `std/ws.qma` | 同上 | `未定义变量 ST_H0`（跨模块 const，§7.39） |

如实记录：本版买的是**语法地基**，不是覆盖率数字。

## 1. 字符串 `const`

`const HTTP_HDR_CL = "content-length"` 以前直接报错 —— `_fold` 只认整型。

**改法**：`P` 加两张平行表 `cisk`（是否字符串）与 `cstr`（`strs` 下标）。
const 声明处先判 `E_STR` 再走 `_fold`；引用处按 `cisk` 分派，字符串替换成
`E_STR` 节点（与在每处直接写字面量语义等价，这正是 const 的本意）。

**为什么不用一张 `vec[str]`**：整型路径要能引用非字符串常量，混在一起会让
`_fold` 的类型判断变成"猜"。平行表与既有的 `cname`/`cval` 形状一致。

**关键细节**：引用处**必须先判 `cisk`** —— 字符串常量的 `cval` 是占位的 0，
照着建 `E_NUM` 会静默变成整数 0。那是**错编**，比报错更糟。

## 2. 位运算 / 移位复合赋值

`flags |= HP_F_TE`（`std/http` 真实写法）以前报"期望表达式"。原来只支持
`+= -= *= /= %=`。

新增 6 个标点 id（`&=` `|=` `^=` `<<=` `>>=` `>>>=`），id 从 42 起。
**`<<=` / `>>=` 是三字符，必须排在 `<<` / `>>` 的两字符判定之前** ——
否则 `a <<= 2` 会被切成 `a <<` + `=`，赋值静默消失。

解析器里直接复用既有的"展开成 `lv = lv <op> rhs`"路径。

## 3. `for k in <vec>`

`for k in 0..n` 早就支持，缺的是遍历集合。新增 `S_FOREACH` 节点。

**下标必须是独立变量**：循环变量在体里装的是**元素值**，拿它当下标会让回边的
`i+1` 从元素值出发（vec 元素若是 100，第二轮就从 100 开始读）。

**循环变量必须是元素类型**，不是 `TY_INT`：`str` 元素的值就是数据指针，标成
`TY_INT` 会让下游按整数处理（实测 `for w in vec[str]` 打印出 `5368718456`
而不是 `"x"`）。

**只做 vec，不做 map**：vec 遍历用现成的 `_vec_field` + `_vec_elem_addr`，
零新增运行时；map 要 cap/state/key_at 三个运行时例程（登记 §7.40）。

## 4. 顺带修掉两个既有 bug

### 4.1 `S_FOREACH` 编号与 `S_BREAK` 撞车（§7.38）

新加的 `const S_FOREACH = 19` 与 `const S_BREAK = 19` 撞号。于是 `break`
节点（op=19）被当成 `S_FOREACH` 降级，qlmc 把 `break` 的 `a` 字段（-1）
当集合表达式求值，在 `fc.nodes.get(-1)` 上越界。

**症状极具误导性**：连 `for i in 0..3 { if i == 1 { break } }`（完全没用
新语法）都让 qlmc 编译自己时崩成 `quelmara: vec index out of bounds`。

**定位过程**：连猜三轮都错（`_try_var` 的 -1 哨兵、`_loop_push` 的 `> d*2`
边界），每轮 2 分钟编译。最后靠**注入探针**打印 `nd.op` 才一眼看出：

```
PROBE ENTER-STMT op=19 id=5 nodeslen=11
quelmara: vec index out of bounds (fail-fast)
```

`op=19` 同时是 `S_BREAK` 和 `S_FOREACH`。

**这是本项目第三次因为「常量编号/名字与实际语义不符」浪费轮次**
（前两次：`I_CREATE` 其实是 `CreateThread`、`_op_name` 表错位）。

### 4.2 `_loop_push` 的边界差一

原来写 `len(fc.loops) > d * 2`，但 `set(d*2+1)` 要求长度至少 `d*2+2`。
长度恰为 `d*2+1`（奇数）时越界 —— 而"奇数长度"正是嵌套循环里内层刚
`pop` 完的常态。已改成 `> d * 2 + 1` 并在不足时补齐到偶数。

## 测试

`tests/t194_qlmc_syntax.qma`，加进 `tests/qlmc_test.py` 的 `CASES` 作为
**差分用例**（`s29_syntax`）—— stage-0 与 qlmc 各编一次、产物与输出逐字节
比较。这三项都改的是语义，光"能编过"说明不了算得对；`S_FOREACH` 撞号那次
正是"能编出来但算错"的形态，只有差分能抓住。

覆盖 22 项断言：字符串 const 的拼接/比较/长度/空串、整型 const 不互相污染、
五个位运算复合赋值、foreach 的求和/计数/空集合/首末元素/str 元素/
break/continue/嵌套、range 循环 + break。

## 两个 stage-0 侧的既有缺陷（登记 §7.41）

写差分用例时撞到，**都是 stage-0 错、qlmc 对**：

1. `const A = 64` 后 `A.to_str()` 报"未定义变量 A"（`let x = A` 才认）——
   stage-0 的 `postfix` 遇到 `.` 时不查 const 表。
2. `vec[i] = x` 报"下标赋值只能用于定长数组或切片"。

**方向很重要**：修 stage-0，不能把 qlmc 改成一样错 —— 否则等于把一个语言
缺陷固化进自举链。t194 暂时绕开这两处（先存变量、用变量形态），
注释里写明了原因。
