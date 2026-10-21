# Quelmara 更新日志（CHANGELOG）

> 产品后端 = 自研后端（Linux x86_64 ELF / Windows PE32+ / AArch64）；
> C99 后端仅作交叉验证。格式：每版本记录「特性 / 优化 / 修复 / 回归规模」。
> 本文是各版本特性与回归项数的**唯一权威记录**。

---

> **版本号顺序说明**：下面并列的七节按主题分组（v1.11 = 用户泛型 + 编译期求值，
> v1.10 = 并发与性能地基，v1.9 = 接口动态分发，v1.8 = 语言特性，v1.6 = 标准库 P0，
> v1.5 = 性能 + 协议库，v1.3 = 自举 + 可用性边界），**物理顺序不代表版本先后**。
> v1.8 已提交（`e340962`），v1.9 已提交（`92b05a3`），v1.10 已提交（`f326434`），
> v1.4（IOCP reactor）已提交（`d769435` / `b3e0fe2`）；
> v1.11 本轮提交；v1.3 / v1.5 / v1.6 仍待按节各打一个 commit。
> 各节的回归/对拍项数是**当轮口径**，会随夹具增加而增长（例如 lexdiff 现 92/92、parsediff 现 88/88）；
> 需要"当前实测值"请看 `HANDOVER.md §0` 或直接跑脚本。
> 能力边界与缺口全表见 `docs/GAPS.md`。

## 未发布（v1.11，工作区进行中）

> 主题：**表达力推进**——用户泛型单态化（`fn f[T]`）+ const 编译期算术求值。
> 这两块是"接入大量生态前的表达能力"清单上的最大缺口：泛型让通用算法
> （比较器、映射、归约）不用再复制粘贴，编译期求值让尺寸/表长常量可以
> 由公式推导而不是手算。
>
> 状态总表见 `docs/STATUS.md`，语义见 `docs/LANG.md §10/§11`。

### 语言（全部有夹具）

- **用户泛型（`fn f[T]`，单态化）**：解析期收集模板（不进发射列表）→
  后置 pass `expand_generics` 收集全部 `f[Type](...)` 调用点 → 按 (fn, T)
  深拷贝成具名实例 `f__<T>`，类型元组 `("named", T)` 全替换，体内泛型调用
  （含**自递归**）递归实例化后**降为普通 call**——Lower 与后端**零改动**，
  分发开销为零（与 C++ 模板同级）。
  支持：标量 / str / 具名 struct / enum 实参；`vec[T]` 等容器形参；
  泛型体 `T { ... }` 占位字面量（`("tp_lit", ...)` 节点，单态化后变 structlit）。
  **边界**：显式实例化（无类型推导）、单类型参数、无约束、无泛型 struct/方法。
- **const 编译期算术**：`const BUF: int = 4 * KB`——整型字面量 / 一元负号 /
  括号 / `+ - * / %` / 已声明的 const 引用（按声明序），解析期求值；
  除法/模按 C 截断语义；编译期除零 fail-fast；`const N: int` 类型标注仅文档性。
- **实现要点（两个解析期坑）**：① 泛型 fn 名要在 `_prescan` 预登记占位，
  否则体内自引用 `fact[T](...)` 会被解析成下标链；② `_cur_tparams` 作用域
  控制 `T { ... }` 的字面量识别（只在泛型体内是占位节点，不影响 `P { ... }`）。

### 验证

- 夹具 `tests/t56_generic.qma`：const 算术/引用/截断除法、int/str/struct
  实例、自递归（fact 5!=120）、`T{...}` 构造、`vec[T]` 形参。
- PE 回归 **117 → 118 项**全绿；lexdiff 104/104、parsediff 89/89（t56 进
  PARSE1_PENDING：stage-1 parser 未支持泛型语法）；三道门禁 PASS。

## 未发布（v1.10，工作区进行中）

> 主题：**并发与极致性能地基**——atomic 原语（IR + lock 前缀编码）+ 无锁同步库
> `std/sync`（Quelmara 自实现）+ `now_cycle()`（rdtsc 程序内自计时）。
> 这是"网络并发 / IO / 内存管理安全都算极致性能"承诺的第一块：无锁数据结构与
> 自旋互斥不再需要绕道运行库，全部一条 CPU 指令直达。
>
> 状态总表见 `docs/STATUS.md`，语义与实测见 `docs/LANG.md §9`。

### 语言 / IR（全部有夹具）

- **`atomic_add(addr, v) -> old`**：`lock xadd`（fetch-and-add），无锁计数器地基。
- **`atomic_cas(addr, expect, new) -> old`**：`lock cmpxchg`（期望值走 RAX），
  自旋锁 / 无锁栈的地基。
- **`atomic_fence()`**：`mfence` 全内存屏障；**`spin_hint()`**：`pause` 自旋提示。
- **`now_cycle() -> int`**：`rdtsc`（EDX:EAX 拼 64 位）。微基准必须排除本机
  ~350ms 进程冷启动（Hyper-V/VBS），这是测量纪律的最后一块拼图。
- 新 IR 指令 `atomic` / `mfence` / `pause` / `rdtsc`——**登记纪律升级为五处**：
  `vreg_mentions`、`_map_ins`、`_EFF`、**`_subst_vregs`**（新发现）、`gen_instr`。
  `_subst_vregs` 漏登记的后果（本轮实测）：copy_prop 塌掉 addr 的定义 mov 而
  不替换 atomic 里的 use → 悬空 vreg → 调度器把 atomic 排到定义前 →
  运行期地址是垃圾，段错误。

### 标准库

- **`std/sync.qma`**（全 Quelmara，零 Python 运行时）：自旋锁（CAS + pause）、
  Treiber 无锁栈（多生产者 push / 单消费者 pop，多消费者 ABA 见 GAPS）、
  WaitGroup（fork-join 屏障）。
- **`bench/sync_bench.qma`**：rdtsc 自计时基准（`docs/LANG.md §9.3`）——
  标量自增 2 cycles/iter、`atomic_add` 27、mutex 无竞争 RMW 28、
  无锁栈 push+pop 106。

### 修复

- **架构守卫 bug（v1.5 遗留）**：`mem_xchg` 等内建的 x86_64 判据写成
  `platform not in ("windows", "native")`，而 platform 实际取值是
  `linux | windows` → Linux 链永远拒绝。统一改为 `self.arch != "x86_64"`（4 处）。

### 验证

- 夹具 `tests/t55_sync.qma`：4 线程 atomic 计数 40000 ✓、CAS 成败语义 ✓、
  mutex 防丢更新（非原子 RMW ×2 线程 ×5000）✓、无锁栈并发 push 1000 元素
  总和 ✓、WaitGroup 屏障 ✓。
- PE 回归 **116 → 117 项**全绿；lexdiff 103/103、parsediff 89/89、emitdiff 10/10；
  三道门禁 PASS。

