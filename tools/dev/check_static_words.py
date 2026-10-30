#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`static_word(i)` 槽位登记表门禁（v3.23）。

## 为什么需要它

`static_word(i)` 返回"进程级第 i 个 8 字节静态字"的地址（共 32 个）。
它是语言里**唯一**的进程级可变全局通道 —— 协议库（http / ws / sse）、
日志、定时器、reactor 都靠它把状态放到回调能读到的位置。

**它没有边界检查，也没有登记表。** 实现是：

    off = i << 3
    addr = 静态区基址 + off

于是有两个静默失败模式：

1. **越界**：`static_word(120)` 会写到静态区之外，踩别的全局数据或崩。
2. **抢槽**：两个模块用了同一个 `i`，互相覆盖对方的状态指针。
   这种更常见，也更难查 —— 症状是"用了 A 之后 B 就坏了"，
   而两个模块的代码单独看都没问题。

v3.22 就踩到过一次（测试夹具借用了 120–123），
v3.23 复查时发现**四处真实抢槽**，其中一处会让 `std/log` + `std/timer`
同时使用时静默崩溃。

## 判据

扫描 `std/**/*.qma`，把每一处 `static_word(...)` 解析成**具体槽位号**，
按槽位归组。解析要跨过三层间接：

1. **注释** —— `// static_word(13) = ...` 这种说明文字不是占用。
2. **常量** —— `const _SINK_W = 13` 之后的 `static_word(_SINK_W)`。
3. **辅助函数** —— `log` 的状态全走 `_get(w)` / `_set(w, v)`，
   槽位号在**调用点**（`_get(_SINK_W)`）才定下来。

解析不出来的（参数是运行期变量）单独警告，因为它绕过了整个机制。

然后判定：

* 同一槽位被**多个模块**占用 → FAIL（抢槽）
* 槽位 ≥ 32 → FAIL（越界）
* 某模块占了槽位但**没在 REGISTRY 里登记** → FAIL（登记表过期）
* REGISTRY 里登记了但**源码里找不到** → FAIL（登记表过期）
* REGISTRY 记的模块与源码占用者不符 → FAIL（归属不符）

用法：
    python tools/dev/check_static_words.py          # 判定
    python tools/dev/check_static_words.py -v       # 打印完整槽位表
    python tools/dev/check_static_words.py --table  # 只打印源码实际占用（用于重建 REGISTRY）

退出码：0 = 通过 / 1 = 有冲突或登记表不一致。
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STD = os.path.join(ROOT, "std")
SLOTS = 64  # 与 qlm_native.py 的 STATIC_SLOTS 一致

CALL = re.compile(r"static_word\(\s*([A-Za-z_0-9]\w*)\s*\)")
CONST = re.compile(r"^\s*const\s+([A-Za-z_]\w*)\s*=\s*(\d+)\s*$", re.M)
# 顶层函数：fn name(params) / pub fn name(params)
FUNC = re.compile(r"^(?:pub\s+)?fn\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", re.M)

