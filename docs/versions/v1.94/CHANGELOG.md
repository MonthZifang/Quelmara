# v1.94 — 性能回归门禁：把"感觉变慢了"变成退出码

- 日期：2026-10-24
- 任务：`07-gaps.md` §3「性能回归门禁」🟡 → ✅。原状是"`bench --threshold` 可用，但未进 CI"。
- 影响面：工具链（新增 `bench/gate_bench.qma`、`tools/dev/bench_gate.py`、`bench/perf_baseline.json`）、
  测试（`tests/bench_gate_test.py`）、CI（新增 `perf` job）、文档

## 为什么不是"把 `bench --threshold` 直接塞进 CI"

`quelmara bench` 量的是**进程墙钟**（含 ~426 ms 冷启动），基线是"某台机器上的绝对毫秒"。
直接塞进 CI 只有两种结局：阈值放大到 300% 变成装饰，或者天天假红、最后被人加 `continue-on-error`。
两个结局都等于没有门禁。

所以这一版换的是**被测对象**和**判定口径**，不是把旧命令接上 CI：

| 问题 | 做法 |
|---|---|
| 进程启动噪声盖过被测代码 | 夹具用进程内 `now_ns`（`bench/gate_bench.qma`） |
| 换机器绝对时间不可比 | 同一进程里跑校准形状 `QLMCAL` 做分母，比"比值" |
| 跨时间点判定会带上机器状态漂移 | 基线阈值 25% + 噪声闸；CI 改用**同机交错 A/B**（15%/20%） |
| "变快了因为算错了" | `QLMDIGEST` 与基线不一致直接失败，不看时间 |
| 门禁本身没人验 | `tests/bench_gate_test.py` 把"伪造回归必须判失败"钉成 12 项 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `bench/gate_bench.qma` | **新增（Quelmara 写）**：6 个固定形状（arith / branch / memscan / strbuild / mapstr / sha256）+ 1 个校准形状，进程内 min of 3，输出 `QLMBENCH` / `QLMCAL` / `QLMDIGEST` |
| `tools/dev/bench_gate.py` | **新增**：解析协议 → 校准归一化 → 双模式判定（本机基线 / 同机交错 A/B）→ 噪声闸 → 校验和与体积硬判；`--update` / `--check` / `--ab REV` / `--json` |
| `bench/perf_baseline.json` | **新增**：本机基线，key = 平台/架构/**CPU 型号**/后端 |
| `tests/bench_gate_test.py` | **新增**：12 项自测（建基线 / 同产物 PASS / 伪造 2× 回归必须 FAIL / 校验和 / 体积） |
| `.github/workflows/ci.yml` | **新增 `perf` job**：门禁自测 → `--ab origin/<base>` 同机 A/B（阈值 20%），独立 job 免得与功能回归抢 CPU |
| `docs/05-toolchain.md` | 新增 §1.3 性能回归门禁（协议 / 两种模式 / 三条设计决定）；§5.2 登记脚本；§6 CI 改三个 job；§7 开发循环加门禁命令 |
| `docs/06-status.md` | 新增 §3.11（基线值 / 判定稳定性 / 耗时 / 两条口径）；§1 登记门禁自测 |
| `docs/07-gaps.md` | §3 该行 🟡 → ✅（写清四条边界）；§8 推进顺序同步 |

## 三条设计决定（都是被噪声逼出来的）

1. **归一化**：绝对纳秒换机器就不可比，用同一进程里的标量整数链做分母。
   它约不掉核数/缓存/内存带宽，所以基线 key 里带 CPU 型号——**换机器只 SKIP，不误判**。
2. **交错执行**：A/B 不是"先跑完 A 再跑完 B"，而是 A/B/A/B…。先跑完一边会把整段
   机器状态漂移算到后一边头上（实测同一份代码能漂 ±10%，方向随负载变）。
3. **噪声闸（回归必须大于噪声）**：每个形状先算自己的离散度，本次差值没超过它就只标
   `noisy` 不判红；判红要求 `Δ > max(阈值, 离散度)`。把噪声当回归，会训练出
   "看到红就重跑"的习惯——那等于没有门禁。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/bench_gate_test.py` | **PASS=12 FAIL=0**（伪造 2× 基线 → 退出码 1；校验和/体积各自拦得住） |
| `python tools/dev/bench_gate.py --check` | **PASS**：两次判定 Δ 在 −6.5…+7.7% 与 −13.6…+7.3% |
| `python tools/dev/bench_gate.py --ab HEAD` | **PASS**：Δ −4.7…+4.0%（HEAD `bb145a1` vs 工作区） |
| `python tools/dev/bench_gate.py --ab HEAD`（同一份代码两边） | Δ −3.0…+4.8% → A/B 噪声底 ≈5%，15% 阈值是它的 3 倍 |
| `python tests/run_win_tests.py` | 跑到 **PASS=201 FAIL=0** 时被另一条轨的在途用例 `tests/t118_derive_enum.qma`（尚未落盘）打断；与本版改动无关，本版新增文件只由 `bench_gate_test.py` 驱动 |

## 已知边界 / 遗留

- **不是微架构计数器**：没有 cycles、分支失败率、缓存命中；只量墙钟。
- **不做统计显著性检验**：min-of-N + 离散度闸，够用但不严格（要严格得跑 Mann-Whitney 之类）。
- **基线只对同 CPU 型号生效**：换机器要 `--update`；这是"宁可 SKIP 不假红"的取舍。
- **CI 上生效的是 A/B 那一档**：基线模式在 runner 上会 SKIP（key 对不上），这是有意的。
- **形状只有 6 个**：覆盖算术/分支/内存/字符串/哈希表/加密热路径，不含网络与并发
  （那两类要真实对端，已分别在 `06-status.md` §3.5 与 gzip/HTTP 互操作里量）。
- 基线里记的是 `--update` 那一刻的编译器口径（本版是 qlm 1.92.0）。版本继续前进后
  若判定开始漂移，先确认是语义改动（校验和会变）还是真回归，再决定是否 `--update`。
- 顺带发现：`--no-opt` 在这 6 个形状上**不变慢**（紧循环，优化器能做的有限）——
  已写进 `06-status.md` §3.11，避免以后有人拿它当"优化没生效"的证据。
