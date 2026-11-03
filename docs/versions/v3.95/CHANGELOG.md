# v3.95 — ELF 后端跑通真实基准 + 基准体系开始扩充

- 日期：2026-11-03
- 任务：让 qlmc 的 ELF 后端能跑基准；开始把 bench/speed 从 10 项扩到 75 项。
- 影响面：`bootstrap/qlmc/qlmc.qma`（mmap 分配器 / clock_gettime / 整数格式化）、
  `bench/speed/{quelmara,c,go}/`（新增 9 项基准）、`bench/speed/run.py`

## 一、ELF 后端的三块必要补充

### ① `mmap` 代替 `VirtualAlloc`

`__alloc` 原来在冷路径调 `VirtualAlloc`（Windows API）。ELF 侧改成
`mmap(NULL, HEAP_SIZE, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0)`
（syscall 9）。

**失败判定要改**：`mmap` 出错返回的是**高半区的 -errno**，不是 0。所以 ELF 分支
用 `js .oom`（判符号）而不是 `jz .oom` —— 判零的话失败会被当成"拿到地址 0"
继续用，直接段错误。

### ② `clock_gettime` 代替 `QueryPerformanceCounter`

`now_ns()` 在 IR 降低期展开，而那里发不了 `syscall`（IR 没有这个操作码）。
所以包成运行库例程 `RT_CGT` 走既有通路：
`clock_gettime(CLOCK_MONOTONIC, &ts)`（syscall 228）。

比 Windows 版简单得多 —— 一次调用直接拿到 `(tv_sec, tv_nsec)`，
不用"取计数 + 取频率再算除法"。

### ③ 整数格式化必须自己实现

PE 版 `RT_I64FMT` 靠 `wsprintfA("%I64d")`，Linux 上没有。
`_gen_i64_fmt_elf` 用机器码除 10 取余、从临时区尾部往前填。

**符号处理**：`test r8,r8` + `jns`，负数先写 `'-'` 再 `neg`。
不用"先取绝对值再判号"—— 那样 `INT64_MIN` 溢出（§7.19 的老坑）。

## 二、手写机器码踩的四个坑（全部实测）

### ① 缓冲区与"长度暂存槽"重叠 —— **一个 bug 解释了全部症状**

```quelmara
_sub_rsp(code, 0x38)
_lea_rsp(code, RCX, 0x20)      // 缓冲区从 rsp+0x20 起，要放最多 20 位
...
_mov_rsp_store(code, 0x28, RDX) // ← 长度暂存在 rsp+0x28，正好在缓冲区里！
```

数字往 `[rsp+0x20..]` 写，第 8 字节之后就把"长度"踩掉。
**症状：8 位以内全对，9 位以上必错，且恒定只错后几位。**

修法：帧改 0x40，缓冲 `[rsp+0x20, rsp+0x40)`，长度暂存挪到 `[rsp+0x18]`。

### ② `div` 循环里 `rcx` 被反复覆盖

`mov rcx, 10` 每轮都把 buf 指针冲掉 —— 所以 buf 必须存到别处
（最后用 `R11`，因为 `RT_*` 约定里它是自由寄存器）。

### ③ 复制长度要用"数字位数"而不是"总长度"

负数时 `rdi` 已经 `inc` 跳过符号位，符号是直接写进 `buf[0]` 的。
用总长度当复制长度会多复制 1 字节，末尾冒出垃圾。

### ④ `lea` 的 fixup 位置

`_lea_rip` 一次写 7 字节，`len(code)` 已指向**下一条指令**。
必须是 `len(code) + 3`。现象：换行没输出 + 段错误。

## 三、基准扩充（第一批 9 项，三语言结果逐字节一致）

| 基准 | 内容 |
|---|---|
| `b10_ackermann` | Ackermann(2,8) 深层非原始递归 |
| `b11_nqueens` | 8 皇后 × 2000 轮（回溯 + 数组标记） |
| `b12_gcd` | 3000 万次辗转相除 |
| `b13_collatz` | Collatz 1..30 万（分支预测 + 整数除法） |
| `b15_loopsum` | 最朴素循环累加 2 亿次（循环开销基线） |
| `b17_bubble` | 冒泡 8 万（最坏分支 + 交换开销） |
| `b22_knapsack` | 0/1 背包 800×800 DP |
| `b27_sieve` | 埃氏筛 5000 万（布尔数组） |
| `b28_matrix` | 矩阵乘法 300×300（朴素三重循环） |

**每一项都要求三语言算法完全等价、只打印结果 + 耗时**，否则比出来的是算法
差异而不是编译器差异。已逐项核对 quelmara / C / Go 的结果完全相同。

## 四、当前状态

| 项 | 状态 |
|---|---|
| ELF 后端产出可执行文件 | ✅ |
| 大整数 / 负数 / 循环 / 取模 / 递归 | ✅ |
| **PE 回归** `tests/qlmc_test.py` | **PASS=110 FAIL=0** |
| qlmc(ELF) 跑通基准 | 4/6（`b10` 31.9μs、`b12` 11.1s、`b15` 264ms、`b28` 809ms） |
| `b13_collatz` / `b27_sieve` | ❌ 待查（b27 撞 64MB 堆上限；b13 缩小规模后正常，怀疑特定代码形状） |

## 五、下一步

1. 修 `b13` / `b27`，把 6 项全部跑通；
2. 堆上限从 64MB 提高（`b27_sieve` 的 5000 万字节几乎顶满）；
3. 继续扩基准到 75 项，并接入更多语言（Rust/C#/Zig/Ada/Fortran/D/Nim）。
