#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara -> C99 转译器原型 (v0.1)
================================
把 Quelmara 源码 (.qma) 转译为 C99，再交给任意 C 编译器原生编译。

已实现（对应 SPEC.md §9）：
  - module / import / fn / let / let mut / if-else / while / for-in-range / return
  - int / bool / str / []byte / net.Conn 类型与表达式全集（含字符串 + 拼接）
  - parfor：多核 pthread 分块并行 + reduction 归约
      * 根目录 Quelmara.toml [core] multicore = false  -> 编译期降级为串行
      * [core] threads = 0 (自动) / >0 (精确线程数)
  - net.TcpServer { ... } + server.serve()：epoll 非阻塞并发 echo 运行时
      * [net] max_conns / recv_buffer 等资源上限注入编译产物

用法：
  python3 tools/stage0/qlm.py build examples/hello.qma -o build/hello.c
  python3 tools/stage0/qlm.py run   examples/hello.qma
"""

import argparse
import os
import struct
import subprocess
import sys
import tomllib

# ---------------------------------------------------------------------------
# 0. 配置文件 Quelmara.toml（项目根目录，唯一全局资源开关）
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "core": {"multicore": True, "threads": 0, "affinity": "none", "preempt": True},
    "src": {"lib": "src/lib", "ref": "src/ref", "asset": "src/asset"},
    "net": {"backend": "auto", "io_threads": 0, "max_conns": 1000000,
            "recv_buffer": 4096, "send_buffer": 4096, "tcp_nodelay": True,
            "reuse_port": True, "backpressure": "drop"},
    "memory": {"arena_default": False, "heap_limit_mb": 512},
    "build": {"opt": "speed", "lto": True, "target": "native",
              "bounds_check": True},
}

# 文件命名契约（唯一权威，见 docs/EXTENSIONS.md）
CONFIG_NAME = "Quelmara.toml"
SRC_EXT = ".qma"          # Quelmara Module：唯一源码扩展名
LEGACY_EXT = ".ros"       # 已废弃，硬切：只用于给出迁移提示  # legacy-ok


def require_source(path):
    """校验源码扩展名。.ros 硬切，给出可直接执行的迁移命令。"""  # legacy-ok
    ext = os.path.splitext(path)[1].lower()
    if ext == LEGACY_EXT:
        new = path[:-len(LEGACY_EXT)] + SRC_EXT
        sys.stderr.write(
            f"[qlm] 错误：{path} 使用已废弃的 .ros 扩展名。\n"  # legacy-ok
            f"      Quelmara 源码扩展名为 {SRC_EXT}，请执行：\n"
            f"      git mv {path} {new}\n")
        raise SystemExit(2)
    if ext != SRC_EXT:
        sys.stderr.write(
            f"[qlm] 错误：{path} 不是 Quelmara 源码（期望 {SRC_EXT}）。\n")
        raise SystemExit(2)
    return path


def find_config(src_path):
    """从源文件目录向上（以及 cwd）查找 Quelmara.toml"""
    candidates = []
    d = os.path.dirname(os.path.abspath(src_path))
    while True:
        candidates.append(os.path.join(d, CONFIG_NAME))
        if d == os.path.dirname(d):
            break
        d = os.path.dirname(d)
    candidates.append(os.path.join(os.getcwd(), CONFIG_NAME))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def find_legacy_config(src_path):
    # legacy-ok:begin
    """查找遗留的 Rosoto.toml（只用于给出迁移提示，不参与配置加载）"""
    d = os.path.dirname(os.path.abspath(src_path))
    while True:
        c = os.path.join(d, "Rosoto.toml")
        if os.path.isfile(c):
            return c
        if d == os.path.dirname(d):
            break
        d = os.path.dirname(d)
    c = os.path.join(os.getcwd(), "Rosoto.toml")
    return c if os.path.isfile(c) else None
    # legacy-ok:end


def load_config(src_path):
    cfg = {k: dict(v) for k, v in DEFAULT_CONFIG.items()}
    path = find_config(src_path)
    if path is None:
        legacy = find_legacy_config(src_path)
        if legacy:
            sys.stderr.write(
                f"[qlm] 错误：发现旧配置 {legacy}，Quelmara 只读取 {CONFIG_NAME}。\n"
                f"      请执行：git mv {legacy} {os.path.join(os.path.dirname(legacy), CONFIG_NAME)}\n")
            raise SystemExit(2)
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

KEYWORDS = {"fn", "let", "mut", "if", "else", "while", "for", "parfor", "rc",
            "interface", "impl",
            "return", "module", "import", "true", "false", "test",
            "break", "continue", "defer", "struct", "enum", "match",
            "arena", "spawn", "chan", "option", "result", "map", "select",
            "const", "vec"}

FOUR_CHAR = {">>>="}
THREE_CHAR = {"<<=", ">>=", ">>>"}
TWO_CHAR = {"->", "==", "!=", "<=", ">=", "&&", "||", "+=", "-=", "*=", "/=", "..", "=>",
            "<<", ">>", "&=", "|=", "^=", "%="}
ONE_CHAR = "(){}[],:.=<>+-*/%!?@&|^~"

# 闭包值的字段表（v1.95）：word0 = 代码地址，word1 = 捕获环境指针（0 = 无捕获）。
# 与接口值 {data, vt} 同构——两字聚合，拷贝/传参/返回全走既有聚合 ABI。
CLOSURE_FIELDS = (("code", ("named", "int")), ("env", ("named", "int")))

SYMBOLS = sorted(FOUR_CHAR | THREE_CHAR | TWO_CHAR | set(ONE_CHAR), key=len, reverse=True)


class Tok:
    __slots__ = ("kind", "val", "line")

    def __init__(self, kind, val, line):
        self.kind, self.val, self.line = kind, val, line

    def __repr__(self):
        return f"{self.kind}({self.val!r})"


# v3.33：`read_source` 抽到独立的 `qlm_src` 模块（零依赖），
# 让 qlm_doc / qlm_fmt / qlm_fuzz / qlm_dbinfo / qlm_dbg / qlm_cli
# 都能用上，而不必为一个读文件函数去 import 整个编译器。
# 这里保留同名别名，老调用点与 `qlm.read_source` 都不受影响。
from qlm_src import read_source  # noqa: E402,F401
def tokenize(src, keep_comments=False):
    """词法分析。keep_comments=True 时保留注释记号（供 `quelmara fmt` 使用，
    格式化器必须能原样保留注释，否则会静默删掉用户文档）。"""
    toks, i, line, n = [], 0, 1, len(src)
    while i < n:
        c = src[i]
        # 插值字符串 f"..."（v1.61）：吞掉前缀 f，按普通字符串扫描，
        # 记号种类记 FSTR。放在标识符分支之前，`f` 作变量名不受影响。
        fstr = False
        if c == "f" and i + 1 < n and src[i + 1] == '"':
            fstr = True
            i += 1
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
        if c.isdigit() and i + 1 < n and src[i] == "0" and src[i + 1] in "xXbBoO":
            # 0x / 0b / 0o 字面量（编译器写指令编码必须要有十六进制）
            base = {"x": 16, "b": 2, "o": 8}[src[i + 1].lower()]
            ok = "0123456789abcdefABCDEF" if base == 16 else (
                "01" if base == 2 else "01234567")
            j = i + 2
            while j < n and (src[j] in ok or src[j] == "_"):
                j += 1
            if j == i + 2:
                raise SyntaxError(f"line {line}: {src[i:i + 2]} 后面缺少数字")
            toks.append(Tok("INT", int(src[i + 2:j].replace("_", ""), base), line))
            i = j
            continue
        if c.isdigit():
            j = i
            while j < n and (src[j].isdigit() or src[j] == "_"):
                j += 1
            # 浮点字面量：小数点后必须跟数字（`0..n` 的 `..` 不受影响）
            is_float = False
            if j + 1 < n and src[j] == "." and src[j + 1].isdigit():
                is_float = True
                j += 1
                while j < n and (src[j].isdigit() or src[j] == "_"):
                    j += 1
            # 指数部分：e/E 后可跟 +/-，再必须跟数字（`1e` 不吞进标识符）
            if j < n and src[j] in "eE":
                k2 = j + 1
                if k2 < n and src[k2] in "+-":
                    k2 += 1
                if k2 < n and src[k2].isdigit():
                    is_float = True
                    j = k2
                    while j < n and (src[j].isdigit() or src[j] == "_"):
                        j += 1
            text = src[i:j].replace("_", "")
            if is_float:
                # `f` 后缀 = f32（单精度）；默认 f64
                width = "f64"
                if j < n and src[j] == "f" and not (
                        j + 1 < n and (src[j + 1].isalnum() or src[j + 1] == "_")):
                    width = "f32"
                    j += 1
                toks.append(Tok("FLOAT", (float(text), width), line))
            else:
                toks.append(Tok("INT", int(text), line))
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
                    # v1.5：补 \r \0 \a \b \f \v 与 \xNN —— 网络协议
                    # （HTTP/1.1 的 CRLF、SSE、WebSocket 帧）必须能写字面量，
                    # 否则 \r 会被当成字母 r（此前 "GET / HTTP/1.1\r\n" 静默错位）。
                    if esc == "x" and j + 3 < n:
                        try:
                            b = int(src[j + 2:j + 4], 16)
                            # ⚠ \xNN 是**原始字节**，不是 Unicode 码点。
                            # 之前 buf.append(chr(b)) 让 \xe4 变成 U+00E4，
                            # 再 encode("utf-8") 就成 C3 A4（2 字节）——
                            # 二进制协议/哈希实现全被拖坏（b2 误编译）。
                            # 用 surrogateescape 区（U+DC80..U+DCFF）承载
                            # 原始字节，发射端 encode("utf-8", "surrogateescape")
                            # 原样还原成单字节。
                            buf.append(chr(b) if b < 0x80 else chr(0xDC00 + b))
                            j += 4
                            continue
                        except ValueError:
                            pass
                    buf.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0",
                                "a": "\a", "b": "\b", "f": "\f", "v": "\v",
                                '"': '"', "\\": "\\", "'": "'"}.get(esc, esc))
                    j += 2
                else:
                    if src[j] == "\n":
                        line += 1
                    buf.append(src[j])
                    j += 1
            if j >= n:
                raise SyntaxError(f"line {line}: 字符串未闭合")
            toks.append(Tok("FSTR" if fstr else "STR", "".join(buf), line))
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
# 1b. doc comment（`///` / `//!`）—— 语言层语法的唯一实现（v1.92）
#
# 设计取舍：doc comment **不进记号流**。词法上它与 `//` 一样被丢弃，语法
# 分析器看不到它；前端用本节的扫描器按行把文档挂到声明上（f["doc"] /
# Parser.type_docs）。理由：
#   * lexdiff / parsediff 的对拍契约是"记号序列 + 声明级 AST"，把文档塞进
#     记号流会让两份实现同时改，收益为零（文档不参与语义）；
#   * 文档是**声明级**事实，按行号关联比按记号关联更直接（声明行号本来
#     就在 f["line"] 里）。
# 语法规则见 docs/02-language.md §2.4；消费方见 tools/stage0/qlm_doc.py。
# ---------------------------------------------------------------------------

_DOC_KINDS = ("fn", "struct", "enum", "interface")


def _doc_text(rest):
    """`///` 之后的部分 -> 文档文本：剥一个前导空格与行尾 CR。"""
    if rest.startswith(" "):
        rest = rest[1:]
    return rest.rstrip("\r")


def _decl_head(s):
    """顶层声明行 -> (kind, name, is_pub)；不是声明返回 None。

    只认行首写法（无缩进由调用方保证）：`[pub] [const] fn|struct|enum|interface`。
    """
    pub = False
    if s.startswith("pub "):
        pub, s = True, s[4:]
    if s.startswith("const "):
        s = s[6:]
    for kind in _DOC_KINDS:
        if s.startswith(kind + " "):
            rest = s[len(kind) + 1:]
            j = 0
            while j < len(rest) and (rest[j].isalnum() or rest[j] == "_"):
                j += 1
            if j:
                return kind, rest[:j], pub
            return None
    return None


def scan_doc_comments(src):
    """扫描 doc comment -> (module_doc, blocks, orphans)。

    module_doc: `//!` 行文本列表（只认文件开头、代码之前的连续块）
    blocks:     [(声明行号, kind, name, is_pub, [文档行])]，按出现顺序
    orphans:    [(行号, 原因)] —— 写了 `///` 却没挂上声明的块

    规则（与 02-language.md §2.4 一一对应）：
      * `///` 必须**紧贴**下一行的顶层声明；空行、`//` 注释或其它代码即脱离；
      * 顶层的 `@注解` 行不算脱离（`///` + `@derive` + `pub struct` 合法）；
      * `////`（4 个及以上斜杠）与 `//` 是普通注释，不产生文档；
      * 缩进的 `///`（函数体 / impl 内部）按普通注释处理，不收也不报错；
      * `///` 后一个空格被剥掉；`///` 独占一行 = 空串（Markdown 段落分隔）。
    """
    lines = src.splitlines()
    n = len(lines)
    module_doc, blocks, orphans = [], [], []

    i = 0
    while i < n:
        raw = lines[i]
        if raw.startswith("//!"):
            module_doc.append(_doc_text(raw[3:]))
            i += 1
            continue
        if not raw.strip():
            i += 1
            continue
        break

    pending = None                       # (起始行号, [文本])
    while i < n:
        raw = lines[i]
        if raw.startswith("///") and not raw.startswith("////"):
            if pending is None:
                pending = (i + 1, [])
            pending[1].append(_doc_text(raw[3:]))
            i += 1
            continue
        if pending is not None:
            if not raw.strip():
                orphans.append((pending[0], "doc 块与声明之间有空行"))
                pending = None
                i += 1
                continue
            if raw[:1] in (" ", "\t"):
                orphans.append((pending[0], "doc 块后面不是顶层声明（缩进）"))
                pending = None
                i += 1
                continue
            if raw.startswith("@"):
                i += 1                   # 注解行：文档继续等待真正的声明
                continue
            head = _decl_head(raw)
            if head:
                blocks.append((i + 1, head[0], head[1], head[2], pending[1]))
            else:
                orphans.append((pending[0], "doc 块后面不是顶层声明"))
            pending = None
        elif raw.startswith("//!"):
            orphans.append((i + 1, "//! 只能出现在文件开头"))
        i += 1
    if pending is not None:
        orphans.append((pending[0], "文件结尾的 doc 块没有声明"))
    return module_doc, blocks, orphans


def iter_decls(src):
    """逐行找**顶层**声明 -> (行号, kind, name, is_pub)。

    文档工具用它统计"公开 API 面"（含没有 `///` 的那些），与
    scan_doc_comments 共用 _decl_head，保证两边认的声明是同一批。
    """
    for i, raw in enumerate(src.splitlines()):
        if not raw or raw[0] in (" ", "\t"):
            continue
        head = _decl_head(raw)
        if head:
            yield i + 1, head[0], head[1], head[2]


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


# 限定引用的内部编码分隔符（v1.99）：`模块串 \x01 名字`。
# 解析期把模块信息**留在 AST 里**，load_program 才能按节点解析——
# 这是 per-module mangling 的前提：同一个文件里 `helper()` 与 `lib.helper()`
# 必须能落到两个不同的符号上（v1.44 的做法是"剥掉模块段 + 记一个集合"，
# 集合无法区分这两个节点）。\x01 不可能出现在标识符里。
QSEP = "\x01"


def qref(imp, name):
    """把限定引用编码成可解析的内部名字。"""
    return imp + QSEP + name


def parse_version(text, what, line):
    """`"1.2.3"` / `"1.2"` / `"1"` -> (major, minor, patch)（v1.99）。

    接受可选前缀 `>=` / `^` / `=`（都表示"至少这个版本、且同 major"）——
    模块版本只用来**挡住不兼容的导入**，不做完整 semver 求解（那是 qpm 的活）。
    """
    t = text.strip()
    for pre in (">=", "^", "="):
        if t.startswith(pre):
            t = t[len(pre):].strip()
            break
    parts = t.split(".")
    if not 1 <= len(parts) <= 3 or any(not x.isdigit() for x in parts):
        raise SyntaxError(
            f"line {line}: {what} 的版本号 {text!r} 不合法——"
            "写法是 \"1.2.3\" / \"1.2\" / \"1\"（可带 >= / ^ 前缀）")
    nums = [int(x) for x in parts] + [0, 0]
    return (nums[0], nums[1], nums[2])


class Parser:
    def __init__(self, toks, consts=None, generic_fns=None, ifaces=None,
                 lenient_iface=False, src=None):
        self.toks, self.pos = toks, 0
        # doc comment（v1.92）：src= 给出源码文本时按行号把 `///` 挂到声明上。
        # 不给就完全跳过（第一次宽松扫描、单测里手工喂记号时不需要）。
        # 快路径：源码里没有 `///` / `//!` 就一行都不扫。
        self.module_doc = []
        self.type_docs = {}        # 类型名 -> [文档行]（struct/enum/interface）
        self._doc_by_line = {}     # 声明行号 -> [文档行]（fn 用）
        if src is not None and ("///" in src or "//!" in src):
            self.module_doc, blocks, _orphans = scan_doc_comments(src)
            for line, kind, name, _pub, doc in blocks:
                if kind == "fn":
                    self._doc_by_line[line] = doc
                else:
                    self.type_docs[name] = doc
        self.structs = {}          # name -> [(field, type)]（预扫描先登记名字）
        self.enums = {}            # name -> [(variant, [(field, type)])]（预扫描先登记名字）
        self.decl_order = []       # [("struct"|"enum", name)] 声明顺序（C typedef 输出顺序）
        self.externs = {}          # name -> fdef（@extern("C") 声明，无函数体）
        # v1.87：@ffi("dll"[, "Symbol"]) 声明——自研 PE 后端按导入表解析的
        # 外部函数。与 @extern("C") 的区别是**有 DLL 名**，因此能进导入表，
        # 不需要系统链接器。
        self.ffis = {}             # name -> fdef（带 fdef["ffi"] = {dll, sym}）
        # 接口表。ifaces= 跨文件种子（v1.81，与 consts/generic_fns 同一批两遍
        # 解析）：被导入文件声明的接口在这里可见，`impl T : Iface` 因此可以
        # 写在别的文件里。种子同时带来接口值的 {data,vt} 两字布局。
        self.interfaces = dict(ifaces) if ifaces else {}
        self._iface_seed = set(ifaces) if ifaces else set()
        # 内建接口 Drop（v1.93）：析构钩子。不注册成 struct——Drop 不是可装箱
        # 的值类型，只是"这个类型有析构函数"的挂载点：
        #   impl F : Drop { fn drop(f: F) { ... } }
        # 每个文件都能直接写，不必自己声明接口。用户显式声明同名同签名的
        # interface Drop 也走幂等分支（签名一致不报错）。
        self.interfaces.setdefault(
            "Drop", [("drop", [("named", "__self__")], ("named", "void"))])
        self._lenient_iface = lenient_iface
        # 宽松期"凭空登记"的接口名（v1.88）：第一遍扫描遇到 `impl T : Iface`
        # 时接口可能还没被扫到，只能先占位。占位**不能**进跨文件种子——
        # 否则"根本没声明的接口"会被第二遍当成合法种子放行（静默通过）。
        self.iface_provisional = set()
        self.impls = {}            # (iface, type) -> {method: fdef}
        self.methods = {}          # (type, method) -> fdef（impl 里定义的实例方法）
        # pub 可见性（v1.43）：pub 标记跨模块导出；本 Parser 实例 = 一个文件。
        self.pub_types = set()     # pub struct/enum/interface 名
        self._pending_pub = False  # `pub` 已吃掉、等下一个 fn/struct/enum 消化
        # 命名空间限定语法（v1.44）：lib.fn(...) / lib.Enum.Variant /
        # 模式 lib.Enum.Variant —— import 全串见 self.import_paths，
        # 限定引用（import 串, 名字）见 self.qrefs（load_program 校验指向）。
        self.import_paths = set()
        self.qrefs = set()
        # 模块版本（v1.99）：module util "1.2.3" 声明；import util ">=1.2" 要求。
        self.mod_version = None    # (major, minor, patch) 或 None
        self.import_reqs = {}      # import 串 -> (major, minor, patch)
        # 顶层 const，编译期内联。consts= 跨文件种子（load_program 两遍解析：
        # 第一遍收集各文件 const，第二遍带着全集重解析——import 侧的 const
        # 因此可见，std 库的槽位布局常量得以跨文件共享）。
        self.consts = dict(consts) if consts else {}
        # 泛型模板全集（v1.11）：调用点 f[int](...) 的解析需要知道 f 是不是
        # 泛型——种子跨文件传递（与 consts 同一批两遍解析）。
        self.generic_fns = dict(generic_fns) if generic_fns else {}
        # const fn 表（v1.58）：既进 fns 列表（运行时可调），也在这里登记
        # 供 const 右值做编译期解释执行。按声明序可见（与 const 同规则）。
        self.const_fns = {}
        self._const_steps = 0
        # 泛型 struct 模板（v1.59）：name -> {"params": [T...], "fields": [(f, ty)]}。
        # 不进 structs 表——只有实例化产物（Box__int）才是真正的结构体。
        self.generic_structs = {}
        self.generic_enums = {}
        self._cur_struct_tparams = None
        # 泛型 struct 的 impl 模板（v1.62）：(struct 名, 接口名) -> 模板方法。
        # 解析期按每个已实例化的 Box__X 物化成普通方法 Box__X__m。
        self.generic_impls = {}
        self._in_gimpl = False     # 正在解析泛型 impl 模板的方法体
        self._cur_tparams = []     # 当前作用域的类型参数（签名与体都认，v1.62）
        self.impl_labels = {}      # (接口, 实例名) -> 源码写法（报错用）
        self.symbolic_structs = {}  # 符号类型名 -> (模板名, 实参名表)（v1.62）
        self.struct_instances = []  # [(模板名, 实参名元组, 实例名)]，按生成顺序
        self.enum_instances = []    # 同上，泛型 enum 的实例（v1.64）
        # 本文件定义的泛型模板（种子里的不算）：类型约束名要等 interface
        # 全部解析完才能校验（v1.61），所以在 parse_program 末尾统一查。
        self._own_templates = []
        # 待展开的 @derive（v1.96）：(类型名, 字段/变体表, "struct"|"enum", 行号)
        self._pending_derives = []
        # 运行时反射（v1.96）：非常量下标改写成按需生成的查表函数
        self._refl_helpers = {}     # (what, 类型名) -> 生成的函数名
        self._refl_pending = []     # [(函数名, what, 类型名, 行号)]
        # 通用 token 宏（v1.96）：名字 -> (形参表, 宏体记号, 定义行号)。
        # 与 @derive 同一层（语法分析之前），但**不理解宏体语义**：只搬运记号。
        self.macros = {}
        self._scan_macros()
        # 属性宏 @derive（v1.71）：类型名 -> (派生项列表, 行号)。
        # 在 _scan_derives 里从记号流中摘掉注解，parse_program 只看到普通声明。
        self.derives = {}
        self._scan_derives()
        self._prescan()
        # 跨文件接口种子：接口值的布局（{data, vt} 两字）必须在本文件可见，
        # 否则 `let s: Shape = ...` 找不到结构体布局（v1.81）。
        for _iname in self._iface_seed:
            self.structs.setdefault(
                _iname, [("data", ("named", "int")),
                         ("vt", ("named", "int"))])
        # 闭包值布局（v1.95）：`closure` = {code, env} 两字，与接口值同构。
        # 注册成结构体后，布局/拷贝/形参/返回值/vec 元素全部复用既有聚合机制；
        # 用户在类型位写 `closure`（`let f: closure` / `fn apply(f: closure)`）。
        self.structs.setdefault("closure", list(CLOSURE_FIELDS))

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
            elif depth == 0 and t.kind == "fn" and i + 2 < len(toks) \
                    and toks[i + 1].kind == "NAME" \
                    and toks[i + 2].kind == "SYM" and toks[i + 2].val == "[":
                # 泛型 fn 名占位（v1.11）：体解析时 `fact[n](...)` 的自引用 /
                # 相互递归需要提前知道"这个名字是泛型"，否则会被解析成
                # 下标链。占位值在 parse_program 解析到声明时被完整模板覆盖。
                self.generic_fns.setdefault(toks[i + 1].val, None)
            i += 1

    def parse_const_value(self, name):
        """const 的右值（v1.11 起支持**编译期整型算术**——编译期求值的最小形态）：

        - int：字面量 / 一元负号 / 括号 / `+ - * / %` / 已声明的 const 引用
          （按声明序，引用未声明的报错）。求值在解析期完成，除法与模
          按 C 截断语义（与语言 binop 一致），编译期除零 fail-fast。
        - float / str / bool：仍仅字面量（含一元负号）。
        """
        t = self.peek()
        if t.kind == "STR":
            self.next()
            return ("str", t.val)
        if t.kind in ("true", "false"):
            self.next()
            return ("bool", t.kind == "true")
        if t.kind == "FLOAT" or (t.kind == "SYM" and t.val == "-"
                                 and self.peek(1).kind == "FLOAT"):
            neg = False
            if t.kind == "SYM":
                self.next()
                neg = True
            tf = self.next()
            return ("num", -tf.val if neg else tf.val)
        # v1.58：返回 bool 的 const fn 调用（int 返回值的走 _const_int_expr，
        # 这样 `const A = sq(3) + 1` 这类算术里嵌调用也能求值）
        if (t.kind == "NAME" and t.val in self.const_fns
                and self.const_fns[t.val].get("ret") == ("named", "bool")
                and self.peek(1).kind == "SYM" and self.peek(1).val == "("):
            self.next()
            self.next()
            args = []
            if not self.at("SYM", ")"):
                args.append(self._const_arg(name))
                while self.at("SYM", ","):
                    self.next()
                    args.append(self._const_arg(name))
            self.eat("SYM", ")")
            return self._const_call(t.val, args, t.line, name)
        # int 路径：字面量或编译期算术
        return ("num", self._const_int_expr(name))

    def _const_arg(self, ctx):
        """const fn 调用的实参：bool 字面量或整型常量表达式。"""
        t = self.peek()
        if t.kind in ("true", "false"):
            self.next()
            return t.kind == "true"
        return self._const_int_expr(ctx)

    def _const_int_expr(self, name):
        """编译期整型表达式求值（const 专用，递归下降）。

        只允许 INT / const 名 / 括号 / 算术——没有函数调用、没有类型转换，
        求值不可能有副作用，这就是"编译期求值"的安全边界。
        """
        def factor():
            t = self.peek()
            if t.kind == "SYM" and t.val == "-":
                self.next()
                return -factor()
            if t.kind == "SYM" and t.val == "(":
                self.next()
                v = expr()
                self.eat("SYM", ")")
                return v
            if t.kind == "INT":
                self.next()
                return t.val
            if t.kind == "NAME" and self.peek(1).kind == "SYM" \
                    and self.peek(1).val == "(":
                # v1.58：const fn 调用可以嵌在算术里（fact(5) + 1）
                if t.val in self.const_fns:
                    self.next()
                    self.next()
                    args = []
                    if not self.at("SYM", ")"):
                        args.append(self._const_arg(name))
                        while self.at("SYM", ","):
                            self.next()
                            args.append(self._const_arg(name))
                    self.eat("SYM", ")")
                    self._const_steps = 0
                    return self._const_invoke(t.val, args, t.line, 0)
                raise SyntaxError(
                    f"line {t.line}: const {name} 调用了非 const fn 的 {t.val!r}"
                    "（const 右值里只能调用 const fn）")
            if t.kind == "NAME":
                if t.val in self.consts:
                    cv = self.consts[t.val]
                    if cv[0] == "num" and isinstance(cv[1], int):
                        self.next()
                        return cv[1]
                    raise SyntaxError(
                        f"line {t.line}: const {name} 引用了非整型 const {t.val!r}")
                raise SyntaxError(
                    f"line {t.line}: const {name} 的算术引用了未声明的 {t.val!r}"
                    "（const 按声明序求值）")
            raise SyntaxError(
                f"line {t.line}: const {name} 的右值不是编译期可求值表达式"
                "（支持整型字面量/const 引用/括号/+ - * / %）")

        def term():
            v = factor()
            while self.at("SYM", "*") or self.at("SYM", "/") or self.at("SYM", "%"):
                op = self.next().val
                r = factor()
                if r == 0 and op in ("/", "%"):
                    raise SyntaxError(f"const {name}: 编译期除零")
                if op == "*":
                    v = v * r
                elif op == "/":
                    q = abs(v) // abs(r)
                    v = q if (v >= 0) == (r >= 0) else -q   # C 截断语义
                else:
                    m = abs(v) % abs(r)
                    v = m if v >= 0 else -m
            return v

        def expr():
            v = term()
            while self.at("SYM", "+") or self.at("SYM", "-"):
                op = self.next().val
                r = term()
                v = v + r if op == "+" else v - r
            return v

        return expr()

    # ---- v1.58：const fn —— 编译期求值 -----------------------------------
    #
    # 语义：const fn 既是普通函数（运行时可调、照常发射），也能在 const 右值里
    # 被解释执行。求值结果按**有符号 64 位回卷**——必须与同一个函数在运行时的
    # 结果逐位一致，否则 `const X = f(3)` 与 `let x = f(3)` 会分叉。
    #
    # 支持子集（fail-fast，不静默降级）：int/bool 形参与返回值；语句
    # let / 赋值（含 += 等）/ if / while / return / 表达式；表达式字面量、
    # 变量、算术、比较、逻辑、位运算、调用其他 const fn（含递归）。
    _CONST_STEP_LIMIT = 200000
    _CONST_DEPTH_LIMIT = 64

    @staticmethod
    def _wrap64(x):
        """按有符号 64 位回卷（与运行时 int 一致）。"""
        x &= (1 << 64) - 1
        return x - (1 << 64) if x >> 63 else x

    def _const_check_fn(self, f):
        ok = {("named", "int"), ("named", "bool")}
        for pname, pty in f["params"]:
            if pty not in ok:
                raise SyntaxError(
                    f"const fn {f['name']}: 形参 {pname} 的类型暂不支持"
                    "（只支持 int / bool）")
        ret = f.get("ret")
        if ret is not None and ret not in ok and ret != ("named", "void"):
            raise SyntaxError(
                f"const fn {f['name']}: 返回类型暂不支持（只支持 int / bool）")

    def _const_call(self, fname, args, line, ctx):
        """const 右值里的 const fn 调用：解释执行，返回 AST 常量节点。"""
        f = self.const_fns[fname]
        if len(args) != len(f["params"]):
            raise SyntaxError(
                f"line {line}: const {ctx} 调用 {fname} 需要 "
                f"{len(f['params'])} 个实参，得到 {len(args)} 个")
        self._const_steps = 0
        v = self._const_invoke(fname, args, line, 0)
        if f.get("ret") == ("named", "bool"):
            return ("bool", bool(v))
        return ("num", v)

    def _const_invoke(self, fname, args, line, depth):
        if depth > self._CONST_DEPTH_LIMIT:
            raise SyntaxError(
                f"line {line}: const fn {fname} 递归超过 "
                f"{self._CONST_DEPTH_LIMIT} 层")
        f = self.const_fns[fname]
        env = {}
        for (pname, pty), v in zip(f["params"], args):
            if pty == ("named", "bool"):
                if not isinstance(v, bool):
                    raise SyntaxError(
                        f"line {line}: const fn {fname} 的形参 {pname} 需要 bool")
            elif isinstance(v, bool) or not isinstance(v, int):
                raise SyntaxError(
                    f"line {line}: const fn {fname} 的形参 {pname} 需要 int")
            env[pname] = v
        sig, v = self._const_run(f["body"], env, line, depth)
        if sig == "break" or sig == "continue":
            raise SyntaxError(
                f"line {line}: const fn {fname} 里的 break/continue 没有外层循环")
        ret = f.get("ret")
        if ret == ("named", "bool"):
            if v is None:
                raise SyntaxError(
                    f"line {line}: const fn {fname} 声明返回 bool 但没有 return")
            return bool(v)
        if ret is not None and ret != ("named", "void") and v is None:
            raise SyntaxError(
                f"line {line}: const fn {fname} 声明返回 int 但没有 return")
        return self._wrap64(v) if isinstance(v, int) and not isinstance(v, bool) else 0

    def _const_tick(self, line):
        self._const_steps += 1
        if self._const_steps > self._CONST_STEP_LIMIT:
            raise SyntaxError(
                f"line {line}: const fn 求值超过 {self._CONST_STEP_LIMIT} 步"
                "（疑似死循环）")

    def _const_run(self, stmts, env, line, depth):
        """执行语句序列，返回 (信号, 值)：normal / return / break / continue。"""
        for s in stmts:
            self._const_tick(line)
            k = s[0]
            if k == "let":
                env[s[2]] = self._const_eval(s[3], env, line, depth)
            elif k == "assign":
                name, op = s[1], s[2]
                if name not in env:
                    raise SyntaxError(
                        f"line {line}: const fn 给未声明的 {name!r} 赋值")
                v = self._const_eval(s[3], env, line, depth)
                if op != "=":
                    v = self._const_binop(op[:-1], env[name], v, line)
                env[name] = v
            elif k == "if":
                branch = s[2] if self._const_eval(s[1], env, line, depth) else s[3]
                if branch:
                    sig, v = self._const_run(branch, env, line, depth)
                    if sig != "normal":
                        return sig, v
            elif k == "while":
                while self._const_eval(s[1], env, line, depth):
                    self._const_tick(line)
                    sig, v = self._const_run(s[2], env, line, depth)
                    if sig == "return":
                        return sig, v
                    if sig == "break":
                        break
            elif k == "return":
                return "return", (self._const_eval(s[1], env, line, depth)
                                  if s[1] is not None else None)
            elif k == "break":
                return "break", None
            elif k == "continue":
                return "continue", None
            elif k == "expr":
                self._const_eval(s[1], env, line, depth)
            else:
                raise SyntaxError(
                    f"line {line}: const fn 不支持 {k!r} 语句"
                    "（只支持 let / 赋值 / if / while / return / 表达式）")
        return "normal", None

    def _const_eval(self, e, env, line, depth):
        k = e[0]
        if k in ("num", "bool"):
            return e[1]
        if k == "str":
            raise SyntaxError(f"line {line}: const fn 暂不支持 str 值")
        if k == "name":
            if e[1] in env:
                return env[e[1]]
            if e[1] in self.consts:
                cv = self.consts[e[1]]
                if cv[0] in ("num", "bool"):
                    return cv[1]
            raise SyntaxError(
                f"line {line}: const fn 里引用了未声明的 {e[1]!r}"
                "（只认形参 / 局部变量 / 顶层 const）")
        if k == "unop":
            v = self._const_eval(e[2], env, line, depth)
            if e[1] == "-":
                if isinstance(v, bool):
                    raise SyntaxError(f"line {line}: const fn 对 bool 取负")
                return self._wrap64(-v)
            if e[1] == "!":
                return not v
            raise SyntaxError(f"line {line}: const fn 不支持一元运算符 {e[1]!r}")
        if k == "binop":
            a = self._const_eval(e[2], env, line, depth)
            b = self._const_eval(e[3], env, line, depth)
            return self._const_binop(e[1], a, b, line)
        if k == "call":
            if len(e[1]) == 1 and e[1][0] in self.const_fns:
                args = [self._const_eval(a, env, line, depth) for a in e[2]]
                return self._const_invoke(e[1][0], args, line, depth + 1)
            raise SyntaxError(
                f"line {line}: const fn 里只能调用 const fn，"
                f"{'.'.join(str(x) for x in e[1])} 不是")
        raise SyntaxError(
            f"line {line}: const fn 不支持 {k!r} 表达式"
            "（只支持字面量 / 变量 / 算术 / 比较 / 逻辑 / 位运算 / 调用 const fn）")

    def _const_binop(self, op, a, b, line):
        if op in ("==", "!=", "<", "<=", ">", ">="):
            return {"==": a == b, "!=": a != b, "<": a < b,
                    "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        if op == "&&":
            return bool(a) and bool(b)
        if op == "||":
            return bool(a) or bool(b)
        if isinstance(a, bool) or isinstance(b, bool):
            raise SyntaxError(
                f"line {line}: const fn 的 {op} 不接受 bool 操作数")
        if op == "+":
            return self._wrap64(a + b)
        if op == "-":
            return self._wrap64(a - b)
        if op == "*":
            return self._wrap64(a * b)
        if op in ("/", "%"):
            if b == 0:
                raise SyntaxError(f"line {line}: const fn 编译期除零")
            q = abs(a) // abs(b)
            q = -q if (a < 0) != (b < 0) else q
            return q if op == "/" else a - q * b
        if op == "&":
            return self._wrap64(a & b)
        if op == "|":
            return self._wrap64(a | b)
        if op == "^":
            return self._wrap64(a ^ b)
        if op in ("<<", ">>", ">>>"):
            if not 0 <= b < 64:
                raise SyntaxError(
                    f"line {line}: const fn 的移位位数越界（{b}）")
            if op == "<<":
                return self._wrap64(a << b)
            if op == ">>":
                return a >> b
            return self._wrap64((a & ((1 << 64) - 1)) >> b)
        raise SyntaxError(f"line {line}: const fn 不支持运算符 {op!r}")

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

    # v1.87：@ffi 声明的绑定与类型校验（解析期就 fail-fast——
    # 外部符号的参数宽度/寄存器类一旦写错，错在运行期是"垃圾值"，比崩溃更难查）
    FFI_SCALARS = ("int", "bool", "f64", "f32")

    def _bind_ffi(self, fdef, aargs, line):
        """@ffi("dll") / @ffi("dll", "Symbol") -> fdef["ffi"] = {dll, sym}

        口径：
          * 只接受标量形参/返回（int/bool/f64/f32，返回可为 void）；
            `str` 是长度前缀 ABI，C 侧要 NUL 结尾——用 `cstr(s)` 显式转换，
            不在这里静默改写（静默转换会在调用点悄悄多一次分配）。
          * 聚合/容器/切片一律拒绝：Win64 ABI 的按值结构体传参未实现。
        """
        name = fdef["name"]
        if not 1 <= len(aargs) <= 2:
            raise SyntaxError(
                f'line {line}: @ffi 需要 1–2 个字符串参数：'
                f'@ffi("kernel32.dll") 或 @ffi("kernel32.dll", "Symbol")')
        if fdef["body"] is not None:
            raise SyntaxError(f"line {line}: @ffi 声明不能带函数体（符号在 DLL 里）")
        dll, sym = aargs[0], (aargs[1] if len(aargs) == 2 else name)
        if not dll:
            raise SyntaxError(f"line {line}: @ffi 的 DLL 名不能为空")
        for pname, pt in fdef["params"]:
            if not (pt[0] == "named" and pt[1] in self.FFI_SCALARS):
                raise SyntaxError(
                    f"line {line}: @ffi 函数 {name!r} 的形参 {pname!r} 类型是 "
                    f"{pt[1] if pt[0] == 'named' else pt[0]}——FFI 只接受 "
                    f"int/bool/f64/f32。str 请改声明为 int 并传 cstr(s)；"
                    f"缓冲区请用 mem_alloc 并传指针")
        rt = fdef["ret"]
        if not (rt[0] == "named" and (rt[1] in self.FFI_SCALARS or rt[1] == "void")):
            raise SyntaxError(
                f"line {line}: @ffi 函数 {name!r} 的返回类型不支持"
                f"（只接受 int/bool/f64/f32/void）")
        fdef["ffi"] = {"dll": dll, "sym": sym}
        self.ffis[name] = fdef

    def parse_program(self):
        mod, imports, fns, tests = None, [], [], []
        while not self.at("EOF"):
            if self.at("module"):
                self.next()
                mod = self.eat("NAME").val
                if self.at("STR"):
                    # 模块版本（v1.99）：module util "1.2.3"
                    vt = self.next()
                    self.mod_version = parse_version(vt.val, "module", vt.line)
            elif self.at("import"):
                self.next()
                path = [self.eat("NAME").val]
                while self.at("SYM", "."):
                    self.next()
                    path.append(self.eat("NAME").val)
                imports.append(".".join(path))
                self.import_paths.add(".".join(path))
                if self.at("STR"):
                    # 版本要求（v1.99）：import util ">=1.2"
                    vt = self.next()
                    self.import_reqs[".".join(path)] = parse_version(
                        vt.val, "import", vt.line)
            elif self.at("const"):
                # const NAME [: T] = <编译期可求值>：解析期内联，无运行时存储。
                # v1.11：右值支持整型算术（+ - * / % 与括号、const 引用），
                # 编译期求值、C 截断语义；类型标注仅文档性（不做检查）。
                self.next()
                if self.at("fn"):
                    # const fn（v1.58）：既是普通函数（运行时可调、照常发射），
                    # 也能在 const 右值里被编译期解释执行（见 _const_call）。
                    fdef = self.parse_fn()
                    if fdef.get("type_params"):
                        raise SyntaxError(
                            f"const fn {fdef['name']!r} 暂不支持泛型类型参数")
                    self._const_check_fn(fdef)
                    fdef["const_fn"] = True
                    self.const_fns[fdef["name"]] = fdef
                    fns.append(fdef)
                    continue
                cname = self.eat("NAME").val
                if self.at("SYM", ":"):
                    self.next()
                    self.parse_type()
                self.eat("SYM", "=")
                self.consts[cname] = self.parse_const_value(cname)
            elif self.at("NAME", "pub"):
                # pub 可见性（v1.43）：上下文关键字——只在顶层声明位识别，
                # 函数内的 pub 变量名不受影响。作用于顶层 fn/struct/enum；
                # interface 自 v1.81 起也可 pub（跨文件 impl 的前提）。
                # const 本就解析期内联全局共享，不需要 pub。
                self.next()
                nxt = self.peek()
                if nxt.kind not in ("fn", "struct", "enum") and nxt.val not in (
                        "fn", "struct", "enum", "interface"):
                    raise SyntaxError(
                        f"line {nxt.line}: pub 只支持 fn/struct/enum/interface，"
                        f"得到 {nxt.val!r}")
                self._pending_pub = True
            elif self.at("fn"):
                fdef = self.parse_fn()
                if self._pending_pub:
                    fdef["pub"] = True
                    self._pending_pub = False
                if fdef.get("type_params"):
                    # 泛型模板（v1.11）：不进发射列表，只作单态化种子。
                    # 带注解的泛型（@simd/@extern ...）暂不支持——模板复制
                    # 会丢注解语义，先 fail-fast。
                    if fdef.get("annots") or fdef.get("extern"):
                        raise SyntaxError(
                            f"line ?: 泛型函数 {fdef['name']!r} 暂不支持注解"
                            "（@simd/@extern 等只用于具体函数）")
                    self.generic_fns[fdef["name"]] = fdef
                    self._own_templates.append(fdef)
                else:
                    fns.append(fdef)
            elif self.at("SYM", "@"):
                # 注解：@extern("C") fn ... （v0.11）/ @ffi("dll"[, "Sym"])（v1.87）
                # 参数一律是字符串字面量，逗号分隔（v1.87 起支持多参——
                # @ffi 需要 DLL 名 + 可选符号名）。
                annots = []
                while self.at("SYM", "@"):
                    at = self.next()
                    aname = self.eat("NAME").val
                    aargs = []
                    if self.at("SYM", "("):
                        self.next()
                        while not self.at("SYM", ")"):
                            if not self.at("STR"):
                                raise SyntaxError(
                                    f"line {at.line}: @{aname} 的参数必须是"
                                    f"字符串字面量")
                            aargs.append(self.next().val)
                            if self.at("SYM", ","):
                                self.next()
                        self.eat("SYM", ")")
                    annots.append((aname, aargs, at.line))
                if not self.at("fn"):
                    raise SyntaxError(
                        f"line {annots[-1][2]}: 注解只能用于 fn 声明")
                fdef = self.parse_fn()
                fdef["annots"] = [(a, (g[0] if len(g) == 1 else (tuple(g) or None)))
                                  for a, g, _ in annots]
                if fdef["body"] is not None and any(
                        a in ("extern", "ffi") for a, _, _ in annots):
                    raise SyntaxError(
                        f"line {annots[-1][2]}: @extern/@ffi 声明不能带函数体")
                for aname, aargs, line in annots:
                    if aname == "extern":
                        if aargs != ["C"]:
                            raise SyntaxError(
                                f"line {line}: @extern 只支持 \"C\"，得到 {aargs!r}")
                        fdef["extern"] = True
                        self.externs[fdef["name"]] = fdef
                    elif aname == "ffi":
                        self._bind_ffi(fdef, aargs, line)
                    elif aname in ("simd", "no_preempt"):
                        # v1.8：函数级提示/约定，语义见 docs/LANG.md
                        if aargs:
                            raise SyntaxError(f"line {line}: @{aname} 不接受参数")
                    elif aname == "rc":
                        # @rc 只允许出现在返回 rc[T] 的函数上（借用检查用）
                        pass
                    else:
                        raise SyntaxError(
                            f"line {line}: 未知注解 @{aname}"
                            f"（支持 @extern(\"C\") / @ffi(\"dll\"[, \"Sym\"]) / "
                            f"@simd / @no_preempt）")
                if fdef.get("extern") and fdef.get("ffi"):
                    raise SyntaxError(
                        f"line {fdef['line']}: @extern 与 @ffi 不能同时出现在"
                        f" {fdef['name']!r} 上（一个是 C 后端原型，一个是 PE 导入）")
                fns.append(fdef)
            elif self.at("interface"):
                self.next()
                iname = self.eat("NAME").val
                if self._pending_pub:
                    self.pub_types.add(iname)     # pub interface（v1.81）
                    self._pending_pub = False
                self.eat("SYM", "{")
                msigs = []
                while not self.at("SYM", "}"):
                    self.eat("fn")
                    mname = self.eat("NAME").val
                    self.eat("SYM", "(")
                    ptypes = []
                    while not self.at("SYM", ")"):
                        pn = self.eat("NAME").val
                        if pn == "self" and not self.at("SYM", ":"):
                            # 接口签名里的接收者不写类型：self
                            ptypes.append(("named", "__self__"))
                        else:
                            self.eat("SYM", ":")
                            ptypes.append(self.parse_type())
                        if self.at("SYM", ","):
                            self.next()
                    self.eat("SYM", ")")
                    rty = ("named", "void")
                    if self.at("SYM", "->"):
                        self.next()
                        rty = self.parse_type()
                    msigs.append((mname, ptypes, rty))
                self.eat("SYM", "}")
                if iname in self.interfaces and self.interfaces[iname] != msigs:
                    # 两遍解析会把本文件自己的声明也当种子送回来（幂等），
                    # 只有"同名不同签名"才是真冲突（v1.81）
                    raise SyntaxError(
                        f"line {line}: 接口 {iname} 在多个模块中声明不一致"
                        f"（跨文件接口必须同名同签名）")
                self.interfaces[iname] = msigs
                # 真声明覆盖宽松占位：这个名字从此不再是"凭空登记"（v1.88）
                self.iface_provisional.discard(iname)
                # 接口值 = {data, vt} 两字（v1.9 动态分发）：
                #   data = 堆上装箱的 payload 指针；vt = vtable 地址（代码段）
                # 注册成 struct 后，布局/复制/vec[Shape] 元素全部复用既有机制。
                self.structs[iname] = [("data", ("named", "int")),
                                       ("vt", ("named", "int"))]
                self.decl_order.append(("interface", iname))
            elif self.at("impl"):
                # impl Type : Interface { fn m(...) { ... } ... }
                # Type（v1.62）：`Name`（普通类型）、`Name[args]`（泛型 struct 的
                #   具体实例，如 impl Box[int] : Show）、`Name[T]`（泛型 impl 模板，
                #   如 impl Box[T] : Show——按每个已实例化的 Box__X 展开）。
                impl_tok = self.next()
                sname = self.eat("NAME").val
                targs = None
                if self.at("SYM", "["):
                    # 类型实参：具体类型，或类型参数（可带能力约束 T: Show）
                    self.next()
                    targs, ibounds = [], {}
                    while True:
                        tk = self.peek()
                        if tk.kind == "NAME" and not self._is_known_type(tk.val):
                            self.next()
                            targs.append(("named", tk.val))
                            if self.at("SYM", ":"):
                                self.next()
                                bl = [self.eat("NAME").val]
                                while self.at("SYM", "+"):
                                    self.next()
                                    bl.append(self.eat("NAME").val)
                                ibounds[tk.val] = bl
                        else:
                            targs.append(self.parse_type())
                        if self.at("SYM", ","):
                            self.next()
                            continue
                        break
                    self.eat("SYM", "]")
                self.eat("SYM", ":")
                iname = self.eat("NAME").val
                if iname not in self.interfaces:
                    if self._lenient_iface:
                        # 第一遍收集期（load_program 的 const/泛型/接口扫描）：
                        # 接口可能声明在另一个还没扫到的文件里，先登记空签名，
                        # 真正的校验在第二遍（带全量种子）做。v1.81
                        # 占位名记进 iface_provisional：它不进跨文件种子，
                        # 否则"完全没声明"的接口会被第二遍误当成合法种子（v1.88）
                        self.interfaces[iname] = []
                        self.iface_provisional.add(iname)
                        self.structs.setdefault(
                            iname, [("data", ("named", "int")),
                                    ("vt", ("named", "int"))])
                    else:
                        raise SyntaxError(
                            f"line {self.peek().line}: 未声明的接口 {iname}"
                            f"（接口可以声明在别的模块里，但必须被 import，"
                            f"且要加 pub）")
                if targs is not None and sname not in self.generic_structs \
                        and sname not in self.generic_enums:
                    raise SyntaxError(
                        f"line {impl_tok.line}: {sname} 不是泛型类型"
                        "（只有 struct/enum Name[T] 才能写 impl Name[...] : ...）")
                gimpl_kind = ("enum" if targs is not None
                              and sname in self.generic_enums else "struct")
                gimpl_tps = []
                if targs is not None:
                    gimpl_tps = [t[1] for t in targs
                                 if t[0] == "named" and not self._is_known_type(t[1])]
                    if len(gimpl_tps) != len(set(gimpl_tps)):
                        raise SyntaxError(
                            f"line {impl_tok.line}: impl {sname}[...] 的类型参数重名："
                            f"{gimpl_tps}")
                    if gimpl_tps and len(gimpl_tps) != len(targs):
                        raise SyntaxError(
                            f"line {impl_tok.line}: impl {sname}[...] 不能混用类型参数与"
                            "具体类型（要么全写 T，要么全写具体类型）")
                self.eat("SYM", "{")
                bodies = {}
                if gimpl_tps:
                    # 泛型 impl 模板：方法体按模板解析（`T { ... }` 是占位字面量），
                    # 具体实例在 parse_program 末尾物化。
                    saved_tp = getattr(self, "_cur_tparams", None)
                    saved_gi = getattr(self, "_in_gimpl", False)
                    self._cur_tparams = gimpl_tps
                    self._in_gimpl = True
                    while not self.at("SYM", "}"):
                        fd = self.parse_fn()
                        bodies[fd["name"]] = fd
                    self._cur_tparams = saved_tp
                    self._in_gimpl = saved_gi
                    self.eat("SYM", "}")
                    self.generic_impls[(sname, iname)] = {
                        "tparams": gimpl_tps, "methods": bodies,
                        "kind": gimpl_kind, "bounds": ibounds,
                        "sig": {m: (pt, rt) for m, pt, rt in self.interfaces[iname]},
                        "line": impl_tok.line}
                    continue
                if targs is not None:
                    if gimpl_kind == "enum":
                        tname = self._instantiate_enum(sname, targs, impl_tok.line)
                    else:
                        tname = self._instantiate_struct(sname, targs, impl_tok.line)
                    self.impl_labels[(iname, tname)] = (
                        f"{sname}[{', '.join(_ty_str(t) for t in targs)}]")
                else:
                    tname = sname
                while not self.at("SYM", "}"):
                    fd = self.parse_fn()
                    bodies[fd["name"]] = fd
                self.eat("SYM", "}")
                if (iname, tname) in self.impls:
                    # v1.93：同一 (类型, 接口) 只能有一个 impl。此前是静默
                    # 覆盖——两个 impl 里后写的赢，对 Drop 尤其危险（两个
                    # 析构函数，谁生效看书写顺序）。
                    raise SyntaxError(
                        f"line {impl_tok.line}: impl {tname} : {iname} 重复实现"
                        f"（同一类型在同一接口上只能有一个 impl）")
                self.impls[(iname, tname)] = bodies
                sig = {m: (pt, rt) for m, pt, rt in self.interfaces[iname]}
                for mname, fd in bodies.items():
                    # 方法落成普通函数 Circle__area(c, ...)；方法调用语法
                    # 在后端 eval 的 method 分支里解析成直接调用。
                    fd["name"] = f"{tname}__{mname}"
                    fd["self_type"] = tname
                    fd["impl_iface"] = iname
                    fd["impl_method"] = mname
                    # 接口方法顺序（vtable 槽位）与签名（动态调用的返回类型）
                    fd["iface_order"] = [m for m, _pt, _rt in self.interfaces[iname]]
                    fd["iface_sig"] = sig
                    prev = self.methods.get((tname, mname))
                    if prev is not None and prev.get("impl_iface") != iname:
                        # 同一类型在两个接口里有同名方法（v1.81）：按接口名
                        # 二次 mangling（Type__Iface__m），两条都进 fns。
                        # 静态调用 `c.m()` 从此是歧义（后端报错并指引走接口值），
                        # vtable 派发按各接口的槽位各走各的。
                        fd["name"] = f"{tname}__{iname}__{mname}"
                    else:
                        self.methods[(tname, mname)] = fd
                    fns.append(fd)
            elif self.at("struct"):
                dline = self.next().line
                name = self.eat("NAME").val
                if self._pending_pub:
                    self.pub_types.add(name)
                    self._pending_pub = False
                # 泛型 struct（v1.59）：struct Box[T] { value: T }
                # 模板不进 structs 表；类型位置写 Box[int] 时现场单态化出
                # 普通结构体 Box__int，下游布局/ABI/方法全部零改动。
                stparams = None
                sbounds = {}
                if self.at("SYM", "["):
                    bracket = self.next()
                    stparams = []
                    while True:
                        pname = self.eat("NAME").val
                        stparams.append(pname)
                        if self.at("SYM", ":"):
                            # 类型约束（v1.61）：泛型 struct 只支持能力约束
                            # （Ord/Eq/Num/Bit）——接口约束需要 impl 表，而
                            # 实例化发生在解析期，impl 可能还没解析到。
                            self.next()
                            bl = [self.eat("NAME").val]
                            while self.at("SYM", "+"):
                                self.next()
                                bl.append(self.eat("NAME").val)
                            for b in bl:
                                if b not in _BOUND_CAPS:
                                    raise SyntaxError(
                                        f"line {bracket.line}: 泛型 struct "
                                        f"{name} 的类型参数 {pname} 用了约束 {b}"
                                        "——struct 只支持能力约束 "
                                        + " / ".join(_BOUND_CAPS)
                                        + "（接口约束请写在泛型函数上）")
                            if len(set(bl)) != len(bl):
                                raise SyntaxError(
                                    f"line {bracket.line}: 类型参数 {pname} "
                                    f"的约束重复：{bl}")
                            sbounds[pname] = bl
                        if self.at("SYM", ","):
                            self.next()
                            continue
                        break
                    if len(set(stparams)) != len(stparams):
                        raise SyntaxError(
                            f"line {bracket.line}: 泛型 struct 类型参数重名：{stparams}")
                    self.eat("SYM", "]")
                self.eat("SYM", "{")
                self._cur_struct_tparams = stparams
                fields = []
                while not self.at("SYM", "}"):
                    fname = self.eat("NAME").val
                    self.eat("SYM", ":")
                    fields.append((fname, self.parse_type()))
                    if self.at("SYM", ","):
                        self.next()
                self.eat("SYM", "}")
                self._cur_struct_tparams = None
                # v1.96：按值自包含的聚合没有有限布局，必须在声明处拦下——
                # 否则尺寸计算会无限递归（RecursionError 指不到源码行）
                for _fn2, _ft2 in fields:
                    if _ft2 == ("named", name):
                        raise SyntaxError(
                            f"line {dline}: struct {name} 不能按值包含自身"
                            f"（用 vec[{name}] / map / chan 间接引用）")
                if stparams:
                    # _prescan 把 `struct NAME` 当普通结构体登记了空字段占位，
                    # 模板必须摘掉——否则 `Box { }` 会被当成零字段结构体
                    self.structs.pop(name, None)
                    if name in self.derives:
                        raise SyntaxError(
                            f"line {self.derives[name][1]}: 泛型 struct {name} "
                            "不能直接 @derive（字段类型还是类型参数）——"
                            "请对具体实例派生，或在 impl 里手写")
                    self.generic_structs[name] = {
                        "params": stparams, "fields": fields,
                        "bounds": sbounds}
                else:
                    self.structs[name] = fields
                    self.decl_order.append(("struct", name))
                    if name in self.derives:
                        # 属性宏展开（v1.71 / v1.96）：登记到文件末尾统一展开。
                        # 不在声明处就地展开，是因为字段类型可能是**后面**才
                        # 声明的 struct/enum（`_prescan` 只登记了名字，变体表
                        # 还是空的）——就地展开会在 `_zero_lit` / 嵌套检查上
                        # 读到半成品。派生函数是普通函数，展开顺序不影响调用。
                        self._pending_derives.append(
                            (name, fields, "struct", self.derives[name][1],
                             len(fns)))
            elif self.at("enum"):
                eline = self.next().line
                name = self.eat("NAME").val
                if self._pending_pub:
                    self.pub_types.add(name)
                    self._pending_pub = False
                # 泛型 enum（v1.63）：enum Opt[T] { Some(v: T), None }
                # 与泛型 struct 同款——解析期单态化，模板不进 enums 表。
                eparams = None
                if self.at("SYM", "["):
                    bracket = self.next()
                    eparams = [self.eat("NAME").val]
                    while self.at("SYM", ","):
                        self.next()
                        eparams.append(self.eat("NAME").val)
                    if len(set(eparams)) != len(eparams):
                        raise SyntaxError(
                            f"line {bracket.line}: 泛型 enum 类型参数重名：{eparams}")
                    self.eat("SYM", "]")
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
                for vn, vf in variants:
                    if vn in seen:
                        raise SyntaxError(f"enum {name} 变体 {vn} 重复声明")
                    seen.add(vn)
                    for _fn2, _ft2 in vf:
                        if _ft2 == ("named", name):
                            raise SyntaxError(
                                f"line {eline}: enum {name} 不能按值包含自身"
                                f"（变体 {vn} 的载荷）；递归类型请用 vec[{name}] "
                                "或 map 间接引用")
                if eparams:
                    self.enums.pop(name, None)   # _prescan 的占位登记要摘掉
                    if name in self.derives:
                        # 与泛型 struct 同一条规则：载荷类型还是类型参数，
                        # 展开时字段表不完整，必须在声明处拒绝（v1.96）
                        raise SyntaxError(
                            f"line {self.derives[name][1]}: 泛型 enum {name} "
                            "不能直接 @derive（载荷类型还是类型参数）——"
                            "请对实例化后的类型派生，或在 impl 里手写")
                    self.generic_enums[name] = {
                        "params": eparams, "variants": variants}
                else:
                    self.enums[name] = variants
                    self.decl_order.append(("enum", name))
                    if name in self.derives:
                        self._pending_derives.append(
                            (name, variants, "enum", self.derives[name][1],
                             len(fns)))
            elif self.at("test"):
                # 内建测试块：test "名字" { ... }（SPEC §8 `quelmara test`）
                self.next()
                name = self.eat("STR").val
                tests.append({"name": name, "body": self.parse_block()})
            else:
                t = self.peek()
                raise SyntaxError(
                    f"line {t.line}: 顶层期望 fn/struct/test/module/import，得到 {t.val!r}")
        # ---- 泛型 impl 模板物化（v1.62）----
        # impl Box[T] : Show 按每个已实例化的 Box__int / Box__str 展开成普通方法
        # Box__int__show——与手写 impl Box[int] : Show 的产物完全一致（同一套
        # 布局/派发/ABI）。物化后登记进 self.impls，下面既有的接口一致性检查
        # 会顺带把它们也校验一遍（方法齐全 / 参数个数 / 接收者 / 返回类型）。
        import copy as _copy
        for (gsname, iface), tmpl in self.generic_impls.items():
            tps = tmpl["tparams"]
            sym = gsname + "__" + "_".join(tps)
            done = set()
            # 模板目标是泛型 enum 还是 struct：各自的实例表不同（v1.64）
            insts = (self.enum_instances if tmpl.get("kind") == "enum"
                     else self.struct_instances)
            for (gname, tags, iname) in insts:
                if gname != gsname or iname in done:
                    continue
                done.add(iname)
                key = (iface, iname)
                if key in self.impls:
                    raise SyntaxError(
                        f"line {tmpl['line']}: {self.impl_labels.get(key, iname)} 已有 "
                        f"impl {self.impl_labels.get(key, iname)} : {iface}，"
                        f"与泛型 impl {gsname}[{', '.join(tps)}] : {iface} 重复"
                        "（同一接口对同一类型只能实现一次）")
                tp_map = dict(zip(tps, tags))
                tp_map[sym] = iname
                # 类型约束（v1.64）：impl Opt[T: Show] 的实参必须满足约束
                for tp, bl in (tmpl.get("bounds") or {}).items():
                    tyn = tp_map[tp]
                    for cap in bl:
                        if cap not in _BOUND_CAPS:
                            raise SyntaxError(
                                f"line {tmpl['line']}: impl "
                                f"{gsname}[{tp}: {cap}] —— impl 模板的类型参数"
                                "只支持能力约束 "
                                + " / ".join(_BOUND_CAPS))
                        if not _cap_supports(cap, tyn):
                            raise SyntaxError(
                                f"line {tmpl['line']}: impl "
                                f"{gsname}[{tp}: {cap}] 的实参 {tyn} 不满足 {cap}"
                                f"（{_cap_desc(cap)}）")
                # 方法体里其他泛型 struct 的符号名（Pair[T, int] 之类）：
                # 先按具体实参落实例（否则字面量指向一个不存在的类型），再换名
                for sname2, (gname2, argnames, kind2) in self.symbolic_structs.items():
                    if not all(a in tp_map or self._is_known_type(a)
                               for a in argnames):
                        continue
                    concrete = [("named", tp_map.get(a, a)) for a in argnames]
                    tp_map[sname2] = (
                        self._instantiate_enum(gname2, concrete, tmpl["line"])
                        if kind2 == "enum"
                        else self._instantiate_struct(gname2, concrete,
                                                      tmpl["line"]))
                bodies = {}
                for mname, fd in tmpl["methods"].items():
                    inst = _copy.deepcopy(fd)
                    inst["name"] = f"{iname}__{mname}"
                    inst["params"] = [(n, _subst_gimpl(t, tp_map))
                                      for n, t in inst["params"]]
                    inst["ret"] = _subst_gimpl(inst["ret"], tp_map)
                    inst["body"] = _subst_gimpl(inst["body"], tp_map)
                    inst["self_type"] = iname
                    inst["impl_iface"] = iface
                    inst["impl_method"] = mname
                    inst["iface_order"] = [m for m, _p, _r
                                           in self.interfaces[iface]]
                    inst["iface_sig"] = tmpl["sig"]
                    prev = self.methods.get((iname, mname))
                    if prev is not None:
                        # 与普通 impl 同一条规则（v1.81）：同名方法跨接口按
                        # 接口名二次 mangling，静态调用变歧义而不是编译失败
                        inst["name"] = f"{iname}__{iface}__{mname}"
                    else:
                        self.methods[(iname, mname)] = inst
                    bodies[mname] = inst
                    fns.append(inst)
                self.impls[key] = bodies
                self.impl_labels[key] = f"{gsname}[{', '.join(tps)}]"

        # ---- 类型约束名校验（v1.61）----
        # interface 可能声明在泛型函数之后，所以放到这里统一查：约束名必须
        # 是能力约束（Ord/Eq/Num/Bit）或**本文件**声明的 interface。
        for fd in self._own_templates:
            for tp, bl in (fd.get("type_bounds") or {}).items():
                for b in bl:
                    if b in _BOUND_CAPS:
                        continue
                    if b in self.interfaces:
                        continue
                    raise SyntaxError(
                        f"line {fd.get('line', 0)}: 泛型函数 {fd['name']} 的类型参数 "
                        f"{tp} 用了未知约束 {b}——可用："
                        + " / ".join(_BOUND_CAPS)
                        + "，或本文件声明的 interface（interface 与 impl "
                        "必须同源文件）")
        # ---- interface 一致性检查（v1.8）----
        for (iname, tname), bodies in self.impls.items():
            # 泛型 impl 模板物化出来的实例，报错用源码里的写法（Box[T]）而不是
            # 单态化名（Box__T）——v1.62
            label = self.impl_labels.get((iname, tname), tname)
            if tname not in self.structs and tname not in self.enums:
                raise SyntaxError(
                    f"impl {label} : {iname} —— 未声明的类型 {tname}")
            for mname, ptypes, rty in self.interfaces[iname]:
                if mname not in bodies:
                    raise SyntaxError(f"impl {label} : {iname} 缺少方法 {mname}")
                fd = bodies[mname]
                got = [t for _, t in fd["params"]]
                if len(got) != len(ptypes):
                    raise SyntaxError(
                        f"{label}.{mname}: 接口要求 {len(ptypes)} 个参数，实现给了 {len(got)}")
                if got and got[0] != ("named", tname):
                    raise SyntaxError(
                        f"{label}.{mname}: 第一个参数必须是接收者 {label}")
                for i, (a, b) in enumerate(zip(got[1:], ptypes[1:]), start=1):
                    if a != b:
                        raise SyntaxError(f"{label}.{mname}: 第 {i} 个参数类型与接口不一致")
                if fd["ret"] != rty:
                    raise SyntaxError(f"{label}.{mname}: 返回类型与接口声明不一致")
        # ---- @derive 统一展开（v1.96）----
        # 到这里 struct / enum 表才完整：字段类型可能指向后面声明的类型。
        # 生成物仍然**插回声明处**（`at` = 登记时的 fns 长度）——声明顺序是
        # parsediff 的比对口径，展开放到文件末尾会让 dump 顺序变掉。
        _blocks = []
        for _dn, _df, _dk, _dl, _at in self._pending_derives:
            _before = len(fns)
            self._expand_derive(_dn, _df, _dk, _dl, fns, imports)
            _blocks.append((_at, fns[_before:]))
            del fns[_before:]
        _off = 0
        for _at, _blk in sorted(_blocks, key=lambda x: x[0]):
            fns[_at + _off:_at + _off] = _blk
            _off += len(_blk)
        self._pending_derives = []

        # ---- 编译期反射折叠（v1.71 / v1.96）----
        # 到这里 struct/enum 表已完整：常量下标折叠成字面量，非常量下标改写成
        # 按需生成的查表函数（v1.96）——表是代码，不是数据，仍然零元数据段。
        for fd in fns:
            if fd.get("body") is not None:
                fd["body"] = self._refl_resolve(fd["body"])
        for tdef in tests:
            tdef["body"] = self._refl_resolve(tdef["body"])
        if self._refl_pending:
            src = "\n\n".join(self._refl_helper_src(*p)
                               for p in self._refl_pending)
            sub = Parser(tokenize(src), consts=self.consts,
                         generic_fns=self.generic_fns)
            sub.structs, sub.enums = self.structs, self.enums
            sub.const_fns = self.const_fns
            fns.extend(sub.parse_program()[2])
        self._methods = self.methods
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
        if self.at("vec"):
            # vec[T]：堆上变长数组（v1.2）；元素为标量或具名聚合 struct/enum（v1.3）
            # 元素按值拷贝进出；vec[vec[T]] / vec[map] 不支持（见 docs/GAPS.md §2）
            t = self.next()
            self.eat("SYM", "[")
            et = self.parse_type()
            self.eat("SYM", "]")
            vec_elem_tag(et, t.line)
            return ("vec", et)
        if self.at("rc"):
            # rc[T]：引用计数句柄（v1.8）。T 只支持具名 struct；句柄按值传递、
            # 不自动 drop —— 所有权由借用检查器强制（docs/LANG.md §rc）。
            t = self.next()
            self.eat("SYM", "[")
            tt = self.parse_type()
            self.eat("SYM", "]")
            if tt[0] != "named":
                raise SyntaxError(f"line {t.line}: rc[T] 的 T 目前只支持具名结构体")
            return ("rc", tt)
        if self.at("map"):
            # map[K]V：开放寻址哈希表（K/V 仅 int/bool/str 标量，SPEC 附录 v0.10）
            t = self.next()
            self.eat("SYM", "[")
            kt = self.parse_type()
            self.eat("SYM", "]")
            vt = self.parse_type()
            map_kv_tag(kt, "键类型", t.line)
            map_kv_tag(vt, "值类型", t.line)
            return ("map", kt, vt)
        if self.at("option"):
            self.next()
            self.eat("SYM", "[")
            tt = self.parse_type()
            self.eat("SYM", "]")
            return ("named", self.ensure_option_enum(tt, self.peek().line))
        if self.at("result"):
            # result[T, E]（T=Ok 载荷，E=Err 载荷）受控单态化入口
            rt = self.peek()
            self.next()
            self.eat("SYM", "[")
            tt = self.parse_type()
            self.eat("SYM", ",")
            et = self.parse_type()
            self.eat("SYM", "]")
            return ("named", self.ensure_result_enum(tt, et, rt.line))
        name = self.eat("NAME").val
        if self.at("SYM", "[") and "." not in name:
            # 泛型类型实例化：Box[int] -> ("named","Box__int")（v1.59 struct，
            # v1.63 enum）
            if name not in self.generic_structs and name not in self.generic_enums:
                raise SyntaxError(
                    f"line {self.peek().line}: {name} 不是泛型类型"
                    "（只有 struct/enum Name[T] 才能带类型实参）")
            self.next()
            targs = [self.parse_type()]
            while self.at("SYM", ","):
                self.next()
                targs.append(self.parse_type())
            self.eat("SYM", "]")
            if name in self.generic_structs:
                return ("named",
                        self._instantiate_struct(name, targs, self.peek().line))
            return ("named",
                    self._instantiate_enum(name, targs, self.peek().line))
        if name in self.generic_structs or name in self.generic_enums:
            raise SyntaxError(
                f"line {self.peek().line}: 泛型类型 {name} 必须带类型实参"
                f"（写成 {name}[int] 这种形式）")
        while self.at("SYM", "."):
            self.next()
            name += "." + self.eat("NAME").val
        return ("named", name)

    def _subst_type(self, t, tp_map):
        """类型元组里的类型参数替换（泛型 struct 单态化用）。"""
        if not isinstance(t, tuple):
            return t
        if t[0] == "named":
            # tp_map 存的是【完整类型元组】（("named","int") 等），直接替换，
            # 不能再包一层 ("named", ...) —— 否则字段类型变成 (named,(named,int))
            if t[1] in tp_map:
                return tp_map[t[1]]
            return t
        if t[0] in ("vec", "slice", "chan", "rc"):
            return (t[0], self._subst_type(t[1], tp_map))
        if t[0] == "map":
            return ("map", self._subst_type(t[1], tp_map),
                    self._subst_type(t[2], tp_map))
        if t[0] == "array":
            return ("array", t[1], self._subst_type(t[2], tp_map))
        return t

    def _is_known_type(self, name):
        """name 是否是一个已知的具体类型名（标量 / struct / enum / 泛型 struct 模板）。
        泛型 impl 的 `impl Box[T]` 用"不认识的具名类型 = 类型参数"来区分模板与实例。"""
        return (name in _GEN_SCALARS or name in self.structs
                or name in self.enums or name in self.generic_structs)

    # ---- 通用 token 宏（v1.96）----
    def _scan_macros(self):
        """`macro 名字(形参) { 记号 }` —— 通用 token 宏（v1.96）。

        与 `@derive` 的分工：`@derive` 是**结构化**的（编译器知道字段表，按表
        生成代码）；宏是**纯记号替换**（编译器不理解宏体语义，只搬运记号）。
        两者都在语法分析之前跑，产物是普通记号流——宏不可能造出后端没见过的
        AST 形状，这是"宏 = 代码生成"最省事的正确性来源。

        规则（每条都有负向夹具 `tests/bad/macro_*.qma`）：
          * 只能在顶层定义；宏体里的花括号必须配平；
          * 调用点必须是 `名字(`，且前一个记号不是 `.`（`x.macro(...)` 不展开）；
          * 实参按**顶层逗号**切分，个数必须与形参一致（缺/多都编译期报错）；
          * 展开是递归的（宏体里可以再调宏），层数上限 `_MACRO_MAX_DEPTH`；
          * **无卫生性**（hygiene）：形参按记号替换，不加括号、不改名。因此宏体
            里引用的自由名字与调用点同作用域，形参最好整体使用（`(x)` 而不是
            `x * 2` 里的半个表达式）。
          * 宏名不得与关键字同名；与函数/类型同名时宏优先（定义顺序无关）。
        """
        toks = self.toks
        out = []
        depth, i = 0, 0
        while i < len(toks):
            t = toks[i]
            if t.kind == "SYM" and t.val == "{":
                depth += 1
            elif t.kind == "SYM" and t.val == "}":
                depth -= 1
            if depth == 0 and t.kind == "NAME" and t.val == "macro":
                i = self._macro_define(toks, i, out)
                continue
            out.append(t)
            i += 1
        toks = out

        # 展开：一轮扫一遍，没有命中就停（命中过就再来一轮，支持宏调宏）
        for _round in range(_MACRO_MAX_DEPTH):
            if not self.macros:
                break
            out, i, hit = [], 0, False
            while i < len(toks):
                t = toks[i]
                prev_dot = bool(out) and out[-1].kind == "SYM" and out[-1].val == "."
                if (t.kind == "NAME" and t.val in self.macros and not prev_dot
                        and i + 1 < len(toks) and toks[i + 1].kind == "SYM"
                        and toks[i + 1].val == "("):
                    params, body, dline = self.macros[t.val]
                    args, j = self._macro_args(toks, i + 1, t.val, t.line)
                    if len(args) != len(params):
                        raise SyntaxError(
                            f"line {t.line}: 宏 {t.val} 需要 {len(params)} 个实参"
                            f"（{'、'.join(params) if params else '无'}），"
                            f"得到 {len(args)} 个")
                    sub = dict(zip(params, args))
                    for bt in body:
                        if bt.kind == "NAME" and bt.val in sub:
                            out.extend(sub[bt.val])
                        else:
                            # 宏体记号的诊断行号统一改成调用点：报错指向用户
                            # 写的那一行，而不是宏定义（宏体不是用户直接写的）
                            out.append(Tok(bt.kind, bt.val, t.line))
                    i, hit = j, True
                    continue
                out.append(t)
                i += 1
            toks = out
            if not hit:
                break
        else:
            raise SyntaxError(
                f"宏展开超过 {_MACRO_MAX_DEPTH} 层——宏体里可能自递归")
        self.toks = toks

    def _macro_define(self, toks, i, out):
        """解析一条 `macro` 定义，登记进 self.macros，返回定义之后的记号下标。"""
        line = toks[i].line
        j = i + 1
        if j >= len(toks) or toks[j].kind != "NAME":
            raise SyntaxError(f"line {line}: macro 后面需要宏名")
        name = toks[j].val
        j += 1
        if name in KEYWORDS:
            raise SyntaxError(f"line {line}: 宏名 {name} 与关键字同名")
        if j >= len(toks) or not (toks[j].kind == "SYM" and toks[j].val == "("):
            raise SyntaxError(f"line {line}: macro {name} 需要形参表："
                              f"macro {name}(a, b) {{ ... }}")
        j += 1
        params = []
        while j < len(toks) and not (toks[j].kind == "SYM" and toks[j].val == ")"):
            tk = toks[j]
            if tk.kind == "NAME":
                if tk.val in params:
                    raise SyntaxError(
                        f"line {line}: macro {name} 的形参 {tk.val} 重复")
                params.append(tk.val)
            elif not (tk.kind == "SYM" and tk.val == ","):
                raise SyntaxError(
                    f"line {line}: macro {name} 的形参表只接受名字，得到 {tk.val!r}")
            j += 1
        if j >= len(toks):
            raise SyntaxError(f"line {line}: macro {name} 的形参表没有闭合")
        j += 1
        if j >= len(toks) or not (toks[j].kind == "SYM" and toks[j].val == "{"):
            raise SyntaxError(f"line {line}: macro {name} 的定义体需要花括号")
        j += 1
        body, bd = [], 0
        while j < len(toks):
            tk = toks[j]
            if tk.kind == "SYM" and tk.val == "{":
                bd += 1
            elif tk.kind == "SYM" and tk.val == "}":
                if bd == 0:
                    break
                bd -= 1
            elif tk.kind == "EOF":
                break
            body.append(tk)
            j += 1
        if j >= len(toks) or not (toks[j].kind == "SYM" and toks[j].val == "}"):
            raise SyntaxError(f"line {line}: macro {name} 的定义体没有闭合")
        j += 1
        if name in self.macros:
            raise SyntaxError(f"line {line}: 宏 {name} 重复定义"
                              f"（前一次在第 {self.macros[name][2]} 行）")
        if not body:
            raise SyntaxError(f"line {line}: macro {name} 的定义体是空的")
        self.macros[name] = (params, body, line)
        return j

    def _macro_args(self, toks, i, name, line):
        """从 `(` 起切分实参（按顶层逗号），返回 (实参记号列表, `)` 之后的下标)。"""
        assert toks[i].kind == "SYM" and toks[i].val == "("
        args, cur, depth = [], [], 0
        j = i + 1
        while j < len(toks):
            tk = toks[j]
            if tk.kind == "SYM" and tk.val in ("(", "[", "{"):
                depth += 1
            elif tk.kind == "SYM" and tk.val in (")", "]", "}"):
                if depth == 0 and tk.val == ")":
                    if cur or args:
                        args.append(cur)
                    return args, j + 1
                depth -= 1
            elif tk.kind == "SYM" and tk.val == "," and depth == 0:
                args.append(cur)
                cur = []
                j += 1
                continue
            elif tk.kind == "EOF":
                break
            cur.append(tk)
            j += 1
        raise SyntaxError(f"line {line}: 宏 {name} 的调用没有闭合的 ')'")

    def _scan_derives(self):
        """`@derive(A, B)` 属性宏扫描（v1.71）——在语法分析**之前**跑。

        把注解从记号流里摘掉，登记 `self.derives[类型名] = (派生项, 行号)`。
        摘除之后 parse_program 完全不知道宏存在：它看到的是普通 struct/enum
        声明，字段表由下面的 `_expand_derive` 在声明解析完后按需展开成普通
        函数——宏只影响"写了哪些函数"，不影响语法。

        只在花括号深度 0（顶层）识别，函数体里的 `@derive` 不当作宏；
        注解后面必须紧跟 struct/enum 声明，否则 fail-fast（不猜）。
        """
        toks, out = self.toks, []
        depth, i = 0, 0
        while i < len(toks):
            t = toks[i]
            if t.kind == "SYM" and t.val == "{":
                depth += 1
            elif t.kind == "SYM" and t.val == "}":
                depth -= 1
            if (depth == 0 and t.kind == "SYM" and t.val == "@"
                    and i + 1 < len(toks) and toks[i + 1].kind == "NAME"
                    and toks[i + 1].val == "derive"):
                j = i + 2
                if j >= len(toks) or not (toks[j].kind == "SYM"
                                          and toks[j].val == "("):
                    raise SyntaxError(
                        f"line {t.line}: @derive 需要括号：@derive(Json, Eq)")
                j += 1
                items = []
                while j < len(toks) and not (toks[j].kind == "SYM"
                                             and toks[j].val == ")"):
                    if toks[j].kind == "NAME":
                        items.append(toks[j].val)
                    elif not (toks[j].kind == "SYM" and toks[j].val == ","):
                        raise SyntaxError(
                            f"line {t.line}: @derive(...) 里只接受派生项名字，"
                            f"得到 {toks[j].val!r}")
                    j += 1
                if j >= len(toks):
                    raise SyntaxError(f"line {t.line}: @derive( 没有闭合")
                if not items:
                    raise SyntaxError(f"line {t.line}: @derive() 至少要一个派生项")
                j += 1                      # 吃掉 ')'
                if not (j + 1 < len(toks)
                        and toks[j].kind in ("struct", "enum")
                        and toks[j + 1].kind == "NAME"):
                    raise SyntaxError(
                        f"line {t.line}: @derive 只能用于紧随其后的 "
                        "struct / enum 声明")
                tname = toks[j + 1].val
                if tname in self.derives:
                    raise SyntaxError(
                        f"line {t.line}: 类型 {tname} 有多个 @derive")
                self.derives[tname] = (items, t.line)
                i = j
                continue
            out.append(t)
            i += 1
        self.toks = out

    # ---- 类型文本（反射返回值 / 文档 / 报错统一口径）----
    def _type_text(self, ty):
        """类型元组 -> 源码写法（`vec[int]` / `Point` / `map[str]int`）。"""
        if not isinstance(ty, tuple) or not ty:
            return str(ty)
        k = ty[0]
        if k == "named":
            return ty[1]
        if k == "vec":
            return f"vec[{self._type_text(ty[1])}]"
        if k == "slice":
            return f"[]{self._type_text(ty[1])}"
        if k == "array":
            return f"[{ty[1]}]{self._type_text(ty[2])}"
        if k == "chan":
            return f"chan[{self._type_text(ty[1])}]"
        if k == "rc":
            return f"rc[{self._type_text(ty[1])}]"
        if k == "map":
            return f"map[{self._type_text(ty[1])}]{self._type_text(ty[2])}"
        return str(ty)

    # ---- @derive：字段分类 ----
    def _derive_field_kind(self, ty, tname, line):
        """字段类型 -> (kind, info)。kind ∈ int/bool/str/f64/struct/enum/vec。

        不支持的形状一律 fail-fast 并说清"为什么不支持"——静默跳过某个字段
        会让 JSON 少一个键，比编译不过危险得多。
        """
        def bad(why):
            raise SyntaxError(
                f"line {line}: @derive 作用在 {tname} 上，字段类型 "
                f"{self._type_text(ty)} 不支持——{why}")

        if not isinstance(ty, tuple) or not ty:
            bad("不是合法类型")
        if ty[0] == "named":
            t = ty[1]
            if t in _DERIVE_INT_TYPES:
                return ("int", t)
            if t == "bool":
                return ("bool", t)
            if t == "str":
                return ("str", t)
            if t in ("f64", "float"):
                return ("f64", "f64")
            if t == "f32":
                bad("f32 不参与派生——JSON 数字统一按 f64 读写，"
                    "请把字段声明成 f64（f32 只有 7 位有效数字，往返会丢精度）")
            if t in self.structs:
                return ("struct", t)
            if t in self.enums:
                return ("enum", t)
            bad("既不是标量也不是本文件声明的 struct/enum")
        if ty[0] == "vec":
            ek, einfo = self._derive_field_kind(ty[1], tname, line)
            if ek == "vec":
                bad("vec[vec[...]] 暂不支持")
            return ("vec", (ek, einfo))
        bad("只支持标量 / f64 / struct / enum / vec[标量·struct·enum]")

    def _zero_lit(self, ty, tname, line):
        """字段类型的零值字面量（解码函数先用它构造完整 struct 再逐字段赋值）。"""
        k, info = self._derive_field_kind(ty, tname, line)
        if k == "int":
            return "0"
        if k == "bool":
            return "false"
        if k == "str":
            return '""'
        if k == "f64":
            return "0.0"
        if k == "vec":
            return f"vec[{self._type_text(ty[1])}].new(0)"
        if k == "enum":
            # 枚举零值 = 第一个**无载荷**变体；都带载荷就用第一个变体的零载荷
            vs = self.enums[info]
            for vn, vf in vs:
                if not vf:
                    return f"{info}.{vn}"
            vn, vf = vs[0]
            inner = ", ".join(f"{n}: {self._zero_lit(t, tname, line)}"
                              for n, t in vf)
            return f"{info}.{vn}({inner})"
        flds = self.structs[info]
        if not flds:
            return f"{info} {{}}"
        inner = ", ".join(f"{n}: {self._zero_lit(t, tname, line)}"
                          for n, t in flds)
        return f"{info} {{ {inner} }}"

    def _check_derive_nested(self, owner, fields, item, line):
        """嵌套的 struct/enum 必须派生同一项。

        提前查（而不是让 Lower 报"未定义函数"）是因为后者的信息指不到根因：
        用户只看到 `<T>__json_into` 不存在，不知道是字段类型漏了派生。
        """
        fn_of = {"Json": "__json_into", "Eq": "__eq", "Show": "__show"}
        for fname, fty in fields:
            k, info = self._derive_field_kind(fty, owner, line)
            if k == "vec":
                k, info = info
            if k in ("struct", "enum"):
                items = self.derives.get(info, ((), 0))[0]
                if item not in items:
                    raise SyntaxError(
                        f"line {line}: @derive 作用在 {owner} 上，字段 {fname} 的类型 "
                        f"{info} 没有派生 {item}——生成的代码要调 "
                        f"{info}{fn_of[item]}，请给 {info} 也写 @derive({item})")

    def _derive_uses_f64(self, fields):
        for _fname, fty in fields:
            k, info = self._derive_field_kind(fty, "", 0)
            if k == "f64":
                return True
            if k == "vec" and info[0] == "f64":
                return True
        return False

    # ---- @derive：代码生成（三个派生项各自产出一段源码文本）----
    def _json_emit_field(self, expr, fname, fty, owner, line, ind, idx):
        """`"fname": <expr 的 JSON>` 的源码行（vec 展开成循环）。"""
        k, info = self._derive_field_kind(fty, owner, line)
        if k == "int":
            return [f'{ind}json_key_int(h, "{fname}", {expr})']
        if k == "bool":
            return [f'{ind}json_key_bool(h, "{fname}", {expr})']
        if k == "str":
            return [f'{ind}json_key_str(h, "{fname}", {expr})']
        if k == "f64":
            # f64 走 f64_repr（最短往返文本），不用 to_str——后者只有 7 位
            # 有效数字，写进 JSON 就是静默丢精度
            return [f'{ind}json_key_raw(h, "{fname}", f64_repr({expr}))']
        if k in ("struct", "enum"):
            return [f'{ind}json_key(h, "{fname}")',
                    f"{ind}{info}__json_into({expr}, h)"]
        ek, einfo = info
        L = [f'{ind}json_key(h, "{fname}")',
             f"{ind}json_begin_arr(h)",
             f"{ind}let mut j{idx} = 0",
             f"{ind}while j{idx} < {expr}.len() {{"]
        L += self._json_emit_value(f"{expr}.get(j{idx})", ek, einfo, ind + "    ")
        L += [f"{ind}    j{idx} = j{idx} + 1", f"{ind}}}", f"{ind}json_end_arr(h)"]
        return L

    def _json_emit_value(self, expr, ek, einfo, ind):
        """数组元素 / 无键值的 JSON 写入。"""
        if ek == "int":
            return [f"{ind}json_val_int(h, {expr})"]
        if ek == "bool":
            return [f"{ind}json_val_bool(h, {expr})"]
        if ek == "str":
            return [f"{ind}json_val_str(h, {expr})"]
        if ek == "f64":
            return [f"{ind}json_val_raw(h, f64_repr({expr}))"]
        return [f"{ind}{einfo}__json_into({expr}, h)"]

    def _json_read_expr(self, fname, fty, owner, line, ind, idx):
        """读一个字段 -> (前置语句行, 求值表达式)。

        f64 需要一条 let + 一条 assert（`json_num_raw` 对非数字返回空串，
        直接喂给 f64_parse 的报错指不到字段名）；vec 需要先搭容器。
        """
        k, info = self._derive_field_kind(fty, owner, line)
        key = f'json_obj_get(d, n, "{fname}")'
        if k == "int":
            return [], f"json_int(d, {key})"
        if k == "bool":
            return [], f"json_bool(d, {key})"
        if k == "str":
            return [], f"json_str(d, {key})"
        if k == "f64":
            return ([f"{ind}let mut r{idx} = json_num_raw(d, {key})",
                     f'{ind}assert(r{idx} != "", "字段 {fname} 不是 JSON 数字")'],
                    f"f64_parse(r{idx})")
        if k in ("struct", "enum"):
            return [], f"{info}__from_node(d, {key})"
        ek, einfo = info
        L = [f"{ind}let mut v{idx} = vec[{self._type_text(fty[1])}].new(0)",
             f"{ind}let a{idx} = {key}",
             f"{ind}let mut j{idx} = 0",
             f"{ind}while j{idx} < json_arr_len(d, a{idx}) {{"]
        inner = f"json_arr_at(d, a{idx}, j{idx})"
        if ek == "f64":
            L += [f"{ind}    v{idx}.push(f64_parse(json_num_raw(d, {inner})))"]
        elif ek == "int":
            L += [f"{ind}    v{idx}.push(json_int(d, {inner}))"]
        elif ek == "bool":
            L += [f"{ind}    v{idx}.push(json_bool(d, {inner}))"]
        elif ek == "str":
            L += [f"{ind}    v{idx}.push(json_str(d, {inner}))"]
        else:
            L += [f"{ind}    v{idx}.push({einfo}__from_node(d, {inner}))"]
        L += [f"{ind}    j{idx} = j{idx} + 1", f"{ind}}}"]
        return L, f"v{idx}"

    def _gen_json(self, name, fields, line):
        """derive(Json)：编码 `<T>__json` / `<T>__json_into` + 解码 `<T>_from_json`。

        走 std/json 的 builder / DOM API——转义、数字格式、逗号状态机全部复用
        已有实现，派生层只负责"字段名 + 字段类型"这两件声明里已有的事实。
        """
        L = [f"fn {name}__json(self: {name}) -> str {{",
             "    let h = json_new(64)",
             f"    {name}__json_into(self, h)",
             "    return json_done(h)",
             "}",
             "",
             f"fn {name}__json_into(self: {name}, h: int) -> int {{",
             "    json_begin_obj(h)"]
        for i, (fname, fty) in enumerate(fields):
            L += self._json_emit_field(f"self.{fname}", fname, fty, name, line,
                                       "    ", i)
        L += ["    json_end_obj(h)",
              "    return 0",
              "}",
              "",
              f"fn {name}_from_json(s: str) -> {name} {{",
              "    let d = json_parse(s)",
              f'    assert(json_ok(d), "{name}_from_json: 非法 JSON")',
              f"    return {name}__from_node(d, json_root(d))",
              "}",
              "",
              f"fn {name}__from_node(d: int, n: int) -> {name} {{"]
        zeros = ", ".join(f"{fn}: {self._zero_lit(ft, name, line)}"
                          for fn, ft in fields)
        L.append(f"    let mut out = {name} {{ {zeros} }}")
        for i, (fname, fty) in enumerate(fields):
            pre, expr = self._json_read_expr(fname, fty, name, line, "    ", i)
            L += pre
            L.append(f"    out.{fname} = {expr}")
        L += ["    return out",
              "}"]
        return "\n".join(L)

    # ---- @derive：enum 的 JSON（v1.96）----
    def _gen_json_enum(self, name, variants, line):
        """enum 的 JSON 表示：`{"$v":"变体名", <载荷字段>...}`。

        约定（唯一事实来源，文档 §4.8.1 同款）：
          * 无载荷变体 → `{"$v":"Dot"}`；
          * 有载荷变体 → `{"$v":"Circle","r":3}`，载荷按**声明顺序**跟在 $v 后；
          * 解码只认 `$v` 字面量，未知变体 fail-fast（不猜、不给默认值）。
        为什么不用"裸字符串 / 裸数字"：同一个 enum 的变体可能带不同载荷，
        带 $v 的对象让"类型 → 表示"始终是满射，跨语言消费方不用猜。
        """
        L = [f"fn {name}__json(self: {name}) -> str {{",
             "    let h = json_new(64)",
             f"    {name}__json_into(self, h)",
             "    return json_done(h)",
             "}",
             "",
             f"fn {name}__json_into(self: {name}, h: int) -> int {{",
             "    match self {"]
        for vname, vfields in variants:
            # 载荷绑定用位置名 _v0/_v1：字段名可能叫 h/d/n，与生成代码里的
            # JSON 句柄、DOM 参数同名，直接用字段名会静默把 int 当句柄传
            binds = ", ".join(f"_v{i}" for i in range(len(vfields)))
            L.append(f"        {name}.{vname}"
                     + (f"({binds})" if vfields else "") + " => {")
            L.append("            json_begin_obj(h)")
            L.append(f'            json_key_str(h, "$v", "{vname}")')
            for i, (fname, fty) in enumerate(vfields):
                L += self._json_emit_field(f"_v{i}", fname, fty, name, line,
                                           "            ", f"{vname}_{i}")
            L.append("            json_end_obj(h)")
            L.append("        }")
        L += ["    }", "    return 0", "}",
              "",
              f"fn {name}_from_json(s: str) -> {name} {{",
              "    let d = json_parse(s)",
              f'    assert(json_ok(d), "{name}_from_json: 非法 JSON")',
              f"    return {name}__from_node(d, json_root(d))",
              "}",
              "",
              f"fn {name}__from_node(d: int, n: int) -> {name} {{",
              '    let tag = json_str(d, json_obj_get(d, n, "$v"))']
        for vname, vfields in variants:
            L.append(f'    if tag == "{vname}" {{')
            if not vfields:
                L.append(f"        return {name}.{vname}")
            else:
                args = []
                for i, (fname, fty) in enumerate(vfields):
                    pre, expr = self._json_read_expr(fname, fty, name, line,
                                                     "        ", f"{vname}_{i}")
                    L += pre
                    args.append(f"{fname}: {expr}")
                L.append(f"        return {name}.{vname}({', '.join(args)})")
            L.append("    }")
        L += [f'    assert(false, "{name}__from_node: 未知变体（$v 不是已知变体名）")',
              f"    return {self._zero_lit(('named', name), name, line)}",
              "}"]
        return "\n".join(L)

    def _eq_check(self, lhs, rhs, fty, owner, line, ind, idx):
        """逐字段判等：不等就 `return false`。vec 展开成长度 + 逐元素。"""
        k, info = self._derive_field_kind(fty, owner, line)
        if k in ("int", "bool", "str", "f64"):
            return [f"{ind}if {lhs} != {rhs} {{", f"{ind}    return false", f"{ind}}}"]
        if k in ("struct", "enum"):
            return [f"{ind}if !{info}__eq({lhs}, {rhs}) {{",
                    f"{ind}    return false", f"{ind}}}"]
        ek, einfo = info
        L = [f"{ind}if {lhs}.len() != {rhs}.len() {{",
             f"{ind}    return false", f"{ind}}}",
             f"{ind}let mut i{idx} = 0",
             f"{ind}while i{idx} < {lhs}.len() {{"]
        if ek in ("int", "bool", "str", "f64"):
            L.append(f"{ind}    if {lhs}.get(i{idx}) != {rhs}.get(i{idx}) {{")
        else:
            L.append(f"{ind}    if !{einfo}__eq({lhs}.get(i{idx}), {rhs}.get(i{idx})) {{")
        L += [f"{ind}        return false", f"{ind}    }}",
              f"{ind}    i{idx} = i{idx} + 1", f"{ind}}}"]
        return L

    def _gen_eq(self, name, fields, line):
        """derive(Eq)：结构等价。

        为什么需要：聚合的 `==` 在 Lower 里是**地址比较**（07-gaps §7.6），
        `Point{x:1} == Point{x:1}` 为 false。派生出的 `<T>__eq` 逐字段比，
        是语言里第一个"聚合按值相等"的实现。
        """
        L = [f"fn {name}__eq(self: {name}, o: {name}) -> bool {{"]
        for i, (fname, fty) in enumerate(fields):
            L += self._eq_check(f"self.{fname}", f"o.{fname}", fty, name, line,
                                "    ", i)
        L += ["    return true", "}"]
        return "\n".join(L)

    def _gen_eq_enum(self, name, variants, line):
        """enum 等价：先比变体（match 的两层），再比载荷。

        等价定义（文档 §4.8.1 同款）：同一变体且载荷逐字段相等。不同变体
        永远不等——不是"内存里前几个字相同"。
        """
        L = [f"fn {name}__eq(self: {name}, o: {name}) -> bool {{",
             "    match self {"]
        for vname, vfields in variants:
            binds = ", ".join(f"_v{i}" for i in range(len(vfields)))
            L.append(f"        {name}.{vname}" + (f"({binds})" if vfields else "")
                     + " => {")
            if not vfields:
                L += [f"            match o {{",
                      f"                {name}.{vname} => {{ return true }}",
                      "                _ => { return false }",
                      "            }"]
            else:
                obinds = ", ".join(f"_o{i}" for i in range(len(vfields)))
                L += [f"            match o {{",
                      f"                {name}.{vname}({obinds}) => {{"]
                for i, (fname, fty) in enumerate(vfields):
                    L += self._eq_check(f"_v{i}", f"_o{i}", fty, name, line,
                                        "                    ", f"{vname}_{i}")
                L += ["                    return true", "                }",
                      "                _ => { return false }",
                      "            }"]
            L.append("        }")
        L += ["    }", "    return false", "}"]
        return "\n".join(L)

    def _gen_show(self, name, fields, line):
        """derive(Show)：`Point { x: 1, y: 2 }` 形态的文本（非 JSON，给人看）。

        bool 单独走 if/else 拼字面量：`b.to_str()` 对**字段访问**走的是整数
        路径（打印 1/0），只有字面量位置才认 bool（Lower 的既有口径）。
        派生层不赌这个差异，直接拼 "true"/"false"。
        """
        if not fields:
            return (f"fn {name}__show(self: {name}) -> str {{\n"
                    f'    return "{name} {{}}"\n}}')
        L = [f'    let mut s = "{name} {{"']
        for i, (fname, fty) in enumerate(fields):
            k, info = self._derive_field_kind(fty, name, line)
            sep = f" {fname}: " if i == 0 else f", {fname}: "
            if k == "bool":
                L.append(f'    s = s + "{sep}"')
                L.append(f"    if self.{fname} {{")
                L.append('        s = s + "true"')
                L.append("    } else {")
                L.append('        s = s + "false"')
                L.append("    }")
            elif k == "vec":
                L.append(f'    s = s + "{sep}["')
                L += self._show_vec_into(fname, fty, i, name, line)
                L.append('    s = s + "]"')
            else:
                L.append(f'    s = s + "{sep}"'
                         f" + {self._show_expr('self.' + fname, k, info)}")
        L.append('    return s + " }"')
        head = f"fn {name}__show(self: {name}) -> str {{"
        return "\n".join([head] + L + ["}"])

    def _gen_show_enum(self, name, variants, line):
        """enum 的 Show：`Circle(3)` / `Rect(3, 5)` / `Dot`（无载荷不带括号）。"""
        L = [f"fn {name}__show(self: {name}) -> str {{",
             "    match self {"]
        for vname, vfields in variants:
            binds = ", ".join(f"_v{i}" for i in range(len(vfields)))
            L.append(f"        {name}.{vname}" + (f"({binds})" if vfields else "")
                     + " => {")
            if not vfields:
                L.append(f'            return "{vname}"')
            else:
                parts, pre = [], []
                for i, (fname, fty) in enumerate(vfields):
                    k, info = self._derive_field_kind(fty, name, line)
                    if k == "bool":
                        # bool 的 to_str 在字段/绑定位置走整数路径，单独拼
                        pre += [f'            let mut b{i} = "false"',
                                f'            if _v{i} {{ b{i} = "true" }}']
                        parts.append(f"b{i}")
                    else:
                        parts.append(self._show_expr(f"_v{i}", k, info))
                L += pre
                expr = f'"{vname}("'
                for i, p in enumerate(parts):
                    if i:
                        expr += ' + ", "'
                    expr += f" + {p}"
                expr += ' + ")"'
                L.append(f"            return {expr}")
            L.append("        }")
        L += ["    }", '    return ""', "}"]
        return "\n".join(L)

    def _show_vec_into(self, fname, fty, idx, tname, line):
        k, info = self._derive_field_kind(fty, tname, line)
        ek, einfo = info
        body = [f"    let mut i{idx} = 0",
                f"    while i{idx} < self.{fname}.len() {{",
                f"        if i{idx} > 0 {{",
                '            s = s + ", "',
                "        }"]
        if ek == "str":
            body.append(f"        s = s + self.{fname}.get(i{idx})")
        else:
            body.append(f"        s = s + "
                        f"{self._show_expr('self.' + fname + f'.get(i{idx})', ek, einfo)}")
        body += [f"        i{idx} = i{idx} + 1", "    }"]
        return body

    def _show_expr(self, expr, kind, info):
        if kind == "int":
            return f"{expr}.to_str()"
        if kind == "bool":
            return f"{expr}.to_str()"
        if kind == "str":
            return expr
        if kind == "f64":
            return f"{expr}.to_str()"
        return f"{info}__show({expr})"

    def _expand_derive(self, name, fields, kind, line, fns, imports):
        """按 `@derive` 列表展开成普通函数，追加进本文件的函数列表。

        实现方式是**生成源码再解析**（不是手工拼 AST）：生成的代码走的是
        与用户手写完全相同的解析/推断/降级路径，宏不可能造出后端没见过的
        节点形状。子解析器共享本文件的 struct/enum 符号表，所以字段类型
        能照常解析。
        """
        items, dline = self.derives[name]
        seen = set()
        for it in items:
            if it not in _DERIVE_ITEMS:
                raise SyntaxError(
                    f"line {dline}: 未知派生项 {it!r}——支持 "
                    + " / ".join(_DERIVE_ITEMS))
            if it in seen:
                raise SyntaxError(f"line {dline}: @derive 重复写了 {it}")
            seen.add(it)
        if kind == "struct":
            if name in self.generic_structs:
                raise SyntaxError(
                    f"line {dline}: 泛型 struct {name} 不能直接 @derive——"
                    "请对实例化后的类型派生，或在 impl 里手写")
        elif kind == "enum":
            if name in self.generic_enums:
                raise SyntaxError(
                    f"line {dline}: 泛型 enum {name} 不能直接 @derive——"
                    "请对实例化后的类型派生（v1.96 边界）")
        else:
            raise SyntaxError(
                f"line {dline}: @derive 只支持 struct / enum（{name} 是 {kind}）")
        # 枚举的"字段"是各变体的载荷：嵌套派生检查与 f64 判定都按展平后的表走
        flat = fields if kind == "struct" else [f for _v, vf in fields for f in vf]
        parts = []
        for it in _DERIVE_ITEMS:
            if it in seen:
                self._check_derive_nested(name, flat, it, dline)
                suffix = "_enum" if kind == "enum" else ""
                parts.append(getattr(self, "_gen_" + it.lower() + suffix)(
                    name, fields, dline))
        src = "\n\n".join(parts)
        if "Json" in seen and "std.json" not in imports:
            # derive(Json) 的产物调用 std/json 的 builder/DOM API：
            # 自动补 import，用户不必知道派生实现依赖哪个模块。
            imports.append("std.json")
        if "Json" in seen and self._derive_uses_f64(flat) \
                and "std.f64" not in imports:
            # f64 字段的编解码走 std/f64 的 f64_repr / f64_parse
            imports.append("std.f64")
        sub = Parser(tokenize(src), consts=self.consts,
                     generic_fns=self.generic_fns)
        sub.structs, sub.enums = self.structs, self.enums
        sub.const_fns = self.const_fns
        res = sub.parse_program()
        for fd in res[2]:
            fd["derive_of"] = name
            fd["derive_line"] = dline
            if name in self.pub_types:
                # 派生函数继承类型的可见性：pub struct 的 json/eq/show 也要能
                # 被别的模块调用（否则库导出的类型在调用方一用就撞 pub 检查）
                fd["pub"] = True
        fns.extend(res[2])

    # ---- 编译期反射：refl_*[T](i) 的折叠 ----
    def _refl_value(self, node):
        _, what, ty, args, line = node
        if not (isinstance(ty, tuple) and ty[0] == "named"):
            raise SyntaxError(
                f"line {line}: {what} 的类型实参必须是具名类型"
                f"（得到 {self._type_text(ty)}）")
        tname = ty[1]

        def const_int(k=0):
            """下标是编译期常量就返回它，否则返回 None（走运行时查表）。"""
            if len(args) <= k:
                raise SyntaxError(f"line {line}: {what} 缺少下标实参")
            a = args[k]
            if isinstance(a, tuple) and a[0] == "num":
                return a[1]
            return None

        if len(args) > 1:
            raise SyntaxError(f"line {line}: {what} 最多一个下标实参")
        if args and isinstance(args[0], tuple) and args[0][0] == "str":
            # 下标位写字符串字面量一定是笔误；变量位没法查（语言没有完整的
            # 形参类型检查：str 传 int 形参也会静默编译）
            raise SyntaxError(
                f"line {line}: {what} 的下标必须是 int（得到字符串字面量 "
                f"{args[0][1]!r}）")
        if what == "refl_type_name":
            if args:
                raise SyntaxError(f"line {line}: refl_type_name 不接受实参")
            return ("str", tname)
        if what in ("refl_field_count", "refl_field_name", "refl_field_type"):
            if tname not in self.structs:
                raise SyntaxError(
                    f"line {line}: {what}[{tname}] —— {tname} 不是 struct"
                    "（字段反射只支持 struct）")
            flds = self.structs[tname]
            if what == "refl_field_count":
                if args:
                    raise SyntaxError(f"line {line}: refl_field_count 不接受实参")
                return ("num", len(flds))
            i = const_int()
            if i is None:
                return self._refl_dynamic(what, tname, args[0], line)
            if not 0 <= i < len(flds):
                raise SyntaxError(
                    f"line {line}: {what}[{tname}]({i}) 越界——"
                    f"{tname} 有 {len(flds)} 个字段")
            return ("str", flds[i][0]) if what == "refl_field_name" \
                else ("str", self._type_text(flds[i][1]))
        if what in ("refl_variant_count", "refl_variant_name",
                    "refl_variant_arity"):
            if tname not in self.enums:
                raise SyntaxError(
                    f"line {line}: {what}[{tname}] —— {tname} 不是 enum")
            vs = self.enums[tname]
            if what == "refl_variant_count":
                if args:
                    raise SyntaxError(f"line {line}: refl_variant_count 不接受实参")
                return ("num", len(vs))
            i = const_int()
            if i is None:
                return self._refl_dynamic(what, tname, args[0], line)
            if not 0 <= i < len(vs):
                raise SyntaxError(
                    f"line {line}: {what}[{tname}]({i}) 越界——"
                    f"{tname} 有 {len(vs)} 个变体")
            return ("str", vs[i][0]) if what == "refl_variant_name" \
                else ("num", len(vs[i][1]))
        raise SyntaxError(f"line {line}: 未知反射函数 {what}")

    def _refl_dynamic(self, what, tname, idx_node, line):
        """下标不是编译期常量：改写成按需生成的查表函数（v1.96）。

        仍然没有元数据段——表是**代码**（if 链），不是数据：O(n) 分支、
        常量内存、无动态派发。这样就能写"按下标遍历字段/变体"的循环，
        而编译期常量下标仍折叠成字面量（零成本路径不变）。
        """
        key = (what, tname)
        fname = self._refl_helpers.get(key)
        if fname is None:
            fname = f"__refl_{what}_{tname}"
            self._refl_helpers[key] = fname
            self._refl_pending.append((fname, what, tname, line))
        return ("call", [fname], [idx_node])

    def _refl_helper_src(self, fname, what, tname, line):
        """生成查表函数的源码（与 @derive 同一条"生成源码再解析"路径）。"""
        if what == "refl_field_name":
            ret, vals = "str", [fn for fn, _ in self.structs[tname]]
        elif what == "refl_field_type":
            ret, vals = "str", [self._type_text(ft)
                                for _, ft in self.structs[tname]]
        elif what == "refl_variant_name":
            ret, vals = "str", [vn for vn, _ in self.enums[tname]]
        else:
            ret, vals = "int", [len(vf) for _, vf in self.enums[tname]]
        L = [f"fn {fname}(i: int) -> {ret} {{"]
        for k, v in enumerate(vals):
            lit = f'"{v}"' if ret == "str" else str(v)
            L.append(f"    if i == {k} {{ return {lit} }}")
        L.append(f'    assert(false, "{what}[{tname}]: 下标越界'
                 f'（共 {len(vals)} 项）")')
        L.append('    return ""' if ret == "str" else "    return 0")
        L.append("}")
        return "\n".join(L)

    def _refl_resolve(self, node):
        """把 AST 里的 ("refl", ...) 节点整棵替换成常量字面量 / 查表调用。"""
        if isinstance(node, tuple):
            if node and node[0] == "refl":
                return self._refl_value(node)
            return tuple(self._refl_resolve(x) for x in node)
        if isinstance(node, list):
            return [self._refl_resolve(x) for x in node]
        if isinstance(node, dict):
            return {k: self._refl_resolve(v) for k, v in node.items()}
        return node

    def _instantiate_struct(self, gname, targs, line):
        """按类型实参现场合成具名结构体（受控单态化）。

        命名 Box__int；同一实例只生成一次。产物就是普通结构体——布局、字段
        偏移、值语义、聚合返回 ABI、方法派发全部复用既有路径。
        """
        tmpl = self.generic_structs[gname]
        params = tmpl["params"]
        if len(targs) != len(params):
            raise SyntaxError(
                f"line {line}: 泛型 struct {gname} 需要 {len(params)} 个类型实参"
                f"（[{'、'.join(params)}]），得到 {len(targs)} 个")
        tags = []
        for t in targs:
            if not (t and t[0] == "named"):
                raise SyntaxError(
                    f"line {line}: 泛型 struct {gname} 的类型实参暂只支持具名类型"
                    "（标量 / struct / enum / 其他实例），容器类型实参不做")
            if self._in_gimpl and t[1] in (self._cur_tparams or []):
                # 泛型 impl 模板里的符号类型（v1.62）：impl Box[T] 的 Box[T] 不
                # 实例化，返回符号名 Box__T，物化时按具体实例名替换。
                # 同时记下符号名的实参表——方法体里可能还出现 Pair[T, int]
                # 这种"部分具体"的形态，物化时要逐个参数替换。
                sym = gname + "__" + "_".join(
                    x[1] for x in targs if x and x[0] == "named")
                self.symbolic_structs[sym] = (
                    gname, [x[1] for x in targs if x and x[0] == "named"], "struct")
                return sym
            if t[1] in (self._cur_tparams or []):
                # 泛型函数里 Box[T] 以前会静默造出一个字段类型为 T 的假 struct
                # Box__T（只有单字布局的实参才"碰巧能用"），v1.62 起 fail-fast。
                raise SyntaxError(
                    f"line {line}: 泛型函数里暂不支持把类型参数用作泛型 struct 的"
                    f"类型实参（{gname}[{t[1]}]）——请用具体类型（{gname}[int]），"
                    "或把逻辑写进泛型 impl 模板 impl "
                    f"{gname}[{t[1]}] : <接口>")
            if self._cur_struct_tparams and t[1] in self._cur_struct_tparams:
                raise SyntaxError(
                    f"line {line}: 泛型 struct 的字段里暂不支持嵌套泛型 struct"
                    f"（{gname}[{t[1]}] 的类型实参还是外层模板的类型参数）")
            tags.append(t[1])
        iname = gname + "__" + "_".join(tags)
        # 类型约束（v1.61）：实例化时逐条核对能力约束。
        # 放在 "已生成则复用" 之前——不同实参组合是不同实例，各查各的。
        sbounds = tmpl.get("bounds") or {}
        for tp, bl in sbounds.items():
            tyn = tags[params.index(tp)]
            for cap in bl:
                if not _cap_supports(cap, tyn):
                    raise SyntaxError(
                        f"line {line}: 泛型 struct {gname} 的类型参数 {tp} "
                        f"要求 {cap}（{_cap_desc(cap)}），但实参 {tyn} 不满足")
        if iname in self.structs:
            return iname
        tp_map = dict(zip(params, [("named", tg) for tg in tags]))
        fields = [(fn, self._subst_type(ft, tp_map))
                  for fn, ft in tmpl["fields"]]
        self.structs[iname] = fields
        self.decl_order.append(("struct", iname))
        self.struct_instances.append((gname, tuple(tags), iname))
        return iname

    def _instantiate_enum(self, gname, targs, line):
        """泛型 enum 单态化（v1.63）：Opt[int] -> Opt__int（普通枚举）。

        与泛型 struct 同一套纪律：解析期现场合成，布局/匹配/穷尽性检查全部
        复用既有路径；变体载荷里的 T 按实参替换。
        """
        tmpl = self.generic_enums[gname]
        params = tmpl["params"]
        if len(targs) != len(params):
            raise SyntaxError(
                f"line {line}: 泛型 enum {gname} 需要 {len(params)} 个类型实参"
                f"（[{'、'.join(params)}]），得到 {len(targs)} 个")
        tags = []
        for t in targs:
            if not (t and t[0] == "named"):
                raise SyntaxError(
                    f"line {line}: 泛型 enum {gname} 的类型实参暂只支持具名类型"
                    "（标量 / struct / enum / 其他实例）")
            if self._in_gimpl and t[1] in (self._cur_tparams or []):
                # 泛型 impl 模板里的符号类型（v1.64）：impl Opt[T] 的 Opt[T]
                # 不实例化，返回符号名 Opt__T，物化时按具体实例名替换。
                sym = gname + "__" + "_".join(
                    x[1] for x in targs if x and x[0] == "named")
                self.symbolic_structs[sym] = (
                    gname, [x[1] for x in targs if x and x[0] == "named"], "enum")
                return sym
            if t[1] in (self._cur_tparams or []):
                raise SyntaxError(
                    f"line {line}: 泛型函数/impl 模板里暂不支持把类型参数用作泛型 "
                    f"enum 的类型实参（{gname}[{t[1]}]）——请用具体类型")
            tags.append(t[1])
        iname = gname + "__" + "_".join(tags)
        if iname in self.enums:
            return iname
        tp_map = dict(zip(params, [("named", tg) for tg in tags]))
        variants = [(vn, [(fn, self._subst_type(ft, tp_map)) for fn, ft in fs])
                    for vn, fs in tmpl["variants"]]
        self.enums[iname] = variants
        self.decl_order.append(("enum", iname))
        self.enum_instances.append((gname, tuple(tags), iname))
        return iname

    def parse_fn(self):
        fn_tok = self.eat("fn")
        name = self.eat("NAME").val
        tparams = None
        tbounds = {}
        if self.at("SYM", "["):
            # 用户泛型（v1.11 起；v1.36 支持多类型参数；v1.61 支持类型约束）：
            # fn name[A, B](a: A, b: B) -> ... { ... }
            # fn name[T: Ord + Num](...)        —— 能力约束
            # fn name[T: Shape](...)            —— 接口约束（impl T : Shape 必须存在）
            # 调用点可显式实例化 f[int, str](...)，也可省略方括号由推导
            # 补全（v1.36，见 expand_generics / _GenInfer）。
            bracket = self.next()
            tparams = []
            while True:
                pname = self.eat("NAME").val
                tparams.append(pname)
                if self.at("SYM", ":"):
                    self.next()
                    bl = [self.eat("NAME").val]
                    while self.at("SYM", "+"):
                        self.next()
                        bl.append(self.eat("NAME").val)
                    if len(set(bl)) != len(bl):
                        raise SyntaxError(
                            f"line {bracket.line}: 类型参数 {pname} 的约束重复：{bl}")
                    tbounds[pname] = bl
                if self.at("SYM", ","):
                    self.next()
                    continue
                break
            if len(set(tparams)) != len(tparams):
                raise SyntaxError(
                    f"line {bracket.line}: 泛型类型参数重名：{tparams}")
            self.eat("SYM", "]")
        self.eat("SYM", "(")
        # 类型参数作用域：形参/返回值/体内的 `T` 都要认（v1.62 起覆盖签名，
        # 此前只有函数体——`fn f[T](x: Box[T])` 会在签名里静默造出假 struct）。
        # 非泛型函数（如泛型 impl 里的方法）**继承**外层作用域，不能清空。
        saved_tp = getattr(self, "_cur_tparams", None)
        if tparams:
            self._cur_tparams = tparams
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
        if self.at("SYM", "{"):
            body = self.parse_block()
        else:
            # 无函数体：仅 @extern("C") 声明允许（parse_program 校验注解存在）
            body = None
        self._cur_tparams = saved_tp
        fd = {"name": name, "params": params, "ret": ret, "body": body,
              "line": fn_tok.line}
        if self._doc_by_line:
            doc = self._doc_by_line.get(fn_tok.line)
            if doc:
                fd["doc"] = doc          # doc comment（v1.92），只读不参与语义
        if tparams:
            fd["type_params"] = tparams
        if tbounds:
            fd["type_bounds"] = tbounds
        return fd

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
        # 语句注解（v1.8）：@simd for ... / @no_preempt while ...
        if t.kind == "SYM" and t.val == "@":
            line = t.line
            anns = []
            while self.at("SYM", "@"):
                self.next()
                aname = self.eat("NAME").val
                aarg = None
                if self.at("SYM", "("):
                    self.next()
                    if self.at("INT"):
                        aarg = self.next().val
                    elif self.at("STR"):
                        aarg = self.next().val
                    self.eat("SYM", ")")
                anns.append((aname, aarg, line))
            inner = self.parse_stmt()
            if inner[0] not in ("for", "while"):
                raise SyntaxError(f"line {line}: 语句注解只能修饰 for / while")
            return ("annot", anns, inner)
        if t.kind == "let":
            self.next()
            mut = False
            if self.at("mut"):
                self.next()
                mut = True
            name = self.eat("NAME").val
            # v1.8：`let x: u8 = ...` 类型标注。宽度类型在**边界处截断/回绕**
            # （init/assign/形参/返回值），表达式内部按 C 语义提升到 64 位。
            anno = None
            if self.at("SYM", ":"):
                self.next()
                anno = self.parse_type()
            self.eat("SYM", "=")
            node = ("let", mut, name, self.parse_expr())
            if anno is not None:
                node = node + (("as", anno),)
            return node
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
            first = self.parse_expr()
            if self.at("SYM", ".."):
                self.next()
                hi = self.parse_expr()
                return ("for" if t.kind == "for" else "parfor",
                        var, first, hi, self.parse_block())
            if t.kind == "parfor":
                raise SyntaxError(f"line {t.line}: parfor 只支持 parfor v in lo..hi")
            # for x in <map|vec>：遍历（v1.2）
            return ("foreach", var, first, self.parse_block())
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
        if t.kind == "defer":
            # defer 语句（v1.48）：defer <表达式/赋值> —— 所在块退出时
            # LIFO 执行（正常落到块尾 / return / break / continue 跳出均算）。
            # 变量取【退出时】的值（同块内后绑定可见，内层块 shadow 不可见）。
            self.next()
            stmt = self.parse_stmt()
            if stmt[0] not in ("expr", "assign", "assign_field", "assign_index"):
                raise SyntaxError(
                    f"line {t.line}: defer 只支持表达式/赋值语句，得到 {stmt[0]!r}")
            return ("defer", stmt)
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
        if self.at("SYM") and self.peek().val in (
                "=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", ">>>="):
            op = self.next().val
            rhs = self.parse_expr()
            if isinstance(expr, tuple) and expr[0] == "name":
                return ("assign", expr[1], op, rhs)
            if isinstance(expr, tuple) and expr[0] in ("path", "field"):
                return ("assign_field", expr, op, rhs)
            if isinstance(expr, tuple) and expr[0] == "index":
                return ("assign_index", expr[1], expr[2], op, rhs)
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
        if self.at("SYM", "[") and name in self.generic_enums:
            # 泛型 enum 模式（v1.63）：Opt[int].Some(x) => ...
            self.next()
            targs = [self.parse_type()]
            while self.at("SYM", ","):
                self.next()
                targs.append(self.parse_type())
            self.eat("SYM", "]")
            path = [self._instantiate_enum(name, targs, t.line)]
        while self.at("SYM", "."):
            self.next()
            path.append(self.eat("NAME").val)
        # 命名空间限定模式（v1.44）：lib.Color.Red -> Color.Red（剥模块段）
        if len(path) > 2:
            imp, rest = self._match_import(tuple(path[:-1]))
            if imp is not None and len(rest) >= 1:
                self.qrefs.add((imp, rest[0]))
                # 保留模块段（v1.99）：load_program 按节点解析并可能 mangling
                path = [qref(imp, rest[0])] + list(rest[1:]) + [path[-1]]
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

    def ensure_option_enum(self, tt, line):
        """option[T] 受控单态化：按 T 现场合成具名枚举 __opt_<T>{Some(value:T),None}。
        类型元组直接坍缩为 ("named","__opt_<T>")，下游 enum 布局/match/聚合返回 ABI 全部复用。
        v1.38：T 放宽到具名 struct/enum（多字载荷——enum 布局本就是 1+最大载荷字）。"""
        if not (tt and tt[0] == "named" and (
                tt[1] in ("int", "i64", "i32", "i16", "i8",
                          "u64", "u32", "u16", "u8", "bool", "str")
                or tt[1] in self.structs or tt[1] in self.enums)):
            raise SyntaxError(f"line {line}: option[T] 的 T 暂只支持整数/bool/str 标量与具名 struct/enum")
        name = "__opt_" + tt[1]
        if name not in self.enums:
            self.enums[name] = [("Some", [("value", tt)]), ("None", [])]
            self.decl_order.append(("enum", name))
        return name

    def ensure_result_enum(self, tt, et, line):
        """result[T,E] 受控单态化：按 (T,E) 现场合成具名枚举 __res_<T>_<E>
        {Ok(value:T), Err(error:E)}（Ok 固定在前）。
        类型元组直接坍缩为 ("named","__res_<T>_<E>")，下游 enum 布局/match/聚合返回 ABI 全部复用。
        v1.38：T/E 放宽到具名 struct/enum（多字载荷——库层终于能把 errno+上下文
        装进 Err）；类型名含下划线时 (A_B,C) 与 (A,B_C) 会撞同一名字，撞且语义
        不同直接报错（fail-fast，不静默用错枚举）。"""
        for t in (tt, et):
            if not (t and t[0] == "named" and (
                    t[1] in ("int", "i64", "i32", "i16", "i8",
                             "u64", "u32", "u16", "u8", "bool", "str")
                    or t[1] in self.structs or t[1] in self.enums)):
                raise SyntaxError(f"line {line}: result[T,E] 的 T/E 暂只支持整数/bool/str 标量与具名 struct/enum")
        name = "__res_" + tt[1] + "_" + et[1]
        want = [("Ok", [("value", tt)]), ("Err", [("error", et)])]
        if name not in self.enums:
            self.enums[name] = want
            self.decl_order.append(("enum", name))
        elif self.enums[name] != want:
            raise SyntaxError(
                f"line {line}: result 枚举名 {name} 冲突——类型名含下划线时"
                "（如 result[A_B, C] 与 result[A, B_C]）会相撞，请给类型改名")
        return name

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
        l = self.parse_bor()
        while self.at("SYM", "&&"):
            self.next()
            l = ("binop", "&&", l, self.parse_bor())
        return l

    # 位运算优先级故意采用「自下而上收紧」的层次：
    #   |  最松
    #   ^
    #   &
    #   比较
    #   << >>
    #   加减
    # 这与 Go（把 << >> 放在乘法层、| 放在加法层）和 Python（& 高于 ^）都不同，
    # 是 Quelmara 自己的定义，见 SPEC §2.4。
    def parse_bor(self):
        l = self.parse_bxor()
        while self.at("SYM", "|"):
            self.next()
            l = ("binop", "|", l, self.parse_bxor())
        return l

    def parse_bxor(self):
        l = self.parse_band()
        while self.at("SYM", "^"):
            self.next()
            l = ("binop", "^", l, self.parse_band())
        return l

    def parse_band(self):
        l = self.parse_eq()
        while self.at("SYM", "&"):
            self.next()
            l = ("binop", "&", l, self.parse_eq())
        return l

    def parse_eq(self):
        l = self.parse_rel()
        while self.at("SYM") and self.peek().val in ("==", "!="):
            op = self.next().val
            l = ("binop", op, l, self.parse_rel())
        return l

    def parse_rel(self):
        l = self.parse_shift()
        while self.at("SYM") and self.peek().val in ("<", "<=", ">", ">="):
            op = self.next().val
            l = ("binop", op, l, self.parse_shift())
        return l

    def parse_shift(self):
        l = self.parse_add()
        while self.at("SYM") and self.peek().val in ("<<", ">>", ">>>"):
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
        if self.at("SYM", "~"):
            self.next()
            return ("unop", "~", self.parse_unary())
        if self.at("spawn"):
            # spawn f(args) -> 线程句柄（int64）；语义见 SPEC §4
            t = self.next()
            target = self.parse_primary()
            if not (isinstance(target, tuple) and target[0] == "call"):
                raise SyntaxError(f"line {t.line}: spawn 后面必须是函数调用，如 spawn work(x)")
            # `spawn f(x).join()`：join 直接作用于 spawn 表达式（脱糖为 join(spawn f(x))）
            if self.at("SYM", ".") and self.peek(1).kind == "NAME" \
                    and self.peek(1).val == "join" \
                    and self.peek(2).kind == "SYM" and self.peek(2).val == "(":
                self.next()
                self.next()
                self.next()
                jargs = self.parse_args()
                if jargs:
                    raise SyntaxError(f"line {t.line}: join() 不接受实参")
                return ("call", ["join"], [("spawn", target)])
            return ("spawn", target)
        return self.parse_postfix()

    def _match_import(self, segs):
        """段元组 -> (匹配的 import 全串, 剥离模块段后的剩余段)。
        精确等于某 import -> rest=()；某 import 是段前缀 -> rest=多余段
        （`ws.ws_core.greet` 的 ("ws","ws_core") 精确、("ws",) 前缀均命中）；
        不匹配 -> (None, None)。"""
        if not segs or not self.import_paths:
            return None, None
        joined = ".".join(segs)
        if joined in self.import_paths:
            return joined, ()
        for imp in sorted(self.import_paths):
            ps = imp.split(".")
            if len(segs) > len(ps) and tuple(segs[:len(ps)]) == tuple(ps):
                return imp, tuple(segs[len(ps):])
        return None, None

    def parse_postfix(self):
        e = self._postfix_inner()
        if e[0] == "path":
            # 命名空间限定路径（v1.44）：lib.Color.Red -> Color.Red（剥模块段）
            imp, rest = self._match_import(tuple(e[1]))
            if imp is not None and rest:
                self.qrefs.add((imp, rest[0]))
                e = ("path", [qref(imp, rest[0])] + list(rest[1:]))
        return e

    def _postfix_inner(self):
        e = self.parse_primary()
        line = self.peek().line
        while True:
            if self.at("SYM", "."):
                self.next()
                name = self.eat("NAME").val
                if self.at("SYM", "("):
                    self.next()
                    args = self.parse_args()
                    # 命名空间限定调用（v1.44）：lib.fn(...) / lib.Color.Red(...)
                    # —— 头部段匹配本文件 import 时改写为扁平调用/枚举构造，
                    # 并记录限定引用（load_program 校验指向与 pub）。
                    cand = None
                    if e[0] == "name":
                        cand = (e[1],)
                    elif e[0] == "path":
                        cand = tuple(e[1])
                    if cand is not None:
                        imp, rest = self._match_import(cand)
                        if imp is not None:
                            if rest:
                                # 枚举构造：限定引用记枚举名（rest[0]），
                                # 变体名不是顶层声明
                                self.qrefs.add((imp, rest[0]))
                                if any(a[0] == "namedarg" for a in args):
                                    raise SyntaxError(
                                        f"line {line}: 限定枚举构造只支持位置实参"
                                        f"（字段表在被导入模块里，命名实参无法在此校验）")
                                e = ("enumlit_pos",
                                     [qref(imp, rest[0])] + list(rest[1:])
                                     + [name], list(args))
                            else:
                                self.qrefs.add((imp, name))
                                e = ("call", [qref(imp, name)], list(args))
                            continue
                    # `Shape.Circle(radius: 5)` -> 枚舉變體構造
                    if e[0] == "name" and self.enum_variant_of([e[1], name]):
                        e = self.mk_enumlit([e[1], name], args, line)
                    else:
                        if any(a[0] == "namedarg" for a in args):
                            raise SyntaxError(f"line {line}: 普通函数/方法调用不支持命名实参")
                        # `h.join()` 方法式语法：脱糖为内置 join(h)，与函数式完全等价
                        # （用户自定义 join 函数优先，走统一 call 路径校验）
                        if name == "join":
                            e = ("call", ["join"], [e] + list(args))
                        else:
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
            elif self.at("SYM", "["):
                # 下标 a[i] 或区间 a[lo..hi]（v1.1 子切片：左闭右开）
                self.next()
                lo = self.parse_expr()
                if self.at("SYM", ".."):
                    self.next()
                    hi = self.parse_expr()
                    self.eat("SYM", "]")
                    e = ("sliceof", e, lo, hi)
                else:
                    self.eat("SYM", "]")
                    e = ("index", e, lo)
            elif self.at("SYM", "?"):
                self.next()
                e = ("try", e)
            else:
                return e

    def _parse_interp(self, text, line):
        """把 "a{x}b" 拆成 ("interp", [("str","a"), <expr>, ("str","b")])。

        表达式段用**子解析器**（tokenize 子串 + parse_expr）解析，共享父解析器的
        const / 泛型 / 结构体表；段内只允许表达式（不含语句），花括号不嵌套。
        """
        parts = []
        buf = []
        i, n = 0, len(text)
        while i < n:
            c = text[i]
            if c == "{" and i + 1 < n and text[i + 1] == "{":
                buf.append("{")
                i += 2
                continue
            if c == "}" and i + 1 < n and text[i + 1] == "}":
                buf.append("}")
                i += 2
                continue
            if c == "{":
                j = text.find("}", i + 1)
                if j < 0:
                    raise SyntaxError(f"line {line}: 字符串插值缺少右花括号")
                if buf:
                    parts.append(("str", "".join(buf)))
                    buf = []
                inner = text[i + 1:j].strip()
                if not inner:
                    raise SyntaxError(f"line {line}: 插值表达式为空")
                parts.append(self._parse_interp_expr(inner, line))
                i = j + 1
                continue
            buf.append(c)
            i += 1
        if buf:
            parts.append(("str", "".join(buf)))
        if not parts:
            parts.append(("str", ""))
        return ("interp", parts)

    def _parse_interp_expr(self, text, line):
        sub = Parser(tokenize(text), consts=self.consts,
                     generic_fns=self.generic_fns)
        sub.structs.update(self.structs)
        sub.enums.update(self.enums)
        sub.generic_structs.update(self.generic_structs)
        sub.const_fns.update(self.const_fns)
        e = sub.parse_expr()
        if not sub.at("EOF"):
            raise SyntaxError(
                f"line {line}: 插值表达式有多余记号 {sub.peek().val!r}"
                "（插值里只能放一个表达式）")
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

    # ---- 闭包字面量（v1.95）----
    def parse_lambda(self):
        """`fn(x: int) -> int { ... }` —— 表达式位置的匿名函数（闭包）。

        与顶层 `fn` 声明的区别只有两点：没有名字、捕获外层局部变量（按值，
        创建时快照）。返回值类型必须写（`-> T`）；省略时按 void。
        函数体必须是块；块内最后一条表达式语句即返回值（等价于 `return`），
        也可显式 `return`。"""
        t = self.eat("fn")
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
        if not self.at("SYM", "{"):
            raise SyntaxError(
                f"line {t.line}: 闭包字面量必须有函数体 {{ ... }}")
        body = self.parse_block()
        names = [n for n, _ in params]
        if len(set(names)) != len(names):
            raise SyntaxError(f"line {t.line}: 闭包形参重名：{names}")
        return ("lambda", params, ret, body, t.line)

    def parse_primary(self):
        t = self.peek()
        if t.kind == "fn":
            # 闭包字面量（v1.95）：`fn` 只在顶层是声明关键字，在表达式位置
            # 没有别的解释，因此无需前瞻即可判定。
            return self.parse_lambda()
        if t.kind == "match":
            return self.parse_match()
        if t.kind == "select":
            # select { c1.recv(), c2.recv() } -> 首个就绪臂的值（v0.11）
            # 声明序优先；轮询 + yield 等待；全部关闭且排空 -> 0
            self.next()
            self.eat("SYM", "{")
            arms = []
            while not self.at("SYM", "}"):
                arms.append(self.parse_expr())
                if self.at("SYM", ","):
                    self.next()
            self.eat("SYM", "}")
            if not arms:
                raise SyntaxError(f"line {t.line}: select 至少需要一个 recv 臂")
            return ("select", arms)
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
        if t.kind == "vec":
            # vec[T].new(cap)
            self.next()
            self.eat("SYM", "[")
            et = self.parse_type()
            self.eat("SYM", "]")
            vec_elem_tag(et, t.line)
            self.eat("SYM", ".")
            meth = self.eat("NAME").val
            if meth != "new":
                raise SyntaxError(f"line {t.line}: vec[T] 只支持 .new(cap)")
            self.eat("SYM", "(")
            args = self.parse_args()
            return ("vecnew", et, args)
        if t.kind == "map":
            # map[K]V.new(cap) -> 开放寻址哈希表句柄（cap 须 2 的幂，省略默认 16）
            # 注意：值类型只取单段名字，否则 parse_type 的限定名循环会把
            # `int.new` 整个吞成类型名（历史坑：构造表达式必须与类型位分开）。
            self.next()
            self.eat("SYM", "[")
            kt = self.parse_type()
            self.eat("SYM", "]")
            if self.at("SYM", "[") or self.at("chan") or self.at("option") \
                    or self.at("result") or self.at("map"):
                vt = self.parse_type()      # 复合值类型：留给校验统一报错
            else:
                vt = ("named", self.eat("NAME").val)
            map_kv_tag(kt, "键类型", t.line)
            map_kv_tag(vt, "值类型", t.line)
            self.eat("SYM", ".")
            self.eat("NAME", "new")
            self.eat("SYM", "(")
            args = self.parse_args()
            if len(args) > 1:
                raise SyntaxError(f"line {t.line}: map[K]V.new(cap) 至多一个容量实参")
            if args:
                v = map_lit_cap(args[0])
                if v is not None and (v < 1 or (v & (v - 1)) != 0):
                    raise SyntaxError(
                        f"line {t.line}: map[K]V.new 容量必须是 2 的幂，得到 {v}")
            return ("mapnew", ("map", kt, vt), args)
        if t.kind == "option":
            # option[T].some(x) / option[T].none() -> 合成枚举构造（脱糖为 enumlit）
            self.next()
            self.eat("SYM", "[")
            tt = self.parse_type()
            self.eat("SYM", "]")
            name = self.ensure_option_enum(tt, t.line)
            self.eat("SYM", ".")
            meth = self.eat("NAME").val
            self.eat("SYM", "(")
            args = self.parse_args()
            if meth == "some" and len(args) == 1:
                return ("enumlit", [name, "Some"], [("value", args[0])])
            if meth == "none" and len(args) == 0:
                return ("enumlit", [name, "None"], [])
            raise SyntaxError(f"line {t.line}: option[T].{meth} 用法无效（仅 some(x)/none()）")
        if t.kind == "result":
            # result[T,E].ok(x) / result[T,E].err(e) -> 合成枚举构造（脱糖为 enumlit）
            self.next()
            self.eat("SYM", "[")
            tt = self.parse_type()
            self.eat("SYM", ",")
            et = self.parse_type()
            self.eat("SYM", "]")
            name = self.ensure_result_enum(tt, et, t.line)
            self.eat("SYM", ".")
            meth = self.eat("NAME").val
            self.eat("SYM", "(")
            args = self.parse_args()
            if meth == "ok" and len(args) == 1:
                return ("enumlit", [name, "Ok"], [("value", args[0])])
            if meth == "err" and len(args) == 1:
                return ("enumlit", [name, "Err"], [("error", args[0])])
            raise SyntaxError(f"line {t.line}: result[T,E].{meth} 用法无效（仅 ok(x)/err(e)）")
        if t.kind == "SYM" and t.val == "[":
            # 定长数组字面量：[1, 2, 3]（v0.6 只支持数值元素）
            self.next()
            elems = []
            while not self.at("SYM", "]"):
                elems.append(self.parse_expr())
                if self.at("SYM", ","):
                    self.next()
            self.eat("SYM", "]")
            if not elems:
                raise SyntaxError(f"line {t.line}: 空数组字面量暂不支持")
            return ("arraylit", elems)
        if t.kind == "INT":
            self.next()
            return ("num", t.val)
        if t.kind == "FLOAT":
            self.next()
            return ("fnum", t.val[0], t.val[1])   # (值, "f32"|"f64")
        if t.kind == "STR":
            self.next()
            return ("str", t.val)
        if t.kind == "FSTR":
            # 插值字符串（v1.61）：f"x={x}, n={n}" —— {{ / }} 是转义
            self.next()
            return self._parse_interp(t.val, t.line)
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
            # 顶层 const 内联：只在"不是函数调用/成员访问"时替换
            if t.val in self.consts and not (
                    self.at("SYM", "(") or self.at("SYM", ".")):
                return self.consts[t.val]
            # 点路径（仅吸收非方法调用的 .NAME 段；NAME( 留给 postfix 处理方法调用）
            path = [t.val]
            if self.at("SYM", "[") and t.val in self.generic_enums:
                # 泛型 enum 构造（v1.63）：Opt[int].Some(v: 1) / Opt[int].None
                # 先把类型实参单态化成 Opt__int，再交给 postfix 的枚举变体分支
                self.next()
                targs = [self.parse_type()]
                while self.at("SYM", ","):
                    self.next()
                    targs.append(self.parse_type())
                self.eat("SYM", "]")
                path = [self._instantiate_enum(t.val, targs, t.line)]
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
            if self.at("SYM", "{") and len(path) == 1 \
                    and path[0] in (self._cur_tparams or []):
                # 泛型体内的 `T { ... }` 字面量（v1.11）：T 是当前 fn 的
                # 类型参数，不是具体 struct——生成占位节点，单态化时替换
                # 为 ("structlit", 实例类型, fields)（Lower 照常校验字段）。
                self.next()
                fields = {}
                while not self.at("SYM", "}"):
                    fname = self.eat("NAME").val
                    self.eat("SYM", ":")
                    fields[fname] = self.parse_expr()
                    if self.at("SYM", ","):
                        self.next()
                self.eat("SYM", "}")
                return ("tp_lit", path[0], fields)
            if self.at("SYM", "[") and len(path) == 1 \
                    and path[0] in self.generic_structs:
                # 泛型 struct 字面量（v1.59）：Box[int] { value: 1 }
                # 类型实参必须显式写——字面量不做类型推导（字段值推不出 T）。
                self.next()
                targs = [self.parse_type()]
                while self.at("SYM", ","):
                    self.next()
                    targs.append(self.parse_type())
                self.eat("SYM", "]")
                iname = self._instantiate_struct(path[0], targs, self.peek().line)
                if not self.at("SYM", "{"):
                    raise SyntaxError(
                        f"line {self.peek().line}: 泛型 struct {path[0]} 的实例化"
                        "只用于类型位置与结构体字面量（后面要跟 { 字段 }）")
                self.next()
                gfields = {}
                while not self.at("SYM", "}"):
                    fname = self.eat("NAME").val
                    self.eat("SYM", ":")
                    gfields[fname] = self.parse_expr()
                    if self.at("SYM", ","):
                        self.next()
                self.eat("SYM", "}")
                return ("structlit", [iname], gfields)
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
            if self.at("SYM", "[") and len(path) == 1 \
                    and path[0] in _REFL_FUNCS:
                # 编译期反射（v1.71）：refl_field_count[Point]()
                # 节点先原样留在 AST 里，parse_program 末尾统一折叠成常量——
                # 这样反射可以写在使用点的**前面**（类型尚未解析完）。
                g = self.next()
                rty = self.parse_type()
                self.eat("SYM", "]")
                self.eat("SYM", "(")
                rargs = self.parse_args()   # parse_args 自己吃掉 ')'
                return ("refl", path[0], rty, rargs, g.line)
            if self.at("SYM", "[") and len(path) == 1 and path[0] in self.generic_fns:
                # 泛型显式实例化：f[int, str](...)（v1.11 单参；v1.36 多参）。
                # 之所以不歧义：语言没有"下标后调用"（函数指针数组），
                # 而 f 在泛型模板集合里——唯一解释就是实例化。
                g = self.next()
                tys = [self.parse_type()]
                while self.at("SYM", ","):
                    self.next()
                    tys.append(self.parse_type())
                for ty in tys:
                    if ty[0] != "named" or "." in ty[1]:
                        raise SyntaxError(
                            f"line {g.line}: 泛型实参只支持具名类型"
                            "（标量 / struct / enum；vec/map 嵌套见 07-gaps §1）")
                self.eat("SYM", "]")
                self.eat("SYM", "(")
                args = self.parse_args()
                if any(a[0] == "namedarg" for a in args):
                    raise SyntaxError(f"line {g.line}: 泛型调用不支持命名实参")
                return ("gcall", path[0], tuple(t[1] for t in tys), args, g.line)
            if self.at("SYM", "("):
                self.next()
                args = self.parse_args()
                if ev is not None:
                    return self.mk_enumlit(path, args, t.line)
                if any(a[0] == "namedarg" for a in args):
                    raise SyntaxError(f"line {t.line}: 普通函数调用不支持命名实参")
                if len(path) == 1 and path[0] in self.generic_fns:
                    # 泛型隐式调用（v1.36）：f(...) 不带类型方括号——
                    # 类型实参在单态化期由实参推导（_GenInfer），推不出就
                    # 报错并提示显式实例化。跨文件前向泛型（被调用方后解析）
                    # 仍要求显式方括号——解析期还不知道它是泛型。
                    return ("gcall_infer", path[0], args, t.line)
                return ("call", path, args)
            if ev is not None:
                # 無載荷變體：`Color.Red` 即值
                return self.mk_enumlit(path, [], t.line)
            return ("path", path) if len(path) > 1 else ("name", path[0])
        raise SyntaxError(f"line {t.line}: 意外的记号 {t.val!r}")


# ---------------------------------------------------------------------------
# 2b. 测试块合成（SPEC §8 `quelmara test`）
# ---------------------------------------------------------------------------


def parse_source(src, with_docs=False):
    """解析源码 -> (module, imports, fns, tests, structs, enums, decl_order)

    doc comment（v1.92）：声明上的 `///` 会挂成 f["doc"]；`with_docs=True`
    时再多返回 (type_docs, module_doc)，供 quelmara doc / 测试使用。
    """
    p = Parser(tokenize(src), src=src)
    r = p.parse_program()
    return r + (p.type_docs, p.module_doc) if with_docs else r


def _import_candidates(imp, src_dir):
    """import a.b.c 的候选文件：主文件目录优先，标准库 std/（仓库根）其次。
    （qpm 依赖目录由 _qpm_candidates 单独提供——始终按主项目根解析。）"""
    parts = imp.split(".")
    rel = os.sep.join(parts) + SRC_EXT
    std_root = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "std"))
    rel_in_std = (os.sep.join(parts[1:]) + SRC_EXT) if parts[0] == "std" else rel
    return [os.path.normpath(os.path.join(src_dir, rel)),
            os.path.join(std_root, rel_in_std)]


def _qpm_candidates(imp, main_dir):
    """qpm 依赖的 import 候选：<main_dir>/.qpm/deps/<a>/<b>.qma（v1.14）。
    由 qpm.py install 填充（git 依赖从全局缓存复制、路径依赖直接复制）。"""
    parts = imp.split(".")
    rel = os.sep.join(parts) + SRC_EXT
    return [os.path.normpath(os.path.join(main_dir, ".qpm", "deps", rel))]


# ---------------------------------------------------------------------------
# 2c. 用户泛型：多类型参数 + 调用点推导（v1.36）
# ---------------------------------------------------------------------------

_GEN_SCALARS = {"int", "i64", "i32", "i16", "i8", "u64", "u32", "u16", "u8",
                "bool", "str", "float", "f64", "f32"}
_GEN_INTS = {"int", "i64", "i32", "i16", "i8", "u64", "u32", "u16", "u8"}

# ---------------------------------------------------------------------------
# 2d. 类型约束（trait bound，v1.61）
# ---------------------------------------------------------------------------
# 约束名 -> 它授权模板体使用的运算符。检查分三层：
#   * 声明期（模板本身）：体内对 T 用到的每个运算符都必须被声明的约束覆盖，
#     否则报"约束不足"——约束是给调用方的契约，必须诚实；
#   * 实例化期：类型实参必须满足声明的约束；
#   * 实例化期：未声明约束的模板也要按"体内实际用到的运算符"逐条核对具体
#     类型（否则 struct 会被静默地按地址比较——v1.61 之前的真实坑）。
# 具体类型口径与 Lower 的实际行为一致（tests/t101_bounds.qma 逐条钉住）：
#   * Ord：整数族 + 浮点 + str（v1.66 起 str 按字典序）。struct 的 < 是地址比较，不算支持；
#   * Eq ：整数族 + 浮点 + bool + str。**聚合（struct/enum）不算**——
#          `Color.Red == Color.Red` 实测为 false，比较的是聚合的地址
#          （见 docs/07-gaps.md §7.6）；
#   * Num：整数族 + 浮点（str 只有 + 拼接，不算 Num）；
#   * Bit：仅整数族。
_BOUND_CAPS = ("Ord", "Eq", "Num", "Bit", "Show")

_BOUND_OPS = {
    "Ord": ("<", "<=", ">", ">="),
    "Eq": ("==", "!="),
    "Num": ("+", "-", "*", "/", "%"),
    "Bit": ("&", "|", "^", "<<", ">>", ">>>", "~"),
    # to_str 是方法不是运算符，但同样是"能力"：只有标量与 str 能转文本，
    # 聚合值调 to_str 会拿到指针数字（v1.64 起用 Show 约束在编译期拦）
    "Show": ("to_str",),
}

_FLOAT_NAMES = ("f64", "f32", "float")


def _cap_supports(cap, tyname):
    """具体类型 tyname 是否满足能力约束 cap（口径见上方注释）。"""
    if cap == "Ord":
        # str 自 v1.66 起按字节字典序比较（此前 < 是地址比较，故不在表里）
        return (tyname in _GEN_INTS or tyname in _FLOAT_NAMES
                or tyname == "str")
    if cap == "Eq":
        return (tyname in _GEN_INTS or tyname in _FLOAT_NAMES
                or tyname in ("bool", "str"))
    if cap == "Num":
        return tyname in _GEN_INTS or tyname in _FLOAT_NAMES
    if cap == "Bit":
        return tyname in _GEN_INTS
    if cap == "Show":
        return (tyname in _GEN_INTS or tyname in _FLOAT_NAMES
                or tyname in ("bool", "str"))
    return False


def _cap_for_op(op):
    """运算符 -> 需要的能力约束；无对应约束（如 str 拼接之外的 ==）返回 None。"""
    for cap in _BOUND_CAPS:
        if op in _BOUND_OPS[cap]:
            return cap
    return None


def _cap_desc(cap):
    return {"Ord": "整数/浮点/str（可比较大小）",
            "Eq": "整数/浮点/bool/str（可判等）",
            "Num": "整数/浮点（可四则运算）",
            "Bit": "整数（可位运算）",
            "Show": "整数/浮点/bool/str（可 to_str）"}.get(cap, cap)


# ---------------------------------------------------------------------------
# 2e. 属性宏 @derive + 编译期反射（v1.71）+ 通用 token 宏（v1.96）
# ---------------------------------------------------------------------------
# 语言没有运行时元数据段。这一层给的是**纯编译期**能力：
#
#   * `@derive(Json, Eq, Show)` 作用在 struct/enum 声明上，按**字段表**生成
#     `<T>__json` / `<T>__json_into` / `<T>_from_json` / `<T>__eq` / `<T>__show`
#     等普通函数——产物与手写字段表逐字等价（同一套 AST、同一套 Lower，
#     零运行时元数据、零动态派发）。序列化从此不用再抄字段名。
#   * `macro 名字(形参) { 记号 }` 是**通用 token 宏**（v1.96）：语法分析之前
#     按记号替换展开，任何语法位置都能用（语句、表达式、类型、甚至 @derive
#     注解本身）。无卫生性，宏体与调用点同作用域。
#   * `refl_*[T](i)` 在解析期折叠成 int / str 字面量；下标不是常量时改写成
#     按需生成的查表函数（v1.96，仍无元数据段）。
#
# 边界（同步写在 docs/02-language.md §4.8）：
#   * 泛型 struct / 泛型 enum 模板不能直接派生（字段类型还是类型参数）；
#   * Json 支持 int 族 / bool / str / f64 / 嵌套 struct·enum / vec[这些]；
#   * 无卫生性：宏形参按记号替换，不加括号。
_MACRO_MAX_DEPTH = 64
_DERIVE_ITEMS = ("Json", "Eq", "Show")
_DERIVE_INT_TYPES = {"int", "i64", "i32", "i16", "i8",
                     "u64", "u32", "u16", "u8", "byte"}
_REFL_FUNCS = ("refl_type_name", "refl_field_count", "refl_field_name",
               "refl_field_type", "refl_variant_count", "refl_variant_name",
               "refl_variant_arity")


def _iter_bound_ops(body, infer, env):
    """遍历函数体，产出 (op, 左操作数类型, 右操作数类型)。

    只产出**运算符**节点（binop / 复合赋值 / 一元 -~）；类型推断失败的
    一侧给 None。语句与表达式统一递归——AST 里 tuple/list 不会成环。
    """
    def ty(e):
        try:
            return infer.infer(e, env)
        except Exception:          # 推断是尽力而为：拿不到类型就跳过
            return None

    def walk(x):
        if isinstance(x, list):
            for v in x:
                yield from walk(v)
            return
        if not isinstance(x, tuple) or not x:
            return
        k = x[0]
        if k == "binop" and len(x) == 4:
            yield (x[1], ty(x[2]), ty(x[3]))
        elif k == "unop" and len(x) == 3:
            yield (x[1], ty(x[2]), None)
        elif k == "method" and len(x) == 4 and x[2] == "to_str":
            # to_str 能力（Show 约束）：只对标量/str 成立
            yield ("to_str", ty(x[1]), None)
        elif k == "assign" and len(x) == 4 and x[2] != "=":
            # 复合赋值 x += e 等价于 x = x + e
            yield (x[2][:-1], ty(("name", x[1])), ty(x[3]))
        for v in x[1:]:
            yield from walk(v)

    yield from walk(body)


def _named(t):
    """("named", X) -> X；其余返回 None。"""
    if isinstance(t, tuple) and len(t) == 2 and t[0] == "named":
        return t[1]
    return None


def _bound_list_str(bounds):
    return " + ".join(bounds) if bounds else "（无）"


def _ty_str(t):
    """类型 AST -> 可读串（错误信息用）"""
    if t is None:
        return "void"
    if not isinstance(t, tuple):
        return repr(t)
    k = t[0]
    if k == "named":
        return t[1]
    if k == "vec":
        return "vec[" + _ty_str(t[1]) + "]"
    if k == "map":
        return "map[" + _ty_str(t[1]) + "]" + _ty_str(t[2])
    if k == "slice":
        return "[]" + _ty_str(t[1])
    if k == "array":
        return "[" + str(t[1]) + "]" + _ty_str(t[2])
    if k == "rc":
        return "rc[" + _ty_str(t[1]) + "]"
    if k == "chan":
        return "chan[" + _ty_str(t[1]) + "]"
    return k


def _ty_subst(t, mapping):
    """类型 AST 的类型参数替换（named/vec/map/slice/array/rc/chan 全形态）。
    变量引用是 ("name", s)、类型是 ("named", s)——替换只认后者，天然不撞。"""
    if not isinstance(t, tuple):
        return t
    k = t[0]
    if k == "named" and len(t) == 2 and t[1] in mapping:
        return ("named", mapping[t[1]])
    if k == "vec":
        return ("vec", _ty_subst(t[1], mapping))
    if k == "map":
        return ("map", _ty_subst(t[1], mapping), _ty_subst(t[2], mapping))
    if k == "slice":
        return ("slice", _ty_subst(t[1], mapping))
    if k == "array":
        return ("array", t[1], _ty_subst(t[2], mapping))
    if k == "rc":
        return ("rc", _ty_subst(t[1], mapping))
    if k == "chan":
        return ("chan", _ty_subst(t[1], mapping))
    return t


def _subst_gimpl(x, tp_map):
    """泛型 impl 模板物化时的替换（v1.62）：类型参数名 -> 具体类型名。

    与 expand_generics.subst 的分工：这里只做**纯改名**——impl 模板的方法体
    在解析期就是完整 AST（没有 gcall 之外的类型痕迹），替换点只有三处：
      * ("named", "T") / ("named", "Box__T")  类型位置与标注
      * ("tp_lit", "T")                       `T { ... }` 占位字面量
      * ("gcall", f, ("T",), ...)             显式实例化的类型方括号
    变量名是 ("name", s)，与类型 ("named", s) 不同标签，天然不会被误替换。
    """
    if isinstance(x, tuple):
        if x and x[0] == "named" and len(x) == 2 and x[1] in tp_map:
            return ("named", tp_map[x[1]])
        if x and x[0] == "tp_lit" and x[1] in tp_map:
            return ("structlit", [tp_map[x[1]]],
                    {k: _subst_gimpl(v, tp_map) for k, v in x[2].items()})
        if x and x[0] in ("structlit", "enumlit", "pat") and len(x) >= 3 \
                and isinstance(x[1], list):
            # 字面量的类型名是**字符串列表**（不是 ("named", s)），
            # Pair[T, int] { ... } 的路径要单独换名
            return (x[0], [tp_map.get(p, p) for p in x[1]],
                    _subst_gimpl(x[2], tp_map))
        if x and x[0] == "gcall" and len(x) >= 4:
            return ("gcall", x[1], tuple(tp_map.get(t, t) for t in x[2]),
                    [_subst_gimpl(a, tp_map) for a in x[3]],
                    x[4] if len(x) > 4 else 0)
        return tuple(_subst_gimpl(v, tp_map) for v in x)
    if isinstance(x, list):
        return [_subst_gimpl(v, tp_map) for v in x]
    return x


class _GenInfer:
    """泛型调用点推导（v1.36）：函数内轻量类型环境 + 一元化。

    推导来源：int/float/str/bool 字面量、结构体与枚举字面量、非泛型函数
    返回类型、泛型实例返回类型、let 标注与变量环境、vec/map/array 元素
    一元化、结构体字段类型。

    推断是**流不敏感、尽力而为**的：推不出就返回 None——单态化期据此报错
    （提示显式实例化），环境构建期静默放弃。推导只决定"实例化到哪个类型"，
    真实类型检查仍由 Lower 负责（实例的形参/实参类型不匹配由 Lower 报）。
    """

    def __init__(self, generic_fns, structs, enums, fn_ret):
        self.generic_fns = generic_fns
        self.structs = structs
        self.enums = enums
        self.fn_ret = fn_ret

    # ---- 表达式 -> 类型（tp_map：当前实例映射，应用于推断结果） ----
    def infer(self, e, env, tp_map=None):
        t = self._infer(e, env)
        if t is None:
            return None
        return _ty_subst(t, tp_map) if tp_map else t

    def _infer(self, e, env):
        if not isinstance(e, tuple) or not e:
            return None
        k = e[0]
        if k == "num":
            v = e[1]
            if isinstance(v, bool):
                return ("named", "bool")
            return ("named", "int") if isinstance(v, int) else ("named", "float")
        if k == "fnum":
            # ("fnum", 值, "f32"|"f64")——浮点字面量（v0.10 起的形态）
            return ("named", e[2])
        if k == "vecnew":
            return ("vec", e[1])          # vec[T].new(cap)
        if k == "mapnew":
            return e[1]                   # ("map", kt, vt)
        if k == "chanopen":
            return ("chan", e[1])
        if k == "arraylit" and e[1]:
            return ("array", len(e[1]), self._infer(e[1][0], env))
        if k == "str":
            return ("named", "str")
        if k == "bool":
            return ("named", "bool")
        if k == "name":
            return env.get(e[1])
        if k == "structlit" and len(e[1]) == 1 and e[1][0] in self.structs:
            return ("named", e[1][0])
        if k == "lambda":
            # 闭包字面量（v1.95）：静态类型就是 `closure`（{code, env} 两字）。
            return ("named", "closure")
        if k == "enumlit" and e[1] and e[1][0] in self.enums:
            return ("named", e[1][0])
        if k == "call" and len(e[1]) == 1 and e[1][0] not in env:
            return self._call_ret(e[1][0], e[2], env)
        if k == "gcall_infer":
            got = self.infer_gcall(e[1], e[2], env, None, None, False)
            return got[1] if got else None
        if k == "gcall":
            return self._gcall_ret(e[1], e[2], e[3])
        if k == "index":
            at = self._infer(e[1], env)
            if at is not None and at[0] == "named" and at[1] == "str":
                return ("named", "int")     # str 下标得字节值
            return self._elem(at)
        if k == "sliceof":
            el = self._elem(self._infer(e[1], env))
            return ("slice", el) if el is not None else None
        if k == "field":
            st = self._infer(e[1])
            if st is not None and st[0] == "named" and st[1] in self.structs:
                for fn_, ft in self.structs[st[1]]:
                    if fn_ == e[2]:
                        return ft
            return None
        if k == "binop":
            return self._binop_ty(e, env)
        if k == "unop":
            if e[1] == "!":
                return ("named", "bool")
            return self._infer(e[2], env) or ("named", "int")
        if k == "method":
            return self._method_ty(e, env)
        return None

    def _binop_ty(self, e, env):
        op = e[1]
        ta, tb = self._infer(e[2], env), self._infer(e[3], env)
        if op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
            return ("named", "bool")
        if op == "+" and ((ta or ("",))[1:2] == ("str",)
                          or (tb or ("",))[1:2] == ("str",)):
            return ("named", "str")
        names = [t[1] for t in (ta, tb)
                 if t is not None and t[0] == "named"]
        if any(n in ("float", "f64", "f32") for n in names):
            return ("named", "float")
        if names and all(n in _GEN_INTS for n in names):
            return ta if ta == tb else ("named", "int")
        return None

    def _method_ty(self, e, env):
        ot = self._infer(e[1], env)
        if e[2] == "len":
            return ("named", "int")
        if ot is None:
            return None
        if ot[0] == "vec" and e[2] in ("get", "pop"):
            return ot[1]
        if ot[0] == "map" and e[2] == "get":
            return ot[2]
        return None

    def _elem(self, t):
        if not isinstance(t, tuple):
            return None
        if t[0] in ("vec", "slice"):
            return t[1]
        if t[0] in ("map", "array"):
            return t[-1]
        return None

    def _call_ret(self, fname, args, env):
        if fname in self.generic_fns:
            got = self.infer_gcall(fname, args, env, None, None, False)
            return got[1] if got else None
        return self.fn_ret.get(fname)

    def _gcall_ret(self, fname, tynames, args):
        """显式实例化调用的返回类型（环境构建期用；类型实参可含符号参数）"""
        tmpl = self.generic_fns.get(fname)
        if tmpl is None:
            return None
        tps = tmpl.get("type_params") or []
        if len(tynames) != len(tps):
            return None
        return _ty_subst(tmpl.get("ret"), dict(zip(tps, tynames)))

    # ---- 一元化 ----
    def unify(self, tpl_ty, arg_ty, bindings, tps, line, fname, strict):
        """模板形参类型 tpl_ty 与实参类型 arg_ty 对齐，填充 bindings[T] = 类型。
        容器形态递归（vec[T] ~ vec[int] 推出 T=int）；结构相同返回 True。"""
        if not isinstance(tpl_ty, tuple) or not isinstance(arg_ty, tuple):
            return False
        if tpl_ty[0] == "named" and len(tpl_ty) == 2 and tpl_ty[1] in tps:
            prev = bindings.get(tpl_ty[1])
            if prev is None:
                if not self._legal(arg_ty):
                    if strict:
                        raise SyntaxError(
                            f"line {line}: 泛型 {fname} 的类型参数 {tpl_ty[1]} "
                            f"推导为 {_ty_str(arg_ty)}——泛型实参只支持具名类型"
                            "（标量 / struct / enum）")
                    return False
                bindings[tpl_ty[1]] = arg_ty
            elif _ty_str(prev) != _ty_str(arg_ty):
                if strict:
                    raise SyntaxError(
                        f"line {line}: 泛型 {fname} 的类型参数 {tpl_ty[1]} "
                        f"推导冲突：{_ty_str(prev)} vs {_ty_str(arg_ty)}")
                return False
            return True
        if tpl_ty[0] in ("vec", "slice", "rc", "chan") \
                and arg_ty[0] == tpl_ty[0]:
            return self.unify(tpl_ty[1], arg_ty[1], bindings, tps,
                              line, fname, strict)
        if tpl_ty[0] == "array" and arg_ty[0] == "array" \
                and tpl_ty[1] == arg_ty[1]:
            return self.unify(tpl_ty[2], arg_ty[2], bindings, tps,
                              line, fname, strict)
        if tpl_ty[0] == "map" and arg_ty[0] == "map":
            return (self.unify(tpl_ty[1], arg_ty[1], bindings, tps,
                               line, fname, strict)
                    or self.unify(tpl_ty[2], arg_ty[2], bindings, tps,
                                  line, fname, strict))
        if _ty_str(tpl_ty) == _ty_str(arg_ty):
            return True     # 结构相同、无类型参数——不绑定但算匹配
        return False

    def _legal(self, t):
        return (isinstance(t, tuple) and t[0] == "named" and len(t) == 2
                and "." not in t[1]
                and (t[1] in _GEN_SCALARS or t[1] in self.structs
                     or t[1] in self.enums))

    # ---- 推导入口 ----
    def infer_gcall(self, fname, args, env, tp_map, line, strict):
        """推导泛型调用的类型实参。strict=True 时推不出/冲突即报错。
        返回 (类型实参元组, 实例返回类型)；非 strict 失败返回 None。"""
        tmpl = self.generic_fns.get(fname)
        if tmpl is None:
            if strict:
                raise SyntaxError(f"line {line}: {fname!r} 不是泛型函数")
            return None
        tps = tmpl.get("type_params") or []
        bindings = {}
        for (pname, pty), arg in zip(tmpl.get("params") or [], args or []):
            aty = self.infer(arg, env, tp_map)
            self.unify(pty, aty, bindings, tps, line, fname, strict)
        missing = [tp for tp in tps if tp not in bindings]
        if missing:
            if strict:
                raise SyntaxError(
                    f"line {line}: 泛型调用 {fname}(...) 推不出类型参数 "
                    + ", ".join(missing)
                    + f"——请显式实例化 {fname}[{', '.join(tps)}](...)，"
                    "或让至少一个实参的类型可推导（字面量 / 标注 / 具名返回）")
            return None
        tynames = tuple(bindings[tp][1] for tp in tps)
        return tynames, _ty_subst(tmpl.get("ret"), bindings)

    # ---- 变量类型环境（流不敏感、按语句序、后写覆盖） ----
    def compute_env(self, body, params):
        env = {}
        for n, t in (params or []):
            env[n] = t
        self._walk_stmts(body, env)
        return env

    def _walk_stmts(self, stmts, env):
        if not isinstance(stmts, list):
            return
        for s in stmts:
            self._walk_stmt(s, env)

    def _walk_stmt(self, s, env):
        if not isinstance(s, tuple) or not s:
            return
        k = s[0]
        if k == "lambda":
            # 闭包体是**另一个作用域**（v1.95）：它的 let 不能污染外层推断表，
            # 捕获由 Lower 按真实 env 处理。
            return
        if k == "let":
            anno = (s[4][1] if len(s) > 4 and isinstance(s[4], tuple)
                    and s[4][0] == "as" else None)
            if anno is not None:
                env[s[2]] = anno
            else:
                t = self._infer(s[3], env)
                if t is not None:
                    env[s[2]] = t
            return
        if k == "assign" and s[2] == "=":
            t = self._infer(s[3], env)
            if t is not None:
                env[s[1]] = t
            return
        if k in ("for", "parfor"):
            env[s[1]] = ("named", "int")
            self._walk_stmts(s[4], env)
            return
        if k == "foreach":
            el = self._elem(self._infer(s[2], env))
            if el is not None:
                env[s[1]] = el
            self._walk_stmts(s[3], env)
            return
        # 容器语句泛型递归（if/while/match/arena/annot/return/expr……）。
        # 表达式里没有语句定义，递归进去不会误绑变量。
        for v in s[1:]:
            if isinstance(v, list):
                self._walk_stmts(v, env)
            elif isinstance(v, tuple):
                self._walk_stmt(v, env)


def expand_generics(fns, generic_fns, structs, enums):
    """用户泛型单态化（v1.11 起；v1.36：多类型参数 + 调用点推导）。

    收集全部泛型调用（显式 gcall / 隐式 gcall_infer），按类型实参元组复制
    模板成具名实例 `f__T1_T2`：体内类型参数全替换、体内泛型调用递归实例化
    后降为普通 call。**Lower 与后端零改动**——pass 之后 AST 里不再有泛型
    痕迹（模板不进发射列表，只有实例存在）。

    v1.36 新增：
      * 多类型参数 `fn f[A, B](...)`；显式 `f[int, str](...)` 与隐式
        `f(...)`（类型实参由实参推导，_GenInfer：流不敏感、尽力而为）；
      * 隐式调用推不出全部类型参数时编译期报错并提示显式实例化；
      * 修掉 v1.11 埋的 tp_lit 形态 bug：`T { ... }` 单态化结果此前是
        ("structlit", <字符串>, ...)，多字符结构体名会被下游按字符 join
        （"Point" -> "P.o.i.n.t" 直接报错）——现改为路径列表，与解析器一致。

    支持范围（诚实边界，docs/07-gaps.md §1）：
      * 类型实参只接受具名类型（标量 / struct / enum）；容器类型实参不做；
      * T 可出现在：形参 / 返回值 / let 标注 / 嵌套容器元素（vec[T] 等）；
      * 泛型体内可调用其他泛型（含自递归，显式或推导）；
      * 泛型模板不支持注解（@simd/@extern），fail-fast 在 parse_program；
      * 推导是流不敏感的：分支里改绑类型可能推错，Lower 会抓住不匹配；
      * 类型约束（v1.61）：`[T: Ord + Eq]`（能力）与 `[T: Shape]`（接口）；
      * 不支持：泛型方法、泛型 enum。
    """
    import copy
    instances = {}   # (fname, 类型实参元组) -> 实例 fn dict（先注册后填体）

    infer = _GenInfer(generic_fns, structs, enums,
                      {f["name"]: f.get("ret") for f in fns})

    # 接口约束的实现表：impl Type : Iface 落成的函数带 impl_iface/self_type。
    impls = {(f.get("impl_iface"), f.get("self_type"))
             for f in fns if f.get("impl_iface")}

    def legal(tyname):
        return (tyname in _GEN_SCALARS or tyname in structs
                or tyname in enums)

    def check_declared(fname, tmpl, tp_map, line):
        """实例化期：类型实参必须满足模板声明的约束（v1.61）。"""
        for tp, bl in (tmpl.get("type_bounds") or {}).items():
            tyn = tp_map[tp]
            for b in bl:
                if b in _BOUND_CAPS:
                    if not _cap_supports(b, tyn):
                        raise SyntaxError(
                            f"line {line}: 泛型 {fname} 的类型参数 {tp} 声明了"
                            f"约束 {b}（{_cap_desc(b)}），实参 {tyn} 不满足")
                elif (b, tyn) not in impls:
                    raise SyntaxError(
                        f"line {line}: 泛型 {fname} 的类型参数 {tp} 声明了接口"
                        f"约束 {b}，但 {tyn} 没有 `impl {tyn} : {b}`"
                        "（interface 与 impl 必须同源文件）")

    def check_template_body(fname, tmpl):
        """声明期：体内对 T 用到的运算符必须被声明的约束覆盖（v1.61）。

        只在模板**声明了**约束时检查——没有约束的模板沿用旧行为（实例化
        期再按具体类型核对），这样 v1.60 及以前的泛型库不需要改一行。
        """
        bounds = tmpl.get("type_bounds") or {}
        if not bounds:
            return
        tps = set(tmpl.get("type_params") or [])
        env = infer.compute_env(tmpl.get("body"), tmpl.get("params"))
        for op, ta, tb in _iter_bound_ops(tmpl.get("body"), infer, env):
            cap = _cap_for_op(op)
            if cap is None:
                continue
            for t in (ta, tb):
                tp = _named(t)
                if tp not in tps:
                    continue
                if cap in bounds.get(tp, []):
                    continue
                raise SyntaxError(
                    f"line {tmpl.get('line', 0)}: 泛型 {fname} 的模板体对 {tp} "
                    f"使用了 {op}，但约束只声明了 {_bound_list_str(bounds.get(tp))}"
                    f"——请写成 [{tp}: {_bound_list_str(bounds.get(tp))} + {cap}]"
                    f"（{cap} = {_cap_desc(cap)}）")

    def check_instance_body(fname, iname, inst, tp_map, line):
        """实例化期：体内实际用到的运算，具体类型必须支持（v1.61）。

        这是"没有约束声明"的模板的安全网：struct 的 < 和 == 在 Lower 里
        是**地址比较**（静默算错），以前只有跑起来才发现。
        """
        targets = set(tp_map.values())
        back = {v: k for k, v in tp_map.items()}
        env = infer.compute_env(inst.get("body"), inst.get("params"))
        for op, ta, tb in _iter_bound_ops(inst.get("body"), infer, env):
            cap = _cap_for_op(op)
            if cap is None:
                continue
            for t in (ta, tb):
                tyn = _named(t)
                if tyn not in targets:
                    continue
                if op == "+" and tyn == "str":
                    continue                    # str 拼接：合法且常用
                if _cap_supports(cap, tyn):
                    continue
                raise SyntaxError(
                    f"line {line}: 泛型 {fname} 的实例 {iname}: 体内对 {tyn} "
                    f"使用了 {op}，但 {tyn} 不支持（{cap} 需要 {_cap_desc(cap)}）"
                    f"——请把模板的类型参数约束写成 [{back[tyn]}: {cap}]，"
                    "让违反在调用点就报错；或换类型实参")

    def ensure(fname, tynames, line):
        key = (fname, tynames)
        if key in instances:
            return instances[key]
        tmpl = generic_fns.get(fname)
        if tmpl is None:
            raise SyntaxError(f"line {line}: {fname!r} 不是泛型函数")
        tps = tmpl.get("type_params") or []
        if len(tynames) != len(tps):
            raise SyntaxError(
                f"line {line}: 泛型 {fname} 需要 {len(tps)} 个类型实参"
                f"（[{'、'.join(tps)}]），得到 {len(tynames)} 个")
        for tyn in tynames:
            if not legal(tyn):
                raise SyntaxError(
                    f"line {line}: 泛型实参 {tyn!r} 不是已知类型"
                    "（标量 / struct / enum）")
        tp_map = dict(zip(tps, tynames))
        check_declared(fname, tmpl, tp_map, line)
        inst = copy.deepcopy(tmpl)
        iname = fname + "__" + "_".join(tynames)
        if iname in {f["name"] for f in fns}:
            raise SyntaxError(
                f"泛型实例 {iname!r} 与已有函数重名（请改名）")
        inst["name"] = iname
        inst.pop("type_params", None)
        inst.pop("type_bounds", None)
        instances[key] = inst            # 先注册：体内自递归直接引用
        env = infer.compute_env(tmpl.get("body"), tmpl.get("params"))
        inst["params"] = [(n, _ty_subst(t, tp_map)) for n, t in inst["params"]]
        inst["ret"] = _ty_subst(inst.get("ret"), tp_map)
        inst["body"] = subst(inst.get("body"), tp_map, env)
        check_instance_body(fname, iname, inst, tp_map, line)
        return inst

    def subst(x, tp_map, env):
        # ("named", T) -> ("named", 实例类型)；tp_lit -> structlit（路径列表）；
        # gcall / gcall_infer -> 普通 call（实例名）。
        if isinstance(x, tuple):
            if x[0] == "named" and len(x) == 2 and x[1] in tp_map:
                return ("named", tp_map[x[1]])
            if x[0] == "tp_lit" and x[1] in tp_map:
                return ("structlit", [tp_map[x[1]]],
                        {k: subst(v, tp_map, env) for k, v in x[2].items()})
            if x[0] == "gcall":
                ty2 = tuple(tp_map.get(t, t) for t in x[2])
                inner = ensure(x[1], ty2, x[4] if len(x) > 4 else 0)
                return ("call", [inner["name"]],
                        [subst(a, tp_map, env) for a in x[3]])
            if x[0] == "gcall_infer":
                # ("gcall_infer", fname, args, line)——4 元素，行号在 x[3]
                got = infer.infer_gcall(x[1], x[2], env, tp_map, x[3], True)
                inner = ensure(x[1], got[0], x[3])
                return ("call", [inner["name"]],
                        [subst(a, tp_map, env) for a in x[2]])
            return tuple(subst(v, tp_map, env) for v in x)
        if isinstance(x, list):
            return [subst(v, tp_map, env) for v in x]
        return x

    # 声明期检查（v1.61）：带约束的模板即使一次都没被实例化，也必须自洽
    # （约束是给调用方的契约——体内用了约束没覆盖的运算就是契约撒谎）。
    for _t in generic_fns.values():
        if isinstance(_t, dict) and _t.get("type_bounds"):
            check_template_body(_t["name"], _t)

    out = []
    for f in fns:
        if f.get("type_params"):
            continue                       # 模板不发射（只有实例存在）
        env = infer.compute_env(f.get("body"), f.get("params"))
        f["body"] = subst(f.get("body"), {}, env)
        out.append(f)
    for inst in instances.values():
        out.append(inst)
    return out


_LINK_BUILTIN_TY = {"int", "i64", "i32", "i16", "i8", "u64", "u32", "u16",
                     "u8", "bool", "str", "void", "byte", "float", "f64",
                     "f32", "__self__"}


def link_modules(files, imp_of, main_ap, ifaces):
    """跨模块链接（v1.99）：per-module mangling + 限定引用解析。

    `files` = [(label, ap, res, (pub_types, gens, qrefs))]，`res` 就地改写。

    规则（`02-language.md` §1 是唯一事实来源）：

    * **只在一个文件里声明的名字一个字节都不改**——既有程序走的是同一条
      路径，输出逐字节不变（回归的全部用例都属于这一类）。
    * 同一个名字在 ≥2 个文件里声明（**跨模块同名声明**）时：导入方的同名
      声明加模块前缀 `<模块>__<名字>`；**主文件保留原名**（入口侧不用改）。
      前缀取 import 串（`std.json` -> `std__json`），与源码里的写法同源。
    * 限定引用 `lib.name` 解析到 lib 那个文件的最终名字（可能带前缀）；
      未限定引用按"本文件 > 唯一外部声明 > 歧义报错"解析。
    * 类型被 mangling 时，它的方法 / 派生函数（`T__m` / `T__json` …）跟着
      换前缀——Lower 的派发按 `Type__method` 拼名字，两边必须一致。

    返回新的 files（顺序不变）。
    """
    # ---- 模块前缀 ----
    best_imp = {}
    for (fap, imp), tap in imp_of.items():
        cur = best_imp.get(tap)
        if cur is None or len(imp) < len(cur):
            best_imp[tap] = imp
    key_of = {ap: imp.replace(".", "__") for ap, imp in best_imp.items()}
    key_of[main_ap] = "main"
    used = {}
    for ap in list(key_of):
        k = key_of[ap]
        if k in used:
            used[k] += 1
            key_of[ap] = f"{k}_{used[k]}"
        else:
            used[k] = 1

    # ---- 声明表 ----
    fn_decls, ty_decls, pub_fn, pub_ty = {}, {}, {}, {}
    for label, ap, res, pex in files:
        fn_decls[ap] = {f["name"] for f in res[2]}
        ty_decls[ap] = {k for k in list(res[4]) + list(res[5])
                        if k not in ifaces and k != "closure"}
        pub_fn[ap] = {f["name"] for f in res[2] if f.get("pub")}
        pub_ty[ap] = set(pex[0])
    label_of = {ap: label for label, ap, _r, _p in files}

    def _owners(table):
        out = {}
        for ap, names in table.items():
            for n in names:
                out.setdefault(n, []).append(ap)
        return out
    fn_owners, ty_owners = _owners(fn_decls), _owners(ty_decls)

    def _dups(owners):
        return {n: aps for n, aps in owners.items() if len(aps) > 1}
    fn_dup, ty_dup = _dups(fn_owners), _dups(ty_owners)
    fn_dup.pop("main", None)

    # ---- 改名表（主文件不动）----
    ren = {ap: {} for ap in fn_decls}
    for n, aps in list(fn_dup.items()) + list(ty_dup.items()):
        for ap in aps:
            if ap != main_ap:
                ren[ap][n] = f"{key_of[ap]}__{n}"
    if not fn_dup and not ty_dup:
        # 没有跨模块同名：只需要解析限定引用（下面同一套代码走一遍）
        pass

    def _final(ap, name):
        return ren[ap].get(name, name)

    def _split_q(n):
        return n.split(QSEP, 1) if QSEP in n else None

    def _resolve(enc, ap, label, ns):
        """限定引用 -> 目标文件的最终名字（并校验存在 + pub）。"""
        q = _split_q(enc)
        imp, name = q
        tgt = imp_of.get((ap, imp))
        if tgt is None:
            raise SyntaxError(
                f"{label}: 限定引用 {imp}.{name} 无法解析——"
                f"{imp!r} 不是本文件的 import")
        decls = fn_decls if ns == "fn" else ty_decls
        if name not in decls.get(tgt, ()):
            raise SyntaxError(
                f"{label}: 限定引用 {imp}.{name} 无法解析——"
                f"{label_of.get(tgt, imp)} 里没有声明 {name!r}")
        pubs = pub_fn if ns == "fn" else pub_ty
        if name not in pubs.get(tgt, ()):
            raise SyntaxError(
                f"{label}: 限定引用 {imp}.{name} —— {name!r} 在 "
                f"{label_of.get(tgt, imp)} 里不是 pub（非 pub 声明跨模块不可见）")
        return _final(tgt, name)

    def _resolve_bare(name, ap, label, ns):
        """未限定引用：本文件 > 唯一外部声明 > 歧义报错。"""
        decls = fn_decls if ns == "fn" else ty_decls
        if name in decls.get(ap, ()):
            return _final(ap, name)
        owners = (fn_owners if ns == "fn" else ty_owners).get(name, [])
        if not owners:
            return name                 # 内建 / 未定义：交给 Lower 报错
        if len(owners) == 1:
            return _final(owners[0], name)
        where = "、".join(sorted(label_of.get(o, "?") for o in owners))
        raise SyntaxError(
            f"{label}: 名字 {name!r} 在多个模块里都有（{where}）——"
            f"请用 lib.{name} 限定调用（per-module mangling 只在冲突时生效）")

    def _ty(t, ap, label):
        if not isinstance(t, tuple) or not t:
            return t
        k = t[0]
        if k == "named" and len(t) > 1 and isinstance(t[1], str):
            n = t[1]
            if n in _LINK_BUILTIN_TY:
                return t
            if QSEP in n:
                return ("named", _resolve(n, ap, label, "ty"))
            return ("named", _resolve_bare(n, ap, label, "ty"))
        if k in ("vec", "slice", "chan", "rc"):
            return (k, _ty(t[1], ap, label))
        if k == "map":
            return (k, _ty(t[1], ap, label), _ty(t[2], ap, label))
        if k == "array":
            return (k, t[1], _ty(t[2], ap, label))
        return t

    def _nm(n, ap, label, ns):
        if QSEP in n:
            return _resolve(n, ap, label, ns)
        return _resolve_bare(n, ap, label, ns)

    def rn(node, ap, label, shadow):
        """重写一棵 AST：声明名 / 类型位 / 引用位 / 限定引用。"""
        if isinstance(node, tuple):
            if not node:
                return node
            k = node[0]
            if k == "name" and len(node) > 1 and isinstance(node[1], str):
                n = node[1]
                return node if n in shadow else ("name", _nm(n, ap, label, "fn"))
            if k == "named":
                return _ty(node, ap, label)
            if k == "call" and len(node) > 1 and isinstance(node[1], list) \
                    and node[1]:
                path = node[1]
                if len(path) == 1:
                    path = [_nm(path[0], ap, label, "fn")]
                return ("call", path, rn(node[2], ap, label, shadow))
            if k in ("gcall", "gcall_infer") and len(node) > 1 \
                    and isinstance(node[1], str):
                head = [_nm(node[1], ap, label, "fn")]
                rest = [rn(x, ap, label, shadow) for x in node[2:]]
                return tuple([k] + head + rest)
            if k in ("enumlit", "enumlit_pos", "structlit") and len(node) > 1 \
                    and isinstance(node[1], list) and node[1]:
                path = [_nm(node[1][0], ap, label, "ty")] + list(node[1][1:])
                return tuple([k, path] + [rn(x, ap, label, shadow)
                                          for x in node[2:]])
            if k == "pat" and len(node) > 2 and isinstance(node[1], list) \
                    and node[1]:
                path = [_nm(node[1][0], ap, label, "ty")] + list(node[1][1:])
                binds = node[2]
                body_shadow = shadow | {b for b in (binds or []) if b}
                return ("pat", path, binds)
            if k == "path" and len(node) > 1 and isinstance(node[1], list) \
                    and node[1]:
                segs = node[1]
                if QSEP in segs[0]:
                    segs = [_nm(segs[0], ap, label, "ty")] + list(segs[1:])
                elif segs[0] in ty_decls.get(ap, ()):
                    segs = [_final(ap, segs[0])] + list(segs[1:])
                return ("path", segs)
            if k == "let" and len(node) > 2 and isinstance(node[2], str):
                # 先走右值，再把名字算进遮蔽（`let x = x` 的右边是外层 x）
                out = [node[0], node[1], node[2]] + [rn(x, ap, label, shadow)
                                                     for x in node[3:]]
                shadow.add(node[2])
                return tuple(out)
            if k in ("for", "parfor", "foreach") and len(node) > 1 \
                    and isinstance(node[1], str):
                out = [node[0], node[1]] + [rn(x, ap, label, shadow)
                                            for x in node[2:]]
                shadow.add(node[1])
                return tuple(out)
            return tuple(rn(x, ap, label, shadow) for x in node)
        if isinstance(node, list):
            return [rn(x, ap, label, shadow) for x in node]
        if isinstance(node, dict):
            return {kk: rn(v, ap, label, shadow) for kk, v in node.items()}
        return node

    out_files = []
    for label, ap, res, pex in files:
        mod, imports, fns, tests, structs, enums, decl_order = res[:7]
        tmap = {t: n for t, n in ren[ap].items() if t in ty_decls[ap]}

        def _mangle_method(nm):
            for t, n in tmap.items():
                if nm.startswith(t + "__"):
                    return n + nm[len(t):]
            return ren[ap].get(nm, nm)

        new_fns = []
        for f in fns:
            f = dict(f)
            f["name"] = _mangle_method(f["name"])
            if f.get("self_type") in tmap:
                f["self_type"] = tmap[f["self_type"]]
            f["params"] = [(pn, _ty(pt, ap, label)) for pn, pt in f["params"]]
            f["ret"] = _ty(f["ret"], ap, label)
            body = f.get("body")
            if body is not None:
                shadow = {pn for pn, _pt in f["params"]}
                f["body"] = rn(body, ap, label, shadow)
            new_fns.append(f)

        new_tests = []
        for t in tests:
            t = dict(t)
            t["body"] = rn(t["body"], ap, label, set())
            new_tests.append(t)

        new_structs = {}
        for k, fields in structs.items():
            nk = tmap.get(k, k)
            new_structs[nk] = [(fn_, _ty(ft, ap, label)) for fn_, ft in fields]
        new_enums = {}
        for k, variants in enums.items():
            nk = tmap.get(k, k)
            new_enums[nk] = [(vn, [(fn_, _ty(ft, ap, label)) for fn_, ft in vfs])
                             for vn, vfs in variants]
        new_order = []
        for kind, n in decl_order:
            new_order.append((kind, tmap.get(n, n)))

        out_files.append((label, ap,
                          (mod, imports, new_fns, new_tests, new_structs,
                           new_enums, new_order),
                          pex))
    return out_files, ren


def load_program(src_path, cfg=None):
    """带 import 的程序加载（v1.17：支持 [src] 三类资源布局）。

    - 库（lib）：`[src].lib`（默认 src/lib）下**按名称建文件夹**，
      `import ws.core` 解析为 src/lib/ws/core.qma——目录即清单，
      扫描后按前缀引用，不需要逐库声明（import 什么解析什么，惰性）。
    - 引用（ref）：`[src].ref` 下放置跨项目引用说明/锚点（qpm install
      的 .qpm/deps 优先于它）。
    - 资源（asset）：`[src].asset`（默认 src/asset）为 read_asset()
      的运行期基准路径（编译期嵌入）。

    - 合并范围：顶层 fn / struct / enum / test。const 在各文件解析期内联，
      天然可用，无需导出；module 声明只作文档。
    - 查找顺序：主文件目录 -> 仓库根 std/ -> [src].lib 库扫描 ->
      [src].ref 引用 -> .qpm/deps（qpm 依赖）。
    - 名字冲突（fn/struct/enum 与主文件或导入彼此重名）报错；
      被导入文件定义 main 报错（入口只在主文件）；
      循环 import 报错；找不到模块报错并列出全部查找路径。
      后端零改动：合并后的 AST 按单文件流程照常编译。
    """
    src_dir = os.path.dirname(os.path.abspath(src_path))
    seen, order, stack = {}, [], []
    order_labels = []          # 与 order 平行：每个被导入文件的 basename（报错用）
    order_aps = []             # 与 order 平行：绝对路径（defs_of/限定引用校验键）
    imp_of = {}                # (文件 ap, import 串) -> 目标文件 ap（限定引用校验）

    def parse_file(path, consts=None, generic_fns=None, ifaces=None,
                   lenient=False):
        text = read_source(path)
        p = Parser(tokenize(text), consts=consts,
                   generic_fns=generic_fns, ifaces=ifaces,
                   lenient_iface=lenient, src=text)
        res = p.parse_program()
        # 本文件新定义的泛型模板（种子里的不算）：pub 标记随 fdef["pub"]
        seed = set(generic_fns or {})
        gens = {k: bool(p.generic_fns[k].get("pub"))
                for k in p.generic_fns if k not in seed}
        return res, p.pub_types, gens, p.qrefs, (p.mod_version, p.import_reqs)

    main_dir = os.path.dirname(os.path.abspath(src_path))
    src_cfg = (cfg or {}).get("src", {}) if isinstance(cfg, dict) else {}
    lib_dir = os.path.normpath(os.path.join(
        main_dir, src_cfg.get("lib", "src/lib")))
    ref_dir = os.path.normpath(os.path.join(
        main_dir, src_cfg.get("ref", "src/ref")))

    def resolve_or_raise(imp, from_path):
        cands = _import_candidates(imp, os.path.dirname(os.path.abspath(from_path)))
        # [src].lib 库扫描：import ws.core -> lib/ws/core.qma（目录即库，
        # 按前缀引用）；单文件库 lib/ws.qma 同样支持
        parts = imp.split(".")
        rel = os.sep.join(parts) + SRC_EXT
        cands.append(os.path.join(lib_dir, rel))
        if len(parts) > 1:
            cands.append(os.path.join(lib_dir, os.sep.join(parts[:-1]),
                                      parts[-1] + SRC_EXT))
        cands.append(os.path.join(ref_dir, rel))
        # qpm 依赖目录始终按**主文件**的 .qpm/deps 解析（依赖包内部的
        # 递归 import 也要能在主项目的依赖集合里找到彼此）
        cands += _qpm_candidates(imp, main_dir)
        for cand in cands:
            if os.path.isfile(cand):
                return cand
        raise SyntaxError(f"{from_path}: import {imp!r} 找不到模块"
                          f"（查找：{'；'.join(cands)}）")

    def load(path, chain):
        ap = os.path.normpath(os.path.abspath(path))
        if ap in seen:
            return
        if ap in stack:
            raise SyntaxError(f"import 循环："
                              f"{' -> '.join(chain + [os.path.basename(path)])}")
        stack.append(ap)
        # 第一遍只用来发现 import 链与收集 const/泛型/接口种子：
        # 接口可能来自尚未扫到的模块，这一遍放宽（v1.81）
        res, pub_types, gens, qrefs, _mv = parse_file(ap, lenient=True)
        stack.pop()
        meta[ap] = {"version": _mv[0], "reqs": _mv[1]}
        seen[ap] = (res, pub_types, gens, qrefs)
        order.append(res)
        order_labels.append(os.path.basename(path))
        order_aps.append(ap)
        for imp in res[1]:
            cand = resolve_or_raise(imp, path)
            imp_of[(ap, imp)] = os.path.normpath(os.path.abspath(cand))
            load(cand, chain + [os.path.basename(path)])

    main_res, main_pub_types, main_gens, main_qrefs, _mm = parse_file(
        src_path, lenient=True)
    main_label = os.path.basename(src_path)
    main_ap = os.path.normpath(os.path.abspath(src_path))
    meta = {main_ap: {"version": _mm[0], "reqs": _mm[1]}}
    for imp in main_res[1]:
        cand = resolve_or_raise(imp, src_path)
        imp_of[(main_ap, imp)] = os.path.normpath(os.path.abspath(cand))
        load(cand, [os.path.basename(src_path)])

    # 两遍解析（const 跨 import 可见）：第一遍已把各文件解析过、const 都已
    # 登记；这里收集全部顶层 const 成全集（同名不同值报错），再带全集把
    # 主文件与全部被导入模块重新解析一遍。没有这一步，std 库里定义的
    # 槽位布局常量（如 std/net/core.qma 的 SLOT_*）对使用方不可见——
    # 解析期内联发生在各自文件，而 import 是扁平合并、解析顺序不保证。
    def _consts_of(path):
        p = Parser(tokenize(read_source(path)), lenient_iface=True)
        p.parse_program()
        # 宽松占位（`impl T : X` 里出现过、但本文件没声明的 X）**不进种子**：
        # 它只是"扫描顺序"的产物，不是声明。放进种子会让"根本没声明"的
        # 接口在第二遍被当成合法种子静默放行（v1.88）。
        real_if = {k: v for k, v in p.interfaces.items()
                   if k not in p.iface_provisional}
        return p.consts, p.generic_fns, real_if, set(p.iface_provisional)

    acc = {}
    acc_gf = {}
    acc_if = {}
    prov_seen = False
    for path in [src_path] + list(seen.keys()):
        cs, gf, ifs, prov = _consts_of(path)
        prov_seen = prov_seen or bool(prov)
        for k, v in cs.items():
            if k in acc and acc[k] != v:
                raise SyntaxError(
                    f"const 冲突：{k!r} 在多个模块中取值不同")
            acc[k] = v
        for k, v in gf.items():
            if k in acc_gf and acc_gf[k] != v:
                raise SyntaxError(
                    f"泛型函数冲突：{k!r} 在多个模块中定义不同")
            acc_gf[k] = v
        for k, v in ifs.items():
            # 跨文件接口（v1.81）：同名接口必须在所有模块里签名一致。
            # 占位已被 _consts_of 滤掉，所以这里出现的都是**真声明**：
            # 签名不同即冲突，签名相同即幂等（v1.88）。
            if k in acc_if and acc_if[k] != v:
                raise SyntaxError(
                    f"接口冲突：{k!r} 在多个模块中声明不一致"
                    f"（跨文件接口必须同名同签名）")
            acc_if[k] = v
    # prov_seen：有文件在 impl 里引用了"本文件没声明"的接口。这类程序
    # 必须走第二遍严格校验（否则宽松期的占位会让它静默通过）——v1.88。
    if acc or acc_gf or acc_if or prov_seen:
        seen2, order2, pex2, labels2, aps2 = {}, [], [], [], []

        def reload(path):
            ap = os.path.normpath(os.path.abspath(path))
            if ap in seen2:
                return
            res, pub_types, gens, qrefs, _mv = parse_file(
                ap, consts=acc, generic_fns=acc_gf, ifaces=acc_if)
            meta[ap] = {"version": _mv[0], "reqs": _mv[1]}
            seen2[ap] = res
            order2.append(res)
            pex2.append((pub_types, gens, qrefs))
            labels2.append(os.path.basename(path))
            aps2.append(ap)
            for imp in res[1]:
                cand = resolve_or_raise(imp, path)
                imp_of[(ap, imp)] = os.path.normpath(os.path.abspath(cand))
                reload(resolve_or_raise(imp, path))

        main_res, main_pub_types, main_gens, main_qrefs, _mm = parse_file(
            src_path, consts=acc, generic_fns=acc_gf, ifaces=acc_if)
        meta[main_ap] = {"version": _mm[0], "reqs": _mm[1]}
        for imp in main_res[1]:
            cand = resolve_or_raise(imp, src_path)
            imp_of[(main_ap, imp)] = os.path.normpath(os.path.abspath(cand))
            reload(resolve_or_raise(imp, src_path))
        seen, order = seen2, order2
        pex_list = pex2
        labels = labels2
        aps = aps2
        main_pex = (main_pub_types, main_gens, main_qrefs)
    else:
        pex_list = [seen[ap][1:] for ap in seen]
        labels = order_labels
        aps = order_aps
        main_pex = (main_pub_types, main_gens, main_qrefs)

    # ---- pub 可见性检查（v1.43）----
    # 规则：文件 X 引用了名字 r，且 r 定义在另一文件 Y（X 自己没定义），
    # 而 Y 里 r 不是 pub -> 编译期报错。单文件程序只有一个"文件"，
    # 永远不触发（全部既有测试零影响）。
    # 引用口径（与 global_dce 的 walk 同款 + 类型位置）：
    #   ("call", path, ...) 取 path[-1]；("gcall", name, ...) 取 name；
    #   ("name", x) 叶子；("enumlit"/"structlit"/"pat", [头, ...], ...) 取头段；
    #   ("named", T) 类型引用（内建标量除外——出现在签名/字段/let 标注/
    #   vec/map/chan 元素等一切类型位）。
    # 遮蔽豁免：let/参数/循环变量/match 绑定过的名字跳过——局部绑定遮蔽
    # 顶层名，跨模块同名非 pub 声明在这些位置本来就不可见，避免变量误报。
    BUILTIN_TY = {"int", "i64", "i32", "i16", "i8", "u64", "u32", "u16", "u8",
                  "bool", "str", "void", "byte", "float", "f64", "f32",
                  "__self__"}

    def _collect(e, refs, bound):
        if isinstance(e, tuple):
            k = e[0] if e else None
            if k == "call" and isinstance(e[1], list) and e[1]:
                refs.add(e[1][-1])
            elif k == "gcall" and isinstance(e[1], str):
                refs.add(e[1])
            elif k == "name" and isinstance(e[1], str):
                refs.add(e[1])
            elif k in ("enumlit", "structlit", "pat") and \
                    isinstance(e[1], list) and e[1]:
                refs.add(e[1][0])
            elif k == "named" and isinstance(e[1], str) and e[1] not in BUILTIN_TY:
                refs.add(e[1])
            elif k == "let" and len(e) > 2 and isinstance(e[2], str):
                bound.add(e[2])
            elif k in ("for", "parfor", "foreach") and len(e) > 1 \
                    and isinstance(e[1], str):
                bound.add(e[1])
            for x in e:
                _collect(x, refs, bound)
        elif isinstance(e, list):
            for x in e:
                _collect(x, refs, bound)
        elif isinstance(e, dict):
            for x in e.values():
                _collect(x, refs, bound)

    files = [(main_label, main_ap, main_res, main_pex)] + [
        (label, ap, res, pex)
        for label, (ap, (res, pex)) in zip(order_labels, zip(aps, zip(order, pex_list)))]

    # ---- 模块版本检查（v1.99）----
    # `module util "1.2.3"` 声明；`import util ">=1.2"` 要求。只挡"明显不兼容"
    # 的导入（同 major 且 >= 要求），不做 semver 求解——依赖解析是 qpm 的活。
    for (_ap, _imp), _tgt in imp_of.items():
        _req = meta.get(_ap, {}).get("reqs", {}).get(_imp)
        if _req is None:
            continue
        _ver = meta.get(_tgt, {}).get("version")
        _req_s = ".".join(str(x) for x in _req)
        _who = os.path.basename(_ap)
        _what = os.path.basename(_tgt)
        if _ver is None:
            raise SyntaxError(
                f"{_who}: import {_imp} 要求版本 >= {_req_s}，但 {_what} "
                f"没有声明版本——请在它开头写 module <名字> \"x.y.z\"")
        if _ver[0] != _req[0] or _ver < _req:
            raise SyntaxError(
                f"{_who}: import {_imp} 要求版本 >= {_req_s}（同 major "
                f"{_req[0]}），实际是 {'.'.join(str(x) for x in _ver)}"
                f"（{_what}）——版本不兼容")

    # ---- 跨模块链接（v1.99）：per-module mangling + 限定引用解析 ----
    # 没有跨模块同名、也没有限定引用时，这一步是恒等变换（既有程序零影响）。
    files, link_ren = link_modules(files, imp_of, main_ap, acc_if)
    main_res = files[0][2]
    order = [f[2] for f in files[1:]]
    for _ap, _m in link_ren.items():
        for _old, _new in _m.items():
            if _old in acc_gf:          # 泛型模板跟着改名（展开时按名查表）
                acc_gf[_new] = acc_gf.pop(_old)

    defs_of = {}
    for _label, ap, res, (pub_types, gens, _qr) in files:
        fdefs = {f["name"]: bool(f.get("pub")) for f in res[2]}
        for k in res[4]:
            fdefs[k] = k in pub_types        # struct/enum/interface
        for k in res[5]:
            # v1.44 修复：enum 也要进定义表——v1.43 漏收，枚举的跨模块
            # pub 检查被静默跳过（r not in defs_of 直接 continue）
            fdefs[k] = k in pub_types
        fdefs.update(gens)
        for name, is_pub in fdefs.items():
            # fn/struct/enum 重名已由上面的合并冲突检查报错；这里 setdefault
            # 只兜 interface/泛型这类没有专属冲突检查的条目
            defs_of.setdefault(name, (ap, is_pub))
    for label, ap, res, (_pt, _gn, qrefs) in files:
        # 限定引用的指向 / pub 校验已在 link_modules 里按**节点**做完
        # （v1.99：同一个文件里 `f()` 与 `lib.f()` 必须是两个不同符号，
        #  v1.44 的"集合式"校验无法区分，故整体挪到链接期）。
        refs, bound = set(), set()
        for f in res[2]:
            for pn, _pt in f["params"]:
                bound.add(pn)
            _collect(f["body"], refs, bound)
        for t in res[3]:
            _collect(t["body"], refs, bound)
        for fields in res[4].values():
            for _fn, ft in fields:
                _collect(ft, refs, bound)
        for variants in res[5].values():
            for _vn, vfs in variants:
                for _fn, ft in vfs:
                    _collect(ft, refs, bound)
        viols = []
        for r in refs:
            if r in bound or r not in defs_of:
                continue
            dap, is_pub = defs_of[r]
            if dap != ap and not is_pub:
                viols.append(f"{r!r} <- {os.path.basename(dap)}")
        if viols:
            raise SyntaxError(
                f"{label}: 引用了非 pub 声明（{len(viols)} 处）："
                + "、".join(sorted(viols))
                + "。请在对方声明前加 pub 导出，或改在本模块内使用")

    mod, imports, fns, tests, structs, enums, decl_order = main_res
    fn_names = {f["name"] for f in fns}
    for res in order:
        imp_path = f"(imported)"
        for f in res[2]:
            if f["name"] == "main":
                raise SyntaxError("被导入的模块不能定义 main()（入口只在主文件）")
            if f["name"] in fn_names:
                raise SyntaxError(f"import 冲突：函数 {f['name']!r} 重名")
            fn_names.add(f["name"])
        fns = fns + res[2]
        for k in res[4]:
            if k == "closure":
                # 闭包布局（v1.95）是内建类型：每个文件的 Parser 都自带一份
                # 同构登记，跨文件合并时不算重名（与接口种子的处理同理）。
                structs.setdefault(k, res[4][k])
                continue
            if k in structs:
                if k in acc_if:
                    # 跨文件接口（v1.81）：两边 structs 里都有它——声明方是真身，
                    # 引用方只是种子带来的 {data,vt} 布局，同名不算冲突。
                    continue
                raise SyntaxError(f"import 冲突：struct {k!r} 重名")
        structs.update(res[4])
        for k in res[5]:
            if k in enums:
                raise SyntaxError(f"import 冲突：enum {k!r} 重名")
        enums.update(res[5])
        have = set(decl_order)
        decl_order = decl_order + [d for d in res[6] if d not in have]
        tests = tests + res[3]

    # 用户泛型单态化（v1.11）：gcall 全部降为普通 call，模板换成实例。
    # 必须在合并完成后做——调用点可能跨文件（std 库的泛型）。
    if acc_gf:
        fns = expand_generics(fns, acc_gf, structs, enums)
    return mod, imports, fns, tests, structs, enums, decl_order


def resolve_option_patterns(arms, scrut_ename):
    """把 `Option.Some/None` / `Result.Ok/Err` 模式路径首段改写为求值式真实合成枚举名
    __opt_* / __res_*（受控单态化）。
    仅当求值式确为对应合成枚举时改写（用户手写 Result 等原样返回）；其余原样返回。"""
    if not scrut_ename:
        return arms
    if str(scrut_ename).startswith("__opt_"):
        head = "Option"
    elif str(scrut_ename).startswith("__res_"):
        head = "Result"
    else:
        return arms
    out = []
    for pat, body in arms:
        if pat and pat[0] == "pat" and pat[1] and pat[1][0] == head:
            out.append((("pat", [scrut_ename] + list(pat[1][1:]), pat[2]), body))
        else:
            out.append((pat, body))
    return out


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

def global_dce(fns_ast, keep=None):
    """全局死代码消除（v1.17d）：从 main 的调用图可达性分析，删除不可达
    的用户函数——import 大库只链接用到的（库生态"不拉进无用代码"的核心）。

    保守规则（宁可少删，不可错删）：
    - 根 = main（测试模式下 with_test_runner 已把测试合成进 main，
      所以测试模式自动保留被测函数；普通构建自动剔除 test 块——
      发布二进制不带测试代码，这是 DCE 的副产品而非缺陷）；
    - 引用收集：("call", [path...], args) 取 path[-1]（lower_call 同款
      解析）；("gcall", name, ...) 取 name；("name", x) 叶子也记——
      函数值/回调经裸名传递（net.serve 的 cbconn 等），局部变量与
      函数重名时会多保留（保守方向正确）；
    - ("method", obj, m, args)：静态不知 obj 类型——出现方法名 m 就
      保留全部以 "__m" 结尾的 fn（impl Type : Interface 落成的
      Type__method 命名约定）；
    - 不动点迭代（递归可达）。
    - QLM_NO_DCE=1 环境变量关闭（诊断用）。
    运行库（__ 前缀内建）不在 fns_ast 里，天然不受影响。"""
    import os as _os
    import sys as _sys
    if _os.environ.get("QLM_NO_DCE"):
        return fns_ast
    # @extern 前置检查：语言级错误与可达性无关——声明了自研后端无法
    # 兑现的链接语义就必须报错，哪怕这个 fn 随后会被 DCE 删除
    # （否则"不可达 extern"静默编译通过，违反 fail-fast 契约）
    for f in fns_ast:
        if f.get("extern"):
            raise SyntaxError(
                f'函数 {f["name"]} 声明为 @extern("C")：自研后端不支持'
                f'外部符号链接（原型无函数体无法发射）。'
                f'请在 C 后端使用，或删除 @extern 改为本体实现')
    by_name = {}
    for f in fns_ast:
        by_name[f["name"]] = f
    if "main" not in by_name:
        return fns_ast                     # 无 main（病态）：全保留

    def walk(e, refs, methods):
        if isinstance(e, tuple):
            if e and e[0] == "call" and isinstance(e[1], list) and e[1]:
                refs.add(e[1][-1])
            elif e and e[0] == "gcall" and isinstance(e[1], str):
                refs.add(e[1])
            elif e and e[0] == "method" and len(e) > 2 and isinstance(e[2], str):
                methods.add(e[2])
            elif e and e[0] == "name" and isinstance(e[1], str):
                refs.add(e[1])
            for x in e:
                walk(x, refs, methods)
        elif isinstance(e, list):
            for x in e:
                walk(x, refs, methods)
        elif isinstance(e, dict):
            # v2.91：`("structlit", path, {字段: 表达式})` 的第三个元素是 **dict**，
            # 而这里以前只认 tuple/list —— 结构体字面量里的引用**整片漏扫**。
            # 后果不是"多删一个函数"，而是把回调函数当死代码删掉：实测
            #   `let s = S { cb: hello }`  ->  DCE 删 hello  ->  C 里 `hello` 未定义。
            # 自研后端同样吃这份 DCE，只是它的报错更早（"未定义变量 handler"）。
            for x in e.values():
                walk(x, refs, methods)

    # impl 家族：接口装箱的 vtable 覆盖同 (iface, type) 的**全部**方法
    # 槽——任一成员可达则全族保留，否则 build_iface_meta 的
    # table[m] KeyError（v1.17d 首版踩坑：只调用接口的一个方法，
    # 其余方法被 DCE，vtable 建不出来）
    family = {}
    for f in fns_ast:
        ii = f.get("impl_iface")
        if ii:
            family.setdefault((ii, f.get("self_type")), []).append(f["name"])

    reach = {"main"}
    if keep:
        # v1.93：隐式调用的函数（析构）当额外根——AST 里没有 call 节点，
        # 只从 main 走调用图找不到它，会被当死代码删掉。
        reach |= set(keep)
    seen = set()
    methods = set()
    while True:
        before = len(reach)
        for name in list(reach):
            if name in seen or name not in by_name:
                continue
            seen.add(name)
            refs, ms = set(), set()
            walk(by_name[name]["body"], refs, ms)
            methods |= ms
            for r in refs:
                if r in by_name:
                    reach.add(r)
            fobj = by_name[name]
            if fobj.get("impl_iface"):
                for sib in family.get((fobj["impl_iface"], fobj.get("self_type")), []):
                    reach.add(sib)
        for m in methods:
            suf = "__" + m
            for f in fns_ast:
                if f["name"].endswith(suf):
                    reach.add(f["name"])
        if len(reach) == before:
            break
    kept = [f for f in fns_ast if f["name"] in reach]
    dropped = len(fns_ast) - len(kept)
    if dropped and _os.environ.get("QLM_DCE_VERBOSE"):
        print(f"[dce] dropped {dropped} unreachable fns "
              f"({len(fns_ast)} -> {len(kept)})", file=_sys.stderr)
    return kept


BUILTIN_RETS = {"print": "void", "cores": "int", "assert": "void",
                "join": "int64_t", "len": "int64_t",
                "to_float": "double", "to_f32": "float", "to_int": "int64_t"}

CTYPE = {
    "int": "int64_t", "i64": "int64_t", "i32": "int32_t", "u64": "uint64_t",
    "float": "double", "f64": "double", "f32": "float",
    "bool": "bool", "str": "const char *", "void": "void",
    "net.Conn": "QlmConn *", "[]byte": "QlmBuf", "net.Action": "int",
}


def type_str(t):
    return t[1] if t[0] == "named" else ("QlmBuf" if t[1] == ("named", "byte") else "void *")


# 切片 `[]T` = {ptr, len} 两字（与自研后端 QuIR 字宽一致）
SLICE_WORDS = 2
# 切片/数组元素只接受标量：一律按 8 字节字存放
SCALAR_ELEMS = ("int", "i64", "i32", "u64", "u32", "i16", "u16", "i8", "u8",
                "bool", "str", "byte")


def slice_elem_tag(t):
    """切片元素类型元组 -> 环境类型串标签；越界元素报错"""
    if t[0] != "named" or t[1] not in SCALAR_ELEMS:
        raise SyntaxError("切片元素暂只支持标量类型（int/bool/str）")
    return t[1]


def is_slice_env(t):
    """环境类型串是否是切片（`slice:<elem>`）"""
    return isinstance(t, str) and t.startswith("slice:")


def slice_env_elem(t):
    """`slice:<elem>` -> 元素标签"""
    return t[6:] if is_slice_env(t) else None


# ---- map[K]V（v0.10）：开放寻址哈希表 ----
# 键：int/bool/str 标量（v0.10）；值：标量 + 具名 struct/enum（v1.41 值扩容，
# 多字值按 agg 布局占 N 槽，槽宽由后端查符号表）。复合容器（vec/map/chan）作值
# 仍不做——句柄语义要配 mapinner 标签链，留作后续。
MAP_KV_SCALARS = ("int", "bool", "str")


def map_kv_tag(t, which, line=None):
    """map 的键/值类型标签：键只允许标量；值 v1.41 起还允许具名聚合
    （返回类型名，标量与聚合由消费方查符号表区分）。越界明确报错。"""
    loc = f"line {line}: " if line is not None else ""
    if t is None or t[0] != "named" or t[1] == "byte":
        got = t[1] if (t and t[0] == "named") else repr(t)
        raise SyntaxError(
            f"{loc}map 的{which}只支持 int/bool/str 标量"
            + ("或具名 struct/enum" if which == "值类型" else "")
            + f"，得到 {got!r}")
    if t[1] in MAP_KV_SCALARS or which == "值类型":
        return t[1]          # 标量原样；值侧具名聚合放行（v1.41）
    got = t[1]
    raise SyntaxError(f"{loc}map 的{which}只支持 int/bool/str 标量，得到 {got!r}")


def map_lit_cap(e):
    """map[K]V.new(cap) 实参是整数字面量 -> 返回值（供 2 的幂校验），否则 None"""
    return e[1] if (isinstance(e, tuple) and e[0] == "num") else None


def map_env_tag(kt, vt):
    """map 在作用域里的类型标记：`map:<键标签>:<值标签>`"""
    return f"map:{kt}:{vt}"


def map_env_of_type(t):
    """类型元组 ("map", k, v) -> 环境标记；不是 map 返回 None"""
    if t and t[0] == "map":
        return map_env_tag(map_kv_tag(t[1], "键类型"), map_kv_tag(t[2], "值类型"))
    return None


def is_map_env(t):
    """环境类型串是否是 map（`map:<k>:<v>`）"""
    return isinstance(t, str) and t.startswith("map:")


VEC_SCALARS = ("int", "i64", "i32", "i16", "i8", "u64", "u32", "u16", "u8",
               "bool", "str")


def vec_elem_tag(t, line=None):
    """vec 元素类型标签：标量原样返回，具名聚合返回 ('agg', Name)，
    嵌套 vec 返回 ('vecinner', 内层标签)（v1.12：句柄 1 字标量语义），
    map 返回 ('mapinner', 键标签, 值标签)（v1.37：句柄 1 字标量语义）。
    只在解析期做语法级校验；是不是真的 struct/enum 由后端查符号表。"""
    if t[0] == "named" and t[1] in VEC_SCALARS:
        return t[1]
    if t[0] == "named":
        return ("agg", t[1])
    if t[0] == "vec":
        # vec[vec[T]]：元素 = 内层 vec 的句柄（1 字，标量拷贝语义）。
        # 内层标签供 get 取回时重新 mark（row.push 才认类型）。
        return ("vecinner", vec_elem_tag(t[1]))
    if t[0] == "map":
        # vec[map[K]V]（v1.37）：元素 = map 句柄（1 字，与 vecinner 同构）。
        # K/V 标签供 get 取回时重新 mark 成 map（m.set/m.get 才认类型）。
        # map 句柄不持有元素所有权——vec 清空/扩容不释放 map 本身。
        return ("mapinner", _map_kv_label(t[1]), _map_kv_label(t[2]))
    raise SyntaxError(f"vec 元素类型只支持标量、具名类型、嵌套 vec 与 map，得到 {t!r}")


def _map_kv_label(t):
    """map K/V 类型 -> 短标签（int/str/bool；vec_elem_tag 的 mapinner 用）"""
    return t[1] if (isinstance(t, tuple) and t[0] == "named") else "int"


def _vec_tag_str(t):
    """vec 元素标签串：标量原样，聚合 -> "agg:Name"，嵌套 -> "vecinner:..."，
    map -> "mapinner:K:V"（env 里用字符串传）"""
    tag = vec_elem_tag(t)
    if isinstance(tag, str):
        return tag
    if tag[0] == "mapinner":
        return "mapinner:" + tag[1] + ":" + tag[2]
    return ":".join(map(str, tag))


def _vec_ewords(cg, t):
    """vec 元素占几个 8 字节槽（决定分配大小与拷贝宽度）。
    标量 1；struct = 字段数（字段各占 1 槽，嵌套聚合按 C 结构体布局也会是 1 槽指针式占位，
    这条限制在 SPEC 里写明）；enum = 1 + 最大变体载荷数；嵌套 vec = 1（句柄）。"""
    tag = vec_elem_tag(t)
    if isinstance(tag, str):
        return 1
    if tag[0] in ("vecinner", "mapinner"):
        return 1          # 句柄 1 字（v1.37：map 同 vecinner）
    name = tag[1]
    if name in cg.structs:
        return max(1, len(cg.structs[name]))
    if name in cg.enums:
        variants = cg.enums[name] or []
        return 1 + max([len(fs) for _v, fs in variants] or [0])
    raise SyntaxError(f"vec 元素类型 {name} 未声明（需要先声明 struct/enum）")


def is_vec_env(t):
    """环境类型串是否是 vec（`vec:<elem>`）"""
    return isinstance(t, str) and t.startswith("vec:")


def vec_env_elem(t):
    return t[4:] if is_vec_env(t) else None


def map_env_parts(t):
    """`map:<k>:<v>` -> (键标签, 值标签)；不是 map 返回 None"""
    if not is_map_env(t):
        return None
    _, k, v = t.split(":", 2)
    return k, v


def slice_access(elem):
    """切片元素访问三元组：(ptr 字段名, C 元素指针类型, 读出的 C 类型)。
    `[]byte` 走 QlmBuf（字节寻址，网络运行时 ABI）；其余按 8 字节字寻址。"""
    if elem == "byte":
        return "data", "char *", "int64_t"
    if elem == "str":
        return "ptr", "const char **", "const char *"
    return "ptr", "int64_t *", "int64_t"


def slice_cname(elem):
    """切片元素标签 -> C 结构体名"""
    return "QlmBuf" if elem == "byte" else "QlmSlice"


def slice_ptr_field(elem):
    return "data" if elem == "byte" else "ptr"


# 定长数组在作用域里的标记：`arr:<elem>:<n>`（elem = 元素类型名，n = 长度）
def arr_env(elem, n):
    return f"arr:{elem}:{n}"


def is_arr_env(t):
    return isinstance(t, str) and t.startswith("arr:")


def arr_env_parts(t):
    """`arr:<elem>:<n>` -> (elem, n)；不是数组返回 None"""
    if not is_arr_env(t):
        return None
    elem, _, n = t[4:].partition(":")
    return elem, int(n)


# C 侧类型串 -> 元素类型名（arraylit 这类只有 C 类型可参考的场合用）
C_TO_ELEM = {"int64_t": "int", "bool": "bool", "const char *": "str"}


# ---- 浮点（SPEC §2）：float == f64 双精度；f32 单精度。
# 环境类型串直接用 C 类型名：f64/float -> "double"，f32 -> "float"。
FLOAT_ENVS = ("double", "float")


def is_float_env(t):
    """环境类型串是否浮点"""
    return t in FLOAT_ENVS


def float_env_of(width):
    """"f32"/"f64" -> 环境类型串"""
    return "float" if width == "f32" else "double"


def float_width_of_env(t):
    """环境类型串 -> "f32"/"f64"""  
    return "f32" if t == "float" else "f64"


