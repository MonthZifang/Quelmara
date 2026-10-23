#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara DWARF v4 调试信息发射（stage-0 工具链，v1.71）
=====================================================
把 codegen 已经收集到的调试表（`.qlmdbg` 的同一份数据源）再编码一份
**标准 DWARF v4**，随 PE 一起发出，供外部工具（llvm-dwarfdump / objdump /
gdb / IDE）消费。

四个节：

| 节 | 内容 |
|---|---|
| `.debug_abbrev` | 10 条固定缩写（CU / base_type / structure / member / subprogram / variable / formal_parameter / pointer / typedef / 数组不用） |
| `.debug_info`   | 一个 CU：基础类型 → 结构体布局 → 每个源文件函数的 subprogram + 形参/局部变量 |
| `.debug_line`   | 行号程序：每个函数一条 `set_address`，随后 `advance_pc` / `advance_line` / `copy` |
| `.debug_loc`    | 变量位置列表：`[bind, last)` 区间内 `DW_OP_fbreg -off` 或 `DW_OP_regN` |

三条口径（必须与 `.qlmdbg` 一致，否则两份调试信息会各说各话）：

1. **地址一律是 RVA（镜像相对），不是绝对虚拟地址。** PE 的调试节不参与
   基址重定位（DISCARDABLE、不映射），写绝对地址就得给调试节造重定位表；
   RVA 与 `qlm_dbg` 的 `PC - image_base` 同一口径，外部工具加 image base 即可。
2. **帧基址是 RBP**（`DW_AT_frame_base = DW_OP_breg6 0`）。栈槽位置写
   `DW_OP_fbreg -off`，与 codegen 的 `[rbp - off]` 同源。
3. **寄存器号要翻译**。codegen 的内部编号是 Rax/Rcx/Rdx/... 的声明顺序，
   DWARF x86-64 的编号是 rax/rdx/rcx/rbx/rsi/rdi/rbp/rsp/...——两者在
   第 1、2 位和第 4、5、6 位不同，直接照抄会读到错的寄存器。

