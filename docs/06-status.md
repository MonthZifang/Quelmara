# 当前状态（实测）

> **本文是全部实测数字的唯一出处。** 其它文档引用数字时写"见 `06-status.md`"。
> 口径日期：2026-10-24。环境：Windows 10/11 x86-64，Xeon E5-2666 v3（Haswell 代，
> **无 SHA-NI、无 AVX2**），VBS/Hyper-V 开启（进程冷启动 ~426 ms，跑分噪声 ±50%）。
> 解释器：Python 3.13.14。

## 1. 回归与对拍

| 项 | 结果 | 命令 |
|---|---|---|
| PE 回归（主回归） | **PASS=297 FAIL=0 SKIP=1**（v2.76 口径：qlmc 差分 63 条、LSP 42 条；数字增长来自 v2.27–v2.75 期间各轨新增夹具，本轮只跑不改。v2.26 口径：qlmc 差分 35 → 37 条（新增 `s13_closure`），主回归总数不变；v2.25 口径：新增 `s12_ffi`；v2.24 口径：新增 `s11_import`；v2.23 口径：新增 `s10_defer`；v2.22 口径：新增 `s9_slice`；v2.21 口径：新增 `s8_map`；v2.20 口径：新增 `s7_aggfn`；v2.19 口径：新增 `s6_vec`；v2.18 口径：新增 `s5_enum`；v2.17 口径：新增 `s4_agg`；v2.16 口径：新增 `t143_parshard`（分片并行写 / 工作线程读共享 vec / 8 参 spawn）；v2.14 口径：新增 `[9b]` stage-1 编译器差分（`tests/qlmc_test.py`，7 条）；v2.13 口径：新增 `t141_vecindex`（vec 下标六形态）+ `test_exitcode()` 三条（`exit(运行期值)` 的退出码）；v2.12 口径：新增负向夹具 `net_serve_builtin`——reactor 搬进 std 后直接调内建 `net_serve` 必须给出迁移诊断；v2.11 那条 `.qla` 沙箱删除 FAIL 已随夹具改「就地覆盖」收口。以下为 v2.10 口径的历史记录：本版新增项 `[3j2]`：`t130_router_dispatch`（路由表 / 参数 / 404·405 / 表满）+ `http_router_test.py`（20 项真实 socket E2E）。**唯一 FAIL 是 `.qla` 目标文件用例撞沙箱的批量删除策略**（`[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]`：一次删 `build/_qlatest` 里 62 个文件，超过 50 个的阈值），与被测逻辑无关；`cache_test` 的 `build/` 争用失败本次未复现。v2.07 记录的那条 LSP FAIL 已收口（`tests/lsp_test.py` 的容错索引段改成 `std/sse` / `std/ws`（仍解析失败）负向 + `std/http` / `std/timer`（已修好）正向，内部断言 38 → 42）。SKIP 为 WSL 交叉验证，本机被沙箱拦。此前新增项：语言轨 `t97_atomic`/`t121_syncmpmc`/`t122_syncport`，工具链 `cov_test`（23 条断言）/`fuzz_test`（12 条断言）/`cache_test`（24 条断言，v1.100）/`kv_test`（10 条断言，v1.102）；语言轨 `[9] AArch64 接口 vtable`（7 用例）+ 两个跨文件接口负向夹具 + **模块系统 `modsame` 正例与 3 个多文件负例**（v1.101）） | `python tests/run_win_tests.py` |
| 词法器对拍 | **PASS=297 FAIL=0**（300 个源文件，v2.78 口径；SKIP 3 个含 `f"..."` 插值的文件——stage-1 词法器不认 `FSTR`，v1.61 插值未移植。**闭包不再进 SKIP 名单**：`fn(x: int) -> int { ... }` 用的全是既有记号，`t126_closure` 逐记号一致（v1.95）） | `python tests/lexdiff.py` |
| 声明级 AST 对拍 | **PASS=201 FAIL=0**（201 个源文件，v2.78 口径：v2.78 让 stage-1 parser 的签名行"struct/enum 全在前、fn 全在后"，与 oracle 顺序一致；v1.98 口径：150 个源文件；唯一 FAIL 是 `tests/t115_derive.qma`——并行轨的 enum 派生让声明顺序变了、自举 parser 还没跟上，**与并发改动无关**。跳过 17 个：`t52_iface` / `t54_iface_dyn` / `t56_generic` / `t81_generic_infer` / `t99_generic_struct` / `t101_bounds` / `t102_generic_impl` / `t103_generic_enum` / `t104_generic_enum_impl` / `t116_iface_multi` / `iface_rc` / `iface_rc_a64` / `t118_iface_own` / `t119_drop` / `t123_derive_enum` / `t124_macro` / `t125_refl_dyn`——自举 parser 未做 interface/impl/泛型单态化、类型约束、泛型 impl 与泛型 enum，v1.96 的 enum 派生 / token 宏 / 运行时下标反射也未移植；v1.97 把 `iface_rc_a64` 与 `t118_iface_own` 按同一口径记账，`t120_ffi` / `t115_derive` / `dpub_*` 两侧逐行一致） | `python tests/parsediff.py` |
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
| 解释器差分（v2.84） | **PASS=12 FAIL=0**（解释执行 vs 编译执行逐字节：算术 20 行 / 控制流 5 行 / 函数与递归 7 行 / vec+for 11 行 / struct 字段 15 行 / enum+match 12 行 / 闭包 8 行（这一条用 stage-0 当参照，qlmc 还不支持闭包）；边界五条：语法错非零退出并带行号、无 main、文件不存在、无参数） | `python tests/interp_test.py` |
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

### 3.25 stage-1 编译器 `qlmc`（v2.44：子集 S12，**自举不动点 + f64 完整 + map 扩容 + IR 优化层**）

口径：本机 20 逻辑核（VBS 开着，噪声见 §3.26，只做纵向比较）；`qlmc` 的耗时是
**它自己报的**（`now_ns()` 差，排除进程创建税），每个数字取 5 次的最小值。
噪声 ±30% 是常态，**只有跨版本同量级才可比**。

| 用例 | 源码 | 产物 | 编译（进程内，min of 5） |
|---|---|---|---|
| `examples/fib.qma` | 0.2 KB | 4096 B | 4.9 ms |
| `examples/loop_sum.qma` | 0.3 KB | 4096 B | 7.6 ms |
| `tests/selfhost/s4_agg.qma`（struct+数组+for） | 1.7 KB | 6144 B | **6.7 ms** |
| `tests/selfhost/s5_enum.qma`（enum+match） | 1.8 KB | 5632 B | **7.3 ms** |
| `tests/selfhost/s6_vec.qma`（vec） | 0.8 KB | 8192 B | **7.1 ms** |
| `tests/selfhost/s7_aggfn.qma`（聚合形参/返回） | 1.2 KB | 6144 B | **7.2 ms** |
| `tests/selfhost/s8_map.qma`（map + 4 实参） | 0.8 KB | 11776 B | **8.5 ms** |
| `tests/selfhost/s9_slice.qma`（切片） | 0.9 KB | 6144 B | **7.4 ms** |
| `tests/selfhost/s10_defer.qma`（defer） | 1.0 KB | 4608 B | **7.3 ms** |
| `tests/selfhost/s11_import.qma`（import，2 个文件） | 0.5 KB | 4608 B | **8.3 ms** |
| `tests/selfhost/s12_ffi.qma`（@ffi 三个 API） | 0.8 KB | 4608 B | **6.2 ms** |
| `tests/selfhost/s13_closure.qma`（闭包） | 1.0 KB | 5632 B | **6.4 ms** |
| `tests/selfhost/s14_vecgrow.qma`（扩容 + 别名） | 1.4 KB | 10752 B | **8.0 ms** |
| `tests/selfhost/s15_bitops.qma`（位运算/移位/进制） | 2.7 KB | 5120 B | **6.4 ms** |
| `tests/selfhost/s16_stackargs.qma`（5/6/7 形参走栈） | 2.4 KB | 7168 B | **7.7 ms** |
| `tests/selfhost/s17_constexpr.qma`（const 常量表达式） | 1.7 KB | 6144 B | **7.0 ms** |
| `tests/selfhost/s18_vecagg.qma`（vec[Struct] + else if） | 1.9 KB | 11264 B | **9.1 ms** |
| `tests/selfhost/s19_spawn.qma`（spawn/join，0/1/2/5/8 实参） | 1.7 KB | 8192 B | **7.6 ms** |
| `tests/selfhost/s20_mem.qma`（内存/串/诊断内建） | 3.4 KB | 7680 B | **8.3 ms** |
| `tests/selfhost/s21_f64.qma`（f64 数值） | 1.9 KB | 7168 B | **7.4 ms** |
| `tests/selfhost/s22_f64print.qma`（f64 打印） | 1.1 KB | 11264 B | **7.5 ms** |
| `tests/selfhost/s23_map_grow.qma`（map 自动扩容） | 3.6 KB | 24576 B | **10.8 ms** |
| **`bootstrap/qlmc/qlmc.qma`（自己编自己 → stage-2）** | 305 KB | **459 776 B** | **320 ms**（`-j1`） |
| **stage-2 编自己 → stage-3（不动点）** | 305 KB | **459 776 B**（与 stage-2 逐字节相同） | **`-j1` 同量级** |
| `tests/selfhost/s3_manyfns.qma`（200 函数，`-j1`） | 46 KB | 39 424 B | **31.2 ms** |
| └ 其中后端阶段 | — | — | **~3 ms（-j1）** |

`build/qlmc.exe` 自身 **2105 KB**（v2.43 2030 KB；增量来自优化层自己的代码 ——
`qlmc.qma` 从 303 319 涨到 311 533 字节），由 stage-0 编出来。

**自举状态（v2.44）**：**不动点仍成立**。`qlmc` 编自己 → stage-2（459 776 字节），
stage-2 再编自己 → stage-3，**两者逐字节相同**（`-j1`）。stage-2 编
`tests/selfhost/` 全部 25 组独立程序与 stage-1 逐字节相同。
`python tests/bootstrap_test.py --strict` **五级全 PASS**。
注意源码从 v2.38 的 231 KB 涨到 305 KB，**编译耗时不能跨版本直接比**；
横向对比一律走 git worktree 基线（v2.44 的口径见 `versions/v2.44/CHANGELOG.md`）。

