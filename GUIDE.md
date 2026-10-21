# Quelmara GUIDE —— 怎么用、怎么写、自举为什么还差 7/9（已完成 2/9）、性能对比

> 一份全景指南：给"想上手的人"讲怎么用工具链、给"想写程序的人"讲怎么写、
> 给"关心编译器本体的人"讲自举为什么还差 7/9（2/9 已完成）、给"关心快不快的人"讲性能对比。
> 语言细节看 `SPEC.md`，分步教程看 `TUTORIAL.md`，后端与优化器细节看 `BACKEND.md`，
> 自举路线细节看 `docs/SELFHOST.md`。

---

## 一、怎么用（工具链 5 分钟）

### 1.1 三条编译链

| 链路 | 产物 | 依赖 | 用途 |
|---|---|---|---|
| 自研 x86_64 ELF | 裸 Linux ELF64 | **无**（无 libc/gcc） | Linux 产品链 |
| 自研 PE/COFF | Windows PE（无 CRT） | **无**（仅 kernel32，用到网络再 +ws2_32） | Windows 产品链 |
| 自研 AArch64 | 裸 ELF（aarch64） | 无 | ARM/Linux；测试用模拟器执行级验证 |
| C99（交叉验证） | C 源码 → gcc | gcc/clang | **测试 oracle**，不是产品链 |

### 1.2 命令行（`quelmara` CLI）

```bash
Q=python tools/stage0/qlm_cli.py

$Q build app.qma --target win -o app.qex   # 编译（native/win/arm64/c/both）
$Q run app.qma --target win                # 编译并运行
$Q test tests --targets all                # 测试矩阵：可执行目标跑执行级 +
                                           #   arm64 走模拟器 + 跨后端输出逐字节比对
$Q fmt . --check                           # 官方格式化器（CI 可用 --check 挡板）
$Q bench app.qma --target win --runs 5     # 基准 + 回归对比（baseline/threshold）
```

- 默认目标 = 当前平台自研后端（Windows=win，POSIX=native）。
- `--dump-ir` 打印 QuIR（中间表示），`--no-opt` 关优化管线。
- 配置文件 `Quelmara.toml`（唯一全局开关）：

```toml
[core]
multicore = true     # 出厂默认：多核自动并行
threads = 0          # 0 = 自动取物理核数

[build]
bounds_check = true  # 越界 fail-fast（默认开；可证明安全的检查会被优化器消除）
```

**不需要手写循环拆分、不需要指定核心数**——`parfor` 自动按核数分块，
`spawn` 每任务自动调度；单核是显式 opt-out（`multicore = false`）。

### 1.3 质量门禁与测试

| 门禁 | 命令 | 口径 |
|---|---|---|
| 改名残留 | `python tools/dev/check_names.py` | 旧名零残留 + C 运行时符号自洽 |
| 原创性 | `python tools/dev/check_origin.py` | 仅标准库、无第三方产物 |
| 自举对拍 | `tests/lexdiff.py` 等 | 词法 99/99、声明级 AST 90/90（1 显式跳过）、QuIR 59/59（22 skip）、发射 10/10 |
| PE 回归 | `python tests/run_win_tests.py` | 113 项（执行级 + fail-fast + 单核降级 + v1.8 正/负夹具） |
| 自举进度 | `python tools/dev/selfhost_status.py` | 组件归属 / 对拍 / 行数占比 |
| CI | `.github/workflows/ci.yml` | Linux + Windows 双平台矩阵 |

---

## 二、怎么写（语言速览 + 三个真实应用）

### 2.1 语言核心（30 秒版）

```quelmara
module app

struct Point { x: int, y: int }

enum Shape {
    Circle(Point, int)
    Rect(Point, int, int)
}

fn area(s: Shape) -> int {
    match s {
        Shape.Circle(_, r)    { return 3 * r * r }
        Shape.Rect(_, w, h)   { return w * h }
    }
}

fn main() {
    let mut pts = vec[Point].new(2)        // 堆上变长数组
    let m = map[str]int.new(16)            // 开放寻址哈希表（语法 map[K]V，无逗号）
    m.set("area", area(Shape.Rect(Point{x: 0, y: 0}, 3, 4)))
    for k in m { print(k) }                // 遍历产出键
    if m.has("area") { print(m.get("area")) }
}
```

