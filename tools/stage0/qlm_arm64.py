#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara 原生后端 —— AArch64 发射器 v0.1（平台轨）
================================================
Quelmara -> QuIR（与 x86_64 完全共享）-> 同一套优化 passes / 寄存器分配
      -> 自研 ARM64 指令编码器 -> ELF64 (e_machine=AArch64) 裸可执行文件

移植成本验证：QuIR/优化/分配器 100% 复用，本文件只实现
  ① A64 指令编码器（~30 条原语） ② 发射层 ③ ELF 写出参数
对应 BACKEND.md 平台轨承诺的"每个新平台 = 一个发射器 + 一个格式写出器"。

用法：
  python3 tools/stage0/qlm_arm64.py build examples/fib.qma -o build/fib_a64
  python3 tools/stage0/qlm_arm64.py verify examples/fib.qma   # capstone 反汇编级验证

⚠ 本机无 qemu-aarch64：aarch64 产物的【执行级】验证需 aarch64 主机或 qemu-user；
  当前验证级别 = ELF 结构 + capstone 反汇编 + 关键序列人工核对（见 HANDOVER.md）。
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qlm_native import (lower_and_optimize, allocate, vreg_mentions,  # noqa: E402
                           BASE, ENTRY_OFF, SYSCALLS)

# ---------------------------------------------------------------------------
# AArch64 寄存器约定
# ---------------------------------------------------------------------------
X0, X1, X2, X3, X4, X5, X6, X7 = 0, 1, 2, 3, 4, 5, 6, 7
X8, X9, X10, X11, X12, X13, X14, X15 = 8, 9, 10, 11, 12, 13, 14, 15
X16, X17, X18 = 16, 17, 18
X19, X20, X21, X22, X23, X24, X25, X26 = 19, 20, 21, 22, 23, 24, 25, 26
X27, X28, X29, X30, SP, XZR = 27, 28, 29, 30, 31, 31

POOL_A64 = [X9, X10, X11, X12, X13, X14, X15, X19, X20, X21, X22, X23, X24, X25, X26, X27, X28]
CALLEE_A64 = [X19, X20, X21, X22, X23, X24, X25, X26, X27, X28]
# v1.42：扩到 8 个（SysV AArch64 本就定义 X0-X7 传参；X6/X7 此前闲置）。
# 与 x86-64 后端的"6 寄存器 + 栈传参"不同构——A64 未接栈传参，>8 实参
# 在 call/args 处 fail-fast（irdiff SKIP 如实登记）。
ARG_REGS = [X0, X1, X2, X3, X4, X5, X6, X7]
ACC = X0           # call/syscall 返回值
SCRATCH, SCRATCH2 = X16, X17   # IP0/IP1（约定俗成的编码期临时）

COND = {"e": 0x0, "ne": 0x1, "ge": 0xA, "l": 0xB, "le": 0xD, "g": 0xC,
        # v2.60：无符号比较（越界检查用一条 `b.lo` 覆盖 [0, n)）
        # A64：HS/CS=0x2（unsigned >=）、LO/CC=0x3（unsigned <）、
        #      HI=0x8（unsigned >）、LS=0x9（unsigned <=）
        "b": 0x3, "ae": 0x2, "a": 0x8, "be": 0x9}
INV_COND = {0x0: 0x1, 0x1: 0x0, 0xA: 0xB, 0xB: 0xA, 0xC: 0xD, 0xD: 0xC,
            0x2: 0x3, 0x3: 0x2, 0x8: 0x9, 0x9: 0x8}


# ---------------------------------------------------------------------------
# A64 编码器（32 位定长指令字）
# ---------------------------------------------------------------------------


