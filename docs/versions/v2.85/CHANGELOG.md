# v2.85 — 修 qlmc「每次编译错误都 SIGSEGV」（§7.34）

- 日期：2026-10-27
- 任务：修编译器的**用户可见崩溃**
- 影响面：`bootstrap/qlmc/qlmc.qma`（`_fail` 的退出路径）、`docs/07-gaps.md §7.34`

## 症状

```
$ build/qlmc.exe build bad.qma -o bad.exe
qlmc: line 3: 期望表达式
Segmentation fault (exit 139)
```

诊断打印得**完全正确**，然后进程访问违例。CI 判据只看退出码非零，所以一直没红 ——
但用户看到的是"编译器挂了"，不是"你的代码第 3 行有问题"。

## 排查：先把范围压小

用 `tools/dev/fault_probe.py` 拿到现场：AV 是**读地址 0xFFFFFFFFFFFFFFFF**，
Rip 落在**系统 DLL 的地址空间**（0x7FFD…），不在 qlmc 的映像里。

然后逐条排除：

| 试验 | 结果 | 结论 |
|---|---|---|
| `eprint` + `exit(2)` 的小程序（含深递归、含聚合形参） | 干净退出 | 不是 exit 本身 |
| `qlmc`（无参数）→ 打印用法 + `exit(2)` | rc=2，不崩 | 不是 eprint |
| `struct 重复声明` 的报错（浅层） | rc=2，不崩 | 不是 `_fail` 本身 |
| `to_str(2)` 的报错（lowering 阶段，也深） | rc=2，不崩 | 不是"深度" |
| **`let x = `（表达式解析器深处）** | **崩** | 只有这一条路径 |
| 把 `_fail` 改成"只 exit、不打印" | 仍然崩 | 与打印无关 |
| 各函数帧大小 | 全部 ≤ 0xC8（200 字节） | 不是栈溢出 |

排除到最后，剩下的解释只有一个：**`ExitProcess` 的进程关闭流程**
（`RtlExitUserProcess` → `LdrShutdownProcess` → 遍历模块表 + 逐个调 DLL 的
`DLL_PROCESS_DETACH`）在某条特定调用栈上会 AV。

## 改法

出错退出不走 `ExitProcess`，走 **`TerminateProcess(GetCurrentProcess(), code)`**：

```quelmara
fn _die(code: int) {
    _TerminateProcess(_GetCurrentProcess(), code)
    exit(code)                       // 万一 TerminateProcess 失败
}
```

`TerminateProcess` **不做** loader 的关闭流程，直接结束进程。

为什么这样做是安全的：qlmc 的 `print` / `eprint` 都直接 `WriteFile`，**没有缓冲
需要 flush**；出错路径也没有需要释放的资源（文件句柄在 `_read_text` 里已经关掉）。
编译器在"源码有语法错"这种场景下硬退出，语义上完全等价。

`_die` 只用在 `_fail`（语法/语义诊断）。正常结束仍走 `exit(0)`，其余
`exit(2)` 的路径（`没有 main`、`to_str 不接受实参`）实测不崩，保持原样。

## 验证

```
$ build/qlmc.exe dump bad3.qma        → rc=2（打印诊断，无崩溃）
$ build/qlmc.exe build t8.qma         → rc=2（嵌套 struct 字段：报错不崩）
$ build/qlmc.exe build nomain.qma     → rc=2
$ build/qlmc.exe build dup.qma        → rc=2
```

qlmc 差分 **PASS=65 FAIL=0**（新加的两个 `@ffi` 导入没有影响产物）。

## 诚实说明：根因没定位

这一版修的是**症状**。loader 的关闭流程为什么在那条栈上会崩，仍然不知道 ——
已知它不依赖：栈深度、聚合形参、`eprint`、退出码数值。要继续挖需要
`cdb`/WinDbg 看 DLL 里那条指令的上下文，本机没有。

记在这里，免得下次以为"已经彻底修好了"。

**判据已经补进测试**：`tests/qlmc_test.py` 开头加了一条"错误路径"——
编一个语法错的源文件，要求 **rc=2 且 stderr 带诊断**（崩溃是 0xC0000005 /
139，不是 2）。这条以前没有，所以 §7.34 潜伏了三个版本没人发现：
**"编译器出错时的行为"本身就该有测试**，不能只测成功路径。
