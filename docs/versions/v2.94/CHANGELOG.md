# v2.94 — Windows job 的失败原因现在看得见：FAIL 落盘 + summary 回显

- 日期：2026-10-28
- 任务：工具链 —— CI 可观测性（v2.93 之后 `windows` job 红着，但看不到红在哪）
- 结论：外部拿 GitHub job 日志要 **admin 权限（403）**，annotations 里只有
  `Process completed with exit code 1`。本版把逐条 FAIL 写进
  `build/win_failures.log`，workflow 在失败时把这份清单贴进 **step summary**
  ——那是免费、匿名可读的唯一通道。

## 背景

v2.91 之后 CI 三个 job 里，`linux` 与 `perf` 已经全绿；`windows` 的
`Windows PE 回归` 一步从某个版本起持续红（`a80c6a5`、`0f062f1` 两个 run 都红）。
要修它得先知道哪条 FAIL：

| 通道 | 结果 |
|---|---|
| `GET /actions/jobs/{id}/logs` | **403**（Must have admin rights to Repository）|
| `GET /check-runs/{id}/annotations` | 只有 Node 弃用 warning + `exit code 1`，**没有测试输出** |
| step summary | 免费可读 ✓ —— 本版把 FAIL 清单搬到这里 |

## 改动一：`bad()` 顺手落盘

`tests/run_win_tests.py` 的 `bad()` 在打印之外追加一行到
`build/win_failures.log`（`ok()`/`skip()` 不动；写失败吞 `OSError`，
日志通道绝不能反过来弄崩测试本身）。

## 改动二：workflow 失败时贴清单

`ci.yml` windows job 加一步 `if: failure()` 的 pwsh：文件存在就把内容
包进代码块 `Add-Content $env:GITHUB_STEP_SUMMARY`。成功时什么都不做。

## 改动三：gzip zlib 互操作在非 Windows 上诚实 SKIP

本地跑 `run_win_tests.py`（Linux）暴露了一条**记账错误**：

```
[FAIL] gzip zlib 互操作失败：没有找到 build/gz_*.bin：请先跑 tests/t47_gzip.qma
```

样本 `build/gz_*.bin` 由 `t47_gzip` **在 Windows 上执行**产出；Linux 上
t47 本身是 `skip(...)`，样本必然不存在——可 `gzip_interop.py` 却无条件跑，
把"没有样本"记成 FAIL。改成 `if not IS_WIN: skip(...)`，与 t47 同口径。

> 这条与 v2.90/v2.91 记过两次的"两条路径实现不一致"同源：**Windows 侧的
> 用例假设了 Windows 的执行产物，Linux 侧照跑不误**。区别是这次红的是
> "SKIP 被记成 FAIL"，方向相反但错因相同。

## 验证

| 项 | 结果 |
|---|---|
| `run_win_tests.py`（Linux，跑到超时前） | PASS=59 **FAIL=0**；gzip 段现在正确 SKIP |
| `win_failures.log` | 本地全程无 FAIL 行（新通道自证没误报）|
| 门禁（names/origin/docs） | PASS |

## 下一步（本轮就要做）

推送后等 `windows` job 变红 → 读 step summary 里的清单 → 修真正的 FAIL。
清单里预期会出现哪类问题没有把握：v2.93 的两个后端改动（阈值 60 + 标记
重映射 + guard 认立即数）都同时作用于 PE 产物，而 Windows 执行级回归
是唯一能验证 PE 语义的通道。
