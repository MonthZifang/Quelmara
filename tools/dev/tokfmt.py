#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""词法器对拍协议（stage-0 侧 oracle）。

协议：每个 token 一行 `KIND|RAW|LINE`
  - KIND: KW / NAME / INT / FLOAT / STR / SYM / EOF
  - RAW : 源码原文切片（STR 去掉两侧引号，保留转义原样；数字保留 `_` 与 `f` 后缀）
  - LINE: token **起始**行号（1 起）
  - RAW 里的 `\\` `|` 换行 制表 回车 需转义成 `\\\\` `\\|` `\\n` `\\t` `\\r`

为什么不比对 token 的「值」而比对原文：值需要浮点格式化、转义解码，
两侧实现稍有差异就会假红；而"扫描边界"才是词法器的核心正确性。

自检：`scan_raw` 产出的 KIND 序列必须与 qlm.tokenize 的 kind 序列一致，
每次对拍前都会跑这条断言，防止协议实现与真实词法器漂移。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

from qlm import KEYWORDS, SYMBOLS, tokenize  # noqa: E402


def esc(s):
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "|":
            out.append("\\|")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        else:
            out.append(ch)
    return "".join(out)


def scan_raw(src):
    """返回 [(kind, raw, line)]，规则与 qlm.tokenize 逐一对应。"""
    toks = []
    i, line, n = 0, 1, len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            i += 2
            while i < n and not src.startswith("*/", i):
                if src[i] == "\n":
                    line += 1
                i += 1
            i += 2
            continue
        if c.isdigit() and i + 1 < n and src[i] == "0" and src[i + 1] in "xXbBoO":
            start, startline = i, line
            base = {"x": 16, "b": 2, "o": 8}[src[i + 1].lower()]
            ok = "0123456789abcdefABCDEF" if base == 16 else (
                "01" if base == 2 else "01234567")
            j = i + 2
            while j < n and (src[j] in ok or src[j] == "_"):
                j += 1
            if j == i + 2:
                raise SyntaxError("line %d: 基数前缀后面缺少数字" % line)
            toks.append(("INT", src[start:j], startline))
            i = j
            continue
        if c.isdigit():
            start, startline = i, line
            j = i
            while j < n and (src[j].isdigit() or src[j] == "_"):
                j += 1
            is_float = False
            if j + 1 < n and src[j] == "." and src[j + 1].isdigit():
                is_float = True
                j += 1
                while j < n and (src[j].isdigit() or src[j] == "_"):
                    j += 1
            if j < n and src[j] in "eE":
                k2 = j + 1
                if k2 < n and src[k2] in "+-":
                    k2 += 1
                if k2 < n and src[k2].isdigit():
                    is_float = True
                    j = k2
                    while j < n and (src[j].isdigit() or src[j] == "_"):
                        j += 1
            if is_float and j < n and src[j] == "f" and not (
                    j + 1 < n and (src[j + 1].isalnum() or src[j + 1] == "_")):
                j += 1
            toks.append(("FLOAT" if is_float else "INT", src[start:j], startline))
            i = j
            continue
        if c.isalpha() or c == "_":
            start = i
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[start:j]
            toks.append(("KW" if word in KEYWORDS else "NAME", word, line))
            i = j
            continue
        if c == '"':
            start, startline = i, line
            j = i + 1
            closed = False
            while j < n:
                if src[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if src[j] == '"':
                    closed = True
                    break
                if src[j] == "\n":
                    line += 1
                j += 1
            if not closed:
                raise SyntaxError("line %d: 字符串未闭合" % startline)
            toks.append(("STR", src[start + 1:j], startline))
            i = j + 1
            continue
        for sym in SYMBOLS:
            if src.startswith(sym, i):
                toks.append(("SYM", sym, line))
                i += len(sym)
                break
        else:
            raise SyntaxError("line %d: 非法字符 %r" % (line, c))
    toks.append(("EOF", "", line))
    return toks


def dump(src):
    """协议文本（末尾带换行）"""
    return "".join("%s|%s|%d\n" % (k, esc(raw), ln) for k, raw, ln in scan_raw(src))


def selfcheck(src):
    """协议实现 vs 真实词法器：KIND 序列必须一致"""
    want = [("KW" if t.kind in KEYWORDS else t.kind) for t in tokenize(src)]
    got = [k for k, _r, _l in scan_raw(src)]
    if want != got:
        for idx, (a, b) in enumerate(zip(want, got)):
            if a != b:
                raise AssertionError(f"第 {idx} 个 token kind 不一致：oracle={a} tokenize={b}")
        raise AssertionError(f"token 数不一致：oracle={len(got)} tokenize={len(want)}")


if __name__ == "__main__":
    for path in sys.argv[1:]:
        src = open(path, encoding="utf-8").read()
        selfcheck(src)
        sys.stdout.buffer.write(dump(src).encode("utf-8"))
