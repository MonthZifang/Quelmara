#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试链路性能探针（v1.71，手动运行）
==================================
量四件事，全部 min-of-N，只做纵向比较（本机 VBS 噪声 ±50%）：

  1. 构建开销：默认构建 vs `--dbg-info`（多出的部分是行号钩子 + 变量表 +
     `.qlmdbg` + DWARF 编码）
  2. 产物体积：`.text` / `.qlmdbg` / 四个 `.debug_*` 各占多少
  3. 每次断点命中的净开销（5000 次 continue 穿过循环体）
  4. 每次源码行单步的净开销（2000 次 next 在循环里绕）

3/4 都减掉了"启动 + 加载调试信息 + 跑到退出"的固定开销，差值除以次数。
跑法：python tools/dev/dbg_bench.py [--runs 3] [--hits 500] [--steps 100]
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

SRC = "fixtures/dbgdemo/main.qma"
LOOP = "fixtures/dbgdemo/loop.qma"
LOOP_LINE = 11                    # while 循环体第一行（acc = acc + i）
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
DBG = os.path.join(ROOT, "tools", "stage0", "qlm_dbg.py")


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def time_build(src, dbg, runs):
    best = 1e9
    for _ in range(runs):
        out = os.path.join(ROOT, "build", "bench_dbg_tmp.exe")
        cmd = [sys.executable, CLI, "build", src, "--target", "win", "-o", out]
        if dbg:
            cmd.append("--dbg-info")
        t = time.perf_counter()
        r = run(cmd)
        dt = (time.perf_counter() - t) * 1000
        if r.returncode != 0:
            raise SystemExit(f"构建失败: {r.stderr[-400:]}")
        best = min(best, dt)
    return best


def time_session(script_lines, runs, exe):
    best = 1e9
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as f:
        f.write("\n".join(script_lines) + "\n")
        path = f.name
    try:
        for _ in range(runs):
            t = time.perf_counter()
            r = run([sys.executable, DBG, exe, "--script", path])
            dt = (time.perf_counter() - t) * 1000
            if r.returncode not in (0, 1):
                raise SystemExit(f"调试失败: {r.stdout[-400:]}{r.stderr[-400:]}")
            best = min(best, dt)
    finally:
        os.unlink(path)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--hits", type=int, default=5000)
    ap.add_argument("--steps", type=int, default=2000)
    a = ap.parse_args()

    exe = os.path.join(ROOT, "build", "bench_dbg.exe")
    r = run([sys.executable, CLI, "build", SRC, "--target", "win",
             "--dbg-info", "-o", exe])
    if r.returncode != 0:
        raise SystemExit(r.stderr[-600:])
    lexe = os.path.join(ROOT, "build", "bench_dbg_loop.exe")
    r = run([sys.executable, CLI, "build", LOOP, "--target", "win",
             "--dbg-info", "-o", lexe])
    if r.returncode != 0:
        raise SystemExit(r.stderr[-600:])

    t_plain = time_build(SRC, False, a.runs)
    t_dbg = time_build(SRC, True, a.runs)
    print(f"构建（min of {a.runs}，{SRC}）")
    print(f"  默认         {t_plain:8.1f} ms")
    print(f"  --dbg-info   {t_dbg:8.1f} ms   （{t_dbg - t_plain:+.1f} ms，"
          f"×{t_dbg / t_plain:.2f}）")

    import qlm_dbg
    _b, secs, _d = qlm_dbg.parse_pe(exe)
    total = os.path.getsize(exe)
    text = secs[".text"][0]
    qdbg = secs[".qlmdbg"][0]
    dwarf = sum(v[0] for k, v in secs.items() if k.startswith(".debug_"))
    print(f"\n体积（{SRC}，--dbg-info）")
    print(f"  文件总计     {total:8d} B")
    print(f"  .text        {text:8d} B")
    print(f"  .qlmdbg      {qdbg:8d} B   （{qdbg / total * 100:.1f}%）")
    print(f"  .debug_*     {dwarf:8d} B   （{dwarf / total * 100:.1f}%）")

    bp = f"break loop.qma:{LOOP_LINE}"
    t0 = time_session([bp, "run", "continue", "quit"], a.runs, lexe)
    t_hits = time_session([bp, "run"] + ["continue"] * a.hits + ["quit"],
                          a.runs, lexe)
    t_steps = time_session([bp, "run"] + ["next"] * a.steps + ["quit"],
                           a.runs, lexe)

    print(f"\n调试会话（min of {a.runs}，含 Python 解释器启动 ~1.4 s）")
    print(f"  固定开销（1 次命中）      {t0:9.1f} ms")
    print(f"  +{a.hits} 次断点命中       {t_hits:9.1f} ms   "
          f"每命中 {(t_hits - t0) / (a.hits - 1) * 1000:7.1f} µs")
    print(f"  +{a.steps} 次 next         {t_steps:9.1f} ms   "
          f"每步   {(t_steps - t0) / a.steps * 1000:7.1f} µs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
