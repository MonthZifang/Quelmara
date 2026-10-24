# v2.00 — 里程碑：1.x 缺口线收口，VERSION → 2.00.0

- 日期：2026-10-24
- 任务：版本号推到 2.00 里程碑（用户原话"刷一下提交到200"，确认为 v2.00 里程碑提交）。
  v1.18–v1.102 把语言层 / 标准库 / 工具链三张缺口表逐项刷绿，本版零功能改动，
  只做里程碑标记：`VERSION` → 2.00.0，文档口径同步。
- 影响面：版本号、文档（无代码改动）

## 里程碑口径

1.x 线的终点状态（实测数字唯一出处：`06-status.md`）：

- **语言层（§1）**：红/黄标全部翻绿——泛型（多类型参数 / 调用点推导 / struct / enum /
  方法 / 类型约束）、接口（装箱回收 / 跨接口同名 / 跨文件 impl / AArch64 vtable）、
  所有权（rc 线性 + 视图生命周期 / 写别名 / 跨线程）、并发（MPMC 栈 / WaitGroup 退避 /
  A64 原子原语）、`@ffi`、闭包、`Drop`、宏与反射（enum 派生 / 通用 token 宏 / 运行时下标）、
  模块系统（跨模块同名 mangling + 模块版本）。
- **标准库（§2）**：60 个模块 / 406 个公开声明全部有 `///` 文档；持久化
  （`std/fs` + `std/kv`）✅ v1.102。
- **工具链（§3）**：源码级调试器、行/分支覆盖率、fuzz、性能回归门禁、语言服务器、
  包管理（registry / 发布 / 传递依赖）、增量 / 并行编译全绿。
- **回归**：PE 主回归 PASS=275 FAIL=0 SKIP=1；对拍四件套 + 五道门禁全 PASS。
- **仍未做（❌）**：macOS Mach-O + kqueue、wasm32/64、Android 三个平台移植（§4，暂停中）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_cli.py` | `VERSION` → `2.00.0` |
| `docs/06-status.md` | 口径日期 → 2026-10-24；§3.16 的"批量提交 v1.103"改为"列入 2.x 后续版本"（里程碑后下一版不再编号 v1.103） |
| `docs/07-gaps.md` | §8 推进顺序同步同一处版本引用 |
| `docs/versions/v2.00/CHANGELOG.md` | 本文件（新建） |

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/dev/check_docs.py` | PASS（版本号同源：`VERSION` 2.00 ↔ `docs/versions/v2.00/`） |
| `python tools/dev/check_names.py` / `check_origin.py` | PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 2.00.0` |
| `python tests/run_win_tests.py` | 零代码改动，数字不变（PASS=275 FAIL=0 SKIP=1，见 `06-status.md` §1） |

## 已知边界 / 遗留

- KV 批量提交（原计划的 v1.103）顺延为 2.x 线首个功能版——写路径被文件 I/O 支配
  （约 26 µs/条），批量提交是下一步（见 `06-status.md` §3.16）。
- 三大平台移植（macOS / wasm / Android）仍未做；TLS 根证书库 / P-384 / SHA-384、
  连接池与 HTTP/2 等标准库红标见 §2 当前清单。
- `.qla` 目标文件格式（函数级增量的前提）未做，增量编译仍是单元级。
