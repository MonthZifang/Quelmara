#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
链接期性能探针（v1.101，手动运行）
==================================
`load_program` 里的**链接层**（import 合并 + 限定引用解析 + per-module
mangling）是纯编译期的，运行时零开销。这个脚本量它到底花多少：

  1. 恒等路径：模块之间**没有**重名 —— 改名表为空，走的是既有路径
  2. mangling 路径：每个模块都定义同名函数 —— 触发前缀改名 + 引用重写
  3. 限定调用：主文件对每个模块各写一次 `mod.f()` 限定调用

三种场景的模块数 / 函数数完全相同（默认 40 模块 × 40 函数），所以差值就是
"多出来的那一步"的代价。只做纵向比较（本机 VBS 噪声 ±50%）。

跑法：python tools/dev/link_bench.py [--mods 40] [--fns 40] [--runs 5]
"""

import argparse
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm  # noqa: E402


def gen(root, mods, fns, same_names, qualified):
    """生成一个多模块工程：mods 个模块 × fns 个函数 + 一个主文件。"""
    names = []
    for m in range(mods):
        lines = ['module m%d' % m, '']
        for f in range(fns):
            # same_names=True 时每个模块都定义同名函数（触发 mangling）
            nm = f"f{f}" if same_names else f"f{m}_{f}"
            lines += [f"pub fn {nm}() -> int {{",
                      f"    return {m * 1000 + f}",
                      "}", ""]
        path = os.path.join(root, f"m{m}.qma")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        names.append((m, f"m{m}"))
    main = ["module bench", ""]
    for _m, imp in names:
        main.append(f"import {imp}")
    main += ["", "fn main() {", "    let mut acc = 0"]
    for m, imp in names:
        callee = "f0" if same_names else f"f{m}_0"
        # 重名时**必须**限定调用（未限定是歧义，编译期会报错）
        if qualified or same_names:
            main.append(f"    acc = acc + {imp}.{callee}()")
        else:
            main.append(f"    acc = acc + {callee}()")
    main += ["    print(acc.to_str())", "}", ""]
    main_path = os.path.join(root, "main.qma")
    with open(main_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(main))
    return main_path


def time_link(path, runs):
    best = None
    for _ in range(runs):
        t0 = time.perf_counter()
        qlm.load_program(path)
        dt = (time.perf_counter() - t0) * 1000.0
        best = dt if best is None else min(best, dt)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", type=int, default=40)
    ap.add_argument("--fns", type=int, default=40)
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()

    cases = [
        ("identity", False, False, "无重名、未限定（恒等路径）"),
        ("qualified", False, True, "无重名、全部限定调用（只多走限定解析）"),
        ("mangled", True, False, "每模块同名 f0..fN（mangling + 限定调用）"),
    ]
    print(f"模块数 {args.mods} × 每模块函数 {args.fns} 个"
          f"（共 {args.mods * args.fns} 个顶层函数），min of {args.runs}")
    print()
    base = None
    for key, same, qual, desc in cases:
        d = tempfile.mkdtemp(prefix=f"qlmlink_{key}_")
        try:
            path = gen(d, args.mods, args.fns, same, qual)
            ms = time_link(path, args.runs)
            if base is None:
                base = ms
            print(f"  {key:10s} {ms:8.1f} ms  ×{ms / base:4.2f}  {desc}")
        finally:
            shutil.rmtree(d, ignore_errors=True)
    print()
    print("说明：三档的解析量相同，差值就是链接层（改名表 + 引用重写 + 限定解析）")
    print("      的净开销；运行时零开销（改名只影响符号名）。")


if __name__ == "__main__":
    main()
