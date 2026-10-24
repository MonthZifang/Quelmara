# 能力缺口与路线

> 本文只登记**做不到什么**和**先做什么**。实测数字见 [`06-status.md`](06-status.md)，
> 不在此重复。每条尽量给出复核方式或前置条件。
>
> 标记：✅ 已可用 ｜ 🟡 部分可用（边界见右栏） ｜ 🚧 规范已定、实现未做 ｜ ❌ 未做

## 1. 语言层

| 能力 | 状态 | 缺什么 | 影响 |
|---|---|---|---|
| 用户泛型 | ✅ v1.36 | 多类型参数 + 调用点推导（流不敏感、尽力而为）；显式实例化仍在 | 调用点不再啰嗦；推不出编译期报错并提示显式 |
| 泛型 struct / 泛型方法 / 泛型 enum | ✅ v1.63 | **泛型 struct**（解析期单态化 `Box[int]` → `Box__int`）；**泛型方法**（`impl Box[int] : Iface` 具体实例 + `impl Box[T] : Iface` 模板按实例展开成 `Box__X__m`，静态派发与 vtable 都通）；**泛型 enum**（`Opt[int]` 现场合成枚举，构造/模式/穷尽性按实例检查，嵌套实例与容器元素可用）。边界：实参须具名类型；泛型函数里 `Box[T]`/`Opt[T]` fail-fast；泛型 impl 泛型 enum 未做 | 通用容器与自定义和类型（Opt/Either/Tree）都能写；库层不用再按类型手写特化 |
| 类型约束（trait bound） | ✅ v1.61 | **能力约束** `Ord`/`Eq`/`Num`/`Bit` + **接口约束**（`impl T : Iface` 表校验）：声明期查"模板体不超过约束"，实例化期查"实参满足约束"，没写约束的模板按体内实际运算核对具体类型；泛型 struct 只接受能力约束 | 违反在调用点编译失败（此前"T 须支持 <"只是文档约定，struct 实参被静默按地址比较）；聚合（struct/enum）不满足 `Eq`，见 §7.6 |
| `map[K]V` | ✅ v1.41 | V 支持 int/bool/str + 具名 struct/enum（值槽按 agg 布局 N 字，set/get 按值拷入拷出）；**键仍限标量**；复合容器（vec/map）作值不做（需 mapinner 标签链） | 配置表/符号表不再拆平行 map |
| `vec[T]` | ✅ v1.37 | 标量/str/具名聚合/嵌套 vec（任意深度）/map 句柄全支持；**下标 `v[i]` v2.13 才真的能编**（此前只有 `.get(i)` 可用，`std/sort` 因此编不出来，见 §7.15） | 元素即用即取，无扁平化成本 |
| struct 内嵌套聚合 | ✅ v1.39 | 字段可装 vec/map/chan/slice/struct——vec/map/chan 按句柄 1 槽、slice 按 2 槽视图；方法/下标/派发全部可用 | 无（句柄语义即设计） |
| 函数值 | ✅ v1.42 | `callr` 8 参 + struct/slice 实参（x86-64 第 7 参起走栈传参；A64 用满 X0-X7，>8 fail-fast）；裸函数名**无捕获**（捕获用闭包，见下行）；聚合返回值的目标不可间接调用 | 回调带聚合载荷可行；闭包是独立条目（v1.95 已绿） |
| 所有权检查 | ✅ v1.84 | rc 线性（use-after-drop / double-drop / move-then-use + 泄漏警告）+ **视图生命周期**（本帧栈视图从 return / 堆容器 / spawn 逃逸即报错，含结构体字段的污染传播）+ **写别名**（同基址独立视图区间可能重叠且都被写）+ **跨线程**（rc 句柄、栈视图进 spawn）。不查：多线程写同一堆内存的**数据竞争**、`mem_str` 裸指针来源、跨函数别名（被调方写 `[]T` 形参）。边界与口径见 `02-language.md` §8.3 | 切片/结构体字段的生命周期错误编译期拦下；仍**不是**"Rust 那套借用检查"（没有独占借用，切片零拷贝共享是显式语义） |
| `interface` | ✅ v1.97 | **原四项边界全清**：① **装箱带引用计数**（v1.83，块布局 `[rc][字节数][payload]`；块尾 / 提前 `return` / `break`·`continue` / 赋值替换 / 容器元素各走各的 retain·release，1 MB 堆上限下跑完 19 MB 装箱量）；② **同类型跨接口同名方法共存**（按接口名二次 mangling `Type__Iface__m`，两套槽位各走各的；静态调用 `t.m()` 报歧义并指引转接口值）；③ **接口与 impl 不必同源文件**（`pub interface` + 跨文件种子；同名同签名重复声明幂等，签名不一致报冲突，v1.88 起宽松占位不再冒充声明）；④ **AArch64 vtable 已接**（v1.97，代码段尾部一张 8 字节槽函数指针表 + `BLR` 派发，模拟器执行级 7 用例）。边界：接口值的静态类型是接口名，`impl T : Drop` 不会在装箱释放时被调用（`drop_table` 按具体类型挂载，v1.86 那条线）；热点循环每次装箱仍有 ~20 ns 分配成本（见 `06-status.md` §3.4j） | 热点循环装箱不再涨堆；每轮装箱约 20 ns、vtable 派发比静态调用慢约 0.6 ns |
| 错误处理 | ✅ v1.38 | result/option 载荷支持具名 struct/enum——库层可把 errno+上下文装入 Err（std 库尚未批量改造为富错误，属标准库工作） | 错误对象成为可能 |
| 模块系统 | ✅ v1.99 | 四件齐：① **`pub` 可见性**（v1.43）；② **限定语法**（v1.44，`lib.fn()` / `lib.Enum.Variant` / 限定模式）；③ **跨模块同名声明**（v1.99，per-module mangling：只在真重名时给导入方加 `<模块>__` 前缀，主文件保留原名；未限定引用按"本文件 > 唯一外部 > 歧义报错"解析；同名类型的方法与派生函数跟着换前缀）；④ **模块版本**（v1.99，`module util "1.2.3"` 声明 + `import util ">=1.2"` 要求，同 major 且 >=，不做 semver 求解——那是 qpm 的活）。边界：const 在解析期内联不参与 mangling（同名不同值仍报错）；同名 interface 视为同一份契约（签名一致即幂等）；限定 struct 字面量仍不做（用 pub 工厂函数） | 库层不用再靠 `http_`/`ws_` 前缀避免撞名；第三方库可以同名共存并按模块限定调用；导入方能声明"我要的版本" |
| 整数宽度 | ✅ v1.40/v1.56 | **语义全覆盖**：窄值在所有存储点截断（let / 形参 / 返回值 / 赋值 / struct 字段 / enum 载荷 / vec 元素 / 定长数组 / **切片别名写入**）；表达式内部按 C 提升不截断。`vec[u8]` 槽仍 8 字节属**内存打包**，已移到 §5 性能专项 | 不用再自己 mask；二进制格式读写窄值安全 |
| `@simd` | ✅ v1.85 | **四种形状全接**：int 归约（`paddq`）/ f64 归约（`addpd`）/ **f64 点积** `a[i]*b[i]`（v1.60，`mulpd` 两路）/ **int 点积**（v1.85）。int 点积没有 `pmulld` 可用（x86 无 64 位整数 SIMD 乘法），改用 3×`pmuludq` 拼 64×64→低 64，与标量 `imul` 逐位等价（含回绕）。点积要求两数组与累加器同类型，混写编译期报错。**仍不是向量化器**：只认这四种语句形状，其余循环原样走标量；4 通道与 32 位元素特化是性能问题，已转 §5 | 归约/点积不用手写；通用循环自动向量化仍没有 |
| 并发 | ✅ v1.98 | **原子原语双后端**（x86 `lock` 前缀 / A64 `LDAXR`+`STLXR` 重试）：`atomic_add`·`atomic_cas`·`mem_xchg`·`atomic_fence`·`now_cycle` 都能在 A64 上发射并执行；新增 `mem_load_acq`/`mem_store_rel`（x86 零成本 mov、A64 LDAR/STLR）、`thread_yield()`、`cpu_ns()`。**栈 pop 的 ABA 结构性消除**：pop 先取每栈消费者锁再 CAS head，正确性不再依赖"节点地址永不复用"这条隐含前提（单消费者走 `stack_pop_single` 快路径）。**WaitGroup 不再烧核**：三段退避（64 次 `pause` → 1024 次让出 → 1 ms 睡眠）。边界：A64 仍无线程（`spawn`/`parfor`），那里的并发原语只能单线程用；`wg_wait` 不是 futex park，长等待唤醒粒度 = 一个 `sleep_ms(1)`（本机实测见 `06-status.md` §3.5b） | 高竞争场景不必再加保护；要更低唤醒延迟仍需 futex/WaitOnAddress（见 §5） |
| 编译期求值 | ✅ v1.58 | `const` 右值：整型算术 + const 引用 + **const fn 调用**；`const fn` 支持 int/bool 形参与返回值、let/赋值/if/while/return、算术/比较/逻辑/位运算、递归（≤64 层），按有符号 64 位回卷（与运行时逐位一致）。仍无：str/浮点求值、泛型 const fn、跨文件 const fn 种子 | 常量表/尺寸计算/位掩码可在编译期算完，且与运行时同值 |
| 闭包 / 捕获 | ✅ v1.95 | 语法 `fn(x: int) -> int { ... }`（表达式位置）；值 = `{code, env}` 两字聚合；创建时按值捕获**1 字值**（int/bool/f64/str + vec/map/chan 句柄）；环境在堆上可逃逸（返回 / 存 `vec[closure]`）；同一函数内创建的闭包带编译期签名（返回值打标记、实参转换、聚合返回值开出参槽）。边界：捕获聚合/切片/数组/rc、体内写捕获变量、裸函数名当闭包传——三者编译期拒绝；递归与跨函数签名不支持（后者退回"按标量处理"）；C 后端 fail-fast | 回调不再需要把上下文塞进全局或结构体；`std` 的回调式 API 可以改成带捕获的写法 |
| FFI（自研后端） | ✅ v1.87 | **`@ffi("dll"[, "Sym"])`**：任意 DLL + 符号名直接进 PE 导入表，Win64 寄存器类（整数 `RCX/RDX/R8/R9`、浮点 `XMM0-3` **独立计数**）+ 第 5+ 个同类实参落栈 + `cstr`/`cstr_read` 字符串编组；返回值 `RAX`/`XMM0`，`bool` 按 32 位 BOOL 零扩展。边界：**仅 Windows PE**（ELF 后端是静态 ET_EXEC，无 `PT_INTERP`，编译期 fail-fast）；无变参（`printf` 族的 `AL` 约定）；无按值结构体；无回调 thunk（自研 ABI ≠ Win64，函数地址传给 `EnumWindows` 会被错位读参）；DLL/符号名写错是**加载期**错误 | user32/ntdll/ucrtbase/第三方 DLL 都能直接调；回调与变参仍需编译器侧改造 |
| `defer` / RAII / `Drop` | ✅ v1.93 | **`defer` 语句 ✅ v1.48**：块级作用域、LIFO、执行到才登记、取退出时的值；形态限表达式/赋值；C 后端 fail-fast。**`Drop` ✅ v1.93**：`impl T : Drop { fn drop(t: T) }`（内建接口，不用声明）→ `let` 绑定的聚合变量在块尾 / `return` / `break` / `continue` **逆序**析构，跑在 `defer` 之后，析构体收到**原对象地址**（`c.fd = -1` 落在原对象上）；`let b = a` 与 `return a` 按移动处理（不双重析构）。边界：**按绑定**析构——形参 / 容器元素 / 字段副本不析构（只泄漏不悬垂，要唯一所有权用 `rc[T]`）；无字段 drop glue；`exit()` 不跑析构；C 后端不支持 | 资源生命周期从"约定"变成"语法"：fd/锁/缓冲在作用域退出自动释放 |
| 宏 / 反射 | ✅ v1.96 | **三件套齐**：① 属性宏 `@derive(Json, Eq, Show)` 作用于 **struct 和 enum**（enum 的 JSON 是 `{"$v":"变体", 载荷...}`，见 `02-language.md` §4.8.1）；② **通用 token 宏** `macro 名字(形参) { 记号 }`——语法分析前按记号替换，能生成声明 / 表达式 / 注解本身；③ **反射** `refl_*[T](i)`：常量下标折叠成字面量，**运行时下标改写成按需生成的 if 链**（能写"遍历字段"的循环）。字段类型：int 族 / bool / str / **f64** / 本文件 struct·enum / vec[这些]。边界：泛型 struct·enum 模板不能直接派生（先实例化）、`f32` 字段不支持、宏无卫生性且不能拼接记号、运行时反射是 O(n) 分支不是 O(1) 表、反射不能读字段值 | 序列化 / 判等 / 展示不用手抄字段表；聚合可按值判等（原生 `==` 仍是地址比较，§7.6） |
| 字符串插值 / `format` | ✅ v1.61 | **插值字符串 ✅**（`f"n={n}"`：int/bool/f64/str，段内任意表达式，`{{`/`}}` 转义，单次分配；比手写 `+` 链快约 10%）；`format(fmt, ...)` 变参仍无——插值已覆盖该用途 | 拼接不再冗长；`+` 链已被 v1.3 融合成单次分配，不存在 O(n²) |
| `switch` | — | 用 `match` 代替（设计选择） | — |

