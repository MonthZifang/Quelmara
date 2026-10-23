#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增量 / 并行编译的性能探针（v1.90）
=================================
回答三个问题，全部实测，不做理论推算：

  1. **缓存命中**比全量重编快多少（单单元：冷 vs 热）
  2. **并行构建**比串行快多少（16 个单元：`-j 1` vs `-j 8`）
  3. 缓存本身占多大、命中率多少

两个口径都记，因为它们的差别本身就是结论：

- **墙钟**：用户真正等待的时间，含 Python 进程启动（本机 VBS 开启，冷启动
  1.1–1.5 s 且抖动大）。小单元的下限就是这段启动，缓存再快也压不下去。
- **编译阶段**：编译器自己报的耗时（`重编 N ms` / `缓存命中 N ms`），
  不含进程启动——衡量"缓存到底省了多少编译"。

并行段用**合成单元**（`build/_incrbench/units/u00..u15.qma`，各带一个
`test "..."` 块和一处唯一常量）：真实 `tests/` 里带 test 块的文件太少，
凑不出并行规模；而并行比的是**驱动层**（N 个单元分给 M 个进程），
单元内容只要代表"一个正常编译单元"就成立。合成单元不入库，跑一次生成一次。

用法：
    python tools/dev/incr_bench.py             # 全量（约 2 分钟）
    python tools/dev/incr_bench.py --quick     # 只测单单元冷/热
    python tools/dev/incr_bench.py --units 24  # 改并行段单元数
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")

UNITS = ["examples/hello.qma", "examples/https_get.qma", "tests/t69_tls_client.qma"]
UNIT_DIR = os.path.join("build", "_incrbench", "units")

_RE_MS = re.compile(r"(?:重编|缓存命中|缓存关闭)\s+(\d+)\s+ms")


def run(cmd, timeout=1800):
    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       errors="replace", timeout=timeout)
    return time.perf_counter() - t0, r.returncode, r.stdout + r.stderr


def build_once(src, extra=None):
    """跑一次构建，返回 (墙钟, 编译阶段秒, 是否命中)。"""
    out = os.path.join("build", "_incrbench", os.path.basename(src) + ".qex")
    dt, rc, text = run([sys.executable, CLI, "build", src, "--target", "win",
                        "-o", out] + (extra or []))
    if rc != 0:
        raise RuntimeError(f"{src} 构建失败：{text[-300:]}")
    m = _RE_MS.search(text)
    return dt, (int(m.group(1)) / 1000.0 if m else None), ("缓存命中" in text)


def best_hit(src, n=3, tries=8):
    """热路径只采信"确实命中"的样本。

    另一条轨正在改 `tools/stage0/*.py` 时，编译器指纹每变一次缓存就整体
    失效（这是设计，不是 bug）——这种样本必须剔除，否则会得出"缓存更慢"
    的假结论。
    """
    vals = []
    for _ in range(tries):
        dt, ms, hit = build_once(src)
        if hit:
            vals.append((dt, ms))
            if len(vals) >= n:
                break
    if not vals:
        return None
    return (min(v[0] for v in vals), min(v[1] for v in vals if v[1]))


