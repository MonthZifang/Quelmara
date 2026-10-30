# v3.28 — 补上分片用例，抓到"分片之后连接永久卡死"

- 日期：2026-10-30
- 任务：用户要求"继续"；v3.27 明确遗留的"`std/ws` 分片没有端到端用例"
- 影响面：**标准库**（`std/ws` 分片完成时的 `_drop_frame` 参数错误），
  夹具从 7 项扩到 11 项
- 版本：按 `00-convention.md` §5.1 建版本目录

## 起点：v3.27 自己留的尾巴

v3.27 的 CHANGELOG 最后写着：

> `std/ws` 的分片（continuation frame）在夹具里没覆盖 —— 需要客户端发
> FIN=0 的多帧序列。代码路径存在（`WS_OP_CONT` 分支），但没有端到端用例。

这一版就补它。补的过程直接撞出一个**严重缺陷**。

## 缺陷：分片之后，这条连接再也收不到任何消息

先写最小复现：分片收一条，再发一条普通单帧 ——

```python
sock.sendall(make_frame(0x1, b"AAA", fin=False))
sock.sendall(make_frame(0x0, b"BBB", fin=True))
print(recv_frame(sock))          # (1, b'AAABBB')  ← 分片本身是对的
sock.sendall(make_frame(0x1, b"after-frag"))
print(recv_frame(sock))          # 超时 ← 卡死了
```

实测：

```
frag -> (1, b'AAABBB')
single NO RESPONSE: timed out
```

**不是偶发**：只要用过一次分片，之后这条连接就永久失效。

## 根因：`_drop_frame` 的 `keep_to` 传错了

分片完成的分支原本是：

```quelmara
let total = mlen + plen
let msg = mem_str(buf, total)
_drop_frame(p, total, pay, plen)     // ← keep_to = total
```

`_drop_frame(p, keep_to, pend_from, plen)` 的语义是"保留 `[0, keep_to)`，
跳过 `[pend_from, pend_from+plen)` 的帧，把帧后的数据贴到 `keep_to`"。

但分片消息到这里**已经消费完了** —— 消息本体 `[0, total)` 应该整体丢弃，
不是保留。传 `total` 的后果：

1. 消息本体留在缓冲区开头，`SLOT_RECVLEN` 变成 `total + tail`；
2. `WS_FOP` 已清零，下一轮 `off` 从 **0** 开始解析帧头；
3. 而 `buf[0]` 是上一条消息的第一个字节（比如 `'A'` = 0x41）——
   按帧头解读就是 `FIN=0, opcode=1`，长度字节也是垃圾；
4. 于是要么等一个永远凑不齐的帧，要么直接判协议错误关连接。

正确写法是 `keep_to = 0`：

```quelmara
_drop_frame(p, 0, pay, plen)
```

## 为什么 v3.27 没抓到

v3.27 的 7 项用例里没有分片 —— 全部是单帧（`fin=True`）。而**单帧路径
传的 `keep_to` 是对的**（`_drop_frame(p, off, pay, plen)`，`off` 是帧头起点，
单帧时 `off == 0`）。所以这个 bug 只在分片路径上暴露。

教训：**代码路径存在 ≠ 被测过**。`WS_OP_CONT` 分支写了 30 行，
从没跑过，里面藏着一个"连接永久失效"级别的错误。

## 夹具扩到 15 项

新增 8 条（8–15）：

| # | 判据 |
|---|---|
| 8 | 分片消息拼接正确（3 片 → 28 B） |
| 9 | 分片二进制消息的 opcode 取**首帧**（回的是二进制帧） |
| 10 | 分片中间穿插 ping：pong 已回，消息仍正确拼接 |
| 11 | **分片之后连接仍可用**（下一帧能收到） |
| 12 | close 握手：服务端回 close 帧且 code 回显 1000 |
| 13 | close 之后服务端真的关闭了连接 |
| 14 | 未掩码的客户端帧被拒（close code **1002**） |
| 15 | 分片未完成时的新数据帧被拒（close code **1002**） |

第 11 条是这次 bug 的回归钉。

第 10 条对应 RFC 6455 5.4：控制帧允许夹在分片之间，且不打断分片序列。

第 12–15 条补的是**从没跑过的代码路径**：`WS_OP_CLOSE`（5 行）与
两个协议错误分支（各 2–4 行）。它们与分片那条同源 —— 写了但没人跑。
实测都对，现在钉住。

错误路径用**新连接**测，不污染前面那条（服务端拒绝后会 close）。

### 夹具自身的健壮性也修了

第一次跑带 bug 的版本时，脚本直接抛 `TimeoutError` / `ConnectionResetError`
崩栈 —— 前面已通过的断言全丢了，也看不出是哪条失败。加了两个包装：

* `safe_recv` —— 超时/断开返回 `(None, None)`
* `safe_send` —— 连接被重置返回 `False`

现在带 bug 版本会干净地报出 3 条 FAIL：

```
[FAIL] 分片二进制消息收不到
[FAIL] 分片+ping 穿插：pong=False msg=None
[FAIL] 分片消息本身就收不到（连接卡死）：[WinError 10054] ...
WS_E2E: PASS=8 FAIL=3
```

**端到端脚本里"收不到"本身就是判据**，不该让它变成未捕获异常。

## 回归

全量 Windows 回归 PASS=344 FAIL=0 SKIP=0（v3.27 是 344，主回归条数不变 ——
ws 在 run_win_tests 里仍是**一条**用例，是脚本内部的断言数从 7 增到 15）。

## 遗留

`std/ws` 的分片、close、两条协议错误路径现在都测过了。仍未覆盖的：

* **超长消息被拒**（`plen > maxmsg` → close code **1009**）——
  要发 > 1 MB 的帧，夹具会变慢（`WS_DEFAULT_MAX_MSG = 1MB`）；
* **64 位长度档**（`plen >= 65536` 走 8 字节长度）—— 上面那条 1009
  测试顺带就能覆盖，但同样要发大帧。

两条都值得补，但会让 E2E 从"秒级"变"十秒级"，留待后续按需加。
