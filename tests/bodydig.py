#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bodydiff 的深挖工具：对单个/多个文件，逐函数并排输出 stage-0 与 stage-1
的函数体协议行，标出第一个分叉语句。用法：
    python tests/bodydig.py tests/t30_xxx.qma        # 单文件逐函数并排
    python tests/bodydig.py --summary                # 全量：按函数名列出两侧是否一致
"""
import glob
import subprocess
import sys

QEX = "build/_qp.qex"


def stage0_dump(files):
    """astbody：输出 'path fnname stmt' 行 -> {fname: [stmt,...]}"""
    r = subprocess.run([sys.executable, "tools/dev/astbody.py"] + files,
                       capture_output=True, text=True, errors="replace")
    out = {}
    for ln in r.stdout.splitlines():
        if " " not in ln or not ln.split(" ", 1)[0].endswith(".qma"):
            continue
        body = ln.split(" ", 1)[1]
        parts = body.split(" ", 2)
        if len(parts) < 3:
            continue
        fname, stmt = parts[1], parts[2]
        out.setdefault(fname, []).append(stmt)
    return out


def stage1_dump(files):
    out = {}
    for f in files:
        r = subprocess.run([QEX, "--body", f], capture_output=True, text=True,
                           errors="replace")
        for ln in r.stdout.splitlines():
            if ln.startswith("fn "):
                parts = ln[3:].split(" ", 1)
                if len(parts) < 2:
                    continue
                out.setdefault(parts[0], []).append(parts[1])
    return out


def main():
    import re

    def strip_n(n):
        return re.sub(r"#\d+$", "", n)

    if sys.argv[1] == "--summary":
        files = sorted(glob.glob("tests/*.qma") + glob.glob("examples/*.qma"))
        a_raw = stage0_dump(files)
        b_raw = stage1_dump(files)
        # 键对齐：stage-0 同名函数带 #N 序号，stage-1 不带——剥掉后按
        # （名字, 出现序）对齐。同名多函数（impl 展开的 area 等）按
        # 字典序配对（两侧同名集合内各按语句串排序匹配）。
        a, b = {}, {}
        for k, v in a_raw.items():
            a.setdefault(strip_n(k), []).append(v)
        for k, v in b_raw.items():
            b.setdefault(strip_n(k), []).append(v)
        names = sorted(set(a) | set(b))
        bad = []
        for n in names:
            la, lb = a.get(n), b.get(n)
            # 每个名字下可能有多份（重载/展开）：集合级比较
            seta = {tuple(rows) for rows in (la or [])}
            setb = {tuple(rows) for rows in (lb or [])}
            if seta == setb:
                continue
            onlya = seta - setb
            onlyb = setb - seta
            fa = next(iter(onlya)) if onlya else ("<缺>",)
            fb = next(iter(onlyb)) if onlyb else ("<缺>",)
            bad.append((n, len(onlya), len(onlyb), fa[0], fb[0]))
        print(f"总函数名 {len(names)}，不一致 {len(bad)}")
        for n, na, nb, fa, fb in bad:
            print(f"  [x] {n} (仅s0:{na} 仅s1:{nb})")
            if fa and fa != "<缺>":
                print(f"      s0: {fa[:90]}")
            if fb and fb != "<缺>":
                print(f"      s1: {fb[:90]}")
        return 0
    files = sys.argv[1:]
    a = stage0_dump(files)
    b = stage1_dump(files)
    for n in sorted(set(a) | set(b)):
        ra, rb = a.get(n), b.get(n)
        if ra == rb:
            continue
        print(f"=== {n} ===")
        for i in range(max(len(ra or []), len(rb or []))):
            sa = ra[i] if ra and i < len(ra) else "<缺>"
            sb = rb[i] if rb and i < len(rb) else "<缺>"
            mark = "  " if sa == sb else "!!"
            print(f"{mark} s0: {sa}")
            if sa != sb:
                print(f"{mark} s1: {sb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
