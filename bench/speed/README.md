# `bench/speed/` —— Quelmara vs C / Go / Python 同题基准

四份**同一道题**的实现，放在一起量语言本身的速度，而不是各家的库。
每个基准都打印一个校验和，**四个语言的输出必须逐字节相同** —— 不同就说明有一份
写错了，这时时间数字一概不看。

实测结果见 [`RESULTS.md`](RESULTS.md)。

## 目录

```
bench/speed/
  run.py              语言基准驱动器（编译 + 计时 + 校验 + 出表）
  compiler.py         编译器本身：冷编译 / 增量 / 大型源文件的时间与内存
  quelmara/*.qma      Quelmara 版（用 qlmc 编译）
  c/*.c               C 版（zig cc / gcc / clang）
  go/*.go             Go 版
  python/*.py         Python 版
  RESULTS.md          实测数字（含机器、口径、结论）
```

## 怎么跑

```bash
# 语言基准（默认 5 次取最小）
python bench/speed/run.py

# 只跑某几个 / 某几个语言 / 直接出 markdown 表
python bench/speed/run.py --only b1_int b7_sort
python bench/speed/run.py --langs quelmara go
python bench/speed/run.py --markdown

# 编译器本身
python bench/speed/compiler.py --sizes 200 1000 5000
```

前置条件：

| 语言 | 需要什么 | 没有会怎样 |
|---|---|---|
| Quelmara | `build/qlmc.exe`（自举产物） | 该列跳过，并提示自举命令 |
| C | `CC` 环境变量，或 `zig cc` / `gcc` / `clang` | 该列跳过 |
| Go | `go` 在 PATH | 该列跳过 |
| Python | 就是跑 `run.py` 的解释器 | — |

自举出 `qlmc.exe`：

```bash
python tools/stage0/qlm_cli.py build bootstrap/qlmc/qlmc.qma --target win -o build/qlmc.exe
```

## 十个基准

| id | 覆盖 | 规模 |
|---|---|---|
| `b1_int` | 整数运算 + 热循环 | 2000 万次 |
| `b2_float` | 浮点运算（调和级数） | 500 万项 |
| `b3_recursion` | 递归调用 | `fib(30)`，约 270 万次调用 |
| `b4_array` | 数组写入 + 顺序/跨步遍历 | 200 万元素 |
| `b5_string` | int→str→int | 20 万次 |
| `b6_hash` | 哈希表插入 + 查找 | 10 万 + 10 万 |
| `b7_sort` | 手写快排 | 20 万个伪随机 int |
| `b8_threads1` | 并发基线（单线程） | 1.6 亿次 |
| `b8_threads4` | 并发（4 线程，总量相同） | 4 × 4000 万次 |
| `b9_json` | JSON 解析 | 2590 字节文档 × 2000 遍 |

## 三条口径（不看会误读数字）

1. **计时取 N 次里的最小值。** 本机开着 VBS（虚拟化安全），噪声 ±50%，
   单次数字没有意义，最小值是唯一稳的统计量。**只做同表横向比较，别跨表比。**

2. **手写同一套算法，不用各家的库。** 哈希表和快排都是自己写的开放寻址 / 快排，
   JSON 也是自己写的递归下降。原因：qlmc 的内建 `map` 是**线性扫描**，
   拿它跟 Go 的 map 比会变成量算法差异；而拿 Go 的 stdlib JSON 跟手写扫描器比
   同样不公平。**这一节的数字代表"语言的算术/访存/调用开销"，不代表"标准库好不好用"。**

3. **`b8_threads4` 里 Python 那一列量的是 GIL，不是并行能力。** CPython 的线程
   对 CPU 密集任务不并行。要看 Python 的真实并行得用 `multiprocessing`，
   但那已经不是"同一份程序"了，所以这里保留 `threading` 并在结果里注明。

## 没量的（qlmc 目前做不到，不是没测）

| 项目 | 为什么 |
|---|---|
| 文件处理 | qlmc **没有文件 I/O 内建**（只有 `file_exists`）。要读文件得走 `@ffi` 调 `CreateFileA`/`ReadFile`，那是写一遍 Win32 胶水，不是基准。stage-0 侧有 `read_file`，但对比就不是同一条链路了 |
| HTTP 请求 | qlmc **没有 socket 内建**。stage-0 有 `net_serve`，qlmc 没有 |
| 泛型 / 接口 / 宏 的编译开销 | qlmc 还没实现这些特性 |

这三条在 `docs/07-gaps.md` 里都有记录。

## 编译器那一节（`compiler.py`）

量的是**两条链路**，不是四个语言：

- **stage-0**：`tools/stage0/qlm_cli.py`，Python 写的引导编译器，**有增量缓存**。
  冷编译用 `QLM_NO_CACHE=1` 关掉缓存，热编译就是再跑一次（缓存命中）。
- **qlmc**：`build/qlmc.exe`，Quelmara 自己写的 stage-1 编译器，**没有增量模式**
  （每次全量重编），所以"增量"那格对它是 N/A —— 这是事实，不是漏测。

峰值内存用 `GetProcessMemoryInfo` 每 2 ms 采一次峰值工作集。stage-0 是 Python
进程，数字里含解释器本身（20 MB 起步），这也要算进去看。
