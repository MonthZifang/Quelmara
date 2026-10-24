# 编译器实现

> 事实来源：`tools/stage0/*.py`、`bootstrap/*`。本文回答"编译流程是什么、要改哪里"，
> 不解释语言语义（见 [`02-language.md`](02-language.md)）。

## 1. 流水线

```
.qma 源码
   │  tokenize        qlm.py        词法：关键字/运算符/字面量
   ▼
 Token 流
   │  parse_program   qlm.py        递归下降 → AST
   ▼
   AST
   │  常量求值 / 泛型展开（含类型约束校验）/ 接口校验 / 类型标注推断
   ▼
   AST（已单态化、已校验）
   │  Lower           qlm_native.py AST → QuIR（每个函数一张指令表）
   ▼
  QuIR（非 SSA，虚拟寄存器）
   │  run_pipeline    qlm_opt.py     15 个 pass + 内联 + 循环展开
   ▼
  QuIR（已优化）
   │  qlm_qla.py      ← v2.11：可在这里落盘成 .qla（目标文件）
   ▼                  （函数记录 + 全局区 + 符号表 + 类型表，确定性字节）
  QuIR（已优化）
   │  线性扫描寄存器分配            栈槽溢出
   ▼
  机器码
   │  encode + link
   ├─ native → ELF64（基址 0x400000，单 RWX 段，无重定位）
   ├─ win    → PE32+（基址 0x140000000，导入 kernel32 + ws2_32）
   ├─ arm64  → AArch64 ELF64（部分 IR 形态显式拒绝）
   └─ c      → C99 源码（仅交叉验证）
```

**整条流水线可以被跳过**：`qlm_cli` 在进入这里之前先查增量缓存（v1.100），
键 = 编译器指纹 + 主文件 + **精确 import 闭包** + 源根清单 + `QLM_*` 环境快照。
命中就直接拷上次的产物，编译器根本不启动；不命中才走上面整条链路。
闭包是编译期用审计钩子**观测**出来的（编译器 open 过哪些文件），不是重新推
import 顺序——所以改 `load_program` 的解析规则不会让缓存失效判断出错
（改它会让编译器指纹变，旧条目全废）。细节见 [`05-toolchain.md`](05-toolchain.md) §1.7。

**流水线中间也有落盘点**：`build --emit-qla` 把「已优化 QuIR」写成 `.qla` 目标文件
（v2.11）。它比缓存细一层——缓存是"整个单元的产物"，`.qla` 是"每个函数的 IR"，
所以可以只重编变了的函数（`--incr`），也可以把它当二进制库分发（`--lib` +
`--lib-input` + `link`）。档案里不含机器码，链接期才走"寄存器分配 + 编码"。
细节见 [`05-toolchain.md`](05-toolchain.md) §1.8。

### 1.1 所有权检查（`Lower.check_ownership`，v1.84）

**在哪一步**：`qlm_native.lower_fn` 的**第一行**（`if f.get("body"): self.check_ownership(f)`），
即"AST 已单态化、已校验"之后、发第一条 IR 之前。**纯 AST 级**，不碰 IR，
所以运行时零成本、`--no-opt` 与各优化开关都不影响它。

**它能看到什么**：`f["params"]`（名字 + 类型元组）、`f["ret"]`、`self.structs`
（字段表）、`self.fns_ast`（别的函数的返回类型）。**没有类型推断结果**——
局部变量的类型只能靠 `let` 上的标注、`arraylit` 长度、`slice_of`/`structlit`
的形态反推。这是它保守的原因：认不出的一律不报（宁可漏，不可误报）。

**四类检查与扩展点**：

