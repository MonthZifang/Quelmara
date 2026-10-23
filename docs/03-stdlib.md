# 标准库

标准库全部是 **Quelmara 源码**（`std/*.qma`），无第三方运行时依赖。`import` 时按需合并，
未用到的函数由全局 DCE 剔除（`QLM_NO_DCE=1` 可关）。

> API 清单由源码自动提取，只列**公开函数**（不带 `_` 前缀）。私有函数是内部实现细节，不承诺稳定。
> 重新生成：见本文件末尾「维护方式」。

## 1. 模块总览

47 个模块，**323 个公开函数**（另有 481 个内部函数）

| 模块 | 一句话 | 公开 / 全部 |
|---|---|---|
| `std/core` | `abs` / `max2` / `min2` / `pow2k` | 4 / 4 |
| `std/mem` | slab 分配、fd 表、缓冲、对象池 | 30 / 30 |
| `std/str` | 查找/切分/拼接/大小写/补齐 | 26 / 30 |
| `std/url` | URL 解析、query 取值、编码解码 | 12 / 18 |
| `std/json` | DOM 解析 + builder | 39 / 84 |
| `std/gzip` | DEFLATE 编码 + **inflate 解码** + crc32 | 6 / 29 |
| `std/hex` | 十六进制编解码（v1.19） | 5 / 5 |
| `std/math` | sqrt/cbrt/取整/powi/gcd（v1.19） | 21 / 21 |
| `std/sha1` | SHA-1（WS 握手用） | 5 / 5 |
| `std/sha256` | SHA-256 + HMAC-SHA256 | 11 / 11 |
| `std/rsa` | RSA PKCS#1 v1.5 / PSS 验签（SHA-256） | 2 / 12 |
| `std/aes` | AES-128-GCM（T-table 加密 + GHASH 4-bit 表） | 6 / 33 |
| `std/x25519` | X25519 密钥交换（RFC 7748，TLS ECDHE 地基） | 3 / 21 |
| `std/tls13` | TLS 1.3 密钥调度 + AEAD 记录层 + 记录/握手解析（v1.21/24） | 29 / 29 |
| `std/tls_client` | TLS 1.3 客户端握手核心 + 证书链入口（v1.24/26） | 9 / 13 |
| `std/tls_net` | TLS 1.3 网络层：TCP 建连 + 握手 + 应用数据（v1.25，Windows） | 5 / 5 |
| `std/p256` | NIST P-256 域运算 + ECDSA 验签（v1.22） | 2 / 45 |
| `std/x509` | X.509 解析 + P-256/RSA 验签 + 链/有效期/域名校验（v1.23/26/27） | 23 / 34 |
| `std/b64` | base64 编解码 | 5 / 5 |
| `std/http` | HTTP/1.1 服务端 | 33 / 40 |
| `std/ws` | WebSocket 服务端（RFC 6455） | 14 / 24 |
| `std/sse` | Server-Sent Events | 17 / 20 |
| `std/net` | 阻塞 TCP 便捷层（服务端 + 客户端 connect） | 7 / 7 |
| `std/net/core` | 连接槽位层（640 B/连接） | 18 / 18 |
| `std/net/udp` | UDP 封装 + 地址解析 | 3 / 3 |
| `std/ds` | RingBuf + MinHeap | 10 / 10 |
| `std/serialize` | LEB128 varint + 定长 + 帧 | 10 / 10 |
| `std/sync` | 自旋锁 / Treiber 栈 / WaitGroup | 10 / 10 |
| `std/rand` | xorshift64* | 4 / 5 |
| `std/sort` | 快排 + 有序性检查 | 2 / 5 |
| `std/log` | 分级日志 + 结构化字段 + 级别过滤 | 6 / 7 |
| `std/time` | `now_ms` / `sleep_ms` 便捷层 | 2 / 2 |
| `std/timer` | 轮询式定时器 | 4 / 4 |