还有：`Result` + `?` 错误传播、`spawn`/`chan`/`select`（多核）、`arena` 块（帧级回收无 GC 停顿）、
位运算 `& | ^ ~ << >> >>>`、进制字面量 `0x/0b/0o`、子切片 `s[lo..hi]`、
`parfor`（自动并行归约）。**所有越界/类型错误一律 fail-fast**（退出码 1 + stderr 消息），
没有未定义行为的静默错。

### 2.2 应用一：文件分析（读 → 统计 → 写）

```quelmara
module report

import std.core                     // 标准库扁平合并（std/ 随编译器分发）

fn main() {
    let text = read_text("input.txt")            // 整文件读，失败 fail-fast
    let mut lines = 1
    let mut i = 0
    while i < len(text) {
        if text[i] == 10 { lines += 1 }          // 字节级扫描，text[i] 是 0..255
        i += 1
    }
    let out = "lines=" + lines.to_str()
    let n = write_text("report.txt", out + "\n") // 覆盖写，返回字节数
    print("written " + n.to_str())
    print(max2(lines, 0))                        // std/core 的函数直接可见
}
```

多文件组织：`import mymod` 加载主文件同目录的 `mymod.qma`；`import std.net`
加载标准库 `std/net.qma`。被导入文件的顶层 fn/struct/enum/test 全部扁平可见
（无命名空间前缀，重名报错；循环 import 报错；被导入文件不得定义 main）。

### 2.3 应用二：TCP echo 服务（原生 socket，无 CRT）

```quelmara
module echo

import std.net                          // listen/accept/send/recv/close_conn

fn main() {
    let srv = listen(19527)             // 绑定 0.0.0.0:port，Windows 走 ws2_32
    while true {
        let conn = accept(srv)          // 阻塞等待
        send(conn, recv(conn, 4096))    // 回显一包
        close_conn(conn)
    }
}
```

编译 `--target win` 后是 **8.7 KB 单文件**（无 CRT），Windows 上直接运行。
这是阻塞式第一格；SPEC 规划的 reactor（epoll/IOCP + 回调结构体）在其之上。

### 2.4 应用三：多核并行（不用手写分核）

```quelmara
fn main() {
    let mut buf = [0, 0, ... ]          // 定长数组，值语义
    parfor i in 0..200_000_000 acc += ... {
        // 自动按物理核数分块 + 归约；acc += 是目前唯一归约算子（v1.3 边界）
    }
}
```

### 2.5 当前边界（诚实清单）

| 能力 | 状态 |
|---|---|
| 多文件 import、文件读写、阻塞 TCP、多核、arena、Result/`?` | ✅ |
| 目录 API（exists/mkdir/列目录）、追加写 | ⬜ 下一步 |
| reactor 网络（epoll/IOCP + 回调） | ⬜ tcp_* 地基已通 |
| interface / impl | 🟡 v1.8 静态分发（契约 + 校验 + 方法调用）；动态分发未实现 |
| 所有权 / 借用检查 | 🟡 v1.8 只查 `rc[T]` 句柄（use-after-drop / double-free / move） |
| 用户泛型、闭包、FFI | ⬜ 规范已定，代码未写 |
| `vec[vec[T]]`、chan 载荷 8 字节、parfor 归约仅 `+=` | ⬜ 边界见 SPEC / `docs/GAPS.md` |

---

## 三、自举：为什么还差 7/9（已完成 2/9）

### 3.1 自举是什么、为什么必须做

**原则：编译器本体必须用 Quelmara 自己写。** Python 只允许当 stage-0 引导层，
按组件逐个退场——长期使用的每一行编译器最终都必须是 Quelmara（`qlm_opt.py` 这类
`.py` 不是"工具"，是内核组件的临时引导实现，退场目标就是 `bootstrap/opt/`）。

