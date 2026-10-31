# 当前状态（实测）

> **本文是全部实测数字的唯一出处。** 其它文档引用数字时写"见 `06-status.md`"。
> 口径日期：2026-10-29。环境：Windows 10/11 x86-64，Xeon E5-2666 v3（Haswell 代，
> **无 SHA-NI、无 AVX2**），VBS/Hyper-V 开启（进程冷启动 ~426 ms，跑分噪声 ±50%）。
> 解释器：Python 3.13.14。
>
> **v3.00 里程碑（2026-10-29）**：2.x 线 v2.01–v2.99（99 次编号更新 / 97 个版本目录）
> 收口，`VERSION` → `3.00.0`。本版**无代码改动**，下表数字沿用 v2.99 的实测值；
> 2.x 线整体复盘见 [`versions/v3.00/REPORT.md`](versions/v3.00/REPORT.md)。

## 1. 回归与对拍

| 项 | 结果 | 命令 |
|---|---|---|
| PE 回归（主回归） | **PASS=336 FAIL=0 SKIP=0**（v3.22 口径：新增 \	174_peer_ip\（双栈下的 peer_ip：端到端 3 组 + addr_text 纯函数 4 组）= 335 → 336；v3.21 口径：新增 \	est_reactor_dualstack\（IOCP reactor 同一端口 v4/v6）= 334 → 335；v3.20 口径：新增 \	173_udp6\（UDP over IPv6 回环 4 组）= 333 → 334；v3.15 口径：新增 `t170_wg_park`（WaitGroup 的 park 唤醒 4 组）= 332 → 333；v3.14 口径：新增 `t169_spin_wait`（自旋等待不被 LICM 外提 load）= 331 → 332；v3.13 口径：把 4 项"文档记着 PASS、门禁里没有"的脚本接进主回归——`gzip_http_test`（重写为自包含）、`debugger_test`、`doc_test`、`bootstrap_test --strict`（自举五级链）= 327 → 331；v3.12 口径：新增 `t168_httpc_bulk`（HTTP 客户端大响应 5 场景）= 326 → 327；v3.11 口径：新增 `[3k]` TCP 批量收发与两端超时 5 项 + `[11]` HTTP 端到端 1 项 = 302 → 308，当时记录的 SKIP=1 是 WSL 交叉验证，本机 v3.12 复跑为 SKIP=0；v3.10 及以前为 302。下面那串历史注记停在 v2.76，仅作追溯）（v2.76 口径：qlmc 差分 63 条、LSP 42 条；数字增长来自 v2.27–v2.75 期间各轨新增夹具，本轮只跑不改。v2.26 口径：qlmc 差分 35 → 37 条（新增 `s13_closure`），主回归总数不变；v2.25 口径：新增 `s12_ffi`；v2.24 口径：新增 `s11_import`；v2.23 口径：新增 `s10_defer`；v2.22 口径：新增 `s9_slice`；v2.21 口径：新增 `s8_map`；v2.20 口径：新增 `s7_aggfn`；v2.19 口径：新增 `s6_vec`；v2.18 口径：新增 `s5_enum`；v2.17 口径：新增 `s4_agg`；v2.16 口径：新增 `t143_parshard`（分片并行写 / 工作线程读共享 vec / 8 参 spawn）；v2.14 口径：新增 `[9b]` stage-1 编译器差分（`tests/qlmc_test.py`，7 条）；v2.13 口径：新增 `t141_vecindex`（vec 下标六形态）+ `test_exitcode()` 三条（`exit(运行期值)` 的退出码）；v2.12 口径：新增负向夹具 `net_serve_builtin`——reactor 搬进 std 后直接调内建 `net_serve` 必须给出迁移诊断；v2.11 那条 `.qla` 沙箱删除 FAIL 已随夹具改「就地覆盖」收口。以下为 v2.10 口径的历史记录：本版新增项 `[3j2]`：`t130_router_dispatch`（路由表 / 参数 / 404·405 / 表满）+ `http_router_test.py`（20 项真实 socket E2E）。**唯一 FAIL 是 `.qla` 目标文件用例撞沙箱的批量删除策略**（`[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]`：一次删 `build/_qlatest` 里 62 个文件，超过 50 个的阈值），与被测逻辑无关；`cache_test` 的 `build/` 争用失败本次未复现。v2.07 记录的那条 LSP FAIL 已收口（`tests/lsp_test.py` 的容错索引段改成 `std/sse` / `std/ws`（仍解析失败）负向 + `std/http` / `std/timer`（已修好）正向，内部断言 38 → 42）。SKIP 为 WSL 交叉验证，本机被沙箱拦。此前新增项：语言轨 `t97_atomic`/`t121_syncmpmc`/`t122_syncport`，工具链 `cov_test`（23 条断言）/`fuzz_test`（12 条断言）/`cache_test`（24 条断言，v1.100）/`kv_test`（10 条断言，v1.102）；语言轨 `[9] AArch64 接口 vtable`（7 用例）+ 两个跨文件接口负向夹具 + **模块系统 `modsame` 正例与 3 个多文件负例**（v1.101）） | `python tests/run_win_tests.py` |
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
| 调试器脚本化会话（v1.75） | **PASS**（18 项：断点行号/源码文本、int·bool·f64·str·struct 求值、`a.b` 字段、step/next 行推进、bt 帧链、退出码；外加调试构建与非调试构建输出逐字节相同） | `python tests/debugger_test.py`（v3.13 起在主回归 `test_debug_chain` 内） |
| DWARF v4 互操作（v1.80） | **PASS=20 FAIL=0**（CU 头 / 行表 40 条逐项 / subprogram 的 low_pc·high_pc / 变量位置多重集 / `Point` 布局 / DataDirectory[6] 为空） | `python tests/dwarf_test.py` |
| 调试器端到端命令链（v1.80） | **PASS=40 FAIL=0**（断点编号与命中计数、三种不可读语义、next/finish、bt、删除断点、程序输出与退出码） | `python tests/dbg_test.py` |
| 覆盖率链路（行 + 分支，v1.83） | **PASS=23 FAIL=0**（`cov.qma` 行 4/5、分支 1/2 且列出未覆盖分支 `8->9`；`main.qma` 行/分支双 100%；行与分支两种阈值各退出码 1；`cov2.qma` 两次运行合并后行 8/8、分支 4/4；`--lines-only` 分支显示 `0/0`） | `python tests/cov_test.py` |
| 模糊测试链路（v1.83） | **PASS=12 FAIL=0**（同 seed 逐字节一致 / 不同 seed 不同 / 变异生效且仍是合法 UTF-8 / built·rejected·bug 三分类口径 / 端到端 8 例 0 崩溃） | `python tests/fuzz_test.py` |
| doc comment 链路（v1.92） | **PASS=31 FAIL=0**（语法规则 10 / 前端挂载 6 / 工具链 14 / 产物逐字节相同 1） | `python tests/doc_test.py`（v3.13 起在主回归 `test_debug_chain` 内） |
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

### 3.5b WaitGroup 等待的 CPU 成本（`bench/wg_bench.qma`，v1.98；v3.14 重测）

同一个等待（worker 睡 200 ms 后 `wg_done`），两种等待策略各跑一遍，
`now_ns()` 量墙钟、`cpu_ns()` 量进程 CPU 时间（3 次运行区间）：

| 策略 | wall | CPU | CPU / wall |
|---|---|---|---|
| 纯自旋（v1.93 及以前 `wg_wait`） | 205–210 ms | 109–171 ms | **51–82%** |
| 三段退避（v1.98：64×`pause` → 1024×`thread_yield` → `sleep_ms(1)`） | 217–271 ms | 0–15 ms | **0–6%** |

代价是唤醒粒度：`sleep_ms(1)` 在本机（Windows 默认 15.6 ms 时钟片 + VBS）
实际约 **25 ms**，所以长等待的唤醒可能晚 25 ms（wall 那列的 217–271 ms 就是它）。
毫秒级等待（3 ms 忙任务）不会掉进睡眠段：实测 wall 5–16 ms、等待方 CPU ≈ 0。

> **v3.14 更正**：上表 v1.98 的"纯自旋"那行是**在对照组编错的情况下测的**。
> `spin_wait` 的 `while mem_load64(w,0) != 0 { spin_hint() }` 被 LICM 把 load
> 外提到了循环外（判据"循环里没有 call/store"把它当纯读循环，而 `spin_hint()`
> 发射的 `('pause',)` 读写集都是空的），编出来是**死循环** —— 所以那行数字
> 只可能来自更早的版本，或者根本没跑完过。v3.14 修掉 LICM 之后重测：
>
> | 策略 | wall | CPU | CPU / wall |
> |---|---|---|---|
> | 纯自旋（修复后） | 200 ms | 203 ms | **101%**（整核跑满，符合预期） |
> | 三段退避 | 202 ms | 0 ms | **0%** |
>
> 结论方向不变（退避把核还回去了），但**纯自旋的 CPU 是 101% 不是 51–82%** ——
> 旧数字低得不合逻辑（自旋等待本就该吃满一个核）。修 bug 顺带纠正了这个口径。
> 修复与夹具见 `versions/v3.14/CHANGELOG.md`、`tests/t169_spin_wait.qma`。

#### 3.5b.1 唤醒延迟：`sleep_ms` 片 → `WaitOnAddress` park（v3.15）

上表第 3 段退避是 `sleep_ms(1)`，本机实际 **15.6–25 ms**，长等待的唤醒要等
一整个时钟片。v3.15 换成 `WaitOnAddress`（KernelBase.dll）。

**测法**（`build/probe_wake2.qma`，未入库）：worker **忙等**到精确时刻再
`wg_done`，把 `wg_done` 前的 `now_ns()` 记进静态字；等待方醒来后与之相减，
得到真正的唤醒延迟。200 ms 等待，新旧两版**交替**各 7 次：

| 实现 | min | median | max |
|---|---|---|---|
| 旧（`sleep_ms(1)` 片） | 292 µs | **1194 µs** | 1824 µs |
| 新（`WaitOnAddress`） | 24 µs | **55 µs** | 74 µs |

**中位 21.7×**，最大抖动 1824 → 74 µs；CPU 两者都归零（`bench/wg_bench.qma`
仍是 0%）。

> **探针踩过的坑**：第一版让 worker `sleep_ms(ms)` 再算 `wall - ms`，测出来
> park 反而"慢 2 倍"。真因是 **Windows 的 sleep 粒度 15.6 ms 把被测的
> 唤醒延迟整个淹掉了** —— 量到的是 sleep 抖动。**测 µs 级的东西，夹具里
> 不能出现 ms 级的定时器。**

**两段负结果（都记在 `versions/v3.15/CHANGELOG.md`）：**

