# v2.11 — 目标文件 `.qla`：函数级增量 + 二进制库分发（工具链 §3 最后一条 🚧 收口）

- 日期：2026-10-24
- 任务：`docs/07-gaps.md` §3 的「库归档 `.qla` | 🚧 | 无目标文件格式 → 无法**函数级**
  增量编译、无法分发二进制库」一次补成 ✅。**只动工具链**（编译器新增"可复用"与
  "可存根"两个钩子，不新增语言语法）。
- 影响面：`tools/stage0/`（新增 `qlm_qla.py`，改 `qlm_native.py` / `qlm_pe.py` /
  `qlm_cli.py`）、测试、基准、文档

## 主事件

`.qla` 是**目标文件**：一个编译单元的「已优化 QuIR + 全局数据区 + 符号表 + 类型布局」，
不含源码、也不含机器码。它同时解决两件事：

1. **函数级增量**：重编时按函数比对哈希，只重降级变了的函数，其余直接复用档案里的
   IR。无改动时产物与全量构建**逐字节相同**（这是"档案没说谎"的硬证据）。
2. **二进制库**：`--lib` 产出的档案可以脱离源码分发；使用方 `--lib-input` 只拿签名与
   类型布局，`link` 把多份档案的 IR 按**名字**合并成一份可执行文件。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_qla.py`（新，647 行） | `QLA1` 容器：header JSON + `meta` 段 + 全局数据段，段级/整体 sha256，确定性字节；`Archive` 读写与自校验；IR ↔ JSON 严格互逆；`merge()`（gid 按单元基址重编号、进程级单例全局字共享、同名函数按"忽略 gid 的结构签名"去重、vtable 合并、未定义符号检查）；`symbols()` / `describe()` |
| `tools/stage0/qlm_native.py` | `Lower(seed=…)`：接管全局区 / 单例全局字 / 计数器 / 字符串池映射；`Lower.run(reuse=…, reuse_order=…)`：按档案顺序接管、只降级没复用的函数、`uses_*` 标志按函数记增量（`needs`）、同名 helper 去重、需要的内联体已在档案里时**跳过整个运行库发射**；`fn_hashes()`（AST + 类型环境 + 被引签名）；`_env_digest()` / `cfg_digest()`；**内联传播**（`Fn.inlined_from` + 复用时的不动点失效）；`_inject_libs()`（`.qla` 签名存根 + 类型表注入，含 tuple 还原与布局冲突检查）；`_fill_meta()`（档案元数据）；`opt_inline(only=…)`；`lower_and_optimize(reuse=, keep_all=, libs=, meta=)` |
| `tools/stage0/qlm_pe.py` | `transpile_win(reuse=, libs=, meta=)`；新增 `emit_archive()`（编译到档案，`kind="lib"` 时不做 DCE）与 `link_win()`（多档案 → PE） |
| `tools/stage0/qlm_cli.py` | `build` 加 `--emit-qla` / `--lib` / `--incr` / `--lib-input`；新子命令 `link`、`qla`（`--stat` / `--symbols` / `--verify`）；`version` 的工具行、模块文档串 |
| `tests/qla_test.py`（新，32 条） | 往返逐字节（12 个代表夹具）、函数级增量五种形态、二进制库无源码链接、7 条失败路径、CLI |
| `tests/run_win_tests.py` | 调试链路组加 `qla_test`（主回归多一项） |
| `tests/../fixtures/qla_lib/lib.qma`、`fixtures/qla_app/app.qma`（新） | 库/使用方夹具：pub 函数 + 结构体 + 聚合实参/返回值 + 内部非 pub 函数 + 字符串跨库 |
| `bench/qla_bench.qma`（新） | 性能负载：import 六个标准库模块，展开后 98 函数 / 14695 条 IR |
| `tools/dev/qla_bench.py`（新） | 冷编译 / 无改动增量 / 改一个函数 / `link` 四档 + "解析占增量下限"的分离测量 |
| `docs/05-toolchain.md` | 新增 **§1.8 目标文件 `.qla` 与函数级增量**（容器格式、判定规则、链接规则、边界）；§1.7 的"没有 `.qla`"改成"函数级见 §1.8"；CLI 表加 `link`/`qla`/`build` 新开关；§5.2 加两个脚本 |
| `docs/07-gaps.md` | §3 的 `.qla` 行 🚧 → **✅ v2.11**（含边界）；增量/并行行的边界改写（单元级 ↔ 函数级分工）；§8 工具链推进顺序收尾 |
| `docs/06-status.md` | 新增 **§3.22**（四档耗时 + 解析下限 + 往返 192/192 + 体积口径） |
| `docs/04-compiler.md` | 流水线图加 `.qla` 落盘点；§2 模块表加 `qlm_qla.py` |
| `tools/stage0/qlm_cli.py` | `VERSION` → `2.11.0` |

## 关键设计（别推翻）

1. **档案里存"已优化 IR"，不存机器码**。存机器码就必须做重定位与跨档案符号修补，
   而 IR 的函数引用本来就是名字（`call` / `fnaddr` / vtable 槽），链接期是纯名字解析。
   代价是链接期要再跑一次寄存器分配与编码（单档案 432 ms / 98 函数）。
2. **函数哈希不能只看自身 AST**：被调方改签名会改调用方的降级（聚合返回开出参槽、
   实参转换），所以哈希里带"它引用到的函数签名"。但**不能带整张签名表**，否则
   "加一个函数"会让全库失效。
3. **内联必须传播失效**。内联把 callee 的函数体搬进了 caller，callee 一改，caller 的
   IR 就是旧副本。档案里每个函数记 `inl`（内联进来的 callee 名单），复用时沿这张表
   做不动点。**这是正确性修复，不是优化**：不做时 `helper` 从 `* 2` 改成 `* 3`，
   被内联的 `use` 仍算旧值（产物能跑、结果错）。
4. **运行库 helper 永远复用**。它们的 IR 只由编译器指纹 + 平台 + 配置决定，与用户源码
   无关；重新发射一份会把全局字重开（数据区变大）且 IR 与旧版不一致。全部函数复用
   时连运行库都不重发——这是"无改动 = 逐字节相同"的前提。
5. **复用要接管三样状态**：全局区 + `gid_of_str` 字符串池映射、进程级单例全局字
   （`argc`/`argv`/`static_word`/空闲链/`args` 拷贝标志）、计数器（`lam_seq`/`spawn_id`）。
   少一样，产物就与全量构建不一致（少第二样会让 `args()` 读到没被入口写过的零）。
6. **链接要重编两种 gid 写法**：`("ga", gid)` 元组与 `movaddr` 的**裸 gid**。漏后者时
   跨库字符串会指到别人的数据区——实测 `"hello, " + who` 打成 `qlaqla`。
7. **布局冲突必须报错**：同名 struct 两套布局 = 使用方按错偏移读写。`_inject_libs`
   逐字段比较，不一致直接编译失败。

## 实测（同机同日，`tools/dev/qla_bench.py`，min-of-5）

| 场景 | ms | 倍数 | 复用 |
|---|---|---|---|
| 冷编译到 `.qla` | 2395 | 1.00× | — |
| 无改动增量 | **1083** | **2.21×** | 69/69 函数、14695/14695 条 IR，产物逐字节相同 |
| 改一个函数体（被内联） | 1685 | 1.42× | 67/69 |
| `link` 单档案 | 432 | — | 纯发射 |

- 档案 555 KB / PE 151 KB：**IR 约为机器码的 3.7 倍**，这是分发二进制库的成本口径。
- **增量下限是解析**：`load_program()` 单独 1059 ms，无改动增量总共 1083 ms →
  复用逻辑只占 ~25 ms（2%）。下一步收益在解析缓存，不在 IR 复用。
- **往返一致**：`tests/` + `examples/` + `bench/` 里能独立编译的 **192 个源文件**，
  「直编 PE」与「档案 → 链接」逐字节相同（192/192，diff 0，另 5 个不可独立编译）。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qla_test.py` | **PASS=32 FAIL=0** |
