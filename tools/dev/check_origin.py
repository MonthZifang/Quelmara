#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原创性自查：依赖是否只用标准库、有没有混入其它语言运行时的代码特征。

用法：
    python tools/dev/check_origin.py
    python tools/dev/check_origin.py --verbose
"""
import argparse
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_DIRS = {".git", "build", "__pycache__", ".openclaw", "archive", "node_modules", "bench"}

# 其它语言/运行时的高辨识度标识（正常写 Quelmara 代码不会自然出现）
FOREIGN_MARKERS = [
    ("CPython C API", "PyObject"),
    ("CPython C API", "Py_INCREF"),
    ("CPython 头文件", "#include <Python.h>"),
    ("Go 运行时", "GOMAXPROCS"),
    ("Go 运行时", "goroutine"),
    ("Go 运行时", "runtime.mallocgc"),
    ("Go 语法", "package main"),
    ("Go 语法", "func main("),
    ("Go 语法", "go:build"),
    ("Rust 语法", "use std::"),
    ("Rust 语法", "fn main() ->"),
    ("Rust 语法", "impl Drop for"),
    ("Java/C# 语法", "public static void main"),
    ("V8/Node 内部", "Isolate::New"),
]

THIRD_PARTY_DIRS = ["vendor", "third_party", "third-party", "deps", "site-packages"]
THIRD_PARTY_EXT = [".whl", ".egg-info", ".so", ".dll", ".dylib"]


def py_files():
    out = []
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if fn.endswith(".py"):
                out.append(os.path.join(dp, fn))
    return out


def _optional_imports(tree):
    """被 try/except ImportError 包住的 import 视为「可选开发依赖」。"""
    opt = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches_import_error = any(
            (isinstance(h.type, ast.Name) and h.type.id == "ImportError")
            or (isinstance(h.type, ast.Tuple) and any(
                isinstance(x, ast.Name) and x.id == "ImportError" for x in h.type.elts))
            for h in node.handlers if h.type is not None)
        if not catches_import_error:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                opt.update(a.name.split(".")[0] for a in sub.names)
            elif isinstance(sub, ast.ImportFrom) and sub.module:
                opt.add(sub.module.split(".")[0])
    return opt


def check_imports(files, verbose):
    """所有 import 的根模块必须是标准库（或本仓库自己的模块）。
    try/except ImportError 包住的第三方依赖按「可选」处理，只警告不失败。"""
    stdlib = set(sys.stdlib_module_names)
    own = {os.path.splitext(os.path.basename(f))[0] for f in files}
    bad = []
    optional = []
    for path in files:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError as exc:
            bad.append((rel, f"语法错误：{exc}"))
            continue
        opt = _optional_imports(tree)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for n in names:
                if n not in stdlib and n not in own:
                    if n in opt:
                        optional.append((rel, n))
                    else:
                        bad.append((rel, f"第三方依赖：{n}"))
    for rel, n in optional:
        print(f"  [warn] {rel}: 可选依赖 {n}（缺失时自动跳过，不影响编译与测试）")
    if verbose:
        print(f"  扫描 {len(files)} 个 .py，标准库模块 {len(stdlib)} 个可用")
    return bad


def check_markers(files, verbose):
    hits = []
    for path in files:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        text = open(path, encoding="utf-8", errors="replace").read()
        for label, marker in FOREIGN_MARKERS:
            if marker in text:
                # 允许在"检测清单"本身与文档里出现
                if rel in ("tools/dev/check_origin.py",):
                    continue
                hits.append((rel, label, marker))
    return hits


def check_third_party():
    found = []
    for dp, dns, fns in os.walk(ROOT):
        # .qpm 是 qpm 的依赖副本（Quelmara 源码包，git tag 锁定），
        # 不属于"C/Python 第三方构建产物"检查的范畴
        dns[:] = [d for d in dns if d not in {".git", "__pycache__", ".openclaw", ".qpm"}]
        for d in list(dns):
            if d in THIRD_PARTY_DIRS:
                found.append(os.path.relpath(os.path.join(dp, d), ROOT))
        for fn in fns:
            if any(fn.endswith(e) for e in THIRD_PARTY_EXT):
                rel = os.path.relpath(os.path.join(dp, fn), ROOT)
                if not rel.startswith("build"):
                    found.append(rel)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    files = py_files()
    print(f"[1/3] 依赖检查（{len(files)} 个 .py）")
    bad = check_imports(files, args.verbose)
    for rel, msg in bad:
        print(f"  [FAIL] {rel}: {msg}")

    print("[2/3] 外部语言运行时特征")
    hits = check_markers(files, args.verbose)
    for rel, label, marker in hits:
        print(f"  [FAIL] {rel}: 出现 {label} 标识 {marker!r}")

    print("[3/3] 第三方产物目录")
    fp = check_third_party()
    for p in fp:
        print(f"  [FAIL] {p}")

    total = bad + hits + fp
    print("-" * 56)
    if total:
        print(f"FAIL: {len(total)} 处")
        return 1
    lines = 0
    for path in files:
        lines += sum(1 for _ in open(path, encoding="utf-8", errors="replace"))
    print(f"PASS：仅依赖标准库、无外部运行时特征、无第三方产物（自有 Python {lines} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