## 2. 标准库

| 类别 | 缺什么 | 撞到什么场景 |
|---|---|---|
| 压缩 | ✅ v1.32：多 member gzip 拼接流 + **zlib 容器**（RFC 1950，含 adler32 校验）；`adler32` 也可单独用 | 仍无 zlib 预置字典（FDICT）与 raw inflate 的窗口复用 |
| TLS | **根证书库**（信任锚管理）、**P-384 / SHA-384**；RSA（PKCS#1 + PSS）与链校验 v1.27 已实现 | 无法自动信任公网证书；部分站点链验不过 |
| HTTP 客户端 | ✅ v1.50：`std/httpc`（URL 拆分 / 请求构造 / 响应解析 content-length+chunked / 重定向判定，纯函数）+ `std/httpc_net`（get / get_tls / get_follow，Windows，loopback E2E 实测） | 仍缺：连接池 / 流水线、自动解压 Content-Encoding、HTTP/2、Linux DNS |
| 路由 / 中间件 | ✅ v2.10：`std/router`（`/users/:id` 参数段、尾部 `*` 通配、query/尾斜杠归一化、参数捕获、方法白名单）+ **`std/http` 已可导入**（原有 40 个顶层函数里 29 个补成 `pub` + `///`，本版新增的 10 个路由/中间件 API 也全部公开——现在 54 个顶层函数 / 39 个公开）并带**路由表 + 中间件链**：`http_route`（64 条）/ `http_use`（16 个；1 = 继续，0 = 终止）/ `http_dispatch` / `http_param` / `http_query`；匹配零拷贝（路径字节直接喂 `route_match_bytes`，注册期归一化 + 字面前缀过滤）。边界：先注册先匹配（不按具体度排序）、无正则路由、405 不带 `Allow`、handler 必须裸函数名（闭包是两字聚合，`callr` 进不了 reactor）；`std/sse` / `std/ws` 仍不可导入（§7.13） | 路径分发不用再手写 if 链；日志 / 鉴权 / gzip 协商按中间件链挂上去（`examples/http_router.qma` 是完整样板） |
| 静态文件 / MIME / cookie / session / multipart | **MIME ✅ v1.67**（`std/mime`）；**静态文件 ✅ v1.69**（`std/staticfile`：URL 解码 / 穿越防护 / index / Cache-Control / ETag / Range + `static_serve` 直接产出 200/206/403/404 完整响应）；剩 If-None-Match / Last-Modified / 分块发送 / gzip 协商；**Cookie ✅ v1.70**（`std/cookie`）；**Session ✅ v1.71**（`std/session`：TTL 惰性过期 / 滑动续期 / 墓碑销毁；sid 可预测、无后台 GC、无并发保护）；**multipart ✅ v1.72**（`std/multipart`：boundary / 字段与文件 / CRLF 正文） | 这条 §2 行已全绿 |
| `chunked` 请求体 | 回 501 | 部分客户端上传 |
| DNS | Windows 走系统 `getaddrinfo`（v1.25；v2.07 起 `AF_UNSPEC`，v4/v6 两个家族都返）；Linux 无解析器 | Linux 只能写 IPv4 字面量 |
| IPv6 | ✅ v2.07：**TCP 全链路**——`tcp_listen6`（AF_INET6 + `sockaddr_in6` 28B + `IPV6_V6ONLY=0` 双栈，同一端口同时接 v4 映射连接）；`tcp_connect` 的 family 从 `AF_INET` 放宽到 `AF_UNSPEC`（IPv6 字面量与 AAAA 记录直接可用，失败沿 `ai_next` 回退——`localhost` 先给 `::1` 时 v4-only 服务端仍能连上）；`tcp_peer_raw`（`getpeername` 的 20 字节视图）+ `std/net/addr`（`ip_family` / `ip6_parse` / `ip6_format`（RFC 5952）/ `ip4_format` / `peer_ip` / `peer_port`，双栈上的 `::ffff:a.b.c.d` 还原成点分） | 仍缺：**UDP 没有 v6**（`udp_sendto` 的地址参数是 u32 网络序，要改成 16 字节 API 才带得动 v6）；`net_serve`（IOCP reactor）仍只绑 v4；Linux 侧 `tcp_connect`/`tcp_listen6` 编译期报错；无 zone id（`%eth0`）、不做 `::a.b.c.d` 兼容地址归一 |
| TCP 批量收发 | 只有单次 `tcp_send/recv` | 高吞吐场景 syscall 太多 |
| 可靠 UDP | UDP 四件之上未做 | 游戏/实时传输 |
| 日志 | ✅ v2.03：**`std/log`**（级别过滤 / **绝对时间戳**（RFC 3339 毫秒 + 时区偏移，同一毫秒内复用缓存）/ **stdout·stderr 双通道** / 结构化 `k=v` 字段 / 每行持锁不交错）+ **`std/logfile`**（追加写 + **按大小轮转** `.1`…`.keep` + 64 KB 攒批 + `logf_tee` 同时打控制台 + 共享打开可边写边 tail）。边界：文件通道走 `std/fs`，**仅 Windows PE**；攒批的崩溃窗口最多 64 KB（要即时落盘调 `logf_flush`，掉电仍要 `fs_sync`）；不做 syslog/网络输出、不做压缩归档、级别不能热加载 | 生产可观测性：日志能对上外部系统的时钟，stdout 留业务、stderr 留诊断，文件自己滚动；写路径 434 ns/行（173 MB/s），被过滤的行 2 ns |
| 编码 | ✅ v1.29：`std/utf8`（严格解码/编码/校验/按字符切片）+ `b64url_*`（hex v1.19 已补） | 仍缺 Unicode 规范化与大小写折叠；**f64 打印已修（v1.51）**：定点/科学计数按 C 后端口径逐位一致（`__f64_to_str` 有限值路径漏长度前缀已补），仍缺最短往返表示（grisu/ryu） |
| 数学 | ✅ v1.47：`exp`/`log`/`log2`/`log10`/`pow`/`sin`/`cos`/`tan`/`asin`/`acos`/`atan`/`atan2`/`sinh`/`cosh`/`tanh`/`hypot` + 常数助手（Cody–Waite 双字归约；sin/cos 误差随 |x|·1.1e-16 增长，多字 π 归约未做） | 图形、统计、复利 |
| 哈希 | ✅ v1.35：SHA-1 / SHA-256 / FNV-1a 32/64 / MD5（仅兼容用途）；✅ v1.53：**SHA-512 / SHA-384 + HMAC-SHA512** + **CRC-64/XZ**（FIPS 180-4 / RFC 4231 / ECMA-182 向量全过） | ✅ v1.55：**BLAKE2b**（RFC 7693，含 keyed 与变长输出）；仍无 SHA-512/224、SHA-3 |
| 数据结构 | ✅ v2.05：**set[int]·set[str]** / **deque** / **LRU**（自建开放寻址表 + 双向链表，单句柄）/ **RingBuf·MinHeap**（`std/ds` 补成公开模块：13 个 `pub` + 全量 `///` + `tests/t129_ds.qma` + `bench/ds_bench.qma`） | 边界：`std/ds` 只存 int（`MinHeap` 是 key-only，句柄打包进 key 低位）；空/满哨兵 -1 与元素值同域；LRU 的 key 只有 int（字符串先 `fnv1a64`）、无 TTL、无容量自适应；全部非线程安全 |
| 定时器 | ✅ v2.08：**`std/timer`** 从"不可导入"到可用——轮询式定时器（无后台线程/无回调），二叉最小堆落在 **mem 块**（`static_word(13)/(14)`）而非 `vec`（`vec` 句柄存进静态字会丢类型标签）；`timer_after`/`cancel`/`poll`/`pending`/`clear` 五个 API，push/poll 均 O(log n)，取消 O(1)；`tests/t131_timer.qma` + `bench/timer_bench.qma` | 边界：**轮询式**——没人 poll 就不会触发（没有后台线程）；`timer_pending` 是 O(n) 扫描；同一时刻到期按 id 出堆（不做优先级）；非线程安全；进程退出不清理（`timer_clear` 要自己调） |
| 持久化 | ✅ v1.102：**`std/fs`**（open / read / write / seek / size / sync / close / rename，`@ffi` 直调 kernel32）+ **`std/kv`**（追加日志 + 内存索引：put / get / del / has / len / compact / sync，重开重放，**撕裂尾与垃圾尾都能恢复**，压缩把覆盖写后的日志压回一半）。边界：**Windows PE**（ELF 后端无动态链接器，`@ffi` 编译期 fail-fast）；值全量驻留内存（内存 ≈ 数据集大小）；无 SQL / 事务 / 并发写保护；**写路径已批量提交**（v2.01：每 64 条合并一次 `WriteFile`，`kv_sync`/`kv_close`/`kv_compact` 前冲刷；代价是进程被强杀最多丢最后不足 64 条，掉电仍要 `kv_sync`）；**语言内建仍只有元数据操作**（`file_exists`/`file_size`/`fs_mkdir`/`fs_remove`），读写走 `@ffi` 是当前方案，内建 `file_*` 要同时改 x86 与 A64 两个发射层，未做 | 配置 / 会话 / 计数 / 缓存元数据都能落盘；SQL 与大于内存的数据集还要 mmap 视图 + 页缓存 |
| 正则 | ✅ v1.57 | `std/regex`：回溯 VM（字节码 + 显式栈，无 AST），字面字节 / `.` / 字符类（含 `\d \w \s` 及否定式）/ 转义 / 贪婪量词 `* + ? {n} {n,} {n,m}` / 交替 / 分组 `( )`·`(?: )` / 锚点 `^ $`；`regex_compile` / `match` / `match_full` / `exec` / `find` / `replace` / `replace_all`。**不做**：捕获组、反向引用、环视、懒惰量词、多行模式、Unicode 属性；病态模式由 400 万步上限兜底。期望值全部由 Python `re` 现算的差分对拍见 `tests/t99_regex.qma` | 文本清洗 / 表单校验 / 路由匹配不必再手写逐字节扫描 |
| CLI | ✅ v1.29：`std/cli`（`--k=v` / `--k v` / `-k v` / 布尔 / 位置参数）；无子命令与自动 usage | 子命令要自己 switch |
| 国际化 | 无 locale、无 Unicode 分类、无大小写折叠 | 多语言输出 |

