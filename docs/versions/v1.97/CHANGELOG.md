# v1.97 — `interface` 黄标翻绿：装箱回收 / 跨接口同名方法 / 跨文件 impl / AArch64 vtable

- 日期：2026-10-24
- 任务：把 `07-gaps.md` §1 的 `interface` 行从 🟡 补成 ✅——一次只补一个语言项，
  补完同步文档并测性能。原行列的四个边界：
  ① 装箱不释放 ② 同类型跨接口同名方法报错 ③ 接口与 impl 必须同源文件
  ④ AArch64 未接 vtable。
- 影响面：语言层（`qlm.py` / `qlm_native.py` / `qlm_arm64.py`）、测试、文档、基准
- 注：v1.83–v1.96 由并行轨（闭包 / `@ffi` / doc comment / `Drop` / 宏 / 增量缓存）
  占用，本版顺延为 1.97

## 为什么这次能一次做完

前三个边界在 v1.83 就已经落进代码（引用计数、二次 mangling、跨文件种子），
但**没有一条能证明它对**：`07-gaps.md` 的行还是黄的，`02-language.md` §8.4 还写着
"装箱不回收 / 必须同源文件 / A64 报错"，`06-status.md` 里也没有任何一条实测数字。
本轮补的是**证据链**，外加两处真缺口（A64 发射层、宽松占位的污染）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_arm64.py` | **AArch64 vtable 发射**：代码段尾部按 `low.vtables` 铺表，每槽两个 32 位字 = 一个 64 位绝对地址；`vt_fixups` 在收尾时按函数标签回填。删掉原来"vtable 未接 → 抛 SyntaxError"的拦门 |
| `tools/stage0/qlm.py` | **宽松接口占位不再冒充声明**（`iface_provisional`）：第一遍扫描为 `impl T : X` 占位的名字单独记账，`_consts_of` 过滤后才进跨文件种子；有占位时强制走第二遍严格校验。接口冲突检查改为"真声明之间比对"（空签名不再当占位） |
| `tests/a64_iface_test.py` | **新增**：A64 执行级回归，编译成 ELF 后用 `tests/a64_emu.py` 真跑 7 个接口用例；`--quick` 跳过最慢的低堆用例 |
| `tests/iface_lowheap_a64/` | **新增**：A64 版低堆夹具（1 MB 上限 / 1.14 MB 装箱量 / 900 KB 探针），规模压到模拟器跑得动（约 23 s） |
| `tests/bad/iface_xfile_conflict/` | **新增（负向）**：同名接口在两个模块里签名不一致 → 接口冲突 |
| `tests/bad/iface_xfile_undecl/` | **新增（负向）**：`impl R : Shappe` 拼错接口名 → 未声明的接口（此前被静默接受，vtable 为空） |
| `fixtures/ifacexfile/main.qma` | 加一段**同名同签名重复声明**（幂等正例），把"跨文件重复声明"从"能用"钉成"语义明确" |
| `tests/run_win_tests.py` | 新增 `[9] AArch64 接口 vtable` 组（调 `a64_iface_test.py`）；两个跨文件负向夹具进编译期拦截清单；头部覆盖清单补 `[8]`/`[9]` |
| `docs/07-gaps.md` | `interface` 行 🟡 → ✅（四项边界逐条给证据 + 剩余边界）；§4 平台行去掉 vtable；§8 推进顺序标记 |
| `docs/02-language.md` | §8.4 重写成"值表示 / 所有权表 / 跨接口与跨文件 / 平台与边界"；§4.4 两条过期断言（不释放、同名方法报错）改正 |
| `docs/04-compiler.md` | 新增 §1.4（vtable 与跨文件种子的六个阶段 + 四个容易踩的点）；§6.3 AArch64 改成"已接 vtable" |
| `docs/06-status.md` | §1 新增 A64 接口执行级行、主回归按隔离快照复核；§3 新增 §3.4j 接口成本；§5 平台行更新 |
| `docs/versions/v1.97/CHANGELOG.md` | 本文件 |

## 关键实现点

1. **A64 的 vtable 是数据不是指令**：`enc.emit(0)` ×2 占一个槽，收尾时拆成
   低/高 32 位回填绝对地址。`enc.resolve()` 之前标签只有字索引，算不出地址，
   所以回填必须在 `resolve()` 之后、拼 `blob` 之前。
2. **占位与声明的区别是"证据"的区别**：第一遍扫描看到 `impl R : X` 时，X 可能
   还在别的文件里没扫到。给它占位是对的，但占位只能活在**当前这遍**——一旦
   进 `acc_if`（跨文件种子），第二遍就会把它当成"某处声明过"，拼错的名字
   因此静默通过，vtable 是空表，派发永远走不到。
3. **冲突检查要拿真声明比**：原来用"空签名视为占位"来兼容，结果
   `interface Foo {}`（真·空接口）和占位无法区分。现在占位在源头被滤掉，
   直接比对签名即可。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/a64_iface_test.py` | **PASS=7 FAIL=0**（t52 / t54 / t116 / t118 / ifacexfile / t104 泛型 enum 载荷 / A64 低堆回收） |
| `python tests/run_win_tests.py`（隔离快照） | **PASS=264 FAIL=0 SKIP=1**（SKIP 为沙箱拦 `wsl.exe`，交叉验证无法执行） |
| `python tests/irdiff.py`（隔离快照） | **PASS=88 FAIL=0 SKIP=68**——接口六个夹具由 SKIP 转 PASS（A64 不再缺 vtable，IR 无架构差异） |
| `python tools/stage0/qlm_cli.py run bench/iface_bench.qma --target win` | A 25.4–28.1 / B 5.4–7.7 / C 24.8–31.1 / D 4.8–5.4 ns/轮（见 `06-status.md` §3.4j） |
| 负向夹具 | `iface_xfile_conflict` → 接口冲突；`iface_xfile_undecl` → 未声明的接口；`iface_dup_method` → 静态调用有歧义 |
| 五道门禁 | check_names / check_origin / check_docs / gen_stdlib_doc 全 PASS |

## 已知边界 / 遗留

- **装箱释放不调用 payload 的 `impl T : Drop`**：`drop_table` 按具体类型挂载，
  而接口槽的静态类型是接口名。要做就得在装箱块里再存一个"析构函数指针"
  （块布局从 `[rc][字节数][payload]` 变成 4 字头），属于 v1.92 `Drop` 线的延伸。
- **每次装箱约 20 ns**：A − B = 20 ns 是 `__alloc` + payload 拷贝 + `__free` 的
  实价。接口值"装一次、循环里只派发"几乎免费（+0.6 ns），每轮新建则要按 20 ns 预算。
- **接口值没有弱引用 / 循环引用处理**：`a.b = x; x.c = a` 这类环会漏，与 rc 句柄同一条边界。
- **A64 仍缺 chan / map / spawn / SHA-NI**：与接口无关，属平台轨。
- **`06-status.md` 主回归的数字取自隔离快照**：并行轨当时仍在改 `run_win_tests.py`
  与 `tests/bad/`（本轮实测期间它删了 `derive_enum.qma` 等负向夹具），
  合并后用例数若变化，由合并方复核这一行。
