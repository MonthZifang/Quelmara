# v2.80 — 解释器 `qlm_interp`：不编译，直接跑 .qma（用 Quelmara 写）

- 日期：2026-10-27
- 任务：新增组件 —— 语言的第二条执行通道
- 影响面：`bootstrap/interp/qlm_interp.qma`（新增 1400 行 Quelmara）、
  `tests/interp_test.py`、`tests/t151..t153`、`tests/run_win_tests.py`、
  `docs/05-toolchain.md` §1.13、`docs/07-gaps.md` §7.33

## 是什么

一个**用 Quelmara 写的树遍历解释器**，由 qlmc 编成裸 PE（无 CRT、无第三方
运行时）。不编译，直接读 `.qma` 执行；`--repl` 进交互模式。

```bash
build/qlmc.exe build bootstrap/interp/qlm_interp.qma --target win -o build/qlm_interp.exe
build/qlm_interp.exe examples/hello.qma
build/qlm_interp.exe --repl
```

## 为什么值得做

不只是"改完想立刻看结果"。更重要的是它给了编译器一个**独立的语义参照**：
同一份源码，解释执行与编译执行必须**逐字节相同**。这条判据和"自举不动点"
是一对 —— 前者管"语义没跑偏"，后者管"编译器能重建自己"。

`tests/interp_test.py` 就是钉这条的：每个夹具跑两遍（解释 / 编译），比 stdout
与退出码，逐字节。**这条测试在写解释器的过程中立刻抓到了三处口径差异**
（见下），每一处都是"编译器就是这么干的"，不是解释器的自由。

## 设计取舍

| 决定 | 理由 |
|---|---|
| 树遍历，不生成字节码 | 解释器本身要能被 qlmc 编译（子集 S20）；字节码 VM 多一层编解码，收益等有正确基线再谈 |
| 动态类型 `Val { k, i, f, s }` | 只需对**类型正确的程序**给出正确结果；类型检查留给编译器，避免第二套类型口径 |
| AST = 下标数组 + 连续区间 | 块 = (起点, 条数)、实参 = (起点, 个数)；解析时"整块一次追加"保证连续 |
| 可变状态全放 vec | qlmc 传结构体形参是"传指针 + 被调方按值拷贝"：标量字段改不回去，vec 字段是句柄能改回去 |
| 扁平绑定栈 | `binds` 存 (名字下标, 槽位)，从栈顶往下找 → 天然支持遮蔽；帧返回只回退**逻辑长度**，槽位复用（否则 fib(30) 要吃掉上百 MB） |

支持的子集（v1）：`fn` / `let` / 赋值 / `while` / `if-else if-else` / `return` /
`break` / `continue`；int、str、bool、f64 字面量；`+ - * / %`、`== != < <= > >=`、
`&& || !`；函数调用（含递归、多参数）；`print` / `eprint` / `len` / `assert`；
`const` 全局；`module` / `import` / `struct` 声明跳过。

还没做：vec / map / struct 值 / enum / match / 闭包 / 下标 / 字段访问 / for。

## 写的时候踩的四个坑

1. **`vec[T].new(n)` 只给容量，长度是 0**。解释器有 8 个"单槽状态"（游标、
   帧基址、返回值…），一律 `new(1)` 之后直接 `set(0, ...)` —— 全部撞越界检查，
   表现是 **`exit 1` 且一个字节都不打印**（qlmc 的 die 路径）。必须在
   `st_new()` 里 push 出第 0 格。
2. **qlmc 的"第 5 个及以后的 f64 形参"传错**（已记进 §7.33）。`mknd` 的
   第 7 个形参是 f64，读出来是 denormal 垃圾。绕法：浮点字面量放进
   `fp: vec[f64]` 池，节点只存下标。**绕法不是修复**，qlmc 侧要修。
3. **`print(bool)` 的口径不是想当然的**。差分抓到三处：
   - `print(true)` / `print(1 < 2)` / `print(!true)` → **1 / 0**
   - `print(a && b)` / `print(a || b)` → **true / false**
   - `print("x" == "x")` → **true**（字符串比较是真 bool），整数比较是 1/0

   也就是说比较运算产出 int，逻辑运算产出 bool，字符串比较产出 bool。
   解释器照抄，否则差分永远差几行。
4. **块语句在池里必须连续**。嵌套块先解析、先落池，如果外层也边解析边落池，
   外层的"区间"会把嵌套语句一起圈进来。改法是每块先收进临时 vec、整块一次追加。

## 验证

```
== 解释执行 vs 编译执行（逐字节） ==
  [PASS] t151_interp_arith.qma: 20 行输出逐字节一致，rc=0
  [PASS] t152_interp_control.qma: 5 行输出逐字节一致，rc=0
  [PASS] t153_interp_fn.qma: 7 行输出逐字节一致，rc=0
== 边界行为 ==
  [PASS] 语法错：非零退出
  [PASS] 语法错：诊断带行号
  [PASS] 没有 main：非零退出
  [PASS] 文件不存在：非零退出
  [PASS] 无参数：打印用法并非零退出
INTERP: PASS=8 FAIL=0
```

已挂进 `tests/run_win_tests.py` 的调试链路（CI 会跑），不需要改 workflow 文件。

## 下一步

按"最常用"补子集，每补一个加一条差分夹具：`vec` → 字段访问 / `struct` 值 →
`for` → `match` → 闭包。`vec` 是第一个，因为绝大多数示例都要它。
