# v4.128 — div/mod 同源自除数融合（b78_sum_digits −34%）

- 日期：2026-11-23
- 任务：继续按"跑分最差且修得动"挑靶。b78_sum_digits 3.49×（Ubuntu CI），
  根因是 `x % 10` 与 `x / 10` 各发一整条有符号魔数除法链（~13 条符号修正），
  而 C 编译器（gcc/zig cc）把它们融合成**一次** `mulq`：先算 `q = x/10`，
  再用 `r = x - q*10` 得余数。这是纯优化器缺口，一轮可落地。
- 影响面：编译器（stage-1 优化 pass，不动调用约定 / ABI / vec 布局）

## 等价性（本版全部分量所在）

C 的截断除法恒满足：

```
x % d == x - trunc(x/d) * d
```

对负数、MIN_INT 都成立（逐值核过 -1000..1000 × d∈{3,7,10,13,100,1000003}）。
所以"商只算一次、余数用减法推"在 qlmc 的**有符号截断语义**下也正确 ——
这与 v4.122 的非负分析不同，不需要证明 x≥0。

## 实现（`_opt_divmod_fuse`，接在 `_opt_divc_unsigned` 之后）

判据（全满足才动）：

1. 同一基本块内（无 LAB / 跳转）有 `mr = x % d`（`OP_DIVC`，2≤d≤2^31-1）；
2. 其后、x 被其它指令改写之前，有 `q = x / d`（同源 x、同除数 d）；
3. `qdst` 在两条 DIVC 之间未被读（避免提前算改变可见值）。

命中时改写成 4 条连续 IR：

```
DIVC qnew, x, /d      ← 唯一的魔数链
BINI t, qnew, MUL, d  ← t = q*d
SUB  mr, x, t         ← mr = x - q*d（原 MOD 的 dst）
MOV  qdst, qnew       ← 原 DIV 的结果照旧给下游
```

新增的 `qnew`/`t` 显式钉回活跃区间（`fc.vstart`/`vend`），仿 `_opt_licm`。
一次只融一对后 return，让下一轮 `_opt` 再扫，避免插入导致下标漂移。
判据全是形状、不依赖 vreg 编号 → 不动点安全。

**踩过的两个坑**（都修掉后才过）：

1. 一开始用 `ndef[x]==1` 守卫 —— b78 的 x 被 MOV 和 DIV 各写一次，
   全局单定义会漏掉它。真正需要的只是"两 DIVC 之间 x 未改写"，基本块内
   扫描已证明，全局守卫过度保守。
2. 一开始把 SUB 插在 i+2、而 `mr` 的下游使用紧跟 i+1（b78 的
   `s = s + x%10`）——余数算晚了。三条指令必须在 i 处**连续发完**。

## 收益（本机 min-of-9，新旧 ELF 交替）

| 基准 | 旧 | 新 | 比值 |
|---|---|---|---|
| **b78_sum_digits** | 91.08 ms | **59.74 ms** | **0.656（−34.4%）** |

与先用源码改写（`let q = x/10; s = s + x - q*10`）量到的上限 0.662 一致 ——
说明 pass 把理论收益完整拿到了。全量只有 b78 一项 ELF 变化（5153→5063 B，−90），
其余 75 项逐字节不变，改动面极窄。

## 验证

| 项 | 结果 |
|---|---|
| 新旧 qlmc 编全量 76 基准到 ELF 并运行 | **76/76 校验和一致，零 MISMATCH** |
| 差分夹具 `s_unsigned_mod` / `s_unsigned_scope` / `s_nonneg_sound` / `s_ref` / `s25_divmod` | 5/5 stage-0 与新 qlmc 输出逐字节一致 |
| `python3 tests/qlmc_test.py --qlmc build/qlmc_v4128b.exe` | **PASS=134 FAIL=0** |
| `python3 tests/bootstrap_test.py --strict` | **PASS**：stage-2 可用且与 stage-1 逐字节等价（42/42 组），stage-2 == stage-3 不动点成立 |
| `python3 tools/dev/check_docs.py` | PASS |

## 已知边界 / 遗留

- 只融合**同一基本块**内、同除数、x 未改写的 DIV+MOD 对。跨基本块/带比较的
  形态（如 qlmc 自身 `m % 10 == 0; m = m / 10`）不动 —— 这也是自举不动点
  能直接成立的原因。
- 同源同除子的 DIV+MOD 只在 3 个基准出现（b57_pow_mod、b75_fib_matrix、
  b78_sum_digits），本轮只 b78 实际命中；b57/b75 的 DIV 与 MOD 之间隔着
  控制流，未满足同基本块判据。
- CI 权威基准见 run <待填>；本机数字只作粗判，不代表 CI 口径。
