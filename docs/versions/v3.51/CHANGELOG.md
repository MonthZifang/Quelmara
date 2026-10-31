# v3.51 — 修 `len()` 在 R12 上崩（`_len_of` 缺 SIB 字节）

- 日期：2026-10-31
- 任务：用户要求"继续"；修 v3.50 结束后发现的既有崩溃
- 影响面：`bootstrap/qlmc/qlmc.qma`（`_len_of` 一行）、
  `tests/t195_qlmc_strlen.qma`、`tests/qlmc_test.py`（`CASES` 加 `s30_strlen`）
- 覆盖率：**51 / 70（不变）** —— 本版是正确性修复，不是覆盖率推进
- 回归：PASS=367 FAIL=0 SKIP=0；qlmc 差分 70 → **72**

## 现象

```quelmara
fn main() {
    let s = "hello"
    print(len(s).to_str())      // ✗ 0xC0000005
}
```

但同一个表达式换个写法就正常：

```quelmara
print("x" + len(s).to_str())    // ✓ x5
let n = len(s)
print(n.to_str())               // ✓ 5
```

**两种写法的 IR 几乎逐行相同**，唯一差别是寄存器分配：

```
A（崩）   2  LEN  dst=3(r12)  a=1      ← 结果落在 r12
F（正常） 2  LEN  dst=4(r13)  a=1      ← 结果落在 r13
```

`--no-opt` / `-j1` 都照样崩，排除优化层与并行。stage-0 编同一个文件一直是对的。

## 根因

`_len_of` 生成 `mov dst, [base - 8]`，用的是**裸 `_modrm`**：

```quelmara
fn _len_of(code: vec[int], dst: int, base: int) {
    _rex2(code, 1, dst, base)
    _b(code, 0x8B)
    _modrm(code, 1, dst, base)     // ← rm=100 时需要 SIB 字节
    _b(code, 0xF8)                 // disp8 = -8
}
```

x86-64 里 `rm=100` **不表示"RSP 寄存器"**，而是"后面跟一个 SIB 字节"。
R12 的低 3 位正好是 4（`12 & 7 == 4`），而 `_cs_reg(1)` 返回的就是 **12**。

于是 `_modrm` 发出 `rm=100`，紧接着的 `0xF8`（本该是 disp8 = -8）被 CPU
当成 **SIB 字节**吃掉，位移变成 0 —— 实际指令是 `mov r12, [r12]`，
读的是字符串的**第一个字节**当指针，立刻 AV。

`r12` 是 `_cs_reg(1)`，即"第 2 个变量寄存器"。所以这个 bug 只在
**分配器恰好把 `LEN` 的结果放到 r12** 时出现 —— 换个上下文（比如
`"x" + len(s)` 里多了个中间值）结果就落到 r13，一切正常。

**这就是"寄存器分配换个顺序就崩"的典型形态，也是最难靠读代码发现的一类。**

## 修复

```quelmara
_modrm_mem(code, 1, dst, base)     // 低 3 位是 4 时自动补 SIB
```

`_modrm_mem` 已经存在（`_lea_rm` 用它），就是为这个场景写的。

## 顺带审计了全部 9 处裸 `_modrm`

修完把源码里所有 `_modrm(code, N, ...)` 过了一遍，确认只有 `_len_of` 是真 bug：

| 位置 | 函数 | `base` 来源 | 结论 |
|---|---|---|---|
| 2313 / 2327 | `_sse_mem` / `_sse_mem0` | 全部调用点传 `RBP` | ✅ 安全（低 3 位 = 5） |
| 2490 | `_lea_rip` | 硬编码 `rm=5` | ✅ RIP 相对，正确 |
| 3074 | `_alu_rm` | 全部调用点传 `RBP` | ✅ 安全 |
| 3148 | `_imul_rm` | 全部调用点传 `RBP` | ✅ 安全 |
| 3156 | `_idiv_rm` | 全部调用点传 `RBP` | ✅ 安全 |
| 3164 | `_neg_rm` | 全部调用点传 `RBP` | ✅ 安全 |
| 3191 | `_lea_rbp` | 硬编码 `RBP` | ✅ 正确 |
| 7413 | `JCMPVLEN` 发射 | 硬编码 `RCX` | ✅ 安全（低 3 位 = 1） |
| **3194** | **`_len_of`** | **任意 vreg 的寄存器** | ❌ **就是它** |

结论：`_modrm` 只在"base 一定是 RBP / 固定寄存器"的场合才安全。
凡是 base 来自 `_cs_reg()` / `_to_reg()` 的，都必须走 `_modrm_mem`。

## 测试

`tests/t195_qlmc_strlen.qma`，加进 `tests/qlmc_test.py` 的 `CASES`
作为差分用例（`s30_strlen`）。

**必须是差分用例**：这个 bug 只在分配器把 `LEN` 的结果分到 r12 时出现，
光"能编过"完全看不出来，stage-0 一直是对的。夹具凑了 8 组形态
（直接嵌套 / 落变量 / 字面量 / 算术 / 拼接 / 连续四次 / 当循环上界），
逼分配器覆盖多种寄存器落点。

10 行输出与 stage-0 逐字节一致：`5 / 1 / 0 / 10 / 5 / 3 / 15 / n=5 / 16 / 10`。

## 自举

30/30 组等价 + 不动点成立（未受影响 —— `_len_of` 只改一个字节的编码，
`__alloc` 等运行库例程不变）。

## 方法教训

这一版**先建诊断再动手**，一轮就定位了：

1. 写 `_nl.py` 试四种编译选项（default / `--no-opt` / `-j1` / 两者）——
   全部崩，**排除优化层与并行**，把范围压到降级 + 发射；
2. 写 `_cmp.py` 对比 stage-0 与 qlmc 的 6 个变体 —— 找到
   "`A_nested` 崩、`F_plus_nested` 正常"这个最小对立对；
3. `irdump` 两份 IR 逐行对比 —— 唯一差别是 `r12` vs `r13`；
4. 查 `_cs_reg` → 发现 `r12` 是 `_cs_reg(1)` → 查 `_len_of` 的编码 → 命中。

对比 v3.49/v3.50 那两次"连猜 3-6 轮、每轮 2 分钟编译"，
这次 4 步、约 15 分钟就收敛。**诊断脚本的成本远低于试错的成本。**