**`-jN` 编自己也通了（v2.43 复测）**：`-j 1 / 2 / 4 / 8` 四种取值编 qlmc 自己都是
rc=0、产物字节数相同且 md5 相同。v2.35 记的"多线程编自己段错误"（§7.24）已不复现，
真凶应该是堆上限（32 → 64 MB）与 `ARENA_CAP`（16 → 4 MB）—— 多线程下每线程一份
arena 才是吃满堆的地方。注意 `-j` 与数字**必须用空格分开**，`-j4` 会被忽略。

**优化层（v2.44）**：降级之后、分配之前跑三条 pass —— 常量折叠 / 常量进变量 /
死临时值删除 / 空跳删除。**产物 `.text` 真实字节 −10.9%、指令 −5.1%，编译耗时
+1.7% ~ +3.2%，运行期中性**（git worktree 基线双向对照，28 个夹具，逐用例无负优化）。
同一版把 4 KB 固定帧改成按需（16~232 字节），修掉了编译期 37 项表达式、运行期
400 层递归两个栈溢出（§7.29）。

**v2.45**：修掉 `join()` 缺 Win64 影子空间导致"改掉调用方 rbx 里的变量"（§7.30）；
新增 `bench/speed/`（Quelmara / C / Go / Python 四语言同题基准 10 项，40 个组合
校验和一致，数字见 `bench/speed/RESULTS.md`）。基准结论：访存为主的项与 C 打平
（手写哈希 1.06×）、算术密集项差 18×（缺强度削减）、f64 差 32×（不进 XMM）、
并发 4 线程 3.65×、编译器本身比 stage-0 快 6.6–41× 且省内存 2.4–7×。

**v2.46**：优化底层代码 —— 立即数二元运算、强度削减、**地址计算与访存融合**
（`vec.get(i)` 从 13 条指令降到 4 条）、越界检查改单分支。代码体积 **−1.6%**；
速度上 `b7_sort` **−14%**、`b6_hash` 与 C 持平，其余在噪声内（`b1_int` 是 `idiv`
延迟瓶颈、`b4_array` 是内存带宽瓶颈 —— 见 §7.31）。

**v2.47**：f64 大修 —— 二元运算 / int 转换全部内联（`OP_FBIN`/`OP_ITOF`/`OP_FTOI`），
并且 **f64 字面量在一个函数里只解析一次**（以前每次求值都跑 `strtod`，字面量在循环体
里就是每轮一次）。`b2_float` **760.6 → 66.3 ms（11.5 倍）**，qlmc/C 从 34.3× 降到
**2.9×**；并发加速比 3.51× → **3.72×**。40 个校验和全部不变。

**v2.48**：常数除法改魔数乘法（`OP_DIVC`）—— 无符号魔数 + 显式符号分离，
**可证明正确**（不是推导），8.4M 采样点零失败。`b1_int` **203.3 → 42.1 ms（4.8 倍）**、
`b8_threads1` **406.8 → 92.5 ms（4.4 倍）**，qlmc/C 从 18.3× 降到 **3.8× / 4.2×**。
除数限制 `2..2^31-1`，超范围保持 `idiv`。

**v2.49**：`&&`/`||` 短路直接发跳转（以前条件落到 `_lower_expr`，每个比较多 6 条
"规范化"指令；`jws` 的白空格判断从 93 条降到 37 条）+ `s[p]` 的地址计算与字节
访存融合。`b9_json` **46.8 → 30.3 ms（1.54 倍）**、qlmc/C 6.6× → **4.3×**；
代码体积合计 **−8.9%**，stage-2 **395 776 字节**（−14%）。

**v2.50**：变量寄存器从"按创建顺序"改成**按使用次数**分配（`_alloc_vars`，只动标量、
且跳过被 `OP_ADDRV` 烧过槽号的）。以前 7 个变量的函数里最热的累加器/循环变量反而
溢出到帧槽，热循环每轮两次 store→load 串行依赖。`b7_sort` **29.9 → 24.3 ms（−19%）**、
`b9_json` 30.3 → 28.1 ms。

**v2.51**：变量寄存器池从 5 个扩到 **7 个**（`RBX`+`R12-R15`+`RSI`+`RDI`，全是
Win64 的 callee-saved）。前提是把所有运行库例程审计干净（`__memcpy`/`__memset`
换 `r8`/`r9`，`__str_cat` 自己 push/pop），并新增踩踏回归夹具 `s24_varreg`。
stage-2 **395 776 → 390 656 字节**，并发加速比 **3.30× → 3.85×**，`b6_hash`
39.5 ms（快于 C 的 40.4）。

**v2.52**：常数除法的符号位从"算两次"改成"存 R11 一次"（`%` 18→15 条、`/` 15→12 条），
`b1_int` **41.9 → 39.1 ms**。第一版 REX 写成 `0x4D`（应为 `0x49`）导致负数除法
走成无符号除 —— 被新增的 `s25_divmod`（156 组负数差分）抓到。

**v2.53**：越界检查的"取长度 + 比较"融合成一条 `cmp r64, [base±8]`
（`OP_JCMPVLEN`/`OP_JCMPSTR`）。`b7_sort` **−5%**、`b1_int` −3%、`b8_threads1` −5%，
`b6_hash` 42.9 ms（快于 C 的 45.9）。

**v2.54**：**基准搬到 GitHub Actions**（`.github/workflows/bench.yml`）——
本机 VBS 噪声已经大到单次测量没有意义（进程创建 447 ms、`b1_int` 单次 59.3 /
min-of-5 42.4、4 线程加速比三轮 3.06/3.22/3.85）。CI 上 windows 跑四语言全量 +
编译器轴，ubuntu/macos 跑 C/Go/Python 参照值（qlmc 只有 PE 后端）。为此把 C 侧
计时抽成 `c/bench.h`（QPC / `CLOCK_MONOTONIC`）、`b8_threads4.c` 加 pthread 路径、
`run.py` 加平台判定。**对外引用的数字一律用 CI 的。**

**v2.55**：**f64 从"聚合"改成 8 字节标量，值住 XMM 寄存器**（XMM6-XMM15 给变量、
XMM0-XMM3 给临时值、XMM4/XMM5 当专用临时）。以前 f64 是帧槽 + 地址传递，
`acc = acc + 1.0/to_float(i)` 编成 **52 条指令**（含一次 `call __memcpy`），C 只要 6 条。
现在主循环 **12 条**、`acc` 住 XMM6。另外**编译期算出 f64 字面量的 IEEE 位模式**
（`OP_F64IMM`，精确可表示时），字面量不再需要"槽 + 已解析标志 + 每轮守卫"。
`b2_float` 本机 **65.6 → 33.2 ms（1.98 倍）**，qlmc/C **3.0× → 1.50×**。
顺带挖出并修掉一个从 v2.16 就存在的通用 bug：**`dst` 与右操作数同寄存器时
二元运算算错**（`x = 0 - x` 恒得 0、`x = 3 * x` 得 a·a），新增夹具 `s26_alias`。

**v2.56**：**打破 SSE 部分寄存器写造成的跨迭代假依赖**。`movsd xmm, xmm` 只写低
64 位、对目标旧值有依赖 —— `movsd xmm0,xmm2; divsd xmm0,xmm1` 让每轮除法都要等
上一轮除法写完，**除法被完全串行化**（15 周期/轮，C 只要 4）。寄存器到寄存器的
f64 搬运一律改用 `movaps`（整 128 位写）。另外把编译期 f64 字面量放进**帧常量槽**，
序言写一次、循环体里 `divsd xmm0,[rbp+slot]` 零额外指令。`b2_float` 主循环
**10 → 8 条**，本机 **25.4 → 22.1 ms**，**已快于 C（24.5 ms）**。
CI 权威数字（run 40274533499，windows EPYC 9V74，min of 5）：`b2_float`
**6.3 ms vs C 6.5 ms = 0.97×**（v2.54 是 8.5×、v2.55 是 4.0×）；`b5_string`
**0.92×**、`b6_hash` 1.03×、`b8_threads4` 1.20×、`b7_sort` 1.58× ——
**qlmc 已有两项快于 C**。

**v2.57**：三处通用的代码质量改进 —— ① **`OP_JCMPI`**（条件跳转的立即数形式，
`cmp r64, imm32` 一条顶"装载常量 + 比较"两条；`b9_json` 里 `mov imm`+`cmp` 的
组合从 11 处降到 0 处）；② **`_opt_copy`**（相邻拷贝传播，消掉降级期产生的
`mov` 链）；③ **循环里跨调用的临时值改用空着的 callee-saved 寄存器**（溢出是
每轮两条内存往返，占用寄存器只是每函数一次 push/pop；循环外不做，实测那样会让
`fib` 慢 4.7%）。`b9_json` 本机 **29.76 → 26.64 ms（−10.5%）**、
`b6_hash` **42.48 → 39.58 ms（−6.8%）**。

CI 权威数字（run 40280376387，windows EPYC 9V45，min of 5）：**10 项里 5 项在
1.5× 以内**，`b2_float` **4.7 ms 与 C 完全持平**（1.00×）；`b5_string` 1.10×、
`b6_hash` 1.14×、`b7_sort` 1.33×、`b8_threads4` 1.45×、`b3` 2.00×、
`b4` 2.85×、`b9_json` 3.82×、`b1_int`/`b8` 4.28×。
`b1_int`/`b8` 的 C 版本是 **AVX2 向量化**的（48 条指令/16 元素），qlmc 标量
追不上是必然的 —— 要追得写自动向量化器。

**v2.58**：基准矩阵补平台 —— `run.py` 加 `quelmara0` 列（用 **stage-0** 编，
win=PE / posix=ELF64），于是 **Linux 上第一次有了 quelmara 的数字**（run
40281824686，4 语言校验和全一致）：`b5_string` **0.83×**、`b6_hash` **0.92×**
（快于 C）、`b8_threads1` 1.08×、`b1_int` 1.27×、`b8_threads4` 1.71×、
`b7_sort` 2.1×、`b4` 2.9×、`b3` 3.6×、`b9_json` 6.0×、`b2_float` 7.3×
（后者的差距说明 stage-0 还没有 v2.55/2.56 那套 f64 优化 —— 后端差距一目了然）。
**macOS 仍然没有 quelmara 数字**：`--target native` 在 Darwin 上产的是 ELF64，
执行报 `Exec format error`；需要 Mach-O 后端（§4 平台表）。顺带修掉两个静默
失效的门禁：`--markdown` 分支跳过校验和检查、`| tee` 吞掉退出码。

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

**stage-0 的"性能层面布局敏感"**（v2.32 实测，`-j1`，min of 3）：