| 检查 | 实现位置 | 扩展方式 |
|---|---|---|
| rc 线性 | `check_ownership` 内 `scan()`（递归、按 `if` 分支合并状态） | 新增 rc 语义时同时改 `is_rc_producer` 与 `assign`/`return` 的转移规则 |
| 视图生命周期（逃逸） | `_check_views` 的 `escape_one()` | 新增"比本帧活得久"的地方（容器方法 / 线程原语）时加一条调用 |
| 视图写别名 | `_check_views` 里 `assign_index` 分支 + `_ranges_may_overlap` | 新增可判定的区间形态时补 `_bound` / `_shift_bound` |
| 跨线程 | `_check_views` 里 `spawn` 分支 | 新增线程原语（`parfor` 归共享内存模型，不在此列） |

**视图基址分类**由 `_view_of` / `_place_view` 完成，五类：本帧栈 / 堆 / 静态 /
形参 / 返回值未知。改视图构造语法（新的切片来源、新的 str 构造函数）时，
**必须同时在这两个函数里登记**，否则新来源会静默归"未知"（= 不检查）。

回归：正例 `tests/t116_ownview.qma`，负向 `tests/bad/own_*.qma`（8 个，含
`own_nested_match`——专守 `_own_parts` 不跳过块体），
编译期开销见 `tools/dev/own_bench.py` 与 [`06-status.md`](06-status.md) §3.9。

### 1.2 闭包降级（`Lower.lower_lambda`，v1.95）

| 阶段 | 做什么 |
|---|---|
| 解析 | `Parser.parse_lambda`：表达式位置的 `fn(...) {...}` → `("lambda", 形参表, 返回类型, 体, 行号)`；`closure` 在 `Parser.__init__` 里登记成 `{code, env}` 两字的内建 struct（与接口值同构，跨文件合并时豁免重名） |
| 创建点 | `Lower.eval` → `lower_lambda`：`__alloc(8n)` 开环境 + 逐个 `store` 捕获值 + 两字闭包槽（`mov fnaddr` 写 code，环境指针写 env） |
| 延后降级 | lambda 体压进 `self.pending_lambdas`，**所有顶层函数降级完**再 `lower_pending_lambdas()` 统一降级（体里还能再产生 lambda，队列边降边追加） |
| 合成函数 | `__lam_N` 形参表 = `("__env__", int)` + 原形参；入口处按固定下标 `load` 捕获值并重新打类型标记，之后体内与普通局部变量完全一致 |
| 调用点 | `Lower.lower_call`：`_struct_of(callee) == "closure"` → `code = c[0]; env = c[1]; callr code, [env, args…]` |

**为什么延后**：`lower_fn` 会改 `fn_ret_agg` / `fn_ret_target` / `loop_stack` /
`defer_stack` 这些按函数保存的 Lower 状态；在外层函数降到一半时递归降级内层会污染它们。

**捕获分析**是纯 AST 遍历（`_lambda_uses` / `_lambda_bound` / `_lambda_assigns`），
不碰 IR；名字排序后进环境，保证同一份源码产出同一份布局（可复现）。

**不动的地方**：QuIR 没有新增操作码——`__alloc` / `store` / `load` / `callr` 全是既有指令，
所以优化器、寄存器分配、x86-64 编码器、AArch64 发射器都零改动。
新增闭包相关能力（多字捕获、递归、跨函数签名）时，改的是 `lower_lambda` /
`_capture_tag` / `lower_pending_lambdas` 三处，不需要动后端。

### 1.3 `Drop` 降级（`Lower.block` / `emit_drop`，v1.93）

析构是**隐式调用**——AST 里没有 `call` 节点，只有一条 `impl T : Drop` 声明。
所以它比 defer（有显式语句）多一道"表要先算好"的手续：

