# v1.44 — 命名空间限定语法：lib.fn() / lib.Enum.Variant（模块系统继续收窄）

- 日期：2026-10-23
- 任务：语言层 §1 模块系统 🟡 继续收窄——限定语法 `lib.fn(...)`、
  `lib.Enum.Variant(...)`（带/无载荷）、模式 `lib.Enum.Variant =>` 落地：
  头部段匹配本文件 import 时改写为扁平名，并做**指向 + pub 双重校验**。
  命名空间与版本的剩余差异（跨模块同名声明）如实登记，行保持 🟡。
- 影响面：parser（限定改写）、load_program（qref 指向校验 + enum 定义表
  修复）、双后端（enumlit_pos 位置实参形态）、测试（t89 + 负例）

## 为什么是它

P1-2 的另一半。v1.43 的 pub 让"哪些名字是 API"成为语言事实，但跨模块
消费仍是扁平直呼其名——调用点看不出依赖来自哪个模块。限定语法让
`ns_lib.greet(...)` 自带来源信息，且限定头必须匹配本文件 import
（拼错模块名 / 没 import 就用 = 编译期报错，不是静默按方法调用失败）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | Parser：`import_paths` / `qrefs` 收集；`_match_import`（精确 + 前缀匹配，`ws.ws_core.greet` 与 `ws.greet` 都命中）；postfix 方法分支改写（`lib.fn(...)` → 扁平 call；`lib.Color.Red(v)` → `enumlit_pos`）；限定路径剥离（无载荷 `lib.Color.Red` / 限定模式剥模块段） |
| `tools/stage0/qlm.py` | load_program：qref **指向校验**（`lib.name` 的 name 必须定义在 import 解析到的文件——扁平唯一性下指错模块即报错）；**修复 v1.43 缺陷：enum 从未进 defs_of，枚举的跨模块 pub 检查被静默跳过** |
| `tools/stage0/qlm.py` | C 后端：Infer/gen_enumlit 支持 `enumlit_pos`（位置实参按 merged 变体表下标映射字段名）；walk_expr 加分支 |
| `tools/stage0/qlm_native.py` | lower_enum_lit 支持 `enumlit_pos`（同上）；eval 分派加 enumlit_pos |
| `fixtures/qualified/` | **新增** t89 正例：限定调用 / 带载荷与无载荷限定枚举构造 / 限定模式 / 自有枚举不受影响 |
| `tests/bad/pub_hidden_q/` | **新增**负例：限定调用指向非 pub 声明（"非 pub" 或 "无法解析" 任一消息均算拦下） |
| `tests/run_win_tests.py` | 注册 t89 + pub_hidden_q（主回归 152 → 155） |
| `tools/stage0/qlm_cli.py` | VERSION 1.43.0 → **1.44.0** |
| `docs/02-language.md` / `docs/07-gaps.md` / `docs/06-status.md` | 限定语法语义、缺口行、状态数字同步 |

## 实现要点

- **parse 期改写为扁平名**：`lib.fn(...)` 生成与 `fn(...)` 完全相同的 AST
  （`("call", [fn], args)`）——限定是纯语法 + 校验，不引入新运行时形态。
  头部匹配 import 的引用才改写；不匹配则维持方法调用语义（对局部变量
  无影响）。模块名与局部变量同名时模块赢（解析期判定，如实登记）。
- **`enumlit_pos` 位置实参形态**：限定的枚举构造在 parse 期拿不到跨模块
  变体字段表（命名实参无法校验——fail-fast 拒绝），载荷按位置传递，
  lower/gen 按 merged 变体表校验个数并按下标映射字段名。专属 AST 形态
  而非复用 ("enumlit", fields dict)——两后端 + Infer + walk_expr 四处同步。
- **指向校验补全 v1.43 的盲区**：defs_of 漏收 enum（枚举的跨模块 pub
  检查被 `r not in defs_of` 静默跳过）——本轮修复并经 t88/t89 的枚举
  引用实证。
- **限定 struct 字面量不做**：`lib.Point { }` 需要 parse 期跨模块 struct
  表，留待与"跨模块同名声明"（真正的命名空间 mangling）同轮；现状用
  pub 工厂函数（`lib.make_point(...)`）。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=155 FAIL=0 SKIP=1**（v1.43 为 152；+t89 正例 +pub_hidden_q 负例） |
| `python tests/irdiff.py` | **67-0-48**（限定语法双架构 IR 一致，t89 的 A64 语料直通） |
| `python tests/lexdiff.py` / `parsediff.py` | 139 / 119 全绿 |
| `python tests/bodydiff.py` | 一致 1202 / 分叉 872（无新增 MISMATCH） |
| `python tests/emitdiff.py` | 10-0 |
| 三道门禁 + `gen_stdlib_doc.py --check` | 全 PASS |
| 性能（基线 = git worktree@HEAD(v1.43)） | **生成代码逐字节相同**（cmp 实证 gbench .qex 两树一致）+ bench 双向对照无回退 |

性能对照（两侧各跑两轮取更优；本轮系统噪声大，以逐字节比较为硬证据）：

| 项 | v1.43 最优 | v1.44 最优 |
|---|---|---|
| tokenizer / mix_arith / map_str / branchy | 4.63 / 49.3 / 5.45 / 50.3 ms | 3.92 / 48.0 / 4.65 / 39.7 ms |
| str_build / buf_scan / hashmix | 0.83 / 2.42 / 51.3 ms | 0.81 / 2.16 / 50.2 ms |
| scan16k / concat20k / loopsum50m / collatz | 224 µs / 117 / 84.0 / 112 ms | 224 µs / 104 / 79.8 / 108.5 ms |

全部 ≤ 基线最优。nested 项两侧抖动大（0.34–1.54 ms），经 .qex 逐字节
比较证实为环境噪声而非代码差异。

## 已知边界 / 遗留

- **跨模块同名声明仍不允许**：扁平唯一性未放开——`http.get` 与 `ws.get`
  不能共存，前缀约定还得用。放开需要 per-module mangling + 无作用域
  跟踪下安全的引用改写（局部遮蔽盲区会放大），与泛型 struct 同量级，
  单独一轮。
- **限定 struct 字面量 / 类型位置限定（`let p: lib.Point`）不做**：
  parse 期无跨模块类型表；用 pub 工厂函数替代。
- **限定枚举构造只收位置实参**：命名实参需要跨模块变体字段表，fail-fast
  拒绝并提示。
- **模块名遮蔽**：头部匹配 import 的引用一律按模块解析——局部变量与
  import 同名时该变量的方法调用不可用（解析期判定，如实登记）。
