# Quelmara 交接文档（HANDOVER）

> 工作区状态（2026-10-21）：**已发布 v1.2；v1.3（自举）+ v1.4/v1.5（reactor + 性能 + 协议库）
> + v1.6（标准库六件）+ v1.8（语言特性大补）在工作区落地待提交**。  
> 各版本特性、修复与回归项数的**权威记录**在 `CHANGELOG.md`；本文只保留  
> 当前快照、差距清单与下一步排期，不再按轮复述。  
> **完整能力边界（含"文档与代码不符"逐条核对、标准库缺口全表、优先级路线）见 `docs/GAPS.md`。**  
> **工具链分层**：`tools/stage0/` 是 Python 引导层（待退场），`bootstrap/` 是 Quelmara 自举层，  
> `tests/`、`tools/dev/` 允许长期用 Python/Node。分层纪律见 `docs/SELFHOST.md`。  
> 本机（Windows）验证边界：PE 链可执行级验证；[7] 交叉验证与 native/C 链需 Linux/WSL  
> （本机无 gcc/clang，C 后端只能验证「生成」不能验证「执行」）。

## 0.0 AI 接力包（记忆注入 · 下个会话先读这一节）

> 这一节是给"接手的 AI"看的：把当前状态、已验证的事实、踩过的坑、不能违反的约定一次写清，
> 避免重新探索、避免重复犯错。**读完这一节再动代码。**

### 身份与坐标

<!-- legacy-ok:begin -->
- 项目：**Quelmara**（旧名 Rosoto，仓库目录仍是 `Rosoto/rosoto/`，改名脚本见 §6）。
<!-- legacy-ok:end -->
- 语言定位：自研系统级语言，**产品后端只允许自研**（x86_64 ELF / PE32+ / AArch64），
  C99 后端只做交叉验证，**永远不是产品链路**。
- 宿主环境：Windows，用户 `43551`；本机只能跑 PE 链；`wsl.exe` 被沙箱拉黑（`[7]` 交叉验证永远 SKIP）；
  本机无 gcc/clang（C 后端只能验证"生成"不能验证"执行"）。
- 解释器：`C:/Users/43551/.workbuddy/binaries/python/envs/default/Scripts/python.exe`
  （系统 Python 也能跑，但依赖装在这个 venv 里）。

### 当前状态（2026-10-21 实测，不是文档抄的）

| 项 | 数字 | 命令 |
|---|---|---|
| PE 回归 | **113 项全绿**（FAIL=0，SKIP=1 WSL） | `python tests/run_win_tests.py` |
| 自举 | **2/9**，1770 / 18909 行 = 8.6% | `python tools/dev/selfhost_status.py` |
| 函数体对拍 | dump 一致 94 / 分叉 636 / SKIP 不同步 25 | `python tests/bodydiff.py` |
| 词法 / 声明 / IR / 发射 | 99/99、90/90（1 跳过）、50/50（19 skip）、10/10 | `tests/lexdiff.py` 等 |
| 三件门禁 | check_names / check_origin / check_docs 全 PASS | `tools/dev/check_*.py` |

### 本轮（v1.8 工作区）新增：语言特性补全

| 特性 | 语义 | 夹具 | 边界 |
|---|---|---|---|
| 整数宽度 `u8..u32/i8..i32` | 边界截断（let/形参/返回值/赋值），表达式内按 C 提升 | `tests/t49_width.qma` | struct 字段存值不截断 |
| `let x: T` | 只有宽度类型参与语义 | 同上 | 不是完整 typeck |
| `@simd` | SSE2 `paddq` 两路归约 + 标量尾 | `tests/t50_simd.qma` | 只认 `acc += a[i]` 的 `[N]int` |
| `@no_preempt` | 抑制编译器插入的 `sched_yield` | 同上 | 不是内核抢占 |
| `rc[T]` | `[refcount][payload]`，`rc_new/clone/get/drop/count` | `tests/t51_rc.qma` | 载荷仅具名 struct |
| 所有权检查 | use-after-drop / double-free / move-then-use | `tests/bad/own_*.qma` | 只查 `rc` 句柄 |
| `interface`/`impl` | 契约 + 校验 + **静态分发** | `tests/t52_iface.qma` | **无动态分发** |

