# Quelmara 自研后端设计（BACKEND.md）

> 决策：**产品后端必须自研**，不走 LLVM、不走 C 中转。C99 生成器仅保留为显式交叉验证、自举和移植工具，不属于产品运行后端。平台优先与游戏定位**两条线并行推进**，优化持续加深。
> 现状：v0.1 已实现 x86_64 全链路 —— Quelmara → RosIR → 优化 passes → 线性扫描寄存器分配 → 自研指令编码器 → **裸 ELF64 可执行文件**（无 libc、无 gcc、无外部依赖）。
> v0.3 新增 **Windows x86_64 PE/COFF 写出器 + kernel32 导入 + CreateThread 多核**（无 CRT，产物 6–26 KB）。
> v0.4 新增 **spawn/join 任务并行**（`spawn_child` IR + Linux clone / Windows CreateThread / C pthread）
> 与 **arena 帧级回收**（native 回卷 bump 指针；C 后端为作用域）。
> v0.5 新增 **chan[T] 有界 MPMC 通道**（`xchg` 原子自旋锁 + yield；C 后端条件变量），
> 并改为**运行库按需发射**（只用到的 arena/join/chan 才进产物）。
> v0.6 新增 **定长数组 `[N]T`**（帧槽 N 字、动态下标、值语义拷贝、越界 fail-fast）。
> AArch64 ELF 发射层已实现（模拟器执行级验证），待真机。

---

## 1. 编译管线

```
.ros 源码
  │  Parser（词法/语法 → AST）
  ▼
AST ── Lower(platform=linux|windows) ──▶ RosIR（函数 = vreg + 指令流，非 SSA）
  │               └─ 运行库（print/itoa/alloc/parfor）用 RosIR 自举
  │                  平台差异只在 emit_write/emit_exit/emit_alloc/parfor 的薄层
  ▼
优化 passes（见 §3 优化目录，后端/平台 100% 共享）
  │  常量折叠 → 强度削减 → 复制传播 → 死代码消除（不动点）
  ▼
寄存器分配（线性扫描 + 调用感知 + 循环回边保守扩展）
  │
  ├── x86_64 编码器（自研 REX/ModRM/SIB 发射器）
  │     ├── ELF64 写出器（Linux，单 RWX PT_LOAD，raw syscall）
  │     └── PE/COFF 写出器（Windows，kernel32 导入 + DIR64 重定位 + winapi）
  │
  └── AArch64 编码器 → ELF64 写出器（Linux）
```

**双实现交叉验证**：同一份 `.ros` 源码可显式用 C 后端（gcc -O2）与自研后端编译，输出 diff 即回归——C 生成器只作为测试 oracle，不改变产品默认的自研后端路径。

---

## 2. 核心设计决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| IR 形态 | 非 SSA、变量原地更新 | 无 phi 节点，循环/分支降级直白；配合 DCE 不动点正确处理回边 |
| 寄存器分配 | 线性扫描（9 寄存器池） | 简单可证；跨调用值强制 callee-saved 或溢出 |
| 循环处理 | 活跃区间对回边保守扩展到整个循环区 | 线性区间对回边必须保守，否则跨迭代值被复用（已踩坑修复） |
| 溢出槽 | `[rbp-8], [rbp-16], ...` | 与保存的 rbp/返回地址隔离（off-by-one 已修复并有回归测试） |
| 临时寄存器 | rax/rcx/rdx/r10/r11 不入池 | mul/div/syscall/编码 scratch 固定使用，杜绝隐式 clobber |
| 调用约定 | 自研 ABI（SysV 形状） | 无 libc 依赖；参数并行搬移算法（DAG 调度 + 环破除） |
| 多核 | raw `clone()` + `wait4()` + 共享内存归约 | 不依赖 pthread；子线程栈 mmap 独立，归约数组全局段 |
| 运行库 | RosIR 自举（print/itoa/strlen/alloc） | 整个二进制从语言自身语义生长，无外部运行时 |
| Windows ABI | kernel32 导入 + IAT `call [rip+disp32]` + Win64 shadow space | 不链 CRT；每个 winapi 指令预留 32B 影子空间，第 5/6 实参落栈 |
| Windows 代码入口 | `and rsp,-16` → `call main` → `ExitProcess(rax)` | 无 CRT 初始化；线程入口另存 RDI/RSI（Win64 callee-saved） |
| PE 绝对地址 | 每个 `movabs` 生成一条 DIR64 重定位 | ASLR 打开也正确；`fnaddr`（线程入口）同样重定位 |
| Windows 堆 | `MEM_RESERVE` + 1MB 粒度 `MEM_COMMIT` | 512MB 上限只占虚拟地址；真正写多少提交多少 |
| Windows 多核 | `CreateThread` + 共享归约 + `WaitForSingleObject` + `CloseHandle` | 与 Linux `clone()` 语义一致；单核配置编译期串行化 |
| 任务并行（v0.4） | `spawn f(args)` + `join(h)`；句柄 = `[线程句柄, 参数块]`，参数块首字存返回值 | 每任务一线程（非 work-stealing）；标量参数/返回值 |
| Linux 子线程入口 | `spawn_child`：`rdi = [rsp-8]` → `call worker` → `exit(0)` | 参数块指针放新栈顶，避开父栈溢出槽竞争 |
| arena（v0.4） | `__arena_mark/__arena_release` 回卷 bump 偏移 | 块内分配一次性回收；对象不得逃逸 |
| chan[T]（v0.5） | 48字节控制块 `[cap,head,tail,count,lock,buf]` + `xchg` 自旋锁 + yield | 有界 MPMC、阻塞 send/recv；C 后端用 pthread 条件变量 |
| `[N]T`（v0.6） | 帧上连续 N 个 8 字节槽；`load/store base,idx` 直接寻址；`frameaddr` 取首地址 | 值语义拷贝；数组作实参/返回值明确报错 |
| 越界 fail-fast（v0.6） | `bounds_check` 编译期开关；读/写前两次 `jcc` + `__bounds_fail` | 默认开启；关闭后越界即 UB |
| 运行库按需发射 | 先降级用户函数收集 `uses_arena/uses_join/uses_chan`，再发射运行库 | 非 chan 程序不带 SwitchToThread/通道代码，省体积与导入 |

