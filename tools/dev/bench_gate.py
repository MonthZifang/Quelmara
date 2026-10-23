#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能回归门禁（`bench/gate_bench.qma` + 本脚本）。

`quelmara bench` 量的是**进程墙钟**（含 ~426 ms 冷启动），只能看出"慢了半秒"
这种量级；本门禁量的是**进程内 now_ns**，并且把时间按同一进程里的校准形状
归一化，因此在换机器后仍然可比。

两种判定模式，各管一段：

| 模式 | 比什么 | 用在哪 | 默认阈值 |
|---|---|---|---|
| 基线（默认） | 本机数值 vs `bench/perf_baseline.json` 里**同一平台/架构/后端**的记录 | 开发机、参考机 | 15% |
| A/B（`--ab REV`） | 当前工作区 vs 某个 git 修订（同一台机器、同一次运行） | CI（PR 与 base 分支对比） | 15% |

硬失败项（与时间无关，永不受噪声影响）：

1. **校验和**：`QLMDIGEST` 与基线不一致 → 直接失败（"变快了因为算错了"是性能门禁最怕的失败）。
2. **产物体积**：超过基线 `--size-threshold`% → 失败（代码膨胀先于时间可测）。

时间判定还带**噪声闸**：同一形状在 `--repeat` 次运行里的离散度超过
`--noise-cap`% 时，只报数不判失败——共享 runner 上把噪声当回归会训练出
"看到红就重跑"的习惯，那等于没有门禁。

用法：

    python tools/dev/bench_gate.py --check                  # 对基线判定（默认）
    python tools/dev/bench_gate.py --update                 # 重写基线（改了代码/换机器）
    python tools/dev/bench_gate.py --ab origin/master       # 与修订做 A/B（CI 用）
    python tools/dev/bench_gate.py --check --json           # 机器可读

退出码：0 通过 / 1 回归 / 2 构建或运行失败。
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "bench", "gate_bench.qma")
BASELINE = os.path.join(ROOT, "bench", "perf_baseline.json")
BUILD = os.path.join(ROOT, "build")

LINE = re.compile(r"^QLM(BENCH|CAL|DIGEST)\|(.+)$")
METRICS = ("arith", "branch", "memscan", "strbuild", "mapstr", "sha256")


def cpu_tag():
    """CPU 型号进 key：基线只跟"同一类机器"比。

    CI runner 与本机是不同 CPU，跨机器比绝对时间没有意义（校准量只能约掉
    主频，约不掉核数/缓存/内存带宽）。宁可 SKIP，也不要制造假红。
    """
    raw = ""
    try:
        if os.name == "nt":
            raw = platform.processor()
        else:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        raw = line.split(":", 1)[1]
                        break
    except OSError:
        raw = ""
    tag = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return (tag[:28] or platform.machine().lower())


def key_of(target):
    return (f"{platform.system().lower()}/{platform.machine().lower()}"
            f"/{cpu_tag()}/{target}")


def build(src, target, out, tree=ROOT, optimize=True):
    cli = os.path.join(tree, "tools", "stage0", "qlm_cli.py")
    cmd = [sys.executable, cli, "build", src, "--target", target, "-o", out]
    if not optimize:
        cmd.append("--no-opt")
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError((r.stdout or "") + (r.stderr or ""))
    if not os.path.isfile(out):
        raise RuntimeError(f"构建成功但产物不存在：{out}")
    return os.path.getsize(out)


def run_once(exe, target):
    """跑一次，返回 {metric: (iters, ns)}, cal, digest。arm64 走自研模拟器。"""
    if target == "arm64":
        cmd = [sys.executable, os.path.join(ROOT, "tests", "a64_emu.py"), exe]
    else:
        cmd = [os.path.abspath(exe)]
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"运行失败（rc={r.returncode}）：{(r.stderr or '')[-400:]}")
    metrics, cal, digest = {}, None, None
    for raw in r.stdout.splitlines():
        m = LINE.match(raw.strip())
        if not m:
            continue
        kind, rest = m.group(1), m.group(2)
        if kind == "BENCH":
            name, iters, ns = rest.split("|")
            metrics[name] = (int(iters), int(ns))
        elif kind == "CAL":
            iters, ns = rest.split("|")
            cal = (int(iters), int(ns))
        else:
            digest = rest.strip()
    missing = [n for n in METRICS if n not in metrics]
    if missing or cal is None or digest is None:
        raise RuntimeError(f"输出协议不完整，缺 {missing or 'CAL/DIGEST'}；"
                           f"实际输出：{r.stdout[:300]}")
    return metrics, cal, digest


