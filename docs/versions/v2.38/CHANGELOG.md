# v2.38 — f64（数值部分），子集 S20

- 日期：2026-10-25
- 任务：回功能线，补 f64
- 影响面：自举层（词法/类型/IR/发射器/运行库/导入表）/ 测试 / 文档

## 做到了什么

```quelmara
let a = 1.5
let b = 2.25
let c = a + b                 // 3.75
print(to_int(c))              // 3
print(to_int(a * 4.0))        // 6
print(to_int(a + 10))         // 11（int 一侧自动提升）
if a < b { ... }              // 六种比较都支持
let v = V { x: 1.5, y: 2.5, tag: 9 }   // f64 可以当 struct 字段
```

覆盖：字面量（`1.5` / `100.0` / `1e3` / `2.5e2` / `-1.5` / `-0.0`）、`+ - * /`、
六种比较、一元 `-`、`to_float(x)` / `to_int(x)`、struct 字段、函数形参/返回值。

**`print(f64)` 还没做**（见下）。`tests/selfhost/s21_f64.qma` 与 stage-0
**31 行输出逐字节相同**。

## 两个关键设计决定

### ① f64 住在帧槽里，按"地址"传递

qlmc 的分配器只管通用寄存器。要支持 f64 就得有 **XMM 寄存器文件 + 一整套调用约定**
（前 4 个浮点实参走 XMM0-3、返回值在 XMM0、可变参数要管 AL……），那是另一个量级的改动。

这一版走"先要正确"的路：**f64 值一律占 8 字节帧槽，按聚合的方式传地址**，
每次运算把操作数 `movsd` 进 xmm0、对右操作数直接带内存操作数算，算完存回槽：

```asm
movsd xmm0, [rdx]      ; 左
addsd xmm0, [r8]       ; 右（内存操作数，不用第二个 xmm）
movsd [rcx], xmm0      ; 结果
```

好处是几乎没碰分配器：`_ty_is_agg(TY_F64)` 返回 true，赋值/传参/返回自动走既有的
"8 字节整块拷贝"路径。代价是慢（每次运算 3 条访存），f64 密集的代码以后再优化。

### ② 字面量的 IEEE 位交给运行时的 `strtod`

qlmc 是 Quelmara 写的，**只会整数算术** —— 要自己把 `"1.5"` 算成 IEEE 位，就得实现
正确舍入的十进制→二进制转换（那是 `std/f64` 的 `f64_parse`，几百行）。

所以字面量在**编译期只做一件事：把原文入字符串表**；降级时发 `OP_LEA` + 调用运行库
`__fparse(rcx=原文, rdx=目标槽)`，内部 `strtod(str, NULL)` 再 `movsd` 存槽。

- 正确性：`strtod` 是正确舍入的，与 stage-0（用 Python `float()` 解析）**逐位一致**，
  差分才对得上。
- 代价：每个字面量在**运行时解析一次**（不是常量折叠）。f64 密集的代码会慢，
  但换来"不用在编译器里实现浮点解析"。
- 副作用：输出程序现在会导入 `msvcrt.dll` 的 `strtod`（IAT 第 3 个 DLL）。

## 撞出来并修掉的四个坑

1. **`E_FNUM` 的类型判定放错函数**：加到了 `_fold`（常量折叠）里，而 `_ty_of_expr`
   不认识 `E_FNUM` → `let a = 1.5` 把 `a` 推成 **int**，赋值只搬了地址。
   教训：`_ty_of_expr` 里 `E_NUM` 有**两处**同名分支（一处是 `_fold`），别按字符串
   首次匹配去改。
2. **f64 算术必须写进调用方给的 `dst`**：`_emit_bin` 自己 `_new_f64` 开新槽并返回它，
   而 `_lower_expr` 用的是它自己那个 `dst` —— 于是 `let c = a + b` 之后 `c` 里是
   **上一个临时值的地址**。这是 `_emit_bin` 的契约：结果一定写进 `dst`。
3. **`if` 里的 f64 比较不能走 `JCMP`**：`_lower_cond` 直接用 `OP_JCMP` 比两个**槽地址**。
   巧合之下 `<` / `<=` 还是对的（地址有序），`==` / `!=` 就全错。改成走
   `ucomisd`（`OP_FCMP`）再 `JZ`/`JNZ`。
4. **类型推断不能硬失败**：`_ty_of_expr` 递归进 `E_BIN` 的操作数时会走 `_var_id`，
   而变量还没登记时它是**硬失败** → `s5_enum` 报"未定义变量 rate"。
   改成用不会失败的 `_ty_maybe_f64`（只认字面量/变量/一元/二元）。

另外：`_ty_is_agg(TY_F64)` 为真会让 struct 字段检查拒收 f64 —— 给两处（字段声明、
struct 字面量）加了 `fty != TY_F64` 的例外，并且 f64 字段要**拷 8 字节**而不是把地址存进去。

## 顺带：堆又不够了，`.bss` 32 MB → 64 MB

加完 f64，qlmc 自己从 444 KB 长到 468 KB，**不动点立刻崩**（stage-3 写出 0 字节文件）。
原因是老问题：`.bss` 32 MB 不够（v2.35 那次是 16 MB arena 撑爆 32 MB 堆）。
这次直接把 `BSS_SIZE` 提到 **64 MB**，不动点恢复。`.bss` 不占文件体积、按需提交，
给足没有代价 —— 但**每次加功能都要重跑 `bootstrap_test.py`**，它是最先报警的那个。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=53**（25 组用例 + 并行确定性 2 条；新增 `s21_f64`） |
| `python tests/bootstrap_test.py --strict` | **五级全 PASS**（含不动点） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| 四道门 | 全绿 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `T_FNUM`/`E_FNUM`/`TY_F64`；浮点词法；`_ty_is_agg`/`_ty_of_expr`/`_ty_maybe_f64`；`_emit_bin` 的 f64 分支；`_lower_cond` 的 f64 比较；`_lower_expr` 的 E_FNUM/E_UN；`to_float`/`to_int` 内建；`OP_FCMP` + 7 个运行库例程（fparse/fadd/fsub/fmul/fdiv/itof/ftoi/fneg）；msvcrt `strtod` 导入；`BSS_SIZE` 32→64 MB |
| `tests/selfhost/s21_f64.qma` | **新增**：f64 差分夹具（31 行输出） |
| `tests/qlmc_test.py` | 用例 24 → 25 |
| `docs/05-toolchain.md` | §1.11 改 S20 + 新增 f64 小节（两个设计决定） |
| `docs/07-gaps.md` | §3 stage-1 行、自举状态 |
| `docs/06-status.md` | §3.25 体积/耗时/自举状态 |

## 已知边界

- **`print(f64)` 不支持**（fail-fast 提示用 `to_int()`）：十进制格式化要移植
  `std/f64` 的 `f64_repr`（最短往返），是下一件该做的事。
- f64 字面量在运行时解析（非常量折叠）。
- f64 不进 XMM 寄存器（全走帧槽），性能未优化。
- `f64 % f64`、`f64` 的 `vec`/`map` 元素、f64 数组等还没测/没支持。
- 仍然缺：泛型、宏/反射、接口、`rc`/`Drop`、闭包捕获、map 扩容。
