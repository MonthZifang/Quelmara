# v3.87 — 收 §7.47：不是源码缺陷，是本地 `build/qlmc.exe` 陈旧

- 日期：2026-11-02
- 任务：修 v3.86 登记的严重缺陷 §7.47（`while flag && ...` + `if/else` 里
  循环只跑一轮）。
- 结论：**源码里没有这个缺陷**。复现来自磁盘上一个陈旧二进制。
- 影响面：`tests/selfhost/s47_flagloop.qma`（头部重写 + **正式登记**）、
  `tests/qlmc_test.py`（CASES 加 s47）、`docs/07-gaps.md`（§7.47 收尾）、
  `docs/06-status.md`（§3.125）
- 代码改动：**无**（`bootstrap/qlmc/qlmc.qma` 一行未动）

## 定位过程

v3.86 记录的复现是：stage-0 打 `3`，qlmc 打 `1`。v3.87 先做了一件之前
没做的事 —— **确认手上那个 `build/qlmc.exe` 是从哪份源码编出来的**：

```
$ stat -c '%y' build/qlmc.exe
2026-11-02 14:05:40 +0000

$ git log -1 --format='%h %ad' --date=iso
b1dd0cc 2026-11-02 15:04:54 +0000      # HEAD 比那个二进制晚 1 小时

$ git log -S_opt_flag_loop --oneline -- bootstrap/qlmc/qlmc.qma
(空)                                    # 该 pass 从未进入任何提交
```

那个二进制是 14:05 用一次**已完全回退**的 `_opt_flag_loop`（"标志位循环 →
break"，v3.84 的失败实验）编出来的。它带着一个半成品优化，而该优化**从未
被提交过**，所以源码树是干净的。

## 验证

从 HEAD 重建 qlmc（`python tools/stage0/qlm_cli.py build
bootstrap/qlmc/qlmc.qma -o build/qlmc_new.exe --target win -j4`，10m36s）：

| 输入 | stage-0 | 旧 `build/qlmc.exe`（14:05） | 从 HEAD 重建（16:19） |
|---|---|---|---|
| `/tmp/g21/t.qma`（最小复现） | `3` | `1` ❌ | `3` ✅ |
| `tests/selfhost/s47_flagloop.qma`（12 行） | 12 行 | 3 行不同 ❌ | **逐字节一致** ✅ |

## 为什么 CI 一直是绿的

`tests/qlmc_test.py` 每次开跑都先执行

```python
build_with([PY, CLI, "build", SRC_QLMC, "--target", "win", "-o", QLMC], QLMC)
```

**从源码重建被测编译器**，再拿它跑差分。所以 CI 从来没见过那个坏二进制 ——
只有"手动 `wine build/qlmc.exe`"这条路会踩到它。这也解释了为什么 §7.47
在 CI 全绿的情况下"存在"了整整一版。

## 那个误导信号也解释得通了

v3.86 记录："逐个 `QLM_SKIP_PASSES` 跳过 8 个 pass，**每一个都能让结果变正确**"，
并据此推断是"多 pass 状态耦合"。

真实原因是那个二进制里**混进了一个半成品 pass** —— 扰动任何一环都会改变它的
行为。源码里没有这个 pass，自然也就没有这个耦合。**"跳过任何一个都能修好"
不是耦合的证据，而是"被测对象本身有问题"的信号。**

## 保留的资产

`s47_flagloop.qma` **v3.87 起正式登记**进 `tests/qlmc_test.py` 的 CASES
（v3.86 因"怕 CI 常红"而故意不登记）。它现在钉住的是另一件事：

> 任何把 `while go == 1 && ...` 里的 `go = 0` 改写成 `break` 的优化，
> 都会在这里翻红。

这正是 v3.84 那次失败的形状（`go` 在循环外仍被读取 / 被重新赋值 / 参与
返回值 / 在循环内被重新置 1 —— 夹具 6 种形态全覆盖）。

## 教训（已写进 `docs/07-gaps.md` §7.47）

1. `build/` 是**产物目录**，不是可信输入。它不入库，也没人管它的新鲜度。
2. 任何"我复现了"的结论，都必须先 `rm -rf .qlmcache` 重建，或直接用
   `tests/qlmc_test.py`（它每次重建）。
3. 差分测试的**被测编译器必须来自当前源码** —— 否则测的是历史。

## 回归

`tests/qlmc_test.py`：**PASS=102 FAIL=0**（含新增 s47，比 v3.86 多 2 项）。