def unify_float(lt, rt):
    """浮点二元运算结果类型：任一 f64 则提升为 f64（与 C 提升规则一致）"""
    return "double" if "double" in (lt, rt) else "float"



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
        if t[0] == "map":
            return "int64_t"
        if t[0] == "slice":
            return "slice:" + slice_elem_tag(t[1])
        if t[0] == "vec":
            return "vec:" + map_kv_tag(t[1], "vec 元素类型")
        if t[0] == "array":
            if not (t[2][0] == "named" and t[2][1] in
                    ("int", "i64", "i32", "u64", "u32", "i16", "u16", "i8", "u8", "bool")):
                raise SyntaxError("定长数组暂只支持数值元素")
            return arr_env(t[2][1], t[1])
        if t[0] == "named" and t[1] in self.structs:
            return "struct:" + t[1]
        if t[0] == "named" and t[1] in self.enums:
            return "enum:" + t[1]
        if t[0] == "vec":
            return "vec:" + _vec_tag_str(t[1])
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
            if t[0] == "slice":
                return "slice:" + slice_elem_tag(t[1])
            if t[0] == "map":
                return map_env_of_type(t) or "int64_t"
            if t[0] == "vec":
                return "vec:" + _vec_tag_str(t[1])
            return "QlmBuf" if t[1] == ("named", "byte") else "void *"
        return BUILTIN_RETS.get(name, "void")

    def expr(self, e, env):
        """返回 C 侧类型字符串: int64_t / bool / const char * / QlmBuf / QlmConn * / int / void"""
        k = e[0]
        if k == "num":
            return "int64_t"
        if k == "fnum":
            return "float" if e[2] == "f32" else "double"
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
            if name == "slice_of" and name not in self.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("slice_of(x) 需要且只需要一个数组实参")
                at = self.expr(e[2][0], env)
                if not is_arr_env(at):
                    raise SyntaxError("slice_of() 目前只支持定长数组变量（零拷贝转换）")
                return "slice:" + arr_env_parts(at)[0]
            return self.fn_ret(name)
        if k == "spawn":
            return "int64_t"
        if k == "select":
            for arm in e[1]:
                if not (isinstance(arm, tuple) and arm[0] == "method"
                        and arm[2] == "recv" and not arm[3]):
                    raise SyntaxError("select 臂必须是 ch.recv() 形式")
            return "int64_t"
        if k == "chanopen":
            return "int64_t"
        if k == "mapnew":
            return map_env_of_type(e[1]) or "int64_t"
        if k == "arraylit":
            elem = None
            for el in e[1]:
                et = self.expr(el, env)
                if et in ("const char *", "void", "QlmBuf") or \
                        (isinstance(et, str) and (et.startswith("struct:") or
                                                  et.startswith("enum:") or
                                                  is_arr_env(et) or is_slice_env(et))):
                    raise SyntaxError("数组字面量暂只支持数值元素")
                if elem is None:
                    elem = C_TO_ELEM.get(et, "int")
            return arr_env(elem or "int", len(e[1]))
        if k == "vecnew":
            return "vec:" + map_kv_tag(e[1], "vec 元素类型")
        if k == "sliceof":
            ot = self.expr(e[1], env)
            if ot == "const char *":
                return "const char *"
            if is_arr_env(ot):
                return "slice:" + arr_env_parts(ot)[0]
            if is_slice_env(ot):
                return ot
            raise SyntaxError("子切片 a[lo..hi] 只支持 str、切片与定长数组")
        if k == "index":
            ot = self.expr(e[1], env)
            if is_arr_env(ot):
                return "int64_t"
            if is_slice_env(ot):
                return "const char *" if slice_env_elem(ot) == "str" else "int64_t"
            if ot == "const char *":
                return "int64_t"          # str[i] -> 该字节的无符号值
            raise SyntaxError("下标只能用于定长数组、切片或 str")
        if k == "method":
            obj_t = self.expr(e[1], env)
            m = e[2]
            if is_vec_env(obj_t):
                elem = vec_env_elem(obj_t)
                if m in ("get", "pop"):
                    if elem == "str":
                        return "const char *"
                    if elem.startswith("agg:"):
                        return "struct:" + elem[4:]
                    if elem.startswith("mapinner:"):
                        # vec[map]（v1.37）：取回的是 map 句柄，重挂 map 类型
                        # （否则 .set/.get 链式调用认不出来）
                        return "map:" + elem[len("mapinner:"):]
                    return "int64_t"
                if m == "len":
                    return "int64_t"
                return "int64_t"          # push/set/clear 视作语句，值不用
            mp = map_env_parts(obj_t) if isinstance(obj_t, str) else None
            if mp:
                kv, vv = mp
                if m == "get":
                    if vv == "str":
                        return "const char *"
                    if vv not in MAP_KV_SCALARS:
                        # 聚合值（v1.41）：与 struct/enum 变量同类型串
                        return ("struct:" if vv in self.structs else "enum:") + vv
                    return "int64_t"
                if m == "has":
                    return "bool"
                return "int64_t"
            if m in ("send", "recv"):
                return "int64_t"
            if m == "close":
                return "void"
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
            if is_float_env(lt) or is_float_env(rt):
                return unify_float(lt, rt)
            return "const char *" if "const char *" in (lt, rt) else "int64_t"
        if k == "unop":
            return "bool" if e[1] == "!" else self.expr(e[2], env)
        if k == "structlit":
            return "struct:" + ".".join(e[1])
        if k == "enumlit":
            return "enum:" + e[1][0]
        if k == "enumlit_pos":
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
            inner = self.expr(e[1], env)
            if isinstance(inner, str) and inner.startswith("enum:"):
                ename = inner[5:]
                variants = self.enums.get(ename, [])
                for vn, fields in variants:
                    if vn == "Ok" and fields:
                        return self._env_type(fields[0][1])
            return inner
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
/* ===== Quelmara runtime (core) ===== */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>

