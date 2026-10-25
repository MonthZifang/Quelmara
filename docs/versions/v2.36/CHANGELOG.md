# v2.36 — `__spawn_entry` 的 ABI 修复；`-jN` 与错误路径两个缺陷定性

- 日期：2026-10-25
- 任务：攻 §7.24（`-jN` 编自己崩）
- 影响面：自举层（线程入口 ABI）/ 文档

## 修掉的：`__spawn_entry` 不保存非易失寄存器

线程回调也是一个"函数"，`BaseThreadInitThunk` 在它返回后还会用到非易失寄存器。
`__spawn_entry` 直接把 **rbx** 当块指针、**r12** 当栈大小用，**进出都没保存** ——
这是 ABI 违规。补上 `push rbx / push r12` 与对应的 pop。

```asm
push rbp
push rbx        ; ← v2.36 新增
push r12        ; ← v2.36 新增
mov  rbp, rsp
mov  rbx, rcx   ; 块指针
...
mov  rsp, rbp
pop  r12
pop  rbx
pop  rbp
ret
```

**诚实说明**：这个修复本身是对的（违规就是违规），但它**没有**修好 `-jN` 编自己
（见下）。所以这一版的主线成果是"把一个真 ABI bug 修掉 + 把两个缺陷定性到可交接"。

## 未达成：`-jN` 编自己仍崩（§7.24 更新）

`-j1` 不动点仍然成立（stage-2 == stage-3）。`-j2` / `-j4` 编 qlmc 自己仍段错误，
但这轮把范围缩到了很具体的位置：

用带线程号与阶段日志的调试版（`-j4`）追到：

```
T2 194 a → b → c → d → e → f     # 线程 2 的最后一个函数（fi=194）走完全部阶段
T2 loop done                      # 循环正常结束
WD1 / WD0 / WD3 / WD2            # 四个线程都从 _compile_range 返回
JOINED                            # main 的 join 全部成功
（然后崩）
```

所以**不是**编译逻辑、不是 arena、不是 join；崩在**线程退出后的清理路径**上
（`fault_probe` 的 `Rsp` 落在工作线程的栈区，返回地址在 DLL 帧里）。
已排除：堆耗尽（修正越界上限后仍崩且没触发 exit 3）、每线程 arena 不足
（8 MB 仍崩）、栈不够（`SizeOfStackReserve` 调到 8 MB 仍崩）、线程竞争
（`__alloc` 已加自旋锁，且 `-j1` 也曾经崩）。

## 新发现并定性：报语法错误后崩在 exit（§7.25）

```bash
$ ./qlmc.exe build bad.qma -o bad.exe
qlmc: line 3: 期望表达式
Segmentation fault          # 期望 rc=2
```

- **既有缺陷，不是这版引入的**：用 `HEAD` 的源码编出来的 qlmc 同样崩。
- 消息打印成功，崩在随后的 `exit(2)` 上。
- 触发条件缩小到 **`eprint(<含 sret 聚合调用的多段拼接>)`**：
  `eprint("…" + _cur(p,pos).line.to_str() + "…")` 崩，而 `eprint(单段拼接)`、
  `print(同样的表达式)`、`assert` 失败走 `__die` 都正常。
- **布局敏感性极强**：同一份源码、只改一处无关代码，rc 就在 139 与 2 之间跳。
  这轮试过的四种"修法"都只在某些布局下有效，所以**一个都没留下**（不把运气当修复）。
- 已把证据、排除项和建议的下一步（逐条对照 `print` 版与 `eprint` 版的产物，
  看 sret 隐藏指针与 `OP_ARG` 抢 RCX 的寄存器分配）写进 §7.25。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/bootstrap_test.py --strict` | **三级全 PASS**（不动点 `-j1` 仍成立） |
| `python tests/qlmc_test.py` | **PASS=51** |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| 四道门 | 全绿 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `__spawn_entry` 保存/恢复 `rbx`、`r12`（+10 行） |
| `docs/07-gaps.md` | §7.24 补这轮的定位过程与排除项；**新增 §7.25**（错误路径崩溃，含布局敏感性表与下一步建议） |

## 下一步（建议按此顺序）

1. **§7.25 错误路径崩溃** —— 影响所有语法错误的报告，用户可感知，优先级最高。
2. **§7.24 `-jN` 编自己** —— 只影响"多线程自编译"这一种用法。
3. 然后回到功能：f64 / 泛型 / 接口 / `rc`。
