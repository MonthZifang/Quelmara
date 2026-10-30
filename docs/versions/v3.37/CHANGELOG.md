# v3.37 — qlmc 加 lib 模式：`std/` 覆盖率 0/70 → 37/70

- 日期：2026-10-30
- 任务：用户要求"`tools/stage0/*.py` 里的编译器核心全部改用自研语言"
- 影响面：**核心（Quelmara 源码）** `bootstrap/qlmc/qlmc.qma`
  （lib 模式 + `mem_chr` / `str_from_mem` 内建），新增覆盖率门禁
- 版本：按 `00-convention.md` §5.1 建版本目录

## 起点：v3.36 留下的最大阻塞

v3.36 把 qlmc 编 `std/` 的失败按原因分类，最大的一项是 **30 个模块
"没有 main"** —— 那是功能缺失（qlmc 只做 program、不做 lib），
不是内建缺失。

## lib 模式

新增 `qlmc build X.qma -lib -o out.exe`：

* **不要求 main**；
* **不发真正的入口**，只放一条 `ret`。

### 为什么仍要放一条 `ret`

PE 的 `AddressOfEntryPoint` 必须指向 `.text` 内的合法位置（不能是 0、
不能越界），否则某些加载器会拒绝映像。一条 `ret` 同时满足两个约束：
合法位置 + 即使真被执行也立刻返回（不会跑飞）。

### 改了什么

1. `main()` 解析 `-lib` 参数；
2. `Ctx` 加 `is_lib` 字段（**注意 `Ctx` 被定义了两次**，第 605 行与
   第 2679 行，实际用的是后者 —— 第一版只改了前者，编译时报
   `结构体 Ctx 没有字段 is_lib`）；
3. `_gen_entry` 在 lib 模式下只发 `ret`；
4. `_target_of` 的 `FK_FN`/`id == -1` 分支：lib 模式不该被问到入口，
   真问到说明有别的路径依赖 main，给明确诊断而不是去查 main。

顺带把"没有 main"的报错改成 **"没有 main（编库请加 -lib）"** ——
让用户知道有这条路。

## 补 `mem_chr`（std/ 5 个模块用）

`mem_chr(p, n, byte)` 返回**首个匹配字节的下标**，找不到 -1，`n` 是上界。

需要新的运行库例程 `RT_MEMCHR`。顺带把 rt_pos 的大小改成 `RT_COUNT`
常量 —— 原来硬编码 24 且注释写"加例程时这里要一起改"，正是容易漏的地方。

### 踩的坑：REX 字节写错

第一版 `cmp r9, rdx` 编码成 `4D 39 D1`：

* `39 /r` 是 `cmp r/m, r`（不是 `cmp r, r/m`）；
* `D1` = `mod=11 reg=010(rdx) rm=001(rcx)` —— 这是 `cmp rcx, rdx`；
* 需要 `rm=r9` 则要 REX.B（不是 REX.R）。

正确是 `49 39 D1`（REX.W|B）。症状很典型：`mem_chr(p,4,99)` 返回 -1
而不是 2 —— 循环上界比错了，只跑了 1 轮。

**这个 bug 是靠 stage-0 / qlmc 对拍抓到的**：同一个夹具两边编，
stage-0 给 `[1, 2, -1, -1]`，qlmc 给 `[1, -1, -1, -1]`。

## 补 `str_from_mem(data, n)`（std/ 2 个模块用）

语义与 `mem_str` 完全相同（拷 n 字节、补 NUL、带长度头），直接复用
`_bi_mem_str`。

## 结果

| 指标 | v3.36 | v3.37 |
|---|---|---|
| **qlmc 覆盖 `std/`** | **0 / 70** | **37 / 70** |
| 缺内建类失败 | 12 | 约 18（类别变了） |

覆盖率涨的 37 个里，30 个是 lib 模式直接解开的，7 个是 `mem_chr`。

## 新增门禁：`tools/dev/qlmc_coverage.py`

这是本版**最重要的产出**。用户要"编译器核心改用自研语言"，
那件事的进度不能靠感觉，得有一个**会变的数字**。

脚本用 qlmc 逐个编译 `std/**/*.qma`（lib 模式），与 `BASELINE` 比较：

* 低于基线 -> **FAIL**（退化了）
* 等于基线 -> PASS
* 高于基线 -> PASS，并提示"该上调 BASELINE 了"

基线是**下限不是目标**，作用是防止"改坏了没人发现"。提升覆盖率时
把 BASELINE 一起上调 —— 这是有意的摩擦，让人看见进步。

已挂进 `run_win_tests.py`（`case_qlmc_coverage`），代价约 40 秒。

## 夹具

`tests/t181_qlmc_lib.qma`：

* `mem_chr` 基本语义（找得到 / 找不到 / 重复字节返回第一个）；
* **`n` 是上界不含**（`mem_chr(p,2,99)` 找不到 index 2）；
* **`n = 0` 必须找不到**（不能越界读）。

用 stage-0 与 qlmc **两边各编一遍**，行为必须一致 —— 上面那个 REX bug
就是这条对拍抓到的。

## 回归

全量 Windows 回归 PASS=355 FAIL=0 SKIP=0（v3.36 是 352，新增 3 条：
覆盖率门禁 + `qlmc_lib` + `t181` 进 `parsediff`）。

## 下一步

覆盖率 37/70 的剩余失败已经分散：

| 数量 | 原因 |
|---|---|
| 4 | vec 方法不全（`.clear` / `.pop` …） |
| 2+2+2 | `xmm_load` / `mem_diff` / `mem_xchg` 缺内建 |
| 1×N | `tcp_listen` / `udp_*` / `file_size` / `wall_ms` 等网络与系统内建 |
| 4 | vec[vec[T]] 类型码撞区间（§7.18，stage-0 也有） |

**网络内建那一批是下一个大块**（reactor / http / ws / sse 全卡在那里）。
它们不是"加个内建"就完事 —— 要接 Winsock，是独立工程量。

`vec[vec[T]]` 那条更值得优先：它是 **stage-0 与 qlmc 的共同缺口**，
修了能同时改善两边。
