# Quelmara

**原生编译 · 多核默认 · 网络原生 · 全平台 · 结构干净 · 游戏/工程双强 · 省资源**

Quelmara 是一门从 0 到 1 设计的系统级编程语言。本仓库包含编译器（自研后端 + C 交叉验证）、  
语言规范、教程与五套回归测试。

> **后端约束：产品编译必须使用自研后端。** Linux 默认走自研 x86_64 ELF，Windows 默认走自研 x86_64 PE/COFF，AArch64 使用自研发射器。C99 后端只用于显式交叉验证、自举和测试，不是产品运行后端。

> **当前状态**：已发布 **v1.2**（`vec[T]` / 集合遍历 / `[N]T` 作参数返回值），  
> v1.3（import 实装 + parser 声明级自举）、v1.4（IOCP reactor）、v1.5（性能七项 + http/ws/sse）
> 与 v1.6（sha256/str/url/json/gzip/aes 六件套 + HTTP 压缩协商）、
> v1.8（整数宽度 / `@simd` / `@no_preempt` / `rc[T]` / 所有权检查 / `interface` 静态分发
> + 三个误编译修复）在工作区落地待提交
> —— 见 `CHANGELOG.md` 与 `HANDOVER.md`。  
> **能力边界与缺口全表**见 `docs/GAPS.md`（含"文档说没做、代码其实做了"的逐条核对）。

## 文档地图

| 文档                    | 一句话                                      |
| --------------------- | ---------------------------------------- |
| `GUIDE.md`            | 全景指南：怎么用 / 怎么写 / 自举为什么还差 7/9（2/9 已完成）/ 性能对比        |
| `SPEC.md`             | 语言规范全文（词法/类型/多核/网络/配置/工具链）               |
| `TUTORIAL.md`         | 从零上手：环境 → 第一个程序 → 多核 → 避坑                |
| `SHOWCASE.md`         | 一页看懂长什么样、能干什么、跑多快                        |
| `BACKEND.md`          | 自研后端设计：QuIR / 优化目录 / 双轨路线 / 实测基线         |
| `PLATFORM.md`         | 全平台矩阵与移植成本模型（Windows/macOS/wasm 讨论）      |
| `HANDOVER.md`         | 交接文档：现状 / 未完成 / 差什么 / 下一步                |
| `CHANGELOG.md`        | 版本日志（各版本特性/修复/回归数字的**唯一权威记录**）           |
| `docs/EXTENSIONS.md`  | 扩展名规范（`.qma` / `.qex` / `.qel` / `.qir`） |
| `docs/SELFHOST.md`    | 自举路线与组件退场表                               |
| `docs/ORIGINALITY.md` | 原创性声明与依赖清单                               |
| `docs/STATUS.md`      | **状态总表**：语言 / 工程化 / 性能 / 平台四维"现在到哪了" |
| `docs/LANG.md`        | v1.8 新特性语义：整数宽度 / @simd / @no_preempt / rc[T] / 所有权 / interface |
| `docs/GAPS.md`        | **能力缺口登记册**：现在做不到什么 / 文档与代码不符处 / 优先级路线 |
| `docs/P0_LIBS.md`     | 标准库 P0 四件套（sha256 / str / url / json）API、语义与实测 |
| `docs/SELFHOST_PLAN.md` | 后端自举 7 阶段排期与每阶段门禁                  |
| `docs/TLS.md`         | TLS（https / wss）分阶段路线图                   |
| `docs/PERF.md`        | 性能通用性归因与百万连接内存账                       |



