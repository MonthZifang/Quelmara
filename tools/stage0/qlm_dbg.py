#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quelmara 源码级调试器（stage-0 工具链，v1.62）

调试器链路第二段：读 PE 的 .qlmdbg 调试节，用 Windows 调试 API 提供
源码断点 / 单步 / 变量查看 / 调用栈。与 qlm_dbinfo（编译期发射调试信息）
配对使用；不依赖任何外部工具（无 gdb / 无 capstone / 无 WinDbg）。

用法：
  python tools/stage0/qlm_dbg.py build/x.exe              # 交互
  python tools/stage0/qlm_dbg.py build/x.exe --script f   # 脚本（测试用）
  python tools/stage0/qlm_dbg.py build/x.exe -- a b       # 传参给被调试程序

命令：
  break FILE:LINE / break FUNC   下断点（源码行 / 函数入口）
  run / continue / c             继续
  step / s                       单步进入（行粒度）
  next / n                       单步跨过（不进调用）
  finish / f                     运行到当前函数返回
  print EXPR / p EXPR            变量求值（name / a.b.c）
  locals                         当前帧全部存活变量
  bt                             调用栈（RBP 链）
  list [LINE]                    看源码（默认当前行附近）
  info break                     断点列表
  delete N                       删除断点
  quit / q                       结束

自研边界（v1.62）：
  * 调试信息是自研 .qlmdbg 节（JSON：行表 + 变量位置表 + 结构体布局），
    不是 DWARF/PDB；只支持 Windows PE 产物（ELF 后端未接）。
    同一次构建还会发一份标准 DWARF v4（.debug_* 四节，见 qlm_dwarf），
    供外部工具读；调试器自己只读 .qlmdbg（它带活跃区间，DWARF 的
    location list 是同一份数据的标准编码）。
  * 变量位置 = 线性扫描分配结果（寄存器号或 [rbp-off] 帧槽）；生命周期
    之外的变量报"已超出生命周期"，不显示被复用的过期值。
  * 调试构建（--dbg-info）默认不内联：内联会让源码行落进调用者函数体、
    独立函数体变死代码，断点静默不命中。
  * import 的库函数帧无源码行号（行号属于别的文件），显示 <library>。
  * 内联帧：行表可能落在被内联函数的行上（物理帧是调用者），bt 按物理
    帧走 RBP 链。
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import struct
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------------------
# Windows 调试 API 常量
# ---------------------------------------------------------------------------
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
DEBUG_ONLY_THIS_PROCESS = 0x00000002
EXCEPTION_DEBUG_EVENT = 1
CREATE_THREAD_DEBUG_EVENT = 2
CREATE_PROCESS_DEBUG_EVENT = 3
EXIT_THREAD_DEBUG_EVENT = 4
EXIT_PROCESS_DEBUG_EVENT = 5
LOAD_DLL_DEBUG_EVENT = 6
STATUS_BREAKPOINT = 0x80000003
STATUS_SINGLE_STEP = 0x80000004
CONTEXT_AMD64 = 0x00100000
CONTEXT_INTEGER = CONTEXT_AMD64 | 0x1
CONTEXT_CONTROL = CONTEXT_AMD64 | 0x2
CONTEXT_DEBUG_REGISTERS = CONTEXT_AMD64 | 0x10
# 只要 整数 + 控制（ Rip/Rsp/EFlags ）。**不要** DEBUG_REGISTERS：本调试器
# 用 int3 软断点，不需要硬件断点；而实测布局里 Dr0-Dr7 在 Rip 之后，
# 请求它会让内核把调试寄存器写到结构体尾部之外——堆溢出（Python 段错误）
# 且 SetThreadContext 会把缓冲区垃圾写进线程硬件断点（被调试进程
# 0xC0000005）。v1.62 实测踩坑，记此牢。
CONTEXT_FLAGS = CONTEXT_INTEGER | CONTEXT_CONTROL
THREAD_GET_CONTEXT = 0x0008
THREAD_SET_CONTEXT = 0x0010
STACK_GUARD = (0x10000, 0x0000800000000000)   # 用户态栈的合理区间


class EXCEPTION_RECORD(ctypes.Structure):
    _fields_ = [("ExceptionCode", wt.DWORD), ("ExceptionFlags", wt.DWORD),
                ("ExceptionRecord", ctypes.c_void_p),
                ("ExceptionAddress", ctypes.c_void_p),
                ("NumberParameters", wt.DWORD),
                ("ExceptionInformation", ctypes.c_ulonglong * 15)]


class EXCEPTION_DEBUG_INFO(ctypes.Structure):
    _fields_ = [("ExceptionRecord", EXCEPTION_RECORD),
                ("dwFirstChance", wt.DWORD)]


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [("dwDebugEventCode", wt.DWORD), ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD), ("_pad", wt.DWORD),
                ("u", ctypes.c_byte * 160)]


class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR),
                ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD),
                ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


