# v3.94 — qlmc 自研 ELF64 后端（Linux 平台缺口收口）

- 日期：2026-11-03
- 任务：让 qlmc 能产出 Linux 可执行文件 —— 这是"在 Linux 上和 C/Go 同台对比"的前提。
- 结论：**成功**。`qlmc build x.qma --target elf -o x` 产出可直接 `execve` 的静态 ELF64。
- 影响面：`bootstrap/qlmc/qlmc.qma`（新后端，约 300 行）、`docs/07-gaps.md` §4、
  `docs/06-status.md`

## 为什么要这个后端

在此之前 qlmc **只能产 PE**。而基准对比环境是 Linux —— CI 的 ubuntu job 里
`quelmara` 那一列一直是空的，只能跑 `quelmara0`（stage-0 的 ELF 后端）。

**这意味着 qlmc 一项都进不了 Linux 侧的 45 项对比。** 补上这个后端是前提。

## 全部用 Quelmara 自己写

**没有调用 Python、没有调用外部汇编器或链接器。** ELF 头、段表、syscall 版
运行库全部在 `bootstrap/qlmc/qlmc.qma` 里用 Quelmara 实现：

* `build_elf()` —— ELF64 ehdr(64B) + phdr(56B) + 代码/数据，**单 RWX PT_LOAD、
  无重定位、无动态链接器**。`p_memsz > p_filesz` 的那部分由内核补零（就是 .bss）。
* `_syscall()` —— `0F 05` 编码器。
* `_gen_entry_elf` / `_gen_print_i64_elf` / `_gen_print_str_elf` /
  `_gen_print_bool_elf` / `_gen_eprint_str_elf` / `_gen_i64_fmt_elf` ——
  Linux 版运行库。

**stage-0 的 ELF 后端只用于差分对拍**（`--target native`），不作为实现来源。

## 关键设计：两条后端共享 99% 的代码

机器码本身（x86-64）是同一套，所以 **IR / 优化器 / 线性扫描分配器 / 指令编码
全部共用**。只有两处分叉：

1. **外层容器**：`build_pe` vs `build_elf`
2. **与操作系统打交道的 6 个运行库例程**：PE 走
   `GetStdHandle`/`WriteFile`/`wsprintfA`/`ExitProcess`，ELF 走 `syscall`

其余运行库（memcpy / alloc / str_cat / f64 / 原子操作 / 内存函数）**完全共用**。

为了让回填逻辑通用，`_target_of` / `resolve_seq` / `resolve_fn` 都加了一个
`text_base` 参数：PE 是 `TEXT_RVA`(0x1000)，ELF 是 `ELF_ENTRY_OFF`(0x78)。

## 自己实现整数格式化

PE 版的 `RT_I64FMT` 靠 `wsprintfA("%I64d")` —— Linux 上没有这个 API。
所以 `_gen_i64_fmt_elf` **完全用机器码自己算**：除 10 取余、从临时区尾部往前填、
再挪到 buf 开头。

**符号处理**：先判符号（`test/jns`），负数先写 `'-'` 再 `neg`。不用"先取绝对值
再判号"——那样 `INT64_MIN` 会溢出（§7.19 的老坑）；`neg` 对 INT64_MIN 正好
得到 2^63 的无符号位模式，配合**无符号 `div`** 正确。

## 踩到的三个坑（都是手写机器码的经典错误）

### ① `lea` 的 fixup 位置错了

```quelmara
_lea_rip(code, RSI, 0)      // 一次写完整 7 字节
let at = len(code)          // ← 错！这已经是指令末尾
_w32(code, 0)
```

`_lea_rip` 写完后 `len(code)` 指向**下一条指令**，回填会改掉别人的操作数。
现象：`hello elf` 打印出来了但换行没出来，随后段错误。
正确写法是 `let at = len(code) + 3`（REX + 8D + ModRM 之后）。

### ② 8 位操作多加了 REX.W

`add dl, 48` 应是 `80 C2 30`，我写了 `48 80 C2 30`。REX.W 会让 CPU 按
64 位解析后续字节，得到完全不同的指令。

### ③ 长度没算符号位

`print(-12345)` 打成 `-1234` —— 数字的起始指针 `rdi` 已经因为写 `-` 而
`inc` 了一格，但返回的长度只算了数字位数。**每一位负数都少一位**：
`-1` → `-`，`-12` → `-1`。

这个 bug 还有个陷阱：`rcx` 在函数中途被 `mov rcx, 10`（除法用）覆盖了，
所以算 `rdi - buf` 时不能直接用 `rcx` —— 必须在入口把 buf 原值存栈。

## 验证

| 项 | 结果 |
|---|---|
| `hello.qma` | `hello elf` / `42`，rc=0 |
| 负数边界（-1/-9/-10/-1234/-12345/-123456） | 全部正确 |
| 循环/取模/`(i*7)%13` 累加 100 次 | `590`，与 stage-0 逐字节一致 |
| `tests/selfhost/s1_basics.qma` | `s1 basics` / `42` |
| `tests/selfhost/s7_aggfn.qma` | `3` / `11` |
| **PE 回归** `tests/qlmc_test.py` | **PASS=110 FAIL=0**（无回归） |
| **自举链** `tests/bootstrap_test.py` | 1/2/2.5 级 PASS，产物逐字节等价 |

## 下一步

ELF 后端目前**还没接** `spawn`/`join`（用的是 PE 的 `CreateThread`）和
`@ffi`/文件/网络（都是 Windows API）。基准里 `b8_threads*` 会用到线程，
其余 9 项纯计算的不受影响 —— 所以先把纯计算的基准跑起来，线程类后续补。
