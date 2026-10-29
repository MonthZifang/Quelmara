# v3.07 — `send_all` 零拷贝：新增 `str_ptr` 内建，修掉 O(n²) 堆爆

- 日期：2026-10-29
- 任务：补 v3.06 自己登记的边界 —— "发送侧仍是单次 `tcp_send`"
- 影响面：**编译器**（新内建 `str_ptr`）、标准库（`std/net.send_all`）、测试（新增 `tests/t164_sendall.qma`）、文档

## 问题：`send` 会短写

`std/net` 只有：

```quelmara
pub fn send(conn: int, data: str) -> int {
    return tcp_send(conn, data)
}
```

`tcp_send` 是**一次** `send()` 系统调用，返回值是"这次写进去多少"，
**可能小于 `len(data)`**。短写不是错误，是 TCP 的正常行为：

| 场景 | 结果 |
|---|---|
| 内核发送缓冲区快满 | 只接受一部分 |
| 大块数据（> 64 KB） | 几乎一定分多次 |
| 非阻塞 socket | 必然短写 |

拿 `send` 当"发完了"用，会在高吞吐或大包场景**丢尾巴**。

## 第一版写错了：`substr` 切尾巴 → O(n²)

最直觉的循环写是"每轮切掉已发部分"：

```quelmara
while sent < total {
    let rest = substr(data, sent, total - sent)   // ← 每轮复制剩余全部数据
    let n = tcp_send(conn, rest)
    sent = sent + n
}
```

**`substr` 是复制**。4 MB 负载、短写分成 64 次 → 累计复制约 128 MB；
分成更多次就是 O(n²)。实测直接撞堆上限：

```
$ ./build/sendall2      # 4 MB
quelmara: heap_limit_mb exceeded (fail-fast)
EXIT: 124（超时）
```

这不是"慢一点"，是**跑不完**。v3.06 的文档其实已经预判了这个风险
（"字符串拼接是 O(n²) 风险"），但真正写发送侧时才撞上。

## 正确做法：零拷贝指针推进

语言里**已经有**零拷贝发送的内建：

```quelmara
tcp_send_n(fd, ptr, n) -> int      // 裸指针 + 长度，不构造 str、不扫 strlen
```

缺的只是"从 str 拿到数据指针"。于是新增一个内建：

### `str_ptr(s) -> int`（v3.07，编译器能力）

```quelmara
pub fn send_all(conn: int, data: str) -> int {
    let total = len(data)
    if total == 0 { return 0 }
    let base = str_ptr(data)
    let mut sent = 0
    while sent < total {
        let n = tcp_send_n(conn, mem_ptr(base, sent), total - sent)
        if n <= 0 { break }
        sent = sent + n
    }
    return sent
}
```

**零分配、零复制**：整个循环只推进一个整数偏移。

## 实现 `str_ptr` 时踩的两个坑

### 坑 1：`s + n` 会被字符串拼接劫持

第一版写 `tcp_send_n(conn, base + sent, ...)`，编译器直接给出明确诊断：

```
SyntaxError: 字符串与 int 拼接需 to_str()；指针偏移用 mem_ptr(p, off)
```

这是语言刻意的设计（`s + n` 有歧义），正确写法是 `mem_ptr(base, sent)`。

### 坑 2：把操作数的 str 标记摘掉，连 `len(s)` 都坏了

Quelmara 的 str 是长度前缀 ABI：`[len:8][bytes...]`，而**str 变量的值本身
就是数据指针**（`__str_len` 的实现就是 `load(p-8)`，正好印证）。所以
`str_ptr` 理论上可以"直接返回操作数"。

第一版就是这么写的，然后把操作数 vreg 从 `fn.strv` 里 `discard` 掉
（否则 `print(str_ptr(s))` 会打印字符串内容而不是地址）。结果：

```quelmara
let s = "hello"
let p = str_ptr(s)
print(len(s))       // SyntaxError: len() 目前只支持定长数组、切片、map 或 str
```

**因为 `s` 和 `p` 是同一个 vreg**，摘标记等于把 `s` 也标成 int 了。

修法：拷到一个**新 vreg**，只给新 vreg 去标记：

```python
d = fn.new_v()
fn.emit("mov", d, v)
fn.strv.discard(d)      # 只影响新 vreg
return d
```

多一条 `mov`，会被复制传播消掉，成本可忽略。

## 验证

### `tests/t164_sendall.qma`（3 场景）

| # | 场景 | 断言 |
|---|---|---|
| 1 | 小负载 14 字节 | `recv_exact` 收到的内容逐字节一致 |
| 2 | **4 MB**（`vec[int]` 构造 + `str_from_bytes`） | `send_all` 发全，`recv_exact` 收全 4194304 |
| 3 | `str_ptr` 语义 | 指针非 0；`mem_load8(p,0)==104`（'h'）；`mem_load64(p-8)==5`（长度前缀）；**`len(s)` 仍是 5**（原 str 未被破坏） |

```
$ ./build/t164
14
4194304
send batch ok
EXIT: 0
```

场景 2 是关键：同一份负载在修正前是 `heap_limit_mb exceeded` + 超时，
现在是 4 MB 一次通过。

场景 3 的第 4 条断言是坑 2 的回归——如果 `str_ptr` 再摘掉原操作数的标记，
`len(s)` 会立刻编译失败。

### 回归

| 命令 | 结果 |
|---|---|
| `./build/t164`（native） | `send batch ok`，退出码 0 |
| `bash tests/run_native_tests.sh` | 见 `06-status.md` §1 |

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 新增内建 `str_ptr`（约 20 行，含两处坑的注释） |
| `std/net.qma` | 新增 `send_all`（零拷贝指针推进） |
| `tests/t164_sendall.qma` | **新增**（3 场景，含 4 MB 零拷贝回归） |
| `docs/02-language.md` | 内建表新增 `str_ptr` 行 |
| `docs/07-gaps.md` | §2「TCP 批量收发」改为 v3.06 接收 / v3.07 发送；§6 P1 同步 |

## 已知边界 / 遗留

- **`str_ptr` 返回的指针只在源 str 存活期内有效**。语言没有生命周期检查，
  这是"裸指针来源"的一类（与 `mem_str` 裸指针同口径）。跨作用域保存它是
  调用方的责任。
- **无超时**：`tcp_send_n` 阻塞。对端一直不收且缓冲区满时会一直等——
  这是 TCP 的背压语义，不是 bug。要超时得给 `tcp_send_n` 做
  `SO_SNDTIMEO` 变体。
- **`send_all` 中途出错返回已写出的字节数**，不是 0 也不是 `len(data)`。
  调用方用 `== len(data)` 判断是否发全。
- **`str_ptr` 目前只对 str 有定义**。vec / 切片没有对应内建；它们的
  `get/set` 已够用，且 `tcp_send_n` 的典型输入就是 str 缓冲区。
- **AArch64 / C 后端**：`str_ptr` 是纯前端内建（直接返回操作数 + 一条 mov），
  与发射层无关，三个后端都可用；`tcp_send_n` 仍只在 x86_64 实现（与
  `tcp_send` 同边界）。
