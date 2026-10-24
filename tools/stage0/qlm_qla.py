#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara 目标文件格式 `.qla`（v2.03）
====================================
一个 `.qla` 是**一个编译单元的降级产物**：QuIR（已优化）+ 全局数据区 +
符号表 + 类型表。它不含机器码，也不含源码，所以：

  * **函数级增量**：重编时按函数比对 AST 哈希，只重降级变了的函数，
    其余函数直接复用 `.qla` 里的 IR（见 `qlm_native.Lower.run(reuse=…)`）。
  * **分发二进制库**：`build --lib` 产出的 `.qla` 可以脱离源码分发；
    使用方用 `--lib-input` 把它的符号表注入编译期（只拿签名，不拿实现），
    链接期 `link` 把两边的 IR 合并成一份可执行文件。

容器格式（确定性——同源码同编译器 ⇒ 同字节，sha256 即身份）
-------------------------------------------------------------
    b"QLA1\\n"                    魔数 + 版本
    <header json>\\n              单行 ASCII（sort_keys，无时间戳、无绝对路径）
    <payload>                     meta 段 + globals 段，偏移/长度/摘要都在 header

`header` 字段：format / unit / kind(program|lib) / arch / platform / opt /
compiler（编译器指纹）/ payload_sha256 / sections[{name,off,len,sha256}]。

`meta` 段（JSON）：
    funcs      [{name, hash, needs, ir, nv, frame_words, structv, no_inline,
                 iface_fresh, iface_own, closig, win_thread, label_id}]（按降级顺序）
    global_len [每个全局块的字节数]
    vtables    [[接口名, 类型名, [方法函数名…]]]
    special    {argc/argv/static/…: gid}（进程级单例全局字，链接期要共享）
    counters   {lam_seq, spawn_id}
    exports    [{name, params, ret, pub, impl_iface, self_type, impl_method}]
    decls      {structs, enums, ifaces}（类型表，使用方要按同一布局编译）
    undefined  [本单元引用但未定义的符号]（链接期必须被别人补上）
    stats      {nfuncs, ninstrs, nglobals}

设计口径（别推翻）
------------------
1. **IR 里的 gid 是单元内的**（`("ga", n)`），链接期按单元基址重编号；
   函数引用一律是**名字**（`call` / `fnaddr` / vtable 槽），所以链接是
   名字解析，不需要重定位表。
2. **进程级单例全局字要共享**：`argc/argv/static_word/args_copied` 这些在
   每个单元里各有一份，链接时统一指向第一个单元那份——否则 `args()`
   读到的是没被入口写过的零。
3. **同名函数去重按"忽略 gid 的结构签名"**：运行库 helper（`__alloc` 等）
   每个单元都有一份，逻辑相同但 gid 不同；签名一致就只留一份（于是全进程
   一个堆、一份空闲链），不一致就报符号冲突而不是随便挑一个。
