#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qlm_doc —— Quelmara doc comment 生成器（v1.47）。

**自研实现**：只用 Python 标准库；纯文本扫描，不依赖编译器（编译器不解析
`///`——本工具是 doc comment 的唯一消费方，边界如实登记）。

语法约定（自研设计，v1.47 口径）：
  * `///` 行文档注释，必须**紧贴**其下的顶层 pub 声明（fn / struct / enum），
    中间有空行即脱离，该注释块被忽略（不报错）；
  * `////` 四斜杠是普通注释，`//` 两斜杠同理，都不产生文档；
  * `///` 后可选一个空格；块内空 `///` 行 = 段落分隔；
  * 只收 **pub** 顶层声明——内部函数不进公开文档（与 pub 可见性语义一致）；
  * doc 文本按 Markdown 解释（本工具只做原样透出，不渲染）。

CLI：
  python tools/dev/qlm_doc.py <src.qma|dir...>            # 打印到 stdout
  python tools/dev/qlm_doc.py <paths...> -o out.md        # 写文件
  python tools/dev/qlm_doc.py <paths...> -o out.md --check  # 只校验一致（CI）

gen_stdlib_doc.py 复用本模块的 scan_file / fn_counts 生成 03-stdlib.md。
"""
import argparse
import os
import re
import sys

DECL_RE = re.compile(r"^pub\s+(fn|struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)")
ANY_FN_RE = re.compile(r"^(?:pub\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)")


class Decl:
    """一个 pub 顶层声明及其文档。"""

    __slots__ = ("kind", "name", "signature", "doc")

    def __init__(self, kind, name, signature, doc):
        self.kind = kind                    # fn / struct / enum
        self.name = name
        self.signature = signature          # 显示用：剥 pub 前缀、归一空白
        self.doc = doc                      # 段落列表，每段是行列表

    def __repr__(self):
        return f"<{self.kind} {self.name} doc={bool(self.doc)}>"


def _norm_signature(line):
    """声明行 -> 显示签名：剥 pub 前缀、去尾部 {、折叠空白。"""
    s = re.sub(r"\s+", " ", line.strip())
    if s.endswith("{"):
        s = s[:-1].strip()
    if s.startswith("pub "):
        s = s[4:]
    return s


def _split_paragraphs(lines):
    """doc 行列表 -> 段落列表（空行分段）。"""
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


def scan_file(path):
    """扫一个 .qma：返回 pub 声明列表（含紧贴的 /// 文档）。

    单行签名口径：声明只取第一行——多行签名（罕见）只显示首行，
    边界如实登记。doc 只认紧贴声明（无空行间隔）的连续 /// 块。
    """
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, pending = [], []
    for line in lines:
        s = line.strip()
        if s.startswith("///") and not s.startswith("////"):
            text = s[3:]
            pending.append(text[1:] if text.startswith(" ") else text)
            continue
        if not s:                            # 空行：脱离待挂载的文档块
            pending = []
            continue
        m = DECL_RE.match(s)
        if m:
            out.append(Decl(m.group(1), m.group(2), _norm_signature(s),
                            _split_paragraphs(pending)))
        pending = []                         # 任何其它行都中断紧贴关系
    return out


def fn_counts(path):
    """(pub fn 数, 内部 fn 数)——供文档引言句统计，与 scan_file 同源。"""
    pub = internal = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not ANY_FN_RE.match(s):
                continue
            if s.startswith("pub fn "):
                pub += 1
            else:
                internal += 1
    return pub, internal


def iter_sources(paths):
    """路径参数 -> .qma 文件列表（目录递归），保持给定顺序。"""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for dp, _dn, fns in sorted(os.walk(p)):
                out.extend(os.path.join(dp, fn) for fn in sorted(fns)
                           if fn.endswith(".qma"))
        else:
            out.append(p)
    return out


def render(modules):
    """modules: [(显示路径, [Decl])] -> markdown 文本。"""
    parts = []
    for rel, decls in modules:
        parts.append(f"## `{rel}`\n")
        if not decls:
            parts.append("（无公开声明）\n")
            continue
        for d in decls:
            for para in d.doc:
                parts.append("\n".join(para))
                parts.append("")
            parts.append("```quelmara")
            parts.append(d.signature)
            parts.append("```")
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="Quelmara doc comment 生成器")
    ap.add_argument("paths", nargs="+", help=".qma 文件或目录")
    ap.add_argument("-o", "--out", help="输出 markdown（缺省打印 stdout）")
    ap.add_argument("--check", action="store_true",
                    help="配合 -o：只校验输出与文件一致，不写")
    args = ap.parse_args()

    modules = []
    for path in iter_sources(args.paths):
        if not os.path.isfile(path):
            raise SystemExit(f"qlm_doc: 文件不存在：{path}")
        modules.append((path.replace(os.sep, "/"), scan_file(path)))
    text = render(modules)

    if not args.out:
        sys.stdout.write(text)
        return 0
    if args.check:
        try:
            with open(args.out, encoding="utf-8") as f:
                cur = f.read()
        except OSError:
            print(f"FAIL：{args.out} 不存在")
            return 1
        if cur != text:
            print(f"FAIL：{args.out} 与源码 doc comment 不一致，"
                  f"请运行 qlm_doc.py 重新生成")
            return 1
        n = sum(len(d) for _r, d in modules)
        print(f"PASS：{len(modules)} 个模块 / {n} 个公开声明，文档与源码一致")
        return 0
    d = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(d, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    n = sum(len(d) for _r, d in modules)
    print(f"已生成 {args.out}：{len(modules)} 个模块 / {n} 个公开声明")
    return 0


if __name__ == "__main__":
    sys.exit(main())
