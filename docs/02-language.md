# 语言参考

> 事实来源：`tools/stage0/qlm.py`（词法/语法/推断）、`tools/stage0/qlm_native.py`（语义与内建）、
> `tests/*.qma`（可运行用例）。每节末尾的"证据"给出可复核的文件或命令。

## 1. 源文件与模块

```quelmara
module hello "1.2.0"   // 模块名 + 可选版本（只用于 import 的版本校验）
import std.core        // 扁平合并：递归加载 std/ 与同目录 .qma
import util ">=1.2"    // 可选版本要求（同 major 且 >= 要求）
```

- 源码扩展名固定 `.qma`；`.ros` 已废弃，遇到会给出 `git mv` 迁移提示  <!-- legacy-ok -->
  （`tools/stage0/qlm.py:50` `require_source`）。
- `import` 是**扁平合并**：顶层 `fn` / `struct` / `enum` / `test` 直接并入主 AST，
  消费时直呼其名。
- **`pub` 可见性（v1.43）**：顶层 `pub fn` / `pub struct` / `pub enum` 跨模块可见；
  非 pub 声明只在本模块内可用，跨模块引用**编译期报错**（一次报出全部违规，
  并指明定义文件）。`pub` 是上下文关键字——只在顶层声明位识别，函数内
  `pub` 变量名不受影响。`const` 本就解析期内联全局共享，无需 pub。
- **限定语法（v1.44 / 链接期解析 v1.99）**：`lib.fn(...)` 限定调用、
  `lib.Color.Red(v)` 限定枚举构造（只收位置实参）、模式 `lib.Color.Red =>`——
  头段必须匹配本文件 `import`（拼错模块名/漏 import 编译期报错），且目标必须
  `pub` 并定义在该 import 解析到的文件里。**限定 struct 字面量不做**
  （用 pub 工厂函数）。
  v1.99 起限定信息**保留到链接期**：解析期把"哪个模块"编进节点，链接期再
  落到最终符号——这是下面 per-module mangling 的前提（旧做法"剥掉模块段 +
  记一个集合"无法区分同一个文件里的 `helper()` 与 `lib.helper()`）。
- **跨模块同名声明（v1.99）**：per-module mangling，**只在真的重名时才动名字**：

  | 情形 | 结果 |
  |---|---|
  | 名字只在一个文件里声明 | 一个字节都不改（既有程序逐字节不变） |
  | 主文件与 import 重名 | 主文件保留原名；导入方变 `<模块>__<名字>` |
  | 两个 import 之间重名 | 两边都加前缀；未限定引用 = **歧义报错**（提示 `lib.name`） |
  | 同名 struct / enum | 方法、派生函数跟着换前缀（`T__m` → `<模块>__T__m`） |
  | 同名非 pub 私有函数 | 各归各的模块（前缀保证不撞） |

  前缀取 import 串：`import std.json` → `std__json`。未限定引用的解析顺序是
  **本文件声明 > 唯一外部声明 > 歧义报错**。
- **模块版本（v1.99）**：`module util "1.2.3"` 声明，`import util ">=1.2"` 要求。
  检查口径：**同 major 且实际 >= 要求**；不满足、或模块没声明版本，都编译期
  报错（报错带实际版本与文件名）。版本号写法 `"1"` / `"1.2"` / `"1.2.3"`，
  可带 `>=` / `^` / `=` 前缀（三者同义）。**不做 semver 求解**——依赖选择与
  锁是 qpm 的事（`05-toolchain.md`）。
- 查找顺序：主文件目录 → `std/` → `[src].lib` → `[src].ref` → `.qpm/deps`，
  **惰性解析**（import 什么加载什么）。布局规则见 [`05-toolchain.md`](05-toolchain.md)。
- 仍然报错的情形：循环 import、被导入文件定义 `main`、未限定引用歧义、
  限定引用指向不存在的名字或非 pub 声明、版本不兼容。
- 顶层 `const` 两遍解析，可跨模块可见；同名 const 取值不同仍报错
  （const 在解析期内联，不参与 mangling）。同名 `interface` 视为**同一份契约**：
  签名一致即幂等，不一致报错。

## 2. 词法

### 2.1 关键字（32 个，`qlm.py:125`）

```
fn  let  mut  if  else  while  for  parfor  return  break  continue  defer
struct  enum  match  interface  impl  rc
module  import  test  const  vec  map  chan  option  result  select
arena  spawn  true  false
```

> `int` / `str` / `f64` 等类型名不是关键字，是普通标识符（可被同名变量遮蔽，见 §9 陷阱）。

### 2.2 运算符

| 类别 | 符号 |
|---|---|
| 算术 | `+ - * / %` |
| 比较 | `== != < <= > >=` |
| 逻辑 | `&& \|\| !` |
| 位运算 | `& \| ^ ~ << >> >>>` |
| 赋值 | `= += -= *= /= %= &= \|= ^= <<= >>= >>>=` |
| 其它 | `..`（区间）、`?`（错误传播）、`->`、`=>`、`@`（注解）、`.`、`::`（无，用 `.`） |

`>>` 是**算术右移**（灌符号位），无符号右移用 `>>>`。

### 2.3 字面量

```quelmara
42  0xFF  0b1010  0o755      // 整型（十进制/十六/二/八）
1_000_000                    // 下划线分隔
3.14  1.0e-3                 // f64
"text"  "中文"  "\xNN"       // 字符串；\xNN ≥0x80 是原始字节，不是码点
true  false
```

字符串是**长度前缀 ABI**：值指向 `[len:8][bytes][NUL]`，`len(s)` / `s[i]` 为 O(1)。

**插值字符串（v1.61）**：前缀 `f`，`{expr}` 段在运行时求值并转成文本：

```quelmara
let n = 42
let s = "hi"
f"n={n}, s={s}"        // "n=42, s=hi"
f"{{}}"                // "{}"（{{ / }} 是转义）
f"{n * 2}"             // 段内可以是任意表达式
f"p=({p.x},{p.y})"     // 字段访问也可以
```

| 项 | 语义 |
|---|---|
| 支持类型 | `int` / `bool` / `f64` / `str`（结构体值拒绝：先转成 str） |
| 分配 | **整条结果一次分配**；整数直接 `__fmt_u64` 写进缓冲，不生成临时 str |
| 与手写拼接 | 语义等价（`f"n={n}" == "n=" + n.to_str()`），300k 次实测比手写链快约 10% |
| 普通字符串 | 不带 `f` 前缀的字符串里 `{` `}` 仍是字面量（JSON 不受影响） |
| C 后端 | 不支持（fail-fast，只进原生后端） |

证据：`tests/t100_interp.qma`（21 条断言）、`bench/interp_bench.qma`、
`tests/bad/interp_*.qma`（必须编译失败）。

### 2.4 注释与 doc comment（v1.92）

```quelmara
// 行注释（编译期丢弃）
/// 声明文档：紧贴其下的顶层声明
//! 模块文档：只认文件头
//// 四个及以上斜杠 = 普通注释
```

只有行注释，没有块注释（`/* */` 不支持）。

| 写法 | 位置 | 作用 |
|---|---|---|
| `///` | 紧贴顶层 `fn` / `struct` / `enum` / `interface` 的上一行 | 该声明的文档 |
| `//!` | 文件开头、任何代码之前 | 模块文档 |
| `////` | 任意 | 普通注释（不产生文档） |

细节（每条都被 `tests/doc_test.py` 锁住）：

- **一个空格被剥掉**：`/// 加法。` → `加法。`；`///` 独占一行 = 空串，在 Markdown 里当段落分隔。
- **空行即脱离**：`///` 块与声明之间夹空行、`//` 注释或任何代码，文档就挂不上；
  脱离的块被 `quelmara doc --missing` / `--check` 判为错误（防"写了文档却没人看到"）。
- **顶层 `@注解` 不算脱离**：`///` + `@derive(Json)` + `pub struct` 合法。
- **缩进的 `///` 不收**：函数体、`impl` 内部的 `///` 按普通注释处理。v1.92 只收顶层声明，
  方法/impl 的文档没有做（`07-gaps.md` §3）。
- **只有 `pub` 顶层声明进公开文档**；非 pub 声明的 `///` 仍挂到 AST 上，只是不导出。

前端怎么认：doc comment **不进记号流**——词法上它仍是注释，`lexdiff` / `parsediff` 的
对拍契约不变。解析每个文件时按行扫一遍，把文档挂到声明上：

```python
p = qlm.Parser(tokenize(src), src=src)   # 给 src= 才扫（快路径：没有 `///` 就整段跳过）
fdef["doc"]                # fn 的文档行（list[str]，未分段）
p.type_docs["Point"]       # struct / enum / interface 的文档
p.module_doc               # //! 模块文档
```

`parse_source(src, with_docs=True)` 额外返回 `(type_docs, module_doc)`；不给 `with_docs`
时返回值仍是原来的 7 元组（旧调用零改动）。

产物无关：doc comment 不进 IR，同一程序带与不带文档编译出的 PE 逐字节相同
（`tests/doc_test.py` 的"产物无关"一节）。生成文档用 `quelmara doc`，见 `05-toolchain.md` §1.2。

## 3. 类型系统

| 类型 | 写法 | 说明 |
|---|---|---|
| 整数 | `int` | 64 位有符号，默认整型 |
| 宽度整数 | `u8 u16 u32 u64 i8 i16 i32 i64` | 只在边界截断，表达式内按 C 提升（§8.1） |
| 浮点 | `f64` / `f32` | 四则、比较、`to_int`、`to_str` |
| 布尔 | `bool` | |
| 字符串 | `str` | 长度前缀，按字节索引，无 UTF-8 解码 |
| 结构体 | `struct Point { x: int, y: int }` | 值语义，赋值/传参整体拷贝 |
| 枚举 | `enum Light { Red, Yellow, Green, Flashing(rate: int) }` | 可带载荷，`match` 必须穷尽 |
| 定长数组 | `[N]T` | 值语义，可作参数/返回值 |
| 切片 | `[]T` | 零拷贝视图 `{ptr, len}`，别名共享 |
| 动态数组 | `vec[T]` | 堆上，2 倍扩容，句柄语义 |
| 映射 | `map[K]V` | 开放寻址，K∈int/bool/str，V∈int/str/具名 struct/enum（v1.41 值扩容，按值拷入拷出） |
| 通道 | `chan[T]` | 有界 MPMC |
| 可选 | `option[T]` | 合成枚举，`some` / `none` |
| 结果 | `result[T,E]` | 合成枚举，`ok` / `err`，支持 `?` |
| 引用计数 | `rc[T]` | `[refcount][payload]`，载荷仅具名 struct |
| 接口 | `interface Shape { ... }` | 接口值 = `{data, vt}` 两字 |
| 函数值 | 函数名直接作值 | `callr` 间接调用，8 参 + struct/slice 实参（v1.42；x86-64 第 7 参起走栈） |
| 闭包 | `closure`（`fn(x: int) -> int { ... }`） | 值 = `{code, env}` 两字，创建时按值捕获（v1.95，§6.5） |

嵌套容器：`vec[vec[T]]` 支持（任意深度）；`vec[map[K]V]` 支持（v1.37，
map 句柄 1 字标量拷贝语义——vec 不持有 map 的所有权）。

## 4. 声明

### 4.1 函数

```quelmara
fn add(a: int, b: int) -> int { return a + b }
fn log(msg: str) { print(msg) }        // 无返回值
```

### 4.2 结构体与字面量

```quelmara
struct Rect { w: int, h: int }

