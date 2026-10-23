# v1.77 — 属性宏 `@derive` + 编译期反射：序列化不再手抄字段表

- 日期：2026-10-23
- 任务：`07-gaps.md` §1「宏 / 反射」❌ → 🟡。原文的前置是"编译期 AST API、
  类型元数据段"，后果是"序列化只能手写字段表"——本版把**后果**消掉：
  `@derive(Json, Eq, Show)` 按字段表生成代码，`refl_*[T](i)` 提供编译期类型元数据。
- 影响面：语言（`tools/stage0/qlm.py` 解析期宏展开 + 反射折叠）、
  标准库（`std/json.qma` 一处 `pub`）、测试（1 正向 + 1 跨模块 + 10 负向）、
  基准（`bench/derive_bench.qma`）、文档

## 为什么是它

`std/json.qma` 的文件头从 v1.17 起就写着"语言目前没有用户泛型、没有反射，
写不出 `to_json<T>`，所以这里给的是显式树 API"。用户泛型 v1.36–v1.63 补齐了，
但"结构体 → JSON"这一步仍然要手抄一遍字段名：

```quelmara
// v1.76 之前：每个 struct 一段胶水，字段改名就静默错位
fn point_to_json(p: Point) -> str {
    let h = json_new(64)
    json_begin_obj(h)
    json_key_int(h, "x", p.x)
    json_key_int(h, "y", p.y)
    json_end_obj(h)
    return json_done(h)
}
```

同一份字段表还要再抄两遍（解码、等价比较），三处任何一处漂移都是静默错。
这一版让编译器从**声明本身**生成这三份代码。

## 设计：为什么是"编译期"，不是"元数据段"

原缺口写的前置是"类型元数据段"，但那意味着运行时多一段数据 + 一套动态访问路径
（字段按名字查表、类型标签、动态派发）。本版走另一条路：

| 方案 | 运行时成本 | 本版选择 |
|---|---|---|
| 类型元数据段 + 运行时反射 | 每个类型一段元数据 + 查表 | ✗ |
| 编译期宏展开 + 常量折叠 | 0 字节元数据 | ✓ |

`@derive` 的产物就是**用户本来会手写的那几个普通函数**（`Point__json` /
`Point_from_json` / `Point__eq` / `Point__show`），走同一套解析 / 推断 / 降级路径。
`refl_*[T](i)` 直接折叠成字面量，运行时不存在"类型"这个概念。

### 实现要点

1. **注解在词法后、语法前摘除**（`_scan_derives`）：`@derive(...)` 从记号流里
   摘掉并登记 `类型名 → 派生项`。`parse_program` 完全不知道宏存在，它看到的
   是普通 struct 声明——宏不改变语法。
2. **展开方式是"生成源码再解析"**（`_expand_derive`）：子解析器共享本文件的
   struct/enum 符号表，生成的代码走与手写完全相同的路径。宏不可能造出后端
   没见过的 AST 形状（这是"宏 = 代码生成"最省事的正确性来源）。
3. **字段表是唯一事实来源**：`_derive_field_kind` 一处判定字段类型，编码 /
   解码 / 等价 / 展示四条路径共用；不支持的类型在那里 fail-fast，不会静默跳过
   某个字段（少一个 JSON 键比编译不过危险得多）。
4. **解码先零值后赋值**：`let mut out = T { 零值 }` 再逐字段赋值，而不是在
   结构体字面量里直接调函数——后者会撞 §7.9 的 Lower 缺陷。
5. **pub 继承**：`pub struct` 上的派生函数也是 pub，否则库导出的类型在调用方
   一用 `json()` 就撞"非 pub 跨模块引用"。
6. **反射折叠在 `parse_program` 末尾**：反射可以写在使用点之前（类型在文件后面
   声明），因为折叠发生在整个文件解析完之后。

## 新增 API

| 形态 | 生成的函数 | 说明 |
|---|---|---|
| `@derive(Json)` | `T__json(self)` / `T__json_into(self, h)` / `T_from_json(s)` / `T__from_node(d, n)` | 走 `std/json` 的 builder/DOM，自动补 `import std.json` |
| `@derive(Eq)` | `T__eq(self, o) -> bool` | 逐字段按值比较（str 按内容、嵌套递归、vec 逐元素） |
| `@derive(Show)` | `T__show(self) -> str` | 人读文本，bool 输出 `true`/`false` |
| `refl_*[T](...)` | 编译期常量 | 见 `docs/02-language.md` §4.8.2 |

