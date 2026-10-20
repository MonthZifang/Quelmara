#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rosoto 原生后端 v0.1（自研，零外部依赖）
========================================
Rosoto 源码 -> RosIR -> 优化passes -> 线性扫描寄存器分配 -> 自研 x86_64 编码器 -> ELF64 裸可执行文件

不依赖 libc / gcc / LLVM：
  - 直接产出静态 ELF64（基址 0x400000，单 RWX 段，无重定位）
  - 运行库（print/itoa）用 RosIR 自举实现，I/O 走 raw syscall
  - parfor 多核：raw clone() + wait4() + 共享内存归约（无需 pthread）

已实现优化（见 BACKEND.md 优化目录）：
  常量折叠 / 强度削减(mul->shl) / 复制传播 / 死代码消除 /
  cmp+jcc 融合 / 线性扫描寄存器分配(调用感知) / 帧槽复用 / mov 消除

用法：
  python3 tools/rosoto_native.py build examples/fib.ros -o build/fib
  python3 tools/rosoto_native.py run   examples/loop_sum.ros
"""

import argparse
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rosoto import (tokenize, Parser, load_config, walk_stmts,  # noqa: E402
                    parse_source, with_test_runner, validate_match,
                    resolve_option_patterns)

# ---------------------------------------------------------------------------
# x86-64 寄存器编号
# ---------------------------------------------------------------------------
RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = 0, 1, 2, 3, 4, 5, 6, 7
R8, R9, R10, R11, R12, R13, R14, R15 = 8, 9, 10, 11, 12, 13, 14, 15

POOL = [RBX, RSI, RDI, R8, R9, R12, R13, R14, R15]   # 可分配寄存器（9 个）
CALLEE_SAVED = [RBX, R12, R13, R14, R15]              # 跨调用存活用
ARG_REGS = [RDI, RSI, RDX, RCX, R8, R9]               # 调用约定（自研 ABI，SysV 形状）
SCRATCH, SCRATCH2, ACC = R11, R10, RAX                # 编码期临时寄存器（不参与分配）

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

    def mov8_mr(self, base, index, scale, disp, src):
        self.emit(rex(r=src, x=index, b=base), b"\x88",
                  modrm_mem(src, base, index, scale, disp))

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

    def movzx_r_r8(self, dst, src8):
        self.emit(rex(w=1, r=dst, b=src8), b"\x0f\xb6", modrm_reg(dst, src8))

    # ---- SSE2 浮点（x86-64 基线自带 SSE2；xmm0/xmm1/xmm2 作编码期临时）----
    def movq_xr(self, x, r):
        """movq xmm_x, r64（64 位位模式进 XMM）"""
        self.emit(b"\x66", rex(w=1, r=x, b=r), b"\x0f\x6e", modrm_reg(x, r))

    def movq_rx(self, r, x):
        """movq r64, xmm_x"""
        self.emit(b"\x66", rex(w=1, r=x, b=r), b"\x0f\x7e", modrm_reg(x, r))

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

    def resolve(self):
        for patch, label in self.fixups:
            target = self.labels[label]
            struct.pack_into("<i", self.buf, patch, target - (patch + 4))
        self.fixups = []


# ---------------------------------------------------------------------------
# RosIR：函数 = vreg + 指令列表（非 SSA，可变量原地更新，无 phi）
# 指令：
#   ('mov', dst, src)                  src: vreg | ('imm',n) | ('ga',gid)
#   ('bin', op, dst, a, b)             op: add sub mul div mod and or xor shl shr sar
#   ('neg'/'not', dst, a)
#   ('cmpset', cc, dst, a, b)          dst = (a cc b) ? 1 : 0
#   ('label', L) ('jmp', L) ('jz', a, L) ('jnz', a, L) ('jcc', cc, a, b, L)
#   ('call', dst|None, fname, [args])
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
# 降级：AST -> RosIR
# ---------------------------------------------------------------------------


# 切片 `[]T` = {ptr, len} 两字：word0 指向元素序列，word1 是元素个数。
# 与结构体/枚举一样走聚合 ABI（隐藏出参指针返回 / 地址传递），
# 因此作函数参数/返回值零改动复用。
SLICE_WORDS = 2


class Lower:
    def __init__(self, fns_ast, cfg, arch="x86_64", structs=None, enums=None,
                 platform="linux"):
        self.fns_ast = {f["name"]: f for f in fns_ast}
        self.cfg = cfg
        self.arch = arch
        self.platform = platform          # linux | windows
        self.sc = SYSCALLS[arch]
        self.structs = structs or {}
        self.enums = enums or {}
        self.loop_stack = []       # [(cont_label, break_label)]，供 break/continue
        self.out = []
        self.globals = []          # bytes 列表
        self.gid_of_str = {}
        self.spawn_id = 0
        self.uses_chan = False
        self.uses_map = False
        self.uses_arena = False
        self.uses_join = False
        self.uses_bounds = False
        self.uses_f64_str = False
        if platform == "windows":
            # WriteFile 的 lpNumberOfBytesWritten 落点（Win32 必须给非空指针）
            self.written_gid = self.intern_array(1)
            # 已 MEM_COMMIT 的字节数（Windows 按 1MB 粒度按需提交）
            self.committed_gid = self.intern_array(1)

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
    @staticmethod
    def _mark_slice(fn, v):
        if isinstance(v, int):
            if not hasattr(fn, "slicev"):
                fn.slicev = set()
            fn.slicev.add(v)
        return v

    @staticmethod
    def _is_slice(fn, v):
        return isinstance(v, int) and v in getattr(fn, "slicev", set())

    def alloc_slice(self, fn):
        """开一段 2 字帧槽作为切片值（word0=ptr, word1=len）"""
        return self._mark_slice(fn, self.alloc_words(fn, SLICE_WORDS))

    def make_slice(self, fn, ptr, length):
        """由指针 + 长度构造切片值（零拷贝）"""
        s = self.alloc_slice(fn)
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

    def array_copy(self, fn, dst, src, n):
        for i in range(n):
            t = fn.new_v()
            fn.emit("load", t, src, ("imm", i))
            fn.emit("store", dst, ("imm", i), t)

    def emit_bounds(self, fn, idx, n, dynamic=False):
        """越界 fail-fast（Rosoto.toml [build] bounds_check 可关闭）。
        n 默认是常量长度；dynamic=True 时 n 是运行期 vreg（切片动态长度）"""
        if not self.cfg["build"].get("bounds_check", True):
            return
        self.uses_bounds = True
        nval = n if dynamic else ("imm", n)
        l_ok = fn.label("bok")
        l_fail = fn.label("bfail")
        fn.emit("jcc", "ge", idx, nval, l_fail)
        fn.emit("jcc", "ge", idx, ("imm", 0), l_ok)
        fn.emit("label", l_fail)
        fn.emit("call", None, "__bounds_fail", [])
        fn.emit("label", l_ok)

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
                sub = fn.new_v()
                fn.emit("bin", "add", sub, addr, ("imm", off * 8))
                self._mark_struct(fn, sub, ftype[1])
                self.struct_copy(fn, sub, val, ftype[1])
            else:
                val = self.conv_to(fn, val, self._float_of(fn, val), self._ty_float_w(ftype))
                fn.emit("store", addr, ("imm", off), val)
        return addr

    def lower_enum_lit(self, e, fn, env):
        """枚举构造 -> 帧槽块：字 0 存 tag，字 1.. 存载荷"""
        path, fields = e[1], e[2]
        ename, vname = path[0], path[1]
        if ename not in self.enums:
            raise SyntaxError(f"未声明的枚举 {ename}")
        vidx, vfields = self.enum_variant(ename, vname)
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
                off += self.agg_size(ftype[1])
            else:
                val = self.conv_to(fn, val, self._float_of(fn, val), self._ty_float_w(ftype))
                fn.emit("store", addr, ("imm", off), val)
                off += 1
        return self._mark_struct(fn, addr, ename)

    def lower_match(self, e, fn, env, as_expr):
        """match -> tag 比较链 + 每臂载荷绑定（不新增 RosIR 指令，纯现有指令降级）"""
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
    def intern(self, data: bytes):
        self.globals.append(data)
        return len(self.globals) - 1

    def intern_str(self, s: str):
        key = s
        if key not in self.gid_of_str:
            self.gid_of_str[key] = self.intern(s.encode("utf-8") + b"\x00")
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
        if self.platform == "windows":
            fn.emit("winapi", None, "ExitProcess", [("imm", code)])
        else:
            fn.emit("syscall", None, self.sc["exit"],
                    [("imm", code), ("imm", 0), ("imm", 0),
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
        """Rosoto.toml 是否要求单核/单线程（spawn/parfor 编译期降级）"""
        return (not self.cfg["core"]["multicore"]) or \
            int(self.cfg["core"]["threads"] or 0) == 1

    def emit_yield(self, fn):
        """让出 CPU（自旋等待时避免把整核跑满）"""
        if self.platform == "windows":
            fn.emit("winapi", None, "SwitchToThread", [])
        else:
            fn.emit("syscall", None, self.sc["yield"],
                    [("imm", 0), ("imm", 0), ("imm", 0),
                     ("imm", 0), ("imm", 0), ("imm", 0)])

    # ---- 表达式：返回 ('imm',n) | ('ga',gid) | vreg ----
    def eval(self, e, fn, env):
        k = e[0]
        if k == "num":
            return ("imm", e[1])
        if k == "fnum":
            return self.make_fnum(fn, e[1], e[2])
        if k == "bool":
            return ("imm", 1 if e[1] else 0)
        if k == "str":
            return ("ga", self.intern_str(e[1]))
        if k == "name":
            if e[1] not in env:
                raise SyntaxError(f"未定义变量 {e[1]}")
            return env[e[1]]
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
                    raise SyntaxError("数组元素暂不支持浮点（v1 边界）")
                fn.emit("store", addr, ("imm", i), v)
            return addr
        if k == "index":
            obj = self.eval(e[1], fn, env)
            n = self._arr_of(fn, obj)
            if n is not None:
                idx = self.eval(e[2], fn, env)
                self.emit_bounds(fn, idx, n)
                d = fn.new_v()
                fn.emit("load", d, obj, idx)
                return d
            if self._is_slice(fn, obj):
                # 切片：ptr = s.word0，长度是运行期值（动态越界检查）
                ptr = self.slice_ptr(fn, obj)
                ln = self.slice_len(fn, obj)
                idx = self.eval(e[2], fn, env)
                self.emit_bounds(fn, idx, ln, dynamic=True)
                d = fn.new_v()
                fn.emit("load", d, ptr, idx)
                return d
            raise SyntaxError("下标只能用于定长数组或切片")
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
            cap = self.eval(e[2][0], fn, env) if e[2] else ("imm", 16)
            d = fn.new_v()
            fn.emit("call", d, "__map_open", [cap, ("imm", ktag)])
            return self._mark_map(fn, d, kt, vt)
        if k == "unop":
            a = self.eval(e[2], fn, env)
            if e[1] == "-":
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
        if k == "binop":
            return self.lower_binop(e, fn, env)
        if k == "method":
            obj = self.eval(e[1], fn, env)
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
            raise SyntaxError(f"原生后端 v0.2 不支持方法 {e[2]}")
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
            if okt[0] != "named" or okt[1] not in (
                    "int", "i64", "i32", "i16", "i8", "u64", "u32", "u16", "u8", "bool", "str"):
                raise SyntaxError("? 的 Ok 载荷暂只支持整数/bool/str 标量")
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
        if k == "enumlit":
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
        fw = self._ty_float_w(ftype)
        if fw:
            self._mark_float(fn, d, fw)
        return d

    def lower_binop(self, e, fn, env):
        return self.arith(e[1], self.eval(e[2], fn, env), self.eval(e[3], fn, env), fn, env)

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
        # 魔数乘高位替代 idiv（分支无关，含符号修正）
        if op in ("/", "%") and isinstance(b, tuple) and b[0] == "imm" and 0 < b[1] < 2**63:
            mag = magic_unsigned(b[1])
            if mag:
                M, sh = mag
                x = a
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
        if op not in ("add", "sub", "mul", "div", "mod", "and", "or", "xor", "shl", "shr", "sar"):
            opmap = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod",
                     "&": "and", "|": "or", "^": "xor"}
            if op not in opmap:
                raise SyntaxError(f"不支持的运算符 {op}")
            op = opmap[op]
        fn.emit("bin", op, d, a, b)
        return d

    def lower_map_method(self, m, obj, mp, args, fn, env):
        """m.set/get/has/del -> __map_* 运行时（开放寻址 + 线性探测）。
        键相等/哈希在运行时按句柄 ktag 分派（str 走 __str_eq 内容比较）；
        这里在编译期校验键/值实参与声明的 K/V 标量一致，不许静默错编。"""
        kt, vt = mp
        self.uses_map = True

        def key_arg(a):
            kv = self.eval(a, fn, env)
            self.check_map_arg("键", kt, self._is_str(fn, kv))
            return kv

        if m == "set":
            if len(args) != 2:
                raise SyntaxError("m.set(k, v) 需要两个实参")
            kv = key_arg(args[0])
            vv = self.eval(args[1], fn, env)
            self.check_map_arg("值", vt, self._is_str(fn, vv))
            d = fn.new_v()
            fn.emit("call", d, "__map_set", [obj, kv, vv])
            return d
        if m == "get":
            if len(args) != 1:
                raise SyntaxError("m.get(k) 需要且只需要一个实参")
            kv = key_arg(args[0])
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
        """短路求值 -> 0/1"""
        d = fn.new_v()
        l_true, l_false, l_end = fn.label("t"), fn.label("f"), fn.label("e")
        if op == "&&":
            fn.emit("jz", a, l_false)
            fn.emit("jz", b, l_false)
        else:
            fn.emit("jnz", a, l_true)
            fn.emit("jnz", b, l_true)
        fn.emit("mov", d, ("imm", 1))
        fn.emit("jmp", l_end)
        fn.emit("label", l_true)
        fn.emit("mov", d, ("imm", 1))
        fn.emit("jmp", l_end)
        fn.emit("label", l_false)
        fn.emit("mov", d, ("imm", 0))
        fn.emit("label", l_end)
        return d

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
        if name in ("to_float", "to_f32", "to_int") and name not in self.fns_ast:
            if len(e[2]) != 1:
                raise SyntaxError(f"{name}(x) 需要且只需要一个实参")
            x = self.eval(e[2][0], fn, env)
            wf = self._float_of(fn, x)
            if name == "to_int":
                return self.conv_to(fn, x, wf, None)
            tw = "f64" if name == "to_float" else "f32"
            return self.conv_to(fn, x, wf, tw)
        if name == "cores":
            return ("imm", os.cpu_count() or 1)
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
            self.emit_exit(fn, 1)
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
                if self._map_of(fn, env[a[1]]) is not None:
                    self.uses_map = True
                    d = fn.new_v()
                    fn.emit("call", d, "__map_len", [env[a[1]]])
                    return d
            # 非名字实参：按求值结果判别（如函数返回的切片）
            av = self.eval(a, fn, env)
            if self._is_slice(fn, av):
                return self.slice_len(fn, av)
            if self._map_of(fn, av) is not None:
                self.uses_map = True
                d = fn.new_v()
                fn.emit("call", d, "__map_len", [av])
                return d
            raise SyntaxError("len() 目前只支持定长数组、切片或 map")
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
            return self.make_slice(fn, av, ("imm", n))
        if name not in self.fns_ast:
            raise SyntaxError(f"未定义函数 {name}")
        args = [self.eval(a, fn, env) for a in e[2]]
        params = self.fns_ast[name]["params"]
        for i, a in enumerate(args):
            n = self._arr_of(fn, a)
            if n is not None:
                # 数组作实参：形参是 `[]T` 时零拷贝转切片（SPEC §2），否则报错
                if i < len(params) and params[i][1][0] == "slice":
                    args[i] = self.make_slice(fn, a, ("imm", n))
                    continue
                raise SyntaxError("定长数组暂不支持作函数实参；请用 slice_of(a) 转成切片")
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
                tmp = self.alloc_struct(fn, sname)
                self.struct_copy(fn, tmp, a, sname)
                args[i] = tmp
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
            return tmp
        if ret[0] == "named" and self.is_agg(ret[1]):
            # 聚合返回值：隐藏出参指针约定（调用方开帧槽，callee 拷入）
            tmp = self.alloc_struct(fn, ret[1])
            fn.emit("call", None, name, [tmp] + args)
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
        return d

    # ---- 布尔条件跳转 ----
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
            cc = {"==": "e", "!=": "ne", "<": "l", "<=": "le", ">": "g", ">=": "ge"}[e[1]]
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
    def stmt(self, s, fn, env):
        k = s[0]
        if k == "let":
            spec = self.eval(s[3], fn, env)
            n = self._arr_of(fn, spec)
            if n is not None:
                if s[3][0] == "arraylit":
                    # 字面量已经是在帧上新建的数组，直接绑定，不再多拷一次
                    env[s[2]] = spec
                    return
                dst = self.alloc_array(fn, n)
                self.array_copy(fn, dst, spec, n)
                env[s[2]] = dst
                return
            sname = self._struct_of(fn, spec)
            if sname is not None:
                # 结构体：值语义 -> 拷贝到新的帧槽
                dst = self.alloc_struct(fn, sname)
                self.struct_copy(fn, dst, spec, sname)
                env[s[2]] = dst
                return
            if self._is_slice(fn, spec):
                # 切片：{ptr,len} 两字值语义拷贝（仍共享底层存储）
                dst = self.alloc_slice(fn)
                self.words_copy(fn, dst, spec, SLICE_WORDS)
                env[s[2]] = dst
                return
            is_str = self._is_str(fn, spec)
            is_bool = s[3][0] == "bool" or (isinstance(spec, int) and spec in getattr(fn, "boolv", set()))
            if isinstance(spec, tuple) and spec[0] in ("imm", "ga"):
                d = fn.new_v()
                fn.emit("mov", d, spec)
                spec = d
            if is_str:
                self._mark_str(fn, spec)
            if is_bool:
                self._mark_bool(fn, spec)
            env[s[2]] = spec
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
                self.array_copy(fn, cur, spec, n)
                return
            sname = self._struct_of(fn, cur)
            if sname is not None:
                if s[2] != "=":
                    raise SyntaxError("结构体只支持 = 整体赋值")
                spec = self.eval(s[3], fn, env)
                if self._struct_of(fn, spec) != sname:
                    raise SyntaxError("结构体赋值两侧类型不一致")
                self.struct_copy(fn, cur, spec, sname)
                return
            spec = self.eval(s[3], fn, env)
            op = s[2]
            if isinstance(cur, int):           # 可变量：原地更新（避免 phi）
                if op == "=":
                    spec = self.conv_to(fn, spec, self._float_of(fn, spec),
                                        self._float_of(fn, cur))
                    fn.emit("mov", cur, spec)
                    if self._is_str(fn, spec):
                        self._mark_str(fn, cur)
                else:
                    binop = {"+=": "+", "-=": "-", "*=": "*", "/=": "/", "%=": "%"}[op]
                    tmp = self.arith(binop, cur, spec, fn, env)
                    tmp = self.conv_to(fn, tmp, self._float_of(fn, tmp),
                                       self._float_of(fn, cur))
                    fn.emit("mov", cur, tmp)
                    if self._is_str(fn, tmp):
                        self._mark_str(fn, cur)
            else:
                raise SyntaxError("常量不可赋值")
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
            self.loop_stack.append((l_top, l_end))   # continue -> 重新判据
            self.block(s[2], fn, dict(env))
            self.loop_stack.pop()
            fn.emit("jmp", l_top)
            fn.emit("label", l_end)
            return
        if k in ("for", "parfor"):
            self.lower_for(s, fn, env, parallel=(k == "parfor"))
            return
        if k == "return":
            if self.fn_ret[0] == "array":
                raise SyntaxError("定长数组暂不支持作返回值（v0.6 边界）")
            if self.fn_ret_agg or self.fn_ret_slice:
                if s[1] is None:
                    raise SyntaxError("聚合（结构体/枚举/切片）返回值函数必须 return 一个值")
                spec = self.eval(s[1], fn, env)
                if self.fn_ret_slice:
                    if not self._is_slice(fn, spec):
                        raise SyntaxError("函数返回类型是切片，return 的表达式类型不匹配")
                    self.words_copy(fn, self.fn_ret_target, spec, SLICE_WORDS)
                else:
                    if self._struct_of(fn, spec) != self.fn_ret_agg:
                        raise SyntaxError(
                            f"函数返回类型是 {self.fn_ret_agg}，return 的表达式类型不匹配")
                    # 值语义：拷进调用方提供的隐藏出参槽，再返回
                    self.struct_copy(fn, self.fn_ret_target, spec, self.fn_ret_agg)
                fn.emit("ret", ("imm", 0))
                return
            if s[1] is None:
                fn.emit("ret", None)
            else:
                v = self.eval(s[1], fn, env)
                v = self.conv_to(fn, v, self._float_of(fn, v),
                                 self._ty_float_w(self.fn_ret) if self.fn_ret[0] == "named" else None)
                fn.emit("ret", v)
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
            fn.emit("jmp", self.loop_stack[-1][1])
            return
        if k == "continue":
            if not self.loop_stack:
                raise SyntaxError("continue 只能出现在循环内")
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
            if self._struct_of(fn, spec) != ftype[1]:
                raise SyntaxError("结构体赋值两侧类型不一致")
            sub = fn.new_v()
            fn.emit("bin", "add", sub, addr, ("imm", off * 8))
            self._mark_struct(fn, sub, ftype[1])
            self.struct_copy(fn, sub, spec, ftype[1])
            return
        spec = self.eval(s[3], fn, env)
        if op == "=":
            spec = self.conv_to(fn, spec, self._float_of(fn, spec), self._ty_float_w(ftype))
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
        if op == "=":
            fn.emit("store", tgt, idx, val)
            return
        binop = {"+=": "add", "-=": "sub", "*=": "mul",
                 "/=": "div", "%=": "mod"}[op]
        cur = fn.new_v()
        fn.emit("load", cur, tgt, idx)
        fn.emit("bin", binop, cur, cur, val)
        fn.emit("store", tgt, idx, cur)

    def block(self, stmts, fn, env):
        for s in stmts:
            self.stmt(s, fn, env)

    # ---- for / parfor ----
    def lower_for(self, s, fn, env, parallel):
        _, var, lo_e, hi_e, body = s
        lo = self.eval(lo_e, fn, env)
        hi = self.eval(hi_e, fn, env)
        if parallel:
            self.lower_parfor(var, lo, hi, body, fn, env)
            return
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
        self.loop_stack.append((l_cont, l_end))      # continue -> 自增步
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
            # 单核降级（Rosoto.toml [core] multicore=false）：确定性串行
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
            self.loop_stack.append((l_cont, l_end))
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
        self.loop_stack.append((l_cont, l_end))
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
                fn.emit("store", ("ga", pid_gid), ("imm", t), pid)
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
        fn.strv = set()
        fn.boolv = set()
        self.fn_ret_agg = None
        self.fn_ret_target = None
        self.fn_ret_slice = False
        ret = f["ret"]
        if ret[0] == "slice":
            # 切片返回值：同聚合 ABI（隐藏出参指针作第一参数）
            self.fn_ret_slice = True
            self.fn_ret_target = fn.new_v()
        elif ret[0] == "named" and self.is_agg(ret[1]):
            # 聚合返回值：ABI = 隐藏出参指针作第一参数（发射层零改动）
            self.fn_ret_agg = ret[1]
            self.fn_ret_target = fn.new_v()
        params = [fn.new_v() for _ in f["params"]]
        if self.fn_ret_agg or self.fn_ret_slice:
            fn.emit("args", [self.fn_ret_target] + params)
            if self.fn_ret_agg:
                self._mark_struct(fn, self.fn_ret_target, self.fn_ret_agg)
            else:
                self._mark_slice(fn, self.fn_ret_target)
        else:
            fn.emit("args", params)
        env = {name: params[i] for i, (name, _) in enumerate(f["params"])}
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
                self._mark_slice(fn, params[i])
            elif ty[0] == "array":
                self._mark_arr(fn, params[i], ty[1])
            elif ty[0] == "named" and self.is_agg(ty[1]):
                # 聚合形参：实参侧传入的是【副本地址】，值语义成立
                self._mark_struct(fn, params[i], ty[1])
        self.fn_ret = f["ret"]
        self.block(f["body"], fn, env)
        fn.emit("ret", ("imm", 0))     # 兜底返回
        self.out.append(fn)
        return fn

    # ---- 自举运行库（print/itoa，全部 RosIR + raw syscall）----
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
        f = Fn("__str_eq")
        pa, pb = f.new_v(), f.new_v()
        f.emit("args", [pa, pb])
        i = f.new_v()
        f.emit("mov", i, ("imm", 0))
        l_top, l_diff, l_same = f.label("seq"), f.label("sdiff"), f.label("ssame")
        f.emit("label", l_top)
        ca, cb = f.new_v(), f.new_v()
        f.emit("load8", ca, pa, i)
        f.emit("load8", cb, pb, i)
        f.emit("jcc", "ne", ca, cb, l_diff)
        f.emit("jz", ca, l_same)          # 同位置 0 -> 到结尾，全等
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
        d = f.new_v()
        f.emit("bin", "mod", d, v, ("imm", 10))
        chv = f.new_v()
        f.emit("bin", "add", chv, d, ("imm", ord("0")))
        f.emit("store8", buf, pos, chv)
        f.emit("bin", "sub", pos, pos, ("imm", 1))
        f.emit("bin", "div", v, v, ("imm", 10))
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
        # 内存策略跟 Rosoto.toml [memory] heap_limit_mb 走：超限 fail-fast。
        heap_sz = int(self.cfg["memory"]["heap_limit_mb"] or 512) * 1024 * 1024
        gid_oom = self.intern_str("rosoto: heap_limit_mb exceeded (fail-fast)\n")
        gid_zero = self.intern_array(1)
        self.heap_gid = self.intern_array(1)       # 堆基址
        self.bump_gid = self.intern_array(1)       # 已用偏移

        # __alloc(n) -> ptr   自举 bump 分配器（惰性 mmap / VirtualAlloc + 上限检查）
        f = Fn("__alloc")
        n = f.new_v()
        f.emit("args", [n])
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
            self.emit_exit(f, 1)
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
        self.emit_exit(f, 1)
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
        r = f.new_v()
        f.emit("bin", "add", r, h, off)
        f.emit("ret", r)
        self.out.append(f)

        # ---- arena / 任务运行时（v0.4）----
        # 只发射真正用到的部分：hello 这种程序不会带 __join / __chan_*（省体积/导入）。
        if self.uses_bounds:
            msg = "rosoto: index out of bounds (fail-fast)\n"
            gid_b = self.intern_str(msg)
            f = Fn("__bounds_fail")
            f.emit("args", [])
            bp = f.new_v()
            f.emit("movaddr", bp, gid_b)
            self.emit_write(f, 2, bp, ("imm", len(msg.encode("utf-8"))))
            self.emit_exit(f, 1)
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
        # 布局（6 个 8 字节字）：[cap, head, tail, count, lock, buf]
        # lock 用 xchg 原子抢锁；忙等时 yield，不把整核跑满。
        # 只在 x86_64 发射（AArch64 需要 ldaxr/stxr 版本，后续补）。
        if self.uses_chan and self.arch == "x86_64":
            f = Fn("__chan_open")
            cap = f.new_v()
            f.emit("args", [cap])
            l_ok = f.label("cok")
            f.emit("jcc", "g", cap, ("imm", 0), l_ok)
            f.emit("mov", cap, ("imm", 1))
            f.emit("label", l_ok)
            blk = f.new_v()
            f.emit("call", blk, "__alloc", [("imm", 48)])
            sz = f.new_v()
            f.emit("bin", "mul", sz, cap, ("imm", 8))
            buf = f.new_v()
            f.emit("call", buf, "__alloc", [sz])
            for i, val in enumerate([cap, ("imm", 0), ("imm", 0),
                                     ("imm", 0), ("imm", 0), buf]):
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
            msg_nf = "rosoto: map key not found (fail-fast)\n"
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

            # __map_open(cap, ktag) -> 句柄（cap<1 取 16，再向上取整到 2 的幂）
            f = Fn("__map_open")
            cap, ktag = f.new_v(), f.new_v()
            f.emit("args", [cap, ktag])
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
            f.emit("call", blk, "__alloc", [("imm", 56)])
            sz = f.new_v()
            f.emit("bin", "mul", sz, cap, ("imm", 8))
            st = f.new_v()
            f.emit("call", st, "__alloc", [sz])
            kt = f.new_v()
            f.emit("call", kt, "__alloc", [sz])
            vt = f.new_v()
            f.emit("call", vt, "__alloc", [sz])
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
            f.emit("ret", blk)
            self.out.append(f)

            # __map_grow(m)：容量翻倍 rehash（旧表是 bump 分配，不回收；
            # arena 块内随块整体回卷，块外到进程退出才丢）
            f = Fn("__map_grow")
            m = f.new_v()
            f.emit("args", [m])
            cap = f.new_v()
            f.emit("load", cap, m, ("imm", 0))
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
            nst = f.new_v()
            f.emit("call", nst, "__alloc", [nsz])
            nkt = f.new_v()
            f.emit("call", nkt, "__alloc", [nsz])
            nvt = f.new_v()
            f.emit("call", nvt, "__alloc", [nsz])
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
            f.emit("label", l_rt)
            f.emit("jcc", "ge", i, cap, l_re)
            s = f.new_v()
            f.emit("load", s, ost, i)
            f.emit("jcc", "ne", s, ("imm", 1), l_skip)   # 墓碑/空槽不带入
            kk = f.new_v()
            f.emit("load", kk, okt, i)
            vv = f.new_v()
            f.emit("load", vv, ovt, i)
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
            f.emit("store", nvt, j, vv)
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
            self.emit_exit(f, 1)
            f.emit("label", l_ok)
            vt = f.new_v()
            f.emit("load", vt, m, ("imm", 6))
            d = f.new_v()
            f.emit("load", d, vt, idx)
            f.emit("ret", d)
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

        # __str_len(p) -> int
        f = Fn("__str_len")
        p = f.new_v()
        f.emit("args", [p])
        i = f.new_v()
        f.emit("mov", i, ("imm", 0))
        l_t, l_e = f.label("slt"), f.label("sle")
        f.emit("label", l_t)
        ch = f.new_v()
        f.emit("load8", ch, p, i)
        f.emit("jz", ch, l_e)
        f.emit("bin", "add", i, i, ("imm", 1))
        f.emit("jmp", l_t)
        f.emit("label", l_e)
        f.emit("ret", i)
        self.out.append(f)

        # __memcpy(dst, src, n)  正向拷贝（不处理重叠；调用方保证）
        f = Fn("__memcpy")
        d, s, m = f.new_v(), f.new_v(), f.new_v()
        f.emit("args", [d, s, m])
        i = f.new_v()
        f.emit("mov", i, ("imm", 0))
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

        # __str_concat(a, b) -> ptr
        f = Fn("__str_concat")
        a, b = f.new_v(), f.new_v()
        f.emit("args", [a, b])
        la = f.new_v()
        f.emit("call", la, "__str_len", [a])
        lb = f.new_v()
        f.emit("call", lb, "__str_len", [b])
        nn = f.new_v()
        f.emit("bin", "add", nn, la, lb)
        f.emit("bin", "add", nn, nn, ("imm", 1))
        dst = f.new_v()
        f.emit("call", dst, "__alloc", [nn])
        f.emit("call", None, "__memcpy", [dst, a, la])
        d2 = f.new_v()
        f.emit("bin", "add", d2, dst, la)
        f.emit("call", None, "__memcpy", [d2, b, lb])
        z = f.new_v()
        f.emit("bin", "add", z, la, lb)
        f.emit("store8", dst, z, ("imm", 0))
        f.emit("ret", dst)
        self.out.append(f)

        # __str_from_i64(v) -> ptr   低位起写、正向搬移（无 memmove 也能正确）
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
        f.emit("call", buf, "__alloc", [("imm", 33)])
        pos = f.new_v()
        f.emit("mov", pos, ("imm", 31))
        l_d, l_de = f.label("idig"), f.label("idige")
        f.emit("label", l_d)
        dd = f.new_v()
        f.emit("bin", "mod", dd, v, ("imm", 10))
        cc = f.new_v()
        f.emit("bin", "add", cc, dd, ("imm", 48))
        f.emit("store8", buf, pos, cc)
        f.emit("bin", "sub", pos, pos, ("imm", 1))
        f.emit("bin", "div", v, v, ("imm", 10))
        f.emit("jnz", v, l_d)
        f.emit("label", l_de)
        ln = f.new_v()
        f.emit("mov", ln, ("imm", 31))
        f.emit("bin", "sub", ln, ln, pos)            # ln = 31 - pos = 位数
        src = f.new_v()
        f.emit("bin", "add", src, pos, ("imm", 1))  # 数字串起点
        i = f.new_v()
        f.emit("mov", i, ("imm", 0))
        l_c, l_ce = f.label("icp"), f.label("icpe")
        f.emit("label", l_c)
        f.emit("jcc", "ge", i, ln, l_ce)
        ch = f.new_v()
        f.emit("bin", "add", ch, src, i)
        b1 = f.new_v()
        # 注意：load8 语义是 [base + idx]，base 必须是 buf，idx 才是字节偏移
        #（历史 bug：把偏移当基址，从绝对地址 ~31 读字节 -> 必然段错误）
        f.emit("load8", b1, buf, ch)
        dpos = f.new_v()
        f.emit("bin", "add", dpos, neg, i)
        f.emit("store8", buf, dpos, b1)
        f.emit("bin", "add", i, i, ("imm", 1))
        f.emit("jmp", l_c)
        f.emit("label", l_ce)
        l_nn = f.label("ineg")
        f.emit("jz", neg, l_nn)
        f.emit("store8", buf, ("imm", 0), ("imm", 45))   # '-'
        f.emit("label", l_nn)
        z = f.new_v()
        f.emit("bin", "add", z, neg, ln)
        f.emit("store8", buf, z, ("imm", 0))
        f.emit("ret", buf)
        self.out.append(f)

        # ---- 浮点格式化（与 C 端 rosoto_f64_to_str 算法逐位一致，双链 diff 依赖）----
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
            f.emit("call", buf, "__alloc", [("imm", 64)])
            pos = f.new_v()
            f.emit("mov", pos, ("imm", 0))

            def st(chs):
                """从 pos 起写字符串（含结尾 0），返回后 pos 已前进"""
                nonlocal pos
                for cc in chs:
                    f.emit("store8", buf, pos, ("imm", cc))
                    f.emit("bin", "add", pos, pos, ("imm", 1))

            def ret_buf():
                f.emit("ret", buf)

            # nan
            c = f.new_v()
            f.emit("fcmpset", "f64", "ne", c, x, x)
            l1 = f.label("fnan")
            f.emit("jz", c, l1)
            f.emit("store8", buf, ("imm", 0), ("imm", 110))   # 'n'
            f.emit("store8", buf, ("imm", 1), ("imm", 97))    # 'a'
            f.emit("store8", buf, ("imm", 2), ("imm", 110))   # 'n'
            f.emit("store8", buf, ("imm", 3), ("imm", 0))
            ret_buf()
            f.emit("label", l1)
            # +inf / -inf
            c = f.new_v()
            f.emit("fcmpset", "f64", "g", c, x, ("imm", fbits(1.7976931348623157e308)))
            l2 = f.label("finf")
            f.emit("jz", c, l2)
            f.emit("store8", buf, ("imm", 0), ("imm", 105))   # 'i'
            f.emit("store8", buf, ("imm", 1), ("imm", 110))   # 'n'
            f.emit("store8", buf, ("imm", 2), ("imm", 102))   # 'f'
            f.emit("store8", buf, ("imm", 3), ("imm", 0))
            ret_buf()
            f.emit("label", l2)
            c = f.new_v()
            f.emit("fcmpset", "f64", "l", c, x, ("imm", fbits(-1.7976931348623157e308)))
            l3 = f.label("fninf")
            f.emit("jz", c, l3)
            f.emit("store8", buf, ("imm", 0), ("imm", 45))    # '-'
            f.emit("store8", buf, ("imm", 1), ("imm", 105))   # 'i'
            f.emit("store8", buf, ("imm", 2), ("imm", 110))   # 'n'
            f.emit("store8", buf, ("imm", 3), ("imm", 102))   # 'f'
            f.emit("store8", buf, ("imm", 4), ("imm", 0))
            ret_buf()
            f.emit("label", l3)
            # 0
            c = f.new_v()
            f.emit("fcmpset", "f64", "e", c, x, ("imm", 0))   # +0.0 == 整数 0 位模式
            l4 = f.label("fzero")
            f.emit("jz", c, l4)
            f.emit("store8", buf, ("imm", 0), ("imm", 48))    # '0'
            f.emit("store8", buf, ("imm", 1), ("imm", 0))
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
            f.emit("ret", buf)
            self.out.append(f)

        # __str_from_bool(v) -> ptr
        f = Fn("__str_from_bool")
        v = f.new_v()
        f.emit("args", [v])
        l_f, l_e = f.label("sbf"), f.label("sbe")
        f.emit("jz", v, l_f)
        t = f.new_v()
        f.emit("movaddr", t, gid_true)
        f.emit("ret", t)
        f.emit("label", l_f)
        g = f.new_v()
        f.emit("movaddr", g, gid_false)
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
    def _map_of(fn, v):
        return getattr(fn, "mapv", {}).get(v) if isinstance(v, int) else None

    def run(self, fns_ast):
        # 先降级用户函数，再按需发射运行库：只把真正用到的
        # arena/join/chan 运行时塞进产物（省体积、省导入）。
        for f in fns_ast:
            self.lower_fn(f)
        self.lower_runtime()
        return self.out


# ===========================================================================
# 第二部分：RosIR 优化 passes -> 线性扫描寄存器分配 -> 机器码发射 -> ELF
# ===========================================================================


# ---------------------------------------------------------------------------
# RosIR 优化 passes 独立模块：tools/rosoto_opt.py（x86_64 / aarch64 发射层共享）
# 这里只做再导出，保持 `from rosoto_native import vreg_mentions` 的既有用法可用。
# ---------------------------------------------------------------------------

from rosoto_opt import (PURE, vreg_mentions, loop_regions,          # noqa: E402,F401
                        opt_dce, opt_copy_prop, opt_cse, opt_licm,
                        opt_loop_unroll, opt_all)


# ---------------------------------------------------------------------------
# 过程内联（RosIR 级）：小函数 / 单调用点函数内联，递归/环禁止
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
    if op == "ret":
        return ("ret", S(ins[1]) if ins[1] is not None else None)
    if op in ("load", "load8"):
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
    if op == "xchg":
        return ("xchg", V(ins[1]), S(ins[2]), S(ins[3]))
    if op == "args":
        return ("args", [V(x) for x in ins[1]])
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


def opt_inline(fns, max_instrs=28, rounds=3):
    """内联：小函数一律内联，大函数仅单调用点；递归/调用环禁止"""
    fmap = {f.name: f for f in fns}
    for _ in range(rounds):
        g = {f.name: {i[2] for i in f.instrs if i[0] == "call"} for f in fns}
        counts = _call_sites(fns)
        changed = False
        for fn in fns:
            out = []
            for ins in fn.instrs:
                if ins[0] == "call" and ins[2] in fmap:
                    callee = fmap[ins[2]]
                    cyclic = callee.name == fn.name or fn.name in _reachable(g, callee.name)
                    big = len(callee.instrs) > max_instrs
                    if getattr(callee, "no_inline", False) or cyclic or (big and counts.get(callee.name, 0) > 1):
                        out.append(ins)
                        continue
                    out.extend(_inline_one(fn, callee, ins))
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
        elif op == "frameaddr":
            res.append(("frameaddr", ren(ins[1]), ins[2] + fbase))
        else:
            res.append(_map_ins(ins, ren))
    res.append(("label", end))
    return res


# ---------------------------------------------------------------------------
# 线性扫描寄存器分配（保守区间 + 调用感知）
# ---------------------------------------------------------------------------


def allocate(fn, pool=POOL, callee_saved=CALLEE_SAVED):
    n = fn.nv
    first = [10 ** 9] * n
    last = [-1] * n
    call_sites = []
    for idx, ins in enumerate(fn.instrs):
        if ins[0] in ("call", "syscall", "winapi"):
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
            alloc[v] = ("m", 8 * (nslots + 1))   # 溢出到栈槽：[rbp-8], [rbp-16], ...
            nslots += 1
    return alloc, nslots, sorted(used_callee)


# ---------------------------------------------------------------------------
# 机器码发射
# ---------------------------------------------------------------------------

BASE = 0x400000
ENTRY_OFF = 0x78

# 各架构 Linux 系统调用号（IR 层架构无关，发射层按表取用）
SYSCALLS = {
    "x86_64": {"write": 1, "exit": 60, "mmap": 9, "clone": 56, "wait4": 61,
               "yield": 24},
    "aarch64": {"write": 64, "exit": 93, "mmap": 222, "clone": 220, "wait4": 260,
                "yield": 124},
}


class Codegen:
    def __init__(self, fns, globals_bytes, base=BASE, entry_off=ENTRY_OFF):
        self.fns = fns
        self.globals = globals_bytes
        self.base = base
        self.entry_off = entry_off
        self.enc = Enc()
        self.global_fixups = []    # (patch_pos, gid) -> 数据区绝对地址
        self.code_fixups = []      # (patch_pos, label) -> 代码区绝对地址（线程入口等）

    # ---- 操作数 ----
    def fetch(self, target, spec):
        if isinstance(spec, int):
            kind, val = self.alloc[spec]
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
            return (kind, val) if kind == "r" else ("m", val)
        return spec  # ('imm', n) / ('ga', gid)

    def dst_move(self, dst):
        kind, val = self.alloc[dst]
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
                else:
                    raise RuntimeError("并行搬移无法调度")

    def emit_move(self, src, dst):
        if src[0] == "r" and dst[0] == "r":
            if src[1] != dst[1]:
                self.enc.mov_rr(dst[1], src[1])
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
        if op == "label":
            enc.labels[ins[1]] = enc.pos()
        elif op == "jmp":
            enc.jmp(ins[1])
        elif op in ("jz", "jnz"):
            r = self.fetch(SCRATCH, ins[1])
            enc.test_rr(r, r)
            enc.jcc("e" if op == "jz" else "ne", ins[2])
        elif op == "jcc":
            cc, a, b, lbl = ins[1], ins[2], ins[3], ins[4]
            ra = self.fetch(SCRATCH2, a)
            if isinstance(b, tuple) and b[0] == "imm" and -2**31 <= b[1] < 2**31:
                enc.alu_ri("cmp", ra, b[1])
            else:
                rb = self.fetch(SCRATCH, b)
                enc.alu_rr("cmp", ra, rb)
            enc.jcc(cc, lbl)
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
            self.fp_from_gpr(w, 0, self.mat(SCRATCH2, a))
            self.fp_from_gpr(w, 1, self.mat(SCRATCH, b))
            enc.fp_alu(w, fop, 0, 1)
            self.fp_to_dst(w, dst, 0)
        elif op == "fneg":
            w, dst, a = ins[1], ins[2], ins[3]
            self.fp_from_gpr(w, 0, self.mat(SCRATCH2, a))
            enc.mov_ri(SCRATCH, 0x8000000000000000 if w == "f64" else 0x80000000)
            self.fp_from_gpr(w, 2, SCRATCH)
            enc.fp_xor(w, 0, 2)
            self.fp_to_dst(w, dst, 0)
        elif op == "fcmpset":
            w, cc, dst, a, b = ins[1], ins[2], ins[3], ins[4], ins[5]
            self.fp_from_gpr(w, 0, self.mat(SCRATCH2, a))
            self.fp_from_gpr(w, 1, self.mat(SCRATCH, b))
            enc.fp_cmp(w, 0, 1)
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
            if kind in ("i2f64", "i2f32"):
                # cvtsi2sd/ss 的源是 GPR，不是 XMM
                enc.cvt(kind, 0, self.mat(SCRATCH2, a))
                self.fp_to_dst("f32" if kind == "i2f32" else "f64", dst, 0)
                return
            if kind in ("f64i", "f32i"):
                self.fp_from_gpr("f64" if kind == "f64i" else "f32", 0, self.mat(SCRATCH2, a))
                enc.cvt(kind, ACC, 0)
                self.commit(dst, ACC)
                return
            self.fp_from_gpr("f32" if kind in ("i2f32", "f32f64") else "f64", 0,
                             self.mat(SCRATCH2, a))
            enc.cvt(kind, 0, 0)
            self.fp_to_dst("f32" if kind in ("i2f32", "f64f32") else "f64", dst, 0)
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
            moves = []
            for i, arg in enumerate(ins[3]):
                moves.append((self.src_move(arg), ("r", ARG_REGS[i])))
            self.parallel_move(moves)
            enc.call(ins[2])
            if ins[1] is not None:
                self.commit(ins[1], ACC)
        elif op == "ret":
            if ins[1] is not None:
                r = self.fetch(ACC, ins[1])
                if r != ACC:
                    enc.mov_rr(ACC, r)
            self.emit_epilogue()
            enc.ret()
        elif op in ("load", "load8"):
            rd = self.safe_dst_reg(ins[1], [ins[2], ins[3]])
            fb = self.fetch(SCRATCH2, ins[2])
            fi = self.fetch(SCRATCH, ins[3])
            target = rd if rd is not None else ACC
            if op == "load":
                enc.mov_rm(target, fb, fi, 3, 0)
            else:
                enc.movzx8_rm(target, fb, fi, 0, 0)
            if rd is None:
                self.commit(ins[1], ACC)
        elif op in ("store", "store8"):
            fb = self.fetch(SCRATCH2, ins[1])
            fi = self.fetch(SCRATCH, ins[2])
            fs = self.fetch(ACC, ins[3])
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
                moves.append((("r", ARG_REGS[i]), self.dst_move(d)))
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
            # 先看 a 是否已经在寄存器里（不搬运）
            if isinstance(src_a, int):
                _k, a_reg = self.alloc.get(src_a, ("m", 0))
            else:
                a_reg = None
            if a_reg is not None and isinstance(src_a, int) \
                    and self.alloc.get(src_a, ("m", 0)) == ("r", rd):
                a_reg = rd                            # a 已驻留 dst 寄存器 -> 零搬运
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
        """Linux _start：对齐栈 -> 调 main -> exit(返回值)"""
        enc = self.enc
        enc.alu_ri("and", RSP, -16)
        enc.call("main")
        enc.mov_rr(RDI, RAX)
        enc.mov_ri(ACC, 60)
        enc.syscall()

    def gen_functions(self):
        enc = self.enc
        for fn in self.fns:
            self.alloc, nslots, self.used_callee = allocate(fn)
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
            rbp_mod = (8 - 8 * (len(self.used_callee) + 1)) % 16
            frame = (nslots + self.frame_words) * 8
            while frame % 16 != rbp_mod:
                frame += 8
            if frame:
                enc.alu_ri("sub", RSP, frame)
            for ins in fn.instrs:
                self.gen_instr(ins)
            # 兜底返回
            self.emit_epilogue()
            enc.ret()

    def gen_all(self):
        self.gen_entry()
        self.gen_functions()
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


def lower_and_optimize(src_path, arch="x86_64", optimize=True, dump_ir=False,
                       platform="linux"):
    """前端共享层：解析 + 降级 + 优化（x86_64 / aarch64 发射层共用）"""
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    cfg = load_config(src_path)
    mod, _imports, fns_ast, tests, structs, enums, _order = parse_source(src)
    fns_ast = with_test_runner(fns_ast, tests)   # test "name" { } -> 测试入口
    low = Lower(fns_ast, cfg, arch=arch, structs=structs, enums=enums,
                platform=platform)
    fns = low.run(fns_ast)
    if optimize:
        # v0.2 管线：内联 -> 逐函数收敛（复制传播 / CSE-GVN / LICM / 循环展开 / DCE）
        opt_inline(fns)
        for fn in fns:
            opt_all(fn, unroll=True)
    if dump_ir:
        for fn in fns:
            print(f"== {fn.name} (vregs={fn.nv}) ==")
            for ins in fn.instrs:
                print("   ", ins)
    return fns, low, cfg


def transpile_native(src_path, dump_ir=False, optimize=True, arch="x86_64"):
    fns, low, cfg = lower_and_optimize(src_path, arch=arch, optimize=optimize, dump_ir=dump_ir)
    cg = Codegen(fns, low.globals)
    blob = cg.gen_all()
    return blob, cfg


def main():
    ap = argparse.ArgumentParser(description="Rosoto 原生后端 (Rosoto -> 裸 ELF64)")
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
    print(f"[rosoto-native] {args.src} -> {out} ({len(blob)} 字节机器码+数据, 无 libc)")
    print(f"[rosoto-native] config: {cfg['_path'] or '(默认)'} | "
          f"multicore={cfg['core']['multicore']} threads={cfg['core']['threads'] or 'auto'}")
    if args.cmd == "run":
        print(f"[rosoto-native] exec {out}")
        os.execv(os.path.abspath(out), [os.path.abspath(out)])


if __name__ == "__main__":
    main()
