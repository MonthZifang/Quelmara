# v3.11 — 把 TCP 与 HTTP 端到端接进主回归：红了 4 个版本的教训

- 日期：2026-10-30
- 任务：用户要求"继续"；承接 v3.09 登记的缺口 —— "端到端套件没全进主回归"
- 影响面：工具链（`tests/run_win_tests.py` 两段新覆盖 + `check_docs.py` 扫描范围）、
  测试（`tests/http_router_test.py` 的计数方式）、文档

## 问题：三处网络缺陷都是"在 Windows 挖出来、却只有 Linux 在跑"

v3.06–v3.10 修的四件事（批量收发、O(n²) 堆爆、接收超时、发送超时）全部是**在
Windows 上用探针实测**发现的，而它们进了 `tests/run_native_tests.sh` —— 那是
**Linux CI job** 的脚本。Windows 主回归 `tests/run_win_tests.py` 一条都没跑：

| 用例 | 覆盖 | 主回归里有吗（v3.10 为止） |
|---|---|---|
| `t163_recvbatch` | 批量接收 4 场景 | ❌（只有 Linux job） |
| `t164_sendall` | `send_all` + 4 MB 零拷贝 | ❌ |
| `t165_recvtimeout` | 接收超时 / 半开连接 | ❌ |
| `t166_recvbulk` | 4 MB / 4 KB 分块（O(n²) 回归） | ❌ |
| `t167_sendtimeout` | 零窗口短写 / `send_to` | ❌ |
| `http_router_test.py` | HTTP 路由 / 中间件 / chunked / gzip（25 项） | ❌ |

代价已经付过一次：`http_router_test.py` 的 R10 用例（chunked 分片）数据自相矛盾
（声明 7 字节实发 8），**从 v2.95 红到 v3.09**，四个版本无人发现 —— 因为它不在
主回归里，而手工跑的人（如果有）看到红也以为是环境问题。见 `06-status.md` §3.64。

"写在某个脚本里"不等于"被验证"。**没进默认入口的用例 = 不存在**。

## 改动

### 1. `[3k] TCP 批量收发与两端超时`

五个用例按顺序进主回归。用新助手 `case_selfcheck_to(name, src, seconds)` 给**短超时**
（120 s / 180 s）：这批用例自带内部超时，正常 3–7 s 跑完；真挂住时 600 s 的默认
上限会把 CI 拖死，而"挂住"恰恰是它们要检测的失败模式之一——用一个会让失败变成
"很慢的失败"的上限，等于把信号丢掉。

### 2. `[11] HTTP 端到端`

`http_router_test.py` 自己负责编译 `examples/http_router.qma`、起服务、等就绪
（6 s 内）、跑断言、退出码。主回归只做三件事：

| 情况 | 判定 |
|---|---|
| 端口 8092 已被别的进程占用（bind 探测失败） | **SKIP**（环境问题，不是回归） |
| 非 Windows | **SKIP**（服务端运行时仅 PE） |
| 脚本退出码 0 且打印 `http_router ok` | PASS（回显脚本自报的断言数） |

端口占用记 SKIP 而不是 FAIL 是刻意的：共享机器上"8092 被占"与"路由坏了"是两件事，
混在一起会训练出"看到红就重跑"的习惯——那等于没有门禁。

### 3. `http_router_test.py` 的断言数不再手写

原来结尾是 `total = 26` 的**手写常量**，而实际断言是 **25** 条。加一条用例不改正数
就打印一个假数字——和文档里"同一个指标四个值"是同一种病。现在 `ok()` 自增计数，
`http_router ok（25 项断言）` 是真数出来的。

### 4. `check_docs.py` 不再扫 `.workbuddy/`

`.workbuddy/memory/*.md` 是 agent 的工作区数据（会话记忆），不是项目文档。
`00-convention.md` 规定文档只放 `docs/`，而记忆文件里**必然**出现实测数字
（那正是它存在的意义）。v3.11 加这版日志时门禁第一次碰上了它，于是把
`.workbuddy/` 从扫描集里排除——**收窄范围的理由写在代码注释里**，不是为了让红变绿。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=308 FAIL=0 SKIP=1**（v3.10 是 302；+5 TCP +1 HTTP E2E） |
| 单独跑新增两段 | `[3k]` 5 项全 PASS；`[11]` `http_router ok（25 项断言）` |
| `python tools/dev/check_docs.py` | PASS（198 个 Markdown） |
| `python tests/http_router_test.py` | `http_router ok（25 项断言）`，退出码 0 |

主回归耗时从 ~10m50s 变成 ~7m55s —— 不是变快了，是 `build/` 缓存已热（`qlmc`
与各夹具的增量缓存命中）。这两个数字不可横比。

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `tests/run_win_tests.py` | `import socket`；`case_selfcheck_to`；`test_tcp_batch`（5 用例）；`test_http_e2e`（端口探测 + SKIP 口径）；`[3k]` 与 `[11]` 两段 |
| `tests/http_router_test.py` | 断言数改成实际计数（`checks`），删掉手写 `total = 26` |
| `tools/dev/check_docs.py` | 扫描集排除 `.workbuddy/`（附理由） |
| `docs/06-status.md` | §1 主回归口径 → 308 |
| `docs/07-gaps.md` | §3「端到端套件没全进主回归」→ ✅ v3.11 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.11.0 |

## 已知边界 / 遗留

- **`gzip_http_test.py` 仍未接入**：它要求**手工先起** `examples/http_gzip.qma`
  （端口 18080），不是自包含脚本。要接进来得先给它加"自己起停 + 端口探测"那套，
  与 `http_router_test.py` 同构。gzip 协商的端到端覆盖目前由 R6 保证。
- **`[3k]` 的五个用例占固定端口 18073–18097**，与 8092 不冲突；但如果宿主机上
  有别的程序占了这些端口，失败信息会是 `tcp_bind() failed`（fail-fast），
  而不是 SKIP。要更稳得给每个用例加端口探测，收益不大，先记着。
- **主回归不覆盖 Linux 专属路径**（`poll` 版发送超时、`tcp_connect` 的 raw syscall）。
  那部分仍只有 CI 的 linux job（`run_native_tests.sh`）能验。
- **`.workbuddy/` 里现在有会话记忆入库**（`memory/2026-10-30.md`）。它记录的是
  当轮实测数字与踩坑，属于"工作日志"而不是"文档"；如果仓库不想要它，加进
  `.gitignore` 即可，与本版的门禁改动无关。
