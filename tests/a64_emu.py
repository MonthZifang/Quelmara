#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A64 迷你模拟器（测试工具）
========================
用于【执行级】验证 Quelmara aarch64 发射器：直接按位解码我们发射的指令子集
（编码器与模拟器是两套独立实现，互为校验）。支持：movz/movk、orr(=mov)、
add/sub(imm/reg)、and/orr/eor/orn、madd(=mul)、umulh、sdiv、lslv/lsrv/asrv、
ubfm/sbfm(lsl/lsr/asr imm)、cmp、csinc(=cset)、b/b.cond/bl/ret、cbz/cbnz、
ldr/str(ldur/stur/reg-shift/ldrb/strb)、stp/ldp、svc(write/exit)。

用法： python3 tests/a64_emu.py <elf> [max_steps]
"""

import struct
import sys

BASE = 0x400000
ENTRY = 0x400078
STACK_BASE = 0x7F0000000000
STACK_SZ = 2 * 1024 * 1024
HEAP_BASE = 0x6F0000000000
HEAP_SZ = 512 * 1024 * 1024         # 虚拟堆空间（__alloc 一次性 mmap 整个 arena）
                                   # 实际内存按需惰性展开，不会真占 512MB

COND = {"0": ("Z",), }  # 占位，见 condh


class A64:
    def __init__(self, blob):
        self.img = bytearray(blob)   # 可写：itoa 等会写全局数据区
        self.img_base = ENTRY
        self.mem = bytearray(STACK_SZ)
        self.heap = bytearray(HEAP_SZ)
        self.heap_off = 0
        self.r = [0] * 32          # r[31] 视语义为 SP 或 XZR
        self.r[31] = STACK_BASE + STACK_SZ - 256
        self.pc = ENTRY
        self.out = bytearray()
        self.exit_code = None
        self.N = self.Z = self.C = self.V = 0

    # ---- 内存 ----
    def _addr(self, a):
        if self.img_base <= a < self.img_base + len(self.img):
            return ("img", a - self.img_base)
        if STACK_BASE <= a < STACK_BASE + STACK_SZ:
            return ("stk", a - STACK_BASE)
        if HEAP_BASE <= a < HEAP_BASE + HEAP_SZ:
            o = a - HEAP_BASE
            if o >= len(self.heap):          # 惰性展开（按 64KB 块）
                need = ((o // 65536) + 1) * 65536
                self.heap.extend(b"\x00" * (need - len(self.heap)))
            return ("heap", o)
        raise RuntimeError(f"非法地址 0x{a:x} (pc=0x{self.pc:x})")

    def _buf(self, k):
        return {"img": self.img, "stk": self.mem, "heap": self.heap}[k]

    def rd64(self, a):
        k, o = self._addr(a)
        return struct.unpack_from("<Q", self._buf(k), o)[0]

    def wr64(self, a, v):
        k, o = self._addr(a)
        struct.pack_into("<Q", self._buf(k), o, v & (2**64 - 1))

    def rd8(self, a):
        k, o = self._addr(a)
        return self._buf(k)[o]

    def wr8(self, a, v):
        k, o = self._addr(a)
        self._buf(k)[o] = v & 0xFF

    def rd_bytes(self, a, n):
        b = bytearray()
        for i in range(n):
            b.append(self.rd8(a + i))
        return bytes(b)

    # ---- 寄存器 ----
    def get(self, i, sp_ctx=False):
        if i == 31:
            return self.r[31] if sp_ctx else 0
        return self.r[i]

    def put(self, i, v, sp_ctx=False):
        if i == 31:
            if sp_ctx:
                self.r[31] = v & (2**64 - 1)
            return
        self.r[i] = v & (2**64 - 1)

    def set_flags_sub(self, a, b, res):
        self.Z = 1 if res == 0 else 0
        self.N = 1 if res >> 63 else 0
        self.C = 1 if a >= b else 0
        self.V = 1 if ((a ^ b) & (a ^ res)) >> 63 else 0

    def cond_holds(self, cond):
        EQ, NE, GE, LT, LE, GT = 0x0, 0x1, 0xA, 0xB, 0xD, 0xC
        return {EQ: self.Z == 1, NE: self.Z == 0, GE: self.N == self.V,
                LT: self.N != self.V, LE: self.Z == 1 or self.N != self.V,
                GT: self.Z == 0 and self.N == self.V}[cond]

    def sext(self, v, bits):
        s = 1 << (bits - 1)
        return (v & (s - 1)) - (v & s)

    # ---- 执行 ----
    def step(self):
        w = self.rd64(self.pc) & 0xFFFFFFFF
        self.pc += 4

        # MOVZ / MOVK
        if (w & 0xFF800000) == 0xD2800000:
            rd, hw, imm = w & 31, (w >> 21) & 3, (w >> 5) & 0xFFFF
            self.put(rd, imm << (16 * hw))
            return
        if (w & 0xFF800000) == 0xF2800000:
            rd, hw, imm = w & 31, (w >> 21) & 3, (w >> 5) & 0xFFFF
            cur = self.get(rd)
            self.put(rd, (cur & ~(0xFFFF << (16 * hw))) | (imm << (16 * hw)))
            return
        # SVC
        if (w & 0xFFE0001F) == 0xD4000001:
            self.syscall()
            return
        # RET
        if w == 0xD65F03C0:
            self.pc = self.get(30)
            return
        # B / BL
        if (w & 0xFC000000) == 0x14000000 or (w & 0xFC000000) == 0x94000000:
            off = self.sext(w & 0x3FFFFFF, 26) * 4
            if (w & 0xFC000000) == 0x94000000:   # BL：链接位是 bit31（0x94…）
                self.put(30, self.pc)
            self.pc += off - 4
            return
        # B.cond
        if (w & 0xFF000010) == 0x54000000:
            if self.cond_holds(w & 0xF):
                self.pc += self.sext((w >> 5) & 0x7FFFF, 19) * 4 - 4
            return
        # CBZ / CBNZ
        if (w & 0x7E000000) == 0x34000000:
            rt = w & 31
            val = self.get(rt)
            is64 = (w >> 31) & 1
            is_nz = (w >> 24) & 1
            take = (val != 0) if is_nz else (val == 0)
            if take:
                self.pc += self.sext((w >> 5) & 0x7FFFF, 19) * 4 - 4
            return
        # STP / LDP（无符号偏移，64 位）
        if (w & 0xFFC00000) in (0xA9000000, 0xA9400000):
            rt, rt2, rn = w & 31, (w >> 10) & 31, (w >> 5) & 31
            imm7 = self.sext((w >> 15) & 0x7F, 7) * 8
            base = self.get(rn, sp_ctx=True)
            if (w & 0xFFC00000) == 0xA9000000:
                self.wr64(base + imm7, self.get(rt))
                self.wr64(base + imm7 + 8, self.get(rt2))
            else:
                self.put(rt, self.rd64(base + imm7))
                self.put(rt2, self.rd64(base + imm7 + 8))
            return
        # LDR/STR 立即数无符号比例（64 位）
        if (w & 0xFFC00000) in (0xF9400000, 0xF9000000):
            rt, rn, imm = w & 31, (w >> 5) & 31, ((w >> 10) & 0xFFF) * 8
            addr = self.get(rn, sp_ctx=True) + imm
            if (w & 0xFFC00000) == 0xF9400000:
                self.put(rt, self.rd64(addr))
            else:
                self.wr64(addr, self.get(rt))
            return
        # LDUR/STUR（非缩放 simm9）
        if (w & 0xFFE00C00) in (0xF8400000, 0xF8000000):
            rt, rn = w & 31, (w >> 5) & 31
            imm = self.sext((w >> 12) & 0x1FF, 9)
            addr = self.get(rn, sp_ctx=True) + imm
            if (w & 0xFFE00C00) == 0xF8400000:
                self.put(rt, self.rd64(addr))
            else:
                self.wr64(addr, self.get(rt))
            return
        # LDR/STR 寄存器偏移 LSL#3
        if (w & 0xFFE0FC00) in (0xF8607800, 0xF8207800):
            rt, rn, rm = w & 31, (w >> 5) & 31, (w >> 16) & 31
            addr = self.get(rn, sp_ctx=True) + (self.get(rm) << 3)
            if (w & 0xFFE0FC00) == 0xF8607800:
                self.put(rt, self.rd64(addr))
            else:
                self.wr64(addr, self.get(rt))
            return
        # LDRB/STRB 寄存器偏移
        if (w & 0xFFE0FC00) in (0x38606800, 0x38206800):
            rt, rn, rm = w & 31, (w >> 5) & 31, (w >> 16) & 31
            addr = self.get(rn, sp_ctx=True) + self.get(rm)
            if (w & 0xFFE0FC00) == 0x38606800:
                self.put(rt, self.rd8(addr))
            else:
                self.wr8(addr, self.get(rt) & 0xFF)
            return
        # CSET = CSINC Xd, XZR, XZR, inv(cond)
        if (w & 0xFFE00C00) == 0x9A800400 and ((w >> 5) & 31) == 31 and ((w >> 16) & 31) == 31:
            rd = w & 31
            inv = (w >> 12) & 0xF
            real = {0x1: 0x0, 0x0: 0x1, 0xB: 0xA, 0xA: 0xB, 0xD: 0xC, 0xC: 0xD}[inv]
            self.put(rd, 1 if self.cond_holds(real) else 0)
            return
        # CMP reg = SUBS XZR, Rn, Rm
        if (w & 0xFFE0001F) == 0xEB00001F:
            rn, rm = (w >> 5) & 31, (w >> 16) & 31
            a, b = self.get(rn), self.get(rm)
            self.set_flags_sub(a, b, (a - b) & (2**64 - 1))
            return
        # CMP imm = SUBS XZR, Rn, #imm12
        if (w & 0xFFC0001F) == 0xF100001F:
            rn, imm = (w >> 5) & 31, (w >> 10) & 0xFFF
            a = self.get(rn)
            self.set_flags_sub(a, imm, (a - imm) & (2**64 - 1))
            return
        # UBFM / SBFM（用于 lsl/lsr/asr 立即数）
        if (w & 0xFFC00000) in (0xD3400000, 0x93400000):
            rd, rn = w & 31, (w >> 5) & 31
            immr, imms = (w >> 16) & 0x3F, (w >> 10) & 0x3F
            v = self.get(rn)
            if imms == 63:                      # lsr / asr
                if (w & 0xFFC00000) == 0xD3400000:
                    self.put(rd, v >> immr)
                else:
                    self.put(rd, self.sext(v >> immr, 64 - immr) if immr else self.sext(v, 64))
            else:                               # lsl: immr=64-sh, imms=63-sh
                sh = 64 - immr
                self.put(rd, (v << sh) & (2**64 - 1))
            return
        # 三操作数数据处理（寄存器）
        rn, rm, rd = (w >> 5) & 31, (w >> 16) & 31, w & 31
        a, b = self.get(rn), self.get(rm)
        # ADD/SUB 立即数（此形式 Rn/Rd=31 表示 SP）
        if (w & 0xFF800000) in (0x91000000, 0xD1000000):
            imm = (w >> 10) & 0xFFF
            a_sp = self.get(rn, sp_ctx=True)
            val = (a_sp + imm) if (w & 0xFF800000) == 0x91000000 else (a_sp - imm)
            self.put(rd, val, sp_ctx=True)
            return
        if (w & 0xFFE0FC00) == 0x8B000000:      # ADD reg (+LSL)
            sh = (w >> 10) & 0x3F
            self.put(rd, a + (b << sh))
            return
        if (w & 0xFFE0FC00) == 0xCB000000:      # SUB reg
            self.put(rd, a - b)
            return
        if (w & 0xFFE0FC00) == 0x8A000000:      # AND
            self.put(rd, a & b)
            return
        if (w & 0xFFE0FC00) == 0xAA000000:      # ORR（=mov when Rn=XZR）
            self.put(rd, a | b)
            return
        if (w & 0xFFE0FC00) == 0xCA000000:      # EOR
            self.put(rd, a ^ b)
            return
        if (w & 0xFFE0FC00) == 0xAA200000:      # ORN（=mvn）
            self.put(rd, a | (~b & (2**64 - 1)))
            return
        if (w & 0xFFE08000) == 0x9B000000 and ((w >> 10) & 31) == 31:  # MADD(=MUL)
            self.put(rd, a * b)
            return
        if (w & 0xFFE08000) == 0x9BC00000 and ((w >> 10) & 31) == 31:  # UMULH
            self.put(rd, (a * b) >> 64)
            return
        if (w & 0xFFE0FC00) == 0x9AC00C00:      # SDIV
            sa, sb = self.sext(a, 64), self.sext(b, 64)
            q = 0 if sb == 0 else (abs(sa) // abs(sb)) * (1 if (sa < 0) == (sb < 0) else -1)
            self.put(rd, q)
            return
        if (w & 0xFFE0FC00) == 0x9AC02000:      # LSLV
            self.put(rd, a << (b & 63))
            return
        if (w & 0xFFE0FC00) == 0x9AC02400:      # LSRV
            self.put(rd, a >> (b & 63))
            return
        if (w & 0xFFE0FC00) == 0x9AC02800:      # ASRV
            self.put(rd, self.sext(a >> (b & 63), 64 - (b & 63)) if (b & 63) else self.sext(a, 64))
            return
        raise RuntimeError(f"未实现指令 0x{w:08x} @ pc=0x{self.pc - 4:x}")

    def syscall(self):
        num = self.get(8)
        if num == 64:                          # write
            fd, buf, cnt = self.get(0), self.get(1), self.get(2)
            if fd == 1:
                self.out += self.rd_bytes(buf, cnt)
            self.put(0, cnt if fd == 1 else 0)
        elif num == 93:                        # exit
            self.exit_code = self.sext(self.get(0), 64)
        elif num == 222:                       # mmap（__alloc 用）：线性 bump，返回 x0
            size = (self.get(1) + 15) & ~15
            if self.heap_off + size > HEAP_SZ:
                raise RuntimeError("模拟器堆耗尽")
            ptr = HEAP_BASE + self.heap_off
            self.heap_off += size
            self.put(0, ptr)
        else:
            raise RuntimeError(f"未实现 syscall {num}")

    def run(self, max_steps=200_000_000):
        for _ in range(max_steps):
            if self.exit_code is not None:
                return self.exit_code
            self.step()
        raise RuntimeError("超出最大步数（疑似死循环）")


def main():
    path = sys.argv[1]
    max_steps = int(sys.argv[2]) if len(sys.argv) > 2 else 200_000_000
    with open(path, "rb") as f:
        elf = f.read()
    assert elf[:4] == b"\x7fELF", "非 ELF"
    assert struct.unpack_from("<H", elf, 18)[0] == 0xB7, "非 AArch64 ELF"
    blob = elf[0x78:]
    cpu = A64(blob)
    code = cpu.run(max_steps)
    sys.stdout.write(cpu.out.decode("utf-8", "replace"))
    sys.stdout.flush()
    sys.exit(code & 0xFF)


if __name__ == "__main__":
    main()