## 2. 用法约定

```quelmara
import std.json
import std.http
```

- 每个模块一个文件，函数用**模块前缀**防冲突（`http_` / `ws_` / `str_` / `url_` …）——
  因为 `import` 是扁平合并，没有命名空间。
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
fn aes128_expand(key: str, rk: int) -> int
fn aes128_encrypt_block(inp: int, out: int, rk: int) -> int
fn _aes128_encrypt_block_fast(inp: int, out: int, rk: int) -> int
fn _aes128_encrypt_block_ni(inp: int, out: int, rk: int) -> int
fn aes128_decrypt_block(inp: int, out: int, rk: int) -> int
fn _gf_mul(x: int, h: int, out: int) -> int
fn _ghash_table(h: int, t: int) -> int
fn _gf_mul_t(x: int, t: int, out: int) -> int
fn gcm_encrypt(key: str, iv: str, aad: str, plain: str) -> str
fn gcm_decrypt(key: str, iv: str, aad: str, sealed: str) -> str
```

### `std/b64.qma`

base64 编解码

```quelmara
fn b64_encode(p: int, n: int) -> str
fn b64_dec_max(s: str) -> int
fn b64_decode_into(s: str, out: int) -> int
fn b64url_encode(p: int, n: int) -> str
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
fn cli_count() -> int
fn cli_at(i: int) -> str
fn cli_has(name: str) -> bool
fn cli_str(name: str, def: str) -> str
fn cli_int(name: str, def: int) -> int
fn cli_positionals() -> vec[str]
```

### `std/core.qma`

标量小工具

```quelmara
// 无公开函数
```

### `std/crc64.qma`

CRC-64/XZ（ECMA-182 反射多项式，xz/zlib 容器的 64 位校验）

```quelmara
/// CRC-64/XZ 校验值（64 位；以补码整数返回，>2^63 时为负）
fn crc64(s: str) -> int
/// CRC-64/XZ 十六进制（16 位小写）
fn crc64_hex(s: str) -> str
```

### `std/deque.qma`

双端队列（两端 O(1) + 自动扩容）

```quelmara
fn dq_new(cap: int) -> int
fn dq_len(d: int) -> int
fn dq_cap(d: int) -> int
fn dq_push_back(d: int, v: int) -> int
fn dq_push_front(d: int, v: int) -> int
fn dq_pop_front(d: int) -> int
fn dq_pop_back(d: int) -> int
fn dq_peek_front(d: int) -> int
fn dq_peek_back(d: int) -> int
fn dq_get(d: int, i: int) -> int
fn dq_set(d: int, i: int, v: int) -> int
fn dq_clear(d: int) -> int
fn dq_free(d: int) -> int
```

### `std/ds.qma`

环形缓冲与二叉最小堆

```quelmara
// 无公开函数
```

### `std/gen.qma`

泛型算法库（min/max/clamp/dist/contains/index_of/reverse，调用点推导单态化）

```quelmara
// 无公开函数
```

### `std/gzip.qma`

DEFLATE 编码 + gzip 包装 + CRC-32；v1.19 起含 inflate 解码

```quelmara
fn crc32(s: str) -> int
fn deflate_raw(s: str) -> str
fn gzip_encode(s: str) -> str
fn inflate_raw(s: str) -> str
fn gzip_decode(s: str) -> str
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
fn hex_encode(s: str) -> str
fn hex_encode_upper(s: str) -> str
fn hex_decode_ok(s: str) -> int
fn hex_decode(s: str) -> str
```

### `std/http.qma`

HTTP/1.1 服务端（keep-alive / 流水线 / 压缩协商）

```quelmara
// 无公开函数
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
/// 解析完整响应字节。buf 可以只含部分响应（complete=0）；传输层应持续
/// 拼接后再次调用。头未收全（无 \r\n\r\n）返回 status=-1。
fn httpc_parse_response(buf: str) -> HttpResponse
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

