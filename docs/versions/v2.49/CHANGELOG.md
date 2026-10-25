# v2.49 — `&&`/`||` 短路直接发跳转：`b9_json` 快 1.54 倍，代码体积 −8.9%

- 日期：2026-10-25
- 任务：严重优化性能与加速比（攻 §7.31 的最后一个大项：`b9_json`）
- 影响面：自举层（`_lower_cond` + 两个新操作码）/ 基准 / 文档

## 怎么找到的

`b9_json` 是当时最差的一项（6.6 倍）。把生成的代码 dump 出来数指令 —— `jws`
（跳白空格，JSON 里调用最频繁的函数）里这一段：

```quelmara
if c == 32 || c == 9 || c == 10 || c == 13 { p = p + 1 }
```

**编成了 93 条指令。** 一个字节的空白判断。

看代码就明白了：`_lower_cond` 只认 `E_BIN` 里的**比较操作码**，不认 `P_AND`/`P_OR`，
于是整个条件落到 `_lower_expr`，每个比较都要先物化成 0/1 再 `JZ`：

```
cmp  rax, 9
sete al
movzx rax, al
mov  r9, rax
mov  rax, r9        ← 纯搬运
cmp  rax, 0
setne al            ← 又把 0/1 重新规范化一遍
movzx rax, al
```

**六条"规范化"**，乘 3 个比较，再乘上循环 —— 这就是那 93 条。

## 修法：`_lower_cond` 认短路

给 `_lower_cond` 加 `P_AND`/`P_OR` 的分支，**直接发跳转，不物化布尔值**：

| 形式 | `if_false == 1`（假就跳 lab） | `if_false == 0`（真就跳 lab） |
|---|---|---|
| `A && B` | `cond(A, lab, 1)` + `cond(B, lab, 1)` | `cond(A, lend, 1)` + `cond(B, lab, 0)` + `LAB lend` |
| `A \|\| B` | `cond(A, lend, 0)` + `cond(B, lab, 1)` + `LAB lend` | `cond(A, lab, 0)` + `cond(B, lab, 0)` |

短路顺序与求值序和 `_lower_expr` 那版**完全一致**（左先右后），只是不再把布尔值
物化出来。`jws` 从 **93 条降到 37 条**。

顺带还修了另一处：`s[p]` 的地址计算是 `OP_ADD str, int`，而 `_opt_fuse` 只认
`ADDRF`/`ADDRX`/`ADDRXN`，所以它没被融合。新增 `OP_LOAD8I` / `OP_STORE8I`
（SIB scale = 0，即 `[a + b*1]`）：

```
以前：mov r9,str; add r9,p; mov rax,r9; movzx r10,[rax]     （4 条）
现在：movzx r10, [str + p]                                  （1 条）
```

注意 `OP_ADD` 也是 str 拼接用的，所以只在 `vty(dst) == TY_INT` 时才当地址用。

## 结果

| 基准 | v2.48 | **v2.49** | C | qlmc / C |
|---|---|---|---|---|
| **`b9_json`** | 46.8 | **30.3** | 7.1 | 6.6× → **4.3×** |
| `b8_threads1`（1.6 亿次） | 381.0 | 339.2 | 89.0 | 4.3× → 3.8× |
| `b8_threads4` | 101.7 | 86.8 | 43.8 | **加速比 3.91×** |
| `b5_string` | 85.5 | 80.5 | 57.7 | 1.4× |
| `b6_hash` | 39.2 | 43.0 | 45.3 | **0.95×**（仍快于 C） |
| 其余 | — | — | — | 噪声内 |

**代码体积**（对 v2.45 基线，15 个夹具合计）：**−8.9%**（13 119 → 11 791 条指令），
最好 `s14_vecgrow` **−21.3%** —— 那个夹具的 map 代码里全是 `&&`。

**stage-2 体积：395 776 字节**（v2.44 是 459 776，−14%）。

`&&`/`||` 在 qlmc 自己的源码里到处都是，所以这一版**编自己也变快了**。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=57 FAIL=0** |
| `python tests/bootstrap_test.py --strict` | **五级全 PASS**（不动点仍成立，stage-2 395 776 B） |
| `python bench/speed/run.py --reps 3` | 10 基准 × 4 语言，**40 个校验和一致** |
| 四道门 + `run_win_tests` | 全绿 / **PASS=290 FAIL=0 SKIP=1** |

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `_lower_cond` 加 `P_AND`/`P_OR` 短路分支；新增 `OP_LOAD8I`/`OP_STORE8I` + `_fuse_op`/`_opt_fuse` 支持 `OP_ADD` 当基址 |
| `bench/speed/RESULTS.md` | 更新四语言表 + v2.48→v2.49 对比列 |
| `docs/05-toolchain.md` | §1.11 优化层补"短路直接跳转"一条 |
| `docs/07-gaps.md` | §7.31 (c) 改写：`b9_json` 6.6× → 4.3×，剩下的瓶颈重定位 |
| `docs/06-status.md` | §3.25 更新到 v2.49 |

## 下一步（已确认的瓶颈，没做）

**`RDI`/`RSI` 可以当第 6/7 个变量寄存器。** Win64 里它们是 **callee-saved**，
现在只用了 `RBX + R12-R15` 五个。`jval` 这种 6 个局部变量的函数会把 `p` 溢出到
帧槽，热循环里每轮两次内存往返。

障碍：`__memcpy`/`__memset` 系列用 `RDI`/`RSI` 传参（5 处调用点），`__f64_fmt`
内部也用 —— 要一起改。收益估计：`b9_json` 与 qlmc 自己再快 10–15%。