let r = Rect { w: 2, h: 3 }
print(r.w.to_str())
```

**泛型 struct（v1.59）**：解析期单态化——`Box[int]` 现场合成普通结构体
`Box__int`，布局 / 字段偏移 / 值语义 / 聚合返回 ABI 全部复用既有路径，后端零改动。

```quelmara
struct Box[T] { value: T }
struct Pair[A, B] { first: A, second: B }
struct Slot[T: Ord] { value: T }        // 类型约束（v1.61，见 §4.5.1）

let a = Box[int] { value: 42 }          // 类型实参必须显式写
let p = Pair[int, str] { first: 7, second: "x" }

fn unwrap(b: Box[int]) -> int { return b.value }   // 类型位置同样可用
```

| 项 | 范围 |
|---|---|
| 类型参数 | 一个或多个（`struct Pair[A, B]`）；同一模板的不同实例互不干扰 |
| 字段类型 | `T` 本身，或 `vec[T]` / `map[K]T` / `[]T` / `[N]T` / `chan[T]` |
| 类型实参 | 只能是具名类型（标量 / struct / enum / 另一实例如 `Box[Box[int]]`） |
| 字面量 | `Box[int] { ... }`——**不做类型推导**（字段值推不出 T） |
| 约束 | `struct Slot[T: Ord]`——**只支持能力约束**（`Ord`/`Eq`/`Num`/`Bit`），实例化时校验 |
| 拒绝 | 裸写 `Box`（缺实参）、容器实参 `Box[vec[int]]`、实参个数不符、模板字段里嵌套泛型 struct |
| 未做 | 泛型 enum |

**方法（v1.62）**：泛型 struct 的方法写在 `impl` 里，两种写法等价于同一套产物：

```quelmara
interface Show { fn show(self) -> str }

impl Box[int] : Show { fn show(b: Box[int]) -> str { ... } }   // 只给一个实例
impl Box[T]   : Show { fn show(b: Box[T])   -> str { ... } }   // 模板：每个实例各一份
```

`impl Box[T] : Iface` 在解析期按**已实例化的**每个 `Box__X` 展开成普通方法
`Box__X__show`——布局、聚合 ABI、静态派发、vtable 全部复用既有路径，方法体里的
`T` / `Box[T]` / `T { ... }` 都按实例替换。静态调用 `b.show()` 直接 `call`
（与手写函数同速），`let s: Show = b` 之后走 vtable（实测约 2× 于直接调用）。
泛型函数里**不能**把类型参数用作泛型 struct 的类型实参（`fn f[T](x: Box[T])` 编译期拒绝）。

证据：`tests/t99_generic_struct.qma`（20 条断言）、`tests/bad/gstruct_*.qma`（必须编译失败）、
`tests/bad/bound_struct_param.qma`（约束违反）。

### 4.3 枚举与 match

```quelmara
enum Light {
    Red
    Yellow
    Green
    Flashing(rate: int)
}

fn name(l: Light) -> str {
    return match l {
        Light.Red => "RED"
        Light.Flashing(rate) => "FLASH@ " + rate.to_str()
        _ => "other"
    }
}

let warn = Light.Flashing(rate: 4)     // 载荷用「名: 值」
```

`match` 可以作表达式（`return match ...`）或语句；**必须穷尽**，否则编译报错
（负向夹具 `tests/bad/nonexhaustive.qma`）。通配 `_` 只能放最后。

**泛型 enum（v1.63）**：`enum Opt[T] { Some(v: T), None }`——与泛型 struct 同款，
解析期单态化：类型位置写 `Opt[int]` 现场合成普通枚举 `Opt__int`，构造与模式都带类型实参。

```quelmara
enum Opt[T] { Some(v: T), None }
enum Either[A, B] { Left(a: A), Right(b: B) }

let a: Opt[int] = Opt[int].Some(v: 7)
let b: Opt[int] = Opt[int].None
let s = match a {
    Opt[int].Some(v) => v.to_str()
    Opt[int].None => "-"
}
let nested: Opt[Opt[int]] = Opt[Opt[int]].Some(v: Opt[int].Some(v: 1))
```

| 项 | 范围 |
|---|---|
| 变体载荷 | `T` 本身或容器（`vec[T]` 等），按实参替换 |
| 嵌套实例 | `Opt[Opt[int]]`、`Either[int, Opt[str]]` 都可用 |
| 容器元素 | `vec[Opt[int]]`（元素按实例枚举布局） |
| 穷尽性 | 按**实例**的变体表检查（`Opt__int` 与 `Opt__str` 各自穷尽） |
| 拒绝 | 裸写 `Opt`、实参个数不符、泛型函数里 `Opt[T]`（fail-fast） |
| 方法 | `impl Opt[T: Show] : Show { ... }`（v1.64，按每个实例展开成 `Opt__int__show`） |
| 拒绝 | 裸写 `Opt`、实参个数不符、泛型函数里 `Opt[T]`（fail-fast）、实参不满足 impl 模板约束 |

证据：`tests/t103_generic_enum.qma`、`tests/bad/genum_*.qma`（必须编译失败）。

### 4.4 接口与实现

```quelmara
interface Shape {
    fn area(self) -> int
    fn name(self) -> str
}

struct Circle { r: int }

impl Circle : Shape {
    fn area(c: Circle) -> int { return c.r * c.r * 3 }
    fn name(c: Circle) -> str { return "circle" }
}

let s: Shape = Circle { r: 3 }    // 隐式装箱 {data, vt}
print(s.area())                    // vt[slot] -> callr，运行期派发
```

- `impl` 的方法**第一个参数就是接收者**，类型必须与 `impl` 左侧一致。
- `impl` 左侧（v1.62）也可以是泛型 struct：`impl Box[int] : Show`（具体实例）或
  `impl Box[T] : Show`（模板，按每个已实例化实例展开）——见 §4.2。
- 编译器校验：方法齐全、参数个数、返回类型；缺方法/签名不符 → 编译失败
  （`tests/bad/iface_missing.qma` 等）。
- 隐式装箱四处：`let` 标注、函数实参、`vec[Shape].push`、`return`。
- 装箱块**带引用计数**（v1.83）：块尾 / 提前 `return` / `break`·`continue` /
  赋值替换都会释放，进容器或 struct 字段时 retain——热点循环不再涨堆。
  完整规则见 §8.4。
- 同一类型在两个接口里同名方法（v1.83）：按接口名二次 mangling 共存，
  vtable 各走各的槽位；此时**静态调用** `t.m()` 有歧义（编译报错），
  先转成接口值再调。
- 接口可以 `pub`，`impl` 也可以写在别的文件里（v1.83）；同名同签名重复声明幂等，
  签名不一致报"接口冲突"（§8.4）。
- `Drop` 是**内建接口**（不用自己声明）：`impl T : Drop { fn drop(t: T) { ... } }`
  让 T 的 `let` 绑定在作用域退出时自动析构——语义与边界见 §8.7（v1.93）。
- 同一 `(类型, 接口)` 只能有一个 `impl`（v1.93 起重复实现编译报错；此前是静默覆盖）。

### 4.5 用户泛型（单态化）

```quelmara
fn pick_first[T](a: T, b: T) -> T { return a }
fn pair[A, B](a: A, b: B) -> A { return a }        // 多类型参数（v1.36）
fn fact[T](n: T) -> T {
    if n <= 1 { return 1 }
    return n * fact[T](n - 1)      // 自递归可用（显式或推导）
}

let x = pick_first(1, 2)            // 隐式：T 由实参推导（v1.36）
let s = pick_first("a", "b")        // T = str
let p = pair(1, "x")                // A=int, B=str
let e = pick_first[int](1, 2)       // 显式实例化仍然可用
let m = pair[int, str](1, "x")      // 显式多参
```

编译期把模板深拷贝成具名实例（`fact__int`、`pair__int_str`），调用点降为普通 `call`——**零运行时分发开销**。

推导规则（v1.36）：省略类型方括号时，类型实参按形参—实参一元化推出。推导来源：
字面量（int/float/str/bool）、结构体与枚举字面量、`let` 标注、非泛型函数返回类型、
泛型实例返回类型、`vec[T]`/`map[K]V`/数组元素类型（容器形参把元素类型交给 T）、
结构体字段类型。推导是**流不敏感**的（按语句序收集变量类型、后写覆盖）；推不出
全部类型参数时编译期报错并提示显式实例化，实参互相矛盾（如 `same(1, "s")`）报冲突。

边界：类型实参只接受具名类型（标量 / struct / enum，容器类型实参不做）；无泛型方法；
模板不支持注解（@simd/@extern）；跨文件调用时若被调用方在调用方之后解析，仍需显式方括号
（解析期还不知道它是泛型）。类型约束见 §4.5.1，泛型 struct 见 §4.2。
开箱即用的泛型算法（min/max/clamp/contains/index_of/reverse）见 `std/gen`。

### 4.5.1 类型约束（trait bound，v1.61）

```quelmara
fn my_min[T: Ord](a: T, b: T) -> T { ... }
fn max3[T: Num + Ord](a: T, b: T, c: T) -> T { ... }
fn keep[A: Eq, B: Num + Ord](a: A, b: B) -> B { ... }   // 多类型参数各自带约束

