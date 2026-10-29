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
                           ACC, RCX, RDX, R8, R9, RSP, SCRATCH, SCRATCH2)

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
# v1.62：.qlmdbg 调试节（自研格式，非 DWARF/PDB）。只读数据——
# 不放 DEBUG_DIRECTORY：那是 CODEVIEW 目录，挂非标准格式会让标准工具误读。
SCN_DBG = 0x40000040          # INITIALIZED_DATA | READ
# v1.71：DWARF 节（.debug_abbrev / .debug_info / .debug_line / .debug_loc）。
# MinGW 口径：INITIALIZED_DATA | DISCARDABLE | READ——调试节不映射进内存，
# 也不参与基址重定位（所以地址一律写 RVA，见 qlm_dwarf 模块头）。
SCN_DWARF = 0x42000040


def align(n, a):
    return (n + a - 1) // a * a


# ---------------------------------------------------------------------------
# Windows 代码生成：复用 Codegen，只覆盖「入口」与「winapi」两条指令
# ---------------------------------------------------------------------------


class WinCodegen(Codegen):
    def __init__(self, fns, globals_bytes, low=None):
        super().__init__(fns, globals_bytes, base=IMAGE_BASE, entry_off=TEXT_RVA,
                         low=low)
        # (patch_pos, dll|None, api_name)：dll=None 表示"内置调用"，
        # 由 _dll_groups 的白名单归组（kernel32 / ws2_32）；@ffi 声明的
        # 调用带显式 DLL 名（v1.87）。
        self.api_fixups = []

    # ---- 导入调用：call qword ptr [rip + disp32] ----
    def _call_api(self, api, dll=None):
        self.enc.emit(b"\xff\x15")
        self.api_fixups.append((self.enc.pos(), dll, api))
        self.enc.emit(b"\x00\x00\x00\x00")

    def gen_entry(self):
        """PE AddressOfEntryPoint：对齐栈 -> 调 main -> ExitProcess(返回值)"""
        enc = self.enc
        enc.alu_ri("and", RSP, -16)
        enc.call("main")
        enc.alu_ri("sub", RSP, 32)       # Win64 shadow space（ExitProcess 不返回）
        enc.mov_rr(RCX, ACC)
        self._call_api("ExitProcess")

    def gen_ffi(self, ins):
        """('ffi', dst|None, dll, sym, kinds, ret, [args])：Win64 调用约定（v1.87）

        Win64 与自研 ABI 的差异，全在这一个函数里：
          1. 整数实参进 RCX/RDX/R8/R9（不是 RDI/RSI/RDX/RCX/R8/R9）；
          2. **浮点实参单独计数**进 XMM0-3——第 5 个浮点实参才落栈，
             与整数实参的序号互不影响（Win64 的独立寄存器类分配）；
          3. 返回值：整数在 RAX、浮点在 XMM0；bool 按 32 位 BOOL 零扩展。

        栈：始终预留 32 字节 shadow space；第 5+ 个同类实参落 [rsp+32+8k]
        （k 是"落栈实参"的出现序号，整数与浮点混排时按出现顺序连续排）。
        搬移顺序 = 栈实参 -> XMM -> 整数寄存器：XMM 装载读的是 GPR 位模式，
        必须在整数搬移改写这些 GPR 之前完成。
        """
        _, dst, dll, sym, kinds, ret, args = ins
        enc = self.enc
        int_regs, xmm_regs, stack = [], [], []
        n_int = n_flt = 0
        for a, k in zip(args, kinds):
            if k == "i":
                if n_int < 4:
                    int_regs.append((a, n_int))
                else:
                    stack.append(a)
                n_int += 1
            else:
                if n_flt < 4:
                    xmm_regs.append((a, n_flt, k))
                else:
                    stack.append(a)
                n_flt += 1
        extra = align(32 + 8 * len(stack), 16)
        enc.alu_ri("sub", RSP, extra)
        # 1) 栈实参（GPR 里就是位模式，直接存）
        for j, a in enumerate(stack):
            r = self.fetch(SCRATCH, a)
            enc.mov_mr(RSP, 4, 0, 32 + 8 * j, r)
        # 2) 浮点实参 -> XMM0-3（f64 走 movq，f32 走 movd）
        for a, x, k in xmm_regs:
            r = self.fetch(SCRATCH2, a)
            if k == "f32":
                enc.movd_xr(x, r)
            else:
                enc.movq_xr(x, r)
        # 3) 整数实参 -> RCX/RDX/R8/R9（并行搬移处理环）
        if int_regs:
            self.parallel_move([(self.src_move(a), ("r", WIN_ARG[i]))
                                for a, i in int_regs])
        self._call_api(sym, dll)
        enc.alu_ri("add", RSP, extra)
        if dst is None:
            return
        if ret == "f64":
            enc.movq_rx(ACC, 0)
        elif ret == "f32":
            enc.movd_rx(ACC, 0)
        elif ret == "bool":
            enc.trunc_reg(ACC, 32, False)      # BOOL 是 32 位，零扩展后当 bool
        self.commit(dst, ACC)

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
        if ins[0] == "ffi":
            self.gen_ffi(ins)
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
        self.gen_vtables()
        # v1.83：分支表的标签 -> .text 偏移（前向标签到这里才有位置）
        self._dbg_resolve_branches()
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

        # v1.87：导入项是 (dll|None, 符号) 二元组——@ffi 带显式 DLL 名，
        # 内置 winapi 调用仍按白名单归组（dll=None）。
        imports = list(dict.fromkeys(
            (dll, api) for _p, dll, api in self.api_fixups))
        # v1.62：函数 RVA = TEXT_RVA + 标签偏移（enc.labels 在 gen_functions
        # 里逐个登记）。调试器按 "PC - base" 反查落在哪个函数。
        for fd in self.dbg["funcs"]:
            fd["rva"] = TEXT_RVA + enc.labels[fd["name"]]
        return bytes(code), data, relocs, imports, self.api_fixups


