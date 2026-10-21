#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage-1 parser 支持矩阵：从 stage-0 dump 提取所有语句形态，逐条生成
mini 文件喂给 _qp.qex --body，报告 SKIP / dump / 分叉。输出按"顶层节点类型"
聚类，定位最该修的解析模式。用法：python tests/bodymatrix.py
"""
import glob
import re
import subprocess
import sys

QEX = "build/_qp.qex"


def top_kind(stmt):
    m = re.match(r"\((\w+)", stmt)
    return m.group(1) if m else "?"


def mini_src(stmt):
    return ("module m\n"
            "fn f(s: str, i: int) -> int {\n"
            "    " + stmt + "\n"
            "    return 0\n"
            "}\n")


def main():
    files = sorted(glob.glob("tests/*.qma") + glob.glob("examples/*.qma"))
    r = subprocess.run([sys.executable, "tools/dev/astbody.py"] + files,
                       capture_output=True, text=True, errors="replace")
    stmts = set()
    for ln in r.stdout.splitlines():
        if " " not in ln or not ln.split(" ", 1)[0].endswith(".qma"):
            continue
        body = ln.split(" ", 1)[1]
        parts = body.split(" ", 2)
        if len(parts) < 3:
            continue
        s = parts[2].strip()
        if s.endswith(" SKIP") or s == "SKIP":
            continue
        stmts.add(s)
    # 聚类：按顶层 kind + 形状签名（去字面量）取代表
    groups = {}
    for s in stmts:
        k = top_kind(s)
        sig = (k, re.sub(r"\(num \d+\)", "(num N)", s)[:70])
        groups.setdefault(sig, s)
    # 批处理：每批 16 个形态合成一个文件（每个形态一个 fn），一次子进程跑完
    # （PE 冷启动 ~350ms，逐形态跑会乘出来几分钟）
    keys = sorted(groups)
    results = {}
    BATCH = 16
    for bi in range(0, len(keys), BATCH):
        batch = keys[bi:bi + BATCH]
        src = "module mx\n"
        names = []
        for j, sig in enumerate(batch):
            s = groups[sig]
            src += (f"fn mx{j}(s: str, i: int) -> int {{\n"
                    "    " + s + "\n"
                    "    return 0\n"
                    "}\n")
            names.append((f"mx{j}", sig))
        with open("build/_mx.qma", "w", encoding="utf-8") as f:
            f.write(src)
        r = subprocess.run([QEX, "--body", "build/_mx.qma"],
                           capture_output=True, text=True, errors="replace")
        got = {}
        for ln in r.stdout.splitlines():
            if not ln.startswith("fn mx"):
                continue
            parts = ln.split(" ", 1)
            got.setdefault(parts[0], []).append(parts[1].strip())
        for fname, sig in names:
            rows = got.get(fname, [])
            skipped = any(x == "SKIP" for x in rows)
            s = groups[sig]
            if skipped:
                results[sig] = ("SKIP", s)
            elif any(x == s for x in rows):
                results[sig] = ("OK", s)
            else:
                results[sig] = ("分叉", s, rows[0] if rows else "<空>")
    ok = sum(1 for v in results.values() if v[0] == "OK")
    skip = sum(1 for v in results.values() if v[0] == "SKIP")
    dif = sum(1 for v in results.values() if v[0] == "分叉")
    print(f"语句形态 {len(results)}：OK {ok} / SKIP {skip} / 分叉 {dif}\n")
    print("== SKIP 模式（stage-1 需要支持的） ==")
    for sig, v in sorted(results.items()):
        if v[0] == "SKIP":
            print(f"  {v[1][:100]}")
    print("\n== 分叉模式（dump 出来但形态不同） ==")
    for sig, v in sorted(results.items()):
        if v[0] == "分叉":
            print(f"  期望: {v[1][:80]}")
            print(f"    得: {v[2][:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
