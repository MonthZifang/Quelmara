# v2.90 — args() 在 Linux/AArch64 上双重偏移：`args()[0]` 越界读，SIGSEGV

- 日期：2026-10-28
- 任务：修 lint/回归 —— CI 的 `linux` job 从 v2.20 起一直是红的，根因在这
- 结论：**`lower_args` 两条路径共用了一份偏移量**，Linux 侧于是少一个参数、
  首元素读到表尾之后。一个字面量级的修复，但它让整个 Linux 自举对拍链断在第一步。

## 症状

`tests/lexdiff.py` 在 Linux 上是 **PASS=0 FAIL=307**（310 个源文件里 307 个
失败，剩下 3 个是本来就 SKIP 的 `f"..."` 插值文件）。每个失败都是：

```
[FAIL] examples/hello.qma: oracle 142 行 / lexer 0 行 rc=1
```

`rc=1` 且 `lexer 0 行` —— 词法器**一行都没输出**就退出了。直接跑：

```
$ ./build/qlm_lex.qex examples/hello.qma
quelmara: read_text() failed (fail-fast)
```

词法器 `bootstrap/lexer/qlm_lex.qma` 的入口是 `let src = read_text(a[0])`。
`a[0]` 拿到的不是 `examples/hello.qma`，于是 `open` 失败。**不是词法器的问题，
是 `args()` 的问题。**

## 根因：两条路径产出的 argv 表口径相反

`tools/stage0/qlm_native.py` 的 `lower_args()` 里，两条路径共用同一段收尾：

```python
cnt = argc - 1        # 长度减一
ptr = argv + 8        # 基址加八
```

但两条路径产出的表**含义正好相反**：

| 路径 | `__unix_args_copy` / `__win_args_init` 产出 | 正确取法 |
|---|---|---|
| Windows | 完整命令行拆成 `argc` 个 token，`argv[0]` 是**程序名** | `argv+8`、`argc-1` ✓ |
| Linux/AArch64 | **原地改写**内核 argv 成"已排除程序名"的表，`arr0[i]` 就是第 i 个参数 | `argv`、`argc-1` ✗ |

于是 Linux 上**双重偏移**：既跳过了第 0 个真实参数（`argc-1` 又减了一次），
又把基址往后再推了 8 字节 —— 读到的是表尾之后的内存。

- 单个参数时：`len(a)` 报 0，`a[0]` 是越界读；
- 多个参数时：`len(a)` 少一，`a[i]` 整体错位一格；
- 实测单参数 `./prog foo`：**SIGSEGV**；双参数 `./prog AAA BBB`：`[0]` 打印出 `BBB`。

## 为什么活了一年没被发现

`args()` 的回归**只在 Windows 上跑**：`tests/run_win_tests.py` 的 `[3d]` 段带
三个参数执行 `tests/t29_args.qma`。Linux 侧（`tests/run_native_tests.sh`）从头
到尾没有一条 `args` 用例 —— 而 `lower_args` 恰恰**按平台分叉**，正是最该两边
都测的地方。

同一类错误在 `docs/07-gaps.md` 里已经记过一次（"两条路径实现不一致"是
v1.19 浮点比较 bug 的根因）。这是第二次。

## 修复

按平台拆开，各自用自己那份表的口径：

```python
if self.platform == "windows":
    ...                      # argv+8 / argc-1（不变）
    return self.make_slice(fn, ptr, cnt, elem="str")

fn.emit("call", None, "__unix_args_copy", [])
argc = load(argc_gid)
argv = load(argv_gid)        # 已是"排除程序名"的新表
cnt  = argc - 1              # argc_gid 仍是内核口径（含程序名）
return self.make_slice(fn, argv, cnt, elem="str")   # 基址不加 8
```

注意 `argc_gid` **没有被** `__unix_args_copy` 覆写（只覆写了 `argv_gid` 和
`_args_copied_gid` 哨兵），所以长度仍要减一 —— 这一点在改的时候容易想反，
写进代码注释了。

AArch64 共用同一个 `Lower`（`qlm_arm64.py` 调 `lower_and_optimize(arch="aarch64")`，
`platform` 默认 `"linux"`），所以这一处修复**同时修好两个后端**。

## 验证

| 项 | 修复前 | 修复后 |
|---|---|---|
| `tests/lexdiff.py`（Linux） | PASS=0 FAIL=307 | **PASS=307 FAIL=0**（3 SKIP 不变） |
| `tests/parsediff.py`（Linux） | PASS=0 FAIL=211 | **PASS=211 FAIL=0** |
| `tests/run_native_tests.sh` | PASS=64 FAIL=34 | **PASS=67 FAIL=34**（+3 是新用例） |
| `tests/a64_iface_test.py` | PASS=7 FAIL=0 | PASS=7 FAIL=0（无回归） |

`run_native_tests.sh` 剩下的 34 个 FAIL **全部是 `C 后端 ... 失败` 与它连带的
"双后端不一致"**，根因是本机没有 C 编译器（`command -v gcc cc clang` → 空），
`build/c_divmod` 之类根本没产出。这批失败在装了 C 编译器的机器上不出现，
与本次改动无关 —— 但**它们同样是"Linux 上跑不全"的一部分**，见下节。

## 新增回归

`tests/run_native_tests.sh` 加了 `[23] args() 在自研后端`，三条断言把 Linux
口径钉死：

1. 三个参数时退出码 0（**修复前这里是 SIGSEGV**）；
2. 输出逐字节等于 `3 / alpha / beta / two words / alpha`（个数 + 顺序 + 首元素）；
3. 零参数时非零退出（夹具的 `assert(len(a)==3)` 与 `arg(0)` 的越界检查都不许静默）。

第 2 条是关键：只用"退出码 0"是抓不到"少一个参数"的 —— 修复前单参数也能
`exit 0`，只是 `a[0]` 是垃圾。

## 还没解决的（登记，不在本版做）

| 项 | 现状 | 影响 |
|---|---|---|
| CI `linux` job 仍红 | 本次修复只清了 `自举对拍` 那一步的 518 个 FAIL；后面 `自研后端回归` 那一步在本机因缺 C 编译器红 34 条，runner 上有 gcc 应当不红 —— **需要一次真实 CI 验证** | 下次推送看 `linux` job 是否转绿 |
| `args()` 的 Windows 路径仍无 Linux 侧对照 | 本次只加 Linux 侧用例，Windows 侧仍是 `run_win_tests.py` 那一份 | 两条路径现在各有一份用例了 |
| `arg(i)` 越界在零参数时走 `emit_bounds` | 依赖 `bounds_check=true`（`Quelmara.toml` 默认开）；关掉后行为是 UB，与 `vec`/数组一致 | 不是缺陷，是已声明的配置语义 |

## 口径

本版没有性能数字（这是正确性修复）。基准与上一版相同，见
`docs/06-status.md` §3.52 的 v2.89 全表。
