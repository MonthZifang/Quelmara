#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara 自研 Windows x86_64 后端（PE/COFF，无 CRT）
================================================
Quelmara 源码 -> QuIR（与 Linux/ELF 后端完全同一条前端与优化管线）
           -> 自研 x86_64 编码器（复用 qlm_native.Enc）
           -> 自研 PE/COFF 写出器（导入 kernel32、DIR64 重定位、4 个节）

设计要点：
  * 不依赖 libc / CRT / MSVC / MinGW：入口直接是自研机器码，
    I/O 走 kernel32 导入（GetStdHandle / WriteFile / ExitProcess），
    内存走 VirtualAlloc（MEM_RESERVE + 1MB 粒度 MEM_COMMIT），
    多核走 CreateThread / WaitForSingleObject，不依赖 pthread。
  * 与 Linux 后端共享：Parser / QuIR / 优化 passes / 寄存器分配 / 编码器。
    平台差异只在「如何做一次系统调用」这一薄层（Lower 的 emit_* helper）。
  * 产物默认约数 KB，无运行时初始化，冷启动即 main —— 「省用」。

PE 结构：
  DOS header | PE sig | COFF | PE32+ optional | 4 section headers
  .text  (RX, 代码)  .data (RW, 字符串/运行库全局)
  .rdata (RW, 导入表 ILT/IAT)  .reloc (DIR64, ASLR 安全)
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qlm_native import (Codegen, lower_and_optimize,  # noqa: E402
                           ACC, RCX, RDX, R8, R9, RSP, SCRATCH)

# ---------------------------------------------------------------------------
# PE 常量
# ---------------------------------------------------------------------------
IMAGE_BASE = 0x140000000
TEXT_RVA = 0x1000
SECT_ALIGN = 0x1000
FILE_ALIGN = 0x200
HDR_DOS = 0x80
OPT_SIZE = 240                # PE32+ optional header
WIN_ARG = [RCX, RDX, R8, R9]

SCN_CODE = 0x60000020         # CODE | EXECUTE | READ
SCN_RDATA = 0xC0000040        # INITIALIZED_DATA | READ | WRITE（IAT 由加载器回填）
SCN_DATA = 0xC0000040         # INITIALIZED_DATA | READ | WRITE
SCN_RELOC = 0x42000040        # INITIALIZED_DATA | DISCARDABLE | READ


def align(n, a):
    return (n + a - 1) // a * a


# ---------------------------------------------------------------------------
# Windows 代码生成：复用 Codegen，只覆盖「入口」与「winapi」两条指令
# ---------------------------------------------------------------------------


