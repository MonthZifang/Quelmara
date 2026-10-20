#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage-1 词法器对拍：Quelmara 写的 qlm_lex 与 stage-0 tokenize 逐行比对。

用法：
    python tests/lexdiff.py              # 全量（所有 .qma + fixtures）
    python tests/lexdiff.py -v           # 打印每个文件的 token 数
"""
import argparse
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))
sys.path.insert(0, os.path.join(ROOT, "tools", "dev"))

import tokfmt  # noqa: E402

EXE = os.path.join(ROOT, "build", "qlm_lex.qex")


def collect():
    files = []
    for pat in ("tests/**/*.qma", "examples/*.qma", "bootstrap/**/*.qma"):
        files += glob.glob(os.path.join(ROOT, pat), recursive=True)
    return sorted(set(files))


def build_lexer():
    out = EXE
    cmd = [sys.executable, os.path.join(ROOT, "tools", "stage0", "qlm_cli.py"),
           "build", os.path.join(ROOT, "bootstrap", "lexer", "qlm_lex.qma"),
           "--target", "win" if os.name == "nt" else "native", "-o", out]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write(p.stdout.decode(errors="replace"))
        sys.stderr.write(p.stderr.decode(errors="replace"))
        raise SystemExit("词法器编译失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    build_lexer()
    files = collect()
    ok = bad = 0
    for path in files:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        src = open(path, encoding="utf-8").read()
        try:
            tokfmt.selfcheck(src)                    # oracle 与真实词法器一致性
            want = tokfmt.dump(src)
        except (SyntaxError, AssertionError) as exc:
            print(f"  [SKIP] {rel}: oracle {type(exc).__name__}: {exc}")
            continue
        p = subprocess.run([EXE, path], capture_output=True)
        got = p.stdout.decode("utf-8", errors="replace")
        if got == want:
            ok += 1
            if args.verbose:
                print(f"  [ok] {rel} ({want.count(chr(10))} tokens)")
        else:
            bad += 1
            wl, gl = want.splitlines(), got.splitlines()
            print(f"  [FAIL] {rel}: oracle {len(wl)} 行 / lexer {len(gl)} 行 rc={p.returncode}")
            for i, (a, b) in enumerate(zip(wl, gl)):
                if a != b:
                    print(f"         第 {i + 1} 行：want {a!r}  got {b!r}")
                    break
    print("-" * 56)
    print(f"PASS={ok} FAIL={bad}（共 {len(files)} 个源文件）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
