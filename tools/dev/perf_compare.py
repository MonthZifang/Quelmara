#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""perf_compare.py —— stage-0 与 qlmc 的**公平**性能对比（v3.83）。

## 为什么需要它

v3.83 复核 §7.31 时发现：以前一直拿 **stage-0 的 ELF 原生运行** vs
**qlmc 的 PE 走 wine** 做对比 —— 那是**不公平的**，wine 的启动与系统调用
开销会混进结果。

本工具把两边都编成 **PE**、都用 wine 跑，只比"编译器产出的代码质量"。

## 口径

* 每个基准自己打印纳秒耗时（`now_ns()` 前后差），**不含进程创建**；
* 每个基准跑 N 次取**最小值**（wine 噪声大，最小值是唯一稳的统计量）；
* 校验和必须两边一致 —— 不同就判 FAIL，此时时间数字一概不看。

用法：
    python tools/dev/perf_compare.py                 # 默认 4 个基准 x 3 次
    python tools/dev/perf_compare.py --reps 5
    python tools/dev/perf_compare.py --only b1_int b9_json
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(ROOT, "bench", "speed", "quelmara")
OUT = os.path.join(ROOT, "build", "_perfcmp")

DEFAULT = ["b1_int", "b2_float", "b7_sort", "b9_json"]


def _runner(exe):
    """Linux 上跑 PE 必须显式走 wine（binfmt 的 MZ handler 会重复 argv[0]）。"""
    if os.name == "nt":
        return [exe]
    wine = shutil.which("wine")
    if wine is None:
        raise SystemExit("FAIL：Linux 上需要 wine 才能执行 PE")
    return [wine, exe]


def build(src, out, use_qlmc):
    if use_qlmc:
        qlmc = os.path.join(ROOT, "build", "qlmc.exe")
        if not os.path.isfile(qlmc):
            raise SystemExit("FAIL：build/qlmc.exe 不存在（先跑 tests/bootstrap_test.py）")
        cmd = _runner(qlmc) + ["build", src, "-o", out]
    else:
        cmd = [sys.executable, os.path.join(ROOT, "tools", "stage0", "qlm_cli.py"),
               "build", src, "--target", "win", "-o", out]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=600)
    if r.returncode != 0 or not os.path.exists(out):
        raise SystemExit(f"编译失败：{(r.stdout + r.stderr)[-500:]}")


def run_once(exe):
    """返回 (校验和行们, 内部耗时纳秒)。基准的末行是耗时。"""
    try:
        os.chmod(exe, 0o755)
    except OSError:
        pass
    r = subprocess.run(_runner(exe), capture_output=True, text=True, timeout=600)
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if not lines:
        return [], 0
    try:
        ns = int(lines[-1])
    except ValueError:
        return lines, 0
    return lines[:-1], ns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--only", nargs="*", default=DEFAULT)
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    print(f"{'基准':<12} {'stage-0':>10} {'qlmc':>10} {'比值':>8}  校验和")
    print("-" * 58)
    bad = 0
    for name in args.only:
        src = os.path.join(BENCH, name + ".qma")
        if not os.path.isfile(src):
            print(f"{name:<12} 跳过（源不存在）")
            continue
        e0 = os.path.join(OUT, name + "_s0.exe")
        e1 = os.path.join(OUT, name + "_qlmc.exe")
        try:
            build(src, e0, False)
            build(src, e1, True)
        except SystemExit as ex:
            print(f"{name:<12} {ex}")
            bad += 1
            continue

        best0 = best1 = None
        sum0 = sum1 = None
        for _ in range(args.reps):
            c0, t0 = run_once(e0)
            c1, t1 = run_once(e1)
            sum0, sum1 = c0, c1
            if t0 and (best0 is None or t0 < best0):
                best0 = t0
            if t1 and (best1 is None or t1 < best1):
                best1 = t1

        if sum0 != sum1:
            print(f"{name:<12} FAIL：校验和不同 {sum0} vs {sum1}")
            bad += 1
            continue
        if not best0 or not best1:
            print(f"{name:<12} FAIL：没拿到耗时")
            bad += 1
            continue
        ratio = best1 / best0
        print(f"{name:<12} {best0/1e6:>9.1f}ms {best1/1e6:>9.1f}ms {ratio:>7.2f}x  ok")

    print("-" * 58)
    if bad:
        print(f"FAIL：{bad} 个基准有问题")
        return 1
    print("说明：比值 > 1 表示 qlmc 更慢。两边都编成 PE 且都用 wine 跑，只比代码质量。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
