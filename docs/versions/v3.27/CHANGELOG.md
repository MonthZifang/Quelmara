# v3.27 — `ws` / `sse` 修完没验过：真跑一遍发现 opcode 丢了

- 日期：2026-10-30
- 任务：用户要求"继续"；v3.26 把 `std/ws` / `std/sse` 从"调不到"修到
  "能编译"，但**从没验证过它们真的能跑**
- 影响面：**标准库**（`std/ws` 新增 `ws_last_op()` + 记录当前 opcode），
  新增两个端到端夹具
- 版本：按 `00-convention.md` §5.1 建版本目录

## 起点：能编译 ≠ 能用，能起服务 ≠ 协议对

v3.26 让 `std/ws` / `std/sse` 有了 `pub`、能 import、demo 也能构建。
但 WebSocket 和 SSE 的坑**全在线上协议**，一条都不靠编译能发现：

| 协议点 | 编译能发现吗 |
|---|---|
| 握手摘要（SHA-1 + base64） | ❌ |
| 帧头 7 / 7+16 / 7+64 三档长度 | ❌ |
| 客户端掩码必须解开 | ❌ |
| 文本帧 vs 二进制帧分派 | ❌ |
| SSE 事件块以空行结尾 | ❌ |
| `retry:` 是毫秒不是秒 | ❌ |

所以这一版写了两个端到端夹具，用 Python 手写客户端（不引第三方库）。

## 发现一：`std/ws` 把 opcode 丢了

`_frames` 里文本帧和二进制帧**合并分派**：

```quelmara
if op == WS_OP_TEXT || op == WS_OP_BIN {
    ...
    let hr = h_msg(fd, msg)      // 回调签名是 fn(fd, data)
}
```

回调签名 `fn(fd: int, data: str) -> int` 里**没有 opcode**，于是用户拿到
一条消息时**没法知道它是文本还是二进制**。

实测症状：demo 里 `on_msg` 无脑 `ws_send(fd, data)`，客户端发二进制帧
（`opcode=0x2`）回来的是文本帧（`opcode=0x1`）—— 客户端按二进制解析
就是乱码。夹具直接抓到了：

```
[FAIL] 二进制 echo：op=1 len=256
```

### 修法：不动回调签名，加一个查询函数

改签名（`fn(fd, data, op)`）会让**所有现有 ws 代码编译失败**，代价太大。
改成把当前帧的 opcode 记进状态块，回调用 `ws_last_op()` 查：

```quelmara
pub fn ws_last_op() -> int {
    return mem_load64(_wst(), WS_OP_W)
}
```

状态块 128 字节 = 16 个 8 字节槽，`ST_AUX` 是 12，13–15 空闲，
用 `WS_OP_W = 13`。

两处 `h_msg` 调用都要记：

* **完整帧**：`mem_store64(st, WS_OP_W, op)`
* **分片消息完成**：`mem_store64(st, WS_OP_W, fop)` —— 取**首帧**的 opcode，
  续帧一律是 `CONT`(0)，拿它当类型就错了。

demo 改成按类型回：

```quelmara
if ws_last_op() == 2 {
    ws_send_bin(fd, data)
} else {
    ws_send(fd, data)
}
```

## 发现二：端口撞了

`ws_demo.qma` 原来监听 **8092**，而 `http_router_test.py` 和
`reactor_dualstack_test.py` 也用 8092。三者进同一个回归会互相抢端口。

挪到 **18150**（与 18073–18097 那批、8092、8093 都错开）。
夹具从源码里正则读端口（`ws_serve\((\d+)`），demo 改端口时自动跟上 ——
不会变成"服务起了但连不上"的假失败。

## 夹具

### `tests/ws_e2e_test.py`（7 项）

| # | 判据 |
|---|---|
| 1 | 握手返回 101 |
| 2 | `Sec-WebSocket-Accept` 与客户端算的一致（SHA-1 + base64） |
| 3 | `on_open` 主动推送收到 |
| 4 | 文本帧 echo（掩码已解） |
| 5 | 300 B 长文本（走 16 位长度档） |
| 6 | 256 B 二进制帧 echo，**opcode 必须是 2** |
| 7 | 两次不同掩码 key 都能正确解出明文 |

第 7 条是关键：如果服务端"碰巧"把掩码当明文处理，同一内容两次发送
（掩码 key 不同）就会得到两个不同结果 —— 这条能抓住。

### `tests/sse_e2e_test.py`（8 项）

| # | 判据 |
|---|---|
| 1 | 订阅返回 200 |
| 2 | `Content-Type: text/event-stream` |
| 3 | `Cache-Control` 含 `no-cache` |
| 4 | `retry:` 行值是 2000（毫秒，不是秒） |
| 5 | `event:` + `data:` 两字段格式正确 |
| 6 | 收到 N 个**以空行结束**的事件块 |
| 7 | 收到 tick 广播（验证 `spawn` 线程能跨线程推送） |
| 8 | tick 序号递增（0..9，没丢没重） |

## 回归

全量 Windows 回归 PASS=344 FAIL=0 SKIP=0（v3.26 是 342，新增 2 条）。

## 遗留

`std/ws` 的分片（continuation frame）在夹具里没覆盖 —— 需要客户端发
FIN=0 的多帧序列。代码路径存在（`WS_OP_CONT` 分支）且 v3.27 顺手在
那里也记了 opcode，但没有端到端用例。留待后续。