支持字段类型：int 族 / bool / str / 本文件 struct（自身也派生）/ `vec[这些]`。
`f64`、enum 字段、`map`、定长数组一律编译期拒绝并说明原因。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | 新增 §2e 常量与 `_scan_derives` / `_expand_derive` / `_gen_json` / `_gen_eq` / `_gen_show` / `_type_text` / `_zero_lit` / `_derive_field_kind` / `_refl_value` / `_refl_resolve`；`parse_primary` 认 `refl_*[T](...)`；`parse_program` 三处挂载（struct 声明后展开、enum fail-fast、末尾折叠反射） |
| `std/json.qma` | `json_val_int` 由内部改为 `pub`（派生层写数组元素需要它） |
| `tests/t115_derive.qma` | 新增：39 条断言（编码 / 往返 / 嵌套 / 容器 / 窄整数 / 反射 / 前向引用 / 原生 `==` 仍是地址比较） |
| `fixtures/derivepub/` | 新增：跨模块派生正例（pub struct + `import`，验证 pub 继承） |
| `tests/bad/derive_*.qma`（7 个） | 新增：未知派生项 / enum 上派生 / 泛型 struct 上派生 / f64 字段 / 注解后不是声明 / enum 字段 / 未派生项不生成 |
| `tests/bad/refl_*.qma`（3 个） | 新增：下标越界 / 对 enum 做字段反射 / 下标不是常量 |
| `tests/run_win_tests.py` | 注册 t115、derivepub 与 10 条负向 |
| `tests/parsediff.py` | `t115_derive` / `dpub_*` 进 `PARSE1_PENDING`（stage-1 不认 `@derive`） |
| `bench/derive_bench.qma` | 新增：派生 vs 手写字段表（编码 / 解码各两路，断言结果逐字节一致） |
| `docs/02-language.md` | 新增 §4.8（含 §4.8.1 派生、§4.8.2 反射、支持面表、边界）；§4.7 注解表补 `@derive` |
| `docs/07-gaps.md` | §1 该行 ❌ → 🟡；**新增 §7.10**（`to_float(str)` 返回垃圾值）；§8 P2 第 1 条改写 |
| `docs/03-stdlib.md` | 重新生成（模块数 / 公开函数数随之更新） |
| `docs/06-status.md` | 回归与对拍数字、性能 §3.4e |
| `tools/stage0/qlm_cli.py` | VERSION → 1.77.0（并行轨随后推进到 1.78.0，`check_docs` 的版本同源检查以最新目录为准） |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=219 FAIL=0 SKIP=1（SKIP 为 WSL 交叉验证） |
| `python tests/lexdiff.py` | PASS=201 FAIL=0（204 源文件，SKIP 3 个含插值） |
| `python tests/parsediff.py` | PASS=142 FAIL=0（跳过 12 个泛型/接口/派生文件） |
| `python tests/irdiff.py` | PASS=78 FAIL=0 SKIP=66（91 s） |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| `python tests/bodydiff.py` | 一致 1719 / 分叉 1608 / SKIP 同步 26 / SKIP 不同步 44（诊断项，非门禁） |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（57 模块 / 379 公开函数） |
| 四道门禁（check_docs / check_names / check_origin） | 全 PASS |

性能（`bench/derive_bench.qma`，4 字段 struct，20000 次 × min of 3，三次运行取中位）：

| 路 | ns/次 | 相对手写 |
|---|---|---|
| `enc_derived`（`r.json()`） | 890 | +0.3% |
| `enc_hand`（手写字段表） | 887 | 基线 |
| `dec_derived`（`Row_from_json`） | 2171 | −0.6% |
| `dec_hand`（手写解码） | 2184 | 基线 |

编译期（8 字段 struct，只派生 Json，编译 3 次取最小）：派生 447 ms / 29184 B，
手写 448 ms / 28672 B——**编译时间在噪声内**，体积差 +512 B 是解码函数
（`T_from_json` + `T__from_node`）本身，不是元数据。

结论：派生层零运行时开销——它生成的正是手写那段代码，产物逐字节一致
（基准里的断言钉住了这一条）。ns 差异方向不稳定，属本机 VBS 噪声。

## 已知边界 / 遗留

- **enum 不支持派生**（`@derive` 在 enum 上 fail-fast）。原因：变体载荷的
  match 生成还没做，且 enum 的 JSON 表示需要定约定（`{"$v":"Circle","r":3}`？）。
- **`f64` 字段不支持**——撞到 §7.10 的新缺陷：`to_float("2.25")` 返回
  `1.407002e+14`（把指针当位模式转）。修掉它之前，JSON 里的浮点只能取原文本。
- **没有通用 token 宏**：`macro name(...) { ... }` 这种任意语法扩展还没有，
  本版是"属性宏 + 固定派生项"。
- **没有运行时反射**：`refl_*` 的下标必须是编译期常量，写不出"遍历字段"的循环
  （`tests/bad/refl_dynidx.qma` 明确拦下）。这是刻意的——运行时元数据段没做。
- 跨模块**结构体字面量**仍不可用（既有边界，与派生无关）：调用方只能通过
  pub 函数拿到值，本版夹具即按这个方式写。