| 尝试 | 结果 | 结论 |
|---|---|---|
| 给 `mutex_lock` 也用 park | 16 线程 × 20 万次加锁 **281 → 1568 ms（慢 5.6×）**；加「先 yield 1024 次」门槛后仍 855 ms | 锁的临界区约 88 ns，「已经等多久」这个代理判据区分不了「马上就好」与「要等很久」。**park 只对"等待 ≫ 系统调用开销、且只等一次"有利** |
| 给 `wg_done` 加「有人在睡才 Wake」的 parked 计数 | **漏唤醒**，lag ≈ **953 ms**（睡到 1000 ms 兜底超时） | 「登记」与「检查」是两次独立原子操作，窗口关不掉；Win32 没有把「减计数 + 检查 + Wake」做成原子事务的原语。改成无条件 Wake |

#### 3.5b.2 park 拆成 `std/park`、改为注入式（v3.16）

v3.15 把三条 `@ffi` 直接写进 `std/sync`，**打红了 native/arm64 编译** ——
`@ffi` 只在 Windows PE 后端实现，于是 `tests/t122_syncport.qma` 在
`--target native` / `--target arm64` 上都是声明期 SyntaxError，而 CI 的
`run_native_tests.sh [7]` 正是编它到 A64 再在模拟器里跑。

v3.16 把 `@ffi` 与 `_park` 整体搬到 **`std/park`**（只编 Windows PE），
`std/sync` 回到零 `@ffi`、跨平台可编译；park 由调用方
`sync_set_park(park_on, wake_all)` **显式注入**（两个 `static_word` 存函数指针）。
不注入时 `wg_wait` 第 3 段退回 `sleep_ms(1)`，语义正确、只是唤醒晚一个时钟片。

**收益仍在**（`build/probe_wake3b.qma`，200 ms 忙等，交替各 7 次；
这次对照组是**不注入的 `wg_wait`**，而 v3.15 的对照组是手写的 `wg_wait_old`）：

| 模式 | min | median | max |
|---|---|---|---|
| 不注入（纯退避） | 64 µs | **622 µs** | 1488 µs |
| 注入 park | 30 µs | **44 µs** | 102 µs |

**中位 14×**。与 v3.15 记的 21.7× 的差异在噪声范围内（§3.50：本机分辨率 ±20%），
**量级结论不变**：park 把唤醒从"一个时钟片"降到几十 µs。

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
`python tests/bootstrap_test.py --strict` **五级全 PASS**（v3.13 起由主回归
`test_qlmc` 每轮执行，不再是"有人记得手工跑才存在"）。
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

### 3.57 内联阈值 28→60（v2.93）：b8_threads4 −37%、b5 −21%、b9 −14%

`opt_inline` 的阈值判据是 **降级后的 IR 条数**，不是源码行数。而循环降级很重：
`while go == 1 && p < n { ... }` 源码 5 行、降级 43 条。于是 b9_json 每解析一个
token 就要调一次的 `jws`（43 条）、`jstr`（35 条）**永远进不了内联**。

本机 x86-64，同轮对 C（min of 3）：

| 基准 | v2.92 | v2.93 | 变化 |
|---|---|---|---|
| **b8_threads4** | 378.8 | **239.0** | **−37%** |
| **b5_string** | 131.4 | **104.4** | **−21%** |
| **b9_json** | 92.4 | **78.7** | **−15%** |
| **b6_hash** | 93.9 | **83.0** | **−12%** |
| b7_sort | 97.2 | 95.8 | −1% |
| b1_int / b2_float / b3 / b8_threads1 | — | — | 0 |
| b4_array | 64.8 | 79.6 | **+23%**（寄存器压力） |

校验和 10/10 一致。产物体积不变（hello / http_demo 逐字节同大小）。

**代价是 b4_array +23%**：更大的函数体让寄存器压力上升、溢出槽变多。没回退，
因为 b8/b5/b9 的收益比它大一个量级；正解是按热度分档（热函数 60、冷函数 28），
已登记为下一步。

这一版真正的工时不在阈值，而在它**暴露的两个隐藏缺陷**：

| 缺陷 | 症状 | 根因 |
|---|---|---|
| LICM 外提内联副本的 `load` | `t22_map` 在阈值 38 起 SIGSEGV | 内联重编号 vreg 后，"base 本循环内不变"**偶然成立**，load 被提到不属于它的循环外 |
| `floatv` 标记未搬 | `AttributeError: 'dict' object has no attribute 'add'` | `floatv` 是 vreg→`'f32'/'f64'` 的 **dict**，不是 `strv`/`boolv` 那样的 set |

第一条的定位用三级二分：`git stash` 确认引入 → 扫阈值定位到 34/38 之间 →
`QLM_SKIP_PASSES` 逐个跳 pass，**只有跳 `opt_licm` 才恢复**。

修复时踩过一个坑：先用"给指令元组加第 5 位标记"，**失效**——中间 pass 会按
4 元组重建指令，标记被悄悄丢掉。改用调用方身上的集合才生效。**指令元组的形状
是下游共同依赖的契约，不要往上加字段。**

### 3.58 chunked 请求体（v2.95）：`std/http` 不再回 501

gaps §2 的 "chunked 请求体 | 回 501" 收口。解码抽成**纯内存模块**
`std/http_chunk`（`chunk_scan` / `chunk_pack`，输入只是"缓冲区 + 区间"），
所以 Linux CI 第一次能真跑 chunked 语义（`tests/t158_chunk.qma` native 执行
全过；win 由 `case_selfcheck` 跑同一份夹具；arm64 编译级）。

就地向前压缩的安全性：每个 chunk 占 `hex行+2+size+2` 而写游标只前进 `size`，
恒有 `src − (dst+size) ≥ 6`——写区永远追不上读区，头块不碰。

口径（RFC 7230）：chunk-ext 与 trailer 丢弃；**TE 与 Content-Length 同时
出现以 TE 为准**（守卫双向——CL 行排在 TE 之后也会把刚清的 `HP_BLEN` 写回去，
E2E 正反两种头序都覆盖）；病态流 400，绝不"尽力解一半"。handler 零感知：
`http_body_len` 读到的是解包后的真实体长。

顺带修 C 后端 `cstr()` **漏转义 `\r`**：任何含 CR 的字符串字面量生成的 C
直接非法（`missing terminating " character`）——与 v2.90 `args()`、v2.91
`structlit` 同族："两条实现路径各写一份，一份跟上、一份没跟上"。

回归：`run_native_tests.sh` **PASS=108 FAIL=0**；lexdiff 310/313、
parsediff 214/214（新夹具全过自举前端）；E2E `http_router_test.py` 20→26 条
（Windows-only 通道，待真机）。

### 3.59 `__vec_grow` 禁止内联（v2.96）：b4 −20%，收掉 v2.93 的 +23%

v2.93 登记的 "b4_array +23%" 代价定位到了具体函数：`__vec_grow`
（18 条 IR，判满→realloc→memcpy 搬旧数据，稳态下 2M 次 push 只有几次真的进）
被阈值 60 放进每个 push 调用点的**热循环**。LICM 探针实测：内联后 b4 的
push 循环区域 17 → 98 条 IR、load 3 → 12 条、`readonly` 转 False。
`no_inline=True` 一个标记收口——**要按冷热路径分档，不是按热度**。

三臂交错 A/B（min of 5，每臂带生效探针逐臂验证）：

| grow | memcpy | b4 | b9 |
|---|---|---|---|
| 不内联 | 内联 | **67.3** | **76.1** |
| 不内联 | 不内联 | 67.7 | 76.0 |
| 内联 | 不内联 | 83.7 | 76.1 |
| 内联 | 内联（v2.93 原状） | 83.9 | 78.9 |

b4 的 20% 全部跟着 grow 列走；memcpy 列基本无关（b9 的 3.7% 只在两者都内联
时出现）→ 只 ban grow。同轮对 C（min of 3）：**b4 对 C 1.95× → 1.57×**。

这版的测量教训比收益大：第一版 A/B 工具的"什么都不做"臂**没撤销源码里
已加的 ban**，两臂实际同配置、测出 delta≈0，差点把正确方向判死。之后每臂
都必须带生效探针（查 `main.inlined_from`）才算数。
详见 `versions/v2.96/CHANGELOG.md`。

### 3.60 内置 TLS 根证书库（v2.97）：能验链之后，第一次"知道该信谁"

`x509_verify_chain` 的锚参数一直留给调用方——对真实 HTTPS 客户端这是结构性
缺口：tls_client 握手路径里没有任何东西能提供锚。`std/x509roots` 把 12 个
主流根 DER 内联（Debian bookworm ca-certificates 同源提取，2026-10-28），
DN 逐字节配对 + `x509_verify_stored` 一键验证；配套把 `x509_subject/issuer/is_ca`
转 pub。`tests/t159_roots.qma` 在 native 上真验两条当天抓的公网链：

| 项 | 结果 |
|---|---|
| pypi.org / www.apple.com 两链验到表内锚 | **通过**（全程 RSA-SHA256） |
| 域名不符 / 篡改叶证书 | 拒绝 |
| 12 根自验证 | **5/12 通过**，其余 7 个是 P-384/SHA-384/SHA-1，现有栈验不动 |

写库前的五站点普查钉死了覆盖面（这是 v2.98 的验收清单）：

| 站点 | 每一环签名 | 现有栈 |
|---|---|---|
| pypi.org / apple.com | RSA-SHA256 | **通** |
| deno.com（Let's Encrypt YE2→Root YE→X2）、cloudflare（GTS WE1→R4） | **ECDSA-SHA384/P-384** | ✗ |
| microsoft.com | RSA **SHA-384** | ✗ |

所以本版不吹"HTTPS 全自动"：锚的问题收了，**SHA-384/P-384 是下一个结构性
缺口**，登记在 gaps §2 TLS 行。`examples/https_get.qma` 暂不接根库——
example.com 链的桥锚（AAA Certificate Services）不在表内，硬接会造出一个
"验不过的示例"。

### 3.61 parfor 归约的概率性错误（v2.98）：一次 clone 返两次，store 却只该返一次

`examples/parfor_sum.qma` 有 ~7% 概率算错，差值**恒等于一个 chunk 的和**。
根因：`clone()` 一次返回两次（父得子 pid、子得 0），父子从**同一条指令流**
继续；而 `store pid_gid[t]=pid` 写在**分流之前**，子线程于是把父写的真 pid
覆盖成 0。join 阶段 `wait4(0)` 是"收任意子进程"——先退出的别的 worker 被这个
槽收走，轮到它自己的槽时已无子可等（`wait4` 立刻返回，代码未检查），归并读到
一个**还在跑**的 worker 的 `out[t]`（0）→ 少一个分片。

