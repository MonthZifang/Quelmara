# Rosoto 全平台路线（PLATFORM.md）

> 结论先说：**「全平台」不是一句口号，而是一张可逐格填满的矩阵**。
> 每一格 = 指令发射层 + 可执行格式写出器 + 系统 ABI/运行时 + IO 后端。
> RosIR、优化 passes、寄存器分配、前端 100% 复用 —— 这是移植成本能压住的原因。
>
> 本轮（v0.3）填上了 **Windows x86_64（PE/COFF，无 CRT）**：计算、字符串、结构体/枚举、
> 多核 `parfor` 全部可用，产物 6–26 KB，冷启动即 `main`。**网络（IOCP/AFD）尚未接入**。

---

## 1. 当前矩阵

| 目标 | 可执行格式 | 指令发射 | 系统 ABI | IO 后端 | 状态 |
|---|---|---|---|---|---|
| Linux x86_64 | ELF64（裸，无 libc） | 自研 x86_64 | raw syscall | epoll（C 后端 + io_uring 运行时） | ✅ v0.1 |
| **Windows x86_64** | **PE32+ / COFF** | 自研 x86_64（复用） | **kernel32 导入** | ❌ IOCP 未接 | ✅ v0.3（本机实测） |
| Linux aarch64 | ELF64 | 自研 AArch64 | raw syscall | epoll | 🟡 模拟器执行级验证，缺真机 |
| macOS / iOS arm64 | Mach-O | 自研 AArch64（复用） | libSystem 导入 | kqueue | ⛔ 未做 |
| Android arm64 | ELF64 | 自研 AArch64 | raw syscall | epoll | ⛔ 未做 |
| Web (wasm64) | .wasm | RosIR → wasm | WASI | 浏览器 fetch/WebSocket | ⛔ 未做 |
| 主机（PS/Xbox/Switch） | 各家格式 | 自研 x86/ARM | 平台 SDK | 平台网络栈 | ⛔ 需 NDA/法务 |

图例：✅ 执行级通过；🟡 部分验证；⛔ 未开始。

---

## 2. Windows 这一格做了什么（v0.3）

```
.ros ──Parser──▶ AST ──Lower(platform="windows")──▶ RosIR
                                                   │
                    优化 passes（与 Linux 完全相同）│ 内联/CSE/LICM/展开/调度/DCE
                                                   ▼
                     线性扫描寄存器分配（9 寄存器池，同一套）
                                                   ▼
                    自研 x86_64 编码器（同一套指令编码）
                                                   ▼
        WinCodegen：winapi 指令 → call [rip+IAT]（Win64 ABI + shadow space）
                                                   ▼
        PE 写出器：DOS/PE32+ 头 + .text/.data/.rdata/.reloc + kernel32 导入表
```

- **无 CRT**：入口就是自研机器码，`main` 返回后直接 `ExitProcess`。不链 msvcrt、不跑全局构造。
- **导入仅 kernel32**：`GetStdHandle / WriteFile / ExitProcess / VirtualAlloc /
  CreateThread / WaitForSingleObject / CloseHandle`。
- **ASLR 安全**：所有绝对地址（字符串/全局/线程入口）都进 `.reloc`（DIR64），
  加载基址随机化后仍然正确。
- **省用**：堆先 `MEM_RESERVE` 512MB 虚拟地址，按 **1MB 粒度 MEM_COMMIT**，
  只有真正写到才占提交配额；`heap_limit_mb` 仍是 fail-fast 硬上限。
- **多核**：`CreateThread` + 共享内存归约，和 Linux 的 `clone()` 语义一致；
  `Rosoto.toml [core] multicore=false` 时编译期降级为串行，结果不变。

### 实测（本机 Windows 10/11 x64，20 逻辑核）

| 负载 | PE 后端 | 说明 |
|---|---|---|
| hello（字符串 + 循环） | 6144 B | 冷启动直入 main，无 CRT 初始化 |
| fib(25) | 6656 B | 递归 |
| loop_sum 2 亿热循环 | 6144 B / 357.9 ms（5 次最优） | 与 Linux 自研后端同一套优化 |
| parfor_sum 20 线程 6M 任务 | 14848 B / 196.1 ms | CreateThread + 归约 |
| prime_parallel（10 万以内素数） | 15872 B | 自校验通过 |
| 游戏示例 game_loop | 20480 B | 嵌套结构体 + 帧循环 + parfor |

> Windows 上没有 gcc/clang，所以「PE vs gcc -O2」无法在本机对比；
> Linux 侧的 C 后端基线仍由 WSL 跑（见 BACKEND.md §5）。

---

## 3. 「全平台」的移植成本模型

**共享部分（约 90% 代码）**：Parser / 类型检查 / RosIR / 优化 passes / 寄存器分配 /
诊断信息 / 测试框架。新增平台**不碰**这些。

**每平台新增部分（约 10%）**：