新增 IR 指令：`('trunc', dst, a, bits, signed)`、`('vsum', dst, base, count)`。
**加新 IR 指令的纪律**：必须同时登记到 `qlm_opt.vreg_mentions`、`qlm_native._map_ins`、
`qlm_opt._EFF`（访存类）。漏一处就是"开优化才错"的静默误编译——
本轮 `vsum` 就是这样被调度器挪到数组初始化之前、归约少一个元素的。

### 上一轮（v1.6 工作区）新增

- **P0 标准库六件**：`std/sha256.qma`（SHA-256+HMAC）、`std/str.qma`、`std/url.qma`、
  `std/json.qma`、`std/gzip.qma`（DEFLATE 编码 + gzip）、`std/aes.qma`（AES-128-GCM）；
  回归 `t43`–`t48` + gzip 的 zlib 互操作；HTTP 端已接 `Content-Encoding` 协商。
  说明与实测见 `docs/P0_LIBS.md`。
- **文档门禁** `tools/dev/check_docs.py`（已进 CI 双 job）：拦"过期断言"，强制 README/HANDOVER/SPEC 链接 `docs/GAPS.md`。
- **自举计划** `docs/SELFHOST_PLAN.md`：分 7 阶段、每阶段有门禁与工作量估计。
- 编译器新增调试开关：`QLM_NO_INLINE=1`（关内联）、`QLM_SKIP_PASSES=a,b`（按 pass 跳过）、`QLM_ENABLE_LICM=1`（开 LICM）。

### 三个误编译已在 v1.8 全部修掉（不是"还有洞"）

| # | 症状 | 根因 | 回归 |
|---|---|---|---|
| 1 | 循环内 `substr` 长度来自调用结果 → 越界/错串（`--no-opt` 正常） | 内联路径把栈偏移 `8` 当 `R8` 寄存器号比较，跳过 fetch | `tests/t53_regress.qma` |
| 2 | `"\xNN"`（≥0x80）被当 Unicode 码点再 UTF-8 编码 | 词法器 `chr(b)` + `encode("utf-8")` 二次编码 | 同上 |
| 3 | 一个表达式里两次调用 + 下标 → 结果整体偏移 | 同 #1 | 同上 |

> 曾被怀疑的 `len(f(x))` 段错误**已排除**：真实原因是我把 `mem_load64` 的字节偏移
> 当槽索引，写穿了堆。教训：**随机位置段错误先怀疑自己越界写**，
> 最小化到 30 行内仍复现才算编译器 bug。

含义：**#1/#3 的根因是"栈偏移与寄存器号类型混淆"**，修完之后 b1/b3 两个形状
（循环内调用 + 下标）都不再需要规避写法。LICM 仍默认关闭（`QLM_ENABLE_LICM=1` 可开），
原因是分配器布局敏感的另一条段错误还没根修——那是**下一件事**，不阻塞写业务代码。
### 语言层的"写库须知"（用血换的，写标准库前必读）

- `mem_load64/store64` 的偏移是**槽索引（×8）**，不是字节偏移 —— 按字节偏移写会
  静默写穿堆，崩溃点随机漂移（曾误判成编译器 bug）。
- `vec` 句柄经 `int` 形参/返回值传递会**丢类型标签**（`v.push` 报"不支持方法"）；
  要写成 `vec[int]` 形参/返回类型。
- 方法调用**不能链在函数调用结果上**（`f(x).push(y)` 不支持），先落局部变量。
- 64 位值可能为负，右移要用 `>>>`（`>>` 是算术右移，会灌符号位）—— GHASH 踩过。
- `len()` 只对**带类型标签的本地 vec 变量**可靠；句柄跨函数后要自己记账或用
  `vec[int]` 返回类型。
- `"\xNN"`（≥0x80）现在是**原始字节**（v1.8），可以直接写二进制字面量。

