# Rosoto 语言规范 (v0.1 草案)

> 目标一句话：**原生编译、多核默认、网络 IO 极致、全平台、代码结构干净、游戏/工程双强、省资源。**

---

## 0. 设计原则

| 原则 | 含义 |
|---|---|
| 原生优先 | AOT 编译为机器码，无 VM、无解释器、无 GC 停顿 |
| 多核默认 | 并行是默认行为，单核是显式选择（根目录 `Rosoto.toml` 禁用） |
| 网络原生 | 协议栈路径最短：epoll/kqueue/io_uring 内建，百万连接、KB 级常驻 |
| 可预测 | 确定性析构、无隐式堆分配、无隐藏控制流（错误用 `?` 显式传播） |
| 结构即文档 | 一个模块一个目录，入口即声明，无全局命名空间污染 |
| 省 | 编译产物小、启动快、内存占用低；资源上限可在配置文件声明 |

---

## 1. 词法与结构

```rosoto
// 单行注释
/* 块注释 /* 可嵌套 */ */

module app                // 模块声明 = 文件第一行有效语句
import std.net            // 导入标准库模块
import std.core
```

- 文件扩展名：`.ros`
- 一个模块 = 一个 `.ros` 文件 = 一个命名空间
- 标识符：`snake_case`（变量/函数）、`PascalCase`（类型/模块）、`SCREAMING_CASE`（常量）
- 语句以换行分隔，块用 `{}`；**没有分号**（结构即语法，减少噪音）

---

## 2. 类型系统

静态类型 + 局部推断。

```
int     默认 64 位有符号        i8 i16 i32 i64  u8 u16 u32 u64
float   默认 64 位浮点          f32 f64
bool    true | false
str     UTF-8 不可变字符串（长度内联）
[]T     切片（指针+长度，零拷贝传递）
[N]T    定长数组（栈上）
map[K]V 开放寻址哈希表（可指定 arena 分配）
option[T]   可空（无 null 指针）
result[T, E] 显式错误（配合 `?` 传播）
```

自定义类型：

```rosoto
struct Vec3 {
    x: f32
    y: f32
    z: f32
}

enum Shape {
    Circle(radius: f32)
    Rect(w: f32, h: f32)
}

interface Renderable {
    fn draw(self, target: &Canvas) -> result[void, DrawError]
}
```

**内存模型**：默认无 GC。
- 所有权 + 借用检查（编译期）：`T` 移动语义，`&T` 不可变借用，`&mut T` 可变借用
- **arena 分配**（`arena { ... }` 块内批量分配、块结束整体释放）——游戏帧循环友好
- `@rc[T]` 显式引用计数（付出成本是你自己选的）
- 析构确定性：离开作用域立即释放，无停顿

---

## 3. 函数与控制流

```rosoto
fn add(a: int, b: int) -> int {
    return a + b
}

fn classify(x: int) -> str {
    if x < 0 {
        return "negative"
    } else if x == 0 {
        return "zero"
    } else {
        return "positive"
    }
}

fn countdown(n: int) {
    let mut i = n                 // let 默认不可变，mut 显式可变
    while i > 0 {
        print(i)
        i = i - 1
    }
    for i in 0..n {               // 半开区间 [0, n)
        print(i)
    }
}
```

- 表达式一切皆值：`if`、`match`、`block` 均可返回值
- `match` 必须穷尽（编译期检查）：

```rosoto
let name = match shape {
    Shape.Circle(r) => "circle r=" + r.to_str()
    Shape.Rect(w, h) => "rect " + w.to_str() + "x" + h.to_str()
}
```

- 错误传播：`?` 把 `result` 的错误一路上抛，禁止静默吞错

```rosoto
fn load_config(path: str) -> result[Config, IoError] {
    let text = fs.read_to_string(path)?    // 出错直接 return Err
    return Ok(parse(text))
}
```

---

## 4. 多核模型（默认开启）

Rosoto 的运行时是一个 **work-stealing 任务调度器**，默认占用全部物理核心。