interface Shape { fn area(self) -> int }
fn area_twice[T: Shape](s: T) -> int { return s.area() + s.area() }
```

约束写在类型参数后，`+` 连接多条。两类约束：

| 约束 | 授权的运算符 | 满足它的类型 |
|---|---|---|
| `Ord` | `<` `<=` `>` `>=` | 整数族 + `f64`/`f32` + `str`（v1.66 起按字节字典序） |
| `Eq` | `==` `!=` | 整数族 + `f64`/`f32` + `bool` + `str` |
| `Num` | `+` `-` `*` `/` `%` | 整数族 + `f64`/`f32` |
| `Bit` | `&` \| `^` `<<` `>>` `>>>` `~` | 整数族 |
| `Show` | `x.to_str()` | 整数族 + `f64`/`f32` + `bool` + `str` |
| 任意 interface 名 | 该接口声明的方法（单态化后静态派发） | 有 `impl T : Iface` 的类型 |

`Eq` **不含聚合**：`struct`/`enum` 的 `==` 在降级期是地址比较（`Color.Red == Color.Red`
为 `false`，见 §9 陷阱 12 与 `07-gaps.md` §7.6），所以它们不满足 `Eq`。
`str` 自 v1.66 起 `<` `<=` `>` `>=` 按**字节字典序**（`__str_cmp`，表达式与条件两条
降级路径都接了），因此 `Ord` 覆盖 `str`——`gen_min[str]`、字符串排序都能用了。

三层检查，全部编译期：

| 时机 | 检查 | 违反时 |
|---|---|---|
| 声明期 | 模板体对 `T` 用到的每个运算符，都必须被**声明的**约束覆盖——契约不能撒谎 | `[T: Eq]` 体内用 `<` → 报"约束只声明了 Eq" |
| 实例化期 | 类型实参必须满足声明的约束（能力表 / `impl` 表） | `my_min[P](...)` → 报"实参 P 不满足 Ord" |
| 实例化期 | **没写约束的模板**：体内实际用到的运算，具体类型必须支持 | `any_min[P]` → 报"体内对 P 使用了 `<`，但 P 不支持" |

第三层是安全网：没有它，struct 实参会被静默按地址比较（v1.61 之前就是这样）。
约束**零运行时成本**——单态化在解析期完成，约束在实例生成前已被擦除，
`bench/bound_bench.qma` 里带约束 / 不带约束 / 手写 int 三个版本同速（差值在噪声内）。

边界：约束只作用于类型参数，不能约束单个形参；泛型 struct 只接受能力约束（接口约束
需要 `impl` 表，而 struct 实例化发生在解析期，`impl` 可能还没解析到）；没有泛型方法，
因此也没有"方法级"约束。接口约束只校验 `impl T : Iface` **是否存在**——模板体里调用的
方法名是否属于该接口，仍由 Lower 在实例化期按具体类型解析（报"方法 X 未定义"）。

证据：`tests/t101_bounds.qma`、`tests/bad/bound_*.qma`（六种违反形态）、`bench/bound_bench.qma`。

### 4.6 常量与 `const fn`（编译期求值）

```quelmara
const KB: int = 1024
const BUF: int = 4 * KB        // 引用前面的 const
const HALF: int = BUF / 2      // C 截断除法

const fn fact(n: int) -> int {  // 编译期可求值，运行期也可调
    let mut r = 1
    let mut i = 2
    while i <= n {
        r = r * i
        i = i + 1
    }
    return r
}

const F5 = fact(5)              // 解析期解释执行 → 120
const BIG = fact(5) * 2 + 1     // 调用可嵌在算术里
const EVEN = is_even(10)        // 返回 bool 的 const fn
```

`const` 右值：整型字面量 / 一元负号 / 括号 / `+ - * / %` / const 引用 / **const fn 调用**，
按声明序求值（引用未声明即报错）。`const fn` 的支持子集：

| 项 | 范围 |
|---|---|
| 形参与返回值 | `int` / `bool`（其余编译期拒绝） |
| 语句 | `let` / 赋值（含 `+=` 等）/ `if` / `while` / `return` / 表达式 |
| 表达式 | 字面量、变量、算术、比较、逻辑、位运算、调用其他 const fn（含递归，深度 ≤ 64） |
| 求值口径 | **有符号 64 位回卷**——与同一个函数在运行时的结果逐位一致 |
| 拒绝 | `str` 值、普通函数调用、`break`/`continue`、超 200000 步（疑似死循环） |

`const fn` 同时是**普通函数**：照常发射、运行时可调，只是多了一个"能在解析期被解释执行"
的身份。证据：`tests/t98_constfn.qma`（18 条断言）、`tests/bad/constfn_*.qma`（必须编译失败）。

### 4.7 注解

| 注解 | 位置 | 作用 |
|---|---|---|
| `@simd` | 函数或 `for` 语句 | 触发 SSE2 归约（形状不匹配则静默回落标量） |
| `@no_preempt` | 函数 | 不插入让出点 |
| `@extern("C")` | 函数声明 | C 后端用；自研后端显式拒绝 |
| `@ffi("dll"[, "Sym"])` | 函数声明 | 声明外部 DLL 函数，自研 PE 后端写进导入表直接调用（v1.87，见 §4.9） |
| `@derive(...)` | `struct` / `enum` 声明前 | 按字段表生成序列化 / 等价 / 展示函数（见 §4.8.1） |

### 4.8 宏与反射：`@derive` / `macro` / `refl_*`（v1.77 起，v1.96 收口）

三件事都是**纯编译期**的：没有运行时元数据段，没有动态派发。类型信息只存在于
编译器里，产物是普通函数与常量字面量。

分工：

| 形态 | 编译器是否理解语义 | 产物 |
|---|---|---|
| `@derive(...)` | 理解（按字段表生成） | 普通函数（`T__json` / `T__eq` / `T__show` …） |
| `macro 名字(...) { 记号 }` | 不理解（只搬运记号） | 展开后的记号流，任何语法位置都能用 |
| `refl_*[T](...)` | 理解（读类型表） | 常量字面量；非常量下标 → 按需生成的查表函数 |

#### 4.8.1 属性宏 `@derive(Json, Eq, Show)`

```quelmara
@derive(Json, Eq, Show)
struct Point { x: int, y: int, label: str }

@derive(Json, Eq, Show)
enum Shape { Dot, Circle(r: int), Rect(w: int, h: int) }

fn main() {
    let p = Point { x: 1, y: -2, label: "a\"b" }
    print(p.json())          // {"x":1,"y":-2,"label":"a\"b"}
    print(p.show())          // Point { x: 1, y: -2, label: a"b }
    assert(p.eq(Point_from_json(p.json())))   // 按值相等

    print(Shape.Circle(r: 5).json())          // {"$v":"Circle","r":5}
    print(Shape.Circle(r: 5).show())          // Circle(5)
    assert(Shape.Dot.eq(Shape_from_json(Shape.Dot.json())))
}
```

派生项各自生成的函数（全是普通顶层函数，可当自由函数直接调用）：

| 派生项 | 生成的函数 | 说明 |
|---|---|---|
| `Json` | `<T>__json(self) -> str`、`<T>__json_into(self, h)`、`<T>_from_json(s) -> <T>`、`<T>__from_node(d, n)` | 编解码都走 `std/json` 的 builder / DOM；`@derive(Json)` 会自动补 `import std.json`（有 `f64` 字段时再补 `import std.f64`） |
| `Eq` | `<T>__eq(self, o) -> bool` | 逐字段比较（str 按内容、嵌套递归、vec 逐元素、enum 先比变体） |
| `Show` | `<T>__show(self) -> str` | 人读文本；bool 输出 `true`/`false` |

struct 的语义要点：

- **字段顺序 = 声明顺序**，JSON key 顺序稳定（可作对拍依据）。
- 编码复用 `std/json` 的转义与整数格式，因此 `"` `\` `\n` 与 UTF-8 的处理和手写一致。
- 解码前先 `assert(json_ok(d))`：非法 JSON **fail-fast**，不返回半成品。
- 只派生写到的项：`@derive(Json)` 不会生成 `show`/`eq`（调用即"方法未定义"）。
- 派生函数是**普通函数**，可以被其他函数、泛型模板、`impl` 直接调用；`pub struct`
  上的派生函数也继承 `pub`。

enum 的 JSON 约定（v1.96，唯一事实来源）：

| 形态 | 编码 |
|---|---|
| 无载荷变体 | `{"$v":"Dot"}` |
| 单载荷 | `{"$v":"Circle","r":5}` |
| 多载荷 | `{"$v":"Rect","w":3,"h":4}` |

- `$v` 永远**第一个**键，载荷按声明顺序跟在后面。
- 解码只认 `$v` 字面量；未知变体名 `assert` 失败（不猜、不给默认值）。
- 为什么不用"裸字符串 / 裸数字"：同一个 enum 的不同变体载荷形状不同，带 `$v`
  的对象让"类型 → 表示"始终是满射，跨语言消费方不用猜。
- `Eq` 的定义是"同变体且载荷逐字段相等"——不同变体永远不等，**不是**比内存前缀。
- `Show` 的形态是 `Dot` / `Circle(5)` / `Rect(3, 4)`。

字段类型支持面（其余一律编译期报错，不静默跳过）：

| 字段类型 | Json | Eq | Show |
|---|---|---|---|
| `int` / `i8`–`i64` / `u8`–`u64` / `byte` | ✅ | ✅ | ✅ |
| `bool` / `str` | ✅ | ✅ | ✅ |
| `f64`（`float` 同义） | ✅ 最短往返（见下） | ✅ | ✅（`to_str`，7 位） |
| 本文件声明的 struct / enum（自身也派生对应项） | ✅ 递归 | ✅ 递归 | ✅ 递归 |
| `vec[上述标量 / struct / enum]` | ✅ | ✅ 逐元素 | ✅ 逐元素 |
| `f32` / `map` / 定长数组 / `rc` / `vec[vec[...]]` | ❌ 编译期拒绝并说明原因 | — | — |

