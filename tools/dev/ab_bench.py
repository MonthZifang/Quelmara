#!/usr/bin/env python3
"""ab_bench.py —— 两个 qlmc 编译器的 A/B 基准对比器。

用途
    Lead 在优化 `bootstrap/qlmc/qlmc.qma` 时，需要回答"新编译器编出来的
    代码是更快了还是更慢了"，而且**只信数字、不信直觉**。这个脚本把
    "同一份 .qma 用 A/B 两个编译器各编一遍、各跑 N 次取最小"自动化，
    再把 A/B 两个结果并列成一张 markdown 表。

口径（跟 bench/speed/run.py 一致，别自己发明）
    · 计时用**进程内**的 `now_ns()` 差值 —— 每个基准自己打印 `<校验和>`、
      `T`、`纳秒`。进程创建成本不计入（本机 wine 起来一次就要几百 ms）。
    · 统计量取 **N 次里的最小值**。这台机器（Celeron J1900，4 核，经常
      有别的活）噪声很大，最小值是唯一稳的量；平均值/中位数会被抖动带跑。
    · **校验和门禁**：A/B（以及可选的 C 参考）必须打印逐字节相同的校验和。
      不一致就整行判 `CHECKSUM-MISMATCH`，时间数字不予比较 —— 那说明
      优化改坏了语义，继续比时间毫无意义。

用法
    # 自比（证明工具本身没偏置，比值应该 ~1.00）
    python3 tools/dev/ab_bench.py --compiler build/qlmc.exe --compiler build/qlmc.exe

    # 真正的 A/B：老编译器 vs 新编译器，跑 7 次取最小
    python3 tools/dev/ab_bench.py --compiler /tmp/qlmc_old.exe \\
                                  --compiler /tmp/qlmc_new.exe --reps 7

    # 只跑几个基准，并且带 C 参考列
    python3 tools/dev/ab_bench.py --compiler /tmp/a.exe --compiler /tmp/b.exe \\
                                  --only b1_int b83_lcg_random --c

    # 同一个编译器编出来的东西跟 C 比（--langs c 只是打开 C 列）
    python3 tools/dev/ab_bench.py --compiler build/qlmc.exe --langs c

设计取舍
    · 编译器是 Windows PE，Linux 上用 wine 跑；它**编出来的**是原生 ELF，
      直接 exec。所以只有"编译"这一步需要 wine，"运行"不需要。
    · 编译产物缓存在 /tmp/qbench/<编译器指纹>/<基准>。指纹 = 编译器文件的
      mtime+size（不做全文件哈希：4.7MB 的 exe 每次哈希没意义，mtime+size
      已经能在"重新自举后文件名不变"的场景下正确失效）。
    · 单个基准编译失败 / 运行超时都**不中断整轮**，只在那一行标记，并附上
      编译器的 stderr 尾巴 —— 因为优化期最常见的现象就是"某几个基准编不过"。
"""

import argparse
import concurrent.futures as futures
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QMA_DIR = os.path.join(ROOT, "bench", "speed", "quelmara")
C_DIR = os.path.join(ROOT, "bench", "speed", "c")
CACHE = os.environ.get("QBENCH_CACHE", "/tmp/qbench")

# 单次运行的硬超时（秒）。一个挂住的基准不能把整个工具拖死。
RUN_TIMEOUT = 300
# 单个基准的**编译**超时。qlmc 编一个基准 normally 2~15 s（含 wine 启动）。
BUILD_TIMEOUT = 300

REGRESS_PCT = 5.0          # B/A 超过这个百分比算回退
IMPROVE_PCT = 5.0          # 低于这个百分比算改进


