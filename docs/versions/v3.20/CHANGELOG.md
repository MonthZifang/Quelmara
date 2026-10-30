# v3.20 — UDP over IPv6：`AF_INET6` 在 Windows 是 23 不是 10

- 日期：2026-10-30
- 任务：用户要求"继续"；`07-gaps.md` P1 剩「UDP v6 / reactor 双栈」
- 影响面：**编译器**（`udp_open6`/`udp_bind6`/`udp_sendto6`/`udp_recvfrom6{,_to}`
  五个内建 + 四个运行库）、标准库（新增 `std/net/udp6`）、测试（新增 `t173`）、文档

## 先说 P1 复核：三条早就做完了

本轮本来只想做 UDP v6，但按"先复核再动手"的纪律查了一遍 P1，发现**四条里三条是
文档滞后**（实现早就完成，条目没划掉）：

| P1 条目 | 状态 | 证据 |
|---|---|---|
| 3. `map[str]Struct` | ✅ **v1.41 就有** | `tests/t86_mapstruct.qma`（5 组）已在主回归 |
| 4. 函数值放宽：8 参 + struct 实参 | ✅ **v1.42 就有** | `tests/t38_callr.qma` 已在主回归；**v3.20 探针实测**三项全过 |
| 6. UDP v6 | ❌ 真缺 | 本轮做 |

`map[str]Struct` 那条尤其能说明问题：`vec[map]` 在 v1.37 打了删除线，
`map[str]Struct` 却没打 —— 同一行里两种状态并存了好几个版本。

**教训**：能力表里的"未做"要定期对着夹具复核。实现做了而条目没划掉，
与"文档说做了其实没做"一样会误导排期，只是方向相反。

## 问题：UDP 的地址家族被写死在 16 字节 sockaddr 里

`std/net/udp` 的四个内建（`udp_open`/`udp_bind`/`udp_sendto`/`udp_recvfrom`）
全部按 **IPv4** 构造：`sockaddr_in` 16 字节、`AF_INET`、地址是 u32 网络序。
要支持 v6 必须换成 `sockaddr_in6` 28 字节 + 16 字节地址。

**为什么拆成独立内建而不是加参数**：地址家族在 `socket()` 那一刻就定死了，
调用方拿到的是一个不透明 fd —— 后续 `udp_sendto` 无法判断该按 16 还是 28 字节
构造地址。把"用哪个内建"当作家族的载体，比在 fd 之外再传一个 family 参数
更不容易传错。

## 改动

### 1. 五个新内建

| 内建 | 说明 |
|---|---|
| `udp_open6()` | `AF_INET6` + `SOCK_DGRAM` |
| `udp_bind6(fd, port)` | 28 字节 `sockaddr_in6`，地址 `::` 通配 |
| `udp_sendto6(fd, addr_ptr, port, data)` | `addr_ptr` 指向 **16 字节**大端地址 |
| `udp_recvfrom6(fd, cap)` | 源地址丢弃（与 v4 同口径） |
| `udp_recvfrom6_to(fd, cap, ms)` | 超时返回**空串**，不是 fail-fast |

地址用指针而不是字符串：v6 的文本形式（`::` 压缩、`::ffff:1.2.3.4`、
未来的 `%zone`）解析放在 `std/net/addr.ip6_parse` 里，内建只认字节。

### 2. `std/net/udp6`

薄封装：`udp_send6`（文本地址 → 字节）、`udp_recv6` / `udp_recv6_to`、
`udp_once6`（一次性发送）。

**踩到的坑**：第一版写了 `pub fn udp_open6() -> int { return udp_open6() }`
—— 库函数与内建同名，解析会落到内建上，库函数成死代码（或无限递归）。
改成不做同名包装：本模块直接暴露内建，只加"文本地址 → 字节"的转换层。

## 三个踩坑（每个都真实卡了一次）

### 坑一：`AF_INET6` 在 Windows 是 **23**，不是 10

第一版把 `sin6_family = 10` 写死了（那是 Linux 的值）。结果 Windows 上
`bind` 返回 `-1`，而且**不报错、不说原因** —— 内核按 family 字段判错。

`__udp_open6` 里我按平台分叉了（Windows 23 / Linux 10），但 `udp_sin6`
（构造地址结构那个）没有。**同一个事实在 `tcp_peer_raw` 的注释里早就写着**
（"`[2] family（2=v4 / 23=v6 / 0=未知）`"），当时没串起来。

修完之后 `bind6 ret=0`。

