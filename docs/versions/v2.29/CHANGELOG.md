# v2.29 — 形参/实参不限个数（第 5 个起走栈），子集 S15

- 日期：2026-10-25
- 任务：**超过 4 个形参** —— 上一版结尾定位出的"自举第二个硬阻塞"
- 影响面：自举层（qlmc 解析 / 降级 / ABI / 发射器）/ 测试 / 文档

## 主事件：第 5 个形参起走栈

```quelmara
fn pack7(a: int, b: int, c: int, d: int, e: int, f: int, g: int) -> int {
    return a * 1000000 + b * 100000 + c * 10000 + d * 1000 + e * 100 + f * 10 + g
}
print(pack7(1, 2, 3, 4, 5, 6, 7))     // 1234567
```

Win64 的口径：前 4 个实参走 RCX/RDX/R8/R9，**之后的一律走栈**，栈上位置在
`[rsp+32]`（32 字节 shadow space 之后）起，每个 8 字节。

| 侧 | 做法 |
|---|---|
| 调用点 | `sub rsp, stk` → 寄存器实参 `OP_ARG` → 栈实参 `OP_STKARG`（`[rsp+32+8k]`）→ `call` → `add rsp, stk` |
| `stk` | `32 + 8*栈实参数`，再补到 16 的倍数（`call` 那一刻 rsp 必须 16 对齐，否则被调方里的 Win32 API 用对齐 SSE 存取会 AV） |
| 被调方 | 第 5 个形参读 `[rbp + 48 + 8*nsaved + 8*si]`（见下面的坑） |

## 形参表：Fn 从"4 个槽"改成"nodes 里的一段记录"

旧的 `Fn` 硬编码 `p0..p3` / `p0t..p3t` 八个字段，天然只能存 4 个形参。
现在改成：

```quelmara
struct Fn { name, np, pbase, ret_t, body, nbody, nlocals }   // 16 字段 → 7 字段
```

`pbase` 指向 `nodes` 里连续 `np` 条 `E_FPARAM` 记录（`a`=名字 id，`b`=类型）。
`nodes` 本来就是"索引寻址 + 追加"的平坦表（块走 `nx` 链、不按区间遍历），
拿它当形参记录区不需要新增任何全局状态，也顺手把 `Fn` 从 16 字段瘦到 7 字段
（§7.17 之后虽然不再是硬限制，但少字段总归安全）。

实参侧同理：`E_CALL` 只有 `b/c/n/slot` 四个槽，第 5 个起挂在 `nx` 链上
（表达式节点的 `nx` 本来是空的——语句链是 `S_*` 节点自己的 `nx`）。

## 两个 ABI 坑（都是差分/崩溃逼出来的）

### ① 返回地址不在 `[rbp+8]` —— 序言是"先 push callee-saved，最后 push rbp"

第一版栈形参写死 `[rbp+48]`，5 个 callee-saved 全用上时正好读成"保存的 r15"：

```
$ ./qlmc.exe build args.qma && ./args.exe
5368714847          ← 应该是 15
```

因为 `push rbx; push r12..r15; push rbp; mov rbp,rsp` 之后：

```
[rbp]      = 保存的 rbp
[rbp+8]    = 保存的 r15     ← 不是返回地址！
...
[rbp+48]   = 返回地址       ← nsaved=5 时
[rbp+56..] = shadow space
[rbp+88]   = 第 5 个实参
```

所以正确偏移是 `48 + 8*nsaved + 8*si`。而 `nsaved` 要到**发射期**才知道，
所以 `OP_PARAMSTK` 的 `imm` 只记"第几个栈实参"，字节偏移由 `_emit_ir` 现算
（`nsaved` 存在 `fc.cells[C_NSAVED]`，`_emit_fn` 里算完 `used[]` 后写进去）。

### ② sret 指针必须最后才搬进 RCX；活到 call 的值必须 pin

聚合返回时 sret 指针走 RCX。旧代码在**求值实参之前**就 `OP_ARG → RCX`，
于是 `mk(sum6(...), 2, 3, 4, 5)` 里内层 `sum6` 的调用把 RCX 冲掉了——
`sret` 变成 `sum6` 的第一个实参（1），mk 把结果写到地址 1：

