# v2.21 — map 落地 + 实参放开到 4 个，子集 S7

- 日期：2026-10-24
- 任务：map（最后一块容器）+ 放开实参个数
- 影响面：自举层（qlmc 前后端）/ 测试 / 文档

## 主事件 1：`map[K]V`

| 能力 | 做法 |
|---|---|
| `map[K]V.new(n)` | 固定容量，堆块 `[cap][count]` + `cap` 个 `(key, val)` 槽（每槽 16 字节） |
| `m.set(k, v)` | 线性扫描：遇到空槽就插入并 `count++`，键相同就覆盖值；扫满 `exit(1)` |
| `m.get(k)` | 命中读值；空槽返回 0 |
| `m.has(k)` | 返回 **bool**（打印 `true`/`false`，与 stage-0 一致） |
| `len(m)` / `m.len()` | 读 `[count]` |
| 类型编码 | `TY_MAP + (K<<8) + V`，K/V 限 int/bool/str |

**取舍**：这一版是**固定容量 + 线性扫描**，不是哈希表——O(n) 每次操作，但实现短、
边界清楚（没有扩容/墓碑/哈希碰撞）。键槽为 0 表示空位，所以 **int 键不能用 0**。
等切片和 import 做完再回来换开放寻址哈希。

## 主事件 2：实参从 2 个放开到 4 个

parser 之前只解析两个实参（`E_CALL` 只有 b/c 两个子槽）。现在用 `b/c/n/slot` 四个槽，
机器层本来就是 RCX/RDX/R8/R9 四个寄存器（聚合返回会占掉一个，所以最多 3 个）。

## 踩到的坑（同一条规律，第二次）

`map` 第一版生成的程序直接 AV（读 0x20）。反汇编看到两处**跨循环回边/跨调用存活的临时值
被复用**：

1. `cap16`（循环上界）在循环外算好、循环内每次比较——临时值的活跃区间不覆盖回边，
   分配器把它的槽位复用成了 `slot` 地址；
2. `n`/`per` 在 `__alloc` 调用之后还要用，而 **`__alloc` 会踩 R8**（`lea r8, [rax+rcx+7]`）。

修法：加 `_pin(fc, v)` 把值钉进变量（pinned 到 callee-saved 寄存器或帧槽），
凡"跨循环回边"或"跨调用"存活的值一律先 pin。`_vec_new` 也有同样的隐患，一并修了。

> 这条规律在 v2.17 的 `for` 上界已经踩过一次（当时是死循环），这次是 AV。
> 已写进 `05-toolchain.md` 坑表：**临时值不跨回边，跨了就 pin**。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=27**（12 组用例 + 并行确定性 2 条；新增 `s8_map`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s8_map.qma` | 11 行输出与 stage-0 逐字节相同（`1234/0/3/100/200/300/true/false/222/3/622`） |

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | map：类型编码、`map[K]V.new(n)`、`.set/.get/.has/.len`、线性扫描降级、`OP_ZERON`（动态长度清零）、`_pin`；实参：parser 收到 4 个、`E_CALL` 用 `b/c/n/slot` |
| `tests/selfhost/s8_map.qma` | **新增**：map + 4 实参的差分夹具 |
| `tests/qlmc_test.py` | 用例 11 → 12 |
| `docs/05-toolchain.md` | §1.11 改 S7；坑表补「跨回边/跨调用的临时值必须 pin」 |
| `docs/06-status.md` / `07-gaps.md` | 数字与 stage-1 行更新 |

## 已知边界

- map **不扩容**（`new(n)` 定死容量，满了 `exit(1)`）；线性扫描 O(n)；int 键不能用 0。
- map 的键/值限 int/bool/str（聚合值还不能进 map）。
- 实参上限 4 个寄存器（聚合返回占一个 → 最多 3 个实参）。
- 仍缺：f64、切片、泛型、闭包、`defer`、`import`、宏/反射、`@ffi`、接口、`rc`。
