# v3.60 — 修 CI 红：交接文档搬进 `docs/` + 数字单一来源

- 日期：2026-11-01
- 任务：用户要求"每一次更改都提交一次 github，所有基准都在 github 上测试"。
  上手第一件事是确认 CI 状态 —— 发现 **v3.58 / v3.59 连续两次推送 CI 全红**，
  且红在第 4 步"门禁"，后面所有测试步骤全部 skipped。本版先修这个。
- 影响面：文档（`HANDOFF.md` → `docs/08-handoff.md`）、`docs/README.md`、
  `docs/06-status.md`、`docs/versions/v3.59/CHANGELOG.md`
- 代码改动：**零**（纯文档门禁修复）

## 问题

GitHub Actions 上 `ci` 工作流在 `4e901f9`（v3.59）与 `db2a893`（v3.58）
两次都是 `failure`，`linux` 与 `windows` 两个 job 都倒在**第 4 步**：

```
4 门禁（改名残留 / 原创性 / 文档漂移） failure
5 文档生成门禁            skipped
6 包管理 qpm              skipped
7 自举对拍                skipped
8 C 后端回归              skipped
9 自研后端回归            skipped
10 运行时回归             skipped
```

也就是说 **v3.58 / v3.59 的所有基准数字，CI 里一个都没跑过**。本地全绿，
远端全红，两边判据不一致。

## 根因：v3.59 新增的 `HANDOFF.md` 违反了两条仓库自己的规矩

```
$ python tools/dev/check_docs.py
FAIL HANDOFF.md:190  命中：PASS=370
FAIL HANDOFF.md:20   命中：自举 30/30
FAIL：2 处文档问题
```

1. **位置**：`00-convention.md` §1 明写"**禁止**在 `docs/` 之外新建 `.md`
   （`README.md` 导航桩除外）"。`HANDOFF.md` 建在了仓库根。
2. **数字**：`00-convention.md` §4 规定实测数字（`PASS=n`、自举 `n/9` 等）
   **只允许**出现在 `06-status.md` 与 `versions/*/CHANGELOG.md`。
   `HANDOFF.md` §6 整段抄了基线数字。

讽刺的是 v3.59 的 CHANGELOG 写着"6 个文档门禁全过" —— 本地跑的是
`check_names` / `check_origin` / `check_docs` 里的**前两个**加别的东西，
`check_docs` 本身没跑或没看结果。**这正是"门禁跑了但没人看退出码"
的同一类问题**（v3.14 那条"一条从不影响退出码的告警迟早等于消失"的变体）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `HANDOFF.md` → `docs/08-handoff.md` | `git mv` 进 `docs/`（编号 08 未被占用） |
| `docs/08-handoff.md` | 重写：**删掉全部实测数字**，改为"见 `06-status.md`"；补 §2 上手四步、§4.6「验证矩阵少一格那一格就烂掉」；§3 缺口表按性价比重排 |
| `docs/README.md` | 索引加两行（"按用途查找" + "文档清单"），`check_docs` 要求 `docs/` 下每份 `.md` 都在索引里 |
| `docs/06-status.md` | §3.109 里 `HANDOFF.md` 的说法更正为 `docs/08-handoff.md`，并记下搬迁原因 |
| `docs/versions/v3.59/CHANGELOG.md` | 影响面与「顺带」小节同步改名，注明 v3.60 搬迁 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/dev/check_docs.py` | **PASS**（无过期断言、索引完整、版本目录完整、数字单一来源、版本号同源） |
| `python tools/dev/check_names.py` | PASS |
| `python tools/dev/check_origin.py` | PASS |

改前 `check_docs.py` 是 `FAIL：2 处文档问题`，改后 PASS —— 这条命令
**就是 CI 第 4 步实际执行的那一条**，所以 linux/windows 两个 job 都会转绿，
后面 6 个测试步骤才有机会真的跑起来。

## 顺带清理：5 个文件的 CRLF 噪声

工作区里另有 5 个文件显示 modified，实际是 **zip 解包把 LF 转成了 CRLF**：

```
std/httpc.qma  std/httpc_net.qma  std/net.qma  std/net/reactor.qma  tests/irdump_test.py
```

逐文件用 `tr -d '\r'` 后的 sha256 与 HEAD 比对，**5/5 完全相同**，
确认是纯行尾差异后 `git checkout --` 还原。这类噪声会掩盖真实改动，
提交前应当清掉。

## 未做（下一版）

CI 转绿之后，覆盖率的实际验证要靠 CI 或 wine —— 本机是 Linux，
`tools/dev/qlmc_coverage.py` 产的是 **PE32+**，在 Linux 上直接
`OSError: [Errno 8] Exec format error`。详见 `docs/08-handoff.md` §2。
