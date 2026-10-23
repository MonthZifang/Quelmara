# v1.78 — UUID `std/uuid`

- 日期：2026-10-23
- 任务：标准库补 UUID。`std/session` 之前只能生成 `s1`/`s2` 这种可枚举的 sid，
  请求 id / 幂等键也没东西可用。
- 影响面：标准库（`std/uuid.qma`，全部用 Quelmara 写）、测试、文档
- 注：v1.75（调试器）、v1.77（`@derive`）被另一条轨占用，本版顺延为 1.78

## 新增 API

| 函数 | 说明 |
|---|---|
| `uuid_v4()` | 128 位随机，按 RFC 4122 打版本位（第 6 字节高 4 位 = 0100）与变体位（第 8 字节高 2 位 = 10），小写带连字符 |
| `uuid_nil()` | 全零 UUID |
| `uuid_valid(s)` | 长度 36、连字符在 8/13/18/23、其余十六进制（大小写都收） |
| `uuid_version(s)` | 读版本号（1..5）；非法返回 -1 |
| `uuid_variant_ok(s)` | 变体位是否为 `10xx`（8/9/a/b） |

## 实现要点

- **两次 `rand_next()` 拼 128 位**：`std/rand` 是 xorshift，一次给 64 位；
  低字节用 `(x >> (i*8)) & 0xFF` 取，负数右移是算术移位，靠 `& 0xFF` 兜住。
- **版本/变体位是"改写"不是"拼接"**：`bytes[6] = (b & 0x0F) | 0x40`、
  `bytes[8] = (b & 0x3F) | 0x80`——先清位再置位，避免把随机位污染成非法组合。
- **校验按位置判**：长度 36 后逐个字符看"是不是连字符位"，比 split 更直接，
  也天然拒绝 `_` 之类分隔符。
- **十六进制大小写都收**：`uuid_valid` 只认字符集，不强制小写（客户端常发大写）。

## 改动

| 文件 | 改了什么 |
|---|---|
| `std/uuid.qma` | **新增**：5 个公开函数 + 4 个内部辅助（nibble/hex 转换、字节格式化） |
| `tests/t115_uuid.qma` | **新增**：格式与位域、64 个唯一性、校验十种（空/短/长/无连字符/位置错/非十六进制/大写）、v1/v4/v5 版本、变体 10xx 与非 10xx |
| `tests/run_win_tests.py` | 注册 `t115_uuid` |
| `tools/dev/gen_stdlib_doc.py` | DESC 登记 |
| `docs/03-stdlib.md` | 重新生成：57 个模块 / 379 个公开函数 |
| `docs/06-status.md` | 回归数字 |
| `tools/stage0/qlm_cli.py` | VERSION → 1.78.0 |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/t115_uuid.qma` | 30 条断言全过（含 64 个 UUID 两两不重复） |
| `python tests/run_win_tests.py` | PASS=219 FAIL=0 SKIP=1（含另一条轨 `@derive` 新增用例） |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（57 模块 / 379 公开函数） |
| 四道门禁 | 全 PASS |

## 已知边界 / 遗留

- **不是密码学随机**：`std/rand` 是 xorshift，做标识够用，做密钥/令牌不行
  （会话令牌建议再加一层 HMAC，需要 `std/hash` + 密钥，另开一版）。
- 只生成 v4；v1（时间）/v5（命名空间哈希）没做。
- 不做 UUID 到 16 字节的二进制编解码（`uuid_bytes` / `uuid_from_bytes`）——
  等有二进制协议需求再加。