`f64` 字段的编解码（v1.96）：

- 编码走 `std/f64` 的 `f64_repr`——**精确十进制展开 + 15/16/17 位回读验证**，
  产物是最短往返文本（`0.1` 就写 `0.1`，不会写成 `0.10000000000000001`）。
  内建 `to_str` 只有 7 位有效数字，写进 JSON 就是静默丢精度，所以不走它。
- 解码走 `f64_parse`（十进制解析，非法输入 fail-fast）。
- 非有限值（`inf` / `nan`）在编码时 `assert` 失败：JSON 数字表示不了它们。
- 代价：`f64_repr` 比 `to_str` 慢两个数量级（数字见 `06-status.md` §3.4e）；
  整型 / 字符串字段不受影响。
- 极端量级（`|x| > 1e22` 或 `< 1e-22`）受解析器两步运算限制，可能差 1 ULP
  （与 §2 的 grisu/ryu 遗留同源，`06-status.md` 有口径）。

#### 4.8.2 通用 token 宏 `macro`（v1.96）

```quelmara
// 语句宏：宏体是多条语句
macro require_range(v, lo, hi) {
    assert((v) >= (lo) && (v) <= (hi), "out of range")
}

// 表达式宏：整体带括号，调用点才能继续接 `.to_str()`
macro square(x) { ((x) * (x)) }

// 生成声明（含注解：宏展开先于 @derive 扫描）
macro decl_point(name) {
    @derive(Json, Eq, Show)
    struct name { x: int, y: int }
}

decl_point(Pt)

fn main() {
    require_range(5, 1, 10)
    assert(square(7) == 49)
    let p = Pt { x: 1, y: 2 }
    assert(p.json() == "{\"x\":1,\"y\":2}")
}
```

规则与边界：

- **只在顶层定义**；宏体里的花括号必须配平，空宏体报错。
- 调用点必须是 `名字(`，且前一个记号不是 `.`（`x.macro(...)` 不展开）。
- 实参按**顶层逗号**切分（括号 / 方括号 / 花括号里的逗号不算），个数必须与形参一致。
- 展开是**递归**的（宏体里可以再调宏），上限 64 层；超过即编译期报错（抓自递归）。
- **前向引用**：宏可以用在定义之前——先摘定义，再反复展开。
- 展开在 `@derive` 扫描**之前**，所以宏可以生成 `@derive` 注解本身。
- **无卫生性**（hygiene）：形参按记号替换，**不加括号、不改名**。因此宏体里的自由
  名字与调用点同作用域，形参在宏体里出现几次就求值几次；表达式宏要自己写括号。
- 没有记号拼接（`##`）：名字不能由两段拼出来；需要按名字生成声明时，把名字当形参。
- 宏名不得与关键字同名；与函数 / 类型同名时**宏优先**（定义顺序无关）。

#### 4.8.3 反射 `refl_*[T](...)`

```quelmara
struct Point { x: int, y: int }
enum Shape { Dot, Circle(r: int), Rect(w: int, h: int) }

print(refl_type_name[Point]())        // Point
print(refl_field_count[Point]())      // 2
print(refl_field_name[Point](1))      // y
print(refl_field_type[Point](1))      // int
print(refl_variant_name[Shape](1))    // Circle
print(refl_variant_arity[Shape](2))   // 2

// v1.96：下标可以是运行时值——按需生成查表函数，于是能写"遍历字段"
let mut i = 0
while i < refl_field_count[Point]() {
    print(refl_field_name[Point](i))
    i = i + 1
}
```

| 函数 | 返回 | 适用 |
|---|---|---|
| `refl_type_name[T]()` | `str` | struct / enum |
| `refl_field_count[T]()` | `int` | struct |
| `refl_field_name[T](i)` | `str` | struct，`i` 是 int（常量或运行时） |
| `refl_field_type[T](i)` | `str`（`int` / `vec[str]` / `Point` 这类源码写法） | struct |
| `refl_variant_count[E]()` | `int` | enum |
| `refl_variant_name[E](i)` | `str` | enum |
| `refl_variant_arity[E](i)` | `int`（载荷字段数） | enum |

两种下标走两条路：

- **编译期常量**（字面量 / `const`）→ 折叠成字面量，零运行时成本。
- **运行时值** → 改写成按需生成的查表函数（`if i == 0 { return "x" }` 这样的
  if 链）。表是**代码**不是数据：O(n) 分支、常量内存、仍然没有元数据段。
  同一个 `(函数, 类型)` 只生成一次；越界在运行时 `assert` 失败。

边界（每条都有负向夹具）：

- 越界（常量下标在编译期、运行时下标在运行期）、类型不是 struct / enum、
  未知反射函数、下标写成字符串字面量，全部报错。
- 反射**不能读字段的值**：字段类型不同，没有统一的返回类型；按值遍历请用 `@derive`。
- `const` 右值暂不认 `refl_*`：const 求值器是独立的整数算术求值器，
  反射只能写在**表达式位置**（可作循环上界、可参与算术，因为它折叠成字面量）。
- 反射可以写在使用点之前（类型在文件后面声明）——折叠发生在整个文件解析完之后。
- 泛型 struct / 泛型 enum 模板不能直接 `@derive`（载荷类型还是类型参数）：
  先实例化，或在 `impl` 里手写。`f32` 字段不参与派生。
- 按值自包含的聚合（`struct S { s: S }`、`enum E { Node(inner: E) }`）在声明处
  报错——没有有限布局。

证据：`tests/t115_derive.qma`（struct 派生 39 条断言）、`tests/t123_derive_enum.qma`
（enum 派生 + f64 + vec[enum] + 往返）、`tests/t124_macro.qma`（token 宏）、
`tests/t125_refl_dyn.qma`（运行时下标）；负向 12 个（`tests/bad/derive_*` /
`refl_*` / `macro_*` / `struct_self` / `enum_self`）；
性能对照见 `bench/derive_bench.qma`（派生 vs 手写，数字见 `06-status.md` §3.4e）。

### 4.9 FFI：调用系统库（v1.87）

`@extern("C")` 是给 C 后端用的原型（交给系统链接器）；自研后端不链接任何东西，
所以另有 `@ffi`——**带 DLL 名**，编译器把它写进 PE 导入表，由加载器解析符号。
没有动态链接器参与，也不需要 CRT。

```quelmara
// 符号名 = 函数名
@ffi("kernel32.dll")
fn GetTickCount64() -> int

// 符号名与函数名不同时给第二个参数（大小写敏感，Win32 的 A/W 后缀在这里选）
@ffi("user32.dll", "MessageBoxA")
fn msg_box(hwnd: int, text: int, caption: int, flags: int) -> int

@ffi("ntdll.dll", "RtlMoveMemory")
fn rtl_move(dst: int, src: int, n: int)          // 返回 void

@ffi("ucrtbase.dll", "sqrt")
fn c_sqrt(x: f64) -> f64

fn main() {
    let t = GetTickCount64()
    let buf = mem_alloc(16)
    rtl_move(buf, cstr("hi"), 3)                 // str -> NUL 结尾的 char*
    mem_store8(buf, 2, 0)
    print(cstr_read(buf))                        // char* -> str
    print(c_sqrt(2.0))                           // 1.414214
    print(t > 0)
}
```

| 项 | 规则 |
|---|---|
| 声明形态 | 无函数体（符号在 DLL 里）；带函数体编译期报错 |
| 形参类型 | `int` / `bool` / `f64` / `f32`（`str`、struct、enum、容器、切片一律编译期拒绝） |
| 返回类型 | `int` / `bool` / `f64` / `f32` / `void` |
| 调用约定 | Win64：整数实参 `RCX RDX R8 R9`、浮点实参 `XMM0-3`（**两类独立计数**），第 5+ 个同类实参落 `[rsp+32+8k]`，32 字节 shadow space 恒留 |
| 返回值 | 整数 `RAX`、浮点 `XMM0`；`bool` 按 32 位 BOOL 零扩展 |
| 隐式转换 | 整数实参 → 浮点形参自动 `cvtsi2sd`（与 C 一致）；反向不隐式 |
| 字符串 | 用 `cstr(s)` 得到 NUL 结尾指针、`cstr_read(p)` 读回；`str` 是长度前缀 ABI，直接当 `char*` 传会越界 |
| 指针 | 一律 `int`；`mem_alloc` / `mem_ptr` / `mem_load*` / `mem_store*` 自己编组 |
| 导入表 | 每个 DLL 一组 `{ILT, IAT}`；DLL 名不带扩展名时补 `.dll` |

边界（都是"做不到"，不是"没试过"）：

- **仅 Windows PE 后端**。ELF 后端产出静态可执行文件（单 RWX `PT_LOAD`，无
  `PT_INTERP`/`PT_DYNAMIC`），外部符号无处解析——`@ffi` 在 `--target native`
  下编译期 fail-fast 并给出这条原因。
- **无变参**：`printf`/`wsprintfA` 这类可变参数函数没有 `AL`（向量寄存器个数）
  约定，调用会静默错，所以不做；需要格式化就在语言里拼串。
- **无按值结构体**：Win64 的"≤8 字节按整数、>8 字节按隐式指针"两套规则未实现，
  形参只能是标量；传结构体请自己 `mem_alloc` + 逐字段写。
- **无回调 thunk**：Quelmara 函数用的是自研 ABI（`RDI RSI RDX RCX R8 R9`），
  与 Win64 不同；把函数地址传给 `EnumWindows` 这类 API 会被以错误的寄存器读参数。
  回调需要编译器生成一层寄存器重排 thunk，未做。
- **符号必须存在**：DLL 或符号名写错不是编译错误，是**加载期**错误
  （`0xC0000135`/`0xC0000139`，进程直接起不来）。

证据：`tests/t120_ffi.qma`（int/void/bool/f64/f32、栈传参 5 参与 7 参、
三个 DLL、`cstr`/`cstr_read` 往返、自身 exe 的 `MZ` 魔数）；
`tests/bad/ffi_str_param.qma`、`ffi_struct_param.qma`、`ffi_body.qma`（负向）；
开销与吞吐见 `bench/ffi_bench.qma`（数字见 `06-status.md`）。


