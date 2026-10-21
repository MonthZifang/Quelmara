# Quelmara 语言参考（v1.8 新增特性）

> 本文只写**已经实现并且有回归夹具**的特性，每条都给出语义边界和可跑命令。
> 完整语法见 `SPEC.md`，能力边界见 `docs/GAPS.md`，状态总表见 `docs/STATUS.md`。

---

## 1. 真实整数宽度：`u8 / u16 / u32 / u64 / i8 / i16 / i32 / i64`

### 1.1 语义

所有值在寄存器里都是 64 位；**宽度只在边界生效**：

| 位置 | 行为 | 例子 |
|---|---|---|
| `let x: u8 = e` | 取 `e & 0xFF` | `let a: u8 = 300` → `44` |
| `x = e` / `x += e`（x 已声明为窄类型） | 同上 | `let mut b: u8 = 255; b = b + 1` → `0` |
| 形参 `fn f(x: u8)` | **入口**截断 | `f(300)` 里 `x == 44` |
| 返回值 `-> i8` | **出口**截断 | `127 + 1` 返回 `-128` |
| 表达式内部 | **不截断**（按 C 提升到 64 位） | `u8 200 + 100 == 300` |

有符号类型（`i8/i16/i32`）用**符号扩展**，无符号用**零扩展**。

### 1.2 与 C 的差异

- C 的 `int8_t` 运算会整型提升到 `int`，Quelmara 提升到 `int64`——结果一致；
- C 的结构体字段赋值会截断，**Quelmara 目前不会**（字段宽度只用于布局）。
  这条是已知缺口，见 `docs/GAPS.md §2`。

### 1.3 夹具

```bash
python tools/stage0/qlm_cli.py run tests/t49_width.qma --target win
# 期望输出：width ok
```

---

## 2. 类型标注 `let x: T`

```quelmara
let a: u8 = 300        // 44
let mut b: u32 = 0
b = b - 1              // 4294967295
```

- 标注**只用于宽度类型**与可读性；它不是完整类型检查器，
  非宽度类型的标注会被忽略（仍按值语义绑定）。
- 数组 / 结构体的**初始化**仍要走字面量（`let a = [1,2,3]`）。

---

## 3. `@simd`：SSE2 归约

### 3.1 可用形状（故意窄）

```quelmara
let a = [1,2,3,4,5,6,7,8]
let mut s = 0
@simd for i in 0..8 { s = s + a[i] }     // 或 s += a[i]
```

硬性要求（不满足 → **编译错误**，不会静默降级）：

1. 循环体只有一条语句，且是 `acc = acc + a[i]` 或 `acc += a[i]`；
2. `a` 是 `[N]int` 定长数组，下标正好是循环变量；
3. 区间 `lo..hi` 为常量时编译器会检查越界。

函数级写法（作为**提示**，形状不匹配的循环静默回落标量）：

```quelmara
@simd
fn sum_all(a: [16]int) -> int {
    let mut s = 0
    for i in 0..16 { s = s + a[i] }
    return s
}
```

### 3.2 生成什么

`paddq` 两路（xmm0 累加，movdqu 载入）+ 标量尾循环 + 水平求和
（`movq` / `psrldq 8` / `add`）。不是自动向量化器。

### 3.3 语义差异（必须知道）

- **逐元素越界检查被跳过**：调用方要保证 `lo..hi ⊆ [0, len(a)]`；
- 溢出按 64 位补码回绕，与标量版一致。

### 3.4 实测

4096 元素 `int64` 求和 ×200：

| 版本 | 每次耗时 |
|---|---|
| 标量 `while` | 3–4 µs |
| `@simd for` | 1 µs（**3–4×**） |

`bench/p0_bench.qma` 与 `tests/t50_simd.qma` 可复跑。

---

## 4. `@no_preempt`：不插让出点

```quelmara
@no_preempt
fn spin_until(flag: int) -> int { ... }
```

语义：**编译器不在这个函数（或语句块）里插入 `sched_yield` / `SwitchToThread`**。
用在自旋等待、无锁临界区、要求确定性延迟的路径上。

- 代价：会把核跑满（没有让出，其他任务只能等时间片）；
- 它**不是**内核抢占开关，也不影响 `spawn/parfor` 的线程调度策略；
- 语句级写法：`@no_preempt while ... { ... }`（块内生效）。

---

## 5. `rc[T]`：引用计数句柄

```quelmara
struct Point { x: int, y: int }

fn make(a: int, b: int) -> rc[Point] {
    let p = Point { x: a, y: b }
    return rc_new(p)
}

fn main() {
    let r = make(3, 4)          // count = 1
    let c = rc_clone(r)          // count = 2
    let p = rc_get(r)            // 借用，不增计数
    rc_drop(c)                   // count = 1
    rc_drop(r)                   // count = 0 -> __free
}
```

### 5.1 内存布局

```
[ refcount: 8B ][ payload: n*8B ]
                  ^ 句柄 h 指向这里（h-8 是计数）
```

### 5.2 API