# ---------------------------------------------------------------------------
# 登记表：槽位 -> (模块列表, 用途)
#
# **这张表是唯一的权威**。加新槽位必须同时改这里与源码；
# 只改源码会被门禁打回，只改这里也会。
#
# 模块写成**列表**只允许一种情况：http / ws / sse 三个服务端框架
# **共享**同一个回调通道槽 —— 同一个机制、同一个槽，不是冲突。
# 除此之外任何共享都是 bug。
#
# v3.23 重排：原来 log 与 timer 抢 13/14、log 与 reactor 抢 15、
# log 与 sync 抢 28/29 —— 其中 log+timer 那条实测会让程序**静默崩溃**。
# ---------------------------------------------------------------------------
REGISTRY = {
    0:  (["std/http", "std/ws", "std/sse"],
         "连接状态块（三个服务端框架共享的回调通道）"),
    1:  (["std/http"], "解析失败码"),
    2:  (["std/http"], "路由/中间件表"),
    6:  (["std/gzip"], "CRC32 查表指针"),
    8:  (["std/rand"], "xorshift64* 状态（0 = 未播种）"),
    11: (["std/net/core"], "协议库全局自旋锁"),
    12: (["std/aes"], "sbox/inv_sbox 表指针"),
    13: (["std/timer"], "堆块指针"),
    14: (["std/timer"], "存活块指针"),
    15: (["std/net/reactor"], "reactor 全局状态块指针"),
    17: (["std/logfile"], "路径字节指针"),
    18: (["std/logfile"], "路径长度"),
    19: (["std/logfile"], "轮转阈值（字节）"),
    20: (["std/logfile"], "保留份数"),
    21: (["std/logfile"], "文件句柄（0=未打开 -1=失败）"),
    22: (["std/logfile"], "当前文件已写字节"),
    23: (["std/logfile"], "缓冲块指针"),
    24: (["std/logfile"], "缓冲已用字节"),
    25: (["std/logfile"], "累计轮转次数"),
    26: (["std/logfile"], "是否同时打控制台"),
    27: (["std/logfile"], "写锁句柄（0 = 还没建）"),
    28: (["std/sync"], "park 函数指针（park_on）"),
    29: (["std/sync"], "wake 函数指针（wake_all）"),
    30: (["std/park"], "WaitOnAddress 比较值槽"),
    32: (["std/log"], "首条日志 now_ns（相对模式基准）"),
    33: (["std/log"], "当前级别阈值"),
    34: (["std/log"], "输出通道（0=stdout 1=stderr）"),
    35: (["std/log"], "时区偏移（分钟）"),
    36: (["std/log"], "时间戳模式（0=绝对 1=相对）"),
    37: (["std/log"], "输出锁句柄（0 = 还没建）"),
    38: (["std/log"], "时间戳缓存块（惰性分配）"),
    39: (["std/log"], "时间戳缓存键（毫秒×2048+时区+1024）"),
}


def strip_comments(text):
    """去掉 // 行注释，但**尊重字符串字面量**（URL 里也有 //）。"""
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
        elif ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def std_files():
    out = []
    for base, _dirs, files in os.walk(STD):
        for f in files:
            if f.endswith(".qma"):
                out.append(os.path.join(base, f))
    return sorted(out)


def module_of(path):
    """`std/net/reactor.qma` -> `std/net/reactor`（与 REGISTRY 的写法一致）。"""
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    return rel[:-4] if rel.endswith(".qma") else rel


def module_consts(text):
    return {m.group(1): int(m.group(2)) for m in CONST.finditer(text)}


def passthrough_helpers(text):
    """找出"把 static_word 的槽位号当参数传进来"的函数。

    返回 {函数名: 参数名}，例如 log 的 `_get(w)` / `_set(w, v)`。
    这样 `_get(_SINK_W)` 才能被解析成槽位。
    """
    funcs = list(FUNC.finditer(text))
    helpers = {}
    for k, m in enumerate(funcs):
        start = m.end()
        end = funcs[k + 1].start() if k + 1 < len(funcs) else len(text)
        body = text[start:end]
        for raw in m.group(2).split(","):
            p = raw.split(":")[0].strip()
            if not p:
                continue
            if re.search(r"static_word\(\s*%s\s*\)" % re.escape(p), body):
                helpers[m.group(1)] = p
                break
    return helpers


def scan_module(text):
    """返回 (槽位集合, 无法解析的调用列表[(行号, 参数)])。"""
    text = strip_comments(text)
    consts = module_consts(text)
    helpers = passthrough_helpers(text)
    slots, unresolved = set(), []

    # 辅助函数体内的 static_word(形参) 不是"动态用法"，它是那条通道的
    # 实现本体（`_get(w)` / `_set(w, v)`）；真正要解析的是调用点。
    passthrough = set(helpers.values())

    for m in CALL.finditer(text):
        arg = m.group(1)
        if arg.isdigit():
            slots.add(int(arg))
        elif arg in consts:
            slots.add(consts[arg])
        elif arg in passthrough:
            continue  # 辅助函数形参，槽位由调用点决定
        else:
            line = text[:m.start()].count("\n") + 1
            unresolved.append((line, arg))

    # 辅助函数的调用点：_get(_SINK_W) -> 槽位
    for fn in helpers:
        for cm in re.finditer(r"\b%s\s*\(\s*([A-Za-z_0-9]\w*)" % re.escape(fn), text):
            arg = cm.group(1)
            if arg.isdigit():
                slots.add(int(arg))
            elif arg in consts:
                slots.add(consts[arg])
            elif arg in passthrough:
                continue  # 辅助函数转调另一个辅助函数，槽位更上一层决定
            else:
                line = text[:cm.start()].count("\n") + 1
                unresolved.append((line, "%s(%s)" % (fn, arg)))
    return slots, unresolved


