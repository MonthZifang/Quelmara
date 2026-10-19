#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rosoto -> C99 转译器原型 (v0.1)
================================
把 Rosoto 源码 (.ros) 转译为 C99，再交给任意 C 编译器原生编译。

已实现（对应 SPEC.md §9）：
  - module / import / fn / let / let mut / if-else / while / for-in-range / return
  - int / bool / str / []byte / net.Conn 类型与表达式全集（含字符串 + 拼接）
  - parfor：多核 pthread 分块并行 + reduction 归约
      * 根目录 Rosoto.toml [core] multicore = false  -> 编译期降级为串行
      * [core] threads = 0 (自动) / >0 (精确线程数)
  - net.TcpServer { ... } + server.serve()：epoll 非阻塞并发 echo 运行时
      * [net] max_conns / recv_buffer 等资源上限注入编译产物

用法：
  python3 tools/rosoto.py build examples/hello.ros -o build/hello.c
  python3 tools/rosoto.py run   examples/hello.ros
"""

import argparse
import os
import subprocess
import sys
import tomllib

# ---------------------------------------------------------------------------
# 0. 配置文件 Rosoto.toml（项目根目录，唯一全局资源开关）
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "core": {"multicore": True, "threads": 0, "affinity": "none", "preempt": True},
    "net": {"backend": "auto", "io_threads": 0, "max_conns": 1000000,
            "recv_buffer": 4096, "send_buffer": 4096, "tcp_nodelay": True,
            "reuse_port": True, "backpressure": "drop"},
    "memory": {"arena_default": False, "heap_limit_mb": 512},
    "build": {"opt": "speed", "lto": True, "target": "native"},
}


def find_config(src_path):
    """从源文件目录向上（以及 cwd）查找 Rosoto.toml"""
    candidates = []
    d = os.path.dirname(os.path.abspath(src_path))
    while True:
        candidates.append(os.path.join(d, "Rosoto.toml"))
        if d == os.path.dirname(d):
            break
        d = os.path.dirname(d)
    candidates.append(os.path.join(os.getcwd(), "Rosoto.toml"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def load_config(src_path):
    cfg = {k: dict(v) for k, v in DEFAULT_CONFIG.items()}
    path = find_config(src_path)
    if path:
        with open(path, "rb") as f:
            user = tomllib.load(f)
        for section, values in user.items():
            if section in cfg and isinstance(values, dict):
                cfg[section].update(values)
        cfg["_path"] = path
    else:
        cfg["_path"] = None
    return cfg


# ---------------------------------------------------------------------------
# 1. 词法分析
# ---------------------------------------------------------------------------

KEYWORDS = {"fn", "let", "mut", "if", "else", "while", "for", "parfor",
            "return", "module", "import", "true", "false", "test",
            "break", "continue", "struct", "enum", "match",
            "arena", "spawn", "chan"}

TWO_CHAR = {"->", "==", "!=", "<=", ">=", "&&", "||", "+=", "-=", "*=", "/=", "..", "=>"}
ONE_CHAR = "(){}[],:.=<>+-*/%!?"

SYMBOLS = sorted(TWO_CHAR | set(ONE_CHAR), key=len, reverse=True)


class Tok:
    __slots__ = ("kind", "val", "line")

    def __init__(self, kind, val, line):
        self.kind, self.val, self.line = kind, val, line

    def __repr__(self):
        return f"{self.kind}({self.val!r})"


def tokenize(src, keep_comments=False):
    """词法分析。keep_comments=True 时保留注释记号（供 `rosoto fmt` 使用，
    格式化器必须能原样保留注释，否则会静默删掉用户文档）。"""
    toks, i, line, n = [], 0, 1, len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            if keep_comments:
                toks.append(Tok("NL", "\n", line))
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if src.startswith("//", i):
            j = i
            while j < n and src[j] != "\n":
                j += 1
            if keep_comments:
                toks.append(Tok("COMMENT", src[i:j], line))
            i = j
            continue
        if src.startswith("/*", i):
            j, buf = i + 2, ["/*"]
            while j < n and not src.startswith("*/", j):
                if src[j] == "\n":
                    line += 1
                buf.append(src[j])
                j += 1
            buf.append("*/")
            if keep_comments:
                toks.append(Tok("COMMENT", "".join(buf), line))
            i = j + 2
            continue
        if c.isdigit():
            j = i
            while j < n and (src[j].isdigit() or src[j] == "_"):
                j += 1
            toks.append(Tok("INT", int(src[i:j].replace("_", "")), line))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            toks.append(Tok(word if word in KEYWORDS else "NAME", word, line))
            i = j
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    esc = src[j + 1]
                    buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc, esc))
                    j += 2
                else:
                    if src[j] == "\n":
                        line += 1
                    buf.append(src[j])
                    j += 1
            if j >= n:
                raise SyntaxError(f"line {line}: 字符串未闭合")
            toks.append(Tok("STR", "".join(buf), line))
            i = j + 1
            continue
        for sym in SYMBOLS:
            if src.startswith(sym, i):
                toks.append(Tok("SYM", sym, line))
                i += len(sym)
                break
        else:
            raise SyntaxError(f"line {line}: 非法字符 {c!r}")
    toks.append(Tok("EOF", None, line))
    return toks


# ---------------------------------------------------------------------------
# 2. 语法分析（递归下降）
#    AST 节点：元组形式
#      stmt: ('let',mut,name,expr) ('assign',name,op,expr)
#            ('assign_field',lhs,op,expr) ('if',cond,then,else)
#            ('while',cond,body) ('for'|'parfor',var,lo,hi,body)
#            ('arena', body) ('return',expr|None) ('expr',expr)
#            ('break',) ('continue',)
#      expr: ('num',v) ('str',s) ('bool',v) ('name',n) ('path',[..])
#            ('call',path,args) ('method',obj,name,args) ('binop',op,l,r)
#            ('unop',op,x) ('structlit',path,fields) ('try',expr)
#            ('field',obj,name) ('spawn', call_expr)
#
# 路径消歧：`a.b.c` 在表达式位置解析为 ('path',['a','b','c'])。
# 降级时若 a 是当前作用域的变量，则整条链是【字段访问链】；
# 否则是模块/枚举常量路径（如 net.Action.Keep）。
# ---------------------------------------------------------------------------


class Parser:
    def __init__(self, toks):
        self.toks, self.pos = toks, 0
        self.structs = {}          # name -> [(field, type)]（预扫描先登记名字）
        self.enums = {}            # name -> [(variant, [(field, type)])]（预扫描先登记名字）
        self.decl_order = []       # [("struct"|"enum", name)] 声明顺序（C typedef 输出顺序）
        self._prescan()

    def _prescan(self):
        """顶层预扫描：先把 struct 名字登记下来。
        表达式里 `NAME { ... }` 是结构体字面量还是别的东西，取决于 NAME
        是不是结构体；没有符号表就用一次线性预扫描解决（O(n)）。
        花括号深度 > 0 的位置（函数体 / test 块）不看，避免把局部东西当声明。"""
        depth, i, toks = 0, 0, self.toks
        while i < len(toks):
            t = toks[i]
            if t.kind == "SYM" and t.val == "{":
                depth += 1
            elif t.kind == "SYM" and t.val == "}":
                depth -= 1
            elif depth == 0 and t.kind == "struct" and i + 1 < len(toks) \
                    and toks[i + 1].kind == "NAME":
                self.structs.setdefault(toks[i + 1].val, [])
            elif depth == 0 and t.kind == "enum" and i + 1 < len(toks) \
                    and toks[i + 1].kind == "NAME":
                self.enums.setdefault(toks[i + 1].val, [])
            i += 1

    def peek(self, off=0):
        return self.toks[min(self.pos + off, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def at(self, kind, val=None):
        t = self.peek()
        return t.kind == kind and (val is None or t.val == val)

    def eat(self, kind, val=None):
        if self.at(kind, val):
            return self.next()
        t = self.peek()
        raise SyntaxError(f"line {t.line}: 期望 {val or kind}，得到 {t.val!r}")

    def parse_program(self):
        mod, imports, fns, tests = None, [], [], []
        while not self.at("EOF"):
            if self.at("module"):
                self.next()
                mod = self.eat("NAME").val
            elif self.at("import"):
                self.next()
                path = [self.eat("NAME").val]
                while self.at("SYM", "."):
                    self.next()
                    path.append(self.eat("NAME").val)
                imports.append(".".join(path))
            elif self.at("fn"):
                fns.append(self.parse_fn())
            elif self.at("struct"):
                self.next()
                name = self.eat("NAME").val
                self.eat("SYM", "{")
                fields = []
                while not self.at("SYM", "}"):
                    fname = self.eat("NAME").val
                    self.eat("SYM", ":")
                    fields.append((fname, self.parse_type()))
                    if self.at("SYM", ","):
                        self.next()
                self.eat("SYM", "}")
                self.structs[name] = fields
                self.decl_order.append(("struct", name))
            elif self.at("enum"):
                self.next()
                name = self.eat("NAME").val
                self.eat("SYM", "{")
                variants = []
                while not self.at("SYM", "}"):
                    vname = self.eat("NAME").val
                    fields = []
                    if self.at("SYM", "("):
                        self.next()
                        while not self.at("SYM", ")"):
                            fname = self.eat("NAME").val
                            self.eat("SYM", ":")
                            fields.append((fname, self.parse_type()))
                            if self.at("SYM", ","):
                                self.next()
                        self.eat("SYM", ")")
                    variants.append((vname, fields))
                    if self.at("SYM", ","):
                        self.next()
                self.eat("SYM", "}")
                seen = set()
                for vn, _ in variants:
                    if vn in seen:
                        raise SyntaxError(f"enum {name} 变体 {vn} 重复声明")
                    seen.add(vn)
                self.enums[name] = variants
                self.decl_order.append(("enum", name))
            elif self.at("test"):
                # 内建测试块：test "名字" { ... }（SPEC §8 `rosoto test`）
                self.next()
                name = self.eat("STR").val
                tests.append({"name": name, "body": self.parse_block()})
            else:
                t = self.peek()
                raise SyntaxError(
                    f"line {t.line}: 顶层期望 fn/struct/test/module/import，得到 {t.val!r}")
        return mod, imports, fns, tests, self.structs, self.enums, self.decl_order

    # ---- 类型 ----
    def parse_type(self):
        if self.at("SYM", "["):
            self.next()
            if self.at("SYM", "]"):
                self.next()
                return ("slice", self.parse_type())
            n = self.eat("INT").val
            self.eat("SYM", "]")
            return ("array", n, self.parse_type())
        if self.at("chan"):
            self.next()
            self.eat("SYM", "[")
            et = self.parse_type()
            self.eat("SYM", "]")
            return ("chan", et)
        name = self.eat("NAME").val
        while self.at("SYM", "."):
            self.next()
            name += "." + self.eat("NAME").val
        return ("named", name)

    def parse_fn(self):
        self.eat("fn")
        name = self.eat("NAME").val
        self.eat("SYM", "(")
        params = []
        while not self.at("SYM", ")"):
            pname = self.eat("NAME").val
            self.eat("SYM", ":")
            params.append((pname, self.parse_type()))
            if self.at("SYM", ","):
                self.next()
        self.eat("SYM", ")")
        ret = ("named", "void")
        if self.at("SYM", "->"):
            self.next()
            ret = self.parse_type()
        body = self.parse_block()
        return {"name": name, "params": params, "ret": ret, "body": body}

    # ---- 语句 ----
    def parse_block(self):
        self.eat("SYM", "{")
        stmts = []
        while not self.at("SYM", "}"):
            stmts.append(self.parse_stmt())
        self.eat("SYM", "}")
        return stmts

    def parse_stmt(self):
        t = self.peek()
        if t.kind == "let":
            self.next()
            mut = False
            if self.at("mut"):
                self.next()
                mut = True
            name = self.eat("NAME").val
            self.eat("SYM", "=")
            return ("let", mut, name, self.parse_expr())
        if t.kind == "if":
            return self.parse_if()
        if t.kind == "while":
            self.next()
            cond = self.parse_expr()
            return ("while", cond, self.parse_block())
        if t.kind in ("for", "parfor"):
            self.next()
            var = self.eat("NAME").val
            self.eat("NAME", "in")
            lo = self.parse_expr()
            self.eat("SYM", "..")
            hi = self.parse_expr()
            return ("for" if t.kind == "for" else "parfor", var, lo, hi, self.parse_block())
        if t.kind == "return":
            self.next()
            if self.at("SYM", "}"):
                return ("return", None)
            return ("return", self.parse_expr())
        if t.kind == "break":
            self.next()
            return ("break",)
        if t.kind == "continue":
            self.next()
            return ("continue",)
        if t.kind == "match":
            return ("match_stmt", self.parse_match())
        if t.kind == "arena":
            # arena { ... }：块内分配在块结束整体回收（SPEC §6 帧级 arena）
            self.next()
            return ("arena", self.parse_block())
        if t.kind == "enum":
            raise SyntaxError(f"line {t.line}: enum 声明只能在顶层")
        # 赋值 / 表达式语句
        expr = self.parse_expr()
        if self.at("SYM") and self.peek().val in ("=", "+=", "-=", "*=", "/="):
            op = self.next().val
            rhs = self.parse_expr()
            if isinstance(expr, tuple) and expr[0] == "name":
                return ("assign", expr[1], op, rhs)
            if isinstance(expr, tuple) and expr[0] in ("path", "field"):
                return ("assign_field", expr, op, rhs)
            raise SyntaxError(f"line {t.line}: 赋值目标不是可赋值的左值")
        return ("expr", expr)

    # ---- match ----
    def parse_match(self):
        """match 語句/表達式：
        match 求值式 {
            Enum.Variant(a, b) => 表達式
            Enum.Variant2       => { 語句塊 }
            _                   => 表達式 / { 語句塊 }
        }
        窮盡性檢查在降級期做（enum 宣告可能在 match 之後）。"""
        self.eat("match")
        scrut = self.parse_expr()
        self.eat("SYM", "{")
        arms = []
        while not self.at("SYM", "}"):
            pat = self.parse_pattern()
            self.eat("SYM", "=>")
            if self.at("SYM", "{"):
                body = ("block", self.parse_block())
            else:
                body = ("expr", self.parse_expr())
            arms.append((pat, body))
        self.eat("SYM", "}")
        return ("match", scrut, arms)

    def parse_pattern(self):
        """模式：`_` 通配 | `Enum.Variant` | `Enum.Variant(a, _, b)`（按位綁定）"""
        t = self.peek()
        if t.kind == "NAME" and t.val == "_":
            self.next()
            return ("wild",)
        name = self.eat("NAME").val
        path = [name]
        while self.at("SYM", "."):
            self.next()
            path.append(self.eat("NAME").val)
        binds = []
        if self.at("SYM", "("):
            self.next()
            while not self.at("SYM", ")"):
                b = self.eat("NAME").val
                binds.append(None if b == "_" else b)
                if self.at("SYM", ","):
                    self.next()
            self.eat("SYM", ")")
        return ("pat", path, binds)

    def parse_args(self):
        """調用實參：支持 `f(a, b)` 與命名實參 `f(x: 1, y: 2)`（枚舉變體構造用）"""
        args = []
        while not self.at("SYM", ")"):
            if self.peek().kind == "NAME" and self.peek(1).kind == "SYM" \
                    and self.peek(1).val == ":":
                nm = self.next().val
                self.next()
                args.append(("namedarg", nm, self.parse_expr()))
            else:
                args.append(self.parse_expr())
            if self.at("SYM", ","):
                self.next()
        self.eat("SYM", ")")
        return args

    def enum_variant_of(self, path):
        """路徑是否是枚舉變體（如 Shape.Circle）；返回 (enum 名, 變體名) 或 None"""
        if len(path) == 2 and path[0] in self.enums and self.enums[path[0]]:
            for vn, _ in self.enums[path[0]]:
                if vn == path[1]:
                    return path[0], path[1]
        return None

    def mk_enumlit(self, path, args, line):
        """枚舉構造：命名實參 -> [(name, expr)]；位置實參按變體字段順序展開"""
        ev = self.enum_variant_of(path)
        if ev is None:
            raise SyntaxError(f"line {line}: {'.'.join(path)} 不是已声明的枚举变体")
        ename, vname = ev
        fields = dict(self.enums[ename])
        vfields = fields[vname]
        if any(a[0] == "namedarg" for a in args) and any(a[0] != "namedarg" for a in args):
            raise SyntaxError(f"line {line}: 枚举构造实参不能混用命名与位置实参")
        out = []
        if args and args[0][0] == "namedarg":
            out = [(a[1], a[2]) for a in args]
            names = [n for n, _ in out]
            if len(set(names)) != len(names):
                raise SyntaxError(f"line {line}: {ename}.{vname} 构造实参重名")
            for n in names:
                if n not in [f for f, _ in vfields]:
                    raise SyntaxError(f"line {line}: {ename}.{vname} 没有载荷字段 {n}")
        else:
            if len(args) != len(vfields):
                raise SyntaxError(
                    f"line {line}: {ename}.{vname} 需要 {len(vfields)} 个实参，得到 {len(args)}")
            out = [(vfields[i][0], a) for i, a in enumerate(args)]
        return ("enumlit", path, out)

    def parse_if(self):
        self.eat("if")
        cond = self.parse_expr()
        then = self.parse_block()
        els = None
        if self.at("else"):
            self.next()
            if self.at("if"):
                els = [self.parse_if()]
            else:
                els = self.parse_block()
        return ("if", cond, then, els)

    # ---- 表达式（优先级：|| && == != 关系 + - * / % 一元 调用链）----
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        l = self.parse_and()
        while self.at("SYM", "||"):
            self.next()
            l = ("binop", "||", l, self.parse_and())
        return l

    def parse_and(self):
        l = self.parse_eq()
        while self.at("SYM", "&&"):
            self.next()
            l = ("binop", "&&", l, self.parse_eq())
        return l

    def parse_eq(self):
        l = self.parse_rel()
        while self.at("SYM") and self.peek().val in ("==", "!="):
            op = self.next().val
            l = ("binop", op, l, self.parse_rel())
        return l

    def parse_rel(self):
        l = self.parse_add()
        while self.at("SYM") and self.peek().val in ("<", "<=", ">", ">="):
            op = self.next().val
            l = ("binop", op, l, self.parse_add())
        return l

    def parse_add(self):
        l = self.parse_mul()
        while self.at("SYM") and self.peek().val in ("+", "-"):
            op = self.next().val
            l = ("binop", op, l, self.parse_mul())
        return l

    def parse_mul(self):
        l = self.parse_unary()
        while self.at("SYM") and self.peek().val in ("*", "/", "%"):
            op = self.next().val
            l = ("binop", op, l, self.parse_unary())
        return l

    def parse_unary(self):
        if self.at("SYM", "!"):
            self.next()
            return ("unop", "!", self.parse_unary())
        if self.at("SYM", "-"):
            self.next()
            return ("unop", "-", self.parse_unary())
        if self.at("spawn"):
            # spawn f(args) -> 线程句柄（int64）；语义见 SPEC §4
            t = self.next()
            target = self.parse_postfix()
            if not (isinstance(target, tuple) and target[0] == "call"):
                raise SyntaxError(f"line {t.line}: spawn 后面必须是函数调用，如 spawn work(x)")
            return ("spawn", target)
        return self.parse_postfix()

    def parse_postfix(self):
        e = self.parse_primary()
        line = self.peek().line
        while True:
            if self.at("SYM", "."):
                self.next()
                name = self.eat("NAME").val
                if self.at("SYM", "("):
                    self.next()
                    args = self.parse_args()
                    # `Shape.Circle(radius: 5)` -> 枚舉變體構造
                    if e[0] == "name" and self.enum_variant_of([e[1], name]):
                        e = self.mk_enumlit([e[1], name], args, line)
                    else:
                        if any(a[0] == "namedarg" for a in args):
                            raise SyntaxError(f"line {line}: 普通函数/方法调用不支持命名实参")
                        e = ("method", e, name, args)
                else:
                    # 成员路径段（如 net.Action.Keep 的尾段）
                    if e[0] == "name":
                        e = ("path", [e[1], name])
                    elif e[0] == "path":
                        e = ("path", e[1] + [name])
                    else:
                        # 调用结果 / 括号表达式上的 .field -> 字段访问
                        e = ("field", e, name)
            elif self.at("SYM", "?"):
                self.next()
                e = ("try", e)
            else:
                return e

    def _is_type_path(self, path):
        """路径是否是【类型】路径：
        - 末段是已声明的用户结构体名，或
        - 限定路径且末段大写开头（如 net.TcpServer）
        类型名按 SPEC §1 用 PascalCase，与变量名（snake_case）天然不歧义。
        否则 `for i in 0..crate.count {` 里的 `{` 会被误当成结构体字面量。"""
        last = path[-1]
        if last in self.structs:
            return True
        return len(path) > 1 and last[:1].isupper()

    def parse_primary(self):
        t = self.peek()
        if t.kind == "match":
            return self.parse_match()
        if t.kind == "chan":
            # chan[T].open(cap) -> 有界通道句柄（SPEC §4）
            self.next()
            self.eat("SYM", "[")
            et = self.parse_type()
            self.eat("SYM", "]")
            self.eat("SYM", ".")
            self.eat("NAME", "open")
            self.eat("SYM", "(")
            args = self.parse_args()      # parse_args 已吃掉右括号
            return ("chanopen", et, args)
        if t.kind == "INT":
            self.next()
            return ("num", t.val)
        if t.kind == "STR":
            self.next()
            return ("str", t.val)
        if t.kind == "true":
            self.next()
            return ("bool", True)
        if t.kind == "false":
            self.next()
            return ("bool", False)
        if t.kind == "SYM" and t.val == "(":
            self.next()
            e = self.parse_expr()
            self.eat("SYM", ")")
            return e
        if t.kind == "NAME":
            self.next()
            # 点路径（仅吸收非方法调用的 .NAME 段；NAME( 留给 postfix 处理方法调用）
            path = [t.val]
            while self.at("SYM", ".") and self.peek(1).kind == "NAME":
                nxt2 = self.peek(2)
                if nxt2.kind == "SYM" and nxt2.val == "(":
                    break
                self.next()
                path.append(self.eat("NAME").val)
            ev = self.enum_variant_of(path)
            if ev is not None and self.at("SYM", "{"):
                # `Shape.Circle { radius: 5 }` -> 枚舉變體構造（命名字段）
                self.next()
                fields = []
                while not self.at("SYM", "}"):
                    fname = self.eat("NAME").val
                    self.eat("SYM", ":")
                    fields.append((fname, self.parse_expr()))
                    if self.at("SYM", ","):
                        self.next()
                self.eat("SYM", "}")
                return ("enumlit", path, fields)
            if self._is_type_path(path) and self.at("SYM", "{"):
                # 结构体字面量 net.TcpServer { ... } / Vec3 { ... }
                self.next()
                fields = {}
                while not self.at("SYM", "}"):
                    fname = self.eat("NAME").val
                    self.eat("SYM", ":")
                    fields[fname] = self.parse_expr()
                    if self.at("SYM", ","):
                        self.next()
                self.eat("SYM", "}")
                return ("structlit", path, fields)
            if self.at("SYM", "("):
                self.next()
                args = self.parse_args()
                if ev is not None:
                    return self.mk_enumlit(path, args, t.line)
                if any(a[0] == "namedarg" for a in args):
                    raise SyntaxError(f"line {t.line}: 普通函数调用不支持命名实参")
                return ("call", path, args)
            if ev is not None:
                # 無載荷變體：`Color.Red` 即值
                return self.mk_enumlit(path, [], t.line)
            return ("path", path) if len(path) > 1 else ("name", path[0])
        raise SyntaxError(f"line {t.line}: 意外的记号 {t.val!r}")


# ---------------------------------------------------------------------------
# 2b. 测试块合成（SPEC §8 `rosoto test`）
# ---------------------------------------------------------------------------


def parse_source(src):
    """解析源码 -> (module, imports, fns, tests, structs, enums, decl_order)"""
    return Parser(tokenize(src)).parse_program()


def validate_match(arms, enums, line=None):
    """match 检查：模式合法性 + 穷尽性（SPEC §3：match 必须穷尽）。
    返回 (enum 名, [(变体下标, 绑定名列表, body), ...], 通配臂或 None)。
    任何后端（C / 自研 x86_64 / 自研 AArch64）都必须先过这道检查。"""
    ename, covered, wild_arm, plain = None, {}, None, []
    for pat, body in arms:
        if pat[0] == "wild":
            if wild_arm is not None:
                raise SyntaxError("match 有多个 `_` 通配臂")
            wild_arm = body
            plain.append((None, [], body))
            continue
        path, binds = pat[1], pat[2]
        if len(path) != 2 or path[0] not in enums or not enums[path[0]]:
            raise SyntaxError(f"match 模式 {'.'.join(path)} 必须是 Enum.Variant 形式")
        if ename is None:
            ename = path[0]
        elif ename != path[0]:
            raise SyntaxError(f"match 模式跨了多个枚举：{ename} 与 {path[0]}")
        variants = enums[ename]
        idx = None
        for i, (vn, vfields) in enumerate(variants):
            if vn == path[1]:
                idx = i
                break
        if idx is None:
            raise SyntaxError(f"枚举 {ename} 没有变体 {path[1]}")
        vfields = variants[idx][1]
        if binds and len(binds) != len(vfields):
            raise SyntaxError(
                f"{ename}.{path[1]} 有 {len(vfields)} 个载荷字段，模式绑定了 {len(binds)} 个")
        if idx in covered:
            raise SyntaxError(f"match 变体 {ename}.{path[1]} 被匹配了多次")
        covered[idx] = True
        names = binds if binds else [None] * len(vfields)
        plain.append((idx, names, body))
    if ename is None:
        if wild_arm is None:
            raise SyntaxError("match 至少需要一个枚举模式或 `_` 通配臂")
        return None, plain, wild_arm
    if wild_arm is not None and plain[-1][0] is not None:
        raise SyntaxError("`_` 通配臂必须是 match 的最后一臂（否则后面的臂不可达）")
    missing = [vn for i, (vn, _) in enumerate(enums[ename]) if i not in covered]
    if missing and wild_arm is None:
        raise SyntaxError(
            f"match 不穷尽：{ename} 缺少变体 {', '.join(missing)}（或加 `_` 通配臂）")
    return ename, plain, wild_arm


def with_test_runner(fns_ast, tests):
    """把 `test "name" { ... }` 块合成一个测试入口。

    每个 test 块单独包成一个函数（避免不同块的局部变量撞名），
    合成的 main 逐个调用并打印 `ok <名字>`；块内 assert 失败即退出码 1。
    若源文件自带 main，测试模式下会被测试入口替换（被测函数照常保留）。
    """
    if not tests:
        return fns_ast
    out = [f for f in fns_ast if f["name"] != "main"]
    main_body = []
    for i, t in enumerate(tests):
        out.append({"name": f"__test_{i}", "params": [], "ret": ("named", "void"),
                    "body": t["body"]})
        main_body.append(("expr", ("call", [f"__test_{i}"], [])))
        main_body.append(("expr", ("call", ["print"], [("str", f"ok {t['name']}")])))
    out.append({"name": "main", "params": [], "ret": ("named", "void"),
                "body": main_body})
    return out


# ---------------------------------------------------------------------------
# 3. 类型推断（原型子集）
# ---------------------------------------------------------------------------

BUILTIN_RETS = {"print": "void", "cores": "int", "assert": "void", "join": "int64_t"}

CTYPE = {
    "int": "int64_t", "i64": "int64_t", "i32": "int32_t", "u64": "uint64_t",
    "float": "double", "f64": "double", "f32": "float",
    "bool": "bool", "str": "const char *", "void": "void",
    "net.Conn": "RosotoConn *", "[]byte": "RosotoBuf", "net.Action": "int",
}


def type_str(t):
    return t[1] if t[0] == "named" else ("RosotoBuf" if t[1] == ("named", "byte") else "void *")


class Infer:
    def __init__(self, fns, structs=None, enums=None):
        self.fns = {f["name"]: f for f in fns}
        self.structs = structs or {}
        self.enums = enums or {}

    def is_agg(self, name):
        return name in self.structs or name in self.enums

    def _env_type(self, t):
        if t[0] == "chan":
            return "int64_t"
        if t[0] == "named" and t[1] in self.structs:
            return "struct:" + t[1]
        if t[0] == "named" and t[1] in self.enums:
            return "enum:" + t[1]
        return CTYPE.get(t[1], "int64_t") if t[0] == "named" else "void *"

    def fn_ret(self, name):
        f = self.fns.get(name)
        if f:
            t = f["ret"]
            if t[0] == "named":
                if t[1] in self.structs:
                    return "struct:" + t[1]
                if t[1] in self.enums:
                    return "enum:" + t[1]
                return CTYPE.get(t[1], "int64_t")
            return "RosotoBuf" if t[1] == ("named", "byte") else "void *"
        return BUILTIN_RETS.get(name, "void")

    def expr(self, e, env):
        """返回 C 侧类型字符串: int64_t / bool / const char * / RosotoBuf / RosotoConn * / int / void"""
        k = e[0]
        if k == "num":
            return "int64_t"
        if k == "str":
            return "const char *"
        if k == "bool":
            return "bool"
        if k == "name":
            return env.get(e[1], "int64_t" if e[1] in self.fns else "int64_t")
        if k == "path":
            return "int" if e[1][0] == "net" else "int64_t"
        if k == "call":
            name = e[1][-1]
            return self.fn_ret(name)
        if k == "spawn":
            return "int64_t"
        if k == "chanopen":
            return "int64_t"
        if k == "method":
            obj_t = self.expr(e[1], env)
            m = e[2]
            if m in ("send", "recv"):
                return "int64_t"
            if m == "to_str":
                return "const char *"
            if m == "write":
                return "int"
            if m == "peer_addr":
                return "const char *"
            if m == "serve":
                return "void"
            return "int64_t"
        if k == "binop":
            op = e[1]
            if op in ("==", "!=", "<", "<=", ">", ">=", "&&", "||"):
                return "bool"
            lt, rt = self.expr(e[2], env), self.expr(e[3], env)
            return "const char *" if "const char *" in (lt, rt) else "int64_t"
        if k == "unop":
            return "bool" if e[1] == "!" else self.expr(e[2], env)
        if k == "structlit":
            return "struct:" + ".".join(e[1])
        if k == "enumlit":
            return "enum:" + e[1][0]
        if k == "match":
            t = None
            for pat, body in e[2]:
                if body[0] == "expr":
                    e2 = dict(env)
                    if pat[0] == "pat" and pat[1] and len(pat[1]) == 2 and pat[1][0] in self.enums:
                        for i, b in enumerate(pat[2] or []):
                            if b is not None:
                                vfields = dict(self.enums[pat[1][0]]).get(pat[1][1], [])
                                if i < len(vfields):
                                    e2[b] = self._env_type(vfields[i][1])
                    bt = self.expr(body[1], e2)
                    if t is None:
                        t = bt
            return t or "int64_t"
        if k == "field":
            st = self.struct_of(self.expr(e[1], env))
            if st and st in self.structs:
                for fname, ftype in self.structs[st]:
                    if fname == e[2]:
                        return ("struct:" + ftype[1]) if ftype[1] in self.structs \
                            else CTYPE.get(ftype[1], "int64_t")
            return "int64_t"
        if k == "try":
            return self.expr(e[1], env)
        return "int64_t"

    @staticmethod
    def struct_of(t):
        """从类型串里取出结构体/枚举名（'struct:Vec3'/'enum:Shape' -> 名字），非聚合返回 None"""
        if isinstance(t, str) and t.startswith("struct:"):
            return t[7:]
        if isinstance(t, str) and t.startswith("enum:"):
            return t[5:]
        return None


# ---------------------------------------------------------------------------
# 4. C 运行时（按需生成）
# ---------------------------------------------------------------------------

CORE_RUNTIME = r"""
/* ===== Rosoto runtime (core) ===== */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

