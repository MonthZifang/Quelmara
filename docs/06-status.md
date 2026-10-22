# 当前状态（实测）

> **本文是全部实测数字的唯一出处。** 其它文档引用数字时写"见 `06-status.md`"。
> 口径日期：2026-10-22。环境：Windows 10/11 x86-64，Xeon E5-2666 v3（Haswell 代，
> **无 SHA-NI、无 AVX2**），VBS/Hyper-V 开启（进程冷启动 ~426 ms，跑分噪声 ±50%）。
> 解释器：Python 3.13.12。

## 1. 回归与对拍

| 项 | 结果 | 命令 |
|---|---|---|
| PE 回归（主回归） | **PASS=127 FAIL=0 SKIP=1**（SKIP 为 WSL 交叉验证，本机被沙箱拦） | `python tests/run_win_tests.py` |
| 词法器对拍 | **PASS=112 FAIL=0**（112 个源文件） | `python tests/lexdiff.py` |
| 声明级 AST 对拍 | **PASS=97 FAIL=0**（跳过 3 个：`t52_iface` / `t54_iface_dyn` / `t56_generic`，自举 parser 未支持 interface/impl/泛型） | `python tests/parsediff.py` |
| 函数体 dump 对拍 | **一致 789 / 分叉 685 / SKIP 同步 18 / SKIP 不同步 18** | `python tests/bodydiff.py` |
| IR 架构无关对拍 | **PASS=56 FAIL=0 SKIP=35**，并行后 **49 s**（原串行 5 min 41 s） | `python tests/irdiff.py` |
| 发射层确定性对拍 | **PASS=10 FAIL=0** | `python tests/emitdiff.py` |
| gzip 解码互操作 | **PASS=63 FAIL=0**（zlib 9 种编码组合 × 7 类输入）+ **损坏输入拒绝 5/5** | `python tests/gzip_inflate_test.py` |
| 三道门禁 | check_names / check_origin / check_docs 全 PASS | `python tools/dev/check_*.py` |

`run_win_tests.py` 的 7 组覆盖：PE 结构（MZ/PE32+/AMD64/无 CRT 符号）、基础语义、
语言特性（struct/enum/match/宽度/@simd/rc/所有权/vec/map/切片/函数值）、多核
（CreateThread 归约）、单核降级、arena 帧级回收、assert 失败路径、交叉验证。

## 2. 产物

| 程序 | 大小 | 说明 |
|---|---|---|
| `examples/hello.qma` → `hello.exe` | 8.7 KB | 无 CRT，只导入 kernel32 |
| `examples/loop_sum.qma` → `ls.exe` | 6.6 KB | 全局 DCE 后只保留可达函数 |

## 3. 性能

### 3.1 标准库（`bench/p0_bench.qma`，程序内 `now_ns`，min of 3）

| 负载 | 耗时 | 吞吐 |
|---|---|---|
| SHA-256 1 MiB | **70 ms** | 15.0 MB/s |
| gzip 编码 1 MiB（重复文本，输出 7658 B） | **25–27 ms** | 39 MB/s |
| **gzip 解码 1 MiB** | **15 ms**（min of 3） | **70 MB/s** |
| CRC-32 1 MiB | **3–6 ms** | 170–330 MB/s |
| `str_split` + `join` 1 MiB（65537 段） | **8 ms** | 125 MB/s |
| URL parse × 100k | **69 ms** | 0.69 µs/次 |
| JSON parse 92 891 B | **2 ms** | 46 MB/s |
| JSON 遍历 2000 对象 | **< 1 ms** | — |
| X25519 单次标量乘 | **7 ms** | 约 100× 于优化过的 C（OpenSSL ~0.05 ms） |

### 3.2 通用形状（`bench/gbench.qma`，8 个从未参与调优的形状）

| 形状 | 耗时 |
|---|---|
| 词法器扫描 512 KB | 3.87 ms |
| 混合算术 10M 次 | 46.1 ms |
| 字符串 map 10k 次 | 4.29 ms |
| 分支密集 10M 次 | 39.2 ms |
| 字符串构造 1k 次 | 0.78 ms |
| 缓冲区扫描 1 MB | 1.71 ms |
| 嵌套循环 300×300 | 0.41 ms |
| 哈希混合 10M 次 | 70.2 ms |

### 3.3 字符串与循环（`bench/bench_str.qma`）

