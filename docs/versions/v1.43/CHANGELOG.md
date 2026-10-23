# v1.43 — pub 可见性：跨模块显式导出（模块系统黄标收窄）

- 日期：2026-10-23
- 任务：语言层 §1 模块系统 🟡 收窄——`pub` 可见性落地：非 pub 的顶层
  fn/struct/enum 跨模块引用在**编译期报错**。命名空间（限定语法）与版本
  仍缺，模块系统行保持 🟡。
- 影响面：parser（pub 上下文关键字）、load_program（按文件可见性检查）、
  std/ 全库（显式导出标记）、文档生成器、测试（t88 + 负例）

## 为什么是它

P1-2 的可见性半边。此前 import 扁平合并后**一切顶层声明全项目可见**——
库的内部辅助函数与公开 API 无法区分，误用内部函数编译器不吭声。可见性
是命名空间的前置：先把"哪些名字是 API"变成语言事实，限定语法（lib.fn()）
才有语义可挂。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | `pub` 上下文关键字（不在 KEYWORDS 表——只在顶层声明位识别，函数内 `pub` 变量名不受影响，t68 实证）；作用于顶层 fn/struct/enum |
| `tools/stage0/qlm.py` | load_program：按文件收集 defs/refs/bound，合并前做可见性检查——引用口径与 global_dce 同款（call path[-1]/gcall/name 叶子/enumlit-structlit-pat 头段）+ 类型位置（`("named", T)`，内建标量除外）；**遮蔽豁免**：let/参数/循环变量/match 绑定名跳过（局部绑定遮蔽顶层名，跨模块同名非 pub 本就不可见） |
| `tools/stage0/qlm.py` | 检查一次报出全部违规（不是逐个挤牙膏）；错误信息带定义文件名 |
| `std/**`（22 个文件） | 真实跨模块消费的声明加 `pub`（cli_*/sha256_hex/hmac_sha256_hex/net 的 send/serve/accept 等 ~110 处）；`_` 前缀内部函数一律保持非 pub |
| `tools/dev/gen_stdlib_doc.py` | `pub fn` 也算公开函数（显示归一化回 `fn` 前缀）；03-stdlib.md 从"非下划线约定 461"改为**显式导出 195**——文档口径与语言语义对齐 |
| `fixtures/pubvis/` | **新增** t88 正例（main + pubvis_lib：pub fn/struct/enum 跨模块 + 库内非 pub 自用） |
| `tests/bad/pub_hidden/` | **新增**负例：跨模块引用非 pub 声明必须编译失败（含"非 pub"字样） |
| `tests/run_win_tests.py` | 注册 t88 正例 + pub 负例（主回归 150 → 152） |
| `tools/stage0/qlm_cli.py` | VERSION 1.42.0 → **1.43.0** |
| `docs/02-language.md` / `docs/07-gaps.md` / `docs/06-status.md` | 模块语义、缺口行、状态数字同步 |

## 实现要点

- **上下文关键字**：`pub` 不进 KEYWORDS——只在 parse_program 顶层分发处按
  NAME 文本识别。既有代码里 `pub` 作局部变量（t68_x509 的 `let pub = ...`）
  零破坏；顶层标识符位置本就没有其它合法形态，无歧义。
- **检查在合并循环之前**：合并会把 main 的 structs/enums 字典（Parser 活对象）
  灌入全部导入文件的定义——首版检查放在合并后，main 的"文件视图"被污染，
  Point 被算成 main 的非 pub 声明（t88 首跑踩坑）。移到合并前即正确。
- **检查不碰后端**：可见性是纯 parse/merge 期行为，合并后的 AST 与 v1.42
  逐字节相同——后端零改动，生成代码零变化（bench 实测印证）。
- **std 全库显式导出**：以"回归 + examples + bench 全语料编译"为收敛面，
  迭代把真实跨模块消费的声明标 pub（collect-all 检查一次报全部违规，
  脚本按报错自动补标注，2 轮收敛）；孤儿 std 文件（http_demo 依赖的
  `rc` 变量名等不可编译死代码）不在收敛面，保持原样。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=152 FAIL=0 SKIP=1**（v1.42 为 150；+t88 正例 +pub 负例） |
| `python tests/irdiff.py` | **67-0-48**（与 v1.42 持平：t41/t42 补导出后 A64 语料恢复） |
| `python tests/lexdiff.py` / `parsediff.py` | 137 / 119 全绿 |
| `python tests/bodydiff.py` | 一致 1202 / 分叉 872（无新增 MISMATCH） |
| `python tests/emitdiff.py` | 10-0 |
| 三道门禁 + `gen_stdlib_doc.py --check` | 全 PASS（41 模块 / **195** 公开函数） |
| 性能（基线 = git worktree@HEAD(v1.42)） | 见下——**无回退** |

性能对照（基线 → 改动后；VBS 噪声带 ±50%）：

| 项 | 基线 | 改动后 |
|---|---|---|
| sha256 / split+join / url / json | 42 / 9 / 76 / 2 ms | 42 / 9 / 75 / 2 ms |
| gbench tokenizer / mix_arith / map_str / branchy | 3.84 / 48.1 / 4.30 / 42.1 ms | 3.82 / 49.2 / 4.82 / 42.0 ms |
| gbench str_build / buf_scan / nested / hashmix | 0.76 / 2.02 / 0.41 / 51.1 ms | 0.75 / 2.04 / 0.40 / 50.6 ms |
| bench_str scan16k / concat20k / loopsum50m / collatz | 224 µs / 87.9 / 77.3 / 103.2 ms | 225 µs / 83.8 / 77.0 / 105.1 ms |

全部在噪声带内。改动是纯 parse/merge 期行为，生成代码与 v1.42 逐字节相同
（结构性保证）。

## 已知边界 / 遗留

- **命名空间（限定语法）未做**：`lib.fn()` 目前解析为方法调用，不支持——
  跨模块消费仍是扁平合并直呼其名（与 std 消费方式一致）。这是模块系统行
  剩余的最大项，前置已就绪（pub 集合即命名空间的导出表）。
- **版本管理未做**：qpm 无 semver 区间（07-gaps §3 既有边界）。
- **可见性豁免的盲区**：文件内"先局部绑定、另一函数里引用同名顶层声明"
  的形态会漏报（遮蔽豁免的代价）——parse 期无作用域跟踪，要精确需把检查
  下沉到 lowering 的 env 解析，另行评估。
- **interface/impl 仍限同源文件**（既有边界）：pub 对 interface 语法上
  可标但不产生跨模块能力。
