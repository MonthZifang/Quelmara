# v3.69 — 新增 `addrdump`：把 VA 映射回函数名

- 日期：2026-11-01
- 任务：排查 §7.18 时反复需要"从差异 VA 反推是哪个函数"，而 PE 里没有
  函数边界信息（qlmc 不发 pdata）。本版把这个能力做成内建命令。
- 影响面：`bootstrap/qlmc/qlmc.qma`（`--addrdump` + `_want_addrdump`）
- 代码改动：**约 25 行**

## 用法

```bash
qlmc build <src.qma> --addrdump -o out.exe
```

编译照常进行，额外把每个函数的 `.text` 相对偏移打到 stdout：

```
ADDR 65564 _prescan_imports
ADDR 69069 _prescan_consts
...
```

配合 PE 节表（`.text` VA=0x1000），即可把任意 VA 映射回函数：

```python
offset = va - 0x1000          # VA → 相对 .text 偏移
# 在 addrdump 输出里找 <= offset 的最大那一行
```

## 为什么需要它

排查 stage-2 缺陷时，反汇编只能给出差异 **VA**（如 `0x114c5`），
而"这是哪个函数"必须靠猜 —— 本轮前几次就是靠 `irdump` 逐个函数试，
**400 个函数 × 2 次 wine 进程要跑 30+ 分钟**（实测跑不完，已终止）。

有了 `addrdump`，一行命令就能定位：

```
0x114c5 → 偏移 0x104c5 → _prescan_imports（起始 0x1001c）
```

## 本轮的连带收获

用它在**一次**编译内就定位到了 §7.18 缺陷的精确位置：

```
IR# 11  S1_FULL:     BINI a=7 b=43 imm=3     ← ×8  (错)
        s1_real365:  BINI a=7 b=43 imm=6     ← ×64 (对)
```

对应源码 `_prescan_imports` 里的 `nodes: vec[Node].new(1)` ——
`Node` 8 字段，步长应为 64（`1 << 6`），被折成了 `1 << 3`。

详见 `docs/07-gaps.md` §7.18 第七次排查。

## 验证

| 命令 | 结果 |
|---|---|
| `qlmc build ... --addrdump` 输出 389 个函数地址 | ✅ |
| VA `0x114c5` 反查 → `_prescan_imports` | ✅ 正确 |
| stage-1 编 qlmc 自己 | ✅ rc=0 |
| 四个文档门禁 | 全 PASS |

> 这个命令的诊断价值超出本次排查 —— 以后任何"从 VA 反查函数"的场景
> 都能直接用，不必再手写 PE 解析或猜函数边界。