## 3. 工具链

| 项 | 状态 | 缺什么 |
|---|---|---|
| 调试器 | ✅ v1.75 / v1.80 | **两种调试信息一份数据源**：`.qlmdbg`（自研 JSON，带 `bind`/`last` 活跃区间，调试器读它）+ **标准 DWARF v4**（`.debug_abbrev`/`info`/`line`/`loc`，外部工具读它，地址用 RVA）。`quelmara debug` 源码断点（`break 文件:行` / `break 函数`）/ `step` / `next` / `finish` / `print a.b.c` / `locals` / `bt` / `list`（Windows 调试 API，int3 软断点 + RBP 帧链，零外部依赖）。边界：仅 Windows PE（ELF 后端未接节写出）；**不发 PDB**（无 MSVC 工具链可验证）；库函数帧无行号（`<library>`）；调试构建默认不内联（否则源码断点静默不命中）；变量只在"最后一次使用之前"可见；`print` 限变量与字段路径。测试 `tests/debugger_test.py` + `tests/dbg_test.py` + `tests/dwarf_test.py` |
| LSP / 补全 | ✅ v1.91 | **语义索引 + 补全/跳转/引用/重命名/悬停/大纲/全局符号**（`quelmara lsp`，stdio LSP 3.17 子集，零依赖）。索引是**容错**的（不经过编译器前端，一个语法错误不会让整篇符号消失），词法另有位置信息并与 `qlm.tokenize` 全仓库对拍。边界见 `05-toolchain.md` §1.4：**诊断只到词法/结构层**（不做类型检查）、`didChange` 整篇重建（无增量索引）、成员解析靠语法推断（推不出就退化为本文件成员）、重命名只改解析得到的引用。编辑器里从此能补全、能跳转、能改名 |
| 文档生成 | ✅ v1.92 | **`///` 是语言层语法**（`02-language.md` §2.4）：紧贴顶层声明、`//!` 模块文档、空行即脱离、`////` 不算、缩进不收；前端按行挂到声明上（`f["doc"]` / `type_docs` / `module_doc`），**不进记号流**（lexdiff/parsediff 契约不变）。工具链 `quelmara doc`：Markdown/JSON、`--check` 漂移、`--missing` 覆盖门禁；std 全库 387 个公开声明 100% 覆盖，`03-stdlib.md` 与源码同源。边界：只收顶层声明（`impl` 内方法文档未做）、不做交叉引用/链接校验、不渲染 Markdown、全量不增量 | API 文档从源码长出来；门禁拦『写了文档却挂不上』与『声明没文档』 |
| 库归档 `.qla` | ✅ v2.11 | **目标文件格式**：`QLA1` 容器（header JSON + `meta` 段 + 全局数据段，段级 + 整体 sha256，**确定性字节**——同源码同编译器同字节，sha256 即身份），内容是**已降级+已优化**的 QuIR + 全局区 + 符号表 + 类型布局，不含源码也不含机器码。**函数级增量**：每个函数按「自身 AST + 类型环境摘要（类型表/接口/析构表/配置）+ 被引函数的签名 + **内联传播**」算哈希，未变就复用档案里的 IR（无改动时产物与全量构建**逐字节相同**）；`build --incr` 实测 2.4×（下限是解析）。**二进制库**：`build --lib` 不做 DCE、带符号表与类型布局，`--lib-input` 只取签名与布局、`link` 按名字解析合并 IR（`call`/`fnaddr`/vtable 槽），**源码可以不分发**。边界：仅 PE/x86-64；档案跨编译器/跨配置不复用（指纹 + 配置摘要不符直接报错）；改被内联的小函数会连带重编调用链（正确性要求，见 `05-toolchain.md` §1.8）；泛型模板与 `const` 不从档案导出；无跨档案内联；`--dbg-info` 不走档案。见 `05-toolchain.md` §1.8、实测 `06-status.md` §3.22、回归 `tests/qla_test.py`（32 条） |
| 包管理 | ✅ v1.99 | **qpm 全链路**：三种来源（path / git / **registry**）+ **sparse 索引**（每包一个 JSON，解析不下载包体）+ **确定性 `.qpk`**（同源码同字节，sha256 即身份）+ `publish` / `yank`（同版本不可覆盖，撤回不删历史）+ **传递依赖**（读每个包自己的 `[deps]`，同名区间取交集选最大版本，git 归一化 rev，跨来源直接报冲突，环可安装并提示）+ 锁 v2（`--locked` 可复现、`verify` 锁/清单/磁盘三方校验、`tree`）。边界：**一个项目只从一个 registry 解析**、无签名/公信链、无多租户权限（只有 Bearer token）、无构建钩子、无增量（每次重解析重落地）。细节见 `05-toolchain.md` §4 |
| 增量 / 并行编译 | ✅ v1.100 | **单元级增量**（内容寻址缓存：编译器指纹 + 主文件 + **精确 import 闭包** + 源根目录清单 + `QLM_*` 环境快照，任一不符即重编；产物 sha256 校验，半截/损坏的条目不会交出去）+ **单元级并行**（`build -j` 多源、`test -j` 多文件，进程池，输出顺序与串行一致）。边界：这一层省的是**整个单元**的重编；函数级增量由上一行的 `.qla` 提供（v2.11），两者叠加：缓存未命中时，`.qla` 仍能复用没变的函数；单文件内部不并行；并行收益受进程创建成本限制。见 `05-toolchain.md` §1.7 / §1.8、实测 `06-status.md` §3.14 / §3.18、回归 `tests/cache_test.py`、`tests/qla_test.py` |
| 性能回归门禁 | ✅ v1.88 | **`tools/dev/bench_gate.py`**：`bench/gate_bench.qma`（**Quelmara 写**，输出 `QLMBENCH`/`QLMCAL`/`QLMDIGEST`）+ 校准归一化（换机器仍可比）+ 噪声闸 + 双模式（本机基线 `--check` / CI 同机交错 A/B `--ab REV`）+ 校验和与体积硬判；CI 独立 `perf` job。边界：基线按 CPU 型号分 key（换机器 SKIP，不误判）；不做统计显著性检验（min-of-N + 离散度）；不是微架构计数器（无 cycles / 分支失败率）；`quelmara bench` 的进程墙钟口径保留，两者分工见 `05-toolchain.md` §1.3 |
| 覆盖率 / fuzz | ✅ v1.83 | **行 + 分支覆盖**：`quelmara cov` = 调试器逐行/逐 `jcc` 断点采集 + `tools/qlm_cov.qma`（**用 Quelmara 写**，自己读 PE 节表 + `.qlmdbg` JSON）汇总；行/分支/函数/文件四级，`--min`/`--min-branch` 双门禁，`--append` 多次运行累加。分支判定用 EFLAGS 不单步；只收"目标为语句入口"的源码级分支（`assert` 失败块/越界 panic 块/`args()` 展开不计入）。**fuzz ✅**：`quelmara fuzz` = `tools/qlm_fuzz.qma`（Quelmara 写的变异器，确定性 LCG）+ `qlm_fuzz.py` 判定（built/rejected/deep/bug/slow 五分类，`bug` 退出码 1）。边界：不采条件级 MC/DC（`&&` 子条件按各自 `jcc` 自然计数）；采集靠断点，大文件线性慢；fuzz 默认只跑前端；非 UTF-8 源文件抛 `UnicodeDecodeError`（§7.11） |
| 服务端运行时自举 | ✅ v2.12 | **IOCP reactor 从 stage-0 搬到 `std/net/reactor.qma`**（Quelmara 源码）：v1.4 起手搓的 400 行 IR（`__net_serve` / `__net_worker` / rec 池 / accept 循环）全部删除，stage-0 只留 `thread_start`（Win64 线程入口 ABI）与 `net_config`（编译期读 `[net]`）。worker 数 = `[net] io_threads`（默认物理核数），完成端口共用一个（per-reactor 实测更差，见 `06-status.md` §3.23）。分层：`std/net/reactor.qma` 仅 Windows PE（`@ffi`）/ `std/net.qma` 不含 `@ffi`（但 `tcp_*` 内建目前也只在 Windows 实现）/ `std/net/core.qma` 槽位层。边界：**仍只有 Windows**（Linux epoll/io_uring reactor 未做）；accept 在**主线程单点**（未做多 acceptor + `SO_REUSEPORT`，`[net] reuse_port` 目前是声明未用）；`max_conns` 用 `atomic_add` 计数、拒绝发生在 accept 之后（连接已被内核接受一次）。回归：主回归 + `tests/http_router_test.py`（20 项 E2E） | 服务端链路（http/ws/sse/router/reactor）100% 本语言实现；改事件循环不用再碰编译器 |
| stage-1 编译器 | 🚧 v2.29 | **`bootstrap/qlmc/qlmc.qma`**（约 5.7 千行 Quelmara）：`.qma` -> PE32+ **全链路**，后端为三地址 IR + 两段式寄存器分配 + `cmp/jcc` 融合 + **按函数多核并行**（`-j N`，产物与线程数无关）。**子集 S15**：int/bool/str、struct、定长数组 `[N]T`、enum/match、vec[T]（**容量可变，满了翻倍**）、map[K]V、切片 []T、defer、import、@ffi、**闭包（无捕获）**、聚合作形参/返回值、**形参与实参不限个数（第 5 个起走栈）**、`for`/`break`/`continue`、`while`、`let`/`mut`、`const`、`print`、`len`、`assert`、递归、算术/比较/短路逻辑、**位运算与移位（`& | ^ ~ << >> >>>`）**、**进制字面量（`0x`/`0b`/`0o` + 下划线）**、str 拼接与内容比较。与 stage-0 **逐字节差分**通过（`tests/qlmc_test.py`：20 组用例 + 并行确定性 2 条）。**缺**：**`const` 的表达式初值**（自举的下一个硬阻塞：`qlmc` 编译自己源码时报 `line 236: const 只支持整型字面量`，即 `const TBL_SIZE = EN_HDR + 1 + 64 * EN_STRIDE`）、f64、泛型、宏/反射、接口、`rc`/`Drop`、闭包的**捕获**与作形参类型、`pub` 可见性与限定调用、ffi 的 f64/结构体/变参实参、嵌套聚合类型与字段（`vec[vec[T]]` 见 §7.18）、聚合作容器元素、map 扩容、match 穷尽性检查、常量折叠 / 强度削减 / CSE、前端并行。实测数字见 `06-status.md` §3.25 |
| 对拍脚本耗时 | ✅ | `irdiff` 并行后 60 s（原 5 min 41 s）；`emitdiff` 10 s 内 |
| `version` 口径 | ✅ | `tools/stage0/qlm_cli.py` 的 `VERSION` 与最新 `docs/versions/vX.Y/` 一致（v1.24 起 1.24.0，由 `check_docs.py` 校验） |

