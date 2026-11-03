# v4.00 — 修 stage-2 自举（`_lower_builtin` 帧超限）+ 拆出 `now_ns` 两套实现

- 日期：2026-11-03
- 任务：CI 在 v3.98 / v3.99 上是**红的**，唯一失败项是
  `[FAIL] 自举五级链失败：stage-2 构建 —— 需要 417 个槽（已用 416）`。
- 结论：**已修**。五级链全 PASS（含第 3 级不动点），110 项差分无回归。

## 我漏了什么

v3.97 / v3.98 / v3.99 三个提交我只跑了 `tests/qlmc_test.py`（110 项全过），
**没跑 `tests/bootstrap_test.py`**。而 CI 的 `win_failures.log` 里唯一那条红
就是自举链。351 项 PASS / 1 项 FAIL，比例小但性质严重 ——
**自举是硬门禁，它红了等于"编译器编不出自己"**。

教训：**`qlmc_test.py` 全绿 ≠ 可以提交**。两个套件必须都跑：
* `tests/qlmc_test.py` —— 110 项stage-0/qlmc 差分
* `tests/bootstrap_test.py` —— 五级自举链（stage-2 编自己 + 不动点）

## 二分定位

| 版本 | 源码 | 编译器 | 自举 |
|---|---|---|---|
| v3.94 | v3.94 | v3.94 | ✅ 708608 字节 |
| v3.95 | v3.95 | v3.95 | ❌ 417 槽 |
| v3.96~v3.99 | 同上 | 同上 | ❌ 417 槽 |

**v3.95 是引入点** —— 那一版加了 ELF 运行库（`_gen_cgt_elf` /
`_gen_syscall_elf` / `_gen_i64_fmt_elf` / `mmap` 分支）和 `now_ns` 的
ELF 分支。ELF 分支直接内联在 `_lower_builtin` 里，那个函数本来就有
869 行、66 个内建分支、贴着 `SLOT_TEMP`(416) 上限。

## 修法：把 `now_ns` 的两套实现都抽成独立函数

* `_bi_now_ns_pe(fc)` —— QPC 两段式（`ns = (c/f)*1e9 + ((c%f)*1e9)/f`）
* `_bi_now_ns_elf(fc)` —— `clock_gettime(CLOCK_MONOTONIC)`（一次 syscall）

`_lower_builtin` 里只剩两行分叉：

```quelmara
if bn == "now_ns" {
    if fc.target == 1 {
        return _bi_now_ns_elf(fc)
    }
    return _bi_now_ns_pe(fc)
}
```

这是本项目**第五次**因为同一个原因（`_lower_builtin` / `_emit_ir` 贴着帧上限）
翻车：v2.55（`_emit_f64`）、v3.90（`_emit_csubns`）、v3.91（`_emit_binop` /
`_emit_trunc`）、v3.97（`_bi_now_ns_elf` 抽了一半）、现在这次。

**规则**：往 `_lower_builtin` / `_emit_ir` 里加任何局部变量或分支之前，
先想"这个函数还有多少帧余量"。**没有余量就抽函数，不要赌**。

## 验证

| 项 | 结果 |
|---|---|
| `tests/bootstrap_test.py` | **五级全 PASS**（含不动点 stage-2 == stage-3） |
| `tests/qlmc_test.py` | **PASS=110 FAIL=0** |
| ELF 后端（5 项基准抽查） | 结果全对 |

## 另一件**没有**采纳的改动

顺手试了"`_opt_copy` 跳过 NOP 找下一条实指令"（想让更多 MOV 被消掉）。
12 项基准结果全对，但它**同样把 `_lower_builtin` 顶到 417 槽** ——
因为 IR 变短后分配器的位置分配跟着变。

按纪律回退：**收益不明确、破坏自举**，不留。