## 未发布（v1.9，工作区进行中）

> 主题：**interface 动态分发（trait object）**——v1.8 落地静态分发后，
> 这是语言层最后一块多态拼图。接口值 = `{data, vt}` 两字结构，
> `obj.m()` 走 `vt[slot] -> callr`，运行期派发到具体类型的实现。
>
> 状态总表见 `docs/STATUS.md`，语义与内存布局见 `docs/LANG.md §7.3`。

### 语言（全部有夹具）

- **接口值与 vtable 动态分发**：`interface` 声明自动注册成 2 字结构体
  `{data, vt}`（data = 堆上装箱的 payload 指针，vt = 代码段里按方法声明顺序排布的
  函数指针表）；`obj.m()` 降级为 `vt = obj[1]; fp = vt[slot]; callr fp, [obj[0], ...]`。
  vtable 在代码段末尾生成（`gen_vtables`），方法地址由 `code_fixups` 回填，
  ELF 与 PE 共用同一机制（PE 额外登记 DIR64 重定位）。
- **隐式装箱四处**（编译器自动完成）：`let s: Shape = Circle{..}`（类型标注）、
  函数实参（接口形参）、`vec[Shape].push(Circle{..})`、`return`（接口返回类型）。
  装箱 = 结构体按值拷入堆块 + 存 vtable 地址。
- **异构容器**：`vec[Shape]` 现在可用（静态分发做不到），`for-in` 遍历逐元素派发。
- **接口返回聚合**：方法可返回 struct（隐藏出参指针 + `callr`，与直接调用同 ABI）。
- **静态分发不受影响**：接收者类型编译期已知时仍走直接调用（零开销路径）。
- **两个新负向检查**：类型未实现接口（`impl` 缺失 → 编译失败，
  `tests/bad/iface_no_impl.qma`）；同一类型在两个接口里有同名方法（mangling
  撞车，暂无消歧义规则 → 编译报错，`tests/bad/iface_dup_method.qma`）。

### 边界（明确写死）

- 装箱是**拷贝**且**不释放**（无引用计数 / drop；需要共享语义用 `rc[T]`）；
- `interface` 与 `impl` 必须同源文件；C 后端不支持 `interface`/`impl`；
- **AArch64 发射层未接 vtable**：遇接口值编译期明确报错
  （此前会是 KeyError 栈；`trunc`/`vsum` 同条边界，见 `docs/STATUS.md` 平台表）。

### 验证

- 夹具 `tests/t54_iface_dyn.qma`：7 类场景（接口变量 / 形参 / 返回值 /
  `vec[Shape]` 求和与计数 / 方法返回聚合 / 链式 `pick(0).area()` / for-in 容器 /
  静态分发回归确认）。
- PE 回归 **113 → 116 项**（+1 动态分发 +2 负向）全绿；lexdiff 102/102、
  parsediff 88/88、emitdiff 10/10；三道门禁 PASS
  （`check_names` 修复 `push_via_api.py` 的 GitHub 仓库名误报，行级 `legacy-ok` 豁免）。

## 未发布（v1.8，工作区进行中）

> 主题：**语言层补全 + 三个必现误编译修复**。v1.6 把标准库补齐到"能交付 JSON API"，
> v1.8 把语言层从"玩具语法"推到"能写中型程序"：真实整数宽度、`@simd`、`@no_preempt`、
> `rc[T]`、所有权检查、`interface`（静态分发）。
>
> 状态总表见 `docs/STATUS.md`，特性语义见 `docs/LANG.md`。

### 语言（全部有夹具）

- **真实整数宽度 `u8/u16/u32/u64/i8/i16/i32`**：值统一 64 位承载，
  在 `let` 标注 / 形参入口 / 返回值出口 / 赋值四处按声明宽度截断
  （uN 零扩展、iN 符号扩展）；表达式内部按 C 语义提升到 64 位，不中途回绕。
  新 IR 指令 `('trunc', dst, a, bits, signed)`（`movzx/movsx/mov r32,r32`）。
  夹具：`tests/t49_width.qma`。
- **`let x: T` 类型标注**：解析器支持（此前语法上不存在）。目前只有宽度类型参与语义，
  非宽度标注仅作可读性。
- **`@simd`**：把 `acc = acc + a[i]` / `acc += a[i]` 形状的 `[N]int` 归约
  编译成 SSE2（`paddq` 两路 + `movdqu` + 水平求和 + 标量尾）。新 IR 指令
  `('vsum', dst, base, count)`。实测 4096 元素 ×200：标量 3µs → **1µs（≈3×）**。
  语义差异：**跳过逐元素越界检查**（调用方保证区间），形状不匹配直接编译报错。
  夹具：`tests/t50_simd.qma`。
- **`@no_preempt`**：函数级 / 语句级注解，抑制编译器插入的 `sched_yield` /
  `SwitchToThread`（自旋、无锁临界区、确定性延迟场景）。
- **`rc[T]` 引用计数句柄**：布局 `[refcount 8B][payload n*8B]`，句柄指向 payload；
  `rc_new/rc_get/rc_clone/rc_drop/rc_count`。载荷仅支持具名 struct。
  夹具：`tests/t51_rc.qma`。
- **所有权 / 借用检查**（只针对 `rc[T]` 句柄）：语句级线性扫描 + 分支合并，
  三类**编译错误**（use-after-drop / double-free / move-then-use）+ 两类**编译警告**
  （函数结束仍存活、覆盖活句柄）。负向夹具：`tests/bad/own_*.qma`。
- **`interface` / `impl`**：契约声明、实现完整性检查（缺方法 / 参数类型 / 返回类型），
  方法调用语法 `c.area()` 解析成 `Type__method` 直接调用（**静态分发，零开销**）。
  **动态分发未实现**（`let s: Shape = ...` 不支持）。夹具：`tests/t52_iface.qma`；
  负向：`tests/bad/iface_*.qma`。

### 修复：三个必现误编译（v1.6 遗留）

- **#1/#3 根因相同**：`gen_bin` 的就地路径里，`a` 溢出到栈时把 `[rbp-8]` 的
  **偏移 8** 当成了 **R8 寄存器号 8**，于是"a 已在 dst 寄存器"判断误判为真、
  跳过 fetch，运算吃到上一条指令的残值。
  修法：区分 `("r", reg)` 与 `("m", off)`。
  影响：循环内 `substr` 用调用结果算长度、一个表达式里两次调用 + 下标，两类形状
  不再需要规避写法。回归：`tests/t53_regress.qma`。
- **#2**：`"\xNN"`（≥0x80）被当 Unicode 码点再 UTF-8 编码（`"\xe4"` → 2 字节）。
  修法：词法器用 surrogateescape 区（U+DC80..U+DCFF）承载原始字节，
  发射端 `encode("utf-8", "surrogateescape")`。
  影响：可以直接写字面量二进制（HTTP 帧、哈希夹具）。
  回归：`tests/t53_regress.qma`。
