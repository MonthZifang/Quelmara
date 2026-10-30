# v3.41 — 决策验证：qlmc 能通过 `@ffi` 调 Winsock，网络内建可以走源码

- 日期：2026-10-31
- 任务：用户要求"继续"；推进"编译器核心改用自研语言"
- 影响面：**只有测试**（新增 `tests/t185_qlmc_winsock.qma`），
  覆盖率不变（44/70）—— 这一版买的是**决策依据**，不是数字
- 版本：按 `00-convention.md` §5.1 建版本目录

## 为什么这一版不涨覆盖率

v3.40 的结论是"网络内建是唯一的大块（6 个模块），但需要接 Winsock"。

补这组内建有两条路，**风险差一个量级**：

| 路线 | 做法 | 风险 |
|---|---|---|
| A | 改 qlmc 的 IAT 表，把 `ws2_32` 的符号加进内置导入 | **高**（要动 `I_USER` 索引与导入表布局，影响所有产物） |
| B | 用 Quelmara 源码 + `@ffi` 实现整组内建 | **低**（不动编译器结构） |

选 B 的前提是：**qlmc 产出的程序能通过 `@ffi` 调 ws2_32**。
这件事**没人验证过** —— qlmc 的 `@ffi` 只在少数测试里用过（`s12_ffi`），
没有对 ws2_32 这种"多函数 + 句柄语义"的 DLL 试过。

所以这一版先把这个前提钉住，再决定怎么走。**先验证再动手**，
避免又一次"基于错误前提做决策"（v3.38 / v3.40 连续犯过两次）。

## 验证内容

`tests/t185_qlmc_winsock.qma` 走完整 socket 生命周期：

```
WSAStartup -> socket -> bind -> listen -> closesocket
```

五个 API 全部用 `@ffi("ws2_32.dll", ...)` 声明，包括 `WSAGetLastError`
（证明非零参数/返回值也正常）。

**结果：stage-0 与 qlmc 两边都通过。**

```
PASS: qlmc 可以通过 @ffi 调用 Winsock（网络内建可用源码实现）
```

## 夹具设计的两个细节

### 端口写 0，不调 accept

夹具要在回归里稳定通过：

* **端口 0** = 让系统分配，不会与任何服务冲突（回归里别的用例占了不少端口）；
* **不调 `accept`** —— 它会阻塞，夹具会挂住。

只验证到 `listen` 成功，已经足够回答"能不能调 Winsock"这个问题。

### 用 `s > 0` 而不是 `s != -1`

Win64 的 `int` 返回值**只写 eax**（高 32 位 0 扩展），所以 `SOCKET_ERROR`
在 rax 里是 `0x00000000FFFFFFFF` 而不是 64 位 `-1`。直接与 `-1` 比较
**会漏检** —— stage-0 的注释里记着这个坑（"bind/listen 失败被放过，
accept 才炸"）。

夹具用 `s > 0` 判断，避开这个陷阱。

## 结论与下一步

**路线 B 可行**。下一版可以开始用 Quelmara 源码实现这 12 个内建：

```
tcp_listen / tcp_listen6 / tcp_accept / tcp_connect / tcp_close
tcp_send / tcp_send_n / tcp_send_to / tcp_send_n_to
tcp_recv / tcp_recv_to / tcp_peer_raw
```

（`udp_*` 另算，`std/net/udp.qma` / `udp6.qma` / `dns.qma` 用）

实现时要注意与 stage-0 对齐的语义：

| 内建 | 语义要点 |
|---|---|
| `tcp_listen(port)` | 绑定 0.0.0.0:port；失败 **fail-fast** |
| `tcp_accept(fd)` | 阻塞等待；失败 fail-fast |
| `tcp_send(fd, str)` | 返回发送字节数 |
| `tcp_recv(fd, cap)` | 对端关闭返回**空串**（不是错误） |
| `tcp_close(fd)` | 返回 0 |
| `tcp_send_n(fd, ptr, n)` | 零拷贝变体，协议库缓冲池靠它 |
| `tcp_peer_raw(fd)` | 返回 20 字节原始地址（端口网络序 + family + 地址） |

## 回归

全量 Windows 回归 PASS=358 FAIL=0 SKIP=0（v3.40 是 357，新增 1 条
qlmc_winsock；	185 另计入 parsediff 的 240 项）。

## 一个值得记的节奏

这一版**覆盖率没动**（44/70），但它是必要的：上一版如果直接去改 IAT 表
（路线 A），可能花掉一整版还引入风险；而这次 20 分钟的验证直接排除了
那条路。

**"验证决策前提"本身是产出** —— 它不需要涨数字才算工作。