为什么现在还是 Python：**自举悖论**——需要先有一个能编译 Quelmara 的编译器，
才能用 Quelmara 重写编译器。stage-0 就是那个"先有的编译器"；
自举完成后 stage-0 全目录退场，编译器 100% 是 Quelmara 自己。

### 3.2 九个组件，2/9 已转正

| # | 组件 | stage-0（引导） | stage-1（目标） | 对拍口径 | 状态 |
|---|---|---|---|---|---|
| 1 | 词法 | `qlm.py::tokenize` | `bootstrap/lexer/` | 逐 token **92/92 全等** | ✅ |
| 2 | 语法（声明级 + 函数体） | `qlm.py::Parser` | `bootstrap/parser/` | AST 逐层全等（声明级 **87/87** ✅，函数体 🟡） | ✅/🟡 |
| 3 | 类型推断 | `qlm.py` 推断层 | `bootstrap/typeck/` | 负向夹具两阶段同类别报错 | ⬜ |
| 4 | AST→IR | `qlm_native.py::Lower` | `bootstrap/ir/` | QuIR 规范 diff | 🟡 骨架 |
| 5 | 优化器 | `qlm_opt.py` | `bootstrap/opt/` | 优化前后 QuIR diff | ⬜ |
| 6 | x86_64 编码 | `qlm_native.py::Codegen` | `bootstrap/codegen/x64/` | 反汇编逐指令 + 确定性 | 🟡 骨架 |
| 7 | ELF 写出 | `qlm_native.py` | `bootstrap/codegen/elf/` | 魔数/入口/确定性 | 🟡 骨架 |
| 8 | PE 写出 | `qlm_pe.py` | `bootstrap/codegen/pe/` | MZ/PE32+/导入表/确定性 | 🟡 骨架 |
| 9 | AArch64 | `qlm_arm64.py` | `bootstrap/codegen/a64/` | IR 架构无关 50/50 + 模拟器执行 | 🟡 骨架 |
| — | 固定点闭环 | — | 三轮固定点 | stage0→S1→S2 产物一致 | ⬜ 收官门禁 |

（C99 后端**不移植**——它只是交叉验证 oracle，永久保留在 stage-0。）

**"还差 7/9" 的准确含义**：第 1、2 号已完成并通过全等对拍；第 3-9 号七件里
六个有骨架、一个未动——**从"骨架"到"转正"缺的是真实的 Quelmara 实现**
（数千行）加逐层对拍门禁。**为什么不能快**：每一层都必须先过"与 stage-0 逐字节/
逐节点全等"的门禁才能切，typeck 还要求负向夹具在两阶段报同类别错误——
这是保证自举不破坏语言语义的代价，也是价值所在。

### 3.3 方法论：对拍门禁逐层切

1. **对拍先行**：每层转正前先有 stage-1 与 stage-0 的差异比较脚本
   （`tests/lexdiff.py` / `parsediff.py` / `irdiff.py` / `emitdiff.py`）。
2. **全等才切**：对拍全绿后，CLI 切到 stage-1 实现（输出标 `[qlm:stage1]`），
   stage-0 对应组件进入"仅对拍基准"状态。
3. **真自举闭环收官**：三轮固定点——stage0 编译 S1（Quelmara 写的编译器），
   S1 编译 S2，**S1 与 S2 的产物必须逐字节一致**——证明编译器已经能
   确定性地编译自己。
4. **退场**：全部 9 组件转正 + 固定点通过后，`tools/stage0/` 全目录退役。

### 3.4 路线图

```
parser 函数体（🟡 进行中）
  → typeck（负向夹具体检）
  → AST→IR → 优化器 → x64 编码 → ELF/PE 写出（骨架已就绪，逐层转正）
  → AArch64（IR 架构无关对拍已就绪）
  → 三轮固定点闭环 → stage-0 退役 → 自举 9/9
```

---

## 四、性能：与 C、与 Go

### 4.1 与 gcc -O2（C 后端做 oracle，同机对照）

