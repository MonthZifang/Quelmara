# v4.123 — 非负值域分析的 soundness 修复（stage-0 静默算错）+ 编译器/CI 缺口收口

- 日期：2026-11-18
- 任务：修掉一次系统性审计发现的全部 P0/P1/P2 问题。核心是一条
  **正在产出错误结果**的缺陷：stage-0 的非负值域分析缺 soundness，
  让 `x / D`、`x % D` 在负被除数时静默算错。

## 1. P0：非负值域分析四处 unsoundness（`tools/stage0/`）

同一份源码，三个后端输出不一致——这正是"静默错编"的指纹：

```qma
fn f(flag: int, v: int) -> int {
    let mut x = v
    if flag == 1 { x = 0 }
    return x / 4
}
print(f(0, -9))      // C99 截断语义：-9/4 == -2
```

| 路径 | 修复前 | 修复后 |
|---|---|---|
| stage-0 `--target native` | **-3** ❌ | -2 ✅ |
| stage-0 `--target win`（PE，默认） | **-3** ❌ | -2 ✅ |
| stage-0 `--target c`（语义参照） | -2 ✅ | -2 ✅ |
| qlmc（自举编译器） | -2 ✅ | -2 ✅ |

四条独立根因，全部收口：

| # | 位置 | 缺陷 | 修法 |
|---|---|---|---|
| ① | `qlm_native.py` `arith` 的 `%` 分支 | `x % D`（D>0）**无条件**标非负。C99 取模是截断语义，余数与被除数**同号**（`-7 % 4 == -3`） | 只有被除数已证非负时才标；同时记上界 `D-1` |
| ② | `qlm_native.py` `if`/`while`/`for`/`foreach`/`match` 降级 | `dict(env)` 克隆了环境，但 `fn.nnv` 是**函数级共享集合** → 分支里写的 `x = 0` 泄漏到另一条路径 | 快照 + 汇合取**交集**（`_nnv_join`）；循环体出口用 `_nnv_loop_exit` 丢掉体内被写过的变量 |
| ③ | `qlm_native.py` 复合赋值 `%=` | 无条件把 `cur` 标非负 | 一律跟着 `tmp` 的真实标记走 |
| ④ | `qlm_opt.py` `analyze_ranges` 的 `x % D` 规则 | 对**任意** x 记 `[0, D-1]` → `opt_const_div` 换成**无符号魔数乘**、`opt_bounds_elim` 删掉越界检查 | 要求被除数已在 `ranges`/`nn` 里（即已证 `>= 0`） |

另有一条**回绕**导致的 unsoundness：`+` / `*` 的"两非负 ⇒ 结果非负"在
int64 回绕下不成立。`s = 0; while i < 50 { s = s*3 + 1 }` 会绕成负数，若
沿这条链继续标非负，`s % 1000003` 就走无符号快路径（实测 212086，C 是
**-138601**）。修法：非负事实**必须同时带上界**（`fn.nnub`），加法/乘法的
结果上界可证且 `< 2^62` 才继续传播。

### 1.1 循环归纳：修 soundness 不能把性能做成事故

"体内被赋值就作废事实"这条保守规则会让 LCG 类基准回退 20%+
（实测 b83 +21.3%、b26 +23.9%、b65 +19.3%）。但 `seed = (seed*C+K) % D`
这类循环携带变量**其实恒非负**，可以用归纳自己证：

`_nnv_loop_induction` 的四条前提（全满足才给上界 `D-1`）：
1. **进入循环时 `v >= 0`**（现场由 `_is_nonneg` 证明）；
2. 体内对 `v` 的赋值**恰好一次**，形如 `v = (v * C + K) % D`；
3. `C`、`K`、`D` 都是非负整数常量，`D >= 2`，`C > 0`；
4. `(D-1) * C + K < 2^62`（归纳步不溢出的不动点条件）。