| 阶段 | 做什么 |
|---|---|
| 解析 | `Parser.__init__` 预置内建接口 `Drop`（`drop(self) -> void`），用户直接写 `impl T : Drop`；`impl` 左侧类型必须已声明 |
| 建表 | `qlm_native.drop_table(fns_ast)` → `{类型名: 函数名}`；**在 `global_dce` 之前**调用 |
| 保根 | `global_dce(fns_ast, keep=set(drops.values()))`：析构函数是隐式可达，只从 `main` 走调用图会把它当死代码删掉 |
| 登记 | `Lower.block()` 里 `drop_stack` 与 `defer_stack` **同进同出**（同一处 push/pop），因此 `loop_stack` 记的 defer 深度可以直接当 drop 深度用 |
| 绑定 | `_stmt` 的 `let` 聚合分支：`_has_drop(sname)` → `_drop_register(dst, sname)`；`let b = a` 时 `_drop_forget(a)`（移动） |
| 发射 | 块尾 `_emit_frame(defer)` **之后**、接口槽释放**之前**，按 `reversed(frame)` 逐条 `emit_drop` |
| 提前退出 | `return` / `break` / `continue` 各补一次 `_emit_drops(fn, upto=…)`；`return a` 先 `_return_moved` 再发射 |
| 覆盖赋值 | `assign` 的结构体分支：`spec != cur` 时先 `emit_drop(cur)` 再 `struct_copy` |

**两个容易踩的点**：

1. **DCE 之后算表 = 析构被删**。`global_dce` 只认 AST 里的 `call`/`name` 引用，
   隐式析构一个都看不见。表现为"程序正常跑，但清理没执行"——静默错，所以
   建表必须在 DCE 之前，且用 `keep=` 钉成根。
2. **不能借 `lower_call` 发析构**。`lower_call` 对聚合实参一律"拷进临时帧槽再传地址"
   （值语义），析构就只改到副本——`c.fd = -1` 白写，fd 还会被关两次。所以
   `emit_drop` 直接 `fn.emit("call", None, name, [slot])`，把对象地址原样传过去。

**扩展点**：加"字段 drop glue"（struct 里的字段递归析构）改 `emit_drop`（按
`self.structs[sname]` 逐字段查 `drop_fns`）；加"容器元素析构"改 `vec/map` 的
`pop`/`free` 路径 + `_drop_register` 的登记口径；把析构扩到形参要先解决
"调用方与被调方谁拥有"（本版按借用处理，不析构）。

回归：`tests/t119_drop.qma`（12 组断言）、`tests/bad/drop_arity.qma` /
`tests/bad/drop_dupe.qma`；性能见 [`06-status.md`](06-status.md) §3.4h。

### 1.4 接口 vtable 与跨文件接口种子（v1.97 收口）

接口是**唯一需要"跨函数的数据结构"的语法**：一张函数指针表 + 一次间接调用。
两头都要编译器单独安排——解析期决定表里放什么，发射期决定表放在哪。

| 阶段 | 做什么 | 位置 |
|---|---|---|
| 解析 | `interface` 登记签名与**方法声明顺序**（顺序 = 槽位号）；接口值注册成 `{data, vt}` 两字 struct | `qlm.py` `parse_program` |
| 跨文件 | `pub interface` 的名字进 `acc_if` 种子，第二遍解析带种子重跑，因此 `impl` 可以写在别的文件 | `qlm.py` `load_program` |
| 建表 | `build_iface_meta` 按 `(iface, type)` 收 `[方法名]`，槽位按接口声明序对齐 | `qlm_native.py` |
| 装箱 | `box_iface`：`__alloc(16+8w)` → `[rc][字节数][payload]`，`data` 指向 payload，`vt` 存表地址 | `qlm_native.py` `Lower` |
| 派发 | `obj.m()` → `vt[slot]` → `callr`（x86 `call r`，A64 `BLR`） | 两端各自的发射层 |
| 表落位 | 代码段**尾部**依次放各表，槽是 8 字节绝对地址，收尾时按函数标签回填 | `qlm_pe.py` `gen_vtables` / `qlm_arm64.py` `vt_fixups` |
| 释放 | 块尾 / 提前退出 / 赋值替换 / `break`·`continue` → `__iface_release`；进容器 → `__iface_retain` | `qlm_native.py` `_iface_exit` |

**四个容易踩的点**

