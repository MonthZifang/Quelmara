#!/usr/bin/env python3
"""fault_probe.py —— 让一个 exe 在调试器下跑，捕获访问违例并打印现场。

用途：qlmc 在编译某些输入时会 segfault（07-gaps §7.17）。没有 gdb 的情况下，
用 Windows 调试 API 拿到崩溃点的 Rip/Rsp/Rbp + 栈顶内容，就能判断是
"栈耗尽"（Rsp 贴着栈底）还是"帧算错/越界写"（Rsp 明显不对但不在栈底）。

用法：
    python tools/dev/fault_probe.py build/qlmc.exe build build/t/r1.qma -o build/t/r1.exe
"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

DEBUG_ONLY_THIS_PROCESS = 0x00000002
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_DEBUG_EVENT = 1
CREATE_PROCESS_DEBUG_EVENT = 3
EXIT_PROCESS_DEBUG_EVENT = 5
INFINITE = 0xFFFFFFFF

CONTEXT_AMD64 = 0x00100000
CONTEXT_CONTROL = CONTEXT_AMD64 | 0x1
CONTEXT_INTEGER = CONTEXT_AMD64 | 0x2
CONTEXT_FULL = CONTEXT_CONTROL | CONTEXT_INTEGER


class STARTUPINFOA(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPSTR),
                ("lpDesktop", wt.LPSTR), ("lpTitle", wt.LPSTR),
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


class EXCEPTION_RECORD(ctypes.Structure):
    _fields_ = [("ExceptionCode", wt.DWORD), ("ExceptionFlags", wt.DWORD),
                ("ExceptionRecord", ctypes.c_void_p),
                ("ExceptionAddress", ctypes.c_void_p),
                ("NumberParameters", wt.DWORD),
                ("ExceptionInformation", ctypes.c_void_p * 15)]


class EXCEPTION_DEBUG_INFO(ctypes.Structure):
    _fields_ = [("ExceptionRecord", EXCEPTION_RECORD),
                ("dwFirstChance", wt.DWORD)]


class DEBUG_EVENT_UNION(ctypes.Union):
    # 必须按 8 字节对齐：Windows 把 union 放在偏移 16（dwThreadId 后有 4 字节填充）
    _fields_ = [("q", ctypes.c_ulonglong * 20), ("raw", ctypes.c_byte * 160)]


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [("dwDebugEventCode", wt.DWORD), ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD), ("u", DEBUG_EVENT_UNION)]


# CONTEXT 只需要前面几个字段，但必须够大；用 0x500 字节缓冲 + 按偏移取值
class CONTEXT(ctypes.Structure):
    _fields_ = [("P1Home", ctypes.c_ulonglong * 6),
                ("ContextFlags", wt.DWORD), ("MxCsr", wt.DWORD),
                ("SegCs", wt.WORD), ("SegDs", wt.WORD),
                ("SegEs", wt.WORD), ("SegFs", wt.WORD),
                ("SegGs", wt.WORD), ("SegSs", wt.WORD),
                ("EFlags", wt.DWORD),
                ("Dr0", ctypes.c_ulonglong), ("Dr1", ctypes.c_ulonglong),
                ("Dr2", ctypes.c_ulonglong), ("Dr3", ctypes.c_ulonglong),
                ("Dr6", ctypes.c_ulonglong), ("Dr7", ctypes.c_ulonglong),
                ("Rax", ctypes.c_ulonglong), ("Rcx", ctypes.c_ulonglong),
                ("Rdx", ctypes.c_ulonglong), ("Rbx", ctypes.c_ulonglong),
                ("Rsp", ctypes.c_ulonglong), ("Rbp", ctypes.c_ulonglong),
                ("Rsi", ctypes.c_ulonglong), ("Rdi", ctypes.c_ulonglong),
                ("R8", ctypes.c_ulonglong), ("R9", ctypes.c_ulonglong),
                ("R10", ctypes.c_ulonglong), ("R11", ctypes.c_ulonglong),
                ("R12", ctypes.c_ulonglong), ("R13", ctypes.c_ulonglong),
                ("R14", ctypes.c_ulonglong), ("R15", ctypes.c_ulonglong),
                ("Rip", ctypes.c_ulonglong)]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    exe = os.path.abspath(sys.argv[1])
    args = sys.argv[2:]
    cmd = '"' + exe + '"'
    for a in args:
        cmd += ' ' + ('"' + a + '"' if ' ' in a else a)

    si = STARTUPINFOA()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    ok = k32.CreateProcessA(exe.encode(), cmd.encode(), None, None, False,
                            DEBUG_ONLY_THIS_PROCESS, None,
                            os.getcwd().encode(), ctypes.byref(si),
                            ctypes.byref(pi))
    if not ok:
        print("CreateProcess 失败", ctypes.get_last_error())
        return 2

    tries = int(os.environ.get("PROBE_TRIES", "1"))
    for attempt in range(tries):
        r = _run_once(exe, cmd, pi)
        if r == 0:
            return 0
        if attempt + 1 < tries:
            k32.CloseHandle(pi.hProcess)
            k32.CloseHandle(pi.hThread)
            pi = PROCESS_INFORMATION()
            ok = k32.CreateProcessA(exe.encode(), cmd.encode(), None, None, False,
                                    DEBUG_ONLY_THIS_PROCESS, None,
                                    os.getcwd().encode(), ctypes.byref(si),
                                    ctypes.byref(pi))
            if not ok:
                print("CreateProcess 失败", ctypes.get_last_error())
                return 2
    print(f"跑了 {tries} 次都没有崩")
    return 1


def _run_once(exe, cmd, pi):
    ev = DEBUG_EVENT()
    base = None
    while True:
        if not k32.WaitForDebugEvent(ctypes.byref(ev), INFINITE):
            break
        if os.environ.get("PROBE_TRACE"):
            print("event", ev.dwDebugEventCode, "tid", ev.dwThreadId)
        if ev.dwDebugEventCode == CREATE_PROCESS_DEBUG_EVENT:
            base = ev.u.raw  # 需要自己解析，简单起见从 PE 头读
            # CREATE_PROCESS_DEBUG_INFO: hFile, hProcess, hThread, lpBaseOfImage...
            ptr = ctypes.cast(ctypes.byref(ev.u),
                              ctypes.POINTER(ctypes.c_void_p))
            base = ptr[3]
        elif ev.dwDebugEventCode == EXCEPTION_DEBUG_EVENT:
            info = ctypes.cast(ctypes.byref(ev.u),
                               ctypes.POINTER(EXCEPTION_DEBUG_INFO)).contents
            rec = info.ExceptionRecord
            c = rec.ExceptionCode
            if c == 0x80000003:      # 初始断点
                k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId,
                                       DBG_CONTINUE)
                continue
            # 真正的异常
            ctx = CONTEXT()
            ctx.ContextFlags = CONTEXT_FULL
            k32.GetThreadContext(pi.hThread, ctypes.byref(ctx))
            fault = rec.ExceptionAddress or 0
            print(f"异常码    : 0x{c:08X}")
            print(f"故障地址  : 0x{fault:016X}"
                  + (f"  (RVA 0x{fault - base:X})" if base else ""))
            print(f"Rip       : 0x{ctx.Rip:016X}"
                  + (f"  (RVA 0x{ctx.Rip - base:X})" if base else ""))
            print(f"Rsp       : 0x{ctx.Rsp:016X}")
            print(f"Rbp       : 0x{ctx.Rbp:016X}")
            print(f"Rax/Rcx   : 0x{ctx.Rax:X} / 0x{ctx.Rcx:X}")
            print(f"Rbx/R12/R13/R14: 0x{ctx.Rbx:X} / 0x{ctx.R12:X} / 0x{ctx.R13:X} / 0x{ctx.R14:X}")
            if rec.NumberParameters >= 2:
                info2 = ctypes.cast(rec.ExceptionInformation,
                                    ctypes.POINTER(ctypes.c_ulonglong))
                print(f"AV 类型   : {info2[0]}（0=读 1=写 8=DEP）")
                print(f"AV 地址   : 0x{info2[1]:016X}")
            # 走 rbp 链，看递归深度与重复的函数
            if base:
                rb = ctx.Rbp
                print("rbp 链（前 30 帧，返回值 RVA）:")
                for k in range(30):
                    buf2 = ctypes.create_string_buffer(16)
                    g2 = ctypes.c_size_t(0)
                    if not k32.ReadProcessMemory(pi.hProcess, ctypes.c_void_p(rb),
                                                 buf2, 16, ctypes.byref(g2)):
                        print(f"  #{k}: 读不到 rbp=0x{rb:X}")
                        break
                    nxt, ret = struct.unpack("<QQ", buf2.raw[:16])
                    print(f"  #{k}  rbp=0x{rb:X}  返回 RVA 0x{(ret - base) & 0xFFFFFF:X}")
                    if nxt <= rb or nxt - rb > 0x100000:
                        break
                    rb = nxt
            # 栈顶 12 个字
            n = 12
            buf = ctypes.create_string_buffer(n * 8)
            got = ctypes.c_size_t(0)
            k32.ReadProcessMemory(pi.hProcess, ctypes.c_void_p(ctx.Rsp),
                                  buf, n * 8, ctypes.byref(got))
            words = struct.unpack("<" + "Q" * (got.value // 8), buf.raw[:got.value])
            print("栈顶 12 字:")
            for i, w in enumerate(words):
                tag = ""
                if base and base <= w < base + 0x200000:
                    tag = f"  <- 代码 RVA 0x{w - base:X}"
                print(f"  [rsp+{i*8:02X}] 0x{w:016X}{tag}")
            k32.TerminateProcess(pi.hProcess, 3)
            k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId,
                                   DBG_EXCEPTION_NOT_HANDLED)
            return 0
        elif ev.dwDebugEventCode == 5:
            code = 0
            k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, DBG_CONTINUE)
            ec = ctypes.c_ulong(0)
            k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(ec))
            if ec.value != 0:
                print(f"进程退出（未捕获异常），exit code = 0x{ec.value:08X}")
            return 1
        k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, DBG_CONTINUE)
    return 1


if __name__ == "__main__":
    sys.exit(main())
