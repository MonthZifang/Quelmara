# Quelmara 代码教程（TUTORIAL）

> 从零上手 Quelmara：环境 → 第一个程序 → 语法 → 多核 → 工具链 → 避坑。
> 全部命令在仓库根目录执行。代码示例均可直接运行。
> 看效果请先翻 **`SHOWCASE.md`**；查语言细节看 `SPEC.md`。

---

## 0. 环境准备

| 平台 | 需要 | 说明 |
|---|---|---|
| Linux | Python 3.10+ | 自研后端直接产出裸 ELF64，**不需要 gcc** |
| Windows | Python 3.10+ | 自研后端产出 PE32+（无 CRT）；C 后端交叉验证需 WSL gcc |
| AArch64 | Python 3.10+ | 自研 ELF 发射层已就绪（模拟器验证，待真机） |

```bash
git clone https://github.com/MonthZifang/Quelmara.git
cd Quelmara
# 验证安装：跑一个示例
python3 tools/stage0/qlm_native.py run examples/hello.qma
# hello, quelmara
```

---

## 1. 第一个程序

创建 `my.qma`：

```quelmara
module my

fn main() {
    print("hello")
    print(1 + 2 * 3)
}
```

```bash
python3 tools/stage0/qlm_native.py run my.qma     # 编译 + 立即运行
python3 tools/stage0/qlm_native.py build my.qma -o build/my   # 只编译
./build/my
```

规则先记三条：
- 文件第一行是 `module 名`；
- **没有分号**，换行分隔语句；
- 一个 `.qma` 文件 = 一个模块 = 一个命名空间。

---

## 2. 变量与类型

```quelmara
fn main() {
    let x = 10              // let 默认不可变
    let mut y = 0           // mut 显式声明可变
    y = y + x
    print(y)

    let ok = true           // bool
    let name = "quelmara"     // str（UTF-8 不可变）
    print(name + " says " + ok.to_str())
}
```

- `int` 是 64 位有符号；`bool` / `str` 一等类型，`str` 是内容比较；
- 静态类型 + 局部推断：`let x = 10` 自动是 `int`；
- 类型标注写法：`fn f(a: int, b: str) -> bool { ... }`；
- 顶层 `const`（v1.1）只接受字面量（含进制前缀与负号），解析期内联：
  `const MAX_RETRY = 3`。

---

## 3. 表达式与控制流

```quelmara
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
    let mut i = n
    while i > 0 {
        if i == 2 {
            i = i - 1
            continue          // continue / break 均支持
        }
        print(i)
        i = i - 1
    }

    for k in 0..n {           // 半开区间 [0, n)
        print(k)
    }
}
```

`match` 是表达式，必须穷尽（编译期检查）：

```quelmara
enum Shape {
    Circle(radius: int)
    Rect(w: int, h: int)
}

fn area(s: Shape) -> int {
    return match s {
        Shape.Circle(r) => 3 * r * r
        Shape.Rect(w, h) => w * h
    }
}
```

位运算与进制字面量（v1.1）：

```quelmara
let flags = 0b1010 & 0b0110     // & | ^ ~ << >> >>>（>>> 为逻辑右移）
let addr  = 0xFF00 | 0x00FF
print(-8 >> 1)                  // -4（算术右移）
print(-8 >>> 1)                 // 按无符号解释的逻辑右移
```

注意：优先级是 Quelmara 自定义层次（`| < ^ < & < 比较 < 移位 < 加减 < 乘除`），
与 Go / Python 都不同，写代码按 `SPEC.md` §1.1 的表，不要按旧习惯猜。

---

## 4. 函数

```quelmara
fn add(a: int, b: int) -> int {
    return a + b
}

fn main() {
    print(add(2, 3))     // 5
}
```

- 递归、传参按值（struct 也是按值拷贝，副作用不外泄）；
- 函数可以互相调用，小函数会被内联进调用点（优化器自动做）。

---

## 5. struct：值语义建模

```quelmara
struct Item {
    name: str
    qty: int
    price: int
}

fn main() {
    let mut it = Item { name: "apple", qty: 3, price: 5 }
    it.qty += 10              // 字段读写 / 复合赋值
    print(it.qty)             // 13

    let copy = it             // 按值拷贝
    copy.qty = 0
    print(it.qty)             // 13（copy 的修改不影响 it）
}
```

---

## 6. 错误处理：Result + `?`