1. **槽位顺序必须是"接口声明序"，不是 impl 书写序**。两边不一致时派发会跳到
   错误的方法上——症状是"调 A 得到 B 的返回值"，比崩溃更难查。所以
   `build_iface_meta` 用 `iface_order` 排序，`gen_vtables` 只按这张表铺。
2. **宽松第一遍扫描的接口占位不能进种子**。`impl T : Shape` 里出现的名字，
   第一遍扫描时接口可能还没扫到，只能先占位；若占位进了 `acc_if`，
   拼错的名字（`Shappe`）在第二遍会被当成合法种子，得到一个**空 vtable**，
   派发永远走不到（v1.88 修：`iface_provisional` 单独记账，`_consts_of` 过滤）。
3. **同名方法跨接口要二次 mangling**（`Type__Iface__m`）。否则两张 impl 的
   方法名撞车，后者覆盖前者，其中一个接口的 vtable 槽指向错的方法。
   静态调用此时必须报歧义，不能随便挑一个。
4. **A64 的 vtable 是"数据"，不是指令**。`enc.emit(0)` 占两个 32 位字，
   收尾时把 64 位绝对地址拆成低/高两半回填；`enc.resolve()` 之前不能算地址。

回归：`tests/t52_iface.qma` / `t54_iface_dyn` / `t116_iface_multi` /
`t118_iface_own` / `t104_generic_enum_impl` / `fixtures/ifacexfile/`（正向），
`tests/bad/iface_*.qma`、`tests/bad/iface_xfile_*/`（负向），
`tests/iface_lowheap/`（引用计数回收）、`tests/a64_iface_test.py`（A64 执行级）。

## 2. 模块分工

| 文件 | 行数 | 职责 | 要改它当…… |
|---|---|---|---|
| `tools/stage0/qlm.py` | ~8005 | 词法、语法、类型推断、常量求值、泛型展开（含类型约束校验）、接口校验、模块加载与链接期 mangling、**doc comment 扫描**（`scan_doc_comments`）、C99 后端 | 加语法、改类型规则、改 import 解析、改 doc comment 规则 |
| `tools/stage0/qlm_opt.py` | ~1786 | 优化 pass、范围分析、调度、边界消除 | 改优化效果 |
| `tools/stage0/qlm_native.py` | ~11836 | AST→QuIR、x86-64 编码器、ELF64 写出、运行时、内建函数 | 加内建、改指令编码、改运行时 |
| `tools/stage0/qlm_pe.py` | ~530 | PE32+ 头、节表、导入表、DIR64 重定位 | 改 Windows 产物 |
| `tools/stage0/qlm_arm64.py` | ~798 | AArch64 编码与发射 | 补 AArch64 特性 |
| `tools/stage0/qlm_cli.py` | ~954 | build/run/test/fmt/doc/lex/bench/debug/cov/fuzz/lsp/version | 加命令 |
| `tools/stage0/qlm_index.py` | ~1847 | LSP 语义索引：位置感知词法 + 容错结构索引 + 补全/跳转/重命名 | 改补全/跳转语义 |
| `tools/stage0/qlm_lsp.py` | ~586 | LSP 3.17 子集 stdio 服务（JSON-RPC 层） | 加 LSP 方法 |
| `tools/stage0/qlm_cache.py` | ~532 | 增量编译缓存（内容寻址 + 精确依赖闭包） | 改缓存键/失效规则 |
| `tools/stage0/qlm_qla.py` | ~647 | **`.qla` 目标文件**（v2.11）：容器读写 + 自校验、IR 序列化、多档案链接（gid 重编号 / 单例全局字共享 / 同名去重 / 未定义符号检查）、符号表渲染 | 改档案格式、改链接规则 |
| `tools/stage0/qlm_mem.py` | ~904 | 内存相关运行时（QuIR 片段） | 改分配器 |
| `tools/stage0/qlm_mt.py` | ~936 | 多线程/任务运行时 | 改 spawn/parfor |
| `tools/stage0/qlm_store.py` | ~1186 | 存储/持久化运行时 | 改存储层 |
| `tools/stage0/qlm_uring.py` | ~1195 | io_uring 后端（C 链） | 改 Linux 异步 IO |
| `tools/stage0/qlm_fmt.py` | ~199 | 格式化器 | 改排版规则 |
| `tools/stage0/qlm_doc.py` | ~303 | doc comment 生成器（`quelmara doc`）：扫描、Markdown/JSON 渲染、`--check` / `--missing` 门禁 | 改文档版式、加输出目标 |
| `tools/stage0/qlm_dbg.py` | ~1254 | **源码级调试器**（`quelmara debug`）：读 `.qlmdbg`，Windows 调试 API 提供断点/单步/变量/栈 | 加调试命令、改断点语义 |
| `tools/stage0/qlm_dbinfo.py` | ~114 | 编译期调试信息发射钩子（语句行号 / 变量位置） | 改调试元数据 |
| `tools/stage0/qlm_dwarf.py` | ~432 | DWARF v4 节编码（`.debug_abbrev`/`info`/`line`/`loc`） | 改标准调试信息 |
| `tools/stage0/qlm_fuzz.py` | ~164 | fuzz 判定器（built/rejected/deep/bug/slow 五分类） | 改崩溃分类口径 |