## 5. 语句

```quelmara
let x = 1              // 不可变绑定（重新赋值报错）
let mut y = 2          // 可变
let z: u8 = 300        // 类型标注 → 边界截断为 44
y = y + 1

if cond { ... } else if cond2 { ... } else { ... }

while i < n { i += 1 }
for i in 0..n { }          // 区间，左闭右开
for x in v { }             // vec / 切片，按值取元素
for k in m { }             // map，遍历键

match v { ... }            // 语句或表达式

arena { ... }              // 块内分配随块结束整体回卷

let h = spawn work(a, b)   // 线程任务，返回句柄
h.join()                   // 等待并取返回值

parfor i in 0..n { }       // 数据并行；归约算子目前只认 +=

let ch = chan[int].open(4)
ch.send(1)
let v = ch.recv()
ch.close()
let got = select { ch.recv() }   // 多臂就绪选择（声明序优先）

assert(cond, "消息")       // 失败 → stderr 消息 + 退出码 1
defer expr / defer x = v   // 块退出清理（LIFO，见 §8.6）
break / continue
return expr
```

`test "名字" { ... }` 是内建测试块，`qlm_cli.py test` 会收集执行；普通构建时被剔除。

## 6. 表达式

### 6.1 优先级（低 → 高）

```
||  →  &&  →  |  →  ^  →  &  →  == !=  →  < <= > >=  →  << >> >>>
→  + -  →  * / %  →  一元 ! ~ -  →  postfix(. [] ())  →  基本项
```

### 6.2 方法调用

内建方法（非用户定义）：

| 接收者 | 方法 |
|---|---|
| `vec[T]` | `push` `pop` `get` `set` `len` `clear` |
| `map[K]V` | `set` `get` `del` `has`（长度用 `len(m)`；**没有** `clear`，清空请新建） |
| `chan[T]` | `send` `recv` `close` |
| `int` / `f64` | `to_str` `to_int` |
| `option[T]` | 构造 `option[int].some(x)` / `.none()`；T 可为具名 struct/enum（v1.38）；解构走 `match Option.Some/None` |
| `result[T,E]` | 构造 `result[int,str].ok(x)` / `.err(e)`；T/E 可为具名 struct/enum（v1.38，errno+上下文可装入 Err）；解构走 `match Result.Ok/Err` |
| 任务句柄 | `join` |
| 接口值 | 接口声明的方法（运行期派发） |

**不能**把方法链在函数调用结果上：`f(x).push(y)` 不支持，先落局部变量。

### 6.3 `?` 错误传播

```quelmara
fn add_one(n: int) -> result[int, str] {
    let value = parse(n)?          // Err 则直接返回，Ok 则解出载荷
    return result[int, str].ok(value + 1)
}
```

只接受两变体、单载荷的 result；载荷可为标量或**具名 struct/enum**（v1.38，多字——
enum 布局本就是 1+最大载荷字，零新机制）。`?` 所在函数必须返回同一 result 枚举。

### 6.4 其它

- 子切片：`a[lo..hi]`（左闭右开）。`str` 切片是拷贝，数组/切片是零拷贝视图。
- 函数值：直接写函数名，经 `callr` 间接调用（v1.42：8 参、聚合/切片实参按值编组；
  无捕获）。返回值按标量处理——聚合/切片返回的函数不可间接调用；
  间接调用无签名校验，聚合实参要求目标形参是聚合类型（与标量路径同信任级）。
  **需要捕获外层变量时用闭包**（§6.5）。
- 强制转换：`to_int(x)` / `to_float(x)` / `to_f32(x)`。

### 6.5 闭包（v1.95）

```quelmara
let n = 10
let add = fn(x: int) -> int { x + n }      // 捕获 n（创建时按值快照）
assert(add(5) == 15)

fn apply(f: closure, x: int) -> int { return f(x) }
assert(apply(add, 1) == 11)

fn make_adder(k: int) -> closure {          // 闭包逃逸：环境在堆上
    return fn(x: int) -> int { x + k }
}
```

| 项 | 规则 |
|---|---|
| 值表示 | `{code, env}` 两字聚合（与接口值 `{data, vt}` 同构），类型名 `closure` |
| 捕获 | 自由变量按**值快照**拷进堆上环境；只支持 1 字值——`int`/`bool`/`f64`/`str` 与 `vec`/`map`/`chan` **句柄**（句柄语义：共享同一份存储） |
| 赋值 | 体内给捕获变量赋值 = 编译期错误（快照写入传不回去，不能静默） |
| 逃逸 | 环境在堆上：可作返回值、存 `vec[closure]`，外层帧销毁后仍可调用 |
| 返回值 | `-> T` 非 void 时**块尾表达式即返回值**；显式 `return` 等价 |
| 调用 | `f(args)` → `code = f[0]; env = f[1]; callr code, [env, args…]`，env 占第 1 个形参寄存器（因此最多 5 个普通形参走寄存器，其余走栈） |
| 签名 | **同一函数内**创建的闭包带编译期签名：返回值按 `-> T` 打标记、实参按形参类型转换、聚合返回值自动开出参槽 |
| 不捕获 | 全局函数名（`foo` 仍是裸代码地址 `int`）、顶层 `const`（解析期内联） |

边界（都 fail-fast，不静默降级）：

- 捕获聚合（struct/enum）、切片、定长数组、`rc[T]` → 编译期报错。捕获槽是 1 个字，
  多字捕获需要变长环境布局。
- **裸函数名不是闭包**：`let f: closure = foo` / `apply(foo, 1)` 编译期报错
  （裸名是代码地址 `int`，闭包是两字聚合，按聚合读会读飞）。需要就包一层
  `fn(x: int) -> int { return foo(x) }`。
- 闭包不能递归（字面量没有自己的名字）；需要递归就写顶层 `fn` 再传名。
- 跨函数传递后签名不可知（`closure` 形参、容器元素、返回值）：仍可调用，
  但返回值按标量处理（`str`/`f64` 返回值请包一层有类型的 `fn`）。
- `--target c` 不支持（C99 后端只做交叉验证）；`--target arm64` 走同一条 `callr` 路径。

实现：每个 lambda 落成一个合成顶层函数 `__lam_N`（形参表前面多一个隐式 `__env__`），
捕获引用降级成 `load __env__[i]`；**运行时零元数据**（没有 vtable、没有类型描述符）。
回归 `tests/t126_closure.qma`（11 组）、负向 `tests/bad/closure_*.qma`（2 个）。
性能见 [`06-status.md`](06-status.md) §3.4g。

## 7. 内建函数（73 个）

> 全部在 `tools/stage0/qlm_native.py` 的内建分派里；用户可用同名 `fn` 覆盖（分派处均有
> `name not in self.fns_ast` 保护）。

### 7.1 输出 / 进程 / 参数

| 函数 | 说明 |
|---|---|
| `print(x)` | 输出 + 换行，接受 int/str/f64/bool |
| `eprint(x)` | 输出到 stderr |
| `exit(code)` | 退出进程。`code` 可以是字面量也可以是**运行期值**（v2.13 修：此前 vreg 号被当立即数，`exit(变量)` 静默退 0，见 `07-gaps.md` §7.16） |
| `args()` / `arg(i)` | 命令行参数（`args()[0]` 起） |
| `cores()` | 物理核数 |
| `assert(cond, msg)` | 失败 → stderr + 退出码 1 |

### 7.2 字符串 / 内存

| 函数 | 说明 |
|---|---|
| `len(s)` | 长度（str/vec/slice/map） |
| `substr(s, lo, hi)` | 子串 |
| `chr(n)` | 单字节字符串 |
| `str_alloc(n)` | 分配 n 字节字符串（`[n][bytes][NUL]`） |
| `str_from_mem(p, n)` | 从内存拷贝构造 |
| `str_from_bytes(v)` | 从 `vec[int]` 构造 |
| `mem_ptr(p, off)` | 指针偏移（**str 指针算术必须用它**，`s + n` 会被拼接劫持） |
| `mem_copy(dst, src, n)` / `mem_zero(p, n)` / `mem_cmp(a, b, n)` | 内存操作 |
| `mem_chr(p, n, byte)` | 在 n 字节内找首个等于 byte 的字节，返回下标或 -1（v1.29，8 字节 SWAR） |
| `mem_diff(p1, p2, n)` | 两段 n 字节的**首个不同字节下标**，全等返回 n（v1.30，8 字节字比较；即公共前缀长度） |
| `cpu_aes()` | AES-NI 特征位（CPUID.1:ECX[25]，v1.31）；1 = 走硬件快路径 |
| `xmm_load(slot, addr)` / `xmm_store(addr, slot)` | 16 字节搬进/搬出 xmm 固定槽（slot 0-7 编译期常量） |
| `aesenc` / `aesenclast`(d, s) | AES 轮（AES-NI），操作数是 xmm 槽号 |
| `aesdec` / `aesdeclast`(d, s) / `aesimc`(d, s) | AES 逆轮（解密方向，库层暂未使用） |
| `aeskeygenassist(d, s, imm)` | 轮密钥辅助（库层目前用软件扩展，未使用此指令） |
| `cpu_pclmul()` | PCLMULQDQ 特征位（CPUID.1:ECX[1]，v1.33） |
| `xmm_mov` / `pand` / `por` / `pshufb`(d, s) | xmm 槽间搬运与位运算（v1.33，GHASH 用） |
| `pclmulqdq(d, s, imm8)` | 64×64 进位无乘法（GCM 的 GF(2^128) 乘法核心） |
| `psrlw/psllw/psrlq/psllq/pslldq/psrldq`(d, imm8) | 字/双字/整寄存器移位 |
| `mem_str(p, n)` | 内存转 str |
| `str_ptr(s)` | str -> **数据指针**（int，零成本，v3.07）。str 是长度前缀 ABI（`[len:8][bytes]`），变量的值本身就是数据指针；长度在 `ptr-8`。用途：喂 `tcp_send_n` 做零拷贝发送，避免 `substr` 切片的 O(n²) 复制。**指针只在 s 存活期间有效**；不破坏原 str 的类型（拷到新 vreg） |
| `cstr(s)` | str -> **NUL 结尾**的 C 字符串指针（新分配，返回 int；FFI 传 `char*` 用它，v1.87） |
| `cstr_read(p)` | C 字符串指针 -> str（扫到首个 NUL，无上界保护，v1.87） |
| `mem_load8/32/64(p)`、`mem_store8/64(p, v)` | 裸读写（8/32 是字节偏移，64 是槽索引 ×8） |
| `mem_alloc(n)` / `mem_free(p, n)` | 裸分配/释放。**`mem_free` 要两个实参**（指针 + 与 alloc 对称的字节数）；写成 `mem_free(p)` 是编译期 `SyntaxError: mem_free(ptr, n) 需要两个实参`（`qlm_native.py:2918`，v2.05 修文档） |
| `mem_xchg(p, v)` | 原子交换 |

