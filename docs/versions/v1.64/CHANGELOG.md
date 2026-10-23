# v1.64 — 泛型 enum 的方法 + `Show` 能力约束

- 日期：2026-10-23
- 任务：① `impl Opt[T] : Show`（泛型 impl 覆盖 enum，v1.63 只认 struct）；
  ② 能力约束新增 `Show`（`x.to_str()`），并让 **impl 模板**也支持类型约束
  （`impl Opt[T: Show] : Show`）。
- 影响面：语言（`tools/stage0/qlm.py`）、测试（1 正向 + 2 负向）、文档

## 为什么是它

v1.63 的泛型 impl 模板只接受泛型 **struct**；enum 想要方法只能退化成自由函数。
更麻烦的是**静默错**：模板体里 `v.to_str()` 对聚合实参不会报错，而是把指针当整数
打印（`Some(140702967414824)`）——v1.61 的能力约束只管运算符，`to_str` 不在表里。

这一版把两件事一起收口：泛型 enum 能实现接口，且 `to_str` 有了 `Show` 约束，
实参不满足时在**编译期**报错。

## 语义

```quelmara
enum Opt[T] { Some(v: T), None }

impl Opt[T: Show] : Show {
    fn show(o: Opt[T]) -> str {
        return match o {
            Opt[T].Some(v) => "Some(" + v.to_str() + ")"
            Opt[T].None => "None"
        }
    }
}

Opt[int].Some(v: 3).show()      // "Some(3)"
Opt[str].Some(v: "hi").show()   // "Some(hi)"
Opt[Point].Some(v: p).show()    // 编译期报错：Point 不满足 Show
```

| 项 | 范围 |
|---|---|
| impl 模板目标 | 泛型 struct / 泛型 enum 都可以；按每个已实例化实例展开 |
| impl 模板约束 | `impl Opt[T: Show] : Show`——能力约束（Ord/Eq/Num/Bit/Show），实例化时校验 |
| 方法体 | `match` 里的 `Opt[T].Some(v)` 在模板里是符号类型，物化时替换成 `Opt__int` |
| 具体实例 impl | `impl Opt[int] : Tag` 与模板 impl 共存（不同接口） |
| 静态派发 | `o.show()` 直接 `call Opt__int__show`，零开销 |
| 未做 | 枚举装箱成接口值（`let s: Show = o`）——`box_iface` 只按 struct 布局取宽度 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | ① 能力表新增 `Show`（`_BOUND_OPS` 里挂 `to_str`，`_cap_supports` 认整数/浮点/bool/str）。② 体遍历器把 `x.to_str()` 当成一次能力使用。③ impl 头部支持泛型 enum 目标 + 每个类型参数的能力约束 `[T: Show]`。④ `_instantiate_enum` 增加**符号类型**分支（`impl Opt[T]` 里的 `Opt[T]` 不实例化，登记实参表）。⑤ 物化按 `kind` 选实例表（struct / enum），并校验 impl 模板约束。⑥ `_subst_gimpl` 增加 `pat` 路径换名。⑦ 接口一致性检查允许 enum 作 impl 目标 |
| `tests/t104_generic_enum_impl.qma` | **新增**：Opt[T: Show] 模板 impl（int/str/bool）、Either[A: Show, B: Show] 多参数、方法体内 match、具体实例 impl 共存 |
| `tests/bad/genumimpl_*.qma` | **新增 2 个负向**：`genumimpl_bound`（struct 实参不满足 Show）/ `genumimpl_missing`（模板 impl 缺方法） |
| `tests/run_win_tests.py` | 注册正向 + 2 条负向；`gimpl_notgeneric` 的 needle 跟着文案改成"不是泛型类型" |
| `tests/parsediff.py` | `t104_generic_enum_impl.qma` 记入 `PARSE1_PENDING` |
| `docs/02-language.md` | §4.3 泛型 enum 表补"方法"行；§4.5.1 能力表加 `Show` |
| `docs/07-gaps.md` | §1 interface 行补"enum 不能装箱"；新增 §7.7（enum 的 f64 载荷当整数用，待查） |
| `docs/06-status.md` | 回归/对拍数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.64.0 |

## 实现要点

- **符号类型统一**：`symbolic_structs` 的条目升级成 `(模板名, 实参表, kind)`，
  struct 与 enum 共用同一套"先落实例再换名"的物化逻辑。
- **约束在物化时校验**：`impl Opt[T: Show]` 的每个实参逐个查能力表，报错文案带源码写法
  `impl Opt[T: Show] 的实参 P 不满足 Show（整数/浮点/bool/str（可 to_str））`。
- **`Show` 的边界**：只覆盖标量（整数/浮点/bool）与 `str`；聚合值没有结构化的 to_str
  （v1.61 起 `Eq`/`Ord` 也不含聚合，口径一致）。
- **踩到的既有坑**（都已登记 07-gaps）：
  - enum 装箱成接口值直接报"未声明的结构体"——`box_iface` 用 `struct_size`，
    没走 `agg_size`（非泛型 enum 同样中招，属既有缺陷）；
  - enum 的 `f64` 载荷取出来当整数（match 绑定丢浮点标记），所以 t104 不覆盖 f64。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=196 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证，沙箱拦） |
| `python tests/lexdiff.py` | PASS=179 FAIL=0（182 个源文件） |
| `python tests/parsediff.py` | PASS=131 FAIL=0（跳过 9 个：interface/泛型/约束/泛型 impl/泛型 enum） |
| `python tests/irdiff.py` | PASS=74 FAIL=0 SKIP=58（t104 用了接口 impl，A64 无 vtable 记 SKIP） |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| 四道门禁 | check_names / check_origin / check_docs / gen_stdlib_doc --check 全 PASS |

## 已知边界 / 遗留

- **枚举不能装箱成接口值**（`let s: Show = o` 报错）：`box_iface` 只按 struct 布局取宽度。
  修法是一行（`struct_size` → `agg_size`），但该文件是另一条轨的在途文件，本版没动。
- **enum 的 f64 载荷**取出来当整数（07-gaps §7.7），所以 `Show` 约束对"泛型 enum 的
  f64 实例"仍是假绿——修在 Lower，单开一版。
- impl 模板的类型参数只支持能力约束，不支持接口约束（`impl Opt[T: Shape]`）。
- 泛型函数里仍不能用 `Opt[T]`/`Box[T]` 作类型（fail-fast，v1.62 起）。
