# 标准库

标准库全部是 **Quelmara 源码**（`std/*.qma`），无第三方运行时依赖。`import` 时按需合并，
未用到的函数由全局 DCE 剔除（`QLM_NO_DCE=1` 可关）。

> API 清单由源码自动提取，只列**公开函数**（不带 `_` 前缀）。私有函数是内部实现细节，不承诺稳定。
> 重新生成：见本文件末尾「维护方式」。

## 1. 模块总览

70 个模块，**584 个公开函数**（另有 597 个内部函数）

<!-- overview:begin -->
| 模块 | 一句话 | 公开 / 全部 |
|---|---|---|
| `std/aes` | AES-128-GCM：分组加密（AES-NI 快路径 + T-table 降级）+ GHASH + CTR | 10 / 38 |
| `std/b64` | base64 编解码 | 5 / 9 |
| `std/blake2b` | BLAKE2b（RFC 7693）密码学哈希 + keyed / 变长输出 | 4 / 10 |
| `std/cli` | 命令行 flag 解析（--k=v / --k v / -k v） | 6 / 9 |
| `std/cookie` | Cookie 头解析与 Set-Cookie 生成（取值 / 百分号编解码 / Max-Age / SameSite / HttpOnly / Secure） | 6 / 9 |
| `std/core` | 标量小工具 | 0 / 4 |
| `std/crc64` | CRC-64/XZ（ECMA-182 反射多项式，xz/zlib 容器的 64 位校验） | 2 / 3 |
| `std/csv` | CSV 解析与生成（RFC 4180：引号包裹 / "" 转义 / 字段内换行 / CRLF 或 LF） | 4 / 6 |
| `std/deque` | 双端队列（两端 O(1) + 自动扩容） | 13 / 21 |
| `std/ds` | 环形缓冲与二叉最小堆 | 13 / 13 |
| `std/f64` | 十进制文本 ↔ f64（严格十进制解析 + Clinger 快路径，非十进制 fail-fast） | 3 / 16 |
| `std/fs` | 文件读写（open/read/write/seek/size/sync/close/rename；Windows PE，@ffi 直调 kernel32） | 11 / 20 |
| `std/gen` | 泛型算法库（min/max/clamp/dist/contains/index_of/reverse，调用点推导单态化） | 0 / 9 |
| `std/gzip` | DEFLATE 编码 + gzip 包装 + CRC-32；v1.19 起含 inflate 解码 | 6 / 33 |
| `std/hash` | FNV-1a 32/64 非密码学哈希（缓存键 / 分片） | 4 / 4 |
| `std/hex` | 十六进制编解码 | 4 / 5 |
| `std/http` | HTTP/1.1 服务端（keep-alive / 流水线 / 压缩协商 / chunked 请求体 v2.95） | 39 / 55 |
| `std/http_chunk` | Transfer-Encoding: chunked 的扫描与就地解包（纯内存，零 socket 依赖；v2.95） | 2 / 2 |
| `std/httpc` | HTTP/1.1 客户端核心：URL 拆分 / 请求构造 / 响应解析（content-length / chunked）/ 重定向判定（纯函数，零 socket 依赖） | 8 / 16 |
| `std/httpc_net` | HTTP 客户端传输层：httpc_get / httpc_get_tls / httpc_get_follow（Windows；TLS 走 std/tls_net） | 3 / 19 |
| `std/httpdate` | HTTP 日期（RFC 7231 IMF-fixdate）格式化与解析 + If-Modified-Since 判定 | 3 / 13 |
| `std/json` | DOM 式 JSON 解析与 builder | 32 / 85 |
| `std/kv` | 持久化键值存储（追加日志 + 内存索引；重开重放 / 撕裂尾恢复 / 压缩；Windows PE） | 11 / 16 |
| `std/log` | 日志核心（级别过滤 / 绝对时间戳 / stdout·stderr 双通道 / 结构化字段） | 17 / 23 |
| `std/logfile` | 日志文件通道 + 按大小轮转（攒批写 + 共享打开可 tail；Windows PE） | 12 / 20 |
| `std/lru` | LRU 缓存（开放寻址表 + 双向链表，单句柄 O(1)） | 10 / 24 |
| `std/math` | 浮点与整数数学（exp/log/pow/sin/cos/atan/双曲/hypot + sqrt/cbrt/取整/gcd） | 44 / 51 |
| `std/md5` | MD5（RFC 1321，仅兼容用途，不要用于密码） | 1 / 5 |
| `std/mem` | slab 分配 / fd 表 / 缓冲 / 对象池 | 21 / 30 |
| `std/mime` | 扩展名 ↔ Content-Type（内置 30 项表，大小写不敏感，带 charset 参数反查） | 4 / 5 |
| `std/multipart` | multipart/form-data 解析（boundary 提取 / 表单字段与文件部分 / 头字段大小写不敏感） | 4 / 6 |
| `std/net` | 阻塞 TCP 便捷层 | 16 / 18 |
| `std/net/addr` | 地址文本层：IPv4/IPv6 字面量解析与 RFC 5952 格式化 + fd 对端地址 | 11 / 15 |
| `std/net/core` | 连接槽位层（IOCP reactor 的底座） | 22 / 22 |
| `std/net/dns` | 自研 DNS 解析器（RFC 1035 最小子集：A 记录 / 压缩指针 / resolv.conf） | 8 / 9 |
| `std/net/reactor` | 高并发 reactor：IOCP 事件循环（Quelmara 实现，仅 Windows PE） | 2 / 22 |
| `std/net/udp` | UDP 封装与地址解析 | 2 / 3 |
| `std/net/udp6` | UDP over IPv6：文本地址转换 + 便捷发送（udp_open6/udp_bind6 内建） | 4 / 4 |
| `std/p256` | NIST P-256 域运算 + ECDSA 验签（TLS 证书签名） | 2 / 45 |
| `std/p384` | NIST P-384（secp384r1）ECDSA 验签（12 limb Montgomery + Jacobian，SHA-384 摘要；v2.99） | 2 / 47 |
| `std/park` | 线程 park 原语：WaitOnAddress / WakeByAddress（仅 Windows PE；由 std/sync 注入使用） | 4 / 7 |
| `std/park_linux` | 线程 park 原语：futex(2)（仅 Linux；与 std/park 同一组 API，由 std/sync 注入使用） | 4 / 6 |
| `std/path` | 路径处理（join / clean / dir / base / ext / stem；'/' 与 '\' 都认） | 7 / 9 |
| `std/rand` | xorshift64* 伪随机 | 4 / 5 |
| `std/regex` | 正则引擎（回溯 VM）：字面/./字符类/转义类/量词 *+?{n,m}/交替/分组(?:)/锚点 ^$；compile+match/full/exec/find/replace[_all]，步数上限防病态回溯 | 7 / 24 |
| `std/router` | 路径模板匹配（/users/:id、尾部 * 通配、query/尾斜杠归一化、方法白名单） | 11 / 14 |
| `std/rsa` | RSA PKCS#1 v1.5 / PSS 验签（SHA-256，证书链与 TLS 用） | 3 / 14 |
| `std/serialize` | LEB128 varint / 定长整数 / 长度前缀帧 | 0 / 10 |
| `std/session` | 内存会话存储（sid 生成 / TTL 惰性过期 / 滑动续期 / 墓碑销毁） | 8 / 9 |
| `std/set` | 集合 set[int] / set[str]（map 支撑，含交并差） | 14 / 17 |
| `std/sha1` | SHA-1 | 1 / 5 |
| `std/sha256` | SHA-256 + HMAC-SHA256 | 4 / 13 |
| `std/sha512` | SHA-512 / SHA-384（变体 IV 复用压缩函数）+ HMAC-SHA512 | 6 / 12 |
| `std/sort` | 快速排序与有序性检查 | 2 / 5 |
| `std/sse` | Server-Sent Events 服务端 | 0 / 20 |
| `std/staticfile` | 静态文件服务的安全解析层（URL 解码 / 目录穿越防护 / index 补全 / Cache-Control / ETag / Range 解析） | 9 / 14 |
| `std/str` | 字符串工具集 | 26 / 30 |
| `std/sync` | 自旋锁 / Treiber 无锁栈 / WaitGroup（零 @ffi，park 由调用方注入） | 13 / 15 |
| `std/time` | 时间便捷层 | 0 / 2 |
| `std/timer` | 轮询式定时器（mem 块上的二叉最小堆；无后台线程 / 无回调，主循环 poll） | 5 / 9 |
| `std/tls13` | TLS 1.3 密钥调度（HKDF-Expand-Label）+ AEAD 记录层 | 23 / 29 |
| `std/tls_client` | TLS 1.3 客户端握手核心 + 证书链入口（RFC 8448 逐字节） | 7 / 13 |
| `std/tls_net` | TLS 1.3 网络层：TCP 建连 + 握手 + 应用数据（Windows） | 3 / 5 |
| `std/url` | URL 解析 / query 取值 / 编码解码 | 12 / 19 |
| `std/utf8` | UTF-8 解码/编码/严格校验（RFC 3629） | 7 / 8 |
| `std/uuid` | UUID v4 生成 + nil + 校验/版本/变体位（随机源为 std/rand，非密码学） | 5 / 9 |
| `std/ws` | WebSocket 服务端（RFC 6455） | 0 / 24 |
| `std/x25519` | Curve25519 上的 X25519 密钥交换（RFC 7748，TLS ECDHE 地基） | 3 / 21 |
| `std/x509` | X.509 解析 + P-256 验签 + 证书链/有效期/域名校验 | 19 / 42 |
| `std/x509roots` | 内置 TLS 根证书库（12 个主流根 + 按 DN 配锚 + 一键验证到表内锚；v2.97） | 6 / 7 |
<!-- overview:end -->

## 2. 用法约定

```quelmara
import std.json
import std.http
```

- 每个模块一个文件，函数用**模块前缀**防冲突（`http_` / `ws_` / `str_` / `url_` …）——
  这是历史惯例：`import` 是扁平合并，同名会撞。v1.99 起编译器会给**真重名**的导入方加
  `<模块>__` 前缀（per-module mangling，见 `02-language.md` §1），前缀不再是唯一手段，
  但 std 全库仍按它命名（改名的收益抵不上破坏既有调用点）。
- **跨模块引用要求 `pub`**（v1.43）：非 `pub` 的顶层声明只在本模块内可见。`std` 里有 10 个
  模块当前**一个 `pub` 都没有**（下表"公开 / 全部"列为 `0 / N`），用户代码引用会编译失败，
  清单见 `07-gaps.md` §7.13。
- 所有 `str` 参数都是长度前缀值；**不要**把 `("ga", gid)` 这类全局字符串直接传进 str 函数，
  必须先 `+8` 成数据指针（`read_asset` 踩过这个坑）。
- 库函数出错多为 fail-fast（退出进程）或返回 `-1`/空串，**没有错误对象**（见 `07-gaps.md`）。

## 3. 公开 API 全表

> 格式：`fn 名字(参数) -> 返回`。省略返回表示无返回值。
> 参数类型以源码为准；`int` 常被用作"内存地址"（裸指针），这类函数在说明里标了 `ptr`。

<!-- api:begin -->

### `std/aes.qma`

AES-128-GCM：分组加密（AES-NI 快路径 + T-table 降级）+ GHASH + CTR

```quelmara
/// AES-128 密钥扩展：key 16 字节 → rk 176 字节（11 轮 × 16）。
/// rk 由调用方分配，后续加解密复用它。
fn aes128_expand(key: str, rk: int) -> int
/// 加密一个 16 字节分组（inp → out，rk 来自 aes128_expand）；恒返回 0。
/// 软件路径（T-table），AES-NI 可用时内部走快路径。
fn aes128_encrypt_block(inp: int, out: int, rk: int) -> int
/// T-table 加密（v1.28）：每轮 16 次 32 位查表 + 异或，替代逐字节 SubBytes/MixColumns。
/// 只用于 GCM 的 CTR 路径；解密仍走逐字节实现（GCM 不需要 AES 解密）。
fn _aes128_encrypt_block_fast(inp: int, out: int, rk: int) -> int
/// v1.31：AES-NI 单块加密（cpu_aes() == 1 时启用）。
/// 10 轮全是硬件指令（AESENC ×9 + AESENCLAST），没有查表——
/// 既快（一个块 ~10 个周期级操作）也没有 T-table 的缓存侧信道问题。
/// rk 是 aes128_expand 产出的 176 字节标准轮密钥表，AESENC 直接吃这个字节序
/// （软件路径要 _bswap32 是因为它按大端字读，硬件按字节读，不需要转换）。
/// xmm 槽 0/1 是固定协议：0 = 状态，1 = 轮密钥。
fn _aes128_encrypt_block_ni(inp: int, out: int, rk: int) -> int
/// 解密一个 16 字节分组（inp → out）；恒返回 0。
/// **不用于 GCM**：GCM 只需加密方向，CTR 模式解密即加密。
fn aes128_decrypt_block(inp: int, out: int, rk: int) -> int
/// GHASH 的 128 位乘法：Z = X * H（X、H 都是 16 字节大端缓冲）
/// 逐位算法：Z 累加 V，V 每轮右移并在最低位为 1 时异或 R=0xE1<<120。
fn _gf_mul(x: int, h: int, out: int) -> int
/// 由 H（16 字节）预计算 GHASH 用的 4-bit 表（t 缓冲 16×16 字节）。
/// 表只需建一次，多次 GCM 复用；导出为 pub 是为了让基准/测试能单独测。
fn _ghash_table(h: int, t: int) -> int
/// 4-bit 表乘法：Y = X · H。
/// v1.32：改成**按 64 位字**累加，并且累加器留在两个局部变量里。
/// 旧实现每个 nibble 做 16 次 mem_load8 + 16 次 mem_store8（一块 1024 次
/// 字节操作），是 GCM 在 AES-NI 之后唯一的瓶颈；字级之后每 nibble 只剩
/// 2 次读 + 2 次异或，且 32 个 nibble 期间不碰内存。
/// 字节序不用管：表行就是 16 字节原样，字级异或 + 字级写回与字节级等价。
fn _gf_mul_t(x: int, t: int, out: int) -> int
/// gcm_encrypt(key, iv12, aad, plain) -> str
///   返回密文 || 16 字节 tag（TLS 1.3 的 AEAD 布局）
fn gcm_encrypt(key: str, iv: str, aad: str, plain: str) -> str
/// gcm_decrypt(key, iv, aad, sealed) -> str
///   sealed = 密文 || tag；tag 不匹配返回 ""（调用方必须当作失败处理）
fn gcm_decrypt(key: str, iv: str, aad: str, sealed: str) -> str
```

### `std/b64.qma`

base64 编解码

```quelmara
/// 把缓冲区 p 的前 n 字节编码为标准 Base64（字母表 A-Za-z0-9+/，带 `=` 填充）。
/// 输出一次性分配，长度 = ⌈n/3⌉×4。
fn b64_encode(p: int, n: int) -> str
/// 真实长度看 b64_decode_into 的返回值，别按上界算。
/// 解码输出缓冲区的**上界**字节数（⌈len/4⌉×3+1），用于 mem_alloc。
fn b64_dec_max(s: str) -> int
/// 把 Base64 文本解码进调用方缓冲区 out，返回写入的字节数。
/// 非字母表字符（含 `=` 填充与空白）直接跳过；不做长度合法性校验。
fn b64_decode_into(s: str, out: int) -> int
/// Base64url 编码（`-` `_` 替代 `+` `/`，**无填充**），用于 JWT / URL 参数。
/// 输出一次性分配，长度 = 4×⌊n/3⌋ + {0,2,3}。
fn b64url_encode(p: int, n: int) -> str
/// Base64url 解码进调用方缓冲区 out，返回写入字节数；`-` `_` 与标准字母表都认。
/// 非法字符跳过，填充可选（无填充是常态）。
fn b64url_decode_into(s: str, out: int) -> int
```

### `std/blake2b.qma`

BLAKE2b（RFC 7693）密码学哈希 + keyed / 变长输出

```quelmara
/// BLAKE2b 摘要缓冲区（outlen 字节，大端，含 0 字节不能当 str；用完 mem_free(d, outlen)）
fn blake2b_str(s: str, outlen: int) -> int
/// BLAKE2b-512 十六进制（128 位小写）
fn blake2b_hex(s: str) -> str
/// BLAKE2b 变长输出十六进制（outlen 1..64）
fn blake2b_hex_n(s: str, outlen: int) -> str
/// keyed BLAKE2b-512 十六进制（key ≤ 64 字节）
fn blake2b_keyed_hex(s: str, key: str) -> str
```

### `std/cli.qma`

命令行 flag 解析（--k=v / --k v / -k v）

```quelmara
/// 参数总数（程序名之后的全部参数，按 args() 原样计数）。
fn cli_count() -> int
/// 第 i 个原始参数；越界返回空串（不 assert）。
fn cli_at(i: int) -> str
/// cli_has(name) -> bool：flag 是否出现（三种写法都算）
fn cli_has(name: str) -> bool
/// cli_str(name, def) -> str：取字符串值
fn cli_str(name: str, def: str) -> str
/// cli_int(name, def) -> int：取整数值，解析失败回落默认值
fn cli_int(name: str, def: int) -> int
/// cli_positionals() -> vec[str]：位置参数（保持原顺序）
/// 判定规则：不以 '-' 开头，且**不是前一个 flag 的值**。
/// "前一个 flag 的值"的启发式：上一个参数以 '-' 开头且不含 '='（`--out x` 形态）；
/// 含 '=' 的形态（`--out=x`）自身就带值，不吃下一个参数。
/// 这个启发式覆盖常见 CLI；如果某个 flag 的值恰好以 '-' 开头，请用 --name=value 形态。
fn cli_positionals() -> vec[str]
```