| 组件 | 规模 | 说明 |
|---|---|---|
| 指令发射层 | 0–1500 行 | x86_64 平台可完全复用；换架构才重写（AArch64 已 570 行） |
| 可执行格式写出器 | 150–350 行 | PE 332 行；ELF 15 行；Mach-O 预计 ~300 行 |
| ABI / 系统调用层 | 100–250 行 | Linux raw syscall ↔ Windows kernel32 ↔ macOS libSystem |
| IO 后端 | 400–1200 行 | epoll / io_uring / IOCP / kqueue / WASI 各自的事件循环 |
| 平台测试夹具 | 100–200 行 | 结构自检 + 执行级回归 + 与 Linux 交叉验证 |

**判断**：Windows 这一格花了约 1 个编译器模块的量（353 行 PE + 平台 helper + 54 项回归），
验证了「换平台 ≈ 换壳」的假设。剩下每一格的边际成本会继续下降。

---

## 4. 下一格怎么选（需要一起定）

### 候选 A：Windows 网络（IOCP / AFD）——**推荐优先级 P0**

理由：Windows 已经是可用后端，但 `net.TcpServer` 还不能在 Windows 上跑；
「网络原生」是语言的四条主线之一，缺了它 Windows 格只能算半格。

实现路径（两条，建议先 B 后 A）：

1. **B：IOCP + winsock2 导入**（正统、文档全）
   - 导入 `WSAStartup / WSASocketW / bind / listen / AcceptEx / WSARecv / WSASend /
     CreateIoCompletionPort / GetQueuedCompletionStatus`。
   - 连接对象 = `OVERLAPPED` + 池化 buffer；完成端口线程数 = `[net] io_threads`。
   - 与现有 `Rosoto.toml [net]` 上限（max_conns / buffer / backpressure）一一对应。
   - 成本：~600–900 行导入封装 + 运行时事件循环。
2. **A：AFD（\Device\Afd）**（更底层、更省，但无公开文档）
   - 直接 `NtDeviceIoControlFile` + IO_STATUS_BLOCK，少一层 winsock。
   - 不适合作为第一版：可维护性差、行为随 Windows 版本漂移。

建议：**先 B**，把 `net.TcpServer` 在 Windows 上跑通百万连接测试；AFD 作为后续「极致省用」选项。

### 候选 B：macOS / iOS（Mach-O + kqueue）——P1

- 指令层复用 AArch64（`rosoto_arm64.py`），新增 Mach-O 写出器（LC_SEGMENT_64 /
  LC_MAIN / LC_LOAD_DYLIB / LC_DYLD_INFO_ONLY / 代码签名留空）。
- 系统调用：macOS 不再稳定支持 raw syscall 跨版本，走 **libSystem 导入**
  （`write / exit / mmap / pthread_create`），与 Windows 的 winapi 层同构。
- IO：kqueue 事件循环（结构比 epoll 简单）。
- **阻塞点**：需要 macOS 真机或 GitHub Actions macOS runner；本机没有。
  可以先写 Mach-O 写出器 + 用 `otool`/静态校验，执行级验证等机器。

### 候选 C：WebAssembly（wasm64）——P2

- RosIR → wasm 指令是一一映射，优化器完全复用；运行时用 WASI（`fd_write` / `proc_exit`）。
- 多核：Web Workers + SharedArrayBuffer（需要 COOP/COEP 响应头）。
- 价值：浏览器里跑 Rosoto 游戏 demo，传播力最强；性能不如原生，但「全平台」叙事完整。
- 成本：~1200 行（wasm 编码 + 线性内存布局 + WASI 导入）。

### 候选 D：移动端（iOS/Android）——P3

- Android 复用 Linux aarch64 + epoll，主要是打包/NDK 工具链。
- iOS 复用 macOS arm64 + Mach-O，受 App Store 限制（JIT 禁止，AOT 反而合适）。
- 两者都需要真机与签名流程，建议在 macOS 格打通后再做。

### 候选 E：主机——按需

- 需要厂商 NDA、SDK、认证流程；技术上是「再写一个格式 + 一个 IO 后端」。

---

## 5. 需要你拍板的三个问题

1. **下一格做哪个？**
   - [ ] Windows 网络（IOCP）——把 Windows 补成完整平台（推荐）
   - [ ] macOS arm64（Mach-O + kqueue）——补 Apple 生态
   - [ ] wasm64——补 Web/游戏 demo
2. **真机/CI 资源**：macOS 格需要 Mac 或 GitHub Actions macOS runner；
   ARM64 Linux 格需要 aarch64 主机或 qemu-user。你那边能提供哪一种？
3. **「全平台」的验收口径**：是「能编译出对应格式」还是「执行级测试全部通过」？
   本仓库目前的标准是后者（Windows 54 项、Linux 126 项）。

---

## 6. 平台无关的硬约束（所有格都必须满足）

- **同一份 `.ros` 源码**，不改一行即可换 target。
- **同一套 `Rosoto.toml`**：多核/线程/网络上限/堆上限在编译期注入。
- **交叉验证**：新平台的输出必须与 Linux 自研后端逐字节一致（浮点/CPU 信息除外）。
- **无 CRT / 无 GC / 无隐藏分配**：启动即 main，退出即 ExitProcess。
- **失败要响**：超限（连接数/堆）一律 fail-fast，不静默膨胀。
