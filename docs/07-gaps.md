# 能力缺口与路线

> 本文只登记**做不到什么**和**先做什么**。实测数字见 [`06-status.md`](06-status.md)，
> 不在此重复。每条尽量给出复核方式或前置条件。
>
> 标记：✅ 已可用 ｜ 🟡 部分可用（边界见右栏） ｜ 🚧 规范已定、实现未做 ｜ ❌ 未做

## 1. 语言层

| 能力 | 状态 | 缺什么 | 影响 |
|---|---|---|---|
| 用户泛型 | 🟡 | 只有单类型参数 + **显式实例化**；无推导、无约束、无泛型 struct / 泛型方法 | 通用算法可写，但调用点啰嗦 |
| `map[K]V` | 🟡 | V 仅 int/str，不能 `map[str]Struct` | 配置表/符号表要拆成平行 map |
| `vec[T]` | 🟡 | `vec[map]` 不支持；struct 内嵌套聚合按 1 槽占位 | 复杂 AST 仍需扁平化 |
| 函数值 | 🟡 | `callr` ≤6 参、实参不能是 struct/slice、**无捕获**（无闭包） | 回调只能固定签名 |
| 所有权检查 | 🟡 | **只查 `rc[T]` 句柄**；struct/数组/str 的别名与生命周期不查，并发竞争不查 | 不能对外宣称"Rust 那套借用检查" |
| `interface` | 🟡 | 装箱不释放；同类型跨接口同名方法报错；接口与 impl 必须同源文件；AArch64 未接 vtable | 热点循环装箱会涨堆 |
| 错误处理 | 🟡 | `result[T,E]` 载荷限标量；库层错误只能 fail-fast 或返回 -1/空串 | 库无法把 errno + 上下文交给调用方 |
| 模块系统 | 🟡 | `import` 是扁平合并；**无命名空间、无可见性、无版本** | 第三方库靠前缀约定共存 |
| 整数宽度 | 🟡 | struct 字段存窄值**不截断**；`vec[u8]` 元素仍是 8 字节槽 | 二进制格式要自己 mask |
| `@simd` | 🟡 | 只认 `acc += a[i]` 两种形状（int / f64）；点积需 AVX2 | 不是向量化器 |
| 并发 | 🟡 | `chan` 单消费者栈 pop 有 ABA；WaitGroup 自旋等待；AArch64 未接 atomic | 高竞争场景要自己加保护 |
| 编译期求值 | 🟡 | 只有整型 `+ - * / %`；`const fn` 未做 | 复杂常量表要手算 |
| 闭包 / 捕获 | ❌ | — | 只能传函数名 |
| FFI（自研后端） | ❌ | 无动态链接器；`@extern` 只有 C 后端原型 | 无法调用系统库 |
| `defer` / RAII / `Drop` | ❌ | 只有 `arena { }` 整块回卷 | fd/锁/缓冲释放全靠手写 |
| 宏 / 反射 | ❌ | 前置：编译期 AST API、类型元数据段 | 序列化只能手写字段表 |
| 字符串插值 / `format` | ❌ | 无可变参数机制 | 拼接冗长，`+` 链是 O(n²) |
| `switch` | — | 用 `match` 代替（设计选择） | — |

## 2. 标准库