```quelmara
enum Result {
    Ok(value: int)
    Err(error: str)
}

fn parse(n: int) -> Result {
    if n < 0 {
        return Result.Err("negative")
    }
    return Result.Ok(n)
}

fn add_one(n: int) -> Result {
    let v = parse(n)?         // Err 直接一路上抛，不静默吞错
    return Result.Ok(v + 1)
}

fn main() {
    let r = add_one(5)        // Ok(6)
    let e = add_one(-1)       // Err("negative")
}
```

已落地边界（超出会明确报错）：`Result` 需为两个单载荷变体
`Ok(v)` / `Err(e)`，载荷限标量 int/bool/str；`?` 所在函数返回同一 Result。

`option[T]` 同理可用（int/bool/str）：

```quelmara
let m = option[int].some(42)
let v = match m {
    Option.Some(x) => x
    Option.None => -1
}
```

---

## 7. 数组、切片与 vec

```quelmara
fn main() {
    let mut a = [1, 2, 3, 4]
    a[1] = 20
    a[2] += 5
    print(len(a))             // 4

    let b = a                 // 值语义拷贝
    b[0] = 100
    print(a[0])               // 1

    print(a[1..3])            // 子切片 [20, 30]：左闭右开，零拷贝视图

    let mut i = 0
    while i < len(a) {
        print(a[i])           // 动态下标
        i = i + 1
    }
}
```

- 越界默认 **fail-fast**（退出码 1）；`Quelmara.toml` 里
  `[build] bounds_check = false` 可关闭（越界即 UB，慎用）；
- 子切片 `a[lo..hi]`（v1.1）：切片/数组是零拷贝视图（写视图会写穿原数组），
  `str` 切片是拷贝（str 不可变）；
- `[N]T` 作函数参数/返回值自 **v1.2** 起支持（值语义拷贝 + 隐藏出参，
  自研后端；C 后端会明确拒绝）——函数内改动不外泄，与 struct 一致；
- 切片 `[]T`（{ptr, len} 两字零拷贝视图）与 `slice_of(a)` 仍然是传大块数据的轻量选择。

变长数组 `vec[T]` 与集合遍历（v1.2）：

```quelmara
fn main() {
    let v = vec[int].new(4)   // 堆上变长数组，容量不足自动 2 倍扩容
    v.push(10)
    v.push(20)
    for x in v { print(x) }   // vec 按下标序遍历

    let m = map[str]int.new(16)
    m.set("apple", 3)
    for k in m { print(k) }   // map 产出键（顺序实现定义，不要依赖）
}
```

- `vec` 元素支持标量 / struct / enum（v1.3 起，按值拷贝进出）；空表 `pop()` / 越界 `get/set` fail-fast；
- 遍历期间不要修改集合（扩容/墓碑会导致未定义行为，SPEC 已写明）。

---

## 8. 多核：parfor / spawn / chan

### 8.1 parfor —— 数据并行 + 归约

```quelmara
fn main() {
    let mut total = 0
    parfor i in 0..1_000_000 {
        total += f(i)         // += 是归约变量，多线程结果确定性一致
    }
    print(total)
}
```

- 边界需编译期常量；归约只支持 `+=`；
- 运行时静态分块 + 线程本地累积，Linux 用 `clone()`、Windows 用 `CreateThread`。

### 8.2 spawn / join —— 任务并行

```quelmara
fn square(x: int) -> int {
    return x * x
}

fn main() {
    let h = spawn square(7)
    print(join(h))            // 49
}
```

### 8.3 chan[T] —— 有界 MPMC 通道

```quelmara
fn producer(ch: chan[int], n: int) {
    let mut i = 0
    while i < n {
        ch.send(i)            // 满则阻塞
        i = i + 1
    }
}

fn main() {
    let ch = chan[int].open(64)
    let h = spawn producer(ch, 10)
    let mut sum = 0
    let mut i = 0
    while i < 10 {
        sum += ch.recv()      // 空则阻塞
        i = i + 1
    }
    join(h)
    print(sum)                // 45
}
```

### 8.4 单核开关

```toml
# Quelmara.toml
[core]
multicore = false    # parfor/spawn 编译期降级串行，代码零改动
threads   = 1
```

---

## 9. arena：批量分配、整体回收

```quelmara
fn main() {
    arena {
        let msg = "sum=" + 45.to_str()
        print(msg)
    }                 // 块结束 bump 指针整体回卷，无 GC
}
```

适合游戏帧循环：块内随便分配，帧末一次性回收，析构确定性、无停顿。
对象不得逃逸出 arena 块（越界使用是语义错误）。

