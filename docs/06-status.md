# 当前状态（实测）

> **本文是全部实测数字的唯一出处。** 其它文档引用数字时写"见 `06-status.md`"。
> 口径日期：2026-10-24。环境：Windows 10/11 x86-64，Xeon E5-2666 v3（Haswell 代，
> **无 SHA-NI、无 AVX2**），VBS/Hyper-V 开启（进程冷启动 ~426 ms，跑分噪声 ±50%）。
> 解释器：Python 3.13.14。

## 1. 回归与对拍

| 项 | 结果 | 命令 |
|---|---|---|
| PE 回归（主回归） | **PASS=290 FAIL=0 SKIP=1**（v2.26 口径：qlmc 差分 35 → 37 条（新增 `s13_closure`），主回归总数不变；v2.25 口径：新增 `s12_ffi`；v2.24 口径：新增 `s11_import`；v2.23 口径：新增 `s10_defer`；v2.22 口径：新增 `s9_slice`；v2.21 口径：新增 `s8_map`；v2.20 口径：新增 `s7_aggfn`；v2.19 口径：新增 `s6_vec`；v2.18 口径：新增 `s5_enum`；v2.17 口径：新增 `s4_agg`；v2.16 口径：新增 `t143_parshard`（分片并行写 / 工作线程读共享 vec / 8 参 spawn）；v2.14 口径：新增 `[9b]` stage-1 编译器差分（`tests/qlmc_test.py`，7 条）；v2.13 口径：新增 `t141_vecindex`（vec 下标六形态）+ `test_exitcode()` 三条（`exit(运行期值)` 的退出码）；v2.12 口径：新增负向夹具 `net_serve_builtin`——reactor 搬进 std 后直接调内建 `net_serve` 必须给出迁移诊断；v2.11 那条 `.qla` 沙箱删除 FAIL 已随夹具改「就地覆盖」收口。以下为 v2.10 口径的历史记录：本版新增项 `[3j2]`：`t130_router_dispatch`（路由表 / 参数 / 404·405 / 表满）+ `http_router_test.py`（20 项真实 socket E2E）。**唯一 FAIL 是 `.qla` 目标文件用例撞沙箱的批量删除策略**（`[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]`：一次删 `build/_qlatest` 里 62 个文件，超过 50 个的阈值），与被测逻辑无关；`cache_test` 的 `build/` 争用失败本次未复现。v2.07 记录的那条 LSP FAIL 已收口（`tests/lsp_test.py` 的容错索引段改成 `std/sse` / `std/ws`（仍解析失败）负向 + `std/http` / `std/timer`（已修好）正向，内部断言 38 → 42）。SKIP 为 WSL 交叉验证，本机被沙箱拦。此前新增项：语言轨 `t97_atomic`/`t121_syncmpmc`/`t122_syncport`，工具链 `cov_test`（23 条断言）/`fuzz_test`（12 条断言）/`cache_test`（24 条断言，v1.100）/`kv_test`（10 条断言，v1.102）；语言轨 `[9] AArch64 接口 vtable`（7 用例）+ 两个跨文件接口负向夹具 + **模块系统 `modsame` 正例与 3 个多文件负例**（v1.101）） | `python tests/run_win_tests.py` |
| 词法器对拍 | **PASS=238 FAIL=0**（241 个源文件；SKIP 3 个含 `f"..."` 插值的文件——stage-1 词法器不认 `FSTR`，v1.61 插值未移植。**闭包不再进 SKIP 名单**：`fn(x: int) -> int { ... }` 用的全是既有记号，`t126_closure` 逐记号一致（v1.95）） | `python tests/lexdiff.py` |
| 声明级 AST 对拍 | **PASS=149 FAIL=1**（150 个源文件；唯一 FAIL 是 `tests/t115_derive.qma`——并行轨的 enum 派生让声明顺序变了、自举 parser 还没跟上，**与并发改动无关**。跳过 17 个：`t52_iface` / `t54_iface_dyn` / `t56_generic` / `t81_generic_infer` / `t99_generic_struct` / `t101_bounds` / `t102_generic_impl` / `t103_generic_enum` / `t104_generic_enum_impl` / `t116_iface_multi` / `iface_rc` / `iface_rc_a64` / `t118_iface_own` / `t119_drop` / `t123_derive_enum` / `t124_macro` / `t125_refl_dyn`——自举 parser 未做 interface/impl/泛型单态化、类型约束、泛型 impl 与泛型 enum，v1.96 的 enum 派生 / token 宏 / 运行时下标反射也未移植；v1.97 把 `iface_rc_a64` 与 `t118_iface_own` 按同一口径记账，`t120_ffi` / `t115_derive` / `dpub_*` 两侧逐行一致） | `python tests/parsediff.py` |
| 函数体 dump 对拍 | **一致 1719 / 分叉 1608 / SKIP 同步 26 / SKIP 不同步 44**（诊断项，非门禁：分叉随新增源文件增长，含 stage-1 body parser 未支持的 `defer`/f64 形态） | `python tests/bodydiff.py` |
| IR 架构无关对拍 | **PASS=89 FAIL=0 SKIP=68**（v1.98 实测：`t97_a64atomic` 与 `t122_syncport` 从 SKIP 转 PASS——A64 原子与 acquire/release 已能发射；SKIP 全是 arm64/ELF 未接的特性：`trunc`/map 聚合值/f64 二元运算/点积/`@ffi`/`spawn`） | `python tests/irdiff.py` |
| AArch64 接口 vtable 执行级（v1.97） | **PASS=7 FAIL=0**（`t52_iface` / `t54_iface_dyn` / `t116_iface_multi` / `t118_iface_own` / `ifacexfile` / `t104_generic_enum_impl` / `iface_rc_a64`。最后一项在 1 MB 堆上限下跑 1.14 MB 装箱量 + 900 KB 探针，证明 A64 上 `__iface_release` 真的把箱还回去了；整套约 70 s，纯 Python 模拟器） | `python tests/a64_iface_test.py` |
| 发射层确定性对拍 | **PASS=10 FAIL=0** | `python tests/emitdiff.py` |
| gzip 解码互操作 | **PASS=86 FAIL=0**（12 种编码组合 × 7 类输入 + 多 member 拼接）+ **损坏输入拒绝 5/5** | `python tests/gzip_inflate_test.py` |
| ECDSA P-256 验签互操作 | **PASS=32 FAIL=0**（20 正向 + 12 负向，Python bigint 参考实现） | `python tests/ecdsa_p256_test.py` |
| 自研 HTTPS GET（示例，手动） | **handshake ok cv=1；cert chain=2 host_ok=1 time_ok=1；HTTP/1.1 200 OK**（example.com，2026-10-22） | `python tools/stage0/qlm_cli.py run examples/https_get.qma --target win` |
| TLS 1.3 真实握手（手动探针） | **ok=1 cv=1**（cloudflare.com / www.cloudflare.com / example.com，2026-10-22） | `python tools/dev/tls_probe.py <host>` |
| TLS 1.3 握手核心（RFC 8448 §3） | **PASS**（共享密钥 / hs+ap secrets / key,iv / 服务器 Finished / 客户端 Finished 记录 58 B 逐字节一致） | `python tools/stage0/qlm_cli.py run tests/t69_tls_client.qma --target win` |
| RSA 验签（PKCS#1 v1.5 / PSS） | **t71 / t72 全绿**（1024 位正负向量 + PSS + 2048 位） | `python tests/run_win_tests.py` |
| X.509 证书链 / 有效期 / 域名 | **PASS=13 FAIL=0**（EC 三级链 + RSA 根混合链 + 通配符/过期/篡改/缺中间证书） | `python tests/x509_chain_test.py` |
| X.509 解析 + 自签验签互操作 | **PASS=7 FAIL=0**（4 正向：v3/v1/长 CN/大序列号；3 负向：篡改 TBS/篡改签名/截断） | `python tests/x509_test.py` |
| 调试器脚本化会话（v1.75） | **PASS**（18 项：断点行号/源码文本、int·bool·f64·str·struct 求值、`a.b` 字段、step/next 行推进、bt 帧链、退出码；外加调试构建与非调试构建输出逐字节相同） | `python tests/debugger_test.py` |
| DWARF v4 互操作（v1.80） | **PASS=20 FAIL=0**（CU 头 / 行表 40 条逐项 / subprogram 的 low_pc·high_pc / 变量位置多重集 / `Point` 布局 / DataDirectory[6] 为空） | `python tests/dwarf_test.py` |
| 调试器端到端命令链（v1.80） | **PASS=40 FAIL=0**（断点编号与命中计数、三种不可读语义、next/finish、bt、删除断点、程序输出与退出码） | `python tests/dbg_test.py` |
| 覆盖率链路（行 + 分支，v1.83） | **PASS=23 FAIL=0**（`cov.qma` 行 4/5、分支 1/2 且列出未覆盖分支 `8->9`；`main.qma` 行/分支双 100%；行与分支两种阈值各退出码 1；`cov2.qma` 两次运行合并后行 8/8、分支 4/4；`--lines-only` 分支显示 `0/0`） | `python tests/cov_test.py` |
| 模糊测试链路（v1.83） | **PASS=12 FAIL=0**（同 seed 逐字节一致 / 不同 seed 不同 / 变异生效且仍是合法 UTF-8 / built·rejected·bug 三分类口径 / 端到端 8 例 0 崩溃） | `python tests/fuzz_test.py` |
| doc comment 链路（v1.92） | **PASS=31 FAIL=0**（语法规则 10 / 前端挂载 6 / 工具链 14 / 产物逐字节相同 1） | `python tests/doc_test.py` |
| 文档生成门禁（v1.92） | **PASS**：62 个模块 / **531 个公开声明全部有 `///`**，0 个脱离块（v2.08 实测：`std/ds` 13 个 + `std/timer` 5 个 API 计入）；`03-stdlib.md` 与源码一致 | `python tools/stage0/qlm_cli.py doc std --missing` + `python tools/dev/gen_stdlib_doc.py --check --require-doc` |
| 语言服务器（v1.91） | **PASS=38 FAIL=0**（五段：词法对拍 321 文件 / 213208 记号分叉 0；容错索引 2 个前端解析不了的文件；索引语义；真 JSON-RPC 协议；性能阈值） | `python tests/lsp_test.py` |
| 性能门禁自测（v1.88） | **PASS=12 FAIL=0**（建基线 / 同产物判 PASS / 伪造 2× 回归必须 FAIL / 校验和与体积必须拦住） | `python tests/bench_gate_test.py` |
| 闭包 / 捕获（v1.95） | **t126 的 11 组断言全过**（无捕获 / 单捕获 / str+f64 / 逃逸 / 快照 / 嵌套 / 捕获 vec 句柄 / 循环建多个 / 聚合返回 + 聚合形参 / 6·8 参走栈）；负向 3 个编译期拦下（捕获 struct、体内写捕获变量、裸函数名当闭包传）；`--no-opt` 与 `--dbg-info` 构建输出一致；AArch64 构建通过（同一条 `callr`）；C 后端 fail-fast | `python tools/stage0/qlm_cli.py run tests/t126_closure.qma --target win` （主回归总数见 §1 主行；本版新增 1 正 + 3 负用例） |
| 包管理 qpm（v1.99） | **PASS=61 FAIL=0**（确定性打包逐字节一致 / 打包跳过产物 / 恶意 tar 拒绝 / spec 十一种形态 / registry 索引与包体落盘 / 同版本不可覆盖 / 传递依赖选版本 / 区间交集合并 / 无交集与跨来源冲突的诊断文案 / yank 后回退 / `--locked` 不升级且检出清单漂移 / `verify` 检出磁盘被改 / 依赖环可安装 / HTTP PUT 发布与 GET 安装 / 401 拒发 / 装完能被编译器 import 并跑出依赖里的字符串） | `python tests/qpm_test.py` |
| 五道门禁 | check_names / check_origin / check_docs 全 PASS；`gen_stdlib_doc.py --check --require-doc` PASS（62 个模块 / 528 个公开函数） | `python tools/dev/check_*.py` + `python tools/dev/gen_stdlib_doc.py --check` |