### 7.3 并发 / 原子

| 函数 | x86-64 | AArch64 | 说明 |
|---|---|---|---|
| `atomic_add(p, v)` | `lock xadd` | `LDAXR`+`ADD`+`STLXR` 重试 | `*p += v`，**返回旧值** |
| `atomic_cas(p, old, new)` | `lock cmpxchg` | `LDAXR`+`CMP`+`STLXR` 重试 | 相等才写，**返回旧值**（不相等不写） |
| `mem_xchg(p, v)` | `xchg`（隐含 lock） | `LDAXR`+`STLXR` 重试 | 交换，返回旧值 |
| `atomic_fence()` | `mfence` | `DMB ISH` | 全内存屏障 |
| `mem_load_acq(p)` | `mov`（TSO 已含 acquire） | `LDAR` | acquire 读 |
| `mem_store_rel(p, v)` | `mov`（TSO 已含 release） | `STLR` | release 写（解锁用这个，别用 fence） |
| `spin_hint()` | `pause` | `YIELD` | 自旋提示（纳秒级、不切线程） |
| `thread_yield()` | `SwitchToThread` | `sched_yield` | 让出时间片（微秒级、会切上下文） |
| `now_cycle()` | `rdtsc` | `CNTVCT_EL0` | 单调计数器（**不保证 = 核心周期**） |
| `static_word(n)` | — | — | 静态字槽（库内部用于惰性表）。**共 32 个（0–31），手工分配、没有登记表**——见下方「静态字占用」 |
| `thread_start(fn, arg)` | `CreateThread` | `clone` + 新栈 | **显式 OS 线程**（v2.12）：`arg` 按 int 传（句柄/指针，不做类型转换），返回线程句柄。与 `spawn` 的唯一区别是**不受 `multicore=false` 降级**——给 reactor 这类「循环永不返回」的线程用；`spawn` 在单核配置下会内联执行，主线程就再也回不到 accept |

**静态字占用**（`static_word(i)` 是进程级 8 字节槽，库之间靠约定避让；撞了会静默改坏
另一个库的指针，编译器不会报错）：

| 槽 | 使用者 |
|---|---|
| 0–2 | 协议库：`std/sse`（0）、`std/ws`（0）、`std/http`（0 连接状态 / 1 解析失败码 / 2 路由中间件表） |
| 6 | `std/gzip`（CRC-32 查表指针） |
| 8 | `std/rand`（xorshift64* 状态） |
| 9 | `std/log`（首条日志的 `now_ns` 基准） |
| 11 | `std/net/core`（协议库全局自旋锁） |
| 12 | `std/aes`（sbox / inv_sbox 表指针） |
| 13 / 14 | `std/timer`（堆块指针 / 存活位块指针，v2.08） |
| 15 | `std/net/reactor`（reactor 全局状态块指针，v2.12） |

> 新增库请取**下一个空号**并在这里登记。v2.08 修掉过一个真实冲突：`std/timer` 原先也用
> 12，与 `std/aes` 撞车——同时用 HTTPS 与定时器的进程会把 sbox 指针踩成堆指针。
> 现在 timer 用 13/14。

边界（v1.86 起双后端）：

- **AArch64 上没有单指令 RMW**（无 `lock` 前缀），三个读改写内建都编成 LL/SC
  重试循环；用带 acquire/release 的 `LDAXR`/`STLXR` 变体，省掉循环外的 `DMB`。
  `cas` 的不相等路径会 `CLREX` 放弃独占监视器。
- **`now_cycle` 不是周期数**：A64 读的是虚拟计数器 `CNTVCT_EL0`（频率通常
  24 MHz，与核心频率无关）。跨架构比较只能用"同一次运行内读两次取差"。
- **`mem_store_rel` 是解锁的正确形态**：`atomic_fence()` 在 x86 是 `mfence`
  （一次全屏障），而 x86 的普通写本来就满足 release，所以用 `mov` 就够；
  只有 AArch64 需要真的发 `STLR`。
- **AArch64 无线程**（`spawn`/`parfor` 未接），所以上面这些原语在 A64 上
  只能单线程用；库层（`std/sync`）照样编译并给出正确结果（`tests/t122_syncport.qma`）。

证据：`tests/t97_a64atomic.qma`（两个后端同一份语义用例）、
`tests/t122_syncport.qma`（`std/sync` 在 A64 模拟器上执行）、
`tests/t121_syncmpmc.qma`（x86 2 生产者 / 2 消费者压测）。

### 7.4 时间 / 文件 / 资源

| 函数 | 说明 |
|---|---|
| `now_ns()` | 单调纳秒（墙钟时间，含等待） |
| `cpu_ns()` | **进程累计 CPU 时间**纳秒（内核+用户态）；与 `now_ns` 的比值就是"这段时间有多少在真跑" |
| `wall_ms()` | 墙钟 Unix epoch 毫秒 |
| `sleep_ms(n)` | 睡眠 |
| `read_text(path)` / `write_text(path, s)` | 文本读写 |
| `file_exists(path)` / `file_size(path)` | 文件查询 |
| `fs_mkdir(path)` / `fs_remove(path)` | 目录/文件操作（mkdir 幂等） |
| `read_asset(name)` | 读 `[src].asset` 根下的资源（编译期嵌入） |

### 7.5 网络

| 函数 | 说明 |
|---|---|
| `tcp_listen(port)` / `tcp_listen6(port)` / `tcp_accept(fd)` / `tcp_send(fd, s)` / `tcp_recv(fd)` / `tcp_recv_n` / `tcp_send_n` / `tcp_close(fd)` | 阻塞 TCP。`tcp_listen` 绑 `0.0.0.0`（只接 IPv4）；`tcp_listen6` 绑 `::` 且 `IPV6_V6ONLY=0`——同一个 socket 同时接 IPv6 与 IPv4 映射连接（v2.07，仅 Windows PE） |
| `tcp_connect(host, port)` | 客户端连接：域名 / IPv4 / IPv6 字面量都行（`AF_UNSPEC` + `ai_next` 回退，Windows PE；Linux 编译期报错） |
| `tcp_peer_raw(fd)` | 对端地址的 20 字节视图（端口网络序 / family / 地址），文本化交给 `std/net/addr`（v2.07） |
| `udp_open()` / `udp_bind(fd, port)` / `udp_sendto(fd, ip, port, s)` / `udp_recvfrom(fd)` | UDP 四件 |
| `tcp_recv_to(fd, cap, ms)` | 带**接收超时**的单次 TCP 接收（v3.08）：`ms` 毫秒内没收到返回**空串**，不 fail-fast。`ms <= 0` 是非阻塞探测。Linux 走 `setsockopt(SO_RCVTIMEO)` + `recv`，Windows 走 `setsockopt(SO_RCVTIMEO)`（DWORD 毫秒）。给 `recv_all_to` 系列用——无超时的 `recv_all` 遇半开连接会**永久阻塞** |
| `udp_recvfrom_to(fd, cap, ms)` | 带**接收超时**的单 datagram 接收（v3.04）：`ms` 毫秒内没收到返回**空串**，不 fail-fast。`ms <= 0` 是非阻塞探测。Linux 走 `setsockopt(SO_RCVTIMEO)` + `recvfrom`，Windows 走 `setsockopt(SO_RCVTIMEO)`（DWORD 毫秒）。给 `std/net/dns` 用，避免 nameserver 不响应时永久挂起 |
| `net_config(key)` | **编译期常量**（v2.12）：`0` = `max_conns`、`1` = `recv_buffer`、`2` = `io_threads`（已解析：`0` → 物理核数）、`3` = `tcp_nodelay`（0/1）。`key` 必须是编译期常量 |

> `net_serve` **不再是内建**（v2.12）：reactor 已经用 Quelmara 写在
> `std/net/reactor.qma`——`import std.net.reactor` 之后调 `net_serve(...)` 或
> `serve(...)`（回调仍是裸函数名，IR 层是代码地址）。不 import 直接调会在
> 编译期得到迁移诊断，`tests/bad/net_serve_builtin.qma` 钉住这条。

### 7.6 引用计数 / 指令级

| 函数 | 说明 |
|---|---|
| `rc_new(v)` / `rc_get(h)` / `rc_clone(h)` / `rc_drop(h)` / `rc_count(h)` | `rc[T]` 操作 |
| `cpu_sha()` | CPUID 检测 SHA-NI |
| `xmm_load(slot, addr)` / `xmm_store(slot, addr)` | XMM 槽读写（SHA-NI 基础设施） |
| `slice_of(arr, lo, hi)` | 数组转切片 |

## 8. 特性语义（精确边界）

### 8.1 整数宽度：只在边界截断

| 边界 | 行为 |
|---|---|
| `let x: u8 = expr` | `& 0xFF`（零扩展） |
| `x = expr`（x 为窄变量） | 同上 |
| 形参 `fn f(x: u8)` | **入口**截断（传 300 → 44） |
| 返回值 `-> i8` | **出口**截断（`127+1` → `-128`） |
| struct 窄字段（字面量 / `p.f =` / `p.f +=`） | **存槽**截断（v1.40） |
| enum 窄载荷（变体构造） | **存槽**截断（v1.40） |
| `vec[u8]` 元素（`push` / `set`） | **存槽**截断（v1.40） |
| `[N]u8` 定长数组（字面量 / `a[i] =` / `a[i] +=` / 整体赋值拷入 / 形参拷贝） | **存槽**截断（v1.40） |
| 切片别名写入（`slice_of(a)` 后 `s[i] =` / `s[i] +=`，含子切片与 `[]T` 形参） | **存槽**截断（v1.56，按元素声明宽度） |
| 表达式内部 | **不截断**，按 C 提升（`u8 200 + 100 == 300`） |