- 旧的 `tests/known_bugs/` 目录移除（三条全部转正）。

### 自举对拍

- 词法 **99/99**、声明级 **90/90**（**显式跳过 1 个** file：`t52_iface.qma`，
  stage-1 parser 尚未实现 `interface`/`impl`；跳过的文件会被打印出来，不是静默忽略）。
- `bootstrap/lexer/qlm_lex.qma` 关键字表补 `rc` / `interface` / `impl`；
  `bootstrap/parser/qlm_parse.qma` 补 `rc[T]` 类型渲染（两侧必须一致）。
- QuIR 架构无关 59/59（22 skip：a64 无 chan/map/spawn，以及新增的 `vsum`/`trunc`
  AArch64 发射层尚未实现 → 显式 SKIP）。

### 工程化

- `tests/parsediff.py` 增加 `PARSE1_PENDING` 显式跳过名单（打印原因），
  避免"新语法悄悄拉低对拍数字"。
- `tests/run_win_tests.py` 新增 `[3j]` 段：3 个特性正测 + 5 个负向夹具
  （断言错误信息包含关键字，避免"因别的原因失败"被当成通过"）。
- 新增 `docs/STATUS.md`（语言/工程化/性能/平台四维状态总表，唯一"现在到哪了"口径）、
  `docs/LANG.md`（v1.8 特性精确语义与边界）。

### 验证

- Windows PE 回归 **113 项全绿**（FAIL=0，SKIP=1 为 WSL 被沙箱拦）。
- 词法 99/99、声明级 90/90（1 跳过）、IR 59/59（22 skip）、发射 10/10。
- 三道门禁 PASS（check_names / check_origin / check_docs）。

---

## 未发布（v1.6，工作区进行中）

> 主题：**标准库 P0 四件套 + 文档漂移治理**。目标是把"HTTP 服务能对外交付"从
> 五缺五变成三缺二（JSON / 字符串 / URL 已就位，gzip 与 TLS 仍缺）。

### 标准库（全部 Quelmara 自实现，零 Python/Node 运行时）

- **`std/sha256.qma`**：SHA-256 + HMAC-SHA256。FIPS 180-4 与 RFC 4231（case 1/2/6，
  含 131 字节超块长 key）向量全过；1MiB 单遍 71ms（≈14.7 MB/s，标量实现）。
  轮常量改用 6 层判定树（线性 64 次比较会让每块多四千次分支）。
- **`std/str.qma`**：26 个函数——查找/判定/裁剪/大小写/拆分/拼接/替换/填充/切片包装。
  全部 `str_` 前缀（扁平合并下 `join` 已被任务句柄占用）；`str_split` 单遍扫描，
  1MiB 文本拆分+拼接往返 30ms。
- **`std/url.qma`**：14 个函数——scheme/host/port/path/query/fragment 分段、query 取值、
  百分号编解码（`+` 语义区分 query/path）、IPv6 字面量、非法端口返回 -1 而非退出进程。
- **`std/json.qma`**：DOM 式解析 + builder 序列化（无泛型/反射，明确不做 `to_json<T>`）。
  节点池 6 字/节点、字符串与数字原文存字节缓冲、对象保持源顺序、错误记位置不 fail-fast、
  嵌套深度上限 64；`\uXXXX` 覆盖 BMP 与代理对。
- **`std/gzip.qma`**：DEFLATE（LZ77 3 字节哈希链 + **固定 Huffman**）+ gzip 封装 + CRC-32。
  1 MiB 重复文本 7,658 B（137×）/ 117 ms；`tests/gzip_interop.py` 用 Python zlib 解压
  7 个样本（含 0x00/0xFF 二进制与 671 KB 大输入）逐字节一致。
- **`std/aes.qma`**：AES-128 分组加解密 + **GCM**（CTR + GHASH + tag 校验）。
  FIPS-197 C.1、NIST SP 800-38D GCM case 2/3（含 AAD）全过；另有往返、
  篡改 1 bit 必须失败、AAD 不匹配必须失败。S-box 运行时按 GF(2^8) 生成
  （不用字面量表，绕开 `\xNN` 已知误编译），缓存于 `static_word(12)`。
- **`std/http.qma` 增加压缩协商**：`http_accepts_gzip` / `http_respond_gzip` /
  `http_respond_auto` / `http_json_auto` / `http_html_auto`（<256 B 不压，带 `Vary`）。
  示例 `examples/http_gzip.qma` + 端到端测试 `tests/gzip_http_test.py`：1420 B → 101 B。
- **`bench/p0_bench.qma`**：四件套进程内微基准（sha256 1MiB / split+join 1MiB /
  url×100k / json 2000 对象）。

### 修复 / 发现：两个误编译

- **循环内 `substr` 的长度来自调用结果、结果又 push 进 `vec[str]`**：`--no-opt` 正常、
  开优化必现，越界或错串（`str_split` 因此改为单遍扫描）。
- **`"\xNN"`（≥0x80）被当 Unicode 码点再 UTF-8 编码**：`"\xe4"` 得到 2 字节。
- **循环内一个表达式里两次调用 + 下标**（`f(s[2i])*16 + f(s[2i+1])`）→ 结果整体偏移。
- 三条均已在本轮修掉，夹具转正为 `tests/t53_regress.qma`（详见 v1.8 节）。

### 工程化

- **`tools/dev/check_docs.py`**（新增，进 CI 双 job）：拦"过期断言"
  （`import 只做语法保留` / `元素仅标量` / `vec[Struct] 暂不支持` / `没有长度前缀`），
  并强制 README / HANDOVER / SPEC 链接 `docs/GAPS.md`。
- **`QLM_NO_INLINE=1`**：排查内联相关误编译的开关（与 `QLM_SKIP_PASSES` / `QLM_ENABLE_LICM` 同族）。
- 修 `tests/bodydiff.py` 死代码 import（曾让 `check_origin.py` 一直 FAIL）。
- **文档**：新增 `docs/GAPS.md`（能力边界登记册）、`docs/P0_LIBS.md`（四件套 API/实测）、
  `docs/SELFHOST_PLAN.md`（后端自举 7 阶段排期）；HANDOVER 增加「AI 接力包」记忆注入节。

### 验证

- Windows PE 回归 **103 项全绿**（v1.5 时点 96 + 标准库 6 项 + gzip 互操作 1 项；
  SKIP=1 为 WSL 被沙箱拦）。
- 三道门禁 PASS（check_names / check_origin / check_docs）；对拍 92/92、87/87、50/50、10/10。

---

## 未发布（v1.5，工作区进行中）

> 本版本主题：**性能报告全项落地 + 协议库三件套**。
> 上一轮（v1.4，已提交 d769435/b3e0fe2）：Windows PE IOCP 高并发 reactor
> （net_serve + callr 间接调用）。以下为工作区已落地、尚未提交内容。