static int64_t qlm_cores(void) {
    long n = sysconf(_SC_NPROCESSORS_ONLN);
    return (int64_t)(n > 0 ? n : 1);
}

/* 字符串：轮转缓冲池（无 GC、无 malloc 热点） */
#define QLM_SBUF_N 64
#define QLM_SBUF_SZ 512
static char qlm_sbuf[QLM_SBUF_N][QLM_SBUF_SZ];
static int qlm_sbuf_i = 0;

static const char *qlm_i64_to_str(int64_t v) {
    char *b = qlm_sbuf[qlm_sbuf_i++ & (QLM_SBUF_N - 1)];
    snprintf(b, QLM_SBUF_SZ, "%lld", (long long)v);
    return b;
}
static const char *qlm_bool_to_str(bool v) { return v ? "true" : "false"; }

/* 浮点格式化：与自研后端 __f64_to_str 算法逐位一致（双链 diff 依赖）。
   nan/inf/-inf；0 -> "0"；[1e-6, 1e12) 定点 6 位小数去尾零；
   其余科学计数 d.dddddde±N（尾数 6 位小数去尾零）。
   四舍五入（half away from zero）；定点用 x*1e6+0.5 截断，与原生后端
   cvttsd2si 语义一致。 */
static const char *qlm_f64_to_str(double x) {
    char *b = qlm_sbuf[qlm_sbuf_i++ & (QLM_SBUF_N - 1)];
    if (x != x) { strcpy(b, "nan"); return b; }
    if (x > 1.7976931348623157e308) { strcpy(b, "inf"); return b; }
    if (x < -1.7976931348623157e308) { strcpy(b, "-inf"); return b; }
    if (x == 0.0) { strcpy(b, "0"); return b; }
    int neg = x < 0;
    if (neg) x = -x;
    char *p = b;
    if (neg) *p++ = '-';
    if (x >= 1e-6 && x < 1e12) {
        uint64_t u = (uint64_t)(x * 1e6 + 0.5);
        uint64_t ip = u / 1000000, fp = u % 1000000;
        p += sprintf(p, "%llu", (unsigned long long)ip);
        if (fp != 0) {
            char f[8]; sprintf(f, "%06llu", (unsigned long long)fp);
            char *e = f + 6; while (e > f && e[-1] == '0') e--;
            *p++ = '.'; memcpy(p, f, (size_t)(e - f)); p += e - f;
        }
        *p = 0;
    } else {
        int exp10 = 0;
        while (x >= 10.0) { x /= 10.0; exp10++; }
        while (x < 1.0) { x *= 10.0; exp10--; }
        uint64_t m = (uint64_t)(x * 1e6 + 0.5);
        if (m == 10000000ULL) { m = 1000000ULL; exp10++; }
        char mf[8]; sprintf(mf, "%07llu", (unsigned long long)m);
        *p++ = mf[0];
        char *e = mf + 7; while (e > mf + 1 && e[-1] == '0') e--;
        if (e > mf + 1) { *p++ = '.'; memcpy(p, mf + 1, (size_t)(e - (mf + 1))); p += e - (mf + 1); }
        *p++ = 'e'; *p++ = exp10 >= 0 ? '+' : '-';
        p += sprintf(p, "%llu", (unsigned long long)(exp10 >= 0 ? exp10 : -exp10));
        *p = 0;
    }
    return b;
}
static void qlm_print_f64(double v) { printf("%s\n", qlm_f64_to_str(v)); }
static const char *qlm_concat(const char *a, const char *b) {
    char *buf = qlm_sbuf[qlm_sbuf_i++ & (QLM_SBUF_N - 1)];
    snprintf(buf, QLM_SBUF_SZ, "%s%s", a ? a : "", b ? b : "");
    return buf;
}
static void qlm_print_str(const char *s) { printf("%s\n", s ? s : "(null)"); }
static void qlm_print_i64(int64_t v) { printf("%lld\n", (long long)v); }
static void qlm_print_bool(bool v) { printf("%s\n", v ? "true" : "false"); }
/* 字符串相等：内容比较（而非指针比较）——str 是一等类型 */
static bool qlm_str_eq(const char *a, const char *b) {
    if (a == b) return true;
    if (!a || !b) return false;
    return strcmp(a, b) == 0;
}
static void qlm_assert(bool cond, const char *msg) {
    if (!cond) {
        fprintf(stderr, "assert failed: %s\n", msg ? msg : "(no message)");
        fflush(stdout);
        exit(1);
    }
}

