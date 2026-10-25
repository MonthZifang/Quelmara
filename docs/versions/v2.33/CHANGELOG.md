# v2.33 — 内存/串内建 + import 向上查找：**qlmc 编出了自己**，子集 S19

- 日期：2026-10-25
- 任务：上一版定位的"自举最后一块基础设施"——import 源根 + 内存内建
- 影响面：自举层（qlmc 内建/语法/IR/发射器/运行库/导入表）/ 测试 / 文档

## 主事件：`qlmc` 编译自己的源码，产出了 stage-2

```
$ ./build/qlmc.exe build bootstrap/qlmc/qlmc.qma -o build/p/self.exe
[qlmc] bootstrap/qlmc/qlmc.qma -> build/p/self.exe  (417792 字节, 子集 S12)
       编译 143882 us（进程内）  后端 21418 us  -j4
```

**但要说清楚：能编出来 ≠ 能用。** stage-2 现在的状态：

| 命令 | 结果 |
|---|---|
| `self.exe`（无参） | ✓ 打用法，退 2 |
| `self.exe version` | ✓ 正确 |
| `self.exe dump no_such.qma` | ✓ 正确报「找不到」 |
| `self.exe dump <存在的文件>` | ✗ 读到的内容是垃圾 → 词法报「不认识的字符」 |
| `self.exe build ...` | ✗ 同上 |

`_args()` / `_read_text` 的**同一个函数体**单独交给 qlmc 编出来是对的（`len=226, s[0]=47`），
所以这是「qlmc 编自己」才暴露的误编译——下一版从 `_read_text` 的返回值开始查。

## 这一版补的东西（都是自举的前置条件）

### ① import 逐级向上查找

stage-0 的 import 解析除了源目录，还会去**仓库根**的 `std/` 找；qlmc 只看源文件同目录，
于是 `import std.core` 直接找不到（`std/` 在仓库根，不在 `src/lib`，`Quelmara.toml` 里
连 `[src]` 段都没有）。新增 `_dir_up` / `_find_module`：从源文件目录**逐级向上**试
`<d>/<mod>.qma`，空目录也试一次（相对 cwd）。不需要读配置文件。

### ② 16 个内建（qlmc 之前只有 `assert`/`len`/`join`）

| 类 | 内建 |
|---|---|
| 诊断 | `eprint`（写 stderr + 换行，新运行库 `__eprint_str`） |
| 内存 | `mem_alloc` / `mem_free`（bump，**不回收**）/ `mem_load8` / `mem_store8` / `mem_load64` / `mem_store64` / `mem_copy` / `mem_zero` / `mem_cmp`（新运行库 `__memcmp`）/ `mem_str` |
| 串 | `chr` / `substr`（第三个数是**长度**）/ `cstr`（qlmc 的 str 自带 NUL → **恒等**）/ `int.to_str`（走 `wsprintfA "%I64d"`，新运行库 `__i64_fmt`）/ `str.to_int`（新运行库 `__str_to_int`，溢出前置检查） |
| 其它 | `file_exists`（GetFileAttributesA，掩到 32 位再比 `0xFFFFFFFF`）/ `now_ns`（QPC，先除后乘再补余数避免溢出） |

新增 IAT 内置槽 3 个（`GetFileAttributesA` / `QueryPerformanceCounter` /
`QueryPerformanceFrequency`），`I_USER` 7 → 10；新增 IR 指令 `OP_LOAD8` / `OP_STORE8`。

### ③ `s[i]` 字符串下标（按字节）

之前只支持 vec/数组/切片下标。str 下标是"第 i 个字节（0..255）"：`_addr_index` 里
特判 `TY_STR` → `s + i`，地址标成 `TY_BYTE`，读写分别走 `LOAD8`/`STORE8`；越界
fail-fast（与 vec 同口径）。qlmc 自己的词法器全是 `src[i]`，没有这条根本编不动。

### ④ 聚合值可以直接当左值基址

`nodes.get(i).op` / `mk(...).x` 这种"对调用结果取字段"以前报「这个表达式不能取地址」。
按既有约定「聚合值 = 区域地址」，`_addr_of` 的兜底分支改成：类型是聚合就
`_lower_expr` 拿地址。qlmc 自己的源码里这种写法成百上千处。

### ⑤ 两处源码改写（落在自己支持的子集里）

- `args()` → `_args()`：用 `GetCommandLineA` + 30 行 Quelmara 切参数（跳过 argv[0]、
  支持双引号）。做成内建要写上百条机器码，不划算。
