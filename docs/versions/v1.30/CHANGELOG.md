# v1.30 — mem_diff 内建（gzip 编码 1.6×）+ LRU 缓存

- 日期：2026-10-22
- 任务：继续性能优化（gzip 编码器内层热点）+ 补齐最后一个红标数据结构（LRU）
- 影响面：编译器（新内建 + 运行时）、标准库（gzip 编码器 + 新模块 lru）、测试、文档

## 为什么是这两个

- **性能**：`07-gaps.md` §5 把 gzip 列在性能专项里。先量了一遍现状（1 MiB 重复文本）：
  编码 25 ms、解码 15 ms、CRC 3 ms。解码已经没有明显空间，编码的内层是
  "一字节一次 `mem_load8` + 比较"算匹配长度——这是 LZ77 的经典热点。
- **补全**：§2 的数据结构红标只剩 LRU。上一轮判断"需要 map + 双向链表双句柄 API"，
  这次换了个思路：**不用 map**，自己在 `vec[int]` 里建开放寻址表 + 双向链表，
  单句柄、零依赖。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 新增内建 `mem_diff(p1, p2, n)` → 运行时 `__memdiff`（8 字节字比较，字不等再逐字节定位首差） |
| `std/gzip.qma` | 匹配长度改 `mem_diff`；插入哈希链与滚动哈希**合并成一趟**（每位置省 3 次读 + 2 次乘） |
| `std/lru.qma` | **新增**：LRU 缓存，get/put/del 均摊 O(1)，单句柄（开放寻址表 + 墓碑 + 双向链表） |
| `tests/t78_lru.qma` | **新增**：命中刷新 / 淘汰 / 更新不增条目 / 墓碑复用 / 5000 次 churn / 删空 |
| `tests/run_win_tests.py` | 注册 t78（主回归 140 → 141） |
| `tools/dev/gen_stdlib_doc.py` | DESC 补 `std/lru`，重新生成 `03-stdlib.md`（39 模块 / 445 公开函数） |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.29.0 → **1.30.0** |
| `docs/02-language.md` | 内建表补 `mem_diff` |
| `docs/03-stdlib.md` | §4 补 lru 边界行 |
| `docs/06-status.md` | 回归 141；gzip 编码 25–27 ms → **16 ms** |
| `docs/07-gaps.md` | 数据结构行翻绿（含 LRU）；§5 修正 gzip 那一项的表述（见下） |

## 实现要点

- **`__memdiff`**：`n>>3` 个整字逐个 `xor`，字为 0 就整字跳过，字不为 0 再在该字的
  8 字节里逐字节定位。返回的是**首个**不同字节下标（不是"某个"），全等返回 `n`
  ——正好等于"公共前缀长度"，也就是 LZ77 要的匹配长度。
- **gzip 的两处改动必须分开看**：
  1. `mem_diff` 替掉逐字节比较：25 → 20 ms。
  2. 插入哈希链 + 滚动哈希合并：20 → 16 ms。旧代码是两趟——先按位置重算
     `h2`（3 次读 + 2 次乘）插入，再单独滚一遍 `h`；1 MiB 重复文本下有 ~100 万次
     位置，这两趟就是当前的头号成本。合并后保持滚动不变式"进入循环时 h 就是 pos 的哈希"，
     只在 `hok == 0`（末尾几字节）退化成逐位置重算。
- **输出字节不变**：7658 B 与 v1.29 完全一致，`t47_gzip` / `t63_inflate` 与
  Python zlib 的 63 项互操作全过——压缩流没有变，只是算得快了。
- **LRU 的哈希表**：`h = k * 0x9E3779B97F4A7C15; h ^= h >> 29; idx = h & (tc-1)`，
  表容量取 ≥ 2×cap 的 2 的幂（负载因子 ≤ 0.5）；删除写墓碑（-2）而不是清空，
  否则探测链会断。空闲槽走一条单向链表，避免每次 put 都线性找空位。

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run bench/gzip_bench.qma --target win` | **16 ms / MiB**（v1.29 前 25–27 ms，**1.6×**），out=7658 B 不变；解码 15 ms；CRC 3 ms |
| `python tests/run_win_tests.py` | **PASS=141 FAIL=0 SKIP=1**（v1.29 为 140） |
| `python tests/gzip_inflate_test.py` | **PASS=63 FAIL=0**；损坏输入拒绝 5/5 |
| `python tools/stage0/qlm_cli.py run tests/t47_gzip.qma --target win` | ok |
| `python tools/stage0/qlm_cli.py run tests/t63_inflate.qma --target win` | ok |
| `python tools/stage0/qlm_cli.py run tests/t78_lru.qma --target win` | ok（含 5000 次 churn） |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| `python tools/dev/check_*.py` | 三禁 PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.30.0` |

## 已知边界 / 遗留

- **没有 lazy matching**：`07-gaps.md` §5 原来把"lazy matching"写成 25→15 ms 的提速项，
  这是**错的**——lazy matching 用时间换压缩率（时间 +20~30%、体积 -3~8%）。已改正：
  提速靠的是批量比对与合并遍历；要更高压缩率再单独做 lazy。
- **LRU 的 key 只有 int**：字符串 key 走 `fnv1a64`，碰撞由调用方负责（缓存层无法知道
  两个不同字符串映射到同一个 int）。没有 TTL、没有容量自适应。
- **`lru_get` 未命中返回 -1**：与"值是 -1"歧义，文档已写明用 `lru_has` 或 `lru_get_or`。
  根治要等 `option[T]` 能承载 int（现在可以，但会让调用点啰嗦，先不换）。
- **`mem_diff` 只做整字节**：没有"忽略大小写"或"按 UTF-8 边界"的变体。
- **§7.3 的 64 位立即数问题仍在**：这一步没有继续追——复现路径只在手写 IR 里
  （源码常量会先进 vreg），实际影响面已限制在编译器运行时函数内部，库层已全部避开。
