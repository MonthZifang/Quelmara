#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DWARF v4 互操作回归（v1.71）
===========================
用**独立实现**的 DWARF 读取器（不 import qlm_dwarf，只按规范解字节）
解析 `--dbg-info` 产物的四个 `.debug_*` 节，与 `.qlmdbg` 逐项对照：

  1. CU 头：version=4 / address_size=8 / name=源文件 / low_pc=.text RVA
  2. 行表：`.qlmdbg` 的每个 (偏移, 行号) 在 `.debug_line` 里有同址同行的行
  3. 函数：`main` / `work` / `fact` 的 low_pc 与 `.qlmdbg` 的 rva 一致，
     high_pc 落在下一个函数之前
  4. 变量：`main` 的每个变量都有 DIE，`.debug_loc` 区间 == [bind, last)，
     表达式按 loc 形态解出 `DW_OP_fbreg` 或 `DW_OP_regN`
  5. 结构体：`Point` 的 byte_size 与字段偏移

只依赖标准库。跑法：python tests/dwarf_test.py
"""

import json
import os
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm_dbg  # noqa: E402  （只用它的 PE 解析，不用它的 DWARF 代码）

TEXT_RVA = 0x1000
SRC = "fixtures/dbgdemo/main.qma"

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def check(cond, msg):
    ok(msg) if cond else bad(msg)


# ---------------------------------------------------------------------------
# 独立 DWARF 读取器
# ---------------------------------------------------------------------------

DW_TAG = {0x11: "compile_unit", 0x24: "base_type", 0x13: "structure_type",
          0x0d: "member", 0x2e: "subprogram", 0x34: "variable",
          0x05: "formal_parameter", 0x0f: "pointer_type"}

FORM_ADDR, FORM_DATA1, FORM_DATA2, FORM_DATA4 = 0x01, 0x0b, 0x05, 0x06
FORM_DATA8, FORM_STRING, FORM_FLAG_PRESENT = 0x07, 0x08, 0x19
FORM_REF4, FORM_SEC_OFFSET, FORM_EXPRLOC = 0x13, 0x17, 0x18


def uleb(buf, pos):
    n = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        n |= (b & 0x7f) << shift
        shift += 7
        if not (b & 0x80):
            return n, pos


def sleb(buf, pos):
    n = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        n |= (b & 0x7f) << shift
        shift += 7
        if not (b & 0x80):
            if b & 0x40:
                n -= 1 << shift
            return n, pos


def parse_abbrev(buf):
    table = {}
    pos = 0
    while pos < len(buf) and buf[pos]:
        code, pos = uleb(buf, pos)
        tag, pos = uleb(buf, pos)
        children = buf[pos]
        pos += 1
        specs = []
        while True:
            at, pos = uleb(buf, pos)
            form, pos = uleb(buf, pos)
            if at == 0 and form == 0:
                break
            specs.append((at, form))
        table[code] = (tag, children, specs)
    return table


def read_form(buf, pos, form, cu_base=0):
    if form == FORM_ADDR:
        return struct.unpack_from("<Q", buf, pos)[0], pos + 8
    if form == FORM_DATA1:
        return buf[pos], pos + 1
    if form == FORM_DATA2:
        return struct.unpack_from("<H", buf, pos)[0], pos + 2
    if form == FORM_DATA4:
        return struct.unpack_from("<I", buf, pos)[0], pos + 4
    if form == FORM_DATA8:
        return struct.unpack_from("<Q", buf, pos)[0], pos + 8
    if form == FORM_STRING:
        end = buf.index(b"\x00", pos)
        return buf[pos:end].decode("utf-8", "replace"), end + 1
    if form == FORM_FLAG_PRESENT:
        return 1, pos
    if form == FORM_REF4:
        return struct.unpack_from("<I", buf, pos)[0], pos + 4
    if form == FORM_SEC_OFFSET:
        return struct.unpack_from("<I", buf, pos)[0], pos + 4
    if form == FORM_EXPRLOC:
        n, pos = uleb(buf, pos)
        return buf[pos:pos + n], pos + n
    raise ValueError(f"未支持的 form 0x{form:02x}")


def parse_info(buf, abbrev):
    """返回 (cu_attrs, dies)；dies 里每项 {tag, attrs, depth}"""
    unit_len = struct.unpack_from("<I", buf, 0)[0]
    version = struct.unpack_from("<H", buf, 4)[0]
    addr_size = buf[10]
    pos = 11
    cu_attrs = {}
    dies = []
    cur = cu_attrs
    stack = [cu_attrs]
    end = 4 + unit_len
    while pos < end:
        code, pos = uleb(buf, pos)
        if code == 0:
            if len(stack) > 1:
                stack.pop()
                cur = stack[-1]
            continue
        tag, children, specs = abbrev[code]
        attrs = {}
        for at, form in specs:
            attrs[at], pos = read_form(buf, pos, form)
        node = {"tag": tag, "attrs": attrs, "depth": len(stack)}
        dies.append(node)
        if children:
            stack.append(node)
            cur = node
    return {"version": version, "addr_size": addr_size,
            "attrs": cu_attrs, "dies": dies}


def parse_line(buf, file_names_out=None):
    unit_len = struct.unpack_from("<I", buf, 0)[0]
    version = struct.unpack_from("<H", buf, 4)[0]
    header_len = struct.unpack_from("<I", buf, 6)[0]
    pos = 10
    min_inst = buf[pos]
    max_ops = buf[pos + 1]
    default_stmt = buf[pos + 2]
    line_base = struct.unpack_from("<b", buf, pos + 3)[0]
    line_range = buf[pos + 4]
    opcode_base = buf[pos + 5]
    pos += 6
    std_lens = list(buf[pos:pos + opcode_base - 1])
    pos += opcode_base - 1
    # include_directories
    dirs = []
    while buf[pos]:
        end = buf.index(b"\x00", pos)
        dirs.append(buf[pos:end].decode())
        pos = end + 1
    pos += 1
    files = []
    while buf[pos]:
        end = buf.index(b"\x00", pos)
        name = buf[pos:end].decode()
        pos = end + 1
        _d, pos = uleb(buf, pos)
        _m, pos = uleb(buf, pos)
        _l, pos = uleb(buf, pos)
        files.append(name)
    pos += 1
    assert pos == 10 + header_len, f"行表头长度不符: {pos} != {10 + header_len}"

    rows = []
    addr = 0
    file = 1
    line = 1
    while pos < 4 + unit_len:
        op = buf[pos]
        pos += 1
        if op == 0:                      # 扩展
            n, pos = uleb(buf, pos)
            sub = buf[pos]
            if sub == 0x01:              # end_sequence
                addr = 0
                line = 1
                file = 1
            elif sub == 0x02:            # set_address
                addr = struct.unpack_from("<Q", buf, pos + 1)[0]
            pos += n
        elif op == 1:                    # copy
            rows.append((addr, line, file))
        elif op == 2:                    # advance_pc
            d, pos = uleb(buf, pos)
            addr += d * min_inst
        elif op == 3:                    # advance_line
            d, pos = sleb(buf, pos)
            line += d
        elif op == 8:                    # const_add_pc
            addr += ((255 - opcode_base) // line_range) * min_inst
        elif op == 9:                    # fixed_advance_pc
            addr += struct.unpack_from("<H", buf, pos)[0]
            pos += 2
        else:
            for _ in range(std_lens[op - 1]):
                _v, pos = uleb(buf, pos)
    if file_names_out is not None:
        file_names_out.extend(files)
    return {"version": version, "rows": rows, "files": files,
            "line_base": line_base, "line_range": line_range,
            "default_stmt": default_stmt, "max_ops": max_ops,
            "dirs": dirs}


def parse_loc(buf):
    """-> [(offset, begin, end, expr)]；offset 即 DW_AT_location 的值"""
    out = []
    pos = 0
    while pos + 16 <= len(buf):
        entry_off = pos
        begin, end = struct.unpack_from("<QQ", buf, pos)
        pos += 16
        if begin == 0 and end == 0:
            break
        n = struct.unpack_from("<H", buf, pos)[0]
        pos += 2
        out.append((entry_off, begin, end, buf[pos:pos + n]))
        pos += n
    return out


# ---------------------------------------------------------------------------
# 主体
# ---------------------------------------------------------------------------

def main():
    out = os.path.join(ROOT, "build", "dwarf_probe.exe")
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "tools", "stage0", "qlm_cli.py"),
                        "build", SRC, "--target", "win", "--dbg-info",
                        "-o", out],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        bad(f"构建失败: {r.stdout[-400:]} {r.stderr[-800:]}")
        return 1
    ok("--dbg-info 构建成功")

    image_base, secs, data = qlm_dbg.parse_pe(out)
    need = [".qlmdbg", ".debug_abbrev", ".debug_info",
            ".debug_line", ".debug_loc"]
    missing = [n for n in need if n not in secs]
    check(not missing, f"五个调试节齐全（缺: {missing or '无'}）")
    if missing:
        return 1

    def body(name):
        vsize, _rva, _raw, ptr = secs[name]
        return data[ptr:ptr + vsize]

    dbg = json.loads(body(".qlmdbg").decode("utf-8"))
    abbrev = parse_abbrev(body(".debug_abbrev"))
    cu = parse_info(body(".debug_info"), abbrev)
    lt = parse_line(body(".debug_line"))
    locs = parse_loc(body(".debug_loc"))

    # ---- 1. CU ----
    check(cu["dies"][0]["tag"] == 0x11, "第一个 DIE 是 compile_unit")
    a = cu["dies"][0]["attrs"]
    check(cu["version"] == 4, f"CU version = 4（实为 {cu['version']}）")
    check(cu["addr_size"] == 8, f"address_size = 8（实为 {cu['addr_size']}）")
    check(a.get(0x03, "").endswith("main.qma"),
          f"CU name 指向源文件（{a.get(0x03)}）")
    check(a.get(0x11) == TEXT_RVA,
          f"CU low_pc = .text RVA 0x{TEXT_RVA:x}（实为 0x{a.get(0x11, 0):x}）")
    check(a.get(0x12, 0) > 0, f"CU high_pc = {a.get(0x12, 0)}（.text 长度偏移）")
    check(a.get(0x13) == 0x0c, "language = DW_LANG_C99")

    # ---- 2. 行表 ----
    check(lt["version"] == 4, f"line version = 4（实为 {lt['version']}）")
    check(lt["files"] and lt["files"][0] == "main.qma",
          f"file_names[0] = 源文件名（{lt['files'][:1]}）")
    check(lt["line_base"] == -5 and lt["line_range"] == 14,
          "line_base=-5 / line_range=14（GCC 口径）")

    dwarf_rows = {}
    for addr, line, _f in lt["rows"]:
        dwarf_rows.setdefault(addr, []).append(line)
    mism = []
    total = 0
    for fn in dbg["funcs"]:
        if not fn.get("file"):
            continue
        for off, line in fn["lines"]:
            total += 1
            addr = TEXT_RVA + off
            if addr not in dwarf_rows:
                mism.append((hex(addr), line, "缺地址"))
            elif line not in dwarf_rows[addr]:
                mism.append((hex(addr), line, f"行号 {dwarf_rows[addr]}"))
    check(not mism, f"行表逐项一致（{total} 条）{mism[:3] if mism else ''}")

    # ---- 3. 函数 ----
    subs = {d["attrs"].get(0x03): d for d in cu["dies"]
            if d["tag"] == 0x2e}
    qdbg_fn = {f["name"]: f for f in dbg["funcs"]}
    check(set(subs) == {f["name"] for f in dbg["funcs"] if f.get("file")},
          f"subprogram 集合 == 主文件函数集（{len(subs)} 个）")
    bad_pc = []
    for name, d in subs.items():
        low = d["attrs"].get(0x11)
        hi = d["attrs"].get(0x12)
        if low != qdbg_fn[name]["rva"]:
            bad_pc.append((name, hex(low or 0), hex(qdbg_fn[name]["rva"])))
        if not (hi and low and low + hi <= len(body(".text")) + TEXT_RVA):
            bad_pc.append((name, "high_pc 越界", hi))
    check(not bad_pc, f"每个 subprogram 的 low_pc/high_pc 正确 {bad_pc[:3]}")

    # ---- 4. 变量 ----
    # 按"子程序"逐个比对：.qlmdbg 的每个变量 -> (名字, 区间, 位置表达式)，
    # 与 DWARF 子项里的 DIE 多重集对照。用多重集而不是按名字查，是因为
    # 内联后同名变量会重复（main 里既有自己的 n，也有内联进来的 fact 的 n）。
    def expr_of(loc):
        if loc[0] == "m":
            return bytes([0x91]) + _sleb(-loc[1])
        return bytes([0x50 + DWARF_REGS[loc[1]]])

    def span_of(v):
        b = TEXT_RVA + v["bind"]
        e = TEXT_RVA + v["last"]
        return (b, e if e > b else b + 1)

    def kids_of(die):
        idx = cu["dies"].index(die)
        out = []
        for d in cu["dies"][idx + 1:]:
            if d["depth"] <= die["depth"]:
                break
            if d["tag"] in (0x34, 0x05):
                out.append(d)
        return out

    var_bad = []
    for name, die in subs.items():
        want = sorted((v["name"],) + span_of(v) + (expr_of(v["loc"]).hex(),)
                      for v in qdbg_fn[name]["vars"])
        got = []
        for d in kids_of(die):
            off = d["attrs"].get(0x02)
            hit = [e for e in locs if e[0] == off]
            if not hit:
                got.append((d["attrs"].get(0x03), 0, 0, "无位置条目"))
                continue
            _o, begin, end, expr = hit[0]
            got.append((d["attrs"].get(0x03), begin, end, expr.hex()))
        if sorted(got) != want:
            miss = [w for w in want if w not in got][:2]
            extra = [g for g in got if g not in want][:2]
            var_bad.append((name, f"缺 {miss} 多 {extra}"))
    check(not var_bad, f"变量位置列表与 .qlmdbg 逐项一致 {var_bad[:2]}")

    # ---- 5. 结构体 ----
    st = {d["attrs"].get(0x03): d for d in cu["dies"]
          if d["tag"] == 0x13}
    check("Point" in st, "结构体 Point 有 DIE")
    if "Point" in st:
        check(st["Point"]["attrs"].get(0x0b) == 16,
              f"Point byte_size = 16（实为 {st['Point']['attrs'].get(0x0b)}）")
        idx = cu["dies"].index(st["Point"])
        mem = {}
        for d in cu["dies"][idx + 1:]:
            if d["depth"] <= st["Point"]["depth"]:
                break
            if d["tag"] == 0x0d:
                mem[d["attrs"].get(0x03)] = d["attrs"].get(0x38)
        check(mem.get("x") == 0 and mem.get("y") == 8,
              f"Point 字段偏移 x=0 y=8（实为 {mem}）")

    # ---- 6. 不挂 CODEVIEW 目录（避免标准工具误读）----
    e = struct.unpack_from("<I", data, 0x3C)[0]
    coff = e + 4
    opt = coff + 20
    dbg_dir_rva, dbg_dir_size = struct.unpack_from("<II", data, opt + 112 + 8 * 6)
    check(dbg_dir_rva == 0 and dbg_dir_size == 0,
          "DataDirectory[6]（DEBUG/CodeView）为空")

    print(f"\nDWARF: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


# 与 qlm_dwarf 相同的寄存器映射（测试里独立写一份，避免自证）
DWARF_REGS = [0, 2, 1, 3, 7, 6, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15]


def _sleb(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if (n == 0 and not (b & 0x40)) or (n == -1 and (b & 0x40)):
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


if __name__ == "__main__":
    sys.exit(main())