### `std/cookie.qma`

Cookie 头解析与 Set-Cookie 生成（取值 / 百分号编解码 / Max-Age / SameSite / HttpOnly / Secure）

```quelmara
/// 按 RFC 6265 对 cookie 值做百分号编码：unreserved 字符原样，其余 %XX 大写十六进制。
/// 只编值，不编属性。
fn cookie_value_encode(s: str) -> str
/// 百分号解码；不含 '%' 时原样返回（不分配）。
fn cookie_value_decode(s: str) -> str
/// 从 Cookie 头里取 name 的值；不存在返回空串
fn cookie_get(header: str, name: str) -> str
/// Cookie 头里是否存在该名字（按 ';' 分段、去空白后精确比名，不看值）。
fn cookie_has(header: str, name: str) -> bool
/// 属性串：HttpOnly / Secure / SameSite（3 参，避开"第 7 个 str 参数"的 Lower 缺陷，
/// 见 07-gaps §7.8）
fn cookie_attrs(http_only: bool, secure: bool, same_site: str) -> str
/// 拼 Set-Cookie 值（不含 "Set-Cookie: " 前缀）
///   max_age <= 0 表示会话 cookie；值为空串时输出 Max-Age=0（删除的标准写法）
///   attrs 直接拼在末尾，通常来自 cookie_attrs(...)
fn cookie_set(name: str, value: str, path: str, max_age: int, attrs: str) -> str
```

### `std/core.qma`

标量小工具

```quelmara
// 本模块的顶层函数都未 pub 导出：可以 import，但用户代码引用会
// 编译失败（见 07-gaps.md §7.13）
```

### `std/crc64.qma`

CRC-64/XZ（ECMA-182 反射多项式，xz/zlib 容器的 64 位校验）

```quelmara
/// CRC-64/XZ 校验值（64 位；以补码整数返回，>2^63 时为负）
fn crc64(s: str) -> int
/// CRC-64/XZ 十六进制（16 位小写）
fn crc64_hex(s: str) -> str
```

### `std/csv.qma`

CSV 解析与生成（RFC 4180：引号包裹 / "" 转义 / 字段内换行 / CRLF 或 LF）

```quelmara
/// 把 CSV 文本解析成行×列的 vec[vec[str]]（RFC 4180：引号包裹、"" 转义、字段内换行、CRLF/LF）。
/// 末尾换行不会多出一行空记录。
fn csv_parse(text: str) -> vec[vec[str]]
/// 把行×列拼成 CSV 文本（CRLF 分行）；需要时自动加引号并把 " 转义成 ""。
fn csv_build(rows: vec[vec[str]]) -> str
/// 取第 i 列（越界返回空串）
fn csv_col(row: vec[str], i: int) -> str
/// 在第 col 列里找第一个等于 value 的行号（找不到返回 -1）
fn csv_find_row(rows: vec[vec[str]], col: int, value: str) -> int
```

### `std/deque.qma`

双端队列（两端 O(1) + 自动扩容）

```quelmara
/// dq_new(cap) -> int：cap 是最小初始容量（<4 按 4 算）
fn dq_new(cap: int) -> int
/// 当前元素个数（逻辑长度，不含空洞）。
fn dq_len(d: int) -> int
/// 当前容量（槽数，不是字节）；扩容后翻倍，dq_free 才归还。
fn dq_cap(d: int) -> int
/// 尾部入队；满则 2 倍扩容并重排（句柄不变，不需要 `d = ...` 回写）。
/// 恒返回 0（失败只可能是内存不足，直接崩）。
fn dq_push_back(d: int, v: int) -> int
/// 头部入队；满则扩容。只改 head，两端都是 O(1)。
/// 恒返回 0。
fn dq_push_front(d: int, v: int) -> int
/// 头部出队并返回该值；空队列返回 -1（先用 dq_len 判别）。
fn dq_pop_front(d: int) -> int
/// 尾部出队并返回该值；空队列返回 -1。
fn dq_pop_back(d: int) -> int
/// dq_peek_front / dq_peek_back：看但不弹（空返回 -1）
fn dq_peek_front(d: int) -> int
/// 看尾部元素但不弹出；空队列返回 -1。
fn dq_peek_back(d: int) -> int
/// 按逻辑下标 i（0 = 队头）取值；i<0 或 i>=len 返回 -1，不做 fail-fast。
fn dq_get(d: int, i: int) -> int
/// 按逻辑下标 i 赋值；越界返回 -1，成功返回 0。
fn dq_set(d: int, i: int, v: int) -> int
/// 清空（len 与 head 归零），**不释放内存**——容量留给下次复用。
fn dq_clear(d: int) -> int
/// dq_free(d)：释放状态块与句柄盒（句柄之后不可再用）
fn dq_free(d: int) -> int
```

### `std/ds.qma`

环形缓冲与二叉最小堆

```quelmara
/// rb_new(cap) -> int：建一个容量 cap 的环形缓冲，返回句柄（cap <= 0 按 1 算）。
/// 整个生命周期只在这里分配一次内存（24 + cap*8 字节）。
fn rb_new(cap: int) -> int
/// rb_count(rb) -> int：当前元素个数，O(1)。
fn rb_count(rb: int) -> int
/// rb_cap(rb) -> int：容量（建时定下，永不变化），O(1)。
fn rb_cap(rb: int) -> int
/// rb_push(rb, v) -> int：尾部入队。0 = 成功；-1 = 已满（**不覆盖最老的元素**）。
fn rb_push(rb: int, v: int) -> int
/// rb_pop(rb) -> int：头部出队。空返回 -1（先看 rb_count 才能与"值就是 -1"区分）。
fn rb_pop(rb: int) -> int
/// rb_peek(rb) -> int：看头部但不出队。空返回 -1。
fn rb_peek(rb: int) -> int
/// rb_clear(rb)：清空（count 与 head 归零），**不释放内存**——容量留给下次复用。
fn rb_clear(rb: int)
/// rb_free(rb)：释放整块内存（句柄之后不可再用；头与数据在同一块里，一次 mem_free 即可）。
/// 注意 `mem_free` 是**两参**（指针 + 字节数），字节数由 rb_cap 反算，调用方不用记。
fn rb_free(rb: int)
/// heap_new(cap) -> vec[int]：建堆，cap 是预分配槽数（只影响扩容次数，不影响语义）。
fn heap_new(cap: int) -> vec[int]
/// heap_len(h) -> int：堆内元素个数，O(1)。
fn heap_len(h: vec[int]) -> int
/// heap_push(h, key)：插入一个 key，O(log n)。
/// 挖洞上浮：key 先挂在末尾，父节点下移让位，最后一次性落到空位——
/// 每层只读一次父、写一次子（朴素写法是"读父读子 + 写父写子"四次）。
fn heap_push(h: vec[int], key: int)
/// heap_peek(h) -> int：最小 key（不出堆）。空返回 -1。
fn heap_peek(h: vec[int]) -> int
/// heap_pop(h) -> int：弹出最小 key，O(log n)。空返回 -1。
/// 同样是挖洞下沉：末元素先取出，逐层把较小孩子上提，最后一次性落位——
/// 每层 2 次读（左右孩子）+ 1 次写，且**先 pop 再下沉**，不需要临时把末元素写回根。
fn heap_pop(h: vec[int]) -> int
```

### `std/f64.qma`

十进制文本 ↔ f64（严格十进制解析 + Clinger 快路径，非十进制 fail-fast）

```quelmara
/// f64_parse(s) -> f64：十进制解析，非法输入直接 assert 失败（不返回 0）
fn f64_parse(s: str) -> f64
/// f64_finite(x) -> bool：不是 inf / nan（JSON 只能表示有限值）
/// 用 x*0.0 == 0.0 判定：inf*0 = nan、nan*0 = nan，两者都不等于 0.0
fn f64_finite(x: f64) -> bool
/// f64_repr(x) -> str：最短往返十进制文本（有限值；inf/nan 直接 assert 失败）
fn f64_repr(x: f64) -> str
```

### `std/fs.qma`

文件读写（open/read/write/seek/size/sync/close/rename；Windows PE，@ffi 直调 kernel32）

```quelmara
/// 打开文件，返回句柄；失败返回 -1。
/// `mode`：`"r"` 只读（必须存在）/ `"w"` 读写并截断 / `"a"` 读写并定位到末尾
/// （不存在则新建）。
fn fs_open(path: str, mode: str) -> int
/// 与 `fs_open` 同形，但**允许别人同时读**（`FILE_SHARE_READ|FILE_SHARE_WRITE`）。
/// 给"边写边 tail"的场景用（`std/logfile` 就是它）：独占打开的日志文件
/// 没法被 `tail -f` 或另一个进程读到刚写进去的内容。
/// 代价是并发写不设防——两个进程往同一个文件写会交错，要独占安全就用 `fs_open`。
fn fs_open_shared(path: str, mode: str) -> int
/// 关闭句柄：0 成功 / -1 失败。
fn fs_close(h: int) -> int
/// 从当前偏移读最多 `n` 字节，返回读到的内容。
/// EOF 或出错都返回空串（长度就是判断依据，没有单独的 errno）。
fn fs_read(h: int, n: int) -> str
/// 从当前偏移写入整个字符串，返回写入字节数；失败返回 -1。
fn fs_write(h: int, data: str) -> int
/// 定位到绝对偏移（从文件头算），返回 0 成功 / -1 失败。
fn fs_seek(h: int, off: int) -> int
/// 文件当前大小（字节）；失败返回 -1。
fn fs_size(h: int) -> int
/// 把内核缓冲刷到磁盘（FlushFileBuffers）：0 成功 / -1 失败。
/// 只对**可写**句柄有意义——只读句柄上 Win32 会拒绝（返回 -1）。
/// 不调用它时，进程崩溃数据仍在（WriteFile 已进内核），**掉电才会丢**。
fn fs_sync(h: int) -> int
/// 改名/覆盖目标文件（MoveFileEx + REPLACE_EXISTING）：0 成功 / -1 失败。
fn fs_rename(from: str, to: str) -> int
/// 整文件读入内存；文件不存在或读失败返回空串。
fn fs_read_all(path: str) -> str
/// 整文件覆盖写（截断后写入），0 成功 / -1 失败。
fn fs_write_all(path: str, data: str) -> int
```

### `std/gen.qma`

泛型算法库（min/max/clamp/dist/contains/index_of/reverse，调用点推导单态化）

```quelmara
// 本模块的顶层函数都未 pub 导出：可以 import，但用户代码引用会
// 编译失败（见 07-gaps.md §7.13）
```

### `std/gzip.qma`

DEFLATE 编码 + gzip 包装 + CRC-32；v1.19 起含 inflate 解码

```quelmara
/// CRC-32（IEEE 802.3，zlib 同款多项式），slice-by-4 表驱动，返回 32 位无符号值。
/// 表在首次调用时惰性构建（4 张 × 256 项）。
fn crc32(s: str) -> int
/// deflate_raw(s) -> str：裸 DEFLATE 流（无 gzip/zlib 头）
fn deflate_raw(s: str) -> str
/// deflate_raw + gzip 头尾（无 mtime、无文件名，尾 8 字节 = CRC32 + ISIZE）。
/// 输出确定性：同一输入逐字节相同（可当缓存键）。
fn gzip_encode(s: str) -> str
/// raw deflate（RFC 1951，无外层封装）
fn inflate_raw(s: str) -> str
/// gzip_decode(s) -> str：逐 member 解，结果按顺序拼接
fn gzip_decode(s: str) -> str
/// zlib 容器（RFC 1950）解压：跳过 2 字节头与 4 字节 Adler-32，中间是 deflate。
/// 头校验（CMF/FLG）、预置字典、窗口大小都在这里拦；数据过短直接 assert。
fn zlib_decode(s: str) -> str
```

### `std/hash.qma`

FNV-1a 32/64 非密码学哈希（缓存键 / 分片）

```quelmara
/// 按字节计算 FNV-1a 32 位（p=缓冲区指针，n=字节数）。
/// 非密码学哈希：1 字节 1 次乘加，适合缓存键 / 分片 / 布隆过滤器；
/// 结果恒在 [0, 2^32)，可直接当数组下标取模。
fn fnv1a32_bytes(p: int, n: int) -> int
/// 按字节计算 FNV-1a 64 位（p=缓冲区指针，n=字节数）。
/// 返回 int64 承载的**无符号**值——高位为 1 时结果为负，打印成十六进制
/// 请用 std/hex（hex_encode(mem_str(p, 8))）。
fn fnv1a64_bytes(p: int, n: int) -> int
/// 对 str 按 UTF-8 字节计算 FNV-1a 32 位（等价于对 mem_ptr/len 调
/// fnv1a32_bytes）。按字节计算，不做码点归一。
fn fnv1a32(s: str) -> int
/// 对 str 按 UTF-8 字节计算 FNV-1a 64 位（语义同 fnv1a64_bytes）。
fn fnv1a64(s: str) -> int
```

### `std/hex.qma`

十六进制编解码

```quelmara
/// 把字节串编码为小写十六进制（每字节 2 个字符，无前缀、无分隔）。
fn hex_encode(s: str) -> str
/// 同 hex_encode，输出大写 A-F。
fn hex_encode_upper(s: str) -> str
/// 校验是否为合法十六进制：长度偶数且每个字符都在 0-9a-fA-F 内。
/// 返回 1/0，不分配、不解码——先判再解可以避免 assert 失败。
fn hex_decode_ok(s: str) -> int
/// 把十六进制文本解码为字节串（大小写都认）。
/// 长度为奇数或含非法字符时 **assert 失败**，不返回空串。
fn hex_decode(s: str) -> str
```

### `std/http.qma`

HTTP/1.1 服务端（keep-alive / 流水线 / 压缩协商 / chunked 请求体 v2.95）

