# v4.92 — `parfor ... reduce` 真并行：单线程代码改一个词拿到多核

- 日期：2026-11-10
- 任务：让单线程单核应用**无缝迁移**到本语言后直接获得多核性能
- 影响面：编译器（词法 / 语法 / 解析期函数合成 / 降低）、语言参考

## 做了什么

v4.91 立住了 `parfor` 的语法，但降低成串行循环。本版把它变成**真并行**：

```qma
// 串行
let mut s = 0
for i in 0..n { s = s + (i * 7) % 13 }

// 并行：只多两个词（parfor + reduce s），结果完全一致
let mut s = 0
parfor i in 0..n reduce s { s = s + (i * 7) % 13 }
```

实测（4 核，4000 万次迭代，min of 3）：

| | 耗时 |
|---|---|
| `for`（串行） | 181 ms |
| `parfor ... reduce`（并行） | **118 ms** |
| 加速比 | **1.53×** |

校验和与串行版**逐字节一致**。

## 关键设计：为什么能不掉一行语义就把循环变并行

### 1. 解析期合成 worker 函数

`spawn` 只能调**函数**，而 qlmc 的函数表在解析结束后就定长
（`main` 里 `let nfunc = len(fns)`）。所以 worker 必须在**解析期**生成。

Q: 为什么不用把变量 id 重映射一遍？
A: 因为 AST 里的变量引用存的是**全局名字 id**（`_name_id`），不是绑定。
worker 的循环变量用一个全新名字（`__parfor_N`），就自动与外层同名变量
隔离；其余名字 id 可以原样共享 —— 它们指向同一个全局名字表，语义正确。
这比"深拷贝 + 重映射绑定"简单得多，是这条路线可行的根本原因。

生成的 worker 形如：

```qma
fn __parfor_0(lo: int, hi: int) -> int {
    let mut __parfor_0_acc = 0        // 每块**自己的**累加器
    for i in lo..hi { __parfor_0_acc = __parfor_0_acc + (i * 7) % 13 }
    return __parfor_0_acc
}
```

### 2. 归约变量改名（必须做）

worker 里的累加器**不能**沿用外层的名字 id。否则 `let mut s = 0` 会与外层
`s` 撞 id，`s = s + ...` 在降低期会被当成同一个变量 —— 语义直接错。
所以克隆出来的体里要做一次名字替换（`red` → `__parfor_N_acc`）。

### 3. 每块独立累加 = 无数据竞争

worker 写的是**自己的局部变量**，共享的那个 `acc` 只在父线程里被写：

```qma
acc = acc + worker(lo0, hi0) + worker(lo1, hi1) + ... + 父线程自己算的其中一块
```

热循环里**零锁、零原子操作**。这也是为什么必须让用户显式写 `reduce`：
没有归约声明，编译器不知道哪次写是"可合并的"，就不能并行。

### 4. 切 4 块，最后一块由父线程自己算

块数在编译期固定为 4（qlmc 的 IR 里没有"运行时核数"这个值，而块数必须
是编译期常量才能展开成 N 次 spawn）。最后一块不 spawn、由父线程直接算，
省一次 spawn/join 往返。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增 `reduce` 关键字；`parfor` 解析支持 `reduce <变量>` 子句；新增 `_clone_list`（深拷贝语句链）、`_rename_in_list` / `_rename_expr`（名字替换）、`_emit_spawn_call`（与 `_lower_spawn` 同形的 spawn 发射）；`parfor` 降低改为切 4 块 + spawn + join 合并 |

## 踩到的三个坑（都写进注释了）

1. **`nx` 槽不能存 worker 下标**。`nx` 是语句链指针，`_block` 的
   `_set_nx(p, last, id)` 会把下一条语句写进去 —— 实测 `parfor` 后面的
   `print(s)` 让 nx 从 0 变成 21，降低期拿到错误的函数下标。改用 `ty` 槽。
2. **AST 子树不能共享**。同一个体不能同时挂在父函数和 worker 上，
   否则降低期两边都顺着 `nx` 走，**编译器死循环**（实测挂 4 分钟）。必须深拷贝。
3. **没有 `reduce` 时不能合成 worker**。否则 `acc_nid = -1`，
   `S_LET` 的 `a = -1`，降低期报"未定义变量"。

## 验证

| 命令 | 结果 |
|---|---|
| `parfor ... reduce` vs `for` 同区间 | 校验和**逐字节一致** |
| 自举三代 | **逐字节不动点**，730624 B |
| 76 个基准 checksum vs C | **76/76 一致** |
| 并行加速比（4 核 / 4000 万次） | **1.53×**（181 → 118 ms） |
| `python3 tools/dev/check_docs.py` | PASS |

复核命令：

```bash
cd /root/Quelmara/Quelmara
cat > /tmp/pb.qma <<'Q'
fn main() {
    let n = 40000000
    let t0 = now_ns()
    let mut s = 0
    for i in 0..n { s = s + (i * 7) % 13 }
    let t1 = now_ns()
    let mut p = 0
    parfor i in 0..n reduce p { p = p + (i * 7) % 13 }
    let t2 = now_ns()
    print(s == p)
    print(t1 - t0)
    print(t2 - t1)
}
Q
wine build/qlmc.exe build /tmp/pb.qma -o /tmp/pb --target elf
chmod +x /tmp/pb && /tmp/pb     # true / 串行 ns / 并行 ns
```

## 已知边界 / 遗留

- **块数固定 4**（编译期常量）。应该有 `cores()` 内建或在启动时探测，
  让块数跟机器走 —— 这是下一步。
- **只支持 `+=` 形态的归约**（`acc = acc + expr`）。`*=`、`min`/`max`
  归约、以及"归约变量是 vec 元素"都还没做。
- **只有带 `reduce` 才并行**。没有归约的 `parfor`（纯副作用循环）
  仍按串行降级 —— 那种循环体可能写任意共享状态，编译器无法证明安全。
- 加速比 1.53× 低于 4 核理想值：本机是 4 个共享 L2 的 Celeron J1900，
  同机 C+pthread 的 4 核效率也只有 0.60（见 v4.86 文档）。另外
  spawn 固定开销在 4000 万次这种中小负载上占比不可忽略。
- `break`/`continue` 在 `parfor` 体内未定义（串行阶段可用，并行阶段语义不明）。
