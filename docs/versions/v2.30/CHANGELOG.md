# v2.30 — `const` 的编译期求值，子集 S16

- 日期：2026-10-25
- 任务：**`const` 常量表达式** —— 上一版结尾定位出的"自举第三个硬阻塞"
- 影响面：自举层（qlmc 解析 / 常量表）/ 测试 / 文档

## 主事件：const 右值可以是表达式

```quelmara
const A = 5
const B = A * 4 + 1          // 21
const C = (A + B) * 2        // 52
const NEG = -7               // 以前会被当成"未定义"，这版一起修了
const D = 100 / 7            // 14（C 截断语义）
const E = NEG + B            // 14
```

做法：`const` 的右值先交给**正常的表达式解析器**（`_expr`），拿到 AST 后用一个
小的 `_fold` 在解析期递归折成整数。这样**优先级自动与语言一致**，不用另写一套
降级解析器。

`_fold` 认：整型字面量、**已定义**的常量、一元 `-` `~`、二元
`+ - * / % & | ^ << >> >>>`。折不动的节点一律 fail-fast：

```
$ qlmc const_bad.qma
qlmc: line 2: const 初值只能引用**已定义**的常量（按声明序求值）
qlmc: line 2: const 初值编译期除零
qlmc: line 2: const 初值里的二元运算只支持 + - * / % & | ^ << >> >>>
```

**口径差异（有意为之）**：stage-0 的 `const` 右值只支持 `+ - * / %`
（`parse_const_value`），qlmc 支持位运算与移位是**超集**。只多不少，不影响逐字节
差分；但夹具里只能用两边都认的写法（`s17_constexpr.qma` 就避开了位运算）。

除法/取模沿用语言语义（`idiv`，C 截断），负数符号都对：
`-100 / 7 = -14`、`-100 % 7 = -2`。

## 顺带修掉的老 bug：`const NEG = -7` 引用不了

`_const_of` 用 **-1 当"没找到"的哨兵**：

```quelmara
fn _const_of(p: P, nid: int) -> int {
    ...
    return -1          // ← 和"值就是 -1"撞了
}
```

于是 `const NEG = -7` 被引用时 `_const_of` 返回 -7（< 0），调用点判定为"不是常量"，
继续走变量路径 → 报"未定义变量"。改成 `_const_idx` 返回**下标**（-1 = 没找到），
值另取。这个坑以前没人踩，是因为没人写过负值常量。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=45**（21 组用例 + 并行确定性 2 条；新增 `s17_constexpr`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s17_constexpr.qma` | 24 行输出与 stage-0 逐字节相同：折叠结果、除法/取模符号、常量参与运行期表达式、常量当 vec 容量/循环上界/数组长度 |
| fail-fast 手工验证 | 引用未定义常量 / 编译期除零 / 比较运算出现在 const 初值，三种都报错退出 |

## 自举进度：第三个阻塞已清，下一个是 `vec[Struct]`

```
$ ./qlmc.exe build bootstrap/qlmc/qlmc.qma -o build/self.exe
（v2.29）qlmc: line 236: const 只支持整型字面量          ← 已清
（v2.30）qlmc: line 307: 本版 vec 元素只支持 int/bool/str  ← 下一个
```

line 307 是 `nodes: vec[Node]`（还有 `vec[Ir]` / `vec[Fix]` / `vec[Fn]`）。
**下一版做"聚合作容器元素"**：vec 的元素步长从固定 8 字节改成 `_ty_size(elem)`，
`_vec_elem_addr` 的 `ADDRX` 要能按任意步长算（现在是 `shl 3` 写死的），
push/get 改成按 `elem_size` 做 `OP_COPY`。这条做完，qlmc 的数据结构就能自举了。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `const` 右值改走 `_expr` + `_fold`（新函数）；`_const_of` → `_const_idx`（返回下标，修 -1 哨兵）；`_primary` 的常量内联改用下标判定 |
| `tests/selfhost/s17_constexpr.qma` | **新增**：const 表达式差分夹具 |
| `tests/qlmc_test.py` | 用例 20 → 21 |
| `docs/05-toolchain.md` | §1.11 改 S16；声明行改"整型常量表达式"；不支持表换成「聚合作容器元素」；坑表补 #27（-1 哨兵） |
| `docs/07-gaps.md` | §3 stage-1 行更新 |
| `docs/06-status.md` | §3.25 加 `s17` 行、体积与耗时更新 |

## 已知边界

- const 只支持 **int**（str/bool 常量仍然不支持，stage-0 支持）。
- 不支持 `const fn` 调用（stage-0 从 v1.58 起支持 `const A = sq(3) + 1`）。
- 位运算是超集（stage-0 拒绝），跨编译器复用源码时要注意。
- 没有溢出检查：`const X = 9223372036854775807 + 1` 静默回绕（与语言运行期口径一致）。
- 仍然缺：聚合作容器元素、f64、泛型、宏/反射、接口、`rc`/`Drop`、闭包捕获、
  `vec[vec[T]]`（§7.18）、map 扩容、`mk(...).x`（对调用结果取字段）。
