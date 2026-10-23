# v1.51 — f64 打印修复（`__f64_to_str` 有限值路径）+ 一元负号 str 拦截

- 日期：2026-10-23
- 任务：清 07-gaps §2「编码」行登记的运行库缺陷（v1.47 实测、标准库轨点名要求
  语言轨优先修）：**有限非零 f64 打印成空串**；顺带把 `-str` 从"静默野指针"改成
  编译期拒绝。
- 影响面：`tools/stage0/qlm_native.py`（`__f64_to_str` 返回路径 + `unop` 类型检查）、
  `tests/t93_f64print.qma`（新增）、`tests/bad/neg_str.qma`（新增负向）、
  `tests/run_win_tests.py`（注册）、`docs/07-gaps.md`（§2 编码行）、
  `docs/06-status.md`、`tools/stage0/qlm_cli.py`（VERSION）

## 为什么是它

标准库轨 v1.47 把 `exp/log/sin/cos` 做完了，但 `print(1.5)` 打出来是空行——
f64 无法输出，数学库的结果只能靠 assert 逐位比，人看不见、日志打不出。这不是
"缺功能"而是"错功能"，且它挡在所有浮点工作的出口上。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | `__f64_to_str`：有限值（定点 / 科学计数）共同出口由 `ret(buf)` 改为 `ret_buf()`——补写长度前缀并返回 `buf+8`（字节区），与 nan/inf/0 三条早期路径一致。`unop "-"`：操作数是 str 时编译期报错（此前落到 `neg` 指令，把长度前缀指针按整数取负） |
| `tests/t93_f64print.qma` | **新增**：21 条断言——定点（`1.5` / `-2.25` / `3` / `0.1` / `1/3→0.333333` / `1e-6` 下界）、科学计数（`1e+12` 上界 / `2.5e-7` / `1e+300` / `-1e-300`）、特殊值（`0` / `-0.0→0` / `nan` / `inf` / `-inf`）、长度前缀（`len("1.5")==3`）、拼接 |
| `tests/bad/neg_str.qma` | **新增负向**：`-s`（s 为 str）必须编译期拒绝 |
| `docs/07-gaps.md` | §2 编码行删掉缺陷登记，改记"已修 v1.51"与剩余边界 |

## 实现要点

- **根因**：`__f64_to_str` 有三条提前返回（nan / inf / 0）都走 `ret_buf()`，唯独
  有限值共同出口写的是 `ret(buf)`——既没写 `[buf]` 长度，又把**分配基址**当 str
  返回。调用方按 str ABI 读 `[ptr-8]` 当长度，读到的是分配器头部（0 或垃圾）：
  于是 `print(1.5)` 输出空行，`len(1.5.to_str())` 是 0。`-0.0` 走的是 `x == 0`
  分支，所以只有"非零有限值"中招——这也是为什么缺陷看起来像"只有小数坏"。
- **与 C 后端逐位一致**：`qlm.py` 的 `qlm_f64_to_str` 是独立实现（定点 6 位小数去
  尾零 / 科学计数尾数 6 位去尾零 / half away from zero / `-0.0 → "0"`），本轮按它的
  注释口径逐条对断言，保证双链对拍不产生格式分叉。本机无 gcc，C 侧只做源码对照。
- **一元负号**：`-1e-300.to_str()` 的真身是 `-(1e-300.to_str())`（`.` 优先级高于一元
  负号）。旧行为把它当整数取负 → 野指针 → 比较/打印段错误；现在编译期报错并提示
  加括号（`(-1e-300).to_str()`）。

## 验证（本轮全部现跑）

<!-- verify:begin -->
| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=161 FAIL=0 SKIP=1**（SKIP 为 WSL 交叉验证） |
| `python tests/lexdiff.py` | **PASS=145 FAIL=0** |
| `python tests/parsediff.py` | **PASS=123 FAIL=0** |
| `python tests/bodydiff.py` | 一致 1279 / 分叉 1106 / SKIP 同步 25 / SKIP 不同步 31（诊断项） |
| `python tests/irdiff.py` | **PASS=68 FAIL=0 SKIP=51** |
| `python tests/emitdiff.py` | **PASS=10 FAIL=0** |
| 三道门禁 | check_names / check_origin / check_docs 全 PASS |
| **性能（双向对照）** | `git worktree add ../perfbase-v151 bb5e35e` 建基线，两树各构建 8 个 bench：**`.qex` 逐字节相同**（p0/gbench/bench_str/find/simd/sync/gzip/bench_mod 全部相同）——不打印 f64 的程序零指令变化；`__f64_to_str` 本身不在这些程序的可达集里（全局 DCE 后不发射） |
<!-- verify:end -->

## 已知边界 / 遗留

- **不是最短往返表示**：定点最多 6 位小数、科学计数尾数 6 位小数（`0.1 + 0.2` 打
  `0.3`，`1/3` 打 `0.333333`）。要 printf 级往返精度需 grisu/ryu，未做。
- **`-0.0` 归一为 `0`**（符号位丢弃，与 C 后端一致）；要区分需另开 API。
- 科学计数指数不带前导零（`1e-7` 而非 `1e-07`），与 C 后端一致。
- 定点区间是 `[1e-6, 1e12)`，越界转科学计数；这条分界与 C 后端共享，改动需双链同步。
- `-str` 现在是编译错误：第三方代码若靠"对 str 取负"碰巧拿到整数（本就无意义），
  需要改写。
