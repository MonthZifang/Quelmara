#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gzip 互操作验证：用 Python 标准库 zlib 解压 Quelmara 生成的 .gz 产物。

这是 gzip 编码器**唯一权威**的正确性证明——自校验只能证明格式形状，
解压回原字节才算数。

用法：
    python tests/gzip_interop.py            # 验证 build/gz_*.bin
    python tests/gzip_interop.py --keep     # 保留产物
"""
import argparse
import glob
import os
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.parse_args()

    bins = sorted(glob.glob(os.path.join(BUILD, "gz_*.bin")))
    if not bins:
        print("没有找到 build/gz_*.bin：请先跑 tests/t47_gzip.qma")
        return 2

    fail = 0
    for b in bins:
        name = os.path.basename(b)[:-4]
        src = os.path.join(BUILD, name + ".txt")
        raw = open(b, "rb").read()
        want = open(src, "rb").read()
        try:
            got = zlib.decompress(raw, 16 + zlib.MAX_WBITS)   # gzip 容器
        except Exception as e:                                # noqa: BLE001
            print(f"  [FAIL] {name}: 解压异常 {e!r}")
            fail += 1
            continue
        if got != want:
            print(f"  [FAIL] {name}: 字节不一致（原始 {len(want)}，解出 {len(got)}）")
            fail += 1
            continue
        ratio = (len(raw) / len(want)) if want else 0.0
        print(f"  [PASS] {name}: {len(want)} -> {len(raw)} B（{ratio:.2f}×）")

    print("-" * 56)
    print(f"PASS={len(bins) - fail} FAIL={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
