# v3.19 — 编译期目标探测 `target_os()` / `target_arch()` + Linux futex park

- 日期：2026-10-30
- 任务：用户要求"继续"；v3.18 补了 `syscall` 内建后，Linux futex 只剩
  "编号架构相关 + 无条件编译"这一条障碍
- 影响面：**编译器**（两个编译期常量内建）、标准库（新增 `std/park_linux`）、
  测试（新增 `t172`、`irdiff` 归一化规则）、文档

## 问题：库层没法知道自己在给哪个目标编译

`syscall`（v3.18）的调用号是**架构 + OS 相关**的：

| 调用 | x86-64 Linux | AArch64 Linux |
|---|---|---|
| `futex` | 202 | 98 |

而语言没有条件编译，编译器内部的 `self.platform` / `self.arch` 也**没有暴露
给用户代码**。于是标准库要写"按目标选常量"只能靠猜或写两份源码。

## 改动一：两个编译期常量内建

```quelmara
target_os()   -> 1 = Linux / 2 = Windows
target_arch() -> 1 = x86_64 / 2 = aarch64
```

**它们返回编译期立即数**，所以 `if target_arch() == 2 { ... }` 里的比较
在编译期就折叠成常量真假。IR 证据（`--dump-ir`）：

```
== f (vregs=0) ==
    ('jcc', 'ne', ('imm', 1), ('imm', 2), 'f.ielse.2')   ← target_arch() 折叠成 imm 1
```

对比同一份源码在 a64 上折叠成 `('imm', 2)`。

**它们不能用在 `const` 右值里**：`const IS_LINUX = target_os() == 1` 会报
`const 右值里只能调用 const fn`。原因是 `const` 求值在 `qlm.py` 的 parser 里，
而**parser 不知道 target**（那是架构无关的）。让 parser 感知目标会污染它的
定位，所以本版**不做**；代价是这些常量只能内联写在使用点。

**它们不是条件编译**。这一点必须说清楚：
`@ffi` 与 `syscall` 各自在对方的后端上是**声明期硬失败**，`if` 守卫救不了声明本身。
实测：

```quelmara
@ffi("KernelBase.dll", "WaitOnAddress")
fn _WaitOnAddress(...)
fn main() {
    if target_os() == 2 { _WaitOnAddress(...) }   // 守卫在调用点
}
```

`--target native` 仍然报 `@ffi 只在 Windows PE 后端实现`。**所以 `target_os()`
只能用来"选常量"，不能用来"剔掉某个后端根本不存在的声明"。**

## 改动二：`std/park_linux` —— Linux 的 futex park

既然守卫救不了声明，跨平台 park 只能**拆文件**（与 v3.16 把 `std/park` 从
`std/sync` 拆出来是同一个理由）：

| 文件 | 后端 | 实现 |
|---|---|---|
| `std/park` | 仅 Windows PE | `WaitOnAddress` / `WakeByAddressAll`（`@ffi`） |
| `std/park_linux` | 仅 Linux | `futex(2)`（`syscall`） |

**同一组 API**：`park_available()` / `park_on(p, want, ms)` / `wake_all(p)` /
`wake_one(p)`。调用方按目标 import 其中一个。

`futex` 与 `WaitOnAddress` 的三处实质差异：

| 项 | `WaitOnAddress` | `futex` |
|---|---|---|
| 比较值 | **另一个指针**里的值 | **直接传整数** |
| 超时 | `DWORD ms` | `struct timespec *`（相对时间） |
| 返回值 | `BOOL` | `0` / `-EAGAIN`（值不匹配）/ `-EINTR` |

**超时被忽略**（传 `NULL` = 永久等待）。这是刻意的：拼 `timespec` 要两条
store + 一次换算，而调用方（`std/sync.wg_wait`）本来就用"谓词复查"兜底，
不依赖 park 超时。**要超时支持得先补 timespec 构造**，已登记 07-gaps。

**`-EAGAIN` 也算"被唤醒"**：它表示"值已经变了、我没睡"，语义上等价于
"条件满足，该回去重查了"。只有 `-EINTR` 与其它负值才返回 0。

## 改动三：`irdiff` 归一化规则扩展（顺带发现的真问题）

加完 `target_os()`/`target_arch()` 后，**`irdiff` 会判分叉** ——
因为它要求两个后端产出逐字节相同的 IR，而这两个内建按定义就返回不同值。
实测（用探针 `tests/probe_irdiff_target.qma`）：

```
[FAIL] tests/probe_irdiff_target.qma: x86 360 行 / a64 360 行
```

