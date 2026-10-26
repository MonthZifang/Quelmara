#!/usr/bin/env python3
"""run.py —— Quelmara / C / Go / Python 四语言同题基准驱动器。

口径（很重要，别看错）：
  · 计时用**挂钟时间，取 N 次里的最小值**。本机 VBS 噪声 ±50%，最小值是唯一
    稳的统计量；单次数字没有意义。
  · 每个基准都打印**校验和**，四个语言必须逐字节相同 —— 不同就判 FAIL，
    说明其中一份写错了（或语言语义有分歧），此时时间数字一概不看。
  · 峰值内存用 `GetProcessMemoryInfo` 轮询采样（Windows），只对编译器那节有意义。

用法：
    python bench/speed/run.py                  # 全部语言 × 全部基准
    python bench/speed/run.py --reps 7         # 每个基准跑 7 次取最小
    python bench/speed/run.py --only b1_int b7_sort
    python bench/speed/run.py --langs quelmara go
    python bench/speed/run.py --langs quelmara0 c go python   # 跨平台（stage-0 后端）
    python bench/speed/run.py --markdown       # 直接出 markdown 表

环境：
    QLMC     qlmc.exe 路径（默认 build/qlmc.exe）
    ZIG      zig.exe 路径（用 `zig cc` 当 C 编译器；默认自动找 winget 安装位置）
    CC       C 编译器命令（优先于 ZIG，例如 "gcc -O2"）
"""
import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import time

# v2.54：跨平台。Windows 上跑四语言全量（qlmc 只有 win 后端）；
# Linux/macOS 只跑 C/Go/Python —— 那三个是可移植的，用来给"同一道题在不同
# 机器上是什么样"做参照（也就是"适配度"那一列）。
IS_WIN = os.name == "nt"
EXE = ".exe" if IS_WIN else ""
if IS_WIN:
    import ctypes.wintypes as wt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "build", "speed")

# 基准表：(id, 一句话说明)
BENCHES = [
    ("b1_int", "整数运算：2000 万次 (i*7)%13 累加"),
    ("b2_float", "浮点运算：调和级数前 500 万项"),
    ("b3_recursion", "递归：朴素 fib(30)（约 270 万次调用）"),
    ("b4_array", "数组：200 万元素写入 + 顺序 + 跨步遍历"),
    ("b5_string", "字符串：20 万次 int→str→int"),
    ("b6_hash", "哈希表：10 万插入 + 10 万查找（手写开放寻址）"),
    ("b7_sort", "排序：20 万伪随机 int 快排（手写）"),
    ("b8_threads1", "并发：单线程 4000 万次整数运算"),
    ("b8_threads4", "并发：4 线程各 1000 万次（总量相同）"),
    ("b9_json", "JSON：2590 字节文档解析 2000 遍（手写递归下降）"),
]


# ---------------------------------------------------------------- 峰值内存采样
# 只在 Windows 上可用（psapi）。非 Windows 时 `--mem` 会退化成 0 —— 别假装有数。
if IS_WIN:
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wt.DWORD),
            ("PageFaultCount", wt.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]


def _peak_ws(handle):
    if not IS_WIN:
        return 0
    pmc = PROCESS_MEMORY_COUNTERS()
    pmc.cb = ctypes.sizeof(pmc)
    if ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(pmc), pmc.cb):
        return int(pmc.PeakWorkingSetSize)
    return 0


def run_once(exe, args=None, sample_mem=False):
    """跑一次，返回 (挂钟秒, 峰值字节, stdout)。"""
    cmd = [exe] + (args or [])
    if not sample_mem:
        t0 = time.perf_counter()
        r = subprocess.run(cmd, capture_output=True, text=True)
        dt = time.perf_counter() - t0
        return dt, 0, r.stdout
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True)
    peak = 0
    # `p._handle` 是 Windows 专属；非 Windows 上 `--mem` 直接给 0（别假装有数）
    while p.poll() is None:
        if IS_WIN:
            peak = max(peak, _peak_ws(int(p._handle)))
        time.sleep(0.002)
    out, _ = p.communicate()
    return time.perf_counter() - t0, peak, out


def parse_out(out):
    """程序约定：若干行校验和 + 一行 `T` + 一行纳秒。返回 (校验和, 纳秒)。

    **为什么要在进程内计时**：本机 VBS 开着，光进程创建就 ~450 ms，而大部分基准
    的真实负载只有几毫秒到几十毫秒 —— 用挂钟量等于在量 CreateProcess。所以每个
    程序自己用单调时钟圈住负载，只把负载时间打出来。
    """
    lines = [l for l in (out or "").splitlines()]
    if "T" not in lines:
        return (out or "").strip(), None
    i = lines.index("T")
    ck = "\n".join(lines[:i]).strip()
    try:
        ns = int(lines[i + 1].strip())
    except (IndexError, ValueError):
        ns = None
    return ck, ns


