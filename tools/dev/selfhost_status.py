#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打印 Quelmara 自举进度：哪些组件已经由 Quelmara 自己实现。

用法：python tools/dev/selfhost_status.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 组件退场表（与 docs/SELFHOST.md 保持一致）
COMPONENTS = [
    # (组件, stage-0 实现, stage-1 目标, 自检命令)
    ("词法", "tools/stage0/qlm.py::tokenize", "bootstrap/lexer/qlm_lex.qma",
     ["tests/lexdiff.py"]),
    ("语法", "tools/stage0/qlm.py::Parser", "bootstrap/parser/", None),
    ("类型推断", "tools/stage0/qlm.py 推断层", "bootstrap/typeck/", None),
    ("AST->IR", "tools/stage0/qlm_native.py::Lower", "bootstrap/ir/", None),
    ("优化", "tools/stage0/qlm_opt.py", "bootstrap/opt/", None),
    ("x86_64 编码", "tools/stage0/qlm_native.py::Codegen", "bootstrap/codegen/x64/", None),
    ("ELF 写出", "tools/stage0/qlm_native.py", "bootstrap/codegen/elf/", None),
    ("PE 写出", "tools/stage0/qlm_pe.py", "bootstrap/codegen/pe/", None),
    ("AArch64", "tools/stage0/qlm_arm64.py", "bootstrap/codegen/a64/", None),
    ("C99 后端", "tools/stage0/qlm.py::Codegen", "（不移植，仅交叉验证）", None),
]


def lines_of(path):
    p = os.path.join(ROOT, path)
    if not os.path.isfile(p):
        return 0, 0
    n = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
    return n, 0


def bootstrap_lines():
    total = 0
    base = os.path.join(ROOT, "bootstrap")
    for dp, _dn, fns in os.walk(base):
        for fn in fns:
            if fn.endswith(".qma"):
                total += sum(1 for _ in open(os.path.join(dp, fn), encoding="utf-8"))
    return total


def stage0_lines():
    total = 0
    base = os.path.join(ROOT, "tools", "stage0")
    for fn in os.listdir(base):
        if fn.endswith(".py"):
            total += sum(1 for _ in open(os.path.join(base, fn), encoding="utf-8"))
    return total


def main():
    s1 = bootstrap_lines()
    s0 = stage0_lines()
    print(f"{'组件':<10} {'阶段':<6} {'stage-1 目标':<28} 说明")
    print("-" * 78)
    done = 0
    for name, impl0, impl1, check in COMPONENTS:
        exists = "-" if impl1.startswith("（") else (
            "就绪" if os.path.exists(os.path.join(ROOT, impl1)) else "缺失")
        status = "stage1" if exists == "就绪" else "stage0"
        if status == "stage1":
            done += 1
        verify = ""
        if status == "stage1" and check:
            r = subprocess.run([sys.executable] + [os.path.join(ROOT, c) for c in check],
                               capture_output=True, cwd=ROOT)
            verify = "对拍通过" if r.returncode == 0 else "对拍失败"
        print(f"{name:<10} {status:<6} {impl1:<28} {exists} {verify}")
    print("-" * 78)
    real = [c for c in COMPONENTS if not c[2].startswith("（")]
    print(f"组件自举：{done}/{len(real)}")
    print(f"代码行数：自举 {s1} 行  /  stage-0 {s0} 行  "
          f"（自举占比 {100.0 * s1 / max(1, s0 + s1):.1f}%）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