### 协议库三件套（全部 Quelmara 自实现，零 Python/Node）

- **`std/http.qma`**：HTTP/1.1 服务端。keep-alive + 流水线（一次 on_data
  派发多个请求）、Content-Length 请求体、头部增量解析（\r\n\r\n 扫描位置
  跨段持久，整请求只扫一遍）、Connection: close / HTTP/1.0 语义。
  明确 fail-fast：chunked → 501、头部超限 → 431、请求行非法 → 400。
  响应单次组包单次 send；零拷贝体访问（`http_body_ptr`）。
- **`std/ws.qma`**：WebSocket（RFC 6455）服务端。握手
  Sec-WebSocket-Accept = base64(sha1(key+GUID))（std/sha1 + std/b64 闭环）、
  帧层全量：7/16/64 位长度、客户端帧强制掩码（1002）、分片消息重组
  （控制帧交错合法）、ping/pong、close 握手、单消息 1MB 上限（1009）。
- **`std/sse.qma`**：Server-Sent Events。W3C event 编码（event/data/id/retry、
  多行 data 拆分）、心跳注释行、`sse_broadcast` 遍历槽位层活跃连接广播。
- **`std/net/core.qma`**：协议共用连接层——定长槽位（640 B/连接，
  十万连接 = 64 MB 常驻、O(1) 归还复用）+ fdtab 开放寻址 + 自旋锁
  （mem_xchg）+ 溢出缓冲自动扩容（上限 1MB/连接）。
- 示例：`examples/http_demo.qma` / `ws_demo.qma` / `sse_demo.qma`
  （本机 Python 客户端实测全绿：200/404/POST 体/流水线；握手校验/
  文本与 70000 字节帧 echo/分片/控制帧交错/close；SSE 建流/retry/
  事件/广播）。
- **修复**：`conn_open` 此前只初始化 w0–w5，协议私有字（扫描位置/分片
  状态）读到 slab 脏页——HTTP 头搜索从垃圾偏移开始永远找不到
  \r\n\r\n。整槽清零。
- **修复**：`std/net/core.qma` 缺 `import std.mem`（flat-merge 下未定义符号）。

### 编译器：性能报告七项优化（对应 Quelmara-性能分析.html）

- **v1.5.1 str 长度前缀 ABI**（报告项 #1，收益最大）：str 值指向
  `[len][字节][NUL]`，`len(s)`/`s[i]` O(1)，越界检查不再内联 strlen。
  实测 16KB 逐字节扫描 85.9ms → **22µs**（~3900×）；
  配套 `opt_strlen_hoist` 跨段合并。
- **2 的幂除法/取模特化**（#2）：`x/2^k`、`x%2^k` 走移位/掩码
  （非负 1 条指令），collatz 300k 203ms → 172ms。
- **掩码值域建模 + 越界检查合并**（#3）：`analyze_ranges` 建模
  `and`/`mod-imm` 上界；`opt_bounds_dedupe` 同一下标读写合并检查。
- **8 字节字块 memcpy**（#4）：字符串拼接 437.5ms → 137ms（3.2×）。
- **内联热函数白名单**（#5）：`__map_hash/__map_find/__map_len` 阈值 160。
- **短循环展开阈值 1024 → 8**（#6）。
- **分配器回收**（#7）：`__realloc` 顶端块原地延展（`__vec_grow` 不再
  泄漏旧块）；`mem_free` 尺寸类归还；sha1 工作区即用即还。

### 编译器：const 跨 import 可见（两遍解析）

- 顶层 const 此前只在单文件解析期内联——std 库的槽位布局常量
  （`std/net/core.qma` 的 SLOT_*/ST_*）对使用方不可见。
  `load_program` 现为两遍解析：第一遍收集全部顶层 const（同名不同值
  报错），第二遍带全集重解析主文件与全部被导入模块。
- **系统级内建（v1.5）**：`now_ns`（单调纳秒，用户侧微基准不再缺位）、
  `mem_alloc/free/load8/store8/load64/store64/copy/zero/cmp/str`、
  `mem_xchg`（x86_64 原子交换）、`tcp_send_n/recv_n`（零拷贝变体）。

### 修复：两个通用形状基准抓出的编译器 bug（v1.5.1）

- **LICM 外提触发 x64 分配器布局敏感段错误**（复现：循环体内含内联
  memcpy 的程序，数据量跨阈值）：QuIR 语义等价、A64 模拟器全绿，
  纯 x64 线性扫描分配器问题。**licm 默认禁用**（QLM_ENABLE_LICM=1
  可开），根修另立轮次（docs/PERF.md §4）。
- **循环展开常量溯源**：60 条宽窗口把别的 mov imm 误当循环上界
  （实测 __memcpy 字块循环 mw=8 被匹配成字节长度 66 → 展开越界）；
  展开副本被下一轮 LICM 二次处理。修复：窗口收紧 12 条、上界定义
  唯一性验证、unroll 移出收敛循环、body 含内层循环 label 不展开。
- **通用形状基准** `bench/gbench.qma`：8 个从未参与调优的代码形状
  （tokenizer/状态机/str 哈希表/日志组装/模式搜索/矩阵/散列链）——
  通用性的裁判是这些形状，不是调优期用例（docs/PERF.md §1-2）。
- **网络负载工具** `bench/loadgen.py`（临时 Python 工具）：短连接/
  长连接流水线/并发；keep-alive 流水线 0.3µs/请求量级，短连接通道
  功能验证通过（沙箱注入使绝对值不可信）。百万连接内存账与配置
  指南：docs/PERF.md §3（rec 惰性分配短连接零累积；百万长连接
  recv_buffer=512 → 总账 ~1.2 GB）。

### 验证

- Windows PE 回归 **96 项全绿**（v1.2 时点 91 → 96）。
- 基准复测（进程内 now_ns，扣除启动开销）：见上文各项实测数字。
- TLS（https/wss）路线定稿：`docs/TLS.md`——Phase A 密码学地基
  （sha256/hmac → aes-gcm → x25519）→ Phase B TLS 1.3 服务端 →
  Phase C 接线，协议层回调签名不变。

---

## 未发布（v1.3，工作区进行中）

> 以下内容已在工作区落地、尚未提交为正式版本；完成后随 v1.3 正式入栏。

### 优化：基于范围证明的越界检查消除 `opt_bounds_elim`

- **通用优化**（非模式特化）：数组/切片/str 下标的越界检查窗口
  （`jcc ge idx, n, fail` × 2 + fail 路径）在**可证明恒通过**时整窗删除。