| 项 | 结果 |
|---|---|
| 修复后压测 | **0 / 500** |
| 旧二进制对照（同机同形状） | **22 / 300 = 7.3%** |
| 同型审计 | `spawn` / `thread_start` 分流前只写新栈私有槽，无此问题；A64 无线程、win 走 CreateThread 无 fork 语义 → 仅 x86-64 POSIX parfor 一处 |

**为什么长期潜伏**：单次回归只有 ~7% 概率出错，而每次发版只跑一次——
93% 的把握判绿而实际是红的。本版给 `[4]` 加了 10 连跑哨兵（检出率抬到 ~20%，
代价 ~20 s）。教训：**概率性错误不能用单次绿证明修好**。

### 3.62 ECDSA P-384 / SHA-384（v2.99）：根库从"有表"变成"能用"

v2.97 的根库只有 5/12 能自验证，公网主流链整条验不过。根因不是"缺一条曲线"，
而是**摘要算法与密钥曲线被错绑**——`_x509_link` 之前按签发者密钥宽度选摘要
（P-256→SHA-256、RSA→SHA-256），而真实链上大量存在：

| 证书 | 公钥曲线 | 签名算法 |
|---|---|---|
| deno.com 叶 | **P-256** | **ecdsa-with-SHA384** |
| Google WE1 | **P-256** | **ecdsa-with-SHA384** |
| Let's Encrypt YE2 | P-384 | ecdsa-with-SHA384 |

改成按**子证书的 signatureAlgorithm** 选摘要、曲线仍看签发者密钥，并按
FIPS 186-4 §6.4 取摘要最左 n 位（P-256 配 SHA-384 取左 32 字节）。这是
本版最关键的一行。再补 `std/p384`（12 limb Montgomery + Jacobian，结构与
p256 逐函数对应）与 `rsa_verify_pkcs1_sha384`（DigestInfo 前缀参数化）。

| 项 | 结果 |
|---|---|
| 12 根自验证覆盖 | **5/12 → 11/12**（仅剩 Certum 的 SHA-1，RFC 9155 已弃用） |
| t160：P-384 向量 + 6 类负向 | **p384 ok**（向量由 Python 纯 bigint 独立算出，两侧走完全不同的代码路径） |
| t161：deno/cloudflare 两条真实链 | **p384chain ok**（四层到自签根 + 缺中间证书/域名负向） |

一次误判值得记下：t161 第一版拿 **Root YE 当锚**，失败后我怀疑 P-384 实现，
排查了几轮 TBS/公钥编码，最后靠 openssl + 独立 Python 双向确认"输入全对、
算法也对"——真相是 **Root YE 由 ISRG Root X2 签发，不是自签根**，拿它当锚
本来就不成立。**验证失败先怀疑输入、再怀疑算法**：输入是否符合协议可以被
外部工具独立裁判，实现有没有 bug 不能自证。

### 3.63 TCP 接收超时（v3.08）：从"永久阻塞"到"按毫秒返回"

`recv_all` 的停止条件只有对端 FIN。对端发一半就挂着不关时，阻塞 `recv()` 不会
返回，循环也不会退出。这不是理论问题，是实现里唯一的退出路径。

**改前**（`build/probe_hang.qma`：worker 发 17 字节后 `sleep_ms(60000)` 保持连接）：

| 命令 | 结果 |
|---|---|
| `timeout 12 ./build/probe_hang.exe` | **退出码 124**（12 s 被外部杀掉，程序自己不会返回） |

**改后**（`tests/t165_recvtimeout.qma`，同一台机器，Windows PE）：

| 场景 | 输入 | 结果 |
|---|---|---|
| 半开连接 | 对端发 16 字节后 sleep 3 s | `recv_all_to(c, 4096, 1000)` 返回 16 字节，耗时 ~1.0 s（断言区间 900–5000 ms） |
| 短读 | 对端只发 3 字节，要 100 | `recv_exact_to(c, 100, 8, 800)` 返回 `"abc"`（len 3） |
| 正常关闭 | 对端发完即关 | `recv_all_to` 读到全部，路径不受影响 |
| 整轮墙钟 | 3 场景串行（含两次 `sleep_ms(3000)`） | **6.27 s**，退出码 0 |

主回归：`python tests/run_win_tests.py` → `PASS=302 FAIL=0 SKIP=1`（SKIP 是 WSL 交叉验证）。

超时机制的边界：粒度是**每次接收**而不是总时长；`ms <= 0` 退化为非阻塞探测，
此时"超时"与"对端关闭"都表现为空串。

### 3.64 批量接收 O(n²) → O(n)（v3.09）：4 MB / 4 KB 分块从堆爆到 75 ms

接收侧六个函数原来是 `out = out + part` —— 每轮复制**已累计的全部数据**，
总拷贝 ≈ n²/(2·chunk)。分块越小越糟，而 v3.08 新加的 `*_to` 默认分块正好是 4096。
v3.07 在发送侧踩过同一个坑（`str_ptr` + `tcp_send_n` 零拷贝），接收侧当时没跟上：
`t164` 用的分块是 65536，只有 64 轮、累计复制 128 MB，在 512 MB 上限下"看起来正常"。

改法：缓冲区累积（一次分配 + 翻倍扩容 + 原地 `mem_copy` + 末尾 `mem_str` 一次成串）。

**本机 Windows PE，`build/probe_recv*.qma`，各 3–5 次：**

| 形状 | 改前 | 改后 |
|---|---|---|
| 4 MB / **4 KB** 分块 | **`heap_limit_mb exceeded`（跑不完，退出码 1）** | **57 / 65 / 70 / 75 / 80 ms**（中位 75） |
| 4 MB / 64 KB 分块 | 187 / 191 / 225 ms（中位 191） | 72 / 78 / 80 / 83 / 90 ms（中位 80） |
| `t166` 全链（5 场景，约 13 MB 传输） | — | **0.45 s**，退出码 0 |

64 KB 那行是同一形状的公平对照（**2.4×**）；4 KB 那行不是"慢"而是**跑不完**。

**同版修掉的两处"证据型"缺陷：**

| 缺陷 | 症状 | 处置 |
|---|---|---|
| 死循环告警对**复合条件**误报 | `while limit <= 0 \|\| got < limit` 报 `guard variable never updated`（只看 header 后第一条 `jcc`，把 `limit` 当 guard） | 判据改成"整段 guard 的变量都没被写过"（跨 `label` 收集最多 8 条 `jcc`）；真阳性探针仍报、复合条件不报 |
| `http_router_test.py` R10 用例数据错 | 声明 7 字节实发 8 字节 → 服务端按 RFC 7230 判 400（判得对） | 用例改成补 2 字节；该文件从 1 项红变 `http_router ok（26 项断言）` |

R10 这项红了 4 个版本没人发现，原因是 **`http_router_test.py` 不在主回归里**
（要编译 `examples/http_router.qma` 并占 8092 端口）。接进主回归需要处理端口
占用与起停时序，留作单独一轮，见 `07-gaps.md` §3。

### 3.65 TCP 发送超时（v3.10）：`SO_SNDTIMEO` 不管用，只能自己等可写

发送侧的对称缺口：`send_all` 里的 `tcp_send_n` 是阻塞 `send()`，对端不读时缓冲区一满
就再也不返回。**改前**（`build/probe_sendloop.qma`：循环发 1 MB，对端全程不读）：

| 命令 | 结果 |
|---|---|
| `timeout 12 ./build/probe_sendloop.exe` | **退出码 124**（12 s 被外部杀掉，程序自己不会返回） |

### 负结果：`SO_SNDTIMEO` 在 Win32 上对零窗口无效

第一版照抄接收侧的 `setsockopt(SO_RCVTIMEO)` 写法，换成 `SO_SNDTIMEO`（`0x1007`）：

| 实验 | 结果 |
|---|---|
| `ms = 200` | 窗口满后 `send` 挂住，不返回 |
| `ms = 5000` | 挂 **40 s+**（外部 `timeout` 杀掉） |
| 对照：同一套发射代码的 `SO_RCVTIMEO`（接收侧） | 1.0 s 按时返回（v3.08 已验） |

参数与常量都按文档传的，问题在 Win32 传输层：零窗口挂起后它会自己重试，不看这个
选项。**这条实现被整条废掉**（留一个"看着像超时、其实不超时"的 API 比没有更糟）。

### 改成「先等可写、再发」

每轮先用 `select`(Windows) / `poll`(Linux) 等 `ms` 毫秒，可写了再 `send`——阻塞
socket 只在"连 1 字节都进不去"时阻塞，于是 `send` 写一部分就返回。

| 场景 | 结果 |
|---|---|
| 对端不读，循环发 1 MB / 200 ms | `iters=1 total=1048576 short=1 ms=200`（第二次发送等满 200 ms 后短写） |
| `t167` 全链（4 组，含 1 MB 正常路径） | **3.27 s**，退出码 0，连跑 3 次稳定 |
| 窗口满时单次 `send_to` | 返回 **0**，耗时 ∈ [250, 5000) ms |

两个平台的布局差异（`fd_set` vs `pollfd`、Windows `timeval` 是两个 4 字节 long 而不是
两个 8 字节）见 `versions/v3.10/CHANGELOG.md`；`select` 另需登记进 `ws2_32` 白名单，
否则是加载期 `ENTRYPOINT_NOT_FOUND`。

### 3.66 HTTP 客户端接收大响应（v3.12）：两层 O(n²) 合成一个，2 MB 堆爆 → 8 MB 45 ms

`std/net` 的接收函数在 v3.09 已经改成缓冲区累积，但 `std/httpc_net` 的接收循环
**原封不动地留着同一个形状**，而且是两层：

```quelmara
buf = buf + part                        // ① 每轮复制已收到的全部字节
let r = httpc_parse_response(buf)       // ② 每轮把整段缓冲区从头重解析
```

`_dechunk` 内部还有第三层（每块 `r.body = r.body + slice(...)`）。

**本机 Windows PE，`build/probe_httpc_one.qma`（Content-Length 响应，16 KB 分块）：**

| 响应大小 | 改前 | 改后（3 次） |
|---|---|---|
| 512 KB | 21 ms | 5 / 5 / 5 ms |
| 1 MB | 70 ms | 13 / 4 / 17 ms |
| 1.5 MB | 141 ms | — |
| **2 MB** | **`heap_limit_mb exceeded`（退出码 1）** | 22 / 8 / 25 ms |
| 4 MB | — | 36 / 30 / 32 ms |
| 8 MB | — | 45 / 43 / 47 ms |

1 MB → 2 MB 是 70 → 141 ms（**翻倍**），2 MB 直接撞 512 MB 堆上限（累计复制约 256 MB，
再加扩容瞬间新旧缓冲并存）。改后 1 MB → 8 MB 是 6 → 45 ms，线性。