static int64_t rosoto_cores(void) {
    long n = sysconf(_SC_NPROCESSORS_ONLN);
    return (int64_t)(n > 0 ? n : 1);
}

/* 字符串：轮转缓冲池（无 GC、无 malloc 热点） */
#define ROSOTO_SBUF_N 64
#define ROSOTO_SBUF_SZ 512
static char rosoto_sbuf[ROSOTO_SBUF_N][ROSOTO_SBUF_SZ];
static int rosoto_sbuf_i = 0;

static const char *rosoto_i64_to_str(int64_t v) {
    char *b = rosoto_sbuf[rosoto_sbuf_i++ & (ROSOTO_SBUF_N - 1)];
    snprintf(b, ROSOTO_SBUF_SZ, "%lld", (long long)v);
    return b;
}
static const char *rosoto_bool_to_str(bool v) { return v ? "true" : "false"; }
static const char *rosoto_concat(const char *a, const char *b) {
    char *buf = rosoto_sbuf[rosoto_sbuf_i++ & (ROSOTO_SBUF_N - 1)];
    snprintf(buf, ROSOTO_SBUF_SZ, "%s%s", a ? a : "", b ? b : "");
    return buf;
}
static void rosoto_print_str(const char *s) { printf("%s\n", s ? s : "(null)"); }
static void rosoto_print_i64(int64_t v) { printf("%lld\n", (long long)v); }
static void rosoto_print_bool(bool v) { printf("%s\n", v ? "true" : "false"); }
/* 字符串相等：内容比较（而非指针比较）——str 是一等类型 */
static bool rosoto_str_eq(const char *a, const char *b) {
    if (a == b) return true;
    if (!a || !b) return false;
    return strcmp(a, b) == 0;
}
static void rosoto_assert(bool cond, const char *msg) {
    if (!cond) {
        fprintf(stderr, "assert failed: %s\n", msg ? msg : "(no message)");
        fflush(stdout);
        exit(1);
    }
}

