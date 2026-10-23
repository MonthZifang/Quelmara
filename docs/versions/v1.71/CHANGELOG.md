# v1.71 — 会话存储 `std/session`

- 日期：2026-10-23
- 任务：§2「静态文件 / MIME / cookie / session / multipart」里的 **session** 一块。
- 影响面：标准库（`std/session.qma`，全部用 Quelmara 写）、测试、文档

## 新增 API

| 函数 | 说明 |
|---|---|
| `session_new() -> SessionStore` | 建空存储（两个 map 句柄） |
| `session_create(st, ttl, now) -> str` | 新建会话，返回 sid；`ttl<=0` 表示永不过期 |
| `session_alive(st, sid, now) -> bool` | 存活判定（惰性过期，正好到期视为过期） |
| `session_get(st, sid, key, now) -> str` | 读；会话死/键不存在返回空串 |
| `session_set(st, sid, key, value, now) -> bool` | 写；会话死返回 false |
| `session_touch(st, sid, ttl, now) -> bool` | 滑动续期 |
| `session_destroy(st, sid)` | 打墓碑（`exp[sid] = -1`） |
| `session_count(st) -> int` | 已创建条目数（含墓碑） |

## 实现要点

- **结构体是值类型，map 是句柄**：`SessionStore` 按值传参，`st.data.set(...)` 的改动
  对调用方可见（句柄），但 `st.n = st.n + 1` 这种**字段赋值不会**——第一版就把
  计数器放在 struct 里，结果两个会话都拿到 `s1`（后者覆盖前者的过期时间）。
  改用 `len(st.exp) + 1` 生成 sid：`exp` 从不删条目，天然单调。
- **没有嵌套 map，也没有 map 遍历**：键用 `sid + 0x1f + key` 拼成扁平表；
  销毁只能打墓碑，`data` 里的键会留下（模块头注释写明了）。
- **惰性过期**：读取时比对 `exp[sid]`，没有后台清理线程——`map` 不支持遍历，
  全表扫描做不到。
- **sid 可预测**（`s1`、`s2`…）：只适合测试/单机；线上需要随机源（见遗留）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/session.qma` | **新增**：`SessionStore` + 8 个公开函数 + 1 个内部键拼接 |
| `tests/t110_session.qma` | **新增**：sid 单调/不复用、ttl 边界（正好到期）、ttl=0、双会话隔离、过期后读写、续期、销毁、计数 |
| `tests/run_win_tests.py` | 注册 `t110_session` |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 |
| `docs/03-stdlib.md` | 重新生成：52 个模块 / 355 个公开函数 |
| `docs/07-gaps.md` | §2 该行补 session ✅ |
| `docs/06-status.md` | 回归数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.71.0 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/t110_session.qma` | 25 条断言全过 |
| `python tests/run_win_tests.py` | PASS=202 FAIL=0 SKIP=1 |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（52 模块 / 356 公开函数） |
| 四道门禁 | 全 PASS |
| lexdiff / parsediff / irdiff / emitdiff | **本次未复跑**：另一条轨正在改编译器（21:27 加 `dbg_info`、21:34 加 `_scan_derives`），中途 `AttributeError: 'Parser' object has no attribute '_scan_derives'`。本版只新增 `std/session.qma` 与 `tests/t110_session.qma`，不动编译器 |

## 已知边界 / 遗留

- **sid 可预测**：`s1`/`s2` 递增，攻击者可枚举。需要随机源（`rand` 内建或
  `now_ns` + 哈希），属于语言层缺口，登记在 §2。
- 进程内内存，重启即失；没有 LRU 淘汰、没有后台 GC（`map` 不可遍历）。
- 无并发保护：多线程共享同一个 store 需要调用方加锁。
- multipart 仍缺（§2 同一行的最后一项）。
