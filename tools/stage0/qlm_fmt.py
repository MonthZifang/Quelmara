#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara 官方格式化器（`quelmara fmt`）
==================================
SPEC §8：「官方格式化器（一种风格，终结争论）」

策略：**保留作者的换行结构，统一缩进与横向间距**，注释原样保留。
- 一个源码行 = 一个输出行（连续空行折叠为一行）
- 缩进 = 4 空格 × 花括号深度
- 独占一行的 `{` 会合并到上一行（`fn f()` + `{` -> `fn f() {`）
- 运算符两侧留空格，`,` 前不留后留，`(`/`[` 后不留、`)`/`]` 前不留

格式化器必须是幂等的：fmt(fmt(x)) == fmt(x)（有回归测试保证）。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qlm import tokenize  # noqa: E402

INDENT = "    "

# 二元/复合运算符：两侧留空格
BINOPS = {"==", "!=", "<=", ">=", "<", ">", "+", "-", "*", "/", "%",
          "=", "+=", "-=", "*=", "/=", "&&", "||", "->", "|", "&", "^"}

KEYWORDS = {"fn", "let", "mut", "if", "else", "while", "for", "parfor",
            "return", "module", "import", "test", "true", "false"}


def _is_binop(t):
    return t.kind == "SYM" and t.val in BINOPS


def _space_between(prev, cur):
    """判断两个记号之间是否需要空格（规则顺序即优先级）"""
    if prev is None:
        return False
    if prev.kind == "COMMENT" or cur.kind == "COMMENT":
        return True
    # 1) 紧贴左侧的标点
    if cur.val in (",", ")", "]", "}", ".", ":", "?", ";"):
        return False
    # 2) 紧贴右侧的标点
    if prev.val in ("(", "[", ".", "?"):
        return False
    # 3) 函数调用 / 下标 / 泛型：名字后面紧跟 ( 或 [
    if prev.kind == "NAME" and cur.val in ("(", "["):
        return False
    # 4) 切片类型 []T、索引结尾 ]name
    if prev.val == "]" and (cur.kind == "NAME" or cur.val == "["):
        return False
    # 5) 区间运算符 0..n 不留空格
    if prev.val == ".." or cur.val == "..":
        return False
    # 6) 运算符两侧留空格
    if _is_binop(prev) or _is_binop(cur):
        return True
    # 7) 关键字后面留空格
    if prev.val in KEYWORDS or prev.kind in KEYWORDS:
        return True
    return True


def _render_str(v):
    return ('"' + v.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\t", "\\t") + '"')


def _is_unary(t, prev):
    """判断 - / ! / + 是否处于一元位置（此时不留空格：-4 而不是 - 4）"""
    if t.kind != "SYM" or t.val not in ("-", "!", "+"):
        return False
    if prev is None:
        return True
    return (prev.val in ("(", "[", "{", ",", "=", "return")
            or _is_binop(prev) or prev.val == "..")


def format_src(src):
    """把 Quelmara 源码格式化成规范风格。返回格式化后的源码。"""
    toks = [t for t in tokenize(src, keep_comments=True) if t.kind != "EOF"]

    # 按源码行分组（NL 记号分隔）
    lines, cur = [], []
    for t in toks:
        if t.kind == "NL":
            if cur:
                lines.append(cur)
                cur = []
            continue
        cur.append(t)
    if cur:
        lines.append(cur)

    # 空行：两个记号组之间源码行号相差 >=2 则保留一个空行
    blank = [False] * len(lines)
    prev_src_line = None
    for i, group in enumerate(lines):
        if prev_src_line is not None and group[0].line > prev_src_line + 1:
            blank[i] = True
        prev_src_line = group[-1].line

    depth = 0
    out = []
    for i, group in enumerate(lines):
        lead_close = 0
        for t in group:
            if t.kind == "SYM" and t.val == "}":
                lead_close += 1
            else:
                break
        indent = max(0, depth - lead_close)

        # 独占一行的 `{` 合并到上一行
        if (len(group) == 1 and group[0].kind == "SYM" and group[0].val == "{"
                and out and not out[-1].strip().startswith("//")
                and not out[-1].rstrip().endswith("{")):
            out[-1] = out[-1].rstrip() + " {"
            depth += 1
            continue

        if blank[i] and out:
            out.append("")

        buf = INDENT * indent
        prev = None
        prev_unary = False
        for t in group:
            if t.kind == "COMMENT":
                if prev is not None:
                    buf += " "
                buf += t.val
                prev = t
                prev_unary = False
                continue
            if prev is not None and not prev_unary and _space_between(prev, t):
                buf += " "
            buf += _render_str(t.val) if t.kind == "STR" else str(t.val)
            prev_unary = _is_unary(t, prev)
            prev = t
        out.append(buf.rstrip())

        for t in group:                       # `}` 先减深度
            if t.kind == "SYM" and t.val == "}":
                depth = max(0, depth - 1)
        for t in group:                       # `{` 后加深度
            if t.kind == "SYM" and t.val == "{":
                depth += 1

    text = "\n".join(out)
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Quelmara 官方格式化器")
    ap.add_argument("paths", nargs="*", help=".ros 文件或目录（默认当前目录）")
    ap.add_argument("--check", action="store_true",
                    help="只检查不写入；不符合规范时退出码 1")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    targets = []
    for p in args.paths or ["."]:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in ("build", "__pycache__", ".git")]
                targets += [os.path.join(root, f) for f in files if f.endswith(".ros")]
        else:
            targets.append(p)

    bad = 0
    for t in sorted(targets):
        with open(t, encoding="utf-8") as f:
            src = f.read()
        formatted = format_src(src)
        if formatted == src:
            if not args.quiet:
                print(f"  ok    {t}")
            continue
        if args.check:
            print(f"  NEED  {t}")
            bad += 1
        else:
            with open(t, "w", encoding="utf-8") as f:
                f.write(formatted)
            if not args.quiet:
                print(f"  fmt   {t}")
    if args.check and bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
