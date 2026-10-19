# Rosoto 交接文档（HANDOVER）

> 本轮：**v0.5 有界通道 `chan[T]` + v0.6 定长数组 `[N]T`**
> 交接时间：2026-10-19（GMT+8）
> 状态：**180 项回归全绿**（Windows 54 / 自研 Linux 50 / C 16 / corelib 34 / io_uring 26）
> 代码总量：`tools/` 12.0k 行 Python + `tests/` 1.4k 行（脚本/测试/模拟器）
> 本轮已提交：`3e9b8c0 v0.5: chan[T] ...` 与 `v0.6: fixed-size arrays [N]T ...`

---

## 0. 一句话结论

并发与数据两条主线同时往前推了一格：

- **v0.5 `chan[T]`**：有界 MPMC、阻塞 `send/recv`，自研后端用 `xchg` 自旋锁 + yield，
  C 后端用 `pthread_mutex/cond`；`spawn`/`join` 与通道组合可用。
- **v0.6 `[N]T`**：栈上定长数组，字面量 / 动态下标 / 复合赋值 / `len` / 值语义拷贝，
  越界默认 **fail-fast**（`Rosoto.toml [build] bounds_check` 可关）。

两条特性都在 **Linux 裸 ELF / Windows PE（无 CRT）/ C99** 三条链上输出一致、有回归覆盖。

```rosoto
let mut a = [1, 2, 3, 4]
a[1] = 20
a[2] += 5
assert(len(a) == 4, "len")
let b = a                 // 值语义拷贝
b[0] = 100
assert(a[0] == 1, "no alias")

let ch = chan[int].open(4)
let h = spawn producer(ch, 100)
let mut sum = 0
let mut i = 0
while i < 100 { sum += ch.recv()  i += 1 }
join(h)
```

---

## 1. 这一轮做了什么

### 1.1 `chan[T]`：有界 MPMC 通道（v0.5）

| 后端 | 实现 |
|---|---|
| Linux 自研 x86_64 | 48B 控制块 `[cap, head, tail, count, lock, buf]`；`xchg` 原子自旋锁；忙等 `sched_yield(24)` |
| Windows 自研 PE | 同一套 RosIR；忙等 `SwitchToThread`（kernel32 导入） |
| C 后端 | `pthread_mutex_t` + `pthread_cond_t`（`not_empty/not_full`） |
| 单核降级 | 无跨线程，FIFO 与阻塞语义保持；容量足够时可直接用 |

- 新 IR `('xchg', dst, addr, val)`：x86 `xchg [mem], reg`（隐含 LOCK），编码 `REX.W 87 /r`。
- 语法：`chan[T].open(cap)`、`ch.send(v)`、`x = ch.recv()`；`chan[T]` 可作函数参数。
- 限制：载荷 8 字节（int/bool/str 指针）；AArch64 未实现；`close/select` 未做；
  单核配置下生产者发送量 > 容量会按阻塞语义等待（预期行为）。

### 1.2 `[N]T` 定长数组（v0.6）

| 能力 | 实现 |
|---|---|
| 字面量 | `[1, 2, 3]` → 帧上 N 个 8 字节槽（C：`int64_t a[N] = {...}`） |
| 下标读 | `a[i]` → native `load base,idx`；C `a[i]` |
| 下标写 / 复合赋值 | `a[i] = v` / `a[i] += v`，支持动态下标 |
| `len(a)` | 编译期常量 N |
| 值语义拷贝 | `let b = a` / `b = a` → 逐字拷贝（C：`memcpy`） |
| 越界检查 | 默认 fail-fast：stderr 输出 `rosoto: index out of bounds (fail-fast)` + 退出码 1 |

- 配置：`Rosoto.toml [build] bounds_check = false` 可关闭检查（性能优先，越界即 UB）。
- 边界：**只支持数值元素**、**只能作函数内局部数组**；作函数参数/返回值会明确报错。
  （`[]T` 切片与 `map` 需要运行时表示，留到下一轮。）

### 1.3 运行库按需发射（v0.5，省用）

`Lower.run` 改为先降级用户函数、记录 `uses_arena/uses_join/uses_chan/uses_bounds`，
再发射运行库。效果：

- 不写通道的程序不带 `__chan_*`，Windows PE 不再无谓导入 `SwitchToThread`；
- hello 的 PE 导入保持 4 个（`ExitProcess/GetStdHandle/WriteFile/VirtualAlloc`）。

### 1.4 本轮修掉的 3 个真实缺陷（都有回归）

