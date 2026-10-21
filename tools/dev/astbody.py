#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage-1 parser 对拍：函数体 S 表达式（Phase 1 核心子集）。

协议（两侧必须逐字节一致）：
  行格式   fn <name>#<i> <sexpr>     —— 第 i 条顶层语句
           fn <name> SKIP            —— 函数体含未支持形态（Phase 2）
  表达式   (num N) (fnum <hex-of-repr>) (bool 0|1) (str <hex-of-utf8>)
           (name x) (path a.b.c) (field <E> .n)
           (binop <op> <L> <R>) (unop <op> <X>)
           (call <dotted> <A>...) (method <recv> <name> <A>...)
           (index <B> <I>) (sliceof <B> <LO> <HI>)
           (arr <E>...) (slit <T> <f> <E>...) (enumlit T.V <A>...) (vec <T> <A>...)
  语句     (let mut|imm <n> <E>) (assign <n> <op> <E>) (assignf <path> <op> <E>)
           (assigni <B> <I> <op> <E>)
           (if <C> <S>... | <S>...)          —— 无 else 则无尾随 |
           (while <C> <S>...) (for <v> <LO> <HI> <S>...) (foreach <v> <C> <S>...)
           (do <E>) (ret <E>) / (ret) (continue) (break)

Phase 1 未支持（整函数 SKIP）：match/match_stmt/arena/parfor/spawn/select/
try/chanopen/map/mapnew/error/value/named 之外的扩展形态与 test 块。
stage-1 侧（bootstrap/parser/qlm_parse.qma）按同一协议输出，diff 即对拍。
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "tools", "stage0"))
import qlm  # noqa: E402

SUPPORTED_EXPR = {"num", "fnum", "bool", "str", "name", "path", "field",
                  "binop", "unop", "call", "index", "sliceof", "arraylit",
                  "structlit", "method", "enumlit", "vecnew", "try"}
SUPPORTED_STMT = {"let", "assign", "assign_field", "assign_index", "if",
                  "while", "for", "foreach", "expr", "return", "continue",
                  "break"}


class Unsupported(Exception):
    pass


def hexs(s: str) -> str:
    return s.encode("utf-8").hex()


def dump_expr(e) -> str:
    if not isinstance(e, tuple) or not e or e[0] not in SUPPORTED_EXPR:
        raise Unsupported(str(e)[:60])
    k = e[0]
    if k == "num":
        return f"(num {e[1]})"
    if k == "fnum":
        return f"(fnum {repr(e[1]).encode('ascii').hex()})"
    if k == "bool":
        return f"(bool {1 if e[1] else 0})"
    if k == "str":
        return f"(str {hexs(e[1])})"
    if k == "name":
        return f"(name {e[1]})"
    if k == "path":
        return f"(path {'.'.join(e[1])})"
    if k == "field":
        return f"(field {dump_expr(e[1])} .{e[2]})"
    if k == "binop":
        return f"(binop {e[1]} {dump_expr(e[2])} {dump_expr(e[3])})"
    if k == "unop":
        return f"(unop {e[1]} {dump_expr(e[2])})"
    if k == "call":
        args = " ".join(dump_expr(a) for a in e[2])
        return f"(call {'.'.join(e[1])}{(' ' + args) if args else ''})"
    if k == "method":
        args = " ".join(dump_expr(a) for a in e[3])
        return f"(method {dump_expr(e[1])} {e[2]}{(' ' + args) if args else ''})"
    if k == "index":
        return f"(index {dump_expr(e[1])} {dump_expr(e[2])})"
    if k == "sliceof":
        return f"(sliceof {dump_expr(e[1])} {dump_expr(e[2])} {dump_expr(e[3])})"
    if k == "arraylit":
        items = " ".join(dump_expr(a) for a in e[1])
        return f"(arr{(' ' + items) if items else ''})"
    if k == "structlit":
        parts = [e[1][0]]
        for fname, fe in e[2].items():
            parts += [fname, dump_expr(fe)]
        return "(slit " + " ".join(parts) + ")"
    if k == "enumlit":
        args = " ".join(dump_expr(a) for a in e[2])
        return f"(enumlit {'.'.join(e[1])}{(' ' + args) if args else ''})"
    if k == "try":
        return f"(try {dump_expr(e[1])})"
    if k == "vecnew":
        ty = e[1][1] if isinstance(e[1], tuple) and len(e[1]) > 1 else "?"
        args = " ".join(dump_expr(a) for a in e[2])
        return f"(vec {ty}{(' ' + args) if args else ''})"
    raise Unsupported(k)


def dump_stmt(s) -> str:
    if not isinstance(s, tuple) or not s or s[0] not in SUPPORTED_STMT:
        raise Unsupported(str(s)[:60])
    k = s[0]
    if k == "let":
        return f"(let {'mut' if s[1] else 'imm'} {s[2]} {dump_expr(s[3])})"
    if k == "assign":
        return f"(assign {s[1]} {s[2]} {dump_expr(s[3])})"
    if k == "assign_field":
        return (f"(assignf {'.'.join(s[1][1])} {s[2]} "
                f"{dump_expr(s[3])})")
    if k == "assign_index":
        return (f"(assigni {dump_expr(s[1])} {dump_expr(s[2])} "
                f"{s[3]} {dump_expr(s[4])})")
    if k == "if":
        then = " ".join(dump_stmt(t) for t in s[2])
        tail = ""
        if s[3] is not None:
            els = " ".join(dump_stmt(t) for t in s[3])
            tail = f" | {els}" if els else " |"
        return f"(if {dump_expr(s[1])}{(' ' + then) if then else ''}{tail})"
    if k == "while":
        body = " ".join(dump_stmt(t) for t in s[2])
        return f"(while {dump_expr(s[1])}{(' ' + body) if body else ''})"
    if k == "for":
        body = " ".join(dump_stmt(t) for t in s[4])
        return (f"(for {s[1]} {dump_expr(s[2])} {dump_expr(s[3])}"
                f"{(' ' + body) if body else ''})")
    if k == "foreach":
        body = " ".join(dump_stmt(t) for t in s[3])
        return f"(foreach {s[1]} {dump_expr(s[2])}{(' ' + body) if body else ''})"
    if k == "expr":
        return f"(do {dump_expr(s[1])})"
    if k == "return":
        return "(ret)" if len(s) < 2 or s[1] is None else f"(ret {dump_expr(s[1])})"
    if k == "continue":
        return "(continue)"
    if k == "break":
        return "(break)"
    raise Unsupported(k)


def dump_fn(f) -> list:
    """返回该函数的协议行列表；含未支持形态则单行 SKIP。"""
    try:
        lines = []
        for i, s in enumerate(f["body"]):
            lines.append(f"fn {f['name']}#{i} {dump_stmt(s)}")
        return lines
    except Unsupported:
        return [f"fn {f['name']} SKIP"]
    except Exception:                          # Phase 1 未覆盖（含 extern 声明）
        return [f"fn {f['name']} SKIP"]


def main():
    paths = sys.argv[1:] or sorted(
        glob.glob("tests/*.qma") + glob.glob("examples/*.qma"))
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                _, _, fns, _tests, _, _, _ = qlm.parse_source(fh.read())
        except Exception as e:
            print(f"{path} PARSE_SKIP {type(e).__name__}")
            continue
        for f in fns:
            for line in dump_fn(f):
                print(f"{path} {line}")


if __name__ == "__main__":
    main()