def scan():
    """返回 (占用表{槽位: set(模块)}, 无法解析列表[(模块, 行号, 参数)])。"""
    used, unresolved = {}, []
    for path in std_files():
        mod = module_of(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        slots, bad = scan_module(text)
        for s in slots:
            used.setdefault(s, set()).add(mod)
        for line, arg in bad:
            unresolved.append((mod, line, arg))
    return used, unresolved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--table", action="store_true",
                    help="只打印源码实际占用（用于重建 REGISTRY）")
    args = ap.parse_args()

    used, unresolved = scan()

    if args.table:
        for idx in sorted(used):
            print(f"{idx:>3}  {', '.join(sorted(used[idx]))}")
        return 0

    fails = []

    # ---- 1. 越界 ----
    for idx in sorted(used):
        if idx < 0 or idx >= SLOTS:
            fails.append(f"越界：static_word({idx}) 超出 0..{SLOTS - 1}"
                         f"（{', '.join(sorted(used[idx]))}）")

    # ---- 2. 抢槽：同一槽位被多个模块用 ----
    # 例外：REGISTRY 里明确登记为**共享**的槽位（模块列表长度 > 1）。
    # 目前只有 static_word(0) —— http/ws/sse 三个服务端框架的回调通道。
    for idx in sorted(used):
        if len(used[idx]) > 1:
            declared = REGISTRY.get(idx, (None, None))[0]
            if isinstance(declared, list) and len(declared) > 1 \
                    and set(declared) == used[idx]:
                continue  # 登记为共享，且占用者与登记一致
            mods = ", ".join(sorted(used[idx]))
            fails.append(f"抢槽：static_word({idx}) 被多个模块占用 —— {mods}")

    # ---- 3. 登记表与源码不一致（双向）----
    for idx in sorted(used):
        if idx not in REGISTRY:
            mods = ", ".join(sorted(used[idx]))
            fails.append(f"未登记：static_word({idx}) 被 {mods} 使用，"
                         f"但 REGISTRY 里没有这一项")
    for idx in sorted(REGISTRY):
        if idx not in used:
            mods, what = REGISTRY[idx]
            fails.append(f"登记过期：REGISTRY 说 static_word({idx}) 属于 "
                         f"{', '.join(mods)}（{what}），但源码里找不到")

    # ---- 4. 登记表里的模块名与占用者不符 ----
    for idx in sorted(used):
        if idx in REGISTRY:
            declared = set(REGISTRY[idx][0])
            actual = used[idx]
            if declared != actual:
                fails.append(
                    f"归属不符：static_word({idx}) 源码里是 "
                    f"{', '.join(sorted(actual))}，REGISTRY 记的是 "
                    f"{', '.join(sorted(declared))}")

    # ---- 5. 无法解析的调用（警告，不判失败）----
    if unresolved:
        print(f"  [warn] {len(unresolved)} 处 static_word(...) 参数是运行期变量，"
              f"绕过登记机制、无法静态检查：")
        for mod, line, arg in unresolved:
            print(f"         {mod}:{line}  static_word({arg})")

    # ---- 输出 ----
    if args.verbose:
        print(f"{'idx':>3}  {'模块':<22} 用途")
        print("-" * 74)
        for idx in range(SLOTS):
            if idx in REGISTRY:
                mods, what = REGISTRY[idx]
                mark = "" if idx in used else "  [未使用]"
                print(f"{idx:>3}  {', '.join(mods):<22} {what}{mark}")
        print("-" * 74)
        print(f"共 {len(used)} 个槽位在用 / {SLOTS} 个可用")

    if fails:
        print(f"\nstatic_word 登记检查 FAIL（{len(fails)} 项）：")
        for f in fails:
            print("  -", f)
        print("\n修法：改源码避开冲突，或改 REGISTRY 登记（两边必须一致）。")
        return 1

    print(f"PASS：{len(used)} 个 static_word 槽位无冲突、无越界、"
          f"登记表与源码一致（共 {SLOTS} 个可用）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
