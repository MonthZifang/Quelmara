#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara 原生后端 v0.1（自研，零外部依赖）
========================================
Quelmara 源码 -> QuIR -> 优化passes -> 线性扫描寄存器分配 -> 自研 x86_64 编码器 -> ELF64 裸可执行文件

不依赖 libc / gcc / LLVM：
  - 直接产出静态 ELF64（基址 0x400000，单 RWX 段，无重定位）
  - 运行库（print/itoa）用 QuIR 自举实现，I/O 走 raw syscall
  - parfor 多核：raw clone() + wait4() + 共享内存归约（无需 pthread）

已实现优化（见 BACKEND.md 优化目录）：
  常量折叠 / 强度削减(mul->shl) / 复制传播 / 死代码消除 /
  cmp+jcc 融合 / 线性扫描寄存器分配(调用感知) / 帧槽复用 / mov 消除

用法：
  python3 tools/stage0/qlm_native.py build examples/fib.qma -o build/fib
  python3 tools/stage0/qlm_native.py run   examples/loop_sum.qma
"""

import argparse
import hashlib
import json
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qlm import (tokenize, Parser, load_config, walk_stmts,  # noqa: E402
                    parse_source, with_test_runner, validate_match,
                    resolve_option_patterns, require_source, load_program,
                    global_dce, SCALAR_ELEMS)

# ---------------------------------------------------------------------------
# x86-64 寄存器编号
# ---------------------------------------------------------------------------
RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = 0, 1, 2, 3, 4, 5, 6, 7
R8, R9, R10, R11, R12, R13, R14, R15 = 8, 9, 10, 11, 12, 13, 14, 15

POOL = [RBX, RSI, RDI, R8, R9, R12, R13, R14, R15]   # 可分配寄存器（9 个）
CALLEE_SAVED = [RBX, R12, R13, R14, R15]              # 跨调用存活用
ARG_REGS = [RDI, RSI, RDX, RCX, R8, R9]               # 调用约定（自研 ABI，SysV 形状）
SCRATCH, SCRATCH2, ACC = R11, R10, RAX                # 编码期临时寄存器（不参与分配）

# ---- f64 的 XMM 寄存器文件（v2.65）----
# 以前 f64 值住在 GPR 里，每条浮点指令都要 movq 进出 XMM 各一次，
# 循环里还过一趟 GPR —— b2_float 的热循环 23 条指令里有 8 条是这个往返，
# 每轮多 10 个以上周期。现在 f64 值直接住 XMM。
#
# 只用 XMM0-XMM3 当分配池、XMM4/XMM5 当编码期临时（**都不参与分配**）：
# 六个全是 caller-saved，所以**跨调用的值必须落栈**（见 allocate 的
# span_call 分支）。不用 XMM6-XMM15（Win64 非易失）是刻意的 —— 用它们就得
# 在序言里额外保存/恢复，还要和 WinAPI 调用的约定对齐，收益抵不上风险。
XPOOL = [0, 1, 2, 3]                       # caller-saved：不跨调用的值
XPOOL_CALLEE = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15]   # 非易失：跨调用存活
XS0, XS1 = 4, 5          # 编码期临时 XMM（f64 与 f32 共用，不参与分配）

CC = {"e": (0x84, 0x94), "ne": (0x85, 0x95), "l": (0x8C, 0x9C),
      "ge": (0x8D, 0x9D), "le": (0x8E, 0x9E), "g": (0x8F, 0x9F),
      "p": (0x8A, 0x9A), "np": (0x8B, 0x9B), "b": (0x82, 0x92),
      "be": (0x86, 0x96), "a": (0x87, 0x97), "ae": (0x83, 0x93)}
INV_CC = {"e": "ne", "ne": "e", "l": "ge", "ge": "l", "le": "g", "g": "le"}


# ---- 魔数除法：编译期搜索 (M, s) 并边界验证，除法 -> 乘高位+移位 ----
_MAGIC_CACHE = {}


def _verify_magic(M, s, d):
    UM = 1 << (64 + s)
    crit = {0, 1, 2, 3, d - 1, d, d + 1, (1 << 32) - 1, 1 << 32,
            (1 << 63) - 1, (1 << 64) - 1, (1 << 64) - d, (1 << 64) - d - 1}
    for k in (0, 1, 2, 7, 13, d, max((1 << 31) // d, 1), max((1 << 63) // d, 1)):
        for j in (-2, -1, 0, 1, 2):
            x = k * d + j
            if 0 <= x < (1 << 64):
                crit.add(x)
    rng = random.Random(12345)
    for _ in range(512):
        crit.add(rng.randrange(0, 1 << 64))
    for x in crit:
        if (x * M) // UM != x // d:
            return False
    return True


def magic_unsigned(d):
    """返回 (M, s) 使 floor(x/d) == floor(x*M / 2^(64+s)) 对全部 x∈[0,2^64) 成立
    约束 M < 2^64（否则无法单寄存器承载）；找不到合格魔数则回退 idiv"""
    if d in _MAGIC_CACHE:
        return _MAGIC_CACHE[d]
    result = None
    if 0 < d < 2**63:
        for p in range(64, 128):
            M = -(-(1 << p) // d)          # ceil(2^p / d)
            if M >= (1 << 64):
                break                       # M 随 p 增大，超界后不可能再合格
            s = p - 64
            if _verify_magic(M, s, d):
                result = (M, s)
                break
    _MAGIC_CACHE[d] = result
    return result

# ---- 常量乘法 -> LEA/移位链 ----
# x86 的 lea 只能算 base + index*scale（scale ∈ 1,2,4,8），延迟 1 周期；
# imul 延迟 3 周期且占用乘法器。热循环里 `x * 13` 这类小常量乘法
# 用 LEA 链能把关键路径直接砍掉 2 周期。
_CHAIN_CACHE = {}


def const_mul_chain(c, max_steps=6, max_frontier=8000):
    """找一条 LEA 链把 x*c 表达成 `p + q*s` 的组合，返回 [(p, q, s, nv), ...]。

    值 1 代表源 x；每步产生的 nv 都是 LEA 可算的形式（p + q*s）。
    找不到（或代价太高）返回 None -> 调用方安全回退 imul。
    """
    if c in _CHAIN_CACHE:
        return _CHAIN_CACHE[c]
    result = None
    if 1 < c < (1 << 40):
        seen = {1}
        frontier = [(1, (1,), [])]
        for _depth in range(max_steps):
            nxt = []
            for _val, avail, chain in frontier:
                done = False
                for p in avail:
                    for q in avail:
                        for s in (1, 2, 4, 8):
                            nv = p + q * s
                            if nv in seen or nv <= 0 or nv > (1 << 40):
                                continue
                            seen.add(nv)
                            nchain = chain + [(p, q, s, nv)]
                            if nv == c:
                                result = nchain
                                done = True
                                break
                            nxt.append((nv, avail + (nv,), nchain))
                        if done:
                            break
                    if done:
                        break
                if done:
                    break
            if result is not None or not nxt:
                break
            if len(nxt) > max_frontier:
                nxt.sort(key=lambda t: abs(t[0] - c))
                nxt = nxt[:max_frontier]
            frontier = nxt
    _CHAIN_CACHE[c] = result
    return result


STACK_SZ = 512 * 1024          # clone() 工作线程栈
CLONE_FLAGS = 0x511            # CLONE_VM|CLONE_FS|CLONE_FILES|SIGCHLD
PROT_RW, MAP_PRIVATE_ANON = 3, 0x22


# ---------------------------------------------------------------------------
# x86-64 编码器
# ---------------------------------------------------------------------------


def rex(w=0, r=0, x=0, b=0):
    v = 0x40 | (w << 3) | ((r >> 3) << 2) | ((x >> 3) << 1) | (b >> 3)
    return bytes([v]) if v != 0x40 else b""


def modrm_reg(reg, rm):
    return bytes([0xC0 | ((reg & 7) << 3) | (rm & 7)])


def modrm_mem(reg, base, index, scale, disp):
    """统一走 [base + index*2^scale + disp32]（SIB 形式）"""
    modrm = bytes([0x80 | ((reg & 7) << 3) | 0x4])          # mod=10, rm=100(SIB)
    sib = bytes([((scale & 3) << 6) | ((index & 7) << 3) | (base & 7)])
    return modrm + sib + struct.pack("<i", disp)


def _emit_divmod10c(f, v, base):
    """非负 v -> (q, ch)：q = v/10、ch = v%10 + base（ASCII 字符）。

    与 `_emit_divmod10` 的区别是**少一个临时值**：直接算
    `ch = (v + base) - q*10`，而不是先算出余数再 `+base`。
    取位循环里同时活着的临时值从 4 个降到 3 个 —— b5_string 的 main 正好
    卡在寄存器池边界上（9 个池寄存器 vs 9 个活值），少一个就能少一次溢出。
    """
    q = f.new_v()
    f.emit("bin", "umulhi", q, v, ("imm", 0xCCCCCCCCCCCCCCCD))
    f.emit("bin", "shr", q, q, ("imm", 3))
    t = f.new_v()
    f.emit("bin", "mul", t, q, ("imm", 10))
    c = f.new_v()
    f.emit("bin", "add", c, v, ("imm", base))
    f.emit("bin", "sub", c, c, t)
    return q, c


def _emit_divmod10(f, v):
    """非负 v -> (q, d)：q = v/10、d = v%10，**不用 idiv**。

    v2.64：`__str_from_i64` / `__print_i64` 的取位循环一直是
    `mod 10` + `div 10` 两条指令 —— 在 x86 上是**两次** `idiv`
    （20-40 周期，还是微码化的）。b5_string 做 50 万次 int→str，
    每个数平均 5.9 位，就是 ~600 万次 idiv。

    换成魔数乘：floor(v/10) == umulhi(v, 0xCCCCCCCCCCCCCCCD) >> 3，
    余数用 `v - q*10` 反算（Granlund-Montgomery，对 64 位全范围成立）。
    两条 idiv → umulhi + shr + imul + sub（4 条，各 3-4 周期，可流水）。

    **前提 v >= 0**：调用点都在"负数已取绝对值"之后（INT64_MIN 单独
    走定值分支），所以无符号魔数是对的。
    """
    q = f.new_v()
    f.emit("bin", "umulhi", q, v, ("imm", 0xCCCCCCCCCCCCCCCD))
    f.emit("bin", "shr", q, q, ("imm", 3))
    t = f.new_v()
    f.emit("bin", "mul", t, q, ("imm", 10))
    d = f.new_v()
    f.emit("bin", "sub", d, v, t)
    return q, d


class Enc:
    """函数级机器码发射器"""

    def __init__(self):
        self.buf = bytearray()
        self.labels = {}          # label -> offset（相对本 code 缓冲）
        self.fixups = []          # (patch_off, label)  rel32

    def pos(self):
        return len(self.buf)

    def emit(self, *chunks):
        for c in chunks:
            self.buf += c if isinstance(c, (bytes, bytearray)) else bytes(c)

    # -- 数据移动 --
    def mov_rr(self, dst, src):
        self.emit(rex(w=1, r=src, b=dst), b"\x89", modrm_reg(src, dst))

    def mov_ri(self, dst, imm):
        if -2**31 <= imm < 2**31:
            self.emit(rex(w=1, b=dst), b"\xc7", modrm_reg(0, dst), struct.pack("<i", imm))
        else:
            self.emit(rex(w=1, b=dst), bytes([0xB8 + (dst & 7)]), struct.pack("<Q", imm & (2**64 - 1)))

    def mov_rm(self, dst, base, index, scale, disp):
        self.emit(rex(w=1, r=dst, x=index, b=base), b"\x8b",
                  modrm_mem(dst, base, index, scale, disp))

    def mov_mr(self, base, index, scale, disp, src):
        self.emit(rex(w=1, r=src, x=index, b=base), b"\x89",
                  modrm_mem(src, base, index, scale, disp))

    def movzx8_rm(self, dst, base, index, scale, disp):
        self.emit(rex(w=1, r=dst, x=index, b=base), b"\x0f\xb6",
                  modrm_mem(dst, base, index, scale, disp))

    def mov32_rm(self, dst, base, index, scale, disp):
        # MOV r32, r/m32（8B /r，无 REX.W——x86-32 位写零扩展到 64 位，
        # u32 语义正是 crc32 这类校验和需要的）
        self.emit(rex(r=dst, x=index, b=base), b"\x8b",
                  modrm_mem(dst, base, index, scale, disp))

    def mov8_mr(self, base, index, scale, disp, src):
        # ⚠ 与 setcc 同一个坑：**字节寄存器 spl/bpl/sil/dil（编号 4..7）必须
        #   强制 REX 前缀**。无 REX 时 `88 /r` 的 reg=4..7 编码成 ah/ch/dh/bh，
        #   于是"存 sil"变成"存 ch"——写进去的是**另一个寄存器的值**。
        #
        # §7.32（v2.59 修）：`mem_store8(p, j, j+10)` 被编成
        #   `mov byte ptr [rbx+rsi], bh`   ← 值在 RDI，却存了 BH
        # 分配器把字节存储的**值**分到 RSI/RDI（caller-saved 的前两个）时
        # 必然触发。若被存的是地址/长度，就是越界写 → 段错误。
        # 所以它是"布局敏感"的：改几行无关代码就可能翻转。
        r = rex(r=src, x=index, b=base)
        if not r and 4 <= (src & 7) <= 7:
            r = b"\x40"
        self.emit(r, b"\x88", modrm_mem(src, base, index, scale, disp))

    def lea(self, dst, base, disp):
        self.emit(rex(w=1, r=dst, b=base), b"\x8d", modrm_mem(dst, base, 4, 0, disp))

    # -- 算术 / 逻辑 --
    ALU = {"add": 0x01, "or": 0x09, "and": 0x21, "sub": 0x29, "xor": 0x31, "cmp": 0x39}
    ALU_EXT = {"add": 0, "or": 1, "and": 4, "sub": 5, "xor": 6, "cmp": 7}

    def alu_rr(self, op, dst, src):
        self.emit(rex(w=1, r=src, b=dst), bytes([self.ALU[op]]), modrm_reg(src, dst))

    def alu_ri(self, op, dst, imm):
        ext = self.ALU_EXT[op]
        if -128 <= imm < 128:
            self.emit(rex(w=1, b=dst), b"\x83", modrm_reg(ext, dst), bytes([imm & 0xFF]))
        else:
            self.emit(rex(w=1, b=dst), b"\x81", modrm_reg(ext, dst), struct.pack("<i", imm))

    def imul_rr(self, dst, src):
        self.emit(rex(w=1, r=dst, b=src), b"\x0f\xaf", modrm_reg(dst, src))

    def mul_u(self, src):
        """无符号单操作数乘：rdx:rax = rax * src（取高 64 位做 mulhi）"""
        self.emit(rex(w=1, b=src), b"\xf7", modrm_reg(4, src))

    def neg(self, dst):
        self.emit(rex(w=1, b=dst), b"\xf7", modrm_reg(3, dst))

    def shl_i(self, dst, imm):
        self.emit(rex(w=1, b=dst), b"\xc1", modrm_reg(4, dst), bytes([imm & 0xFF]))

    def sar_i(self, dst, imm):
        self.emit(rex(w=1, b=dst), b"\xc1", modrm_reg(7, dst), bytes([imm & 0xFF]))

    def shr_i(self, dst, imm):
        self.emit(rex(w=1, b=dst), b"\xc1", modrm_reg(5, dst), bytes([imm & 0xFF]))

    def shift_cl(self, dst, kind):
        ext = {"shl": 4, "shr": 5, "sar": 7}[kind]
        self.emit(rex(w=1, b=dst), b"\xd3", modrm_reg(ext, dst))

    def cqo(self):
        self.emit(b"\x48\x99")

    def idiv(self, src):
        self.emit(rex(w=1, b=src), b"\xf7", modrm_reg(7, src))

    def test_rr(self, a, b):
        self.emit(rex(w=1, r=b, b=a), b"\x85", modrm_reg(b, a))

    def setcc(self, cc, dst8):
        # ⚠ 字节寄存器 spl/bpl/sil/dil（编号 4..7）必须强制 REX 前缀，
        #   否则无 REX 时编码会落到 ah/ch/dh/bh 上。
        if 4 <= dst8 <= 7:
            self.emit(b"\x40", b"\x0f", bytes([CC[cc][1]]), modrm_reg(0, dst8))
        else:
            self.emit(rex(b=dst8), b"\x0f", bytes([CC[cc][1]]), modrm_reg(0, dst8))

    def trunc_reg(self, r, bits, signed):
        """按宽度截断寄存器（v1.8 真实整数宽度）。
        u8/u16 -> movzx r64, r/m8|16；u32 -> mov r32,r32（写 32 位自动清高）
        i8/i16 -> movsx r64, r/m8|16；i32 -> movsxd r64, r/m32"""
        mr = modrm_reg(r, r)          # mod=11, reg=rm=r（rex 内部自己右移 3 位）
        if bits == 32:
            if signed:
                self.emit(rex(w=1, r=r, b=r), b"\x63", mr)   # movsxd r64, r/m32
            else:
                # 32 位写目标隐含零扩展到 64 位
                self.emit(rex(w=0, r=r, b=r), b"\x89", mr)   # mov r32, r32
            return
        op = {8: b"\xB6", 16: b"\xB7"}[bits] if not signed else \
             {8: b"\xBE", 16: b"\xBF"}[bits]
        self.emit(rex(w=1, r=r, b=r), b"\x0F", op, mr)

    def movzx_r_r8(self, dst, src8):
        self.emit(rex(w=1, r=dst, b=src8), b"\x0f\xb6", modrm_reg(dst, src8))

    # ---- SSE2 浮点（x86-64 基线自带 SSE2；xmm0/xmm1/xmm2 作编码期临时）----
    def movq_xr(self, x, r):
        """movq xmm_x, r64（64 位位模式进 XMM）"""
        self.emit(b"\x66", rex(w=1, r=x, b=r), b"\x0f\x6e", modrm_reg(x, r))

    def movq_rx(self, r, x):
        """movq r64, xmm_x"""
        self.emit(b"\x66", rex(w=1, r=x, b=r), b"\x0f\x7e", modrm_reg(x, r))

    def movsd_xm(self, x, base, index, scale, disp):
        """movsd xmm_x, [base + index*2^scale + disp]（F2 0F 10 /r）

        f64 从内存直接进 XMM —— 以前是 `mov gpr,[mem]` + `movq xmm,gpr`
        两条，且要过一趟 GPR 的存储转发。
        """
        self.emit(b"\xf2", rex(r=x, x=index, b=base), b"\x0f\x10",
                  modrm_mem(x, base, index, scale, disp))

    def movsd_mx(self, base, index, scale, disp, x):
        """movsd [base + index*2^scale + disp], xmm_x（F2 0F 11 /r）"""
        self.emit(b"\xf2", rex(r=x, x=index, b=base), b"\x0f\x11",
                  modrm_mem(x, base, index, scale, disp))

    def movaps_rr(self, xd, xs):
        """整 128 位寄存器搬移（0F 28 /r）。

        **不能用 movsd xmm,xmm**：那是部分寄存器写，高 64 位保留 ⇒ 有假依赖
        （v2.56 在 qlmc 上踩过：让每轮除法都等上一轮除法写完）。
        """
        self.emit(rex(r=xd, b=xs), b"\x0f\x28", modrm_reg(xd, xs))

    def movups_xm(self, x, base, index, scale, disp):
        """movups xmm_x, [mem]（0F 10 /r，无前缀）—— 保存非易失 XMM 用。
        帧里的保存区不保证 16 字节对齐，所以用 unaligned 形式。"""
        self.emit(rex(r=x, x=index, b=base), b"\x0f\x10",
                  modrm_mem(x, base, index, scale, disp))

    def movups_mx(self, base, index, scale, disp, x):
        """movups [mem], xmm_x（0F 11 /r）"""
        self.emit(rex(r=x, x=index, b=base), b"\x0f\x11",
                  modrm_mem(x, base, index, scale, disp))

    def pxor_rr(self, xd, xs):
        """pxor xmm_xd, xmm_xs（66 0F EF /r）——整 128 位写，用来断开假依赖"""
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\xef", modrm_reg(xd, xs))

    # ---- SSE2 打包（v1.8 @simd）----
    def pxor_x(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\xef", modrm_reg(xd, xs))

    # ---- SHA-NI 指令族（v1.15，CPUID leaf 7 EBX[29]）----
    # 全部 xmm-xmm reg,rm 形态（WIG：无需 REX.W），操作数是 xmm 槽号 0-7。
    # 隐含操作数：sha256rnds2 固定用 XMM0 作为消息调度输入（Intel 约定）。
    def sha256rnds2(self, xd, xs):
        # F2 0F 38 CB /r：xmd = rounds(xmd, xms, XMM0)
        self.emit(b"\xf2", rex(r=xd, b=xs), b"\x0f\x38\xcb", modrm_reg(xd, xs))

    def sha256msg1(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x38\xcc", modrm_reg(xd, xs))

    def sha256msg2(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x38\xcd", modrm_reg(xd, xs))

    def sha256nexte(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x38\xce", modrm_reg(xd, xs))

    # -- AES-NI（AESENC 族，66 0F 38 DC..DF /r；AESIMC DB；AESKEYGENASSIST 66 0F 3A DF /r ib）--
    def aesenc(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x38\xdc", modrm_reg(xd, xs))

    def aesenclast(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x38\xdd", modrm_reg(xd, xs))

    def aesdec(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x38\xde", modrm_reg(xd, xs))

    def aesdeclast(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x38\xdf", modrm_reg(xd, xs))

    def aesimc(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x38\xdb", modrm_reg(xd, xs))

    def aeskeygenassist(self, xd, xs, imm):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x3a\xdf",
                  modrm_reg(xd, xs), bytes([imm & 0xFF]))

    # -- SSE2 / SSSE3 / PCLMULQDQ（v1.33，GHASH 用）--
    def movdqa_rr(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x6f", modrm_reg(xd, xs))

    def pand(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\xdb", modrm_reg(xd, xs))

    def por(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\xeb", modrm_reg(xd, xs))

    def pshufb(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x38\x00", modrm_reg(xd, xs))

    def pclmulqdq(self, xd, xs, imm):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x3a\x44",
                  modrm_reg(xd, xs), bytes([imm & 0xFF]))

    # 立即数形式：66 0F 71/72/73 + modrm(/group) + imm8（组号决定具体指令）
    def _sse_shift_imm(self, group, opcode, xd, imm):
        self.emit(b"\x66", rex(b=xd), opcode, modrm_reg(group, xd), bytes([imm & 0xFF]))

    def psrlw_i(self, xd, imm):
        self._sse_shift_imm(2, b"\x0f\x71", xd, imm)

    def psllw_i(self, xd, imm):
        self._sse_shift_imm(6, b"\x0f\x71", xd, imm)

    def psrlq_i(self, xd, imm):
        self._sse_shift_imm(2, b"\x0f\x73", xd, imm)

    def psllq_i(self, xd, imm):
        self._sse_shift_imm(6, b"\x0f\x73", xd, imm)

    def pslldq_i(self, xd, imm):
        self._sse_shift_imm(7, b"\x0f\x73", xd, imm)

    def psrldq_i(self, xd, imm):
        self._sse_shift_imm(3, b"\x0f\x73", xd, imm)

    def paddd(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\xfe", modrm_reg(xd, xs))

    def pshufd(self, xd, xs, imm):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x70", modrm_reg(xd, xs),
                  bytes([imm & 0xFF]))

    def palignr(self, xd, xs, imm):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x3a\x0f", modrm_reg(xd, xs),
                  bytes([imm & 0xFF]))

    # ---- f64 packed（v1.16 @simd f64 归约）----
    def movupd_rm(self, x, base, index, scale, disp):
        """movupd xmm, [base + index*2^scale + disp]（非对齐读）"""
        self.emit(b"\x66", rex(r=x, x=index, b=base), b"\x0f\x10",
                  modrm_mem(x, base, index, scale, disp))

    def addpd(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x58", modrm_reg(xd, xs))

    def movhlps(self, xd, xs):
        """xd[63:0] = xs[127:64]（无前缀 0F 12 /r）"""
        self.emit(rex(r=xd, b=xs), b"\x0f\x12", modrm_reg(xd, xs))

    def addsd(self, xd, xs):
        self.emit(b"\xf2", rex(r=xd, b=xs), b"\x0f\x58", modrm_reg(xd, xs))

    def mulpd(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x59", modrm_reg(xd, xs))

    def mulsd(self, xd, xs):
        self.emit(b"\xf2", rex(r=xd, b=xs), b"\x0f\x59", modrm_reg(xd, xs))

    def movdqu_mr(self, base, index, scale, disp, x):
        """movdqu [base + index*2^scale + disp], xmm（非对齐存储）"""
        self.emit(b"\x66", rex(r=x, x=index, b=base), b"\x0f\x7f",
                  modrm_mem(x, base, index, scale, disp))

    def cpuid(self):
        self.emit(b"\x0f\xa2")

    def movdqu_rm(self, x, base, index, scale, disp):
        """movdqu xmm, [base + index*2^scale + disp]（非对齐）"""
        self.emit(b"\xf3", rex(r=x, x=index, b=base), b"\x0f\x6f",
                  modrm_mem(x, base, index, scale, disp))

    def paddq(self, xd, xs):
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\xd4", modrm_reg(xd, xs))

    def pmuludq(self, xd, xs):
        """PMULUDQ xmm1, xmm2/m128（66 0F F4 /r，SSE2）。

        取每个 64 位通道的**低 32 位**做无符号 32x32 -> 64 乘法，结果写回
        同一 64 位通道（高 32 位通道 d1/d3 被忽略）。64 位整数乘法在
        SSE2/SSE4.1 里没有单指令（pmulld 是 32x32->低32、pmuldq 只算
        偶数 32 位通道），`vdot` 用三次本指令拼出 64x64->低64。"""
        self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\xf4", modrm_reg(xd, xs))

    def psrldq(self, x, imm):
        self.emit(b"\x66", rex(b=x), b"\x0f\x73", modrm_reg(3, x), bytes([imm & 0xFF]))

    def movd_xr(self, x, r):
        """movd xmm_x, r32（f32 低 32 位）"""
        self.emit(b"\x66", rex(r=x, b=r), b"\x0f\x6e", modrm_reg(x, r))

    def movd_rx(self, r, x):
        """movd r32, xmm_x（写 r32 高 32 位自动清零）"""
        self.emit(b"\x66", rex(r=x, b=r), b"\x0f\x7e", modrm_reg(x, r))

    def fp_alu(self, w, op, xd, xs):
        """addsd/subsd/mulsd/divsd（w=f64）或 addss/...（w=f32）：xd = xd OP xs"""
        pfx = b"\xf2" if w == "f64" else b"\xf3"
        opc = {"add": b"\x58", "sub": b"\x5c", "mul": b"\x59", "div": b"\x5e"}[op]
        self.emit(pfx, rex(r=xd, b=xs), b"\x0f", opc, modrm_reg(xd, xs))

    def fp_cmp(self, w, xd, xs):
        """comisd（66 0F 2F）/ comiss（0F 2F）——设置 EFLAGS，PF=1 无序/NaN。
        注意与算术指令不同：比较指令的双/单精度靠 66 前缀区分，无 F2/F3。"""
        if w == "f64":
            self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x2f", modrm_reg(xd, xs))
        else:
            self.emit(rex(r=xd, b=xs), b"\x0f\x2f", modrm_reg(xd, xs))

    def fp_xor(self, w, xd, xs):
        """xorpd（f64）/ xorps（f32）—— fneg 用符号位掩码：xd ^= xs"""
        if w == "f64":
            self.emit(b"\x66", rex(r=xd, b=xs), b"\x0f\x57", modrm_reg(xd, xs))
        else:
            self.emit(rex(r=xd, b=xs), b"\x0f\x57", modrm_reg(xd, xs))

    def cvt(self, kind, xd_or_r, xs_or_r):
        """标量转换：
        i2f64: cvtsi2sd xmm, r64   i2f32: cvtsi2ss xmm, r64
        f64i:  cvttsd2si r64, xmm  f32i:  cvttss2si r64, xmm
        f32f64: cvtss2sd xmm, xmm  f64f32: cvtsd2ss xmm, xmm"""
        if kind == "i2f64":
            self.emit(b"\xf2", rex(w=1, r=xd_or_r, b=xs_or_r), b"\x0f\x2a",
                      modrm_reg(xd_or_r, xs_or_r))
        elif kind == "i2f32":
            self.emit(b"\xf3", rex(w=1, r=xd_or_r, b=xs_or_r), b"\x0f\x2a",
                      modrm_reg(xd_or_r, xs_or_r))
        elif kind == "f64i":
            self.emit(b"\xf2", rex(w=1, r=xd_or_r, b=xs_or_r), b"\x0f\x2c",
                      modrm_reg(xd_or_r, xs_or_r))
        elif kind == "f32i":
            self.emit(b"\xf3", rex(w=1, r=xd_or_r, b=xs_or_r), b"\x0f\x2c",
                      modrm_reg(xd_or_r, xs_or_r))
        elif kind == "f32f64":
            self.emit(b"\xf3", rex(r=xs_or_r, b=xd_or_r), b"\x0f\x5a",
                      modrm_reg(xs_or_r, xd_or_r))
        elif kind == "f64f32":
            self.emit(b"\xf2", rex(r=xs_or_r, b=xd_or_r), b"\x0f\x5a",
                      modrm_reg(xs_or_r, xd_or_r))
        else:
            raise RuntimeError(f"未知 fcvt {kind}")

    # -- 控制流 --
    def jmp(self, label):
        self.emit(b"\xe9")
        self.fixups.append((self.pos(), label))
        self.emit(b"\x00\x00\x00\x00")

    def jcc(self, cc, label):
        self.emit(b"\x0f", bytes([CC[cc][0]]))
        self.fixups.append((self.pos(), label))
        self.emit(b"\x00\x00\x00\x00")

    def call(self, label):
        self.emit(b"\xe8")
        self.fixups.append((self.pos(), label))
        self.emit(b"\x00\x00\x00\x00")

    def call_reg(self, reg):
        # FF /2：间接调用（call rax 形态）。modrm reg 字段 = 2（/2 = CALL），
        # rm 字段 = 目标寄存器；reg >= 8 时 REX.B 扩展 rm。
        self.emit(rex(b=reg), b"\xff", modrm_reg(2, reg))

    def cmov(self, cc, dst, src):
        # 0F 4x /r（x = 条件码）：CMOVne = 0F45、CMOVns = 0F49。64 位
        # 寄存器-寄存器需 REX.W；REX.R 扩展 reg 字段（dst），REX.B 扩展 rm（src）。
        code = {"e": 4, "ne": 5, "s": 8, "ns": 9}.get(cc, 5)
        self.emit(rex(w=1, r=dst, b=src), b"\x0f",
                  bytes([0x40 + code]), modrm_reg(dst, src))

    def ret(self):
        self.emit(b"\xc3")

    def syscall(self):
        self.emit(b"\x0f\x05")

    def push(self, r):
        self.emit(rex(b=r), bytes([0x50 + (r & 7)]))

    def pop(self, r):
        self.emit(rex(b=r), bytes([0x58 + (r & 7)]))

    def lea3(self, dst, base, index, scale):
        """dst = base + index * scale（scale ∈ 1,2,4,8），延迟 1 周期（imul 为 3）

        固定用 mod=01 + disp8=0：这样 base 为 rbp/r13 时也不会被编码成
        「无 base + disp32」的歧义形式。
        """
        sc = {1: 0, 2: 1, 4: 2, 8: 3}[scale]
        self.emit(rex(w=1, r=dst, x=index, b=base), b"\x8d",
                  bytes([0x40 | ((dst & 7) << 3) | 0x4]),
                  bytes([(sc << 6) | ((index & 7) << 3) | (base & 7)]),
                  b"\x00")

    def xchg_mr(self, base, index, scale, disp, src):
        """原子交换：*[base+index*scale+disp] <-> src（x86 隐含 LOCK）

        用于通道自旋锁：`xchg [lock], 1` 返回旧值，0 表示抢锁成功。
        """
        self.emit(rex(w=1, r=src, x=index, b=base), b"\x87",
                  modrm_mem(src, base, index, scale, disp))

    def xadd_mr(self, base, index, scale, disp, src):
        """lock xadd [mem], src：*mem += src，src 返回**旧值**（fetch-and-add）。

        无锁计数器 / 队列序号的地基。lock 前缀必须在 REX 之前（F0 48 0F C1 /r）。
        """
        self.emit(b"\xf0", rex(w=1, r=src, x=index, b=base), b"\x0f\xc1",
                  modrm_mem(src, base, index, scale, disp))

    def cmpxchg_mr(self, base, index, scale, disp, src):
        """lock cmpxchg [mem], src：RAX(期望值) 与 *mem 比较；相等则 *mem=src
        且 ZF=1，否则 RAX=*mem（取回旧值）。CAS 循环的地基。

        注意期望值固定走 RAX（ACC），调用方负责先物化。
        """
        self.emit(b"\xf0", rex(w=1, r=src, x=index, b=base), b"\x0f\xb1",
                  modrm_mem(src, base, index, scale, disp))

    def mfence(self):
        """全内存屏障：串行化本核所有 load/store（SSE2，0F AE F0）。"""
        self.emit(b"\x0f\xae\xf0")

    def pause(self):
        """自旋等待提示（F3 90，rep nop）：降功耗 + 避免内存序消歧流水线清空。"""
        self.emit(b"\xf3\x90")

    def rdtsc(self):
        """读周期计数器（0F 31）：EDX = 高 32 位，EAX = 低 32 位。

        32 位寄存器写入会把 64 位寄存器高半清零，所以 rdtsc 后
        RAX/RDX 各自就是干净的 32 位值。RDX 不在分配池（仅传参用），
        覆盖安全；RAX=ACC 是编码期临时，跨指令不驻留。
        """
        self.emit(b"\x0f\x31")

    def resolve(self):
        for patch, label in self.fixups:
            target = self.labels[label]
            struct.pack_into("<i", self.buf, patch, target - (patch + 4))
        self.fixups = []


# ---------------------------------------------------------------------------
# QuIR：函数 = vreg + 指令列表（非 SSA，可变量原地更新，无 phi）
# 指令：
#   ('mov', dst, src)                  src: vreg | ('imm',n) | ('ga',gid)
#   ('bin', op, dst, a, b)             op: add sub mul div mod and or xor shl shr sar
#   ('neg'/'not', dst, a)
#   ('cmpset', cc, dst, a, b)          dst = (a cc b) ? 1 : 0
#   ('label', L) ('jmp', L) ('jz', a, L) ('jnz', a, L) ('jcc', cc, a, b, L)
#   ('call', dst|None, fname, [args])
#   ('callr', dst|None, fnspec, [args])  间接调用：fnspec 为 vreg / ('fnaddr',name) / ('ga',gid)
#   ('cssub', dst, a, b)                 dst = (a >= b) ? a - b : a（有符号；
#                                        a-b 须不溢出；回绕用法 a∈[0,2b) 天然满足）
#   ('ret', op|None)
#   ('load'/'load8', dst, base, idx)   dst = [base + idx*8] / 字节
#   ('store'/'store8', base, idx, src)
#   ('movaddr', dst, gid)              dst = &global[gid]
#   ('frameaddr', dst, word)           dst = &frame_struct_area[word]（结构体局部量）
#   ('syscall', dst|None, num, [6 args])   Linux raw syscall
#   ('winapi', dst|None, name, [args])     Windows kernel32 导入调用（Win64 ABI）
#   ('args', [dsts])                   形参从标准参数寄存器搬入
#   ('winargs', [dsts])                ThreadProc 形参从 Win64 参数寄存器搬入
# ---------------------------------------------------------------------------


class Fn:
    def __init__(self, name):
        self.name = name
        self.instrs = []
        self.nv = 0
        self.label_id = 0
        self.frame_words = 0      # 结构体局部区占用的 8 字节字数
        self.structv = {}         # vreg -> 结构体名（该 vreg 持有结构体首地址）
        self.no_inline = False    # 禁止被内联（parfor worker 必须保留独立栈帧）
        self.iface_fresh = set()  # 接口值槽：持有"新建装箱"的 rc=1（v1.81）
        self.iface_own = set()    # 接口值槽：拥有一个计数（作用域尾释放）
        # v1.95 闭包签名表：closure 值 vreg -> (形参表, 返回类型)。
        # 只在"同一函数内由 lambda 字面量直接创建"的闭包上有值——跨函数传递
        # 后签名不可知，调用点退回"按标量处理"（与 callr 同一口径）。
        self.closig = {}
        # v2.03：本函数里被内联进来的 callee（增量失效要顺着这张表传播）
        self.inlined_from = set()
    def new_v(self):
        self.nv += 1
        return self.nv - 1

    def new_struct_slot(self, words):
        """在帧上开一段 words*8 字节的结构体存储，返回起始字下标"""
        base = self.frame_words
        self.frame_words += words
        return base

    def emit(self, *ins):
        self.instrs.append(tuple(ins))

    def label(self, hint):
        self.label_id += 1
        return f"{self.name}.{hint}.{self.label_id}"


# ---------------------------------------------------------------------------
# 降级：AST -> QuIR
# ---------------------------------------------------------------------------


# 切片 `[]T` = {ptr, len} 两字：word0 指向元素序列，word1 是元素个数。
# 与结构体/枚举一样走聚合 ABI（隐藏出参指针返回 / 地址传递），
# 因此作函数参数/返回值零改动复用。
SLICE_WORDS = 2


# v1.33：GHASH 用的 SSE 族（xmm 槽 + 立即数），与 AES 族分开登记便于排查
_SSE_BUILTINS = ("cpu_pclmul", "xmm_mov", "pand", "por", "pshufb", "pclmulqdq",
                 "psrlw", "psllw", "psrlq", "psllq", "pslldq", "psrldq")

_XMM_BUILTINS = ("cpu_sha", "cpu_aes", "xmm_load", "xmm_store",
                  "sha_nexte", "sha_rnds2",
                  "aesenc", "aesenclast", "aesdec", "aesdeclast", "aesimc",
                  "aeskeygenassist",
                 "sha_msg1", "sha_msg2", "xmm_paddd", "xmm_pxor",
                 "xmm_pshufd", "xmm_palignr")


class Lower:
    def __init__(self, fns_ast, cfg, arch="x86_64", structs=None, enums=None,
                 platform="linux", asset_root=None, dbg=False, dbg_main=None,
                 dbg_src=None, drop_fns=None, seed=None):
        self.fns_ast = {f["name"]: f for f in fns_ast}
        self.cfg = cfg
        self.arch = arch
        self.platform = platform          # linux | windows
        self.sc = SYSCALLS[arch]
        self.structs = structs or {}
        self.enums = enums or {}
        # v1.62 调试信息：dbg=True 时发射 ('line', n) / ('dbgvar', name, vreg)
        # 标记（源码行表 + 变量位置表的数据源）。dbg_main = 主文件定义的
        # 函数名集合（import 的库函数不给行号——行号属于别的文件）。
        self.dbg = dbg
        self.dbg_main = dbg_main or set()
        self.dbg_src = dbg_src
        self.loop_stack = []       # [(cont_label, break_label, defer_depth)]，供 break/continue
        # v1.48 defer：每块一帧 {"slots": [登记标志], "entries": [(stmt, env, flag)], "cursor": n}
        # 标志位初始 0、执行到 defer 语句置 1，退出点按 LIFO 逐条"标志为 1 才执行"。
        self.defer_stack = []
        # v1.93 Drop：类型名 -> 析构函数名（`impl T : Drop { fn drop(t: T) }`）。
        # 与 defer_stack **同进同出**（都在 block() 里 push/pop），因此
        # loop_stack 里记的 defer 深度可以同时当 drop 深度用。
        # drop_fns 由 lower_and_optimize 在**全局 DCE 之前**算好传进来：
        # DCE 只从 main 出发找可达函数，而析构是隐式调用（AST 里没有 call
        # 节点），在 DCE 之后再算会把析构函数当死代码删掉。
        self.drop_fns = dict(drop_fns) if drop_fns is not None \
            else drop_table(fns_ast)
        self.drop_stack = []       # 每块一帧 [(帧槽地址, 类型名)]，按绑定顺序
        # v1.81 接口值所有权：语句临时槽（调用实参/返回槽）与作用域 owned 槽
        self.iface_temps = []
        self.iface_scope = []
        self.uses_iface_rc = False
        self.out = []
        # v2.03 `.qla` 复用：把档案里的全局数据区原样接过来（复用 IR 里的
        # ("ga", gid) 就是按这张表编号的），新 intern 的块追加在后面。
        # seed 为 None 时就是空表——默认构建一个字节都不变。
        self.globals = [bytes(g) for g in (seed or {}).get("globals", ())]
        # 字符串字面量 -> gid 也要接回来：否则重降级的函数会把同一份字面量
        # 再 intern 一遍（数据区里出现重复块，产物与全量构建不一致）。
        self.gid_of_str = dict((seed or {}).get("strmap") or {})
        self._seed_special = dict((seed or {}).get("special") or {})
        # 惰性创建的进程级单例（static_word / 空闲链 / args 拷贝标志）：
        # 档案里已有就**预先挂上**，否则全量复用时不调用 getter 就会丢条目
        for _nm, _attr in (("static", "_static_gid"), ("free", "free_gid"),
                           ("args_copied", "_args_copied_gid")):
            if _nm in self._seed_special:
                setattr(self, _attr, self._seed_special[_nm])
        _ctr = (seed or {}).get("counters") or {}
        self.reuse_fns = {}        # name -> Fn（来自 .qla，已降级+已优化）
        self.qla_stubs = {}        # name -> (params, ret)：只声明，链接期解析
        self.fn_needs = {}         # name -> [uses_* 标志名]：增量复用的前提
        self.fn_owner = {}         # 合成函数 -> 它属于哪个源码函数
        self._cur_owner = None     # 正在降级的源码函数名（lambda 队列用）
        self.lam_seq = _ctr.get("lam_seq", 0)
        self.spawn_id = _ctr.get("spawn_id", 0)
        self.uses_chan = False
        self.uses_udp = False
        self.uses_wall = False
        self.asset_root = asset_root  # [src].asset（read_asset 基准，编译期嵌入）
        self.arr_elem = {}         # base vreg -> 元素类型（"f64"）；f64 数组的
                                   # index/arith 位模式链路依赖此标记
        self.arr_narrow = {}       # base vreg -> (bits, signed)；窄元素数组的
                                   # 下标赋值/整体赋值按声明宽度截断（v1.40）
        self.uses_map = False
        self.uses_arena = False
        self.uses_join = False
        self.uses_bounds = False
        self.uses_f64_str = False
        self.uses_str_to_int = False
        self.uses_args = False
        self.uses_io = False
        self.uses_net = False
        self.uses_threads = False   # v2.12：thread_start 起的线程 -> 分配器加锁
        self.uses_sfb = False
        self.uses_strmem = False
        self.uses_memcpy = False
        self.uses_substr = False
        self.uses_str_cmp = False
        self.uses_vec = False
        # v1.87 FFI：@ffi("dll"[, "Sym"]) 声明的函数表。
        # name -> (dll, sym, [形参类], 返回类)；形参/返回类是 "int"/"bool"/
        # "f64"/"f32"/"void"（解析期已白名单，见 qlm.py::Parser._bind_ffi）。
        self.ffi_decls = {}
        # v1.95 闭包：lambda 体在"外层函数降级完"之后统一降级（避免嵌套降级
        # 覆盖 fn_ret_agg / loop_stack 等按函数保存的状态）；计数器给合成名。
        self.pending_lambdas = []
        self.lam_seq = _ctr.get("lam_seq", 0)
        # v1.5 内存/时间内建：按需发射（未用到的程序体积零变化）
        self.uses_peer = False           # v2.07 tcp_peer_raw（依赖 __str_from_mem）
        self.uses_memset = False
        self.uses_memcmp = False
        self.uses_memchr = False
        self.uses_memdiff = False
        self.uses_mem_to_str = False
        self.uses_realloc = False
        self.uses_free = False
        self.uses_now = False
        self.uses_cpu = False
        # 命令行参数（args()）：argc 字数 + argv 指针，入口期或惰性初始化填入
        self.argc_gid = self._seed_gid("argc", 1)
        self.argv_gid = self._seed_gid("argv", 1)
        if platform == "windows":
            # WriteFile 的 lpNumberOfBytesWritten 落点（Win32 必须给非空指针）
            self.written_gid = self._seed_gid("written", 1)
            # 已 MEM_COMMIT 的字节数（Windows 按 1MB 粒度按需提交）
            self.committed_gid = self._seed_gid("committed", 1)

    def _seed_gid(self, name, words):
        """进程级单例全局字：档案里已有就沿用它的 gid（复用 IR 按老 gid
        引用，重开一份会让 `args()` / `static_word` 读到两份不同的存储），
        没有才新开一块。"""
        gid = self._seed_special.get(name)
        if isinstance(gid, int) and 0 <= gid < len(self.globals):
            return gid
        return self.intern_array(words)
    def static_gid(self):
        """进程级静态字区（static_word(i) 的落点，32 个字）。"""
        if getattr(self, "_static_gid", None) is None:
            self._static_gid = self._seed_gid("static", 32)
        return self._static_gid

    def free_list_gid(self):
        """尺寸类空闲链的表头数组（__alloc 与 __free 必须共用同一份）。"""
        if getattr(self, "free_gid", None) is None:
            self.free_gid = self._seed_gid("free", FREE_CLASSES)
        return self.free_gid

    def args_copied_gid(self):
        """unix argv 前缀拷贝的 once 标志（0 = 未拷贝）。"""
        if getattr(self, "_args_copied_gid", None) is None:
            self._args_copied_gid = self._seed_gid("args_copied", 1)
        return self._args_copied_gid

    # ---- 结构体/枚举布局（字段一律占一个 8 字节槽；嵌套聚合占连续多个槽）----
    def is_agg(self, name):
        return name in self.structs or name in self.enums

    def field_words(self, t):
        return self.type_words(t)

    def type_words(self, t):
        """类型元组 -> 占用字数（切片恒为 2 字 {ptr,len}）"""
        if not t:
            return 1
        if t[0] == "slice":
            return SLICE_WORDS
        if t[0] == "named" and self.is_agg(t[1]):
            return self.agg_size(t[1])
        return 1

    def is_agg_type(self, t):
        """是否走聚合 ABI（隐藏出参指针返回 / 地址传递）"""
        if not t:
            return False
        if t[0] == "slice":
            return True
        return t[0] == "named" and self.is_agg(t[1])

    def struct_size(self, sname):
        fields = self.structs.get(sname)
        if fields is None:
            raise SyntaxError(f"未声明的结构体 {sname}")
        return sum(self.field_words(t) for _, t in fields)

    def enum_size(self, ename):
        """枚举值布局：字 0 = tag，字 1.. = 载荷（各变体共用最大槽位）"""
        variants = self.enums.get(ename)
        if variants is None:
            raise SyntaxError(f"未声明的枚举 {ename}")
        payload = max((sum(self.field_words(t) for _, t in vf) for _, vf in variants),
                      default=0)
        return 1 + payload

    def agg_size(self, name):
        return self.struct_size(name) if name in self.structs else self.enum_size(name)

    def enum_variant(self, ename, vname):
        for i, (vn, vf) in enumerate(self.enums[ename]):
            if vn == vname:
                return i, vf
        raise SyntaxError(f"枚举 {ename} 没有变体 {vname}")

    def field_offset(self, sname, fname):
        """返回 (字下标, 字段类型)"""
        if sname in self.enums:
            raise SyntaxError(f"枚举 {sname} 不能按字段访问，请用 match 解构")
        off = 0
        for n, t in self.structs.get(sname, []):
            if n == fname:
                return off, t
            off += self.field_words(t)
        raise SyntaxError(f"结构体 {sname} 没有字段 {fname}")

    def dbg_struct_layout(self):
        """v1.62 调试信息：结构体布局表 {名字: {words, [[字段, 类型, 字偏移]]}}。

        字段偏移规则与 struct_size/field_offset 同源（type_words），
        不在调试器侧重算——避免两边规则漂移。"""
        out = {}
        for name, fields in self.structs.items():
            fl, off = [], 0
            for fname, fty in fields:
                fl.append([fname, self.dbg_type_str(fty), off])
                off += self.field_words(fty)
            out[name] = {"words": off, "fields": fl}
        return out

    @staticmethod
    def dbg_type_str(t):
        """类型元组 -> 调试信息里的短类型名（struct/slice/标量）"""
        if not isinstance(t, tuple) or not t:
            return "?"
        if t[0] == "named":
            return t[1]
        if t[0] == "slice":
            return "slice"
        return t[0]

    # ---- 结构体值跟踪 ----
    @staticmethod
    def _mark_struct(fn, v, sname):
        if isinstance(v, int):
            fn.structv[v] = sname
        return v

    @staticmethod
    def _struct_of(fn, v):
        return fn.structv.get(v) if isinstance(v, int) else None

    def struct_copy(self, fn, dst, src, sname):
        """按值拷贝 words 个字（src/dst 都是地址；枚举/结构体共用）"""
        self.words_copy(fn, dst, src, self.agg_size(sname))

    def words_copy(self, fn, dst, src, w):
        """按值拷贝 w 个字（src/dst 都是地址；切片也用它）"""
        for i in range(w):
            t = fn.new_v()
            fn.emit("load", t, src, ("imm", i))
            fn.emit("store", dst, ("imm", i), t)

    def alloc_struct(self, fn, sname, words=None):
        """开一段新帧槽并返回其地址"""
        w = self.agg_size(sname) if words is None else words
        return self._mark_struct(fn, self.alloc_words(fn, w), sname)

    def alloc_words(self, fn, w):
        base = fn.new_struct_slot(w)
        addr = fn.new_v()
        fn.emit("frameaddr", addr, base)
        return addr

    # ---- 切片（v0.9）：{ptr, len} 两字零拷贝视图 ----
    # ---- rc[T] 引用计数句柄（v1.8）----
    @staticmethod
    def _mark_rc(fn, v, sname):
        if isinstance(v, int):
            if not hasattr(fn, "rcv"):
                fn.rcv = {}
            fn.rcv[v] = sname
        return v

    @staticmethod
    def _rc_of(fn, v):
        return getattr(fn, "rcv", {}).get(v) if isinstance(v, int) else None

    @staticmethod
    def _mark_slice(fn, v, elem=None):
        if isinstance(v, int):
            if not hasattr(fn, "slicev"):
                fn.slicev = set()
            fn.slicev.add(v)
            if elem is not None:
                if not hasattr(fn, "slice_elem"):
                    fn.slice_elem = {}
                fn.slice_elem[v] = elem
        return v

    @staticmethod
    def _is_slice(fn, v):
        return isinstance(v, int) and v in getattr(fn, "slicev", set())

    @staticmethod
    def _slice_elem(fn, v):
        """切片元素标签：'str' / 'u8' 等窄类型名 / 'f64' / None（未知）。

        v1.56 起窄元素也带标签：切片是零拷贝别名，写入必须按元素声明宽度截断，
        否则 `slice_of(u8数组)` 后 s[i] = 300 会把 300 原样写进槽（读回还是 300）。
        """
        return getattr(fn, "slice_elem", {}).get(v) if isinstance(v, int) else None

    def alloc_slice(self, fn):
        """开一段 2 字帧槽作为切片值（word0=ptr, word1=len）"""
        return self._mark_slice(fn, self.alloc_words(fn, SLICE_WORDS))

    def make_slice(self, fn, ptr, length, elem=None):
        """由指针 + 长度构造切片值（零拷贝）"""
        s = self.alloc_slice(fn)
        if elem is not None:
            self._mark_slice(fn, s, elem)
        fn.emit("store", s, ("imm", 0), ptr)
        fn.emit("store", s, ("imm", 1), length)
        return s

    def slice_ptr(self, fn, s):
        p = fn.new_v()
        fn.emit("load", p, s, ("imm", 0))
        return p

    def slice_len(self, fn, s):
        n = fn.new_v()
        fn.emit("load", n, s, ("imm", 1))
        return n

    def str_len(self, fn, p):
        """str 的字节长度（v1.5.1 长度前缀 ABI）：str 值指向字节，
        长度 word 就在指针前 8 字节——O(1) 加载，不再扫 NUL。
        布局与 __str_len 运行时函数一致：[len][bytes][NUL]。"""
        t = fn.new_v()
        fn.emit("bin", "sub", t, p, ("imm", 8))
        n = fn.new_v()
        fn.emit("load", n, t, ("imm", 0))
        return n

    def lower_args(self, fn):
        """args() -> []str：程序参数，不含程序名。

        两条路径产出的 argv 表**含义不同**，这里必须分开取基址（v2.90 修）：

        Linux/AArch64：`__unix_args_copy` 把内核栈上的原始 argv **原地改写**成
          "已排除程序名"的长度前缀表——`arr0[i]` 就是第 i 个参数（i 从 0 起），
          同时把 `argc` 覆写成 `argc-1`。所以基址**不加 8**、长度**不再减 1**。
        Windows：`__win_args_init` 把完整命令行（含程序名）拆成 `argc` 个 token，
          `argv[0]` 仍是程序名。所以基址 `+8`、长度 `argc-1`。

        v2.89 及以前两条路径共用 `argv+8` / `argc-1`，Linux 上于是**双重偏移**：
        `args()` 少一个参数、`args()[0]` 读到表尾之后（越界读，实测 SIGSEGV）。
        """
        if self.platform == "windows":
            cur = fn.new_v()
            fn.emit("load", cur, ("ga", self.argv_gid), ("imm", 0))
            l_ready = fn.label("argsin")
            fn.emit("jnz", cur, l_ready)
            fn.emit("call", None, "__win_args_init", [])
            fn.emit("label", l_ready)
            argc = fn.new_v()
            argv = fn.new_v()
            fn.emit("load", argc, ("ga", self.argc_gid), ("imm", 0))
            fn.emit("load", argv, ("ga", self.argv_gid), ("imm", 0))
            cnt = fn.new_v()
            fn.emit("bin", "sub", cnt, argc, ("imm", 1))
            l_ok = fn.label("argcok")
            fn.emit("jcc", "ge", cnt, ("imm", 0), l_ok)
            fn.emit("mov", cnt, ("imm", 0))
            fn.emit("label", l_ok)
            ptr = fn.new_v()
            fn.emit("bin", "add", ptr, argv, ("imm", 8))
            return self.make_slice(fn, ptr, cnt, elem="str")
        # 内核 argv 是原始串；首次 args() 统一拷贝为长度前缀 str（once）。
        # 拷贝后：argv_gid 指向"已排除程序名"的新表（长度 argc-1），
        # 但 argc_gid **仍是内核口径**（含程序名），所以长度还要减 1、基址不加 8。
        fn.emit("call", None, "__unix_args_copy", [])
        argc = fn.new_v()
        argv = fn.new_v()
        fn.emit("load", argc, ("ga", self.argc_gid), ("imm", 0))
        fn.emit("load", argv, ("ga", self.argv_gid), ("imm", 0))
        cnt = fn.new_v()
        fn.emit("bin", "sub", cnt, argc, ("imm", 1))
        l_ok = fn.label("argcok")
        fn.emit("jcc", "ge", cnt, ("imm", 0), l_ok)
        fn.emit("mov", cnt, ("imm", 0))
        fn.emit("label", l_ok)
        return self.make_slice(fn, argv, cnt, elem="str")

    # ---- 定长数组（v0.6）：帧槽 N 字 + 值语义拷贝 ----
    @staticmethod
    def _mark_arr(fn, v, n):
        if isinstance(v, int):
            if not hasattr(fn, "arrv"):
                fn.arrv = {}
            fn.arrv[v] = n
        return v

    @staticmethod
    def _arr_of(fn, v):
        return getattr(fn, "arrv", {}).get(v) if isinstance(v, int) else None

    def alloc_array(self, fn, n):
        base = fn.new_struct_slot(n)
        addr = fn.new_v()
        fn.emit("frameaddr", addr, base)
        return self._mark_arr(fn, addr, n)

    def array_copy(self, fn, dst, src, n, nb=None):
        """逐字拷贝；nb 给定时按声明宽度截断每个元素（v1.40 窄数组）"""
        for i in range(n):
            t = fn.new_v()
            fn.emit("load", t, src, ("imm", i))
            if nb is not None:
                tt = fn.new_v()
                fn.emit("trunc", tt, t, nb[0], nb[1])
                t = tt
            fn.emit("store", dst, ("imm", i), t)

    def emit_bounds(self, fn, idx, n, dynamic=False):
        """越界 fail-fast（Quelmara.toml [build] bounds_check 可关闭）。
        n 默认是常量长度；dynamic=True 时 n 是运行期 vreg（切片动态长度）"""
        if not self.cfg["build"].get("bounds_check", True):
            return
        self.uses_bounds = True
        nval = n if dynamic else ("imm", n)
        l_ok = fn.label("bok")
        l_fail = fn.label("bfail")
        # v2.66：**一次无符号比较**覆盖 [0, n) —— 负下标按无符号解释是巨大值，
        # 与"idx >= n"走同一条失败路径。省掉"idx >= 0"那次比较与分支。
        fn.emit("jcc", "b", idx, nval, l_ok)
        fn.emit("label", l_fail)
        fn.emit("call", None, "__bounds_fail", [])
        fn.emit("label", l_ok)

    # ---- 真实整数宽度（v1.8）----
    # 值统一按 64 位寄存器承载，但在**边界**（let 标注 / 形参 / 返回值 /
    # 赋值 / 复合赋值）按声明宽度截断：uN 零扩展、iN 符号扩展。
    # 表达式内部按 C 语义提升到 64 位，因此 a*b 不会在中途回绕。
    NARROW_BITS = {"u8": (8, False), "u16": (16, False), "u32": (32, False),
                   "i8": (8, True), "i16": (16, True), "i32": (32, True)}

    @classmethod
    def narrow_of(cls, ty):
        if ty and ty[0] == "named":
            return cls.NARROW_BITS.get(ty[1])
        return None

    def _arr_narrow_of(self, ty):
        """声明类型 ("array", n, elem) -> 元素窄宽度 (bits, signed) / None"""
        if ty and ty[0] == "array" and len(ty) > 2:
            return self.narrow_of(ty[2])
        return None

    def trunc_to(self, fn, v, nb):
        """把 v 截断到 nb=(bits, signed)，返回新 vreg。"""
        d = fn.new_v()
        fn.emit("trunc", d, v, nb[0], nb[1])
        return d

    @staticmethod
    def _ty_float_w(ty):
        """类型元组 -> 'f32'/'f64'/None（浮点宽度）"""
        if ty and ty[0] == "named" and ty[1] in ("float", "f64", "f32"):
            return "f32" if ty[1] == "f32" else "f64"
        return None

    def lower_struct_lit(self, sname, fields, fn, env):
        addr = self.alloc_struct(fn, sname)
        for fname, fexpr in fields.items():
            off, ftype = self.field_offset(sname, fname)
            val = self.eval(fexpr, fn, env)
            if ftype and ftype[0] == "named" and self.is_agg(ftype[1]):
                # 嵌套聚合字段：拷贝到 addr+off*8
                if self._is_iface(ftype[1]):
                    # 接口字段接受具体类型：先装箱（v1.83；此前按错宽度静默拷贝）
                    sn = self._struct_of(fn, val)
                    if sn is not None and sn != ftype[1]:
                        val = self.box_iface(fn, val, sn, ftype[1])
                sub = fn.new_v()
                fn.emit("bin", "add", sub, addr, ("imm", off * 8))
                self._mark_struct(fn, sub, ftype[1])
                self.struct_copy(fn, sub, val, ftype[1])
                if self._is_iface(ftype[1]):
                    self._iface_share(fn, sub, val)
            elif ftype and ftype[0] == "slice":
                # 切片字段（v1.39）：2 字 {ptr,len} 整体拷。
                # 早期走 else 的 1 字 store——ptr 存了、len 丢了，静默错编。
                sub = fn.new_v()
                fn.emit("bin", "add", sub, addr, ("imm", off * 8))
                self.words_copy(fn, sub, val, SLICE_WORDS)
            else:
                val = self.conv_to(fn, val, self._float_of(fn, val), self._ty_float_w(ftype))
                nb = self.narrow_of(ftype)
                if nb is not None:
                    val = self.trunc_to(fn, val, nb)   # 窄字段按声明宽度截断（v1.40）
                fn.emit("store", addr, ("imm", off), val)
        return addr

    def lower_enum_lit(self, e, fn, env):
        """枚举构造 -> 帧槽块：字 0 存 tag，字 1.. 存载荷。
        ("enumlit", path, [(fname, expr)]) 命名实参（parse 期已按本文件
        变体表展开）；("enumlit_pos", path, [expr]) 位置实参（v1.44 限定
        枚举构造——parse 期拿不到跨模块变体表，这里按 merged 表校验个数
        并按下标映射字段名）。"""
        path, fields = e[1], e[2]
        ename, vname = path[0], path[1]
        if ename not in self.enums:
            raise SyntaxError(f"未声明的枚举 {ename}")
        vidx, vfields = self.enum_variant(ename, vname)
        if e[0] == "enumlit_pos":
            if len(fields) != len(vfields):
                raise SyntaxError(
                    f"{ename}.{vname} 构造需 {len(vfields)} 个载荷字段，得到 {len(fields)}")
            exprs = {vf[0]: fields[i] for i, vf in enumerate(vfields)}
        else:
            exprs = dict(fields)
            if set(exprs) != {f for f, _ in vfields}:
                raise SyntaxError(
                    f"{ename}.{vname} 构造需给出全部载荷字段 {[f for f, _ in vfields]}")
        addr = self.alloc_struct(fn, ename)
        fn.emit("store", addr, ("imm", 0), ("imm", vidx))
        off = 1
        for fname, ftype in vfields:
            val = self.eval(exprs[fname], fn, env)
            if ftype and ftype[0] == "named" and self.is_agg(ftype[1]):
                sub = fn.new_v()
                fn.emit("bin", "add", sub, addr, ("imm", off * 8))
                self._mark_struct(fn, sub, ftype[1])
                self.struct_copy(fn, sub, val, ftype[1])
                if self._is_iface(ftype[1]):
                    self._iface_share(fn, sub, val)
                off += self.agg_size(ftype[1])
            else:
                val = self.conv_to(fn, val, self._float_of(fn, val), self._ty_float_w(ftype))
                nb = self.narrow_of(ftype)
                if nb is not None:
                    val = self.trunc_to(fn, val, nb)   # 窄载荷按声明宽度截断（v1.40）
                fn.emit("store", addr, ("imm", off), val)
                off += 1
        return self._mark_struct(fn, addr, ename)

    def lower_match(self, e, fn, env, as_expr):
        """match -> tag 比较链 + 每臂载荷绑定（不新增 QuIR 指令，纯现有指令降级）"""
        _m, scrut, arms = e
        addr = self.eval(scrut, fn, env)
        sname = self._struct_of(fn, addr)
        arms = resolve_option_patterns(arms, sname)
        ename, plain, _wild = validate_match(arms, self.enums)
        if sname not in self.enums:
            raise SyntaxError("match 的求值式必须是枚举类型")
        if ename is not None and ename != sname:
            raise SyntaxError(f"match 模式是 {ename}，求值式是 {sname}")
        if as_expr and any(body[0] != "expr" for _i, _n, body in plain):
            raise SyntaxError("match 表达式的臂必须是表达式；块臂请把 match 当语句使用")
        tag = fn.new_v()
        fn.emit("load", tag, addr, ("imm", 0))
        l_end = fn.label("mend")
        l_arms = [fn.label("marm") for _ in plain]
        for (idx, _n, _b), L in zip(plain, l_arms):
            if idx is not None:
                fn.emit("jcc", "e", tag, ("imm", idx), L)
        fn.emit("jmp", l_arms[-1])          # 穷尽性已证：落到最后一臂（含通配）
        d = fn.new_v() if as_expr else None
        res_agg, res_base = None, None
        for (idx, names, body), L in zip(plain, l_arms):
            fn.emit("label", L)
            env2 = dict(env)
            if idx is not None:
                vname, vfields = self.enums[sname][idx]
                off = 1
                for i, b in enumerate(names):
                    ftype = vfields[i][1]
                    if b is not None:
                        if ftype and ftype[0] == "named" and self.is_agg(ftype[1]):
                            # 聚合载荷绑定 -> 按值拷贝（值语义）
                            tmp = self.alloc_struct(fn, ftype[1])
                            sub = fn.new_v()
                            fn.emit("bin", "add", sub, addr, ("imm", off * 8))
                            self._mark_struct(fn, sub, ftype[1])
                            self.struct_copy(fn, tmp, sub, ftype[1])
                            env2[b] = tmp
                        else:
                            v = fn.new_v()
                            fn.emit("load", v, addr, ("imm", off))
                            if ftype == ("named", "str"):
                                self._mark_str(fn, v)
                            elif ftype == ("named", "bool"):
                                self._mark_bool(fn, v)
                            elif ftype and ftype[0] == "named" \
                                    and ftype[1] in ("f64", "float", "f32"):
                                # 浮点载荷：绑定后必须打浮点标记，否则
                                # to_str/算术会按整数位模式处理（v1.65 修复）
                                self._mark_float(
                                    fn, v, "f32" if ftype[1] == "f32" else "f64")
                            elif ftype and ftype[0] == "vec":
                                # v1.93：容器载荷的标签跟着绑定走。此前只打
                                # str/bool/f64 标记，`E.A(buf, v)` 解出 buf 后
                                # `buf.push(...)` 会报"方法 push 未定义"——
                                # 枚举装缓冲区（错误对象、资源句柄）因此写不了。
                                self._mark_vec(fn, v, self._vec_tag_of(ftype[1]))
                            elif ftype and ftype[0] == "map":
                                self._mark_map(fn, v, ftype[1][1], ftype[2][1])
                            elif ftype and ftype[0] == "chan":
                                self._mark_chan(fn, v)
                            env2[b] = v
                    off += self.field_words(ftype)
            if body[0] == "expr":
                r = self.eval(body[1], fn, env2)
                if as_expr:
                    ragg = self._struct_of(fn, r)
                    if ragg is not None:
                        # 聚合结果：拷进共享结果帧槽。
                        # ⚠ 帧槽地址必须【每个臂各自 frameaddr】再拷贝，
                        #   绝不能把定义只发在第一个臂里（非 SSA 下其它臂用到未定义值）。
                        if res_agg is None:
                            res_agg = ragg
                            res_base = fn.new_struct_slot(self.agg_size(ragg))
                        elif ragg != res_agg:
                            raise SyntaxError("match 各臂返回类型不一致")
                        addr = fn.new_v()
                        fn.emit("frameaddr", addr, res_base)
                        self._mark_struct(fn, addr, ragg)
                        self.struct_copy(fn, addr, r, ragg)
                    else:
                        if res_agg is not None:
                            raise SyntaxError("match 各臂返回类型不一致")
                        fn.emit("mov", d, r)
                        if self._is_str(fn, r):
                            self._mark_str(fn, d)
                        if isinstance(r, int) and r in getattr(fn, "boolv", set()):
                            self._mark_bool(fn, d)
                        # 浮点结果同样要传标记（v1.65）：漏了它，match 表达式
                        # 的 f64 结果会被当成整数位模式（print/to_str 输出乱码）
                        wf = self._float_of(fn, r)
                        if wf:
                            self._mark_float(fn, d, wf)
            else:
                self.block(body[1], fn, env2)
            fn.emit("jmp", l_end)
        fn.emit("label", l_end)
        if res_agg is not None:
            # 合并点统一取结果地址（支配所有臂）
            res_addr = fn.new_v()
            fn.emit("frameaddr", res_addr, res_base)
            return self._mark_struct(fn, res_addr, res_agg)
        return d

    def resolve_field_chain(self, e, fn, env):
        """('field' | 'path') 链 -> (地址 vreg, 字段名)；只支持取到字段为止"""
        segs = []
        cur = e
        while isinstance(cur, tuple) and cur[0] == "field":
            segs.append(cur[2])
            cur = cur[1]
        if isinstance(cur, tuple) and cur[0] == "path":
            segs.extend(reversed(cur[1][1:]))
            base_name = cur[1][0]
            cur = ("name", base_name)
        segs.reverse()
        addr = self.eval(cur, fn, env)
        return addr, segs

    def field_addr(self, fn, addr, sname, fname):
        """返回 (目标字下标, 字段类型, 该字段的首地址或 None)"""
        off, ftype = self.field_offset(sname, fname)
        return off, ftype, addr

    # ---- 全局数据 ----
    @staticmethod
    def _u8(s: str) -> bytes:
        """字面量 -> 原始字节。\\xNN(>=0x80) 以 surrogateescape 区字符承载，
        必须用同一个 errors 策略还原，否则会被再编码成 2 字节 UTF-8（b2 误编译）。"""
        return s.encode("utf-8", "surrogateescape")

    def intern(self, data: bytes):
        self.globals.append(data)
        return len(self.globals) - 1

    def intern_str(self, s: str):
        key = s
        if key not in self.gid_of_str:
            self.gid_of_str[key] = self.intern(self._u8(s) + b"\x00")
        return self.gid_of_str[key]

    def intern_str_lit(self, s: str):
        """语言层字符串字面量（v1.5.1 str 长度前缀 ABI）：
        布局 [8 字节长度][utf8 字节][NUL]，str 值 = ga+8（指向字节）。
        消息/诊断串仍走 intern_str（原始字节，喂 winapi）。"""
        key = "\x00lit:" + s
        if key not in self.gid_of_str:
            b = self._u8(s)
            self.gid_of_str[key] = self.intern(
                struct.pack("<Q", len(b)) + b + b"\x00")
        return self.gid_of_str[key]

    def intern_array(self, n: int):
        return self.intern(b"\x00" * (8 * n))

    # ---- 平台抽象 ----------------------------------------------------------
    # 运行库（print/itoa/assert/arena）与 parfor 只调用这些 helper：
    # Linux 发射 raw syscall，Windows 发射 winapi 指令（kernel32 导入）。
    # 这样「同一份自举运行库」可以跨平台复用，平台差异只在一个薄层。
    def emit_write(self, fn, fd, ptr, length):
        """write(fd, ptr, length)；fd=1 stdout / 2 stderr"""
        if self.platform == "windows":
            h = fn.new_v()
            fn.emit("winapi", h, "GetStdHandle",
                    [("imm", -11 if fd == 1 else -12)])
            ok = fn.new_v()
            fn.emit("winapi", ok, "WriteFile",
                    [h, ptr, length, ("ga", self.written_gid), ("imm", 0)])
        else:
            fn.emit("syscall", None, self.sc["write"],
                    [("imm", fd), ptr, length,
                     ("imm", 0), ("imm", 0), ("imm", 0)])

    def emit_exit(self, fn, code):
        """code：`("imm", n)` 立即数 / 裸 int = **vreg** / 其它操作数原样传。

        v2.13 修：此前裸 int 被当成立即数，于是 `exit(变量)` 把 **vreg 号**
        当退出码——`let c = 3; exit(c)` 静默退 0（vreg 0）、`f(4)` 里
        `exit(c)` 也是 0。内部调用点（assert/越界/panic）传的都是字面量 1，
        所以只有"退出码是运行期算出来的"这一条路坏，回归也没覆盖到。"""
        if isinstance(code, tuple) and code[0] == "imm":
            arg = ("imm", code[1])
        else:
            arg = code
        if self.platform == "windows":
            fn.emit("winapi", None, "ExitProcess", [arg])
        else:
            fn.emit("syscall", None, self.sc["exit"],
                    [arg, ("imm", 0), ("imm", 0),
                     ("imm", 0), ("imm", 0), ("imm", 0)])

    def emit_alloc(self, fn, size, reserve_only=False):
        """分配一段内存，返回 vreg（Linux mmap / Windows VirtualAlloc）

        reserve_only=True 时 Windows 只做 MEM_RESERVE（不占提交配额），
        后续由 __alloc 以 1MB 粒度按需 MEM_COMMIT —— 这就是「省用」：
        512MB 的 heap_limit 只在真正被写到时才消耗物理内存/页面文件。
        """
        d = fn.new_v()
        if self.platform == "windows":
            # MEM_COMMIT|MEM_RESERVE = 0x3000, MEM_RESERVE = 0x2000, PAGE_READWRITE = 4
            flags = 0x2000 if reserve_only else 0x3000
            fn.emit("winapi", d, "VirtualAlloc",
                    [("imm", 0), size, ("imm", flags), ("imm", 4)])
        else:
            fn.emit("syscall", d, self.sc["mmap"],
                    [("imm", 0), size, ("imm", PROT_RW),
                     ("imm", MAP_PRIVATE_ANON), ("imm", -1), ("imm", 0)])
        return d

    def is_serial(self):
        """Quelmara.toml 是否要求单核/单线程（spawn/parfor 编译期降级）"""
        return (not self.cfg["core"]["multicore"]) or \
            int(self.cfg["core"]["threads"] or 0) == 1

    def emit_yield(self, fn):
        """让出 CPU（自旋等待时避免把整核跑满）。
        @no_preempt 函数内不插让出点：自旋/临界区要求确定性延迟时用，
        代价是会把核跑满（见 SPEC §5）。"""
        if getattr(self, "no_preempt", False):
            return
        if self.platform == "windows":
            fn.emit("winapi", None, "SwitchToThread", [])
        else:
            fn.emit("syscall", None, self.sc["yield"],
                    [("imm", 0), ("imm", 0), ("imm", 0),
                     ("imm", 0), ("imm", 0), ("imm", 0)])

    # ---- 表达式：返回 ('imm',n) | ('ga',gid) | vreg ----
    def eval(self, e, fn, env):
        if e[0] == "vreg":
            return e[1]
        k = e[0]
        if k == "num":
            return ("imm", e[1])
        if k == "fnum":
            return self.make_fnum(fn, e[1], e[2])
        if k == "bool":
            return ("imm", 1 if e[1] else 0)
        if k == "str":
            # 字面量 = [len][bytes][NUL] 全局，值指向字节（len 前缀在 -8）
            gid = self.intern_str_lit(e[1])
            d = fn.new_v()
            fn.emit("movaddr", d, gid)
            fn.emit("bin", "add", d, d, ("imm", 8))
            return self._mark_str(fn, d)
        if k == "interp":
            # 字符串插值（v1.61）：单次分配 + 整数直写缓冲区
            return self.lower_interp(e[1], fn, env)
        if k == "name":
            if e[1] not in env:
                # 函数名作值：已知函数名 -> 代码地址操作数（fnaddr）。可作实参
                # 传给间接调用目标（如网络回调），或 let 绑定（mov 走
                # movabs + 回填；PE 下生成 DIR64 重定位，ASLR 安全）。
                if e[1] in self.ffi_decls:
                    # v1.87：@ffi 符号没有本地代码地址（它在 DLL 里），
                    # 取地址只能得到空标签——明确拒绝，别让它在发射期炸。
                    raise SyntaxError(
                        f"{e[1]} 是 @ffi 声明，没有本地代码地址（符号在 DLL 里）；"
                        f"要回调请先在语言里写一个 Win64 约定的包装函数"
                        f"（当前未支持回调 thunk）")
                if e[1] in self.fns_ast:
                    return ("fnaddr", e[1])
                raise SyntaxError(f"未定义变量 {e[1]}")
            return env[e[1]]
        if k == "lambda":
            return self.lower_lambda(e, fn, env)
        if k == "call":
            return self.lower_call(e, fn, env)
        if k == "arraylit":
            n = len(e[1])
            addr = self.alloc_array(fn, n)
            for i, el in enumerate(e[1]):
                v = self.eval(el, fn, env)
                if self._struct_of(fn, v) is not None or self._is_str(fn, v):
                    raise SyntaxError("数组元素暂只支持数值（v0.6 边界）")
                if self._float_of(fn, v):
                    # v1.16：f64 元素放开（位模式 1 槽，与 [N]f64 配套）；
                    # f32 仍禁（槽宽不同）
                    if self._float_of(fn, v) != "f64":
                        raise SyntaxError("数组元素暂不支持 f32（槽宽边界）")
                fn.emit("store", addr, ("imm", i), v)
            if all(self._float_of(fn, self.eval(el, fn, env)) == "f64"
                   for el in e[1]) and e[1]:
                self.arr_elem[addr] = "f64"
            return addr
        if k == "index":
            obj = self.eval(e[1], fn, env)
            n = self._arr_of(fn, obj)
            if n is not None:
                idx = self.eval(e[2], fn, env)
                self.emit_bounds(fn, idx, n)
                d = fn.new_v()
                fn.emit("load", d, obj, idx)
                if self.arr_elem.get(obj) == "f64":
                    self._mark_float(fn, d, "f64")
                return d
            if self._is_slice(fn, obj):
                # 切片：ptr = s.word0，长度是运行期值（动态越界检查）
                ptr = self.slice_ptr(fn, obj)
                ln = self.slice_len(fn, obj)
                idx = self.eval(e[2], fn, env)
                self.emit_bounds(fn, idx, ln, dynamic=True)
                d = fn.new_v()
                fn.emit("load", d, ptr, idx)
                if self._slice_elem(fn, obj) == "str":
                    self._mark_str(fn, d)
                return d
            if self._is_str(fn, obj):
                # str 下标 -> 该字节的无符号值（0..255）；长度是运行期 strlen 结果，
                # load8 走 movzx，不做符号扩展
                idx = self.eval(e[2], fn, env)
                ln = self.str_len(fn, obj)
                self.emit_bounds(fn, idx, ln, dynamic=True)
                d = fn.new_v()
                fn.emit("load8", d, obj, idx)
                return d
            # vec[T] 下标（v2.13）：文档一直写 `v[i]`，实现里只有定长数组/切片/str
            # 三条路，vec 句柄落到这里就报错——`std/sort.qma` 因此**整个模块编不过**
            # （它全是 `v[i]` 的快速排序）。降级同 `.get(i)`：__vec_get 自带越界
            # fail-fast，元素标签照 .get 的三条重挂路径（str / 嵌套 vec / vec[map]）。
            if self._is_vec(fn, obj):
                idx = self.eval(e[2], fn, env)
                elem = self._vec_elem(fn, obj)
                if isinstance(elem, tuple) and elem[0] == "agg":
                    dst = self.alloc_struct(fn, elem[1])
                    fn.emit("call", None, "__vec_get_n", [obj, idx, dst])
                    return self._mark_struct(fn, dst, elem[1])
                d = fn.new_v()
                fn.emit("call", d, "__vec_get", [obj, idx])
                if elem == "str":
                    self._mark_str(fn, d)
                if isinstance(elem, tuple) and elem[0] == "vecinner":
                    self._mark_vec(fn, d, elem[1])
                if isinstance(elem, tuple) and elem[0] == "mapinner":
                    self._mark_map(fn, d, elem[1], elem[2])
                return d
            raise SyntaxError("下标只能用于定长数组、切片、vec 或 str")
        if k == "spawn":
            return self.lower_spawn(e[1], fn, env)
        if k == "chanopen":
            if self.arch != "x86_64":
                raise SyntaxError("chan[T] 目前仅支持 x86_64 后端")
            if len(e[2]) != 1:
                raise SyntaxError("chan[T].open(cap) 需要且只需要一个容量实参")
            self.uses_chan = True
            cap = self.eval(e[2][0], fn, env)
            d = fn.new_v()
            fn.emit("call", d, "__chan_open", [cap])
            return self._mark_chan(fn, d)
        if k == "mapnew":
            if self.arch != "x86_64":
                raise SyntaxError("map[K]V 目前仅支持 x86_64 后端")
            if len(e[2]) > 1:
                raise SyntaxError("map[K]V.new(cap) 至多一个容量实参")
            self.uses_map = True
            kt = e[1][1][1] if e[1][0] == "map" else "int"
            vt = e[1][2][1] if e[1][0] == "map" else "int"
            ktag = 1 if kt == "str" else 0
            # 值扩容（v1.41）：聚合值按 agg 布局占 N 槽；未声明的聚合在这里
            # fail-fast（agg_size 报"未声明的结构体/枚举"）
            vw = self.agg_size(vt) if self.is_agg(vt) else 1
            cap = self.eval(e[2][0], fn, env) if e[2] else ("imm", 16)
            d = fn.new_v()
            fn.emit("call", d, "__map_open", [cap, ("imm", ktag), ("imm", vw)])
            return self._mark_map(fn, d, kt, vt)
        if k == "unop":
            a = self.eval(e[2], fn, env)
            if e[1] == "-":
                # v1.51 fail-fast：str 没有取负语义。此前落到 "neg" 指令，
                # 把长度前缀指针按整数取负，运行时读到野指针（-1e-300.to_str()
                # 这类写法会把比较/打印直接打成段错误）。
                if self._is_str(fn, a):
                    raise SyntaxError("一元 - 不能用于 str（需先 to_int 或加括号）")
                wa = self._float_of(fn, a)
                if wa:
                    d = fn.new_v()
                    fn.emit("fneg", wa, d, a)
                    return self._mark_float(fn, d, wa)
                if isinstance(a, tuple) and a[0] == "imm":
                    return ("imm", -a[1])
                d = fn.new_v()
                fn.emit("neg", d, a)
                return d
            if e[1] == "!":
                wa = self._float_of(fn, a)
                if wa:
                    d = fn.new_v()
                    # +0.0 的位模式就是整数 0，直接当立即数比
                    fn.emit("fcmpset", wa, "e", d, a, ("imm", 0))
                    return self._mark_bool(fn, d)
                if isinstance(a, tuple) and a[0] == "imm":
                    return ("imm", 0 if a[1] else 1)
                d = fn.new_v()
                fn.emit("cmpset", "e", d, a, ("imm", 0))
                return self._mark_bool(fn, d)
            if e[1] == "~":
                # 按位取反：x ^ -1（全 1 掩码），不做位宽截断（Quelmara 是 64 位整数）
                if isinstance(a, tuple) and a[0] == "imm":
                    return ("imm", ~a[1])
                d = fn.new_v()
                fn.emit("bin", "xor", d, a, ("imm", -1))
                return d
        if k == "vecnew":
            self.uses_vec = True
            et = e[1]
            tag = self._vec_tag_of(et)
            cap = ("imm", 4)
            if e[2]:
                if len(e[2]) != 1:
                    raise SyntaxError("vec[T].new(cap) 只接受一个容量实参")
                cap = self.eval(e[2][0], fn, env)
            d = fn.new_v()
            fn.emit("call", d, "__vec_new", [cap, ("imm", self.type_words(et))])
            return self._mark_vec(fn, d, tag)
        if k == "sliceof":
            return self.lower_sliceof(e, fn, env)
        if k == "binop":
            return self.lower_binop(e, fn, env)
        if k == "select":
            # select { c1.recv(), ... }（v0.11）：轮询 + yield，
            # 声明序优先；全部关闭且排空 -> 0。try_recv 的 ok 走帧槽出参。
            if not e[1]:
                raise SyntaxError("select 至少需要一个 recv 臂")
            self.uses_chan = True
            slot = fn.new_struct_slot(1)
            okp = fn.new_v()
            fn.emit("frameaddr", okp, slot)
            result = fn.new_v()
            fn.emit("mov", result, ("imm", 0))
            l_loop = fn.label("selloop")
            l_done = fn.label("seldone")
            l_wait = fn.label("selwait")
            fn.emit("label", l_loop)
            objs = []
            for arm in e[1]:
                if not (arm[0] == "method" and arm[2] == "recv" and not arm[3]):
                    raise SyntaxError("select 臂必须是 ch.recv() 形式")
                aobj = self.eval(arm[1], fn, env)
                if not self._is_chan(fn, aobj):
                    raise SyntaxError("select 臂只能用于 chan 通道")
                objs.append(aobj)
                v = fn.new_v()
                fn.emit("call", v, "__chan_try_recv", [aobj, okp])
                ok = fn.new_v()
                fn.emit("load", ok, okp, ("imm", 0))
                l_next = fn.label("selnext")
                fn.emit("jz", ok, l_next)
                fn.emit("mov", result, v)
                fn.emit("jmp", l_done)
                fn.emit("label", l_next)
            # 全部未就绪：全部已关闭 -> 0；否则 yield 后重试
            for aobj in objs:
                cl = fn.new_v()
                fn.emit("load", cl, aobj, ("imm", 6))
                fn.emit("jz", cl, l_wait)
            fn.emit("jmp", l_done)
            fn.emit("label", l_wait)
            self.emit_yield(fn)
            fn.emit("jmp", l_loop)
            fn.emit("label", l_done)
            return result
        if k == "method":
            obj = self.eval(e[1], fn, env)
            if self._is_vec(fn, obj):
                return self.lower_vec_method(e[2], obj, self._vec_elem(fn, obj),
                                             e[3], fn, env)
            mp = self._map_of(fn, obj)
            if mp:
                return self.lower_map_method(e[2], obj, mp, e[3], fn, env)
            if e[2] in ("send", "recv") and self._is_chan(fn, obj):
                d = fn.new_v()
                if e[2] == "send":
                    if len(e[3]) != 1:
                        raise SyntaxError("ch.send(v) 需要一个实参")
                    v = self.eval(e[3][0], fn, env)
                    if self._float_of(fn, v):
                        raise SyntaxError("chan 暂不支持浮点值（v1 边界）")
                    fn.emit("call", d, "__chan_send", [obj, v])
                else:
                    fn.emit("call", d, "__chan_recv", [obj])
                return d
            if e[2] == "close" and self._is_chan(fn, obj):
                if e[3]:
                    raise SyntaxError("ch.close() 不接受实参")
                self.uses_chan = True
                d = fn.new_v()
                fn.emit("call", d, "__chan_close", [obj])
                return d
            if e[2] == "to_str":
                if self._is_str(fn, obj):
                    return obj
                wf = self._float_of(fn, obj)
                if wf:
                    x = self.conv_to(fn, obj, wf, "f64")
                    self.uses_f64_str = True
                    d = fn.new_v()
                    fn.emit("call", d, "__f64_to_str", [x])
                    return self._mark_str(fn, d)
                if e[1][0] == "bool" or (isinstance(obj, int) and obj in getattr(fn, "boolv", set())):
                    d = fn.new_v()
                    fn.emit("call", d, "__str_from_bool", [obj])
                    return self._mark_str(fn, d)
                d = fn.new_v()
                fn.emit("call", d, "__str_from_i64", [obj])
                return self._mark_str(fn, d)
            if e[2] == "to_int" and self._is_str(fn, obj):
                # s.to_int()：十进制解析；非法输入 / 溢出 fail-fast
                if e[3]:
                    raise SyntaxError(".to_int() 不接受实参")
                self.uses_str_to_int = True
                d = fn.new_v()
                fn.emit("call", d, "__str_to_int", [obj])
                return d
            # 用户方法（impl Type : Interface 落成的 Type__method）：
            # 接收者静态类型已知 -> 直接调用，零开销。动态分发未实现，
            # 见 docs/GAPS.md §2「interface」。
            sname = self._struct_of(fn, obj)
            if sname is not None:
                amb = getattr(self, "method_ambig", {}).get((sname, e[2]))
                if amb:
                    # 同名方法跨接口（v1.81）：impl 已经能共存（按接口名
                    # mangling），但静态调用 c.m() 没有消歧规则 -> fail-fast
                    # 并给出可复制的写法，别让用户猜。
                    raise SyntaxError(
                        f"方法 {e[2]} 在类型 {sname} 上有 {len(amb)} 个实现"
                        f"（接口 {' / '.join(amb)}），静态调用有歧义；"
                        f"请先转成接口值再调用："
                        f"let s: {amb[0]} = x; s.{e[2]}(...)")
                mname = f"{sname}__{e[2]}"
                if mname in self.fns_ast:
                    # ("vreg", n) 让已求值的接收者原样穿过 lower_call 的实参处理
                    args = [("vreg", obj)] + list(e[3])
                    return self.lower_call(("call", [mname], args), fn, env)
                if self._is_iface(sname):
                    # 接口值：vt[slot] 取出函数指针 -> callr（真正的 vtable 派发）
                    return self.lower_iface_call(sname, obj, e[2], e[3], fn, env)
            raise SyntaxError(
                f"方法 {e[2]} 未定义（原生后端只支持 vec/map/chan/str 内建方法与 "
                f"impl 里声明的方法）")
        if k == "try":
            spec = self.eval(e[1], fn, env)
            sname = self._struct_of(fn, spec)
            if sname is None or sname not in self.enums:
                raise SyntaxError("? 只能用于带 Ok/Err 变体的枚举结果")
            variants = self.enums[sname]
            ok_idx = next((i for i, (vn, _fs) in enumerate(variants) if vn == "Ok"), None)
            err_idx = next((i for i, (vn, _fs) in enumerate(variants) if vn == "Err"), None)
            ok = variants[ok_idx][1] if ok_idx is not None else None
            err = variants[err_idx][1] if err_idx is not None else None
            if len(variants) != 2 or ok_idx is None or err_idx is None or not ok or not err \
                    or len(ok) != 1 or len(err) != 1:
                raise SyntaxError("结果枚举必须只有 Ok(value) 和 Err(error) 两个单载荷变体")
            okt = ok[0][1]
            if okt[0] != "named" or not (
                    okt[1] in ("int", "i64", "i32", "i16", "i8",
                               "u64", "u32", "u16", "u8", "bool", "str")
                    or self.is_agg(okt[1])):
                # v1.38：Ok 载荷放宽到具名 struct/enum（多字）
                raise SyntaxError("? 的 Ok 载荷暂只支持整数/bool/str 标量与具名 struct/enum")
            if self.fn_ret_agg != sname:
                raise SyntaxError("? 所在函数必须返回相同的结果枚举")
            tag = fn.new_v()
            fn.emit("load", tag, spec, ("imm", 0))
            l_ok, l_err = fn.label("try_ok"), fn.label("try_err")
            fn.emit("jcc", "e", tag, ("imm", ok_idx), l_ok)
            fn.emit("jmp", l_err)
            fn.emit("label", l_err)
            self.struct_copy(fn, self.fn_ret_target, spec, sname)
            fn.emit("ret", ("imm", 0))
            fn.emit("label", l_ok)
            if self.is_agg(okt[1]):
                # v1.38：多字载荷——把 Ok 载荷拷进新帧槽按值返回
                # （struct 值 = 槽地址，与字段访问/vec.get 聚合元素同构）
                slot = self.alloc_struct(fn, okt[1])
                src = fn.new_v()
                fn.emit("bin", "add", src, spec, ("imm", 8))   # 载荷在 tag 之后（字偏移 1）
                self.struct_copy(fn, slot, src, okt[1])
                return slot
            value = fn.new_v()
            fn.emit("load", value, spec, ("imm", 1))
            if ok[0][1] == ("named", "str"):
                self._mark_str(fn, value)
            elif ok[0][1] == ("named", "bool"):
                self._mark_bool(fn, value)
            return value
        if k == "path":
            p = e[1]
            if p[0] in env:
                # 头段是当前作用域的变量 -> 字段访问链 v.x.y
                obj = ("name", p[0])
                for seg in p[1:]:
                    obj = ("field", obj, seg)
                return self.eval(obj, fn, env)
            if p == ["net", "Action", "Keep"]:
                return ("imm", 1)
            if p == ["net", "Action", "Close"]:
                return ("imm", 0)
            raise SyntaxError(f"原生后端不支持的路径 {'.'.join(p)}")
        if k == "field":
            return self.lower_field(e, fn, env)
        if k == "structlit":
            path, fields = e[1], e[2]
            sname = self.struct_name_of(path)
            if sname is None:
                raise SyntaxError(f"原生后端不支持的结构体字面量 {'.'.join(path)}")
            return self.lower_struct_lit(sname, fields, fn, env)
        if k in ("enumlit", "enumlit_pos"):
            return self.lower_enum_lit(e, fn, env)
        if k == "match":
            return self.lower_match(e, fn, env, as_expr=True)
        raise SyntaxError(f"无法降级表达式: {e!r}")

    def struct_name_of(self, path):
        name = path[-1]
        return name if name in self.structs else None

    def lower_field(self, e, fn, env):
        obj = self.eval(e[1], fn, env)
        sname = self._struct_of(fn, obj)
        if sname is None:
            raise SyntaxError(f"对非结构体表达式取字段 .{e[2]}")
        off, ftype = self.field_offset(sname, e[2])
        if ftype and ftype[0] == "named" and self.is_agg(ftype[1]):
            d = fn.new_v()
            fn.emit("bin", "add", d, obj, ("imm", off * 8))
            return self._mark_struct(fn, d, ftype[1])
        d = fn.new_v()
        fn.emit("load", d, obj, ("imm", off))
        # 嵌套容器字段（v1.39）：句柄 1 字存字段里，读出必须重挂类型标记，
        # 否则 r.cells.push(...) / r.m.set(...) 认不出类型（"方法未定义"）。
        # chan 同批补上（send/recv 派发依赖 _is_chan）。
        if ftype and ftype[0] == "vec":
            return self._mark_vec(fn, d, self._vec_tag_of(ftype[1]))
        if ftype and ftype[0] == "map":
            return self._mark_map(fn, d,
                                  ftype[1][1] if ftype[1][0] == "named" else "int",
                                  ftype[2][1] if ftype[2][0] == "named" else "int")
        if ftype and ftype[0] == "chan":
            return self._mark_chan(fn, d)
        if ftype and ftype[0] == "slice":
            # 切片字段（v1.39）：2 字 {ptr,len} 拷进新帧槽并重挂 slice 标记，
            # 否则 x.s[0] 认不出是切片（"下标只能用于定长数组、切片或 str"）。
            dst = self.alloc_slice(fn)
            src = fn.new_v()
            fn.emit("bin", "add", src, obj, ("imm", off * 8))
            self.words_copy(fn, dst, src, SLICE_WORDS)
            elem = ftype[1][1] if (ftype[1][0] == "named"
                                   and ftype[1][1] in SCALAR_ELEMS) else None
            return self._mark_slice(fn, dst, elem)
        # 字段的类型标签必须跟着值走：早期漏了 str，导致 print(p.name) 打印指针
        if ftype == ("named", "str"):
            self._mark_str(fn, d)
            return d
        fw = self._ty_float_w(ftype)
        if fw:
            self._mark_float(fn, d, fw)
        return d

    def lower_sliceof(self, e, fn, env):
        """a[lo..hi]：左闭右开。
        - str  ：拷贝出新串（与原串不共享，符合 str 不可变语义）
        - 切片 ：零拷贝视图 {ptr+lo, hi-lo}
        - 定长数组：转成切片视图（等价 slice_of(a)[lo..hi]）
        越界一律 fail-fast，判定顺序与 substr 一致。
        """
        obj = self.eval(e[1], fn, env)
        lo = self.eval(e[2], fn, env)
        hi = self.eval(e[3], fn, env)
        self.uses_substr = True                     # 复用 __substr_fail
        l_bad = fn.label("rngbad")
        l_ok = fn.label("rngok")
        b = fn.new_v()
        fn.emit("cmpset", "l", b, lo, ("imm", 0))
        fn.emit("jnz", b, l_bad)
        fn.emit("cmpset", "l", b, hi, lo)
        fn.emit("jnz", b, l_bad)

        if self._is_str(fn, obj):
            ln = self.str_len(fn, obj)
            fn.emit("cmpset", "g", b, hi, ln)
            fn.emit("jnz", b, l_bad)
            cnt = fn.new_v()
            fn.emit("bin", "sub", cnt, hi, lo)
            n1 = fn.new_v()
            fn.emit("bin", "add", n1, cnt, ("imm", 9))
            h = fn.new_v()
            fn.emit("call", h, "__alloc", [n1])
            buf = fn.new_v()
            fn.emit("bin", "add", buf, h, ("imm", 8))
            sp = fn.new_v()
            fn.emit("bin", "add", sp, obj, lo)
            fn.emit("call", None, "__memcpy", [buf, sp, cnt])
            fn.emit("store", h, ("imm", 0), cnt)      # 长度前缀
            z = fn.new_v()
            fn.emit("bin", "add", z, buf, cnt)
            fn.emit("store8", z, ("imm", 0), ("imm", 0))
            fn.emit("jmp", l_ok)
            fn.emit("label", l_bad)
            fn.emit("call", None, "__substr_fail", [])
            fn.emit("label", l_ok)
            return self._mark_str(fn, buf)

        n = self._arr_of(fn, obj)
        if n is not None or self._is_slice(fn, obj):
            if n is not None:
                ln = ("imm", n)
                base = obj                       # 数组的帧槽地址就是元素起点
                elem = None
            else:
                ln = self.slice_len(fn, obj)
                base = self.slice_ptr(fn, obj)
                elem = self._slice_elem(fn, obj)
            fn.emit("cmpset", "g", b, hi, ln)
            fn.emit("jnz", b, l_bad)
            cnt = fn.new_v()
            fn.emit("bin", "sub", cnt, hi, lo)
            off = fn.new_v()
            fn.emit("bin", "shl", off, lo, ("imm", 3))     # 元素 8 字节
            ptr = fn.new_v()
            fn.emit("bin", "add", ptr, base, off)
            fn.emit("jmp", l_ok)
            fn.emit("label", l_bad)
            fn.emit("call", None, "__substr_fail", [])
            fn.emit("label", l_ok)
            return self.make_slice(fn, ptr, cnt, elem=elem)
        raise SyntaxError("子切片 a[lo..hi] 只支持 str、切片与定长数组")

    def lower_interp(self, parts, fn, env):
        """字符串插值（v1.61）：一次分配写完整条结果。

        与手写 `"a" + x.to_str()` 的差别：整数不再先生成临时 str——直接
        `__fmt_u64` 写进结果缓冲，省掉每段一次分配 + 一次拷贝。浮点/布尔/str
        段仍各自成串，但结果只分配一次（手写 `+` 链是 1 次链分配 + n 次 to_str）。

        容量 = 8(长度前缀) + 字面量字节 + 24*整数段 + Σ(str 段运行期长度) + 1(NUL)。
        """
        items = []          # ("lit", bytes) / ("int", vreg) / ("str", vreg)
        fixed = 8 + 1
        for p in parts:
            if p[0] == "str":
                raw = p[1].encode("utf-8")
                items.append(("lit", raw))
                fixed += len(raw)
                continue
            v = self.eval(p, fn, env)
            if self._is_str(fn, v):
                items.append(("str", v))
                continue
            w = self._float_of(fn, v)
            if w:
                self.uses_f64_str = True      # __f64_to_str 的发射守卫
                s = fn.new_v()
                fn.emit("call", s, "__f64_to_str", [v])
                self._mark_str(fn, s)
                items.append(("str", s))
                continue
            if isinstance(v, int) and v in getattr(fn, "boolv", set()):
                self.uses_sfb = True          # __str_from_bool 的发射守卫
                s = fn.new_v()
                fn.emit("call", s, "__str_from_bool", [v])
                self._mark_str(fn, s)
                items.append(("str", s))
                continue
            if self._struct_of(fn, v) is not None:
                raise SyntaxError("字符串插值不支持结构体值（先用方法转成 str）")
            # 整数直接写缓冲区：__fmt_u64 与 f64 格式化同块发射，置同一守卫
            self.uses_f64_str = True
            items.append(("int", v))
            fixed += 24          # 符号 + 20 位数字 + 余量

        total = fn.new_v()
        fn.emit("mov", total, ("imm", fixed))
        for it in items:
            if it[0] != "str":
                continue
            self.uses_memcpy = True
            p8 = fn.new_v()
            fn.emit("bin", "sub", p8, it[1], ("imm", 8))
            ln = fn.new_v()
            fn.emit("load", ln, p8, ("imm", 0))
            fn.emit("bin", "add", total, total, ln)

        buf = fn.new_v()
        fn.emit("call", buf, "__alloc", [total])
        pos = fn.new_v()
        fn.emit("mov", pos, ("imm", 8))
        for it in items:
            if it[0] == "lit":
                for by in it[1]:
                    fn.emit("store8", buf, pos, ("imm", by))
                    fn.emit("bin", "add", pos, pos, ("imm", 1))
                continue
            if it[0] == "int":
                v = it[1]
                neg = fn.new_v()
                fn.emit("cmpset", "l", neg, v, ("imm", 0))
                l_pos = fn.label("ipos")
                fn.emit("jz", neg, l_pos)
                fn.emit("store8", buf, pos, ("imm", 45))
                fn.emit("bin", "add", pos, pos, ("imm", 1))
                # 取负必须落到新 vreg（v 可能就是源变量的槽，原地 neg 会把
                # 用户的变量改成相反数）；两条分支各发一次格式化调用，
                # 不做"编译期改绑 v"那种假 phi。
                av = fn.new_v()
                fn.emit("neg", av, v)
                fn.emit("call", pos, "__fmt_u64", [buf, pos, av, ("imm", 1)])
                l_done = fn.label("idone")
                fn.emit("jmp", l_done)
                fn.emit("label", l_pos)
                fn.emit("call", pos, "__fmt_u64", [buf, pos, v, ("imm", 1)])
                fn.emit("label", l_done)
                continue
            s = it[1]
            p8 = fn.new_v()
            fn.emit("bin", "sub", p8, s, ("imm", 8))
            ln = fn.new_v()
            fn.emit("load", ln, p8, ("imm", 0))
            dst = fn.new_v()
            fn.emit("bin", "add", dst, buf, pos)
            fn.emit("call", None, "__memcpy", [dst, s, ln])
            fn.emit("bin", "add", pos, pos, ln)
        fn.emit("store8", buf, pos, ("imm", 0))
        ln = fn.new_v()
        fn.emit("bin", "sub", ln, pos, ("imm", 8))
        fn.emit("store", buf, ("imm", 0), ln)
        r = fn.new_v()
        fn.emit("bin", "add", r, buf, ("imm", 8))
        return self._mark_str(fn, r)

    def lower_binop(self, e, fn, env):
        if e[1] == "+" and self._has_str_lit(e):
            # v1.3 concat 链融合：a+b+c+... 单次分配（str `+` 累积 O(n^2) 的编译器级解）
            leaves = []
            self._collect_str_chain(e, leaves)
            if len(leaves) >= 3:
                regs = []
                for leaf in leaves:
                    v = self.eval(leaf, fn, env)
                    if not self._is_str(fn, v):
                        raise SyntaxError("字符串与 int 拼接需 to_str()/chr()（typeck 前的显式报错）")
                    regs.append(v)
                self.uses_memcpy = True
                total = fn.new_v()
                fn.emit("mov", total, ("imm", 0))
                lens = []
                for v in regs:
                    l = fn.new_v()
                    fn.emit("call", l, "__str_len", [v])
                    fn.emit("bin", "add", total, total, l)
                    lens.append(l)
                n1 = fn.new_v()
                fn.emit("bin", "add", n1, total, ("imm", 9))
                h = fn.new_v()
                fn.emit("call", h, "__alloc", [n1])
                dst = fn.new_v()
                fn.emit("bin", "add", dst, h, ("imm", 8))
                pos = fn.new_v()
                fn.emit("mov", pos, ("imm", 0))      # dst 已 = h+8，pos 从 0 起
                for v, l in zip(regs, lens):
                    fn.emit("call", None, "__memcopy", [dst, pos, v, l])
                    fn.emit("bin", "add", pos, pos, l)
                fn.emit("store", h, ("imm", 0), total)  # 长度前缀
                z = fn.new_v()
                fn.emit("bin", "add", z, dst, total)
                fn.emit("store8", z, ("imm", 0), ("imm", 0))
                return self._mark_str(fn, dst)
        return self.arith(e[1], self.eval(e[2], fn, env), self.eval(e[3], fn, env), fn, env)

    def _has_str_lit(self, e):
        """链中是否含 str 字面量叶（融合的静态预判——解析器输出全以此形态出现）"""
        if isinstance(e, tuple) and e[0] == "binop" and e[1] == "+":
            return self._has_str_lit(e[2]) or self._has_str_lit(e[3])
        return isinstance(e, tuple) and e[0] == "str"

    def _collect_str_chain(self, e, leaves):
        """收集 str `+` 链的叶子 AST（左->右）；遇到非 + 节点即叶。"""
        if isinstance(e, tuple) and e[0] == "binop" and e[1] == "+":
            self._collect_str_chain(e[2], leaves)
            self._collect_str_chain(e[3], leaves)
            return
        leaves.append(e)

    def make_fnum(self, fn, v, width):
        """浮点字面量：IEEE754 位模式存进通用寄存器，并打上浮点标记"""
        if width == "f32":
            bits = struct.unpack("<I", struct.pack("<f", v))[0]
        else:
            bits = struct.unpack("<Q", struct.pack("<d", v))[0]
        d = fn.new_v()
        fn.emit("mov", d, ("imm", bits))
        return self._mark_float(fn, d, width)

    def conv_to(self, fn, v, from_w, to_w):
        """浮点宽度 / 整数<->浮点转换（与 C 隐式转换规则一致）。
        from_w/to_w：None=整数，'f32'，'f64'。同型零开销直通。"""
        if from_w == to_w:
            return v
        kind = {(None, "f64"): "i2f64", (None, "f32"): "i2f32",
                ("f64", None): "f64i", ("f32", None): "f32i",
                ("f32", "f64"): "f32f64", ("f64", "f32"): "f64f32"}.get((from_w, to_w))
        if kind is None:
            raise SyntaxError("不支持的类型转换")
        d = fn.new_v()
        fn.emit("fcvt", kind, d, v)
        return self._mark_float(fn, d, to_w) if to_w else d

    def arith(self, op, a, b, fn, env):
        if op in ("&&", "||"):
            return self._mark_bool(fn, self.lower_logic(op, a, b, fn, env))
        wa, wb = self._float_of(fn, a), self._float_of(fn, b)
        # 字符串拼接（str 是一等类型，运行库自举）
        if op == "+" and (self._is_str(fn, a) or self._is_str(fn, b)):
            if wa or wb:
                raise SyntaxError("字符串与浮点不能拼接；请用 to_str()")
            if not (self._is_str(fn, a) and self._is_str(fn, b)):
                # v1.14：str + int 从"静默把 int 当 str 句柄读"改为编译期
                # fail-fast（此前直接 __str_concat(a, b)，运行期段错误）。
                # 库内部的指针算术请用 mem_ptr(p, off)（返回纯 int）。
                raise SyntaxError(
                    "字符串与 int 拼接需 to_str()；指针偏移用 mem_ptr(p, off)")
            d = fn.new_v()
            fn.emit("call", d, "__str_concat", [a, b])
            return self._mark_str(fn, d)
        # 字符串相等：内容比较（而非地址比较）
        if op in ("==", "!=") and (self._is_str(fn, a) or self._is_str(fn, b)):
            if wa or wb:
                raise SyntaxError("字符串与浮点不能比较；请用 to_str()")
            eq = fn.new_v()
            fn.emit("call", eq, "__str_eq", [a, b])
            if op == "==":
                return self._mark_bool(fn, eq)
            d = fn.new_v()
            fn.emit("cmpset", "e", d, eq, ("imm", 0))
            return self._mark_bool(fn, d)
        # 浮点运算：按 C 提升规则统一宽度后计算（int 隐式转浮点）
        if wa or wb:
            if op in ("%", "&", "|", "^", "<<", ">>"):
                raise SyntaxError(f"浮点不支持运算符 {op}")
            w = "f64" if "f64" in (wa, wb) else "f32"
            a = self.conv_to(fn, a, wa, w)
            b = self.conv_to(fn, b, wb, w)
            if op in ("==", "!=", "<", "<=", ">", ">="):
                fcc = {"==": "e", "!=": "ne", "<": "l", "<=": "le", ">": "g", ">=": "ge"}[op]
                d = fn.new_v()
                fn.emit("fcmpset", w, fcc, d, a, b)
                return self._mark_bool(fn, d)
            fop = {"+": "add", "-": "sub", "*": "mul", "/": "div"}.get(op)
            if fop is None:
                raise SyntaxError(f"不支持的浮点运算符 {op}")
            d = fn.new_v()
            fn.emit("fbin", w, fop, d, a, b)
            return self._mark_float(fn, d, w)
        # 常量折叠（整数截断语义，与 C 一致）
        if isinstance(a, tuple) and isinstance(b, tuple) and a[0] == "imm" and b[0] == "imm":
            x, y = a[1], b[1]
            if op == "+":
                return ("imm", x + y)
            if op == "-":
                return ("imm", x - y)
            if op == "*":
                return ("imm", x * y)
            if op in ("/", "%") and y != 0:
                q = abs(x) // abs(y) * (1 if (x >= 0) == (y >= 0) else -1)
                return ("imm", q if op == "/" else x - q * y)
            if op == "&":
                return ("imm", x & y)
            if op == "|":
                return ("imm", x | y)
            if op == "^":
                return ("imm", x ^ y)
            cmp_map = {"==": x == y, "!=": x != y, "<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}
            if op in cmp_map:
                return ("imm", 1 if cmp_map[op] else 0)
        d = fn.new_v()
        if op in ("<", "<=", ">", ">=") and (self._is_str(fn, a) or self._is_str(fn, b)):
            # 字符串按字节字典序比较（早期这里走的是指针比较，属于语义 bug）
            self.uses_str_cmp = True
            c = fn.new_v()
            fn.emit("call", c, "__str_cmp", [a, b])
            cc = {"<": "l", "<=": "le", ">": "g", ">=": "ge"}[op]
            fn.emit("cmpset", cc, d, c, ("imm", 0))
            return self._mark_bool(fn, d)
        if op in ("==", "!=", "<", "<=", ">", ">="):
            cc = {"==": "e", "!=": "ne", "<": "l", "<=": "le", ">": "g", ">=": "ge"}[op]
            fn.emit("cmpset", cc, d, a, b)
            return self._mark_bool(fn, d)
        # 强度削减：乘 2^k -> shl
        # 除法/取模特例与强度削减
        if op in ("/", "%") and isinstance(b, tuple) and b[0] == "imm" and b[1] == 1:
            d = fn.new_v()
            fn.emit("mov", d, a if op == "/" else ("imm", 0))
            return d
        # 2 的幂除法/取模特化（v1.5）：x / 2^k、x % 2^k 不再走 9 条魔数除法。
        # 有符号向零取整：q = (x + ((x>>63) & (d-1))) >> k，r = x - (q << k)。
        # 值域已知非负时：q = x >> k（1 条）、r = x & (d-1)（1 条）。
        # 这是 Collatz / 位运算 / 环形缓冲下标最常踩的形态（报告 §4.2：2.17×）。
        if (op in ("/", "%") and isinstance(b, tuple) and b[0] == "imm"
                and b[1] > 1 and (b[1] & (b[1] - 1)) == 0):
            k = b[1].bit_length() - 1
            if self._is_nonneg(fn, a):
                if op == "/":
                    fn.emit("bin", "sar", d, a, ("imm", k))
                else:
                    fn.emit("bin", "and", d, a, ("imm", b[1] - 1))
                return d
            sm = fn.new_v()
            fn.emit("bin", "sar", sm, a, ("imm", 63))            # 符号掩码
            bias = fn.new_v()
            fn.emit("bin", "and", bias, sm, ("imm", b[1] - 1))
            x2 = fn.new_v()
            fn.emit("bin", "add", x2, a, bias)
            q = fn.new_v()
            fn.emit("bin", "sar", q, x2, ("imm", k))             # q = trunc(x/d)
            if op == "/":
                return q
            qd = fn.new_v()
            fn.emit("bin", "shl", qd, q, ("imm", k))
            r = fn.new_v()
            fn.emit("bin", "sub", r, a, qd)                       # r = x - q*d
            return r
        # 魔数乘高位替代 idiv（分支无关，含符号修正）
        if op in ("/", "%") and isinstance(b, tuple) and b[0] == "imm" and 0 < b[1] < 2**63:
            mag = magic_unsigned(b[1])
            if mag:
                M, sh = mag
                x = a
                if self._is_nonneg(fn, x):
                    # 值域已知非负：跳过符号修正（省 4 条/迭代，v1.3 值域分析）
                    t = fn.new_v()
                    fn.emit("bin", "umulhi", t, x, ("imm", M))
                    fn.emit("bin", "sar", t, t, ("imm", sh))     # t = x / d
                    q = t
                    if op == "/":
                        return q
                    qd = fn.new_v()
                    fn.emit("bin", "mul", qd, q, ("imm", b[1]))
                    r = fn.new_v()
                    fn.emit("bin", "sub", r, x, qd)              # r = x - q*d
                    return r
                mask = fn.new_v()
                fn.emit("bin", "sar", mask, x, ("imm", 63))     # mask = x < 0 ? -1 : 0
                ax = fn.new_v()
                fn.emit("bin", "xor", ax, x, mask)
                fn.emit("bin", "sub", ax, ax, mask)              # ax = |x|
                t = fn.new_v()
                fn.emit("bin", "umulhi", t, ax, ("imm", M))
                fn.emit("bin", "sar", t, t, ("imm", sh))         # t = |x| / d
                q = fn.new_v()
                fn.emit("bin", "xor", q, t, mask)
                fn.emit("bin", "sub", q, q, mask)                # q = trunc(x / d)
                if op == "/":
                    return q
                qd = fn.new_v()
                fn.emit("bin", "mul", qd, q, ("imm", b[1]))
                r = fn.new_v()
                fn.emit("bin", "sub", r, x, qd)                  # r = x - q*d
                return r
        if op == "*" and isinstance(b, tuple) and b[0] == "imm" and b[1] > 0 and (b[1] & (b[1] - 1)) == 0:
            k = b[1].bit_length() - 1
            fn.emit("bin", "shl", d, a, ("imm", k))
            return d
        if op == "*" and isinstance(a, tuple) and a[0] == "imm" and a[1] > 0 and (a[1] & (a[1] - 1)) == 0:
            k = a[1].bit_length() - 1
            fn.emit("bin", "shl", d, b, ("imm", k))
            return d
        if op == "+" and isinstance(a, tuple) and a[0] == "imm" and a[1] == 0:
            fn.emit("mov", d, b)
            return d
        if op == "+" and isinstance(b, tuple) and b[0] == "imm" and b[1] == 0:
            fn.emit("mov", d, a)
            return d
        if op == "-" and isinstance(b, tuple) and b[0] == "imm" and b[1] == 0:
            fn.emit("mov", d, a)
            return d
        # 非负值域传播（v1.3 通用值域分析最小版：只标确凿模式）
        if op == "+" and self._is_nonneg(fn, a) and self._is_nonneg(fn, b):
            self._mark_nonneg(fn, d)
        if op == "*" and self._is_nonneg(fn, a) and self._is_nonneg(fn, b):
            self._mark_nonneg(fn, d)
        if op == "mod" and isinstance(b, tuple) and b[0] == "imm" and b[1] > 0:
            self._mark_nonneg(fn, d)                       # 模非负
        if op not in ("add", "sub", "mul", "div", "mod", "and", "or", "xor", "shl", "shr", "sar"):
            opmap = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod",
                     "&": "and", "|": "or", "^": "xor",
                     "<<": "shl", ">>": "sar", ">>>": "shr"}
            if op not in opmap:
                raise SyntaxError(f"不支持的运算符 {op}")
            op = opmap[op]
        fn.emit("bin", op, d, a, b)
        return d

    def lower_vec_method(self, m, obj, elem, args, fn, env):
        """v.push/get/set/pop/len/clear（元素恒为 8 字节字）"""
        self.uses_vec = True

        def one_arg():
            if len(args) != 1:
                raise SyntaxError(f"vec.{m}() 需要且只需要一个实参")
            return self.eval(args[0], fn, env)

        if m == "len":
            if args:
                raise SyntaxError("vec.len() 不接受实参")
            d = fn.new_v()
            fn.emit("call", d, "__vec_len", [obj])
            return d
        if m == "clear":
            if args:
                raise SyntaxError("vec.clear() 不接受实参")
            fn.emit("call", None, "__vec_clear", [obj])
            return ("imm", 0)
        if m == "push":
            v = one_arg()
            nb = self.narrow_of(("named", elem)) if isinstance(elem, str) else None
            if nb is not None:
                v = self.trunc_to(fn, v, nb)      # vec[u8] 等窄元素（v1.40）
            if (isinstance(elem, tuple) and elem[0] == "agg"
                    and self._is_iface(elem[1])):
                sn = self._struct_of(fn, v)
                if sn is not None and sn != elem[1]:
                    v = self.box_iface(fn, v, sn, elem[1])   # vec[Shape].push(Circle)
                # 元素槽没有 Drop：push 之后元素永久持有这一箱（v1.81）
                self._iface_share(fn, v, v)
            if isinstance(elem, tuple) and elem[0] == "agg":
                fn.emit("call", None, "__vec_push_n", [obj, v])
            else:
                fn.emit("call", None, "__vec_push", [obj, v])
            return ("imm", 0)
        if m == "pop":
            if args:
                raise SyntaxError("vec.pop() 不接受实参")
            if isinstance(elem, tuple) and elem[0] == "agg":
                dst = self.alloc_struct(fn, elem[1])
                fn.emit("call", None, "__vec_pop_n", [obj, dst])
                return self._mark_struct(fn, dst, elem[1])
            d = fn.new_v()
            fn.emit("call", d, "__vec_pop", [obj])
            if elem == "str":
                self._mark_str(fn, d)
            if isinstance(elem, tuple) and elem[0] == "vecinner":
                # 嵌套 vec：弹出的是内层句柄，重挂内层标签（v1.12）
                self._mark_vec(fn, d, elem[1])
            if isinstance(elem, tuple) and elem[0] == "mapinner":
                # vec[map]（v1.37）：弹出的是 map 句柄，重挂 map 标记
                self._mark_map(fn, d, elem[1], elem[2])
            return d
        if m == "get":
            i = one_arg()
            if isinstance(elem, tuple) and elem[0] == "agg":
                dst = self.alloc_struct(fn, elem[1])
                fn.emit("call", None, "__vec_get_n", [obj, i, dst])
                return self._mark_struct(fn, dst, elem[1])
            d = fn.new_v()
            fn.emit("call", d, "__vec_get", [obj, i])
            if elem == "str":
                self._mark_str(fn, d)
            if isinstance(elem, tuple) and elem[0] == "vecinner":
                # 嵌套 vec：get 返回内层句柄，重挂内层标签——
                # row.push / row.get 从此认领类型（v1.12 vec[vec[T]] 解锁）
                self._mark_vec(fn, d, elem[1])
            if isinstance(elem, tuple) and elem[0] == "mapinner":
                # vec[map]（v1.37）：get 返回 map 句柄，重挂 map 标记——
                # m.set / m.get 链式调用从此认领类型
                self._mark_map(fn, d, elem[1], elem[2])
            return d
        if m == "set":
            if len(args) != 2:
                raise SyntaxError("vec.set(i, v) 需要两个实参")
            i = self.eval(args[0], fn, env)
            v = self.eval(args[1], fn, env)
            nb = self.narrow_of(("named", elem)) if isinstance(elem, str) else None
            if nb is not None:
                v = self.trunc_to(fn, v, nb)      # vec[u8] 等窄元素（v1.40）
            if isinstance(elem, tuple) and elem[0] == "agg":
                if self._is_iface(elem[1]):
                    sn = self._struct_of(fn, v)
                    if sn is not None and sn != elem[1]:
                        v = self.box_iface(fn, v, sn, elem[1])
                    self._iface_share(fn, v, v)
                fn.emit("call", None, "__vec_set_n", [obj, i, v])
            else:
                fn.emit("call", None, "__vec_set", [obj, i, v])
            return ("imm", 0)
        raise SyntaxError(f"vec 不支持方法 {m}（可用 push/get/set/pop/len/clear）")

    def lower_map_method(self, m, obj, mp, args, fn, env):
        """m.set/get/has/del -> __map_* 运行时（开放寻址 + 线性探测）。
        键相等/哈希在运行时按句柄 ktag 分派（str 走 __str_eq 内容比较）；
        这里在编译期校验键/值实参与声明的 K/V 标签一致，不许静默错编。
        值扩容（v1.41）：聚合值走 __map_set_n/__map_get_n（N 字槽按值拷入/
        拷出），标量值走原 __map_set/__map_get（热路径零改动）。"""
        kt, vt = mp
        self.uses_map = True
        agg_v = self.is_agg(vt)      # 值是具名 struct/enum（v1.41）

        def key_arg(a):
            kv = self.eval(a, fn, env)
            self.check_map_arg("键", kt, self._is_str(fn, kv))
            return kv

        if m == "set":
            if len(args) != 2:
                raise SyntaxError("m.set(k, v) 需要两个实参")
            kv = key_arg(args[0])
            vv = self.eval(args[1], fn, env)
            if agg_v:
                # 值是聚合：实参必须是同名 struct/enum 值（帧槽地址），
                # 运行时按值拷 N 字进表槽——与 struct 拷贝同语义
                if self._struct_of(fn, vv) != vt:
                    raise SyntaxError(f"map 值类型是 {vt}，实参不是 {vt} 值")
                d = fn.new_v()
                fn.emit("call", d, "__map_set_n", [obj, kv, vv])
                return d
            self.check_map_arg("值", vt, self._is_str(fn, vv))
            d = fn.new_v()
            fn.emit("call", d, "__map_set", [obj, kv, vv])
            return d
        if m == "get":
            if len(args) != 1:
                raise SyntaxError("m.get(k) 需要且只需要一个实参")
            kv = key_arg(args[0])
            if agg_v:
                # 拷出到新帧槽并挂聚合标记——let/传参/取字段全部按既有
                # struct 值语义走（与 vec[Struct].get 同构）
                dst = self.alloc_struct(fn, vt)
                fn.emit("call", None, "__map_get_n", [obj, kv, dst])
                return dst
            d = fn.new_v()
            fn.emit("call", d, "__map_get", [obj, kv])
            return self._mark_str(fn, d) if vt == "str" else d
        if m == "has":
            if len(args) != 1:
                raise SyntaxError("m.has(k) 需要且只需要一个实参")
            kv = key_arg(args[0])
            d = fn.new_v()
            fn.emit("call", d, "__map_has", [obj, kv])
            return self._mark_bool(fn, d)
        if m == "del":
            if len(args) != 1:
                raise SyntaxError("m.del(k) 需要且只需要一个实参")
            kv = key_arg(args[0])
            d = fn.new_v()
            fn.emit("call", d, "__map_del", [obj, kv])
            return d
        raise SyntaxError(f"map 未知方法 .{m}（支持 set/get/has/del）")

    @staticmethod
    def check_map_arg(which, want, is_str):
        """map 键/值实参类型校验：str 走内容语义，类型不匹配必须报错"""
        if want == "str" and not is_str:
            raise SyntaxError(f"map {which}类型是 str，实参不是 str")
        if want != "str" and is_str:
            raise SyntaxError(f"map {which}类型是 {want}，不能用 str 实参")

    def lower_spawn(self, call, fn, env):
        """spawn f(args) -> 任务句柄（v0.4）。

        并行路径：参数拷贝进 __alloc 参数块 -> 新建栈/CreateThread ->
        worker 调目标函数并把返回值写回参数块首字 -> join 等待并取结果。
        约束：实参/返回值仅支持标量（int/bool/str 指针）；结构体/枚举按值跨线程
        涉及生命周期，留到所有权/借用落地后再开（明确报错，不静默降级）。
        """
        name = call[1][-1]
        if name not in self.fns_ast:
            raise SyntaxError(f"spawn 的目标必须是用户函数：{name}")
        target = self.fns_ast[name]
        ret = target["ret"]
        if ret[0] == "named" and self.is_agg(ret[1]):
            raise SyntaxError("spawn 暂不支持结构体/枚举返回值")
        if ret[0] == "slice" or ret == ("named", "str"):
            raise SyntaxError("spawn 返回值暂支持 int/bool/void（不支持 str/slice）")
        params = target["params"]
        args = call[2]
        if len(args) != len(params):
            raise SyntaxError(f"{name} 需要 {len(params)} 个实参，spawn 给了 {len(args)}")
        for pn, pt in params:
            if pt[0] == "slice" or (pt[0] == "named" and self.is_agg(pt[1])):
                raise SyntaxError(f"spawn 实参 {pn} 暂不支持结构体/枚举/slice")
        vals = [self.eval(a, fn, env) for a in args]

        if self.is_serial():
            if ret == ("named", "void"):
                fn.emit("call", None, name, vals)
                return ("imm", 0)
            d = fn.new_v()
            fn.emit("call", d, name, vals)
            return d
        if self.arch != "x86_64":
            raise SyntaxError("spawn（并行）目前仅支持 x86_64 后端")
        self.uses_join = True

        # 参数块：字 0 = 返回值，字 1.. = 实参
        n = len(vals)
        blk = fn.new_v()
        fn.emit("call", blk, "__alloc", [("imm", 8 * (1 + n))])
        for i, v in enumerate(vals):
            fn.emit("store", blk, ("imm", 1 + i), v)

        wname = f"__spawn_{fn.name}_{self.spawn_id}"
        self.spawn_id += 1
        w = Fn(wname)
        w.no_inline = True          # 跑在另一个栈上（与 parfor worker 同理）
        wp = w.new_v()
        w.emit("args", [wp])
        av = []
        for i, (pn, pt) in enumerate(params):
            v = w.new_v()
            w.emit("load", v, wp, ("imm", 1 + i))
            if pt == ("named", "str"):
                self._mark_str(w, v)
            elif pt == ("named", "bool"):
                self._mark_bool(w, v)
            av.append(v)
        if ret == ("named", "void"):
            w.emit("call", None, name, av)
            w.emit("store", wp, ("imm", 0), ("imm", 0))
        else:
            rv = w.new_v()
            w.emit("call", rv, name, av)
            w.emit("store", wp, ("imm", 0), rv)
        w.emit("ret", ("imm", 0))
        self.out.append(w)

        if self.platform == "windows":
            wrap = Fn(wname + "__entry")
            wrap.win_thread = True
            xp = wrap.new_v()
            wrap.emit("winargs", [xp])
            wrap.emit("call", None, wname, [xp])
            wrap.emit("ret", ("imm", 0))
            self.out.append(wrap)
            tid = fn.new_v()
            fn.emit("winapi", tid, "CreateThread",
                    [("imm", 0), ("imm", 0), ("fnaddr", wrap.name),
                     blk, ("imm", 0), ("imm", 0)])
        else:
            st = fn.new_v()
            fn.emit("syscall", st, self.sc["mmap"],
                    [("imm", 0), ("imm", STACK_SZ), ("imm", PROT_RW),
                     ("imm", MAP_PRIVATE_ANON), ("imm", -1), ("imm", 0)])
            top = fn.new_v()
            fn.emit("bin", "add", top, st, ("imm", STACK_SZ - 256))
            # 参数块指针放在新栈顶下方 8 字节；子线程用 spawn_child 从 [rsp-8] 取。
            # （不能依赖寄存器/父栈溢出槽：子线程和父线程并发执行，父栈槽会被复用）
            fn.emit("store", st, ("imm", (STACK_SZ - 264) // 8), blk)
            pid = fn.new_v()
            fn.emit("syscall", pid, self.sc["clone"],
                    [("imm", CLONE_FLAGS), top, ("imm", 0),
                     ("imm", 0), ("imm", 0), ("imm", 0)])
            l_child, l_after = fn.label("spchild"), fn.label("spafter")
            fn.emit("jz", pid, l_child)
            fn.emit("jmp", l_after)
            fn.emit("label", l_child)
            fn.emit("spawn_child", wname)
            fn.emit("label", l_after)
            tid = pid

        rec = fn.new_v()
        fn.emit("call", rec, "__alloc", [("imm", 16)])
        fn.emit("store", rec, ("imm", 0), tid)
        fn.emit("store", rec, ("imm", 1), blk)
        return rec

    def lower_logic(self, op, a, b, fn, env):
        """短路求值 -> 0/1

        注意两条分支的「落空值」不同：
          a && b：两个操作数都非零 才是 true  -> 两次 jz 都没跳 = 真
          a || b：两个操作数都为零   才是 false -> 两次 jnz 都没跳 = 假
        早期这里共用了一段 `mov d, 1` 尾巴，导致 || 恒为真（0 || 0 == true）。
        """
        d = fn.new_v()
        l_true, l_false, l_end = fn.label("t"), fn.label("f"), fn.label("e")
        if op == "&&":
            fn.emit("jz", a, l_false)
            fn.emit("jz", b, l_false)
            fn.emit("mov", d, ("imm", 1))
        else:
            fn.emit("jnz", a, l_true)
            fn.emit("jnz", b, l_true)
            fn.emit("mov", d, ("imm", 0))
        fn.emit("jmp", l_end)
        fn.emit("label", l_true)
        fn.emit("mov", d, ("imm", 1))
        fn.emit("jmp", l_end)
        fn.emit("label", l_false)
        fn.emit("mov", d, ("imm", 0))
        fn.emit("label", l_end)
        return d

    # =====================================================================
    # 闭包 / 捕获（v1.95）
    # =====================================================================
    # 设计（与既有聚合机制同构，不新增 ABI 概念）：
    #   * 闭包值 = `closure` 聚合 {code, env} 两字（与接口值 {data, vt} 同构）；
    #   * 捕获环境 = 堆上一段 n*8 字节，**创建时按值快照**；
    #   * lambda 体 = 一个合成的顶层函数 `__lam_N`，形参表前面多一个
    #     `__env__`（隐式），体内对捕获变量的引用降级为 `load __env__[i]`；
    #   * 调用点：`f(args)` 在 f 的静态类型是 `closure` 时降级为
    #     `code = f[0]; env = f[1]; callr code, [env, args...]`。
    # 纯函数名（`foo`）仍是裸代码地址（int）走原路径——两种值互不干扰。

    @staticmethod
    def _lambda_bound(body, out):
        """lambda 体内**新绑定**的名字：let / 循环变量 / match 绑定 /
        嵌套 lambda 形参。这些名字一律不捕获（保守：宁可编译报"未定义变量"，
        也不把外层同名变量错抓进来）。"""
        def walk(x):
            if isinstance(x, tuple):
                if not x:
                    return
                k = x[0]
                if k == "let" and len(x) > 2 and isinstance(x[2], str):
                    out.add(x[2])
                elif k in ("for", "parfor", "foreach") \
                        and len(x) > 1 and isinstance(x[1], str):
                    out.add(x[1])
                elif k == "pat" and len(x) > 2:
                    for b in x[2]:
                        if b:
                            out.add(b)
                elif k == "lambda" and len(x) > 1:
                    for n, _t in x[1]:
                        out.add(n)
                for y in x:
                    walk(y)
            elif isinstance(x, list):
                for y in x:
                    walk(y)
            elif isinstance(x, dict):
                for y in x.values():
                    walk(y)
        walk(body)

    @staticmethod
    def _lambda_uses(body, env):
        """lambda 体内出现过的变量名（按首次出现顺序；`("name", s)` 才是
        变量引用——`("field", e, s)` / `("method", e, s, ...)` 里的 s 不是）。
        `("path", [head, ...])` 的 head 若在本层作用域可见，是 `v.x.y` 字段链
        （不是枚举/类型路径），同样算一次引用。"""
        used = []

        def walk(x):
            if isinstance(x, tuple):
                if not x:
                    return
                if x[0] == "name" and len(x) > 1 and isinstance(x[1], str):
                    used.append(x[1])
                    return
                if x[0] == "path" and len(x) > 1 and isinstance(x[1], list) \
                        and x[1] and x[1][0] in env:
                    used.append(x[1][0])
                for y in x:
                    walk(y)
            elif isinstance(x, list):
                for y in x:
                    walk(y)
            elif isinstance(x, dict):
                for y in x.values():
                    walk(y)
        walk(body)
        return used

    @staticmethod
    def _lambda_assigns(body):
        """lambda 体内被赋值的名字（`x = ...`）。捕获变量不可写——写入只改
        环境副本，会让调用方误以为原变量变了，所以编译期直接拒绝。"""
        names = set()

        def walk(x):
            if isinstance(x, tuple):
                if not x:
                    return
                if x[0] == "assign" and len(x) > 1 and isinstance(x[1], str):
                    names.add(x[1])
                for y in x:
                    walk(y)
            elif isinstance(x, list):
                for y in x:
                    walk(y)
            elif isinstance(x, dict):
                for y in x.values():
                    walk(y)
        walk(body)
        return names

    def _capture_tag(self, fn, v, name, line):
        """捕获槽的类型标签（决定 lambda 体内 load 出来后怎么重新打标记）。

        v1.95 边界：只捕获**一个槽**的值——标量 / str / f64 / vec·map·chan 句柄。
        聚合（struct/enum）、切片、定长数组、rc 句柄捕获会失效或破坏所有权
        （帧槽地址、视图生命周期、引用计数），一律编译期拒绝。"""
        if (self._struct_of(fn, v) is not None or self._is_slice(fn, v)
                or self._arr_of(fn, v) is not None or self._rc_of(fn, v) is not None):
            raise SyntaxError(
                f"line {line}: 闭包暂不支持捕获聚合/切片/数组/rc 变量 {name!r}"
                f"（v1.95 边界：只捕获标量与 vec/map/chan 句柄）")
        if self._is_str(fn, v):
            return ("str",)
        fw = self._float_of(fn, v)
        if fw:
            return ("float", fw)
        if self._is_vec(fn, v):
            return ("vec", self._vec_elem(fn, v))
        mp = self._map_of(fn, v)
        if mp is not None:
            return ("map", mp[0], mp[1])
        if self._is_chan(fn, v):
            return ("chan",)
        return ("int",)

    def _apply_capture_tag(self, fn, v, tag):
        """把捕获槽 load 出来的 vreg 重新打上类型标记（与创建点同源）。"""
        k = tag[0]
        if k == "str":
            fn.strv.add(v)
        elif k == "float":
            self._mark_float(fn, v, tag[1])
        elif k == "vec":
            self._mark_vec(fn, v, tag[1])
        elif k == "map":
            self._mark_map(fn, v, tag[1], tag[2])
        elif k == "chan":
            self._mark_chan(fn, v)

    def _lambda_captures(self, params, body, env, line, fn):
        """自由变量 = 体内出现的名字 - 体内新绑定 - 形参，且**外层此刻可见**。
        顺序按名字排序：环境布局与源码书写顺序无关，编译产物可复现。"""
        bound = {n for n, _t in params}
        self._lambda_bound(body, bound)
        assigned = self._lambda_assigns(body)
        caps, seen = [], set()
        for name in self._lambda_uses(body, env):
            if name in bound or name in seen or name not in env:
                continue
            seen.add(name)
            caps.append(name)
        caps.sort()
        out = []
        for name in caps:
            if name in assigned:
                raise SyntaxError(
                    f"line {line}: 闭包内不能给捕获变量 {name!r} 赋值"
                    f"（捕获按值快照，写入不会传回外层）")
            v = env[name]
            if not isinstance(v, int):
                raise SyntaxError(
                    f"line {line}: 闭包不能捕获编译期常量 {name!r}")
            out.append((name, self._capture_tag(fn, v, name, line)))
        return out

    def lower_lambda(self, e, fn, env):
        params, ret, body, line = e[1], e[2], e[3], e[4]
        caps = self._lambda_captures(params, body, env, line, fn)
        self.lam_seq += 1
        lname = f"__lam_{self.lam_seq}"
        self.pending_lambdas.append({
            "name": lname, "params": list(params), "ret": ret, "body": body,
            "captures": caps, "line": line,
            # v2.03：记下它属于哪个源码函数——增量复用时按父函数决定去留
            "owner": self._cur_owner})
        dst = self.alloc_struct(fn, "closure")
        code = fn.new_v()
        fn.emit("mov", code, ("fnaddr", lname))
        fn.emit("store", dst, ("imm", 0), code)
        # 签名随值走（编译期表，不进产物）：调用点据此恢复返回值类型与实参转换
        fn.closig[dst] = (tuple(params), ret)
        if not caps:
            fn.emit("store", dst, ("imm", 1), ("imm", 0))
            return dst
        raw = fn.new_v()
        fn.emit("call", raw, "__alloc", [("imm", 8 * len(caps))])
        for i, (cname, _tag) in enumerate(caps):
            src = env[cname]
            if not isinstance(src, int):
                src = fn.new_v()
                fn.emit("mov", src, env[cname])
            fn.emit("store", raw, ("imm", i), src)
        fn.emit("store", dst, ("imm", 1), raw)
        return dst

    def lower_pending_lambdas(self):
        """外层函数全部降级完之后再降级 lambda 体：lambda 体本身可能再产生
        lambda（嵌套捕获），所以用"边降边追加"的队列。"""
        i = 0
        while i < len(self.pending_lambdas):
            lam = self.pending_lambdas[i]
            i += 1
            body = list(lam["body"])
            self._cur_owner = lam.get("owner")
            # 块尾表达式即返回值（ret 非 void 时）：`fn(x: int) -> int { x + 1 }`
            if lam["ret"] != ("named", "void") and body \
                    and isinstance(body[-1], tuple) and body[-1][0] == "expr":
                body[-1] = ("return", body[-1][1])
            self.lower_fn({
                "name": lam["name"],
                "params": [("__env__", ("named", "int"))] + list(lam["params"]),
                "ret": lam["ret"],
                "body": body,
                "captures": lam["captures"],
                "line": lam["line"],
            })
            self.fn_owner.setdefault(lam["name"], lam.get("owner"))

    def lower_ffi(self, name, e, fn, env):
        """@ffi 调用（v1.87）：把实参按 Win64 寄存器类分好，发射一条 'ffi'。

        指令形态：('ffi', dst|None, dll, sym, kinds, ret, [args])
          kinds: 每个实参一个 "i"（整数寄存器 RCX/RDX/R8/R9 -> 栈）或
                 "f64"/"f32"（XMM0-3 -> 栈）；由**声明**的形参类型决定，
                 不看实参推断——C 侧的寄存器类只由原型说了算。
          ret:   "int"/"bool"（RAX）/ "f64"/"f32"（XMM0）/ "void"。

        平台差异全部留在发射层（qlm_pe.WinCodegen.gen_ffi）；这里只做
        语言层的三件事：类型对账、隐式整数->浮点转换、结果打标记。
        """
        dll, sym, ptypes, ret = self.ffi_decls[name]
        if len(e[2]) != len(ptypes):
            raise SyntaxError(
                f"{name} 是 @ffi 声明，需要 {len(ptypes)} 个实参，"
                f"得到 {len(e[2])}")
        args, kinds = [], []
        for i, a in enumerate(e[2]):
            v = self.eval(a, fn, env)
            pt = ptypes[i]
            if self._is_str(fn, v) or a[0] == "str":
                raise SyntaxError(
                    f"{name} 的第 {i + 1} 个实参是 str——FFI 形参里没有 str"
                    f"（长度前缀 ≠ NUL 结尾）；请用 cstr(s) 转成指针再传")
            if pt in ("f64", "f32"):
                # C 的隐式转换口径：整数实参自动拓宽成浮点
                args.append(self.conv_to(fn, v, self._float_of(fn, v), pt))
                kinds.append(pt)
            else:
                if self._float_of(fn, v):
                    raise SyntaxError(
                        f"{name} 的第 {i + 1} 个形参是 {pt}，浮点实参不能"
                        f"隐式转整数；请显式 to_int(x)")
                args.append(v)
                kinds.append("i")
        dst = fn.new_v() if ret != "void" else None
        fn.emit("ffi", dst, dll, sym, tuple(kinds), ret, args)
        if ret == "void":
            return ("imm", 0)
        if ret in ("f64", "f32"):
            return self._mark_float(fn, dst, ret)
        if ret == "bool":
            return self._mark_bool(fn, dst)
        return dst

    def lower_call(self, e, fn, env):
        name = e[1][-1]
        if name == "print":
            arg = e[2][0]
            spec = self.eval(arg, fn, env)
            if self._struct_of(fn, spec) is not None:
                raise SyntaxError("print 暂不支持结构体/枚举；请打印具体字段或 match 解构")
            if self._map_of(fn, spec) is not None:
                raise SyntaxError("print 不支持 map 句柄；请打印 get 到的值")
            # 按值类型选打印函数
            if arg[0] == "str" or self._is_str(fn, spec):
                tgt = "__print_cstr"
            elif arg[0] == "bool" or (isinstance(spec, int) and spec in getattr(fn, "boolv", set())):
                tgt = "__print_bool"
            elif self._float_of(fn, spec):
                # 浮点：先格式化再打印（f32 先拓宽到 f64，与 C (double) 转换一致）
                spec = self.conv_to(fn, spec, self._float_of(fn, spec), "f64")
                self.uses_f64_str = True
                s = fn.new_v()
                fn.emit("call", s, "__f64_to_str", [spec])
                fn.emit("call", None, "__print_cstr", [s])
                return ("imm", 0)
            else:
                tgt = "__print_i64"
            fn.emit("call", None, tgt, [spec])
            return ("imm", 0)
        if name == "eprint":
            # eprint(x)：与 print 同样的格式化，但写 stderr（诊断输出专用）
            if len(e[2]) != 1:
                raise SyntaxError("eprint(x) 需要一个实参")
            spec = self.eval(e[2][0], fn, env)
            if self._is_str(fn, spec) or e[2][0][0] == "str":
                sp = spec
            elif self._float_of(fn, spec):
                x = self.conv_to(fn, spec, self._float_of(fn, spec), "f64")
                self.uses_f64_str = True
                sp = fn.new_v()
                fn.emit("call", sp, "__f64_to_str", [x])
            elif e[2][0][0] == "bool" or (isinstance(spec, int) and spec in getattr(fn, "boolv", set())):
                sp = fn.new_v()
                fn.emit("call", sp, "__str_from_bool", [spec])
            else:
                sp = fn.new_v()
                fn.emit("call", sp, "__str_from_i64", [spec])
            n = self.str_len(fn, sp)
            self.emit_write(fn, 2, sp, n)
            nl = fn.new_v()
            fn.emit("movaddr", nl, self.intern_str("\n"))
            self.emit_write(fn, 2, nl, ("imm", 1))
            return ("imm", 0)
        if name == "exit":
            # exit(code)：直接结束进程（不跑析构——Quelmara 没有析构）
            if len(e[2]) != 1:
                raise SyntaxError("exit(code) 需要一个实参")
            code = self.eval(e[2][0], fn, env)
            self.emit_exit(fn, code)
            return ("imm", 0)
        if name in ("rc_new", "rc_get", "rc_clone", "rc_drop", "rc_count"):
            return self.lower_rc(name, e, fn, env)
        if name in ("to_float", "to_f32", "to_int") and name not in self.fns_ast:
            if len(e[2]) != 1:
                raise SyntaxError(f"{name}(x) 需要且只需要一个实参")
            x = self.eval(e[2][0], fn, env)
            if name == "to_int" and self._is_str(fn, x):
                # to_int(str)：十进制解析，与 s.to_int() 同一条运行时
                self.uses_str_to_int = True
                d = fn.new_v()
                fn.emit("call", d, "__str_to_int", [x])
                return d
            if name in ("to_float", "to_f32") and self._is_str(fn, x):
                # v1.96：止血。旧实现把 str 的**指针**当数值转，得到地址量级的
                # 垃圾值（07-gaps §7.10），不报错也不崩——典型静默错。
                raise SyntaxError(
                    f"{name}(str) 不做十进制解析——旧实现会把字符串指针当数值转，"
                    "静默给出垃圾值（见 docs/07-gaps.md §7.10）。"
                    "请用 std/f64 的 f64_parse(s)")

            wf = self._float_of(fn, x)
            if name == "to_int":
                return self.conv_to(fn, x, wf, None)
            tw = "f64" if name == "to_float" else "f32"
            return self.conv_to(fn, x, wf, tw)
        if name == "cores":
            return ("imm", os.cpu_count() or 1)
        # ---- v1.5 系统级内建：让库层（ws/http/sse、缓冲池、解析器）用
        # Quelmara 自身写成零开销代码，而不是绕回 Python/Node 工具 ----
        if name == "now_ns" and name not in self.fns_ast:
            # now_ns() -> int：单调纳秒（微基准 / 延迟直方图）
            if len(e[2]) != 0:
                raise SyntaxError("now_ns() 不需要实参")
            self.uses_now = True
            d = fn.new_v()
            fn.emit("call", d, "__now_ns", [])
            return d
        if name == "wall_ms" and name not in self.fns_ast:
            # wall_ms() -> int：真实墙钟毫秒（Unix epoch）。与单调的 now_ns
            # 互补——wall 用于时间戳展示，单调用于测量。
            if len(e[2]) != 0:
                raise SyntaxError("wall_ms() 不需要实参")
            self.uses_wall = True
            d = fn.new_v()
            fn.emit("call", d, "__wall_ms", [])
            return d
        if name == "udp_open" and name not in self.fns_ast:
            # udp_open() -> fd：AF_INET + SOCK_DGRAM 数据报套接字。
            # Windows 首次调用走 WSAStartup（与 TCP 同款的 8B WSADATA）。
            if len(e[2]) != 0:
                raise SyntaxError("udp_open() 不需要实参")
            self.uses_udp = True
            d = fn.new_v()
            fn.emit("call", d, "__udp_open", [])
            return d
        if name in ("udp_bind", "udp_sendto", "udp_recvfrom", "udp_recvfrom_to") \
                and name not in self.fns_ast:
            # udp_bind(fd, port) -> 0/-1
            # udp_sendto(fd, ip_u32, port, data) -> 发送字节数/-1
            #   ip_u32 是**网络序**（std/net/udp.qma 的 udp_parse_ip 产出）
            # udp_recvfrom(fd, cap) -> str（单 datagram，源地址 v0 丢弃）
            # udp_recvfrom_to(fd, cap, ms) -> str（v3.04：带接收超时；
            #   超时返回空串而不是永久阻塞 —— DNS 查询没有它就会挂死）
            if self.arch != "x86_64":
                raise SyntaxError(f"{name} 目前只在 x86_64 后端实现")
            self.uses_udp = True
            need = {"udp_bind": 2, "udp_sendto": 4, "udp_recvfrom": 2,
                    "udp_recvfrom_to": 3}[name]
            if len(e[2]) != need:
                raise SyntaxError(f"{name} 需要 {need} 个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            d = fn.new_v()
            fn.emit("call", d, "__" + name, vals)
            if name in ("udp_recvfrom", "udp_recvfrom_to"):
                return self._mark_str(fn, d)
            return d
        if name == "mem_alloc" and name not in self.fns_ast:
            if len(e[2]) != 1:
                raise SyntaxError("mem_alloc(n) 需要一个实参")
            n = self.eval(e[2][0], fn, env)
            d = fn.new_v()
            fn.emit("call", d, "__alloc", [n])
            return d
        if name == "mem_free" and name not in self.fns_ast:
            if len(e[2]) != 2:
                raise SyntaxError("mem_free(ptr, n) 需要两个实参")
            p = self.eval(e[2][0], fn, env)
            n = self.eval(e[2][1], fn, env)
            self.uses_free = True
            d = fn.new_v()
            fn.emit("call", d, "__free", [p, n])
            return d
        if name == "mem_load_acq" and name not in self.fns_ast:
            # mem_load_acq(addr) -> int：acquire 读（v1.98）。
            # x86_64 的普通 mov 本身就是 acquire（TSO：读不会被提前），
            # 所以这里是零成本；AArch64 发 LDAR。用于"先读标志、再读数据"
            # 的发布-订阅读端。
            if len(e[2]) != 1:
                raise SyntaxError("mem_load_acq(addr) 需要一个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            d = fn.new_v()
            fn.emit("ldar", d, vals[0])
            return d
        if name == "mem_store_rel" and name not in self.fns_ast:
            # mem_store_rel(addr, v)：release 写（v1.98）。x86 普通 mov 已是
            # release（写不会被推后），AArch64 发 STLR。互斥锁的解锁走它：
            # 语义上要的是"之前的写对抢到锁的人可见"，不是全屏障。
            if len(e[2]) != 2:
                raise SyntaxError("mem_store_rel(addr, v) 需要两个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            fn.emit("stlr", vals[0], vals[1])
            return ("imm", 0)
        if name == "mem_xchg" and name not in self.fns_ast:
            # mem_xchg(addr, val) -> old：原子交换。
            # x86_64：`xchg [m], r`（隐含 LOCK）；AArch64：LDAXR/STLXR 重试（v1.98）。
            # 协议库的多 io 线程自旋锁靠它实现。
            if len(e[2]) != 2:
                raise SyntaxError("mem_xchg(addr, val) 需要两个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            d = fn.new_v()
            fn.emit("xchg", d, vals[0], vals[1])
            return d
        if name == "atomic_add" and name not in self.fns_ast:
            # atomic_add(addr, v) -> old：*addr += v，返回**旧值**（x86 lock xadd /
            # A64 LL-SC 循环）。无锁计数器 / MPMC 队列序号的地基。addr 须
            # 8 字节对齐（mem_alloc 产物或 static_word 槽）。
            if len(e[2]) != 2:
                raise SyntaxError("atomic_add(addr, v) 需要两个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            d = fn.new_v()
            fn.emit("atomic", "add", d, vals[0], vals[1])
            return d
        if name == "atomic_cas" and name not in self.fns_ast:
            # atomic_cas(addr, expect, new) -> old：旧值==expect 时写 new。
            # 返回旧值，调用方比较判断是否成功（cmpxchg 语义；A64 上是
            # LDAXR + CMP + STLXR，不相等直接返回、不写）。
            # 自旋锁：while atomic_cas(p, 0, 1) != 0 { spin_hint() }
            if len(e[2]) != 3:
                raise SyntaxError("atomic_cas(addr, expect, new) 需要三个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            d = fn.new_v()
            fn.emit("atomic", "cas", d, vals[0], vals[1], vals[2])
            return d
        if name == "atomic_fence" and name not in self.fns_ast:
            # atomic_fence()：全内存屏障（x86 mfence / A64 DMB ISH）。发布-订阅
            # 模式里"先写数据、再置 ready 标志"的顺序保证。
            fn.emit("mfence")
            return ("imm", 0)
        if name == "spin_hint" and name not in self.fns_ast:
            # spin_hint()：pause 指令。自旋循环里降低功耗、避免流水线清空。
            fn.emit("pause")
            return ("imm", 0)
        if name == "now_cycle" and name not in self.fns_ast:
            # now_cycle() -> int：x86 rdtsc / A64 CNTVCT_EL0（v1.98 双后端）。
            # 程序内自计时的地基——本机进程冷启动 ~426ms（Hyper-V/VBS），
            # 微基准必须排除它，这是 docs/06-status.md 的测量纪律。
            # 纯读（无副作用），不进 _EFF：调度器挪它只影响测量精度，
            # 不影响正确性；跨测量段归一化由调用方做（读两次取差）。
            d = fn.new_v()
            fn.emit("rdtsc", d)
            return d
        if name in ("mem_load8", "mem_load32", "mem_store8", "mem_load64", "mem_store64") \
                and name not in self.fns_ast:
            # mem_load8(p, i)        -> int   读第 i 个字节（0..255）
            # mem_store8(p, i, v)    -> 0     写第 i 个字节
            # mem_load64(p, w)       -> int   读第 w 个 8 字节字
            # mem_store64(p, w, v)   -> 0     写第 w 个 8 字节字
            want = 3 if "store" in name else 2
            if len(e[2]) != want:
                raise SyntaxError(f"{name} 需要 {want} 个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            if "store" in name:
                if name == "mem_store8":
                    fn.emit("store8", vals[0], vals[1], vals[2])
                else:
                    fn.emit("store", vals[0], vals[1], vals[2])
                return ("imm", 0)
            d = fn.new_v()
            if name == "mem_load8":
                fn.emit("load8", d, vals[0], vals[1])
            elif name == "mem_load32":
                # u32 语义：零扩展（crc32/校验和的直接消费形态）
                fn.emit("load32", d, vals[0], vals[1])
            else:
                fn.emit("load", d, vals[0], vals[1])
            return d
        if name == "mem_ptr" and name not in self.fns_ast:
            # mem_ptr(p, off) -> int：纯 int 指针偏移（v1.14）。
            # str 值是 int 形态，`s + n` 会被 str 拼接劫持（v1.14 起 str+int
            # 直接编译报错）——std 库内部的指针算术统一用这个原语，
            # 返回值**不带任何标记**（纯 int，+ - 等算术走整数路径）。
            if len(e[2]) != 2:
                raise SyntaxError("mem_ptr(p, off) 需要两个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            d = fn.new_v()
            fn.emit("bin", "add", d, vals[0], vals[1])
            return d
        if name == "cpu_sha" and name not in self.fns_ast:
            # cpu_sha() -> int：SHA-NI 特征位（CPUID leaf 7 EBX[29]，v1.15）。
            # 1 = 支持（走 SHA-NI 快路径），0 = 降级标量。探测一次缓存即可。
            if len(e[2]) != 0:
                raise SyntaxError("cpu_sha() 不接受实参")
            if self.arch not in ("x86_64",):
                raise SyntaxError("cpu_sha 目前只在 x86_64 后端实现")
            d = fn.new_v()
            fn.emit("cpuid_sha", d)
            return d
        if name == "cpu_aes" and name not in self.fns_ast:
            # cpu_aes() -> int：AES-NI 特征位（CPUID leaf 1 ECX[25]，v1.31）。
            # 1 = 支持（走 aesenc 快路径），0 = 降级 T-table 软件实现。
            if len(e[2]) != 0:
                raise SyntaxError("cpu_aes() 不接受实参")
            if self.arch not in ("x86_64",):
                raise SyntaxError("cpu_aes 目前只在 x86_64 后端实现")
            d = fn.new_v()
            fn.emit("cpuid_aes", d)
            return d
        if name in _XMM_BUILTINS and name not in self.fns_ast:
            # XMM / SHA-NI 操作族（v1.15）：操作数是 xmm 槽号（0-7 的编译期
            # 常量）——固定槽协议由库层维护（寄存器分配器不参与 xmm 管理）。
            #   xmm_load(dst_x, addr)  xmm_store(addr, src_x)
            #   sha_nexte/sha_rnds2/sha_msg1/sha_msg2(d_x, s_x)
            #   xmm_paddd/xmm_pxor(d_x, s_x)
            #   xmm_pshufd(d_x, s_x, imm8)  xmm_palignr(d_x, s_x, imm8)
            if self.arch != "x86_64":
                raise SyntaxError(f"{name} 目前只在 x86_64 后端实现")
            arity = {"xmm_pshufd": 3, "xmm_palignr": 3,
                     "aeskeygenassist": 3}.get(name, 2)
            if len(e[2]) != arity:
                raise SyntaxError(f"{name} 需要 {arity} 个实参")
            if name == "cpu_sha":
                d = fn.new_v()
                fn.emit("cpuid_sha", d)
                return d
            # xmm 槽在 IR 里用**负数编码** -(x+1)：vreg 是非负 int，
            # 负数天然不冲突（mentions/subst 过滤负 int 即"非 vreg"）
            def xn(x):
                return -(int(x) + 1)

            # ⚠ 槽参数的位置按指令而异：xmm_load 的槽在**第 0 位**（第 1 位
            # 是地址 vreg），xmm_store 的槽在**第 1 位**（第 0 位是地址）。
            # v1.15 那版把前两个实参都当槽校验，只要地址是变量就
            # `v[0]` 取下标炸掉（vreg 是裸 int，不是 tuple）——因为当时
            # 没有任何 .qma 真的调用过 xmm_*，这个 bug 一直没暴露（v1.31 修）。
            def slot_of(a):
                v = self.eval(a, fn, env)
                if not isinstance(v, tuple) or v[0] != "imm" or not (0 <= v[1] <= 7):
                    raise SyntaxError(
                        f"{name} 的 xmm 槽参数必须是 0-7 的编译期常量")
                return v[1]

            if name == "xmm_load":
                x = slot_of(e[2][0])
                av = self.eval(e[2][1], fn, env)
                fn.emit("xmm_ld", xn(x), av)
                return ("imm", 0)
            if name == "xmm_store":
                av = self.eval(e[2][0], fn, env)
                x = slot_of(e[2][1])
                fn.emit("xmm_st", av, xn(x))
                return ("imm", 0)
            vals = [slot_of(e[2][0]), slot_of(e[2][1])]
            if arity == 2:
                fn.emit(name, xn(vals[0]), xn(vals[1]))
            else:
                vi = self.eval(e[2][2], fn, env)
                if vi[0] != "imm":
                    raise SyntaxError(f"{name} 的立即数必须是编译期常量")
                fn.emit(name, xn(vals[0]), xn(vals[1]), vi[1] & 0xFF)
            return ("imm", 0)
        if name == "cpu_pclmul" and name not in self.fns_ast:
            # cpu_pclmul() -> int：PCLMULQDQ 特征位（CPUID.1:ECX[1]，v1.33）。
            if len(e[2]) != 0:
                raise SyntaxError("cpu_pclmul() 不接受实参")
            if self.arch not in ("x86_64",):
                raise SyntaxError("cpu_pclmul 目前只在 x86_64 后端实现")
            d = fn.new_v()
            fn.emit("cpuid_pclmul", d)
            return d
        if name in _SSE_BUILTINS and name not in self.fns_ast:
            # SSE 族（v1.33）：与 AES 族同一套"xmm 槽 = 编译期常量 0-7"协议。
            #   双槽：xmm_mov / pand / por / psphufb
            #   双槽+imm：pclmulqdq(d, s, imm8)
            #   单槽+imm：psrlw/psllw/psrlq/psllq/pslldq/psrldq(d, imm8)
            if self.arch != "x86_64":
                raise SyntaxError(f"{name} 目前只在 x86_64 后端实现")

            def slot_of(a):
                v = self.eval(a, fn, env)
                if not isinstance(v, tuple) or v[0] != "imm" or not (0 <= v[1] <= 7):
                    raise SyntaxError(f"{name} 的 xmm 槽参数必须是 0-7 的编译期常量")
                return -(int(v[1]) + 1)          # 负数编码 -(x+1)

            def imm_of(a):
                v = self.eval(a, fn, env)
                if not isinstance(v, tuple) or v[0] != "imm":
                    raise SyntaxError(f"{name} 的立即数必须是编译期常量")
                return v[1] & 0xFF

            if name in ("psrlw", "psllw", "psrlq", "psllq", "pslldq", "psrldq"):
                if len(e[2]) != 2:
                    raise SyntaxError(f"{name}(slot, imm8) 需要两个实参")
                x = slot_of(e[2][0])
                fn.emit(name + "_i", x, imm_of(e[2][1]))
                return ("imm", 0)
            if name == "pclmulqdq":
                if len(e[2]) != 3:
                    raise SyntaxError("pclmulqdq(d, s, imm8) 需要三个实参")
                d = slot_of(e[2][0])
                b = slot_of(e[2][1])
                fn.emit("pclmul_x", d, b, imm_of(e[2][2]))
                return ("imm", 0)
            if len(e[2]) != 2:
                raise SyntaxError(f"{name}(d, s) 需要两个实参")
            d = slot_of(e[2][0])
            b = slot_of(e[2][1])
            fn.emit({"xmm_mov": "xmm_mov", "pand": "pand_x",
                     "por": "por_x", "pshufb": "pshufb_x"}[name], d, b)
            return ("imm", 0)
        if name == "mem_copy" and name not in self.fns_ast:
            if len(e[2]) != 3:
                raise SyntaxError("mem_copy(dst, src, n) 需要三个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            fn.emit("call", None, "__memcpy", vals)
            return ("imm", 0)
        if name == "mem_zero" and name not in self.fns_ast:
            if len(e[2]) != 2:
                raise SyntaxError("mem_zero(p, n) 需要两个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            self.uses_memset = True
            fn.emit("call", None, "__memset", [vals[0], ("imm", 0), vals[1]])
            return ("imm", 0)
        if name == "mem_cmp" and name not in self.fns_ast:
            if len(e[2]) != 3:
                raise SyntaxError("mem_cmp(a, b, n) 需要三个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            self.uses_memcmp = True
            d = fn.new_v()
            fn.emit("call", d, "__memcmp", vals)
            return d
        if name == "mem_chr" and name not in self.fns_ast:
            # mem_chr(p, n, byte) -> int：在 p 起 n 字节内找第一个等于 byte 的
            # 字节，返回下标；找不到 -1（v1.29）。
            # 这是"找字符内建"——str_find / str_split / str_lines / HTTP 头
            # 解析的共同热点。实现见运行时 __memchr（8 字节 SWAR）。
            if len(e[2]) != 3:
                raise SyntaxError("mem_chr(p, n, byte) 需要三个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            self.uses_memchr = True
            d = fn.new_v()
            fn.emit("call", d, "__memchr", vals)
            return d
        if name == "mem_diff" and name not in self.fns_ast:
            # mem_diff(p1, p2, n) -> int：两段 n 字节里**第一个不同字节的下标**，
            # 全等返回 n（v1.30）。等价于"公共前缀长度"。
            # 用途：LZ77 匹配长度（gzip deflate 的内层热点）、逐字节 diff。
            # 实现见运行时 __memdiff（8 字节字比较）。
            if len(e[2]) != 3:
                raise SyntaxError("mem_diff(p1, p2, n) 需要三个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            self.uses_memdiff = True
            d = fn.new_v()
            fn.emit("call", d, "__memdiff", vals)
            return d
        if name == "str_ptr" and name not in self.fns_ast:
            # str_ptr(s) -> int：取 str 的**数据指针**（v3.07）。
            #
            # Quelmara 的 str 是长度前缀 ABI：`[len:8][bytes...]`，而 str 变量
            # 的值**本身就是数据指针**（指向第一个字节）——`__str_len` 的实现
            # 就是 `load(p-8)`，正好印证这一点。
            #
            # 所以这个内建不分配、不复制、零成本：直接返回操作数。
            # 用途：把 str 喂给 `tcp_send_n(fd, ptr, n)` 这类零拷贝内建，
            # 避免 `substr` 切片造成的 O(n²) 复制。
            #
            # 边界：返回的指针**只在 s 存活期间有效**；调用方不能保存它跨
            # 作用域使用（语言没有生命周期检查，这是"裸指针来源"的一类，
            # 与 mem_str 裸指针同口径）。
            if len(e[2]) != 1:
                raise SyntaxError("str_ptr(s) 需要且只需要一个 str 实参")
            v = self.eval(e[2][0], fn, env)
            # 关键：操作数 vreg 在 fn.strv 里（print/len 会按 str 处理）。
            # 本内建要的是**同一个值当 int 用**，但**不能把原 vreg 的 str 标记
            # 摘掉** —— 那会让 `let p = str_ptr(s)` 之后 `len(s)` 也报
            # "只支持定长数组/切片/map/str"（v3.07 踩过）。
            #
            # 正确做法：拷到一个**新 vreg**，只给新 vreg 去掉 str 标记。
            # 拷一条 mov 的成本可以忽略（且会被复制传播消掉）。
            if isinstance(v, int):
                d = fn.new_v()
                fn.emit("mov", d, v)
                if hasattr(fn, "strv"):
                    fn.strv.discard(d)      # 新 vreg 不是 str
                return d
            return v
        if name == "mem_str" and name not in self.fns_ast:
            # mem_str(p, n) -> str：拷 n 字节并补 NUL（缓冲区 -> 不可变串）
            if len(e[2]) != 2:
                raise SyntaxError("mem_str(p, n) 需要两个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            self.uses_mem_to_str = True
            d = fn.new_v()
            fn.emit("call", d, "__mem_to_str", vals)
            return self._mark_str(fn, d)
        if name == "cstr" and name not in self.fns_ast:
            # cstr(s) -> int：str -> NUL 结尾的 C 字符串指针（v1.87）。
            # 语义：新分配一块 [n][bytes][NUL]（与 str_alloc 同一运行时
            # __str_from_mem），把 s 的 n 字节拷进去，返回**数据指针**。
            # 为什么必须显式调用：Quelmara 的 str 是长度前缀 ABI（[len][bytes]），
            # 末尾没有 NUL——直接把它当 char* 传给 Win32 会让 API 读越界。
            if len(e[2]) != 1:
                raise SyntaxError("cstr(s) 需要且只需要一个 str 实参")
            if self.arch != "x86_64":
                raise SyntaxError("cstr 目前只在 x86_64 后端实现")
            self.uses_strmem = True
            sv = self.eval(e[2][0], fn, env)
            n = self.str_len(fn, sv)
            d = fn.new_v()
            fn.emit("call", d, "__str_from_mem", [sv, n])
            # 返回**纯 int 指针**（不打 str 标记）：FFI 形参是 int，
            # 打上 str 标记反而会被 lower_ffi 当成"传了长度前缀串"拒掉。
            # 布局仍是合法 str（[n][bytes][NUL]），要读回来用 cstr_read。
            return d
        if name == "cstr_read" and name not in self.fns_ast:
            # cstr_read(p) -> str：C 字符串指针 -> str（v1.87，找首个 NUL）。
            # 无上界保护：p 必须真的指向 NUL 结尾的缓冲区（Win32 返回值满足）。
            if len(e[2]) != 1:
                raise SyntaxError("cstr_read(p) 需要且只需要一个指针实参")
            if self.arch != "x86_64":
                raise SyntaxError("cstr_read 目前只在 x86_64 后端实现")
            self.uses_strmem = True
            p = self.eval(e[2][0], fn, env)
            k = fn.new_v()
            fn.emit("mov", k, ("imm", 0))
            l_scan = fn.label("cstrs")
            l_done = fn.label("cstrd")
            fn.emit("label", l_scan)
            ch = fn.new_v()
            fn.emit("load8", ch, p, k)          # 字节偏移寻址（scale 0）
            fn.emit("jz", ch, l_done)
            fn.emit("bin", "add", k, k, ("imm", 1))
            fn.emit("jmp", l_scan)
            fn.emit("label", l_done)
            d = fn.new_v()
            fn.emit("call", d, "__str_from_mem", [p, k])
            return self._mark_str(fn, d)
        if name == "thread_yield" and name not in self.fns_ast:
            # thread_yield()：让出当前时间片（v1.98）。Windows 走
            # kernel32.SwitchToThread，Linux 走 sched_yield（x86 24 / A64 124）。
            # 与 spin_hint 的分工：spin_hint 是"再等一会儿"（ns 级、不切线程），
            # thread_yield 是"让别的线程先跑"（µs 级、会切上下文）。
            # 退避等待（std/sync 的 wg_wait、mutex_lock 长等待）靠它把 CPU 还回去。
            if len(e[2]) != 0:
                raise SyntaxError("thread_yield() 不需要实参")
            if self.platform == "windows":
                fn.emit("winapi", None, "SwitchToThread", [])
            else:
                fn.emit("syscall", None, self.sc["yield"],
                        [("imm", 0), ("imm", 0), ("imm", 0),
                         ("imm", 0), ("imm", 0), ("imm", 0)])
            return ("imm", 0)
        if name == "cpu_ns" and name not in self.fns_ast:
            # cpu_ns() -> int：**进程**累计 CPU 时间纳秒（v1.98）。与 now_ns
            # （单调墙钟）配对使用：wall 远大于 cpu 说明在睡/等，wall≈cpu
            # 说明在烧核——这是"自旋 vs 退避"唯一可测的判据。
            # Windows：GetProcessTimes（内核+用户态，100ns 单位）；
            # Linux：clock_gettime(CLOCK_PROCESS_CPUTIME_ID=2)。
            if len(e[2]) != 0:
                raise SyntaxError("cpu_ns() 不需要实参")
            self.uses_cpu = True
            d = fn.new_v()
            fn.emit("call", d, "__cpu_ns", [])
            return d
        if name == "sleep_ms" and name not in self.fns_ast:
            # sleep_ms(ms)：线程挂起指定毫秒（v1.16）。
            # Windows：kernel32.Sleep(ms)；Linux：nanosleep(timespec{ms/1000,
            # (ms%1000)*1e6}, 0)，timespec 用帧槽 2 字。
            if len(e[2]) != 1:
                raise SyntaxError("sleep_ms(ms) 需要一个实参")
            ms = self.eval(e[2][0], fn, env)
            if self.platform == "windows":
                fn.emit("winapi", None, "Sleep", [ms])
            else:
                ts = fn.new_struct_slot(2)
                ta = fn.new_v()
                fn.emit("frameaddr", ta, ts)
                sec = fn.new_v()
                fn.emit("bin", "div", sec, ms, ("imm", 1000))
                rem = fn.new_v()
                fn.emit("bin", "mod", rem, ms, ("imm", 1000))
                nsl = fn.new_v()
                fn.emit("bin", "mul", nsl, rem, ("imm", 1000000))
                fn.emit("store", ta, ("imm", 0), sec)
                fn.emit("store", ta, ("imm", 1), nsl)
                fn.emit("syscall", None, self.sc["nanosleep"],
                        [ta, ("imm", 0), ("imm", 0), ("imm", 0), ("imm", 0), ("imm", 0)])
            return ("imm", 0)
        if name == "file_exists" and name not in self.fns_ast:
            # file_exists(path) -> int：0/1（v1.16）。
            # Windows：GetFileAttributesA != INVALID(0xFFFFFFFF)；Linux：access(path, F_OK)
            if len(e[2]) != 1:
                raise SyntaxError("file_exists(path) 需要一个实参")
            pa = self.eval(e[2][0], fn, env)
            if self.platform == "windows":
                attr = fn.new_v()
                fn.emit("winapi", attr, "GetFileAttributesA", [pa])
                # winapi 返回 32 位值（RAX 高 32 为 0）——先符号扩展到 64 位
                # 再与 -1 比较（0xFFFFFFFF 符号扩展后才是 -1）
                sx = fn.new_v()
                fn.emit("bin", "shl", sx, attr, ("imm", 32))
                fn.emit("bin", "sar", sx, sx, ("imm", 32))
                d = fn.new_v()
                fn.emit("cmpset", "ne", d, sx, ("imm", -1))
                return d
            fn.emit("syscall", d, self.sc["access"],
                    [("imm", -100), pa, ("imm", 0), ("imm", 0), ("imm", 0), ("imm", 0)])
            z = fn.new_v()
            fn.emit("cmpset", "e", z, d, ("imm", 0))
            return z
        if name in ("file_size", "fs_mkdir", "fs_remove") and name not in self.fns_ast:
            # 文件系统最小集（v1.16）：
            #   file_size(path) -> 字节数（失败 -1）
            #   fs_mkdir(path) -> 0 成功 / -1 失败（已存在也算失败，与 POSIX 同）
            #   fs_remove(path) -> 0 成功 / -1 失败（仅文件；目录用 fs_rmdir——未做）
            # Windows：CreateFileA+GetFileSize+CloseHandle / CreateDirectoryA / DeleteFileA
            # Linux：openat+lseek(SEEK_END)+close / mkdir(0o755) / unlink
            if len(e[2]) != 1:
                raise SyntaxError(f"{name}(path) 需要一个实参")
            pa = self.eval(e[2][0], fn, env)
            if name == "fs_mkdir":
                if self.platform == "windows":
                    d = fn.new_v()
                    fn.emit("winapi", d, "CreateDirectoryA", [pa, ("imm", 0)])
                    # 非 0 = 成功 → 返回 0；0 = 失败 → 返回 -1
                    ok = fn.new_v()
                    fn.emit("cmpset", "ne", ok, d, ("imm", 0))
                    r = fn.new_v()
                    fn.emit("bin", "sub", r, ok, ("imm", 1))
                    return r
                fn.emit("syscall", d, self.sc["mkdir"],
                        [pa, ("imm", 493), ("imm", 0), ("imm", 0), ("imm", 0), ("imm", 0)])
                # POSIX：0 成功 / -1 失败——非 0 的 -1 保留、0 保留
                z = fn.new_v()
                fn.emit("cmpset", "e", z, d, ("imm", 0))
                r = fn.new_v()
                fn.emit("bin", "sub", r, z, ("imm", 1))
                return r
            if name == "fs_remove":
                if self.platform == "windows":
                    d = fn.new_v()
                    fn.emit("winapi", d, "DeleteFileA", [pa])
                    ok = fn.new_v()
                    fn.emit("cmpset", "ne", ok, d, ("imm", 0))
                    r = fn.new_v()
                    fn.emit("bin", "sub", r, ok, ("imm", 1))
                    return r
                fn.emit("syscall", d, self.sc["unlink"],
                        [pa, ("imm", 0), ("imm", 0), ("imm", 0), ("imm", 0), ("imm", 0)])
                z = fn.new_v()
                fn.emit("cmpset", "e", z, d, ("imm", 0))
                r = fn.new_v()
                fn.emit("bin", "sub", r, z, ("imm", 1))
                return r
            # file_size
            if self.platform == "windows":
                h = fn.new_v()
                fn.emit("winapi", h, "CreateFileA",
                        [pa, ("imm", -2147483648), ("imm", 0), ("imm", 0),
                         ("imm", 3), ("imm", 0), ("imm", 0)])
                bad = fn.new_v()
                fn.emit("cmpset", "e", bad, h, ("imm", -1))
                sz = fn.new_v()
                l_fail = fn.label("fsf")
                l_end = fn.label("fsd")
                fn.emit("jnz", bad, l_fail)
                fn.emit("winapi", sz, "GetFileSize", [h, ("imm", 0)])
                fn.emit("winapi", None, "CloseHandle", [h])
                fn.emit("jmp", l_end)
                fn.emit("label", l_fail)
                fn.emit("mov", sz, ("imm", -1))
                fn.emit("label", l_end)
                return sz
            fd = fn.new_v()
            fn.emit("syscall", fd, self.sc["openat"],
                    [("imm", -100), pa, ("imm", 0), ("imm", 0), ("imm", 0), ("imm", 0)])
            neg = fn.new_v()
            fn.emit("bin", "sub", neg, ("imm", 0), fd)
            pos = fn.new_v()
            fn.emit("cmpset", "g", pos, fd, ("imm", 0))   # fd > 0 才继续
            l_ok = fn.label("fso")
            fn.emit("jnz", pos, l_ok)
            sz2 = fn.new_v()
            fn.emit("mov", sz2, ("imm", -1))
            l_end = fn.label("fse2")
            fn.emit("jmp", l_end)
            fn.emit("label", l_ok)
            cur = fn.new_v()
            fn.emit("syscall", cur, self.sc["lseek"],
                    [fd, ("imm", 0), ("imm", 2), ("imm", 0), ("imm", 0), ("imm", 0)])
            fn.emit("syscall", None, self.sc["close"], [fd])
            fn.emit("label", l_end)
            return cur
        if name == "read_asset" and name not in self.fns_ast:
            # read_asset(name) -> str：从 [src].asset 基准路径读资源文件
            # （v1.17）。asset 根编译期嵌入为 global 字符串，运行期与
            # name 拼接后走 read_text——资源路径不散落代码里。
            if len(e[2]) != 1:
                raise SyntaxError("read_asset(name) 需要一个实参")
            if not self.asset_root:
                raise SyntaxError(
                    "read_asset 需要项目 Quelmara.toml 的 [src] asset 配置")
            root = self.asset_root.replace("\\", "/").rstrip("/")
            # 语言层布局（[len][bytes][NUL]）——read_asset 的路径要参与
            # str 拼接，必须走 intern_str_lit（intern_str 是给 winapi 的
            # 无 len 头 C 串，用它 concat 会把路径字节当 len 巨量分配）
            gid = self.intern_str_lit(root + "/")
            # global 字符串的 ga 指向 [len][bytes] 的 **len 头**——
            # 传给 str 函数前必须 +8 变成数据指针（str 值约定）；
            # 直接 ("ga", gid) 传参会让 concat 读到垃圾 len（v1.17 修）
            rp = fn.new_v()
            fn.emit("movaddr", rp, gid)
            fn.emit("bin", "add", rp, rp, ("imm", 8))
            na = self.eval(e[2][0], fn, env)
            full = fn.new_v()
            fn.emit("call", full, "__str_concat", [rp, na])
            self.uses_io = True
            if os.environ.get("QLM_ASSET_DEBUG"):
                return full        # 调试：只返回拼接后的完整路径（跳过读取）
            d = fn.new_v()
            fn.emit("call", d, "__read_text", [full])
            return self._mark_str(fn, d)
        if name == "read_text" and name not in self.fns_ast:
            # read_text(path) -> str：整文件读入（NUL 结尾）。失败 fail-fast。
            if len(e[2]) != 1:
                raise SyntaxError("read_text(path) 需要一个实参")
            self.uses_io = True
            pa = self.eval(e[2][0], fn, env)
            d = fn.new_v()
            fn.emit("call", d, "__read_text", [pa])
            return self._mark_str(fn, d)
        if name == "write_text" and name not in self.fns_ast:
            # write_text(path, content) -> int：整文件写入（覆盖），返回写入
            # 字节数。打开/写入失败一律 fail-fast。
            if len(e[2]) != 2:
                raise SyntaxError("write_text(path, content) 需要两个实参")
            self.uses_io = True
            pa = self.eval(e[2][0], fn, env)
            ca = self.eval(e[2][1], fn, env)
            d = fn.new_v()
            fn.emit("call", d, "__write_text", [pa, ca])
            return d
        if name == "str_from_bytes" and name not in self.fns_ast:
            # str_from_bytes(v: vec[int]) -> str：字节缓冲 O(n) 成串（v1.3，
            # 自举解析器实测 str+ 累积 O(n^2) 短板的对症内建）。
            if len(e[2]) != 1:
                raise SyntaxError("str_from_bytes(v) 需要一个实参")
            self.uses_vec = True
            self.uses_sfb = True
            va = self.eval(e[2][0], fn, env)
            d = fn.new_v()
            fn.emit("call", d, "__str_from_bytes", [va])
            return self._mark_str(fn, d)
        if name == "str_alloc" and name not in self.fns_ast:
            # str_alloc(n) -> str：分配一个长度为 n 的可写空串（v1.14）。
            # 返回**数据指针**（str 值约定），len 头已写 0，NUL 已置；
            # 配合 mem_copy/mem_store8 批量填充——join/split/gzip 等
            # 批量构造场景替代逐字节 vec push（O(n) 且无每字节 call）。
            if len(e[2]) != 1:
                raise SyntaxError("str_alloc(n) 需要一个实参")
            if self.arch != "x86_64":
                raise SyntaxError("str_alloc 目前只在 x86_64 后端实现")
            self.uses_strmem = True
            na = self.eval(e[2][0], fn, env)
            d = fn.new_v()
            fn.emit("call", d, "__str_alloc", [na])
            return self._mark_str(fn, d)
        if name == "str_from_mem" and name not in self.fns_ast:
            # str_from_mem(data, n) -> str：从内存区间 O(n) 构造 str（v1.14）。
            # data 是字节数据地址（str 值本身、mem 指针算术均可）；
            # [n][bytes][NUL] 布局，一次分配一次拷贝——split/join 的
            # 每段构造原语。语义边界：区间与目标不重叠（mem_copy 同约定）。
            if len(e[2]) != 2:
                raise SyntaxError("str_from_mem(data, n) 需要两个实参")
            if self.arch != "x86_64":
                raise SyntaxError("str_from_mem 目前只在 x86_64 后端实现")
            self.uses_strmem = True
            da = self.eval(e[2][0], fn, env)
            na = self.eval(e[2][1], fn, env)
            d = fn.new_v()
            fn.emit("call", d, "__str_from_mem", [da, na])
            return self._mark_str(fn, d)
        if name in ("tcp_listen", "tcp_accept", "tcp_send", "tcp_recv",
                    "tcp_close") and name not in self.fns_ast:
            # 原生 socket 第一格（v1.3，过程式阻塞模型）：
            #   tcp_listen(port) -> fd     绑定 0.0.0.0:port 并监听
            #   tcp_accept(fd) -> conn     阻塞等待连接
            #   tcp_send(fd, str) -> n     发送，返回字节数
            #   tcp_recv(fd, cap) -> str   接收（对端关闭返回空串）
            #   tcp_close(fd) -> 0
            # 失败（初始化/创建/绑定/监听/发送）一律 fail-fast。
            # SPEC 的 net.TcpServer reactor（回调结构体）仍是目标模型，
            # 这一组是它的地基：同一条 QuIR，Windows 走 ws2_32，
            # Linux 走 raw syscall。
            self.uses_net = True
            nargs = {"tcp_listen": 1, "tcp_accept": 1, "tcp_send": 2,
                     "tcp_recv": 2, "tcp_close": 1}[name]
            if len(e[2]) != nargs:
                raise SyntaxError(f"{name} 需要 {nargs} 个实参")
            as_ = [self.eval(a, fn, env) for a in e[2]]
            d = fn.new_v()
            fn.emit("call", d, "__" + name, as_)
            if name == "tcp_recv":
                return self._mark_str(fn, d)
            return d
        if name == "tcp_connect" and name not in self.fns_ast:
            # 客户端连接：tcp_connect(host, port) -> fd。
            # Windows 走 getaddrinfo（系统 DNS + hosts），v2.07 起 family 放宽
            # 到 AF_UNSPEC，IPv6 字面量与 AAAA 记录直接可用，并按 ai_next
            # 逐个尝试（"localhost" 先返回 ::1 时 v4-only 服务端仍能连上）。
            # POSIX（v2.92）走 raw syscall：只支持 **IPv4 点分字面量** 直连，
            # 域名 fail-fast（Linux resolver 要 dlopen nsswitch 插件，抄一遍
            # 等于把 glibc 的 resolver 内联进来，与本后端定位冲突）。
            if len(e[2]) != 2:
                raise SyntaxError("tcp_connect(host, port) 需要两个实参")
            self.uses_net = True
            # 运行时按 ai_addrlen 整段拷 sockaddr（v4 16B / v6 28B）
            self.uses_memcpy = True
            vals = [self.eval(a, fn, env) for a in e[2]]
            d = fn.new_v()
            fn.emit("call", d, "__tcp_connect", vals)
            return d
        if name == "tcp_listen6" and name not in self.fns_ast:
            # IPv6 监听（v2.07）：tcp_listen6(port) -> fd。
            # AF_INET6 + sockaddr_in6（28B）+ IPV6_V6ONLY=0 —— 同一个 socket
            # 同时接 IPv6 与 IPv4（映射成 ::ffff:a.b.c.d）连接。
            # 仅 Windows PE（ELF 后端无动态链接器，与 tcp_connect 同边界）。
            if self.platform != "windows":
                raise SyntaxError(
                    "tcp_listen6() 目前只在 Windows PE 后端实现")
            if len(e[2]) != 1:
                raise SyntaxError("tcp_listen6(port) 需要一个实参")
            self.uses_net = True
            pv = self.eval(e[2][0], fn, env)
            d = fn.new_v()
            fn.emit("call", d, "__tcp_listen6", [pv])
            return d
        if name == "tcp_peer_raw" and name not in self.fns_ast:
            # 对端地址原始字节（v2.07）：tcp_peer_raw(fd) -> str（20 字节）。
            # 布局：[0..1] 端口网络序 | [2] family（2=v4 / 23=v6 / 0=未知）
            #       [3] 保留 0 | [4..19] 地址网络序（v4 占前 4 字节，其余 0）
            # 文本化交给 std/net/addr.qma（IPv6 压缩格式要 8 组十六进制 + "::"，
            # 放库层比放发射器好读，也不占运行时体积）。
            if self.platform != "windows":
                raise SyntaxError(
                    "tcp_peer_raw() 目前只在 Windows PE 后端实现")
            if len(e[2]) != 1:
                raise SyntaxError("tcp_peer_raw(fd) 需要一个实参")
            self.uses_net = True
            self.uses_strmem = True          # __str_from_mem
            self.uses_peer = True            # __tcp_peer_raw 本体
            fv = self.eval(e[2][0], fn, env)
            d = fn.new_v()
            fn.emit("call", d, "__tcp_peer_raw", [fv])
            return self._mark_str(fn, d)
        if name in ("tcp_send_n", "tcp_recv_n") and name not in self.fns_ast:
            # 零拷贝变体（v1.5）：直接给指针 + 长度，不构造 str、不扫 strlen。
            #   tcp_send_n(fd, ptr, n) -> 发送字节数
            #   tcp_recv_n(fd, ptr, cap) -> 收到字节数（0 = 对端关闭）
            # 协议库（ws/http/sse）的缓冲池靠这两个内建做零拷贝收发。
            self.uses_net = True
            want = 3 if name == "tcp_send_n" else 3
            if len(e[2]) != want:
                raise SyntaxError(f"{name} 需要 {want} 个实参")
            vals = [self.eval(a, fn, env) for a in e[2]]
            d = fn.new_v()
            fn.emit("call", d, "__" + name, vals)
            return d
        if name == "static_word" and name not in self.fns_ast:
            # static_word(i) -> int：第 i 个进程级 8 字节静态字的地址（共 32 个）。
            # 语言没有模块级可变全局，而协议库（ws/http/sse）必须把回调与
            # 连接表放在进程级位置才能被 reactor 的回调函数读到 —— 这是那条
            # 通道的最小实现：返回地址，库层用 mem_load64/mem_store64 读写。
            if len(e[2]) != 1:
                raise SyntaxError("static_word(i) 需要一个实参")
            iv = self.eval(e[2][0], fn, env)
            off = fn.new_v()
            fn.emit("bin", "shl", off, iv, ("imm", 3))
            d = fn.new_v()
            fn.emit("bin", "add", d, ("ga", self.static_gid()), off)
            return d
        if name == "net_serve" and name not in self.fns_ast:
            # v2.12：reactor 已整体迁到 std/net/reactor.qma（Quelmara 源码）。
            # 内建只留一条有信息量的迁移诊断——直接报"未定义函数 net_serve"
            # 会让老代码看不出发生了什么。
            raise SyntaxError(
                "net_serve 在 v2.12 迁到标准库了：import std.net.reactor 后调用 "
                "net_serve(...) 或 serve(...)（见 docs/05-toolchain.md §1.9）")
        if name == "thread_start" and name not in self.fns_ast:
            # thread_start(fn, arg) -> int：显式 OS 线程（v2.12）。
            # 与 spawn 的唯一区别：**不受 Quelmara.toml multicore=false 降级**。
            # reactor 的 GQCS 循环必须真的跑在另一个线程上——单核配置下 spawn
            # 会内联执行，主线程就永远卡在完成端口里、accept 再也不运行。
            # arg 按 int 传（句柄/指针），不做类型转换（与被调方签名无关）。
            if len(e[2]) != 2:
                raise SyntaxError("thread_start(fn, arg) 需要两个实参")
            if self.arch != "x86_64":
                raise SyntaxError("thread_start 目前仅支持 x86_64 后端")
            fv = self.eval(e[2][0], fn, env)
            av = self.eval(e[2][1], fn, env)
            self.uses_threads = True          # 多线程 -> __alloc 加锁
            blk = fn.new_v()
            fn.emit("call", blk, "__alloc", [("imm", 24)])
            fn.emit("store", blk, ("imm", 0), ("imm", 0))    # 返回值槽
            fn.emit("store", blk, ("imm", 1), av)            # 线程实参
            fn.emit("store", blk, ("imm", 2), fv)            # 目标代码地址
            wname = f"__thread_{self.spawn_id}"
            self.spawn_id += 1
            w = Fn(wname)
            w.no_inline = True                # 跑在另一个栈上
            wp = w.new_v()
            w.emit("args", [wp])
            fp = w.new_v()
            w.emit("load", fp, wp, ("imm", 2))
            ap = w.new_v()
            w.emit("load", ap, wp, ("imm", 1))
            rv = w.new_v()
            w.emit("callr", rv, fp, [ap])
            w.emit("store", wp, ("imm", 0), rv)
            w.emit("ret", ("imm", 0))
            self.out.append(w)
            if self.platform == "windows":
                wrap = Fn(wname + "__entry")
                wrap.win_thread = True        # 序言/尾声保存 RDI/RSI（Win64）
                xp = wrap.new_v()
                wrap.emit("winargs", [xp])
                wrap.emit("call", None, wname, [xp])
                wrap.emit("ret", ("imm", 0))
                self.out.append(wrap)
                tid = fn.new_v()
                fn.emit("winapi", tid, "CreateThread",
                        [("imm", 0), ("imm", 0), ("fnaddr", wrap.name),
                         blk, ("imm", 0), ("imm", 0)])
            else:
                st = fn.new_v()
                fn.emit("syscall", st, self.sc["mmap"],
                        [("imm", 0), ("imm", STACK_SZ), ("imm", PROT_RW),
                         ("imm", MAP_PRIVATE_ANON), ("imm", -1), ("imm", 0)])
                top = fn.new_v()
                fn.emit("bin", "add", top, st, ("imm", STACK_SZ - 256))
                fn.emit("store", st, ("imm", (STACK_SZ - 264) // 8), blk)
                pid = fn.new_v()
                fn.emit("syscall", pid, self.sc["clone"],
                        [("imm", CLONE_FLAGS), top, ("imm", 0),
                         ("imm", 0), ("imm", 0), ("imm", 0)])
                l_child, l_after = fn.label("thchild"), fn.label("thafter")
                fn.emit("jz", pid, l_child)
                fn.emit("jmp", l_after)
                fn.emit("label", l_child)
                fn.emit("spawn_child", wname)
                fn.emit("label", l_after)
                tid = pid
            return tid
        if name == "net_config" and name not in self.fns_ast:
            # net_config(key) -> int：编译期读 Quelmara.toml 的有效值（v2.12）。
            # reactor 搬进 std 之后仍要以根配置为唯一开关，所以把这些上限
            # 做成编译期常量内建，而不是让库层自己写死数字。
            #   0 = max_conns   1 = recv_buffer   2 = io_threads（已解析）
            #   3 = tcp_nodelay（0/1）
            if len(e[2]) != 1:
                raise SyntaxError("net_config(key) 需要一个实参")
            k = self.eval(e[2][0], fn, env)
            if not (isinstance(k, tuple) and k[0] == "imm"):
                raise SyntaxError("net_config 的 key 必须是编译期常量（0-3）")
            ncfg = self.cfg.get("net", {}) or {}
            key = int(k[1])
            if key == 0:
                return ("imm", int(ncfg.get("max_conns", 1000000) or 1000000))
            if key == 1:
                return ("imm", int(ncfg.get("recv_buffer", 4096) or 4096))
            if key == 2:
                t = int(ncfg.get("io_threads", 0) or 0)
                if t <= 0:
                    t = int(self.cfg["core"].get("threads", 0) or 0)
                if t <= 0:
                    t = os.cpu_count() or 1
                return ("imm", t)
            if key == 3:
                return ("imm", 1 if ncfg.get("tcp_nodelay", True) else 0)
            raise SyntaxError("net_config(key) 的 key 只有 0-3")

        if name == "substr" and name not in self.fns_ast:
            # substr(s, lo, n) -> str：越界 fail-fast（与下标同策略）
            if len(e[2]) != 3:
                raise SyntaxError("substr(s, lo, n) 需要三个实参")
            self.uses_substr = True
            src = self.eval(e[2][0], fn, env)
            lo = self.eval(e[2][1], fn, env)
            cnt = self.eval(e[2][2], fn, env)
            ln = self.str_len(fn, src)
            l_fail = fn.label("ssfail")
            b = fn.new_v()
            f_neg = lambda v: None
            fn.emit("cmpset", "l", b, lo, ("imm", 0))
            fn.emit("jnz", b, l_fail)
            fn.emit("cmpset", "l", b, cnt, ("imm", 0))
            fn.emit("jnz", b, l_fail)
            end = fn.new_v()
            fn.emit("bin", "add", end, lo, cnt)
            fn.emit("cmpset", "g", b, end, ln)
            fn.emit("jnz", b, l_fail)
            ln1 = fn.new_v()
            fn.emit("bin", "add", ln1, cnt, ("imm", 9))
            h = fn.new_v()
            fn.emit("call", h, "__alloc", [ln1])
            buf = fn.new_v()
            fn.emit("bin", "add", buf, h, ("imm", 8))
            sp = fn.new_v()
            fn.emit("bin", "add", sp, src, lo)
            fn.emit("call", None, "__memcpy", [buf, sp, cnt])
            fn.emit("store", h, ("imm", 0), cnt)      # 长度前缀
            z = fn.new_v()
            fn.emit("bin", "add", z, buf, cnt)
            fn.emit("store8", z, ("imm", 0), ("imm", 0))
            l_ok = fn.label("ssok")
            fn.emit("jmp", l_ok)
            fn.emit("label", l_fail)
            fn.emit("call", None, "__substr_fail", [])
            fn.emit("label", l_ok)
            return self._mark_str(fn, buf)
        if name == "chr" and name not in self.fns_ast:
            # chr(byte) -> str：单字节字符串（0..255）
            if len(e[2]) != 1:
                raise SyntaxError("chr(x) 需要一个实参")
            v = self.eval(e[2][0], fn, env)
            h = fn.new_v()
            fn.emit("call", h, "__alloc", [("imm", 9)])
            buf = fn.new_v()
            fn.emit("bin", "add", buf, h, ("imm", 8))
            fn.emit("store8", buf, ("imm", 0), v)
            fn.emit("store8", buf, ("imm", 1), ("imm", 0))
            fn.emit("store", h, ("imm", 0), ("imm", 1))   # 长度前缀
            return self._mark_str(fn, buf)
        if name == "args" and name not in self.fns_ast:
            # args() -> []str：程序参数（不含程序名）。Linux/AArch64 由入口直接
            # 保存 argc/argv；Windows 走 GetCommandLineA 惰性拆分。
            if e[2]:
                raise SyntaxError("args() 不接受实参")
            self.uses_args = True
            return self.lower_args(fn)
        if name == "arg" and name not in self.fns_ast:
            # arg(i) -> option[str] 暂不做；这里给 i 越界 fail-fast 的 str 版本
            if len(e[2]) != 1:
                raise SyntaxError("arg(i) 需要且只需要一个下标")
            self.uses_args = True
            sl = self.lower_args(fn)
            idx = self.eval(e[2][0], fn, env)
            ptr = self.slice_ptr(fn, sl)
            ln = self.slice_len(fn, sl)
            self.emit_bounds(fn, idx, ln, dynamic=True)
            d = fn.new_v()
            fn.emit("load", d, ptr, idx)
            return self._mark_str(fn, d)
        if name == "assert":
            # assert(cond) / assert(cond, "msg")：失败即写 stderr + exit(1)
            cond = self.eval(e[2][0], fn, env)
            l_ok = fn.label("assert_ok")
            fn.emit("jnz", cond, l_ok)
            msg = "assert failed: (no message)"
            if len(e[2]) > 1 and e[2][1][0] == "str":
                msg = "assert failed: " + e[2][1][1]
            gid = self.intern_str(msg + "\n")
            p = fn.new_v()
            fn.emit("movaddr", p, gid)
            # 注意：write 的长度是【字节数】，不是字符数（中文消息必须按 UTF-8 字节计）
            blen = len((msg + "\n").encode("utf-8"))
            self.emit_write(fn, 2, p, ("imm", blen))
            self.emit_exit(fn, ("imm", 1))
            fn.emit("label", l_ok)
            return ("imm", 0)
        if name == "join" and name not in self.fns_ast:
            if len(e[2]) != 1:
                raise SyntaxError("join(handle) 需要且只需要一个句柄")
            hv = self.eval(e[2][0], fn, env)
            d = fn.new_v()
            if self.is_serial():
                # 单核降级：spawn 已同步执行并直接返回结果，join 就是恒等
                fn.emit("mov", d, hv)
            else:
                self.uses_join = True
                fn.emit("call", d, "__join", [hv])
            return d
        if name == "len" and name not in self.fns_ast:
            if len(e[2]) != 1:
                raise SyntaxError("len(x) 需要且只需要一个实参")
            a = e[2][0]
            if a[0] == "name" and a[1] in env:
                n = self._arr_of(fn, env[a[1]])
                if n is not None:
                    return ("imm", n)
                if self._is_slice(fn, env[a[1]]):
                    return self.slice_len(fn, env[a[1]])
                if self._is_vec(fn, env[a[1]]):
                    self.uses_vec = True
                    d = fn.new_v()
                    fn.emit("call", d, "__vec_len", [env[a[1]]])
                    return d
                if self._map_of(fn, env[a[1]]) is not None:
                    self.uses_map = True
                    d = fn.new_v()
                    fn.emit("call", d, "__map_len", [env[a[1]]])
                    return d
                if self._is_str(fn, env[a[1]]):
                    return self.str_len(fn, env[a[1]])
            # 非名字实参：按求值结果判别（如函数返回的切片）
            av = self.eval(a, fn, env)
            if self._is_slice(fn, av):
                return self.slice_len(fn, av)
            if self._is_vec(fn, av):
                self.uses_vec = True
                d = fn.new_v()
                fn.emit("call", d, "__vec_len", [av])
                return d
            if self._map_of(fn, av) is not None:
                self.uses_map = True
                d = fn.new_v()
                fn.emit("call", d, "__map_len", [av])
                return d
            if self._is_str(fn, av):
                return self.str_len(fn, av)
            raise SyntaxError("len() 目前只支持定长数组、切片、map 或 str")
        if name == "slice_of" and name not in self.fns_ast:
            # 数组 -> 切片：零拷贝转换（SPEC §2 `[]T`）
            if len(e[2]) != 1:
                raise SyntaxError("slice_of(x) 需要且只需要一个数组实参")
            a = e[2][0]
            if a[0] != "name" or a[1] not in env:
                raise SyntaxError("slice_of() 目前只支持定长数组变量（零拷贝转换）")
            av = env[a[1]]
            n = self._arr_of(fn, av)
            if n is None:
                raise SyntaxError("slice_of() 目前只支持定长数组变量（零拷贝转换）")
            return self.make_slice(fn, av, ("imm", n), elem=self.arr_elem.get(av))
        if name in self.ffi_decls:
            # v1.87：@ffi 声明的函数没有函数体——必须在这里截住，否则会走到
            # 下面的用户函数路径，发射一条指向"从未发射过的标签"的 call。
            return self.lower_ffi(name, e, fn, env)
        if name not in self.fns_ast:
            if len(e[1]) == 1 and name in env:
                # 通过值调用：标识符是持有函数地址的局部变量（fnaddr 或 vreg）
                # -> callr 间接调用。无签名信息：返回值按标量处理（聚合/切片
                # 返回的目标不可间接调用）；标量/str 实参原样传；
                # 聚合实参按值编组——拷进临时帧槽传地址（v1.42，与直接调用的
                # 聚合编组同语义；目标形参须是聚合类型，无签名校验，
                # 与标量路径同信任级）。参数个数不再限 6（v1.42 栈传参）。
                callee = env[name]
                args = [self.eval(a, fn, env) for a in e[2]]
                for i, a in enumerate(args):
                    if self._is_slice(fn, a):
                        tmp = self.alloc_slice(fn)
                        self.words_copy(fn, tmp, a, SLICE_WORDS)
                        args[i] = tmp
                        continue
                    sname = self._struct_of(fn, a)
                    if sname is not None:
                        tmp = self.alloc_struct(fn, sname)
                        self.struct_copy(fn, tmp, a, sname)
                        args[i] = tmp
                d = fn.new_v()
                if self._struct_of(fn, callee) == "closure":
                    # 闭包调用（v1.95）：{code, env} 两字，env 作隐藏的第一实参
                    # （lambda 体形参表前面就是 __env__，ABI 与直接调用一致）。
                    # 同一函数内创建的闭包带签名 -> 恢复返回值类型、按形参转换
                    # 实参；跨函数传进来的闭包无签名，退回"按标量处理"。
                    sig = fn.closig.get(callee)
                    if sig is not None:
                        cps, cret = sig
                        for i, a in enumerate(args):
                            if i < len(cps):
                                args[i] = self.conv_to(
                                    fn, a, self._float_of(fn, a),
                                    self._ty_float_w(cps[i][1]))
                    code = fn.new_v()
                    fn.emit("load", code, callee, ("imm", 0))
                    envp = fn.new_v()
                    fn.emit("load", envp, callee, ("imm", 1))
                    cret = sig[1] if sig is not None else None
                    if cret is not None and cret[0] == "slice":
                        tmp = self.alloc_slice(fn)
                        fn.emit("callr", None, code, [tmp, envp] + args)
                        if cret[1][0] == "named":
                            self._mark_slice(fn, tmp, cret[1][1])
                        return tmp
                    if cret is not None and cret[0] == "array":
                        tmp = self.alloc_array(fn, cret[1])
                        fn.emit("callr", None, code, [tmp, envp] + args)
                        return tmp
                    if cret is not None and cret[0] == "named" \
                            and self.is_agg(cret[1]):
                        tmp = self.alloc_struct(fn, cret[1])
                        fn.emit("callr", None, code, [tmp, envp] + args)
                        return tmp
                    fn.emit("callr", d, code, [envp] + args)
                    if cret is not None:
                        if cret[0] == "named" and cret[1] == "str":
                            fn.strv.add(d)
                        elif cret[0] == "named" and cret[1] == "bool":
                            self._mark_bool(fn, d)
                        elif self._ty_float_w(cret):
                            self._mark_float(fn, d, self._ty_float_w(cret))
                    return d
                fn.emit("callr", d, callee, args)
                return d
            raise SyntaxError(f"未定义函数 {name}")
        args = [self.eval(a, fn, env) for a in e[2]]
        params = self.fns_ast[name]["params"]
        for i, a in enumerate(args):
            n = self._arr_of(fn, a)
            if n is not None:
                if i < len(params):
                    pt = params[i][1]
                    # 形参是 `[]T`：零拷贝转切片（SPEC §2）
                    if pt[0] == "slice":
                        args[i] = self.make_slice(fn, a, ("imm", n), elem=self.arr_elem.get(a))
                        continue
                    # 形参是 `[N]T`：传地址，callee 里按值拷一份（v1.2）
                    if pt[0] == "array":
                        if pt[1] != n:
                            raise SyntaxError(
                                f"实参数组长度 {n} 与形参 {pt[1]} 不一致")
                        continue
                raise SyntaxError("定长数组实参的形参必须是 [N]T 或 []T；也可用 slice_of(a)")
        # 聚合实参（结构体/枚举/切片）：拷贝到临时帧槽再传地址
        # -> 值语义与 C 后端一致（callee 改不到 caller 的切片头）
        for i, a in enumerate(args):
            if self._is_slice(fn, a):
                tmp = self.alloc_slice(fn)
                self.words_copy(fn, tmp, a, SLICE_WORDS)
                args[i] = tmp
                continue
            sname = self._struct_of(fn, a)
            if sname is not None:
                if (i < len(params) and params[i][1][0] == "named"
                        and self._is_iface(params[i][1][1])
                        and sname != params[i][1][1]):
                    a = self.box_iface(fn, a, sname, params[i][1][1])
                    sname = params[i][1][1]
                tmp = self.alloc_struct(fn, sname)
                self.struct_copy(fn, tmp, a, sname)
                if self._is_iface(sname):
                    # 实参槽 = 语句级临时：fresh 移动，否则 retain；语句结束时
                    # 释放（callee 只借用，不拥有）——v1.81
                    if a in fn.iface_fresh:
                        fn.iface_fresh.discard(a)
                    else:
                        self._iface_retain_slot(fn, tmp)
                    self.iface_temps.append(tmp)
                args[i] = tmp
        # 接口形参必须收到结构体（否则运行期 vt 是垃圾）
        for i, a in enumerate(args):
            if (i < len(params) and params[i][1][0] == "named"
                    and self._is_iface(params[i][1][1])
                    and self._struct_of(fn, a) is None):
                raise SyntaxError(
                    f"函数 {name} 的第 {i + 1} 个形参是接口 {params[i][1][1]}，"
                    f"实参不是结构体（需要传实现了该接口的类型）")
        # 闭包形参必须收到闭包（v1.95）：裸函数名是代码地址（int），
        # 按聚合传进去会让被调方从"地址的地址"读 code/env，必错。
        for i, a in enumerate(args):
            if (i < len(params) and params[i][1] == ("named", "closure")
                    and self._struct_of(fn, a) != "closure"):
                raise SyntaxError(
                    f"函数 {name} 的第 {i + 1} 个形参是 closure，实参不是闭包"
                    f"（裸函数名是代码地址，请用 fn(...) {{ ... }} 字面量，"
                    f"或包一层 fn(x: int) -> int {{ return foo(x) }}）")
        # 标量实参按形参类型转换（浮点宽度 / 整数<->浮点，与 C 隐式转换一致）
        for i, a in enumerate(args):
            if i < len(params):
                args[i] = self.conv_to(fn, a, self._float_of(fn, a),
                                      self._ty_float_w(params[i][1]))
        ret = self.fns_ast[name]["ret"]
        if ret[0] == "slice":
            # 切片返回值：同聚合（隐藏出参指针约定，调用方开帧槽，callee 拷入）
            tmp = self.alloc_slice(fn)
            fn.emit("call", None, name, [tmp] + args)
            # v1.56：返回类型里的元素标签要挂上，否则调用方经返回值写入不截断
            if ret[1][0] == "named":
                self._mark_slice(fn, tmp, ret[1][1])
            return tmp
        if ret[0] == "array":
            tmp = self.alloc_array(fn, ret[1])
            fn.emit("call", None, name, [tmp] + args)
            return tmp
        if ret[0] == "named" and self.is_agg(ret[1]):
            # 聚合返回值：隐藏出参指针约定（调用方开帧槽，callee 拷入）
            tmp = self.alloc_struct(fn, ret[1])
            fn.emit("call", None, name, [tmp] + args)
            if self._is_iface(ret[1]):
                # callee 已把计数移进 tmp：tmp 是语句级临时，语句尾释放
                self.iface_temps.append(tmp)
            return self._mark_struct(fn, tmp, ret[1])
        d = fn.new_v()
        fn.emit("call", d, name, args)
        if ret == ("named", "str"):
            return self._mark_str(fn, d)
        rw = self._ty_float_w(ret) if ret and ret[0] == "named" else None
        if rw:
            return self._mark_float(fn, d, rw)
        if ret and ret[0] == "map":
            return self._mark_map(fn, d, ret[1][1], ret[2][1])
        if ret and ret[0] == "vec":
            return self._mark_vec(fn, d, self._vec_tag_of(ret[1]))
        if ret and ret[0] == "rc":
            # rc[T] 返回值把"句柄 + payload 类型"一起带回来，
            # 否则调用方拿到的只是一个裸 int，后续 rc_* 全被拒。
            self._mark_rc(fn, d, ret[1][1])
            return self._mark_struct(fn, d, ret[1][1])
        return d

    # ---- 布尔条件跳转 ----
    # ---- 所有权 / 借用检查 ----
    # v1.8：rc[T] 句柄的线性检查（use-after-drop / double-drop / move-then-use /
    #       泄漏警告）。
    # v1.84：扩到**视图**（切片 []T、str 切片）的**生命周期**与**别名**，外加
    #       跨线程传递。四件事：
    #   1) 视图基址分五类：本帧栈 / 堆 / 静态 / 形参（调用方所有）/ 返回值（未知）。
    #      值语义形参（定长数组、struct）是**本帧副本** → 归"本帧栈"；
    #      视图/句柄形参（[]T、str、vec/map/chan/rc）→ 归"调用方所有"。
    #   2) 逃逸检查（错误）：本帧栈视图从 return / 堆容器（vec/map/chan 的
    #      push·set·insert·send）/ spawn 逃出 → 悬垂。结构体字段里装了栈视图时
    #      整个结构体标"含栈视图"并随拷贝传播，该结构体逃逸同样报错。
    #   3) 写别名检查（错误）：同一基址上两个**独立创建**的视图范围可能重叠且都被
    #      写入。由拷贝/赋值得到的视图继承同一"别名组"——切片零拷贝共享是本语言的
    #      显式语义（02-language §3），同组写入不报；常量区间或同一界表达式
    #      （`a[0..mid]` / `a[mid..n]`）可证不重叠，也放行。
    #   4) 跨线程（错误）：spawn 实参里出现 rc 句柄（引用计数非原子，跨线程
    #      clone/drop 必竞争）或本帧栈视图。
    # 不查（如实登记在 02-language §8.3）：多线程同时写同一堆内存的数据竞争、
    #   mem_str 裸指针的来源、跨函数的别名（被调方写 []T 形参，调用方看不到）。
    @staticmethod
    def _owned_names(stmts, state):
        """返回本块内"确定仍是活句柄"的名字集合（保守近似）"""
        return {n for n, st in state.items() if st == "live"}

    def _walk_names(self, node, out):
        if isinstance(node, tuple):
            if node and node[0] == "name" and len(node) > 1 and isinstance(node[1], str):
                out.append(node[1])
            for x in node:
                self._walk_names(x, out)
        elif isinstance(node, list):
            for x in node:
                self._walk_names(x, out)
        elif isinstance(node, dict):
            for x in node.values():
                self._walk_names(x, out)

    def _iter_nodes(self, node):
        """按源码顺序产出子树里的每个元组节点（语句 + 表达式）"""
        if isinstance(node, tuple):
            if node and isinstance(node[0], str):
                yield node
            for x in node:
                if isinstance(x, (tuple, list, dict)):
                    yield from self._iter_nodes(x)
        elif isinstance(node, list):
            for x in node:
                yield from self._iter_nodes(x)
        elif isinstance(node, dict):
            for x in node.values():
                yield from self._iter_nodes(x)

    def _expr_text(self, e):
        """表达式 -> 报错文案里的短写法"""
        if isinstance(e, tuple) and e:
            k = e[0]
            if k == "name":
                return e[1]
            if k == "path":
                return ".".join(str(x) for x in e[1])
            if k == "field":
                return self._expr_text(e[1]) + "." + str(e[2])
            if k == "index":
                return self._expr_text(e[1]) + "[…]"
            if k == "sliceof":
                return self._expr_text(e[1]) + "[..]"
            if k == "call":
                return str(e[1][-1]) + "(…)"
            if k == "method":
                return self._expr_text(e[1]) + "." + str(e[2]) + "(…)"
            if k == "structlit":
                return " ".join(str(x) for x in e[1]) + "{…}"
        return "…"

    def _root_name(self, e):
        if not isinstance(e, tuple) or not e:
            return None
        k = e[0]
        if k == "name":
            return e[1]
        if k == "path":
            return e[1][0] if e[1] else None
        if k in ("field", "index", "sliceof"):
            return self._root_name(e[1])
        return None

    @staticmethod
    def _bound(e):
        """区间端点 -> int / ('var', 名字) / None（未知）"""
        if isinstance(e, tuple) and e:
            if e[0] == "num":
                return e[1]
            if e[0] == "name":
                return ("var", e[1])
        return None

    def _own_parts(self, s):
        """语句"自己"的表达式部分（不含已被 _flat_stmts 摊平的块体）

        摊平后若还对整条复合语句走一遍子树，嵌套层数就是平方级的重复遍历。
        """
        k = s[0]
        if k == "if":
            return [s[1]]
        if k == "while":
            return [s[1]]
        if k in ("for", "parfor"):
            return [s[2], s[3]]
        if k == "foreach":
            return [s[2]]
        if k in ("annot", "arena", "defer"):
            return []
        if k == "match_stmt" and isinstance(s[1], tuple) and s[1][0] == "match":
            return [s[1][1]]
        return [s]

    def _flat_stmts(self, stmts, out):
        """按源码顺序摊平语句（含嵌套块），用于别名/生命周期的顺序近似"""
        for s in stmts or []:
            if not isinstance(s, tuple) or not s:
                continue
            out.append(s)
            k = s[0]
            if k == "if":
                self._flat_stmts(s[2], out)
                if s[3]:
                    self._flat_stmts(s[3], out)
            elif k == "while":
                self._flat_stmts(s[2], out)
            elif k in ("for", "parfor"):
                self._flat_stmts(s[4], out)
            elif k == "foreach":
                self._flat_stmts(s[3], out)
            elif k == "annot":
                self._flat_stmts([s[2]], out)
            elif k == "arena":
                self._flat_stmts(s[1], out)
            elif k == "defer":
                self._flat_stmts([s[1]], out)
            elif k == "match_stmt" and isinstance(s[1], tuple) and s[1][0] == "match":
                for arm in s[1][2]:
                    b = arm[1]
                    if isinstance(b, tuple) and b and b[0] == "block":
                        self._flat_stmts(b[1], out)

    def _place_view(self, e, views, arrays, agglocals):
        """位置表达式 -> 它所指存储的 (kind, base, lo, hi)，追不到返回 None"""
        if not isinstance(e, tuple) or not e:
            return None
        k = e[0]
        if k == "name":
            n = e[1]
            if n in views:
                return views[n][:4]
            if n in arrays:
                return ("stack", n, 0, arrays.get(n))
            if n in agglocals:
                return ("stack", n, 0, None)
            return None
        if k in ("path", "field"):
            root = self._root_name(e)
            if root is None:
                return None
            if root in views:
                # 视图的字段（`[]T` 无字段，`str` 无字段）——按原基址处理
                return views[root][:4]
            if root in arrays or root in agglocals:
                # 结构体/数组的字段：以 `h.f` 为独立基址（不同字段互不别名）
                return ("stack", self._expr_text(e), 0, None)
            return None
        return None

    @staticmethod
    def _vw(kind, base, lo, hi):
        """视图描述：kind/base/区间/别名组（None = 尚未分配组号）"""
        return (kind, base, lo, hi, None)

    def _view_of(self, e, views, arrays, agglocals):
        """表达式 -> 视图描述 (kind, base, lo, hi, group)；不是视图返回 None

        kind: stack（本帧栈）/ heap / static / param（调用方所有）/ ret（未知）
        """
        if not isinstance(e, tuple) or not e:
            return None
        k = e[0]
        if k == "name":
            return views.get(e[1])
        if k == "str":
            return self._vw("static", None, 0, None)
        if k == "call":
            fname = e[1][-1]
            if fname == "slice_of" and len(e[2]) == 1:
                b = self._place_view(e[2][0], views, arrays, agglocals)
                return self._vw(b[0], b[1], b[2], b[3]) if b is not None else None
            if fname in ("mem_str", "substr", "str_from_mem", "str_from_bytes",
                         "str_alloc", "chr", "read_text", "read_asset"):
                return self._vw("heap", None, None, None)
            ret = (self.fns_ast.get(fname) or {}).get("ret")
            if ret and (ret[0] == "slice" or
                        (ret[0] == "named" and ret[1] == "str")):
                # 被调方自己的逃逸检查已经拦住"返回本帧视图"，此处视为外部所有
                return self._vw("ret", None, None, None)
            return None
        if k == "sliceof":
            # 子切片：基址可以是视图，也可以是定长数组/结构体字段（值语义位置）
            inner = self._place_view(e[1], views, arrays, agglocals)
            if inner is None:
                inner = self._view_of(e[1], views, arrays, agglocals)
            if inner is None:
                return None
            lo, hi = self._bound(e[2]), self._bound(e[3])
            blo = inner[2]
            if isinstance(blo, int):
                if blo:
                    lo = self._shift_bound(blo, lo)
                    hi = self._shift_bound(blo, hi)
            else:
                lo = hi = None       # 基址自身偏移未知，区间只能算"未知"
            return self._vw(inner[0], inner[1], lo, hi)
        return None

    @staticmethod
    def _shift_bound(k, x):
        """区间端点平移 k（k 是基址偏移）"""
        if x is None:
            return None
        if isinstance(x, int):
            return k + x
        return ("+", k, x)

    @staticmethod
    def _ranges_may_overlap(a, b):
        """两个视图的区间是否可能重叠（左闭右开）；能证不重叠返回 False"""
        l1, h1, l2, h2 = a[2], a[3], b[2], b[3]
        if all(isinstance(x, int) for x in (l1, h1, l2, h2)):
            return l1 < h2 and l2 < h1
        # 同一界表达式：`a[0..mid]` 与 `a[mid..n]` 首尾相接，不重叠
        if h1 is not None and l2 is not None and h1 == l2:
            return False
        if h2 is not None and l1 is not None and h2 == l1:
            return False
        return True

    def _check_views(self, f, errs, warns):
        """视图生命周期 / 写别名 / 跨线程（v1.84）"""
        fname = f["name"]
        flat = []
        self._flat_stmts(f["body"], flat)
        views = {}       # name -> (kind, base, lo, hi, group)
        tainted = {}     # name -> 说明（哪个字段装了栈视图）
        arrays = {}      # 本帧定长数组变量 -> 长度（未知为 None）
        agglocals = set()  # 本帧 struct/enum 值（含值语义形参）
        rcnames = set()  # rc 句柄名
        gid = [0]

        def new_group():
            gid[0] += 1
            return gid[0]

        for (pn, pt) in f["params"]:
            if not isinstance(pt, tuple) or not pt:
                continue
            if pt[0] == "slice":
                views[pn] = ("param", None, None, None, -1)
            elif pt[0] == "array":
                # 值语义形参：调用方那份被拷进本帧，`slice_of` 指向本帧副本
                arrays[pn] = pt[1] if len(pt) > 1 and isinstance(pt[1], int) else None
            elif pt[0] == "named" and pt[1] == "str":
                views[pn] = ("param", None, None, None, -1)
            elif pt[0] == "named" and self.is_agg(pt[1]):
                agglocals.add(pn)
            elif pt[0] == "rc":
                rcnames.add(pn)

        # 名字最后出现的语句下标（近似活跃区间；写目标也算一次使用）
        last = {}
        for i, s in enumerate(flat):
            names = []
            for part in self._own_parts(s):
                self._walk_names(part, names)
            for n in names:
                last[n] = i

        seen = set()
        alias_pairs = set()

        def add_err(msg):
            if msg not in seen:
                seen.add(msg)
                errs.append(msg)

        def escape_one(e, where, what):
            """把 e 交给"比本帧活得久"的地方 → 栈视图/含栈视图结构体即悬垂"""
            v = self._view_of(e, views, arrays, agglocals)
            if v is not None and v[0] == "stack":
                add_err(f"{fname}: 把指向本帧栈存储的视图 `{self._expr_text(e)}` "
                        f"交给 {where}（{v[1]} 在本帧退出后失效 → 悬垂）")
            elif (isinstance(e, tuple) and e and e[0] == "name"
                    and e[1] in tainted):
                add_err(f"{fname}: 把含栈视图的结构体 `{e[1]}` 交给 {where}"
                        f"（{tainted[e[1]]}；本帧退出后悬垂）")

        for i, s in enumerate(flat):
            k = s[0]
            if k == "let":
                name, expr = s[2], s[3]
                anno = s[4][1] if len(s) > 4 and s[4][0] == "as" else None
                if anno is not None:
                    if anno[0] == "array":
                        arrays[name] = (anno[1] if len(anno) > 1 and
                                        isinstance(anno[1], int) else None)
                    elif anno[0] == "named" and self.is_agg(anno[1]):
                        agglocals.add(name)
                    elif anno[0] == "rc":
                        rcnames.add(name)
                if isinstance(expr, tuple) and expr and expr[0] == "arraylit":
                    arrays.setdefault(name, len(expr[1]))
                v = self._view_of(expr, views, arrays, agglocals)
                if v is not None:
                    if v[4] is None:
                        v = (v[0], v[1], v[2], v[3], new_group())
                    views[name] = v
                elif isinstance(expr, tuple) and expr and expr[0] == "structlit":
                    for fld, fe in expr[2].items():
                        fv = self._view_of(fe, views, arrays, agglocals)
                        if fv is not None and fv[0] == "stack":
                            tainted[name] = f"{name}.{fld} 装着指向 {fv[1]} 的视图"
                            break
                        if (isinstance(fe, tuple) and fe and fe[0] == "name"
                                and fe[1] in tainted):
                            tainted[name] = f"{name}.{fld} 来自含栈视图的 {fe[1]}"
                            break
                elif (isinstance(expr, tuple) and expr and expr[0] == "name"
                        and expr[1] in tainted):
                    tainted[name] = f"由含栈视图的 {expr[1]} 拷入"
                elif (isinstance(expr, tuple) and expr and expr[0] == "call"
                        and expr[1][-1] in ("rc_new", "rc_clone")):
                    rcnames.add(name)
            elif k == "assign" and s[2] == "=":
                if s[1] in views:
                    v = self._view_of(s[3], views, arrays, agglocals)
                    if v is not None:
                        views[s[1]] = v if v[4] is not None else \
                            (v[0], v[1], v[2], v[3], new_group())
                    else:
                        views.pop(s[1], None)
                if isinstance(s[3], tuple) and s[3] and s[3][0] == "call" \
                        and s[3][1][-1] in ("rc_new", "rc_clone"):
                    rcnames.add(s[1])
            elif k == "assign_field":
                root = self._root_name(s[1])
                if root:
                    fv = self._view_of(s[3], views, arrays, agglocals)
                    if fv is not None and fv[0] == "stack":
                        tainted[root] = \
                            f"{self._expr_text(s[1])} 装着指向 {fv[1]} 的视图"
                    elif (isinstance(s[3], tuple) and s[3] and s[3][0] == "name"
                            and s[3][1] in tainted):
                        tainted[root] = f"{self._expr_text(s[1])} 来自含栈视图的 {s[3][1]}"
            elif k == "return":
                e = s[1]
                if e is not None:
                    v = self._view_of(e, views, arrays, agglocals)
                    if v is not None and v[0] == "stack":
                        add_err(f"{fname}: 返回的视图 `{self._expr_text(e)}` 指向"
                                f"本帧栈存储（{v[1]}）；函数返回后该存储失效 → 悬垂")
                    elif (isinstance(e, tuple) and e and e[0] == "name"
                            and e[1] in tainted):
                        add_err(f"{fname}: 返回的结构体 `{e[1]}` 含指向本帧栈存储的"
                                f"视图（{tainted[e[1]]}）；返回后即悬垂")

            # 写别名：通过视图写元素时，看同基址上还有没有活着的独立视图
            if k == "assign_index":
                v = self._view_of(s[1], views, arrays, agglocals)
                if v is not None and v[1] is not None:
                    cname = self._expr_text(s[1])
                    for other, ov in views.items():
                        if other == cname or ov[4] == v[4]:
                            continue      # 同一视图 / 同一别名组（拷贝而来）
                        if ov[1] != v[1]:
                            continue
                        if last.get(other, -1) <= i:
                            continue      # 该视图在本语句之后不再使用
                        if not self._ranges_may_overlap(v, ov):
                            continue
                        pair = tuple(sorted((cname, other)))
                        if pair in alias_pairs:
                            break
                        alias_pairs.add(pair)
                        add_err(f"{fname}: 视图 `{pair[0]}` 与 `{pair[1]}` 指向同一底层"
                                f"存储（{v[1]}），范围可能重叠且二者都被写入（别名写）")
                        break

            # 逃逸到堆容器 / 另一个线程
            for part in self._own_parts(s):
                for node in self._iter_nodes(part):
                    nk = node[0]
                    if nk == "method" and node[2] in ("push", "set", "insert", "send"):
                        where = f"{self._expr_text(node[1])}.{node[2]}()"
                        for a in node[3]:
                            escape_one(a, where, "容器")
                    elif nk == "spawn":
                        tgt = node[1]
                        if isinstance(tgt, tuple) and tgt[0] == "call":
                            for a in tgt[2]:
                                if (isinstance(a, tuple) and a and a[0] == "name"
                                        and a[1] in rcnames):
                                    add_err(
                                        f"{fname}: spawn 把 rc 句柄 `{a[1]}` 传给了另一个"
                                        f"线程（引用计数非原子，跨线程 clone/drop 会竞争）")
                                else:
                                    escape_one(a, "spawn（另一个线程）", "线程")

    def check_ownership(self, f):
        state = {}
        errs = []
        warns = []

        def dead_uses(node, st):
            names = []
            self._walk_names(node, names)
            for n in names:
                if st.get(n) == "dead":
                    errs.append(f"{f['name']}: 使用已失效的 rc 句柄 {n}"
                                f"（已 drop 或已 move）")

        def is_rc_producer(e):
            return (isinstance(e, tuple) and e and e[0] == "call"
                    and e[1][-1] in ("rc_new", "rc_clone"))

        def scan(stmts, st):
            for s in stmts:
                k = s[0]
                if k == "let":
                    expr = s[3]
                    anno = s[4][1] if len(s) > 4 and s[4][0] == "as" else None
                    names = []
                    self._walk_names(expr, names)
                    for n in names:
                        if st.get(n) == "dead":
                            errs.append(f"{f['name']}: `let {s[2]}` 的初值使用了"
                                        f"已失效的 rc 句柄 {n}")
                    moved_from = (expr[1] if (expr[0] == "name"
                                              and st.get(expr[1]) == "live") else None)
                    if (anno and anno[0] == "rc") or is_rc_producer(expr) or moved_from:
                        if moved_from:
                            st[moved_from] = "dead"   # move：所有权转到新名字
                        st[s[2]] = "live"
                elif k == "assign":
                    if s[2] == "=" and st.get(s[1]) == "live":
                        # 覆盖一个还活着的句柄 -> 泄漏（warn，不拦编译）
                        if not (is_rc_producer(s[3]) or
                                (s[3][0] == "name" and s[3][1] == s[1])):
                            warns.append(f"{f['name']}: 变量 {s[1]} 还持有 rc 句柄就"
                                         f"被重新赋值（旧句柄泄漏）")
                            st[s[1]] = "dead"
                    dead_uses(s[3], st)
                    if s[2] == "=" and (is_rc_producer(s[3]) or
                                        (s[3][0] == "name" and st.get(s[3][1]) == "live")):
                        if s[3][0] == "name" and st.get(s[3][1]) == "live":
                            st[s[3][1]] = "dead"
                        st[s[1]] = "live"
                elif k == "expr":
                    e = s[1]
                    if e[0] == "call" and e[1][-1] == "rc_drop":
                        a = e[2][0]
                        if a[0] == "name":
                            if st.get(a[1]) == "dead":
                                errs.append(f"{f['name']}: rc_drop({a[1]}) 的句柄已失效"
                                            f"（已 move 或已 drop，双重释放）")
                            elif st.get(a[1]) == "live":
                                st[a[1]] = "dead"
                            else:
                                # 未知来源（形参/跨块）不记账
                                pass
                        continue
                    dead_uses(e, st)
                elif k == "return":
                    if s[1] is not None:
                        if s[1][0] == "name" and st.get(s[1][1]) == "live":
                            st[s[1][1]] = "dead"       # 所有权随返回值转移
                        else:
                            dead_uses(s[1], st)
                elif k == "if":
                    dead_uses(s[1], st)
                    a, b = dict(st), dict(st)
                    scan(s[2], a)
                    if s[3]:
                        scan(s[3] if isinstance(s[3], list) else [s[3]], b)
                        merged = {}
                        for n in set(a) | set(b):
                            if a.get(n) == b.get(n):
                                merged[n] = a.get(n)
                            elif "dead" in (a.get(n), b.get(n)):
                                merged[n] = st.get(n) if st.get(n) == "dead" else "live"
                        st.clear(); st.update(merged)
                    else:
                        st.clear(); st.update({n: v for n, v in a.items()})
                elif k in ("while", "for"):
                    dead_uses(s[1] if k == "while" else (s[2], s[3]), st)
                    inner = dict(st)
                    body = s[2] if k == "while" else s[4]
                    scan(body, inner)
                elif k == "annot":
                    if s[2][0] == "for" and "simd" in [a[0] for a in s[1]]:
                        continue          # @simd 体已被识别/校验过
                    scan([s[2]], st)
                elif k in ("match_stmt", "match"):
                    dead_uses(s, st)
                elif k == "arena":
                    pass
                else:
                    dead_uses(s, st)

        scan(f["body"], state)
        for n, st in state.items():
            if st == "live":
                warns.append(f"{f['name']}: rc 句柄 {n} 在函数结束时仍存活"
                             f"（泄漏；需要 rc_drop 或 return）")
        # v1.84：视图生命周期 / 写别名 / 跨线程
        self._check_views(f, errs, warns)
        for w in warns:
            print(f"[qlm] 警告：{w}", file=sys.stderr)
        if errs:
            raise SyntaxError("所有权检查失败：\n  " + "\n  ".join(errs))

    # ---- interface 动态分发（v1.9）----
    # 接口值 = {data, vt} 两个字：
    #   data -> 堆上装箱的 payload（结构体按值拷进去，生命周期跟接口值走）
    #   vt   -> vtable 地址（代码段里一张函数指针表，按接口方法声明顺序）
    # 调用 obj.m(...) 时：vt = load obj[1]; fp = load vt[slot]; callr fp, [data, ...]
    def build_iface_meta(self, fns_ast):
        self.iface_names = set()
        self.iface_m = {}      # iface -> {m: (slot, ret_ty, params)}
        self.vtables = {}      # (iface, type) -> [fn name per slot]
        self.method_ambig = {}  # (type, m) -> [iface...]（同名方法跨接口，v1.81）
        impls = {}             # (iface) -> {type: {m: fn name}}
        for f in fns_ast:
            iname = f.get("impl_iface")
            if not iname:
                continue
            self.iface_names.add(iname)
            slots = self.iface_m.setdefault(iname, {})
            for i, m in enumerate(f.get("iface_order") or []):
                pt, rt = f.get("iface_sig", {}).get(m, ([], ("named", "void")))
                slots.setdefault(m, (i, rt, pt))
            bym = impls.setdefault(iname, {}).setdefault(f["self_type"], {})
            # 同一类型 + 同名方法出现在不同接口里 -> 静态调用歧义。
            # 注意不能按接口分组统计（每个接口一张新表），必须全局按
            # (类型, 方法名) 记（v1.81）。
            key = (f["self_type"], f["impl_method"])
            amb = self.method_ambig.setdefault(key, [])
            if iname not in amb:
                amb.append(iname)
            bym[f["impl_method"]] = f["name"]
        # 只有真的来自 2 个以上接口才算歧义
        self.method_ambig = {k: sorted(v) for k, v in self.method_ambig.items()
                             if len(v) > 1}
        for iname, by_type in impls.items():
            order = [m for m, (_s, _r, _p) in
                     sorted(self.iface_m[iname].items(), key=lambda kv: kv[1][0])]
            for tname, table in by_type.items():
                self.vtables[(iname, tname)] = [table[m] for m in order]

    def _is_iface(self, name):
        return name in getattr(self, "iface_names", set())

    def box_iface(self, fn, spec, sname, iname):
        """把具体结构体装箱成接口值；spec 已经是接口值则只复制。

        装箱块布局（v1.81 引用计数）：
            [rc][payload_bytes][payload ...]
        `data` 指向 payload（= raw+16），因此 impl 方法的 self 依旧是
        一个普通的聚合指针，既有方法体/ABI 零改动；rc 与字节数在
        data-16 / data-8，由 __iface_release 读取。
        新建的箱 rc=1（所有权归当前表达式），交给槽位时"移动"或"复制"，
        见 _iface_take / _iface_retain_slot。"""
        if sname == iname:
            dst = self.alloc_struct(fn, iname)
            self.struct_copy(fn, dst, spec, iname)
            return dst
        key = (iname, sname)
        if key not in self.vtables:
            raise SyntaxError(
                f"{sname} 没有实现接口 {iname}（需要一个 `impl {sname} : {iname} {{ ... }}`）")
        # 装箱宽度按聚合布局取（struct 或 enum）：此前只认 struct，
        # 把枚举装进接口值会报"未声明的结构体"（v1.65 修复）
        w = self.agg_size(sname)
        self.uses_iface_rc = True
        self.uses_free = True          # __iface_release 走 __free 尺寸类回收
        raw = fn.new_v()
        fn.emit("call", raw, "__alloc", [("imm", 16 + 8 * w)])
        fn.emit("store", raw, ("imm", 0), ("imm", 1))        # rc
        fn.emit("store", raw, ("imm", 1), ("imm", 8 * w))    # payload 字节数
        body = fn.new_v()
        fn.emit("bin", "add", body, raw, ("imm", 16))
        i = 0
        while i < w:
            v = fn.new_v()
            fn.emit("load", v, spec, ("imm", i))
            fn.emit("store", body, ("imm", i), v)
            i = i + 1
        dst = self.alloc_struct(fn, iname)
        fn.emit("store", dst, ("imm", 0), body)
        vt = fn.new_v()
        fn.emit("mov", vt, ("fnaddr", f"__vt_{iname}__{sname}"))
        fn.emit("store", dst, ("imm", 1), vt)
        self._mark_struct(fn, dst, iname)
        fn.iface_fresh.add(dst)        # 这个箱的 rc=1 归"当前表达式"
        return dst

    # ---- 接口值所有权（v1.81）----
    # 规则（保守到"只会泄漏、不会悬垂"）：
    #   * 箱由 box_iface 创建时 rc=1，所有权属于当前表达式（fresh）；
    #   * 装进"会被释放的槽"（let 变量 / 语句临时槽）时：
    #       fresh -> 移动（不增计数），否则 -> __iface_retain（复制一份计数）；
    #   * 槽死亡（块尾 / 语句尾 / return 前 / break·continue 跳出）时
    #       __iface_release，计数归零即 __free；
    #   * 无法判定所有权的来源（vec.get / 字段 / 切片元素 / 形参）按"借用"
    #     处理：不增计数也不释放 —— 计数只会偏大，不会提前回收；
    #   * 进入容器元素 / struct 字段 / map 值的接口值一律 retain（容器本身
    #     没有 Drop，元素随容器一起不释放，与语言其余部分一致）。
    def _iface_data(self, fn, slot):
        p = fn.new_v()
        fn.emit("load", p, slot, ("imm", 0))
        return p

    def _iface_retain_slot(self, fn, slot):
        self.uses_iface_rc = True
        self.uses_free = True
        p = self._iface_data(fn, slot)
        l_skip = fn.label("ifacekeep")
        fn.emit("jz", p, l_skip)       # 空接口值（data=0）不计数
        fn.emit("call", None, "__iface_retain", [p])
        fn.emit("label", l_skip)

    def _iface_release_slot(self, fn, slot):
        self.uses_iface_rc = True
        self.uses_free = True
        p = self._iface_data(fn, slot)
        l_skip = fn.label("ifacedrop")
        fn.emit("jz", p, l_skip)
        fn.emit("call", None, "__iface_release", [p])
        fn.emit("label", l_skip)

    def _iface_take(self, fn, dst, src, rhs=None):
        """把接口值 src 装进"会被释放的槽" dst：fresh 移动、否则 retain。
        返回 True 表示 dst 从此拥有一个计数（已登记进当前作用域）。
        返回 False = 按借用处理（不增计数、不释放——安全侧）。"""
        fresh = getattr(fn, "iface_fresh", None)
        if fresh and src in fresh:
            fresh.discard(src)
            fn.iface_own.add(dst)
            self.iface_scope[-1].append(dst)
            return True
        if rhs is None or self._iface_rhs_owns(rhs):
            self._iface_retain_slot(fn, dst)
            fn.iface_own.add(dst)
            self.iface_scope[-1].append(dst)
            return True
        return False

    def _iface_rhs_owns(self, rhs):
        """右侧表达式是否产生"我们拥有的一份计数"：
        变量名（我们自己 retain 的那份）与返回接口值的用户函数调用。"""
        if not isinstance(rhs, tuple):
            return False
        if rhs[0] == "name":
            return True
        if rhs[0] == "call" and isinstance(rhs[1], list) and rhs[1]:
            f = self.fns_ast.get(rhs[1][-1])
            if f is not None:
                ret = f.get("ret") or ()
                return (len(ret) == 2 and ret[0] == "named"
                        and self._is_iface(ret[1]))
        return False

    def _iface_share(self, fn, slot, src):
        """接口值进入不释放的位置（容器元素 / struct 字段 / map 值）：
        fresh 直接移动，否则 retain（多留一份，绝不悬垂）。
        retain 作用在"数据指针"上，因此借 src 或目标槽都等价。"""
        fresh = getattr(fn, "iface_fresh", None)
        if fresh and src in fresh:
            fresh.discard(src)
            return
        self._iface_retain_slot(fn, slot)

    def _iface_exit(self, fn, depth=0):
        """控制流提前离开作用域（return / break / continue）时的释放：
        先清语句临时槽，再由内向外释放 owned 槽。**不 pop 作用域帧**——
        正常落到底的路径还要在块尾释放/弹出（两条路径互斥，不会重复）。"""
        while len(self.iface_temps) > 0:
            self._iface_release_slot(fn, self.iface_temps.pop())
        for frame in reversed(self.iface_scope[depth:]):
            for slot in reversed(frame):
                self._iface_release_slot(fn, slot)


    def lower_iface_call(self, iname, obj, mname, arg_exprs, fn, env):
        info = self.iface_m.get(iname, {}).get(mname)
        if info is None:
            raise SyntaxError(f"接口 {iname} 没有方法 {mname}")
        slot, ret, ptypes = info
        vt = fn.new_v()
        fn.emit("load", vt, obj, ("imm", 1))
        fp = fn.new_v()
        fn.emit("load", fp, vt, ("imm", slot))
        data = fn.new_v()
        fn.emit("load", data, obj, ("imm", 0))
        args = [data] + [self.eval(a, fn, env) for a in arg_exprs]
        # 实参侧：接口形参 / 浮点宽度按签名转换（与直接调用一致）
        for i, a in enumerate(args):
            if i < len(ptypes):
                sname = self._struct_of(fn, a)
                if (sname is not None and ptypes[i][0] == "named"
                    and self._is_iface(ptypes[i][1])):
                    args[i] = self.box_iface(fn, a, sname, ptypes[i][1])
                    # 新装的箱直接当实参传（callee 借用）：语句尾释放 v1.81
                    self.iface_temps.append(args[i])
        if ret[0] == "named" and ret[1] in ("void",):
            fn.emit("callr", None, fp, args)
            return ("imm", 0)
        if ret[0] == "slice" or (ret[0] == "named" and self.is_agg(ret[1])):
            # 聚合/切片返回：隐藏出参指针作第一个实参（同直接调用 ABI）
            tmp = (self.alloc_slice(fn) if ret[0] == "slice"
                   else self.alloc_struct(fn, ret[1]))
            fn.emit("callr", None, fp, [tmp] + args)
            if ret[0] == "named" and self._is_iface(ret[1]):
                self.iface_temps.append(tmp)      # 方法返回接口值：转移给调用方
                return self._mark_struct(fn, tmp, ret[1])
            return tmp
        d = fn.new_v()
        fn.emit("callr", d, fp, args)
        if ret == ("named", "str"):
            return self._mark_str(fn, d)
        rw = self._ty_float_w(ret)
        if rw:
            return self._mark_float(fn, d, rw)
        return d

    # ---- rc[T] 内建 ----
    def lower_rc(self, name, e, fn, env):
        """布局：[refcount 8B][payload n*8B]；句柄指向 payload。
        rc_new 拷贝构造；rc_get 只是取回 payload（借用，不增计数）；
        rc_clone 增计数；rc_drop 减计数并在 0 时 __free。"""
        args = e[2]
        if name == "rc_new":
            if len(args) != 1:
                raise SyntaxError("rc_new(x) 需要一个实参")
            spec = self.eval(args[0], fn, env)
            sname = self._struct_of(fn, spec)
            if sname is None:
                raise SyntaxError("rc_new 目前只支持具名结构体（docs/GAPS.md §2）")
            w = self.struct_size(sname)
            raw = fn.new_v()
            fn.emit("call", raw, "__alloc", [("imm", 8 + 8 * w)])
            fn.emit("store", raw, ("imm", 0), ("imm", 1))
            i = 0
            while i < w:
                v = fn.new_v()
                fn.emit("load", v, spec, ("imm", i))
                fn.emit("store", raw, ("imm", i + 1), v)
                i = i + 1
            h = fn.new_v()
            fn.emit("bin", "add", h, raw, ("imm", 8))
            self._mark_rc(fn, h, sname)
            self._mark_struct(fn, h, sname)
            return h
        if len(args) != 1:
            raise SyntaxError(f"{name}(h) 需要一个实参")
        h = self.eval(args[0], fn, env)
        sname = self._rc_of(fn, h)
        if sname is None:
            raise SyntaxError(f"{name} 的实参不是 rc[T] 句柄")
        w = self.struct_size(sname)
        if name == "rc_get":
            self._mark_struct(fn, h, sname)
            return h
        if name == "rc_count":
            c = fn.new_v()
            fn.emit("load", c, h, ("imm", -1))
            return c
        if name == "rc_clone":
            c = fn.new_v()
            fn.emit("load", c, h, ("imm", -1))
            c2 = self.arith("+", c, ("imm", 1), fn, env)
            fn.emit("store", h, ("imm", -1), c2)
            self._mark_rc(fn, h, sname)
            self._mark_struct(fn, h, sname)
            return h
        # rc_drop
        c = fn.new_v()
        fn.emit("load", c, h, ("imm", -1))
        c2 = fn.new_v()
        fn.emit("bin", "sub", c2, c, ("imm", 1))
        fn.emit("store", h, ("imm", -1), c2)
        l_keep, l_end = fn.label("rckeep"), fn.label("rcend")
        fn.emit("jnz", c2, l_keep)
        raw = fn.new_v()
        fn.emit("bin", "sub", raw, h, ("imm", 8))
        self.uses_free = True
        fn.emit("call", None, "__free", [raw, ("imm", 8 + 8 * w)])
        fn.emit("label", l_keep)
        fn.emit("label", l_end)
        return ("imm", 0)

    def branch(self, e, fn, env, l_true, l_false):
        k = e[0]
        if k == "binop" and e[1] in ("==", "!=", "<", "<=", ">", ">="):
            a = self.eval(e[2], fn, env)
            b = self.eval(e[3], fn, env)
            # str 是内容相等（不是指针比较）：条件分支必须走 __str_eq，
            # 否则 `if s == "x"` 永远为假（表达式路径早就正确，分支路径曾漏掉）。
            if e[1] in ("==", "!=") and (self._is_str(fn, a) or self._is_str(fn, b)):
                eq = fn.new_v()
                fn.emit("call", eq, "__str_eq", [a, b])
                fn.emit("jnz" if e[1] == "==" else "jz", eq, l_true)
                fn.emit("jmp", l_false)
                return
            # str 有序比较（v1.66）：条件路径同样要走 __str_cmp——表达式路径
            # 早就改了，分支路径曾漏掉（v1.19 浮点比较的同款双路径坑）
            if e[1] in ("<", "<=", ">", ">=") \
                    and (self._is_str(fn, a) or self._is_str(fn, b)):
                c = fn.new_v()
                fn.emit("call", c, "__str_cmp", [a, b])
                cc2 = {"<": "l", "<=": "le", ">": "g", ">=": "ge"}[e[1]]
                fn.emit("jcc", cc2, c, ("imm", 0), l_true)
                fn.emit("jmp", l_false)
                return
            cc = {"==": "e", "!=": "ne", "<": "l", "<=": "le", ">": "g", ">=": "ge"}[e[1]]
            # 浮点比较必须走 fcmpset（comisd + setcc），不能直接 jcc：
            # IEEE754 负数的位模式在整数序下是反的，直接 jcc 会让
            # `if -2.0 > -1.0` 成立（v1.19 修复）。
            wa, wb = self._float_of(fn, a), self._float_of(fn, b)
            if wa or wb:
                w = "f64" if "f64" in (wa, wb) else "f32"
                a = self.conv_to(fn, a, wa, w)
                b = self.conv_to(fn, b, wb, w)
                d = fn.new_v()
                fn.emit("fcmpset", w, cc, d, a, b)
                fn.emit("jnz", d, l_true)
                fn.emit("jmp", l_false)
                return
            fn.emit("jcc", cc, a, b, l_true)
            fn.emit("jmp", l_false)
            return
        if k == "binop" and e[1] == "&&":
            mid = fn.label("and")
            self.branch(e[2], fn, env, mid, l_false)
            fn.emit("label", mid)
            self.branch(e[3], fn, env, l_true, l_false)
            return
        if k == "binop" and e[1] == "||":
            mid = fn.label("or")
            self.branch(e[2], fn, env, l_true, mid)
            fn.emit("label", mid)
            self.branch(e[3], fn, env, l_true, l_false)
            return
        if k == "unop" and e[1] == "!":
            self.branch(e[2], fn, env, l_false, l_true)
            return
        v = self.eval(e, fn, env)
        fn.emit("jnz", v, l_true)
        fn.emit("jmp", l_false)

    # ---- 语句 ----
    def _dbg_bind(self, fn, name, v):
        """v1.62 调试信息：let 绑定处发射"变量 -> vreg"标记。

        只有 vreg（int）能发射：('imm', n) 这类编译期常量没有运行期位置。
        标记位置即变量诞生点，调试器据此在断点处解析"当前值在哪"。"""
        if isinstance(v, int):
            fn.emit("dbgvar", name, v)

    def _dbg_bind_param(self, fn, name, v):
        """v1.62：形参绑定标记。与 let 的区别是**入口即可用**——codegen
        把它的 bind 归到函数起点（偏移 0），断点落在函数任何一条语句上
        都能查到（let 绑定则要求断点严格晚于绑定偏移：在 `let x = ...`
        自己那条行上，x 还没赋值，报了反而是错的）。"""
        if isinstance(v, int):
            fn.emit("dbgparam", name, v)

    def stmt(self, s, fn, env):
        """语句包装：语句结束时释放本语句产生的接口临时槽（v1.81）。
        临时槽来自"调用实参拷贝"与"返回接口值的调用结果"——它们的
        所有权只覆盖一条语句；`return` 自己在 emit ret 之前先清空。"""
        n0 = len(self.iface_temps)
        self._stmt(s, fn, env)
        if len(self.iface_temps) > n0:
            for slot in self.iface_temps[n0:]:
                self._iface_release_slot(fn, slot)
            del self.iface_temps[n0:]

    def _stmt(self, s, fn, env):
        k = s[0]
        # v1.62 调试信息：语句行号标记（qlm_dbinfo 的 parse_stmt 钩子追加的
        # ("__line__", n) 尾部元素）。只在 --dbg-info 构建发射。
        if self.dbg and len(s) > 1:
            m = s[-1]
            if isinstance(m, tuple) and len(m) == 2 and m[0] == "__line__":
                fn.emit("line", m[1])
        if k == "annot":
            names = [a[0] for a in s[1]]
            inner = s[2]
            if "simd" in names:
                if inner[0] != "for":
                    raise SyntaxError("@simd 只能修饰 for 循环")
                self.lower_simd_for(inner, fn, env)
                return
            if "no_preempt" in names:
                prev = getattr(self, "no_preempt", False)
                self.no_preempt = True
                try:
                    self.stmt(inner, fn, env)
                finally:
                    self.no_preempt = prev
                return
            self.stmt(inner, fn, env)
            return
        if k == "let":
            spec = self.eval(s[3], fn, env)
            if len(s) > 4 and s[4][0] == "as":
                at = s[4][1]
                nb = self.narrow_of(at)
                if nb is not None:
                    spec = self.trunc_to(fn, spec, nb)
                elif at[0] == "named" and self._is_iface(at[1]):
                    # let s: Shape = Circle{..} —— 隐式装箱
                    sn = self._struct_of(fn, spec)
                    if sn is not None:
                        spec = self.box_iface(fn, spec, sn, at[1])
            n = self._arr_of(fn, spec)
            if n is not None:
                ann = s[4][1] if (len(s) > 4 and s[4][0] == "as") else None
                nb = self._arr_narrow_of(ann)
                if s[3][0] == "arraylit":
                    # 字面量已经是在帧上新建的数组，直接绑定，不再多拷一次；
                    # 窄元素：字面量按 64 位存槽，就地把每个元素截到声明宽度（v1.40）
                    env[s[2]] = spec
                    if self.dbg:
                        self._dbg_bind(fn, s[2], env[s[2]])
                    if nb is not None:
                        self.arr_narrow[spec] = nb
                        self.arr_elem[spec] = ann[2][1]
                        for i in range(n):
                            t = fn.new_v()
                            fn.emit("load", t, spec, ("imm", i))
                            tt = fn.new_v()
                            fn.emit("trunc", tt, t, nb[0], nb[1])
                            fn.emit("store", spec, ("imm", i), tt)
                    return
                dst = self.alloc_array(fn, n)
                self.array_copy(fn, dst, spec, n, nb=nb)
                if nb is not None:
                    self.arr_narrow[dst] = nb
                    self.arr_elem[dst] = ann[2][1]
                env[s[2]] = dst
                if self.dbg:
                    self._dbg_bind(fn, s[2], env[s[2]])
                return
            if self._rc_of(fn, spec) is not None:
                # rc 句柄按句柄语义绑定（不拷贝 payload）；引用计数不变
                env[s[2]] = spec
                if self.dbg:
                    self._dbg_bind(fn, s[2], env[s[2]])
                return
            if (len(s) > 4 and s[4][0] == "as"
                    and s[4][1] == ("named", "closure")
                    and self._struct_of(fn, spec) != "closure"):
                # 注解是 closure 却拿到非闭包值（典型：裸函数名）——不能静默
                # 存成代码地址，否则后续按两字聚合读 code/env 会读飞。
                raise SyntaxError(
                    f"let {s[2]}: closure 的初值不是闭包"
                    f"（裸函数名是代码地址；请用 fn(...) {{ ... }} 字面量）")
            sname = self._struct_of(fn, spec)
            if sname is not None:
                # 结构体：值语义 -> 拷贝到新的帧槽
                dst = self.alloc_struct(fn, sname)
                self.struct_copy(fn, dst, spec, sname)
                if sname == "closure" and spec in fn.closig:
                    fn.closig[dst] = fn.closig[spec]     # 闭包签名跟着值走
                if self._is_iface(sname):
                    # 接口值变量：登记所有权，块尾释放（v1.81）
                    self._iface_take(fn, dst, spec, s[3])
                elif self._has_drop(sname):
                    # v1.93：析构绑定。`let b = a` 是**移动**——a 的析构
                    # 责任随值转给 b（否则同一份资源析构两次）。
                    if s[3][0] == "name":
                        src = env.get(s[3][1])
                        if isinstance(src, int):
                            self._drop_forget(src)
                    self._drop_register(dst, sname)
                env[s[2]] = dst
                if self.dbg:
                    self._dbg_bind(fn, s[2], env[s[2]])
                return
            if self._is_slice(fn, spec):
                # 切片：{ptr,len} 两字值语义拷贝（仍共享底层存储）
                dst = self.alloc_slice(fn)
                self.words_copy(fn, dst, spec, SLICE_WORDS)
                elem = self._slice_elem(fn, spec)
                if elem is not None:
                    self._mark_slice(fn, dst, elem)     # 元素标签要跟着拷贝走
                env[s[2]] = dst
                if self.dbg:
                    self._dbg_bind(fn, s[2], env[s[2]])
                return
            is_str = self._is_str(fn, spec)
            is_bool = s[3][0] == "bool" or (isinstance(spec, int) and spec in getattr(fn, "boolv", set()))
            # 标量 let 必须【拷贝到新 vreg】：早期直接把 env[name] 指向同一个 vreg，
            # 于是 `let mut j = i` 之后 `j += 1` 会连带改掉 i（值语义被破坏）。
            d = fn.new_v()
            fn.emit("mov", d, spec)
            # 拷贝出来的新 vreg 必须继承所有类型标签，否则 chan.recv()/map.get()
            # 会因为"这个 vreg 不再是通道/表"而报错。
            if is_str:
                self._mark_str(fn, d)
            if is_bool:
                self._mark_bool(fn, d)
            if self._is_nonneg(fn, spec):
                self._mark_nonneg(fn, d)
            else:
                self._unmark_nonneg(fn, d)
            if self._is_chan(fn, spec):
                self._mark_chan(fn, d)
            mp = self._map_of(fn, spec)
            if mp is not None:
                self._mark_map(fn, d, mp[0], mp[1])
            if self._is_vec(fn, spec):
                self._mark_vec(fn, d, self._vec_elem(fn, spec))
            if self._float_of(fn, spec):
                self._mark_float(fn, d, self._float_of(fn, spec))
            if len(s) > 4 and s[4][0] == "as":
                nb = self.narrow_of(s[4][1])
                if nb is not None:
                    if not hasattr(fn, "narrow_v"):
                        fn.narrow_v = {}
                    fn.narrow_v[d] = nb
            env[s[2]] = d
            if self.dbg:
                self._dbg_bind(fn, s[2], env[s[2]])
            return
        if k == "assign":
            if s[1] not in env:
                raise SyntaxError(f"未定义变量 {s[1]}")
            cur = env[s[1]]
            n = self._arr_of(fn, cur)
            if n is not None:
                if s[2] != "=":
                    raise SyntaxError("数组只支持 = 整体赋值")
                spec = self.eval(s[3], fn, env)
                if self._arr_of(fn, spec) != n:
                    raise SyntaxError("数组赋值两侧长度不一致")
                # 窄元素数组：目标侧的声明宽度约束拷入值（v1.40）
                self.array_copy(fn, cur, spec, n, nb=self.arr_narrow.get(cur))
                return
            sname = self._struct_of(fn, cur)
            if sname is not None:
                if s[2] != "=":
                    raise SyntaxError("结构体只支持 = 整体赋值")
                spec = self.eval(s[3], fn, env)
                src_n = self._struct_of(fn, spec)
                if src_n is not None and src_n != sname and self._is_iface(sname):
                    spec = self.box_iface(fn, spec, src_n, sname)   # 装箱
                elif self._struct_of(fn, spec) != sname:
                    raise SyntaxError("结构体赋值两侧类型不一致")
                if self._is_iface(sname) and spec != cur:
                    # 接口值赋值（v1.81）：先释放旧箱，再按 fresh/复制装新值。
                    # 非 owned 的目标（形参/借用）只 retain 不释放——多留一份
                    # 计数是泄漏，释放别人的计数才是悬垂。
                    if cur in fn.iface_own:
                        self._iface_release_slot(fn, cur)
                    self.struct_copy(fn, cur, spec, sname)
                    self._iface_take(fn, cur, spec, s[3])
                    return
                if self._has_drop(sname) and spec != cur:
                    # v1.93：覆盖式赋值先析构旧值（右值已求值完），再拷入。
                    # 目标不是 drop 绑定（形参/字段副本）时同样析构一次——
                    # 与 C++ 赋值语义一致：被覆盖的那份值必须释放。
                    self.emit_drop(fn, cur, sname)
                self.struct_copy(fn, cur, spec, sname)
                if sname == "closure" and spec in fn.closig:
                    fn.closig[cur] = fn.closig[spec]
                return
            spec = self.eval(s[3], fn, env)
            op = s[2]
            if isinstance(cur, int):           # 可变量：原地更新（避免 phi）
                if op == "=":
                    spec = self.conv_to(fn, spec, self._float_of(fn, spec),
                                        self._float_of(fn, cur))
                    fn.emit("mov", cur, spec)
                    nb = getattr(fn, "narrow_v", {}).get(cur)
                    if nb is not None:
                        fn.emit("trunc", cur, cur, nb[0], nb[1])
                    if self._is_str(fn, spec):
                        self._mark_str(fn, cur)
                    if self._is_nonneg(fn, spec):
                        self._mark_nonneg(fn, cur)
                    else:
                        self._unmark_nonneg(fn, cur)
                else:
                    binop = {"+=": "+", "-=": "-", "*=": "*", "/=": "/", "%=": "%",
                             "&=": "&", "|=": "|", "^=": "^",
                             "<<=": "<<", ">>=": ">>", ">>>=": ">>>"}[op]
                    tmp = self.arith(binop, cur, spec, fn, env)
                    tmp = self.conv_to(fn, tmp, self._float_of(fn, tmp),
                                       self._float_of(fn, cur))
                    fn.emit("mov", cur, tmp)
                    nb = getattr(fn, "narrow_v", {}).get(cur)
                    if nb is not None:
                        fn.emit("trunc", cur, cur, nb[0], nb[1])
                    if self._is_str(fn, tmp):
                        self._mark_str(fn, cur)
                    if binop == "+=" and self._is_nonneg(fn, tmp) and self._is_nonneg(fn, cur):
                        self._mark_nonneg(fn, cur)
                    elif binop == "%=":
                        self._mark_nonneg(fn, cur)
                    else:
                        self._unmark_nonneg(fn, cur)
            else:
                raise SyntaxError("常量不可赋值")
            return
        if k == "foreach":
            self.lower_foreach(s, fn, env)
            return
        if k == "if":
            l_body, l_else, l_end = fn.label("ibody"), fn.label("ielse"), fn.label("iend")
            self.branch(s[1], fn, env, l_body, l_else)
            fn.emit("label", l_body)
            self.block(s[2], fn, dict(env))
            fn.emit("jmp", l_end)
            fn.emit("label", l_else)
            if s[3]:
                self.block(s[3], fn, dict(env))
            fn.emit("label", l_end)
            return
        if k == "while":
            l_top, l_end = fn.label("while"), fn.label("wend")
            fn.emit("label", l_top)
            self.branch(s[1], fn, env, l_body := fn.label("wbody"), l_end)
            fn.emit("label", l_body)
            self.loop_stack.append((l_top, l_end, len(self.defer_stack),
                                    len(self.iface_scope)))   # continue -> 重新判据
            self.block(s[2], fn, dict(env))
            self.loop_stack.pop()
            fn.emit("jmp", l_top)
            fn.emit("label", l_end)
            return
        if k in ("for", "parfor"):
            self.lower_for(s, fn, env, parallel=(k == "parfor"))
            return
        if k == "return":
            if getattr(self, "fn_ret_arr", None):
                if s[1] is None:
                    raise SyntaxError("返回定长数组的函数必须 return 一个数组")
                spec = self.eval(s[1], fn, env)
                n = self._arr_of(fn, spec)
                if n != self.fn_ret_arr[1]:
                    raise SyntaxError("return 的数组长度与函数返回类型不一致")
                self.array_copy(fn, self.fn_ret_target, spec, n)
                self._emit_defers(fn)
                self._emit_drops(fn)      # v1.93：返回前析构本帧 drop 绑定
                self._iface_exit(fn)
                fn.emit("ret", ("imm", 0))
                return
            if self.fn_ret_agg or self.fn_ret_slice:
                if s[1] is None:
                    raise SyntaxError("聚合（结构体/枚举/切片）返回值函数必须 return 一个值")
                spec = self.eval(s[1], fn, env)
                if self.fn_ret_slice:
                    if not self._is_slice(fn, spec):
                        raise SyntaxError("函数返回类型是切片，return 的表达式类型不匹配")
                    self.words_copy(fn, self.fn_ret_target, spec, SLICE_WORDS)
                else:
                    src_n = self._struct_of(fn, spec)
                    if (src_n is not None and src_n != self.fn_ret_agg
                            and self._is_iface(self.fn_ret_agg)):
                        spec = self.box_iface(fn, spec, src_n, self.fn_ret_agg)
                    elif self._struct_of(fn, spec) != self.fn_ret_agg:
                        raise SyntaxError(
                            f"函数返回类型是 {self.fn_ret_agg}，return 的表达式类型不匹配")
                    # 值语义：拷进调用方提供的隐藏出参槽，再返回
                    self.struct_copy(fn, self.fn_ret_target, spec, self.fn_ret_agg)
                    if self._is_iface(self.fn_ret_agg):
                        # 接口返回值：所有权转给调用方（fresh 移动，否则
                        # retain——本帧马上要释放自己的 owned 槽）
                        if spec in fn.iface_fresh:
                            fn.iface_fresh.discard(spec)
                        else:
                            self._iface_retain_slot(fn, self.fn_ret_target)
                self._emit_defers(fn)
                # v1.93：`return a` 把 a 的值移动出去（已拷进调用方出参槽），
                # a 不再析构；其余 drop 绑定照常逆序析构。
                self._return_moved(s[1], fn, env)
                self._emit_drops(fn)
                self._iface_exit(fn)      # v1.81：ret 之前释放本帧接口值
                fn.emit("ret", ("imm", 0))
                return
            if s[1] is None:
                self._emit_defers(fn)
                self._emit_drops(fn)
                self._iface_exit(fn)
                if self.fn_ret == ("named", "void"):
                    # 空 return 也要把 RAX 清零（v1.101）：入口把 main 的 RAX 当退出码，
                    # 否则 `if c { return }` 会带着上一次比较的结果退出（实测 rc=1）。
                    fn.emit("ret", ("imm", 0))
                else:
                    fn.emit("ret", None)
            else:
                v = self.eval(s[1], fn, env)
                v = self.conv_to(fn, v, self._float_of(fn, v),
                                 self._ty_float_w(self.fn_ret) if self.fn_ret[0] == "named" else None)
                nb = self.narrow_of(self.fn_ret)
                if nb is not None:
                    v = self.trunc_to(fn, v, nb)
                # 返回值先算好，再跑 defer（defer 可改局部变量，不改已算出的返回值）。
                # 有 defer 时必须先落一份副本：`return x` 求值拿到的就是 x 的槽，
                # defer 里 `x = ...` 会把同一个槽改掉。
                if any(fr["entries"] for fr in self.defer_stack):
                    snap = fn.new_v()
                    fn.emit("mov", snap, v)
                    v = snap
                self._emit_defers(fn)
                self._return_moved(s[1], fn, env)
                self._emit_drops(fn)
                self._iface_exit(fn)
                fn.emit("ret", v)
            return
        if k == "defer":
            # defer 语句（v1.48）：执行到才登记（标志位置 1），块退出点 LIFO 执行。
            # 只支持表达式/赋值语句——let/if/while 等有作用域与控制流
            # 语义，纳入即变成闭包/块对象问题，fail-fast 拒绝。
            d = s[1]
            if d[0] not in ("expr", "assign", "assign_field", "assign_index"):
                raise SyntaxError(
                    f"defer 只支持表达式/赋值语句，得到 {d[0]!r}")
            if not self.defer_stack:
                raise SyntaxError("defer 只能出现在块内")
            frame = self.defer_stack[-1]
            if frame["cursor"] >= len(frame["slots"]):
                # 块入口的预扫描与降序不一致时才会到这里（内部错误，不静默）
                raise SyntaxError("defer 登记与块入口预扫描不一致（编译器内部错误）")
            flag = frame["slots"][frame["cursor"]]
            frame["cursor"] += 1
            fn.emit("mov", flag, ("imm", 1))
            frame["entries"].append((d, env, flag))
            return
        if k == "expr":
            self.eval(s[1], fn, env)
            return
        if k == "match_stmt":
            self.lower_match(s[1], fn, env, as_expr=False)
            return
        if k == "arena":
            # 块内 __alloc 的 bump 偏移在块末整体回卷（帧级 arena）。
            # 限制：块内 break/continue/return 会跳过 release；块内对象不得逃逸。
            self.uses_arena = True
            mark = fn.new_v()
            fn.emit("call", mark, "__arena_mark", [])
            self.block(s[1], fn, dict(env))
            fn.emit("call", None, "__arena_release", [mark])
            return
        if k == "assign_field":
            self.lower_assign_field(s, fn, env)
            return
        if k == "assign_index":
            self.lower_assign_index(s, fn, env)
            return
        if k == "break":
            if not self.loop_stack:
                raise SyntaxError("break 只能出现在循环内")
            self._emit_defers(fn, upto=self.loop_stack[-1][2])
            # v1.93：跳出循环体时析构体内已绑定的 drop 变量
            self._emit_drops(fn, upto=self.loop_stack[-1][2])
            # v1.81：跳出循环体时释放块内接口值（否则每轮 break 泄漏一箱）
            self._iface_exit(fn, self.loop_stack[-1][3])
            fn.emit("jmp", self.loop_stack[-1][1])
            return
        if k == "continue":
            if not self.loop_stack:
                raise SyntaxError("continue 只能出现在循环内")
            self._emit_defers(fn, upto=self.loop_stack[-1][2])
            self._emit_drops(fn, upto=self.loop_stack[-1][2])
            self._iface_exit(fn, self.loop_stack[-1][3])
            fn.emit("jmp", self.loop_stack[-1][0])
            return
        if k == "block":
            self.block(s[1], fn, dict(env))
            return
        raise SyntaxError(f"原生后端不支持的语句: {s!r}")

    def lower_assign_field(self, s, fn, env):
        """v.x[.y] = 表达式（含 += 等复合赋值）"""
        lhs, op = s[1], s[2]
        addr, segs = self.resolve_field_chain(lhs, fn, env)
        sname = self._struct_of(fn, addr)
        for seg in segs[:-1]:
            off, ftype = self.field_offset(sname, seg)
            if not (ftype and ftype[0] == "named" and self.is_agg(ftype[1])):
                raise SyntaxError(f"{seg} 不是结构体字段，无法继续取 .")
            sub = fn.new_v()
            fn.emit("bin", "add", sub, addr, ("imm", off * 8))
            addr = self._mark_struct(fn, sub, ftype[1])
            sname = ftype[1]
        fname = segs[-1]
        off, ftype = self.field_offset(sname, fname)
        if ftype and ftype[0] == "named" and self.is_agg(ftype[1]):
            if op != "=":
                raise SyntaxError("结构体字段只支持 = 整体赋值")
            spec = self.eval(s[3], fn, env)
            sn = self._struct_of(fn, spec)
            if self._is_iface(ftype[1]) and sn is not None and sn != ftype[1]:
                spec = self.box_iface(fn, spec, sn, ftype[1])   # 隐式装箱（v1.83）
            elif sn != ftype[1]:
                raise SyntaxError("结构体赋值两侧类型不一致")
            sub = fn.new_v()
            fn.emit("bin", "add", sub, addr, ("imm", off * 8))
            self._mark_struct(fn, sub, ftype[1])
            self.struct_copy(fn, sub, spec, ftype[1])
            if self._is_iface(ftype[1]):
                # 接口字段没有 Drop：元素随结构体走，这里只保证不悬垂（v1.81）
                self._iface_share(fn, sub, spec)
            return
        if ftype and ftype[0] == "slice":
            # 切片字段赋值（v1.39）：2 字整体拷；复合赋值（+= 等）无意义，拒绝
            if op != "=":
                raise SyntaxError("切片字段只支持 = 整体赋值")
            spec = self.eval(s[3], fn, env)
            if not self._is_slice(fn, spec):
                raise SyntaxError("切片字段赋值两侧类型不一致")
            sub = fn.new_v()
            fn.emit("bin", "add", sub, addr, ("imm", off * 8))
            self.words_copy(fn, sub, spec, SLICE_WORDS)
            return
        spec = self.eval(s[3], fn, env)
        nb = self.narrow_of(ftype)
        if op == "=":
            spec = self.conv_to(fn, spec, self._float_of(fn, spec), self._ty_float_w(ftype))
            if nb is not None:
                spec = self.trunc_to(fn, spec, nb)   # 窄字段赋值截断（v1.40）
            fn.emit("store", addr, ("imm", off), spec)
            return
        binop = {"+=": "+", "-=": "-", "*=": "*", "/=": "/", "%=": "%"}[op]
        cur = fn.new_v()
        fn.emit("load", cur, addr, ("imm", off))
        fw = self._ty_float_w(ftype)
        if fw:
            self._mark_float(fn, cur, fw)
        tmp = self.arith(binop, cur, spec, fn, env)
        tmp = self.conv_to(fn, tmp, self._float_of(fn, tmp), fw)
        if nb is not None:
            tmp = self.trunc_to(fn, tmp, nb)         # 窄字段复合赋值也截断（v1.40）
        fn.emit("store", addr, ("imm", off), tmp)

    def lower_assign_index(self, s, fn, env):
        """a[i] = v / a[i] += v（越界 fail-fast）；定长数组与切片通用"""
        base, idxe, op, rhs = s[1], s[2], s[3], s[4]
        obj = self.eval(base, fn, env)
        n = self._arr_of(fn, obj)
        if n is not None:
            tgt, nval, dyn = obj, n, False
        elif self._is_slice(fn, obj):
            # 切片：写入落到底层元素序列（零拷贝别名）
            tgt = self.slice_ptr(fn, obj)
            nval, dyn = self.slice_len(fn, obj), True
        else:
            raise SyntaxError("下标赋值只能用于定长数组或切片")
        idx = self.eval(idxe, fn, env)
        self.emit_bounds(fn, idx, nval, dynamic=dyn)
        val = self.eval(rhs, fn, env)
        nb = self.arr_narrow.get(obj)     # 窄元素数组（v1.40）：存槽截断
        if nb is None and self._is_slice(fn, obj):
            # v1.56：切片别名写入也按元素声明宽度截断（此前只跟踪 str 元素，
            # `slice_of(a)` 之后 s[i] = 300 会把 300 原样写进 u8 元素槽）
            se = self._slice_elem(fn, obj)
            if se is not None and se != "str":
                nb = self.narrow_of(("named", se))
        if op == "=":
            if nb is not None:
                val = self.trunc_to(fn, val, nb)
            fn.emit("store", tgt, idx, val)
            return
        binop = {"+=": "add", "-=": "sub", "*=": "mul",
                 "/=": "div", "%=": "mod"}[op]
        cur = fn.new_v()
        fn.emit("load", cur, tgt, idx)
        fn.emit("bin", binop, cur, cur, val)
        if nb is not None:
            fn.emit("trunc", cur, cur, nb[0], nb[1])
        fn.emit("store", tgt, idx, cur)

    def _emit_defers(self, fn, upto=None):
        """defer 清理（v1.48）：从最内层帧起 LIFO 发射。upto=帧深度下界
        （break/continue 只跑循环体帧，函数帧留到 return/函数尾）。"""
        frames = self.defer_stack if upto is None else self.defer_stack[upto:]
        for frame in reversed(frames):
            self._emit_frame(frame, fn)

    def _emit_frame(self, frame, fn):
        """一帧的 defer：LIFO，逐条"标志位为 1 才执行"。

        标志位是语义必需，不是优化：`if c { break }` 写在 defer 之前时，
        那条路径上 defer 根本没执行过，不能跑。
        """
        for dstmt, denv, flag in reversed(frame["entries"]):
            skip = fn.label("dskip")
            fn.emit("jcc", "e", flag, ("imm", 0), skip)
            self.stmt(dstmt, fn, denv)
            fn.emit("label", skip)

    # ---- v1.93 Drop：作用域退出析构 ----
    # 语义（与 02-language §8.7 对齐）：
    #   * 只对 **let 绑定的聚合变量**（struct/enum 且 `impl T : Drop`）生效；
    #     形参、容器元素、字段、临时值都不析构——宁可泄漏，不可悬垂。
    #   * 退出点：块正常结束、return、break/continue 跳出该块；同块内**逆序**
    #     （后绑定的先析构），并且**在 defer 之后**跑（defer 里可能还在用变量）。
    #   * `let b = a` / `return a` 是**移动**：析构责任随值转移，a 不再析构。
    #   * 析构函数直接收到**对象地址**（不经 lower_call 的值拷贝），因此
    #     析构体里的写入（如 `f.fd = -1`）落在原对象上。
    def _has_drop(self, sname):
        return sname in self.drop_fns

    def emit_drop(self, fn, slot, sname):
        """发一次析构调用。直接 emit call（不走 lower_call）：聚合实参在
        lower_call 里会被拷进临时槽，析构就只能改到副本。"""
        fn.emit("call", None, self.drop_fns[sname], [slot])

    def _emit_drops(self, fn, upto=None):
        """upto=None 表示本帧所有块帧（return）；否则只跑 depth >= upto 的帧
        （break/continue 只跑循环体内的）。"""
        frames = self.drop_stack if upto is None else self.drop_stack[upto:]
        for frame in reversed(frames):
            for slot, sname in reversed(frame):
                self.emit_drop(fn, slot, sname)

    def _drop_register(self, slot, sname):
        """let 绑定登记：块退出时按逆序析构。"""
        if self.drop_stack:
            self.drop_stack[-1].append((slot, sname))

    def _drop_forget(self, slot):
        """值被移动出去（`let b = a` / `return a`）：撤销 a 的析构责任。
        找不到（a 本来就不是 drop 绑定）时静默返回。"""
        for frame in self.drop_stack:
            for i in range(len(frame) - 1, -1, -1):
                if frame[i][0] == slot:
                    del frame[i]
                    return True
        return False

    def _return_moved(self, expr, fn, env):
        """`return x`（x 是 drop 绑定）：值已拷进调用方出参槽/寄存器，
        责任随值转移，本帧不再析构 x。"""
        if isinstance(expr, tuple) and expr and expr[0] == "name":
            slot = env.get(expr[1])
            if isinstance(slot, int):
                self._drop_forget(slot)

    def block(self, stmts, fn, env):
        """块：入口给块内每条 defer 分配"已登记"标志（初始 0），
        正常落到块尾时按 LIFO 逐条判断执行。"""
        frame = {"slots": [], "entries": [], "cursor": 0}
        for s in stmts:
            if s[0] == "defer":
                flag = fn.new_v()
                fn.emit("mov", flag, ("imm", 0))
                frame["slots"].append(flag)
        self.defer_stack.append(frame)
        self.drop_stack.append([])         # v1.93：与 defer 帧同进同出
        self.iface_scope.append([])        # v1.81：块内 let 的接口槽
        for s in stmts:
            self.stmt(s, fn, env)
        self.defer_stack.pop()
        self._emit_frame(frame, fn)
        # v1.93：块内 drop 绑定按逆序析构。位置在 defer 之后（defer 里可能
        # 还在用这些变量），接口槽释放之前（析构体里可能还在用接口值）。
        for slot, sname in reversed(self.drop_stack.pop()):
            self.emit_drop(fn, slot, sname)
        # 接口槽按 LIFO 释放（defer 之后：defer 里可能还在用这些变量）
        for slot in reversed(self.iface_scope.pop()):
            self._iface_release_slot(fn, slot)

    # ---- for / parfor ----
    def lower_foreach(self, s, fn, env):
        """for x in <map|vec>：遍历。
        - map：按桶序（实现相关但稳定），只产出【键】；需要值时用 m.get(k)
        - vec：按下标序
        顺序在 SPEC 里明确写为"实现定义"，测试只依赖集合内容不依赖顺序。
        """
        _, var, coll_e, body = s
        coll = self.eval(coll_e, fn, env)
        idx = fn.new_v()
        fn.emit("mov", idx, ("imm", 0))
        item = fn.new_v()
        l_top, l_body, l_end = fn.label("fe.t"), fn.label("fe.b"), fn.label("fe.e")
        l_skip = fn.label("fe.s")

        mp = self._map_of(fn, coll)
        if mp is not None:
            self.uses_map = True
            cap = fn.new_v()
            st = fn.new_v()
            kt = fn.new_v()
            fn.emit("load", cap, coll, ("imm", 0))       # 桶数
            fn.emit("load", st, coll, ("imm", 4))        # state 字节数组
            fn.emit("load", kt, coll, ("imm", 5))        # 键数组
            b = fn.new_v()
            fn.emit("label", l_top)
            fn.emit("cmpset", "ge", b, idx, cap)
            fn.emit("jnz", b, l_end)
            sv = fn.new_v()
            fn.emit("load", sv, st, idx)          # state 是 8 字节槽（见 __map_set）
            fn.emit("cmpset", "ne", b, sv, ("imm", 1))
            fn.emit("jnz", b, l_skip)
            fn.emit("load", item, kt, idx)
            l_body = fn.label("fe.b2")
            fn.emit("label", l_body)
        else:
            vec = self._is_vec(fn, coll)
            if not vec:
                raise SyntaxError("for x in ... 只支持 map 与 vec（区间循环用 a..b）")
            self.uses_vec = True
            data = fn.new_v()
            ln = fn.new_v()
            fn.emit("load", data, coll, ("imm", 0))
            fn.emit("load", ln, coll, ("imm", 1))
            b = fn.new_v()
            fn.emit("label", l_top)
            fn.emit("cmpset", "ge", b, idx, ln)
            fn.emit("jnz", b, l_end)
            fn.emit("load", item, data, idx)
            l_body = fn.label("fe.b3")
            fn.emit("label", l_body)

        if mp is not None:
            elem = "str" if mp[0] == "str" else None      # 键类型
        else:
            elem = self._vec_elem(fn, coll)
        if elem == "str":
            self._mark_str(fn, item)
        elif isinstance(elem, tuple) and elem[0] == "agg":
            # 聚合元素：每轮把第 idx 个元素拷进一个帧槽，循环变量绑到这个槽
            slot = self.alloc_struct(fn, elem[1])
            fn.emit("call", None, "__vec_get_n", [coll, idx, slot])
            item = self._mark_struct(fn, slot, elem[1])
        elif isinstance(elem, tuple) and elem[0] == "vecinner":
            # 嵌套 vec（v1.37 补漏）：循环变量是内层 vec 句柄，重挂标签
            self._mark_vec(fn, item, elem[1])
        elif isinstance(elem, tuple) and elem[0] == "mapinner":
            # vec[map]（v1.37）：循环变量是 map 句柄，重挂 map 标记
            self._mark_map(fn, item, elem[1], elem[2])
        inner = dict(env)
        inner[var] = item
        self.loop_stack.append((l_skip, l_end, len(self.defer_stack),
                                len(self.iface_scope)))
        self.block(body, fn, inner)
        self.loop_stack.pop()
        fn.emit("label", l_skip)
        fn.emit("bin", "add", idx, idx, ("imm", 1))
        fn.emit("jmp", l_top)
        fn.emit("label", l_end)

    def lower_simd_for(self, s, fn, env):
        """@simd for i in lo..hi { acc += a[i] } -> SSE2 paddq 归约。

        识别范围（故意窄，宁可报错也不静默降级）：
          * 累加形式 `acc = acc + a[i]` 或 `acc += a[i]`；
          * 点积形式 `acc += a[i] * b[i]`（v1.60 f64 / v1.81 int）；
          * a 是 `[N]int` / `[N]f64` 定长数组（连续 8 字节元素），下标就是循环变量；
          * 循环体只有这一条语句。
        语义差异（写进 SPEC，必须知道）：
          * 逐元素越界检查被跳过 —— 调用方保证 lo/hi 落在 [0, len(a)]；
          * 整数溢出按 64 位补码回绕（与标量版本一致）；
          * 点积要求两数组同长、且与累加器同类型（全 int 或全 f64）。
        """
        _, var, lo_e, hi_e, body = s
        rhs = acc = None
        dot = False
        dot_f = False
        arr2_e = None
        if len(body) == 1 and body[0][0] == "assign":
            b = body[0]
            if b[2] == "+=":
                acc, rhs = b[1], b[3]
            elif b[2] == "=" and b[3][0] == "binop" and b[3][1] == "+":
                lhs, r2 = b[3][2], b[3][3]
                if lhs == ("name", b[1]):
                    acc, rhs = b[1], r2
                elif r2 == ("name", b[1]):
                    acc, rhs = b[1], lhs
        if acc is None or rhs is None:
            raise SyntaxError(
                "@simd 只支持 `acc = acc + a[i]` / `acc += a[i]` / "
                "`acc += a[i] * b[i]`（点积）形式的归约（见 docs/LANG.md §@simd）")
        if rhs[0] == "index":
            arr_e, idx_e = rhs[1], rhs[2]
            if arr_e[0] != "name" or idx_e != ("name", var):
                raise SyntaxError("@simd 要求下标正好是循环变量，数组是具名数组")
        elif rhs[0] == "binop" and rhs[1] == "*":
            # 点积形状（v1.60）：acc += a[i] * b[i]，两个 [N]f64
            la, lb = rhs[2], rhs[3]
            if (la[0] != "index" or lb[0] != "index"
                    or la[2] != ("name", var) or lb[2] != ("name", var)
                    or la[1][0] != "name" or lb[1][0] != "name"):
                raise SyntaxError(
                    "@simd 点积要求 `a[i] * b[i]`：两个下标都正好是循环变量、数组具名")
            arr_e, arr2_e, idx_e = la[1], lb[1], la[2]
            dot = True
        else:
            raise SyntaxError(
                "@simd 只支持 `acc = acc + a[i]` / `acc += a[i]` / "
                "`acc += a[i] * b[i]`（点积）形式的归约（见 docs/LANG.md §@simd）")
        if acc not in env or arr_e[1] not in env or (dot and arr2_e[1] not in env):
            raise SyntaxError("@simd 归约变量/数组未定义")
        base = env[arr_e[1]]
        n = self._arr_of(fn, base)
        if n is None:
            raise SyntaxError("@simd 目前只支持定长数组 [N]int（切片/vec 见 GAPS）")
        if dot:
            base2 = env[arr2_e[1]]
            n2 = self._arr_of(fn, base2)
            if n2 is None or n2 != n:
                raise SyntaxError("@simd 点积要求两个数组是同长度定长数组")
            # 类型必须三者一致（全 f64 或全整数）：混着写说明用户以为会做
            # 隐式转换，而 SIMD 段不做转换——静默按位相乘就是错的。
            fa = self.arr_elem.get(base) == "f64"
            fb = self.arr_elem.get(base2) == "f64"
            facc = self._float_of(fn, env[acc]) == "f64"
            if not (fa == fb == facc):
                raise SyntaxError(
                    "@simd 点积要求两个数组与累加器同类型（全 f64 或全整数）")
            dot_f = fa
        lo = self.eval(lo_e, fn, env)
        hi = self.eval(hi_e, fn, env)
        # 静态越界：常量区间直接查
        if isinstance(lo, tuple) and lo[0] == "imm" and isinstance(hi, tuple) and hi[0] == "imm":
            if lo[1] < 0 or hi[1] > n or lo[1] > hi[1]:
                raise SyntaxError(f"@simd 区间 {lo[1]}..{hi[1]} 超出数组长度 {n}")
        cnt = fn.new_v()
        fn.emit("bin", "sub", cnt, hi, lo)
        ptr = fn.new_v()
        fn.emit("bin", "shl", ptr, lo, ("imm", 3))
        fn.emit("bin", "add", ptr, ptr, base)
        cur = env[acc]
        if dot:
            # 点积（v1.60 f64 / v1.81 int）：两个基址各自偏移 lo*8
            ptr2 = fn.new_v()
            fn.emit("bin", "shl", ptr2, lo, ("imm", 3))
            fn.emit("bin", "add", ptr2, ptr2, base2)
            part = fn.new_v()
            fn.emit("vdotd" if dot_f else "vdot", part, ptr, ptr2, cnt)
            if dot_f:
                self._mark_float(fn, part, "f64")
        elif self.arr_elem.get(base) == "f64" and self._float_of(fn, cur) == "f64":
            # f64 归约（v1.16）：acc += a[i]，a 是 [N]f64（acc 的 float
            # 标记即契约——调用方保证数组元素类型一致）。
            part = fn.new_v()
            fn.emit("vsumd", part, ptr, cnt)
            self._mark_float(fn, part, "f64")
        else:
            part = fn.new_v()
            fn.emit("vsum", part, ptr, cnt)
        tot = self.arith("+", cur, part, fn, env)
        fn.emit("mov", cur, tot)
        # 循环变量在 @simd 后不可见（与 for 的作用域一致：块内绑定）

    def lower_for(self, s, fn, env, parallel):
        _, var, lo_e, hi_e, body = s
        lo = self.eval(lo_e, fn, env)
        hi = self.eval(hi_e, fn, env)
        if parallel:
            self.lower_parfor(var, lo, hi, body, fn, env)
            return
        if getattr(self, "fn_simd", False):
            # @simd 函数：能向量化就向量化，形状不匹配静默回落标量
            try:
                self.lower_simd_for(s, fn, env)
                return
            except SyntaxError:
                pass
        i = fn.new_v()
        fn.emit("mov", i, lo)
        hi_v = fn.new_v()
        fn.emit("mov", hi_v, hi)
        l_top, l_body, l_end = fn.label("for"), fn.label("fbody"), fn.label("fend")
        l_cont = fn.label("fcont")
        fn.emit("label", l_top)
        fn.emit("jcc", "ge", i, hi_v, l_end)
        fn.emit("label", l_body)
        env2 = dict(env)
        env2[var] = i
        self.loop_stack.append((l_cont, l_end, len(self.defer_stack),
                                len(self.iface_scope)))      # continue -> 自增步
        self.block(body, fn, env2)
        self.loop_stack.pop()
        fn.emit("label", l_cont)
        fn.emit("bin", "add", i, i, ("imm", 1))
        fn.emit("jmp", l_top)
        fn.emit("label", l_end)

    def lower_parfor(self, var, lo, hi, body, fn, env):
        """多核：raw clone() 派生 worker -> 共享内存归约 -> wait4() join
        v0.1 约束：边界为编译期常量、仅支持 += 归约变量（避免共享可变量竞态）"""
        if not (isinstance(lo, tuple) and lo[0] == "imm" and
                isinstance(hi, tuple) and hi[0] == "imm"):
            raise SyntaxError("原生后端 parfor v0.1 要求区间为编译期常量")
        if not self.cfg["core"]["multicore"] or int(self.cfg["core"]["threads"] or 0) == 1:
            # 单核降级（Quelmara.toml [core] multicore=false）：确定性串行
            i = fn.new_v()
            fn.emit("mov", i, lo)
            hi_v = fn.new_v()
            fn.emit("mov", hi_v, hi)
            l_top, l_end = fn.label("seqfor"), fn.label("seqfore")
            l_cont = fn.label("seqcont")
            fn.emit("label", l_top)
            fn.emit("jcc", "ge", i, hi_v, l_end)
            env2 = dict(env)
            env2[var] = i
            self.loop_stack.append((l_cont, l_end, len(self.defer_stack),
                                len(self.iface_scope)))
            self.block(body, fn, env2)
            self.loop_stack.pop()
            fn.emit("label", l_cont)
            fn.emit("bin", "add", i, i, ("imm", 1))
            fn.emit("jmp", l_top)
            fn.emit("label", l_end)
            return

        # 归约变量识别
        declared, assigned, referenced = set(), set(), set()
        walk_stmts(body, declared, assigned, referenced)
        declared.add(var)
        reds = sorted((assigned & referenced) - declared)
        for r in reds:
            if self._assign_op(body, r) != "+=":
                raise SyntaxError(f"parfor 外部变量 {r} 仅支持 += 归约")
        if not reds:
            raise SyntaxError("parfor v0.1 需要至少一个 += 归约变量")

        T = int(self.cfg["core"]["threads"]) or (os.cpu_count() or 1)
        out_gid = self.intern_array(T)
        pid_gid = self.intern_array(T)

        # 按线程分块：线程 t 负责 [lo + t*chunk, min(hi, lo + (t+1)*chunk))
        span = hi[1] - lo[1]
        chunk = (span + T - 1) // T

        # worker 函数
        wname = f"__pf_{fn.name}_{fn.label_id}_{len(self.out)}"
        w = Fn(wname)
        # worker 在 clone() 出来的【另一个栈】上运行：一旦被内联进父函数，
        # 其溢出槽 / 结构体帧槽就会落到父栈帧上，子线程写进去直接砸坏父线程
        # 的活跃值（已踩坑：struct + parfor 同函数时归约结果错乱）。
        w.no_inline = True
        p_lo, p_hi, p_out, p_tid = w.new_v(), w.new_v(), w.new_v(), w.new_v()
        w.emit("args", [p_lo, p_hi, p_out, p_tid])
        accs = {}
        for r in reds:
            accs[r] = w.new_v()
            w.emit("mov", accs[r], ("imm", 0))
        i = w.new_v()
        w.emit("mov", i, p_lo)
        l_top, l_end = w.label("pt"), w.label("pe")
        l_cont = w.label("pc")
        w.emit("label", l_top)
        w.emit("jcc", "ge", i, p_hi, l_end)
        env2 = dict(env)
        env2[var] = i
        for r in reds:
            env2[r] = accs[r]
        self.loop_stack.append((l_cont, l_end, len(self.defer_stack),
                                len(self.iface_scope)))
        self.block(body, w, env2)
        self.loop_stack.pop()
        w.emit("label", l_cont)
        w.emit("bin", "add", i, i, ("imm", 1))
        w.emit("jmp", l_top)
        w.emit("label", l_end)
        for r in reds:
            w.emit("store", p_out, p_tid, accs[r])
        w.emit("ret", ("imm", 0))
        self.out.append(w)

        # 派生 + join（父线程侧）
        if self.platform == "windows":
            # Win32 线程入口是 DWORD (*)(LPVOID)：包一层，参数从全局数组取
            arg_gid = self.intern_array(4 * T)
            handle_gid = self.intern_array(T)
            wrap = Fn(wname + "__entry")
            wrap.win_thread = True          # Win64 ThreadProc：参数在 RCX，且须保存 RDI/RSI
            wp = wrap.new_v()
            wrap.emit("winargs", [wp])
            wa = [wrap.new_v() for _ in range(4)]
            for k in range(4):
                wrap.emit("load", wa[k], wp, ("imm", k))
            wrap.emit("call", None, wname, wa)
            wrap.emit("ret", ("imm", 0))
            self.out.append(wrap)
            for t in range(T):
                t_lo = lo[1] + t * chunk
                t_hi = min(hi[1], lo[1] + (t + 1) * chunk)
                base = 4 * t
                fn.emit("store", ("ga", arg_gid), ("imm", base + 0), ("imm", t_lo))
                fn.emit("store", ("ga", arg_gid), ("imm", base + 1), ("imm", t_hi))
                fn.emit("store", ("ga", arg_gid), ("imm", base + 2), ("ga", out_gid))
                fn.emit("store", ("ga", arg_gid), ("imm", base + 3), ("imm", t))
                ap = fn.new_v()
                fn.emit("movaddr", ap, arg_gid)
                if t:
                    fn.emit("bin", "add", ap, ap, ("imm", 32 * t))
                h = fn.new_v()
                fn.emit("winapi", h, "CreateThread",
                        [("imm", 0), ("imm", 0), ("fnaddr", wrap.name), ap,
                         ("imm", 0), ("imm", 0)])
                fn.emit("store", ("ga", handle_gid), ("imm", t), h)
            for t in range(T):
                hv = fn.new_v()
                fn.emit("load", hv, ("ga", handle_gid), ("imm", t))
                fn.emit("winapi", None, "WaitForSingleObject", [hv, ("imm", -1)])
                fn.emit("winapi", None, "CloseHandle", [hv])
        else:
            for t in range(T):
                st = fn.new_v()
                fn.emit("syscall", st, self.sc["mmap"], [("imm", 0), ("imm", STACK_SZ), ("imm", PROT_RW),
                                           ("imm", MAP_PRIVATE_ANON), ("imm", -1), ("imm", 0)])
                top = fn.new_v()
                fn.emit("bin", "add", top, st, ("imm", STACK_SZ - 256))
                pid = fn.new_v()
                fn.emit("syscall", pid, self.sc["clone"], [("imm", CLONE_FLAGS), top, ("imm", 0),
                                             ("imm", 0), ("imm", 0), ("imm", 0)])
                # v2.98：**pid 的登记必须在父子分流之后、只在父路径上**。
                # clone 返回后父子从同一条指令流继续跑——分流前的任何 store
                # 子线程也会执行一份，而它的 pid 是 0。CLONE_VM 下 pid_gid 是
                # 共享内存：子线程晚到的 `store pid_gid[t]=0` 会抹掉父写的真 pid。
                # 之后 join 对该槽 wait4(0)（通配）收走的是**先退的那个别的 worker**，
                # 轮到它自己的槽时已无人在等——归并读到一个还在跑的 worker 的
                # out 槽（0），结果正好少一个分片。实测 parfor_sum 复现 ~2/60，
                # 缺的值 = 恰好一个 chunk 的和；与内联阈值无关（th28 同复现率）。
                l_child, l_after = fn.label("child"), fn.label("after")
                fn.emit("jz", pid, l_child)
                fn.emit("jmp", l_after)
                fn.emit("label", l_child)
                t_lo = lo[1] + t * chunk
                t_hi = min(hi[1], lo[1] + (t + 1) * chunk)
                fn.emit("call", None, wname,
                        [("imm", t_lo), ("imm", t_hi), ("ga", out_gid), ("imm", t)])
                fn.emit("syscall", None, self.sc["exit"], [("imm", 0), ("imm", 0), ("imm", 0),
                                              ("imm", 0), ("imm", 0), ("imm", 0)])
                fn.emit("label", l_after)
                fn.emit("store", ("ga", pid_gid), ("imm", t), pid)
            # join
            for t in range(T):
                pidv = fn.new_v()
                fn.emit("load", pidv, ("ga", pid_gid), ("imm", t))
                fn.emit("syscall", None, self.sc["wait4"], [pidv, ("imm", 0), ("imm", 0),
                                              ("imm", 0), ("imm", 0), ("imm", 0)])
        # 归约合并
        for r in reds:
            for t in range(T):
                slot = fn.new_v()
                fn.emit("load", slot, ("ga", out_gid), ("imm", t))
                fn.emit("bin", "add", env[r], env[r], slot)

    def _assign_op(self, stmts, name):
        for s in stmts:
            if s[0] == "assign" and s[1] == name:
                return s[2]
            if s[0] == "if":
                for blk in (s[2], s[3] or []):
                    r = self._assign_op(blk, name)
                    if r:
                        return r
            if s[0] == "while":
                r = self._assign_op(s[2], name)
                if r:
                    return r
            if s[0] in ("for", "parfor"):
                r = self._assign_op(s[4], name)
                if r:
                    return r
        return None

    # ---- 函数 ----
    def lower_fn(self, f):
        fn = Fn(f["name"])
        # v1.62 调试信息：只有主文件定义的函数配源码行号（import 的库函数
        # 行号属于别的文件，本版不给——调试器对这些帧显示 <library>）。
        # 路径统一成正斜杠：Windows 上传入的可能是反斜杠，调试器按正斜杠
        # 做后缀匹配（basename 比较不受影响，endswith 会）
        fn.dbg_file = (self.dbg_src.replace("\\", "/")
                       if (self.dbg and f["name"] in self.dbg_main)
                       else None)
        anns = [a for a, _ in f.get("annots", [])]
        self.no_preempt = "no_preempt" in anns
        fn.no_preempt = self.no_preempt
        self.fn_simd = "simd" in anns
        if f.get("body"):
            self.check_ownership(f)
        fn.strv = set()
        fn.boolv = set()
        self.fn_ret_agg = None
        self.fn_ret_target = None
        self.fn_ret_slice = False
        self.fn_ret_arr = None
        ret = f["ret"]
        if ret[0] == "slice":
            # 切片返回值：同聚合 ABI（隐藏出参指针作第一参数）
            self.fn_ret_slice = True
            self.fn_ret_target = fn.new_v()
        elif ret[0] == "named" and self.is_agg(ret[1]):
            # 聚合返回值：ABI = 隐藏出参指针作第一参数（发射层零改动）
            self.fn_ret_agg = ret[1]
            self.fn_ret_target = fn.new_v()
        elif ret[0] == "array":
            # 定长数组返回值：隐藏出参指针（调用方开 N 字帧槽，callee 拷入）
            self.fn_ret_arr = ret
            self.fn_ret_target = fn.new_v()
        params = [fn.new_v() for _ in f["params"]]
        if self.fn_ret_agg or self.fn_ret_slice or self.fn_ret_arr:
            fn.emit("args", [self.fn_ret_target] + params)
            if self.fn_ret_agg:
                self._mark_struct(fn, self.fn_ret_target, self.fn_ret_agg)
            else:
                self._mark_slice(fn, self.fn_ret_target)
        else:
            fn.emit("args", params)
        env = {name: params[i] for i, (name, _) in enumerate(f["params"])}
        # 宽度形参在入口截断：调用方给的 64 位值可能是任意值（如 u8 收 300）
        if not hasattr(fn, "narrow_v"):
            fn.narrow_v = {}
        for i, (name, ty) in enumerate(f["params"]):
            nb = self.narrow_of(ty)
            if nb is not None:
                fn.emit("trunc", params[i], params[i], nb[0], nb[1])
                fn.narrow_v[params[i]] = nb
        for i, (name, ty) in enumerate(f["params"]):
            if ty == ("named", "str"):
                fn.strv.add(params[i])
            elif self._ty_float_w(ty):
                self._mark_float(fn, params[i], self._ty_float_w(ty))
            elif ty[0] == "chan":
                self._mark_chan(fn, params[i])
            elif ty[0] == "map":
                self._mark_map(fn, params[i], ty[1][1], ty[2][1])
            elif ty[0] == "slice":
                # v1.56：元素标签带全（str / 窄类型 / f64）——切片形参内部写入
                # 也要按声明宽度截断，否则调用方数组会被写进超宽值
                et = ty[1][1] if ty[1][0] == "named" else None
                self._mark_slice(fn, params[i], et)
            elif ty[0] == "rc":
                self._mark_rc(fn, params[i], ty[1][1])
                self._mark_struct(fn, params[i], ty[1][1])
            elif ty[0] == "vec":
                self._mark_vec(fn, params[i], self._vec_tag_of(ty[1]))
            elif ty[0] == "array":
                # 数组形参按值语义：就地拷一份，函数内改动不外泄；
                # 窄元素按声明宽度截断（v1.40）
                dst = self.alloc_array(fn, ty[1])
                nb = self._arr_narrow_of(ty)
                self.array_copy(fn, dst, params[i], ty[1], nb=nb)
                env[name] = dst
                if nb is not None:
                    self.arr_narrow[dst] = nb
                    self.arr_elem[dst] = ty[2][1]
                if len(ty) > 2 and "f64" in str(ty[2]):
                    self.arr_elem[dst] = "f64"
            elif ty[0] == "array":
                self._mark_arr(fn, params[i], ty[1])
            elif ty[0] == "named" and self.is_agg(ty[1]):
                # 聚合形参：实参侧传入的是【副本地址】，值语义成立
                self._mark_struct(fn, params[i], ty[1])
        self.fn_ret = f["ret"]
        # v1.95 闭包：捕获环境在 __env__（形参 0）里，按固定下标 load 回来
        # 并重新打类型标记——此后体内对捕获名的处理与普通局部变量完全一致。
        caps = f.get("captures") or []
        if caps:
            envp = params[0]
            for i, (cname, ctag) in enumerate(caps):
                v = fn.new_v()
                fn.emit("load", v, envp, ("imm", i))
                self._apply_capture_tag(fn, v, ctag)
                env[cname] = v
        if self.dbg:
            # 形参绑定标记：入口处即可查看（数组形参 env 已指向拷贝后的槽）
            for name, _ty in f["params"]:
                self._dbg_bind_param(fn, name, env[name])
        self.block(f["body"], fn, env)
        fn.emit("ret", ("imm", 0))     # 兜底返回
        self.out.append(fn)
        return fn

    # ---- 自举运行库（print/itoa，全部 QuIR + raw syscall）----
    def lower_runtime(self):
        gid_nl = self.intern(b"\n\x00")
        gid_minus = self.intern(b"-\x00")
        gid_true = self.intern(b"true\x00")
        gid_false = self.intern(b"false\x00")

        # __print_cstr(ptr): write(1, ptr, len) + "\n"
        f = Fn("__print_cstr")
        p = f.new_v()
        f.emit("args", [p])
        i = f.new_v()
        f.emit("mov", i, ("imm", 0))
        l_top, l_end = f.label("len"), f.label("lene")
        f.emit("label", l_top)
        ch = f.new_v()
        f.emit("load8", ch, p, i)
        f.emit("jz", ch, l_end)
        f.emit("bin", "add", i, i, ("imm", 1))
        f.emit("jmp", l_top)
        f.emit("label", l_end)
        self.emit_write(f, 1, p, i)
        nl = f.new_v()
        f.emit("movaddr", nl, gid_nl)
        self.emit_write(f, 1, nl, ("imm", 1))
        f.emit("ret", ("imm", 0))
        self.out.append(f)

        # __str_eq(a, b): 字节级内容比较（字符串一等类型的 == / != 语义）
        # v1.5.1 长度前缀：先比长度（快速拒绝），再逐字节；嵌入 NUL 也正确
        f = Fn("__str_eq")
        pa, pb = f.new_v(), f.new_v()
        f.emit("args", [pa, pb])
        la, lb = f.new_v(), f.new_v()
        f.emit("call", la, "__str_len", [pa])
        f.emit("call", lb, "__str_len", [pb])
        l_diff = f.label("sdiff")
        f.emit("jcc", "ne", la, lb, l_diff)
        i = f.new_v()
        f.emit("mov", i, ("imm", 0))
        l_top, l_same = f.label("seq"), f.label("ssame")
        f.emit("label", l_top)
        f.emit("jcc", "ge", i, la, l_same)
        ca, cb = f.new_v(), f.new_v()
        f.emit("load8", ca, pa, i)
        f.emit("load8", cb, pb, i)
        f.emit("jcc", "ne", ca, cb, l_diff)
        f.emit("bin", "add", i, i, ("imm", 1))
        f.emit("jmp", l_top)
        f.emit("label", l_diff)
        f.emit("ret", ("imm", 0))
        f.emit("label", l_same)
        f.emit("ret", ("imm", 1))
        self.out.append(f)

        # __print_i64(v): 自举 itoa（栈下标递减写全局缓冲）
        f = Fn("__print_i64")
        v = f.new_v()
        f.emit("args", [v])
        buf_gid = self.intern_array(4)          # 32 字节缓冲
        buf = f.new_v()
        f.emit("movaddr", buf, buf_gid)
        # 负数处理：先写 '-'，再对绝对值做 itoa
        l_pos = f.label("pos")
        f.emit("jcc", "ge", v, ("imm", 0), l_pos)
        minus_addr = f.new_v()
        f.emit("movaddr", minus_addr, gid_minus)
        self.emit_write(f, 1, minus_addr, ("imm", 1))
        f.emit("neg", v, v)
        f.emit("label", l_pos)
        pos = f.new_v()
        f.emit("mov", pos, ("imm", 29))
        l_dig, l_dige = f.label("dig"), f.label("dige")
        f.emit("label", l_dig)
        q10, chv = _emit_divmod10c(f, v, ord("0"))
        f.emit("store8", buf, pos, chv)
        f.emit("bin", "sub", pos, pos, ("imm", 1))
        f.emit("mov", v, q10)
        f.emit("jnz", v, l_dig)
        f.emit("label", l_dige)
        # write(1, buf+pos+1, 29-pos)
        ptr = f.new_v()
        f.emit("bin", "add", ptr, buf, pos)
        f.emit("bin", "add", ptr, ptr, ("imm", 1))
        ln = f.new_v()
        f.emit("mov", ln, ("imm", 29))
        f.emit("bin", "sub", ln, ln, pos)
        self.emit_write(f, 1, ptr, ln)
        nl2 = f.new_v()
        f.emit("movaddr", nl2, gid_nl)
        self.emit_write(f, 1, nl2, ("imm", 1))
        f.emit("ret", ("imm", 0))
        self.out.append(f)

        # __print_bool(v)
        f = Fn("__print_bool")
        v = f.new_v()
        f.emit("args", [v])
        l_f, l_e = f.label("pf"), f.label("pe")
        f.emit("jz", v, l_f)
        t_addr = f.new_v()
        f.emit("movaddr", t_addr, gid_true)
        f.emit("call", None, "__print_cstr", [t_addr])
        f.emit("jmp", l_e)
        f.emit("label", l_f)
        f_addr = f.new_v()
        f.emit("movaddr", f_addr, gid_false)
        f.emit("call", None, "__print_cstr", [f_addr])
        f.emit("label", l_e)
        f.emit("ret", ("imm", 0))
        self.out.append(f)

        # ---- 字符串运行库（v0.2）：bump 分配器 + 拼接 + itoa ----
        # 内存策略跟 Quelmara.toml [memory] heap_limit_mb 走：超限 fail-fast。
        heap_sz = int(self.cfg["memory"]["heap_limit_mb"] or 512) * 1024 * 1024
        gid_oom = self.intern_str("quelmara: heap_limit_mb exceeded (fail-fast)\n")
        gid_zero = self.intern_array(1)
        self.heap_gid = self.intern_array(1)       # 堆基址
        self.bump_gid = self.intern_array(1)       # 已用偏移

        # __alloc(n) -> ptr   自举 bump 分配器（惰性 mmap / VirtualAlloc + 上限检查）
        f = Fn("__alloc")
        n = f.new_v()
        f.emit("args", [n])
        # 8 字节对齐：堆上的聚合（str 指针数组、struct）必须按字宽落位，
        # 否则 a64 上会因非对齐访问而崩、x86 上会静默错位。
        f.emit("bin", "add", n, n, ("imm", 7))
        f.emit("bin", "and", n, n, ("imm", -8))
        if self.uses_free:
            # 小对象按 32 字节粒度上取整：尺寸类里的块大小必须一致，
            # 否则 __free 回收的 8 字节块会被当成 32 字节块复用（写穿）。
            f.emit("bin", "add", n, n, ("imm", 31))
            f.emit("bin", "and", n, n, ("imm", -32))
        # 多线程程序（spawn / net reactor）bump 指针加 xchg 自旋锁：
        # io 线程与 acceptor 并发分配时，非原子的 load->add->store 会
        # 返回重叠内存 / 回退 bump（曾因此 reactor 静默不回声）。
        # 无线程程序不发射锁——单线程路径零变化（hello/loop_sum 不受影响）。
        alloc_locked = self.uses_join or self.uses_threads
        if alloc_locked:
            gid_alloc_lock = self.intern_array(1)
            l_spin = f.label("aspin")
            f.emit("label", l_spin)
            old = f.new_v()
            f.emit("xchg", old, ("ga", gid_alloc_lock), ("imm", 1))
            l_locked = f.label("alock")
            f.emit("jz", old, l_locked)
            self.emit_yield(f)
            f.emit("jmp", l_spin)
            f.emit("label", l_locked)
        if self.uses_free:
            # 尺寸类空闲链优先（O(1) 复用）：库层的连接槽 / 缓冲池靠这条路径
            # 做到"释放即复用"，不需要 GC、没有扫描停顿。
            gid_fl = self.free_list_gid()
            l_bump = f.label("abump")
            cls = f.new_v()
            f.emit("bin", "shr", cls, n, ("imm", 5))
            f.emit("bin", "sub", cls, cls, ("imm", 1))
            f.emit("jcc", "l", cls, ("imm", 0), l_bump)
            f.emit("jcc", "ge", cls, ("imm", FREE_CLASSES), l_bump)
            head = f.new_v()
            f.emit("load", head, ("ga", gid_fl), cls)
            f.emit("jz", head, l_bump)
            nxt = f.new_v()
            f.emit("load", nxt, head, ("imm", 0))
            f.emit("store", ("ga", gid_fl), cls, nxt)
            if alloc_locked:
                f.emit("store", ("ga", gid_alloc_lock), ("imm", 0), ("imm", 0))
            f.emit("ret", head)
            f.emit("label", l_bump)
        h = f.new_v()
        f.emit("load", h, ("ga", self.heap_gid), ("imm", 0))
        l_ready = f.label("aready")
        f.emit("jnz", h, l_ready)
        hv = self.emit_alloc(f, ("imm", heap_sz), reserve_only=True)
        f.emit("mov", h, hv)
        if self.platform == "windows":
            l_have = f.label("ahave")
            f.emit("jnz", h, l_have)
            oom0 = f.new_v()
            f.emit("movaddr", oom0, gid_oom)
            self.emit_write(f, 2, oom0, ("imm", 46))
            self.emit_exit(f, ("imm", 1))
            f.emit("label", l_have)
        f.emit("store", ("ga", self.heap_gid), ("imm", 0), h)
        f.emit("store", ("ga", self.bump_gid), ("imm", 0), ("imm", 0))
        if self.platform == "windows":
            f.emit("store", ("ga", self.committed_gid), ("imm", 0), ("imm", 0))
        f.emit("label", l_ready)
        off = f.new_v()
        f.emit("load", off, ("ga", self.bump_gid), ("imm", 0))
        newoff = f.new_v()
        f.emit("bin", "add", newoff, off, n)
        l_ok = f.label("aok")
        f.emit("jcc", "le", newoff, ("imm", heap_sz), l_ok)
        oom = f.new_v()
        f.emit("movaddr", oom, gid_oom)
        self.emit_write(f, 2, oom, ("imm", 46))
        self.emit_exit(f, ("imm", 1))
        f.emit("label", l_ok)
        if self.platform == "windows":
            # 按 1MB 粒度提交：512MB 的 heap_limit 只在真正用到时才占提交配额。
            cm = f.new_v()
            f.emit("load", cm, ("ga", self.committed_gid), ("imm", 0))
            l_cok = f.label("acommitted")
            f.emit("jcc", "le", newoff, cm, l_cok)
            ce = f.new_v()
            f.emit("bin", "add", ce, newoff, ("imm", 0xFFFFF))
            f.emit("bin", "and", ce, ce, ("imm", -0x100000))
            cptr = f.new_v()
            f.emit("bin", "add", cptr, h, cm)
            csz = f.new_v()
            f.emit("bin", "sub", csz, ce, cm)
            cand = f.new_v()
            f.emit("winapi", cand, "VirtualAlloc",
                    [cptr, csz, ("imm", 0x1000), ("imm", 4)])
            f.emit("store", ("ga", self.committed_gid), ("imm", 0), ce)
            f.emit("label", l_cok)
        f.emit("store", ("ga", self.bump_gid), ("imm", 0), newoff)
        if alloc_locked:
            f.emit("store", ("ga", gid_alloc_lock), ("imm", 0), ("imm", 0))
        r = f.new_v()
        f.emit("bin", "add", r, h, off)
        f.emit("ret", r)
        self.out.append(f)

        # ---- arena / 任务运行时（v0.4）----
        # 只发射真正用到的部分：hello 这种程序不会带 __join / __chan_*（省体积/导入）。
        if self.uses_bounds:
            msg = "quelmara: index out of bounds (fail-fast)\n"
            gid_b = self.intern_str(msg)
            f = Fn("__bounds_fail")
            # v2.60：失败路径**不内联**。内联后每个下标访问点都复制一份
            # "movaddr + WriteFile + ExitProcess"（5-8 条），b9_json 那种大函数
            # 会多出几十份，纯粹挤 I-cache；而这条路径正常情况一次都不走。
            f.no_inline = True
            f.emit("args", [])
            bp = f.new_v()
            f.emit("movaddr", bp, gid_b)
            self.emit_write(f, 2, bp, ("imm", len(msg.encode("utf-8"))))
            self.emit_exit(f, ("imm", 1))
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        if self.uses_arena:
            # __arena_mark() -> 当前 bump 偏移；__arena_release(mark) 整体回卷。
            # 语义：arena 块内用 __alloc 分配的对象（当前主要是字符串）在块末一次性回收；
            #       块内分配的对象不得逃逸到块外（无借用检查，约定式语义）。
            f = Fn("__arena_mark")
            f.emit("args", [])
            am = f.new_v()
            f.emit("load", am, ("ga", self.bump_gid), ("imm", 0))
            f.emit("ret", am)
            self.out.append(f)

            f = Fn("__arena_release")
            amark = f.new_v()
            f.emit("args", [amark])
            f.emit("store", ("ga", self.bump_gid), ("imm", 0), amark)
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        if self.uses_join:
            # __join(h) -> int：h 指向 16 字节记录 [原生线程句柄, 参数块]，
            # 参数块首字是任务返回值。等待线程结束后取结果。
            f = Fn("__join")
            h = f.new_v()
            f.emit("args", [h])
            l_zero = f.label("jzero")
            f.emit("jz", h, l_zero)
            tid = f.new_v()
            f.emit("load", tid, h, ("imm", 0))
            blk = f.new_v()
            f.emit("load", blk, h, ("imm", 1))
            if self.platform == "windows":
                f.emit("winapi", None, "WaitForSingleObject", [tid, ("imm", -1)])
                f.emit("winapi", None, "CloseHandle", [tid])
            else:
                f.emit("syscall", None, self.sc["wait4"],
                       [tid, ("imm", 0), ("imm", 0),
                        ("imm", 0), ("imm", 0), ("imm", 0)])
            jr = f.new_v()
            f.emit("load", jr, blk, ("imm", 0))
            f.emit("ret", jr)
            f.emit("label", l_zero)
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        # ---- chan[T]（v0.5）：有界 MPMC 环形队列 + 自旋锁 + yield ----
        # 布局（7 个 8 字节字）：[cap, head, tail, count, lock, buf, closed]
        # lock 用 xchg 原子抢锁；忙等时 yield，不把整核跑满。
        # closed（v0.11）：close() 置 1；send 见到即 fail-fast，
        # recv 排空后返回 0（零值）。与 C 端 QlmChan.closed 行为一致。
        # 只在 x86_64 发射（AArch64 需要 ldaxr/stxr 版本，后续补）。
        if self.uses_chan and self.arch == "x86_64":
            msg_cs = "quelmara: send on closed channel (fail-fast)\n"
            gid_cs = self.intern_str(msg_cs)
            msg_cd = "quelmara: chan double close (fail-fast)\n"
            gid_cd = self.intern_str(msg_cd)

            def chan_fail(f, gid, msg):
                """fail-fast：stderr 写消息 + exit(1)（锁已由调用方释放）"""
                p = f.new_v()
                f.emit("movaddr", p, gid)
                self.emit_write(f, 2, p, ("imm", len(msg.encode("utf-8"))))
                self.emit_exit(f, ("imm", 1))

            f = Fn("__chan_open")
            cap = f.new_v()
            f.emit("args", [cap])
            l_ok = f.label("cok")
            f.emit("jcc", "g", cap, ("imm", 0), l_ok)
            f.emit("mov", cap, ("imm", 1))
            f.emit("label", l_ok)
            blk = f.new_v()
            f.emit("call", blk, "__alloc", [("imm", 56)])
            sz = f.new_v()
            f.emit("bin", "mul", sz, cap, ("imm", 8))
            buf = f.new_v()
            f.emit("call", buf, "__alloc", [sz])
            for i, val in enumerate([cap, ("imm", 0), ("imm", 0),
                                     ("imm", 0), ("imm", 0), buf, ("imm", 0)]):
                f.emit("store", blk, ("imm", i), val)
            f.emit("ret", blk)
            self.out.append(f)

            f = Fn("__chan_send")
            h = f.new_v()
            v = f.new_v()
            f.emit("args", [h, v])
            l_retry, l_locked = f.label("csretry"), f.label("cslock")
            l_space, l_nowrap = f.label("csspace"), f.label("csnowrap")
            f.emit("label", l_retry)
            addr = f.new_v()
            f.emit("bin", "add", addr, h, ("imm", 32))
            old = f.new_v()
            f.emit("xchg", old, addr, ("imm", 1))
            f.emit("jz", old, l_locked)
            self.emit_yield(f)
            f.emit("jmp", l_retry)
            f.emit("label", l_locked)
            # closed 检查（v0.11）：初始进入与满等待重试都经由此处
            cl = f.new_v()
            f.emit("load", cl, h, ("imm", 6))
            l_go = f.label("csgo")
            f.emit("jz", cl, l_go)
            f.emit("store", h, ("imm", 4), ("imm", 0))
            chan_fail(f, gid_cs, msg_cs)
            f.emit("label", l_go)
            cnt = f.new_v()
            f.emit("load", cnt, h, ("imm", 3))
            cap2 = f.new_v()
            f.emit("load", cap2, h, ("imm", 0))
            f.emit("jcc", "ne", cnt, cap2, l_space)
            f.emit("store", h, ("imm", 4), ("imm", 0))
            self.emit_yield(f)
            f.emit("jmp", l_retry)
            f.emit("label", l_space)
            tail = f.new_v()
            f.emit("load", tail, h, ("imm", 2))
            buf2 = f.new_v()
            f.emit("load", buf2, h, ("imm", 5))
            f.emit("store", buf2, tail, v)
            t2 = f.new_v()
            f.emit("bin", "add", t2, tail, ("imm", 1))
            f.emit("jcc", "ne", t2, cap2, l_nowrap)
            f.emit("mov", t2, ("imm", 0))
            f.emit("label", l_nowrap)
            f.emit("store", h, ("imm", 2), t2)
            c2 = f.new_v()
            f.emit("bin", "add", c2, cnt, ("imm", 1))
            f.emit("store", h, ("imm", 3), c2)
            f.emit("store", h, ("imm", 4), ("imm", 0))
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__chan_recv")
            h = f.new_v()
            f.emit("args", [h])
            l_retry, l_locked = f.label("crretry"), f.label("crlock")
            l_data, l_nowrap = f.label("crdata"), f.label("crnowrap")
            f.emit("label", l_retry)
            addr = f.new_v()
            f.emit("bin", "add", addr, h, ("imm", 32))
            old = f.new_v()
            f.emit("xchg", old, addr, ("imm", 1))
            f.emit("jz", old, l_locked)
            self.emit_yield(f)
            f.emit("jmp", l_retry)
            f.emit("label", l_locked)
            cnt = f.new_v()
            f.emit("load", cnt, h, ("imm", 3))
            f.emit("jnz", cnt, l_data)
            # 空：closed -> 返回 0；否则继续等
            cl = f.new_v()
            f.emit("load", cl, h, ("imm", 6))
            l_wait = f.label("crwait")
            f.emit("jz", cl, l_wait)
            f.emit("store", h, ("imm", 4), ("imm", 0))
            f.emit("ret", ("imm", 0))
            f.emit("label", l_wait)
            f.emit("store", h, ("imm", 4), ("imm", 0))
            self.emit_yield(f)
            f.emit("jmp", l_retry)
            f.emit("label", l_data)
            head = f.new_v()
            f.emit("load", head, h, ("imm", 1))
            buf2 = f.new_v()
            f.emit("load", buf2, h, ("imm", 5))
            v = f.new_v()
            f.emit("load", v, buf2, head)
            h2 = f.new_v()
            f.emit("bin", "add", h2, head, ("imm", 1))
            cap2 = f.new_v()
            f.emit("load", cap2, h, ("imm", 0))
            f.emit("jcc", "ne", h2, cap2, l_nowrap)
            f.emit("mov", h2, ("imm", 0))
            f.emit("label", l_nowrap)
            f.emit("store", h, ("imm", 1), h2)
            c2 = f.new_v()
            f.emit("bin", "sub", c2, cnt, ("imm", 1))
            f.emit("store", h, ("imm", 3), c2)
            f.emit("store", h, ("imm", 4), ("imm", 0))
            f.emit("ret", v)
            self.out.append(f)

            # __chan_close(h) -> 0（v0.11）：幂等校验 + 置 closed + 放锁
            f = Fn("__chan_close")
            h = f.new_v()
            f.emit("args", [h])
            l_retry, l_locked = f.label("clretry"), f.label("cllock")
            f.emit("label", l_retry)
            addr = f.new_v()
            f.emit("bin", "add", addr, h, ("imm", 32))
            old = f.new_v()
            f.emit("xchg", old, addr, ("imm", 1))
            f.emit("jz", old, l_locked)
            self.emit_yield(f)
            f.emit("jmp", l_retry)
            f.emit("label", l_locked)
            cl = f.new_v()
            f.emit("load", cl, h, ("imm", 6))
            l_dbl = f.label("cldbl")
            f.emit("jz", cl, l_dbl)
            f.emit("store", h, ("imm", 4), ("imm", 0))
            chan_fail(f, gid_cd, msg_cd)
            f.emit("label", l_dbl)
            f.emit("store", h, ("imm", 6), ("imm", 1))
            f.emit("store", h, ("imm", 4), ("imm", 0))
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            # __chan_try_recv(h, okptr) -> v（v0.11 select 用）：
            # 非阻塞取一个；[okptr] = 1 取到 / 0 空。锁协议同 recv。
            f = Fn("__chan_try_recv")
            h, okp = f.new_v(), f.new_v()
            f.emit("args", [h, okp])
            l_retry, l_locked = f.label("ctretry"), f.label("ctlock")
            l_data, l_nowrap = f.label("ctdata"), f.label("ctnowrap")
            f.emit("label", l_retry)
            addr = f.new_v()
            f.emit("bin", "add", addr, h, ("imm", 32))
            old = f.new_v()
            f.emit("xchg", old, addr, ("imm", 1))
            f.emit("jz", old, l_locked)
            self.emit_yield(f)
            f.emit("jmp", l_retry)
            f.emit("label", l_locked)
            cnt = f.new_v()
            f.emit("load", cnt, h, ("imm", 3))
            f.emit("jnz", cnt, l_data)
            f.emit("store", h, ("imm", 4), ("imm", 0))
            f.emit("store", okp, ("imm", 0), ("imm", 0))
            f.emit("ret", ("imm", 0))
            f.emit("label", l_data)
            head = f.new_v()
            f.emit("load", head, h, ("imm", 1))
            buf2 = f.new_v()
            f.emit("load", buf2, h, ("imm", 5))
            v = f.new_v()
            f.emit("load", v, buf2, head)
            h2 = f.new_v()
            f.emit("bin", "add", h2, head, ("imm", 1))
            cap2 = f.new_v()
            f.emit("load", cap2, h, ("imm", 0))
            f.emit("jcc", "ne", h2, cap2, l_nowrap)
            f.emit("mov", h2, ("imm", 0))
            f.emit("label", l_nowrap)
            f.emit("store", h, ("imm", 1), h2)
            c2 = f.new_v()
            f.emit("bin", "sub", c2, cnt, ("imm", 1))
            f.emit("store", h, ("imm", 3), c2)
            f.emit("store", h, ("imm", 4), ("imm", 0))
            f.emit("store", okp, ("imm", 0), ("imm", 1))
            f.emit("ret", v)
            self.out.append(f)

        # ---- map[K]V（v0.10）：开放寻址 + 线性探测哈希表 ----
        # 控制块 7 字：[cap, count, used, ktag, st, kt, vt]，st/kt/vt 三组平行槽，
        # state 0=空 1=占用 2=墓碑。键相等/哈希按 ktag 分派（str 走 __str_eq 内容比较）。
        # 哈希与 C 后端逐位一致：整数 splitmix64 终混、str FNV-1a，否则双链 diff 会挂。
        # 扩容：used*10 >= cap*7 时容量翻倍 rehash（墓碑不带入）。
        # arena 绑定：存储走 __alloc bump 分配器，因此 arena 块内创建的 map
        # 随 __arena_release 整体回卷回收（块内对象不得逃逸，与字符串同约定）。
        if self.uses_map:
            if self.arch != "x86_64":
                raise SyntaxError("map[K]V 目前仅支持 x86_64 后端")
            msg_nf = "quelmara: map key not found (fail-fast)\n"
            gid_nf = self.intern_str(msg_nf)

            # __map_hash_word(x) -> u64   splitmix64 终混（64 位回绕乘）
            f = Fn("__map_hash_word")
            x = f.new_v()
            f.emit("args", [x])
            z = f.new_v()
            f.emit("mov", z, x)
            t = f.new_v()
            for sh, mul in ((30, 0xBF58476D1CE4E5B9), (27, 0x94D049BB133111EB)):
                f.emit("bin", "shr", t, z, ("imm", sh))
                f.emit("bin", "xor", z, z, t)
                f.emit("bin", "mul", z, z, ("imm", mul))
            f.emit("bin", "shr", t, z, ("imm", 31))
            f.emit("bin", "xor", z, z, t)
            f.emit("ret", z)
            self.out.append(f)

            # __map_hash_str(s) -> u64   FNV-1a（逐字节到 NUL）
            f = Fn("__map_hash_str")
            s = f.new_v()
            f.emit("args", [s])
            h = f.new_v()
            f.emit("mov", h, ("imm", 0xcbf29ce484222325))
            i = f.new_v()
            f.emit("mov", i, ("imm", 0))
            l_t, l_e = f.label("hst"), f.label("hse")
            f.emit("label", l_t)
            b = f.new_v()
            f.emit("load8", b, s, i)
            f.emit("jz", b, l_e)
            f.emit("bin", "xor", h, h, b)
            f.emit("bin", "mul", h, h, ("imm", 0x100000001b3))
            f.emit("bin", "add", i, i, ("imm", 1))
            f.emit("jmp", l_t)
            f.emit("label", l_e)
            f.emit("ret", h)
            self.out.append(f)

            # __map_hash(m, k) -> u64   按 ktag 分派
            f = Fn("__map_hash")
            m, k = f.new_v(), f.new_v()
            f.emit("args", [m, k])
            tag = f.new_v()
            f.emit("load", tag, m, ("imm", 3))
            l_str = f.label("mhstr")
            f.emit("jnz", tag, l_str)
            h1 = f.new_v()
            f.emit("call", h1, "__map_hash_word", [k])
            f.emit("ret", h1)
            f.emit("label", l_str)
            h2 = f.new_v()
            f.emit("call", h2, "__map_hash_str", [k])
            f.emit("ret", h2)
            self.out.append(f)

            # __map_key_eq(m, a, b) -> 0/1   int/bool 按值，str 按 __str_eq 内容
            f = Fn("__map_key_eq")
            m, a, b = f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [m, a, b])
            tag = f.new_v()
            f.emit("load", tag, m, ("imm", 3))
            l_str = f.label("kestr")
            f.emit("jnz", tag, l_str)
            d = f.new_v()
            f.emit("cmpset", "e", d, a, b)
            f.emit("ret", d)
            f.emit("label", l_str)
            d2 = f.new_v()
            f.emit("call", d2, "__str_eq", [a, b])
            f.emit("ret", d2)
            self.out.append(f)

            # __map_find(m, k) -> 槽下标 / -1（线性探测；墓碑继续探）
            f = Fn("__map_find")
            m, k = f.new_v(), f.new_v()
            f.emit("args", [m, k])
            cap = f.new_v()
            f.emit("load", cap, m, ("imm", 0))
            mask = f.new_v()
            f.emit("bin", "sub", mask, cap, ("imm", 1))
            st = f.new_v()
            f.emit("load", st, m, ("imm", 4))
            kt = f.new_v()
            f.emit("load", kt, m, ("imm", 5))
            h = f.new_v()
            f.emit("call", h, "__map_hash", [m, k])
            i = f.new_v()
            f.emit("bin", "and", i, h, mask)
            l_t, l_empty = f.label("fdt"), f.label("fde")
            l_next, l_hit = f.label("fdn"), f.label("fdh")
            f.emit("label", l_t)
            s = f.new_v()
            f.emit("load", s, st, i)
            f.emit("jcc", "e", s, ("imm", 0), l_empty)
            f.emit("jcc", "ne", s, ("imm", 1), l_next)    # 墓碑：继续探测
            kk = f.new_v()
            f.emit("load", kk, kt, i)
            eq = f.new_v()
            f.emit("call", eq, "__map_key_eq", [m, kk, k])
            f.emit("jnz", eq, l_hit)
            f.emit("jmp", l_next)
            f.emit("label", l_hit)
            f.emit("ret", i)
            f.emit("label", l_empty)
            f.emit("ret", ("imm", -1))
            f.emit("label", l_next)
            f.emit("bin", "add", i, i, ("imm", 1))
            f.emit("bin", "and", i, i, mask)
            f.emit("jmp", l_t)
            self.out.append(f)

            # __map_open(cap, ktag, vw) -> 句柄（cap<1 取 16，再向上取整到 2 的幂）
            # vw = 值槽宽（字）。标量 1（与 v0.10 布局逐字节一致）；聚合值
            # （v1.41）按 agg 布局 N 字，值表容量相应 ×vw，槽宽存控制块 [7]。
            f = Fn("__map_open")
            cap, ktag, vw = f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [cap, ktag, vw])
            l_ok = f.label("mook")
            f.emit("jcc", "ge", cap, ("imm", 1), l_ok)
            f.emit("mov", cap, ("imm", 16))
            f.emit("label", l_ok)
            n = f.new_v()
            f.emit("bin", "sub", n, cap, ("imm", 1))
            for sh in (1, 2, 4, 8, 16, 32):
                tt = f.new_v()
                f.emit("bin", "shr", tt, n, ("imm", sh))
                f.emit("bin", "or", n, n, tt)
            f.emit("bin", "add", cap, n, ("imm", 1))
            blk = f.new_v()
            f.emit("call", blk, "__alloc", [("imm", 64)])
            sz = f.new_v()
            f.emit("bin", "mul", sz, cap, ("imm", 8))
            szv = f.new_v()
            f.emit("bin", "mul", szv, sz, vw)          # 值表：cap*vw*8 字节
            st = f.new_v()
            f.emit("call", st, "__alloc", [sz])
            kt = f.new_v()
            f.emit("call", kt, "__alloc", [sz])
            vt = f.new_v()
            f.emit("call", vt, "__alloc", [szv])
            i = f.new_v()
            f.emit("mov", i, ("imm", 0))
            l_zt, l_ze = f.label("mozt"), f.label("moze")
            f.emit("label", l_zt)
            f.emit("jcc", "ge", i, cap, l_ze)
            f.emit("store", st, i, ("imm", 0))
            f.emit("bin", "add", i, i, ("imm", 1))
            f.emit("jmp", l_zt)
            f.emit("label", l_ze)
            f.emit("store", blk, ("imm", 0), cap)
            f.emit("store", blk, ("imm", 1), ("imm", 0))    # count
            f.emit("store", blk, ("imm", 2), ("imm", 0))    # used
            f.emit("store", blk, ("imm", 3), ktag)
            f.emit("store", blk, ("imm", 4), st)
            f.emit("store", blk, ("imm", 5), kt)
            f.emit("store", blk, ("imm", 6), vt)
            f.emit("store", blk, ("imm", 7), vw)            # 值槽宽（v1.41）
            f.emit("ret", blk)
            self.out.append(f)

            # __map_grow(m)：容量翻倍 rehash（旧表是 bump 分配，不回收；
            # arena 块内随块整体回卷，块外到进程退出才丢）
            # 值拷贝按控制块 [7] 的槽宽逐字搬（v1.41）；vw=1 时与旧布局一致
            f = Fn("__map_grow")
            m = f.new_v()
            f.emit("args", [m])
            cap = f.new_v()
            f.emit("load", cap, m, ("imm", 0))
            vw = f.new_v()
            f.emit("load", vw, m, ("imm", 7))
            ncap = f.new_v()
            f.emit("bin", "mul", ncap, cap, ("imm", 2))
            nmask = f.new_v()
            f.emit("bin", "sub", nmask, ncap, ("imm", 1))
            ost = f.new_v()
            f.emit("load", ost, m, ("imm", 4))
            okt = f.new_v()
            f.emit("load", okt, m, ("imm", 5))
            ovt = f.new_v()
            f.emit("load", ovt, m, ("imm", 6))
            nsz = f.new_v()
            f.emit("bin", "mul", nsz, ncap, ("imm", 8))
            nszv = f.new_v()
            f.emit("bin", "mul", nszv, nsz, vw)        # 新值表：ncap*vw*8
            nst = f.new_v()
            f.emit("call", nst, "__alloc", [nsz])
            nkt = f.new_v()
            f.emit("call", nkt, "__alloc", [nsz])
            nvt = f.new_v()
            f.emit("call", nvt, "__alloc", [nszv])
            i = f.new_v()
            f.emit("mov", i, ("imm", 0))
            l_zt, l_ze = f.label("mgzt"), f.label("mgze")
            f.emit("label", l_zt)
            f.emit("jcc", "ge", i, ncap, l_ze)
            f.emit("store", nst, i, ("imm", 0))
            f.emit("bin", "add", i, i, ("imm", 1))
            f.emit("jmp", l_zt)
            f.emit("label", l_ze)
            nused = f.new_v()
            f.emit("mov", nused, ("imm", 0))
            f.emit("mov", i, ("imm", 0))
            l_rt, l_re = f.label("mgrt"), f.label("mgre")
            l_skip, l_pt, l_slot = f.label("mgsk"), f.label("mgpt"), f.label("mgsl")
            l_vc, l_vd = f.label("mgvc"), f.label("mgvd")
            f.emit("label", l_rt)
            f.emit("jcc", "ge", i, cap, l_re)
            s = f.new_v()
            f.emit("load", s, ost, i)
            f.emit("jcc", "ne", s, ("imm", 1), l_skip)   # 墓碑/空槽不带入
            kk = f.new_v()
            f.emit("load", kk, okt, i)
            h = f.new_v()
            f.emit("call", h, "__map_hash", [m, kk])
            j = f.new_v()
            f.emit("bin", "and", j, h, nmask)
            f.emit("label", l_pt)
            ts = f.new_v()
            f.emit("load", ts, nst, j)
            f.emit("jz", ts, l_slot)
            f.emit("bin", "add", j, j, ("imm", 1))
            f.emit("bin", "and", j, j, nmask)
            f.emit("jmp", l_pt)
            f.emit("label", l_slot)
            f.emit("store", nst, j, ("imm", 1))
            f.emit("store", nkt, j, kk)
            # 值逐字拷贝：ovt[i*vw + w] -> nvt[j*vw + w]，w in 0..vw
            base_o = f.new_v()
            f.emit("bin", "mul", base_o, i, vw)
            base_n = f.new_v()
            f.emit("bin", "mul", base_n, j, vw)
            w = f.new_v()
            f.emit("mov", w, ("imm", 0))
            f.emit("label", l_vc)
            f.emit("jcc", "ge", w, vw, l_vd)
            so = f.new_v()
            f.emit("bin", "add", so, base_o, w)
            vv = f.new_v()
            f.emit("load", vv, ovt, so)
            dn = f.new_v()
            f.emit("bin", "add", dn, base_n, w)
            f.emit("store", nvt, dn, vv)
            f.emit("bin", "add", w, w, ("imm", 1))
            f.emit("jmp", l_vc)
            f.emit("label", l_vd)
            f.emit("bin", "add", nused, nused, ("imm", 1))
            f.emit("label", l_skip)
            f.emit("bin", "add", i, i, ("imm", 1))
            f.emit("jmp", l_rt)
            f.emit("label", l_re)
            f.emit("store", m, ("imm", 0), ncap)
            f.emit("store", m, ("imm", 2), nused)
            f.emit("store", m, ("imm", 4), nst)
            f.emit("store", m, ("imm", 5), nkt)
            f.emit("store", m, ("imm", 6), nvt)
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            # __map_set(m, k, v)：插入/覆盖写；墓碑优先复用；越阈值扩容
            f = Fn("__map_set")
            m, k, v = f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [m, k, v])
            cap = f.new_v()
            f.emit("load", cap, m, ("imm", 0))
            mask = f.new_v()
            f.emit("bin", "sub", mask, cap, ("imm", 1))
            st = f.new_v()
            f.emit("load", st, m, ("imm", 4))
            kt = f.new_v()
            f.emit("load", kt, m, ("imm", 5))
            vt = f.new_v()
            f.emit("load", vt, m, ("imm", 6))
            h = f.new_v()
            f.emit("call", h, "__map_hash", [m, k])
            i = f.new_v()
            f.emit("bin", "and", i, h, mask)
            first = f.new_v()
            f.emit("mov", first, ("imm", -1))
            l_t, l_ins = f.label("mst"), f.label("msins")
            l_tomb, l_upd = f.label("mstm"), f.label("msup")
            l_next, l_use = f.label("msn"), f.label("msuse")
            l_noused, l_grow = f.label("msnu"), f.label("msgr")
            f.emit("label", l_t)
            s = f.new_v()
            f.emit("load", s, st, i)
            f.emit("jcc", "e", s, ("imm", 0), l_ins)
            f.emit("jcc", "e", s, ("imm", 2), l_tomb)
            kk = f.new_v()
            f.emit("load", kk, kt, i)
            eq = f.new_v()
            f.emit("call", eq, "__map_key_eq", [m, kk, k])
            f.emit("jnz", eq, l_upd)
            f.emit("jmp", l_next)
            f.emit("label", l_upd)
            f.emit("store", vt, i, v)                  # 覆盖写
            f.emit("ret", ("imm", 0))
            f.emit("label", l_tomb)
            f.emit("jcc", "ge", first, ("imm", 0), l_next)
            f.emit("mov", first, i)                   # 记第一个墓碑
            f.emit("jmp", l_next)
            f.emit("label", l_ins)
            f.emit("jcc", "l", first, ("imm", 0), l_use)
            f.emit("mov", i, first)                   # 复用墓碑，探测链不断
            f.emit("label", l_use)
            f.emit("store", st, i, ("imm", 1))
            f.emit("store", kt, i, k)
            f.emit("store", vt, i, v)
            cnt = f.new_v()
            f.emit("load", cnt, m, ("imm", 1))
            f.emit("bin", "add", cnt, cnt, ("imm", 1))
            f.emit("store", m, ("imm", 1), cnt)
            f.emit("jcc", "ge", first, ("imm", 0), l_noused)
            used = f.new_v()
            f.emit("load", used, m, ("imm", 2))
            f.emit("bin", "add", used, used, ("imm", 1))
            f.emit("store", m, ("imm", 2), used)
            f.emit("label", l_noused)
            used2 = f.new_v()
            f.emit("load", used2, m, ("imm", 2))
            u10 = f.new_v()
            f.emit("bin", "mul", u10, used2, ("imm", 10))
            c7 = f.new_v()
            f.emit("bin", "mul", c7, cap, ("imm", 7))
            f.emit("jcc", "ge", u10, c7, l_grow)     # 装载因子 >= 0.7 -> 扩容
            f.emit("ret", ("imm", 0))
            f.emit("label", l_grow)
            f.emit("call", None, "__map_grow", [m])
            f.emit("ret", ("imm", 0))
            f.emit("label", l_next)
            f.emit("bin", "add", i, i, ("imm", 1))
            f.emit("bin", "and", i, i, mask)
            f.emit("jmp", l_t)
            self.out.append(f)

            # __map_get(m, k) -> v；键不存在 fail-fast（stderr + exit(1)）
            f = Fn("__map_get")
            m, k = f.new_v(), f.new_v()
            f.emit("args", [m, k])
            idx = f.new_v()
            f.emit("call", idx, "__map_find", [m, k])
            l_ok = f.label("mgok")
            f.emit("jcc", "ge", idx, ("imm", 0), l_ok)
            p = f.new_v()
            f.emit("movaddr", p, gid_nf)
            self.emit_write(f, 2, p, ("imm", len(msg_nf.encode("utf-8"))))
            self.emit_exit(f, ("imm", 1))
            f.emit("label", l_ok)
            vt = f.new_v()
            f.emit("load", vt, m, ("imm", 6))
            d = f.new_v()
            f.emit("load", d, vt, idx)
            f.emit("ret", d)
            self.out.append(f)

            # __map_set_n(m, k, src)：聚合值插入/覆盖写（v1.41）。
            # 探测结构与 __map_set 完全一致，值写改为按控制块 [7] 的槽宽
            # 逐字从 src 拷入 vt[i*vw + w]。只在聚合值 map 上发射，
            # 标量热路径（__map_set）零改动。
            f = Fn("__map_set_n")
            m, k, src = f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [m, k, src])
            cap = f.new_v()
            f.emit("load", cap, m, ("imm", 0))
            vw = f.new_v()
            f.emit("load", vw, m, ("imm", 7))
            mask = f.new_v()
            f.emit("bin", "sub", mask, cap, ("imm", 1))
            st = f.new_v()
            f.emit("load", st, m, ("imm", 4))
            kt = f.new_v()
            f.emit("load", kt, m, ("imm", 5))
            vt = f.new_v()
            f.emit("load", vt, m, ("imm", 6))
            h = f.new_v()
            f.emit("call", h, "__map_hash", [m, k])
            i = f.new_v()
            f.emit("bin", "and", i, h, mask)
            first = f.new_v()
            f.emit("mov", first, ("imm", -1))
            l_t, l_ins = f.label("msnt"), f.label("msnins")
            l_tomb, l_upd = f.label("msntm"), f.label("msnup")
            l_next, l_use = f.label("msnn"), f.label("msnuse")
            l_ucp, l_udone = f.label("msnuc"), f.label("msnud")
            l_icp, l_idone = f.label("msnic"), f.label("msnid")
            l_noused, l_grow = f.label("msnnu"), f.label("msngr")
            f.emit("label", l_t)
            s = f.new_v()
            f.emit("load", s, st, i)
            f.emit("jcc", "e", s, ("imm", 0), l_ins)
            f.emit("jcc", "e", s, ("imm", 2), l_tomb)
            kk = f.new_v()
            f.emit("load", kk, kt, i)
            eq = f.new_v()
            f.emit("call", eq, "__map_key_eq", [m, kk, k])
            f.emit("jnz", eq, l_upd)
            f.emit("jmp", l_next)
            f.emit("label", l_upd)
            # 覆盖写：vt[i*vw + w] <- src[w]，逐字拷入后直接返回
            base = f.new_v()
            f.emit("bin", "mul", base, i, vw)
            w = f.new_v()
            f.emit("mov", w, ("imm", 0))
            f.emit("label", l_ucp)
            f.emit("jcc", "ge", w, vw, l_udone)
            ld = f.new_v()
            f.emit("load", ld, src, w)
            dn = f.new_v()
            f.emit("bin", "add", dn, base, w)
            f.emit("store", vt, dn, ld)
            f.emit("bin", "add", w, w, ("imm", 1))
            f.emit("jmp", l_ucp)
            f.emit("label", l_udone)
            f.emit("ret", ("imm", 0))
            f.emit("label", l_tomb)
            f.emit("jcc", "ge", first, ("imm", 0), l_next)
            f.emit("mov", first, i)                   # 记第一个墓碑
            f.emit("jmp", l_next)
            f.emit("label", l_ins)
            f.emit("jcc", "l", first, ("imm", 0), l_use)
            f.emit("mov", i, first)                   # 复用墓碑，探测链不断
            f.emit("label", l_use)
            f.emit("store", st, i, ("imm", 1))
            f.emit("store", kt, i, k)
            base2 = f.new_v()
            f.emit("bin", "mul", base2, i, vw)
            w2 = f.new_v()
            f.emit("mov", w2, ("imm", 0))
            f.emit("label", l_icp)
            f.emit("jcc", "ge", w2, vw, l_idone)
            ld2 = f.new_v()
            f.emit("load", ld2, src, w2)
            dn2 = f.new_v()
            f.emit("bin", "add", dn2, base2, w2)
            f.emit("store", vt, dn2, ld2)
            f.emit("bin", "add", w2, w2, ("imm", 1))
            f.emit("jmp", l_icp)
            f.emit("label", l_idone)
            cnt = f.new_v()
            f.emit("load", cnt, m, ("imm", 1))
            f.emit("bin", "add", cnt, cnt, ("imm", 1))
            f.emit("store", m, ("imm", 1), cnt)
            f.emit("jcc", "ge", first, ("imm", 0), l_noused)
            used = f.new_v()
            f.emit("load", used, m, ("imm", 2))
            f.emit("bin", "add", used, used, ("imm", 1))
            f.emit("store", m, ("imm", 2), used)
            f.emit("label", l_noused)
            used2 = f.new_v()
            f.emit("load", used2, m, ("imm", 2))
            u10 = f.new_v()
            f.emit("bin", "mul", u10, used2, ("imm", 10))
            c7 = f.new_v()
            f.emit("bin", "mul", c7, cap, ("imm", 7))
            f.emit("jcc", "ge", u10, c7, l_grow)     # 装载因子 >= 0.7 -> 扩容
            f.emit("ret", ("imm", 0))
            f.emit("label", l_grow)
            f.emit("call", None, "__map_grow", [m])
            f.emit("ret", ("imm", 0))
            f.emit("label", l_next)
            f.emit("bin", "add", i, i, ("imm", 1))
            f.emit("bin", "and", i, i, mask)
            f.emit("jmp", l_t)
            self.out.append(f)

            # __map_get_n(m, k, dst)：聚合值拷出（v1.41）。键不存在同样
            # fail-fast；命中后按槽宽逐字 vt[idx*vw + w] -> dst[w]。
            f = Fn("__map_get_n")
            m, k, dst = f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [m, k, dst])
            idx = f.new_v()
            f.emit("call", idx, "__map_find", [m, k])
            l_ok = f.label("mgnok")
            f.emit("jcc", "ge", idx, ("imm", 0), l_ok)
            p = f.new_v()
            f.emit("movaddr", p, gid_nf)
            self.emit_write(f, 2, p, ("imm", len(msg_nf.encode("utf-8"))))
            self.emit_exit(f, ("imm", 1))
            f.emit("label", l_ok)
            vt = f.new_v()
            f.emit("load", vt, m, ("imm", 6))
            vw = f.new_v()
            f.emit("load", vw, m, ("imm", 7))
            base = f.new_v()
            f.emit("bin", "mul", base, idx, vw)
            w = f.new_v()
            f.emit("mov", w, ("imm", 0))
            l_cp, l_cpdone = f.label("mgncp"), f.label("mgncd")
            f.emit("label", l_cp)
            f.emit("jcc", "ge", w, vw, l_cpdone)
            ld = f.new_v()
            f.emit("load", ld, vt, base)              # vt[base + w]
            f.emit("store", dst, w, ld)
            f.emit("bin", "add", base, base, ("imm", 1))
            f.emit("bin", "add", w, w, ("imm", 1))
            f.emit("jmp", l_cp)
            f.emit("label", l_cpdone)
            f.emit("ret", dst)
            self.out.append(f)

            # __map_has(m, k) -> 0/1
            f = Fn("__map_has")
            m, k = f.new_v(), f.new_v()
            f.emit("args", [m, k])
            idx = f.new_v()
            f.emit("call", idx, "__map_find", [m, k])
            d = f.new_v()
            f.emit("cmpset", "ge", d, idx, ("imm", 0))
            f.emit("ret", d)
            self.out.append(f)

            # __map_del(m, k)：置墓碑（删缺失键：无操作）
            f = Fn("__map_del")
            m, k = f.new_v(), f.new_v()
            f.emit("args", [m, k])
            idx = f.new_v()
            f.emit("call", idx, "__map_find", [m, k])
            l_ok, l_end = f.label("mdok"), f.label("mdend")
            f.emit("jcc", "ge", idx, ("imm", 0), l_ok)
            f.emit("ret", ("imm", 0))
            f.emit("label", l_ok)
            st = f.new_v()
            f.emit("load", st, m, ("imm", 4))
            f.emit("store", st, idx, ("imm", 2))     # 墓碑：探测链继续有效
            cnt = f.new_v()
            f.emit("load", cnt, m, ("imm", 1))
            f.emit("bin", "sub", cnt, cnt, ("imm", 1))
            f.emit("store", m, ("imm", 1), cnt)
            f.emit("label", l_end)
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            # __map_len(m) -> count（不含墓碑）
            f = Fn("__map_len")
            m = f.new_v()
            f.emit("args", [m])
            d = f.new_v()
            f.emit("load", d, m, ("imm", 1))
            f.emit("ret", d)
            self.out.append(f)

        # __str_len(p) -> int（v1.5.1 长度前缀：O(1) 加载，不再扫 NUL）
        f = Fn("__str_len")
        p = f.new_v()
        f.emit("args", [p])
        t = f.new_v()
        f.emit("bin", "sub", t, p, ("imm", 8))
        n = f.new_v()
        f.emit("load", n, t, ("imm", 0))
        f.emit("ret", n)
        self.out.append(f)

        if self.uses_vec:
            # vec[T] 头：w0=data, w1=len, w2=cap, w3=ew（每个元素的 8 字节槽数）
            # 标量 ew=1 走 __vec_push/get 的快速路径；聚合 ew>1 走 *_n 变体（memcpy）。
            msg = "quelmara: vec index out of bounds (fail-fast)\n"
            gid_v = self.intern_str(msg)
            f = Fn("__vec_fail")
            f.no_inline = True      # 同上：失败路径只留一条 call
            f.emit("args", [])
            bp = f.new_v()
            f.emit("movaddr", bp, gid_v)
            self.emit_write(f, 2, bp, ("imm", len(msg.encode("utf-8"))))
            self.emit_exit(f, ("imm", 1))
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__vec_new")
            cap, ew = f.new_v(), f.new_v()
            f.emit("args", [cap, ew])
            b0 = f.new_v()
            l_ok = f.label("vn.ok")
            f.emit("cmpset", "ge", b0, cap, ("imm", 4))     # 最小容量 4
            f.emit("jnz", b0, l_ok)
            f.emit("mov", cap, ("imm", 4))
            f.emit("label", l_ok)
            h = f.new_v()
            f.emit("call", h, "__alloc", [("imm", 32)])
            nb = f.new_v()
            f.emit("bin", "mul", nb, cap, ew)
            f.emit("bin", "shl", nb, nb, ("imm", 3))
            data = f.new_v()
            f.emit("call", data, "__alloc", [nb])
            f.emit("store", h, ("imm", 0), data)
            f.emit("store", h, ("imm", 1), ("imm", 0))
            f.emit("store", h, ("imm", 2), cap)
            f.emit("store", h, ("imm", 3), ew)
            f.emit("ret", h)
            self.out.append(f)

            # __vec_grow(h)：len==cap 时容量翻倍并搬旧数据（返回 data 指针）
            f = Fn("__vec_grow")
            # v2.96：**冷路径 helper，禁止内联**（同 parfor worker 的机制）。
            # grow 只在扩容那一瞬间执行（预分配的 vec 一次都不进），但内联
            # 会把它的 realloc+memcpy 大块体塞进每个 push 调用点的**热循环**里
            # ——`ln==cp` 冷分支摊薄了热循环的代码密度，i-cache/分支预测双亏。
            # 实测（本机 x86-64，阈值 60 全量内联 vs 只 ban grow，min of 2）：
            #   b4_array 82.1 -> 65.5 ms（阈值 28 基线 64.9，完全恢复）
            #   b9_json  79.7 -> 76.0 ms（还更好）
            #   b1/b2/b3/b5/b6/b7 全在噪声内（±2%）
            # v2.93 登记的"b4_array +23%"就是它；按热度分档不是必要，
            # **按冷热分档**才是：一个标记解决，不用启发式引擎。
            f.no_inline = True
            h = f.new_v()
            f.emit("args", [h])
            ln, cp, ew = f.new_v(), f.new_v(), f.new_v()
            f.emit("load", ln, h, ("imm", 1))
            f.emit("load", cp, h, ("imm", 2))
            f.emit("load", ew, h, ("imm", 3))
            data = f.new_v()
            f.emit("load", data, h, ("imm", 0))
            b1 = f.new_v()
            l_ret, l_g = f.label("vg.r"), f.label("vg.g")
            f.emit("cmpset", "l", b1, ln, cp)
            f.emit("jnz", b1, l_ret)
            ncp = f.new_v()
            f.emit("bin", "shl", ncp, cp, ("imm", 1))
            nb = f.new_v()
            f.emit("bin", "mul", nb, ncp, ew)
            f.emit("bin", "shl", nb, nb, ("imm", 3))
            nbytes = f.new_v()
            f.emit("bin", "mul", nbytes, ln, ew)
            f.emit("bin", "shl", nbytes, nbytes, ("imm", 3))
            # v1.5：顶端块原地延展（不拷贝、不泄漏旧块）；否则分配新块并搬。
            nd = f.new_v()
            f.emit("call", nd, "__realloc", [data, nbytes, nb])
            f.emit("store", h, ("imm", 0), nd)
            f.emit("store", h, ("imm", 2), ncp)
            f.emit("ret", nd)
            f.emit("label", l_ret)
            f.emit("ret", data)
            self.out.append(f)

            f = Fn("__vec_push")
            h, v = f.new_v(), f.new_v()
            f.emit("args", [h, v])
            # v2.67：**容量检查内联**，只在真的需要扩容时才调 __vec_grow。
            # 以前是"每次 push 都 call __vec_grow"，而它在容量够时只是
            # `load data; ret` —— b4_array 的 200 万次 push 就是 200 万次
            # 白白的 call/ret + 序言（约 15-20 周期/次）。
            ln = f.new_v()
            f.emit("load", ln, h, ("imm", 1))
            cp = f.new_v()
            f.emit("load", cp, h, ("imm", 2))
            b_ = f.new_v()
            l_g, l_h = f.label("vp.g"), f.label("vp.h")
            f.emit("cmpset", "l", b_, ln, cp)
            f.emit("jnz", b_, l_h)          # 容量够 -> 直接跳过扩容
            f.emit("call", None, "__vec_grow", [h])
            f.emit("label", l_h)
            # 扩容会换数据块，所以 data 必须在检查之后读（与旧实现语义一致）
            data = f.new_v()
            f.emit("load", data, h, ("imm", 0))
            f.emit("store", data, ln, v)
            ln1 = f.new_v()
            f.emit("bin", "add", ln1, ln, ("imm", 1))
            f.emit("store", h, ("imm", 1), ln1)
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            # __vec_push_n(h, src)：聚合元素，按 ew*8 字节拷贝
            f = Fn("__vec_push_n")
            h, src = f.new_v(), f.new_v()
            f.emit("args", [h, src])
            # v2.67：容量检查内联（同 __vec_push）
            ln = f.new_v()
            f.emit("load", ln, h, ("imm", 1))
            cp = f.new_v()
            f.emit("load", cp, h, ("imm", 2))
            b_ = f.new_v()
            l_g, l_h = f.label("vpn.g"), f.label("vpn.h")
            f.emit("cmpset", "l", b_, ln, cp)
            f.emit("jnz", b_, l_h)
            f.emit("call", None, "__vec_grow", [h])
            f.emit("label", l_h)
            data = f.new_v()
            f.emit("load", data, h, ("imm", 0))
            ew = f.new_v()
            f.emit("load", ew, h, ("imm", 3))
            off = f.new_v()
            f.emit("bin", "mul", off, ln, ew)
            f.emit("bin", "shl", off, off, ("imm", 3))
            dst = f.new_v()
            f.emit("bin", "add", dst, data, off)
            nbytes = f.new_v()
            f.emit("bin", "shl", nbytes, ew, ("imm", 3))
            f.emit("call", None, "__memcpy", [dst, src, nbytes])
            ln1 = f.new_v()
            f.emit("bin", "add", ln1, ln, ("imm", 1))
            f.emit("store", h, ("imm", 1), ln1)
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__vec_len")
            h = f.new_v()
            f.emit("args", [h])
            d = f.new_v()
            f.emit("load", d, h, ("imm", 1))
            f.emit("ret", d)
            self.out.append(f)

            f = Fn("__vec_clear")
            h = f.new_v()
            f.emit("args", [h])
            f.emit("store", h, ("imm", 1), ("imm", 0))
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            # 边界检查内联到 get/set/pop（都用 cmpset+jnz，避免 jcc+cmp 立即数）
            f = Fn("__vec_get")
            h, i = f.new_v(), f.new_v()
            f.emit("args", [h, i])
            ln = f.new_v()
            f.emit("load", ln, h, ("imm", 1))
            b = f.new_v()
            l_bad, l_ok = f.label("vg.b"), f.label("vg.k")
            # v2.66：一次无符号比较覆盖 [0, len)
            f.emit("cmpset", "b", b, i, ln)
            f.emit("jz", b, l_bad)
            data = f.new_v()
            f.emit("load", data, h, ("imm", 0))
            d = f.new_v()
            f.emit("load", d, data, i)
            f.emit("ret", d)
            f.emit("label", l_bad)
            f.emit("call", None, "__vec_fail", [])
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__vec_get_n")
            h, i, dstp = f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [h, i, dstp])
            ln = f.new_v()
            f.emit("load", ln, h, ("imm", 1))
            b = f.new_v()
            l_bad2, l_ok2 = f.label("vgn.b"), f.label("vgn.k")
            # v2.66：一次无符号比较覆盖 [0, len)
            f.emit("cmpset", "b", b, i, ln)
            f.emit("jz", b, l_bad2)
            data = f.new_v()
            f.emit("load", data, h, ("imm", 0))
            ew = f.new_v()
            f.emit("load", ew, h, ("imm", 3))
            off = f.new_v()
            f.emit("bin", "mul", off, i, ew)
            f.emit("bin", "shl", off, off, ("imm", 3))
            src = f.new_v()
            f.emit("bin", "add", src, data, off)
            nbytes = f.new_v()
            f.emit("bin", "shl", nbytes, ew, ("imm", 3))
            f.emit("call", None, "__memcpy", [dstp, src, nbytes])
            f.emit("ret", dstp)
            f.emit("label", l_bad2)
            f.emit("call", None, "__vec_fail", [])
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__vec_set")
            h, i, v = f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [h, i, v])
            ln = f.new_v()
            f.emit("load", ln, h, ("imm", 1))
            b = f.new_v()
            l_bad3, _l_ok3 = f.label("vs.b"), f.label("vs.k")
            # v2.66：一次无符号比较覆盖 [0, len)
            f.emit("cmpset", "b", b, i, ln)
            f.emit("jz", b, l_bad3)
            data = f.new_v()
            f.emit("load", data, h, ("imm", 0))
            f.emit("store", data, i, v)
            f.emit("ret", ("imm", 0))
            f.emit("label", l_bad3)
            f.emit("call", None, "__vec_fail", [])
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__vec_set_n")
            h, i, srcp = f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [h, i, srcp])
            ln = f.new_v()
            f.emit("load", ln, h, ("imm", 1))
            b = f.new_v()
            l_bad4 = f.label("vsn.b")
            # v2.66：一次无符号比较覆盖 [0, len)
            f.emit("cmpset", "b", b, i, ln)
            f.emit("jz", b, l_bad4)
            data = f.new_v()
            f.emit("load", data, h, ("imm", 0))
            ew = f.new_v()
            f.emit("load", ew, h, ("imm", 3))
            off = f.new_v()
            f.emit("bin", "mul", off, i, ew)
            f.emit("bin", "shl", off, off, ("imm", 3))
            dst = f.new_v()
            f.emit("bin", "add", dst, data, off)
            nbytes = f.new_v()
            f.emit("bin", "shl", nbytes, ew, ("imm", 3))
            f.emit("call", None, "__memcpy", [dst, srcp, nbytes])
            f.emit("ret", ("imm", 0))
            f.emit("label", l_bad4)
            f.emit("call", None, "__vec_fail", [])
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__vec_pop")
            h = f.new_v()
            f.emit("args", [h])
            ln = f.new_v()
            f.emit("load", ln, h, ("imm", 1))
            b = f.new_v()
            l_bad5 = f.label("vx.b")
            f.emit("cmpset", "le", b, ln, ("imm", 0))
            f.emit("jnz", b, l_bad5)
            ln1 = f.new_v()
            f.emit("bin", "sub", ln1, ln, ("imm", 1))
            f.emit("store", h, ("imm", 1), ln1)
            data = f.new_v()
            f.emit("load", data, h, ("imm", 0))
            d = f.new_v()
            f.emit("load", d, data, ln1)
            f.emit("ret", d)
            f.emit("label", l_bad5)
            f.emit("call", None, "__vec_fail", [])
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__vec_pop_n")
            h, dstp = f.new_v(), f.new_v()
            f.emit("args", [h, dstp])
            ln = f.new_v()
            f.emit("load", ln, h, ("imm", 1))
            b = f.new_v()
            l_bad6 = f.label("vxn.b")
            f.emit("cmpset", "le", b, ln, ("imm", 0))
            f.emit("jnz", b, l_bad6)
            ln1 = f.new_v()
            f.emit("bin", "sub", ln1, ln, ("imm", 1))
            f.emit("store", h, ("imm", 1), ln1)
            data = f.new_v()
            f.emit("load", data, h, ("imm", 0))
            ew = f.new_v()
            f.emit("load", ew, h, ("imm", 3))
            off = f.new_v()
            f.emit("bin", "mul", off, ln1, ew)
            f.emit("bin", "shl", off, off, ("imm", 3))
            src = f.new_v()
            f.emit("bin", "add", src, data, off)
            nbytes = f.new_v()
            f.emit("bin", "shl", nbytes, ew, ("imm", 3))
            f.emit("call", None, "__memcpy", [dstp, src, nbytes])
            f.emit("ret", dstp)
            f.emit("label", l_bad6)
            f.emit("call", None, "__vec_fail", [])
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        if self.uses_str_cmp:
            # __str_cmp(a, b) -> -1 / 0 / 1：按无符号字节字典序
            f = Fn("__str_cmp")
            pa, pb = f.new_v(), f.new_v()
            f.emit("args", [pa, pb])
            i = f.new_v()
            f.emit("mov", i, ("imm", 0))
            ca, cb, bb = f.new_v(), f.new_v(), f.new_v()
            l_top, l_same = f.label("sc.t"), f.label("sc.s")
            l_gt, l_eq, l_end = f.label("sc.g"), f.label("sc.e"), f.label("sc.x")
            f.emit("label", l_top)
            f.emit("load8", ca, pa, i)
            f.emit("load8", cb, pb, i)
            f.emit("cmpset", "e", bb, ca, cb)
            f.emit("jnz", bb, l_same)
            f.emit("cmpset", "l", bb, ca, cb)
            f.emit("jz", bb, l_gt)
            f.emit("ret", ("imm", -1))
            f.emit("label", l_gt)
            f.emit("ret", ("imm", 1))
            f.emit("label", l_same)
            f.emit("jz", ca, l_eq)
            f.emit("bin", "add", i, i, ("imm", 1))
            f.emit("jmp", l_top)
            f.emit("label", l_eq)
            f.emit("ret", ("imm", 0))
            f.emit("label", l_end)
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        if self.uses_io:
            msg = "quelmara: read_text() failed (fail-fast)\n"
            gid_io = self.intern_str(msg)
            f = Fn("__read_fail")
            f.emit("args", [])
            bp = f.new_v()
            f.emit("movaddr", bp, gid_io)
            self.emit_write(f, 2, bp, ("imm", len(msg.encode("utf-8"))))
            self.emit_exit(f, ("imm", 1))
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__read_text")
            p = f.new_v()
            f.emit("args", [p])
            b = f.new_v()
            l_fail = f.label("rdbad")
            if self.platform == "windows":
                # CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING,
                #             FILE_ATTRIBUTE_NORMAL, 0)
                h = f.new_v()
                f.emit("winapi", h, "CreateFileA",
                       [p, ("imm", 0x80000000), ("imm", 1), ("imm", 0),
                        ("imm", 3), ("imm", 0x80), ("imm", 0)])
                f.emit("cmpset", "e", b, h, ("imm", -1))
                f.emit("jnz", b, l_fail)
                size = f.new_v()
                f.emit("winapi", size, "GetFileSize", [h, ("imm", 0)])
                n1 = f.new_v()
                f.emit("bin", "add", n1, size, ("imm", 9))
                buf = f.new_v()
                f.emit("call", buf, "__alloc", [n1])
                rbuf = f.new_v()
                f.emit("bin", "add", rbuf, buf, ("imm", 8))
                wptr = f.new_v()
                f.emit("movaddr", wptr, self.written_gid)
                okv = f.new_v()
                f.emit("winapi", okv, "ReadFile", [h, rbuf, size, wptr, ("imm", 0)])
                f.emit("jz", okv, l_fail)
                got = f.new_v()
                f.emit("load", got, ("ga", self.written_gid), ("imm", 0))
                f.emit("store", buf, ("imm", 0), got)      # 长度前缀
                z = f.new_v()
                f.emit("bin", "add", z, rbuf, got)
                f.emit("store8", z, ("imm", 0), ("imm", 0))
                f.emit("winapi", None, "CloseHandle", [h])
                f.emit("ret", rbuf)
            else:
                fd = f.new_v()
                f.emit("syscall", fd, self.sc["openat"],
                       [("imm", -100), p, ("imm", 0), ("imm", 0)])
                f.emit("cmpset", "l", b, fd, ("imm", 0))
                f.emit("jnz", b, l_fail)
                cap = ("imm", 1 << 20)
                buf = f.new_v()
                f.emit("call", buf, "__alloc", [("imm", (1 << 20) + 9)])
                rbuf = f.new_v()
                f.emit("bin", "add", rbuf, buf, ("imm", 8))
                got = f.new_v()
                f.emit("syscall", got, self.sc["read"], [fd, rbuf, cap])
                f.emit("cmpset", "l", b, got, ("imm", 0))
                f.emit("jnz", b, l_fail)
                f.emit("store", buf, ("imm", 0), got)      # 长度前缀
                z = f.new_v()
                f.emit("bin", "add", z, rbuf, got)
                f.emit("store8", z, ("imm", 0), ("imm", 0))
                f.emit("syscall", None, self.sc["close"], [fd])
                f.emit("ret", rbuf)
            f.emit("label", l_fail)
            f.emit("call", None, "__read_fail", [])
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            # __write_fail：写文件失败统一走这里（stderr + exit 1）
            msg_w = "quelmara: write_text() failed (fail-fast)\n"
            gid_w = self.intern_str(msg_w)
            f = Fn("__write_fail")
            f.emit("args", [])
            bp = f.new_v()
            f.emit("movaddr", bp, gid_w)
            self.emit_write(f, 2, bp, ("imm", len(msg_w.encode("utf-8"))))
            self.emit_exit(f, ("imm", 1))
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            # __write_text(path, content) -> written：覆盖写整文件。
            # 与 __read_text 同构：Windows winapi / POSIX raw syscall，
            # 其余逻辑架构无关（同一 QuIR，a64 只换 syscall 号与发射层）。
            f = Fn("__write_text")
            p = f.new_v()
            c = f.new_v()
            f.emit("args", [p, c])
            b = f.new_v()
            l_fail = f.label("wrbad")
            if self.platform == "windows":
                # CreateFileA(path, GENERIC_WRITE, 0, 0, CREATE_ALWAYS,
                #             FILE_ATTRIBUTE_NORMAL, 0)
                h = f.new_v()
                f.emit("winapi", h, "CreateFileA",
                       [p, ("imm", 0x40000000), ("imm", 0), ("imm", 0),
                        ("imm", 2), ("imm", 0x80), ("imm", 0)])
                f.emit("cmpset", "e", b, h, ("imm", -1))
                f.emit("jnz", b, l_fail)
                n = f.new_v()
                f.emit("call", n, "__str_len", [c])
                wptr = f.new_v()
                f.emit("movaddr", wptr, self.written_gid)
                okv = f.new_v()
                f.emit("winapi", okv, "WriteFile", [h, c, n, wptr, ("imm", 0)])
                f.emit("jz", okv, l_fail)
                got = f.new_v()
                f.emit("load", got, ("ga", self.written_gid), ("imm", 0))
                f.emit("winapi", None, "CloseHandle", [h])
                f.emit("ret", got)
            else:
                # openat(AT_FDCWD, path, O_WRONLY|O_CREAT|O_TRUNC, 0644)
                fd = f.new_v()
                f.emit("syscall", fd, self.sc["openat"],
                       [("imm", -100), p, ("imm", 0x241), ("imm", 0o644)])
                f.emit("cmpset", "l", b, fd, ("imm", 0))
                f.emit("jnz", b, l_fail)
                n2 = f.new_v()
                f.emit("call", n2, "__str_len", [c])
                got2 = f.new_v()
                f.emit("syscall", got2, self.sc["write"], [fd, c, n2])
                f.emit("cmpset", "l", b, got2, ("imm", 0))
                f.emit("jnz", b, l_fail)
                f.emit("syscall", None, self.sc["close"], [fd])
                f.emit("ret", got2)
            f.emit("label", l_fail)
            f.emit("call", None, "__write_fail", [])
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        if self.uses_strmem:
            # __str_alloc(n) -> str：分配 [n][bytes][NUL] 块，len 头写 0、
            # NUL 已置，返回数据指针（str 值约定）。调用方用 mem_copy /
            # mem_store8 批量填内容后即可当 str 用。
            # __str_from_mem(data, n) -> str：从内存区间拷贝构造。
            # 两者都是 str ABI 的正规批量构造器（v1.14），O(n) 且零逐字节 call。
            f = Fn("__str_alloc")
            nn = f.new_v()
            f.emit("args", [nn])
            tot = f.new_v()
            f.emit("bin", "add", tot, nn, ("imm", 9))
            h = f.new_v()
            f.emit("call", h, "__alloc", [tot])
            # 约定：str 值 = 数据指针（h+8），len 头在数据指针前 8 字节（h）
            f.emit("store", h, ("imm", 0), nn)
            end = f.new_v()
            f.emit("bin", "add", end, h, nn)
            f.emit("store8", end, ("imm", 8), ("imm", 0))
            dp = f.new_v()
            f.emit("bin", "add", dp, h, ("imm", 8))
            f.emit("ret", dp)
            self.out.append(f)

            f = Fn("__str_from_mem")
            sp, sn = f.new_v(), f.new_v()
            f.emit("args", [sp, sn])
            tot2 = f.new_v()
            f.emit("bin", "add", tot2, sn, ("imm", 9))
            h2 = f.new_v()
            f.emit("call", h2, "__alloc", [tot2])
            f.emit("store", h2, ("imm", 0), sn)
            dst = f.new_v()
            f.emit("bin", "add", dst, h2, ("imm", 8))
            f.emit("call", None, "__memcpy", [dst, sp, sn])
            end2 = f.new_v()
            f.emit("bin", "add", end2, dst, sn)
            f.emit("store8", end2, ("imm", 0), ("imm", 0))
            f.emit("ret", dst)
            self.out.append(f)

        if self.uses_sfb:
            # __str_from_bytes(v: vec[int]) -> str：取各槽低字节拼成 NUL 结尾串。
            # O(n) 一次分配——替代 str `+` 累积的 O(n^2)（自举解析器热点）。
            # v1.5.1 长度前缀：[ln][字节][NUL]，返回 +8
            f = Fn("__str_from_bytes")
            v = f.new_v()
            f.emit("args", [v])
            ln = f.new_v()
            f.emit("load", ln, v, ("imm", 1))
            ptr = f.new_v()
            f.emit("load", ptr, v, ("imm", 0))
            n1 = f.new_v()
            f.emit("bin", "add", n1, ln, ("imm", 9))
            h = f.new_v()
            f.emit("call", h, "__alloc", [n1])
            f.emit("store", h, ("imm", 0), ln)            # 长度前缀
            buf = f.new_v()
            f.emit("bin", "add", buf, h, ("imm", 8))
            iv = f.new_v()
            f.emit("mov", iv, ("imm", 0))
            l_loop = f.label("sfb")
            l_done = f.label("sfbd")
            f.emit("label", l_loop)
            f.emit("jcc", "ge", iv, ln, l_done)
            off = f.new_v()
            f.emit("bin", "shl", off, iv, ("imm", 3))
            addr = f.new_v()
            f.emit("bin", "add", addr, ptr, off)
            b = f.new_v()
            f.emit("load8", b, addr, ("imm", 0))
            f.emit("store8", buf, iv, b)
            f.emit("bin", "add", iv, iv, ("imm", 1))
            f.emit("jmp", l_loop)
            f.emit("label", l_done)
            f.emit("store8", buf, ln, ("imm", 0))
            f.emit("ret", buf)
            self.out.append(f)

        if self.uses_memcpy:
            # __memcopy(dst, off, src, n)：dst[off..off+n) <- src[0..n)
            f = Fn("__memcopy")
            dst = f.new_v()
            off = f.new_v()
            s = f.new_v()
            cnt = f.new_v()
            f.emit("args", [dst, off, s, cnt])
            iv = f.new_v()
            f.emit("mov", iv, ("imm", 0))
            l_loop = f.label("mc")
            l_done = f.label("mcd")
            f.emit("label", l_loop)
            f.emit("jcc", "ge", iv, cnt, l_done)
            saddr = f.new_v()
            f.emit("bin", "add", saddr, s, iv)     # src 是 str：字节连续，直接 +i
            b = f.new_v()
            f.emit("load8", b, saddr, ("imm", 0))
            doff = f.new_v()
            f.emit("bin", "add", doff, off, iv)
            f.emit("store8", dst, doff, b)
            f.emit("bin", "add", iv, iv, ("imm", 1))
            f.emit("jmp", l_loop)
            f.emit("label", l_done)
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        if self.uses_net:
            # ---- 原生 socket 运行时（同一条 QuIR：Windows winapi / Linux syscall）----
            # 每步独立 fail 函数（无参 + exit(1)，与 __read_fail 同款；
            # 消息文本区分失败步骤，stderr 直接可读）
            for tag in ("socket", "bind", "listen", "accept", "send", "recv", "connect"):
                msg_n = "quelmara: tcp_" + tag + "() failed (fail-fast)\n"
                gid_nf = self.intern_str(msg_n)
                f = Fn("__net_fail_" + tag)
                f.emit("args", [])
                if self.platform == "windows":
                    err = f.new_v()
                    f.emit("winapi", err, "WSAGetLastError", [])
                    f.emit("call", None, "__print_i64", [err])   # stdout 错误码
                bp = f.new_v()
                f.emit("movaddr", bp, gid_nf)
                self.emit_write(f, 2, bp, ("imm", len(msg_n.encode("utf-8"))))
                self.emit_exit(f, ("imm", 1))
                f.emit("ret", ("imm", 0))
                self.out.append(f)

            def net_fail(f, lb, tag):
                f.emit("label", lb)
                f.emit("call", None, "__net_fail_" + tag, [])
                f.emit("ret", ("imm", 0))

            # __tcp_listen(port) -> fd
            f = Fn("__tcp_listen")
            p = f.new_v()
            f.emit("args", [p])
            b = f.new_v()
            l_fs = f.label("netfs")     # socket 失败 -> __net_fail_socket
            l_fb = f.label("netfb")     # bind 失败   -> __net_fail_bind
            l_fl = f.label("netfl")     # listen 失败 -> __net_fail_listen
            if self.platform == "windows":
                gid_wsa = self.intern_array(8)      # WSADATA（64B，内容不读）
                wsa = f.new_v()
                f.emit("movaddr", wsa, gid_wsa)
                sw = f.new_v()
                f.emit("winapi", sw, "WSAStartup", [("imm", 0x202), wsa])
                f.emit("jnz", sw, l_fs)             # 非 0 = 失败（码 11 同类）
                s = f.new_v()
                f.emit("winapi", s, "socket",
                       [("imm", 2), ("imm", 1), ("imm", 0)])   # AF_INET, SOCK_STREAM
                # Win64 API 的 int 返回值只写 eax（高 32 位 0 扩展）：
                # SOCKET_ERROR 落在 rax 里是 0x00000000FFFFFFFF 而不是 64 位 -1，
                # 直接与 -1 比较会漏检（踩过：bind/listen 失败被放过，accept 才炸）。
                # 一律先截断到 32 位再与 0xFFFFFFFF 比较。
                # Win64 int 返回值经 shl32+sar32 符号扩展后与 -1 比较

                s32 = f.new_v()

                f.emit("bin", "shl", s32, s, ("imm", 32))

                s322 = f.new_v()

                f.emit("bin", "sar", s322, s32, ("imm", 32))

                f.emit("cmpset", "e", b, s322, ("imm", -1))

                f.emit("jnz", b, l_fs)
            else:
                s = f.new_v()
                f.emit("syscall", s, self.sc["socket"],
                       [("imm", 2), ("imm", 1), ("imm", 0)])
                f.emit("cmpset", "l", b, s, ("imm", 0))
                f.emit("jnz", b, l_fs)
            # sockaddr_in（16B）：用 __alloc 堆缓冲构造（堆指针 store 与
            # read_text 的 store8 buf 同模式；movaddr+store 全局路径实测
            # bind 收到的 family 字节不对，见 CHANGELOG v1.3 调试记录）。
            sinb = f.new_v()
            f.emit("call", sinb, "__alloc", [("imm", 16)])
            if isinstance(p, tuple) and p[0] == "imm":
                port_v = p[1]
                port_be = ((port_v & 0xFF) << 8) | ((port_v >> 8) & 0xFF)
                w0v = 2 | (port_be << 16)
                f.emit("store", sinb, ("imm", 0), ("imm", w0v))
                f.emit("store", sinb, ("imm", 1), ("imm", 0))
            else:
                hp = f.new_v()
                f.emit("bin", "and", hp, p, ("imm", 0xFF))
                hp2 = f.new_v()
                f.emit("bin", "shl", hp2, hp, ("imm", 8))
                hb = f.new_v()
                f.emit("bin", "shr", hb, p, ("imm", 8))
                hb2 = f.new_v()
                f.emit("bin", "and", hb2, hb, ("imm", 0xFF))
                hp3 = f.new_v()
                f.emit("bin", "or", hp3, hp2, hb2)
                # w0 = family(2) | htons(port)<<16 —— family 在低 16 位，
                # port 在位 16-31（此前写成 hp3 | (2<<16)，family 落到了
                # 字节 2-3、port 占了字节 0-1，bind 报 10047 EAFNOSUPPORT）
                sh16 = f.new_v()
                f.emit("bin", "shl", sh16, hp3, ("imm", 16))
                w0 = f.new_v()
                f.emit("bin", "or", w0, sh16, ("imm", 2))
                f.emit("store", sinb, ("imm", 0), w0)
                f.emit("store", sinb, ("imm", 1), ("imm", 0))
            sin = sinb
            if self.platform == "windows":
                br = f.new_v()
                f.emit("winapi", br, "bind", [s, sin, ("imm", 16)])
                # Win64 int 返回值经 shl32+sar32 符号扩展后与 -1 比较

                br32 = f.new_v()

                f.emit("bin", "shl", br32, br, ("imm", 32))

                br322 = f.new_v()

                f.emit("bin", "sar", br322, br32, ("imm", 32))

                f.emit("cmpset", "e", b, br322, ("imm", -1))

                f.emit("jnz", b, l_fb)
                lr = f.new_v()
                f.emit("winapi", lr, "listen", [s, ("imm", 16)])
                # Win64 int 返回值经 shl32+sar32 符号扩展后与 -1 比较

                lr32 = f.new_v()

                f.emit("bin", "shl", lr32, lr, ("imm", 32))

                lr322 = f.new_v()

                f.emit("bin", "sar", lr322, lr32, ("imm", 32))

                f.emit("cmpset", "e", b, lr322, ("imm", -1))

                f.emit("jnz", b, l_fl)
            else:
                br = f.new_v()
                f.emit("syscall", br, self.sc["bind"], [s, sin, ("imm", 16)])
                f.emit("cmpset", "l", b, br, ("imm", 0))
                f.emit("jnz", b, l_fb)
                lr = f.new_v()
                f.emit("syscall", lr, self.sc["listen"], [s, ("imm", 16)])
                f.emit("cmpset", "l", b, lr, ("imm", 0))
                f.emit("jnz", b, l_fl)
            f.emit("ret", s)
            net_fail(f, l_fs, "socket")
            net_fail(f, l_fb, "bind")
            net_fail(f, l_fl, "listen")
            self.out.append(f)

            # __tcp_connect(host, port) -> fd
            #   v1.25：getaddrinfo（系统 DNS + hosts）
            #   v2.07：hints.family 从 AF_INET 放宽到 AF_UNSPEC —— IPv6 字面量
            #   与 AAAA 记录直接可用；socket 家族/类型/协议全部取 ai_*，
            #   sockaddr 按 ai_addrlen 整段拷（v4 16B / v6 28B）。
            #   失败时沿 ai_next 逐个尝试：Windows 对 "localhost" 常先给 ::1，
            #   若服务端只监听 v4，不回溯就等于把原来的可用路径弄丢。
            f = Fn("__tcp_connect")
            host = f.new_v()
            port = f.new_v()
            f.emit("args", [host, port])
            b = f.new_v()
            l_fail = f.label("netfc")
            if self.platform != "windows":
                # ---- POSIX 分支（v2.92）----
                # 以前这里是**无条件**的 WSAStartup/getaddrinfo：Linux 上一编
                # `import std.net` 就死在 "无法发射指令 ('winapi', … 'WSAStartup')"。
                # 现在走 raw syscall：只做 **IPv4 点分字面量** 直连。
                #
                # 为什么不做 DNS：Linux 的解析要走 nsswitch → dlopen 插件 →
                # /etc/resolv.conf 状态机，手写一遍等于把 glibc 的 resolver 抄进来。
                # 本后端的定位是"无 libc 的静态可执行文件"，DNS 交给调用方传字面量
                # （服务端侧本来也只需要 listen，不需要 connect 域名）。
                # 域名会 fail-fast 而不是静默连错地址。
                si = f.new_v()
                f.emit("syscall", si, self.sc["socket"],
                       [("imm", 2), ("imm", 1), ("imm", 0)])      # AF_INET/SOCK_STREAM
                l_ok4 = f.label("netc4ok")
                f.emit("jcc", "ge", si, ("imm", 0), l_ok4)
                f.emit("jmp", l_fail)
                f.emit("label", l_ok4)
                # sockaddr_in（16B）：[0]=family|htons(port)<<16  [1]=IPv4 网络序
                sin4 = f.new_v()
                f.emit("call", sin4, "__alloc", [("imm", 16)])
                # 端口：port_be = ((port&0xFF)<<8) | ((port>>8)&0xFF)
                ph = f.new_v()
                f.emit("bin", "and", ph, port, ("imm", 0xFF))
                ph2 = f.new_v()
                f.emit("bin", "shl", ph2, ph, ("imm", 8))
                pl = f.new_v()
                f.emit("bin", "shr", pl, port, ("imm", 8))
                pl2 = f.new_v()
                f.emit("bin", "and", pl2, pl, ("imm", 0xFF))
                pbe = f.new_v()
                f.emit("bin", "or", pbe, ph2, pl2)
                psh = f.new_v()
                f.emit("bin", "shl", psh, pbe, ("imm", 16))
                w0 = f.new_v()
                f.emit("bin", "or", w0, psh, ("imm", 2))
                f.emit("store", sin4, ("imm", 0), w0)
                # IPv4：把点分字面量解析成 32 位网络序（4 段，每段 0..255）
                # 状态：acc = 已收好的段（大端累积）；oct_v = 当前段值；i = 下标
                acc = f.new_v()
                f.emit("mov", acc, ("imm", 0))
                oct_v = f.new_v()
                f.emit("mov", oct_v, ("imm", 0))
                nseg = f.new_v()
                f.emit("mov", nseg, ("imm", 0))
                i = f.new_v()
                f.emit("mov", i, ("imm", 0))
                l_loop = f.label("netc4lp")
                l_done = f.label("netc4dn")
                l_seg = f.label("netc4sg")
                l_next = f.label("netc4nx")
                l_dig = f.label("netc4dg")
                f.emit("label", l_loop)
                ch = f.new_v()
                f.emit("load8", ch, host, i)
                f.emit("jz", ch, l_done)
                isdot = f.new_v()
                f.emit("cmpset", "e", isdot, ch, ("imm", 46))
                f.emit("jnz", isdot, l_seg)
                # 数字判定用无符号区间：48 <= ch <= 57
                f.emit("jcc", "b", ch, ("imm", 48), l_fail)    # < '0'
                f.emit("jcc", "b", ch, ("imm", 58), l_dig)     # < ':' -> 是数字
                f.emit("jmp", l_fail)                          # > '9'
                f.emit("label", l_dig)
                # oct_v = oct_v*10 + (ch - 48)
                t10 = f.new_v()
                f.emit("bin", "mul", t10, oct_v, ("imm", 10))
                dv = f.new_v()
                f.emit("bin", "sub", dv, ch, ("imm", 48))
                ov = f.new_v()
                f.emit("bin", "add", ov, t10, dv)
                f.emit("mov", oct_v, ov)
                f.emit("label", l_next)
                f.emit("bin", "add", i, i, ("imm", 1))
                f.emit("jmp", l_loop)
                f.emit("label", l_seg)
                seg = f.new_v()
                f.emit("bin", "shl", seg, acc, ("imm", 8))
                f.emit("bin", "or", seg, seg, oct_v)
                f.emit("mov", acc, seg)
                f.emit("mov", oct_v, ("imm", 0))
                f.emit("bin", "add", nseg, nseg, ("imm", 1))
                f.emit("bin", "add", i, i, ("imm", 1))
                f.emit("jmp", l_loop)
                f.emit("label", l_done)
                # 必须正好 4 段，否则不是合法 IPv4 字面量
                f.emit("cmpset", "e", b, nseg, ("imm", 3))
                f.emit("jz", b, l_fail)
                # 最后一段收尾
                seg2 = f.new_v()
                f.emit("bin", "shl", seg2, acc, ("imm", 8))
                f.emit("bin", "or", seg2, seg2, oct_v)
                f.emit("store", sin4, ("imm", 1), seg2)
                cr = f.new_v()
                f.emit("syscall", cr, self.sc["connect"], [si, sin4, ("imm", 16)])
                l_crok = f.label("netc4cr")
                f.emit("jcc", "ge", cr, ("imm", 0), l_crok)
                f.emit("syscall", None, self.sc["close"], [si])
                f.emit("jmp", l_fail)
                f.emit("label", l_crok)
                f.emit("ret", si)
                f.emit("label", l_fail)
                f.emit("call", None, "__net_fail_connect", [])
                f.emit("ret", ("imm", 0))
                self.out.append(f)
            else:
                gid_wsa2 = self.intern_array(8)
                wsa2 = f.new_v()
                f.emit("movaddr", wsa2, gid_wsa2)
                sw2 = f.new_v()
                f.emit("winapi", sw2, "WSAStartup", [("imm", 0x202), wsa2])
                f.emit("jnz", sw2, l_fail)
                # hints（48B）：family=AF_UNSPEC(0)@4、socktype=SOCK_STREAM(1)@8、
                # protocol=IPPROTO_TCP(6)@12，其余 0
                hints = f.new_v()
                f.emit("call", hints, "__alloc", [("imm", 48)])
                for slot in range(6):
                    f.emit("store", hints, ("imm", slot), ("imm", 0))
                f.emit("store8", hints, ("imm", 4), ("imm", 0))
                f.emit("store8", hints, ("imm", 8), ("imm", 1))
                f.emit("store8", hints, ("imm", 12), ("imm", 6))
                # PADDRINFOA *res = NULL
                res = f.new_v()
                f.emit("call", res, "__alloc", [("imm", 8)])
                f.emit("store", res, ("imm", 0), ("imm", 0))
                gr = f.new_v()
                f.emit("winapi", gr, "getaddrinfo", [host, ("imm", 0), hints, res])
                f.emit("jnz", gr, l_fail)
                # head 留给 freeaddrinfo（链表中间节点不能直接 free）
                head = f.new_v()
                f.emit("load", head, res, ("imm", 0))
                f.emit("jz", head, l_fail)
                ai = f.new_v()
                f.emit("mov", ai, head)
                s = f.new_v()
                f.emit("mov", s, ("imm", 0))
                # 端口高/低字节（网络序）：sockaddr_in 与 sockaddr_in6 的端口
                # 都在字节 2/3，算一次两个家族共用
                hi = f.new_v()
                f.emit("bin", "shr", hi, port, ("imm", 8))
                f.emit("bin", "and", hi, hi, ("imm", 0xFF))
                lo = f.new_v()
                f.emit("bin", "and", lo, port, ("imm", 0xFF))
                l_try = f.label("netct")
                l_retry = f.label("netcr")
                l_ok = f.label("netco")
                f.emit("label", l_try)
                f.emit("jz", ai, l_fail)                   # 链表走完仍失败
                fam = f.new_v()
                f.emit("load8", fam, ai, ("imm", 4))       # ai_family（低字节即可）
                sty = f.new_v()
                f.emit("load8", sty, ai, ("imm", 8))       # ai_socktype
                pro = f.new_v()
                f.emit("load8", pro, ai, ("imm", 12))      # ai_protocol
                alen = f.new_v()
                f.emit("load", alen, ai, ("imm", 2))       # ai_addrlen（字节 16）
                # sockaddr 缓冲 32B（v6 28B 够用；多给 4B 留 scope_id 余量）
                sin = f.new_v()
                f.emit("call", sin, "__alloc", [("imm", 32)])
                addr = f.new_v()
                f.emit("load", addr, ai, ("imm", 4))       # ai_addr 在字节 32
                f.emit("call", None, "__memcpy", [sin, addr, alen])
                f.emit("store8", sin, ("imm", 2), hi)
                f.emit("store8", sin, ("imm", 3), lo)
                cs = f.new_v()
                f.emit("winapi", cs, "socket", [fam, sty, pro])
                cs32 = f.new_v()
                f.emit("bin", "shl", cs32, cs, ("imm", 32))
                cs322 = f.new_v()
                f.emit("bin", "sar", cs322, cs32, ("imm", 32))
                f.emit("cmpset", "e", b, cs322, ("imm", -1))
                f.emit("jnz", b, l_retry)
                cr = f.new_v()
                f.emit("winapi", cr, "connect", [cs, sin, alen])
                cr32 = f.new_v()
                f.emit("bin", "shl", cr32, cr, ("imm", 32))
                cr322 = f.new_v()
                f.emit("bin", "sar", cr322, cr32, ("imm", 32))
                f.emit("cmpset", "e", b, cr322, ("imm", -1))
                f.emit("jnz", b, l_retry)
                f.emit("mov", s, cs)
                f.emit("jmp", l_ok)
                f.emit("label", l_retry)
                f.emit("winapi", None, "closesocket", [cs])   # socket 失败时 -1 无害
                nxt = f.new_v()
                f.emit("load", nxt, ai, ("imm", 5))        # ai_next 在字节 40
                f.emit("mov", ai, nxt)
                f.emit("jmp", l_try)
                f.emit("label", l_ok)
                f.emit("winapi", None, "freeaddrinfo", [head])
                f.emit("ret", s)
                f.emit("label", l_fail)
                f.emit("call", None, "__net_fail_connect", [])
                f.emit("ret", ("imm", 0))
                self.out.append(f)

            # __tcp_listen6(port) -> fd（v2.07，AF_INET6 + 双栈）
            # sockaddr_in6（28B）：family(u16) port(u16) flowinfo(u32)
            #                     addr(16B, :: = 全 0) scope_id(u32)
            # 只写 w0（family | htons(port)<<16）与 w1..w3 = 0，即绑 ::。
            if self.platform == "windows":
                f = Fn("__tcp_listen6")
                p6 = f.new_v()
                f.emit("args", [p6])
                b6 = f.new_v()
                l6_fs = f.label("net6fs")
                l6_fb = f.label("net6fb")
                l6_fl = f.label("net6fl")
                gid_wsa6 = self.intern_array(8)
                wsa6 = f.new_v()
                f.emit("movaddr", wsa6, gid_wsa6)
                sw6 = f.new_v()
                f.emit("winapi", sw6, "WSAStartup", [("imm", 0x202), wsa6])
                f.emit("jnz", sw6, l6_fs)
                s6 = f.new_v()
                f.emit("winapi", s6, "socket",
                       [("imm", 23), ("imm", 1), ("imm", 0)])   # AF_INET6, SOCK_STREAM
                s632 = f.new_v()
                f.emit("bin", "shl", s632, s6, ("imm", 32))
                s6322 = f.new_v()
                f.emit("bin", "sar", s6322, s632, ("imm", 32))
                f.emit("cmpset", "e", b6, s6322, ("imm", -1))
                f.emit("jnz", b6, l6_fs)
                # IPV6_V6ONLY=0：Windows 默认 1，不开就等于"只接 v6"，
                # 双栈部署要的是同一个端口同时接 v4（映射地址）。
                f.emit("store", ("ga", gid_wsa6), ("imm", 0), ("imm", 0))
                f.emit("winapi", None, "setsockopt",
                       [s6, ("imm", 41), ("imm", 27), ("ga", gid_wsa6), ("imm", 4)])
                sin6 = f.new_v()
                f.emit("call", sin6, "__alloc", [("imm", 32)])
                for slot in range(4):
                    f.emit("store", sin6, ("imm", slot), ("imm", 0))
                if isinstance(p6, tuple) and p6[0] == "imm":
                    port_v = p6[1]
                    port_be = ((port_v & 0xFF) << 8) | ((port_v >> 8) & 0xFF)
                    f.emit("store", sin6, ("imm", 0), ("imm", 23 | (port_be << 16)))
                else:
                    hp6 = f.new_v()
                    f.emit("bin", "and", hp6, p6, ("imm", 0xFF))
                    hp62 = f.new_v()
                    f.emit("bin", "shl", hp62, hp6, ("imm", 8))
                    hb6 = f.new_v()
                    f.emit("bin", "shr", hb6, p6, ("imm", 8))
                    hb62 = f.new_v()
                    f.emit("bin", "and", hb62, hb6, ("imm", 0xFF))
                    hp63 = f.new_v()
                    f.emit("bin", "or", hp63, hp62, hb62)
                    sh6 = f.new_v()
                    f.emit("bin", "shl", sh6, hp63, ("imm", 16))
                    w60 = f.new_v()
                    f.emit("bin", "or", w60, sh6, ("imm", 23))
                    f.emit("store", sin6, ("imm", 0), w60)
                br6 = f.new_v()
                f.emit("winapi", br6, "bind", [s6, sin6, ("imm", 28)])
                br632 = f.new_v()
                f.emit("bin", "shl", br632, br6, ("imm", 32))
                br6322 = f.new_v()
                f.emit("bin", "sar", br6322, br632, ("imm", 32))
                f.emit("cmpset", "e", b6, br6322, ("imm", -1))
                f.emit("jnz", b6, l6_fb)
                lr6 = f.new_v()
                f.emit("winapi", lr6, "listen", [s6, ("imm", 16)])
                lr632 = f.new_v()
                f.emit("bin", "shl", lr632, lr6, ("imm", 32))
                lr6322 = f.new_v()
                f.emit("bin", "sar", lr6322, lr632, ("imm", 32))
                f.emit("cmpset", "e", b6, lr6322, ("imm", -1))
                f.emit("jnz", b6, l6_fl)
                f.emit("ret", s6)
                net_fail(f, l6_fs, "socket")
                net_fail(f, l6_fb, "bind")
                net_fail(f, l6_fl, "listen")
                self.out.append(f)

            if self.uses_peer:
                # __tcp_peer_raw(fd) -> str（v2.07，getpeername 的字节视图）
                # 20 字节：[0..1] 端口网络序 | [2] family | [3] 0 | [4..19] 地址
                # getpeername 失败（fd 已关）时 name 保持全 0 -> family=0、地址全 0，
                # 库层按"未知"处理，不在这里开失败分支。
                f = Fn("__tcp_peer_raw")
                pfd = f.new_v()
                f.emit("args", [pfd])
                name = f.new_v()
                f.emit("call", name, "__alloc", [("imm", 32)])
                for slot in range(4):               # 全 0：失败时 family 读出来就是 0
                    f.emit("store", name, ("imm", slot), ("imm", 0))
                lp = f.new_v()
                f.emit("call", lp, "__alloc", [("imm", 8)])
                f.emit("store", lp, ("imm", 0), ("imm", 28))
                f.emit("winapi", None, "getpeername", [pfd, name, lp])
                raw = f.new_v()
                f.emit("call", raw, "__alloc", [("imm", 24)])
                for slot in range(3):               # 24B 全 0（v4 时地址后半段就是 0）
                    f.emit("store", raw, ("imm", slot), ("imm", 0))
                ph = f.new_v()
                f.emit("load8", ph, name, ("imm", 2))
                f.emit("store8", raw, ("imm", 0), ph)
                pl = f.new_v()
                f.emit("load8", pl, name, ("imm", 3))
                f.emit("store8", raw, ("imm", 1), pl)
                pfam = f.new_v()
                f.emit("load8", pfam, name, ("imm", 0))
                f.emit("store8", raw, ("imm", 2), pfam)
                bpf = f.new_v()
                l_pv6 = f.label("peer6")
                l_pdone = f.label("peerd")
                f.emit("cmpset", "e", bpf, pfam, ("imm", 23))
                f.emit("jnz", bpf, l_pv6)
                # v4（或未知）：sockaddr_in 的地址在字节 4，拷 4B 到 raw+4
                rd4 = f.new_v()
                f.emit("bin", "add", rd4, raw, ("imm", 4))
                nd4 = f.new_v()
                f.emit("bin", "add", nd4, name, ("imm", 4))
                f.emit("call", None, "__memcpy", [rd4, nd4, ("imm", 4)])
                f.emit("jmp", l_pdone)
                f.emit("label", l_pv6)
                # v6：sockaddr_in6 的地址在字节 8，拷 16B 到 raw+4
                rd6 = f.new_v()
                f.emit("bin", "add", rd6, raw, ("imm", 4))
                nd6 = f.new_v()
                f.emit("bin", "add", nd6, name, ("imm", 8))
                f.emit("call", None, "__memcpy", [rd6, nd6, ("imm", 16)])
                f.emit("label", l_pdone)
                ps = f.new_v()
                f.emit("call", ps, "__str_from_mem", [raw, ("imm", 20)])
                f.emit("ret", ps)
                self.out.append(f)


            # __tcp_accept(fd) -> conn（阻塞）
            f = Fn("__tcp_accept")
            fd = f.new_v()
            f.emit("args", [fd])
            b = f.new_v()
            l_fail = f.label("netbad")
            if self.platform == "windows":
                c = f.new_v()
                f.emit("winapi", c, "accept", [fd, ("imm", 0), ("imm", 0)])
                # Win64 int 返回值经 shl32+sar32 符号扩展后与 -1 比较

                c32 = f.new_v()

                f.emit("bin", "shl", c32, c, ("imm", 32))

                c322 = f.new_v()

                f.emit("bin", "sar", c322, c32, ("imm", 32))

                f.emit("cmpset", "e", b, c322, ("imm", -1))

                f.emit("jnz", b, l_fail)
            else:
                c = f.new_v()
                f.emit("syscall", c, self.sc["accept"],
                       [fd, ("imm", 0), ("imm", 0)])
                f.emit("cmpset", "l", b, c, ("imm", 0))
                f.emit("jnz", b, l_fail)
            f.emit("ret", c)
            net_fail(f, l_fail, "accept")
            self.out.append(f)

            # __tcp_send(fd, str) -> n
            f = Fn("__tcp_send")
            fd = f.new_v()
            c = f.new_v()
            f.emit("args", [fd, c])
            b = f.new_v()
            l_fail = f.label("netbad")
            n = f.new_v()
            f.emit("call", n, "__str_len", [c])
            if self.platform == "windows":
                r = f.new_v()
                f.emit("winapi", r, "send", [fd, c, n, ("imm", 0)])
                # Win64 int 返回值经 shl32+sar32 符号扩展后与 -1 比较

                r32 = f.new_v()

                f.emit("bin", "shl", r32, r, ("imm", 32))

                r322 = f.new_v()

                f.emit("bin", "sar", r322, r32, ("imm", 32))

                f.emit("cmpset", "e", b, r322, ("imm", -1))

                f.emit("jnz", b, l_fail)
            else:
                r = f.new_v()
                f.emit("syscall", r, self.sc["sendto"],
                       [fd, c, n, ("imm", 0), ("imm", 0), ("imm", 0)])
                f.emit("cmpset", "l", b, r, ("imm", 0))
                f.emit("jnz", b, l_fail)
            f.emit("ret", r)
            net_fail(f, l_fail, "send")
            self.out.append(f)

            # __tcp_recv(fd, cap) -> str（对端关闭返回空串）
            # v1.5.1 长度前缀：[n][n 字节][NUL]，返回 +8（n=0 即空串）
            f = Fn("__tcp_recv")
            fd = f.new_v()
            cap = f.new_v()
            f.emit("args", [fd, cap])
            b = f.new_v()
            l_fail = f.label("netbad")
            nb = f.new_v()
            f.emit("bin", "add", nb, cap, ("imm", 9))
            h = f.new_v()
            f.emit("call", h, "__alloc", [nb])
            buf = f.new_v()
            f.emit("bin", "add", buf, h, ("imm", 8))
            if self.platform == "windows":
                n = f.new_v()
                f.emit("winapi", n, "recv", [fd, buf, cap, ("imm", 0)])
                # Win64 int 返回值经 shl32+sar32 符号扩展后与 -1 比较

                n32 = f.new_v()

                f.emit("bin", "shl", n32, n, ("imm", 32))

                n322 = f.new_v()

                f.emit("bin", "sar", n322, n32, ("imm", 32))

                f.emit("cmpset", "e", b, n322, ("imm", -1))

                f.emit("jnz", b, l_fail)
            else:
                n = f.new_v()
                f.emit("syscall", n, self.sc["recvfrom"],
                       [fd, buf, cap, ("imm", 0), ("imm", 0), ("imm", 0)])
                f.emit("cmpset", "l", b, n, ("imm", 0))
                f.emit("jnz", b, l_fail)
            f.emit("store", h, ("imm", 0), n)             # 长度前缀
            z = f.new_v()
            f.emit("bin", "add", z, buf, n)
            f.emit("store8", z, ("imm", 0), ("imm", 0))
            f.emit("ret", buf)
            net_fail(f, l_fail, "recv")
            self.out.append(f)

            # __tcp_send_n(fd, ptr, n) -> n：零拷贝发送（不扫 strlen、不建 str）
            f = Fn("__tcp_send_n")
            fd = f.new_v()
            sp = f.new_v()
            sn = f.new_v()
            f.emit("args", [fd, sp, sn])
            b = f.new_v()
            l_fail = f.label("netbad")
            if self.platform == "windows":
                r = f.new_v()
                f.emit("winapi", r, "send", [fd, sp, sn, ("imm", 0)])
                r32 = f.new_v()
                f.emit("bin", "shl", r32, r, ("imm", 32))
                r322 = f.new_v()
                f.emit("bin", "sar", r322, r32, ("imm", 32))
                f.emit("cmpset", "e", b, r322, ("imm", -1))
                f.emit("jnz", b, l_fail)
            else:
                r = f.new_v()
                f.emit("syscall", r, self.sc["sendto"],
                       [fd, sp, sn, ("imm", 0), ("imm", 0), ("imm", 0)])
                f.emit("cmpset", "l", b, r, ("imm", 0))
                f.emit("jnz", b, l_fail)
            f.emit("ret", r)
            net_fail(f, l_fail, "send")
            self.out.append(f)

            # __tcp_recv_n(fd, ptr, cap) -> n：零拷贝接收（0 = 对端关闭）
            f = Fn("__tcp_recv_n")
            fd = f.new_v()
            rp = f.new_v()
            rc = f.new_v()
            f.emit("args", [fd, rp, rc])
            b = f.new_v()
            l_fail = f.label("netbad")
            if self.platform == "windows":
                n = f.new_v()
                f.emit("winapi", n, "recv", [fd, rp, rc, ("imm", 0)])
                n32 = f.new_v()
                f.emit("bin", "shl", n32, n, ("imm", 32))
                n322 = f.new_v()
                f.emit("bin", "sar", n322, n32, ("imm", 32))
                f.emit("cmpset", "e", b, n322, ("imm", -1))
                f.emit("jnz", b, l_fail)
            else:
                n = f.new_v()
                f.emit("syscall", n, self.sc["recvfrom"],
                       [fd, rp, rc, ("imm", 0), ("imm", 0), ("imm", 0)])
                f.emit("cmpset", "l", b, n, ("imm", 0))
                f.emit("jnz", b, l_fail)
            f.emit("ret", n)
            net_fail(f, l_fail, "recv")
            self.out.append(f)

            # __tcp_close(fd) -> 0
            f = Fn("__tcp_close")
            fd = f.new_v()
            f.emit("args", [fd])
            if self.platform == "windows":
                f.emit("winapi", None, "closesocket", [fd])
            else:
                f.emit("syscall", None, self.sc["close"], [fd])
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        if self.uses_substr:
            msg = "quelmara: substr() range out of bounds (fail-fast)\n"
            gid_s = self.intern_str(msg)
            f = Fn("__substr_fail")
            f.emit("args", [])
            bp = f.new_v()
            f.emit("movaddr", bp, gid_s)
            self.emit_write(f, 2, bp, ("imm", len(msg.encode("utf-8"))))
            self.emit_exit(f, ("imm", 1))
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        if self.uses_args:
            # Linux/AArch64：_start 调用 __qlm_args_boot(argc, argv)，把内核栈上的
            # 原始指针存进全局字（零拷贝，不复制字符串）。
            if self.platform != "windows":
                f = Fn("__qlm_args_boot")
                a, v = f.new_v(), f.new_v()
                f.emit("args", [a, v])
                f.emit("store", ("ga", self.argc_gid), ("imm", 0), a)
                f.emit("store", ("ga", self.argv_gid), ("imm", 0), v)
                f.emit("ret", ("imm", 0))
                self.out.append(f)

                # __unix_args_copy() -> 0（v1.5.1 长度前缀 ABI）：
                # 内核栈上的 argv 是原始 NUL 串（无前缀），首次 args() 时
                # 统一拷贝成 [len][bytes][NUL] 的 str，argv_gid 指向新表。
                # 每个参数一次 O(len) 扫描 + 一次分配，只在启动时发生。
                f = Fn("__unix_args_copy")
                g_ac = self.args_copied_gid()
                done0 = f.label("uacdone")
                fl0 = f.new_v()
                f.emit("load", fl0, ("ga", g_ac), ("imm", 0))
                f.emit("jnz", fl0, done0)                    # 已拷贝过，直接返回
                a0 = f.new_v()
                v0 = f.new_v()
                f.emit("load", a0, ("ga", self.argc_gid), ("imm", 0))
                f.emit("load", v0, ("ga", self.argv_gid), ("imm", 0))
                n0 = f.new_v()
                f.emit("bin", "sub", n0, a0, ("imm", 1))
                l_np, l_nd = f.label("uacnp"), f.label("uacnd")
                f.emit("jcc", "ge", n0, ("imm", 0), l_np)
                f.emit("mov", n0, ("imm", 0))
                f.emit("label", l_np)
                arr0 = f.new_v()
                nb0 = f.new_v()
                f.emit("bin", "mul", nb0, n0, ("imm", 8))
                f.emit("call", arr0, "__alloc", [nb0])
                i0 = f.new_v()
                f.emit("mov", i0, ("imm", 0))
                l_lt, l_ld = f.label("uaclt"), f.label("uacld")
                f.emit("label", l_lt)
                f.emit("jcc", "ge", i0, n0, l_ld)
                # raw = argv[i0+1]（内核栈指针，无前缀）
                idx1 = f.new_v()
                f.emit("bin", "add", idx1, i0, ("imm", 1))
                raw = f.new_v()
                f.emit("load", raw, v0, idx1)
                # 内联 strlen（原始串只能扫）
                j0 = f.new_v()
                f.emit("mov", j0, ("imm", 0))
                l_st, l_sd = f.label("uacst"), f.label("uacsd")
                f.emit("label", l_st)
                bc = f.new_v()
                f.emit("load8", bc, raw, j0)
                f.emit("jz", bc, l_sd)
                f.emit("bin", "add", j0, j0, ("imm", 1))
                f.emit("jmp", l_st)
                f.emit("label", l_sd)
                # tok = alloc(j0+9)；[len][bytes][NUL]
                th = f.new_v()
                f.emit("bin", "add", th, j0, ("imm", 9))
                tok = f.new_v()
                f.emit("call", tok, "__alloc", [th])
                f.emit("store", tok, ("imm", 0), j0)
                tdst = f.new_v()
                f.emit("bin", "add", tdst, tok, ("imm", 8))
                f.emit("call", None, "__memcpy", [tdst, raw, j0])
                tz = f.new_v()
                f.emit("bin", "add", tz, tdst, j0)
                f.emit("store8", tz, ("imm", 0), ("imm", 0))
                f.emit("store", arr0, i0, tdst)
                f.emit("bin", "add", i0, i0, ("imm", 1))
                f.emit("jmp", l_lt)
                f.emit("label", l_ld)
                f.emit("store", ("ga", self.argv_gid), ("imm", 0), arr0)
                f.emit("store", ("ga", g_ac), ("imm", 0), ("imm", 1))
                f.emit("label", done0)
                f.emit("ret", ("imm", 0))
                self.out.append(f)
            else:
                # Windows：加载器不给 argv，只能自己拆命令行。
                # 注意：这里一律用 cmpset + jnz 做比较（和用户代码的 if/while 同源），
                # 不用 jcc+cmp 立即数——那条内部路径在真实程序里不可靠。
                f = Fn("__win_args_init")
                cl = f.new_v()
                f.emit("winapi", cl, "GetCommandLineA", [])
                # cl 是 WinAPI 原始串（无长度前缀），内联扫描求长
                ln = f.new_v()
                f.emit("mov", ln, ("imm", 0))
                l_clt, l_cle = f.label("wacl"), f.label("wacle")
                f.emit("label", l_clt)
                lc = f.new_v()
                f.emit("load8", lc, cl, ln)
                f.emit("jz", lc, l_cle)
                f.emit("bin", "add", ln, ln, ("imm", 1))
                f.emit("jmp", l_clt)
                f.emit("label", l_cle)
                l1 = f.new_v()
                f.emit("bin", "add", l1, ln, ("imm", 1))
                buf = f.new_v()
                f.emit("call", buf, "__alloc", [l1])
                f.emit("call", None, "__memcpy", [buf, cl, l1])

                # ---- 第一遍：数 token（引号内的空白不算分隔）----
                i, ntok, inq, inword = f.new_v(), f.new_v(), f.new_v(), f.new_v()
                for v in (i, ntok, inq, inword):
                    f.emit("mov", v, ("imm", 0))
                c, b = f.new_v(), f.new_v()
                ltop1, lend1 = f.label("wac1"), f.label("wae1")
                l_quote1, l_sep1 = f.label("waq1"), f.label("was1")
                l_word1, l_have1 = f.label("waw1"), f.label("wah1")
                f.emit("label", ltop1)
                f.emit("load8", c, buf, i)
                f.emit("cmpset", "e", b, c, ("imm", 0))
                f.emit("jnz", b, lend1)
                f.emit("cmpset", "e", b, c, ("imm", 34))
                f.emit("jnz", b, l_quote1)
                f.emit("cmpset", "e", b, c, ("imm", 32))
                f.emit("jnz", b, l_sep1)
                f.emit("cmpset", "e", b, c, ("imm", 9))
                f.emit("jnz", b, l_sep1)
                f.emit("label", l_word1)
                f.emit("jnz", inword, l_have1)
                f.emit("bin", "add", ntok, ntok, ("imm", 1))
                f.emit("mov", inword, ("imm", 1))
                f.emit("label", l_have1)
                f.emit("bin", "add", i, i, ("imm", 1))
                f.emit("jmp", ltop1)
                f.emit("label", l_sep1)
                f.emit("jnz", inq, l_word1)        # 引号内空白：算词字符
                f.emit("mov", inword, ("imm", 0))
                f.emit("bin", "add", i, i, ("imm", 1))
                f.emit("jmp", ltop1)
                f.emit("label", l_quote1)
                f.emit("cmpset", "e", b, inq, ("imm", 0))   # 开关翻转
                f.emit("mov", inq, b)
                f.emit("bin", "add", i, i, ("imm", 1))
                f.emit("jmp", ltop1)
                f.emit("label", lend1)

                arr = f.new_v()
                nb = f.new_v()
                f.emit("bin", "mul", nb, ntok, ("imm", 8))
                f.emit("call", arr, "__alloc", [nb])

                # ---- 第二遍：压缩（去掉引号）+ 为每个 token 拷贝带前缀的 str ----
                i2, w, k = f.new_v(), f.new_v(), f.new_v()
                inq2, started = f.new_v(), f.new_v()
                wstart = f.new_v()
                for v in (i2, w, k, inq2, started, wstart):
                    f.emit("mov", v, ("imm", 0))
                c2 = f.new_v()
                ltop2, lend2 = f.label("wbc2"), f.label("wbe2")
                l_quote2, l_sep2 = f.label("wbq2"), f.label("wbs2")
                l_word2, l_started = f.label("wbw2"), f.label("wbst2")
                l_sepd, l_endok = f.label("wbsd2"), f.label("wbend")

                def finish_tok():
                    """token = buf[wstart..w)：拷成 [len][bytes][NUL] 的 str
                    （v1.5.1 长度前缀 ABI），指针写入 arr[k]。"""
                    tln = f.new_v()
                    f.emit("bin", "sub", tln, w, wstart)
                    th = f.new_v()
                    f.emit("bin", "add", th, tln, ("imm", 9))
                    tok = f.new_v()
                    f.emit("call", tok, "__alloc", [th])
                    f.emit("store", tok, ("imm", 0), tln)
                    tdst = f.new_v()
                    f.emit("bin", "add", tdst, tok, ("imm", 8))
                    tsrc = f.new_v()
                    f.emit("bin", "add", tsrc, buf, wstart)
                    f.emit("call", None, "__memcpy", [tdst, tsrc, tln])
                    tz = f.new_v()
                    f.emit("bin", "add", tz, tdst, tln)
                    f.emit("store8", tz, ("imm", 0), ("imm", 0))
                    f.emit("store", arr, k, tdst)
                    f.emit("bin", "add", k, k, ("imm", 1))

                f.emit("label", ltop2)
                f.emit("load8", c2, buf, i2)
                f.emit("cmpset", "e", b, c2, ("imm", 0))
                f.emit("jnz", b, lend2)
                f.emit("cmpset", "e", b, c2, ("imm", 34))
                f.emit("jnz", b, l_quote2)
                f.emit("cmpset", "e", b, c2, ("imm", 32))
                f.emit("jnz", b, l_sep2)
                f.emit("cmpset", "e", b, c2, ("imm", 9))
                f.emit("jnz", b, l_sep2)
                f.emit("label", l_word2)
                f.emit("jnz", started, l_started)
                f.emit("mov", wstart, w)                  # 记词首（结束时才拷贝）
                f.emit("mov", started, ("imm", 1))
                f.emit("label", l_started)
                f.emit("store8", buf, w, c2)
                f.emit("bin", "add", w, w, ("imm", 1))
                f.emit("bin", "add", i2, i2, ("imm", 1))
                f.emit("jmp", ltop2)
                f.emit("label", l_sep2)
                f.emit("jnz", inq2, l_word2)               # 引号内空白保留
                f.emit("jz", started, l_sepd)
                finish_tok()                               # 先收 token（w 未含分隔符）
                f.emit("store8", buf, w, ("imm", 0))       # buf 分隔 NUL（重用缓冲）
                f.emit("bin", "add", w, w, ("imm", 1))
                f.emit("mov", started, ("imm", 0))
                f.emit("label", l_sepd)
                f.emit("bin", "add", i2, i2, ("imm", 1))
                f.emit("jmp", ltop2)
                f.emit("label", l_quote2)
                f.emit("cmpset", "e", b, inq2, ("imm", 0))
                f.emit("mov", inq2, b)
                f.emit("bin", "add", i2, i2, ("imm", 1))
                f.emit("jmp", ltop2)
                f.emit("label", lend2)
                f.emit("jz", started, l_endok)
                finish_tok()                               # 同上：先收 token
                f.emit("store8", buf, w, ("imm", 0))
                f.emit("bin", "add", w, w, ("imm", 1))
                f.emit("label", l_endok)
                f.emit("store", ("ga", self.argv_gid), ("imm", 0), arr)
                f.emit("store", ("ga", self.argc_gid), ("imm", 0), k)
                f.emit("ret", ("imm", 0))
                self.out.append(f)

        if self.uses_str_to_int:
            msg = "quelmara: str.to_int() invalid decimal input (fail-fast)\n"
            gid_f = self.intern_str(msg)
            f = Fn("__str_to_int_fail")
            f.emit("args", [])
            bp = f.new_v()
            f.emit("movaddr", bp, gid_f)
            self.emit_write(f, 2, bp, ("imm", len(msg.encode("utf-8"))))
            self.emit_exit(f, ("imm", 1))
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__str_to_int")
            p = f.new_v()
            f.emit("args", [p])
            i, neg, acc, digits = f.new_v(), f.new_v(), f.new_v(), f.new_v()
            for v in (i, neg, acc, digits):
                f.emit("mov", v, ("imm", 0))
            cc = f.new_v()
            f.emit("load8", cc, p, ("imm", 0))
            l_not_minus = f.label("stnm")
            l_sign_done = f.label("stsd")
            f.emit("jcc", "ne", cc, ("imm", 45), l_not_minus)   # '-'
            f.emit("mov", neg, ("imm", 1))
            f.emit("mov", i, ("imm", 1))
            f.emit("jmp", l_sign_done)
            f.emit("label", l_not_minus)
            f.emit("jcc", "ne", cc, ("imm", 43), l_sign_done)   # '+'
            f.emit("mov", i, ("imm", 1))
            f.emit("label", l_sign_done)

            l_top = f.label("stt")
            l_end = f.label("ste")
            l_fail = f.label("stf")
            l_pos = f.label("stp")
            f.emit("label", l_top)
            f.emit("load8", cc, p, i)          # 原地更新：循环内不得换 vreg
            f.emit("jz", cc, l_end)
            f.emit("jcc", "l", cc, ("imm", 48), l_fail)        # < '0'
            f.emit("jcc", "g", cc, ("imm", 57), l_fail)        # > '9'
            # 溢出前置检查：acc > INT64_MAX/10 时再乘 10 必溢出
            f.emit("jcc", "g", acc, ("imm", 922337203685477580), l_fail)
            f.emit("bin", "mul", acc, acc, ("imm", 10))
            f.emit("bin", "sub", cc, cc, ("imm", 48))
            f.emit("bin", "add", acc, acc, cc)
            # 乘法回绕成负数同样视为溢出（覆盖末位 8/9 的边界情况）
            f.emit("jcc", "l", acc, ("imm", 0), l_fail)
            f.emit("mov", digits, ("imm", 1))
            f.emit("bin", "add", i, i, ("imm", 1))
            f.emit("jmp", l_top)

            f.emit("label", l_end)
            f.emit("jz", digits, l_fail)       # 一位数字都没有
            f.emit("jz", neg, l_pos)
            # 注意：不能用 bin sub acc, imm0, acc —— dst 与 rhs 同为 acc 时
            # 分配器会先写 dst 再读 rhs，结果恒为 0。取反走专用 neg 指令。
            f.emit("neg", acc, acc)
            f.emit("label", l_pos)
            f.emit("ret", acc)
            f.emit("label", l_fail)
            f.emit("call", None, "__str_to_int_fail", [])
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        # __memcpy(dst, src, n)  正向拷贝（不处理重叠；调用方保证）
        # v1.5：8 字节字块拷贝 + 尾字节，替代逐字节循环（报告 §4.5 的
        # "21.9 µs/次拼接 ≈ 逐字节 memcpy" 就是这里）。x86_64/AArch64 都允许
        # 非对齐 64 位访问，所以不需要对齐前导。
        f = Fn("__memcpy")
        d, s, m = f.new_v(), f.new_v(), f.new_v()
        f.emit("args", [d, s, m])
        mw = f.new_v()
        f.emit("bin", "shr", mw, m, ("imm", 3))          # 字数
        j = f.new_v()
        f.emit("mov", j, ("imm", 0))
        l_wt, l_we = f.label("mcwt"), f.label("mcwe")
        f.emit("label", l_wt)
        f.emit("jcc", "ge", j, mw, l_we)
        w = f.new_v()
        f.emit("load", w, s, j)
        f.emit("store", d, j, w)
        f.emit("bin", "add", j, j, ("imm", 1))
        f.emit("jmp", l_wt)
        f.emit("label", l_we)
        i = f.new_v()
        f.emit("bin", "shl", i, mw, ("imm", 3))          # 已拷字节数
        l_t, l_e = f.label("mct"), f.label("mce")
        f.emit("label", l_t)
        f.emit("jcc", "ge", i, m, l_e)
        c = f.new_v()
        f.emit("load8", c, s, i)
        f.emit("store8", d, i, c)
        f.emit("bin", "add", i, i, ("imm", 1))
        f.emit("jmp", l_t)
        f.emit("label", l_e)
        f.emit("ret", ("imm", 0))
        self.out.append(f)

        # __memset(dst, byte, n)：8 字节广播填充 + 尾字节
        f = Fn("__memset")
        d, val, m = f.new_v(), f.new_v(), f.new_v()
        f.emit("args", [d, val, m])
        vw = f.new_v()
        f.emit("bin", "and", vw, val, ("imm", 0xFF))
        t1 = f.new_v()
        f.emit("bin", "mul", t1, vw, ("imm", 0x0101010101010101))
        mw = f.new_v()
        f.emit("bin", "shr", mw, m, ("imm", 3))
        j = f.new_v()
        f.emit("mov", j, ("imm", 0))
        l_wt, l_we = f.label("mswt"), f.label("mswe")
        f.emit("label", l_wt)
        f.emit("jcc", "ge", j, mw, l_we)
        f.emit("store", d, j, t1)
        f.emit("bin", "add", j, j, ("imm", 1))
        f.emit("jmp", l_wt)
        f.emit("label", l_we)
        i = f.new_v()
        f.emit("bin", "shl", i, mw, ("imm", 3))
        l_t, l_e = f.label("mst"), f.label("mse")
        f.emit("label", l_t)
        f.emit("jcc", "ge", i, m, l_e)
        f.emit("store8", d, i, vw)
        f.emit("bin", "add", i, i, ("imm", 1))
        f.emit("jmp", l_t)
        f.emit("label", l_e)
        f.emit("ret", ("imm", 0))
        if self.uses_memset:                     # 只发射真正用到的运行时（省体积）
            self.out.append(f)

        # __memcmp(a, b, n) -> 0 / <0 / >0：8 字节字比较，命中差异后逐字节定位
        f = Fn("__memcmp")
        pa, pb, pn = f.new_v(), f.new_v(), f.new_v()
        f.emit("args", [pa, pb, pn])
        nw = f.new_v()
        f.emit("bin", "shr", nw, pn, ("imm", 3))
        k = f.new_v()
        f.emit("mov", k, ("imm", 0))
        ca = f.new_v()
        cb = f.new_v()
        f.emit("mov", ca, ("imm", 0))          # 所有路径上都已定义（pn==0 时直接返回 0）
        f.emit("mov", cb, ("imm", 0))
        l_wt, l_we = f.label("mcpt"), f.label("mcpe")
        l_bt, l_be = f.label("mcbt"), f.label("mcbe")
        f.emit("label", l_wt)
        f.emit("jcc", "ge", k, nw, l_we)
        wa = f.new_v()
        f.emit("load", wa, pa, k)
        wb = f.new_v()
        f.emit("load", wb, pb, k)
        f.emit("jcc", "ne", wa, wb, l_be)       # 差异字 -> 逐字节定位
        f.emit("bin", "add", k, k, ("imm", 1))
        f.emit("jmp", l_wt)
        # 差异字：从该字起点逐字节比，找到第一个不同的字节即返回差值
        f.emit("label", l_be)
        i = f.new_v()
        f.emit("bin", "shl", i, k, ("imm", 3))
        l_bt2, l_be2 = f.label("mcb2"), f.label("mce2")
        f.emit("label", l_bt2)
        f.emit("jcc", "ge", i, pn, l_be2)
        f.emit("load8", ca, pa, i)
        f.emit("load8", cb, pb, i)
        f.emit("jcc", "ne", ca, cb, l_be2)
        f.emit("bin", "add", i, i, ("imm", 1))
        f.emit("jmp", l_bt2)
        f.emit("label", l_be2)
        r1 = f.new_v()
        f.emit("bin", "sub", r1, ca, cb)
        f.emit("ret", r1)
        # 尾字节
        f.emit("label", l_we)
        i2 = f.new_v()
        f.emit("bin", "shl", i2, nw, ("imm", 3))
        l_tt, l_te = f.label("mctt"), f.label("mcte")
        f.emit("label", l_tt)
        f.emit("jcc", "ge", i2, pn, l_te)
        f.emit("load8", ca, pa, i2)
        f.emit("load8", cb, pb, i2)
        f.emit("jcc", "ne", ca, cb, l_te)
        f.emit("bin", "add", i2, i2, ("imm", 1))
        f.emit("jmp", l_tt)
        f.emit("label", l_te)
        r2 = f.new_v()
        f.emit("bin", "sub", r2, ca, cb)
        f.emit("ret", r2)
        if self.uses_memcmp:
            self.out.append(f)

        # __memchr(p, n, c) -> int：首个等于 c 的字节下标，找不到 -1（v1.29）
        # 8 字节 SWAR：c 广播成 64 位字 rep，x = word ^ rep；
        # 零字节检测 haszero(x) = (x - 0x01…) & ~x & 0x80…
        # ⚠ SWAR 只回答"这个字里有 c"，不回答"是第几个字节"——命中后必须
        # 逐字节确认，否则返回的是字内任意一个匹配（首匹配语义就丢了）。
        # 高位掩码不用 0x8080808080808080（= 2^63，超出 int64 正区间，
        # 走有符号立即数容易踩坑）：改成 >>7 再 & 0x0101…，效果等价。
        f = Fn("__memchr")
        p, n, c = f.new_v(), f.new_v(), f.new_v()
        f.emit("args", [p, n, c])
        cb = f.new_v()
        f.emit("bin", "and", cb, c, ("imm", 0xFF))
        rep = f.new_v()
        f.emit("bin", "mul", rep, cb, ("imm", 0x0101010101010101))
        nw = f.new_v()
        f.emit("bin", "shr", nw, n, ("imm", 3))          # 整字数
        k = f.new_v()
        f.emit("mov", k, ("imm", 0))
        l_wt, l_we = f.label("mchwt"), f.label("mchwe")
        l_bt, l_bf, l_bn = f.label("mchbt"), f.label("mchbf"), f.label("mchbn")
        f.emit("label", l_wt)
        f.emit("jcc", "ge", k, nw, l_we)
        w = f.new_v()
        f.emit("load", w, p, k)
        x = f.new_v()
        f.emit("bin", "xor", x, w, rep)
        t1 = f.new_v()
        f.emit("bin", "sub", t1, x, ("imm", 0x0101010101010101))
        t2 = f.new_v()
        f.emit("not", t2, x)
        t3 = f.new_v()
        f.emit("bin", "and", t3, t1, t2)
        t4 = f.new_v()
        f.emit("bin", "shr", t4, t3, ("imm", 7))          # 每字节的 bit7 -> bit0
        t5 = f.new_v()
        f.emit("bin", "and", t5, t4, ("imm", 0x0101010101010101))
        f.emit("jz", t5, l_bn)                            # 该字无 c -> 下一个字
        i = f.new_v()
        f.emit("bin", "shl", i, k, ("imm", 3))
        f.emit("label", l_bt)                             # 字内逐字节确认
        f.emit("jcc", "ge", i, n, l_bn)
        b = f.new_v()
        f.emit("load8", b, p, i)
        f.emit("jcc", "e", b, cb, l_bf)
        f.emit("bin", "add", i, i, ("imm", 1))
        f.emit("jmp", l_bt)
        f.emit("label", l_bf)
        f.emit("ret", i)
        f.emit("label", l_bn)
        f.emit("bin", "add", k, k, ("imm", 1))
        f.emit("jmp", l_wt)
        # 尾字节（n % 8）
        f.emit("label", l_we)
        i2 = f.new_v()
        f.emit("bin", "shl", i2, nw, ("imm", 3))
        l_tt, l_tf, l_tn = f.label("mchtt"), f.label("mchtf"), f.label("mchtn")
        f.emit("label", l_tt)
        f.emit("jcc", "ge", i2, n, l_tn)
        b2 = f.new_v()
        f.emit("load8", b2, p, i2)
        f.emit("jcc", "e", b2, cb, l_tf)
        f.emit("bin", "add", i2, i2, ("imm", 1))
        f.emit("jmp", l_tt)
        f.emit("label", l_tf)
        f.emit("ret", i2)
        f.emit("label", l_tn)
        f.emit("ret", ("imm", -1))
        if self.uses_memchr:
            self.out.append(f)



        # __memdiff(a, b, n) -> int：首个不同字节的下标，全等返回 n（v1.30）
        # 8 字节字比较：字相等就整字跳过，字不等再逐字节定位（公共前缀长度）。
        # 这是 LZ77 匹配长度的核心——gzip 编码的内层热点原来是一字节一次比较。
        f = Fn("__memdiff")
        pa, pb, pn = f.new_v(), f.new_v(), f.new_v()
        f.emit("args", [pa, pb, pn])
        nw = f.new_v()
        f.emit("bin", "shr", nw, pn, ("imm", 3))
        k = f.new_v()
        f.emit("mov", k, ("imm", 0))
        l_wt, l_tail = f.label("mdwt"), f.label("mdtail")
        l_next = f.label("mdnext")
        l_bt, l_r1 = f.label("mdbt"), f.label("mdr1")
        f.emit("label", l_wt)
        f.emit("jcc", "ge", k, nw, l_tail)
        wa = f.new_v()
        f.emit("load", wa, pa, k)
        wb = f.new_v()
        f.emit("load", wb, pb, k)
        x = f.new_v()
        f.emit("bin", "xor", x, wa, wb)
        f.emit("jz", x, l_next)                  # 整字相同 -> 下一个字
        i = f.new_v()
        f.emit("bin", "shl", i, k, ("imm", 3))
        f.emit("label", l_bt)                    # 字内定位（保证返回**首个**不同）
        f.emit("jcc", "ge", i, pn, l_next)
        ba = f.new_v()
        f.emit("load8", ba, pa, i)
        bb = f.new_v()
        f.emit("load8", bb, pb, i)
        f.emit("jcc", "ne", ba, bb, l_r1)
        f.emit("bin", "add", i, i, ("imm", 1))
        f.emit("jmp", l_bt)
        f.emit("label", l_r1)
        f.emit("ret", i)
        f.emit("label", l_next)
        f.emit("bin", "add", k, k, ("imm", 1))
        f.emit("jmp", l_wt)
        # 尾字节（n % 8）
        f.emit("label", l_tail)
        i2 = f.new_v()
        f.emit("bin", "shl", i2, nw, ("imm", 3))
        l_tt, l_r2, l_none = f.label("mdtt"), f.label("mdr2"), f.label("mdnone")
        f.emit("label", l_tt)
        f.emit("jcc", "ge", i2, pn, l_none)
        ba2 = f.new_v()
        f.emit("load8", ba2, pa, i2)
        bb2 = f.new_v()
        f.emit("load8", bb2, pb, i2)
        f.emit("jcc", "ne", ba2, bb2, l_r2)
        f.emit("bin", "add", i2, i2, ("imm", 1))
        f.emit("jmp", l_tt)
        f.emit("label", l_r2)
        f.emit("ret", i2)
        f.emit("label", l_none)
        f.emit("ret", pn)
        if self.uses_memdiff:
            self.out.append(f)

        # __mem_to_str(p, n) -> str：拷 n 字节并补 NUL（缓冲区 -> 不可变串）
        # v1.5.1 长度前缀：[n][n 字节][NUL]，返回 +8
        f = Fn("__mem_to_str")
        mp, mn = f.new_v(), f.new_v()
        f.emit("args", [mp, mn])
        nb = f.new_v()
        f.emit("bin", "add", nb, mn, ("imm", 9))
        h = f.new_v()
        f.emit("call", h, "__alloc", [nb])
        f.emit("store", h, ("imm", 0), mn)            # 长度前缀
        d1 = f.new_v()
        f.emit("bin", "add", d1, h, ("imm", 8))
        f.emit("call", None, "__memcpy", [d1, mp, mn])
        z = f.new_v()
        f.emit("bin", "add", z, d1, mn)
        f.emit("store8", z, ("imm", 0), ("imm", 0))
        f.emit("ret", d1)
        if self.uses_mem_to_str:
            self.out.append(f)

        # __realloc(p, old, new) -> ptr：顶端块原地延展（vec 扩容不再泄漏旧块）
        f = Fn("__realloc")
        rp, ro, rn = f.new_v(), f.new_v(), f.new_v()
        f.emit("args", [rp, ro, rn])
        ext = f.new_v()
        f.emit("bin", "sub", ext, rn, ro)
        got = f.new_v()
        f.emit("call", got, "__alloc", [ext])
        want = f.new_v()
        f.emit("bin", "add", want, rp, ro)
        l_same, l_copy = f.label("rlsame"), f.label("rlcopy")
        f.emit("jcc", "e", got, want, l_same)
        q = f.new_v()
        f.emit("call", q, "__alloc", [rn])
        f.emit("call", None, "__memcpy", [q, rp, ro])
        f.emit("ret", q)
        f.emit("label", l_same)
        f.emit("ret", rp)
        if self.uses_realloc or self.uses_vec:
            self.out.append(f)

        # __free(p, n)：O(1) 归还到尺寸类空闲链（确定性回收，无扫描/无 STW）
        f = Fn("__free")
        fp, fn_ = f.new_v(), f.new_v()
        f.emit("args", [fp, fn_])
        f.emit("bin", "add", fn_, fn_, ("imm", 31))
        f.emit("bin", "and", fn_, fn_, ("imm", -32))
        gid_fl = self.free_list_gid()
        l_skip = f.label("frskip")
        cls = f.new_v()
        f.emit("bin", "shr", cls, fn_, ("imm", 5))
        f.emit("bin", "sub", cls, cls, ("imm", 1))
        f.emit("jcc", "l", cls, ("imm", 0), l_skip)      # 超大块不回收（交给 arena）
        f.emit("jcc", "ge", cls, ("imm", FREE_CLASSES), l_skip)
        head = f.new_v()
        f.emit("load", head, ("ga", gid_fl), cls)
        f.emit("store", fp, ("imm", 0), head)            # 块首字存 next
        f.emit("store", ("ga", gid_fl), cls, fp)
        f.emit("label", l_skip)
        f.emit("ret", ("imm", 0))
        if self.uses_free:
            self.out.append(f)

        # ---- 接口装箱引用计数（v1.81）----
        # 箱布局 [rc][payload_bytes][payload...]，data 指向 payload：
        #   __iface_retain(p)   p[-16] += 1
        #   __iface_release(p)  p[-16] -= 1；归零 -> __free(p-16, 16+bytes)
        # 只发射真正用到的部分（不用接口的程序体积/行为零变化）。
        if self.uses_iface_rc:
            f = Fn("__iface_retain")
            rp = f.new_v()
            f.emit("args", [rp])
            rc = f.new_v()
            f.emit("load", rc, rp, ("imm", -2))
            rc2 = f.new_v()
            f.emit("bin", "add", rc2, rc, ("imm", 1))
            f.emit("store", rp, ("imm", -2), rc2)
            f.emit("ret", ("imm", 0))
            self.out.append(f)

            f = Fn("__iface_release")
            rp = f.new_v()
            f.emit("args", [rp])
            rc = f.new_v()
            f.emit("load", rc, rp, ("imm", -2))
            rc2 = f.new_v()
            f.emit("bin", "sub", rc2, rc, ("imm", 1))
            f.emit("store", rp, ("imm", -2), rc2)
            l_end = f.label("ifre")
            f.emit("jnz", rc2, l_end)
            nb = f.new_v()
            f.emit("load", nb, rp, ("imm", -1))     # payload 字节数
            tot = f.new_v()
            f.emit("bin", "add", tot, nb, ("imm", 16))
            blk = f.new_v()
            f.emit("bin", "sub", blk, rp, ("imm", 16))
            f.emit("call", None, "__free", [blk, tot])
            f.emit("label", l_end)
            f.emit("ret", ("imm", 0))
            self.out.append(f)

        # __now_ns() -> int：单调时钟纳秒。语言层此前完全没有计时内建
        # （性能报告 §8 指出的缺口），用户无法在自己的程序里做微基准。
        f = Fn("__now_ns")
        f.emit("args", [])
        if self.platform == "windows":
            gid_fq = self.intern_array(1)
            gid_cnt = self.intern_array(1)
            fq = f.new_v()
            f.emit("load", fq, ("ga", gid_fq), ("imm", 0))
            l_have = f.label("nshave")
            f.emit("jnz", fq, l_have)
            f.emit("winapi", None, "QueryPerformanceFrequency", [("ga", gid_fq)])
            f.emit("label", l_have)
            f.emit("winapi", None, "QueryPerformanceCounter", [("ga", gid_cnt)])
            cnt = f.new_v()
            f.emit("load", cnt, ("ga", gid_cnt), ("imm", 0))
            fq2 = f.new_v()
            f.emit("load", fq2, ("ga", gid_fq), ("imm", 0))
            # cnt * 1e9 会溢出 int64（QPC 计数 ~1e10）——先拆成秒 + 余数
            sec = f.new_v()
            f.emit("bin", "div", sec, cnt, fq2)
            whole = f.new_v()
            f.emit("bin", "mul", whole, sec, fq2)
            rem = f.new_v()
            f.emit("bin", "sub", rem, cnt, whole)
            ns = f.new_v()
            f.emit("bin", "mul", ns, sec, ("imm", 1000000000))
            rn = f.new_v()
            f.emit("bin", "mul", rn, rem, ("imm", 1000000000))
            f.emit("bin", "div", rn, rn, fq2)
            f.emit("bin", "add", ns, ns, rn)
            f.emit("ret", ns)
        else:
            gid_ts = self.intern_array(2)
            f.emit("syscall", None, self.sc["clock_gettime"],
                   [("imm", 1), ("ga", gid_ts)])          # CLOCK_MONOTONIC
            sec = f.new_v()
            f.emit("load", sec, ("ga", gid_ts), ("imm", 0))
            nsec = f.new_v()
            f.emit("load", nsec, ("ga", gid_ts), ("imm", 1))
            ns = f.new_v()
            f.emit("bin", "mul", ns, sec, ("imm", 1000000000))
            f.emit("bin", "add", ns, ns, nsec)
            f.emit("ret", ns)
        if self.uses_now:
            self.out.append(f)          # 必须在这里 append：后面的 wall 块会复用 f

        if self.uses_udp:
            # ---- UDP（v1.17）：数据报套接字四件 ----
            # 块内自带 net_fail（TCP gate 未触发时外层的 def 不存在）
            def udp_net_fail(f, lb, tag):
                f.emit("label", lb)
                f.emit("call", None, "__net_fail_" + tag, [])

            def net_fail(f, lb, tag):
                udp_net_fail(f, lb, tag)

            # UDP 自己的 __net_fail_* 运行库（TCP gate 只定义了它的五个）
            for tag, msg in (("udpsocket", "quelmara: udp socket failed (fail-fast)\n"),
                             ("udpsendto", "quelmara: udp sendto failed (fail-fast)\n"),
                             ("udprecvfrom", "quelmara: udp recvfrom failed (fail-fast)\n")):
                gid_nf = self.intern_str(msg)
                f = Fn("__net_fail_" + tag)
                bp = f.new_v()
                f.emit("movaddr", bp, gid_nf)
                self.emit_write(f, 2, bp, ("imm", len(msg.encode("utf-8"))))
                self.emit_exit(f, ("imm", 1))
                self.out.append(f)

            # sockaddr_in 16B：[0]=family(2)|htons(port)<<16，[1]=ip(网络序)
            # Windows 的 API int 返回值高 32 位为 0（SOCKET_ERROR 形态
            # 0x00000000FFFFFFFF），失败判定走 shl32+sar32 符号扩展后 == -1
            gid_wsa_udp = self.intern_array(8)
            gid_sa = self.intern_array(2)

            def udp_sin(f, ip_v, port_v):
                """构造 sockaddr_in（16B），返回堆指针 vreg。

                真实字节布局：family@0-1、port(网络序)@2-3、addr@4-7、
                zero@8-15——**字节紧排**，不是一个字段一个 8B 槽！
                slot0（字节 0-7）= 2 | (htons(port)<<16) | (ip<<32)：
                  - ip 已是内存序（udp_parse_ip 约定 127.0.0.1 ->
                    0x0100007F），LE 写入后字节 4-7 = [a,b,c,d] 恰为
                    网络序地址字节；
                  - htons(port) 寄存器值 = (port&0xFF)<<8 | (port>>8)&0xFF，
                    LE 写入字节 2-3 即还原成大端端口字节。
                slot1（字节 8-15）= 0（sin_zero）。"""
                sinb = f.new_v()
                f.emit("call", sinb, "__alloc", [("imm", 16)])
                f.emit("store", sinb, ("imm", 0), ("imm", 2))   # family
                pb = f.new_v()
                f.emit("bin", "and", pb, port_v, ("imm", 0xFF))
                pb2 = f.new_v()
                f.emit("bin", "shl", pb2, pb, ("imm", 8))
                ph = f.new_v()
                f.emit("bin", "shr", ph, port_v, ("imm", 8))
                ph2 = f.new_v()
                f.emit("bin", "and", ph2, ph, ("imm", 0xFF))
                pw = f.new_v()
                f.emit("bin", "or", pw, pb2, ph2)              # htons(port)
                pw2 = f.new_v()
                f.emit("bin", "shl", pw2, pw, ("imm", 16))
                w0 = f.new_v()
                f.emit("bin", "or", w0, pw2, ("imm", 2))
                w1 = f.new_v()
                f.emit("bin", "shl", w1, ip_v, ("imm", 32))
                w2 = f.new_v()
                f.emit("bin", "or", w2, w0, w1)
                f.emit("store", sinb, ("imm", 0), w2)          # family|port|addr
                f.emit("store", sinb, ("imm", 1), ("imm", 0))  # sin_zero
                return sinb

            # __udp_open
            f = Fn("__udp_open")
            if self.platform == "windows":
                wsa = f.new_v()
                f.emit("movaddr", wsa, gid_wsa_udp)
                sw = f.new_v()
                f.emit("winapi", sw, "WSAStartup", [("imm", 0x202), wsa])
                # WSAStartup：0 = 成功，非 0 = 错误码。结果必须被消费——
                # 否则优化器把"结果未使用"的调用当死代码删除（v1.17b 的
                # 隐蔽坑：UDP 全链路代码正确，WSAStartup 却被 DCE 掉，
                # socket 恒返回 SOCKET_ERROR）。
                b = f.new_v()
                f.emit("cmpset", "ne", b, sw, ("imm", 0))
                lf = f.label("uof")
                f.emit("jnz", b, lf)
                s = f.new_v()
                f.emit("winapi", s, "socket", [("imm", 2), ("imm", 2), ("imm", 0)])
                b = f.new_v()
                r32 = f.new_v()
                f.emit("bin", "shl", r32, s, ("imm", 32))
                r322 = f.new_v()
                f.emit("bin", "sar", r322, r32, ("imm", 32))
                f.emit("cmpset", "e", b, r322, ("imm", -1))
                f.emit("jnz", b, lf)
                # 成功先 ret；失败标签必须在 ret 之后（fall-through 语义：
                # jnz 不跳 = 成功，紧跟 ret——fail 块放 ret 后才不会把
                # 成功路径吞进失败处理器，v1.17b 的 PE 即崩/恒 fail 皆此因）
                f.emit("ret", s)
                net_fail(f, lf, "udpsocket")
            else:
                s = f.new_v()
                f.emit("syscall", s, self.sc["socket"],
                       [("imm", 2), ("imm", 2), ("imm", 0), ("imm", 0), ("imm", 0), ("imm", 0)])
                f.emit("ret", s)
            if self.platform == "windows":
                pass  # ret 已在失败标签前发射
            self.out.append(f)

            # __udp_bind(fd, port)
            f = Fn("__udp_bind")
            fdu, pu = f.new_v(), f.new_v()
            f.emit("args", [fdu, pu])
            sinb = udp_sin(f, ("imm", 0), pu)
            if self.platform == "windows":
                r = f.new_v()
                f.emit("winapi", r, "bind", [fdu, sinb, ("imm", 16)])
                b = f.new_v()
                r32 = f.new_v()
                f.emit("bin", "shl", r32, r, ("imm", 32))
                r322 = f.new_v()
                f.emit("bin", "sar", r322, r32, ("imm", 32))
                f.emit("cmpset", "ne", b, r322, ("imm", -1))
                r2 = f.new_v()
                f.emit("bin", "sub", r2, b, ("imm", 1))
                f.emit("ret", r2)
            else:
                f.emit("syscall", r, self.sc["bind"],
                       [fdu, sinb, ("imm", 16), ("imm", 0), ("imm", 0), ("imm", 0)])
                z = f.new_v()
                f.emit("cmpset", "e", z, r, ("imm", 0))
                r2 = f.new_v()
                f.emit("bin", "sub", r2, z, ("imm", 1))
                f.emit("ret", r2)
            self.out.append(f)

            # __udp_sendto(fd, ip, port, data)
            f = Fn("__udp_sendto")
            fdu, ipu, pu, du = f.new_v(), f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [fdu, ipu, pu, du])
            sinb = udp_sin(f, ipu, pu)
            dn = f.new_v()
            f.emit("call", dn, "__str_len", [du])
            if self.platform == "windows":
                r = f.new_v()
                f.emit("winapi", r, "sendto",
                       [fdu, du, dn, ("imm", 0), sinb, ("imm", 16)])
                b = f.new_v()
                r32 = f.new_v()
                f.emit("bin", "shl", r32, r, ("imm", 32))
                r322 = f.new_v()
                f.emit("bin", "sar", r322, r32, ("imm", 32))
                f.emit("cmpset", "l", b, r322, ("imm", 0))
                lf = f.label("usf")
                f.emit("jnz", b, lf)
                f.emit("ret", r)
                net_fail(f, lf, "udpsendto")   # fail 块在 ret 之后（fall-through 语义）
            else:
                f.emit("syscall", r, self.sc["sendto"],
                       [fdu, du, dn, ("imm", 0), sinb, ("imm", 16)])
                b = f.new_v()
                f.emit("cmpset", "l", b, r, ("imm", 0))
                lf = f.label("usf")
                f.emit("jnz", b, lf)
                f.emit("ret", r)
                net_fail(f, lf, "udpsendto")
            self.out.append(f)

            # __udp_recvfrom(fd, cap) -> str（单 datagram，src 丢弃）
            f = Fn("__udp_recvfrom")
            fdu, capu = f.new_v(), f.new_v()
            f.emit("args", [fdu, capu])
            nb = f.new_v()
            f.emit("bin", "add", nb, capu, ("imm", 9))
            buf = f.new_v()
            f.emit("call", buf, "__alloc", [nb])
            sinb = f.new_v()
            f.emit("call", sinb, "__alloc", [("imm", 16)])
            slen = f.new_v()
            f.emit("call", slen, "__alloc", [("imm", 8)])
            f.emit("store", slen, ("imm", 0), ("imm", 16))
            bufd = f.new_v()
            f.emit("bin", "add", bufd, buf, ("imm", 8))
            if self.platform == "windows":
                r = f.new_v()
                f.emit("winapi", r, "recvfrom",
                       [fdu, bufd, capu, ("imm", 0), sinb, slen])
                b = f.new_v()
                r32 = f.new_v()
                f.emit("bin", "shl", r32, r, ("imm", 32))
                r322 = f.new_v()
                f.emit("bin", "sar", r322, r32, ("imm", 32))
                f.emit("cmpset", "l", b, r322, ("imm", 0))
                lf = f.label("urf")
                f.emit("jnz", b, lf)
            else:
                r = f.new_v()
                f.emit("syscall", r, self.sc["recvfrom"],
                       [fdu, bufd, capu, ("imm", 0), sinb, slen])
                b = f.new_v()
                f.emit("cmpset", "l", b, r, ("imm", 0))
                lf = f.label("urf")
                f.emit("jnz", b, lf)
            f.emit("store", buf, ("imm", 0), r)       # 长度头 = 实收字节数
            # NUL 终止符在数据**末尾**（offset = r+8）——写在 8 会清掉
            # 第一个数据字节（v1.17b 踩坑：echo 内容断言挂的根因）
            noff = f.new_v()
            f.emit("bin", "add", noff, r, ("imm", 8))
            f.emit("store8", buf, noff, ("imm", 0))
            rbuf = f.new_v()
            f.emit("bin", "add", rbuf, buf, ("imm", 8))
            f.emit("ret", rbuf)
            net_fail(f, lf, "udprecvfrom")             # fail 块在 ret 之后
            self.out.append(f)

            # __udp_recvfrom_to(fd, cap, ms) -> str（v3.04）
            #
            # 带接收超时的版本。`ms <= 0` 表示"不等"（非阻塞探测）；
            # 超时/失败返回**空串**而不是 fail-fast —— 调用方（DNS）需要
            # "这个 nameserver 没响应"是可恢复结果，不是进程终止条件。
            #
            # 实现：先 setsockopt(SO_RCVTIMEO) 设超时，再 recvfrom。
            #   * Linux x86_64：syscall 54，SOL_SOCKET=1、SO_RCVTIMEO=20，
            #     optval 是 struct timeval{sec, usec}（16 字节）。
            #   * Windows：SOCKET 句柄不是 fd，走 winapi setsockopt
            #     （SOL_SOCKET=0xFFFF、SO_RCVTIMEO=0x1006，DWORD 毫秒）。
            # 两种平台都**只设一次**，不改回——超时对同一 fd 的后续接收
            # 持续有效，与调用方预期一致（DNS 用完就 close）。
            f = Fn("__udp_recvfrom_to")
            ft, capt, mst = f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [ft, capt, mst])
            tv = f.new_v()
            f.emit("call", tv, "__alloc", [("imm", 16)])
            if self.platform == "windows":
                # DWORD 毫秒（4 字节，直接放在 tv 前 4 字节）
                f.emit("store", tv, ("imm", 0), mst)
                f.emit("winapi", None, "setsockopt",
                       [ft, ("imm", 0xFFFF), ("imm", 0x1006), tv, ("imm", 4)])
            else:
                # struct timeval{ tv_sec, tv_usec }（x86_64 各 8 字节）
                sec = f.new_v()
                f.emit("bin", "div", sec, mst, ("imm", 1000))
                mrem = f.new_v()
                f.emit("bin", "mod", mrem, mst, ("imm", 1000))
                usec = f.new_v()
                f.emit("bin", "mul", usec, mrem, ("imm", 1000))
                f.emit("store", tv, ("imm", 0), sec)
                f.emit("store", tv, ("imm", 1), usec)
                f.emit("syscall", None, self.sc["setsockopt"],
                       [ft, ("imm", 1), ("imm", 20), tv, ("imm", 16)])
            nb = f.new_v()
            f.emit("bin", "add", nb, capt, ("imm", 9))
            buf = f.new_v()
            f.emit("call", buf, "__alloc", [nb])
            sinb = f.new_v()
            f.emit("call", sinb, "__alloc", [("imm", 16)])
            slen = f.new_v()
            f.emit("call", slen, "__alloc", [("imm", 8)])
            f.emit("store", slen, ("imm", 0), ("imm", 16))
            bufd = f.new_v()
            f.emit("bin", "add", bufd, buf, ("imm", 8))
            l_empty = f.label("urt0")
            l_ok = f.label("urt1")
            if self.platform == "windows":
                r = f.new_v()
                f.emit("winapi", r, "recvfrom",
                       [ft, bufd, capt, ("imm", 0), sinb, slen])
                b = f.new_v()
                r32 = f.new_v()
                f.emit("bin", "shl", r32, r, ("imm", 32))
                r322 = f.new_v()
                f.emit("bin", "sar", r322, r32, ("imm", 32))
                f.emit("cmpset", "l", b, r322, ("imm", 0))
                f.emit("jnz", b, l_empty)
            else:
                r = f.new_v()
                f.emit("syscall", r, self.sc["recvfrom"],
                       [ft, bufd, capt, ("imm", 0), sinb, slen])
                b = f.new_v()
                f.emit("cmpset", "l", b, r, ("imm", 0))
                f.emit("jnz", b, l_empty)
            # 成功：长度头 = 实收字节数，NUL 在 r+8
            f.emit("store", buf, ("imm", 0), r)
            noff = f.new_v()
            f.emit("bin", "add", noff, r, ("imm", 8))
            f.emit("store8", buf, noff, ("imm", 0))
            rbuf = f.new_v()
            f.emit("bin", "add", rbuf, buf, ("imm", 8))
            f.emit("ret", rbuf)
            # 超时/失败：返回空串（长度 0 的 str，头 8 字节写 0）
            f.emit("label", l_empty)
            f.emit("store", buf, ("imm", 0), ("imm", 0))
            f.emit("store8", buf, ("imm", 8), ("imm", 0))
            f.emit("bin", "add", rbuf, buf, ("imm", 8))
            f.emit("ret", rbuf)
            self.out.append(f)

        if self.uses_cpu:
            # __cpu_ns() -> int：进程累计 CPU 时间（内核 + 用户态）纳秒。
            # 只用于测量：与 now_ns 的比值就是"这段时间有多少在真跑"。
            # Windows：GetProcessTimes(GetCurrentProcess()=伪句柄 -1,
            #   creation, exit, kernel, user) → 两个 FILETIME 各 8 字节，
            #   100ns 单位；帧上开 4 个字接收四个输出。
            # Linux：clock_gettime(CLOCK_PROCESS_CPUTIME_ID=2, timespec)。
            f = Fn("__cpu_ns")
            f.emit("args", [])
            ts = f.new_struct_slot(4 if self.platform == "windows" else 2)
            ta = f.new_v()
            f.emit("frameaddr", ta, ts)
            if self.platform == "windows":
                p2 = f.new_v()
                f.emit("bin", "add", p2, ta, ("imm", 8))
                p3 = f.new_v()
                f.emit("bin", "add", p3, ta, ("imm", 16))
                p4 = f.new_v()
                f.emit("bin", "add", p4, ta, ("imm", 24))
                f.emit("winapi", None, "GetProcessTimes",
                       [("imm", -1), ta, p2, p3, p4])
                kern = f.new_v()
                f.emit("load", kern, ta, ("imm", 2))
                user = f.new_v()
                f.emit("load", user, ta, ("imm", 3))
                tot = f.new_v()
                f.emit("bin", "add", tot, kern, user)
                ns = f.new_v()
                f.emit("bin", "mul", ns, tot, ("imm", 100))    # 100ns -> ns
                f.emit("ret", ns)
            else:
                f.emit("syscall", None, self.sc["clock_gettime"],
                       [("imm", 2), ta, ("imm", 0), ("imm", 0),
                        ("imm", 0), ("imm", 0)])
                sec = f.new_v()
                f.emit("load", sec, ta, ("imm", 0))
                nsec = f.new_v()
                f.emit("load", nsec, ta, ("imm", 1))
                ns = f.new_v()
                f.emit("bin", "mul", ns, sec, ("imm", 1000000000))
                f.emit("bin", "add", ns, ns, nsec)
                f.emit("ret", ns)
            self.out.append(f)

        if self.uses_wall:
            # __wall_ms：Linux clock_gettime(CLOCK_REALTIME)；Windows            # GetSystemTimeAsFileTime（1601 epoch 100ns -> 1970 epoch 毫秒）
            f = Fn("__wall_ms")
            if self.platform == "windows":
                ft = f.new_v()
                f.emit("call", ft, "__alloc", [("imm", 8)])
                f.emit("winapi", None, "GetSystemTimeAsFileTime", [ft])
                v = f.new_v()
                f.emit("load", v, ft, ("imm", 0))
                # 116444736000000000 * 100ns = 1601->1970 秒差
                adj = f.new_v()
                f.emit("bin", "sub", adj, v, ("imm", 116444736000000000))
                ms = f.new_v()
                f.emit("bin", "div", ms, adj, ("imm", 10000))
                f.emit("ret", ms)
            else:
                ts = f.new_v()
                f.emit("call", ts, "__alloc", [("imm", 16)])
                f.emit("syscall", None, self.sc["clock_gettime"],
                       [("imm", 0), ts, ("imm", 0), ("imm", 0), ("imm", 0), ("imm", 0)])
                sec = f.new_v()
                f.emit("load", sec, ts, ("imm", 0))
                nsec = f.new_v()
                f.emit("load", nsec, ts, ("imm", 1))
                ms = f.new_v()
                f.emit("bin", "mul", ms, sec, ("imm", 1000))
                ms2 = f.new_v()
                f.emit("bin", "add", ms2, ms, nsec)
                ms3 = f.new_v()
                f.emit("bin", "div", ms3, ms2, ("imm", 1000000))
                f.emit("ret", ms3)
            self.out.append(f)

        # __str_concat(a, b) -> ptr（v1.5.1 长度前缀 ABI）：
        # [la+lb][a 字节][b 字节][NUL]，返回值 = 分配块 + 8
        f = Fn("__str_concat")
        a, b = f.new_v(), f.new_v()
        f.emit("args", [a, b])
        la = f.new_v()
        f.emit("call", la, "__str_len", [a])
        lb = f.new_v()
        f.emit("call", lb, "__str_len", [b])
        nn = f.new_v()
        f.emit("bin", "add", nn, la, lb)
        nb = f.new_v()
        f.emit("bin", "add", nb, nn, ("imm", 9))
        h = f.new_v()
        f.emit("call", h, "__alloc", [nb])
        f.emit("store", h, ("imm", 0), nn)            # 长度前缀
        d1 = f.new_v()
        f.emit("bin", "add", d1, h, ("imm", 8))
        f.emit("call", None, "__memcpy", [d1, a, la])
        d2 = f.new_v()
        f.emit("bin", "add", d2, d1, la)
        f.emit("call", None, "__memcpy", [d2, b, lb])
        z = f.new_v()
        f.emit("bin", "add", z, d2, lb)
        f.emit("store8", z, ("imm", 0), ("imm", 0))
        f.emit("ret", d1)
        self.out.append(f)

        # __str_from_i64(v) -> ptr   低位起写、正向搬移（无 memmove 也能正确）
        # v1.5.1 长度前缀：41 字节块 = [len][33 字节数字工作区]，返回 +8
        f = Fn("__str_from_i64")
        v = f.new_v()
        f.emit("args", [v])
        neg = f.new_v()
        f.emit("mov", neg, ("imm", 0))
        l_pos = f.label("ipos")
        f.emit("jcc", "ge", v, ("imm", 0), l_pos)
        f.emit("mov", neg, ("imm", 1))
        f.emit("neg", v, v)
        f.emit("label", l_pos)
        buf = f.new_v()
        f.emit("call", buf, "__alloc", [("imm", 56)])
        # INT64_MIN 的取负会溢出回自身（-(-2^63) == -2^63），digit 循环里
        # mod/div 拿到负数，写出的是一串乱码字节（实测 20 个垃圾字符）。
        # 这是 int64 里唯一的溢出值，直接写定值走人（v1.29 修）。
        l_notmin = f.label("inotmin")
        f.emit("jcc", "ge", v, ("imm", 0), l_notmin)
        _min_str = "-9223372036854775808"
        for _i, _ch in enumerate(_min_str):
            f.emit("store8", buf, ("imm", 8 + _i), ("imm", ord(_ch)))
        f.emit("store", buf, ("imm", 0), ("imm", len(_min_str)))   # 长度前缀
        f.emit("store8", buf, ("imm", 8 + len(_min_str)), ("imm", 0))
        _rm = f.new_v()
        f.emit("bin", "add", _rm, buf, ("imm", 8))
        f.emit("ret", _rm)
        f.emit("label", l_notmin)
        # v2.71：**不再把数字拷一遍**。旧实现把数字写到 [pos+1, 39]，再把它们
        # 搬到 [8+neg, ...]（为了给 8 字节长度前缀腾位置）—— 那个拷贝循环
        # 每个数字 ~19 条机器指令（含越界检查、load8/store8、下标运算），
        # 6 位数就是 110+ 条，占 b5_string 一次迭代的 1/6。
        #
        # 新布局：数字从**缓冲区尾部**往左写，写完把 8 字节前缀写到数字正前方，
        # 返回 `buf + 前缀偏移`。字符串不需要落在固定偏移上 —— `__str_len`
        # 读的是 `[ptr-8]`，别处都只用 ptr/len。
        pos = f.new_v()
        f.emit("mov", pos, ("imm", 47))
        l_d, l_de = f.label("idig"), f.label("idige")
        f.emit("label", l_d)
        q10, cc = _emit_divmod10c(f, v, 48)
        f.emit("store8", buf, pos, cc)
        f.emit("bin", "sub", pos, pos, ("imm", 1))
        f.emit("mov", v, q10)
        f.emit("jnz", v, l_d)
        f.emit("label", l_de)
        # 负号：写在第一个数字的前一个字节
        l_nn = f.label("ineg")
        f.emit("jz", neg, l_nn)
        f.emit("store8", buf, pos, ("imm", 45))
        f.emit("bin", "sub", pos, pos, ("imm", 1))
        f.emit("label", l_nn)
        # len = 47 - pos（含负号）；前缀 8 字节落在 [pos-7, pos]，返回 pos-7
        ln = f.new_v()
        f.emit("mov", ln, ("imm", 47))
        f.emit("bin", "sub", ln, ln, pos)
        # NUL 落在固定字节 48（= pos + 1 + len 恒成立，与位数无关）
        f.emit("store8", buf, ("imm", 48), ("imm", 0))
        # 前缀 8 字节：高 7 字节清零，低字节是长度（len < 256）
        pfx = f.new_v()
        f.emit("mov", pfx, pos)
        for _k in range(7):
            f.emit("store8", buf, pfx, ("imm", 0))
            f.emit("bin", "sub", pfx, pfx, ("imm", 1))
        f.emit("store8", buf, pfx, ln)                   # pfx == pos - 7
        # 返回**字符串起点** buf+pos+1 —— 长度前缀正好是它前面那 8 字节
        # （[pos-7, pos]）。返回 buf+pfx 会早 8 字节，`__str_len` 读到垃圾。
        r8 = f.new_v()
        f.emit("bin", "add", r8, buf, pos)
        f.emit("bin", "add", r8, r8, ("imm", 1))
        f.emit("ret", r8)
        self.out.append(f)

        # ---- 浮点格式化（与 C 端 qlm_f64_to_str 算法逐位一致，双链 diff 依赖）----
        # __fmt_u64(buf, pos, v, pad) -> 新 pos：十进制写入，至少 pad 位（前导零）
        if self.uses_f64_str:
            def fbits(v):
                return struct.unpack("<Q", struct.pack("<d", v))[0]

            f = Fn("__fmt_u64")
            buf, pos, v, pad = f.new_v(), f.new_v(), f.new_v(), f.new_v()
            f.emit("args", [buf, pos, v, pad])
            l_rec, l_wr = f.label("f64rec"), f.label("f64wr")
            f.emit("jcc", "ge", v, ("imm", 10), l_rec)
            f.emit("jcc", "g", pad, ("imm", 1), l_rec)
            f.emit("jmp", l_wr)
            f.emit("label", l_rec)
            q = f.new_v()
            f.emit("bin", "div", q, v, ("imm", 10))
            p2 = f.new_v()
            f.emit("bin", "sub", p2, pad, ("imm", 1))
            f.emit("call", pos, "__fmt_u64", [buf, pos, q, p2])
            f.emit("label", l_wr)
            dd = f.new_v()
            f.emit("bin", "mod", dd, v, ("imm", 10))
            ch = f.new_v()
            f.emit("bin", "add", ch, dd, ("imm", 48))
            f.emit("store8", buf, pos, ch)
            f.emit("bin", "add", pos, pos, ("imm", 1))
            f.emit("ret", pos)
            self.out.append(f)

            # __f64_to_str(x) -> ptr
            f = Fn("__f64_to_str")
            x = f.new_v()
            f.emit("args", [x])
            buf = f.new_v()
            f.emit("call", buf, "__alloc", [("imm", 72)])   # 8 前缀 + 64 工作区
            pos = f.new_v()
            f.emit("mov", pos, ("imm", 8))                  # 字节区从 +8 起

            def st(chs):
                """从 pos 起写字符串（含结尾 0），返回后 pos 已前进"""
                nonlocal pos
                for cc in chs:
                    f.emit("store8", buf, pos, ("imm", cc))
                    f.emit("bin", "add", pos, pos, ("imm", 1))

            def ret_buf():
                # v1.5.1 长度前缀：pos-8 = 字节数；返回 buf+8
                ln = f.new_v()
                f.emit("bin", "sub", ln, pos, ("imm", 8))
                f.emit("store", buf, ("imm", 0), ln)
                r = f.new_v()
                f.emit("bin", "add", r, buf, ("imm", 8))
                f.emit("ret", r)

            def adv(k):
                nonlocal pos
                f.emit("bin", "add", pos, pos, ("imm", k))

            # nan
            c = f.new_v()
            f.emit("fcmpset", "f64", "ne", c, x, x)
            l1 = f.label("fnan")
            f.emit("jz", c, l1)
            f.emit("store8", buf, ("imm", 8), ("imm", 110))   # 'n'
            f.emit("store8", buf, ("imm", 9), ("imm", 97))    # 'a'
            f.emit("store8", buf, ("imm", 10), ("imm", 110))  # 'n'
            f.emit("store8", buf, ("imm", 11), ("imm", 0))
            adv(3)
            ret_buf()
            f.emit("label", l1)
            # +inf / -inf
            c = f.new_v()
            f.emit("fcmpset", "f64", "g", c, x, ("imm", fbits(1.7976931348623157e308)))
            l2 = f.label("finf")
            f.emit("jz", c, l2)
            f.emit("store8", buf, ("imm", 8), ("imm", 105))   # 'i'
            f.emit("store8", buf, ("imm", 9), ("imm", 110))   # 'n'
            f.emit("store8", buf, ("imm", 10), ("imm", 102))  # 'f'
            f.emit("store8", buf, ("imm", 11), ("imm", 0))
            adv(3)
            ret_buf()
            f.emit("label", l2)
            c = f.new_v()
            f.emit("fcmpset", "f64", "l", c, x, ("imm", fbits(-1.7976931348623157e308)))
            l3 = f.label("fninf")
            f.emit("jz", c, l3)
            f.emit("store8", buf, ("imm", 8), ("imm", 45))    # '-'
            f.emit("store8", buf, ("imm", 9), ("imm", 105))   # 'i'
            f.emit("store8", buf, ("imm", 10), ("imm", 110))  # 'n'
            f.emit("store8", buf, ("imm", 11), ("imm", 102))  # 'f'
            f.emit("store8", buf, ("imm", 12), ("imm", 0))
            adv(4)
            ret_buf()
            f.emit("label", l3)
            # 0
            c = f.new_v()
            f.emit("fcmpset", "f64", "e", c, x, ("imm", 0))   # +0.0 == 整数 0 位模式
            l4 = f.label("fzero")
            f.emit("jz", c, l4)
            f.emit("store8", buf, ("imm", 8), ("imm", 48))    # '0'
            f.emit("store8", buf, ("imm", 9), ("imm", 0))
            adv(1)
            ret_buf()
            f.emit("label", l4)
            # 负号（注意非 SSA：两条路径都必须先定义 xn，否则跳过分支后读垃圾）
            neg = f.new_v()
            f.emit("fcmpset", "f64", "l", neg, x, ("imm", 0))
            xn = f.new_v()
            l5, l5b = f.label("fpos"), f.label("fpos2")
            f.emit("jz", neg, l5)
            f.emit("store8", buf, pos, ("imm", 45))
            f.emit("bin", "add", pos, pos, ("imm", 1))
            f.emit("fneg", "f64", xn, x)
            f.emit("jmp", l5b)
            f.emit("label", l5)
            f.emit("mov", xn, x)
            f.emit("label", l5b)
            x = xn
            # 定点区间判定：1e-6 <= x < 1e12
            c1 = f.new_v()
            f.emit("fcmpset", "f64", "ge", c1, x, ("imm", fbits(1e-6)))
            c2 = f.new_v()
            f.emit("fcmpset", "f64", "l", c2, x, ("imm", fbits(1e12)))
            band = f.new_v()
            f.emit("bin", "and", band, c1, c2)
            l_sci = f.label("fsci")
            f.emit("jz", band, l_sci)
            # ---- 定点 ----
            t = f.new_v()
            f.emit("fbin", "f64", "mul", t, x, ("imm", fbits(1e6)))
            t2 = f.new_v()
            f.emit("fbin", "f64", "add", t2, t, ("imm", fbits(0.5)))
            u = f.new_v()
            f.emit("fcvt", "f64i", u, t2)
            ip = f.new_v()
            f.emit("bin", "div", ip, u, ("imm", 1000000))
            fp = f.new_v()
            f.emit("bin", "mod", fp, u, ("imm", 1000000))
            f.emit("call", pos, "__fmt_u64", [buf, pos, ip, ("imm", 1)])
            l_nf = f.label("fnofrac")
            f.emit("jz", fp, l_nf)
            f.emit("store8", buf, pos, ("imm", 46))          # '.'
            f.emit("bin", "add", pos, pos, ("imm", 1))
            p0 = f.new_v()
            f.emit("mov", p0, pos)
            f.emit("call", pos, "__fmt_u64", [buf, pos, fp, ("imm", 6)])
            # 去尾零
            l_tr, l_tre = f.label("ftr"), f.label("ftre")
            f.emit("label", l_tr)
            f.emit("jcc", "le", pos, p0, l_tre)
            m1 = f.new_v()
            f.emit("bin", "sub", m1, pos, ("imm", 1))
            ch = f.new_v()
            f.emit("load8", ch, buf, m1)
            f.emit("jcc", "ne", ch, ("imm", 48), l_tre)
            f.emit("bin", "sub", pos, pos, ("imm", 1))
            f.emit("jmp", l_tr)
            f.emit("label", l_tre)
            f.emit("label", l_nf)
            l_done = f.label("fdone")
            f.emit("jmp", l_done)
            # ---- 科学计数 ----
            f.emit("label", l_sci)
            exp = f.new_v()
            f.emit("mov", exp, ("imm", 0))
            # 注意非 SSA：循环变量必须原地更新（dst==src，同 itoa 的 div v,v,10），
            # 若写入新 vreg 再 rebind Python 变量，循环条件读到的仍是旧 vreg -> 死循环
            l_hi, l_hie = f.label("fhi"), f.label("fhie")
            f.emit("label", l_hi)
            c = f.new_v()
            f.emit("fcmpset", "f64", "ge", c, x, ("imm", fbits(10.0)))
            f.emit("jz", c, l_hie)
            f.emit("fbin", "f64", "div", x, x, ("imm", fbits(10.0)))
            f.emit("bin", "add", exp, exp, ("imm", 1))
            f.emit("jmp", l_hi)
            f.emit("label", l_hie)
            l_lo, l_loe = f.label("flo"), f.label("floe")
            f.emit("label", l_lo)
            c = f.new_v()
            f.emit("fcmpset", "f64", "l", c, x, ("imm", fbits(1.0)))
            f.emit("jz", c, l_loe)
            f.emit("fbin", "f64", "mul", x, x, ("imm", fbits(10.0)))
            f.emit("bin", "sub", exp, exp, ("imm", 1))
            f.emit("jmp", l_lo)
            f.emit("label", l_loe)
            t = f.new_v()
            f.emit("fbin", "f64", "mul", t, x, ("imm", fbits(1e6)))
            t2 = f.new_v()
            f.emit("fbin", "f64", "add", t2, t, ("imm", fbits(0.5)))
            m = f.new_v()
            f.emit("fcvt", "f64i", m, t2)
            l_mc = f.label("fmcarry")
            f.emit("jcc", "ne", m, ("imm", 10000000), l_mc)
            f.emit("mov", m, ("imm", 1000000))
            f.emit("bin", "add", exp, exp, ("imm", 1))
            f.emit("label", l_mc)
            d0 = f.new_v()
            f.emit("bin", "div", d0, m, ("imm", 1000000))
            rest = f.new_v()
            f.emit("bin", "mod", rest, m, ("imm", 1000000))
            f.emit("call", pos, "__fmt_u64", [buf, pos, d0, ("imm", 1)])
            l_nr = f.label("fnorest")
            f.emit("jz", rest, l_nr)
            f.emit("store8", buf, pos, ("imm", 46))
            f.emit("bin", "add", pos, pos, ("imm", 1))
            p0 = f.new_v()
            f.emit("mov", p0, pos)
            f.emit("call", pos, "__fmt_u64", [buf, pos, rest, ("imm", 6)])
            l_tr2, l_tre2 = f.label("ftr2"), f.label("ftre2")
            f.emit("label", l_tr2)
            f.emit("jcc", "le", pos, p0, l_tre2)
            m1 = f.new_v()
            f.emit("bin", "sub", m1, pos, ("imm", 1))
            ch = f.new_v()
            f.emit("load8", ch, buf, m1)
            f.emit("jcc", "ne", ch, ("imm", 48), l_tre2)
            f.emit("bin", "sub", pos, pos, ("imm", 1))
            f.emit("jmp", l_tr2)
            f.emit("label", l_tre2)
            f.emit("label", l_nr)
            # 指数
            f.emit("store8", buf, pos, ("imm", 101))          # 'e'
            f.emit("bin", "add", pos, pos, ("imm", 1))
            aexp = f.new_v()
            l_ep, l_eout = f.label("fepos"), f.label("feout")
            f.emit("jcc", "ge", exp, ("imm", 0), l_ep)
            f.emit("store8", buf, pos, ("imm", 45))           # '-'
            f.emit("bin", "add", pos, pos, ("imm", 1))
            f.emit("bin", "sub", aexp, ("imm", 0), exp)
            f.emit("jmp", l_eout)
            f.emit("label", l_ep)
            f.emit("store8", buf, pos, ("imm", 43))           # '+'
            f.emit("bin", "add", pos, pos, ("imm", 1))
            f.emit("mov", aexp, exp)
            f.emit("label", l_eout)
            f.emit("call", pos, "__fmt_u64", [buf, pos, aexp, ("imm", 1)])
            f.emit("label", l_done)
            f.emit("store8", buf, pos, ("imm", 0))
            # v1.51 修：有限值路径曾直接 ret(buf)——漏长度前缀、返回的是分配基址
            # 而不是字节区（buf+8），调用方按 str ABI 读到的长度是 0（打印空串）。
            ret_buf()
            self.out.append(f)

        # __str_from_bool(v) -> ptr
        f = Fn("__str_from_bool")
        v = f.new_v()
        f.emit("args", [v])
        l_f, l_e = f.label("sbf"), f.label("sbe")
        f.emit("jz", v, l_f)
        t = f.new_v()
        f.emit("movaddr", t, self.intern_str_lit("true"))
        f.emit("bin", "add", t, t, ("imm", 8))
        f.emit("ret", t)
        f.emit("label", l_f)
        g = f.new_v()
        f.emit("movaddr", g, self.intern_str_lit("false"))
        f.emit("bin", "add", g, g, ("imm", 8))
        f.emit("ret", g)
        f.emit("label", l_e)
        f.emit("ret", ("imm", 0))
        self.out.append(f)

    # ---- 浮点值跟踪（与 str/bool 同机制：vreg -> 'f32'/'f64'）----
    @staticmethod
    def _mark_float(fn, v, w):
        if isinstance(v, int):
            fv = getattr(fn, "floatv", None)
            if fv is None:
                fv = {}
                fn.floatv = fv
            fv[v] = w
        return v

    @staticmethod
    def _float_of(fn, x):
        """vreg -> 'f32'/'f64'；非浮点（含 imm/ga）返回 None"""
        if isinstance(x, int):
            return getattr(fn, "floatv", {}).get(x)
        return None

    # ---- 非负值域跟踪（v1.3 通用值域分析最小版：只标确凿模式）----
    @staticmethod
    def _is_nonneg(fn, x):
        if isinstance(x, tuple) and x and x[0] == "imm":
            return x[1] >= 0
        return isinstance(x, int) and x in getattr(fn, "nnv", set())

    @staticmethod
    def _mark_nonneg(fn, v):
        if isinstance(v, int):
            if not hasattr(fn, "nnv"):
                fn.nnv = set()
            fn.nnv.add(v)
        return v

    @staticmethod
    def _unmark_nonneg(fn, v):
        if isinstance(v, int) and hasattr(fn, "nnv"):
            fn.nnv.discard(v)
        return v

    # ---- 字符串值跟踪（非 SSA：在 Fn 上记一个集合）----
    @staticmethod
    def _is_str(fn, x):
        if isinstance(x, tuple) and x and x[0] == "ga":
            return True
        return isinstance(x, int) and x in getattr(fn, "strv", set())

    @staticmethod
    def _mark_str(fn, v):
        if not hasattr(fn, "strv"):
            fn.strv = set()
        fn.strv.add(v)
        return v

    @staticmethod
    def _mark_bool(fn, v):
        if isinstance(v, int):
            if not hasattr(fn, "boolv"):
                fn.boolv = set()
            fn.boolv.add(v)
        return v

    @staticmethod
    def _mark_chan(fn, v):
        if isinstance(v, int):
            if not hasattr(fn, "chanv"):
                fn.chanv = set()
            fn.chanv.add(v)
        return v

    @staticmethod
    def _is_chan(fn, v):
        return isinstance(v, int) and v in getattr(fn, "chanv", set())

    # ---- map 值跟踪（v0.10）：句柄 vreg -> (键标签, 值标签) ----
    @staticmethod
    def _mark_map(fn, v, kt, vt):
        if isinstance(v, int):
            if not hasattr(fn, "mapv"):
                fn.mapv = {}
            fn.mapv[v] = (kt, vt)
        return v

    @staticmethod
    def _mark_vec(fn, v, elem):
        if not isinstance(v, int):
            return v
        if not hasattr(fn, "vecv"):
            fn.vecv = set()
            fn.vecelem = {}
        fn.vecv.add(v)
        if elem is not None:
            fn.vecelem[v] = elem
        return v

    @staticmethod
    def _is_vec(fn, v):
        return isinstance(v, int) and v in getattr(fn, "vecv", set())

    @staticmethod
    def _vec_elem(fn, v):
        return getattr(fn, "vecelem", {}).get(v) if isinstance(v, int) else None

    def _vec_tag_of(self, et):
        """vec 元素标签（v1.12 统一入口；v1.37 加 mapinner）：str / ("agg", name) /
        ("vecinner", 内层标签) / ("mapinner", K, V) / None（标量）。形参、返回值、
        vecnew 三处共用——此前各自硬编码，嵌套 vec 拿不到标签导致 row.push 被拒。"""
        if et == ("named", "str"):
            return "str"
        if et and et[0] == "named" and self.is_agg(et[1]):
            return ("agg", et[1])
        if et and et[0] == "named" and et[1] in self.NARROW_BITS:
            # 窄标量元素（v1.40）：标签 = 类型名（与 parser 的 vec_elem_tag 一致）。
            # 消费方全是 "== 'str'" / isinstance(tuple) 判定，字符串标签走标量路径；
            # push/set 凭它查出窄宽度做截断，vecinner 嵌套时随内层标签穿透。
            return et[1]
        if et and et[0] == "vec":
            return ("vecinner", self._vec_tag_of(et[1]))
        if et and et[0] == "map":
            # vec[map[K]V]（v1.37）：句柄 1 字，与 vecinner 同构；
            # K/V 短标签供 get/pop 取回时重挂 map 标记
            return ("mapinner",
                    et[1][1] if et[1][0] == "named" else "int",
                    et[2][1] if et[2][0] == "named" else "int")
        return None

    @staticmethod
    def _map_of(fn, v):
        return getattr(fn, "mapv", {}).get(v) if isinstance(v, int) else None

    def run(self, fns_ast, reuse=None, reuse_order=None):
        """降级整个程序。

        reuse: {函数名: fn_record}（来自 `.qla` 的已降级+已优化函数）；
        reuse_order: 档案里的函数顺序——**复用的函数按这个顺序接管**，
        这样"什么都没改"的增量构建产物与全量构建逐字节相同。
        """
        # @extern("C") 声明只有函数原型、没有函数体：自研后端产出裸 ELF/PE，
        # 没有动态链接器可用，外部符号无处解析。这里必须给出明确诊断，
        # 而不是让 body=None 一路漏到 lowering 里炸成 Python traceback。
        # v1.87：@ffi("dll"[, "Sym"]) 是另一条路——它带 DLL 名，能进 PE 导入表，
        # 由加载器解析，**不需要**链接器；但那只在 Windows 上成立（ELF 后端产出
        # 静态 ET_EXEC，没有 PT_INTERP/PT_DYNAMIC），所以按平台分流。
        for f in fns_ast:
            if f.get("extern"):
                raise SyntaxError(
                    f'函数 {f["name"]} 声明为 @extern("C")：自研后端（Linux ELF / '
                    f"Windows PE）不链接外部符号，无法解析该声明；"
                    f"Windows 上请改用 @ffi(\"dll\"[, \"Sym\"])，"
                    f"或 --target c 由系统链接器接 libc")
            if f.get("ffi"):
                spec = f["ffi"]
                if self.platform != "windows":
                    raise SyntaxError(
                        f'函数 {f["name"]} 声明为 @ffi("{spec["dll"]}", '
                        f'"{spec["sym"]}")：@ffi 只在 Windows PE 后端实现——'
                        f"ELF 后端产出静态可执行文件（单 RWX PT_LOAD，"
                        f"无 PT_INTERP / 动态链接器），外部符号无处解析；"
                        f"请用 --target win 构建，或改用 syscall/内建")
                self.ffi_decls[f["name"]] = (
                    spec["dll"], spec["sym"],
                    [pt[1] for _pn, pt in f["params"]], f["ret"][1])
            elif f.get("body") is None:
                if f.get("qla"):
                    # v2.03：`.qla` 二进制库的声明——实现不在本单元，
                    # 由链接期按名字解析（`qlm_qla.merge` 补上）。
                    self.qla_stubs[f["name"]] = (f["params"], f["ret"])
                    continue
                raise SyntaxError(
                    f"函数 {f['name']} 没有函数体：无函数体的声明必须带 "
                    f'@extern("C") 或 @ffi("dll") 注解')
        self.build_iface_meta(fns_ast)
        reuse = reuse or {}
        adopted = set()
        if reuse:
            # 1) 按档案顺序原样接管（含 lambda 体 / parfor worker / 运行库
            #    helper——它们不在 fns_ast 里，只存在于档案中）
            for name in (reuse_order or list(reuse)):
                rec = reuse.get(name)
                if rec is None:
                    continue
                self._adopt(rec)
                adopted.add(name)
        # 2) 只降级"没被复用"的函数
        newly = 0
        fresh = []
        for f in fns_ast:
            if f.get("body") is None:
                continue          # @ffi 声明 / .qla 存根：无本地产物
            if f["name"] in adopted:
                continue
            before = self._flag_snapshot()
            start = len(self.out)
            self._cur_owner = f["name"]
            self.lower_fn(f)
            self._cur_owner = None
            after = self._flag_snapshot()
            self.fn_needs[f["name"]] = [k for k, v in after.items()
                                        if v and not before.get(k)]
            for fn in self.out[start:]:
                if fn.name != f["name"]:
                    self.fn_owner.setdefault(fn.name, f["name"])
                else:
                    fresh.append(fn)
            newly += 1
        # v1.95 闭包：lambda 体在外层函数之后降级（顺序无关，按名字引用）
        self.lower_pending_lambdas()
        # 3) 运行库：三种情况
        #    a) 全部函数复用 -> 不重发（否则新 intern 一批全局字，产物就
        #       不再与全量构建逐字节相同）；
        #    b) 部分复用，但新降级的函数要用到的 helper 全在档案里 -> 也不重发
        #       （省掉整个运行库的 IR 生成，是"改一个函数"的主要成本之一）；
        #    c) 其余 -> 照常发射，同名 helper 在下面按名字去重，留档案里那份。
        need_rt = None
        if reuse:
            need_rt = set()
            for fn in fresh:
                for ins in fn.instrs:
                    if ins and ins[0] == "call" and isinstance(ins[2], str) \
                            and ins[2].startswith("__"):
                        need_rt.add(ins[2])
                    elif ins and ins[0] == "fnaddr" and isinstance(ins[1], str) \
                            and ins[1].startswith("__"):
                        need_rt.add(ins[1])
            if getattr(self, "uses_args", False):
                need_rt.add("__qlm_args_boot")
        if not (reuse and newly == 0) and not (need_rt is not None
                                               and need_rt <= set(reuse)):
            self.lower_runtime()
        seen, out = set(), []
        for fn in self.out:
            if fn.name in seen:
                continue
            seen.add(fn.name)
            out.append(fn)
        self.out = out
        return self.out

    _FLAG_CACHE = None

    def _flag_snapshot(self):
        """`uses_*` 标志快照——一个函数"需要哪些运行库"就是它们的增量。"""
        names = Lower._FLAG_CACHE
        if names is None:
            names = sorted(n for n in dir(self) if n.startswith("uses_"))
            Lower._FLAG_CACHE = names
        return {n: getattr(self, n) for n in names}

    def _adopt(self, rec):
        """接管一条档案记录：置位它需要的运行库标志，并把 Fn 放进 out。"""
        import qlm_qla
        for n in rec.get("needs") or ():
            if hasattr(self, n):
                setattr(self, n, True)
        fn = qlm_qla.record_to_fn(rec)
        self.reuse_fns[fn.name] = fn
        self.out.append(fn)
        return fn


# ===========================================================================
# 第二部分：QuIR 优化 passes -> 线性扫描寄存器分配 -> 机器码发射 -> ELF
# ===========================================================================


# ---------------------------------------------------------------------------
# QuIR 优化 passes 独立模块：tools/stage0/qlm_opt.py（x86_64 / aarch64 发射层共享）
# 这里只做再导出，保持 `from qlm_native import vreg_mentions` 的既有用法可用。
# ---------------------------------------------------------------------------

from qlm_opt import (PURE, vreg_mentions, loop_regions,          # noqa: E402,F401
                        opt_dce, opt_copy_prop, opt_cse, opt_licm,
                        opt_loop_unroll, opt_all, opt_strlen_hoist)


# ---------------------------------------------------------------------------
# 过程内联（QuIR 级）：小函数 / 单调用点函数内联，递归/环禁止
# ---------------------------------------------------------------------------


def _map_ins(ins, f):
    """按指令形态重命名 vreg（f: vreg -> vreg）"""
    op = ins[0]
    V = f
    S = lambda x: f(x) if isinstance(x, int) else x
    L = lambda xs: [f(x) if isinstance(x, int) else x for x in xs]
    if op == "mov":
        return ("mov", V(ins[1]), S(ins[2]))
    if op == "bin":
        return ("bin", ins[1], V(ins[2]), S(ins[3]), S(ins[4]))
    if op == "fbin":
        return ("fbin", ins[1], ins[2], V(ins[3]), S(ins[4]), S(ins[5]))
    if op == "fneg":
        return ("fneg", ins[1], V(ins[2]), S(ins[3]))
    if op == "fcmpset":
        return ("fcmpset", ins[1], ins[2], V(ins[3]), S(ins[4]), S(ins[5]))
    if op == "fcvt":
        return ("fcvt", ins[1], V(ins[2]), S(ins[3]))
    if op in ("neg", "not"):
        return (op, V(ins[1]), S(ins[2]))
    if op == "cmpset":
        return ("cmpset", ins[1], V(ins[2]), S(ins[3]), S(ins[4]))
    if op in ("label", "jmp"):
        return ins
    if op in ("jz", "jnz"):
        return (op, S(ins[1]), ins[2])
    if op == "jcc":
        return ("jcc", ins[1], S(ins[2]), S(ins[3]), ins[4])
    if op == "call":
        return ("call", V(ins[1]) if ins[1] is not None else None, ins[2], L(ins[3]))
    if op == "callr":
        return ("callr", V(ins[1]) if ins[1] is not None else None, S(ins[2]), L(ins[3]))
    if op == "cssub":
        return ("cssub", V(ins[1]), S(ins[2]), S(ins[3]))
    if op == "ret":
        return ("ret", S(ins[1]) if ins[1] is not None else None)
    if op in ("load", "load8", "load32"):
        return (op, V(ins[1]), S(ins[2]), S(ins[3]))
    if op in ("store", "store8"):
        return (op, S(ins[1]), S(ins[2]), S(ins[3]))
    if op == "movaddr":
        return ("movaddr", V(ins[1]), ins[2])
    if op == "frameaddr":
        return ("frameaddr", V(ins[1]), ins[2])
    if op == "syscall":
        return ("syscall", V(ins[1]) if ins[1] is not None else None, ins[2], L(ins[3]))
    if op == "winapi":
        return ("winapi", V(ins[1]) if ins[1] is not None else None, ins[2], L(ins[3]))
    if op == "ffi":
        # ('ffi', dst, dll, sym, kinds, ret, args)：dll/sym/kinds/ret 是常量
        return ("ffi", V(ins[1]) if ins[1] is not None else None,
                ins[2], ins[3], ins[4], ins[5], L(ins[6]))
    if op == "cpuid_sha":
        return ("cpuid_sha", V(ins[1]))
    if op == "cpuid_aes":
        return ("cpuid_aes", V(ins[1]))
    if op == "cpuid_pclmul":
        return ("cpuid_pclmul", V(ins[1]))
    if op in ("xmm_mov", "pand_x", "por_x", "pshufb_x", "pclmul_x",
              "psrlw_i", "psllw_i", "psrlq_i", "psllq_i", "pslldq_i", "psrldq_i"):
        return ins                       # 槽号是负编码、立即数是常量：不需要重命名
    if op in ("xmm_ld", "xmm_st", "sha_nexte", "sha_rnds2", "sha_msg1",
              "sha_msg2", "xmm_paddd", "xmm_pxor", "xmm_pshufd", "xmm_palignr",
              "aesenc", "aesenclast", "aesdec", "aesdeclast", "aesimc",
              "aeskeygenassist"):
        # xmm 槽负数编码保留，地址实参（正 int）重命名
        return tuple(v if isinstance(v, int) and v < 0 else
                     (f(v) if isinstance(v, int) else v) for v in ins)
    if op == "xchg":
        return ("xchg", V(ins[1]), S(ins[2]), S(ins[3]))
    if op == "ldar":
        return ("ldar", V(ins[1]), S(ins[2]))
    if op == "stlr":
        return ("stlr", S(ins[1]), S(ins[2]))
    if op == "args":
        return ("args", [V(x) for x in ins[1]])
    if op == "trunc":
        return ("trunc", V(ins[1]), S(ins[2]), ins[3], ins[4])
    if op == "vsum":
        return ("vsum", V(ins[1]), S(ins[2]), S(ins[3]))
    if op == "vsumd":
        return ("vsumd", V(ins[1]), S(ins[2]), S(ins[3]))
    if op == "vdotd":
        return ("vdotd", V(ins[1]), S(ins[2]), S(ins[3]), S(ins[4]))
    if op == "vdot":
        return ("vdot", V(ins[1]), S(ins[2]), S(ins[3]), S(ins[4]))
    if op == "atomic":
        # ('atomic', sub, dst, addr, a[, b])：变长，cas 多一个操作数
        return tuple(["atomic", ins[1], V(ins[2]), S(ins[3]), S(ins[4])]
                     + ([S(ins[5])] if len(ins) > 5 else []))
    if op == "mfence":
        return ("mfence",)
    if op == "pause":
        return ("pause",)
    if op == "rdtsc":
        return ("rdtsc", V(ins[1]))
    # v1.62 调试标记：line 的行号不是 vreg，原样穿过内联；dbgvar/
    # dbgparam 的 vreg 要跟着重命名（否则内联后绑定指向 caller 空间里
    # 不存在的 vreg）
    if op == "line":
        return ins
    if op == "dbgvar":
        return ("dbgvar", ins[1], V(ins[2]))
    if op == "dbgparam":
        return ("dbgparam", ins[1], V(ins[2]))
    raise AssertionError(f"_map_ins 缺少指令形态：{op}（内联会静默重命名错误）")
    if op == "winargs":
        return ("winargs", [V(x) for x in ins[1]])
    return ins


def _call_sites(fns):
    counts = {}
    for fn in fns:
        for ins in fn.instrs:
            if ins[0] == "call":
                counts[ins[2]] = counts.get(ins[2], 0) + 1
    return counts


def _reachable(g, start):
    seen, stack = set(), [start]
    while stack:
        n = stack.pop()
        for m in g.get(n, ()):
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def opt_inline(fns, max_instrs=60, rounds=3, hot=None, only=None):
    """内联：小函数一律内联，大函数仅单调用点；递归/调用环禁止

    hot: {函数名: 放宽阈值} —— 运行时热函数（__map_hash/__map_find 等）跨
    多个调用点也必须内联。
    only: 只改写这些调用者（v2.03 增量复用：档案里接管过来的函数已经是
    优化后的 IR，再跑一遍内联会让"什么都没改"的产物与全量构建不一致）。

    **阈值 28 -> 60（v2.93）**：28 是**优化前**的指令数口径（`lower_fn` 出来的
    原始 IR），而像 `jws` 这种"扫空白/扫字符串"的小函数，源码只有 10 行，
    降级后却有 43 条（循环的开销全在 label/jcc/jmp 上）。于是它们**永远进不了
    内联**，b9_json 每解析一个 token 就要真调一次。

    实测（本机 x86-64，min of 1，同轮对比）：

    | 基准 | 阈值 28 | 阈值 60 | 差 |
    |---|---|---|---|
    | b9_json | 92.0 ms | **78.9 ms** | **−14%** |
    | b1_int | 65.3 | 65.2 | 0 |
    | b7_sort | 96.0 | 96.2 | 0 |
    | b5_string | 104.5 | 105.1 | 0 |

    体积**没有变化**（hello / http_demo 逐字节同大小）：全局 DCE 先跑，
    多内联进来的副本只出现在真正调用了它们的程序里。

    注意这条阈值只对**单调用点**生效——多调用点的大函数仍按
    `big and counts > 1` 拒绝（否则每个调用点一份副本，代码会爆）。
    """
    hot = hot or {"__map_hash": 160, "__map_find": 160, "__map_len": 160}
    fmap = {f.name: f for f in fns}
    for _ in range(rounds):
        g = {f.name: {i[2] for i in f.instrs if i[0] == "call"} for f in fns}
        counts = _call_sites(fns)
        changed = False
        for fn in fns:
            if only is not None and fn.name not in only:
                continue
            out = []
            for ins in fn.instrs:
                if ins[0] == "call" and ins[2] in fmap:
                    callee = fmap[ins[2]]
                    cyclic = callee.name == fn.name or fn.name in _reachable(g, callee.name)
                    limit = hot.get(callee.name, max_instrs)
                    big = len(callee.instrs) > limit
                    if getattr(callee, "no_inline", False) or cyclic or (big and counts.get(callee.name, 0) > 1):
                        out.append(ins)
                        continue
                    out.extend(_inline_one(fn, callee, ins))
                    fn.inlined_from.add(callee.name)
                    changed = True
                else:
                    out.append(ins)
            fn.instrs = out
        if not changed:
            break
    return fns


def _inline_one(fn, callee, call_ins):
    dst, args = call_ins[1], call_ins[3]
    base = fn.nv
    ren = lambda v: v + base
    fn.nv += callee.nv
    # v2.93：**类型标记必须跟着重编号**。
    # `strv`/`boolv`/`floatv` 是按 **vreg 号**记的集合（`_mark_str` 等
    # 在降级时塞进去），发射层靠它们决定"这个值走 str ABI（`[len][bytes]`）
    # 还是当普通 8 字节整数"。内联把被调方的 vreg 整体平移到 `+base`，
    # 若不同步搬标记，被内联进去的 `__str_len` 结果就**不再被认成 str** ——
    # 于是 `__str_concat` 里那句 `len(s)` 变成"把长度前缀当整数读"，
    # 算出来的长度是垃圾，后面的 memcpy 按它拷贝就越界。
    # 表现：tests/t22_map.qma 在阈值 38 起 SIGSEGV（`__str_concat` 内联了
    # `__str_len`），阈值 28/34 时恰好没内联到那个尺寸，所以一直是隐藏的。
    #
    # 注意 `f64v` **不在这里**：它是 Codegen 阶段按 `f64_vregs(fn)` 现算的
    # （由 `fbin`/`fcvt` 这类指令反推，见该函数 docstring），不是降级时打的
    # 标记，所以内联后自动正确。
    for attr in ("strv", "boolv"):
        marks = getattr(callee, attr, None)
        if not marks:
            continue
        dstset = getattr(fn, attr, None)
        if dstset is None:
            dstset = set()
            setattr(fn, attr, dstset)
        for v in marks:
            if isinstance(v, int):
                dstset.add(ren(v))
    # `floatv` 是 **vreg -> 'f32'/'f64' 的 dict**（不是 set），单独搬。
    fmarks = getattr(callee, "floatv", None)
    if fmarks:
        fdst = getattr(fn, "floatv", None)
        if fdst is None:
            fdst = {}
            fn.floatv = fdst
        for v, w in fmarks.items():
            if isinstance(v, int):
                fdst[ren(v)] = w
    # 帧上结构体区要整体搬迁到 caller 的区里，否则两边槽位重叠
    fbase = fn.frame_words
    fn.frame_words += callee.frame_words
    # ⚠ 标签后缀必须带【caller 名字】：只用 caller.nv 时，两个不同函数
    # 可能在同一个 nv 上内联同一个 callee，生成同名标签；后发射的会覆盖
    # 前者，导致 EARLIER 函数里的跳转跳到 LATER 函数体内（已踩坑：
    # 断言失败路径静默变成正常退出）。
    suffix = f".inl_{fn.name}_{base}"
    rlab = lambda L: L + suffix
    end = f"{callee.name}{suffix}.end"
    res = []
    body = callee.instrs
    # 形参绑定：实参 -> 重命名后的形参 vreg
    if body and body[0][0] == "args":
        for p, a in zip(body[0][1], args):
            res.append(("mov", ren(p), a))
        body = body[1:]
    for ins in body:
        op = ins[0]
        if op == "ret":
            if ins[1] is not None and dst is not None:
                res.append(("mov", dst, ren(ins[1]) if isinstance(ins[1], int) else ins[1]))
            res.append(("jmp", end))
        elif op == "label":
            res.append(("label", rlab(ins[1])))
        elif op == "jmp":
            res.append(("jmp", rlab(ins[1])))
        elif op in ("jz", "jnz"):
            res.append((op, ren(ins[1]) if isinstance(ins[1], int) else ins[1], rlab(ins[2])))
        elif op == "jcc":
            res.append(("jcc", ins[1],
                        ren(ins[2]) if isinstance(ins[2], int) else ins[2],
                        ren(ins[3]) if isinstance(ins[3], int) else ins[3], rlab(ins[4])))
        elif op == "args":
            continue
        elif op == "dbgparam":
            # v1.62 调试信息：内联函数的形参绑定降级成普通变量绑定——
            # 它在调用点（实参搬迁之后）才诞生，不是"入口可用"；
            # 否则内联参数会以 bind=0 泄漏成调用方全函数可见的幽灵变量
            res.append(("dbgvar", ins[1], ren(ins[2]) if isinstance(ins[2], int) else ins[2]))
        elif op == "frameaddr":
            res.append(("frameaddr", ren(ins[1]), ins[2] + fbase))
        elif op == "load":
            # v2.93：**内联进来的 `load` 打标记，禁止 LICM 外提**。
            #
            # 为什么：内联把被调方的函数体塞进调用点，但 `load` 的 base 可能是
            # 被调方的形参（内联后被重编号成调用方的某个 vreg）。LICM 只看
            # "base 在本循环内是否被重定义" —— 重编号之后这个条件会**偶然成立**，
            # 于是把 load 提到一个它本来不属于的循环外面。
            #
            # 实测事故（tests/t22_map.qma，阈值提到 60 后必崩）：
            #   `__map_key_eq` 里的 `load 44, 0, 3`（读 vreg 0 的第 3 字）
            #   被 LICM 提到 `__map_find` 的**探测循环**之前；而那个 `0` 是
            #   `total` 的 map 句柄 —— 内联重编号恰好让它"看起来"不变。
            #   运行时读到的是错的槽位，越界后 memcpy 按垃圾长度拷贝 -> SIGSEGV。
            #
            # 保守处置：内联副本里的 load 一律不参与 LICM。代价是这些 load
            # 在循环里每轮重读（本来也可能被别处优化掉），收益远小于正确性。
            # `("load", dst, base, off, True)` 的第 5 位 = "来自内联"，发射层与
            # 其它 pass 都只读前 4 位，多一位不影响它们。
            m = _map_ins(ins, ren)
            # 记录"这条 load 来自内联"：用 (dst, base, off) 三元组登记在
            # caller 上，而不是往指令元组里加第 5 位 —— 元组长度是下游
            # `vreg_mentions`/`_map_ins`/发射层共同依赖的契约，加字段会在
            # 第一个不认它的 pass 里被悄悄丢掉（实测就是这样失效的）。
            try:
                fn.inline_loads.add((m[1], m[2], m[3]))
            except AttributeError:
                fn.inline_loads = {(m[1], m[2], m[3])}
            res.append(m)
        else:
            res.append(_map_ins(ins, ren))
    res.append(("label", end))
    return res


# ---------------------------------------------------------------------------
# 线性扫描寄存器分配（保守区间 + 调用感知）
# ---------------------------------------------------------------------------


def dbg_vreg_ranges(fn):
    """vreg -> (first_ins, last_ins)：原始提及区间（v1.62 调试器判断变量
    是否已死用）。不做 allocate() 的回边扩展——那是分配决策，不是作用域；
    原始区间是"这个 vreg 在哪些指令之间被提及"的安全超集。"""
    n = fn.nv
    first = [10 ** 9] * n
    last = [-1] * n
    for idx, ins in enumerate(fn.instrs):
        defs, uses = vreg_mentions(ins)
        for v in defs + uses:
            if 0 <= v < n:
                if idx < first[v]:
                    first[v] = idx
                if idx > last[v]:
                    last[v] = idx
    return first, last


def f64_vregs(fn):
    """返回承载 **f64**（8 字节 IEEE 位模式）的 vreg 集合。

    IR 里的类型是**逐指令**携带的（`fbin`/`fcvt`/`fneg`/`fcmpset` 都带
    width 字段），所以这里从这些"根"出发做不动点：

      * `fbin f64 d,a,b`   → d,a,b 是 f64
      * `fneg f64 d,a`     → d,a
      * `fcmpset f64 ...`  → a,b（dst 是 int！）
      * `fcvt i2f64 d,a`   → d；`f64i d,a` → a；`f32f64 d,a` → d；`f64f32 d,a` → a
      * `mov d,a`          → 双向传播（f64 只会在 f64 之间搬）

    保守边界：**只认 f64**。f32 仍走原来的"GPR 存位模式 + 每条指令 movd
    进出 XMM"路径 —— f32 的寄存器文件共用会牵扯 movd/movss 的部分寄存器
    写语义，收益小得多。

    误判风险：如果某个 f64 值只被 `mov` 传递、从不参与任何 f64 运算，
    它就不会进集合，继续住 GPR（ABI 本来就是 GPR 传位模式），无害。
    """
    # **SIMD 归约函数直接放弃**：`vsumd`/`vdotd` 的发射把 xmm0/xmm1 当固定
    # 临时寄存器用（movupd/addpd/movhlps 全写死），与 XPOOL 的 0-3 直接
    # 冲突。这类函数整体退回"f64 住 GPR"，正确性优先。
    if any(ins[0] in ("vsum", "vsumd", "vdot", "vdotd") for ins in fn.instrs):
        return set()

    s = set()
    changed = True
    while changed:
        changed = False
        for ins in fn.instrs:
            op = ins[0]
            add = ()
            if op == "fbin" and ins[1] == "f64":
                add = (ins[3], ins[4], ins[5])
            elif op == "fneg" and ins[1] == "f64":
                add = (ins[2], ins[3])
            elif op == "fcmpset" and ins[1] == "f64":
                add = (ins[3], ins[4])
            elif op == "fcvt":
                k = ins[1]
                if k == "i2f64":
                    add = (ins[2],)
                elif k == "f64i":
                    add = (ins[3],)
                elif k == "f32f64":
                    add = (ins[2],)
                elif k == "f64f32":
                    add = (ins[3],)
            elif op == "mov":
                d, a = ins[1], ins[2]
                if isinstance(a, int) and a in s:
                    add = (d,)
                elif isinstance(d, int) and d in s and isinstance(a, int):
                    add = (a,)
            for v in add:
                if isinstance(v, int) and v not in s:
                    s.add(v)
                    changed = True

    # ---- 冲突消解：vreg 编号在非 SSA 的 IR 里会被**复用** ----
    # 同一个编号可能在 A 处装 f64、在 B 处装整数（实测：`fcmpset` 的 dst
    # 在 inlined `__f64_to_str` 里又被当成整数用）。这种编号**一律退回 GPR**
    # —— f64 的发射路径对 GPR 操作数本来就有 movq 分支，只是慢一点；
    # 而判错方向（该在 GPR 的住进 XMM）会直接崩。
    #
    # 例外：`mov`/`load`/`store`/`ret`/`args`/`call` 是**类型无关**的搬运，
    # 它们不产生"必须是整数"的约束 —— 否则 `acc = acc + x` 这类
    # `mov var, tmp` 会把整个循环的浮点值赶回 GPR，优化直接失效。
    must_int = set()
    for ins in fn.instrs:
        op = ins[0]
        if op in ("fbin", "fneg") and ins[1] == "f64":
            continue
        if op == "fcmpset" and ins[1] == "f64":
            must_int.add(ins[3])                  # dst 是 0/1 的整数
            continue
        if op == "fcvt":
            k = ins[1]
            if k in ("i2f64", "f32f64"):
                must_int.add(ins[3])              # 源是整数/f32（住 GPR）
            elif k in ("f64i", "f64f32"):
                must_int.add(ins[2])              # 目的不是 f64
            else:
                d, u = vreg_mentions(ins)
                must_int.update(d)
                must_int.update(u)
            continue
        if op in ("mov", "load", "store", "ret", "args", "call", "callr"):
            continue
        d, u = vreg_mentions(ins)
        must_int.update(d)
        must_int.update(u)
    return s - must_int


def allocate(fn, pool=POOL, callee_saved=CALLEE_SAVED, f64=()):
    n = fn.nv
    first = [10 ** 9] * n
    last = [-1] * n
    call_sites = []
    for idx, ins in enumerate(fn.instrs):
        if ins[0] in ("call", "syscall", "winapi", "callr", "ffi"):
            call_sites.append(idx)
        defs, uses = vreg_mentions(ins)
        for v in defs + uses:
            if 0 <= v < n:
                first[v] = min(first[v], idx)
                last[v] = max(last[v], idx)

    # 循环回边处理（精确版）：数据流活跃分析，只对【真正跨回边活跃】的 vreg
    # 扩展区间覆盖整个循环区；循环内临时量保持短区间，避免无谓溢出。
    n_ins = len(fn.instrs)
    succs = [[] for _ in range(n_ins)]
    label_pos = {ins[1]: i for i, ins in enumerate(fn.instrs) if ins[0] == "label"}
    for i, ins in enumerate(fn.instrs):
        op = ins[0]
        if op == "ret":
            continue
        if op == "jmp":
            succs[i] = [label_pos[ins[1]]]
        elif op in ("jz", "jnz"):
            succs[i] = [label_pos[ins[2]], i + 1]
        elif op == "jcc":
            succs[i] = [label_pos[ins[4]], i + 1]
        elif i + 1 < n_ins:
            succs[i] = [i + 1]
    # 后向不动点：live_in[i]
    uses_at, defs_at = [], []
    for ins in fn.instrs:
        d, u = vreg_mentions(ins)
        defs_at.append(set(d))
        uses_at.append(set(u))
    live_in = [set() for _ in range(n_ins)]
    for _ in range(n_ins + 2):
        changed = False
        for i in range(n_ins - 1, -1, -1):
            live_out = set()
            for s in succs[i]:
                live_out |= live_in[s]
            new = (live_out - defs_at[i]) | uses_at[i]
            if new != live_in[i]:
                live_in[i] = new
                changed = True
        if not changed:
            break
    # 回边：凡在循环头活跃的值，区间扩展到整个循环区
    regions = []
    for i, ins in enumerate(fn.instrs):
        if ins[0] == "jmp" and ins[1] in label_pos and label_pos[ins[1]] < i:
            regions.append((label_pos[ins[1]], i))
    for _ in range(len(regions) + 1):
        changed = False
        for rs, re_ in regions:
            for v in live_in[rs]:
                if 0 <= v < n:
                    if first[v] > rs:
                        first[v] = rs
                        changed = True
                    if last[v] < re_:
                        last[v] = re_
                        changed = True
        if not changed:
            break

    alloc = {}
    free = list(pool)
    active = []       # (end, v, reg)
    nslots = 0
    used_callee = set()

    order = sorted([v for v in range(n) if last[v] >= 0], key=lambda v: first[v])
    for v in order:
        if v in f64:
            continue                     # f64 走 XMM 文件，见下面第二遍扫描
        # 释放已结束区间
        active = [(e, w, r) for (e, w, r) in active if e >= first[v]]
        free = list(pool)
        for _, _, r in active:
            if r in free:
                free.remove(r)
        span_call = any(first[v] < c < last[v] for c in call_sites)
        candidates = [r for r in free if (not span_call or r in callee_saved)]
        if candidates:
            # 不跨调用的优先用 caller-saved，节省被调用者保存寄存器
            if span_call:
                reg = candidates[0]
            else:
                caller_first = [r for r in candidates if r not in callee_saved]
                reg = caller_first[0] if caller_first else candidates[0]
            alloc[v] = ("r", reg)
            active.append((last[v], v, reg))
            active.sort()
            if reg in callee_saved:
                used_callee.add(reg)
        else:
            # v2.73：**没有空闲寄存器时，溢出"区间结束得最晚"的那个**，
            # 把寄存器让给当前值（当前值的区间更短）。
            #
            # 以前是无条件溢出**当前值** —— 于是短命临时值（取位循环里的
            # q、q*10、字符）反而被赶进栈，下一条指令立刻又读回来，每位数
            # 8 次内存往返。经典线性扫描的溢出启发式就是"spill the interval
            # with the furthest end"，这里补上。
            #
            # 安全性：`alloc` 是最终表，发射器按它取位置；把某个 vreg 从
            # 寄存器改成栈槽后，`fetch` 会老老实实 `mov reg, [rbp-off]`。
            victim = None
            for t in active:
                if t[0] > last[v] and (not span_call or t[2] in callee_saved):
                    if victim is None or t[0] > victim[0]:
                        victim = t
            if victim is not None:
                _e, _w, _r = victim
                active.remove(victim)
                alloc[_w] = ("m", 8 * (nslots + 1))
                nslots += 1
                alloc[v] = ("r", _r)
                active.append((last[v], v, _r))
                active.sort()
            else:
                alloc[v] = ("m", 8 * (nslots + 1))   # 溢出到栈槽：[rbp-8], ...
                nslots += 1

    # ---- 第二遍：f64 走 XMM 寄存器文件（v2.65）----
    # 与 GPR 同一套线性扫描，只是换一个寄存器池。两条硬约束：
    #   1. **跨调用的值落栈**：XMM0-3 全是 caller-saved，任何被调方（含
    #      WinAPI）都可以随手踩掉；
    #   2. 栈槽与 GPR 溢出槽**共用 nslots 计数器**，否则会互相覆盖。
    used_xcallee = set()
    if f64:
        active = []
        for v in order:
            if v not in f64:
                continue
            active = [(e, w, r) for (e, w, r) in active if e >= first[v]]
            span_call = any(first[v] < c < last[v] for c in call_sites)
            busy = {r for (_, _, r) in active}
            # 跨调用 → 非易失池（XMM6-15，序言保存/尾声恢复）；
            # 不跨调用 → caller-saved 池（省掉保存/恢复）。
            pools = (XPOOL_CALLEE, XPOOL) if span_call else (XPOOL, XPOOL_CALLEE)
            reg = None
            for pl in pools:
                cand = [r for r in pl if r not in busy]
                if cand:
                    reg = cand[0]
                    break
            if reg is not None:
                alloc[v] = ("x", reg)
                active.append((last[v], v, reg))
                active.sort()
                if reg in XPOOL_CALLEE:
                    used_xcallee.add(reg)
            else:
                alloc[v] = ("m", 8 * (nslots + 1))
                nslots += 1
    return alloc, nslots, sorted(used_callee), sorted(used_xcallee)


# ---------------------------------------------------------------------------
# 机器码发射
# ---------------------------------------------------------------------------

BASE = 0x400000
ENTRY_OFF = 0x78

# 各架构 Linux 系统调用号（IR 层架构无关，发射层按表取用）
SYSCALLS = {
    "x86_64": {"write": 1, "exit": 60, "mmap": 9, "clone": 56, "wait4": 61,
               "yield": 24, "read": 0, "close": 3, "openat": 257,
               "socket": 41, "bind": 49, "listen": 50, "accept": 43,
               "sendto": 44, "recvfrom": 45, "connect": 42,
               "getsockname": 51, "setsockopt": 54,
               "clock_gettime": 228,
               "mkdir": 83, "unlink": 87, "access": 21, "lseek": 8,
               "nanosleep": 35, "getpid": 39},
    "aarch64": {"write": 64, "exit": 93, "mmap": 222, "clone": 220, "wait4": 260,
                "yield": 124, "read": 63, "close": 57, "openat": 56,
                "socket": 198, "bind": 200, "listen": 201, "accept": 202,
                "sendto": 206, "recvfrom": 207, "connect": 203,
                "getsockname": 204, "setsockopt": 208,
                "clock_gettime": 113,
                "mkdir": 34, "unlink": 35, "access": 48, "lseek": 62,
                "nanosleep": 101, "getpid": 172},
}

# 小对象尺寸类数量：32 字节粒度，覆盖 32..1024 字节（__alloc/__free 空闲链）
FREE_CLASSES = 32


class Codegen:
    def __init__(self, fns, globals_bytes, base=BASE, entry_off=ENTRY_OFF, low=None):
        self.fns = fns
        self.globals = globals_bytes
        self.low = low            # 需要 argc/argv 全局字时读 low.argc_gid / low.argv_gid
        self.base = base
        self.entry_off = entry_off
        self.enc = Enc()
        self.global_fixups = []    # (patch_pos, gid) -> 数据区绝对地址
        self.code_fixups = []      # (patch_pos, label) -> 代码区绝对地址（线程入口等）
        # v1.62 调试信息：{"funcs": [{name,file,rva,lines,vars}, ...]}
        # lines/vars 的 offset 都是 .text 内偏移（RVA = TEXT_RVA + offset，
        # 由 WinCodegen.gen_all_pe 统一补）；file=None 表示无源码行号
        # （import 的库函数 / 运行库合成函数）。
        self.dbg = {"funcs": []}
        self._dbg = None           # 当前函数的收集态
        self.f64v = set()          # 当前函数里承载 f64 的 vreg（住 XMM）
        self.used_xcallee = []     # 本函数用到的非易失 XMM（序言保存/尾声恢复）
        self.xsave_base = 0

    # ---- v1.62 调试信息收集 ----
    def _dbg_reset(self, fn):
        self._dbg = {"name": fn.name, "file": getattr(fn, "dbg_file", None),
                     "rva": None, "push": 1, "lines": [], "vars": [],
                     "branches": []}
        self._dbg_cur = 0          # 当前源码行（分支表用它标"分支属于哪一行"）

    def _dbg_line(self, line):
        self._dbg["lines"].append([self.enc.pos(), line])
        self._dbg_cur = line

    def _dbg_branch(self, off, label, cc):
        """v1.83 分支表：记 (jcc 偏移, 目标标签, 条件码, 源码行)。

        标签在 gen_all 末尾统一解析成偏移——前向标签发射到这里时还没有位置。
        「不跳」边的目标恒为 off+6：本编码器的 jcc 一律 rel32（6 字节），
        所以不必再存一份。"""
        if self._dbg is None:
            return
        self._dbg["branches"].append([off, label, cc, self._dbg_cur])

    def _dbg_var(self, ins):
        if ins[0] == "dbgparam":
            _, name, v = ins
            self._dbg["vars"].append([self.enc.pos(), name, v, 1])
        else:
            _, name, v = ins
            self._dbg["vars"].append([self.enc.pos(), name, v, 0])

    def _dbg_kind(self, fn, v):
        """vreg -> 显示类型。类型标记集合要等 lowering 全部结束才最终，
        故在 codegen 期解析；优先级 struct > str > bool > f64 > int。"""
        if v in getattr(fn, "structv", {}):
            return ("struct", fn.structv[v])
        if v in getattr(fn, "strv", set()):
            return ("str", None)
        if v in getattr(fn, "boolv", set()):
            return ("bool", None)
        fv = getattr(fn, "floatv", {}).get(v)
        if fv:
            return (fv, None)
        return ("int", None)

    def _dbg_finish(self, fn, ins_off):
        """把当前函数的行表/变量绑定钉上机器码位置：
        - loc = 线性扫描分配结果：("r", 寄存器号) 或 ("m", 帧槽字节距)，
          地址即 [rbp - off]（与 fetch/commit 的寻址同源）；
        - last = vreg 最后一次被提及的指令位置——之后的帧槽/寄存器可能
          被复用，调试器据此标 <dead>，不显示过期值；
        - entry=1（自身形参）：bind 取 args 之后第一条真实指令的偏移。
          'args' 是函数第一条指令（把参数寄存器搬进形参 vreg），断点落在
          第一条语句行首时它还没执行——那时形参不可读；
        - let 绑定：bind = 绑定 mov 之后的位置（dbgvar 标记在 mov 之后）。
          可用规则（调试器侧）：bind <= 当前 PC。在 `let x = ...` 自己
          那条行上 PC 在 mov 之前 -> 不可用（赋值还没发生）；mov 之后的
          任何断点 -> 可用。"""
        first, last = dbg_vreg_ranges(fn)
        # args 之后第一条真实指令的偏移（自身形参的可用起点）
        after_args = ins_off[0]
        for o in ins_off:
            if o > ins_off[0]:
                after_args = o
                break
        vars_out = []
        for off, name, v, entry in self._dbg["vars"]:
            loc = self.alloc.get(v)
            if loc is None:
                continue
            kind, extra = self._dbg_kind(fn, v)
            end = ins_off[last[v]] if 0 <= v < len(last) and last[v] >= 0 else off
            vars_out.append({"name": name, "kind": kind, "s": extra,
                             "bind": (after_args if entry else off), "entry": entry,
                             "loc": [loc[0], loc[1]], "last": end})
        self._dbg["vars"] = vars_out
        self._dbg["lines"].sort(key=lambda e: e[0])
        self.dbg["funcs"].append(self._dbg)
        self._dbg = None

    # ---- 操作数 ----
    def fetch(self, target, spec):
        if isinstance(spec, int):
            kind, val = self.alloc[spec]
            if kind == "x":
                raise RuntimeError(
                    f"[{getattr(self, 'cur_fn_name', '?')}] f64 vreg v{spec} "
                    f"走了整数路径（fetch）—— 该指令的发射没接 XMM 分支")
            if kind == "r":
                return val
            self.enc.mov_rm(target, RBP, 4, 0, -val)
            return target
        if spec[0] == "imm":
            self.enc.mov_ri(target, spec[1])
            return target
        if spec[0] == "fnaddr":
            # 代码地址（线程入口 / 回调）：movabs + 回填（PE 下同时生成 DIR64 重定位）
            self.enc.emit(rex(w=1, b=target), bytes([0xB8 + (target & 7)]))
            self.code_fixups.append((self.enc.pos(), spec[1]))
            self.enc.emit(b"\x00" * 8)
            return target
        # ('ga', gid)
        self.enc.emit(rex(w=1, b=target), bytes([0xB8 + (target & 7)]))
        self.global_fixups.append((self.enc.pos(), spec[1]))
        self.enc.emit(b"\x00" * 8)
        return target

    def commit_ret(self, dst):
        """被调方返回值落地。ABI 不变（f64 也按位模式走 RAX），
        所以 f64 结果要额外搬进 XMM 家。"""
        if isinstance(dst, int) and dst in self.f64v:
            kind, val = self.alloc[dst]
            if kind == "x":
                self.enc.movq_xr(val, ACC)
                return
            self.enc.movq_xr(XS0, ACC)
            self.fcommit(dst, XS0)
            return
        self.commit(dst, ACC)

    def fx(self, x, spec):
        """把 f64 操作数放进 XMM `x`，返回**真正**持有它的 XMM 号。

        - 已经在 XMM 里 → 直接返回那个号（零搬运）
        - 在 GPR 里     → movq（1 条，1 周期）
        - 在栈槽里      → movsd 直接从内存进 XMM（以前是 mov gpr,[mem] +
                          movq xmm,gpr 两条，还要过一趟存储转发）
        """
        if isinstance(spec, int):
            kind, val = self.alloc[spec]
            if kind == "x":
                if val != x:
                    # 已在 XMM 但不在目标号 —— 必须真的搬过去。
                    # （v2.65 第一版这里直接 return val，调用方以为值在 x 里，
                    #   b2 算出 0.0 —— 静默错值，不是崩溃。）
                    self.enc.movaps_rr(x, val)
                return x
            if kind == "r":
                self.enc.movq_xr(x, val)
                return x
            self.enc.movsd_xm(x, RBP, 4, 0, -val)
            return x
        if isinstance(spec, tuple) and spec[0] == "imm":
            self.enc.mov_ri(SCRATCH, spec[1])
            self.enc.movq_xr(x, SCRATCH)
            return x
        raise RuntimeError(f"f64 操作数形态不支持：{spec!r}")

    def fcommit(self, dst, x):
        """XMM `x` -> dst 的家（XMM / GPR / 栈槽）。"""
        kind, val = self.alloc[dst]
        if kind == "x":
            if val != x:
                self.enc.movaps_rr(val, x)
        elif kind == "r":
            self.enc.movq_rx(val, x)
        else:
            self.enc.movsd_mx(RBP, 4, 0, -val, x)

    def fp_from_gpr(self, w, x, r):
        """GPR 位模式 -> XMM x（f64 走 movq，f32 走 movd）"""
        if w == "f64":
            self.enc.movq_xr(x, r)
        else:
            self.enc.movd_xr(x, r)

    def fp_to_dst(self, w, dst, x):
        """XMM x -> dst vreg（f32 写出后高位清零，保持 64 位槽语义）"""
        rd = self.safe_dst_reg(dst)
        if rd is not None:
            if w == "f64":
                self.enc.movq_rx(rd, x)
            else:
                self.enc.movd_rx(rd, x)
            return
        if w == "f64":
            self.enc.movq_rx(SCRATCH2, x)
        else:
            self.enc.movd_rx(SCRATCH2, x)
        self.commit(dst, SCRATCH2)

    def commit(self, dst, reg):
        kind, val = self.alloc[dst]
        if kind == "x":
            raise RuntimeError(
                f"[{getattr(self, 'cur_fn_name', '?')}] f64 vreg v{dst} "
                f"走了整数路径（commit）—— 该指令的发射没接 XMM 分支")
        if kind == "r":
            if val != reg:
                self.enc.mov_rr(val, reg)
        else:
            self.enc.mov_mr(RBP, 4, 0, -val, reg)

    def mat(self, target, spec):
        """强制把操作数物化到 target（破坏性运算前必调，避免改写活值）"""
        r = self.fetch(target, spec)
        if r != target:
            self.enc.mov_rr(target, r)
        return target

    def src_move(self, spec):
        if isinstance(spec, int):
            kind, val = self.alloc[spec]
            if kind == "x":
                return ("x", val)
            return (kind, val) if kind == "r" else ("m", val)
        return spec  # ('imm', n) / ('ga', gid)

    def dst_move(self, dst):
        kind, val = self.alloc[dst]
        if kind == "x":
            return ("x", val)
        return ("r", val) if kind == "r" else ("m", val)

    def safe_dst_reg(self, dst, others=()):
        """dst 驻留寄存器、且该寄存器不被 others 里的其他 vreg 占用时返回寄存器号。

        用途：把运算**直接做在 dst 的寄存器里**（二地址形式），省掉
        mat->scratch 运算->commit 的两次搬运。

        安全性依据（见 allocate()）：线性扫描对**同一指令位置上同时活跃**的
        vreg 保证分配到不同寄存器。本指令里 dst 是定义、a/b 是使用，
        三者在本指令处同时活跃 => 寄存器互不相同。
        此处再做一次显式校验作为保险：只要发现别的 vreg 与 dst 同寄存器
        就退回保守路径，绝不冒险。
        """
        kind, val = self.alloc.get(dst, ("m", 0))
        if kind != "r":
            return None
        for o in others:
            if isinstance(o, int) and o != dst:
                k2, v2 = self.alloc.get(o, ("m", 0))
                if k2 == "r" and v2 == val:
                    return None
        return val

    def parallel_move(self, moves):
        """moves: [(src, dst)] src=('r',r)|('m',off)|('imm',n)|('ga',gid), dst=('r',r)|('m',off)"""
        pending = list(moves)
        while pending:
            progressed = False
            for i, (src, dst) in enumerate(pending):
                if dst[0] == "r":
                    blocked = False
                    for j, (s, d) in enumerate(pending):
                        if j != i and s[0] == "r" and s[1] == dst[1]:
                            blocked = True
                            break
                    if blocked:
                        continue
                self.emit_move(src, dst)
                pending.pop(i)
                progressed = True
                break
            if not progressed:
                # 环：用 SCRATCH 打破
                for i, (src, dst) in enumerate(pending):
                    if src[0] == "r":
                        self.enc.mov_rr(SCRATCH, src[1])
                        pending[i] = (("r", SCRATCH), dst)
                        break
                    if src[0] == "x":
                        self.enc.movaps_rr(XS0, src[1])
                        pending[i] = (("x", XS0), dst)
                        break
                else:
                    raise RuntimeError("并行搬移无法调度")

    def _emit_call_args(self, args):
        """调用实参布局（v1.42 ABI）：前 6 参进 ARG_REGS（并行搬移，既有路径），
        第 7 参起进调用方溢出区：sub rsp 开区 -> 逐参经 SCRATCH 存 [rsp+8j]。
        返回栈参数个数（call/callr 在 call 之后按它回卷 rsp）。
        安全性：参数搬移只写 ARG_REGS 与 SCRATCH（都在分配池外），池寄存器与
        RBP 相对槽不受影响——栈实参的取值在搬移前后读都正确。
        调用点栈布局：call 压返回地址后，被调方 [rbp+8]=返回地址、
        [rbp+16+8j]=第 7+j 参（'args' 指令的 ("stk", j) 源与之对应）。"""
        reg = args[:6]
        stk = args[6:]
        moves = [(self.src_move(a), ("r", ARG_REGS[i])) for i, a in enumerate(reg)]
        self.parallel_move(moves)
        if stk:
            self.enc.alu_ri("sub", RSP, 8 * len(stk))
            for j, a in enumerate(stk):
                if isinstance(a, int) and a in self.f64v:
                    self.fx(XS0, a)
                    self.enc.movq_rx(SCRATCH, XS0)
                else:
                    self.mat(SCRATCH, a)
                self.enc.mov_mr(RSP, 4, 0, 8 * j, SCRATCH)
        return len(stk)

    def _stkarg_base(self):
        """栈实参在被调方帧里的基址偏移（v1.42）。
        序言是 push callee-saved -> push rbp -> mov rbp,rsp，所以 [rbp+8]
        不是返回地址：ret 在 [rbp + 8*(1+n)]（n = rbp 之前的 push 数），
        第一个栈实参在 [rbp + 8*(2+n)]（= 调用点的 [rsp+0]，call 压 ret 后
        恰好落到这里）。线程入口（win_thread）在 callee-saved 之前还压了
        RDI/RSI 两次，一并计入——线程函数当前不收栈实参，公式保持成立。"""
        n = len(self.used_callee or [])
        if getattr(self, "cur_fn_thread", False):
            n += 2
        return 8 * (2 + n)

    def emit_move(self, src, dst):
        # ---- XMM 端（f64）：GPR 侧一律走 movq 位模式搬运，ABI 不变 ----
        if src[0] == "x" or dst[0] == "x":
            if src[0] == "x" and dst[0] == "x":
                if src[1] != dst[1]:
                    self.enc.movaps_rr(dst[1], src[1])
            elif src[0] == "x" and dst[0] == "r":
                self.enc.movq_rx(dst[1], src[1])
            elif src[0] == "r" and dst[0] == "x":
                self.enc.movq_xr(dst[1], src[1])
            elif src[0] == "x" and dst[0] == "m":
                self.enc.movsd_mx(RBP, 4, 0, -dst[1], src[1])
            elif src[0] == "m" and dst[0] == "x":
                self.enc.movsd_xm(dst[1], RBP, 4, 0, -src[1])
            elif src[0] == "imm" and dst[0] == "x":
                self.enc.mov_ri(SCRATCH, src[1])
                self.enc.movq_xr(dst[1], SCRATCH)
            elif src[0] == "stk" and dst[0] == "x":
                base = self._stkarg_base() + src[1] * 8
                self.enc.mov_rm(SCRATCH, RBP, 4, 0, base)
                self.enc.movq_xr(dst[1], SCRATCH)
            else:
                raise RuntimeError(f"f64 搬移不支持：{src!r} -> {dst!r}")
            return
        if src[0] == "r" and dst[0] == "r":
            if src[1] != dst[1]:
                self.enc.mov_rr(dst[1], src[1])
        elif src[0] == "stk":
            # 栈实参（v1.42）：调用方溢出区 -> dst（偏移见 _stkarg_base）
            base = self._stkarg_base() + src[1] * 8
            if dst[0] == "r":
                self.enc.mov_rm(dst[1], RBP, 4, 0, base)
            else:
                self.enc.mov_rm(SCRATCH, RBP, 4, 0, base)
                self.enc.mov_mr(RBP, 4, 0, -dst[1], SCRATCH)
        elif src[0] == "r" and dst[0] == "m":
            self.enc.mov_mr(RBP, 4, 0, -dst[1], src[1])
        elif src[0] == "m" and dst[0] == "r":
            self.enc.mov_rm(dst[1], RBP, 4, 0, -src[1])
        elif src[0] == "m" and dst[0] == "m":
            self.enc.mov_rm(SCRATCH, RBP, 4, 0, -src[1])
            self.enc.mov_mr(RBP, 4, 0, -dst[1], SCRATCH)
        elif src[0] == "imm" and dst[0] == "r":
            self.enc.mov_ri(dst[1], src[1])
        elif src[0] == "imm" and dst[0] == "m":
            self.enc.mov_ri(SCRATCH, src[1])
            self.enc.mov_mr(RBP, 4, 0, -dst[1], SCRATCH)
        elif src[0] == "fnaddr" and dst[0] == "r":
            self.enc.emit(rex(w=1, b=dst[1]), bytes([0xB8 + (dst[1] & 7)]))
            self.code_fixups.append((self.enc.pos(), src[1]))
            self.enc.emit(b"\x00" * 8)
        elif src[0] == "fnaddr" and dst[0] == "m":
            self.enc.emit(rex(w=1, b=SCRATCH), bytes([0xB8 + (SCRATCH & 7)]))
            self.code_fixups.append((self.enc.pos(), src[1]))
            self.enc.emit(b"\x00" * 8)
            self.enc.mov_mr(RBP, 4, 0, -dst[1], SCRATCH)
        elif src[0] == "ga" and dst[0] == "r":
            self.enc.emit(rex(w=1, b=dst[1]), bytes([0xB8 + (dst[1] & 7)]))
            self.global_fixups.append((self.enc.pos(), src[1]))
            self.enc.emit(b"\x00" * 8)
        elif src[0] == "ga" and dst[0] == "m":
            self.enc.emit(rex(w=1, b=SCRATCH), bytes([0xB8 + (SCRATCH & 7)]))
            self.global_fixups.append((self.enc.pos(), src[1]))
            self.enc.emit(b"\x00" * 8)
            self.enc.mov_mr(RBP, 4, 0, -dst[1], SCRATCH)
        else:
            raise RuntimeError(f"无法搬移 {src} -> {dst}")

    # ---- 单条指令 ----
    def gen_instr(self, ins):
        enc = self.enc
        op = ins[0]
        # v1.62 调试信息标记：不发射任何字节，只把位置记进行表/变量表。
        # 标记被 qlm_opt._EFF 登记为效应指令，调度器不会把它浮走，
        # 因此记录到的 enc.pos() 就是"语句边界"的真实机器码位置。
        if op == "line":
            self._dbg_line(ins[1])
            return
        if op == "dbgvar":
            self._dbg_var(ins)
            return
        if op == "dbgparam":
            self._dbg_var(ins)
            return
        if op == "ffi":
            # v1.87：'ffi' 只有 WinCodegen（PE 导入表）能发射。Lower 已按平台
            # 拦截过，这里是二道闸——绝不静默生成一条指向空标签的调用。
            raise SyntaxError(
                "FFI（@ffi）只在 Windows PE 后端实现（需要导入表 + 加载器）")
        if op == "cpuid_pclmul":
            # PCLMULQDQ 特征探测：CPUID leaf 1（ECX=0）ECX[1]。
            _, dst = ins
            R11 = 11
            enc.push(RAX)
            enc.push(RBX)
            enc.push(RCX)
            enc.push(RDX)
            enc.mov_ri(RAX, 1)
            enc.mov_ri(RCX, 0)
            enc.cpuid()
            enc.mov_rr(R11, RCX)
            enc.shr_i(R11, 1)
            enc.alu_ri("and", R11, 1)
            enc.pop(RDX)
            enc.pop(RCX)
            enc.pop(RBX)
            enc.pop(RAX)
            self.commit(dst, R11)
            return
        if op == "cpuid_aes":
            # AES-NI 特征探测：CPUID leaf 1（ECX=0）ECX[25]。
            # 与 cpuid_sha 同一套纪律：全寄存器保护，结果经 R11 中转。
            _, dst = ins
            R11 = 11
            enc.push(RAX)
            enc.push(RBX)
            enc.push(RCX)
            enc.push(RDX)
            enc.mov_ri(RAX, 1)
            enc.mov_ri(RCX, 0)
            enc.cpuid()
            enc.mov_rr(R11, RCX)
            enc.shr_i(R11, 25)
            enc.alu_ri("and", R11, 1)
            enc.pop(RDX)
            enc.pop(RCX)
            enc.pop(RBX)
            enc.pop(RAX)
            self.commit(dst, R11)
            return
        if op == "cpuid_sha":
            # SHA-NI 特征探测：CPUID leaf 7（ECX=0）EBX[29]。
            # cpuid 破坏 RAX/RBX/RCX/RDX（RAX 是 ACC、RBX 在池）——push/pop
            # 全保护，结果经 R11 中转（R11 非池，pop 不会覆盖它）。探测一次
            # 成本无所谓，正确性优先。arm64 无 cpuid：gen 为常量 0。
            _, dst = ins
            R11 = 11
            enc.push(RAX)
            enc.push(RBX)
            enc.push(RCX)
            enc.push(RDX)
            enc.mov_ri(RAX, 7)
            enc.mov_ri(RCX, 0)
            enc.cpuid()
            enc.mov_rr(R11, RBX)
            enc.shr_i(R11, 29)
            enc.alu_ri("and", R11, 1)
            enc.pop(RDX)
            enc.pop(RCX)
            enc.pop(RBX)
            enc.pop(RAX)
            self.commit(dst, R11)
            return
        if op == "vsumd":
            # f64 归约（v1.16）：movupd 非对齐读 + addpd 两路累加 + 标量尾。
            # 结构与 vsum 完全同构：RCX 是元素下标（步 2）、lea(RDX, RCX, 2)
            # 是"下一对下标"边界检查（RDX = RCX + 2 > cnt 则退出向量段）。
            # bug 史：v1.16 首版把 lea 的第三参写成 3（把"字节 scale"与
            # "元素步进"混淆——lea(dst, base, disp) 的 disp 是**简单加法**，
            # 不是乘法），导致每 8 元素漏 2 个（s=255 → s!=255）。
            _, dst, base, count = ins
            seq = getattr(self, "_vsumd_seq", 0)
            self._vsumd_seq = seq + 1
            Lv, Lt, Ls, Ld = (f"__vsumd.v{seq}", f"__vsumd.t{seq}",
                              f"__vsumd.s{seq}", f"__vsumd.d{seq}")
            bp = self.mat(SCRATCH, base)
            cnt = self.mat(SCRATCH2, count)
            enc.mov_ri(RCX, 0)
            enc.pxor_x(0, 0)
            enc.labels[Lv] = enc.pos()
            enc.lea(RDX, RCX, 2)                 # 下一对下标（元素计数）
            enc.alu_rr("cmp", RDX, cnt)
            enc.jcc("g", Lt)
            enc.movupd_rm(1, bp, RCX, 3, 0)      # [bp + RCX*8]（字节偏移）
            enc.addpd(0, 1)
            enc.alu_ri("add", RCX, 2)
            enc.jmp(Lv)
            enc.labels[Lt] = enc.pos()
            enc.movhlps(1, 0)                    # xmm1 低 = xmm0 高
            enc.addsd(0, 1)
            enc.movq_rx(ACC, 0)
            enc.labels[Ls] = enc.pos()
            enc.alu_rr("cmp", RCX, cnt)
            enc.jcc("ge", Ld)
            enc.mov_rm(RDX, bp, RCX, 3, 0)       # [bp + RCX*8]
            enc.movq_xr(1, RDX)
            enc.addsd(0, 1)
            enc.movq_rx(ACC, 0)
            enc.alu_ri("add", RCX, 1)
            enc.jmp(Ls)
            enc.labels[Ld] = enc.pos()
            self.commit(dst, ACC)
            return
        if op == "vdotd":
            # f64 点积（v1.60）：movupd 非对齐读两路 + mulpd + addpd 两路累加
            # + 标量尾（mulsd/addsd）。结构与 vsumd 同构；多一个 baseB：
            # R11=baseA、R10=baseB、R8=count（push/pop 保护——R8 非池寄存器，
            # 序列内无调用，按 cpuid 族纪律显式保护）、RCX=下标、RDX=临时。
            # xmm0=累加器、xmm1/xmm2=两路加载。
            _, dst, base_a, base_b, count = ins
            seq = getattr(self, "_vdotd_seq", 0)
            self._vdotd_seq = seq + 1
            Lv, Lt, Ls, Ld = (f"__vdotd.v{seq}", f"__vdotd.t{seq}",
                              f"__vdotd.s{seq}", f"__vdotd.d{seq}")
            bpa = self.mat(SCRATCH, base_a)
            bpb = self.mat(SCRATCH2, base_b)
            enc.push(R8)
            cnt = self.mat(R8, count)
            enc.mov_ri(RCX, 0)
            enc.pxor_x(0, 0)
            enc.labels[Lv] = enc.pos()
            enc.lea(RDX, RCX, 2)
            enc.alu_rr("cmp", RDX, cnt)
            enc.jcc("g", Lt)
            enc.movupd_rm(1, bpa, RCX, 3, 0)
            enc.movupd_rm(2, bpb, RCX, 3, 0)
            enc.mulpd(1, 2)
            enc.addpd(0, 1)
            enc.alu_ri("add", RCX, 2)
            enc.jmp(Lv)
            enc.labels[Lt] = enc.pos()
            enc.movhlps(1, 0)
            enc.addsd(0, 1)
            enc.movq_rx(ACC, 0)
            enc.labels[Ls] = enc.pos()
            enc.alu_rr("cmp", RCX, cnt)
            enc.jcc("ge", Ld)
            enc.mov_rm(RDX, bpa, RCX, 3, 0)
            enc.movq_xr(1, RDX)
            enc.mov_rm(RDX, bpb, RCX, 3, 0)
            enc.movq_xr(2, RDX)
            enc.mulsd(1, 2)
            enc.addsd(0, 1)
            enc.movq_rx(ACC, 0)
            enc.alu_ri("add", RCX, 1)
            enc.jmp(Ls)
            enc.labels[Ld] = enc.pos()
            enc.pop(R8)
            self.commit(dst, ACC)
            return
        if op == "vdot":
            # int 点积（v1.85）：SSE2 两路 + 3×pmuludq 拼 64x64->低64 + paddq。
            #
            # 为什么不是一条指令：x86 没有 64 位整数 SIMD 乘法（pmulld 是
            # 32x32 低位、pmuldq 只算偶数 32 位通道且截断到 32 位输入，
            # vpmullq 要 AVX-512DQ）。所以按 a*b = a_lo*b_lo +
            # ((a_lo*b_hi + a_hi*b_lo) << 32) 拆成三次无符号 32x32->64：
            # 低 64 位与有无符号无关，逐位等价于标量 imul。
            #
            # 寄存器：R11=baseA、R10=baseB（SCRATCH，不在分配池）、
            # R8=count（push/pop）、R9=尾部乘数（push/pop）、RCX=下标、
            # RDX=临时；xmm0=累加器、xmm1/2=两路加载、xmm3/4/5=中间量。
            _, dst, base_a, base_b, count = ins
            seq = getattr(self, "_vdot_seq", 0)
            self._vdot_seq = seq + 1
            Lv, Lt, Ls, Ld = (f"__vdot.v{seq}", f"__vdot.t{seq}",
                              f"__vdot.s{seq}", f"__vdot.d{seq}")
            bpa = self.mat(SCRATCH, base_a)
            bpb = self.mat(SCRATCH2, base_b)
            enc.push(R8)
            enc.push(R9)
            cnt = self.mat(R8, count)
            enc.mov_ri(RCX, 0)
            enc.pxor_x(0, 0)
            enc.labels[Lv] = enc.pos()
            enc.lea(RDX, RCX, 2)
            enc.alu_rr("cmp", RDX, cnt)
            enc.jcc("g", Lt)
            enc.movdqu_rm(1, bpa, RCX, 3, 0)     # xmm1 = A[i], A[i+1]
            enc.movdqu_rm(2, bpb, RCX, 3, 0)     # xmm2 = B[i], B[i+1]
            # 高 32 位用 pshufd 取（Haswell 上 pshufd 走 p5，psrlq/psllq 走 p0；
            # 三个 pmuludq 已占满 p0 的 3 拍，再用 psrlq 取高位就把这段变成
            # p0 单口串行 —— 实测 3 拍/元素 vs 下面的 2 拍/元素）。
            enc.pshufd(3, 1, 0xF5)               # xmm3 = A 每通道高 32 位（d0<-d1, d2<-d3）
            enc.pshufd(4, 2, 0xF5)               # xmm4 = B 每通道高 32 位
            enc.movdqa_rr(5, 1)
            enc.pmuludq(5, 4)                    # xmm5 = a_lo*b_hi
            enc.pmuludq(1, 2)                    # xmm1 = a_lo*b_lo
            enc.pmuludq(3, 2)                    # xmm3 = a_hi*b_lo
            enc.paddq(3, 5)                      # 交叉项相加（高 32 位溢出部分本就该丢）
            enc.psllq_i(3, 32)
            enc.paddq(3, 1)                      # + a_lo*b_lo = 64 位乘积低位
            enc.paddq(0, 3)                      # 累加（64 位回绕）
            enc.alu_ri("add", RCX, 2)
            enc.jmp(Lv)
            enc.labels[Lt] = enc.pos()
            enc.movq_rx(ACC, 0)
            enc.psrldq(0, 8)
            enc.movq_rx(RDX, 0)
            enc.alu_rr("add", ACC, RDX)          # 两通道水平相加
            enc.labels[Ls] = enc.pos()
            enc.alu_rr("cmp", RCX, cnt)
            enc.jcc("ge", Ld)
            enc.mov_rm(RDX, bpa, RCX, 3, 0)
            enc.mov_rm(R9, bpb, RCX, 3, 0)
            enc.imul_rr(RDX, R9)
            enc.alu_rr("add", ACC, RDX)
            enc.alu_ri("add", RCX, 1)
            enc.jmp(Ls)
            enc.labels[Ld] = enc.pos()
            enc.pop(R9)
            enc.pop(R8)
            self.commit(dst, ACC)
            return
        if op in ("psrlw_i", "psllw_i", "psrlq_i", "psllq_i", "pslldq_i", "psrldq_i"):
            # 单槽 + imm8：xmm 槽是负数编码，立即数原样
            _, x, imm = ins
            getattr(enc, op)(-int(x) - 1, imm)
            return
        if op in ("xmm_mov", "pand_x", "por_x", "pshufb_x", "pclmul_x"):
            _, d, s = ins[:3]
            d, s = -int(d) - 1, -int(s) - 1
            if op == "xmm_mov":
                enc.movdqa_rr(d, s)
            elif op == "pand_x":
                enc.pand(d, s)
            elif op == "por_x":
                enc.por(d, s)
            elif op == "pshufb_x":
                enc.pshufb(d, s)
            else:
                enc.pclmulqdq(d, s, ins[3])
            return
        if op in ("xmm_ld", "xmm_st", "sha_nexte", "sha_rnds2", "sha_msg1",
                  "sha_msg2", "xmm_paddd", "xmm_pxor", "xmm_pshufd",
                  "xmm_palignr", "aesenc", "aesenclast", "aesdec",
                  "aesdeclast", "aesimc", "aeskeygenassist"):
            # SHA-NI / XMM 族（v1.15）：操作数是 xmm 槽号 imm（0-7），
            # 地址实参是 vreg（经 mat 映射）。固定槽协议（STATE0=XMM0 等）
            # 由库层维护——寄存器分配器完全不参与 xmm 的管理。
            if op == "xmm_ld":
                # ⚠ 第 3 个参数是 SIB 的 index：**必须传 4（RSP）** 表示"无索引"。
                # 传 0 会被编码成 [base + RAX*1]——v1.15 写的 xmm_* 从来没有
                # .qma 调用过，这个错编码一直没暴露（v1.31 用 AES-NI 时才炸）。
                _, x, addr = ins
                enc.movdqu_rm(-int(x) - 1, self.mat(SCRATCH, addr), 4, 0, 0)
                return
            if op == "xmm_st":
                _, addr, x = ins
                enc.movdqu_mr(self.mat(SCRATCH, addr), 4, 0, 0, -int(x) - 1)
                return
            _, d, s = ins[:3]
            d, s = -int(d) - 1, -int(s) - 1   # 负数编码 -(x+1) -> 槽号 x
            if op == "sha_nexte":
                enc.sha256nexte(d, s)
            elif op == "sha_rnds2":
                enc.sha256rnds2(d, s)
            elif op == "sha_msg1":
                enc.sha256msg1(d, s)
            elif op == "sha_msg2":
                enc.sha256msg2(d, s)
            elif op == "xmm_paddd":
                enc.paddd(d, s)
            elif op == "xmm_pxor":
                enc.pxor_x(d, s)
            elif op == "xmm_pshufd":
                enc.pshufd(d, s, ins[3])
            elif op == "xmm_palignr":
                enc.palignr(d, s, ins[3])
            elif op == "aesenc":
                enc.aesenc(d, s)
            elif op == "aesenclast":
                enc.aesenclast(d, s)
            elif op == "aesdec":
                enc.aesdec(d, s)
            elif op == "aesdeclast":
                enc.aesdeclast(d, s)
            elif op == "aesimc":
                enc.aesimc(d, s)
            elif op == "aeskeygenassist":
                enc.aeskeygenassist(d, s, ins[3])
            return
        if op == "vsum":
            # SSE2 两路（paddq）+ 标量尾。4 路要 AVX2，见 docs/PERF.md。
            _, dst, base, count = ins
            seq = getattr(self, "_vsum_seq", 0)
            self._vsum_seq = seq + 1
            Lv, Lt, Ls, Ld = (f"__vsum.v{seq}", f"__vsum.t{seq}",
                              f"__vsum.s{seq}", f"__vsum.d{seq}")
            bp = self.mat(SCRATCH, base)
            cnt = self.mat(SCRATCH2, count)
            enc.mov_ri(RCX, 0)
            enc.pxor_x(0, 0)
            enc.labels[Lv] = enc.pos()
            enc.lea(RDX, RCX, 2)
            enc.alu_rr("cmp", RDX, cnt)
            enc.jcc("g", Lt)
            enc.movdqu_rm(1, bp, RCX, 3, 0)
            enc.paddq(0, 1)
            enc.alu_ri("add", RCX, 2)
            enc.jmp(Lv)
            enc.labels[Lt] = enc.pos()
            enc.movq_rx(ACC, 0)
            enc.psrldq(0, 8)
            enc.movq_rx(RDX, 0)
            enc.alu_rr("add", ACC, RDX)
            enc.labels[Ls] = enc.pos()
            enc.alu_rr("cmp", RCX, cnt)
            enc.jcc("ge", Ld)
            enc.mov_rm(RDX, bp, RCX, 3, 0)
            enc.alu_rr("add", ACC, RDX)
            enc.alu_ri("add", RCX, 1)
            enc.jmp(Ls)
            enc.labels[Ld] = enc.pos()
            self.commit(dst, ACC)
        elif op == "trunc":
            _, dst, a, bits, signed = ins
            r = self.mat(SCRATCH2, a)
            enc.trunc_reg(r, bits, signed)
            self.commit(dst, r)
        elif op == "label":
            enc.labels[ins[1]] = enc.pos()
        elif op == "jmp":
            enc.jmp(ins[1])
        elif op in ("jz", "jnz"):
            r = self.fetch(SCRATCH, ins[1])
            enc.test_rr(r, r)
            bcc = "e" if op == "jz" else "ne"
            boff = enc.pos()
            enc.jcc(bcc, ins[2])
            self._dbg_branch(boff, ins[2], bcc)
        elif op == "jcc":
            cc, a, b, lbl = ins[1], ins[2], ins[3], ins[4]
            ra = self.fetch(SCRATCH2, a)
            if isinstance(b, tuple) and b[0] == "imm" and -2**31 <= b[1] < 2**31:
                enc.alu_ri("cmp", ra, b[1])
            else:
                rb = self.fetch(SCRATCH, b)
                enc.alu_rr("cmp", ra, rb)
            boff = enc.pos()
            enc.jcc(cc, lbl)
            self._dbg_branch(boff, lbl, cc)
        elif op == "mov":
            self.parallel_move([(self.src_move(ins[2]), self.dst_move(ins[1]))])
        elif op == "bin":
            self.gen_bin(ins)
        elif op in ("neg", "not"):
            rd = self.safe_dst_reg(ins[1], [ins[2]])
            if rd is not None:
                ra = self.fetch(rd, ins[2])
                if ra != rd:
                    enc.mov_rr(rd, ra)
                if op == "neg":
                    enc.neg(rd)
                else:
                    enc.alu_ri("xor", rd, -1)
                return
            ra = self.mat(SCRATCH2, ins[2])
            if op == "neg":
                enc.neg(ra)
            else:
                enc.alu_ri("xor", ra, -1)
            self.commit(ins[1], ra)
        elif op == "fbin":
            w, fop, dst, a, b = ins[1], ins[2], ins[3], ins[4], ins[5]
            if w == "f64":
                # v2.65：f64 值直接住 XMM。**尽量少搬**：
                #   · b 已经在 XMM 里 → 直接用它的寄存器当源，不拷到 scratch
                #   · dst 有自己的 XMM 家 → 结果直接算进去（1 条 movaps + 1 条运算）
                # 以前是「两个操作数各拷到 scratch + 算 + 再拷回 dst」= 4 条。
                ka = self.alloc[a] if isinstance(a, int) else None
                kb = self.alloc[b] if isinstance(b, int) else None
                xa = ka[1] if (ka is not None and ka[0] == "x") else None
                xb = kb[1] if (kb is not None and kb[0] == "x") else None
                if xb is None:
                    xb = self.fx(XS1, b)
                kd = self.alloc[dst]
                if kd[0] == "x":
                    d = kd[1]
                    if d == xa:
                        enc.fp_alu(w, fop, d, xb)          # 已与 a 合并
                    elif d != xb:
                        if xa is None:
                            self.fx(d, a)                  # 直接拷进 dst 的家
                        else:
                            enc.movaps_rr(d, xa)
                        enc.fp_alu(w, fop, d, xb)
                    else:
                        # d == xb：b 的值还要用，不能就地写
                        xa = self.fx(XS0, a)
                        enc.fp_alu(w, fop, xa, xb)
                        enc.movaps_rr(d, xa)
                else:
                    xa = self.fx(XS0, a)
                    enc.fp_alu(w, fop, xa, xb)
                    self.fcommit(dst, xa)
            else:
                self.fp_from_gpr(w, XS0, self.mat(SCRATCH2, a))
                self.fp_from_gpr(w, XS1, self.mat(SCRATCH, b))
                enc.fp_alu(w, fop, XS0, XS1)
                self.fp_to_dst(w, dst, XS0)
        elif op == "fneg":
            w, dst, a = ins[1], ins[2], ins[3]
            self.fx(XS0, a)
            enc.mov_ri(SCRATCH, 0x8000000000000000 if w == "f64" else 0x80000000)
            self.fp_from_gpr(w, XS1, SCRATCH)
            enc.fp_xor(w, XS0, XS1)
            if w == "f64":
                self.fcommit(dst, XS0)
            else:
                self.fp_to_dst(w, dst, XS0)
        elif op == "fcmpset":
            w, cc, dst, a, b = ins[1], ins[2], ins[3], ins[4], ins[5]
            if w == "f64":
                self.fx(XS0, a)
                self.fx(XS1, b)
            else:
                self.fp_from_gpr(w, XS0, self.mat(SCRATCH2, a))
                self.fp_from_gpr(w, XS1, self.mat(SCRATCH, b))
            enc.fp_cmp(w, XS0, XS1)
            # 有序语义与 C 一致：NaN 时 PF=1，比较结果必须为假（!= 为真）
            if cc == "ne":
                enc.setcc("p", SCRATCH)
                enc.setcc("ne", ACC)
                enc.movzx_r_r8(SCRATCH, SCRATCH)
                enc.movzx_r_r8(ACC, ACC)
                enc.alu_rr("or", ACC, SCRATCH)
            else:
                # comis* 按无符号语义置 CF/ZF：l/le/g/ge 必须用 setb/setbe/seta/setae
                ucc = {"e": "e", "ne": "ne", "l": "b", "le": "be",
                       "g": "a", "ge": "ae"}[cc]
                enc.setcc("np", SCRATCH)
                enc.setcc(ucc, ACC)
                enc.movzx_r_r8(SCRATCH, SCRATCH)
                enc.movzx_r_r8(ACC, ACC)
                enc.alu_rr("and", ACC, SCRATCH)
            self.commit(dst, ACC)
        elif op == "fcvt":
            kind, dst, a = ins[1], ins[2], ins[3]
            if kind == "i2f64":
                # cvtsi2sd 的源是 GPR。**先 pxor 再 cvt**：SSE2 形式的
                # cvtsi2sd 只写低 64 位、高 64 位保留 ⇒ 对目的寄存器有
                # 假依赖，会把循环里的每一轮除法串行化（b2_float 实测）。
                r = self.mat(SCRATCH2, a)
                kd = self.alloc[dst]
                if kd[0] == "x":
                    enc.pxor_rr(kd[1], kd[1])
                    enc.cvt(kind, kd[1], r)
                else:
                    enc.pxor_rr(XS0, XS0)
                    enc.cvt(kind, XS0, r)
                    self.fcommit(dst, XS0)
                return
            if kind == "f64i":
                self.fx(XS0, a)
                enc.cvt(kind, ACC, XS0)
                self.commit(dst, ACC)
                return
            if kind == "f32f64":
                self.fp_from_gpr("f32", XS0, self.mat(SCRATCH2, a))
                enc.cvt(kind, XS0, XS0)
                self.fcommit(dst, XS0)
                return
            if kind == "f64f32":
                self.fx(XS0, a)
                enc.cvt(kind, XS0, XS0)
                self.fp_to_dst("f32", dst, XS0)      # f32 仍住 GPR
                return
            if kind == "i2f32":
                enc.cvt(kind, XS0, self.mat(SCRATCH2, a))
                self.fp_to_dst("f32", dst, XS0)
                return
            if kind == "f32i":
                self.fp_from_gpr("f32", XS0, self.mat(SCRATCH2, a))
                enc.cvt(kind, ACC, XS0)
                self.commit(dst, ACC)
                return
            raise SyntaxError(f"未知浮点转换 {kind}")
        elif op == "cmpset":
            cc, dst, a, b = ins[1], ins[2], ins[3], ins[4]
            rd = self.safe_dst_reg(dst, [a, b])
            host = rd if rd is not None else SCRATCH2
            ra = self.fetch(host, a)
            if ra != host:
                enc.mov_rr(host, ra)
            if isinstance(b, tuple) and b[0] == "imm" and -2**31 <= b[1] < 2**31:
                enc.alu_ri("cmp", host, b[1])
            else:
                rb = self.fetch(SCRATCH, b)
                enc.alu_rr("cmp", host, rb)
            if rd is not None:
                enc.setcc(cc, rd)                  # 直接写进 dst 的字节寄存器
                enc.movzx_r_r8(rd, rd)
                return
            enc.setcc(cc, RAX)
            enc.movzx_r_r8(ACC, RAX)
            self.commit(dst, ACC)
        elif op == "call":
            nk = self._emit_call_args(ins[3])
            enc.call(ins[2])
            if nk:
                enc.alu_ri("add", RSP, 8 * nk)     # 回卷溢出区（v1.42）
            if ins[1] is not None:
                self.commit_ret(ins[1])
        elif op == "callr":
            # 间接调用（自研 ABI，与 call 同参数布局）。函数地址先物化进
            # SCRATCH2（r10 不在分配池，不会被随后的参数搬移覆盖；
            # fnaddr/ga 操作数在此走 movabs + 回填，PE 下生成 DIR64 重定位）。
            # 栈传参（v1.42）：第 7 参起落调用方溢出区；r10 全程无人碰
            # （栈区存取走 SCRATCH，参数搬移只写 ARG_REGS）。
            freg = self.mat(SCRATCH2, ins[2])
            nk = self._emit_call_args(ins[3])
            enc.call_reg(SCRATCH2)
            if nk:
                enc.alu_ri("add", RSP, 8 * nk)     # 回卷溢出区（v1.42）
            if ins[1] is not None:
                self.commit_ret(ins[1])
        elif op == "cssub":
            # dst = (a >= b) ? a - b : a。妙点：借位就在 sub 的标志位里——
            #   host = a ; rax = a - b（SF = (a-b) < 0） ; CMOVns host, rax
            # 不需要 setcc/movzx/test 物化布尔值（sel 版曾因此白吃 ~4 周期）。
            a, b = ins[2], ins[3]
            rd = self.safe_dst_reg(ins[1], [a, b])
            host = rd if rd is not None else SCRATCH2
            ra = self.fetch(host, a)
            if ra != host:
                self.enc.mov_rr(host, ra)      # host = a
            self.enc.mov_rr(ACC, host)         # rax = a
            if isinstance(b, tuple) and b[0] == "imm" and -2**31 <= b[1] < 2**31:
                self.enc.alu_ri("sub", ACC, b[1])      # rax -= imm32（置 SF）
            else:
                rb = self.fetch(SCRATCH, b)
                self.enc.alu_rr("sub", ACC, rb)        # rax -= b（置 SF）
            self.enc.cmov("ns", host, ACC)      # a-b >= 0（SF=0）-> 采纳
            if rd is None:
                self.commit(ins[1], SCRATCH2)
        elif op == "ret":
            if ins[1] is not None:
                if isinstance(ins[1], int) and ins[1] in self.f64v:
                    # f64 走 XMM 文件，返回仍按 ABI 放 RAX（位模式）
                    self.fx(XS0, ins[1])
                    enc.movq_rx(ACC, XS0)
                else:
                    r = self.fetch(ACC, ins[1])
                    if r != ACC:
                        enc.mov_rr(ACC, r)
            self.emit_epilogue()
            enc.ret()
        elif op in ("load", "load8", "load32"):
            # v2.70：**常量下标直接用位移**。以前是
            #   mov r11, 1 ; mov r15, [r14 + r11*8]
            # —— 每条带常量下标的访问都白付一条 `mov`。vec 句柄的
            # data/len/cap、结构体字段全是常量下标，命中率很高。
            ci = None
            if isinstance(ins[3], tuple) and ins[3][0] == "imm":
                scale0 = 3 if op == "load" else 0
                d0 = ins[3][1] << scale0
                if -2 ** 27 <= d0 < 2 ** 27:
                    ci = d0
            if op == "load" and isinstance(ins[1], int) and ins[1] in self.f64v:
                fb = self.fetch(SCRATCH2, ins[2])
                if ci is None:
                    fi = self.fetch(SCRATCH, ins[3])
                    enc.movsd_xm(XS0, fb, fi, 3, 0)
                else:
                    enc.movsd_xm(XS0, fb, 4, 0, ci)
                self.fcommit(ins[1], XS0)
                return
            rd = self.safe_dst_reg(ins[1], [ins[2], ins[3]])
            fb = self.fetch(SCRATCH2, ins[2])
            target = rd if rd is not None else ACC
            if ci is not None:
                if op == "load":
                    enc.mov_rm(target, fb, 4, 0, ci)
                elif op == "load32":
                    enc.mov32_rm(target, fb, 4, 0, ci)
                else:
                    enc.movzx8_rm(target, fb, 4, 0, ci)
            else:
                fi = self.fetch(SCRATCH, ins[3])
                if op == "load":
                    enc.mov_rm(target, fb, fi, 3, 0)
                elif op == "load32":
                    # 字节偏移寻址（同 load8）：scale 0——不是 load64 的槽索引
                    enc.mov32_rm(target, fb, fi, 0, 0)
                else:
                    enc.movzx8_rm(target, fb, fi, 0, 0)
            if rd is None:
                self.commit(ins[1], ACC)
        elif op in ("store", "store8"):
            # v2.70：常量下标直接用位移（同 load）
            ci = None
            if isinstance(ins[2], tuple) and ins[2][0] == "imm":
                scale0 = 3 if op == "store" else 0
                d0 = ins[2][1] << scale0
                if -2 ** 27 <= d0 < 2 ** 27:
                    ci = d0
            fb = self.fetch(SCRATCH2, ins[1])
            if op == "store" and isinstance(ins[3], int) and ins[3] in self.f64v:
                self.fx(XS0, ins[3])
                if ci is None:
                    fi = self.fetch(SCRATCH, ins[2])
                    enc.movsd_mx(fb, fi, 3, 0, XS0)
                else:
                    enc.movsd_mx(fb, 4, 0, ci, XS0)
                return
            fs = self.fetch(ACC, ins[3])
            if ci is not None:
                if op == "store":
                    enc.mov_mr(fb, 4, 0, ci, fs)
                else:
                    enc.mov8_mr(fb, 4, 0, ci, fs)
            else:
                fi = self.fetch(SCRATCH, ins[2])
                if op == "store":
                    enc.mov_mr(fb, fi, 3, 0, fs)
                else:
                    enc.mov8_mr(fb, fi, 0, 0, fs)
        elif op == "movaddr":
            kind, val = self.alloc[ins[1]]
            target = val if kind == "r" else SCRATCH
            self.enc.emit(rex(w=1, b=target), bytes([0xB8 + (target & 7)]))
            self.global_fixups.append((self.enc.pos(), ins[2]))
            self.enc.emit(b"\x00" * 8)
            if kind == "m":
                self.enc.mov_mr(RBP, 4, 0, -val, SCRATCH)
        elif op == "frameaddr":
            # dst = &帧上结构体区[word]。
            # 关键：结构体区整体位于溢出槽之下，且【字序号递增 == 地址递增】，
            # 与 load/store 的 [base + idx*8] 寻址方向保持一致。
            # 否则字段会反向错位，首结构体的高位字段甚至写穿到保存的 rbp/返回地址。
            kind, val = self.alloc[ins[1]]
            target = val if kind == "r" else SCRATCH
            disp = -8 * (self.nslots + self.frame_words) + 8 * ins[2]
            self.enc.lea(target, RBP, disp)
            if kind == "m":
                self.enc.mov_mr(RBP, 4, 0, -val, SCRATCH)
        elif op == "xchg":
            # dst = *addr（旧值）；*addr = val（原子，x86 内存 xchg 隐含 LOCK）
            dst, addr, val = ins[1], ins[2], ins[3]
            ra = self.fetch(SCRATCH2, addr)
            rv = self.fetch(ACC, val)
            if rv != ACC:
                self.enc.mov_rr(ACC, rv)
            self.enc.xchg_mr(ra, 4, 0, 0, ACC)
            if dst is not None:
                self.commit(dst, ACC)
        elif op == "atomic":
            # ('atomic', sub, dst, addr, a[, b])（v1.10）：
            #   add -> dst = 旧值；*addr += a          （lock xadd）
            #   cas -> dst = 旧值；*addr==a 时 *addr=b （lock cmpxchg，期望走 RAX）
            # 登记纪律：_EFF（调度器不可跨越）+ vreg_mentions + _map_ins 三处已同步。
            sub, dst, addr = ins[1], ins[2], ins[3]
            ra = self.fetch(SCRATCH2, addr)
            if sub == "add":
                rv = self.fetch(ACC, ins[4])
                if rv != ACC:
                    self.enc.mov_rr(ACC, rv)
                self.enc.xadd_mr(ra, 4, 0, 0, ACC)
                if dst is not None:
                    self.commit(dst, ACC)
            elif sub == "cas":
                re = self.fetch(ACC, ins[4])
                if re != ACC:
                    self.enc.mov_rr(ACC, re)
                rn = self.fetch(SCRATCH, ins[5])
                self.enc.cmpxchg_mr(ra, 4, 0, 0, rn)
                if dst is not None:
                    self.commit(dst, ACC)     # RAX = 内存旧值（ZF 指示是否交换）
            else:
                raise SyntaxError(f"atomic 未知子操作 {sub}")
        elif op == "ldar":
            # acquire 读：x86 TSO 下读不会被提前，普通 mov 就是 acquire
            # （v1.98）——所以这里与 load 同形，零额外指令。
            ra = self.fetch(SCRATCH2, ins[2])
            self.enc.mov_rm(ACC, ra, 4, 0, 0)
            self.commit(ins[1], ACC)
        elif op == "stlr":
            # release 写：x86 TSO 下写不会被推后，普通 mov 就是 release。
            ra = self.fetch(SCRATCH2, ins[1])
            rv = self.fetch(ACC, ins[2])
            self.enc.mov_mr(ra, 4, 0, 0, rv)
        elif op == "mfence":
            self.enc.mfence()
        elif op == "pause":
            self.enc.pause()
        elif op == "rdtsc":
            # dst = EDX:EAX（64 位 TSC）。纯读不进 _EFF：调度器挪它
            # 只影响测量精度，不影响正确性（调用方读两次取差）。
            self.enc.rdtsc()
            rd = self.safe_dst_reg(ins[1])
            if rd is None:
                self.enc.mov_rr(SCRATCH2, 0)     # lo
                self.enc.shl_i(2, 32)            # rdx = hi << 32
                self.enc.alu_rr("or", SCRATCH2, 2)
                self.commit(ins[1], SCRATCH2)
            else:
                if rd != 0:
                    self.enc.mov_rr(rd, 0)       # rd = lo
                self.enc.shl_i(2, 32)            # rdx = hi << 32
                self.enc.alu_rr("or", rd, 2)     # rd |= hi（rdx 已不在池）
                self.commit(ins[1], rd)
        elif op == "spawn_child":
            # 子线程起始点（clone 返回 0 后跳到这里）：
            # 参数块指针由父线程写在【新栈顶 - 8】，这里直接用 rsp 取，
            # 不经过任何 vreg/父栈溢出槽，避免与并发执行的父线程抢槽位。
            enc.mov_rm(RDI, RSP, 4, 0, -8)
            enc.call(ins[1])
            enc.mov_ri(RDI, 0)
            enc.mov_ri(ACC, 60)          # exit(0)
            enc.syscall()
        elif op == "syscall":
            dst, num, args = ins[1], ins[2], ins[3]
            fixed = [RDI, RSI, RDX, R10, R8, R9]
            moves = [(self.src_move(a), ("r", fixed[i])) for i, a in enumerate(args) if i < 6]
            self.parallel_move(moves)
            enc.mov_ri(ACC, num)
            enc.syscall()
            if dst is not None:
                self.commit(dst, ACC)
        elif op == "args":
            moves = []
            for i, d in enumerate(ins[1]):
                if i < 6:
                    moves.append((("r", ARG_REGS[i]), self.dst_move(d)))
                else:
                    # 第 7+ 参从调用方溢出区读（v1.42）：[rbp+16+8j]，
                    # 与 _emit_call_args 的调用点布局逐字节对应
                    moves.append((("stk", i - 6), self.dst_move(d)))
            self.parallel_move(moves)
        else:
            raise SyntaxError(f"无法发射指令 {ins!r}")

    def _plan_mul_chain(self, chain, dst, src):
        """给 LEA 链预先分配寄存器；分配不出来返回 None（调用方回退 imul）。

        先规划后发射：保证要么整条链发完，要么一条都不发，
        避免「发到一半寄存器不够、dst 已被污染」的半成品。
        """
        last_use = {}
        for i, (p, q, _s, _nv) in enumerate(chain):
            last_use[p] = i
            last_use[q] = i
        reg_of = {1: src}
        temps = [SCRATCH, SCRATCH2]
        plan = []
        for i, (p, q, s, nv) in enumerate(chain):
            if p not in reg_of or q not in reg_of:
                return None
            if i == len(chain) - 1:
                target = dst
            else:
                target = None
                for r in temps:
                    held = [v for v, rr in reg_of.items() if rr == r]
                    if not held or all(last_use.get(v, -1) <= i for v in held):
                        target = r
                        break
                if target is None:
                    return None
            plan.append((target, reg_of[p], reg_of[q], s))
            for v in [v for v, rr in reg_of.items() if rr == target]:
                del reg_of[v]
            reg_of[nv] = target
        return plan

    def mul_const(self, dst, src, c):
        """dst = src * c：小常量用 LEA/移位链，比 imul 少 2 周期延迟"""
        enc = self.enc
        if c == 0:
            enc.mov_ri(dst, 0)
            return
        if c == 1:
            if dst != src:
                enc.mov_rr(dst, src)
            return
        if c < 0:
            self.mul_const(dst, src, -c)
            enc.neg(dst)
            return
        if c & (c - 1) == 0:                       # 2^k -> shl
            if dst != src:
                enc.mov_rr(dst, src)
            enc.shl_i(dst, c.bit_length() - 1)
            return
        chain = const_mul_chain(c)
        plan = self._plan_mul_chain(chain, dst, src) if chain else None
        if plan is None:
            # 合格魔数找不到：安全回退 imul。
            # 大常量（如 map 哈希用的 splitmix64 / FNV 素数，>= 2^40）走这里：
            # 先把常量物化进 SCRATCH 再 imul（历史 bug：直接 imul_rr(dst, src)
            # 算成了 src*src，大常量乘法会静默算错）。
            if dst != src:
                enc.mov_rr(dst, src)
            enc.mov_ri(SCRATCH, c)
            enc.imul_rr(dst, SCRATCH)
            return
        for (t, pb, qi, sc) in plan:
            enc.lea3(t, pb, qi, sc)

    def gen_bin(self, ins):
        enc = self.enc
        _, kind, dst, a, b = ins
        rd = self.safe_dst_reg(dst, [a, b])
        alu_ops = ("add", "sub", "and", "or", "xor", "mul", "shl", "shr", "sar")

        # ---- 就地（二地址）路径：运算直接做在 dst 的寄存器里 ----
        # 老路径是 mat(scratch) -> op -> commit(dst) 三次搬运；
        # 常见的 `x = x + 1` 因此变成 3 条指令，而实际只需要 1 条。
        if rd is not None and kind in alu_ops:
            src_a, src_b = a, b
            # 交换律允许把能就地的那一侧换到前面，再省掉一次搬运
            if kind in ("add", "and", "or", "xor", "mul") and isinstance(b, int) \
                    and not isinstance(a, int):
                src_a, src_b = b, a
            # 先看 a 是否已经在寄存器里（不搬运）。
            # ⚠ 这里必须区分 ("r", 寄存器号) 与 ("m", 栈偏移)：两者都是小整数，
            # 直接比较会把 [rbp-8] 的 8 当成 R8，于是"a 已在 dst 寄存器里"的
            # 判断误判为真、跳过 fetch，运算吃到上一条指令的残值。
            # 这正是 b1/b3 两个误编译的根因（循环里 dst 恰好分到同一个寄存器号）。
            if isinstance(src_a, int):
                _k, a_val = self.alloc.get(src_a, ("m", 0))
                a_reg = a_val if _k == "r" else None
            else:
                a_reg = None
            # 常量乘法：结果直接写进 dst，不必先把 a 搬进 dst
            if kind == "mul" and isinstance(src_b, tuple) and src_b[0] == "imm":
                if a_reg is None:
                    a_reg = self.fetch(rd, src_a)
                self.mul_const(rd, a_reg, src_b[1])
                return
            if a_reg is None or a_reg != rd:
                ra = self.fetch(rd, src_a)
                if ra != rd:
                    enc.mov_rr(rd, ra)
            if kind == "mul":
                enc.imul_rr(rd, self.fetch(SCRATCH, src_b))
                return
            if kind in ("shl", "shr", "sar"):
                if isinstance(src_b, tuple) and src_b[0] == "imm":
                    if kind == "shl":
                        enc.shl_i(rd, src_b[1])
                    elif kind == "shr":
                        enc.emit(rex(w=1, b=rd), b"\xc1", modrm_reg(5, rd),
                                 bytes([src_b[1] & 0xFF]))
                    else:
                        enc.sar_i(rd, src_b[1])
                    return
                rb = self.fetch(RCX, src_b)     # 移位计数必须在 CL
                if rb != RCX:
                    enc.mov_rr(RCX, rb)
                enc.shift_cl(rd, kind)
                return
            if isinstance(src_b, tuple) and src_b[0] == "imm" and -2**31 <= src_b[1] < 2**31:
                enc.alu_ri(kind, rd, src_b[1])
            else:
                enc.alu_rr(kind, rd, self.fetch(SCRATCH, src_b))
            return

        # ---- 保守路径（dst 在栈上 / 特殊运算）----
        if kind in ("add", "sub", "and", "or", "xor"):
            ra = self.mat(SCRATCH2, a)
            if isinstance(b, tuple) and b[0] == "imm" and -2**31 <= b[1] < 2**31:
                enc.alu_ri(kind, ra, b[1])
            else:
                rb = self.fetch(SCRATCH, b)
                enc.alu_rr(kind, ra, rb)
            self.commit(dst, ra)
            return
        if kind == "mul":
            if isinstance(b, tuple) and b[0] == "imm" and rd is None:
                ra = self.mat(SCRATCH2, a)
                self.mul_const(SCRATCH2, ra, b[1])
                self.commit(dst, SCRATCH2)
                return
            ra = self.mat(SCRATCH2, a)
            rb = self.fetch(SCRATCH, b)
            enc.imul_rr(ra, rb)
            self.commit(dst, ra)
            return
        if kind in ("div", "mod"):
            ra = self.fetch(SCRATCH2, a)
            rb = self.fetch(SCRATCH, b)
            enc.mov_rr(ACC, ra)
            enc.cqo()
            enc.idiv(rb)
            self.commit(dst, ACC if kind == "div" else RDX)
            return
        if kind == "umulhi":
            ra = self.mat(ACC, a)          # rax = a
            rb = self.fetch(SCRATCH, b)
            enc.mul_u(rb)                  # rdx:rax = rax * rb
            self.commit(dst, RDX)
            return
        if kind in ("shl", "shr", "sar"):
            if isinstance(b, tuple) and b[0] == "imm":
                ra = self.mat(SCRATCH2, a)
                if kind == "shl":
                    enc.shl_i(ra, b[1])
                elif kind == "shr":
                    enc.emit(rex(w=1, b=ra), b"\xc1", modrm_reg(5, ra), bytes([b[1] & 0xFF]))
                else:
                    enc.sar_i(ra, b[1])
            else:
                self.mat(RCX, b)          # 移位计数必须在 CL
                ra = self.mat(SCRATCH2, a)
                enc.shift_cl(ra, kind)
            self.commit(dst, ra)
            return
        raise SyntaxError(f"未知二元运算 {kind}")

    def emit_epilogue(self):
        enc = self.enc
        for _i, _xr in enumerate(getattr(self, "used_xcallee", ())):
            enc.movups_xm(_xr, RBP, 4, 0, -self.xsave_base + 16 * _i)
        enc.mov_rr(RSP, RBP)
        enc.pop(RBP)
        for r in reversed(self.used_callee):
            enc.pop(r)
        if getattr(self, "cur_fn_thread", False):
            # 与 gen_functions 里的两次 push 对称（Windows 线程入口）
            enc.pop(RSI)
            enc.pop(RDI)

    # ---- 整体生成 ----
    def gen_entry(self):
        """Linux _start：保存 argc/argv -> 对齐栈 -> 调 main -> exit(返回值)"""
        enc = self.enc
        low = self.low
        if low is not None and getattr(low, "uses_args", False):
            # 内核在 [rsp] 放 argc、(rsp+8) 放 argv[]；必须在 and rsp,-16 之前取，
            # 且只能走 boot 函数把值落到全局字（入口处不能依赖被调用者保存寄存器）。
            enc.mov_rm(RDI, RSP, RSP, 0, 0)      # rdi = [rsp] = argc
            enc.lea(RSI, RSP, 8)                 # rsi = &argv[0]
            enc.call("__qlm_args_boot")
        enc.alu_ri("and", RSP, -16)
        enc.call("main")
        enc.mov_rr(RDI, RAX)
        enc.mov_ri(ACC, 60)
        enc.syscall()

    def gen_functions(self):
        enc = self.enc
        for fn in self.fns:
            self._dbg_reset(fn)
            ins_off = []
            self.f64v = f64_vregs(fn)
            self.cur_fn_name = fn.name
            (self.alloc, nslots, self.used_callee,
             self.used_xcallee) = allocate(fn, f64=self.f64v)
            self.nslots = nslots
            self.frame_words = getattr(fn, "frame_words", 0)
            enc.labels[fn.name] = enc.pos()
            # Win64 线程入口（ThreadProc）由 Windows 直接调用：
            # RDI/RSI 在 Windows ABI 里是 callee-saved，而我们的寄存器池会用到，
            # 所以额外 push/pop（两次 push 共 16 字节，不破坏 16 字节对齐）。
            self.cur_fn_thread = bool(getattr(fn, "win_thread", False))
            if self.cur_fn_thread:
                enc.push(RDI)
                enc.push(RSI)
            # 序言：push callee-saved -> push rbp -> mov rbp,rsp -> sub rsp,F
            for r in self.used_callee:
                enc.push(r)
            enc.push(RBP)
            enc.mov_rr(RBP, RSP)
            # v1.62 调试信息：序言在 rbp 之前压了 (used_callee + rbp [+线程
            # 入口的 RDI/RSI]) 个寄存器——返回地址在 [rbp + 8*(n+1)]，
            # 不在标准的 [rbp+8]。帧链（bt / next / finish 的深度）必须
            # 知道每个函数压了几个，否则从第一个调用帧就断链。
            self._dbg["push"] = (len(self.used_callee) + 1
                                 + (2 if self.cur_fn_thread else 0))
            rbp_mod = (8 - 8 * (len(self.used_callee) + 1)) % 16
            # XMM 保存区放在**帧的最底部**（比溢出槽与结构体区都低），
            # 每个非易失 XMM 占 16 字节（整 128 位，callee-saved 语义）。
            nx = len(self.used_xcallee)
            self.xsave_base = (nslots + self.frame_words) * 8 + 16 * nx
            frame = self.xsave_base
            while frame % 16 != rbp_mod:
                frame += 8
            if frame:
                enc.alu_ri("sub", RSP, frame)
                # §7.17（v2.19 修）：帧 > 4 KB 时 `sub rsp` 会**跳过** guard page，
                # Windows 不会自动扩栈，函数体第一次写帧就 AV（表现为"随机崩在
                # 某个 call / 某条 mov"）。这里逐页 touch 一遍，等价于 __chkstk
                # 的效果：每 4 KB 一条 `mov qword [rsp+off], 0`（帧是全新的，
                # 写 0 不会破坏任何已初始化数据）。
                if frame > 0x1000:
                    # 必须**从高往低**逐页 touch（和 __chkstk 一样）：先碰最靠近
                    # 旧 rsp 的那一页（它才是 guard page），Windows 才会把栈扩下来。
                    # 反过来从低往高，第一条就落在未提交页上，直接 AV。
                    off = frame - 0x1000
                    while off >= 0:
                        enc.emit(b"\x48\xc7\x84\x24",
                                 struct.pack("<I", off), b"\x00\x00\x00\x00")
                        off -= 0x1000
            for _i, _xr in enumerate(self.used_xcallee):
                enc.movups_mx(RBP, 4, 0, -self.xsave_base + 16 * _i, _xr)
            for ins in fn.instrs:
                ins_off.append(enc.pos())
                self.gen_instr(ins)
            self._dbg_finish(fn, ins_off)
            # 兜底返回
            self.emit_epilogue()
            enc.ret()

    def gen_vtables(self):
        """接口 vtable = 代码段里一张函数指针表（每槽 8 字节）。
        放在所有函数之后，用 code_fixups 回填方法地址（ELF/PE 都能处理）。"""
        enc = self.enc
        for (iname, tname), fnames in sorted(
                (getattr(self.low, "vtables", None) or {}).items()):
            enc.labels[f"__vt_{iname}__{tname}"] = enc.pos()
            for fname in fnames:
                self.code_fixups.append((enc.pos(), fname))
                enc.emit(b"\x00" * 8)

    def _dbg_resolve_branches(self):
        """v1.83：把分支表的标签解析成 .text 内偏移，并**只留源码级分支**。

        两条过滤规则（宁缺勿错——错的分支表会让覆盖率数字骗人）：

        1. 解析不到标签、或退化成自环的条目丢弃；
        2. 跳转目标必须是**语句入口**（行表里的某个偏移）。不是的话这条
           jcc 属于编译器生成的机械跳转，不是源码里的 if/while/match：
           `assert` 的失败块、定长数组越界检查的 panic 块、`args()` 展开的
           拷贝循环、`@simd` 的内联循环——它们算进分母只会让"分支覆盖率"
           变成编译器的体检报告，不是用户代码的。"""
        for f in self.dbg["funcs"]:
            entry = {off for off, _ln in f.get("lines", [])}
            out = []
            for off, label, cc, line in f.get("branches", []):
                tgt = self.enc.labels.get(label)
                if tgt is None or tgt < 0 or tgt == off:
                    continue
                if tgt not in entry:
                    continue
                out.append([off, tgt, cc, line])
            f["branches"] = out

    def gen_all(self):
        self.gen_entry()
        self.gen_functions()
        self.gen_vtables()
        self._dbg_resolve_branches()
        enc = self.enc
        enc.resolve()
        code = bytes(enc.buf)
        # 全局数据拼接 + 绝对地址回填
        blob = bytearray(code)
        for patch, gid in self.global_fixups:
            off = sum(len(g) for g in self.globals[:gid])
            addr = self.base + self.entry_off + len(code) + off
            struct.pack_into("<q", blob, patch, addr)
        for patch, label in self.code_fixups:
            struct.pack_into("<q", blob, patch,
                             self.base + self.entry_off + enc.labels[label])
        for g in self.globals:
            blob += g
        return bytes(blob)


# ---------------------------------------------------------------------------
# ELF64 写出（静态、无重定位、单 RWX PT_LOAD）
# ---------------------------------------------------------------------------


def write_elf(path, blob):
    total = ENTRY_OFF + len(blob)
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    ehdr = ident + struct.pack("<HHIQQQIHHHHHH",
                               2, 0x3E, 1, BASE + ENTRY_OFF, 64, 0, 0,
                               64, 56, 1, 0, 0, 0)
    phdr = struct.pack("<IIQQQQQQ", 1, 7, 0, BASE, BASE, total, total, 0x1000)
    with open(path, "wb") as f:
        f.write(ehdr + phdr + blob)
    os.chmod(path, 0o755)


def drop_table(fns_ast):
    """v1.93：`impl T : Drop { fn drop(t: T) { ... } }` -> {T: 函数名}。

    析构是**隐式调用**（AST 里没有 call 节点），所以这张表必须在全局 DCE
    之前算——否则析构函数会被当成不可达代码删掉，程序静默少跑清理。
    签名不合规（多参/有返回值）在这里 fail-fast，别等到发射期。"""
    out = {}
    for f in fns_ast:
        if f.get("impl_iface") != "Drop" or f.get("impl_method") != "drop":
            continue
        params = f.get("params") or []
        if len(params) != 1 or f.get("ret") != ("named", "void"):
            raise SyntaxError(
                f"{f.get('self_type')}.drop：析构函数必须是 "
                f"`fn drop(t: {f.get('self_type')})`（一个接收者、无返回值）")
        out[f["self_type"]] = f["name"]
    return out


def _ast_refs(node, refs, methods, bound):
    """AST 里引用到的顶层名字（增量哈希用：被调方签名变了必须重编调用方）。"""
    if isinstance(node, tuple):
        k = node[0] if node else None
        if k == "call" and len(node) > 1 and isinstance(node[1], list) and node[1]:
            refs.add(node[1][-1])
        elif k == "gcall" and len(node) > 1 and isinstance(node[1], str):
            refs.add(node[1])
        elif k == "name" and len(node) > 1 and isinstance(node[1], str):
            refs.add(node[1])
        elif k == "method" and len(node) > 2 and isinstance(node[2], str):
            methods.add(node[2])
        elif k in ("enumlit", "structlit", "pat") and len(node) > 1 \
                and isinstance(node[1], list) and node[1]:
            refs.add(node[1][0])
        elif k == "named" and len(node) > 1 and isinstance(node[1], str):
            refs.add(node[1])
        elif k == "let" and len(node) > 2 and isinstance(node[2], str):
            bound.add(node[2])
        elif k in ("for", "parfor", "foreach") and len(node) > 1 \
                and isinstance(node[1], str):
            bound.add(node[1])
        for v in node:
            _ast_refs(v, refs, methods, bound)
    elif isinstance(node, list):
        for v in node:
            _ast_refs(v, refs, methods, bound)
    elif isinstance(node, dict):
        for v in node.values():
            _ast_refs(v, refs, methods, bound)


def _sig_of(f):
    """函数签名（影响调用方降级的最小集合）。"""
    return [f.get("params"), f.get("ret"), f.get("impl_iface"),
            f.get("self_type"), f.get("impl_method")]


def fn_hashes(fns_ast, env_digest):
    """每个函数的增量哈希：自身 AST + 环境摘要 + 它引用到的函数签名。

    为什么不是"整个签名表"：加一个函数就会让全表变，等于没有增量。
    为什么不能只看自身 AST：改被调方的形参/返回类型会改调用方的降级
    （聚合返回开出参槽、实参转换），调用方必须跟着重编。
    """
    import qlm_qla
    sigs = {f["name"]: _sig_of(f) for f in fns_ast}
    out = {}
    for f in fns_ast:
        refs, methods, bound = set(), set(), set()
        _ast_refs(f.get("body"), refs, methods, bound)
        used = []
        for n in sorted(refs - bound):
            if n in sigs:
                used.append([n, sigs[n]])
        for m in sorted(methods):
            for k in sorted(sigs):
                if k.endswith("__" + m):
                    used.append([k, sigs[k]])
        body = {k: v for k, v in f.items() if k not in ("doc", "line")}
        blob = qlm_qla._canon_json({"env": env_digest, "deps": used,
                                    "fn": body})
        out[f["name"]] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
    return out


def _env_digest(arch, platform, optimize, structs, enums, drops, ifaces, cfg=""):
    """类型环境摘要：类型布局/接口/析构表变了，所有函数都得重编。"""
    import qlm_qla
    blob = qlm_qla._canon_json({
        "compiler": qlm_qla.compiler_fingerprint(),
        "arch": arch, "platform": platform, "opt": bool(optimize),
        "cfg": cfg,
        "structs": structs, "enums": enums,
        "drops": drops, "ifaces": ifaces,
    })
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def cfg_digest(cfg):
    """构建配置摘要（Quelmara.toml 变了，产物就可能变——不能复用档案）。"""
    import qlm_qla
    blob = qlm_qla._canon_json(
        {k: v for k, v in (cfg or {}).items() if not k.startswith("_")})
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _ir_json(v):
    """QuIR 操作数 -> JSON 可序列化值（tuple 递归转 list，int/str 原样）。"""
    if isinstance(v, (tuple, list)):
        return [_ir_json(x) for x in v]
    return v


def lower_and_optimize(src_path, arch="x86_64", optimize=True, dump_ir=False,
                  asset_root=None,
                       platform="linux", prog=None,
                       reuse=None, keep_all=False, libs=None, meta=None):
    """前端共享层：解析 + 降级 + 优化（x86_64 / aarch64 发射层共用）

    prog: v1.62 调试信息预加载程序（qlm_dbinfo.load_program_dbg 的产物：
    带行号标记的 fns_ast + 主文件函数名集）。非 None 时跳过内部
    load_program，并打开 Lower 的调试标记发射。

    v2.03 `.qla` 相关参数：
    reuse:   `qlm_qla.Archive`——按函数哈希复用它的 IR（函数级增量）。
    keep_all: 不做全局 DCE（`--lib`：库没有入口，全部函数都要留下）。
    libs:    其他 `.qla`（二进制库）：注入它们的类型表与函数签名存根。
    meta:    非 None 时填入档案元数据（函数记录/全局区/符号表/未定义符号）。
    """
    require_source(src_path)
    cfg = load_config(src_path)
    if prog is None:
        mod, _imports, fns_ast, tests, structs, enums, _order = load_program(src_path)
    else:
        fns_ast, tests = prog["fns_ast"], prog["tests"]
        structs, enums = prog["structs"], prog["enums"]
    # v2.03：二进制库（.qla）注入——类型表按布局一致性合并，函数只拿签名
    # 存根（body=None + qla=True），实现留给链接期。
    if libs:
        fns_ast = _inject_libs(fns_ast, structs, enums, libs)
    fns_ast = with_test_runner(fns_ast, tests)   # test "name" { } -> 测试入口
    # v1.93：析构表必须在 DCE 之前算（隐式调用，DCE 看不到），并把析构
    # 函数钉成 DCE 根——否则"定义了 drop 但只在作用域退出时被调用"的函数
    # 会被当死代码删掉。
    drops = drop_table(fns_ast)
    # 全局 DCE（v1.17d）：main 调用图可达性——import 大库只链接用到的。
    # 在测试合成之后（根含测试入口）、Lower 之前（AST 级，一次到位）
    if not keep_all:
        fns_ast = global_dce(fns_ast, keep=set(drops.values()))
    ifaces = {}
    for f in fns_ast:
        if f.get("impl_iface") and f.get("iface_sig"):
            ifaces.setdefault(f["impl_iface"], {}).update(f["iface_sig"])
    cdg = cfg_digest(cfg)
    hashes = fn_hashes(fns_ast, _env_digest(arch, platform, optimize, structs,
                                            enums, drops, ifaces, cdg))
    # 复用：只有哈希一致、且来源档案与当前环境同源的函数才接管
    reuse_map, reuse_order, seed = None, None, None
    if reuse is not None:
        import qlm_qla
        if reuse.compiler != qlm_qla.compiler_fingerprint():
            raise SyntaxError(
                f"增量档案 {reuse.unit} 是另一版编译器产出的"
                f"（指纹 {reuse.compiler}），不能复用——请全量重编")
        if reuse.cfg and reuse.cfg != cdg:
            raise SyntaxError(
                f"增量档案 {reuse.unit} 的构建配置与本工程不同"
                f"（{reuse.cfg} vs {cdg}）——配置变了必须全量重编")
        if bool(reuse.opt) != bool(optimize):
            raise SyntaxError(
                f"增量档案 {reuse.unit} 是 {'--no-opt' if not reuse.opt else '优化'} "
                f"构建产出的，与本次开关不一致——请全量重编")
        reuse_map = {r["name"]: r for r in reuse.funcs}
        reuse_order = [r["name"] for r in reuse.funcs]
        seed = {"globals": reuse.globals, "special": reuse.special,
                "counters": reuse.counters, "strmap": reuse.strmap}
        keep = {n: r for n, r in reuse_map.items()
                if n in hashes and hashes[n] == r.get("hash")}
        # 不在 fns_ast 里的记录（lambda 体 / parfor worker / 运行库 helper）
        # 跟着它们的父函数走：父函数复用时一并复用，父函数重编时全部作废
        # （否则新旧两份 `__lam_N` 同名，链接期会撞）。
        alive = set(keep)
        for n, r in reuse_map.items():
            if n in hashes:
                continue
            owner = r.get("owner")
            if owner is not None:
                if owner in alive:            # 父函数复用 -> 合成函数跟着复用
                    keep[n] = r
            else:
                # 运行库 helper（无 owner）：它的 IR 只由编译器指纹 + 平台 +
                # 配置决定，与用户源码无关——**永远复用**。重新发射一份会
                # 把全局字重开（数据区变大）且 IR 与旧版不一致。
                keep[n] = r
        # 内联传播：内联把 callee 的函数体搬进了 caller，所以 callee 一变，
        # caller 的 IR 也"应该"跟着变——不失效就会留着**旧函数体的副本**
        # （实测：改 helper 的 `* 2` 为 `* 3`，被内联的 use 仍算出旧值）。
        # 沿着 `inl` 图做不动点，直到没有新的失效。
        dirty = {n for n in hashes if n not in keep}
        changed = True
        while changed:
            changed = False
            for n, r in list(keep.items()):
                if any(c in dirty for c in (r.get("inl") or ())):
                    keep.pop(n)
                    dirty.add(n)
                    changed = True
        reuse_map = keep
        reuse_order = [n for n in reuse_order if n in keep]
        seed["special"] = {k: v for k, v in (reuse.special or {}).items()}
    low = Lower(fns_ast, cfg, arch=arch, structs=structs, enums=enums,
                asset_root=asset_root,
                platform=platform,
                dbg=prog is not None,
                dbg_main=(prog.get("main_fns") if prog else None),
                dbg_src=(src_path if prog else None),
                drop_fns=drops, seed=seed)
    fns = low.run(fns_ast, reuse=reuse_map, reuse_order=reuse_order)
    reused = set(low.reuse_fns)
    fresh = [fn for fn in fns if fn.name not in reused]
    if optimize:
        # v0.2 管线：字符串求长外提 -> 内联 -> 逐函数收敛
        # （求长外提必须在内联之前：内联会把 __str_len 的扫描循环搬进循环体）
        for fn in fresh:
            opt_strlen_hoist(fn)
        # v1.71：调试构建（prog 非 None，即 --dbg-info）默认**不内联**。
        # 内联后被调函数的语句行落在调用者函数体里，独立函数体成为死代码，
        # 源码断点会静默不命中（实测：work 内联进 main 后
        # `break main.qma:12` 永不触发，bt 也看不到 work 帧）。
        # 调试构建以断点语义优先；QLM_NO_INLINE=1 仍可显式关。
        if prog is None and "1" not in os.environ.get(
                "QLM_NO_INLINE", "").split(","):
            # 复用的函数已经是优化后的 IR：只让新降级的函数再走一遍内联
            opt_inline(fns, only=None if not reused else
                       {fn.name for fn in fresh})
        for fn in fresh:
            # 调试/覆盖率构建（prog 非 None）不做分支反转：覆盖率靠 `jcc`
            # 的目标记分支边，反转后 then 分支直落、边就观测不到了。
            opt_all(fn, unroll=True, invert=(prog is None))
    # 编译期死循环体检（v1.16）：guard 变量不更新 → 警告 + 位置
    import qlm_opt as _qopt
    _qopt.check_suspicious_loops(fns)
    if dump_ir:
        if dump_ir == "json":
            # v2.59：结构化 QuIR，给 tools/*.qma（自研语言写的分析工具）读。
            # 只导出"分析要用的三件套"：函数名 / vreg 总数 / 指令数组。
            # 指令里的 tuple（('imm',3) 这类）递归转 list，整型 vreg 保持 int，
            # 消费端用"是数组还是整数"区分立即数与 vreg。
            print(json.dumps({"fns": [
                {"name": fn.name, "nv": fn.nv,
                 "instrs": [_ir_json(x) for x in fn.instrs]}
                for fn in fns]}, ensure_ascii=False))
        else:
            for fn in fns:
                print(f"== {fn.name} (vregs={fn.nv}) ==")
                for ins in fn.instrs:
                    print("   ", ins)
    if meta is not None:
        _fill_meta(meta, fns, low, fns_ast, hashes, reuse_map, structs, enums,
                   ifaces, keep_all, cdg)
    return fns, low, cfg


def _inject_libs(fns_ast, structs, enums, libs):
    """把 `.qla` 的类型表与函数签名存根注入本次编译。"""
    import qlm_qla
    T = qlm_qla.deep_tuple
    have = {f["name"] for f in fns_ast}
    for arc in libs:
        for kind, table in (("structs", structs), ("enums", enums)):
            norm = qlm_qla.norm_decl(kind, arc.decls.get(kind) or {})
            for k, v in norm.items():
                if k in table and qlm_qla.norm_decl(kind, {k: table[k]})[k] != v:
                    raise SyntaxError(
                        f"二进制库 {arc.unit} 的 {kind[:-1]} {k} 与本地定义"
                        f"布局不一致——同名类型不能有两套布局")
                table.setdefault(k, v)
        for e in arc.exports:
            if e["name"] in have:
                continue          # 本地有同名定义：本地优先（不静默替换）
            stub = {"name": e["name"],
                    "params": qlm_qla.norm_params(e["params"]),
                    "ret": T(e["ret"]), "body": None, "qla": True, "pub": True}
            for k in ("impl_iface", "self_type", "impl_method"):
                if e.get(k):
                    stub[k] = e[k]
            if e.get("iface_sig"):
                stub["iface_sig"] = {m: [qlm_qla.norm_params(ps), T(rt)]
                                     for m, (ps, rt) in e["iface_sig"].items()}
            fns_ast.append(stub)
            have.add(e["name"])
    return fns_ast


def _fill_meta(meta, fns, low, fns_ast, hashes, reuse_map, structs, enums,
               ifaces, keep_all, cfg_dg=""):
    """把降级结果整理成 `.qla` 需要的元数据（qlm_qla.Archive 直接吃）。"""
    import qlm_qla
    by_name = {f["name"]: f for f in fns_ast}
    records = []
    for fn in fns:
        if reuse_map and fn.name in reuse_map:
            # 复用的函数：记录**原样搬过来**（IR 已经是 JSON 形态）。
            # 重新序列化 1.4 万条指令要多花上百毫秒，而且结果一字不差。
            records.append(dict(reuse_map[fn.name]))
            continue
        h = hashes.get(fn.name)
        needs = low.fn_needs.get(fn.name)
        owner = low.fn_owner.get(fn.name)
        records.append(qlm_qla.fn_record(fn, h or "", needs or (), owner))
    exports = []
    for f in fns_ast:
        if not f.get("pub") or f.get("qla"):
            continue
        e = {"name": f["name"], "params": [list(p) for p in f["params"]],
             "ret": list(f["ret"]), "pub": True}
        for k in ("impl_iface", "self_type", "impl_method", "iface_sig"):
            if f.get(k):
                e[k] = f[k]
        exports.append(e)
    defined = {r["name"] for r in records}
    vt_labels = {f"__vt_{i}__{t}"
                 for (i, t) in (getattr(low, "vtables", None) or {})}
    undefined = []
    for r in records:
        for ref in qlm_qla.symbol_refs(qlm_qla.json_to_ir(r["ir"])):
            if ref in defined or ref in vt_labels or ref in undefined:
                continue
            undefined.append(ref)
    for _k, fnames in (getattr(low, "vtables", None) or {}).items():
        for ref in fnames:
            if ref not in defined and ref not in undefined:
                undefined.append(ref)
    special = {}
    for name, attr in (("argc", "argc_gid"), ("argv", "argv_gid"),
                       ("written", "written_gid"),
                       ("committed", "committed_gid"),
                       ("static", "_static_gid"), ("free", "free_gid"),
                       ("args_copied", "_args_copied_gid")):
        gid = getattr(low, attr, None)
        if isinstance(gid, int):
            special[name] = gid
    meta.update({
        "funcs": records,
        "globals": list(low.globals),
        "vtables": [[i, t, list(fs)]
                    for (i, t), fs in sorted(
                        (getattr(low, "vtables", None) or {}).items())],
        "special": special,
        "counters": {"lam_seq": low.lam_seq, "spawn_id": low.spawn_id},
        "exports": exports,
        "decls": {"structs": structs, "enums": enums, "ifaces": ifaces},
        "undefined": sorted(undefined),
        "uses_args": bool(getattr(low, "uses_args", False)),
        "nreused": sum(1 for n in (reuse_map or ()) if n in hashes),
        "ntotal": len(by_name),
        "irreused": sum(len(r["ir"]) for r in records
                        if reuse_map and r["name"] in reuse_map),
        "irtotal": sum(len(r["ir"]) for r in records),
        "nreused_all": len(reuse_map or ()),
        "strmap": dict(getattr(low, "gid_of_str", {}) or {}),
        "cfg": cfg_dg,
    })
    return meta


def transpile_native(src_path, dump_ir=False, optimize=True, arch="x86_64", asset_root=None):
    fns, low, cfg = lower_and_optimize(src_path, arch=arch, optimize=optimize, dump_ir=dump_ir,
                                       asset_root=asset_root)
    cg = Codegen(fns, low.globals, low=low)
    blob = cg.gen_all()
    return blob, cfg


def main():
    ap = argparse.ArgumentParser(description="Quelmara 原生后端 (Quelmara -> 裸 ELF64)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("build", "run"):
        p = sub.add_parser(c)
        p.add_argument("src")
        p.add_argument("-o", "--out", default=None)
        p.add_argument("--dump-ir", action="store_true")
        p.add_argument("--no-opt", action="store_true")
    args = ap.parse_args()

    blob, cfg = transpile_native(args.src, dump_ir=args.dump_ir, optimize=not args.no_opt)
    base = os.path.splitext(os.path.basename(args.src))[0]
    out = args.out or os.path.join("build", base)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    write_elf(out, blob)
    print(f"[qlm-native] {args.src} -> {out} ({len(blob)} 字节机器码+数据, 无 libc)")
    print(f"[qlm-native] config: {cfg['_path'] or '(默认)'} | "
          f"multicore={cfg['core']['multicore']} threads={cfg['core']['threads'] or 'auto'}")
    if args.cmd == "run":
        print(f"[qlm-native] exec {out}")
        os.execv(os.path.abspath(out), [os.path.abspath(out)])


if __name__ == "__main__":
    main()
