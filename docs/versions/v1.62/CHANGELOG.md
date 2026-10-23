# v1.62 — 泛型 struct 的方法（impl 泛型 struct）：红标 → 黄标收窄

- 日期：2026-10-23
- 任务：`07-gaps.md` §1「泛型 struct / 泛型方法」行里的**泛型方法 / impl 泛型 struct**
  落地——`Box[int]` 之前只是数据，不能带方法，通用容器（Box/Pair/Stack）没法写
  `show/get/push`，只能用自由函数 + 手写特化。
- 影响面：语言（`tools/stage0/qlm.py`）、测试（1 正向 + 5 负向）、基准、文档

## 为什么是它

§8 顺序：v1.61 类型约束之后就是泛型方法。约束解决了"模板体能对 T 做什么"，
方法解决"类型能对外提供什么"——两者合起来，泛型容器才第一次能当库用：

```quelmara
interface Show { fn show(self) -> str }

impl Box[T] : Show { fn show(b: Box[T]) -> str { ... } }   // 一次声明，所有实例各一份
impl Box[int] : Show { fn show(b: Box[int]) -> str { ... } } // 只给一个实例
```

## 语义

| 写法 | 含义 | 产物 |
|---|---|---|
| `impl Box[int] : Show` | 只给具体实例实现 | `Box__int__show` |
| `impl Box[T] : Show` | 模板：按**已实例化**的每个 `Box__X` 各展开一份 | `Box__int__show` / `Box__str__show` / … |
| `impl Pair[A, B] : Show` | 多类型参数模板 | `Pair__int_str__show` / … |

- 方法体里的 `T`、`Box[T]`、`Pair[T, int]`（部分具体）、`T { ... }` 字面量、
  `f[T](...)` 显式实例化，全部按实例替换。
- 静态派发 `b.show()` 直接 `call Box__int__show`（与手写函数同速）；
  `let s: Show = b` 之后走 vtable，`vec[Show]` 异构容器可用。
- 同一接口对同一实例只能实现一次（具体 impl 与模板 impl 撞车 → 编译期报错）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | ① `impl` 左侧支持 `Name[args]`（具体实例 → 现场单态化；`args` 里"不认识的具名类型"= 类型参数 → 模板）。② `_instantiate_struct` 新增**符号类型**分支：泛型 impl 模板里的 `Box[T]` 不实例化，返回 `Box__T` 并登记实参表。③ 新增 `_subst_gimpl`（纯改名替换：`named` / `tp_lit` / `structlit`/`enumlit` 路径 / `gcall` 类型方括号）。④ `parse_program` 末尾物化：按 `struct_instances` 逐个实例展开方法，登记进 `self.impls` 后**复用既有接口一致性检查**。⑤ `parse_fn` 的 `_cur_tparams` 提前到签名解析（此前只覆盖函数体）。⑥ 泛型函数里 `Box[T]` 从"静默造假 struct `Box__T`"改为 fail-fast |
| `tests/t102_generic_impl.qma` | **新增**：模板 impl（int/str/f64）、具体实例 impl、多参数模板、容器字段（`Stack[T].items`）、部分具体（`Pair[T, int]`）、静态/动态派发、`vec[Show]` 异构容器、具体实例作形参/返回值 |
| `tests/bad/gimpl_*.qma` | **新增 5 个负向**：`gimpl_missing`（模板缺方法）/ `gimpl_dup`（同接口重复实现）/ `gimpl_rettype`（返回类型不符）/ `gimpl_notgeneric`（非泛型 struct 带实参）/ `gimpl_generic_fn`（泛型函数里的 `Box[T]`） |
| `tests/run_win_tests.py` | 注册正向 + 5 条负向（各带 needle） |
| `tests/parsediff.py` | `t102_generic_impl.qma` 记入 `PARSE1_PENDING` |
| `bench/gimpl_bench.qma` | **新增**：静态派发 / 手写函数 / 动态派发三方对照 |
| `docs/02-language.md` | §4.2 补"方法（v1.62）"小节 + 未做项收窄为泛型 enum；§4.4 补 impl 左侧可为泛型 struct |
| `docs/07-gaps.md` | §1 行改名为「泛型 struct / 泛型方法 / 泛型 enum」，泛型方法 ✅ v1.62；§8 顺序更新 |
| `docs/06-status.md` | 回归/对拍数字 + §3.4d 派发成本 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.62.0 |

## 实现要点

- **符号类型**：解析泛型 impl 模板时，`Box[T]` 返回符号名 `Box__T` 且**不建结构体**
  （以前会建一个字段类型为 `T` 的假 struct，只对单字实参"碰巧能用"）。物化时按
  `symbolic_structs` 里登记的实参表替换成 `Box__int`，必要时先把目标实例落实例
  （`Pair[T, int]` → `Pair__str_int`）。
- **物化时机**：`parse_program` 末尾一次性展开（而不是 `_instantiate_struct` 里即时展开），
  这样 `impl Box[T]` 写在 `Box[int]` 使用点之后也能覆盖到，且不受解析顺序影响。
- **校验复用**：物化出来的方法登记进 `self.impls`，v1.8 的接口一致性检查（方法齐全 /
  参数个数 / 接收者 / 返回类型）原样生效；报错文案用源码写法 `Box[T]` 而不是 `Box__T`。
- **零后端改动**：产物是普通函数 `Box__int__show`，Lower / 优化器 / 三个后端都不知情。
- **一个被自己踩到的坑**：`parse_fn` 早先把 `_cur_tparams` 只设在函数体上，v1.62 提到
  签名后，非泛型方法（`fn show(b: Box[T])`）会把外层作用域清空——已改成"非泛型函数
  继承外层"，否则 `Box[T]` 又会被实例化成假 struct。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=188 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证，沙箱拦） |
| `python tests/lexdiff.py` | PASS=171 FAIL=0（174 个源文件） |
| `python tests/parsediff.py` | PASS=131 FAIL=0（跳过 7 个：interface/泛型/约束/泛型 impl） |
| `python tests/irdiff.py` | PASS=73 FAIL=0 SKIP=57 |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| 四道门禁 | check_names / check_origin / check_docs / gen_stdlib_doc --check 全 PASS |
| `bench/gimpl_bench.qma` | 静态 1.7 / 手写 1.7 / 动态 3.4 ns/次（20M 次，min of 3） |

## 已知边界 / 遗留

- **泛型 enum 仍未做**（`enum Tree[T] { ... }`），是这一行剩下的最后一项。
- 泛型函数里不能把类型参数用作泛型 struct 的类型实参（`fn f[T](x: Box[T])`）——
  编译期明确报错并给出两条出路（用具体类型 / 写进泛型 impl 模板）。
- `impl Box[T] : Iface` 只按**已实例化**的实例展开：模板声明后若没有任何 `Box[X]`
  出现，方法就不存在（调用会报"方法未定义"）。
- 同一接口对同一实例只能实现一次；跨接口同名方法仍不支持（v1.9 起的既有边界）。
- 泛型 impl 模板的方法体里不能再用"另一层模板参数"（`impl Box[T]` 里写 `Pair[T, U]`，
  `U` 无处绑定）。