### 文档权威分工（别再写串）

| 文档 | 管什么 |
|---|---|
| `CHANGELOG.md` | 版本特性、修复、回归项数的**历史记录** |
| `docs/STATUS.md` | **当前状态总表**：语言 / 工程化 / 性能 / 平台（唯一"现在到哪了"口径） |
| `docs/GAPS.md` | 能力边界与缺口全表、优先级路线、误编译根因 |
| `docs/LANG.md` | v1.8 新特性的精确语义与边界（宽度 / @simd / rc / 所有权 / interface） |
| `docs/SELFHOST.md` / `SELFHOST_PLAN.md` | 自举进度与阶段门禁 |
| `HANDOVER.md`（本文） | 快照、接力记忆、下一步排期 |

> 规则：任何"支持/不支持"的翻转，**同一次提交**里改 `STATUS.md` + `GAPS.md`，
> 再跑 `tools/dev/check_docs.py`。文档漂移按缺陷算。

### 下一步三件事（按顺序，不要跳）

1. **接口动态分发**：接口值 = `{data, tid}` 两字结构；每个 (interface, method) 生成
   一个派发函数 `if tid == k { call Type__m }`。做完 `let s: Shape = Circle{..}` 才成立。
2. **重开 LICM 并压测**：默认关闭是因为 x64 分配器布局敏感的段错误未根修；
   先补最小复现的回归网，再开 `QLM_ENABLE_LICM=1` 跑全量 + bench。
3. **用户泛型**（`fn f[T]` 单态化）：`vec/option/result/rc` 之外的通用容器与算法。

并行可做（不阻塞上面三条）：`std/gzip` 解码、X25519 + TLS 记录层、
文件系统/时间/随机/排序最小集（`docs/GAPS.md §3.3`）。

### 交接纪律

- 不要 `git reset --hard` / 不要删 `build/` 以外的任何目录；`archive/` 是旧快照。
- 跑完任何改动，至少复跑：`run_win_tests.py` + `parsediff.py` + 三道门禁。
- **新增 IR 指令的检查表**（`docs/STATUS.md §5.2`）：`vreg_mentions`、`_map_ins`、
  `_EFF`（访存类）三处必须同时登记，否则就是"开优化才错"的静默误编译。
- 大改动前先 `git status`：工作区常有大量未提交内容（v1.3–v1.8），别误判。
- 提交粒度：按 `CHANGELOG.md` 的版本节各打一个 commit（v1.3 → v1.5 → v1.6 → v1.8），
  不要攒成一坨。

---

## 0. 当前快照

- **协议库（v1.5 本轮）**：`std/http.qma`（HTTP/1.1）+ `std/ws.qma`（RFC 6455
  WebSocket）+ `std/sse.qma`（SSE）+ `std/net/core.qma`（十万连接槽位层，
  640 B/连接）——全部 Quelmara 自实现，Python 客户端互操作实测全绿。
  TLS（https/wss）路线定稿 `docs/TLS.md`，协议层回调签名已预留 TLS 缝。
- **性能（v1.5）**：性能报告（2026-10-21）七项优化全部落地——str 长度前缀
  ABI（16KB 扫描 85.9ms → 22µs）、2 的幂除法特化、掩码值域 + 越界检查合并、
  8 字节块 memcpy（拼接 3.2×）、内联白名单、展开阈值 1024→8、
  `__realloc` 原地延展。
- **P0 标准库六件（v1.6 本轮）**：sha256（+HMAC）、str（26 函数）、url（14 函数）、
  json（DOM 解析 + builder）、gzip（LZ77 + 固定 Huffman + CRC32，zlib 互操作 7/7）、
  aes（AES-128-GCM，FIPS/NIST 向量全过）。说明与实测见 `docs/P0_LIBS.md`；
  回归 **113 项全绿**。
