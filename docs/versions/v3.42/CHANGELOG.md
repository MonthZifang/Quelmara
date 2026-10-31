# v3.42 — 网络内建落地：TCP 六个内建 + 分配器 ARG 屏障缺陷

- 日期：2026-10-31
- 任务：用户要求"继续"；v3.41 已证明路线 B 可行，这一版真的把 TCP 内建写出来
- 影响面：`bootstrap/qlmc/qlmc.qma`（IAT 槽位 + 六个内建 + 分配器修复）、
  `tests/t186_qlmc_tcp.qma`、`tests/net_e2e_test.py`、`tests/run_win_tests.py`
- 覆盖率：**44 → 45**（基线已上调）
- 回归：PASS=358 → **359** FAIL=0 SKIP=0

## 做了什么

按 v3.41 定下的路线 B（Quelmara 源码 + `@ffi`），在 qlmc 里实现 TCP 六个内建：

| 内建 | 语义 |
|---|---|
| `tcp_listen(port)` | 绑定 `0.0.0.0:port` 并监听；失败 **fail-fast** |
| `tcp_accept(fd)` | 阻塞等到连接；失败 fail-fast |
| `tcp_send(fd, str)` | 发一个 str（长度取 `[s-8]` 头） |
| `tcp_send_n(fd, ptr, n)` | 零拷贝发送（协议库缓冲池用） |
| `tcp_recv(fd, cap)` | 返回 `[len][bytes][NUL]` 的 str；出错 fail-fast |
| `tcp_close(fd)` | `closesocket` 薄封装，恒返回 0 |

配套改动：`I_USER` 12 → 20，新增 8 个 ws2_32 的 IAT 槽位
（`I_WSASTART..I_CLOSESOCK`），`dnames` 加 `ws2_32.dll`（索引 3）。

## 三个真缺陷（都不是"写错一行"，是结构性的）

### 1. IAT 槽位漏填 → `CALLIAT` 跳到地址 0

第一版 `tcp_listen(0)` 编出来能跑，但**一执行就 `0xC0000005`**，连第一条
`print` 都活不过去。

原因：`build_rdata` 末尾那段 `iat.set(I_XXX, ...)` 是**逐条硬编码**的
（`I_GETSTD` 到 `I_WSPRINTF` 共 12 条）。我加了 8 个新槽位常量、
在 `dsym` 里 push 了 8 个符号，**但忘了加对应的 `iat.set`** —— 槽位留着 0，
`CALLIAT` 就 `call [0]`。

> 教训：IAT 槽位是"两处必须同步"的结构（`dsym.push` 顺序 + `iat.set` 偏移）。
> 加内置导入时，漏任何一处都是**运行时**崩溃，编译期一声不响。

### 2. 分配器把实参寄存器当临时值用（**通用缺陷**）

修完槽位后 `tcp_send_n` 返回 0 —— 对端一个字节都收不到。

诊断过程：同一份 `.qma` 用 stage-0 编出来是对的（收到 `ABCDEFGHIJABCDE`），
用 qlmc 编就是 0。所以是**代码生成错**，不是夹具错。

根因在寄存器分配：

* 临时值池是 `R8 / R9 / R10 / R11`（`_tmp_reg`）；
* Win64 的第 3/4 个实参寄存器**正好是 `R8` / `R9`**；
* `cp[]`（"区间是否跨调用"的前缀和）**只把 `CALL` 记为屏障**，`OP_ARG` 不算。

于是 `_ir_emit(ARG, 2, n)` 之后，`n` 的区间里没有 `CALL`，`crosses == 0`，
分配器就敢把它放进 `R8`。紧接着为第 4 个实参 CONST 的那个 0 复用了同一个
`R8`，`mov r8, 0` 把第 3 个实参覆盖掉 → `send(fd, p, 0, 0)` → 返回 0。

修复：把 `OP_ARG` 也算作跨调用屏障（`_opt_alloc` 里 `cp[]` 的构建处）：

```quelmara
if ins.op == OP_ARG && ins.imm >= 2 {
    c = c + 1
}
```

只对 `imm >= 2` 生效 —— `_out_arg_reg` 把 0/1 映到 `RCX`/`RDX`，那两个不在
临时池里，没有冲突，也就没必要付溢出的代价。

**用户函数的三参调用一直是对的**（那边的实参在 `CALL` 前就搬完、区间含
`CALL`），所以这个坑只在**手写 IR 的内建**里暴露 —— 而内建恰恰最容易把
`CONST` 写在 `ARG` 后面。`_bi_tcp_send_n` 里那段注释现在就是这条的回归探针：
顺序故意保持"先 ARG、后 CONST"，删掉屏障它立刻退回返回 0。

### 3. 帧槽上限：416 格被顶爆

修完分配器，**自举 stage-2 编不过自己**：

```
qlmc: 局部变量/聚合超出帧（416 个 8 字节槽）
  当前函数：build_rdata
  需要 417 个槽（已用 416，本次要 1）
```

先试着把 `SLOT_TEMP` 416 → 424、`MAX_SLOT` 512 → 520，结果报错变成
"需要 425 个槽" —— **数字跟着上限一起涨**。这说明根本不是容量问题。

加临时诊断（`_st_units` 里 `s > 400` 时打印）才看清：`build_rdata` 里
**每条 `let` / 每个 push 语句占 1 格**，一路累积到 424。那函数本来就
贴着 416 的边，我加的 8 个 `dsym.push` 正好把它推过去。

正解不是加帧（帧 > 4 KB 要栈探测，§7.17，qlmc 还没做），而是**把那 8 个
符号注册搬进独立函数 `_reg_ws2(dsym, ddll)`** —— 函数调用不占调用方的
局部变量槽。上限改回 416/512。

> 顺带记住：`_st_units` 的报错只说"当前函数 + 已用/本次要"，
> 不说**是哪一行**。大函数里靠这个数字定位很痛苦，临时加个
> `s > N` 的打印比猜快得多。

## 测试

`tests/t186_qlmc_tcp.qma` 是个**服务端**（listen → accept → recv → send →
close），它阻塞在 `accept` 上等客户端，所以**不能**走 `case_selfcheck_to`
（那条路径没人连它，会挂到超时）。

真正验证收发的是 `tests/net_e2e_test.py`：拉起 exe、**用 Python 当客户端**
连接、发 `hello`、收回显，再断言两边输出。Python 端是独立实现 —— 这正是
差分口径，能同时钉住 IAT 槽位、`sockaddr_in` 布局、htons 字节序、fail-fast 判定。

```
[PASS] TCP 连接建立（tcp_listen + bind + listen 正确）
[PASS] 回显正确：b'echo:hello'（tcp_recv + tcp_send 正确）
[PASS] 服务端退出码 0
=== t186 net e2e: PASS=6 FAIL=0 ===
```

端口 39471，被占用时返回退出码 2 → 主回归记 SKIP（不假红）。

## 自举

```
stage-1（stage-0 编 qlmc）  2 789 376 B
stage-2（qlmc 编自己）        464 384 B
stage-3（stage-2 编自己）     464 384 B
不动点成立  sha256 3FCC4B18D151905E…
```

## 已知边界

* `tcp_listen` 只做 IPv4（`tcp_listen6` 未做）；
* `tcp_connect` / `tcp_send_to` / `tcp_send_n_to` / `tcp_recv_to` /
  `tcp_peer_raw` 未做 —— 超时类内建要 `select`/`setsockopt`，另算；
* `udp_*` 三个未做。

覆盖率 45/70，剩余阻塞项见 `06-status.md` §3.92。
