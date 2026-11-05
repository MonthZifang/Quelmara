# 性能优化交接文档（qlmc vs C 差距的完整地图）

- 日期：2026-11-05
- 状态：截至 v4.49（HEAD 6a0f8bc）

## 目标与现实

用户目标：45 项以上基准跑赢 go/c（≤1.10x 或更好）。
现实：**1/19**。差距是结构性的，不是调参能解决的。

## 已确认的三大结构阻碍

### 1. vec 双重访存（最大头）

`v.get(i)` 生成的机器码：

| 指令 | 作用 | 条数 |
|---|---|---|
| `LOADD dst,[h+0]` | 读 data 指针 | 1 |
| `JCMPVLEN` 系列 | 越界检查 | 2（cmp+jcc） |
| `LOADX dst,[data+i*8]` | 读元素 | 1 |

C 是 `mov rax,[base+i*8]` 一条。**每元素多 4-5 条指令**。

唯一根治法 = vec 内联布局 `[len][cap][data...]`。
**5 次尝试全部失败**（详见 `docs/perf/ANALYSIS.md` 附录 1-4）。
最后一次 trace 定位到：stage-2 死在 `_new_fc` 的 FnCtx 构造
（23 个 vec 字段一次性创建），单独测试全部正常——自引用 bug。

### 2. 寄存器池已满

`N_VARREG = 7`（RBX/R12-R15/RSI/RDI，全部 callee-saved）。
x86-64 扣掉 RSP/RBP/RAX/RCX/RDX（发射器约定用）后只剩这 7 个。
**没有可加的空间**。要改必须动 ABI 或实现真正的图着色分配器。

### 3. 无循环向量化

qlmc 有 7 个 SSE 发射函数（`_sse_rr`/`_sse_mem` 等），但只用于 f64
标量运算。把标量循环转 SIMD 需要循环依赖分析 + 尾部处理，
是数周工程。

## 已落地且验证过的优化（保留）

| 项 | 版本 | 收益 | 验证 |
|---|---|---|---|
| `_mov_rr` 同寄存器不发 mov | v4.41 | 微小 | 自举全绿 |
| `_vec_check` 冷路径精简 | v4.42 | 二进制 -2.5% | 自举全绿 |
| ELF EXIT 走 syscall | v4.16 | 屏障减少 | 自举全绿 |
| `--heap-mb` 堆上限可配 | v4.44/45 | 功能 | 自举全绿 |
| `bounds_check` 开关 | v4.46 | **b18/b72/b23 各 -20%** | 自举全绿 |
| `--trace` 诊断通道 | v4.48 | 调试能力 | 自举全绿 |
| `_map_cap`/`_map_count` 语义分离 | v4.47 | 正确性 | 自举全绿 |

## bounds_check 的坑（重要！）

不是无脑全赢。逐基准实测：

* 循环内 **≥2 次** vec 访问 → **-20%**（b18/b72/b23）
* 循环内 **1 次** vec 访问 → 可能 **+28% 回退**（b70_lin_search）

原因：热循环整体移位带来的 i-cache/分支对齐变化，可能超过省下的
2 条指令。**任何全局开关都要逐基准验证。**

## vec 内联布局：如果想再试

**已修掉 6 个真 bug**（5 次尝试积累）：

1. `_vec_grow_body` 里重复 `_pin(fc, h)` → 迭代内副本，改不到调用方
2. `_lower_vecnew` 死变量 `hdr`
3. `_map_cap`：map 的 `[h+0]` 是 cap，vec 是 data —— **语义相反**
4. `_map_count`：map 的 `[h+8]` 是 count，vec 是 len
5. `_map_slot_of`/`_map_put`/`_map_del` 三处借用 `_vec_field`
6. `_vec_push` 的 `hp = _pin(fc, h)`（同 1，最隐蔽）

**最后一个未解**：stage-2 死在 FnCtx 构造。已排除：
22/23 个连续 vec、struct vec、嵌套 vec、大 vec —— 单测全过。
只在内联代码**自编自己**时出现。

**再做的话**：
1. 先写一个独立的小分配器测试（不经 12 分钟构建就能跑）
2. 或给 `_new_fc` 的 FnCtx 构造逐字段加 trace
3. RT_ALLOC 返回值检查：内联分配是 `16+n*stride`，查是否溢出 imm32

## 建议的下一步（按收益/风险排）

1. **逐基准开 bounds_check**（在 run.py 里按基准传参）——已验证，
   b18/b72/b23 可拿 -20%，零风险
2. `_vec_field` 的 off=0 返回 `h+16` 但**只对 stride==8 的 vec**——
   聚合 vec 先不动，缩小爆炸半径
3. SIMD：先做 `vec[int]` 的 memcpy/memset 向量化（`OP_MEMCPYN` 走 SSE），
   不需要循环分析