| 类别 | 缺什么 | 撞到什么场景 |
|---|---|---|
| 压缩 | 多 member gzip 流（一次只解第一个）；zlib 容器（`wbits=15`）需先用 `inflate_raw` | 拼接过的 gzip 文件 |
| TLS | **记录层 / 握手状态机 / X.509**（密码学零件已齐：SHA-256+HMAC、AES-128-GCM、X25519） | https / wss 无法提供 |
| HTTP 客户端 | 出站请求（含 TLS 时才能 https） | 调用第三方 API |
| 路由 / 中间件 | `std/http` 只有单回调，path 匹配要自己写 if 链 | 稍大的服务都要手写路由表 |
| 静态文件 / MIME / cookie / session / multipart | 全缺 | 文件上传、登录态 |
| `chunked` 请求体 | 回 501 | 部分客户端上传 |
| DNS | 无解析器、无 `getaddrinfo` | 只能写 IPv4 字面量 |
| IPv6 | socket 家族改造（AF_INET6 + sockaddr_in6 + 字面量解析） | 现代部署基本要求 |
| TCP 批量收发 | 只有单次 `tcp_send/recv` | 高吞吐场景 syscall 太多 |
| 可靠 UDP | UDP 四件之上未做 | 游戏/实时传输 |
| 日志 | 无 stderr 通道、无轮转、无绝对时间戳（级别过滤 v1.19 已补） | 生产可观测性 |
| 编码 | 无 UTF-8 解码（一切按字节）、无 base64url（hex v1.19 已补） | 中文长度/截断、JWT |
| 数学 | 有 sqrt/cbrt/powi/取整/gcd；**无 `exp` / `log` / `pow(x,y)` / `sin` / `cos`** | 图形、统计、复利 |
| 哈希 | 只有 SHA-1 / SHA-256；无 MD5 / FNV | 缓存键、校验 |
| 数据结构 | 有 RingBuf / MinHeap；无 set / deque / LRU | 去重、任务队列、缓存 |
| 持久化 | 无 SQLite / KV / 序列化格式（`std/serialize` 只是编码原语） | 任何要存数据的应用 |
| 正则 | 无 | 文本清洗、路由匹配 |
| CLI | 有 `args()`，无 flag 解析（`-x` / `--k=v` / 子命令） | 工具类入口 |
| 国际化 | 无 locale、无 Unicode 分类、无大小写折叠 | 多语言输出 |

## 3. 工具链

| 项 | 状态 | 缺什么 |
|---|---|---|
| 调试器 | 🟡 | 无 DWARF/PDB、无源码断点、无变量查看；靠 `capstone` / `--dump-ir` / `readelf` |
| LSP / 补全 | ❌ | 无语义索引、跳转、重命名 |
| 文档生成 | ❌ | 无 doc comment 语法 |
| 库归档 `.qla` | 🚧 | 无目标文件格式 → 无法增量编译、无法分发二进制库 |
| 包管理 | 🟡 | 有 qpm v0（path + git）；无 semver 区间、registry、发布流程、传递依赖冲突合并 |
| 增量 / 并行编译 | ❌ | 每次全量 |
| 性能回归门禁 | 🟡 | `bench --threshold` 可用，但未进 CI |
| 覆盖率 / fuzz | ❌ | — |
| 对拍脚本耗时 | ✅ | `irdiff` 并行后 49 s（原 5 min 41 s）；`emitdiff` 10 s 内 |
| `version` 口径 | ✅ | v1.19 起 `VERSION = "1.19.0"`，与 `docs/versions/` 对齐 |

## 4. 平台

| 平台 | 状态 | 前置 |
|---|---|---|
| Windows PE32+ | ✅ 主平台 | — |
| Linux ELF64 | ✅ 构建级（CI 执行） | 本机无 gcc/WSL |
| Linux io_uring | ✅ | 5.1+ 内核 |
| AArch64 | 🟡 模拟器执行级 | 需补 chan/map/spawn/vtable/atomic/SHA |
| macOS Mach-O + kqueue | ❌ | 新后端 + 新事件层 |
| wasm32/64 | ❌ | 新后端 + 线性内存模型 |
| Android | ❌ | 依赖 AArch64 + NDK 链路 |

## 5. 性能专项

按"赢回幅度 / 成本"排序：

| 专项 | 预期收益 | 前置 / 风险 |
|---|---|---|
| **SHA-NI 64 轮序列** | SHA-256 65 ms → ~3 ms（20×） | 基础设施已就绪（`cpuid_sha` + 4 条 SHA 指令 + xmm 槽）；**本机 CPU 无该扩展**，必须先写 Python mini-emulator 验证 8 条 xmm 指令语义，否则错 hash 比慢更糟 |
| **GHASH 4-bit nibble 表** | AES-GCM 15–20× | H 固定，会话级惰性生成 16×16×16B 表；FIPS 向量必须仍全过 |
| **AES-NI** | AES 数量级 | 与 SHA-NI 同批进编码器，保留标量降级 |
| **LICM 根修** | 普适（所有循环） | 根因是 x64 分配器布局敏感段错误；修好前 LICM 只能关 |
| **loop_sum 三件套** | 循环 10.8 → ~4 cycles/iter | ① phi copy 消除（分配器 coalescing）② do-while 变换（CFG 要容错 jcc 回边）③ cssub 形态 |
| **JSON memchr 化** | 2 ms → ~1 ms | 需 `memchr` / 找字符内建 |
| **gzip lazy matching** | 25 ms → ~15 ms | 匹配器改造，zlib 互操作必须仍全过 |
| **AVX2 点积** | 新形状 | 需 `vpmullq`（SSE2 64 位乘语义不一致） |

