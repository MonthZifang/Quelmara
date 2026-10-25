# v2.32 — `spawn` / `join`（真线程），子集 S18

- 日期：2026-10-25
- 任务：**`spawn` / `join`** —— 上一版结尾定位出的"自举第五个硬阻塞"
- 影响面：自举层（qlmc 语法/降级/IR/发射器/运行库/导入表）/ 测试 / 文档

## 主事件：spawn/join 跑真线程

```quelmara
fn work(n: int) -> int { ... }
let h = spawn work(1000)     // 任务句柄
print(join(h))               // 等它跑完并取返回值
```

| 环节 | 做法 |
|---|---|
| 参数块 | `[0]=返回值 [1]=目标函数地址 [2]=实参个数 [3+i]=实参`（`32+8n` 字节，多给 8 字节余量） |
| 起线程 | `CreateThread(0, 0, &__spawn_entry, blk, 0, 0)` —— 6 个实参，后两个走 v2.29 的栈实参 |
| 句柄 | 再分配 16 字节：`[0]=线程句柄 [1]=参数块`，句柄值 = 这块的地址 |
| join | `WaitForSingleObject(tid, -1)` → `CloseHandle` → 读 `blk[0]` |
| 线程入口 | `__spawn_entry`：从块里取"函数地址 + 实参个数"，按 Win64 摆好寄存器/栈实参，`call [rbx+8]`，把结果写回 `blk[0]` |

**为什么只做一个通用入口**：函数体是**并行编译**的，spawn 站点在发射期才知道，
没法往顺序段里追加"每个站点一个入口例程"。所以把"目标函数地址 + 实参个数"塞进
块里，一个入口吃所有形状（0/1/2/5/8 实参都验过）。

入口的三个要点：
1. 入口没有序言，`rsp` 进来是 ≡8(mod 16) → 先 `push rbp` 抬成 ≡0，
   后面 `sub rsp, stk`（16 的倍数）才能保持对齐；
2. 栈实参放 `[rsp + 8*i]`——调用方约定是 `[rsp+32+8*(i-4)]`，两者相等；
3. `rbx` 存块指针（callee-saved，跨 `call [rbx+8]` 安全），收尾 `mov rsp, rbp`。

新增：关键字 `spawn`、AST 节点 `E_SPAWN`、`join` 内建、IR 指令 `OP_RTADDR`
（取运行库例程地址，FK_RT 回填）、运行库 `RT_JOIN` / `RT_SPAWN`、三个 kernel32
导入（CreateThread / WaitForSingleObject / CloseHandle，IAT 内置槽 4→7）。

## 撞出来并修掉的两个真 bug

### ① `[base+disp]` 的基址是 RSP/R12 时没发 SIB —— 整条指令错位

第一版 `spawn` 编出来的代码是这样的：

```
lea      r9, [r8 + rax + 0x4c000000]     ← 期待 lea r9,[r12]
mov      eax, ecx
mov      qword ptr [rax], rcx
```

因为 `_lea_rm` / `_mov_load` / `_mov_store` 都用 `_modrm(mod=2, reg, base)` 直出，
而 ModRM 的 **rm=100 是"SIB 跟在后面"的标记**：base 是 RSP 或 R12 时必须补一个
SIB 字节，否则 disp32 的第一个字节会被当成 SIB 解析，**整条指令连同后面全部错位**。
以前没炸是因为基址一直是 RBP；`_lower_spawn` 用了 4 个 pin，第二个正好落到 R12。
现在统一走 `_modrm_mem`（`(base & 7) == 4` 时走 `_modrm_sib`）。

### ② `iat` 表大小写死 4 个内置槽

加完三个内置导入后，`iat` 还是 `4 + len(fsym)` 大小 → 编译期
`vec index out of bounds`（连 `print(1)` 都编不过）。改成 `I_USER + len(fsym)`，
**用 `I_USER` 推，不再写死**。

## 一个更麻烦的发现：stage-0 的"性能层面布局敏感"

第一版通过全部测试，但 `s3_manyfns`（96 KB / 200 函数）的编译耗时从 **17.8 ms
涨到 32–34 ms（1.8×）**，前后端一起变慢。排查过程：