def log(msg):
    """进度一律走 stderr，stdout 只留干净的 markdown 表。"""
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------- 基准发现
def discover():
    """返回 {基准名: qma 路径}，按名字自然排序。"""
    out = {}
    if not os.path.isdir(QMA_DIR):
        return out
    for fn in os.listdir(QMA_DIR):
        if fn.endswith(".qma"):
            out[fn[:-4]] = os.path.join(QMA_DIR, fn)
    # 自然序：b1_int, b2_float, b10_ackermann ...（b10 排在 b2 后面）
    return dict(sorted(out.items(), key=lambda kv: _natkey(kv[0])))


def _natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def c_source(bench):
    p = os.path.join(C_DIR, bench + ".c")
    return p if os.path.exists(p) else None


# --------------------------------------------------------------- 编译器封装
class Compiler:
    """一个 qlmc 二进制。自动决定用不用 wine 包一层。"""

    def __init__(self, path, tag=None):
        self.path = os.path.abspath(path)
        if not os.path.exists(self.path):
            raise SystemExit(f"找不到编译器：{path}")
        self.tag = tag or os.path.basename(self.path)
        st = os.stat(self.path)
        # 指纹：mtime + size。重新自举后 mtime 必变，产物缓存因此自动失效。
        self.fp = hashlib.sha1(
            f"{self.path}:{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:12]
        self.wine = None
        if not _is_native_elf(self.path):
            self.wine = shutil.which("wine")
            if not self.wine:
                raise SystemExit(
                    f"{path} 不是本机可执行格式，也没有找到 wine")

    def __str__(self):
        return self.tag

    def build_cmd(self, src, out):
        cmd = ([self.wine] if self.wine else []) + [
            self.path, "build", src, "-o", out,
            "--target", "elf", "--no-bounds-check"]
        return cmd

    def compile(self, src, out):
        """编译一个 .qma。返回 (ok, stderr_tail)。"""
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cmd = self.build_cmd(src, out)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=BUILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            return False, f"编译超时（>{BUILD_TIMEOUT}s）"
        if r.returncode != 0:
            tail = ((r.stdout or "") + (r.stderr or "")).strip()
            return False, tail[-600:] or f"退出码 {r.returncode}"
        if not os.path.exists(out):
            return False, "编译器退出码 0 但没有产物"
        os.chmod(out, 0o755)
        return True, ""


def _is_native_elf(path):
    """看 magic：ELF 直接跑，PE（MZ）要 wine。"""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    return magic == b"\x7fELF"


# --------------------------------------------------------------- 运行与解析
def parse_out(text):
    """协议：若干行校验和 → 一行 `T` → 一行纳秒。

    返回 (checksum, ns)；ns 可能是 None（协议没走通）。
    """
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if "T" not in lines:
        return "\n".join(lines), None
    i = lines.index("T")
    ck = "\n".join(lines[:i]).strip()
    ns = None
    if i + 1 < len(lines):
        try:
            ns = int(lines[i + 1])
        except ValueError:
            ns = None
    return ck, ns


def run_exe(exe, reps, settle=0.0):
    """跑 reps 次，返回 (min_ns, checksum, err)。

    · 每次都用 subprocess 超时，挂住的进程不会拖死工具。
    · checksum 取**第一次**成功的结果；后续次结果不一致也记下来（异常抖动）。
    """
    best = None
    ck = None
    errs = []
    for k in range(reps):
        if settle and k:
            time.sleep(settle)
        try:
            r = subprocess.run([exe], capture_output=True, text=True,
                               timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            return None, ck, f"运行超时（>{RUN_TIMEOUT}s）"
        if r.returncode != 0:
            return None, ck, (f"退出码 {r.returncode}: "
                              f"{(r.stderr or '').strip()[:300]}")
        c, ns = parse_out(r.stdout)
        if ns is None:
            return None, c, "输出里没有 T/纳秒 行"
        if ck is None:
            ck = c
        elif c != ck:
            errs.append("同一二进制多次运行校验和不一致")
        if best is None or ns < best:
            best = ns
    if errs and best is not None:
        return best, ck, "; ".join(set(errs))
    return best, ck, None


def build_c(bench, out):
    """gcc -O2 编 C 参考实现。返回 (ok, stderr_tail)。"""
    src = c_source(bench)
    if not src:
        return False, "没有对应的 C 源文件"
    cc = shutil.which("gcc") or shutil.which("cc")
    if not cc:
        return False, "没有 gcc/cc"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        r = subprocess.run([cc, "-O2", "-o", out, src, "-I", C_DIR],
                           capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "gcc 超时"
    if r.returncode != 0:
        return False, ((r.stdout or "") + (r.stderr or "")).strip()[-600:]
    return True, ""


# --------------------------------------------------------------- 主流程
def ms(ns):
    return ns / 1e6


def fmt_ms(ns):
    if ns is None:
        return "—"
    return f"{ms(ns):.2f}"


def fmt_ratio(r):
    if r is None:
        return "—"
    return f"{r:.3f}"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="两个 qlmc 编译器的 A/B 基准对比（进程内计时，min-of-N）")
    ap.add_argument("--compiler", action="append", default=[],
                    metavar="EXE",
                    help="qlmc 二进制；给两次做 A/B，给一次只做 vs C")
    ap.add_argument("--reps", type=int, default=5, help="每个基准跑几次取最小（默认 5）")
    ap.add_argument("--only", nargs="+", default=None, metavar="BENCH",
                    help="只跑这些基准（名字或前缀，例如 b1_int b8_）")
    ap.add_argument("--langs", nargs="+", default=None, metavar="LANG",
                    help="要包含的语言列；目前支持 quelmara / c")
    ap.add_argument("--c", action="store_true",
                    help="同时编 C 参考实现，多一列 vs C（等价于 --langs c）")
    ap.add_argument("--jobs", type=int, default=1,
                    help="并行编译/运行的并行度（默认 1：本机只有 4 核，"
                         "并行会让计时噪声变大；编译阶段可调高）")
    ap.add_argument("--build-only", action="store_true",
                    help="只编译不跑（用于预热 /tmp/qbench 缓存）")
    ap.add_argument("--no-cache", action="store_true", help="忽略已缓存的产物")
    ap.add_argument("--list", action="store_true", help="列出所有基准名后退出")
    ap.add_argument("--timeout", type=int, default=300,
                    help="单次运行超时秒数（默认 300）")
    args = ap.parse_args(argv)

    globals()["RUN_TIMEOUT"] = args.timeout

    if args.list:
        for name in discover():
            print(name)
        return 0
    if not args.compiler:
        ap.error("至少给一个 --compiler（--list 除外）")

    comps = [Compiler(p, tag=os.path.basename(p)) for p in args.compiler]
    if len(comps) > 2:
        raise SystemExit("最多两个 --compiler（A/B）")
    # 两个编译器同名时给个区分标签
    if len(comps) == 2 and comps[0].tag == comps[1].tag:
        comps[1].tag = comps[1].tag + "#B"

    langs = set(args.langs or [])
    if args.c:
        langs.add("c")
    want_c = "c" in langs
    unknown = langs - {"quelmara", "c"}
    if unknown:
        raise SystemExit(f"暂不支持这些语言列：{sorted(unknown)}（只有 quelmara / c）")

    benches = discover()
    if not benches:
        raise SystemExit(f"{QMA_DIR} 下没有 .qma")

    sel = list(benches)
    if args.only:
        pref = args.only
        sel = [b for b in sel if any(b == p or b.startswith(p) for p in pref)]
        if not sel:
            raise SystemExit(f"--only {pref} 没匹配到任何基准")

    reps = max(1, args.reps)
    log(f"[ab_bench] {len(sel)} 个基准, reps={reps}, 编译器: "
        + ", ".join(f"{c.tag}={c.path}" for c in comps))

    # ---- 1) 编译阶段（可并行：编译用 wine，跟被测程序的计时无关）----
    outdirs = {c.tag: os.path.join(CACHE, c.fp) for c in comps}
    for c in comps:
        os.makedirs(outdirs[c.tag], exist_ok=True)

    def ensure(c, b):
        out = os.path.join(outdirs[c.tag], b)
        if not args.no_cache and os.path.exists(out):
            os.chmod(out, 0o755)
            return b, c.tag, True, ""
        ok, err = c.compile(benches[b], out)
        return b, c.tag, ok, err

    tasks = [(c, b) for c in comps for b in sel]
    build_fail = {}     # (tag, bench) -> err
    n = 0
    if args.jobs > 1:
        with futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
            futs = [ex.submit(ensure, c, b) for c, b in tasks]
            for fu in futures.as_completed(futs):
                b, tag, ok, err = fu.result()
                n += 1
                if not ok:
                    build_fail[(tag, b)] = err
                    log(f"  [{n}/{len(tasks)}] {b} @ {tag}: COMPILE-FAIL")
                else:
                    log(f"  [{n}/{len(tasks)}] {b} @ {tag}: ok")
    else:
        for c, b in tasks:
            b2, tag, ok, err = ensure(c, b)
            n += 1
            if not ok:
                build_fail[(tag, b)] = err
                log(f"  [{n}/{len(tasks)}] {b} @ {tag}: COMPILE-FAIL — "
                    f"{err.splitlines()[-1][:120] if err else ''}")
            else:
                log(f"  [{n}/{len(tasks)}] {b} @ {tag}: ok")

    cbin = {}
    if want_c:
        cdir = os.path.join(CACHE, "c")
        os.makedirs(cdir, exist_ok=True)
        for b in sel:
            out = os.path.join(cdir, b)
            if not args.no_cache and os.path.exists(out):
                cbin[b] = out
                continue
            ok, err = build_c(b, out)
            if ok:
                cbin[b] = out
            else:
                build_fail[("c", b)] = err
                log(f"  C 参考 {b}: COMPILE-FAIL — {err.splitlines()[-1][:120] if err else ''}")

    if args.build_only:
        log("[ab_bench] --build-only：只做了编译，不跑。")
        return 0

    # ---- 2) 计时阶段：串行跑，避免互相抢核（本机只有 4 核）----
    rows = []
    total = len(sel)
    for idx, b in enumerate(sel, 1):
        row = {"bench": b, "times": {}, "cs": {}, "errs": {}, "fail": {}}
        for c in comps:
            if (c.tag, b) in build_fail:
                row["fail"][c.tag] = "COMPILE-FAIL"
                row["errs"][c.tag] = build_fail[(c.tag, b)]
                continue
            exe = os.path.join(outdirs[c.tag], b)
            ns, ck, err = run_exe(exe, reps)
            if ns is None:
                row["fail"][c.tag] = "RUN-FAIL"
                row["errs"][c.tag] = err or "未知"
                continue
            row["times"][c.tag] = ns
            row["cs"][c.tag] = ck
            if err:
                row["errs"][c.tag] = err
        if want_c:
            if ("c", b) in build_fail:
                row["fail"]["c"] = "COMPILE-FAIL"
                row["errs"]["c"] = build_fail[("c", b)]
            elif b in cbin:
                ns, ck, err = run_exe(cbin[b], reps)
                if ns is None:
                    row["fail"]["c"] = "RUN-FAIL"
                    row["errs"]["c"] = err or "未知"
                else:
                    row["times"]["c"] = ns
                    row["cs"]["c"] = ck
                    if err:
                        row["errs"]["c"] = err
        # 校验和门禁：所有**跑成功**的实现必须一致
        had = {t: v for t, v in row["cs"].items()}
        row["ck_ok"] = (len(set(had.values())) <= 1) if had else None
        rows.append(row)
        ta = row["times"].get(comps[0].tag)
        log(f"[{idx}/{total}] {b}: "
            + ", ".join(f"{t}={fmt_ms(v)}ms" for t, v in row["times"].items())
            + ("" if row["ck_ok"] in (True, None) else "  <CHECKSUM-MISMATCH>"))

    emit(rows, comps, want_c, reps)
    return 0


# --------------------------------------------------------------- 输出
def emit(rows, comps, want_c, reps):
    a, b = comps[0], (comps[1] if len(comps) > 1 else None)
    hdr = ["bench", f"{a.tag} (ms)"]
    if b:
        hdr.append(f"{b.tag} (ms)")
        hdr.append("B/A")
    if want_c:
        hdr.append("vs C")
    hdr.append("checksum ok")
    print()
    print("| " + " | ".join(hdr) + " |")
    print("|" + "|".join(["---"] * len(hdr)) + "|")

    ratios = []
    regress = improve = 0
    mismatches = []
    fails = []
    for r in rows:
        cells = [r["bench"]]
        ta = r["times"].get(a.tag)
        tb = r["times"].get(b.tag) if b else None
        tc = r["times"].get("c") if want_c else None
        cells.append(fmt_ms(ta))
        if b:
            cells.append(fmt_ms(tb))
        # 校验和先判：不一致时**不展示比值**
        ok = r["ck_ok"]
        if ok is False:
            mismatches.append(r["bench"])
            if b:
                cells.append("—")
            if want_c:
                cells.append("—")
            cells.append("**CHECKSUM-MISMATCH**")
        else:
            fail_tags = [t for t in r["fail"]]
            if fail_tags:
                fails.append((r["bench"], fail_tags))
            ratio = (tb / ta) if (ta and tb) else None
            if b:
                cells.append(fmt_ratio(ratio))
            if want_c:
                cells.append(fmt_ratio((tb / tc) if (tb and tc) else
                                       (ta / tc if (ta and tc) else None)))
            if fail_tags:
                cells.append("FAIL: " + ",".join(f"{t} {r['fail'][t]}"
                                                 for t in fail_tags))
            elif ok is None:
                cells.append("—")
            else:
                cells.append("yes")
        if b and ta and tb and ok is not False:
            ratio = tb / ta
            ratios.append(ratio)
            if ratio > 1 + REGRESS_PCT / 100:
                regress += 1
            elif ratio < 1 - IMPROVE_PCT / 100:
                improve += 1
        print("| " + " | ".join(cells) + " |")

    print()
    # ---- 汇总 ----
    print(f"**reps={reps}（每次基准取 min-of-{reps}，进程内 now_ns()）**")
    if b:
        if ratios:
            gm = math.exp(sum(math.log(x) for x in ratios) / len(ratios))
            print()
            print(f"- 样本数：{len(ratios)} 个基准（校验和一致、两边都跑成功的）")
            verdict = "B 更快" if gm < 1 else "A 更快" if gm > 1 else "持平"
            print(f"- **几何平均 B/A = {gm:.4f}**"
                  f"（{verdict}，幅度 {abs(gm - 1) * 100:.1f}%）")
            print(f"- 回退（B 慢 >{REGRESS_PCT:.0f}%）：{regress} 个")
            print(f"- 改进（B 快 >{IMPROVE_PCT:.0f}%）：{improve} 个")
            print(f"- 持平（±{REGRESS_PCT:.0f}% 内）：{len(ratios) - regress - improve} 个")
        else:
            print("\n- 没有可比较的样本。")
    if mismatches:
        print()
        print(f"- **校验和不一致（{len(mismatches)}）：** "
              + ", ".join(mismatches))
        print("  → 这些行的时间数字**无效**，说明两个编译器生成的程序语义不同。")
    if fails:
        print()
        print(f"- **编译/运行失败（{len(fails)}）：**")
        for bench, tags in fails:
            for t in tags:
                r = next(r for r in rows if r["bench"] == bench)
                tail = (r["errs"].get(t) or "").strip().splitlines()
                print(f"  - `{bench}` @ {t} [{r['fail'][t]}]: "
                      f"{(tail[-1] if tail else '')[:200]}")
    print()


if __name__ == "__main__":
    sys.exit(main())