| 版本 | `s3_manyfns` 编译 | 说明 |
|---|---|---|
| v2.31 | 17.8–18.5 ms | 基线 |
| v2.32 第一版 | **32–34 ms（1.8×）** | `_lower_spawn` 里两处 `eprint("…" + expr)` |
| v2.32 定稿 | **17.3–18.7 ms** | 把那两处字符串拼接删掉（错误消息不再带细节） |

那段代码**从不执行**（s3_manyfns 里没有 spawn），纯属 stage-0 生成代码时的敏感性；
而且不单调——同一函数体只留前 3 行（含拼接）慢、多留 10 行反而快。所以
**改完 `qlmc.qma` 必须量这一条**，否则 2× 的回退会静默溜过去。

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

### 3.27 LICM 默认开启的 A/B（v2.59，`bench/speed/run.py`，本机 min of 3）

同一台机器、同一份源码，唯一变量是 `QLM_DISABLE_LICM=1`。校验和 10/10 一致。

| 基准 | LICM 关 | LICM 开 | 变化 |
|---|---|---|---|
| b1_int | 41.9 | 38.0 | **−9.3%** |
| b6_hash | 45.2 | 42.5 | **−6.0%** |
| b8_threads1 | 340.3 | 318.6 | **−6.4%** |
| b8_threads4 | 109.6 | 104.1 | **−5.0%** |
| b9_json | 30.9 | 27.4 | **−11.3%** |
| b5_string | 81.4 | 86.0 | 首轮 +5.7% 是噪声；reps 5 两轮复测 86.3/84.9 vs 82.8/78.5，实为更快 |
| b2_float / b3 / b4 / b7 | — | — | 差异 ≤1% |

**这条数只用于方向判断**：本机单次抖动 ±40%（见 §3.26），`b5_string` 首轮
的 5% 假信号就是例证。权威数字等 CI `bench.yml`。

### 3.28 代码体积：失败路径不内联（v2.60）

`__bounds_fail` / `__vec_fail` 不再被内联到每个下标访问点。同一份源码的
PE 文件大小：

| 基准 | 内联 | 不内联 | 变化 |
|---|---|---|---|
| b9_json | 22016 | 18432 | −16.3% |
| b7_sort | 15872 | 13312 | −16.1% |
| b4_array | 12288 | 11264 | −8.3% |

运行时间**测不出变化**（十个基准全部在噪声内，校验和 10/10 一致）——
失败路径正常一次都不走，省的是 I-cache 与文件大小。
同轮的"越界检查收成一条无符号比较"（每次下标少 2 条指令）同样测不出时间
差异，原因见 `07-gaps.md` §5：这些基准的瓶颈是带宽 / SIMD / 调用延迟链，
不是指令数。

### 3.29 stage-0 的真实基准（v2.61，`--langs quelmara0`）

**先记一条纪律**：`bench/speed/run.py` 的 `quelmara` 列跑的是
`build/qlmc.exe`（**stage-1 自举编译器**的产物），`quelmara0` 才是
**stage-0（本仓 `tools/stage0/`）** 的产物。改 stage-0 的优化器却看
`quelmara` 列，测的是 qlmc —— v2.61 之前有 8 次"测不出收益"的尝试，
根因全在这里。

本机 min of 7（同一台机器、同一份源码）：

| 基准 | quelmara0 | c | 倍数 | 备注 |
|---|---|---|---|---|
| b1_int | 25.9 | 11.0 | 2.4× | C 走 AVX2 |
| b2_float | 48.5 | 22.4 | 2.2× | f64 住帧槽 |
| b3_recursion | 6.2 | 3.0 | 2.1× | 调用延迟链 |
| b4_array | 18.4 | 7.4 | 2.5× | 内存带宽 |
| b5_string | 83.8 | 57.9 | 1.4× | `idiv` 占大头 |
| b6_hash | 41.0 | 41.6 | **1.0×** | 已持平 |
| b7_sort | 41.8 | 15.1 | 2.8× | 内存 + 分支 |
| b8_threads1 | 247.9 | 89.2 | 2.8× | 同 b1 |
| b8_threads4 | 67.2 | 44.5 | 1.5× | 并行效率 3.7× |
| b9_json | 39.8 | 6.9 | **5.8×** | 每 token 一次调用 + 越界检查 |

对照：同一台机器上 **qlmc** 的 b1 是 38 ms、b9 是 27 ms —— stage-0 的
b1 更快、b9 更慢，两条编译器的强弱项不同，**混在一列里比会得出反向结论**。

### 3.30 CI 权威数字（v2.63 提交，windows-latest，min of 5）

来源：`bench.yml` run 40352126511（push `ea8f204`，三 job 全绿）。**这是
唯一可以引用的基准表**，上面 3.29 的本机数字只用于粗判方向。

| 基准 | quelmara（qlmc） | quelmara0（stage-0） | c | go | stage-0 / C |
|---|---|---|---|---|---|
| b1_int | 28.4 | 18.8 | 6.4 | 18.9 | 2.9× |
| b2_float | **7.0** | 15.6 | 7.0 | 6.8 | 2.2× |
| b3_recursion | 8.1 | 6.3 | 2.4 | 4.0 | 2.6× |
| b4_array | 11.8 | 15.2 | 4.0 | 3.1 | 3.8× |
| b5_string | 30.9 | 34.1 | 39.9 | 20.9 | **0.85×** |
| b6_hash | 12.4 | 11.4 | 11.7 | 11.0 | **0.97×** |
| b7_sort | 21.4 | 30.6 | 13.2 | 12.9 | 2.3× |
| b8_threads1 | 226.6 | 150.0 | 51.0 | 151.2 | 2.9× |
| b8_threads4 | 115.6 | 112.4 | 69.0 | 87.4 | 1.6× |
| b9_json | 21.2 | 26.5 | 5.0 | 5.8 | 5.3× |

三条要注意的：

1. **stage-0 在 b1 / b3 / b8 上比 qlmc 快**（b8_threads1 快 34%），而 qlmc 在
   b2（7.0 vs 15.6）、b4、b5、b7、b9 上更快。两条编译器的强弱项是**互补**的，
   不存在"哪条全面更好"。
2. **stage-0 的 b5_string 已经快于 C 15%**，b6_hash 快 3%。这两项是
   "语言本身没有额外开销"的证据。
3. `go` 在 b8_threads1 是 151.2、stage-0 是 150.0 —— 单线程整数运算上
   Quelmara 和 Go 打平；b1_int 上 stage-0（18.8）也略快于 Go（18.9）。

v2.64 的 itoa 魔数化**不在这张表里**（本机 b5 −56%，见
`versions/v2.64/CHANGELOG.md`），要等下一次 CI 才能拿到权威数字。

### 3.31 CI 数字（v2.64 提交，windows-latest，min of 5）

来源：run `40359540744`（workflow_dispatch）与 `40357506818`（push），**两次
数字一致到 0.5%**，可以当一次采样看。

| 基准 | quelmara（qlmc） | quelmara0（stage-0） | c | go | stage-0 / C |
|---|---|---|---|---|---|
| b1_int | 18.3 | 14.2 | 4.3 | 12.8 | 3.3× |
| b2_float | 4.8 | 44.0 | 4.7 | 4.6 | **9.4×** |
| b3_recursion | 3.6 | 3.2 | 1.7 | 3.1 | 1.9× |
| b4_array | 8.0 | 9.6 | 2.9 | 3.5 | 3.3× |
| b5_string | 23.4 | 16.2 | 21.2 | 11.8 | **0.76×** |
| b6_hash | 9.7 | 8.6 | 9.8 | 8.8 | **0.88×** |
| b7_sort | 15.1 | 21.5 | 11.3 | 11.5 | 1.9× |
| b8_threads1 | 148.8 | 115.4 | 35.0 | 105.4 | 3.3× |
| b8_threads4 | 74.2 | 59.8 | 50.9 | 58.0 | 1.18× |
| b9_json | 10.7 | 13.4 | 2.8 | 3.0 | 4.8× |

**⚠ 跨 run 的绝对值不能直接比。** 这两次跑（v2.64）的机器比 v2.63 那次快
约 1.5×（C 的 b1 从 6.4 → 4.3、Go 从 18.9 → 12.8、Python 从 2833 → 1586），
所以**只能比同一次 run 内的比值**。b5 的比值：

| 口径 | v2.63 | v2.64 |
|---|---|---|
| stage-0 / C | 0.855 | **0.764** |
| stage-0 / qlmc | 1.10（慢 10%） | **0.69（快 31%）** |

两个口径方向一致（stage-0 的 b5 变快了），但幅度不同 —— C 的 `snprintf`
在新机器上受益更多。**量级以本机受控对照为准**（同一台机、交替、min of 5、
三轮）：83.8 → 37.1 ms，−56%。

**b2_float 有一个未解释的跨 run 差异**：v2.63 那次 windows 报 stage-0 = 15.6
（2.2×），v2.64 的两次都报 44.0（9.4×）。但本机把 `qlm_native.py` 换回 v2.63
版本做三轮交替 A/B，b2 是 48–54 ms vs 48–51 ms（**没有差异**），且本机绝对值
（~50 ms）与 v2.64 的 CI 数字吻合。所以 v2.64 **没有引入 b2 回归**，
v2.63 那次的 15.6 更像 runner 异常（同一台机器上 C/Go/Python 都更慢，
只有 stage-0 的 b2 快 3 倍）。b2 需要一次专门的复测，暂按 9.4× 记。

### 3.32 f64 住进 XMM（v2.65）：b2_float 反超 C

**改动**：f64 值以前住在 GPR 里，每条浮点指令 `movq` 进出 XMM（热循环 23 条
指令里有 8 条是这个往返），而且 SSE2 的 `cvtsi2sd` 对目的寄存器有**假依赖**，
把 5M 次除法全串行化。现在 f64 有独立的 XMM 寄存器文件
（caller-saved xmm0-3 / 非易失 xmm6-15 / 临时 xmm4-5），热循环 23 → 15 条。

**本机 min of 7**（同一张表内横向比较）：

| 基准 | 改前 | 改后 | c | 对 C |
|---|---|---|---|---|
| b2_float | 48.5 | **21.2** | 24.5 | **0.87×** |
| b5_string | 83.8 | 39.0 | 56.8 | **0.69×** |
| b6_hash | 41.0 | 38.3 | 38.0 | 1.01× |

**三项不慢于 C**（b2/b5/b6）。b2 在 CI v2.64 上是 9.4×，这是单点最大的一笔。

两个坑（都写进 `versions/v2.65/CHANGELOG.md`）：