- **语言能力**：写编译器所需的语法基本齐了 —— `vec[T]`（可增长容器）、  
  `for x in <map|vec>`（可枚举符号表）、`[N]T` 作参数/返回值（按值拷贝 + 隐藏出参，v1.2）；  
  此前 v1.0–v1.1 已补齐 `args()`/`read_text`/`substr`/`chr`、位运算（含 `>>>`）、  
  进制字面量、子切片 `a[lo..hi]`、顶层 `const`、`eprint`/`exit`、字符串字典序。
- **自举进度：2/9 组件**。stage-1 词法器（v1.0）与声明级 parser（v1.3 进行中）均已通过对拍：  
  词法 **92/92** 逐 token 全等、声明级 AST **87/87** 全等、函数体 Phase 1 **dump 一致 94 / 分叉 636**（`tests/bodydiff.py` 实测）、QuIR 架构无关 **50/50**（19 skip：a64 无 chan/map/spawn）、  
  发射层确定性 **10/10**（详见 `docs/SELFHOST.md`）。
- **代码规模**：`tools/stage0/` 18.9k 行 Python（引导层）+ `bootstrap/` **1770 行** Quelmara（自举层，  
  自举占比 **8.6%**，`selfhost_status.py` 实测）+ `tests/` 2.0k 行脚本与 53 个 `.qma` 夹具（`examples/` 16 个）。
- **验证**：Windows PE 回归 **113 项全绿**（本机实测，SKIP=1 因 WSL 被沙箱拦截）；  
  跨平台基线 win + arm64 输出哈希一致（v1.1 起）。

### 版本一句话索引（详情见 `CHANGELOG.md`）

