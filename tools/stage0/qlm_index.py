#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Quelmara 语义索引（`quelmara lsp` 的数据源）
==========================================
本模块是工具链里**唯一的索引实现**：编辑器（LSP）与命令行诊断都读它，
不再各自维护一套"这个文件里有什么名字"的逻辑。

## 为什么不用编译器前端（`qlm.Parser`）

`qlm.Parser` 要求源码**语法完整**：一个字符打错就抛 `SyntaxError`，
整个文件的符号全部消失——而编辑器里正在编辑的文件**永远**是半成品
（光标停在 `fn foo(` 上时也要求补全）。所以索引器是**容错**的：
只认词法 + 结构（括号配对、声明关键字），不认语义。实测证据：
`std/timer.qma` 用了顶层 `let`、`std/http.qma` 拿 `rc` 当变量名，
两者当前都过不了 `qlm.Parser`（见 `tests/lsp_test.py` 的 `tolerant` 段），
但索引器照常给出符号表。

## 为什么自己写词法（`scan`）

`qlm.tokenize` 的 `Tok` 只有 `kind/val/line`，**没有列号**，而 LSP 的每个
请求/响应都以 (行, 列) 定位。另写一份会漂移，所以：

- `scan()` 与 `qlm.tokenize` 逐条同构（同 `KEYWORDS`/`SYMBOLS`、同数字与
  字符串转义规则、同 `\xNN` 单字节语义），只是多记了 `off`/`end` 偏移；
- `tests/lsp_test.py` 用**全仓库 .qma 对拍**钉住二者一致（`kind` 与 `val`
  逐条相等），编译器词法一改，测试立刻红——这是防漂移的硬约束，不是注释。

## 索引里有什么

| 层 | 内容 | 用途 |
|---|---|---|
| 顶层 | `module` / `import` / `fn` / `const` / `struct` / `enum` / `interface` / `impl` 方法 / `test` / 顶层 `let` | 补全、大纲、workspace/symbol |
| 成员 | struct 字段、enum 变体与载荷字段、interface 方法与 `impl` 方法 | `x.` 之后的补全、`Enum.Variant` 跳转 |
| 局部 | 形参、`let`、`for`/`parfor` 变量、`match` 臂绑定（按花括号分块） | 作用域内的补全/重命名 |
| 引用 | 每个 `NAME` 记号的解析结果（本地符号 / 跨文件符号 / 内建 / 未解析） | 跳转、引用、重命名、高亮 |

## 边界（做不到的写在这里，不粉饰）

- **不做类型检查**：索引不带类型系统，`.member` 的类型来自形参标注、
  `let` 标注、struct 字面量/枚举构造/`fn()` 返回值的**语法推断**，
  推不出来就是"未知"——此时 `.` 补全退化为"本文件所有成员名"，不猜。
- **作用域按花括号近似**：`match` 臂绑定、`for` 变量落在最近一层块里；
  同名遮蔽按"最内层块优先"处理，够用于补全与重命名，不等价于编译器的
  精确活跃区间。
- **泛型按源码写法归属**：`impl Box[T] : Show` 的方法登记在 `Box`（剥掉
  实参），`impl Box[int] : Show` 登记在 `Box[int]`；查成员时先精确再剥离，
  所以两者都能命中，但**不区分子类型实参**。
- **不索引 `std/` 之外没打开的文件**：`references`/`rename` 要跨文件时
  会先按需索引工作区（`Workspace.ensure_all`），耗时见 `06-status.md`。
- **诊断只到词法/结构层**：非法字符、未闭合字符串、括号不配对、顶层重名。
  类型错误、未定义函数不报（那需要完整前端，见 `07-gaps.md` §3）。

用法（命令行，便于脚本与测试直接查，不必起 LSP）：

