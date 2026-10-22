# v1.37 — vec[map[K]V]：map 句柄作 vec 元素（语言层黄标翻绿）

- 日期：2026-10-22
- 任务：语言层 P1-3 后半（07-gaps §8 顺序）。`vec[T]` 🟡 → ✅：map 句柄元素
  放行；struct 内嵌套聚合仍 🟡（拆条保留，诚实记账）。
- 影响面：编译器（parser 标签 + 原生后端 + C 后端）、测试（t82）、文档

## 为什么是它

v1.36 翻掉泛型后，§1 剩下的黄标里 `vec[T]` 的缺口只剩 `vec[map]`
（vec[vec[T]] 在 v1.12 已解锁）。查了一遍机制发现它不是表示问题：map 句柄
和 vec 句柄一样是 1 字值，`vec[vec[T]]` 的"句柄 1 字标量拷贝语义"原样适用——
差的只是元素标签管道（解析期放行 + 取出时重挂 map 标记）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | `vec_elem_tag` 放行 map 元素 → `("mapinner", K, V)` 标签；新增 `_map_kv_label`；`_vec_tag_str` mapinner 分支；`_vec_ewords` mapinner = 1 槽 |
| `tools/stage0/qlm.py` | C 后端：vec get/pop 取回 mapinner 重挂 `map:K:V` 环境类型（链式 `.set/.get/.has` 认领）；**foreach 循环变量重挂**（mapinner 新增 + vecinner 补漏） |
| `tools/stage0/qlm_native.py` | `_vec_tag_of` map 分支；vec get/pop 取回重挂 map 标记（`_mark_map`）；**foreach 循环变量重挂**（mapinner 新增 + vecinner 补漏） |
| `tests/t82_vecmap.qma` | **新增**：8 组覆盖（构造/push、链式、落变量、foreach、set 替换/pop、形参、map[str]str、vec[vec] foreach） |
| `tests/run_win_tests.py` | 注册 t82（主回归 144 → 145） |
| `tools/stage0/qlm_cli.py` | VERSION 1.36.0 → **1.37.0** |
| `docs/02-language.md` | 嵌套容器表述更新；陷阱 #10 改写（存句柄不存所有权） |
| `docs/07-gaps.md` | §1 `vec[T]` 🟡→✅；拆出"struct 内嵌套聚合"🟡 新行；§6/§8 划掉 vec[map] |
| `docs/06-status.md` | 回归 144 → **145** |

## 实现要点

- **与 vecinner 完全同构**：map 句柄 1 字，走 vec 现有标量槽路径
  （`__vec_push/__vec_get/__vec_set`，无 _n 变体）；元素大小 `type_words`
  对 map 恒 1，vecnew 自动正确。真正要做的只有两件事：解析期放行、
  取出时把句柄重新 mark 成 map（否则 `.set/.get` 不认类型）。
- **驱动修复（v1.12 漏的标记）**：`for row in grid`（vec[vec[T]]）的循环
  变量此前不重挂 vecinner 标签——循环体内 `row.push(...)` 会报"不支持方法"。
  本次在原生与 C 后端同步补上（t82 第 8 组回归）。
- **C 后端同路径修**：C 的 foreach 默认把循环变量 Typed 成 `int64_t`，
  mapinner/vecinner 都需要重挂环境类型；get/pop 的 mapinner 返回
  `map:K:V` 让链式调用成立。本机无 gcc，C 源码生成已验证（31 处运行时
  调用、`.has` 分发正确），编译与执行归 CI 交叉验证。
- **语义纪律**：vec 只存 map 句柄，**不持有 map 的所有权**——vec.clear /
  扩容 / pop 都不释放 map 本身（语言无 Drop，与 vec[vec] 一致，已写进
  02-language 陷阱 #10 与 t82 头部注释）。
- arm64：`map[K]V` 本就仅 x86_64，vec[map] 在 mapnew 处 fail-fast
  （实测报错信息正确），不是新限制。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=145 FAIL=0 SKIP=1**（v1.36 为 144；SKIP 为 WSL，沙箱拦） |
| `python tools/stage0/qlm_cli.py run tests/t82_vecmap.qma --target win` | ok（8 组全过） |
| `python tools/stage0/qlm_cli.py build tests/t82_vecmap.qma --target c` | C 源码生成正确（gcc 本机无，归 CI） |
| `python tools/stage0/qlm_cli.py build tests/t82_vecmap.qma --target arm64` | fail-fast：`map[K]V 目前仅支持 x86_64 后端` |
| `python tools/dev/check_names.py` / `check_origin.py` / `check_docs.py` | 三禁 PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS：41 模块 / 461 公开函数 |
| `python tests/lexdiff.py` / `parsediff.py` | 130 / 114 全绿（t82 不含泛型/接口，不进 PARSE1_PENDING） |
| `python tests/bodydiff.py` | 一致 1170 / 分叉 853（+2 分叉 = t82 两个函数，stage-1 尚未支持 vec[map] 语法） |
| `python tests/irdiff.py` / `emitdiff.py` | 65-0-45（SKIP+1 = t82 的 map 形态 arm64 未接）/ 10-0 |
| 性能（改动前 = git worktree@HEAD 基线，改动后各跑一遍，min-of-N） | 见下——**无回退** |

性能对照（基线 → 改动后）：

| 项 | 基线 | 改动后 |
|---|---|---|
| sha256 1MiB / split+join / url / json | 42 / 9 / 76 / 2 ms | 41 / 9 / 76 / 2 ms |
| gbench tokenizer / mix_arith / map_str / branchy | 3.83 / 47.7 / 4.72 / 41.3 ms | 4.45 / 47.6 / 4.10 / 39.6 ms |
| gbench str_build / buf_scan / nested / hashmix | 0.75 / 1.72 / 0.40 / 49.9 ms | 0.73 / 1.79 / 0.34 / 49.8 ms |
| bench_str scan16k / loopsum50m / collatz | 231 µs / 76.6 / 101.8 ms | 224 µs / 77.7 / 102.7 ms |

全部在 VBS 噪声带（±50%）内；vec[map] 是新能力，无历史基线可比。

## 已知边界 / 遗留

- **vec 不持有 map 所有权**：无 Drop 的语言里这是既定纪律（vec[vec] 同）；
  clear/pop 不级联释放。要自动回收需等 RAII/defer（❌ 行里排着）。
- **struct 内嵌套聚合仍 🟡**：struct 字段里的 vec/map 按 1 槽占位（句柄语义），
  不是内联布局——已拆条保留在 07-gaps §1。
- **map 值仍限标量**：`map[str]Struct` 未做（下一个黄标候选）。
- **C 后端编译执行归 CI**：本机无 gcc，只验证了代码生成。
- arm64 上 vec[map] 随 map 一起 fail-fast（既定边界，非本次引入）。
