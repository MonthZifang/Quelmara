# v2.82 — 解释器补子集：vec / 下标 / for / struct 字段（各配一条差分夹具）

- 日期：2026-10-27
- 任务：按"最常用"扩解释器的语言覆盖
- 影响面：`bootstrap/interp/qlm_interp.qma`、`bootstrap/qlmc/qlmc.qma`（MAX_FIELD）、
  `tests/t154_interp_vec.qma`、`tests/t155_interp_struct.qma`、`tests/interp_test.py`

## 补了什么

| 语法 | 说明 |
|---|---|
| `vec[T].new(n)` / `.push` / `.get` / `.set` / `.len` / `.clear` | 类型参数整段跳过（`vec` 不是普通标识符） |
| `v[i]` / `v[i] = x` | 下标读写；`s[i]` 取字节也走同一条路 |
| `for i in lo..hi { }` | 上下界**各求值一次**（与编译器同口径），`break` / `continue` 照常 |
| `struct S { f: T, ... }` + `S { f: e }` + `p.f` / `p.f = x` | 字段布局在解析期记表，运行期按偏移存取 |
| 后缀链 | `.字段` / `.方法(实参)` / `[下标]` 可任意串联 |

**没做**：`match`（要先把 enum 值模型做出来）和**闭包**（捕获语义是另一层）。
这两个是下一版的正经活，不是"顺手补一下"。

## 三个表示决定

1. **vec = 对象号 + 全局元素池**。`Val.i` 存对象号，元素在 `elems` 池里，
   起点/长度/容量在 `ebase`/`elen`/`ecap` 三个数组里。
   为什么不把 `(base,len,cap)` 直接塞进 Val：Val 是**按值拷贝**的，而
   `v.push(x)` 改的是"句柄指向的对象"，扩容会换 base —— 存在 Val 里的话
   调用方那份拷贝就指向旧区。存对象号则三个数组是共享的。
2. **struct = 元素池里一段连续槽**，字段下标就是声明顺序。
   但 struct 是**值类型**：绑定 / 赋值 / 进 vec / 传参都要 `copy_val` 整段复制
   （与编译器一致：聚合形参传指针 + 被调方按值拷贝）。vec 相反，是引用。
3. **`ev` 里塞不下，抽成 `ev_agg`**。加完这几段之后 qlmc 直接报
   "需要 417 个槽（已用 416）" —— 帧槽上限是硬的，只能拆函数。

## 四个坑

1. **`vlen` 重名**。新加的"vec 长度数组"叫了 `vlen`，而 St 里已有
   `vlen`（值栈的逻辑长度）—— qlmc 允许 struct 里字段重名，于是 `st.vlen`
   解析到第一个，值栈长度被当成 vec 长度写，`push` 一次之后 `len` 变成 2。
   改名成 `ebase/elen/ecap` 并留了注释。
2. **`let fn = ...`**：`fn` 是关键字，qlmc 报"let 后期望变量名"。改名 `fid`。
3. **嵌套结构体字面量串位**。`Rect { a: Point { x: 1, y: 2 } }` 里，外层字面量
   若"边解析边往 `argp` 池 push"，内层字面量的 (字段名, 表达式) 对会插进外层的
   区间里，字段全串位（表现是"Rect 没有字段 x"）。改成**先收临时 vec、
   整段一次追加** —— 和块语句是同一个套路。
4. **MAX_FIELD 撞上限**。`St` 有 26 个字段，qlmc 的 `MAX_FIELD` 是 24。
   抬到 **32**。这是**自举约束**：qlmc 必须能编译自己的源码，所以字段上限
   只能往上抬，不能"绕过"。

## 顺带发现（不是本版引入）

**qlmc 在编译错误路径上会 SIGSEGV**：先正确打印 `qlmc: line N: ...`，
然后进程以访问违例结束（bash 报 139）。`build/qlmc_v81.exe`（v2.81）同样崩，
所以是**既有 bug**，不是 MAX_FIELD 改出来的。解释器自己的错误路径不受影响
（`exit(2)` 干净退出），但编译器这条要修 —— 记进 `07-gaps §7.34`。

另外：**qlmc 不支持 struct 字段是聚合类型**（`struct R { a: Point }`），
会报"本版 struct 字段不支持聚合类型"。所以解释器的 struct 夹具只能用扁平
struct；嵌套 struct 值解释器能跑，但没有编译版可对拍。

## 验证

```
== 解释执行 vs 编译执行（逐字节） ==
  [PASS] t151_interp_arith.qma: 20 行
  [PASS] t152_interp_control.qma: 5 行
  [PASS] t153_interp_fn.qma: 7 行
  [PASS] t154_interp_vec.qma: 11 行
  [PASS] t155_interp_struct.qma: 15 行
== 边界行为 == 5 条全过
INTERP: PASS=10 FAIL=0
```

新夹具钉的口径：

- `t154`：push 跨扩容、`get`/`set`/`len`/下标是同一份数据、**vec 是引用**
  （`let w = v` 之后 push 两边都看得见）、`for` 的上界只求值一次。
- `t155`：字段读写、**`let q = p` 之后改 q 不影响 p**、传参按值、
  进 vec 再取出来是独立一份、str/f64 字段。
