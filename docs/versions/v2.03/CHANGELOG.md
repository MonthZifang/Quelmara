# v2.03 — 日志：绝对时间戳 + stderr 通道 + 按大小轮转（标准库「日志」❌ → ✅）

- 日期：2026-10-24
- 任务：用户要求按 `07-gaps.md` §2 的**一条**一次性补成绿色——「日志」那一行的缺口写的是
  "无 stderr 通道、无轮转、无绝对时间戳（级别过滤 v1.19 已补）"。本版把这三件一次补齐，
  同步文档并实测性能。
- 影响面：标准库（`std/log` 重写、新增 `std/logfile`、`std/fs` 加一个共享打开）、
  测试、基准、文档

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/log.qma` | **重写**：① 行格式改成 `[级别] 2026-10-24T14:33:47.123+08:00 消息`（RFC 3339，毫秒 + 时区偏移，固定 29 字节）；② **时间戳缓存**——同一毫秒内复用上次结果（一次 `wall_ms()` + 比较 + 29 字节 `mem_copy`），毫秒精度下语义等价，稳态从 552 → **101 ns/行**；③ `log_set_sink(0/1)` 切 stdout/stderr；④ `log_set_tz_offset(min)`（默认 UTC，480 = 东八区）；⑤ `log_set_time_mode(1)` 保留老的相对格式；⑥ `log_enabled(lv)` 让调用方在拼昂贵载荷前先问一句；⑦ `log_format` / `log_format_kv` 与通道解耦（供 `std/logfile` 复用）；⑧ 每行输出持 `std/sync` 自旋锁，多线程写同一通道**行不交错**；⑨ 新增 `log_kv_lv`（指定级别的结构化行） |
| `std/logfile.qma`（新增） | 文件通道：`logf_open(path, max_bytes, keep)` / `logf_info`·`logf_warn`·`logf_error`·`logf_kv` / `logf_flush` / `logf_close` / `logf_size` / `logf_rotations` / `logf_tee`。追加写（重开续写）+ **64 KB 攒批**（每批一次 `WriteFile`）+ **按大小轮转**（`.1`…`.keep`，最旧一份由 `MoveFileEx(REPLACE_EXISTING)` 覆盖，**不调 `DeleteFile`**）。轮转判定在**写入前**做，单文件不超阈值 |
| `std/fs.qma` | 新增 `fs_open_shared(path, mode)`：`FILE_SHARE_READ\|FILE_SHARE_WRITE` 打开（内部抽 `_open_share`）。日志文件要能边写边 `tail`，独占打开的句柄会让 `read_text` 直接失败——这个坑在写测试时才暴露 |
| `tests/t131_log.qma`（新增） | 自校验 10 段：时间戳形态（29 字节 / 分隔符 / 三位毫秒 / 偏移符号）、时区正负偏移（+08:00 / -05:00，小时差 8）、相对模式、级别过滤、通道切换、文件通道（追加 / 重开 / 7 万字节超长行 / 结构化字段）、轮转（保留份数 / 单文件不超阈值 / 旧份被覆盖）、失败路径（打不开的路径返回 -1 且写日志不崩） |
| `tests/log_streams.qma`（新增） | 通道分流夹具：`log_info` 走 stdout、`log_set_sink(1)` 后走 stderr，由 `run_win_tests.py` 分开断言两路不串（程序自己看不到自己的两个流） |
| `bench/log_bench.qma`（新增） | 九段口径：过滤 / 格式化（缓存命中）/ 格式化（强制重建）/ 相对格式 / 文件通道 / 结构化字段 / 同机文件操作基线 / 轮转 / 控制台 |
| `tests/run_win_tests.py` | 新增 `[3i4] 日志` 分组（t131 自校验 + `test_log_streams()` 四条分流断言） |
| `tools/dev/gen_stdlib_doc.py` | 模块表登记 `std/logfile`，并把 `std/log` 的描述改成"日志核心"（职责已拆开） |
| `docs/03-stdlib.md` | 重生成（**61 个模块 / 430 个公开函数 / 549 内部**）；`std/log` 段按新 API 重写，新增 `std/logfile` 段 |
| `docs/07-gaps.md` | §2 **日志 ❌ → ✅ v2.03**（含边界：文件通道仅 Windows PE、崩溃窗口 64 KB、无 syslog/压缩归档/热加载） |
| `docs/06-status.md` | 新增 **§3.18 日志**（八项实测 + 两条"为什么"）；§1 主回归 275 → **280**、文档门禁 60/409/406 → **61/433/430** |
| `docs/05-toolchain.md` | §5.1 正向夹具 142 → **144** |
| `tools/stage0/qlm_cli.py` | `VERSION` → `2.03.0`（与最新版本目录同源） |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=280 FAIL=0 SKIP=1**（v2.01 的 275 + 本版 5 条：t131 自校验 + 4 条分流断言；SKIP 仍是 WSL 交叉验证被沙箱拦） |
| `python tools/stage0/qlm_cli.py run tests/t131_log.qma --target win` | 退出码 0，打印 `log ok` |
| `python tools/stage0/qlm_cli.py run bench/log_bench.qma --target win` | 见 `06-status.md` §3.18（5 次取中位） |
| `python tools/dev/gen_stdlib_doc.py --check --require-doc` | **PASS：61 个模块 / 430 个公开函数** |
| `python tools/stage0/qlm_cli.py doc std --missing` | **PASS：61 个模块 / 433 个公开声明**全部有 `///` |
| `python tools/dev/check_docs.py` / `check_names.py` / `check_origin.py` | 全 PASS |

## 性能（同机同日，5 次取中位；详见 `06-status.md` §3.18）

| 项 | 结果 |
|---|---|
| 级别过滤（被丢掉的行） | **2 ns/行** |
| 格式化（同毫秒缓存命中） | **101 ns/行** |
| 格式化（每行强制重建） | 375 ns/行 |
| 格式化（老的相对时间戳） | 205 ns/行——**绝对时间戳比它快约 2 倍** |
| 文件通道（64 KB 攒批） | **434 ns/行，173 MB/s** |
| 控制台通道 | 19.3 µs/行（终端速度，不是库成本） |
| 轮转一次 | 15.7 ms（本机 `rename` 2.3–2.9 ms/次、`open/close` 2.8–3.9 ms——环境数字） |

## 已知边界 / 遗留

- **文件通道仅 Windows PE**：走 `std/fs`（`@ffi` → kernel32）。拆成两个模块正是为了不让
  `import std.log` 被绑死在 Windows 上——日志核心是纯内建实现，ELF / AArch64 照常能编。
- **崩溃窗口**：攒批最多 64 KB 还在用户态缓冲里，进程被强杀会丢；`logf_flush` 之后数据
  已进内核（掉电仍要 `fs_sync`，本模块不自动刷盘）。
- **级别不能热加载**：级别、时区、通道、时间戳模式都是进程级静态字，改了对所有线程生效；
  没有"按模块/按 logger 名字分别设级别"的分层 logger。
- **没有 syslog / 网络输出 / 压缩归档**：`std/logfile` 只做本地文件 + 轮转。
- **行不交错靠一把进程级自旋锁**：多线程写同一通道时每行约多付 20 ns；跨进程写同一个
  文件不设防（`fs_open_shared` 是"允许共享"，不是"协调写入"）。
- **轮转成本由环境决定**：本机 `DeleteFile` 约 100 ms（Defender 文件过滤），所以实现里
  刻意用 `MoveFileEx(REPLACE_EXISTING)` 覆盖最旧一份、不做 unlink——这一条把轮转从
  122 ms/次 降到 15.7 ms/次。
