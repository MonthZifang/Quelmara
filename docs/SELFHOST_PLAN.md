# 后端重构（stage-1 自举）执行计划

> 2026-10-21 定稿。目标：**把 `tools/stage0/` 的 Python 编译器逐个组件换成 Quelmara 自己写的实现**，
> 最终 `bootstrap/` 能独立编译自己（三轮固定点）。
> 现状：**2/9**（词法 ✅、声明级 parser ✅；函数体 94 一致 / 636 分叉）。
>
> 本文是排期的唯一权威；每个组件的"是否支持"仍以 `docs/GAPS.md` 为准。

## 0. 为什么不能"一次性重写"

编译器是自指的：新后端要能编译自己，先得有能编译它的东西。可行路径只有一条——
**保持 stage-0 可运行，逐组件替换，每个组件用"对拍门禁"证明等价，再切主链路**。
一次性重写会失去 oracle：出错时无法判断是"新实现错"还是"规范没写清"。

三条铁律（沿用 `docs/SELFHOST.md §6`）：

1. `tools/stage0/` 冻结：只修 bug、不加语言特性；
2. 任何组件切换前，必须先过该组件的**逐字节/逐节点**对拍；
3. CLI 必须打印实现来源（`[qlm:stage0]` / `[qlm:stage1]`），避免"以为在测自举，其实在跑 Python"。

## 1. 组件顺序（按依赖，不按难度）

```
词法 ✅ → 语法(声明) ✅ → 语法(函数体) 🟡 → 类型推断 → AST→QuIR → 优化
                                                              ↓
                                                    x86_64 编码 → ELF 写出 → PE 写出
                                                              ↓
                                                        AArch64 发射
```

顺序不能反：
- **类型推断必须在 IR 之前**：QuIR 的 str/bool/chan/map 标签由前端写入，推断缺失时 IR 无法定型；
- **IR 必须在编码器之前**：编码器只是 QuIR → 机器码的查表；
- **PE 在 ELF 之后**：两者共享 QuIR 与编码器，只差文件格式与导入表；先做 ELF 能最快闭环；
- **AArch64 最后**：它验证"QuIR 架构无关"，是 IR 正确性的外部证据，不是产品必需。

## 2. 每个组件的验收门禁

| 组件 | 门禁 | 现有工具 | 目标 |
|---|---|---|---|
| 语法（函数体） | S 表达式逐语句一致 | `tests/bodydiff.py` | 分叉 636 → **0**，SKIP 不同步 25 → 0 |
| 类型推断 | 负向夹具两阶段**同样报错、同类别**；正向夹具类型串一致 | 需新建 `tests/typeckdiff.py` | 100% |
| AST→QuIR | `--dump-ir` 逐指令一致（除 vreg 编号） | `tests/irdiff.py` 扩展 | 100% |
| 优化 | 优化前后 IR 语义等价 + 与 stage-0 输出一致 | `tests/irdiff.py` | 全部 pass 覆盖 |
| x86_64 编码 | 反汇编逐指令一致 + 确定性 | `tests/emitdiff.py` | 100% |
| ELF 写出 | 魔数/入口/段表/确定性 + 产物可执行 | `emitdiff` + 执行 | 100% |
| PE 写出 | MZ/PE32+/导入表/重定位 + 产物可执行 | `run_win_tests.py` | 96+ 项 |
| AArch64 | IR 逐字节 + 模拟器执行 | `tests/irdiff.py` + `a64_emu.py` | 50/50 |

**切换规则**：门禁全绿 → CLI 默认走 stage-1 → 保留 `--stage0` 回退 → 观察一个版本 → 删回退。

## 3. 分阶段（每阶段可独立交付）

### Phase 1：函数体 parser 收敛（当前主线）

- 现状：`bootstrap/parser/qlm_parse.qma` 1440 行，Phase 1 核心子集；`dump 一致 94 / 分叉 636`。
- 已知失败模式（按清单逐个修）：
  1. `while` 条件里带调用（`while len(s) > 0`）解析失败；
  2. `match` 表达式出现在表达式位置（`return match x {…}`）被当标识符；
  3. 若干空格/换行细节。
