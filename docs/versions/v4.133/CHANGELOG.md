# v4.133 — 撤销 b70_lin_search 的越界检查例外（基准公平性，−33%）

- 日期：2026-11-24
- 任务：b70_lin_search 是当前比值最差的基准之一（CI Ubuntu 15.4×）。它是
  唯一被 `KEEP_BOUNDS_BENCH` 强制保留越界检查的基准，依据是 v4.46 时代
  "关检查 +28% 回退"的代码布局效应（`docs/perf/ANALYSIS.md` 附录 2，该附录
  自己也提醒"换了 CPU/微架构要重测"）。本版在 v4.132 编译器上重测该决策。
- 影响面：工具链（基准驱动 `bench/speed/run.py` 的构建策略，不动编译器/语言）

## 重测结果（本机 min-of-9，v4.132 qlmc）

| 构建方式 | min | median |
|---|---|---|
| 保留越界检查（旧策略） | 3069.9 ms | 3072.8 ms |
| 关闭越界检查（本版） | **2051.4 ms** | 2053.0 ms |

比值 **0.668（−33%）**，九轮稳定、无重叠。校验和 qlm/C 逐字节一致
（332667）。结论：附录 2 的代码布局效应在经历 v4.116 之后的多次优化器改动
后早已翻转；关检查现在与 C/Go/Rust 的默认无检查站在同一起跑线，也符合
`run.py` 既定的公平性策略。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bench/speed/run.py` | `KEEP_BOUNDS_BENCH` 由 `{b70_lin_search}` 改为空集；注释记录重测数据与"附录 2 结论只对应当时编译器/微架构" |

## 验证

| 项 | 结果 |
|---|---|
| `python3 bench/speed/run.py --only b70_lin_search --langs quelmara --reps 3` | b70 2053ms（关检查路径），`build_options.keep_bounds_benches=[]`，校验和一致 |
| 显式 `--bounds-check` 强制全开 | 仍可用（保留 `KEEP_BOUNDS_FORCE` 与全局开关），用于回归/安全验证 |
| 旧策略对照（同一 qlmc、同一机器、交替 9 轮） | 0.668（−33%） |
| `python3 tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- 这是**基准驱动策略**修正，不是编译器优化：b70 的语言/编译器代码未变，
  基准数字会因与 C 站在同一起跑线而改善，这是公平性口径的对齐。
- `docs/perf/ANALYSIS.md` 附录 2 的 v4.46 结论保留为历史记录（它明确写了
  "换 CPU/微架构要重测"），本版在 CHANGELOG 与 run.py 注释里标注其已过时。
- CI 权威基准待推送后实测；本机数字只作粗判，不代表 CI 口径。