---

## 3. 优化目录

### ✅ 已实现（v0.1）

| 优化 | 效果 |
|---|---|
| 常量折叠 | 编译期算术/比较全折叠 |
| 强度削减：乘 2^k → shl | 消除 imul |
| **魔数除法（mulhi + 移位）** | 常量除数的 `/` `%` 从 ~30 周期 idiv → ~4 周期乘高位；编译期搜索 (M,s) 并边界验证，含符号修正（分支无关）；不合格魔数安全回退 idiv |
| 除数 1 特例 | 直接消除 |
| 复制传播 | 消除冗余 mov |
| 死代码消除 | 全局使用集 + 不动点（正确处理循环回边） |
| cmp + jcc 融合 | 条件分支不落标志到寄存器 |
| 线性扫描寄存器分配 | 9 寄存器池，最大化寄存器驻留 |
| 调用感知分配 | 跨调用值只进 callee-saved / 溢出，避免隐式破坏 |
| 帧槽复用 | 不相交生命周期共享槽位 |
| mov 消除 | 同寄存器搬运零成本 |
| 循环范围传播 | 对严格递增常量上界循环证明非负值，消除安全的有符号魔数修正链 |
| worker 内联边界 | parfor/spawn 独立栈 worker 保留调用，避免内联造成寄存器 spill 回退 |

实测说明：本轮范围传播只作用于有唯一初始化、严格上界和无溢出证明的非负值，
用于安全收缩有符号魔数除法窗口；完整回归保持全绿。loop_sum 的跨机器 wall-clock
不作为本轮结论，下一轮 SIMD 基线会固定 CPU/构建参数后再比较。

**跨平台注意事项（新增，血泪教训）**：`winapi` 是**有副作用的屏障** —— 指令调度器必须把它
和 `call/syscall/store/load` 一起放进 `_EFF` 保序集合，否则 `WaitForSingleObject` 会被重排到
归约读取之后，多核结果静默变 0。新增任何 IR 指令都要同步：
`vreg_mentions / _subst_vregs / _map_ins / _LAT / _EFF / allocate 的 call_sites / 两个发射层`。

### 🗓 规划中（按收益排序）

| 优化 | 预期收益 | 版本 |
|---|---|---|
| 过程内联（小函数/单调用点） | parfor_sum 类调用密集负载 2x+ | v0.2 |
| 循环不变量外提 (LICM) | 通用 | v0.2 |
| 公共子表达式消除 (CSE/GVN) | 通用 | v0.2 |
| 循环展开 | 热循环 | v0.2 |
| 指令调度（填延迟槽） | imul/mulhi 延迟 | v0.2 |
| SIMD 自动向量化（SSE2→AVX2） | 热循环 2-4x | v0.3 |
| `@simd` 显式向量提示 | 游戏数学库 | v0.3 |
| 尾调用消除 | 递归/状态机 | v0.3 |
| 越界检查消除 | 带边界语义后 | v0.3 |
| 布局优化（热块前置/对齐） | 分支预测 | v0.3 |
| LTO 级全程序内联 | 工程大库 | v0.4 |

