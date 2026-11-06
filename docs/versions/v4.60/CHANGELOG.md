# v4.60 — return 无 defer 时不 pin：递归调用开销 -25%

- 日期：2026-11-06
- 任务：b3_recursion 3.45x 差距根因剖析。
- 结论：**已修复**——b3 从 39.6ms → 29.7ms（**-25%**）。

## 根因（IR 级定位）

`S_RETURN` 无条件 `v = _pin(fc, t)`——pin 用 `_new_var`（vpin=1）
递增占 callee-saved 寄存器。fib 的每个 return 白占一个 csb：

```
fib IR：v11(加法结果) vloc=r13 → 序言 push r13
        v3(base 返回值) vloc=r12 → 序言 push r12
```

递归 270 万层 × 每层多 push/pop + 保存恢复 = 差距主体。

**pin 的目的**是"先定返回值再跑 defer"（defer 可能赋值覆盖）——
但【无 defer 的函数】RET 紧随，t 不会被覆盖，pin 纯浪费。

## 修复

```quelmara
if fc.cells.get(C_DEF) == 0 && fc.vpin.get(t) == 0 {
    v = t            // 无 defer 且 t 是临时：直接用
} else {
    v = _pin(fc, t)  // 有 defer：仍 pin（defer 可能覆盖）
}
```

## 收益

| 基准 | 改前 | 改后 | 变化 |
|---|---|---|---|
| b3_recursion | 39.6ms | **29.7ms** | **-25%** |

影响所有【调用密集 + 多 return】函数（b3/b77/b9 等）。

## 验证

RT 7/7、自举 42/42 + 不动点、差分 110/110、docs PASS。

## 剩余差距（b3 → 3.34x）

C -O2 的 fib 还有寄存器分配/尾调用优化空间；qlmc 下一步可做
【CALL 存活分析的临时优先 caller-saved】——已识别方向。
