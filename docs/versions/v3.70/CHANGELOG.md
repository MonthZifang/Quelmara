# v3.70 — 把 §7.18 缺陷压缩到两条 IR 的 `cv` 值

- 日期：2026-11-01
- 影响面：`docs/07-gaps.md`（§7.18 第八次排查）
- 代码改动：**零**

## 关键进展

用上一版新增的 `addrdump`，在**一次编译内**定位到具体 IR。

`_prescan_imports` 有 555 条 IR，两个 stage-1 编出来**只有 2 条不同**：

| IR# | `S1_FULL`（坏） | `s1_real365`（好） | 含义 |
|---|---|---|---|
| 11 | `BINI a=7 b=43(SHL) imm=3` | `BINI a=7 b=43(SHL) imm=6` | `1<<3`=8 vs `1<<6`=64 |
| 68 | `BINI a=46 b=43(SHL) imm=3` | `BINI a=46 b=5(MUL) imm=56` | `46*8` vs `46*56` |

## IR#68 是决定性的

* good：`OP_MUL` by **56** —— `Fn` 是 7 字段，步长 `7*8 = 56`；
* bad：`OP_SHL` by **3** —— 折成了 `×8`。

强度削减的条件是"只有 2 的幂才折"：

```quelmara
if op == OP_MUL && cv > 0 && (cv & (cv - 1)) == 0
```

**56 不是 2 的幂，根本不该折。** 所以 `S1_FULL` 里 `cv` 的实际值是 **8**
（8 是 2 的幂，折成 `<< 3` 是正确的）—— 即 **`_ty_size` 在 `S1_FULL` 里
返回了 8，而不是 56/64**。

## 已排除的解释

| 假设 | 结论 |
|---|---|
| `_st_nf` 的 IR 不同 | ❌ 两边完全相同（`imm=66`） |
| `ST_STRIDE` 常量错 | ❌ 两边都是 66 |
| `stt` 里 struct 数不同 | ❌ 两边 `dump` 都报 8 个 |
| `_ty_size` 本身有 bug | ❌ 探针（7/8 字段 struct、`vec[P]`）两个编译器全对 |
| 运行期越界读 `stt` | ❌ stride 是编译期折叠的常量 |

## 矛盾点（下次的入口）

* 单独探针里 `_ty_size` 正确 → 返回 56/64；
* 但在 `_prescan_imports` 这个函数里就返回 8。

触发条件是**这个函数的上下文**。最可疑的是 `_prescan_imports` 里
`P` 字面量的 `stt: vec[int].new(1)` —— **只有 1 个元素的 stt**。

## 下次的第一件事

在 `_ty_size` 里加一行调试：

```quelmara
if ty >= TY_STRUCT && ty < TY_ENUM {
    let nf = _st_nf(fc, ty - TY_STRUCT)
    eprint("TYSIZE ty=" + ty.to_str() + " si=" + (ty-TY_STRUCT).to_str() +
           " nf=" + nf.to_str() + " len(stt)=" + len(fc.stt).to_str())
    return nf * 8
}
```

编 qlmc 自己，看 `vec[Fn]` 那次调用的 `nf` 和 `len(stt)`。

**如果 `len(stt)==1`，就确认是 `_prescan_imports` 的空 stt 导致 `_st_nf`
读到 1（`1*8=8`）—— 根因是"预扫描用的 P 没有 struct 表"。**

> 这个调试只需一次重建（约 11 分钟），比前八轮的任何猜测都直接。
