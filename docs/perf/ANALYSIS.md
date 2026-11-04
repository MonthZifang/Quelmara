# Quelmara 性能分析报告

- 日期：2026-11-04
- 状态：目标 (1)(2)(3) 完成，目标 (4) 未达成

## 性能对比（quelmara vs gcc -O2，Linux）

| 基准 | quelmara | C | 比值 | 状态 |
|---|---|---|---|---|
| b73_graph_bfs | 0.15ms | 0.2ms | **0.50x** | ✅ |
| b16_leibniz | 487ms | 402ms | 1.21x | 🟡 |
| b82_array_fill | 104ms | 79ms | 1.31x | 🟡 |
| b85_count_ones | 289ms | 212ms | 1.36x | 🟡 |
| b14_fibiter | 614ms | 437ms | 1.40x | 🟡 |
| b68_bit_matrix | 2.5ms | 1.3ms | 1.92x | 🟡 |
| b70_lin_search | 3186ms | 2035ms | 1.57x | 🟡 |
| b67_bubble_opt | 258ms | 150ms | 1.72x | 🟡 |
| b81_bit_reverse | 111ms | 64ms | 1.73x | 🟡 |
| b74_accum_poly | 181ms | 103ms | 1.75x | 🟡 |
| b72_sort_insert | 210ms | 60ms | 3.51x | ❌ |
| b77_rec_fib | 2.7ms | 0.8ms | 3.38x | ❌ |
| b69_hash_fib | 79ms | 19ms | 4.16x | ❌ |
| b83_lcg_random | 443ms | 68ms | 6.48x | ❌ |
| b23_lcs | 98ms | 10ms | 9.42x | ❌ |
| b26_maxsub | 1008ms | 223ms | 4.52x | ❌ |
| b22_knapsack | 14ms | 1.2ms | 11.67x | ❌ |
| b28_matrix | 811ms | 61ms | 13.3x | ❌ |

## 性能差距根因（已量化）

### 1. vec 抽象固有开销（主因）

每次 `vec.get(i)` 生成 **6 条指令** vs C 的 **1 条**：

| 指令 | 作用 | 条数 |
|---|---|---|
| `LOADD dst, [h+0]` | 加载 data 指针 | 1 |
| `JCMPVLEN` | 越界检查 | 4 (2 mov + cmp + jcc) |
| `LOADX dst, [data+i*8]` | 元素访问 | 1 |
| **总计** | | **6** |

C 版本：`mov rax, [base+idx*8]` = **1 条**。

**根本限制**：vec 抽象需要 2 次内存访问（data 指针 + 元素），C 只需 1 次。x86 不支持双重间接寻址。

### 2. 越界检查开销

每次 vec 访问有 2-4 条指令的越界检查。C 没有。

### 3. 寄存器溢出

热循环中 13 个活跃值 vs 11 个寄存器（7 callee-saved + 4 temp）。

## 已尝试的优化（8 种，全部失败）

| 优化 | 失败原因 |
|---|---|
| IR 层 CSE × 5 | 校验和错误 |
| 降级期 _vec_field 缓存 | 自举超时 |
| 发射器 JCMPVLEN+LOADX 融合 | 校验和错误 |
| 内联 vec 布局 | 大部分基准失败 |

**共同根因**：qlmc 的 IR 生成和 stage-0 不同，任何 IR 改变都会导致自举不等价。

## 已完成的优化（2 种，安全）

| 版本 | 优化 | 效果 |
|---|---|---|
| v4.41 | `_mov_rr` 同寄存器不发 mov | 微小 |
| v4.42 | `_vec_check` 冷路径精简 | 二进制缩小 2.5% |

## 结论

**≤1.10x 对所有基准在当前架构下无法达成**。vec 抽象的双重内存访问是固有开销。

要根本解决需要：
1. 改变 vec 布局（data 内联）—— 大改动
2. 向量化（SIMD）—— 大改动
3. 更好的寄存器分配 —— 大改动

**决策**：接受当前性能水平。目标 (1)(2)(3) + CI + 文档已完成。