**这不是 bug，是 `irdiff` 的契约需要更新**：它原本只归一化 `syscall` 编号
（"唯一允许的架构差异"），现在多了一类。

新增 `TARGET_IMM_RE`，**只匹配特征形态**（`jcc` 里两个 `imm` 做 `ne`/`eq`
比较），不碰普通常量。四条单元判据：

| 判据 | 结果 |
|---|---|
| `target_arch()` 折叠形态归一化后相同 | ✅ |
| 普通常量差异（`('imm', 98)` vs `('imm', 202)`）**仍能分叉** | ✅ |
| 变量比较不受影响 | ✅ |
| `syscall` 编号归一化未退化 | ✅ |

归一化后 `irdiff` **PASS=108 FAIL=0**（探针加入时 109，移除后回到 108）。

## 验证

| 命令 | 结果 |
|---|---|
| `build probe_target --target win` 执行 | `os=2 arch=1`，`is_win=1 is_x64=1` |
| `build probe_target --target arm64` + 模拟器 | `os=1 arch=2`，`is_linux=1 is_a64=1` |
| IR 折叠验证（`--dump-ir`） | `__str_from_i64` 的参数直接是 `('imm', 2)` / `('imm', 1)` —— 无运行期调用 |
| `build t172_park_linux --target native` | 编过（16617 B，ELF x86_64） |
| `build t172_park_linux --target win` | **编译期 fail-fast**（`syscall` 不支持 Windows） |
| `python tests/irdiff.py` | **PASS=108 FAIL=0 SKIP=92** |
| `python tests/run_win_tests.py` | **PASS=333 FAIL=0 SKIP=0** |

**`t172` 只接进 CI 的 linux job（x86-64），不接 a64**：AArch64 没有 `spawn`，
而 park 的验证必须有第二个线程来唤醒。这不是遗漏，是能力边界。

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 新增 `target_os()` / `target_arch()`（编译期立即数） |
| `std/park_linux.qma` | 新增：futex 版 park（`park_available`/`park_on`/`wake_all`/`wake_one`） |
| `tests/t172_park_linux.qma` | 新增：4 组断言（真唤醒 / 延迟 / 可见性 / 反复 spawn） |
| `tests/run_native_tests.sh` | `[7]` 段接入 t172（仅 x86-64） |
| `tests/irdiff.py` | 新增 `TARGET_IMM_RE` 归一化 + 契约说明 |
| `docs/02-language.md` | 内建表新增两个目标探测内建 |
| `docs/06-status.md` | 新增 §3.69 |
| `docs/07-gaps.md` | §5 的 Linux futex → ✅；§4 更新 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.19.0 |

## 已知边界 / 遗留

- **仍然没有真正的条件编译**。`target_os()`/`target_arch()` 只解决"选对常量"，
  不解决"某个分支在这个后端根本不存在"。`@ffi` / `syscall` 的声明期硬失败
  仍然要靠"拆文件 + 调用方按目标 import"。真做条件编译是语言层设计
  （`02-language.md`），影响面比这一版大得多。
- **`const` 右值里用不了**这两个内建（parser 不知道 target）。要支持得让
  parser 感知目标，或把 `const` 求值挪到 lowering 阶段 —— 两个都是架构改动。
- **`std/park_linux` 没有超时**（`futex` 的 `timespec` 没拼）。调用方靠谓词复查
  兜底，所以不会挂死；但"等 100 ms 就走"这种语义做不到。要补得先做 timespec 构造。
- **`futex` 只比较 32 位**（`int`），我们的计数是 64 位。等待方传的 `want` 是
  "刚读到的非零值"，低 32 位足够区分（从 N 减到 0 时低 32 位必变）。
  但如果将来有人用"高 32 位变化、低 32 位不变"的计数，`futex` 会误判 ——
  这是 futex 的固有约束，已在模块头注明。
- **`t172` 没有真正跑过**：本机是 Windows，跑不了 Linux ELF。编过了、
  ELF 头对（x86_64）、但执行级验证要等 CI。这是"本机能过 ≠ CI 能过"的
  又一处 —— 至少它进了 CI，不是只写在本机（v3.16 的教训）。
- **`irdiff` 的归一化放宽了契约**。它现在会抹掉 `jcc` 里两个 `imm` 的比较，
  理论上掩盖面存在。实践上：① 这个形态只在"比较目标常量"时出现；
  ② 其余 100+ 个对拍文件没有这个模式（加了探针才 109，移除后 108，全是 PASS）。
  如果将来有人写出"用普通常量做 ne/eq 比较"的代码，会被这条规则掩盖 ——
  届时应该收紧成"只匹配 target 折叠的特定值域"。
