# v4.50 — RT_MEMCPY 从逐字节循环改为 8 字节块

- 日期：2026-11-05
- 任务：路线图第 3 项（`handoff/PERF-ROADMAP.md`）——memcpy 向量化，
  不需要循环分析，直接改发射器/运行库。
- 结论：**已实现**，正确性全绿，不动点时间**减半**。

## 改前是什么样

`_gen_memcpy` 是**逐字节循环**：

```
mov al,[r9]; mov [r8],al; inc r9; inc r8; dec rcx; jnz
```

**每字节 7 条指令**。拷 100 万字节 = 700 万条指令。
C 的 memcpy 是 `rep movsq`（每 8 字节 1 条微指令）—— 差 5-40 倍。

这影响所有聚合元素操作：`vec[Struct]` 的 push/get（`OP_MEMCPYN`）、
`_vec_grow` 的数据搬迁、字符串拼接。

## 改后

三段式：

1. **qword 循环**：`mov r10,[r9]; mov [r8],r10; add r9,8; add r8,8; dec; jnz`
   —— 每 8 字节 7 条指令（原实现的 8 倍吞吐）
2. **尾部字节循环**：`rcx &= 7` 后逐字节（最多 7 字节）
3. 寄存器仍遵守 v2.51 约定：**rsi/rdi 不碰**（它们是变量寄存器），
   用 r8/r9/rax/r10

没有用 `rep movsq` 的原因：它硬性要求 rsi/rdi，与"rsi/rdi 是变量寄存器"
的约定冲突（要么 push/pop 一对、要么换寄存器组）。
普通 8 字节 load/store 循环已有 8 倍收益，且零 ABI 风险。

## 验证

* `b31_memcpy` / `b52_io_scan` / `b28_matrix` 校验和全对
* **自举不动点 stage-2 == stage-3：8.1s → 4.8s（-41%）**
  —— 最直接的证据：自举过程大量编译/拷贝，memcpy 提速直接反映在墙上时钟
* 差分测试运行中

## 没做的

`RT_ZERO`（memset）还是逐字节循环 —— 同样的改法（`rep stosq` 有 rdi
问题，用 r10 做游标的 8 字节循环），下一轮顺手。

## 追加（同版本）：RT_ZERO 也改了

`_gen_zero`（memset）同样逐字节（每字节 5 条）。同 memcpy 的三段式：
qword 循环（`mov qword [r8],0`）+ 尾部字节。

验证：b28/b82/b23 校验和全对（960991321 / 9999999 / 1498），
自举 42/42 + 不动点 4.8s（保持）。