### 坑二：`__net_fail_<tag>` 标签必须先在运行库里定义

我给四个新函数写了 `net_fail(f, lf, "udpopen6")`，链接期报
`KeyError: '__net_fail_udpopen6'`。因为 `net_fail` 只是 emit 一个
`call __net_fail_<tag>`，而那个标签要在运行库里手工定义 ——
原来只定义了三个（`udpsocket`/`udpsendto`/`udprecvfrom`）。

**每个 `net_fail` 调用点都对应一个必须存在的运行库标签**，
这是内建层的隐式契约，没有编译期检查。

### 坑三：`recvfrom` 返回的是**数据指针**，不是缓冲区指针

`str` 的值必须指向数据起点，而长度头在前 8 字节。我第一版 `ret buf`，
应该 `ret buf+8` —— 与 v4 的 `__udp_recvfrom` 同口径。

同一个错误在 `_to` 版本上还多一层：v4 的 `_to` 在超时/失败时**返回空串**，
我错用了 `net_fail`（fail-fast）。**带超时的版本不该把超时当致命错误** ——
调用方（DNS）需要"这个 nameserver 没响应"是可恢复结果。

## 验证

| 命令 | 结果 |
|---|---|
| `build tests/t173_udp6.qma --target win` | 编过（80896 B） |
| `t173` 执行 | **`udp6 ok`**（4 组断言全过） |
| `python tests/run_win_tests.py` | **PASS=333 FAIL=0 SKIP=0**（IPv4 UDP 无回归） |
| 加 `t173` 进主回归后 | 见下表 |

`t173` 四组断言：

| 组 | 内容 | 判据 |
|---|---|---|
| `[1]` | `udp_open6` + `udp_bind6` | 都返回成功（fd ≥ 0 / 0） |
| `[2]` | `::1` 回环收发 | 发 10 字节，收回来内容一致 |
| `[3]` | 非法地址 | `udp_send6` 返回 **-1**，不崩溃 |
| `[4]` | 超时 | `udp_recv6_to(fd, 512, 100)` 约 100 ms 返回**空串** |

## 改动清单

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | 五个 v6 内建 + `udp_sin6`（平台相关 AF_INET6）+ 四个运行库 + `__net_fail_*` 标签 |
| `std/net/udp6.qma` | 新增：文本地址转换层 + 三个便捷函数 |
| `tests/t173_udp6.qma` | 新增：4 组断言 |
| `tests/run_win_tests.py` | `[3k]` 段之后接入 `udp6`（60 s 短超时） |
| `docs/07-gaps.md` | P1 复核（3/4/5/7 打删除线）+ UDP v6 → ✅ |
| `docs/06-status.md` | 新增 §3.70 |
| `tools/stage0/qlm_cli.py` | `VERSION` → 3.20.0 |

## 已知边界 / 遗留

- **仅 x86_64**（与 v4 的 `udp_*` 同口径）。A64 的发射层没有 UDP 内建，
  要支持得补 `qlm_arm64.py` 那侧 —— 但 A64 连 `spawn` 都没有，网络用例
  本来也跑不了。
- **源地址丢弃**：`udp_recvfrom6` 不返回对端地址（与 v4 同口径）。
  要做 DNS 的 v6 应答校验或 echo 服务，得加 `udp_recvfrom6_from` 内建
  （返回 16 字节地址 + 端口）。登记 `07-gaps.md` §2。
- **`reactor` 双栈仍未做**：`net_serve`（IOCP）只绑 v4。这是 P1 第 6 条的
  另一半，与 UDP v6 是两件事 —— 本轮只做了 UDP。
- **`%zone`（链路本地地址的 scope id）**：`ip6_parse` 不支持 `fe80::1%eth0`，
  `udp_sin6` 的 `sin6_scope_id` 恒为 0。做链路本地通信会缺这一块。
- **`t173` 用固定端口 18120**：如果宿主机上被占，失败信息会是
  `udp6 socket failed`（fail-fast），不是 SKIP。与 `[3k]` 那批 TCP 用例
  同一种处理（v3.11 记过"收益不大，先记着"）。
- **三个踩坑都是"静默失败"**：`AF_INET6` 写错只返回 -1、`__net_fail` 标签
  缺失是链接期才炸、`ret buf` 错是内容错位而不是崩溃。**内建层的隐式契约
  没有编译期检查**，这类改动只能靠夹具跑真流量来验 —— 这也是为什么
  `t173` 必须做**真实回环收发**，而不只是"能编过"。