**chunked 路径（`build/probe_ck_big.qma`，8 KB 一块）：**

| 响应大小 | 改后（3 次） |
|---|---|
| 1 MB | 10 / 12 / 12 ms |
| 2 MB | 28 / 14 / 20 ms |
| 4 MB | 41 / 33 / 30 ms |
| 8 MB | 41 ms |
| 16 MB | 112 ms |

改后两者都受网络与内存带宽支配，噪声 ±40%（与 §3.50/§3.51 的口径一致：
**只有结构性证据可靠，绝对值不可横比**）。

**这个缺陷活了 4 个版本**，原因与 §3.64 的 R10 同源但更细：老用例 `t92_httpc`
的响应是 **12 字节**（`hello httpc!`）与 **10 字节**（chunked），轮数根本不够
暴露累积成本。**"被验证"还要看用例形状够不够极端** —— v3.09 的教训是
"验证 O(n²) 要用最坏形状（最小分块 + 最大负载）"，这里是它的镜像：
**验证增量状态机要用跨 recv 边界的形状**（第一版把 8 KB 块搬错，7 字节的
t92 全绿也看不出来，见 `versions/v3.12/CHANGELOG.md`）。

回归夹具 `tests/t168_httpc_bulk.qma`（5 场景：CL 1 MB / CL 4 MB / chunked 1 MB /
chunked 4 MB / CL 短读）已接进主回归。**对老代码是红的**：stash 掉修复重编，
`heap_limit_mb exceeded`、退出码 1。

### 3.67 两个性能候选的负结果（v3.17）：`@simd` 放弃 XMM 与 `tls_net` 的 O(n²)

`07-gaps.md` §5 剩两条"看起来该修"的候选，v3.17 逐条实测，**都没测出值得付的收益**。

**(a) `@simd` 函数整体放弃 XMM 分配**（`qlm_native.py` 的 `_xmm_candidates`
里 `return set()`）。探针 `build/probe_simd_xmm2.qma`：两个同形函数各持
**8 个 f64 累加器**（GPR 池只有 5 个变量寄存器，必然溢出；XMM 池有 10 个）、
跑 10 万轮 `a = (a*y+1.5)/2.25`，唯一差别是一个含 `@simd` 归约：

| 轮次 | with_simd（放弃 XMM） | no_simd（正常 XMM） | 比值 |
|---|---|---|---|
| 1 | 3564 µs | 3601 µs | 98% |
| 2 | 3557 µs | 3668 µs | 96% |
| 3 | 3907 µs | 3905 µs | 100% |

**噪声内**（§3.50：本机分辨率 ±20%）。原因不是探针写错：IR 层面两者
`fbin f64` 数量几乎相同（**111 vs 110**），"放弃 XMM"只影响寄存器分配阶段；
而这条依赖链的瓶颈是**除法 15 周期**，帧槽访存被掩盖。

**(b) `std/tls_net` 两处 O(n²)**（`tls_recv_exact` 第 40 行、`tls_connect`
第 74 行）。探针 `build/probe_tls_recv.qma` 复刻同一形状：

| n | 耗时 |
|---|---|
| 16 KB | **0 ms** |
| 64 KB | **0 ms** |
| 128 KB | **0 ms** |
| 256 KB | **2 ms** |

**262 KB 已是 TLS 最坏情况**（记录上限 16 KB+256、握手 ≤16 轮），2 ms 可接受。
对比 v3.12 修的 `httpc_net`（**2 MB 就堆爆**），差三个数量级 ——
**"形状像"不等于"代价大"**。

两条都改成"实测负结果 + 重启条件"，**不动代码**。
Linux futex 查下来被**语言层缺能力**挡住（`syscall` 不是用户可调内建、
语言没有条件编译），见 `07-gaps.md` §4。

### 3.68 用户可调的 `syscall` 内建（v3.18）：Linux 侧地基补上

v3.17 查 Linux futex 时发现三堵墙，第一堵是「`syscall` 只是编译器内部的发射指令，
用户发不了系统调用」。v3.18 补上内建 `syscall(n, a0..a5) -> int`：

| 项 | 语义 |
|---|---|
| 调用号 | **必须是编译期常量**（内核在 `rax`/`x8` 读它；笔误要在编译期抓） |
| 实参 | 最多 6 个（不足补 0） |
| 返回 | 内核**原样**返回值；**负值即 `-errno`**，不置 errno、不抛异常 |
| 平台 | **仅 Linux**；Windows 编译期 fail-fast（用户态不能直接发 `syscall`） |

寄存器约定：x86-64 `rax`+`rdi/rsi/rdx/r10/r8/r9`；AArch64 `x8`+`x0..x5`。

**执行级验证**（`tests/t171_syscall.qma`，接进 CI linux job 的 `[7]` 段）：

| 组 | 内容 | 结果 |
|---|---|---|
| `[1]` | `getpid`（x64=39 / a64=172） | 返回 > 0 且两次一致 |
| `[2]` | `write`（x64=1 / a64=64） | 返回字节数 == `len(msg)` |
| `[3]` | 非法编号 9999 | **返回负值**（`-ENOSYS`），不崩溃 |

x86-64 直接跑 → `syscall ok`；AArch64 走模拟器 → `syscall ok`。

**顺带修正 `tests/a64_emu.py`**：未实现的调用号原来 `raise RuntimeError`，
两个问题 —— ① 与内核语义不符（内核返回 `-ENOSYS`），`t171` 的 `[3]` 组会假红；
② 更隐蔽：**同一编号在不同架构上是不同的调用**（`202` 在 x86-64 是 `futex`、
在 AArch64 是 `accept`），按 x86 编号写的探针在 A64 模拟器上撞进来时，
抛异常会让人误判成模拟器缺陷。改成一律返回 `-ENOSYS`。

**仍有的限制**（`07-gaps.md` §5）：编号**架构相关**而语言**没有条件编译**，
同一份源码没法自动选对编号。futex 本身仍未做 —— 本版只补地基。

### 3.69 编译期目标探测 + Linux futex park（v3.19）

v3.18 补了 `syscall` 之后，Linux futex 只剩"编号架构相关"一条障碍。
v3.19 加两个**编译期常量**内建：

```quelmara
target_os()   -> 1 = Linux / 2 = Windows
target_arch() -> 1 = x86_64 / 2 = aarch64
```

**折叠证据**（`--dump-ir`，同一份源码两个目标）：

| 目标 | IR 里的比较 | 运行期调用 |
|---|---|---|
| `--target win` | `('jcc', 'ne', ('imm', 2), ('imm', 2), ...)` | 无 |
| `--target arm64` | `('jcc', 'ne', ('imm', 1), ('imm', 2), ...)` | 无 |

`__str_from_i64` 的参数直接是 `('imm', 2)` / `('imm', 1)` —— 常量已折叠，
不是运行期算出来的。

**它们不是条件编译**（实测）：`@ffi` 在 ELF 后端是**声明期**硬失败，
`if target_os() == 2 { ... }` 守卫救不了声明本身。所以跨平台 park 只能拆文件：

| 文件 | 后端 | 实现 |
|---|---|---|
| `std/park` | 仅 Windows PE | `WaitOnAddress`（`@ffi`） |
| `std/park_linux` | 仅 Linux | `futex(2)`（`syscall`） |

同一组 API（`park_available` / `park_on` / `wake_all` / `wake_one`），
调用方按目标 import。

**顺带发现 `irdiff` 契约要扩展**：加完这两个内建后，任何用它们选常量的源码
都会被判 IR 分叉（两个后端返回不同立即数）。这不是 bug —— `irdiff` 原本只
归一化 `syscall` 编号（"唯一允许的架构差异"），现在多了一类。新增
`TARGET_IMM_RE` **只匹配特征形态**（`jcc` 里两个 `imm` 做 `ne`/`eq` 比较）。
四条单元判据确认没过度归一化：target 形态相同 ✅ / 普通常量仍可分叉 ✅ /
变量比较不受影响 ✅ / syscall 归一化未退化 ✅。

| 命令 | 结果 |
|---|---|
| `build t172_park_linux --target native` | 编过（16617 B，ELF x86_64） |
| `build t172_park_linux --target win` | **编译期 fail-fast** |
| `python tests/irdiff.py` | **PASS=108 FAIL=0 SKIP=92** |
| `python tests/run_win_tests.py` | **PASS=333 FAIL=0 SKIP=0** |

**`t172` 只接 CI linux job 的 x86-64**：AArch64 没有 `spawn`，
而 park 验证必须有第二个线程唤醒。是能力边界，不是遗漏。

### 3.70 UDP over IPv6（v3.20）：`AF_INET6` 在 Windows 是 23 不是 10

`std/net/udp` 的四个内建全按 IPv4 构造（`sockaddr_in` 16B、地址 u32 网络序），
v6 需要 `sockaddr_in6` 28B + 16 字节地址。新增五个内建 + `std/net/udp6`：

| 内建 | 说明 |
|---|---|
| `udp_open6()` | `AF_INET6` + `SOCK_DGRAM` |
| `udp_bind6(fd, port)` | 28B `sockaddr_in6`，地址 `::` 通配 |
| `udp_sendto6(fd, addr_ptr, port, data)` | `addr_ptr` 指向 16 字节大端地址 |
| `udp_recvfrom6{,_to}` | 源地址丢弃；`_to` 超时返回**空串** |

**执行级验证**（`tests/t173_udp6.qma`，主回归 `[3k]` 段之后）：

| 组 | 内容 | 结果 |
|---|---|---|
| `[1]` | `udp_open6` + `udp_bind6` | fd ≥ 0 / 0 |
| `[2]` | `::1` 回环收发 | 发 10 字节，收回内容一致 |
| `[3]` | 非法地址 | `udp_send6` 返回 **-1** |
| `[4]` | `udp_recv6_to(fd, 512, 100)` | 约 100 ms 返回**空串** |

**三个静默失败（每个都真实卡了一次）**：

| 坑 | 症状 | 根因 |
|---|---|---|
| `sin6_family` 写死 10 | `bind` 返回 **-1**，不报错 | Windows 的 `AF_INET6` = **23**、Linux = 10。`__udp_open6` 分叉了、`udp_sin6` 没有 |
| `__net_fail_<tag>` 未定义 | 链接期 `KeyError` | `net_fail` 只 emit `call __net_fail_<tag>`，标签要手工在运行库定义；原来只有 3 个 |
| `recvfrom` 返回 `buf` | 内容错位 | str 的值必须指向**数据起点**（`buf+8`），长度头在前 8 字节 |

