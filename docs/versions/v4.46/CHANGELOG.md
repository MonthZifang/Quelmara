# v4.46 — `[build] bounds_check` 在 qlmc 里真正生效

- 日期：2026-11-05
- 任务：`Quelmara.toml` 里早就有 `[build] bounds_check`，但只有 stage-0 读，
  qlmc 一直忽略它。
- 结论：**已接通**，热循环收益明显。

## 实现

新增全局状态 `SW_NOBOUNDS` + 命令行 `--no-bounds-check`。
`_vec_check` 开头：

```quelmara
if _no_bounds() == 1 {
    return          // 整段越界检查省掉
}
```

`run.py` 读 `[build] bounds_check`，为 `false` 时自动加 `--no-bounds-check`，
并打印一行说明。

## 收益（实测，Linux ELF 后端）

| 基准 | 有检查 | 无检查 | 变化 |
|---|---|---|---|
| `b23_lcs` | 95ms | **76ms** | **-20%** |
| `b28_matrix` | 804ms | 797ms | -1% |
| `b1_int` | 67ms | 68ms | 噪声内 |

`b23_lcs` 收益大是因为它内层循环每轮 3 次 vec 访问（`cur.get`/`cur.set`/
`prev.get`），每次 2 条 `cmp+jcc`，省掉后直接可见。

校验和全部一致（`b23_lcs` = 1498，`b28_matrix` = 960991321），
自举五级链 42/42 + 不动点 PASS。

## 用法

```bash
# 命令行
python bench/speed/run.py --langs quelmara c --no-bounds-check

# 配置文件（Quelmara.toml）
[build]
bounds_check = false
```

## 注意

关掉越界检查后，**越界访问是未定义行为**（不是干净 OOM 退出）。
仅用于性能对比或已充分验证过的程序。

## 仍未做

* vec 内联布局（v4.44/v4.46 两次失败，见 `docs/perf/ANALYSIS.md` 附录）
* 寄存器分配改进（`N_VARREG=7` 已占满 callee-saved）
* SIMD 向量化（缺循环向量化分析）
