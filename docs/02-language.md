# 语言参考

> 事实来源：`tools/stage0/qlm.py`（词法/语法/推断）、`tools/stage0/qlm_native.py`（语义与内建）、
> `tests/*.qma`（可运行用例）。每节末尾的"证据"给出可复核的文件或命令。

## 1. 源文件与模块

```quelmara
module hello        // 每个文件一个模块名，仅作文档用途（不参与名字解析）
import std.core     // 扁平合并：递归加载 std/ 与同目录 .qma
```

- 源码扩展名固定 `.qma`；`.ros` 已废弃，遇到会给出 `git mv` 迁移提示  <!-- legacy-ok -->
  （`tools/stage0/qlm.py:50` `require_source`）。
- `import` 是**扁平合并**：顶层 `fn` / `struct` / `enum` / `test` 直接并入主 AST，
  没有命名空间、没有可见性、没有版本（`load_program`）。
- 查找顺序：主文件目录 → `std/` → `[src].lib` → `[src].ref` → `.qpm/deps`，
  **惰性解析**（import 什么加载什么）。布局规则见 [`05-toolchain.md`](05-toolchain.md)。
- 名字冲突、循环 import、被导入文件定义 `main`，一律编译报错。
- 顶层 `const` 两遍解析，可跨模块可见。

## 2. 词法

### 2.1 关键字（31 个，`qlm.py:125`）

```
fn  let  mut  if  else  while  for  parfor  return  break  continue
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

### 2.4 注释

```quelmara
// 行注释
```

只有行注释，没有块注释。

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
| 映射 | `map[K]V` | 开放寻址，K∈int/bool/str，V∈int/str |
| 通道 | `chan[T]` | 有界 MPMC |
| 可选 | `option[T]` | 合成枚举，`some` / `none` |
| 结果 | `result[T,E]` | 合成枚举，`ok` / `err`，支持 `?` |
| 引用计数 | `rc[T]` | `[refcount][payload]`，载荷仅具名 struct |
| 接口 | `interface Shape { ... }` | 接口值 = `{data, vt}` 两字 |
| 函数值 | 函数名直接作值 | `callr` 间接调用，≤6 参 |

嵌套容器：`vec[vec[T]]` 支持（任意深度）；`vec[map]` **不支持**。

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
- 编译器校验：方法齐全、参数个数、返回类型；缺方法/签名不符 → 编译失败
  （`tests/bad/iface_missing.qma` 等）。
- 隐式装箱四处：`let` 标注、函数实参、`vec[Shape].push`、`return`。
- 装箱是**拷贝且不释放**（无 rc/drop）；热点循环里频繁装箱会涨堆。
- 同一类型在两个接口里同名方法 → 编译错误（无消歧规则）。

### 4.5 用户泛型（单态化）

```quelmara
fn pick_first[T](a: T, b: T) -> T { return a }
fn fact[T](n: T) -> T {
    if n <= 1 { return 1 }
    return n * fact[T](n - 1)      // 自递归可用
}

