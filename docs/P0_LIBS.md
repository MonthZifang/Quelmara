# P0 标准库交付说明（sha256 / str / url / json）

> 2026-10-21。对应 `docs/GAPS.md §3.2` 的"HTTP 可交付五件套"：**五件已交付四件**
> （JSON / 字符串 / URL / gzip），TLS 走到 Phase A 的 2/3（SHA-256、AES-GCM 已落地，X25519 与握手仍缺）。
> 全部用 Quelmara 自实现，零 Python/Node 运行时依赖；已进 PE 回归（`tests/t43`–`t46`，回归 96 → **100 项**）。

## 1. 交付清单

| 模块 | 行数 | 对外 API | 回归 |
|---|---|---|---|
| `std/sha256.qma` | ~660 | `sha256_str` `sha256_hex` `hmac_sha256_str` `hmac_sha256_hex` | `tests/t43_sha256.qma`（FIPS 180-4 + RFC 4231 五组向量） |
| `std/str.qma` | ~430 | 见 §3（26 个函数） | `tests/t44_str.qma`（含 820KB 拆分/拼接压力形状） |
| `std/url.qma` | ~330 | 见 §4（14 个函数） | `tests/t45_url.qma`（含 IPv6、非法端口、往返） |
| `std/json.qma` | ~900 | 见 §5（解析 20 + 序列化 13） | `tests/t46_json.qma`（含错误路径、转义、嵌套、往返） |
| `std/gzip.qma` | ~380 | `crc32` `deflate_raw` `gzip_encode` `gzip_hex` | `tests/t47_gzip.qma` + `tests/gzip_interop.py`（Python zlib 逐字节解压） |
| `std/aes.qma` | ~600 | `aes128_expand` `aes128_encrypt_block` `aes128_decrypt_block` `gcm_encrypt` `gcm_decrypt` | `tests/t48_aes.qma`（FIPS-197 + NIST GCM case 2/3） |

验证口径：`python tests/run_win_tests.py` → **PASS=103 FAIL=0 SKIP=1**（SKIP 是 WSL 被沙箱拦）。

## 2. SHA-256 / HMAC-SHA256

```quelmara
import std.sha256

let hex = sha256_hex("abc")
// ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad

let mac = hmac_sha256_hex("Jefe", "what do ya want for nothing?")
// 5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843

let dig = sha256_str("payload")   // 32 字节摘要缓冲区（含 0 字节，不是 str）
// 用完 mem_free(dig, 32)
```

实现要点：
- 32 位运算全部 `& 0xFFFFFFFF` 截断（int 是 64 位，不截断会串位）；
- 轮常量用 **6 层判定树**（线性 64 个 `if` 会让每块多四千次比较）；
- 消息拷贝/补零走 `mem_copy` / `mem_zero`（不是逐字节循环）；
- HMAC 支持任意长度 key（>64 字节先取摘要），RFC 4231 case 1/2/6 全过。

**实测**（`bench/p0_bench.qma`，进程内 `now_ns`）：1 MiB 单遍 **71 ms ≈ 14.7 MB/s**。
这是"能用"的水平，不是"能打"的水平：每轮 ~68ns，主要成本是 64 轮标量运算 + 每块
调度表。要到 100 MB/s 级需要 8 字节加载 + 轮展开 + 常量表常驻寄存器（见 §9）。

## 3. 字符串工具（`str_` 前缀）

为什么必须带前缀：`import` 是**扁平合并**、无命名空间，`join` 已被任务句柄占用。

| 分类 | 函数 |
|---|---|
| 查找 | `str_find` `str_find_from` `str_rfind` `str_contains` `str_count` |
| 判定 | `str_starts_with` `str_ends_with` `str_eq_ci` |
| 裁剪 | `str_trim` `str_trim_left` `str_trim_right` |
| 变换 | `str_upper` `str_lower` `str_repeat` `str_pad_left` |
| 拆分 | `str_split` `str_split_n` `str_lines` |
| 拼接/替换 | `str_join` `str_replace` `str_replace_first` |
| 切片包装 | `str_slice` `str_left` `str_right` `str_strip_prefix` `str_strip_suffix` |

