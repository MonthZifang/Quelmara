# v3.18 — 用户可调的 `syscall(n, a0..a5)` 内建：Linux 侧的最后一格地基

- 日期：2026-10-30
- 任务：用户要求"继续"；v3.17 查清 Linux futex 被"语言层缺能力"挡住后，
  补上那个能力
- 影响面：**编译器**（新内建 `syscall`）、测试（新增 `tests/t171_syscall.qma`
  接进 CI linux job；`tests/a64_emu.py` 语义修正）、文档

## 问题：`syscall` 只是内部发射指令，用户发不了系统调用

v3.17 查 Linux futex 时发现三堵墙，第一堵就是：

```python
fn.emit("syscall", None, self.sc["write"], ...)   # 编译器自己用
```

`syscall` 在 `qlm_native.py` 里是**内部 IR 指令**，没有任何用户可调的内建入口。
于是标准库只能通过 `@ffi` 调外部函数 —— 而 `@ffi` 在 ELF 后端是声明期硬失败
（ELF 是静态可执行文件、无 `PT_INTERP`、外部符号无处解析）。

**结果**：Linux 侧的 futex / io_uring / 新 socket 选项 / 任何内核新接口全都做不了。
`std/park` 只能 Windows（v3.16 的拆法就是被这个逼出来的）。

## 改动

### 1. 新内建 `syscall(n, a0..a5) -> int`

| 项 | 语义 |
|---|---|
| 调用号 | `n`，**必须是编译期常量** |
| 实参 | 最多 6 个（不足补 0） |
| 返回 | 内核**原样**返回值；负值即 `-errno`（**不置 errno、不抛异常**） |
| 平台 | **仅 Linux**（native / arm64）；Windows 编译期 fail-fast |

寄存器约定按各自 ABI：

- x86-64：`rax`=编号，`rdi/rsi/rdx/r10/r8/r9`=参数，`syscall` 指令，结果在 `rax`
- AArch64：`x8`=编号，`x0..x5`=参数，`svc #0`，结果在 `x0`

**为什么调用号必须是常量**：内核在 `rax`/`x8` 里读它，允许运行期值没有意义；
更重要的是**编号笔误应该在编译期抓出来**，而不是运行期收到一个 `-ENOSYS` 慢慢查。
（这条约束当场就抓到了我自己的探针 —— 见下。）

**为什么不做编号白名单**：内核会拒绝非法编号并返回 `-ENOSYS`，这与 C 里直接
`syscall(2)` 一致。安全边界由操作系统提供，编译器不该假装自己更懂。

**为什么 Windows fail-fast 而不是"产出能编过但会崩的可执行文件"**：
Windows 用户态不能直接发 `syscall` 指令（要过 ntdll 的 stub），产出一个会崩的
二进制比编译期报错糟得多。诊断信息里直接指路：*要调 Win32 API 请用 `@ffi`*。

### 2. `tests/t171_syscall.qma`（新增）

三组断言，都用**两个架构的编号各试一次**（因为编号是架构相关的，见边界）：

| 组 | 内容 | 判据 |
|---|---|---|
| `[1]` | `getpid`（x64=39 / a64=172） | 返回值 > 0 且两次一致 |
| `[2]` | `write`（x64=1 / a64=64）写一行到 stdout | 返回字节数 == `len(msg)` |
| `[3]` | 非法编号 9999 | **返回负值**（`-ENOSYS`），不是崩溃 |

接进 **CI 的 linux job**（`tests/run_native_tests.sh` 的 `[7]` 段），
x86-64 直接跑、AArch64 走模拟器。**主回归跑不了它** ——
主回归在 Windows 上，而 `syscall` 在 Windows 是编译期 fail-fast。

### 3. `tests/a64_emu.py` 语义修正（顺带发现的真问题）

模拟器原来是：

```python
else:
    raise RuntimeError(f"未实现 syscall {num}")
```

两个问题：

1. **与内核语义不符**：真实内核遇到非法编号返回 `-ENOSYS`，模拟器抛异常。
   `t171` 的 `[3]` 组会假红。
