# v2.31 — 聚合作容器元素（`vec[Struct]`）+ `else if`，子集 S17

- 日期：2026-10-25
- 任务：**`vec[Struct]`** —— 上一版结尾定位出的"自举第四个硬阻塞"
- 影响面：自举层（qlmc 类型/降级/IR/发射器/语法）/ 测试 / 文档

## 主事件：vec 的元素可以是聚合

```quelmara
struct P { x: int, y: int }
let v = vec[P].new(1)
v.push(P { x: 1, y: 2 })
v.set(0, P { x: 100, y: 200 })
print(v[0].x)          // 100
print(v.get(0).y)      // 200（要先落变量，见边界）
```

核心是**元素步长**：`OP_ADDRX` 的 `shl rcx, 3` 只对 8 字节元素成立。新增
`OP_ADDRXN`（`imul rcx, rcx, imm32`）按 `_ty_size(elem)` 算，`stride == 8` 时仍走
`shl` 快路径。跟着改的地方有五处，漏一处就是"下标越大错得越离谱"：

| 位置 | 改法 |
|---|---|
| `_vec_elem_addr` | 收 `stride` 参数，8 走 `ADDRX`、其余走 `ADDRXN` |
| `_lower_vecnew` | 数据块 = `cap * stride`（不是 `cap * 8`） |
| `_vec_grow_body` | 新块 `ncp * stride`、搬 `len * stride` 字节 |
| `push` / `set` | 聚合元素槽里存的是**值**不是指针 → 整块 `OP_COPY(stride)` |
| `get` / `v[i]` | 聚合值 = **元素地址**（沿用"聚合值 = 区域地址"的约定） |

顺带补上 `.set(i, x)`（之前 qlmc 只有 push/get/len，没有 set——而它自己的源码里
`p.nodes.set(cid, Node{...})` 用的就是这个）。

## 顺带修的三处（都是自举时撞出来的）

### ① `else if` 根本不支持

`_stmt` 的 `if` 分支在 `else` 之后直接 `_block()`，也就是**只认 `else {`**。
qlmc 自己的源码里到处是 `else if`，一编译就报 `期望标点 #3`（`{`）。修法：
`else` 后面若紧跟 `if`，就递归 `_stmt` 拿到那一条 if 语句当 else 体（单节点链）。

### ② struct 字段的"只收标量"检查用错了判据

```quelmara
if fty >= TY_STRUCT { _fail(...) }      // ← vec[Tok] 的码是 0x8000+…，也被拦了
```

`vec[Tok]` 是**标量**（8 字节句柄），只是它的类型码数值大于 `TY_STRUCT`。改成
`if _ty_is_agg(fty)`。qlmc 自己的 `struct P { toks: vec[Tok], nodes: vec[Node], … }`
正是这个形状。

### ③ `MAX_FIELD = 8` 太小

`struct P` 有 11 个字段、`struct FnCtx` 有 22 个。提到 **24**（`ST_STRIDE` 改成
`2 + MAX_FIELD * 2` 自动跟随，`TBL_SIZE` 随之变大）。错误信息里写死的"8 个"也
换成了"上限（MAX_FIELD）"。

## 结构体字面量可以当值用

以前 `P { x: 1, y: 2 }` 只能出现在 `let` / 赋值 / 字段初始化里，`v.push(P{...})`
直接报"聚合字面量只能出现在…"。现在 `_lower_expr` 遇到 `E_STRUCTLIT` 就开一块
临时区域逐字段写进去、返回区域地址——与 `E_ENUMCTOR` 完全同构。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=47**（22 组用例 + 并行确定性 2 条；新增 `s18_vecagg`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s18_vecagg.qma` | 18 行输出与 stage-0 逐字节相同：vec[P]（16 字节步长）与 vec[Big]（**24 字节步长，非 8 的幂**）的 push/get/set/len/下标读、从 1 格扩到 11 格的搬移、`else if` 链 |
| 手工（stage-0 不支持 vec 下标赋值） | `v[1] = P { x: 7, y: 8 }` 对聚合元素整块覆盖，读到 7/8，元素 0 不受影响 |

## 自举进度：第四个阻塞已清，下一个是 `spawn`/`join`

```
$ ./qlmc.exe build bootstrap/qlmc/qlmc.qma -o build/self.exe
（v2.30）qlmc: line 307: 本版 vec 元素只支持 int/bool/str  ← 已清
（v2.31）qlmc: line 6146: 期望标点 #2                      ← 下一个
```

line 6146 是并行编译那段：

```quelmara
hs.push(spawn _compile_range(arb, w, nodes, names, strs, fns, rt_pos, stt))
...
join(hs.get(w))
```

**下一版做 `spawn` / `join`**：`CreateThread`（传一个 `void*` 上下文指针，
所以要把参数打成一个结构体）+ `WaitForSingleObject` + 返回值从上下文里取。
stage-0 的实现在 `qlm_native.py` 的 `spawn`/`join` 分支，可以照着抄语义。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `_type` 放开聚合元素；`OP_ADDRXN` + 发射器；`_vec_elem_addr` 收 stride；`_lower_vecnew` / `_vec_grow_body` 步长化；`push`/`set`/`get` 聚合分支；新增 `.set`；`v[i] = x` 聚合拷贝；`E_STRUCTLIT` 当值；`else if`；struct 字段判据改 `_ty_is_agg`；`MAX_FIELD` 8→24 |
| `tests/selfhost/s18_vecagg.qma` | **新增**：vec[Struct] + else if 差分夹具 |
| `tests/qlmc_test.py` | 用例 21 → 22 |
| `docs/05-toolchain.md` | §1.11 改 S17；支持表加 `.set`/聚合元素/结构体字面量当值/`else if`；不支持表换成「spawn/join」；坑表补 #28（步长不是常量 8）/#29（句柄也算标量） |
| `docs/07-gaps.md` | §3 stage-1 行更新 |
| `docs/06-status.md` | §3.25 加 `s18` 行、体积与耗时更新 |

## 已知边界

- 聚合元素的 `get` 返回**元素地址**（不拷贝）。对 `let p = v.get(0)` 这种"立刻落到
  变量"的用法等价于值语义；但如果先把地址存下来、再让 vec 扩容，读到的是**旧块**
  （bump 分配器不回收，地址仍然有效，只是内容停在扩容那一刻）。stage-0 是拷贝，
  两者在"拿到地址后立刻扩容"这一种形状下会不同。
- 仍然不支持对调用结果直接取字段：`v.get(0).x` / `mk(...).x` 报"这个表达式不能取地址"，
  要先落变量。
- `vec[vec[T]]` / `vec[map]` / `vec[切片]` / `vec[闭包]` 仍被拒绝（类型码撞区间，§7.18）。
- 数组字面量仍只能出现在 let / 赋值 / 字段初始化里（结构体字面量放开了，数组没放）。
- 仍然缺：`spawn`/`join`、f64、泛型、宏/反射、接口、`rc`/`Drop`、闭包捕获、map 扩容。
