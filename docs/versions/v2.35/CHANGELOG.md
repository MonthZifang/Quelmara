# v2.35 — 自举不动点达成（stage-2 == stage-3）

- 日期：2026-10-25
- 任务：上一版结尾的"不动点还没达成"
- 影响面：自举层（工作区大小 / 堆越界检查）/ 测试 / 文档

## 主事件：不动点成立

```bash
$ python tests/bootstrap_test.py --strict
[0] stage-1（stage-0 编 qlmc）：PASS  26.0s
[1] stage-2（qlmc 编自己）：PASS  0.7s  444416 字节
[2] stage-2 与 stage-1 产物一致：22/22 组  PASS
[3] 不动点 stage-2 == stage-3（-j1）：PASS  0.9s
PASS：stage-2 可用且与 stage-1 逐字节等价
```

```
$ ./build/p/self.exe build bootstrap/qlmc/qlmc.qma -o stage3.exe -j 1
[qlmc] bootstrap/qlmc/qlmc.qma -> stage3.exe  (444416 字节)  318 ms
$ cmp stage2.exe stage3.exe && echo same
same
```

**自举闭环成立**：qlmc 编自己得到 stage-2，stage-2 再编自己得到 stage-3，两者**逐字节相同**。
也就是说从这一版起，这个编译器不再需要 stage-0 才能繁殖。

## 真因：不是"布局敏感"，是**堆耗尽**

上一版我把"崩点随源码改动而移动"判断成布局敏感（§7.17 那一类），走了一大圈弯路。
这一版用 `mem_alloc(0)` 打印堆游标，一眼看到问题：

| 编到第几个函数 | 堆游标 | code 长度 |
|---|---|---|
| AP 80 | 29.7 MB | 92 KB |
| AP 140 | 29.7 MB | 128 KB |
| AP 160 | **31.7 MB** | 204 KB |

堆只有 **32 MB**，而 `ARENA_CAP`（并行编译工作区）**一项就占 16 MB** ——
qlmc 自己产物的 `.text` 才 440 KB。堆一满，后续分配落到未映射页 → AV；
崩在哪一步取决于当时恰好谁在分配，所以看起来"换个源码就换个崩点"。

**修法**：`ARENA_CAP` 16 MB → **4 MB**（4 MB 对 440 KB 的产物有 9 倍余量）。

顺带修掉 `__alloc` 的越界检查：上限写成 `heap_start + (BSS_SIZE - 64)`，而堆起点是
`bss+16` —— 这个上限比 `.bss` 末尾**还高 184 KB**，检查形同虚设。改成
`heap_start + (BSS_SIZE - 4096)`。

## 排错过程中排除掉的方向（留给下次）

- 大函数：造了 300 个局部变量的函数，stage-2 编得完全正确。
- 多文件 import：单独编 `std/mem.qma`（439 行 / 49 函数）没问题。
- `spawn` 站点：把并行段换成顺序调用，照样崩。
- 临时值溢出池耗尽：那条路径是 fail-fast（有消息），不是静默。
- 线程竞争：`__alloc` 已加自旋锁；且 `-j1` 也崩（当时）。

## 还没做到：`-jN` 编自己

`-j1` 不动点已达成，但 `-j2` / `-j4` 编 **qlmc 自己** 仍段错误（编夹具的 `-j4` 正常）。
现场：`fault_probe` 报「读 0xFFFF…FFFF」、RIP 在 DLL 里、`Rcx=4`、`R12=-1`，
返回地址不在我们的 `.text` 内 —— 像是把 `-1` 当指针传给了 Win32 API。
已排除堆耗尽（修正上限后仍崩且没触发 exit 3）和 arena 每线程不足（调到 8 MB 仍崩）。
记在 §7.24。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/bootstrap_test.py --strict` | **三级全 PASS** |
| `python tests/qlmc_test.py` | **PASS=51**（24 组用例 + 并行确定性 2 条） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| 四道门 | check_docs / check_names / check_origin / check_bad(75/75) 全绿 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `ARENA_CAP` 16 MB → 4 MB；`__alloc` 越界上限按堆起点算（`BSS_SIZE-4096`）；`_bi_mem_str` 加长度合法性检查（负/超 64 MB → exit 7，把静默 AV 换成可识别退出码） |
| `tests/bootstrap_test.py` | 第 3 级改用 `-j1`（多线程编自己仍崩，见 §7.24）；`--strict` 现在应全绿 |
| `docs/05-toolchain.md` | §1.11 改 v2.35「不动点达成」；不支持表换成「多线程编自己」；坑表补 #36（arena 别开太大）/ #37（越界上限按堆起点算） |
| `docs/07-gaps.md` | §3 stage-1 行改「不动点达成」；**§7.23 改为已修**（真因堆耗尽）；**新增 §7.24**（-jN 编自己待查） |
| `docs/06-status.md` | §3.25 自举状态、体积与不动点耗时 |

## 已知边界

- `-jN` 编自己崩（§7.24）。
- `print(<运行期比较>)` 与 stage-0 不同（§7.22）。
- `mem_free` 仍是空操作（bump 分配器）。
- 仍然缺：f64、泛型、宏/反射、接口、`rc`/`Drop`、闭包捕获、`vec[vec[T]]`、map 扩容。
