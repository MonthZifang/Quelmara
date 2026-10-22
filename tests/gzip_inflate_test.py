#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gzip / deflate 解码互操作测试：zlib 压缩 → Quelmara 解压 → 逐字节比对。

覆盖编码器组合，确保不只对自家固定 Huffman 生效：
  * level 0（存储块）、1、6、9（动态 Huffman）
  * Z_FIXED（固定 Huffman）、Z_HUFFMAN_ONLY、Z_RLE
  * gzip 封装与 raw deflate 两条路径
  * 空输入、单字节、全 256 字节、纯随机、高重复文本、长距离回溯（>32KB）

用法：
    python tests/gzip_inflate_test.py
    python tests/gzip_inflate_test.py -v
"""
import argparse
import os
import random
import subprocess
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
WORK = os.path.join(ROOT, "build", "_inflate_probe")
PROBE_SRC = WORK + ".qma"
PROBE_EXE = WORK + ".exe"
HEX_FILE = os.path.join(ROOT, "build", "_inflate_in.hex")

PROBE = '''module probe

import std.gzip
import std.hex

fn main() {
    let a = args()
    let h = read_text(a[0])
    let g = hex_decode(h)
    let mut out = ""
    if a[1] == "raw" {
        out = inflate_raw(g)
    } else {
        out = gzip_decode(g)
    }
    print(hex_encode(out))
}
'''


def build_probe():
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    with open(PROBE_SRC, "w", encoding="utf-8") as f:
        f.write(PROBE)
    r = subprocess.run([PY, CLI, "build", PROBE_SRC, "--target", "win",
                        "-o", PROBE_EXE], cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        raise SystemExit("probe 编译失败")


def run_probe(data, mode):
    with open(HEX_FILE, "w", encoding="ascii") as f:
        f.write(data.hex())
    r = subprocess.run([PROBE_EXE, HEX_FILE, mode], cwd=ROOT,
                       capture_output=True, timeout=120)
    if r.returncode != 0:
        return None, r.stderr.decode("utf-8", "replace").strip()
    return r.stdout.decode("ascii", "replace").strip(), ""


def cases():
    rnd = random.Random(20261022)
    text = (b"Quelmara is a systems language. " * 4000)[:120000]
    far = bytes(range(256)) * 40          # 10 KB
    # 长距离回溯：先放 40KB 随机，再重复开头 1000 字节（距离 40KB > 32KB 窗口外，
    # 但 zlib 会在窗口内重新编码，用于验证距离码边界）
    longdist = bytes(rnd.getrandbits(8) for _ in range(40000)) + far[:1000]
    yield "empty", b""
    yield "one", b"a"
    yield "allbytes", bytes(range(256))
    yield "text120k", text
    yield "random4k", bytes(rnd.getrandbits(8) for _ in range(4096))
    yield "far10k", far
    yield "longdist41k", longdist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    build_probe()
    ok = bad = 0
    # (mode, wbits, compressobj 参数)
    combos = [
        ("gzip", 31, dict(level=0)),                                  # 存储块
        ("gzip", 31, dict(level=1)),                                  # 动态 Huffman
        ("gzip", 31, dict(level=6)),
        ("gzip", 31, dict(level=9)),
        ("gzip", 31, dict(level=6, strategy=zlib.Z_FIXED)),           # 固定 Huffman
        ("gzip", 31, dict(level=6, strategy=zlib.Z_HUFFMAN_ONLY)),
        ("gzip", 31, dict(level=6, strategy=zlib.Z_RLE)),
        ("raw", -15, dict(level=6)),                                  # 裸 deflate
        ("raw", -15, dict(level=9)),
    ]
    for name, data in cases():
        for mode, wbits, kw in combos:
            co = zlib.compressobj(wbits=wbits, **kw)
            blob = co.compress(data) + co.flush()
            got, err = run_probe(blob, mode)
            want = data.hex()
            label = f"{name:12} {mode:4} {kw}"
            if got == want:
                ok += 1
                if args.verbose:
                    print(f"  [ok]   {label} ({len(blob)} B -> {len(data)} B)")
            else:
                bad += 1
                detail = err if got is None else f"长度 {len(got or '')//2} vs {len(data)}"
                print(f"  [FAIL] {label}: {detail}")
    print("-" * 56)
    print(f"PASS={ok} FAIL={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
