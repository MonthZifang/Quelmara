# v3.52 — 跨模块 const + str 切片（收 §7.39）

- 日期：2026-10-31
- 任务：用户要求"继续"；推进 qlmc 对 `std/` 的覆盖率，收 §7.39
- 影响面：`bootstrap/qlmc/qlmc.qma`（三段式解析 + `_lower_str_slice` +
  const 表 upsert）、`tests/t196_qlmc_strslice.qma`、
  `tests/modconst/{mc_mod,mc_main}.qma`、`tests/modconst_test.py`、
  `tests/qlmc_test.py`、`tests/run_win_tests.py`
- 覆盖率：**51 / 70（本版没涨）**，但 `std/ws` 与 `std/sse` 的障碍全部前移
- 回归：PASS=367 → **368** FAIL=0 SKIP=0；qlmc 差分 72 → **74**

## 为什么覆盖率没涨

本版解开的是 `std/ws` 和 `std/sse` 的 **const 障碍**与 **str 切片障碍**，
但这两个模块各自还有别的缺口：

| 模块 | 改前 | 改后 |
|---|---|---|
| `std/ws.qma` | `未定义变量 ST_H0` | `未定义函数 thread_start` |
| `std/sse.qma` | `未定义变量 ST_H0` | `未定义函数 thread_start` |

`thread_start` 现在一次挡 **3 个**模块（`std/net/reactor`、`std/ws`、`std/sse`），
是剩余缺口里最大的单点。如实记录：本版买的是**两个语言特性**，不是覆盖率数字。

## 1. 跨模块 const

**问题**：`import m` 之后引用 `m` 里的 const，qlmc 报 `未定义变量`。

**根因**：`parse` 会把 const 引用**当场**折成 `E_NUM`/`E_STR` 节点，而原来
的顺序是「parse 主文件 → 再装载 import」。主文件 parse 时被 import 模块的
const 还没进表，`MX` 被定型成 `E_VAR`（普通变量引用）—— 之后再补 const 表
也没用，节点已经定型了。

**修法**：三段式解析。

```
0. _prescan_imports(主文件)          只要 import 路径
1. 循环装载：每个模块先 _prescan_consts 再 _prescan_imports，
   直到 import 集合不再增长（只预扫描，不 parse）
2. _prescan_consts(主文件)
3. 统一 parse —— 此时所有 const 都在表里
```

第 1 步的循环必须能"发现新模块"：模块 A import B 时 B 也要先进表。

**预扫描只认两种初值**：字符串字面量、单个整数字面量（可带前置 `-`）。
复杂表达式整条跳过，留给第二遍 `parse`。原因：`_expr` 会一路解析到表达式
结束，而 qlmc 自己的源码有 9 万多个 token —— v3.51 实测在主文件的预扫描上
越界崩（`vec index out of bounds`）。预扫描的职责只是"让**跨文件**引用能
命中"，同文件内的 const 引用本来就按声明序可见。

### 关键陷阱：`parse` 里必须 upsert，不能 push

第一版 `parse` 的 const 分支是**无条件 `p.cname.push(...)`**。预扫描已经把
本文件的 const 登记过一遍，于是表里出现**重复项**：

- `_const_idx` 返回第一次出现的下标（预扫描登记的那份）；
- 预扫描只认简单字面量，复杂初值的真实结果在**第二份**里，永远读不到。

后果不是报错，而是**静默错编**：stage-2 编出的 qlmc 行为与 stage-1 不同
（30/30 组产物不等价），而且它编**任何**文件都报 `编译缓冲不够（线程 0）`
—— 连 5 KB 的 `s1_basics.qma` 也是。查了半天 `ARENA_CAP` 才发现
根本不是空间问题，是 const 表被污染了。

改成"有则更新、无则追加"后，自举立刻恢复 30/30 + 不动点成立。

**这是本项目第四次因为「同一张表被写两遍」浪费轮次**（前三次：`I_CREATE`
其实是 `CreateThread`、`_op_name` 表错位、`S_FOREACH` 编号撞 `S_BREAK`）。
共同点都是"看着能跑、结果静默错"。

## 2. str 切片