/* spawn/join 任务句柄：rec[0] = 线程（0 = 单核同步执行），
   rec[1] = 参数块（块首字是返回值）。join 负责回收两块内存。 */
static int64_t rosoto_join(int64_t h) {
    if (h == 0) return 0;
    int64_t *rec = (int64_t *)(intptr_t)h;
    if (rec[0] != 0) pthread_join((pthread_t)(uintptr_t)rec[0], NULL);
    int64_t *blk = (int64_t *)(intptr_t)rec[1];
    int64_t r = blk[0];
    free(blk);
    free(rec);
    return r;
}

/* 有界 MPMC 通道：固定容量、阻塞式 send/recv（SPEC §4） */
typedef struct {
    pthread_mutex_t m;
    pthread_cond_t not_empty, not_full;
    int64_t cap, head, tail, count;
    int64_t *buf;
} RosotoChan;

static int64_t rosoto_chan_open(int64_t cap) {
    if (cap <= 0) cap = 1;
    RosotoChan *c = (RosotoChan *)malloc(sizeof(RosotoChan));
    pthread_mutex_init(&c->m, NULL);
    pthread_cond_init(&c->not_empty, NULL);
    pthread_cond_init(&c->not_full, NULL);
    c->cap = cap; c->head = 0; c->tail = 0; c->count = 0;
    c->buf = (int64_t *)malloc((size_t)cap * sizeof(int64_t));
    return (int64_t)(intptr_t)c;
}

