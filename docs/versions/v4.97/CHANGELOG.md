# v4.97 — 修正自举进度统计（2/9 → 8/8）与不动点判定口径

- 日期：2026-11-10
- 任务：核实"核心模块是否全部用自研语言实现"这条目标的真实进度
- 影响面：工具链（`tools/dev/selfhost_status.py`）、文档

## 修掉的是一处**会误导所有决策**的统计错误

`tools/dev/selfhost_status.py` 一直打印 **"组件自举：2/9"**。它按"每个编译阶段
一个目录"去找实现：

```
bootstrap/typeck/  bootstrap/ir/  bootstrap/opt/
bootstrap/codegen/x64/  bootstrap/codegen/elf/  bootstrap/codegen/pe/
```

**这些目录从来不存在。** 实际的自举编译器是**单体**的
`bootstrap/qlmc/qlmc.qma`（20224 行）：词法、语法、降级、优化、寄存器分配、
x86-64 编码、ELF/PE 写出**全在同一个文件里**。它能编出可执行的 ELF64 与
PE32+，并且编自己能到逐字节不动点。

所以那个 2/9 不是"后端还留在 Python"，而是**脚本扫描了错误的路径**。

### 新口径

按**阶段**判定，判据是"`qlmc.qma` 里存在该阶段的实现函数"，并打印**实测行号**
供复核：

| 阶段 | 状态 | qlmc.qma 行号 |
|---|---|---|
| 词法 | ✅ 自举 | 367 |
| 语法 | ✅ 自举 | 1612 |
| 降级/IR | ✅ 自举 | 4721 |
| 优化 | ✅ 自举 | 8694 |
| 寄存器分配 | ✅ 自举 | 8922 |
| x86-64 编码 | ✅ 自举 | 10098 |
| ELF64 写出 | ✅ 自举 | 19180 |
| PE32+ 写出 | ✅ 自举 | 19232 |

**阶段自举：8/8**

## 顺带查清：`tests/bootstrap_test.py` 为什么会 FAIL

原来的不动点判定直接跑 `tests/bootstrap_test.py`，它的 stage-1 是
**stage-0（Python）编出来的**。实测这条路径是断的，而且断在 stage-0 一侧：

- stage-0 编 qlmc 产出 **4,894,720 字节**（4 个节）
- qlmc 自举产物只有 **741,888 字节**（3 个节）
- 两者差 **6.6 倍**
- 用那份 4.89 MB 的产物去编自己 → **栈溢出崩溃**：
  `err:seh:NtRaiseException Exception frame is not in stack limits`

也就是说 **stage-0 生成的代码承载不了 20k 行的 qlmc** —— 是 stage-0 的代码
质量问题，**不是自举链断了**。

真正的自举链是：`build/qlmc.exe`（自举产物）→ 编自己 → s2 → 编自己 → s3。
新脚本用它判定，结果 **✅ 成立（逐字节相同）**。

> 这条差异很重要：如果只看 `bootstrap_test.py` 的 FAIL，会误判"自举坏了"，
> 然后去修错的地方。真实待修的是 **stage-0 的代码质量**（它是自举的对照
> 基准，但已跟不上 qlmc 的增长）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/dev/selfhost_status.py` | 整体重写：按阶段判定（附实测行号）、不动点改用真实自举链、单列"仍在 Python 侧的真实债务" |

## 输出示例

```
阶段自举：8/8
端到端自举（build/qlmc.exe 编自己 → s2 → s3，逐字节相同）：✅ 成立

仍在 Python 侧的部分（真实债务，不是统计口径问题）
  AArch64 后端            805 行  qlmc 只能出 x86-64；A64 仍只有 stage-0 实现
  C99 交叉验证后端        8096 行  仅用于对拍，按设计不移植
  stage-0 参考编译器     13588 行  自举的对照基准，保留但不参与产品链路

代码量：Quelmara 核心 25034 行（bootstrap/）  /  Python stage-0 37338 行
       Quelmara 单体编译器 bootstrap/qlmc/qlmc.qma = 20224 行
```

## 验证

| 命令 | 结果 |
|---|---|
| `python3 tools/dev/selfhost_status.py` | 8/8 阶段 + 不动点 ✅ |
| `python3 tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- **AArch64 后端**仍只有 stage-0 实现（805 行 Python）。qlmc 只能出 x86-64。
  这是自举目标里最大的一块空缺。
- **stage-0（Python）已跟不上 qlmc**：它编 qlmc 会产出 6.6 倍大的坏产物、
  编自己时栈溢出。需要单独评估——是补 stage-0，还是正式宣布 qlmc 为唯一
  编译器（stage-0 只留作历史对照）。
- macOS（Mach-O）后端仍未做。
