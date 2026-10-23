#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc comment 链路回归（v1.92）
============================
`///` 是语言层语法（`tools/stage0/qlm.py::scan_doc_comments`），
`quelmara doc` 是它的唯一消费方。本测试按"语法 → 前端 → 工具链 → 产物"四段验：

  1. 语法规则：紧贴才挂、空行脱离、`////` 不算、`@注解` 不断链、缩进不收、
     `//!` 只在文件头、`///` 后一个空格被剥
  2. 前端挂载：`parse_source(with_docs=True)` 给出 f["doc"] / type_docs / module_doc
  3. 工具链：Markdown / JSON / `--check` 漂移 / `--missing` 门禁 / fmt 保留
  4. 产物无关：带与不带 doc comment 的同一程序，PE 逐字节相同

跑法：python tests/doc_test.py
"""

import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
FIX = os.path.join(ROOT, "tests", "t119_doc.qma")
BUILD = os.path.join(ROOT, "build")
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm          # noqa: E402
import qlm_fmt      # noqa: E402

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def want(cond, msg, extra=""):
    ok(msg) if cond else bad(f"{msg}{('：' + extra) if extra else ''}")


def run(*args):
    """跑 quelmara 子命令，返回 (rc, stdout+stderr)。"""
    p = subprocess.run([sys.executable, CLI] + list(args), cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ---------------------------------------------------------------------------
# 1. 语法规则
# ---------------------------------------------------------------------------

def test_rules():
    src = (
        "//! 模块文档一\n"
        "//! 模块文档二\n"
        "\n"
        "/// 加法。\n"
        "///\n"
        "/// 第二段。\n"
        "pub fn add(a: int) -> int { return a }\n"
        "\n"
        "//// 四个斜杠 = 普通注释\n"
        "/// 结构体。\n"
        "@derive(Json)\n"
        "pub struct P { x: int }\n"
        "\n"
        "/// 缩进的不收\n"
        "fn inner() -> int {\n"
        "    /// 体内更不收\n"
        "    return 1\n"
        "}\n"
        "\n"
        "/// 空行脱离\n"
        "\n"
        "pub fn lost() -> int { return 0 }\n"
    )
    md, blocks, orphans = qlm.scan_doc_comments(src)
    want(md == ["模块文档一", "模块文档二"], "`//!` 只收文件头的连续块", str(md))

    names = {(b[1], b[2]): b[4] for b in blocks}
    want(("fn", "add") in names, "`///` 挂到紧贴的 pub fn")
    want(names.get(("fn", "add")) == ["加法。", "", "第二段。"],
         "`///` 独占一行 = 空串（段落分隔）", str(names.get(("fn", "add"))))
    want(("struct", "P") in names, "`///` 与声明之间允许 @注解（不断链）")
    want(("fn", "inner") in names, "缩进的 `///` 不收（普通注释）")
    want(("fn", "lost") not in names, "空行脱离后不再挂到声明上")
    want(len(orphans) == 1 and orphans[0][1].find("空行") >= 0,
         "脱离的块进 orphans（可被门禁抓）", str(orphans))

    _, b2, _ = qlm.scan_doc_comments("///x\npub fn f() -> int { return 0 }\n")
    want(b2[0][4] == ["x"], "`///x` 没有空格也能取到文本")
    _, b3, _ = qlm.scan_doc_comments("//// 不是文档\npub fn g() -> int { return 0 }\n")
    want(not b3, "`////` 不产生文档")

    late = "fn a() -> int { return 0 }\n//! 迟到的模块文档\n"
    _, _, o4 = qlm.scan_doc_comments(late)
    want(any("//!" in why for _, why in o4), "`//!` 出现在代码之后判为脱离")


# ---------------------------------------------------------------------------
# 2. 前端挂载
# ---------------------------------------------------------------------------

def test_ast():
    src = open(FIX, encoding="utf-8").read()
    mod, _imports, fns, _tests, _structs, _enums, _order, type_docs, module_doc = \
        qlm.parse_source(src, with_docs=True)
    docs = {f["name"]: f.get("doc") for f in fns}
    want(docs.get("add") is not None, "编译期 AST 上带 f[\"doc\"]（pub fn）")
    want(docs.get("answer") is not None, "非 pub 声明的 `///` 也挂到 AST（只是不进公开文档）")
    want(module_doc and module_doc[0].startswith("t119_doc"),
         "`//!` 模块文档进 Parser.module_doc", str(module_doc[:1]))
    want(type_docs.get("Pt") is not None, "struct 文档进 Parser.type_docs")

    plain = qlm.parse_source(src)
    want(len(plain) == 7, "不给 with_docs 时返回结构不变（7 元组，兼容旧调用）")
    want(all("doc" in f for f in plain[2] if f["name"] == "add"),
         "doc 仍挂在 fns 上（编译路径也能读到）")


# ---------------------------------------------------------------------------
# 3. 工具链
# ---------------------------------------------------------------------------

def test_cli():
    rc, out = run("doc", "tests/t119_doc.qma")
    want(rc == 0, "quelmara doc 退出码 0")
    want("### `add`" in out, "Markdown 有声明小节标题")
    want("pub struct Pt" not in out and "struct Pt" in out,
         "struct 块剥掉 pub 前缀、保留字段")
    want("### `answer`" not in out, "非 pub 声明不进公开文档")
    want("t119_doc —— doc comment 语法夹具" in out, "`//!` 模块文档渲染在模块标题下")

    rc, out = run("doc", "tests/t119_doc.qma", "--format", "json")
    try:
        data = json.loads(out)
        decls = data["modules"][0]["decls"]
        names = {d["name"] for d in decls}
        good = (data["version"] == 1 and "add" in names and "answer" not in names
                and all(d["signature"].startswith(("fn ", "struct ", "enum "))
                        for d in decls))
    except Exception as exc:                     # noqa: BLE001
        good, data = False, str(exc)
    want(good, "`--format json` 可解析且字段齐全", str(data)[:120])

    out_md = os.path.join(BUILD, "doc_t119.md")
    rc, _ = run("doc", "tests/t119_doc.qma", "-o", out_md)
    want(rc == 0 and os.path.isfile(out_md), "`-o` 写文件")
    rc, msg = run("doc", "tests/t119_doc.qma", "-o", out_md, "--check")
    want(rc == 0, "`--check` 与刚生成的文件一致")

    with open(out_md, "a", encoding="utf-8") as f:
        f.write("\n手改一行\n")
    rc, msg = run("doc", "tests/t119_doc.qma", "-o", out_md, "--check")
    want(rc == 1, "`--check` 能抓到漂移（退出码 1）")

    rc, msg = run("doc", "tests/t119_doc.qma", "--missing")
    want(rc == 0 and "PASS" in msg, "`--missing` 全有文档时 PASS")

    miss = os.path.join(BUILD, "doc_missing.qma")
    with open(miss, "w", encoding="utf-8") as f:
        f.write("pub fn no_doc(a: int) -> int { return a }\n")
    rc, msg = run("doc", miss, "--missing")
    want(rc == 1 and "no_doc" in msg, "`--missing` 缺文档时退出码 1 并点名")

    rc, msg = run("doc", "std", "--missing")
    want(rc == 0, "std/ 全库公开声明都有 doc comment（门禁口径）", msg.strip()[-80:])

    src = open(FIX, encoding="utf-8").read()
    fmt = qlm_fmt.format_src(src)
    want(fmt.count("///") == src.count("///"), "`quelmara fmt` 原样保留 `///`")
    want(qlm_fmt.format_src(fmt) == fmt, "fmt 幂等（带 doc comment 的源码）")


# ---------------------------------------------------------------------------
# 4. 产物无关
# ---------------------------------------------------------------------------

def test_binary():
    body = ('fn helper(a: int) -> int {\n    return a * 3\n}\n'
            'pub fn main() -> int {\n    return helper(14)\n}\n')
    doc = ('/// 乘三。\nfn helper(a: int) -> int {\n    return a * 3\n}\n'
           '/// 入口。\npub fn main() -> int {\n    return helper(14)\n}\n')
    outs = []
    for tag, text in (("nodoc", body), ("withdoc", doc)):
        src = os.path.join(BUILD, f"doc_{tag}.qma")
        exe = os.path.join(BUILD, f"doc_{tag}.exe")
        with open(src, "w", encoding="utf-8") as f:
            f.write(text)
        rc, msg = run("build", src, "--target", "win", "-o", exe)
        if rc != 0:
            bad(f"构建 {tag} 失败：{msg.strip()[-120:]}")
            return
        outs.append(hashlib.sha256(open(exe, "rb").read()).hexdigest())
    want(outs[0] == outs[1], "doc comment 不改变产物（PE 逐字节相同）",
         f"{outs[0][:12]} vs {outs[1][:12]}")


def main():
    print("doc comment 链路（v1.92）")
    test_rules()
    test_ast()
    test_cli()
    test_binary()
    print(f"\nPASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
