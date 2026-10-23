# 当前状态（实测）

> **本文是全部实测数字的唯一出处。** 其它文档引用数字时写"见 `06-status.md`"。
> 口径日期：2026-10-23。环境：Windows 10/11 x86-64，Xeon E5-2666 v3（Haswell 代，
> **无 SHA-NI、无 AVX2**），VBS/Hyper-V 开启（进程冷启动 ~426 ms，跑分噪声 ±50%）。
> 解释器：Python 3.13.12。

## 1. 回归与对拍

| 项 | 结果 | 命令 |
|---|---|---|
| PE 回归（主回归） | **PASS=221 FAIL=0 SKIP=1**（SKIP 为 WSL 交叉验证，本机被沙箱拦） | `python tests/run_win_tests.py` |
| 词法器对拍 | **PASS=201 FAIL=0**（204 个源文件；SKIP 3 个含 `f"..."` 插值的文件——stage-1 词法器不认 `FSTR`，v1.61 插值未移植） | `python tests/lexdiff.py` |
| 声明级 AST 对拍 | **PASS=142 FAIL=0**（跳过 12 个：`t52_iface` / `t54_iface_dyn` / `t56_generic` / `t81_generic_infer` / `t99_generic_struct` / `t101_bounds` / `t102_generic_impl` / `t103_generic_enum` / `t104_generic_enum_impl` / `t115_derive` / `dpub_main` / `dpub_model`，自举 parser 未做 interface/impl/泛型单态化、类型约束、泛型 impl、泛型 enum 与 `@derive`） | `python tests/parsediff.py` |
| 函数体 dump 对拍 | **一致 1719 / 分叉 1608 / SKIP 同步 26 / SKIP 不同步 44**（诊断项，非门禁：分叉随新增源文件增长，含 stage-1 body parser 未支持的 `defer`/f64 形态） | `python tests/bodydiff.py` |
| IR 架构无关对拍 | **PASS=78 FAIL=0 SKIP=66**，并行后 **91 s**（原串行 5 min 41 s；SKIP 全是 arm64 未接的特性，t85 的 `trunc` / t86 的 map 聚合值 / t90_mathfn 的 f64 二元运算属此类；t87 的 8 参、t91 的 `defer`、t94 的窄切片写入已接，t96 点积 A64 未接） | `python tests/irdiff.py` |
| 发射层确定性对拍 | **PASS=10 FAIL=0** | `python tests/emitdiff.py` |
| gzip 解码互操作 | **PASS=86 FAIL=0**（12 种编码组合 × 7 类输入 + 多 member 拼接）+ **损坏输入拒绝 5/5** | `python tests/gzip_inflate_test.py` |
| ECDSA P-256 验签互操作 | **PASS=32 FAIL=0**（20 正向 + 12 负向，Python bigint 参考实现） | `python tests/ecdsa_p256_test.py` |
| 自研 HTTPS GET（示例，手动） | **handshake ok cv=1；cert chain=2 host_ok=1 time_ok=1；HTTP/1.1 200 OK**（example.com，2026-10-22） | `python tools/stage0/qlm_cli.py run examples/https_get.qma --target win` |
| TLS 1.3 真实握手（手动探针） | **ok=1 cv=1**（cloudflare.com / www.cloudflare.com / example.com，2026-10-22） | `python tools/dev/tls_probe.py <host>` |
| TLS 1.3 握手核心（RFC 8448 §3） | **PASS**（共享密钥 / hs+ap secrets / key,iv / 服务器 Finished / 客户端 Finished 记录 58 B 逐字节一致） | `python tools/stage0/qlm_cli.py run tests/t69_tls_client.qma --target win` |
| RSA 验签（PKCS#1 v1.5 / PSS） | **t71 / t72 全绿**（1024 位正负向量 + PSS + 2048 位） | `python tests/run_win_tests.py` |
| X.509 证书链 / 有效期 / 域名 | **PASS=13 FAIL=0**（EC 三级链 + RSA 根混合链 + 通配符/过期/篡改/缺中间证书） | `python tests/x509_chain_test.py` |
| X.509 解析 + 自签验签互操作 | **PASS=7 FAIL=0**（4 正向：v3/v1/长 CN/大序列号；3 负向：篡改 TBS/篡改签名/截断） | `python tests/x509_test.py` |
| 调试器脚本化会话（v1.79） | **PASS**（18 项：断点行号/源码文本、int·bool·f64·str·struct 求值、`a.b` 字段、step/next 行推进、bt 帧链、退出码；外加调试构建与非调试构建输出逐字节相同） | `python tests/debugger_test.py` |
| DWARF v4 互操作（v1.80） | **PASS=20 FAIL=0**（CU 头 / 行表 40 条逐项 / subprogram 的 low_pc·high_pc / 变量位置多重集 / `Point` 布局 / DataDirectory[6] 为空） | `python tests/dwarf_test.py` |
| 调试器端到端命令链（v1.80） | **PASS=40 FAIL=0**（断点编号与命中计数、三种不可读语义、next/finish、bt、删除断点、程序输出与退出码） | `python tests/dbg_test.py` |
| 四道门禁 | check_names / check_origin / check_docs 全 PASS；`gen_stdlib_doc.py --check` PASS（57 个模块 / 379 个公开函数） | `python tools/dev/check_*.py` + `python tools/dev/gen_stdlib_doc.py --check` |

