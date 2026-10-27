# v2.83 — 解释器补 enum + match（载荷绑定 / 通配臂 / 块臂里的 return）

- 日期：2026-10-27
- 任务：解释器子集第 4 步
- 影响面：`bootstrap/interp/qlm_interp.qma`、`tests/t156_interp_enum.qma`、
  `tests/interp_test.py`

## 补了什么

```quelmara
enum Light { Red  Yellow  Green  Flashing(rate: int) }

let f = Light.Flashing(rate: 7)          // 构造（命名实参与裸实参等价）
print(match f {                          // 作表达式
    Light.Flashing(rate) => rate * 3
    _ => -1
})
match c {                                // 作语句（臂体是块）
    Light.Green => { total = total + i }
    _ => { total = total - 100 }
}
```

## 表示

**枚举值 = 元素池里两格 `[变体槽号, 载荷]`**，`Val` 只存起点。
- 变体槽号是 `variants` 池里的**槽位偏移**（每 3 格一个变体：enum 号 /
  变体名 / 载荷名），全局唯一，match 直接比这个整数。
- 载荷槽恒存在（无载荷时放 void），所以 `match` 取载荷不用判空。

**臂池 `arms`** 每 3 格一条：`(变体槽号|-1, 绑定名|-1, 体节点)`，`-1` 是通配臂。

## 三个坑

1. **`match` / `enum` 两个关键字漏了**。我在 lexer 里加了 `K_MATCH` 常量却忘了在
   `kw_id` 里注册，于是 `match` 被当成普通标识符 —— 报的是
   "顶层只认 fn / const / struct / module / import"（`enum` 同理）。教训：
   **加关键字要同时改三处**：常量、`kw_id`、`parse_program` 的分派。
2. **`=>` 是新的双字符记号**。`=` 后面跟 `>` 在别的上下文里不存在，所以可以
   直接吞成 `O_FATARROW`；顺序上必须排在单字符 `=` 之前。
3. **块臂里的 `return` 要能从表达式里带出去**。`ev` 只返回值、不返回控制流，
   而 `match c { X => { return 1 } }` 是常见写法。做法：`St` 加一个
   `flow: vec[int]`，块臂执行完若 `ex` 返回 1 就写进 `flow`；`exec_range`
   每条语句后检查一次 —— 语句本身已经执行完，所以"跳过后续语句"的语义正好。

## 验证

```
[PASS] t156_interp_enum.qma: 14 行输出逐字节一致，rc=0
INTERP: PASS=11 FAIL=0
```

夹具钉的六条：无载荷 / 带载荷（int、str）、命名实参与裸实参、
match 作表达式与作语句、通配臂与载荷绑定、**块臂里的 `return`**（含早返回与
正常返回两条路径）。
