# v2.26 — 闭包（无捕获），子集 S12；顺带修掉 `_ty_is_agg` 的老 bug

- 日期：2026-10-25
- 任务：闭包（剩余 5 项里我判断最可行的一个）
- 影响面：自举层（qlmc 前后端）/ 测试 / 文档

## 主事件：闭包（本版无捕获）

```quelmara
let double = fn(x: int) -> int { return x * 2 }
print(double(21))          // 42
let f = double             // 别名 = 拷贝闭包值
print(f(5))                // 10
```

| 环节 | 做法 |
|---|---|
| 字面量 | `fn(params) -> T { body }` 在表达式位置：**合成一个顶层函数**（名字 `__lambda_N`），表达式节点 `E_CLOSURE` 存它的序号 |
| 值 | `TY_FN` = `{code, env}` 两字聚合（16 字节），与 struct/切片共用"值 = 区域地址"的表示 |
| 创建 | `OP_LEAFN` 取函数地址（`lea rax,[rip+disp]`，走 FK_FN 回填）+ env 写 0 |
| 调用 | 闭包**变量**的调用走 `OP_CALLR`：`mov r11,[闭包]` + `call r11`；实参仍按 RCX/RDX 传（无捕获时被调方就是普通函数，ABI 完全一致） |
| 别名 | `let f = double` 是 16 字节拷贝 ✓ |

**边界**：没有捕获（闭包体只能用自己的形参和顶层函数），没有嵌套闭包、没有闭包作形参类型标注。

## 顺带修掉的真实 bug：`_ty_is_agg` 一直是旧版本

排查闭包时发现 `let d = fn...` 的 `d` 被当成**标量**（存进寄存器）。根因是
`_ty_is_agg` 还是 v2.20 那个写法：

```quelmara
if ty >= TY_STRUCT && ty < TY_VEC { r = 1 }   // ← 漏了 TY_SLICE(0x20000) 与 TY_FN(0x30000)
if ty >= TY_ARRAY { r = 1 }
```

也就是说 **v2.22 的切片一直是"半个聚合"**：`_new_var` 只给它一个 8 字节槽，
而 `_lower_slice` 往里写 16 字节（ptr + len）——靠"相邻槽恰好空闲"侥幸通过全部用例。
闭包（第二个字是 code 指针）把这个隐患直接引爆了。

修法：改成按区间判定——`int/bool/str` 与 `vec`/`map` 句柄是标量，其余（struct /
enum / array / slice / 闭包）都是聚合。修完切片与闭包都正常，35 条旧用例全绿。

> 教训：**区间式的类型编码，判定函数必须随新类型码一起改**；`_ty_is_agg` 漏一个
> 区间的表现是"能跑但内存布局错位"，不会立刻报错。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=37**（17 组用例 + 并行确定性 2 条；新增 `s13_closure`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s13_closure.qma` | 6 行输出与 stage-0 逐字节相同（`42/33/10/15/101/201`） |

`s13_closure` 覆盖：单参/双参闭包、闭包别名、闭包体内调普通函数、同函数多闭包互不干扰。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 闭包字面量（合成函数 + `E_CLOSURE`）、`TY_FN`、`OP_LEAFN` / `OP_CALLR`、闭包变量调用分派、`_try_var`；**`_ty_is_agg` 改成区间判定**；`_alloc` 的跨调用判定加 `OP_CALLR` |
| `tests/selfhost/s13_closure.qma` | **新增**：闭包差分夹具 |
| `tests/qlmc_test.py` | 用例 16 → 17 |
| `docs/05-toolchain.md` | §1.11 改 S12；坑表补「区间式类型码要同步判定函数」 |
| `docs/06-status.md` / `07-gaps.md` | 数字与 stage-1 行更新 |

## 已知边界

- **无捕获**：闭包体引用外层变量会报"未定义变量"（捕获要环境布局 + 捕获分析）。
- 闭包最多 2 个形参、形参/返回限 int/bool/str。
- 闭包不能作形参类型标注（`fn f(cb: fn)` 不支持）；把闭包传给普通函数只能靠 int 句柄。
- 仍缺：f64、泛型、宏/反射、接口、`rc`/`Drop`；vec/map 固定容量。
