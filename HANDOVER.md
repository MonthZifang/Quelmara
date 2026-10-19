# Rosoto 交接文档（HANDOVER）

> 本轮：**v0.3 平台轮 —— 自研 Windows x86_64 PE/COFF 后端（无 CRT）**
> 交接时间：2026-10-19（GMT+8）
> 状态：**152 项回归全绿**（Windows 41 / 自研 Linux 35 / C 16 / corelib 34 / io_uring 26）
> 代码总量：`tools/` 11.1k 行 Python + `tests/` 1.3k 行（脚本/测试/模拟器）

---

## 0. 一句话结论

Rosoto 现在有**四个可交叉验证的后端**：Linux x86_64 裸 ELF、**Windows x86_64 PE/COFF（本轮新增，无 CRT）**、
Linux AArch64 ELF（模拟器执行级）、C99 中转。同一份 `.ros` 在 Windows 上可直接双击运行，
hello 产物 **6144 字节**，多核 `parfor` 走 `CreateThread`，输出与 Linux 自研后端逐字节一致。

> ⚠️ 上一版 HANDOVER 说「`enum`/`match` 未实现」是**文档滞后**：parser/C/自研后端里早已实现并有
> `tests/t12.ros` 覆盖。本轮已核对并同步文档（`SPEC.md` / `README.md`）。

---

## 1. 这一轮做了什么

### 1.1 自研 Windows 后端（`tools/rosoto_pe.py`，353 行）

| 层 | 实现 |
|---|---|
| 前端 / IR / 优化 / 寄存器分配 | **完全复用** `rosoto.py` / `rosoto_native.py` / `rosoto_opt.py`，零分叉 |
| 平台抽象 | `Lower(platform="windows")` 新增 `emit_write / emit_exit / emit_alloc` 三个薄 helper；Linux 走 raw syscall，Windows 走 `winapi` IR 指令 |
| Win64 调用 | `winapi` → `call qword ptr [rip+IAT]`；RCX/RDX/R8/R9 传参，32B shadow space，第 5/6 参落 `[rsp+32]/[rsp+40]` |
| PE/COFF 写出 | DOS + PE32+ + 4 节（`.text`/`.data`/`.rdata`/`.reloc`）；导入表（ILT/IAT/hint-name/kernel32）；DIR64 基址重定位（ASLR 安全） |
| 运行库 | print/itoa/str_concat/str_eq/assert/heap 全部复用 RosIR 自举，只换 I/O 原语 |
| 内存 | `VirtualAlloc(MEM_RESERVE)` + **1MB 粒度 MEM_COMMIT**；`heap_limit_mb` 仍 fail-fast |
| 多核 | `CreateThread` + 全局参数槽 + 共享归约 + `WaitForSingleObject` + `CloseHandle` |
| 入口 | `and rsp,-16` → `call main` → `ExitProcess(rax)`；无 CRT、无全局构造、无解释器 |
| 工具链 | `rosoto build/run/test --target win`；Windows 上 `rosoto test` 默认走 win 后端 |

**导入只有 7 个 kernel32 API**：`GetStdHandle / WriteFile / ExitProcess / VirtualAlloc /
CreateThread / WaitForSingleObject / CloseHandle`。不链 msvcrt、不链 ucrt、不依赖 vcruntime。

### 1.2 新增回归：`tests/run_win_tests.py`（41 项）

- PE 结构：MZ/PE32+/AMD64/console 子系统、入口在 `.text`、导入仅 kernel32、无 CRT 符号、体积上限
- 执行语义：hello、fib、loop_sum、大整数、UTF-8 中文、`assert` 失败路径（退出码 1 + stderr）
- 语言特性：t8（break/continue）、t9（struct 值语义）、t11（嵌套布局）、t12（enum+match）
- 多核：parfor_sum（20 线程归约）、prime_parallel、game_loop、t10（struct×parfor 共存）
- 单核降级：临时工程 `Rosoto.toml [core] multicore=false`，结果不变
- 交叉验证：Windows PE 与 Linux 自研 ELF 输出**逐字节**比对（divmod/t8/t9/t11/t12/inventory/collatz/game_loop）

### 1.3 本轮抓到的 4 个真实缺陷（全部有回归）