1. `fx` 少一条 `movaps` → **静默算成 0**（不是崩溃）。夹具
   `t148_f64_xmm` 用"循环累加 vs 直线展开两条路径对拍"抓这类搬错。
2. `@simd` 的 `vsumd`/`vdotd` 把 xmm0/xmm1 写死当临时 → 与 XMM 池冲突。
   **含 SIMD 归约的函数整体放弃 XMM 分配**。

**整数路径逐字节未变**：b1_int 的产物 sha256 与改动前完全相同。

### 3.33 越界检查：两条比较 → 一条无符号比较（v2.66）

`emit_bounds` 与四个 `__vec_*` 内联体都从"先查 `idx >= 0`、再查
`idx >= n`"收成一次无符号比较 `idx <u n`：负下标的无符号解释是巨大值，
天然落进失败路径。

| 基准 | 改前 | 改后 |
|---|---|---|
| b4_array | 20.2 / 20.1 | 19.3 / 18.1 |
| b7_sort | 45.5 / 45.5 | 43.1 / 39.3 |
| b9_json | 36.8 / 42.1 | 34.9 / 38.6 |

（本机 min of 5，两轮交替 A/B。）每次下标访问省 2 条指令 + 1 个分支。

**注意**：v2.60 的 CHANGELOG 曾声称做过这个改动，实际没有进提交 ——
做 A/B 的脚本最后一轮把源码留在了 `off` 状态。本轮重新实现并量过。

### 3.34 CI 数字（v2.66 提交，windows-latest，min of 5）

来源：run `40370465800`（三 job 全绿）。与 v2.64 那次（§3.31）机器性能相当
（C 的 b1 4.3→4.6、Python 1586→1650），可以横向比。

| 基准 | quelmara（qlmc） | quelmara0（stage-0） | c | go | 对 C | 对 Go |
|---|---|---|---|---|---|---|
| b1_int | 19.3 | 14.9 | 4.6 | 13.4 | 3.24× | 1.11× |
| b2_float | 4.9 | **5.0** | 5.0 | 4.7 | **1.00×** | 1.06× |
| b3_recursion | 3.6 | 3.3 | 1.8 | 3.0 | 1.83× | 1.10× |
| b4_array | 8.5 | 9.7 | 3.3 | 3.4 | 2.94× | 2.85× |
| b5_string | 23.8 | **16.7** | 21.4 | 12.2 | **0.78×** | 1.37× |
| b6_hash | 10.4 | **8.3** | 8.4 | 9.8 | **0.99×** | **0.85×** |
| b7_sort | 16.0 | 23.1 | 11.7 | 11.8 | 1.97× | 1.96× |
| b8_threads1 | 150.2 | 116.6 | 35.1 | 105.4 | 3.32× | 1.11× |
| b8_threads4 | 73.6 | 60.4 | 51.0 | 58.3 | 1.18× | 1.04× |
| b9_json | 10.9 | 13.1 | 2.8 | 3.1 | 4.68× | 4.23× |

**两轮改动（v2.65 f64 住 XMM + v2.66 越界检查合并）的效果**：

- `b2_float` **44.0 → 5.0 ms（8.8×）**，对 C 从 **9.4× 变成 1.00×**（持平），
  对 Go 从 9.6× 变成 1.06×。这是单点最大的一笔。
- `b5_string` 16.2 → 16.7（同机器基准下持平；v2.64 的 itoa 收益已在表里）。
- 其余基准在噪声内（b7 21.5→23.1、b9 13.4→13.1、b4 9.6→9.7）。

**现状**：三项不慢于 C（b5 0.78×、b6 0.99×、b2 1.00×），一项快于 Go
（b6 0.85×），另外四项对 Go 在 1.04–1.11× 之间（b3/b8s4/b1/b8s1）。
还差的：**b9_json 4.68×、b4_array 2.94×、b1_int/b8_threads1 3.2–3.3×**
（后两个是 C 的 AVX2 向量化，见 §5）。

### 3.35 就地更新折叠 + push 容量检查内联（v2.67）

- **`opt_store_back`**：`t = a OP b; a = t` → `a = a OP b`。b1_int 热循环
  15 → 11 条。只在 `t` 是纯临时值（全函数出现两次）时合并，安全性靠
  "覆盖 a 的旧值发生在 a 被读完之后"。**与 v2.61 失败的分配器级拷贝合并
  不同：这次改 IR，不改寄存器分配。**
- **`__vec_push` / `__vec_push_n` 容量检查内联**：以前每次 push 都
  `call __vec_grow`（容量够时它只做 `load data; ret`），b4_array 的 200 万次
  push 就是 200 万次白白的 call/ret。A/B：25.9/23.2 → 19.0/21.0 ms。

本机全基准（min of 7）：b4 20.3 → **17.9**、b8_threads1 274.9 → **221.9**、
b2 23.2 / C 23.3 = **1.00×**、b5 49.2 / C 71.8 = **0.69×**。

### 3.36 CI 数字（v2.67 提交，windows-latest，min of 5）

来源：run `40377624274`。**这台 runner 比 §3.34 那次慢约 1.7×**
（C 的 b1 4.6 → 7.8、Python 1650 → 2316），所以绝对值不能跨 run 比，
只能比**同一次 run 内的比值**。

| 基准 | quelmara0 | c | go | 对 C | 对 Go |
|---|---|---|---|---|---|
| b1_int | 14.0 | 7.8 | 17.1 | 1.79× | **0.82×** |
| b2_float | 6.3 | 6.4 | 5.9 | **0.98×** | 1.07× |
| b3_recursion | 4.7 | 2.1 | 3.8 | 2.24× | 1.24× |
| b4_array | 11.3 | 7.3 | 7.3 | 1.55× | 1.55× |
| b5_string | 20.1 | 33.1 | 19.0 | **0.61×** | 1.06× |
| b6_hash | 13.2 | 15.2 | 13.7 | **0.87×** | **0.96×** |
| b7_sort | 29.7 | 14.8 | 15.8 | 2.01× | 1.88× |
| b8_threads1 | 105.0 | 60.9 | 136.0 | 1.72× | **0.77×** |
| b8_threads4 | 76.2 | 67.3 | 68.2 | 1.13× | 1.12× |
| b9_json | 29.2 | 5.4 | 6.4 | 5.4× | 4.6× |

与 §3.34（v2.66）的**比值**对比：

| 基准 | 对 C：v2.66 → v2.67 | 对 Go：v2.66 → v2.67 |
|---|---|---|
| b1_int | 3.24 → **1.79** | 1.11 → **0.82** |
| b4_array | 2.94 → **1.55** | 2.85 → **1.55** |
| b8_threads1 | 3.32 → **1.72** | 1.11 → **0.77** |
| b5_string | 0.78 → **0.61** | 1.37 → **1.06** |
| b6_hash | 0.99 → **0.87** | 0.85 → **0.96** |
| b2_float | 1.00 → 0.98 | 1.06 → 1.07 |
| b7_sort | 1.97 → 2.01 | 1.96 → 1.88 |
| b3_recursion | 1.83 → 2.24 | 1.10 → 1.24 |
| b9_json | 4.68 → 5.40 | 4.23 → 4.56 |

**现在 beat 的**：对 C —— b5（0.61×）、b6（0.87×）、b2（0.98×）；
对 Go —— b8_threads1（**0.77×**）、b1_int（**0.82×**）、b6（0.96×）。

**b3 / b9 的比值反而变差**（1.83→2.24、4.68→5.40）。这两个都是
**分支/调用延迟敏感**的基准（b3 是 270 万次调用链，b9 是每字节两次守卫），
换到一台更慢的 runner 上放大得比 C 更多。

**已用本机受控 A/B 排除"是 `opt_store_back` 拖累的"**（三轮交替、min of 5）：

| 基准 | 有 pass | 无 pass |
|---|---|---|
| b9_json | 38.1 / 38.1 / 38.1 | 38.5 / 38.9 / 38.7 |
| b3_recursion | 6.3 / 7.0 / 7.1 | 7.0 / 7.0 / 6.9 |

b9 上这个 pass 是**略快 1.5%**、b3 是噪声内 —— 所以 CI 比值的变化是
runner 特性，不是回归。要精确判定 b3/b9 需要固定 runner 复测。

### 3.37 两条控制流优化（v2.68 / v2.69）

**v2.68 死跳转消除**：`jmp L` 紧跟 `label L` → 删（`jcc .. L` 同样）。
`_lower_cond` 把 `a || b || c` 降级成 `jcc T; jmp next; next: jcc T; ...`，
每个 `jmp next` 的目标就是紧邻的下一条 label。b9 的空白判断因此是
12 条 / 8 分支，4 条 `jmp` 全废 → 9 条 / 5 分支。

**v2.69 标志位循环换 break**：`while go == 1 && p < n` 里的 `go` 只在
"该退出"的分支里置 0，其实是 break 的笨写法，每轮白付一次比较 + 分支。
满足 4 个前提（循环外只定义一次 / 循环内只有 `mov go,0` / 只有一处 /
没有别的读）时把 `go = 0` 换成 `jmp E`，守卫从 6 条降到 3 条。
**回边不能删**（then 分支还要回循环头）。

b9_json 的 `jws` 循环：v2.67 的 **26 条 → 20 条**；b9 本机 A/B
33.1/33.9 → **29.6/29.0（−11~14%）**。

### 3.38 CI 数字（v2.69 提交，windows-latest，min of 5）

来源：run `40449955296`（三 job 全绿）。机器与 §3.34 那次接近
（C 的 b1 6.4 vs 4.6、Python 2820 vs 1650 —— 比 §3.34 慢、比 §3.36 快），
仍然只能比同 run 内的比值。

| 基准 | quelmara0 | c | go | 对 C | 对 Go |
|---|---|---|---|---|---|
| b1_int | 18.8 | 6.4 | 18.9 | 2.94× | **0.99×** |
| b2_float | 7.0 | 7.0 | 7.1 | **1.00×** | **0.99×** |
| b3_recursion | 6.3 | 2.4 | 4.3 | 2.63× | 1.47× |
| b4_array | 9.0 | 4.0 | 4.2 | 2.25× | 2.14× |
| b5_string | 32.2 | 39.9 | 20.4 | **0.81×** | 1.58× |
| b6_hash | 11.3 | 11.7 | 11.1 | **0.97×** | 1.02× |
| b7_sort | 29.6 | 13.3 | 13.1 | 2.23× | 2.26× |
| b8_threads1 | 149.5 | 50.9 | 151.2 | 2.94× | **0.99×** |
| b8_threads4 | 103.7 | 69.3 | 89.6 | 1.50× | 1.16× |
| b9_json | 21.6 | 5.0 | 5.8 | 4.32× | 3.72× |