```quelmara
/// 阻塞运行 HTTP 服务：`backlog` 是监听队列长度，`on_request` 是
/// `fn(fd: int) -> int` 的裸函数名（返回 0 = 响应后关连接，1 = 按 keep-alive 继续）。
/// 十万连接档的槽位在启动时一次预分配（640 B/连接）。
fn http_serve(port: int, backlog: int, on_request: int) -> int
/// 可调连接上限版：槽位层按 `max_conns` 预分配定长槽位
/// （640 B/连接 × max_conns，十万连接 = 64 MB 常驻，无 GC、无停顿）。
/// 超过上限的新连接被直接拒绝（fail-fast，不静默膨胀）。
fn http_serve_max(port: int, backlog: int, on_request: int, max_conns: int) -> int
/// 累计 accept 的连接数
fn http_accepted() -> int
/// 累计关闭的连接数
fn http_closed() -> int
/// 累计派发给 handler 的请求数
fn http_reqs() -> int
/// 累计收到的字节数
fn http_bytes_in() -> int
/// 累计发出的字节数
fn http_bytes_out() -> int
/// 请求方法（"GET" / "POST" …）
fn http_method(fd: int) -> str
/// 请求目标原样（含 query 串；归一化请用 std.router 的 route_norm）
fn http_path(fd: int) -> str
/// `?` 之后的 query 串（到 `#` 或行尾为止；没有 query 返回 ""）
fn http_query(fd: int) -> str
/// 零拷贝体访问（大请求体：拿到指针直接读，不构造 str）
fn http_body_ptr(fd: int) -> int
/// 请求体长度。Content-Length 请求 = 头里声明的字节数；**chunked 请求
/// （v2.95）= 解包后的真实体长**（不含 hex 行/CRLF，ext 与 trailer 已丢弃）；
/// 无体为 0。
fn http_body_len(fd: int) -> int
/// 请求体（拷成一个 str；大请求体用 http_body_ptr + http_body_len）
fn http_body(fd: int) -> str
/// 按名找请求头（name 传小写；比较大小写无关）。没有返回 ""。
fn http_header(fd: int, name: str) -> str
/// 强制本连接在本次响应后关闭（不等对端 Connection 头）
fn http_set_close(fd: int) -> int
/// 状态码 → 原因短语（未收录的返回 "Unknown"）
fn http_reason(status: int) -> str
/// 标准响应：状态行 + Content-Type/Length + Connection + 体，一次组包一次 send。
/// `extra` 传 "" 表示没有附加头；要附加时每行自带 \r\n。
fn http_respond_ext(fd: int, status: int, ctype: str, extra: str, body: str) -> int
/// 标准响应（无附加头）
fn http_respond(fd: int, status: int, ctype: str, body: str) -> int
/// 响应后立即关闭（force close 不看对端头）
fn http_respond_close(fd: int, status: int, ctype: str, body: str) -> int
/// text/plain; charset=utf-8 响应
fn http_text(fd: int, status: int, body: str) -> int
/// text/html; charset=utf-8 响应
fn http_html(fd: int, status: int, body: str) -> int
/// application/json 响应
fn http_json(fd: int, status: int, body: str) -> int
/// 供库内解析失败路径用（此时槽位协议字未就绪，直接组包发送并关连接）
fn http_respond_raw(fd: int, status: int, extra: str, body: str) -> int
/// 客户端是否接受 gzip（看 Accept-Encoding）
fn http_accepts_gzip(fd: int) -> bool
/// 强制 gzip 响应（带 Content-Encoding 与 Vary）
fn http_respond_gzip(fd: int, status: int, ctype: str, body: str) -> int
/// 自动协商：客户端支持且体 ≥256 字节才压，否则原样发
fn http_respond_auto(fd: int, status: int, ctype: str, body: str) -> int
/// JSON + 自动 gzip 协商
fn http_json_auto(fd: int, status: int, body: str) -> int
/// HTML + 自动 gzip 协商
fn http_html_auto(fd: int, status: int, body: str) -> int
/// 404 响应（text/plain）
fn http_not_found(fd: int) -> int
/// 405 响应（text/plain）
fn http_method_not_allowed(fd: int) -> int
/// 清空路由表与中间件链（只清计数，不释放内存；测试与「重载配置」用）
fn http_routes_reset() -> int
/// 注册一条路由：`method` 传 "GET"/"POST"…，`"*"` 或 "" 表示任意方法；
/// `pattern` 见 std.router（`/users/:id`、尾部 `*`）；`handler` 是裸函数名。
/// 返回条目下标；表满返回 -1，方法/模板超长返回 -2（模板 ≤127 字节）。
fn http_route(method: str, pattern: str, handler: int) -> int
/// 注册一个中间件（`fn(fd: int) -> int`：1 = 继续，0 = 终止链路）。
/// 执行顺序 = 注册顺序；返回槽位下标，满返回 -1。
fn http_use(mw: int) -> int
/// 已注册路由条数
fn http_route_count() -> int
/// 已注册中间件条数
fn http_mw_count() -> int
/// 纯查询版路由匹配（不碰连接、不发送）：返回条目下标 / -1 未匹配 / -2 方法不符。
/// 用于单测与「先查再处理」的自定义派发。
fn http_route_index(method: str, path: str) -> int
/// 当前请求命中的第 `i` 个 `:参数`（从 0 起；不匹配/越界返回 ""）
fn http_param(fd: int, i: int) -> str
/// 当前请求命中的 `:参数` 个数（没命中返回 0）
fn http_param_count(fd: int) -> int
/// 内置派发器：中间件链 → 路由表 → handler；未命中回 404、方法不符回 405。
/// 当 `http_serve(port, backlog, http_dispatch)` 的 handler 用。
/// 永远返回 1（连接按 keep-alive 走），要关连接在 handler/中间件里调
/// http_set_close。
fn http_dispatch(fd: int) -> int
```

### `std/http_chunk.qma`

Transfer-Encoding: chunked 的扫描与就地解包（纯内存，零 socket 依赖；v2.95）

```quelmara
/// 扫描 [start, n) 的 chunked 流。返回：
///   >= 0  完整流的**原始结束偏移**（`0\r\n` + 空行/trailer 之后的位置）——
///         注意它不是"解包后的长度"；keep-alive 搬余包要按它截断。
///   -1    流还没收全（size 行截断 / 数据不足 / 终止行不完整），等下一段。
///   -2    病态流：非 hex 的 size、空 size 行、超过 8 位 hex、数据后缺 CRLF、
///         终止块后缺 \r\n\r\n —— 调用方应拒绝请求（std/http 回 400）。
fn chunk_scan(buf: int, start: int, n: int) -> int
/// 就地解包：把 [start, end) 的**完整合法** chunked 流（必须先用 chunk_scan
/// 验过、end 就是它返回的偏移）解包压到 [start, start+len)。返回解出的字节数。
/// trailer 与 chunk-ext 被丢弃；数据段里的 CRLF 序列按 size 原样保留。
/// 契约：end 不来自 chunk_scan 时行为未定义 —— 配对调用由调用方（std/http）保证。
fn chunk_pack(buf: int, start: int, end: int) -> int
```

### `std/httpc.qma`

HTTP/1.1 客户端核心：URL 拆分 / 请求构造 / 响应解析（content-length / chunked）/ 重定向判定（纯函数，零 socket 依赖）

```quelmara
/// 拆分 URL 为 scheme/host/port/path。无 scheme 前缀时按 http 处理。
fn httpc_split_url(u: str) -> HttpUrl
/// 构造完整请求字节（方法 + URL + 附加头 + 体）。hdrs 每行一条完整
/// "Name: Value"（自带 \r\n 由本函数补）。URL 非法返回 ""。
fn httpc_build_request(method: str, url: str, hdrs: vec[str], body: str) -> str
/// 失败响应（URL 非法 / 连接失败时由传输层返回）
fn httpc_bad_response() -> HttpResponse
/// 由传输层组装一条已解析的响应（v3.12）。
/// 为什么需要这个工厂：**限定 struct 字面量不做**（`02-language.md` §1），
/// 所以 `std/httpc_net` 没法写 `HttpResponse { ... }`。v3.12 起传输层不再
/// 每轮把整个缓冲区重新喂给 `httpc_parse_response`（那是 O(n²)），改成
/// "头块解析一次 + body 增量累积"，最后由这里按部件拼出结果。
/// `chunked` 由 `framing == 2` 决定，调用方不必重复判断。
fn httpc_make_response(status: int, reason: str, head: str, body: str, complete: int, chunked: int) -> HttpResponse
/// 解析完整响应字节。buf 可以只含部分响应（complete=0）；传输层应持续
/// 拼接后再次调用。头未收全（无 \r\n\r\n）返回 status=-1。
fn httpc_parse_response(buf: str) -> HttpResponse
/// 头块内按名取值（大小写不敏感；跳过 status line）。
/// v3.12 起公开：传输层 `std/httpc_net` 的接收循环要自己判 framing
/// （content-length / chunked），而它只拿到头块文本、拿不到 HttpResponse。
fn httpc_header_raw(head: str, name: str) -> str
/// 响应头取值（大小写不敏感；无此头返回 ""）
fn httpc_header(resp: HttpResponse, name: str) -> str
/// 重定向目标解析：3xx 且有 Location 返回目标 URL（绝对 Location 原样，
/// 绝对路径拼 base 的 scheme://host，相对路径简化拼接），否则返回 ""。
/// 只解析不跟随（跟随见 httpc_net.httpc_get_follow）。
fn httpc_redirect(resp: HttpResponse, base: str) -> str
```

### `std/httpc_net.qma`

HTTP 客户端传输层：httpc_get / httpc_get_tls / httpc_get_follow（Windows；TLS 走 std/tls_net）

```quelmara
/// 明文 HTTP GET（Windows）。http:// 走 TCP；https:// 转 httpc_get_tls。
fn httpc_get(url: str) -> HttpResponse
/// HTTPS GET（Windows，TLS 1.3）。seq 从 0 起逐条 +1。
fn httpc_get_tls(url: str) -> HttpResponse
/// 跟随重定向的 GET：最多 max_hops 跳（超出返回最后一个 3xx 响应）。
fn httpc_get_follow(url: str, max_hops: int) -> HttpResponse
```

### `std/httpdate.qma`

HTTP 日期（RFC 7231 IMF-fixdate）格式化与解析 + If-Modified-Since 判定

```quelmara
/// UTC 秒 -> "Sun, 06 Nov 1994 08:49:37 GMT"
fn httpdate_format(epoch: int) -> str
/// "Sun, 06 Nov 1994 08:49:37 GMT" -> UTC 秒；格式不对返回 -1
fn httpdate_parse(s: str) -> int
/// 资源 mtime <= 客户端持有的时间 -> 可以回 304
fn httpdate_not_modified(mtime: int, since: str) -> bool
```

### `std/json.qma`

DOM 式 JSON 解析与 builder

```quelmara
/// json_parse(s) -> doc 句柄。失败时 json_ok(doc) == false。
/// 句柄不自动回收（一个文档一个块）；长驻进程请 mem_free(doc, 72) 并在
/// 之前释放 pool/buf/kids（当前不提供 json_free，见 docs/GAPS.md）。
fn json_parse(s: str) -> int
/// 解析是否成功：err==0 且 root>=0；d==0 也返回 false。
fn json_ok(d: int) -> bool
/// 错误位置（1-based 字节偏移；0 = 无错）
fn json_error_pos(d: int) -> int
/// 根节点索引；解析失败返回 -1。
fn json_root(d: int) -> int
/// 节点是否为 null。
fn json_is_null(d: int, node: int) -> bool
/// 节点是否为数组（tag=4）。
fn json_is_arr(d: int, node: int) -> bool
/// 节点是否为对象（tag=5）。
fn json_is_obj(d: int, node: int) -> bool
/// 取布尔值；节点不是 bool 时返回 false（不报错）。
fn json_bool(d: int, node: int) -> bool
/// 整数部分：取小数点/指数之前的文本（"−2.75e2" -> -2），不四舍五入。
/// 实现上走 str 工具而不是自己扫 vec：v1.5 实测"局部量跨调用后读错槽位"
/// 的 codegen 问题会把这种循环算错（见 docs/GAPS.md 已知问题）。
fn json_int(d: int, node: int) -> int
/// 原始数字文本（保留小数/指数，便于上层自己转 float）
fn json_num_raw(d: int, node: int) -> str
/// 取字符串值；节点不是 str 时返回空串。
/// 返回值是 buf 的零拷贝切片——doc 句柄释放后失效。
fn json_str(d: int, node: int) -> str
/// 数组元素个数；节点不是数组时返回 0。
fn json_arr_len(d: int, node: int) -> int
/// 第 i 个元素的节点索引；i 越界或节点不是数组返回 -1。
fn json_arr_at(d: int, node: int, i: int) -> int
/// 对象键个数；节点不是对象时返回 0。
fn json_obj_len(d: int, node: int) -> int
/// 第 i 个键名；越界或不是对象返回空串（内部走 json_str，节点为 -1 时即空串）。
fn json_obj_key(d: int, node: int, i: int) -> str
/// 按 key 取子节点（不存在返回 -1）
fn json_obj_get(d: int, node: int, key: str) -> int
/// 建序列化 builder，cap 是输出缓冲的初始容量（字节，可增长）。
/// 配对用法：json_begin_obj → json_key_* → json_end_obj → json_done。
fn json_new(cap: int) -> int
/// 开一个对象（先按值位置补逗号，再写 `{` 并入栈）；恒返回 0。
fn json_begin_obj(h: int) -> int
/// 关对象：弹栈并写 `}`；栈空时只写 `}`（不报错）。
fn json_end_obj(h: int) -> int
/// 开一个数组（补逗号 + `[` + 入栈）；恒返回 0。
fn json_begin_arr(h: int) -> int
/// 关数组：弹栈并写 `]`。
fn json_end_arr(h: int) -> int
/// key：写 "key":（逗号在此处决定）
fn json_key(h: int, k: str) -> int
/// 追加一个字符串值（自动加引号并转义 `"` `\\` 与控制字符）。
fn json_val_str(h: int, v: str) -> int
/// 追加一个整数值（to_str 后原样写入，不加引号）。
fn json_val_int(h: int, v: int) -> int
/// 追加 true / false。
fn json_val_bool(h: int, v: bool) -> int
/// 追加 null。
fn json_val_null(h: int) -> int
/// 原样插入（调用方保证是合法 JSON 片段；解析出的 num_raw 可用它回写）
/// v1.96：改为 pub——@derive(Json) 的 f64 字段要用它写 f64_repr 的结果
fn json_val_raw(h: int, raw: str) -> int
/// 写一个键值对，值是一段**原样的合法 JSON 片段**（`"k": raw`）；f64 字段走这里。
/// 调用方负责保证 raw 合法（`json_num_raw` 取出的数字可以直接回写）。
fn json_key_raw(h: int, k: str, raw: str) -> int
/// 写一个键值对（字符串值），等价于 json_key + json_val_str。
fn json_key_str(h: int, k: str, v: str) -> int
/// 写一个键值对（整数值）。
fn json_key_int(h: int, k: str, v: int) -> int
/// 写一个键值对（布尔值）。
fn json_key_bool(h: int, k: str, v: bool) -> int
/// 收尾并返回拼好的 JSON 文本。
/// **不校验括号配平**：begin/end 不配对时原样输出半截 JSON，由调用方负责对称。
fn json_done(h: int) -> str
```

### `std/kv.qma`

持久化键值存储（追加日志 + 内存索引；重开重放 / 撕裂尾恢复 / 压缩；Windows PE）

```quelmara
/// 打开（不存在则新建）一个库，返回句柄；失败时 `kv_ok(db) == 0`。
/// 打开时重放整份日志重建索引，并把写位置定位到最后一条完好记录之后。
fn kv_open(path: str) -> Kv
/// 句柄是否可用：1 / 0（`kv_open` 失败、或已经 `kv_close`）。
fn kv_ok(db: Kv) -> int
/// 写入一个键（覆盖旧值）：0 成功 / -1 失败。空键被拒绝。
/// 记录先进缓冲，满 `_BATCH` 条才落盘；要立刻可见于磁盘用 `kv_sync`。
fn kv_put(db: Kv, key: str, val: str) -> int
/// 读一个键；不存在（或已删除）返回空串。用 `kv_has` 区分"空值"与"没有"。
fn kv_get(db: Kv, key: str) -> str
/// 键是否存在：1 / 0。
fn kv_has(db: Kv, key: str) -> int
/// 删除一个键（追加墓碑）：0 成功 / -1 失败。删不存在的键也算成功。
fn kv_del(db: Kv, key: str) -> int
/// 当前键数量（不含已删除的）。
fn kv_len(db: Kv) -> int
/// 刷盘（先冲刷缓冲，再 FlushFileBuffers）：0 成功 / -1 失败。掉电安全需要它。
fn kv_sync(db: Kv) -> int
/// 压缩：把活记录重写进 `<path>.tmp` 后原子改名。
/// 返回 `[压缩前字节数, 压缩后字节数]`；失败返回空 vec。压缩后句柄仍可用。
fn kv_compact(db: Kv) -> vec[int]
/// 关闭：先刷盘再关句柄，并清空内存索引。
/// 关闭后 `kv_ok(db)` 为 0，其余接口一律 -1 / 空串 / 0——**不留"还能读但写不进去"
/// 的半死状态**（那会让人误以为数据还在库里）。
fn kv_close(db: Kv) -> int
/// 文件当前字节数（观察日志膨胀 / 压缩效果），失败 -1。
/// **含未落盘的缓冲**——报的是"逻辑日志大小"，不是磁盘上已有的字节。
fn kv_file_size(db: Kv) -> int
```

### `std/log.qma`

日志核心（级别过滤 / 绝对时间戳 / stdout·stderr 双通道 / 结构化字段）

```quelmara
/// 级别阈值：0=全部 1=只 warn/error 2=只 error 3=静默。返回设置后的值。
fn log_set_level(lv: int) -> int
/// 当前级别阈值（0=全开 1=只 warn/error 2=只 error 3=静默）。
fn log_level() -> int
/// 这条级别的日志会不会被输出（`lv`：0=info 1=warn 2=error）。
/// 调用方要拼昂贵的载荷（JSON、hexdump）时先问一句，省掉无用的分配。
fn log_enabled(lv: int) -> bool
/// 输出通道：0=stdout（默认）1=stderr；其他值按 stdout 处理。返回设置后的值。
fn log_set_sink(kind: int) -> int
/// 当前输出通道（0=stdout 1=stderr）。
fn log_sink() -> int
/// 时间戳模式：0=绝对（默认）1=相对启动毫秒。返回设置后的值。
fn log_set_time_mode(m: int) -> int
/// 当前时间戳模式（0=绝对 1=相对）。
fn log_time_mode() -> int
/// 时区偏移（分钟，东八区 = 480；默认 0 = UTC）。只影响**显示**，不改变时刻。
fn log_set_tz_offset(min: int) -> int
/// 当前时区偏移（分钟）。
fn log_tz_offset() -> int
/// 拼一行 `[tag] 时间戳 消息`（不含换行）。时间戳形态由 `log_set_time_mode` 决定。
/// 需要自己决定去向（文件 / 网络 / 测试断言）时用它，再用 `log_emit` 输出。
fn log_format(tag: str, msg: str) -> str
/// 在 `log_format` 的行尾追加 `k=v` 字段（`kv` 是交替的 key/value 串）。
fn log_format_kv(tag: str, msg: str, kv: vec[str]) -> str
/// 把一行写到当前通道（stdout / stderr）。**不加换行**——换行由 print/eprint 补。
/// 写操作在进程级锁内，多线程同时写不会让两行交错。
fn log_emit(line: str)
/// 写一行 `[INFO] 时间戳 消息`；级别 >=1 时直接返回（不格式化、不分配）。
fn log_info(msg: str)
/// 写一行 `[WARN] 时间戳 消息`；级别 >=2 时跳过。
fn log_warn(msg: str)
/// 写一行 `[ERROR] 时间戳 消息`；级别 >=3（静默）时跳过。
fn log_error(msg: str)
/// 带结构化字段的 INFO 行：`[tag] 时间戳 消息 k1=v1 k2=v2`。
/// `kv` 是**交替**的 key/value 串；值非 str 时调用方先 `to_str()`。
fn log_kv(tag: str, msg: str, kv: vec[str]) -> int
/// 指定级别的结构化行（`lv`：0=info 1=warn 2=error），级别不够时整行跳过。
fn log_kv_lv(lv: int, tag: str, msg: str, kv: vec[str]) -> int
```

### `std/logfile.qma`

日志文件通道 + 按大小轮转（攒批写 + 共享打开可 tail；Windows PE）

```quelmara
/// 打开（或续写）`path`，并设定轮转策略：`max_bytes <= 0` 不轮转，
/// `keep` 是保留的备份份数（`.1` … `.keep`）。成功返回 0，失败返回 -1
/// （失败后 `logf_active()` 为 false，写日志是空操作）。
fn logf_open(path: str, max_bytes: int, keep: int) -> int
/// 冲刷缓冲（一次 WriteFile）。0 成功 / -1 失败。
fn logf_flush() -> int
/// 冲刷并关闭。0 成功 / -1 失败（缓冲写不进去时返回 -1，但句柄照样关）。
fn logf_close() -> int
/// 当前是否有一个可用通道（打开成功且没关）。
fn logf_active() -> bool
/// 当前文件的逻辑字节数（已落盘 + 缓冲里还没写的）。
fn logf_size() -> int
/// 累计轮转次数（跨多次打开累计，便于测试与监控断言）。
fn logf_rotations() -> int
/// 同时往 `std/log` 的通道（stdout/stderr）打一份：1 开 / 0 关。
fn logf_tee(on: int) -> int
/// 写一行（不加级别前缀，`tag` 由调用方给）。0 成功 / -1 失败。
fn logf_line(tag: str, msg: str) -> int
/// INFO 行；级别 >=1 时跳过。
fn logf_info(msg: str)
/// WARN 行；级别 >=2 时跳过。
fn logf_warn(msg: str)
/// ERROR 行；级别 >=3（静默）时跳过。
fn logf_error(msg: str)
/// 带结构化字段的 INFO 行（`kv` 是交替的 key/value 串）。0 成功 / -1 失败。
fn logf_kv(tag: str, msg: str, kv: vec[str]) -> int
```

### `std/lru.qma`

LRU 缓存（开放寻址表 + 双向链表，单句柄 O(1)）

```quelmara
/// lru_new(cap) -> vec[int]：建缓存，cap 是**最大条目数**（<2 按 2 算）
fn lru_new(cap: int) -> vec[int]
/// 容量上限（建表时给定，不扩容；满了淘汰 LRU）。
fn lru_cap(st: vec[int]) -> int
/// 当前条目数（O(1)，存在状态表头部）。
fn lru_len(st: vec[int]) -> int
/// 键是否在缓存里；**不刷新** LRU 顺序（要刷新用 lru_get）。
fn lru_has(st: vec[int], k: int) -> bool
/// lru_get(st, k) -> int：命中返回并刷新为 MRU；未命中 -1（值域有歧义，见文件头）
fn lru_get(st: vec[int], k: int) -> int
/// lru_get_or(st, k, def) -> int：命中返回值，未命中返回 def（不插入）
fn lru_get_or(st: vec[int], k: int, def: int) -> int
/// lru_put(st, k, v) -> int：写入并置为 MRU；满了淘汰 tail。返回 1=新增 / 0=更新
fn lru_put(st: vec[int], k: int, v: int) -> int
/// lru_del(st, k) -> int：1=删掉了 / 0=本来没有
fn lru_del(st: vec[int], k: int) -> int
/// lru_order(st) -> vec[int]：按 MRU -> LRU 顺序导出 key（测试与观测用）
fn lru_order(st: vec[int]) -> vec[int]
/// lru_peek(st, k) -> int：取值但**不**刷新使用顺序（观测/调试用）
fn lru_peek(st: vec[int], k: int) -> int
```

### `std/math.qma`

浮点与整数数学（exp/log/pow/sin/cos/atan/双曲/hypot + sqrt/cbrt/取整/gcd）

```quelmara
/// 绝对值；NaN 仍是 NaN，-0.0 原样返回（不是 +0.0）。
fn fabs(x: f64) -> f64
/// 符号：x>0 返回 1，x<0 返回 -1，0 与 NaN 返回 0。
fn fsign(x: f64) -> int
/// NaN 判定（用 x != x），返回 1/0——不是 bool，配合 C 风格判断用。
fn is_nan(x: f64) -> int
/// inf 的特征：x-x 不是 0（NaN 也满足），但 x==x 排除 NaN
fn is_inf(x: f64) -> int
/// 有限值判定：既不是 NaN 也不是 ±inf 时返回 1。
fn is_finite(x: f64) -> int
/// 朝零截断（to_int 再转回 f64），-2.7 → -2.0。
/// 超出 int64 范围的值未定义（先溢出再回转）。
fn trunc_f(x: f64) -> f64
/// 向下取整，-2.5 → -3.0；实现是 to_int 后按方向修正，超 int64 范围未定义。
fn floor(x: f64) -> f64
/// 向上取整，-2.5 → -2.0；超 int64 范围未定义。
fn ceil(x: f64) -> f64
/// 四舍五入（.5 向上）
fn round(x: f64) -> f64
/// 整数幂（快速幂）；n 可为负
fn powi(x: f64, n: int) -> f64
/// 平方根：先把 y 缩放到 [1,4)，牛顿迭代 8 轮，再乘回 2^k
fn sqrt(x: f64) -> f64
/// 立方根（牛顿：r = (2r + x/r²)/3）
fn cbrt(x: f64) -> f64
/// 两个 int 取小（相等返回 a）。
fn imin(a: int, b: int) -> int
/// 两个 int 取大（相等返回 a）。
fn imax(a: int, b: int) -> int
/// 把 x 钳到 [lo, hi]；先判下界再判上界，所以 lo>hi 时结果取 lo。
fn clamp_int(x: int, lo: int, hi: int) -> int
/// 把 f64 钳到 [lo, hi]；顺序同 clamp_int（lo>hi 时返回 lo）。
fn clamp_f(x: f64, lo: f64, hi: f64) -> f64
/// 整数平方根（牛顿，向下取整）
fn isqrt(n: int) -> int
/// 最大公约数 / 最小公倍数
fn gcd(a: int, b: int) -> int
/// 最小公倍数（取绝对值），任一参数为 0 返回 0。
/// 按 a/g*b 计算，乘积超 int64 会回绕——大数请先判范围。
fn lcm(a: int, b: int) -> int
/// π（3.141592653589793）
fn pi() -> f64
/// e（2.718281828459045）
fn e() -> f64
/// ln2（0.6931471805599453）
fn ln2() -> f64
/// ln10（2.302585092994046）
fn ln10() -> f64
/// √2（1.4142135623730951）
fn sqrt2() -> f64
/// 安静 NaN（0/0）
fn nan() -> f64
/// +∞（1/0）
fn inf() -> f64
/// 自然指数 e^x。x > 710 → +∞；x < −745.2 → 0（双精度边界）
fn exp(x: f64) -> f64
/// 自然对数 ln(x)。x < 0 → NaN；x = 0 → −∞；x = +∞ → +∞
fn log(x: f64) -> f64
/// 以 2 为底的对数
fn log2(x: f64) -> f64
/// 以 10 为底的对数
fn log10(x: f64) -> f64
/// x^y。整数指数走精确快速幂（含负底奇次幂）；x < 0 且 y 非整数 → NaN
/// （C 库约定）；pow(0, 0) = 1；pow(0, 负) = +∞
fn pow(x: f64, y: f64) -> f64
/// 正弦。|x| ≥ 2^52 断言失败（ULP 超过 π/2，无法定相）
fn sin(x: f64) -> f64
/// 余弦。|x| ≥ 2^52 断言失败（同 sin）
fn cos(x: f64) -> f64
/// 正切（sin/cos 商；cos 接近 0 时给出大数，与 C 库一致）
fn tan(x: f64) -> f64
/// 反正切（弧度，(-π/2, π/2)）
fn atan(x: f64) -> f64
/// 二参数反正切（弧度，(-π, π]；按 C 库约定处理 0 与 ∞ 组合）
fn atan2(y: f64, x: f64) -> f64
/// 反正弦（[-1, 1] 外 → NaN；±1 → ±π/2）
fn asin(x: f64) -> f64
/// 反余弦（[-1, 1] 外 → NaN）
fn acos(x: f64) -> f64
/// 双曲正弦。|x| > 20 走 exp(x−ln2)，避开 e^x 中间溢出
fn sinh(x: f64) -> f64
/// 双曲余弦
fn cosh(x: f64) -> f64
/// 双曲正切。|x| > 20 给 ±1，避开 inf/inf
fn tanh(x: f64) -> f64
/// 欧几里得范数 √(x²+y²)（先按 max 归一，防中间溢出/枯竭）
fn hypot(x: f64, y: f64) -> f64
/// 角度 → 弧度（乘 π/180）
fn to_radians(deg: f64) -> f64
/// 弧度 → 角度（乘 180/π）
fn to_degrees(rad: f64) -> f64
```

### `std/md5.qma`

MD5（RFC 1321，仅兼容用途，不要用于密码）

```quelmara
/// **不要**用于密码或抗碰撞场合（见模块头的定位纪律）；仅兼容旧接口 / ETag / 校验和。
/// 对 str 的 UTF-8 字节算 MD5，返回 32 位小写十六进制。
fn md5_hex(s: str) -> str
```

### `std/mem.qma`

slab 分配 / fd 表 / 缓冲 / 对象池

```quelmara
/// 建固定槽位分配器：cap 个槽、每槽 slot_words 字，返回 4 字句柄 {data,cap,slot_words,free_head}。
/// 一次大块分配 + 空闲链，槽位首字被链占用，**业务数据从第 1 字起用**。
fn slab_new(cap: int, slot_words: int) -> int
/// 取一个空闲槽，返回槽下标；槽用尽返回 -1。返回前把整槽 mem_zero（不残留上一次的数据）。
fn slab_alloc(h: int) -> int
/// 归还槽位（头插自由链）；idx<0 返回 -1。不校验重复归还——同一 idx 还两次会让链成环。
fn slab_free(h: int, idx: int) -> int
/// 槽位首字的字节地址（业务数据从 +8 起）。调用方自己按槽内布局读写。
fn slab_ptr(h: int, idx: int) -> int
/// 槽位总数（建表时给定，不扩容）。
fn slab_cap(h: int) -> int
/// 建 fd → 槽位表（开放寻址 + 线性探测，2 字/项），返回 4 字句柄。
/// **cap 必须是 2 的幂**（用 &(cap-1) 代替取模），负载因子到 50% 就该扩容。
fn fdtab_new(cap: int) -> int
/// 插入或更新 fd 对应的槽位；表满（探测一圈没空位）返回 -1，调用方负责扩容。
fn fdtab_put(h: int, fd: int, slot: int) -> int
/// 查 fd 对应的槽位；不存在返回 -1。
fn fdtab_get(h: int, fd: int) -> int
/// 删除用「后移填洞」：命中后把后续探测链上仍可前移的项前移，
/// 避免墓碑堆积（开放寻址 + 无墓碑 = 查找链不断裂）。
fn fdtab_del(h: int, fd: int) -> int
/// 当前项数（O(1)，存在句柄第 3 字）。
fn fdtab_len(h: int) -> int
/// 建定长字节缓冲区，句柄 3 字 {ptr,cap,len}；容量固定，**不自动扩容**。
fn buf_new(cap: int) -> int
/// 已写入的字节数（读游标与写游标是同一个）。
fn buf_len(h: int) -> int
/// 把 str 的字节追加到缓冲末尾；剩余空间不足返回 -1（不截断、不扩容）。
fn buf_put_str(h: int, s: str) -> int
/// 把已写入部分包成 str（mem_str，零拷贝：与缓冲区共享内存，缓冲释放后失效）。
fn buf_str(h: int) -> str
/// 在 [from, len) 里找 needle 的首个出现位置；找不到返回 -1
fn buf_find(h: int, from: int, needle: str) -> int
/// 找 "\r\n\r\n"（HTTP 头结束）—— 按 4 字节滑窗，避免逐字节 substr 分配
fn buf_find_head_end(h: int) -> int
/// 在 [from, len) 里做**大小写不敏感**（仅 ASCII）查找，返回起点；找不到 -1。
/// 用于 HTTP 头名 / WebSocket 头这类大小写不固定的场景。
fn buf_find_ci(h: int, from: int, needle: str) -> int
/// 建定长块池：capacity 块 × block_words 字，返回 3 字句柄。
/// 适用高频 alloc/free 的同尺寸对象（连接、消息帧）；块首 8 字节存 freelist 的 next。
fn pool_new(block_words: int, capacity: int) -> int
/// 取一块，返回块地址；池空返回 **0**（不是 -1）——调用方判 0 后扩容或降级。
fn pool_alloc(h: int) -> int
/// 把块头插回 freelist；p 必须来自本池。
/// **不查 double-free**：还两次会让 freelist 成环，后续 alloc 会重复发同一块。
fn pool_free(h: int, p: int) -> int
/// freelist 是否为空（= 池里没有可用块）。
fn pool_empty(h: int) -> bool
```

### `std/mime.qma`

扩展名 ↔ Content-Type（内置 30 项表，大小写不敏感，带 charset 参数反查）

```quelmara
/// 路径 -> 扩展名（不含点，小写）；没有扩展名返回空串
fn mime_ext_of(path: str) -> str
/// 按扩展名查 Content-Type（带 charset 参数，如 text/html; charset=utf-8）。
/// 认不出返回 application/octet-stream；扩展名取最后一个点之后、大小写不敏感。
fn mime_of(path: str) -> str
/// Content-Type -> 扩展名（不带点）；认不出返回空串
fn mime_ext(ctype: str) -> str
/// 是否"人可读"的类型（决定要不要加 charset / 能不能按文本压缩）
fn mime_is_text(ctype: str) -> bool
```

### `std/multipart.qma`

multipart/form-data 解析（boundary 提取 / 表单字段与文件部分 / 头字段大小写不敏感）

```quelmara
/// 从 Content-Type 头里取 boundary（去引号）
fn multipart_boundary(ctype: str) -> str
/// 按 boundary 把 multipart/form-data 正文切成 Part 列表（字段与文件都在里面，按 name 取）。
/// boundary 为空或正文不含分隔符时返回空 vec。
fn multipart_parse(body: str, boundary: str) -> vec[Part]
/// 取某个表单字段的值（同名取第一个）；没有返回空串
fn multipart_field(body: str, boundary: str, name: str) -> str
/// 取上传文件的正文（按 name 找带 filename 的 part）；没有返回空串
fn multipart_file(body: str, boundary: str, name: str) -> str
```

### `std/net.qma`

阻塞 TCP 便捷层

```quelmara
/// 在 port 上建监听 socket（tcp_listen 内建），返回监听 fd；失败直接 fail-fast。
/// 只接 IPv4（绑 0.0.0.0）；要双栈用 listen6。
fn listen(port: int) -> int
/// 在 port 上建 **IPv6 双栈**监听（tcp_listen6 内建，AF_INET6 + IPV6_V6ONLY=0），
/// 返回监听 fd；同一个 socket 同时接 IPv6 与 IPv4（映射成 ::ffff:a.b.c.d）连接。
/// 失败直接 fail-fast（与 listen 同口径）。仅 Windows PE。
fn listen6(port: int) -> int
/// 阻塞接受一个连接，返回连接 fd。
fn accept(fd: int) -> int
/// 客户端连接（v1.25 / v2.07）：host 可以是域名、IPv4 字面量或 IPv6 字面量
/// （"::1"，不带方括号）。Windows 走系统 DNS（getaddrinfo + hosts）并按返回的
/// 地址家族逐个尝试；Linux 暂未实现（编译期报错）。失败 fail-fast。
fn connect(host: str, port: int) -> int
/// 把 str 的全部字节写到连接上，返回写入字节数（短写要自己续写）。
fn send(conn: int, data: str) -> int
/// 把 `data` **全部**写出，返回实际写出的字节数（v3.07）。
/// 为什么需要它：`send(conn, data)` 是**一次** `send()` 系统调用，返回值是
/// "这次写进去多少"，**可能小于 `len(data)`**（短写）。短写不是错误，是 TCP
/// 的正常行为：内核发送缓冲区快满时只接受一部分；大块数据（> 64 KB）几乎
/// 一定分多次。拿 `send` 当"发完了"用，会在高吞吐或大包场景丢尾巴。
/// **实现：零拷贝指针推进**。第一版用 `substr(data, sent, ...)` 切尾巴，
/// 每轮把剩余数据**复制一遍** —— 4 MB 负载直接 O(n²)、堆爆 512 MB 上限
/// （实测 `heap_limit_mb exceeded`）。现在改用 `tcp_send_n(fd, ptr+off, n)`：
/// 裸指针 + 长度，不构造新 str、不扫 strlen。`str_ptr` 取数据指针是零成本的
/// （str 的值本身就是数据指针，长度在 ptr-8）。
/// **返回值语义**：成功返回 `len(data)`；中途出错返回已写出的字节数。
/// 调用方用 `== len(data)` 判断是否发全。
/// 边界：无超时（`tcp_send_n` 阻塞）；对端一直不收且缓冲区满时会一直等
/// ——要超时用 `send_all_to`。
fn send_all(conn: int, data: str) -> int
/// 把 `data` 全部写出，**每次发送**最多等 `ms` 毫秒（v3.10）。
/// 与 `send_all` 的唯一区别：对端不读、内核发送缓冲区满时，不会永久阻塞，
/// 而是等 `ms` 毫秒后停下并返回**已写出的字节数**。
/// 调用方用 `== len(data)` 判断是否发全：短了就是"对端吃不下"，通常意味着
/// 该断开（慢消费者）或重试（瞬时拥塞），这是调用方的策略，不是库的。
/// 超时粒度是**每次 `send()`**，不是整段总时长——一个持续被读的对端可以让
/// 这个循环跑任意久（这正是想要的：大文件传输不该被总时长砍断）。
/// 边界：`ms = 0` 是**不限时**（等到底，等价于 `send_all`），不是非阻塞。
fn send_all_to(conn: int, data: str, ms: int) -> int
/// 单次发送（可能短写），带 `ms` 毫秒超时；超时返回 0（v3.10）。
/// 与 `send` 的关系同 `tcp_send_to` 与 `tcp_send`：`send` 是阻塞单次写，
/// 这里是"最多等 ms 毫秒的一次写"。要"发全"用 `send_all_to`。
fn send_to(conn: int, data: str, ms: int) -> int
/// 从连接读最多 cap 字节并返回 str；对端关闭时返回空串。
fn recv(conn: int, cap: int) -> str
/// 读到**对端关闭**为止，返回全部字节（v3.06，v3.09 起 O(n)）。
/// `chunk` 是每次 `tcp_recv` 的上限（建议 4096–65536）。为什么需要它：
/// `recv(conn, cap)` 是**单次** `recv()`，内核缓冲区里有多少就返回多少，
/// 可能远少于 `cap`——拿它当"读完"用，在慢链路或大数据包上会截断。
/// 这里循环读到返回空串（对端 FIN）为止。
/// **v3.09 起累积走缓冲区**（`_recv_buf`），不再每轮 `out = out + part`
/// 复制全部已读数据：4 MB / 4 KB 分块从堆爆变成一次通过，总拷贝量 O(n)。
/// 边界：**没有总长度上限**——对端一直发就会一直读，要上限用 `recv_all_max`；
/// **没有超时**——对端半开时永久阻塞，要超时用 `recv_all_to`。
fn recv_all(conn: int, chunk: int) -> str
/// 读到对端关闭，但最多读 `maxbytes` 字节（v3.06，v3.09 起 O(n)）。
/// 与 `recv_all` 的区别：**有上限**，到上限就返回，不会因为对端一直发而
/// 无限增长内存。适合"读 HTTP 响应体但有 Content-Length 上限"这类场景。
fn recv_all_max(conn: int, chunk: int, maxbytes: int) -> str
/// 精确读 `n` 字节；对端提前关闭时返回**已读到的部分**（v3.06，v3.09 起 O(n)）。
/// 这是 HTTP/1.1 的 `Content-Length` 与 TLS 记录层都要的语义：
/// "我知道正好要 n 字节，给我读满"。用 `len(result) == n` 判断是否读满。
fn recv_exact(conn: int, n: int, chunk: int) -> str
/// 读到对端关闭**或超时**，返回已读到的全部（v3.08，v3.09 起 O(n)）。
/// 与 `recv_all` 的唯一区别是每次 `tcp_recv_to` 都有 `ms` 毫秒超时：超时后
/// 把它当作"对端不再发"，**立即停止**并返回已读到的部分（可能为空串）。
/// 返回值语义与 `recv_exact` 的短读一致：调用方用 `len(result) == n` 判断
/// 是否读满，不要假定"返回了就是收全了"。超时粒度是**每次接收**，不是总时长。
fn recv_all_to(conn: int, chunk: int, ms: int) -> str
/// 读到关闭或超时，最多 `maxbytes` 字节（v3.08，v3.09 起 O(n)）。
fn recv_all_max_to(conn: int, chunk: int, maxbytes: int, ms: int) -> str
/// 精确读 `n` 字节，超时即停并返回已读到的部分（v3.08，v3.09 起 O(n)）。
fn recv_exact_to(conn: int, n: int, chunk: int, ms: int) -> str
/// 关闭连接 fd（不返回值）。
fn close_conn(fd: int)
```

### `std/net/addr.qma`

地址文本层：IPv4/IPv6 字面量解析与 RFC 5952 格式化 + fd 对端地址

```quelmara
/// ip_family(s) -> int：字面量家族判定。4 = 点分 IPv4，6 = IPv6，0 = 不是字面量。
/// 只看字面量不做解析：域名（含 "localhost"）一律 0，那是 tcp_connect 的活。
fn ip_family(s: str) -> int
/// ip6_parse(s) -> str：IPv6 字面量 -> 16 字节网络序原始串；非法返回空串。
/// 支持 "::" 压缩（最多一处）与末尾点分四段（::ffff:1.2.3.4）。
fn ip6_parse(s: str) -> str
/// strip_brackets(host) -> str：URL 的 IPv6 host 是 "[::1]" 形态，去掉方括号；
/// 没有方括号原样返回（IPv4 / 域名不受影响）。
fn strip_brackets(host: str) -> str
/// ip4_format(b) -> str：4 字节网络序 -> 点分四段。
fn ip4_format(b: str) -> str
/// ip6_format(b) -> str：16 字节网络序 -> RFC 5952 文本
/// （小写、无前导零、最长连续 0 段压成 "::"，等长取最左）。
fn ip6_format(b: str) -> str
/// addr_family(raw) -> int：2 = IPv4，23 = IPv6，0 = 未知（fd 已关闭）。
fn addr_family(raw: str) -> int
/// addr_port(raw) -> int：对端端口（主机序）；raw 不合法返回 -1。
fn addr_port(raw: str) -> int
/// addr_text(raw) -> str：对端地址文本。IPv6 里 ::ffff:a.b.c.d（双栈 socket
/// 上 IPv4 客户端的形态）还原成点分四段，其余走 ip6_format。
fn addr_text(raw: str) -> str
/// peer_raw(fd) -> str：对端地址的 20 字节原始视图（见本文件末尾布局说明）。
fn peer_raw(fd: int) -> str
/// peer_ip(fd) -> str：对端 IP 文本（IPv4 点分 / IPv6 压缩格式）。
fn peer_ip(fd: int) -> str
/// peer_port(fd) -> int：对端端口（主机序）。
fn peer_port(fd: int) -> int
```

### `std/net/core.qma`

连接槽位层（IOCP reactor 的底座）

```quelmara
/// 新建协议状态块：`max_conns` 个定长槽位（每槽 `slot_words` 字）。
/// 返回状态指针，交给 `conn_open` / `conn_*` 统计函数使用。
fn conn_state_new(max_conns: int, slot_words: int) -> int
/// 槽位上限（超过后 `conn_open` 返回 -1，由协议层拒绝连接）。
fn conn_max_conns(st: int) -> int
/// 累计 accept 的连接数（含已关闭）。
fn conn_accepted(st: int) -> int
/// 累计关闭的连接数。
fn conn_closed(st: int) -> int
/// 累计派发给协议层的消息/请求数（`conn_msg_inc` 加）。
fn conn_msgs(st: int) -> int
/// 累计收到的字节数。
fn conn_bytes_in(st: int) -> int
/// 累计发出的字节数。
fn conn_bytes_out(st: int) -> int
/// 取全局自旋锁（`static_word(11)`）。共享结构（槽位空闲链 / fd 表）改前必取。
/// 持锁时间必须是 O(1)（几个指令），否则 io 线程会互相拖死。
fn conn_lock() -> int
/// 放全局自旋锁（与 `conn_lock` 成对）。
fn conn_unlock() -> int
/// 新连接：分配槽位、整槽清零、登记 fd→槽位。返回槽位下标；超上限返回 -1。
fn conn_open(st: int, fd: int) -> int
/// fd → 槽位指针（未登记返回 0）。协议私有字从 `SLOT_PROTO` 起，见 `std/net/core.qma` 头部布局。
fn conn_slot(st: int, fd: int) -> int
/// 关连接：归还溢出缓冲与槽位（O(1)，空闲链复用）。
fn conn_close(st: int, fd: int) -> int
/// 连接数据区指针：有溢出缓冲用堆，否则用槽位内联区。
fn conn_buf_ptr(p: int) -> int
/// 数据区当前容量（字节）。
fn conn_buf_cap(st: int, p: int) -> int
/// 把一段数据追加到连接缓冲，返回新的总长度；超 `CONN_MAX_BUF` 返回 -1。
/// 内联区满时自动溢出到堆（倍增扩容），任意分片都不会丢数据。
fn conn_append(st: int, p: int, data: str) -> int
/// 已收到的字节数（协议层的解析游标读它，不必知道槽位布局）
fn conn_recvlen(p: int) -> int
/// 派发计数 +1（协议层每处理一条完整消息调用一次）
fn conn_msg_inc(st: int) -> int
/// 协议回调槽 0（`ST_H0`）：协议库把用户 handler 存这里，reactor 回调时取用
fn conn_h0(st: int) -> int
/// 写协议回调槽 0
fn conn_set_h0(st: int, h: int) -> int
/// 把 `[from, len)` 搬到缓冲头部（处理完一个请求后剩下的半包），返回剩余长度。
fn conn_shift(p: int, from: int) -> int
/// 发送一段缓冲区（指针 + 长度直接进 send，零拷贝）。返回实际写入字节数。
fn conn_send(st: int, fd: int, ptr: int, n: int) -> int
/// 发送一个 str（`len(s)` 字节）。返回实际写入字节数。
fn conn_send_str(st: int, fd: int, s: str) -> int
```

### `std/net/dns.qma`

自研 DNS 解析器（RFC 1035 最小子集：A 记录 / 压缩指针 / resolv.conf）

```quelmara
/// dns_build_query(name) -> str：拼一个 A 记录的查询报文（12 字节头 + QNAME
/// + 4 字节 QTYPE/QCLASS）。name 必须是 FQDN（如 "example.com"）。
/// 头：id=0x1234 | flags=0x0100（RD） | qd=1 | an=0 | ns=0 | ar=0
/// QNAME 用标签格式：每段前置长度字节，以 0 结尾。
/// 返回空串表示名字非法（空段 / 段长 > 63 / 总长 > 255 / 非法字符）。
fn dns_build_query(name: str) -> str
/// dns_parse_a(msg) -> int：从应答里取出**第一条 A 记录**的 IPv4 地址，
/// 返回网络序 u32（与 udp_parse_ip 同口径）；没有 A 记录 / 报文非法返回 0。
/// 校验：ID 必须回显 0x1234、QR 必须为 1（应答）、RCODE 必须为 0（NOERROR）、
/// ANCOUNT > 0。任何长度越界都返回 0，不信任报文里的长度字段。
fn dns_parse_a(msg: str) -> int
/// dns_ip4_str(ip) -> str：网络序 u32 -> 点分字符串（A 记录的可读形式）。
fn dns_ip4_str(ip: int) -> str
/// dns_resolv_ns(text) -> str：从 resolv.conf 的**内容**里取出第一个
/// `nameserver` 的 IPv4 地址；没有则返回空串。
/// 做成"吃文本"而不是"自己读文件"，是为了能在测试里喂固定夹具
/// （文件读取在 ELF 后端要走 openat+read，属于调用方的事）。
fn dns_resolv_ns(text: str) -> str
/// dns_resolve(name) -> str：把域名解析成点分 IPv4 字符串；失败返回空串。
/// 这是调用方真正要用的入口。流程：
///   1. 先当 IPv4 字面量试（"1.2.3.4" 直接返回，不查网）；
///   2. 读 /etc/resolv.conf 取**全部** nameserver（没有则用 8.8.8.8 兜底）；
///   3. 依次向每个 nameserver 发 A 查询（每个 3 s 超时），第一个成功的胜出。
/// 失败一律返回空串（不 exit）——DNS 不可用是可恢复错误，调用方可以选择
/// 回退到字面量或报自己的错。这与库里"能返回就返回、不能返回才 fail-fast"
/// 的口径一致。
/// 需要自定义超时用 `dns_resolve_ex(name, ms_per_ns)`。
fn dns_resolve(name: str) -> str
/// dns_resolv_all(text) -> vec[str]：从 resolv.conf 内容里取出**全部**
/// `nameserver` 地址（按出现顺序）。没有则返回空 vec。
/// 与 `dns_resolv_ns` 的关系：后者只取第一个（保留给"只要一个"的调用方），
/// 前者给轮询用。两者共用同一套行扫描规则（注释 / 空白 / 行尾注释）。
fn dns_resolv_all(text: str) -> vec[str]
/// dns_query_ns(ns, q, ms) -> int：向**一个** nameserver 发查询并解析，
/// 返回网络序 u32；超时/失败返回 0。
/// 每次调用都新开一个 socket 并在结束时关闭：DNS 查询是低频操作，
/// 复用 fd 省下的那点开销抵不上"超时设置会串到下一次查询"的风险。
fn dns_query_ns(ns: str, q: str, ms: int) -> int
/// dns_resolve_ex(name, ms_per_ns) -> str：多 nameserver 轮询版解析。
/// 依次向 resolv.conf 里的每个 nameserver 发同一个查询，**第一个成功的胜出**；
/// 全部失败返回空串。`ms_per_ns` 是**每个** nameserver 的超时（不是总预算）——
/// 这样 3 个 nameserver 各 1 s 的最坏情况是 3 s，而不是把 1 s 摊给三个
/// （摊薄会让每个都必然超时，等于没轮询）。
/// 为什么要轮询：resolv.conf 里第一个 nameserver 常常是本地 stub
/// （127.0.0.53 / 127.0.0.1），它自己再往上游转发；stub 挂了或没起来时，
/// 只认第一个就等于整个解析不可用。轮询是 glibc 的默认行为，这里对齐它。
fn dns_resolve_ex(name: str, ms_per_ns: int) -> str
```

### `std/net/reactor.qma`

高并发 reactor：IOCP 事件循环（Quelmara 实现，仅 Windows PE）

```quelmara
/// 高并发 reactor：`net_serve(port, backlog, on_connect, on_data, on_close)`，
/// 阻塞运行到进程结束。回调传**裸函数名**（IR 层就是代码地址，经 `callr` 派发；
/// 0 = 不回调）：
///   `on_connect(fd: int)`、`on_data(fd: int, data: str) -> int`
///   （1 = 保持连接继续收；0 = 关闭）、`on_close(fd: int)`。
/// worker 线程数默认 = 物理核数（`Quelmara.toml [net] io_threads`，0 = 自动），
/// 连接上限 / 收缓冲 / TCP_NODELAY 同样取自 `[net]`；超上限的新连接直接关闭，
/// socket 级失败一律 fail-fast（stderr + 退出码 1）。仅 Windows PE（IOCP + `@ffi`）。
fn net_serve(port: int, backlog: int, on_connect: int, on_data: int, on_close: int) -> int
/// `net_serve` 的同义入口（`import std.net.reactor` 后可直接 `serve(...)`，
/// 与 `std/net.qma` 的过程式 API 并列）。
fn serve(port: int, backlog: int, on_connect: int, on_data: int, on_close: int) -> int
```

### `std/net/udp.qma`

UDP 封装与地址解析

```quelmara
/// udp_parse_ip("1.2.3.4") -> int：点分 IPv4 -> 网络序 u32（非法返回 0）
fn udp_parse_ip(ip: str) -> int
/// udp_send_str(fd, ip, port, data) -> int：字符串地址便捷层
/// （解析失败返回 -1）
fn udp_send_str(fd: int, ip: str, port: int, data: str) -> int
```

### `std/net/udp6.qma`

UDP over IPv6：文本地址转换 + 便捷发送（udp_open6/udp_bind6 内建）

```quelmara
/// 把点分/冒号形式的 IPv6 文本发到 (addr, port)。
/// 返回发送字节数；地址非法返回 -1。
fn udp_send6(fd: int, addr: str, port: int, data: str) -> int
/// 收一个数据报（源地址丢弃，与 v4 同口径）。
fn udp_recv6(fd: int, cap: int) -> str
/// 收一个数据报，最多等 ms 毫秒；超时返回空串（与 v4 的 `*_to` 同口径）。
fn udp_recv6_to(fd: int, cap: int, ms: int) -> str
/// 便捷：建 socket + 发一个数据报 + 关掉。
/// 适合"发一条 DNS 查询"这类一次性场景。
fn udp_once6(addr: str, port: int, data: str) -> int
```

### `std/p256.qma`

NIST P-256 域运算 + ECDSA 验签（TLS 证书签名）

```quelmara
/// 公钥是否在曲线上：y^2 == x^3 - 3x + b
fn p256_on_curve(pub_x: str, pub_y: str) -> int
/// ECDSA P-256 验签：输入均 32 字节大端；返回 1 = 有效
fn ecdsa_p256_verify(pub_x: str, pub_y: str, hash: str, r_sig: str, s_sig: str) -> int
```

### `std/p384.qma`

NIST P-384（secp384r1）ECDSA 验签（12 limb Montgomery + Jacobian，SHA-384 摘要；v2.99）

```quelmara
/// 公钥是否在曲线上：y^2 == x^3 - 3x + b。pub_x/pub_y 各 48 字节大端。
fn p384_on_curve(pub_x: str, pub_y: str) -> int
/// ECDSA P-384 验签：pub_x/pub_y/r/s 各 48 字节大端，hash 为 48 字节 SHA-384 摘要。
/// 返回 1 = 有效，0 = 无效。参数长度不对是调用方 bug（assert，同 p256 口径）。
fn ecdsa_p384_verify(pub_x: str, pub_y: str, hash: str, r_sig: str, s_sig: str) -> int
```

### `std/park.qma`

线程 park 原语：WaitOnAddress / WakeByAddress（仅 Windows PE；由 std/sync 注入使用）

```quelmara
/// 本后端有没有真正的 park。`std/park` 能编过就一定有，恒为 1。
fn park_available() -> int
/// 把 p 上的 8 字节值 park 到「不再等于 `want`」为止，最多 ms 毫秒。
/// 调用方契约：调用前把「当前值」读进 `want`。**不必**先确认谓词仍成立 ——
/// `WaitOnAddress` 自己会比：`*p != want` 时立即返回。
/// 返回 1 = 被唤醒，0 = 超时。
/// **语义保证（这是它比自旋正确的地方）**：「比较 `*p == want`」与「进入睡眠」
/// 由内核在同一个临界区里完成，所以不存在「刚检查完、还没睡下去，别人就
/// Wake 了」的丢失唤醒窗口。调用方只需「读值 → park → 回头重读」。
fn park_on(p: int, want: int, ms: int) -> int
/// 唤醒所有在 p 上 park 的线程。没有等待者时是安全的空操作（约 300–400 ns）。
fn wake_all(p: int)
/// 唤醒一个在 p 上 park 的线程。
/// 边界：**不知道它会不会立刻又睡回去**。如果被唤醒的线程因为条件仍不满足
/// 而重新 park，其余等待者就收不到这次唤醒 —— 所以只有在「唤醒一个就够」
/// （单等待者、或条件对任一等待者都成立）时才用它。多等待者用 `wake_all`。
fn wake_one(p: int)
```

### `std/park_linux.qma`

线程 park 原语：futex(2)（仅 Linux；与 std/park 同一组 API，由 std/sync 注入使用）

```quelmara
/// 本后端有没有真正的 park。`std/park_linux` 能编过就一定有，恒为 1。
fn park_available() -> int
/// 把 p 上的 8 字节值 park 到「不再等于 `want`」为止。
/// 返回 1 = 被唤醒（或被 `-EAGAIN` 立即返回），0 = 出错。
/// **`ms` 被忽略**：本实现是无限等待（见文件头）。谓词复查由调用方负责，
/// 所以"无限等待"不会挂死 —— `std/sync.wg_wait` 醒来后会重新读计数。
fn park_on(p: int, want: int, ms: int) -> int
/// 唤醒所有在 p 上 park 的线程（`FUTEX_WAKE` 传 INT_MAX）。
fn wake_all(p: int)
/// 唤醒一个在 p 上 park 的线程。
fn wake_one(p: int)
```

### `std/path.qma`

路径处理（join / clean / dir / base / ext / stem；'/' 与 '\' 都认）

```quelmara
/// 绝对路径判定：'/' 开头，或 `C:` 这种盘符开头；空串返回 false。
fn path_is_abs(p: str) -> bool
/// 拼接两段路径：b 是绝对路径直接返回 b；接缝处只留一个 '/'。
/// 任一段为空时返回另一段（不产生多余的 '/'）。
fn path_join(a: str, b: str) -> str
/// 消解 . 与 ..
fn path_clean(p: str) -> str
/// 最后一个分隔符之前的部分（根目录返回 "/"）
fn path_dir(p: str) -> str
/// 最后一个分隔符之后的部分
fn path_base(p: str) -> str
/// 扩展名（不含点）；没有返回空串。以点开头的文件名（.gitignore）没有扩展名
fn path_ext(p: str) -> str
/// 去掉扩展名（含点）
fn path_stem(p: str) -> str
```

### `std/rand.qma`

xorshift64* 伪随机

```quelmara
/// rand_seed(s)：显式播种。s 经混合避免弱种子（如全 0）。
fn rand_seed(s: int)
/// rand_next() -> int：产出 64 位伪随机数（可能为负——int 是有符号 64 位）
fn rand_next() -> int
/// rand_below(n) -> int：[0, n) 的非负随机数（n > 0）。
/// 取 rand_next 的高位（低位质量差）并钳到非负。
fn rand_below(n: int) -> int
/// rand_range(lo, hi) -> int：[lo, hi) 的随机数（hi > lo）
fn rand_range(lo: int, hi: int) -> int
```

### `std/regex.qma`

正则引擎（回溯 VM）：字面/./字符类/转义类/量词 *+?{n,m}/交替/分组(?:)/锚点 ^$；compile+match/full/exec/find/replace[_all]，步数上限防病态回溯

```quelmara
/// 编译正则。成功返回程序（vec[int]）；语法错误返回空 vec（len = 0）。
fn regex_compile(pat: str) -> vec[int]
/// 搜索：pat 在 s 任意位置匹配返回 1；语法错误 -2；不匹配 0
fn regex_match(pat: str, s: str) -> int
/// 全匹配：整个 s 被 pat 匹配返回 1（等价 Python fullmatch）；语法错误 -2
fn regex_match_full(pat: str, s: str) -> int
/// 已编译程序的搜索：1 匹配 / 0 不匹配 / -2 坏程序
fn regex_exec(prog: vec[int], s: str) -> int
/// 查找：返回最左匹配的起始位置；无匹配 -1；坏程序 -2
fn regex_find(prog: vec[int], s: str) -> int
/// 替换第一处（rep 为字面量，无引用展开）；空匹配不替换；坏程序返回原串
fn regex_replace(prog: vec[int], s: str, rep: str) -> str
/// 替换全部（空匹配跳过，避免 Python 空匹配邻接规则的复杂度）
fn regex_replace_all(prog: vec[int], s: str, rep: str) -> str
```

### `std/router.qma`

路径模板匹配（/users/:id、尾部 * 通配、query/尾斜杠归一化、方法白名单）

```quelmara
/// 归一化：去 query/fragment、去尾 '/'、去首 '/'
fn route_norm(target: str) -> str
/// 归一化后按 '/' 切段；空路径给 0 段
fn route_segs(target: str) -> vec[str]
/// 路径模板匹配：`/users/:id` 的 `:段` 匹配任意一段，尾部 `*` 匹配剩余（含零段）。
/// 比较前两边都归一化（去 query、去尾斜杠）；段数不等且没有 `*` 则不匹配。
fn route_match(pattern: str, path: str) -> bool
/// 捕获的参数（按出现顺序）；不匹配返回空 vec
fn route_params(pattern: str, path: str) -> vec[str]
/// 归一化后的有效长度（截掉 `?query` / `#frag`、去掉尾部 '/'）。
/// 路由表在注册期用它把模板存成**归一化形态**，派发期用它把路径算一次。
fn route_eff_len(buf: int, n: int) -> int
/// 归一化缓冲的段数（'/' 分隔；空缓冲 0 段；连续 '/' 会产生空段，与 str_split 一致）
fn route_seg_count(buf: int, n: int) -> int
/// 模板匹配的字节级版：`pat`/`path` 是 (数据指针, 字节长度)。
/// 归一化（query / fragment / 首尾斜杠）与 `route_match` 完全一致。
fn route_match_bytes(pat: int, pat_len: int, path: int, path_len: int) -> bool
/// 已归一化输入的匹配（两边都去过 query / 首尾斜杠）：纯逐段走，不再扫归一化。
/// 路由表在注册期就把模板存成归一化形态、派发期把路径归一化一次，热路径走这里。
fn route_match_norm(pat: int, pat_len: int, path: int, path_len: int) -> bool
/// 第 idx 个 `:参数` 捕获（不匹配或越界返回 ""）。零分配匹配、只拷贝那一段。
fn route_param_at(pat: int, pat_len: int, path: int, path_len: int, idx: int) -> str
/// `:参数` 段个数（不匹配返回 0）
fn route_param_count(pat: int, pat_len: int, path: int, path_len: int) -> int
/// "GET,POST" 里是否允许 method（HTTP 方法区分大小写，按原样比）
fn route_method_allowed(allowed: str, method: str) -> bool
```

### `std/rsa.qma`

RSA PKCS#1 v1.5 / PSS 验签（SHA-256，证书链与 TLS 用）

```quelmara
/// PKCS#1 v1.5 + SHA-256 验签。
/// n：模数（大端、无前导 0）；e：指数；sig：签名字节；hash：32 字节摘要。
/// 返回 1 = 有效，0 = 无效。
fn rsa_verify_pkcs1_sha256(n: str, e: int, sig: str, hash: str) -> int
/// PKCS#1 v1.5 + SHA-384 验签（v2.99）。
/// 为什么需要：Amazon Root CA 1 的自签、microsoft.com 全链、大量企业 CA
/// 都用 sha384WithRSAEncryption——只有 SHA-256 时这些根验不了自签、
/// 这些链验不过。hash 是 48 字节摘要。
fn rsa_verify_pkcs1_sha384(n: str, e: int, sig: str, hash: str) -> int
/// RSASSA-PSS + SHA-256 验签（TLS 1.3 CertificateVerify 用，0x0804）
fn rsa_verify_pss_sha256(n: str, e: int, sig: str, hash: str, salt_len: int) -> int
```

### `std/serialize.qma`

LEB128 varint / 定长整数 / 长度前缀帧

```quelmara
// 本模块的顶层函数都未 pub 导出：可以 import，但用户代码引用会
// 编译失败（见 07-gaps.md §7.13）
```

### `std/session.qma`

内存会话存储（sid 生成 / TTL 惰性过期 / 滑动续期 / 墓碑销毁）

```quelmara
/// 新建会话存储（两张 map：data 存 sid\x1fkey→值，exp 存 sid→过期时刻）。
/// 按值传递，所以在同一处创建并使用，别复制后各改各的。
fn session_new() -> SessionStore
/// 新建会话，返回 sid；ttl 单位秒（<=0 表示永不过期）
fn session_create(st: SessionStore, ttl: int, now: int) -> str
/// 会话是否有效：sid 为空 / 不存在 / 已过期都返回 false；过期时刻 0 表示永不过期。
fn session_alive(st: SessionStore, sid: str, now: int) -> bool
/// 取会话里某个键的值；会话无效或键不存在返回空串（与『存在但为空』不可区分）。
fn session_get(st: SessionStore, sid: str, key: str, now: int) -> str
/// 写入；会话不存在或已过期返回 false
fn session_set(st: SessionStore, sid: str, key: str, value: str, now: int) -> bool
/// 续期（滑动过期）；会话已死返回 false
fn session_touch(st: SessionStore, sid: str, ttl: int, now: int) -> bool
/// 销毁：打墓碑（exp = -1），data 里的键无法枚举所以留在表里（见模块头注释）
fn session_destroy(st: SessionStore, sid: str)
/// 已创建的会话总数（含已销毁的墓碑）
fn session_count(st: SessionStore) -> int
```

### `std/set.qma`

集合 set[int] / set[str]（map 支撑，含交并差）

```quelmara
/// 建一个 set[int]（底层 map[int]int，cap 是初始槽数，可被自动扩容覆盖）。
fn iset_new(cap: int) -> map[int]int
/// 加入元素，幂等：1=新增 / 0=已存在（调用方可直接累加算基数）。
fn iset_add(s: map[int]int, v: int) -> int
/// 成员判定，O(1)。
fn iset_has(s: map[int]int, v: int) -> bool
/// 删除元素：1=删掉了 / 0=本来就没有（先 has 再 del，因为 map.del 无返回值）。
fn iset_del(s: map[int]int, v: int) -> int
/// 元素个数，O(1)（= len(map)）。
fn iset_len(s: map[int]int) -> int
/// iset_to_vec(s) -> vec[int]：导出成 vec（遍历顺序未定义，需要有序自行排序）
fn iset_to_vec(s: map[int]int) -> vec[int]
/// iset_union_into(dst, src) -> int：把 src 并入 dst，返回新增个数
fn iset_union_into(dst: map[int]int, src: map[int]int) -> int
/// iset_isect(a, b) -> vec[int]：交集（结果无序）
fn iset_isect(a: map[int]int, b: map[int]int) -> vec[int]
/// iset_diff(a, b) -> vec[int]：差集 a - b（结果无序）
fn iset_diff(a: map[int]int, b: map[int]int) -> vec[int]
/// 建一个 set[str]（底层 map[str]int），用于标签 / Header 名 / 路由段。
fn sset_new(cap: int) -> map[str]int
/// 加入字符串，幂等：1=新增 / 0=已存在。
fn sset_add(s: map[str]int, v: str) -> int
/// 字符串成员判定，O(1)。
fn sset_has(s: map[str]int, v: str) -> bool
/// 删除字符串：1=删掉了 / 0=本来就没有。
fn sset_del(s: map[str]int, v: str) -> int
/// 字符串元素个数，O(1)。
fn sset_len(s: map[str]int) -> int
```

### `std/sha1.qma`

SHA-1

```quelmara
/// 对 str 的 UTF-8 字节算 SHA-1，返回 40 位小写十六进制（WebSocket 握手用）。
/// 按字节计算，不做任何归一；空串有定义（da39a3ee…）。
fn sha1_hex(s: str) -> str
```

### `std/sha256.qma`

SHA-256 + HMAC-SHA256

```quelmara
/// sha256_str(s) -> int：32 字节摘要缓冲区指针（大端序，含 0 字节，不能当 str）。
/// 调用方用完后 mem_free(dig, 32)。
fn sha256_str(s: str) -> int
/// sha256_hex(s) -> str：64 位小写十六进制
fn sha256_hex(s: str) -> str
/// hmac_sha256_str(key, msg) -> int：32 字节摘要缓冲区（用完 mem_free(d, 32)）
fn hmac_sha256_str(key: str, msg: str) -> int
/// HMAC-SHA256 的十六进制形式（RFC 2104：ipad/opad 各 64 字节，密钥超长先哈希）。
/// 返回 64 位小写十六进制；key 与 msg 都按字节处理。
fn hmac_sha256_hex(key: str, msg: str) -> str
```

### `std/sha512.qma`

SHA-512 / SHA-384（变体 IV 复用压缩函数）+ HMAC-SHA512

```quelmara
/// SHA-512 摘要缓冲区（64 字节，大端，含 0 字节不能当 str；用完 mem_free(d, 64)）
fn sha512_str(s: str) -> int
/// SHA-512 十六进制（128 位小写）
fn sha512_hex(s: str) -> str
/// SHA-384 原始摘要（48 字节，mem_alloc 分配，调用方 mem_free(dig, 48)）。
/// v2.99 起提供：ECDSA P-384 验签要的是**字节**而不是十六进制串
/// （sha384_hex 只给串，从串转回字节是绕路且会掩盖长度口径）。
fn sha384_str(s: str) -> int
/// SHA-384（FIPS 180-4 变体：不同的 IV，输出截断到前 48 字节）
fn sha384_hex(s: str) -> str
/// HMAC-SHA512 摘要缓冲区（64 字节；用完 mem_free(d, 64)）
fn hmac_sha512_str(key: str, msg: str) -> int
/// HMAC-SHA512 十六进制（128 位小写）
fn hmac_sha512_hex(key: str, msg: str) -> str
```

### `std/sort.qma`

快速排序与有序性检查

```quelmara
/// sort_int(v)：就地升序排序 vec[int]。
fn sort_int(v: vec[int])
/// is_sorted(v) -> int：升序校验（1/0）
fn is_sorted(v: vec[int]) -> int
```

### `std/sse.qma`

Server-Sent Events 服务端

```quelmara
// 本模块的顶层函数都未 pub 导出：可以 import，但用户代码引用会
// 编译失败（见 07-gaps.md §7.13）
```

### `std/staticfile.qma`

静态文件服务的安全解析层（URL 解码 / 目录穿越防护 / index 补全 / Cache-Control / ETag / Range 解析）

```quelmara
/// 百分号解码；没有 '%' 时直接返回原串（快路径）
fn static_url_decode(s: str) -> str
/// 解码后是否安全（无目录穿越、无反斜杠、无 NUL）
fn static_path_safe(url: str) -> bool
/// URL -> 磁盘路径；不安全返回空串（调用方回 403/404）
fn static_resolve(root: str, url: str) -> str
/// 目录请求补 index.html（空路径也算目录）
fn static_index_for(path: str) -> str
/// 静态文件的 Content-Type（= mime_of(path)，认不出给 application/octet-stream）。
fn static_content_type(path: str) -> str
/// HTML 不缓存（改一次立刻生效）；其余静态资源按一年长缓存
fn static_cache_control(path: str) -> str
/// 由 size 与 mtime 拼出弱 ETag（带引号的 `size-mtime`），不读文件内容。
fn static_etag(size: int, mtime: int) -> str
/// Range: bytes=... -> [start, end]；空 vec 表示"按全量处理"
fn static_range(hdr: str, size: int) -> vec[int]
/// 生成完整 HTTP/1.1 响应；调用方把返回串写给 fd 即可
///   root  —— 站点根目录（磁盘路径）
///   url   —— 请求路径（可带 query/fragment，内部会归一化）
///   range —— 请求的 Range 头（没有就传空串）
fn static_serve(root: str, url: str, range: str) -> str
```

### `std/str.qma`

字符串工具集

```quelmara
/// str_find(s, needle) -> int：首个出现位置，找不到 -1
fn str_find(s: str, needle: str) -> int
/// 从字节下标 from 起找 needle 首次出现，返回起点下标；找不到返回 -1。
/// from<0 或 from>=len 返回 -1；空 needle 返回 0（与 str_find 同口径）。
fn str_find_from(s: str, from: int, needle: str) -> int
/// 反向查找：从 need 的位置往前找最后一次出现
fn str_rfind(s: str, needle: str) -> int
/// needle 是否出现（等价于 str_find(s, needle) >= 0）；空 needle 恒 true。
fn str_contains(s: str, needle: str) -> bool
/// 按字节比较前缀；p 比 s 长或前缀不同返回 false，空 p 恒 true。
fn str_starts_with(s: str, p: str) -> bool
/// 按字节比较后缀；p 比 s 长或后缀不同返回 false，空 p 恒 true。
fn str_ends_with(s: str, p: str) -> bool
/// needle 在 s 里出现的次数，**不重叠**（每次命中后跳过 len(needle) 字节）。
/// 空 needle 返回 0（不是 len+1）。
fn str_count(s: str, needle: str) -> int
/// 去掉左侧空白（空格 / \t / \n / \r / \v / \f），全空白返回空串。
fn str_trim_left(s: str) -> str
/// 去掉右侧空白（同上六种），全空白返回空串。
fn str_trim_right(s: str) -> str
/// 两端去空白（= trim_left + trim_right）；返回新串，不共享缓冲。
fn str_trim(s: str) -> str
/// ASCII 小写 a-z 转大写，其它字节原样（非 ASCII / UTF-8 多字节不动）。
/// 新分配，长度不变。
fn str_upper(s: str) -> str
/// ASCII 大写 A-Z 转小写，其它字节原样；新分配，长度不变。
fn str_lower(s: str) -> str
/// ASCII 忽略大小写比较（HTTP 头名 / 方法名常用；RFC 7230 规定 token 是 ASCII）
fn str_eq_ci(a: str, b: str) -> bool
/// 把 s 重复 n 次拼接；n<=0 返回空串。
/// 一次分配 len(s)*n 字节，不做 O(n²) 累加。
fn str_repeat(s: str, n: int) -> str
/// 用分隔符拼 vec[str]（对应 Python 的 sep.join(list)）
fn str_join(parts: vec[str], sep: str) -> str
/// str_split(s, sep) -> vec[str]：单遍扫描拆分。sep 为空 -> 整体一项。
/// 实现纪律：循环内不调用 substr（v1.5 实测"循环内 substr + 调用结果做下标"
/// 会被优化器误编译），改为累积字节缓冲、到分隔符处一次性成串。
fn str_split(s: str, sep: str) -> vec[str]
/// 只拆前 max_parts-1 次，剩余整段作为最后一项（HTTP 请求行等场景）
fn str_split_n(s: str, sep: str, max_parts: int) -> vec[str]
/// 按行拆（\n，自动去掉行尾 \r），日志/配置/HTTP 头常用
fn str_lines(s: str) -> vec[str]
/// 把**全部**不重叠的 from 替换为 to；from 为空或没有命中时原样返回 s。
fn str_replace(s: str, from: str, to: str) -> str
/// 只替换第一处 from；找不到时原样返回 s。
fn str_replace_first(s: str, from: str, to: str) -> str
/// 按字节切 [lo, hi)：两端自动钳到 [0, len]，a>=b 返回空串。
/// 按字节，不保证落在 UTF-8 字符边界（要按字符切用 std/utf8 的 utf8_slice）。
fn str_slice(s: str, lo: int, hi: int) -> str
/// 取前 n 字节（= str_slice(s, 0, n)）；n 超过长度自动钳到全长。
fn str_left(s: str, n: int) -> str
/// 取后 n 字节（= str_slice(s, len-n, len)）；n 超过长度返回整串。
fn str_right(s: str, n: int) -> str
/// 去掉前缀/后缀（不存在则原样返回）
fn str_strip_prefix(s: str, p: str) -> str
/// 后缀匹配才去掉，否则原样返回（不报错、不 assert）。
fn str_strip_suffix(s: str, p: str) -> str
/// 左补字符到宽度（str_pad_left("7", 3, "0") = "007"）
fn str_pad_left(s: str, width: int, pad: str) -> str
```

### `std/sync.qma`

自旋锁 / Treiber 无锁栈 / WaitGroup（零 @ffi，park 由调用方注入）

```quelmara
/// 注入 park/wake 实现（传 0 表示恢复纯退避）。
/// 典型用法（Windows）：`import std.park` 之后
/// `sync_set_park(park_on, wake_all)`。
/// 非 Windows 后端不 import `std.park` 即可 —— 本模块照样编得过。
fn sync_set_park(park_fn: int, wake_fn: int)
/// 当前有没有注入 park 实现（1 = 有）。
fn sync_has_park() -> int
/// 新建一把锁（8 字节堆块，0=未锁 / 1=已锁），返回锁句柄。
/// 锁对象不自动回收：用完自己 mem_free。
fn mutex_new() -> int
/// 获取锁：atomic_cas 抢 0→1，失败时前 128 次 spin_hint、之后 thread_yield，直到抢到。
/// **不是 futex park**：长等待靠让出时间片，不睡眠。
/// **v3.15 的负结果：锁不用 park，这是实测结论，不是没做。**
/// 第一版把长等待换成 `WaitOnAddress`（与 `wg_wait` 同样的改法），16 线程 ×
/// 20 万次加锁从 **281 ms 掉到 1568 ms（慢 5.6×）**。加"先 yield 1024 次再
/// park"的门槛后仍有 855 ms（慢 3×）。原因不是 park 慢，而是**判据在原理上
/// 缺信息**：
///   * 这个基准的临界区约 88 ns，整个基准才 281 ms；
///   * 每个线程等待锁的时间被切成很多小段（每次等几十 µs），
///     而"已经等多久"这个代理判据无法区分"马上就好"与"要等很久"；
///   * 一旦跨过门槛就付 ~400 ns 的 `WaitOnAddress` + 解锁侧的
///     `WakeByAddressAll`，比"再 yield 一次（~5.5 µs，但能立刻抢到）"还亏，
///     因为 park 的唤醒要经过内核调度器，而 yield 的对手通常就在同一个核上。
/// **park 只对"等待时长 ≫ 系统调用开销"有利**，而锁的等待时长在拿锁瞬间
/// 是不可知的。WaitGroup 不一样：它的等待时长由调用方决定（等一批任务），
/// 动辄几十毫秒到几秒，且**只等一次**，不在热循环里 —— 那才是 park 的战场。
fn mutex_lock(m: int)
/// 释放锁（mem_store_rel，release 语义）；x86 下就是普通 mov，AArch64 用 STLR。
fn mutex_unlock(m: int)
/// 新建 Treiber 栈（16 字节：head + poplock），返回句柄；节点 16 字节 [next][value]。
fn stack_new() -> int
/// 压栈：节点 CAS 挂到 head，失败重读重挂；**全程无锁**，不拿 poplock。
fn stack_push(s: int, v: int)
/// 消费者锁：pop 串行化。为什么这样就消掉了 ABA——
///   设同一时刻只有一个线程在 pop。它读到的 head = A、A.next = B 之后，
///   能把 A 从链上摘掉的只有 pop（push 只增加节点），而 pop 只有它自己，
///   所以 CAS(head, A, B) 之前 A 不可能"先被摘掉再被挂回来"。
///   并发 push 只会让 head 变成新节点，CAS 自然失败并重试（安全）。
///   不加这把锁时的前提是"节点地址永不复用"：本库不 free 节点、也不把节点
///   还给调用方，所以现状下 ABA 不会发生（2P/2C 压测 10 次不复现）。但那只是
///   **隐含约定**——一旦有人让 pop 返回节点、或 allocator 把弹出的块还给新的
///   push，head 就会变回旧值，链被写坏且无任何报错。这把锁把"不可能"变成
///   结构性保证，代价是一次原子交换。单消费者场景用 stack_pop_single 免掉它。
fn stack_pop(s: int) -> int
/// 单消费者快路径：不取 poplock，因此只在"同一时刻只有一个线程 pop"时正确。
/// 与 stack_pop 的差 = 一次原子交换 + 一次存储（见 docs/06-status.md §3.5）。
fn stack_pop_single(s: int) -> int
/// 新建 WaitGroup（8 字节计数，初始 0），返回句柄。
fn wg_new() -> int
/// 计数加 n（atomic_add，全屏障）；通常在 spawn 之前一次性加好。
fn wg_add(w: int, n: int)
/// 计数减 1；减到 0 时等待方才能通过 wg_wait。
fn wg_done(w: int)
/// 阻塞到计数归零。
/// 三段退避：
///   1. 前 64 次 `spin_hint`（≈0.3 µs）—— "马上就好"的等待不该付系统调用；
///   2. 再 1024 次 `thread_yield`（≈5.6 ms）—— 毫秒级等待，让出但不睡；
///   3. 之后：**注入过 park 就 park**（CPU 归零、唤醒 µs 级），
///      否则退回 `sleep_ms(1)`（本机实际约 15.6–25 ms 一个片）。
/// 第 3 段的行为取决于调用方有没有 `sync_set_park(park_on, wake_all)`：
/// 不注入时本函数仍正确，只是长等待的唤醒晚一个时钟片。这是 v3.16 为了
/// 让本模块在非 PE 后端可编译而做的取舍（见文件头）。
/// **为什么 park 不需要额外的锁**：`WaitOnAddress(w, &cmp, 8, ms)` 的语义是
/// "若 *w == cmp 才睡，否则立即返回"，内核在同一个临界区里完成"比较 + 入队"。
/// 我们把 cmp 设成**刚刚读到的非零值**，于是：
///   * 若 wg_done 已经把计数减到 0，*w != cmp → 立即返回，重新检查，退出循环；
///   * 若我们真的睡下去了，那 wg_done 的 wake 一定能把我们叫醒。
/// 两种情况都不丢唤醒，所以循环里只要"读值 → 若非零则 park → 回头重读"。
fn wg_wait(w: int)
```

### `std/time.qma`

时间便捷层

```quelmara
// 本模块的顶层函数都未 pub 导出：可以 import，但用户代码引用会
// 编译失败（见 07-gaps.md §7.13）
```

### `std/timer.qma`

轮询式定时器（mem 块上的二叉最小堆；无后台线程 / 无回调，主循环 poll）

```quelmara
/// timer_after(ms) -> int：ms 毫秒后到期，返回句柄 id（从 1 递增，永不复用）。
/// `ms <= 0` 表示"下一次 timer_poll 就到期"（到期时刻不晚于调用时刻）。
fn timer_after(ms: int) -> int
/// timer_cancel(id)：取消（O(1)，只清存活位）。到期时 timer_poll 静默丢弃。
/// 已取消 / 已到期的 id 再取消一次是幂等的；越界 id 直接忽略。
fn timer_cancel(id: int)
/// timer_poll() -> int：弹出一个**已到期且未取消**的 id（没有则 -1）。
/// 已取消的到期项静默跳过——所以一次调用可能弹掉多个堆项才返回。
fn timer_poll() -> int
/// timer_pending() -> int：还没到期/没取消的定时器个数（**O(n) 扫描**，诊断用）。
fn timer_pending() -> int
/// timer_clear()：释放两个块（下次 timer_after 重新建、id 从 1 起）。
/// 主要给测试与"整轮重启"用；释放后旧 id 全部失效。
fn timer_clear()
```

### `std/tls13.qma`

TLS 1.3 密钥调度（HKDF-Expand-Label）+ AEAD 记录层

```quelmara
/// SHA-256 → 32 字节 str
fn tls_hash(s: str) -> str
/// HKDF-Extract：PRK = HMAC(salt, IKM)。salt 为空时按 RFC 用全零 32 字节。
fn hkdf_extract(salt: str, ikm: str) -> str
/// HKDF-Expand：OKM = T(1) || T(2) || …，T(i) = HMAC(PRK, T(i-1) || info || i)
fn hkdf_expand(prk: str, info: str, n: int) -> str
/// Derive-Secret(Secret, Label, Messages)
///   = HKDF-Expand-Label(Secret, Label, Transcript-Hash(Messages), Hash.length)
fn tls_derive_secret(secret: str, label: str, transcript_hash: str) -> str
/// early_secret = HKDF-Extract(0, 0)
fn tls_early_secret() -> str
/// 空 transcript 的哈希（SHA-256("")）
fn tls_empty_hash() -> str
/// handshake_secret = HKDF-Extract(Derive-Secret(early, "derived", ""), ECDHE)
fn tls_handshake_secret(early: str, shared: str) -> str
/// master_secret = HKDF-Extract(Derive-Secret(handshake, "derived", ""), 0…0)
fn tls_master_secret(handshake: str) -> str
/// 流量密钥 / IV（RFC 8446 §7.3）
fn tls_traffic_key(secret: str) -> str
/// 由流量密钥派生出 12 字节 IV（HKDF-Expand-Label 的 iv）；每代密钥一次。
fn tls_traffic_iv(secret: str) -> str
/// finished_key = HKDF-Expand-Label(BaseKey, "finished", "", Hash.length)
fn tls_finished_key(secret: str) -> str
/// Finished 的 verify_data = HMAC(finished_key, Transcript-Hash(handshake))
fn tls_finished_verify_data(finished_key: str, transcript_hash: str) -> str
/// nonce = IV XOR (seq 按大端放在最后 8 字节)
fn tls_nonce(iv: str, seq: int) -> str
/// 完整记录：type || 0x0303 || len || payload（明文记录，如 ClientHello）
fn tls_record(ctype: int, payload: str) -> str
/// 加密记录：type(23) || 0x0303 || len || (密文||tag)
fn tls_seal_record(key: str, iv: str, seq: int, ctype: int, plain: str) -> str
/// 解密记录：payload 是去掉 5 字节记录头后的密文||tag
fn tls_open_record(key: str, iv: str, seq: int, sealed: str) -> str
/// 解密记录并保留末尾的内容类型字节（调用方可区分握手/应用数据/告警）。
/// 解密失败返回空串。
fn tls_open_record_raw(key: str, iv: str, seq: int, sealed: str) -> str
/// 握手消息头：type || 3 字节长度
fn tls_hs_msg(mtype: int, body: str) -> str
/// 16 位大端整数（构造扩展、长度前缀时用）
fn tls_u16(v: int) -> str
/// 24 位大端整数
fn tls_u24(v: int) -> str
/// 解析记录头：返回 [ctype, hdr_len, payload_off, payload_len, next_off]；非法返回空 vec。
fn tls_record_parse(buf: str, pos: int) -> vec[int]
/// 解析握手消息头：返回 [mtype, hdr_len, body_off, body_len, next_off]；非法返回空 vec。
fn tls_hs_parse(buf: str, pos: int) -> vec[int]
/// 构造扩展：type || len || body
fn tls_ext(etype: int, body: str) -> str
```

### `std/tls_client.qma`

TLS 1.3 客户端握手核心 + 证书链入口（RFC 8448 逐字节）

```quelmara
/// 构造一个失败结果（ok=0，err=给定错误码），其余字段清空；错误码形如 priv-len / ch-record。
fn tls_client_err(code: str) -> TlsClientResult
/// CertificateVerify 的待签名内容哈希：
///   64 个 0x20 || "TLS 1.3, server CertificateVerify" || 0x00 || transcript_hash
fn tls_cert_verify_hash(transcript_hash: str) -> str
/// TLS 1.3 的 ECDSA 签名是 DER 的 SEQUENCE { INTEGER r, INTEGER s }，
/// 这里转成 64 字节 r||s；格式非法返回 ""。
fn tls_ecdsa_sig_raw(sig: str) -> str
/// 构造 ClientHello 记录（单 cipher suite、单 key share、SNI）。
/// rnd 必须是 32 字节随机数，sid 是 0..32 字节的 legacy_session_id。
fn tls_client_hello(host: str, pub: str, rnd: str, sid: str) -> str
/// 用客户端私钥（32 字节 X25519）+ ClientHello 记录处理服务端回包，走完 TLS 1.3 握手。
/// 返回 TlsClientResult：ok=1 表示服务器 Finished 验证通过；失败时 err 给原因，cv 是 CertificateVerify 结果（1 通过 / 0 失败 / -1 算法不支持）。
fn tls_client_handshake(priv: str, ch_record: str, server_bytes: str) -> TlsClientResult
/// Certificate 消息里的证书数量
fn tls_cert_count(r: TlsClientResult) -> int
/// 第 i 张证书的 DER（0 = leaf）；越界返回 ""
fn tls_cert(r: TlsClientResult, i: int) -> str
```

### `std/tls_net.qma`

TLS 1.3 网络层：TCP 建连 + 握手 + 应用数据（Windows）

```quelmara
/// 建连并完成握手；成功后 fd 有效，client_finished 已发送。
fn tls_connect(host: str, port: int) -> TlsClientResult
/// 发一条应用数据记录（seq 从 0 开始）
fn tls_send_app(r: TlsClientResult, seq: int, data: str) -> int
/// 收一条应用数据（跳过 NewSessionTicket / KeyUpdate 等握手消息）。
/// 对端关闭或解密失败返回空串。
fn tls_read_app(r: TlsClientResult, seq: int) -> str
```

### `std/url.qma`

URL 解析 / query 取值 / 编码解码

```quelmara
/// url_decode(s)：%XX 解码 + '+' -> 空格（application/x-www-form-urlencoded）
fn url_decode(s: str) -> str
/// url_decode_path(s)：只解 %XX，保留 '+'（路径语义）
fn url_decode_path(s: str) -> str
/// url_encode(s)：保留 unreserved，其余 %XX（空格 -> %20，不是 +）
fn url_encode(s: str) -> str
/// url_encode_query(s)：同 url_encode，但空格编成 '+'（表单提交语义）
fn url_encode_query(s: str) -> str
/// scheme（小写化，: 之前）；无 scheme 返回 ""
fn url_scheme(u: str) -> str
/// host（去掉 userinfo 与端口；IPv6 保留方括号）
fn url_host(u: str) -> str
/// 端口；缺省返回 -1
fn url_port(u: str) -> int
/// path（不含 query/fragment）；没有 path 返回 "/" 之外的空串
fn url_path(u: str) -> str
/// 原始 query（不含 '?' 与 '#')
fn url_query(u: str) -> str
/// 取 '#' 之后的片段（不含 '#'）；没有 '#' 返回空串。
fn url_fragment(u: str) -> str
/// query 里取某个键（解码后返回）；不存在返回 ""
/// 语义：同名键取第一个；键值以 '&' 分隔，'=' 可省略（值按 ""）
fn url_query_get(u: str, key: str) -> str
/// 便捷：拼 query（已编码的 key/value）
fn url_join_query(base: str, key: str, val: str) -> str
```

### `std/utf8.qma`

UTF-8 解码/编码/严格校验（RFC 3629）

```quelmara
/// utf8_decode_at(s, i) -> int：解出 i 处码点；非法返回 -1
fn utf8_decode_at(s: str, i: int) -> int
/// utf8_valid(s) -> bool：整串严格校验（上面四条全查）
fn utf8_valid(s: str) -> bool
/// utf8_encode(cp) -> str：码点编码成 UTF-8（非法码点写成 U+FFFD）
fn utf8_encode(cp: int) -> str
/// utf8_count(s) -> int：字符数（非法字节各算 1）
fn utf8_count(s: str) -> int
/// utf8_byte_of_char(s, ci) -> int：第 ci 个字符的起始字节偏移；越界返回 -1
fn utf8_byte_of_char(s: str, ci: int) -> int
/// utf8_slice(s, lo, hi) -> str：按**字符**下标切片（半开区间，越界自动夹紧）
fn utf8_slice(s: str, lo: int, hi: int) -> str
/// utf8_to_chars(s) -> vec[int]：码点序列（非法位置填 -1，便于测试定位）
fn utf8_to_chars(s: str) -> vec[int]
```

### `std/uuid.qma`

UUID v4 生成 + nil + 校验/版本/变体位（随机源为 std/rand，非密码学）

```quelmara
/// 生成 v4 UUID（两次 rand_next 取 128 位，按 RFC 4122 打版本位与变体位）。
/// 小写带连字符；随机源是 xorshift，**不是密码学安全**——标识可以，密钥不行。
fn uuid_v4() -> str
/// 全零 UUID（00000000-0000-0000-0000-000000000000）。
fn uuid_nil() -> str
/// 格式校验：长度 36、连字符在 8/13/18/23、其余为十六进制（大小写都收）；不校验版本/变体。
fn uuid_valid(s: str) -> bool
/// 版本号（1..5）；不是合法 UUID 返回 -1
fn uuid_version(s: str) -> int
/// RFC 4122 变体位是否为 10xx（0x8 / 0x9 / 0xa / 0xb）
fn uuid_variant_ok(s: str) -> bool
```

### `std/ws.qma`

WebSocket 服务端（RFC 6455）

```quelmara
// 本模块的顶层函数都未 pub 导出：可以 import，但用户代码引用会
// 编译失败（见 07-gaps.md §7.13）
```

### `std/x25519.qma`

Curve25519 上的 X25519 密钥交换（RFC 7748，TLS ECDHE 地基）

```quelmara
/// 标量钳位：k[0] &= 248, k[31] &= 127, k[31] |= 64
fn x25519_clamp(k: str) -> str
/// X25519(k, u)：32 字节标量 × 32 字节 u 坐标 → 32 字节共享值
fn x25519(k: str, u: str) -> str
/// 基点 9 上的标量乘：生成公钥（u = 9，小端：首字节 9，其余 0）
fn x25519_base(k: str) -> str
```

### `std/x509.qma`

X.509 解析 + P-256 验签 + 证书链/有效期/域名校验

```quelmara
/// TBSCertificate 的原始 DER 字节（验签时对它做哈希）
fn x509_tbs(cert: str) -> str
/// 签名算法 OID（原始字节，如 ecdsa-with-SHA256 = 1.2.840.10045.4.3.2）
fn x509_sig_alg_oid(cert: str) -> str
/// SPKI 里的公钥算法 OID（第二个 OID，如 prime256v1）
fn x509_curve_oid(cert: str) -> str
/// P-256 公钥：返回 64 字节 X||Y；非 P-256 或格式不对返回 ""
fn x509_pubkey(cert: str) -> str
/// P-384 公钥：返回 96 字节 X||Y；非 P-384 或格式不对返回 ""。
/// secp384r1 的 OID 是 1.3.132.0.34（v2.99：Let's Encrypt 现役链、
/// Google Trust Services、Sectigo E 系列都用它）。
fn x509_pubkey384(cert: str) -> str
/// 签名值：返回 96 字节 r||s（各左补到 48 字节，P-384 用）；格式不对返回 ""。
/// 与 x509_sig 的区别只是宽度——DER 里的 INTEGER 长度本来就是变长的。
fn x509_sig384(cert: str) -> str
/// P-384 证书自验证（自签根）
fn x509_verify_self_p384(cert: str) -> int
/// 签名值：返回 64 字节 r||s（各左补到 32 字节）；格式不对返回 ""
fn x509_sig(cert: str) -> str
/// 用证书自己的公钥验证它自己的签名（根证书 / 自签测试）。
/// 返回 1 = 签名有效且是 P-256 证书。
fn x509_verify_self_p256(cert: str) -> int
/// 颁发者 DN 的原始 DER 字节（v2.97 起公开：std/x509roots 建链按 DN 配对，
/// 与 x509_verify_chain 内部同口径——**逐字节比较，不做 RFC 4514 规范化**。
/// 代价是"同一实体不同 DN 编码"（如打印串大小写、UTF8String vs PrintableString）
/// 会配对失败；主流 CA 的跨签名链（USERTrust→AAA 那种）不受影响，因为比较的
/// 两侧本来就是逐字抄写的同一串。无扩展返回 ""。
fn x509_issuer(cert: str) -> str
/// 主题 DN 的原始 DER 字节（公开理由同 x509_issuer）。无扩展返回 ""。
fn x509_subject(cert: str) -> str
/// 证书有效期：[not_before, not_after]（Unix 秒）；解析失败返回空 vec。
/// 时间按 UTCTime/GeneralizedTime 都支持，调用方自己做区间判断。
fn x509_validity(cert: str) -> vec[int]
/// 在 [not_before, not_after] 内返回 1
fn x509_time_valid(cert: str, now: int) -> int
/// basicConstraints（2.5.29.19）→ CA 位。无扩展/解析失败返回 0。
/// v2.97 起公开：std/x509roots 的根自验证与调用方筛选都要用。
fn x509_is_ca(cert: str) -> int
/// subjectAltName（2.5.29.17）里的 DNS 名列表；没有扩展返回空 vec。
/// 通配符（`*.example.com`）原样返回，匹配规则由调用方决定。
fn x509_san(cert: str) -> vec[str]
/// 证书是否覆盖该主机名：逐个 SAN 比对，`*.example.com` 只匹配一级子域；任一命中返回 1。
/// 只看 SAN，不回退 CN。
fn x509_host_ok(cert: str, host: str) -> int
/// 验证 leaf（可选 intermediates，按 leaf→root 顺序）到 anchor。
/// host 非空时额外校验 SAN；now 是 Unix 秒。
/// 返回 1 = 通过，0 = 失败。
fn x509_verify_chain(leaf: str, inter: vec[str], anchor: str, host: str, now: int) -> int
/// RSA 模数（大端、去前导 0）；非 RSA 返回 ""
fn x509_rsa_pub(cert: str) -> str
/// RSA 公钥指数（通常 65537）
fn x509_rsa_exp(cert: str) -> int
```

### `std/x509roots.qma`

内置 TLS 根证书库（12 个主流根 + 按 DN 配锚 + 一键验证到表内锚；v2.97）

```quelmara
/// 表内根证书数量。
fn x509_roots_count() -> int
/// 第 i 个根的 DER（原始字节）。越界返回 ""。
fn x509_root_at(i: int) -> str
/// 按主题 DN（`x509_subject` 的原始 DER）查根；没有返回 -1。
fn x509_root_find(subject_dn: str) -> int
/// 离 `cert` 最近的受信锚：按 issuer DN 查表命中（跨签名桥不在这里找，
/// 桥证书应由调用方放进 intermediates）。没有返回 ""。
fn x509_trusted_anchor(cert: str) -> str
/// 一键验证：leaf + intermediates（leaf→根方向排序，不含根），锚**自动查表**
/// ——查"链尾证书的 issuer"：表里没有链上中间 CA 的根时，链尾的 issuer 才是
/// 真锚。host/now 语义同 x509_verify_chain。
/// 返回 1 = 通过；0 = 不通过（含"锚在表里但签名算法当前栈验不动"）。
fn x509_verify_stored(leaf: str, inter: vec[str], host: str, now: int) -> int
/// 根自验证：用**自己的公钥验自己的签名**。信任锚的"可信"本质是人工契约
/// （这张表被审过），密码学上能做的只有自证签名闭合——这就是那个闭合检查。
/// 1 = 通过；0 = 失败或当前栈不支持该根的签名算法（见文件头边界）。
fn x509_root_selfcheck(i: int) -> int
```
<!-- api:end -->

## 4. 关键库的边界

| 库 | 能做 | 不能做 |
|---|---|---|
| `std/http` | 服务端、keep-alive、流水线、`Content-Encoding: gzip` 协商、JSON/text/html 响应 | 客户端、路由/中间件、静态文件服务、MIME、cookie/session、multipart；`Transfer-Encoding: chunked` 请求体回 501 |
| `std/ws` | 服务端握手、帧收发、ping/close | 客户端、permessage-deflate |
| `std/json` | DOM 解析、builder、转义、代理对 | `to_json<T>`（无泛型/反射）；数字统一按原文保留 |
| `std/gzip` | 编码（DEFLATE + 固定 Huffman）、**解码（存储块 / 固定 / 动态 Huffman）**、CRC-32、gzip 头尾校验、**多 member 拼接流**（v1.32）、**zlib 容器 + adler32**（v1.32） | 无 zlib 预置字典（FDICT）；解码失败 fail-fast |
| `std/hex` | `hex_encode` / `hex_encode_upper` / `hex_decode` / `hex_decode_ok` / `hex_val` | 无 base32/base64url（base64url 用 `std/b64` 自行替换字符） |
| `std/math` | `sqrt`（牛顿，相对误差 <1e-15）、`cbrt`、`floor/ceil/round/trunc_f`、`powi`、`gcd/lcm/isqrt`、NaN/inf 判定 | 无 `exp/log/pow(x,y)/sin/cos`（需要超越函数库）；`floor` 等受 int64 范围限制 |
| `std/aes` | AES-128-GCM 加解密（FIPS/NIST 向量通过） | AES-256、AES-NI 加速 |
| `std/x25519` | X25519 标量乘 / 公钥生成 / 共享密钥（RFC 7748 向量全过） | 单次约 7 ms（约 100× 于优化过的 C）；无 X448、无 Ed25519 |
| `std/tls13` | HKDF（RFC 5869）、Expand-Label、key schedule、AEAD 记录封装、Finished 派生、记录/握手消息解析 | 不含网络 I/O；握手状态机见 `std/tls_client` |
| `std/tls_client` | ClientHello 构造、ServerHello 解析、服务器 flight 解密、Finished/CertificateVerify 验证、客户端 Finished 生成、应用流量密钥、`tls_verify_chain` 证书链入口 | 无 TCP 连接（网络层见 `std/tls_net`）；只支持 TLS1.3 + AES-128-GCM-SHA256 + x25519；**没有内置根证书库**，链验证需调用方给锚证书；RSA 验签返回 -1 |
| `std/tls_net` | `tls_connect` 建连并握手、`tls_send_app` / `tls_read_app` 收发应用数据、`tls_random` / `tls_recv_exact` | 只在 Windows（依赖 `tcp_connect`）；seq 由调用方维护，适合单次请求/响应；不校验证书 |
| `std/p256` | ECDSA-P256 验签（含无效曲线点防护）、曲线上点判定 | 只验签不签名；只支持 SHA-256 摘要与未压缩点；单次约 25 ms |
| `std/x509` | DER TLV、TBS/SPKI/签名提取、P-256 与 RSA 公钥解析、`x509_verify_chain`（链 + 有效期 + SAN，通配符只匹配一级）、`x509_is_ca` / `x509_san` / `x509_validity` | EC 只认 P-256 未压缩点；RSA 只认 PKCS#1 v1.5；不校验用途 / CRL / OCSP / 策略；无 P-384、Ed25519；无根证书库 |
| `std/sha256` | SHA-256、HMAC-SHA256 | SHA-NI 硬件加速（基础设施已就绪，本机 CPU 无该扩展） |
| `std/rsa` | PKCS#1 v1.5 与 PSS（SHA-256）验签，2048 位约几十毫秒 | 只验签；无 SHA-384/512；无密钥生成/签名；指数按 32 位 |
| `std/net` | 阻塞 TCP 服务端（`listen` v4 / `listen6` **双栈**）+ 客户端 `connect`（Windows 走系统 DNS，v4/v6 字面量与域名都行） | Linux 客户端未实现（`tcp_connect` 编译期报错）；`net_serve` reactor 仍只绑 v4；批量收发 |
| `std/net/addr` | IPv4/IPv6 字面量判定与解析（`ip_family` / `ip6_parse`）、RFC 5952 格式化（`ip6_format` / `ip4_format`）、fd 对端地址（`peer_raw` / `peer_ip` / `peer_port` / `addr_text`，`::ffff:a.b.c.d` 还原成点分） | 不解析域名（那是 `tcp_connect` 的活）；无 zone id（`%eth0`）；不做 `::a.b.c.d` 兼容地址归一 |
| `std/net/udp` | open/bind/sendto/recvfrom + 地址解析 | 可靠 UDP、批量收发、**IPv6**（`udp_sendto` 的地址是 u32 网络序） |
| `std/url` | scheme/host/port/path/query/fragment、query 取值、encode/decode | 规范化、相对路径解析 |
| `std/str` | find/split/join/trim/replace/大小写/补齐/slice | `str_format`（无可变参数）、正则；**UTF-8 语义见 `std/utf8`**（`str_*` 一律按字节） |
| `std/utf8` | 严格解码/编码/校验（RFC 3629）、字符数、按字符切片、码点序列 | 无 Unicode 规范化、无大小写折叠、无字符分类（标点/数字/字母） |
| `std/set` | `iset_*` / `sset_*`：add/has/del/len + 并/交/差 + to_vec | 无泛型 `set[T]`（map 的 V 只允许 int/str）；遍历顺序由哈希决定；**无 clear**（新建更快） |
| `std/deque` | 两端 O(1) 进出 + 自动扩容，句柄是不变地址（扩容只换内部块） | 只有 `int` 元素；无迭代器；无 insert/drain |
| `std/hash` | FNV-1a 32/64（缓存键、分片、采样） | 非密码学（要抗碰撞用 `std/sha256`）；无 MD5/CRC64 |
| `std/lru` | LRU 缓存：get/put/del 均摊 O(1)，满了淘汰最久未用，单句柄（自建开放寻址表 + 双向链表） | key 只有 `int`（字符串请先 `fnv1a64`，碰撞由调用方负责）；`lru_get` 未命中返回 -1，与真实值 -1 有歧义（用 `lru_has` 或 `lru_get_or`） |
| `std/cli` | `--k=v` / `--k v` / `-k v` / 布尔开关 / 位置参数 / 缺值回落默认 | 无子命令、无自动 usage、无环境变量回落；位置参数判定是启发式（见源码注释） |
| `std/b64` | 标准字母表（带填充）+ **base64url**（无填充，JWT/URL 用） | 无流式编码（整块进内存） |
| `std/sort` | `sort_int`（Lomuto 快排 + 小段插入）、`is_sorted` | 泛型比较器（函数值 ≤6 参限制） |
| `std/log` | 级别 + 启动毫秒时间戳 + `log_kv` 结构化字段 | stderr 通道切换、级别过滤、轮转 |
| `std/rand` | xorshift64*（`now_ns` 混合种子） | CSPRNG |

## 5. 命名陷阱

- `http_json(fd, status, body)` **不是** JSON 序列化——它只是把 `Content-Type` 设成
  `application/json`。序列化要用 `std/json` 的 builder。
- `gzip_hex(s)` 返回十六进制串，不是压缩结果；压缩用 `gzip_encode(s)`。
- `str_from_bytes(v)` 的参数是 `vec[int]`，不是 `vec[str]`。

## 6. 维护方式

本文件的 API 清单是**从源码生成的**，不要手改：

```bash
# 1) 重新生成 API 段（脚本见 tools/dev/gen_stdlib_doc.py）
python tools/dev/gen_stdlib_doc.py

# 2) 或手工复核某个模块
grep -n "^fn " std/json.qma
```

新增模块时，同步更新 §1 的模块总览表与生成脚本里的 `DESC` 表。