## 4. 平台

| 平台 | 状态 | 前置 |
|---|---|---|
| Windows PE32+ | ✅ 主平台 | — |
| Linux ELF64 | ✅ 构建级（CI 执行） | 本机无 gcc/WSL；**`tcp_*` 内建没有 Linux 实现**（`import std.net` 编 native 会在 `tcp_listen` 处报 `无法发射指令 ('winapi', … 'WSAStartup')`，v2.12 复核），Linux 侧的网络走 `qlm_uring` 那条 C 链 |
| Linux io_uring | ✅ | 5.1+ 内核 |
| AArch64 | 🟡 模拟器执行级 | 需补 chan/map/spawn/SHA（**atomic/acquire-release 已接**，v1.98）；~~vtable~~ ✅ v1.97（`tests/a64_iface_test.py` 执行级 7 用例） |
| macOS Mach-O + kqueue | ❌ | 新后端 + 新事件层 |
| wasm32/64 | ❌ | 新后端 + 线性内存模型 |
| Android | ❌ | 依赖 AArch64 + NDK 链路 |

## 5. 性能专项

按"赢回幅度 / 成本"排序：

| 专项 | 预期收益 | 前置 / 风险 |
|---|---|---|
| **SHA-NI 64 轮序列** | SHA-256 65 ms → ~3 ms（20×） | 基础设施已就绪（`cpuid_sha` + 4 条 SHA 指令 + xmm 槽）；**本机 CPU 无该扩展**，必须先写 Python mini-emulator 验证 8 条 xmm 指令语义，否则错 hash 比慢更糟 |
| ~~GHASH 4-bit nibble 表~~ | ✅ v1.28 已做：GHASH 段 1.44×，配合 AES T-table 后 GCM 整体 **8.0×**（1369 → 171 ms/MiB） | — |
| ~~AES-NI~~ | ✅ v1.31 已做：CTR 段 63 → **2 ms**/MiB（**31×**），GCM 端到端 171 → 125 ms | 编码器新增 6 条 AES 指令 + `cpu_aes()` 降级；解密方向未接 |
| ~~GHASH 字级化~~ | ✅ v1.32 已做：4-bit 表乘法从逐字节改成 64 位字（一块 1024 次字节操作 → 64 次字操作），GHASH 123 → **34 ms**，GCM 端到端 125 → 36 ms | — |
| ~~GHASH PCLMULQDQ~~ | ✅ v1.33 已做：4 次 `pclmulqdq` + 显式归约，GHASH 34 → **17 ms**，GCM 端到端 36 → 19 ms（相对 v1.28 的 1369 ms 是 **72×**） | 归约用移位折叠（不是 0xC2 常数版），比教科书实现多几条指令；AAD 与非整块尾仍走软件路径 |
| ~~URL 解析 / mem_chr 回归~~ | ✅ v1.35 已查证：没有回归（v1.28 逐字节 85 ms → v1.34 mem_chr 81 ms） | 文档里的 69 ms 是环境漂移（VBS 噪声 ±50%），不要再怀疑一遍 |
| ~~URL / JSON / KV 读取路径~~ | ✅ v2.02 已做：`url_port` **1.55×**、`url_query_get` 1.18×、`json_parse` 41→**49 MB/s**（1.19×）、`kv_get` 190→**160 ns**（1.19×） | 全是「去掉多余分配 / 多余扫描」，不是算法改造；JSON 容器共用暂存、SHA-256 展开两个实验测不出收益已回退。数字见 `06-status.md` §3.17 |
| ~~KV 批量提交~~ | ✅ v2.01 已做：put **16.5 → 2.7 µs/条（6.1×）**、覆盖写 **16.2 → 2.1 µs（7.7×）**；磁盘格式与恢复语义不变 | 每 64 条合并一次 `WriteFile`，`kv_sync`/`kv_close`/`kv_compact` 前冲刷。代价是崩溃窗口 ≤64 条；`kv_sync` 384 µs/条 不变（每条都等落盘）。数字见 `06-status.md` §3.16 |
| ~~`std/ds` 堆下沉"挖洞"~~ | ✅ v2.05 已做：`heap_pop` 同进程 A/B **670–730 → 450–465 ns/次**（20 万元素，**1.5×**） | 每层从"读 4 写 4"降到"读 2 写 1"（末元素取出 → 逐层上提 → 最后落位）。剩余成本是**树高 × 缓存行**（17.6 层随机访存），不是方法调用——换 mem 块也救不了，只有 4 叉堆 / B 树布局才有用。数字见 `06-status.md` §3.19 |
| ~~`std/timer` 的 poll 扫描~~ | ✅ v2.08 已做：`timer_poll` 从"每次弹堆后线性扫平行数组找 id"（O(n)）改成**堆里同时存 id、弹到即返回**（O(log n)）；2 万个取消项 drain **256 ns/项** | 取消改成存活位（O(1)，不搬堆），到期时静默丢弃。10 万个定时器：push **136 ns**、poll **433 ns**、cancel **12 ns**。数字见 `06-status.md` §3.20 |
| ~~SHA-256 轮展开~~ | ❌ **已验证无收益**（v2.02）：8 轮展开 + 状态变量环移位命名，每轮 8 条搬移全部消失，1 MiB 仍是 41–42 ms | 瓶颈不是搬移而是**指令数**：每块约 3000 条，8450 cycles/块 ≈ 2.8 cycles/条；x86 的 `mov` 在重命名阶段就消掉了，省它不省时间。要更快只有两条路：SHA-NI（本机无该扩展）或 `int` 走 32 位指令（现为恒 64 位，`& 0xFFFFFFFF` 掩码消不掉）。数字见 `06-status.md` §3.17 |
| **GHASH 4 路并行** | 现在是串行依赖（每块依赖上一块结果）；4 路聚合可再快 2–3× | 需要重排 CTR/GHASH 交织，收益已不大 |
| **LICM 根修** | 普适（所有循环） | 根因是 x64 分配器布局敏感段错误；修好前 LICM 只能关 |
| **loop_sum 三件套** | 循环 10.8 → ~4 cycles/iter | ① phi copy 消除（分配器 coalescing）② do-while 变换（CFG 要容错 jcc 回边）③ cssub 形态 |
| ~~JSON memchr 化~~ | ❌ **已验证不可行**（v1.35）：1.35 MB 负载 29 ms → 62 ms（**慢 2 倍**） | JSON 字符串普遍 <32 字节，SWAR 每次调用的固定开销（参数搬运 + 调用 + 三次独立扫描）远大于逐字节循环（循环体 4 条指令）。结论：**8 字节扫描只在长串且单字节目标时划算** |
| ~~gzip 编码提速~~ | ✅ v1.30 已做：**25–27 ms → 16 ms（1.6×）**，输出字节不变 | 走的是「mem_diff 批量比对 + 插入/滚动合并」，不是 lazy matching——lazy 只会更慢、压缩率更好 |
| **gzip lazy matching** | 压缩率 -3~8%（时间 +20~30%） | 若要更好压缩率再做；与上面的提速是两个目标，别混 |
| **int 点积加宽（4 通道 / 32 位元素）** | v1.85 的 int 点积是 2 通道 + 3×`pmuludq`，4 拍/2 元素打满 port 0。32 位元素可走单条 `pmulld`（2 元素/条），AVX2 4 通道可望再快 2× | ① 本机（Haswell-EP）**无 AVX2**，要先写 Python mini-emulator 验语义；② AVX2 也没有 `vpmullq`（64 位乘要 AVX-512DQ），4 通道只对 32 位元素成立；③ 32 位元素要求槽压缩——`[N]i32` 现在也是 8 字节槽，见下一条 |
| ~~chan 抢锁先自旋~~ | ❌ **已验证无收益**（v1.98）：双线程往返与 4 生产者争用两个场景，自旋版与让出版的中位数差异都落在噪声里（区间大幅重叠） | 自旋只对"持锁者一定在跑"成立；本机核数少于生产者数时这个前提不成立，收益被"抢到锁的概率"抵消。结论：**测不出好处就不留这份复杂度**，保留"抢不到就让出"；想同时要低延迟与低 CPU 只能上 futex/WaitOnAddress（见下条）。数字见 `06-status.md` §3.5c |
| **futex / WaitOnAddress park** | `wg_wait`/`mutex_lock` 的唤醒延迟从 25 ms 降到 µs 级，CPU 仍然归零 | Linux 要发 `futex(FUTEX_WAIT/WAKE)`（syscall 202，参数 6 个、含超时结构）；Windows 的 `WaitOnAddress`/`WakeByAddressAll` 在 KernelBase 而非 kernel32，PE 导入表要加第二个 DLL；还要处理"唤醒丢失"（park 前重查谓词）。数字见 `06-status.md` §3.5b |
| **vec 窄元素槽压缩**（**已降级**） | 理论收益是 `vec[u8]` 内存 8×，但 v2.02 全库盘点：`std/` 里 `vec[u8]`/`u16`/`u32` 只有 **3 处**，`vec[int]` 339 处、`vec[str]` 42 处——**真实代码吃不到收益** | 运行时按 `ew` 字寻址（`ln*ew*8`），压缩要改成字节寻址 + 符号扩展加载，push/get/set/pop/foreach/grow + A64 + C 后端全动。除非将来出现字节缓冲密集的库（图像 / 编解码），否则不做 |