`run_win_tests.py` 的 10 组覆盖：PE 结构（MZ/PE32+/AMD64/无 CRT 符号）、基础语义、
语言特性（struct/enum/match/宽度/@simd/rc/所有权/vec/map/切片/函数值/**@ffi**）、多核
（CreateThread 归约）、单核降级、arena 帧级回收、assert 失败路径、交叉验证、
调试链路（DWARF 互操作 + 调试器端到端 + 行/分支覆盖率 + 模糊测试）、AArch64 vtable、语言服务器。

> **口径（v1.85 起）**：语言层与工具链双轨并行、共用同一个工作区，回归数字取
> "HEAD + 本版改动"的隔离 worktree（`git worktree add ../qbase183 HEAD`）上的实测值，
> 不取正在被另一条轨编辑的工作区。合并后若用例数变化，由合并方复核这一行。

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
| URL parse × 100k（`url_port` + `url_query_get`） | **58–62 ms**（v2.02 前 74 ms，**1.2–1.3×**） | 0.58–0.62 µs/次 |
| JSON parse 92 891 B | **2 ms** | 46 MB/s（1.35 MB 大文档见 §3.17：**49 MB/s**） |
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

### 3.4e 派生宏的运行时成本（`bench/derive_bench.qma`，v1.96）

v1.96 起 bench 分三种规模（整型 struct 1 万次、enum 5 千次、f64 1 千次 × min of 3，
三次运行取中位）。次数比 v1.72 低是因为**一个进程的 512 MB 堆上限**：没有 GC，
11 路 × 3 轮 × 每次一条字符串 / 一棵 DOM 会顶到上限（v1.72 只有 4 路，2 万次）。

| 路 | ns/次 | 相对手写 |
|---|---|---|
| 编码 `r.json()`（`@derive(Json)` 生成） | 1736 | +0.6% |
| 编码手写字段表（基线） | 1725 | — |
| 解码 `Row_from_json`（派生） | 4115 | +1.7% |
| 解码手写（基线） | 4045 | — |
| enum 编码 `e.json()`（派生） | 1214 | −0.2% |
| enum 编码手写 `match`（基线） | 1216 | — |
| enum 解码 `Ev_from_json`（派生） | 3447 | +2.6% |
| enum 解码手写 `match`（基线） | 3361 | — |

派生层是**编译期**展开，产物就是手写那段代码（基准里断言两路逐字节一致），
所以耗时差落在本机 VBS 噪声里、方向不稳定。

`f64` 字段的文本化（同一台机、同一轮）：

| 路 | ns/次 |
|---|---|
| `f64_repr(3.141592653589793)`（最短往返，`@derive(Json)` 用它） | 5531 |
| `x.to_str()`（内建，7 位有效数字） | 282 |
| `FRow { a: f64, b: f64, id: int }.json()`（两个 f64 字段） | 6530 |

`f64_repr` 比 `to_str` 慢约 20×：它要把二进制值展开成**精确十进制**
（尾数 × 2^e，e<0 时乘 5^k，base 1e9 大数）再回读验证 15/16/17 位。整型 / 字符串
字段完全不经过这条路径，所以 struct 编码的基线没有变化。

编译期代价（8 字段 struct，只派生 `Json`，编译 3 次取最小，v1.77 口径未变）：
派生 447 ms / 29184 B，手写 448 ms / 28672 B——编译时间相同，体积差 +512 B 是
解码函数本身（`T_from_json` + `T__from_node`），不是元数据：运行时**零元数据**。
enum 派生的生成代码量更大（每个变体一个 match 臂 × 三条路径），
`tests/t123_derive_enum.qma`（7 个类型）单文件编译 6–12 s（VBS 噪声大），属可接受范围。

### 3.4f int 点积（`bench/idot_bench.qma`，1024 元素，5 轮 × 2000 次取最小，v1.85）

| 版本 | ns/次 |
|---|---|
| 标量 `s = s + a[k] * b[k]` | 1295–1349（六次运行） |
| `@simd` int 点积（`acc += a[i] * b[i]`） | **660–670** |
| 加速比 | **约 1.96×** |

口径：HEAD `bb145a1` + v1.85 改动的隔离 worktree，同一份 1024 元素数据
（`a[i] = i%13+1`、`b[i] = i%11+1`，两路和均为 429710000），六次运行取中位。

- 上限来自 port 0：这段每 2 个元素必须发 3 条 `pmuludq`（64 位乘法只能拼），
  再加 1 条 `psllq`，本机（Haswell，`pmuludq` 只在 p0）就是 4 拍/2 元素 = 2 拍/元素。
- 首版用 `psrlq` 取高 32 位，两条 `psrlq` 也落在 p0 → 6 拍/2 元素，
  实测 972–1056 ns/次（约 1.33×）。改成 `pshufd`（p5）后降到 660 ns/次：
  **同一份算法，1.47× 的差距全在端口分配上**。
- 与 f64 点积的差别：f64 有单指令 `mulpd`，int 没有——所以 int 点积的收益
  主要来自**跳过逐元素越界检查**，不是来自并行度。

### 3.4g FFI 调用开销与吞吐（`bench/ffi_bench.qma`，3 轮取最小，v1.87）

| 负载 | 结果 | 说明 |
|---|---|---|
| 原生函数调用（递归函数，不可内联） | **2–3 ns/次** | 基线：调用 + 序言 + 返回 |
| `@ffi` 调 `kernel32!GetCurrentProcessId` | **3–4 ns/次** | 相对原生调用**多约 1 ns**：寄存器类分拣 + 32 字节 shadow space + 一次 IAT 间接跳转 |
| 1 MiB 拷贝：内建 `mem_copy` | **7.6–7.8 GB/s** | `__memcpy` |
| 1 MiB 拷贝：`ntdll!RtlMoveMemory`（FFI） | **6.1–6.4 GB/s** | 比内建慢约 20%——FFI 本身只差 1 ns，差的是两个实现（`rep movsb` 与 SSE 循环）的差异 |
| 1 MiB 串长：内建 `len(s)` | **2.6–3.0 ns/次** | 长度前缀，O(1) |
| 1 MiB 串长：`kernel32!lstrlenA`（FFI） | **119–141 µs/次**（7.5–8.8 GB/s） | 真的逐字节扫到 NUL，O(n) |

口径：同一进程内 `now_ns()` 计时，每段 3 轮取最小；`ffi_pid` 每轮 2×10⁶ 次，
拷贝 100 次 × 1 MiB，`len`/`lstrlenA` 各 1000 次。本机 VBS 噪声 ±50%（见文首口径），
跨机器不可比。

结论：**FFI 的固定开销 ≈1 ns（3 个周期）**，可以忽略；性能差异来自被调方实现本身，
不是调用机制。这也说明"能不能调系统库"是能力问题，不是性能问题。

### 3.4h `Drop` 析构的运行时成本（`bench/drop_bench.qma`，v1.93）

五种写法做同一件事（每轮绑一个 4 字聚合 `{x, y, buf}`、累加、块尾清理一次），
只有"清理怎么写"不同；n = 2×10⁶，**同一台机连续 6 轮按形状取最小**，单位 ns/轮：

| 写法 | ns/轮 | 相对基线 |
|---|---|---|
| 无清理（基线，`struct P`） | **3.9** | — |
| 手写显式清理 `release(buf)`（v1.93 之前的唯一做法） | **8.9** | +5.0 |
| `defer release(buf)`（v1.48：登记标志位 + 退出点分支） | **9.6** | +5.7 |
| **`impl Q : Drop`**（v1.93：块尾直接 `call`，无标志位） | **8.9** | +5.0 |
| 空析构体（只量调用本身） | **3.9** | ±0（内联后归零） |

- **`Drop` 与手写调用同价**（8.95 vs 8.93）：析构就是一次**静态** `call`，没有 vtable、
  没有闭包、没有登记标志位。
- **比 `defer` 省约 0.7 ns/轮**（9.6 → 8.9）：省掉的正是 defer 的"已登记标志 + 退出点分支"。
- 空析构体被内联后完全消失（3.9 ≈ 基线）；**关内联**（`QLM_NO_INLINE=1`）时
  一次空析构 +2.8 ns，即纯调用开销，与 §3.4g 的原生调用基线（2–3 ns/次）一致。
- 本机 VBS 噪声大（同一份代码不同时刻能差 1.5×），只做**同一次运行内的横向比较**。

> 复现：`python tools/stage0/qlm_cli.py run bench/drop_bench.qma --target win`
> （输出 11 行：预热 + 5 个总耗时 + 5 个 ns/次×1000）。

### 3.4j 接口装箱与动态派发的成本（`bench/iface_bench.qma`，v1.97）

四组做同一件事（`Sq{n}.area() = n*n`，1M 轮，程序内 min of 3；三次独立运行取最小），
单位 ns/轮：

| 组 | 写法 | ns/轮 | 相对静态派发 |
|---|---|---|---|
| A | 接口形参 `area_of(Sq{n})`——**每轮一次装箱 + 释放** | **25.4–28.1** | +20.6 |
| B | 接口值只装一次，循环里只 `vt[slot]` + 间接调用 | **5.4–7.7** | +0.6 |
| C | 循环体内 `let s: Shape = Sq{n}`（块尾释放） | **24.8–31.1** | +20.0 |
| D | 静态派发 `let q = Sq{n}; q.area()`（基线） | **4.8–5.4** | — |

- **vtable 派发本身很便宜**：B − D = **0.6 ns/次**（约 +12%），与 §3.4i 的裸函数值
  （`callr` 4.6–5.0 ns）同量级——多出来的一次 load（`vt[slot]`）几乎免费。
- **贵的是装箱**：A − B = **20 ns/次**，C − D = **20 ns/次**，两路一致。
  这一份成本 = `__alloc` + 拷 payload + 写 rc/字节数 + `__free` 归还尺寸类。
- 所以"热点循环里每轮装箱"仍要避免（20 ns 是静态派发的 4 倍），但**不再涨堆**：
  同一形状跑 1M 轮，v1.83 前堆增长 24 MB，现在稳态在几 MB 内
  （`tests/iface_lowheap` 用 1 MB 上限跑 19 MB 装箱量就是这条的回归）。
- 用法结论：**接口值装一次、循环里只派发**（B 组形态）几乎无成本；
  每轮新建接口值（A/C 组）按"每次 20 ns"算预算。

> 复现：`python tools/stage0/qlm_cli.py run bench/iface_bench.qma --target win`
> （输出 4 行 µs/1M，本机 VBS 噪声 ±20%，只看组间差值，别拿绝对值跨机器比）

### 3.5 并发原语（`bench/sync_bench.qma`，rdtsc，n=2e6，单线程，v1.98）

同一台机器、同一个编译器、同一时段的 A/B（旧列 = HEAD 的 `std/sync`，
5 次运行取中位；VBS 噪声下同列不同次可差 ±50%）：

| 操作 | v1.97（旧） | v1.98 | 说明 |
|---|---|---|---|
| 普通自增 | 2 | 3 | 基线（循环 + 自增 + 比较） |
| `atomic_add` | 26 | 25 | `lock xadd`，与栈/锁改动无关 |
| 自旋锁保护的读改写 | 28 | 29 | 解锁改 release 存储，x86 下同一条 `mov` |
| 栈 push+pop（无锁 pop） | 125 | — | 旧路径 = 现在 `stack_pop_single` |
| 栈 push+pop（MPMC 安全 pop） | — | **144** | 多一次原子交换 + 一次 release 存储 |
| 栈 push+pop（`stack_pop_single`） | — | **121** | 单消费者快路径，与旧路径同速 |
| `chan` send+recv（容量 1） | — | **73** | 含一次抢锁 + 一次放锁 |
| `wg_wait`（计数已为 0） | — | **5** | 只测"检查一次"的成本 |

**结论**：MPMC 安全的 pop 比旧的无锁 pop 贵 **19 cycles（+15%）**；单消费者
走 `stack_pop_single` 与旧路径无差（121 vs 125，噪声内）。这 19 cycles 买的是
"节点地址被复用时也不会 ABA"——旧路径的正确性依赖"节点永不回收"这条隐含前提。

### 3.5b WaitGroup 等待的 CPU 成本（`bench/wg_bench.qma`，v1.98）

同一个等待（worker 睡 200 ms 后 `wg_done`），两种等待策略各跑一遍，
`now_ns()` 量墙钟、`cpu_ns()` 量进程 CPU 时间（3 次运行区间）：

| 策略 | wall | CPU | CPU / wall |
|---|---|---|---|
| 纯自旋（v1.93 及以前 `wg_wait`） | 205–210 ms | 109–171 ms | **51–82%** |
| 三段退避（v1.98：64×`pause` → 1024×`thread_yield` → `sleep_ms(1)`） | 217–271 ms | 0–15 ms | **0–6%** |

代价是唤醒粒度：`sleep_ms(1)` 在本机（Windows 默认 15.6 ms 时钟片 + VBS）
实际约 **25 ms**，所以长等待的唤醒可能晚 25 ms（wall 那列的 217–271 ms 就是它）。
毫秒级等待（3 ms 忙任务）不会掉进睡眠段：实测 wall 5–16 ms、等待方 CPU ≈ 0。

### 3.5c chan 抢锁策略 A/B（否决的实验，v1.98）

把通道锁的"抢不到就 `thread_yield`"改成"先 `pause` 32 次再让出"，
同一份源码、只改这一个常量，两个变体各跑 7 次：

| 场景 | 抢不到就让出（保留） | 先自旋 32 次（已回滚） |
|---|---|---|
| 双线程 ping-pong（`bench/chan_bench.qma`） | 36 µs/往返 | 37 µs/往返 |
| 4 生产者 × 5000 条，容量 8 | 中位 51 ms（21–337） | 中位 62 ms（16–179） |

区间大幅重叠，**没有可复现的收益**。自旋只对"持锁者一定在跑"成立，本机 2 vCPU
跑 4 个生产者时这个前提不成立。按"测不出好处就不留复杂度"，改动已回滚。
（早期在并行构建把机器打满时曾观察到秒级尾延迟，那是环境噪声，不能算证据。）

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
python tools/stage0/qlm_cli.py run bench/idot_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/sync_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/wg_bench.qma   --target win
python tools/stage0/qlm_cli.py run bench/chan_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/bound_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/gimpl_bench.qma --target win
python tools/stage0/qlm_cli.py run bench/drop_bench.qma  --target win
```

`bench/*.qma` 已内置 min-of-N；单次跑不可比。

并发三个基准的读法：`sync_bench` 报 cycles/iter（单线程、程序内 `rdtsc`）；`wg_bench` 报 wall / CPU / CPU 占比（`now_ns` 与 `cpu_ns` 一起读，判"有没有烧核"）；`chan_bench` 报往返延迟（两线程交替，判通道锁的固定成本）。

### 3.8b 文档生成（`tools/dev/doc_bench.py`，min of 5）

`///` 的扫描是"解析每个文件时多走一遍行"，没有第二次词法，也不进 IR：

| 项 | 数值 |
|---|---|
| 全库扫描（60 文件 / 552 KB / 554 行 `///`） | **5.6 ms**（**97 MB/s**；单文件均摊 ~93 µs） |
| 同批文件全库词法 | 236 ms → doc 扫描是它的 **2.4%** |
| 最大文件 `std/aes.qma`（1087 行） | 词法 15.3 ms / doc 扫描 0.31 ms（**2%**） |
| 一次真实构建（`examples/hello.qma`） | doc 扫描占 **0.35%**（构建要加载 std 全库，按文件数线性摊开） |
| 产物体积 | **+0 B**——带与不带 doc comment 的同一程序 PE 逐字节相同 |

口径：只有源码里出现 `///` 或 `//!` 才启动扫描（`"///" in src` 的 C 级子串判断，
未写文档的项目一行都不扫）；本机 VBS 噪声 ±50%，**只做纵向比较**。
复现：`python tools/dev/doc_bench.py`。
> 2026-10-24 复测（v2.01）：上一轮记录是 12–15 ms / 595 ms 词法，同一台机器这次整体
> 快 2.5 倍——机器负载不同批次，**不要把两批的绝对值混着比**，比值（2.4%）才是口径。

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

覆盖率 / fuzz 链路的性能见 §3.12。

### 3.9 所有权检查的编译期开销（`tools/dev/own_bench.py`，v1.84）

所有权检查是**纯编译期**的 AST 遍历（`04-compiler.md` §1.1），所以只有两个数字
值得记：它占编译时间多少，以及它会不会改变产物。

**① 占端到端编译的比例**（min of 3，两次运行取区间；端到端含解析 + 降级 + 优化 + 编码）

| 源文件 | 被检查函数 | 检查器耗时 | 占端到端 |
|---|---|---|---|
| `tests/t116_ownview.qma` | 5 | 1.4–2.4 ms | 0.61–0.94% |
| `tests/t106_weblib.qma` | 21 | 3.8–8.9 ms | 0.64–0.66% |
| `examples/https_get.qma` | 187 | 48.8–88.4 ms | 0.43–0.59% |
| 合计 | 213 | 54–100 ms | **0.45–0.60%** |

绝对值随机器负载漂移很大（同一份源两次运行差 2.5 倍，VBS 噪声），**只有占比可比**。

**② 运行时零成本**（检查开 / 关，同一份源的 PE 逐字节比对）

| 源文件 | 检查开 | 检查关 | 一致 |
|---|---|---|---|
| `tests/t116_ownview.qma` | `cf3f6b29e9818aa9` / 23552 B | 同左 | ✅ |
| `tests/t106_weblib.qma` | `d70ac51efcd1c928` / 53248 B | 同左 | ✅ |

这条是"不碰 IR"的直接证据：检查只读 AST、不改写，产物字节完全一致。

**③ `_own_parts`：跳过已摊平的块体**（每层 8 条语句的合成源，只计 `_check_views`，min of 15）

`_flat_stmts` 先把嵌套块摊成一维，再逐条处理。若对每条复合语句仍走一遍完整子树，
第 k 层的语句就要重复访问 k 层以下的全部节点——**O(深度²)**。`_own_parts` 只返回
语句"自己的"表达式部分（`if` 的条件、`for` 的界、`match` 的被匹配值…），块体交给
摊平后的下一轮，回到线性。

| 嵌套深度 | 摊平后语句 | 现版（`_own_parts`） | 朴素（整条语句走子树） | 朴素/现版 |
|---|---|---|---|---|
| 4 | 48 | 0.5–1.3 ms | 1.7–2.4 ms | 1.8–3.5× |
| 8 | 84 | 1.6–2.0 ms | 6.6–7.3 ms | 3.7–4.6× |
| 16 | 156 | 2.8–3.0 ms | 26.2–27.1 ms | 9.1–9.2× |
| 32 | 300 | 5.6–5.9 ms | 107–117 ms | 18–21× |

（区间取三次运行；深度 4 的绝对值都在 1 ms 上下，比值噪声最大。）

语句数只涨 6.25×（48 → 300）：朴素写法涨 **49–63×**（平方项主导），现版涨 5–11×
（小样本里固定开销占比大，所以不是严格的 6.25×）。

**真实代码看不出差别**：嵌套普遍只有 2–3 层，`_own_parts` 前后落在噪声内
（`t106_weblib` 曾测出 2.28×、`https_get` 曾测出 0.87×，方向相反 → 该量级不可分辨）。
加这个助手不是为了常见情形更快，而是**堵住深嵌套的平方级退化**——生成式代码、
机械展开的 `match`/`if` 链会踩到。

复现：

```bash
python tools/dev/own_bench.py                 # ① + 真实文件的 _own_parts 对照
python tools/dev/own_bench.py --bytecheck     # ② 产物逐字节
python tools/dev/own_bench.py --scale         # ③ 深度扫描
```

口径：Windows x86-64 / Xeon E5-2666 v3 / VBS 开启 / Python 3.13.14，**只做纵向比较**。

### 3.10 语言服务器（`tools/stage0/qlm_index.py`，v1.91）

单文件冷索引（`Index(path, src)`，9 次取中位，**不含**被导入模块的一次性索引）：

| 文件 | 行 | 记号 | 中位 | 最小 |
|---|---|---|---|---|
| `examples/hello.qma` | 20 | 74 | **0.64 ms** | 0.62 ms |
| `fixtures/lspdemo/main.qma` | 40 | 196 | **1.86 ms** | 1.37 ms |
| `tests/t101_bounds.qma` | 133 | 696 | **5.09 ms** | 3.93 ms |
| `std/httpc.qma` | 310 | 1479 | **10.79 ms** | 9.33 ms |
| `std/sha512.qma` | 420 | 3071 | **26.35 ms** | 21.10 ms |
| `bootstrap/parser/qlm_parse.qma` | 1688 | 12243 | **107.21 ms** | 96.79 ms |

随记号数线性增长（约 8 µs/记号：词法 ~40%、结构扫描 ~35%、引用解析 ~25%）。
100 ms 是"整篇重建"的上限：再大的文件要靠客户端 debounce 或做增量索引
（登记在 `07-gaps.md` §3）。

全仓库首次索引（321 个 `.qma`，**含** import 传递的一次性索引）：**3.0–3.5 s**
（三次 3453 / 3542 / 3191 ms），均值 **9–11 ms/文件**；之后按文件缓存，
编辑只重建被改的那个。

补全（`completion` 的内核，200 次，`tests/t101_bounds.qma`）：**p50 0.5–0.9 ms /
p95 1.6–1.9 ms**（多次运行的区间，单次请求到出结果）。词法对拍规模：
**321 个源文件 / 213208 个记号，分叉 0**。

复现：`python tests/lsp_test.py`（`[E]` 段直接打印上面这些数字）。
同一台机器上并行跑别的构建会让这些数整体上浮 2–3 倍（实测过 7.4 s / 23.8 ms
的读数，那是回归进程在抢 CPU），**只做纵向比较**。

### 3.11 性能回归门禁（`tools/dev/bench_gate.py`，v1.88）

口径：Windows 10/11 x86-64，Xeon E5-2666 v3，VBS 开启，qlm 1.92.0，2026-10-24。
测量时另一条轨在本机并行跑构建（非空载），**绝对值只做纵向参考**，可比的是比值。

夹具基线（`bench/perf_baseline.json`，进程内 `now_ns`，min of 3）：

| 形状 | ns/iter | 说明 |
|---|---|---|
| `arith` 8M | 4.75 | 整数依赖链（乘 / 移位 / 异或） |
| `branch` 8M | 7.56 | 数据相关分支（小状态机） |
| `memscan` 1 MiB | 2.94 | 逐字节扫描 + 模式计数 |
| `strbuild` 2k 行 | 1272.55 | 拼接 + 整数转字符串 |
| `mapstr` 5k 键 | 594.50 | `map[str]int` 插入 + 全量查找 |
| `sha256` 256 KiB | 68.79 | 标准库热路径 |
| `cal` 16M（校准分母） | 2.98 | 纯标量整数链，做归一化 |
| 产物 | 80896 B | DCE 后体积 |

判定稳定性（同一份产物重复判定）：

| 模式 | 两次判定的 Δ 范围 | 离散度 | 说明 |
|---|---|---|---|
| 基线 `--check` | −6.5…+7.7% / −13.6…+7.3% | ±12% / ±50% | 25% 阈值留够余量；±50% 那次 `mapstr` 被噪声闸标成 noisy，不判失败 |
| A/B `--ab HEAD`（**同一份代码**两边） | −3.0…+4.8% | — | 噪声底 ≈5%，15% 阈值是它的 3 倍 |
| A/B 真实对比（HEAD `bb145a1` vs 工作区） | −4.7…+4.0% | — | 这一轮编译器改动在这 6 个形状上无代价 |

耗时：

| 项 | 耗时 |
|---|---|
| 基线模式一次判定（构建 + 3 次运行 + 噪声采样） | 27–30 s |
| A/B 一次判定（两棵树构建 + 6 次交错运行） | 43 s |
| 门禁自测 `tests/bench_gate_test.py` | 12 项，约 1 min |

两条口径，避免误读：

- **`--no-opt` 在这 6 个形状上不变慢**（`mapstr` +18.7%、`arith` −2.2%，都在噪声内）：
  形状本身是紧循环，优化器能做的有限。所以"关优化不变慢"不能当"优化没生效"的证据，
  要看 §3.1 那些库函数负载。
- **校验和跨版本一致**：`QLMDIGEST=668567131` 在 HEAD（v1.75 口径编译器）与工作区
  （v1.92）上相同 → 这些形状的计算语义没被本轮改动动过，A/B 的时间对比因此成立。
- **噪声闸的口径是"回归必须大于噪声"**：同一份代码在不同时刻实测能差 ±30%，另一条轨
  并行构建最重时离散度到过 ±66%；所以判红要求 `Δ > max(阈值, 该形状离散度)`，
  A/B 里看到的 `noisy(±21%)`、`noisy(±66%)` 就是这条在起作用。


### 3.12 覆盖率与 fuzz（`tools/dev/cov_bench.py`，min of 2–3）

本机实测，2026-10-24（VBS 噪声 ±50%，只做纵向比较）：

| 项 | 数值 |
|---|---|
| 产物（`fixtures/dbgdemo/main.qma`，`--dbg-info`） | 15413 B |
| └ `.qlmdbg` 节 | 3111 B（**20.2%**） |
| └ 其中分支表 | 241 B（主文件 1 条分支） |
| `--dbg-info` 构建 vs 默认构建 | 3860 ms vs 4837 ms（**差值落在噪声内**；分支表只是每条 `jcc` 记一条 4 元组，不进 IR、不影响代码生成） |
| 采集会话 `loop.qma`（5000 次循环）：行 + 分支 | 11.8 s |
| 采集会话 `loop.qma`：仅行（`--lines-only`） | 11.0 s |
| 分支断点的额外成本 | **+0.8 s / 1251 次分支命中（≈0.67 ms/次）** |
| 汇总工具（`build/qlm_cov.exe`）进程冷启动 | 636 ms |
| 汇总 `main.qma`（5 行 / 1 分支） | 707 ms（净 ~70 ms） |
| 汇总 `tools/qlm_cov.qma`（264 行 / 39 分支） | 779 ms（净 ~140 ms） |
| fuzz 生成 32 例（含变异器进程启动） | 0.84 s |
| fuzz 编译 32 例（种子 `cov.qma`） | 2.58 s（**12.4 例/s**） |
| fuzz 战役（8 个 seed × 30–40 例，3 个种子文件） | 290 例，崩溃 0 |

> 成本结构：整条链路的钱花在**调试会话**（每次命中一个 `WaitForDebugEvent`，
> 外加一次单步回填 int3），不在统计。汇总工具本身 70–140 ms，冷启动就占 636 ms。
> 分支断点的额外成本 ≈ 一次普通命中的 4–5 倍（0.67 ms vs 140–160 µs）：分支命中
> 之后同样要单步回填 `int3`，而那一步的固定开销（Get/SetThreadContext）远大于
> 事件本身。要压这块只能换插桩，不是调参能解决的。
>
> 命中计数不等于执行次数：`loop.qma` 跑 5000 次循环，行/边命中各只记到 1251 次
> （每次命中后单步回填期间不再触发）。覆盖率是二值判断，不受影响；但别把日志里的
> `hits` 当执行次数用。

### 3.13 包管理（`tools/dev/qpm_bench.py`，min of 3–5，v1.99）

合成 registry：40 个包 × 3 个版本、77 条依赖边，每包 3 个 `.qma` 文件；
全部在**同一进程内**调用 qpm 的 API，不含解释器启动（本机约 1.4 s）。

| 项 | 数值 |
|---|---|
| 合成 registry（一次性发布 120 个版本） | 5044 ms |
| 解析（冷：重读全部索引） | **371.0 ms** |
| 解析（热：索引缓存命中） | **48.3 ms** |
| install 全流程（解析 + 落地 40 个包 + 写锁） | **1987.2 ms** |
| `verify`（40 个包全量内容哈希） | 123.9 ms |
| `publish` 打包（20 文件，确定性 tar.gz） | 18.1 ms |
| 单包体积（4 文件） | 275 B |

> 冷/热差 7.7× 全在**索引读取与 JSON 解析**（40 个索引文件），不在版本比较：
> 区间求值 + 交集 + 定点迭代只占热路径的一部分。所以大工程的第一条优化不是
> "更快的不等式"，而是"少读几份索引"——sparse index 已经只读被引用的包。
> 落地成本（1987 − 48 ≈ 1.9 s）几乎全是 40 次解包；`verify` 只要 123.9 ms，
> 说明算哈希不贵，贵的是解包（tar + 写盘）。真实 `qpm install` 命令的墙钟时间
> 还要加上解释器启动。

### 3.14 增量 / 并行编译（`tools/dev/incr_bench.py`，min of 3，v1.100）

口径：墙钟 = 用户等待的整条命令（含 Python 启动）；编译 = 编译器自报的
`重编 N ms` / `缓存命中 N ms`（不含启动）。每个点取 min of 3。

**单单元：全量重编 vs 缓存命中**

| 源文件 | 全量墙钟 | 全量编译 | 命中墙钟 | 命中编译 | 编译阶段加速 |
|---|---|---|---|---|---|
| `examples/hello.qma` | 2795 ms | 1168 ms | 1798 ms | **190 ms** | **6.1×** |
| `examples/https_get.qma`（20 个 std 模块） | 11800 ms | 10144 ms | 1931 ms | **232 ms** | **43.7×** |
| `tests/t69_tls_client.qma` | 8524 ms | 6776 ms | 1917 ms | **239 ms** | **28.4×** |

命中路径的 1.8–1.9 s 墙钟里，编译只占 0.2 s，其余是 **Python 进程启动**
（本机 VBS 开启，空进程 1.2 s 上下）+ 缓存查表（哈希闭包 + 校验产物）。

**16 个单元并行（合成单元，各 ~1 s 编译）**

| 模式 | 墙钟 | 结果 |
|---|---|---|
| `build` 多源 `-j 1` | 15.0 s | 16/16 |
| `build` 多源 `-j 8` | **6.7 s** | 16/16（**2.2×**） |
| `test -j 1` | 23.6 s | PASS=16 |
| `test -j 8` | **8.1 s** | PASS=16（**2.9×**） |

**并行天花板在进程创建**，不在 CPU：同一台机器上 `python -c pass` 串行 **1233 ms/个**，
16 个空进程用 8 并发也要 6.7 s（约 3.3×，再高上不去）。所以：

- 单元越重、越多，并行越接近线性；单元很轻时 **串行 + 缓存** 更快
  （`-j 1` 在同进程内编所有单元，import 只付一次）。
- 这里报的是"最优串行 vs 最优并行"，不是同一条实现开不开 `-j`。
- 缓存与并行**叠加**时：先按内容过滤掉没变的单元，再把剩下的分给 worker——
  CI 里典型收益是"改 1 个文件 → 只编 1 个"。

缓存体积：`.qlmcache/entries/<key>/{meta.json,artifact}`，一条 `hello` 约 9 KB、
`https_get` 约 600 KB；命中率与累计省时由 `quelmara cache --stat` 报告。


### 3.15 链接期（`tools/dev/link_bench.py`，min of 5，v1.101）

链接层（import 合并 + 限定引用解析 + per-module mangling）是**纯编译期**的，
运行时零开销。三档同规模（40 个模块 × 40 个函数 = 1600 个顶层函数 + 主文件），
两轮实测：

| 场景 | load_program | 相对 |
|---|---|---|
| 无重名、未限定（恒等路径） | 452 / 469 ms | ×1.00 |
| 无重名、全部限定调用 | 482 / 443 ms | ×1.07 / ×0.94 |
| 每模块同名 `f0..fN`（mangling + 限定调用） | 441 / 440 ms | ×0.98 / ×0.94 |

三档差异在噪声内：**改名表与引用重写是字典查一遍的量级**，时间几乎全在解析
（21 个文件、1600 个函数）。口径：`python tools/dev/link_bench.py`，
本机 VBS 噪声 ±50%，只做纵向比较。

### 3.16 持久化 KV（`bench/kv_bench.qma`，v1.102 / 批量提交 v2.01）

`std/kv` = 追加日志 + 内存索引；`std/fs` 走 `@ffi` 直调 kernel32。
数据集 2 万条（8 B 键 + 32 B 值），键值**预先构造好、不计时**；进程内 `now_ns()`。
两列是**同一台机器、同一天、同一条命令**的 A/B（各 3 次取中位）：左列是 v1.102 的
"每条一次 `WriteFile`"，右列是 v2.01 的"攒 64 条合并成一次 `WriteFile`"。

| 项 | 改造前（每条一次写） | 改造后（批量提交） | 变化 |
|---|---|---|---|
| put 2 万条 | 331 ms（16.5 µs/条，≈ 60k 写/秒） | **54 ms（2.7 µs/条，≈ 370k 写/秒）** | **6.1×** |
| get 2 万条 | 3 ms（190 ns/条） | 3 ms（**160 ns/条**，v2.02 去掉重复查表） | 1.19× |
| 覆盖写 2 万次（2000 键 × 10 轮） | 324 ms（16.2 µs/次） | **42 ms（2.1 µs/次）** | **7.7×** |
| put + `kv_sync` ×200 | 79 ms（**397 µs/条**） | 76 ms（**384 µs/条**） | 不变（每条都等落盘） |
| 重开 + 重放 20 200 条 | 38 ms（1.85 µs/条） | 38 ms（1.9 µs/条） | 不变 |
| 压缩 | 342 ms，**2 660 010 B → 1 343 695 B** | 351 ms，同体积 | 不变（纯重写活记录） |
| 单条记录 | 66 B | 66 B | **磁盘格式未变** |

> 写路径原先被**文件 I/O 支配**：一条 66 字节记录，语言侧只做一次 `map` 插入与一次
> `WriteFile`，16 µs 里绝大部分是内核与文件过滤驱动（本机开着 Defender）。批量提交把
> 这 16 µs 摊到 64 条上，剩下 **2.7 µs/条** 全是语言侧成本：`_rec` 拼记录（两次分配 +
> 三次 `int.to_str`）+ `map` 插入 + `vec.push`。读路径仍是纯内存的 190 ns——两者差
> **14 倍**（改造前是 87 倍），所以下一步要再快就轮到 `_rec` 的分配次数，不再是 I/O。
>
> `kv_sync` 384 µs/条 是「每条都等落盘」的代价，批量提交对它**没有帮助**（每次 sync 都要
> 先把缓冲冲刷干净）：真实用法是写一批、sync 一次。代价是**崩溃窗口**——进程被强杀时
> 最多丢最后不足 64 条（掉电仍要 `kv_sync`），已写进 `std/kv.qma` 头注释与
> `07-gaps.md` §2 的边界栏。

> 恢复路径的正确性在 `tests/kv_test.py` 里用**独立 Python 解析器**对拍磁盘格式：
> 撕裂尾（砍掉半条记录）只丢那一条，垃圾尾（追加 200 字节）不影响重放，两种情况之后
> 继续写都一致。


### 3.17 v2.02 批量微调（A/B，同机同日，各 3 次取中位）

四处"去掉多余分配 / 多余扫描"，全部是库内改动，**不动编译器**：

| 负载 | 改动前 | 改动后 | 倍数 | 改了什么 |
|---|---|---|---|---|
| `url_port` 单次 | 275 ns | **178 ns** | **1.55×** | authority 一遍扫完（原来 5 遍）+ 端口数字就地解析（不再 `substr` + `to_int`） |
| `url_query_get` 单次 | 453 ns | **385 ns** | 1.18× | 直接在 URL 上扫（不再先分配 query 子串）+ 只有区间含 `%` 才 decode |
| `p0` URL parse × 100k | 74 ms | **58–62 ms** | 1.2–1.3× | 上面两条合起来 |
| `json_parse` 1.35 MB | 31 ms / 41 MB/s | **26 ms / 49 MB/s** | **1.19×** | 按输入长度预分配节点池 / kids / 字节池（省 13 次 realloc 与约 17 MB 拷贝） |
| `kv_get` 2 万条 | 190 ns/条 | **160 ns/条** | 1.19× | 先 `get` 再按需 `has`——非空值只查一次表 |
| `sha256` 1 MiB | 41–42 ms | 41–42 ms | **1.00×** | 8 轮展开实现并验证正确（t43 向量 + TLS 逐字节），**测不出收益 → 已回退** |

> 三个"做了但没留代码"的实验，都验证过正确性：
>
> ① **SHA-256 8 轮展开**：状态变量按环移位命名，每轮末尾 8 条搬移（`h=g; g=f; …`）
> 全部消失，1 MiB 仍 41–42 ms。瓶颈在**指令数**——每块约 3000 条（64 轮 × ~35 +
> 48 步调度 × ~15），8450 cycles/块 ≈ 2.8 cycles/条，已经接近这段代码的发射上限；
> 而 x86 的 `mov` 本来就在寄存器重命名阶段被消掉，省掉它们不省时间。要更快只能上
> SHA-NI（本机无该扩展）或让 `int` 走 32 位指令（Quelmara 的 `int` 恒 64 位，
> `& 0xFFFFFFFF` 掩码消不掉）。结论已改写进 `07-gaps.md` §5。
>
> ② **JSON 容器共用暂存缓冲**（去掉每对象一个 `vec[int]`，2 万对象 = 2 万次分配）：
> 26 → 27 ms，落在噪声内 → 回退，"测不出好处就不留复杂度"。
>
> ③ **`vec[u8]` 槽压缩**：查了全库——`std/` 里 `vec[u8]`/`u16`/`u32` 一共只有 **3 处**，
> 而 `vec[int]` 339 处、`vec[str]` 42 处。压缩对真实代码没有收益，已从 §5 的优先级里降级。

### 3.18 日志（`bench/log_bench.qma`，v2.03）

`std/log` = 级别过滤 + 绝对时间戳 + stdout/stderr 双通道；`std/logfile` = 追加写 +
按大小轮转（走 `std/fs`，Windows PE）。进程内 `now_ns()`，2 万行，跑 5 遍取中位；
行内容固定 50 字节（`GET /api/v1/items?page=3 200 12ms user=42`）。

| 项 | 结果 | 说明 |
|---|---|---|
| 级别过滤（被丢掉的行） | **2 ns/行** | 一次静态字读 + 比较就返回，不格式化、不分配 |
| 格式化（同一毫秒内） | **101 ns/行** | 时间戳走缓存：只有每毫秒第一行要算日历 |
| 格式化（每行强制重建） | **375 ns/行** | 日历换算 + 19 个数字位，用改时区强制缓存失效测得 |
| 格式化（相对时间戳） | **205 ns/行** | 老格式 `[1234ms]`；每行都 `to_str`，比绝对时间戳**慢约 2 倍** |
| 格式化 + 结构化字段（4 个 kv） | **351 ns/行** | `log_format_kv` |
| 文件通道（64 KB 攒批） | **434 ns/行，173 MB/s** | 含格式化 + 拷进缓冲；每批一次 `WriteFile` |
| 控制台通道 | **19.3 µs/行** | 终端/管道速度，不是日志库成本（单独列） |
| 轮转一次（改名 5 次 + 新建） | **15.7 ms** | 环境数字，见下 |

> **为什么绝对时间戳反而更快**：v1.16 的相对格式每行都要 `(now_ns()-t0)/1e6` 再
> `to_str()`（一次分配 + 一次整数转字符串）；v2.03 的绝对时间戳在**同一毫秒内复用**
> 上一次的结果（一次 `wall_ms()` + 一次比较 + 29 字节 `mem_copy`），毫秒精度下语义
> 完全等价。2 万行只跨 2–3 毫秒，日历换算总共只发生 2–3 次，所以稳态就是 101 ns。
>
> **轮转 15.7 ms/次 是环境数字，不是库成本**：同机基线 `open/write/close` ≈ 2.8–3.9 ms、
> `rename` ≈ 2.3–2.9 ms/次（本机开着 Defender，文件过滤驱动把每次元数据操作都拖到毫秒
> 级）。一次轮转 = 5 次改名 + 1 次新建，正好对得上。部署里 4 MB 轮一次，等于每 10 万行
> 付一次这个钱。实现上刻意**不用 `fs_remove`**：`MoveFileEx(REPLACE_EXISTING)` 会把最旧
> 一份直接覆盖掉，省掉一次 unlink——本机 `DeleteFile` 约 100 ms，比 rename 贵两个数量级
> （这一改动把轮转从 122 ms/次 降到 15.7 ms/次）。
>
> 正确性：`tests/t131_log.qma` 自校验时间戳形态（29 字节 / 分隔符 / 三位毫秒 / 偏移符号）、
> 时区正负偏移、相对模式、级别过滤、文件通道（追加 / 重开 / 7 万字节超长行 / 结构化字段）、
> 轮转（保留份数 / 单文件不超阈值 / 旧份被覆盖）与失败路径；`tests/log_streams.qma`
> 单独钉住 stdout / stderr 不串流。

### 3.19 `std/ds`（RingBuf / MinHeap）单价（`bench/ds_bench.qma`，v2.05）

`std/ds` 从"0 个 `pub`、用户一引用就编译失败"补成公开模块（13 个 API），这是补完后
第一次量到的单价。**口径**：进程内 `now_ns()`；RingBuf 跑稳态（cap 4096 先填到 cap-1，
再循环 push+pop 配对，每轮都跨"尾部绕回 0"）；键由确定性 LCG 预先生成、不计时。
下表是**同一条命令跑 10 次的中位**（括号里是最小–最大，能看出噪声有多宽）：

| 负载 | 中位 | 区间 | 口径 |
|---|---|---|---|
| RingBuf push+pop 配对（跨绕回） | **32 ns/对** | 23–40 | 100 万对 |
| RingBuf `peek` | **1.5 ns/次** | 1–2 | 100 万次 |
| `vec[int]` push+pop 配对（同形状对照） | 12 ns/对 | 8–62 | 100 万对 |
| `std/deque` push_back+pop_front 配对 | 41 ns/对 | 28–102 | 100 万对 |
| MinHeap push（20 万，堆 1.6 MB） | **59 ns/次** | 36–75 | 20 万次 |
| MinHeap pop（20 万，堆 1.6 MB） | **462 ns/次** | 295–588 | 20 万次 |
| MinHeap push（1 万，堆 80 KB） | 52 ns/次 | 36–72 | 1 万次 |
| MinHeap pop（1 万，堆 80 KB） | **271 ns/次** | 188–297 | 1 万次 |
| `sort_int` 20 万（一次性排序对照） | 260 ns/元素 | 205–355 | 20 万元素 |
| `heap_pop` 挖洞前 → 后（**同进程交错 A/B**） | **700 → 458 ns/次** | 670–730 → 450–465 | 20 万，3 轮 |

> 只有最后一行是可当结论用的 A/B：其余各行是**跨进程**重复测量，别的轨道的编译负载
> 直接进数字（同一行能差 2 倍）；A/B 在同一进程里交替跑新旧实现，漂移对两边同等生效。
>
> **RingBuf 比 `vec` 慢约 2.7 倍**是取模 + 句柄头读的代价（每轮多 2 次 `mem_load64` 与
> 一次 `%`），换来的是"容量恒定、不扩容、不搬移"；`std/deque` 与它同量级但可扩容——
> 两者不是快慢关系，是"有界"与"可长"的选择。
>
> **MinHeap 的 pop 比 push 贵 8 倍不是实现问题，是树高**：随机 key 上浮平均 1.4 层就停，
> 下沉每一层都要走到底（20 万 = 17.6 层）。1 万（13.3 层）比 20 万快 1.7 倍，比树高比
> （1.32）多出来的部分就是每层跨一条缓存行的访存延迟——所以换 mem 块承载也救不了，
> 只有 4 叉堆（树高减半）或 B 树布局才动得了这块。
>
> **全量取空时堆比一次性排序慢约 1.8 倍**（462 ns × 20 万 ≈ 92 ms vs `sort_int` 52 ms）：
> 优先队列的价值在**增量插入 + 只取前 k 个**，不在"把 n 个全排一遍"。只要排序结果就用
> `sort_int`，要"边来边取最小"才用堆。

### 3.20 `std/timer` 轮询式定时器（`bench/timer_bench.qma`，v2.08）

重写前这个模块**根本编译不过**（四个顶层 `let` + 调不存在的 `now_ms()`），所以没有"改造前"
可比——这里只有重写后的绝对数字（同一条命令 8 次的中位）。10 万个定时器，到期时刻打散在
0–4 ms 十档；push 走"分配 + 存活位 + 挖洞上浮 + 扩容"，drain 走"弹堆 + 下沉"。

| 负载 | 中位 | 区间 | 口径 |
|---|---|---|---|
| `timer_after`（10 万个，含 3 次 2 倍扩容） | **130 ns/次** | 112–139 | 10 万次 |
| `timer_poll`（全部到期后弹空） | **454 ns/次** | 367–520 | 10 万次 |
| `timer_cancel` | **7 ns/次** | 2–12 | 2 万次 |
| `timer_pending`（O(n) 扫描存活位） | **168 µs** | 133–228 | 10 万项 |
| 全取消后 drain（每项都跳过） | **236 ns/项** | 196–297 | 2 万项 |

> `poll` 454 ns 与 `std/ds` 的 `heap_pop`（462 ns）几乎一样——两个模块的堆下沉是同一套
> 挖洞写法，瓶颈也同一处：**17.6 层 × 每层跨一条缓存行**。`after` 只要 130 ns 是因为
> 随机到期时刻上浮平均 1.4 层就停。
>
> `cancel` 7 ns 是"只清一个存活位"的代价（O(1) 不搬堆）；代价转移到了 drain：被取消的
> 项仍留在堆里，到期时弹出来再丢掉（236 ns/项）。这是刻意取舍——取消通常零散发生，
> 而"从堆里精确删除"要额外维护 id→位置的索引，复杂度换不来这个收益。
>
> `timer_pending` 168 µs 是 O(n) 扫描，**不是热路径**（诊断/测试用）；要 O(1) 就再维护
> 一个计数器，等真有调用方再说。

### 3.21 IPv6 / 双栈 socket（`bench/net6_bench.qma`，v2.07）

**这一节的主要结论是"v6 不比 v4 贵"**，不是绝对数字——本机环回被 WFP 过滤拖慢，
`connect` 的绝对值由平台主导，所以每行都配一条**同机同日的 CPython 基线**（同一份
"connect+close 200 次 / send+recv 2000 次"负载），看的是两条轨之间的比例。

口径：进程内 `now_ns()`；服务端在 `spawn` 出来的线程里，客户端在主线程，环回不经网卡；
`connect` 一栏 = `connect` + `close` 一整圈（含 `WSAStartup`、`getaddrinfo`、`socket`、
三次握手/四次挥手），服务端每圈 `accept` 一次；`pingpong` 一栏 = 已建连接上
`send`+`recv` 一个来回。Quelmara 取 3 次运行的中位，CPython 单次 200/2000 次取平均。

| 负载 | Quelmara v2.07 | 同机 CPython | 读法 |
|---|---|---|---|
| `connect`+`close`，`127.0.0.1` → v4 监听 | **948 µs/圈** | 1 146 µs/圈 | 平台成本主导；我们少一层解释开销 |
| `connect`+`close`，`::1` → `listen6` 双栈 | **939 µs/圈** | — | **与 v4 同价（−1%）**：`sockaddr_in6` 28B 与 `AF_INET6` 没有额外代价 |
| `connect`+`close`，`localhost` → `listen6` | **2.23 ms/圈** | `getaddrinfo("localhost")` 1 324 µs + 建连 1 146 µs | 多出来的就是**名字解析**（数字字面量 `getaddrinfo` 只要 7 µs） |
| `send`+`recv` 往返，v4 | **145 µs/来回** | 139 µs/来回 | 协议栈往返为主，语言侧开销在噪声内 |
| `send`+`recv` 往返，v6 | **134 µs/来回** | 138 µs/来回 | **v6 不慢于 v4**（3 次区间 123–138，与 v4 的 129–146 重叠） |

> **"localhost 回退到 v4"不进基准**：`localhost` 若先解析到 `::1` 而服务端只监听 v4，
> 第一次 `connect` 要**被拒**才回退。本沙箱里被拒连接固定 ~2.0 s（CPython 测同一目标
> 也是 2.03 s，是 WFP 丢 SYN 而不是 RST），200 圈就是 400 s，基准没法跑。正确性由
> `tests/t140_net6.qma` 的第 4 段断言（v4-only 监听 + `connect("localhost")` 必须连上）；
> 代价口径：**一次被拒连接**，正常机器上 <1 ms。
>
> 双栈 socket 上 IPv4 客户端在内核里是 `::ffff:127.0.0.1`：`std/net/addr` 的
> `addr_text` 把它还原成点分四段（t140 断言），日志里不会出现映射前缀。

### 3.21 HTTP 路由表 + 中间件（`bench/http_router_bench.qma` / `tests/http_router_test.py`，v2.10）

路由派发是本版新增的热路径，分两层量：**进程内**（查表 / 参数捕获，不受网络干扰）与
**端到端**（真实 socket，同一 Python 客户端跑三个服务做对照）。

**进程内**（`now_ns()`，每档 20 万次 × 3 轮取最小；路径字符串**预先生成、不计时**；
路径按 `i % n` 轮转，命中的是最后一条——最坏情况）：

| 负载 | 最小 | 口径 |
|---|---|---|
| 查表 1 条路由 | **109 ns** | 20 万次 |
| 查表 4 条 | 142 ns | 20 万次 |
| 查表 16 条 | 240 ns | 20 万次 |
| 查表 64 条 | **609 ns** | 20 万次 |
| `route_param_at`（取 1 个 `:参数`） | 172 ns | 20 万次 |
| `route_match`（str 版，`str_split` 两次） | 188 ns | 20 万次 |
| `route_match_bytes`（字节版，零分配） | 205 ns | 20 万次 |

**端到端**（同机同日，keep-alive 单连接 × 2000 请求，各 3 次取最小；服务端 `--quiet`，
否则一次控制台 `WriteFile` 就是几十微秒）：

| 服务 | µs/往返 | 说明 |
|---|---|---|
| `echo_reactor`（基线） | **147.1** | 只有 IOCP 回环 + `tcp_send`，没有 HTTP |
| `http_demo`（单回调，无路由/中间件） | 183.4 | HTTP 解析 + 响应组包 |
| `http_router`（7 路由 + 2 中间件 + 参数捕获） | **178.5** | 本版形态 |
| `http_router` 4 连接 × 1000 | 11.5k req/s（86.9 µs/往返） | 并发口径 |

> **结论一：路由 + 中间件在端到端里测不出成本。** `http_router` 反而比单回调的
> `http_demo` 快 5 µs——符号不可信，实际是"落在噪声内"（本机 VBS 噪声 ±50%）。与进程内
> 单价一致：16 条路由 240 ns，只占 180 µs 往返的 **0.13%**。
>
> **结论二：HTTP 层比裸 reactor 贵 ~36 µs**（147.1 → 183.4）。这部分是请求行/头解析
> （单遍字节扫描）+ 响应组包（多次字符串拼接）+ 一次 `WSASend`，本版没动它们——要动就
> 得先量出拼接占多少，别拿"路由优化"去解释这 36 µs。
>
> **结论三：字节版匹配不比 str 版快**（205 vs 188 ns）。它的价值是**不分配**：每请求省
> 掉 2 个 `vec[str]` + N 个段子串。单条 200 字节请求的往返是 180 µs，分配成本本来就看不见，
> 所以别把"零拷贝"当性能卖点——它是"没有 GC 压力、堆不随请求数增长"的保证。
>
> 口径提醒：测量期间另一条轨在跑编译，跨进程比较只能看量级；上表每行都是 3 次最小值，
> 且三个服务是**同一条命令、同一个客户端循环**跑出来的，横向可比。

### 3.22 `.qla` 目标文件 / 函数级增量（`tools/dev/qla_bench.py`，v2.11）

负载 `bench/qla_bench.qma`：import `json` / `regex` / `sha256` / `url` / `gzip` / `f64`
六个模块，展开后 **98 个函数 / 14695 条 IR**。量的是**编译期**（进程内
`perf_counter`，`min-of-5`，`QLM_NO_CACHE=1`）：

| 场景 | ms | 倍数 | 复用 |
|---|---|---|---|
| 冷编译到 `.qla`（全量降级 + 优化 + 序列化） | 2255–2395 | 1.00× | — |
| 无改动增量（全部函数复用） | **1025–1083** | **2.20–2.21×** | 69/69 函数、14695/14695 条 IR，**产物逐字节相同** |
| 改一个函数体（`work`，被 `main` 内联） | 1565–1685 | 1.44–1.42× | 67/69（`work` + `main` 重编） |
| 同上，只加一条语句 | 1487–1824 | 1.52–1.31× | 67/69 |
| `link` 单档案（98 函数） | 432–435 | — | 100% 复用（纯发射） |

档案 **555 KB**（14695 条 IR），同一份程序的 PE 151 KB——**IR 比机器码大约 3.7 倍**，
这是"分发二进制库"的真实成本口径。

**增量下限是解析，不是复用**：同一负载 `qlm.load_program()` 单独跑就是 **1059 ms**，
而无改动增量总共 1083 ms——复用逻辑本身只占约 25 ms（2%）。解析器一个文件读三遍
（宽松扫描 / 严格二次解析 / `_consts_of`），所以**下一步的收益在解析缓存，不在 IR 复用**。

改小函数为什么会连带重编：`work` 被内联进 `main`，`main` 的 IR 里就是 `work` 的函数体
副本，`work` 一变 `main` 必须重编（见 `05-toolchain.md` §1.8 的"内联传播"）。不被内联的
大函数（>28 条 IR 且多调用点）改体只重编它自己——`tests/qla_test.py [B]` 钉住这一条。

**往返一致**：`tests/*.qma` + `examples/` + `bench/` 里能独立编译的 **192 个源文件**，
「直编 PE」与「档案 → 链接」的产物**逐字节相同**（192/192，diff 0，另 5 个不可独立编译）。

> 口径提醒：本表是在**另一条轨同时在跑回归**时采的（本机 VBS + 并行编译负载），
> 绝对毫秒会偏高 20–50%；倍数（同一进程内前后对照）受影响小。测绝对值请独占机器。

### 3.23 服务端运行时：reactor 迁到 Quelmara + 多核标定（v2.12）

口径：本机 20 核；客户端与服务端同机（回环本身 ~30–40 µs）；min-of-3；
`tools/dev/net_bench.py`。测量时机器上还有别的编译负载，**绝对数只做纵向参考**。

**echo 往返（4 连接 × 300 请求，单客户端线程）**

| 实现 | req/s（3 次） | RTT p50 | p99 |
|---|---|---|---|
| 基线：stage-0 内建 reactor（v2.11） | 5,382 / 5,896 / 6,427 | 155 / 148 / 148 µs | 427 / 331 / 237 |
| Quelmara reactor（共享完成端口） | 5,580 / 6,454 / 5,576 | 154 / 146 / 154 µs | 362 / 236 / 377 |
| Quelmara reactor（per-reactor 端口，**已回退**） | 4,925 / 5,762 | 187 / 173 µs | 371 / 292 |

**32 连接 × 4 客户端线程（吞吐，2 次）**

| 实现 | req/s |
|---|---|
| 基线 4 worker | 19,014 / 19,762 |
| Quelmara 4 worker | 20,063 / 19,602 |
| 基线 20 worker | 20,001 / 19,826 |
| Quelmara 20 worker | 19,466 / 19,817 |

> 这一档**客户端先到顶**（4 条 Python 线程），测不出服务端上限——它只用来证明"没回归"。

**多核标定（`bench/net_cpu_bench.qma`：handler 里 40 万次循环；20 连接 × 5 客户端线程）**

| `[net] io_threads` | req/s | RTT p50 | 相对 1 worker |
|---|---|---|---|
| 1 | 2,203 | 1,904 µs | 1.0× |
| 4 | 9,517 | 473 µs | **4.3×** |
| 20 | 9,822 | 451 µs | 4.5×（客户端到顶） |

p50 从 1,904 → 473 µs 是 **4.0×**，与 worker 数同阶——多核确实在干活，不是"配了 20 个
线程其实一个在跑"。4 → 20 的收益被压测客户端吃掉，要更准的上限需要多进程压测（未做，
`07-gaps.md` §3 已登记）。

**结论**：reactor 换成 Quelmara 实现后与 stage-0 版本同档（差异落在噪声内）；
`per-reactor` 端口方案在低并发下 p50 明显更差（146 → 175 µs），按数据回退到共享端口。

### 3.24 引导层耗时分解 + 原生驱动器（v2.13）

口径：本机 20 核；每次都是**冷进程**；min of 3–5。

| 步骤 | 毫秒 |
|---|---|
| `C:\Windows\System32\hostname.exe`（系统自带，纯进程创建基线） | 380 |
| 裸 Quelmara `build/hello.exe` | 372 |
| `python -c pass` | 561 |
| `import qlm_native` | 1740 |
| `qlm_cli version` | 911 |
| `build examples/hello.qma`（冷） | 2136 |
| 同上（缓存命中） | 1071 |

**结论一：这台机器上"端到端比 C 快 5 倍"测不出来**——任何进程创建要 ~370 ms
（系统自带的 `hostname.exe` 同价），比 gcc 编一个小文件的 30–50 ms 还贵一个数量级。
能比的只有"编译器自己的活"，所以下表只报进程内耗时。

**原生驱动器**（`bootstrap/driver/qlm_drv.qma`；数字是驱动器自报的 `now_ns()` 差，
排除进程创建）：

| 源 | 输入数 | 判定耗时（5 次） |
|---|---|---|
| `examples/hello.qma` | 8 | 3.8 / 4.1 / 4.3 / 4.6 / 6.6 ms |
| `std/http.qma` | 14 | 12.8 ms |

即"输入未变"这条路径的**自身开销**从 1071 ms（Python 缓存命中，仍要启动解释器）
降到 4–13 ms；冷路径不变（委托 stage-0，2136 ms）。失效正确性实测：`exit(7)` 改成
`exit(8)` 后 `qlm run` 的退出码从 7 变 8，产物被重新生成。

### 3.25 stage-1 编译器 `qlmc`（v2.31：子集 S17）

口径：本机 20 逻辑核（VBS 开着，噪声见 §3.26，只做纵向比较）；`qlmc` 的耗时是
**它自己报的**（`now_ns()` 差，排除进程创建税），每个数字取 5 次的最小值。
噪声 ±30% 是常态，**只有跨版本同量级才可比**。

| 用例 | 源码 | 产物 | 编译（进程内，min of 5） |
|---|---|---|---|
| `examples/fib.qma` | 0.2 KB | 2560 B | 4.1–5.1 ms |
| `examples/loop_sum.qma` | 0.3 KB | 2560 B | 4.8 ms |
| `tests/selfhost/s4_agg.qma`（struct+数组+for） | 1.3 KB | 4096 B | **5.6 ms** |
| `tests/selfhost/s5_enum.qma`（enum+match） | 1.5 KB | 3584 B | **8.9 ms** |
| `tests/selfhost/s6_vec.qma`（vec） | 0.9 KB | 4096 B | **5.8–6.0 ms** |
| `tests/selfhost/s7_aggfn.qma`（聚合形参/返回） | 1.2 KB | 4096 B | **4.9 ms** |
| `tests/selfhost/s8_map.qma`（map + 4 实参） | 0.8 KB | 7168 B | **4.9 ms** |
| `tests/selfhost/s9_slice.qma`（切片） | 0.9 KB | 4096 B | **4.7 ms** |
| `tests/selfhost/s10_defer.qma`（defer） | 1.0 KB | 2560 B | **4.6 ms** |
| `tests/selfhost/s11_import.qma`（import，2 个文件） | 1.1 KB | 2560 B | **6.3 ms** |
| `tests/selfhost/s12_ffi.qma`（@ffi 三个 API） | 0.7 KB | 2560 B | **5.7 ms** |
| `tests/selfhost/s13_closure.qma`（闭包） | 1.1 KB | 3584 B | **5.1 ms** |
| `tests/selfhost/s14_vecgrow.qma`（扩容 + 别名） | 1.5 KB | 9216 B | **6.1–7.8 ms** |
| `tests/selfhost/s15_bitops.qma`（位运算/移位/进制） | 2.2 KB | 4096 B | **6.8 ms** |
| `tests/selfhost/s16_stackargs.qma`（5/6/7 形参走栈） | 1.9 KB | 5632 B | **5.8 ms** |
| `tests/selfhost/s17_constexpr.qma`（const 常量表达式） | 2.0 KB | 4608 B | **5.6 ms** |
| `tests/selfhost/s18_vecagg.qma`（vec[Struct] + else if） | 2.3 KB | 9728 B | **7.4 ms** |
| `tests/selfhost/s3_manyfns.qma`（200 函数） | 96 KB | 44 544 B | **17.0 ms** |
| └ 其中后端阶段 | — | — | **2.5–3.4 ms（-j1）/ 1.6–2.5 ms（-j4）** |

`build/qlmc.exe` 自身 **1368 KB**（v2.30 1342 KB，+1.9%：步长化 vec + 结构体字面量当值 + else if），
由 stage-0 编出来。

**`push` 的机器码代价**（v2.27 实测，用 `tools/dev/dumpasm.py` 数指令，不受噪声影响）：

| 版本 | push 常见路径 | 说明 |
|---|---|---|
| v2.26 | ~26 条 | `[len][cap][data...]` 单块，数据基址是 `h+16` 立即数 |
| v2.27 第一版 | ~40 条 | 为了跨扩容调用，把 len/cap/data 提前钉进帧槽（**回退掉了**） |
| v2.27 定稿 | ~34 条 | 冷路径自包含；多出的几条是"句柄→数据指针"多一次 load（新布局固有） |

编译耗时看不出差异（`fib` 4.3→4.1–5.1 ms、`s3_manyfns` 16.5–19.2→15.9–16.6 ms，
都在噪声内），所以**不宣称加速或回退**。

**词法热循环的代价**（v2.28，`s3_manyfns` 96 KB 输入，min of 5）：

| 版本 | 编译 | 说明 |
|---|---|---|
| v2.27 | 16.5–19.2 ms | 每字符一次 `substr(src,i,2)`（既有代价） |
| v2.28 第一版 | **54 ms（3.3×）** | 又多了一次 `substr(src,i,3)` 判 `>>>`（**回退掉了**） |
| v2.28 定稿 | **16.1 ms** | 标点全部改直接比字节，两处 `substr` 都没了 |

这条对词法成本最敏感，**改词法必须测它**。

**生成代码质量**（v2.16 引入寄存器分配时测的，v2.17 未变）

| 形状 | v2.15 产物 | v2.16+ 产物 | 净加速 |
|---|---|---|---|
| 5 个局部变量互累加 1 亿次（无除法） | 919.8 ms | **543.4 ms** | **3.2×** |
| `loop_sum`（`% 13` 主导）2 亿次 | 2671.7 ms | 2324.1 ms | 1.17× |

### 3.26 测量噪声到底从哪来（v2.17 实测）

每组 15 次，同一台机器、同一时刻：

| 测量对象 | min | 中位 | max | 波动 |
|---|---|---|---|---|
| `python -c pass` | 949.7 ms | 1125.5 ms | 1307.9 ms | **37.7%** |
| 裸 Quelmara exe（无 Python） | 373.7 ms | 442.9 ms | 492.9 ms | **31.9%** |
| qlmc 进程内计时（-j1，200 函数） | 14 170 µs | 16 697 µs | 33 712 µs | **137.9%** |
| qlmc 进程内计时（后端段 -j1） | 2415 µs | 2760 µs | 6699 µs | **177.4%** |

结论：**噪声与 Python 无关**。裸 exe 的进程创建本身就波动 32%；qlmc 的进程内计时
（不含进程创建、不含 Python）波动更大，说明是宿主（VBS/Hyper-V）在抽走 vCPU。
唯一可靠口径是 `min of N`。

**`cpu_ns()` 不可用于微秒级测量**：Windows PE 上实测两次读数差恒为 156 250 000 ns
（≈156 ms 粒度），1M 与 200M 次循环的读数差都落在同一档。

**编译期优化的一次失败尝试（已回退）**：把 `_name_id` 的 O(n²) 线性查表换成
FNV-1a 哈希，800 函数前端 32.7 ms → 34.4 ms（无收益）。瓶颈不在查表，在词法/语法的
分配与结构体拷贝。

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

**组件自举 2/9；代码行数 自举 2024 / stage-0 34413 = 5.6%**（`python tools/dev/selfhost_status.py`）。

> v2.12 按当前树**重算**了这行：旧值 26541 是 v1.9x 的，之后 stage-0 陆续加了
> `qlm_index`（LSP）/`qlm_dbg`/`qlm_uring`/`qlm_store`/`qlm_qla` 等模块，分母早就变了。
> 同一次改动删掉 400 行手写 IR（reactor 搬进 `std/net/reactor.qma`），净减 ~310 行。
> 这 9 个组件只统计**编译器**；服务端运行时（reactor）v2.12 起已 100% Quelmara，
> 但它不在这个分母里——库层一直不计入自举口径。

## 5. 平台

| 平台 | 状态 | 证据 | 边界 |
|---|---|---|---|
| Windows x86-64（PE32+） | ✅ 主平台 | 本文 §1 主回归 | 无 CRT，只导入 kernel32 / ws2_32 |
| Linux x86-64（ELF64） | ✅ 构建级 | CI `run_native_tests.sh` | 本机无 gcc/WSL，只能 CI 验证 |
| Linux io_uring | ✅ | CI `test_uring.sh` | 需 5.1+ 内核 |
| AArch64（ELF64） | 🟡 | `tests/a64_emu.py` 执行级（`tests/a64_iface_test.py` 7 用例） | 无 chan/map/spawn/SHA；**vtable 已接**（v1.97）；遇不支持形态编译期报错 |
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
| `std` 里 6 个模块 0 个 `pub` 导出、2 个模块解析失败 | 用户代码一引用就编译失败；`examples/{ws_demo,sse_demo}` 构建不过 | v2.01 审计、**v2.08 重测**（`std/ds` 补 13 个 `pub`、`std/timer` 重写后 5 个 `pub`，`http`/`net/core` 由同期另一条轨补齐）：剩 `core`/`gen`/`serialize`/`sse`/`time`/`ws` 共 69 个声明。清单与复现见 `07-gaps.md` §7.13 |