语义边界（写死，不做惊喜）：
- 全部按**字节**处理，不做 UTF-8 解码；大小写只对 ASCII A-Z/a-z 生效；
- 找不到返回 `-1`，空 needle 返回 `0`（与 `std/mem.buf_find` 一致）；
- `str_split(s, "")` 返回整体一项，不拆成单字符；
- `str_lines` 自动剥 `\r`（CRLF），末尾换行不产生空尾项。

**实测**：1 MiB 文本 `str_split` + `str_join` 往返 **30 ms**（65537 段）。

## 4. URL

```quelmara
import std.url

let u = "https://user@example.com:8443/a/b?q=hello%20world&x=1#frag"
url_scheme(u)              // "https"
url_host(u)                // "example.com"（去掉 userinfo；IPv6 保留 [::1]）
url_port(u)                // 8443（缺省/非法 -1，不 fail-fast）
url_path(u)                // "/a/b"
url_query(u)               // "q=hello%20world&x=1"
url_query_get(u, "q")      // "hello world"（已解码，同名取第一个）
url_decode("%E4%B8%AD")    // 原始 UTF-8 字节；'+' -> 空格
url_decode_path("a+b")     // "a+b"（路径不移 '+')
url_encode("a b")          // "a%20b"（unreserved 原样，其余大写 %XX）
url_encode_query("a b")    // "a+b"（表单语义）
url_join_query(base, k, v) // 自动选 ? 或 &
```

**实测**：解析 + 取端口 + 取 query × 100k = **103 ms**（≈1.0 µs/次）。
`url_port` 对 `http://h:abc/` 返回 -1 而不是退出进程——库函数不该替调用方决定死活。

## 5. JSON（DOM 式）

语言没有用户泛型、没有反射，所以**写不出 `to_json<T>`**。这里给的是显式树 API；
等泛型/trait 落地后可以在这一层之上加类型化编解码，底层表示不用改。

### 5.1 解析

```quelmara
import std.json

let d = json_parse("{\"name\":\"quelmara\",\"tags\":[\"a\"],\"n\":2}")
if json_ok(d) == false {
    eprint(json_error_pos(d))       // 1-based 字节偏移
    return
}
let root = json_root(d)
let name = json_str(d, json_obj_get(d, root, "name"))
let tags = json_obj_get(d, root, "tags")
let first = json_str(d, json_arr_at(d, tags, 0))
```

| 函数 | 说明 |
|---|---|
| `json_parse(s) -> int` | 返回文档句柄；失败不 fail-fast，`json_ok` 为 false |
| `json_ok / json_error_pos / json_root` | 状态与根节点 |
| `json_type / json_is_null/bool/num/str/arr/obj` | 类型判定（tag：0–5） |
| `json_str / json_int / json_num_raw / json_bool` | 取值 |
| `json_arr_len / json_arr_at` | 数组 |
| `json_obj_len / json_obj_key / json_obj_val / json_obj_get` | 对象（保持源顺序） |

语义边界：
- 数字按**原始文本**保存（不丢精度）；`json_int` 取小数/指数**之前**的整数部分
  （`-2.75e2` → `-2`），要真值请用 `json_num_raw` 自己转 float；
- `\uXXXX` 处理 BMP 与常规代理对，孤立代理替换为 U+FFFD；
- 嵌套深度上限 **64**，超限报错而不是栈溢出；
- 对象键保持源顺序，`json_obj_get` 线性查找（小对象足够，大对象建议自建索引）。

### 5.2 序列化

```quelmara
let h = json_new(256)
json_begin_obj(h)
json_key_str(h, "name", "quelmara")
json_key_int(h, "ver", 1)
json_key_bool(h, "ok", true)
json_key_null(h, "none")
json_key(h, "tags")
json_begin_arr(h)
json_val_str(h, "a")
json_end_arr(h)
json_end_obj(h)
let out = json_done(h)      // {"name":"quelmara","ver":1,"ok":true,"none":null,"tags":["a"]}
```