- 三条证明路径：
  1. **全局上界**：`analyze_ranges` 证明的 `idx` 上界 < n（静态 n）；
  2. **循环级静态**：窗口在规范循环体内、`idx` 是该 guard 的归纳变量、
     guard 上界（可追溯常量）<= n——循环内 `0 <= ivar < hi <= n` 恒真；
  3. **循环级动态**：`n` 与 guard 的 `hi` 是同一个 vreg（如 `for i in 0..n`
     驱动 `buf[i]` 的场景待 CSE 合并 len 后接入，见已知限制）。
- **循环级证明是局部的**：init 紧邻可追溯且 >= 0、step 唯一且 > 0、
  body 内无归纳变量重定义、窗口严格在 body 区间（step 后 `ivar` 可能 == hi）。
  多个循环共享 `i` 的常见形态各自独立成立——不再被全函数 def 唯一性挡住。
- label 引用计数兜底：窗口内 label 被窗口外跳转引用时放弃删除。
- **实测**（Windows PE，1.92 亿次定长数组读写）：`bounds_check=true + 消除`
  642.7ms vs `bounds_check=false`（UB 上限）641.9ms——**检查开销 19.3% → 0.1%**，
  fail-fast 安全性与热循环性能兼得。
- **顺带修复**：`analyze_ranges`（原 `analyze_nonneg`）的循环识别此前只接受
  while 形态的 `jcc l` guard，**所有 for 形态（`jcc ge`）被跳过**——for 循环的
  魔数除法符号修正链收缩因此从未生效。现在两种 guard 条件码统一识别。
- 验证：负向场景（step≠1 的循环、循环外下标、无证明的 vreg）窗口全部保留；
  越界运行时仍 fail-fast（退出码 1）；PE 回归 92 项全绿。
- **已知限制**：切片/str/vec 的动态长度窗口暂不消除——`len(s)` 二次求值
  产生不同 vreg，guard 的 `hi` 与窗口的 `n` 不同源；需要跨块 CSE 合并
  同 (base, off) load 或 LICM 有条件外提 load 后接入（下一轮）。

### 自举：parser 函数体 Phase 1（核心子集对拍，进行中）

- **协议**：函数体 S 表达式逐语句行（`(let mut x (num 0))` / `(binop < ...)` 等），
  str 用 hex 编码、fnum SKIP（Phase 2），未支持形态函数级 SKIP（两侧同判即对拍绿）。
- **两侧实现**：`tools/dev/astbody.py`（stage-0 协议 dump，含 Phase 1 白名单）+
  `bootstrap/parser/qlm_parse.qma` 扩展 `--body` 模式（**Quelmara 写的函数体解析器**
  ~950 行：11 层优先级链、postfix 调用/下标/字段/`?`、SKIP 信号游标盒、回溯）。
- **对拍门禁**：`tests/bodydiff.py`（函数级匹配统计：dump 一致 / SKIP 同步 / 不同步）。
  当前：**77 行 dump 逐字节一致**、SKIP 同步 21——核心子集真实工作。
- **剩余（下一步，bug 模式已定位）**：while+call 条件解析失败、match 表达式拦截、
  若干空格细节——按 bodydiff 的 MISMATCH 清单逐个修即可清零。
- 调试方法学沉淀：错误码打印 + 分步 fail 函数 + ctypes 参照 + capstone 反汇编 +
  monkey-patch eval 定位 + 逐语句 eprint 探针。

### 三条可用性边界补齐（v1.3 本轮）

> 之前"能写单文件计算程序"的三条硬边界（无标准库 / 只读不写 / 自研后端无网络）全部打通。

- **`write_text(path, content) -> int` 三链**：覆盖写整文件、返回写入字节数、失败 fail-fast。
  Windows 走 CreateFileA/WriteFile，Linux 走 openat/write（x64/a64 同一 QuIR），C 走 fwrite。
  写后读回比对测试通过（19 字节往返）。
- **`import` 实装（扁平合并）**：`import std.net` / `import mymod` 递归加载
  `std/`（仓库根，随编译器分发）与主文件同目录的 `.qma`，顶层 fn/struct/enum/test
  扁平合并进主 AST——**后端零改动**（C/native/a64 通用）。名字冲突、循环 import、
  被导入文件定义 main 一律报错。标准库雏形 `std/core.qma`（abs/max2/min2/pow2k）、
  `std/net.qma`（tcp_* 的过程式包装）随仓库分发。既有源码的 `import std.core/net`
  从语法保留变为真实加载。
- **原生 socket 第一格（tcp_* 内建）**：`tcp_listen/accept/send/recv/close` 阻塞式过程
  API。Windows PE 走 **ws2_32 导入**（导入表重构为多 DLL：kernel32 + ws2_32 按函数
  白名单分组）；Linux native 走 raw syscall（socket/bind/listen/accept/sendto/recvfrom，
  x64+a64 号表），CI ubuntu 验证。**本机 echo 实测打通**：listen(19527) → accept →
  recv → send 回显 → close，客户端 19 字节原样返回。
  调试过程中抓出三个新坑（见 HANDOVER 累计教训）。
- **验证**：PE 回归 PASS=92 FAIL=0 SKIP=1；门禁双 PASS。

### 工程化：测试矩阵与 CI

- **`quelmara test --targets all`**：多后端测试矩阵——`native`/`win` 在本机执行级验证，
  `arm64` 走 **A64 模拟器执行级**（`tests/a64_emu.py`），全部可执行目标的输出
  **逐字节比对**（跨后端/跨架构交叉验证自动化）；不可执行的目标做构建级 SKIP
  并说明原因。`--targets native,win` 逗号分隔子集同样支持。
- **CI 接入**（`.github/workflows/ci.yml`）：Linux job（门禁 + 自举对拍四件套 +
  五套回归，含 AArch64 模拟器与 io_uring）与 Windows job（门禁 + PE 回归 +
  对拍 + `test --targets all`），push/PR 触发。
- **`qlm_fmt` 新语法覆盖确认**：全量冒烟 62/62 个 `.qma`（含位运算/vec/for-in/
  子切片/vec 聚合）零崩溃——fmt 是 token 级重排，新语法天然适用。
- **默认多核口径确认（无代码改动）**：`[core] multicore = true` / `threads = 0`
  （自动物理核数）即出厂默认，`parfor` 自动分块、`spawn` 自动并行——
  用户程序不需要手写循环拆分或指定核心数；单核是显式 opt-out。

### 自举：parser 声明级

- **parser 声明级自举**：`bootstrap/parser/qlm_parse.qma` 与 stage-0 声明级 AST
  对拍 **68/68 全等**（`tests/parsediff.py`，辅以 `tools/dev/astdecl.py`）。
- **新增对拍脚本**：`tests/irdiff.py`（QuIR 架构无关 46/46，14 skip：a64 无 chan/map）、
  `tests/emitdiff.py`（发射层确定性 10/10 + ELF/PE「无 CRT」结构自检）。