def prepare(src, target, tree=ROOT, tag="", optimize=True):
    """构建一次，返回 (产物路径, 字节数)。"""
    out = os.path.join(BUILD, f"gate_bench{tag}.{'exe' if target != 'native' else 'elf'}")
    os.makedirs(BUILD, exist_ok=True)
    return out, build(src, target, out, tree=tree, optimize=optimize)


def collapse(runs, size, repeats):
    """把多次运行折成一条记录：逐指标取最小值（min-of-N 是抗噪的唯一可靠办法）。"""
    digests = {_d for _m, _c, _d in runs}
    if len(digests) > 1:
        raise RuntimeError(f"同一产物多次运行校验和不一致：{sorted(digests)}")
    best = {}
    for name in METRICS:
        cand = [m[name] for m, _c, _d in runs]
        iters = {c[0] for c in cand}
        if len(iters) > 1:
            raise RuntimeError(f"{name} 的迭代数在多次运行间不一致")
        best[name] = (cand[0][0], min(c[1] for c in cand))
    cal = (runs[0][1][0], min(r[1][1] for r in runs))
    return {"size": size, "digest": runs[0][2], "metrics": best, "cal": cal,
            "runs": repeats}


def measure(src, target, repeats, tree=ROOT, tag="", optimize=True):
    out, size = prepare(src, target, tree=tree, tag=tag, optimize=optimize)
    return collapse([run_once(out, target) for _ in range(repeats)], size, repeats)



def ratio_of(iters, ns, cal):
    """归一化耗时：一次迭代折合多少次校准迭代（跨机器可比）。"""
    per_op = ns / iters
    if isinstance(cal, dict):                 # 基线里存的是 {"iters", "ns"}
        cal = (cal["iters"], cal["ns"])
    per_cal = cal[1] / cal[0]
    return per_op / per_cal


def _it_ns(m):
    """基线里是 {"iters","ns"}，实测里是 (iters, ns)——统一成二元组。"""
    return (m["iters"], m["ns"]) if isinstance(m, dict) else (m[0], m[1])


def compare(now, base, threshold, size_threshold, noise=None, digest_fatal=True):
    """返回 (rows, failed)。rows: [(name, base_ratio, now_ratio, delta%, verdict)]

    digest_fatal=False 用于 A/B：两棵树语义不同是**有意的改动**，此时时间对比
    本身没有意义，调用方会整段 SKIP，而不是判失败。
    """
    rows, failed = [], False
    if base["digest"] != now["digest"]:
        rows.append(("digest", base["digest"], now["digest"], None,
                     "FAIL 校验和不一致" if digest_fatal else "SKIP 语义已变"))
        failed = failed or digest_fatal
    grow = (now["size"] - base["size"]) / base["size"] * 100.0
    verdict = "ok"
    if grow > size_threshold:
        verdict = f"FAIL 体积 +{grow:.1f}%"
        failed = True
    rows.append(("size", f"{base['size']}B", f"{now['size']}B", grow, verdict))

    for name in METRICS:
        b, n = base["metrics"].get(name), now["metrics"].get(name)
        if not b or not n:
            rows.append((name, "-", "-", None, "SKIP 基线无此项"))
            continue
        br = ratio_of(*_it_ns(b), base["cal"])
        nr = ratio_of(*_it_ns(n), now["cal"])
        delta = (nr - br) / br * 100.0
        # 离散度（%）是这台机器在当前负载下的"分辨率"：差异没超过它就不判红，
        # 否则共享机器上的正常抖动会被当成回归（实测同一份代码能差 ±30%）。
        sp = (noise or {}).get(name, 0.0) * 100.0
        if delta > threshold:
            verdict = f"noisy(±{sp:.0f}%)" if sp > 0 and delta <= sp else "FAIL 回归"
        elif delta < -threshold:
            verdict = "faster"
        else:
            verdict = f"noisy(±{sp:.0f}%)" if sp > threshold else "ok"
        if verdict.startswith("FAIL"):
            failed = True
        rows.append((name, f"{br:.3f}", f"{nr:.3f}", delta, verdict))
    return rows, failed


def series_of(runs):
    """把 [ (metrics, cal, digest), … ] 摊成 {形状: [(iters, ns), …]}。"""
    return {n: [m[n] for m, _c, _d in runs] for n in METRICS}


