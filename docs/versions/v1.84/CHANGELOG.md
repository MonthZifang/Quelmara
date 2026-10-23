# v1.84 — 所有权检查扩到视图：切片/str 的生命周期、写别名、跨线程

- 日期：2026-10-24（编译期开销测量于 10-24 00:30 复核）
- 任务：`07-gaps.md` §1「所有权检查」🟡 → ✅。原来只查 `rc[T]` 句柄的线性，
  struct/数组/str 的别名与生命周期一概不管；本版把**视图**（切片 `[]T`、str）
  的生命周期、写别名、跨线程传递全部纳入编译期检查。
- 影响面：语言层（`Lower.check_ownership` 扩写 + `_check_views` 新增）、
  测试（1 正例 + 7 负例）、工具（`tools/dev/own_bench.py` 新增）、文档

## 做了什么

四类检查，全部在 AST 上完成（`qlm_native.py` 的 `lower_fn` 第一行），不碰 IR：

| # | 检查 | 结果 | 拦下的形态 |
|---|---|---|---|
| 1 | rc 线性 | 错误 | use-after-drop / double-drop / move-then-use（v1.8 已有） |
| 1′ | rc 泄漏 | 警告 | 函数结束时仍有活句柄 |
| 2 | 视图生命周期 | **错误** | 本帧栈视图从 `return` / 堆容器（`vec.push`·`vec.set`·`map.set`·`chan.send`）/ `spawn` 逃出；结构体字段装了栈视图时整个结构体标"含栈视图"并随拷贝传播 |
| 3 | 视图写别名 | **错误** | 同一基址上两个**独立创建**的视图区间可能重叠、且都被写入 |
| 4 | 跨线程 | **错误** | `spawn` 实参含 `rc[T]` 句柄（引用计数非原子）或本帧栈视图 |

视图基址分五类（本帧栈 / 堆 / 静态 / 形参 / 返回值未知），由 `_view_of` +
`_place_view` 判定；`[]T` / `str` 形参归"调用方所有"，`[N]T` / struct 形参是
**本帧副本**（值语义），所以 `slice_of(形参数组)` 逃逸照样报错。

写别名的口径**不是** Rust 的独占借用：切片零拷贝共享是本语言的显式语义
（`02-language.md` §3），所以 `let t = s` 算同一别名组、两处写入不报；
只有两次独立创建且区间可能重叠才报。能证不重叠就放行——常量区间按 `[lo,hi)`
判交，变量界按"同一界表达式"判首尾相接（`a[0..mid]` 与 `a[mid..8]`）。

## `_own_parts`：跳过已摊平的块体

`_check_views` 先用 `_flat_stmts` 把嵌套块摊成一维，再逐条语句处理。若对每条
**复合**语句仍走一遍完整子树，第 k 层的语句要重复访问 k 层以下的全部节点，
复杂度是 O(嵌套深度²)。`_own_parts` 只返回语句"自己的"表达式部分
（`if` 的条件、`for`/`parfor` 的界、`foreach` 的被遍历值、`match` 的被匹配值），
块体交给摊平后的下一轮，回到线性。

实测（`tools/dev/own_bench.py --scale`，每层 8 条语句，只计 `_check_views`）：

| 嵌套深度 | 摊平后语句 | 现版 | 朴素（整条语句走子树） | 倍数 |
|---|---|---|---|---|
| 4 | 48 | 0.5–1.3 ms | 1.7–2.4 ms | 1.8–3.5× |
| 8 | 84 | 1.6–2.0 ms | 6.6–7.3 ms | 3.7–4.6× |
| 16 | 156 | 2.8–3.0 ms | 26.2–27.1 ms | 9.1–9.2× |
| 32 | 300 | 5.6–5.9 ms | 107–117 ms | 18–21× |

