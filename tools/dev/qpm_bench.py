#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qpm 性能探针：解析 / 落地 / 发布打包 / 校验的耗时（v1.83）。

口径：
  * 全部在**同一个进程内**调用 qpm 的 API，不含 Python 解释器启动
    （本机冷启动约 1.4 s，会把毫秒级差异全糊掉）。
  * 合成 registry：N 个包 × 3 个版本，每个包依赖 2 个"更靠后"的包（DAG，
    无环），每条依赖都是 `^1.0` 区间——即"最坏情况下的区间求值 + 定点迭代"。
  * 每个数字取 min of 5（VBS 噪声 ±50%，只做纵向比较）。

用法：
    python tools/dev/qpm_bench.py
    python tools/dev/qpm_bench.py --pkgs 80 --runs 7
"""
import argparse
import contextlib
import io
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(ROOT, "build", "_qpm_bench")
os.environ["QPM_CACHE"] = os.path.join(WORK, "cache")
os.environ["QPM_INDEX_TTL"] = "3600"
sys.path.insert(0, os.path.join(ROOT, "tools"))
import qpm  # noqa: E402


def _write_pkg(dirpath, name, version, deps):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, "Quelmara.toml"), "w", encoding="utf-8") as f:
        f.write(f'[package]\nname = "{name}"\nversion = "{version}"\n')
        if deps:
            f.write("\n[deps]\n")
            for k, v in deps.items():
                f.write(f'{k} = "{v}"\n')
    for i in range(3):
        with open(os.path.join(dirpath, f"m{i}.qma"), "w", encoding="utf-8") as f:
            f.write(f"module {name}\n\npub fn f{i}(x: int) -> int {{\n"
                    f"    return x + {i}\n}}\n")


def build_registry(n_pkgs, versions=3):
    """合成 DAG：pkg_k 依赖 pkg_{k+1}、pkg_{k+2}（都要求 ^1.0）。"""
    reg = os.path.join(WORK, "reg")
    pkgs = os.path.join(WORK, "pkgs")
    for k in range(n_pkgs):
        deps = {}
        for j in (k + 1, k + 2):
            if j < n_pkgs:
                deps[f"pkg{j:03d}"] = "^1.0"
        for v in range(versions):
            ver = f"1.{v}.0"
            d = os.path.join(pkgs, f"pkg{k:03d}-{ver}")
            _write_pkg(d, f"pkg{k:03d}", ver, deps)
            qpm.Registry("path:" + reg).publish(
                f"pkg{k:03d}", ver, qpm.pack_tree(d), deps)
    proj = os.path.join(WORK, "app")
    os.makedirs(proj, exist_ok=True)
    with open(os.path.join(proj, "Quelmara.toml"), "w", encoding="utf-8") as f:
        f.write('[registry]\ndefault = "local"\n'
                f'local = "path:{reg.replace(chr(92), "/")}"\n\n[deps]\n')
        for k in range(min(5, n_pkgs)):
            f.write(f'pkg{k:03d} = "^1.0"\n')
    return qpm.Project(proj), reg


def timed(fn, runs):
    best = None
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        dt = (time.perf_counter() - t) * 1000
        best = dt if best is None else min(best, dt)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkgs", type=int, default=40)
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()
    if os.path.isdir(WORK):
        qpm._rmtree(WORK)
    os.makedirs(WORK, exist_ok=True)

    t0 = time.perf_counter()
    proj, reg = build_registry(args.pkgs)
    setup_ms = (time.perf_counter() - t0) * 1000
    print(f"  [setup] {args.pkgs}×3 个包已发布，用时 {setup_ms:.0f} ms", flush=True)
    n_edges = sum(1 for k in range(args.pkgs) for j in (k + 1, k + 2)
                  if j < args.pkgs)

    print("  [1/4] 解析（冷/热）…", flush=True)
    # 解析：冷（refresh=True，重读全部索引）vs 热（索引缓存命中）
    cold = timed(lambda: qpm.Resolver(proj, refresh=True, log=None).run(),
                 args.runs)
    warm = timed(lambda: qpm.Resolver(proj, log=None).run(), args.runs)

    print("  [2/4] install 全流程…", flush=True)
    # 全流程：解析 + 落地 + 写锁（第一次会解包全部包体）
    def full():
        res = qpm.Resolver(proj, refresh=True, log=None).run()
        qpm.materialize(proj, res, log=lambda *a: None)
        qpm.write_lock(proj, res)
    full_ms = timed(full, max(2, args.runs - 2))
    def quiet_verify():
        with contextlib.redirect_stdout(io.StringIO()):
            qpm.verify(proj)
    ver_ms = timed(quiet_verify, max(2, args.runs - 2))

    print("  [3/4] verify…", flush=True)
    # 发布打包：20 个文件的包
    big = os.path.join(WORK, "bigpkg")
    os.makedirs(big, exist_ok=True)
    for i in range(20):
        with open(os.path.join(big, f"m{i:02d}.qma"), "w", encoding="utf-8") as f:
            f.write(f"module big\n\npub fn f{i}(x: int) -> int {{\n    return x + {i}\n}}\n")
    pack_ms = timed(lambda: qpm.pack_tree(big), args.runs)

    lock = qpm.read_lock(proj)
    print(f"qpm 性能探针：{args.pkgs} 个包 × 3 版本，{n_edges} 条依赖边，"
          f"{len(lock['packages'])} 个包被解析进锁")
    print(f"  合成 registry 用时（一次性）        {setup_ms:8.0f} ms")
    print(f"  解析（冷：重读全部索引）            {cold:8.1f} ms")
    print(f"  解析（热：索引缓存命中）            {warm:8.1f} ms")
    print(f"  install 全流程（解析+落地+写锁）    {full_ms:8.1f} ms")
    print(f"  verify（锁 vs 磁盘全量哈希）        {ver_ms:8.1f} ms")
    print(f"  publish 打包（20 文件，确定性 tar） {pack_ms:8.2f} ms")
    print(f"  包体大小（单包 4 文件）             "
          f"{len(qpm.pack_tree(os.path.join(WORK, 'pkgs', 'pkg000-1.0.0')))} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
