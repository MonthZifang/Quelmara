# v2.84 — 解释器补闭包（捕获按值快照 / 逃逸 / 调用值）

- 日期：2026-10-27
- 任务：解释器子集第 5 步（"最常用"清单的最后一项）
- 影响面：`bootstrap/interp/qlm_interp.qma`、`tests/t157_interp_closure.qma`、
  `tests/interp_test.py`

## 补了什么

```quelmara
let twice = fn(x: int) -> int { x * 2 }        // 无捕获
fn make_adder(n: int) -> closure {             // 逃逸出去
    return fn(x: int) -> int { x + n }
}
let mut k = 0
let snap = fn(x: int) -> int { x + k }         // 快照：之后改 k 不影响它
k = 100
snap(1)                                        // → 1
```

也支持"调用一个值"：`v.get(0)(5)`、`h.cb(20)`（字段里放闭包）。

## 表示

**闭包 = (体节点号, 形参区间, 捕获快照)**，`Val { k: K_CLOSURE, i: 捕获起点,
n: 捕获个数, c: 节点号 }`。

捕获池 `cpool` 每 2 格一对 `(名字下标, 元素池下标)`。

**为什么快照存在元素池里而不是值栈**：值栈的槽位在帧返回时会被回退复用，而闭包
常常比创建它的帧活得久（逃逸）。元素池（`elems`）只增不减，所以捕获值放那儿是
安全的 —— 调用时再从元素池复制一份到新帧的值栈。

**捕获是"全量快照"**：创建时把当前帧可见的绑定**逐个复制**，不做自由变量的
活跃分析。慢一点、多占一点，但语义与编译器一致（按值快照），而且不用担心
"漏捕"。

## 三个坑

1. **`ev_agg` 的帧槽又爆了**（421 > 416）。把闭包的两个分支拆成 `ev_clo`。
   这已经是这个文件第三次因为帧槽上限拆函数了 —— 上限是硬的。
2. **`ev_agg` 只拿到 `Nd`、拿不到节点号**，而闭包要存"体节点号"。把签名从
   `ev_agg(st, nd)` 改成 `ev_agg(st, ni)`，进去再 `st.nd.get(ni)`。
   这类"参数传了结构体却要的是下标"的错，表现是 `x` 未定义（闭包体读到了
   节点 0 的体）。
3. **`s.replace` 没断言等于没改**。给 `p_postfix` 加"调用值"分支时，
   我的替换模式写的是 `} else if p_is_op(st, O_LB) {`，而文件里其实是
   `if p_is_op(st, O_LB) {` —— `str.replace` 静默什么也没做，脚本照样打印
   "ok"，于是 `v.get(0)(5)` 一路被解析成 `print(v.get(0))`，输出 `<closure>`。
   **改源码的脚本必须每条替换都 assert**。

## 一个发现：qlmc 根本不支持闭包

`grep -c closure bootstrap/qlmc/qlmc.qma` = **0**。闭包与 `closure` 类型是
**stage-0 独有的能力**，qlmc（自举编译器）还没移植。

所以这条夹具的"编译参照"不能用 qlmc —— `interp_test.py` 加了
`STAGE0_ONLY = {"t157_interp_closure.qma"}`，这些夹具用 **stage-0** 编。
stage-0 是语言的参考实现（它跑得通全套 298 条回归），拿它当基准是对的。

顺带说明一件事：**解释器现在覆盖的语言比自举编译器还多一点**（闭包）。
这不是"解释器超前"，而是自举的已知阶段边界 —— 记在这里，免得下次误以为
qlmc 能编闭包。

## 顺带补的三样（跑真实示例时撞出来的）

拿 `examples/` 当试金石，撞出三个缺的东西：

| 缺什么 | 谁用到 | 补法 |
|---|---|---|
| `+= -= *= /= %=` 复合赋值 | `collatz.qma` 的 `steps += 1` | 展开成 `lv = lv <op> rhs`（左值会求值两次，变量/下标幂等，可接受） |
| `cores()` / `now_ns()` | `hello.qma` / `bench/` 下的程序 | `cores()` 恒报 1（解释器单线程）；`now_ns()` 走 QPC，与编译版同口径 |
| `.to_str()` 标量方法 | `hello.qma` 的 `i.to_str()` | 复用 `to_text` |

现在 `examples/hello.qma`、`examples/fib.qma`、`examples/collatz.qma` 都能解释执行，
输出与编译版一致。

**又一个"解释器比 qlmc 走得远"的例子**：`collatz.qma` 用了 `+=`，qlmc 在
`line 11: 期望表达式` 上直接拒绝 —— 复合赋值也是 stage-0 独有的。

## 验证

```
[PASS] t157_interp_closure.qma: 8 行输出逐字节一致，rc=0
INTERP: PASS=12 FAIL=0
```

夹具钉的六条：无捕获 / 单捕获 / 逃逸（返回出去）/ **快照语义**（创建后改外层
变量不影响闭包）/ 闭包作形参 / 闭包进 `vec[closure]`。

## "最常用"清单收尾

vec → 字段访问/struct 值 → for → match → 闭包，**五项全部完成**，每项一条
差分夹具。解释器现在能跑 `examples/` 里除了泛型/接口之外的大部分程序。
