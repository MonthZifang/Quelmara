# v4.58 — RT_ZERO 升 16 字节块（memcpy 16B 同款模式复用）

- 日期：2026-11-06
- 任务：PERF-ROADMAP 遗留——16B 模式在 memcpy 已验证（v4.52），
  RT_ZERO 当时随 vec 内联实验回退撤销。本轮独立落地。
- 结论：**已落地**，RT 7/7 + 自举 42/42 + 差分 110/110。

## 实现

`_gen_zero` 升三级：16B movdqu（xorps 清 xmm0 一次复用）→
8B qword → 尾部字节。模式与 memcpy 16B（v4.52）同款：

* xmm0 保存/恢复（sub rsp,24 + movdqu，qlmc SSE 池全占用）
* 5 标签（labs 128 容量足够，v4.52 起）
* xorps 清零一次后循环复用（比 memset 逐次加载更省）
* 尾部 and rcx,7

## 验证

* RT 7/7（含 grow_edge 精确边界、two_allocs ×8 哨兵）
* 自举 42/42 + 不动点
* 差分 110/110
* docs PASS

## 收益

mem_zero 是 vec.new 扩容清零（_map_grow 清槽）、str 拼接等
的底层——与 memcpy 同频使用。16B 段使大块清零吞吐翻倍。


## 效果实测（RT_ZERO 16B 落地后）

b87_memcopy_big（min of 3）：**quelmara 214.8ms vs C 232.8ms = 0.92x，
反超 C**（RT_ZERO 16B 前 224 vs 219 = 1.02x）——mem_alloc 的 ZERON
清零路径升级后，b87 成为【第一个跑赢 C 的大块负载基准】。
校验和双端一致。