**现在的总账**（对 C / 对 Go）：

| 结论 | 基准 |
|---|---|
| **快于 C** | b5 0.81×、b6 0.97×、b2 1.00× |
| **快于或持平 Go** | b1 0.99×、b2 0.99×、b6 1.02×、b8_threads1 0.99× |
| 还差一截 | b9 4.32×、b3 2.63×、b7 2.23×、b4 2.25×、b8s4 1.50× |

从 v2.64 到 v2.69（同一量级机器上）：b9 4.68 → **4.32**（对 Go 4.23 → 3.72）、
b4 2.94 → **2.25**、b8s1 3.32 → **2.94**、b1 3.24 → **2.94**。

**b3 / b7 的比值在这几轮里持续漂移**（b3 1.83→2.24→2.63，b7 1.97→2.01→2.23），
而本机 A/B 测不出对应变化（b3 6.5~7.1、b7 在噪声内）—— 这两个都是
**调用/分支延迟敏感**的基准，对 runner 的微架构最敏感。要判定它们
必须有固定 runner，不能跨 run 比。

### 3.39 常量下标位移 + itoa 去拷贝（v2.70 / v2.71）

**v2.70 常量下标用位移**：`load d, base, ('imm', k)` 以前先 `mov r11, k` 再
`[base + r11*8]`。vec 句柄的 data/len/cap、结构体字段、定长数组下标全是
常量，这条 `mov` 命中率极高。改成直接 `[base + k*8]`，b4 的 push 循环
29 → 25 条。

**v2.71 int→str 不再拷数字**：旧布局为了给 8 字节长度前缀腾位置，把数字
从 `[pos+1,39]` 整体拷到 `[8+neg,...]` —— 拷贝循环每个数字 ~19 条机器
指令，6 位数 110+ 条。新布局把前缀写到数字**正前方**、返回
`buf+pos+1`（`__str_len` 读 `[ptr-8]`，字符串不必落在固定偏移）。
b5 本机 A/B：38.5/35.2 → **34.3/31.9**。

两个踩过的坑（都记在 `versions/v2.71/CHANGELOG.md`）：NUL 必须写固定字节
48（`pos+1` 会清掉首字符）；返回值必须是**字符串起点**而不是前缀起点
（早 8 字节 → `__str_len` 读垃圾）。

### 3.40 CI 数字（v2.71 提交，windows-latest，min of 5）

来源：run `40454253895`（三 job 全绿）。这台 runner 与 §3.34 同一量级
（C 的 b1 4.0 vs 4.6、Python 1501 vs 1586），所以可以和 v2.64 那行比。

| 基准 | quelmara0 | c | go | 对 C | 对 Go |
|---|---|---|---|---|---|
| b1_int | 13.4 | 4.0 | 11.9 | 3.35× | 1.13× |
| b2_float | 4.7 | 4.6 | 4.6 | 1.02× | 1.02× |
| b3_recursion | 3.1 | 1.6 | 2.5 | 1.94× | 1.24× |
| b4_array | 4.9 | 3.1 | 3.7 | **1.58×** | **1.32×** |
| b5_string | 14.6 | 21.1 | 11.3 | **0.69×** | 1.29× |
| b6_hash | 8.6 | 9.3 | 9.0 | **0.92×** | **0.96×** |
| b7_sort | 17.9 | 11.2 | 11.0 | **1.60×** | **1.63×** |
| b8_threads1 | 110.2 | 32.3 | 97.2 | 3.41× | 1.13× |
| b8_threads4 | 54.9 | 49.0 | 55.3 | 1.12× | **0.99×** |
| b9_json | 10.2 | 2.6 | 2.4 | **3.92×** | 4.25× |

**v2.64 → v2.71 的比值变化**（同量级机器，八个 pass 的累计效果）：

| 基准 | 对 C | 对 Go |
|---|---|---|
| b4_array | 2.94 → **1.58** | 2.85 → **1.32** |
| b7_sort | 1.97 → **1.60** | 1.96 → **1.63** |
| b9_json | 4.68 → **3.92** | 4.23 → 4.25 |
| b5_string | 0.78 → **0.69** | 1.37 → **1.29** |
| b6_hash | 0.99 → **0.92** | 0.85 → 0.96 |
| b8_threads4 | 1.18 → **1.12** | 1.04 → **0.99** |

**当前总账**：对 C 快于——b5 0.69×、b6 0.92×；对 Go 快于或持平——b6 0.96×、
b8_threads4 0.99×、b2 1.02×。b4/b7 从"差 3 倍"压到"差 1.3–1.6 倍"。

还差一截的：b9 3.92×（每字节的越界检查 + 4 次比较的空白判断）、
b1/b8s1 3.4×（C 的 AVX2）、b3 1.94×（调用开销）。

### 3.41 CI 数字（v2.72 提交，windows-latest，min of 5）

来源：run `40458437872`（三 job 全绿）。机器与 §3.38（v2.69）同一量级
（C 的 b1 6.6 vs 6.4、Python 2764 vs 2820），可以逐行比。

| 基准 | quelmara0 | c | go | 对 C | 对 Go |
|---|---|---|---|---|---|
| b1_int | 23.2 | 6.6 | 23.1 | 3.52× | **1.00×** |
| b2_float | 5.8 | 5.8 | 5.6 | **1.00×** | 1.04× |
| b3_recursion | 5.5 | 2.3 | 4.4 | 2.39× | 1.25× |
| b4_array | 10.4 | 6.3 | 6.4 | **1.65×** | **1.63×** |
| b5_string | 21.7 | 34.3 | 19.1 | **0.63×** | 1.14× |
| b6_hash | 14.3 | 16.1 | 14.6 | **0.89×** | **0.98×** |
| b7_sort | 27.9 | 14.4 | 14.1 | **1.94×** | **1.98×** |
| b8_threads1 | 175.6 | 52.6 | 183.2 | 3.34× | **0.96×** |
| b8_threads4 | 92.8 | 87.1 | 93.8 | **1.07×** | **0.99×** |
| b9_json | 20.5 | 5.2 | 5.7 | **3.94×** | **3.60×** |

**v2.69 → v2.72 的比值变化**（三个 pass：常量下标位移 / itoa 去拷贝 /
分支反转 + 终结符后死码）：

| 基准 | 对 C | 对 Go |
|---|---|---|
| b8_threads4 | 1.50 → **1.07** | 1.16 → **0.99** |
| b4_array | 2.25 → **1.65** | 2.14 → **1.63** |
| b7_sort | 2.23 → **1.94** | 2.26 → **1.98** |
| b5_string | 0.81 → **0.63** | 1.58 → **1.14** |
| b9_json | 4.32 → **3.94** | 3.72 → **3.60** |
| b3_recursion | 2.63 → **2.39** | 1.47 → **1.25** |
| b6_hash | 0.97 → **0.89** | 1.02 → **0.98** |

**当前总账**：

| 结论 | 基准 |
|---|---|
| **快于 C** | b5 0.63×、b6 0.89×、b2 1.00× |
| **快于或持平 Go** | b8_threads1 0.96×、b6 0.98×、b8_threads4 0.99×、b1 1.00× |
| 还差一截 | b9 3.94×、b1 3.52×（C 的 AVX2）、b8s1 3.34×、b3 2.39× |

### 3.42 CI 数字（v2.75 提交，windows-latest，min of 5）

来源：run `40465644492`（三 job 全绿）。机器与 §3.41（v2.72）同一量级
（C 的 b1 6.4 vs 6.6、Python 2853 vs 2764），可逐行比。

| 基准 | quelmara0 | c | go | 对 C | 对 Go |
|---|---|---|---|---|---|
| b1_int | 18.7 | 6.4 | 18.7 | **2.92×** | **1.00×** |
| b2_float | 7.0 | 7.0 | 7.3 | **1.00×** | **0.96×** |
| b3_recursion | 6.3 | 2.4 | 4.0 | 2.63× | 1.58× |
| b4_array | 7.1 | 3.9 | 4.3 | 1.82× | 1.65× |
| b5_string | 17.6 | 40.0 | 20.7 | **0.44×** | **0.85×** |
| b6_hash | 10.9 | 11.7 | 11.2 | **0.93×** | **0.97×** |
| b7_sort | 26.6 | 13.2 | 12.9 | 2.02× | 2.06× |
| b8_threads1 | 150.2 | 51.2 | 153.0 | **2.93×** | **0.98×** |
| b8_threads4 | 100.1 | 69.0 | 87.9 | 1.45× | 1.14× |
| b9_json | 17.1 | 5.0 | 5.4 | **3.42×** | **3.17×** |

**总账**：

| 结论 | 基准 |
|---|---|
| **快于 C** | b5 **0.44×**、b6 0.93×、b2 1.00× |
| **快于或持平 Go** | b5 **0.85×**、b2 0.96×、b6 0.97×、b8_threads1 0.98×、b1 1.00× |
| 还差一截 | b9 3.42×、b1 2.92×（C 的 AVX2）、b8s1 2.93×、b3 2.63×、b7 2.02× |

**v2.72 → v2.75 的关键变化**（这轮抓到一个自己造成的回归）：

| 基准 | 对 C | 说明 |
|---|---|---|
| b1_int | 3.52 → **2.92** | v2.72 的分支反转打断了归纳削减，v2.75 把反转挪到最后 |
| b8_threads1 | 3.34 → **2.93** | 同上 |
| b5_string | 0.63 → **0.44** | v2.73 的常量折叠 + 分配器溢出启发式 |
| b9_json | 3.94 → **3.42** | v2.74 让 flag_loop 认反转后的守卫形态 |

### 3.43 堆换成 VirtualAlloc 私有页（v2.76）：b4 −54%

**发现过程**：b4_array 上 qlmc 比 stage-0 慢 2.2×，分段计时后差距**全在 push 循环**
（34.8 vs 7.6 ms），而循环只有 17 条指令。用"同一循环跑两遍"的对照
（`build/probe/pf.qma`）定位到**首次触碰**：

| | 首次 push | 第二遍 |
|---|---|---|
| qlmc（.bss 堆） | 23.3 ms | 7.3 ms |
| stage-0（HeapAlloc） | 7.4 ms | 3.8 ms |

用 C 直接量三种内存来源写 16 MB（本机 VBS 开启）：