**都不是崩溃，是"返回错误值"** —— 内建层的隐式契约没有编译期检查，
所以 `t173` 必须做**真实回环收发**，不能只验"能编过"。

### 3.71 reactor 双栈（v3.21）：`WSASocketW(2, ...)` → `(23, ...)`

`std/net/reactor.qma` 的监听 socket 原来是 `WSASocketW(2, ...)`（AF_INET）+
16 字节 `sockaddr_in`，只接 v4 —— 所有跑在 reactor 上的东西（`std/http` 的
路由/中间件、`http_router`、ws/sse）都继承这个限制。

改成双栈：

| 项 | 值 | 说明 |
|---|---|---|
| `WSASocketW` family | **23** | Windows 的 `AF_INET6`（Linux 是 10 —— v3.20 刚在 UDP 上踩过） |
| `IPV6_V6ONLY` | level 41 / opt 27 / 值 **0** | Windows 默认 **1**（只接 v6），必须显式置 0 |
| `sockaddr_in6` | **28 B** | `sin6_addr` 全零 = `::` 通配 |

**执行级验证**（`tests/reactor_dualstack_test.py`，主回归 `[11]` 段）：

| 组 | 内容 | 改造前 | 改造后 |
|---|---|---|---|
| `[2]` | IPv4 `127.0.0.1` | 200 OK | 200 OK |
| `[3]` | **IPv6 `::1`** | **`WinError 10061` 连接被拒** | **200 OK** |

**夹具对旧代码是红的**（stash 掉 `reactor.qma` 重编实测），不是"跑通就行"。
`http_router_test.py` 的 25 项断言在改造后全过 —— 双栈没破坏任何路由语义。

**遗留**：`tcp_listen6`（发射层）与 reactor（std 源码）现在是**两套独立的
双栈实现**，`23/41/27/28` 这几个值在两边各写一遍，**没有共享常量** ——
改一处忘另一处就会分叉。这是 v2.12「reactor 搬进 std」的遗留。

### 3.72 双栈下的 `peer_ip`（v3.22）：补上 v3.21 留下的空白

v3.21 把 reactor 改成 `AF_INET6` 双栈后，**所有连接的对端地址都以
`sockaddr_in6` 返回**（family = 23），IPv4 客户端表现为 `::ffff:a.b.c.d`。
`std/net/addr` 的 `addr_text` 里有还原逻辑（v2.07 写的），但那段代码
**此前只在 v4-only socket 上跑过** —— `fam == 23` 那个分支根本没被走过。
如果它错了，症状是所有 IPv4 客户端在访问日志里显示成 `::ffff:127.0.0.1`，
基于 IP 的限流/白名单全部失效。**不会崩、不会报错。**

`tests/t174_peer_ip.qma` 两层验证：

| 层 | 组 | 内容 | 判据 |
|---|---|---|---|
| 端到端 | `[1]` | IPv4 客户端连双栈 `listen6` | `peer_ip == "127.0.0.1"` 且不含 `::` |
| 端到端 | `[2]` | IPv6 客户端 | `peer_ip == "::1"` |
| 端到端 | `[3]` | 端口 | `> 0` 且 `!= 监听端口` |
| 纯函数 | `[4a]` | `fam=23` + `::ffff:127.0.0.1` | `"127.0.0.1"` |
| 纯函数 | `[4b]` | `fam=23` + `::1` | `"::1"` |
| 纯函数 | `[4c]` | `fam=2` + `10.0.0.5` | `"10.0.0.5"` |
| 纯函数 | `[4d]` | `fam=23` + `2001:db8::1` | **不误判成点分** |

`[4d]` 是关键负向：`2001:0db8:...` 前 10 字节恰好不是全零，所以不会误判；
但如果有人把判据从"前 10 字节全零"简化成"看最后 4 字节"，
它就会变成 `0.0.0.1`。这条钉住它。

**结论：v2.07 的还原逻辑是对的**，本轮没改实现 —— 只把它从
"没被验证过的代码"变成"有夹具钉住的代码"。实测输出：
`v4_ip=127.0.0.1 v4_port=51357` / `v6_ip=::1 v6_port=51358`。

**顺带发现一个真隐患**：夹具第一版为跨线程传字符串长度借用了
`static_word(120..123)` —— 那是**越界写**。`static_word` 的实现是
`i << 3` 加到静态区基址、**没有上限检查**，而静态区只有 32 个字。
改成 `mem_alloc` 堆块后正常。这条已记进 `07-gaps.md` §4.2，
v3.23 连同"槽位登记表"一起收了（见 §3.73）。

### 3.73 `static_word` 槽位全满（v3.23）：33 个需求 vs 32 个槽位

v3.22 记下的越界隐患只是症状。真去查的时候发现更严重的事：
**32 个槽位已经被标准库全部占满，而且四处抢槽。**

要数清占用，光扫 `static_word(\d+)` 是不够的 —— 会漏掉三层间接：

| 层 | 例子 | 只看字面量的结果 |
|---|---|---|
| 注释 | `const _SINK_W = 13  // static_word(13) = ...` | 把说明文字当成占用 |
| 常量 | `static_word(_SINK_W)` | 完全看不见 |
| 辅助函数 | `_get(w)` → `static_word(w)`，槽位在调用点 `_get(_SINK_W)` | 完全看不见 |

三层都解析之后，真实需求是 **33 个**（logfile 11 + log 9 + timer 2 +
sync 2 + 协议库共享通道 1 + 其余 6 + http 2），而槽位只有 32 个。
所以冲突不是"谁写错了号"，是**装不下**：

| 槽位 | 抢槽 | 后果 |
|---|---|---|
| 13 / 14 | `std/log` ↔ `std/timer` | **静默崩溃**（实测） |
| 15 | `std/log` ↔ `std/net/reactor` | 日志打乱 reactor 状态块指针 |
| 28 / 29 | `std/log` ↔ `std/sync` | 日志打乱 park/wake 函数指针 |

13/14 那条是实测的：同时 `import std.log` 与 `std.timer`，
`log_info` 之后再无任何输出，进程直接死掉，**没有任何报错**。
两个模块单独用都正常 —— 这正是抢槽最难查的地方。

改法三件：

1. `STATIC_SLOTS` 32 → 64（每个槽 8 字节，扩一倍 = 256 字节静态区）。
2. 字面量下标**编译期**越界检查：`static_word(64)` 直接
   `SyntaxError: static_word(64) 越界：槽位下标必须在 0..63 之间`。
   以前越界是静默踩内存。
3. `std/log` 的 9 个槽位整体搬到 32–39，把 13/14/15/28/29 让回去。

门禁 `tools/dev/check_static_words.py` 把登记表变成强制的（越界 / 抢槽 /
未登记 / 登记过期 / 归属不符五条判据），已挂进 `run_win_tests.py`。
唯一允许的共享是 `static_word(0)` —— http/ws/sse 三个服务端框架的回调通道
（同一个机制、同一个槽），登记表里写成模块列表表示允许。

夹具 `tests/t175_static_words.qma` 按"先 timer、再 log、再 rand、再堆分配"
复现过去那条崩溃路径；`case_static_word_oob` 锁住"越界必须编译期报错"。

### 3.74 `.qla` 链接不校验单例尺寸（v3.24）：先证明隐患能不能触发

v3.23 扩静态区时留了一句"旧档案仍按 32 字、新代码按 64 字写会错位"。
这次先写探针实测，**没有直接改代码**：

| 场景 | 构造方式 | 结果 |
|---|---|---|
| A. 编译器指纹不同 | 把 `compiler` 改成假值 | **被拦下** |
| B. 指纹相同、尺寸不同 | 指纹对齐，只把 `static` 砍回 32 字 | **链接成功** ← 隐患成立 |

A 能拦是因为编译器指纹是 `tools/stage0/*.py` 的**全内容哈希** —— 改了
编译器指纹就变，旧档案自然链不上。所以"升级编译器后旧档案错位"这条
**实际上已被现有机制覆盖**，不用额外修。

B 说明兜底不成立：指纹只保证"同一份编译器"，不保证"同一块尺寸"。
真会出事的是这种组合 —— 指纹算别的目录、档案被手工构造、或将来把某个
单例尺寸做成配置项。

链接期 `merge()` 把各档案全局区首尾拼接，同名单例统一重定向到**第一个**
档案那一份；于是 32 字的块 + 按 64 字写的代码 = 写到块外，踩紧邻的全局块。

修法：`_check_compatible` 强制所有档案里同名单例的**字节数**相等。尺寸信息
档案里现成（`global_len`），比对一次是 O(特例数)。放链接期是因为编译期
只能看到自己那一份，尺寸不一致是两份档案之间的**关系**。

```
档案不兼容：进程级单例 `static` 的尺寸不同 —— t175_static_words 是 512 字节，
<same-fp-32words> 是 256 字节（同名单例在所有档案里必须等长，否则链接后会错位踩内存）
```

用例 `tests/qla_test.py::test_singleton_size_mismatch`，QLA PASS=33 FAIL=0。

### 3.75 `static_word(0)` 的共享（v3.25）：核实后不是隐患

v3.23 的登记表把 slot 0 记成 http/ws/sse 共享，文档里留了句"三者同时跑会
互相覆盖，得改成连接表"。v3.25 照 v3.24 的方法先实测，结论是那句话**不成立**：

| 问题 | 查法 | 答案 |
|---|---|---|
| 布局相同吗？ | 三个框架都调 `conn_state_new(max_conns, 80)` | **相同**，结构上安全 |
| 能同时跑吗？ | `net_serve` 的 acceptor 在 `while true` 里 | **不能**，主线程被占死 |
| 那语义是什么？ | —— | 最后写入者获胜，与单实例语义**一致** |

真要做多端口/多协议并发，卡点不在 slot 0，而在 `net_serve` 本身是单实例的
（`R_STATE_W` 也只有一个槽）。那是独立的大改动。

这一版没改实现，产出是把判断钉住：夹具 `tests/t176_slot0_share.qma`、
门禁新增 `SHARED_LAYOUT`（共享槽位必须声明并校验"所有共享者调同一个
构造函数"）、两处文档修正。**共享**与**抢槽**是两件事 —— 前者是约定、
布局相同即可，后者是互不知情、必须改；`REGISTRY` 用"模块列表"表达共享，
但原先**只登记归属、没校验布局**，于是"共享"仍可能悄悄退化成"抢槽"。

### 3.76 标准库 6 个模块外部调不到（v3.26）：能编译 ≠ 能用

`07-gaps.md` §7.13 那条挂了 24 个版本。重跑完整审计（70 个模块逐个
import + 构建），三类问题：

