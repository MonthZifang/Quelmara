# v1.61 — 类型约束（trait bound）：红标 → 绿

- 日期：2026-10-23
- 任务：`07-gaps.md` §1「类型约束（trait bound）」❌ → ✅——把"T 须支持 `<`"
  从**文档约定**变成**编译器强制**，违反在调用点编译失败。
- 影响面：语言（`tools/stage0/qlm.py`）、标准库（`std/gen.qma` 声明约束）、
  测试（1 正向 + 6 负向）、基准（`bench/bound_bench.qma`）、文档

## 为什么是它

§8 语言层顺序：泛型 struct（v1.59 黄）之后就是"红标逐项"，类型约束是其中唯一一条
**"文档写了要求、编译器完全不拦"**的。`std/gen.qma` 的注释写着"gen_min 要求 T 支持 `<`"，
但传 struct 实参时 Lower 把 `<` 降成整数比较——比的是**地址**，静默给出错误答案。

同一轮实测还挖出两个既有坑（登记在 `07-gaps.md` §7.6，本轮不修）：

- `Color.Red == Color.Red` 为 `false`（enum 的 `==` 也是地址比较）；
- `"zzz" < "aaa"` 可能为真（`str` 的 `<` 是地址比较）。

这两条直接决定了能力表的口径：`Eq` 不含聚合、`Ord` 不含 `str`——**约束只承诺语言真的
支持的东西**，宁可报"不支持"，也不放行一个静默错。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | ① `parse_fn` / `struct` 的类型参数改成 `while True` 循环，支持 `[T: A + B, U]`；`fdef` 首次记录声明行 `line`（报错定位）。② 新增能力表 `_BOUND_CAPS`/`_BOUND_OPS`/`_cap_supports`/`_cap_for_op`/`_cap_desc` 与体遍历器 `_iter_bound_ops`。③ `expand_generics`：`impls` 表、`check_declared`（实例化期查实参）、`check_template_body`（声明期查模板体）、`check_instance_body`（无约束模板的安全网）。④ `_instantiate_struct` 校验泛型 struct 的能力约束。⑤ `parse_program` 末尾校验约束名（interface 可能后置声明）。⑥ 修 `_GenInfer._infer` 的 `index`/`sliceof` 分支漏传 `env`（`TypeError` 潜伏 bug） |
| `std/gen.qma` | `gen_min`/`gen_max`/`gen_clamp` 声明 `[T: Ord]`，`gen_dist` 声明 `[T: Num + Ord]`，`gen_contains`/`gen_index_of` 声明 `[T: Eq]`；头部注释从"要求是文档性的"改成约束说明 |
| `tests/t101_bounds.qma` | **新增**：能力约束正例（int/f64/str/bool）、多约束、多类型参数各自带约束、接口约束（两个 impl 静态派发）、泛型 struct 约束、显式实例化与推导、约束在模板体内传递、与手写 `int_min` 逐位一致 |
| `tests/bad/bound_*.qma` | **新增 6 个负向**：`bound_unknown`（未知约束名）/ `bound_struct_ord`（struct 不满足 Ord）/ `bound_body_exceed`（体内用 `<` 但只声明 Eq）/ `bound_iface_missing`（接口约束缺 impl）/ `bound_struct_param`（泛型 struct 约束）/ `bound_enum_eq`（enum 不满足 Eq） |
| `tests/run_win_tests.py` | 注册 `t101_bounds` 正向 + 6 条负向（各带 needle） |
| `tests/parsediff.py` | `t101_bounds.qma` 记入 `PARSE1_PENDING`（stage-1 不做单态化，约束解析期就擦除） |
| `bench/bound_bench.qma` | **新增**：带约束 / 不带约束 / 手写 int 三个版本同形状对跑 |
| `docs/02-language.md` | 新增 §4.5.1（能力表 + 三层检查 + 边界）；§4.2 补 `struct Slot[T: Ord]`；§4.5 边界改写；§9 新增陷阱 12（聚合 `==` / `str` `<` 是地址比较） |
| `docs/07-gaps.md` | §1 行 ❌ → ✅；新增 §7.6（聚合 `==` 地址比较，待查）；§8 顺序更新 |
| `docs/04-compiler.md` | 流水线加"类型约束校验"；模块表行数与职责同步 |
| `docs/06-status.md` | 回归 / 对拍数字、§3.4c 约束性能 |

## 语义

约束写在类型参数后，`+` 连接多条：

```quelmara
fn my_min[T: Ord](a: T, b: T) -> T
fn max3[T: Num + Ord](a: T, b: T, c: T) -> T
fn area_twice[T: Shape](s: T) -> int      // Shape 是本文件声明的 interface
struct Box[T: Ord] { value: T }           // 泛型 struct 只接受能力约束
```