已知边界：不发 PDB（Windows 原生链路需要 MSF 容器 + CodeView 记录，
与 DWARF 是两套；本机无 MSVC 工具链可验证）；不发 `.eh_frame`（我们的
帧链是 RBP 链，`DW_AT_frame_base` 直接写 RBP，不依赖 CFI）。
"""

import os
import struct

# ---------------------------------------------------------------------------
# DWARF 常量（只列用到的）
# ---------------------------------------------------------------------------

DW_TAG_array_type = 0x01
DW_TAG_formal_parameter = 0x05
DW_TAG_member = 0x0d
DW_TAG_pointer_type = 0x0f
DW_TAG_compile_unit = 0x11
DW_TAG_structure_type = 0x13
DW_TAG_base_type = 0x24
DW_TAG_subprogram = 0x2e
DW_TAG_variable = 0x34

DW_AT_location = 0x02
DW_AT_name = 0x03
DW_AT_byte_size = 0x0b
DW_AT_stmt_list = 0x10
DW_AT_low_pc = 0x11
DW_AT_high_pc = 0x12
DW_AT_language = 0x13
DW_AT_comp_dir = 0x1b
DW_AT_producer = 0x25
DW_AT_type = 0x49
DW_AT_encoding = 0x3e
DW_AT_data_member_location = 0x38
DW_AT_decl_file = 0x3a
DW_AT_decl_line = 0x3b
DW_AT_external = 0x3f
DW_AT_frame_base = 0x40

DW_FORM_addr = 0x01
DW_FORM_data1 = 0x0b
DW_FORM_data2 = 0x05
DW_FORM_data8 = 0x07
DW_FORM_string = 0x08
DW_FORM_flag_present = 0x19
DW_FORM_ref4 = 0x13
DW_FORM_sec_offset = 0x17
DW_FORM_exprloc = 0x18

DW_ATE_boolean = 0x02
DW_ATE_float = 0x04
DW_ATE_signed = 0x05
DW_ATE_signed_char = 0x06
DW_ATE_unsigned = 0x07

DW_LANG_C99 = 0x000c

DW_LNS_copy = 0x01
DW_LNS_advance_pc = 0x02
DW_LNS_advance_line = 0x03
DW_LNE_end_sequence = 0x01
DW_LNE_set_address = 0x02

DW_OP_fbreg = 0x91
DW_OP_breg6 = 0x76          # DW_OP_breg0 + 6 = RBP
DW_OP_reg0 = 0x50

# codegen 内部寄存器编号 -> DWARF x86-64 寄存器号
# 内部：Rax Rcx Rdx Rbx Rsp Rbp Rsi Rdi R8..R15（见 qlm_dbg.REG_NAMES）
# DWARF：rax rdx rcx rbx rsi rdi rbp rsp r8..r15
DWARF_REGS = [0, 2, 1, 3, 7, 6, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15]

# 缩写表：(code, tag, children, [(attr, form)...])
ABBREVS = [
    (1, DW_TAG_compile_unit, 1,
     [(DW_AT_name, DW_FORM_string),
      (DW_AT_producer, DW_FORM_string),
      (DW_AT_language, DW_FORM_data1),
      (DW_AT_comp_dir, DW_FORM_string),
      (DW_AT_low_pc, DW_FORM_addr),
      (DW_AT_high_pc, DW_FORM_data8),
      (DW_AT_stmt_list, DW_FORM_sec_offset)]),
    (2, DW_TAG_base_type, 0,
     [(DW_AT_name, DW_FORM_string),
      (DW_AT_encoding, DW_FORM_data1),
      (DW_AT_byte_size, DW_FORM_data1)]),
    (3, DW_TAG_structure_type, 1,
     [(DW_AT_name, DW_FORM_string),
      (DW_AT_byte_size, DW_FORM_data2)]),
    (4, DW_TAG_member, 0,
     [(DW_AT_name, DW_FORM_string),
      (DW_AT_type, DW_FORM_ref4),
      (DW_AT_data_member_location, DW_FORM_data2)]),
    (5, DW_TAG_subprogram, 1,
     [(DW_AT_name, DW_FORM_string),
      (DW_AT_low_pc, DW_FORM_addr),
      (DW_AT_high_pc, DW_FORM_data8),
      (DW_AT_decl_file, DW_FORM_data1),
      (DW_AT_decl_line, DW_FORM_data2),
      (DW_AT_frame_base, DW_FORM_exprloc),
      (DW_AT_external, DW_FORM_flag_present)]),
    (6, DW_TAG_variable, 0,
     [(DW_AT_name, DW_FORM_string),
      (DW_AT_type, DW_FORM_ref4),
      (DW_AT_location, DW_FORM_sec_offset)]),
    (7, DW_TAG_formal_parameter, 0,
     [(DW_AT_name, DW_FORM_string),
      (DW_AT_type, DW_FORM_ref4),
      (DW_AT_location, DW_FORM_sec_offset)]),
    (8, DW_TAG_pointer_type, 0,
     [(DW_AT_type, DW_FORM_ref4)]),
]

BASE_TYPES = [
    ("int", DW_ATE_signed, 8),
    ("bool", DW_ATE_boolean, 1),
    ("f64", DW_ATE_float, 8),
    ("f32", DW_ATE_float, 4),
    ("char", DW_ATE_signed_char, 1),
    # str 是长度前缀字节串（数据指针前 8 字节是长度），DWARF 里只能表达
    # "8 字节无符号"；真实内容由调试器按 .qlmdbg 渲染。
    ("str", DW_ATE_unsigned, 8),
]


# ---------------------------------------------------------------------------
# LEB128
# ---------------------------------------------------------------------------

def uleb(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def sleb(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if (n == 0 and not (b & 0x40)) or (n == -1 and (b & 0x40)):
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


def cstr(s):
    return s.encode("utf-8") + b"\x00"


def abbrev_blob():
    out = bytearray()
    for code, tag, children, specs in ABBREVS:
        out += uleb(code) + uleb(tag) + bytes([children])
        for at, form in specs:
            out += uleb(at) + uleb(form)
        out += b"\x00\x00"
    out += b"\x00"
    return bytes(out)


# ---------------------------------------------------------------------------
# 位置表达式
# ---------------------------------------------------------------------------

def loc_expr(loc):
    """["r", 内部寄存器号] | ["m", 帧槽字节距] -> DWARF 表达式字节"""
    if loc[0] == "r":
        return bytes([DW_OP_reg0 + DWARF_REGS[loc[1]]])
    return bytes([DW_OP_fbreg]) + sleb(-loc[1])


def frame_base_expr():
    return bytes([DW_OP_breg6]) + sleb(0)


# ---------------------------------------------------------------------------
# 主体
# ---------------------------------------------------------------------------

class _Info:
    """按 CU 相对偏移写 DIE；未解析的类型引用先占 4 字节、最后回填。"""

    def __init__(self):
        self.b = bytearray()
        self.fix = []          # (pos, type_name)

    def u8(self, v):
        self.b.append(v & 0xff)

    def u16(self, v):
        self.b += struct.pack("<H", v)

    def u32(self, v):
        self.b += struct.pack("<I", v)

    def u64(self, v):
        self.b += struct.pack("<Q", v)

    def uleb(self, v):
        self.b += uleb(v)

    def ref(self, name):
        self.fix.append((len(self.b), name))
        self.b += b"\x00\x00\x00\x00"

    def patch(self, offsets):
        for pos, name in self.fix:
            if name not in offsets:
                raise KeyError(f"DWARF 类型引用未解析: {name}")
            struct.pack_into("<I", self.b, pos, offsets[name])
        self.fix = []


def _build_loc(funcs, text_rva):
    """变量位置列表；返回 (bytes, {(func_index, var_index): offset})"""
    out = bytearray()
    offs = {}
    for fi, fn in enumerate(funcs):
        for vi, v in enumerate(fn["vars"]):
            begin = text_rva + v["bind"]
            end = text_rva + v["last"]
            if end <= begin:
                end = begin + 1        # 单指令生命周期也要有非空区间
            expr = loc_expr(v["loc"])
            offs[(fi, vi)] = len(out)
            out += struct.pack("<QQH", begin, end, len(expr)) + expr
    out += struct.pack("<QQ", 0, 0)    # 列表结束哨兵
    return bytes(out), offs


def _build_line(funcs, text_rva, src_name):
    """行号程序（DWARF v4，单文件）。"""
    prog = bytearray()
    for fn in funcs:
        prog += bytes([0x00]) + uleb(9) + bytes([DW_LNE_set_address])
        prog += struct.pack("<Q", fn["rva"])
        cur_addr = fn["rva"]
        cur_line = 1
        for off, line in fn["lines"]:
            addr = text_rva + off
            if addr != cur_addr:
                prog += bytes([DW_LNS_advance_pc]) + uleb(addr - cur_addr)
                cur_addr = addr
            if line != cur_line:
                prog += bytes([DW_LNS_advance_line]) + sleb(line - cur_line)
                cur_line = line
            prog += bytes([DW_LNS_copy])
        prog += bytes([0x00]) + uleb(1) + bytes([DW_LNE_end_sequence])

    body = bytearray()
    body += bytes([1])                      # minimum_instruction_length
    body += bytes([1])                      # maximum_operations_per_instruction
    body += bytes([1])                      # default_is_stmt
    body += struct.pack("<b", -5)           # line_base
    body += bytes([14])                     # line_range
    body += bytes([13])                     # opcode_base
    body += bytes([0, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0, 1])   # std lengths
    body += cstr(".")                       # include_directories[0] = 编译目录
    body += b"\x00"                         # 目录表结束
    # DWARF 4 的 file_names 表从 1 开始编号：DW_AT_decl_file = 1 指向
    # file_names[0]，所以第一项就放源文件本身（不要先塞一个空项——
    # 那样 decl_file=1 会指向空名字）。
    body += cstr(src_name) + uleb(0) + uleb(0) + uleb(0)  # file_names[0]
    body += b"\x00"                         # 文件表结束

    header_len = len(body)
    unit = bytearray()
    unit += struct.pack("<H", 4)            # version
    unit += struct.pack("<I", header_len)   # header_length
    unit += bytes(body)
    unit += bytes(prog)
    return struct.pack("<I", len(unit)) + bytes(unit)


def _type_of(v, struct_layout):
    """变量/形参的类型名（决定 DW_AT_type 指向哪个 DIE）"""
    if v["kind"] == "struct" and v["s"]:
        return v["s"]
    if v["kind"] in ("f64", "f32", "bool", "str"):
        return v["kind"]
    if v["kind"] == "slice":
        return "slice"
    return "int"


def _field_type(fty):
    if fty in ("int", "bool", "f64", "f32", "str", "slice", "char"):
        return fty
    return fty          # 具名 struct / enum 按同名 DIE 引用


def build(dbg, src_path, struct_layout, text_rva, text_size, comp_dir="."):
    """返回 {节名: 节体}；节名是标准 DWARF 名（PE 里走长节名表）。

    dbg 结构见 qlm_dbinfo.serialize_dbg：{"funcs":[{name,file,rva,lines,vars}]}
    """
    allf = sorted(dbg["funcs"], key=lambda f: f["rva"])
    end_of = {}
    for i, f in enumerate(allf):
        end_of[id(f)] = (allf[i + 1]["rva"] if i + 1 < len(allf)
                         else text_rva + text_size)

    # 只有主文件函数有源码行号；库函数（file=None）不进 DWARF——
    # 它们的行号属于别的文件，混进单 CU 的行表会把行号算错。
    funcs = [f for f in allf if f.get("file") and f.get("lines")]

    # 结构体 DIE 集合：布局表 + 被字段/变量引用到的 slice 合成类型
    struct_names = list(struct_layout.keys())
    need_slice = any(fty == "slice"
                     for lay in struct_layout.values()
                     for _n, fty, _o in lay["fields"])
    need_slice = need_slice or any(
        _type_of(v, struct_layout) == "slice"
        for f in funcs for v in f["vars"])

    loc, loc_offs = _build_loc(funcs, text_rva)
    line = _build_line(funcs, text_rva, os.path.basename(src_path))

    info = _Info()
    info.u32(0)                    # unit_length 占位
    info.u16(4)                    # version
    info.u32(0)                    # debug_abbrev_offset
    info.u8(8)                     # address_size

    # ---- CU ----
    info.uleb(1)
    info.b += cstr(src_path.replace("\\", "/"))
    info.b += cstr("Quelmara stage-0 (qlm_dwarf v1.71)")
    info.u8(DW_LANG_C99)
    info.b += cstr(comp_dir.replace("\\", "/"))
    info.u64(text_rva)
    info.u64(text_size)
    info.u32(0)                    # stmt_list

    offsets = {}

    # ---- 基础类型 ----
    for name, enc, size in BASE_TYPES:
        offsets[name] = len(info.b)
        info.uleb(2)
        info.b += cstr(name)
        info.u8(enc)
        info.u8(size)

    # ---- 结构体 ----
    for sname in struct_names:
        offsets[sname] = len(info.b)
        info.uleb(3)
        info.b += cstr(sname)
        info.u16(struct_layout[sname]["words"] * 8)
        for fname, fty, woff in struct_layout[sname]["fields"]:
            info.uleb(4)
            info.b += cstr(fname)
            info.ref(_field_type(fty))
            info.u16(woff * 8)
        info.u8(0)                 # 子项结束

    if need_slice:
        offsets["slice"] = len(info.b)
        info.uleb(3)
        info.b += cstr("slice")
        info.u16(16)
        for fname, fty, woff in (("data", "int", 0), ("len", "int", 1)):
            info.uleb(4)
            info.b += cstr(fname)
            info.ref(fty)
            info.u16(woff * 8)
        info.u8(0)

    # ---- 函数 ----
    for fi, fn in enumerate(funcs):
        info.uleb(5)
        info.b += cstr(fn["name"])
        info.u64(fn["rva"])
        info.u64(end_of[id(fn)] - fn["rva"])
        info.u8(1)                                  # decl_file = file_names[0]
        info.u16(fn["lines"][0][1])                 # decl_line
        fb = frame_base_expr()
        info.b += uleb(len(fb)) + fb
        # DW_AT_external 是 flag_present：无值
        for vi, v in enumerate(fn["vars"]):
            info.uleb(7 if v.get("entry") else 6)
            info.b += cstr(v["name"])
            info.ref(_type_of(v, struct_layout))
            info.u32(loc_offs[(fi, vi)])
        info.u8(0)                 # 函数子项结束
    info.u8(0)                     # CU 子项结束

    info.patch(offsets)
    unit = info.b
    struct.pack_into("<I", unit, 0, len(unit) - 4)

    return {".debug_abbrev": abbrev_blob(),
            ".debug_info": bytes(unit),
            ".debug_line": line,
            ".debug_loc": loc}