---

## 10. 工具链速查

```bash
# 自研后端（产品路径）
python3 tools/stage0/qlm_native.py run   examples/hello.qma          # 编译+运行
python3 tools/stage0/qlm_native.py build examples/hello.qma -o build/hello
python3 tools/stage0/qlm_native.py build examples/hello.qma --dump-ir  # 看 QuIR

# Windows（在 Windows 上）
python tools/stage0/qlm_cli.py run examples/hello.qma --target win   # 产出 build/hello.exe

# C 后端（仅交叉验证/自举，不是产品后端）
python3 tools/stage0/qlm.py build examples/hello.qma --cc

# 性能基准（best-of-3）
bash tests/bench.sh

# 回归测试（五套 + 四个自举对拍脚本；各版本项数以 CHANGELOG.md 为准）
bash tests/run_native_tests.sh        # 自研后端（含 AArch64 模拟器执行级）
bash tests/run_tests.sh               # C 后端
bash tests/test_corelib.sh            # mem/mt/store 运行时
bash tests/test_uring.sh              # io_uring 网络
python tests/run_win_tests.py         # Windows PE（需在 Windows 上执行）

# 自举对拍（stage-0 vs stage-1，详见 docs/SELFHOST.md）
python tests/lexdiff.py               # 词法逐 token
python tests/parsediff.py             # 声明级 AST
python tools/dev/selfhost_status.py   # 自举进度总览
```

---

## 11. Quelmara.toml 常用配置

```toml
[core]
multicore = true     # 多核默认开
threads   = 0        # 0 = 自动（物理核数）
affinity  = "none"   # none | compact | scatter | [0,1,2]

[build]
opt          = "speed"
bounds_check = true  # 数组越界 fail-fast

[memory]
heap_limit_mb = 512

[net]                # 网络资源上限（io_uring/epoll 后端）
max_conns    = 1000000
backpressure = "drop"   # drop | close | block
```

配置是**全局唯一开关**：多核降级、线程数、堆上限、背压策略都在这一处声明。

---

## 12. 避坑清单

| 坑 | 说明 |
|---|---|
| 位运算优先级与 Go/Python 不同 | `\| < ^ < & < 比较 < 移位`，按 SPEC §1.1 写，别猜 |
| map 遍历顺序是实现定义 | 按桶序，随插入/删除/扩容变化；测试只校验内容与计数 |
| 遍历期间不要修改集合 | push/del 触发扩容或墓碑变化 = 未定义行为 |
| vec 元素类型 | 标量（各占 1 槽）/ struct / enum（v1.3，按值拷贝）；`vec[vec[T]]` 仍不支持，嵌套请扁平化 |
| `[N]T` 作参数/返回值仅自研后端 | C 后端（仅交叉验证）明确拒绝；跨链代码用 `[]T` |
| `parfor` 归约只支持 `+=` | 其他共享写法会报错（竞态语义不明确） |
| `parfor` 区间需编译期常量 | `0..N` 的 N 必须能编译期求值 |
| `Result` 需为 Ok/Err 两变体 | 载荷限标量；结构体载荷暂不接受 |
| `?` 只能用在返回同款 Result 的函数里 | 语义不对会编译报错 |
| `match` 必须穷尽 | 漏分支编译不过（这是特性不是麻烦） |
| arena 对象不得逃逸出块 | 块末整体回收，逃逸 = use-after-free |
| str 不可变 | 拼接产生新串（arena/轮转缓冲池管理） |
| 非法输入一律 fail-fast | 数组/str 越界、`to_int` 非法输入都是退出码 1，不是静默 0 |

---

## 13. 接下来读什么

| 文档 | 内容 |
|---|---|
| `SHOWCASE.md` | 代码展示 + 性能实测 |
| `SPEC.md` | 语言规范全文（词法/类型/多核/网络/配置） |
| `BACKEND.md` | 自研后端架构、QuIR、优化器目录 |
| `PLATFORM.md` | 全平台矩阵与移植成本 |
| `HANDOVER.md` | 工程现状、未完成项、路线图 |
| `CHANGELOG.md` | 版本更新日志（回归项数的权威记录） |
| `docs/SELFHOST.md` | 自举路线、组件退场表与对拍门禁 |
| `docs/EXTENSIONS.md` | 扩展名规范（`.qma`/`.qex`/`.qel`） |
| `docs/ORIGINALITY.md` | 原创性声明与依赖清单 |

祝玩得开心。Issues 欢迎提。