| 约束 | 授权运算符 | 满足它的类型 |
|---|---|---|
| `Ord` | `<` `<=` `>` `>=` | 整数族 + `f64`/`f32` |
| `Eq` | `==` `!=` | 整数族 + `f64`/`f32` + `bool` + `str` |
| `Num` | `+` `-` `*` `/` `%` | 整数族 + `f64`/`f32` |
| `Bit` | `&` `\|` `^` `<<` `>>` `>>>` `~` | 整数族 |
| interface 名 | 该接口的方法（单态化后静态派发） | 有 `impl T : Iface` 的类型 |

三层检查，全部编译期：

| 时机 | 检查 | 例子 |
|---|---|---|
| 声明期 | 模板体对 `T` 用到的运算符必须被**声明的**约束覆盖 | `[T: Eq]` 体内用 `<` → "约束只声明了 Eq" |
| 实例化期 | 类型实参满足声明的约束（能力表 / `impl` 表） | `my_min[P](...)` → "实参 P 不满足 Ord" |
| 实例化期 | **没写约束的模板**：体内实际用到的运算，具体类型必须支持 | `any_min[P]` → "体内对 P 使用了 `<`，但 P 不支持" |

第三层是兼容旧代码的安全网：v1.60 及以前的模板一行不用改，但 struct 实参不再静默错。

## 实现要点

- **擦除点**：检查都在 `expand_generics.ensure` 里、`copy.deepcopy` 之后与实例注册之前完成，
  实例 dict 里 `type_bounds` 被 `pop`——下游（Lower / 优化器 / 三个后端）零改动。
  `--target c` 的产物仍是 `my_min__int` 这样的普通函数（实测 `build/bc.c`）。
- **约束名解析延后到 `parse_program` 末尾**：`interface` 可能声明在泛型函数之后；
  `self._own_templates` 只收本文件模板，避免把种子（其他文件的模板）拿到本文件校验。
- **体遍历器**用 `_GenInfer` 的表达式类型推断（流不敏感、尽力而为），拿不到类型就跳过——
  宁可漏报也不误报；`_iter_bound_ops` 顺带覆盖 `+=` 这类复合赋值与一元 `-`/`~`。
- **泛型 struct 只支持能力约束**：struct 实例化发生在解析期（`parse_type`），此时 `impl`
  可能还没解析到，接口约束会变成"声明顺序敏感"，所以直接拒绝并提示写到函数上。
- **零运行时成本**：单态化产物与不带约束的模板逐字节同构——`bench/bound_bench.qma`
  三个版本 ns/次 1273 / 1273 / 1264（差值在噪声内）。

## 同版并入：插值字符串（语言轨，v1.61 前序）

> 同一工作区的另一条轨先落地了插值字符串（`f"n={n}"`），文档见
> `02-language.md` §2.3、测试 `tests/t100_interp.qma`、基准 `bench/interp_bench.qma`。
> 两条轨的文件面在 `qlm.py` 上重叠，本版合并提交；约束功能本身与插值零耦合。

- 语法：`f"..."`，段内任意表达式，支持 int/bool/f64/str，`{{`/`}}` 转义，单次分配。
- 负向：`tests/bad/interp_unclosed.qma` / `interp_empty.qma`。
- stage-1 词法器不认 `FSTR` → `lexdiff` 记 3 个 SKIP（显式记账）。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=182 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证，沙箱拦） |
| `python tests/lexdiff.py` | PASS=165 FAIL=0（168 个源文件，3 个 FSTR SKIP） |
| `python tests/parsediff.py` | PASS=131 FAIL=0（跳过 6 个：interface/泛型/约束） |
| `python tests/irdiff.py` | PASS=73 FAIL=0 SKIP=56 |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| `python tools/dev/check_docs.py` 等四道门禁 | 全 PASS |
| `bench/bound_bench.qma` | 1273 / 1273 / 1264 ns/次（bounded / unbounded / 手写） |
| 编译期开销（220 实例，min-of-5） | 带约束 2639 ms / 不带约束 2662 ms |

## 已知边界 / 遗留

- **聚合的 `==` 与 `str` 的 `<` 仍是地址比较**（`07-gaps.md` §7.6，本轮不修）。约束只是
  把"泛型里踩到"变成编译错误，语言层本身没有结构比较；修它要么在 Lower 展开逐字段比较，
  要么加 `__str_cmp` + 聚合比较内建，单开一版。
- 泛型 struct 只接受能力约束（接口约束需要 `impl` 表，见上）。
- 接口约束只校验 `impl T : Iface` 是否存在；模板体里调用的方法名是否属于该接口，
  仍由 Lower 在实例化期按具体类型解析（报"方法 X 未定义"），不是声明期错误。
- 约束只作用于类型参数，不能约束单个形参；没有泛型方法，因此也没有方法级约束。
- 模板体检查依赖流不敏感推断：分支里改绑变量类型时可能漏检（不会误报，拿不到类型就跳过）。
- `qlm fmt` 仍是早期实现（会叠加缩进、`{ r: int}` 缺空格），未进门禁；新语法 `[T: Ord]`
  能原样保留，但格式化后的文件不保证与手写风格一致——既有问题，不在本版范围。
