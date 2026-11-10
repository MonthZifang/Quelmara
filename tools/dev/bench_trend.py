#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 CI 的 bench artifact 里提取若干个提交的跑分，并按 **C 归一化** 出趋势。

## 为什么需要它

CI 的 runner 机型**不固定** —— 实测相邻两次跑的同一份 C 基准能差 1.45–2.7 倍。
直接比较 quelmara 的绝对毫秒会得出"性能退化"的错误结论（v4.100 之后就被
这么误判过一次）。

**正确口径**：用同一 run 里的 C 作分母，比较 `quelmara / C` 这个比值。
C 和 quelmara 跑在同一台机器、同一个 run 里，机器差异在比值中被约掉。

## 用法

    # 比较两个 commit 的 CI 数据（需要 gh 已登录，且那两个 commit 跑过 bench）
    python tools/dev/bench_trend.py --sha b08a355 --sha 3d9bb01

    # 只给一个 sha，对比"当前工作区 vs 那个 sha"
    python tools/dev/bench_trend.py --sha b08a355 --local

    # 指定若干基准
    python tools/dev/bench_trend.py --sha a --sha b --only b3_recursion b34_bitops

## 判定

  · 比值变化 < ±10% → 视为"持平"（CI 噪声）
  · 同时打印 **C 参照列的变化**：若 C 自己就变了 >20%，说明换了机器，
    那一次的数据不可用于跨 run 比较。
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ART_NAME = "bench-windows"   # quelmara 列只在 windows job 里有
CACHE = os.path.join("/tmp", "qlm_ci_bench")


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True, cwd=ROOT)


def run_for_sha(sha):
    r = sh("git", "rev-parse", sha)
    if r.returncode != 0:
        return None
    full = r.stdout.strip()
    r = sh("gh", "run", "list", "--workflow=bench.yml", "--limit", "60",
           "--json", "databaseId,headSha")
    if r.returncode != 0:
        print("gh 不可用或未登录", file=sys.stderr)
        return None
    for row in json.loads(r.stdout or "[]"):
        if row["headSha"] == full:
            return row["databaseId"]
    return None


def fetch(run_id, sha):
    out = os.path.join(CACHE, str(run_id))
    md = os.path.join(out, "bench.md")
    if os.path.isfile(md):
        return md
    os.makedirs(out, exist_ok=True)
    r = sh("gh", "run", "download", str(run_id), "-n", ART_NAME, "-D", out)
    return md if os.path.isfile(md) else None


def parse(md):
    """→ {bench: (quelmara, c)}；列顺序是 quelmara|c|go|cpp|... """
    out = {}
    if not md:
        return out
    pat = re.compile(r"^\|\s*`(b[0-9a-z_]+)`[^|]*\|([^|]*)\|([^|]*)\|([^|]*)\|")
    for ln in open(md, encoding="utf-8", errors="replace"):
        m = pat.match(ln)
        if not m:
            continue
        b = m.group(1)
        try:
            q = float(m.group(3).strip())
            c = float(m.group(4).strip())
        except ValueError:
            continue
        out[b] = (q, c)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", action="append", default=[],
                    help="要比较的 commit（可多次给）")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()

    if len(args.sha) < 2:
        ap.error("至少给两个 --sha")

    series = []
    for s in args.sha:
        rid = run_for_sha(s)
        if rid is None:
            print(f"{s}: 找不到对应的 bench run（可能没跑过或已过期）", file=sys.stderr)
            series.append((s, {}))
            continue
        series.append((s, parse(fetch(rid, s))))

    names = args.only or sorted(set().union(*[set(d) for _, d in series]))
    hdr = "".join(f"{s:>16}" for s, _ in series)
    print(f"{'bench':18}{hdr}   判定")
    print("-" * (18 + 16 * len(series) + 8))
    for b in names:
        vals = []
        for _, d in series:
            vals.append(d.get(b))
        if any(v is None for v in vals):
            continue
        # 用 C 归一化
        ratios = [q / c for q, c in vals if c > 0]
        cells = "".join(f"{r:15.2f}x" for r in ratios)
        # C 自身的变化（检测换机器）
        cs = [c for _, c in vals]
        cmove = (cs[-1] / cs[0]) if cs[0] > 0 else 1.0
        first, last = ratios[0], ratios[-1]
        chg = (last / first - 1.0) * 100.0 if first > 0 else 0.0
        if abs(cmove - 1.0) > 0.20:
            verdict = f"机器变了(C {cmove:.2f}x)，不可比"
        elif abs(chg) < 10:
            verdict = "持平"
        elif chg > 0:
            verdict = f"退化 {chg:+.0f}%"
        else:
            verdict = f"改进 {chg:+.0f}%"
        print(f"{b:18}{cells}   {verdict}")
    print()
    print("说明：单元格是 **quelmara / C** 的比值（越小越好）。")
    print("      C 列自身变化 >20% 说明换机器了，那次数据不可跨 run 比较。")


if __name__ == "__main__":
    sys.exit(main())
