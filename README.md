# Rosoto

**原生编译 · 多核默认 · 网络原生 · 全平台 · 结构干净 · 游戏/工程双强 · 省资源**

Rosoto 是一门从 0 到 1 设计的系统级编程语言。本仓库包含：

> **后端约束：产品编译必须使用自研后端。** Linux 默认走自研 x86_64 ELF，Windows 默认走自研 x86_64 PE/COFF，AArch64 使用自研发射器。C99 后端只用于显式交叉验证、自举和测试，不是产品运行后端。

```
Rosoto/
├── SPEC.md              # 语言规范（语法/类型/多核/网络/配置文件/工具链）
├── BACKEND.md           # 自研后端设计：RosIR/优化目录/双轨路线/实测基线
├── PLATFORM.md          # 全平台矩阵与移植成本模型（Windows/macOS/wasm 讨论）
├── HANDOVER.md          # 交接文档：做了什么/没做什么/差什么/写了多少/需要写什么
├── Rosoto.toml          # 根配置文件：多核开关、线程数、网络资源上限（唯一全局开关）
├── examples/
│   ├── hello.ros              # 最小程序：函数/字符串/while
│   ├── fib.ros                # 递归（多后端交叉验证）
│   ├── loop_sum.ros           # 2 亿热循环基准（魔数除法）
│   ├── collatz.ros            # 热循环 + break/continue（自校验）
│   ├── parallel_sum.ros       # parfor 多核数据并行 + 归约（字符串版）
│   ├── parfor_sum.ros         # parfor 多核（多后端交叉验证）
│   ├── prime_parallel.ros     # 多核素数统计（parfor 归约，自校验）
│   ├── game_loop.ros          # 游戏：嵌套结构体 + 帧循环 + break/continue + parfor
│   ├── inventory.ros          # 工程建模：结构体值语义 + 字段更新（自校验）
│   ├── traffic_light.ros      # 状态机：enum + match（自校验）
│   └── echo_server.ros        # net.TcpServer 百万连接 echo（epoll 非阻塞，C 后端）
├── tools/
│   ├── rosoto.py          # 前端 + C 后端：Rosoto -> C99（pthread / epoll / 配置驱动降级）
│   ├── rosoto_native.py   # 自研 x86_64：Rosoto -> RosIR -> 机器码 -> 裸 ELF64（无 libc）
│   ├── rosoto_pe.py       # 自研 Windows：同一 RosIR -> PE32+/COFF（无 CRT，kernel32 导入）
│   ├── rosoto_arm64.py    # 自研 AArch64：同一条 RosIR，只换发射层
│   ├── rosoto_opt.py      # RosIR 优化器（后端/平台无关）
│   ├── rosoto_cli.py      # 统一命令行：默认当前平台自研后端；C 仅显式交叉验证
│   ├── rosoto_fmt.py      # 官方格式化器
│   ├── rosoto_mt.py       # 多核任务运行时发射器（work-stealing）
│   ├── rosoto_mem.py      # 内存/引用运行时发射器（arena/slab/稳定引用/视图）
│   ├── rosoto_store.py    # 文件/存储运行时发射器（CRC32C/WAL/页存储/io_uring 文件 IO）
│   └── rosoto_uring.py    # io_uring 网络后端运行时发射器
└── tests/
    ├── run_tests.sh         # C 后端回归（16 项）
    ├── run_native_tests.sh  # 自研后端回归（52 项，含 AArch64 模拟器执行级验证）
    ├── run_win_tests.py     # Windows PE 回归（55 项：结构/执行/多核/chan/arena/数组/交叉验证）
    ├── test_corelib.sh      # mem/mt/store 运行时回归（34 项）
    ├── test_uring.sh        # io_uring 网络回归（26 项）
    └── single_core/         # multicore=false 单核降级测试夹具
```

## 快速开始

```bash
# 自研后端：Rosoto -> 裸 ELF64（无 libc / 无 gcc）
python3 tools/rosoto_native.py run examples/fib.ros
python3 tools/rosoto_native.py run examples/parfor_sum.ros   # 多核：raw clone()

# Windows：Rosoto -> PE32+（无 CRT，kernel32 导入）
python tools/rosoto_cli.py run examples/hello.ros --target win     # 产出 build/hello.exe
python tests/run_win_tests.py                                     # Windows 55 项回归

# C 后端（仅显式交叉验证/自举，不是产品后端）
python3 tools/rosoto.py run examples/hello.ros
python3 tools/rosoto.py run examples/parallel_sum.ros

# 网络 echo 服务器（当前网络 intrinsic 仍在 C 后端，另开终端 nc localhost 9000）
python3 tools/rosoto.py build examples/echo_server.ros --cc
./build/echo_server

# 回归测试（五套，共 183 项）
bash tests/run_native_tests.sh   # 自研后端 52 项（含 AArch64 模拟器执行级）
bash tests/run_tests.sh          # C 后端 16 项
bash tests/test_corelib.sh       # mem/mt/store 运行时 34 项
bash tests/test_uring.sh         # io_uring 网络 26 项
python tests/run_win_tests.py    # Windows PE 55 项（需在 Windows 上执行）
```

## 核心机制速览

**1. 多核是默认行为**，单核是显式选择 —— 在项目根目录 `Rosoto.toml`：

```toml
[core]
multicore = false    # parfor/spawn 编译期降级为串行，代码零改动、语义不变
threads   = 1
```

Linux 走 `clone()`，Windows 走 `CreateThread`，归约结果语义一致。

**2. 网络是运行时的一部分**，不是库：

