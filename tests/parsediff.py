#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage-1 parser 对拍：声明级 AST（module/import/struct/enum/fn 签名）逐行比对。

用法：
    python tests/parsediff.py           # 全量
    python tests/parsediff.py -v        # 打印每个文件的声明数
"""
import argparse
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))
sys.path.insert(0, os.path.join(ROOT, "tools", "dev"))

import astdecl  # noqa: E402

EXE = os.path.join(ROOT, "build", "qlm_parse.qex")

# stage-1 parser 的语法缺口（v1.8）：这些文件跳过声明级对拍。
# 补进 bootstrap/parser/qlm_parse.qma 后把这里清空，数字自然回升。
PARSE1_PENDING = {"t52_iface.qma", "t54_iface_dyn.qma", "t56_generic.qma",
                  "t81_generic_infer.qma",
                  "iface_missing.qma", "iface_rettype.qma", "iface_no_impl.qma",
                  "iface_dup_method.qma"}


def collect():
    files = []
    for pat in ("tests/**/*.qma", "examples/*.qma", "bootstrap/**/*.qma"):
        files += glob.glob(os.path.join(ROOT, pat), recursive=True)
    # tests/bad/ 是"预期编译失败"的负向夹具，两侧都不该产出声明
    files = [f for f in set(files) if "/bad/" not in f.replace("\\", "/")]
    # stage-1 parser 尚未实现 v1.8 的 interface / impl 声明；这些文件在
    # 语法补进 bootstrap/parser 之前跳过（**显式记账**，不是静默忽略）。
    skip = [f for f in files if os.path.basename(f) in PARSE1_PENDING]
    for f in skip:
        files.remove(f)
    if skip:
        print(f"[parsediff] 跳过 {len(skip)} 个文件（stage-1 未支持 "
              "interface/impl/泛型）："
              + ", ".join(os.path.basename(f) for f in sorted(skip)))
    return sorted(files)


def build_parser():
    cmd = [sys.executable, os.path.join(ROOT, "tools", "stage0", "qlm_cli.py"),
           "build", os.path.join(ROOT, "bootstrap", "parser", "qlm_parse.qma"),
           "--target", "win" if os.name == "nt" else "native", "-o", EXE]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write(p.stdout.decode(errors="replace"))
        sys.stderr.write(p.stderr.decode(errors="replace"))
        raise SystemExit("stage-1 parser 编译失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    build_parser()
    files = collect()
    ok = bad = 0
    for path in files:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        try:
            want = astdecl.dump(open(path, encoding="utf-8").read())
        except SyntaxError as exc:
            print(f"  [SKIP] {rel}: oracle 拒绝（{exc}）")
            continue
        p = subprocess.run([EXE, path], capture_output=True)
        got = p.stdout.decode("utf-8", errors="replace")
        if got == want:
            ok += 1
            if args.verbose:
                print(f"  [ok] {rel} ({want.count(chr(10))} decls)")
        else:
            bad += 1
            wl, gl = want.splitlines(), got.splitlines()
            print(f"  [FAIL] {rel}: oracle {len(wl)} 行 / parser {len(gl)} 行")
            shown = 0
            for i in range(max(len(wl), len(gl))):
                a = wl[i] if i < len(wl) else "<缺行>"
                b = gl[i] if i < len(gl) else "<缺行>"
                if a != b:
                    print(f"         第 {i + 1} 行：want {a!r}  got {b!r}")
                    shown += 1
                    if shown >= 2:
                        break
    print("-" * 56)
    print(f"PASS={ok} FAIL={bad}（共 {len(files)} 个源文件）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
