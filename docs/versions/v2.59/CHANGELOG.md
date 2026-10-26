# v2.59 — LICM 默认开启：两个潜伏 bug 一起挖出来

- 日期：2026-10-26
- 任务：把 `opt_licm` 从"默认关闭（已知会崩）"变成默认开启，并根修
  "x64 线性扫描分配器布局敏感段错误"
- 影响面：`tools/stage0/qlm_opt.py`（`_skip_pass` / `loop_regions`）、
  `tools/stage0/qlm_native.py`（`Enc.mov8_mr` / `--dump-ir-json`）、
  `tools/stage0/qlm_cli.py`（`--dump-ir-json`）、新工具
  `tools/qlm_licm_audit.qma`、新夹具 `tests/t144_licm_bytes.qma` /
  `tests/t145_licm_multiedge.qma`

## 结论先说

"LICM 会触发 x64 分配器的布局敏感段错误"这条记录是**误判**。真正的两个
bug 都不在分配器：

| # | 位置 | 错误 | 表现 |
|---|---|---|---|
| A | `Enc.mov8_mr` | `mov byte [mem], reg` 在 reg 4..7 时漏 REX，被编成 `ah/ch/dh/bh` | 写进去的是**另一个寄存器的值**；该值若是长度/偏移 → 越界写（段错误），否则静默错值 |
| B | `loop_regions` | 一个循环头一条回边 → 多回边（`continue`）时区间残缺 | 循环携带的值被当不变量外提 → 误编译 |

两个都是"LICM 改变布局后才现形"的潜伏 bug，所以历史上看起来像"分配器
对布局敏感"。分配器本身清白：审计工具复算的区间与分配，与
`qlm_native.allocate()` 逐 vreg 完全一致。

## 新增：`--dump-ir-json` + `tools/qlm_licm_audit.qma`

`--dump-ir` 以前只有 Python repr，自研语言写的工具吃不了。现在
`quelmara build x.qma --dump-ir-json` 输出 `{"fns":[{name,nv,instrs}]}`。

审计工具用 Quelmara 写（`docs/00-convention`：只读分析工具用自研语言），
`tools/qlm_licm_audit.qma` 做四件事：

1. 对比 LICM 开/关两份 QuIR：函数、指令数、vreg 数、第一处差异 + 上下文；
2. 逐 vreg 的 def/use 位置与**活跃区间**（含回边扩展、跨调用约束）；
3. **复算线性扫描**：寄存器分配、溢出槽、帧大小、callee-saved 用量；
4. 报三类问题：同寄存器区间重叠 / 溢出槽复用 / `store8` 的
   base+index+src 全 <8 且 src 落在 4..7（字节寄存器无 REX 的触发条件）。

辅助模式：`--alloc`（机器可读分配表，供 `build/licm/xcheck.py` 对拍）、
`-v`（逐 vreg 区间）、`--trace-v N`（单个 vreg 的每次出现）、
`--fn NAME`（只看一个函数）。

**可信度**：`build/licm/xcheck.py` 用编译器自己的 `allocate()` 复算同一份
JSON，与工具输出逐 vreg diff —— `t1` 的 off/on 两侧全部一致。工具的可信度
是这一步换来的，不是"看起来对"。

## 修法

**(A) `Enc.mov8_mr`**：

```python
r = rex(r=src, x=index, b=base)
if not r and 4 <= (src & 7) <= 7:
    r = b"\x40"          # 强制 REX，让 4..7 落在 spl/bpl/sil/dil
```

`setcc` 早就单独处理过这条规则，`mov8_mr` 漏了。全库只有这两处有裸字节
reg 字段。

**(B) `loop_regions`**：按循环头合并、取最远回边。区间 =
`[循环头, 最远回边]`，会把"跳出路径上的指令"也算进循环体（它们确实在回边
之前），对 8 个用它的 pass 都只会更保守。

## 默认值变化

| 环境变量 | 之前 | 现在 |
|---|---|---|
| （不设） | LICM **关** | LICM **开** |
| `QLM_ENABLE_LICM=1` | 开（已知会崩） | 开（等价默认） |
| `QLM_ENABLE_LICM=0` | — | 关（兼容保留） |
| `QLM_DISABLE_LICM=1` | — | 关（新） |
| `QLM_SKIP_PASSES=opt_licm` | 关 | 关 |

验证：默认配置与 `QLM_ENABLE_LICM=1` 产物**逐字节相同**；
`QLM_DISABLE_LICM=1` 与 `QLM_SKIP_PASSES=opt_licm` 逐字节相同且不同默认。

## 复现（三个层次）

| 复现 | LICM=0 | LICM=1（修前） | LICM=1（修后） |
|---|---|---|---|
| `build/licm/t1.qma`（字节往返） | `1..8` | `0 0 0 0 0 0 0 0` | `1..8` |
| `build/licm/m2.qma`（两行 CSV） | `2 3 a 3` | `2 5 a ` | `2 3 a 3` |
| `tests/t113_csv.qma` | `csv ok` | `assert failed: 三列` | `csv ok` |

前两个分别对应 bug A / B；`t1` 只关掉 A 的那两行就会失败，
`t145_licm_multiedge` 只在旧 `loop_regions` 下失败 —— 两个夹具各自
锁住一个根因。

## 回归

`tests/run_win_tests.py` 默认配置（LICM 开）：**PASS=290 FAIL=0 SKIP=1**
（SKIP 是 WSL 被沙箱拦下的交叉验证）。新增两项：

- `t144_licm_bytes`：字节存储写/读往返 + 不变量外提 + `memcpy` 字块/尾字节；
- `t145_licm_multiedge`：`continue` 造成的多回边下，循环携带值不得外提。

## 收益（本机，min of 3，`QLM_DISABLE_LICM=1` vs 默认，双向对照）

| 基准 | LICM 关 | LICM 开 | 变化 |
|---|---|---|---|
| b1_int | 41.9 | 38.0 | **−9.3%** |
| b6_hash | 45.2 | 42.5 | **−6.0%** |
| b8_threads1 | 340.3 | 318.6 | **−6.4%** |
| b8_threads4 | 109.6 | 104.1 | **−5.0%** |
| b9_json | 30.9 | 27.4 | **−11.3%** |
| b5_string | 81.4 | 86.0 | +5.7% → 复测（reps 5，两轮）86.3/84.9 vs 82.8/78.5，**实为更快**，首轮是噪声 |
| b2_float / b3 / b4 / b7 | — | — | 差异 ≤1%（噪声内） |

10 个基准的**校验和全部一致**（优化不改变输出）。本机测量噪声大（单次抖动
±40%），这组数只能做同表横向比较；权威数字要等 CI 的 `bench.yml`。

## 待办

- CI 上重跑一轮 `bench.yml`，把"LICM 默认开启"的权威收益补进 `06-status.md`
  （本机数字只作为方向）。
- `opt_licm` 自身仍是"只外提绝不陷入的纯运算"，没有做"外提代价 vs 收益"
  的估算：区间暴涨到整个函数会挤掉寄存器（`m2` 里 26 个溢出槽 vs 16）。
  下一步可以在外提前估计"新增溢出数"，超过阈值就不外提。
- `b5_string` 首轮 +5.7% 的假信号值得记一笔：**同一台机器上，单轮 3 次
  最小值的 5% 差异仍然不可信**，复测到两轮一致才能下结论。
