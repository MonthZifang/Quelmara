# v1.96 — 宏 / 反射收口：enum 派生 + 通用 token 宏 + 运行时反射（语言层黄标 → 绿）

- 日期：2026-10-24
- 任务：`07-gaps.md` §1「宏 / 反射」🟡 → ✅。v1.77 只落地了"struct 的属性宏 +
  编译期常量反射"，剩余四项（enum 派生、`f64` 字段、通用 token 宏、运行时反射）
  这一版一次补齐——**只动语言层**（编译器解析期 + 两个标准库模块）。
- 影响面：语言层（`tools/stage0/qlm.py` 解析期宏展开、`qlm_native.py` 与 C 后端的
  `to_float(str)` 拒绝）、标准库（新增 `std/f64`、`std/json` 两处 pub）、
  测试（3 正 + 6 负）、基准、文档

## 为什么这四项必须一起做

它们不是四个独立特性，而是同一条链上的四段：

| 缺口 | 不做的后果 |
|---|---|
| enum 派生 | 领域模型一半是 enum（`Opt`/`Either`/协议消息），一半能序列化一半要手抄 |
| `f64` 字段 | JSON 里的浮点只能取原文本，`@derive(Json)` 对数值类型是残的 |
| 通用 token 宏 | `@derive` 只能覆盖编译器**认识**的模式，用户没法表达自己的模式 |
| 运行时反射 | 只能写 `refl_field_name[T](0/1/2)`，写不出"遍历字段"的循环 |

## 设计

### 1. enum 的 JSON 约定（唯一事实来源）

```
{"$v":"Dot"}                    // 无载荷变体
{"$v":"Circle","r":5}           // 单载荷
{"$v":"Rect","w":3,"h":4}       // 多载荷
```

- `$v` 永远第一个键，载荷按**声明顺序**跟在后面（可作对拍依据）。
- 解码只认 `$v` 字面量；未知变体 `assert` 失败——不猜、不给默认值。
- 不用"裸字符串 / 裸数字"：同一 enum 的变体载荷形状不同，带 `$v` 的对象让
  "类型 → 表示"始终是满射，跨语言消费方不用猜。
- `Eq` = 同变体且载荷逐字段相等（跨变体永远不等，不是比内存前缀）。
- `Show` = `Dot` / `Circle(5)` / `Rect(3, 4)`。

### 2. `f64` 字段：先止血，再补解析器

`07-gaps.md` §7.10 的老账：`to_float("2.25")` 把字符串**指针**当数值转，静默给出
`1.407002e+14`。两步都做了：

1. **止血**：`to_float(str)` / `to_f32(str)` 在编译期直接拒绝（自研后端
   `qlm_native.py` + C 后端 `qlm.py` 各一处），报错指向替代方案。
2. **补解析器**：新增 `std/f64`：
   - `f64_parse(s)`：十进制解析（符号 / 小数点 / 指数 / 两端空白；`inf`/`nan`/
     十六进制一律拒绝）。≤15 位有效数字且 |指数| ≤ 22 走 Clinger 快路径
     （尾数 ≤ 2^53 精确、10^k 精确、单次乘除 = 单次舍入）→ **正确舍入**；
     其余按两步乘除，可能差 1–2 ULP（grisu/ryu 仍是 §2 的遗留）。
   - `f64_repr(x)`：**最短往返**文本。精确十进制展开（尾数 × 2^e；e<0 时乘 5^k
     把二进制小数变成十进制整数，base 1e9 大数），再按 15/16/17 位有效数字
     逐级回读验证，第一个能回读相等的就是最短表示。
     为什么不用内建 `to_str`：它只有 7 位有效数字（`3.141593`），写进 JSON 就是
     静默丢精度。

`@derive(Json)` 的 `f64` 字段走 `f64_repr` / `f64_parse`，自动补 `import std.f64`。

### 3. 通用 token 宏：`macro 名字(形参) { 记号 }`

与 `@derive` 的分工：`@derive` 是**结构化**的（编译器知道字段表），宏是**纯记号
替换**（编译器不理解宏体语义，只搬运记号）。两者都在语法分析之前跑：