> **前提 1 是第一版的 bug**：漏了它，`t = -7` 起的
> `t = (t*3+1) % 16` 会被误判成非负——截断余数在负被除数时**仍是负数**，
> 根本不会落进 `[0, D-1]`。实测 `tests/s_unsigned_mod.qma` 第 7 项从
> 真值 496 变成 500。补上前提 1 后回到 496。

### 1.2 验证

| 项 | 结果 |
|---|---|
| 新夹具 `tests/s_nonneg_sound.qma`（16 个断言，覆盖条件赋值 / 循环体 / 负余数 / int64 回绕 / 复合赋值） | 三后端 + qlmc **逐字节一致**，全部符合 C99 |
| `tests/s_unsigned_mod.qma`（v4.122 既有夹具） | stage-0 / qlmc 均为 `31404 202594 -52 -15 4947616 3500 496 19377` |
| `tests/s_unsigned_scope.qma`（v4.122 既有夹具） | stage-0 / qlmc 均为 `-3 0 0 3` |
| 全量 76 基准 stage-0 vs C 校验和 | **76/76 一致**（修复前 b45、b74 两项错） |
| `python tests/run_native_tests.sh` | **PASS=128 FAIL=0**（修复前 126/2） |
| `python tests/qlmc_test.py` | **PASS=133 FAIL=0**（含新增 nonneg_sound） |

### 1.3 删除测试逃生口

`tests/qlmc_test.py` 里的 `EXPECTED_OUTPUTS` 曾把 `unsigned_scope` 的期望值
钉成手写常量，注释写着"stage-0 Windows PE 在这个控制流形状上不一致，但
C/native 是对的"——那是**拿测试绕过被测 bug**：只要 stage-0 一直错，测试
就一直绿，而 CI 会一直红。bug 已修，逃生口删除，两个编译器回到"必须逐字节
一致"。

### 1.4 性能影响（stage-0 native，min of 5）

| 基准 | 修复前 | 修复后 | 变化 | 说明 |
|---|---|---|---|---|
| b83_lcg_random | 367.6ms | 367.8ms | +0.1% | 循环归纳保住 |
| b65_random_walk | 32.8ms | 32.1ms | −2.1% | 循环归纳保住 |
| b26_maxsub | 378.3ms | 373.8ms | −1.2% | 循环归纳保住 |
| b69_hash_fib | 86.6ms | 91.7ms | +5.9% | 分支汇合更保守 |
| b13_collatz | 398.1ms | 400.6ms | +0.6% | — |
| **b45_accumulate** | 51.7ms | 57.0ms | **+10.3%** | **这是正确性代价，不是回退** |
| **b74_accum_poly** | 175.8ms | 192.7ms | **+9.6%** | 同上 |

> b45/b74 的 `s = s*n + k` 内层循环**真的会溢出成负数**（实测前 10 万次
> 迭代里 50022 次 `s<0`），原来那 10% 是**靠算错换来的**无符号快路径。
> 这种"越快越错"的收益不该保留。

## 2. P1：CI / 发布缺口

| # | 问题 | 修法 |
|---|---|---|
| ③ | `bench/speed/go/bench_clock_{windows,other}.go` 是 untracked，但 `run.py` 拿它们构建、CI 又开了 `--require-complete` → 干净 checkout 上 76 个 Go 基准全挂 | 纳入版本控制。验证：两个 build tag 各自单编通过（`go build` linux/windows 交叉） |
| ④ | `docs/versions/v4.122/` untracked，但 `VERSION` 已是 4.122.0 → 干净 checkout 上 `check_docs.py` 直接 FAIL（版本号同源） | 纳入版本控制 |
| ⑤ | `build/qlmc.exe`（11-15 01:07）比 `bootstrap/qlmc/qlmc.qma`（11-15 14:43）旧 → `qlmc_test` 用陈旧二进制跑出 FAIL=1 | 从源码重建（**注意**：`build/` 是产物目录不是可信输入，见 `07-gaps.md` §7.47 的前科） |

## 3. P2：真实缺口

