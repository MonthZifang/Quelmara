# v3.45 — `qlmc irdump`：IR dump 工具（补上 v3.44 缺的那块）

- 日期：2026-10-31
- 任务：用户要求"继续"；执行 v3.44 自己写下的重启条件（`07-gaps.md` §7.36）
- 影响面：`bootstrap/qlmc/qlmc.qma`（新命令 + 3 个函数）、
  `tests/irdump_test.py`、`tests/run_win_tests.py`
- 覆盖率：46 / 70（不变 —— 这一版买的是**工具**，不是内建）
- 回归：PASS=361 → **362** FAIL=0 SKIP=0

## 做了什么

新增 `qlmc irdump <src.qma> [函数名]`：

* **不给函数名** → 列出所有函数（名字 / IR 条数 / vreg 数 / 帧字节）；
* **给函数名** → 打该函数的完整 IR，每条带 `dst`/`a`/`b`/`imm` 和
  **vreg 的实际落点**（`r<N>` 寄存器 / `s<N>` 帧槽 / `-` 未分配）。

打的是**优化之后**（`_alloc` 完成、`_emit_fn` 之前）的形态 —— 要查的
正是分配器与融合之后的指令序列。

```
$ qlmc irdump tests/x.qma f6
=== fn f6  ir=16  vregs=14  frame=40B ===
  0  PARAM2  dst=1(r3)  a=0  b=0  imm=0
  1  PARAM2  dst=2(r12)  a=0  b=0  imm=1
  2  PARAM2  dst=3(r13)  a=0  b=0  imm=2
  3  PARAM2  dst=4(r14)  a=0  b=0  imm=3
  4  PARAMSTK  dst=5(r15)  a=0  b=0  imm=0
  5  PARAMSTK  dst=6(r6)  a=0  b=0  imm=1
  6  ADD  dst=11(s0)  a=1  b=2  imm=0
  ...
```

一眼就能看出：前 4 个形参走寄存器（`PARAM2` → `r3`/`r12`/`r13`/`r14`），
第 5/6 个走栈（`PARAMSTK`），第 6 条 `ADD` 因为溢出落到了帧槽 `s0`。

## 踩的坑：工具本身把 stage-2 搞崩了

第一版把 `irdump` 的 60 行初始化**内联在 `main` 里**，结果**自举等价性
30 组全 FAIL**、`stage-2` 编普通程序直接 `0xC0000005`。

用 `irdump` 自己一查就清楚了：

```
main 帧：v3.44 = 1776B   →  内联 irdump 后 = 2544B（+768B）
```

那 12 个局部变量（`rt_pos`/`ucnt`/`baked`/`csb`/`lpm`/`cok`/`cval`/`use`/
`ndef`/`out`/`want_fn`/`fi2`）每个占一个帧槽。2544B 本身没超 4096，但
**stage-2 编自己时 `main` 还会再涨**，越过 4 KB 就崩。

修复：整段抽成独立函数 `_cmd_irdump` —— 函数调用不占调用方的局部槽。
`main` 的帧回到 1776B，自举立刻恢复 30/30。

> 这是本项目**第三次**踩同一个坑（前两次：`build_rdata` 加 8 个
> `dsym.push`、`_lower_builtin` 内联 6 个网络内建）。规律很清楚：
> **往 `main`/`_lower_builtin`/`build_rdata` 这种大函数里加东西之前，
> 先用 `irdump` 看一眼帧字节。**

## `_op_names` 的两次返工

名字表最初写成 `vec[str]` + 80 次 `push`/`set`，**每个语句占 1 个帧槽**，
直接把 `_op_names` 自己顶到 417 格（上限 416）—— 编译期就 fail-fast。

改成**一条逗号分隔的常量串** + 按序号数逗号（`_op_name(n)`），只占 1 格。
中途还试过 `const OP_NAMES = "..."`，被 qlmc 拒绝：
`const 初值必须是编译期可求值的整型表达式`（qlmc 的 `const` 不支持字符串，
这是已知限制，`07-gaps` 里那 3 个 `const 常量表达式` 失败项之一）。
最后落成 `fn _op_names_str() -> str { return "..." }`。

## 测试

`tests/irdump_test.py`（7 项断言）钉住工具自身：

```
[PASS] 清单模式列出 2 个函数
[PASS] f6 的 IR 条数 = 16
[PASS] 单函数模式的 IR 条数与清单一致（16）
[PASS] 不存在的函数名报错退出（不静默返回空）
[PASS] 所有 dst 位置标注都是 r<N> / s<N> / -
[PASS] 6 参函数的 PARAMSTK（栈形参）在 IR 里可见
=== IRDUMP: PASS=7 FAIL=0 ===
```

为什么要给"调试工具"写回归：它坏了会让人**误判成"目标函数的 IR 就是这样"**，
比没有工具更糟。

## 下一步

`udp_sendto` 的崩溃现在可以用这个工具查了：把 `_bi_udp_sendto` 与已知
正常的 `_bi_udp_recvfrom` 各 dump 一遍，逐条对比指令序列。这是 v3.44
耗掉 40 轮也没做到的事。

## 回归与自举

```
PASS=362 FAIL=0 SKIP=0
自举五级链：stage-2 可用且与 stage-1 逐字节等价（30/30 组，不动点成立）
```