```rosoto
fn main() {
    // 数据并行：自动分块、跨核调度、归约
    let mut total = 0
    parfor i in 0..1_000_000 {
        total += heavy(i)          // total 是 reduction 变量，自动合并
    }

    // 任务并行：显式 spawn，返回 JoinHandle
    let h = spawn render_frame(scene)
    let a = spawn bake_lighting(scene)
    h.join()
    a.join()

    // 通信：类型化 channel，MPMC
    let ch = chan[Job].open(1024)
    spawn worker(ch)
    ch.send(Job { id: 1 })?
}
```

规则：
1. `parfor`/`spawn` 默认并行 —— **无需任何注解**
2. 多核禁用必须在**项目根目录 `Rosoto.toml`** 显式声明（见 §7）；禁用后所有并行结构退化为确定性串行，程序语义不变
3. 抢占点在安全位置（无锁临界区不切），游戏主循环可选 `@no_preempt`
4. 绑核/亲和性可配置；容器场景自动识别 cgroup CPU 配额

### 4.1 v0.4 已落地子集（明确边界）

```rosoto
fn tick(n: int) -> int { return n * 2 }

fn main() {
    let a = spawn tick(21)     // 任务句柄（int64）
    let b = spawn tick(20)
    assert(join(a) == 42, "task a")
    assert(join(b) == 40, "task b")
}
```

- ✅ `spawn f(args)`：任务并行，Linux `clone` / Windows `CreateThread` / C `pthread`；
  `join(h)` 等待并返回结果（void 任务返回 0）。
- ✅ `[core] multicore = false`：`spawn` 编译期退化为同步调用，`join` 恒等返回结果。
- ⚠️ v0.4 约束：实参/返回值仅标量（int/bool/str）；结构体/枚举按值跨线程明确报错；
  并行 `spawn` 目前只支持 x86_64（AArch64 待发射层）；句柄漏回收（bump 无 free），
  批量任务建议用 `arena { spawn ...; join ... }` 包住。
- 🚧 `h.join()` 方法式语法、`chan[T]`、work-stealing 调度器仍待实现（当前
  `spawn` 是每任务一线程，`parfor` 是静态分块）。

---

## 5. 网络模型（原生 IO）

网络不是库，是语言运行时的一部分。IO reactor 与任务调度器同进程协作：**IO 线程只做事件分发，业务在任务池执行**，零拷贝 buffer 池化复用。

```rosoto
module echo

import std.net

fn on_connect(c: net.Conn) {
    print("peer connected: " + c.peer_addr())
}

fn on_data(c: net.Conn, data: []byte) -> net.Action {
    c.write(data)?                 // 零拷贝回写，buffer 用后归还池
    return net.Action.Keep
}

fn on_close(c: net.Conn) {
    print("peer closed")
}

fn main() {
    let server = net.TcpServer {
        addr:           "0.0.0.0:9000"
        backlog:        65535
        max_conns:      1_000_000
        io_threads:     0          // 0 = 自动（按核数/配置）
        nodelay:        true
        reuse_port:     true
        on_connect:     on_connect
        on_data:        on_data
        on_close:       on_close
    }
    server.serve()                 // 阻塞于 reactor；Ctrl-C 优雅退出
}
```

要点：
- 后端按平台自动选择：Linux `io_uring` → `epoll`，macOS/BSD `kqueue`，Windows `IOCP`，移动端 `epoll/kqueue`
- 每连接内存 ≈ 数百字节；100 万连接常驻内存 < 1 GB（可配上限 `max_conns`）
- 背压：`c.write` 返回 `result[void, Backpressured]`，超限时策略可配（丢弃/断开/阻塞任务）
- 资源上限全部在 `Rosoto.toml` 声明（见 §7），超限行为确定（fail-fast，不静默膨胀）
- UDP / Unix socket / TLS / HTTP/2 / WebSocket 作为 `std.net` 子模块同级提供

---

## 6. 游戏与工程性能

