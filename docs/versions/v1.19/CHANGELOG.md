# v1.19 — 补齐最大缺口（gzip 解码）+ 修浮点比较误编译 + 标准库三件

- 日期：2026-10-22
- 任务：一次性推进所有"缺失内容与隐患"，没有指定范围——按缺口清单挑可验证的做透。
- 影响面：编译器（比较降级）、标准库（gzip/hex/math/log）、测试与工具链、文档

## 改动

### 编译器

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | **修 f64 比较误编译**：`branch()` 对 `if` / `while` 的比较直接发整数 `jcc`，没检查操作数是否浮点。IEEE754 负数的位模式在整数序下相反，导致 `if -2.0 > -1.0` 成立。改为先判 `_float_of` → `conv_to` → `fcmpset` + `jnz`（与 `arith()` 的表达式路径一致） |
| `tools/stage0/qlm_cli.py` | `VERSION` 从 `1.0.0` 改为 `1.19.0`，与 `docs/versions/` 对齐 |

### 标准库

| 文件 | 改了什么 |
|---|---|
| `std/gzip.qma` | **新增 inflate 解码**（约 400 行）：存储块 / 固定 Huffman / 动态 Huffman；gzip 头解析（FEXTRA/FNAME/FCOMMENT/FHCRC）；CRC32 + ISIZE 校验；`inflate_raw` 处理裸 deflate。实现用 puff 风格规范 Huffman（counts+symbols 逐位下降），literal 与 distance 两套码表合并进同一对 vec（**函数参数上限 6 个**，寄存器传参） |
| `std/hex.qma` | 新增：`hex_encode` / `hex_encode_upper` / `hex_decode` / `hex_decode_ok` / `hex_val` |
| `std/math.qma` | 新增 21 个函数：`sqrt`（牛顿 + 4 的幂缩放，8 轮）、`cbrt`、`floor/ceil/round/trunc_f`、`powi`、`isqrt`、`gcd/lcm`、`fmin/fmax/fabs/fsign`、`is_nan/is_inf/is_finite`、`clamp_int/clamp_f` |
| `std/log.qma` | 新增 `log_set_level` / `log_level`（0=全开 1=warn 2=error 3=静默），三个级别函数按阈值短路 |

### 测试

| 文件 | 改了什么 |
|---|---|
| `tests/t63_inflate.qma` | 新增：空串 / 短文本 / 2000B 重复 / UTF-8 / raw deflate / hex 往返 |
| `tests/t64_math.qma` | 新增：取整四方向、sqrt/cbrt/powi、isqrt/gcd/lcm、特殊值、日志级别过滤 |
| `tests/gzip_inflate_test.py` | 新增：zlib 互操作矩阵（level 0/1/6/9 × 默认/FIXED/HUFFMAN_ONLY/RLE × gzip/raw × 7 类输入）+ **5 类损坏输入必须被拒绝且不挂死** |
| `tests/run_win_tests.py` | 注册 t63 / t64 |
| `tests/irdiff.py` | **并行化**（`-j`，默认按核数）+ 每文件独立 `-o` 路径避免竞争；5 min 41 s → 49 s |
| `bench/gzip_bench.qma` | 增加解码计时（预热一次后计时） |

### 工程

| 文件 | 改了什么 |
|---|---|
| `.gitignore` | 忽略 `*.exe` / `*.qex` 与 `fixtures/**` 下的产物（`fixtures/srcproj/main.exe` 之前是未跟踪噪声） |
| `tools/dev/gen_stdlib_doc.py` | DESC 补 `std/hex` / `std/math`，重新生成 API 段 |
| `docs/03-stdlib.md` | 重新生成（26 模块 / 309 公开函数）+ 更新边界表 |
| `docs/04-compiler.md` | 新增 §9.1「同一个语义往往有两条降级路径」——本次 bug 的方法论教训 |
| `docs/06-status.md` | 更新回归/对拍/性能数字，风险表加浮点比较条目 |
| `docs/07-gaps.md` | 压缩/编码/数学/工具链四行改写；新增 §7.2 编译器缺陷记录 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=126 FAIL=0 SKIP=1**（124 + t63 + t64） |
| `python tests/gzip_inflate_test.py` | **PASS=63 FAIL=0**；损坏输入拒绝 **5/5** |
| `python tests/lexdiff.py` | PASS=111 FAIL=0 |
| `python tests/parsediff.py` | PASS=96 FAIL=0 |
| `python tests/bodydiff.py` | 一致 766 / 分叉 680 / SKIP 不同步 18 |
| `python tests/irdiff.py` | PASS=56 FAIL=0 SKIP=35，49 s |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| `python tools/dev/check_docs.py` | PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（26 模块 / 309 函数） |

性能（本机，程序内 `now_ns`）：

| 负载 | 结果 |
|---|---|
| gzip 解码 1 MiB | **15 ms**（70 MB/s，min of 3） |
| gzip 编码 1 MiB | 25–27 ms |
| CRC-32 1 MiB | 3–6 ms |

## 已知边界 / 遗留

- **inflate 只解第一个 member**：多 member gzip（`cat a.gz b.gz`）只返回第一段；
  需要循环调用并把偏移往下推，登记在 `07-gaps.md`。
- **解码错误 fail-fast**：CRC/ISIZE 不符直接 `assert` 退出进程，不返回错误码——
  与库层"没有错误对象"的现状一致（`result` 载荷限标量）。
- **`std/math` 没有超越函数**：`exp`/`log`/`pow(x,y)`/`sin`/`cos` 需要展开式与
  更高精度控制，本轮不做；`floor` 系列受 `to_int` 的 int64 范围限制。
- **`bodydiff` 分叉数从 625 涨到 680**：新增的 `std/gzip` 解码与 `std/math` 用了
  自举 parser 尚不支持的形态（多参数 vec 形参、`vec[int]` 返回等），分母变大导致
  分叉变多，**不是解析能力回退**。
- `tools/stage0/qlm_arm64.py` 在工作区有一份纯行尾变化（CRLF）的改动，未纳入本次提交。