- **自举进度 2/9**：词法 ✅（v1.0）、语法声明级 ✅（本节）；自举代码 774 行，
  占引导层 16.3k 行的 4.5%（`tools/dev/selfhost_status.py`）。
- **`vec[Struct]` 聚合元素**：工作区夹具 `tests/t37_vecagg.qma` 验证 struct 元素
  按值拷贝进出（改副本不影响表内元素），为 AST 节点表铺路。
- 下一步：parser 函数体对拍（AST 逐层比对）→ `bootstrap/typeck/`。

---

## v1.2 — 2026-10-20 vec[T] / 集合遍历 / 数组参数返回 —— 自举 parser 的地基补齐

### 新特性

- **`vec[T]` 堆上变长数组**：`vec[T].new(cap)`、`push/get/set/pop/len/clear`。
  元素仅标量（int/bool/str，各占 8 字节槽）；容量翻倍扩容 + `__memcpy` 搬数据；
  句柄语义（函数内 push 对调用方可见）；C 后端用 `malloc/realloc`，
  自研后端用 `__alloc`（旧块由 arena 回收）。空表 `pop()` / 越界 `get/set` 一律 fail-fast。
- **`for x in <map|vec>` 集合遍历**：map 产出键（按桶序，**实现定义**），vec 按下标序。
  与区间循环 `for i in a..b` 靠 `..` 区分；遍历期间修改集合是未定义行为，已写进 SPEC。
- **`[N]T` 作函数参数/返回值**（自研后端）：参数按值拷贝（callee 改不到调用方），
  返回值走隐藏出参指针，与切片/结构体返回同一套 ABI。
  C99 后端（仅交叉验证）会明确拒绝并提示改用 `slice_of` / `vec[T]`。
- 自举词法器的关键字表补上 `const` / `vec`。

### 为什么这一步重要

自举 parser 需要三样东西：**可增长的同质容器**（token 表 → `vec`）、
**可枚举的符号表**（→ `for k in m`）、**按值传的定长缓冲**（→ `[N]T` 参数）。
这三块地基补齐后，`bootstrap/parser/` 才具备开工条件。

### 验证

- Windows PE：**91 项全绿**（v1.1 的 88 + vec + iter + arrparam）。
- 词法对拍：**71/71 全等**（新增三个夹具 + 关键字同步）。
- 新增夹具可直接当示例读：`tests/t34_vec.qma` / `t35_iter.qma` / `t36_arrparam.qma`。

---

## v1.1 — 2026-10-20 位运算 / 子切片 / const / 字典序 / 跨平台基线 / 原创性自查

### 新特性

- **位运算**：`& | ^ ~ << >>` 与 `>>>`（逻辑右移），复合赋值 `%= &= |= ^= <<= >>= >>>=`。
  优先级是 Quelmara 自定义层次（`| < ^ < & < 比较 < 移位 < 加减 < 乘除`），
  与 Go（移位在乘法层、`|` 在加法层）和 Python（`&` 高于 `^`）都不同，见 SPEC §1.1。
- **进制字面量**：`0xFF` / `0b1010` / `0o755`（编译器写指令编码的前提）。
- **子切片 `a[lo..hi]`**：左闭右开。`str` 切片是**拷贝**（与不可变语义一致），
  切片/数组切片是**零拷贝视图**；越界 fail-fast。两个后端都实现。
- **顶层 `const`**：只接受字面量（含负号），在**解析期内联**，不产生运行时存储。
- **`eprint(x)` / `exit(code)`**：诊断输出与显式退出；`exit` 支持运行期退出码。
- **字符串字典序**：`< <= > >=` 现在按无符号字节比较（此前是指针比较——文档写了但没实现）。
- **跨平台 bench 基线**：`quelmara bench <src> --targets win,arm64 --update-baseline`。
  基线 key = `平台/架构/后端/源名`，时间只在同 key 内比较；
  **输出哈希跨后端必须一致**，这是"跨平台"真正守住的东西。基线文件 `bench/baseline.json` 入库。

### 原创性

- `docs/ORIGINALITY.md`：代码来源声明、依赖清单、与 Python/Go 的 12 项设计差异对照。
- `tools/dev/check_origin.py`：只允许标准库依赖（`try/except ImportError` 包住的可选依赖只警告）、
  禁止其它语言运行时特征标识、禁止第三方产物目录。
- 内部表示更名 **QuIR**（原 RosIR），彻底去掉旧项目名残留。

### 验证

- Windows PE：**88 项全绿**（v1.0 的 86 + 位运算 + 子切片）。
- 词法对拍：**68/68 全等**（自举词法器同步支持 `& | ^ ~ << >> >>>` 与进制前缀）。
- 跨平台基线：`win` 与 `arm64`（自研模拟器）对同一源码产出相同输出哈希。

---

## v1.0 — 2026-10-20 Quelmara 改名 + 自举前置能力 + stage-1 词法器

### 改名与工具链分层

<!-- legacy-ok:begin -->
- 语言/产品 Rosoto → **Quelmara**；内部符号 `qlm_*` / `Qlm*` / `QLM_*`。
- Python 编译器整体下沉到 **`tools/stage0/`**（引导层，待退场）；自举源码放 `bootstrap/`。
- 源码扩展名 `.ros` → **`.qma`**（硬切：`.ros` 直接退出码 2 并给出 `git mv` 命令）；
  产物扩展名按 target 定：`win → .qex`，`native/arm64 → .qel`，`c → .c`。
- 配置 `Rosoto.toml` → `Quelmara.toml`（检测到旧配置报错提示改名，不静默回退默认值）。
- 新增 `docs/EXTENSIONS.md`（扩展名规范）、`docs/MIGRATION_rosoto_to_quelmara.md`、
  `docs/SELFHOST.md`（组件退场表）；`tools/dev/check_names.py` 常驻门禁。
<!-- legacy-ok:end -->

### 新特性（自举前置能力）

- **`__alloc` 8 字节对齐**：堆上聚合按字宽落位（a64 上非对齐访问会直接崩）。
- **`args() -> []str` / `arg(i)`**：不含程序名。
  Linux/AArch64 由 `_start` 从内核栈取 argc/argv（零拷贝）；
  Windows 走 `GetCommandLineA` + 两遍扫描拆分（引号分组、去引号），只用 kernel32。
- **`read_text(path) -> str`**：整文件读入（Windows `CreateFileA/ReadFile`，Linux `openat/read`），失败 fail-fast。
- **`substr(s, lo, n)` / `chr(byte)`**：子串与单字节串，越界 fail-fast。
- **切片元素标签**：`[]str` 的下标结果标记为 str（否则 `print(a[i])` 打成指针），
  且 `let` 拷贝时标签随值传播。

### 修复（都是自举词法器跑起来才暴露的）

- **`||` 恒为真**：`lower_logic` 里 `&&` 与 `||` 共用了一段「落空即 true」的尾巴，
  导致 `0 || 0 == true`。两条短路分支的落空值现在分开处理。
