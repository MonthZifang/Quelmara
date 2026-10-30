# v3.13 — 把"文档说有门禁、其实没有"的四项接进主回归

- 日期：2026-10-30
- 任务：用户要求"继续"；承接 v3.12 结束时的遗留 —— 主回归之外还有一批
  在 `06-status.md` 里记着 PASS、却**不在任何自动门禁**里的脚本
- 影响面：工具链（`tests/run_win_tests.py`）、测试（`tests/gzip_http_test.py`
  重写为自包含）、文档

## 问题：文档记着 PASS，门禁里没有

v3.11 的教训是"没进默认入口的用例 = 不存在"，v3.12 的教训是"用例形状不够极端
等于没测"。本版继续按同一个判据审计，把 `tests/*.py` 与 `06-status.md` 的
`命令` 列逐条对照，发现四项**文档声称有回归、实际只靠人记得手工跑**：

| 脚本 | `06-status.md` 怎么写的 | 在 CI 里？ | 在主回归里？ |
|---|---|---|---|
| `tests/gzip_http_test.py` | "HTTP gzip 端到端" | ❌ | ❌（v3.11 明确登记为遗留） |
| `tests/debugger_test.py` | "PASS（18 项…）" | ❌ | ❌ |
| `tests/doc_test.py` | "PASS=31 FAIL=0" | ❌ | ❌ |
| `tests/bootstrap_test.py` | "五级全 PASS" | ❌ | ❌ |

`bootstrap_test` 那一条最刺眼：**自举不动点是这条轨道的核心指标**，文档里
写着"stage-2 编自己 → stage-3，两者逐字节相同"，而这个断言从来没被任何门禁执行过。

这正是 `00-convention.md` §7 说的那类漂移的变体：**文档不是被改错的，是被
"记下来之后没人执行"放旧的**。数字单一来源能防"同一个指标四个值"，防不了
"这个指标根本没在跑"。

## 改动

### 1. `tests/gzip_http_test.py` 改成自包含

老形态要求**手工先起** `examples/http_gzip.qma`（18080），所以结构上不可能进
自动门禁。改成与 `http_router_test.py` 同构：

| 环节 | 做法 |
|---|---|
| 编译 | 脚本自己调 `qlm_cli.py build` |
| 端口探测 | `bind` 试探；被占 → **退出码 2** |
| 起停 | `Popen` + 6 s 内轮询就绪 + `finally` 里 `terminate`→`kill` |
| 断言计数 | `ok()` 自增（老版本是手写常量，与 v3.11 修 `http_router_test.py` 同一个病） |

**退出码 2 记 SKIP 而不是 FAIL** 是刻意的，理由与 v3.11 给 8092 定的一样：
共享机器上"18080 被占"和"gzip 协商坏了"是两件事，混在一起会训练出
"看到红就重跑"的习惯。用退出码区分比 grep 输出文本稳。

### 2. `tests/run_win_tests.py` 补三项 + 一个函数

| 新增 | 位置 | 断言数 |
|---|---|---|
| `test_gzip_http_e2e()` | `[11]` HTTP 端到端段 | +1 |
| `debugger_test.py` | `test_debug_chain()` 的循环里 | +1 |
| `doc_test.py` | 同上 | +1 |
| `bootstrap_test.py --strict` | 追加在 `test_qlmc()` 里 | +1 |

`debugger_test` 与 `doc_test` 直接进 `test_debug_chain()` 那个已有的
`(名称, 脚本)` 循环 —— 它们本来就是"脚本内部逐条断言、只看退出码"的形态，
一行一个，不用新函数。`bootstrap_test` 跟在 `qlmc_test` 后面：两者都是自举轨，
放一起看输出更直观。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=330 FAIL=0 SKIP=0**（v3.12 是 327；+gzip E2E +debugger +doc = 330，bootstrap 记在 qlmc 那一项内） |
| `python tests/gzip_http_test.py` | `gzip_http ok（5 项断言）`，退出码 0 |
| 端口被占时跑 `gzip_http_test.py` | 退出码 **2**，打印"已被占用，跳过" |
| `python tests/debugger_test.py` | `PASS：断点/变量/字段/单步/调用栈/行为不变 全绿` |
| `python tests/doc_test.py` | `PASS=31 FAIL=0` |
| `python tests/bootstrap_test.py --strict` | `PASS：stage-2 可用且与 stage-1 逐字节等价` |
| `python tools/dev/check_docs.py` | PASS（201 个 Markdown） |

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `tests/gzip_http_test.py` | 重写为自包含（编译/起停/就绪/端口探测/自增计数）；端口占用退出码 2 |
| `tests/run_win_tests.py` | 新增 `test_gzip_http_e2e()`；`test_debug_chain()` 加 `debugger_test`/`doc_test`；`test_qlmc()` 追加 `bootstrap_test --strict`；`[11]` 段调用新函数 |
| `docs/06-status.md` | §1 主回归口径 → 330；§3 相关行的"命令"列标注已在主回归 |
| `docs/07-gaps.md` | §3「端到端套件没全进主回归」→ 全绿 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.13.0 |

## 已知边界 / 遗留

- **`dns_test.py` / `x509_*.py` / `qpm_test.py` / `ecdsa_p256_test.py` /
  `gzip_inflate_test.py` / `bench_gate_test.py` 仍只在 CI 跑**。这些是纯 Python
  对拍（不依赖 Windows PE 执行），CI 覆盖是够的；主回归再跑一遍等于把本机
  回归时间翻倍。**判据是"要不要在提交前拦住"，不是"能不能跑"**。
- **`lexdiff` / `parsediff` / `bodydiff` / `irdiff` / `emitdiff` 同理**：它们是
  对拍工具（跑全仓源文件，几十秒到几分钟），放 CI 合适；`bodydiff` 本来就是
  诊断项不是门禁（`06-status.md` §1 写明"分叉随新增源文件增长"）。
- **`bodymatrix` / `bodydig` / `frame_scan` 等是手工诊断脚本**，不是回归，
  不该接 —— 这一条写在这里是为了避免下一个人再把它们当"漏接"。
- **主回归耗时继续增长**：v3.11 ~7m55s → v3.12/v3.13 因新增 HTTP 大响应夹具与
  自举五级链，热缓存下约 9–12 分钟。再往里塞东西之前应该先想清楚"这一项
  该不该由 CI 的 linux job 分担"。
- **`gzip_http_test.py` 的 18080 是硬编码**：与 `examples/http_gzip.qma` 里的
  `http_serve(18080, ...)` 必须一致。改端口要同时改两处，没有共享常量。