| 版本            | 一句话                                                                   |                                         |
| ------------- | --------------------------------------------------------------------- | --------------------------------------- |
| v0.7          | 用户 Result + `?` 三链打通 + 严格范围证明 + 产品默认自研后端                              |                                         |
| v0.8          | `option[T]` 受控单态化（合成枚举，后端零改动）                                         |                                         |
| v0.9          | `[]T` 切片 + 泛型 `result[T,E]` + modsum 闭环（loop_sum 518ms → 11–13ms）     |                                         |
| v0.10         | `map[K]V` 开放寻址哈希表 + 浮点实际运算（f64/f32）                                   |                                         |
| v0.11         | `h.join()` 方法式 + `chan.close()` + `select`                            |                                         |
| v0.12         | 字符串 `len`/字节下标/`to_int` + `@extern` 收口 + AArch64 CLI 修复               |                                         |
| v1.0          | 改名 Quelmara + 自举前置能力 + **stage-1 词法器**（抓出 `\|\|` 恒真、`let` 别名两个核心 bug） |                                         |
| v1.1          | 位运算/进制字面量/子切片/`const`/字典序 + 跨平台 bench 基线 + 原创性门禁                      |                                         |
| v1.2          | `vec[T]` + \`for x in <map                                            | vec>`+`[N]T\` 作参数/返回值 —— 自举 parser 地基补齐 |
| **v1.3（进行中）** | parser 声明级自举（87/87）→ 下一步：函数体解析、类型推断                                   |                                         |

---

## 1. 语言特性状态（截至 v1.8）

| 特性                                      | 状态                                                       |
| --------------------------------------- | -------------------------------------------------------- |
| `option[T]` 单态化                         | ✅ v0.8 合成枚举 + match 解构（int/bool/str）                     |
| 泛型 `result[T,E]`                        | ✅ v0.9 受控单态化（t20）                                        |
| `[]T` 切片（指针+长度）                         | ✅ v0.9 `slice_of(a)` 零拷贝 + 参数/返回值/别名写入（t21）              |
| `map[K]V`                               | ✅ v0.10 开放寻址 + 墓碑 + 扩容（t22）                              |
| `chan.close()` / `select`               | ✅ v0.11（t25/t26）；无界通道仍 ❌                                 |
| `h.join()` 方法式语法                        | ✅ v0.11 解析期脱糖（t24）                                       |
| `len(str)` / `s[i]` 字节下标 / `s.to_int()` | ✅ v0.12 三链；越界与非法输入 fail-fast（t27/t28）                    |
| `argv` / 命令行参数                          | ✅ v1.0 `args()` / `arg(i)`（Windows 走 GetCommandLineA 拆分） |
| 位运算 `& \| ^ ~ << >> >>>`                | ✅ v1.1 含复合赋值与自定义优先级                                      |
| 顶层 `const`                              | ✅ v1.1 字面量内联（无运行时存储）                                     |
| 进制字面量 `0x/0b/0o`                        | ✅ v1.1 三链                                                |
| 子切片 `a[lo..hi]`                         | ✅ v1.1 str 拷贝 / 切片视图 / 数组视图（三链）                          |
| 字符串字典序 `< <= > >=`                      | ✅ v1.1 修正（此前是指针比较）                                       |
| `eprint` / `exit`                       | ✅ v1.1                                                   |
| `vec[T]` 变长数组                           | ✅ v1.2 push/get/set/pop/len/clear + 2 倍扩容                |
| `for k in m` 遍历 map / `for x in v`      | ✅ v1.2（顺序实现定义，SPEC 写明不要依赖）                               |
| `[N]T` 作参数/返回值                          | ✅ v1.2 值语义拷贝 + 隐藏出参（仅自研后端；C 后端明确拒绝）                      |
| 浮点实际运算                                  | ✅ v0.10 运算/比较/转换/格式化三链打通（t23，f64+f32）                    |
| `vec[Struct]` 聚合元素                      | ✅ v1.3 元素支持标量/struct/enum，按值拷贝进出（t37 实测 `vecagg ok`）；`vec[vec[T]]` 仍 ❌ |
| `import` 模块加载                         | ✅ v1.3 扁平合并（递归 `std/` + 同目录），无命名空间/可见性              |
| str 长度前缀 ABI                         | ✅ v1.5.1 `len`/`s[i]` O(1)（值指向 `[len][bytes][NUL]`）     |
| 真实整数宽度（u8/u32 回绕）                   | ✅ **v1.8** 边界截断（let/形参/返回值/赋值），表达式内按 C 提升（t49）        |
| `let x: T` 类型标注                         | ✅ v1.8（只有宽度类型参与语义，不是完整 typeck）                          |
| `@simd` 归约                              | ✅ **v1.8** SSE2 `paddq` 两路 + 标量尾，仅 `[N]int` 加法归约（t50）    |
| `@no_preempt`                           | ✅ v1.8 抑制编译器插入的 `sched_yield`（t50）                       |
| `rc[T]` 引用计数                          | ✅ **v1.8** `rc_new/clone/get/drop/count`，载荷仅具名 struct（t51）  |
| 所有权 / 借用检查                             | 🟡 **v1.8 只查 `rc[T]`**：use-after-drop / double-free / move-then-use（`tests/bad/own_*`） |
| `interface` / `impl`                    | 🟡 **v1.8 静态分发**：契约 + 校验 + 方法调用；**无 vtable/动态分发**（t52） |
| `std/http` / `std/ws` / `std/sse`      | ✅ v1.5 服务端（keep-alive/流水线、RFC 6455、W3C SSE）；无客户端、无 TLS |
| `@extern("C")`                          | 🟡 C 后端发射原型；自研后端明确拒绝（无动态链接器）                             |
| `qlm_fmt` 新语法覆盖                         | ✅ v1.3 全量冒烟 62/62（token 级重排，新语法零崩溃）        |

## 2. 平台 / 性能 / 工程化缺口

| 项                            | 状态                                      |
| ---------------------------- | --------------------------------------- |
| Windows IOCP/AFD             | ✅ v1.4 `net_serve` + 回调派发（单 acceptor + N 工作线程；未设 SO_REUSEADDR/SO_REUSEPORT）<br>❌ `net.TcpServer` 结构体模型未进 Windows PE |
| 自研 Linux epoll 网络            | ❌ native 后端尚无网络 intrinsic；`net_serve` 仅 Windows（Linux 侧仍只有 C 后端 epoll/io_uring demo） |
| macOS/iOS Mach-O + kqueue    | ❌ 需 Mac 真机/CI                           |
| Android / wasm64             | ❌                                       |
| AArch64 spawn/chan           | ❌ 需要 `ldaxr/stxr` 原子发射层                 |
| SIMD 自动向量化                   | ❌ 与 gcc -O2 的主要差距（v0.9 后 modsum 类负载已反超） |
| 尾调用消除 / LTO / 热重载            | ❌                                       |
| Windows PE 调试信息 / SEH unwind | ❌                                       |
| `quelmara test --target all` | ✅ v1.3 `--targets all` 多后端矩阵（arm64 模拟器执行级 + 输出比对） |
| Linux/Windows CI             | ✅ v1.3 `.github/workflows/ci.yml` 双平台矩阵               |
| Windows C 后端执行验证             | ❌ 本机无 gcc/clang                         |

## 3. 还差什么

1. **Mac/ARM64 机器或 CI**：macOS Mach-O/kqueue 与 AArch64 真机验证缺硬件。
2. **Windows C 工具链**：本机无 gcc/clang，C 后端只能验证「生成」不能验证「执行」  
   （已验证 `gcc`/`clang`/`tcc`/MSVC 均不可用于 GNU C + POSIX 头）。
3. **IOCP 压测环境**：需要 Windows 句柄上限、防火墙配置和压测客户端。
4. **SIMD 基线环境**：需要固定 CPU、固定构建参数和 baseline 文件，避免把机器负载误判成优化收益。

## 4. 下一步要写什么

0. **接口动态分发（最高优先）**：接口值 = `{data, tid}`，每个 (interface, method)
   生成派发函数。做完 `let s: Shape = Circle{..}` / `vec[Shape]` 才成立。
   细节见 `docs/GAPS.md §2`、`docs/LANG.md §7.3`。
0.1 **重开 LICM 并压测**：先补最小复现回归网，再开 `QLM_ENABLE_LICM=1` 跑全量 + bench。
0.2 **TLS Phase A 收尾**：X25519 需要 255 位域算术——先做 `std/u128.qma`
   （limb 加减乘/比较），再做 GF(2^255-19)；之后才是记录层/握手/X.509（Phase B）。
   同时补 gzip 解码（inflate）与文件系统/时间最小集（需编译器内建）。
1. **TLS Phase A 已完成 2/3**：`std/sha256.qma`（SHA-256+HMAC，FIPS/RFC 全过）、
   `std/aes.qma`（AES-128-GCM，FIPS-197 / NIST case 2-3 全过）。
   剩 `std/ecdh.qma`（X25519）——需要先有 255 位域算术（`std/u128` limb 层）。
   详见 `docs/TLS.md`。
2. **协议库回归入 CI**：http/ws/sse 的 Python 客户端互操作脚本
   （本会话已验证的用例）固化为 `tests/netlibs_test.py`。
3. **parser 函数体自举**（v1.3 主线）：在 `bootstrap/parser/qlm_parse.qma` 上扩展，  
   对拍口径 = AST 节点逐层比对（`tests/parsediff.py` 扩展）。
4. **类型推断自举**（`bootstrap/typeck/`）：负向夹具体检 —— 两阶段必须报错且类别一致。
5. **动态长度检查消除**（`opt_bounds_elim` 下半场）：切片/str/vec 窗口接入
   （跨块 CSE 合并 len load）。注意 v1.5.1 长度前缀 ABI 后 `len(s)` 已是
   O(1) load，此条收益重估后再排。
6. **SIMD 自动向量化**：`@simd` 已有单形状手写路径（v1.8），下一步推广到切片/`vec`/浮点，再谈自动识别。
7. **macOS Mach-O + kqueue**：有 Mac runner 后落地。
8. **`__map_grow` 旧表回收**：map rehash 仍走 bump（vec 已用 realloc），
   大 map 场景的内存峰值待测。

## 5. 怎么接着干

```bash
# Windows（本机可跑）
python tests/run_win_tests.py           # PE 回归（v1.2 时点 91 项）
python tests/lexdiff.py                 # 词法对拍 92/92
python tests/parsediff.py               # 声明级对拍 87/87
python tests/irdiff.py                  # QuIR 架构无关 50/50
python tests/emitdiff.py                # 发射层确定性 10/10
python tools/dev/check_docs.py          # 文档漂移门禁（过期断言 / GAPS 链接）
python tools/dev/selfhost_status.py     # 自举进度（2/9）