```
_scan_macros（摘定义 → 递归展开，上限 64 层）
  → _scan_derives（@derive 注解，可能由宏生成）
    → parse_program（看到的全是普通记号）
```

- 只在顶层定义；实参按**顶层逗号**切分；个数必须与形参一致。
- 调用点必须是 `名字(`，且前一个记号不是 `.`（方法调用不展开）。
- 前向引用可用（先摘定义再展开）。
- **无卫生性**：形参按记号替换，不加括号、不改名；宏体里的自由名字与调用点同作用域。
- 没有记号拼接（`##`）；需要按名字生成声明时把名字当形参。
- 自递归在编译期拦下（层数上限），不静默无限展开。

### 4. 运行时反射：表是代码，不是数据

`refl_*[T](i)` 的 `i` 不再是常量限定：

- **常量下标**（字面量 / `const`）→ 折叠成字面量，零运行时成本（v1.77 路径不变）。
- **运行时下标** → 改写成按需生成的查表函数：
  `fn __refl_field_name_Point(i: int) -> str { if i == 0 { return "x" } ... }`。
  仍然是**零元数据段**：表是指令，不是数据；O(n) 分支、常量内存、无动态派发。
  同一个 `(函数, 类型)` 只生成一次；越界在运行时 `assert` 失败。

## 顺带修掉的两个静默错

| 缺陷 | 症状 | 修法 |
|---|---|---|
| 按值自包含的聚合 | `struct S { s: S }` / `enum E { Node(inner: E) }` 让尺寸计算无限递归（`RecursionError`，指不到源码行） | 声明处 fail-fast：`不能按值包含自身`，提示用 `vec[T]` / `map` 间接引用 |
| 枚举载荷绑定与生成代码局部变量撞名 | 载荷字段名叫 `h` / `d` / `n` 时，生成的 `json_key(h, ...)` 把 **int 当句柄**传，整段输出静默消失（`Rect(w:3, h:4)` 实测无任何输出、退出码 0） | 生成的 match 一律用位置绑定 `_v0/_v1`（`_o0/_o1`），不再直接用字段名 |

第二条是这次写 enum 派生时踩出来的**真 bug**：与 §7.8 同族（静默丢代码），
只是触发条件是"载荷字段名与生成代码局部变量同名"。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | 新增 `_scan_macros` / `_macro_define` / `_macro_args`（token 宏）；`_gen_json_enum` / `_gen_eq_enum` / `_gen_show_enum` 与共享的 `_json_emit_field` / `_json_emit_value` / `_json_read_expr` / `_eq_check`（struct 也改走同一套）；`_derive_field_kind` 增 `f64` / `enum`；`_check_derive_nested`（嵌套类型必须派生同一项）；`_refl_dynamic` / `_refl_helper_src`（运行时下标）；`_zero_lit` 增 enum；struct / enum 自包含检查；泛型 enum 上 `@derive` 拒绝 |
| `tools/stage0/qlm_native.py` | `to_float(str)` / `to_f32(str)` 编译期拒绝 |
| `std/f64.qma` | 新增：`f64_parse` / `f64_repr` / `f64_finite`（+ 精确十进制展开、base 1e9 大数、最短往返验证） |
| `std/json.qma` | `json_val_raw` 转 pub；新增 `json_key_raw` |
| `tests/t123_derive_enum.qma` | 新增：enum 派生（Json/Eq/Show）、`{"$v":...}` 约定、f64 字段、vec[enum]、跨 enum 嵌套、往返、精度 |
| `tests/t124_macro.qma` | 新增：语句宏 / 表达式宏 / 宏调宏 / 生成声明 / 生成 `@derive` / 零形参 / 前向引用 |
| `tests/t125_refl_dyn.qma` | 新增：常量折叠 + 运行时下标遍历字段与变体 |
| `tests/bad/derive_genenum.qma`、`derive_f32.qma`、`derive_field_enum.qma`、`refl_stridx.qma`、`macro_arity.qma`、`macro_recursive.qma`、`macro_dup.qma`、`struct_self.qma`、`enum_self.qma` | 新增/改写负向（`derive_enum.qma`、`derive_f64.qma`、`refl_dynidx.qma` 已随能力翻转删除） |
| `tests/run_win_tests.py` | 注册 3 个正向 + 9 个负向（负向清单随之改写） |
| `tests/parsediff.py` | 三个新文件进 `PARSE1_PENDING`（bootstrap parser 还没移植 enum 派生 / token 宏 / 运行时反射） |
| `bench/derive_bench.qma` | 增 enum 编解码两路（派生 vs 手写 match）+ `f64_repr` vs `to_str` + 两个 f64 字段的 struct；规模下调（512 MB 堆上限，无 GC） |
| `docs/02-language.md` | §4.8 重写为三小节（派生 / 宏 / 反射），加支持面表、enum JSON 约定、`f64` 口径 |
| `docs/07-gaps.md` | §1 该行 🟡 → ✅；§7.10 → 已修；§8 P2 第 1 条改写 |
| `docs/06-status.md` | §3.4e 换成本版实测（含 enum 与 f64 行）；回归数字 |
| `docs/03-stdlib.md` | 重新生成（58 模块 / 385 公开函数） |
| `tools/stage0/qlm_cli.py` | VERSION → 1.96.0（并行轨随后推进到 1.97 / 1.98，版本号连续） |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=266 FAIL=0 SKIP=1（隔离副本实测；SKIP 为 WSL 交叉验证，本机被沙箱拦；含本版新增 3 正向 + 9 负向） |
| `python tests/lexdiff.py` | PASS=238 FAIL=0（241 个源文件，SKIP 3 个含插值） |
| `python tests/parsediff.py` | PASS=150 FAIL=0（跳过 17 个：interface/impl/泛型 + 本版 3 个） |
| `python tests/irdiff.py` | PASS=89 FAIL=0 SKIP=68 |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| 四道门禁（check_docs / check_names / check_origin） | 全 PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（58 模块 / 385 公开函数） |