---

## 4. 平台优先 × 游戏定位：双轨并推

### 平台轨（跨平台矩阵）

| 目标 | 后端方案 | 状态 |
|---|---|---|
| Linux x86_64 | 自研编码器 + ELF 写出器 | ✅ v0.1 |
| Windows x86_64 | 自研 PE/COFF 写出器 + kernel32 导入 + CreateThread | ✅ v0.3（本机执行级 55 项） |
| Linux aarch64 | 自研 ARM64 编码器（RosIR 架构无关，只换发射层） | 🟡 模拟器执行级，待真机 |
| Windows 网络（IOCP/AFD） | 导入 WSA*/IOCP 或 AFD 设备 | 🚧 下一格（PLATFORM.md 候选 A） |
| macOS / iOS (arm64) | Mach-O 写出器 + libSystem + kqueue 运行时 | 🚧 需 Mac 真机/CI |
| Android (arm64) | 复用 Linux aarch64 + epoll | 🚧 |
| Web (wasm64) | RosIR → wasm 发射器（多核用 workers/SharedArrayBuffer） | 🚧 |
| 嵌入式 (riscv/arm) | 自研编码器 + 最小运行时（`multicore=false` + `heap_limit_mb`） | 🚧 |
| 主机平台 | 各家 SDK 适配层（NDA/法务先行） | 按需 |

移植成本模型：**RosIR 与优化 passes 100% 复用**，每个新平台 = 一个指令发射器 + 一个可执行格式写出器 + 一个 IO 后端（epoll/kqueue/IOCP/io_uring）。

### 游戏轨（帧率/确定性/内存）

| 能力 | 方案 | 状态 |
|---|---|---|
| 帧级 arena | `arena { }` 批量分配帧末整体释放，零 GC 抖动 | 运行时已备，缺语法 |
| Job 系统 | `parfor`/`spawn` 即游戏引擎任务图（work-stealing） | ✅ 雏形（Linux clone + Windows CreateThread） |
| 确定性 | 同输入同调度 → 帧耗时可复现，性能回归可 CI | 设计已定 |
| SIMD 数学库 | Vec3/Vec4/Matrix SoA 布局 + `@simd` | v0.4 |
| 缓存友好 | struct_of_arrays、批处理渲染提交 | v0.4 |
| 嵌入 C/C++ 引擎 | `@extern("C")` 导出 + C ABI | v0.4 |
| 热重载 | 模块级动态库 + 状态保留协议 | v0.5 |

---

## 5. 实测基线

### Linux（3 核容器，2026-10）

| 负载 | 自研后端 | gcc -O2（C 后端） | 备注 |
|---|---|---|---|
| fib(25) 递归 | 75025 ✓ | 75025 ✓ | 双后端交叉验证 |
| divmod 160 行 | 全等 ✓ | 参考 | 魔数 + idiv 回退语义一致 |
| loop_sum 2 亿热循环 | 518ms | 158ms | 差距 = 向量化/调度（v0.4 目标） |
| parfor_sum 3 核 6M 任务 | 388ms | 153ms | 差距 = 内联深化 |
| 单核降级（multicore=false）| 结果不变 ✓ | 结果不变 ✓ | 语义等价保证 |

回归：`bash tests/run_native_tests.sh`（含退出码检查——覆盖退出崩溃类回归）。

### Windows（本机 x64 / 20 逻辑核，2026-10）

| 负载 | PE 产物 | 时间（5 次最优） | 备注 |
|---|---|---|---|
| hello | 6144 B | — | 无 CRT，冷启动直入 main |
| fib(25) | 6656 B | — | 与 Linux ELF 输出一致 |
| loop_sum 2 亿热循环 | 6144 B | 357.9 ms | 同一套 RosIR 优化 |
| parfor_sum 20 线程 6M | 14848 B | 196.1 ms | CreateThread + 共享归约 |
| prime_parallel（10 万内素数） | 15872 B | 18.7 ms | 自校验通过 |
| game_loop（结构体帧循环） | 20480 B | — | 自校验通过 |

回归：`python tests/run_win_tests.py`（结构自检 + 执行级 + 单核降级 + assert 失败路径
+ 与 Linux ELF 逐字节交叉验证，共 55 项）。

---

## 6. 已修复的坑（教训记录）

### v0.1