> 性能实验两条铁律（两次回滚换来的）：
> 1. 单点核对全对 ≠ 装起来对——必须反汇编对照或单元素 trace。
> 2. 前置条件不满足就回滚并登记重启条件；错误代码比没有代码更糟。

## 6. 优先级

### P0 —— 让"一个真实服务能上线"

1. TLS：根证书库 + P-384/SHA-384——RSA 与链校验已就绪（v1.27），缺锚与曲线
2. HTTP 客户端 + DNS（DNS 需要 UDP，已有）
3. 路由 / 静态文件 / MIME 最小层
4. ~~`result` 允许 struct 载荷~~（✅ v1.38）+ 库层错误对象批量改造（停止"库函数只能退出进程"）
5. 多 member gzip + zlib 容器解码（`inflate_raw` 已可处理裸流）

> v1.19 已完成原本的 P0 第 1 项（gzip 解码），并把 `std/math`、`std/hex`、
> 日志级别过滤一并补上；v1.20 补上 TLS 的最后一块密码学零件 X25519。

### P1 —— 让"语言能撑住中型程序"

1. ~~泛型推导 + 多类型参数（`f[int]` → 能推就推）~~ ✅ v1.36：多参 + 调用点推导
2. ~~命名空间 / 模块系统~~ ✅ v1.99（可见性 v1.43 / 限定语法 v1.44 /
   跨模块同名声明 + 模块版本 v1.99，见 §1）
3. `map[str]Struct`（~~`vec[map]`~~ ✅ v1.37）
4. 函数值放宽：8 参、允许 struct 实参
5. ~~`defer` / `Drop`~~（✅ v1.48 / v1.93：资源生命周期进语法）
6. UDP v6 / reactor 双栈、TCP 批量收发
7. ~~包管理 registry + 发布~~ ✅ v1.99（~~semver 区间~~ v1.45 → registry/发布/传递依赖）
8. 自举主线：函数体 parser 收敛（当前分叉数见 `06-status.md`）

### P2 —— 生态

1. ~~宏 / 反射~~ ✅ v1.96：派生宏（struct + enum）/ 通用 token 宏 / 编译期与运行时反射全部落地（§1）
2. ~~所有权/借用检查扩到视图~~ ✅ v1.84（切片/str 的生命周期与写别名；vec/map/chan 仍是句柄语义，不做线性检查）
3. ~~FFI：PE 导入表已有白名单机制，推广到"用户声明库 + 符号白名单"~~ ✅ v1.87
   （`@ffi("dll"[, "Sym"])`，任意 DLL + 符号名；剩余 **变参**、**按值结构体**、
   **回调 thunk** 三项，见 §1 该行的边界栏）
4. ~~DWARF~~ ✅ v1.80 → ~~LSP~~ ✅ v1.91 → ~~文档生成~~ ✅ v1.92 → PDB（可选，需 MSVC 链路验证）
   → 增量索引（大文件 100 ms 级，见 `06-status.md` §3.10）
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
| `to_str(INT64_MIN)` 输出乱码 | `(1<<63).to_str()` 得到 20 个垃圾字符 | `__str_from_i64` 先 `neg v, v`，而 `-(-2^63)` 溢出回自身；随后 `mod/div` 拿到负数，写出的字节不是数字 | `tests/t76_codec.qma`（含 INT64_MIN 断言） |

表达式位置（`let c = a > b`）一直是对的——它走 `arith()` 的 `fcmpset` 分支。
只有条件位置（`if` / `while`）漏了浮点分流，属于"两条路径实现不一致"的典型。

### 7.3 待查：64 位立即数（≥2^63）的 `and`

v1.29 写 `__memchr` 的 SWAR 时踩到：`and rd, imm` 里 imm 取 `-2^63`（即 `0x8000000000000000`），
实测结果不对；换成 `>>7 & 0x0101…`（同一个掩码效果）就正确。已确认**不是**值语义问题——
`assert((neg & sh) == sh)` 用寄存器操作数时通过。所以问题在"立即数 > 32 位时走 `fetch(SCRATCH, imm)`
→ `alu_rr`"这条路径上，怀疑 SCRATCH 与某条活跃 vreg 冲突或 imm64 物化截断。

- 影响面：所有"大常量位运算"（掩码/魔数）都可能静默算错；当前库层已全部避开。
- 复现骨架：`tests/t76_codec.qma` 之外的独立用例尚未加（需要 IR 级注入）。
- 下一步：`--dump-ir` 对照 + `QLM_SKIP_PASSES` 二分，定位是发射层还是分配器。

### 7.4 待查：`_aes128_encrypt_block_fast` 直接写在 main 里会被误编译

v1.31 写 AES-NI 时顺手发现的**既有**误编译（与 AES-NI 无关，v1.30 及以前同样存在）：

```quelmara
// build/_aes_sw.qma：FIPS-197 C.1 向量
let rk = mem_alloc(176)
aes128_expand(key, rk)
let out1 = mem_alloc(16)
_aes128_encrypt_block_fast(pt, out1, rk)     // 直接调用
print(hex_encode(mem_str(out1, 16)))
// 期望 69c4e0d86a7b0430d8cdb78070b4c55a
// 实测 69c4e0d86a7b0430d8cdb78070b4c500   ← 最后一个字节丢了
```

- **不是值语义问题**：同一个函数包一层包装函数调用就完全正确；`--no-opt` 也正确。
  所以是优化后（内联 / 分配器）在特定寄存器压力下的误编译，症状是**最后一个
  `mem_store8` 丢失**。
- **产品路径未受影响**：`_ctr_xor` 里的调用形状是对的，RFC 8448 逐字节、GCM
  NIST 向量、真实 TLS 全过（`tests/t48_aes.qma` 现在把两条路径都包一层调用纳入回归）。
- 复现件：`build/_aes_sw.qma`（未入库，因为它是"必失败"件；要入库得做成负向夹具）。
- 下一步：`QLM_SKIP_PASSES` 二分（先排 inline，再排 copy_prop），对照 `--no-opt` 的
  寄存器分配差异。**这类"少写一个字节"的 bug 比崩溃危险**，值得单独一轮。

### 7.5 待查：多一条 xmm 指令就改变结果（分配器布局敏感，与 §7.4 同源）

v1.33 写 GHASH 时想用 `pxor xmm7, xmm7` 清零溢出累加器，单独写探针是对的
（全 0），放进 `_gmul_ni` 之后 GHASH 结果全错；换回"内存零块 + load"就正确。

