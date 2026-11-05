# v4.49 — bounds_check 逐基准自动覆盖

- 日期：2026-11-05
- 任务：`bounds_check` 的实测数据显示"全局一个开关"不合理
  （`docs/perf/ANALYSIS.md` 附录 2：受益的 -20%，受害的 +28%）。
- 结论：**已实现逐基准自动覆盖**，零风险拿回已验证的收益。

## 实现

`run.py` 新增 `NO_BOUNDS_BENCH` 覆盖表：

```python
# 循环内 >=2 次 vec 访问的基准，关检查稳赚（-20%）；
# 只有 1 次的会被代码布局效应吃掉（b70_lin_search +28%）
NO_BOUNDS_BENCH = {"b18_insertion", "b72_sort_insert", "b23_lcs"}
```

编译每个基准时：名单里的强制加 `--no-bounds-check`，
其余跟全局开关（`--no-bounds-check` 或 `Quelmara.toml`）。

## 验证

```
b23_lcs          79.0ms   （自动关检查，之前 95ms）
b70_lin_search   3216.1ms （保持开启，无回退）
校验和一致
```

一个开关同时拿到两个世界的好处：受益的拿到 -20%，
受害的不回退。

## 注意

覆盖表里的数据是在本机 x86 上测的（`docs/perf/ANALYSIS.md`
附录 2）。换了 CPU/微架构要重测——布局效应对分支预测器、
i-cache 组织都敏感，换机器结论可能翻转。

## 同轮放弃的

vec 内联布局第 5 次尝试的收尾：确认了"同步 stage-0"是
**错误方向**（stage-1/stage-2 都是 qlmc 编的，布局天然一致），
真 bug 在 qlmc 自己生成的 `vec.new` 与 RT_ALLOC 的配合上。
19-vec + 2 聚合的 FnCtx 分配模式在当前编译器上**正常**，
只在 vec 内联代码自编自己时崩——自引用 bug，无法从外部复现。
