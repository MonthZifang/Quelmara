# v3.00 — 里程碑：2.x 线收口，VERSION → 3.00.0，99 次更新总结

- 日期：2026-10-29
- 任务：把 2.x 线（v2.01–v2.99）收口成里程碑，并按约定在到达 v2.99 后升级为
  **v3.00**，同时写一份横跨 99 次更新的总结报告。
- 影响面：版本号、文档（**无代码改动**——与 v2.00 同口径的纯里程碑版本）

> 99 次更新的完整复盘见同目录 [`REPORT.md`](REPORT.md)。
> 本文只记「这一版做了什么、怎么验证、边界在哪」。

## 为什么需要这一版

2.x 线从 v2.01 的 `std/kv` 批量提交一路走到 v2.99 的 ECDSA P-384，跨度为
**2026-10-24 → 2026-10-28（5 天）、97 个版本目录、99 次编号更新**。

其中三件事在这条线上**改变了项目的性质**，值得单独定版：

1. **自举闭环**（v2.33 → v2.35）：`qlmc` 编出自己，并达成 stage-2 == stage-3 的
   不动点。语言不再依赖 Python 引导层才能产出二进制。
2. **性能进入 C/Go 射程**（v2.46 → v2.79）：`b2_float` 对 C 从 9.4× 收敛到
   **1.00×（持平）**，`b5_string` 0.78×、`b6_hash` 0.99× **快于 C**。
3. **基准搬到 GitHub CI**（v2.54）：跑分从此有权威来源，不再是本机噪声里的读数。

到 v3.00 这个点，"语言 + 编译器 + 标准库 + 工具链全栈自有"这条主张已经有了
可复核的证据链，而不是一份能力声明。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_cli.py` | `VERSION` → `3.00.0` |
| `docs/06-status.md` | 口径日期 → 2026-10-29；补 v3.00 里程碑口径说明 |
| `docs/07-gaps.md` | §6 优先级中已收口的条目更新为 2.x 终态 |
| `docs/versions/v3.00/CHANGELOG.md` | 本文件（新建） |
| `docs/versions/v3.00/REPORT.md` | 99 次更新总结报告（新建） |
| `docs/README.md` | 版本导航补 v3.00 报告入口 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/dev/check_docs.py` | PASS（版本号同源：`VERSION` 3.00 ↔ `docs/versions/v3.00/`） |
| `python tools/dev/check_names.py` / `check_origin.py` | PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 3.00.0` |
| `bash tests/run_tests.sh`（C 后端，容器内 gcc 13） | PASS=15 FAIL=0 |
| `bash tests/run_native_tests.sh`（自研 ELF 后端） | 见 `06-status.md` §1 |

**口径提醒**：本版是里程碑版本，**不引入功能改动**。所有性能与回归数字沿用
v2.99 的实测值，唯一出处仍是 `06-status.md`；本文件与 `REPORT.md` 不复制新数字。

## 已知边界 / 遗留

- **编号空位**：`v2.04` / `v2.06` / `v2.09` 三个目录不存在。它们不是丢失——
  v2.04 在代码注释里被预占但任务被 v2.03 吸收，v2.06 / v2.09 由同期并行轨
  落地后并入相邻版本（`docs/versions/v2.05/CHANGELOG.md` §已知边界 有原始记录）。
  因此 2.x 线是 **99 次编号更新 / 97 个版本目录**，两者不是同一个计数。
- **迟到的收口项**：`b1_int` / `b8_threads1` 对 C 仍是 3.2–4.3×，根因是
  C 侧被 AVX2 完全向量化（见 `06-status.md` §3.34 与 `07-gaps.md` §5），
  不是调用开销或寄存器分配问题。
- **未做的平台**：macOS Mach-O + kqueue、wasm32/64、Android（`07-gaps.md` §4）。
  macOS 缺后端直接导致 CI 基准矩阵里那一列没有 quelmara 的数字。
