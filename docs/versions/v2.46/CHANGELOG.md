# v2.46 — 优化底层代码：立即数运算 + 地址/访存融合

- 日期：2026-10-25
- 任务：按 v2.45 基准指出的方向优化生成代码
- 影响面：自举层（`_opt` 新增两条 pass + 8 个新操作码 + 越界检查分支方向）/ 文档

## 先量后改

动手前先把 `b1_int` 的热循环 dump 出来数指令（14 条/轮）：

```
cmp r13, rbx          ; i < n
jge done
mov r9d, 0xd          ; 常量 13 —— 每轮重新加载
mov r11d, 7           ; 常量 7  —— 每轮重新加载
mov r10, r13
imul r10, r11         ; i*7
mov rax, r10
mov rcx, r9
cqo
idiv rcx              ; ← 约 30 周期
mov rax, rdx
mov r8, rax
add r12, r8
mov r8d, 1
add r13, r8
jmp top
```

`vec.get(i)` 更夸张，13 条指令（C 只要 1 条）：

```
lea r8, [r12 + 8]     ; &v.len
mov rax, r8
mov r9, [rax]         ; len
cmp r15, r9
jae die
jmp ok                ; ← 多余的跳
die: ...call die...
ok:
lea r8, [r12]         ; &v.data
mov rax, r8
mov r9, [rax]         ; data
mov rcx, r15
shl rcx, 3
mov rax, r9
add rax, rcx          ; data + i*8
mov r8, rax
mov rax, r8
mov r9, [rax]         ; 取值
```

## 做了四件事（全部在 `_opt` 里，Quelmara 写）

**1. 立即数二元运算 `OP_BINI` / `OP_CMPI`**。`b` 槽放子操作码、`imm` 放常量：

| 原来 | 现在 |
|---|---|
| `mov r8d, 1` + `add r13, r8` | `add r13, 1` |
| `mov r11d, 7` + `imul r10, r11` | `imul r10, r13, 7`（三操作数形态） |

**2. 强度削减**：`x * 2^k` → `shl k`；`x*1` / `x+0` / `x-0` / `x|0` / `x^0` / `x<<0` →
`MOV`；`x*0` / `x&0` → `CONST 0`；`x*-1` → `NEG`；`x&-1` → `MOV`；`x|-1` → `CONST -1`。

**3. 地址计算与访存融合**（最大的一块，8 个新操作码）：

| 融合前 | 融合后 |
|---|---|
| `ADDRF t,a,imm` + `LOAD d,t` | `OP_LOADD d,a,imm` → `mov d,[a+disp]` |
| `ADDRX t,a,b,8` + `LOAD d,t` | `OP_LOADX d,a,b` → `mov d,[a+b*8]` |
| `ADDRF/ADDRX` + `STORE` | `OP_STORED` / `OP_STOREX` → `mov [a+disp],v` / `mov [a+b*8],v` |
| `ADDRF/ADDRX` + `LOAD8/STORE8` | 四个 `*8D/*8X` 变体 → `movzx` / `mov byte` |

条件：地址临时值**单定义、单使用**。`vec.get(i)` 从 13 条降到 4 条：

```
cmp r15, rbx
jge done
mov r9, [r12 + 8]      ; len
cmp r15, r9
jb  ok                 ; ← 单分支
die: ...call die...
ok:
mov r9, [r12]          ; data
mov r9, [r9 + r15*8]   ; data[i]
```

**4. 越界检查条件反过来写**：`jae lfail` + `jmp lok` → `jb lok`，热路径少一条跳转。
三处都改了（`s[i]` 字符串下标 / `vec` 下标 / 切片检查）。

## 这一轮踩的四个坑（都已进坑表）

| 坑 | 现象 | 修法 |
|---|---|---|
| `_rex_full` 把**寄存器编号**当位标志用 | `(r << 2)` 里 r=9 而不是 1，REX 字节发成 `0x7E` 而不是 `0x4E` → CPU 当非法指令跑飞，RIP 到 image 外面 | 参数是编号，`if r >= 8 { 1 } else { 0 }` |
| 强度削减的**兜底分支**把 `OP_MOD` 也收进 `OP_BINI`，而发射器的 ext 链默认落到 add | `(i*7) % 13` 静默变成 `(i*7) + 13`，校验和 119999988 → 1400000190000000 | 兜底只放行 ADD/SUB/MUL/AND/OR/XOR；发射器对未知子操作 **fail-fast**，禁止"默认 0 = add" |
| 融合把操作数的**最后一次使用**从第 i 条搬到第 hit 条，但 `vend` 还是 `_ir_emit` 记的 i | 分配器提前复用寄存器 → 数组/切片用例**间歇** AV（`s4_agg` / `s9_slice`） | 融合成功后 `vend[a]` / `vend[b]` 取 max(vend, hit) |
| `_mov_imm` 的 imm32 档漏下界 | `1 << 61` 被截断成 0（`s15_bitops` 打出 `-128`） | `v < 0 && v >= -2147483648`（v2.44 踩过一次同样的，这版又犯了） |

## 效果（诚实版）

