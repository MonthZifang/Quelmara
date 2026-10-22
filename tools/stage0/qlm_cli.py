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
  --dump-ir                      打印 QuIR
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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qlm import SRC_EXT, require_source  # noqa: E402

# 版本号口径：与 docs/versions/ 下的目录一致（vX.Y → "X.Y.0"，补丁 → "X.Y.Z"）
VERSION = "1.24.0"

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

SELFHOST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "build", "selfhost")
EXE_SUFFIX = ".qex" if os.name == "nt" else ".qel"


def stage1_lexer():
    """stage-1 自举词法器：存在就优先用（这才是"用 Quelmara 写编译器"的落地）"""
    cand = os.path.join(SELFHOST_DIR, "qlm_lex" + EXE_SUFFIX)
    return cand if os.path.isfile(cand) else None


def cmd_lex(args):
    require_source(args.src)
    exe = None if args.stage0 else stage1_lexer()
    if exe:
        print(f"[qlm:stage1] {exe}")
        return subprocess.call([exe, args.src])
    print("[qlm:stage0] tools/dev/tokfmt.py")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "dev"))
    import tokfmt
    src = open(args.src, encoding="utf-8").read()
    sys.stdout.buffer.write(tokfmt.dump(src).encode("utf-8"))
    return 0


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
    if args.target == "arm64":
        # AArch64 ELF 不能在 x86/Windows 主机上直接跑：走 tests/a64_emu.py
        # 模拟器（执行级验证，与 cmd_test 同一条路径）。
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        a64_emu = os.path.join(root, "tests", "a64_emu.py")
        if not os.path.isfile(a64_emu):
            print("[qlm] 找不到 tests/a64_emu.py，无法执行 arm64 产物")
            return 1
        return subprocess.call([sys.executable, a64_emu,
                                os.path.abspath(out)] + (args.args or []))
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

    # 目标矩阵：--targets all / --targets a,b 优先，其次 --target 单数，最后默认。
    if getattr(args, "targets", None):
        ts = [t.strip() for t in args.targets.split(",") if t.strip()]
        targets = (["native", "win", "arm64", "c"] if ts == ["all"] else ts)
        bad = [t for t in targets
               if t not in ("native", "win", "arm64", "c")]
        if bad:
            print(f"[qlm-test] 未知目标：{', '.join(bad)}"
                  f"（可选 native/win/arm64/c/all）")
            return 1
    elif args.target == "both":
        targets = ["native", "c"]
    elif args.target:
        targets = [args.target]
    else:
        # 默认回归只验证当前平台的自研后端；C 后端必须显式指定。
        targets = [DEFAULT_TARGET]

    # 执行能力矩阵：本机能执行哪些 target 的产物。
    is_win = (os.name == "nt")
    host_target = "win" if is_win else "native"
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a64_emu = os.path.join(root, "tests", "a64_emu.py")

    def can_exec(t):
        if t == host_target:
            return True
        if t == "arm64" and os.path.isfile(a64_emu):
            return True                     # A64 模拟器全平台可跑（执行级）
        if t == "c" and not is_win:
            return True                     # POSIX 默认有 cc
        return False

    def run_prod(t, out):
        """执行产物，返回 (returncode, stdout)；arm64 走模拟器。"""
        if t == "arm64":
            r = subprocess.run([sys.executable, a64_emu, os.path.abspath(out)],
                               capture_output=True, encoding="utf-8",
                               errors="replace", timeout=300)
            return r.returncode, r.stdout
        r = subprocess.run([os.path.abspath(out)], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=300)
        return r.returncode, r.stdout

    passed = failed = skipped = 0
    results = {}
    for f in files:
        outs = {}
        for t in targets:
            tag = f"{f} [{t}]"
            try:
                out, _, _ = build(f, t, optimize=not args.no_opt)
            except Exception as e:
                print(f"  ⏭️  {tag} 构建不可用：{str(e).splitlines()[0][:80]}")
                skipped += 1
                continue
            if not can_exec(t):
                print(f"  ⏭️  {tag} 本机不能执行该产物（构建成功）")
                skipped += 1
                continue
            try:
                rc, stdout = run_prod(t, out)
            except Exception as e:
                print(f"  ❌ {tag} 执行异常：{e}")
                failed += 1
                continue
            if rc == 0:
                print(f"  ✅ {tag}")
                passed += 1
                outs[t] = stdout
            else:
                print(f"  ❌ {tag}（退出码 {rc}）")
                failed += 1
        # 跨后端输出一致性：所有可执行目标的 stdout 必须逐字节一致
        if len(outs) >= 2:
            vals = list(outs.values())
            if all(v == vals[0] for v in vals[1:]):
                print(f"  ✅ {f} 跨后端输出一致（{' vs '.join(outs)}）")
                passed += 1
            else:
                print(f"  ❌ {f} 跨后端输出不一致（{' vs '.join(outs)}）")
                failed += 1
    print("-" * 48)
    print(f"PASS={passed} FAIL={failed} SKIP={skipped}")
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