class CONTEXT(ctypes.Structure):
    """x64 CONTEXT。

    偏移是**本机实测校准**的，不是照抄资料：调试事件自带异常地址
    （= 真实 RIP），在 GetThreadContext 缓冲区里反查它的落点，再写
    16 个不同魔数 Set+Get 回显逐一定位 GPR。实测结论（Win10/11 x64）：

        ContextFlags=0x30  MxCsr=0x34  SegCs..SegSs=0x38  EFlags=0x44
        Rax..R15 = 0x78..0xF0      Rip = 0xF8

    与部分资料所写（GPR 0x88 起、Rip 0x108）相差 0x10——按错的布局
    SetThreadContext 会把"回退 RIP"写进真实 R14，线程从 int3 之后
    继续执行、跳过一条指令，结果静默算错（v1.62 开发期实测踩到）。
    因此 _on_breakpoint 每次都会校验读到的 Rip == bp+1，不符即
    fail-fast，绝不静默写错寄存器。0x48-0x77 是本工具不用的调试
    寄存器区，占位保持偏移正确。"""
    _fields_ = [
        ("P1Home", ctypes.c_ulonglong), ("P2Home", ctypes.c_ulonglong),
        ("P3Home", ctypes.c_ulonglong), ("P4Home", ctypes.c_ulonglong),
        ("P5Home", ctypes.c_ulonglong), ("P6Home", ctypes.c_ulonglong),
        ("ContextFlags", ctypes.c_ulong), ("MxCsr", ctypes.c_ulong),
        ("SegCs", ctypes.c_ushort), ("SegDs", ctypes.c_ushort),
        ("SegEs", ctypes.c_ushort), ("SegFs", ctypes.c_ushort),
        ("SegGs", ctypes.c_ushort), ("SegSs", ctypes.c_ushort),
        ("EFlags", ctypes.c_ulong),
        ("_dr", ctypes.c_ulonglong * 6),
        ("Rax", ctypes.c_ulonglong), ("Rcx", ctypes.c_ulonglong),
        ("Rdx", ctypes.c_ulonglong), ("Rbx", ctypes.c_ulonglong),
        ("Rsp", ctypes.c_ulonglong), ("Rbp", ctypes.c_ulonglong),
        ("Rsi", ctypes.c_ulonglong), ("Rdi", ctypes.c_ulonglong),
        ("R8", ctypes.c_ulonglong), ("R9", ctypes.c_ulonglong),
        ("R10", ctypes.c_ulonglong), ("R11", ctypes.c_ulonglong),
        ("R12", ctypes.c_ulonglong), ("R13", ctypes.c_ulonglong),
        ("R14", ctypes.c_ulonglong), ("R15", ctypes.c_ulonglong),
        ("Rip", ctypes.c_ulonglong),
        # 尾部补足到 sizeof(CONTEXT)=1232（winnt.h x64）。即使以后有人
        # 把 CONTEXT_FLAGS 改回含 DEBUG_REGISTERS，Dr0-Dr7 也落在缓冲区内
        # 而不是堆外——见 CONTEXT_FLAGS 处的牢事记录。
        ("_tail", ctypes.c_ulonglong * ((1232 - 0x100) // 8)),
    ]


REG_NAMES = ["Rax", "Rcx", "Rdx", "Rbx", "Rsp", "Rbp", "Rsi", "Rdi",
             "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15"]

TF_FLAG = 0x100          # EFlags 陷阱标志（单步）
MAX_STEPS = 200000       # 单次继续里允许的单步上限（防在库里逐指令爬死）
TEXT_RVA = 0x1000        # 与 qlm_pe.TEXT_RVA 同源：.qlmdbg 的偏移是 .text 相对的


# ---------------------------------------------------------------------------
# PE 解析：节表 + .qlmdbg 调试节 + 镜像基址
# ---------------------------------------------------------------------------

def parse_pe(path):
    """返回 (image_base, sections)；sections = {名字: (vsize, rva, rawsize, ptr)}"""
    data = open(path, "rb").read()
    if data[:2] != b"MZ":
        raise RuntimeError(f"{path}: 不是 PE 文件")
    e = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e:e + 4] != b"PE\x00\x00":
        raise RuntimeError(f"{path}: 缺少 PE 签名")
    coff = e + 4
    nsec = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    magic = struct.unpack_from("<H", data, coff + 20)[0]
    if magic != 0x20B:
        raise RuntimeError(f"{path}: 不是 PE32+（magic=0x{magic:x}）")
    image_base = struct.unpack_from("<Q", data, coff + 20 + 24)[0]
    secs = {}
    entries = []
    for i in range(nsec):
        off = coff + 20 + opt_size + 40 * i
        name = data[off:off + 8].rstrip(b"\x00").decode("ascii", "replace")
        vsize, rva, rawsize, ptr = struct.unpack_from("<IIII", data, off + 8)
        entries.append((name, vsize, rva, rawsize, ptr))
    # 长节名（v1.71 的 .debug_abbrev 等）按 PE 规范存成 "/<字符串表偏移>"，
    # 真名在最后一节之后的字符串表里（4 字节总长 + 若干 NUL 结尾串）。
    if any(e[0].startswith("/") and e[0][1:].isdigit() for e in entries):
        strtab = max(e[4] + e[3] for e in entries)
        resolved = []
        for name, vsize, rva, rawsize, ptr in entries:
            if name.startswith("/") and name[1:].isdigit():
                at = strtab + int(name[1:])
                end = data.index(b"\x00", at)
                name = data[at:end].decode("ascii", "replace")
            resolved.append((name, vsize, rva, rawsize, ptr))
        entries = resolved
    for name, vsize, rva, rawsize, ptr in entries:
        secs[name] = (vsize, rva, rawsize, ptr)
    return image_base, secs, data


def load_debug_info(path):
    """读 .qlmdbg 节并解析为调试器可用的索引。"""
    image_base, secs, data = parse_pe(path)
    if ".qlmdbg" not in secs:
        raise RuntimeError(
            f"{path}: 没有 .qlmdbg 调试节——请用 --dbg-info 构建"
            f"（quelmara build --dbg-info <src>）")
    vsize, rva, rawsize, ptr = secs[".qlmdbg"]
    dbg = json.loads(data[ptr:ptr + vsize].decode("utf-8"))
    if dbg.get("version") != 1:
        raise RuntimeError(f".qlmdbg 版本不支持: {dbg.get('version')}")
    # 按 RVA 排序的函数表（bt / 反查当前函数用）
    funcs = sorted(dbg["funcs"], key=lambda f: f["rva"])
    return image_base, secs, dbg, funcs


# ---------------------------------------------------------------------------
# 调试器
# ---------------------------------------------------------------------------

class DbgError(Exception):
    pass


class Debugger:
    def __init__(self, exe, prog_args, script=None):
        self.exe = os.path.abspath(exe)
        self.prog_args = prog_args
        self.script = script            # 脚本命令列表（None = 交互）
        self.script_i = 0
        self.errors = 0
        self.image_base, self.secs, self.dbg, self.funcs = \
            load_debug_info(self.exe)
        self.h_process = None
        self.h_thread = None
        self._threads = {}              # tid -> 线程句柄（见 thread_handle）
        self._steps = 0                 # 本次继续里的单步计数（MAX_STEPS 护栏）
        self.pid = self.tid = 0
        self.ev = DEBUG_EVENT()
        self.running = False
        self.exit_code = None
        # 断点：rva -> {"orig": byte, "hits": int, "n": 序号}
        self.bps = {}
        self.bp_seq = 0
        self.stop_reason = None         # "bp" | "step" | "exit" | None
        self.stop_rva = 0
        self.step_mode = None           # None | "step" | "next" | "finish"
        self.step_line = None
        self.step_depth = 0
        self.step_fn = None             # 起点的物理函数名（见 _on_single_step）
        self.pending_rearm = []         # 断点重贴清单（单步跨过原指令后）
        self._pending = None            # (pid, tid, status) 待继续的事件
        self._src_cache = {}

    # ---- 基础输出 ----
    def out(self, msg):
        print(f"[dbg] {msg}")

    def err(self, msg):
        self.errors += 1
        print(f"[dbg] error: {msg}")

    # ---- 进程/线程/内存 ----
    def start(self):
        si = STARTUPINFO()
        si.cb = ctypes.sizeof(si)
        pi = PROCESS_INFORMATION()
        cmd = " ".join([self.exe] + self.prog_args)
        ok = k32.CreateProcessW(None, cmd, None, None, False,
                                DEBUG_ONLY_THIS_PROCESS, None, None,
                                ctypes.byref(si), ctypes.byref(pi))
        if not ok:
            raise DbgError(f"CreateProcess 失败: {ctypes.get_last_error()}")
        self.h_process = pi.hProcess
        self.pid = pi.dwProcessId
        self.running = True

    def thread_handle(self, tid):
        """线程句柄按 tid 缓存。

        单步一步要做 4~6 次 Get/SetThreadContext；每次都 OpenThread +
        CloseHandle 的话，句柄表操作比内核真正读写上下文还贵（实测每
        源码行 3.7 ms，缓存后降到 1 ms 量级）。句柄在 cleanup 里统一关。
        """
        h = self._threads.get(tid)
        if h:
            return h
        h = k32.OpenThread(THREAD_GET_CONTEXT | THREAD_SET_CONTEXT, False, tid)
        if not h:
            raise DbgError(f"OpenThread({tid}) 失败: {ctypes.get_last_error()}")
        self._threads[tid] = h
        return h

    def get_context(self, tid):
        h = self.thread_handle(tid)
        ctx = CONTEXT()
        ctx.ContextFlags = CONTEXT_FLAGS
        if not k32.GetThreadContext(h, ctypes.byref(ctx)):
            raise DbgError(f"GetThreadContext 失败: {ctypes.get_last_error()}")
        return ctx

    def set_context(self, tid, ctx):
        h = self.thread_handle(tid)
        if not k32.SetThreadContext(h, ctypes.byref(ctx)):
            raise DbgError(f"SetThreadContext 失败: {ctypes.get_last_error()}")

    def read_mem(self, addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.h_process, ctypes.c_void_p(addr),
                                     buf, n, ctypes.byref(got)):
            return None
        return buf.raw[:got.value]

    def read_u64(self, addr):
        d = self.read_mem(addr, 8)
        return None if d is None or len(d) < 8 else struct.unpack("<Q", d)[0]

    def write_mem(self, addr, data):
        buf = ctypes.create_string_buffer(data)
        got = ctypes.c_size_t()
        if not k32.WriteProcessMemory(self.h_process, ctypes.c_void_p(addr),
                                      buf, len(data), ctypes.byref(got)):
            raise DbgError(f"WriteProcessMemory(0x{addr:x}) 失败: "
                           f"{ctypes.get_last_error()}")
        k32.FlushInstructionCache(self.h_process, ctypes.c_void_p(addr),
                                  len(data))

    # ---- 源码位置 ----
    def fn_at(self, rva):
        """RVA 落在哪个函数（物理帧）"""
        best = None
        for f in self.funcs:
            if f["rva"] <= rva:
                best = f
            else:
                break
        return best

    def line_at(self, fn, rva):
        """函数内 <= rva 的最后一个行表项 -> (line, entry_rva)。

        同一代码偏移可能有多个行号（语句首指令 + 被内联函数的行）：
        取**第一条**——它是用户写下这条语句的位置（break 35 不该
        因为同偏移的内联行显示成 12）。"""
        if not fn or not fn.get("file") or not fn["lines"]:
            return None, None
        best = None
        best_off = -1
        for off, line in fn["lines"]:
            e = off + TEXT_RVA
            if e <= rva and e > best_off:
                best_off = e
                best = (line, e)
        return best if best else (None, None)

    def src_line(self, path, n):
        if path not in self._src_cache:
            for cand in (path,
                         os.path.join(os.path.dirname(self.exe), path),
                         os.path.join(os.path.dirname(self.exe),
                                      os.path.basename(path))):
                try:
                    with open(cand, encoding="utf-8") as f:
                        self._src_cache[path] = f.read().splitlines()
                    break
                except OSError:
                    continue
            else:
                self._src_cache[path] = None
        lines = self._src_cache[path]
        if lines is None or not (1 <= n <= len(lines)):
            return "<source unavailable>"
        return lines[n - 1].rstrip()

    def where(self, rva):
        """当前位置的人类可读描述 -> (file, line, fn)"""
        fn = self.fn_at(rva)
        if fn is None:
            # 镜像内但不在任何函数里：入口桩（gen_entry）等合成代码
            if 0 < rva < (self.funcs[0]["rva"] if self.funcs else 0):
                return None, None, "<entry>"
            return None, None, None
        if fn.get("file"):
            line, _e = self.line_at(fn, rva)
            return fn["file"], line, fn["name"]
        return None, None, fn["name"]

    def print_where(self, rva):
        f, line, name = self.where(rva)
        if f and line:
            self.out(f"stopped: {f}:{line} in {name}()")
            self.out(f"  {line}| {self.src_line(f, line)}")
        elif name and f:
            # 有文件名但行号未到：函数入口（序言里，第一条语句标记之前）
            self.out(f"stopped: {f} in {name}() (入口，首条语句未执行)")
        elif name:
            self.out(f"stopped: <library> in {name}() (rva 0x{rva:x})")
        else:
            self.out(f"stopped: rva 0x{rva:x}（无调试信息）")

    # ---- 断点 ----
    def set_bp(self, rva, desc, temp=False, silent=False):
        """下断点。temp=True 是内部临时断点（next/finish 用），命中后自动摘除；
        silent=True 表示命中时不停下（用于"跳过整个被调函数"）。"""
        if rva in self.bps:
            self.err(f"断点已存在: {desc} (rva 0x{rva:x})")
            return False
        orig = self.read_mem(self.image_base + rva, 1)
        if orig is None:
            self.err(f"地址不可读: rva 0x{rva:x}")
            return False
        self.write_mem(self.image_base + rva, b"\xCC")
        self.bp_seq += 1
        self.bps[rva] = {"orig": orig[0], "hits": 0, "n": self.bp_seq,
                         "desc": desc, "temp": temp, "silent": silent}
        if not temp:
            self.out(f"breakpoint {self.bp_seq}: {desc} -> rva 0x{rva:x}")
        return True

    def del_bp(self, n):
        for rva, bp in list(self.bps.items()):
            if bp["n"] == n:
                if self.running:
                    self.write_mem(self.image_base + rva,
                                   bytes([bp["orig"]]))
                del self.bps[rva]
                self.out(f"deleted breakpoint {n}")
                return
        self.err(f"没有断点 {n}")

    # ---- 单步控制 ----
    def set_trap(self, tid, on):
        ctx = self.get_context(tid)
        if on:
            ctx.EFlags |= TF_FLAG
        else:
            ctx.EFlags &= ~TF_FLAG
        self.set_context(tid, ctx)

    # ---- 帧链（RBP 链：本站帧有 push rbp; mov rbp,rsp）----
    # 注意：序言在 push rbp 之前还压了 used_callee 个被调用者保存寄存器
    # （线程入口再多 RDI/RSI 两个）。push 计数含 rbp 那一下，布局自 rbp
    # 向上： [rbp]=调用方 rbp，随后是各被压寄存器，返回地址在
    # [rbp + 8*push]（无被调保存寄存器时 push=1，即标准 [rbp+8]）。
    # 每个函数的 push 数由 .qlmdbg 的 "push" 字段给出（codegen 侧按
    # used_callee 实测登记）。
    def frame_chain(self, tid, start_fn=None):
        ctx = self.get_context(tid)
        rbp = ctx.Rbp
        frames = []
        fn = start_fn or self.fn_at(ctx.Rip - self.image_base)
        for _ in range(64):
            if not (STACK_GUARD[0] < rbp < STACK_GUARD[1]):
                break
            n = (fn or {}).get("push", 1)
            ret = self.read_u64(rbp + 8 * n)
            nxt = self.read_u64(rbp)
            if ret is None or nxt is None:
                break
            frames.append(ret)
            if nxt <= rbp:
                break
            rbp = nxt
            fn = self.fn_at(ret - self.image_base)
        return frames

    def frame_depth(self, tid):
        return len(self.frame_chain(tid))

    # ---- 事件循环 ----
    def resume(self, mode):
        """继续执行直到用户可见的停止。

        mode: None=继续 | "step" | "next" | "finish"
        返回 stop_reason: "bp" | "step" | "exit"
        """
        if not self.running:
            self.err("进程已退出")
            return "exit"
        tid0 = self.tid
        self._steps = 0
        # 有断点被"吃掉"但还没贴回（单步正好落在断点地址上）时，必须先走完
        # 那一步重贴再继续，否则那条断点会永久消失（TF 已被 CPU 清掉，
        # 不主动打开的话原指令会一路执行过去）。
        if self.pending_rearm:
            self.set_trap(tid0, True)
        if mode == "finish":
            # finish 快路径：在返回地址下临时断点直接跑过去，不逐指令单步
            ctx = self.get_context(tid0)
            fn = self.fn_at(ctx.Rip - self.image_base)
            n = (fn or {}).get("push", 1)
            ret = self.read_u64(ctx.Rbp + 8 * n)
            if ret:
                ret_rva = ret - self.image_base
                if 0 < ret_rva < (1 << 24):
                    if ret_rva not in self.bps:
                        self.set_bp(ret_rva, "<temp:finish>", temp=True)
                    self.step_mode = None
                    return self._go()
            # 读不到返回地址（帧链异常）→ 退回逐指令单步
        if mode in ("step", "next", "finish"):
            ctx = self.get_context(tid0)
            self.step_mode = mode
            self.step_line = self._cur_line(ctx)
            self.step_depth = self.frame_depth(tid0)
            self.step_fn = (self.fn_at(ctx.Rip - self.image_base) or {}).get("name")
            self.set_trap(tid0, True)
        else:
            self.step_mode = None
        return self._go()

    def _cur_line(self, ctx):
        rva = ctx.Rip - self.image_base
        _f, line, _n = self.where(rva)
        return line

    def _go(self):
        while True:
            if self._pending is not None:
                pid, tid, status = self._pending
                self._pending = None
                k32.ContinueDebugEvent(pid, tid, status)
            if not k32.WaitForDebugEvent(ctypes.byref(self.ev), 20000):
                err = ctypes.get_last_error()
                if err == 121:        # ERROR_SEM_TIMEOUT
                    continue
                raise DbgError(f"WaitForDebugEvent 失败: {err}")
            code = self.ev.dwDebugEventCode
            pid, tid = self.ev.dwProcessId, self.ev.dwThreadId
            self.tid = tid          # 当前线程 = 交付最后一个事件的线程
            if code == CREATE_PROCESS_DEBUG_EVENT:
                base = ctypes.c_void_p.from_buffer(self.ev.u, 24).value or 0
                self.image_base = base
                self.out(f"process started pid={pid} base=0x{base:X}")
            elif code == EXIT_PROCESS_DEBUG_EVENT:
                self.exit_code = wt.DWORD.from_buffer(self.ev.u, 0).value
                self.running = False
                self.stop_reason = "exit"
                self._pending = (pid, tid, DBG_CONTINUE)
                return "exit"
            elif code == EXCEPTION_DEBUG_EVENT:
                info = ctypes.cast(ctypes.byref(self.ev.u),
                                   ctypes.POINTER(EXCEPTION_DEBUG_INFO)).contents
                rec = info.ExceptionRecord
                addr = rec.ExceptionAddress or 0
                if rec.ExceptionCode == STATUS_BREAKPOINT:
                    stop = self._on_breakpoint(addr, tid)
                    if stop is not None:
                        self.stop_reason, self.stop_rva = stop
                        self._pending = (pid, tid, DBG_CONTINUE)
                        return stop[0]
                elif rec.ExceptionCode == STATUS_SINGLE_STEP:
                    stop = self._on_single_step(tid)
                    if stop is not None:
                        self.stop_reason, self.stop_rva = stop
                        self._pending = (pid, tid, DBG_CONTINUE)
                        return stop[0]
                else:
                    # 真实异常：如实报告，交回进程（不吞）
                    rva = addr - self.image_base if addr else 0
                    f, line, name = self.where(rva)
                    loc = f"{f}:{line}" if f and line else f"rva 0x{rva:x}"
                    self.out(f"exception code=0x{rec.ExceptionCode & 0xffffffff:08X} "
                             f"at {loc} in {name or '?'}()")
                    self._pending = (pid, tid, DBG_EXCEPTION_NOT_HANDLED)
                    return "exit"
            # 其余事件（线程/DLL/调试串）：直接继续
            self._pending = (pid, tid, DBG_CONTINUE)

    def _on_breakpoint(self, addr, tid):
        """返回 None=不是用户断点（继续）；("bp", rva)=用户断点停下"""
        rva = addr - self.image_base
        bp = self.bps.get(rva)
        if bp is None:
            return None              # 初始断点（ntdll）等：继续
        # 回退 RIP、恢复原字节、单步跨过、再重贴。
        # int3 是 1 字节、只覆盖目标指令首字节：陷阱保存的 RIP = addr+1，
        # 要重执行原指令必须把 RIP 设回 **addr**（不是 addr-1——那会从
        # 上一条指令的中间字节开始解码，静默算错或 0xC0000005）。
        ctx = self.get_context(tid)
        # CONTEXT 布局校验：int3 陷阱保存的 RIP 必然是 bp+1。读到别的值
        # 说明结构体偏移和这台机器的内核不一致——此时若继续写上下文会
        # 静默破坏线程状态。fail-fast。
        if ctx.Rip != addr + 1:
            raise DbgError(
                f"CONTEXT 布局校验失败：读到 Rip=0x{ctx.Rip:X}，"
                f"期望 0x{addr + 1:X}（断点地址+1）；"
                f"本机 CONTEXT 偏移与 qlm_dbg 的实测假设不一致")
        ctx.Rip = addr
        self.set_context(tid, ctx)
        self.write_mem(addr, bytes([bp["orig"]]))
        bp["hits"] += 1
        temp = bp.get("temp")
        silent = bp.get("silent")
        self.pending_rearm.append((rva, not temp))
        if temp:
            del self.bps[rva]
        self.set_trap(tid, True)
        if silent:
            return None              # 内部跳过用：不停下，接着走
        return ("bp", rva)

    def _absorb_bp_at(self, rva):
        """单步正好落到一个断点地址上：把这次命中就地"吃掉"。

        单步走到的地址若已被 int3 覆盖，字节还留在那儿——下一次 continue
        会立刻再触发一次断点，`finish`/`next` 会看起来"原地没动"（实测：
        next 停在断点行之后，finish 直接停回同一行）。这里恢复原字节、
        登记重贴、命中数 +1，后续继续就按正常单步/继续走。"""
        bp = self.bps.get(rva)
        if bp is None:
            return
        self.write_mem(self.image_base + rva, bytes([bp["orig"]]))
        self.pending_rearm.append((rva, not bp.get("temp")))
        bp["hits"] += 1
        if bp.get("temp"):
            del self.bps[rva]

    def _skip_callee(self, tid, ctx, rva):
        """在被调函数的返回地址下临时断点，然后关掉单步跑过去。

        `next` 逐指令单步穿过被调函数的话，一次 `print` 就要走几千条
        指令（实测每步 3.8 ms × 上千步 = 数秒）。标准做法是"步过调用"：
        在返回地址上放临时断点，命中即静默摘除、恢复单步。"""
        fn = self.fn_at(rva)
        n = (fn or {}).get("push", 1)
        ret = self.read_u64(ctx.Rbp + 8 * n)
        if not ret:
            return False
        ret_rva = ret - self.image_base
        if not (0 < ret_rva < (1 << 24)):
            return False
        if ret_rva not in self.bps:
            self.set_bp(ret_rva, "<temp:skip>", temp=True, silent=True)
        self.set_trap(tid, False)
        return True

    def _on_single_step(self, tid):
        self._steps += 1
        if self._steps > MAX_STEPS:
            raise DbgError(
                f"单步超过 {MAX_STEPS} 条指令仍未离开当前行"
                f"（可能走进了库/入口桩）；已中止本次继续，请用 break 定位")
        if self.pending_rearm:
            # 断点重贴步：原指令已执行，按需贴回 0xCC（临时断点不贴）
            rva, repatch = self.pending_rearm.pop()
            if repatch:
                self.write_mem(self.image_base + rva, b"\xCC")
            if self.step_mode is None:
                return None          # 用户只要继续：接着跑
            self.set_trap(tid, True)  # 用户要单步：这一步只是重贴，继续单步
            return None
        ctx = self.get_context(tid)
        rva = ctx.Rip - self.image_base
        fn_now = (self.fn_at(rva) or {}).get("name")
        # 帧深度在**序言/尾声**里不可靠：尾声先 `leave`（恢复 rbp）再 `ret`，
        # 那一刻还没离开本函数，帧链却已经少了一层。所以"是否已回到调用者"
        # 必须同时看"物理函数变了"——只看深度会让 finish 停在 `return` 那行。
        left_fn = fn_now != self.step_fn
        if self.step_mode == "step":
            # 行粒度：单步到**行号变化**或**进入/离开函数**才停
            # （一条语句含多条指令；只停一条指令看起来"没动"）
            line = self._cur_line(ctx)
            if line != self.step_line or left_fn:
                self.step_mode = None
                self._absorb_bp_at(rva)
                return ("step", rva)
            self.set_trap(tid, True)
            return None
        if self.step_mode == "next":
            line = self._cur_line(ctx)
            if line != self.step_line and not left_fn:
                self.step_mode = None
                self._absorb_bp_at(rva)
                return ("step", rva)
            if left_fn:
                # 函数变了：要么是"返回到了调用者"，要么是"步进了被调函数"
                if self.frame_depth(tid) < self.step_depth:
                    self.step_mode = None
                    self._absorb_bp_at(rva)
                    return ("step", rva)
                if self._skip_callee(tid, ctx, rva):
                    return None      # 临时断点 + 关单步，跑完被调函数再说
            self.set_trap(tid, True)
            return None
        if self.step_mode == "finish":
            if left_fn and self.frame_depth(tid) < self.step_depth:
                self.step_mode = None
                self._absorb_bp_at(rva)
                return ("step", rva)
            self.set_trap(tid, True)
            return None
        self.step_mode = None
        return ("step", rva)

    # ---- 变量求值 ----
    def stopped(self):
        """是否停在"上下文可用"的位置。

        入口停点（初始断点）不行：该停止点读到的上下文 Rip=0（内核对
        初始断点返回的整数上下文不完整），任何上下文读写都不安全——
        step/print/bt 一律要求先 run 到真实断点。"""
        return self.running and self.stop_reason in ("bp", "step")

    def _live_vars(self, fn, rva):
        """当前 PC 处存活的最新绑定。

        可用条件：绑定偏移 **不晚于** 当前 PC（dbgvar 标记在绑定 mov
        之后，bind <= PC 即"赋值已发生"；let 自己那条行上 PC 在 mov
        之前 -> 不可用，报了反而是错值）。生命周期之后的（last 早于
        PC）标 <dead>，不显示被复用的过期值。"""
        best = {}
        for v in fn["vars"]:
            if v["bind"] + TEXT_RVA > rva:
                continue
            if rva > v["last"] + TEXT_RVA:
                continue
            cur = best.get(v["name"])
            if cur is None or v["bind"] >= cur["bind"]:
                best[v["name"]] = v
        return best

    def read_var(self, v, ctx):
        """变量当前位置的值 -> (kind, extra, raw)"""
        loc = v["loc"]
        if loc[0] == "r":
            val = getattr(ctx, REG_NAMES[loc[1]])
        else:
            val = self.read_u64(ctx.Rbp - loc[1])
            if val is None:
                raise DbgError(f"帧槽不可读 [rbp-0x{loc[1]:x}]")
        return v["kind"], v["s"], val

    def field_kind(self, fty):
        if fty in self.dbg["structs"]:
            return ("struct", fty)
        if fty == "str":
            return ("str", None)
        if fty == "bool":
            return ("bool", None)
        if fty == "f64":
            return ("f64", None)
        if fty == "f32":
            return ("f32", None)
        if fty == "slice":
            return ("slice", None)
        return ("int", None)

    def fmt_value(self, kind, extra, val, depth=0):
        val &= 0xFFFFFFFFFFFFFFFF
        if kind == "int":
            s = val - (1 << 64) if val >= (1 << 63) else val
            return f"{s} (0x{val:x})"
        if kind == "bool":
            return "true" if val else "false"
        if kind in ("f64", "f32"):
            f = "<d" if kind == "f64" else "<f"
            return repr(struct.unpack(f, struct.pack("<Q", val))[0])
        if kind == "str":
            ln = self.read_u64(val - 8)
            if ln is None or ln > (1 << 20):
                return f"<bad str 0x{val:x}>"
            data = self.read_mem(val, ln) if ln else b""
            if data is None:
                return "<unreadable str>"
            return '"' + data.decode("utf-8", "replace") + '"'
        if kind == "struct":
            return self.fmt_struct(extra, val, depth)
        if kind == "slice":
            p = self.read_u64(val)
            n = self.read_u64(val + 8)
            return f"slice{{ptr=0x{p:x}, len={n}}}" if p is not None \
                else "<unreadable slice>"
        return f"0x{val:x}"

    def fmt_struct(self, sname, addr, depth):
        lay = self.dbg["structs"].get(sname)
        if lay is None or depth > 4:
            return f"{sname}@0x{addr:x}"
        parts = []
        for fname, fty, woff in lay["fields"]:
            raw = self.read_u64(addr + woff * 8)
            if raw is None:
                parts.append(f"{fname}=<unreadable>")
                continue
            kind, extra = self.field_kind(fty)
            if kind == "struct":
                parts.append(f"{fname}={self.fmt_struct(extra, raw, depth + 1)}")
            else:
                parts.append(f"{fname}={self.fmt_value(kind, extra, raw, depth + 1)}")
        return f"{sname}{{" + ", ".join(parts) + "}}"

    def field_of(self, kind, extra, val, name):
        if kind != "struct":
            raise DbgError("不是结构体，不能取字段")
        lay = self.dbg["structs"].get(extra)
        if lay is None:
            raise DbgError(f"未知结构体 {extra}")
        for fname, fty, woff in lay["fields"]:
            if fname == name:
                raw = self.read_u64(val + woff * 8)
                if raw is None:
                    raise DbgError(f"字段 {name} 不可读")
                k, e = self.field_kind(fty)
                return k, e, raw
        raise DbgError(f"结构体 {extra} 没有字段 {name}")

    # ---- 命令 ----
    def cmd_break(self, arg):
        if not arg:
            self.err("break 需要 FILE:LINE 或函数名")
            return
        if ":" in arg:
            f, _, ln_s = arg.rpartition(":")
            if not ln_s.strip().isdigit():
                self.err(f"无法解析断点 {arg!r}（要 FILE:LINE 或函数名）")
                return
            ln = int(ln_s)
            hits = []
            for fd in self.funcs:
                if not fd.get("file"):
                    continue
                if not (fd["file"] == f or fd["file"].endswith("/" + f)
                        or os.path.basename(fd["file"]) == os.path.basename(f)):
                    continue
                for off, line in fd["lines"]:
                    if line == ln:
                        hits.append((fd, off))
            if not hits:
                self.err(f"{f}:{ln} 没有对应代码（空行/注释/声明行不能下断点）")
                return
            fd, off = hits[0]
            self.set_bp(off + TEXT_RVA, f"{os.path.basename(fd['file'])}:{ln}")
        else:
            fn = next((f for f in self.funcs if f["name"] == arg), None)
            if fn is None:
                self.err(f"没有函数 {arg!r}")
                return
            self.set_bp(fn["rva"], f"{arg}()")

    def _after_stop(self, reason):
        if reason == "exit":
            self.out(f"process exited code={self.exit_code}")
        else:
            self.print_where(self.stop_rva)

    def cmd_continue(self):
        if not self.running:
            self.err("进程已退出")
            return
        self._after_stop(self.resume(None))

    def cmd_step(self, mode):
        if not self.stopped():
            self.err("进程未停止（先 run 到断点）")
            return
        # 停在 <entry> 桩或库函数里时没有"下一源码行"可去：单步会在
        # ntdll 里逐指令爬（实测一次 next 走了 51 万条指令、231 秒）。
        # 这里直接按 continue 处理，并如实说明。
        ctx = self.get_context(self.tid)
        fn = self.fn_at(ctx.Rip - self.image_base)
        if not fn or not fn.get("file"):
            self.out("当前位置没有源码行（<entry>/库帧），按 continue 处理")
            self._after_stop(self.resume(None))
            return
        self._after_stop(self.resume(mode))

    def cmd_print(self, arg):
        if not self.stopped():
            self.err("进程未停止")
            return
        if not arg:
            self.err("print 需要表达式（变量名 / a.b.c）")
            return
        ctx = self.get_context(self.tid)
        rva = ctx.Rip - self.image_base
        parts = arg.split(".")
        fn = self.fn_at(rva) or {"vars": []}
        live = self._live_vars(fn, rva)
        v = live.get(parts[0])
        if v is None:
            # 区分"根本不存在"和"存在但已过期"：后者是优化后的正常现象
            # （寄存器/帧槽被复用），提示得含糊会让人以为调试器坏了。
            if any(x["name"] == parts[0] for x in fn.get("vars", [])):
                cand = [x for x in fn["vars"] if x["name"] == parts[0]]
                if any(x["bind"] + TEXT_RVA > rva for x in cand):
                    self.err(f"变量 {parts[0]!r} 尚未初始化"
                             f"（还没执行到它的声明）")
                else:
                    self.err(f"变量 {parts[0]!r} 已超出生命周期"
                             f"（该值所在寄存器/帧槽已被复用，不显示过期值）")
            else:
                self.err(f"未知变量或不在作用域: {parts[0]!r}")
            return
        kind, extra, val = self.read_var(v, ctx)
        for p in parts[1:]:
            kind, extra, val = self.field_of(kind, extra, val, p)
        self.out(f"{arg} = {self.fmt_value(kind, extra, val)}")

    def cmd_locals(self):
        if not self.stopped():
            self.err("进程未停止")
            return
        ctx = self.get_context(self.tid)
        rva = ctx.Rip - self.image_base
        fn = self.fn_at(rva)
        live = self._live_vars(fn or {"vars": []}, rva)
        parts = []
        for name in sorted(live):
            kind, extra, val = self.read_var(live[name], ctx)
            parts.append(f"{name}={self.fmt_value(kind, extra, val)}")
        self.out("locals: " + (", ".join(parts) if parts else "(无)"))

    def cmd_bt(self):
        if not self.stopped():
            self.err("进程未停止")
            return
        ctx = self.get_context(self.tid)
        rva = ctx.Rip - self.image_base
        f, line, name = self.where(rva)
        loc = f"{f}:{line}" if f and line else "<library>"
        self.out(f"bt #0 {name or '?'}() {loc}")
        for i, ret in enumerate(self.frame_chain(self.tid), start=1):
            f2, l2, n2 = self.where(ret - self.image_base)
            loc2 = f"{f2}:{l2}" if f2 and l2 else "<library>"
            self.out(f"bt #{i} {n2 or '?'}() {loc2}")

    def cmd_list(self, arg):
        if not self.stopped():
            self.err("进程未停止")
            return
        ctx = self.get_context(self.tid)
        f, line, _n = self.where(ctx.Rip - self.image_base)
        if arg.strip().isdigit():
            line = int(arg.strip())
        if not f or not line:
            self.err("无源码位置（库帧不能 list）")
            return
        for n in range(max(1, line - 2), line + 3):
            mark = ">" if n == line else " "
            self.out(f"{mark} {n}| {self.src_line(f, n)}")

    def cmd_info(self, arg):
        if arg.strip() != "break":
            self.err("info 只支持 break")
            return
        if not self.bps:
            self.out("no breakpoints")
            return
        for rva in sorted(self.bps):
            bp = self.bps[rva]
            self.out(f"#{bp['n']} {bp['desc']} rva=0x{rva:x} hits={bp['hits']}")

    def cmd_delete(self, arg):
        if not arg.strip().isdigit():
            self.err("delete 需要断点编号")
            return
        self.del_bp(int(arg.strip()))

    # ---- REPL ----
    def next_command(self):
        if self.script is not None:
            if self.script_i >= len(self.script):
                return None
            cmd = self.script[self.script_i]
            self.script_i += 1
            print(f"[dbg] > {cmd}")
            return cmd
        try:
            return input("(qlm-dbg) ").strip()
        except EOFError:
            return None

    def exec_command(self, line):
        parts = line.split()
        if not parts:
            return True
        cmd, arg = parts[0], " ".join(parts[1:])
        if cmd in ("quit", "q", "exit"):
            self.out("quit")
            return False
        try:
            if cmd in ("run", "r", "continue", "c"):
                self.cmd_continue()
            elif cmd in ("break", "b"):
                self.cmd_break(arg)
            elif cmd in ("step", "s"):
                self.cmd_step("step")
            elif cmd in ("next", "n"):
                self.cmd_step("next")
            elif cmd in ("finish", "f"):
                self.cmd_step("finish")
            elif cmd in ("print", "p"):
                self.cmd_print(arg)
            elif cmd == "locals":
                self.cmd_locals()
            elif cmd == "bt":
                self.cmd_bt()
            elif cmd in ("list", "l"):
                self.cmd_list(arg)
            elif cmd == "info":
                self.cmd_info(arg)
            elif cmd in ("delete", "d"):
                self.cmd_delete(arg)
            elif cmd == "help":
                self.out(__doc__.strip())
            else:
                self.err(f"未知命令 {cmd!r}（help 看列表）")
        except DbgError as e:
            self.err(str(e))
        return True

    def startup(self):
        """消费启动事件：CREATE_PROCESS（拿运行期基址）+ 初始断点（停住）。"""
        # CREATE_PROCESS
        while True:
            if not k32.WaitForDebugEvent(ctypes.byref(self.ev), 20000):
                raise DbgError(f"等待启动事件失败: {ctypes.get_last_error()}")
            if self.ev.dwDebugEventCode == CREATE_PROCESS_DEBUG_EVENT:
                base = ctypes.c_void_p.from_buffer(self.ev.u, 24).value or 0
                self.image_base = base
                self.tid = self.ev.dwThreadId
                self._pending = (self.ev.dwProcessId, self.ev.dwThreadId,
                                 DBG_CONTINUE)
                break
        # 初始断点（ntdll，镜像外）：停住，等用户命令
        while True:
            if self._pending is not None:
                pid, tid, status = self._pending
                self._pending = None
                k32.ContinueDebugEvent(pid, tid, status)
            if not k32.WaitForDebugEvent(ctypes.byref(self.ev), 20000):
                raise DbgError(f"等待初始断点失败: {ctypes.get_last_error()}")
            if (self.ev.dwDebugEventCode == EXCEPTION_DEBUG_EVENT):
                info = ctypes.cast(
                    ctypes.byref(self.ev.u),
                    ctypes.POINTER(EXCEPTION_DEBUG_INFO)).contents
                if info.ExceptionRecord.ExceptionCode == STATUS_BREAKPOINT:
                    self.tid = self.ev.dwThreadId
                    self.stop_reason = "entry"
                    self.stop_rva = (info.ExceptionRecord.ExceptionAddress or 0) \
                        - self.image_base
                    self._pending = (self.ev.dwProcessId, self.ev.dwThreadId,
                                     DBG_CONTINUE)
                    return
            self._pending = (self.ev.dwProcessId, self.ev.dwThreadId,
                             DBG_CONTINUE)

    def cleanup(self):
        if self._pending is not None:
            pid, tid, status = self._pending
            self._pending = None
            try:
                k32.ContinueDebugEvent(pid, tid, status)
            except Exception:
                pass
        if self.running and self.h_process:
            k32.TerminateProcess(self.h_process, 1)
            for _ in range(3):
                if not k32.WaitForDebugEvent(ctypes.byref(self.ev), 500):
                    break
                k32.ContinueDebugEvent(self.ev.dwProcessId, self.ev.dwThreadId,
                                       DBG_CONTINUE)
        if self.h_process:
            k32.CloseHandle(self.h_process)
            self.h_process = None
        for h in self._threads.values():
            k32.CloseHandle(h)
        self._threads = {}

    def repl(self):
        self.start()
        self.out(f"exe={os.path.basename(self.exe)} funcs={len(self.funcs)} "
                 f"lines={sum(len(f['lines']) for f in self.funcs)} "
                 f"vars={sum(len(f['vars']) for f in self.funcs)}")
        self.startup()
        self.out(f"stopped at entry (initial breakpoint), "
                 f"base=0x{self.image_base:X}")
        while True:
            if not self.running:
                if self.stop_reason != "exit":
                    self.out(f"process exited code={self.exit_code}")
                break
            cmd = self.next_command()
            if cmd is None:
                break
            if not self.exec_command(cmd):
                break
        self.cleanup()
        return 0 if self.errors == 0 else 1


HELP = """命令：break FILE:LINE|FUNC / run|continue / step / next / finish /
print EXPR / locals / bt / list / info break / delete N / quit"""


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            # 行缓冲：被调试进程直接写 fd，Python 侧若不行缓冲，
            # 脚本模式下 [dbg] 输出会堆在缓冲区里看不到（实测踩过）
            stream.reconfigure(encoding="utf-8", errors="replace",
                               line_buffering=True)
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="qlm-dbg",
                                 description="Quelmara 源码级调试器（v1.62）")
    ap.add_argument("exe", help="带 .qlmdbg 调试节的 PE（--dbg-info 构建）")
    ap.add_argument("--script", default=None,
                    help="命令脚本文件（每行一条命令，# 注释；测试用）")
    ap.add_argument("prog_args", nargs="*", help="传给被调试程序的参数")
    args = ap.parse_args(argv)
    script = None
    if args.script:
        with open(args.script, encoding="utf-8") as f:
            script = [ln.strip() for ln in f
                      if ln.strip() and not ln.strip().startswith("#")]
    return Debugger(args.exe, args.prog_args, script).repl()


if __name__ == "__main__":
    sys.exit(main())