# ---------------------------------------------------------------------------
# 导入表（多 DLL：kernel32 + ws2_32——v1.3 起支持原生 socket）
# ---------------------------------------------------------------------------

# ws2_32.dll 白名单：命中走 ws2_32，其余一律 kernel32
WS2_32_FUNCS = {"WSAStartup", "WSACleanup", "socket", "bind", "listen",
                "accept", "recv", "send", "sendto", "recvfrom",
                "closesocket", "inet_addr", "connect", "getaddrinfo",
                "freeaddrinfo", "getpeername", "getsockname",
                "htons", "ntohs", "setsockopt", "ioctlsocket",
                # v3.10：发送超时靠"先等可写再发"。SO_SNDTIMEO 在 Win32 上
                # 对 TCP 零窗口的阻塞发送**不生效**（实测 5 s 也不返回），
                # 只能自己 select。select 在标准库里是 ws2_32 的符号。
                "select"}


def _norm_dll(dll):
    """DLL 名规范化：`user32` -> `user32.dll`（加载器其实也会补，但导入表里
    写全名对 dumpbin/objdump 友好，且让"同一 DLL 两种写法"不会分成两组）。"""
    if "." not in dll:
        return dll + ".dll"
    return dll


def _resolve_dll(dll, name):
    """(dll|None, 符号) -> 真实 DLL 名。dll=None 走内置白名单。"""
    if dll:
        return _norm_dll(dll)
    return "ws2_32.dll" if name.startswith("WSA") or name in WS2_32_FUNCS \
        else "kernel32.dll"


def _dll_groups(imports):
    """[(dll|None, 函数名)] -> {dll 名: [函数名]}（保持首次出现顺序）。
    WSA* 前缀一律 ws2_32（WSAGetLastError 曾被漏归 kernel32 导致
    0xC0000139 ENTRYPOINT_NOT_FOUND，进程起不来）。"""
    groups = {}
    for dll, name in imports:
        groups.setdefault(_resolve_dll(dll, name), []).append(name)
    return groups