`bootstrap/` 是自举层（Quelmara 写自己）：`lexer/qlm_lex.qma`、`parser/qlm_parse.qma`。
stage-1 parser 覆盖**声明层**：`module` / `import` / `struct` / `enum` / `fn` 签名，含
`pub` 前缀、泛型模板（跳过——stage-0 在声明层也不产出）、以及 `@derive` 的派生函数
签名与自动补的 `import std.json`。函数体只做括号配平跳过（字符串/注释感知）。
派生函数的**签名**只依赖类型名与派生项，所以 stage-1 不必复制代码生成器，
只需按同一顺序产出同一批签名行。进度见 [`06-status.md`](06-status.md) §4。

## 3. QuIR

- **非 SSA**：虚拟寄存器可被多次赋值。循环内变量必须**原地更新**（`dst == src`），
  否则会读到旧值——写新 vreg 再 rebind Python 变量会导致死循环。
- 指令形态：`(op, dst, src...)` 的元组列表，`label` 是跳转目标。
- 操作码（46 个）：

```
数据    mov  movaddr  load  load32  store  frameaddr  lea(隐含)
算术    bin(add/sub/mul/div/mod/and/or/xor/shl/shr/sar)  cssub  neg  not
浮点    fbin  fneg  fcvt  fcmpset
比较    cmpset  trunc
控制    label  jmp  jcc  jz  ret  call  callr
内存    memfence(mfence)  xchg  atomic
并发    spawn_child  pause  rdtsc
SIMD    vsum  vsumd  xmm_ld  xmm_st  xmm_paddd  xmm_pshufd  xmm_palignr  xmm_pxor
SHA     cpuid_sha  sha_rnds2  sha_msg1  sha_msg2  sha_nexte
平台    syscall(Linux)  winapi / winargs(Windows)
```

## 4. 优化 pass

`qlm_opt.py` 的 `run_pipeline(fns, inline=True, unroll=True)` 依次执行：

| pass | 作用 |
|---|---|
| 内联 | 小函数内联（`QLM_NO_INLINE=1` 关）；worker 是寄存器分配边界，不内联 |
| `opt_strlen_hoist` | 循环内 `len(s)` 外提（长度前缀使之为纯读） |
| `opt_cse` | 公共子表达式消除（GVN 风格） |
| `opt_licm` | 循环不变量外提（**默认关闭**，`QLM_ENABLE_LICM=1` 开） |
| `opt_loop_unroll` | 循环展开（阈值可配） |
| `opt_strength_reduce` | 强度削减（乘 2 的幂 → 移位等） |
| `opt_signed_divmod_simplify` | 有符号除模的符号修正消除 |
| `opt_mod_inductive` | 模归纳削减（`(i*7)%13` 滚动更新） |
| `opt_bounds_elim` | 越界检查消除（循环窗口证明 + **等值类**跨两次 len 读取） |
| `opt_bounds_dedupe` | 重复越界检查去重 |
| `opt_schedule` | 指令调度（按延迟表重排） |
| `opt_dce` | 死代码消除 |
| `opt_copy_prop` | 复制传播（`_subst_vregs` 替换操作数） |
| `analyze_ranges` | 值域分析（支撑除模特化与越界证明） |
| `analyze_nonneg` | 非负分析（`/` `%` 跳过符号修正） |
| `check_suspicious_loops` | **不是优化**：检测"guard 变量在循环体内不更新 + 常量上界"的死循环并警告 |

