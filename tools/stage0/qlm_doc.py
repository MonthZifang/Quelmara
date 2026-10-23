#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quelmara doc comment 生成器 —— `quelmara doc`（v1.92）

`///` 的**语法**由语言层实现（`tools/stage0/qlm.py::scan_doc_comments`，
规则见 `docs/02-language.md` §2.4）；本模块只做三件事：按行号取回文档、
截出可读的签名/声明块、渲染成 Markdown 或 JSON。

**单一实现**：`gen_stdlib_doc.py`（生成 `docs/03-stdlib.md` 的 API 段）
复用本模块的 `scan_file` / `fn_counts`，不再自己扫一遍源码。

语法（摘要，权威在 02-language.md §2.4）：
  * `///` 行文档注释，紧贴其下的**顶层**声明（fn / struct / enum / interface）；
  * `//!` 文件头模块文档；
  * `////` 与 `//` 是普通注释；缩进的 `///`（函数体 / impl 内）不收；
  * 空行、其它代码即脱离——脱离的块会被 `--check` / `--missing` 判为错误。

CLI：
  python tools/stage0/qlm_doc.py <src.qma|dir...>              # Markdown -> stdout
  python tools/stage0/qlm_doc.py <paths...> -o api.md           # 写文件
  python tools/stage0/qlm_doc.py <paths...> -o api.md --check   # 只校验一致（CI）
  python tools/stage0/qlm_doc.py <paths...> --missing           # 公开声明缺文档 -> 退出码 1
  python tools/stage0/qlm_doc.py <paths...> --format json       # 机器可读（LSP 预留）
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qlm import SRC_EXT, iter_decls, scan_doc_comments  # noqa: E402


class Decl:
    """一个声明及其文档。"""

    __slots__ = ("kind", "name", "signature", "doc", "line", "is_pub")

    def __init__(self, kind, name, signature, doc, line, is_pub):
        self.kind = kind                    # fn / struct / enum / interface
        self.name = name
        self.signature = signature          # 显示用：剥 pub 前缀、归一空白
        self.doc = doc                      # 段落列表，每段是行列表
        self.line = line                    # 声明行号（1 起）
        self.is_pub = is_pub

    def __repr__(self):
        return f"<{self.kind} {self.name} doc={bool(self.doc)}>"


class Module:
    """一个源文件的文档。"""

    __slots__ = ("path", "module_doc", "decls", "orphans")

    def __init__(self, path, module_doc, decls, orphans):
        self.path = path
        self.module_doc = module_doc        # 段落列表
        self.decls = decls                  # [Decl]
        self.orphans = orphans              # [(行号, 原因)]


def _split_paragraphs(lines):
    """doc 行列表 -> 段落列表（空串分段）。"""
    paras, cur = [], []
    for ln in lines:
        if ln.strip():
            cur.append(ln)
        elif cur:
            paras.append(cur)
            cur = []
    if cur:
        paras.append(cur)
    return paras


def _collapse(parts):
    """字符片段 -> 单行签名：折叠空白、剥 pub 前缀。"""
    s = " ".join("".join(parts).split())
    return s[4:] if s.startswith("pub ") else s


def _capture_fn_sig(lines, idx):
    """声明行 -> 签名文本：截到行内第一个顶层 `{`；无函数体则整行。"""
    parts, depth = [], 0
    for ln in lines[idx:idx + 60]:
        for ch in ln:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch == "{" and depth <= 0:
                return _collapse(parts)
            parts.append(ch)
        if depth <= 0 and not ln.rstrip().endswith((",", "->")):
            break
        parts.append(" ")
    return _collapse(parts)


def _capture_type_block(lines, idx):
    """声明行 -> 完整声明块（含字段/变体），去掉 `pub ` 与尾部空行。"""
    out, depth, opened = [], 0, False
    for ln in lines[idx:]:
        out.append(ln.rstrip())
        depth += ln.count("{") - ln.count("}")
        if "{" in ln:
            opened = True
        if opened and depth <= 0:
            break
    while out and not out[-1]:
        out.pop()
    text = "\n".join(out)
    return text[4:] if text.startswith("pub ") else text


def scan_file(path, rel=None):
    """扫一个 .qma -> Module（公开声明表 + 文档 + 签名 + 脱离块）。

    公开 API 面 = 顶层 `pub` 声明（含没写 `///` 的——`--missing` 靠它统计）；
    非 pub 声明即使写了 `///` 也不进公开文档（前端仍挂到 AST 上）。
    """
    with open(path, encoding="utf-8") as f:
        src = f.read()
    lines = src.splitlines()
    module_doc, blocks, orphans = scan_doc_comments(src)
    doc_at = {line: doc for line, _k, _n, _p, doc in blocks}
    decls = []
    for line, kind, name, is_pub in iter_decls(src):
        if not is_pub:
            continue
        idx = line - 1
        sig = (_capture_type_block(lines, idx) if kind != "fn"
               else _capture_fn_sig(lines, idx))
        decls.append(Decl(kind, name, sig,
                          _split_paragraphs(doc_at.get(line, [])), line, is_pub))
    return Module(rel or path.replace(os.sep, "/"), _split_paragraphs(module_doc),
                  decls, orphans)


def fn_counts(path):
    """(pub fn 数, 内部 fn 数)——文档引言句用，与 scan_file 同源。"""
    pub = internal = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s.startswith("fn ") and not s.startswith("pub fn "):
                continue
            if s.startswith("pub fn "):
                pub += 1
            else:
                internal += 1
    return pub, internal