| 函数 | 语义 |
|---|---|
| `rc_new(v)` | 堆上分配 `8 + sizeof(T)`，拷贝 `v`，计数 = 1 |
| `rc_get(h)` | 取回 payload（`T` 值语义视图，**不增计数**） |
| `rc_clone(h)` | 计数 +1，返回同一句柄 |
| `rc_drop(h)` | 计数 -1；到 0 时 `__free` |
| `rc_count(h)` | 读计数（诊断用） |

### 5.3 边界

- `T` 只能是具名 `struct`（标量载荷 / enum / 嵌套 `rc` 未支持）；
- **不自动 drop**：没有析构器、没有作用域自动回收，必须显式 `rc_drop`
  或 `return`（所有权转移）；
- 句柄按值传递，不增计数——传参是**借用**语义，调用方要保证生命周期覆盖调用。

---

## 6. 所有权 / 借用检查

### 6.1 检查什么

只对 **`rc[T]` 句柄**做线性类型检查，三条**编译错误**：

| 错误 | 例子 |
|---|---|
| use-after-drop | `rc_drop(a); print(rc_count(a))` |
| double free | `rc_drop(a); rc_drop(a)` |
| move-then-use | `let b = a; rc_drop(a)` ← `a` 已 move 给 `b` |

外加一条**编译警告**（不阻断）：

- 函数结束时仍有存活的 `rc` 句柄（泄漏）；
- 覆盖一个还活着的句柄（旧句柄泄漏）。

### 6.2 怎么做

语句级线性扫描 + 分支合并（`if` 两个分支都置 dead 才算 dead，
避免误报），每个函数入口跑一次。实现：`tools/stage0/qlm_native.py::check_ownership`。

### 6.3 不检查什么

- struct / 数组 / `str` 的别名与生命周期（值语义或 arena 借用）；
- `vec` 句柄的别名（堆上，无引用计数）；
- 并发下的数据竞争（`spawn` 共享内存不检查）。

> 这三条明确记在 `docs/GAPS.md §2`，**不要**把当前实现当成 Rust 那套借用检查。

### 6.4 夹具

```bash
python tools/stage0/qlm_cli.py build tests/bad/own_use_after_drop.qma --target win   # 必须失败
python tools/stage0/qlm_cli.py build tests/bad/own_double_drop.qma    --target win   # 必须失败
python tools/stage0/qlm_cli.py build tests/bad/own_move_use.qma       --target win   # 必须失败
```

---

## 7. `interface` / `impl`

### 7.1 写法

```quelmara
interface Shape {
    fn area(self) -> int
    fn scaled(self, k: int) -> int
}

struct Circle { r: int }

impl Circle : Shape {
    fn area(c: Circle) -> int { return c.r * c.r * 3 }
    fn scaled(c: Circle, k: int) -> int { return c.area() * k }
}
```

- 接口方法的第一个参数写 `self`（不写类型），其余参数带类型；
- `impl` 里的方法第一个参数必须是接收者（类型 = impl 的结构体）。

用接口值（v1.9 起）：

```quelmara
let s: Shape = Circle { r: 3 }     // 隐式装箱：{data, vt}
print(s.area())                    // 动态派发：vt[slot] -> callr

let v = vec[Shape].new(4)          // 异构容器
v.push(Circle { r: 1 })
v.push(Rect { w: 2, h: 3 })
for x in v { print(x.area()) }     // 每个元素派发到自己的实现

fn describe(s: Shape) -> str { return s.name() }   // 接口形参（调用点装箱）
fn pick(f: int) -> Shape { ... }                    // 接口返回值
```

### 7.2 编译期检查

| 错误 | 结果 |
|---|---|
| `impl` 少实现接口方法 | 编译失败：`impl T : S 缺少方法 b` |
| 参数个数/类型不符 | 编译失败 |
| 返回类型不符 | 编译失败：`T.a: 返回类型与接口声明不一致` |
| `impl` 的类型未声明 | 编译失败 |

### 7.3 分发方式：静态优先，接口值走 vtable

| 场景 | 分发方式 | 开销 |
|---|---|---|
| `c.area()`，`c: Circle`（接收者类型编译期已知） | **静态**：直接 `call Circle__area` | 零（可内联） |
| `s.area()`，`s: Shape`（接口值） | **动态**：`vt = s[1]; fp = vt[slot]; callr fp, [s[0]]` | 两次 load + 一次间接调用 |
| `vec[Shape].push(Circle{..})` | 装箱后按 2 字元素存 | 一次 `__alloc` + 拷贝 |
| `f(Circle{..})`，形参是 `Shape` | 调用点隐式装箱 | 同上 |

**接口值的内存布局**（`interface` 声明时自动注册成 2 字结构体）：

```
+0  data : 指向堆上装箱的 payload（结构体按值拷进去）
+8  vt   : 指向 vtable（代码段里的一张函数指针表，槽位 = 接口方法声明顺序）
```

**vtable** 在代码段末尾生成，每槽 8 字节，内容由 `code_fixups` 回填方法地址
（ELF 与 PE 走同一套绝对地址 + 重定位机制，PE 同时登记 DIR64 重定位）。