def build_idata(imports, rdata_rva):
    """多 DLL 导入表。每个 DLL 一个 {ILT, IAT} 对 + 结束哨兵描述符。
    imports: [(dll|None, 符号名)]
    返回 (rdata 内容, 0, dir_size, {(dll, 符号名): IAT 槽 RVA})"""
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
            iat_map[(dll, name)] = rdata_rva + iat_offs[dll] + 8 * j
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


def build_pe(code, data, reloc_offsets, imports, api_fixups, dbg=None,
             dwarf=None):
    code = bytearray(code)
    text_size = len(code)
    data = data or b"\x00" * 8

    data_rva = TEXT_RVA + align(text_size, SECT_ALIGN)
    rdata_rva = data_rva + align(len(data), SECT_ALIGN)

    rdata, imp_off, imp_size, iat = build_idata(imports, rdata_rva)
    reloc_rva = rdata_rva + align(len(rdata), SECT_ALIGN)

    # 回填 call [rip+disp32]：disp 相对下一条指令
    for patch, dll, api in api_fixups:
        disp = iat[(_resolve_dll(dll, api), api)] - (TEXT_RVA + patch + 4)
        struct.pack_into("<i", code, patch, disp)

    reloc = build_reloc(reloc_offsets, TEXT_RVA) if reloc_offsets else b""
    # v1.62：.qlmdbg 排在最后（.reloc 之后），不影响前面各节的 RVA 计算
    # v1.71：DWARF 四节再往后排（只影响 --dbg-info 构建的体积）
    extras = []                    # [(节名 bytes, 节体, 特征)]
    if dbg:
        extras.append((b".qlmdbg", dbg, SCN_DBG))
    for name, body in (dwarf or {}).items():
        extras.append((name.encode("ascii"), body, SCN_DWARF))

    # ---- 节表 ----
    # headers_size 必须把 section header 算进去，否则最后一节头会被 .text
    # 的 RawData 覆盖（已踩坑：入口跳到垃圾字节 -> 0xC0000096）。
    nsec = 3 + (1 if reloc else 0) + len(extras)
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

    next_rva = reloc_rva + align(len(reloc), SECT_ALIGN)
    for name, body, chars in extras:
        add_sec(name, next_rva, body, chars)
        next_rva += align(max(len(body), 1), SECT_ALIGN)

    size_of_image = align(secs[-1][2] + max(secs[-1][1], 1), SECT_ALIGN)
    # 所有非 .text 节的 RawData 之和（SizeOfInitializedData）
    init_size = sum(s[3] for s in secs[1:])

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

    # COFF 节名只有 8 字节；".debug_abbrev" 这类名字放不下，按 PE 规范
    # 写成 "/<字符串表偏移>"，真名进节尾的字符串表（MinGW 同款做法）。
    strtab = bytearray(b"\x00\x00\x00\x00")
    sect_hdr = b""
    for name, vsize, rva, raw_size, ptr, chars in secs:
        if len(name) <= 8:
            nm = name.ljust(8, b"\x00")
        else:
            nm = (b"/%d" % len(strtab)).ljust(8, b"\x00")
            strtab += name + b"\x00"
        sect_hdr += nm
        sect_hdr += struct.pack("<IIIIIIHHI", vsize, rva, raw_size, ptr,
                                0, 0, 0, 0, chars)

    pe = dos + b"\x00" * (HDR_DOS - len(dos)) + b"PE\x00\x00" + coff + bytes(o) + sect_hdr
    blob = bytearray(pe)
    blob += b"\x00" * (headers_size - len(blob))

    bodies = [bytes(code), data, rdata, reloc if reloc else b""]
    bodies += [body for _n, body, _c in extras]
    for (name, vsize, rva, raw_size, ptr, chars), body in zip(secs, bodies):
        blob += b"\x00" * (ptr - len(blob))
        blob += body
        blob += b"\x00" * (raw_size - len(body))

    if len(strtab) > 4:            # 只有长节名时才追加（默认构建逐字节不变）
        struct.pack_into("<I", strtab, 0, len(strtab))
        blob += strtab

    return bytes(blob)


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def transpile_win(src_path, dump_ir=False, optimize=True, dbg=False,
                  reuse=None, libs=None, meta=None):
    from qlm import load_config
    cfg = load_config(src_path)
    main_dir = os.path.dirname(os.path.abspath(src_path))
    asset_root = os.path.normpath(os.path.join(
        main_dir, cfg.get("src", {}).get("asset", "src/asset")))
    prog = None
    if dbg:
        # v1.62：调试信息走 qlm_dbinfo 的行号加载器（parse_stmt 钩子 +
        # 主文件函数名集），不改共享 parser 文件
        import qlm_dbinfo
        prog = qlm_dbinfo.load_program_dbg(src_path, cfg)
    fns, low, cfg = lower_and_optimize(src_path, optimize=optimize,
                                       dump_ir=dump_ir, platform="windows",
                                       asset_root=asset_root, prog=prog,
                                       reuse=reuse, libs=libs, meta=meta)
    cg = WinCodegen(fns, low.globals, low=low)   # vtable 需要 low.vtables
    code, data, relocs, imports, api_fixups = cg.gen_all_pe()
    dbg_blob = None
    dwarf = None
    if dbg:
        import qlm_dbinfo
        import qlm_dwarf
        layout = low.dbg_struct_layout()
        dbg_blob = qlm_dbinfo.serialize_dbg(cg.dbg, src_path, layout)
        # v1.71：同一份调试表再编码一份标准 DWARF v4（供外部工具消费）
        dwarf = qlm_dwarf.build(cg.dbg, src_path, layout, TEXT_RVA, len(code))
    pe = build_pe(code, data, relocs, imports, api_fixups, dbg=dbg_blob,
                  dwarf=dwarf)
    return pe, cfg