static int64_t rosoto_chan_send(int64_t h, int64_t v) {
    RosotoChan *c = (RosotoChan *)(intptr_t)h;
    pthread_mutex_lock(&c->m);
    while (c->count == c->cap) pthread_cond_wait(&c->not_full, &c->m);
    c->buf[c->tail] = v;
    c->tail = (c->tail + 1) % c->cap;
    c->count++;
    pthread_cond_signal(&c->not_empty);
    pthread_mutex_unlock(&c->m);
    return 0;
}

static int64_t rosoto_chan_recv(int64_t h) {
    RosotoChan *c = (RosotoChan *)(intptr_t)h;
    pthread_mutex_lock(&c->m);
    while (c->count == 0) pthread_cond_wait(&c->not_empty, &c->m);
    int64_t v = c->buf[c->head];
    c->head = (c->head + 1) % c->cap;
    c->count--;
    pthread_cond_signal(&c->not_full);
    pthread_mutex_unlock(&c->m);
    return v;
}
"""

NET_RUNTIME = r"""
/* ===== Rosoto runtime (net: epoll 非阻塞并发 reactor) ===== */
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef ROSOTO_NET_MAX_CONNS
#define ROSOTO_NET_MAX_CONNS 1000000
#endif
#ifndef ROSOTO_RECV_BUF
#define ROSOTO_RECV_BUF 4096
#endif

typedef struct RosotoBuf { char *data; size_t len; } RosotoBuf;
typedef struct RosotoConn RosotoConn;
struct RosotoConn {
    int fd;
    char peer[64];
    bool closing;
};

#define NET_ACTION_CLOSE 0
#define NET_ACTION_KEEP  1

static const char *rosoto_conn_peer(RosotoConn *c) { return c->peer; }

/* 零拷贝回写；EAGAIN 时丢弃余量（背压策略 drop，见 Rosoto.toml [net].backpressure） */
static int rosoto_conn_write(RosotoConn *c, RosotoBuf b) {
    size_t off = 0;
    while (off < b.len) {
        ssize_t n = write(c->fd, b.data + off, b.len - off);
        if (n > 0) { off += (size_t)n; continue; }
        if (n < 0 && errno == EAGAIN) return 0;   /* 背压：drop */
        return 1;                                  /* 错误：交由 ? 传播 -> 关闭 */
    }
    return 0;
}