| # | 症状 | 根因 | 修复 |
|---|---|---|---|
| 1 | 一运行就 `0xC0000096`（特权指令） | PE 头 `SizeOfHeaders` 少算 section header（`0x80+4+20+240`，漏 `40*n`），`.text` RawData 覆盖了节表 | `headers_size` 计入 `40*nsec` |
| 2 | 修完变 `0xC0000005`（访问冲突），入口第一条指令被改 | `.reloc` 奇数补齐用了 `(10<<12)|0`，等于「在页首做 DIR64」，把入口 8 字节加了加载偏移 | 补齐项必须是裸 `0x0000` 哨兵 |
| 3 | 多核线程启动即崩 | `ThreadProc(lpParameter)` 参数在 **RCX**（Win64），代码按 RDI 取；且 RDI/RSI 在 Win64 是 callee-saved，未保存 | 新增 `winargs` IR + `win_thread` 序言/尾声保存 RDI/RSI |
| 4 | 多核结果静默变 0 / 字符串拼接打印空行 | 优化器不认识新 IR：复制传播漏替换 `winapi` 操作数；调度器没把 `winapi` 当副作用屏障，`WaitForSingleObject` 被排到归约读取之后 | `_subst_vregs` 加 `winapi/winargs`；`_EFF`/`_LAT`/`_TERM` 加 `winapi`/`winargs` |

### 1.4 文档同步与新文档

- 新增 **`PLATFORM.md`**：全平台矩阵、移植成本模型、Windows 网络（IOCP/AFD）、macOS、wasm 的方案与取舍，以及需要你拍板的 3 个问题。
- `README.md` / `SPEC.md` / `BACKEND.md` 全部更新到 v0.3（四后端、152 项、Windows 实测）。
- 修正上一版交接文档关于 `enum`/`match` 的过时描述。

---

## 2. 还没有做什么（未完成清单）

### 2.1 语言特性（SPEC 已写、编译器未实现）

| 特性 | SPEC 出处 | 现状 | 优先级 |
|---|---|---|---|
| `option[T]` / `result[T,E]` + `?` 传播 | §2 / §3 | ❌ `?` 仅 C 后端有 int 占位；自研后端直接报错 | **高** |
| `arena { ... }` 帧级分配 | §2 / §6 | ❌ 运行时 `rosoto_mem.py` 已写好，缺语法与降级 | 高 |
| `spawn` / `join` / `chan[T]` | §4 | ❌ 运行时 `rosoto_mt.py` 已写好，缺语法与降级 | 高 |
| `map[K]V`、`[N]T`、`[]T` 运算 | §2 | ❌ 只有类型语法占位 | 高 |
| 泛型 / `interface` | §2 | ❌ 未实现 | 中 |
| 所有权 + 借用检查（`&T` / `&mut T`） | §2 | ❌ 未实现 | 中 |
| `@simd` / `@no_preempt` / `@rc[T]` / `@extern("C")` / `@import_c` | §2/§4/§6 | ❌ 未实现 | 中 |
| `rosoto_fmt` 适配 `struct`/`enum`/`match` | §8 | ❌ 格式化器未覆盖这些新语法 | 低 |
| 浮点类型实际运算（f32/f64） | §2 | 🟡 类型名可解析，运算/打印未打通 | 中 |

### 2.2 平台 / 性能

| 项 | 现状 |
|---|---|
| **Windows 网络（IOCP/AFD）** | ❌ `net.TcpServer` 在 Windows 上不可用 —— 这是 Windows 格的最大缺口 |
| macOS/iOS（Mach-O + kqueue） | ❌ 未做；需 Mac 真机/CI |
| Android（aarch64 + epoll） | ❌ 未做 |
| Web（wasm64） | ❌ 未做 |
| AArch64 真机验证 | 🟡 只有自研模拟器执行级；需 aarch64 主机或 qemu-user |
| SIMD 自动向量化（SSE2→AVX2） | ❌ 未做（loop_sum 与 gcc -O2 的主要差距） |
| 尾调用消除 / LTO / 热重载 | ❌ 未做 |
| Windows PE 调试信息 / SEH unwind | ❌ 未做（崩溃只有异常地址，无符号/栈回溯） |

### 2.3 工程化

| 项 | 现状 |
|---|---|
| `rosoto test --target all` 一次跑四后端 | ❌ 目前要分别指定 target |
| `rosoto bench` 基线对比 | 🟡 有壳，未建立跨平台基线文件 |
| CI（Linux/Windows 双矩阵） | ❌ 未接 |
| Windows 上 C 后端验证 | ❌ 本机无 gcc/clang；C 后端 16 项在 WSL 里跑 |
| 文本编码 | ✅ 已修：`rosoto test` 在 GBK 控制台不再抛 UnicodeError |

---

## 3. 差什么（阻塞项 / 需要的输入）

1. **真正的 git 远端**：本目录此前**不是 git 仓库**（`git status` 报 not a repository）。
   本轮已 `git init` + 提交（见 §7）。要推送到 GitHub/Gitee/自建远端，需要你给 **remote URL**
   （或在本机执行 `git remote add origin <URL> && git push -u origin master`）。
   在此之前，「推送」只能体现为**更新本目录 + 本地提交历史**。
2. **macOS / ARM64 真机或 CI**：Mach-O/kqueue 与 AArch64 ELF 的执行级验证都缺硬件。
   可选：GitHub Actions `macos-latest` / `ubuntu-24.04-arm`（需要仓库与网络）。
