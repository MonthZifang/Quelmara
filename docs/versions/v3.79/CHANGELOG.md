# v3.79 — 比较 / 逻辑结果一律按 bool 打印（收 §7.22）

- 日期：2026-11-02
- 任务：收 §7.22（v2.33 发现，一直登记为"已知差异"）。
- 影响面：`tools/stage0/qlm_native.py`（常量折叠）、`bootstrap/qlmc/qlmc.qma`
  （比较 / `!` 的类型）、`tests/selfhost/s43_boolprint.qma`（新增夹具）
- 代码改动：约 60 行

## 症状：stage-0 自己就不一致

```quelmara
let n = 3
let i = 0
print(i + 1 < n)   # true（运行期比较）
print(1 < 2)       # 1   （编译期折叠）   <- 同一个表达式形态，两种输出
```

qlmc 以前为了对齐，把所有比较都收成 int（打 `1`）。**那是把一个不一致
固化进契约** —— 同一个语言构造在同一个编译器里两种输出，本身就是缺陷。

## 修法：两边都收 bool

### stage-0：折叠结果也要带 bool 标记

`arith()` 里的常量折叠直接返回 `("imm", 0/1)`，绕过了 `_mark_bool`：

```python
if op in cmp_map:
    return ("imm", 1 if cmp_map[op] else 0)     # 以前
```

改成折成一个**带标记的临时 vreg**（一条 `mov` 而已，省下的指令数基本不变）：

```python
d = fn.new_v()
fn.emit("mov", d, ("imm", 1 if cmp_map[op] else 0))
return self._mark_bool(fn, d)
```

`!` 的折叠同理（`print(!true)` 以前打 `0`，现在打 `false`）。

### qlmc：比较与 `!` 返回 TY_BOOL

三处：
* `_emit_bin` 的标量比较分支（`OP_CMP`）→ `TY_BOOL`；
* `_emit_bin` 的 f64 比较分支（`OP_FCMP`）→ `TY_BOOL`；
* `_emit_bin` 的聚合比较分支（v3.78 新增）→ `TY_BOOL`；
* `E_UN` 的 `!`（两处：`_lower_expr` 与 `_lower_into`）→ `TY_BOOL`
  （`-` / `~` 仍是 int）。

## 顺带修：v3.78 聚合比较的**分配器复用缺陷**

排查中发现 v3.78 的聚合 `==` 在某些上下文里恒为 true。根因是我创建的
两个基址临时值（`la` / `ra`）**没有 `_pin`**：分配器允许把 `ra` 与后面的
临时值复用同一寄存器，于是 `ARG ra` 传了别人的值 —— `mem_cmp` 变成
"自己和自己比"，恒等。

修法：两处都 `_pin`（`_pin` 生成的是**变量**，`vpin=1`，分配器不会当临时值
复用）。

> **踩到的坑**：`setcc` 的判据第一次写成 `0x04`。`_cmp_cc(P_EQ)` 返回的是
> **jcc** 形态 `0x84`（`je`），`setcc` 是 jcc + 0x10 = `0x94`（`sete`）。

## 一个**未修**的发现：聚合比较对布局敏感

`s43_boolprint` 最初把聚合比较也放进去，结果**只有 21 行输出错**，而
把同样的代码单独拿出来（`ag5.qma`）就正确。逐步二分后确认：

* 代码完全相同（`diff` 去掉注释后无差异）；
* IR 结构完全相同（只是帧槽号不同）；
* 加一条 `print(p1.x)` 就变正确。

**这是分配器布局敏感缺陷**，与 §7.4 / §7.5 同类（"多一条指令就改变结果"）。
它与本版的 bool 口径无关，因此把聚合部分从 `s43` 移除（挪到 `s42_aggeq`
单独覆盖），并在 §7.5 记下这次的新证据。

## 验证

| 判据 | 结果 |
|---|---|
| `i + 1 < n` / `1 < 2` | ✅ 都打 `true` |
| `!(1 == 2)` / `!true` | ✅ 都打 `true` / `false` |
| `&&` / `\|\|` | ✅ 不受影响（本来就是 bool） |
| f64 比较 / str 比较 | ✅ `true` / `false` |
| `s43_boolprint` 与 stage-0 逐字节一致 | ✅ 20 行 IDENTICAL |
| 全套差分 | ✅ **46/46** |
| irdiff | ✅ **121/121** |
| `s42_aggeq`（v3.78 的聚合断言） | ✅ 仍通过 |
