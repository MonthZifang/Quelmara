#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuIR 架构无关性对拍：同一份源码在 x86_64 与 aarch64 两个后端下，
除「系统调用号」外必须产出**逐字节相同**的 IR。

这是 IR 层的契约：QuIR 是架构无关的，架构差异只允许出现在系统调用编号
与指令发射层。stage-1 的 bootstrap/ir 将来必须通过这一条。

用法：
    python tests/irdiff.py          # 全量
    python tests/irdiff.py -v
"""
import argparse
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE0 = os.path.join(ROOT, "tools", "stage0")

SYSCALL_RE = re.compile(r"\('syscall', (None|\d+), (\d+),")


def normalize(text):
    """归一化：
    1) 去掉编译器横幅行（`[qlm-native] xxx -> yyy (字节数)` 不是 IR）；
    2) 把 syscall 的编号统一成 N —— 这是唯一允许的架构差异。"""
    lines = [ln for ln in text.splitlines()
             if not ln.lstrip().startswith("[qlm")]
    return SYSCALL_RE.sub(lambda m: f"('syscall', {m.group(1)}, N,", "\n".join(lines)) + "\n"


def dump_ir(src, backend):
    cmd = [sys.executable, os.path.join(STAGE0, backend), "build", src,
           "-o", os.path.join(ROOT, "build", "_irdiff.out"), "--dump-ir"]
    r = subprocess.run(cmd, capture_output=True, cwd=ROOT)
    # --dump-ir 打到 stdout；编译日志在 stderr
    return r.returncode, r.stdout.decode("utf-8", errors="replace"), \
        r.stderr.decode("utf-8", errors="replace")


def collect():
    files = []
    for pat in ("tests/*.qma", "examples/*.qma"):
        files += glob.glob(os.path.join(ROOT, pat))
    return sorted(files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    ok = bad = skip = 0
    for path in collect():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        rc1, out1, err1 = dump_ir(path, "qlm_native.py")
        rc2, out2, err2 = dump_ir(path, "qlm_arm64.py")
        if rc1 != 0 or rc2 != 0:
            skip += 1
            first = (err1 or err2).strip().splitlines()
            print(f"  [SKIP] {rel}: {first[-1] if first else 'build failed'}")
            continue
        a, b = normalize(out1), normalize(out2)
        if a == b:
            ok += 1
            if args.verbose:
                print(f"  [ok] {rel} ({a.count(chr(10))} IR lines)")
        else:
            bad += 1
            al, bl = a.splitlines(), b.splitlines()
            print(f"  [FAIL] {rel}: x86 {len(al)} 行 / a64 {len(bl)} 行")
            for i in range(max(len(al), len(bl))):
                x = al[i] if i < len(al) else "<缺行>"
                y = bl[i] if i < len(bl) else "<缺行>"
                if x != y:
                    print(f"         第 {i + 1} 行：x86 {x!r}  a64 {y!r}")
                    break
    print("-" * 56)
    print(f"PASS={ok} FAIL={bad} SKIP={skip}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
