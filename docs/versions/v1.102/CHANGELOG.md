# v1.102 — 持久化：`std/fs` + `std/kv`（标准库「持久化」❌ → ✅）+ 空 return 退出码修复

- 日期：2026-10-24
- 任务：`07-gaps.md` §2 的「持久化 | 无 SQLite / KV / 序列化格式 | 任何要存数据的应用」
  一次补成绿的可用形态——能落盘、能重开、崩了能恢复；顺带修掉过程中撞到的编译器缺陷。
- 影响面：标准库（新增 `std/fs`、`std/kv`）、编译器（`return` 降级一处）、回归、文档

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/fs.qma` | **新增**。文件读写最小集：`fs_open/fs_read/fs_write/fs_seek/fs_size/fs_sync/fs_close/fs_rename` + `fs_read_all/fs_write_all`。走 `@ffi`（v1.87）直调 kernel32（`CreateFileA`/`ReadFile`/`WriteFile`/`SetFilePointerEx`/`GetFileSizeEx`/`FlushFileBuffers`/`CloseHandle`/`MoveFileExA`）。失败一律 -1，不抛不退出 |
| `std/kv.qma` | **新增**。追加日志 + 内存索引的键值存储：`kv_open/put/get/has/del/len/sync/compact/close/ok/file_size`。磁盘格式 `KV1 <klen> <vlen> <fnv64>\n<key><val>`（ASCII 头 + 裸正文，二进制安全）；重开重放，**撕裂尾/垃圾尾**都能恢复到最后一个完好字节；压缩走 `<path>.tmp` + 原子改名 |
| `tools/stage0/qlm_native.py` | 修 **void 函数的空 `return` 不清 RAX**：入口把 `main` 的 RAX 当 `ExitProcess` 参数，于是 `if c { return }` 会让进程带着上一次比较结果退出（实测 rc=1）。现在 `fn_ret == ("named","void")` 时发 `ret ("imm", 0)`，与函数体末尾的兜底返回对齐 |
| `tests/t127_kv.qma` | **新增**自校验用例（单进程内）：put/get/has/del/len、空值 vs 不存在、二进制键值、重开重放、两库并存、覆盖写 + 压缩、关闭后行为 |
| `tests/kv_fixture.qma` | **新增**进程级夹具（`seed/verify5/verify4/verify5b/verify6/add`），每个模式一个独立进程——恢复路径只有在进程边界上才测得到 |
| `tests/kv_test.py` | **新增** 10 条：跨进程重开、**撕裂尾**（砍半条记录）、**垃圾尾**（追加 200 字节）、**独立 Python 解析器对拍磁盘格式**（含 FNV-1a 64 标准向量）、吞吐报告 |
| `tests/t128_mainret.qma` | **新增**：`if` / `while` / 被调 void 函数三条早退路径，钉住"退出码必须是 0" |
| `tests/run_win_tests.py` | 新分组 `[3i3] 持久化`（`case_selfcheck` t127 + `case_output` t128）；`[8]` 组注册 `kv_test.py` |
| `bench/kv_bench.qma` | **新增**：put/get/覆盖写/sync/重开/压缩的吞吐与体积 |
| `tools/dev/gen_stdlib_doc.py` | `DESC` 登记 `std/fs`、`std/kv` |
| `docs/03-stdlib.md` | 重新生成（60 个模块 / 406 个公开函数） |
| `docs/07-gaps.md` | §2 持久化 ❌ → **✅ v1.102**（含边界）；新增 §7.12（已修缺陷：空 return 污染退出码） |
| `docs/06-status.md` | 新增 §3.16（KV 实测）；把并行轨误插到 §4 之后的 §3.15（链接期）移回性能章节 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=275 FAIL=0 SKIP=1**（本版新增 `kv` 自校验 / `mainret` 退出码 / `kv_test` 三组；其余增量来自并行轨同期落地的链接期用例。SKIP = WSL 交叉验证被安全策略拦） |
| `python tests/kv_test.py` | **KV: PASS=10 FAIL=0** |
| `python tools/stage0/qlm_cli.py run tests/t127_kv.qma --target win` | 退出码 0，打印 `kv ok` |
| `python tools/dev/incr_bench.py` | 见 `06-status.md` §3.16（`bench/kv_bench.qma`） |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS |
| `python tools/dev/check_docs.py` / `check_names.py` / `check_origin.py` | PASS |

## 已知边界 / 遗留

- **Windows PE only**：`std/fs` 走 `@ffi`，ELF 后端没有动态链接器，编译期 fail-fast。
  真正的跨平台解是**内建 `file_*`**（x86 `openat/read/write/lseek/fsync` + A64 同款，
  `SYSCALLS` 表里已经有 read/write/close/openat/lseek，缺 fsync/ftruncate），
  那要同时改两个发射层，单开一版。
- **值全量驻留内存**：`map[str]str` 保存全部键值，内存 ≈ 数据集大小。大表要 mmap 视图 +
  页缓存（`tools/stage0/qlm_store.py` 的 C99 运行时已有原型，但没接到自研后端）。
- **无并发写保护**：同一进程多线程共享一个 `Kv` 要调用方加锁；多进程同时写同一文件不支持。
- **写路径被文件 I/O 支配**：26 µs/条（≈ 38k 写/秒）。要提吞吐就做**批量提交**
  （攒 N 条一次 `WriteFile`，顺带摊薄 `kv_sync`），这是下一版的事。
- **压缩是阻塞的**：531 ms / 2 万条，期间整个库不可写（单线程语义，没有后台线程）。
- 版本号取 v1.102：并行轨正在推 v1.101（链接期），`VERSION` 归它持有，收尾时按同源规则对齐。
