# v1.95 — 闭包 / 捕获：`fn(...) { ... }` 字面量 + 按值捕获（语言层红标 → 绿）

- 日期：2026-10-24
- 任务：把 `07-gaps.md` §1 的 `闭包 / 捕获 ❌（只能传函数名）` 一次补完——语法、
  捕获语义、逃逸、调用约定、文档、回归与性能口径；**只动语言层**
- 影响面：语言层（parser / Lower / C 后端 fail-fast）、测试（1 正 + 2 负）、
  基准、文档。QuIR 操作码与两个机器码后端**零改动**

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | `CLOSURE_FIELDS` + `Parser.__init__` 登记内建 `closure`（`{code, env}` 两字，跨文件合并不算重名）；`Parser.parse_lambda`（表达式位置的 `fn(...) -> T { ... }`）；`parse_primary` 分派；`_GenInfer._infer` 返回 `closure`；`_walk_stmt` 不为闭包体泄漏绑定；`Codegen.gen_expr` 对闭包 fail-fast |
| `tools/stage0/qlm_native.py` | `Fn.closig` 签名表；`Lower.lower_lambda` / `_lambda_captures` / `_capture_tag` / `_apply_capture_tag` / `_lambda_uses` / `_lambda_bound` / `_lambda_assigns` / `lower_pending_lambdas`；`eval` 分派；`lower_fn` 捕获槽回填；`lower_call` 闭包调用路径（含聚合返回值 / 实参转换）；`run()` 在顶层函数之后降级 lambda 体 |
| `tests/t126_closure.qma` | **新增**：11 组覆盖（无捕获 / 单捕获 / str+f64 / 逃逸 / 快照 / 嵌套 / 捕获 vec 句柄 / 循环建多个 / 聚合返回 + 聚合形参 / 6·8 参走栈） |
| `tests/bad/closure_capture_struct.qma` | **新增**负向：捕获 struct 必须编译期拒绝 |
| `tests/bad/closure_assign_capture.qma` | **新增**负向：体内给捕获变量赋值必须编译期拒绝 |
| `tests/bad/closure_fnptr_param.qma` | **新增**负向：把裸函数名当闭包传给 `closure` 形参必须编译期拒绝（代码地址 vs 两字聚合） |
| `tests/run_win_tests.py` | 注册 `t126_closure` + 两个负向夹具 |
| `bench/closure_bench.qma` | **新增**：直接调用 / 裸函数值 / 闭包（0 捕获 / 1 捕获）/ 创建成本 |
| `docs/02-language.md` | §3 类型表加 `closure` 行；§6.4 函数值条目改口径；**新增 §6.5 闭包**（语义表 + 边界 + 实现） |
| `docs/04-compiler.md` | **新增 §1.2 闭包降级**（阶段表、为什么延后、捕获分析、不动后端） |
| `docs/06-status.md` | §1 补闭包回归行；**新增 §3.4i 闭包成本** |
| `docs/07-gaps.md` | §1 `闭包 / 捕获` ❌ → ✅；`函数值` 行口径同步 |

## 设计（为什么是这两字）

闭包值 = `{code, env}` 两字聚合，与接口值 `{data, vt}` 同构。这样布局/拷贝/形参/
返回值/`vec[closure]` 元素全部复用既有聚合机制，**QuIR 不加操作码**：

```
创建   __alloc(8n) → 逐个 store 捕获值 → {code = fnaddr __lam_N, env = ptr}
调用   code = f[0]; env = f[1]; callr code, [env, args…]      // env 占第 1 个形参寄存器
体内   形参表 = ("__env__", int) + 原形参；捕获名在入口 load __env__[i] 并重打类型标记
```

捕获是**创建时按值快照**（不是引用捕获）：这与 `let` 的值语义一致，也让"循环里造
一堆闭包"天然各自独立。写捕获变量直接编译期拒绝（快照写入传不回去，不能静默）。

## 实测（`bench/closure_bench.qma`，n=1e7，六次运行取中位）

| 路 | ns/次 |
|---|---|
| 直接调用（可内联） | 1.3–1.5 |
| 函数名作值（裸代码地址 + `callr`） | 3.3–4.1 |
| 闭包（零捕获 / 1 捕获，不可区分） | 3.0–4.9（中位 ~4.0） |
| 闭包创建（`__alloc(8)` + 写环境 + 两字槽）+ 一次调用 | 10.6–15.2（中位 ~11.5） |

结论：**捕获不引入额外调用成本**（闭包与裸函数值同级），与直接调用的差主要是
"不能被内联"；创建付一次 `__alloc`。口径与复现见 `06-status.md` §3.4i。

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run tests/t126_closure.qma --target win` | ok（10 组断言全过） |
| `python tools/stage0/qlm_cli.py build tests/bad/closure_capture_struct.qma --target win` | 编译期拦下：`闭包暂不支持捕获聚合/切片/数组/rc 变量 'p'` |
| `python tools/stage0/qlm_cli.py build tests/bad/closure_assign_capture.qma --target win` | 编译期拦下：`闭包内不能给捕获变量 'n' 赋值` |
| `python tools/stage0/qlm_cli.py build tests/bad/closure_fnptr_param.qma --target win` | 编译期拦下：`第 1 个形参是 closure，实参不是闭包` |
| `python tools/stage0/qlm_cli.py run tests/t126_closure.qma --target win --no-opt` | ok（优化开关不影响语义） |
| `python tools/stage0/qlm_cli.py build tests/t126_closure.qma --target win --dbg-info` | ok（调试构建产物输出一致，退出码 0） |
| `python tools/stage0/qlm_cli.py build build/cl1.qma --target arm64` | ok（走同一条 `callr`，A64 无新增指令） |
| `python tools/stage0/qlm_cli.py build build/cl1.qma --target c` | fail-fast：`C 后端不支持闭包字面量` |
| `python tools/stage0/qlm_cli.py run bench/closure_bench.qma --target win` | 见 `06-status.md` §3.4i |
| `python tests/run_win_tests.py` | **PASS=266 FAIL=0 SKIP=1**（比 v1.90 快照多 2 项 = `t126_closure` + 3 个闭包负向夹具，其中 2 个并入既有负向循环；SKIP 是沙箱拦下 `wsl.exe`） |
| `python tools/dev/check_docs.py` / `check_names.py` | PASS |

## 已知边界 / 遗留

- **捕获槽只有 1 个字**：struct/enum/切片/定长数组/`rc[T]` 捕获编译期拒绝。
  放开需要变长环境布局（`{words, slot...}` + 偏移表），单开一版。
- **闭包不能递归**：字面量没有自己的名字；需要递归就写顶层 `fn`。
- **跨函数签名不可知**：`closure` 形参 / 容器元素 / 返回值拿到的闭包仍可调用，
  但返回值按标量处理（`str`/`f64` 返回值需包一层有类型的 `fn`）。同一函数内
  创建的闭包带编译期签名：返回值打标记、实参按形参转换、聚合返回值自动开出参槽。
- **没有引用捕获 / 可变捕获**：需要共享状态时捕获 `vec`/`map`/`chan` 句柄
  （句柄语义 = 共享同一份存储）。
- **C 后端不实现**（只做交叉验证）；AArch64 只验证到构建级，未跑执行级回归。
- 本轮工作区与另一会话（工具链轨）并行，`qlm.py` / `qlm_native.py` / 三份文档
  同时被两边编辑；本版只声明自己改动的那几段，合并时按函数名 / 小节核对。