```
Quelmara/
├── Quelmara.toml        # 根配置：多核开关、线程数、网络资源上限（唯一全局开关）
├── quelmara.cmd         # Windows 命令入口
├── examples/            # 16 个可直接运行的示例
│   ├── hello.qma              # 最小程序：函数/字符串/while
│   ├── fib.qma                # 递归（多后端交叉验证）
│   ├── loop_sum.qma           # 2 亿热循环基准（魔数除法 + 闭式折叠）
│   ├── collatz.qma            # 热循环 + break/continue（自校验）
│   ├── parallel_sum.qma       # parfor 多核数据并行 + 归约（字符串版）
│   ├── parfor_sum.qma         # parfor 多核（多后端交叉验证）
│   ├── prime_parallel.qma     # 多核素数统计（parfor 归约，自校验）
│   ├── game_loop.qma          # 游戏：嵌套结构体 + 帧循环 + break/continue + parfor
│   ├── inventory.qma          # 工程建模：结构体值语义 + 字段更新（自校验）
│   ├── traffic_light.qma      # 状态机：enum + match（自校验）
│   └── echo_server.qma        # net.TcpServer 百万连接 echo（epoll 非阻塞，C 后端）
├── tools/
│   ├── stage0/          # Python 引导层（stage-0，待退场，见 docs/SELFHOST.md）
│   │   ├── qlm.py           # 前端 + C99 后端（仅交叉验证/自举）
│   │   ├── qlm_native.py    # 自研 x86_64：Quelmara -> QuIR -> 机器码 -> 裸 ELF64（无 libc）
│   │   ├── qlm_pe.py        # 同一 QuIR -> PE32+/COFF（无 CRT，kernel32 导入）
│   │   ├── qlm_arm64.py     # 自研 AArch64：同一条 QuIR，只换发射层
│   │   ├── qlm_opt.py       # QuIR 优化器（后端/平台无关）
│   │   ├── qlm_cli.py       # 统一命令行：默认当前平台自研后端；C 仅显式交叉验证
│   │   └── qlm_fmt/mt/mem/store/uring/dbg.py   # 格式化器与各运行时发射器
│   └── dev/             # 开发脚本：门禁/迁移/自举进度（永久允许 Python）
├── bootstrap/           # Quelmara 自举层（stage-1，目标实现）
│   ├── lexer/qlm_lex.qma    # 流式词法器（与 Python 词法器逐 token 对拍全等）
│   └── parser/qlm_parse.qma # 声明级 parser（对拍 87/87 全等，v1.3 进行中）
├── tests/               # 五套回归 + 对拍脚本（lexdiff/parsediff/irdiff/emitdiff）
├── bench/               # 跨平台基线（baseline.json，v1.1）
├── docs/                # 规范与历史文档
└── archive/             # 旧版本快照
```

## 快速开始

```bash
# 自研后端：Quelmara -> 裸 ELF64（无 libc / 无 gcc）
python3 tools/stage0/qlm_native.py run examples/fib.qma
python3 tools/stage0/qlm_native.py run examples/parfor_sum.qma   # 多核：raw clone()

# Windows：Quelmara -> PE32+（无 CRT，kernel32 导入）
python tools/stage0/qlm_cli.py run examples/hello.qma --target win     # 产出 build/hello.qex
python tests/run_win_tests.py                                     # Windows 回归

# C 后端（仅显式交叉验证/自举，不是产品后端）
python3 tools/stage0/qlm.py run examples/hello.qma
python3 tools/stage0/qlm.py run examples/parallel_sum.qma

# 网络 echo 服务器（C 后端 epoll 版；自研后端请用 tcp_*/net_serve 示例）
python3 tools/stage0/qlm.py build examples/echo_server.qma --cc
./build/echo_server

# 回归测试（五套；项数随版本增长，权威数字见 CHANGELOG）
bash tests/run_native_tests.sh   # 自研后端（含 AArch64 模拟器执行级）
bash tests/run_tests.sh          # C 后端
bash tests/test_corelib.sh       # mem/mt/store 运行时
bash tests/test_uring.sh         # io_uring 网络
python tests/run_win_tests.py    # Windows PE（需在 Windows 上执行）

# 标准库四件套基准（sha256 1MiB / split+join / url×100k / json 2000 对象）
python tools/stage0/qlm_cli.py run bench/p0_bench.qma --target win

# 自举对拍（stage-0 与 stage-1 逐 token / 逐节点 / 逐字节比对）
python tests/lexdiff.py && python tests/parsediff.py
python tools/dev/selfhost_status.py   # 自举进度
```

## 核心机制速览

**1. 多核是默认行为**，单核是显式选择 —— 在项目根目录 `Quelmara.toml`：

