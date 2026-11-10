# v4.99 — `cores()` 内建 + `parfor` 块数自适应

- 日期：2026-11-10
- 任务：`parfor` 在任意核数的机器上都能用满（目标③的收尾）
- 影响面：编译器（新增 `cores()` 内建 / ELF 运行库例程 / `parfor` 降低）

## 问题：块数写死 4

v4.98 把 `parfor` 的加速比从 1.10× 提到 3.29×，但块数是**编译期常量 4**：

```qma
let nch = 4     // 写死
```

换到 8 核 / 16 核机器，`parfor` 只用得上 4 个核。而且这个 4 还是"参考机是
4 核"的假设 —— 容器里被 `taskset` 限制到 2 核时它也照样开 4 块。

## 改动 1：新增 `cores()` 内建

```qma
let c = cores()      // 可用 CPU 数，恒 >= 1
```

**ELF 实现**：`sched_getaffinity(0, 8, &mask)`（syscall 204），数掩码里的
置位。用 affinity 而不是 `_SC_NPROCESSORS_ONLN` 的理由是它**反映
cgroup / taskset 的实际限制** —— 容器里 `nproc` 会变，这个也跟着变，
正是分块需要的"我实际能用几个核"。

数置位用 Brian Kernighan 的 `n &= n-1`（每轮清最低位），不用 `popcnt`
（SSE4.2，老 CPU 没有）。

**PE 实现**：暂返回 4。`GetActiveProcessorCount` 要直接进 IAT，本轮只落地
ELF 侧。

### 踩到的坑：不能用 `标签 + 偏移` 做跳转

第一版想省几个标签，写了 `_addfix(ctx.fixes, pj, lret + 8, FK_LAB)`。
`_setlab` 记的是**代码下标**，`lab + 8` 不是合法标签 —— 结果跳到例程外面的
任意位置，`cores()` 直接 SIGSEGV。

**所有跳转必须用 `_setlab` 建的真实标签。** 多建 3 个标签的代价远小于
一次崩溃。

## 改动 2：`parfor` 块数改成运行期

原来是"展开成 N 次 spawn"（所以 N 必须编译期常量）。改成**运行期循环
spawn**：

```qma
nch = max(1, min(cores(), 64))     // 上下界夹住，防异常环境
per = (hi - lo) / nch
k = 0
while k < nch - 1 {                // spawn 前 nch-1 块
    hbuf[k] = spawn worker(lo + k*per, lo + (k+1)*per)
    k = k + 1
}
acc += worker(lo + (nch-1)*per, hi)   // 最后一块父线程自己算，省一次 spawn/join
j = 0
while j < nch - 1 { acc += join(hbuf[j]) ; j = j + 1 }
```

- 句柄数组走 `RT_ALLOC` 一次分配 512 字节（够 64 块）
- 上下界 `[1, 64]` 夹住：`cores()` 返回 0 或异常大值时不会算错
- 循环里 `spawn` 是合法的 —— 单独验证过（4 个 worker 各返回 `i+1`，
  累加得 10）

**块数与核数的关系**：`ncores` 块对 `ncores` 个核，1:1。更细的切块
（2×ncores）能改善慢核拖尾，但每次 spawn 要 mmap 1MB 栈 + clone，
中小负载上不划算，所以按 1:1。

## 效果

| 指标 | v4.98 | v4.99 |
|---|---|---|
| `parfor` 加速比（本机 4 核） | 3.29× | **3.21–3.33×**（持平） |
| 块数 | 写死 4 | **运行期 `cores()`** |
| 8 核机器 | 只用 4 核 | **自动 8 块** |

本机是 4 核，所以加速比不变是预期的 —— 收益在"换机器时自动跟上"。

**单核无退化**：76 项总耗时 68598 → 68195 ms（**−0.59%**），64 项持平，
`b9_json` −5.7%、`b61_cache_scan` −5.3%。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增 `RT_NCORES` 例程槽（`RT_COUNT` 33→34）；新增 `_gen_ncores_elf`（sched_getaffinity + Kernighan 计数）；新增 `cores()` 内建；`parfor` 降低改为运行期循环 spawn |

## 验证

| 命令 | 结果 |
|---|---|
| `print(cores())`（ELF） | **4**（本机 4 核，正确） |
| 76 个基准 checksum vs C | **76/76 一致** |
| 自举两代 | 逐字节不动点 |
| `parfor` 加速比 | **3.21–3.33×**（结果与串行一致） |
| 单核 76 项总耗时 | −0.59% |
| `python3 tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- **PE 侧 `cores()` 返回固定 4**。要真正支持 Windows，得把
  `GetActiveProcessorCount` 加进 IAT 表（`I_*` 常量 + 导入名列表 + 调用）。
- 块数 1:1 于核数，没有做"超过核数的细粒度切块"（慢核拖尾时更均衡，
  但 spawn 开销在中小负载上不划算）。
- `parfor` 仍只支持 `acc = acc + expr` 形态归约。
- 无 `reduce` 的 `parfor` 仍串行降级。