| 来源 | 16 MB 顺序写 |
|---|---|
| `static int64_t a[2M]`（.bss） | **21 ~ 29 ms** |
| `malloc(16 MB)` | 5.9 ~ 7.1 ms |
| `VirtualAlloc(MEM_COMMIT)` | **5.7 ~ 6.4 ms** |

`.bss` 是映像节（pagefile 后备 + 写时复制），每页 5.5 µs；私有页 1 µs。
**提交本身不花钱**（`VirtualAlloc` 16 MB 0.01 ms，零页在首次写时才给）。

**改法**：`__alloc` 首次调用时 `VirtualAlloc(0, 64 MB, MEM_COMMIT|MEM_RESERVE,
PAGE_READWRITE)`，基址/上限写进 `.bss` 四个槽（游标/锁/基址/上限）。`.bss` 从
64 MB 缩到 **32 字节**；越界检查顺带从三条指令收成 `cmp r8,[rip+bss+24]` 一条。

**本机 min of 5，两轮交替**：

| 基准 | 改前 | 改后 |
|---|---|---|
| b4_array | 31.3 ~ 32.7 | **13.7 ~ 15.9** |
| b9_json | 29.2 ~ 30.7 | 27.1 ~ 31.2（噪声内） |

同一版还修了 b9_json 的两条纯浪费（`jws` 每字节 22 → 18 条）：JCMP→JCMPI 折叠
后没有退回使用计数（死 `mov r8d, imm`）、比较操作数被搬进 RCX 才能比。

**本机这一轮整体偏慢**（b1 从 25 ms 涨到 42 ms，新旧产物一起变慢），所以绝对值
只用于同轮横向比；跨版本比值看 CI 表。

### 3.44 CI 数字（v2.77 提交，windows-latest，min of 5）

来源：run `40473331285`（三 job 全绿；windows job 的 gzip 一步已随 v2.77 修好）。
这一版第一次把 **qlmc 列**和 stage-0 列并排看，于是暴露一个长期缺口（见下）。

| 基准 | qlmc | stage-0 | c | go | qlmc/C | qlmc/Go | s0/C | s0/Go |
|---|---|---|---|---|---|---|---|---|
| b1_int | 28.3 | 18.8 | 6.4 | 18.7 | 4.42× | 1.51× | 2.94× | 1.01× |
| b2_float | 7.0 | 7.0 | 7.0 | 7.0 | **1.00×** | **1.00×** | 1.00× | 1.00× |
| b3_recursion | 8.4 | 6.3 | 2.4 | 4.6 | 3.50× | 1.83× | 2.63× | 1.37× |
| b4_array | 6.2 | 7.0 | 4.0 | 4.0 | 1.55× | 1.55× | 1.75× | 1.75× |
| b5_string | 24.3 | 17.0 | 39.9 | 20.8 | **0.61×** | 1.17× | **0.43×** | **0.82×** |
| b6_hash | 10.2 | 10.9 | 11.8 | 10.7 | **0.86×** | **0.95×** | **0.92×** | 1.02× |
| b7_sort | 20.4 | 26.5 | 13.2 | 12.9 | 1.55× | 1.58× | 2.01× | 2.05× |
| b8_threads1 | 227.8 | 149.8 | 51.0 | 152.7 | 4.47× | 1.49× | 2.94× | **0.98×** |
| b8_threads4 | 113.2 | 100.0 | 69.8 | 88.7 | 1.62× | 1.28× | 1.43× | 1.13× |
| b9_json | 20.5 | 16.9 | 5.0 | 5.6 | 4.10× | 3.66× | 3.38× | 3.02× |

**总账（qlmc）**：快于 C 两项（b5 0.61×、b6 0.86×）、持平一项（b2），快于 Go
一项（b6 0.95×）、持平一项（b2）。b4 从 v2.75 的 1.82× 降到 **1.55×**（堆换私有页）。

**新发现：qlmc 在五项上比 stage-0 慢 30~50%。**

| 基准 | qlmc | stage-0 | 倍数 |
|---|---|---|---|
| b1_int | 28.3 | 18.8 | 1.51× |
| b8_threads1 | 227.8 | 149.8 | 1.52× |
| b5_string | 24.3 | 17.0 | 1.43× |
| b9_json | 20.5 | 16.9 | 1.21× |
| b3_recursion | 8.4 | 6.3 | 1.33× |

反汇编 b1 的热循环就看清了：**stage-0 有归纳削减，qlmc 没有**。

```
stage-0（9 条）                      qlmc（21 条）
  cmp  r12, n                          cmp  r13, rbx
  jge  end                             jge  end
  mov  rsi, rdi   ; acc += 旧值        imul r10, r13, 7
  add  rdi, 7     ; m += 7             mov  rcx, r10        ← 纯搬运
  mov  rax, rdi                        mov  r11, rcx ; sar r11, 0x3f
  sub  rax, 0xd                        mov  rax, rcx ; xor/sub  ← 取绝对值
  cmovns rdi, rax ; 回绕               movabs rdx, 魔数 ; mul rdx
  add  rbx, rsi                        shr  rax, 3 ; xor/sub   ← 符号修正
  add  r12, 1 ; jmp                    imul rax, rax, 0xd ; sub
                                       mov  rax, rcx ; mov r8, rax  ← 纯搬运
```

`(i*7)%13` 在 stage-0 上是"递增计数器 + `cmovns` 回绕"，在 qlmc 上是**每轮一次
64 位 `mul` + 16 条**。这就是 b1/b8_threads1 的 1.5× 差距（两者都是这个形状）。

**为什么没直接搬**：stage-0 的 `opt_mod_inductive`（`tools/stage0/qlm_opt.py`）
依赖"`t` 非负"的证明（`analyze_nonneg` + 降级期非负链 `nnv`），而 qlmc 的
优化层没有范围分析。没有这个证明就套 `cssub` 回绕，负数取模会算错（C 语义是
截断取模）。这是下一轮的正经活：**给 qlmc 加一个窄范围分析（循环计数器从 0
起、步长为正、上界是常量 → 非负），再把归纳削减搬过来**。

### 3.45 归纳削减搬进 qlmc（v2.81）：b1 热循环 21 → 10 条

v2.77 的 §3.44 指出 qlmc 在 b1_int / b8_threads1 上比 stage-0 慢 1.5×，
根因是**没有归纳削减**。v2.81 补上，但用的是**比 stage-0 窄得多**的证明
（stage-0 依赖范围分析，qlmc 没有）：

> `t = i * C`，`i` 循环外初始化成常量 `k >= 0`、循环内唯一定义是 `i = i + s`
> （`s > 0`）→ `t >= 0`；再要求 `0 < C < D` 与守卫 `i < N`（常量，
> `C*N < 2^62`，排掉溢出）。

变换：前导 `v = (k*C) % D`（常量）；体内 `r = v`，`i += s` 之后
`v += C`，`v >= D` 时 `v -= D`。

**本机 min of 5，新旧产物交替**：

| 基准 | 改前 | 改后 |
|---|---|---|
| b1_int | 40.0 / 49.1 / 43.8 | **21.0 / 22.1 / 21.3** |

热循环 **21 → 10 条**（stage-0 是 9 条），校验和不变（`119999988`）。
顺带修掉 `_opt_pure` 漏列 `OP_BINI` —— 以前归纳削减把 `t = i*C` 变成死代码
之后 DCE 删不掉，热循环里白留一条 `imul`。

**b8_threads1 没覆盖**：同一个形状，但 `n` 是形参不是常量，溢出不可证，
所以不换。要覆盖它得做循环版本化（运行时判安全区间），留到下一版。

### 3.46 CI 数字（v2.81 提交，windows-latest，min of 5）

来源：run `40498117292`（bench 三 job 全绿）。**b1_int 从最差的一项翻成最快的一项**。

| 基准 | qlmc | stage-0 | c | go | qlmc/C | qlmc/Go |
|---|---|---|---|---|---|---|
| b1_int | **7.3** | 13.9 | 4.2 | 12.4 | 1.74× | **0.59×** |
| b2_float | 4.5 | 4.5 | 4.6 | 4.6 | **0.98×** | **0.98×** |
| b3_recursion | 3.4 | 2.8 | 1.7 | 3.1 | 2.00× | 1.10× |
| b4_array | 4.4 | 4.5 | 2.9 | 3.2 | 1.52× | 1.38× |
| b5_string | 18.5 | 11.9 | 20.0 | 11.2 | **0.93×** | 1.65× |
| b6_hash | 8.6 | 8.2 | 9.1 | 8.7 | **0.95×** | **0.99×** |
| b7_sort | 14.3 | 18.4 | 10.6 | 11.2 | 1.35× | 1.28× |
| b8_threads1 | 139.5 | 107.7 | 32.5 | 97.1 | 4.29× | 1.44× |
| b8_threads4 | 67.5 | 54.6 | 46.6 | 53.1 | 1.45× | 1.27× |
| b9_json | 10.1 | 9.2 | 2.6 | 3.1 | 3.88× | 3.26× |

**总账（qlmc）**：

| 结论 | 基准 |
|---|---|
| **快于 C** | b2 0.98×、b5 0.93×、b6 0.95× |
| **快于 Go** | b1 **0.59×**、b2 0.98×、b6 0.99× |
| 还差一截 | b8_threads1 4.29×（C 向量化）、b9 3.88×、b3 2.00×、b4 1.52×、b8s4 1.45×、b7 1.35× |

**b1_int 的变化**（v2.77 → v2.81，同一个基准、不同 runner，只看比值）：

| | v2.77 | v2.81 |
|---|---|---|
| 对 C | 4.42× | **1.74×** |
| 对 Go | 1.51× | **0.59×** |

而且 qlmc 现在**比 stage-0 快 1.9×**（7.3 vs 13.9）—— 两者都有归纳削减，差别在
回绕的写法：stage-0 用 `cmovns`（在循环携带链上多 2 个周期），qlmc 用一条
`jl` 跳过的条件减（分支完全可预测）。这是同一算法的两种实现，实测差一倍。

**注意**：qlmc 的 b8_threads1 仍是 4.29× —— 同一形状但 `n` 是形参，
归纳削减没覆盖（溢出不可证），要等循环版本化。

### 3.47 归纳削减加运行期守卫（v2.87）：上界是形参的循环也能优化

v2.81 的归纳削减只认"常量上界"，而**上界是形参是最常见的形状**
（`fn work(n)` 里 `while i < n`）。v2.87 加运行期守卫：`i < LIMIT`
（`LIMIT = 2^62/C`）才走快路，否则走原来的除法。`i` 单调递增 → 越过 LIMIT
就回不到快路，所以慢路把 `v` 弄脏也无所谓；非负前提仍由"初值常量 + 步长为正"
保证。

