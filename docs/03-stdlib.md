# 标准库

标准库全部是 **Quelmara 源码**（`std/*.qma`），无第三方运行时依赖。`import` 时按需合并，
未用到的函数由全局 DCE 剔除（`QLM_NO_DCE=1` 可关）。

> API 清单由源码自动提取，只列**公开函数**（不带 `_` 前缀）。私有函数是内部实现细节，不承诺稳定。
> 重新生成：见本文件末尾「维护方式」。

## 1. 模块总览

41 个模块，**195 个公开函数**（另有 216 个 `_` 前缀的内部函数）。

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
fn ghash(h: int, data: int, n: int, out: int) -> int
```

### `std/b64.qma`

base64 编解码

```quelmara
fn b64_char(v: int) -> int
fn b64_val(b: int) -> int
fn b64url_char(v: int) -> int
fn b64url_val(b: int) -> int
```

### `std/cli.qma`

命令行 flag 解析（--k=v / --k v / -k v）

```quelmara
// 无公开函数
```

### `std/core.qma`

标量小工具

```quelmara
fn abs(x: int) -> int
fn max2(a: int, b: int) -> int
fn min2(a: int, b: int) -> int
fn pow2k(x: int, k: int) -> int
```

### `std/deque.qma`

双端队列（两端 O(1) + 自动扩容）

```quelmara
// 无公开函数
```

### `std/ds.qma`

环形缓冲与二叉最小堆

```quelmara
fn rb_new(cap: int) -> int
fn rb_count(rb: int) -> int
fn rb_cap(rb: int) -> int
fn rb_push(rb: int, v: int) -> int
fn rb_pop(rb: int) -> int
fn rb_peek(rb: int) -> int
fn heap_new(cap: int) -> vec[int]
fn heap_push(h: vec[int], key: int)
fn heap_peek(h: vec[int]) -> int
fn heap_pop(h: vec[int]) -> int
```

### `std/gen.qma`

泛型算法库（min/max/clamp/dist/contains/index_of/reverse，调用点推导单态化）

```quelmara
fn gen_min[T](a: T, b: T) -> T
fn gen_max[T](a: T, b: T) -> T
fn gen_clamp[T](v: T, lo: T, hi: T) -> T
fn gen_dist[T](a: T, b: T) -> T
fn gen_first[T](xs: vec[T]) -> T
fn gen_last[T](xs: vec[T]) -> T
fn gen_contains[T](xs: vec[T], v: T) -> bool
fn gen_index_of[T](xs: vec[T], v: T) -> int
fn gen_reverse[T](xs: vec[T])
```

### `std/gzip.qma`

DEFLATE 编码 + gzip 包装 + CRC-32；v1.19 起含 inflate 解码

```quelmara
fn gzip_hex(s: str) -> str
fn adler32(s: str) -> int
fn zlib_decode(s: str) -> str
```

### `std/hash.qma`

FNV-1a 32/64 非密码学哈希（缓存键 / 分片）

```quelmara
// 无公开函数
```

### `std/hex.qma`

十六进制编解码

```quelmara
fn hex_val(c: int) -> int
```

### `std/http.qma`

HTTP/1.1 服务端（keep-alive / 流水线 / 压缩协商）

```quelmara
fn http_serve(port: int, backlog: int, on_request: int) -> int
fn http_serve_max(port: int, backlog: int, on_request: int,
fn http_accepted() -> int
fn http_closed() -> int
fn http_reqs() -> int
fn http_bytes_in() -> int
fn http_bytes_out() -> int
fn http_on_connect(fd: int) -> int
fn http_on_close(fd: int) -> int
fn http_on_data(fd: int, data: str) -> int
fn http_respond_raw_parse_fail(fd: int) -> int
fn http_method(fd: int) -> str
fn http_path(fd: int) -> str
fn http_body_ptr(fd: int) -> int
fn http_body_len(fd: int) -> int
fn http_body(fd: int) -> str
fn http_header(fd: int, name: str) -> str
fn http_set_close(fd: int) -> int
fn http_reason(status: int) -> str
fn http_respond_ext(fd: int, status: int, ctype: str, extra: str,
fn http_respond(fd: int, status: int, ctype: str, body: str) -> int
fn http_respond_close(fd: int, status: int, ctype: str, body: str) -> int
fn http_text(fd: int, status: int, body: str) -> int
fn http_html(fd: int, status: int, body: str) -> int
fn http_json(fd: int, status: int, body: str) -> int
fn http_respond_raw(fd: int, status: int, extra: str, body: str) -> int
fn http_accepts_gzip(fd: int) -> bool
fn http_respond_gzip(fd: int, status: int, ctype: str, body: str) -> int
fn http_respond_auto(fd: int, status: int, ctype: str, body: str) -> int
fn http_json_auto(fd: int, status: int, body: str) -> int
fn http_html_auto(fd: int, status: int, body: str) -> int
fn http_not_found(fd: int) -> int
fn http_method_not_allowed(fd: int) -> int
```

### `std/json.qma`

DOM 式 JSON 解析与 builder

```quelmara
fn json_type(d: int, node: int) -> int
fn json_is_bool(d: int, node: int) -> bool
fn json_is_num(d: int, node: int) -> bool
fn json_is_str(d: int, node: int) -> bool
fn json_obj_val(d: int, node: int, i: int) -> int
fn json_escape_into(h: int, s: str) -> int
fn json_escape(s: str) -> str
fn json_val_int(h: int, v: int) -> int
fn json_val_raw(h: int, raw: str) -> int
fn json_key_null(h: int, k: str) -> int
```

### `std/log.qma`

分级日志（stdout）+ 结构化字段 + 级别过滤

```quelmara
// 无公开函数
```

### `std/lru.qma`

LRU 缓存（开放寻址表 + 双向链表，单句柄 O(1)）

```quelmara
// 无公开函数
```

### `std/math.qma`

浮点与整数数学（sqrt/cbrt/floor/ceil/round/powi/gcd）

```quelmara
fn fmin(a: f64, b: f64) -> f64
fn fmax(a: f64, b: f64) -> f64
```

### `std/md5.qma`

MD5（RFC 1321，仅兼容用途，不要用于密码）

```quelmara
fn md5_load_block(block: int, w: int) -> int
fn md5_block(state: int, block: int, w: int) -> int
fn md5_init(state: int) -> int
fn md5_str(s: str) -> int
```

### `std/mem.qma`

slab 分配 / fd 表 / 缓冲 / 对象池

```quelmara
fn slab_slot_words(h: int) -> int
fn fdtab_hash(k: int) -> int
fn fdtab_cap(h: int) -> int
fn buf_ptr(h: int) -> int
fn buf_cap(h: int) -> int
fn buf_reset(h: int) -> int
fn buf_put8(h: int, b: int) -> int
fn buf_put(h: int, src: int, n: int) -> int
fn buf_lower8(b: int) -> int
```

### `std/net.qma`

阻塞 TCP 便捷层

```quelmara
fn connect(host: str, port: int) -> int
```

### `std/net/core.qma`

连接槽位层（IOCP reactor 的底座）

```quelmara
fn conn_state_new(max_conns: int, slot_words: int) -> int
fn conn_max_conns(st: int) -> int
fn conn_accepted(st: int) -> int
fn conn_closed(st: int) -> int
fn conn_msgs(st: int) -> int
fn conn_bytes_in(st: int) -> int
fn conn_bytes_out(st: int) -> int
fn conn_lock() -> int
fn conn_unlock() -> int
fn conn_open(st: int, fd: int) -> int
fn conn_slot(st: int, fd: int) -> int
fn conn_close(st: int, fd: int) -> int
fn conn_buf_ptr(p: int) -> int
fn conn_buf_cap(st: int, p: int) -> int
fn conn_append(st: int, p: int, data: str) -> int
fn conn_shift(p: int, from: int) -> int
fn conn_send(st: int, fd: int, ptr: int, n: int) -> int
fn conn_send_str(st: int, fd: int, s: str) -> int
```

### `std/net/udp.qma`

UDP 封装与地址解析

```quelmara
fn udp_parse_ip(ip: str) -> int
fn udp_loopback() -> int
```

### `std/p256.qma`

NIST P-256 域运算 + ECDSA 验签（TLS 证书签名）

```quelmara
// 无公开函数
```

### `std/rand.qma`

xorshift64* 伪随机

```quelmara
// 无公开函数
```

### `std/rsa.qma`

RSA PKCS#1 v1.5 / PSS 验签（SHA-256，证书链与 TLS 用）

```quelmara
// 无公开函数
```

### `std/serialize.qma`

LEB128 varint / 定长整数 / 长度前缀帧

```quelmara
fn varint_put(v: int) -> str
fn varint_get(buf: str, off: int) -> int
fn put_u16le(w: int, off: int, v: int) -> int
fn put_u32le(w: int, off: int, v: int) -> int
fn put_u64le(w: int, off: int, v: int) -> int
fn get_u16le(buf: int, off: int) -> int
fn get_u32le(buf: int, off: int) -> int
fn get_u64le(buf: int, off: int) -> int
fn frame_put(payload: str) -> str
fn frame_get(buf: str, off: int) -> str
```

### `std/set.qma`

集合 set[int] / set[str]（map 支撑，含交并差）

```quelmara
fn sset_to_vec(s: map[str]int) -> vec[str]
fn sset_union_into(dst: map[str]int, src: map[str]int) -> int
fn sset_isect(a: map[str]int, b: map[str]int) -> vec[str]
```

### `std/sha1.qma`

SHA-1

```quelmara
fn sha1_rotl(x: int, n: int) -> int
fn sha1_load_block(block: int, w: int) -> int
fn sha1_block(state: int, block: int, w: int) -> int
fn sha1_str(s: str) -> int
```

### `std/sha256.qma`

SHA-256 + HMAC-SHA256

```quelmara
fn sha256_rotr(x: int, n: int) -> int
fn sha256_load_block(block: int, w: int) -> int
fn sha256_k(i: int) -> int
fn sha256_block(state: int, block: int, w: int) -> int
fn sha256_init(state: int) -> int
fn sha256_pad_and_hash(s: str) -> int
fn hmac_key_block(key: str, blk: int) -> int
```

### `std/sort.qma`

快速排序与有序性检查

```quelmara
// 无公开函数
```

### `std/sse.qma`

Server-Sent Events 服务端

```quelmara
fn sse_serve(port: int, backlog: int, on_sub: int) -> int
fn sse_serve_max(port: int, backlog: int, on_sub: int,
fn sse_accepted() -> int
fn sse_closed() -> int
fn sse_subs() -> int
fn sse_events_out() -> int
fn sse_on_connect(fd: int) -> int
fn sse_on_close(fd: int) -> int
fn sse_on_data(fd: int, data: str) -> int
fn sse_event_ext(fd: int, event: str, data: str, id: str) -> int
fn sse_event(fd: int, event: str, data: str) -> int
fn sse_data(fd: int, data: str) -> int
fn sse_event_id(fd: int, event: str, data: str, id: str) -> int
fn sse_retry(fd: int, ms: int) -> int
fn sse_comment(fd: int, text: str) -> int
fn sse_broadcast_ext(event: str, data: str, id: str) -> int
fn sse_broadcast(event: str, data: str) -> int
```

### `std/str.qma`

字符串工具集

```quelmara
// 无公开函数
```

### `std/sync.qma`

自旋锁 / Treiber 无锁栈 / WaitGroup

```quelmara
// 无公开函数
```

### `std/time.qma`

时间便捷层

```quelmara
fn now_ms() -> int
fn ms_str(ms: int) -> str
```

### `std/timer.qma`

轮询式定时器（MinHeap 驱动）

```quelmara
fn timer_after(ms: int) -> int
fn timer_cancel(id: int)
fn timer_poll() -> int
fn timer_pending() -> int
```

### `std/tls13.qma`

TLS 1.3 密钥调度（HKDF-Expand-Label）+ AEAD 记录层

```quelmara
fn tls_zeros(n: int) -> str
fn tls_hmac(key: str, msg: str) -> str
fn hkdf_expand_label(secret: str, label: str, ctx: str, n: int) -> str
fn tls_aad(ctype: int, cipher_len: int) -> str
fn tls_seal(key: str, nonce: str, aad: str, plain: str) -> str
fn tls_open(key: str, nonce: str, aad: str, sealed: str) -> str
```

### `std/tls_client.qma`

TLS 1.3 客户端握手核心 + 证书链入口（RFC 8448 逐字节）

```quelmara
fn tls_verify_cert_verify(cert_der: str, alg: int, sig: str, transcript_hash: str) -> int
fn tls_verify_chain(r: TlsClientResult, anchor: str, host: str, now: int) -> int
```

### `std/tls_net.qma`

TLS 1.3 网络层：TCP 建连 + 握手 + 应用数据（Windows）

```quelmara
fn tls_random(n: int) -> str
fn tls_recv_exact(fd: int, n: int) -> str
```

### `std/url.qma`

URL 解析 / query 取值 / 编码解码

```quelmara
// 无公开函数
```

### `std/utf8.qma`

UTF-8 解码/编码/严格校验（RFC 3629）

```quelmara
fn utf8_char_len(b: int) -> int
```

### `std/ws.qma`

WebSocket 服务端（RFC 6455）

```quelmara
fn ws_serve(port: int, backlog: int, on_open: int, on_message: int,
fn ws_serve_max(port: int, backlog: int, on_open: int, on_message: int,
fn ws_accepted() -> int
fn ws_closed() -> int
fn ws_msgs() -> int
fn ws_bytes_in() -> int
fn ws_bytes_out() -> int
fn ws_on_connect(fd: int) -> int
fn ws_on_close(fd: int) -> int
fn ws_on_data(fd: int, data: str) -> int
fn ws_send(fd: int, data: str) -> int
fn ws_send_bin(fd: int, data: str) -> int
fn ws_ping(fd: int, data: str) -> int
fn ws_close(fd: int, code: int) -> int
```

### `std/x25519.qma`

Curve25519 上的 X25519 密钥交换（RFC 7748，TLS ECDHE 地基）

```quelmara
// 无公开函数
```

### `std/x509.qma`

X.509 解析 + P-256 验签 + 证书链/有效期/域名校验

```quelmara
fn x509_tlv(s: str, pos: int) -> vec[int]
fn x509_ok(t: vec[int]) -> int
fn x509_root(cert: str) -> vec[int]
fn x509_spki_tlv(cert: str) -> vec[int]
fn x509_verify_with_p256(cert: str, issuer_pub: str) -> int
fn x509_issuer(cert: str) -> str
fn x509_subject(cert: str) -> str
fn x509_validity_raw(cert: str) -> str
fn x509_validity(cert: str) -> vec[int]
fn x509_is_ca(cert: str) -> int
fn x509_san(cert: str) -> vec[str]
fn x509_sig_bits(cert: str) -> str
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