| `python tests/qla_test.py --full`（全量往返） | 192/192 逐字节相同 |
| `python tools/stage0/qlm_cli.py build fixtures/qla_lib/lib.qma --lib -o build/lib.qla` | 16 函数 / 403 条 IR / 18 KB |
| `... build fixtures/qla_app/app.qma --lib-input build/lib.qla` | 链接后跑出 `5 6 8 14 hello, qla` |
| `python tools/stage0/qlm_cli.py qla --verify / --stat / --symbols` | 通过 / 统计 / 5 个导出符号 |
| 三道门禁（`check_names` / `check_origin` / `check_docs`） | 全 PASS |
| `python tests/run_win_tests.py` | **PASS=283 FAIL=0 SKIP=1**（SKIP 是 wsl.exe 被安全策略拦；新增 `qla 目标文件：QLA: PASS=32 FAIL=0` 一项） |

## 已知边界 / 遗留

1. **仅 `--target win`**：IR 与 ABI 都按 PE/x86-64 固化；`--dbg-info` 不走档案
   （链接产物没有 `.qlmdbg`）。
2. **档案不跨编译器/跨配置复用**：编译器指纹或配置摘要不符直接报错，不猜。
3. **改被内联的小函数会连带重编调用链**（正确性代价）；不被内联的大函数（>28 条 IR
   且多调用点）改体只重编它自己。
4. **无跨档案内联**、**无档案级调试信息**、**泛型模板与 `const` 不从档案导出**
   （`const` 在解析期内联，已经在 IR 里）、**A64/ELF 档案未做**。
5. **增量下限是解析**：解析器一个文件读三遍（宽松扫描 / 严格重解析 / `_consts_of`）。
   解析缓存是下一个可做的版本（预计能把 2.21× 抬到 4× 以上）。
6. 本表数字是在**另一条轨同时跑回归**时采的（绝对毫秒偏高 20–50%，倍数受影响小）。