- 验收：`bodydiff` 分叉 = 0；CI 增加该门禁。
- 工作量：**1–2 轮**（每轮 = 一次会话）。

### Phase 2：类型推断（`bootstrap/typeck/`）

- 先做**类型表示与单态化命名**（`__opt_int` / `__res_int_str`），再做表达式定型、再做负向诊断。
- 门禁：`tests/typeckdiff.py`（新建）—— 对每个 `.qma` 比较"类型串序列"；负向夹具比较错误类别。
- 风险：负向诊断的**错误类别**在 stage-0 里是散落的 `SyntaxError` 文案，需要先抽成枚举
  （这是 stage-0 的合法修 bug 范围）。
- 工作量：**2–3 轮**。

### Phase 3：AST→QuIR（`bootstrap/ir/`）

- 先只覆盖 `let/int 算术/print/if/while/return`（够跑 hello + fib），再扩 struct/enum/vec/map/chan。
- 门禁：`--dump-ir` 归一化后逐条一致（vreg 重编号、label 名归一）。
- 关键约束：**QuIR 非 SSA**——循环变量必须原地更新（`dst == src`），这是最容易写错的一条。
- 工作量：**3–4 轮**。

### Phase 4：x86_64 编码 + ELF 写出

- 编码器是查表活：ModRM/REX/SIB 每个指令一个函数，靠 `emitdiff` + capstone 反汇编对拍。
- ELF 写出：文件头 + 段表 + 入口 + 重定位；先静态无 libc（与 stage-0 一致）。
- 验收：`hello.qma` 产出的 ELF 能在 Linux 跑出同样输出；`emitdiff` 10/10 → 全量。
- 工作量：**3–5 轮**（编码器可并行拆给多人）。

### Phase 5：PE 写出 + 导入表

- 复用 Phase 4 的编码器，只换文件格式与 `kernel32/ws2_32` 导入表。
- 验收：Windows PE 回归 113 项由 stage-1 产物跑通。
- 工作量：**2–3 轮**。

### Phase 6：优化器（`bootstrap/opt/`）

- 按"收益/风险"排序移植：常量折叠 → 复制传播 → DCE → 强度削减 → 魔数除法 → 越界消除 → 展开 → 调度。
- **LICM 最后**，且必须先修 x64 分配器布局敏感 bug（`docs/PERF.md §4`）。
- 验收：每个 pass 前后 IR 语义等价（用 stage-0 产物做 oracle）。
- 工作量：**3–4 轮**。

### Phase 7：三轮固定点

```
stage0(源码) → S1 产物
S1(源码)     → S2 产物
S1 == S2（逐字节）→ 自举成立
```

- 前置：Phase 1–6 全绿 + `stage-0` 只读。
- 验收：`tools/dev/selfhost_status.py` 输出 **9/9**；删除 `tools/stage0/`（C99 后端永久保留为交叉验证）。

## 4. 与"性能"的关系（重要）

**先正确，再快。** 本轮写标准库时抓到两个误编译（见 `docs/GAPS.md §6.5`）：

1. 循环内用调用结果做 `substr` 长度、结果又 push 进 `vec[str]` → 错串；
2. `\xNN`（≥0x80）被 UTF-8 二次编码。

第 1 条说明**寄存器分配/生命周期还有洞**。在这种状态下继续加优化（LICM、SIMD），
等于在漏的地基上盖楼——所以性能路线的前置条件是：

```
修 #1 → 重开 LICM 并压测 → 越界消除下半场（动态长度）→ SIMD（先 canonical reduction）
```

顺序反了就会重演"LICM 默认禁用"这种妥协。

## 5. 现在就能开工的三件事（按顺序）

1. `tests/bodydiff.py` 分叉清单里挑 `while + call` 与 `match` 两类，修 `qlm_parse.qma`（Phase 1）；
2. 把 stage-0 的 `SyntaxError` 文案抽成**错误类别枚举**，为 Phase 2 的负向对拍铺路；
3. 给 `tests/irdiff.py` 加"归一化 vreg/label"选项，让 Phase 3 能真正逐条对拍。

三件事都不需要新语言特性，且每件都有可跑的验收命令。