### `std/json.qma`

DOM 式 JSON 解析与 builder

```quelmara
fn json_parse(s: str) -> int
fn json_ok(d: int) -> bool
fn json_error_pos(d: int) -> int
fn json_root(d: int) -> int
fn json_is_null(d: int, node: int) -> bool
fn json_is_arr(d: int, node: int) -> bool
fn json_is_obj(d: int, node: int) -> bool
fn json_bool(d: int, node: int) -> bool
fn json_int(d: int, node: int) -> int
fn json_num_raw(d: int, node: int) -> str
fn json_str(d: int, node: int) -> str
fn json_arr_len(d: int, node: int) -> int
fn json_arr_at(d: int, node: int, i: int) -> int
fn json_obj_len(d: int, node: int) -> int
fn json_obj_key(d: int, node: int, i: int) -> str
fn json_obj_get(d: int, node: int, key: str) -> int
fn json_new(cap: int) -> int
fn json_begin_obj(h: int) -> int
fn json_end_obj(h: int) -> int
fn json_begin_arr(h: int) -> int
fn json_end_arr(h: int) -> int
fn json_key(h: int, k: str) -> int
fn json_val_str(h: int, v: str) -> int
fn json_val_bool(h: int, v: bool) -> int
fn json_val_null(h: int) -> int
fn json_key_str(h: int, k: str, v: str) -> int
fn json_key_int(h: int, k: str, v: int) -> int
fn json_key_bool(h: int, k: str, v: bool) -> int
fn json_done(h: int) -> str
```

### `std/log.qma`

分级日志（stdout）+ 结构化字段 + 级别过滤

```quelmara
fn log_set_level(lv: int) -> int
fn log_level() -> int
fn log_info(msg: str)
fn log_warn(msg: str)
fn log_error(msg: str)
fn log_kv(tag: str, msg: str, kv: vec[str]) -> int
```

### `std/lru.qma`

LRU 缓存（开放寻址表 + 双向链表，单句柄 O(1)）

```quelmara
fn lru_new(cap: int) -> vec[int]
fn lru_cap(st: vec[int]) -> int
fn lru_len(st: vec[int]) -> int
fn lru_has(st: vec[int], k: int) -> bool
fn lru_get(st: vec[int], k: int) -> int
fn lru_get_or(st: vec[int], k: int, def: int) -> int
fn lru_put(st: vec[int], k: int, v: int) -> int
fn lru_del(st: vec[int], k: int) -> int
fn lru_order(st: vec[int]) -> vec[int]
fn lru_peek(st: vec[int], k: int) -> int
```

### `std/math.qma`

浮点与整数数学（exp/log/pow/sin/cos/atan/双曲/hypot + sqrt/cbrt/取整/gcd）

```quelmara
fn fabs(x: f64) -> f64
fn fsign(x: f64) -> int
fn is_nan(x: f64) -> int
fn is_inf(x: f64) -> int
fn is_finite(x: f64) -> int
fn trunc_f(x: f64) -> f64
fn floor(x: f64) -> f64
fn ceil(x: f64) -> f64
fn round(x: f64) -> f64
fn powi(x: f64, n: int) -> f64
fn sqrt(x: f64) -> f64
fn cbrt(x: f64) -> f64
fn imin(a: int, b: int) -> int
fn imax(a: int, b: int) -> int
fn clamp_int(x: int, lo: int, hi: int) -> int
fn clamp_f(x: f64, lo: f64, hi: f64) -> f64
fn isqrt(n: int) -> int
fn gcd(a: int, b: int) -> int
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
fn md5_hex(s: str) -> str
```

### `std/mem.qma`

slab 分配 / fd 表 / 缓冲 / 对象池