**隐式装箱的四个位置**（都已实现并有夹具）：
`let s: Shape = Circle{..}`、函数实参、`vec[Shape].push`、`return`（接口返回类型）。

### 7.3.1 边界（明确写死，不要当成 Rust trait object）

- **装箱是拷贝**：`payload` 会被复制到堆上，之后改原变量不影响接口值；
- **不释放**：装箱内存随进程生命周期（没有引用计数、没有 drop），
  大量短命装箱会涨堆；需要共享/释放语义请用 `rc[T]` 或自己管 arena；
- **同一类型在两个接口里有同名方法 → 编译错误**（mangling 是 `Type__method`，
  现在没有消歧义规则）；
- **`interface` 与其 `impl` 必须在同一个源文件**（一致性检查按文件做）；
- **C 后端（`--target c`）不支持** `interface`/`impl`，只支持自研后端；
- 接口方法可以返回聚合（走隐藏出参 + `callr`），但没有默认方法、没有关联类型。

### 7.4 夹具

```bash
python tools/stage0/qlm_cli.py run   tests/t52_iface.qma            --target win   # 静态分发
python tools/stage0/qlm_cli.py run   tests/t54_iface_dyn.qma        --target win   # 动态分发
python tools/stage0/qlm_cli.py build tests/bad/iface_missing.qma   --target win   # 必须失败
python tools/stage0/qlm_cli.py build tests/bad/iface_rettype.qma   --target win   # 必须失败
python tools/stage0/qlm_cli.py build tests/bad/iface_no_impl.qma   --target win   # 必须失败
python tools/stage0/qlm_cli.py build tests/bad/iface_dup_method.qma --target win  # 必须失败
```

---

## 8. 相关：v1.8 修掉的三个误编译

写库时踩到的三个必现错误，已修复并转正为回归（`tests/t53_regress.qma`）：

| # | 症状 | 根因 |
|---|---|---|
| 1 | 循环内 `substr` 长度来自调用结果 → 越界/错串 | 内联路径把栈偏移 `8` 当 R8 寄存器号比较，跳过 fetch |
| 2 | `"\xNN"`（≥0x80）被二次 UTF-8 编码 | 词法器 `chr(b)` + `encode("utf-8")`，改用 `surrogateescape` |
| 3 | 一个表达式里两次调用 + 下标 → 整体偏移 | 同 #1 |

排查手法与教训见 `docs/GAPS.md §6.5`。

---

## 9. 并发地基：atomic 内建 + std/sync（v1.10）

### 9.1 atomic 内建（x86_64，ELF/PE 同编码）

```quelmara
let p = static_word(3)          // 或 mem_alloc(8)——地址必须 8 字节对齐
let old = atomic_add(p, 1)      // lock xadd：*p += 1，返回**旧值**
let old = atomic_cas(p, 50, 99) // lock cmpxchg：*p==50 时写 99，返回旧值
let old = mem_xchg(p, 7)        // xchg（v1.5 已有）：交换，返回旧值
atomic_fence()                  // mfence：全内存屏障
spin_hint()                     // pause：自旋等待提示
now_cycle() -> int              // rdtsc：周期计数（程序内自计时用）
```

- 成功/失败判断：`atomic_cas` 返回**旧值**，调用方比较 `old == expect`；
- **无锁计数**：`atomic_add` 天然安全；**互斥**：CAS 自旋（见 std/sync）；
- 语义：每条 atomic 自带全屏障（lock 前缀），store-load 顺序无需手补 fence。

### 9.2 std/sync（Quelmara 自实现，零外部运行时）

```quelmara
import std.sync
let m = mutex_new()             // 自旋锁（CAS + pause）
mutex_lock(m) ... mutex_unlock(m)

let s = stack_new()             // Treiber 无锁栈
stack_push(s, v) / stack_pop(s) // 多生产者 push；pop 单消费者（见边界）

let w = wg_new()                // WaitGroup
wg_add(w, 3) ... wg_done(w) ... wg_wait(w)
```

### 9.3 实测（rdtsc 程序内自计时，2e6 次，bench/sync_bench.qma）

| 操作 | cycles/iter | 备注 |
|---|---|---|
| 标量自增（基线） | **2** | 编译器已到指令数下限 |
| `atomic_add`（lock xadd） | **27** | lock 前缀全核串行化，未争用 |
| mutex lock+RMW+unlock | **28** | 无竞争 CAS 一次成功 + store；无 libc 间接 |
| 无锁栈 push+pop | **106** | 两次 CAS + 两次 mem_alloc + 链操作 |

### 9.4 边界

- AArch64 发射层未接 atomic/rdtsc（编译期明确报错，与 trunc/vsum/vtable 同条边界）；
- 栈 pop 多消费者有 ABA（需 tagged pointer，GAPS 登记）；本库 pop 按单消费者设计；
- `now_cycle` 是墙钟近似（TSC 周期，非纳秒）；标定由调用方做。