| # | 症状 | 根因 | 修复 |
|---|---|---|---|
| 1 | `assert(1 == 2)` 的失败路径**静默变成正常退出**（exit 0、stderr 空） | 内联标签后缀只用 `caller.nv`；两个不同函数 nv 相同又内联同一 callee 时标签重名，后发射的覆盖前者，`main` 的跳转跳进**另一个函数体内** | 后缀改为 `.inl_{caller_name}_{base}` |
| 2 | 变量作 `spawn` 实参时 C 编译报 `'ch' undeclared` | C helper 误用调用点变量名（`a->a0 = ch;`），而非形参 | helper 只用 `p0..`，实参只在调用点求值一次 |
| 3 | 非 chan 程序也带通道运行库 + `SwitchToThread` 导入 | 运行库全量发射 | 按需发射（uses_* 标志） |

> 第 1 个是本项目至今最隐蔽的 bug：IR 完全正确、反汇编也「像对的」，
> 只有交叉引用标签地址才暴露；由 `win_assert` 回归与 Windows 套件抓住。

### 1.5 回归扩容

| 套件 | v0.4 | 本轮 | 新增 |
|---|---|---|---|
| Windows PE | 47 | **54** | chan（2 项）、数组与越界（4 项）、单核 chan（1 项） |
| Linux 自研 | 42 | **50** | chan（4 项）、数组与越界（4 项） |
| C / corelib / io_uring | 16 / 34 / 26 | 不变 | — |

新增夹具：
`tests/t15_chan.ros`、`tests/single_core/t15_chan_seq.ros`、
`tests/t16_arrays.ros`、`tests/array_bounds.ros`。

---

## 2. 还没有做什么（未完成清单）

### 2.1 语言特性

| 特性 | 现状 | 优先级 |
|---|---|---|
| `option[T]` / `result[T,E]` + `?` | ❌ native 仍报错；C 只有 int 占位 | **高** |
| `[]T` 切片（指针+长度） | ❌ 只有类型语法；数组也不能当参数 | **高** |
| `map[K]V` | ❌ 未实现 | **高** |
| 数组作函数参数/返回值 | ❌ 明确报错（v0.6 边界） | 高 |
| `chan.close()` / `select` / 无界通道 | ❌ | 中 |
| `h.join()` 方法式语法 | ❌ 当前是 `join(h)` | 中 |
| 泛型 / `interface` | ❌ | 中 |
| 所有权 + 借用检查 | ❌ arena/spawn/array 目前靠约定 | 中 |
| `@simd` / `@no_preempt` / `@rc[T]` / `@extern("C")` | ❌ | 中 |
| 浮点运算（f32/f64） | 🟡 类型名可解析，运算/打印未打通 | 中 |
| `rosoto_fmt` 覆盖新语法 | ❌ | 低 |

### 2.2 平台 / 性能

| 项 | 现状 |
|---|---|
| **Windows 网络（IOCP/AFD）** | ❌ `net.TcpServer` 在 Windows 上仍不可用 |
| **自研后端网络（Linux epoll）** | ❌ native 后端还没有网络；只有 C 后端有 |
| macOS/iOS（Mach-O + kqueue） | ❌ 需 Mac 真机/CI |
| Android / Web(wasm64) | ❌ |
| AArch64 的 `spawn`/`chan` | ❌ 仅 x86_64（需 ldaxr/stxr 版本） |
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

1. **git 远端仍缺失**：仓库是本地 git，未配置 remote。
   请给 URL，或执行 `git remote add origin <URL> && git push -u origin master`。
2. **macOS / ARM64 真机或 CI**：Mach-O/kqueue 与 AArch64 执行级验证缺硬件。
3. **Windows 无 gcc/clang**：C 后端回归只能在 WSL 跑。
4. **Windows 网络压测环境**：IOCP/AFD 落地后需要句柄上限、防火墙、压测客户端。
5. **产品级平台优先级**：`PLATFORM.md §5`（Windows 网络 / macOS / wasm）。

---

## 4. 写了多少（本轮产出统计）

| 类别 | 文件 | 行数 | 说明 |
|---|---|---|---|
| 前端 + C 后端 | `tools/rosoto.py` | 2199（+238） | chan 语法/类型、C 通道运行时、数组字面量/索引/len/拷贝/越界、spawn helper 修复 |
| 自研 x86_64 | `tools/rosoto_native.py` | 3063（+317） | xchg IR、chan 运行时、数组帧槽/拷贝/越界、按需发射、内联标签修复 |
| RosIR 优化器 | `tools/rosoto_opt.py` | 905（+4） | xchg 的 def/use、保序、延迟 |
| Windows PE | `tools/rosoto_pe.py` | 353 | 未改（复用 winapi） |
| 命令行 | `tools/rosoto_cli.py` | 315 | 版本 0.6.0 |
| 回归 | `tests/run_win_tests.py` | 362（+30） | chan/数组/越界/单核 |
| 回归 | `tests/run_native_tests.sh` | — | chan 4 项 + 数组 4 项 |
| 新夹具 | `t15_chan.ros`、`t15_chan_seq.ros`、`t16_arrays.ros`、`array_bounds.ros` | 92 | 通道 / 数组 / 负向越界 |
| 文档 | `README.md` / `SPEC.md` / `BACKEND.md` / `Rosoto.toml` / `HANDOVER.md` | — | v0.5 / v0.6 同步（含 `bounds_check`） |