```quelmara
fn slab_new(cap: int, slot_words: int) -> int
fn slab_alloc(h: int) -> int
fn slab_free(h: int, idx: int) -> int
fn slab_ptr(h: int, idx: int) -> int
fn slab_cap(h: int) -> int
fn fdtab_new(cap: int) -> int
fn fdtab_put(h: int, fd: int, slot: int) -> int
fn fdtab_get(h: int, fd: int) -> int
fn fdtab_del(h: int, fd: int) -> int
fn fdtab_len(h: int) -> int
fn buf_new(cap: int) -> int
fn buf_len(h: int) -> int
fn buf_put_str(h: int, s: str) -> int
fn buf_str(h: int) -> str
fn buf_find(h: int, from: int, needle: str) -> int
fn buf_find_head_end(h: int) -> int
fn buf_find_ci(h: int, from: int, needle: str) -> int
fn pool_new(block_words: int, capacity: int) -> int
fn pool_alloc(h: int) -> int
fn pool_free(h: int, p: int) -> int
fn pool_empty(h: int) -> bool
```

### `std/net.qma`

阻塞 TCP 便捷层

```quelmara
fn listen(port: int) -> int
fn accept(fd: int) -> int
fn send(conn: int, data: str) -> int
fn recv(conn: int, cap: int) -> str
fn close_conn(fd: int)
fn serve(port: int, backlog: int,
```

### `std/net/core.qma`

连接槽位层（IOCP reactor 的底座）

```quelmara
// 无公开函数
```

### `std/net/udp.qma`

UDP 封装与地址解析

```quelmara
fn udp_send_str(fd: int, ip: str, port: int, data: str) -> int
```

### `std/p256.qma`

NIST P-256 域运算 + ECDSA 验签（TLS 证书签名）

```quelmara
fn p256_on_curve(pub_x: str, pub_y: str) -> int
fn ecdsa_p256_verify(pub_x: str, pub_y: str, hash: str, r_sig: str, s_sig: str) -> int
```

### `std/rand.qma`

xorshift64* 伪随机

