# v4.03 — 修 `now_ns` 的 timespec 别名（§7.50 缺陷 B 的主体）

- 日期：2026-11-03
- 任务：ELF 后端下多个基准的**计时是负数**（如 `-5.2e14`），数据不可用。
- 结论：修好大部分场景，`b12_gcd` / `b15_loopsum` / `b16_leibniz` 仍有残留。

## 根因

`_bi_now_ns_elf` 原来这样拿缓冲：

```quelmara
let buf = _vnew(fc)                      // 临时值
_ir_emit(fc, OP_CALLRT, buf, 0, 0, RT_ALLOC)   // 要 32 字节
```

`buf` 是**临时值**，分配器看它的活跃区间只到下一次 `LOAD` 为止，
于是可能把它和后面的结果放进**同一个寄存器**。之后
`LOADD dst, [buf+8]`（读 nsec）就落到垃圾地址 —— `t1` 变成循环耗时那种
数量级，`t1 - t0` 打出 `-5e14` 这样的负数。

IR 层能直接看到这个形状：

```
CALLRT dst=2(r8) ... imm=3     ← buf 落在 R8
CALLRT dst=4(r8) ... imm=30    ← RT_CGT
LOAD   dst=5(r8) a=2           ← 结果也写 R8，把 buf 指针覆盖了
LOADD  dst=7(r10) a=2          ← 还要用 buf 读 nsec，此时 R8 已不是 buf
```

## 改动（三处）

1. **`buf` 改用 `OP_ADDRV` 取帧槽地址** —— 槽是函数固定的，
   不会被任何分配决策复用。`OP_ADDRV` 的 `imm` 是 `-槽号-1`。
2. **`buf` 再用 `_pin` 变成变量** —— 临时值会让分配器认为它"用完即弃"；
   变量在函数内固定一个位置。
3. **给 `_gen_cgt_elf` / `_gen_syscall_elf` 加标准栈帧**
   （`push rbp; mov rbp,rsp` … `mov rsp,rbp; pop rbp`）——
   它们是 `call` 进来的，直接 `push` 会让 `rsp` 偏移后 `ret` 跳错。

## 验证

| 基准 | 结果 | 计时 |
|---|---|---|
| `b10_ackermann` | 19 | 6023 ✅ |
| `b22_knapsack` | 9750 | 13863595 ✅ |
| `b23_lcs` | 1498 | 98428483 ✅ |
| `b28_matrix` | 960991321 | 803922854 ✅ |
| `b12_gcd` | 35700000 | **负数** ❌ |

`tests/bootstrap_test.py` **五级全 PASS**、`tests/qlmc_test.py` **110/110**。

## 残留

`b12_gcd` / `b15_loopsum` / `b16_leibniz` 三项仍是负数 —— 它们的共同点是
`t0` 之后有一个**不含函数调用的大循环**。说明还有另一条路径让
`buf` 和某个值撞寄存器，需要继续查（已记入 §7.50）。