1. **破坏性运算未物化操作数**：`fetch` 返回操作数原寄存器后原地 `add` 摧毁了活跃值 → 破坏性运算前强制 `mat()` 物化到 scratch。
2. **DCE 忽略循环回边**：倒序单趟把循环头使用的更新删了 → 改为全局使用集 + 不动点迭代。
3. **线性区间对回边不保守**：循环内复用寄存器覆盖跨迭代值 → 循环区间的活跃区间强制扩展。
4. **溢出槽 off-by-one**：第一个槽写到 `[rbp+0]` 覆盖保存的 rbp → 退出段错误 → 槽位从 `[rbp-8]` 起 + 退出码回归测试。
5. **魔数 M 超 64 位被截断**：搜索未限制 `M < 2^64`，movabs 截断产生错误商 → 加约束 + 不合格回退 idiv。
6. **parfor 忘记分块**：所有 clone 子线程算全区间 → 结果 T 倍 → 按线程分块 + 双后端交叉验证捕捉。

### v0.3（Windows PE，全部有回归覆盖）

7. **PE 头长度少算节表**：`headers_size` 只算到 optional header，4 个节头被 `.text` RawData 覆盖 →
   入口跳到垃圾字节，`STATUS_PRIVILEGED_INSTRUCTION (0xC0000096)`。→ 把 `40*nsec` 算进 headers_size。
8. **重定位块奇数补齐写成真实重定位**：补位项用了 `(10<<12)|0`，等于「在页首做 DIR64」，
   把入口第一条指令的 8 字节加了加载偏移 → `STATUS_ACCESS_VIOLATION (0xC0000005)`。
   → 补位必须是裸 `0x0000` 哨兵。
9. **Win64 参数寄存器搞错**：`ThreadProc(lpParameter)` 在 RCX，不在 RDI；线程入口还必须在
   RDI/RSI（Win64 callee-saved）上保存恢复 → 新增 `winargs` IR + `win_thread` 序言/尾声。
10. **优化器不认识新 IR 指令**：复制传播漏掉 `winapi` 的操作数替换（字符串指针没被绑定），
    调度器没把 `winapi` 当副作用屏障（`WaitForSingleObject` 被排到归约读取之后，多核结果静默变 0）。
    → 新增指令必须同时更新 `vreg_mentions / _subst_vregs / _map_ins / _LAT / _EFF / call_sites`。

### v0.4（spawn / arena，全部有回归覆盖）

11. **字符串条件分支比的是指针**：`if s == "x"` 走 `Lower.branch()`，旧实现对 `==` 直接
    发 `jcc`（指针比较），条件永远为假；表达式路径 `__str_eq` 是对的。
    → `branch()` 对 str 的 `==`/`!=` 走 `__str_eq`。
12. **子线程从父栈溢出槽取参数会踩父线程**：`clone` 后子线程继续用父 `rbp` 取 spill 槽，
    父线程并发复用同一槽 → 参数随机错误。→ 新增 `spawn_child`：参数块指针放新栈顶
    `[rsp-8]`，子线程用 `rsp` 直接取，不经过任何 vreg。
13. **arena 的 `release` 可能被跳过**：块内 `break/continue/return` 直接跳走 → 内存不复位。
    → v0.4 明确为约定式语义并写进 SPEC；后续用作用域清理栈统一处理。
14. **bump 分配器非线程安全**：并行 worker 里分配会竞争 `bump_gid`。
    → 文档约束：spawn 的参数块在父线程分配；worker 内不要分配。

### v0.5（chan / 运行库按需发射，全部有回归覆盖）

15. **内联标签只用 `caller.nv` 做后缀 → 跨函数同名**：两个函数的 nv 相同、都内联同一个
    callee 时生成相同标签，后发射的覆盖前者；早先函数里的跳转因此跳进**另一个函数体内**。
    症状极隐蔽：`assert(1 == 2)` 失败路径静默变成正常退出（exit 0）。
    → 后缀改为 `.inl_{caller_name}_{base}`。
16. **C 后端 spawn helper 误用调用点变量名**：helper 里写 `a->a0 = ch;`（调用者作用域的名字），
    编译报 undeclared。→ helper 只使用形参 `p0..`，实参表达式只在调用点求值一次。
17. **运行库全量发射**：即使程序不用通道，也会带上 `__chan_*` 与 `SwitchToThread` 导入。
    → `Lower.run` 先降级用户函数收集 uses_* 标志，再按需发射 arena/join/chan。
18. **自旋锁的释放必须用有序存储**：x86 TSO 下普通 `mov [lock],0` 在计数更新之后即可；
    AArch64 需要 `stlr`（当前 chan 未上 AArch64，已在 SPEC 标注）。