- **`let` 是别名而不是拷贝**：`let mut j = i` 直接把 `env[j]` 指向 `i` 的同一个 vreg，
  改 `j` 会连带改 `i`（值语义被破坏）。现在标量一律拷贝到新 vreg，
  并传播 str/bool/chan/map/float 全部类型标签。
- **`bin sub dst, imm, dst` 恒为 0**（v0.12 发现）：取反改用专用 `neg`。
- **`@extern("C")` 在自研后端裸崩**（v0.12）：改为入口显式拒绝。

### 自举里程碑

- **`bootstrap/lexer/qlm_lex.qma`（268 行 Quelmara）**：流式词法器，
  不依赖可变长数组/位运算/map 遍历。
- **对拍 66/66 全等**：`tests/lexdiff.py` 用协议 `KIND|RAW|LINE` 比对
  全部 `.qma`（含词法器自己的源码）与 Python 词法器，逐行一致。
- `quelmara lex`：默认优先用 stage-1 自举词法器，`--stage0` 强制 Python，输出带实现标签。
- `tools/dev/selfhost_status.py`：组件自举进度（当前 1/9，词法已就位）。

### 验证

- Windows PE：**86 项全绿**（v0.12 的 74 + args 4 + io 7 + logic 1）。
- AArch64：模拟器 `t1 => 1`、t27/t28 与 x86 全等。
- 待 Linux 环境验证：`run_tests.sh`（C99 链）、`run_native_tests.sh`（含 C 双跑）。

---

## v0.12 — 2026-10-20 字符串可用性 + @extern 收口

### 新特性

- **`len(s)` 支持 `str`**：走自研后端既有运行时 `__str_len`（字节扫描），
  C 后端走 `strlen`。字符串是零结尾字节串，没有长度前缀，所以是 O(n)。
- **`s[i]` 字符串字节下标**：返回该字节的**无符号值**（0..255，`movzx` 零扩展），
  走与数组/切片同一套动态越界检查；越界 fail-fast（stderr + 退出码 1）。
- **`s.to_int()` / `to_int(s)`**：十进制解析，支持前导 `+`/`-`、前导零。
  非法输入（空串、非数字、前后空格）与 int64 溢出**一律 fail-fast**，
  不静默返回 0、不静默回绕。自研端 `__str_to_int` 与 C 端
  `qlm_str_to_int` 判定顺序逐条对齐。
- **`to_int()` 方法式语法**：浮点 `f.to_int()` 也顺势支持（向零截断）。

### 修复

- **`@extern("C")` 在自研后端裸崩**：v0.11 只实现了 C 后端的原型发射，
  `body=None` 一路漏到 lowering，PE/native 抛 `TypeError: 'NoneType' object
  is not iterable`（Python traceback）。现在在 `run()` 入口显式拒绝并给出
  人话诊断（自研后端产出裸 ELF/PE，没有动态链接器，不解析外部符号）。
- **`bin` 指令 dst 与 rhs 同 vreg 且 lhs 为 imm 时结果恒 0**：`bin sub acc,
  imm0, acc` 先写 dst 再读 rhs，读到的已是被覆盖的值。取反一律改用专用
  `neg` 指令，不再用减法模拟。
- **`quelmara build --target arm64` 完全不可用**：`_build_arm64` 把
  `transpile_a64()` 的 `(blob, cfg)` 二元组直接当 `(out, size, cfg)` 返回，
  CLI 一解包就 `ValueError: not enough values to unpack (expected 3, got 2)`，
  连 `hello.qma` 都编不过。现在补上 `write_elf_a64()` 写盘，AArch64 目标从
  CLI 恢复可用（t27/t28 已能在自研模拟器上跑通）。

### 验证

- Windows PE：**74 项全绿**（v0.11 的 59 + 字符串 15）。
  新增 `[3c] 字符串`：t27/t28 自校验、str 越界、5 类非法十进制、
  `@extern` 诊断共 15 条断言。
- AArch64：t27/t28 经自研模拟器执行，输出与 x86 全等；str 越界同样 fail-fast。
- native runner 新增 `[21] str` / `[22] @extern` 段（native + C 双跑 + 双链 diff + a64 对拍）。

---

## v0.11 — 2026-10-20 任务/通道语法补全（已提交 `ade98a4`，2/2 见 v0.12）

### 新特性

- **`h.join()` 方法式语法**：与函数式 `join(h)` 完全等价（解析期脱糖，
  用户自定义 join 函数优先）；支持 `spawn f(x).join()` 直连式（t24）。
- **`chan.close()`**（t25）：控制块新增 `closed` 字（自研后端布局扩为 7 字）。
  - close 后 `send` fail-fast（stderr + 退出码 1）；重复 close fail-fast；
  - `recv` 排空缓存数据后返回 0（零值）；关闭只阻止新 send，不动已缓存数据；
  - C 端广播唤醒全部等待方，自研端 spin+yield 循环重检。
- **`chan select`**（t26）：`select { c1.recv(), c2.recv() }` 表达式，
  返回首个就绪臂的值。轮询 + yield（C 端 usleep 100µs）；声明序优先；
  全部关闭且排空返回 0；关闭的空臂被跳过。非阻塞取数走
  `try_recv(h, &ok)` 出参协议（自研后端帧槽传址）。

### 验证

- Windows PE：59 项全绿（t24/t25/t26 + 2 个 fail-fast 退出码用例）；
- native runner 新增 [18] join 方法式 / [19] chan close / [20] select 段
  （native + C 双跑 + 双链 diff，需 Linux 环境执行）。

---

## v0.10 — 2026-10-20 map[K]V + 浮点运算（已提交 `b42e0a4`）

### 新特性

- **`map[K]V` 开放寻址哈希表**（K ∈ int/bool/str，V ∈ int/str）：
  `map[K]V.new(cap)` 构造、`set/get/has/del/len`、覆盖写、str 键内容相等判定、
  cap=16 起步插 200 键自动扩容、删除后墓碑复用、map 作函数参数/返回值（句柄传递）、
  arena 块内绑定。缺失键 `get` fail-fast（回归 [16]，自研/C 三链）。
- **浮点实际运算**（`float` = f64，`f` 后缀 = f32）：字面量 / 四则运算 / 比较 /
  `to_int` / `to_float` / 一元负号 / 函数参数与返回值 / `to_str()`，
  格式化与 C 端 `qlm_f64_to_str` 算法逐位一致：`[1e-6, 1e12)` 定点 6 位小数去尾零，
  其余科学计数 `d.dddddde±N`，nan/inf/-inf/0 特判（回归 [17]，自研/C 三链）。

### 修复

