# 标准库

标准库全部是 **Quelmara 源码**（`std/*.qma`），无第三方运行时依赖。`import` 时按需合并，
未用到的函数由全局 DCE 剔除（`QLM_NO_DCE=1` 可关）。

> API 清单由源码自动提取，只列**公开函数**（不带 `_` 前缀）。私有函数是内部实现细节，不承诺稳定。
> 重新生成：见本文件末尾「维护方式」。

## 1. 模块总览

31 个模块，**359 个公开函数**（另有 188 个 `_` 前缀的内部函数）。

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
| `std/aes` | AES-128-GCM | 6 / 26 |
| `std/x25519` | X25519 密钥交换（RFC 7748，TLS ECDHE 地基） | 3 / 21 |
| `std/tls13` | TLS 1.3 密钥调度 + AEAD 记录层（v1.21）+ 记录/握手解析（v1.24） | 28 / 28 |
| `std/tls_client` | TLS 1.3 客户端握手核心（RFC 8448 逐字节验证，v1.24） | 6 / 9 |
| `std/p256` | NIST P-256 域运算 + ECDSA 验签（v1.22） | 2 / 45 |
| `std/x509` | X.509 DER 解析 + P-256 自签/签发者验签（v1.23） | 11 / 12 |
| `std/b64` | base64 编解码 | 5 / 5 |
| `std/http` | HTTP/1.1 服务端 | 33 / 40 |
| `std/ws` | WebSocket 服务端（RFC 6455） | 14 / 24 |
| `std/sse` | Server-Sent Events | 17 / 20 |
| `std/net` | 阻塞 TCP 便捷层 | 6 / 6 |
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

AES-128-GCM：分组加密 + GHASH + CTR

```quelmara
fn aes128_expand(key: str, rk: int) -> int
fn aes128_encrypt_block(inp: int, out: int, rk: int) -> int
fn aes128_decrypt_block(inp: int, out: int, rk: int) -> int
fn ghash(h: int, data: int, n: int, out: int) -> int
fn gcm_encrypt(key: str, iv: str, aad: str, plain: str) -> str
fn gcm_decrypt(key: str, iv: str, aad: str, sealed: str) -> str
```

### `std/b64.qma`

base64 编解码

```quelmara
fn b64_char(v: int) -> int
fn b64_val(b: int) -> int
fn b64_encode(p: int, n: int) -> str
fn b64_dec_max(s: str) -> int
fn b64_decode_into(s: str, out: int) -> int
```

### `std/core.qma`

标量小工具

```quelmara
fn abs(x: int) -> int
fn max2(a: int, b: int) -> int
fn min2(a: int, b: int) -> int
fn pow2k(x: int, k: int) -> int
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

### `std/gzip.qma`

DEFLATE 编码 + gzip 包装 + CRC-32；v1.19 起含 inflate 解码

```quelmara
fn crc32(s: str) -> int
fn deflate_raw(s: str) -> str
fn gzip_encode(s: str) -> str
fn gzip_hex(s: str) -> str
fn inflate_raw(s: str) -> str
fn gzip_decode(s: str) -> str
```

### `std/hex.qma`

十六进制编解码

```quelmara
fn hex_val(c: int) -> int
fn hex_encode(s: str) -> str
fn hex_encode_upper(s: str) -> str
fn hex_decode_ok(s: str) -> int
fn hex_decode(s: str) -> str
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
fn json_parse(s: str) -> int
fn json_ok(d: int) -> bool
fn json_error_pos(d: int) -> int
fn json_root(d: int) -> int
fn json_type(d: int, node: int) -> int
fn json_is_null(d: int, node: int) -> bool
fn json_is_bool(d: int, node: int) -> bool
fn json_is_num(d: int, node: int) -> bool
fn json_is_str(d: int, node: int) -> bool
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
fn json_obj_val(d: int, node: int, i: int) -> int
fn json_obj_get(d: int, node: int, key: str) -> int
fn json_new(cap: int) -> int
fn json_escape_into(h: int, s: str) -> int
fn json_escape(s: str) -> str
fn json_begin_obj(h: int) -> int
fn json_end_obj(h: int) -> int
fn json_begin_arr(h: int) -> int
fn json_end_arr(h: int) -> int
fn json_key(h: int, k: str) -> int
fn json_val_str(h: int, v: str) -> int
fn json_val_int(h: int, v: int) -> int
fn json_val_bool(h: int, v: bool) -> int
fn json_val_null(h: int) -> int
fn json_val_raw(h: int, raw: str) -> int
fn json_key_str(h: int, k: str, v: str) -> int
fn json_key_int(h: int, k: str, v: int) -> int
fn json_key_bool(h: int, k: str, v: bool) -> int
fn json_key_null(h: int, k: str) -> int
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

