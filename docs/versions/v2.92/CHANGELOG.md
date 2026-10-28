# v2.92 — Linux 上的原生 socket：`tcp_connect` 从「只在 Windows」到真能连

- 日期：2026-10-28
- 任务：补齐平台 —— 让 `import std.net` 在 Linux/ELF 后端上不再是死路
- 结论：`tcp_listen/accept/send/recv` 一直是双平台的，**只有 `tcp_connect`
  被一句无条件的 platform 检查挡在门外**；补上 raw syscall 路径后，
  Linux 上的 echo 服务端与客户端都能真跑。

## 现状（v2.91 及以前）

`docs/07-gaps.md` 里写着"`tcp_*` 内建没有 Linux 实现"，实测确实如此：

```
$ python tools/stage0/qlm_cli.py build examples/echo_concurrent.qma --target native
SyntaxError: 无法发射指令 ('winapi', 4, 'WSAStartup', [('imm', 514), 3])
```

但这条描述**不准确**。逐个看运行库：

| 内建 | Linux 分支 | 说明 |
|---|---|---|
| `tcp_listen` | ✅ 有 | `socket`/`bind`/`listen` raw syscall |
| `tcp_accept` | ✅ 有 | `accept` |
| `tcp_send` | ✅ 有 | `sendto(fd, buf, n, 0, NULL, 0)` |
| `tcp_recv` | ✅ 有 | `recvfrom` 同款 |
| `tcp_close` | ✅ 有 | `close` |
| **`tcp_connect`** | ❌ **无** | 整个函数体只有 Win32 的 `WSAStartup`/`getaddrinfo`/`socket`/`connect` |

也就是说，报错信息"tcp_* 内建没有 Linux 实现"掩盖了一个更小的事实：
**五分之四已经有了，缺的是最后五分之一，而且它被两道闸门挡着。**

## 两道闸门

### 闸门一：派发层的无条件拒绝

```python
if name == "tcp_connect" and name not in self.fns_ast:
    if self.platform != "windows":
        raise SyntaxError("tcp_connect() 目前只在 Windows PE 后端实现（Linux DNS 未实现）")
```

报错理由是"Linux DNS 未实现"——但 DNS 与 connect **是两件事**。IPv4 点分
字面量（`"127.0.0.1"`）根本不需要解析器。把整条路径按"DNS 没做"拒掉，
等于连字面量一起拒了。

### 闸门二：运行库里的 `return` 提前退出

补完闸门一之后立刻撞到第二个：

```
KeyError: '__tcp_recv'
```

原因是我在 `lower_runtime()` 里给 `__tcp_connect` 写的 POSIX 分支末尾用了
`return` —— 而 `lower_runtime()` 是**一个巨大的顺序函数**，`__tcp_connect`
后面还有 `__tcp_listen6` / `__tcp_accept` / `__tcp_send` / `__tcp_recv` ……
一句 `return` 把它们**全部跳过**了。表现是"函数定义了但标签不存在"。

改成 `if platform == "windows": … else: …` 之后正常。**这类"运行库生成器里
的早退"是很难看出来的**：报错点（`KeyError: '__tcp_recv'`）离病因（几十行
之前的一个 `return`）很远。

## 修复：POSIX 的 `tcp_connect`

```
socket(AF_INET=2, SOCK_STREAM=1, 0)
  ↓ 失败 -> __net_fail_connect
构造 sockaddr_in（16B）：
  w0 = AF_INET | htons(port) << 16
  w1 = 4 段点分 -> 32 位网络序（逐字符解析，48..57 为数字，'.' 分段）
  ↓ 段数 != 4 -> fail-fast
connect(fd, &sin, 16)
  ↓ 失败 -> close + __net_fail_connect
```

同时给 `SYSCALLS` 表补了三个号（两个架构各一份）：

| 架构 | `connect` | `getsockname` | `setsockopt` |
|---|---|---|---|
| x86_64 | 42 | 51 | 54 |
| aarch64 | 203 | 204 | 208 |

**域名不在支持范围，且是显式 fail-fast**（段数/字符校验不通过就走
`__net_fail_connect`，不静默连到 0.0.0.0）。理由写在代码注释里：Linux 的
名字解析要走 `nsswitch.conf` → `dlopen` 各 `libnss_*` 插件 → `/etc/resolv.conf`
状态机，手写一遍等于把 glibc 的 resolver 内联进运行时——与本后端"无 libc 的
静态可执行文件"这个定位直接冲突。服务端侧本来也只需要 `listen`。

## 顺带修的：`__tcp_listen6` 泄漏到 POSIX

`__tcp_listen6`（IPv6 双栈）是纯 Win32 实现，但它在 `lower_runtime()` 里
**没有平台守卫**——只要 `uses_net` 为真就生成，于是在 Linux 上又冒出一条
`WSAStartup`。已用 `if self.platform == "windows":` 包起来。

## 实测

跑通了完整的一来一回（真 socket，不是 mock）：

```
$ ./build/net_echo_linux &                     # Quelmara 写的服务端，19559
$ python -c "connect + send + recv"            # 3 条并发连接
   -> 3/3 回显正确

$ python -c "listen 19560" &                   # Python 服务端
$ ./build/net_connect_linux                    # Quelmara 写的客户端
   -> got: pong:ping-from-quelmara
```

| 项 | v2.91 | v2.92 |
|---|---|---|
| `run_native_tests.sh` | PASS=101 FAIL=0 | **PASS=106 FAIL=0**（+5 条 POSIX 网络） |
| Linux 上 `import std.net` | 编译期 fail-fast | 可用（显式声明"只支持 IPv4 字面量"） |
| 回归 | 101/101 | 101 条原样通过，无回归 |

新增夹具 `tests/net_echo_linux.qma`（服务端）与 `tests/net_connect_linux.qma`
（客户端），由 `run_native_tests.sh` 的 `[24]` 段驱动。

## 边界（明确不做）

| 项 | 现状 | 为什么 |
|---|---|---|
| Linux 上的域名解析 | ❌ fail-fast | 见上：要抄 glibc resolver |
| Linux 上的 IPv6 `listen6` | ❌ fail-fast（`tcp_listen6` 派发处仍是显式拒绝） | `sockaddr_in6` + `IPV6_V6ONLY` 的两族分支还没写；与 A64 一起排 |
| Linux 上的 reactor（epoll） | ❌ | `std/net/reactor.qma` 是 IOCP 专用（`@ffi` + `CreateIoCompletionPort`），它的替代品是 `qlm_uring` 那条 C 链 + `tests/test_uring.sh` |
| AArch64 上的 `connect` | ⚠️ 已写，未执行验证 | 模拟器（`tests/a64_emu.py`）不模拟 `socket`/`connect` 系统调用；只有交叉编译级保证 |

## 口径

本版是平台补齐，没有性能数字。基准与 v2.89 相同，见 `docs/06-status.md` §3.52。