`run_win_tests.py` 的 8 组覆盖：PE 结构（MZ/PE32+/AMD64/无 CRT 符号）、基础语义、
语言特性（struct/enum/match/宽度/@simd/rc/所有权/vec/map/切片/函数值）、多核
（CreateThread 归约）、单核降级、arena 帧级回收、assert 失败路径、交叉验证、
调试链路（DWARF 互操作 + 调试器端到端）。

## 2. 产物

| 程序 | 大小 | 说明 |
|---|---|---|
| `examples/hello.qma` → `hello.exe` | 8.7 KB | 无 CRT，只导入 kernel32 |
| `examples/loop_sum.qma` → `ls.exe` | 6.6 KB | 全局 DCE 后只保留可达函数 |

## 3. 性能

### 3.1 标准库（`bench/p0_bench.qma`，程序内 `now_ns`，min of 3）

| 负载 | 耗时 | 吞吐 |
|---|---|---|
| AES-128-GCM 1 MiB | **19 ms**（v1.32 36 ms；v1.31 125 ms；v1.28 前 1369 ms，累计 **72×**） | 55 MB/s |
| └ CTR 段 1 MiB（AES 核心） | **2 ms**（软件 T-table 63 ms，**31×**，AES-NI） | 500 MB/s |
| └ GHASH 段 1 MiB | **17 ms**（v1.32 34 ms；v1.31 123 ms；PCLMULQDQ 硬件路径） | 62 MB/s |
| SHA-256 1 MiB | **44 ms**（v1.33 前 70 ms，**1.6×**：旋转内联 + K 表内存化） | 24 MB/s |
| gzip 编码 1 MiB（重复文本，输出 7658 B） | **16 ms**（v1.29 前 25–27 ms，**1.6×**，输出字节不变） | 65 MB/s |
| **gzip 解码 1 MiB** | **15 ms**（min of 3） | **70 MB/s** |
| CRC-32 1 MiB | **3–6 ms** | 170–330 MB/s |
| `str_split` + `join` 1 MiB（65537 段） | **8 ms** | 125 MB/s |
| `str_find` 1.1 MB 未命中（`bench/find_bench.qma`） | **558 µs**（v1.28 逐字节 2944 µs，**5.2×**） | 1.97 GB/s |
| 字节计数 1.1 MB（命中密集，20000 处） | **482 µs**（v1.28 逐字节 2543 µs，**5.2×**） | 2.28 GB/s |
| `str_split` 1.1 MB / 20001 段（含分配） | **2057 µs** | — |
| URL parse × 100k | **69 ms** | 0.69 µs/次 |
| JSON parse 92 891 B | **2 ms** | 46 MB/s |
| JSON 遍历 2000 对象 | **< 1 ms** | — |
| X25519 单次标量乘 | **7 ms** | 约 100× 于优化过的 C（OpenSSL ~0.05 ms） |
| ECDSA P-256 验签 | **25 ms** | 约 100× 于 OpenSSL；一次握手只需一次 |

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

### 3.4b f64 点积（`bench/dot_bench.qma`，1024 元素 ×2000，v1.60）

| 版本 | 每次 |
|---|---|
| 标量 | 约 1850 ns |
| `@simd` 点积（`acc += a[i] * b[i]`） | 约 535 ns |
| 加速比 | **3.5×** |

### 3.4c 类型约束（`bench/bound_bench.qma`，v1.61）

20M 次取小值，三个版本只差声明：带约束泛型 `[T: Ord]` / 不带约束泛型 `[T]` / 手写 int。
同一次运行内 min of 3：

| 版本 | ns/次 |
|---|---|
| `bmin[T: Ord]` | 1273 |
| `umin[T]` | 1273 |
| `imin`（手写 int） | 1264 |

差值在噪声内（±10%）：约束在单态化后**完全擦除**，三者落成同一份机器码。
编译期开销也在噪声内——220 个实例（20 个模板 × 11 种类型）构建 min-of-5：
带约束 **2639 ms** / 不带约束 **2662 ms**。

### 3.4d 泛型 struct 方法的派发成本（`bench/gimpl_bench.qma`，v1.62）

20M 次 `b.get()`，三份等价实现（同一次运行内 min of 3）：

| 派发方式 | ns/次 |
|---|---|
| 静态派发 `b.get()`（单态化后直接 call `Box__int__get`） | 1.7 |
| 手写普通函数 `direct(b)`（基线） | 1.7 |
| 动态派发 `let s: Val = b; s.get()`（vtable + callr） | 3.4 |

静态派发与手写函数同速（差值在噪声内）；动态派发约 2×——多一次 vtable 槽读取
与间接调用，与 v1.9 的接口派发口径一致。