### 3.1 qlmc 定长数组补越界检查（`bootstrap/qlmc/qlmc.qma`）

`[N]T` 的下标降级直接发 `OP_ADDRX`，**没有任何检查**；而 vec（`_vec_check`）/
slice（`_slice_check`）/ str 三条路都有。于是 `Quelmara.toml` 的
`bounds_check = true` 对定长数组是**空承诺**（实测 `arr[5]` 读到
`4194436`、`arr[-2]` 读到 `0`，都不 fail-fast）。

新增 `_arr_check` + `_ty_arr_len`，形状与 `_slice_check` 一致。长度是编译期
常量，藏在类型码里（`TY_ARRAY + (n<<8) + elem`）。

> **踩坑**：`OP_JCMP` 的两个操作数**都必须是 vreg**，直接把 `int` 常量当
> vreg 传进去会读到无关槽位——第一版把**合法下标也拦了**。长度必须先
> `OP_CONST` 进一个临时值再比较。

`bounds_check = false` 时整段省掉（同 `_vec_check`）。

### 3.2 两套编译器的关键字表对齐（第 8 条）

stage-0 有 32 个关键字（`qlm.py:125`），qlmc 只有 25 个（`_kw_id`）。
差集里 `result` / `option` / `select` / `chan` / `arena` / `rc` / `impl` /
`interface` / `test` 被 qlmc 当**普通标识符**，于是同一个程序 stage-0 报
「期望 NAME」、qlmc 却编得过——`bench/speed/quelmara/b57_pow_mod.qma` 的
`let mut result = 1` 就是这样，导致该基准在 stage-0 列**永远编不出来**。

修法：qlmc 把这 9 个词登记成**保留字**（`K_RESULT`…`K_TEST`），子集缺语法
仍拒绝。`vec` / `map` **不在此列**——它们是上下文关键字（`T_NAME` + 紧跟
标点），登记成硬关键字反而会破坏既有解析。

`b57_pow_mod.qma` 同时把 `result` 改成 `r`（保留字当变量名本来就不合法）。

### 3.3 C 后端 `map[K]V` 的 str 键/值（GCC 14+ 阻断）

C 后端把 `const char *` 直接传给 `qlm_map_set(int64_t h, int64_t k, int64_t v)`
的整数形参。C99 允许隐式互转，但 **GCC 14+ 把 `-Wint-conversion` 升成 error**
→ 整条 `map[str]V` 路径编不过，`tests/run_native_tests.sh [16]` 在
ubuntu-latest（GCC 15）上红。

修法（两处，都是把既有隐含语义写明）：
- 运行时形参 `int64_t k` → `intptr_t k`（`qlm_map_set/get/has/del/set_n/
  get_n/find/hash`），运行期本来就靠 `(intptr_t)` 转换，**不改变任何行为**；
- 调用点给 str 键/值加显式 `(intptr_t)` 转换（`get` 侧早已有，`set` 侧漏了）。

验证：`tests/run_native_tests.sh [16] map[K]V` 从 2 FAIL 变 0 FAIL，整轮
**PASS=128 FAIL=0**。

## 4. 文档

- `docs/02-language.md` §2.1 补关键字表的**唯一口径**说明（上下文关键字、
  子集保留字、qlmc 的 4 个内建关键字）。
- `docs/06-status.md` 追加本版验证小节。

## 5. 未做的事（明确记录）

- **LICM 的 `return 0` bug**（`_licm_inv2`，见 `handoff/PERF-ROADMAP.md`）
  仍保留：直接启用会破坏自举不动点，需要值编号/支配关系级工程，不在本版范围。
- `bench/speed/quelmara/*.qma` 里 76 个基准全部用 `now_ns()`，而 **C 后端
  不支持 `now_ns`**（`now_ns` 只在自研后端实现）。所以 `--target c` 编不出
  任何基准产物——这是既有缺口，与 `bench/speed/c/` 下的手写 C 版本无关
  （矩阵里的 C 列用后者）。本版未改。