# Linux（需 gcc / 自研 ELF 环境）
bash tests/run_native_tests.sh
bash tests/run_tests.sh
bash tests/test_corelib.sh
bash tests/test_uring.sh

# 单版本验证示例
python tools/stage0/qlm_cli.py run tests/t34_vec.qma --target win
python tools/stage0/qlm_cli.py bench examples/loop_sum.qma --target win --runs 5

# 调试/IR
python tools/stage0/qlm_pe.py build tests/t17_result.qma -o build/x.exe --dump-ir --no-opt
```

### 新增 IR/优化改动检查表

1. `vreg_mentions`
2. `_subst_vregs`
3. `_map_ins`
4. `PURE`
5. `_EFF`
6. `_LAT` / `_TERM`
7. `allocate.call_sites`
8. x86/Windows `gen_instr`
9. AArch64 `gen_instr`（若跨架构）

### 累计教训

- Result 的 `Ok` tag 不能硬编码为 0，必须按 enum 声明顺序查索引。
- Result `?` 目前只接受两个单载荷变体和标量 Ok payload，超出边界必须报错。
- 非负范围证明必须检查唯一初始化、唯一步进定义、上界和溢出；不能跨控制流读取旧常量。
- worker 是独立栈/寄存器压力边界，不能盲目内联。
- 内联标签必须带 caller 名字，否则跨函数同名会把跳转导入错误函数。
- C helper 只能引用 helper 形参，不能引用调用点局部变量名。
- **`bin` 指令不能用 `sub dst, imm, dst` 模拟取反**：dst 与 rhs 同 vreg 时，  
  分配器先写 dst 再读 rhs，结果恒为 0。取反一律走专用 `neg` 指令。
- **无函数体的声明必须带 `@extern`**：`body=None` 直接漏进 lowering 会变成  
  Python traceback（用户看到的是解释器堆栈而不是编译错误）。后端入口要显式拦截。
- **str 曾是无长度前缀的零结尾串**（v1.5.1 已改为长度前缀 ABI）：`len(s)`、`s[i]` 现为 O(1)
  （str 值指向 `[len][字节][NUL]`）。但所有直接拿 str 当裸指针传给
  `mem_load8/mem_store8` 的代码要知道数据在 ptr+8 起——`tcp_send_n(fd, s, n)`
  这类"str 当 ptr"的调用点必须走库层封装（`conn_send_str` 内部已换算）。
- **`||` 与 `&&` 的短路落空值必须分开处理**（v1.0 自举词法器抓出）：  
  两者共用「落空即 true」的尾巴会让 `0 || 0 == true`。
- **`let` 必须拷贝而不是别名**（v1.0）：`let mut j = i` 若直接共享 vreg，
  改 `j` 会连带改 `i`，值语义被破坏；标量一律拷贝到新 vreg 并传播全部类型标签。
- **范围分析的循环识别必须覆盖两种 guard 条件码**：for 形态 `jcc ge i, hi, End`
  （真则退出）与 while 形态 `jcc l i, hi, Body`（真则进体）语义同为
  "body 在 `i < hi` 下执行"——只认一种会让另一形态的全部循环丢失证明
  （for 循环的魔数除法收缩曾因此从未生效）。
- **循环级归纳变量证明是局部的**：init 紧邻可追溯 >= 0、step 唯一 > 0、
  body 无重定义、窗口在 body 区间内——不需要 ivar 全函数唯一定义；
  用全局 def 唯一性当门槛会把"多个循环共享 i"的常见形态全部挡掉。
- **实验配置会污染实验**：`find_config` 从源文件目录向上查找，实验目录里
  放一份 `bounds_check=false` 的配置会让同目录的负向用例窗口根本不生成——
  差点误判成"优化过度消除"。做对照实验先确认每个源文件命中哪份配置。
- **Win64 API 的 int 返回值高位不可靠**：SOCKET_ERROR 落在 rax 是
  0x00000000FFFFFFFF（0 扩展）而非 64 位 -1，与 -1 直接比较会漏检——
  用 shl32+sar32 符号扩展后再比（tcp_listen 的 bind/listen 曾因此被放过）。
- **winapi 函数的 DLL 归属必须跟着内建走**：WSAGetLastError 被漏归
  kernel32 → 0xC0000139 ENTRYPOINT_NOT_FOUND，进程起不来；WSA* 前缀
  一律 ws2_32。
- **sockaddr_in 的 w0 = family | (htons(port)<<16)**：曾写成
  hp3 | (2<<16)——family 落到字节 2-3，bind 报 10047 EAFNOSUPPORT。
  反汇编（capstone）一锤定音；纸面推演 IR 语义永远有盲区。
- **store/load 的 off 是槽索引（×8）不是字节偏移**：slice 头
  `store s, imm 0/1` 是字节 0-7/8-15；写 imm 8 会落到 [base+64] 越界全局区。

---

## 6. 版本控制 / 远端

<!-- legacy-ok:begin -->
- **git remote**：`origin = https://github.com/MonthZifang/Rosoto`（待改名为 `Quelmara`，
  **截至 2026-10-20 尚未执行**，remote 实测仍为旧地址）。