| 试的假设 | 结果 |
|---|---|
| `_modrm_mem` 多了一层调用 / `(base&7)` 分支 | 去掉仍 30 ms ✗ |
| 两个新运行库例程撑大了 `.text` | 不生成仍 30 ms ✗ |
| 挪 `_lower_spawn` 到文件末尾（位置） | 仍 32 ms ✗ |
| 删掉 `_lower_spawn`（整个函数） | **18 ms ✓** |
| 把它缩成空壳 | 18–20 ms ✓ |
| 逐个替换里面的 `_ty_is_agg` / `_call_args` / `_fn_index` 调用 | 都还慢 ✗ |
| **去掉两处 `eprint("…" + expr)` 字符串拼接** | **18.7 ms ✓** |

也就是说：一个**从不执行**的函数里，两处错误消息的字符串拼接，能让整个编译器慢
1.8 倍。而且**不单调**——同一函数体只留前 3 行（含拼接）慢，多留 10 行反而快。

这是 §7.17 那个"布局敏感误编译"的性能版本（那次是崩溃，这次只是慢）。修法只能是
"换个写法落到快档"，所以纪律是：**改完 `qlmc.qma` 必须量 `s3_manyfns` 的编译耗时
（`-j1`，min of 3）**——它是唯一能发现这类回退的判据。已写进坑表 #31。

代价：这两条错误消息不再带具体函数名/个数。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=49**（23 组用例 + 并行确定性 2 条；新增 `s19_spawn`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s19_spawn.qma` | 8 行输出与 stage-0 逐字节相同：0/1/2/5/8 实参、先 spawn 两个再按序 join、主线程对照 |
| 性能 | `s3_manyfns` **17.3–18.7 ms**（v2.31 17.8–18.5 ms，差在噪声内） |

## 自举进度：第五个阻塞已清，下一个是 import 源根目录

```
$ ./qlmc.exe build bootstrap/qlmc/qlmc.qma -o build/self.exe
（v2.31）qlmc: line 6146: 期望标点 #2        ← 已清
（v2.32）qlmc: 找不到模块 bootstrap/qlmc/std/core.qma   ← 下一个
```

qlmc 自己的源码开头是 `import std.core` / `import std.mem`。qlmc 的 import 解析是
**只看源文件同目录**（`_dir_of(src) + mod + ".qma"`），而 stage-0 按 `Quelmara.toml`
的 `[src] lib` 源根解析。**下一版做"import 走源根"**：读配置的 `[src] lib/ref`
（或者退一步：从源文件目录逐级向上找 `std/`），再按 `a.b.c` → `a/b/c.qma` 拼。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `spawn` 关键字/`E_SPAWN`/`join` 内建/`_lower_spawn`；`OP_RTADDR` + 发射器；`RT_JOIN`/`RT_SPAWN` 两个手写例程；IAT 加 3 个 kernel32 符号（`I_USER` 4→7）；**`_modrm_mem`（RSP/R12 的 SIB）**；`iat` 表按 `I_USER` 推；`rt_pos` 9→11；`_call_node` 抽出供 `E_CALL`/`E_SPAWN` 共用 |
| `tests/selfhost/s19_spawn.qma` | **新增**：spawn/join 差分夹具 |
| `tests/qlmc_test.py` | 用例 22 → 23 |
| `docs/05-toolchain.md` | §1.11 改 S18；语句表加 spawn/join；不支持表换成「import 源根」；坑表补 #30（SIB）/ #31（stage-0 性能敏感） |
| `docs/07-gaps.md` | §3 stage-1 行更新 |
| `docs/06-status.md` | §3.25 加 `s19` 行、体积/耗时、新增"性能层面布局敏感"实测表 |

## 已知边界

- `spawn` 的目标必须是**用户函数**（不能是 `@ffi` 声明），返回值和实参不支持聚合；
  `str` 返回值也不支持（与 stage-0 同口径）。
- 不支持 stage-0 的 `spawn f(x).join()` 脱糖写法——用 `join(spawn f(x))`。
- 没有"单核降级"：qlmc 不看 `Quelmara.toml` 的 `multicore`，永远起真线程。
  差分跑的是默认配置（multicore=true），所以两边一致。
- 句柄不回收（`join` 会 CloseHandle 线程句柄，但 16 字节的句柄记录和参数块留在堆上）。
- 仍然缺：`import` 源根目录、f64、泛型、宏/反射、接口、`rc`/`Drop`、闭包捕获、
  `vec[vec[T]]`（§7.18）、map 扩容、`mk(...).x`（对调用结果取字段）。
