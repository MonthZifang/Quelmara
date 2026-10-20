#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara 统一命令行入口（SPEC §8）
================================
  quelmara build <src>      编译（默认当前平台自研后端）
  quelmara run   <src>      编译并运行
  quelmara test  [path]     运行 test "name" { } 内建测试（默认当前平台自研后端）
  quelmara fmt   [path]     官方格式化器（--check 只检查）
  quelmara bench <src>      基准测试 + 回归对比（--baseline / --update-baseline）
  quelmara version          版本与后端能力

通用选项：
  --target native|win|arm64|c|both   代码生成后端（默认当前平台自研后端）
  -o, --out PATH                 输出路径
  --dump-ir                      打印 RosIR
  --no-opt                       关闭优化管线

设计原则：所有子命令都读取项目根目录的 Quelmara.toml（唯一全局资源开关）。
"""

import argparse
import glob
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qlm import SRC_EXT, require_source  # noqa: E402

VERSION = "1.0.0"

def _default_target():
    """当前主机默认只选自研后端；不把 C99 当产品默认链路。"""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows" and machine in ("amd64", "x86_64", "x64"):
        return "win"
    if system == "linux":
        if machine in ("aarch64", "arm64"):
            return "arm64"
        if machine in ("amd64", "x86_64", "x64"):
            return "native"
    # Unsupported host: leave the default unset so an explicit --target c
    # remains usable for bootstrap/migration workflows.
    return None


DEFAULT_TARGET = _default_target()


# ---------------------------------------------------------------------------
# 后端适配层
# ---------------------------------------------------------------------------

def _build_native(src, out, dump_ir=False, optimize=True):
    import qlm_native as N
    blob, cfg = N.transpile_native(src, dump_ir=dump_ir, optimize=optimize)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    N.write_elf(out, blob)
    return out, len(blob), cfg


def _build_arm64(src, out, dump_ir=False, optimize=True):
    import qlm_arm64 as A
    # transpile_a64 只返回 (blob, cfg)：ELF 头/程序头由 write_elf_a64 写出。
    # 之前直接把 2 元组当 (out, size, cfg) 返回，CLI 一解包就 ValueError。
    blob, cfg = A.transpile_a64(src, dump_ir=dump_ir, optimize=optimize)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    A.write_elf_a64(out, blob)
    return out, len(blob), cfg


def _build_c(src, out, dump_ir=False, optimize=True, cc=True):
    import qlm as R
    c_code, cfg = R.transpile(src)
    base = os.path.splitext(os.path.basename(src))[0]
    out_c = os.path.join("build", base + ".c")
    os.makedirs("build", exist_ok=True)
    with open(out_c, "w", encoding="utf-8") as f:
        f.write(c_code)
    if not cc:
        return out_c, len(c_code), cfg
    cc_cmd = ["cc", "-std=gnu11", "-O2", "-pthread", "-o", out, out_c]
    subprocess.check_call(cc_cmd, stdout=subprocess.DEVNULL)
    return out, os.path.getsize(out), cfg


def _build_win(src, out, dump_ir=False, optimize=True):
    import qlm_pe as W
    pe, cfg = W.transpile_win(src, dump_ir=dump_ir, optimize=optimize)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    W.write_exe(out, pe)
    return out, len(pe), cfg


# 产物扩展名（docs/EXTENSIONS.md）：.qex = PE 可执行，.qel = ELF 可执行，.c = 交叉验证
OUT_EXT = {"win": ".qex", "native": ".qel", "arm64": ".qel", "c": ".c"}

BACKENDS = {
    "native": _build_native,
    "c": _build_c,
    "arm64": _build_arm64,
    "win": _build_win,
}


def build(src, target=DEFAULT_TARGET, out=None, dump_ir=False, optimize=True):
    base = os.path.splitext(os.path.basename(src))[0]
    if target is None:
        raise RuntimeError("当前主机没有自研默认后端；请显式指定 --target c（仅交叉验证/自举）或安装受支持的目标工具链")
    if out is None:
        out = os.path.join("build", base + OUT_EXT.get(target, ""))
    fn = BACKENDS[target]
    return fn(src, out, dump_ir=dump_ir, optimize=optimize)


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def cmd_build(args):
    out, size, cfg = build(args.src, args.target, args.out,
                           dump_ir=args.dump_ir, optimize=not args.no_opt)
    print(f"[qlm] {args.src} -> {out}  ({size} 字节, target={args.target})")
    print(f"[qlm] config: {cfg.get('_path') or '(默认)'} | "
          f"multicore={cfg['core']['multicore']} "
          f"threads={cfg['core']['threads'] or 'auto'} "
          f"opt={cfg['build']['opt']}")
    return 0


def cmd_run(args):
    out, size, cfg = build(args.src, args.target, args.out,
                           dump_ir=args.dump_ir, optimize=not args.no_opt)
    print(f"[qlm] exec {out}")
    rc = subprocess.call([os.path.abspath(out)] + (args.args or []))
    return rc


def _discover_tests(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, fs in os.walk(p):
                dirs[:] = [d for d in dirs
                           if d not in ("build", "__pycache__", ".git", "single_core")]
                files += [os.path.join(root, f) for f in fs if f.endswith(SRC_EXT)]
        elif os.path.isfile(p):
            files.append(p)
    out = []
    for f in sorted(files):
        with open(f, encoding="utf-8") as fh:
            if 'test "' in fh.read():
                out.append(f)
    return out


def cmd_test(args):
    paths = args.paths or ["tests", "examples"]
    files = _discover_tests(paths)
    if not files:
        print("[qlm-test] 没有找到 test \"name\" { } 测试块")
        return 1

    if args.target == "both":
        targets = ["native", "c"]
    elif args.target:
        targets = [args.target]
    else:
        # 默认回归只验证当前平台的自研后端；C 后端必须显式指定。
        targets = [DEFAULT_TARGET]
    passed = failed = 0
    results = {}
    for f in files:
        for t in targets:
            tag = f"{f} [{t}]"
            try:
                out, _, _ = build(f, t, optimize=not args.no_opt)
                r = subprocess.run([os.path.abspath(out)], capture_output=True,
                                   encoding="utf-8", errors="replace", timeout=300)
                ok = (r.returncode == 0)
                results.setdefault(f, {})[t] = r.stdout
            except Exception as e:
                ok = False
                r = type("R", (), {"stdout": "", "stderr": str(e), "returncode": -1})()
            if ok:
                print(f"  ✅ {tag}")
                passed += 1
            else:
                print(f"  ❌ {tag}")
                for line in (r.stderr or r.stdout or "").splitlines()[-6:]:
                    print(f"       {line}")
                failed += 1
        # 双后端交叉验证：输出必须一致
        if len(targets) == 2 and len(results.get(f, {})) == 2:
            a, b = results[f]["native"], results[f]["c"]
            if a == b:
                print(f"  ✅ {f} 双后端输出一致（交叉验证）")
                passed += 1
            else:
                print(f"  ❌ {f} 双后端输出不一致")
                failed += 1
    print("-" * 48)
    print(f"PASS={passed} FAIL={failed}")
    return 0 if failed == 0 else 1


def cmd_fmt(args):
    import qlm_fmt
    argv = list(args.paths or [])
    if args.check:
        argv.append("--check")
    if args.quiet:
        argv.append("-q")
    sys.argv = ["quelmara fmt"] + argv
    qlm_fmt.main()
    return 0


def cmd_bench(args):
    out, size, cfg = build(args.src, args.target, args.out, optimize=not args.no_opt)
    runs = max(1, args.runs)
    times = []
    sample = ""
    for _ in range(runs):
        t0 = time.perf_counter()
        r = subprocess.run([os.path.abspath(out)], capture_output=True,
                           encoding="utf-8", errors="replace")
        times.append(time.perf_counter() - t0)
        sample = r.stdout.strip()
    best, mean = min(times), statistics.fmean(times)
    stdev = statistics.pstdev(times) if len(times) > 1 else 0.0
    print(f"[qlm-bench] {args.src}")
    print(f"  target={args.target}  size={size}B  runs={runs}")
    print(f"  best={best*1000:.2f}ms  mean={mean*1000:.2f}ms  stdev={stdev*1000:.2f}ms")
    if sample:
        print(f"  output: {sample.splitlines()[0][:60]}")

    base_path = args.baseline or "bench_baseline.json"
    record = {"min_s": best, "mean_s": mean, "runs": runs, "size": size,
              "target": args.target, "src": args.src,
              "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

    if args.update_baseline:
        data = {}
        if os.path.isfile(base_path):
            with open(base_path, encoding="utf-8") as f:
                data = json.load(f)
        data[args.src] = record
        with open(base_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        print(f"  baseline 已更新 -> {base_path}")
        return 0

    if os.path.isfile(base_path):
        with open(base_path, encoding="utf-8") as f:
            data = json.load(f)
        prev = data.get(args.src)
        if prev:
            delta = (best - prev["min_s"]) / prev["min_s"] * 100
            flag = "REGRESSION" if delta > args.threshold else ("faster" if delta < 0 else "ok")
            print(f"  vs baseline({prev.get('ts','?')}): "
                  f"{prev['min_s']*1000:.2f}ms -> {best*1000:.2f}ms  ({delta:+.1f}%)  [{flag}]")
            if delta > args.threshold:
                return 2
    else:
        print(f"  （无基线 {base_path}，用 --update-baseline 建立）")
    return 0


def cmd_version(args):
    print(f"Quelmara {VERSION}  ——  自研后端优先 · 多核默认 · 网络原生 · 全平台")
    print(f"  后端: native(x86_64 裸 ELF64) / win(x86_64 PE/COFF，无 CRT) / "
          f"arm64(AArch64 ELF64) / c(C99 交叉验证，不是产品后端)")
    print(f"  优化: 常量折叠 / 强度削减 / 魔数除法 / 内联 / CSE-GVN / LICM / 循环展开 / "
          f"DCE / 复制传播 / 线性扫描寄存器分配")
    print(f"  工具: build / run / test / fmt / bench")
    return 0


def main(argv=None):
    # Windows 控制台默认 GBK：统一按 UTF-8 输出，避免 ✅/中文诊断直接抛
    # UnicodeEncodeError（工具链自己的输出不能因为代码页而崩）。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(prog="quelmara", description="Quelmara 语言工具链")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, src=True):
        if src:
            p.add_argument("src")
        p.add_argument("--target", default=DEFAULT_TARGET,
                       choices=["native", "c", "arm64", "win", "both"],
                       help="代码生成后端（默认当前平台自研后端；c 仅用于显式交叉验证）")
        p.add_argument("-o", "--out", default=None)
        p.add_argument("--no-opt", action="store_true", help="关闭优化管线")
        p.add_argument("--dump-ir", action="store_true", help="打印 RosIR")

    p = sub.add_parser("build", help="编译")
    common(p)

    p = sub.add_parser("run", help="编译并运行")
    common(p)
    p.add_argument("args", nargs="*", help="传给程序的参数")

    p = sub.add_parser("test", help="运行 test \"name\" { } 内建测试")
    p.add_argument("paths", nargs="*", help="文件或目录（默认 tests/ examples/）")
    p.add_argument("--target", default=None,
                   choices=["native", "c", "arm64", "win", "both"],
                   help="后端（默认：Windows=win，POSIX=native+c 交叉验证）")
    p.add_argument("--no-opt", action="store_true")

    p = sub.add_parser("fmt", help="官方格式化器")
    p.add_argument("paths", nargs="*")
    p.add_argument("--check", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("bench", help="基准测试 + 回归对比")
    common(p)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--baseline", default=None)
    p.add_argument("--update-baseline", action="store_true")
    p.add_argument("--threshold", type=float, default=10.0,
                   help="回归阈值（百分比，默认 10%%）")

    sub.add_parser("version", help="版本与能力")

    args = ap.parse_args(argv)
    handler = {"build": cmd_build, "run": cmd_run, "test": cmd_test,
               "fmt": cmd_fmt, "bench": cmd_bench, "version": cmd_version}[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
