# v1.32 — GHASH 字级化（GCM 端到端 4.75×）+ 多 member gzip / zlib 容器

- 日期：2026-10-22
- 任务：继续性能优化（GCM 剩下的 98% 是 GHASH）+ 补齐 `07-gaps.md` §2 的压缩红标
- 影响面：标准库（aes / gzip）、测试、文档

## 为什么是 GHASH

v1.31 把 AES 核心做进硬件后，CTR 段只剩 2 ms，而 GHASH 仍是 123 ms——占端到端 98%。
再往下走，GHASH 是唯一有意义的目标。

看代码发现瓶颈很朴素：`_gf_mul_t`（4-bit 表乘法）是**逐字节**写的——每个 nibble
做 16 次 `mem_load8` + 16 次 `mem_store8`，一个 16 字节块 32 个 nibble 就是
**1024 次字节级内存操作**。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/aes.qma` | `_gf_mul_t` 改 64 位字累加（累加器留在两个局部变量里，32 个 nibble 期间不碰内存）；`ghash` 每块的 `Y ^= 块` 也用两个字 |
| `std/gzip.qma` | `_inflate_core` 回传**流边界**；`gzip_decode` 改成逐 member 循环（RFC 1952 §2.2 拼接流）；新增 `zlib_decode`（RFC 1950）+ `adler32`；头解析抽成 `_gzip_body_start` |
| `tests/gzip_inflate_test.py` | probe 支持 `zlib` 模式；编码组合 9 → 12（加 zlib 三个级别）；新增多 member 拼接用例（×2 / ×3） |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.31.0 → **1.32.0** |
| `docs/06-status.md` | GCM 36 ms；GHASH 34 ms；gzip 互操作 86 |
| `docs/07-gaps.md` | 压缩行翻绿；§5 新增"GHASH 字级化"完成行 |

## 实现要点

- **字级化为什么等价**：表行就是 16 字节原样，字级异或 + 字级写回与逐字节完全一致
  （小端机器上两边都是同一组位）。每 nibble 从 32 次内存操作降到 4 次。
- **累加器留在寄存器**：旧实现每 nibble 都从 `out` 读回来再写回去；新实现
  `lo`/`hi` 两个局部变量从头算到尾，只在最后写 2 次。
- **多 member 的关键是"流在哪结束"**：`_inflate_core` 现在把
  `读指针 - 位缓冲里未消费的整字节数` 写进 endbox，调用方据此找到 CRC32/ISIZE，
  再往后就是下一个 member 的头。
- **zlib 容器**：2 字节头（CMF/FLG，`(CMF*256+FLG) % 31 == 0` 校验、拒绝 FDICT）
  + deflate + 4 字节大端 adler32。HTTP 的 `Content-Encoding: deflate` 实际发的
  就是这个容器，以前只能先剥头再 `inflate_raw`。

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run bench/aes_bench.qma --target win` | **36 ms / MiB**（v1.31 125 ms，**3.5×**；v1.30 171 ms，累计 **4.75×**） |
| `python tests/gzip_inflate_test.py` | **PASS=86 FAIL=0**（v1.31 为 63；含 zlib 容器 21 项 + 多 member 2 项）+ 损坏输入拒绝 5/5 |
| `python tests/run_win_tests.py` | **PASS=141 FAIL=0 SKIP=1** |
| `python tools/stage0/qlm_cli.py run tests/t73_ghash.qma --target win` | ok（NIST 向量 + 4 KiB GCM 往返） |
| `python tools/stage0/qlm_cli.py run tests/t47_gzip.qma --target win` | ok |
| `python tools/stage0/qlm_cli.py run tests/t63_inflate.qma --target win` | ok |
| `python tools/stage0/qlm_cli.py run tests/t48_aes.qma --target win` | ok |
| `python tools/dev/check_*.py` | 三禁 PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.32.0` |

## 已知边界 / 遗留

- **GHASH 仍是 GCM 的大头**（34 ms 里几乎全是它）。4-bit 表的天花板就在这里；
  再快 10× 只能上 **PCLMULQDQ**（预期 GHASH → 1–3 ms，GCM 端到端 → ~5 ms）。
  那是下一项，需要 `pclmulqdq` 编码 + GCM 位反射约定 + 与 4-bit 表逐字节对拍。
- **zlib 预置字典（FDICT）不支持**：遇到 `flg & 0x20` 直接 fail-fast 并说明原因。
- **raw inflate 不复用窗口**：`inflate_raw` 每次新建输出缓冲，没有 `inflateReset`
  那种"保留 32 KiB 窗口"的增量接口。
- **多 member 会多一次拷贝**：成员体先各自成串、再逐字节 append 到累加缓冲。
  单 member（绝大多数情况）走的是同一条路径，多了一次全量拷贝——为了支持拼接流
  先接受这个代价，后续可以改成"直接写进累加缓冲"。
