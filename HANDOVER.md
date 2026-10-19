# Rosoto 交接文档（HANDOVER）

> 本轮：**v0.4 任务并行（spawn/join）+ 帧级 arena**
> 交接时间：2026-10-19（GMT+8）
> 状态：**165 项回归全绿**（Windows 47 / 自研 Linux 42 / C 16 / corelib 34 / io_uring 26）
> 代码总量：`tools/` 11.4k 行 Python + `tests/` 1.4k 行（脚本/测试/模拟器）

---

## 0. 一句话结论

Rosoto 现在有了**真正可用的任务并行与帧级内存回收**：

```rosoto
arena {
    let a = spawn tick(21)     // Linux clone / Windows CreateThread / C pthread
    let b = spawn tick(20)
    assert(join(a) == 42, "task a")
    assert(join(b) == 40, "task b")
}                              // bump 指针整体回卷：1MB 上限下跑完 4MB 分配量
```

同一份源码在 **Linux 裸 ELF / Windows PE（无 CRT）/ C99** 三条链上输出逐字节一致；
`[core] multicore = false` 时 `spawn` 退化为同步调用、`join` 直接取结果，语义不变。

> 上一轮（v0.3）交付了 Windows x86_64 PE/COFF 后端；本轮在其之上补语言层能力，
> Windows 回归从 41 项扩到 47 项。

---

## 1. 这一轮做了什么

### 1.1 语言：`spawn` / `join` 任务并行

| 后端 | 实现 |
|---|---|
| Linux 自研 x86_64 | `clone()`（共享 VM）+ 新栈 + `wait4`；参数块经 `__alloc` 分配 |
| Windows 自研 PE | `CreateThread` + `WaitForSingleObject` + `CloseHandle`；ThreadProc 用 `winargs` 取参 |
| C 后端 | `pthread_create` + `pthread_join`；`ROSOTO_MULTICORE` 宏控制单核同步 |
| 单核降级 | 编译期直接调用目标函数，`join` 恒等返回结果 |

- **返回值**：`join(handle)` 返回任务结果（int/bool/void），句柄是 16 字节记录
  `[原生线程句柄, 参数块]`，参数块首字是返回值。
- **参数/返回值约束**（明确报错，不静默降级）：只支持 int / bool / str 标量；
  结构体/枚举按值跨线程涉及生命周期，等所有权/借用落地后再开。
- **线程入口安全**：Linux 子线程不能从父栈溢出槽取参数（会与并发父线程抢槽位），
  新增 IR `spawn_child`：参数块指针由父线程放在**新栈顶 - 8**，子线程用 `rsp` 直接取，
  调用 worker 后 `exit(0)`，全程不经过 vreg/父栈。
- **worker 永不内联**（`no_inline`），与 parfor worker 同理。

### 1.2 语言：`arena { ... }` 帧级分配

- native（Linux/Windows）：`__arena_mark()` 保存 bump 偏移，块末 `__arena_release(mark)`
  整体回卷；块内 `__alloc`（当前主要是字符串）一次性回收。
- C 后端：字符串走轮转静态缓冲、没有堆分配，`arena` 编译为纯作用域（语义上的
  「分配」不发生，因此无需回收）。
- **验证方式（可证伪）**：`tests/arena_lowheap/` 配 `heap_limit_mb = 1`，
  循环 20 万次、每次分配 ~20 字节（总计 ~4MB）。
  - 有 `arena`：跑完，输出 `arena ok / 200000`；
  - 无 `arena`（`no_arena.ros`）：在 1MB 处 fail-fast，退出码非 0。
- **限制（已写进 SPEC §6）**：块内分配不得逃逸；块内 `break/continue/return`
  会跳过 release（不静默保证）；bump 分配器非原子，别在多个线程里同时分配。

### 1.3 修掉一个潜在语义 bug（arena 测试暴露）