def iter_sources(paths):
    """路径参数 -> .qma 文件列表（目录递归，保持给定顺序）。"""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for dp, dns, fns in sorted(os.walk(p)):
                dns[:] = sorted(d for d in dns
                                if d not in ("build", "__pycache__", ".git"))
                out.extend(os.path.join(dp, fn) for fn in sorted(fns)
                           if fn.endswith(SRC_EXT))
        else:
            out.append(p)
    return out


def _paras(paras):
    return ["\n".join(p) for p in paras]


def render_markdown(modules, title="API 文档"):
    """[Module] -> Markdown 文本。"""
    parts = [f"# {title}", "",
             "> 由 `quelmara doc` 从源码 doc comment 生成，不要手改。", ""]
    for mod in modules:
        parts.append(f"## `{mod.path}`")
        parts.append("")
        for para in _paras(mod.module_doc):
            parts.append(para)
            parts.append("")
        if not mod.decls:
            parts.append("（无公开声明）")
            parts.append("")
        for d in mod.decls:
            parts.append(f"### `{d.name}`")
            parts.append("")
            for para in _paras(d.doc):
                parts.append(para)
                parts.append("")
            parts.append("```quelmara")
            parts.append(d.signature)
            parts.append("```")
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_json(modules):
    """[Module] -> JSON 文本（机器可读：LSP / 索引预留）。"""
    data = {"version": 1, "generator": "quelmara doc", "modules": []}
    for mod in modules:
        data["modules"].append({
            "path": mod.path,
            "module_doc": _paras(mod.module_doc),
            "decls": [{"kind": d.kind, "name": d.name, "line": d.line,
                       "pub": d.is_pub, "signature": d.signature,
                       "doc": _paras(d.doc)} for d in mod.decls],
        })
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def missing_report(modules):
    """[(路径, 行号, 名字, 原因)]——公开声明缺文档 + 脱离块。"""
    out = []
    for mod in modules:
        for line, why in mod.orphans:
            out.append((mod.path, line, "", why))
        for d in mod.decls:
            if d.is_pub and not d.doc:
                out.append((mod.path, d.line, d.name, "公开声明没有 /// 文档"))
    return out


def collect(paths, rel_root=None):
    """路径 -> [Module]（相对路径用于标题，便于跨平台稳定输出）。"""
    mods = []
    for path in iter_sources(paths):
        if not os.path.isfile(path):
            raise SystemExit(f"qlm_doc: 文件不存在：{path}")
        rel = os.path.relpath(path, rel_root) if rel_root else path
        mods.append(scan_file(path, rel.replace(os.sep, "/")))
    return mods


def main(argv=None):
    ap = argparse.ArgumentParser(description="Quelmara doc comment 生成器")
    ap.add_argument("paths", nargs="+", help=".qma 文件或目录")
    ap.add_argument("-o", "--out", help="输出文件（缺省打印 stdout）")
    ap.add_argument("--format", choices=["md", "json"], default=None,
                    help="输出格式（缺省：看 -o 扩展名，否则 md）")
    ap.add_argument("--title", default="API 文档", help="Markdown 一级标题")
    ap.add_argument("--check", action="store_true",
                    help="配合 -o：只校验输出与文件一致，不写")
    ap.add_argument("--missing", action="store_true",
                    help="列出公开声明缺文档 / 脱离的 doc 块；有则退出码 1")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    fmt = args.format or ("json" if (args.out or "").endswith(".json") else "md")
    mods = collect(args.paths, rel_root=None)

    for mod in mods:                     # 脱离的 doc 块：永远是问题
        for line, why in mod.orphans:
            sys.stderr.write(f"  [orphan] {mod.path}:{line}  {why}\n")

    if args.missing:
        miss = missing_report(mods)
        n_pub = sum(1 for m in mods for d in m.decls if d.is_pub)
        n_doc = sum(1 for m in mods for d in m.decls if d.is_pub and d.doc)
        for path, line, name, why in miss:
            sys.stderr.write(f"  [missing] {path}:{line}  "
                             f"{name + '：' if name else ''}{why}\n")
        if miss:
            print(f"FAIL：{len(miss)} 处（公开声明 {n_pub} 个，带文档 {n_doc} 个）")
            return 1
        print(f"PASS：{len(mods)} 个模块 / {n_pub} 个公开声明全部有 doc comment")
        return 0

    text = render_json(mods) if fmt == "json" else render_markdown(mods, args.title)
    if not args.out:
        sys.stdout.write(text)
        return 0
    if args.check:
        try:
            with open(args.out, encoding="utf-8") as f:
                cur = f.read()
        except OSError:
            print(f"FAIL：{args.out} 不存在（先跑一次生成）")
            return 1
        if cur != text:
            print(f"FAIL：{args.out} 与源码 doc comment 不一致，"
                  f"请重新生成（quelmara doc ... -o {args.out}）")
            return 1
        if not args.quiet:
            print(f"PASS：{len(mods)} 个模块，{args.out} 与源码一致")
        return 0

    d = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(d, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    n = sum(len(m.decls) for m in mods)
    if not args.quiet:
        print(f"已生成 {args.out}：{len(mods)} 个模块 / {n} 个公开声明")
    return 0


if __name__ == "__main__":
    sys.exit(main())
