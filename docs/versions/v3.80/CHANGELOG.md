# v3.80 — 栈实参顺序：先存栈、后摆寄存器（收 §7.8）

- 日期：2026-11-02
- 任务：收 §7.8（v1.70 写 `std/cookie` 时发现，一直靠"把 API 设计成 5 参"
  绕过去）。
- 影响面：`tools/stage0/qlm_native.py`（`_emit_call_args`）、
  `tests/selfhost/s44_wideargs.qma`（新增夹具）
- 代码改动：约 25 行

## 症状

```quelmara
fn s7(a,b,c,d,e,f: int, s: str) -> str { return s + a.to_str() }
fn main() {
    print(s7(1, 2, 3, 4, 5, 6, "x"))      # 正常输出 x1
    print(s7(7, 8, 9, 10, 11, 12, "y"))   # 整段程序无输出 / 崩溃
}
```

**触发条件**：参数个数 = 7 且第 7 个是 `str`（走栈传参），且该函数被调用
**≥ 2 次**。7 个 int、8 个 int、5 个参数都正常。

v1.70 记录的症状是"整段程序静默不执行、退出码 0"；v3.80 实测已经退化成
**page fault**（读 `0xfffffffffffffffa`）—— 同一个缺陷，只是寄存器分配
变了，崩法不同。

## 真因：栈实参与寄存器实参的写入顺序反了

`_emit_call_args` 原来是：

```python
moves = [(self.src_move(a), ("r", ARG_REGS[i])) for i, a in enumerate(reg)]
self.parallel_move(moves)          # 先摆前 6 个寄存器实参
if stk:
    self.enc.alu_ri("sub", RSP, 8 * len(stk))
    for j, a in enumerate(stk):    # 再写栈实参
        self.mat(SCRATCH, a)       # <- 此时 a 可能已被覆盖
```

**栈实参的值可能正住在某个 `ARG_REGS` 里**（临时值、变量都可能）。
`parallel_move` 把这 6 个寄存器覆盖掉之后，`self.mat(SCRATCH, a)` 再读 `a`
拿到的是**别人的值**。

单次调用时编译器恰好没把那个 `str` 放进 `ARG_REGS`，所以看起来"一次正常"
—— 这就是为什么这条缺陷藏了这么久。

## 修法：把 `sub rsp` + 存栈提到 `parallel_move` 之前

```python
if stk:
    self.enc.alu_ri("sub", RSP, 8 * len(stk))
    for j, a in enumerate(stk):
        ...
        self.mat(SCRATCH, a)       # 此时 ARG_REGS 还没被动过
        self.enc.mov_mr(RSP, 4, 0, 8 * j, SCRATCH)
moves = [(self.src_move(a), ("r", ARG_REGS[i])) for i, a in enumerate(reg)]
self.parallel_move(moves)
```

`sub rsp` 不影响 `rbp` 相对寻址，所以先开栈区不会让任何实参取值失效。

**这与 qlmc 里 `_emit_call_args` 的注释是同一条教训**（v2.33 实测
`ReadFile(h, buf, sz, got, 0)` 的第 5 个实参被写成了 sz）。qlmc 早就写对了，
stage-0 一直没改。

## 验证

| 判据 | 结果 |
|---|---|
| `s7(...)` 调两次 | ✅ page fault → `x1` / `y7` |
| `s44_wideargs` 与 qlmc 逐字节一致 | ✅ **8/8** |
| 8 个 int / 5 参夹 str / 10 个参数 | ✅ 全对 |
| 栈实参是运算结果 / 函数返回值 | ✅ 全对 |
| 全套差分 | ✅ **46/46** |
| irdiff | ✅ **121/121** |

`s44_wideargs` 覆盖六种形态：8 个 int（全栈）、7 参第 7 个是 str 调三次
（原缺陷触发条件）、5 参中间夹 str（寄存器路径，钉住别退化）、栈实参是
运算结果（临时值，最容易被覆盖）、栈实参是函数返回值、10 个参数（3 个栈
实参）。

## 附：本地跑不了完整 Windows 套件

`tests/run_win_tests.py` 内部会重建 qlmc（约 10 分钟）再跑 350+ 项，
2500 秒的超时不够（`EXIT=124`）。这类验证交给 CI 的 windows 作业。
本地用分段方式覆盖：差分 46/46 + irdiff 121/121 + 覆盖率门禁。