> 性能实验两条铁律（两次回滚换来的）：
> 1. 单点核对全对 ≠ 装起来对——必须反汇编对照或单元素 trace。
> 2. 前置条件不满足就回滚并登记重启条件；错误代码比没有代码更糟。

## 6. 优先级

### P0 —— 让"一个真实服务能上线"

1. TLS：记录层 → 握手状态机 → X.509 最小子集（**X25519 已于 v1.20 完成**）
2. HTTP 客户端 + DNS（DNS 需要 UDP，已有）
3. 路由 / 静态文件 / MIME 最小层
4. `result` 允许 struct 载荷 + 库层错误对象（停止"库函数只能退出进程"）
5. 多 member gzip + zlib 容器解码（`inflate_raw` 已可处理裸流）

> v1.19 已完成原本的 P0 第 1 项（gzip 解码），并把 `std/math`、`std/hex`、
> 日志级别过滤一并补上；v1.20 补上 TLS 的最后一块密码学零件 X25519。

### P1 —— 让"语言能撑住中型程序"

1. 泛型推导 + 多类型参数（`f[int]` → 能推就推）
2. 命名空间 / `pub` 可见性（止住 `http_` / `ws_` 前缀膨胀）
3. `map[str]Struct`、`vec[map]`
4. 函数值放宽：8 参、允许 struct 实参
5. `defer`（接口装箱生命周期的前置）
6. IPv6、TCP 批量收发
7. 包管理 semver + registry
8. 自举主线：函数体 parser 收敛（当前分叉数见 `06-status.md`）

### P2 —— 生态

1. 宏（前置：编译期 AST API）→ 反射（前置：类型元数据段）
2. 所有权/借用检查扩到 vec 与引用
3. FFI：PE 导入表已有白名单机制，推广到"用户声明库 + 符号白名单"
4. DWARF/PDB → LSP → 文档生成
5. 自举 **9/9**（目标）+ 三轮固定点闭环
6. macOS Mach-O + kqueue、wasm

## 7. 历史：已修掉的问题

### 7.1 文档债（2026-10-21 / 2026-10-22）

2026-10-21 的审计发现文档比代码落后 2–3 个版本，其中三条被外部评估引用为"能力缺失"，
实测均不成立（`import` 扁平合并已实装、`vec[Struct]` 可用、`str` 已是长度前缀 ABI）。

2026-10-22 的第二次审计发现同类问题再次发生（版本号停在 v1.10、回归数四份文档四个值、
`vec[vec[T]]` 在三份文档里仍写"不支持"），因此做了文档重构：

- 全部文档收敛到 `docs/`，规则见 [`00-convention.md`](00-convention.md)；
- **数字只在 `06-status.md` 与 `versions/*/CHANGELOG.md` 出现**，由门禁强制；
- 每次任务提交建 `versions/vX.Y.Z/CHANGELOG.md`。

结论没变：**文档债本身就是缺陷**——它让评估者系统性低估项目，也让新写的库绕远路。

### 7.2 编译器缺陷（2026-10-22 v1.19）

| 缺陷 | 症状 | 根因 | 回归 |
|---|---|---|---|
| 浮点比较整型化 | `if -2.0 > -1.0` 成立、`while x > 0.0` 对负数判反 | `branch()` 对比较表达式直接发 `jcc`，没检查操作数是否浮点；IEEE754 负数的位模式在整数序下相反 | `tests/t64_math.qma` |

表达式位置（`let c = a > b`）一直是对的——它走 `arith()` 的 `fcmpset` 分支。
只有条件位置（`if` / `while`）漏了浮点分流，属于"两条路径实现不一致"的典型。