def make_units(n):
    """生成 n 个互不相同的合成单元（内容不同 → 缓存键不同 → 并行可比）。"""
    d = os.path.join(ROOT, UNIT_DIR)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    for i in range(n):
        body = f'''// u{i:02d}.qma — 并行构建探针的合成单元（生成物，不入库）
module u{i:02d}

import std.core
import std.json
import std.str
import std.gzip
import std.sha256

const SEED = {1000 + i}

fn mix(a: int) -> int {{
    let x = a
    let k = 0
    while k < 64 {{
        x = (x * 1103515245 + 12345 + SEED) % 2147483647
        k = k + 1
    }}
    return x
}}

fn label(n: int) -> str {{
    return "u{i:02d}:" + n.to_str()
}}

test "u{i:02d}" {{
    assert(mix(7) == mix(7))
    assert(len(label(1)) > 0)
}}
'''
        with open(os.path.join(d, f"u{i:02d}.qma"), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(body)
    return d


def test_run(extra=None, jobs=1):
    cmd = [sys.executable, CLI, "test", UNIT_DIR, "--target", "win",
           "-j", str(jobs)] + (extra or [])
    dt, rc, text = run(cmd)
    tail = [ln for ln in text.splitlines() if ln.startswith("PASS=")]
    return dt, rc, (tail[-1] if tail else "?")


def clear_cache():
    run([sys.executable, CLI, "cache", "--clear"])


def build_many(units, jobs):
    """多源 build 的墙钟。每单元一个独立进程——启动成本串行/并行两边都付。"""
    dt, rc, text = run([sys.executable, CLI, "build"] + units +
                       ["--target", "win", "--no-cache", "-j", str(jobs)])
    if rc != 0:
        raise RuntimeError(f"多源构建失败：{text[-300:]}")
    return dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="只测单单元冷/热")
    ap.add_argument("--units", type=int, default=16, help="并行段单元数（默认 16）")
    ap.add_argument("--jobs", type=int, default=8, help="并行段并发数（默认 8）")
    args = ap.parse_args()

    print(f"[incr] 仓库 {ROOT}")
    print(f"[incr] Python {sys.version.split()[0]} / {os.cpu_count()} 逻辑核")
    # 进程创建基线：并行编译的**天花板**在这里，不看这个数会误读加速比
    n = 8
    t0 = time.perf_counter()
    for _ in range(n):
        run([sys.executable, "-c", "pass"], timeout=120)
    spawn = (time.perf_counter() - t0) / n
    print(f"[incr] 进程创建基线：{spawn * 1000:.0f} ms/个（{n} 次串行均值）"
          f" —— 并行收益的上限由它决定")
    print()

    # ---- 1. 单单元：冷 vs 热 ----
    print("== 单元构建：全量重编 vs 缓存命中（min of 3）==")
    print(f"{'源文件':<28}{'全量墙钟':>10}{'全量编译':>10}"
          f"{'命中墙钟':>10}{'命中编译':>10}{'加速':>7}")
    for src in UNITS:
        try:
            cold = min((build_once(src, ["--no-cache"]) for _ in range(3)),
                       key=lambda x: x[0])
            warm = best_hit(src)
        except RuntimeError as exc:
            print(f"{src:<28}  跳过：{str(exc).splitlines()[0][:60]}")
            continue
        if warm is None:
            print(f"{src:<28}{cold[0] * 1000:>8.0f}ms{cold[1] * 1000:>8.0f}ms"
                  f"{'—':>10}{'—':>10}   缓存被持续失效（stage0 正在被改）")
            continue
        print(f"{src:<28}{cold[0] * 1000:>8.0f}ms{cold[1] * 1000:>8.0f}ms"
              f"{warm[0] * 1000:>8.0f}ms{warm[1] * 1000:>8.0f}ms"
              f"{cold[1] / warm[1]:>6.1f}x")
    print()

    if args.quick:
        return 0

    # ---- 2. 并行：多源 build（每单元一个进程，启动成本两边都付） ----
    d = make_units(args.units)
    units = [os.path.join(UNIT_DIR, f"u{i:02d}.qma") for i in range(args.units)]
    print(f"== 并行构建：{args.units} 个单元（quelmara build 多源）==")
    print(f"{'模式':<26}{'墙钟':>9}   结果")
    clear_cache()
    ser = build_many(units, 1)
    print(f"{'-j 1（串行，冷缓存）':<26}{ser:>7.1f}s")
    clear_cache()
    par = build_many(units, args.jobs)
    print(f"{f'-j {args.jobs}（并行，冷缓存）':<26}{par:>7.1f}s")
    print(f"{'加速比':<26}{ser / par:>7.1f}x")
    print()
    hot = build_many(units, args.jobs)
    print(f"{f'-j {args.jobs}（热缓存）':<26}{hot:>7.1f}s")
    print()

    # ---- 3. test 驱动（同一进程内编译，启动只付一次） ----
    print(f"== 并行构建：{args.units} 个单元（quelmara test 驱动）==")
    clear_cache()
    ts, _rc, r1 = test_run(["--no-cache"], jobs=1)
    print(f"{'-j 1（串行，冷缓存）':<26}{ts:>7.1f}s   {r1}")
    clear_cache()
    tp, _rc, r2 = test_run(["--no-cache"], jobs=args.jobs)
    print(f"{f'-j {args.jobs}（并行，冷缓存）':<26}{tp:>7.1f}s   {r2}")
    print(f"{'加速比':<26}{ts / tp:>7.1f}x")
    print()

    # ---- 3. 缓存规模 ----
    _dt, _rc, text = run([sys.executable, CLI, "cache", "--stat"])
    for ln in text.splitlines():
        if "qlm-cache" in ln:
            print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