let x = pick_first[int](1, 2)      // 必须显式写类型实参
let s = pick_first[str]("a", "b")
```

编译期把模板深拷贝成具名实例（`fact__int`），调用点降为普通 `call`——**零运行时分发开销**。

边界：单类型参数、必须显式实例化（无推导）、无约束（where）、无泛型 struct、无泛型方法。

### 4.6 常量（编译期算术）

```quelmara
const KB: int = 1024
const BUF: int = 4 * KB        // 引用前面的 const
const HALF: int = BUF / 2      // C 截断除法
```

只支持整型 `+ - * / %`、括号与 const 引用，按声明序求值。`const fn` 未做。

### 4.7 注解

| 注解 | 位置 | 作用 |
|---|---|---|
| `@simd` | 函数或 `for` 语句 | 触发 SSE2 归约（形状不匹配则静默回落标量） |
| `@no_preempt` | 函数 | 不插入让出点 |
| `@extern("C")` | 函数声明 | C 后端用；自研后端显式拒绝 |

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
| `option[T]` | 构造 `option[int].some(x)` / `.none()`；解构走 `match Option.Some/None` |
| `result[T,E]` | 构造 `result[int,str].ok(x)` / `.err(e)`；解构走 `match Result.Ok/Err` |
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

只接受两变体、单标量载荷的 result。

### 6.4 其它

- 子切片：`a[lo..hi]`（左闭右开）。`str` 切片是拷贝，数组/切片是零拷贝视图。
- 函数值：直接写函数名，经 `callr` 间接调用（≤6 参，实参不能是 struct/slice，无捕获）。
- 强制转换：`to_int(x)` / `to_float(x)` / `to_f32(x)`。

## 7. 内建函数（67 个）

> 全部在 `tools/stage0/qlm_native.py` 的内建分派里；用户可用同名 `fn` 覆盖（分派处均有
> `name not in self.fns_ast` 保护）。

### 7.1 输出 / 进程 / 参数

| 函数 | 说明 |
|---|---|
| `print(x)` | 输出 + 换行，接受 int/str/f64/bool |
| `eprint(x)` | 输出到 stderr |
| `exit(code)` | 退出进程 |
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
| `mem_str(p, n)` | 内存转 str |
| `mem_load8/32/64(p)`、`mem_store8/64(p, v)` | 裸读写（8/32 是字节偏移，64 是槽索引 ×8） |
| `mem_alloc(n)` / `mem_free(p)` | 裸分配/释放 |
| `mem_xchg(p, v)` | 原子交换 |

### 7.3 并发 / 原子

| 函数 | 说明 |
|---|---|
| `atomic_add(p, v)` / `atomic_cas(p, old, new)` / `atomic_fence()` | lock 前缀指令，返回旧值 |
| `spin_hint()` | `pause` 指令 |
| `now_cycle()` | `rdtsc` 周期计数 |
| `static_word(n)` | 静态字槽（库内部用于惰性表） |

### 7.4 时间 / 文件 / 资源

| 函数 | 说明 |
|---|---|
| `now_ns()` | 单调纳秒 |
| `wall_ms()` | 墙钟 Unix epoch 毫秒 |
| `sleep_ms(n)` | 睡眠 |
| `read_text(path)` / `write_text(path, s)` | 文本读写 |
| `file_exists(path)` / `file_size(path)` | 文件查询 |
| `fs_mkdir(path)` / `fs_remove(path)` | 目录/文件操作（mkdir 幂等） |
| `read_asset(name)` | 读 `[src].asset` 根下的资源（编译期嵌入） |

### 7.5 网络

| 函数 | 说明 |
|---|---|
| `tcp_listen(port)` / `tcp_accept(fd)` / `tcp_send(fd, s)` / `tcp_recv(fd)` / `tcp_recv_n` / `tcp_send_n` / `tcp_close(fd)` | 阻塞 TCP（IPv4 字面量，无域名解析） |
| `udp_open()` / `udp_bind(fd, port)` / `udp_sendto(fd, ip, port, s)` / `udp_recvfrom(fd)` | UDP 四件 |
| `net_serve(port, handler, threads)` | IOCP reactor（仅 Windows PE） |

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
| 表达式内部 | **不截断**，按 C 提升（`u8 200 + 100 == 300`） |

未覆盖：struct 字段存窄值不截断（字段类型只用于布局）；`vec[u8]` 元素仍是 8 字节槽。

证据：`tests/t49_width.qma`（14 条断言）。

### 8.2 `@simd`：两种形状，不是向量化器

| 形状 | 指令 | 要求 |
|---|---|---|
| `acc += a[i]`，`acc: int`，`a: [N]int` | SSE2 `paddq` 两路 | 循环体只有这一条语句 |
| `acc += a[i]`，`acc: f64`，`a: [N]f64` | SSE2 `addpd` 两路 | 同上 |

- 逐元素越界检查**被跳过**，调用方保证 `lo..hi ⊆ [0, len(a)]`。
- f64 归约**改变求和顺序**，结果可能与标量版不逐位相等（2 的幂可逐位验证）。
- 形状不匹配：函数级注解静默回落标量；语句级注解直接编译报错。
- 点积 `a[i]*b[i]` 需要 AVX2 `vpmullq`，未做。

证据：`tests/t50_simd.qma`、`tests/t59_simdf64.qma`。

### 8.3 `rc[T]` 与所有权检查

```quelmara
struct Point { x: int, y: int }
let r = rc_new(Point { x: 3, y: 4 })
let c = rc_clone(r)      // count 2
let p = rc_get(r)        // 借用，不转移
rc_drop(c)               // count 1
```

内存布局 `[refcount:8][payload]`；载荷仅具名 struct。

所有权检查**只覆盖 rc 句柄**：use-after-drop / double-free / move-then-use 三类编译错误，
外加泄漏警告。struct/数组/str 的别名与生命周期**不检查**，也不查数据竞争。

证据：`tests/t51_rc.qma`、`tests/bad/own_*.qma`（必须编译失败）。

### 8.4 接口动态分发的边界

- 接口值 = `{data, vt}` 两字；`obj.m()` → `vt[slot]` 取函数指针 → `callr`。
- 静态可判定时直接调用，零开销。
- 装箱内存不回收（无 rc/drop）；`vec[Shape]` 异构容器可用。
- 接口与 `impl` 必须**同源文件**。
- AArch64 发射层未接 vtable → 编译期明确报错。
- C 后端不支持 `interface`/`impl`。

### 8.5 并发模型

| 设施 | 实现 | 边界 |
|---|---|---|
| `spawn` / `join` | Linux raw `clone()` + `wait4()`；Windows `CreateThread` | 工作线程栈 512 KB |
| `parfor` | 按核数切块 + 共享内存归约 | 归约算子只认 `+=` |
| `chan[T]` | 有界 MPMC + 自旋锁 | `select` 声明序优先，无随机化 |
| `arena { }` | bump 指针回卷 | 整块回收，无单对象释放 |
| `atomic_*` | `lock xadd` / `lock cmpxchg` | AArch64 未接 |

## 9. 已知陷阱（写代码前先看）

1. **`s + n` 会被字符串拼接劫持**——指针算术一律用 `mem_ptr(p, off)`；`str + int` 现在是编译错误。
2. **`mem_load64/store64` 的偏移是槽索引（×8）**，`mem_load8/32` 是字节偏移。写错会静默写穿堆，崩溃点随机漂移。
3. **`vec` 句柄经 `int` 形参/返回值传递会丢类型标签**（`v.push` 报"不支持方法"）——要用 `vec[int]` 形参/返回类型。
4. **方法不能链在函数调用结果上**：`f(x).push(y)` 不支持。
5. **`>>` 是算术右移**，64 位值可能为负，右移要用 `>>>`。
6. **`"\xNN"`（≥0x80）是原始字节**，不是 Unicode 码点。
7. **struct 赋值是值拷贝**，改副本不影响原值；`vec` 是句柄，共享底层存储。
8. **`match` 必须穷尽**，`_` 只能放最后。
9. **泛型必须显式实例化**：`f[int](...)`，写 `f(...)` 会被当成普通函数找不到。
10. **`vec[map]` 不支持**，需要时用两个平行 `vec` 或编码下标。
11. **`substr(s, start, count)` 的第二参是长度，不是结束位置**——`substr("abcde", 1, 4)` 得
    `"bcde"`（4 个字符），不是 `"bcd"`。切片语法 `s[lo..hi]` 才是左闭右开。