**代码体积**（对 v2.45 基线，15 个夹具合计）：**−1.6%**，最好 `b9_json` −2.6%，
没有一个是负优化。

**速度**（`bench/speed/`，min of 3）：

| 基准 | v2.45 | v2.46 | 变化 | 说明 |
|---|---|---|---|---|
| `b7_sort` | 38.2 | **32.9** | **−14%** | 缓存驻留 + 每元素多次 `vec.get/set` → 指令数敏感 |
| `b6_hash` | 42.5 | 42.2 | 噪声内 | 现在**与 C 持平**（C 43.2） |
| `b4_array` | 32.8 | 31.2 | 噪声内 | 16 MB 数组 → **带宽瓶颈**，指令数不重要 |
| `b9_json` | 48.3 | 49.7 | 噪声内 | 已经主要是 `s[p]` 的越界检查 + 函数调用 |
| `b1_int` / `b8_threads1` | 199 / 402 | 208 / 411 | **没动** | `idiv` 延迟瓶颈（12 条 vs 14 条指令无所谓） |
| `b2_float` | 716 | 761 | 没动 | f64 走运行库调用，与这次改动无关 |

**结论：微优化只对"指令数敏感"的代码有效。** 三个最大的差距各有各的瓶颈：

1. **`b1_int` 的 18 倍 → `idiv`**。要动它只有一条路：**常数除法的魔数乘法**。
   这是下一轮的事，设计已定（见下）。
2. **`b2_float` 的 32 倍 → f64 不进 XMM 寄存器**，每次运算是一次运行库调用。
3. **`b4_array` 的 3.5 倍 → 内存带宽**，不是编译器能改的。

## 下一轮：`OP_DIVC`（常数除法的魔数乘法）

**为什么这次没做**：魔数 + 位移的推导（Granlund–Montgomery）我做了 Python 原型，
但**没验到项目要求的强度**。一个具体的反例：`d=3` 用 `M = ceil(2^64/3)`、`s=0`
在 14 个采样点上全部通过，但误差项 `e = M*d - 2^64 = 2`，而正确的充分条件是
`e * (2^64-1) < 2^64`（即 `e <= 1`）—— **小样本"通过"是假的**。`%` 算错是
静默错值，比崩溃危险，所以宁可不做。

**设计（已定）**：
- 新操作码 `OP_DIVC`：`b` = 子操作（`OP_DIV` / `OP_MOD`），`imm` = 除数。
- **发射期**展开（不在 `_opt` 里展开）—— 因为需要多条指令，而 `_opt` 的铁律是
  "只改指令还在不在，不改下标"，加指令会破坏 `vstart`/`vend`。
- 序列（`x / d`，d > 0）：
  ```
  mov  rcx, x
  mov  rax, rcx
  movabs rdx, M
  imul rdx              ; rdx:rax = x*M（有符号 64×64→128）
  mov  rax, rdx
  shr  rax, 63          ; 符号修正
  sar  rdx, s
  add  rax, rdx         ; q
  ```
  `%` 再加 `imul rax, rax, d` + `sub rcx, rax`。
- **障碍**：编译器要在编译期算出 `M = ceil(2^(64+s)/d)`，而 `2^64` 装不进 int64。
  绕法：`floor(2^63/d) = 0 - (INT64_MIN / d)`（有符号除法对负数向零截断，正好
  等于 `-floor`），再 `floor(2^64/d) = 2*floor(2^63/d) + floor(2*r63/d)`，其中
  `r63 = INT64_MIN - floor(2^63/d)*d`（**利用 int64 回绕**得到正确的正余数）。
- **验证要求**：`d` 取 2..2000 全部非 2 的幂，`x` 取「0/±1/±d/±(d±1)/
  ±2^62/±(2^63-1)/-2^63」+ 100 万随机值；再叠上 `tests/qlmc_test.py` 的逐字节差分。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=57 FAIL=0** |
| `python tests/bootstrap_test.py --strict` | **五级全 PASS**（不动点仍成立） |
| `python bench/speed/run.py --reps 3` | 10 基准 × 4 语言，**40 个校验和全部一致** |
| 四道门 | 全绿 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增 `OP_BINI`/`OP_CMPI`/`OP_LOADD`/`OP_LOADX`/`OP_STORED`/`OP_STOREX`/`OP_LOAD8D`/`OP_LOAD8X`/`OP_STORE8D`/`OP_STORE8X`；新增 `_alu_imm`/`_cmp_imm`/`_shift_imm`/`_imul_imm`/`_rex_full`/`_modrm_sibidx`/`_idx_reg`/`_opt_strength`/`_fuse_op`/`_opt_fuse`；三处越界检查改单分支 |
| `bench/speed/RESULTS.md` | 更新四语言表 + 加 v2.45→v2.46 对比列 |
| `docs/05-toolchain.md` | §1.11 优化层补两条 pass；坑表 **#49/#50/#51** |
| `docs/07-gaps.md` | §7.31：`idiv`/f64/带宽三个瓶颈的定位与下一步 |
| `docs/06-status.md` | §3.25 更新到 v2.46 |