### `std/math.qma`

浮点与整数数学（sqrt/cbrt/floor/ceil/round/powi/gcd）

```quelmara
fn fabs(x: f64) -> f64
fn fsign(x: f64) -> int
fn fmin(a: f64, b: f64) -> f64
fn fmax(a: f64, b: f64) -> f64
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
```

### `std/mem.qma`

slab 分配 / fd 表 / 缓冲 / 对象池

```quelmara
fn slab_new(cap: int, slot_words: int) -> int
fn slab_alloc(h: int) -> int
fn slab_free(h: int, idx: int) -> int
fn slab_ptr(h: int, idx: int) -> int
fn slab_cap(h: int) -> int
fn slab_slot_words(h: int) -> int
fn fdtab_new(cap: int) -> int
fn fdtab_hash(k: int) -> int
fn fdtab_put(h: int, fd: int, slot: int) -> int
fn fdtab_get(h: int, fd: int) -> int
fn fdtab_del(h: int, fd: int) -> int
fn fdtab_len(h: int) -> int
fn fdtab_cap(h: int) -> int
fn buf_new(cap: int) -> int
fn buf_ptr(h: int) -> int
fn buf_len(h: int) -> int
fn buf_cap(h: int) -> int
fn buf_reset(h: int) -> int
fn buf_put8(h: int, b: int) -> int
fn buf_put(h: int, src: int, n: int) -> int
fn buf_put_str(h: int, s: str) -> int
fn buf_str(h: int) -> str
fn buf_find(h: int, from: int, needle: str) -> int
fn buf_find_head_end(h: int) -> int
fn buf_lower8(b: int) -> int
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
fn udp_send_str(fd: int, ip: str, port: int, data: str) -> int
fn udp_loopback() -> int
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

### `std/sha1.qma`

SHA-1

```quelmara
fn sha1_rotl(x: int, n: int) -> int
fn sha1_load_block(block: int, w: int) -> int
fn sha1_block(state: int, block: int, w: int) -> int
fn sha1_str(s: str) -> int
fn sha1_hex(s: str) -> str
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
fn sha256_str(s: str) -> int
fn sha256_hex(s: str) -> str
fn hmac_key_block(key: str, blk: int) -> int
fn hmac_sha256_str(key: str, msg: str) -> int
fn hmac_sha256_hex(key: str, msg: str) -> str
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
fn tls_hash(s: str) -> str
fn tls_hmac(key: str, msg: str) -> str
fn hkdf_extract(salt: str, ikm: str) -> str
fn hkdf_expand(prk: str, info: str, n: int) -> str
fn hkdf_expand_label(secret: str, label: str, ctx: str, n: int) -> str
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
fn tls_aad(ctype: int, cipher_len: int) -> str
fn tls_seal(key: str, nonce: str, aad: str, plain: str) -> str
fn tls_open(key: str, nonce: str, aad: str, sealed: str) -> str
fn tls_record(ctype: int, payload: str) -> str
fn tls_seal_record(key: str, iv: str, seq: int, ctype: int, plain: str) -> str
fn tls_open_record(key: str, iv: str, seq: int, sealed: str) -> str
fn tls_hs_msg(mtype: int, body: str) -> str
fn tls_u16(v: int) -> str
fn tls_u24(v: int) -> str
fn tls_record_parse(buf: str, pos: int) -> vec[int]
fn tls_hs_parse(buf: str, pos: int) -> vec[int]
fn tls_ext(etype: int, body: str) -> str
```

### `std/tls_client.qma`

TLS 1.3 客户端握手核心（RFC 8448 轨迹逐字节验证）

```quelmara
fn tls_client_err(code: str) -> TlsClientResult
fn tls_cert_verify_hash(transcript_hash: str) -> str
fn tls_ecdsa_sig_raw(sig: str) -> str
fn tls_verify_cert_verify(cert_der: str, alg: int, sig: str, transcript_hash: str) -> int
fn tls_client_hello(host: str, pub: str, rnd: str, sid: str) -> str
fn tls_client_handshake(priv: str, ch_record: str, server_bytes: str) -> TlsClientResult
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
fn x25519_clamp(k: str) -> str
fn x25519(k: str, u: str) -> str
fn x25519_base(k: str) -> str
```

### `std/x509.qma`

X.509 证书解析（DER/ASN.1）+ P-256 自签/签发者验签（TLS 证书层）

```quelmara
fn x509_tlv(s: str, pos: int) -> vec[int]
fn x509_ok(t: vec[int]) -> int
fn x509_root(cert: str) -> vec[int]
fn x509_tbs(cert: str) -> str
fn x509_sig_alg_oid(cert: str) -> str
fn x509_curve_oid(cert: str) -> str
fn x509_spki_tlv(cert: str) -> vec[int]
fn x509_pubkey(cert: str) -> str
fn x509_sig(cert: str) -> str
fn x509_verify_self_p256(cert: str) -> int
fn x509_verify_with_p256(cert: str, issuer_pub: str) -> int
```
<!-- api:end -->

## 4. 关键库的边界

| 库 | 能做 | 不能做 |
|---|---|---|
| `std/http` | 服务端、keep-alive、流水线、`Content-Encoding: gzip` 协商、JSON/text/html 响应 | 客户端、路由/中间件、静态文件服务、MIME、cookie/session、multipart；`Transfer-Encoding: chunked` 请求体回 501 |
| `std/ws` | 服务端握手、帧收发、ping/close | 客户端、permessage-deflate |
| `std/json` | DOM 解析、builder、转义、代理对 | `to_json<T>`（无泛型/反射）；数字统一按原文保留 |
| `std/gzip` | 编码（DEFLATE + 固定 Huffman）、**解码（存储块 / 固定 / 动态 Huffman）**、CRC-32、gzip 头尾校验 | 多 member 流（一次只解第一个）；解码失败 fail-fast |
| `std/hex` | `hex_encode` / `hex_encode_upper` / `hex_decode` / `hex_decode_ok` / `hex_val` | 无 base32/base64url（base64url 用 `std/b64` 自行替换字符） |
| `std/math` | `sqrt`（牛顿，相对误差 <1e-15）、`cbrt`、`floor/ceil/round/trunc_f`、`powi`、`gcd/lcm/isqrt`、NaN/inf 判定 | 无 `exp/log/pow(x,y)/sin/cos`（需要超越函数库）；`floor` 等受 int64 范围限制 |
| `std/aes` | AES-128-GCM 加解密（FIPS/NIST 向量通过） | AES-256、AES-NI 加速 |
| `std/x25519` | X25519 标量乘 / 公钥生成 / 共享密钥（RFC 7748 向量全过） | 单次约 7 ms（约 100× 于优化过的 C）；无 X448、无 Ed25519 |
| `std/tls13` | HKDF（RFC 5869）、Expand-Label、key schedule、AEAD 记录封装、Finished 派生、记录/握手消息解析 | 不含网络 I/O；握手状态机见 `std/tls_client` |
| `std/tls_client` | ClientHello 构造、ServerHello 解析、服务器 flight 解密、Finished/CertificateVerify 验证、客户端 Finished 生成、应用流量密钥 | 无 TCP 连接（无 `tcp_connect`/DNS）；只支持 TLS1.3 + AES-128-GCM-SHA256 + x25519；不校验证书链/有效期/域名；RSA 验签返回 -1 |
| `std/p256` | ECDSA-P256 验签（含无效曲线点防护）、曲线上点判定 | 只验签不签名；只支持 SHA-256 摘要与未压缩点；单次约 25 ms |
| `std/x509` | DER TLV（≤3 字节长度）、TBSCertificate / SPKI / signatureValue 提取、`x509_verify_self_p256` 与 `x509_verify_with_p256` | 只认 ECDSA-P256 未压缩点；**不校验**有效期/域名/用途/链/CRL/OCSP；无 RSA、Ed25519、压缩点 |
| `std/sha256` | SHA-256、HMAC-SHA256 | SHA-NI 硬件加速（基础设施已就绪，本机 CPU 无该扩展） |
| `std/net` | 阻塞 TCP（IPv4 字面量） | 域名解析、IPv6、批量收发 |
| `std/net/udp` | open/bind/sendto/recvfrom + 地址解析 | 可靠 UDP、批量收发、IPv6 |
| `std/url` | scheme/host/port/path/query/fragment、query 取值、encode/decode | 规范化、相对路径解析 |
| `std/str` | find/split/join/trim/replace/大小写/补齐/slice | `str_format`（无可变参数）、UTF-8 语义、正则 |
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
