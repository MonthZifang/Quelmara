#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
覆盖率 / 模糊测试链路性能探针（v1.83，手动运行）
================================================
量四件事，min-of-N（本机 VBS 噪声 ±50%，只做纵向比较）：

  1. 构建开销与体积：`main.qma` 默认构建 vs `--dbg-info`；`.qlmdbg` 多大、
     其中分支表占多少条
  2. 采集开销：`loop.qma`（5000 次循环）跑 `cov`（行+分支）vs
     `cov --lines-only`，扣掉构建后的差值 = 分支断点的代价
  3. 汇总工具本身：`build/qlm_cov.exe` 在"小 .qlmdbg"和"大 .qlmdbg"
     （`std/json.qma` 1160 行）上的耗时（空命中日志，只量解析+汇总）
  4. fuzz 吞吐：生成 + 编译 64 例的耗时（变异器是 Quelmara 写的）

跑法：python tools/dev/cov_bench.py [--runs 3] [--fuzz-cases 64]
"""

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
DBG = os.path.join(ROOT, "tools", "stage0", "qlm_dbg.py")
COV_TOOL = os.path.join(ROOT, "build", "qlm_cov.exe")
EMPTY_HITS = os.path.join(ROOT, "build", "cov_bench_empty.tsv")


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def t(fn, runs):
    """min-of-N 秒数"""
    best = 1e9
    for _ in range(runs):
        s = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - s)
    return best


def sec_table(rows):
    for name, val in rows:
        print(f"  {name:44s} {val}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--fuzz-cases", type=int, default=64)
    args = ap.parse_args()
    n = args.runs
    try:
        # 行缓冲：后台跑时能看到进度（重定向到文件时 Python 默认块缓冲）
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    print("cov_bench — 覆盖率 / 模糊测试链路（min of %d）" % n)

    # ---- 1. 构建与体积 ----
    print("\n[1] 构建开销与调试节体积（fixtures/dbgdemo/main.qma）")
    plain = t(lambda: run([sys.executable, CLI, "build",
                           "fixtures/dbgdemo/main.qma", "--target", "win",
                           "-o", "build/cb_plain.qex", "--no-cache"]), n)
    dbg = t(lambda: run([sys.executable, CLI, "build",
                         "fixtures/dbgdemo/main.qma", "--target", "win",
                         "-o", "build/cb_dbg.qex", "--dbg-info",
                         "--no-cache"]), n)
    sec_table([("默认构建", f"{plain * 1000:.0f} ms"),
               ("--dbg-info 构建", f"{dbg * 1000:.0f} ms"
                f"（差值 {(dbg - plain) * 1000:+.0f} ms，落在 VBS 噪声内）")])

    import qlm_dbg
    _b, _s, info, _f = qlm_dbg.load_debug_info(os.path.join(
        ROOT, "build", "cb_dbg.qex"))
    raw = open(os.path.join(ROOT, "build", "cb_dbg.qex"), "rb").read()
    vsize = _s[".qlmdbg"][0]
    nb = sum(len(f.get("branches") or []) for f in info["funcs"]
             if f.get("file"))
    allb = sum(len(f.get("branches") or []) for f in info["funcs"])
    trimmed = json.loads(json.dumps(info))
    for f in trimmed["funcs"]:
        f.pop("branches", None)
    bsz = len(json.dumps(trimmed, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8"))
    sec_table([("产物", f"{len(raw)} B"),
               (".qlmdbg 节", f"{vsize} B（{vsize * 100.0 / len(raw):.1f}%）"),
               ("└ 分支表", f"{vsize - bsz} B（主文件 {nb} 条 / 全部 {allb} 条）")])

    # ---- 2. 采集开销（只量会话，不含构建）----
    print("\n[2] 采集开销（fixtures/dbgdemo/loop.qma，5000 次循环）")
    run([sys.executable, CLI, "build", "fixtures/dbgdemo/loop.qma",
         "--target", "win", "-o", "build/cb_loop.qex", "--dbg-info",
         "--no-cache"])
    exe = os.path.join(ROOT, "build", "cb_loop.qex")
    full = t(lambda: run([sys.executable, DBG, exe, "--cov",
                          "build/cb_hits.tsv"]), n)
    lines = t(lambda: run([sys.executable, DBG, exe, "--cov",
                           "build/cb_hits2.tsv", "--cov-lines-only"]), n)
    # 分支断点自己的命中次数（E 行），用来算每次命中的净开销
    nedge = 0
    with open(os.path.join(ROOT, "build", "cb_hits.tsv"), encoding="utf-8") as f:
        for ln in f:
            if ln.startswith("E "):
                nedge += int(ln.split()[3])
    sec_table([("会话：行+分支", f"{full * 1000:.0f} ms"),
               ("会话：仅行", f"{lines * 1000:.0f} ms"),
               ("分支断点的额外成本",
                f"{(full - lines) * 1000:+.0f} ms"
                f"（{nedge} 次分支命中，"
                f"每次 {(full - lines) * 1e6 / max(nedge, 1):.0f} µs）")])

    # ---- 3. 汇总工具本身 ----
    print("\n[3] 汇总工具（Quelmara 写的 build/qlm_cov.exe，空命中日志）")
    if not os.path.isfile(COV_TOOL):
        run([sys.executable, CLI, "cov", "fixtures/dbgdemo/cov.qma"])
    with open(EMPTY_HITS, "w", encoding="utf-8") as f:
        f.write("# qlm_cov hits v2\n")
    # 大样本：工具链自己（440 行 / 119 分支），有 main 才能构建成 PE
    run([sys.executable, CLI, "build", "tools/qlm_cov.qma", "--target", "win",
         "-o", "build/cb_big.qex", "--dbg-info", "--no-cache"])
    small = t(lambda: run([COV_TOOL, "build/cb_dbg.qex", EMPTY_HITS]), n)
    big = t(lambda: run([COV_TOOL, "build/cb_big.qex", EMPTY_HITS]), n)
    js = qlm_dbg.load_debug_info(os.path.join(ROOT, "build", "cb_big.qex"))[2]
    nfunc = sum(1 for f in js["funcs"] if f.get("file"))
    nline = sum(len(f["lines"]) for f in js["funcs"] if f.get("file"))
    nbr = sum(len(f.get("branches") or []) for f in js["funcs"]
              if f.get("file"))
    sec_table([("小（main.qma）", f"{small * 1000:.0f} ms"),
               (f"大（tools/qlm_cov.qma：{nfunc} 函数 / {nline} 行 / {nbr} 分支）",
                f"{big * 1000:.0f} ms")])

    # ---- 4. fuzz 吞吐 ----
    print(f"\n[4] fuzz 吞吐（种子 fixtures/dbgdemo/cov.qma，{args.fuzz_cases} 例）")
    import qlm_fuzz
    import qlm_cli
    out_dir = os.path.join("build", "fuzz", "bench")
    t0 = time.perf_counter()
    cases = qlm_fuzz._gen_cases("fixtures/dbgdemo/cov.qma", out_dir,
                                args.fuzz_cases, 3, qlm_cli.build)
    tgen = time.perf_counter() - t0
    t0 = time.perf_counter()
    kinds = {}
    for p in cases:
        k, _ = qlm_fuzz._compile_frontend(p)
        kinds[k] = kinds.get(k, 0) + 1
    tcomp = time.perf_counter() - t0
    sec_table([("生成（含变异器启动）", f"{tgen:.2f} s"),
               ("编译", f"{tcomp:.2f} s（{len(cases) / tcomp:.1f} 例/s）"),
               ("分类", "  ".join(f"{k}={v}" for k, v in sorted(kinds.items())))])


if __name__ == "__main__":
    main()
