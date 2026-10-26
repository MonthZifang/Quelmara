# v2.55 — f64 变成标量 + 住 XMM 寄存器；顺带挖出 `dst == b` 的别名 bug

- 日期：2026-10-26
- 任务：`b2_float` 是 CI 上最差的一项（**8.5× C**），按 §7.31 做"新一层机器"：
  把 f64 从"帧槽 + 地址传递"改成"8 字节标量 + XMM 寄存器"
- 影响面：`bootstrap/qlmc/qlmc.qma`（后端：类型判定 / 分配器 / 6 个发射器 /
  降级期 / 优化层守卫）、新增夹具 `tests/selfhost/s26_alias.qma`、文档

## 为什么 f64 以前那么慢

`_ty_is_agg` 里有一条特例：**f64 按"聚合"处理** —— 值住在帧槽里、值 = 槽地址、
按地址传。于是 `acc = acc + 1.0/to_float(i)` 这样的语句被编成：

```
lea rax, [rbp-0x20]        ← to_float 的结果槽
mov [rbp-0x58], rax        ← 把地址溢出到另一个槽
mov rax, [rbp-0x58]
mov rcx, r12
cvtsi2sd xmm0, rcx
movsd [rax], xmm0
lea rax, [rbp-0x28]        ← 1.0 字面量的槽
mov [rbp-0x60], rax
lea r8, [rbp-0x30]         ← "字面量已解析"标志
mov rax, r8
mov r9, [rax]
mov r8d, 0
cmp r9, r8
jne 0x1b4d                 ← 每轮一次守卫
   ... call __fparse（strtod，只在第一轮）...
lea rax, [rbp-0x38]
mov [rbp-0x50], rax
mov rcx, [rbp-0x60]
mov rdx, [rbp-0x58]
mov rax, [rbp-0x50]
movsd xmm0, [rcx]
divsd xmm0, [rdx]
movsd [rax], xmm0
lea r8, [rbp-8]            ← acc 的地址
lea rax, [rbp-0x40]
mov [rbp-0x48], rax
mov rcx, r8
mov rdx, [rbp-0x50]
mov rax, [rbp-0x48]
movsd xmm0, [rcx]
addsd xmm0, [rdx]
movsd [rax], xmm0
lea rax, [rbp-8]
mov [rbp-0x50], rax
mov rax, [rbp-0x50]
mov rdx, [rbp-0x48]
mov r8, rax
mov r9, rdx
mov ecx, 8
call __memcpy              ← **8 字节赋值走一次函数调用**
add r12, 1
jmp
```

**52 条指令**，其中一次 `call __memcpy`（f64 是聚合 → 赋值 = 聚合拷贝）。
C 的同一段循环是 6 条。

## 改了什么

### ① f64 不再是聚合

`_ty_is_agg(TY_F64)` 删掉那条特例。f64 就是**8 字节标量**，值与 int 同构，
只是**位置**多一种编码：

```
vloc >= XLOC(64)     → XMM，编号 = vloc - 64
0 < vloc < XLOC      → 通用寄存器，编号 = vloc - 1
vloc < 0             → 帧槽，槽号 = -vloc - 1
```

### ② 寄存器文件：XMM6-XMM15 给变量，XMM0-XMM3 给临时值

Win64 里 **XMM6-XMM15 是非易失的**（XMM0-5 易失），而 qlmc 以前一个 XMM 都没用。

- `_new_var`：f64 变量依次拿 XMM6..XMM15，用完才落帧槽（`C_NXF` 计数）
- `_alloc`：f64 临时值走 XMM0..XMM3（易失，跨调用同样溢出到帧槽）；
  占用表**复用 `rend` 的第 4..7 格**（不新增 `FnCtx` 字段 —— 字段数敏感）
- `_emit_fn`：把用到的 XMM 变量寄存器存到帧里再恢复。保存槽必须由 `_alloc`
  在**临时池之前**分配 —— 临时池的基址是当时的 `C_ST`，之后再 `_st_slot`
  会落在池子里互相踩
- **XMM4/XMM5 恒空闲**（既不在临时池也不在变量池）→ 当"绝不会撞车"的专用临时

### ③ 六个发射器全部重写

| 指令 | 以前 | 现在 |
|---|---|---|
| `OP_FBIN` | 3 条 `movsd` + 地址搬运 | `addsd xmm6, xmm0`（dst 在 XMM 就直接算，b 在槽就当内存操作数） |
| `OP_ITOF` | 地址 + `cvtsi2sd` + 存 | `cvtsi2sd xmm6, r12`（源在通用寄存器就直接用） |
| `OP_FTOI` | `movsd` + `cvttsd2si` | `cvttsd2si rax, xmm6` |
| `OP_FCMP` | 两次 `movsd` + `ucomisd` | `ucomisd xmm4, xmm6` |
| `OP_FNEG` | `CALLRT(__f64_neg)` | `btc rax, 63` 内联（新 `OP_FNEG`） |
| 字面量 | 开槽 + 标志 + 每轮守卫 | **`OP_F64IMM`**：编译期算好的位模式，`movabs` + `movq` |