边界（如实登记）：`vec[u8]` 元素**仍是 8 字节槽**（语义已对，内存打包见 `07-gaps.md` §5）。

证据：`tests/t49_width.qma`（14 条断言）、`tests/t85_narrowstore.qma`（20 条断言，v1.40）、
`tests/t94_slice_narrow.qma`（16 条断言，v1.56 切片别名写入）。

### 8.2 `@simd`：四种形状，不是向量化器

| 形状 | 指令 | 要求 |
|---|---|---|
| `acc += a[i]`，`acc: int`，`a: [N]int` | SSE2 `paddq` 两路 | 循环体只有这一条语句 |
| `acc += a[i]`，`acc: f64`，`a: [N]f64` | SSE2 `addpd` 两路 | 同上 |
| `acc += a[i] * b[i]`，`acc: f64`，`a/b: [N]f64` | SSE2 `mulpd` 两路（v1.60） | 同上，两数组同长 |
| `acc += a[i] * b[i]`，`acc: int`，`a/b: [N]int` | SSE2 `pshufd`×2 + `pmuludq`×3 + `paddq` 两路（v1.85） | 同上；64 位乘法由三次 32×32→64 拼出 |

- 逐元素越界检查**被跳过**，调用方保证 `lo..hi ⊆ [0, len(a)]`。
- f64 归约**改变求和顺序**，结果可能与标量版不逐位相等（2 的幂可逐位验证）。
- 形状不匹配：函数级注解静默回落标量；语句级注解直接编译报错。
- 点积要求两数组同长，且与累加器**同类型**（全 int 或全 f64）。混写在语句级注解下编译报错
  （`tests/bad/simd_dot_mixed.qma`）——SIMD 段不做隐式类型转换。
- f64 点积（v1.60）：`mulpd` 两路，求和顺序同样改变（测试值精确可表示时与标量逐位相等）。
- int 点积（v1.85）：x86 没有 64 位整数 SIMD 乘法（`pmulld` 是 32×32 取低位、`pmuldq` 只算
  偶数 32 位通道且截断到 32 位输入、`vpmullq` 要 AVX-512DQ），所以按
  `a*b = a_lo*b_lo + ((a_lo*b_hi + a_hi*b_lo) << 32)` 拆成三次 `pmuludq`。
  **低 64 位与有无符号无关**，与标量 `imul` 逐位等价（含 64 位回绕），不是近似。
  高 32 位用 `pshufd` 取（`psrlq` 与 `pmuludq` 同抢 port 0，会把这段变成单口串行）。

证据：`tests/t50_simd.qma`、`tests/t59_simdf64.qma`、`tests/t96_simddot.qma`、
`tests/t117_simdintdot.qma`；`bench/dot_bench.qma`、`bench/idot_bench.qma`（加速比见 `06-status.md`）。

### 8.3 `rc[T]` 与所有权检查（v1.84）

**引用计数句柄**

```quelmara
struct Point { x: int, y: int }
let r = rc_new(Point { x: 3, y: 4 })
let c = rc_clone(r)      // count 2
let p = rc_get(r)        // 借用，不转移
rc_drop(c)               // count 1
```

内存布局 `[refcount:8][payload]`；载荷仅具名 struct。

**检查范围（全部编译期，运行时零成本）**

纯 AST 遍历，不碰 IR：检查开与关的产物 PE 逐字节相同，占端到端编译 0.45–0.60%
（证据见 `06-status.md` §3.9）。
| # | 检查 | 结果 | 拦下的形态 |
|---|---|---|---|
| 1 | rc 线性 | **错误** | use-after-drop / double-drop / move-then-use |
| 1′ | rc 泄漏 | 警告（stderr） | 函数结束时仍有活句柄 |
| 2 | 视图生命周期（逃逸） | **错误** | 本帧栈视图从 `return` / 堆容器（`vec.push`·`vec.set`·`map.set`·`chan.send`）/ `spawn` 逃出 |
| 3 | 视图写别名 | **错误** | 同一基址上两个**独立创建**的视图区间可能重叠、且都被写入 |
| 4 | 跨线程 | **错误** | `spawn` 实参含 `rc[T]` 句柄（引用计数非原子）或本帧栈视图 |

"视图" = 切片 `[]T` 与 str 值（`{ptr,len}` / 长度前缀指针，都是**别名视图**，
不像 struct/数组那样按值拷贝）。视图基址分五类：

| 基址类别 | 来源 | 能否逃出本帧 |
|---|---|---|
| 本帧栈 | 局部定长数组、局部 struct 的数组字段、**值语义形参**（`[N]T` / struct 形参是拷贝） | ❌ 逃逸即报错 |
| 堆 | vec 缓冲、`mem_alloc`、`read_text`、拼接 / `substr` / `to_str` | ✅ |
| 静态 | 字符串字面量 | ✅ |
| 调用方所有 | `[]T` / `str` 形参 | ✅（生命周期由调用方保证） |
| 未知 | 函数返回值 | ✅（被调方自己的检查已拦住"返回本帧视图"） |

**写别名的口径**：切片是**显式零拷贝共享**（§3），所以规则不是 Rust 的
"独占借用"，而是：

- `let t = s`（拷贝视图）算**同一别名组**，两处写入不报——共享本来就是语义；
- 两次**独立创建**（`slice_of(a)` 与 `a[2..6]`）且区间可能重叠、又都被写入 → 报错；
- 能证不重叠就放行：常量区间按 `[lo,hi)` 判交；变量界按"同一界表达式"
  判首尾相接（`a[0..mid]` 与 `a[mid..8]`）。

**如实登记的不查项**（不对外宣称"Rust 那套借用检查"）：

- 多线程同时写同一堆内存的**数据竞争**（只拦 rc 句柄与栈视图跨线程）；
- `mem_str(p, n)` 裸指针的来源（无静态信息）；
- **跨函数别名**：被调方写 `[]T` 形参，调用方看不到（每函数独立检查）；
- str 的别名本身：str 不可变，且只能来自字面量 / 堆 / 形参 / `mem_str`，
  没有指向栈的路径；
- `arena { }` 内的裸指针视图（同样只有 `mem_str` 一条路）。

证据：`tests/t51_rc.qma`、`tests/t116_ownview.qma`（正例：8 类合法形态）、
`tests/bad/own_use_after_drop.qma`、`tests/bad/own_move_use.qma`、
`tests/bad/own_double_drop.qma`、`tests/bad/own_slice_escape.qma`、
`tests/bad/own_struct_escape.qma`、`tests/bad/own_alias_write.qma`、
`tests/bad/own_spawn_rc.qma`、`tests/bad/own_nested_match.qma`（负向，必须编译失败）。

### 8.4 接口动态分发（v1.97 收口）

```quelmara
interface Shape {
    fn area(self) -> int
}
struct Sq { n: int }
impl Sq : Shape {
    fn area(s: Sq) -> int { return s.n * s.n }
}
fn area_of(s: Shape) -> int { return s.area() }   // 接口形参：调用点装箱
let s: Shape = Sq { n: 3 }                        // 接口变量：块尾释放
print(area_of(Sq { n: 4 }).to_str())              // 静态可判定处直接调用
```

**值表示与派发**

- 接口值 = `{data, vt}` 两字：`data` 指向堆上装箱的 payload，`vt` 是代码段里的
  vtable 地址；`obj.m(...)` → `vt[slot]` 取函数指针 → 间接调用（x86-64 `call`，
  AArch64 `BLR`）。槽位顺序 = 接口里方法的**声明顺序**。
- 静态可判定（`let q = Sq{..}` 后调 `q.area()`）直接调用具体方法，零开销。
- payload 宽度按 `agg_size` 取，struct 与 **enum** 都能装箱（enum 装箱 v1.65）。

**装箱块的所有权（v1.83 起带引用计数）**

块布局 `[rc:8][payload_bytes:8][payload...]`，`data` 指向 payload，所以 impl 方法的
`self` 仍是普通聚合指针，方法体与 ABI 零改动。释放规则：

| 场景 | 行为 |
|---|---|
| `let s: Shape = 具体值`（新建箱） | 所有权转给槽位；块尾 / 提前 `return` / `break`·`continue` 跳出时 `__iface_release` |
| `let b: Shape = a`（复制） | `__iface_retain`（+1），两个槽各释放一次 |
| `a = 新值`（赋值替换） | 先释放旧箱，再接管新箱 |
| 接口形参（`area_of(Sq{..})`） | 调用点装箱，语句结束释放 |
| 接口返回值 | 所有权转给调用方，调用方按上面三条处理 |
| 进容器元素 / struct 字段 / map 值 | `retain`（容器没有 Drop，元素随容器走） |
| 来源不可判定（`vec.get` / 字段读 / 形参） | 按**借用**处理：不增计数也不释放——计数只会偏大，不会提前回收 |

计数归零走 `__free` 的尺寸类回收，所以热点循环不再线性涨堆：
`tests/iface_lowheap`（1 MB 上限 / 19 MB 装箱量）与 `tests/iface_lowheap_a64`
（A64 模拟器，1 MB 上限 / 1.14 MB 装箱 + 900 KB 探针）都是这条的回归。

**跨接口同名方法与跨文件**

- 同一类型在两个接口里有同名方法：impl 按接口名二次 mangling（`Type__Iface__m`）
  共存，vtable 各走各的槽位；此时**静态调用** `t.m()` 有歧义 → 编译报错并提示先
  转成接口值（`let s: Show = t`）。证据：`tests/t116_iface_multi.qma`、
  `tests/bad/iface_dup_method.qma`。
- 接口可以 `pub`，`impl` 写在**别的文件**里（v1.83）：接口名进跨文件种子，
  接口值的 `{data, vt}` 布局随之可见。种子是**扁平合并**的一份声明，因此
  同名同签名重复声明是幂等的，签名不一致报"接口冲突"。