3. **Windows 无 gcc/clang**：C 后端只能靠 WSL 验证；如果要做「Windows 上 C 后端」，
   需要装 MSVC Build Tools 或 zig/llvm-mingw。
4. **Windows 网络实测环境**：IOCP/AFD 实现后，百万连接测试需要调大句柄上限、
   关闭防火墙干扰、准备压测客户端（现有 `tests/test_uring.sh` 的 20/32MB 场景可复用思路）。
5. **产品级平台优先级**：见 `PLATFORM.md §5`，需要你选下一格（Windows 网络 / macOS / wasm）。

---

## 4. 写了多少（本轮产出统计）

| 类别 | 文件 | 行数 | 说明 |
|---|---|---|---|
| **新增** Windows 后端 | `tools/rosoto_pe.py` | 353 | PE32+/COFF 写出器 + WinCodegen + winapi/winargs |
| 平台抽象 / IR | `tools/rosoto_native.py` | 2551（+158） | `platform` 参数、emit_write/exit/alloc、winapi/winargs、win_thread 序言、`fnaddr` 重定位 |
| 优化器 | `tools/rosoto_opt.py` | 898（+12） | `winapi/winargs` 的 def/use、复制传播、调度屏障、latency |
| 命令行 | `tools/rosoto_cli.py` | 315（+27） | `--target win`、Windows 默认 target、UTF-8 输出修复 |
| **新增** Windows 回归 | `tests/run_win_tests.py` | 294 | 41 项（结构/执行/多核/降级/assert/交叉验证） |
| 新测试夹具 | `tests/win_assert.ros`、`tests/win_utf8.ros` | 20 | 失败路径 + UTF-8 |
| **新增** 平台文档 | `PLATFORM.md` | 159 | 矩阵、成本模型、方案对比、待拍板问题 |
| 文档更新 | `README.md` / `SPEC.md` / `BACKEND.md` / `HANDOVER.md` | 157+341+183+本文件 | v0.3 同步 |
| 调试工具 | `tools/rosoto_dbg.py` | 147 | 极简 Windows 调试器（模块基址/线程/异常地址/内存 dump） |

**测试规模**：152 项（Windows 41 / 自研 Linux 35 / C 16 / corelib 34 / io_uring 26），全绿。
**交叉验证**：Windows PE × Linux ELF 8 个用例逐字节一致（CPU 核数相关输出除外）。

---

## 5. 需要写什么（下一轮建议，按性价比排序）

1. **Windows IOCP/AFD 网络**（`PLATFORM.md` 候选 A）
   - 先做 **IOCP + winsock2 导入**：`WSAStartup/WSASocketW/bind/listen/AcceptEx/WSARecv/WSASend/
     CreateIoCompletionPort/GetQueuedCompletionStatus`。
   - 复用 `Rosoto.toml [net]` 的 max_conns / buffer / backpressure；补 Windows 版 echo 压测。
   - 这是把 Windows 从「半格」补成「整格」的关键。
2. **SIMD 自动向量化**（性能主线）
   - 先在 RosIR 识别「归约型 for 循环」，发 SSE2 `paddq`（2×i64）或 AVX2（4×i64）；
   - 加 `@simd` 显式提示；用 `loop_sum` 做基线，目标接近 gcc -O2。
   - 注意：Windows PE 与 Linux ELF 共用同一发射层，向量化只写一次。
3. **`arena { }` 语法接入**（最便宜）
   - 运行时 `tools/rosoto_mem.py` 已有 bump/arena；只差 parser 块、Lower 降级、C 后端映射。
4. **`spawn` / `join` / `chan[T]`**
   - Linux 可复用 clone + futex；Windows 用 CreateThread + 条件变量/`WaitOnAddress`；
   - `Rosoto.toml multicore=false` 时降级为直接调用/同步队列。
5. **`option` / `result` + `?`**
   - 先定内存布局（tag + payload，复用 enum 槽位模型），再改三处 lower；
   - 这是 SPEC §3 的核心承诺。
6. **macOS Mach-O + kqueue**（有 Mac 资源再做）
7. **工程化**：`rosoto test --target all`、CI 双矩阵、bench 基线。

---

## 6. 怎么接着干（开工步骤）