static void rosoto_echo_serve(const char *addr,
                              void (*on_connect)(RosotoConn *),
                              int (*on_data)(RosotoConn *, RosotoBuf),
                              void (*on_close)(RosotoConn *),
                              int64_t max_conns, int64_t backlog, bool nodelay, bool reuse_port) {
    /* 解析 addr: host:port */
    char host[128] = "0.0.0.0";
    int port = 0;
    const char *colon = strrchr(addr, ':');
    if (colon) {
        size_t hl = (size_t)(colon - addr);
        if (hl >= sizeof(host)) hl = sizeof(host) - 1;
        memcpy(host, addr, hl);
        host[hl] = 0;
        port = atoi(colon + 1);
    }

    int lfd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK, 0);
    if (lfd < 0) { perror("socket"); exit(1); }
    int one = 1;
    setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    if (reuse_port) setsockopt(lfd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one));
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_port = htons((uint16_t)port);
    sa.sin_addr.s_addr = strcmp(host, "0.0.0.0") == 0 ? INADDR_ANY : inet_addr(host);
    if (bind(lfd, (struct sockaddr *)&sa, sizeof(sa)) < 0) { perror("bind"); exit(1); }
    if (listen(lfd, backlog > 0 ? (int)backlog : 1024) < 0) { perror("listen"); exit(1); }

    int ep = epoll_create1(0);
    if (ep < 0) { perror("epoll_create1"); exit(1); }
    struct epoll_event ev;
    memset(&ev, 0, sizeof(ev));
    ev.events = EPOLLIN;
    ev.data.fd = lfd;
    epoll_ctl(ep, EPOLL_CTL_ADD, lfd, &ev);

    RosotoConn **conns = calloc((size_t)ROSOTO_NET_MAX_CONNS, sizeof(RosotoConn *));
    int64_t nconns = 0;
    struct epoll_event events[512];
    char rbuf[ROSOTO_RECV_BUF];

    for (;;) {
        int n = epoll_wait(ep, events, 512, -1);
        for (int i = 0; i < n; i++) {
            int fd = events[i].data.fd;
            if (fd == lfd) {
                for (;;) {
                    int cfd = accept4(lfd, NULL, NULL, SOCK_NONBLOCK);
                    if (cfd < 0) break;
                    if (nconns >= max_conns || cfd >= ROSOTO_NET_MAX_CONNS) {
                        close(cfd);            /* 超出 [net] max_conns：fail-fast 拒绝 */
                        continue;
                    }
                    if (nodelay) setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
                    RosotoConn *c = (RosotoConn *)calloc(1, sizeof(RosotoConn));
                    c->fd = cfd;
                    struct sockaddr_in peer;
                    socklen_t pl = sizeof(peer);
                    if (getpeername(cfd, (struct sockaddr *)&peer, &pl) == 0)
                        snprintf(c->peer, sizeof(c->peer), "%s:%d",
                                 inet_ntoa(peer.sin_addr), ntohs(peer.sin_port));
                    else
                        snprintf(c->peer, sizeof(c->peer), "unknown");
                    conns[cfd] = c;
                    nconns++;
                    memset(&ev, 0, sizeof(ev));
                    ev.events = EPOLLIN;
                    ev.data.fd = cfd;
                    epoll_ctl(ep, EPOLL_CTL_ADD, cfd, &ev);
                    if (on_connect) on_connect(c);
                }
            } else {
                RosotoConn *c = conns[fd];
                if (!c) continue;
                ssize_t rn = read(fd, rbuf, sizeof(rbuf));
                if (rn <= 0) {
                    if (on_close) on_close(c);
                    epoll_ctl(ep, EPOLL_CTL_DEL, fd, NULL);
                    close(fd);
                    conns[fd] = NULL;
                    nconns--;
                    free(c);
                    continue;
                }
                RosotoBuf b = { rbuf, (size_t)rn };
                int action = on_data ? on_data(c, b) : NET_ACTION_CLOSE;
                if (action == NET_ACTION_CLOSE) {
                    if (on_close) on_close(c);
                    epoll_ctl(ep, EPOLL_CTL_DEL, fd, NULL);
                    close(fd);
                    conns[fd] = NULL;
                    nconns--;
                    free(c);
                }
            }
        }
    }
}
"""

# ---------------------------------------------------------------------------
# 5. 代码生成
# ---------------------------------------------------------------------------


class Codegen:
    def __init__(self, fns, cfg, structs=None, enums=None, decl_order=None):
        self.fns = fns
        self.cfg = cfg
        self.structs = structs or {}
        self.enums = enums or {}
        self.decl_order = decl_order or ([('struct', s) for s in self.structs]
                                         + [('enum', e) for e in self.enums])
        self.infer = Infer(fns, self.structs, self.enums)
        self.helpers = []      # parfor worker 等辅助定义
        self.uses_net = False
        self.pf_id = 0
        self.spawn_id = 0
        self.mid = 0           # match 临时变量计数
        self.threads = cfg["core"]["threads"] or os.cpu_count() or 1
        self.multicore = bool(cfg["core"]["multicore"]) and self.threads > 1

    # ---- 工具 ----
    def ctype(self, t):
        if t[0] == "chan":
            return "int64_t"
        if t[0] == "slice":
            return "RosotoBuf" if t[1] == ("named", "byte") else "void *"
        name = t[1]
        if name in self.structs or name in self.enums:
            return name
        return CTYPE.get(name, "int64_t")

    def struct_name_of(self, path):
        """结构体字面量路径 -> 结构体名；不是已声明的结构体返回 None"""
        name = path[-1]
        return name if name in self.structs else None

    def field_index(self, sname, fname):
        """返回 (下标, 字段类型元组)，找不到抛错"""
        for i, (n, t) in enumerate(self.structs[sname]):
            if n == fname:
                return i, t
        raise SyntaxError(f"结构体 {sname} 没有字段 {fname}")

    def struct_defn(self, sname):
        """struct 定义（嵌套结构体按声明顺序先行输出）"""
        if sname not in self.structs:
            raise SyntaxError(f"未声明的结构体 {sname}")
        body = "; ".join(f"{self.ctype(t)} {n}" for n, t in self.structs[sname])
        return f"typedef struct {{ {body}; }} {sname};"

    def enum_defn(self, ename):
        """enum 定义：tag 字 + 变体载荷 union（字段名即变体名）"""
        variants = self.enums[ename]
        if variants is None:
            raise SyntaxError(f"未声明的枚举 {ename}")
        body = "int64_t __tag;"
        payload = [(vn, vf) for vn, vf in variants if vf]
        if payload:
            uni = " ".join(
                f"struct {{ {'; '.join(f'{self.ctype(t)} {n}' for n, t in vf)}; }} {vn};"
                for vn, vf in payload)
            body += f" union {{ {uni} }} u;"
        return f"typedef struct {{ {body} }} {ename};"

    def enum_variant(self, ename, vname):
        """返回 (变体下标, 载荷字段列表)"""
        for i, (vn, vf) in enumerate(self.enums[ename]):
            if vn == vname:
                return i, vf
        raise SyntaxError(f"枚举 {ename} 没有变体 {vname}")

    def zero_of(self, ret_t):
        ct = self.ctype(ret_t)
        if ct == "void":
            return None
        if ct in ("const char *",):
            return "NULL"
        return "0"

    def cstr(self, s):
        out = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{out}"'

    # ---- 表达式 ----
    def gen_expr(self, e, env):
        k = e[0]
        if k == "num":
            return f"(int64_t)({e[1]})", "int64_t"
        if k == "str":
            return self.cstr(e[1]), "const char *"
        if k == "bool":
            return ("true" if e[1] else "false"), "bool"
        if k == "name":
            return e[1], env.get(e[1], "int64_t")
        if k == "path":
            p = e[1]
            if p[0] in env:
                # 头段是当前作用域的变量 -> 字段访问链 v.x.y
                obj = ("name", p[0])
                for seg in p[1:]:
                    obj = ("field", obj, seg)
                return self.gen_expr(obj, env)
            if p == ["net", "Action", "Keep"]:
                return "NET_ACTION_KEEP", "int"
            if p == ["net", "Action", "Close"]:
                return "NET_ACTION_CLOSE", "int"
            return p[-1], "int64_t"
        if k == "field":
            ocode, otype = self.gen_expr(e[1], env)
            st = self.infer.struct_of(otype)
            if st is None:
                raise SyntaxError(f"对非结构体表达式取字段 .{e[2]}")
            return f"({ocode}).{e[2]}", self.field_ctype(st, e[2])
        if k == "call":
            name = e[1][-1]
            if name == "print":
                code, t = self.gen_expr(e[2][0], env)
                if t.startswith("struct:"):
                    raise SyntaxError("print 暂不支持结构体；请打印具体字段")
                if t == "const char *":
                    return f"rosoto_print_str({code})", "void"
                if t == "bool":
                    return f"rosoto_print_bool({code})", "void"
                return f"rosoto_print_i64({code})", "void"
            if name == "cores":
                return "rosoto_cores()", "int64_t"
            if name == "assert":
                ccode, _ = self.gen_expr(e[2][0], env)
                msg = "(no message)"
                if len(e[2]) > 1 and e[2][1][0] == "str":
                    msg = e[2][1][1]
                return (f'rosoto_assert(({ccode}), "{msg}")', "void")
            if name == "join" and name not in self.infer.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("join(handle) 需要且只需要一个句柄")
                hcode, _ = self.gen_expr(e[2][0], env)
                return f"rosoto_join({hcode})", "int64_t"
            args = ", ".join(self.gen_expr(a, env)[0] for a in e[2])
            return f"{name}({args})", self.infer.fn_ret(name)
        if k == "spawn":
            return self.gen_spawn(e[1], env)
        if k == "chanopen":
            if len(e[2]) != 1:
                raise SyntaxError("chan[T].open(cap) 需要且只需要一个容量实参")
            cap, _ = self.gen_expr(e[2][0], env)
            return f"rosoto_chan_open({cap})", "int64_t"
        if k == "method":
            obj, m, args = e[1], e[2], e[3]
            ocode, otype = self.gen_expr(obj, env)
            if m in ("send", "recv"):
                if not (obj[0] == "name" and env.get("__chan__" + obj[1])):
                    raise SyntaxError(f".{m} 只能用于 chan 通道")
                if m == "send":
                    if len(args) != 1:
                        raise SyntaxError("ch.send(v) 需要一个实参")
                    acode, _ = self.gen_expr(args[0], env)
                    return f"rosoto_chan_send({ocode}, {acode})", "int64_t"
                return f"rosoto_chan_recv({ocode})", "int64_t"
            if m == "to_str":
                if otype == "const char *":
                    return ocode, "const char *"
                if otype == "bool":
                    return f"rosoto_bool_to_str({ocode})", "const char *"
                return f"rosoto_i64_to_str({ocode})", "const char *"
            if m == "write":
                self.uses_net = True
                bcode, _ = self.gen_expr(args[0], env)
                return f"rosoto_conn_write({ocode}, {bcode})", "int"
            if m == "peer_addr":
                self.uses_net = True
                return f"rosoto_conn_peer({ocode})", "const char *"
            if m == "serve":
                return self.gen_serve(obj, env), "void"
            raise SyntaxError(f"未知方法 .{m}")
        if k == "binop":
            op = e[1]
            lc, lt = self.gen_expr(e[2], env)
            rc, rt = self.gen_expr(e[3], env)
            if op == "+" and "const char *" in (lt, rt):
                return f"rosoto_concat({lc}, {rc})", "const char *"
            if op in ("==", "!=") and "const char *" in (lt, rt):
                # 字符串比较：内容相等（非指针）
                cmp = f"rosoto_str_eq({lc}, {rc})"
                return (f"({cmp})" if op == "==" else f"(!{cmp})"), "bool"
            return f"({lc} {op} {rc})", "bool" if op in ("==", "!=", "<", "<=", ">", ">=", "&&", "||") else "int64_t"
        if k == "unop":
            code, t = self.gen_expr(e[2], env)
            return f"({e[1]}{code})", "bool" if e[1] == "!" else t
        if k == "try":
            code, _ = self.gen_expr(e[1], env)
            return code, "int"
        if k == "structlit":
            sname = self.struct_name_of(e[1])
            if sname is None:
                return "<struct>", "struct:" + ".".join(e[1])
            parts = []
            for fname, fexpr in e[2].items():
                self.field_index(sname, fname)      # 字段名必须存在
                fcode, _ = self.gen_expr(fexpr, env)
                parts.append(f".{fname} = {fcode}")
            return f"(({sname}){{ {', '.join(parts)} }})", "struct:" + sname
        if k == "enumlit":
            return self.gen_enumlit(e, env)
        if k == "match":
            inner, res_var, res_type = self.gen_match(e, env, 1, None, as_expr=True)
            code = "({\n" + "\n".join(inner) + f"\n    {res_var};\n}})"
            return code, res_type
        raise SyntaxError(f"无法生成表达式: {e!r}")

    def gen_enumlit(self, e, env):
        """枚举构造 -> C 复合字面量 { .__tag = i, .u.Variant = { .f = ... } }"""
        path, fields = e[1], e[2]
        ename, vname = path[0], path[1]
        if ename not in self.enums:
            raise SyntaxError(f"未声明的枚举 {ename}")
        vidx, vfields = self.enum_variant(ename, vname)
        parts = [f".__tag = {vidx}"]
        if vfields:
            exprs = dict(fields)
            if set(exprs) != {f for f, _ in vfields}:
                raise SyntaxError(
                    f"{ename}.{vname} 构造需给出全部载荷字段 {[f for f, _ in vfields]}")
            inits = []
            for fname, ftype in vfields:
                fcode, _ = self.gen_expr(exprs[fname], env)
                inits.append(f".{fname} = {fcode}")
            parts.append(f".u.{vname} = {{ {', '.join(inits)} }}")
        return f"(({ename}){{ {', '.join(parts)} }})", "enum:" + ename

    def gen_match(self, e, env, ind, ret_t, as_expr):
        """match 降级：tag 比较链 + 每臂载荷绑定。
        返回 (内部行列表, 结果变量|None, 结果类型)；调用方负责外层括号/花括号。"""
        _, scrut, arms = e
        ename, plain, _wild = validate_match(arms, self.enums)
        scode, stype = self.gen_expr(scrut, env)
        sname = Infer.struct_of(stype)
        if sname not in self.enums:
            raise SyntaxError("match 的求值式必须是枚举类型")
        if ename is not None and ename != sname:
            raise SyntaxError(f"match 模式是 {ename}，求值式是 {sname}")
        if as_expr and any(body[0] != "expr" for _i, _n, body in plain):
            raise SyntaxError("match 表达式的臂必须是表达式；块臂请把 match 当语句使用")
        self.mid += 1
        mid = self.mid
        scr_var = f"_mS{mid}"
        res_var = f"_mV{mid}"
        pad = "    " * ind
        inner = [f"{pad}{sname} {scr_var} = {scode};"]
        res_type = None
        if as_expr:
            for idx, names, body in plain:
                if body[0] != "expr":
                    continue
                e2 = dict(env)
                if idx is not None:
                    _vn, vf = self.enums[sname][idx]
                    for i, b in enumerate(names):
                        if b is not None:
                            e2[b] = self.env_type(vf[i][1])
                res_type = self.gen_expr(body[1], e2)[1]
                break
            if res_type and (res_type.startswith("struct:") or res_type.startswith("enum:")):
                res_type = res_type.split(":", 1)[1]     # 聚合结果：剥离类型标记，用裸类型名
            res_type = res_type or "int64_t"
            if res_type in self.structs or res_type in self.enums:
                zero = "{0}"
            else:
                zero = "NULL" if res_type == "const char *" else "0"
            inner.append(f"{pad}{res_type} {res_var} = {zero};")
        first = True
        for idx, names, body in plain:
            vname, vfields = (None, [])
            if idx is not None:
                vname, vfields = self.enums[sname][idx]
            if idx is None:
                inner.append(f"{pad}else {{" if not first else f"{pad}{{")
            else:
                kw = "if" if first else "else if"
                inner.append(f"{pad}{kw} ({scr_var}.__tag == {idx}) {{")
            first = False
            e2 = dict(env)
            for i, b in enumerate(names):
                if b is None:
                    continue
                ftype = vfields[i][1]
                inner.append(f"{pad}    {self.ctype(ftype)} {b} = {scr_var}.u.{vname}.{vfields[i][0]};")
                e2[b] = self.env_type(ftype)
            if body[0] == "expr":
                bcode, _bt = self.gen_expr(body[1], e2)
                if as_expr:
                    inner.append(f"{pad}    {res_var} = {bcode};")
                else:
                    inner.append(f"{pad}    {bcode};")
            else:
                inner.append(self.gen_block(body[1], e2, ind + 1, ret_t))
            inner.append(f"{pad}}}")
        return inner, (res_var if as_expr else None), res_type

    def field_ctype(self, sname, fname):
        """字段在作用域里的类型标记（结构体字段是 'struct:Name'）"""
        _, ftype = self.field_index(sname, fname)
        return self.env_type(ftype)

    def env_type(self, t):
        """作用域里记录的类型标记：结构体 'struct:Name'、枚举 'enum:Name'，其余用 C 类型串"""
        if t[0] == "chan":
            return "int64_t"
        if t[0] == "named" and t[1] in self.structs:
            return "struct:" + t[1]
        if t[0] == "named" and t[1] in self.enums:
            return "enum:" + t[1]
        return self.ctype(t)

    def gen_serve(self, obj, env):
        """server.serve() -> rosoto_echo_serve(...)"""
        self.uses_net = True
        name = obj[1]  # ('name', var)
        rec = env.get("_struct_" + name)
        if rec is None:
            raise SyntaxError("serve() 只支持 net.TcpServer 结构体变量")
        fields = rec["fields"]

        def fget(key, default):
            return self.gen_expr(fields[key], env)[0] if key in fields else default

        addr = fget("addr", '"0.0.0.0:9000"')
        backlog = fget("backlog", "1024")
        max_conns = fget("max_conns", str(self.cfg["net"]["max_conns"]))
        nodelay = fget("nodelay", "true" if self.cfg["net"]["tcp_nodelay"] else "false")
        reuse_port = fget("reuse_port", "true" if self.cfg["net"]["reuse_port"] else "false")
        oc = fget("on_connect", "NULL")
        od = fget("on_data", "NULL")
        ocl = fget("on_close", "NULL")
        return (f"rosoto_echo_serve({addr}, {oc}, {od}, {ocl}, "
                f"{max_conns}, {backlog}, {nodelay}, {reuse_port})")

    # ---- 语句 ----
    def gen_block(self, stmts, env, ind, ret_t):
        out = []
        for s in stmts:
            out.append(self.gen_stmt(s, env, ind, ret_t))
        return "\n".join(out)

    def gen_stmt(self, s, env, ind, ret_t):
        pad = "    " * ind
        k = s[0]
        if k == "let":
            lit = s[3]
            if lit[0] == "structlit" and self.struct_name_of(lit[1]) is None:
                # net.TcpServer { ... }：字段展开为局部变量
                return self.gen_struct_let(s, env, ind)
            code, t = self.gen_expr(lit, env)
            if t.startswith("struct:"):
                t = t[7:]
            if t.startswith("enum:"):
                t = t[5:]
            env[s[2]] = ("struct:" + t) if t in self.structs else (("enum:" + t) if t in self.enums else t)
            decl = t if t in self.structs or t in self.enums else t
            if lit[0] == "chanopen":
                env["__chan__" + s[2]] = True
            elif lit[0] == "name" and env.get("__chan__" + lit[1]):
                env["__chan__" + s[2]] = True
            return f"{pad}{decl} {s[2]} = {code};"
        if k == "assign":
            code, t = self.gen_expr(s[3], env)
            return f"{pad}{s[1]} {s[2]} {code};"
        if k == "assign_field":
            lhs, op = s[1], s[2]
            lcode, ltype = self.gen_expr(lhs, env)
            rcode, _ = self.gen_expr(s[3], env)
            if ltype.startswith("struct:") and op == "=":
                # 结构体整体赋值：按值拷贝
                return f"{pad}{lcode} = {rcode};"
            return f"{pad}{lcode} {op} {rcode};"
        if k == "break":
            return f"{pad}break;"
        if k == "continue":
            return f"{pad}continue;"
        if k == "match_stmt":
            inner, _res, _rt = self.gen_match(s[1], env, ind, ret_t, as_expr=False)
            return "\n".join([f"{pad}{{", *inner, f"{pad}}}"])
        if k == "arena":
            # C 后端的字符串走轮转静态缓冲，没有堆分配；arena 在这里是纯作用域。
            # 语义说明见 SPEC §6：native 后端会真正回卷 bump 指针。
            return "\n".join([f"{pad}{{ /* arena: 块内分配随块结束回收 */",
                              self.gen_block(s[1], dict(env), ind + 1, ret_t),
                              f"{pad}}}"])
        if k == "if":
            cond, _ = self.gen_expr(s[1], env)
            out = [f"{pad}if ({cond}) {{",
                   self.gen_block(s[2], dict(env), ind + 1, ret_t),
                   f"{pad}}}"]
            if s[3]:
                out += [f"{pad}else {{",
                        self.gen_block(s[3], dict(env), ind + 1, ret_t),
                        f"{pad}}}"]
            return "\n".join(out)
        if k == "while":
            cond, _ = self.gen_expr(s[1], env)
            return "\n".join([f"{pad}while ({cond}) {{",
                              self.gen_block(s[2], dict(env), ind + 1, ret_t),
                              f"{pad}}}"])
        if k == "for":
            lo, _ = self.gen_expr(s[2], env)
            hi, _ = self.gen_expr(s[3], env)
            e2 = dict(env)
            e2[s[1]] = "int64_t"
            return "\n".join([
                f"{pad}{{ int64_t _lo = {lo}; int64_t _hi = {hi};",
                f"{pad}for (int64_t {s[1]} = _lo; {s[1]} < _hi; {s[1]}++) {{",
                self.gen_block(s[4], e2, ind + 1, ret_t),
                f"{pad}}}",
                f"{pad}}}"])
        if k == "parfor":
            return self.gen_parfor(s, env, ind, ret_t)
        if k == "return":
            if s[1] is None:
                return f"{pad}return;"
            code, _ = self.gen_expr(s[1], env)
            return f"{pad}return {code};"
        if k == "expr":
            e = s[1]
            if e[0] == "try":
                code, _ = self.gen_expr(e[1], env)
                zero = self.zero_of(ret_t)
                if zero is None:
                    return f"{pad}if ({code} != 0) return;"
                return f"{pad}if ({code} != 0) return {zero};"
            code, _ = self.gen_expr(e, env)
            return f"{pad}{code};"
        raise SyntaxError(f"未知语句 {s!r}")

    def gen_struct_let(self, s, env, ind):
        """let server = net.TcpServer { ... } -> 局部变量 + 记录字段"""
        pad = " " * (4 * ind)
        _, _, var, lit = s
        path, fields = lit[1], lit[2]
        if path != ["net", "TcpServer"]:
            raise SyntaxError(f"暂不支持的结构体 {path}")
        self.uses_net = True
        out = [f"{pad}/* struct net.TcpServer -> {var} */"]
        rec_fields = {}
        for fname, fexpr in fields.items():
            fcode, ftype = self.gen_expr(fexpr, env)
            ctype = ftype if ftype.startswith("struct") is False else "int64_t"
            if ftype == "struct:" + ".".join(path):
                ctype = "int64_t"
            cname = f"{var}_{fname}"
            # 函数引用 -> 函数指针变量
            if fexpr[0] == "name" and fexpr[1] in self.infer.fns:
                fn = self.infer.fns[fexpr[1]]
                ptypes = [self.ctype(p[1]) for p in fn["params"]]
                rtype = self.ctype(fn["ret"])
                out.append(f"{pad}{rtype} (*{cname})({', '.join(ptypes)}) = {fexpr[1]};")
            else:
                out.append(f"{pad}{ctype} {cname} = {fcode};")
            rec_fields[fname] = ("name", cname)
        env["_struct_" + var] = {"path": path, "fields": rec_fields}
        env[var] = "struct:" + ".".join(path)
        return "\n".join(out)

    # ---- parfor ----
    def gen_parfor(self, s, env, ind, ret_t):
        _, var, lo_e, hi_e, body = s
        lo, _ = self.gen_expr(lo_e, env)
        hi, _ = self.gen_expr(hi_e, env)

        # 收集自由变量 / 归约变量
        declared, assigned, referenced = set(), set(), set()
        walk_stmts(body, declared, assigned, referenced)
        declared.add(var)
        fns = set(self.infer.fns) | {"print", "cores", "assert"}
        captured = sorted((referenced - declared) - fns)

        # 归约变量 = 被赋值(+=)且来自外部作用域
        reductions, illegal = [], []
        for name in sorted(assigned & set(captured)):
            if self._assign_op(body, name) == "+=":
                reductions.append(name)
            else:
                illegal.append(name)
        if illegal:
            raise SyntaxError(f"parfor 中外部变量 {illegal} 仅支持 +=（归约）赋值")
        captured_ro = [c for c in captured if c not in reductions]

        pad = "    " * ind
        if not self.multicore:
            # ---- 单核降级：确定性串行（Rosoto.toml [core] multicore = false）----
            e2 = dict(env)
            e2[var] = "int64_t"
            out = [f"{pad}/* parfor -> 串行降级（Rosoto.toml: multicore=false, threads={self.threads}） */"]
            out += [f"{pad}{{ int64_t _lo = {lo}; int64_t _hi = {hi};",
                    f"{pad}for (int64_t {var} = _lo; {var} < _hi; {var}++) {{",
                    self.gen_block(body, e2, ind + 1, ret_t),
                    f"{pad}}}",
                    f"{pad}}}"]
            return "\n".join(out)

        # ---- 多核：pthread 分块 + 归约 ----
        pid = self.pf_id
        self.pf_id += 1
        tname = f"pf{pid}"
        e2 = dict(env)
        e2[var] = "int64_t"
        for r in reductions:
            e2[r] = "int64_t"
        for c in captured_ro:
            e2.setdefault(c, env.get(c, "int64_t"))

        # worker 定义（放入 helpers，先于 main 生成）
        w = [f"/* parfor#{pid} worker */",
             f"typedef struct {{",
             f"    int64_t lo, hi; int tid;"]
        for c in captured_ro:
            ct = env.get(c, "int64_t")
            w.append(f"    {ct} *v_{c};")
        for r in reductions:
            w.append(f"    int64_t *out_{r};")
        w.append(f"}} {tname}_args;")
        w.append(f"static void *{tname}_worker(void *p) {{")
        w.append(f"    {tname}_args *a = ({tname}_args *)p;")
        for c in captured_ro:
            ct = env.get(c, "int64_t")
            w.append(f"    {ct} {c} = *a->v_{c};")
        for r in reductions:
            w.append(f"    int64_t {r} = 0;")
        w.append(f"    for (int64_t {var} = a->lo; {var} < a->hi; {var}++) {{")
        w.append(self.gen_block(body, e2, 2, ret_t))
        w.append(f"    }}")
        for r in reductions:
            w.append(f"    a->out_{r}[a->tid] = {r};")
        w.append(f"    return NULL;")
        w.append(f"}}")
        self.helpers.append("\n".join(w))

        # 驱动代码
        out = [f"{pad}/* parfor#{pid}: 多核分块并行（threads={self.threads}） */",
               f"{pad}{{",
               f"{pad}    int64_t {tname}_lo = {lo}, {tname}_hi = {hi};",
               f"{pad}    int64_t {tname}_span = {tname}_hi - {tname}_lo;",
               f"{pad}    if ({tname}_span > 0) {{",
               f"{pad}        int {tname}_T = {self.threads};",
               f"{pad}        if ((int64_t){tname}_T > {tname}_span) {tname}_T = (int){tname}_span;",
               f"{pad}        pthread_t {tname}_th[{self.threads}];",
               f"{pad}        {tname}_args {tname}_a[{self.threads}];"]
        for r in reductions:
            out.append(f"{pad}        int64_t {tname}_out_{r}[{self.threads}];")
            out.append(f"{pad}        memset({tname}_out_{r}, 0, sizeof({tname}_out_{r}));")
        out += [f"{pad}        int64_t {tname}_chunk = ({tname}_span + {tname}_T - 1) / {tname}_T;",
                f"{pad}        for (int {tname}_t = 0; {tname}_t < {tname}_T; {tname}_t++) {{",
                f"{pad}            {tname}_a[{tname}_t].lo = {tname}_lo + (int64_t){tname}_t * {tname}_chunk;",
                f"{pad}            {tname}_a[{tname}_t].hi = {tname}_lo + (int64_t)({tname}_t + 1) * {tname}_chunk;",
                f"{pad}            if ({tname}_a[{tname}_t].hi > {tname}_hi) {tname}_a[{tname}_t].hi = {tname}_hi;",
                f"{pad}            {tname}_a[{tname}_t].tid = {tname}_t;"]
        for c in captured_ro:
            out.append(f"{pad}            {tname}_a[{tname}_t].v_{c} = &{c};")
        for r in reductions:
            out.append(f"{pad}            {tname}_a[{tname}_t].out_{r} = {tname}_out_{r};")
        out += [f"{pad}            pthread_create(&{tname}_th[{tname}_t], NULL, {tname}_worker, &{tname}_a[{tname}_t]);",
                f"{pad}        }}",
                f"{pad}        for (int {tname}_t = 0; {tname}_t < {tname}_T; {tname}_t++)",
                f"{pad}            pthread_join({tname}_th[{tname}_t], NULL);"]
        for r in reductions:
            out.append(f"{pad}        for (int {tname}_t = 0; {tname}_t < {tname}_T; {tname}_t++)")
            out.append(f"{pad}            {r} += {tname}_out_{r}[{tname}_t];")
        out += [f"{pad}    }}",
                f"{pad}}}"]
        return "\n".join(out)

    # ---- spawn / join（任务并行，SPEC §4）----
    def gen_spawn(self, call, env):
        """`spawn f(args)` -> 任务句柄（int64）。

        v0.4 约束（明确报错，不静默降级）：
          - 目标必须是用户函数，实参/返回值只支持 int / bool / str 标量；
          - 结构体/枚举按值跨线程涉及生命周期，留到 arena/所有权落地后再开；
          - `[core] multicore = false` 时同步执行（句柄 rec[0]=0，join 直接取结果）。
        """
        name = call[1][-1]
        if name not in self.infer.fns:
            raise SyntaxError(f"spawn 的目标必须是用户函数：{name}")
        fn = self.infer.fns[name]
        ret = fn["ret"]
        if ret[0] == "named" and (ret[1] in self.structs or ret[1] in self.enums):
            raise SyntaxError("spawn 暂不支持结构体/枚举返回值")
        if not (ret[1] in ("void", "bool", "int", "i64", "i32", "u64",
                           "u32", "i16", "u16", "i8", "u8")):
            raise SyntaxError(f"spawn 返回值暂支持 int/bool/void，得到 {ret[1]}")
        params = fn["params"]
        args = call[2]
        if len(args) != len(params):
            raise SyntaxError(f"{name} 需要 {len(params)} 个实参，spawn 给了 {len(args)}")
        for pname, ptype in params:
            if ptype[0] == "named" and (ptype[1] in self.structs or ptype[1] in self.enums):
                raise SyntaxError(f"spawn 实参 {pname} 暂不支持结构体/枚举")

        sid = self.spawn_id
        self.spawn_id += 1
        tname = f"sp{sid}"
        ctypes_ = [self.ctype(t) for _n, t in params]
        fields = "; ".join(f"    {ct} a{i};" for i, ct in enumerate(ctypes_))
        sig = ", ".join(f"{ct} p{i}" for i, ct in enumerate(ctypes_)) or "void"
        names = ", ".join(f"a->a{i}" for i in range(len(ctypes_)))
        if ret == ("named", "void"):
            body = f"    {name}({names});\n    a->res = 0;"
        else:
            body = f"    a->res = (int64_t)({name}({names}));"
        h = [f"/* spawn#{sid}: {name} */",
             f"typedef struct {{ int64_t res; {fields} }} {tname}_args;",
             f"static void *{tname}_worker(void *p) {{",
             f"    {tname}_args *a = ({tname}_args *)p;",
             body,
             "    return NULL;",
             "}",
             f"static int64_t {tname}({sig}) {{",
             f"    {tname}_args *a = ({tname}_args *)malloc(sizeof({tname}_args));",
             "    a->res = 0;"]
        for i, (_n, pt) in enumerate(params):
            # helper 内用的是形参 p0..；实参表达式只在调用点求值一次
            h.append(f"    a->a{i} = p{i};")
        h += ["    int64_t *rec = (int64_t *)malloc(2 * sizeof(int64_t));",
              "    rec[1] = (int64_t)(intptr_t)a;",
              "#if ROSOTO_MULTICORE",
              "    pthread_t t;",
              f"    pthread_create(&t, NULL, {tname}_worker, a);",
              "    rec[0] = (int64_t)t;",
              "#else",
              f"    {tname}_worker(a);",
              "    rec[0] = 0;",
              "#endif",
              "    return (int64_t)(intptr_t)rec;",
              "}"]
        self.helpers.append("\n".join(h))
        arg_codes = [self.gen_expr(a, env)[0] for a in args]
        return f"{tname}({', '.join(arg_codes)})", "int64_t"

    def _assign_op(self, stmts, name):
        for s in stmts:
            if s[0] == "assign" and s[1] == name:
                return s[2]
            if s[0] in ("if",):
                for blk in (s[2], s[3] or []):
                    r = self._assign_op(blk, name)
                    if r:
                        return r
            if s[0] in ("while",):
                r = self._assign_op(s[2], name)
                if r:
                    return r
            if s[0] in ("for", "parfor"):
                r = self._assign_op(s[4], name)
                if r:
                    return r
        return None

    # ---- 程序 ----
    def gen_program(self):
        mod = PROGRAM[0] if PROGRAM else None
        fns = self.fns
        # 宏定义最先（net 运行时按需取用配置值）
        lines = ["/* Generated by Rosoto transpiler v0.1 */",
                 "#define _GNU_SOURCE",
                 f"#define ROSOTO_THREADS {self.threads}",
                 f"#define ROSOTO_MULTICORE {1 if self.multicore else 0}",
                 f"#define ROSOTO_NET_MAX_CONNS {int(self.cfg['net']['max_conns'])}",
                 f"#define ROSOTO_RECV_BUF {int(self.cfg['net']['recv_buffer'])}",
                 "#include <unistd.h>",
                 "#include <pthread.h>",
                 CORE_RUNTIME]
        if self.any_net_usage():
            lines.append(NET_RUNTIME)
        lines.append("")

        # 用户结构体/枚举定义（按声明顺序输出，嵌套类型先声明）
        for kind, name in self.decl_order:
            lines.append(self.struct_defn(name) if kind == "struct" else self.enum_defn(name))
        if self.decl_order:
            lines.append("")

        # 前向声明
        for f in fns:
            params = ", ".join(f"{self.ctype(t)} {n}" for n, t in f["params"]) or "void"
            lines.append(f"static {self.ctype(f['ret'])} {f['name']}({params});")
        lines.append("")

        bodies = []
        for f in fns:
            env = {n: self.env_type(t) for n, t in f["params"]}
            for n, t in f["params"]:
                if t[0] == "chan":
                    env["__chan__" + n] = True
            body = self.gen_block(f["body"], env, 1, f["ret"])
            params = ", ".join(f"{self.ctype(t)} {n}" for n, t in f["params"]) or "void"
            bodies.append(f"static {self.ctype(f['ret'])} {f['name']}({params}) {{\n{body}\n}}")

        if self.helpers:
            lines.append("\n".join(self.helpers))
            lines.append("")
        lines += bodies
        has_main = any(f["name"] == "rosoto_main" for f in fns)
        lines += ["int main(void) {",
                  "    rosoto_main();" if has_main else "    /* no main */",
                  "    return 0;", "}"]
        return "\n".join(lines)

    def any_net_usage(self):
        for f in self.fns:
            d, a, r = set(), set(), set()
            walk_stmts(f["body"], d, a, r)
            if "net" in r or any(x.startswith("net") for x in r):
                return True
            for s in f["body"]:
                if s[0] == "expr" and s[1][0] in ("path",) and s[1][1][0] == "net":
                    return True
        return False


# ---- AST 遍历辅助（自由变量/赋值收集）----

def walk_expr(e, declared, assigned, referenced):
    if not isinstance(e, tuple):
        return
    k = e[0]
    if k == "name":
        referenced.add(e[1])
    elif k == "path":
        referenced.update(e[1])
    elif k == "call":
        referenced.update(e[1])
        for a in e[2]:
            walk_expr(a, declared, assigned, referenced)
    elif k == "method":
        walk_expr(e[1], declared, assigned, referenced)
        for a in e[3]:
            walk_expr(a, declared, assigned, referenced)
    elif k == "binop":
        walk_expr(e[2], declared, assigned, referenced)
        walk_expr(e[3], declared, assigned, referenced)
    elif k == "unop":
        walk_expr(e[2], declared, assigned, referenced)
    elif k == "try":
        walk_expr(e[1], declared, assigned, referenced)
    elif k == "spawn":
        walk_expr(e[1], declared, assigned, referenced)
    elif k == "chanopen":
        for a in e[2]:
            walk_expr(a, declared, assigned, referenced)
    elif k == "structlit":
        referenced.update(e[1])
        for v in e[2].values():
            walk_expr(v, declared, assigned, referenced)
    elif k == "enumlit":
        for _n, v in e[2]:
            walk_expr(v, declared, assigned, referenced)
    elif k == "match":
        walk_expr(e[1], declared, assigned, referenced)
        for pat, body in e[2]:
            if pat[0] == "pat":
                declared.update(b for b in pat[2] if b)
            if body[0] == "expr":
                walk_expr(body[1], declared, assigned, referenced)
            else:
                walk_stmts(body[1], declared, assigned, referenced)
    elif k == "field":
        walk_expr(e[1], declared, assigned, referenced)


def lvalue_head(e):
    """左值链的头变量名：v.x.y -> 'v'；找不到返回 None"""
    while isinstance(e, tuple) and e[0] == "field":
        e = e[1]
    if isinstance(e, tuple) and e[0] == "path":
        return e[1][0] if e[1] else None
    if isinstance(e, tuple) and e[0] == "name":
        return e[1]
    return None


def walk_stmts(stmts, declared, assigned, referenced):
    for s in stmts:
        k = s[0]
        if k == "let":
            walk_expr(s[3], declared, assigned, referenced)
            declared.add(s[2])
        elif k == "assign":
            walk_expr(s[3], declared, assigned, referenced)
            assigned.add(s[1])
            referenced.add(s[1])   # 读-改-写：目标同时是引用（parfor 归约识别用）
        elif k == "assign_field":
            walk_expr(s[1], declared, assigned, referenced)
            walk_expr(s[3], declared, assigned, referenced)
            head = lvalue_head(s[1])
            if head:
                assigned.add(head)
                referenced.add(head)
        elif k in ("break", "continue"):
            pass
        elif k == "match_stmt":
            walk_expr(s[1], declared, assigned, referenced)
        elif k == "arena":
            walk_stmts(s[1], declared, assigned, referenced)
        elif k == "if":
            walk_expr(s[1], declared, assigned, referenced)
            walk_stmts(s[2], declared, assigned, referenced)
            if s[3]:
                walk_stmts(s[3], declared, assigned, referenced)
        elif k == "while":
            walk_expr(s[1], declared, assigned, referenced)
            walk_stmts(s[2], declared, assigned, referenced)
        elif k in ("for", "parfor"):
            walk_expr(s[2], declared, assigned, referenced)
            walk_expr(s[3], declared, assigned, referenced)
            declared.add(s[1])
            walk_stmts(s[4], declared, assigned, referenced)
        elif k == "return":
            if s[1]:
                walk_expr(s[1], declared, assigned, referenced)
        elif k == "expr":
            walk_expr(s[1], declared, assigned, referenced)


# ---------------------------------------------------------------------------
# 6. 驱动
# ---------------------------------------------------------------------------

PROGRAM = None


def transpile(src_path):
    global PROGRAM
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    cfg = load_config(src_path)
    mod, imports, fns_ast, tests, structs, enums, decl_order = parse_source(src)
    PROGRAM = (mod, imports, fns_ast, tests)
    fns_ast = with_test_runner(fns_ast, tests)
    # 用户 main 与 C main 区分：编译为 rosoto_main
    for f in fns_ast:
        if f["name"] == "main":
            f["name"] = "rosoto_main"
    cg = Codegen(fns_ast, cfg, structs, enums, decl_order)
    c_code = cg.gen_program()
    return c_code, cfg


def main():
    ap = argparse.ArgumentParser(description="Rosoto transpiler (Rosoto -> C99)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("src")
    b.add_argument("-o", "--out", default=None)
    b.add_argument("--cc", action="store_true", help="转译后同时调用 cc 编译原生二进制")
    r = sub.add_parser("run")
    r.add_argument("src")
    r.add_argument("args", nargs="*")
    args = ap.parse_args()

    c_code, cfg = transpile(args.src)
    base = os.path.splitext(os.path.basename(args.src))[0]
    out_c = args.out if (args.cmd == "build" and args.out) else os.path.join("build", base + ".c")
    os.makedirs(os.path.dirname(out_c) or ".", exist_ok=True)
    with open(out_c, "w", encoding="utf-8") as f:
        f.write(c_code)
    print(f"[rosoto] {args.src} -> {out_c}")
    print(f"[rosoto] config: {cfg['_path'] or '(默认)'} | "
          f"multicore={cfg['core']['multicore']} threads={cfg['core']['threads'] or 'auto'}")

    if args.cmd == "build" and not args.cc:
        return

    bin_path = os.path.join("build", base)
    cc_cmd = ["cc", "-std=gnu11", "-O2", "-pthread", "-o", bin_path, out_c]
    print("[rosoto] cc:", " ".join(cc_cmd))
    subprocess.check_call(cc_cmd)
    if args.cmd == "run":
        print(f"[rosoto] exec {bin_path}")
        subprocess.check_call([os.path.abspath(bin_path)] + args.args)


if __name__ == "__main__":
    main()
