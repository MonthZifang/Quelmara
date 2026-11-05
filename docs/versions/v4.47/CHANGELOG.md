# v4.47 — 拆出 `_map_cap`：map 和 vec 的 `[h+0]` 语义不同

- 日期：2026-11-05
- 任务：追查 vec 内联布局为什么会让 stage-2 静默早退。
- 结论：找到一个**真实的语义混用 bug**，已修，自举全绿。

## 发现

`bootstrap/qlmc/qlmc.qma` 里 `_vec_field(fc, h, off)` 同时被 vec 和 map 用：

| 类型 | `[h+0]` | `[h+8]` | `[h+16]` |
|---|---|---|---|
| **vec** | data 指针 | len | cap |
| **map** | **cap** | count | data |

`_vec_field(fc, h, 0)` 在 vec 上返回"数据块基址"，在 map 上却被当成
"容量"用 —— **同一个函数，`off=0` 的含义完全相反**。

以前能跑，纯粹是因为"`_vec_field` 的实现恰好是 `ADDRF h,0` + `LOAD`"，
而 map 的 cap 也恰好在 `[h+0]`，于是两个语义碰巧落到同一条指令序列上。

**一旦 vec 改成内联布局**（`[h+0]` 变成 len、data 挪到 `[h+16]`），
`_vec_field(h,0)` 就从"加载"变成"算 `h+16` 地址"——map 读容量拿到的是
一个指针，`_map_grow` / `_map_has` / `_map_del` 全部读到垃圾。

这解释了 v4.44/v4.46 两次 vec 内联尝试中 stage-2 的**静默早退**：
`irdump` 无输出、`dump` 正常、`print(42)` 也编不出——故障点在
lowering 里的 map 操作。

## 修法

新增独立函数 `_map_cap(fc, h)`，只做"加载 `[h+0]`"，替换 3 处混用：

* `_map_has`（`let cap2 = ...`）
* `_map_grow`（`let cap = ...`）
* `_map_del`（`let cap = ...`）

这三处原本都是 `_vec_field(fc, hp, 0)`。

## 验证

`_map_cap` 在当前 vec 布局下与 `_vec_field(h,0)` **行为完全等价**
（都是 `ADDRF h,0` + `LOAD`），所以这是**纯重构，不改语义**。

* 自举五级链：**42/42 + 不动点 PASS**
* 编译产物大小 4591616 字节（与改前同量级）

## 意义

这是 vec 内联布局的前置清理。做完这一步，vec 的 `off=0` 可以安全地改成
"算 `h+16` 地址"，不再牵连 map。

## 仍未做

vec 内联布局本体：加了 `_map_cap` 之后 **stage-2 仍然失败**，说明还有
别的混淆点（正在继续二分定位）。寄存器分配、SIMD 未动。
