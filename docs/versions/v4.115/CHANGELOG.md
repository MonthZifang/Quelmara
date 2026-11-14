# v4.115 — 基准公平性审计：消除整负载编译期折叠 + b54 实现对齐

- 日期：2026-11-14
- 性质：基准源码公平性修正（非编译器改动）
- 影响面：bench/speed 的 c/cpp/zig/rust/fortran/quelmara 源码

## 问题一：4 项基准的参照实现被整负载折叠，比值无意义

审计方法：对 v4.113 归档的 76 个 C 二进制做反汇编（`tailret_full_bins/c_*`），
找"计时区间内无循环/无工作函数"的项，再逐语言编译运行确认。

**b36_call / b53_thread_sim / b58_rec_sum / b71_sum_squares** 的 C 版 main 里
**一条跳转都没有**——GCC -O2 把整个负载算成编译期常量（闭式求和/常量递归），
运行时 0.01ms。v4.113 表里 b36 的 9086×、b53 的 2315×、b58 的 206×、b71 的
165× 全部是"quelmara 真干活 vs C 不干活"的假比值。

逐语言审计矩阵（✗=被折叠，OK=真实执行）：

| 语言 | b36 | b53 | b58 | b71 | 检测手段 |
|---|---|---|---|---|---|
| C（gcc -O2） | ✗ | ✗ | ✗ | ✗ | 反汇编：main 无跳转，工作函数消失 |
| C++（g++ -O2） | ✗ | ✗ | ✗ | ✗ | 运行 <1µs |
| C（zig cc/clang） | ✗ | ✗ | ✗ | ✗ | 运行 <1µs（**volatile 边界也挡不住**） |
| Zig ReleaseFast | ✗ | ✗ | ✗ | ✗ | 运行 <1µs（volatile 加载/noinline/doNotOptimizeAway(&n) 全被穿透） |
| Rust -O | ✗ | ✗ | ✗ | OK | 运行 <1µs；**black_box(边界) 无效**——LLVM 对运行时边界仍做闭式代换 |
| Fortran -O2 | ✗ | ✗ | OK | ✗ | 运行 <1µs |
| Go | OK | OK | OK | OK | 运行 ms 级 |
| Java | OK | OK | OK | OK | 运行 ms 级 |
| C# | 待 CI | 待 CI | 待 CI | 待 CI | 本机无 dotnet，未审计 |
| quelmara | OK | OK | OK | OK | 无折叠优化，真实执行 |

关键发现：**LLVM 系（clang/Rust/Zig）即使边界是运行时值，也会把等差/平方和
循环代换成运行时闭式计算**（反汇编可见 `mul+shld` 直接算 n(n-1)/2）。
所以"把边界变 opaque"不够，barrier 必须在**循环/递归内部**作用于累加器。

## 修复模式（零指令 barrier，算法与校验和不变）

| 语言 | 手段 | 位置 |
|---|---|---|
| C / C++ | `__asm__ volatile("" : "+r"(r) :: "memory")` | b36 add3 结果；b53 work 每轮 s；b58 rec_sum 每层结果；b71 每轮 acc |
| Rust | `std::hint::black_box(...)` | 同上 |
| Zig | `std.mem.doNotOptimizeAway(x)`（可移植，std 按架构发 asm） | 同上 |
| Fortran | `integer(kind=8), volatile :: n`（gfortran 不做闭式代换，边界 opaque 即可） | b36/b53/b71 循环边界 |

空 asm/black_box 不发射指令，只让值对优化器 opaque；循环必须逐轮执行。
边界常量全部保留原样（最小 diff）。b58 的 barrier 在递归内部，顺带挡住
GCC 尾调用优化——C 现在跑真实递归，与 quelmara 的 v4.113 循环化形成
"同一算法、不同编译器策略"的正当对比。

## 问题二：quelmara b54_merge_sort 实现与 C 不对等

C/Go/Rust/Zig 版都在 main **预分配一次 tmp 传入**；quelmara 版每次 merge
都 `vec.new(0)` + push 扩容——O(n log n) 次额外分配/扩容，不是同一道题。
改为 main 预分配 tmp（计时区外 push(0) 填长度，对应 C 的 malloc）并传入，
merge 用 set 不用 push，回拷循环用 k（与 C 一致）。

## 验证（23 项全 PASS）

- 18 个修复项（c×4、cpp×4、zig×4、rust×3、fortran×3）+ zig cc 编 C×4 + quelmara b54：
  **校验和全部不变**（50000005000000 / 100000000000000 / 5000500000 / 999998 / 37），
  且全部恢复真实执行（>100µs 门槛）。
- 本机修复后参考值（min of 1，仅供量级判断，非正式跑分）：
  C b36 15.3ms、b53 12.4ms、b58 2.8ms、b71 1.7ms；
  zig cc b36 10.2ms、b53 10.2ms、b58 8.7ms、b71 1.7ms。
- quelmara b54：123.66ms（v4.113 表）→ **37.0ms**（实现对齐后，旧默认编译器），
  校验和 37 不变。剩余差距待编译器优化版基线重测。
- 编译器零改动：VERSION/qlm_cli.py 版本号 → 4.115.0；自举不受影响。

## 对统计口径的影响

- b36/b53/b58/b71 的跨语言比值自本版起才有意义；v4.113 及以前表中这 4 项的
  比值（9086×/2315×/206×/165×）**作废**，几何平均等汇总统计需重算。
- b54 的 quelmara 列自本版起才是与 C 同题的成绩。
- C# 四项待 CI windows 矩阵审计（本机无 SDK）；若发现折叠按同一模式修。

## 遗留

- 其余 72 项未做逐一反汇编审计（本轮只查了极端比值项）；后续版本按需抽查。
- Go/Java 未折叠是实测结论；Nim/D/Ada 子集不含这 4 项，无需处理。