- v1.88 起，宽松第一遍扫描里"凭空登记"的接口占位**不进种子**——拼错接口名
  （`impl R : Shappe`）会报"未声明的接口"，不会被当成空接口静默接受。
  证据：`fixtures/ifacexfile/`（正向，含本侧重复声明）、
  `tests/bad/iface_xfile_conflict/`、`tests/bad/iface_xfile_undecl/`（负向）。

**平台与边界**

- AArch64 发射层已接 vtable（v1.97）：代码段尾部一张 8 字节槽函数指针表，
  收尾时按函数标签回填绝对地址；执行级回归 `tests/a64_iface_test.py`（7 个用例）。
- C 后端不支持 `interface`/`impl`（fail-fast）。
- 仍**不做**：装箱释放不调用 payload 的 `impl T : Drop`（`drop_table` 按具体类型
  挂载，接口槽的静态类型是接口名）；接口值没有"弱引用/循环引用"处理。

### 8.5 并发模型

| 设施 | 实现 | 边界 |
|---|---|---|
| `spawn` / `join` | Linux raw `clone()` + `wait4()`；Windows `CreateThread` | 工作线程栈 512 KB；**AArch64 未接** |
| `parfor` | 按核数切块 + 共享内存归约 | 归约算子只认 `+=` |
| `chan[T]` | 有界 MPMC + 自旋锁（抢不到就 `thread_yield`） | `select` 声明序优先，无随机化；AArch64 未接 |
| `arena { }` | bump 指针回卷 | 整块回收，无单对象释放 |
| `atomic_*` / `mem_xchg` | x86 `lock` 前缀；A64 `LDAXR`/`STLXR` 重试 | 双后端已通（§7.3） |
| `mem_load_acq` / `mem_store_rel` | x86 普通 `mov`（TSO）；A64 `LDAR`/`STLR` | 双后端已通 |
| `std/sync` | mutex / 栈 / WaitGroup（纯 Quelmara） | 栈 pop 取每栈消费者锁（消 ABA）；`wg_wait` 三段退避，非 futex |

**chan 为什么不先自旋抢锁**（v1.98 实测）：把"抢不到就让出"改成"先 pause 32 次
再让出"，双线程往返与多生产者争用两个场景都**没有可复现的收益**（区间大幅重叠）。
自旋只对"持锁者一定在跑"成立，本机核数少于生产者数时这个前提不成立。
测不出好处就不留这份复杂度，所以保留"抢不到就让出"。数字见 `06-status.md` §3.5c。

### 8.6 `defer`：块级清理（v1.48）

```quelmara
fn use(log: vec[int]) {
    let mut n = 0
    defer n = 99          // LIFO：同块内后写的先执行
    defer log.push(n)     // 读的是【退出时】的值
    n = 1
}                         // 退出：push(1) → n = 99
```

| 项 | 语义 |
|---|---|
| 作用域 | 语句所在的块（函数体 / `if` / `while` / `for` / `match` 分支体）；内层块先跑 |
| 顺序 | LIFO（同块内后写的先执行） |
| 触发点 | 块正常结束、`return`、`break`、`continue` 跳出该块 |
| 登记 | 是**语句**：执行到才登记——`if c { break }` 写在 defer 之前时那条路径不执行 |
| 取值 | 变量按**退出时**的值读，不是登记时的值 |
| 返回值 | `return expr` 先求值、再跑 defer；defer 改局部变量不影响已算出的返回值 |
| 可写形态 | 表达式 / `=` / 字段赋值 / 下标赋值 |
| 拒绝 | `defer let ...` 等带作用域的语句 → 编译期报错；C 后端整体不支持（fail-fast） |

实现：块入口给块内每条 defer 分配一个"已登记"标志位（初值 0），执行到 defer 置 1，
退出点 `if flag { 清理 }`。标志位是**语义必需**而非优化——否则 `break` 早于 defer 的
路径会误跑清理。`break`/`continue` 只跑到循环体帧，函数帧留到 `return`/函数尾。

证据：`tests/t91_defer.qma`（13 组断言）、`tests/bad/defer_let.qma`（必须编译失败）。

### 8.7 `Drop`：作用域退出析构（v1.93）

`Drop` 是**内建接口**，不用自己声明。给类型写一个 `drop` 就把它变成"析构类型"：

```quelmara
struct Conn { fd: int }

impl Conn : Drop {
    fn drop(c: Conn) {
        if c.fd >= 0 {          // 幂等：写完置空，重复析构不再动手
            tcp_close(c.fd)
            c.fd = -1
        }
    }
}

fn use() {
    let fd = tcp_listen(8080)   // 先落局部变量：字面量里直接调函数是 §7.9 的已知缺陷
    let c = Conn { fd: fd }
    // ... 用 c
}                               // 退出：自动 Conn__drop(c)，不用写 defer
```

| 项 | 语义 |
|---|---|
| 声明 | `impl T : Drop { fn drop(t: T) { ... } }`——恰好一个接收者、无返回值；多参/有返回值编译期报错 |
| 生效对象 | **`let` 绑定的聚合变量**（struct / enum）；泛型 struct 的 `impl Box[T] : Drop` 按实例展开 |
| 触发点 | 块正常结束、`return`、`break`/`continue` 跳出该块（与 `defer` 同一批退出点） |
| 顺序 | 同块内**逆序**（后绑定的先析构）；内层块先于外层；**在 `defer` 之后**跑 |
| 接收者 | 直接拿到**对象地址**（不经值拷贝），所以 `c.fd = -1` 写在原对象上 |
| 移动 | `let b = a` / `return a` 是**移动**：析构责任随值转移，`a` 不再析构 |
| 覆盖赋值 | `a = T { ... }` 先析构被覆盖的旧值，再装新值 |
| 不析构 | **形参**、容器元素（`vec`/`map`/`chan`）、struct 字段、临时值——宁可泄漏，不可悬垂 |
| 不跑 | `exit(code)` 直接结束进程（与 C++ `exit` 同）；C 后端整体不支持（fail-fast） |

**为什么是"按绑定"而不是"按值唯一所有权"**：本语言的 struct 是值拷贝语义，
`let b = a` 之外还有"传参 / 存进容器 / 读字段"三种拷贝路径。要让析构跟着**值**走，
需要完整的移动语义与借用检查（那是另一件事，见 §8.3 的口径）。当前规则选了
"只泄漏、不双重释放"这一侧：

- `let b = a`、`return a` 这两条**最常见**的转移路径已经按移动处理；
- 传参 / 存容器 / 字段读出的副本**不析构**——被调方或容器持有的是副本，析构它们
  可能破坏调用方还在用的句柄；
- 因此**需要唯一所有权的资源用 `rc[T]`**（§7.6，线性检查会盯住它），
  `Drop` 适合"句柄关一次"这类幂等清理（fd / 锁 / 缓冲）。

实现：`drop_table()` 在**全局 DCE 之前**收集 `impl T : Drop`（析构是隐式调用，
AST 里没有 `call` 节点，DCE 之后算会把析构函数当死代码删掉），并把它钉成 DCE 根；
降级时 `block()` 维护与 `defer_stack` 同进同出的 `drop_stack`，退出点逆序
`emit_drop()`——**直接 `emit("call", ...)`**，不经 `lower_call` 的聚合实参拷贝。

证据：`tests/t119_drop.qma`（12 组断言：逆序 / 嵌套块 / return / break / continue /
defer 顺序 / 两种移动 / 覆盖赋值 / 枚举析构 / 析构体写字段 / 形参不析构）、
`tests/bad/drop_arity.qma`、`tests/bad/drop_dupe.qma`（必须编译失败）。

## 9. 已知陷阱（写代码前先看）

1. **`s + n` 会被字符串拼接劫持**——指针算术一律用 `mem_ptr(p, off)`；`str + int` 现在是编译错误。
2. **`mem_load64/store64` 的偏移是槽索引（×8）**，`mem_load8/32` 是字节偏移。写错会静默写穿堆，崩溃点随机漂移。
3. **`vec` 句柄经 `int` 形参/返回值传递会丢类型标签**（`v.push` 报"不支持方法"）——要用 `vec[int]` 形参/返回类型。
4. **方法不能链在函数调用结果上**：`f(x).push(y)` 不支持。
5. **`>>` 是算术右移**，64 位值可能为负，右移要用 `>>>`。
6. **`"\xNN"`（≥0x80）是原始字节**，不是 Unicode 码点。
7. **struct 赋值是值拷贝**，改副本不影响原值；但 struct 里的 `vec`/`map`/`chan` 字段是
   **句柄**（`slice` 是 2 字视图）——拷贝 struct 后容器底层仍共享（与 `vec[vec]` 一致）。
8. **`match` 必须穷尽**，`_` 只能放最后。
9. **泛型调用推不出类型参数时报错**：`f(...)` 按实参推导；推不出（如唯一约束形参
   不是类型参数）时报错并提示 `f[T](...)`。跨文件前向泛型（被调用方后解析）仍须显式。
10. **`vec[map]` 存的是句柄**（v1.37）：`vec.clear/扩容` 不释放 map 本身；
    `map[K]Struct` 是**按值存储**（v1.41）：`set` 拷 N 字进表槽、`get` 拷出副本，
    改副本不影响表内——与 struct 赋值同语义；struct 里的 vec/map/chan 字段
    是句柄，随值拷贝、底层共享（陷阱 7 同款）。
11. **`substr(s, start, count)` 的第二参是长度，不是结束位置**——`substr("abcde", 1, 4)` 得
    `"bcde"`（4 个字符），不是 `"bcd"`。切片语法 `s[lo..hi]` 才是左闭右开。
12. **`==` 对 `struct`/`enum` 是地址比较**——`Color.Red == Color.Red` 实测为 `false`；
    聚合判等/排序要按字段、按变体手写（`match`），泛型里请声明 `Eq`，让编译器在调用点
    拦下（§4.5.1、`07-gaps.md` §7.6）。
    （`str` 的 `<` 曾经也是地址比较，v1.66 起改成按字节字典序，见 §4.5.1。）
