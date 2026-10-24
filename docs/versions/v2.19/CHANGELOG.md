# v2.19 — vec 落地，并修掉挡住自举的 §7.17（大帧不探测 guard page）

- 日期：2026-10-24
- 任务：vec 语法/运行时 + 攻 §7.17（连续三个版本被它挡住）
- 影响面：**编译器（stage-0 序言）** / 自举层 / 工具（两个新调试脚本）/ 测试 / 文档

## 主事件 1：§7.17 定案并修掉 —— 大帧跳过了 guard page

现象回顾：qlmc 编出来的二进制**随机**崩在某个 `call`（被调方一条语句都没执行），
改栈大小、改代码位置、改语义等价的写法都能翻转"哪些用例崩"，`--no-opt` 与 `-O`
也不同。三个版本里我一度以为是"分配器布局敏感"。

**定位过程**（没有 gdb，自己写工具）：

| 步骤 | 工具 | 结论 |
|---|---|---|
| 1 | 连跑 6 次同一命令 | **崩/不崩交替** → 不是确定性布局问题，是环境相关（栈内容/地址） |
| 2 | `tools/dev/fault_probe.py`（新） | 捕获 `0xC0000005`，AV 地址 = `rsp`，RIP 落在一条 `mov [r13+rdi*8], r14` |
| 3 | capstone 反汇编崩溃点 | 那是**结构体拷贝循环**；`r13 = rbp-0x3450`，而该函数帧是 `0x3458` |
| 4 | `tools/dev/frame_scan.py`（新） | 全程序 **12 个函数帧 ≥ 4 KB**，最大 15 128 字节 |

**根因**：stage-0 的序言只有 `sub rsp, frame`。帧 > 4 KB 时这一条会**跨过 guard
page**，Windows 因此不会自动扩栈；函数体第一次写帧就落在未提交页上 → `0xC0000005`。
这解释了三件事：为什么改栈大小会翻转（提交边界变了）、为什么改代码位置会翻转
（帧大小变了）、为什么崩在"第一次写"。

**修法**（`qlm_native.py` 序言）：帧 > 4 KB 时逐页 touch，**从高地址往低地址**
（和 `__chkstk` 一样，先碰最靠近旧 rsp 的那页才是 guard page）：

```python
if frame > 0x1000:
    off = frame - 0x1000
    while off >= 0:
        emit("mov qword [rsp+off], 0")   # 帧是全新的，写 0 不破坏任何数据
        off -= 0x1000
```

> 注意：第一版我写成"从低往高"，第一条就落在未提交页上，照样 AV——顺序是这条修复的关键。

验证：`r1.qma`（原先随机崩）连跑 6 次全过；fib / s2_str / vec 全部通过；主回归
**PASS=290 FAIL=0** 不变（说明对既有程序无影响）。

## 主事件 2：vec

| 能力 | 做法 |
|---|---|
| `vec[T].new(n)` | 堆块 `[len][cap][data...]`，`__alloc(16 + n*8)`；元素限 int/bool/str |
| `v.push(x)` | 长度到容量就 `exit(1)`（**本版不扩容**，容量在 new 时定死） |
| `v.get(i)` / `v[i]` | 越界检查（无符号 `jb`，负数也拦）+ `data + i*8` |
| `v[i] = x` | qlmc 扩展（stage-0 不支持 vec 下标赋值，故不进差分夹具） |
| `len(v)` / `v.len()` | 读 `[h]` |

实现全部是**内联 IR**（没有新增运行时例程），并且把 vec 下标并进了既有的
`_addr_index`（数组/vec 共用一条取地址链），避免再往 `_lower_expr` 里堆分支——
上一轮正是那些分支让帧变大、触发了 §7.17。

## 数字

| 项 | v2.18 | v2.19 |
|---|---|---|
| `build/qlmc.exe` | 824 KB | **约 900 KB** |
| qlmc 差分 | 21 条 | **23 条**（新增 `s6_vec`） |
| 主回归 | 290 | **290**（不变） |
| `s6_vec.qma` 编译 | — | **5.4 ms**（进程内），产物 4096 B |
| 大帧函数（≥4 KB） | 12 个（会随机崩） | 12 个，但**都有栈探测**，不再崩 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | **序言加栈探测**（帧 > 4 KB 时自高向低逐页 touch）——跨轨改动，语言轨注意 |
| `bootstrap/qlmc/qlmc.qma` | vec：`vec[T]` 类型、`vec[T].new(n)` 构造、`.push/.get/.len`、`v[i]` 读写、`len(v)`；`_addr_index` 支持 vec 句柄 |
| `tests/selfhost/s6_vec.qma` | **新增**：vec 差分夹具（8 行输出） |
| `tests/qlmc_test.py` | 用例 9 → 10 |
| `tools/dev/fault_probe.py` | **新增**：Windows 调试 API 抓 AV 现场（RIP/RSP/RBP/AV 地址/rbp 链），支持重试 |
| `tools/dev/frame_scan.py` | **新增**：扫 PE 里所有函数帧大小，报 ≥ 阈值者 |
| `docs/07-gaps.md` | §7.17 从"待查"改为**已修**，含完整定位链与修法；§3 stage-1 行改 S5 |
| `docs/05-toolchain.md` | §1.11 覆盖表加 vec；坑表补「大帧必须探测」；§5.2 脚本表加两个新工具 |
| `docs/06-status.md` | §3.25 数字更新 |

## 已知边界

- **vec 不扩容**：容量在 `new(n)` 时定死，`push` 超了直接 `exit(1)`（不静默写穿）。
- vec 元素只支持 int/bool/str（不支持 vec[struct]、嵌套 vec）。
- `v[i] = x` 是 qlmc 扩展，stage-0 不支持，因此不在差分覆盖内。
- 聚合形参/返回值仍不支持（fail-fast）。
- 仍缺：map、f64、切片、泛型、闭包、`defer`、`import`、宏/反射、`@ffi`、接口、`rc`。