- 工作区为单一文件夹：`Rosoto/rosoto/`（git 仓库）。

### 目录改名（需要用户手动执行）

当前会话把仓库目录作为工作目录，操作系统会拒绝改名（`Permission denied`）。  
**关闭当前会话后**在 `C://Users//43551//Desktop` 执行：

```bash
mv Rosoto/rosoto Rosoto/quelmara     # 内层仓库目录
mv Rosoto Quelmara                   # 外层目录
```

然后在 `C://Users//43551//Desktop//Quelmara//quelmara` 重新打开项目；  
`.workbuddy/memory` 会随外层目录一起搬走。

### GitHub 仓库改名（需要用户手动执行）

1. 打开 `https://github.com/MonthZifang/Rosoto/settings` → Repository name → 改为 `Quelmara` → Rename。
2. 本地更新 remote 并推送：
   ```bash
   git remote set-url origin https://github.com/MonthZifang/Quelmara
   git push origin master
   ```
3. 旧地址会自动 301 重定向，但建议同步更新文档里的 URL（`README.md` / `TUTORIAL.md`）。

### 远端脚本

`C://Users//43551//Desktop//Rosoto//push.sh` 已改为从环境变量读密码（不再明文），
并支持 `QM_REMOTE` / `QM_LOCAL` 覆盖路径，目录改名后不必改脚本。
<!-- legacy-ok:end -->

---

## 7. 提交线（最近）

```
6ef52ae  docs: SELFHOST 状态表更新（parser 前置能力已齐，仍缺 vec[Struct]）
28f7df9  fix(v1.2): C 后端 vec 的类型串与局部声明
335d23f  feat(v1.2): vec[T] / for-in 集合遍历 / [N]T 作参数与返回值
1a3122d  feat(v1.1): 位运算/进制字面量/子切片/const/字典序/eprint/exit + 基线 + 门禁
ebfe9f9  fix: C 后端 qlm_args 废弃符号；文档历史叙述加 legacy-ok 标注
026be71  feat(v1.0/D): 自举词法器 + || / let 两个核心语义 bug 修复
…（更早见 git log / CHANGELOG）
```

> 工作区当前有 v1.3 未提交内容：`bootstrap/parser/`、`tests/parsediff.py` /  
> `irdiff.py` / `emitdiff.py`、`tools/dev/astdecl.py`、`tests/t37_vecagg.qma` 等。  
> 各轮次的逐文件变更明细不再在本文维护，用 `git show --stat <hash>` 查。
