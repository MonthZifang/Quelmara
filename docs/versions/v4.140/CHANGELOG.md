# v4.140 — 拷贝传播跳过 NOP 找消费者（b70 −12.2%、b61 −8.4%）

- 日期：2026-11-26
- 任务：v4.139 普查认为"发射器层已采完"，但**拷贝传播的一个匹配缺陷**被漏掉了：
  `_opt_copy` 只检查 `i+1` 那一条 IR 是否是 MOV 的消费者。**MOV 与消费者之间
  若夹着 NOP，匹配就永远失败** —— 而 `_opt_empty_jumps` 删跳转、`_opt_load_hoist`
  插指令、内联都会留下 NOP 空位。
- 影响面：编译器（stage-1 优化 pass `_opt_copy`，不动 IR 语义 / 发射器）

## 缺陷实例（b70_lin_search，v4.139 产物）

```
113  LOADD  dst=114        ← load_hoist 外提的 vec 数据指针
114  LAB    (循环头)
...
121  MOV    dst=89, a=114  ← 拷贝
122  NOP                   ← ← ← 这一条 NOP 让匹配失败
123  LOADX  dst=91, a=89   ← 真正的消费者
```

于是 `mov r9, r8` 白留（`LOADX` 本可直接用 `a=114`）。v4.140 修复后 IR 变成
`LOADX dst=91, a=114`，省掉这条 mov。

## 实现

`_opt_copy` 找到 MOV 后，先把 `ni` 从 `i+1` 起**跳过所有 `OP_NOP`** 再取消费者；
其余判据（`use[d]==1`、`ndef[d]==1`、非聚合、`vpin==0`、`nx.dst != d`）全部不变。

## 等价性（为什么 sound）

- 被跳过区间**只有 `OP_NOP`**（循环条件保证），NOP 不读不写任何 vreg；
- `use[d]==1` 保证 MOV 的目的 `d` 全函数只被读这一次，且就是找到的那个消费者；
- 所以把消费者的操作数从 `d` 换成源 `a` 与原来逐步等价；`use[d]` 置 0、MOV 改 NOP。

## 收益（本机 min-of-5，v4.138 → v4.140）

| 基准 | v4.138 | v4.140 | 比值 |
|---|---|---|---|
| **b70_lin_search** | 2052.1ms | **1801.4ms** | **0.878（−12.2%）** |
| **b61_cache_scan** | 24.06ms | **22.04ms** | **0.916（−8.4%）** |
| b23_lcs | 38.30ms | 37.22ms | 0.972（−2.8%） |
| b4_array | 51.25ms | 50.33ms | 0.982（−1.8%） |
| b27_sieve | 613.4ms | 605.4ms | 0.987（−1.3%） |
| b54_merge_sort | 37.58ms | 37.00ms | 0.985（−1.5%） |
| b28_matrix | 191.1ms | 190.5ms | 0.997（噪声内） |

共 **11 项 ELF 变化、合计 −54 字节**；b28/b4 等的 mov 消除属附带。

## 验证

| 项 | 结果 |
|---|---|
| 新旧 qlmc 编全量 76 基准到 ELF 并运行 | **76/76 校验和一致** |
| `python3 tests/qlmc_test.py --qlmc build/qlmc_v4140.exe` | **PASS=136 FAIL=0** |
| `python3 tests/bootstrap_test.py --strict` | **PASS**：stage-2 与 stage-1 逐字节等价（42/42 组）、stage-2 == stage-3 不动点成立 |
| `python3 tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- 只跳过 NOP；若 MOV 与消费者之间有真实指令，仍不合并（正确性优先）。
- 其余 `_opt_copy` 判据不变（单定义、单使用、非聚合）。
- CI 权威基准待推送后实测。
