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
   │  常量求值 / 泛型展开 / 接口校验 / 类型标注推断
   ▼
   AST（已单态化、已校验）
   │  Lower           qlm_native.py AST → QuIR（每个函数一张指令表）
   ▼
  QuIR（非 SSA，虚拟寄存器）
   │  run_pipeline    qlm_opt.py     15 个 pass + 内联 + 循环展开
   ▼
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

## 2. 模块分工

| 文件 | 行数 | 职责 | 要改它当…… |
|---|---|---|---|
| `tools/stage0/qlm.py` | ~4546 | 词法、语法、类型推断、常量求值、泛型展开、接口校验、模块加载、C99 后端 | 加语法、改类型规则、改 import 解析 |
| `tools/stage0/qlm_opt.py` | ~1716 | 优化 pass、范围分析、调度、边界消除 | 改优化效果 |
| `tools/stage0/qlm_native.py` | ~8730 | AST→QuIR、x86-64 编码器、ELF64 写出、运行时、内建函数 | 加内建、改指令编码、改运行时 |
| `tools/stage0/qlm_pe.py` | ~390 | PE32+ 头、节表、导入表、DIR64 重定位 | 改 Windows 产物 |
| `tools/stage0/qlm_arm64.py` | ~656 | AArch64 编码与发射 | 补 AArch64 特性 |
| `tools/stage0/qlm_cli.py` | ~509 | build/run/test/fmt/lex/bench/version | 加命令 |
| `tools/stage0/qlm_mem.py` | ~904 | 内存相关运行时（QuIR 片段） | 改分配器 |
| `tools/stage0/qlm_mt.py` | ~936 | 多线程/任务运行时 | 改 spawn/parfor |
| `tools/stage0/qlm_store.py` | ~1186 | 存储/持久化运行时 | 改存储层 |
| `tools/stage0/qlm_uring.py` | ~1195 | io_uring 后端（C 链） | 改 Linux 异步 IO |
| `tools/stage0/qlm_fmt.py` | ~199 | 格式化器 | 改排版规则 |
| `tools/stage0/qlm_dbg.py` | ~147 | Windows ctypes 调试小工具 | 排查加载/异常码 |

`bootstrap/` 是自举层（Quelmara 写自己）：`lexer/qlm_lex.qma`、`parser/qlm_parse.qma`。
进度见 [`06-status.md`](06-status.md) §4。

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
- 导入表支持**多 DLL 分组**：`kernel32.dll` + `ws2_32.dll`
  （`qlm_pe.py:150` `WS2_32_FUNCS` 白名单——新增网络 API 必须加进去，否则归到 kernel32，
  加载时报 `0xC0000139`）。
- 堆：`VirtualAlloc` 保留 + 按需 `MEM_COMMIT`；512 MB 上限只在真正写到时才消耗物理内存。

### 6.3 AArch64（`--target arm64`）

编码器与发射器独立（`qlm_arm64.py`）。已接基础标量/控制流；**未接**：`chan` / `map` /
`spawn` / vtable 动态分发 / atomic / SHA-NI / `trunc` 之外的宽度 IR / `vsum*`。
遇到不支持的形态在 `gen_all` 里**编译期明确报错**，不静默降级。

### 6.4 C99（`--target c`）

仅用于交叉验证与自举对拍，**不是产品链路**。不支持 `interface`/`impl`。

## 7. 运行时

| 组件 | 实现 | 位置 |
|---|---|---|
| 分配器 | size-class freelist + bump + 1 MB 页提交；热路径 7 条指令 | `qlm_native.py` `__alloc` |
| arena | bump 指针回卷，整块回收 | `arena { }` 降级 |
| 线程 | Linux `clone` / Windows `CreateThread` | `qlm_mt.py` + `qlm_native.py` |
| 字符串 | `[len:8][bytes][NUL]`，`str_alloc` / `str_from_mem` 批量构造 | `std/str.qma` |
| 网络 | IOCP reactor（Windows）+ 槽位层 640 B/连接 | `std/net/core.qma` |
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
