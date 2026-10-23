# v1.63 — 泛型 enum：泛型三件套收口（§1 该行 → ✅）

- 日期：2026-10-23
- 任务：`07-gaps.md` §1「泛型 struct / 泛型方法 / 泛型 enum」最后一项落地——
  自定义和类型（`Opt[T]` / `Either[A, B]` / 自己的 `Tree[T]`）不再需要按类型手写特化。
- 影响面：语言（`tools/stage0/qlm.py`）、测试（1 正向 + 4 负向）、文档

## 为什么是它

v1.62 之后这一行只剩泛型 enum。`option[T]` / `result[T,E]` 是编译器**合成**的枚举，
用户想写自己的和类型（三态结果、树、解析中间态）只能退化成 `(tag, payload)` 手写对。
泛型 enum 与泛型 struct 是同一套机制，补上之后 §1 这一行第一次全绿。

## 语义

```quelmara
enum Opt[T] { Some(v: T), None }
enum Either[A, B] { Left(a: A), Right(b: B) }

let a: Opt[int] = Opt[int].Some(v: 7)
let b: Opt[int] = Opt[int].None
let s = match a {
    Opt[int].Some(v) => v.to_str()
    Opt[int].None => "-"
}
```

| 项 | 范围 |
|---|---|
| 单态化 | `Opt[int]` → 普通枚举 `Opt__int`（解析期现场合成，进 `enums` 表与 `decl_order`） |
| 变体载荷 | `T` 本身或容器（`vec[T]` / `map[K]T` / `[N]T` …），按实参替换 |
| 构造 | `Opt[int].Some(v: 1)`（命名实参）、`Either[int, str].Left(a: 7)` |
| 模式 | `Opt[int].Some(x) =>`，穷尽性按**实例**的变体表检查 |
| 嵌套 / 容器 | `Opt[Opt[int]]`、`vec[Opt[int]]` 都可用 |
| 拒绝 | 裸写 `Opt`、实参个数不符、泛型函数里 `Opt[T]`（fail-fast） |
| 未做 | 泛型 `impl` 泛型 enum（`impl Opt[T] : Iface`） |

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | ① `enum` 解析支持 `[T...]`，模板存 `generic_enums`（`_prescan` 的占位要 pop）。② 新增 `_instantiate_enum`（与 `_instantiate_struct` 同构：元数/具名实参校验、`_subst_type` 替换载荷、登记 `enums` + `decl_order`）。③ `parse_type` 统一处理泛型 struct / enum 的 `Name[args]`。④ `parse_primary` 与 `parse_pattern` 支持 `Opt[int].Variant`（先单态化再交给既有变体分支/模式路径） |
| `tests/t103_generic_enum.qma` | **新增**：Opt[T]（int/str/struct 载荷）、Either[A,B]、穷尽性 + 通配、形参/返回值、嵌套 `Opt[Opt[int]]`、`vec[Opt[int]]`、无载荷变体 |
| `tests/bad/genum_*.qma` | **新增 4 个负向**：`genum_noarg`（裸写）/ `genum_arity`（实参个数）/ `genum_tparam`（泛型函数里 `Opt[T]`）/ `genum_nonexhaustive`（不穷尽） |
| `tests/run_win_tests.py` | 注册正向 + 4 条负向 |
| `tests/parsediff.py` | `t103_generic_enum.qma` 记入 `PARSE1_PENDING` |
| `docs/02-language.md` | §4.3 新增"泛型 enum（v1.63）"小节 + 范围表 |
| `docs/07-gaps.md` | §1 行 🟡 → **✅ v1.63**（泛型三件套收口）；§8 顺序更新 |
| `docs/06-status.md` | 回归/对拍数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.63.0 |

## 实现要点

- **复用单态化套路**：与 v1.59 泛型 struct 完全同构——解析期合成具名类型，模板不进
  类型表；Lower / 优化器 / 三个后端零改动（枚举布局、match 降级、穷尽性检查全部照旧）。
- **构造与模式都走既有分支**：`Opt[int].Some(v: 1)` 先在 `parse_primary` 里把
  `Opt[int]` 换成 `Opt__int`，之后 `.Some(...)` 仍是老的"枚举变体构造"路径；
  模式同理，`Opt[int].Some(x)` → 路径 `["Opt__int", "Some"]`。
- **穷尽性按实例**：`Opt__int` 与 `Opt__str` 各有自己的变体表，互不影响；
  缺变体照样报"match 不穷尽"（负向夹具 `genum_nonexhaustive`）。
- **fail-fast 边界**：泛型函数/impl 模板里 `Opt[T]` 直接编译期报错（与 `Box[T]` 同一条规则），
  不静默造出 `Opt__T` 假枚举。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=193 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证，沙箱拦） |
| `python tests/lexdiff.py` | PASS=176 FAIL=0（179 个源文件） |
| `python tests/parsediff.py` | PASS=131 FAIL=0（跳过 8 个：interface/泛型/约束/泛型 impl/泛型 enum） |
| `python tests/irdiff.py` | PASS=74 FAIL=0 SKIP=57（t103 在 A64 上直接通过：枚举 match 已支持） |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| 四道门禁 | check_names / check_origin / check_docs / gen_stdlib_doc --check 全 PASS |

## 已知边界 / 遗留

- 泛型 `impl` 泛型 enum（`impl Opt[T] : Iface`）未做——泛型 impl 目前只接受泛型 struct
  （enum 的方法需要先有"枚举的方法"这个概念，语言里还没有）。
- 泛型函数里不能用 `Opt[T]` 作类型（与 `Box[T]` 同一条 fail-fast）。
- 类型实参仍只接受具名类型（`Opt[vec[int]]` 不做）。
- match 不穷尽的报错用单态化名（`Opt__int`），不是源码写法 `Opt[int]`——文案待统一。