**已排除"优化器删指令"这个假设**：`--dump-ir` 显示 `('xmm_pxor', -8, -8)`
完整保留在 IR 里，DCE 也不会删（它要求 `defs` 非空，无结果指令本来就跳过），
CSE 的 `_cse_key` 对 xmm 族返回 `None`（不参与）。

结论：和 §7.4 是同一类问题——**指令数变一条，寄存器分配/溢出决策就变，
把某个潜在的发射层缺陷暴露出来**。这类 bug 的共同特征是"改动与症状无关"。

- 现状：库层绕开（用 mem_zero + load 清零），功能正确，代价 1–2 条指令。
- 下一步：和 §7.4 合并成一轮"分配器正确性"专项——先用 `QLM_SKIP_PASSES`
  二分定位到具体 pass，再对照 `--no-opt` 的分配结果。

### 7.6 待查：聚合的 `==` 是地址比较（v1.61 发现；str 的有序比较 v1.66 已修）

写类型约束时为了确定 `Eq` 的口径实测到的**既有**缺陷（与约束功能无关，v1.60 及以前同样存在）：

```quelmara
enum Color { Red, Green }
let a = Color.Red
print((a == a).to_str())        // 期望 true，实测 false
struct P { x: int }
print((P { x: 1 } == P { x: 1 }).to_str())   // 实测 false
```

- 根因：聚合值在 `arith()` 里走整数 `cmpset`，比较的是聚合的**地址**（栈槽不同 →
  永远不等）。
- **`str` 的有序比较 v1.66 已修**：运行时新增 `__str_cmp`（字节字典序；长度前缀让
  "公共前缀 + 长度差"这条尾巴常数时间），`arith()` 与 `branch()` **两条路径都接了**，
  `Ord` 因此覆盖 `str`。回归：`tests/t105_strorder.qma`（表达式 / if / while 三条路径，
  外加前缀、空串、≥0x80 字节）。
- 影响面（仍未修的部分）：聚合判等在语言层**没有正确实现**，库层一律按字段/变体手写；
  泛型模板里会被约束检查拦下（`Eq` 不含聚合），不会静默错。
- 回归：`tests/bad/bound_enum_eq.qma`（负向，钉住"enum 不满足 Eq"）。
- 下一步：在 Lower 给聚合比较发结构比较（按字段宽度展开），或明确禁止聚合 `==`
  并给"按字段比较"的内建。改动面不小，单开一版。

### 7.7 已修（v1.65）：enum 的 `f64` 载荷与 `match` 的浮点结果

写泛型 enum 的方法时实测到的**既有**缺陷（与泛型无关）：

```quelmara
enum Num { I(v: int), F(v: f64) }
let a = Num.F(v: 1.5)
match a { Num.F(v) => print(v.to_str()) ... }    // 实测 4609434218613702656（位模式）
```

- 根因（两处，同一类"漏传标记"）：① `lower_match` 绑定载荷时只给 `str`/`bool`
  打标记，f64 载荷按字搬运后**丢了浮点标记**；② `match` 作表达式时结果 vreg
  只继承 `str`/`bool` 标记，同样漏了浮点。
- 修法：两处各补一次 `_mark_float`（载荷按字段声明类型，结果按臂表达式的浮点宽度）。
- 回归：`tests/t103_generic_enum.qma` 的 `Opt[f64]` 用例（`to_str` 与 `* 2.0`）。
- 顺带修：`box_iface` 取宽度改用 `agg_size`，枚举从此能装箱成接口值
  （`let s: Show = some_enum` 以前直接报"未声明的结构体"）——
  回归在 `tests/t104_generic_enum_impl.qma` 的动态派发段。

### 7.8 待查：第 7 个参数是 `str` 且函数被调用两次 → 整段程序静默不执行（v1.70 发现）

写 `std/cookie` 时撞到的**既有**代码生成缺陷（与 cookie 无关，最小复现如下）：

```quelmara
fn s7(a: int, b: int, c: int, d: int, e: int, f: int, s: str) -> str {
    return s + a.to_str()
}
fn main() {
    print(s7(1, 2, 3, 4, 5, 6, "x"))   // 只调一次：正常输出 x1
    print(s7(7, 8, 9, 10, 11, 12, "y")) // 调两次：整段程序无任何输出、退出码 0
}
```

- 触发条件（已二分）：**参数个数 = 7 且第 7 个是 `str`**（栈上传参的指针），
  且该函数被调用 **≥2 次**。7 个 int 参数、8 个 int 参数、5 个参数都正常。
- 症状：不是崩溃、不是报错——整段 `main` 一行都不输出，退出码 0（静默丢代码）。
- 影响面：任何"参数多于 6 个、最后一个是字符串"的 API 都不能调两次。
  `std/cookie` 因此把 `cookie_set` 设计成 5 参 + 属性串（`cookie_attrs`）。
- 下一步：`--dump-ir` 对照单次/两次调用的差异，重点看栈传参的 `push`/`pop` 与
  调用点栈平衡；大概率是调用点未恢复栈偏移（与 §7.4/§7.5 的分配器布局敏感同源）。

### 7.9 待查：结构体字面量里直接调用函数 → "未定义函数"（v1.72 发现）

写 `std/multipart` 时撞到的 Lower 缺陷（最小复现）：

```quelmara
struct P { a: str, b: str }
fn helper(x: str) -> str { return x + "!" }
fn build(x: str) -> P {
    return P { a: helper(x), b: "lit" }     // SyntaxError: 未定义函数 helper
}
```

- 绕开：先落到局部变量再进字面量（`let v = helper(x)` 然后 `P { a: v }`），已验证可用。
- 影响面：任何"字面量字段值来自函数调用"的写法（很常见的构造器风格）。
- 下一步：看 `lower_struct_lit` 里 `self.fns_ast` 的可见性——大概率是字面量降级时
  函数表还没填充（或用了另一份作用域）。改动在 `qlm_native.py`。

### 7.10 已修（v1.96）：`to_float(str)` 返回垃圾值（v1.77 发现）

写 `@derive(Json)` 的 f64 字段解码时撞到——语言里**没有** str→浮点的解析原语，
而 `to_float` 看起来像：

```quelmara
let g = to_float("2.25")
print(g.to_str())        // 实测 1.407002e+14（不是 2.25）
```

- 现状：`to_float` 在自研后端只接受数值实参；传 `str` 时把**指针**当位模式转，
  得到的是地址量级的值，不报错、不崩——典型静默错。
- 影响面：`@derive(Json)` 因此对 `f64`/`f32` 字段显式 fail-fast
  （`tests/bad/derive_f64.qma`），JSON 里的浮点目前只能取 `json_num_raw` 原文本。
- **v1.96 已修**（两步都做了）：
  1. **止血**：`to_float(str)` / `to_f32(str)` 在编译期直接拒绝（自研后端与 C 后端
     各一处），报错信息指向替代方案，不再静默把指针当数值转；
  2. **补解析器**：`std/f64` 的 `f64_parse(s)` 做真正的十进制解析（符号 / 小数点 /
     指数 / 两端空白；`inf` / `nan` / 十六进制一律拒绝）。舍入口径见该文件头：
     ≤15 位有效数字且 |指数| ≤ 22 走 Clinger 快路径（正确舍入），其余可能差 1–2 ULP。
     反向的 `f64_repr(x)` 给最短往返文本（精确十进制展开 + 回读验证），
     `@derive(Json)` 的 `f64` 字段用的就是这两个。
- 回归：`tests/t123_derive_enum.qma`（f64 字段往返 / 精度）、`tests/bad/derive_f32.qma`；
  负向 `to_float(str)` 的形态由 `tests/bad/` 之外的编译器检查保证（见 §7.10 上方代码）。

### 7.11 待查：非 UTF-8 源文件抛 `UnicodeDecodeError`（v1.83 fuzz 发现）

写模糊测试时撞到的**既有**问题（与 fuzz 无关，任何 `quelmara build` 都一样）：

```bash
# 一个 GBK 编码的源文件（或任何非 UTF-8 字节）
python tools/stage0/qlm_cli.py build gbk.qma --target win
# 实测：Python 回溯 UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe5 ...
# 期望：一行干净诊断（"不是合法 UTF-8 源码 @ 字节 N"）+ 退出码 2
```

- 根因：`qlm.py` 的 `parse_file()` / `_consts_of()` 用
  `open(path, encoding="utf-8")` 直接读，解码异常没转成项目统一的 fail-fast
  （`SyntaxError` + 中文提示）。
- 影响面：Windows 上编辑器默认存 GBK 的用户第一次编译就会看到 Python 回溯；
  工具链侧也无法把"编码错"和"编译器崩了"分开统计——`qlm_fuzz.py` 目前把
  `UnicodeDecodeError` 归到 `bug`，变异器主动只改 ASCII 字节来避开它。
- 下一步：加一个 `read_source_text(path)` 把 `UnicodeDecodeError` 转成
  `SyntaxError`（与 `require_source()` 同风格），三处读源码的点都换过去；
  之后 fuzz 分类器可以把"编码错"单列一类。
- 为什么没顺手修：这三处读点在语言轨正在改的文件里（`qlm.py`），
  本版只做工具链，不制造合并冲突。

### 7.12 已修（v1.102）：void 函数里的空 `return` 污染进程退出码

写 `std/kv` 的夹具时撞到的**既有**缺陷（与持久化无关，v1.100 及以前同样存在）：

```quelmara
fn main() {
    let a = 1
    if a == 1 {
        print("in if")
        return
    }
}
// 实测：打印 in if，但**退出码 1**（期望 0）
```

- 根因：`main` 是 void 函数，入口 `gen_entry` 把 **RAX** 当 `ExitProcess` 的参数；
  而 `return` 无值那条路径发的是 `ret None`（不动 RAX），于是进程带着上一次
  比较/算术的残留值退出。函数体末尾的**兜底返回**早就写的是 `ret 0`，只有显式
  `return` 漏了——又一处「两条路径实现不一致」。
- 修法：`Lower._stmt` 的 `return` 分支在 `fn_ret == ("named", "void")` 时发
  `ret ("imm", 0)`。**不是**在入口清零 RAX——那样 `fn main() -> int` 的退出码
  语义就没了。