```toml
[core]
multicore = false    # parfor/spawn 编译期降级为串行，代码零改动、语义不变
threads   = 1
```

Linux 走 `clone()`，Windows 走 `CreateThread`，归约结果语义一致。

**2. 网络是运行时的一部分**，不是库：

```quelmara
fn on_data(c: net.Conn, data: []byte) -> net.Action {
    c.write(data)?          // 零拷贝回写 + 显式背压
    return net.Action.Keep
}
```

资源上限（`max_conns` / 缓冲区 / 背压策略）全部在 `Quelmara.toml` 声明，超限 fail-fast。  
当前实现：**自研后端 Windows PE IOCP reactor**（`net_serve`，v1.4，见 `std/net.qma`）+
`tcp_listen/accept/send/recv`（v1.3）；Linux 侧自研后端 epoll 尚未落地（现为 C 后端 epoll/io_uring）。
上面 `net.Conn` / `net.Action` 结构体模型是**目标语法**，尚未实现（`docs/GAPS.md §4`）。

**3. 无 GC**：值语义 + 帧级 arena，分配与回收确定性 —— 游戏帧循环无停顿。  
（所有权/借用检查是**目标**，尚未实现；当前靠 arena 作用域约定，见 `docs/GAPS.md §2`。）

**4. `struct` 值语义 + `enum`/`match` + `break`/`continue`**：

```quelmara
struct Vec3 { x: int  y: int  z: int }

enum Shape { Circle(radius: int)  Rect(w: int, h: int) }

fn area(s: Shape) -> int {
    return match s {
        Shape.Circle(r) => 3 * r * r
        Shape.Rect(w, h) => w * h
    }
}
```

嵌套结构体、字段读写/复合赋值、按值拷贝与按值传参（副作用不外泄）；  
x86_64 ELF / Windows PE / AArch64 / C 四条链输出交叉验证。

**5. 任务并行 + 有界通道 + 帧级 arena（v0.4 / v0.5）**：

```quelmara
fn producer(ch: chan[int], n: int) {
    let mut i = 0
    while i < n { ch.send(i)  i += 1 }
}

fn frame() {
    let ch = chan[int].open(64)    // 有界 MPMC：满则阻塞 / 空则阻塞
    let h = spawn producer(ch, 1000)
    let mut sum = 0
    let mut i = 0
    while i < 1000 { sum += ch.recv()  i += 1 }
    join(h)

    arena {                        // 块内分配（字符串等）块末一次性回收
        let msg = "sum=" + sum.to_str()
        assert(msg == "sum=499500", "arena msg")
    }                              // bump 指针整体回卷，无 GC 扫描
}
```

- `spawn`：Linux `clone()`、Windows `CreateThread`、C `pthread`；`join(h)` / `h.join()` 取返回值。
- `chan[T]`：自研后端用**自旋锁 + `xchg` + yield**；C 后端用 `pthread_mutex/cond`；  
  容量满/空时阻塞；`chan.close()` 与 `select` 见 SPEC（v0.11）。
- `arena`：native 真实回卷 bump 指针；C 后端为纯作用域。
- `[core] multicore = false` 时 `spawn` 编译期退化为同步调用，`join` 直接取结果。

非 chan 程序不会带上通道运行库与 `SwitchToThread` 导入（按需发射，省体积）。

**6. 定长数组 `[N]T`、切片 `[]T` 与子切片 `a[lo..hi]`（v0.6 / v0.9 / v1.1）**：

```quelmara
let mut a = [1, 2, 3, 4]
a[1] = 20
a[2] += 5
assert(len(a) == 4, "len")

let b = a          // 值语义拷贝：改 b[0] 不影响 a
b[0] = 100
print(a[0])        // 1

print(a[1..3])     // 子切片：数组/切片是零拷贝视图，str 是拷贝
print(a[i])        // 越界：fail-fast（退出码 1，stderr 报错）
```

- 数值元素、栈上帧槽、值语义拷贝；下标支持动态变量与复合赋值。
- 切片 `[]T` = {ptr, len} 零拷贝视图，可作参数/返回值；`[N]T` 作参数/返回值  
  走值语义拷贝 + 隐藏出参（v1.2，自研后端）。