**字符串条件分支比较的是指针**：表达式路径 `print(s == "v0")` 一直正确，
但 `if s == "v0"` 走 `Lower.branch()`，旧实现对 `==` 直接发 `jcc`，比较的是两个
字符串指针 → 条件永远为假。本轮在 `branch()` 里对 str 的 `==`/`!=` 改走
`__str_eq`，并新增对应回归。这个 bug 影响所有 native 后端的字符串条件判断，
是 arena 低堆测试顺带抓出来的。

### 1.4 回归扩容

| 套件 | 上一轮 | 本轮 | 新增 |
|---|---|---|---|
| Windows PE | 41 | **47** | spawn 任务、arena 低堆回收、无 arena OOM、spawn 单核降级 |
| Linux 自研 | 35 | **42** | spawn 三链交叉验证、spawn 单核降级、arena 低堆、无 arena OOM |
| C / corelib / io_uring | 16 / 34 / 26 | 不变 | — |

新增夹具：`tests/t13_spawn.ros`、`tests/arena_lowheap/{Rosoto.toml,arena.ros,no_arena.ros}`。

### 1.5 文档

- `README.md` / `SPEC.md` / `BACKEND.md` 增加 spawn/arena 章节与实测数据；
- 本 HANDOVER 重写为本轮版本；
- `PLATFORM.md` 的平台优先级不变（Windows IOCP / SIMD / macOS 仍是下一格候选）。

---

## 2. 还没有做什么（未完成清单）

### 2.1 语言特性

| 特性 | 现状 | 优先级 |
|---|---|---|
| `chan[T]`（MPMC 通道） | ❌ 运行时 `rosoto_mt.py` 有 C 版队列，缺语法与 native 降级 | **高** |
| `h.join()` 方法式语法 | ❌ 当前是 `join(h)` 内建函数（与 SPEC §4 示例不同） | 中 |
| `option[T]` / `result[T,E]` + `?` | ❌ `?` 仅 C 后端有 int 占位；native 直接报错 | **高** |
| `map[K]V`、`[N]T`、`[]T` 运算 | ❌ 只有类型语法占位 | 高 |
| 泛型 / `interface` | ❌ 未实现 | 中 |
| 所有权 + 借用检查 | ❌ 未实现（arena/spawn 目前靠约定） | 中 |
| `@simd` / `@no_preempt` / `@rc[T]` / `@extern("C")` | ❌ 未实现 | 中 |
| 浮点类型实际运算（f32/f64） | 🟡 类型名可解析，运算/打印未打通 | 中 |
| `rosoto_fmt` 覆盖 struct/enum/match/arena/spawn | ❌ 格式化器未适配 | 低 |

### 2.2 平台 / 性能

| 项 | 现状 |
|---|---|
| **Windows 网络（IOCP/AFD）** | ❌ `net.TcpServer` 在 Windows 上仍不可用 |
| macOS/iOS（Mach-O + kqueue） | ❌ 未做；需 Mac 真机/CI |
| Android（aarch64 + epoll） | ❌ 未做 |
| Web（wasm64） | ❌ 未做 |
| AArch64 真机验证 | 🟡 仅自研模拟器；且 `spawn` 并行路径暂只支持 x86_64 |
| SIMD 自动向量化 | ❌ 未做（loop_sum 与 gcc -O2 的主要差距） |
| 尾调用消除 / LTO / 热重载 | ❌ 未做 |
| Windows PE 调试信息 / SEH unwind | ❌ 未做 |

### 2.3 工程化

| 项 | 现状 |
|---|---|
| `rosoto test --target all` 一次跑四后端 | ❌ 仍需分别指定 |
| `rosoto bench` 跨平台基线 | 🟡 有壳，未建基线文件 |
| CI（Linux/Windows 双矩阵） | ❌ 未接 |
| Windows 上 C 后端验证 | ❌ 本机无 gcc/clang（C 回归在 WSL 跑） |

---

## 3. 差什么（阻塞项 / 需要的输入）