```quelmara
fn rand_seed(s: int)
fn rand_next() -> int
fn rand_below(n: int) -> int
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

### `std/rsa.qma`

RSA PKCS#1 v1.5 / PSS 验签（SHA-256，证书链与 TLS 用）

```quelmara
fn rsa_verify_pkcs1_sha256(n: str, e: int, sig: str, hash: str) -> int
fn rsa_verify_pss_sha256(n: str, e: int, sig: str, hash: str, salt_len: int) -> int
```

### `std/serialize.qma`

LEB128 varint / 定长整数 / 长度前缀帧

```quelmara
// 无公开函数
```

### `std/set.qma`

集合 set[int] / set[str]（map 支撑，含交并差）

```quelmara
fn iset_new(cap: int) -> map[int]int
fn iset_add(s: map[int]int, v: int) -> int
fn iset_has(s: map[int]int, v: int) -> bool
fn iset_del(s: map[int]int, v: int) -> int
fn iset_len(s: map[int]int) -> int
fn iset_to_vec(s: map[int]int) -> vec[int]
fn iset_union_into(dst: map[int]int, src: map[int]int) -> int
fn iset_isect(a: map[int]int, b: map[int]int) -> vec[int]
fn iset_diff(a: map[int]int, b: map[int]int) -> vec[int]
fn sset_new(cap: int) -> map[str]int
fn sset_add(s: map[str]int, v: str) -> int
fn sset_has(s: map[str]int, v: str) -> bool
fn sset_del(s: map[str]int, v: str) -> int
fn sset_len(s: map[str]int) -> int
```

### `std/sha1.qma`

SHA-1

```quelmara
fn sha1_hex(s: str) -> str
```

### `std/sha256.qma`

SHA-256 + HMAC-SHA256

```quelmara
fn sha256_str(s: str) -> int
fn sha256_hex(s: str) -> str
fn hmac_sha256_str(key: str, msg: str) -> int
fn hmac_sha256_hex(key: str, msg: str) -> str
```

### `std/sha512.qma`

SHA-512 / SHA-384（变体 IV 复用压缩函数）+ HMAC-SHA512

```quelmara
/// SHA-512 摘要缓冲区（64 字节，大端，含 0 字节不能当 str；用完 mem_free(d, 64)）
fn sha512_str(s: str) -> int
/// SHA-512 十六进制（128 位小写）
fn sha512_hex(s: str) -> str
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
fn sort_int(v: vec[int])
fn is_sorted(v: vec[int]) -> int
```

### `std/sse.qma`

Server-Sent Events 服务端

```quelmara
// 无公开函数
```

### `std/str.qma`

字符串工具集

```quelmara
fn str_find(s: str, needle: str) -> int
fn str_find_from(s: str, from: int, needle: str) -> int
fn str_rfind(s: str, needle: str) -> int
fn str_contains(s: str, needle: str) -> bool
fn str_starts_with(s: str, p: str) -> bool
fn str_ends_with(s: str, p: str) -> bool
fn str_count(s: str, needle: str) -> int
fn str_trim_left(s: str) -> str
fn str_trim_right(s: str) -> str
fn str_trim(s: str) -> str
fn str_upper(s: str) -> str
fn str_lower(s: str) -> str
fn str_eq_ci(a: str, b: str) -> bool
fn str_repeat(s: str, n: int) -> str
fn str_join(parts: vec[str], sep: str) -> str
fn str_split(s: str, sep: str) -> vec[str]
fn str_split_n(s: str, sep: str, max_parts: int) -> vec[str]
fn str_lines(s: str) -> vec[str]
fn str_replace(s: str, from: str, to: str) -> str
fn str_replace_first(s: str, from: str, to: str) -> str
fn str_slice(s: str, lo: int, hi: int) -> str
fn str_left(s: str, n: int) -> str
fn str_right(s: str, n: int) -> str
fn str_strip_prefix(s: str, p: str) -> str
fn str_strip_suffix(s: str, p: str) -> str
fn str_pad_left(s: str, width: int, pad: str) -> str
```

### `std/sync.qma`

自旋锁 / Treiber 无锁栈 / WaitGroup

```quelmara
fn mutex_new() -> int
fn mutex_lock(m: int)
fn mutex_unlock(m: int)
fn stack_new() -> int
fn stack_push(s: int, v: int)
fn stack_pop(s: int) -> int
fn wg_new() -> int
fn wg_add(w: int, n: int)
fn wg_done(w: int)
fn wg_wait(w: int)
```

### `std/time.qma`

时间便捷层

```quelmara
// 无公开函数
```

### `std/timer.qma`

轮询式定时器（MinHeap 驱动）

```quelmara
// 无公开函数
```

### `std/tls13.qma`

TLS 1.3 密钥调度（HKDF-Expand-Label）+ AEAD 记录层

```quelmara
fn tls_hash(s: str) -> str
fn hkdf_extract(salt: str, ikm: str) -> str
fn hkdf_expand(prk: str, info: str, n: int) -> str
fn tls_derive_secret(secret: str, label: str, transcript_hash: str) -> str
fn tls_early_secret() -> str
fn tls_empty_hash() -> str
fn tls_handshake_secret(early: str, shared: str) -> str
fn tls_master_secret(handshake: str) -> str
fn tls_traffic_key(secret: str) -> str
fn tls_traffic_iv(secret: str) -> str
fn tls_finished_key(secret: str) -> str
fn tls_finished_verify_data(finished_key: str, transcript_hash: str) -> str
fn tls_nonce(iv: str, seq: int) -> str
fn tls_record(ctype: int, payload: str) -> str
fn tls_seal_record(key: str, iv: str, seq: int, ctype: int, plain: str) -> str
fn tls_open_record(key: str, iv: str, seq: int, sealed: str) -> str
fn tls_open_record_raw(key: str, iv: str, seq: int, sealed: str) -> str
fn tls_hs_msg(mtype: int, body: str) -> str
fn tls_u16(v: int) -> str
fn tls_u24(v: int) -> str
fn tls_record_parse(buf: str, pos: int) -> vec[int]
fn tls_hs_parse(buf: str, pos: int) -> vec[int]
fn tls_ext(etype: int, body: str) -> str
```

### `std/tls_client.qma`

TLS 1.3 客户端握手核心 + 证书链入口（RFC 8448 逐字节）

```quelmara
fn tls_client_err(code: str) -> TlsClientResult
fn tls_cert_verify_hash(transcript_hash: str) -> str
fn tls_ecdsa_sig_raw(sig: str) -> str
fn tls_client_hello(host: str, pub: str, rnd: str, sid: str) -> str
fn tls_client_handshake(priv: str, ch_record: str, server_bytes: str) -> TlsClientResult
fn tls_cert_count(r: TlsClientResult) -> int
fn tls_cert(r: TlsClientResult, i: int) -> str
```

### `std/tls_net.qma`

TLS 1.3 网络层：TCP 建连 + 握手 + 应用数据（Windows）

```quelmara
fn tls_connect(host: str, port: int) -> TlsClientResult
fn tls_send_app(r: TlsClientResult, seq: int, data: str) -> int
fn tls_read_app(r: TlsClientResult, seq: int) -> str
```

### `std/url.qma`

URL 解析 / query 取值 / 编码解码

```quelmara
fn url_decode(s: str) -> str
fn url_decode_path(s: str) -> str
fn url_encode(s: str) -> str
fn url_encode_query(s: str) -> str
fn url_scheme(u: str) -> str
fn url_host(u: str) -> str
fn url_port(u: str) -> int
fn url_path(u: str) -> str
fn url_query(u: str) -> str
fn url_fragment(u: str) -> str
fn url_query_get(u: str, key: str) -> str
fn url_join_query(base: str, key: str, val: str) -> str
```

### `std/utf8.qma`

UTF-8 解码/编码/严格校验（RFC 3629）

```quelmara
fn utf8_decode_at(s: str, i: int) -> int
fn utf8_valid(s: str) -> bool
fn utf8_encode(cp: int) -> str
fn utf8_count(s: str) -> int
fn utf8_byte_of_char(s: str, ci: int) -> int
fn utf8_slice(s: str, lo: int, hi: int) -> str
fn utf8_to_chars(s: str) -> vec[int]
```

### `std/ws.qma`

WebSocket 服务端（RFC 6455）

```quelmara
// 无公开函数
```

### `std/x25519.qma`

Curve25519 上的 X25519 密钥交换（RFC 7748，TLS ECDHE 地基）

```quelmara
fn x25519_clamp(k: str) -> str
fn x25519(k: str, u: str) -> str
fn x25519_base(k: str) -> str
```

### `std/x509.qma`

X.509 解析 + P-256 验签 + 证书链/有效期/域名校验

```quelmara
fn x509_tbs(cert: str) -> str
fn x509_sig_alg_oid(cert: str) -> str
fn x509_curve_oid(cert: str) -> str
fn x509_pubkey(cert: str) -> str
fn x509_sig(cert: str) -> str
fn x509_verify_self_p256(cert: str) -> int
fn x509_time_valid(cert: str, now: int) -> int
fn x509_host_ok(cert: str, host: str) -> int
fn x509_verify_chain(leaf: str, inter: vec[str], anchor: str, host: str, now: int) -> int
fn x509_rsa_pub(cert: str) -> str
fn x509_rsa_exp(cert: str) -> int
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
| `std/net` | 阻塞 TCP 服务端（listen/accept）+ 客户端 `connect`（Windows 走系统 DNS） | Linux 客户端未实现（`tcp_connect` 编译期报错）；IPv6、批量收发 |
| `std/net/udp` | open/bind/sendto/recvfrom + 地址解析 | 可靠 UDP、批量收发、IPv6 |
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