class EncA64:
    def __init__(self):
        self.words = []
        self.labels = {}
        self.fixups = []     # (word_index, label, kind)  kind: b26 | b19

    def pos(self):
        return len(self.words)

    def emit(self, word):
        self.words.append(word & 0xFFFFFFFF)

    # -- 立即数/搬运 --
    def mov_imm(self, rd, value):
        """MOVZ + 3×MOVK 构造 64 位立即数（固定 4 字窗口，便于全局地址回填）"""
        v = value & (2**64 - 1)
        chunks = [(v >> (16 * h)) & 0xFFFF for h in range(4)]
        self.emit(0xD2800000 | (chunks[0] << 5) | rd)          # MOVZ
        for h in (1, 2, 3):
            self.emit(0xF2800000 | (h << 21) | (chunks[h] << 5) | rd)   # MOVK

    def mov_rr(self, rd, rm):
        self.emit(0xAA000000 | (rm << 16) | (XZR << 5) | rd)   # ORR Xd, XZR, Xm

    # -- 算术 / 逻辑（三操作数，天然别名安全） --
    def add_imm(self, rd, rn, imm12):
        self.emit(0x91000000 | ((imm12 & 0xFFF) << 10) | (rn << 5) | rd)

    def sub_imm(self, rd, rn, imm12):
        self.emit(0xD1000000 | ((imm12 & 0xFFF) << 10) | (rn << 5) | rd)

    def add_rr(self, rd, rn, rm, lsl=0):
        self.emit(0x8B000000 | (rm << 16) | ((lsl & 0x3F) << 10) | (rn << 5) | rd)

    def sub_rr(self, rd, rn, rm):
        self.emit(0xCB000000 | (rm << 16) | (rn << 5) | rd)

    def and_rr(self, rd, rn, rm):
        self.emit(0x8A000000 | (rm << 16) | (rn << 5) | rd)

    def orr(self, rd, rn, rm):
        self.emit(0xAA000000 | (rm << 16) | (rn << 5) | rd)

    def eor(self, rd, rn, rm):
        self.emit(0xCA000000 | (rm << 16) | (rn << 5) | rd)

    def orn(self, rd, rn, rm):        # MVN = ORN XZR
        self.emit(0xAA200000 | (rm << 16) | (rn << 5) | rd)

    def mul(self, rd, rn, rm):        # MADD ...,XZR
        self.emit(0x9B007C00 | (rm << 16) | (rn << 5) | rd)

    def umulh(self, rd, rn, rm):
        self.emit(0x9BC07C00 | (rm << 16) | (rn << 5) | rd)

    def sdiv(self, rd, rn, rm):
        self.emit(0x9AC00C00 | (rm << 16) | (rn << 5) | rd)

    def lslv(self, rd, rn, rm):
        self.emit(0x9AC02000 | (rm << 16) | (rn << 5) | rd)

    def lsrv(self, rd, rn, rm):
        self.emit(0x9AC02400 | (rm << 16) | (rn << 5) | rd)

    def asrv(self, rd, rn, rm):
        self.emit(0x9AC02800 | (rm << 16) | (rn << 5) | rd)

    def lsl_i(self, rd, rn, sh):      # UBFM 立即数移位族
        self.emit(0xD3400000 | (((64 - sh) & 0x3F) << 16) | ((63 - sh) << 10) | (rn << 5) | rd)

    def lsr_i(self, rd, rn, sh):
        self.emit(0xD3400000 | ((sh & 0x3F) << 16) | (63 << 10) | (rn << 5) | rd)

    def asr_i(self, rd, rn, sh):
        self.emit(0x93400000 | ((sh & 0x3F) << 16) | (63 << 10) | (rn << 5) | rd)

    # -- 比较 / 条件 --
    def cmp_rr(self, rn, rm):
        self.emit(0xEB00001F | (rm << 16) | (rn << 5))

    def cmp_imm(self, rn, imm12):
        self.emit(0xF100001F | ((imm12 & 0xFFF) << 10) | (rn << 5))

    def cset(self, rd, cond):         # CSINC Xd, XZR, XZR, inv(cond)
        self.emit(0x9A800400 | (XZR << 16) | (INV_COND[cond] << 12) | (XZR << 5) | rd)

    # -- 访存 --
    def ldr(self, rt, rn, imm):       # [Xn, #imm] 无符号按比例（imm 为 8 的倍数）
        self.emit(0xF9400000 | ((imm // 8) << 10) | (rn << 5) | rt)

    def str_(self, rt, rn, imm):
        self.emit(0xF9000000 | ((imm // 8) << 10) | (rn << 5) | rt)

    def ldur(self, rt, rn, imm9):     # [Xn, #simm9] 非缩放（支持负偏移，栈槽用）
        self.emit(0xF8400000 | ((imm9 & 0x1FF) << 12) | (rn << 5) | rt)

    def stur(self, rt, rn, imm9):
        self.emit(0xF8000000 | ((imm9 & 0x1FF) << 12) | (rn << 5) | rt)

    def ldr_reg(self, rt, rn, rm):    # LDR Xt, [Xn, Xm, LSL #3]
        self.emit(0xF8607800 | (rm << 16) | (rn << 5) | rt)

    def str_reg(self, rt, rn, rm):    # STR Xt, [Xn, Xm, LSL #3]
        self.emit(0xF8207800 | (rm << 16) | (rn << 5) | rt)

    def ldrb_reg(self, rt, rn, rm):   # LDRB Wt, [Xn, Xm]
        self.emit(0x38606800 | (rm << 16) | (rn << 5) | rt)

    def strb_reg(self, rt, rn, rm):   # STRB Wt, [Xn, Xm]
        self.emit(0x38206800 | (rm << 16) | (rn << 5) | rt)

    def stp(self, rt, rt2, rn, imm):  # [Xn, #imm]（imm 8 的倍数）
        self.emit(0xA9000000 | (((imm // 8) & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt)

    def ldp(self, rt, rt2, rn, imm):
        self.emit(0xA9400000 | (((imm // 8) & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt)

    # -- 控制流 --
    def b(self, label):
        self.fixups.append((self.pos(), label, "b26"))
        self.emit(0x14000000)

    def bl(self, label):
        self.fixups.append((self.pos(), label, "b26"))
        self.emit(0x94000000)

    def blr(self, reg):
        # BLR Xn：1101 0110 0011 1111 0000 01 Rn（间接调用，链接返回地址到 x30）
        # 注意与 BR（0xD61F0000，不链接）区分——曾把 BLR 写成 BR 的编码，
        # 返回地址丢失、callr 一返回就跳飞。
        self.emit(0xD63F0000 | ((reg & 31) << 5))

    def csel(self, rd, rn, rm, cond):
        # CSEL Xd, Xn, Xm, cond：sf=1, 0011010100, Rm, cond, 00, Rn, Rd
        self.emit(0x1A800000 | ((rm & 31) << 16) | ((cond & 15) << 12)
                  | ((rn & 31) << 5) | (rd & 31))

    def subs_rr(self, rd, rn, rm):
        # SUBS Xd, Xn, Xm（置标志的减法；cssub 的差与比较一步完成）
        self.emit(0xEB000000 | ((rm & 31) << 16) | ((rn & 31) << 5) | (rd & 31))

    def subs_imm(self, rd, rn, imm12):
        # SUBS Xd, Xn, #imm12
        self.emit(0xF1000000 | ((imm12 & 0xFFF) << 10) | ((rn & 31) << 5)
                  | (rd & 31))

    def bcond(self, cond, label):
        self.fixups.append((self.pos(), label, "b19"))
        self.emit(0x54000000 | cond)

    def cbz(self, rt, label):
        self.fixups.append((self.pos(), label, "b19"))
        self.emit(0xB4000000 | rt)

    def cbnz(self, rt, label):
        self.fixups.append((self.pos(), label, "b19"))
        self.emit(0xB5000000 | rt)

    def ret(self):
        self.emit(0xD65F03C0)         # RET X30

    def svc(self):
        self.emit(0xD4000001)

    def nop(self):
        self.emit(0xD503201F)

    # -- 原子 / 屏障（v1.98：LL-SC 序列 + 屏障，AArch64 无 lock 前缀） --
    # ARMv8.0 只有 LL/SC（LDXR/STXR 家族），没有 x86 那样的单指令 RMW；
    # 因此 atomic_add / cas / xchg 都编成 "LDAXR … STLXR + 失败重试" 循环。
    # 用带 acquire/release 的变体（LD AXR / ST LXR）而不是裸 LDXR/STXR：
    # 前者在一条指令里给足顺序保证，省掉循环外的 DMB。
    def ldaxr(self, rt, rn):
        # LDAXR Xt, [Xn]：1100 1000 0101 1111 1100 00 Rn Rt
        self.emit(0xC85FFC00 | ((rn & 31) << 5) | (rt & 31))

    def stlxr(self, rs, rt, rn):
        # STLXR Ws, Xt, [Xn]：1100 1000 0000 0000 1111 11 Rn Rt
        # Ws = 0 表示独占写成功；非 0 表示监视器已被清（须重试）
        self.emit(0xC800FC00 | ((rs & 31) << 16) | ((rn & 31) << 5) | (rt & 31))

    def ldar(self, rt, rn):
        # LDAR Xt, [Xn]：1100 1000 1101 1111 1100 00 Rn Rt（acquire 读）
        self.emit(0xC8DFFC00 | ((rn & 31) << 5) | (rt & 31))

    def stlr(self, rt, rn):
        # STLR Xt, [Xn]：1100 1000 1001 1111 1100 00 Rn Rt（release 写）
        self.emit(0xC89FFC00 | ((rn & 31) << 5) | (rt & 31))

    def clrex(self):
        self.emit(0xD5033F5F)         # CLREX：放弃独占监视器

    def dmb_ish(self):
        self.emit(0xD5033BBF)         # DMB ISH：全内存屏障（等价 mfence 的域内语义）

    def yield_(self):
        self.emit(0xD503203F)         # YIELD：等价 x86 的 pause（自旋提示）

    def mrs_cntvct(self, rt):
        # MRS Xt, CNTVCT_EL0：虚拟计数器（EL0 可读，Linux 默认开放）
        # now_cycle 的 A64 对应物——单调递增，不保证等于核心周期。
        self.emit(0xD53BE040 | (rt & 31))

    def resolve(self):
        for wi, label, kind in self.fixups:
            target = self.labels[label]
            delta = target - wi
            if kind == "b26":
                self.words[wi] |= delta & 0x3FFFFFF
            else:
                self.words[wi] |= (delta & 0x7FFFF) << 5


# ---------------------------------------------------------------------------
# 发射层（QuIR -> A64）
# ---------------------------------------------------------------------------


class CodegenA64:
    def __init__(self, fns, globals_bytes, low=None):
        self.fns = fns
        self.low = low
        self.globals = globals_bytes
        self.enc = EncA64()
        self.global_fixups = []   # (word_index, gid) —— movz/movk 序列起点
        self.code_fixups = []     # (word_index, fname, reg) —— 函数地址（fnaddr）加载点
        self.vt_fixups = []       # (word_index, fname) —— vtable 槽（8 字节数据）

    # ---- 操作数 ----
    def fetch(self, target, spec):
        if isinstance(spec, int):
            kind, val = self.alloc[spec]
            if kind == "r":
                return val
            self.enc.ldur(target, X29, -val)
            return target
        if spec[0] == "imm":
            self.enc.mov_imm(target, spec[1])
            return target
        if spec[0] == "fnaddr":
            # 函数地址（间接调用目标 / 回调）：mov_imm 占位 + 代码回填
            start = self.enc.pos()
            self.enc.mov_imm(target, 0)                   # 占位 4 字窗口
            self.code_fixups.append((start, spec[1], target))
            return target
        start = self.enc.pos()
        self.enc.mov_imm(target, 0)                       # ('ga', gid)：占位 4 字窗口
        self.global_fixups.append((start, spec[1], target))
        return target

    def commit(self, dst, reg):
        kind, val = self.alloc[dst]
        if kind == "r":
            if val != reg:
                self.enc.mov_rr(val, reg)
        else:
            self.enc.stur(reg, X29, -val)

    def src_move(self, spec):
        if isinstance(spec, int):
            kind, val = self.alloc[spec]
            return (kind, val) if kind == "r" else ("m", val)
        return spec

    def dst_move(self, dst):
        kind, val = self.alloc[dst]
        return ("r", val) if kind == "r" else ("m", val)

    def fetch_fixed(self, reg, spec):
        """取值并保证落在指定寄存器。

        `fetch()` 在操作数已经在分配池寄存器里时直接返回那个寄存器，
        而 LL/SC 序列要求地址、期望值、新值、状态四个操作数互不重叠，
        且不能撞上分配池（池里的值在 IR 指令边界上都是活的）。
        X1..X5 不在 POOL_A64 里，可安全当临时寄存器用。
        """
        r = self.fetch(reg, spec)
        if r != reg:
            self.enc.mov_rr(reg, r)
        return reg

    def enc_label(self, hint):
        """代码段标签名（与 x86 后端的 `Fn.label` 同作用：只求全局唯一）"""
        self.label_id = getattr(self, "label_id", 0) + 1
        return f"__{hint}_{self.label_id}"

    def parallel_move(self, moves):
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
                for i, (src, dst) in enumerate(pending):
                    if src[0] == "r":
                        self.enc.mov_rr(SCRATCH, src[1])
                        pending[i] = (("r", SCRATCH), dst)
                        break
                else:
                    raise RuntimeError("并行搬移无法调度")

    def emit_move(self, src, dst):
        if src[0] == "r":
            if dst[0] == "r":
                if src[1] != dst[1]:
                    self.enc.mov_rr(dst[1], src[1])
            else:
                self.enc.stur(src[1], X29, -dst[1])
        elif src[0] == "m":
            tmp = SCRATCH if dst[0] != "r" else dst[1]
            self.enc.ldur(tmp, X29, -src[1])
            if dst[0] == "m":
                self.enc.stur(tmp, X29, -dst[1])
        elif src[0] == "imm":
            if dst[0] == "r":
                self.enc.mov_imm(dst[1], src[1])
            else:
                self.enc.mov_imm(SCRATCH, src[1])
                self.enc.stur(SCRATCH, X29, -dst[1])
        elif src[0] == "ga":
            target = dst[1] if dst[0] == "r" else SCRATCH
            start = self.enc.pos()
            self.enc.mov_imm(target, 0)
            self.global_fixups.append((start, src[1], target))
            if dst[0] == "m":
                self.enc.stur(SCRATCH, X29, -dst[1])
        elif src[0] == "fnaddr":
            # 函数地址（let 绑定函数名 / 函数名作实参）：mov_imm 占位 +
            # 代码段回填（与 fetch 的 fnaddr 分支同一条修复路径）
            target = dst[1] if dst[0] == "r" else SCRATCH
            start = self.enc.pos()
            self.enc.mov_imm(target, 0)
            self.code_fixups.append((start, src[1], target))
            if dst[0] == "m":
                self.enc.stur(SCRATCH, X29, -dst[1])

    # ---- 指令 ----
    def gen_instr(self, ins):
        enc = self.enc
        op = ins[0]
        if op == "label":
            enc.labels[ins[1]] = enc.pos()
        elif op == "jmp":
            enc.b(ins[1])
        elif op in ("jz", "jnz"):
            r = self.fetch(SCRATCH, ins[1])
            (enc.cbz if op == "jz" else enc.cbnz)(r, ins[2])
        elif op == "jcc":
            cc, a, b, lbl = ins[1], ins[2], ins[3], ins[4]
            ra = self.fetch(SCRATCH2, a)
            if isinstance(b, tuple) and b[0] == "imm" and 0 <= b[1] < 4096:
                enc.cmp_imm(ra, b[1])
            else:
                rb = self.fetch(SCRATCH, b)
                enc.cmp_rr(ra, rb)
            enc.bcond(COND[cc], lbl)
        elif op == "mov":
            self.parallel_move([(self.src_move(ins[2]), self.dst_move(ins[1]))])
        elif op == "bin":
            self.gen_bin(ins)
        elif op == "neg":
            ra = self.fetch(SCRATCH2, ins[2])
            enc.sub_rr(SCRATCH, XZR, ra)
            self.commit(ins[1], SCRATCH)
        elif op == "not":
            ra = self.fetch(SCRATCH2, ins[2])
            enc.orn(SCRATCH, XZR, ra)
            self.commit(ins[1], SCRATCH)
        elif op == "cmpset":
            cc, dst, a, b = ins[1], ins[2], ins[3], ins[4]
            ra = self.fetch(SCRATCH2, a)
            if isinstance(b, tuple) and b[0] == "imm" and 0 <= b[1] < 4096:
                enc.cmp_imm(ra, b[1])
            else:
                rb = self.fetch(SCRATCH, b)
                enc.cmp_rr(ra, rb)
            enc.cset(SCRATCH, COND[cc])
            self.commit(dst, SCRATCH)
        elif op == "call":
            if len(ins[3]) > len(ARG_REGS):
                raise SyntaxError("A64 暂不支持超过 8 个实参（栈传参未接）")
            moves = [(self.src_move(arg), ("r", ARG_REGS[i])) for i, arg in enumerate(ins[3])]
            self.parallel_move(moves)
            enc.bl(ins[2])
            if ins[1] is not None:
                self.commit(ins[1], ACC)
        elif op == "callr":
            # 间接调用（自研 ABI）：函数地址先物化进 SCRATCH2（IP1，不在
            # 分配池），参数进 X0-X7 后 BLR（fnaddr/ga 在 fetch 里回填）。
            if len(ins[3]) > len(ARG_REGS):
                raise SyntaxError("A64 暂不支持超过 8 个实参（栈传参未接）")
            fr = self.fetch(SCRATCH2, ins[2])
            if fr != SCRATCH2:
                self.enc.mov_rr(SCRATCH2, fr)
            moves = [(self.src_move(arg), ("r", ARG_REGS[i])) for i, arg in enumerate(ins[3])]
            self.parallel_move(moves)
            enc.blr(SCRATCH2)
            if ins[1] is not None:
                self.commit(ins[1], ACC)
        elif op == "cssub":
            # dst = (a >= b) ? a - b : a。SUBS 一步出差并置标志，
            # CSEL(GE) 选差或原值——与 x86 的 sub+CMOVns 同构。
            a, b = ins[2], ins[3]
            rb = self.fetch(SCRATCH2, b)
            if rb != SCRATCH2:
                self.enc.mov_rr(SCRATCH2, rb)
            ra = self.fetch(SCRATCH, a)
            if ra != SCRATCH:
                self.enc.mov_rr(SCRATCH, ra)
            if isinstance(b, tuple) and b[0] == "imm" and 0 <= b[1] < 4096:
                self.enc.subs_imm(ACC, SCRATCH, b[1])   # ACC = a - imm，置标志
            else:
                self.enc.subs_rr(ACC, SCRATCH, SCRATCH2)
            self.enc.csel(ACC, ACC, SCRATCH, 10)        # GE 取差，否则取 a
            self.commit(ins[1], ACC)
        elif op == "ret":
            if ins[1] is not None:
                r = self.fetch(SCRATCH, ins[1])
                if r != ACC:
                    enc.mov_rr(ACC, r)
            self.emit_epilogue()
            enc.ret()
        elif op in ("load", "load8"):
            fb = self.fetch(SCRATCH2, ins[2])
            fi = self.fetch(SCRATCH, ins[3])
            if op == "load":
                enc.ldr_reg(ACC, fb, fi)
            else:
                enc.ldrb_reg(ACC, fb, fi)
            self.commit(ins[1], ACC)
        elif op in ("store", "store8"):
            fb = self.fetch(SCRATCH2, ins[1])
            fi = self.fetch(SCRATCH, ins[2])
            fs = self.fetch(ACC, ins[3])
            if op == "store":
                enc.str_reg(fs, fb, fi)
            else:
                enc.strb_reg(fs, fb, fi)
        elif op == "movaddr":
            kind, val = self.alloc[ins[1]]
            target = val if kind == "r" else SCRATCH
            start = enc.pos()
            enc.mov_imm(target, 0)
            self.global_fixups.append((start, ins[2], target))
            if kind == "m":
                enc.stur(SCRATCH, X29, -val)
        elif op == "frameaddr":
            # dst = &帧上结构体区[word]（x29 = 帧顶，槽位 [x29-8k]）
            # 字序号递增 == 地址递增，与 load/store 的 [base+idx*8] 一致（见 x86 同名注释）
            kind, val = self.alloc[ins[1]]
            target = val if kind == "r" else SCRATCH
            disp = 8 * (self.nslots + self.frame_words - ins[2])
            enc.mov_imm(SCRATCH2, disp)
            enc.sub_rr(target, X29, SCRATCH2)
            if kind == "m":
                enc.stur(SCRATCH, X29, -val)
        elif op == "syscall":
            dst, num, args = ins[1], ins[2], ins[3]
            moves = [(self.src_move(a), ("r", ARG_REGS[i])) for i, a in enumerate(args) if i < 6]
            self.parallel_move(moves)
            enc.mov_imm(X8, num)          # aarch64：系统调用号在 x8
            enc.svc()
            if dst is not None:
                self.commit(dst, ACC)
        elif op == "args":
            if len(ins[1]) > len(ARG_REGS):
                raise SyntaxError("A64 暂不支持超过 8 个形参（栈传参未接）")
            moves = [(("r", ARG_REGS[i]), self.dst_move(d)) for i, d in enumerate(ins[1])]
            self.parallel_move(moves)
        elif op == "xchg":
            # mem_xchg(addr, val) -> old：LL/SC 交换。
            # 与 x86 的 `xchg [m], r` 语义相同（返回旧值），只是没有单指令形式。
            dst, addr, val = ins[1], ins[2], ins[3]
            ra = self.fetch_fixed(SCRATCH2, addr)      # X17 = 地址
            rv = self.fetch_fixed(X1, val)             # X1  = 新值
            l_retry = self.enc_label("xchg")
            enc.labels[l_retry] = enc.pos()
            enc.ldaxr(ACC, ra)                         # ACC = 旧值 + 抢监视器
            enc.stlxr(X2, rv, ra)                      # W2 = 0 成功 / 非 0 重试
            enc.cbnz(X2, l_retry)
            if dst is not None:
                self.commit(dst, ACC)
        elif op == "atomic":
            # ('atomic', sub, dst, addr, a[, b])（v1.98 A64 版本）
            #   add -> dst = 旧值；*addr += a
            #   cas -> dst = 旧值；*addr == a 时 *addr = b
            # 语义与 x86 的 lock xadd / lock cmpxchg 逐位一致（含 64 位回绕），
            # 差别只在实现：ARMv8.0 没有单指令 RMW，必须 LL/SC 重试。
            sub, dst, addr = ins[1], ins[2], ins[3]
            ra = self.fetch_fixed(SCRATCH2, addr)      # X17 = 地址
            if sub == "add":
                rv = self.fetch_fixed(X1, ins[4])      # X1 = 加数
                l_retry = self.enc_label("aadd")
                enc.labels[l_retry] = enc.pos()
                enc.ldaxr(ACC, ra)
                enc.add_rr(X2, ACC, rv)
                enc.stlxr(X3, X2, ra)
                enc.cbnz(X3, l_retry)
                if dst is not None:
                    self.commit(dst, ACC)
            elif sub == "cas":
                rexp = self.fetch_fixed(X1, ins[4])    # X1 = 期望值
                rnew = self.fetch_fixed(X2, ins[5])    # X2 = 新值
                l_retry = self.enc_label("acas")
                l_done = self.enc_label("acasd")
                enc.labels[l_retry] = enc.pos()
                enc.ldaxr(ACC, ra)                     # ACC = 旧值
                enc.cmp_rr(ACC, rexp)
                enc.bcond(COND["ne"], l_done)          # 不等：不写，直接返回旧值
                enc.stlxr(X3, rnew, ra)
                enc.cbnz(X3, l_retry)                  # 独占写失败：重读重试
                enc.labels[l_done] = enc.pos()
                enc.clrex()                            # 放弃监视器（相等失败路径也要放）
                if dst is not None:
                    self.commit(dst, ACC)
            else:
                raise SyntaxError(f"A64 atomic 未知子操作 {sub}")
        elif op == "ldar":
            # acquire 读：LDAR 一条指令给足顺序（x86 那边是同形的 mov）
            ra = self.fetch_fixed(SCRATCH2, ins[2])
            enc.ldar(ACC, ra)
            self.commit(ins[1], ACC)
        elif op == "stlr":
            # release 写：STLR（x86 那边是同形的 mov）
            ra = self.fetch_fixed(SCRATCH2, ins[1])
            rv = self.fetch_fixed(X1, ins[2])
            enc.stlr(rv, ra)
        elif op == "mfence":
            enc.dmb_ish()
        elif op == "pause":
            enc.yield_()
        elif op == "rdtsc":
            # now_cycle() -> 虚拟计数器（CNTVCT_EL0）。与 x86 的 rdtsc 一样
            # 只保证单调，不保证等于核心周期——微基准里读两次取差即可。
            enc.mrs_cntvct(ACC)
            self.commit(ins[1], ACC)
        else:
            raise SyntaxError(f"A64 无法发射 {ins!r}")

    def gen_bin(self, ins):
        enc = self.enc
        _, kind, dst, a, b = ins
        ra = self.fetch(SCRATCH2, a)
        if kind in ("add", "sub") and isinstance(b, tuple) and b[0] == "imm" and 0 <= b[1] < 4096:
            (enc.add_imm if kind == "add" else enc.sub_imm)(SCRATCH, ra, b[1])
        elif kind in ("and", "or", "xor", "add", "sub"):
            rb = self.fetch(SCRATCH, b)
            {"and": enc.and_rr, "or": enc.orr, "xor": enc.eor,
             "add": enc.add_rr, "sub": enc.sub_rr}[kind](SCRATCH, ra, rb)
        elif kind == "mul":
            rb = self.fetch(SCRATCH, b)
            enc.mul(SCRATCH, ra, rb)
        elif kind == "umulhi":
            rb = self.fetch(SCRATCH, b)
            enc.umulh(SCRATCH, ra, rb)
        elif kind == "div":
            rb = self.fetch(SCRATCH, b)
            enc.sdiv(SCRATCH, ra, rb)
        elif kind == "mod":
            rb = self.fetch(SCRATCH, b)
            enc.sdiv(ACC, ra, rb)              # q = a / b -> x0（避开 scratch 复用）
            enc.mul(ACC, ACC, rb)              # q*b（除数保持完好）
            enc.sub_rr(SCRATCH, ra, ACC)       # a - q*b
        elif kind in ("shl", "shr", "sar"):
            if isinstance(b, tuple) and b[0] == "imm":
                sh = b[1] & 63
                {"shl": enc.lsl_i, "shr": enc.lsr_i, "sar": enc.asr_i}[kind](SCRATCH, ra, sh)
            else:
                rb = self.fetch(SCRATCH, b)
                {"shl": enc.lslv, "shr": enc.lsrv, "sar": enc.asrv}[kind](SCRATCH, ra, rb)
        else:
            raise SyntaxError(f"A64 未知二元运算 {kind}")
        self.commit(dst, SCRATCH)

    def emit_prologue(self, used_callee, nslots, frame_words=0):
        enc = self.enc
        self.saved_top = 16 + 8 * len(used_callee)
        self.frame_words = frame_words
        total = self.saved_top + 8 * (nslots + frame_words)
        total = (total + 15) & ~15
        self.frame_total = total
        enc.sub_imm(SP, SP, total)
        enc.stp(X29, X30, SP, 0)
        for k, r in enumerate(used_callee):
            enc.str_(r, SP, 16 + 8 * k)
        enc.add_imm(X29, SP, total)      # x29 = 帧顶；栈槽 [x29, #-8*(i+1)]

    def emit_epilogue(self):
        enc = self.enc
        enc.ldp(X29, X30, SP, 0)
        for k, r in enumerate(self.used_callee):
            enc.ldr(r, SP, 16 + 8 * k)
        enc.add_imm(SP, SP, self.frame_total)

    # ---- 整体 ----
    def gen_all(self):
        enc = self.enc
        # interface 动态分发（v1.81）：vtable 与 x86_64 同构——代码段尾部
        # 一张函数指针表，每槽 8 字节；派发走 callr（BLR）。表项用
        # vt_fixups 在收尾时按函数标签回填绝对地址。
        # _start：先保存内核栈上的 argc/argv（若程序用到 args()），再 BL main
        if self.low is not None and getattr(self.low, "uses_args", False):
            enc.ldr(X0, SP, 0)          # x0 = [sp] = argc
            enc.add_imm(X1, SP, 8)      # x1 = &argv[0]
            enc.bl("__qlm_args_boot")
        enc.bl("main")
        enc.mov_imm(X8, SYSCALLS["aarch64"]["exit"])
        enc.svc()

        for fn in self.fns:
            (self.alloc, nslots, self.used_callee,
             self.used_xcallee) = allocate(fn, pool=POOL_A64,
                                           callee_saved=CALLEE_A64)
            self.nslots = nslots
            enc.labels[fn.name] = enc.pos()
            self.emit_prologue(self.used_callee, nslots, getattr(fn, "frame_words", 0))
            for ins in fn.instrs:
                self.gen_instr(ins)
            self.emit_epilogue()
            enc.ret()

        # ---- vtable（v1.81）----
        for (iname, tname), fnames in sorted(
                (getattr(self.low, "vtables", None) or {}).items()):
            enc.labels[f"__vt_{iname}__{tname}"] = enc.pos()
            for fname in fnames:
                self.vt_fixups.append((enc.pos(), fname))
                enc.emit(0)      # 低 32 位
                enc.emit(0)      # 高 32 位（一个槽 = 8 字节地址）

        enc.resolve()
        blob = bytearray()
        for w in enc.words:
            blob += struct.pack("<I", w)
        code_len = len(blob)
        for patch, gid, rd in self.global_fixups:
            off = sum(len(g) for g in self.globals[:gid])
            addr = BASE + ENTRY_OFF + code_len + off
            # 重写 movz/movk 占位（固定 4 字窗口）
            v = addr
            chunks = [(v >> (16 * h)) & 0xFFFF for h in range(4)]
            words = [0xD2800000 | (chunks[0] << 5) | rd]
            for h in (1, 2, 3):
                words.append(0xF2800000 | (h << 21) | (chunks[h] << 5) | rd)
            for i, w in enumerate(words):
                struct.pack_into("<I", blob, (patch + i) * 4, w)   # patch 为字索引
        for patch, fname, rd in self.code_fixups:
            # 函数地址 = 代码段基址 + 标签偏移（label 为字索引）
            addr = BASE + ENTRY_OFF + enc.labels[fname] * 4
            v = addr
            chunks = [(v >> (16 * h)) & 0xFFFF for h in range(4)]
            words = [0xD2800000 | (chunks[0] << 5) | rd]
            for h in (1, 2, 3):
                words.append(0xF2800000 | (h << 21) | (chunks[h] << 5) | rd)
            for i, w in enumerate(words):
                struct.pack_into("<I", blob, (patch + i) * 4, w)   # patch 为字索引
        for patch, fname in self.vt_fixups:
            # vtable 槽：两个 32 位字 = 一个 64 位绝对地址（小端）
            addr = BASE + ENTRY_OFF + enc.labels[fname] * 4
            struct.pack_into("<I", blob, patch * 4, addr & 0xFFFFFFFF)
            struct.pack_into("<I", blob, (patch + 1) * 4,
                             (addr >> 32) & 0xFFFFFFFF)
        for g in self.globals:
            blob += g
        return bytes(blob)


# ---------------------------------------------------------------------------
# ELF64 (AArch64)
# ---------------------------------------------------------------------------


def write_elf_a64(path, blob):
    total = ENTRY_OFF + len(blob)
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    ehdr = ident + struct.pack("<HHIQQQIHHHHHH",
                               2, 0xB7, 1, BASE + ENTRY_OFF, 64, 0, 0,
                               64, 56, 1, 0, 0, 0)     # e_machine=183 (AArch64)
    phdr = struct.pack("<IIQQQQQQ", 1, 7, 0, BASE, BASE, total, total, 0x1000)
    with open(path, "wb") as f:
        f.write(ehdr + phdr + blob)
    os.chmod(path, 0o755)


def transpile_a64(src_path, dump_ir=False, optimize=True):
    fns, low, cfg = lower_and_optimize(src_path, arch="aarch64", optimize=optimize, dump_ir=dump_ir)
    cg = CodegenA64(fns, low.globals, low=low)
    return cg.gen_all(), cfg


def verify_disasm(blob, limit=40):
    """capstone 反汇编级验证"""
    try:
        import capstone
    except ImportError:
        print("  (未安装 capstone，跳过反汇编验证)")
        return False
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    count = 0
    for i in md.disasm(blob[:min(len(blob), 4096)], BASE + ENTRY_OFF):
        print(f"    0x{i.address:x}:\t{i.mnemonic}\t{i.op_str}")
        count += 1
        if count >= limit:
            break
    return count > 0


def main():
    ap = argparse.ArgumentParser(description="Quelmara 原生后端 AArch64 发射器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("build", "verify"):
        p = sub.add_parser(c)
        p.add_argument("src")
        p.add_argument("-o", "--out", default=None)
        p.add_argument("--dump-ir", action="store_true")
        p.add_argument("--no-opt", action="store_true")
        p.add_argument("--disasm", type=int, default=40)
    args = ap.parse_args()

    blob, cfg = transpile_a64(args.src, dump_ir=args.dump_ir, optimize=not args.no_opt)
    base = os.path.splitext(os.path.basename(args.src))[0]
    out = args.out or os.path.join("build", base + "_a64")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    write_elf_a64(out, blob)
    print(f"[qlm-a64] {args.src} -> {out} ({len(blob)} 字节, AArch64 ELF, 无 libc)")
    print(f"[qlm-a64] config: {cfg['_path'] or '(默认)'}")
    if args.cmd == "verify":
        print(f"[qlm-a64] 反汇编前 {args.disasm} 条指令：")
        verify_disasm(blob, limit=args.disasm)


if __name__ == "__main__":
    main()