| 类 | 数量 | 例子 |
|---|---|---|
| 连解析都过不去 | 2 个模块 | `let rc = h(fd)` —— `rc` 是关键字 |
| 有函数但 0 个 `pub` | 6 个模块 | `std/core` / `gen` / `serialize` / `sse` / `time` / `ws` |
| 跨模块调非 pub | 1 处 | `ws` 调 `sha1_str`（要原始摘要，`sha1_hex` 给不了） |

第一类最讽刺：`std/http.qma:243` 早就写了注释"`rc` 是关键字，别用作
变量名"，sse/ws 的作者没看到，于是这两个模块一直编不过。

第二类最隐蔽：**能编译，但外部一个函数也调不到**。`03-stdlib.md` 里它们
标着可用。v2.01 那次审计只看了"能不能构建"，所以这种情况一直没被抓住。

改完：能编译 68→**70/70**，有 pub 导出 64→**70/70**，公开函数 584→**635**。

门禁 `check_std_import.py` 的**第二判据**就是为这类问题设的：有顶层函数
却一个 `pub` 都没有，判失败。

顺带修掉：起服务前调 `ws_accepted()` / `sse_accepted()` 会 `0xC0000005`
（`_wst()` 得 0 再传给 `conn_accepted(0)` 解引用空指针）。

**一条流程教训**：`tests/lsp_test.py` 原先把 `std/sse.qma` / `std/ws.qma`
当作"解析失败"的负向样本 —— 修好它们反而打红回归。别拿真实缺陷当测试
前提，负向样本要现场构造。

### 3.77 `ws` / `sse` 真跑一遍（v3.27）：opcode 在分派时丢了

v3.26 让这两个模块能编译、能 import，但**从没验证过它们真的能跑**。
WebSocket 与 SSE 的坑全在线上协议（握手摘要、帧长度三档、客户端掩码、
事件块空行结尾），一条都不靠编译能发现。

写了两个端到端夹具（Python 手写客户端，不引第三方库），立刻抓到两个真问题：

**1. `std/ws` 把 opcode 丢了**

`_frames` 里文本帧与二进制帧**合并分派**（`op == TEXT || op == BIN`），
而回调签名是 `fn(fd, data)` —— 用户拿到消息时没法知道它是哪种。实测：

```
[FAIL] 二进制 echo：op=1 len=256      # 发的是 0x2，回来的是 0x1
```

改签名会让所有现有 ws 代码编译失败，所以改成把当前帧 opcode 记进状态块
（`WS_OP_W = 13`，状态块 16 槽里 13-15 空闲），新增 `ws_last_op()` 供回调
查询。两处 `h_msg` 都要记：完整帧记 `op`，**分片完成记首帧的 `fop`**
（续帧一律是 CONT=0，拿它当类型就错了）。

**2. 端口撞了**

`ws_demo.qma` 监听 8092，而 `http_router_test.py` 与
`reactor_dualstack_test.py` 也用 8092。三者进同一回归会互相抢端口。
挪到 18150；夹具从源码正则读端口，demo 改端口时自动跟上。

夹具：`ws_e2e_test.py`（7 项，含"两次不同掩码 key 都必须解对"——
能抓住"把掩码当明文"的实现错误）、`sse_e2e_test.py`（8 项，含
"事件块以空行结尾"与"tick 序号递增 0..9"，后者顺便验证 spawn 跨线程推送）。

### 3.78 补分片用例，抓到"分片之后连接永久卡死"（v3.28）

v3.27 明确留了尾巴："分片没有端到端用例，代码路径存在但没跑过"。
补它的过程直接撞出一个**严重缺陷**。

最小复现（分片收一条，再发一条普通单帧）：

```
frag   -> (1, b'AAABBB')      ← 分片本身是对的
single -> 超时                 ← 连接永久失效
```

不是偶发：**只要用过一次分片，这条连接就再也收不到任何消息**。

根因在分片完成分支：

```quelmara
_drop_frame(p, total, pay, plen)     // keep_to = total ← 错
```

`_drop_frame` 的语义是"保留 `[0, keep_to)`"。分片消息到这里**已经消费完**，
消息本体该整体丢弃，传 `total` 就把它留在了缓冲区开头；而 `WS_FOP` 已清零、
下一轮 `off` 从 0 解析 —— 于是把上一条消息的首字节当帧头读，永远凑不出
合法帧。正确写法是 `_drop_frame(p, 0, pay, plen)`。

**为什么 v3.27 没抓到**：那 7 项全是单帧，而单帧路径传的 `keep_to` 是对的
（`off` 单帧时等于 0）。bug 只在分片路径上暴露。

**教训：代码路径存在 ≠ 被测过。** `WS_OP_CONT` 分支写了 30 行，从没跑过，
里面藏着一个"连接永久失效"级别的错误。

夹具顺势从 7 项扩到 **15 项**，把 `WS_OP_CONT` / `WS_OP_CLOSE` 与两条
协议错误分支（未掩码帧、分片未完成时来新数据帧）全部覆盖 —— 这四条
都是"写了没跑过"的路径，实测都对。

顺带修了夹具自身：原来超时直接抛异常崩栈，丢掉前面已通过的断言。
加 `safe_recv` / `safe_send` 后，带 bug 版本会干净报出 3 条 FAIL。

### 3.79 两个 1 MB 撞在一起（v3.29）：上限之内的消息反而收不全

补 v3.28 遗留的"超长消息 1009"用例时扫了一遍边界：

| 载荷大小 | 结果 |
|---|---|
| 1 048 476 | ok |
| **1 048 576**（正好 = 上限） | **NO RESPONSE** |

1 MB 是 `WS_DEFAULT_MAX_MSG`，理论上"不超限"，**却卡死**。

根因是两个上限相等：

```quelmara
const WS_DEFAULT_MAX_MSG = 1048576    // std/ws：单条消息上限
const CONN_MAX_BUF      = 1048576     // std/net/core：连接累积上限
```

一条消息要收全，缓冲区得同时放得下「帧头 + 掩码 + 载荷」。两个上限相等时，
载荷没收完连接缓冲就先到顶：`conn_append` 返回 -1 丢掉后续数据，而
`_frames` 里 `n - off < hl + plen` 永远成立 —— **永久卡死，连 1009 都发
不出去**（那条判断压根没机会执行）。

修法：消息上限降到 **960 KB**（留 64 KB 余量），让超限帧的帧头能在缓冲
未满时被解析到，1009 正常触发。

**为什么余量不是 64 字节**：试过 `1 MB - 64 B`，`plen` 略超上限的帧仍会先
把缓冲塞满，发 close 后立刻关闭会被 RST 吃掉，客户端**一个字节都收不到**
（实测 0 字节 + `WinError 10054`）。

**一个如实说明的边界**：客户端一次性猛灌超过连接缓冲的数据仍会卡死。
那不是 ws 协议缺陷，是 TCP 背压 —— 真实客户端都分块发送。夹具里
只发帧头来测 1009，那才是"协议是否拒绝"的正确问法。

### 3.80 负结果：消掉归纳变量那条 mov 测不出收益（v3.30）

`07-gaps.md` §5 的 `loop_sum 三件套` 第 ① 项是"phi copy 消除"。
`examples/loop_sum` 的循环体 IR 里确实有一条搬运：

```quelmara
('mov', 7, 10)                 # tmp = r
('bin', 'add', 10, 10, imm 7)  # r += 7
('cssub', 10, 10, imm 13)
('bin', 'add', 1, 1, 7)        # acc += tmp
```

`opt_copy_prop` 消不掉它（前提是"源 vreg 只定义一次"，而 r 每轮重定义）。
实现了 `opt_phi_copy`：把累加**提到** r 更新之前，直接用旧值 ——
IR 从 5 条降到 4 条，正确性用 Python 现算的已知答案验过。

**但 A/B 完全测不出差异**：

| 形状 | ON best | OFF best |
|---|---|---|
| loop_sum（4–5 条循环体） | 253 / 254 / 253 | 254 / 254 / 254 |
| tight（3–4 条，mov 占比更高） | 333 / 334 / 333 | 333 / 335 / 337 |
| double_use | 381 / 381 / 380 | 380 / 381 / 380 |

确认 pass 真的生效（IR dump 显示 mov 已消除），不是空操作。

**原因**：x86-64 的 `mov r64,r64` 在寄存器重命名阶段就被消掉，不占执行
端口 —— 与 v2.02 SHA-256 轮展开那条负结果同机理。

**一个差点被误导的测量**：第一版探针用源码改写做对照
（`let t = acc; acc = t + (i*7)%13`），测出 255 → 328 ms（+29%），
看起来"一条 mov 值 29%"。看 IR 才知道多出来的 mov 同时**增加了两个
活跃 vreg**（`3` 和 `9`），寄存器分配变差才是那 73 ms 的来源。

**教训**：判断单条指令的代价要用 pass 级 A/B（`QLM_SKIP_PASSES`），
不要用源码改写 —— 源码层"看起来等价"很容易悄悄改变寄存器压力。

按项目铁律回退（测不出好处就不留复杂度），`opt_phi_copy` 代码不在树上。
保留 `tests/t178_phi_copy.qma` 钉住**归纳变量化简本身**的正确性
（那也是重排型变换，错了会静默算错）。

### 3.81 传错类型编得过：静默把 str 指针当 int（v3.31）

`07-gaps.md` 里有 14 条标着"待修/待查"。先写探针批量复核
（`build/audit_gaps.py`），结果 **4 条文档已过期**（7.3 / 7.9 / 7.19 /
7.21 实际早已修好），1 条是真问题：

```
fn g(a: str, b: int, c: str) -> int { return b }
print(g("abc", "not-int", "x").to_str())
  -> 编译通过，运行期打印 140699978051634（str 数据指针当 int）
```

v2.07 在 `std/net/addr` 就踩过这个：`str_find_from` 实参写反 → SIGSEGV。
根因是调用点只做**个数**校验，`str`/`int` 在 IR 里都是一个 8 字节槽。

**修法是保守推断**：只判能确定的（字面量、已知返回类型的调用），
变量一律放行。这不是偷懒 —— stage-0 的类型传播本身有缺口（§7.28），
在那种基础上做严格检查会**误伤正确代码**。

`int` ↔ `bool` 互传不拦（语言允许 0/1 当 bool 用）。

**验证不误伤**是本次最要紧的一步：70 个标准库模块全部编译通过 +
全量回归全绿（数字见本版 CHANGELOG）。

顺带修正 4 条过期文档条目 —— **文档里的"待修"会过期**，审计脚本
留在 `tools/dev/audit_gaps.py`，下次复核直接跑。

### 3.82 非 UTF-8 源文件抛裸异常 + 单源构建打 traceback（v3.32）

v3.31 复核确认 §7.11 仍存在。它其实是**两个问题叠在一起**：

