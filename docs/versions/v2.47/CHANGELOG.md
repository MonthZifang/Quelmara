# v2.47 — f64 大修：字面量只解析一次，`b2_float` 快 11.5 倍

- 日期：2026-10-25
- 任务：严重优化性能与加速比（按 §7.31 的定位打）
- 影响面：自举层（f64 三条路径全改）/ 基准 / 文档

## 先诊断，再改

第一步只做了"f64 二元运算内联"（`OP_FBIN`），结果 `b2_float` **只快 1.5%**（760 → 748 ms）。
说明瓶颈不在那条 `addsd` 上。于是做对照实验：把 `1.0` 手动提到循环外 ——

```
字面量在循环内：752.2 ms
字面量在循环外： 69.8 ms      ← 10.8 倍
```

**真凶**：`E_FNUM` 的降级是「开槽 → `OP_LEA` 取原文 → 运行时 `strtod` 解析进槽」。
字面量落在循环体里就是**每轮一次 `strtod`**，占了 90% 的时间。

## 三件事

**1. `OP_FBIN`：f64 二元运算内联。** `[dst] = [a] <op> [b]`（三个操作数都是 f64 槽的
地址，`imm` 选子操作），发射成 3 条 SSE：

```
movsd xmm0, [rcx]
addsd xmm0, [rdx]        ; sub/mul/div 同理
movsd [rax], xmm0
```

以前是 `ADDRV + 3×ARG + CALLRT(__fadd)` —— 一次调用 + 运行库里 6 条指令。

**2. `OP_ITOF` / `OP_FTOI`：f64 ↔ int 转换内联。** `cvtsi2sd` / `cvttsd2si`，
替掉 `__itof` / `__ftoi` 调用（三处降级点都改了）。

**3. f64 字面量"只解析一次"（这一条是 11 倍）**：`E_FNUM` 先查 `cells` 里的缓存
（串 id → 已解析好的 f64 槽地址），命中就直接复用；没命中才发一次带标志的解析：

```
ADDRV fa, 标志槽; LOAD fv, [fa]; CONST z, 0
JCMP jne fv, z → lskip          ; 已解析过就跳过
LEA sp, "1.0"; ARG sp,0; ARG ad,1; CALLRT __fparse
ADDRV fa2, 标志槽; CONST one,1; STORE [fa2] = one
LAB lskip
```

标志槽由 `_emit_fn` 在**函数序言里直接发机器码清零**（`mov qword [rbp+disp], 0`）——
不能走 IR，因为分配已经跑完了，新开 vreg 会拿到 `vloc = 0` 而 fail-fast。

循环体里剩下的代价是 `ADDRV + LOAD + CONST + JCMP` 四条廉价指令，对比一次 `strtod`
（约 50–100 ns）可以忽略。

## 结果

| 基准 | v2.46 | **v2.47** | C | qlmc / C |
|---|---|---|---|---|
| `b2_float` | 760.6 | **66.3** | 22.6 | 34.3× → **2.9×** |
| `b3_recursion` | 8.8 | 7.9 | 3.3 | 2.8× → 2.4× |
| `b7_sort` | 32.9 | 29.9 | 14.8 | 2.0× |
| `b8_threads4` | 117.1 | 109.2 | 12.3 | 9.2× → 8.9× |
| `b1_int` | 207.9 | 203.3 | 11.1 | 18.3×（没动） |
| `b8_threads1` | 410.7 | 406.8 | 22.2 | 18.3×（没动） |
| 其余 | — | — | — | 在噪声内 |

- **`b2_float`：11.5 倍**，是这一轮的主结果。
- **并发加速比 3.51× → 3.72×**（4 线程；单线程 406.8 → 4 线程 109.2）。
- **40 个校验和全部一致** —— 字面量的值一模一样（还是 `strtod` 算的），只是不再重复调用。

## 踩的坑

**stage-0 不认"常量当方法接收者"**：`FNUM_MAX.to_str()` 报 `未定义变量 FNUM_MAX`。
写成 `(FNUM_MAX).to_str()` 才行。别处 `(SLOT_TEMP).to_str()` 本来就带括号，所以这个
限制一直没暴露。已记进坑表 #52。

**`cells` 可以往后长**：它是个普通 `vec[int]`，`_new_fc` 只初始化 10 格。这轮用了
`cells[10]`（标志槽个数）、`cells[11..]`（标志槽号）、`cells[50]`（缓存条数）、
`cells[51..]`（串 id / 地址 vreg 对）。上限 32 条，超了 fail-fast。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=57 FAIL=0** |
| `python tests/bootstrap_test.py --strict` | **五级全 PASS**（不动点仍成立） |
| `python bench/speed/run.py --reps 3` | 10 基准 × 4 语言，**40 个校验和一致** |
| 四道门 + `run_win_tests` | 全绿 / **PASS=290 FAIL=0 SKIP=1** |

## 剩下的（§7.31 更新）

- **`b1_int` / `b8_threads1` 的 18 倍 → `idiv` 延迟**。微优化已证明无效（循环 14 → 12
  条指令，实测没动）。只有常数除法的魔数乘法能救，而魔数推导我验不到项目要求的强度
  （小样本"通过"是假的），宁可不做。设计与障碍见 §7.31 (a)。
- **`b2_float` 剩下的 2.9 倍 → f64 仍住帧槽**。运行库调用已经没了，剩下的是"每次运算
  两次 `movsd` 内存往返"。要再快就得给分配器加 XMM 寄存器文件，是另一个量级的工程。
- **`b9_json` 6.3 倍 → 每字节一次越界检查**。要范围分析（循环上界证明 `p < len`）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增 `OP_FBIN`/`OP_ITOF`/`OP_FTOI`；`E_FNUM` 加"只解析一次"缓存 + 标志槽；`_emit_fn` 序言清零标志槽；新增 `_cell_ensure`/`_cell_set`/`_fnum_get`/`_fnum_put`/`_fnum_flag` |
| `bench/speed/RESULTS.md` | 更新四语言表 + v2.46→v2.47 对比列 |
| `docs/05-toolchain.md` | 坑表 **#52**；§1.11 f64 小节改写 |
| `docs/07-gaps.md` | §7.31 更新：f64 从 34× 降到 2.9×，剩下的瓶颈重写 |
| `docs/06-status.md` | §3.25 更新到 v2.47 |
