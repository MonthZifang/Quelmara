#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara RosIR 优化器 v0.2(后端无关)
====================================
x86_64 / AArch64 / 未来的 PE·Mach-O 发射层共享的 RosIR 级优化 passes:

  opt_copy_prop    复制传播(仅限单定义 vreg)
  opt_cse          公共子表达式消除(基本块内 GVN,含交换律规范化)
  opt_licm         循环不变量外提(只外提"绝不陷入"的纯运算 → 零投机风险)
  opt_loop_unroll  循环展开(编译期常量步长 1 循环,无守卫展开)
  opt_dce          死代码消除(全局使用集 + 不动点,兼容循环回边)
  run_pipeline     统一入口(内联 → LICM → CSE → 展开 → 收敛)

设计约束(重要):RosIR 是**非 SSA**的--同一 vreg 可被多次定义、变量原地更新、
没有 phi。因此每个 pass 都必须对"vreg 多次定义"保守处理,否则会把
循环携带的值错误地当成不变量(BACKEND.md §6 已记录过同类事故)。

LICM 的安全性论证:
  只外提 add/sub/mul/and/or/xor/shl/shr/sar/umulhi/neg/not/cmpset/mov/movaddr
  这些整数运算在 x86-64 / A64 上**永不陷入**(移位计数已掩码、无除零、无访存),
  因此即使循环体一次都没执行,把它们提到循环外也**不会引入新的崩溃**。
  div/mod/load/store/call/syscall 一律不外提。