`QLM_SKIP_PASSES=<name>` 可逐个跳过，用于定位"哪个 pass 引入的错误"。

### 4.1 新增 IR 指令的登记清单（漏一处 = 静默误编译）

1. `qlm_opt.vreg_mentions` —— defs/uses（寄存器分配与 DCE 依赖）
2. `qlm_opt._subst_vregs` —— 复制传播的操作数替换（漏了 = 悬空 vreg 段错误）
3. `qlm_opt._EFF` —— 副作用表（访存类不可挪过 `call`；`rdtsc` 属"纯读但不可挪"）
4. `qlm_native._map_ins` —— 内联时的寄存器重命名
5. `qlm_native.Codegen.gen_instr` —— x86 编码；同时 `qlm_arm64` 必须**显式拦截**（fail-fast）

## 5. 寄存器分配

线性扫描（linear scan），栈槽溢出：

- 调用约定：整数参数 `rdi rsi rdx rcx r8 r9`，返回 `rax`；浮点走 `xmm0` 起。
- 溢出槽按 8 字节对齐，`mem_load64/store64` 的偏移是**槽索引**（×8）。
- **worker（`parfor`/`spawn`）是分配边界**：跨 worker 不做寄存器级优化，也不内联。
- LICM 关闭的根因就在这里：x64 分配器对布局敏感，开启后偶发段错误（未根修）。

## 6. 后端

### 6.1 ELF64（Linux `--target native`）

- 基址 `0x400000`，单 RWX 段，无重定位，直接 `syscall`。
- 线程：raw `clone()` + `wait4()`，工作线程栈 512 KB。
- 堆：`mmap` 保留虚拟地址，按 1 MB 粒度 `mprotect`/提交。

### 6.2 PE32+（Windows `--target win`）

- 基址 `0x140000000`，`.text`/`.data` 节，DIR64 重定位。
- **无 CRT**：不链接 msvcrt，入口即 `main`。
- 导入表支持**多 DLL 分组**：内置调用按白名单归组（`kernel32.dll` + `ws2_32.dll`，
  `qlm_pe.py` `WS2_32_FUNCS`——新增网络 API 必须加进去，否则归到 kernel32，
  加载时报 `0xC0000139`）；`@ffi` 声明则**自带 DLL 名**，见 §6.2.2。
- 堆：`VirtualAlloc` 保留 + 按需 `MEM_COMMIT`；512 MB 上限只在真正写到时才消耗物理内存。
- **reactor 不在编译器里**（v2.12）：IOCP 事件循环是 `std/net/reactor.qma` 的 Quelmara
  源码（v1.4 起那 400 行 emit 调用已删除）。stage-0 只留两个原语——`thread_start`
  （Win64 线程入口 ABI）与 `net_config`（编译期读 `[net]`）。改 reactor 行为改 `.qma`。

### 6.2.2 FFI 链路（`@ffi`，v1.87）

一条 `@ffi` 调用从源码到机器码经过五个点，改任何一处都要同步另外四处
（§4.1 的登记清单同样适用）：