**问题**：`data[start..i]` 报 `qlmc: 只有数组 / vec / 切片能切片`。

**为什么不能复用视图路径**：Quelmara 的 str 值**本身就是数据指针**，长度藏在
`p-8` 的 8 字节头里。返回 `(ptr,len)` 视图会破坏这个 ABI —— 下游任何
`len()` / 拼接都会读 `ptr-8`，拿到的是**原串**的长度。

**修法**：拷一份新串，算法逐句对齐 stage-0 的 `qlm_native.py`：

```
cnt = hi - lo
h   = __alloc(cnt + 9)        // 8 字节头 + cnt 数据 + 1 NUL
buf = h + 8                   // 数据指针
__memcpy(buf, s + lo, cnt)
h[0] = cnt                    // 长度前缀
buf[cnt] = 0                  // NUL
```

**两个实现细节**：

1. `__memcpy` 的长度是运行时值（`hi - lo`），所以必须用 `OP_MEMCPYN`
   （字节数放 `dst` 槽），不能用 `OP_COPY`（只吃编译期 imm）。
2. `RT_ALLOC` 返回的是**块基址**，`buf = h + 8` 才是数据指针
   （与 `_bi_read_text` 的 `dp = buf + 8` 一致）。

**类型推断也要跟着改**：`_ty_of_expr` 对 `E_SLICE` 一律返回 `TY_SLICE + elem`，
str 切片必须返回 `TY_STR` —— 否则 `let t = s[0..5]` 会被当成聚合赋值，
报"聚合赋值两侧类型不一致"。

## 3. 一个 stage-0 侧的意外发现

写跨模块 const 的差分用例时发现：**stage-0 本身不支持跨模块 const**，
而且连 `pub const` 都不认（`pub 只支持 fn/struct/enum/interface`）。

```
$ python tools/stage0/qlm_cli.py build tests/modconst/mc_main.qma --target win
[qlm] 编译错误：未定义变量 MC_INT
```

所以这个特性是 **qlmc 独有的**，没有"两边逐字节对比"的基准。

**方向很重要**：这里 qlmc 比 stage-0 强。不去为了"能差分"而把 qlmc 也弄坏
—— 那等于把一个语言缺陷固化进自举链（同 §7.41 的口径）。测试改用
**自检**（`tests/modconst_test.py`，期望值按 const 定义手工算出，不是跑一遍
抄回来）。

## 测试

| 夹具 | 类型 | 结果 |
|---|---|---|
| `tests/t196_qlmc_strslice.qma`（`s31_strslice`） | 差分（vs stage-0） | 17 行输出逐字节一致 |
| `tests/modconst/mc_main.qma`（`t197`） | **自检**（stage-0 不支持） | PASS=13 |

`t196` 覆盖：基本切片 / 两段 / 空切片 / 全长 / 长度是新串自己的 /
拼接 / 原串不变 / 连续切片 / 单字符 / 参与长度运算 + 同文件字符串 const。

`t197` 覆盖：跨模块整型 const / 字符串 const / 空串 / 负数 / 十六进制 /
跨模块函数内引用 / 参与算术 / 参与拼接 / 参与比较。

qlmc 差分 **72 → 74**，主回归 367 → **368**。

## 方法教训

这一版是"上一版失败后的重做"，失败原因不是方向错，而是**一个 upsert 没写**。
复盘上一版为什么没定位到：

1. 上一版同时改了三件事（预扫描 + str 切片 + 词法 `\xNN`），失败时无法
   判断是哪一件。这一版**先只做跨模块 const**，验证自举通过后才加 str 切片。
2. 上一版看到 `编译缓冲不够` 就去找 `ARENA_CAP`，方向错了 —— 那只是**症状**。
   这一版先用探针确认 `cap=4193568` 正常，才意识到"不是空间问题"。
3. 上一版在 `len()` 崩溃上连猜 6 轮。这一版先确认 `_len_of` 已修
   （v3.51 的成果），再动切片。

**一次只改一件事，且每一步都验证自举** —— 这是自举项目的硬约束：
stage-2 的失败往往是**静默错编**，不会在编译期报错。
