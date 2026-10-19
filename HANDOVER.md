# Rosoto 交接文档（HANDOVER）

> 本轮：**v0.5 有界通道 `chan[T]` + 运行库按需发射**
> 交接时间：2026-10-19（GMT+8）
> 状态：**172 项回归全绿**（Windows 50 / 自研 Linux 46 / C 16 / corelib 34 / io_uring 26）
> 代码总量：`tools/` 11.7k 行 Python + `tests/` 1.4k 行（脚本/测试/模拟器）

---

## 0. 一句话结论

并发模型的三块拼图现在齐了：**`parfor`（数据并行）+ `spawn/join`（任务并行）+
`chan[T]`（有界 MPMC 通信）**，并且 `arena { }` 提供帧级批量回收。

```rosoto
let ch = chan[int].open(4)          // 容量 4，满则阻塞
let h1 = spawn producer(ch, 500, 0)
let h2 = spawn producer(ch, 500, 1000)
let mut sum = 0
let mut got = 0
while got < 1000 { sum += ch.recv()  got += 1 }
join(h1)
join(h2)
assert(sum == 749500, "channel sum")
```

Linux 裸 ELF / Windows PE（无 CRT）/ C99 三条链输出一致；`multicore=false` 时
`spawn` 同步化、`join` 取结果，通道 FIFO 语义不变。

---

## 1. 这一轮做了什么

### 1.1 `chan[T]`：有界 MPMC 通道

| 后端 | 实现 |
|---|---|
| Linux 自研 x86_64 | 48B 控制块 `[cap, head, tail, count, lock, buf]`；`xchg` 原子自旋锁；忙等时 `sched_yield(24)` |
| Windows 自研 PE | 同一套 RosIR；忙等时 `SwitchToThread`（kernel32 导入） |
| C 后端 | `pthread_mutex_t` + `pthread_cond_t`（`not_empty/not_full`） |
| 单核降级 | 无跨线程，FIFO 与阻塞语义保持；容量足够时可直接用 |

- 新增 RosIR 指令 **`('xchg', dst, addr, val)`**：`dst = *addr; *addr = val`，x86 用
  `xchg [mem], reg`（隐含 LOCK），编码 `REX.W 87 /r`。
- 运行时 `__chan_open / __chan_send / __chan_recv` 全部用 RosIR 自举；
  `open` 校验容量（<=0 修正为 1），缓冲区 `cap*8` 字节。
- 语言侧：`chan[T].open(cap)`、`ch.send(v)`、`v = ch.recv()`；`chan[T]` 可作为
  函数参数类型；`spawn` 可直接把通道句柄传给 worker。

### 1.2 运行库按需发射（省用）

之前无论程序用不用，`__chan_*`、`__join`、arena 运行时都会进产物，Windows PE 还会
多一个 `SwitchToThread` 导入。本轮改为：

1. `Lower.run` 先降级用户函数，过程中记录 `uses_arena / uses_join / uses_chan`；
2. 再 `lower_runtime`，只发射真正用到的部分。

效果：hello 的 PE 导入回到 4 个（`ExitProcess/GetStdHandle/WriteFile/VirtualAlloc`），
不写通道的程序不会带通道代码；写通道的 t15 才引入 `SwitchToThread`。

### 1.3 本轮修掉的 3 个真实缺陷（全部有回归）

| # | 症状 | 根因 | 修复 |
|---|---|---|---|
| 1 | `assert(1 == 2)` 的失败路径**静默变成正常退出**（exit 0、stderr 空） | 内联标签后缀只用 `caller.nv`；两个不同函数 nv 相同又内联同一 callee 时标签重名，后发射的覆盖前者，`main` 里的跳转跳进**另一个函数体内** | 后缀改为 `.inl_{caller_name}_{base}` |
| 2 | 用变量作 `spawn` 实参时 C 编译报 `'ch' undeclared` | C helper 里错误地写了调用点实参表达式（`a->a0 = ch;`），而不是形参 | helper 只使用 `p0..`，实参只在调用点求值一次 |
| 3 | 非 chan 程序也带 `SwitchToThread` 导入与通道运行库 | 运行库全量发射 | 先降级用户函数收集 uses_*，再按需发射 |

> 第 1 个是本项目至今最隐蔽的 bug：IR 层完全正确、反汇编也「像对的」，只有
> 交叉引用标签地址才暴露；由 `win_assert` 回归与 Windows 套件抓住。

### 1.4 回归扩容

| 套件 | v0.4 | v0.5 | 新增 |
|---|---|---|---|
| Windows PE | 47 | **50** | chan 多生产者求和 + FIFO、chan 单核降级 |
| Linux 自研 | 42 | **46** | chan 三链交叉验证、chan FIFO、chan 单核降级 |
| C / corelib / io_uring | 16 / 34 / 26 | 不变 | — |

