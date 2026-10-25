#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""负向用例门禁：`tests/bad/` 里的每个文件都必须**编不过**。

为什么需要这道门：负向用例的价值全在"它失败"这件事上。一旦对应特性落地
（例如 v1.96 做了 enum 派生 / f64 派生 / 运行时反射下标），原本该失败的
用例就变成"能编过"，而**没有任何回归会因此变红**——主回归只跑名单里的
用例，`tests/bad/` 里没登记的文件根本不参与。结果就是负向目录里悄悄躺着
一批失效样本，谁照着它写代码就会被误导。

实例（v2.32 发现）：`derive_enum.qma` / `derive_f64.qma` / `refl_dynidx.qma`
三个文件在特性落地后仍能正常编过并运行（`{"x":1.5}`、反射列出 `x y`），
删掉它们才是对的。当时没有任何检查能发现这件事。

用法：
    python tools/dev/check_bad.py            # 全量扫描
    python tools/dev/check_bad.py --verbose  # 打印每个用例的失败信息首行
    python tools/dev/check_bad.py --jobs 8   # 并行（默认按 CPU 数）

退出码：0 = 全部按预期失败；1 = 有用例编过了（列出清单）。
"""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BAD = os.path.join(ROOT, "tests", "bad")
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")


def collect():
    """收集所有负向用例：(名字, 源文件)。支持 `x.qma` 与 `x/main.qma` 两种形态。"""
    out = []
    for nm in sorted(os.listdir(BAD)):
        p = os.path.join(BAD, nm)
        if os.path.isdir(p):
            m = os.path.join(p, "main.qma")
            if os.path.exists(m):
                out.append((nm, m))
        elif nm.endswith(".qma"):
            out.append((nm, p))
    return out


def probe(item):
    nm, src = item
    exe = os.path.join(ROOT, "build", "dev", "bad_probe.exe")
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    try:
        r = subprocess.run([sys.executable, CLI, "build", src,
                            "--target", "win", "-o", exe],
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return nm, "TIMEOUT", "编译超时（不算通过，但也不是编过了）"
    text = (r.stdout + r.stderr).strip()
    # 末行常常是 "[qlm] config: …"，那对诊断没用——取最后一条真正的输出
    lines = [ln for ln in text.splitlines() if not ln.startswith("[qlm] config")]
    last = lines[-1] if lines else ""
    return nm, r.returncode, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4))
    args = ap.parse_args()

    items = collect()
    print(f"扫描 {len(items)} 个负向用例（tests/bad/）…")
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        results = list(ex.map(probe, items))

    stale = [(nm, msg) for nm, rc, msg in results if rc == 0]
    broken = [(nm, msg) for nm, rc, msg in results if rc == "TIMEOUT"]

    if args.verbose:
        for nm, rc, msg in results:
            flag = "编过了!!" if rc == 0 else "ok"
            print(f"  [{flag:8}] {nm:32} {msg[:70]}")

    print("-" * 56)
    if stale:
        print(f"FAIL：{len(stale)} 个负向用例**能编过**（特性可能已落地，应该删掉或改成正向用例）：")
        for nm, msg in stale:
            print(f"  - tests/bad/{nm}  | {msg[:80]}")
        return 1
    if broken:
        print(f"FAIL：{len(broken)} 个用例编译超时（不是编不过，是卡住了）：")
        for nm, msg in broken:
            print(f"  - tests/bad/{nm}")
        return 1
    print(f"PASS：{len(items)} 个负向用例全部按预期编不过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
