#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""所有权检查的编译期开销探针（v1.84）

用法：
  python tools/dev/own_bench.py [--runs 5] [源文件…]
  python tools/dev/own_bench.py --nested 32          # 深嵌套合成源，对照 _own_parts
  python tools/dev/own_bench.py --nested 32 --wide 40

测三件事：
  1. `check_ownership` 单遍耗时（monkeypatch 计时，只算这个 pass）；
  2. 端到端 `transpile_win`（读文件 → 解析 → 降级 → 编码）；
  3. `_own_parts` 助手的效果：把它换回"整条语句走一遍子树"的朴素写法
     （`return [s]`），同一份源上的差值就是"跳过已摊平块体"省下的时间。

为什么要单独测：所有权检查是纯编译期开销，程序运行时零成本。本机 VBS/Hyper-V
开启，进程冷启动 ~426 ms、噪声 ±50%，所以**只做纵向比较**（同一台机器、同一个
Python、同一进程内交替跑基线/新版），不引用绝对数字做跨机结论。
"""

import argparse
import os
import sys
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     os.pardir, os.pardir))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm_pe                      # noqa: E402
from qlm_native import Lower       # noqa: E402

DEFAULT_SRCS = ["tests/t116_ownview.qma", "tests/t106_weblib.qma",
                "examples/https_get.qma"]

_own_total = [0.0, 0]              # [秒, 调用次数]
_orig_check = Lower.check_ownership
_orig_parts = Lower._own_parts


def _timed(self, f):
    t0 = time.perf_counter()
    try:
        return _orig_check(self, f)
    finally:
        _own_total[0] += time.perf_counter() - t0
        _own_total[1] += 1


def _naive_parts(self, s):
    """v1.84 之前的写法：不区分"语句自己的表达式"和"已摊平的块体"。

    `_flat_stmts` 已经把嵌套块摊成一维，这里再对整条复合语句走一遍子树，
    嵌套层数就变成平方级重复遍历。
    """
    return [s]


def bench(src, runs):
    """返回 (端到端 min ms, 检查器 min ms, 被检查函数数)"""
    best = (1e9, 1e9, 0)
    for _ in range(runs):
        _own_total[0], _own_total[1] = 0.0, 0
        t0 = time.perf_counter()
        qlm_pe.transpile_win(os.path.join(ROOT, src))
        dt = (time.perf_counter() - t0) * 1000.0
        own = _own_total[0] * 1000.0
        if dt < best[0]:
            best = (dt, own, _own_total[1])
    return best


def gen_nested(depth, uses=4):
    """合成一份"深嵌套 + 每层都有视图使用"的源，专门放大重复遍历

    每层放 `uses` 条语句：朴素写法对第 k 层语句要走完 k 层以下的整棵子树，
    总访问量随深度平方增长；`_own_parts` 只走语句自己的表达式，是线性的。
    """
    L = ["module ownbench", "",
         "fn deep(n: int) -> int {",
         "    let mut a: [8]int = [0, 0, 0, 0, 0, 0, 0, 0]",
         "    let s = slice_of(a)",
         "    let mut acc = 0"]
    ind = "    "
    for i in range(depth):
        for j in range(uses):
            L.append(f"{ind}acc = acc + s[{j % 8}]")
        L.append(f"{ind}if n > {i} {{")
        ind += "    "
    for j in range(uses):
        L.append(f"{ind}acc = acc + s[{j % 8}]")
    for _ in range(depth):
        ind = ind[:-4]
        L.append(f"{ind}}}")
    L += ["    return acc", "}", "",
          "fn main() {",
          "    if deep(3) < 0 {",
          '        print("ownbench")',
          "    }",
          "}"]
    return "\n".join(L) + "\n"


def write_synthetic(depth, uses):
    d = os.path.join(ROOT, "build", "_ownbench")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"nested{depth}_u{uses}.qma")
    with open(p, "w", encoding="utf-8") as f:
        f.write(gen_nested(depth, uses))
    return p


def table(rows, runs):
    print(f"{'源文件':30s} {'端到端(ms)':>10s} {'检查器(ms)':>10s} "
          f"{'占比':>7s} {'函数数':>6s}")
    for src, dt, own, pct, n in rows:
        print(f"{src:30s} {dt:10.1f} {own:10.2f} {pct:6.2f}% {n:6d}")
    if rows:
        tot = sum(r[1] for r in rows)
        tot_own = sum(r[2] for r in rows)
        print(f"{'合计':30s} {tot:10.1f} {tot_own:10.2f} "
              f"{tot_own / tot * 100.0:6.2f}%")
    print(f"口径：min of {runs}，Python {sys.version.split()[0]}，"
          f"VBS 噪声 ±50%，只做纵向比较\n")


def _load_deep(src, depth_uses=8):
    """载入合成源，返回 (Lower 实例, deep 函数, 摊平后的语句数)"""
    from qlm import load_program
    _mod, _imp, fns_ast, _t, structs, enums, _o = load_program(src)
    low = Lower(fns_ast, {}, arch="x86_64", structs=structs, enums=enums)
    fn = [x for x in fns_ast if x["name"] == "deep"][0]
    flat = []
    low._flat_stmts(fn["body"], flat)
    return low, fn, len(flat)


def _min_ms(fn, n):
    best = 1e9
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        best = min(best, (time.perf_counter() - t0) * 1000.0)
    return best


def scale(depths, uses, n):
    """嵌套深度 → 检查器耗时：现版（_own_parts）vs 朴素（整条语句走子树）

    只计 `_check_views` 单遍（不含 rc 线性的 `scan`），min of `n`。
    """
    print(f"_own_parts 深度扫描（每层 {uses} 条语句，只计 _check_views，min of {n}）")
    print(f"{'嵌套深度':>8} {'摊平语句':>8} {'现版(ms)':>10} "
          f"{'朴素(ms)':>10} {'朴素/现版':>9}")
    for d in depths:
        p = write_synthetic(d, uses)
        low, fn, nflat = _load_deep(p)
        cur = _min_ms(lambda: low._check_views(fn, [], []), n)
        # 实例级覆盖：绑成单参闭包（类上赋值才会走描述符绑定）
        low._own_parts = lambda s: [s]
        nai = _min_ms(lambda: low._check_views(fn, [], []), n)
        del low._own_parts
        print(f"{d:8d} {nflat:8d} {cur:10.3f} {nai:10.3f} {nai / cur:8.2f}×")
    print()


def bytecheck(srcs):
    """运行时零成本的证据：开关所有权检查，产物 PE 逐字节相同"""
    import hashlib

    def digest(path):
        pe, _cfg = qlm_pe.transpile_win(path)
        return hashlib.sha256(pe).hexdigest()[:16], len(pe)

    print("产物对照（检查开 / 检查关，PE 字节）")
    print(f"{'源文件':30s} {'开(sha/字节)':>22} {'关(sha/字节)':>22} {'一致':>5}")
    for src in srcs:
        p = os.path.join(ROOT, src)
        if not os.path.exists(p):
            continue
        Lower.check_ownership = _orig_check
        a = digest(p)
        Lower.check_ownership = lambda self, f: None
        b = digest(p)
        Lower.check_ownership = _timed
        name = src if not os.path.isabs(src) else os.path.basename(src)
        print(f"{name:30s} {a[0]}/{a[1]:<8d} {b[0]}/{b[1]:<8d} "
              f"{'是' if a == b else '否':>4}")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--nested", type=int, default=0,
                    help="额外合成一个指定嵌套深度的源，做 _own_parts 对照")
    ap.add_argument("--uses", type=int, default=8,
                    help="合成源每层放几条语句")
    ap.add_argument("--scale", action="store_true",
                    help="只跑嵌套深度扫描（4/8/16/32），看 _own_parts 的复杂度差")
    ap.add_argument("--bytecheck", action="store_true",
                    help="只做产物逐字节对照（检查开 / 关），证明运行时零成本")
    ap.add_argument("--no-naive", action="store_true",
                    help="不做 _own_parts 朴素写法对照")
    ap.add_argument("srcs", nargs="*", default=None)
    a = ap.parse_args()

    Lower.check_ownership = _timed

    srcs = a.srcs if a.srcs else list(DEFAULT_SRCS)

    if a.scale:
        scale((4, 8, 16, 32), a.uses, 15)
        return
    if a.bytecheck:
        bytecheck(srcs)
        return

    if a.nested:
        srcs.append(write_synthetic(a.nested, a.uses))

    rows = []
    for src in srcs:
        if not os.path.exists(os.path.join(ROOT, src)):
            print(f"{src:30s} {'(缺文件，跳过)':>10s}")
            continue
        dt, own, n = bench(src, a.runs)
        pct = (own / dt * 100.0) if dt else 0.0
        rows.append((src if not os.path.isabs(src) else os.path.basename(src),
                     dt, own, pct, n))
    table(rows, a.runs)

    if a.no_naive:
        return

    # _own_parts 对照：同一份源，只换这一个助手
    print("_own_parts 对照（同一进程内交替，只算检查器自身耗时）")
    print(f"{'源文件':30s} {'现版(ms)':>9s} {'朴素(ms)':>9s} {'朴素/现版':>9s}")
    for src in srcs:
        if not os.path.exists(os.path.join(ROOT, src)):
            continue
        Lower._own_parts = _orig_parts
        _, cur, _ = bench(src, a.runs)
        Lower._own_parts = _naive_parts
        _, nai, _ = bench(src, a.runs)
        Lower._own_parts = _orig_parts
        ratio = (nai / cur) if cur else 0.0
        name = src if not os.path.isabs(src) else os.path.basename(src)
        print(f"{name:30s} {cur:9.2f} {nai:9.2f} {ratio:8.2f}×")


if __name__ == "__main__":
    main()