**问题一**：非 UTF-8 源文件抛裸 `UnicodeDecodeError`：

```
'utf-8' codec can't decode byte 0xff in position 45: invalid start byte
```

没有文件名、没有行号（`position 45` 是字节偏移）、不是 `SyntaxError`、
没有可操作建议。

**问题二**：因为不是 `SyntaxError`，单源构建路径不捕获它，用户看到
**整段 Python traceback**。有意思的是多源并行路径（`_build_unit`）反而
捕得干净 —— "单源比多源难读"没有任何道理。

修法：`read_source(path)` 统一读源码（解码失败转 `SyntaxError` 带
`文件:行:列`、剥 UTF-8 BOM、给可操作建议）+ `main()` 统一诊断出口
（只捕 `SyntaxError`；其它异常仍带 traceback —— 那是编译器自己的 bug，
藏起来更难查）。

改后：

```
[qlm] 编译错误：bad.qma:3:4: 源文件不是合法的 UTF-8（字节 0xff 无法解码）。
常见原因：编辑器按 GBK/ANSI 保存，或存成了 UTF-16。请转成 UTF-8（无 BOM）。
```

夹具 `tests/encoding_diag_test.py`（6 项，含"带 BOM 的文件能编译**并运行**"
—— BOM 若被当普通字符喂给词法器，编译期就挂，所以运行成功才说明真剥掉了）。

### 3.83 `read_source` 抽成零依赖模块（v3.33）：7 处读源码的点收口

v3.32 只修了编译主路径，其它工具各写各的 `open(..., encoding="utf-8")`。
这一版收掉，但**直接改行不通** —— 先看清约束：

`qlm_cli.py` 里有一段明确注释：

```python
# 源码扩展名，与 `qlm.SRC_EXT` 同值。**刻意不 import qlm 去取**：
# `import qlm` 在本机要 1.3 s，而缓存命中的整条路径只该花几十毫秒。
```

`read_source` 原本在 `qlm.py` 里。让 CLI 为了一个读文件函数拉进整个
编译器，直接毁掉缓存命中的意义。

所以抽成**零依赖**的 `qlm_src.py`（只用 `os`）：

| 函数 | 行为 |
|---|---|
| `read_source(path)` | 失败抛 `SyntaxError`（带 `文件:行:列`） |
| `read_source_or_none(path)` | 任何失败返回 `None` |

`qlm.py` 保留转发别名，`qlm.read_source` 与老调用点都不受影响。

收口 7 处：`qlm_cli`（`lex` + 扫 `test "` 块）、`qlm_doc`、`qlm_fmt`、
`qlm_fuzz`、`qlm_dbinfo`、`qlm_dbg`。其中 `qlm_dbg` 用
`read_source_or_none` —— 调试器读不到源码应退化成 `<source unavailable>`，
不该让整个会话挂掉。顺带修了它原来的 `except OSError` 捕不到
`UnicodeDecodeError` 的缺陷。

**剩下 5 处没改是对的**：它们读的是缓存统计 JSON、缓存元数据、调试脚本、
已生成的文档 —— 都不是源码，失败语义也不同（缓存坏了要静默重建，
不是报语法错）。

现在 `doc` / `fmt --check` / `lex` 对非 UTF-8 都给统一诊断、无 traceback。

### 3.84 负结果：内联的"溢出槽增幅"判据本身是错的（v3.34）

`07-gaps.md` §5 登记着"要给内联加'溢出槽增幅'闸门"。先量一下现在到底
有没有"内联进去反而更慢"的情形 —— 挂钩 `qlm_native.allocate` 记录每个
函数分配后的 `nslots`，对比默认内联 vs `QLM_NO_INLINE=1`：

| 函数 | nslots（关→开） | 指令数 |
|---|---|---|
| `main` | **2 → 86（+84）** | 2558 |
| `map_str` | 0 → 36（+36） | 675 |
| `__map_get_n` | 0 → 6 | 102 |

产物 66560 vs 17920 字节，**差 3.7 倍**。看着正是该回退的情形。

**但 A/B 显示内联整体是赚的**（5 次取最小）：

| bench | ON/OFF |
|---|---|
| map_str | **84.7%** |
| str_build | **90.6%** |
| mix_arith | 97.7% |
| nested | 107.8% |
| buf_scan | 104.9% |

**关键观察**：`main` 的溢出槽涨了 84 个，整体仍然赚。

原因是溢出槽数量与性能不是线性关系：溢出槽只在"跨基本块、跨调用的
活跃值"上真正产生内存往返，`main` 那 86 个槽大部分是各 helper 的
**短命临时**，生命周期不重叠；而内联省掉的是每个调用点的
call/ret + 参数搬运，在热循环里是实打实的。

所以按"溢出槽增幅"写闸门会在 `main` 就**误判**。

**与 v2.96 的关系**：那次 `__vec_grow` 问题的本质不是溢出槽，是
**冷路径代码被搬进热循环**（占指令缓存与解码带宽）。正确的判据是
"callee 是不是冷路径"，那是**语义判断**，不能自动推导成数值阈值。
v2.96 的逐 callee 手工标记在这个意义上是对的，不是"打地鼠"。

决定不写这个启发式 —— 不但测不出好处，按那个判据写还会误判。

### 3.85 v3.31 的类型检查抓出 stage-1 parser 的真实 bug（v3.35）

按 v3.34 新增的 §0 规范转向 `bootstrap/`（核心代码），从
`selfhost_status.py` 那条一直红的"语法：声明级 对拍失败"入手。

跑 `parsediff.py` 立刻看到原因 —— **v3.31 加的类型检查把它拦下来了**：

```
[qlm] 编译错误：函数 dec_val 的第 1 个形参期望 str，实参是 int
```

也就是说 stage-1 parser **从 v3.31 起就编不过**，但没人发现 ——
因为这条对拍只在 `selfhost_status.py` 里跑，而那个脚本**不是门禁**。

根因是 `bootstrap/parser/qlm_parse.qma` 里多套了一层：

```quelmara
dec_val(radix_val(strip_us(substr(t, 2, len(t) - 2)), 16))
```

`radix_val` 已经把 `"ff"` 解析成数值（返回 int），外面再套 `dec_val`
（把字符串解析成数值）既是类型错、也是**语义错**（在解析数值的字节表示）。
三处（`0x`/`0b`/`0o`）都改掉。

修完 `PASS=234 FAIL=0`，自举状态从"对拍失败"变成**"对拍通过"**。

**这件事证明类型检查有用**：v3.31 写它时只验证了"不误伤"，这一版
验证了另一半——它确实能抓到真 bug，而且是**双重性质**的（类型错 +
语义错）。只看类型可能会想加 `to_str()` 绕过去，看语义才知道是多余嵌套。

顺带扫了其余核心代码确认是孤例：`bootstrap/`、`examples/`、`tests/`
里实参类型错误都是 **0**。

**流程问题一并修了**：`selfhost_status.py` 是给人看的状态面板，不是门禁
—— 面板上的红字没人看，和不存在没区别（与 v3.14 那条"从不影响退出码的
告警迟早等于不存在"同源）。已把 `parsediff.py` 接进 `run_win_tests.py`
的 `test_qlmc()`，代价约 6 秒。

### 3.86 给 qlmc 补 5 个内建：`std/` 阻塞项 35 → 12（v3.36）

用户要求"编译器核心全部改用自研语言"。先测规模：`tools/stage0` 约
30 000 行，qlmc 10 377 行（子集 S20），**qlmc 对 `std/` 覆盖率 0/70**。

所以不喊口号，先测阻塞。跑 70 个模块按错误分类，**35/70 是缺内建**：

| 数量 | 原因 |
|---|---|
| 17 | `str_from_bytes` |
| 16 | 没有 main（需 lib 模式） |
| 9 | `static_word` |
| 4 | `mem_ptr` / `mem_load32` |
| 2 | `str_alloc` |

补了 5 个内建，三个有坑：

1. **`str_from_bytes` 签名不是 `(p, n)`** —— 它收**一个 `vec[int]`**，
   取每个元素的**低字节**。第一版按 `(p,n)` 写，调用点只传 1 个实参，
   于是 qlmc 自己 `vec index out of bounds`。
2. **`static_word` 要一块进程级 bss** —— qlmc 的 .bss 只有 32 字节，
   扩成 `32 + 64*8`，新增 `OP_BSSADDR`（`OP_LEA` 的 `FK_BSS` 变体）。
   踩坑：偏移必须放 `imm` 槽，放 `a` 会被当 vreg 计数导致崩溃。
3. **`mem_load32` 两个坑**：第 2 个参数是**字节偏移**（不是 4 字节下标，
   与 `mem_load64` 的"第 w 个字"不同）；而且 `OP_LOAD` 的发射**忽略宽度**，
   无条件发 8 字节 `mov` —— 于是读到脏的高 32 位，差分立刻对不上。
   修法：新增 `_mov_load32`（REX 不带 W 即零扩展）+ 按 `imm` 分派宽度。

**结果**：缺内建失败 35 → **12**，qlmc 自身崩溃 11 → **0**。

覆盖率仍是 0/70，但**剩余阻塞换了类别**：最大项变成"没有 main（需 lib
模式）"30 个 —— 那是功能缺失，不是内建缺失。下一版最该做 lib 模式。

夹具 `t180_qlmc_builtins.qma` 的关键设计：**同一个夹具用 stage-0 编一遍、
用 qlmc 编一遍，两边行为必须一致**。第一次跑 qlmc 版本时 `mem_load32`
就挂了 —— 正是靠这个对拍发现宽度没分派。

### 3.87 qlmc 加 lib 模式：`std/` 覆盖率 0/70 → 37/70（v3.37）

v3.36 分类出的最大阻塞是 **30 个模块"没有 main"** —— 那是功能缺失
（qlmc 只做 program），不是内建缺失。

加 `qlmc build X.qma -lib`：不要求 main、不发真正的入口（只放一条
`ret`，因为 PE 的 `AddressOfEntryPoint` 必须指向 `.text` 内合法位置）。

顺带补 `mem_chr`（5 个模块用，需新的 `RT_MEMCHR` 运行库例程）与
`str_from_mem`（2 个模块用，复用 `_bi_mem_str`）。

| 指标 | v3.36 | v3.37 |
|---|---|---|
| **qlmc 覆盖 `std/`** | **0 / 70** | **37 / 70** |

**踩的坑（值得记）**：`mem_chr` 第一版把 `cmp r9, rdx` 编码成 `4D 39 D1`
—— 忘了 `39 /r` 是 `cmp r/m, r`（不是 `cmp r, r/m`），`D1` 实际是
`cmp rcx, rdx`，需要 `rm=r9` 则要 **REX.B** 而不是 REX.R。正确是
`49 39 D1`。

