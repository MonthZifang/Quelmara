# v2.79 — 性能门禁自测在 runner 上偶发 `FileNotFoundError`（退避重试）

- 日期：2026-10-27
- 任务：修 CI 的 perf job（不是性能本身）
- 影响面：`tools/dev/bench_gate.py`（`run_once` / `measure_noise`）

## 症状

CI 的 perf job 在 v2.72 之后一直红，报的是**门禁自测**的第二条：

```
[FAIL] 同产物 --check 退出码 0（…subprocess.py, in _execute_child
FileNotFoundError: [WinError 2] The system cannot find the file specified
```

本机 12/12 全过，runner 上必挂 —— 而 `--update`（同样构建、同样执行）是过的。

## 判断

`build()` 里已经查了 returncode 和产物存在性，所以**产物确实写出来了**，
是紧接着的 `CreateProcess` 说"找不到文件"。这是 GitHub Windows runner 上
Defender 的典型行为：新写出的 exe 先被扫一遍，扫描窗口内
`CreateProcess` 返回 `ERROR_FILE_NOT_FOUND`，几百毫秒后就正常。

## 改法

- `run_once` 只对 `FileNotFoundError` **退避重试**（8 次，0.15 s 起递增，
  合计约 5 s），其它错误照旧立刻抛 —— 不掩盖真问题。
- `measure_noise` 在自己跑之前补一次"产物不在就构建"，不再依赖
  `measure()` 一定跑在前面（单独调噪声闸时以前会直接 FileNotFoundError）。

本机：`bench_gate_test` **PASS=12 FAIL=0**（与改动前一致）。
