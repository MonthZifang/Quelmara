#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
`.qla` 目标文件 / 函数级增量 / 二进制库链接的性能口径（v2.03）
============================================================
跑法：
    python tools/dev/qla_bench.py            # 默认负载 bench/qla_bench.qma
    python tools/dev/qla_bench.py --src X    # 换负载
    python tools/dev/qla_bench.py --rounds 5

量的是**编译期**，不是运行期：

  1. 冷编译到 `.qla`（全量降级 + 优化）
  2. 无改动增量（全部函数复用）——必须与冷编译**逐字节相同**
  3. 改一个函数体后的增量（只有它重降级）
  4. 改一个被调方签名后的增量（调用方也要跟着重编）
  5. `link` 一份/两份档案的耗时
  6. 档案体积与 IR 条数

口径与坑：
  * 用 `min-of-N`（本机噪声大）；**不要在并行会话跑回归时采数**（读数上浮 30–50%）。
  * 冷编译关掉 `.qlmcache`（`QLM_NO_CACHE=1`）：这里量的是降级，不是缓存命中。
  * 增量构建仍然要**解析**源码（哈希按 AST 算），所以下限是"解析 + 代码发射"，
    降级+优化省下来的那部分才是收益。
"""

import argparse
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))


def best(fn, rounds=3):
    vals = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        vals.append((time.perf_counter() - t0) * 1000.0)
    return min(vals), sorted(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "bench", "qla_bench.qma"))
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()
    os.environ["QLM_NO_CACHE"] = "1"

    import qlm_pe
    import qlm_qla

    src = os.path.abspath(args.src)
    work = tempfile.mkdtemp(prefix="qlabench_")
    copy = os.path.join(work, os.path.basename(src))
    shutil.copy(src, copy)
    # 同目录的 import 依赖：bench/ 与 std/ 都在仓库里，源码路径不变即可
    arc_path = os.path.join(work, "out.qla")

    def cold():
        arc, meta, _ = qlm_pe.emit_archive(copy)
        arc.save(arc_path)
        return arc, meta

    t_cold, cold_all = best(cold, args.rounds)
    arc0, meta0 = cold()
    n_fn, n_ir = len(arc0.funcs), arc0.ninstrs()
    size = os.path.getsize(arc_path)

    base = qlm_qla.Archive.load(arc_path)

    def warm():
        arc, meta, _ = qlm_pe.emit_archive(copy, reuse=base)
        return arc, meta

    t_warm, warm_all = best(warm, args.rounds)
    arc1, meta1 = warm()
    identical = arc1.to_bytes() == base.to_bytes()

    # ---- 改一个函数体 ----
    text = open(copy, encoding="utf-8").read()
    patched = text.replace("    acc = acc + m\n",
                           "    acc = acc + m + 0\n", 1)
    open(copy, "w", encoding="utf-8", newline="\n").write(patched)

    def body_change():
        return qlm_pe.emit_archive(copy, reuse=base)

    t_body, body_all = best(body_change, args.rounds)
    _a, m_body, _ = body_change()

    # ---- 改被调方签名（work 的形参类型 int -> int 不变，改 std 调用面）----
    text2 = text.replace("fn work(seed: int) -> int {",
                         "fn work(seed: int) -> int {\n    let pad = seed + 0", 1)
    open(copy, "w", encoding="utf-8", newline="\n").write(text2)

    def sig_change():
        return qlm_pe.emit_archive(copy, reuse=base)

    t_sig, _ = best(sig_change, args.rounds)
    _a2, m_sig, _ = sig_change()

    # ---- link ----
    def link1():
        return qlm_pe.link_win([base])

    t_link, _ = best(link1, args.rounds)
    pe, _lk = link1()

    print(f"负载: {os.path.relpath(src, ROOT)}")
    print(f"  函数 {n_fn} 个 / IR {n_ir} 条 / 档案 {size} 字节 / "
          f"PE {len(pe)} 字节")
    print()
    print(f"{'场景':<26}{'ms':>9}{'倍数':>8}  复用")
    print(f"{'冷编译（全量降级）':<26}{t_cold:>9.1f}{1.0:>8.2f}x  —")
    print(f"{'无改动增量':<26}{t_warm:>9.1f}{t_cold / t_warm:>8.2f}x  "
          f"{meta1['nreused']}/{meta1['ntotal']} 函数、"
          f"IR {meta1.get('irreused', 0)}/{meta1.get('irtotal', 0)} 条"
          f"{'  [逐字节相同]' if identical else '  [!! 字节不同 !!]'}")
    print(f"{'改一个函数体':<26}{t_body:>9.1f}{t_cold / t_body:>8.2f}x  "
          f"{m_body['nreused']}/{m_body['ntotal']} 函数、"
          f"IR {m_body.get('irreused', 0)}/{m_body.get('irtotal', 0)} 条")
    print(f"{'改一个函数（新增语句）':<26}{t_sig:>9.1f}{t_cold / t_sig:>8.2f}x  "
          f"{m_sig['nreused']}/{m_sig['ntotal']} 函数")
    print(f"{'link 单档案':<26}{t_link:>9.1f}{'':>8}  {len(base.funcs)} 函数")
    print()
    print(f"冷编译样本: {', '.join('%.1f' % v for v in cold_all)}")
    print(f"无改动样本: {', '.join('%.1f' % v for v in warm_all)}")
    print(f"改函数样本: {', '.join('%.1f' % v for v in body_all)}")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if identical else 1


if __name__ == "__main__":
    sys.exit(main())
