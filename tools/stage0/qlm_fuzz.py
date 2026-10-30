#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara 编译器模糊测试驱动（stage-0 工具链，v1.83）
==================================================
分工：

  | 段 | 做什么 | 用什么 |
  |---|---|---|
  | 造用例 | 读种子源码 -> 变异 -> 写 N 个 .qma | **`tools/qlm_fuzz.qma`**（Quelmara 写） |
  | 判定 | 逐个编译，分类 built / rejected / deep / bug / slow | 本文件（要在进程里跑前端） |
  | 报告 | 计数 + 崩溃详情 + 复现命令 | 本文件 |

为什么判定在 Python：前端（lex/parse/lower/opt）是 stage-0 Python 模块，
直接进程内调用最快（~10 ms/例，起子进程光解释器启动就要 0.4 s）；
变异器反而是纯字符串变换，正好用自研语言写——和 `qlm_cov.qma` 同一个思路。

判定口径（什么算 bug）：

  | 结果 | 含义 |
  |---|---|
  | `built` | 前端接受了这个变异体（语义可能错，但编译器没崩） |
  | `rejected` | 抛 `SyntaxError`——**这是设计好的 fail-fast**，不是缺陷 |
  | `deep` | `RecursionError`：嵌套过深撞到 Python 递归上限（单独计数，不混进 bug） |
  | `bug` | 其它异常（`IndexError` / `KeyError` / `AttributeError` / `TypeError` …）——**真缺陷** |
  | `slow` | 单例超过 `--timeout-ms`（只报告，不判失败） |

退出码：0 无崩溃 / 1 发现崩溃 / 2 用法错误。

用法：
  python tools/stage0/qlm_fuzz.py <src.qma> [--cases 64] [--seed 1]
                                  [--out DIR] [--timeout-ms 2000]
                                  [--max-seconds 120] [--emit]
"""

import argparse
import contextlib
import io
import os
import sys
import time

from qlm_src import read_source  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

MUTATOR_SRC = os.path.join(ROOT, "tools", "qlm_fuzz.qma")
MUTATOR_EXE = os.path.join("build", "qlm_fuzz.exe")


def _compile_frontend(path, emit=False):
    """编译一个用例，返回 (kind, detail)。kind ∈ built/rejected/deep/bug。"""
    import qlm_native
    sink = io.StringIO()          # 编译器会 print 警告（如死循环体检），别淹报告
    try:
        with contextlib.redirect_stdout(sink):
            qlm_native.lower_and_optimize(path, platform="windows",
                                          optimize=True)
            if emit:
                import qlm_pe
                qlm_pe.transpile_win(path, optimize=True)
        return "built", ""
    except SyntaxError as e:
        return "rejected", (str(e).splitlines() or [""])[0]
    except RecursionError:
        return "deep", "RecursionError"
    except Exception as e:                       # noqa: BLE001 —— 这里就是要抓全部
        return "bug", f"{type(e).__name__}: {e}"


def _gen_cases(seed_src, out_dir, cases, seed, build_fn):
    """调 Quelmara 变异器生成用例；返回生成的路径列表。"""
    exe = MUTATOR_EXE
    # 变异器只在源码更新时重编：构建一次 ~11 s（本机 VBS 环境），
    # 而 fuzz 的主要成本应该花在编译用例上。
    stale = (not os.path.isfile(exe)
             or os.path.getmtime(exe) < os.path.getmtime(MUTATOR_SRC))
    if stale:
        exe, _s, _c, _i = build_fn(MUTATOR_SRC, "win", MUTATOR_EXE)
    # 不清旧用例：本函数按 case_%04d 覆盖写，返回的路径表就是本次的集合；
    # 上一轮更大的用例数会留下多余文件，它们不参与本次编译（无害）。
    os.makedirs(out_dir, exist_ok=True)
    import subprocess
    subprocess.check_call([os.path.abspath(exe), os.path.abspath(seed_src),
                           os.path.abspath(out_dir), str(cases), str(seed)],
                          stdout=subprocess.DEVNULL)
    return [os.path.join(out_dir, f"case_{i:04d}.qma") for i in range(cases)]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="qlm-fuzz",
        description="Quelmara 编译器模糊测试（变异器用 Quelmara 写，v1.83）")
    ap.add_argument("src", help="种子源码（.qma）")
    ap.add_argument("--cases", type=int, default=64, help="用例数（默认 64）")
    ap.add_argument("--seed", type=int, default=1, help="变异种子（默认 1，确定性）")
    ap.add_argument("--out", default=None, help="用例目录（默认 build/fuzz/seed<N>）")
    ap.add_argument("--timeout-ms", type=int, default=2000,
                    help="单例耗时上限（毫秒，超过只报告不失败）")
    ap.add_argument("--max-seconds", type=float, default=120.0,
                    help="总时长预算（秒，到点停止并报告已跑部分）")
    ap.add_argument("--emit", action="store_true",
                    help="连 x64 后端一起跑（更慢，能抓到发射层缺陷）")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.src):
        print(f"找不到种子文件: {args.src}")
        return 2
    out_dir = args.out or os.path.join("build", "fuzz", f"seed{args.seed}")

    import qlm_cli
    t0 = time.perf_counter()
    cases = _gen_cases(args.src, out_dir, args.cases, args.seed, qlm_cli.build)
    t_gen = time.perf_counter() - t0

    n = {"built": 0, "rejected": 0, "deep": 0, "bug": 0}
    bugs = []
    slow = 0
    slowest = 0.0
    ran = 0
    t1 = time.perf_counter()
    for path in cases:
        if time.perf_counter() - t1 > args.max_seconds:
            print(f"  [warn] 超过 --max-seconds {args.max_seconds:.0f}s，"
                  f"已跑 {ran}/{len(cases)} 例")
            break
        s = time.perf_counter()
        kind, detail = _compile_frontend(path, emit=args.emit)
        dt = time.perf_counter() - s
        ran += 1
        slowest = max(slowest, dt)
        if dt * 1000.0 > args.timeout_ms:
            slow += 1
        n[kind] += 1
        if kind == "bug":
            bugs.append((path, detail))
    t_run = time.perf_counter() - t1

    seed_text = read_source(args.src)
    print("qlm_fuzz — 编译器前端模糊测试（变异器用 Quelmara 写）")
    print(f"  种子: {args.src}（{len(seed_text.splitlines())} 行，"
          f"{len(seed_text.encode('utf-8'))} 字节）")
    print(f"  用例: {ran}/{len(cases)}（seed={args.seed}，1–4 处变异/例，"
          f"目录 {out_dir}）")
    print(f"  接受 {n['built']} / 拒绝 {n['rejected']} / 深递归 {n['deep']}"
          f" / 崩溃 {n['bug']} / 慢例 {slow}")
    print(f"  耗时: 生成 {t_gen:.2f} s + 编译 {t_run:.2f} s"
          f"（{ran / t_run:.1f} 例/s，最慢 {slowest * 1000:.0f} ms）")
    for path, detail in bugs[:5]:
        print(f"  [BUG] {os.path.basename(path)}  {detail}")
        print(f"        复现: python tools/stage0/qlm_cli.py build {path} "
              f"--target win")
    if n["bug"] > 5:
        print(f"  …还有 {n['bug'] - 5} 个崩溃未列出")
    if n["bug"]:
        print(f"  结果: {n['bug']} 个崩溃（退出码 1）")
        return 1
    print("  结果: 无崩溃")
    return 0


if __name__ == "__main__":
    sys.exit(main())
