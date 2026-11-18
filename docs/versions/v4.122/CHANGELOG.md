# v4.122 — 非负范围分析 → 无符号 2 的幂 div/mod（计算密集项提速）

- 日期：2026-11-15
- 任务：系统性优化 qlmc 基准性能。本轮落地**无符号取模快路径**：被除数经保守
  非负范围分析证明 `>= 0` 时，常数 2 的幂 `%`/`/` 从全符号修正链收缩为单条
  `and`/`shr`。**只改 qlmc（stage-1），stage-0 不动。**
- 影响面：qlmc 优化器（新增非负分析 pass）、`_emit_divc` 发射器、测试。

## 根因（第 31 轮反汇编实证）

C 基准多用 `uint64_t` + `% …ULL`（无符号），gcc 因此：`% 2^31` 一条
`and edx,0x7fffffff`；`% 100` 无符号魔数乘（~4 条，无符号修正）。qlmc 的 `int`
有符号，`_emit_divc` 一直走全符号修正：`% 2^31` 5 条（cqo/shr/add/and/sub）、
`% 100` ~13 条。b83_lcg_random 热循环 qlm≈30 条 vs C≈10 条，差距主要来自符号修正链。
（取证：`build/perf_full_4121/qlm_b83_lcg_random` 热循环 0x400d2d–0x400da4。）

## 改动

| 文件 | 改动 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增 `_nn_propagate`（单定义非负+上界不动点：常量/and 掩码/mov/add/mul/移位/mod/div/DIVC/BINI）、`_nn_loop`（循环携带 `v=expr%D`/`expr&M` 归纳，**兼容 DIVC 直写 v**）、`_nn_bound`（递归求界，节点预算 512 兜底防 DAG 指数膨胀）、`_loop_def1`；`_opt` 末尾重算 ndef 后调 `_opt_divc_unsigned`，把被除数已证非负的 2 的幂 `OP_DIVC` 的 b 槽换成 `SUB_MODU`/`SUB_DIVU`（操作码不变，DCE/分配器无需改）；`_emit_divc` 无符号快路径：MOD 单条 `and rax,d-1`、DIV 单条 `shr rax,k` |
| `tests/s_unsigned_mod.qma` | 差分夹具：8 组值含**负数 %/÷ 2^k、负 LCG**，钉死截断有符号语义，证明无符号快路径无误用 |
| `tests/qlmc_test.py` | 注册 unsigned_mod 夹具 |
| `VERSION` / `tools/stage0/qlm_cli.py` | 4.121.0 → 4.122.0 |

**soundness 关键**：截断有符号 `x%D` 仅在 `x>=0` 时结果非负——绝不把任意 x 的
`x%D` 记非负（stage-0 `analyze_ranges` 那条宽松规则不搬）。循环携带用「初值非负 +
更新保非负」归纳，且全程带上界防 int64 溢出。

## 第 32–33 轮 debug 实证（两个首版 bug）

1. **`vec[int].new(n)` 只给容量、长度是 0**（同 `_opt` 的 cok/cval 用 push 填充）：
   首版直接 `.set(i,…)` 越界。修法：push 出 nv 个元素。这是第 32 轮 OOB 的根因。
2. **循环携带变量被 DIVC 直写**：b83 的 `seed=(seed*C+K)%2^31` 降级为
   `OP_DIVC dst=seed`（无中间 MOV），首版 `_nn_loop` 只认 `OP_MOV` 导致不触发。
   修法：顶层运算 d 兼容「MOV 追源」与「DIVC/BINI/AND 直写」。

## 验证

| 项 | 结果 |
|---|---|
| s_unsigned_mod 差分 | 8 值全对（31404 202594 -52 -15 4947616 3500 496 19377），负数/负 LCG 语义不变；stage-0/qlmc 逐字节一致 |
| 全套 qlmc_test | **PASS=127 FAIL=1**——唯一 FAIL 为 s32_thread 已知抖动（夹具用非原子读改写赌调度，源码注释自证基线偶发丢更新）；重跑 6 次全 bits=15/cnt=4 |
| 全量 76 项 ×3 轮 | **76/76 与 C 校验一致**；≤1.1× 19 项 |
| 目标项 b83_lcg_random | **3.756× → 3.288×**（128.0 → 112.3ms，−12.2%）；交替复测 3 轮一致（127.8/127.6/127.6 → 112.5/112.4/112.5ms）；`%2^31` 由 5 条收缩为单条 and |
| 附带收益 | b65_random_walk −23.5%、b26_maxsub −9.8%（均含可证非负取模） |
| 回归 | 逐项对 v4.121 中位变化 **0.00%**，无真实回退（+169% 项为 0.01ms 级测量噪声）；几何平均读数 1.647（v4.121 1.630，C 侧计时抖动，qlm 侧无回退） |
| 源码级冷缓存严格自举 | **PASS**（`QLM_NO_CACHE=1 --strict --keep`）：stage-0 编 stage-1 871.5s；stage-2 800768 字节；42/42 组逐字节一致；错误路径干净退 2；stage-2==stage-3 不动点成立（见 bootstrap-cold.log） |

## 说明与后续

- 本版只落地 **2 的幂**无符号快路径；**非幂常数**（如 b83 的 `%100`）的无符号魔数乘
  需 Granlund-Montgomery 魔数计算（int64 溢出处理），留待后续版。b69 的 `%cap` 是
  变量除数，需先内联 + 常量传播，亦留待后续。
- 非负分析对每个函数跑一遍，节点预算 + 循环区域 `<512` 闸控制编译开销。
- 这是计算密集片（b83/b65/b13 等）的杠杆，与 vec 内联布局（数组密集片）正交。