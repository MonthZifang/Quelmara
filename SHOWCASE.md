# Rosoto 代码展示（SHOWCASE）

> 一页看懂 Rosoto 长什么样、能干什么、跑多快。所有代码都是仓库里可直接运行的示例，
> 输出均为实测。想系统学习请看 **`TUTORIAL.md`**；语言细节看 `SPEC.md`。

---

## 1. 你好，原生机器码

```rosoto
// examples/hello.ros
module hello

fn main() {
    print("hello, rosoto")
}
```

```bash
python3 tools/rosoto_native.py run examples/hello.ros
# hello, rosoto
```

产物是**裸 ELF64**（无 libc、无 gcc 参与链接）；Windows 上产出 PE32+（无 CRT，
只导入 kernel32）。hello 的 PE 产物 **7 KB**。

---

## 2. 热循环：闭式折叠赢过 gcc -O2

```rosoto
// examples/loop_sum.ros —— 2 亿次迭代，魔数取模
module loop_sum

fn work(n: int) -> int {
    let mut acc = 0
    let mut i = 0
    while i < n {
        acc = acc + (i * 7) % 13
        i = i + 1
    }
    return acc
}

fn main() {
    print(work(200_000_000))
}
```

自研优化器识别出「模数算术级数求和」规范形态：gcd(7,13)=1 ⇒ 连续 13 项余数恰是
0..12 的排列，2 亿项整体折叠成常量 + 5 项尾数——**结果 1199999988，全程 13 ms**。

| | Rosoto 自研 | gcc -O2（C 后端） |
|---|---|---|
| loop_sum 2 亿 | **11–13 ms** | 231–235 ms |

---

## 3. 多核 parfor：写循环就并行

```rosoto
// examples/parfor_sum.ros —— 6M 任务、3 核归约
module parfor_sum

fn heavy(i: int) -> int {
    let mut acc = 0
    let mut k = 0
    while k < 40 {
        acc = acc + (i * 31 + k) % 97
        k = k + 1
    }
    return acc
}

fn main() {
    let mut total = 0
    parfor i in 0..6_000_000 {
        total += heavy(i)
    }
    print(total)
}
```

`parfor` 自动静态分块 + 线程本地归约（Linux `clone()` / Windows `CreateThread`）。
`total +=` 是归约变量，结果确定性一致。**35 ms（gcc pthread 版 131 ms）**。
在 `Rosoto.toml` 写一行 `multicore = false`，同一份代码编译期降级为串行，语义不变。

---

## 4. struct 值语义 + enum/match 穷尽检查

```rosoto
// examples/inventory.ros（节选）——工程建模
struct Item {
    name: str
    qty: int
    price: int
}

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

- 结构体按值拷贝、按值传参——副作用不外泄；
- `match` 必须穷尽所有变体，漏写编译不过；
- 同一份代码在 x86_64 ELF / Windows PE / AArch64 / C 四条链交叉验证。

---

## 5. Result + `?`：错误不许静默吞

```rosoto
// examples/（回归 tests/t17_result.ros 同源）
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
    let value = parse(n)?        // 出错直接把 Err 一路上抛
    return Result.Ok(value + 1)
}
```

`?` 在三后端（自研 ELF / Windows PE / C）语义一致；`Ok`/`Err` 可任意声明顺序，
泛型 `result[T, E]` / `option[T]` 已受控单态化：

```rosoto
let maybe = option[int].some(42)
let v = match maybe {
    Option.Some(x) => x
    Option.None => -1
}
```

---

## 6. 任务并行 spawn/join + 有界通道 chan[T]

```rosoto
fn producer(ch: chan[int], n: int) {
    let mut i = 0
    while i < n {
        ch.send(i)
        i = i + 1
    }
}

fn main() {
    let ch = chan[int].open(64)      // 有界 MPMC：满/空自动阻塞
    let h = spawn producer(ch, 1000)
    let mut sum = 0
    let mut i = 0
    while i < 1000 {
        sum += ch.recv()
        i = i + 1
    }
    join(h)
    print(sum)                       // 499500
}
```

自研后端通道 = 自旋锁 `xchg` + yield；`spawn` 一任务一线程，`join(h)` 取返回值。
单核配置下 `spawn` 编译期退化为同步调用——测试夹具 `tests/single_core/` 全绿验证。

---

## 7. 定长数组 [N]T 与切片 []T

```rosoto
let mut a = [1, 2, 3, 4]
a[1] = 20
a[2] += 5
assert(len(a) == 4, "len")

let b = a            // 值语义拷贝：b[0] 不影响 a[0]
b[0] = 100
print(a[0])          // 1

let i = 4
print(a[i])          // 越界 → fail-fast，退出码 1，stderr 报错
```

切片 `[]T` = {ptr, len} 两字零拷贝视图（聚合 ABI），可作参数/返回值，
动态长度越界同样 fail-fast。

---

## 8. arena：帧级回收，没有 GC 停顿

```rosoto
fn frame() {
    arena {
        let msg = "sum=" + 499500.to_str()
        assert(msg == "sum=499500", "arena msg")
    }                  // bump 指针整体回卷：块内分配一次性回收
}
```

无 GC、析构确定性——游戏帧循环里没有随机停顿。1 MB 堆上限下可以跑完 4 MB
分配量的程序（回收真实生效，回归有专项测试）。

---

## 9. 性能与产物一览

**基准**（Xeon E5-2666 v3 / WSL2 / gcc 15.2，`tests/bench.sh` best-of-3，2026-10-20）：

| 负载 | Rosoto 自研 | gcc -O2 / pthread | 倍率 |
|---|---|---|---|
| loop_sum 2 亿热循环 | **13 ms** | 231 ms | 17.8x |
| parfor_sum 6M 任务 / 3 核 | **35 ms** | 131 ms | 3.7x |

**Windows PE 产物体积**（无 CRT）：

| 程序 | 大小 |
|---|---|
| hello | 7,168 B |
| loop_sum | 6,144 B |
| parfor_sum（20 线程） | 14,848 B |
| chan / arrays / spawn | 9–14 KB |

**质量**：五套回归 **198 项全绿**（Windows PE 61 / 自研 Linux 61 / C 16 /
corelib 34 / io_uring 26）+ 优化器差分模糊 180 例。

---

*下一步：`TUTORIAL.md`（上手教程）→ `SPEC.md`（语言规范）→ `BACKEND.md`（后端与优化器）→ `HANDOVER.md`（工程现状与路线）*