逗号由 builder 自己管：每个层级维护 `count*2 + awaiting_value`，`json_key` 与
`json_val_*` 分工明确，不会多/少逗号。`json_escape(s)` 可单独用。

**实测**：92.9 KB / 2000 个对象的数组，解析 **4–11 ms**（≈8–23 MB/s），
遍历取 2000 个 `id` 并求和 **1 ms**。

## 6. gzip / DEFLATE（`std/gzip.qma`）

```quelmara
import std.gzip

let gz = gzip_encode(body)        // 完整 gzip 流（头 + deflate + CRC32 + ISIZE）
let raw = deflate_raw(body)       // 裸 DEFLATE（无 gzip 头）
let c = crc32(body)               // 0xCBF43926 for "123456789"
```

实现：
- **LZ77**：3 字节哈希（4096 桶）+ 链长 8 + 32 KB 窗口；匹配覆盖的位置全部入链；
- **固定 Huffman**（BTYPE=01）：字面量/长度码按 RFC 1951 §3.2.6 生成，码字逆序后写 LSB 位流；
- **CRC-32**：多项式 0xEDB88320，逐位实现（无查表，1 MiB 约 8M 次循环）。

**压缩实测**（`gzip_encode`，进程内计时）：

| 输入 | 输出 | 耗时 | 比率 |
|---|---|---|---|
| 1 MiB 高度重复 | 7,658 B | 117 ms | **137×** |
| 820 KB 英文句式重复 | 6,816 B | 90 ms | **120×** |
| 15 B 短文本 | 35 B | — | 2.3×（头开销占主导，所以 HTTP 层 <256B 不压） |

**互操作（唯一权威验收）**：`tests/gzip_interop.py` 用 Python `zlib.decompress(..., 16+MAX_WBITS)`
解压 7 个样本（空串 / 单字节 / 文本 / 重复 / 混合 / 含 0x00 0xFF 的二进制 / 671 KB 大输入），
**7/7 逐字节一致**。

**边界（写死）**：
- 只实现**编码**；解码需要 dynamic Huffman，留给 HTTP 客户端那一轮；
- 一次输出一个 block，不切分（超大输入注意内存）；
- 不追求压缩率：固定 Huffman 对文本 2–3×，对已压缩数据会轻微膨胀。

### 6.1 HTTP 接线

`std/http.qma` 新增：

| 函数 | 行为 |
|---|---|
| `http_accepts_gzip(fd)` | 读 `Accept-Encoding`，大小写不敏感找 `gzip` |
| `http_respond_gzip(fd, st, ctype, body)` | 压缩 + `Content-Encoding: gzip` + `Vary: Accept-Encoding` |
| `http_respond_auto(fd, st, ctype, body)` | 客户端支持**且** body ≥ 256 B 才压，否则原样 |
| `http_json_auto` / `http_html_auto` | 上面两个的便捷包装 |

端到端验证：`examples/http_gzip.qma` + `tests/gzip_http_test.py`
（真连 127.0.0.1:18080）——支持 gzip 时 **1420 B → 101 B** 且解压还原；
不支持时明文；`/small` 永远不压；三条全 PASS。

## 7. AES-128-GCM（`std/aes.qma`）

```quelmara
import std.aes

let sealed = gcm_encrypt(key16, iv12, aad, plain)   // 密文 || 16B tag
let plain2 = gcm_decrypt(key16, iv12, aad, sealed)  // tag 不匹配返回 ""
```

实现：
- **AES-128** 分组加解密（10 轮，密钥扩展 176 B）；
- **GCM**：H = E(K,0)、J0 = IV||0^31||1、CTR 加密、GHASH（GF(2^128) 逐位乘法，128 次/块）、
  tag = E(K,J0) ⊕ S；