**本机 min of 3，新旧产物交替**：

| 基准 | 改前 | 改后 |
|---|---|---|
| b8_threads1 | 333 / 347 / 377 ms | **296 / 305 / 299 ms**（−13%） |
| b1_int（常量上界，无守卫路径） | 20.2 / 21.6 | 20.5（不变） |

校验和 b1 `119999988`、b8 `959999992` 与改前完全一致。

**只快了 13%，不是 2×**：热循环已经降到 9~10 条指令，瓶颈变成**两条 taken
branch**（回绕的 `jl` + 循环回边）。下一步是回绕无分支化（`t=v-D; m=t>>63;
m&=D; v=t+m`）+ 循环展开 2× —— 试过无分支回绕，但编译器在 `_vnew` 之后崩了
（`vec index out of bounds`），已回退，留待下一轮。

### 3.48 CI 数字（v2.87 提交，windows-latest，min of 5）

来源：run `40530187354`。这台 runner 比 v2.81 那次慢约 1.5×（C 的 b1 4.2 → 6.4），
**只能比同一次 run 内的比值**。

| 基准 | qlmc | stage-0 | c | go | qlmc/C | qlmc/Go |
|---|---|---|---|---|---|---|
| b1_int | 15.4 | 18.7 | 6.4 | 19.2 | 2.41× | **0.80×** |
| b2_float | 7.0 | 7.0 | 7.0 | 7.1 | **1.00×** | **0.99×** |
| b3_recursion | 8.4 | 6.3 | 2.4 | 4.3 | 3.50× | 1.95× |
| b4_array | 6.8 | 7.3 | 4.0 | 4.2 | 1.70× | 1.62× |
| b5_string | 24.3 | 17.6 | 39.8 | 20.7 | **0.61×** | 1.17× |
| b6_hash | 11.7 | 11.6 | 12.1 | 11.7 | **0.97×** | **1.00×** |
| b7_sort | 20.4 | 26.6 | 13.3 | 13.2 | 1.53× | 1.55× |
| b8_threads1 | 173.9 | 149.7 | 51.0 | 150.3 | 3.41× | 1.16× |
| b8_threads4 | 96.5 | 100.2 | 69.4 | 87.8 | 1.39× | 1.10× |
| b9_json | 20.3 | 17.0 | 5.0 | 5.8 | 4.06× | 3.50× |

**b8_threads1 的变化**（v2.77 → v2.87，只看比值）：对 C 4.29× → **3.41×**，
对 Go 1.44× → **1.16×**。这是运行期守卫（§3.47）的直接效果。

**总账（qlmc）**：快于 C 三项（b5 0.61×、b6 0.97×、b2 1.00×）；快于或持平 Go
四项（b1 0.80×、b2 0.99×、b6 1.00×、b8s4 1.10×），b8s1 1.16× / b5 1.17× 紧随。
还差一截：b9 4.06×（对 C）、b3 3.50×、b8s1 3.41×（C 是 AVX2 向量化）。

### 3.49 无分支回绕是负结果（v2.88）：b1 慢 6.6×，已回退

v2.87 把 b8 只推快了 13%，我判断瓶颈是"回绕的 `jl` + 循环回边"两条 taken
branch，于是试了纯算术回绕（`t=v-D; m=t>>63; m&=D; v=t+m`）：

| 基准 | 条件减（保留） | 无分支（弃用） |
|---|---|---|
| b8_threads1 | 278 / 287 / 292 ms | 273 / 279 / 282 ms（快 2~3%） |
| b1_int | 21.0 / 23.5 ms | **138.1 / 138.5 ms（慢 6.6×）** |

原因：无分支版要多两个临时值，b1 的 `main` 里寄存器池（7 个）不够，溢出到
帧槽 —— 热循环凭空多两次访存。**b1 是延迟敏感型、b8 是吞吐型**，同一个变换
在两边方向相反。条件减的分支在 13 周期模式上预测得很好，"少一条 taken
branch"本来就不是瓶颈。**判断错了，回退。**

顺带修了两处优化层隐患（以前不触发，任何"往 IR 加算术"的优化都会踩）：
优化层 `_vnew` 出新 vreg 后 `cok/cval/use/ndef` 四张表要跟着补齐（`_opt_copy`
里有未做上界检查的 `use.get(d)`）；新临时值的 `vstart`/`vend` 必须自己写
（`_vnew` 留的 vend=0 是倒挂区间）。

**下一步的杠杆**：循环展开 2×（摊薄回边）、寄存器压力（7 个变量池是隐性上限）、
自动向量化（追 C 的唯一办法）。

### 3.50 本机测量分辨率只到 ±20%（v2.89 校准）：b8 的微优化已经测不出来

v2.88 之后想继续抠 b8 的 3.41×，先做了一次**测量校准**，结论比优化本身重要。

**同一份产物连测 6 次**（b8_threads1，`min of 1`，中间没有别的负载）：

```
286 / 286 / 288 / 284 / 309 / 290 ms
```

±5% 的run-to-run抖动；而**同一份产物在几十分钟的跨度上**从 278 漂到 360 ms
（±15%）。所以本机能可靠分辨的效果是 **≥20%**，低于这个数的"优化"只能靠
CI（`bench.yml`，min of 5，固定 runner）判定。

**顺带做了一个决定性诊断**：b8 的守卫版热循环里有一条 `imul r10, r13, 7`
（只有慢路用），我把它的 IR 直接 NOP 掉只测时间：

| | 6 次 |
|---|---|
| 带 imul | 320 / 360 / 320 ms |
| 无 imul | 345 / 327 / 334 ms |

**没有差别**（差异全在噪声里）。说明这个循环**不是吞吐瓶颈** —— 少一条指令
不改变时间。结合 v2.88 的"无分支化也没用"，b8 剩下的时间花在**依赖链和前端**
上，靠"减一条指令"已经无效。

**这条校准的用处**：以后凡是想在 b8/b1 这类微基准上做 <20% 的改动，
必须走 CI 验证，不能凭本机数字下结论。本机只适合做**结构性**判断
（"这个循环少了 12 条指令"）和**正确性**判断（校验和）。

**剩下的路都是结构性的**（每个都要单开一轮）：
1. 循环版本化（把守卫挪出热循环，要复制循环体 + vreg 重映射）；
2. 尾调用优化（b3/b7/b9 都是递归，C 靠 sibling call 把它们变成了 jmp）；
3. 自动向量化（b1/b8 对 C 的差距全在这里，C 是 AVX2 的 48 条/16 元素）。

### 3.51 基准复跑（v2.89）：**CI 的比值也有 ±40% 波动**，只有结构性证据可靠

v2.87 / v2.88 / v2.89 三版的**生成代码完全相同**（v2.88 把无分支回绕回退了，
v2.89 零改动）。CI 上 b1_int 的比值却跑了三个数：

| run | qlmc | C | qlmc/C |
|---|---|---|---|
| v2.81 `40498117292` | 7.3 | 4.2 | **1.74×** |
| v2.87 `40530187354` | 15.4 | 6.4 | **2.41×** |
| v2.89 `40541012892` | 21.4 | 6.7 | **3.19×** |

C 那一列只抖了 5%（4.2→6.4→6.7，跨 run 换了 runner），**qlmc 那一列抖了 3 倍**
（7.3→15.4→21.4）。同一份产物。

**结论：连 CI 的绝对值都不可跨 run 比，比值同理（±40%）。** 能作为证据的只有：
1. **指令条数**（结构性事实，如 b1 热循环 21→13→10 条）；
2. **校验和**（正确性）；
3. **同一次 run 内的横向比值**（C/Go/stage-0 与 qlmc 在同一台机器、同一时刻测）。

这解释了为什么 v2.87 的"b8 4.29×→3.41×"看着像进步、v2.89 又回到 3.71× ——
真实的结构性变化（热循环 21→13 条）是真的，具体倍数别当真。

### 3.52 v2.89 基准全表（run `40541012892`，windows-latest，min of 5）

| 基准 | qlmc | stage-0 | c | go | qlmc/C | qlmc/Go |
|---|---|---|---|---|---|---|
| b1_int | 21.4 | 12.0 | 6.7 | 14.7 | 3.19× | 1.46× |
| b2_float | 6.0 | 5.6 | 5.7 | 5.4 | 1.05× | 1.11× |
| b3_recursion | 5.2 | 3.7 | 1.8 | 4.1 | 2.89× | 1.27× |
| b4_array | 9.6 | 8.8 | 6.9 | 6.9 | 1.39× | 1.39× |
| b5_string | 20.6 | 13.1 | 29.8 | 16.3 | **0.69×** | 1.26× |
| b6_hash | 12.4 | 12.6 | 14.3 | 12.7 | **0.87×** | **0.98×** |
| b7_sort | 20.1 | 24.9 | 13.0 | 13.7 | 1.55× | 1.47× |
| b8_threads1 | 201.6 | 95.1 | 54.3 | 120.0 | 3.71× | 1.68× |
| b8_threads4 | 92.2 | 58.6 | 59.5 | 60.7 | 1.55× | 1.52× |
| b9_json | 18.2 | 16.2 | 4.8 | 5.6 | 3.79× | 3.25× |

本机同一轮 quelmara vs C（`--langs quelmara c`，校验和 10/10 一致）：

| b1 | b2 | b3 | b4 | b5 | b6 | b7 | b8s1 | b8s4 | b9 |
|---|---|---|---|---|---|---|---|---|---|
| 19.3 | 22.7 | 7.9 | 17.3 | 63.6 | 45.5 | 26.6 | 282.1 | 86.1 | 26.9 |
| C 11.1 | 22.6 | 3.0 | 9.2 | 57.5 | 43.9 | 15.0 | 90.9 | 47.3 | 7.1 |
| **1.74×** | **1.00×** | 2.63× | 1.88× | 1.11× | 1.04× | 1.77× | 3.10× | 1.82× | 3.79× |

### 3.53 内联器的设计（下一轮执行）：三条硬约束与落地顺序

三轮"深度优化"下来，标量层已经到底（§3.49/§3.50/§3.51）。剩下三件事都是
"新一层机器"，其中**内联器**的收益面最大：b9 4.06×（每 token 一次调用）、
b3 2.89×、b7 1.55× 对 C。这节把设计钉下来，下一轮直接动手。

#### 硬约束一：名字会撞（必须先解决）