**Linux（3 核容器）**：

| 负载 | 自研后端 | gcc -O2 | 说明 |
|---|---|---|---|
| loop_sum 2 亿热循环（取模） | **11–13 ms** | 158 ms | v0.9 闭式折叠把归约循环整体折叠——**反超 gcc**（特化优化） |
| loop_sum 2 亿热循环（折叠前） | 518 ms | 158 ms | 差距 = 向量化/调度 |
| parfor_sum 3 核 6M 任务 | 388 ms | 153 ms | 差距 = 内联深化 |

**Windows（20 逻辑核，PE 产物）**：

| 负载 | 产物体积 | 时间（5 次最优） |
|---|---|---|
| hello | 6 144 B | 冷启动直入 main |
| loop_sum 2 亿热循环 | 6 144 B | 357.9 ms |
| parfor_sum 20 线程 6M | 14 848 B | 196.1 ms |
| prime_parallel（10 万内素数） | 15 872 B | 18.7 ms |

**越界安全检查的代价（v1.3 通用优化后）**：1.92 亿次定长数组读写，
`bounds_check=true` + 范围证明消除 = **642.7 ms**，`bounds_check=false`（无检查上限）
= **641.9 ms**——**检查开销 19.3% → 0.1%**，安全性不再有性能代价。

**产物体积**：hello **6 KB**、fib **6.7 KB**、game_loop **20 KB**——全部无 CRT、
无运行时库；冷启动直入 main。

### 4.2 与 Go（定性 + 待办）

**Go 尚未做同机对照**（TODO：固定 CPU 的 bench 脚本 + `bench/baseline.json` 维护），
这里只给不依赖数字的结构性对比：

| 维度 | Quelmara（自研链） | Go |
|---|---|---|
| GC | **无 GC**——arena 帧级回收，确定性，无停顿 | 并发 GC，有 STW 窗口 |
| 产物 | 裸 PE/ELF，**6–20 KB**，无运行时 | 静态 ~1–2 MB+，含 runtime |
| 并行模型 | `parfor` 静态分块 + `spawn` 一任务一线程（work-stealing 规划中） | goroutine + work-stealing（成熟） |
| 网络 | 阻塞第一格；epoll/IOCP reactor 规划中 | netpoller 成熟 |
| 向量化 | ⬜ 规划中（SSE2→AVX2） | 编译器自动向量化有限，SSA 后端成熟 |
| 优化器 | QuIR 级内联/CSE/LICM/展开/调度/范围证明 | 成熟 SSA 后端 |

**诚实的结论**：
- **对 C**：通用负载目前**落后** gcc -O2（向量化/调度/内联深度差距，loop_sum 类
  规范归约已反超）；差距项全部在 `BACKEND.md` 规划表里，最重的两件是
  SIMD 自动向量化与内联深化。
- **对 Go**：**产物体积与无 GC 确定性是结构性优势**；生态/成熟度/优化器深度
  是结构性劣势。同机数字对比列入待办（CI bench 基线）。

### 4.3 性能路线图

```
已做：modsum 闭式折叠（反超 gcc 的特化）· 范围证明越界消除（通用）
规划：SIMD 自动向量化（2-4x）· 内联深化（LTO 级）· 尾调用 · 布局优化
      · @simd 显式向量提示 · 与 Go/C 的同机对照 bench 基线
```

---

## 五、延伸阅读

| 文档 | 内容 |
|---|---|
| `SPEC.md` | 语言规范（唯一权威） |
| `TUTORIAL.md` | 分步教程（含每步可运行示例） |
| `SHOWCASE.md` | 能力展示（v1.0–v1.3 全特性代码） |
| `BACKEND.md` | 后端架构、优化器、实测基线 |
| `docs/SELFHOST.md` | 自举路线与组件退场表 |
| `docs/ORIGINALITY.md` | 原创性声明 |
| `CHANGELOG.md` | 版本史（唯一权威记录） |
| `HANDOVER.md` | 工程现状、边界与教训 |