2. **更隐蔽**：**同一编号在不同架构上是不同的调用** ——
   `202` 在 x86-64 是 `futex`、在 AArch64 是 `accept`。探针按 x86 编号写，
   在 A64 模拟器上撞进这里，抛异常会让人以为是模拟器缺陷，
   其实只是"这个编号在 A64 上不存在/没实现"。

改成**一律返回 `-ENOSYS`**，`_KNOWN_UNIMPL` 降级为纯文档性列举（不再改变行为）。
另外补了 `getpid(172)` 与 `brk(214)` 两个实现（前者 `t171` 要用）。

## 验证

| 命令 | 结果 |
|---|---|
| `build tests/t171_syscall.qma --target native` | 编过（5188 B） |
| `build tests/t171_syscall.qma --target arm64` | 编过（9178 B） |
| `python tests/a64_emu.py build/t171_a64.elf` | `syscall ok` |
| `build tests/t171_syscall.qma --target win` | **编译期 fail-fast**，诊断指向 `@ffi` |
| `python tests/irdiff.py` | **PASS=108 FAIL=0 SKIP=91**（v3.17 是 89 PASS；`syscall` 编号在 IR 归一化里已被 `SYSCALL_RE` 处理，不产生分叉） |
| `python tests/a64_iface_test.py --quick` | PASS=6 FAIL=0（无回归） |
| `python tests/run_win_tests.py` | **PASS=333 FAIL=0 SKIP=0**（无回归） |

**futex 探针**（`build/probe_futex.qma`，未入库）：native 与 arm64 都编过；
a64 模拟器上 `202`/`98`/`9999` 全部返回 `-38`（`-ENOSYS`）—— 证明
**编号传进去了、返回值按 `-errno` 回来了**。真正的 futex 执行级验证要 Linux 机器。

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 新增 `syscall` 内建（常量调用号校验 + Windows fail-fast + 6 参补齐） |
| `tests/t171_syscall.qma` | 新增：三组断言，双架构编号各试 |
| `tests/run_native_tests.sh` | `[7]` 段接入 t171（x86-64 直跑 + A64 模拟器） |
| `tests/a64_emu.py` | 未实现调用号改返回 `-ENOSYS`；补 `getpid(172)` / `brk(214)` |
| `docs/02-language.md` | 内建函数表新增 `syscall` |
| `docs/06-status.md` | 新增 §3.68 |
| `docs/07-gaps.md` | §4 的 Linux futex 前置条件改为"已解除一半"；§5 更新 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.18.0 |

## 已知边界 / 遗留

- **编号是架构相关的，而语言没有条件编译**。futex 在 x86-64 是 `202`、
  在 AArch64 是 `98`；同一份源码**没法自动选对编号**，只能
  "两个常量都写、按返回值符号选"或由调用方按目标传。
  这是 `syscall` 最实际的限制，**不是实现缺陷** —— 要根治得做条件编译
  （`02-language.md` 的事）。
- **调用号必须是常量**，所以 `syscall(which, ...)` 传变量编不过。
  这是刻意的（编译期抓笔误），但意味着"运行期决定调哪个"做不到。
- **`syscall` 不做 ABI 转换**：实参必须是 `int`，指针要用 `mem_ptr` / `str_ptr`
  转；结构体（如 `timespec`、`iovec`）要自己用 `mem_alloc` + `mem_store` 拼。
  这一层是裸的，封装成好用的 API 是标准库的事。
- **Linux futex 本身还没做**。本版只补了地基；`std/park` 仍然只有 Windows 分支。
  下一步可以用 `syscall(202/98, ...)` 给 `std/park` 加 Linux 路径 ——
  但要解决"编号架构相关"的问题（上面的第一条）。
- **主回归覆盖不到 `syscall`**：它在 Windows 上 fail-fast。CI 的 linux job 才有
  执行级验证。这是 v3.16 那条教训（"验证矩阵少一格"）的延续 ——
  本版至少把它接进了 CI，不是只写在本机。
- **`_KNOWN_UNIMPL` 现在不改变行为**，只作文档。如果将来有人想靠它区分
  "我们没实现"与"编号非法"，得重新设计 —— 但内核本身也不区分，所以大概不该区分。
