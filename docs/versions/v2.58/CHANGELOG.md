# v2.58 — 基准矩阵补全：macOS(arm64/x86_64) + Linux + Windows 五列

- 日期：2026-10-26
- 任务：把性能测试**铺满平台矩阵** —— 之前 posix 那两行只有 C/Go/Python，
  quelmara 在非 Windows 上是空的
- 影响面：`.github/workflows/bench.yml` / `bench/speed/run.py` / 文档

## 之前缺什么

`bench.yml` 有 windows（四语言）和 posix（ubuntu + macos，只有 C/Go/Python）
两个 job。posix 上没有 quelmara，原因是 **qlmc 只有 Windows PE 后端** ——
不是跑不过，是没有产物。

但"同一个语言在 Linux / macOS 上是什么样"恰恰是**适配度**这一栏要回答的。
所以不能就这么空着。

## 做法：加一条 stage-0 列（`quelmara0`）

关键观察：**stage-0（参考编译器）有三个后端** —— `--target win`（PE）、
`--target native`（ELF64，raw syscall）、`--target arm64`。而且
`now_ns()` 在 ELF 后端有实现（`__now_ns` → `clock_gettime`），所以基准的
进程内计时口径在三个平台上是**一致的**。

于是 `run.py` 多一条语言键 `quelmara0`：用 `tools/stage0/qlm_cli.py` 编，
Windows 上 `--target win`、其他平台 `--target native`，posix 上补 `chmod +x`。

**两条 Quelmarara 列的含义（别混淆）：**

| 列 | 编译器 | 后端 | 用来看什么 |
|---|---|---|---|
| `quelmara` | qlmc（stage-1 自举） | 仅 PE | qlmc 的真实水平 |
| `quelmara0` | stage-0（参考实现） | PE / ELF64 | 跨平台适配度；与 `quelmara` 之差 = **后端差距** |

Windows 的 job 同时跑两列，所以同一台机器上能直接读出"自举编译器比参考
编译器快多少"；posix 的 job 跑 `quelmara0`，于是 quelmara 在 Linux / macOS
上也有数字了。

## 第一次跑：Linux 通了，macOS 暴露了一个真缺口

`posix` 的矩阵第一版放了三项（ubuntu / macos-latest / macos-13）。结果：

| 平台 | 结果 |
|---|---|
| `ubuntu-latest` x86_64 | ✅ **quelmara 列跑通了**，10 个基准 × 4 语言的校验和全一致 |
| `macos-latest` arm64 | ❌ `OSError: [Errno 8] Exec format error` |
| `macos-13` x86_64 | ⏳ runner 一直排队（型号可能被回收），40 分钟没起来 |

**macOS 的失败是真缺口，不是配置问题**：`--target native` 在 Darwin 上产出的
仍然是 **ELF64**（stage-0 只有 PE / ELF64 / arm64 三个后端），macOS 需要
**Mach-O**。而 qlmc 只有 PE。所以 quelmara 在 macOS 上**目前没有产物**。

处理方式：
- 矩阵缩回 `ubuntu-latest` + `macos-latest`（去掉排队不靠谱的 `macos-13`）；
- `run.py` 在 Darwin 上**显式跳过** `quelmara0` 并打印原因，不假装跑过；
- 缺口写进 `docs/07-gaps.md` §4 平台表（原本只有一行"❌ 新后端 + 新事件层"，
  现在补上"连带着基准矩阵在 macOS 上没有 quelmara 列"这个后果）。

## 顺带修掉两个**静默失效**的门禁

**① `run.py --markdown` 跳过校验和检查。** 那个分支以前直接 `return 0`，
而 CI 用的正是 `--markdown` —— 于是"某个语言的实现写错了"在 CI 上是静默的，
表照样打出来。校验和一致是整张表的前提（不一致时时间数字一概不能看），
现在抽成 `report_checksums()`，两条路径都走。

**② `| tee` 吞掉退出码。** macOS 那次 python 抛了 `OSError` 并以 1 退出，
但 `python ... | tee bench.md` 的退出码是 `tee` 的 0，**step 报"成功"**。
现在 posix 侧 `set -o pipefail`，Windows 侧显式检查 `$LASTEXITCODE`。

## Linux 的第一批 quelmara 数字（stage-0 后端，run 40281824686）

`ubuntu-latest`（x86_64 + GCC），min of 5，**4 语言校验和全一致**：

| 基准 | quelmara0 | C | Go | quelmara0 / C |
|---|---|---|---|---|
| `b1_int` | 14.4 | 11.3 | 14.9 | **1.27×** |
| `b5_string` | **19.3** | 23.2 | 14.2 | **0.83×** |
| `b6_hash` | **5.8** | 6.3 | 6.0 | **0.92×** |
| `b8_threads1` | 97.0 | 89.7 | 115.3 | **1.08×** |
| `b4_array` | 9.2 | 3.2 | 2.8 | 2.9× |
| `b3_recursion` | 4.3 | 1.2 | 3.7 | 3.6× |
| `b9_json` | 27.7 | 4.6 | 5.7 | 6.0× |
| `b2_float` | 41.0 | 5.6 | 5.7 | 7.3× |
| `b7_sort` | 27.2 | 13.1 | 13.4 | 2.1× |
| `b8_threads4` | 77.1 | 45.1 | 60.5 | 1.71× |

**`b5_string` 与 `b6_hash` 在 Linux 上快于 C**（stage-0 后端！），
`b1_int`/`b8_threads1` 只差 1.1–1.3× —— 因为 **GCC 不像 clang 那样把
`(i*7)%13` 向量化**（Windows 上 C 是 4.3 ms，Linux 上 11.3 ms）。

`b2_float` 7.3× 说明 **stage-0 的 f64 路径还没有 v2.55/2.56 那套优化**
（f64 进 XMM + movaps + 帧常量槽）—— 那是 qlmc 独有的，后端差距一目了然。

## 顺带修掉一个**静默失效的门禁**

`run.py` 的 `--markdown` 分支以前直接 `return 0`，**跳过了校验和检查** ——
而 CI 用的正是 `--markdown`。也就是说"某个语言的实现写错了"在 CI 上是
静默的，表照样打出来。

校验和一致是整张表的前提（不一致时时间数字一概不能看），现在抽成
`report_checksums()`，两条路径都走。

## 本机预检

- 10/10 个基准都能 `--target native` 编出 ELF（本机不能执行 ELF，执行交给 CI）
- `--langs quelmara0 c` 在 Windows 上跑通，**校验和与 C 逐字节一致**
- YAML `safe_load` 通过：2 个 job / windows 10 step / posix 7 step /
  矩阵 3 项

## 已知边界

- `b8_threads4` 在 ELF 后端走 `clone()` + `wait4()`（不是 pthread），
  线程模型与 Windows 的 `CreateThread` 不完全同构 —— 跨平台比加速比时要留意。
- posix 的 `quelmara0` 数字**不能**直接和 Windows 的 `quelmara` 比 ——
  那是"参考编译器 vs 自举编译器"，不是"平台差异"。
- **macOS 没有 quelmara 数字**：缺 Mach-O 后端。这是这一轮最该记住的结论 ——
  "加平台"不是改 YAML，是**先得有那个平台的后端**。