性能（`bench/derive_bench.qma`，三次运行取中位，数字见 `06-status.md` §3.4e）：

- struct 编码 1736 ns vs 手写 1725 ns（+0.6%），解码 4115 vs 4045（+1.7%）——噪声内；
- enum 编码 1214 vs 手写 1216（−0.2%），解码 3447 vs 3361（+2.6%）——噪声内；
- `f64_repr` 5531 ns vs `to_str` 282 ns（**约 20×**，精确展开 + 回读验证的代价）。

结论：派生层仍然**零运行时开销**（产物就是手写那段代码，基准里断言两路逐字节一致）；
唯一的真实成本是 `f64` 的文本化，且只在含 f64 字段的 struct / enum 上出现。

## 已知边界 / 遗留

- **泛型 struct / 泛型 enum 模板不能直接 `@derive`**（载荷类型还是类型参数）：
  先实例化，或在 `impl` 里手写。要支持得让派生在单态化之后跑，是另一版的事。
- **`f32` 字段不参与派生**：JSON 数字统一按 f64 读写；f32 只有 7 位有效数字，
  往返会丢精度，宁可编译期拒绝。
- **宏没有卫生性、没有记号拼接**：形参按记号替换（不加括号、不改名），
  `##` 不支持。这是刻意的——卫生性要引入作用域重命名机制，成本远超收益。
- **运行时反射是 O(n) 分支**，不是 O(1) 表；反射也**读不到字段的值**
  （字段类型不同，没有统一返回类型）。
- **`f64_repr` 在极端量级可能差 1 ULP**：`|x| > 1e22` 时解析器走两步乘除，
  不是正确舍入（与 §2 的 grisu/ryu 遗留同源）。常用区间（|指数| ≤ 22、≤15 位
  有效数字）逐位往返，`tests/t123_derive_enum.qma` 钉住了 `0.1` 与 π。
- **`@derive` 的编译期成本随类型数线性增长**：`t123`（7 个类型、3 条路径）单文件
  编译 6–12 s（VBS 噪声大）；派生函数本身与手写等价，但生成代码量大（每个变体一个 match 臂）。
- 跨模块**结构体字面量**仍不可用（既有边界，与派生无关）。