- 影响面：任何「main 里早退」的程序（`if 参数不对 { print(用法); return }` 是最常见写法）
  在脚本/CI 里都会被判成失败；库函数早退不受影响（调用方不看 RAX），
  但同一个缺陷在「把 void 函数返回值当值用」的路径上也会露出。
- 回归：`tests/t128_mainret.qma`（if / while / 被调 void 函数三条早退路径），
  由 `run_win_tests.py` 的 `case_output` 检查**退出码 0**——只测输出测不出来。

### 7.13 待修：6 个标准库模块没有 `pub` 导出，其中 2 个连解析都过不去（v2.01 审计 / v2.08 重测）

写文档时为了核对"哪些模块真能用"，逐个 `import` 了一遍（命令见下），结果和
`03-stdlib.md` 的 ✅ 标记对不上：

```bash
# 每个模块生成一个只 import 它的空程序，构建一次
python - <<'EOF'
import os, subprocess, sys
for dp, _, fns in os.walk('std'):
    for fn in sorted(fns):
        if not fn.endswith('.qma'): continue
        mod = os.path.join(dp, fn)[:-4].replace('\\', '/').replace('/', '.')
        p = 'build/_audit.qma'
        open(p, 'w').write(f"module t\nimport {mod}\nfn main() {{ print(\"x\") }}\n")
        r = subprocess.run([sys.executable, 'tools/stage0/qlm_cli.py', 'build', p,
                            '--target', 'win', '-o', 'build/_audit.exe'],
                           capture_output=True, text=True)
        if r.returncode: print(mod, (r.stdout + r.stderr).strip().splitlines()[-1])
EOF
```

**已修的部分**（v2.08 重测：`std/` 下每个模块逐个 `import` 复核）

| 模块 | 修法 | 证据 |
|---|---|---|
| `std/ds` | 10 → **13 个 `pub`**，补全 `///`，新增 `rb_clear` / `rb_free` / `heap_len`；堆上浮/下沉改"挖洞" | `tests/t129_ds.qma`（15 组断言）+ `bench/ds_bench.qma` |
| `std/timer` | **重写**：四个顶层 `let` → mem 块 + `static_word(13)/(14)`；`now_ms()`（不存在）→ `now_ns()`；4 → **5 个 `pub`**；`timer_poll` 从"每次 O(n) 扫平行数组"改成 O(log n) 弹堆 | `tests/t131_timer.qma`（7 组）+ `bench/timer_bench.qma` |
| `std/http`、`std/net/core` | v2.10（并行轨）：`http` 的 `let rc` 改名 + 29 个 API 补 `pub`/`///` + 路由表与中间件链；`net/core` 18 → **22 个 `pub`**（跨模块读不了的 `ST_*` / `SLOT_RECVLEN` 常量改成访问器——`const` 不能 `pub`，语法只允许 `fn/struct/enum/interface`） | `tests/t130_router_dispatch.qma` + `tests/http_router_test.py`（20 项 E2E）+ `bench/http_router_bench.qma` |

**A. 两个模块解析失败**（`import` 就报错，连符号表都建不起来）

| 文件:行 | 症状 | 原因 |
|---|---|---|
| `std/sse.qma:132` | `期望 NAME，得到 'rc'` | `let rc = h(fd)`——`rc` 是**关键字**（`rc[T]` 类型构造） |
| `std/ws.qma:179`（另 372/400 同） | 同上 | 同上 |

**B. 六个模块 0 个 `pub` 导出**（能 import，但用户代码一引用就编译失败）

`std/core`（4 个函数）/ `std/gen`（9）/ `std/serialize`（10）/ `std/sse`（20）/ `std/time`（2）/
`std/ws`（24）——合计 **69 个顶层函数**。`03-stdlib.md` §1 总览的"公开 / 全部"列里显示
`0 / N` 的就是这批。

- 复现：`import std.core` 后调 `abs(-3)` → `SyntaxError: 引用了非 pub 声明（1 处）：'abs' <- core.qma`。
- 根因：v1.43 把 std 全库改成 `pub fn` 的那一轮**漏了这批文件**（`gen_stdlib_doc.py` 里
  v1.47 的注释记的是"把 271 个 pub API 全部漏出"，说明当时只核对了"有 pub 的那部分"）。
  之后再没人 import 过它们，所以一直没暴露——`run_win_tests.py` 不构建 `examples/`。
- 连带：`examples/ws_demo.qma` / `sse_demo.qma` 仍构建不过（先撞 A 的解析错，修掉再撞 B 的
  可见性错）；`std/core` 是 `std/log` / `std/rand` / `std/sse` / `std/ws` 的共同依赖，补它的
  `pub` 能一次解开四个模块的引用问题（**下一版就做它**）。

**下一版顺序**：① `sse`/`ws` 的 `rc` → `rcv`（3 处）；② `std/core` 的 4 个声明补 `pub` + `///`
（解开 log/rand/sse/ws 的引用）；③ 余下 5 个模块 65 个声明补 `pub` + `///`；④ 把
`examples/{ws_demo,sse_demo}.qma` 与 `std/timer` 的冒烟构建纳入 `run_win_tests.py`——
**坏了这么久没人发现，就是因为没人编它**。

### 7.14 待查：调用实参类型不匹配不报错，静默按位重解释（v2.07 发现）

写 `std/net/addr` 时把 `str_find_from(s, from, needle)` 的实参写反了
（`str_find_from(s, ".", start)`——第 2 个位置给了 `str`、第 3 个给了 `int`），
编译器**一句都不说**，生成出来的程序当场 SIGSEGV。最小复现：

```quelmara
fn g(a: str, b: int, c: str) -> int { return b }
fn main() { print(g("abc", "not-int", "x").to_str()) }   // 编译通过
```

```
r=140697867661375      ← 把 str 数据指针当 int 原样返回
```

- 期望：编译期报「第 2 个实参期望 `int`，得到 `str`」（`map.get` 缺键都能 fail-fast，
  这里连类型都不看）。
- 现状：调用点只做**个数**校验（`需要 N 个实参`），没有形参类型比对；`str`/`int`/
  指针在 IR 里都是 1 个 8 字节槽，于是"能编过、跑起来读野指针"。
- 影响：写错一个实参顺序 = 段错误（v2.07 踩到一次），而不是编译错误。
- 复核：把上面 4 行存成 `build/tc.qma`，`python tools/stage0/qlm_cli.py run build/tc.qma
  --target win`——能跑出数字就说明这个缺口还在。

### 7.15 已修（v2.13）：`vec[T][i]` 编不过（文档写了两年，实现里没有）

- 现象：`let v = vec[int].new(4); v[0]` → `SyntaxError: 下标只能用于定长数组、
  切片或 str`。**局部变量和 `vec[T]` 形参都一样**，`.get(i)` 反而是好的。
- 根因：`eval` 的 `index` 分支只认三条路（`_arr_of` 定长数组 / `_is_slice` 切片 /
  `_is_str`），vec 句柄落到函数末尾直接 raise——没有第四条。
- 为什么一直没发现：`std/sort.qma` 整篇是 `v[i]` 的快排，**这个模块根本编不出来**，
  而没有任何测试 `import std.sort`（§7.13 的"0 导出模块"审计只看了解析，没看降级）。
- 修法：补第四条路，降级与 `.get(i)` 完全同构（`__vec_get` / `__vec_get_n`，
  越界由运行时 fail-fast，元素标签按 str / 嵌套 vec / `vec[map]` 三条重挂）。
- 回归：`tests/t141_vecindex.qma`（局部 / 形参 / 嵌套 / str / 聚合 / 表达式位置 6 组）。

### 7.16 已修（v2.13）：`exit(变量)` 静默退 0（vreg 号被当立即数）

- 现象：`fn main() { let c = 3; exit(c) }` 的进程退出码是 **0**，不是 3。
  `exit(3)`（字面量）却是对的——所以只看字面量的用例全绿。
- 根因：`emit_exit(fn, code)` 的实现是
  `arg = ("imm", code) if isinstance(code, int) else code`——而 **vreg 号也是 int**，
  于是运行期值被当成立即数（vreg 0 → 退出码 0）。
- 影响：任何"把错误码算出来再退出"的程序（驱动器、测试脚本、CLI）都静默退 0；
  `assert` / 越界 / panic 走的是字面量 1，所以没暴露。
- 修法：裸 int 一律按 **vreg** 解释，立即数必须写成 `("imm", n)`；14 个内部调用点
  改成显式 imm。
- 回归：`tests/t142_exitcode.qma` + `run_win_tests.py::test_exitcode()`（期望 42，
  且 `exit` 之前的输出已刷出、之后的语句不执行）。

### 7.17 已修（v2.19）：大帧跳过 guard page —— 曾连续三个版本挡住自举

现象统一是"qlmc 编出来的二进制有时能用、换一批无关代码就崩"，且 `--no-opt` 与 `-O`
表现不同。两个版本里踩到三个独立触发点：

| 触发 | 症状 | 规避 |
|---|---|---|
| `FnCtx` 从 24 字段涨到 28 字段（按值传） | 单函数能编、两个函数必崩；崩在 `call` 压帧处，被调方一条语句都没执行 | 计数器并进 `cells` 数组，压回 22 字段（v2.18） |
| `-> bool` 函数里用 `if cond { return true }` 早返回 | 部分用例（fib 的递归 + 二元调用）崩，其它正常 | 改成单表达式 `return A or B`（v2.19） |
| 把 7 个函数整体挪到文件末尾（纯位置变化） | 原本能过的 `s4_agg` 开始崩 | 无，只能试（v2.19） |

三者都指向同一件事：**参数区/帧布局的偏移假设在特定代码形状下不成立**，与 §7.4/§7.5
疑似同源。

**为什么它是当前的关键路径**：qlmc 每加一个特性都会改变自身代码布局，"能不能正确
编译"变成掷硬币——v2.19 的 vec 功能本身是通的（`vec[int]` 的构造 / push / get / len
都能编出正确 exe），但同一次改动让 fib 崩了，只能整版回滚（WIP 留在
`.workbuddy-ai/scratch/v219_wip/`）。

