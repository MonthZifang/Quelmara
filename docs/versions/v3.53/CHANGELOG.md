# v3.53 — `thread_start` 落地；覆盖率 51 → 54

- 日期：2026-10-31
- 任务：用户要求"继续"；补 `thread_start` 内建（剩余缺口里最大的单点）
- 影响面：`bootstrap/qlmc/qlmc.qma`（`_bi_thread_start`）、
  `tests/t197_qlmc_thread.qma`、`tests/qlmc_test.py`、
  `tools/dev/qlmc_coverage.py`（`BASELINE` 51 → 54）
- 覆盖率：**51 → 54**（一次解开 3 个模块）
- 回归：PASS=368 FAIL=0 SKIP=0；qlmc 差分 74 → **76**

## 为什么这个内建最划算

`thread_start` 一个缺口同时挡三个模块：

| 模块 | 缺口 |
|---|---|
| `std/net/reactor.qma` | `未定义函数 thread_start` |
| `std/ws.qma` | `未定义函数 thread_start` |
| `std/sse.qma` | `未定义函数 thread_start` |

补上之后三个一起过（51 → 54），是剩余缺口里收益最高的单点。

## 与 `spawn` 的区别

**唯一区别：`thread_start` 不受 `Quelmara.toml` 的 `multicore=false` 降级影响。**

`spawn` 在单核配置下会**内联执行**（同线程直接调）。reactor 的
`GetQueuedCompletionStatus` 循环依赖"真的在另一个线程上"—— 内联的话
主线程卡在完成端口里，`accept` 再也不运行。stage-0 的注释里写着同一件事。

## 实现：复用 `RT_SPAWN` 的线程入口

qlmc 已经有 `RT_SPAWN`（`spawn` 用的线程入口），它处理好了一切麻烦事：
Win64 的栈对齐、32 字节影子空间、非易失寄存器（RBX/R12）保存。
**不重复实现线程入口**，只负责摆好参数块、调 `CreateThread`。

块布局（与 `RT_SPAWN` 的约定一致，`n = 1`）：

```
[+0]  返回值槽（线程写、join 读）
[+8]  目标函数地址
[+16] 实参个数 = 1
[+24] 第 0 个实参
```

然后 `CreateThread(0, 0, &__spawn_entry, blk, 0, 0)` —— 6 个实参，
后两个走栈（复用 `_emit_call_args`）。

**返回值**：`CreateThread` 的句柄（失败返回 0）。reactor 丢弃它，保留是为了
将来能 join。**不返回 `spawn` 那种 `[句柄, 块]` 记录** —— `thread_start`
没有 join 语义，块要留给线程自己写返回值。

## 测试

`tests/t197_qlmc_thread.qma`，加进 `tests/qlmc_test.py` 的 `CASES`
作为**差分用例**（`s32_thread`）—— stage-0 也支持 `thread_start`，
两边输出逐字节一致（37 字节）。

四条判据，逐条对应一个可能出错的方式：

| 判据 | 抓什么 |
|---|---|
| `handles=ok`（4 个句柄都非 0） | `CreateThread` 调用失败 / 返回值丢失 |
| `bits=15`（1\|2\|4\|8） | **arg 没传进去**，或某个线程没跑 —— 任一位丢失都不到 15 |
| `cnt=4` | 线程数与调用次数一致 |
| `cnt2=3`（第二批） | 可以重复调用，不是一次性的 |

`bits` 那条是最关键的：四个线程各传不同的 2 的幂，按位或累加。
arg 传错（比如恒 0 或全传同一个值）会让结果不是 15。

## 覆盖率

`std/` **51 → 54**：`std/net/reactor`、`std/ws`、`std/sse` 同时解锁。
`BASELINE` 已上调到 54。

剩余 16 个模块的缺口分布（下一个最大的单点是 `tcp_connect`，挡 2 个）：

```
2  缺内建: xmm_load       (std/aes, std/tls13)
2  缺内建: tcp_connect    (std/net, std/net/udp6)
2  未知类型 TlsClientResult (std/httpc_net, std/tls_net)
1  缺内建: args           (std/cli)
1  vec[vec[T]] §7.18      (std/csv)
1  泛型 `[T: Ord]`        (std/gen)
1  函数重复定义 _fail     (std/http)
1  函数重复定义 _get      (std/logfile)
1  for k in map §7.40     (std/kv)
1  map 方法不全           (std/set)
1  缺内建: syscall        (std/park_linux)
1  结构体字面量含方法调用  (std/session)
1  缺内建: xmm_mov        (std/tls_client)
```

## 自举

30/30 组等价 + 不动点成立。stage-2 产物 601600 B（v3.52 是 595968 B），
仍在 `ARENA_CAP = 4 MB` 的余量内。
