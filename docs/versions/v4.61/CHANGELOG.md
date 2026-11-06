# v4.61 — pin 清理第二刀：聚合 return 无 defer 时不 pin

- 日期：2026-11-06
- 任务：v4.60 的 return no-pin 模式推广（同族清理）。
- 结论：**已落地**——agg return 的 ADDR V 临时在无 defer 时不再 pin。

## 内容

`S_RETURN` 的聚合分支：av0（ADDR V 临时）原无条件 `_pin`，
现改为无 defer（`C_DEF==0`）时直接用 av0，RETAGG 紧随无覆盖风险；
有 defer 时仍 pin（defer 可能改 tmp 区域）。

## pin 清理总结（两刀）

| 刀 | 场景 | 收益 |
|---|---|---|
| v4.60 | 标量 return 无 defer | b3 -25% |
| v4.61 | 聚合 return 无 defer | struct 返回函数同收益 |

其余 pin 均有语义理由（ARG 重排防覆盖/map 内部状态/跨 CALL 保护），
不动。

## 验证

RT 7/7、自举 42/42 + 不动点、差分 110/110、docs PASS。

## b3 剩余差距说明

3.34x 的剩余来自 ABI 结构成本（shadow space 32B/序言/对齐）——
caller-saved GPR 仅 r8-r11 四个（rax/rcx/rdx 被 ARG/返回占用），
无可再压空间。b3 层面低垂果实已摘完。