| 阶段 | 做什么 | 位置 |
|---|---|---|
| 解析 | `@ffi("dll"[, "Sym"])` -> `fdef["ffi"] = {dll, sym}`；形参/返回类型白名单（`int/bool/f64/f32`，返回可 `void`）在此 fail-fast | `qlm.py` `Parser._bind_ffi` |
| 降级 | 登记 `ffi_decls`（name -> dll/sym/形参类/返回类）；调用点发 `('ffi', dst, dll, sym, kinds, ret, [args])`，`kinds` 由**声明**决定（`"i"` / `"f64"` / `"f32"`），整数实参按 C 口径自动转浮点 | `qlm_native.py` `Lower.lower_ffi` |
| 平台闸 | `platform != "windows"` 直接报错（ELF 是静态 ET_EXEC，没有动态链接器） | `qlm_native.py` `Lower.run` |
| 优化 | `ffi` 进 `vreg_mentions` / `_subst_vregs` / `_EFF` / `_LAT` / 分配器的 `call_sites`；内联时 `_map_ins` 重命名 | `qlm_opt.py`、`qlm_native.py` |
| 编码 | Win64 布局：整数 `RCX/RDX/R8/R9`、浮点 `XMM0-3` 独立计数，第 5+ 个同类实参落 `[rsp+32+8k]`，恒留 32 字节 shadow space；返回值 `RAX`/`XMM0`，`bool` 零扩展 32 位 | `qlm_pe.py` `WinCodegen.gen_ffi` |
| 导入表 | `api_fixups` 记 `(patch, dll, api)`；`_resolve_dll` 只对 `dll=None` 的内置调用查白名单；每个 DLL 一组 `{ILT, IAT}`，IAT 槽按 `(dll, 符号)` 键回填 `call [rip+disp32]` | `qlm_pe.py` `build_idata` / `build_pe` |

两个"看起来能省、实际不能省"的点：

1. **搬移顺序必须是 栈实参 -> XMM -> 整数寄存器**。XMM 装载读的是 GPR 里的位模式
   （Quelmara 的 f64 值就存在整数寄存器/帧槽里），一旦先做整数搬移，那些 GPR
   已被 `RCX/RDX/R8/R9` 覆盖，浮点实参就会拿到别人的值。
2. **`bool` 返回值必须按 32 位零扩展**。Win32 的 `BOOL` 是 `int`，高位是脏的；
   不截断就会出现"`CloseHandle` 返回真但 `if` 判假"这类只在少数 API 上复现的怪事。


### 6.2.1 调试信息发射（`--dbg-info`，v1.75/v1.80）

| 阶段 | 做什么 | 文件 |
|---|---|---|
| 解析 | `parse_stmt` 包一层，语句元组尾部追加 `("__line__", n)`（钩子成对安装/卸载，不改 parser 本体） | `qlm_dbinfo.py` |
| 降级 | 语句边界发 `('line', n)`；let 发 `('dbgvar', name, vreg)`；形参发 `('dbgparam', …)` | `qlm_native.py` `Lower` |
| 优化 | 三种标记登记进 `vreg_mentions` / `_EFF`（可浮动 = 断点落在语句执行之后） | `qlm_opt.py` |
| 编码 | `Codegen._dbg_finish` 把 vreg 映射成 `("r", 寄存器)` / `("m", 帧槽)`，带 `bind`/`last` 活跃区间 | `qlm_native.py` `Codegen` |
| 写节 | `.qlmdbg`（JSON）+ `.debug_*` 四节（DWARF v4），长节名走 COFF 字符串表 | `qlm_pe.py` `build_pe` |
| 编码 DWARF | 行表 / 变量 DIE / `.debug_loc` 区间，地址用 RVA | `qlm_dwarf.py` |

新增一种**语句形态**时，若它自己生成多条指令，必须确认 `line` 标记在该语句的
第一条指令之前（否则断点会落在语句中间，看到"执行了一半"的状态）。

调试构建默认关内联（`lower_and_optimize` 里 `prog is None` 才 inline）：
内联会把被调函数变成死代码，源码断点静默不命中。默认构建完全不受影响
（标记指令根本不进 IR）。

### 6.3 AArch64（`--target arm64`）