def _bench_key(target):
    """基线 key：平台/架构/后端 —— 跨平台基线必须按这个三元组分开存。"""
    return f"{platform.system().lower()}/{platform.machine().lower()}/{target}"


def _bench_norm(text):
    """输出归一化：去掉行尾空白与末行空行，避免换行风格造成假不一致。"""
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()


def _bench_run(exe, target, runs):
    """跑 runs 次，返回 (best_s, out_hash, first_line)。arm64 走自研模拟器。"""
    import hashlib
    if target == "arm64":
        emu = os.path.join(ROOT, "tests", "a64_emu.py")
        if not os.path.isfile(emu):
            return None, None, "(无 a64 模拟器)"
        cmd = [sys.executable, emu, exe]
    else:
        cmd = [os.path.abspath(exe)]
    times, out = [], ""
    for _ in range(max(1, runs)):
        t0 = time.perf_counter()
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        times.append(time.perf_counter() - t0)
        out = r.stdout
    norm = _bench_norm(out)
    return min(times), hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16], (
        norm.splitlines()[0][:60] if norm else "")


def cmd_bench(args):
    """基准 + 跨平台基线。

    基线记录 key = 平台/架构/后端/源文件名：
      - 时间只在同一 key 内比较（换机器/换后端没有可比性）
      - 输出哈希则跨 key 比较：同一份源码在不同后端必须产出相同结果，
        这才是"跨平台"真正要守住的东西。
    """
    base_path = args.baseline or os.path.join(ROOT, "bench", "baseline.json")
    targets = ([t.strip() for t in args.targets.split(",") if t.strip()]
               if args.targets else [args.target])
    name = os.path.splitext(os.path.basename(args.src))[0]

    data = {}
    if os.path.isfile(base_path):
        with open(base_path, encoding="utf-8") as f:
            data = json.load(f)
    entries = data.setdefault("entries", {})
    data.setdefault("version", 1)

    print(f"[qlm-bench] {args.src}  targets={','.join(targets)}  runs={args.runs}")
    results = {}
    rc = 0
    for tg in targets:
        if tg == "c":
            print(f"  {tg:<7} 跳过（C99 只做交叉验证，不计入基线）")
            continue
        try:
            out, size, _cfg = build(args.src, tg, None, optimize=not args.no_opt)
        except Exception as exc:                      # noqa: BLE001
            print(f"  {tg:<7} 构建失败：{type(exc).__name__}: {exc}")
            rc = 2
            continue
        best, oh, first = _bench_run(out, tg, args.runs)
        if best is None:
            print(f"  {tg:<7} 无法执行：{first}")
            continue
        key = f"{_bench_key(tg)}/{name}"
        results[tg] = {"key": key, "best_ms": best * 1000.0, "size": size, "out": oh}
        print(f"  {tg:<7} size={size}B  best={best * 1000:.2f}ms  out={oh}  | {first}")

    # ---- 跨后端一致性：同一源码的输出哈希必须相同 ----
    hashes = {v["out"] for v in results.values()}
    if len(hashes) > 1:
        print("  [FAIL] 跨后端输出不一致：")
        for tg, v in results.items():
            print(f"         {tg}: {v['out']}")
        rc = 2
    elif hashes:
        print(f"  [ok]   跨后端输出一致（{len(results)} 个后端，sha={hashlib_short(hashes)}）")

    if args.update_baseline:
        for tg, v in results.items():
            entries[v["key"]] = {"best_ms": round(v["best_ms"], 3), "size": v["size"],
                                 "out": v["out"], "runs": args.runs,
                                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                 "version": VERSION}
        os.makedirs(os.path.dirname(base_path), exist_ok=True)
        with open(base_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        print(f"  baseline 已更新 -> {os.path.relpath(base_path, ROOT)}")
        return rc

    # ---- 与基线对比 ----
    if not entries:
        print(f"  （无基线 {os.path.relpath(base_path, ROOT)}，用 --update-baseline 建立）")
        return rc
    for tg, v in results.items():
        prev = entries.get(v["key"])
        if not prev:
            print(f"  {tg:<7} 无基线记录（{v['key']}）")
            continue
        if prev.get("out") and prev["out"] != v["out"]:
            print(f"  {tg:<7} [FAIL] 输出与基线不一致：{prev['out']} -> {v['out']}")
            rc = 2
        if prev.get("best_ms"):
            delta = (v["best_ms"] - prev["best_ms"]) / prev["best_ms"] * 100.0
            flag = "REGRESSION" if delta > args.threshold else ("faster" if delta < -args.threshold else "ok")
            print(f"  {tg:<7} 基线 {prev['best_ms']:.2f}ms -> {v['best_ms']:.2f}ms "
                  f"({delta:+.1f}%)  [{flag}]")
            if flag == "REGRESSION":
                rc = 2
    return rc


def hashlib_short(hashes):
    return ",".join(sorted(hashes))


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
        p.add_argument("--dump-ir", action="store_true", help="打印 QuIR")

    p = sub.add_parser("build", help="编译")
    common(p)

    p = sub.add_parser("run", help="编译并运行")
    common(p)
    p.add_argument("args", nargs="*", help="传给程序的参数")

    p = sub.add_parser("test", help="运行 test \"name\" { } 内建测试")
    p.add_argument("paths", nargs="*", help="文件或目录（默认 tests/ examples/）")
    p.add_argument("--target", default=None,
                   choices=["native", "c", "arm64", "win", "both"],
                   help="单后端（默认：Windows=win，POSIX=native+c 交叉验证）")
    p.add_argument("--targets", default=None,
                   help="多后端矩阵：逗号分隔（native,win,arm64,c）或 all="
                        "全部后端；可执行的做执行级+跨后端输出比对，"
                        "不可执行的做构建级 SKIP")
    p.add_argument("--no-opt", action="store_true")

    p = sub.add_parser("fmt", help="官方格式化器")
    p.add_argument("paths", nargs="*")
    p.add_argument("--check", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("lex", help="词法分析（优先用 stage-1 自举词法器）")
    p.add_argument("src")
    p.add_argument("--stage0", action="store_true",
                   help="强制用 stage-0（Python）词法器，用于对拍")

    p = sub.add_parser("bench", help="基准测试 + 回归对比")
    common(p)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--baseline", default=None)
    p.add_argument("--update-baseline", action="store_true")
    p.add_argument("--threshold", type=float, default=10.0,
                   help="回归阈值（百分比，默认 10%%）")
    p.add_argument("--targets", default=None,
                   help="跨平台基线：逗号分隔的多个后端，如 win,native,arm64")

    sub.add_parser("version", help="版本与能力")

    args = ap.parse_args(argv)
    handler = {"build": cmd_build, "run": cmd_run, "test": cmd_test,
               "fmt": cmd_fmt, "bench": cmd_bench, "lex": cmd_lex,
               "version": cmd_version}[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