class WinCodegen(Codegen):
    def __init__(self, fns, globals_bytes):
        super().__init__(fns, globals_bytes, base=IMAGE_BASE, entry_off=TEXT_RVA)
        self.api_fixups = []       # (patch_pos, api_name)

    # ---- 导入调用：call qword ptr [rip + disp32] ----
    def _call_api(self, api):
        self.enc.emit(b"\xff\x15")
        self.api_fixups.append((self.enc.pos(), api))
        self.enc.emit(b"\x00\x00\x00\x00")

    def gen_entry(self):
        """PE AddressOfEntryPoint：对齐栈 -> 调 main -> ExitProcess(返回值)"""
        enc = self.enc
        enc.alu_ri("and", RSP, -16)
        enc.call("main")
        enc.alu_ri("sub", RSP, 32)       # Win64 shadow space（ExitProcess 不返回）
        enc.mov_rr(RCX, ACC)
        self._call_api("ExitProcess")

    def gen_winapi(self, ins):
        """('winapi', dst|None, name, [args])：Win64 调用约定

        RCX/RDX/R8/R9 传前 4 个参数；第 5/6 个落在 [rsp+32]/[rsp+40]。
        始终预留 32 字节 shadow space（Win64 ABI 要求）。
        """
        _, dst, api, args = ins
        n = len(args)
        extra = align(32 + max(0, 8 * (n - 4)), 16)
        enc = self.enc
        enc.alu_ri("sub", RSP, extra)
        # 先写栈参数：随后把参数搬进 RCX/RDX/R8/R9 时可能覆盖它们的来源寄存器
        for i, a in enumerate(args[4:], start=4):
            r = self.fetch(SCRATCH, a)
            enc.mov_mr(RSP, 4, 0, 32 + 8 * (i - 4), r)
        moves = [(self.src_move(a), ("r", WIN_ARG[i]))
                 for i, a in enumerate(args[:4])]
        self.parallel_move(moves)
        self._call_api(api)
        enc.alu_ri("add", RSP, extra)
        if dst is not None:
            self.commit(dst, ACC)

    def gen_instr(self, ins):
        if ins[0] == "winapi":
            self.gen_winapi(ins)
            return
        if ins[0] == "winargs":
            # ThreadProc 形参来自 Win64 参数寄存器 RCX/RDX/R8/R9
            moves = [(("r", WIN_ARG[i]), self.dst_move(d))
                     for i, d in enumerate(ins[1])]
            self.parallel_move(moves)
            return
        if ins[0] == "syscall":
            raise SyntaxError("Windows 后端不应出现 raw syscall（平台抽象漏了）")
        super().gen_instr(ins)

    # ---- 生成代码 + 数据 + 重定位清单（RVA 在 build_pe 里统一排布）----
    def gen_all_pe(self):
        self.gen_entry()
        self.gen_functions()
        enc = self.enc
        enc.resolve()
        code = bytearray(enc.buf)

        data = b"".join(self.globals)
        data_rva = TEXT_RVA + align(len(code), SECT_ALIGN)
        relocs = []

        for patch, gid in self.global_fixups:
            off = sum(len(g) for g in self.globals[:gid])
            struct.pack_into("<q", code, patch, IMAGE_BASE + data_rva + off)
            relocs.append(patch)
        for patch, label in self.code_fixups:
            struct.pack_into("<q", code, patch,
                             IMAGE_BASE + TEXT_RVA + enc.labels[label])
            relocs.append(patch)

        imports = list(dict.fromkeys(api for _p, api in self.api_fixups))
        return bytes(code), data, relocs, imports, self.api_fixups


# ---------------------------------------------------------------------------
# 导入表（多 DLL：kernel32 + ws2_32——v1.3 起支持原生 socket）
# ---------------------------------------------------------------------------

# ws2_32.dll 白名单：命中走 ws2_32，其余一律 kernel32
WS2_32_FUNCS = {"WSAStartup", "WSACleanup", "socket", "bind", "listen",
                "accept", "recv", "send", "closesocket", "inet_addr",
                "htons", "ntohs", "setsockopt", "ioctlsocket"}


def _dll_groups(imports):
    """{dll 名: [函数名]}——保持 imports 首次出现顺序内的稳定分组。
    WSA* 前缀一律 ws2_32（WSAGetLastError 曾被漏归 kernel32 导致
    0xC0000139 ENTRYPOINT_NOT_FOUND，进程起不来）。"""
    groups = {}
    for name in imports:
        dll = ("ws2_32.dll" if name.startswith("WSA") or name in WS2_32_FUNCS
               else "kernel32.dll")
        groups.setdefault(dll, []).append(name)
    return groups


def build_idata(imports, rdata_rva):
    """多 DLL 导入表。每个 DLL 一个 {ILT, IAT} 对 + 结束哨兵描述符。
    返回 (rdata 内容, 0, dir_size, {函数名: IAT 槽 RVA})"""
    groups = _dll_groups(imports)
    dlls = list(groups)
    desc_size = 20 * (len(dlls) + 1)
    cur = align(desc_size, 8)
    ilt_offs, iat_offs, hn_offs = {}, {}, {}
    for dll in dlls:
        k = len(groups[dll])
        ilt_offs[dll] = cur
        cur += 8 * (k + 1)
        iat_offs[dll] = cur
        cur += 8 * (k + 1)
    for dll in dlls:
        for name in groups[dll]:
            cur = align(cur, 2)
            hn_offs[(dll, name)] = cur
            cur += 2 + len(name) + 1
    cur = align(cur, 2)
    dll_offs = {}
    for dll in dlls:
        dll_offs[dll] = cur
        cur += len(dll) + 1

    buf = bytearray(cur)
    iat_map = {}
    for i, dll in enumerate(dlls):
        base = i * 20
        struct.pack_into("<IIIII", buf, base,
                         rdata_rva + ilt_offs[dll], 0, 0,
                         rdata_rva + dll_offs[dll], rdata_rva + iat_offs[dll])
        for j, name in enumerate(groups[dll]):
            hn = hn_offs[(dll, name)]
            struct.pack_into("<Q", buf, ilt_offs[dll] + 8 * j, rdata_rva + hn)
            struct.pack_into("<Q", buf, iat_offs[dll] + 8 * j, rdata_rva + hn)
            iat_map[name] = rdata_rva + iat_offs[dll] + 8 * j
            struct.pack_into("<H", buf, hn, 0)
            raw = name.encode("ascii")
            buf[hn + 2:hn + 2 + len(raw)] = raw
        raw_dll = dll.encode("ascii")
        buf[dll_offs[dll]:dll_offs[dll] + len(raw_dll)] = raw_dll
    return (bytes(buf), 0, desc_size, iat_map)