**建议修法**：先做最小复现（不用 qlmc，直接用 stage-0 编"按值传结构体 + 早返回 bool
函数"的小程序），再用 `QLM_SKIP_PASSES` 二分到具体 pass。在修好之前，qlmc 的每次
语法扩展都必须重跑 `tests/qlmc_test.py`（它会重建 qlmc 并跑全部差分——正是这次的
拦网）。

**v2.19 追加证据（都指向"栈上的越界写"，不是栈耗尽）**：

1. **改 PE 头的栈大小就能翻转结果**。只把 `build/qlmc.exe` 的
   `SizeOfStackReserve` 从 1 MB 改成 8 MB（纯二进制补丁，不重编源码）：
   `r1.qma`（最小递归：`f(n-1)+f(n-2)`）从崩 → 通过，而 `fib.qma`、`s2_str.qma`
   从通过 → 崩。同一份代码，栈更大反而有别的用例坏掉，排除"栈不够用"。
2. **语义等价的改写会翻转**：`-> bool` 函数写成 `return A || B` 与写成
   `if A { r=1 } if B { r=1 } return r==1`，两者通过的用例集合不同。
3. **崩溃点始终一致**：`call` 压帧那一刻，被调方第一条语句都没执行（说明
   `rsp` 在调用点就已经是错的）。
4. `--no-opt` 与 `-O` 通过的用例集合也不同（`--no-opt` 下 vec 全部用例通过、fib 崩）。

**最终定位（v2.19，已修）**：`tools/dev/fault_probe.py` 抓到 AV 地址恰好等于 `rsp`，
`tools/dev/frame_scan.py` 扫出全程序 12 个函数帧 ≥ 4 KB（最大 15 KB）。根因是
**序言只发 `sub rsp, frame`，帧 > 4 KB 时会跨过 guard page**，Windows 不再自动扩栈，
函数体第一次写帧就 AV。修法：帧 > 4 KB 时**自高向低**逐页 touch（等价 `__chkstk`；
从低往高写会直接落在未提交页上，照样崩——顺序是关键）。修完 `r1.qma` 连跑 6 次全过，
主回归 290 不变。

### 7.18 待修：`vec[vec[T]]` 撞类型码区间（v2.27 发现，qlmc 侧）

qlmc 的类型编码是"标签 + 载荷"塞进一个 int：

```
TY_VEC = 0x8000 + elem      // elem 是**完整**的 TY_* 码
TY_MAP = 0x10000 + (K<<8) + V
```

于是 `vec[vec[int]]` 的码是 `0x8000 + 0x8000 = 0x10000`，**正好落进 `TY_MAP` 的区间**。
症状不是崩溃，而是走错分支：

```
qlmc: map 只支持 .set(k,v) / .get(k) / .has(k) / .len()
```

`_lower_method` 里第一段判定是 `if hty >= TY_MAP && hty < TY_ARRAY`，`0x10000` 满足，
于是 `vec[vec[int]].new(1)` 被当成 map 处理。同类风险：`vec[map[K]V]`、`vec[切片]`、
`vec[闭包]`、`vec[enum]`、`vec[struct]` 全部会落进别的区间（后三个是"看似能用但
`_ty_elem` 取出的 elem 值错"）。

**为什么当初没暴露**：S5 起所有夹具的 vec 元素都是 `int`/`str`（码 0/2），
`0x8000+0/2` 落在自己区间内，一路绿灯。

**修法**（不要只给 `TY_VEC` 打补丁）：元素类型不能存"完整 TY 码"，要存
**类型表下标**（`TY_VEC = 0x8000 + ti`，`ti` 是 `fc` 里的类型表项），
让嵌套退化成一次查表。这样 `TY_MAP` 的 K/V 也该一起改成下标。
动之前先看 `_ty_is_agg`、`_ty_elem`、`_ty_size`、`_addr_index`、`_lower_method`
五处按区间判定的地方（教训同 `05-toolchain.md` §1.11 坑表 #19）。

### 7.19 待修：stage-0 打印 INT64_MIN 输出乱码（v2.28 差分发现）

```
$ cat min.qma
fn main() {
    let a = 0 - 9223372036854775807
    print(a - 1)
}
$ python tools/stage0/qlm_cli.py build min.qma --target win -o min.exe && ./min.exe
-'..--).0-*(+,))+(0(          ← 应该是 -9223372036854775808
```

qlmc（走 `wsprintfA("%I64d")`）打印正确，所以差分夹具里**只要出现 INT64_MIN 就会红**。
根因在 stage-0 自己的 itoa：

1. 取绝对值那步 `if x < 0 { neg = 1; x = -x }`——`-INT64_MIN` 溢出，`x` 仍是负数；
2. 逐位 `x % 10` 于是得到**负余数**；
3. `'0' + r` 把字符打到 `'0'` 以下——实测映射正好是 `chr(48 - d)`：
   `9→'`、`2→.`、`3→-`、`4→,`、`5→+`、`6→*`、`7→)`、`8→(`，`0` 恰好不变。
   这串特征可以反过来当"是不是这个 bug"的指纹。

修法（一行）：先判 `x == INT64_MIN` 直接输出 `"-9223372036854775808"`；
或者用无符号算术取绝对值（`neg ? (u64)0 - (u64)x : (u64)x`）。
**归 stage-0 那条线改**（本线只碰 qlmc，不碰对方在途文件）。

`s15_bitops.qma` 里 `1 << 63` 因此改成 `print((1 << 63) >> 62)`（=-2）——
覆盖同一条代码路径，但绕开这个打印 bug。修好之后应改回直接打印。

## 8. 推进顺序（2026-10-22 调整）
平台相关（§4）**暂停**；TLS 信任链（根证书库 / P-384 / SHA-384）也停在 v1.27 的进度。
当前顺序：

1. **性能专项（§5）**：~~GHASH 4-bit 表~~（v1.28）→ ~~memchr~~（v1.29）→ ~~mem_diff + gzip 编码 1.6×~~（v1.30）
   → ~~AES-NI~~（v1.31，CTR 31×）→ ~~GHASH 字级化~~（v1.32）→ ~~GHASH PCLMUL~~（v1.33，GCM 19 ms）→
   **JSON memchr** → loop_sum 三件套 → LICM 根修 → §7.4/§7.5 两个误编译
2. **语言层（§1）**：~~泛型多参 + 调用点推导~~（v1.36）→ ~~`vec[map]`~~（v1.37）→
   ~~result struct 载荷~~（v1.38）→ ~~struct 内嵌套聚合~~（v1.39）→
   ~~窄值存储截断全覆盖~~（v1.40）→ ~~切片别名写入截断~~（v1.56，整数宽度行翻绿；槽压缩转 §5）→
   ~~`map[K]Struct` 值扩容~~（v1.41）→ ~~函数值放宽（8 参 + 聚合实参）~~（v1.42）→
   ~~`pub` 可见性~~（v1.43）→ ~~限定语法 lib.fn()~~（v1.44）→ ~~`defer`~~（v1.48）→ ~~`Drop`/RAII~~（v1.93，本行翻绿）→
   黄标逐项（~~`@simd` 形状~~ ✅ v1.85、~~并发原语~~ ✅ v1.98、~~接口装箱~~ ✅ v1.97、~~所有权范围~~ ✅ v1.84 …）→
   红标逐项 红→黄→绿（~~泛型 struct~~ 黄 v1.59；~~类型约束~~ ✅ v1.61；~~泛型方法~~ ✅ v1.62；
   ~~泛型 enum~~ ✅ v1.63；~~FFI~~ ✅ v1.87）
3. **标准库（§2）**：~~MD5~~（v1.35）→ ~~HTTP 客户端封装~~（v1.50）→ ~~路由 / 静态文件 / MIME /
   cookie / session / multipart~~（v1.67–v1.72）→ ~~多 member gzip + zlib 容器~~（v1.32）→
   ~~正则~~（v1.57）→ ~~持久化（KV）~~ ✅ v1.102（批量提交列入 2.x 后续版本）→ ~~`exp/log/sin/cos`~~（v1.47）→
   ~~`std/ds` 补 pub（RingBuf / MinHeap 变成真 API）~~ ✅ v2.05 → ~~`std/timer` 重写（轮询式定时器可用）~~ ✅ v2.08 → ~~IPv6（TCP 全链路 + 双栈 listen）~~ ✅ v2.07 → ~~HTTP 服务端路由表 + 中间件链（`std/http` 可导入）~~ ✅ v2.10。
   **当前红标只剩**：TLS 根证书库 / P-384 / SHA-384、连接池与 HTTP/2、UDP v6 与 reactor 双栈、TCP 批量收发、Linux DNS、国际化（locale / Unicode 分类 /
   大小写折叠）、SQL 与大于内存的数据集（要 mmap 视图 + 页缓存）
4. **工具链（§3）**：~~调试器~~ ✅ v1.75/v1.80 → ~~覆盖率（行/分支/函数/文件/合并）~~ ✅ v1.83 → ~~fuzz~~ ✅ v1.83 → ~~性能回归门禁~~ ✅ v1.88
   → ~~LSP / 补全~~ ✅ v1.91 → ~~包管理（registry / 发布 / 传递依赖）~~ ✅ v1.99
   → ~~增量 / 并行编译~~ ✅ v1.100（单元级）→ ~~`.qla` 目标文件 / 函数级增量 / 二进制库~~ ✅ v2.11
   （工具链 §3 的缺口表到此全绿；剩下的都是"更强"而不是"没有"：跨档案内联、
   档案级调试信息、A64/ELF 档案）

> 2026-10-23 起语言层与工具链**双轨并行**：语言层由另一会话负责（v1.44 命名空间
> 限定语法即其成果），工具链从 v1.45（qpm semver）起推进。两轨共享连续版本号，
> 改动文件面基本不重叠（编译器/parser ↔ 工具链脚本/文档）。

> v1.29 已把 §2 的四条红标翻绿（UTF-8 / base64url / set / deque / FNV / CLI flag），
> 剩下的红标按「撞到的场景有多近」排序，不按条数排序。

> 排序原则：性能是普适杠杆；语言层决定库能不能写；工具链最后。
