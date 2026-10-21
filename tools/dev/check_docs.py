#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档门禁：堵住"代码已改、文档还在说旧话"这一类漂移。

背景：2026-10-21 审计发现文档比代码落后 2–3 个版本——`import` 早已实装却写着
"只做语法保留"，`vec[Struct]` 早已可用却写着"元素仅标量"，str 早已是长度前缀
ABI 却写着"len 是 O(n)"。这类错误在 Windows 上完全静默，但会直接误导使用者与
评估者（外部评估就是据此低估项目的）。

本脚本只做两件事：
1. **过期说法黑名单**：在 README / HANDOVER / SPEC / GUIDE / docs/*.md 里，
   不允许再出现已被证伪的断言（`docs/GAPS.md` 允许引用它们作反例，
   `CHANGELOG.md` 是历史记录，同样豁免）。
2. **结构完整性**：`docs/GAPS.md` 必须存在，且 README / HANDOVER / SPEC
   必须链接到它——能力边界只有一个入口。

用法：
    python tools/dev/check_docs.py            # 检查
    python tools/dev/check_docs.py --verbose  # 打印每个被检查文件
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 允许引用过期说法作为反例/历史记录的文件
ALLOW = {"docs/GAPS.md", "CHANGELOG.md", "tools/dev/check_docs.py"}

# 已被证伪的断言：(子串, 正确说法, 证据)
STALE = [
    ("import 目前只做语法保留",
     "import 已在 v1.3 实装（扁平合并）",
     "tools/stage0/qlm.py::load_program"),
    ("元素仅标量",
     "vec 元素支持标量 / struct / enum（v1.3）",
     "tests/t37_vecagg.qma"),
    ("元素限标量",
     "vec 元素支持标量 / struct / enum（v1.3）",
     "tests/t37_vecagg.qma"),
    ("vec[Struct] 暂不支持",
     "vec[Struct] 已支持（v1.3）",
     "tests/t37_vecagg.qma"),
    ("没有长度前缀",
     "str 已是长度前缀 ABI（v1.5.1）",
     "tools/stage0/qlm_native.py:665"),
]

# 必须链接到能力缺口登记册的入口文档
NEED_LINK = ["README.md", "HANDOVER.md", "SPEC.md"]
LINK_TARGET = "docs/GAPS.md"


def git_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    return [p.decode("utf-8") for p in out.split(b"\x00") if p]


def markdown_files():
    files = [f for f in git_files() if f.endswith(".md")]
    # 未入库的新文档（本轮刚写的 GAPS.md 在首次提交前）也要检查
    for extra in ("docs/GAPS.md",):
        if extra not in files and os.path.isfile(os.path.join(ROOT, extra)):
            files.append(extra)
    return sorted(set(files))


def read(rel):
    try:
        with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
            return f.read()
    except (UnicodeDecodeError, OSError):
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    files = markdown_files()
    print(f"检查 {len(files)} 个 Markdown 文件 …")

    bad = []
    for rel in files:
        if os.path.basename(rel) in ALLOW or rel in ALLOW:
            if args.verbose:
                print(f"  [skip] {rel}（允许引用过期说法）")
            continue
        text = read(rel)
        for phrase, fixed, evidence in STALE:
            if phrase in text:
                line = text[:text.index(phrase)].count("\n") + 1
                bad.append((rel, line, phrase, fixed, evidence))
        if args.verbose:
            print(f"  [ok]   {rel}")

    # 结构：GAPS.md 必须存在且被三个入口链接
    if not os.path.isfile(os.path.join(ROOT, LINK_TARGET)):
        bad.append((LINK_TARGET, 0, "文件缺失", "能力缺口登记册必须存在", "—"))
    for rel in NEED_LINK:
        if LINK_TARGET not in read(rel):
            bad.append((rel, 0, f"未链接 {LINK_TARGET}",
                        "入口文档必须指向能力缺口登记册", "—"))

    print("-" * 56)
    if bad:
        for rel, line, phrase, fixed, evidence in bad:
            loc = f"{rel}:{line}" if line else rel
            print(f"FAIL {loc}\n     命中：{phrase}\n     应为：{fixed}\n     证据：{evidence}")
        print(f"\nFAIL：{len(bad)} 处文档漂移")
        return 1

    print("PASS：无过期断言、能力缺口登记册已链接")
    return 0


if __name__ == "__main__":
    sys.exit(main())