```rosoto
fn frame(world: &mut World) {
    arena {                        // 帧级 arena：本帧分配，帧末整体释放
        let mut jobs = []Job
        for e in world.entities() {
            jobs.push(spawn update_entity(e, world.dt()))
        }
        for j in jobs {
            j.join()
        }
    }                              // <- 无 GC 扫描，无碎片抖动
}
```

- **零成本抽象**：`parfor`/迭代器/泛型全部单态化内联，release 无运行时开销
- **SIMD 友好**：`@simd for` 提示向量化；`[]f32` 连续内存布局（SoA 可用 `struct_of_arrays`）
- **确定性**：同输入同调度策略下帧耗时可复现，性能回归可 CI 化
- **嵌入 C ABI**：所有公开函数可 `@extern("C")` 导出，C/C++ 引擎直接调用；反向可 `@import_c("lib.h")`
- **编译速度**：模块级并行编译 + 增量缓存（工程级 monorepo 友好）

### 6.1 `arena { }` 的 v0.4 实现与边界

- **native（Linux/Windows）**：真实回卷 bump 分配器 —— 进入块时记下偏移，
  块末整体释放；用 `Rosoto.toml [memory] heap_limit_mb` 可证伪验证
  （`tests/arena_lowheap`：1MB 上限、4MB 分配量，有 arena 通过、无 arena OOM）。
- **C 后端**：字符串走轮转静态缓冲、无堆分配，`arena` 编译为纯作用域。
- **约束**：块内分配的对象**不得逃逸**；块内 `break/continue/return` 会跳过释放；
  bump 分配器非线程安全 —— 不要把分配放进并行 worker。
- 🚧 `[memory] arena_default = true`（顶层默认 arena）尚未接线。

---

## 7. 根配置文件 `Rosoto.toml`

**位置：项目根目录。这是唯一合法的全局资源开关。** 未声明字段取默认值。

```toml
[core]
multicore  = true        # false = 显式禁用多核，全部并行结构串行化
threads    = 0           # 0 = 自动（物理核数）；>0 = 精确指定
affinity   = "none"      # none | compact | scatter | [0,1,2]
preempt    = true        # false = 协作式（游戏主循环常用）

[net]
backend        = "auto"  # auto | io_uring | epoll | kqueue | iocp
io_threads     = 0       # 0 = 自动
max_conns      = 1000000 # 硬上限，超限拒绝连接（fail-fast）
recv_buffer    = 4096
send_buffer    = 4096
tcp_nodelay    = true
reuse_port     = true
backpressure   = "drop"  # drop | close | block

[memory]
arena_default = false    # true = 顶层作用域默认 arena
heap_limit_mb = 512      # 硬上限，超限 OOM fail-fast（不 swap 不膨胀）

[build]
opt        = "speed"     # speed | size | balanced
lto        = true
target     = "native"    # native | x86_64-unknown-linux-gnu | aarch64-apple-darwin ...
```

**示例：禁用多核（单核/单线程模式）**

```toml
[core]
multicore = false
threads   = 1
```

效果：`parfor`/`spawn` 编译期降级为顺序执行，调度器不启动线程池，二进制更小、行为确定；网络 IO 退化为单 reactor 线程内联执行。**代码无需任何修改。**

---

## 8. 编译与工具链

```
.ros 源码 ──parse──▶ AST ──lower──▶ RosIR ──opt──▶ ┌ x86_64 编码器 → 裸 ELF64（Linux）
                                                    ├ x86_64 编码器 → PE32+/COFF（Windows，无 CRT）
                                                    ├ AArch64 编码器 → ELF64（Linux arm64）
                                                    └ C99 转译 → 任意 C 编译器（移植/自举/网络 demo）

rosoto build <src> --target native|win|arm64|c   # 默认 native（Linux 裸 ELF）
```

- `rosoto build`   编译（读取 `Rosoto.toml`）
- `rosoto run`     编译+运行
- `rosoto test`    内建测试框架（`test "名字" { ... }`）
- `rosoto fmt`     官方格式化器（一种风格，终结争论）
- `rosoto bench`   基准测试，输出回归对比

---

## 9. 当前实现状态（v0.3）

本仓库包含**四个后端**（详见 `BACKEND.md` / `PLATFORM.md`）：