### 3.4e 派生宏的运行时成本（`bench/derive_bench.qma`，v1.77）

4 字段 struct（`int` ×2 + `str` ×2），20000 次 × min of 3，三次运行取中位：

| 路 | ns/次 | 相对手写 |
|---|---|---|
| 编码 `r.json()`（`@derive(Json)` 生成） | 890 | +0.3% |
| 编码手写字段表（基线） | 887 | — |
| 解码 `Row_from_json`（派生） | 2171 | −0.6% |
| 解码手写（基线） | 2184 | — |

派生层是**编译期**展开，产物就是手写那段代码（基准里断言两者逐字节一致），
所以耗时差落在本机 VBS 噪声里、方向不稳定。

编译期代价（8 字段 struct，只派生 `Json`，编译 3 次取最小）：派生 447 ms /
29184 B，手写 448 ms / 28672 B——编译时间相同，体积差 +512 B 是解码函数本身
（`T_from_json` + `T__from_node`），不是元数据：运行时**零元数据**。

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
python tools/stage0/qlm_cli.py run bench/find_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/simd_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/dot_bench.qma  --target win
python tools/stage0/qlm_cli.py run bench/sync_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/bound_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/gimpl_bench.qma --target win
```

`bench/*.qma` 已内置 min-of-N；单次跑不可比。

### 3.8 调试链路（`tools/dev/dbg_bench.py`，min of 3）

`fixtures/dbgdemo/main.qma`，目标 `win`，2026-10-23 实测：

| 项 | 数值 |
|---|---|
| 默认构建 | 2163 ms |
| `--dbg-info` 构建 | 2211 ms（**+48 ms，×1.02**；调试构建不内联，与"多编码一份 DWARF"基本抵消） |
| 产物总计 | 14901 B |
| └ `.text` | 6353 B |
| └ `.qlmdbg`（自研） | 2742 B（**18.4%**） |
| └ `.debug_*`（DWARF 四节） | 1008 B（**6.8%**） |
| 调试会话固定开销（启动+加载+跑到退出） | 1540 ms（其中 Python 解释器启动 ~1.4 s） |
| 每次断点命中净开销（5000 次 continue 穿循环体） | **139–159 µs** |
| 每次源码行单步净开销（2000 次 next） | **0.96–1.05 ms** |

> 单步比命中贵一个量级：一行通常 3–6 条指令，每条指令一个单步事件
> （WaitForDebugEvent + Get/SetThreadContext 各一次）。`next`/`finish` 跨调用
> 已改成"返回地址临时断点"，否则一次 `next` 穿过 `print` 会逐指令爬几千步
> （实测 51 万步 / 231 秒）。线程句柄按 tid 缓存后，单步开销从 3.8 ms 降到 1 ms。
> VBS 噪声 ±50%，**只做纵向比较**。

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

**组件自举 2/9；代码行数 自举 1846 / stage-0 21128 = 8.7%**（`python tools/dev/selfhost_status.py`）。

## 5. 平台

| 平台 | 状态 | 证据 | 边界 |
|---|---|---|---|
| Windows x86-64（PE32+） | ✅ 主平台 | 本文 §1 主回归 | 无 CRT，只导入 kernel32 / ws2_32 |
| Linux x86-64（ELF64） | ✅ 构建级 | CI `run_native_tests.sh` | 本机无 gcc/WSL，只能 CI 验证 |
| Linux io_uring | ✅ | CI `test_uring.sh` | 需 5.1+ 内核 |
| AArch64（ELF64） | 🟡 | `tests/a64_emu.py` 执行级 | 无 chan/map/spawn/vtable/atomic/SHA；遇不支持形态编译期报错 |
| macOS（Mach-O） | ❌ | — | 无 |
| wasm32/64 | ❌ | — | 无 |
| TLS（https/wss） | 🟡 客户端可用（Windows） | `std/tls_net` + `std/x509`（链/有效期/域名 + RSA/ECDSA 验签）+ `examples/https_get.qma`（实测 200） | **无内置根证书库**（链校验需调用方给锚）；无 P-384/SHA-384；Linux 无 `tcp_connect`/DNS |

## 6. 已知风险

| 风险 | 影响 | 现状 |
|---|---|---|
| LICM 默认关闭 | 循环不变量无法外提，性能损失普遍存在 | x64 分配器布局敏感段错误未根修，`QLM_ENABLE_LICM=1` 可复现 |
| 接口装箱不释放 | 热点循环频繁装箱会涨堆 | 无 rc/drop 路径 |
| `and` 用 64 位立即数（≥2^63）曾算错 | SWAR 位运算踩过：改成 `>>7 & 0x0101…` 规避 | v1.29 已规避，根因未定位（见 `07-gaps.md` §7.2） |
| `f64` 比较曾整型化 | `if a > b` 对负浮点给出相反结果（v1.19 已修） | 根因：`branch()` 直接发 `jcc` 未走 `fcmpset`；回归 `tests/t64_math.qma` |