1. **真正的 git 远端**：本仓库仍是本地仓库（v0.3 时 `git init`），没有配置 remote。
   要推送到 GitHub/Gitee/自建服务，请给 **remote URL**，或在本机执行：
   `git remote add origin <URL> && git push -u origin master`。
2. **macOS / ARM64 真机或 CI**：Mach-O/kqueue 与 AArch64 执行级验证缺硬件；
   可选 GitHub Actions `macos-latest` / `ubuntu-24.04-arm`。
3. **Windows 无 gcc/clang**：C 后端只能在 WSL 验证。
4. **Windows 网络压测环境**：IOCP/AFD 落地后需要句柄上限、防火墙、压测客户端。
5. **产品级平台优先级**：见 `PLATFORM.md §5`（Windows 网络 / macOS / wasm 三选一）。

---

## 4. 写了多少（本轮产出统计）

| 类别 | 文件 | 行数 | 说明 |
|---|---|---|---|
| 前端 + C 后端 | `tools/rosoto.py` | 1961（+114） | `arena`/`spawn` 语法、C 版 pthread 任务、`rosoto_join`、字符串分支修复（C 侧） |
| 自研 x86_64 | `tools/rosoto_native.py` | 2746（+195） | `lower_spawn`、`spawn_child`、arena runtime、`__join`、字符串分支修复 |
| RosIR 优化器 | `tools/rosoto_opt.py` | 901（+3） | `spawn_child` 的 def/use、调度终止/保序、延迟 |
| Windows PE | `tools/rosoto_pe.py` | 353 | 未改（spawn 复用 winargs/CreateThread） |
| 命令行 | `tools/rosoto_cli.py` | 315 | 版本 0.4.0 |
| 回归 | `tests/run_win_tests.py` | 332（+38） | 新增 spawn/arena/降级用例 |
| 回归 | `tests/run_native_tests.sh` | — | 新增 [11] 段（7 项） |
| 新夹具 | `tests/t13_spawn.ros`、`tests/arena_lowheap/*` | 64 | 任务并行 + 低堆 arena / 负向对照 |
| 文档 | `README.md` / `SPEC.md` / `BACKEND.md` / `HANDOVER.md` | — | v0.4 同步 |

**测试规模**：165 项（Windows 47 / 自研 Linux 42 / C 16 / corelib 34 / io_uring 26），全绿。
**跨链验证**：spawn 在 Linux ELF / Windows PE / C99 三条链输出一致；arena 在三条链语义一致
（native 真回收，C 为作用域）。

---

## 5. 需要写什么（下一轮建议）

1. **`chan[T]` 类型化通道**
   - Linux：`clone` + futex（或 `eventfd`）实现 MPMC 环形队列；
   - Windows：`SRWLOCK` + 条件变量（`SleepConditionVariableSRW`）或 `WaitOnAddress`；
   - C 后端：固定容量、满/空阻塞或 fail-fast。
2. **`option` / `result` + `?`**
   - 复用 enum 的 tag+payload 布局；先定 `option[int]` 等单态化的类型表示；
   - `?` 在 native 后端降级为「tag 检查 + 提前返回 Err」。
3. **`map[K]V` / `[N]T` / `[]T`**
   - 需要先有 `slice` 的运行时表示（指针+长度）与越界检查策略；
   - 可先做 `[N]T`（栈上定长）再 `[]T`，最后 `map`。
4. **Windows IOCP/AFD 网络**（平台主线，`PLATFORM.md` 候选 A）。
5. **SIMD 自动向量化**（性能主线，loop_sum 基线）。
6. **macOS Mach-O + kqueue**（有 Mac 资源再做）。

---

## 6. 怎么接着干（开工步骤）