def emit_archive(src_path, optimize=True, kind="program", unit=None,
                 libs=None, reuse=None):
    """v2.03：编译到 `.qla` 目标文件（不发射机器码）。

    kind="lib"：库没有入口，**不做 DCE**，全部函数与类型表都进档案，
    源码可以不再分发（使用方只需要档案里的签名与布局）。
    reuse：上一版档案——按函数哈希复用它的 IR（函数级增量）。
    """
    import qlm_qla
    meta = {}
    _fns, _low, cfg = lower_and_optimize(
        src_path, optimize=optimize, platform="windows",
        asset_root=_asset_root_of(src_path),
        keep_all=(kind == "lib"), libs=libs, reuse=reuse, meta=meta)
    if unit is None:
        unit = os.path.splitext(os.path.basename(src_path))[0]
    arc = qlm_qla.archive_from_meta(meta, unit, kind=kind, arch="x86_64",
                                    platform="windows", opt=optimize)
    arc.unit = unit
    return arc, meta, cfg


def _asset_root_of(src_path):
    from qlm import load_config
    cfg = load_config(src_path)
    main_dir = os.path.dirname(os.path.abspath(src_path))
    return os.path.normpath(os.path.join(
        main_dir, cfg.get("src", {}).get("asset", "src/asset")))


def link_win(arcs, unit=None):
    """v2.03：链接多份 `.qla` -> PE 可执行文件（IR 级链接）。

    符号按名字解析（`call` / `fnaddr` / vtable 槽），全局区按单元基址拼接，
    运行库 helper 同名去重——全进程一个堆、一份空闲链。
    """
    import qlm_qla
    link = qlm_qla.merge(arcs, unit=unit)
    qlm_qla.check_resolved(link)
    cg = WinCodegen(link.funcs, link.globals, low=link.low())
    code, data, relocs, imports, api_fixups = cg.gen_all_pe()
    pe = build_pe(code, data, relocs, imports, api_fixups)
    return pe, link


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
