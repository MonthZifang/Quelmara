# v2.45 — 修 `join()` 改掉调用方变量（Win64 影子空间）；新增四语言同题基准

- 日期：2026-10-25
- 任务：跑一轮 Quelmara / C / Go / Python 的性能对比 → 顺手挖出一个 spawn/join 的
  正确性 bug
- 影响面：自举层（`__join` 运行库例程）/ 新增 `bench/speed/` / 文档

## 一、`join()` 会静默改掉调用方 `rbx` 里的变量（真 bug）

写并发基准时发现计时结果荒唐（`t1 - t0` 算出 6.4e13 ns，17 小时），顺着查下去：

```quelmara
fn main() {
    let pad = 11
    let t0 = now_ns()
    let a = spawn work(1000)
    print(pad)          // 11   ✓
    let r = join(a)
    print(pad)          // 5368721480  ✗ 变成了一个代码地址
}
```

**根因**：`__join` 是 `push rbx` 之后**直接** `call WaitForSingleObject` /
`CloseHandle`，没留 Win64 要求的 **32 字节影子空间**。而被调方的 home area 恰好是
`[rsp, rsp+0x20)`（rsp = 被调方入口的 rsp）—— 正好是 `push rbx` 保存调用方 rbx 的
那个位置。Win32 一进来就把保存的 rbx 覆盖成自己的 spill，返回后 `pop rbx` 弹回垃圾。

**影响面**：任何用 `spawn`/`join` 的程序，只要调用方有变量落在 rbx 上，`join` 之后
那个变量就被静默改掉。之前的夹具 `s19_spawn` 没抓到，是因为它 join 完之后不再用
之前定义的变量。

**修法**：`sub rsp, 0x20` / `add rsp, 0x20` 包住两次 Win32 调用（0x20 是 16 的倍数，
对齐不变）。已进坑表 **#48**、`docs/07-gaps.md` **§7.30**。

**旁证**：修完之后 4 线程基准的加速比从"算不出来"变成正常的 **3.65×**（单线程 402 ms
→ 4 线程 110 ms）。

## 二、`bench/speed/`：四语言同题基准

见 [`bench/speed/README.md`](../../../bench/speed/README.md)（口径）与
[`RESULTS.md`](../../../bench/speed/RESULTS.md)（全部实测数字）。

10 个基准 × 4 个语言，**40 个组合的校验和逐字节一致**（这是"四份实现写的是同一道题"
的唯一硬证据）。覆盖：整数 / 浮点 / 递归 / 数组 / 字符串 / 哈希表 / 排序 /
单线程与 4 线程 / JSON。

### 方法上踩的坑：本机进程创建要 447 ms

第一版用挂钟量，结果 C 的"20 万次哈希操作"和"2000 万次迭代"都是 ~450 ms —— 说明
量的根本不是负载。单独测空程序：**C 447.6 / Go 446.8 / Quelmara 437.8 /
Python 1082.4 ms**，四个语言一样。这是本机 VBS 下的 `CreateProcess` 成本。

所以改成**进程内计时**：每个程序自己用单调时钟（`now_ns` / QPC / `time.Now` /
`perf_counter_ns`）圈住负载，打印 `T` + 纳秒，驱动器只取那一段。这条口径写进了
`run.py` 的 `parse_out` 注释，以后别改回挂钟。

### 结论摘要（完整表在 RESULTS.md）

- **访存为主的项 qlmc 和 C 打平**：手写哈希 `b6_hash` 42.5 ms vs C 40.0 ms（**1.06×**）。
- **算术密集的项差 18×**：`b1_int` 199 ms vs 11 ms —— 因为 `% 13` 在 qlmc 里是**真的
  `idiv`**，C 会强度削减成"乘+移位+修正"。**qlmc 的优化层还没有强度削减**。
- **f64 差 32×**：qlmc 的 f64 不进 XMM 寄存器，全住帧槽，每次运算是一次运行库调用。
- **并发真并行**：qlmc 4 线程 **3.65×**（C 1.80×、Go 3.81×、Python 0.99× 即 GIL）。
- **编译器本身快 6.6×–41×、省内存 2.4×–7×**：编 qlmc 自己 stage-0 冷编译 31.3 s，
  qlmc 764 ms（进程内 297 ms）；峰值内存 126.7 MB vs 36.1 MB。

### 没量到的（qlmc 做不到，不是漏测）

文件处理（qlmc 没有文件 I/O 内建，只有 `file_exists`）、HTTP 请求（没有 socket
内建）、泛型/接口/宏的编译开销（特性还没实现）。

## 三、验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=57 FAIL=0** |
| `python tests/bootstrap_test.py --strict` | **五级全 PASS**（不动点仍成立） |
| `python bench/speed/run.py --reps 3` | 10 基准 × 4 语言，**校验和全部一致** |
| 四道门 | 全绿 |

## 四、改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `_gen_join` 加 `sub rsp,0x20` / `add rsp,0x20`（影子空间） |
| `bench/speed/` | **新增**：`run.py`（驱动器）/ `compiler.py`（编译器轴）/ `README.md` / `RESULTS.md` / `quelmara` `c` `go` `python` 四份实现 × 10 个基准 |
| `docs/05-toolchain.md` | 坑表 **#48**（运行库例程里 push 完必须留影子空间） |
| `docs/07-gaps.md` | **新增 §7.30**（`join` 缺影子空间 → 改掉调用方 rbx，已修） |
| `docs/06-status.md` | §3.25 补一句 join 修复与基准入口 |

## 五、下一步（基准指出的方向）

按"投入产出比"排：

1. **强度削减**（`x * 2^k` → `shl`、`x % 2^k` → `and`、小常数取模 → 乘+移位）——
   `b1_int`/`b8_threads1` 这 18× 的差距大部分能吃掉。属于 IR 层的局部变换，
   可以放进 `_opt` 已有的框架里。
2. **f64 进 XMM 寄存器** —— `b2_float` 那 32× 是最大的一块，但要动寄存器分配器
   （双寄存器文件 + 调用约定），是另一个量级的工程。
3. `vec.get/set` 的边界检查消除（`b4_array`/`b7_sort` 各 2.6–3.9×）——
   需要循环上界分析，也是新的一层。
