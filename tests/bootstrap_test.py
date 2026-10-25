#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自举检验：qlmc 编自己 → stage-2，再用 stage-2 编一批源文件，与 stage-1 的产物对比。

分三级（都要过才算"自举成立"）：
  1. **构建**：`qlmc build bootstrap/qlmc/qlmc.qma` 能产出 exe
  2. **等价**：stage-2 编 `tests/selfhost/*.qma` 的产物与 stage-1 **逐字节相同**
  3. **不动点**：stage-2 编自己 → stage-3，`stage-2 == stage-3`

第 3 级目前（v2.34）**还不过**：stage-2 能完整解析 qlmc.qma（49705 tokens /
28911 nodes / 260 fns），但代码生成阶段在大型输入上崩（读 0xFFFF…FFFF）。
所以脚本把第 3 级当"信息项"报出来，不判失败——等它修好再改成硬门禁。

用法：
    python tests/bootstrap_test.py            # 1+2 级 + 第 3 级信息
    python tests/bootstrap_test.py --strict   # 第 3 级不过也判失败
    python tests/bootstrap_test.py --keep     # 保留中间产物（build/bootstrap/）
"""
import argparse
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
OUT = os.path.join(ROOT, "build", "bootstrap")
SELF_SRC = os.path.join(ROOT, "bootstrap", "qlmc", "qlmc.qma")


def run(cmd, timeout=900):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def build(driver, src, out):
    """用给定的驱动器（stage-0 CLI 或 qlmc.exe）编一个文件，返回 (ok, 耗时秒, 输出)。"""
    t0 = time.time()
    if driver is None:
        r = run([sys.executable, CLI, "build", src, "--target", "win", "-o", out])
    else:
        r = run([driver, "build", src, "-o", out])
    dt = time.time() - t0
    return r.returncode == 0 and os.path.exists(out), dt, (r.stdout + r.stderr).strip()


def same(a, b):
    with open(a, "rb") as f:
        x = f.read()
    with open(b, "rb") as f:
        y = f.read()
    return x == y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="不动点不过也判失败")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    fails = []

    # ---- 0) 先要有 stage-1（由 stage-0 编出来的 qlmc）----
    stage1 = os.path.join(OUT, "stage1.exe")
    ok, dt, msg = build(None, SELF_SRC, stage1)
    print(f"[0] stage-1（stage-0 编 qlmc）：{'PASS' if ok else 'FAIL'}  {dt:.1f}s")
    if not ok:
        print("    " + msg.splitlines()[-1] if msg else "")
        return 1

    # ---- 1) stage-2：qlmc 编自己 ----
    stage2 = os.path.join(OUT, "stage2.exe")
    ok, dt, msg = build(stage1, SELF_SRC, stage2)
    print(f"[1] stage-2（qlmc 编自己）：{'PASS' if ok else 'FAIL'}  {dt:.1f}s"
          f"  {os.path.getsize(stage2) if ok else 0} 字节")
    if not ok:
        print("    " + (msg.splitlines()[-1] if msg else ""))
        fails.append("stage-2 构建")

    if ok:
        # ---- 2) 等价：stage-2 与 stage-1 编同一批源文件，产物逐字节相同 ----
        # 只比"独立程序"：`tests/selfhost/` 里还有被 import 的依赖模块
        # （如 mod_util.qma，没有 main），它们本身编不出 exe，不参与比较。
        srcs = []
        for p in sorted(glob.glob(os.path.join(ROOT, "tests", "selfhost", "*.qma"))):
            with open(p, encoding="utf-8") as f:
                if "fn main" in f.read():
                    srcs.append(p)
        bad = []
        for src in srcs:
            nm = os.path.basename(src)[:-4]
            a = os.path.join(OUT, "eq_s1.exe")
            b = os.path.join(OUT, "eq_s2.exe")
            oka, _, _ = build(stage1, src, a)
            okb, _, _ = build(stage2, src, b)
            if not (oka and okb and same(a, b)):
                bad.append(nm)
        print(f"[2] stage-2 与 stage-1 产物一致：{len(srcs) - len(bad)}/{len(srcs)} 组"
              f"{'  PASS' if not bad else '  FAIL ' + ', '.join(bad)}")
        if bad:
            fails.append(f"等价性（{len(bad)} 组不同）")

        # ---- 3) 不动点：stage-2 编自己 → stage-3 ----
        stage3 = os.path.join(OUT, "stage3.exe")
        ok3, dt3, msg3 = build(stage2, SELF_SRC, stage3)
        if ok3 and same(stage2, stage3):
            print(f"[3] 不动点 stage-2 == stage-3：PASS  {dt3:.1f}s")
        else:
            why = "崩/超时" if not ok3 else "字节不同"
            print(f"[3] 不动点 stage-2 == stage-3：未达成（{why}）—— 已知，见 docs/07-gaps.md §7.23")
            if args.strict:
                fails.append("不动点")

    print("-" * 56)
    if fails:
        print("FAIL：" + "；".join(fails))
        return 1
    print("PASS：stage-2 可用且与 stage-1 逐字节等价")
    if not args.keep:
        for f in ("eq_s1.exe", "eq_s2.exe"):
            p = os.path.join(OUT, f)
            if os.path.exists(p):
                os.remove(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