症状很典型：`mem_chr(p,4,99)` 返回 -1 而不是 2（循环上界比错，只跑 1 轮）。
**靠 stage-0 / qlmc 对拍抓到**：stage-0 给 `[1,2,-1,-1]`、qlmc 给
`[1,-1,-1,-1]`。

**本版最重要的产出是门禁** `tools/dev/qlmc_coverage.py`：用户要"核心改用
自研语言"，那件事的进度不能靠感觉，得有一个会变的数字。脚本用 qlmc
逐个编译 `std/**/*.qma`，与 `BASELINE`（当前 37）比较，**低于基线判
FAIL**。基线只许上调 —— 这是有意的摩擦，让人看见进步。

### 3.88 补 `mem_diff` / `mem_xchg`：覆盖率 37 → 39（v3.38）

先核实 v3.37 写下的判断"`vec[vec[T]]` 是 stage-0 与 qlmc 的共同缺口"——
**判断错了**：`grep 'vec\[vec' tools/stage0/qlm_native.py` 显示
`v1.12 vec[vec[T]] 解锁`，stage-0 早就支持，只有 qlmc 不支持。

而且当场修不了：`vec[vec[int]]` 的类型码是 `0x8000 + 0x8000 = 0x10000`，
**正好是 `TY_MAP` 本身**。要改编码方案会波及 **34 处**
`>= TY_VEC && < TY_MAP` 形式的范围比较 —— 高风险重构，不适合塞进
"推进一版"。

所以这版做低风险但确定的项，补两个内建（各 2 个模块用）：

* **`mem_diff(p1,p2,n)`** —— 返回首个不同字节的下标，全等返回 `n`。
  手写机器码的要点：返回值直接是循环变量 `r9`（全等时 `r9==n`、
  找到时 `r9` 是下标，**两种情况同一个寄存器**，不需要额外分支）。
* **`mem_xchg(addr,val)`** —— 只有 6 字节：`mov rax,rdx` /
  `xchg [rcx],rax` / `ret`。`xchg [mem],reg` **隐含 LOCK**，不需要
  额外前缀（x86 的特例，其它 RMW 指令都要显式 `lock`）。

**验证方式**：手写机器码错了不会崩、只会静默算错，所以每个内建都用
stage-0 / qlmc 对拍（`mem_diff` 三种输入、`mem_xchg` 的旧值+写入）。

覆盖率 37 → **39**，门禁自己提示"该把 BASELINE 上调到 39" ——
这正是设计意图：**数字涨了要人手动确认，不让人无感地漂**。

**一个流程反思**：上一版把"共同缺口"写进文档时没有 grep 验证。
写进 CHANGELOG 的**因果判断也要核实**，不然下一版会基于错误前提做决策
（这一版差点直接去改 stage-0 的类型编码，那是白费功夫）。

### 3.89 补 `vec.pop()`：覆盖率 39 → 43（v3.39）

查 `ds` / `json` / `path` / `regex` 四个模块用了哪些 vec 方法，结论很干净：
**它们都只用 `.pop()`**，而 qlmc 的报错信息里 `.clear()` 已支持 —— 缺的
就是 `pop`。

语义照 stage-0 的 `__vec_pop`：

```c
if (v->len <= 0) qlm_vec_fail();
v->len--;
return *(int64_t *)(v->buf + v->len * v->esz);
```

qlmc 侧用现有 IR 拼：取 `len` → **`len <= 0` 走 `OP_EXIT 1` 死路**
（不能静默读越界）→ `nl = len-1` 写回 → 读 `buf[nl]`（聚合元素返地址、
标量返加载值）。空 vec 检查复用 `_vec_check` 的"条件反写 + 死路"模式。

覆盖率 39 → **43**（比预期多解开 1 个模块）。基线已上调。

**一个持续有效的做法**：从 v3.36 起每个新内建/方法都做 stage-0 / qlmc
双向对拍，夹具覆盖边界（空 vec、`n=0`、低字节截断…）。这个做法抓到过
两个真实 bug —— `mem_load32` 宽度没分派、`mem_chr` 的 REX 字节写错 ——
都不是"能跑就以为对了"能发现的。

### 3.90 补 `str_ptr` / `target_arch`：覆盖率 43 → 44（v3.40）

先纠正 v3.39 的判断：它写"`vec[vec[T]]` 有 **4 个**模块"，按实际输出
重新数**只有 1 个**（`std/csv.qma`）。上一版的"4"来自 v3.38 的错误分类
（把 `vec 方法不全` 的 4 个和嵌套 vec 混在一起数了）。

这个纠正改变了优先级：若真是 4 个模块，值得重写类型编码（34 处比较）；
**实际 1 个 → 收益与风险不匹配**，不值得现在做。

重新数出的真实分布里**最大的一项是网络内建（6 个模块）**：
`tcp_listen` / `tcp_peer_raw` / `tcp_send_n` / `udp_open` / `udp_sendto` /
`udp_sendto6` —— 那是接 Winsock 的独立工程量。

所以这版做两个**零成本**内建：

* **`str_ptr(s)`** —— str 的值**本身就是数据指针**（长度在 `p-8`），
  所以直接返回操作数，一条 `OP_MOV`。用途是喂 `tcp_send_n` 零拷贝。
* **`target_arch()`** —— 编译期常量，qlmc 只产 x86-64 所以恒为 1。

**夹具的设计要点**是钉 ABI 约定而不是"能调通"：

```quelmara
let p = str_ptr("hello")
assert(mem_load8(p, 0) == 104)      // p[0] = 'h'
assert(mem_load64(p - 8, 0) == 5)   // 长度头在 p-8
```

两条**配对**才有意义。若哪天 str 改成"指向长度头"，`str_ptr` 会静默
偏移 8 字节 —— 喂 `tcp_send_n` 会发错数据，**且不会崩**。这类依赖 ABI
约定的零成本内建最需要断言。

覆盖率 43 → **44**。

**一个反复出现的流程问题**：连续两版（v3.38、v3.40）都在"把判断写进
文档"这一步出错，错因相同 —— **数数字/下结论时没对着实际输出核对**。
"写文档前先跑一遍确认"应该成为固定动作，而不是靠记性。

### 3.91 决策验证：qlmc 能通过 `@ffi` 调 Winsock（v3.41）

这一版**覆盖率没动**（44/70）—— 买的是决策依据。

补网络内建（6 个模块）有两条路，风险差一个量级：

| 路线 | 做法 | 风险 |
|---|---|---|
| A | 改 qlmc 的 IAT 表，把 ws2_32 符号加进内置导入 | **高**（动 `I_USER` 索引与导入表布局，影响所有产物） |
| B | 用 Quelmara 源码 + `@ffi` 实现整组内建 | **低** |

选 B 的前提是"qlmc 产出的程序能通过 `@ffi` 调 ws2_32"—— 这件事
**没人验证过**。qlmc 的 `@ffi` 只在 `s12_ffi` 用过，没对 ws2_32 这种
"多函数 + 句柄语义"的 DLL 试过。

`t185_qlmc_winsock.qma` 走完整生命周期
`WSAStartup -> socket -> bind -> listen -> closesocket`，
**stage-0 与 qlmc 两边都通过** → 路线 B 可行。

夹具两个设计细节：

* **端口写 0**（系统分配，不与回归里别的用例抢端口）+ **不调 `accept`**
  （会阻塞，夹具会挂住）；
* 用 `s > 0` 而不是 `s != -1` —— Win64 的 `int` 返回值只写 eax，
  `SOCKET_ERROR` 在 rax 里是 `0x00000000FFFFFFFF` 而非 64 位 `-1`，
  直接与 `-1` 比较**会漏检**（stage-0 注释里记着这个坑）。

**"验证决策前提"本身是产出** —— 若上一版直接去改 IAT 表，可能花掉一整版
还引入风险；这次 20 分钟的验证直接排除了那条路。

### 3.92 网络内建落地 + 分配器 ARG 屏障缺陷（v3.42）

覆盖率 **44 → 45**（基线已上调）。按 v3.41 的路线 B 实现了 TCP 六个内建
（`tcp_listen` / `tcp_accept` / `tcp_send` / `tcp_send_n` / `tcp_recv` /
`tcp_close`），`I_USER` 12 → 20，`dnames` 加 `ws2_32.dll`。

过程中挖出三个**结构性**缺陷，都不是"写错一行"：

| # | 缺陷 | 症状 | 根因 |
|---|---|---|---|
| 1 | IAT 槽位漏填 | 一执行就 `0xC0000005`，`print` 都活不过 | 加 `dsym.push` 忘了加对应 `iat.set`，槽位留 0 → `call [0]` |
| 2 | 分配器把实参寄存器当临时值 | `tcp_send_n` 恒返回 0，对端收不到 | `cp[]` 只把 `CALL` 当屏障，`OP_ARG` 不算；临时池 `R8/R9` 与第 3/4 实参寄存器重叠 |
| 3 | 帧槽上限顶爆 | 自举 stage-2 编不过自己 | `build_rdata` 每条 `let` 占 1 格，已贴 416；加 8 个 `dsym.push` 推过去 |

第 2 条是**通用缺陷**，只在手写 IR 的内建里暴露：用户函数的三参调用一直
是对的（实参在 `CALL` 前搬完、区间含 `CALL`）。修复是把 `OP_ARG imm>=2`
也算作跨调用屏障 —— 只对 `>= 2` 生效，因为 0/1 映到 `RCX`/`RDX`，不在临时池。

第 3 条的正解不是加帧（帧 > 4 KB 要栈探测，§7.17）：先试过把上限
416 → 424，报错**跟着涨**成"需要 425"，说明不是容量问题；加临时诊断才
看清是 `build_rdata` 真的在用 424 格。正解是把 8 个符号注册搬进独立函数
`_reg_ws2` —— 函数调用不占调用方的局部槽。

验证走差分口径：`tests/t186_qlmc_tcp.qma` 是服务端（阻塞在 `accept`），
由 `tests/net_e2e_test.py` 用 Python 当客户端连接、发报文、收回显，
再断言两边输出。Python 端独立实现，能同时钉住 IAT 槽位、`sockaddr_in`
布局、htons 字节序、fail-fast 判定。

```
stage-1 2 789 376 B / stage-2 464 384 B / stage-3 464 384 B
不动点成立  sha256 3FCC4B18D151905E…
```

剩余阻塞：`tcp_listen6` / `tcp_connect` / `tcp_*_to` / `tcp_peer_raw` /
`udp_*`（超时类要 `select`/`setsockopt`）；另有 `args` / `wall_ms` /
`file_size` / `thread_yield` / `xmm_load` / `xmm_mov` / `syscall` 未做。

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