`OP_LOAD` / `OP_STORE` / `OP_MOV` / `OP_CONST` / `OP_PARAMSTK` 按**值的类型**
选 `mov reg, [mem]` 还是 `movsd xmm, [mem]`，所以字段读、数组元素、形参、
返回值全都不用改降级期。

### ④ 编译期算 f64 字面量的位模式（`_f64_bits`）

以前字面量必须靠运行时 `strtod`（`__fparse`），于是要"槽 + 已解析标志 + 每轮
一次分支"。现在在**解析期**就把十进制文本算成 IEEE 位模式，直接发 `movabs`。

只在**能精确表示**时返回位模式，否则返回 -1 退回 `strtod`（正确性优先）：

- 正指数：`mantissa * 10^k` 且乘积 < 2^53
- 负指数：`mantissa` 能被 `5^k` 除尽（`m/10^k = (m/5^k) * 2^(-k)`，分子分母都精确）

覆盖 `1.0` / `0.5` / `2.5` / `100.0` / `1e3` 这些"整齐"的字面量；
`3.14` / `0.1` / `1e-20` 这种不精确的仍然走 `strtod`。

### ⑤ 优化层守卫：f64 不参与访存融合

`_opt_fuse` 把 `ADDRF + LOAD` 融合成 `LOADD`（整数路径 `mov reg, [mem]`），
会把 `OP_LOAD` 的 f64 分支整个绕过去 —— 现象是**结构体 f64 字段读出来是 0**，
还多一条死写（`mov r15, [r8]` 之后再没用过 r15）。

## 顺带挖出一个从 v2.16 就存在的 bug：`dst == b` 的别名

`_f64_bits` 里有一句 `e10 = 0 - e10`，跑出来是 0。查下去发现是**通用的二元运算
发射器**的问题：

```
if dloc > 0 {
    let d = dloc - 1
    _to_reg(fc, d, ins.a)          ← 先把 a 搬进 dst
    _bin_into(fc, d, ins.b, ...)   ← 再读 b —— **b 已经被覆盖了**
}
```

只要 `dst` 和右操作数落在同一个寄存器（`x = 0 - x`、`x = 5 - x`、`x = 3 * x`），
结果就是：

| 写法 | 正确 | 以前 qlmc |
|---|---|---|
| `x = 0 - x`（x=20） | −20 | **0** |
| `x = 5 - x`（x=100） | −95 | **0** |
| `x = 3 * x`（x=7） | 21 | **49**（= a·a） |

**stage-0 是对的，所以只有 qlmc 编出来错** —— 这也是它从 v2.16 一直没被发现的
原因：差分夹具里没人写过"常量在左、变量在右"。修法是先把 `b` 存进 `RAX`
（永不被 vreg 占用）再搬 `a`（`_bin_alias` / `_mul_alias`）。

浮点侧同一个坑（`v = 0.0 - v`）用 `XMM_SCR`（XMM4）解决：dst 与 b 撞寄存器时
换专用临时，算完再搬回 dst。

新增夹具 `tests/selfhost/s26_alias.qma`：整数 `- * & | ^`、浮点 `- *`、
`if s == s` 等 14 项全覆盖。

## 结果（本机 min of 3，仅纵向比较）

| 基准 | v2.54 | **v2.55** | C | qlmc / C |
|---|---|---|---|---|
| **`b2_float`** | 65.6 | **33.2** | 22.1 | 3.0× → **1.50×** |
| `b9_json` | 27.2 | 29.8 | 7.1 | 噪声内 |
| `b7_sort` | 23.4 | 23.0 | 14.6 | 噪声内 |
| 其余 7 项 | — | — | — | 噪声内 |

**`b2_float` 快 1.98 倍**，主循环从 **52 条指令降到 12 条**：

```
cmp   r12, rbx
jg    end
cvtsi2sd xmm1, r12
movabs rax, 0x3ff0000000000000
movq  xmm2, rax
movsd xmm0, xmm2
divsd xmm0, xmm1
movsd xmm1, xmm0
addsd xmm6, xmm1
add   r12, 1
jmp   loop
```

`acc` 住在 **XMM6**，`memcpy`、字面量守卫、地址溢出全部消失。

### 代价与副作用

- stage-2 **390 656 → 402 944 字节（+3.1%）**：f64 那套编码辅助 + `_f64_bits`
  + XMM 保存/恢复都是新代码。运行期收益远大于这点体积。
- `SLOT_TEMP` **384 → 416**：`_emit_ir` 本来就贴着旧上限，f64 改动让它多要一个槽。
  顺带加了 **帧 > 4 KB 的 fail-fast** —— 现在没有栈探测，超了会跨 guard page 静默 AV。
- 其余 9 项基准在噪声内。

## 验证

- `tests/qlmc_test.py` **PASS=63 FAIL=0**（61 个夹具，含新增 `s26_alias`）
- `tests/bootstrap_test.py --strict` **五级全 PASS**：stage-2 402 944 字节、
  **28/28 组逐字节等价**、错误路径 rc=2、**不动点 stage-2 == stage-3 成立**
- `bench/speed/run.py` **40 个校验和全部一致**
- 四道门全绿（`check_names` / `check_origin` / `check_docs` / `check_bad` 75 项）