- 越界默认 fail-fast（`Quelmara.toml [build] bounds_check = false` 可关闭）。

**7. 字符串与集合（v0.10 / v0.12 / v1.2）**：

```quelmara
let s = "hello"
print(len(s))        // 5：字节长度
print(s[0])          // 104：字节值（0..255），可直接参与算术
print(s == "hello")  // true：内容相等，不是指针比较
print("42".to_int()) // 42：十进制解析，非法输入 fail-fast
print((-7).to_str()) // "-7"

let m = map[str]int.new(16)      // 开放寻址哈希表（语法 map[K]V，无逗号）
m.set("apple", 3)
for k in m { print(k) }          // 集合遍历（顺序实现定义）

let v = vec[int].new(4)          // 堆上变长数组，2 倍扩容
v.push(10)
```

- `str` 是字节串，v1.5.1 起用**长度前缀 ABI**：值指向 `[len][字节][NUL]`，`len(s)` 与 `s[i]` 都是 O(1)。
- `s[i]` 给的是**字节**不是单字符 `str`；越界 fail-fast，与数组/切片同策略。
- 非法十进制（空串 / 非数字 / 空格 / 超出 int64）一律 fail-fast，不静默返回 0。

**8. 位运算、进制字面量与命令行参数（v1.0 / v1.1）**：

```quelmara
const MASK = 0xFF                 // 0x / 0b / 0o 三种基数
let flags = 0b1010 & 0b0110       // & | ^ ~ << >> >>>（含 >>> 逻辑右移）
let lo    = "hello world"[0..5]   // "hello"
fn main() {
    for a in args() { print(a) }  // 命令行参数（不含程序名）
    eprint("diagnostic")          // stderr
}
```

**9. 文件读写、标准库与原生网络（v1.3）**：

```quelmara
import std.net                    // 标准库扁平合并（std/ 随编译器分发）

fn main() {
    let n = write_text("out.txt", "result\n")   // 覆盖写，返回字节数
    let srv = listen(8080)                       // 原生 TCP（无 CRT，ws2_32）
    let conn = accept(srv)                       // 阻塞等待
    send(conn, recv(conn, 4096))                 // echo 一包
    close_conn(conn)
    close_conn(srv)
}
```

**10. 无 CRT 的 Windows 原生产物**：入口即 `main`，  
导入仅 kernel32（+用到 ws2_32），堆按 1MB 粒度提交，hello 仅 **7 KB 级**。

## 实测

### Linux（3 核容器，v0.1–v0.9 基线）

| 负载                   | 自研后端                                | gcc -O2（C 后端）      |
| -------------------- | ----------------------------------- | ------------------ |
| fib(25) 递归           | 75025 ✓                             | 75025 ✓（交叉验证）      |
| divmod 160 行（正负/边界）  | 全等 ✓                                | 参考                 |
| loop_sum 2 亿热循环      | 518ms → **11–13ms**（v0.9 modsum 折叠） | 158–231ms          |
| parfor_sum 3 核 6M 任务 | 388ms → **29–35ms**（v0.9）           | 131–153ms（pthread） |
| 单核降级 multicore=false | 结果不变 ✓                              | 结果不变 ✓             |

### Windows（x64 / 20 逻辑核，本机实测）

| 负载                      | PE 产物   | 时间（5 次最优） |
| ----------------------- | ------- | --------- |
| hello                   | 7168 B  | —         |
| loop_sum 2 亿热循环         | 6144 B  | 357.9 ms  |
| parfor_sum 20 线程 6M     | 14848 B | 196.1 ms  |
| prime_parallel（10 万内素数） | 15872 B | 18.7 ms   |

回归规模随版本增长，**各版本项数以 `CHANGELOG.md` 为唯一权威记录**  
（v1.2 时点：Windows PE 91 项本机全绿；自研 Linux / C / corelib / io_uring 需 Linux 环境执行）。

> 未完成项、阻塞项、下一步排期见 **`HANDOVER.md`**；  
> 全平台矩阵与讨论见 **`PLATFORM.md`**。

## 路线图