```bash
# 0. 本机依赖（Windows）
#    - Python 3.11+（本机 3.14）
#    - 如需跑 C 后端/io_uring 回归：WSL Ubuntu + gcc（本机已装 libc6-dev）

# 1. 全量回归（152 项）
bash tests/run_native_tests.sh      # 33（WSL/Linux）
bash tests/run_tests.sh             # 16（需 cc）
bash tests/test_corelib.sh          # 34
bash tests/test_uring.sh            # 26
python tests/run_win_tests.py       # 40（Windows 原生）

# 2. Windows 单文件
python tools/rosoto_cli.py run examples/hello.ros --target win
python tools/rosoto_pe.py build examples/parfor_sum.ros -o build/p.exe
python tools/rosoto_pe.py run   examples/game_loop.ros

# 3. 看 IR（调编译器必用）
python tools/rosoto_pe.py build tests/t12.ros -o build/x.exe --dump-ir --no-opt
python3 tools/rosoto_native.py build tests/t11.ros -o /dev/null --dump-ir --no-opt

# 4. 排查 Windows 崩溃（本轮新写的调试器）
python tools/rosoto_dbg.py build/hello.exe      # 打印 image base / 线程入口 / 异常 RVA
```

### 改编译器时的硬性检查表（新增 IR 指令 = 改 8 处，漏一处就是隐性错编）

1. `tools/rosoto_native.py::_map_ins`（内联重命名）
2. `tools/rosoto_opt.py::vreg_mentions`（def/use）
3. `tools/rosoto_opt.py::_subst_vregs`（复制传播替换）
4. `tools/rosoto_opt.py::PURE`（能否被 DCE/CSE/LICM）
5. `tools/rosoto_opt.py::_EFF`（副作用/访存保序）
6. `tools/rosoto_opt.py::_LAT` + `_TERM`（调度延迟/基本块终止）
7. `tools/rosoto_native.py::allocate` 的 `call_sites`（是否破坏调用者保存寄存器）
8. 发射层：x86_64 `gen_instr` + AArch64 `gen_instr`（+ Windows 的 `WinCodegen.gen_instr`）

### 其他血泪教训（务必先读）

- **PE `headers_size` 必须含节表**（`0x80+4+20+240+40*n`）；否则 `.text` 覆盖节头 → `0xC0000096`。
- **`.reloc` 补齐项必须是 0x0000**；写成 `(10<<12)|0` 会在页首做一次 DIR64，改掉入口字节。
- **Win64 线程入口参数在 RCX**，且 RDI/RSI 是 callee-saved；用 `winargs` + `win_thread`。
- **`winapi` 必须进 `_EFF`**：否则 `WaitForSingleObject` 会被调度到归约读取之后，多核结果静默变 0。
- **`winapi` 栈参数先写、再搬寄存器实参**，否则第 5/6 参的来源寄存器可能被 RCX/RDX 覆盖。
- **Windows 堆按 1MB MEM_COMMIT**；`MEM_RESERVE` 只占虚拟地址，别一次性 commit 512MB。
- **IAT 所在节要可写**（本轮 `.rdata` 用 RW）；加载器需要回填函数地址。
- **`cores()` 是编译期常量**：跨平台输出比对时要排除（Windows=物理核，WSL=4）。
- **parfor worker 永不内联**（`no_inline`）；帧槽字序号递增方向必须与 `base+idx*8` 一致。
- **RosIR 非 SSA**：任何 pass 都要对「vreg 多次定义」保守处理。

---

## 7. 远端同步 / 版本控制

- 本目录此前**没有 git 仓库**。本轮已：
  - `git init`（默认分支 `master`）
  - 新增 `.gitignore`（忽略 `build/`、`__pycache__`、`.openclaw/`）
  - 首次提交：`v0.3: Windows x86_64 PE/COFF backend (no CRT), 152 tests green`
- **尚未推送到网络远端**（没有配置 remote）。两种方式二选一：
  ```bash
  # A. 你给 URL，我来推
  git remote add origin <URL>
  git push -u origin master
  # B. 如果远端仓库已有内容，先 pull --rebase 再 push
  ```
- 若你的「远程端目录」就是指这台机器的 `C:\Users\43551\Desktop\Rosoto\rosoto`：
  本轮所有文件已直接写入该目录，**目录即最新源码**。

---

## 8. 本轮改动的文件清单（供 diff/回滚）

```
新增：
  tools/rosoto_pe.py          Windows PE/COFF 后端（353 行）
  tools/rosoto_dbg.py         Windows 极简调试器（147 行）
  tests/run_win_tests.py      Windows 回归（294 行，41 项）
  tests/win_assert.ros        assert 失败路径夹具
  tests/win_utf8.ros          UTF-8 输出夹具
  PLATFORM.md                 全平台矩阵与讨论

修改：
  tools/rosoto_native.py      platform 抽象 / winapi / winargs / win_thread / fnaddr
  tools/rosoto_opt.py         新 IR 指令的 def-use / 复制传播 / 调度屏障
  tools/rosoto_cli.py         --target win / Windows 默认 target / UTF-8 输出
  README.md / SPEC.md / BACKEND.md / HANDOVER.md   文档同步到 v0.3

测试：
  Windows 41 ✅  |  自研 Linux 35 ✅  |  C 16 ✅  |  corelib 34 ✅  |  io_uring 26 ✅
```
