#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc comment 链路的编译期开销探针（v1.92）。

三问：
  1. 扫全库 doc comment 要多久？（吞吐 MB/s）
  2. 单文件"词法"与"词法 + doc 扫描"差多少？（附加成本）
  3. 这笔开销占一次真实构建的多少？（占比，min of 3）

跑法：python tools/dev/doc_bench.py
口径：程序内 time.perf_counter，min of 5（构建 min of 3），
      本机 VBS 噪声大，**只做纵向比较**。
"""
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm  # noqa: E402


def min_of(fn, n=5):
    best = None
    for _ in range(n):
        t = time.perf_counter()
        fn()
        dt = (time.perf_counter() - t) * 1000.0
        best = dt if best is None else min(best, dt)
    return best


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "std", "**", "*.qma"),
                            recursive=True))
    srcs = [(p, open(p, encoding="utf-8").read()) for p in files]
    total_bytes = sum(len(s.encode("utf-8")) for _p, s in srcs)
    n_doc = sum(1 for _p, s in srcs for ln in s.splitlines()
                if ln.startswith("///"))
    print(f"[1] 全库 doc 扫描：{len(srcs)} 个文件 / {total_bytes / 1024:.1f} KB / "
          f"{n_doc} 行 `///`")

    def scan_all():
        for _p, s in srcs:
            qlm.scan_doc_comments(s)

    t_scan = min_of(scan_all)
    mbps = total_bytes / 1024 / 1024 / (t_scan / 1000.0)
    print(f"    耗时 {t_scan:.2f} ms（min of 5）  吞吐 {mbps:.1f} MB/s  "
          f"单文件均摊 {t_scan / len(srcs) * 1000:.0f} µs")

    # 同口径基线：全库词法（doc 扫描是"解析每个文件时多走一遍行"，拿词法当尺子）
    t_lex = min_of(lambda: [qlm.tokenize(s) for _p, s in srcs])
    print(f"    同一批文件全库词法 {t_lex:.0f} ms  →  doc 扫描是它的 "
          f"{t_scan / t_lex * 100:.1f}%")

    # [2] 单文件：词法 vs 词法 + doc 扫描
    big = max(srcs, key=lambda x: len(x[1]))
    name = os.path.relpath(big[0], ROOT).replace(os.sep, "/")
    print(f"[2] 最大文件 {name}（{len(big[1].splitlines())} 行）")
    t_tok = min_of(lambda: qlm.tokenize(big[1]))
    t_both = min_of(lambda: (qlm.tokenize(big[1]), qlm.scan_doc_comments(big[1])))
    t_doc = min_of(lambda: qlm.scan_doc_comments(big[1]))
    print(f"    词法 {t_tok:.2f} ms / doc 扫描 {t_doc:.2f} ms / "
          f"两者 {t_both:.2f} ms  →  doc 占词法 {t_doc / t_tok * 100:.0f}%")

    # [3] 真实构建：doc 扫描在整条编译链里的占比
    exe = os.path.join(ROOT, "build", "doc_bench.exe")
    src = os.path.join(ROOT, "examples", "hello.qma")
    cmd = [sys.executable, os.path.join(ROOT, "tools", "stage0", "qlm_cli.py"),
           "build", src, "--target", "win", "-o", exe]
    t_build = min_of(lambda: subprocess.run(cmd, cwd=ROOT, capture_output=True,
                                            check=True), n=3)
    print(f"[3] 构建 examples/hello.qma：{t_build:.0f} ms（min of 3）")
    if t_build > 0:
        print(f"    doc 扫描（全库 {t_scan:.2f} ms）占 {t_scan / t_build * 100:.2f}%"
              f"（构建要加载 std 全库，扫描按文件数线性摊开）")
    size = os.path.getsize(exe) if os.path.isfile(exe) else -1
    print(f"    产物 {size} B（doc comment 不进 IR：带/不带文档逐字节相同，"
          f"见 tests/doc_test.py）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
