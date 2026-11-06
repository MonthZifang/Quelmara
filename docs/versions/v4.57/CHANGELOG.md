# v4.57 — 新基准 b87_memcopy_big：mem_copy 直连量三级拷贝

- 日期：2026-11-06
- 任务：b31 名为 memcpy 实为 vec push/get 循环——75 项里没有
  直接量 mem_copy 的基准。新增 b87 直连 100MB mem_copy。
- 结论：**quelmara 224ms vs C 219ms = 1.02x**——v4.52 的三级拷贝
  （16B movdqu→8B→尾部）已把 mem_copy 拉到与 C 持平！

## 内容

* `bench/speed/quelmara/b87_memcopy_big.qma`：25MB×2 alloc +
  填充 + mem_copy(100MB) + 三点校验
* `bench/speed/c/b87_memcopy_big.c`：同构（memcpy 直连）
* `run.py` 注册（第 88 项基准）

## 首测数据

| 端 | 时间 |
|---|---|
| quelmara | 224ms |
| C | 219ms |
| **比值** | **1.02x** |

对比 b31（vec 循环形态）的 1.55x —— **mem_copy 直连与 C 持平**，
16 字节 movdqu + 8 字节块 + 尾部的三级拷贝在真实大块场景达到
memcpy 目标。这是本会话性能工作的直接量化成果。

## 校验和

双端 131249996 一致（首/中/尾三点求和）。