"""

# ---------------------------------------------------------------------------
# IR 形状(与 qlm_native.py 的注释保持一致)
#   ('mov', dst, src)                src: vreg | ('imm',n) | ('ga',gid)
#   ('bin', op, dst, a, b)           op: add sub mul div mod and or xor shl shr sar umulhi
#   ('neg'/'not', dst, a)
#   ('cmpset', cc, dst, a, b)
#   ('label', L) ('jmp', L) ('jz', a, L) ('jnz', a, L) ('jcc', cc, a, b, L)
#   ('call', dst|None, fname, [args]) ('ret', op|None)
#   ('load'/'load8', dst, base, idx) ('store'/'store8', base, idx, src)
#   ('movaddr', dst, gid) ('frameaddr', dst, word)
#   ('syscall', dst|None, num, [6 args]) ('winapi', dst|None, name, [args])
#   ('args', [dsts]) ('winargs', [dsts])
# ---------------------------------------------------------------------------

BRANCHES = ("jmp", "jz", "jnz", "jcc", "ret")
COMMUTATIVE = ("add", "mul", "and", "or", "xor")
# 绝不陷入的纯运算:可被投机执行(LICM 安全集)
NON_TRAPPING = ("add", "sub", "mul", "and", "or", "xor", "shl", "shr", "sar", "umulhi")
PURE = {"mov", "bin", "neg", "not", "cmpset", "load", "load8", "movaddr", "frameaddr",
        "fbin", "fneg", "fcmpset", "fcvt"}


def vreg_mentions(ins):
    """返回 (defs, uses) 中的 vreg 列表"""
    def ints(xs):
        return [x for x in xs if isinstance(x, int)]

    op = ins[0]
    if op == "mov":
        return [ins[1]], ints([ins[2]])
    if op == "bin":
        return [ins[2]], ints([ins[3], ins[4]])
    if op == "fbin":
        return [ins[3]], ints([ins[4], ins[5]])
    if op == "fneg":
        return [ins[2]], ints([ins[3]])
    if op == "fcmpset":
        return [ins[3]], ints([ins[4], ins[5]])
    if op == "fcvt":
        return [ins[2]], ints([ins[3]])
    if op in ("neg", "not"):
        return [ins[1]], ints([ins[2]])
    if op == "cmpset":
        return [ins[2]], ints([ins[3], ins[4]])
    if op in ("label", "jmp"):
        return [], []
    if op in ("jz", "jnz"):
        return [], ints([ins[1]])
    if op == "jcc":
        return [], ints([ins[2], ins[3]])
    if op == "call":
        return ints([ins[1]]), ints(ins[3])
    if op == "ret":
        return [], ints([ins[1]])
    if op in ("load", "load8"):
        return [ins[1]], ints([ins[2], ins[3]])
    if op in ("store", "store8"):
        return [], ints([ins[1], ins[2], ins[3]])
    if op == "movaddr":
        return [ins[1]], []
    if op == "frameaddr":
        return [ins[1]], []
    if op == "syscall":
        return ints([ins[1]]), ints(ins[3])
    if op == "winapi":
        return ints([ins[1]]), ints(ins[3])
    if op == "args":
        return list(ins[1]), []
    if op == "winargs":
        return list(ins[1]), []
    if op == "spawn_child":
        return [], []
    if op == "xchg":
        return [ins[1]], ints([ins[2], ins[3]])
    raise SyntaxError(f"未知指令 {ins!r}")


def _ints(xs):
    return [x for x in xs if isinstance(x, int)]


# ---------------------------------------------------------------------------
# 循环分析:回边识别自然循环
#   编译器生成的循环形态固定为
#       L:  <guard>            <- 循环头
#           <body>
#           <induction step>
#           jmp L              <- 回边
#       End:
#   因此"自然循环"= [循环头标签下标, 回边下标] 的闭区间。
# ---------------------------------------------------------------------------


def label_index(fn):
    """{label 名: 指令下标}"""
    return {ins[1]: i for i, ins in enumerate(fn.instrs) if ins[0] == "label"}


def loop_regions(fn):
    """返回 [(h, b, lab)]:h=循环头下标,b=回边下标,lab=循环头标签"""
    labs = label_index(fn)
    out = []
    for i, ins in enumerate(fn.instrs):
        if ins[0] == "jmp" and ins[1] in labs:
            h = labs[ins[1]]
            if h < i:                      # 向后跳 = 回边
                out.append((h, i, ins[1]))
    out.sort()
    return out


# ---------------------------------------------------------------------------
# LICM:循环不变量外提
# ---------------------------------------------------------------------------

LICM_SAFE = {"mov", "neg", "not", "cmpset", "movaddr"}


def _licm_safe(ins):
    if ins[0] in LICM_SAFE:
        return True
    return ins[0] == "bin" and ins[1] in NON_TRAPPING


def opt_licm(fn, rounds=3):
    """把循环不变量提到循环头之前。只外提不陷入的纯运算(见模块头论证)。

    保守条件(缺一不可):
      1. 操作数全部在循环外定义;
      2. 目标 vreg 在**整个函数**内只被本条指令定义一次
         (否则循环零次迭代时,循环后的读取会拿到与原语义不同的值);
      3. 目标 vreg 在循环内不能在本指令之前被读。
    """
    for _ in range(rounds):
        moved_any = False
        fn_defs = {}
        for ins in fn.instrs:
            d, _ = vreg_mentions(ins)
            for x in d:
                fn_defs[x] = fn_defs.get(x, 0) + 1
        for (h, b, lab) in loop_regions(fn):
            region = fn.instrs[h:b + 1]
            defs_in_loop = set()
            use_pos = {}
            for off, ins in enumerate(region):
                d, u = vreg_mentions(ins)
                defs_in_loop.update(d)
                for x in u:
                    use_pos.setdefault(x, []).append(off)

            hoist_offs = []
            for off in range(1, len(region) - 1):     # 跳过循环头标签与回边
                ins = region[off]
                if not _licm_safe(ins):
                    continue
                d, u = vreg_mentions(ins)
                if not d:
                    continue
                if any(x in defs_in_loop for x in u):
                    continue
                if any(fn_defs.get(x, 0) != 1 for x in d):
                    continue
                if any(x in use_pos and min(use_pos[x]) < off for x in d):
                    continue
                hoist_offs.append(off)

            if not hoist_offs:
                continue

            # 2) 重建指令流:把选中的指令搬到循环头标签之前
            hoist = set(hoist_offs)
            kept = [region[off] for off in range(len(region)) if off not in hoist]
            picked = [region[off] for off in hoist_offs]
            fn.instrs = fn.instrs[:h] + picked + kept + fn.instrs[b + 1:]
            moved_any = True
            break          # 下标已失效,重新扫描
        if not moved_any:
            break
    return fn


# ---------------------------------------------------------------------------
# CSE / GVN:基本块内公共子表达式消除
# ---------------------------------------------------------------------------


def _cse_key(ins):
    """表达式规范化:交换律运算把操作数排序,消除 (a+b) 与 (b+a) 的差异"""
    op = ins[0]
    if op == "bin" and ins[1] in COMMUTATIVE:
        a, b = ins[3], ins[4]
        if repr(a) > repr(b):
            a, b = b, a
        return ("bin", ins[1], a, b)
    if op in ("mov", "neg", "not", "cmpset", "load", "load8", "movaddr"):
        return ins
    return None


def opt_cse(fn):
    """基本块内 GVN:纯表达式重复计算 -> mov。跨越副作用/控制流即失效。

    ⚠ RosIR 非 SSA,同一个 vreg 会被重新赋值(例如 `acc = acc + x` 的 acc)。
    因此只要某个 vreg 被重定义,不仅要作废"结果是它"的缓存,
    还要作废**所有把它当操作数**的缓存 -- 否则会把新值误当成旧表达式的结果。
    (这条规则由 parfor_sum 的回归测试接入后发现,见 BACKEND.md 教训记录。)
    """
    table = {}          # key -> vreg
    new = []
    for ins in fn.instrs:
        op = ins[0]
        if op in BRANCHES or op in ("label", "args", "call", "syscall",
                                    "store", "store8"):
            table.clear()
            new.append(ins)
            continue

        d, u = vreg_mentions(ins)
        if d:
            killed = set(d)
            for k in [k for k, v in table.items()
                      if v in killed or _key_uses(k) & killed]:
                del table[k]

        key = _cse_key(ins)
        if key is not None and key in table:
            prev = table[key]
            if prev != ins[1]:
                new.append(("mov", ins[1], prev))
            else:
                new.append(ins)
            continue

        if key is not None:
            table[key] = ins[1]
        new.append(ins)

    fn.instrs = new
    return fn


def _key_uses(key):
    """CSE 键里出现的 vreg 集合（用于失效判断）。

    保守地把键里所有 int 都当成 vreg——多作废只是损失优化机会，
    绝不会错。真正的替换走 _subst_vregs（位置精确）。
    """
    out = set()
    stack = list(key)
    while stack:
        x = stack.pop()
        if isinstance(x, int):
            out.add(x)
        elif isinstance(x, (tuple, list)):
            stack.extend(x)
    return out


# ---------------------------------------------------------------------------
# 循环展开(编译期常量步长 1 的规范 for 循环,无守卫展开)
# ---------------------------------------------------------------------------


def _is_imm(x, v=None):
    return isinstance(x, tuple) and x[0] == "imm" and (v is None or x[1] == v)


def _loop_shape(fn, h, b, lab):
    """识别规范循环形态,返回 (guard, body, step, exit_label) 或 None。

    lower_for 生成(条件假时退出):
        L: jcc cc i hi, End ; body ; i+=1 ; jmp L ; End:
    lower_while 生成(条件真时进体):
        L: jcc cc i hi, Body ; jmp End ; label Body ; body ; i+=1 ; jmp L ; End:
    两种都要支持,否则 for/while 只有一半能展开。
    返回 (guard, body, step_ins, exit_label, is_while_shape)。
    """
    ins = fn.instrs
    if ins[h][0] != "label" or b - 1 <= h + 1:
        return None
    guard = ins[h + 1]
    if guard[0] != "jcc":
        return None
    ivar = guard[2]

    # 归纳步长两种降级形态:
    #   S1  ('bin','add', i, i, ('imm',1))
    #   S2  ('bin','add', tmp, i, ('imm',1)) ; ('mov', i, tmp)
    tail = ins[b - 1]
    if (tail[0] == "bin" and tail[1] == "add" and tail[2] == ivar
            and tail[3] == ivar and _is_imm(tail[4], 1)):
        step_ins, body_end = [tail], b - 1
    elif (b - 2 > h and tail[0] == "mov" and tail[1] == ivar
          and isinstance(tail[2], int)):
        p = ins[b - 2]
        if (p[0] == "bin" and p[1] == "add" and p[2] == tail[2]
                and p[3] == ivar and _is_imm(p[4], 1)):
            step_ins, body_end = [p, tail], b - 2
        else:
            return None
    else:
        return None

    # 形态 B:guard 跳进循环体,紧跟着一条跳出的 jmp
    if (ins[h + 2][0] == "jmp" and ins[h + 3][0] == "label"
            and ins[h + 3][1] == guard[4]):
        body = ins[h + 4:body_end]
        return guard, body, step_ins, ins[h + 2][1], True
    body = ins[h + 2:body_end]
    return guard, body, step_ins, guard[4], False


def opt_loop_unroll(fn, factor=4, max_body=64, min_trip=1024, rounds=2):
    """展开 `for i in lo..hi` / `while i < n`(lo/hi 编译期常量且 (hi-lo) % factor == 0)。

    展开后每次回边执行 factor 个原迭代体,回边开销降为 1/factor。
    只在**整除**时展开 => 无需尾部守卫,语义与原循环严格等价。

    min_trip:只展开长循环。小循环(如 heavy() 里 40 次的内层)展开后
    代码体积变大反而走 1-cache,实测变慢;长循环才能摊掉体积成本。
    """
    for _ in range(rounds):
        changed = False
        for (h, b, lab) in loop_regions(fn):
            shape = _loop_shape(fn, h, b, lab)
            if shape is None:
                continue
            guard, body, step_ins, exit_label, is_while = shape
            ivar, hi = guard[2], guard[3]
            if not body or len(body) > max_body:
                continue

            # 前置块里的编译期常量:ivar 初值 lo、上界 hi
            # (lower_for 会生成 `mov hi_v, ('imm',N)`,因此 hi 常常是 vreg 而非字面量)
            consts = {}
            for j in range(h - 1, max(-1, h - 60), -1):
                p = fn.instrs[j]
                if p[0] == "mov" and isinstance(p[2], tuple) and p[2][0] == "imm":
                    consts.setdefault(p[1], p[2][1])
                elif p[0] in BRANCHES or p[0] == "label":
                    break
            lo = consts.get(ivar)
            hi_v = hi[1] if _is_imm(hi) else consts.get(hi)
            if lo is None or hi_v is None:
                continue

            trip = hi_v - lo
            if trip <= 0 or trip % factor != 0 or trip < max(factor, min_trip):
                continue

            # 归纳变量在体内不能被重定义;体内不能有跳回循环头的 continue
            bad = False
            for p in body:
                d, _ = vreg_mentions(p)
                if ivar in d:
                    bad = True
                    break
                if p[0] in ("jmp", "jz", "jnz", "jcc") and p[-1] == lab:
                    bad = True
                    break
            if bad:
                continue

            # 重建:循环头 + guard + factor 份 (body, step) + 回边 + End
            rebuilt = [("label", lab), guard]
            if is_while:                       # 形态 B 需要保留 `jmp End ; label Body`
                rebuilt.append(("jmp", exit_label))
                rebuilt.append(("label", guard[4]))
            for c in range(factor):
                if c == 0:
                    rebuilt.extend(body)
                else:
                    rebuilt.append(("__renameset__", f".u{c}"))
                    rebuilt.extend(body)
                rebuilt.extend(step_ins)
            rebuilt.append(("__renameset__", ""))      # 复位:回边/出口标签不改名
            rebuilt.append(("jmp", lab))
            rebuilt.append(("label", exit_label))
            rebuilt = _apply_rename(rebuilt)
            fn.instrs = fn.instrs[:h] + rebuilt + fn.instrs[b + 2:]
            changed = True
            break
        if not changed:
            break
    return fn


def _apply_rename(instrs):
    """按嵌入的 ('__renameset__', suffix) 标记给后续 label/跳转改名"""
    out = []
    suffix = ""
    for ins in instrs:
        if ins[0] == "__renameset__":
            suffix = ins[1]
            continue
        if not suffix:
            out.append(ins)
            continue
        op = ins[0]
        if op == "label":
            out.append(("label", ins[1] + suffix))
        elif op == "jmp":
            out.append(("jmp", ins[1] + suffix))
        elif op in ("jz", "jnz"):
            out.append((op, ins[1], ins[2] + suffix))
        elif op == "jcc":
            out.append(("jcc", ins[1], ins[2], ins[3], ins[4] + suffix))
        else:
            out.append(ins)
    return out


# ---------------------------------------------------------------------------
# 归纳变量强度削减：循环内 `t = i * C` -> 循环外 t = i0*C，循环内 t += C*S
#
# gcc 在 loop_sum 上比我们快的头号原因就是这个：`i * 7` 被换成一个
# 独立归纳变量，每迭代只加 7，热循环里乘法彻底消失。
# ---------------------------------------------------------------------------
_CF_OPS = ("label", "jmp", "jz", "jnz", "jcc", "ret")


def opt_strength_reduce(fn, rounds=3):
    """把热循环里的 `t = ivar * C` 削减成独立归纳变量。

    前提（保守，宁可漏掉也不错）：
      * 循环体是直线代码（无标签/跳转）——保证 mul 每次迭代都执行
      * ivar / t 不在体内被重定义
      * mul 的一个操作数是 ivar，另一个是编译期常量 C
      * t 在循环外不被使用（否则循环后的值会从"末迭代值"变成"下一步值"）
    """
    for _ in range(rounds):
        changed = False
        for (h, b, lab) in loop_regions(fn):
            shape = _loop_shape(fn, h, b, lab)
            if shape is None:
                continue
            guard, _body, step_ins, _ex, is_while = shape
            ivar = guard[2]
            step = None
            for p in step_ins:
                # 两种降级形态：
                #   S1 ('bin','add', ivar, ivar, ('imm',S))
                #   S2 ('bin','add', tmp, ivar, ('imm',S)) ; ('mov', ivar, tmp)
                if (p[0] == "bin" and p[1] == "add" and p[3] == ivar
                        and _is_imm(p[4])):
                    step = p[4][1]
            if step is None or step <= 0:
                continue

            body_start = h + 4 if is_while else h + 2
            body_end = b - len(step_ins)
            ins = fn.instrs

            # 编译期常量：归纳变量初值 lo、循环上界 hi（与 opt_loop_unroll 同源）
            consts = {}
            for j in range(h - 1, max(-1, h - 60), -1):
                q = fn.instrs[j]
                if q[0] == "mov" and isinstance(q[2], tuple) and q[2][0] == "imm":
                    consts.setdefault(q[1], q[2][1])
                elif q[0] in ("label", "jmp", "jz", "jnz", "jcc"):
                    break
            lo = consts.get(ivar)
            hi_v = guard[3][1] if _is_imm(guard[3]) else consts.get(guard[3])

            mul_idx = mul_dst = None
            mul_c = 0
            bad = False
            for j in range(body_start, body_end):
                p = ins[j]
                if p[0] in _CF_OPS:            # 体内出现控制流 -> 非直线，不碰
                    bad = True
                    break
                if p[0] == "bin" and p[1] == "mul":
                    if p[3] == ivar and _is_imm(p[4]):
                        mul_idx, mul_dst, mul_c = j, p[2], p[4][1]
                    elif p[4] == ivar and _is_imm(p[3]):
                        mul_idx, mul_dst, mul_c = j, p[2], p[3][1]
                if p[0] == "bin" and p[2] == ivar:
                    bad = True                 # ivar 在体内被重定义
                    break
            if bad or mul_idx is None or mul_dst == ivar:
                continue
            if abs(mul_c * step) >= 2 ** 62:
                continue
            # t 不能在体内被别的指令重定义
            if any(mul_dst in vreg_mentions(ins[j])[0]
                   for j in range(body_start, body_end) if j != mul_idx):
                continue
            # t 在循环外不能被使用（否则循环后的值语义会变）
            outside = ins[:h] + ins[b + 1:]
            if any(mul_dst in vreg_mentions(p)[1] for p in outside):
                continue
            # 体内不能有跳回循环头的 continue（否则增量会被跳过）
            if any(p[0] in ("jmp", "jz", "jnz", "jcc") and p[-1] == lab
                   for p in ins[body_start:b]):
                continue

            # ---- 重建 ----
            new = ins[:mul_idx] + ins[mul_idx + 1:]        # 删掉 mul（b 左移 1）
            inc = ("bin", "add", mul_dst, mul_dst, ("imm", mul_c * step))
            pre = ("bin", "mul", mul_dst, ivar, ("imm", mul_c))
            # 增量插在归纳步之前（而不是回边前）：这样 _loop_shape 仍能从
            # 尾部识别出步长，后续循环展开不会因此失效。
            new = new[:body_end - 1] + [inc] + new[body_end - 1:]
            new = new[:h] + [pre] + new[h:]                # 循环头前插入初值
            fn.instrs = new

            # 非负性证明：t = ivar * C，ivar ∈ [lo, hi-1]（guard 是严格小于）。
            # 需 lo >= 0、C > 0、上界乘完不溢出 int64，才能安全地把
            # 取模的符号修正链消掉（见 opt_signed_divmod_simplify）。
            if (lo is not None and hi_v is not None and lo >= 0 and mul_c > 0
                    and hi_v > lo and (max(lo, hi_v - 1) * mul_c) < 2 ** 62):
                nn = set(getattr(fn, "nn", ()))
                nn.add(mul_dst)
                fn.nn = nn
            changed = True
            break
        if not changed:
            break
    return fn


# ---------------------------------------------------------------------------
# 指令调度：基本块内列表调度，填延迟槽
#
# 不改语义（只重排已拓扑有序的无关指令），只把长延迟运算尽量提前，
# 让下一条无关指令填上延迟槽。与内联/展开/强度削减叠加生效。
# ---------------------------------------------------------------------------
_LAT = {"mov": 1, "neg": 1, "not": 1, "cmpset": 2,
        "load": 5, "load8": 5, "store": 1, "store8": 1,
        "movaddr": 1, "call": 6, "syscall": 20, "winapi": 12, "args": 1,
        "winargs": 1, "spawn_child": 8, "xchg": 6}
_BIN_LAT = {"add": 1, "sub": 1, "and": 1, "or": 1, "xor": 1,
            "shl": 1, "shr": 1, "sar": 1,
            "mul": 3, "umulhi": 5, "div": 25, "mod": 25}
# 有副作用/访存的指令：必须保持原有相对顺序
# （winapi 是系统调用：CreateThread/WaitForSingleObject 与访存绝不能重排）
_EFF = ("call", "syscall", "winapi", "spawn_child", "xchg", "ret",
        "store", "store8", "load", "load8")
# 基本块终止符。注意 args 必须独占一块：它从硬件参数寄存器（rdi/rsi/rdx/
# rcx/r8/r9）搬值进 vreg，而变量移位量会用掉 rcx——一旦被调度到它后面
# 就会拿到被污染的参数。因此 args 只能永远排在函数最前面。
_TERM = ("args", "winargs", "spawn_child", "label", "jmp", "jz", "jnz", "jcc", "ret")


def _ins_lat(ins):
    return _BIN_LAT.get(ins[1], 1) if ins[0] == "bin" else _LAT.get(ins[0], 1)


def _sched_block(block):
    """对一个基本块做列表调度；只产生拓扑等价的重排"""
    n = len(block)
    if n < 2:
        return block
    defs, uses = [], []
    for ins in block:
        d, u = vreg_mentions(ins)
        defs.append(set(d))
        uses.append(set(u))
    succ = [set() for _ in range(n)]
    pred = [set() for _ in range(n)]

    def edge(i, j):
        if j not in succ[i]:
            succ[i].add(j)
            pred[j].add(i)

    # vreg 依赖：RAW / WAW / WAR（IR 非 SSA，WAR 尤其不能漏）
    for j in range(n):
        for i in range(j):
            if (defs[i] & (uses[j] | defs[j])) or (uses[i] & defs[j]):
                edge(i, j)
    # 有副作用/访存的指令保持原有相对顺序
    eff = [i for i in range(n) if block[i][0] in _EFF]
    for a, b in zip(eff, eff[1:]):
        edge(a, b)

    # 优先级 = 关键路径长度（长延迟优先发射）
    height = [0] * n
    for i in range(n - 1, -1, -1):
        h = _ins_lat(block[i])
        if succ[i]:
            h += max(height[s] for s in succ[i])
        height[i] = h

    import heapq
    cnt = [len(pred[i]) for i in range(n)]
    heap = [(-height[i], i) for i in range(n) if cnt[i] == 0]
    heapq.heapify(heap)
    out = []
    while heap:
        _, i = heapq.heappop(heap)
        out.append(block[i])
        for s in sorted(succ[i]):
            cnt[s] -= 1
            if cnt[s] == 0:
                heapq.heappush(heap, (-height[s], s))
    return out if len(out) == n else block   # 理论上不可能，兑底保持原序


def opt_schedule(fn):
    """全函数：按基本块调度"""
    out = []
    block = []
    for ins in fn.instrs:
        if ins[0] == "label" and block:
            out.extend(_sched_block(block))
            block = []
        block.append(ins)
        if ins[0] in _TERM:
            out.extend(_sched_block(block))
            block = []
    if block:
        out.extend(_sched_block(block))
    fn.instrs = out
    return fn


# ---------------------------------------------------------------------------
# 非负值分析：证明 vreg 恒 >= 0
#
# 动机：`x % d`（d > 0）的魔数除法要 6 条指令做符号修正（
#   mask=x>>63; |x|; 算完再还原符号 ）。x 若能证明恒非负，
# 这 6 条直接消失，热循环指令数能掉三成。
#
# 从“接地事实”出发做最小不动点，只增不减：
#   接地：常量 >= 0、cmpset 结果（0/1）
#   传递：nn + nn -> nn（add/mul/shl/sar/umulhi/mov）
# 最小不动点而不是最大不动点：避免把“只靠自引用定义”的
# 未初始化变量误判为非负。
# ---------------------------------------------------------------------------
_GROUND_OPS = ("mov", "cmpset")


def analyze_nonneg(fn):
    """返回在所有执行路径上都 >= 0 的 vreg 集合（保守）。

    只在有上界证明时传播算术范围。循环归纳变量由生成器提供的
    ``i < hi`` 形状建立上界，之后可以安全证明 ``i*C``、``i+C`` 非负；
    这正是长整数循环里消除有符号魔数除法修正链的关键。
    """
    limit = 2 ** 62
    ranges = {}
    def_count = {}
    for p in fn.instrs:
        for d in vreg_mentions(p)[0]:
            def_count[d] = def_count.get(d, 0) + 1
    for p in fn.instrs:
        defs = vreg_mentions(p)[0]
        if len(defs) != 1 or def_count.get(defs[0]) != 1:
            continue
        if p[0] == "mov" and isinstance(p[2], tuple) and p[2][0] == "imm":
            v = p[2][1]
            if 0 <= v < limit:
                ranges[p[1]] = max(ranges.get(p[1], -1), v)
        elif p[0] == "cmpset":
            ranges[p[2]] = max(ranges.get(p[2], -1), 1)

    def const_before(before, vreg):
        for j in range(before - 1, max(-1, before - 257), -1):
            p = fn.instrs[j]
            if p[0] in BRANCHES or p[0] == "label":
                return None
            defs, _uses = vreg_mentions(p)
            if vreg in defs:
                if p[0] == "mov" and p[1] == vreg and _is_imm(p[2]):
                    return j, p[2][1]
                return None
        return None

    # 识别严格递增循环：只接受一个常量初始化、一个循环步进定义、
    # 常量上界且无其他写入。上界和末次步进都纳入最大值，避免把循环后的
    # 归纳变量错误地当成仅 <= hi-1。
    for h, b, lab in loop_regions(fn):
        shape = _loop_shape(fn, h, b, lab)
        if shape is None:
            continue
        guard, body, step_ins, _exit, _while = shape
        ivar, hi_spec = guard[2], guard[3]
        if guard[1] != "l" or any(ivar in vreg_mentions(p)[0] for p in body):
            continue
        step = next((p[4][1] for p in step_ins
                     if p[0] == "bin" and p[1] == "add"
                     and _is_imm(p[4]) and p[3] == ivar), None)
        if step is None or step <= 0:
            continue
        init = const_before(h, ivar)
        if init is None:
            continue
        init_idx, lo = init
        hi_def = None
        if _is_imm(hi_spec):
            hi = hi_spec[1]
        else:
            hi_def = const_before(h, hi_spec)
            if hi_def is None:
                continue
            _hi_idx, hi = hi_def
            if any(hi_spec in vreg_mentions(p)[0] for p in body + step_ins):
                continue
        all_defs = {i for i, p in enumerate(fn.instrs)
                    if ivar in vreg_mentions(p)[0]}
        step_defs = {i for i in range(h + 1, b)
                     if ivar in vreg_mentions(fn.instrs[i])[0]}
        if all_defs != ({init_idx} | step_defs) or len(step_defs) != 1:
            continue
        if any(ivar in vreg_mentions(p)[1] for p in fn.instrs[:init_idx]):
            continue
        if not (0 <= lo < hi <= limit):
            continue
        max_i = hi - 1 + step
        if max_i >= limit or max_i >= 2 ** 63:
            continue
        ranges[ivar] = max(ranges.get(ivar, -1), max_i)

    nn = set(getattr(fn, "nn", ())) | {v for v, mx in ranges.items() if mx >= 0}
    for _ in range(12):
        changed = False
        for p in fn.instrs:
            op = p[0]
            defs = vreg_mentions(p)[0]
            if len(defs) != 1 or def_count.get(defs[0]) != 1:
                continue
            if op == "mov":
                src = p[2]
                if isinstance(src, int) and src in ranges:
                    ranges[p[1]] = max(ranges.get(p[1], -1), ranges[src])
                elif isinstance(src, tuple) and src[0] == "imm" and 0 <= src[1] < limit:
                    ranges[p[1]] = max(ranges.get(p[1], -1), src[1])
            elif op == "cmpset":
                ranges[p[2]] = max(ranges.get(p[2], -1), 1)
            elif op == "bin" and p[1] == "sar":
                if isinstance(p[3], int) and p[3] in ranges and _is_imm(p[4]):
                    mx = ranges[p[3]] >> (p[4][1] & 63)
                    if mx < limit:
                        ranges[p[2]] = max(ranges.get(p[2], -1), mx)
            elif op == "bin" and p[1] in ("add", "mul", "shl", "umulhi"):
                a, b = p[3], p[4]
                mx = None
                if isinstance(a, int) and a in ranges and _is_imm(b) and b[1] >= 0:
                    c = b[1]
                    if p[1] == "add":
                        mx = ranges[a] + c
                    elif p[1] == "mul":
                        mx = ranges[a] * c
                    elif p[1] == "shl":
                        mx = ranges[a] << (c & 63)
                    else:
                        mx = (ranges[a] * c) >> 64
                elif p[1] in ("add", "mul") and isinstance(b, int) and b in ranges \
                        and _is_imm(a) and a[1] >= 0:
                    c = a[1]
                    mx = ranges[b] + c if p[1] == "add" else ranges[b] * c
                if mx is not None and mx < limit:
                    ranges[p[2]] = max(ranges.get(p[2], -1), mx)
            for d in defs:
                if d in ranges and ranges[d] >= 0 and d not in nn:
                    nn.add(d)
                    changed = True
        if not changed:
            break
    return nn


def _match_divmod_window(w):
    """校验 7 条指令是否正好是有符号魔数除法的形态，是则返回要素"""
    if len(w) != 7:
        return None
    p_m, p_ax1, p_ax2, p_um, p_sh, p_q1, p_q2 = w
    if not (p_m[0] == "bin" and p_m[1] == "sar" and _is_imm(p_m[4], 63)):
        return None
    x, m = p_m[3], p_m[2]
    if not isinstance(x, int):
        return None
    if not (p_ax1[0] == "bin" and p_ax1[1] == "xor" and p_ax2[0] == "bin"
            and p_ax2[1] == "sub" and p_ax1[2] == p_ax2[2]):
        return None
    a = p_ax2[2]
    if not (p_ax1[3] == x and p_ax1[4] == m and p_ax2[3] == a and p_ax2[4] == m):
        return None
    if not (p_um[0] == "bin" and p_um[1] == "umulhi" and p_um[3] == a
            and isinstance(p_um[4], tuple) and p_um[4][0] == "imm"):
        return None
    t = p_um[2]
    if not (p_sh[0] == "bin" and p_sh[1] == "sar" and p_sh[2] == t
            and p_sh[3] == t and isinstance(p_sh[4], tuple)):
        return None
    if not (p_q1[0] == "bin" and p_q1[1] == "xor" and p_q2[0] == "bin"
            and p_q2[1] == "sub" and p_q1[2] == p_q2[2]):
        return None
    q = p_q2[2]
    if not (p_q1[3] == t and p_q1[4] == m and p_q2[3] == q and p_q2[4] == m):
        return None
    if len({x, m, a, t, q}) != 5:
        return None                 # 变量名交叉，形态不典型，不碰
    return x, m, a, t, q, p_um[4], p_sh[4]


def opt_signed_divmod_simplify(fn):
    """把我们自己降级出来的“有符号魔数除法”收缩成无符号版。

    降级固定形态（见 qlm_native.py 的 bin_op）——注意 ax / t / q 都是
    **同一个 vreg 原地更新**，所以要按相邻指令窗口匹配，不能按 def 链：
        m  = sar  x, 63          # 符号掩码
        ax = xor  x, m
        ax = sub  ax, m          # ax = |x|
        t  = umulhi ax, M
        t  = sar  t, sh          # t = |x| / d
        q  = xor  t, m
        q  = sub  q, m           # q = trunc(x / d)
    若 x 恒非负，则 m 恒为 0：|x| == x、q == t。7 条直接收缩成 4 条：
        ax = x ; t = umulhi ax, M ; t = t >> sh ; q = t
    """
    nn = analyze_nonneg(fn)
    if not nn:
        return fn
    ins = fn.instrs
    out = []
    i = 0
    while i < len(ins):
        got = _match_divmod_window(ins[i:i + 7]) if i + 7 <= len(ins) else None
        if got is not None and got[0] in nn:
            x, _m, a, t, q, mag, sh = got
            out.append(("mov", a, x))
            out.append(("bin", "umulhi", t, a, mag))
            out.append(("bin", "sar", t, t, sh))
            out.append(("mov", q, t))
            i += 7
        else:
            out.append(ins[i])
            i += 1
    fn.instrs = out
    return fn


# ---------------------------------------------------------------------------
# 死代码消除 / 复制传播
# ---------------------------------------------------------------------------


def opt_dce(fn):
    """死代码消除(全局使用集 + 不动点,兼容循环回边)"""
    for _ in range(4):
        used = set()
        for ins in fn.instrs:
            _, uses = vreg_mentions(ins)
            used.update(uses)
        out = []
        changed = False
        for ins in fn.instrs:
            defs, _ = vreg_mentions(ins)
            if ins[0] in PURE and defs and all(d not in used for d in defs):
                changed = True
                continue
            out.append(ins)
        fn.instrs = out
        if not changed:
            break


def _subst_vregs(ins, sub):
    """只在**真正的 vreg 位置**上做替换。

    ⚠ 不能用「遍历元组、凡 int 就替换」的粗暴做法：
      ('syscall', dst, NUM, args) 的 NUM、('movaddr', dst, GID) 的 GID
      都是 int 但**不是 vreg**，被替换会静默把 syscall 1 变成 syscall 0。
    （本文件早期版本正是这个 bug，由字符串运行库接入后暴露。）
    """
    op = ins[0]
    S = lambda x: sub(x) if isinstance(x, int) else x
    L = lambda xs: [sub(x) if isinstance(x, int) else x for x in xs]
    if op == "mov":
        return ("mov", sub(ins[1]), S(ins[2]))
    if op == "bin":
        return ("bin", ins[1], sub(ins[2]), S(ins[3]), S(ins[4]))
    if op == "fbin":
        return ("fbin", ins[1], ins[2], sub(ins[3]), S(ins[4]), S(ins[5]))
    if op == "fneg":
        return ("fneg", ins[1], sub(ins[2]), S(ins[3]))
    if op == "fcmpset":
        return ("fcmpset", ins[1], ins[2], sub(ins[3]), S(ins[4]), S(ins[5]))
    if op == "fcvt":
        return ("fcvt", ins[1], sub(ins[2]), S(ins[3]))
    if op in ("neg", "not"):
        return (op, sub(ins[1]), S(ins[2]))
    if op == "cmpset":
        return ("cmpset", ins[1], sub(ins[2]), S(ins[3]), S(ins[4]))
    if op in ("label", "jmp"):
        return ins
    if op in ("jz", "jnz"):
        return (op, S(ins[1]), ins[2])
    if op == "jcc":
        return ("jcc", ins[1], S(ins[2]), S(ins[3]), ins[4])
    if op == "call":
        return ("call", sub(ins[1]) if ins[1] is not None else None, ins[2], L(ins[3]))
    if op == "ret":
        return ("ret", S(ins[1]) if ins[1] is not None else None)
    if op in ("load", "load8"):
        return (op, sub(ins[1]), S(ins[2]), S(ins[3]))
    if op in ("store", "store8"):
        return (op, S(ins[1]), S(ins[2]), S(ins[3]))
    if op == "movaddr":
        return ("movaddr", sub(ins[1]), ins[2])          # GID 不是 vreg
    if op == "syscall":
        return ("syscall", sub(ins[1]) if ins[1] is not None else None,
                ins[2], L(ins[3]))                       # 系统调用号不是 vreg
    if op == "winapi":
        return ("winapi", sub(ins[1]) if ins[1] is not None else None,
                ins[2], L(ins[3]))                       # API 名不是 vreg
    if op == "args":
        return ("args", [sub(x) for x in ins[1]])
    if op == "winargs":
        return ("winargs", [sub(x) for x in ins[1]])
    if op == "xchg":
        return ("xchg", sub(ins[1]), S(ins[2]), S(ins[3]))
    return ins


def opt_copy_prop(fn):
    """复制传播：仅限只被定义一次的 vreg"""
    def_count = {}
    for ins in fn.instrs:
        defs, _ = vreg_mentions(ins)
        for d in defs:
            def_count[d] = def_count.get(d, 0) + 1
    alias = {}
    for ins in fn.instrs:
        if ins[0] == "mov" and isinstance(ins[2], int) and ins[1] != ins[2]:
            # ⚠ 源 vreg 也必须只定义一次：否则 mov 之后源被重写，
            # 把后续 use 替换成源 vreg 会读到新值（尾零修剪 p0 被吞的教训）。
            if def_count.get(ins[1], 0) == 1 and def_count.get(ins[2], 0) == 1:
                alias[ins[1]] = ins[2]
    for v in list(alias):
        seen = {v}
        while alias[v] in alias and alias[v] not in seen:
            seen.add(alias[v])
            alias[v] = alias[alias[v]]
    if not alias:
        return

    def sub(x):
        return alias.get(x, x) if isinstance(x, int) else x

    new = []
    for ins in fn.instrs:
        ins = _subst_vregs(ins, sub)
        if ins[0] == "mov" and ins[1] == ins[2]:
            continue
        new.append(ins)
    fn.instrs = new


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def opt_all(fn, unroll=True):
    """单函数收尾优化(内联之后调用)"""
    for _ in range(3):
        before = len(fn.instrs)
        opt_copy_prop(fn)
        opt_cse(fn)
        opt_licm(fn)
        # 强度削减在展开之前：展开会把 `t = i*C` 复制成多份，
        # 反而让削减条件（体内只出现一次）失效。
        opt_strength_reduce(fn)
        opt_signed_divmod_simplify(fn)
        # 紧跟着做一次复制传播：把刚收缩出的 `a = x` / `q = t` 塌掉，
        # 否则循环展开会把这些 mov 复制多份，def_count > 1 就再也推不掉。
        opt_copy_prop(fn)
        if unroll:
            opt_loop_unroll(fn)
        opt_cse(fn)
        opt_dce(fn)
        opt_dce(fn)
        if len(fn.instrs) == before:
            break
    # 调度放最后：避免打乱内联/CSE/展开的形态匹配
    opt_schedule(fn)
    return fn


def run_pipeline(fns, inline=True, unroll=True):
    """全部函数的优化管线:内联 -> 逐函数收敛"""
    if inline:
        from qlm_native import opt_inline     # 局部导入避免环依赖
        opt_inline(fns)
    for fn in fns:
        opt_all(fn, unroll=unroll)
    return fns


def stat_text(fns):
    """给 bench / 调试用的规模统计"""
    return " ".join(f"{f.name}:{len(f.instrs)}" for f in fns)
