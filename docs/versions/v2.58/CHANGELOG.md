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

## 矩阵扩到三/四个平台

```yaml
posix:
  matrix:
    include:
      - os: ubuntu-latest   # x86_64 Linux + GCC
      - os: macos-latest    # arm64 macOS（Apple Silicon）+ clang
      - os: macos-13        # x86_64 macOS（Intel）+ clang，标实验性
        experimental: true
```

`macos-13` 加 `continue-on-error: ${{ matrix.experimental || false }}` ——
这个 runner 型号可能被 GitHub 回收，别让它拖红整个 run。

现在拿到的对照：

- **同 OS 不同架构**：macOS arm64 vs macOS x86_64
- **同架构不同 OS**：Linux x86_64 vs macOS x86_64
- **同语言不同后端**：Windows 上 `quelmara` vs `quelmara0`

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
- `macos-13` 是实验性平台，取不到数不影响结论。
- posix 的 `quelmara0` 数字**不能**直接和 Windows 的 `quelmara` 比 ——
  那是"参考编译器 vs 自举编译器"，不是"平台差异"。