编码器与发射器独立（`qlm_arm64.py`），与 x86-64 **共用 QuIR / 优化 / 分配器**。
已接：基础标量 / 控制流 / 8 参寄存器传参 / **interface vtable 动态分发**（v1.97，
`BLR` 派发 + 代码段尾部的 8 字节槽函数指针表，表项用 `vt_fixups` 回填绝对地址）。
**未接**：`chan` / `map` / `spawn` / SHA-NI / `trunc` 之外的宽度 IR / `vsum*` / f64 的
`fneg` / `vdotd`。遇到不支持的形态在 `gen_all` 里**编译期明确报错**，不静默降级。

验证分两层：`tests/irdiff.py` 证明两个后端产出同一份 IR（除 syscall 号）；
`tests/a64_iface_test.py` 编译成 ELF 后用 `tests/a64_emu.py` **真跑**接口用例
（模拟器与编码器是两套独立实现，互为校验）。

### 6.4 C99（`--target c`）

仅用于交叉验证与自举对拍，**不是产品链路**。不支持 `interface`/`impl`。

## 7. 运行时

| 组件 | 实现 | 位置 |
|---|---|---|
| 分配器 | size-class freelist + bump + 1 MB 页提交；热路径 7 条指令 | `qlm_native.py` `__alloc` |
| arena | bump 指针回卷，整块回收 | `arena { }` 降级 |
| 线程 | Linux `clone` / Windows `CreateThread` | `qlm_mt.py` + `qlm_native.py` |
| 字符串 | `[len:8][bytes][NUL]`，`str_alloc` / `str_from_mem` 批量构造 | `std/str.qma` |
| 网络 | IOCP reactor（Windows；worker 数 = `[net] io_threads`，默认核数）+ 槽位层 640 B/连接 | `std/net/reactor.qma` / `std/net/core.qma` |
| 存储 | WAL/视图运行时 | `qlm_store.py` |

## 8. 调试开关

| 环境变量 | 作用 |
|---|---|
| `QLM_NO_DCE=1` | 关闭全局 DCE（保留所有函数） |
| `QLM_DCE_VERBOSE=1` | 打印 DCE 统计（保留/删除的函数数） |
| `QLM_NO_INLINE=1` | 关闭内联 |
| `QLM_ENABLE_LICM=1` | 打开 LICM（**已知会崩**，仅用于复现） |
| `QLM_SKIP_PASSES=a,b` | 跳过指定 pass |
| `QLM_MULTICORE=0` | 单核降级 |
| `QLM_HEAP_LIMIT_MB=n` | 覆盖堆上限 |

命令行：`--dump-ir` 打印 QuIR，`--no-opt` 关闭优化管线，`build` 后可用 `capstone` 反汇编对照。

## 9. 改编译器的顺序建议

1. 先写一个**最小复现**（30 行内），确认是编译器问题而不是自己越界写。
2. `--no-opt` 对照：区分"优化器错"与"codegen 错"。
3. `QLM_SKIP_PASSES` 逐 pass 排除。
4. `--dump-ir` 看降级结果是否符合预期（多数"语义错"在这一步就能定位）。
5. 加回归夹具，再改代码。

### 9.1 同一个语义往往有两条降级路径

表达式位置和**条件位置**是分开实现的：

| 位置 | 入口 | 比较如何降级 |
|---|---|---|
| 表达式（`let c = a > b`） | `arith()` | 先判浮点 → `fcmpset`；否则 `cmpset` |
| 条件（`if a > b` / `while a > b`） | `branch()` | 直接 `jcc`（v1.19 前**漏了浮点分流**） |

v1.19 的浮点比较 bug 就是这么来的：`arith()` 正确，`branch()` 漏了，
于是 `if -2.0 > -1.0` 成立。**改比较/逻辑语义时，两处都要改，并且两处都要有夹具。**

同类"双路径"还有：`for-in` 与索引循环、`print` 与 `eprint`、`==` 与 str 内容比较
（`__str_eq`）。看到一处实现时，先搜另一处。