| 形状 | 耗时 |
|---|---|
| 16 KB 扫描 ×10 | 224 µs（22 µs/次） |
| 20k 次拼接 | 77.3 ms |
| 50M 次循环求和 | 76.7 ms |
| collatz 300k | 131 ms |

### 3.4 SIMD（`bench/simd_bench.qma`，4096 元素 ×200）

| 版本 | 每次 |
|---|---|
| 标量 | 4 µs |
| `@simd` | **1 µs** |
| 加速比 | **4×** |

### 3.5 并发原语（`bench/sync_bench.qma`，rdtsc，n=2e6，单线程）

| 操作 | cycles/iter |
|---|---|
| 普通自增 | 2 |
| `atomic_add` | 17 |
| 自旋锁保护的读改写 | 22 |
| 无锁栈 push+pop | 82 |

### 3.6 进程级（wall clock，min of 5，**含 426 ms 启动**）

| 程序 | 总耗时 | 扣启动后净耗时 |
|---|---|---|
| `hello`（启动基线） | 426 ms | — |
| `loop_sum` 2×10⁸ 次迭代 | 769 ms | ~343 ms（≈1.7 ns/iter） |
| `bench_mod` 形态 A（`(i*7)%13`）1×10⁸ | 679 ms | ~253 ms（≈2.5 ns/iter） |
| `bench_mod` 形态 B（`(x+3)%7` 串行依赖）1×10⁸ | 1892 ms | ~1466 ms（≈14.7 ns/iter） |

> 进程级数字受 VBS 影响很大，**只做纵向比较**，不要跨机器对比。

### 3.7 怎么复现

```bash
python tools/stage0/qlm_cli.py run bench/p0_bench.qma   --target win
python tools/stage0/qlm_cli.py run bench/gzip_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/gbench.qma     --target win
python tools/stage0/qlm_cli.py run bench/bench_str.qma  --target win
python tools/stage0/qlm_cli.py run bench/simd_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/sync_bench.qma --target win
```

`bench/*.qma` 已内置 min-of-N；单次跑不可比。

## 4. 自举

| 组件 | 阶段 | 状态 |
|---|---|---|
| 词法 | stage-1 | ✅ 对拍通过 |
| 语法（声明级） | stage-1 | ✅ 对拍通过 |
| 类型推断 | stage-0 | ❌ 缺失 |
| AST→IR | stage-0 | ❌ 缺失（有对拍骨架） |
| 优化 | stage-0 | ❌ 缺失 |
| x86-64 编码 | stage-0 | ❌ 缺失（有对拍骨架） |
| ELF 写出 | stage-0 | ❌ 缺失 |
| PE 写出 | stage-0 | ❌ 缺失 |
| AArch64 | stage-0 | ❌ 缺失（有 IR 对拍） |
| C99 后端 | — | 不移植（仅交叉验证） |

**组件自举 2/9；代码行数 自举 1846 / stage-0 21114 = 8.0%**（`python tools/dev/selfhost_status.py`）。

## 5. 平台

| 平台 | 状态 | 证据 | 边界 |
|---|---|---|---|
| Windows x86-64（PE32+） | ✅ 主平台 | 本文 §1 主回归 | 无 CRT，只导入 kernel32 / ws2_32 |
| Linux x86-64（ELF64） | ✅ 构建级 | CI `run_native_tests.sh` | 本机无 gcc/WSL，只能 CI 验证 |
| Linux io_uring | ✅ | CI `test_uring.sh` | 需 5.1+ 内核 |
| AArch64（ELF64） | 🟡 | `tests/a64_emu.py` 执行级 | 无 chan/map/spawn/vtable/atomic/SHA；遇不支持形态编译期报错 |
| macOS（Mach-O） | ❌ | — | 无 |
| wasm32/64 | ❌ | — | 无 |
| TLS（https/wss） | 🟡 Phase A 3/3 | `std/sha256` + `std/aes`(GCM) + `std/x25519` 齐备 | 缺记录层、握手状态机、X.509 |

## 6. 已知风险

| 风险 | 影响 | 现状 |
|---|---|---|
| LICM 默认关闭 | 循环不变量无法外提，性能损失普遍存在 | x64 分配器布局敏感段错误未根修，`QLM_ENABLE_LICM=1` 可复现 |
| 接口装箱不释放 | 热点循环频繁装箱会涨堆 | 无 rc/drop 路径 |
| `f64` 比较曾整型化 | `if a > b` 对负浮点给出相反结果（v1.19 已修） | 根因：`branch()` 直接发 `jcc` 未走 `fcmpset`；回归 `tests/t64_math.qma` |