新夹具：`tests/t15_chan.ros`、`tests/single_core/t15_chan_seq.ros`。

### 1.5 文档

`README.md` / `SPEC.md`（新增 §4.2 chan 子集）/ `BACKEND.md`（新 IR、按需发射、
v0.5 坑）已同步；CLI 版本 0.5.0。

---

## 2. 还没有做什么（未完成清单）

### 2.1 语言特性

| 特性 | 现状 | 优先级 |
|---|---|---|
| `option[T]` / `result[T,E]` + `?` | ❌ `?` 仅 C 后端有 int 占位；native 报错 | **高** |
| `map[K]V`、`[N]T`、`[]T` 运算 | ❌ 只有类型语法占位 | **高** |
| `chan.close()` / `select` / 无界通道 | ❌ | 中 |
| `h.join()` 方法式语法 | ❌ 当前是 `join(h)` 内建函数 | 中 |
| 泛型 / `interface` | ❌ | 中 |
| 所有权 + 借用检查 | ❌ arena/spawn 目前靠约定 | 中 |
| `@simd` / `@no_preempt` / `@rc[T]` / `@extern("C")` | ❌ | 中 |
| 浮点类型实际运算（f32/f64） | 🟡 类型名可解析，运算/打印未打通 | 中 |
| `rosoto_fmt` 覆盖新语法 | ❌ | 低 |

### 2.2 平台 / 性能

| 项 | 现状 |
|---|---|
| **Windows 网络（IOCP/AFD）** | ❌ `net.TcpServer` 在 Windows 上仍不可用 |
| **自研后端网络（Linux epoll）** | ❌ native 后端还没有网络；只有 C 后端有 |
| macOS/iOS（Mach-O + kqueue） | ❌ 需 Mac 真机/CI |
| Android（aarch64 + epoll） | ❌ |
| Web（wasm64） | ❌ |
| AArch64 的 `spawn`/`chan` | ❌ 目前仅 x86_64（`ldaxr/stxr` 版本待补） |
| SIMD 自动向量化 | ❌ loop_sum 与 gcc -O2 的主要差距 |
| 尾调用消除 / LTO / 热重载 | ❌ |
| Windows PE 调试信息 / SEH unwind | ❌ |

### 2.3 工程化

| 项 | 现状 |
|---|---|
| `rosoto test --target all` | ❌ 需分别指定 |
| `rosoto bench` 跨平台基线 | 🟡 有壳，未建基线 |
| CI（Linux/Windows 双矩阵） | ❌ 未接 |
| Windows 上 C 后端验证 | ❌ 本机无 gcc/clang |

---

## 3. 差什么（阻塞项 / 需要的输入）

1. **git 远端仍缺失**：仓库是本地 git（v0.3 时 init），没有 remote。
   请给 URL，或执行 `git remote add origin <URL> && git push -u origin master`。
2. **macOS / ARM64 真机或 CI**：Mach-O/kqueue 与 AArch64 执行级验证缺硬件。
3. **Windows 无 gcc/clang**：C 后端回归只能在 WSL 跑。
4. **Windows 网络压测环境**：IOCP/AFD 落地后需要句柄上限、防火墙、压测客户端。
5. **产品级平台优先级**：`PLATFORM.md §5`（Windows 网络 / macOS / wasm）。

---

## 4. 写了多少（本轮产出统计）

| 类别 | 文件 | 行数 | 说明 |
|---|---|---|---|
| 前端 + C 后端 | `tools/rosoto.py` | 2059（+98） | `chan[T]` 语法/类型、C 通道运行时、spawn helper 修复 |
| 自研 x86_64 | `tools/rosoto_native.py` | 2934（+188） | `xchg` IR、chan 运行时、按需发射、内联标签修复 |
| RosIR 优化器 | `tools/rosoto_opt.py` | 905（+4） | `xchg` 的 def/use、副作用保序、延迟 |
| Windows PE | `tools/rosoto_pe.py` | 353 | 未改（chan 复用 winapi） |
| 命令行 | `tools/rosoto_cli.py` | 315 | 版本 0.5.0 |
| 回归 | `tests/run_win_tests.py` | 344（+12） | chan 用例 |
| 回归 | `tests/run_native_tests.sh` | — | 新增 4 项 chan 检查 |
| 新夹具 | `tests/t15_chan.ros`、`tests/single_core/t15_chan_seq.ros` | 55 | 多生产者/容量 4 阻塞/FIFO/单核 |
| 文档 | `README.md` / `SPEC.md` / `BACKEND.md` / `HANDOVER.md` | — | v0.5 同步 |

**测试规模**：172 项（Windows 50 / 自研 Linux 46 / C 16 / corelib 34 / io_uring 26），全绿。
**跨链验证**：chan 在 Linux ELF / Windows PE / C99 三链输出一致；单核降级 FIFO 一致。

