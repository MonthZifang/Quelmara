# v3.24 — 收掉 v3.23 自己留下的隐患：`.qla` 链接不校验单例尺寸

- 日期：2026-10-30
- 任务：用户要求"继续"；v3.23 结束时登记在 `07-gaps.md` §4.2 的遗留项
- 影响面：**链接器**（`qlm_qla._check_compatible` 加一条尺寸一致性检查）
- 版本：按 `00-convention.md` §5.1 建版本目录

## 隐患是什么

v3.23 把 `static` 从 32 字扩到 64 字。当时留了一句话：

> `.qla` 档案混链时 `_check_compatible` **不比较全局块大小**。
> 旧档案的 `static` 仍是 32 字，新代码按 64 字写就会踩到下一个全局块。

道理是：链接期 `merge()` 把各档案的全局区**首尾拼接**，
`static` 这个"进程级单例"被重定向到第一个档案那一份：

```python
if name in spec0:
    mapping[gid + base] = spec0[name]   # 指向第一个档案的 static
```

于是所有代码都写第一份 `static`。如果第一份是 32 字、而某处代码按 64 字写
（`static_word(63)` → 基址 + 504），就会写到 `static` 块**之外**，
踩进紧邻的下一个全局块。

## 先查清楚：这个隐患到底能不能触发

不能凭想象改代码。写了个探针实测两种情况：

| 场景 | 构造方式 | 结果 |
| --- | --- | --- |
| A. 编译器指纹不同 | 把 `compiler` 改成假值 | **被拦下**（`_check_compatible` 的 `compiler` 比对） |
| B. 指纹相同、尺寸不同 | 指纹对齐，只把 `static` 砍回 32 字 | **链接成功** ← 隐患成立 |

A 之所以能拦，是因为编译器指纹是 `tools/stage0/*.py` 的**全内容哈希** ——
我改了 `qlm_native.py`，指纹就变了，旧档案自然链不上。所以
"升级编译器后旧档案错位"这条**实际上已被现有机制覆盖**。

但 B 说明兜底不成立：指纹只保证"同一份编译器"，不保证"同一块尺寸"。
真会出事的正是这种组合 —— 指纹算的是别的目录、档案被手工构造、
或者将来把某个单例的尺寸做成配置项。

## 改法

`_check_compatible` 加一段：所有档案里**同名单例**的块字节数必须相等。

```python
spec0 = first.special or {}
for a in arcs[1:]:
    for name, gid in (a.special or {}).items():
        if name not in spec0:
            continue
        g0, g1 = spec0[name], gid
        n0, n1 = len(first.globals[g0]), len(a.globals[g1])
        if n0 != n1:
            raise LinkError(f"档案不兼容：进程级单例 `{name}` 的尺寸不同 —— ...")
```

尺寸信息档案里现成（`global_len` 早就存了），比对一次是 O(特例数)，
代价可忽略。报错信息给的是**字节数**，不是槽位数 —— 因为这里只认字节。

实测输出：

```
档案不兼容：进程级单例 `static` 的尺寸不同 —— t175_static_words 是 512 字节，
<same-fp-32words> 是 256 字节（同名单例在所有档案里必须等长，否则链接后会错位踩内存）
```

## 为什么放在链接期而不是编译期

编译期只能看到**自己**这一份档案，看不到对面。尺寸不一致是**两份档案之间**
的关系，只有 `merge()` 同时持有它们时才判得了。

## 回归

`tests/qla_test.py` 新增 `test_singleton_size_mismatch()`，把上面 B 场景
固化成用例（指纹对齐 + `static` 砍回 32 字 → 必须 `LinkError`）。

QLA: PASS=33 FAIL=0（v3.23 是 32）。

## 顺带确认的一件事

v3.23 的探针还确认了 `_check_compatible` 的既有行为是对的：它比对
`arch / platform / opt / compiler` 四项，缺一项都会漏。这次只补"尺寸"，
没有动那四项。

## 遗留

`static_word(0)` 由 http / ws / sse **共享**作回调通道，这是**约定**不是
机制保证 —— 三者同时跑会互相覆盖。要真正支持并发多协议得改成连接表，
那是另一个量级的改动，仍挂在 `07-gaps.md` §4.2。
