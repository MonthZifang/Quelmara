#!/usr/bin/env python3
"""dumpasm.py —— 把 qlmc（或任何 quelmara 产物）的 .text 反汇编出来。

为什么需要它：qlmc 的发射器是手写机器码，IR 层看起来完全正确的代码也可能在
编码阶段写坏一个字节。capstone 是**流式**解码的，遇到非法字节就停下——所以
"反汇编提前结束"本身就是定位信号：结束的位置就是出问题的那条指令。

用法：
  python tools/dev/dumpasm.py build/x.exe            # 全部 .text
  python tools/dev/dumpasm.py build/x.exe 0x1332     # 从某个 RVA 开始
  python tools/dev/dumpasm.py build/x.exe 0x1332 0x1600   # 区间

  # **--diff 模式：不需要 capstone**
  python tools/dev/dumpasm.py --diff a.exe b.exe     # 逐处列出 .text 差异
  python tools/dev/dumpasm.py --diff a.exe b.exe -n 8  # 只看前 8 处

`--diff` 是排查"同源码、不同编译器产物不同"的入口（v3.71 的 §7.18 就是
靠它把 6778 处假差异收敛到 2 处真差异）。它只做裸字节对比，不反汇编，
所以**没有 capstone 也能用**。

配合 `qlmc build <src> --addrdump`（v3.69）可以把差异 VA 映射回函数名。
"""
import struct
import sys

# **capstone 只在反汇编模式才需要**。`--diff` 是裸字节对比，不导入它 ——
# 否则没有 capstone 的环境连差异对比都做不了（v3.72 实测踩到）。
def _capstone():
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_64
        return Cs, CS_ARCH_X86, CS_MODE_64
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


def diff_mode(fa, fb, limit):
    """逐处列出两个产物 .text 的差异（不反汇编，无需 capstone）。

    为什么单列这个模式：排查"同源码、不同编译器产物不同"时，
    `cmp` 只给第一个差异点，而反汇编工具要 capstone。
    这里按"连续差异段"分组，直接给出 VA + 两侧字节 —— v3.71 实测把
    6778 处（大多是整体偏移的假差异）收敛到前 2 处真差异。
    """
    da = open(fa, "rb").read()
    db = open(fb, "rb").read()
    _, va_a, ra_a, rsz_a = text_section(da)
    _, va_b, ra_b, rsz_b = text_section(db)
    n = min(rsz_a, rsz_b)
    print(f"A: {fa}  .text VA={va_a:#x} size={rsz_a:#x}")
    print(f"B: {fb}  .text VA={va_b:#x} size={rsz_b:#x}")
    if rsz_a != rsz_b:
        print(f"** .text 大小不同：{rsz_a} vs {rsz_b}（差 {rsz_b - rsz_a} 字节）**")
    # 收集连续差异段
    groups = []
    i = 0
    while i < n:
        if da[ra_a + i] != db[ra_b + i]:
            start = i
            while i < n and da[ra_a + i] != db[ra_b + i]:
                i += 1
            groups.append((start, i - 1))
        else:
            i += 1
    print(f"差异段：{len(groups)} 处（区间取 min(size)，共 {n:#x} 字节）")
    for k, (s0, s1) in enumerate(groups[:limit]):
        va = va_a + s0
        ctx = max(0, s0 - 8)
        a_seg = da[ra_a + ctx: ra_a + s1 + 1 + 8]
        b_seg = db[ra_b + ctx: ra_b + s1 + 1 + 8]
        print(f"\n  [{k+1}] VA {va:#x}..{va + (s1 - s0):#x}"
              f"（{s1 - s0 + 1} 字节）")
        print(f"      A: {a_seg.hex(' ')}")
        print(f"      B: {b_seg.hex(' ')}")
    if len(groups) > limit:
        print(f"\n（还有 {len(groups) - limit} 处未显示，用 -n 调大）")
    # 提示下一步
    if groups:
        print(f"\n下一步：用 `qlmc build <src> --addrdump` 把 VA 映射回函数名")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    if sys.argv[1] == "--diff":
        if len(sys.argv) < 4:
            print("用法：dumpasm.py --diff a.exe b.exe [-n 8]")
            sys.exit(2)
        limit = 8
        if "-n" in sys.argv:
            limit = int(sys.argv[sys.argv.index("-n") + 1])
        diff_mode(sys.argv[2], sys.argv[3], limit)
        return
    d = open(sys.argv[1], "rb").read()
    imagebase, va, ra, rsz = text_section(d)
    lo = int(sys.argv[2], 0) if len(sys.argv) > 2 else va
    hi = int(sys.argv[3], 0) if len(sys.argv) > 3 else va + rsz
    code = d[ra + (lo - va): ra + (hi - va)]
    Cs, CS_ARCH_X86, CS_MODE_64 = _capstone()
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
