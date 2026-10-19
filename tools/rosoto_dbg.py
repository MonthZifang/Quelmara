#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rosoto Windows 调试小工具（开发期用，不属于语言运行时）
========================================================
启动一个 PE，在调试器下打印：
  - 实际加载基址（ASLR 后）
  - 线程创建：ThreadProc 的运行时地址与 RVA
  - 异常：异常码 + 异常地址（换算成 RVA）
  - 进程退出码

用法：
  python tools/rosoto_dbg.py build/hello.exe
  python tools/rosoto_dbg.py build/x.exe --mem 4083 --mem 41c3   # 退出时 dump 数据

为什么不用 WinDbg：本机没有 SDK；ctypes 直接调 kernel32 的调试 API 足够定位
「入口跳飞 / 线程参数错 / 归约结果 0」这类后端问题。
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

DBG_CONTINUE = 0x00010002
EXCEPTION_DEBUG_EVENT = 1
CREATE_THREAD_DEBUG_EVENT = 2
CREATE_PROCESS_DEBUG_EVENT = 3
EXIT_THREAD_DEBUG_EVENT = 4
EXIT_PROCESS_DEBUG_EVENT = 5
DEBUG_ONLY_THIS_PROCESS = 0x00000002


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


def read_mem(h, addr, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n,
                                 ctypes.byref(got)):
        return None
    return buf.raw[:got.value]


def main():
    ap = argparse.ArgumentParser(description="Rosoto Windows PE 调试器")
    ap.add_argument("exe")
    ap.add_argument("--mem", action="append", default=[], metavar="RVA",
                    help="进程退出时 dump 该 RVA 处的 128 字节（可多次）")
    args = ap.parse_args()

    si = STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    if not k32.CreateProcessW(None, args.exe, None, None, False,
                              DEBUG_ONLY_THIS_PROCESS, None, None,
                              ctypes.byref(si), ctypes.byref(pi)):
        print("CreateProcess failed:", ctypes.get_last_error())
        return 1

    ev = DEBUG_EVENT()
    base = 0
    nthread = 0
    while True:
        if not k32.WaitForDebugEvent(ctypes.byref(ev), 15000):
            print("WaitForDebugEvent timeout")
            break
        code = ev.dwDebugEventCode
        if code == CREATE_PROCESS_DEBUG_EVENT:
            base = ctypes.c_void_p.from_buffer(ev.u, 24).value or 0
            print(f"base=0x{base:X}")
        elif code == CREATE_THREAD_DEBUG_EVENT:
            start = ctypes.c_void_p.from_buffer(ev.u, 16).value or 0
            nthread += 1
            rva = hex(start - base) if base and start >= base else "?"
            print(f"thread#{nthread} start=0x{start:X} rva={rva}")
        elif code == EXIT_THREAD_DEBUG_EVENT:
            ec = wt.DWORD.from_buffer(ev.u, 0).value
            print(f"thread exit={ec}")
        elif code == EXCEPTION_DEBUG_EVENT:
            info = ctypes.cast(ctypes.byref(ev.u),
                               ctypes.POINTER(EXCEPTION_DEBUG_INFO)).contents
            rec = info.ExceptionRecord
            addr = rec.ExceptionAddress or 0
            rva = hex(addr - base) if base and addr >= base else hex(addr)
            print(f"exception code=0x{rec.ExceptionCode & 0xffffffff:08X} rva={rva}")
        elif code == EXIT_PROCESS_DEBUG_EVENT:
            ec = wt.DWORD.from_buffer(ev.u, 0).value
            print(f"process exit={ec}")
            for rva_s in args.mem:
                rva = int(rva_s, 16)
                data = read_mem(pi.hProcess, base + rva, 128)
                if data is None:
                    print(f"  @+{rva:x}: unreadable")
                else:
                    vals = struct.unpack("<" + "Q" * (len(data) // 8),
                                         data[:len(data) // 8 * 8])
                    print(f"  @+{rva:x}: {[hex(v) for v in vals[:10]]}")
            k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, DBG_CONTINUE)
            break
        k32.ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, DBG_CONTINUE)

    k32.CloseHandle(pi.hThread)
    k32.CloseHandle(pi.hProcess)
    return 0


if __name__ == "__main__":
    sys.exit(main())