---

## 5. 需要写什么（下一轮建议）

1. **`option` / `result` + `?`**（错误模型，SPEC §3 的核心承诺）
   - 复用 enum 的 tag+payload 布局；`option[int]` / `result[int,str]` 先做单态化；
   - `?` 在 native 后端降级为「tag 检查 + 提前返回 Err」。
2. **`[N]T` / `[]T` / `map`**（数据与游戏数学的基础）
   - 先 `[N]T`（栈上定长 + 索引 + `len` + 值语义拷贝），再 `[]T`（指针+长度），最后 `map`。
3. **自研后端网络**（epoll/IOCP）
   - 需要先有 slice（`[]byte`）与间接调用（回调）；建议在 `[N]T/[]T` 之后。
4. **SIMD 自动向量化**（性能主线，loop_sum 基线）。
5. **macOS Mach-O + kqueue**（有 Mac 资源再做）。

---

## 6. 怎么接着干（开工步骤）

```bash
# 全量回归（172 项）
bash tests/run_native_tests.sh      # 46
bash tests/run_tests.sh             # 16（需 cc）
bash tests/test_corelib.sh          # 34
bash tests/test_uring.sh            # 26
python tests/run_win_tests.py       # 50（Windows 原生）

# chan 三链
python tools/rosoto_cli.py run tests/t15_chan.ros --target win
python3 tools/rosoto_native.py run tests/t15_chan.ros
python3 tools/rosoto.py       run tests/t15_chan.ros

# 单核降级 FIFO
python tools/rosoto_pe.py run tests/single_core/t15_chan_seq.ros

# 看 IR / 调试
python tools/rosoto_pe.py build tests/t15_chan.ros -o build/x.exe --dump-ir --no-opt
python tools/rosoto_dbg.py build/x.exe
```

### 新增 IR 指令检查表（现在共 9 处）

1. `tools/rosoto_native.py::_map_ins`
2. `tools/rosoto_opt.py::vreg_mentions`
3. `tools/rosoto_opt.py::_subst_vregs`
4. `tools/rosoto_opt.py::PURE`
5. `tools/rosoto_opt.py::_EFF`
6. `tools/rosoto_opt.py::_LAT` + `_TERM`
7. `tools/rosoto_native.py::allocate` 的 `call_sites`
8. x86_64 `gen_instr`（+ Windows `WinCodegen.gen_instr`）
9. AArch64 `gen_instr`（若该指令需要跨架构）

### 血泪教训（累计）

- **内联标签后缀必须带 caller 名字**（v0.5 的 exit-0 静默 bug）。
- **C 后端 helper 只能引用形参**，实参表达式只在调用点求值。
- **运行库按需发射**：先降级用户函数收集 uses_*，再发运行库。
- **字符串条件分支走 `__str_eq`**（`branch()` 不能直接比指针）。
- **子线程不能从父栈溢出槽取参数**（`spawn_child` 从新栈顶 `[rsp-8]` 取）。
- **arena release 与 mark 配对**；`break/continue/return` 会跳过 release。
- **`winapi` 必须进 `_EFF`**；栈参数先写再搬寄存器实参。
- **PE `headers_size` 含节表**；`.reloc` 补齐必须是 0x0000；线程入口参数在 RCX。
- **parfor/spawn worker 永不内联**；RosIR 非 SSA。

---

## 7. 远端同步 / 版本控制

- 仓库：本目录（`master`），本轮提交：
  `v0.5: chan[T] bounded MPMC channels + on-demand runtime (172 tests green)`。
- **仍没有 git remote**。请给 URL，或执行：
  ```bash
  git remote add origin <URL>
  git push -u origin master
  ```
- 若「远程端目录」指本机 `C:\Users\43551\Desktop\Rosoto\rosoto`：文件已直接写入。

---

## 8. 本轮改动的文件清单

```
修改：
  tools/rosoto.py             chan[T] 语法/类型、rosoto_chan_* 运行时、spawn helper 修复
  tools/rosoto_native.py      xchg IR、__chan_* 运行时、按需发射、内联标签修复
  tools/rosoto_opt.py         xchg 的 def/use/保序/延迟
  tools/rosoto_cli.py         版本 0.5.0
  tests/run_native_tests.sh   新增 chan 4 项
  tests/run_win_tests.py      新增 chan 3 项
  README.md / SPEC.md / BACKEND.md / HANDOVER.md

新增：
  tests/t15_chan.ros                 多生产者 + 容量 4 阻塞 + FIFO
  tests/single_core/t15_chan_seq.ros 单核 FIFO

测试：
  Windows 50 ✅  |  自研 Linux 46 ✅  |  C 16 ✅  |  corelib 34 ✅  |  io_uring 26 ✅
```