- **自研后端 `__f64_to_str` 科学计数法死循环**（潜伏 bug）：IR 非 SSA，
  两个归一化循环（`x/=10` 降位数 / `x*=10` 升位数）曾写入新 vreg 再 rebind
  Python 变量，循环条件读到的仍是旧 vreg → 进入科学计数路径即无限循环
  （`print(0.0000001)` / `print(1e12)` 挂死）。改为原地更新（`dst==src`，
  同 itoa 的 `div v,v,10` 模式）后修复；C 端本来就是真 while 循环，不受影响。

### 验证

- Windows PE：[1]–[6] 段 **52 项本机全绿**（含新增 float 用例）；
  [7] PE×ELF 交叉验证表已登记 t22/t23（共 13 项，需 WSL 环境执行）。
- 自研 Linux：native runner 新增 [16] map 3 项 + [17] 浮点 3 项（需 Linux 执行）。

---

## v0.9 — 2026-10-20 性能轮（已提交 `b42e0a4`）

**基准**（Xeon E5-2666 v3 / WSL2 / gcc 15.2，`tests/bench.sh` best-of-3）：

| 基准 | v0.8 自研 | **v0.9 自研** | gcc -O2 / pthread | 原目标 |
|---|---|---|---|---|
| loop_sum 2 亿热循环 | 380–518 ms | **11–13 ms** | 231 ms | 80 ms ✅ |
| parfor_sum 6M 任务 / 3 核 | 388–620 ms | **29–35 ms** | 131 ms | 50 ms ✅ |

### 优化

- **模块级数求和折叠 `opt_modsum`（新 pass，`tools/stage0/qlm_opt.py`）**
  规范归约循环 `acc += (x0 + s·j) mod D`（gcd(s,D)=1 且 x 非负已证）整体折叠：
  - 整周期块：任意连续 U=D 项余数是 0..D-1 的排列 ⇒ 每块贡献常量 `D(D-1)/2`，
    `B = N//U` 块直接折叠成 `acc += B·D(D-1)/2`（N 编译期常量时继续常量折叠）；
  - 尾部 R<U 项：s=1 走无除法闭式 `R·tB + R(R-1)/2 − D·max(0, tB+R−D)`；
    s>1 保留只跑 R 次的 peel 小循环；
  - 归约按 2^64 环面同态，回绕语义与逐项累加严格一致。
  - 边界：gcd(s,D)>1 / 迭代数非编译期常量 / x 非负不可证 → 整体放弃，语义不变。
- **范围分析扩展（`analyze_nonneg` + `lower_parfor`）**
  - parfor worker 形参范围：clone() 调用点均为编译期常量块界 → `arg_ranges` 元数据；
  - `for` 形态 `jcc ge` 守卫与 `while` 形态统一按 `i < hi` 做上界证明；
  - 双 vreg 加法传播（如 `i*C + k`）、形参初始化归纳变量；
  - 效果：worker 热循环里有符号魔数除法的双重符号修正链整体消除（parfor 原 4 倍差距的主因）。
- **乘常数编码修复（`tools/stage0/qlm_native.py`，潜伏 bug）**
  `mul_const` 回退路径（lea 链规划失败时）曾把 `x*C` 静默编码成 `x*x`——常数被丢弃。
  新增 `Enc.imul_rri`（三操作数 `imul r64, r64, imm32`）修正；历史上任何
  lea 链规划不下的常量乘法都会错编，本轮由 modsum 闭式代码首次触发并修复。

### 验证

- 回归 **198 项全绿**：Windows PE 61 / 自研 Linux 61 / C 16 / corelib 34 / io_uring 26（本地 + 机器上各跑一遍）；
- modsum 差分模糊 **180 例**：优化 ≡ 无优化 ≡ Python 真值（含负值门控组，覆盖放弃路径）。

### 未发布（工作区既有内容，随本轮一起进入快照）

- `result[T,E]` 泛型单态化 + `?` 传播 + match 解构（回归 [14]，三链全绿）；
- `[]T` 切片：{ptr,len} 两字零拷贝视图 + 聚合 ABI + 动态越界 fail-fast（回归 [15]，三链全绿）。

---

## v0.8 — 2026-10-19 19:59 `option[T]` 受控单态化

- `option[int/bool/str]` 跨 native / Windows PE / C 三链：`option[T].some(x)/.none()` 构造、
  `Option.Some(v)/Option.None` match 解构、函数返回 `option[T]`（复用枚举聚合 ABI）。
- 实现 = 前端合成真枚举 `__opt_<T>` + 构造脱糖 `enumlit` + 模式按求值式真实枚举名改写；后端零改动。
- 回归 187 项全绿（Windows 57 / native 54 / C 16 / corelib 34 / io_uring 26）。

## v0.7 — 2026-10-19 18:21 Result 错误传播 + 保守范围分析

- 用户定义 `Result` 枚举 + `?` 传播三链打通；`Ok` tag 按声明顺序取，不再硬编码 0。
- 自研优化器：严格递增常量上界循环的非负范围传播，安全消除有符号魔数除法符号修正链；
  parfor/spawn worker 保留 `no_inline` 寄存器分配边界。
- 回归 183 项全绿。

## v0.6 — 2026-10-19 14:29 定长数组 `[N]T`

- 帧上连续 N 字、动态下标、值语义拷贝、越界 fail-fast（`bounds_check` 编译期开关）。
- 数组作参数/返回值明确报错（切片见未发布项）。回归 180 项全绿。

## v0.5 — 2026-10-19 14:22 `chan[T]` 有界 MPMC 通道

- 48 字节控制块 + `xchg` 自旋锁 + yield；C 后端条件变量等价实现。
- 运行库按需发射：只用到的 arena/join/chan 才进产物。回归 172 项全绿。

## v0.4 — 2026-10-19 13:46 `spawn`/`join` 任务并行 + arena 帧级回收

- `spawn f(args)` + `join(h)`；Linux raw `clone()` / Windows `CreateThread` / C pthread。
- arena 回卷 bump 指针，块内分配一次性回收。回归 165 项全绿。

## v0.3 — 2026-10-19 13:01 自研 Windows x86_64 PE/COFF 后端

- 同一 QuIR → PE32+ / COFF + kernel32 导入 + DIR64 重定位，无 CRT，产物 6–26 KB。
- 回归 152 项全绿。

## v0.1–v0.2（此前）

- v0.1：Quelmara → QuIR → 优化 passes → 线性扫描寄存器分配 → 自研指令编码器 → 裸 ELF64；
  魔数除法（mulhi+移位）、常量折叠、复制传播、DCE、cmp+jcc 融合、帧槽复用。
- v0.2：QuIR 优化器成型（LICM / CSE / 循环展开 / 指令调度 / 强度削减）、内联、
  运行库 QuIR 自举（print/itoa/strlen/alloc）。

---

*维护约定：性能改动必须附 `tests/bench.sh` 基线对比 + 全量回归数字；
优化 pass 不满足证明条件时必须安全放弃，语义等价由 C 后端交叉验证兜底。*
