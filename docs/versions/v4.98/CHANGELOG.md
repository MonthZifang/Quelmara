# v4.98 — `parfor` 加速比 1.10× → 3.29×（归纳削减支持形参初值）

- 日期：2026-11-10
- 任务：让单线程单核应用**迁移过来后直接拿到多核性能**（目标③）
- 影响面：编译器（`_opt_mod_ind` 归纳削减 / 运行期初始化 / 无符号守卫）

## 问题：`parfor` 只有 1.10×，而 C+pthread 有 3.59×

`parfor` 合成的 worker 签名是 `fn w(lo: int, hi: int)`，循环变量 `i = lo`
是**运行期**值。而归纳削减（把 `(i*C) % D` 换成"递增计数器 + 条件回绕"）
的入口判据写着：

```qma
let k0 = _const_before(ir, i0, h)
if k0 < 0 {
    // "i0 循环外不是常量"
    continue
}
```

于是 **worker 完全吃不到归纳削减**，每轮吃一次完整的 64 位魔数除法。

实测同一份 40M 次 `(i*7)%13`：

| 形态 | 耗时 | 循环体指令数 |
|---|---|---|
| 常量上界函数（吃到归纳削减） | **31.5 ms** | 8 条 |
| 形参上界函数（吃不到） | **117 ms** | 14 条（含 `mul rdx`） |

这正是 `parfor` 只有 1.10×、而 C+pthread 有 3.59× 的主因 —— 不是线程调度
慢，是 **worker 每个分块都多算了一倍多的指令**。

## 修法：运行期初始化 + 无符号守卫

两件事缺一不可。

### 1. 循环前的初值改成**运行期**计算

归纳削减需要 `v` 的初值 `v = (i0 * C) % D`。原来 `i0` 必须是编译期常量才能
算出来；现在改成在循环前发两条 IR：

```
BINI  tv = i0 * C        ; 一条乘法
DIVC  v  = tv % D        ; 常量模数，编译期已算好魔数
```

只在循环**前**执行一次，代价可忽略。

**踩到的坑（插入顺序）**：`_ir_insert(fc, h, X)` 把 X 放在 `h` 位置，
**后插入的排在前**。所以要先插 `DIVC` 再插 `BINI`，最终顺序才是
`BINI → DIVC`。第一版写反了，`DIVC` 读到未初始化的 `tv` →
"内部错误：值 5 未分配位置"。

**第二个坑（活跃区间）**：新临时值必须用 `_vnew`（不是 `_new_var`，
后者会分配**变量槽**），并且要**显式**写 `vstart`/`vend` ——
`_ir_insert` 只把已有区间整体移位，不会替新值建区间。

### 2. 守卫改成**无符号**比较

魔数路径要求 `t = i*C >= 0`。形参 `lo` 的符号编译期不可知，所以靠运行期守卫：

```qma
// 原来：jl（有符号）   i0 < LIMIT → 快路
// 现在：jb（无符号）   i0 <u LIMIT → 快路
```

**负数的无符号值极大**，`jb` 必然不成立 → 自动落回原来的除法路径。
用有符号 `jl` 就挡不住负数（负数一定小于正的 LIMIT，会走快路并算错）。

## 效果

| 指标 | 之前 | 之后 |
|---|---|---|
| `parfor` 加速比（40M 次，4 核） | **1.10×** | **3.29×** |
| 串行耗时 | 138 ms | 139 ms |
| 并行耗时 | 125 ms | **42 ms** |

**接近理想值**（同机 C+pthread 3.59×）。生成码验证：worker 热循环里
`mul rdx`（魔数除法）消失，快路只剩 6 条指令：

```
400cfa: cmp  r14,r15      ; 无符号守卫 i <u LIMIT
400cfd: jb   400d45       ; 走快路
400d45: mov  r8,rbx       ; 直接用递增计数器
400d48: add  r13,r8       ; 累加
400d4b: add  rbx,0x7      ; v += C
400d52: sub  rax,0xd      ;
400d56: cmovns rbx,rax    ; 条件回绕
```

## 单核无退化

76 项总耗时 68453 → 68598 ms（**+0.21%**，噪声内），70 项持平。

`b15_loopsum` 全量跑显示 +11.4%，复测（各 3 次）为
旧 1345–1387 ms vs 新 1314–1397 ms，**在噪声内，不是回归**。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增 `_mod_ind_param_init`（判 i0 是否来自形参）；`_opt_mod_ind` 允许形参初值；`_mod_ind_apply` 支持运行期初值计算；守卫由 `jl`(0x8C) 改 `jb`(0x82) |

## 验证

| 命令 | 结果 |
|---|---|
| 76 个基准 checksum vs C | **76/76 一致** |
| 自举两代 | 逐字节不动点 |
| `parfor` vs `for` 同区间 | 结果一致，加速 **3.29×** |
| 负数起点（`burn(-500000, 500000)`） | 与基线编译器结果一致 |
| 单核 76 项总耗时 | +0.21%（噪声内） |
| `python3 tools/dev/check_docs.py` | PASS |

复核命令：

```bash
cd /root/Quelmara/Quelmara
cat > /tmp/pb.qma <<'Q'
fn main() {
    let n = 40000000
    let t0 = now_ns()
    let mut s = 0
    let mut i = 0
    while i < n { s = s + (i * 7) % 13  i = i + 1 }
    let serial = now_ns() - t0
    let t1 = now_ns()
    let mut p = 0
    parfor i in 0..n reduce p { p = p + (i * 7) % 13 }
    let par = now_ns() - t1
    print(s == p)
    print(serial)
    print(par)
}
Q
wine build/qlmc.exe build /tmp/pb.qma -o /tmp/pb --target elf
chmod +x /tmp/pb && /tmp/pb     # true / ~139ms / ~42ms
```

## 已知边界 / 遗留

- **块数仍固定 4**（编译期常量）。应该有 `cores()` 内建或启动时探测，
  让块数跟机器走。qlmc 目前没有 `cores()`。
- 只支持 `acc = acc + expr` 形态的归约（`*=`、`min`/`max` 未做）。
- 无 `reduce` 的 `parfor` 仍串行降级（纯副作用循环无法证明安全）。
- `break`/`continue` 在 `parfor` 体内语义未定义。
