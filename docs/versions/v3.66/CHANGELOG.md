# v3.66 — `_ty_size` 区间判定补上界（潜伏已久的静默错编）

- 日期：2026-11-01
- 任务：用户要求"继续"。在排查 §7.18（`vec[vec[T]]`）时**顺手抓到一个
  独立的真 bug**，它不属于类型表方案，单独修掉。
- 影响面：`bootstrap/qlmc/qlmc.qma`（`_ty_size` 一个函数）
- 代码改动：**7 行**（一个区间判定）

## 问题

```quelmara
fn _ty_size(fc: FnCtx, ty: int) -> int {
    if ty >= TY_ARRAY { ... }
    if ty >= TY_SLICE && ty < TY_ARRAY { return 16 }
    if ty >= TY_ENUM { return 16 }        // ← 没有上界！
    if ty >= TY_STRUCT { return _st_nf(...) * 8 }
    return 8
}
```

类型码区间：

```
TY_INT..TY_F64  0x0..0x5
TY_STRUCT       0x1000
TY_ENUM         0x2000
TY_VEC          0x8000      ← 落在 TY_ENUM 之上！
TY_MAP          0x10000
TY_SLICE        0x20000
```

`TY_VEC(0x8000) > TY_ENUM(0x2000)`，而那条判定**只卡下界**，于是
**vec / map 句柄被算成 16 字节**（正确是 8）。

## 为什么潜伏这么久没暴露

调用 `_ty_size` 的地方**一直传元素类型**（标量 / struct / enum），
从没传过 vec 类型本身 —— 所以那条错误分支永远走不到。

一旦有人传 vec 类型（例如支持 `vec[vec[T]]` 之后，`_vtypes_elem` 会返回
一个 vec 类型码），元素步长立刻翻倍：实测 `.text` 里 `shl r9, 3`（×8）
变成 `shl r9, 4`（×16）—— **不崩、不报错，只是算错**。

## 改动

```quelmara
// vec / map 都是**句柄**（8 字节）。必须在 TY_ENUM 之前判 ——
// TY_VEC = 0x8000 > TY_ENUM = 0x2000，否则会被下面那条吃掉。
if ty >= TY_VEC && ty < TY_SLICE { return 8 }
if ty >= TY_ENUM && ty < TY_VEC  { return 16 }
if ty >= TY_STRUCT && ty < TY_ENUM { return _st_nf(fc, ty - TY_STRUCT) * 8 }
```

**三条都改成两头都卡**（`>= lo && < hi`）。

## 验证

| 命令 | 结果 |
|---|---|
| stage-1 编 qlmc 自己 | ✅ rc=0 |
| **stage-2 编 tiny** | ✅ **rc=0**（修前 rc=5） |
| qlmc 差分全量 | **40/40 PASS** |
| 四个文档门禁 | 全 PASS |

## 教训

**区间判定必须两头都卡。** 只卡下界的写法在本项目里已经出过多次问题：

* v3.14 的 LICM `readonly` 判据（自旋等待被外提成死循环）；
* §7.18 的 `_ty_size`（本条）；
* §7.18 的类型码撞区间（`TY_VEC + elem` 进位到 `TY_MAP`）。

这类缺陷的共同特征：**不崩、不报错、只是结果错**，而且**潜伏期极长**
（因为触发条件罕见）。写区间判定时多写一个上界，成本 3 个字符；
漏写的代价是一次跨多轮的排查。
