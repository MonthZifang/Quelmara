# v4.44 — 堆上限从编译期常量改为可配置（`--heap-mb`）

- 日期：2026-11-05
- 任务：用户要求"内存上限可设置，可以在配置文件里决定，或在代码里
  对单个程序/目录/进程设限，而不是全局写死"。
- 结论：**已实现** `--heap-mb N`。

## 改前

`bootstrap/qlmc/qlmc.qma` 里写死 `const HEAP_SIZE = 0x10000000`（256 MB），
三处全用 imm32 立即数：PE 的 `VirtualAlloc`、ELF 的 `mmap`、以及上限计算
`lea r8, [rax+HEAP_SIZE]`。

而 `Quelmara.toml` 里**早就有** `[memory] heap_limit_mb = 512` —— 但 qlmc
根本没读它（qlmc 没有配置解析器）。于是"配置写 512、实际 256"长期不一致。

## 改了什么

新增全局状态 `SW_HEAPMB` + 命令行 `--heap-mb N`（1..65536）：

```quelmara
fn _heap_bytes() -> int {
    let mb = _cur_heap_mb()
    if mb <= 0 { return HEAP_SIZE }          // 没设就用默认
    let b = mb * 1048576
    if b > 2147483647 { return 2147483647 }  // imm32 上限
    return b
}
```

三处 `HEAP_SIZE` 全改成 `_heap_bytes()`。

## 一个必须一起改的地方（差点漏掉）

第三处 `lea r8, [rax+HEAP_SIZE]` 是**上限**计算。只改前两处（映射大小）
而不改这里，会变成"只映射 1 MB，但上限仍按 256 MB 判"——越界检查形同虚设，
直接 SIGSEGV 而不是干净退出。

实测确认了这个坑：改前 `--heap-mb 1` 跑 100 万元素 → **SIGSEGV**；
三处全改后 → **exit 3**（干净 OOM）。

## 验证

```
--heap-mb 1    -> exit 3（干净 OOM）
--heap-mb 256  -> 1000000, exit 0
自举 42/42 + 不动点 PASS
```

## 本轮**没有**采纳的改动：vec 内联布局

试过把 vec 从 `[data_ptr][len][cap]` 改成 `[len][cap][data...]` 单块布局，
目标是消除 `v.get(i)` 的第二次访存（这是 8-13× 性能差距的主因）。

* 正确性通过：`b28_matrix` 校验和 `960991321` 一致，且大 vec（1000 万元素）
  不再崩溃。
* **性能确实提升**：`b28_matrix` 811ms → **661ms**（-18%），
  `b22_knapsack` 14ms → 11ms（-21%）。
* **但自举超时**：stage-2 编 `s15_bitops.qma` 卡死 900 秒。

按纪律回退，补丁留在 `/tmp/vec_inline_wip.patch`。这是本项目第 9 次
"IR/布局改动破坏自举"，根因同前：qlmc 的任何 IR 生成变化都会让
stage-2 与 stage-1 的产物不一致。

## 仍未做

* 配置文件读取（`Quelmara.toml` 的 `heap_limit_mb` 还没接进 qlmc）
* 代码内按作用域设限（需把分配器改成 arena 化）
* vec 内联布局（见上，需同步改 stage-0 才能过自举）
* 寄存器分配改进 / SIMD