**测试规模**：180 项（Windows 54 / 自研 Linux 50 / C 16 / corelib 34 / io_uring 26），全绿。
**跨链验证**：chan 与数组在 Linux ELF / Windows PE / C99 三链输出一致；
数组越界在三链都 fail-fast。

---

## 5. 需要写什么（下一轮建议）

1. **`option` / `result` + `?`**（错误模型，SPEC §3 的核心承诺）
   - 复用 enum 的 tag+payload；先做 `option[int]` / `result[int,str]` 单态化；
   - `?` 在 native 后端降级为「tag 检查 + 提前返回 Err」。
2. **`[]T` 切片**（数组作参数/返回值的前提）
   - 表示：`{ptr, len}` 两字；先支持从 `[N]T` 取切片与只读传递；
   - 有了 slice，`net.Conn`/`[]byte` 才有可能在 native 后端落地。
3. **`map[K]V`**（开放寻址；可指定 arena）
4. **自研后端网络**（epoll/IOCP；依赖 slice + 间接调用）
5. **SIMD 自动向量化**（性能主线，loop_sum 基线）
6. **macOS Mach-O + kqueue**（有 Mac 资源再做）

---

## 6. 怎么接着干（开工步骤）

```bash
# 全量回归（180 项）
bash tests/run_native_tests.sh      # 50
bash tests/run_tests.sh             # 16（需 cc）
bash tests/test_corelib.sh          # 34
bash tests/test_uring.sh            # 26
python tests/run_win_tests.py       # 54（Windows 原生）

# 新特性三链
python tools/rosoto_cli.py run tests/t15_chan.ros --target win
python3 tools/rosoto_native.py run tests/t15_chan.ros
python3 tools/rosoto.py       run tests/t15_chan.ros

python tools/rosoto_pe.py run tests/t16_arrays.ros
python3 tools/rosoto_native.py run tests/t16_arrays.ros
python3 tools/rosoto_native.py run tests/array_bounds.ros   # 期望退出码 1

# 看 IR / 调试
python tools/rosoto_pe.py build tests/t16_arrays.ros -o build/x.exe --dump-ir --no-opt
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
- **数组越界检查要覆盖读和写**，负下标也要判（`i < 0 || i >= N`）。
- **`winapi` 必须进 `_EFF`**；栈参数先写再搬寄存器实参。
- **PE `headers_size` 含节表**；`.reloc` 补齐必须是 0x0000；线程入口参数在 RCX。
- **parfor/spawn worker 永不内联**；RosIR 非 SSA。

---

## 7. 远端同步 / 版本控制

- 仓库：本目录（`master`）。
- 已提交：
  - `3e9b8c0 v0.5: chan[T] bounded MPMC channels + on-demand runtime (172 tests green)`
  - v0.6 数组提交：`v0.6: fixed-size arrays [N]T with bounds-checked access (180 tests green)`
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
  tools/rosoto.py             chan 语法/类型、数组字面量/索引/len/拷贝/越界、C 通道运行时、spawn helper 修复
  tools/rosoto_native.py      xchg IR、__chan_*、数组帧槽/拷贝/越界、按需发射、内联标签修复
  tools/rosoto_opt.py         xchg 的 def/use/保序/延迟
  tools/rosoto_cli.py         版本 0.6.0
  tests/run_native_tests.sh   chan 4 项 + 数组 4 项
  tests/run_win_tests.py      chan/数组/越界/单核
  Rosoto.toml                 新增 [build] bounds_check
  README.md / SPEC.md / BACKEND.md / HANDOVER.md

新增：
  tests/t15_chan.ros                 多生产者 + 容量 4 阻塞 + FIFO
  tests/single_core/t15_chan_seq.ros 单核 FIFO
  tests/t16_arrays.ros               数组 len/读写/拷贝/循环
  tests/array_bounds.ros             越界负向用例

测试：
  Windows 54 ✅  |  自研 Linux 50 ✅  |  C 16 ✅  |  corelib 34 ✅  |  io_uring 26 ✅
```
