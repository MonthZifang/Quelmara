#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性名称迁移：旧名 -> Quelmara / qlm / stage0 路径。

用法：
    python tools/dev/migrate_names.py --dry            # 只报告命中，不落盘
    python tools/dev/migrate_names.py --scope code     # 代码/脚本（不含 md）
    python tools/dev/migrate_names.py --scope docs     # 文档
    python tools/dev/migrate_names.py --scope all

设计要点（顺序敏感、大小写敏感、幂等）：
  - 规则按列表顺序逐条 re.sub，前面规则的输出不会被后面规则再次命中；
  - 迁移工具自身、门禁脚本、迁移文档进 ALLOW，避免把自己改坏；
  - 落盘前断言 apply(apply(t)) == apply(t)，发现双替换立即中止。
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 有序规则表：(编号, 正则, 替换, 说明)
RULES = [
    ("1", r"(?:Rosoto|rosoto)\.toml", "Quelmara.toml", "配置文件名"),
    ("2", r"ROSOTO_(?=[A-Za-z0-9_])", "QLM_", "C 宏"),
    ("3", r"\bROSOTO\b", "QLM", "独立大写"),
    ("4", r"Rosoto(?=[A-Z])", "Qlm", "C 类型前缀"),
    ("5", r"Rosoto", "Quelmara", "语言名/字面量"),
    ("6a", r"(?m)^(\s*from\s+)rosoto\b", r"\1qlm", "from rosoto import"),
    ("6b", r"(?m)^(\s*import\s+)rosoto\b", r"\1qlm", "import rosoto"),
    ("6", r"rosoto_", "qlm_", "C 函数 / 模块名"),
    ("7", r"\brosoto\.py\b", "qlm.py", "核心模块文件名"),
    ("8", r"\[rosoto", "[qlm", "CLI 日志前缀"),
    ("9", r"\brosoto\b", "quelmara", "可执行名 / 诊断前缀"),
    ("10", r"tools/qlm_", "tools/stage0/qlm_", "模块路径进引导层"),
    ("11", r"tools/qlm\.py", "tools/stage0/qlm.py", "核心模块路径进引导层"),
]

ALLOW = {
    "tools/dev/migrate_names.py",
    "tools/dev/check_names.py",
    "docs/MIGRATION_rosoto_to_quelmara.md",
}

CODE_EXT = {".py", ".sh", ".cmd", ".toml", ".c", ".h", ".yml", ".yaml"}
SRC_EXT = {".ros", ".qma"}
DOC_EXT = {".md"}

SKIP_DIRS = {".git", "build", "__pycache__", ".openclaw", "archive", "node_modules", ".workbuddy"}


def apply_rules(text):
    for _no, pat, rep, _desc in RULES:
        text = re.sub(pat, rep, text)
    return text


def iter_files(scope):
    exts = set()
    if scope in ("code", "all"):
        exts |= CODE_EXT | SRC_EXT
    if scope in ("docs", "all"):
        exts |= DOC_EXT
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in exts:
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            if rel in ALLOW:
                continue
            yield path, rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只报告，不落盘")
    ap.add_argument("--scope", choices=["code", "docs", "all"], default="all")
    args = ap.parse_args()

    total_hits = 0
    changed = 0
    per_rule = {}
    for path, rel in iter_files(args.scope):
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        # 逐条统计命中（仅用于报告）
        hits = []
        for no, pat, rep, desc in RULES:
            n = len(re.findall(pat, src))
            if n:
                hits.append((no, n, desc))
                per_rule[no] = per_rule.get(no, 0) + n
        if not hits:
            continue
        out = apply_rules(src)
        if apply_rules(out) != out:
            print(f"[ABORT] 幂等检查失败（双替换）：{rel}", file=sys.stderr)
            print(f"        第二次: {out}", file=sys.stderr)
            return 2
        detail = ", ".join(f"r{no}×{n}" for no, n, _d in hits)
        print(f"{'[dry] ' if args.dry else ''}{rel}: {detail}")
        total_hits += sum(n for _no, n, _d in hits)
        changed += 1
        if not args.dry:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(out)

    print("-" * 60)
    print(f"{'命中' if args.dry else '改写'}文件 {changed} 个，替换 {total_hits} 处")
    print("按规则:", ", ".join(f"r{k}={v}" for k, v in sorted(per_rule.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
