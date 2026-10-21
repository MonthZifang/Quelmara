#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage-1 parser 对拍：函数体 S 表达式（Phase 1 核心子集）函数级匹配统计。

匹配语义（每函数一行结论）：
  MATCH        两侧 dump 的语句协议行完全一致
  SKIP-SYNC    两侧都判 SKIP（同判"超出 Phase 1 覆盖"）
  SKIP-MISMATCH  一侧 SKIP 一侧 dump——一侧判据与另一侧不同步
  MISMATCH     两侧都 dump 但语句行不同——解析语义分叉

绿的标准：MISMATCH = 0 且 SKIP-MISMATCH = 0（SKIP-SYNC 允许，Phase 2 收编）。
"""
import glob
import subprocess
import sys

QEX = "build/_qp.qex"


def collect():
    a_lines, b_lines = {}, {}
    files = sorted(glob.glob("tests/*.qma") + glob.glob("examples/*.qma"))
    # stage-0：astbody 一次跑全量
    r = subprocess.run([sys.executable, "tools/dev/astbody.py"] + files,
                       capture_output=True, text=True, errors="replace")
    for ln in r.stdout.splitlines():
        if not ln.startswith(("tests/", "examples/")):
            continue
        body = ln.split(" ", 1)[1] if " " in ln else ln
        key = body.split(" ", 1)[0] if " " in body else body  # fn name#i / fn name
        a_lines.setdefault(ln.split(" ", 1)[1].split(" ")[0] if " " in ln else "?", [])
        a_lines.setdefault(body.split(" ", 1)[0], []).append(body.split(" ", 1)[1] if " " in body else "")
    # stage-1：逐文件跑 --body
    for f in files:
        r = subprocess.run([QEX, "--body", f], capture_output=True, text=True,
                           errors="replace")
        for ln in r.stdout.splitlines():
            if not ln.startswith("fn "):
                continue
            key = ln.split(" ", 1)[0]
            b_lines.setdefault(key, []).append(ln.split(" ", 1)[1] if " " in ln else "")
    return files, a_lines, b_lines


def main():
    files, a, b = collect()
    # stage-0 的键是 fn 名（astbody 输出按 fn 分组需重排——直接用行序列）
    # 改为行级集合比对 + 函数级结论统计
    match = skip_sync = skip_mis = mis = 0
    mismatches = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                src = fh.read()
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "tools", "stage0"))
            import qlm  # noqa
            _, _, fns, _, _, _, _ = qlm.parse_source(src)
        except Exception:
            continue
        for fn in fns:
            nm = fn["name"]
            a_rows = [ln.split(" ", 1)[1] for ln in
                      (r.stdout for r in [subprocess.run])] if False else None
    # 简化：整体行集合比对
    r = subprocess.run([sys.executable, "tools/dev/astbody.py"] + files,
                       capture_output=True, text=True, errors="replace")
    a_set = set()
    for ln in r.stdout.splitlines():
        if " " in ln and ln.split(" ", 1)[0].endswith(".qma"):
            body = ln.split(" ", 1)[1]          # 去路径
            a_set.add(body.split(" ", 1)[1])    # 去 "fn <name>" 前缀，只留语句 S 表达式
    b_set = set()
    for f in files:
        r = subprocess.run([QEX, "--body", f], capture_output=True, text=True,
                           errors="replace")
        for ln in r.stdout.splitlines():
            if ln.startswith("fn "):
                b_set.add(ln[3:])
    skip_a = {x for x in a_set if x.endswith(" SKIP")}
    skip_b = {x for x in b_set if x.endswith(" SKIP")}
    dump_a = a_set - skip_a
    dump_b = b_set - skip_b
    sync = len(skip_a & skip_b)
    skip_mis = len(skip_a ^ skip_b)
    mis = len(dump_a ^ dump_b)
    print(f"函数体协议对拍（Phase 1 核心子集）")
    print(f"  dump 一致   : {len(dump_a & dump_b)}")
    print(f"  SKIP 同步   : {sync}")
    print(f"  SKIP 不同步 : {skip_mis}")
    print(f"  dump 分叉   : {mis}")
    if mis:
        only_a = sorted(dump_a - dump_b)[:6]
        only_b = sorted(dump_b - dump_a)[:6]
        print("  仅 stage-0 :", *only_a, sep="\n    ")
        print("  仅 stage-1 :", *only_b, sep="\n    ")
    return 0 if (mis == 0 and skip_mis == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
