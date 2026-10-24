#!/usr/bin/env python3
"""dumpasm.py —— 把 qlmc（或任何 quelmara 产物）的 .text 反汇编出来。

为什么需要它：qlmc 的发射器是手写机器码，IR 层看起来完全正确的代码也可能在
编码阶段写坏一个字节。capstone 是**流式**解码的，遇到非法字节就停下——所以
"反汇编提前结束"本身就是定位信号：结束的位置就是出问题的那条指令。

用法：
  python tools/dev/dumpasm.py build/x.exe            # 全部 .text
  python tools/dev/dumpasm.py build/x.exe 0x1332     # 从某个 RVA 开始
  python tools/dev/dumpasm.py build/x.exe 0x1332 0x1600   # 区间
"""
import struct
import sys

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
except ImportError:
    print("需要 capstone（可选开发依赖）：pip install capstone")
    sys.exit(2)


def text_section(d):
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optsz = struct.unpack_from("<H", d, pe + 20)[0]
    opt = pe + 24
    imagebase = struct.unpack_from("<Q", d, opt + 24)[0]
    secoff = opt + optsz
    for i in range(nsec):
        o = secoff + i * 40
        name = d[o:o + 8].rstrip(b"\0").decode(errors="replace")
        vsz, va, rsz, ra = struct.unpack_from("<IIII", d, o + 8)
        if name == ".text":
            return imagebase, va, ra, rsz
    raise SystemExit("找不到 .text 节")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    d = open(sys.argv[1], "rb").read()
    imagebase, va, ra, rsz = text_section(d)
    lo = int(sys.argv[2], 0) if len(sys.argv) > 2 else va
    hi = int(sys.argv[3], 0) if len(sys.argv) > 3 else va + rsz
    code = d[ra + (lo - va): ra + (hi - va)]
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    n = 0
    end = lo
    for ins in md.disasm(code, lo):
        print(f"{ins.address:08x}  {ins.mnemonic:8s} {ins.op_str}")
        n += 1
        end = ins.address + len(ins.bytes)
    # 只有"从一个指令边界开始解、中途停下"才是信号；起点本来就切在指令中间时不算
    if n > 0 and end < hi:
        print(f"--- 解码停在 {end:08x}（区间 {lo:08x}..{hi:08x}），"
              f"下一条字节 {code[end - lo]:02x} 不是合法指令 —— 问题就在这里")
    print(f"--- 共 {n} 条")


if __name__ == "__main__":
    main()