# ---------------------------------------------------------------- 工具链探测
def find_zig():
    v = os.environ.get("ZIG")
    if v and os.path.exists(v):
        return v
    cands = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\zig.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
    ]
    if os.path.exists(cands[0]):
        return cands[0]
    for base, dirs, files in os.walk(cands[1]):
        if "zig.exe" in files:
            return os.path.join(base, "zig.exe")
    return shutil.which("zig")


def cc_command():
    """返回 (名字, 命令前缀列表)；找不到返回 (None, None)。"""
    env = os.environ.get("CC")
    if env:
        return env.split()[0], env.split()
    zig = find_zig()
    if zig:
        return "zig cc", [zig, "cc", "-O2"]
    for cand in ("gcc", "clang", "cc"):
        p = shutil.which(cand)
        if p:
            return cand, [p, "-O2"]
    return None, None


def go_exe():
    return shutil.which("go")


def qlmc_exe():
    p = os.environ.get("QLMC") or os.path.join(ROOT, "build", "qlmc.exe")
    return p if os.path.exists(p) else None


# ---------------------------------------------------------------- 各语言构建
def build_all(langs, only):
    os.makedirs(OUT, exist_ok=True)
    built = {}          # (lang, bench) -> exe 或命令
    notes = {}

    if "quelmara" in langs:
        q = qlmc_exe()
        if not q:
            if IS_WIN:
                notes["quelmara"] = ("跳过：build/qlmc.exe 不存在（先自举："
                                     "python tools/stage0/qlm_cli.py build "
                                     "bootstrap/qlmc/qlmc.qma --target win -o build/qlmc.exe）")
            else:
                notes["quelmara"] = "跳过：qlmc 只有 Windows PE 后端（非 Windows 平台无产物）"
        else:
            for b, _ in BENCHES:
                if only and b not in only:
                    continue
                src = os.path.join(HERE, "quelmara", b + ".qma")
                exe = os.path.join(OUT, "qlm_" + b + EXE)
                r = subprocess.run([q, "build", src, "-o", exe],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    notes.setdefault("quelmara", f"{b} 编译失败: " +
                                     (r.stdout + r.stderr).strip()[:200])
                    continue
                built[("quelmara", b)] = [exe]

    if "quelmara0" in langs:
        py = sys.executable
        cli = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
        tgt = "win" if IS_WIN else "native"
        for b, _ in BENCHES:
            if only and b not in only:
                continue
            src = os.path.join(HERE, "quelmara", b + ".qma")
            exe = os.path.join(OUT, "qlm0_" + b + EXE)
            r = subprocess.run([py, cli, "build", src, "--target", tgt,
                                "-o", exe],
                               capture_output=True, text=True)
            if r.returncode != 0:
                notes.setdefault("quelmara0", f"{b} 编译失败: " +
                                 (r.stdout + r.stderr).strip()[:200])
                continue
            if not IS_WIN:
                # POSIX 上刚写出来的文件没有执行位（Windows 不需要）
                os.chmod(exe, 0o755)
            built[("quelmara0", b)] = [exe]

    if "c" in langs:
        name, cc = cc_command()
        if not cc:
            notes["c"] = "跳过：本机没有 C 编译器（gcc/clang/zig 都没有）"
        else:
            for b, _ in BENCHES:
                if only and b not in only:
                    continue
                src = os.path.join(HERE, "c", b + ".c")
                exe = os.path.join(OUT, "c_" + b + EXE)
                r = subprocess.run(cc + ["-o", exe, src],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    notes.setdefault("c", f"{b} 编译失败: " +
                                     (r.stdout + r.stderr).strip()[:200])
                    continue
                built[("c", b)] = [exe]

    if "go" in langs:
        if not go_exe():
            notes["go"] = "跳过：没有 go"
        else:
            for b, _ in BENCHES:
                if only and b not in only:
                    continue
                src = os.path.join(HERE, "go", b + ".go")
                exe = os.path.join(OUT, "go_" + b + EXE)
                r = subprocess.run([go_exe(), "build", "-o", exe, src],
                                   capture_output=True, text=True,
                                   cwd=os.path.join(HERE, "go"))
                if r.returncode != 0:
                    notes.setdefault("go", f"{b} 编译失败: " +
                                     (r.stdout + r.stderr).strip()[:200])
                    continue
                built[("go", b)] = [exe]

    if "python" in langs:
        py = sys.executable
        for b, _ in BENCHES:
            if only and b not in only:
                continue
            built[("python", b)] = [py, os.path.join(HERE, "python", b + ".py")]

    return built, notes


# ---------------------------------------------------------------- 主流程
# quelmara   = qlmc（stage-1 自举编译器）编出来的产物，**只有 Windows PE 后端**
# quelmara0  = stage-0（参考编译器）编出来的产物，**win / linux / macos 都有后端**
#   加这一列是为了拿到"同一个语言在不同平台上"的数字（也就是适配度），
#   同时它和 quelmara 列在同一台 Windows 机器上的差就是**后端差距**。
LANGS = ["quelmara", "quelmara0", "c", "go", "python"]


def report_checksums(fails, rows):
    """校验和门禁：四种实现必须打印**逐字节相同**的校验和。

    不一致说明其中一份写错了（或语言语义有分歧），此时时间数字一概不看。
    """
    if fails:
        print("\n[FAIL] 这些基准的校验和在不同语言之间不一致：")
        for b in fails:
            r = next(x for x in rows if x["bench"] == b)
            print(f"  {b}")
            for l, o in r["out"].items():
                print(f"    {l:<10} {o!r}")
        return 1
    n = len(rows[0]["out"]) if rows else 0
    print(f"\n校验和：{len(rows)} 个基准 × {n} 个语言，全部一致。")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--langs", nargs="*", default=LANGS)
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--mem", action="store_true", help="同时采峰值内存（慢）")
    args = ap.parse_args()

    built, notes = build_all(args.langs, args.only)
    for k, v in notes.items():
        print(f"[{k}] {v}")

    if not built:
        print("没有任何可跑的基准。")
        return 1

    langs = [l for l in LANGS if any(k[0] == l for k in built)]
    rows = []
    fails = []
    for b, desc in BENCHES:
        if args.only and b not in args.only:
            continue
        if not any((l, b) in built for l in langs):
            continue
        rec = {"bench": b, "desc": desc, "t": {}, "mem": {}, "out": {}}
        for l in langs:
            if (l, b) not in built:
                continue
            cmd = built[(l, b)]
            best, bestmem, bestout, bestck = None, 0, None, None
            for _ in range(args.reps):
                dt, mem, out = run_once(cmd[0], cmd[1:], sample_mem=args.mem)
                ck, ns = parse_out(out)
                if ns is not None and (best is None or ns < best):
                    best, bestck, bestout = ns, ck, out
                bestmem = max(bestmem, mem)
            if best is None:      # 没按协议输出，退回挂钟
                best, bestck = int(dt * 1e9), (out or "").strip()
            rec["t"][l] = best / 1e9
            rec["mem"][l] = bestmem
            rec["out"][l] = bestck or ""
        # 校验和必须全部相同
        vals = set(rec["out"].values())
        if len(vals) > 1:
            fails.append(b)
        rows.append(rec)

    # ---- 输出 ----
    if args.markdown:
        print()
        head = "| 基准 | 规模/说明 | " + " | ".join(langs) + " | 最快/最慢 |"
        print(head)
        print("|" + "---|" * (len(langs) + 3))
        for r in rows:
            ts = [r["t"][l] for l in langs if l in r["t"]]
            ratio = (max(ts) / min(ts)) if len(ts) > 1 else 0
            cells = []
            for l in langs:
                cells.append(f"{r['t'][l]*1000:.1f}" if l in r["t"] else "—")
            print(f"| `{r['bench']}` | {r['desc']} | " + " | ".join(cells) +
                  f" | {ratio:.0f}× |")
        print("\n单位：毫秒（min of %d）" % args.reps)
        # **校验和门禁在 markdown 模式下也必须走**（CI 用的就是 --markdown）。
        # 以前这里直接 return 0，于是"某个语言写错了"在 CI 上是静默的 ——
        # 而校验和一致是整张表的前提，不一致时时间数字一概不能看。
        return report_checksums(fails, rows)

    print()
    w = 13
    print(f"{'基准':<{w}}" + "".join(f"{l:>13}" for l in langs) +
          f"{'最快/最慢':>11}")
    print("-" * (w + 13 * len(langs) + 11))
    for r in rows:
        ts = [r["t"][l] for l in langs if l in r["t"]]
        ratio = (max(ts) / min(ts)) if len(ts) > 1 else 0
        line = f"{r['bench']:<{w}}"
        for l in langs:
            line += (f"{r['t'][l]*1000:>12.1f} " if l in r["t"]
                     else f"{'—':>12} ")
        line += f"{ratio:>10.0f}×"
        print(line)
    print("-" * (w + 13 * len(langs) + 11))
    print(f"单位：毫秒（min of {args.reps}）。本机 VBS 噪声大，只做同表横向比较。")

    return report_checksums(fails, rows)


if __name__ == "__main__":
    sys.exit(main())