```rosoto
fn on_data(c: net.Conn, data: []byte) -> net.Action {
    c.write(data)?          // 零拷贝回写 + 显式背压
    return net.Action.Keep
}
```

资源上限（`max_conns` / 缓冲区 / 背压策略）全部在 `Rosoto.toml` 声明，超限 fail-fast。
当前实现：C 后端 epoll / io_uring（Linux）；Windows IOCP 在 PLATFORM.md 候选 A。

**3. 无 GC**：所有权 + 借用检查 + 帧级 arena，析构确定性 —— 游戏帧循环无停顿。

**4. `struct` 值语义 + `enum`/`match` + `break`/`continue`**：

```rosoto
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

```rosoto
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

- `spawn`：Linux `clone()`、Windows `CreateThread`、C `pthread`；`join(h)` 取返回值。
- `chan[T]`：自研后端用**自旋锁 + `xchg` + yield**；C 后端用 `pthread_mutex/cond`；
  容量满/空时阻塞。
- `arena`：native 真实回卷 bump 指针；C 后端为纯作用域。
- `[core] multicore = false` 时 `spawn` 编译期退化为同步调用，`join` 直接取结果。

非 chan 程序不会带上通道运行库与 `SwitchToThread` 导入（按需发射，省体积）。

**6. 定长数组 `[N]T`（v0.6）**：

```rosoto
let mut a = [1, 2, 3, 4]
a[1] = 20
a[2] += 5
assert(len(a) == 4, "len")

let b = a          // 值语义拷贝：改 b[0] 不影响 a
b[0] = 100
print(a[0])        // 1

let i = 4
print(a[i])        // 越界：fail-fast（退出码 1，stderr 报错）
```

- 数值元素、栈上帧槽、值语义拷贝；下标支持动态变量与复合赋值。
- 越界默认 fail-fast（`Rosoto.toml [build] bounds_check = false` 可关闭）。
- `[N]T` 目前只支持函数内局部数组；作函数参数/返回值会**明确报错**（v0.6 边界）。

**7. 无 CRT 的 Windows 原生产物**：入口即 `main`，
导入仅 kernel32（`GetStdHandle/WriteFile/ExitProcess/VirtualAlloc/CreateThread/...`），
堆按 1MB 粒度提交，hello 仅 **7 KB 级**。

## 实测

### Linux（3 核容器）

| 负载 | 自研后端 | gcc -O2（C 后端） |
|---|---|---|
| fib(25) 递归 | 75025 ✓ | 75025 ✓（交叉验证） |
| divmod 160 行（正负/边界）| 全等 ✓ | 参考 |
| loop_sum 2 亿热循环 | 518ms | 158ms |
| parfor_sum 3 核 6M 任务 | 388ms（raw clone）| 153ms（pthread）|
| 单核降级 multicore=false | 结果不变 ✓ | 结果不变 ✓ |

### Windows（x64 / 20 逻辑核，本机实测）

| 负载 | PE 产物 | 时间（5 次最优） |
|---|---|---|
| hello | 7168 B | — |
| loop_sum 2 亿热循环 | 6144 B | 357.9 ms |
| parfor_sum 20 线程 6M | 14848 B | 196.1 ms |
| prime_parallel（10 万内素数） | 15872 B | 18.7 ms |
| t13_spawn（4 个任务） | 13824 B | — |
| t15_chan（2 生产者 + 有界通道） | 11264 B | — |
| t16_arrays（数组 + 越界检查） | 9216 B | — |

回归测试：**183 项全绿**（Windows 55 / 自研 Linux 52 / C 16 / corelib 34 / io_uring 26）。
Windows 的 55 项包含：PE 结构自检（仅 kernel32、无 CRT）、执行级语义、多核归约、
`spawn`/`join` 任务、`chan` 有界通道、`[N]T` 数组与越界 fail-fast、
arena 真实回收（1MB 上限）、单核降级、assert 失败路径，
以及与 Linux ELF 逐字节交叉验证。

> 未完成项、阻塞项、下一步排期见 **`HANDOVER.md`**；
> 全平台矩阵与讨论见 **`PLATFORM.md`**。

## 路线图

| 版本 | 内容 |
|---|---|
| v0.1 | **自研后端 x86_64 全链路**（RosIR/寄存器分配/指令编码/裸 ELF）+ C 后端 + epoll 网络 + 配置驱动降级 ✅ |
| v0.2 | `break`/`continue`/`struct`（值语义/嵌套/字段读写）+ `frameaddr` + 内联/LICM/CSE/展开/调度 + ARM64 发射器 + `enum`/`match` ✅ |
| v0.3 | **Windows x86_64 PE/COFF 后端（无 CRT）** + kernel32 导入 + DIR64 重定位 + CreateThread 多核 + 1MB 粒度提交 + Windows 回归 ✅ |
| v0.4 | **`spawn`/`join` 任务并行 + `arena { }` 帧级回收**（Linux/Windows/C 三链）✅ |
| v0.5 | **`chan[T]` 有界 MPMC 通道**（自旋锁 `xchg` + yield / C 条件变量）+ 运行库按需发射 + 内联标签冲突修复 ✅ |
| v0.6 | **定长数组 `[N]T`**：字面量/索引/复合赋值/`len`/值语义拷贝/越界 fail-fast（三链）✅ |
| **v0.7（当前）** | **用户定义 Result + `?` 错误传播**（native/PE/C）+ 严格范围证明 + worker 内联边界 + 产品默认自研后端 ✅ |
| v0.8 | `[]T` / `map`；Windows IOCP 网络；SIMD 自动向量化；macOS Mach-O/kqueue；wasm64 |