- **S-box 不写字面量表**：`"\xNN"` 高位字节有已知误编译（见 §8），改为运行时用
  GF(2^8) 对数/指数表求逆 + 仿射变换生成，缓存到 `static_word(12)`（0–11 归协议库）。

**向量**（`tests/t48_aes.qma` 全过）：
- FIPS-197 C.1：`000102…0f` / `001122…ff` → `69c4e0d86a7b0430d8cdb78070b4c55a`；
- NIST GCM case 2（K/P/IV 全零）→ `C=0388dace…`、`T=ab6e47d4…`；
- NIST GCM case 3（带 20 B AAD、60 B 明文）→ 密文与 tag 全等；
- 另测：往返、篡改 1 bit 必须返回空、AAD 不匹配必须返回空。

**性能现状**：GHASH 是逐位实现，**只适合握手与短消息**；大量数据要先把
GF 乘法换成 4-bit 表、AES 换成 T-tables（见 `docs/TLS.md` Phase A 备注）。

## 8. 写库时抓出的编译器 bug（比库更重要）

写库时被误编译拦了三次，**v1.8 已全部修掉**，夹具转正为 `tests/t53_regress.qma`：

| # | 现象 | 最小复现 | 规避 |
|---|---|---|---|
| 1 | 循环内 `substr` 的长度来自**调用结果**、结果又 push 进 `vec[str]` → 越界/错串（`--no-opt` 正常） | 已修（栈偏移当寄存器号） | 现在无需规避 |
| 2 | `"\xNN"`（≥0x80）被当 Unicode 码点再 UTF-8 编码 | `b2_hex_literal.qma`（`"\xe4"` → 2 字节） | 用 `chr()` 构造原始字节 |
| 3 | 循环内**一个表达式里两次调用 + 下标**（`f(s[2i])*16 + f(s[2i+1])`）→ 每个字节 +1 | 已修（同 #1） | 现在无需规避 |

另有两个**自己踩的坑**（已写进代码注释，值得反复看）：
- `mem_load64/store64` 的偏移是**槽索引（×8）**，不是字节偏移——我一度写成字节偏移，
  直接写穿 88 字节的 doc 块、污染堆，崩溃点随机漂移，差点误判成编译器 bug；
- `vec` 句柄经 `int` 参数/返回值传递会丢类型标签，`v.push` 直接报"不支持方法"；
  句柄跨函数要用 `vec[int]` 形参/返回类型，或存进 `mem` 后用 `vec[int]` 返回类型取回。

**结论**：看到"随机位置段错误"，先查自己的越界写；只有最小化到 30 行内仍复现，
再认定编译器 bug。

## 9. 未做与下一步

| 项 | 状态 | 说明 |
|---|---|---|
| gzip 解码（inflate） | ❌ | 编码已完成；解码要 dynamic Huffman，留给 HTTP 客户端轮次 |
| TLS 握手 / X25519 / X.509 | ❌ | Phase A 的 SHA-256 与 AES-GCM 已完成；X25519 需要 255 位域算术（先做 `std/u128`） |
| 文件系统最小集 | ❌ | `fs_exists/size/mkdir/listdir/remove/rename/append` 需要编译器内建（winapi + raw syscall） |
| 时间最小集 | ❌ | `now_ms`（wall clock）+ `sleep_ms` + `time_iso8601`，同上 |
| SHA-256 提速 | 🟡 | 目标 100 MB/s：8 字节加载、轮展开、常量表避免分支 |
| GCM 提速 | 🟡 | GHASH 逐个 128 次位运算；换 4-bit 表 + AES T-tables 才有吞吐 |
| gzip 提速 | 🟡 | 当前 ~9 MB/s；CRC 查表 + 更长匹配链可到 30 MB/s 级 |
| JSON 大文档 | 🟡 | `json_obj_get` 线性；>100 键建议加哈希索引（或等 `map[str]int` 之外的值类型） |
| JSON 浮点 | 🟡 | 只有 `json_num_raw`；`to_float` 可用但无 `strtod` 精度保证 |
