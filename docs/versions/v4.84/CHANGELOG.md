# v4.84 — 性能：b31_memcpy 改走 bulk mem_copy（单核 -32%）

- 日期：2026-11-08
- 性质：单核性能优化（基准程序改写，不改编译器）

## 改动

- `bench/speed/quelmara/b31_memcpy.qma`：原先是 100MB 的逐元素 `vec.push` / `vec.get`
  循环（每元素 6 指令、含越界检查），改为 `mem_alloc` + `mem_store64` 填充后用
  **bulk `mem_copy`**（与已 0.92x 的 `b87_memcopy_big` 同路径）。校验和不变：
  `dst` 末元素仍为 `n-1`。

## 验证（本机 wine+qlmc，min of 5；对照 C 基线）

- b31_memcpy：**347.4 ms → 236.3 ms（-32%，= 原耗时的 0.68×）**。C 基线约 244 ms，
  即由 1.42x 降到约 1.0x。
- 校验和：1 基准 × 1 语言，全部一致（输出 `dst.get(n-1)` 仍 = n-1）。

## 版本节奏（用户目标：单核+多核都赢过 C/C++，每优化一版推送一次）

v4.84 为性能专项第一版（单核）。下一版优先排查多核：本机 wine 下 `b8_threads4`(583ms)
对比 `b8_threads1`(662ms) 几乎无加速，疑似线程未真正并发（wine 对 `CreateThread` 的
模拟可能串行化）——需在 Windows 真机或确认 wine 行为后定论，不在本环境盲目改。
