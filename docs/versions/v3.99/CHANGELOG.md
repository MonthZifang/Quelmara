# v3.99 — 基准 24 项全覆盖 + C++ 接入 + 多语言数据驱动框架

- 日期：2026-11-03
- 任务：把 bench/speed 从"10 项 4 语言"推到"**24 项 × 全部语言**"，
  并为剩下的语言装好可扩展的接入框架。
- 影响面：`bench/speed/{python,cpp}/`（新增 24+24 个源文件）、
  `bench/speed/run.py`（数据驱动多语言）、`bench/speed/README.md`

## 一、Python 与 C++ 补齐到 24/24

* **Python 24 项**：作为"参考下限"。所有结果与 C 逐项一致
  （抽查 `ackermann 19` / `knapsack 9750` / `lcs 1498` / `fibiter 364822946`）。
* **C++ 24 项**：直接复用 C 的 `bench.h`（`-I bench/speed/c`），
  算法与 C 版逐字等价。实测 `c` vs `cpp` 的比值全是 **1×**（符合预期 ——
  同一份算法、同一套 -O2）。

## 二、多语言接入改成数据驱动

原来 `c` / `go` / `python` 各写一段 20 行的 `if lang == "x"`。加第 4 种就要
再复制一遍。现在是一张表：

```python
EXTRA_LANGS = {
    "rust": (".rs", _find("rustc"),
             lambda cc, src, out: [cc, "-O", "-o", out, src], False),
    "zig":  (".zig", _find("zig"),
             lambda cc, src, out: [cc, "build-exe", "-O", "ReleaseFast", ...], False),
    ...
}
```

加语言只改这张表。**找不到编译器就明确跳过并把原因写进结果**
（`[rust] 跳过：没有找到 rust 的编译器（rustc（rustup component））`），
不假装测过。

已登记 7 种（rust / zig / nim / d / ada / fortran + cpp 已实现），
`csharp` 单独说明为什么暂时不接：.NET 需要 `csproj` 工程，
`dotnet run` 的启动开销（数百 ms）会直接污染纳秒级计时。

## 三、当前差距（qlmc ELF 后端 vs gcc -O2，24 项里已测的 13 项）

| 基准 | 比值 | 归因 |
|---|---|---|
| `b10_ackermann` | **0.36×（快）** | 递归调用开销 qlmc 反而更低 |
| `b16_leibniz` | 1.21× | 浮点循环 |
| `b18_insertion` | 3.36× | 内存移动密集 |
| `b26_maxsub` | 4.25× | `idiv`（见 v3.98 的说明） |
| `b23_lcs` | **8.84×** | 滚动数组访存，最差项 |

**最需要改的是 `b23_lcs`（8.84×）** —— 它是纯数组读写，没有除法、没有浮点，
8.84× 只能是**地址计算/访存的指令数**问题。下一轮优先查这个。

## 四、纪律

* 每项基准必须**三语言算法逐字等价**，只打印"结果 + `T` + 纳秒耗时"。
* 每项都要核对校验和一致，否则比的是实现差异而不是编译器差异。
* **不假装测过**：没有编译器、没有源码的语言明确跳过。