真实代码嵌套只有 2–3 层，前后差异落在 VBS 噪声内（两个真实文件曾测出方向相反的
0.87× / 2.28×），所以这个助手**不是**为了常见情形更快，而是堵住深嵌套的平方级退化。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | `check_ownership` 末尾接 `_check_views`；新增 `_check_views` / `_view_of` / `_place_view` / `_ranges_may_overlap` / `_flat_stmts` / `_own_parts` / `_iter_nodes` / `_root_name` / `_bound` / `_shift_bound` |
| `tests/t116_ownview.qma` | **新增**：8 类合法形态的正例（帧内切片写入、别名组拷贝、同界变量切区间、返回子切片、堆 str 进 vec、struct 装切片字段、spawn 传标量、rc 线性） |
| `tests/bad/own_slice_escape.qma` 等 7 个 | **新增**：返回本帧栈视图 / 结构体带栈视图逃逸 / 同基址重叠视图都写 / rc 句柄跨线程 / use-after-drop / double-drop / move-then-use |
| `tests/bad/own_nested_match.qma` | **新增**：`match` 臂里的栈视图逃逸——专门守 `_own_parts`（臂体靠摊平、被匹配值靠 `_own_parts`，任一处漏掉这条就静默通过） |
| `tests/run_win_tests.py` | 语言特性组注册 4 个新负例（断言报错关键词），自校验组注册 `t116_ownview` |
| `tools/dev/own_bench.py` | **新增**：编译期开销探针（占比 / 产物逐字节 / 深度扫描） |
| `docs/02-language.md` | §8.3 重写为"检查范围表 + 基址五分类 + 写别名口径 + 如实登记的不查项" |
| `docs/04-compiler.md` | 新增 §1.1：检查在哪一步、能看到什么、四类检查的扩展点 |
| `docs/06-status.md` | 新增 §3.9：占比 0.45–0.60%、产物逐字节一致、`_own_parts` 深度扫描 |
| `docs/07-gaps.md` | §1「所有权检查」🟡 → ✅ v1.84；§8 推进顺序同步 |
| `tools/dev/check_origin.py` | 修一条误报：Rust 特征 `fn main() ->` 会命中 Quelmara 自己的 `pub fn main() -> int`（`tests/doc_test.py` 内嵌源码串），收紧为 `fn main() -> ()` / `fn main() -> Result<` |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=233 FAIL=0 SKIP=1**（SKIP 为 WSL 交叉验证，本机被沙箱拦）。口径：本工作区 2026-10-24 00:29 快照；此后并行轨仍在往 `run_win_tests.py` 加用例，**合并方需复核这一行** |
| `python tools/stage0/qlm_cli.py build tests/bad/own_nested_match.qma` | `SyntaxError: 所有权检查失败：pick: 返回的视图 … 悬垂`（match 臂里的逃逸，守 `_own_parts`） |
| `python tools/stage0/qlm_cli.py run tests/t116_ownview.qma --target win` | `ownview ok` |
| 7 个 `tests/bad/own_*.qma` 逐个 build | 全部 `SyntaxError: 所有权检查失败`，报错文案命中预期关键词 |
| `python tools/dev/own_bench.py` | 检查器占端到端 **0.45–0.60%**（213 个函数） |
| `python tools/dev/own_bench.py --bytecheck` | 检查开/关产物 **sha256 一致**（23552 B / 53248 B）→ 运行时零成本 |
| `python tools/dev/own_bench.py --scale` | 32 层嵌套下朴素写法慢 **18–21×** |
| `python tools/dev/check_origin.py` | PASS（修正前 FAIL 1 处：`tests/doc_test.py` 的 Quelmara 源码串被当成 Rust） |

## 已知边界 / 遗留

- **不是** "Rust 那套借用检查"：没有独占借用，切片零拷贝共享是显式语义。
- 不查：多线程同时写同一堆内存的**数据竞争**（只拦 rc 句柄与栈视图跨线程）、
  `mem_str` 裸指针的来源、**跨函数别名**（被调方写 `[]T` 形参，调用方看不到）。
- `vec` / `map` / `chan` 仍是句柄语义，不做线性检查。
- `_own_parts` 对 `defer` 的表达式不扫（`defer` 仍在同帧执行，逃逸判定的漏报方向是保守）。
- 版本目录：`v1.85`（int 点积）由同一语言轨另行归档；`v1.86` 起属另一条轨。