def spread(runs_metrics):
    """多次运行的相对离散度 (max-min)/min，用来判断这一档能不能判失败。"""
    out = {}
    for name, series in runs_metrics.items():
        vals = [ns / iters for iters, ns in series]
        if len(vals) > 1 and min(vals) > 0:
            out[name] = (max(vals) - min(vals)) / min(vals)
    return out


def measure_noise(src, target, repeats, tag):
    """为噪声闸多跑一遍，收集逐次数据（不计入 min-of-N 结果）。"""
    out = os.path.join(BUILD, f"gate_bench{tag}.{'exe' if target != 'native' else 'elf'}")
    series = {n: [] for n in METRICS}
    for _ in range(max(3, repeats)):
        metrics, _cal, _d = run_once(out, target)
        for n in METRICS:
            series[n].append(metrics[n])
    return spread(series)


def print_table(title, rows):
    print(f"\n{title}")
    print(f"  {'指标':<10} {'基线':>12} {'本次':>12} {'Δ':>8}  判定")
    for name, b, n, delta, verdict in rows:
        ds = f"{delta:+.1f}%" if delta is not None else "-"
        print(f"  {name:<10} {b:>12} {n:>12} {ds:>8}  {verdict}")


def load_baseline(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("entries", {})


def save_baseline(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "entries": entries}, f, indent=2,
                  ensure_ascii=False, sort_keys=True)
        f.write("\n")


def entry_of(now, qlm_version):
    return {
        "digest": now["digest"],
        "size": now["size"],
        "runs": now["runs"],
        "qlm": qlm_version,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cal": {"iters": now["cal"][0], "ns": now["cal"][1]},
        "metrics": {k: {"iters": v[0], "ns": v[1]} for k, v in now["metrics"].items()},
    }


def qlm_version():
    cli = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
    try:
        with open(cli, encoding="utf-8") as f:
            for line in f:
                if line.startswith("VERSION"):
                    return line.split('"')[1]
    except OSError:
        pass
    return "?"