- `read_text()` → `_read_text()`：复用已有的 `CreateFileA`/`ReadFile` 的 @ffi 声明。
- `net_config(2)` → 固定 4：qlmc 没有配置解析器。**线程数不影响产物字节**（`-j1 == -jN`
  有测试钉住），所以只影响构建耗时。

## 又抓到三个真 bug

### ① 摆实参必须「先栈后寄存器」（坑表 #32）

`ReadFile(h, buf, sz, got, 0)` 的第 5 个实参被写成了 `sz` —— 反汇编里是
`mov [rsp+0x20], r8`，而 r8 刚被**上一个实参**（`mov r8, r12`）覆盖。栈实参的值
可能正躺在 R8/R9（临时值寄存器）里，而 `OP_ARG` 会写 R8/R9。改成先写全部 STKARG、
再摆 ARG。现象是 `lpOverlapped = 226`，进程崩在 WriteFile 里，fault_probe 报「写 0xE2」。

### ② `__memcmp` 的 SIB 字节写错

`movzx eax, byte [rcx + r9]` 的 SIB 应是 `0x09`（scale=1, index=r9, base=rcx），
写成了 `0x08`（base=rax）→ 从野指针读，段错误。

### ③ 帧的变量槽从 256 提到 384

`build_rdata` 需要 257 格，只差一格。帧仍是 4 KB（512 格），临时值区剩 128 格。
**不要靠加帧来扩**：帧 > 4 KB 必须做栈探测（§7.17），qlmc 还没做。

顺带把「超出帧」的错误消息补上了**当前函数名和已用/需要的槽数**（新增 `C_CFI` 单元）。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=51**（24 组用例 + 并行确定性 2 条；新增 `s20_mem`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s20_mem.qma` | 31 行输出与 stage-0 逐字节相同：字节/字读写、清零/拷贝/比较、`mem_str`/`chr`/`substr`/`cstr`、`int.to_str`/`str.to_int`、`file_exists`、`now_ns` 单调性 |
| 自编译 | 产出 417 792 字节 stage-2（143–192 ms，`-j4`） |
| 性能 | `s3_manyfns` 17.5–18.5 ms（基线内） |
| 三禁 | 全绿 |

## 顺带发现一个 stage-0 的 bug（§7.21，归对方修）

```quelmara
while i < 4 { mem_store8(p, i, i); i = i + 1 }   // stage-0 写 0 0 0 0；qlmc 写 0 1 2 3（对）
```

触发条件是「循环 + 变量下标 + 变量值」；常量值或常量下标都没事，循环外也没事。
影响任何「用循环按下标填缓冲区」的代码。夹具 `s20_mem.qma` 为此把循环里改成只存常量。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `_dir_up`/`_find_module`；`_lower_builtin`（16 个内建）；`TY_BYTE` + str 下标；`_addr_of` 聚合兜底；`OP_LOAD8`/`OP_STORE8`；`RT_EPRINT`/`RT_MEMCMP`/`RT_I64FMT`/`RT_STR2INT` 四个运行库例程；IAT 加 3 个符号；`_emit_call_args` 先栈后寄存器；`_bi_mem_str`；`_args`/`_read_text`/`_pick_threads` 改写；`SLOT_TEMP` 256→384；`C_CFI`；`__memcmp` SIB 修正 |
| `tests/selfhost/s20_mem.qma` | **新增**：内存/串/诊断内建差分夹具 |
| `tests/qlmc_test.py` | 用例 23 → 24 |
| `docs/05-toolchain.md` | §1.11 改 S19；内建表全重写；坑表补 #32（先栈后寄存器） |
| `docs/07-gaps.md` | §3 stage-1 行（含自举状态）；**新增 §7.21**（stage-0 循环 store8 bug） |
| `docs/06-status.md` | §3.25 加 s20/自编译行、体积与自举状态 |

## 已知边界

- stage-2 **还不能用**（见开头表格）。这是下一版的唯一任务。
- `mem_free` 是空操作（bump 分配器不回收）——与 stage-0 的行为差异，见 §7.20 待补。
- `cstr` 是恒等（qlmc 的 str 自带 NUL）；stage-0 会新分配一份，语义等价（调用方只读）。
- `now_ns` 走 QPC，每次调用新分配 16 字节（不回收）。
- 仍然缺：f64、泛型、宏/反射、接口、`rc`/`Drop`、闭包捕获、`vec[vec[T]]`、map 扩容。
