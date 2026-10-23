#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双向 .qex 对照：同一批 .qma 在「基线 worktree」与「本版 worktree」各编译一次，比产物字节。

为什么需要它：性能/发射层改动的"没退化"不能靠读代码断言。逐字节比产物是唯一
不依赖跑分噪声的证据——本机 VBS 噪声 ±50%，而哈希没有噪声。

判定：
  SAME     两边都编译成功且 .qex 逐字节相同（改动没波及这条源文件）
  DIFF     两边都成功但字节不同（须人工确认只出现在本版预期的那几个上）
  NEWFILE  源文件只在本版存在（本版新增的夹具/基准）——不是 fail-fast 证据
  ONE      源文件两边都有，但只有一边编译成功（基线拒绝新语法 = fail-fast 生效）
  BOTHFAIL 两边都编译失败（语料里的 bad 夹具，正常）

用法：
    git worktree add ../qbase HEAD          # 基线
    # 在另一个 worktree 上叠加本版改动
    python tools/dev/qexcmp.py ../qbase .                     # 当前目录作"本版"
    python tools/dev/qexcmp.py ../qbase . --dirs tests,bench   # 限定语料目录

退出码：有 DIFF 或 ONE 时为 1（ONE 也算"要人看一眼"），全 SAME 时为 0。
产物落在 <临时目录>/qexcmp/<base|new>/，跑完可整个删掉。
"""
import argparse
import hashlib
import os
import subprocess
import sys
import tempfile

DIRS = ("tests", "examples", "bench")


def build(wt, rel, out_dir, tag):
    out = os.path.join(out_dir, tag, rel.replace(os.sep, "_") + ".qex")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(wt, "tools", "stage0", "qlm_cli.py"),
                        "build", os.path.join(wt, rel), "--target", "win", "-o", out],
                       capture_output=True, text=True, cwd=wt)
    if r.returncode != 0 or not os.path.exists(out):
        lines = (r.stdout + r.stderr).strip().splitlines()
        return None, (lines[-1] if lines else ""), None
    data = open(out, "rb").read()
    return hashlib.sha256(data).hexdigest(), None, len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="基线 worktree（干净 HEAD）")
    ap.add_argument("new", help="本版 worktree（HEAD + 本版改动）")
    ap.add_argument("--dirs", default=",".join(DIRS), help="语料目录，逗号分隔")
    ap.add_argument("--out", default=None, help="产物目录（默认系统临时目录）")
    args = ap.parse_args()

    base, new = os.path.abspath(args.base), os.path.abspath(args.new)
    out_dir = args.out or os.path.join(tempfile.gettempdir(), "qexcmp")
    corpus = []
    for d in [x.strip() for x in args.dirs.split(",") if x.strip()]:
        p = os.path.join(new, d)
        if not os.path.isdir(p):
            continue
        for f in sorted(os.listdir(p)):
            if f.endswith(".qma"):
                corpus.append(os.path.join(d, f))

    same = diff = one = bothfail = newfile = 0
    diffs, ones, newfiles = [], [], []
    for rel in corpus:
        if not os.path.exists(os.path.join(base, rel)):
            # 源文件只在本版存在：两边"编译结果不同"是因为基线根本没这个文件，
            # 不能算作基线 fail-fast 的证据（这一格踩过一次，别混）。
            newfile += 1
            newfiles.append(rel)
            continue
        hb, eb, sb = build(base, rel, out_dir, "base")
        hn, en, sn = build(new, rel, out_dir, "new")
        if hb and hn:
            if hb == hn:
                same += 1
            else:
                diff += 1
                diffs.append((rel, sb, sn))
        elif hb or hn:
            one += 1
            ones.append((rel, "base-only" if hb else "new-only", eb or en or ""))
        else:
            bothfail += 1

    print(f"SAME={same} DIFF={diff} ONE={one} NEWFILE={newfile} "
          f"BOTHFAIL={bothfail} TOTAL={len(corpus)}")
    if newfiles:
        print("\n-- NEWFILE（源文件只在本版存在）--")
        for rel in newfiles:
            print(f"  {rel}")
    if diffs:
        print("\n-- DIFF（两边都成功、字节不同）--")
        for rel, sb, sn in diffs:
            print(f"  {rel}  base={sb}B new={sn}B")
    if ones:
        print("\n-- ONE（只有一边编译成功）--")
        for rel, which, err in ones:
            print(f"  {rel}  {which}  {err[:100]}")
    return 1 if (diff or one) else 0


if __name__ == "__main__":
    sys.exit(main())