```bash
python tools/stage0/qlm_index.py tests/t101_bounds.qma            # 统计 + 符号表
python tools/stage0/qlm_index.py tests/t101_bounds.qma --json     # 机器可读
python tools/stage0/qlm_index.py file.qma --at 30:8               # 该位置的解析结果
```
"""

import bisect
import json
import os
import re
import sys
import time
from urllib.parse import quote, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qlm import (KEYWORDS, SYMBOLS, SRC_EXT,  # noqa: E402
                 _import_candidates, _qpm_candidates, load_config)

# ---------------------------------------------------------------------------
# 0. 常量表
# ---------------------------------------------------------------------------

# LSP SymbolKind
SYMBOL_KIND = {
    "module": 2, "import": 2, "fn": 12, "method": 6, "struct": 23, "enum": 10,
    "variant": 22, "field": 8, "const": 14, "iface": 11, "param": 13,
    "local": 13, "global": 13, "test": 12, "type_param": 26,
}

# LSP CompletionItemKind
COMPLETION_KIND = {
    "fn": 3, "method": 2, "struct": 22, "enum": 13, "variant": 20, "field": 5,
    "const": 21, "iface": 8, "param": 6, "local": 6, "global": 6,
    "module": 9, "import": 9, "test": 3, "type_param": 25,
}

# 编译器内建（`qlm_native.py` 里 `name == "..."` 的顶层分派表 + 内建方法）。
# 这些不是符号表里的声明，所以只做补全/悬停，跳转与重命名明确拒绝。
BUILTIN_FNS = {
    "print": "void", "eprint": "void", "assert": "void", "len": "int",
    "cores": "int", "join": "str", "exit": "void", "arg": "str",
    "now_ns": "int", "now_cycle": "int", "wall_ms": "int", "sleep_ms": "void",
    "mem_alloc": "int", "mem_free": "void", "mem_copy": "void",
    "mem_zero": "void", "mem_cmp": "int", "mem_chr": "int", "mem_diff": "int",
    "mem_load8": "int", "mem_load32": "int", "mem_store8": "void",
    "mem_xchg": "int", "mem_str": "str", "mem_ptr": "int",
    "str_alloc": "str", "str_from_bytes": "str", "str_from_mem": "str",
    "substr": "str", "slice_of": "[]T", "read_text": "str",
    "write_text": "void", "read_asset": "str", "file_exists": "bool",
    "fs_mkdir": "void", "fs_remove": "void",
    "to_int": "int", "to_float": "f64", "to_f32": "f32", "chr": "str",
    "rc_new": "rc[T]", "rc_get": "T", "rc_clone": "rc[T]", "rc_count": "int",
    "atomic_add": "int", "atomic_cas": "bool", "atomic_fence": "void",
    "spin_hint": "void", "static_word": "int",
    "tcp_connect": "int", "tcp_send_n": "int", "tcp_recv": "str",
    "udp_open": "int", "udp_recvfrom": "str",
    "net_serve": "void", "xmm_load": "int", "xmm_store": "void",
    "cpu_aes": "bool", "cpu_sha": "bool", "cpu_pclmul": "bool",
    "pclmulqdq": "int", "cast": "T",
}

BUILTIN_TYPES = {"int", "i64", "i32", "i16", "i8", "u64", "u32", "u16", "u8",
                 "bool", "str", "float", "f64", "f32", "byte", "void"}

# 能力约束名（`[T: Ord + Num]`）：编译期内建，不是用户声明
BUILTIN_CAPS = {"Ord", "Eq", "Num", "Bit", "Show"}

# 内建方法（`lower_vec_method` / `lower_map_method` / 标量方法分派）
BUILTIN_METHODS = {
    "str": ["to_str", "to_int", "to_float", "len", "substr", "slice"],
    "vec": ["push", "pop", "get", "set", "len", "clear"],
    "map": ["get", "set", "has", "del", "len", "clear"],
    "chan": ["send", "recv", "close"],
    "any": ["to_str", "len"],
}

_ALL_BUILTIN_METHODS = {m for ms in BUILTIN_METHODS.values() for m in ms}


def _builtin_methods_for(ty):
    """按类型名挑内建方法族：vec[int] -> vec，map[str]Row -> map。

    具名聚合（struct/enum）**不**给 `any` 族：`Point.to_str()` 不是合法调用
    （聚合的 to_str 会打印指针，见 `07-gaps.md` §7.6 的同类问题），
    补全里给出会误导。
    """
    if not ty:
        return []
    if ty in BUILTIN_TYPES or ty in ("f64", "f32", "float"):
        return BUILTIN_METHODS["str"] if ty == "str" else BUILTIN_METHODS["any"]
    for head in ("vec", "map", "chan"):
        if ty == head or ty.startswith(head + "["):
            return BUILTIN_METHODS[head]
    return []


# ---------------------------------------------------------------------------
# 1. 位置感知词法（与 qlm.tokenize 同构，多记偏移）
# ---------------------------------------------------------------------------


class Tok:
    __slots__ = ("kind", "val", "off", "end")

    def __init__(self, kind, val, off, end):
        self.kind, self.val, self.off, self.end = kind, val, off, end

    def __repr__(self):
        return f"Tok({self.kind},{self.val!r},{self.off}-{self.end})"


def _line_of(src, off):
    return src.count("\n", 0, off) + 1


_STR_ESC = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "a": "\a", "b": "\b",
            "f": "\f", "v": "\v", '"': '"', "\\": "\\", "'": "'"}

# 按首字符分桶：符号匹配从"每条 50 个 startswith"降到"每条 1–4 个"。
# 索引是每次编辑都要跑的，词法这一层的常数直接决定补全延迟。
SYM_BY_FIRST = {}
for _s in SYMBOLS:
    SYM_BY_FIRST.setdefault(_s[0], []).append(_s)

_DIGITS = frozenset("0123456789")


def scan(src, keep_comments=False):
    """词法分析，返回带绝对偏移的记号表（不含 NL）。

    与 `qlm.tokenize` 逐条同构：`kind`/`val` 必须完全一致（`tests/lsp_test.py`
    全仓库对拍）。差别只有两点：① 记 `off`/`end`；② 空行/空白不产生记号。
    """
    toks = []
    ap = toks.append
    i, n = 0, len(src)
    sw = src.startswith            # 绑一次：每个记号省一次属性查找
    digits = _DIGITS
    while i < n:
        c = src[i]
        fstr = False
        if c == "f" and i + 1 < n and src[i + 1] == '"':
            fstr = True
            i += 1
            c = src[i]
        if c == "\n":
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if sw("//", i):
            j = i
            while j < n and src[j] != "\n":
                j += 1
            if keep_comments:
                ap(Tok("COMMENT", src[i:j], i, j))
            i = j
            continue
        if sw("/*", i):
            j = i + 2
            while j < n and not sw("*/", j):
                j += 1
            end = min(j + 2, n)
            if keep_comments:
                ap(Tok("COMMENT", src[i:end], i, end))
            i = end
            continue
        if c in digits and i + 1 < n and c == "0" and src[i + 1] in "xXbBoO":
            base = {"x": 16, "b": 2, "o": 8}[src[i + 1].lower()]
            ok = "0123456789abcdefABCDEF" if base == 16 else (
                "01" if base == 2 else "01234567")
            j = i + 2
            while j < n and (src[j] in ok or src[j] == "_"):
                j += 1
            if j == i + 2:
                raise SyntaxError(
                    f"line {_line_of(src, i)}: {src[i:i + 2]} 后面缺少数字")
            ap(Tok("INT", int(src[i + 2:j].replace("_", ""), base), i, j))
            i = j
            continue
        if c in digits:
            j = i
            while j < n and (src[j] in digits or src[j] == "_"):
                j += 1
            is_float = False
            if j + 1 < n and src[j] == "." and src[j + 1] in digits:
                is_float = True
                j += 1
                while j < n and (src[j] in digits or src[j] == "_"):
                    j += 1
            if j < n and src[j] in "eE":
                k2 = j + 1
                if k2 < n and src[k2] in "+-":
                    k2 += 1
                if k2 < n and src[k2] in digits:
                    is_float = True
                    j = k2
                    while j < n and (src[j] in digits or src[j] == "_"):
                        j += 1
            text = src[i:j].replace("_", "")
            if is_float:
                width = "f64"
                if j < n and src[j] == "f" and not (
                        j + 1 < n and (src[j + 1].isalnum() or src[j + 1] == "_")):
                    width = "f32"
                    j += 1
                ap(Tok("FLOAT", (float(text), width), i, j))
            else:
                ap(Tok("INT", int(text), i, j))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            ap(Tok(word if word in KEYWORDS else "NAME", word, i, j))
            i = j
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    esc = src[j + 1]
                    if esc == "x" and j + 3 < n:
                        try:
                            b = int(src[j + 2:j + 4], 16)
                            # 与 qlm.tokenize 一致：\xNN 是原始字节，
                            # 非 ASCII 走 surrogateescape 区承载
                            buf.append(chr(b) if b < 0x80 else chr(0xDC00 + b))
                            j += 4
                            continue
                        except ValueError:
                            pass
                    buf.append(_STR_ESC.get(esc, esc))
                    j += 2
                else:
                    buf.append(src[j])
                    j += 1
            if j >= n:
                raise SyntaxError(f"line {_line_of(src, i)}: 字符串未闭合")
            ap(Tok("FSTR" if fstr else "STR", "".join(buf), i, j + 1))
            i = j + 1
            continue
        for sym in SYM_BY_FIRST.get(c, ()):
            if src.startswith(sym, i):
                ap(Tok("SYM", sym, i, i + len(sym)))
                i += len(sym)
                break
        else:
            raise SyntaxError(f"line {_line_of(src, i)}: 非法字符 {c!r}")
    ap(Tok("EOF", None, n, n))
    return toks


class LineMap:
    """偏移 <-> (行, 列) 双向换算，列口径是 **UTF-16 code unit**（LSP 默认）。"""

    __slots__ = ("src", "starts")

    def __init__(self, src):
        self.src = src
        st, pos = [0], src.find("\n")
        while pos >= 0:
            st.append(pos + 1)
            pos = src.find("\n", pos + 1)
        self.starts = st

    def pos(self, off):
        line = bisect.bisect_right(self.starts, off) - 1
        return line, off - self.starts[line]

    def off(self, line, col):
        if line < 0:
            return 0
        if line >= len(self.starts):
            return len(self.src)
        return min(self.starts[line] + col, len(self.src))

    def line_text(self, line):
        if line < 0 or line >= len(self.starts):
            return ""
        s = self.starts[line]
        e = (self.starts[line + 1] - 1 if line + 1 < len(self.starts)
             else len(self.src))
        return self.src[s:e]

    def to_utf16(self, line, col):
        """列（码点） -> 列（UTF-16 单元）。BMP 之外一个字符算 2。"""
        acc = 0
        for ch in self.line_text(line)[:col]:
            acc += 2 if ord(ch) > 0xFFFF else 1
        return acc

    def from_utf16(self, line, u):
        col, acc = 0, 0
        for ch in self.line_text(line):
            if acc >= u:
                break
            acc += 2 if ord(ch) > 0xFFFF else 1
            col += 1
        return col


# ---------------------------------------------------------------------------
# 2. 符号 / 引用
# ---------------------------------------------------------------------------


class Sym:
    __slots__ = ("sid", "name", "kind", "container", "ty", "detail", "pub",
                 "off", "end", "path", "doc", "line", "col")

    def __init__(self, sid, name, kind, container, ty, detail, pub, off, end,
                 path):
        self.sid, self.name, self.kind = sid, name, kind
        self.container, self.ty, self.detail = container, ty, detail
        self.pub, self.off, self.end, self.path = pub, off, end, path
        self.doc, self.line, self.col = None, 0, 0

    def __repr__(self):
        return f"Sym({self.kind} {self.name} @{self.off})"


class Ref:
    """一次名字解析的结果。`kind` 取值：local / ext / builtin。"""

    __slots__ = ("kind", "sid", "path", "name", "symkind", "off")

    def __init__(self, kind, sid=None, path=None, name=None, symkind=None,
                 off=None):
        self.kind, self.sid, self.path = kind, sid, path
        self.name, self.symkind, self.off = name, symkind, off

    def __repr__(self):
        return (f"Ref({self.kind},{self.sid},{self.name}"
                f"{'@' + os.path.basename(self.path) if self.path else ''})")


class Occ:
    __slots__ = ("off", "end", "name", "ref")

    def __init__(self, off, end, name, ref):
        self.off, self.end, self.name, self.ref = off, end, name, ref


def _strip_args(ty):
    """`Box[int]` -> `Box`；`map[str]Row` 原样（map 是内建族，不剥）。"""
    if not ty:
        return ty
    for head in ("vec", "map", "chan", "rc", "option", "result"):
        if ty == head or ty.startswith(head + "["):
            return ty
    i = ty.find("[")
    return ty[:i] if i > 0 else ty


# ---------------------------------------------------------------------------
# 3. 单文件索引
# ---------------------------------------------------------------------------


class Index:
    """一个文件的符号表 + 引用表。构造即完成，之后只读。"""

    def __init__(self, path, src, ws=None):
        self.path = os.path.normpath(os.path.abspath(path)) if path else "<mem>"
        self.src = src
        self.ws = ws
        self.lm = LineMap(src)
        self.toks = []
        self.tok_offs = []
        self.syms = []
        self.top = {}
        self.members = {}
        self.modules = {}
        self.occs = []
        self.scopes = []
        self.imports = {}
        self.import_alias = {}
        self.decl_off = {}
        self.type_params = {}
        self.tparam_scopes = []
        self.field_by_name = {}
        self.pairs = {}
        self.unmatched = []
        self.dups = []
        self.scan_error = None
        self.build_ms = 0.0
        # 跨文件解析缓存（一次索引内反复查 import 太贵：每次都要 stat 多个候选路径）
        self._imported_cache = None
        self._ext_map = None
        t0 = time.perf_counter()
        try:
            self.toks = scan(src, keep_comments=True)
        except SyntaxError as e:
            self.scan_error = str(e)
            self.toks = [Tok("EOF", None, len(src), len(src))]
        self.tok_offs = [t.off for t in self.toks]
        self._pair_brackets()
        self._build()
        self._index_scopes()
        self._resolve_all()
        self._finish_positions()
        self.build_ms = (time.perf_counter() - t0) * 1000.0

    # ---- 基础设施 ----

    def _pair_brackets(self):
        stack = []
        opens = {"(": ")", "[": "]", "{": "}"}
        for i, t in enumerate(self.toks):
            if t.kind != "SYM":
                continue
            v = t.val
            if v in opens:
                stack.append((i, v))
            elif v in (")", "]", "}"):
                if stack and opens[stack[-1][1]] == v:
                    j, _ = stack.pop()
                    self.pairs[i] = j
                    self.pairs[j] = i
                else:
                    self.unmatched.append((t, "多余的 " + v))
        for i, v in stack:
            self.unmatched.append((self.toks[i], f"{v} 未闭合"))

    def _tok(self, i):
        if 0 <= i < len(self.toks):
            return self.toks[i]
        return self.toks[-1]

    def _val(self, i):
        return self._tok(i).val

    def _add_sym(self, tok, kind, container, detail=None, ty=None, pub=False,
                 end=None):
        s = Sym(len(self.syms), tok.val, kind, container, ty, detail or tok.val,
                pub, tok.off, end if end is not None else tok.end, self.path)
        self.syms.append(s)
        if container is None:
            if kind in ("module", "import"):
                self.modules[tok.val] = s
            elif tok.val in self.top:
                self.dups.append((tok, self.top[tok.val]))
                # 保留先声明的那个（与编译器"重名报错"一致，索引不抛）
            else:
                self.top[tok.val] = s
        else:
            self.members.setdefault((container, tok.val), s)
        if kind == "type_param":
            self.type_params.setdefault(tok.val, s)
        if kind == "field":
            self.field_by_name.setdefault(tok.val, []).append(s)
        self.decl_off[tok.off] = s.sid
        return s

    def _doc_above(self, off):
        """声明上方紧邻的 `//` 注释行（连续、且该行只有注释）。"""
        line, _ = self.lm.pos(off)
        out = []
        while line > 0:
            prev = line - 1
            seg = self.lm.line_text(prev).strip()
            if seg.startswith("//"):
                out.append(seg)
                line = prev
                continue
            break
        out.reverse()
        return "\n".join(out)

    def _parse_type(self, i):
        """读一个类型，返回 (类型串, 下一个位置)。类型串无空格：`map[str]Row`。"""
        t = self._tok(i)
        if t.kind == "SYM" and t.val == "[":
            if self._val(i + 1) == "]":
                inner, j = self._parse_type(i + 2)
                return "[]" + inner, j
            j, n = i + 1, ""
            while self._tok(j).kind == "INT":
                n += str(self._tok(j).val)
                j += 1
            if self._val(j) == "]":
                j += 1
            inner, j = self._parse_type(j)
            return f"[{n}]{inner}", j
        if t.kind in ("chan", "vec", "rc", "option"):
            kw = t.kind
            if self._val(i + 1) == "[":
                inner, j = self._parse_type(i + 2)
                if self._val(j) == "]":
                    j += 1
                return f"{kw}[{inner}]", j
            return kw, i + 1
        if t.kind == "map":
            if self._val(i + 1) == "[":
                k, j = self._parse_type(i + 2)
                if self._val(j) == "]":
                    j += 1
                v, j = self._parse_type(j)
                return f"map[{k}]{v}", j
            return "map", i + 1
        if t.kind == "result":
            if self._val(i + 1) == "[":
                a, j = self._parse_type(i + 2)
                if self._val(j) == ",":
                    j += 1
                b, j = self._parse_type(j)
                if self._val(j) == "]":
                    j += 1
                return f"result[{a},{b}]", j
            return "result", i + 1
        if t.kind == "NAME":
            name, j = t.val, i + 1
            if self._val(j) == "[":
                args, j = [], j + 1
                while j < len(self.toks) and self._val(j) != "]":
                    a, j = self._parse_type(j)
                    args.append(a)
                    if self._val(j) == ",":
                        j += 1
                if self._val(j) == "]":
                    j += 1
                return f"{name}[{', '.join(args)}]", j
            return name, j
        return "?", i + 1

    # ---- 结构扫描 ----

    def _build(self):
        i, n = 0, len(self.toks)
        pub = False
        while i < n:
            t = self.toks[i]
            if t.kind == "EOF":
                break
            if t.kind == "NAME" and t.val == "pub":
                pub = True
                i += 1
                continue
            if t.kind == "SYM" and t.val == "@":
                i = self._skip_annot(i)
                continue
            if t.kind == "module":
                if self._tok(i + 1).kind == "NAME":
                    self._add_sym(self.toks[i + 1], "module", None,
                                  detail="module " + self.toks[i + 1].val)
                i += 2
                continue
            if t.kind == "import":
                i = self._decl_import(i)
                continue
            if t.kind == "const":
                i = self._decl_const(i, pub)
                pub = False
                continue
            if t.kind == "fn":
                i = self._decl_fn(i, None, pub)
                pub = False
                continue
            if t.kind == "struct":
                i = self._decl_struct(i, pub)
                pub = False
                continue
            if t.kind == "enum":
                i = self._decl_enum(i, pub)
                pub = False
                continue
            if t.kind == "interface":
                i = self._decl_iface(i, pub)
                pub = False
                continue
            if t.kind == "impl":
                i = self._decl_impl(i)
                pub = False
                continue
            if t.kind == "test":
                i = self._decl_test(i)
                continue
            if t.kind == "let":
                i = self._decl_global_let(i)
                continue
            i += 1

    def _skip_annot(self, i):
        """跳过 `@name` / `@name("arg")`。"""
        j = i + 1
        if self._tok(j).kind == "NAME":
            j += 1
        if self._val(j) == "(":
            j = self.pairs.get(j, j) + 1
        return j

    def _decl_import(self, i):
        j, parts = i + 1, []
        while self._tok(j).kind == "NAME":
            parts.append(self._tok(j).val)
            j += 1
            if self._val(j) == ".":
                j += 1
                continue
            break
        imp = ".".join(parts)
        if parts:
            # 别名：末段（`import std.core` -> core）与首段（`lib.fn()` 写法）
            sym = self._add_sym(self.toks[i + 1], "import", None,
                                detail="import " + imp,
                                end=self._tok(j - 1).end)
            for alias in {parts[-1], parts[0]}:
                self.imports[alias] = imp
                self.import_alias[alias] = sym
        return j

    def _decl_const(self, i, pub):
        j = i + 1
        if self._tok(j).kind == "fn":
            return self._decl_fn(j, None, pub)
        if self._tok(j).kind != "NAME":
            return j
        name_tok = self.toks[j]
        j += 1
        ty = None
        if self._val(j) == ":":
            ty, j = self._parse_type(j + 1)
        # 右值：同层的表达式，遇到下一行顶格声明即结束
        k, depth = j, 0
        while k < len(self.toks) and self._tok(k).kind != "EOF":
            v = self._val(k)
            if v in ("(", "[", "{"):
                depth += 1
            elif v in (")", "]", "}"):
                depth = max(0, depth - 1)
            elif depth == 0 and k > j and self._tok(k).kind in (
                    "fn", "struct", "enum", "const", "import", "module",
                    "interface", "impl", "test"):
                break
            k += 1
        self._add_sym(name_tok, "const", None,
                      detail=f"const {name_tok.val}" + (f": {ty}" if ty else ""),
                      ty=ty, pub=pub, end=self._tok(k - 1).end)
        return k

    def _scan_tparams(self, open_i, owner):
        """`[T: Ord + Num, U]` -> ([(记号, [约束...])], 下一个位置)。"""
        close = self.pairs.get(open_i, open_i)
        out, k = [], open_i + 1
        while k < close:
            tk = self._tok(k)
            if tk.kind != "NAME":
                k += 1
                continue
            bounds = []
            k += 1
            if self._val(k) == ":":
                k += 1
                while k < close and self._tok(k).kind == "NAME":
                    bounds.append(self._tok(k).val)
                    k += 1
                    if self._val(k) == "+":
                        k += 1
                        continue
                    break
            out.append((tk, bounds))
            if self._val(k) == ",":
                k += 1
        for tok, bounds in out:
            self._add_sym(tok, "type_param", owner,
                          detail=f"类型参数 {tok.val}"
                                 + (f": {' + '.join(bounds)}" if bounds else ""))
        return out, close + 1

    def _add_tparam_scope(self, start, end, tparams):
        """类型参数的约束按**声明范围**登记：`T` 在 `Box[T: Ord]` 与
        `f[T: Shape]` 里各算各的，不能按名字全局合并（会把两个约束混在一起）。"""
        bounds = {tok.val: bs for tok, bs in tparams if bs}
        if bounds:
            self.tparam_scopes.append((start, end, bounds))

    def _tparam_bounds(self, name, off):
        best = None
        for start, end, bounds in self.tparam_scopes:
            if start <= off <= end and name in bounds:
                if best is None or (end - start) < best[0]:
                    best = (end - start, bounds[name])
        return best[1] if best else ()

    def _decl_fn(self, i, container, pub):
        """fn [Name[T]] (params) [-> T] [{ body }]；也用于 impl 内的方法。"""
        j = i + 1
        name_tok = self._tok(j)
        if name_tok.kind != "NAME":
            return i + 1
        j += 1
        tparams = []
        if self._val(j) == "[":
            tparams, j = self._scan_tparams(j, container or name_tok.val)
        params = []
        if self._val(j) == "(":
            close = self.pairs.get(j, j)
            k = j + 1
            while k < close:
                tk = self._tok(k)
                if tk.kind == "NAME":
                    k2 = k + 1
                    ty = None
                    if self._val(k2) == ":":
                        ty, k2 = self._parse_type(k2 + 1)
                    elif tk.val == "self":
                        ty = container
                    params.append((tk, ty))
                    k = k2
                    continue
                k += 1
            j = close + 1
        ret = "void"
        if self._val(j) == "->":
            ret, j = self._parse_type(j + 1)
        body = None
        if self._val(j) == "{":
            close = self.pairs.get(j, j)
            body = (j, close)
            j = close + 1
        plist = ", ".join(f"{p.val}: {t}" if t else p.val for p, t in params)
        sig = f"fn {name_tok.val}({plist})"
        if ret and ret != "void":
            sig += f" -> {ret}"
        if tparams:
            sig = sig.replace("fn " + name_tok.val,
                              "fn " + name_tok.val + "["
                              + ", ".join(t.val for t, _b in tparams) + "]", 1)
        kind = "method" if container else "fn"
        sym = self._add_sym(name_tok, kind, container, detail=sig, ty=ret,
                            pub=pub, end=self._tok(max(j - 1, i)).end,
                            )
        sym.doc = self._doc_above(name_tok.off)
        self._add_tparam_scope(name_tok.off, self._tok(max(j - 1, i)).end, tparams)
        # 形参一律登记（接口签名没有函数体，也要能跳转/悬停）
        psyms = []
        for tok, ty in params:
            psyms.append((tok, self._add_sym(
                tok, "param", name_tok.val,
                detail=f"{tok.val}: {ty}" if ty else tok.val, ty=ty)))
        if body:
            self._scan_body(body[0], body[1], psyms, name_tok.val)
        return j

    def _decl_struct(self, i, pub):
        j = i + 1
        name_tok = self._tok(j)
        if name_tok.kind != "NAME":
            return j
        j += 1
        tparams = []
        if self._val(j) == "[":
            tparams, j = self._scan_tparams(j, name_tok.val)
        if self._val(j) != "{":
            return j
        close = self.pairs.get(j, j)
        tyname = name_tok.val
        detail = "struct " + tyname
        if tparams:
            detail += "[" + ", ".join(t.val for t, _b in tparams) + "]"
        sym = self._add_sym(name_tok, "struct", None, detail=detail, pub=pub,
                            end=self._tok(close).end)
        sym.doc = self._doc_above(name_tok.off)
        self._add_tparam_scope(name_tok.off, self._tok(close).end, tparams)
        k = j + 1
        while k < close:
            tk = self._tok(k)
            if tk.kind == "NAME" and self._val(k + 1) == ":":
                fty, k2 = self._parse_type(k + 2)
                self._add_sym(tk, "field", tyname,
                              detail=f"{tk.val}: {fty}", ty=fty)
                k = min(k2, close)
                continue
            k += 1
        return close + 1

    def _decl_enum(self, i, pub):
        j = i + 1
        name_tok = self._tok(j)
        if name_tok.kind != "NAME":
            return j
        j += 1
        tparams = []
        if self._val(j) == "[":
            tparams, j = self._scan_tparams(j, name_tok.val)
        if self._val(j) != "{":
            return j
        close = self.pairs.get(j, j)
        ename = name_tok.val
        detail = "enum " + ename
        if tparams:
            detail += "[" + ", ".join(t.val for t, _b in tparams) + "]"
        sym = self._add_sym(name_tok, "enum", None, detail=detail, pub=pub,
                            end=self._tok(close).end)
        sym.doc = self._doc_above(name_tok.off)
        self._add_tparam_scope(name_tok.off, self._tok(close).end, tparams)
        k = j + 1
        while k < close:
            tk = self._tok(k)
            if tk.kind != "NAME":
                k += 1
                continue
            vname = tk.val
            k2 = k + 1
            fields, ftoks = [], []
            if self._val(k2) == "(":
                pclose = self.pairs.get(k2, k2)
                m = k2 + 1
                while m < pclose:
                    ft = self._tok(m)
                    if ft.kind == "NAME" and self._val(m + 1) == ":":
                        fty, m2 = self._parse_type(m + 2)
                        fields.append(f"{ft.val}: {fty}")
                        ftoks.append((ft, fty))
                        m = min(m2, pclose)
                        continue
                    m += 1
                k2 = pclose + 1
            d = f"{ename}.{vname}"
            if fields:
                d += "(" + ", ".join(fields) + ")"
            self._add_sym(tk, "variant", ename, detail=d, end=tk.end)
            for ft, fty in ftoks:
                # 载荷字段：容器写成 `Enum.Variant`，`Some(v: 3)` 里的 `v`
                # 因此能解析到变体字段（构造函数按字段名传参）
                self._add_sym(ft, "field", f"{ename}.{vname}",
                              detail=f"{ft.val}: {fty}", ty=fty)
            k = k2
        return close + 1

    def _decl_iface(self, i, pub):
        j = i + 1
        name_tok = self._tok(j)
        if name_tok.kind != "NAME":
            return j
        j += 1
        if self._val(j) != "{":
            return j
        close = self.pairs.get(j, j)
        iname = name_tok.val
        sym = self._add_sym(name_tok, "iface", None, detail="interface " + iname,
                            pub=pub, end=self._tok(close).end)
        sym.doc = self._doc_above(name_tok.off)
        k = j + 1
        while k < close:
            if self._tok(k).kind == "fn":
                k = self._decl_fn(k, iname, False)
                continue
            k += 1
        return close + 1

    def _decl_impl(self, i):
        j = i + 1
        base_tok = self._tok(j)
        if base_tok.kind != "NAME":
            return j
        base = base_tok.val
        j += 1
        tparams = []
        if self._val(j) == "[":
            tparams, j = self._scan_tparams(j, base)
        if self._val(j) != ":":
            return j
        j += 1
        if self._tok(j).kind == "NAME":
            j += 1
        if self._val(j) != "{":
            return j
        close = self.pairs.get(j, j)
        self._add_tparam_scope(base_tok.off, self._tok(close).end, tparams)
        k = j + 1
        while k < close:
            if self._tok(k).kind == "fn":
                k = self._decl_fn(k, base, False)
                continue
            k += 1
        return close + 1

    def _decl_test(self, i):
        j = i + 1
        name_tok = self._tok(j)
        if name_tok.kind != "STR":
            return j
        j += 1
        body = None
        if self._val(j) == "{":
            close = self.pairs.get(j, j)
            body = (j, close)
            j = close + 1
        self._add_sym(name_tok, "test", None, detail=f'test "{name_tok.val}"',
                      end=self._tok(max(j - 1, i)).end)
        if body:
            self._scan_body(body[0], body[1], [], name_tok.val)
        return j

    def _decl_global_let(self, i):
        """顶层 `let`：编译器当前不支持（`std/timer.qma` 在用），索引照收。"""
        j = i + 1
        if self._tok(j).kind == "mut":
            j += 1
        name_tok = self._tok(j)
        if name_tok.kind != "NAME":
            return j
        j += 1
        ty = None
        if self._val(j) == ":":
            ty, j = self._parse_type(j + 1)
        if self._val(j) == "=" and ty is None:
            ty = self._infer_type(j + 1)
        self._add_sym(name_tok, "global", None,
                      detail=f"let {name_tok.val}" + (f": {ty}" if ty else ""),
                      ty=ty)
        return j

    # ---- 函数体：作用域与局部变量 ----

    def _scan_body(self, open_i, close_i, params, fn_name):
        root = {"start": self.toks[open_i].off, "end": self.toks[close_i].end,
                "names": {}}
        self.scopes.append(root)
        for tok, s in params:
            root["names"][tok.val] = s
        stack, pending = [root], []
        i = open_i + 1
        while i < close_i:
            t = self.toks[i]
            if t.kind == "SYM" and t.val == "{":
                c = self.pairs.get(i, i)
                sc = {"start": t.off, "end": self.toks[c].end, "names": {}}
                self.scopes.append(sc)
                for pt in pending:
                    s = self._add_sym(pt, "local", fn_name,
                                      detail=f"let {pt.val}")
                    sc["names"][pt.val] = s
                pending = []
                stack.append(sc)
                i += 1
                continue
            if t.kind == "SYM" and t.val == "}":
                if len(stack) > 1:
                    stack.pop()
                i += 1
                continue
            if t.kind == "let":
                i = self._decl_local(i, stack[-1], fn_name)
                continue
            if t.kind in ("for", "parfor"):
                if self._tok(i + 1).kind == "NAME":
                    pending.append(self.toks[i + 1])
                i += 2
                continue
            if t.kind == "SYM" and t.val == "=>":
                binds = self._pattern_binds(i)
                if self._val(i + 1) == "{":
                    pending = binds
                else:
                    for bt in binds:
                        s = self._add_sym(bt, "local", fn_name,
                                          detail=f"let {bt.val}")
                        stack[-1]["names"][bt.val] = s
                    pending = []
                i += 1
                continue
            i += 1
        for pt in pending:      # 兜底：没等到 `{` 的绑定落在当前块
            s = self._add_sym(pt, "local", fn_name, detail=f"let {pt.val}")
            stack[-1]["names"][pt.val] = s

    def _decl_local(self, i, scope, fn_name):
        j = i + 1
        if self._tok(j).kind == "mut":
            j += 1
        name_tok = self._tok(j)
        if name_tok.kind != "NAME":
            return i + 1
        j += 1
        ty = None
        if self._val(j) == ":":
            ty, j = self._parse_type(j + 1)
        if self._val(j) == "=" and ty is None:
            ty = self._infer_type(j + 1)
        s = self._add_sym(name_tok, "local", fn_name,
                          detail=f"let {name_tok.val}" + (f": {ty}" if ty else ""),
                          ty=ty)
        scope["names"][name_tok.val] = s
        return j

    def _pattern_binds(self, arrow_i):
        """`Variant(a, _, b) =>` 里 `=>` 左边的绑定名。"""
        if self._val(arrow_i - 1) != ")":
            return []
        open_i = self.pairs.get(arrow_i - 1)
        if open_i is None:
            return []
        out = []
        for k in range(open_i + 1, arrow_i - 1):
            t = self.toks[k]
            if t.kind == "NAME" and t.val != "_":
                out.append(t)
        return out

    def _infer_type(self, j):
        """从右值第一个记号猜类型（只认几种写法，猜不到就 None）。"""
        t = self._tok(j)
        if t.kind == "INT":
            return "int"
        if t.kind == "FLOAT":
            return t.val[1]
        if t.kind == "STR" or t.kind == "FSTR":
            return "str"
        if t.kind in ("true", "false"):
            return "bool"
        if t.kind == "NAME":
            nxt = self._val(j + 1)
            if nxt == "{" and self._type_kind(t.val) == "struct":
                return t.val
            if nxt == ".":
                n2 = self._val(j + 2)
                if self._val(j + 3) == "(" and self._type_kind(t.val) == "enum":
                    return t.val
                if n2 == "new" and self._type_kind(t.val) == "struct":
                    return t.val
            if nxt == "(":
                f = self.top.get(t.val)
                if f and f.kind in ("fn", "method") and f.ty not in (None, "void"):
                    return f.ty
        if t.kind in ("vec", "rc", "map"):
            ty, k = self._parse_type(j)
            if self._val(k) == "." and self._val(k + 1) == "new":
                return ty
        return None

    # ---- 名字解析 ----

    def _type_kind(self, name):
        s = self.top.get(name)
        if s and s.kind in ("struct", "enum", "iface"):
            return s.kind
        if self.ws:
            hit = self.ws.lookup_imported(self, name)
            if hit and hit.symkind in ("struct", "enum", "iface"):
                return hit.symkind
        return None

    def _lookup_local(self, name, off):
        # 作用域按 256 字节分块索引，块内按范围从小到大排：第一个命中的
        # 就是最内层（同名遮蔽）。不这么做的话每个名字都要扫全部作用域，
        # 300 行的文件里 800 处引用 × 60 个块 = 五万次比较。
        for sc in self._scope_blocks.get(off >> 8, ()):
            if sc["start"] <= off <= sc["end"]:
                s = sc["names"].get(name)
                if s is not None:
                    return s
        return None

    def _index_scopes(self):
        self._scope_blocks = {}
        for sc in self.scopes:
            for b in range(sc["start"] >> 8, (sc["end"] >> 8) + 1):
                self._scope_blocks.setdefault(b, []).append(sc)
        for lst in self._scope_blocks.values():
            lst.sort(key=lambda s: s["end"] - s["start"])

    def _resolve_all(self):
        for idx, t in enumerate(self.toks):
            if t.kind != "NAME":
                continue
            # 上下文关键字（`pub` 修饰符、`for x in v` 的 `in`）不是引用
            if t.val in ("pub", "in") and t.off not in self.decl_off:
                continue
            self.occs.append(Occ(t.off, t.end, t.val, self._resolve(idx)))

    def _resolve(self, idx):
        t = self.toks[idx]
        sid = self.decl_off.get(t.off)
        if sid is not None:
            return Ref("local", sid=sid)
        prev = self.toks[idx - 1] if idx > 0 else None
        if prev is not None and prev.kind == "SYM" and prev.val == ".":
            return self._resolve_chain(idx)
        s = self._lookup_local(t.val, t.off)
        if s is not None:
            return Ref("local", sid=s.sid)
        s = self.top.get(t.val)
        if s is not None:
            return Ref("local", sid=s.sid)
        s = self.modules.get(t.val)
        if s is not None:
            return Ref("local", sid=s.sid)
        s = self.import_alias.get(t.val)
        if s is not None:
            return Ref("local", sid=s.sid)
        s = self.type_params.get(t.val)
        if s is not None:
            return Ref("local", sid=s.sid)
        # 具名字段/载荷字段：`P { a: x }`、`Some(v: 3)` 里的字段名
        if self._val(idx + 1) == ":" and prev is not None and prev.val in ("(", ",", "{"):
            cands = self.field_by_name.get(t.val)
            if cands and len({c.container for c in cands}) == 1:
                return Ref("local", sid=cands[0].sid)
        if t.val in BUILTIN_FNS:
            return Ref("builtin", name=t.val)
        if t.val in BUILTIN_TYPES or t.val in BUILTIN_CAPS:
            return Ref("builtin", name=t.val)
        if self.ws:
            hit = self.ws.lookup_imported(self, t.val)
            if hit is not None:
                return hit
        return None

    def _resolve_chain(self, idx):
        j = idx
        chain = []
        while j >= 2 and self.toks[j - 1].kind == "SYM" and self.toks[j - 1].val == ".":
            chain.append(self.toks[j].val)
            j -= 2
            # 类型实参：`Opt[int].Some` / `Either[int, str].Left` 要跳过 `[...]`
            if self.toks[j].kind == "SYM" and self.toks[j].val == "]":
                op = self.pairs.get(j)
                if op is not None and op >= 1:
                    j = op - 1
        chain.reverse()
        cur = self._ref_of_expr_at(j)
        if cur is None:
            return None
        for m in chain:
            cur = self._member_of(cur, m)
            if cur is None:
                return None
        return cur

    def _ref_of_expr_at(self, j):
        """表达式末端记号 -> 它指的东西（支持 `x`、`a.b`、`f()`、`Opt[int]`）。"""
        if not (0 <= j < len(self.toks)):
            return None
        t = self.toks[j]
        if t.kind == "NAME":
            if j >= 1 and self.toks[j - 1].kind == "SYM" and self.toks[j - 1].val == ".":
                return self._resolve_chain(j)
            return self._resolve(j)
        if t.kind in ("vec", "map", "rc", "chan"):
            return Ref("builtin", name=t.kind)
        if t.kind == "SYM" and t.val == "]":
            op = self.pairs.get(j)
            if op is not None and op >= 1:
                return self._ref_of_expr_at(op - 1)
            return None
        if t.kind == "SYM" and t.val == ")":
            op = self.pairs.get(j)
            if op is not None and op >= 1:
                return self._ref_of_expr_at(op - 1)
            return None
        return None

    def _member_of(self, cur, name):
        if cur is None:
            return None
        if cur.kind == "builtin":
            # 标量/容器的内建方法：能认出名字就记成内建（跳转无目标、
            # 重命名拒绝），认不出就是未解析——不猜用户类型
            return Ref("builtin", name=name) if name in _ALL_BUILTIN_METHODS else None
        if cur.kind == "ext":
            if self.ws is None:
                return None
            return self.ws.member_of(cur.path, cur.name, name)
        s = self.syms[cur.sid]
        if s.kind in ("module", "import"):
            # `util.make_box` / `std.core`：先在该模块里找 pub 声明，
            # 找不到才把路径段本身当作模块（`import std.core` 的 `core`）
            if self.ws:
                hit = self.ws.lookup_in_module(self, s.name, name)
                if hit is not None:
                    return hit
            return Ref("local", sid=s.sid)
        if s.kind in ("fn", "method") and s.ty:
            # 调用结果：按返回类型继续找成员（`f().x`）
            inner = self._ref_of_type(s.ty)
            return self._member_of(inner, name) if inner is not None else None
        if s.kind in ("struct", "enum", "iface"):
            return self._member_sym(s.name, name)
        if s.ty:
            hit = self._member_sym(s.ty, name)
            if hit is not None:
                return hit
            if self.ws:
                hit = self.ws.member_of_type(s.ty, name)
                if hit is not None:
                    return hit
            # 类型参数带接口约束：`fn f[T: Shape](s: T) { s.area() }`
            for bound in self._tparam_bounds(s.ty, s.off):
                hit = self._member_sym(bound, name)
                if hit is not None:
                    return hit
            if name in _builtin_methods_for(s.ty):
                return Ref("builtin", name=name)
        return None

    def _member_sym(self, owner, name):
        s = self.members.get((owner, name))
        if s is None and owner != _strip_args(owner):
            s = self.members.get((_strip_args(owner), name))
        return Ref("local", sid=s.sid) if s else None

    def _ref_of_type(self, ty):
        """类型名 -> 该类型的声明引用（本文件优先，其次 import）。"""
        if not ty or ty == "void":
            return None
        base = _strip_args(ty)
        s = self.top.get(base)
        if s is not None:
            return Ref("local", sid=s.sid)
        if ty in BUILTIN_TYPES:
            return Ref("builtin", name=ty)
        if self.ws:
            return self.ws.lookup_imported(self, base)
        return None

    # ---- 收尾 ----

    def _finish_positions(self):
        for s in self.syms:
            s.line, s.col = self.lm.pos(s.off)

    # ---- 查询 ----

    def tok_index_at(self, off):
        i = bisect.bisect_right(self.tok_offs, off) - 1
        for k in (i, i + 1):
            if 0 <= k < len(self.toks):
                t = self.toks[k]
                if t.off <= off < t.end:
                    return k
        return None

    def word_at(self, line, col):
        """光标下的名字记号下标（光标在名字末尾也算命中）。"""
        off = self.lm.off(line, col)
        i = bisect.bisect_right(self.tok_offs, off) - 1
        for k in (i, i + 1):
            if 0 <= k < len(self.toks):
                t = self.toks[k]
                if t.kind == "NAME" and t.off <= off <= t.end:
                    return k
        return None

    def occ_at(self, line, col):
        k = self.word_at(line, col)
        if k is None:
            return None
        t = self.toks[k]
        for o in self.occs:
            if o.off == t.off:
                return o
        return None

    def sym_of(self, ref):
        if ref is None or ref.kind != "local":
            return None
        return self.syms[ref.sid]

    def prefix_at(self, off):
        """光标前的标识符前缀（用于过滤补全项）。"""
        s = off
        while s > 0 and (self.src[s - 1].isalnum() or self.src[s - 1] == "_"):
            s -= 1
        return self.src[s:off]

    def members_for(self, ref):
        """`x.` 之后该给什么：返回 [(name, kind, detail)]。"""
        out = []
        if ref is None:
            return out
        if ref.kind == "ext" and self.ws:
            return self.ws.members_of(ref.path, ref.name)
        if ref.kind == "builtin":
            return [(m, "method", f"内建方法 {m}") for m in BUILTIN_METHODS["any"]]
        s = self.syms[ref.sid]
        if s.kind in ("module", "import") and self.ws:
            return self.ws.module_members(self, s.name)
        owners = []
        if s.kind in ("struct", "enum", "iface"):
            owners.append(s.name)
        if s.ty:
            owners.append(s.ty)
            owners.append(_strip_args(s.ty))
            owners.extend(self._tparam_bounds(s.ty, s.off))
        seen = set()
        for owner in owners:
            for (cont, name), ms in self.members.items():
                if cont != owner and cont != _strip_args(owner):
                    continue
                if name in seen:
                    continue
                seen.add(name)
                out.append((name, ms.kind, ms.detail))
        if s.ty:
            for m in _builtin_methods_for(s.ty):
                if m not in seen:
                    seen.add(m)
                    out.append((m, "method", f"内建方法 {m}（{s.ty}）"))
            if self.ws:
                for name, kind, detail in self.ws.members_of_type(s.ty):
                    if name not in seen:
                        seen.add(name)
                        out.append((name, kind, detail))
        return out

    def completions(self, line, col):
        """返回 [(name, kind, detail)]，已按前缀过滤、按相关性排序。"""
        off = self.lm.off(line, col)
        k = bisect.bisect_right(self.tok_offs, off) - 1
        # 注释与字符串里不弹补全（弹出来只会被当成噪音；`f"..."` 的段内表达式
        # 需要拆段解析，未做，同样不弹）
        if k >= 0:
            t0 = self.toks[k]
            if t0.kind in ("COMMENT", "STR", "FSTR") and t0.off <= off <= t0.end:
                return []
        prefix = self.prefix_at(off)
        items, seen = [], set()

        def push(name, kind, detail):
            if name in seen:
                return
            if prefix and not name.startswith(prefix):
                return
            seen.add(name)
            items.append((name, kind, detail))

        # 光标若落在正在输入的 NAME 里（`s.ar|`），前一个记号才是判定依据
        k = bisect.bisect_right(self.tok_offs, off) - 1
        if 0 <= k < len(self.toks):
            t = self.toks[k]
            if t.kind == "NAME" and t.off <= off <= t.end:
                k -= 1
        prev = self.toks[k] if k >= 0 else None
        if prev is not None and prev.kind == "SYM" and prev.val == ".":
            ref = self._ref_of_expr_at(k - 1)
            for name, kind, detail in self.members_for(ref):
                push(name, kind, detail)
            return items

        # 局部：从最内层块往外
        for sc in sorted(self.scopes,
                         key=lambda s: s["end"] - s["start"]):
            if sc["start"] <= off <= sc["end"]:
                for name, s in sc["names"].items():
                    push(name, s.kind, s.detail)
        for name, s in self.top.items():
            push(name, s.kind, s.detail)
        for name, s in self.modules.items():
            push(name, s.kind, s.detail)
        if self.ws:
            for name, kind, detail in self.ws.imported_completions(self):
                push(name, kind, detail)
        for name in sorted(BUILTIN_FNS):
            push(name, "fn", f"内建 {name}(...) -> {BUILTIN_FNS[name]}")
        for kw in sorted(KEYWORDS):
            push(kw, "keyword", "关键字")
        return items

    def diagnostics(self):
        out = []
        if self.scan_error:
            m = re.search(r"line (\d+)", self.scan_error)
            line = max(0, int(m.group(1)) - 1) if m else 0
            text = self.lm.line_text(line)
            out.append({
                "range": {"start": {"line": line, "character": 0},
                          "end": {"line": line,
                                  "character": self.lm.to_utf16(line, len(text))}},
                "severity": 1, "source": "quelmara-lex",
                "message": self.scan_error})
            return out
        for tok, msg in self.unmatched:
            line, col = self.lm.pos(tok.off)
            eline, ecol = self.lm.pos(tok.end)
            out.append({
                "range": {"start": {"line": line,
                                    "character": self.lm.to_utf16(line, col)},
                          "end": {"line": eline,
                                  "character": self.lm.to_utf16(eline, ecol)}},
                "severity": 1, "source": "quelmara-struct", "message": msg})
        for tok, prev in self.dups:
            line, col = self.lm.pos(tok.off)
            pline, _ = self.lm.pos(prev.off)
            out.append({
                "range": {"start": {"line": line,
                                    "character": self.lm.to_utf16(line, col)},
                          "end": {"line": line,
                                  "character": self.lm.to_utf16(
                                      line, col + len(tok.val))}},
                "severity": 2, "source": "quelmara-struct",
                "message": f"顶层重名：{tok.val} 已在该文件第 {pline + 1} 行声明"
                           "（编译器会报重复定义）"})
        return out

    # ---- 供 LSP 直接用的结构 ----

    def sym_range(self, s):
        line, col = self.lm.pos(s.off)
        eline, ecol = self.lm.pos(s.end)
        return {"start": {"line": line, "character": self.lm.to_utf16(line, col)},
                "end": {"line": eline, "character": self.lm.to_utf16(eline, ecol)}}

    def name_range(self, s):
        line, col = self.lm.pos(s.off)
        return {"start": {"line": line, "character": self.lm.to_utf16(line, col)},
                "end": {"line": line,
                        "character": self.lm.to_utf16(line, col + len(s.name))}}

    def document_symbols(self):
        children = {}
        for s in self.syms:
            if s.container is None or s.kind in ("type_param",):
                continue
            children.setdefault(s.container, []).append(s)
        out = []
        for s in self.syms:
            if s.container is not None:
                continue
            kids = []
            for c in children.get(s.name, []):
                if c.kind == "type_param":
                    continue
                kids.append({"name": c.name, "kind": SYMBOL_KIND.get(c.kind, 13),
                             "detail": c.detail, "range": self.sym_range(c),
                             "selectionRange": self.name_range(c)})
            item = {"name": s.name, "kind": SYMBOL_KIND.get(s.kind, 13),
                    "detail": s.detail, "range": self.sym_range(s),
                    "selectionRange": self.name_range(s)}
            if kids:
                item["children"] = kids
            out.append(item)
        return out

    def hover_text(self, s):
        lines = ["```quelmara", s.detail, "```"]
        if s.kind == "field":
            lines.append(f"字段 · `{s.container}`")
        elif s.kind == "variant":
            lines.append(f"枚举变体 · `{s.container}`")
        elif s.kind in ("fn", "method"):
            lines.append("函数" if s.kind == "fn" else f"方法 · `{s.container}`")
        else:
            lines.append({"struct": "结构体", "enum": "枚举", "iface": "接口",
                          "const": "常量", "local": "局部变量",
                          "param": "形参", "global": "全局变量",
                          "module": "模块", "import": "导入",
                          "test": "测试块", "type_param": "类型参数",
                          }.get(s.kind, s.kind))
        if s.doc:
            lines.append("")
            lines.append(s.doc)
        rel = os.path.relpath(s.path, os.getcwd()) if s.path != "<mem>" else "-"
        lines.append("")
        lines.append(f"`{rel}:{s.line + 1}`")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. 工作区（跨文件）
# ---------------------------------------------------------------------------


def path_to_uri(path):
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://" + quote(p, safe="/:")


def uri_to_path(uri):
    if uri.startswith("file://"):
        p = unquote(uri[7:])
        if re.match(r"^/[A-Za-z]:", p):
            p = p[1:]
        return os.path.normpath(p)
    return uri


class Workspace:
    def __init__(self, root=None):
        self.root = os.path.normpath(os.path.abspath(root)) if root else os.getcwd()
        self.docs = {}
        self._stack = set()
        self._cfg = {}
        self._mod_cache = {}

    # ---- 索引管理 ----

    def index(self, path, src=None, force=False):
        path = os.path.normpath(os.path.abspath(path))
        if not force and src is None and path in self.docs:
            return self.docs[path]
        if path in self._stack:      # import 环
            return None
        self._stack.add(path)
        try:
            if src is None:
                with open(path, encoding="utf-8", errors="replace") as f:
                    src = f.read()
            ix = Index(path, src, ws=self)
            self.docs[path] = ix
            return ix
        finally:
            self._stack.discard(path)

    def index_uri(self, uri, src=None, force=False):
        return self.index(uri_to_path(uri), src, force)

    def drop(self, path):
        self.docs.pop(os.path.normpath(os.path.abspath(path)), None)

    def qma_files(self):
        skip = {"build", ".git", "__pycache__", "archive", "node_modules",
                ".qpm", ".workbuddy-ai"}
        out = []
        for base, dirs, names in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
            for n in names:
                if n.endswith(SRC_EXT):
                    out.append(os.path.join(base, n))
        return sorted(out)

    def ensure_all(self):
        n = 0
        for p in self.qma_files():
            if p not in self.docs:
                try:
                    self.index(p)
                    n += 1
                except Exception:
                    continue
        return n

    # ---- import 解析 ----

    def _cfg_for(self, d):
        if d in self._cfg:
            return self._cfg[d]
        try:
            cfg = load_config(os.path.join(d, "x" + SRC_EXT))
        except Exception:
            cfg = {}
        self._cfg[d] = cfg
        return cfg

    def resolve_import(self, imp, from_path):
        d = os.path.dirname(os.path.abspath(from_path))
        cands = list(_import_candidates(imp, d))
        cfg = self._cfg_for(d)
        src = (cfg or {}).get("src") or {}
        parts = imp.split(".")
        rel = os.sep.join(parts) + SRC_EXT
        if src.get("lib"):
            cands.append(os.path.normpath(os.path.join(d, src["lib"], rel)))
        if src.get("ref"):
            cands.append(os.path.normpath(os.path.join(d, src["ref"], rel)))
        cands += _qpm_candidates(imp, self.root)
        for c in cands:
            if os.path.isfile(c):
                return os.path.normpath(os.path.abspath(c))
        return None

    def _imported_indexes(self, ix):
        if ix._imported_cache is not None:
            return ix._imported_cache
        out = []
        for alias, imp in ix.imports.items():
            p = self.resolve_import(imp, ix.path)
            if not p:
                continue
            jx = self.docs.get(p)
            if jx is None:
                jx = self.index(p)
            if jx is not None and jx is not ix and all(jx is not o for _a, o in out):
                out.append((alias, jx))
        ix._imported_cache = out
        return out

    def imported_map(self, ix):
        """被导入模块的 pub 顶层符号：{名字: Ref}（一次建表，解析时 O(1)）。"""
        if ix._ext_map is not None:
            return ix._ext_map
        m = {}
        for _alias, jx in self._imported_indexes(ix):
            for name, s in jx.top.items():
                if s.pub and name not in m:
                    m[name] = Ref("ext", path=jx.path, name=s.name,
                                  symkind=s.kind, off=s.off)
        ix._ext_map = m
        return m

    def lookup_imported(self, ix, name):
        return self.imported_map(ix).get(name)

    def _module_index(self, ix, alias):
        """`ix` 里 `alias` 指向的模块索引（按 (文件, 别名) 缓存）。"""
        imp = ix.imports.get(alias)
        if not imp:
            return None
        key = (ix.path, alias)
        if key in self._mod_cache:
            return self._mod_cache[key]
        p = self.resolve_import(imp, ix.path)
        jx = self.docs.get(p) if p else None
        if p and jx is None:
            jx = self.index(p)
        self._mod_cache[key] = jx
        return jx

    def lookup_in_module(self, ix, alias, name):
        """`alias.name`：在该别名指向的模块里找 pub 声明。"""
        jx = self._module_index(ix, alias)
        if jx is None:
            return None
        s = jx.top.get(name)
        if s is not None and s.pub:
            return Ref("ext", path=jx.path, name=s.name, symkind=s.kind,
                       off=s.off)
        return None

    def module_members(self, ix, alias):
        jx = self._module_index(ix, alias)
        if jx is None:
            return []
        return [(s.name, s.kind, s.detail)
                for s in jx.syms if s.pub and s.container is None]

    def imported_completions(self, ix):
        out = []
        for _alias, jx in self._imported_indexes(ix):
            for name, s in jx.top.items():
                if s.pub:
                    out.append((name, s.kind, s.detail))
        return out

    def member_of(self, path, owner, name):
        """在 path 这个文件里找 `owner` 的成员 `name`。

        `owner` 可能是类型名，也可能是**函数名**（`util.area(b).to_str()`：
        跨文件调用结果的成员按返回类型查）。
        """
        jx = self.docs.get(path)
        if jx is None:
            return None
        s = jx.top.get(owner)
        if s is not None and s.kind in ("fn", "method") and s.ty:
            hit = self.member_of_type(s.ty, name)
            if hit is not None:
                return hit
            if name in _builtin_methods_for(s.ty):
                return Ref("builtin", name=name)
            return None
        ref = jx._member_sym(owner, name)
        if ref is not None:
            t = jx.syms[ref.sid]
            return Ref("ext", path=jx.path, name=t.name, symkind=t.kind,
                       off=t.off)
        return None

    def member_of_type(self, ty, name):
        for p, jx in list(self.docs.items()):
            s = jx.top.get(_strip_args(ty))
            if s is not None and s.kind == "struct":
                ref = jx._member_sym(s.name, name)
                if ref is not None:
                    t = jx.syms[ref.sid]
                    return Ref("ext", path=jx.path, name=t.name,
                               symkind=t.kind, off=t.off)
        return None

    def members_of(self, path, owner):
        jx = self.docs.get(path)
        if jx is None:
            return []
        out = []
        for (cont, name), s in jx.members.items():
            if cont == owner or cont == _strip_args(owner):
                out.append((name, s.kind, s.detail))
        return out

    def members_of_type(self, ty):
        out = []
        for p, jx in list(self.docs.items()):
            s = jx.top.get(_strip_args(ty))
            if s is not None and s.kind == "struct":
                for (cont, name), m in jx.members.items():
                    if cont == s.name:
                        out.append((name, m.kind, m.detail))
        return out

    # ---- 跨文件引用/重命名 ----

    def find_refs(self, target_path, name, symkind, include_decl=True):
        """[(path, off, end)]：所有解析到 (target_path, name, symkind) 的引用。"""
        out = []
        if target_path not in self.docs:
            self.index(target_path)
        for path, jx in list(self.docs.items()):
            for o in jx.occs:
                r = o.ref
                if r is None:
                    continue
                if r.kind == "local":
                    if path != target_path:
                        continue
                    s = jx.syms[r.sid]
                    if s.name != name or s.kind != symkind:
                        continue
                    if not include_decl and s.off == o.off:
                        continue
                    out.append((path, o.off, o.end))
                elif r.kind == "ext":
                    if r.path == target_path and r.name == name and \
                            r.symkind == symkind:
                        out.append((path, o.off, o.end))
        return out


# ---------------------------------------------------------------------------
# 5. 命令行（工具链自查，不起 LSP 也能用）
# ---------------------------------------------------------------------------


def summarize(ix):
    kinds = {}
    for s in ix.syms:
        kinds[s.kind] = kinds.get(s.kind, 0) + 1
    resolved = sum(1 for o in ix.occs if o.ref is not None)
    return {"path": ix.path, "symbols": len(ix.syms), "kinds": kinds,
            "occurrences": len(ix.occs), "resolved": resolved,
            "unresolved": len(ix.occs) - resolved,
            "diagnostics": len(ix.diagnostics()),
            "build_ms": round(ix.build_ms, 3)}


def _parse_pos(s):
    parts = s.replace(":", " ").split()
    if len(parts) < 2:
        raise SystemExit("位置写法：FILE:LINE:COL（行从 1 起）")
    return int(parts[0]) - 1, int(parts[1])


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Quelmara 语义索引")
    ap.add_argument("src")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--at", default=None, metavar="LINE:COL",
                    help="打印该位置的解析结果")
    ap.add_argument("--completions", action="store_true",
                    help="打印 --at 位置的补全项")
    args = ap.parse_args(argv)

    ws = Workspace(os.getcwd())
    ix = ws.index(args.src)
    if args.at:
        line, col = _parse_pos(args.at)
        if args.completions:
            for name, kind, detail in ix.completions(line, col):
                print(f"  {name:<24} {kind:<10} {detail}")
            return 0
        occ = ix.occ_at(line, col)
        if occ is None:
            print("（该位置没有名字）")
            return 1
        print(f"{occ.name} -> {occ.ref}")
        return 0
    info = summarize(ix)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print(f"{os.path.relpath(ix.path, os.getcwd())}")
    print(f"  符号 {info['symbols']}  引用 {info['occurrences']}"
          f"（已解析 {info['resolved']} / 未解析 {info['unresolved']}）"
          f"  索引 {info['build_ms']:.2f} ms")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(info["kinds"].items())))
    for s in ix.syms:
        print(f"    {s.line + 1:>4}:{s.col:<4} {s.kind:<10} {s.detail}")
    for d in ix.diagnostics():
        print(f"  ! {d['range']['start']['line'] + 1}: {d['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
