# v3.23 — `static_word` 槽位全满：四处抢槽，其中一处会静默崩溃

- 日期：2026-10-30
- 任务：用户要求"继续"；v3.22 结束时的待办里挂着"`static_word` 越界隐患"
- 影响面：**编译器 + 标准库**（`STATIC_SLOTS` 32→64、编译期越界检查、
  `std/log` 槽位重排），新增门禁 `tools/dev/check_static_words.py`
- 版本：按 `00-convention.md` §5.1 建版本目录

## 起点：v3.22 踩到的是症状，不是病因

v3.22 的测试夹具借用了 `static_word(120..123)`，越界写踩坏了别的全局数据，
进程直接崩。当时的修法是"把夹具改成 `mem_alloc`"，**没动机制本身** ——
`static_word(i)` 仍然没有边界检查，仍然没有登记表。

所以这一版先把这件事查干净：写一个门禁，把 `std/**/*.qma` 里所有
`static_word(...)` 的**实际槽位号**解析出来，按槽位归组。

解析要跨过三层间接，否则数出来的全是假象：

| 层 | 例子 | 只看字面量会怎样 |
| --- | --- | --- |
| 注释 | `const _SINK_W = 13  // static_word(13) = ...` | 把说明文字当成占用 |
| 常量 | `static_word(_SINK_W)` | 完全看不见 |
| 辅助函数 | `_get(w)` → `static_word(w)`，槽位在调用点 `_get(_SINK_W)` | 完全看不见 |

三层都解析之后，真实占用表是 32 个槽位里用了 30 个 —— **低区已经满了**。

## 病因：槽位总量不够，不是命名失误

把每个模块实际需要的槽位加起来：

| 模块 | 槽位数 |
| --- | --- |
| `std/logfile` | 11 |
| `std/log` | 9 |
| `std/http` / `ws` / `sse` 共享通道 | 1（共享） |
| `std/timer` | 2 |
| `std/sync` | 2 |
| 其余（gzip / rand / aes / reactor / net.core / park） | 6 |

合计 **33 个需求 vs 32 个槽位**。所以冲突不是"谁手滑写错了号"，
而是**装不下** —— 当时的表现就是四处抢槽：

| 槽位 | 抢槽的模块 | 后果 |
| --- | --- | --- |
| 13 / 14 | `std/log` ↔ `std/timer` | **静默崩溃**（实测） |
| 15 | `std/log` ↔ `std/net/reactor` | 日志打乱 reactor 状态块指针 |
| 28 / 29 | `std/log` ↔ `std/sync` | 日志打乱 park/wake 函数指针 |

13/14 那条是实测出来的：同时 `import std.log` 与 `std.timer`，
`log_info` 之后再无任何输出，进程直接死掉，**没有任何报错**。

## 改法

### 1. 槽位从 32 扩到 64

`STATIC_SLOTS = 64`（`qlm_native.py`）。每个槽位 8 字节，
扩一倍只是 256 字节静态区，代价可忽略；换掉"下次加模块又满"的循环。

### 2. 编译期越界检查

```python
if isinstance(arg, tuple) and arg and arg[0] == "num":
    if not (0 <= arg[1] < STATIC_SLOTS):
        raise SyntaxError(f"static_word({arg[1]}) 越界：...")
```

以前越界是**静默**的 —— 写到静态区之外，踩别的全局数据或崩，
编译器一句话都不说。现在字面量下标在编译期就报错：

```
SyntaxError: static_word(64) 越界：槽位下标必须在 0..63 之间（共 64 个槽位）
```

运行期变量（`static_word(n)`）没法静态判定，只能放行 —— 但门禁会
单独警告这种用法，因为它绕过了整个登记机制。

### 3. `std/log` 的 9 个槽位搬到 32–39

log 是可选设施，低区留给"用得更早"的模块。搬完之后：

- 13 / 14 → `std/timer`
- 15 → `std/net/reactor`
- 28 / 29 → `std/sync`
- 32–39 → `std/log`

### 4. 门禁 `tools/dev/check_static_words.py`

判据五条：越界、抢槽、未登记、登记过期、归属不符。
`REGISTRY` 是唯一权威，源码与它必须双向一致。

**唯一允许的共享**是 `static_word(0)` —— http / ws / sse 三个服务端框架
的回调通道（都是先 `mem_store64(static_word(0), 0, st)` 再在回调里读回）。
这是同一个机制、同一个槽，不是冲突，登记表里写成模块**列表**表示允许。

```
PASS：32 个 static_word 槽位无冲突、无越界、登记表与源码一致（共 64 个可用）
```

门禁已挂进 `tests/run_win_tests.py`（`case_static_word_registry`）。

## 夹具

`tests/t175_static_words.qma` 按"先 timer、再 log、再 rand、再堆分配"
的顺序复现过去那条崩溃路径，并验证 `static_word(0)` 与最后一个槽位
`static_word(63)` 读写正常。

`case_static_word_oob` 锁住"越界必须编译期报错"。

## 回归

全量 Windows 回归 PASS=339 FAIL=0 SKIP=0（v3.22 是 336，新增 3 条）。

## 遗留

- `.qla` 档案混链时，`_check_compatible` **不比较全局块大小**。
  旧档案的 `static` 仍是 32 字，新代码按 64 字写就会踩到下一个全局块。
  目前所有档案都由同一个编译器产出，碰不到；但这是真实隐患，
  记进 `07-gaps.md`。
- `static_word(0)` 的共享是"约定"，不是机制保证 —— 三个框架若同时
  在跑，回调通道会互相覆盖。要真正支持并发多协议得改成连接表，
  那是另一个量级的改动，暂不动。
