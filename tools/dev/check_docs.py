#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档门禁：堵住"代码已改、文档还在说旧话"这一类漂移。

背景（两次真实事故）：
1. 2026-10-21：文档比代码落后 2–3 个版本（`import` 早已实装却写"只做语法保留"，
   `vec[Struct]` 早已可用却写"元素仅标量"）。
2. 2026-10-22：同一指标在四份文档里分别是 96 / 113 / 116 / 124，而旧门禁只查短语
   不查数字，全部放行；`docs/STATUS.md` 整篇停在 v1.10。

因此本脚本做五件事：
1. **过期断言黑名单**：已被证伪的说法不得出现（`docs/00-convention.md` 与
   `versions/archive/` 允许引用作反例/历史）。
2. **索引完整性**：`docs/` 下每份 `.md` 都必须在 `docs/README.md` 里被列出。
3. **版本目录完整性**：`docs/versions/v*/` 必须含 `CHANGELOG.md`。
4. **数字单一来源**：实测数字只允许出现在 `docs/06-status.md` 与 `versions/`。
5. **标题存在**：每份文档以 `# ` 开头（避免空文件/半成品）。

用法：
    python tools/dev/check_docs.py
    python tools/dev/check_docs.py --verbose
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs")

# 允许引用过期说法 / 实测数字的文件（相对路径前缀）
ALLOW_STALE = {"docs/00-convention.md"}
ALLOW_NUM = {"docs/00-convention.md", "docs/06-status.md"}
NUM_EXEMPT_PREFIX = ("docs/versions/",)
# 含这些词的句子是在说"目标/计划"，不是实测
PLAN_WORDS = ("目标", "规划", "计划", "路线", "预期")

# 已被证伪的断言：(子串, 正确说法, 证据)
STALE = [
    ("import 目前只做语法保留",
     "import 已在 v1.3 实装（扁平合并）",
     "tools/stage0/qlm.py::load_program"),
    ("元素仅标量",
     "vec 元素支持标量 / struct / enum / vec",
     "tests/t37_vecagg.qma、tests/t57_vecnest.qma"),
    ("元素限标量",
     "vec 元素支持标量 / struct / enum / vec",
     "tests/t37_vecagg.qma"),
    ("vec[Struct] 暂不支持",
     "vec[Struct] 已支持",
     "tests/t37_vecagg.qma"),
    ("vec[vec[T]] 暂不支持",
     "vec[vec[T]] 已支持（v1.12，句柄语义）",
     "tests/t57_vecnest.qma"),
    ("vec[vec[T]] 仍不支持",
     "vec[vec[T]] 已支持（v1.12，句柄语义）",
     "tests/t57_vecnest.qma"),
    ("没有长度前缀",
     "str 已是长度前缀 ABI（v1.5.1）",
     "tools/stage0/qlm_native.py:665"),
    ("动态分发未实现",
     "interface 动态分发 v1.9 已落地",
     "tests/t54_iface_dyn.qma"),
    ("IOCP/AFD）尚未接入",
     "IOCP reactor v1.4 已落地",
     "std/net/core.qma"),
]

# 数字单一来源：这些形态只允许出现在 06-status.md 与 versions/
NUM_PATTERNS = [
    re.compile(r"回归[^\n]{0,8}?\d+\s*项"),
    re.compile(r"\d+\s*项全绿"),
    re.compile(r"PASS=\d+"),
    re.compile(r"自举\s*\d+\s*/\s*\d+"),
]


def git_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, check=True).stdout
        files = [p.decode("utf-8") for p in out.split(b"\x00") if p]
    except (OSError, subprocess.CalledProcessError):
        files = []
    # 未入库的新文档也要检查
    for base, _dirs, names in os.walk(DOCS):
        for n in names:
            if n.endswith(".md"):
                rel = os.path.relpath(os.path.join(base, n), ROOT).replace(os.sep, "/")
                if rel not in files:
                    files.append(rel)
    return sorted(set(files))


def read(rel):
    try:
        with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
            return f.read()
    except (UnicodeDecodeError, OSError):
        return ""


def is_archive(rel):
    return rel.startswith("docs/versions/archive/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    files = [f for f in git_files() if f.endswith(".md")]
    print(f"检查 {len(files)} 个 Markdown 文件 …")
    bad = []

    # 1) 过期断言 + 5) 标题
    for rel in files:
        text = read(rel)
        if args.verbose:
            print(f"  [scan] {rel}")
        if not text.lstrip().startswith("# "):
            bad.append((rel, 0, "缺少一级标题", "每份文档以 `# 标题` 开头", "—"))
        if rel in ALLOW_STALE or rel.startswith("docs/versions/"):
            continue
        for phrase, fixed, evidence in STALE:
            if phrase in text:
                line = text[:text.index(phrase)].count("\n") + 1
                bad.append((rel, line, phrase, fixed, evidence))

    # 2) 索引完整性
    index = read("docs/README.md")
    if not index:
        bad.append(("docs/README.md", 0, "索引缺失", "docs/README.md 必须存在", "—"))
    else:
        for rel in files:
            if not rel.startswith("docs/") or rel.startswith("docs/versions/"):
                continue
            name = os.path.basename(rel)
            if name not in index:
                bad.append((rel, 0, "未出现在 docs/README.md 索引",
                            "每份文档都要在索引里列出", "—"))

    # 3) 版本目录完整性
    vdir = os.path.join(DOCS, "versions")
    if os.path.isdir(vdir):
        for name in sorted(os.listdir(vdir)):
            p = os.path.join(vdir, name)
            if not os.path.isdir(p) or not re.match(r"v\d+\.\d+", name):
                continue
            rel = f"docs/versions/{name}/CHANGELOG.md"
            if not os.path.isfile(os.path.join(ROOT, rel)):
                bad.append((rel, 0, "版本目录缺少 CHANGELOG.md",
                            "每个 vX.Y 目录必须有 CHANGELOG.md", "—"))

    # 4) 数字单一来源
    for rel in files:
        if rel in ALLOW_NUM or rel.startswith(NUM_EXEMPT_PREFIX):
            continue
        text = read(rel)
        for pat in NUM_PATTERNS:
            for m in pat.finditer(text):
                line_no = text[:m.start()].count("\n") + 1
                line = text.splitlines()[line_no - 1]
                if any(w in line for w in PLAN_WORDS):
                    continue          # "目标是 9/9" 这类不是实测
                bad.append((rel, line_no, m.group(0).strip(),
                            "实测数字只写在 docs/06-status.md 与 versions/ 下",
                            "docs/06-status.md"))
                break

    print("-" * 56)
    if bad:
        for rel, line, phrase, fixed, evidence in bad:
            loc = f"{rel}:{line}" if line else rel
            print(f"FAIL {loc}\n     命中：{phrase}\n     应为：{fixed}\n     证据：{evidence}")
        print(f"\nFAIL：{len(bad)} 处文档问题")
        return 1

    print("PASS：无过期断言、索引完整、版本目录完整、数字单一来源")
    return 0


if __name__ == "__main__":
    sys.exit(main())