# ---------------------------------------------------------------------------
# 基址重定位（IMAGE_REL_BASED_DIR64）
# ---------------------------------------------------------------------------


def build_reloc(reloc_offsets, text_rva):
    pages = {}
    for off in reloc_offsets:
        pages.setdefault(off // 0x1000, set()).add(off % 0x1000)
    out = bytearray()
    for page in sorted(pages):
        # 注意：补齐块长度用的必须是真正的 0x0000 哨兵，
        # 不能套 (10<<12)|0 —— 那是一个「在页首做 DIR64」的真实重定位，
        # 会把入口第一条指令的 8 字节改掉（已踩坑：0xC0000005）。
        entries = [(10 << 12) | d for d in sorted(pages[page])]
        if len(entries) % 2:
            entries.append(0)
        out += struct.pack("<II", text_rva + page * 0x1000, 8 + 2 * len(entries))
        out += b"".join(struct.pack("<H", e) for e in entries)
    return bytes(out)


# ---------------------------------------------------------------------------
# PE/COFF 写出
# ---------------------------------------------------------------------------


def build_pe(code, data, reloc_offsets, imports, api_fixups):
    code = bytearray(code)
    text_size = len(code)
    data = data or b"\x00" * 8

    data_rva = TEXT_RVA + align(text_size, SECT_ALIGN)
    rdata_rva = data_rva + align(len(data), SECT_ALIGN)

    rdata, imp_off, imp_size, iat = build_idata(imports, rdata_rva)
    reloc_rva = rdata_rva + align(len(rdata), SECT_ALIGN)

    # 回填 call [rip+disp32]：disp 相对下一条指令
    for patch, api in api_fixups:
        disp = iat[api] - (TEXT_RVA + patch + 4)
        struct.pack_into("<i", code, patch, disp)

    reloc = build_reloc(reloc_offsets, TEXT_RVA) if reloc_offsets else b""

    # ---- 节表 ----
    # headers_size 必须把 section header 算进去，否则最后一节头会被 .text
    # 的 RawData 覆盖（已踩坑：入口跳到垃圾字节 -> 0xC0000096）。
    nsec = 4 if reloc else 3
    headers_size = align(HDR_DOS + 4 + 20 + OPT_SIZE + 40 * nsec, FILE_ALIGN)
    secs = []
    raw = headers_size

    def add_sec(name, rva, body, chars):
        nonlocal raw
        vsize = max(len(body), 1)
        raw_size = align(vsize, FILE_ALIGN)
        ptr = raw
        secs.append((name, vsize, rva, raw_size, ptr, chars))
        raw += raw_size
        return ptr

    add_sec(b".text", TEXT_RVA, bytes(code), SCN_CODE)
    add_sec(b".data", data_rva, data, SCN_DATA)
    add_sec(b".rdata", rdata_rva, rdata, SCN_RDATA)
    if reloc:
        add_sec(b".reloc", reloc_rva, reloc, SCN_RELOC)

    size_of_image = align((reloc_rva + len(reloc)) if reloc else (rdata_rva + len(rdata)),
                          SECT_ALIGN)
    init_size = secs[1][3] + secs[2][3] + (secs[3][3] if reloc else 0)

    # ---- DOS + PE 头 ----
    dos = b"MZ" + b"\x00" * 58 + struct.pack("<I", HDR_DOS)
    coff = struct.pack("<HHIIIHH", 0x8664, len(secs), 0, 0, 0, OPT_SIZE, 0x0022)

    o = bytearray(OPT_SIZE)
    struct.pack_into("<H", o, 0, 0x20B)                 # PE32+
    o[2], o[3] = 14, 0                                  # linker version
    struct.pack_into("<I", o, 4, secs[0][3])            # SizeOfCode
    struct.pack_into("<I", o, 8, init_size)
    struct.pack_into("<I", o, 12, 0)
    struct.pack_into("<I", o, 16, TEXT_RVA)             # AddressOfEntryPoint
    struct.pack_into("<I", o, 20, TEXT_RVA)             # BaseOfCode
    struct.pack_into("<Q", o, 24, IMAGE_BASE)
    struct.pack_into("<I", o, 32, SECT_ALIGN)
    struct.pack_into("<I", o, 36, FILE_ALIGN)
    struct.pack_into("<H", o, 40, 6)                    # OS version 6.0
    struct.pack_into("<H", o, 48, 6)                    # subsystem version 6.0
    struct.pack_into("<I", o, 56, size_of_image)
    struct.pack_into("<I", o, 60, headers_size)
    struct.pack_into("<H", o, 68, 3)                    # console
    struct.pack_into("<H", o, 70, 0x8160)               # HIGH_ENTROPY|DYNAMIC_BASE|NX|TS
    struct.pack_into("<Q", o, 72, 0x100000)             # stack reserve 1MB
    struct.pack_into("<Q", o, 80, 0x1000)               # stack commit 4KB
    struct.pack_into("<Q", o, 88, 0x100000)             # heap reserve
    struct.pack_into("<Q", o, 96, 0x1000)               # heap commit
    struct.pack_into("<I", o, 104, 0)
    struct.pack_into("<I", o, 108, 16)
    struct.pack_into("<II", o, 112 + 8 * 1, rdata_rva + imp_off, imp_size)  # import
    if reloc:
        struct.pack_into("<II", o, 112 + 8 * 5, reloc_rva, len(reloc))

    sect_hdr = b""
    for name, vsize, rva, raw_size, ptr, chars in secs:
        sect_hdr += name.ljust(8, b"\x00")
        sect_hdr += struct.pack("<IIIIIIHHI", vsize, rva, raw_size, ptr,
                                0, 0, 0, 0, chars)

    pe = dos + b"\x00" * (HDR_DOS - len(dos)) + b"PE\x00\x00" + coff + bytes(o) + sect_hdr
    blob = bytearray(pe)
    blob += b"\x00" * (headers_size - len(blob))

    bodies = [bytes(code), data, rdata, reloc if reloc else b""]
    for (name, vsize, rva, raw_size, ptr, chars), body in zip(secs, bodies):
        blob += b"\x00" * (ptr - len(blob))
        blob += body
        blob += b"\x00" * (raw_size - len(body))

    return bytes(blob)


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def transpile_win(src_path, dump_ir=False, optimize=True):
    fns, low, cfg = lower_and_optimize(src_path, optimize=optimize,
                                       dump_ir=dump_ir, platform="windows")
    cg = WinCodegen(fns, low.globals)
    code, data, relocs, imports, api_fixups = cg.gen_all_pe()
    pe = build_pe(code, data, relocs, imports, api_fixups)
    return pe, cfg


def write_exe(path, blob):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(blob)


def main():
    ap = argparse.ArgumentParser(description="Quelmara Windows PE/COFF 后端（无 CRT）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("build", "run"):
        p = sub.add_parser(c)
        p.add_argument("src")
        p.add_argument("-o", "--out", default=None)
        p.add_argument("--dump-ir", action="store_true")
        p.add_argument("--no-opt", action="store_true")
    args = ap.parse_args()

    blob, cfg = transpile_win(args.src, dump_ir=args.dump_ir,
                              optimize=not args.no_opt)
    base = os.path.splitext(os.path.basename(args.src))[0]
    out = args.out or os.path.join("build", base + ".exe")
    write_exe(out, blob)
    print(f"[qlm-win] {args.src} -> {out} ({len(blob)} bytes PE, no CRT)")
    print(f"[qlm-win] config: {cfg['_path'] or '(default)'} | "
          f"multicore={cfg['core']['multicore']} "
          f"threads={cfg['core']['threads'] or 'auto'}")
    if args.cmd == "run":
        import subprocess
        return subprocess.call([os.path.abspath(out)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
