#!/usr/bin/env python3
"""frame_scan.py —— 扫 PE 里所有函数的帧大小，报出超过 4 KB 的（Windows 上会跳过
guard page，导致"第一次写就 AV"这种诡异崩溃，见 07-gaps §7.17）。

判据：`push rbp; mov rbp,rsp; sub rsp, imm32` 这三条连在一起。
用法：python tools/dev/frame_scan.py build/qlmc.exe [阈值]
"""
import struct
import sys

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
except ImportError:
    print("需要 capstone（可选开发依赖）：pip install capstone")
    sys.exit(2)


def sections(d):
    e = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, e + 6)[0]
    optsz = struct.unpack_from("<H", d, e + 20)[0]
    base = e + 24 + optsz
    out = []
    for i in range(nsec):
        o = base + i * 40
        nm = d[o:o + 8].rstrip(b"\0").decode()
        vsz, va, rsz, ptr = struct.unpack_from("<IIII", d, o + 8)
        out.append((nm, va, vsz, rsz, ptr))
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "build/qlmc.exe"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 4096
    d = open(path, "rb").read()
    nm, va, vsz, rsz, ptr = [s for s in sections(d) if s[0] == ".text"][0]
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    hits = []
    prev = []
    for ins in md.disasm(d[ptr:ptr + rsz], va):
        if ins.mnemonic == "push" and ins.op_str == "rbp":
            prev = [("push", "rbp", ins.address)]
            continue
        if prev and ins.mnemonic == "mov" and ins.op_str == "rbp, rsp":
            prev.append(("mov", "rbp,rsp", ins.address))
            continue
        if len(prev) == 2 and ins.mnemonic == "sub" and ins.op_str.startswith("rsp, 0x"):
            try:
                n = int(ins.op_str.split("0x")[1], 16)
            except Exception:
                n = 0
            if n >= limit:
                hits.append((n, prev[0][2]))
            prev = []
            continue
        prev = []
    hits.sort(reverse=True)
    print(f"{path}: 帧 >= {limit} 字节的函数 {len(hits)} 个")
    for n, rva in hits[:20]:
        print(f"  RVA 0x{rva:06X}  帧 0x{n:X} ({n} 字节)")


if __name__ == "__main__":
    main()
