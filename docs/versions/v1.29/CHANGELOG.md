# v1.29 — mem_chr 内建（扫描 5.2×）+ 标准库红标翻绿

- 日期：2026-10-22
- 任务：性能优化为主、同时补齐 `07-gaps.md` §2 的红标（用户要求"黄标红标全部补齐"）
- 影响面：编译器（新内建 + 运行时）、标准库（5 个新模块 + b64 扩展）、基准、测试、文档

## 为什么先做 mem_chr

`07-gaps.md` §5 把"JSON memchr 化"列为性能专项，前置条件是"`memchr` / 找字符内建"。
查了一遍库层：`str_find` / `str_split` / `str_lines` / HTTP 头解析全是**逐字节**循环，
每次迭代一次 `load8` + 一次比较。这是最普适的扫描形态，一个内建能同时喂给四个调用方，
比单独改 JSON 划算。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 新增内建 `mem_chr(p, n, byte)` → 运行时 `__memchr`（8 字节 SWAR：`(x-0x01…) & ~x` 找零字节，命中字内再逐字节确认首匹配）；`__str_from_i64` 修 `INT64_MIN` 取负溢出 |
| `std/str.qma` | `str_find_from` 改"mem_chr 跳扫 + 候选比对"；`str_split` 单字节分隔符走 mem_chr；`str_lines` 用 mem_chr 定位 `\n` |
| `std/set.qma` | **新增**：`iset_*`（set[int]）/ `sset_*`（set[str]），add/has/del/len + 并/交/差/to_vec |
| `std/deque.qma` | **新增**：双端队列，两端 O(1)、自动扩容、句柄是不变地址（指针盒） |
| `std/utf8.qma` | **新增**：严格 UTF-8 解码/编码/校验（RFC 3629）、字符数、按字符切片、码点序列 |
| `std/hash.qma` | **新增**：FNV-1a 32/64（含按字节入口） |
| `std/cli.qma` | **新增**：`--k=v` / `--k v` / `-k v` / 布尔开关 / 位置参数 / 缺省回落 |
| `std/b64.qma` | 新增 `b64url_encode` / `b64url_decode_into`（无填充，JWT/URL 用） |
| `bench/find_bench.qma` | **新增**：旧实现与新实现同进程 A/B（miss / 命中密集 / 完整拆分三种形状） |
| `tests/t74_set_deque.qma` | **新增**：set 交并差 + deque 扩容/回绕/两端 |
| `tests/t75_utf8.qma` | **新增**：中文/emoji 正向 + 8 类非法序列（overlong/代理/超界/截断） |
| `tests/t76_codec.qma` | **新增**：FNV 官方向量 + base64url RFC 4648 向量 + 往返 + INT64_MIN |
| `tests/t77_cli.qma` | **新增**：带参数启动，逐行核对 13 项输出 |
| `tests/run_win_tests.py` | 注册 t74/t75/t76 + 新增 `[3d2] std/cli` 段（带参数） |
| `tools/dev/gen_stdlib_doc.py` | DESC 表补 5 个新模块，重新生成 `03-stdlib.md`（38 模块 / 435 公开函数） |
| `tools/stage0/qlm_cli.py` | `VERSION` 1.28.0 → **1.29.0** |

## 实现要点

- **SWAR 零字节检测**：`haszero(x) = (x - 0x0101010101010101) & ~x & 0x8080…`。
  SWAR 只回答"这个字里有目标字节"，**不回答是第几个**——所以命中字必须再逐字节确认，
  否则返回的是字内任意一个匹配，"首匹配"语义就丢了。`tests/t74`…`t76` 之外，
  `_memchr_probe` 曾用 8 个 in-word 位置逐一验证过这一点。
- **掩码不用 2^63**：`0x8080808080808080` 超出 int64 正区间，走有符号立即数在
  `and` 上实测算错（见 `07-gaps.md` §7.3），改成 `>>7 & 0x0101…` 效果等价且安全。
- **`INT64_MIN` 的 to_str**：`__str_from_i64` 原来先 `neg v, v`，而 `-(-2^63)` 溢出回自身，
  后续 `mod/div` 拿到负数，输出 20 个乱码字符。改成"取负后仍为负 → 直接写定值"。
- **deque 的句柄盒**：扩容会换状态块地址，若句柄就是状态块指针，调用方必须写
  `d = dq_push(d, v)`。改成 8 字节指针盒后句柄恒定，扩容只更新盒子里的指针。
- **set 没有 clear**：`map` 的方法只有 `set/get/has/del`（文档原来写 `put`，已一并修正）。
  `del` 也没有返回值，所以 `iset_del` 先 `has` 再 `del` 才能报"删没删到"。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=140 FAIL=0 SKIP=1**（v1.28 为 135） |
| `python tools/stage0/qlm_cli.py run bench/find_bench.qma --target win` | 未命中 2944→**558 µs**、命中密集 2543→**482 µs**（均 **5.2×**）；拆分 1.1 MB/20001 段 2057 µs |
| `python tools/stage0/qlm_cli.py run tests/t74_set_deque.qma --target win` | ok |
| `python tools/stage0/qlm_cli.py run tests/t75_utf8.qma --target win` | ok |
| `python tools/stage0/qlm_cli.py run tests/t76_codec.qma --target win` | ok |
| `build/t77_cli.exe --name=qm -p 9000 --verbose --bad=xyz file1.txt --out "a b"` | 13 行输出全对 |
| `python tools/dev/check_names.py` / `check_origin.py` / `check_docs.py` | 三禁 PASS |
| `python tests/irdiff.py` | **PASS=63 FAIL=0 SKIP=42**（SKIP 全是 arm64 未接的 map/str_from_mem） |
| `python tests/emitdiff.py` | **PASS=10 FAIL=0** |
| `python tools/stage0/qlm_cli.py version` | `Quelmara 1.29.0` |

## 已知边界 / 遗留

- **JSON 内部仍逐字节**：`_parse_str` 的 span 循环要同时看 `"` / `\` / `<0x20` 三类，
  单个 `mem_chr` 表达不了；下一步要么加 `mem_lt(p, n, bound)`，要么"双 memchr + 控制字符复检"。
- **没有 LRU**：需要 `map` + 双向链表两个句柄（map 句柄存不进 vec/mem 块），
  API 形态要先定，不能硬塞。已登记在 `07-gaps.md` §8。
- **没有 MD5**：FNV 已覆盖缓存键场景，MD5 只剩兼容旧协议，优先级压低。
- **deque 只有 int 元素**：`vec[str]` 可以，但 deque 的槽是裸 8 字节，放 str 需要额外
  管理长度前缀生命周期，暂不做。
- **`and` + 64 位立即数（≥2^63）的根因未定位**：已在库层避开，`07-gaps.md` §7.3 记录了复现条件。
