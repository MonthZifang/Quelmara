#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""声明级 AST 对拍协议（stage-0 侧 oracle）。

只覆盖**顶层声明**（module / import / struct / enum / fn 签名），不含函数体。
理由：函数体 AST 的形状在 stage-0 里是 Python 元组，逐节点对拍会把
"实现细节"当成契约；而"声明层"是可稳定定义的接口，正好作为 parser 的第一段。

协议：一行一条，`|` 分隔
    module|<name>
    import|<dotted.path>
    struct|<Name>|<f1:type,f2:type,...>
    enum|<Name>|<V1:0,V2:1,...>          # 变体名:载荷个数
    fn|<name>|(<t1,t2>)|<ret>
参数只写类型不写名字（名字属于实现细节）。

类型渲染是唯一权威：stage-1 必须产出完全相同的字符串。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

from qlm import parse_source  # noqa: E402


def render_type(t):
    """类型元组 -> 规范文本。两侧必须一致。"""
    if not t:
        return "?"
    k = t[0]
    if k == "named":
        n = t[1]
        # 前端把 option[T] / result[T,E] 合成为枚举名，这里还原成源码写法
        if n.startswith("__opt_"):
            return "option[" + n[len("__opt_"):] + "]"
        if n.startswith("__res_"):
            inner = n[len("__res_"):]
            # __res_<T>_<E>：按下划线切分不可靠，交给 stage-1 一致处理
            return "result[" + inner.replace("_", ",") + "]"
        return n
    if k == "slice":
        return "[]" + render_type(t[1])
    if k == "array":
        return "[" + str(t[1]) + "]" + render_type(t[2])
    if k == "map":
        return "map[" + render_type(t[1]) + "]" + render_type(t[2])
    if k == "vec":
        return "vec[" + render_type(t[1]) + "]"
    if k == "rc":
        return "rc[" + render_type(t[1]) + "]"
    if k == "chan":
        return "chan[" + render_type(t[1]) + "]"
    return "?"


def dump(src):
    mod, imports, fns, _tests, structs, enums, order = parse_source(src)
    out = []
    if mod:
        out.append("module|" + mod)
    for imp in imports:
        out.append("import|" + imp)
    for kind, name in order:
        # __opt_* / __res_* 是前端为 option/result 合成的枚举，不是源码声明
        if name.startswith("__opt_") or name.startswith("__res_"):
            continue
        if kind == "struct":
            fields = ",".join(f"{f}:{render_type(t)}" for f, t in structs.get(name) or [])
            out.append(f"struct|{name}|{fields}")
        else:
            vs = enums.get(name) or []
            body = ",".join(f"{vn}:{len(fs or [])}" for vn, fs in vs)
            out.append(f"enum|{name}|{body}")
    for f in fns:
        params = ",".join(render_type(p[1]) for p in f["params"])
        out.append(f"fn|{f['name']}|({params})|{render_type(f['ret'])}")
    return "".join(line + "\n" for line in out)


if __name__ == "__main__":
    for path in sys.argv[1:]:
        sys.stdout.buffer.write(dump(open(path, encoding="utf-8").read()).encode("utf-8"))
