# v1.81 — 自举 parser 吃掉 `@derive`：派生宏的声明级对拍转绿（全用 Quelmara 写）

- 日期：2026-10-23
- 任务：把 v1.77 的属性宏 `@derive` 移植到**自举层**
  （`bootstrap/parser/qlm_parse.qma`，Quelmara 写 Quelmara），
  `t115_derive` / `dpub_main` / `dpub_model` 从 `PARSE1_PENDING` 移出（跳过数 12 → 11）。
- 影响面：自举层（Quelmara）、对拍清单、文档

## 为什么

v1.77 在 stage-0 里用"生成源码再解析"实现了派生宏，产物是多出来的函数声明。
stage-1（自举 parser）只认普通声明，遇到 `@derive` 会当未知注解跳过，
所以这三个文件被记在 `PARSE1_PENDING` 里——**记了账，但账还在**。

关键观察：**派生函数的签名只依赖类型名与派生项，与字段类型无关**。
所以 stage-1 不必复制代码生成器（不必知道 int/str/vec 怎么编码），
只要按 stage-0 的同一顺序产出同一批签名行即可。这让移植量从"再写一个代码生成器"
降到"一个纯函数"。

## 实现要点（全部是 Quelmara）

1. **`@derive(...)` 不再当"未知注解"跳过**：`read_derive_items` 把括号里的派生项
   读成规范串，顺序固定 `Json → Eq → Show`（与 stage-0 的 `_DERIVE_ITEMS` 一致），
   **与源码书写顺序无关**。
2. **派生签名要缓存、不能立刻输出**：stage-0 的 dump 是"所有 struct/enum 声明在前、
   所有函数签名在后"，而派生函数在 stage-0 的 fns 列表里位于**第一条用户函数之前**。
   所以 `derive_pending` 只把签名塞进 `pending` 缓冲，遇到第一条用户 `fn`（或文件结束）
   时 `flush_pending` 一次刷出。
3. **`import std.json` 要同源**：stage-0 展开 `Json` 派生时会自动补这个 import。
   stage-1 在读到 `Json` 派生项时补一行 `import|std.json`，且只补一次
   （`ds["jsonimp"]` 标记）——否则两个 `@derive(Json)` 会补出两行。
4. **顺带补两处声明层缺口**（本来被静默跳过，是同一个 dispatch 分支的事）：
   - `pub` 前缀（v1.43）：此前 `pub struct ...` 整行被"未知顶层词"跳过；
   - 泛型模板 `fn f[T](...)`（v1.11+）：stage-0 声明层不产出模板，stage-1 现在也整条
     跳过（`skip_generic_fn`：跳过 `[类型参数]`、`(形参)`、`-> 返回类型`、函数体）。
5. **状态怎么传**：语言没有全局变量。已有的游标盒 `map[str]int`（`k`）之外，
   新增一个字符串状态盒 `map[str]str`（`ds`），放 `items`（当前待展开的派生项）、
   `pending`（待刷出的签名行）、`jsonimp`（是否已补 import）。句柄语义，改动对调用方可见。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/parser/qlm_parse.qma` | 新增 `pend_add` / `flush_pending` / `read_derive_items` / `derive_pending` / `skip_generic_fn`；`parse_struct` 增加 `ds` 参数并在 struct 行后挂派生签名；`parse_fn` 认泛型模板并跳过；`main` 的 `@` 分支区分 `derive` 与其他注解、补 `pub` 分支、EOF 与 `fn` 前刷缓冲 |
| `tests/parsediff.py` | `t115_derive` / `dpub_main` / `dpub_model` 移出 `PARSE1_PENDING`（跳过数 12 → 9） |
| `docs/04-compiler.md` | §2 补 stage-1 的覆盖范围（含 `@derive` 为什么只需签名） |
| `docs/06-status.md` | §1 parsediff 行、§4 自举行数 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.81.0（并行轨随后推进到 1.82.0；`check_docs` 的版本同源检查以最新目录为准） |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/parsediff.py` | **PASS=145 FAIL=0**（跳过 11：9 个 interface/impl/泛型 + 并行轨新增的 `iface_rc` / `t116_iface_multi`）——`t115_derive` / `dpub_main` / `dpub_model` 三个派生文件逐行一致 |
| `python tools/dev/selfhost_status.py` | 组件自举 **2/9**；自举 **2024 行** / stage-0 26541 行 = **7.1%** |
| 四道门禁（check_docs / check_names / check_origin / gen_stdlib_doc） | 全 PASS |

其余对拍（主回归 / lexdiff / irdiff / emitdiff / bodydiff）本版**不复制数字**：
并行轨同一时间在改 `qlm.py` / `qlm_native.py`（实测期间它们的 mtime 每几分钟变一次，
`run_win_tests` 的失败项在两次运行之间从 3 个变成 1 个又归零），复制过来的数字
几分钟后就过期。这些数字的唯一出处仍是 `06-status.md` §1。

本版能钉死的只有一条：**自举层与 stage-0 在派生声明上逐行一致**——这一条不依赖
并行轨在改什么（对拍的 oracle 与 stage-1 都只吃源码）。

## 已知边界 / 遗留

- stage-1 仍只到**声明层**：函数体只做括号配平跳过；interface / impl / 泛型单态化
  仍未移植（`PARSE1_PENDING` 剩 9 个文件，都是这几类）。
- `@derive` 在 stage-1 只产出**签名**，不做字段类型校验（stage-0 会 fail-fast；
  非法用例在 `tests/bad/` 里，两侧都不产出声明）。
- enum 派生仍未实现（stage-0 就 fail-fast），所以 stage-1 也不需要。