/* 定长数组越界：fail-fast（可在 Quelmara.toml [build] bounds_check=false 关闭） */
static void qlm_bounds(int64_t i, int64_t n) {
    if (i < 0 || i >= n) {
        fprintf(stderr, "quelmara: index out of bounds (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
}

/* 切片：{ptr, len} 两字零拷贝视图（SPEC §2 `[]T`）。
   ptr 指向元素序列，len 是元素个数；元素一律按 8 字节字存放，
   因此 str 元素是 `const char **`，其余按 `int64_t *` 访问。
   数组 -> 切片是零拷贝转换，两者共享同一段存储。 */
typedef struct { void *ptr; int64_t len; } QlmSlice;

static void qlm_slice_bounds(int64_t i, int64_t n) {
    if (i < 0 || i >= n) {
        fprintf(stderr, "quelmara: slice index out of bounds (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
}

/* 字符串切片 / 单字节串 / 读文件：都用轮转静态缓冲，避免在 C 后端引入堆。 */
static char *qlm_strslot(void) {
    static char bufs[64][1024];
    static int k = 0;
    char *p = bufs[k];
    k = (k + 1) & 63;
    return p;
}

static const char *qlm_substr(const char *s, int64_t lo, int64_t n) {
    int64_t len = (int64_t)strlen(s);
    char *buf;
    if (lo < 0 || n < 0 || lo + n > len) {
        fprintf(stderr, "quelmara: substr() range out of bounds (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
    if (n > 1023) n = 1023;                 /* 轮转缓冲上限，超长截断 */
    buf = qlm_strslot();
    memcpy(buf, s + lo, (size_t)n);
    buf[n] = 0;
    return buf;
}

/* vec[T]：堆上变长数组。头部 {buf, len, cap, esz}，esz = sizeof(元素类型)。
   C 侧一律用字节偏移 + memcpy，这样 bool（1 字节）/struct（含 padding）都对。 */
typedef struct { char *buf; int64_t len; int64_t cap; int64_t esz; } QlmVec;

static void qlm_vec_fail(void) {
    fprintf(stderr, "quelmara: vec index out of bounds (fail-fast)\n");
    fflush(stdout);
    exit(1);
}

static void qlm_vec_bounds(QlmVec *v, int64_t i) {
    if (i < 0 || i >= v->len) qlm_vec_fail();
}

static QlmVec *qlm_vec_new(int64_t cap, int64_t esz) {
    QlmVec *v = (QlmVec *)malloc(sizeof(QlmVec));
    if (!v) qlm_vec_fail();
    if (cap < 4) cap = 4;
    if (esz < 1) esz = 1;
    v->buf = (char *)malloc((size_t)(cap * esz));
    if (!v->buf) qlm_vec_fail();
    v->len = 0;
    v->cap = cap;
    v->esz = esz;
    return v;
}

static void qlm_vec_grow(QlmVec *v) {
    if (v->len < v->cap) return;
    int64_t ncap = v->cap * 2;
    char *nb = (char *)realloc(v->buf, (size_t)(ncap * v->esz));
    if (!nb) qlm_vec_fail();
    v->buf = nb;
    v->cap = ncap;
}

static void qlm_vec_push(QlmVec *v, int64_t x) {
    qlm_vec_grow(v);
    *(int64_t *)(v->buf + v->len * v->esz) = x;
    v->len++;
}

static void qlm_vec_push_n(QlmVec *v, const void *src) {
    qlm_vec_grow(v);
    memcpy(v->buf + v->len * v->esz, src, (size_t)v->esz);
    v->len++;
}

static int64_t qlm_vec_get(QlmVec *v, int64_t i) {
    qlm_vec_bounds(v, i);
    return *(int64_t *)(v->buf + i * v->esz);
}

static void *qlm_vec_get_n(QlmVec *v, int64_t i, void *dst) {
    qlm_vec_bounds(v, i);
    memcpy(dst, v->buf + i * v->esz, (size_t)v->esz);
    return dst;
}

static void qlm_vec_set(QlmVec *v, int64_t i, int64_t x) {
    qlm_vec_bounds(v, i);
    *(int64_t *)(v->buf + i * v->esz) = x;
}

static void qlm_vec_set_n(QlmVec *v, int64_t i, const void *src) {
    qlm_vec_bounds(v, i);
    memcpy(v->buf + i * v->esz, src, (size_t)v->esz);
}

static int64_t qlm_vec_pop(QlmVec *v) {
    if (v->len <= 0) qlm_vec_fail();
    v->len--;
    return *(int64_t *)(v->buf + v->len * v->esz);
}

static void *qlm_vec_pop_n(QlmVec *v, void *dst) {
    if (v->len <= 0) qlm_vec_fail();
    v->len--;
    memcpy(dst, v->buf + v->len * v->esz, (size_t)v->esz);
    return dst;
}

static int64_t qlm_vec_len(QlmVec *v) { return v->len; }

static void qlm_vec_clear(QlmVec *v) { v->len = 0; }

static int64_t qlm_str_cmp(const char *a, const char *b) {
    int c = strcmp(a, b);
    return c < 0 ? -1 : (c > 0 ? 1 : 0);
}

static void qlm_range(int64_t lo, int64_t hi, int64_t len) {
    if (lo < 0 || hi < lo || hi > len) {
        fprintf(stderr, "quelmara: sub-slice range out of bounds (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
}

static const char *qlm_chr(int64_t b) {
    char *buf = qlm_strslot();
    buf[0] = (char)(b & 0xFF);
    buf[1] = 0;
    return buf;
}

static const char *qlm_read_text(const char *path) {
    FILE *f = fopen(path, "rb");
    long sz;
    char *buf;
    if (!f) {
        fprintf(stderr, "quelmara: read_text() failed (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
    fseek(f, 0, SEEK_END);
    sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    buf = (char *)malloc((size_t)sz + 1);
    if (!buf || fread(buf, 1, (size_t)sz, f) != (size_t)sz) {
        fprintf(stderr, "quelmara: read_text() failed (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
    buf[sz] = 0;
    fclose(f);
    return buf;
}

static const char *qlm_str_from_bytes(const int64_t *data, int64_t n) {
    char *buf = (char *)malloc((size_t)n + 1);
    for (int64_t i = 0; i < n; i++) {
        buf[i] = (char)(data[i] & 0xFF);
    }
    buf[n] = 0;
    return buf;
}

static int64_t qlm_write_text(const char *path, const char *content) {
    FILE *f = fopen(path, "wb");
    size_t n;
    if (!f) {
        fprintf(stderr, "quelmara: write_text() failed (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
    n = fwrite(content, 1, strlen(content), f);
    fclose(f);
    return (int64_t)n;
}

/* 命令行参数：main 入口把 argc/argv 交给运行时，args() 返回 {argv+1, argc-1}
   （语义与自研后端一致：不含程序名）。 */
static int qlm_argc = 0;
static char **qlm_argv = 0;

static void qlm_set_args(int argc, char **argv) {
    qlm_argc = argc;
    qlm_argv = argv;
}

static QlmSlice qlm_args(void) {
    int64_t n = (int64_t)qlm_argc - 1;
    QlmSlice s;
    if (n < 0) n = 0;
    s.ptr = (void *)(qlm_argv + 1);
    s.len = n;
    return s;
}

static const char *qlm_arg(int64_t i) {
    int64_t n = (int64_t)qlm_argc - 1;
    if (i < 0 || i >= n) {
        fprintf(stderr, "quelmara: arg() index out of bounds (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
    return qlm_argv[i + 1];
}

/* str 是零结尾字节串（与 __str_eq/__str_concat 同一表示），没有长度前缀，
   str[i] 需要先求 strlen 再比对。越界与数组/切片同策略 fail-fast。 */
static void qlm_str_bounds(int64_t i, int64_t n) {
    if (i < 0 || i >= n) {
        fprintf(stderr, "quelmara: str index out of bounds (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
}

/* str -> int 十进制解析（s.to_int() / to_int(s)）。
   要求整串都是十进制数字（可选前导 +/-），否则 fail-fast；
   溢出同样 fail-fast（不静默回绕）。与自研后端 __str_to_int 逐条对齐。 */
static int64_t qlm_str_to_int(const char *s) {
    int64_t i = 0, neg = 0, acc = 0, digits = 0;
    if (s[0] == '-' || s[0] == '+') {
        neg = (s[0] == '-');
        i = 1;
    }
    while (s[i] != '\0') {
        char c = s[i];
        if (c < '0' || c > '9') goto bad;
        if (acc > 922337203685477580LL) goto bad;
        acc = acc * 10 + (int64_t)(c - '0');
        if (acc < 0) goto bad;
        digits = 1;
        i++;
    }
    if (!digits) goto bad;
    return neg ? -acc : acc;
bad:
    fprintf(stderr, "quelmara: str.to_int() invalid decimal input (fail-fast)\n");
    fflush(stdout);
    exit(1);
}

/* spawn/join 任务句柄：rec[0] = 线程（0 = 单核同步执行），
   rec[1] = 参数块（块首字是返回值）。join 负责回收两块内存。 */
static int64_t qlm_join(int64_t h) {
    if (h == 0) return 0;
    int64_t *rec = (int64_t *)(intptr_t)h;
    if (rec[0] != 0) pthread_join((pthread_t)(uintptr_t)rec[0], NULL);
    int64_t *blk = (int64_t *)(intptr_t)rec[1];
    int64_t r = blk[0];
    free(blk);
    free(rec);
    return r;
}

/* 有界 MPMC 通道：固定容量、阻塞式 send/recv（SPEC §4）。
   closed：close() 后 send fail-fast；recv 排空后返回 0（零值）。 */
typedef struct {
    pthread_mutex_t m;
    pthread_cond_t not_empty, not_full;
    int64_t cap, head, tail, count, closed;
    int64_t *buf;
} QlmChan;

static void qlm_chan_fail(const char *what) {
    fprintf(stderr, "quelmara: %s on closed channel (fail-fast)\n", what);
    fflush(stdout);
    exit(1);
}

static int64_t qlm_chan_open(int64_t cap) {
    if (cap <= 0) cap = 1;
    QlmChan *c = (QlmChan *)malloc(sizeof(QlmChan));
    pthread_mutex_init(&c->m, NULL);
    pthread_cond_init(&c->not_empty, NULL);
    pthread_cond_init(&c->not_full, NULL);
    c->cap = cap; c->head = 0; c->tail = 0; c->count = 0; c->closed = 0;
    c->buf = (int64_t *)malloc((size_t)cap * sizeof(int64_t));
    return (int64_t)(intptr_t)c;
}

static int64_t qlm_chan_send(int64_t h, int64_t v) {
    QlmChan *c = (QlmChan *)(intptr_t)h;
    pthread_mutex_lock(&c->m);
    if (c->closed) { pthread_mutex_unlock(&c->m); qlm_chan_fail("send"); }
    while (c->count == c->cap) {
        if (c->closed) { pthread_mutex_unlock(&c->m); qlm_chan_fail("send"); }
        pthread_cond_wait(&c->not_full, &c->m);
    }
    c->buf[c->tail] = v;
    c->tail = (c->tail + 1) % c->cap;
    c->count++;
    pthread_cond_signal(&c->not_empty);
    pthread_mutex_unlock(&c->m);
    return 0;
}

static int64_t qlm_chan_recv(int64_t h) {
    QlmChan *c = (QlmChan *)(intptr_t)h;
    pthread_mutex_lock(&c->m);
    /* 关闭后排空再返回 0；未关闭且空则等待 */
    while (c->count == 0 && !c->closed) pthread_cond_wait(&c->not_empty, &c->m);
    if (c->count == 0) { pthread_mutex_unlock(&c->m); return 0; }
    int64_t v = c->buf[c->head];
    c->head = (c->head + 1) % c->cap;
    c->count--;
    pthread_cond_signal(&c->not_full);
    pthread_mutex_unlock(&c->m);
    return v;
}

/* close()：幂等校验（重复关闭 fail-fast）；广播唤醒全部等待方 */
static int64_t qlm_chan_close(int64_t h) {
    QlmChan *c = (QlmChan *)(intptr_t)h;
    pthread_mutex_lock(&c->m);
    if (c->closed) {
        pthread_mutex_unlock(&c->m);
        fprintf(stderr, "quelmara: chan double close (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
    c->closed = 1;
    pthread_cond_broadcast(&c->not_empty);
    pthread_cond_broadcast(&c->not_full);
    pthread_mutex_unlock(&c->m);
    return 0;
}

/* try_recv（v0.11 select 用）：非阻塞取一个；*ok=1 取到、0 空/已关闭排空 */
static int64_t qlm_chan_try_recv(int64_t h, int64_t *ok) {
    QlmChan *c = (QlmChan *)(intptr_t)h;
    pthread_mutex_lock(&c->m);
    if (c->count == 0) {
        pthread_mutex_unlock(&c->m);
        *ok = 0;
        return 0;
    }
    int64_t v = c->buf[c->head];
    c->head = (c->head + 1) % c->cap;
    c->count--;
    pthread_cond_signal(&c->not_full);
    pthread_mutex_unlock(&c->m);
    *ok = 1;
    return v;
}

static int64_t qlm_chan_closed(int64_t h) {
    QlmChan *c = (QlmChan *)(intptr_t)h;
    pthread_mutex_lock(&c->m);
    int64_t cl = c->closed;
    pthread_mutex_unlock(&c->m);
    return cl;
}

/* map[K]V：开放寻址 + 线性探测哈希表（SPEC 附录 v0.10；v1.41 值扩容）。
   控制块 [cap, count, used, ktag, esz, st, kt, vt]：st/kt/vt 三组平行槽，
   值槽宽 esz 字（标量 1；聚合值按 C 类型 sizeof）。每槽 state 0=空 1=占用
   2=墓碑；键相等 int/bool 按值、str 按内容（qlm_str_eq）；哈希：整数
   splitmix64 终混、str FNV-1a —— 必须与原生后端 __map_hash_* 逐位一致，
   否则双链 diff 会挂。扩容：used*10 >= cap*7 时容量翻倍 rehash（墓碑不带入）。
   arena 绑定：原生后端走 bump 分配器，arena 块结束整体回收；
   C 后端的 arena 是纯作用域，这里 malloc 出来的表到进程退出才回收。 */
typedef struct {
    int64_t cap, count, used, ktag, esz;
    int64_t *st, *kt, *vt;
} QlmMap;

static uint64_t qlm_map_hash_word(int64_t x) {
    uint64_t z = (uint64_t)x;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static uint64_t qlm_map_hash_str(const char *s) {
    uint64_t h = 0xcbf29ce484222325ULL;
    const unsigned char *p = (const unsigned char *)(s ? s : "");
    for (; *p; p++) h = (h ^ (uint64_t)(*p)) * 0x100000001b3ULL;
    return h;
}

static uint64_t qlm_map_hash(const QlmMap *m, int64_t k) {
    return m->ktag ? qlm_map_hash_str((const char *)(intptr_t)k)
                   : qlm_map_hash_word(k);
}

static bool qlm_map_key_eq(const QlmMap *m, int64_t a, int64_t b) {
    return m->ktag ? qlm_str_eq((const char *)(intptr_t)a, (const char *)(intptr_t)b)
                   : (a == b);
}

static int64_t qlm_map_find(QlmMap *m, int64_t k) {
    int64_t mask = m->cap - 1;
    int64_t i = (int64_t)(qlm_map_hash(m, k) & (uint64_t)mask);
    for (;;) {
        int64_t s = m->st[i];
        if (s == 0) return -1;                       /* 空槽：探测链断 */
        if (s == 1 && qlm_map_key_eq(m, m->kt[i], k)) return i;
        i = (i + 1) & mask;                          /* 线性探测（墓碑继续探） */
    }
}

static void qlm_map_grow(QlmMap *m) {
    int64_t ocap = m->cap, ncap = ocap * 2, nmask = ncap - 1, i;
    int64_t *ost = m->st, *okt = m->kt, *ovt = m->vt;
    int64_t *nst = (int64_t *)calloc((size_t)ncap, sizeof(int64_t));
    int64_t *nkt = (int64_t *)calloc((size_t)ncap, sizeof(int64_t));
    int64_t *nvt = (int64_t *)calloc((size_t)(ncap * m->esz), sizeof(int64_t));
    int64_t nused = 0;
    for (i = 0; i < ocap; i++) {
        if (ost[i] != 1) continue;                   /* 墓碑/空槽不带入 */
        int64_t k = okt[i];
        int64_t j = (int64_t)(qlm_map_hash(m, k) & (uint64_t)nmask);
        while (nst[j] == 1) j = (j + 1) & nmask;
        nst[j] = 1; nkt[j] = k;
        memcpy(nvt + j * m->esz, ovt + i * m->esz, (size_t)(m->esz * sizeof(int64_t)));
        nused++;
    }
    m->cap = ncap; m->used = nused;
    m->st = nst; m->kt = nkt; m->vt = nvt;
    free(ost); free(okt); free(ovt);
}

static int64_t qlm_map_open(int64_t cap, int64_t ktag, int64_t esz) {
    if (esz < 1) esz = 1;
    if (cap < 1) cap = 16;                           /* 默认容量 16 */
    cap--;                                           /* 向上取整到 2 的幂 */
    cap |= cap >> 1; cap |= cap >> 2; cap |= cap >> 4;
    cap |= cap >> 8; cap |= cap >> 16; cap |= cap >> 32;
    cap++;
    QlmMap *m = (QlmMap *)malloc(sizeof(QlmMap));
    m->cap = cap; m->count = 0; m->used = 0; m->ktag = ktag; m->esz = esz;
    m->st = (int64_t *)calloc((size_t)cap, sizeof(int64_t));
    m->kt = (int64_t *)calloc((size_t)cap, sizeof(int64_t));
    m->vt = (int64_t *)calloc((size_t)(cap * esz), sizeof(int64_t));
    return (int64_t)(intptr_t)m;
}

static int64_t qlm_map_set(int64_t h, int64_t k, int64_t v) {
    QlmMap *m = (QlmMap *)(intptr_t)h;
    int64_t mask = m->cap - 1;
    int64_t i = (int64_t)(qlm_map_hash(m, k) & (uint64_t)mask), first = -1;
    for (;;) {
        int64_t s = m->st[i];
        if (s == 0) {
            if (first >= 0) i = first;               /* 复用墓碑，探测链不断 */
            m->st[i] = 1; m->kt[i] = k; m->vt[i] = v;
            m->count++;
            if (first < 0) m->used++;
            if (m->used * 10 >= m->cap * 7) qlm_map_grow(m);
            return 0;
        }
        if (s == 2) {
            if (first < 0) first = i;                /* 记第一个墓碑 */
        } else if (qlm_map_key_eq(m, m->kt[i], k)) {
            m->vt[i] = v;                            /* 覆盖写 */
            return 0;
        }
        i = (i + 1) & mask;
    }
}

static int64_t qlm_map_get(int64_t h, int64_t k) {
    QlmMap *m = (QlmMap *)(intptr_t)h;
    int64_t i = qlm_map_find(m, k);
    if (i < 0) {
        /* 键不存在：fail-fast（打印错误 + 非零退出，不返回垃圾值） */
        fprintf(stderr, "quelmara: map key not found (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
    return m->vt[i];
}

/* 聚合值插入/覆盖写（v1.41）：值写按 esz 字 memcpy 进 vt[i*esz]。
   探测结构与 qlm_map_set 完全一致；只在聚合值 map 上生成调用。 */
static int64_t qlm_map_set_n(int64_t h, int64_t k, const void *src) {
    QlmMap *m = (QlmMap *)(intptr_t)h;
    int64_t mask = m->cap - 1;
    int64_t i = (int64_t)(qlm_map_hash(m, k) & (uint64_t)mask), first = -1;
    for (;;) {
        int64_t s = m->st[i];
        if (s == 0) {
            if (first >= 0) i = first;               /* 复用墓碑，探测链不断 */
            m->st[i] = 1; m->kt[i] = k;
            memcpy(m->vt + i * m->esz, src, (size_t)(m->esz * sizeof(int64_t)));
            m->count++;
            if (first < 0) m->used++;
            if (m->used * 10 >= m->cap * 7) qlm_map_grow(m);
            return 0;
        }
        if (s == 2) {
            if (first < 0) first = i;                /* 记第一个墓碑 */
        } else if (qlm_map_key_eq(m, m->kt[i], k)) {
            memcpy(m->vt + i * m->esz, src, (size_t)(m->esz * sizeof(int64_t)));
            return 0;                                /* 覆盖写 */
        }
        i = (i + 1) & mask;
    }
}

/* 聚合值拷出（v1.41）：键不存在同样 fail-fast；命中后 memcpy esz 字到 dst。 */
static void *qlm_map_get_n(int64_t h, int64_t k, void *dst) {
    QlmMap *m = (QlmMap *)(intptr_t)h;
    int64_t i = qlm_map_find(m, k);
    if (i < 0) {
        fprintf(stderr, "quelmara: map key not found (fail-fast)\n");
        fflush(stdout);
        exit(1);
    }
    memcpy(dst, m->vt + i * m->esz, (size_t)(m->esz * sizeof(int64_t)));
    return dst;
}

static bool qlm_map_has(int64_t h, int64_t k) {
    QlmMap *m = (QlmMap *)(intptr_t)h;
    return qlm_map_find(m, k) >= 0;
}

static int64_t qlm_map_del(int64_t h, int64_t k) {
    QlmMap *m = (QlmMap *)(intptr_t)h;
    int64_t i = qlm_map_find(m, k);
    if (i >= 0) {
        m->st[i] = 2;                                /* 墓碑：探测链继续有效 */
        m->count--;
    }
    return 0;                                        /* 删缺失键：无操作 */
}

static int64_t qlm_map_cap(int64_t h) { return ((QlmMap *)(intptr_t)h)->cap; }
static int64_t qlm_map_state(int64_t h, int64_t i) { return ((QlmMap *)(intptr_t)h)->st[i]; }
static int64_t qlm_map_key_at(int64_t h, int64_t i) { return ((QlmMap *)(intptr_t)h)->kt[i]; }

static int64_t qlm_map_len(int64_t h) {
    QlmMap *m = (QlmMap *)(intptr_t)h;
    return m->count;
}
"""

NET_RUNTIME = r"""
/* ===== Quelmara runtime (net: epoll 非阻塞并发 reactor) ===== */
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef QLM_NET_MAX_CONNS
#define QLM_NET_MAX_CONNS 1000000
#endif
#ifndef QLM_RECV_BUF
#define QLM_RECV_BUF 4096
#endif

typedef struct QlmBuf { char *data; size_t len; } QlmBuf;
typedef struct QlmConn QlmConn;
struct QlmConn {
    int fd;
    char peer[64];
    bool closing;
};

#define NET_ACTION_CLOSE 0
#define NET_ACTION_KEEP  1

static const char *qlm_conn_peer(QlmConn *c) { return c->peer; }

/* 零拷贝回写；EAGAIN 时丢弃余量（背压策略 drop，见 Quelmara.toml [net].backpressure） */
static int qlm_conn_write(QlmConn *c, QlmBuf b) {
    size_t off = 0;
    while (off < b.len) {
        ssize_t n = write(c->fd, b.data + off, b.len - off);
        if (n > 0) { off += (size_t)n; continue; }
        if (n < 0 && errno == EAGAIN) return 0;   /* 背压：drop */
        return 1;                                  /* 错误：交由 ? 传播 -> 关闭 */
    }
    return 0;
}

static void qlm_echo_serve(const char *addr,
                              void (*on_connect)(QlmConn *),
                              int (*on_data)(QlmConn *, QlmBuf),
                              void (*on_close)(QlmConn *),
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

    QlmConn **conns = calloc((size_t)QLM_NET_MAX_CONNS, sizeof(QlmConn *));
    int64_t nconns = 0;
    struct epoll_event events[512];
    char rbuf[QLM_RECV_BUF];

    for (;;) {
        int n = epoll_wait(ep, events, 512, -1);
        for (int i = 0; i < n; i++) {
            int fd = events[i].data.fd;
            if (fd == lfd) {
                for (;;) {
                    int cfd = accept4(lfd, NULL, NULL, SOCK_NONBLOCK);
                    if (cfd < 0) break;
                    if (nconns >= max_conns || cfd >= QLM_NET_MAX_CONNS) {
                        close(cfd);            /* 超出 [net] max_conns：fail-fast 拒绝 */
                        continue;
                    }
                    if (nodelay) setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
                    QlmConn *c = (QlmConn *)calloc(1, sizeof(QlmConn));
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
                QlmConn *c = conns[fd];
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
                QlmBuf b = { rbuf, (size_t)rn };
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
        self.tmp_id = 0        # 数组越界检查临时变量计数
        self.threads = cfg["core"]["threads"] or os.cpu_count() or 1
        self.multicore = bool(cfg["core"]["multicore"]) and self.threads > 1
        self.bounds = bool(cfg["build"].get("bounds_check", True))
        self.uses_args = False

    # C99 是交叉验证后端，但**用户函数必须与 libc 隔离命名空间**（v2.91）。
    # 以前用户函数名原样落到 C：`send`/`read`/`open`/`index`/`time` 这类名字会
    # 与 <unistd.h>/<string.h> 的声明正面冲突（实测 `net.send` 编不过，报
    # "conflicting types for 'send'"）。而 `#include` 在用户代码之前，越靠后
    # 的声明越吃亏——gcc 直接把整个文件判死。
    #
    # 修法：用户函数统一加 `u_` 前缀。`main` 例外（外层 C 入口要调 `qlm_main`），
    # 已经有一套现成约定。运行库的 `qlm_*` 与用户函数从此不可能撞。
    C_FN_PREFIX = "u_"

    def cfn(self, name):
        """Quelmara 用户函数名 -> C 符号名（`u_` 前缀；`qlm_main` 保持原样）。

        **只给真正的用户函数加前缀。** 内置（`mem_load64`/`mem_alloc`/
        `static_word` …）由 C 运行库以 `qlm_*` 提供，或在 gen_expr 里单独映射；
        它们走到这里说明是一条还没被 C 后端实现的路径 —— 加 `u_` 只会把
        "未实现"伪装成"未定义符号"，报错点从一个变一片（实测 echo_server
        里 `void h = u_mem_load64(...)`：因为查不到返回类型，连类型都推成 void）。
        保持原名，至少错误信息指向真名。
        """
        if name == "qlm_main":
            return name
        if name not in self.infer.fns:
            return name                    # 内置/运行库：不加前缀
        return self.C_FN_PREFIX + name

    # ---- 工具 ----
    def ctype(self, t):
        if t[0] == "array":
            # C99 只做交叉验证，数组的按值传参/返回（隐藏出参）只在自研后端实现。
            raise SyntaxError(
                "C99 后端不支持定长数组作参数/返回值（仅自研后端支持）；"
                "交叉验证时请改用 slice_of(a) 或 vec[T]")
        if t[0] == "chan":
            return "int64_t"
        if t[0] == "map":
            return "int64_t"          # map 句柄：整数字（指向运行时表）
        if t[0] == "vec":
            return "int64_t"          # vec 句柄：QlmVec* 转成的整数
        if t[0] == "slice":
            elem = slice_elem_tag(t[1])          # 元素类型越界时在这里报错
            return "QlmBuf" if elem == "byte" else "QlmSlice"
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
        out = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        return f'"{out}"'

    # ---- 表达式 ----
    def gen_expr(self, e, env):
        k = e[0]
        if k == "lambda":
            # 闭包需要"代码地址 + 捕获环境"两字值 + 隐藏 env 形参的调用约定，
            # C 后端只做交叉验证，不复制这套 ABI —— 明确 fail-fast。
            raise SyntaxError(
                "C 后端不支持闭包字面量 fn(...) { ... }（v1.95 边界："
                "只进自研后端）")
        if k == "interp":
            # 插值字符串的 C 侧要接 qlm_str_from_i64 / qlm_f64_to_str / 链式拼接，
            # 与原生后端的单次分配语义对不齐；C 只做交叉验证，直接 fail-fast。
            raise SyntaxError(
                "C 后端不支持插值字符串 f\"...\"（v1.61 边界：只进原生后端）")
        if k == "num":
            return f"(int64_t)({e[1]})", "int64_t"
        if k == "fnum":
            if e[2] == "f32":
                # f32 字面量：用 f32 舍入后的精确值 + f 后缀，与原生后端逐位一致
                v32 = struct.unpack("<f", struct.pack("<f", e[1]))[0]
                return f"((float){v32!r}f)", "float"
            return f"(double)({e[1]!r})", "double"
        if k == "str":
            return self.cstr(e[1]), "const char *"
        if k == "bool":
            return ("true" if e[1] else "false"), "bool"
        if k == "name":
            # 裸函数名当值（函数指针）：必须映射到 C 符号名。以前直接返回
            # `e[1]`，生成的 C 里就是 `hello` 这个未声明标识符 —— 实测
            # `let s = S { cb: hello }` 编不过（"‘hello’ undeclared"）。
            # 自研后端一直是对的（它发 `fnaddr`），所以这是 C 后端独有的缺口。
            if e[1] in self.infer.fns:
                return self.cfn(e[1]), "int64_t"
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
                if is_map_env(t):
                    raise SyntaxError("print 不支持 map 句柄；请打印 get 到的值")
                if t == "const char *":
                    return f"qlm_print_str({code})", "void"
                if t == "bool":
                    return f"qlm_print_bool({code})", "void"
                if is_float_env(t):
                    return f"qlm_print_f64((double)({code}))", "void"
                return f"qlm_print_i64({code})", "void"
            if name == "to_float" and name not in self.infer.fns:
                # to_float(x)：int/bool -> double（浮点唯一隐式入口，显式转换）
                if len(e[2]) != 1:
                    raise SyntaxError("to_float(x) 需要且只需要一个实参")
                acode, at = self.gen_expr(e[2][0], env)
                if at == "const char *":
                    raise SyntaxError(
                        "to_float(str) 不做十进制解析——旧实现会把字符串指针"
                        "当数值转，静默给出垃圾值（见 docs/07-gaps.md §7.10）。"
                        "请用 std/f64 的 f64_parse(s)")
                if is_float_env(at):
                    return f"(double)({acode})", "double"
                return f"((double)({acode}))", "double"
            if name == "to_f32" and name not in self.infer.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("to_f32(x) 需要且只需要一个实参")
                acode, _ = self.gen_expr(e[2][0], env)
                return f"((float)({acode}))", "float"
            if name == "to_int" and name not in self.infer.fns:
                # to_int(x)：浮点 -> int（向零截断）；str -> int（十进制解析，非法输入 fail-fast）
                if len(e[2]) != 1:
                    raise SyntaxError("to_int(x) 需要且只需要一个实参")
                acode, at = self.gen_expr(e[2][0], env)
                if at == "const char *":
                    return f"qlm_str_to_int({acode})", "int64_t"
                return f"((int64_t)({acode}))", "int64_t"
            if name == "cores":
                return "qlm_cores()", "int64_t"
            if name == "eprint" and name not in self.infer.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("eprint(x) 需要一个实参")
                code, t = self.gen_expr(e[2][0], env)
                if t == "const char *":
                    return f'(fprintf(stderr, "%s\\n", {code}))', "int64_t"
                if t == "bool":
                    return f'(fprintf(stderr, "%s\\n", ({code}) ? "true" : "false"))', "int64_t"
                if is_float_env(t):
                    return f'(fprintf(stderr, "%g\\n", (double)({code})))', "int64_t"
                return f'(fprintf(stderr, "%lld\\n", (long long)({code})))', "int64_t"
            if name == "exit" and name not in self.infer.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("exit(code) 需要一个实参")
                code, _t = self.gen_expr(e[2][0], env)
                return f'(exit((int)({code})))', "int64_t"
            if name == "substr" and name not in self.infer.fns:
                if len(e[2]) != 3:
                    raise SyntaxError("substr(s, lo, n) 需要三个实参")
                a1, _ = self.gen_expr(e[2][0], env)
                a2, _ = self.gen_expr(e[2][1], env)
                a3, _ = self.gen_expr(e[2][2], env)
                return f"qlm_substr({a1}, (int64_t)({a2}), (int64_t)({a3}))", "const char *"
            if name == "chr" and name not in self.infer.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("chr(x) 需要一个实参")
                a1, _ = self.gen_expr(e[2][0], env)
                return f"qlm_chr((int64_t)({a1}))", "const char *"
            if name == "read_text" and name not in self.infer.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("read_text(path) 需要一个实参")
                a1, _ = self.gen_expr(e[2][0], env)
                return f"qlm_read_text({a1})", "const char *"
            if name == "str_from_bytes" and name not in self.infer.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("str_from_bytes(v) 需要一个实参")
                a1, _ = self.gen_expr(e[2][0], env)
                return f"qlm_str_from_bytes({a1})", "const char *"
            if name == "write_text" and name not in self.infer.fns:
                if len(e[2]) != 2:
                    raise SyntaxError("write_text(path, content) 需要两个实参")
                a1, _ = self.gen_expr(e[2][0], env)
                a2, _ = self.gen_expr(e[2][1], env)
                return f"qlm_write_text({a1}, {a2})", "int"
            if name == "args" and name not in self.infer.fns:
                if e[2]:
                    raise SyntaxError("args() 不接受实参")
                self.uses_args = True
                return "qlm_args()", "slice:str"
            if name == "arg" and name not in self.infer.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("arg(i) 需要且只需要一个下标")
                self.uses_args = True
                icode, _ = self.gen_expr(e[2][0], env)
                return f"qlm_arg({icode})", "const char *"
            if name == "assert":
                ccode, _ = self.gen_expr(e[2][0], env)
                msg = "(no message)"
                if len(e[2]) > 1 and e[2][1][0] == "str":
                    msg = e[2][1][1]
                return (f'qlm_assert(({ccode}), "{msg}")', "void")
            if name == "len" and name not in self.infer.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("len(x) 需要且只需要一个实参")
                arg = e[2][0]
                if arg[0] == "name":
                    at = env.get(arg[1], "")
                    if is_arr_env(at):
                        return str(arr_env_parts(at)[1]), "int64_t"
                    if is_slice_env(at):
                        return f"({arg[1]}).len", "int64_t"
                    if is_map_env(at):
                        return f"qlm_map_len({arg[1]})", "int64_t"
                    if is_vec_env(at):
                        return f"qlm_vec_len({arg[1]})", "int64_t"
                    if at == "const char *":
                        return f"((int64_t)strlen({arg[1]}))", "int64_t"
                acode, atype = self.gen_expr(arg, env)
                if atype == "QlmSlice" or is_slice_env(atype):
                    return f"({acode}).len", "int64_t"
                if is_map_env(atype):
                    return f"qlm_map_len({acode})", "int64_t"
                if is_vec_env(atype):
                    return f"qlm_vec_len({acode})", "int64_t"
                if atype == "const char *":
                    return f"((int64_t)strlen({acode}))", "int64_t"
                raise SyntaxError(f"len() 目前只支持定长数组、切片、map、vec 或 str（实参类型={atype!r}）")
            if name == "slice_of" and name not in self.infer.fns:
                # 数组 -> 切片：零拷贝转换（SPEC §2 `[]T`）
                if len(e[2]) != 1:
                    raise SyntaxError("slice_of(x) 需要且只需要一个数组实参")
                arg = e[2][0]
                if arg[0] != "name" or not is_arr_env(env.get(arg[1], "")):
                    raise SyntaxError("slice_of() 目前只支持定长数组变量（零拷贝转换）")
                elem, n = arr_env_parts(env[arg[1]])
                return (f"(({slice_cname(elem)}){{ (void *)({arg[1]}), (int64_t)({n}) }})",
                        "slice:" + elem)
            if name == "join" and name not in self.infer.fns:
                if len(e[2]) != 1:
                    raise SyntaxError("join(handle) 需要且只需要一个句柄")
                hcode, _ = self.gen_expr(e[2][0], env)
                return f"qlm_join({hcode})", "int64_t"
            # 实参：数组传给 `[]T` 形参时零拷贝转切片（SPEC §2）
            fdef = self.infer.fns.get(name)
            parts = []
            for i, a in enumerate(e[2]):
                acode, atype = self.gen_expr(a, env)
                if fdef and i < len(fdef["params"]):
                    pt = fdef["params"][i][1]
                    if pt[0] == "slice" and is_arr_env(atype):
                        pe, pn = arr_env_parts(atype)
                        acode = f"(({slice_cname(pe)}){{ (void *)({acode}), (int64_t)({pn}) }})"
                    elif pt[0] == "slice" and is_slice_env(atype) \
                            and slice_env_elem(atype) != slice_elem_tag(pt[1]):
                        raise SyntaxError(
                            f"切片实参元素类型不匹配：得到 {slice_env_elem(atype)}，"
                            f"形参需要 {slice_elem_tag(pt[1])}")
                parts.append(acode)
            args = ", ".join(parts)
            if name in env:
                # 通过变量间接调用（`fn apply(f: int) { f(x) }`）：`f` 是环境里的
                # 函数指针值，不是用户函数名 —— 不能加 `u_` 前缀。
                # 函数值在 Quelmara 里的静态类型是 `int`（与 `fn` 形参声明一致），
                # 而 C 的 `int64_t` 不可直接调用，必须就地转成函数指针类型。
                # 返回类型无从得知（无签名信息，与自研后端 `callr` 同一信任级），
                # 按 int64_t 处理；聚合返回值不可间接调用（自研后端亦然）。
                return (f"((int64_t(*)(/*args*/void*))({name}))({args})"
                        if not args else
                        f"((int64_t(*)(int64_t))({name}))({args})"), "int64_t"
            return f"{self.cfn(name)}({args})", self.infer.fn_ret(name)
        if k == "spawn":
            return self.gen_spawn(e[1], env)
        if k == "select":
            # select { c1.recv(), c2.recv() }（v0.11）：轮询 + usleep 等待，
            # 声明序优先；全部关闭且排空 -> 0。try_recv 非阻塞，ok 出参报捷。
            chans = []
            for arm in e[1]:
                if not (arm[0] == "method" and arm[1][0] == "name"
                        and arm[2] == "recv" and not arm[3]):
                    raise SyntaxError("select 臂必须是 chan 变量上的 ch.recv()")
                if not env.get("__chan__" + arm[1][1]):
                    raise SyntaxError("select 臂只能用于 chan 通道")
                chans.append(arm[1][1])
            self.tmp_id += 1
            n = self.tmp_id
            tries = []
            for i, ch in enumerate(chans):
                tries.append(
                    f"{{ int64_t _so{n}_{i}; int64_t _sv{n}_{i} = "
                    f"qlm_chan_try_recv({ch}, &_so{n}_{i}); "
                    f"if (_so{n}_{i}) {{ _sr{n} = _sv{n}_{i}; break; }} }}")
            closed = " && ".join(f"qlm_chan_closed({ch})" for ch in chans)
            return ("({ int64_t _sr%d = 0; for (;;) { %s "
                    "if (%s) { _sr%d = 0; break; } usleep(100); } _sr%d; })"
                    % (n, " ".join(tries), closed, n, n)), "int64_t"
        if k == "index":
            ocode, otype = self.gen_expr(e[1], env)
            if is_arr_env(otype):
                n = arr_env_parts(otype)[1]
                icode, _ = self.gen_expr(e[2], env)
                if self.bounds:
                    self.tmp_id += 1
                    tmp = f"_bi{self.tmp_id}"
                    return (f"({{ int64_t {tmp} = (int64_t)({icode}); "
                            f"qlm_bounds({tmp}, {n}); ({ocode})[{tmp}]; }})", "int64_t")
                return f"({ocode})[({icode})]", "int64_t"
            if is_slice_env(otype):
                elem = slice_env_elem(otype)
                pfield, cast, rtype = slice_access(elem)
                icode, _ = self.gen_expr(e[2], env)
                if self.bounds:
                    self.tmp_id += 1
                    tmp = f"_bi{self.tmp_id}"
                    return (f"({{ int64_t {tmp} = (int64_t)({icode}); "
                            f"qlm_slice_bounds({tmp}, ({ocode}).len); "
                            f"(({cast})({ocode}).{pfield})[{tmp}]; }})", rtype)
                return f"(({cast})({ocode}).{pfield})[({icode})]", rtype
            if otype == "const char *":
                # str[i] -> 该字节的无符号值（0..255）；长度是运行期 strlen，
                # 越界与数组/切片同策略 fail-fast
                icode, _ = self.gen_expr(e[2], env)
                if self.bounds:
                    self.tmp_id += 1
                    tmp = f"_bi{self.tmp_id}"
                    return (f"({{ int64_t {tmp} = (int64_t)({icode}); "
                            f"qlm_str_bounds({tmp}, (int64_t)strlen({ocode})); "
                            f"((int64_t)(unsigned char)({ocode})[{tmp}]); }})", "int64_t")
                return f"((int64_t)(unsigned char)({ocode})[({icode})])", "int64_t"
            raise SyntaxError("下标只能用于定长数组、切片或 str")
        if k == "vecnew":
            cap = "4"
            if e[2]:
                if len(e[2]) != 1:
                    raise SyntaxError("vec[T].new(cap) 只接受一个容量实参")
                ccode, _ = self.gen_expr(e[2][0], env)
                cap = f"(int64_t)({ccode})"
            esz = self.ctype(e[1]) if e[1][0] == "named" and e[1][1] in self.structs \
                else ("int64_t" if e[1] == ("named", "bool") else
                      ("const char *" if e[1] == ("named", "str") else self.ctype(e[1])))
            return (f"qlm_vec_new({cap}, (int64_t)sizeof({esz}))",
                    "vec:" + _vec_tag_str(e[1]))
        if k == "sliceof":
            ocode, otype = self.gen_expr(e[1], env)
            lcode, _ = self.gen_expr(e[2], env)
            hcode, _ = self.gen_expr(e[3], env)
            self.tmp_id += 1
            base = f"_sl{self.tmp_id}"
            if otype == "const char *":
                return (f"({{ int64_t {base}l = (int64_t)({lcode}); "
                        f"int64_t {base}h = (int64_t)({hcode}); "
                        f"qlm_range({base}l, {base}h, (int64_t)strlen({ocode})); "
                        f"qlm_substr({ocode}, {base}l, {base}h - {base}l); }})",
                        "const char *")
            if is_arr_env(otype):
                n = arr_env_parts(otype)[1]
                return (f"({{ int64_t {base}l = (int64_t)({lcode}); "
                        f"int64_t {base}h = (int64_t)({hcode}); "
                        f"qlm_range({base}l, {base}h, {n}); "
                        f"(QlmSlice){{ .ptr = (void *)((int64_t *)({ocode}) + {base}l), "
                        f".len = {base}h - {base}l }}; }})",
                        "slice:" + arr_env_parts(otype)[0])
            if is_slice_env(otype):
                elem = slice_env_elem(otype)
                pfield, cast, _rt = slice_access(elem)
                return (f"({{ int64_t {base}l = (int64_t)({lcode}); "
                        f"int64_t {base}h = (int64_t)({hcode}); "
                        f"qlm_range({base}l, {base}h, ({ocode}).len); "
                        f"(QlmSlice){{ .ptr = (void *)(({cast})({ocode}).{pfield} + {base}l), "
                        f".len = {base}h - {base}l }}; }})", otype)
            raise SyntaxError("子切片 a[lo..hi] 只支持 str、切片与定长数组")
        if k == "arraylit":
            raise SyntaxError("数组字面量只能直接用于 let（v0.6 边界）")
        if k == "chanopen":
            if len(e[2]) != 1:
                raise SyntaxError("chan[T].open(cap) 需要且只需要一个容量实参")
            cap, _ = self.gen_expr(e[2][0], env)
            return f"qlm_chan_open({cap})", "int64_t"
        if k == "mapnew":
            tag = map_env_of_type(e[1])
            if tag is None:
                raise SyntaxError("map 构造语法是 map[K]V.new(cap)")
            if len(e[2]) > 1:
                raise SyntaxError("map[K]V.new(cap) 至多一个容量实参")
            ktag = 1 if map_env_parts(tag)[0] == "str" else 0
            vv0 = map_env_parts(tag)[1]
            # 值扩容（v1.41）：聚合值槽宽 = sizeof(C 类型)；标量 1
            esz = f"sizeof({vv0})" if vv0 not in MAP_KV_SCALARS else "1"
            cap = "16"
            if e[2]:
                cap, _ = self.gen_expr(e[2][0], env)
            return f"qlm_map_open({cap}, {ktag}, {esz})", tag
        if k == "method":
            obj, m, args = e[1], e[2], e[3]
            ocode, otype = self.gen_expr(obj, env)
            if is_vec_env(otype):
                elem = vec_env_elem(otype)
                if m == "len":
                    if args:
                        raise SyntaxError("vec.len() 不接受实参")
                    return f"qlm_vec_len({ocode})", "int64_t"
                if m == "clear":
                    if args:
                        raise SyntaxError("vec.clear() 不接受实参")
                    return f"qlm_vec_clear({ocode})", "int64_t"
                if m == "push":
                    if len(args) != 1:
                        raise SyntaxError("vec.push(v) 需要一个实参")
                    acode, atype = self.gen_expr(args[0], env)
                    if elem.startswith("agg:"):
                        tn = elem[4:]
                        return (f"({{ {tn} _vt = {acode}; "
                                f"qlm_vec_push_n({ocode}, (const void *)&_vt); (int64_t)0; }})",
                                "int64_t")
                    return f"qlm_vec_push({ocode}, (int64_t)({acode}))", "int64_t"
                if m == "pop":
                    if args:
                        raise SyntaxError("vec.pop() 不接受实参")
                    if elem.startswith("agg:"):
                        tn = elem[4:]
                        return (f"({{ {tn} _vt; qlm_vec_pop_n({ocode}, (void *)&_vt); _vt; }})",
                                "struct:" + tn)
                    base = f"qlm_vec_pop({ocode})"
                    if elem.startswith("mapinner:"):
                        return base, "map:" + elem[len("mapinner:"):]
                    return (f"((const char *)(intptr_t){base})", "const char *") \
                        if elem == "str" else (base, "int64_t")
                if m == "get":
                    if len(args) != 1:
                        raise SyntaxError("vec.get(i) 需要一个实参")
                    icode, _ = self.gen_expr(args[0], env)
                    if elem.startswith("agg:"):
                        tn = elem[4:]
                        return (f"({{ {tn} _vt; "
                                f"qlm_vec_get_n({ocode}, (int64_t)({icode}), (void *)&_vt); _vt; }})",
                                "struct:" + tn)
                    base = f"qlm_vec_get({ocode}, (int64_t)({icode}))"
                    if elem.startswith("mapinner:"):
                        return base, "map:" + elem[len("mapinner:"):]
                    return (f"((const char *)(intptr_t){base})", "const char *") \
                        if elem == "str" else (base, "int64_t")
                if m == "set":
                    if len(args) != 2:
                        raise SyntaxError("vec.set(i, v) 需要两个实参")
                    icode, _ = self.gen_expr(args[0], env)
                    vcode, _ = self.gen_expr(args[1], env)
                    if elem.startswith("agg:"):
                        tn = elem[4:]
                        return (f"({{ {tn} _vt = {vcode}; "
                                f"qlm_vec_set_n({ocode}, (int64_t)({icode}), (const void *)&_vt); "
                                f"(int64_t)0; }})", "int64_t")
                    return (f"qlm_vec_set({ocode}, (int64_t)({icode}), "
                            f"(int64_t)({vcode}))", "int64_t")
                raise SyntaxError(f"vec 不支持方法 {m}")
            mp = map_env_parts(otype) if is_map_env(otype) else None
            if mp:
                return self.gen_map_method(m, ocode, mp, args, env)
            if m in ("send", "recv"):
                if not self._is_chan_expr(obj, env):
                    raise SyntaxError(f".{m} 只能用于 chan 通道")
                if m == "send":
                    if len(args) != 1:
                        raise SyntaxError("ch.send(v) 需要一个实参")
                    acode, _ = self.gen_expr(args[0], env)
                    return f"qlm_chan_send({ocode}, {acode})", "int64_t"
                return f"qlm_chan_recv({ocode})", "int64_t"
            if m == "close":
                if not self._is_chan_expr(obj, env):
                    raise SyntaxError(".close 只能用于 chan 通道")
                if args:
                    raise SyntaxError("ch.close() 不接受实参")
                return f"qlm_chan_close({ocode})", "void"
            if m == "to_str":
                if otype == "const char *":
                    return ocode, "const char *"
                if otype == "bool":
                    return f"qlm_bool_to_str({ocode})", "const char *"
                if is_float_env(otype):
                    return f"qlm_f64_to_str((double)({ocode}))", "const char *"
                return f"qlm_i64_to_str({ocode})", "const char *"
            if m == "to_int":
                # s.to_int()：十进制解析；非法输入 fail-fast（与下标越界同策略）
                if args:
                    raise SyntaxError(".to_int() 不接受实参")
                if otype == "const char *":
                    return f"qlm_str_to_int({ocode})", "int64_t"
                if is_float_env(otype):
                    return f"((int64_t)({ocode}))", "int64_t"
                raise SyntaxError(".to_int() 只支持 str 与浮点")
            if m == "write":
                self.uses_net = True
                bcode, _ = self.gen_expr(args[0], env)
                return f"qlm_conn_write({ocode}, {bcode})", "int"
            if m == "peer_addr":
                self.uses_net = True
                return f"qlm_conn_peer({ocode})", "const char *"
            if m == "serve":
                return self.gen_serve(obj, env), "void"
            raise SyntaxError(f"未知方法 .{m}")
        if k == "binop":
            op = e[1]
            lc, lt = self.gen_expr(e[2], env)
            rc, rt = self.gen_expr(e[3], env)
            lf, rf = is_float_env(lt), is_float_env(rt)
            if lf or rf:
                if not (lf and rf):
                    raise SyntaxError("整数与浮点不能混合运算；请用 to_float(x) 显式转换")
                if op in ("%", "&", "|", "^", "<<", ">>"):
                    raise SyntaxError(f"浮点不支持运算符 {op}")
                if op == "+" and "const char *" in (lt, rt):
                    raise SyntaxError("字符串与浮点不能拼接；请用 to_str()")
                rt2 = unify_float(lt, rt)
                return (f"({lc} {op} {rc})",
                        "bool" if op in ("==", "!=", "<", "<=", ">", ">=") else rt2)
            if op == "+" and "const char *" in (lt, rt):
                return f"qlm_concat({lc}, {rc})", "const char *"
            if op in ("==", "!=") and "const char *" in (lt, rt):
                # 字符串比较：内容相等（非指针）
                cmp = f"qlm_str_eq({lc}, {rc})"
                return (f"({cmp})" if op == "==" else f"(!{cmp})"), "bool"
            if op in ("<", "<=", ">", ">=") and "const char *" in (lt, rt):
                # 字典序（早期这里是指针比较）
                return f"(qlm_str_cmp({lc}, {rc}) {op} 0)", "bool"
            if op == ">>>":
                return f"((int64_t)((uint64_t)({lc}) >> (uint64_t)({rc})))", "int64_t"
            return f"({lc} {op} {rc})", "bool" if op in ("==", "!=", "<", "<=", ">", ">=", "&&", "||") else "int64_t"
        if k == "unop":
            code, t = self.gen_expr(e[2], env)
            return f"({e[1]}{code})", "bool" if e[1] == "!" else t
        if k == "try":
            code, inner_t = self.gen_expr(e[1], env)
            if not (isinstance(inner_t, str) and inner_t.startswith("enum:")):
                raise SyntaxError("? 只能用于带 Ok/Err 变体的枚举结果")
            ename = inner_t[5:]
            variants = self.enums.get(ename, [])
            ok_index = next((i for i, (vn, _fs) in enumerate(variants) if vn == "Ok"), None)
            err_index = next((i for i, (vn, _fs) in enumerate(variants) if vn == "Err"), None)
            ok_fields = variants[ok_index][1] if ok_index is not None else None
            err_fields = variants[err_index][1] if err_index is not None else None
            if len(variants) != 2 or ok_index is None or err_index is None \
                    or not ok_fields or not err_fields or len(ok_fields) != 1 or len(err_fields) != 1:
                raise SyntaxError("结果枚举必须只有 Ok(value) 和 Err(error) 两个单载荷变体")
            okt = ok_fields[0][1]
            if okt[0] != "named" or not (
                    okt[1] in ("int", "i64", "i32", "i16", "i8",
                               "u64", "u32", "u16", "u8", "bool", "str")
                    or okt[1] in self.structs or okt[1] in self.enums):
                # v1.38：Ok 载荷放宽到具名 struct/enum——C 联合体成员访问
                # （{tmp}.u.Ok.value）对 struct 值天然成立，无需特判
                raise SyntaxError("? 的 Ok 载荷暂只支持整数/bool/str 标量与具名 struct/enum")
            if getattr(self, "current_ret_t", None) is None or self.ctype(self.current_ret_t) != ename:
                raise SyntaxError("? 所在函数必须返回相同的结果枚举")
            self.tmp_id += 1
            tmp = f"_try{self.tmp_id}"
            payload = ok_fields[0][0]
            ptype = self.env_type(ok_fields[0][1])
            return (f"({{ {ename} {tmp} = {code}; "
                    f"if ({tmp}.__tag != {ok_index}) return {tmp}; "
                    f"({tmp}.u.Ok.{payload}); }})", ptype)
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
        if k in ("enumlit", "enumlit_pos"):
            return self.gen_enumlit(e, env)
        if k == "match":
            inner, res_var, res_type = self.gen_match(e, env, 1, None, as_expr=True)
            code = "({\n" + "\n".join(inner) + f"\n    {res_var};\n}})"
            return code, res_type
        raise SyntaxError(f"无法生成表达式: {e!r}")

    def gen_enumlit(self, e, env):
        """枚举构造 -> C 复合字面量 { .__tag = i, .u.Variant = { .f = ... } }。
        ("enumlit_pos", path, [expr])：位置实参（v1.44 限定枚举构造），
        字段名按 merged 变体表下标映射。"""
        path, fields = e[1], e[2]
        ename, vname = path[0], path[1]
        if ename not in self.enums:
            raise SyntaxError(f"未声明的枚举 {ename}")
        vidx, vfields = self.enum_variant(ename, vname)
        parts = [f".__tag = {vidx}"]
        if vfields:
            if e[0] == "enumlit_pos":
                if len(fields) != len(vfields):
                    raise SyntaxError(
                        f"{ename}.{vname} 构造需 {len(vfields)} 个载荷字段，得到 {len(fields)}")
                exprs = {vf[0]: fields[i] for i, vf in enumerate(vfields)}
            else:
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
        scode, stype = self.gen_expr(scrut, env)
        sname = Infer.struct_of(stype)
        arms = resolve_option_patterns(arms, sname)
        ename, plain, _wild = validate_match(arms, self.enums)
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
        """作用域里记录的类型标记：结构体 'struct:Name'、枚举 'enum:Name'、
        切片 'slice:<elem>'、map 'map:<k>:<v>'，其余用 C 类型串"""
        if t[0] == "chan":
            return "int64_t"
        if t[0] == "map":
            return map_env_of_type(t)
        if t[0] == "slice":
            return "slice:" + slice_elem_tag(t[1])
        if t[0] == "vec":
            return "vec:" + _vec_tag_str(t[1])
        if t[0] == "named" and t[1] in self.structs:
            return "struct:" + t[1]
        if t[0] == "named" and t[1] in self.enums:
            return "enum:" + t[1]
        return self.ctype(t)

    def _is_chan_expr(self, obj, env):
        """对象表达式是否是 chan：变量跟踪（__chan__ 前缀）或结构体字段的
        静态类型是 chan（v1.39：b.ch.send(...)）。C 类型串里 chan 坍缩成
        int64_t，只能回到 structs 表查字段类型（字段链递归）。
        注意 `b.ch` 在 AST 里是 ("path", ["b","ch"]) 不是 field——先把
        头段是变量的 path 归一化成字段链（与 gen_expr 的 path 处理一致）。"""
        if obj[0] == "path" and len(obj) > 1 and obj[1] and obj[1][0] in env:
            o = ("name", obj[1][0])
            for seg in obj[1][1:]:
                o = ("field", o, seg)
            obj = o
        if obj[0] == "name" and env.get("__chan__" + obj[1]):
            return True
        if obj[0] == "field":
            st = self.infer.struct_of(self.infer.expr(obj[1], env))
            if st:
                for fn_, ft in self.structs.get(st, []):
                    if fn_ == obj[2]:
                        return isinstance(ft, tuple) and ft[0] == "chan"
        return False

    def gen_map_method(self, m, ocode, mp, args, env):
        """m.set/get/has/del -> C 运行时调用（开放寻址表）。
        键相等/哈希在运行时按句柄 ktag 分派：str 按内容，int/bool 按值。
        值扩容（v1.41）：聚合值走 qlm_map_set_n/get_n（按值拷入/拷出），
        模式与 vec[Struct] 的 push/get 相同（语句表达式物化 _vt）。"""
        kv, vv = mp
        agg_v = vv not in MAP_KV_SCALARS

        def key_arg(a):
            kcode, ktype = self.gen_expr(a, env)
            self.check_map_arg("键", kv, ktype)
            return kcode

        if m == "set":
            if len(args) != 2:
                raise SyntaxError("m.set(k, v) 需要两个实参")
            kcode = key_arg(args[0])
            vcode, vtype = self.gen_expr(args[1], env)
            self.check_map_arg("值", vv, vtype)
            if agg_v:
                return (f"({{ {vv} _vt = {vcode}; "
                        f"qlm_map_set_n({ocode}, {kcode}, (const void *)&_vt); "
                        f"(int64_t)0; }})", "int64_t")
            return f"qlm_map_set({ocode}, {kcode}, {vcode})", "int64_t"
        if m == "get":
            if len(args) != 1:
                raise SyntaxError("m.get(k) 需要且只需要一个实参")
            kcode = key_arg(args[0])
            if agg_v:
                tn = ("struct:" if vv in self.structs else "enum:") + vv
                return (f"({{ {vv} _vt; "
                        f"qlm_map_get_n({ocode}, {kcode}, (void *)&_vt); _vt; }})", tn)
            code = f"qlm_map_get({ocode}, {kcode})"
            if vv == "str":
                return f"((const char *)(intptr_t)({code}))", "const char *"
            return code, "int64_t"
        if m == "has":
            if len(args) != 1:
                raise SyntaxError("m.has(k) 需要且只需要一个实参")
            kcode = key_arg(args[0])
            return f"qlm_map_has({ocode}, {kcode})", "bool"
        if m == "del":
            if len(args) != 1:
                raise SyntaxError("m.del(k) 需要且只需要一个实参")
            kcode = key_arg(args[0])
            return f"qlm_map_del({ocode}, {kcode})", "int64_t"
        raise SyntaxError(f"map 未知方法 .{m}（支持 set/get/has/del）")

    @staticmethod
    def check_map_arg(which, want, got):
        """map 键/值实参类型校验：str 走内容语义，类型不匹配必须报错（不许静默错编）；
        聚合值要求 struct:Name / enum:Name 精确同名（v1.41）"""
        if want == "str":
            if got != "const char *":
                raise SyntaxError(f"map {which}类型是 str，实参类型不匹配（得到 {got}）")
        elif want not in MAP_KV_SCALARS:
            if got in ("struct:" + want, "enum:" + want):
                return
            raise SyntaxError(f"map 值类型是 {want}，实参类型不匹配（得到 {got}）")
        elif got == "const char *":
            raise SyntaxError(f"map {which}类型是 {want}，不能用 str 实参")

    def gen_serve(self, obj, env):
        """server.serve() -> qlm_echo_serve(...)"""
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
        return (f"qlm_echo_serve({addr}, {oc}, {od}, {ocl}, "
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
            if lit[0] == "arraylit":
                # 定长数组字面量：int64_t a[N] = { ... };
                n = len(lit[1])
                codes = []
                elem = None
                for el in lit[1]:
                    c, et = self.gen_expr(el, env)
                    if et in ("const char *", "void", "QlmBuf") or (
                            isinstance(et, str) and (et.startswith("struct:") or
                                                     et.startswith("enum:") or
                                                     is_arr_env(et) or is_slice_env(et))):
                        raise SyntaxError("数组字面量暂只支持数值元素")
                    if elem is None:
                        elem = C_TO_ELEM.get(et, "int")
                    codes.append(c)
                env[s[2]] = arr_env(elem or "int", n)
                return f"{pad}int64_t {s[2]}[{n}] = {{ {', '.join(codes)} }};"
            code, t = self.gen_expr(lit, env)
            if is_arr_env(t):
                # 定长数组值语义拷贝
                elem, n = arr_env_parts(t)
                if lit[0] != "name":
                    raise SyntaxError("数组只能从另一个数组变量拷贝")
                env[s[2]] = t
                return (f"{pad}int64_t {s[2]}[{n}]; "
                        f"memcpy({s[2]}, {code}, sizeof({s[2]}));")
            if is_slice_env(t):
                # 切片：{ptr, len} 两字拷贝（零拷贝视图，共享底层存储）
                env[s[2]] = t
                return f"{pad}{slice_cname(slice_env_elem(t))} {s[2]} = {code};"
            if is_map_env(t):
                # map 句柄：int64_t（指向运行时开放寻址表）
                env[s[2]] = t
                return f"{pad}int64_t {s[2]} = {code};"
            if is_vec_env(t):
                # vec 句柄：QlmVec*（初始化表达式是整数句柄，强转即可）
                env[s[2]] = t
                return f"{pad}QlmVec *{s[2]} = (QlmVec *)(intptr_t)({code});"
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
            atype = str(env.get(s[1], ""))
            if is_arr_env(atype):
                n = arr_env_parts(atype)[1]
                if s[2] != "=":
                    raise SyntaxError("数组只支持 = 整体赋值")
                if s[3][0] != "name":
                    raise SyntaxError("数组只能从另一个数组变量赋值")
                code, rt = self.gen_expr(s[3], env)
                if rt != atype:
                    raise SyntaxError("数组赋值两侧长度不一致")
                return f"{pad}memcpy({s[1]}, {code}, sizeof({s[1]}));"
            if is_slice_env(atype):
                if s[2] != "=":
                    raise SyntaxError("切片只支持 = 整体赋值")
                code, rt = self.gen_expr(s[3], env)
                if rt != atype:
                    raise SyntaxError("切片赋值两侧元素类型不一致")
                return f"{pad}{s[1]} = {code};"
            code, t = self.gen_expr(s[3], env)
            return f"{pad}{s[1]} {s[2]} {code};"
        if k == "assign_index":
            base, idxe, op, rhs = s[1], s[2], s[3], s[4]
            bcode, btype = self.gen_expr(base, env)
            if is_slice_env(btype):
                elem = slice_env_elem(btype)
                pfield, cast, _ = slice_access(elem)
                icode, _ = self.gen_expr(idxe, env)
                rcode, _ = self.gen_expr(rhs, env)
                if not self.bounds:
                    return f"{pad}(({cast})({bcode}).{pfield})[({icode})] {op} {rcode};"
                self.tmp_id += 1
                tmp = f"_bi{self.tmp_id}"
                return "\n".join([
                    f"{pad}{{",
                    f"{pad}    int64_t {tmp} = (int64_t)({icode});",
                    f"{pad}    qlm_slice_bounds({tmp}, ({bcode}).len);",
                    f"{pad}    (({cast})({bcode}).{pfield})[{tmp}] {op} {rcode};",
                    f"{pad}}}",
                ])
            if not is_arr_env(btype):
                raise SyntaxError("下标赋值只能用于定长数组或切片")
            n = arr_env_parts(btype)[1]
            icode, _ = self.gen_expr(idxe, env)
            rcode, _ = self.gen_expr(rhs, env)
            if not self.bounds:
                return f"{pad}({bcode})[({icode})] {op} {rcode};"
            self.tmp_id += 1
            tmp = f"_bi{self.tmp_id}"
            return "\n".join([
                f"{pad}{{",
                f"{pad}    int64_t {tmp} = (int64_t)({icode});",
                f"{pad}    qlm_bounds({tmp}, {n});",
                f"{pad}    ({bcode})[{tmp}] {op} {rcode};",
                f"{pad}}}"])
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
        if k == "foreach":
            var, coll_e, body = s[1], s[2], s[3]
            ccode, ctype = self.gen_expr(coll_e, env)
            e2 = dict(env)
            e2[var] = "int64_t"
            if is_vec_env(ctype):
                elem = vec_env_elem(ctype)
                if elem == "str":
                    e2[var] = "const char *"
                if elem.startswith("mapinner:"):
                    # vec[map]（v1.37）：循环变量是 map 句柄，重挂 map 类型
                    e2[var] = "map:" + elem[len("mapinner:"):]
                if elem.startswith("vecinner:"):
                    # vec[vec[T]]（v1.37 补漏）：循环变量是内层 vec 句柄
                    e2[var] = "vec:" + elem[len("vecinner:"):]
                if elem.startswith("agg:"):
                    # 聚合元素：每轮把元素 memcpy 进一个局部变量
                    tn = elem[4:]
                    e2[var] = "struct:" + tn
                    return "\n".join([
                        f"{pad}{{",
                        f"{pad}    QlmVec *_v = (QlmVec *)(intptr_t)({ccode});",
                        f"{pad}    for (int64_t _i = 0; _i < _v->len; _i++) {{",
                        f"{pad}        {tn} {var};",
                        f"{pad}        qlm_vec_get_n(_v, _i, (void *)&{var});",
                        self.gen_block(body, e2, ind + 2, ret_t),
                        f"{pad}    }}",
                        f"{pad}}}"])
                if elem == "str":
                    # 字符串元素：循环变量直接是 const char*
                    out = [f"{pad}{{",
                           f"{pad}    QlmVec *_v = (QlmVec *)(intptr_t)({ccode});",
                           f"{pad}    for (int64_t _i = 0; _i < _v->len; _i++) {{",
                           f"{pad}        const char *{var} = (const char *)(intptr_t)_v->data[_i];",
                           self.gen_block(body, e2, ind + 2, ret_t),
                           f"{pad}    }}",
                           f"{pad}}}"]
                    return "\n".join(out)
                out = [f"{pad}{{",
                       f"{pad}    QlmVec *_v = (QlmVec *)(intptr_t)({ccode});",
                       f"{pad}    for (int64_t _i = 0; _i < _v->len; _i++) {{",
                       f"{pad}        int64_t {var} = _v->data[_i];",
                       self.gen_block(body, e2, ind + 2, ret_t),
                       f"{pad}    }}",
                       f"{pad}}}"]
                return "\n".join(out)
            if is_map_env(ctype):
                ktag = map_env_parts(ctype)[0]
                if ktag == "str":
                    e2[var] = "const char *"
                out = [f"{pad}{{",
                       f"{pad}    int64_t _h = (int64_t)({ccode});",
                       f"{pad}    int64_t _c = qlm_map_cap(_h);",
                       f"{pad}    for (int64_t _i = 0; _i < _c; _i++) {{",
                       f"{pad}        if (qlm_map_state(_h, _i) != 1) continue;"]
                if ktag == "str":
                    out.append(f"{pad}        const char *{var} = "
                               f"(const char *)(intptr_t)qlm_map_key_at(_h, _i);")
                else:
                    out.append(f"{pad}        int64_t {var} = qlm_map_key_at(_h, _i);")
                out += [self.gen_block(body, e2, ind + 2, ret_t),
                        f"{pad}    }}",
                        f"{pad}}}"]
                return "\n".join(out)
            raise SyntaxError("for x in ... 只支持 map 与 vec")
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
        if s[0] == "defer":
            # C 后端没有 defer 语句（C99 无 RAII）；要支持得给每个退出点
            # 复制清理代码 + goto 标签，收益不抵风险。fail-fast 明确拒绝，
            # 不静默丢清理——defer 类测试只进 PE / A64 原生后端回归。
            raise SyntaxError(
                "C 后端不支持 defer（v1.48 边界：defer 只进原生后端，"
                "C 交叉验证不含 defer 测试）")
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
            # ---- 单核降级：确定性串行（Quelmara.toml [core] multicore = false）----
            e2 = dict(env)
            e2[var] = "int64_t"
            out = [f"{pad}/* parfor -> 串行降级（Quelmara.toml: multicore=false, threads={self.threads}） */"]
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
        callee = self.cfn(name)                # v2.91：用户函数带 `u_` 前缀
        if ret == ("named", "void"):
            body = f"    {callee}({names});\n    a->res = 0;"
        else:
            body = f"    a->res = (int64_t)({callee}({names}));"
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
              "#if QLM_MULTICORE",
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
        lines = ["/* Generated by Quelmara transpiler v0.1 */",
                 "#define _GNU_SOURCE",
                 f"#define QLM_THREADS {self.threads}",
                 f"#define QLM_MULTICORE {1 if self.multicore else 0}",
                 f"#define QLM_NET_MAX_CONNS {int(self.cfg['net']['max_conns'])}",
                 f"#define QLM_RECV_BUF {int(self.cfg['net']['recv_buffer'])}",
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

        # @extern("C") / @ffi 原型（非 static，链接期解析；v0.11 / v1.87）
        # @ffi 在 C 后端退化成普通 extern 原型：DLL 名对 C 链接器没有意义，
        # 由用户自己 -l 对应库（PE 导入表那条路只在自研后端成立）。
        for f in fns:
            if not (f.get("extern") or f.get("ffi")):
                continue
            params = ", ".join(f"{self.ctype(t)} {n}" for n, t in f["params"]) or "void"
            lines.append(f"extern {self.ctype(f['ret'])} {f['name']}({params});")
        if any(f.get("extern") or f.get("ffi") for f in fns):
            lines.append("")

        # 前向声明
        for f in fns:
            if f.get("extern") or f.get("ffi"):
                continue
            params = ", ".join(f"{self.ctype(t)} {n}" for n, t in f["params"]) or "void"
            lines.append(f"static {self.ctype(f['ret'])} {self.cfn(f['name'])}({params});")
        lines.append("")

        bodies = []
        for f in fns:
            if f.get("extern") or f.get("ffi"):
                continue
            self.current_ret_t = f["ret"]
            env = {n: self.env_type(t) for n, t in f["params"]}
            for n, t in f["params"]:
                if t[0] == "chan":
                    env["__chan__" + n] = True
            body = self.gen_block(f["body"], env, 1, f["ret"])
            params = ", ".join(f"{self.ctype(t)} {n}" for n, t in f["params"]) or "void"
            bodies.append(
                f"static {self.ctype(f['ret'])} {self.cfn(f['name'])}({params}) {{\n{body}\n}}")

        if self.helpers:
            lines.append("\n".join(self.helpers))
            lines.append("")
        lines += bodies
        has_main = any(f["name"] == "qlm_main" for f in fns)
        lines += ["int main(int argc, char **argv) {",
                  "    qlm_set_args(argc, argv);" if self.uses_args else "",
                  "    qlm_main();" if has_main else "    /* no main */",
                  "    return 0;", "}"]
        return "\n".join(lines)

    def any_net_usage(self):
        for f in self.fns:
            if f.get("extern") or f["body"] is None:
                continue
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
    elif k == "select":
        for arm in e[1]:
            walk_expr(arm, declared, assigned, referenced)
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
    elif k == "mapnew":
        for a in e[2]:
            walk_expr(a, declared, assigned, referenced)
    elif k == "structlit":
        referenced.update(e[1])
        for v in e[2].values():
            walk_expr(v, declared, assigned, referenced)
    elif k == "enumlit":
        for _n, v in e[2]:
            walk_expr(v, declared, assigned, referenced)
    elif k == "enumlit_pos":
        for v in e[2]:
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
    elif k == "index":
        walk_expr(e[1], declared, assigned, referenced)
        walk_expr(e[2], declared, assigned, referenced)
    elif k == "arraylit":
        for el in e[1]:
            walk_expr(el, declared, assigned, referenced)


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
        elif k == "assign_index":
            walk_expr(s[1], declared, assigned, referenced)
            walk_expr(s[2], declared, assigned, referenced)
            walk_expr(s[4], declared, assigned, referenced)
            head = lvalue_head(s[1])
            if head:
                assigned.add(head)
                referenced.add(head)
        elif k in ("break", "continue"):
            pass
        elif k == "defer":
            # defer <表达式/赋值>：内部语句照常计入引用/赋值，
            # 否则"只在 defer 里用到"的变量会被 DCE 当成未使用。
            walk_stmts([s[1]], declared, assigned, referenced)
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
    require_source(src_path)
    cfg = load_config(src_path)
    mod, imports, fns_ast, tests, structs, enums, decl_order = load_program(src_path, cfg)
    PROGRAM = (mod, imports, fns_ast, tests)
    fns_ast = with_test_runner(fns_ast, tests)
    # v1.93：Drop 是作用域退出时的**隐式**调用，C99 没有析构语义。静默不跑
    # 清理就是语义分叉（资源泄漏/句柄不关），所以 fail-fast 拒绝——与 defer
    # 同一口径：析构类测试只进 PE / A64 原生后端回归。
    for f in fns_ast:
        if f.get("impl_iface") == "Drop":
            raise SyntaxError(
                f"C 后端不支持 Drop（v1.93 边界：{f.get('self_type')}.drop 是"
                "作用域退出时的隐式调用，C99 无析构语义；析构只进原生后端）")
    fns_ast = global_dce(fns_ast)          # 全局 DCE（v1.17d）
    # 用户 main 与 C main 区分：编译为 qlm_main
    for f in fns_ast:
        if f["name"] == "main":
            f["name"] = "qlm_main"
    cg = Codegen(fns_ast, cfg, structs, enums, decl_order)
    c_code = cg.gen_program()
    return c_code, cfg


def main():
    ap = argparse.ArgumentParser(description="Quelmara transpiler (Quelmara -> C99)")
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
    print(f"[qlm] {args.src} -> {out_c}")
    print(f"[qlm] config: {cfg['_path'] or '(默认)'} | "
          f"multicore={cfg['core']['multicore']} threads={cfg['core']['threads'] or 'auto'}")

    if args.cmd == "build" and not args.cc:
        return

    bin_path = os.path.join("build", base)
    cc_cmd = ["cc", "-std=gnu11", "-O2", "-pthread", "-o", bin_path, out_c]
    print("[qlm] cc:", " ".join(cc_cmd))
    subprocess.check_call(cc_cmd)
    if args.cmd == "run":
        print(f"[qlm] exec {bin_path}")
        subprocess.check_call([os.path.abspath(bin_path)] + args.args)


if __name__ == "__main__":
    main()