qlmc 的变量解析是 `_try_var` / `_var_id`：先在 `fc.bind`（作用域栈，`C_BD`
是深度）里找，再**从后往前**扫 `fc.vmap`（所有变量的 name→vreg 表）。

内联进来的函数体带着**它自己的名字 id**（`let n = len(s)` 里的 `n` 就是全局
名字池里的同一个 id）。如果直接降级，内联产生的 `n` 会留在 `vmap` 里，**内联
结束之后调用方的 `n` 会被解析到内联体里的那个** —— 静默错。

`vmap` 没有 `truncate`（`vec` 只支持 `push`/`set`/`clear`），所以"用完弹掉"
做不到。**唯一干净的办法是给内联实例的每个名字生成新 id**：

1. 扫一遍被内联的子树，收集出现的所有 name id；
2. 为每个生成新 id：往 `fc.names` 里 push 一个 `"原函数名$实例号$原名"` 串；
3. **克隆子树**，把 `S_LET.a` / `E_VAR.a` / `S_ASSIGN.a` / `E_FIELD` 的名字换成
   新 id —— 必须克隆，原地改会污染被内联函数的本体（它还可能在别处被调用）；
4. 用克隆后的子树降级。

第 3 步是主要工作量：要覆盖**所有带名字的节点**（`S_LET` / `S_ASSIGN` /
`S_ASG_FIELD` / `S_ASG_INDEX` / `E_VAR` / `E_CALL` / `E_METHOD` / `E_ENUMCTOR` …），
漏一个就是"名字串了"的静默错。

#### 硬约束二：`return` 要落到局部出口

`_lower_block(fc, head, ep)` 已经把"返回标签"当参数传下去了 ✓。内联时：
- 新开一个标签 `lret`，用 `_lower_block(fc, body, lret)` 降级体；
- `return e` 的降级要**写进一个专用槽**而不是 `RAX` 再 `jmp ep`。
  加一个 cell `C_INL_RET`（默认 -1）：>= 0 时 `S_RETURN` 发 `MOV slot, v; JMP ep`，
  否则维持现在的 `RET v`；
- 降级完在 `lret` 处把槽里的值取出来作为调用结果。

#### 硬约束三：不能内联自己（含间接）

递归函数（`jval`/`jobj`/`jarr` 互相调用）内联会无限展开。闸门：
- 直接递归：函数体里出现自己的 name id → 拒绝；
- 间接递归：内联**只做一层**（不递归内联内联体），再加"体 ≤ N 个节点"的
  尺寸闸门 —— 一层 + 尺寸限制就够挡住无限展开；
- 有 `defer` 的函数拒绝（`defer` 与出口标签绑定）；
- 形参 > 4 个拒绝（栈实参搬进内联体会很麻烦）。

#### 落地顺序（每步都能单独验证）

| 步 | 内容 | 判据 |
|---|---|---|
| 1 | 子树克隆 + 名字重映射（**不内联任何东西**，只加工具） | 68 条差分全绿 |
| 2 | 内联"无参、无局部、单 `return` 表达式"的纯函数 | 差分 + 校验和 |
| 3 | 放开到有局部、有 `if`、有循环的小函数 | 差分 + 校验和 |
| 4 | 尺寸闸门调到 `jws`/`jstr`/`jnum` 都能进 | b9 的 CI 数字 |

**先做第 1 步**：它是纯工具，不进任何决策路径，所以**不可能改坏产物**——
做完跑一遍 68 条差分确认"零变化"，再往上叠。

### 3.54 args() 双重偏移（v2.90）：Linux 侧对拍链曾经整条是断的

`lower_args` 给 Windows 与 POSIX 两条路径**共用**了同一份收尾偏移
（`argv+8` / `argc-1`）。但 `__unix_args_copy` 产出的表已经排除了程序名，
于是 Linux 上又跳过一个参数、又推了 8 字节基址：

| 输入 | v2.89 | v2.90 |
|---|---|---|
| `./prog`（零参数） | `n=0`（对，但靠运气） | `n=0` |
| `./prog foo`（单参数） | **SIGSEGV** | `n=1` / `[0] foo` |
| `./prog AAA BBB` | `n=1` / `[0] BBB` | `n=2` / `[0] AAA` / `[1] BBB` |

影响面**不是"args 少个参数"这么小**：所有在 Linux 上跑的 stage-1 夹具都把
文件路径经 `args()[0]` 传给 `read_text`，路径拿不到 → 词法器一行不输出就退出。

修复后的对拍（本机 Linux，x86-64）：

| 项 | 修复前 | 修复后 |
|---|---|---|
| `lexdiff` | PASS=0 FAIL=307 | **PASS=307 FAIL=0** |
| `parsediff` | PASS=0 FAIL=211 | **PASS=211 FAIL=0** |
| `run_native_tests.sh` | PASS=64 | **PASS=67**（+3 新用例） |

**为什么漏了一年**：`args()` 的回归只在 Windows 上（`run_win_tests.py` 的
`[3d]`），而 `lower_args` 恰恰按平台分叉。同一个"两条路径实现不一致"的
根因，`docs/07-gaps.md` §7.2 已记过一次（v1.19 浮点比较）。

### 3.55 C 后端第一次真正全绿（v2.91）：两个后端共用的 DCE 缺陷

`tests/run_tests.sh`（C 后端回归）第一次在本机跑通——为此把一个独立 gcc-12
解进工具链（`--sysroot` 指向它，不需要 root）。跑通后暴露的不是一个 bug，
是三个叠在一起的：

| 缺陷 | 症状 | 根因 |
|---|---|---|
| **全局 DCE 漏扫结构体字面量** | 回调函数被当死代码删掉 | `walk()` 只认 `tuple`/`list`，而 `("structlit", path, {字段: 表达式})` 的第三项是 **`dict`** |
| 用户函数与 libc 撞名 | `error: conflicting types for 'send'` | 函数名原样写进 C，`std/net` 的 `pub fn send` 与 `<unistd.h>` 同名同形冲突 |
| 函数值三处缺口 | `undeclared` / `called object is not a function` | 裸函数名当值、变量间接调用、`spawn` 目标名都没走符号映射 |

第一条最要紧：**两个后端共用这份 DCE**。`let s = S { cb: handler }` 里
`handler` 只以裸名出现在 dict 中，DCE 看不见 → 删掉 → 下游报"未定义"。
自研后端也吃这个亏，只是报错更早、更像"名字写错"。

修复后：

| 项 | 修复前 | 修复后 |
|---|---|---|
| `run_tests.sh`（C 后端） | PASS=15 **FAIL=2** | **PASS=15 FAIL=0** |
| `run_native_tests.sh` | PASS=67 **FAIL=34**（缺 cc） | **PASS=101 FAIL=0** |
| `lexdiff` / `parsediff` | 307/211 全绿 | 307/211 全绿（无回归） |

`run_native_tests.sh` 涨的 34 条正是以前因缺 `cc` 而红的 C 侧交叉验证项。

另外 `examples/echo_server.qma` 从 v0.1 起用的是 `net.TcpServer { ... }` 这套
**从未实现的 SPEC 模型**（`std/net.qma` 第二行就写着"仍是目标模型"）——
已改写为真实可用的 `serve(port, backlog, cb...)` 形式。`run_tests.sh` 的网络段
同时改成按能力探测：C 后端没有 `tcp_listen` 就记 SKIP，而不是天天红着。

### 3.56 Linux 原生 socket（v2.92）：缺的其实是五分之一，被两道闸门挡住

`docs/07-gaps.md` 一直写着"`tcp_*` 内建没有 Linux 实现"。逐个看运行库，
**五分之四早就有了**（`listen`/`accept`/`send`/`recv`/`close` 全是 raw syscall），
缺的只有 `tcp_connect`，而它被两道闸门挡着：

| 闸门 | 症状 | 真因 |
|---|---|---|
| 派发层无条件拒绝 | `tcp_connect() 目前只在 Windows PE 后端实现（Linux DNS 未实现）` | 报错理由是 DNS，但点分字面量不需要解析器——把整条路径连字面量一起拒了 |
| 运行库里的 `return` | 补完第一道后报 `KeyError: '__tcp_recv'` | `lower_runtime()` 是个巨大的顺序函数，`__tcp_connect` 分支末尾的 `return` 把后面的 `__tcp_listen6`/`__tcp_accept`/`__tcp_send`/`__tcp_recv` **全跳过**了 |

第二道尤其值得记：报错点（`KeyError: '__tcp_recv'`）离病因（几十行前的
一个 `return`）很远，很容易往"函数没定义"的方向错查。

修复后真 socket 自环跑通（非 mock）：

| 场景 | 结果 |
|---|---|
| Quelmara 服务端 × 3 条 Python 并发连接 | 3/3 回显正确 |
| Quelmara 客户端 × Python 服务端 | `pong:ping-from-quelmara` |
| `run_native_tests.sh` | PASS=101 → **PASS=106 FAIL=0**（+5 条 POSIX 网络） |

顺带修掉 `__tcp_listen6`（纯 Win32）没有平台守卫、在 Linux 上也会发
`WSAStartup` 的问题。边界：只支持 IPv4 点分字面量，域名显式 fail-fast。

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
| ~~LICM 默认关闭~~ | ✅ v2.59 已修：LICM 默认开启 | 根因不是分配器，是 `mov byte [mem], reg` 漏 REX（reg 4..7 编成 `ah/ch/dh/bh`）；见 `07-gaps.md` §7.32 |
| 接口装箱不释放 | 热点循环频繁装箱会涨堆 | 无 rc/drop 路径 |
| `and` 用 64 位立即数（≥2^63）曾算错 | SWAR 位运算踩过：改成 `>>7 & 0x0101…` 规避 | v1.29 已规避，根因未定位（见 `07-gaps.md` §7.2） |
| `f64` 比较曾整型化 | `if a > b` 对负浮点给出相反结果（v1.19 已修） | 根因：`branch()` 直接发 `jcc` 未走 `fcmpset`；回归 `tests/t64_math.qma` |
| `std` 里 6 个模块 0 个 `pub` 导出、2 个模块解析失败 | 用户代码一引用就编译失败；`examples/{ws_demo,sse_demo}` 构建不过 | v2.01 审计、**v2.08 重测**（`std/ds` 补 13 个 `pub`、`std/timer` 重写后 5 个 `pub`，`http`/`net/core` 由同期另一条轨补齐）：剩 `core`/`gen`/`serialize`/`sse`/`time`/`ws` 共 69 个声明。清单与复现见 `07-gaps.md` §7.13 |