def ab_mode(args, tmpdir):
    """与某个 git 修订做同机对比：两棵源码树用同一份 gate_bench.qma 构建。"""
    rev = args.ab
    wt = os.path.join(tmpdir, "base")
    r = subprocess.run(["git", "worktree", "add", "--detach", wt, rev],
                       cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"[gate] 无法建立 {rev} 的工作树（{r.stderr.strip()[:200]}）→ SKIP")
        return 0
    try:
        # 同一份基准源码（工作区可能刚改过 bench/gate_bench.qma）
        src_base = os.path.join(wt, "bench", "gate_bench.qma")
        shutil.copyfile(SRC, src_base)
        # 交错执行：base / now / base / now …，两边各自取最小。
        # 先跑完一边再跑另一边会把"机器状态漂移"整段算到后一边头上
        # （实测同一份代码能漂 ±10%，方向随负载变化）。
        exe_base, size_base = prepare(src_base, args.target, tree=wt, tag="_ab_base")
        exe_now, size_now = prepare(SRC, args.target, tag="_ab_now")
        runs_base, runs_now = [], []
        for _ in range(args.repeat):
            runs_base.append(run_once(exe_base, args.target))
            runs_now.append(run_once(exe_now, args.target))
        base = collapse(runs_base, size_base, args.repeat)
        now = collapse(runs_now, size_now, args.repeat)
        # 噪声闸：两边的离散度取大者。A/B 已经交错执行，剩下的抖动靠这一层兜住
        noise = {}
        for side in (runs_base, runs_now):
            for name, val in spread(series_of(side)).items():
                noise[name] = max(noise.get(name, 0.0), val)
        same = base["digest"] == now["digest"]
        rows, failed = compare(now, base, args.threshold, args.size_threshold,
                               noise=noise if not args.no_noise else None,
                               digest_fatal=False)
        if args.json:
            print(json.dumps({
                "mode": "ab", "rev": rev, "same_digest": same, "failed": failed,
                "rows": [{"metric": r[0], "base": r[1], "now": r[2],
                          "delta_pct": r[3], "verdict": r[4]} for r in rows],
            }, ensure_ascii=False, indent=2))
        else:
            print_table(f"A/B  {rev}（基线） vs 工作区（本次）  阈值 {args.threshold:.0f}%", rows)
        if not same:
            print("  → 校验和不同：两棵树的**计算语义**已经变了，"
                  "时间对比不成立 → SKIP（语义改动请用主回归验，不用性能门禁验）")
            return 0
        print("  → " + ("FAIL：有回归" if failed else "PASS：无回归"))
        return 1 if failed else 0
    finally:
        # 工作树里可能有刚构建出来的产物，remove 失败时不能留下半注册的条目，
        # 否则下一次 `git worktree add` 会撞名（prune 顺手清掉死条目）。
        subprocess.run(["git", "worktree", "remove", "--force", wt],
                       cwd=ROOT, capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=ROOT, capture_output=True)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Quelmara 性能回归门禁")
    ap.add_argument("--check", action="store_true", help="对基线判定（默认动作）")
    ap.add_argument("--update", action="store_true", help="用本次实测重写基线")
    ap.add_argument("--ab", default=None, metavar="REV",
                    help="与 git 修订做同机 A/B 对比（CI 用 origin/master）")
    ap.add_argument("--target", default="win" if os.name == "nt" else "native",
                    choices=["win", "native", "arm64"])
    ap.add_argument("--repeat", type=int, default=3, help="重复次数，逐指标取最小（默认 3）")
    ap.add_argument("--threshold", type=float, default=None,
                    help="时间回归阈值 %%（默认：基线模式 25，A/B 模式 15）")
    ap.add_argument("--size-threshold", type=float, default=10.0,
                    help="产物体积增长阈值 %%（默认 10）")
    ap.add_argument("--noise-cap", type=float, default=30.0,
                    help="离散度超过该值 %% 时该指标只报数不判失败（默认 30）")
    ap.add_argument("--no-noise", action="store_true", help="关掉噪声闸（本地参考机用）")
    ap.add_argument("--baseline", default=BASELINE)
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    ap.add_argument("--no-opt", action="store_true",
                    help="本次构建关优化（灵敏度自检：门禁必须判失败）")
    args = ap.parse_args(argv)

    if args.threshold is None:
        # 基线模式跨"不同时间点"，本机 VBS 下同产物重复判定的系统漂移实测 10–16%，
        # 阈值低于它只会制造假红；A/B 是同一次运行内的对比，可以收紧。
        args.threshold = 15.0 if args.ab else 25.0

    entries = load_baseline(args.baseline)
    key = key_of(args.target)

    if args.ab:
        with tempfile.TemporaryDirectory(prefix="qlm_ab_") as tmp:
            return ab_mode(args, tmp)

    try:
        now = measure(SRC, args.target, args.repeat, tag="_now",
                      optimize=not args.no_opt)
    except RuntimeError as exc:
        print(f"[gate] 构建/运行失败：{exc}")
        return 2

    if args.update:
        entries[key] = entry_of(now, qlm_version())
        save_baseline(args.baseline, entries)
        print(f"[gate] 基线已更新：{os.path.relpath(args.baseline, ROOT)}  [{key}]")
        print(f"  size={now['size']}B  digest={now['digest']}  "
              f"cal={now['cal'][1] / now['cal'][0]:.2f} ns/iter")
        for name, (iters, ns) in now["metrics"].items():
            print(f"  {name:<10} {ns / iters:>10.2f} ns/iter")
        return 0

    base = entries.get(key)
    if not base:
        print(f"[gate] SKIP：基线里没有 {key}（先在有代表性的机器上跑 --update）")
        print(f"  本次实测 size={now['size']}B digest={now['digest']}")
        for name, (iters, ns) in now["metrics"].items():
            print(f"  {name:<10} {ns / iters:>10.2f} ns/iter")
        return 0

    noise = None
    if not args.no_noise:
        try:
            noise = measure_noise(SRC, args.target, args.repeat, "")
        except RuntimeError:
            noise = None

    rows, failed = compare(now, base, args.threshold, args.size_threshold, noise)
    if args.json:
        print(json.dumps({
            "key": key, "failed": failed,
            "rows": [{"metric": r[0], "base": r[1], "now": r[2],
                      "delta_pct": r[3], "verdict": r[4]} for r in rows],
        }, ensure_ascii=False, indent=2))
    else:
        print_table(f"基线 {key}（{base.get('ts', '?')}，qlm {base.get('qlm', '?')}）"
                    f"  阈值 {args.threshold:.0f}%", rows)
        if noise:
            worst = max(noise.values()) * 100.0 if noise else 0.0
            print(f"  噪声：本机离散度最大 ±{worst:.0f}%（阈值 {args.noise_cap:.0f}% 以上只报数）")
        print("  → " + ("FAIL：有回归" if failed else "PASS：无回归"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
