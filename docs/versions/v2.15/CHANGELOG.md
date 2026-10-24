# v2.15 — qlmc 扩到子集 S2：str / const / assert（覆盖从"能算"到"能写字符串"）

- 日期：2026-10-24
- 任务：全部覆盖（在 v2.14 的 S1 上继续扩）
- 影响面：自举层（`bootstrap/qlmc/`）/ 测试（差分用例 3 → 6）/ 文档

## 主事件

v2.14 的 qlmc 只会算整数。这一版补上**字符串**——它是覆盖面最大的一层：
没有 str 的编译器连"hello world"都写不了，更别说仓库里的任何测试。

新增能力：

| 能力 | 做法 |
|---|---|
| str 类型 | 值 = 数据指针，长度在 `ptr-8`（与 stage-0 的 ABI 一致）；字面量进 `.rdata` 的 `[len][bytes][NUL]` |
| 最小类型跟踪 | `_emit_expr` 返回 TY_INT/TY_BOOL/TY_STR，只为选对指令（`+` 是 `add` 还是拼接、`print` 走哪个通道） |
| `+` 拼接 | `__str_cat`：`__alloc` 出 `la+lb+9` 字节 → 写长度前缀 → 两次 `__memcpy` → 补 NUL |
| `==` / `!=` | `__str_eq`：先比长度再逐字节比 |
| `len(s)` | 读 `[ptr-8]` |
| `print(str)` | `__print_str`：WriteFile 数据 + 单独写一个换行字节 |
| 堆 | `.bss` 1 MB（不占文件体积）+ `__alloc` bump 分配器（游标存在 `.bss` 首字） |
| `const` | 解析期内联成字面量（整型），不占运行期存储 |
| `assert(cond, msg)` | 失败写 stderr（handle -12）后 `ExitProcess(1)`，退出码与 stage-0 一致 |

差分用例从 3 组扩到 6 组（13 条断言），新增 `s2_str` / `s2_const` / `s2_assert`，
**全部与 stage-0 逐字节相同**（含"故意失败的 assert"那条，rc 都是 1）。

## 两个"照抄不修正"的口径

差分测试逼出来的：stage-0 里 **`&&`/`||` 与 str 比较产生 bool**（打印 `true`/`false`），
而 **int 比较与 `!` 产生 int**（打印 `1`/`0`）。看着不一致，但那是既有行为；
qlmc 跟它走，不"统一"——统一了差分就红，而差分是这里唯一的正确性判据。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `Fn` 带形参/返回类型；`Node` 带 `ty`；`_emit_expr` 返回类型并支持 str 拼接/比较/len；`.bss` 与 `__alloc`/`__str_cat`/`__str_eq`/`__memcpy`/`__print_str`/`__die` 六个运行库例程；`const` 解析；`assert` 内建 |
| `tests/selfhost/s2_str.qma` | **新增**：str 变量/形参/返回、拼接、内容比较、len、空串、循环拼接 |
| `tests/selfhost/s2_const.qma` | **新增**：const 内联 |
| `tests/selfhost/s2_assert.qma` | **新增**：断言通过 + 故意失败（比 rc） |
| `tests/qlmc_test.py` | 用例表 3 → 6 |
| `docs/05-toolchain.md` | §1.11 覆盖表改成 S2；新增 4 条坑（入口必须在偏移 0、REX 前缀、运行库实参寄存器、结构体按值传） |
| `docs/06-status.md` | §3.25 数字与覆盖更新（qlmc.exe 330 KB、5 个用例的耗时） |
| `docs/07-gaps.md` | §3 stage-1 行：S2 覆盖与剩余缺口 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | PASS=13 FAIL=0（6 组用例逐字节相同 + PE 结构断言） |
| `python tests/run_win_tests.py` | PASS=289 FAIL=0 SKIP=1 |
| `build/qlmc.exe build tests/selfhost/s2_str.qma` → 运行 | 与 stage-0 产物输出逐字节相同（61 字节） |
| 五道门禁 | 全 PASS |

## 已知边界 / 遗留

- **还不支持**：struct/enum/match、数组 `[N]T`、vec/map、f64、泛型、闭包、切片、
  `defer`、`for`、`break`/`continue`、`import`（多文件）、宏/反射、`@ffi`、接口、`rc`。
  离"编整个仓库"还差很远——`std/*.qma` 里几乎每个模块都同时用到 str、struct、vec
  和 import，四样缺一不可。
- **堆只增不减**：`__alloc` 是 bump，1 MB 用完就写穿（没有检查）。循环里疯狂拼串
  会撞上；补"用完报错"是下一版的小事。
- **`assert` 的 stderr 文本**只有消息本身，没有 stage-0 的 `assert failed: ` 前缀
  （差分只比 stdout 与退出码，没比 stderr）。
- **仍然没有寄存器分配与常量折叠**：`loop_sum` 依旧比 stage-0 慢一个量级。
