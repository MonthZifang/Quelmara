# v3.75 — 第 5 个及以后的 f64 形参：分配器不给跨调用的 f64 分 XMM

- 日期：2026-11-02
- 任务：收 §7.33（v2.80 写解释器时撞上的缺陷，一直靠"别让 f64 出现在
  第 5 个及以后的位置"绕过去）。
- 影响面：`bootstrap/qlmc/qlmc.qma`（分配器 + `OP_STKARG` 发射）、
  `tests/selfhost/s41_f64stk.qma`（新增差分夹具）、`tests/qlmc_test.py`
- 代码改动：约 60 行

## 症状

```
fn f(a: int, b: int, c: int, d: int, e: f64) -> f64 { return e }
print(f(1, 2, 3, 4, 3.5))     # stage-0: 3.5   qlmc: 0
```

不崩、不报错，只是**数值不对**。原始形态更隐蔽：七参数函数的第 6 个
形参是 f64，实参传结构体字段，函数里读出来是 `2.017232e-316` 这种
denormal —— 典型的"栈上实参没按 double 落位"。

## 真因：分配器对 f64 的 XMM 分配有个 `crosses == 0` 前置条件

`_alloc` 里 f64 的寄存器分配长这样：

```quelmara
if crosses == 0 {              // crosses = 区间内是否跨过调用
    if fc.vty.get(v) == TY_F64 {
        // 分 XMM0..XMM3（临时池）
    }
}
```

**`CALL` 的返回值，其活跃区间必然包含那次调用本身**，所以 `crosses > 0`
恒成立 —— f64 返回值从来拿不到 XMM，被分到通用寄存器。之后：

* `_store_rax` 按 `dloc < XLOC` 走 `mov r63, rax`；
* 中途任何按 int 语义处理它的指令（比较、算术、spill）都会毁掉位模式；
* 接收侧 `OP_PARAMSTK` 再 `movq xmm, rax` 转回来时，已经是垃圾。

## 修法：跨调用的 f64 分**非易失** XMM6..XMM15

```quelmara
if crosses > 0 && fc.vty.get(v) == TY_F64 {
    let mut nx2 = _nxf_get(fc)
    if nx2 < N_XMMVAR {
        fc.vloc.set(v, XLOC + XMM_VAR0 + nx2)
        _cell_set(fc, C_NXF, nx2 + 1)
        placed = 1
    }
}
```

XMM6-15 在 Win64 里是非易失的，`_emit_fn` 的序言/尾声会按 vloc 里实际
用到的编号统一 `movups` 保存恢复（v2.55 就写好了，不用改）。原来的
`crosses == 0` 分支保留给临时值（用易失的 XMM0-3，省掉保存开销）。

## 顺带修：`OP_STKARG` 不认 XMM

发送侧把第 5 个及以后的实参写栈时，`OP_STKARG` 只有两条路：

```quelmara
if aloc > 0 {  _mov_store_rsp(...)  }        // 通用寄存器
else        {  _mov_load + _mov_store_rsp }  // 帧槽
```

**没有 XMM 分支**。值住在 XMM 里时，`aloc - 1` 是 XMM 编号，会被当通用
寄存器号编进 `mov [rsp+disp], r64` —— 存进去的是垃圾。

补一个 `movsd [rsp+disp32], xmm`（`F2 0F 11 /r`）编码器：

```quelmara
fn _sse_store_rsp(code: vec[int], disp: int, x: int) {
    _b(code, 0xF2)
    _rex2(code, 0, x, RSP)
    _b(code, 0x0F)
    _b(code, 0x11)
    _modrm_sib(code, 2, x)      // RSP 当基址必须有 SIB 字节
    _w32(code, disp)
}
```

**不能复用 `_sse_mem`**：它用 `_modrm` 而非 `_modrm_sib`，base=RSP 时缺
SIB 字节，disp32 会被 CPU 当 SIB 解析，整条指令错位。

帧槽里的 f64 **不需要**特殊处理：`mov rax, [rbp+slot]` + `mov [rsp+imm], rax`
搬的就是那 8 字节位模式，对 f64 完全正确。

## 验证

| 判据 | 结果 |
|---|---|
| `f(1,2,3,4,3.5)` | ✅ `0` → `3.5` |
| `s41_f64stk` 与 stage-0 逐字节一致 | ✅ **6/6**（23 字节输出完全相同） |
| 全套差分 | ✅ **94/94**（含新增 s41） |
| 自举等价性 | ✅ **35/35** |
| 不动点 stage-2 == stage-3 | ✅ PASS |
| 覆盖率 | ✅ **69/69** |

`s41_f64stk` 覆盖五种形态：6 参（第 6 个是 f64）、7 参（第 6/7 都是 f64）、
混合 int/f64 交替、从 struct 字段读出后传（原缺陷形态）、运算结果直接
当栈实参（值在 XMM 临时寄存器里）。

## 顺带修：差分脚本跑产物的两处路径

`tests/qlmc_test.py` 里跑产物的两处（第 231、260 行）直接
`subprocess.run([exe])`，既没走 wine（Linux 上 binfmt 的 `MZ` handler
会重复 `argv[0]`），也没补执行位（stage-0 写出的文件默认没有 x 位）。
本版统一成 `_exe_runner()` + `chmod 0o755`。

**这个缺陷只在 Linux 上暴露** —— 它让整个差分套件在 Linux 上根本跑不完
（`PermissionError` 直接中断），而 CI 跑在 Windows 上所以一直是绿的。
