#!/usr/bin/env python3
"""build_all.py —— 自动编译工作流（CI `build.yml` 的驱动）

做四件事，任何一步失败立刻非零退出（fail-fast，不吞错）：

1. **自举**（仅 Windows）：stage-0 编 `bootstrap/qlmc/qlmc.qma` → stage-1；
   stage-1 再编同一份源码 → stage-2。**stage-1 与 stage-2 必须逐字节相同** ——
   这是"编译器能编译自己"的唯一硬判据（能编出个 exe 很容易，编出来和自己
   一模一样才是真的）。
2. **编译全部基准**：`bench/speed/quelmara/` 下每一个 .qma 都要编过。
3. **编译全部示例**：`examples/` 下每一个 .qma 都要编过（跳过已知需要
   平台特性的，用 `--skip` 控制）。
4. **跑一遍产物**（可选 `--run`）：基准产物各跑一次，校验退出码，
   顺带证明"编出来的东西真能跑"。

用法：
    python tools/dev/build_all.py --compiler stage0 --target win
    python tools/dev/build_all.py --compiler qlmc   --target win --selfhost --run
    python tools/dev/build_all.py --compiler stage0 --target native
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
STAGE0 = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
QLMC_SRC = os.path.join(ROOT, "bootstrap", "qlmc", "qlmc.qma")
BENCH_DIR = os.path.join(ROOT, "bench", "speed", "quelmara")
EXAMPLES = os.path.join(ROOT, "examples")

# 需要平台特性（网络/多线程/终端）的示例，在 CI 上不编译
EXAMPLE_SKIP = {
    "echo_concurrent.qma", "echo_reactor.qma", "echo_server.qma",
    "http_demo.qma", "game_loop.qma",
}


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return p


def build(cmd, out):
    """调编译器；失败时把编译器输出原样抛出来（不要静默）"""
    t0 = time.time()
    p = run(cmd)
    dt = (time.time() - t0) * 1000
    if p.returncode != 0 or not os.path.exists(out):
        sys.stderr.write(f"\n[FAIL] {' '.join(cmd)}\n")
        sys.stderr.write((p.stdout or "")[-2000:])
        sys.stderr.write((p.stderr or "")[-2000:])
        raise SystemExit(1)
    return os.path.getsize(out), dt


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", choices=["stage0", "qlmc"], default="stage0")
    ap.add_argument("--target", default="win")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "build", "ci"))
    ap.add_argument("--selfhost", action="store_true",
                    help="做 stage-1/stage-2 自举一致性检查（需要 qlmc 有该平台后端）")
    ap.add_argument("--run", action="store_true", help="编完再跑一遍（校验退出码）")
    ap.add_argument("--skip-examples", action="store_true")
    a = ap.parse_args()

    outdir = a.outdir
    os.makedirs(outdir, exist_ok=True)
    rows = []

    # ---------- 1. 自举 ----------
    if a.selfhost:
        s1 = os.path.join(ROOT, "build", "qlmc_stage1.exe")
        s2 = os.path.join(ROOT, "build", "qlmc_stage2.exe")
        sz, dt = build([PY, STAGE0, "build", QLMC_SRC, "--target", "win",
                        "-o", s1], s1)
        print(f"[bootstrap] stage-0 -> stage-1  {sz} B  {dt:.0f} ms")
        sz, dt = build([s1, "build", QLMC_SRC, "-o", s2], s2)
        print(f"[bootstrap] stage-1 -> stage-2  {sz} B  {dt:.0f} ms")
        # **不动点判据**：stage-2 与 stage-3 必须逐字节相同。
        # 拿 stage-1 和 stage-2 比是错的 —— 它们是**两个不同的编译器**
        # （stage-0 与 qlmc）编同一份源码，产物本来就不一样（stage-0 的
        # 代码量大 4 倍）。真正的自举一致性是"同一个编译器再编一次自己，
        # 结果不变"。
        s3 = os.path.join(ROOT, "build", "qlmc_stage3.exe")
        sz, dt = build([s2, "build", QLMC_SRC, "-o", s3], s3)
        print(f"[bootstrap] stage-2 -> stage-3  {sz} B  {dt:.0f} ms")
        h2, h3 = sha(s2), sha(s3)
        if h2 != h3:
            print(f"[FAIL] 自举不动点不成立：stage-2 {h2[:16]} != stage-3 {h3[:16]}")
            raise SystemExit(1)
        print(f"[bootstrap] 自举不动点成立  sha256={h2[:16]}…")
        rows.append(("qlmc(自举)", os.path.getsize(s2), "OK"))

    # ---------- 2. 编译器本体 ----------
    if a.compiler == "qlmc":
        qlmc = os.path.join(ROOT, "build", "qlmc.exe")
        if not os.path.exists(qlmc):
            build([PY, STAGE0, "build", QLMC_SRC, "--target", "win",
                   "-o", qlmc], qlmc)
        comp = [qlmc, "build"]
        extra = []
    else:
        comp = [PY, STAGE0, "build"]
        extra = ["--target", a.target]

    # ---------- 3. 全部基准 ----------
    bench = sorted(f for f in os.listdir(BENCH_DIR) if f.endswith(".qma"))
    for f in bench:
        src = os.path.join(BENCH_DIR, f)
        out = os.path.join(outdir, os.path.splitext(f)[0] + ".exe")
        sz, dt = build(comp + [src] + extra + ["-o", out], out)
        status = "OK"
        if a.run:
            p = run([out], timeout=300)
            status = "run" if p.returncode == 0 else f"rc={p.returncode}"
            if p.returncode != 0:
                sys.stderr.write(f"[FAIL] {f} 运行失败 rc={p.returncode}\n")
                sys.stderr.write((p.stdout or "")[-800:])
                raise SystemExit(1)
        print(f"[bench] {f:22} {sz:7} B  {dt:6.0f} ms  {status}")
        rows.append((f, sz, status))

    # ---------- 4. 全部示例 ----------
    # qlmc 只覆盖子集 S1（见 docs/05-toolchain.md §1.11），`examples/` 里
    # 用到 S2/S3 特性的（match、闭包、接口……）它编不了 —— 这不是缺陷，
    # 是自举的阶段边界。所以用 qlmc 时默认跳过示例，只有 stage-0 才全编。
    if a.compiler == "qlmc" and not a.skip_examples:
        print("[example] 跳过：qlmc 只覆盖子集 S1（用 --compiler stage0 才全编）")
        a.skip_examples = True
    if not a.skip_examples and os.path.isdir(EXAMPLES):
        for f in sorted(os.listdir(EXAMPLES)):
            if not f.endswith(".qma") or f in EXAMPLE_SKIP:
                continue
            src = os.path.join(EXAMPLES, f)
            out = os.path.join(outdir, "ex_" + os.path.splitext(f)[0] + ".exe")
            sz, dt = build(comp + [src] + extra + ["-o", out], out)
            print(f"[example] {f:20} {sz:7} B  {dt:6.0f} ms")
            rows.append((f, sz, "OK"))

    print(f"\n合计 {len(rows)} 个产物 → {outdir}")


if __name__ == "__main__":
    main()
