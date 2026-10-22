# v1.18 — 文档全量重构：源码扫描重建 + 统一目录 + 版本档案

- 日期：2026-10-22
- 任务：旧文档长期漂移（同一指标四份文档四个值、版本号停在 v1.10）；要求扫描源码后
  删除全部旧文档，统一在 `docs/` 下重建，并制定文档存放规范；此后每次任务提交都要新建
  带版本号的文件夹并附更新日志。
- 影响面：文档（不影响编译器行为）

## 改动

### 删除（19 份）

| 文件 | 原问题 |
|---|---|
| `README.md`（根） | 重写为导航桩，不再承载内容 |
| `SPEC.md` | `vec[vec[T]]` 仍写"暂不支持"（v1.12 已支持） |
| `TUTORIAL.md` | 同上，教人"嵌套请扁平化" |
| `GUIDE.md` | interface 仍写"动态分发未实现"（v1.9 已落地）；回归数 113 |
| `BACKEND.md` | 停留在 v1.3 时代的优化记录 |
| `PLATFORM.md` | IOCP "尚未接入"（v1.4 已落地） |
| `SHOWCASE.md` | 示例与能力描述过期 |
| `HANDOVER.md` | 唯一准确的旧文档，但结构与其他文档重叠 |
| `CHANGELOG.md`（根） | 迁入 `docs/versions/archive/pre-v1.18-changelog.md` |
| `docs/EXTENSIONS.md` | 扩展名规则并入 `05-toolchain.md` |
| `docs/GAPS.md` | 回归数 113、自举 8.6%、bodydiff 94；§4 UDP ❌ 与 §6.5.16 UDP ✅ 自相矛盾；全局 DCE 写"待实现"（已落地）；6.5.15 标题重复两遍 |
| `docs/LANG.md` | `@simd` 缺 f64 形状；缺 str/mem 原语 |
| `docs/ORIGINALITY.md` | 并入 `05-toolchain.md` 门禁一节 |
| `docs/P0_LIBS.md` | 并入 `03-stdlib.md` |
| `docs/PERF.md` | 并入 `06-status.md` §3 |
| `docs/SELFHOST.md` / `SELFHOST_PLAN.md` | 并入 `06-status.md` §4 与 `04-compiler.md` |
| `docs/SRC.md` | 并入 `05-toolchain.md` §3 |
| `docs/STATUS.md` | 整篇停在 v1.10，把已完成的泛型列为"下一步" |
| `docs/TLS.md` | 并入 `07-gaps.md` §2 |
| `tools/stage0/README.md` | 并入 `04-compiler.md` §2 |

### 新增（9 份文档 + 1 份存档）

| 文件 | 内容 |
|---|---|
| `docs/README.md` | 文档索引与三条硬规则 |
| `docs/00-convention.md` | 存放规范：目录、命名、职责边界、数字单一来源、版本文件夹规则、门禁 |
| `docs/01-overview.md` | 定位、快速开始、仓库结构、关键文件规模 |
| `docs/02-language.md` | 词法（31 关键字）/类型/语句/表达式/**67 个内建函数全表**/特性语义/10 条陷阱 |
| `docs/03-stdlib.md` | **24 个模块 279 个公开函数**（源码自动提取）+ 边界 + 命名陷阱 |
| `docs/04-compiler.md` | 流水线、12 个模块分工、**46 个 IR 操作码**、15 个优化 pass、IR 五处登记、三后端、运行时、调试开关 |
| `docs/05-toolchain.md` | CLI 7 条命令、配置全字段、src 三类资源、qpm、72+12 夹具、15 个脚本、三道门禁、CI |
| `docs/06-status.md` | **全部实测数字的唯一出处**：回归/对拍/产物/性能/自举/平台/风险 |
| `docs/07-gaps.md` | 语言/标准库/工具链/平台缺口 + 性能专项 + P0/P1/P2 路线 |
| `docs/versions/archive/pre-v1.18-changelog.md` | v0.1–v1.17 旧日志全文（只读） |

### 修改

| 文件 | 改了什么 |
|---|---|
| `README.md`（根） | 改为导航桩，只指向 `docs/README.md` |
| `tools/dev/check_docs.py` | 重写：路径改到新结构；新增索引完整性、版本目录完整性、数字单一来源三项检查；过期断言黑名单扩到 9 条 |
| `tools/dev/gen_stdlib_doc.py` | 新增：从 `std/` 源码重新生成 `docs/03-stdlib.md` 的 API 段（`--check` 可用于 CI） |
| `tests/t62_pool_log.qma` | 日志样例字符串 `"rosoto"` → `"quelmara"`；这是 `check_names` 唯一失败的残留，非本次文档改动引入 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=124 FAIL=0 SKIP=1**（文档改动零破坏） |
| `python tests/lexdiff.py` | PASS=109 FAIL=0 |
| `python tests/parsediff.py` | PASS=94 FAIL=0（跳过 3 个 interface/泛型文件） |
| `python tests/bodydiff.py` | 一致 740 / 分叉 625 / SKIP 不同步 18 |
| `python tools/dev/selfhost_status.py` | 2/9，1846 / 21114 行 = 8.0% |
| `python tools/dev/check_docs.py` | PASS |
| `python tools/dev/check_names.py` | PASS |
| `python tools/dev/check_origin.py` | PASS |

基准（本次一并记录，详见 `docs/06-status.md` §3）：

| 负载 | 结果 |
|---|---|
| SHA-256 1 MiB | 69 ms |
| gzip 1 MiB | 25 ms |
| CRC-32 1 MiB | 3 ms |
| split+join 1 MiB | 8 ms |
| URL parse ×100k | 70 ms |
| JSON parse 92 891 B | 2 ms |
| `@simd` int 归约 | 4× 标量 |
| atomic_add / 自旋锁 / 无锁栈 | 17 / 22 / 82 cycles/iter |
| loop_sum 2×10⁸ | 769 ms（含 426 ms 启动） |

## 已知边界 / 遗留

- 文档内容全部来自本次源码扫描与实跑，但 `irdiff` / `emitdiff` 在本机会挂住（>120 s），
  这两项的口径只能以 CI 为准，未写入实测表。
- 旧 `CHANGELOG` 只做了归档，**没有**按版本拆成 `versions/v0.x` 目录——历史粒度不足，
  拆分的收益低于成本。
- `qlm_cli.py version` 仍打印 `1.0.0`，与 v1.17/v1.18 的版本线不一致；本次只登记
  （`07-gaps.md` §3），未改代码。
- `docs/03-stdlib.md` 的 API 段由脚本生成；生成脚本 `tools/dev/gen_stdlib_doc.py`
  在本次提交中补齐，之后改库必须重新生成。