"""

import base64
import hashlib
import json
import os
import struct
import sys

MAGIC = b"QLA1\n"
FORMAT = 1
SRC_EXT = ".qma"
ARC_EXT = ".qla"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def compiler_fingerprint():
    """编译器指纹：`tools/stage0/*.py` 全内容哈希（与 qlm_cache 同一口径）。

    档案跨编译器复用是**不可接受**的（IR 指令集/ABI 会变），所以链接期
    强制所有输入档案指纹一致，不一致就报错而不是给出错位的机器码。
    """
    try:
        import qlm_cache
        return qlm_cache.compiler_fingerprint()
    except Exception:                       # noqa: BLE001
        d = os.path.dirname(os.path.abspath(__file__))
        h = hashlib.sha256()
        for name in sorted(os.listdir(d)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(d, name), "rb") as f:
                h.update(name.encode("utf-8") + b"\x00" + f.read() + b"\n")
        return h.hexdigest()[:32]


def _canon_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def ir_to_json(ir):
    """IR 元组 -> JSON 数组（递归；不认识的类型直接报错，别静默丢数据）。"""
    out = []
    for ins in ir:
        out.append(_t2l(ins))
    return out


def _t2l(x):
    if isinstance(x, tuple):
        return [_t2l(v) for v in x]
    if isinstance(x, list):
        return [_t2l(v) for v in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if isinstance(x, bytes):
        return {"__b64__": base64.b64encode(x).decode("ascii")}
    raise TypeError(f"IR 里出现不可序列化的值：{type(x).__name__} {x!r}")


def json_to_ir(rows):
    """JSON 数组 -> IR 元组（与 ir_to_json 严格互逆）。"""
    return [tuple(_l2t(r)) for r in rows]


def _l2t(x):
    if isinstance(x, list):
        return tuple(_l2t(v) for v in x)
    if isinstance(x, dict) and "__b64__" in x:
        return base64.b64decode(x["__b64__"])
    return x


def deep_tuple(x):
    """JSON 读回来的 list 一律还原成 tuple。

    编译器内部到处用**元组**比较类型（`t == ("named", "str")`），list 与
    tuple 不相等——二进制库注入的签名/类型表必须还原成元组，否则会静默
    走错分支（实测：`print(greet("qla"))` 把 str 返回值当 int 打印）。
    """
    return _l2t(x)


def norm_params(params):
    """形参表：外层保持 list（编译器原生形状），内层类型还原成元组。"""
    return [(n, _l2t(t)) for n, t in params]


def norm_decl(kind, table):
    """类型表：外层保持 dict/list（原生形状），类型元组还原。"""
    if kind == "structs":
        return {k: [(n, _l2t(t)) for n, t in fields]
                for k, fields in table.items()}
    if kind == "enums":
        return {k: [(vn, [(n, _l2t(t)) for n, t in fs]) for vn, fs in variants]
                for k, variants in table.items()}
    return table


def _walk_ir(ir, visit):
    """对每条指令的每个位置调用 visit(容器, 下标, 值)，允许就地改写。"""
    for ins in ir:
        if not isinstance(ins, tuple):
            continue
        for i, v in enumerate(ins):
            visit(ins, i, v)


def _remap_ga(ir, mapping):
    """把 `("ga", gid)` 操作数按 mapping 重编号（只动 ga，绝不动 vreg 整数）。"""
    if not mapping:
        return ir
    out = []
    for ins in ir:
        out.append(_remap_ins(ins, mapping))
    return out


def _remap_ins(ins, mapping):
    if not isinstance(ins, tuple):
        return ins
    if len(ins) == 2 and ins[0] == "ga" and isinstance(ins[1], int):
        return ("ga", mapping.get(ins[1], ins[1]))
    # movaddr 的 gid 是**裸整数**（不是 ("ga", gid) 元组）——链接期漏了它，
    # 跨库的字符串字面量就会指到别人的数据区（实测：`"hello, " + who` 打出
    # `qlaqla`，因为两个档案的 gid 4 分别是两个不同的字面量）。
    if ins and ins[0] == "movaddr" and len(ins) == 3 \
            and isinstance(ins[2], int):
        return ("movaddr", ins[1], mapping.get(ins[2], ins[2]))
    return tuple(_remap_ins(v, mapping) if isinstance(v, tuple) else v
                 for v in ins)


def ir_signature(ir):
    """忽略 gid 的结构签名：`("ga", n)` 换成"第 k 个出现的全局块"。

    用来判断两个同名函数（运行库 helper）是不是"同一份逻辑"——
    它们各自 intern 的全局块位置不同，但引用模式相同。
    """
    seen, rows = {}, []
    for ins in ir:
        rows.append(_sig_ins(ins, seen))
    return _sha(_canon_json(rows).encode("utf-8"))


def _sig_ins(ins, seen):
    if not isinstance(ins, tuple):
        return ins
    if len(ins) == 2 and ins[0] == "ga" and isinstance(ins[1], int):
        k = seen.setdefault(ins[1], len(seen))
        return ["ga", "#%d" % k]
    if ins and ins[0] == "movaddr" and len(ins) == 3 \
            and isinstance(ins[2], int):
        k = seen.setdefault(ins[2], len(seen))
        return ["movaddr", _sig_ins(ins[1], seen), "#%d" % k]
    return [_sig_ins(v, seen) if isinstance(v, tuple) else v for v in ins]


def symbol_refs(ir):
    """IR 里引用到的符号名：`call` 目标 + `fnaddr` 代码地址（递归进操作数）。"""
    out = set()
    for ins in ir:
        _refs_in(ins, out)
    return out


def _refs_in(x, out):
    if not isinstance(x, tuple) or not x:
        return
    if x[0] == "call" and len(x) > 2 and isinstance(x[2], str):
        out.add(x[2])
    if x[0] == "fnaddr" and len(x) > 1 and isinstance(x[1], str):
        out.add(x[1])
    for v in x[1:]:
        if isinstance(v, tuple):
            _refs_in(v, out)


# ---------------------------------------------------------------------------
# 函数记录
# ---------------------------------------------------------------------------

_FN_FIELDS = ("nv", "frame_words", "label_id")


def fn_record(fn, fhash, needs, owner=None):
    """Fn -> 可序列化记录。只存 Codegen 真正会读的字段。

    owner：合成函数（lambda 体 / parfor worker）属于哪个源码函数。增量复用
    时"父函数重编则子作废"——否则新旧两份 `__lam_N` 同名，链接期直接撞。
    """
    return {
        "name": fn.name,
        "owner": owner,
        "hash": fhash,
        "needs": sorted(needs or ()),
        "ir": ir_to_json(fn.instrs),
        "nv": fn.nv,
        "frame_words": getattr(fn, "frame_words", 0),
        "label_id": getattr(fn, "label_id", 0),
        "structv": {str(k): v for k, v in getattr(fn, "structv", {}).items()},
        "no_inline": bool(getattr(fn, "no_inline", False)),
        "iface_fresh": sorted(getattr(fn, "iface_fresh", ())),
        "iface_own": sorted(getattr(fn, "iface_own", ())),
        "closig": {str(k): [list(p), list(r)]
                   for k, (p, r) in (getattr(fn, "closig", {}) or {}).items()},
        "win_thread": bool(getattr(fn, "win_thread", False)),
        "dbg_file": getattr(fn, "dbg_file", None),
        # 这个函数里被**内联进来**的 callee 名：内联让调用方依赖被调方的
        # 函数体，增量时必须顺着这张表传播失效（见 qlm_native 的复用判定）
        "inl": sorted(getattr(fn, "inlined_from", ()) or ()),
    }


def record_to_fn(rec):
    """记录 -> Fn（延迟导入 qlm_native，避免循环依赖）。"""
    from qlm_native import Fn
    fn = Fn(rec["name"])
    fn.instrs = json_to_ir(rec["ir"])
    fn.nv = rec.get("nv", 0)
    fn.frame_words = rec.get("frame_words", 0)
    fn.label_id = rec.get("label_id", 0)
    fn.structv = {int(k): v for k, v in (rec.get("structv") or {}).items()}
    fn.no_inline = bool(rec.get("no_inline"))
    fn.iface_fresh = set(rec.get("iface_fresh") or ())
    fn.iface_own = set(rec.get("iface_own") or ())
    fn.closig = {int(k): (tuple(p), tuple(r))
                 for k, (p, r) in (rec.get("closig") or {}).items()}
    fn.win_thread = bool(rec.get("win_thread"))
    fn.inlined_from = set(rec.get("inl") or ())
    if rec.get("dbg_file"):
        fn.dbg_file = rec["dbg_file"]
    return fn


# ---------------------------------------------------------------------------
# 档案
# ---------------------------------------------------------------------------

class Archive:
    """一个 `.qla` 的内存形态。字段见模块头。"""

    def __init__(self, unit="", kind="program", arch="x86_64",
                 platform="windows", opt=True, compiler=None, cfg=""):
        self.unit = unit
        self.kind = kind
        self.arch = arch
        self.platform = platform
        self.opt = bool(opt)
        self.compiler = compiler or compiler_fingerprint()
        self.cfg = cfg            # 构建配置摘要（Quelmara.toml 变了不能复用）
        self.funcs = []          # fn_record 列表（降级顺序）
        self.globals = []        # [bytes]
        self.vtables = []        # [[iface, type, [fns]]]
        self.special = {}        # name -> gid
        self.counters = {"lam_seq": 0, "spawn_id": 0}
        self.exports = []        # 符号表（pub 声明）
        self.decls = {"structs": {}, "enums": {}, "ifaces": {}}
        self.undefined = []
        self.uses_args = False
        self.strmap = {}         # 字符串字面量 -> gid（增量复用时要接回来）

    # ---- 查询 ----
    @property
    def defined(self):
        return {r["name"] for r in self.funcs}

    def ninstrs(self):
        return sum(len(r["ir"]) for r in self.funcs)

    def stats(self):
        return {
            "unit": self.unit, "kind": self.kind, "arch": self.arch,
            "platform": self.platform, "opt": self.opt,
            "compiler": self.compiler, "cfg": self.cfg,
            "funcs": len(self.funcs),
            "instrs": self.ninstrs(), "globals": len(self.globals),
            "gbytes": sum(len(g) for g in self.globals),
            "exports": len(self.exports), "undefined": len(self.undefined),
            "vtables": len(self.vtables),
        }

    # ---- 序列化 ----
    def meta_obj(self):
        return {
            "funcs": self.funcs,
            "global_len": [len(g) for g in self.globals],
            "vtables": self.vtables,
            "special": self.special,
            "counters": self.counters,
            "exports": self.exports,
            "decls": self.decls,
            "undefined": self.undefined,
            "uses_args": bool(self.uses_args),
            "strmap": self.strmap,
            "stats": self.stats(),
        }

    def to_bytes(self):
        meta = _canon_json(self.meta_obj()).encode("ascii")
        gblob = b"".join(self.globals)
        sections = [("meta", meta), ("globals", gblob)]
        off, desc = 0, []
        for name, blob in sections:
            desc.append({"name": name, "off": off, "len": len(blob),
                         "sha256": _sha(blob)})
            off += len(blob)
        payload = meta + gblob
        header = {
            "format": FORMAT,
            "unit": self.unit,
            "kind": self.kind,
            "arch": self.arch,
            "platform": self.platform,
            "opt": self.opt,
            "compiler": self.compiler,
            "cfg": self.cfg,
            "payload_sha256": _sha(payload),
            "sections": desc,
        }
        return MAGIC + _canon_json(header).encode("ascii") + b"\n" + payload

    def save(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        blob = self.to_bytes()
        with open(path, "wb") as f:
            f.write(blob)
        return len(blob), _sha(blob)

    @classmethod
    def from_bytes(cls, blob, path="<bytes>"):
        if not blob.startswith(MAGIC):
            raise ValueError(f"{path}: 不是 .qla 档案（魔数不符）")
        nl = blob.find(b"\n", len(MAGIC))
        if nl < 0:
            raise ValueError(f"{path}: 档案头不完整（截断？）")
        try:
            header = json.loads(blob[len(MAGIC):nl].decode("ascii"))
        except Exception as exc:                  # noqa: BLE001
            raise ValueError(f"{path}: 档案头损坏（{exc}）")
        if header.get("format") != FORMAT:
            raise ValueError(
                f"{path}: 档案格式版本 {header.get('format')} 与本编译器 "
                f"{FORMAT} 不符——请重新编译该档案")
        payload = blob[nl + 1:]
        if len(payload) != sum(s["len"] for s in header["sections"]):
            raise ValueError(f"{path}: 档案长度不符（截断或拼接损坏）")
        if _sha(payload) != header["payload_sha256"]:
            raise ValueError(f"{path}: 档案校验和失败（内容损坏）")
        sec = {}
        for s in header["sections"]:
            chunk = payload[s["off"]:s["off"] + s["len"]]
            if _sha(chunk) != s["sha256"]:
                raise ValueError(f"{path}: 段 {s['name']} 校验和失败")
            sec[s["name"]] = chunk
        meta = json.loads(sec["meta"].decode("ascii"))
        arc = cls(unit=header["unit"], kind=header["kind"],
                  arch=header["arch"], platform=header["platform"],
                  opt=header["opt"], compiler=header["compiler"],
                  cfg=header.get("cfg", ""))
        arc.funcs = meta["funcs"]
        lens = meta["global_len"]
        g, pos = [], 0
        for n in lens:
            g.append(sec["globals"][pos:pos + n])
            pos += n
        arc.globals = g
        arc.vtables = meta["vtables"]
        arc.special = meta["special"]
        arc.counters = meta["counters"]
        arc.exports = meta["exports"]
        arc.decls = meta["decls"]
        arc.undefined = meta["undefined"]
        arc.uses_args = bool(meta.get("uses_args"))
        arc.strmap = meta.get("strmap") or {}
        return arc

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls.from_bytes(f.read(), path)


# ---------------------------------------------------------------------------
# 链接：多份档案 -> 一份程序
# ---------------------------------------------------------------------------

class LinkError(Exception):
    pass


class Linked:
    """链接结果：可直接交给 Codegen 的形态。"""

    def __init__(self):
        self.funcs = []           # [Fn]
        self.globals = []         # [bytes]
        self.vtables = {}         # (iface, type) -> [fn names]
        self.uses_args = False
        self.undefined = []
        self.reused = 0
        self.origin = {}          # fn name -> unit

    def low(self):
        """Codegen 需要的 `low` 面（只读：globals / vtables / uses_args）。"""
        return _MergedLow(self.globals, self.vtables, self.uses_args)


class _MergedLow:
    """链接期拼出来的 `Low` 替身：Codegen 只读这几个字段。"""

    def __init__(self, globals_, vtables, uses_args):
        self.globals = globals_
        self.vtables = vtables
        self.uses_args = uses_args
        self.argc_gid = None
        self.argv_gid = None
        self.ffi_decls = {}

    def dbg_struct_layout(self):
        return {}


def _check_compatible(arcs):
    first = arcs[0]
    for a in arcs[1:]:
        for f in ("arch", "platform", "opt", "compiler"):
            if getattr(a, f) != getattr(first, f):
                raise LinkError(
                    f"档案不兼容：{a.unit} 的 {f}={getattr(a, f)!r} 与 "
                    f"{first.unit} 的 {getattr(first, f)!r} 不同"
                    f"（同一产物的所有档案必须同架构/同平台/同优化档/同编译器）")


def merge(arcs, unit=None):
    """把若干档案合并成一份程序（IR 级链接）。

    规则（模块头第 1–3 条）：gid 按基址重编号、进程级单例全局字共享、
    同名函数按"忽略 gid 的结构签名"去重。
    """
    if not arcs:
        raise LinkError("没有输入档案")
    _check_compatible(arcs)
    out = Linked()
    base = 0
    spec0 = dict(arcs[0].special)
    seen_sig = {}                 # name -> (sig, unit)
    for ai, arc in enumerate(arcs):
        # 1) 全局区拼接：gid -> gid + base
        out.globals.extend(arc.globals)
        mapping = {gid: gid + base for gid in range(len(arc.globals))}
        if ai > 0:
            for name, gid in arc.special.items():
                # 进程级单例：指向第一个档案那一份（args/static 必须是同一个）
                if name in spec0:
                    mapping[gid + base] = spec0[name]
        # 2) 函数去重
        for rec in arc.funcs:
            name = rec["name"]
            sig = ir_signature(json_to_ir(rec["ir"]))
            if name in seen_sig:
                prev, punit = seen_sig[name]
                if prev != sig:
                    raise LinkError(
                        f"符号冲突：{name} 在 {punit} 与 {arc.unit} 里都定义了，"
                        f"但实现不同（同名不同体）")
                continue
            seen_sig[name] = (sig, arc.unit)
            fn = record_to_fn(rec)
            fn.instrs = _remap_ga(fn.instrs, mapping)
            out.funcs.append(fn)
            out.origin[name] = arc.unit
        # 3) vtable 合并
        for iname, tname, fnames in arc.vtables:
            key = (iname, tname)
            cur = out.vtables.get(key)
            if cur is None:
                out.vtables[key] = list(fnames)
            elif list(fnames) != cur:
                raise LinkError(
                    f"vtable 冲突：{tname} : {iname} 在多个档案里方法表不同")
        out.uses_args = out.uses_args or arc.uses_args
        base += len(arc.globals)
    # 4) 未定义符号：所有引用 - 所有定义
    #    vtable 标签（`__vt_接口__类型`）不是函数，是 Codegen 在代码段尾部
    #    现发的表——它们由合并后的 vtables 决定，不算未定义。
    defined = {f.name for f in out.funcs}
    vt_labels = {f"__vt_{i}__{t}" for (i, t) in out.vtables}
    for f in out.funcs:
        for ref in symbol_refs(f.instrs):
            if ref in defined or ref in vt_labels:
                continue
            if ref not in out.undefined:
                out.undefined.append(ref)
    for _key, fnames in out.vtables.items():
        for ref in fnames:
            if ref not in defined and ref not in out.undefined:
                out.undefined.append(ref)
    out.undefined.sort()
    return out


def check_resolved(link):
    """链接完整性：`main` 唯一、无未定义符号。"""
    names = [f.name for f in link.funcs]
    if names.count("main") == 0:
        raise LinkError("链接失败：没有任何档案定义 main（入口函数）")
    if names.count("main") > 1:
        raise LinkError("链接失败：多个档案都定义了 main（入口必须唯一）")
    if link.undefined:
        raise LinkError(
            "链接失败：以下符号被引用但没有定义（缺一个 --lib-input？）："
            + "、".join(link.undefined))


# ---------------------------------------------------------------------------
# 从 `lower_and_optimize(meta=…)` 的产物建档案
# ---------------------------------------------------------------------------

def archive_from_meta(meta, unit, kind="program", arch="x86_64",
                      platform="windows", opt=True):
    """`qlm_native._fill_meta` 填的字典 -> Archive。"""
    arc = Archive(unit=unit, kind=kind, arch=arch, platform=platform,
                  opt=opt, cfg=meta.get("cfg", ""))
    arc.funcs = meta["funcs"]
    arc.globals = meta["globals"]
    arc.vtables = meta["vtables"]
    arc.special = meta["special"]
    arc.counters = meta["counters"]
    arc.exports = meta["exports"]
    arc.decls = meta["decls"]
    arc.undefined = meta["undefined"]
    arc.uses_args = bool(meta.get("uses_args"))
    arc.strmap = meta.get("strmap") or {}
    return arc


# ---------------------------------------------------------------------------
# 便利函数（CLI 与测试共用）
# ---------------------------------------------------------------------------

def archive_path_for(out_exe):
    return os.path.splitext(out_exe)[0] + ARC_EXT


def load_all(paths):
    return [Archive.load(p) for p in paths]


def describe(path):
    """一行摘要 + 统计（`quelmara qla --stat`）。"""
    arc = Archive.load(path)
    st = arc.stats()
    lines = [
        f"档案: {path}",
        f"  单元: {st['unit']}  类型: {st['kind']}  "
        f"架构: {st['arch']}/{st['platform']}  优化: {'on' if st['opt'] else 'off'}",
        f"  编译器指纹: {st['compiler']}",
        f"  函数: {st['funcs']} 个 / IR 指令: {st['instrs']} 条",
        f"  全局块: {st['globals']} 个 / {st['gbytes']} 字节",
        f"  导出符号: {st['exports']}  未定义符号: {st['undefined']}  "
        f"vtable: {st['vtables']}",
    ]
    if arc.undefined:
        lines.append("  未定义: " + "、".join(arc.undefined))
    return "\n".join(lines)


def symbols(path):
    """符号表（`quelmara qla --symbols`）。"""
    arc = Archive.load(path)
    rows = []
    for e in arc.exports:
        params = ", ".join(f"{n}: {_ty_str(t)}" for n, t in e["params"])
        rows.append(f"  fn {e['name']}({params}) -> {_ty_str(e['ret'])}")
    for k, fields in sorted(arc.decls.get("structs", {}).items()):
        if k in ("Drop", "closure"):      # 编译器预置的内部类型，不是库的 API
            continue
        rows.append(f"  struct {k} {{ "
                    + ", ".join(f"{n}: {_ty_str(t)}" for n, t in fields) + " }")
    for k, variants in sorted(arc.decls.get("enums", {}).items()):
        rows.append(f"  enum {k} {{ " + ", ".join(v for v, _f in variants) + " }")
    for k in sorted(arc.decls.get("ifaces", {})):
        rows.append(f"  interface {k}")
    return "\n".join(rows) or "  （无导出符号）"


def _ty_str(t):
    if isinstance(t, (list, tuple)):
        if t and t[0] == "named":
            return str(t[1])
        if len(t) == 2:
            return f"{t[0]}[{_ty_str(t[1])}]"
        return "[" + ", ".join(_ty_str(x) for x in t) + "]"
    return str(t)
