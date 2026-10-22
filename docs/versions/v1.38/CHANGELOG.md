# v1.38 — result/option 具名 struct 载荷（语言层黄标翻绿）

- 日期：2026-10-22
- 任务：语言层 P1-4 前半（07-gaps §8 顺序）。错误处理 🟡 → ✅：
  result[T,E] / option[T] 载荷放宽到具名 struct/enum。
- 影响面：编译器（parser 合成枚举 + 原生/C 后端 ? 降级）、测试（t83）、文档

## 为什么是它

v1.36/v1.37 连续翻掉泛型与 vec[map] 后，错误处理行的缺口是"result 载荷限标量"——
库层只能 fail-fast 或返回 -1/空串，errno + 上下文交给调用方不可能。查机制发现
卡点只有一个：合成枚举 `__res_<T>_<E>` / `__opt_<T>` 的标量检查。**用户 enum
的变体载荷本就支持 struct**（布局 1+最大载荷字、构造、match 解构、聚合返回 ABI
全部现成，实测 `enum E { A(p: P) }` 一遍过）——合成枚举与用户 enum 走同一条
降级路径，放行检查即得能力，零新机制。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | `ensure_option_enum` / `ensure_result_enum` 放行具名 struct/enum 载荷；result 合成名撞车保护（(A_B,C) vs (A,B_C) 相撞且语义不同 → fail-fast） |
| `tools/stage0/qlm.py` | C 后端 `?` 降级放行 Ok 载荷检查（联合体成员访问 `{tmp}.u.Ok.value` 对 struct 值天然成立） |
| `tools/stage0/qlm_native.py` | `?` 降级放行检查 + **多字载荷提取**：Ok 载荷是聚合时拷进新帧槽按值返回（struct 值 = 槽地址，与字段访问/vec.get 聚合元素同构；载荷在 tag 之后字偏移 1） |
| `tests/t83_resagg.qma` | **新增**：6 组覆盖（双 struct 载荷、? 正常/错误分支、? 链式穿两层、T/E 对调、option[struct]、? 提字段） |
| `tests/run_win_tests.py` | 注册 t83（主回归 145 → 146） |
| `tools/stage0/qlm_cli.py` | VERSION 1.37.0 → **1.38.0** |
| `docs/02-language.md` | §6.2 方法表 option/result 行补 struct 载荷；§6.3 `?` 节边界更新 |
| `docs/07-gaps.md` | §1 错误处理 🟡→✅（std 批量改造注明属标准库工作）；§6 P1-4 划掉前半；§8 同步 |
| `docs/06-status.md` | 回归 145 → **146** |

## 实现要点

- **零新机制**：合成枚举就是普通 enum，载荷多字性由 enum 布局（1+最大载荷字）
  天然承载；要改的只有三处标量检查 + 原生 `?` 的单字 load 换多字拷贝。
- **`?` 的多字提取**：Ok 标签命中后，把 spec+8 起的 N 字拷进新帧槽并 mark 成
  struct 返回——调用方 let / 传参 / 取字段全部按既有 struct 值语义走。
  Err 分支原本就是整体 enum 拷贝，多字无需改。
- **fail-fast 纪律**：`?` 所在函数必须返回同一 result 枚举（main 返回 void
  不能用 `?`）——既有检查原样保留；result 合成名撞车（类型名含下划线时
  (A_B,C) 与 (A,B_C) 同串）语义不一致直接报错，不静默用错枚举。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=146 FAIL=0 SKIP=1**（v1.37 为 145；SKIP 为 WSL，沙箱拦） |
| `python tools/stage0/qlm_cli.py run tests/t83_resagg.qma --target win` | ok（6 组全过） |
| `python tools/stage0/qlm_cli.py build tests/t83_resagg.qma --target c` | C 源码生成正确（15 处 `u.Ok` 联合体访问；gcc 本机无，归 CI） |
| `python tools/dev/check_names.py` / `check_origin.py` / `check_docs.py` | 三禁 PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS：41 模块 / 461 公开函数 |
| `python tests/lexdiff.py` / `parsediff.py` | 131 / 115 全绿 |
| `python tests/bodydiff.py` | 一致 1170 / 分叉 857 / SKIP 23-18（t83 函数体 stage-1 尚未支持 result 语法，如实分叉） |
| `python tests/irdiff.py` / `emitdiff.py` | 66-0-45 / 10-0 |
| 性能（改动前 = git worktree@HEAD(v1.37) 基线，改动后各跑一遍） | 见下——**无回退** |

性能对照（基线 → 改动后）：

| 项 | 基线 | 改动后 |
|---|---|---|
| sha256 / split+join / url / json | 45 / 10 / 78 / 3 ms | 41 / 9 / 75 / 2 ms |
| gbench tokenizer / mix_arith / map_str / branchy | 3.82 / 47.8 / 4.06 / 40.0 ms | 4.13 / 47.8 / 4.06 / 52.5 ms |
| gbench str_build / buf_scan / nested / hashmix | 0.80 / 1.75 / 0.45 / 50.1 ms | 1.12 / 1.89 / 0.42 / 51.0 ms |
| bench_str scan16k / loopsum50m / collatz | 547 µs / 79.5 / 111.4 ms | 224 µs / 76.9 / 105.5 ms |

branchy/str_build/scan16k 的波动是 VBS 已知噪声（本机 ±50%，且基线那次偏高）；
改动只碰 parser 与 `?` 降级，非 result 程序的生成代码零变化。

## 已知边界 / 遗留

- **std 库未批量改造为富错误**：语言侧已通，库层 errno+上下文化属标准库工作
  （07-gaps §6 P1-4 后半）。
- **`?` 仍要求所在函数返回同一 result 枚举**：main（void）里不能用；跨错误
  类型的自动转换（From trait 之类）没有。
- **result/option 载荷仍限具名类型**：vec[T]/map 作载荷不做（与 map 值同界）。
- **错误处理行的另一半**"库函数只能退出进程"要等 std 改造，不是语言层事项。