| 后端 | 路径 | 状态 |
|---|---|---|
| **自研 x86_64 Linux** | Rosoto → RosIR → 自研 x86_64 编码器 → 裸 ELF64（无 libc） | ✅ v0.1，执行级 |
| **自研 x86_64 Windows** | 同一 RosIR/编码器 → PE32+/COFF（无 CRT，kernel32 导入） | ✅ v0.3，本机 47 项 |
| **自研 AArch64 Linux** | 同一条 RosIR，只换发射层 → ELF64 | 🟡 模拟器执行级，待真机 |
| C 后端 | Rosoto → C99 → 任意 C 编译器（移植/bootstrapping/网络 demo） | ✅ v0.1 |

各后端对同一 `.ros` 源码交叉验证输出，互为 oracle。

已实现（v0.2 / v0.3 / v0.4）：

| 特性 | 状态 |
|---|---|
| `module` / `import` / `fn` / `let` / `let mut` | ✅ 全部后端 |
| `if/else` / `while` / `for i in a..b` / `return` | ✅ 全部后端 |
| **`break` / `continue`** | ✅ 全部后端 |
| int / bool / str / 表达式全集 | ✅ 全部后端 |
| **`struct` 声明 / 字面量 / 字段读写 / 复合赋值** | ✅ 全部后端 |
| **嵌套结构体 + 按值拷贝 + 按值传参（副作用不外泄）** | ✅ 全部后端 |
| **`enum` + `match`（穷尽性检查 / 载荷解构 / 块臂 / 通配臂）** | ✅ 全部后端 |
| **结构体/枚举返回值（隐藏出参指针 ABI）** | ✅ 全部后端 |
| `parfor`（Linux：raw clone；Windows：CreateThread；C：pthread）| ✅ 受 `[core] multicore` 控制 |
| `Rosoto.toml` 解析（core/net/memory/build）| ✅ 全部后端 |
| `net.TcpServer()`（epoll 非阻塞并发服务器 / io_uring 后端）| ✅ C 后端 intrinsic；Windows 待 IOCP |
| 魔数除法/强度削减/DCE/复制传播/线性扫描寄存器分配 | ✅ 自研后端 |
| **内联 / CSE-GVN / LICM / 循环展开 / 指令调度** | ✅ 自研后端（RosIR 级，全部发射层共享） |
| **Windows PE32+/COFF 写出 / kernel32 导入 / DIR64 重定位** | ✅ v0.3 |
| `test "名字" { ... }` 内建测试块 | ✅ `rosoto test` |
| `assert(cond, "msg")` | ✅ 全部后端（含 Windows stderr + 退出码 1） |
| **`spawn f(args)` + `join(h)`（Linux clone / Windows CreateThread / C pthread）** | ✅ v0.4，x86_64 + C；标量参数/返回值，单核同步降级 |
| **`arena { }` 帧级分配（native 真实回卷 bump；C 为作用域）** | ✅ v0.4（1MB 上限下 4MB 分配量的可证伪回归） |
| `option`/`result` + `?`、`map`/`[N]T`/`[]T` 运算 | 🚧 下一轮 |
| `chan[T]`、`h.join()` 方法式语法 | 🚧 运行时已备 C 版队列；native 降级待做 |
| 泛型 / interface / 所有权借用检查 / `@extern("C")` | 🚧 规范已定 |
| Windows IOCP/AFD 网络、Mach-O/kqueue、wasm、SIMD 向量化 | 🚧 路线图（PLATFORM.md / BACKEND.md）|

回归：`tests/run_native_tests.sh`（自研 Linux 42 项，含 AArch64 模拟器）+
`tests/run_win_tests.py`（Windows PE 47 项）+ `tests/run_tests.sh`（C 16 项）
+ `tests/test_corelib.sh`（34 项）+ `tests/test_uring.sh`（26 项）= **165 项全绿**。

实现状态、未完成清单、阻塞项与下一步排期见 `HANDOVER.md`。

运行时验证见 `tests/`，示例见 `examples/`。
