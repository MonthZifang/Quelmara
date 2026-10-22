# v1.39 — struct 嵌套聚合字段全形态（语言层黄标翻绿）

- 日期：2026-10-22
- 任务：语言层 §1 struct 内嵌套聚合 🟡 → ✅：vec/map/chan/slice 字段从
  “存得进取不出”变成方法/下标/派发全可用；**顺手修掉 slice 字段的静默截断**。
- 影响面：编译器（原生后端字段访问/字面量/赋值 + C 后端 chan 字段派发）、
  测试（t84）、文档

## 为什么是它

v1.38 翻掉错误处理后，§1 剩的黄标里 struct 内嵌套聚合看起来只是“表示问题”
（句柄 1 槽占位而非内联布局）。实测发现真正的缺口是**类型标记不跟着值走**：
`r.cells.push(3)` 报“方法 push 未定义”——vec/map/chan 句柄存进 struct 字段
后，读出时没重挂标记，方法派发认不出来。与 v1.37 修 vec[map] 时同一类病，
但这次藏在字段访问里，而且** slice 字段更毒：2 字 {ptr,len} 被 1 字 store
静默截断**（ptr 存了、len 丢了，不报错，直到越界/行为怪异）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | `lower_field`：vec/map/chan 字段读出重挂标记（`_mark_vec`/`_mark_map`/`_mark_chan`）——方法链认领类型；**slice 字段 2 字读出 + `_mark_slice`** |
| `tools/stage0/qlm_native.py` | `lower_struct_lit`：slice 字段 2 字拷贝（原来走 else 的 1 字 store，静默丢 len） |
| `tools/stage0/qlm_native.py` | `lower_assign_field`：slice 字段 2 字赋值（复合赋值拒绝） |
| `tools/stage0/qlm.py` | C 后端 `_is_chan_expr`：chan 字段派发（`b.ch.send(...)`）——AST 里 `b.ch` 是 `("path",["b","ch"])` 不是 field，先归一化成字段链再查 structs 表 |
| `tests/t84_structnest.qma` | **新增**：8 组覆盖（vec/map/chan/slice/str 字段、字段写、嵌套 struct、拷贝共享句柄、复合链） |
| `tests/run_win_tests.py` | 注册 t84（主回归 146 → 147） |
| `tools/stage0/qlm_cli.py` | VERSION 1.38.0 → **1.39.0** |
| `docs/07-gaps.md` | §1 struct 内嵌套聚合 🟡→✅；§8 推进顺序同步 |
| `docs/02-language.md` | 陷阱 #7 补“struct 内 vec/map/chan 是句柄、slice 是 2 字视图，拷贝后容器底层共享” |
| `docs/06-status.md` | 回归 → **147**（并更正 v1.38 漏改的回归数：v1.38 提交时 06-status 停在 145，实际当时已 146——本次按现跑值修正） |

## 实现要点

- **vec/map/chan 字段 = 句柄 1 字**：与 v1.12 vec[vec] / v1.37 vec[map] 同一
  语义——struct 布局按 1 槽算（`field_words` 本就如此），缺的只是读出时
  `_mark_*` 重挂；写入侧（字面量 store 1 字 / 赋值 store 1 字）本来就对。
- **slice 字段 = 2 字视图**：`field_words` 布局早就按 2 槽算（SLICE_WORDS），
  但字面量/读出/赋值三处都按 1 字处理——布局与访问不一致才是静默错编的根。
  现在三处统一 2 字（`words_copy`），读出还重挂 slice 标记（否则 `x.s[0]`
  报“下标只能用于定长数组、切片或 str”）。
- **C 后端 chan 字段**：C 类型串里 chan 坍缩成 int64_t，无法从类型串区分；
  且 `b.ch` 在 AST 里是 path 节点。`_is_chan_expr` 先把 path 归一化成字段链
  （与 gen_expr 的 path 处理一致），再回 structs 表查字段静态类型。
  vec/map/slice 字段在 C 后端本就通过 `env_type`/`field_ctype` 正确类型化，
  无需改（实测 4 个探针 C 源码生成全过）。
- **语义落 doc**：struct 拷贝共享容器底层（句柄语义）写进 02-language 陷阱 #7
  与 t84 头注——这是设计不是疏漏。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=147 FAIL=0 SKIP=1**（v1.38 为 146；SKIP 为 WSL，沙箱拦） |
| `python tools/stage0/qlm_cli.py run tests/t84_structnest.qma --target win` | ok（8 组全过） |
| `python tools/stage0/qlm_cli.py build ... --target c`（4 个探针） | C 源码生成全过（gcc 本机无，归 CI） |
| `python tools/dev/check_names.py` / `check_origin.py` / `check_docs.py` | 三禁 PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS：41 模块 / 461 公开函数 |
| `python tests/lexdiff.py` / `parsediff.py` | 132 / 116 全绿 |
| `python tests/bodydiff.py` | 一致 1170 / 分叉 867 / SKIP 24-18（t84 函数体 stage-1 尚未支持 struct 嵌套字段形态，如实分叉） |
| `python tests/irdiff.py` / `emitdiff.py` | 66-0-46 / 10-0 |
| 性能（改动前 = git worktree@HEAD(v1.38) 基线，改动后各跑一遍） | 见下——**无回退** |

性能对照（基线 → 改动后）：

| 项 | 基线 | 改动后 |
|---|---|---|
| sha256 / split+join / url / json | 42 / 9 / 75 / 2 ms | 41 / 9 / 74 / 2 ms |
| gbench tokenizer / mix_arith / map_str / branchy | 4.02 / 49.6 / 4.38 / 41.4 ms | 3.89 / 47.8 / 4.10 / 39.5 ms |
| gbench str_build / buf_scan / nested / hashmix | 0.76 / 1.72 / 0.38 / 50.2 ms | 0.74 / 1.76 / 0.33 / 50.0 ms |
| bench_str scan16k / loopsum50m / collatz | 231 µs / 80.0 / 103.0 ms | 224 µs / 80.1 / 102.3 ms |

全部在 VBS 噪声带（±50%）内；concat20k 81.6→87.0ms 亦在带内（该指标历史上
77–126ms 波动）。改动只碰字段访问/字面量/赋值降级，非 struct 程序代码生成
零变化。

## 已知边界 / 遗留

- **句柄语义即设计**：struct 里的 vec/map/chan 不随 struct 拷贝深拷贝，
  clear/pop 不级联释放——无 Drop 的语言里的既定纪律（与 vec[vec] 同）。
- **slice 字段只支持 = 整体赋值**：复合赋值（+= 等）无意义，fail-fast。
- **C 后端 slice 字段**：布局靠 C 结构体（QlmSlice 2 字）天然正确，本机无
  gcc 未执行，归 CI 交叉验证。
- 剩余黄标见 07-gaps §1：map[str]Struct（map 值扩容，剩余项里最大）、
  函数值放宽、整数宽度、@simd、并发、编译期求值、模块系统、所有权、interface。