```bash
# 全量回归（165 项）
bash tests/run_native_tests.sh      # 42
bash tests/run_tests.sh             # 16（需 cc）
bash tests/test_corelib.sh          # 34
bash tests/test_uring.sh            # 26
python tests/run_win_tests.py       # 47（Windows 原生）

# 新特性试跑（三链）
python tools/rosoto_cli.py run tests/t13_spawn.ros --target win
python3 tools/rosoto_native.py run tests/t13_spawn.ros
python3 tools/rosoto.py       run tests/t13_spawn.ros

# arena 低堆验证（1MB 上限 / 4MB 分配量）
python3 tools/rosoto_native.py run tests/arena_lowheap/arena.ros
python3 tools/rosoto_native.py run tests/arena_lowheap/no_arena.ros   # 期望 OOM

# 看 IR
python tools/rosoto_pe.py build tests/t13_spawn.ros -o build/x.exe --dump-ir --no-opt

# Windows 崩溃排查
python tools/rosoto_dbg.py build/x.exe
```

### 新增 IR 指令检查表（现在共 9 处，漏一处就是隐性错编）

1. `tools/rosoto_native.py::_map_ins`（内联重命名）
2. `tools/rosoto_opt.py::vreg_mentions`（def/use）
3. `tools/rosoto_opt.py::_subst_vregs`（复制传播替换）
4. `tools/rosoto_opt.py::PURE`（DCE/CSE/LICM）
5. `tools/rosoto_opt.py::_EFF`（副作用/访存保序）
6. `tools/rosoto_opt.py::_LAT` + `_TERM`（调度延迟/基本块终止）
7. `tools/rosoto_native.py::allocate` 的 `call_sites`
8. x86_64 `gen_instr`（+ Windows `WinCodegen.gen_instr`）
9. AArch64 `gen_instr`（若该指令需要跨架构）

### 血泪教训（累计）

- **字符串条件分支必须走 `__str_eq`**：`branch()` 里直接 `jcc` 比的是指针，
  `if s == "x"` 会永远为假（本轮修复）。
- **子线程不能从父栈溢出槽取参数**：用 `spawn_child` 从新栈顶 `[rsp-8]` 取。
- **arena 的 release 必须与 mark 配对**：块内 `break/continue/return` 会跳过 release。
- **PE `headers_size` 含节表**；**`.reloc` 补齐必须是 0x0000**；**线程入口参数在 RCX**；
  **`winapi` 必须进 `_EFF`**（详见 BACKEND.md §6）。
- **`winapi` 栈参数先写、再搬寄存器实参**。
- **parfor/spawn worker 永不内联**；RosIR 非 SSA，任何 pass 对多次定义要保守。

---

## 7. 远端同步 / 版本控制

- 仓库：本目录（v0.3 时 `git init`，默认分支 `master`）。
- 本轮提交：`v0.4: spawn/join task parallelism + arena frame reclamation (165 tests green)`。
- **仍未推送到网络远端**（没有 remote）。请给 URL，或执行：
  ```bash
  git remote add origin <URL>
  git push -u origin master
  ```
- 若「远程端目录」指本机 `C:\Users\43551\Desktop\Rosoto\rosoto`：本轮文件已直接写入，目录即最新源码。

---

## 8. 本轮改动的文件清单

```
修改：
  tools/rosoto.py             arena/spawn 语法、C 版任务并行、rosoto_join
  tools/rosoto_native.py      lower_spawn/spawn_child/__join/arena runtime、字符串分支修复
  tools/rosoto_opt.py         spawn_child 的 def-use / 调度分类
  tools/rosoto_cli.py         版本 0.4.0
  tests/run_native_tests.sh   新增 [11] 段（7 项）
  tests/run_win_tests.py      新增 spawn/arena 用例（6 项）
  README.md / SPEC.md / BACKEND.md / HANDOVER.md

新增：
  tests/t13_spawn.ros                  spawn/join 回归
  tests/arena_lowheap/Rosoto.toml      1MB 堆上限夹具
  tests/arena_lowheap/arena.ros        arena 回收验证
  tests/arena_lowheap/no_arena.ros     负向对照（期望 OOM）

测试：
  Windows 47 ✅  |  自研 Linux 42 ✅  |  C 16 ✅  |  corelib 34 ✅  |  io_uring 26 ✅
```
