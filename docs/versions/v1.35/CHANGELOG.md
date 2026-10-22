# v1.35 — MD5（补最后一个哈希红标）+ 一次失败的性能实验

- 日期：2026-10-22
- 任务：继续性能优化 + 补 `07-gaps.md` 的红标
- 影响面：标准库（新模块 md5）、测试、文档

## 一、性能实验：JSON 字符串扫描改 SWAR —— **失败，已回退**

`07-gaps.md` §5 把"JSON memchr 化"列为剩下的性能项。动手做了：

1. 新增 `mem_lt(p, n, bound)` 内建（SWAR hasless，找首个 < bound 的字节）；
2. `_parse_str` 的快路径从"逐字节 3 次比较"改成"三路 SWAR 扫描取最早命中"。

**实测是负优化**：

| 版本 | `bench/json_bench.qma`（1.35 MB） |
|---|---|
| 逐字节（v1.34） | **29 ms，44 MB/s** |
| 三路 SWAR | 卡住（1.3 MB 负载慢一个数量级） |
| 混合（先逐字节 32 字节再 SWAR） | **62 ms，20 MB/s** |

原因很清楚：JSON 里绝大多数字符串都短（<32 字节），而每次 SWAR 调用有固定开销
（参数搬运 + 函数调用 + 三次独立扫描）。逐字节循环反而是最优的——循环体只有
4 条指令，全部在寄存器里。

**结论（已写进 §5，避免以后重犯）**：`mem_chr` 这类 8 字节扫描只在
"扫描长度远超 32 字节、且只找一个字节"时才划算。`str_find` 在长文本上成立
（v1.29 实测 5.2×），JSON 短串上不成立。

`mem_lt` 一并撤掉了：它没有真实消费者，留着就是死代码（而且我第一版还把语义
用反了——它是"找第一个小于 bound 的字节"，不是"判断全部小于"）。

## 二、顺带查证：v1.29 的 mem_chr 没有拖慢短串

发现 `06-status.md` 里 URL 解析写 69 ms，今天实测 81 ms，怀疑是 v1.29 引入的回归。
用 v1.28 的 `std/str.qma` 对照：

| str 实现 | url parse×100k | split+join 1MiB | json parse 92KB |
|---|---|---|---|
| v1.28（逐字节） | 85 ms | 9 ms | 3 ms |
| v1.34（mem_chr） | **81 ms** | 9 ms | **2 ms** |

没有回归，反而略快。69 vs 81 是环境漂移（本机 VBS 噪声，文档自己就标了 ±50%）。
这条数据也写进了 §5，免得下次又怀疑一遍。

## 三、补全：`std/md5.qma`（RFC 1321）

`07-gaps.md` §2 的哈希红标只剩 MD5。它是唯一一个"不安全但生态里到处都是"的算法
（旧接口签名、ETag、文件校验、S3 分片 ETag）。

| 文件 | 内容 |
|---|---|
| `std/md5.qma` | **新增**：`md5_str`（16 字节小端摘要）/ `md5_hex`（32 位小写）；64 轮**全展开**，轮常量是 `const`、位移是字面量 |
| `tests/t80_md5.qma` | **新增**：RFC 1321 附录 A.5 全部 7 个向量 + 55/56/64 字节填充边界 |
| `tests/run_win_tests.py` | 注册 t80（主回归 142 → 143） |
| `tools/dev/gen_stdlib_doc.py` | DESC 补 `std/md5`，重新生成 `03-stdlib.md`（40 模块 / 452 公开函数） |
| `docs/07-gaps.md` | 哈希行翻绿（含 MD5） |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.34.0 → **1.35.0** |

实现要点：
- 用 Python 生成器写那 64 步（常量、位移、轮转变量名都由脚本算），
  避免手抄 64 个 `floor(2^32·|sin(i+1)|)` 出错。**第一次生成还是错了**——
  把"更新 a"写成了"更新 d"，轮转方向反了；`md5_hex("")` 立刻炸出来。
- MD5 与 SHA-256 有两处相反：消息字是**小端**、长度字段是**小端**、输出也是**小端**。
  三个地方错一个就全错，所以测试直接用 RFC 官方向量而不是自造。

## 验证

| 命令 | 结果 |
|---|---|
| `python tools/stage0/qlm_cli.py run tests/t80_md5.qma --target win` | ok（7 个 RFC 向量 + 3 个填充边界） |
| `python tests/run_win_tests.py` | **PASS=143 FAIL=0 SKIP=1** |
| `python tools/stage0/qlm_cli.py run bench/json_bench.qma --target win` | 29 ms（回退后与 v1.34 一致） |
| `python tools/dev/check_*.py` | 三禁 PASS |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.35.0` |

## 已知边界 / 遗留

- **MD5 只做整串**：没有增量接口（`md5_init/update/final`），大文件要整个读进内存。
  与 `sha256_str` 同一条纪律，先不做。
- **JSON 仍是逐字节扫描**：SWAR 方案实测更慢，§5 已把这条从"待做"改成"已验证不可行"。
- **§7.4 / §7.5 仍未修**：这次又验证了一次——`opt_schedule` 一开一关，同一个函数
  的错法就换一种（关掉后是每字首字节错，打开后是末字节错），说明是分配器对布局敏感，
  和 pass 本身无关。这是下一轮该正面处理的事。
