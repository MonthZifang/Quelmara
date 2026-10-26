# v2.65 — f64 值住进 XMM 寄存器文件，b2_float 反超 C

- 日期：2026-10-27
- 任务：深层优化，目标"赢过 C 和 Go"
- 影响面：`tools/stage0/qlm_native.py`（类型推断 / 分配器 / 发射器 / 序言尾声）
- 夹具：`tests/t148_f64_xmm.qma`

## 根因：一次浮点运算要走 4 趟 GPR↔XMM 往返

b2_float 的热循环（`acc += 1.0 / (double)i`）在改动前是 **23 条指令**：

```
cvtsi2sd xmm0, r10      ; (double)i
movq     rdi, xmm0      ; → GPR（位模式）
mov      r10, rsi       ; 1.0
movq     xmm0, r10      ; → XMM
mov      r11, rdi       ; (double)i 再搬一次
movq     xmm1, r11      ; → XMM
divsd    xmm0, xmm1
movq     r8, xmm0       ; 商 → GPR
mov      r10, r12       ; acc
movq     xmm0, r10      ; → XMM
mov      r11, r8
movq     xmm1, r11
addsd    xmm0, xmm1
movq     rdi, xmm0      ; acc → GPR
...
```

**f64 值住在 GPR 里**，每条浮点指令都要 `movq` 进出 XMM。更糟的是
`cvtsi2sd xmm0, r10` 是 SSE2 形式（只写低 64 位），对 xmm0 有**假依赖** ——
上一轮的 `movq xmm0, r10`（acc）会把它串起来，于是 5M 次除法全部串行化。

## 改法：给 f64 一个独立的寄存器文件

### 1. 类型推断（`f64_vregs`）

IR 的类型是**逐指令**携带的（`fbin`/`fcvt`/`fneg`/`fcmpset` 都带 width），
从这些根出发做不动点，再用 `mov` 双向传播。

**关键坑：vreg 编号会复用。** 同一个编号可能在 A 处装 f64、在 B 处装整数
（实测：inlined `__f64_to_str` 里 `fcmpset` 的 dst 又被当整数用）。所以
最后要减掉"被任何整数指令碰过"的编号 —— 这些**一律退回 GPR**（f64 的发射
路径对 GPR 操作数本来就有 `movq` 分支，只是慢一点；判错方向会直接崩）。

例外：`mov`/`load`/`store`/`ret`/`args`/`call` 是类型无关的搬运，不产生
"必须整数"的约束 —— 否则 `acc = acc + x` 这类 `mov var, tmp` 会把整个
循环的浮点值赶回 GPR，优化直接失效。

### 2. 分配器：两遍线性扫描，两个寄存器池

| 池 | 寄存器 | 用途 |
|---|---|---|
| `XPOOL` | xmm0-3 | 不跨调用的值（caller-saved，省掉保存/恢复） |
| `XPOOL_CALLEE` | xmm6-15 | 跨调用存活的值（Win64 非易失） |
| 临时 | xmm4/xmm5 | 编码期 scratch，**不参与分配** |

栈槽与 GPR 溢出槽**共用 `nslots` 计数器**（否则互相覆盖）。
非易失 XMM 在序言里 `movups` 存进帧的最底部（比溢出槽和结构体区都低），
尾声在 `mov rsp,rbp` **之前**恢复。

### 3. 发射器：`fx` / `fcommit` + 少搬

- `fx(x, spec)`：f64 操作数进 XMM。已在 XMM → 直接搬（`movaps`）；
  在 GPR → `movq`；在栈槽 → **`movsd` 直接从内存进 XMM**（以前是
  `mov gpr,[mem]` + `movq xmm,gpr` 两条，还要过一趟存储转发）。
- `fcommit(dst, x)`：写回 XMM / GPR / 栈槽。
- `fbin` 优先"结果直接算进 dst 的 XMM 家"、`b` 直接用它的家当源 ——
  从 4 条搬运转为 1 条 `movaps` + 1 条运算。
- `cvtsi2sd` 前**先 `pxor`**，断开假依赖。
- `load`/`store` 的 f64 走 `movsd`；`call` 的 f64 返回值从 RAX 位模式
  搬进 XMM；`args` 的 f64 形参从 GPR 搬进 XMM。
- **ABI 不变**：f64 仍按位模式走 GPR（自研 ABI），只在函数边界转换。

热循环 23 → **15 条**：

```
cmp/jle/jmp
mov   r10, r12
pxor  xmm1, xmm1
cvtsi2sd xmm1, r10
movaps xmm2, xmm0        ; 1.0
divsd xmm2, xmm1
movaps xmm1, xmm6        ; acc
addsd xmm1, xmm2
mov   rsi, r12 / add rsi,1 / movaps xmm6, xmm1 / mov r12, rsi
jmp
```

## 效果（本机 min of 7，同一张表内比较）

| 基准 | 改前 | 改后 | C | 对 C |
|---|---|---|---|---|
| b2_float | 48.5 ms | **21.2 ms** | 24.5 | **0.87×（反超 13%）** |

改前对 C 是 2.1×（本机）/ 9.4×（CI v2.64），改后 **0.87×**。
整机基准（本机）：b5 0.69×、b6 1.01×、b2 0.87× —— **三项不慢于 C**。

## 两个必须记住的坑

**(A) `fx` 少一条 `movaps` = 静默算成 0。** 第一版里
`if kind == "x": return val` —— 调用方以为值在目标 XMM 里，其实还在别的
号上。b2_float 直接输出 `0`（不是崩溃）。夹具 `t148_f64_xmm` 用
"循环累加 vs 直线展开两条路径对拍"来抓这类搬错：两条路径的寄存器分配
不同，搬错必然对不上。验证过它抓得住（把那条 `movaps` 去掉 → `assert failed:
结构体字段相加`）。

**(B) `@simd` 归约把 xmm0/xmm1 写死了。** `vsumd`/`vdotd` 的发射是
`movupd 1, ...` / `addpd 0, 1` / `movhlps 1, 0` —— 固定用 xmm0、xmm1。
它们与 `XPOOL`（0-3）直接冲突，`t59_simdf64` 立刻挂
（`assert failed: simd == scalar`）。修法是**含 SIMD 归约的函数整体放弃
XMM 分配**（退回"f64 住 GPR"）。

## 回归

`tests/run_win_tests.py`：**PASS=295 FAIL=0 SKIP=1**（含 t148）。

整数路径**逐字节未变**：b1_int 的产物 sha256 与改动前完全相同
（f64 集合为空时分配与发射走的是同一段代码）。
