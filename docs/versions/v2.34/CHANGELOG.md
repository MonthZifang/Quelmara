# v2.34 — 自举出的 stage-2 与 stage-1 逐字节等价，子集 S19

- 日期：2026-10-25
- 任务：上一版结尾的"stage-2 读到垃圾"——把自举链修通
- 影响面：自举层（分配器 / 编码器 / 实参摆放 / 比较类型）/ 测试 / 文档

## 主事件：stage-2 可用了

```bash
$ python tests/bootstrap_test.py
[0] stage-1（stage-0 编 qlmc）：PASS  1.8s
[1] stage-2（qlmc 编自己）：PASS  0.7s  439808 字节
[2] stage-2 与 stage-1 产物一致：22/22 组  PASS
[3] 不动点 stage-2 == stage-3：未达成（崩/超时）—— 已知，见 07-gaps §7.23
PASS：stage-2 可用且与 stage-1 逐字节等价
```

也就是说：**自举出来的编译器，在全部 22 组独立夹具上与 stage-1 逐字节等价**。
（上一版它连 `print(1)` 都编不对。）

新增 `tests/bootstrap_test.py`：三级检验——① 能编出自己 ② stage-2 与 stage-1 产物
逐字节相同 ③ 不动点 `stage-2 == stage-3`。第 3 级目前按"信息项"报（`--strict` 才判失败）。

## 修掉的四个 bug（都是"寄存器压力大才暴露"那一类）

### ① 摆实参要「先栈后寄存器」—— 上一版只修了一半

v2.33 我把 STKARG 挪到了 ARG 之前，但**寄存器实参之间**还有同样的冲突：
实参 2/3 的目标是 R8/R9，而**临时值正好住在 R8-R11**。

```quelmara
fn f(a: int, b: int, c: int, d: int) -> int { ... }
f(a, b, c, 4)      // 第 4 个实参传成了 c（应为 4）
```

`_modrm_sib(code, mod, reg)` 内部就是 `_modrm(code, mod, reg, 4)` —— 于是 stage-2 编出来的
`lea rcx,[rsp+0x30]` 变成 `lea rcx,[rcx+0x3024]`（SIB 没走、rm 字段成了 reg）。
修法：摆实参前把**下标 2/3 的临时值** `_pin` 进变量（0/1 的目标是 RCX/RDX，临时值不
会住那儿）。坑表 #33。

### ② `OP_LOAD8` / `OP_STORE8` 当地址在帧槽时读错了地方

```asm
; 想要：movzx r11, byte [s+i]
; 实际：movzx r11, byte [rbp-0xc08]   ← 读的是槽本身，不是槽里那个地址
```

于是 `s[i] == 47` 恒为假 → 词法器的 `//` 注释跳过失效 → stage-2 读到第一个非 ASCII
字节就报「不认识的字符」。`OP_LOAD`/`OP_STORE` 一直是先用 `_to_reg` 把地址搬进寄存器
再解引用的，我新加的两条没照做。修法：与它们同构。

### ③ bump 分配器不是线程安全的

函数体是多线程并行编译的，每个线程开头都要 `_new_fc`（十几个 vec），而游标是
"读 → 加长度 → 写回"，不加锁就是丢更新 → 两个线程拿到同一块内存。
**竞态指纹：同一输入每次报不同的错**（-j2 报 `未定义变量 pos`、-j4 报
`不支持的表达式节点 60`）。修法：`__alloc` 加 `xchg [bss+8], r8` 自旋锁。

### ④ 自旋锁的释放写到了错误地址 → 死锁

```asm
mov qword ptr [rip + 0x1e46], 0     ; 想写 bss+8，实际写到 bss+12
```

**RIP 相对位移是相对「整条指令末尾」**，而 `mov [rip+disp], imm32` 在 disp32 后面还跟
4 字节 imm32；`_addfix` 按 `pos+4` 算就偏 4 字节。锁永不释放 → 第二次分配自旋死锁
（连 `print(1)` 都编不出来）。修法：改成 `mov ecx,0; mov [rip+disp], rcx`。坑表 #34。

## 另外两处

- **`.bss` 从 1 MB 提到 32 MB**：qlmc 给并行编译的 arena 申请 **16 MB**，而它自己产出的
  exe 只给了 1 MB 堆 → `mem_alloc(16MB)` 静默越界，之后所有分配落在未映射页
  （AV 地址 = 基址 +17.3 MB）。同时给 `__alloc` 加了越界 fail-fast（退 3）。
  stage-0 的堆够大所以一直没暴露。
- **比较结果保持 int**（不动 v2.33 之前的口径）。中途试过改成 bool，结果 `s1_basics` 的
  `print((1 < 2) && (3 > 2))` 从 `1` 变成 `true` —— 因为 stage-0 会把**可折叠**的比较
  折成 int，运行期的比较才是 bool，它自己就不一致。qlmc 没有常量折叠，只能选一头，
  选 int。已知差异记进 07-gaps §7.22。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/bootstrap_test.py` | **前两级 PASS**（stage-2 与 stage-1 22/22 组逐字节相同） |
| `python tests/qlmc_test.py` | **PASS=51**（24 组用例 + 并行确定性 2 条） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| 四道门 | check_docs / check_names / check_origin / check_bad(75/75) 全绿 |
| 性能 | `s3_manyfns` 17.5–18.0 ms（基线内）；自编译 145–153 ms（`-j4`） |

## 还没做到的

**不动点（stage-2 == stage-3）**。stage-2 编 qlmc 自己时崩在代码生成：

- `dump` 能完整解析（49705 tokens / 28911 nodes / 260 fns / 989 names / 227 strs / 8 structs）；
- `build` 崩，`fault_probe` 报「读 0xFFFFFFFFFFFFFFFF」、RIP 在 DLL 里
  （像是把 `-1` 当指针传给了 Win32 API）；
- `-j1` 也崩，所以不是并发问题，是"大型输入 + 高寄存器压力"下的分配类误编译
  （这一版修的 ①②④ 都是这一类）。

下一步：用带 `_compile_range` 函数名日志的 dbg 版二分到具体函数（`-j1` 下可确定）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `_emit_call_args` 钉住实参 2/3 的临时值；`OP_LOAD8`/`OP_STORE8` 改成先 `_to_reg` 再解引用；`__alloc` 加自旋锁 + 越界 fail-fast（释放改用 `mov reg,imm`）；`BSS_SIZE` 1 MB→32 MB 并提到文件前部 |
| `tests/bootstrap_test.py` | **新增**：三级自举检验（构建 / 等价 / 不动点） |
| `docs/05-toolchain.md` | §1.11 标题改 v2.34；不支持表换成「不动点」；坑表补 #33（实参 2/3 要钉）/ #34（RIP 位移与 imm32 尾巴）/ #35（分配器要线程安全） |
| `docs/07-gaps.md` | §3 stage-1 行改 ✅；**新增 §7.22**（比较 print 差异）/ **§7.23**（stage-3 待查） |
| `docs/06-status.md` | §3.25 自举状态与体积更新 |

## 已知边界

- 不动点未达成（见上）。
- `print(<运行期比较>)` 与 stage-0 不同（§7.22）。
- `mem_free` 仍是空操作（bump 分配器）。
- 仍然缺：f64、泛型、宏/反射、接口、`rc`/`Drop`、闭包捕获、`vec[vec[T]]`、map 扩容。