```
rc=139（Segmentation fault）
```

修法：`OP_ARG sret → RCX` 挪到**摆完所有实参之后**。同时 `OP_ARG` 本身会写
R8/R9（那正是临时值寄存器），所以 sret 地址与闭包地址都必须 `_pin`。
这个 bug 在 v2.20 就存在，只是之前没有"聚合返回 + 实参里带调用"的用例。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=43**（20 组用例 + 并行确定性 2 条；新增 `s16_stackargs`） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| `s16_stackargs.qma` | 16 行输出与 stage-0 逐字节相同：5/7 形参、str 夹在栈形参之间、聚合返回+5 实参、聚合形参+4 标量、5 形参递归、实参套调用 |
| 手工（stage-0 不支持，只能单独跑 qlmc） | `WriteFile`（5 实参，第 5 个 ov=0 走栈）成功写出文本并返回 1；`CreateFileA`（7 实参，路径不存在）返回 -1 |

`WriteFile` 那条特别有说服力：如果第 5 个实参摆错，`WriteFile` 会直接失败、
什么都不输出；实际输出了 `five args ok`，说明 4 个寄存器实参 + 1 个栈实参
全部就位。（stage-0 会拒绝把 `str` 当 ffi 实参，要求 `cstr(s)`，所以这条进不了
差分夹具。）

## 自举进度：第二个阻塞已清，下一个是 `const` 表达式

```
$ ./qlmc.exe build bootstrap/qlmc/qlmc.qma -o build/self.exe
（v2.28）qlmc: line 59: 本版最多 4 个形参       ← 已清
（v2.29）qlmc: line 236: const 只支持整型字面量  ← 下一个
```

line 236 是 `const TBL_SIZE = EN_HDR + 1 + 64 * EN_STRIDE`。qlmc 的 `const`
只认字面量，而常量之间做算术在真实代码里到处都是。**下一版做 `const` 的
编译期求值**：复用 `_expr` 解析出 AST，再用一个小 `_fold` 递归求值
（字面量 / 已定义的常量 / 一元 `-` `~` / 二元算术与位运算），遇到折不动
的节点 fail-fast。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `Fn` 改 `pbase` + 形参记录（`E_FPARAM`）、`_param_name/_param_type` 收 `fc`；形参/实参解析放开个数（实参第 5 个起挂 `nx` 链）；`_call_args` / `_emit_call_args` / `_emit_call_free`；`_lower_fn` 栈形参；sret 挪到最后 + `_pin`；4 条新 IR 指令 `OP_PARAMSTK/OP_STKALLOC/OP_STKARG/OP_STKFREE`；`_mov_store_rsp`（RSP 基址必须带 SIB）；`cells` 加 `C_NSAVED` |
| `tests/selfhost/s16_stackargs.qma` | **新增**：栈形参差分夹具 |
| `tests/qlmc_test.py` | 用例 19 → 20 |
| `docs/05-toolchain.md` | §1.11 改 S15；声明行改"形参不限个数"；不支持表换成「const 表达式」；坑表补 #25（nsaved 偏移）/#26（sret 最后 + pin）；顺手把坑表里一段旧的重复编号理顺成 27..31 |
| `docs/07-gaps.md` | §3 stage-1 行更新 |
| `docs/06-status.md` | §3.25 加 `s16` 行、体积与耗时更新 |

## 已知边界

- 栈实参一律按 8 字节整字传，没有"按值传 16 字节结构体"（聚合一律传指针）。
- 没有寄存器实参的"乱序利用"：实参严格按声明顺序占 RCX/RDX/R8/R9 + 栈。
- 栈实参区域每次调用都 `sub`/`add` 一次，没有"函数级预分配 + 复用"的优化。
- 仍然缺：`const` 表达式、f64、泛型、宏/反射、接口、`rc`/`Drop`、闭包捕获、
  `vec[vec[T]]`（§7.18）、map 扩容、聚合作容器元素、`mk(...).x` 这种对调用结果取字段。