| 版本            | 内容                                                                                                     |                              |
| ------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------- |
| v0.1          | **自研后端 x86_64 全链路**（QuIR/寄存器分配/指令编码/裸 ELF）+ C 后端 + epoll 网络 + 配置驱动降级 ✅                                 |                              |
| v0.2          | `break`/`continue`/`struct` + `frameaddr` + 内联/LICM/CSE/展开/调度 + ARM64 发射器 + `enum`/`match` ✅           |                              |
| v0.3          | **Windows x86_64 PE/COFF 后端（无 CRT）** + kernel32 导入 + DIR64 重定位 + CreateThread 多核 + 1MB 粒度提交 ✅          |                              |
| v0.4          | **`spawn`/`join` 任务并行 + `arena { }` 帧级回收**（Linux/Windows/C 三链）✅                                        |                              |
| v0.5          | **`chan[T]` 有界 MPMC 通道**（自旋锁 `xchg` + yield / C 条件变量）+ 运行库按需发射 ✅                                       |                              |
| v0.6          | **定长数组 `[N]T`**：字面量/索引/复合赋值/`len`/值语义拷贝/越界 fail-fast ✅                                                 |                              |
| v0.7          | **用户定义 Result + `?` 错误传播**（native/PE/C）+ 严格范围证明 + worker 内联边界 + 产品默认自研后端 ✅                             |                              |
| v0.8          | `option[T]` 受控单态化（合成枚举 + match 解构）✅                                                                    |                              |
| v0.9          | `[]T` 切片 + 泛型 `result[T,E]` + 模和折叠 `opt_modsum`（loop_sum 11–13ms）✅                                     |                              |
| v0.10         | `map[K]V` 开放寻址哈希表 + 浮点实际运算（f64/f32 三链）✅                                                                |                              |
| v0.11         | `h.join()` 方法式语法 + `chan.close()` + `select` ✅                                                         |                              |
| v0.12         | 字符串 `len` / `s[i]` 字节下标 / `to_int()` + `@extern` 收口 ✅                                                  |                              |
| v1.0          | **改名 Quelmara**（`.qma`/`.qex`/`.qel`）+ 自举前置能力（args/read_text/substr/chr）+ **stage-1 词法器**（对拍全等）✅       |                              |
| v1.1          | 位运算（含 `>>>`）/ 进制字面量 / 子切片 `a[lo..hi]` / 顶层 `const` / `eprint`/`exit` / 字符串字典序 / 跨平台 bench 基线 / 原创性门禁 ✅ |                              |
| v1.2          | `vec[T]` 变长数组 + \`for x in <map                                                                        | vec>`集合遍历 +`[N]T\` 作参数/返回值 ✅ |
| v1.3          | `import` 实装（扁平合并）+ `write_text` + `tcp_*` 原生 socket + parser 声明级自举 87/87 + 测试矩阵/CI ✅（待提交） |  |
| v1.4          | Windows PE **IOCP reactor**（`net_serve` + 回调派发）+ `callr` 间接调用 ✅（已提交 d769435/b3e0fe2） |  |
| v1.5          | 性能七项（str 长度前缀 / 2 的幂除法 / 越界消除 / 8 字节 memcpy / 内联白名单 / 展开阈值 / realloc）+ **http/ws/sse 协议三件套** ✅（待提交） |  |
| **v1.6（工作区）** | 标准库六件套：SHA-256+HMAC / JSON / 字符串 / URL / **gzip** / **AES-128-GCM** + HTTP `Content-Encoding` 协商 ✅（见 `docs/P0_LIBS.md`） |  |
| **v1.8（工作区）** | 语言层：真实整数宽度 / `@simd`(SSE2) / `@no_preempt` / `rc[T]` / 所有权检查 / `interface`+`impl`（静态分发）+ 修掉 3 个必现误编译 ✅（见 `docs/LANG.md`、`docs/STATUS.md`） |  |
| **v1.7（下一步）** | TLS Phase A 收尾（X25519）→ 记录层/握手；gzip 解码；FS/时间/随机最小集 |  |
| v1.7+         | 真整数宽度 / 容器扩展 / 函数值放宽 / 命名空间 / TLS Phase B / HTTP 客户端 / DNS / UDP / 包管理 |  |
