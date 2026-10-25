#!/usr/bin/env python3
"""compiler.py —— 编译器本身的速度与内存（Quelmara 两条链路对照）。

量三件事：
  1. **冷编译**：没有缓存时，把一个源文件编成 exe 的墙钟时间 + 峰值工作集。
  2. **增量编译**：再编一次（stage-0 有增量缓存；qlmc 没有增量模式，如实标 N/A）。
  3. **大型源文件**：生成 5000 个函数的源，看时间随规模的走势。

对照的两条链路：
  · `stage-0`：`tools/stage0/qlm_cli.py`（Python 写的引导编译器，带增量缓存）
  · `qlmc`   ：`build/qlmc.exe`（Quelmara 自己写的 stage-1，无缓存）

口径：
  · 时间取 N 次最小值的**挂钟**（含进程创建税 —— 这正是用户体感）；
    qlmc 自己报的"进程内"时间单独列一栏，方便看清进程创建占多少。
  · 峰值内存用 `GetProcessMemoryInfo` 轮询采样，2 ms 一次。
  · stage-0 是 Python 进程，内存含解释器本身（约 20 MB 起步），这是事实不是缺陷。

用法：
    python bench/speed/compiler.py
    python bench/speed/compiler.py --reps 5 --sizes 200 1000 5000
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "build", "speed")
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")


class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def peak_ws(h):
    pmc = PMC()
    pmc.cb = ctypes.sizeof(pmc)
    if ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
        return int(pmc.PeakWorkingSetSize)
    return 0


def timed(cmd, env=None):
    """跑一次，返回 (秒, 峰值字节, stdout+stderr)。"""
    e = dict(os.environ)
    if env:
        e.update(env)
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, env=e)
    peak = 0
    while p.poll() is None:
        peak = max(peak, peak_ws(int(p._handle)))
        time.sleep(0.002)
    out, err = p.communicate()
    dt = time.perf_counter() - t0
    return dt, peak, (out or "") + (err or "")


def gen_big(nfun, path):
    """生成 nfun 个函数的源文件（每个函数做点真算术，避免被当成死代码）。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("// 自动生成：大型源文件基准\n")
        for i in range(nfun):
            f.write(f"fn f{i}(a: int, b: int) -> int {{\n")
            f.write(f"    let mut s = a + b\n")
            f.write(f"    let mut k = 0\n")
            f.write(f"    while k < 8 {{\n")
            f.write(f"        s = s + (k * {i % 97 + 1}) % 13\n")
            f.write(f"        k = k + 1\n")
            f.write(f"    }}\n")
            f.write(f"    return s\n")
            f.write(f"}}\n")
        f.write("fn main() {\n    let mut t = 0\n")
        for i in range(0, nfun, max(1, nfun // 20)):
            f.write(f"    t = t + f{i}({i % 11}, {i % 7})\n")
        f.write("    print(t)\n}\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--sizes", nargs="*", type=int, default=[200, 1000, 5000])
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    qlmc = os.environ.get("QLMC") or os.path.join(ROOT, "build", "qlmc.exe")
    have_qlmc = os.path.exists(qlmc)
    if not have_qlmc:
        print("build/qlmc.exe 不存在，qlmc 那几列会是 N/A。")

    cases = [("tests/selfhost/s23_map_grow.qma", "小（3.6 KB，map 扩容）"),
             ("bootstrap/qlmc/qlmc.qma", "大（305 KB，qlmc 自己）")]
    for n in args.sizes:
        p = os.path.join(OUT, f"big{n}.qma")
        gen_big(n, p)
        kb = os.path.getsize(p) // 1024
        cases.append((p, f"生成 {n} 函数（{kb} KB）"))

    rows = []
    for src, desc in cases:
        full = src if os.path.isabs(src) else os.path.join(ROOT, src)
        if not os.path.exists(full):
            continue
        rec = {"desc": desc, "src": src, "sz": os.path.getsize(full)}
        # ---- stage-0 冷编译（关缓存）----
        best, mem, out = None, 0, ""
        for _ in range(args.reps):
            dt, m, o = timed([sys.executable, CLI, "build", full,
                              "--target", "win", "-o", os.path.join(OUT, "s0.exe")],
                             env={"QLM_NO_CACHE": "1"})
            if best is None or dt < best:
                best, out = dt, o
            mem = max(mem, m)
        rec["s0_cold"] = best
        rec["s0_cold_mem"] = mem
        rec["s0_ok"] = "字节" in out
        # ---- stage-0 热编译（缓存命中）----
        best, mem = None, 0
        for _ in range(args.reps):
            dt, m, _ = timed([sys.executable, CLI, "build", full,
                              "--target", "win", "-o", os.path.join(OUT, "s0.exe")])
            if best is None or dt < best:
                best = dt
            mem = max(mem, m)
        rec["s0_warm"] = best
        rec["s0_warm_mem"] = mem
        # ---- qlmc ----
        if have_qlmc:
            best, mem, out = None, 0, ""
            for _ in range(args.reps):
                dt, m, o = timed([qlmc, "build", full,
                                  "-o", os.path.join(OUT, "q.exe")])
                if best is None or dt < best:
                    best, out = dt, o
                mem = max(mem, m)
            rec["qlmc"] = best
            rec["qlmc_mem"] = mem
            mm = re.search(r"编译 (\d+) us", out)
            rec["qlmc_inner"] = int(mm.group(1)) / 1e6 if mm else None
            rec["qlmc_ok"] = "字节" in out
        rows.append(rec)

    print()
    print(f"{'源文件':<30}{'stage-0 冷':>12}{'stage-0 热':>12}"
          f"{'qlmc':>10}{'qlmc 内报':>11}")
    print("-" * 76)
    for r in rows:
        def f(v):
            return f"{v*1000:>11.0f} " if v is not None else f"{'N/A':>11} "
        inner = r.get("qlmc_inner")
        inner_cell = f"{inner*1000:>10.0f} " if inner else f"{'N/A':>10} "
        print(f"{r['desc']:<30}{f(r['s0_cold'])}{f(r['s0_warm'])}"
              f"{f(r.get('qlmc'))}{inner_cell}")
    print("-" * 76)
    print(f"单位：毫秒（min of {args.reps}，挂钟，含进程创建）。")

    print()
    print(f"{'源文件':<30}{'stage-0 冷':>12}{'stage-0 热':>12}{'qlmc':>10}")
    print("-" * 66)
    for r in rows:
        def m(v):
            return f"{v/1048576:>10.1f}M " if v else f"{'N/A':>11}"
        print(f"{r['desc']:<30}{m(r['s0_cold_mem'])}{m(r['s0_warm_mem'])}"
              f"{m(r.get('qlmc_mem'))}")
    print("-" * 66)
    print("峰值工作集。stage-0 是 Python 进程，含解释器本身。")

    bad = [r for r in rows if not r["s0_ok"]]
    if bad:
        print("\n[注意] stage-0 有编译失败的用例：" +
              ", ".join(r["desc"] for r in bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
