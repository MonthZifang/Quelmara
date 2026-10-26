#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara QuIR 优化器 v0.2(后端无关)
====================================
x86_64 / AArch64 / 未来的 PE·Mach-O 发射层共享的 QuIR 级优化 passes:

  opt_copy_prop    复制传播(仅限单定义 vreg)
  opt_cse          公共子表达式消除(基本块内 GVN,含交换律规范化)
  opt_licm         循环不变量外提(只外提"绝不陷入"的纯运算 → 零投机风险)
  opt_loop_unroll  循环展开(编译期常量步长 1 循环,无守卫展开)
  opt_dce          死代码消除(全局使用集 + 不动点,兼容循环回边)
  run_pipeline     统一入口(内联 → LICM → CSE → 展开 → 收敛)

设计约束(重要):QuIR 是**非 SSA**的--同一 vreg 可被多次定义、变量原地更新、
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
#   ('ffi', dst|None, dll, sym, kinds, ret, [args])   v1.87 PE 导入调用
#   ('args', [dsts]) ('winargs', [dsts])
# ---------------------------------------------------------------------------

BRANCHES = ("jmp", "jz", "jnz", "jcc", "ret")
COMMUTATIVE = ("add", "mul", "and", "or", "xor")
# 绝不陷入的纯运算:可被投机执行(LICM 安全集)
NON_TRAPPING = ("add", "sub", "mul", "and", "or", "xor", "shl", "shr", "sar", "umulhi")
PURE = {"mov", "bin", "neg", "not", "cmpset", "load", "load8", "load32", "movaddr", "frameaddr",
        "fbin", "fneg", "fcmpset", "fcvt", "cssub"}


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
    if op == "trunc":
        return [ins[1]], ints([ins[2]])
    if op == "vsumd":
        return [ins[1]], ints([ins[2], ins[3]])
    if op == "vdotd":
        return [ins[1]], ints([ins[2], ins[3], ins[4]])
    if op == "vdot":
        return [ins[1]], ints([ins[2], ins[3], ins[4]])
    if op == "vsum":
        return [ins[1]], ints([ins[2], ins[3]])
    if op == "atomic":
        # ('atomic', sub, dst, addr, a[, b])：addr 与操作数 a/b 全是读改写
        return [ins[2]], ints(ins[3:])
    if op == "rdtsc":
        return [ins[1]], []
    if op in ("mfence", "pause"):
        return [], []
    if op in ("label", "jmp"):
        return [], []
    if op in ("jz", "jnz"):
        return [], ints([ins[1]])
    if op == "jcc":
        return [], ints([ins[2], ins[3]])
    if op == "call":
        return ints([ins[1]]), ints(ins[3])
    if op == "callr":
        return ints([ins[1]]), ints([ins[2]]) + ints(ins[3])
    if op == "cssub":
        return ints([ins[1]]), ints([ins[2], ins[3]])
    if op == "ret":
        return [], ints([ins[1]])
    if op in ("load", "load8", "load32"):
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
    if op == "ffi":
        # dll/sym/kinds/ret 是字符串/元组常量，不是 vreg
        return ints([ins[1]]), ints(ins[6])
    if op == "args":
        return list(ins[1]), []
    if op == "winargs":
        return list(ins[1]), []
    if op == "spawn_child":
        return [], []
    if op == "xchg":
        return [ins[1]], ints([ins[2], ins[3]])
    if op == "ldar":
        return [ins[1]], ints([ins[2]])
    if op == "stlr":
        return [], ints([ins[1], ins[2]])
    if op == "cpuid_sha":
        return [ins[1]], []
    if op == "cpuid_aes":
        return [ins[1]], []
    if op == "cpuid_pclmul":
        return [ins[1]], []
    if op in ("xmm_mov", "pand_x", "por_x", "pshufb_x", "pclmul_x",
              "psrlw_i", "psllw_i", "psrlq_i", "psllq_i", "pslldq_i", "psrldq_i"):
        # v1.33：SSE 族——操作数全是 xmm 槽（负编码）与编译期立即数，
        # **没有任何 vreg**。注意不能沿用 xmm_* 那条"把正整数当 vreg"的
        # 规则：这些指令的立即数是 0-255，会被误当成 vreg 号。
        return [], []
    if op in ("xmm_ld", "xmm_st", "sha_nexte", "sha_rnds2", "sha_msg1",
              "sha_msg2", "xmm_paddd", "xmm_pxor", "xmm_pshufd", "xmm_palignr",
              "aesenc", "aesenclast", "aesdec", "aesdeclast", "aesimc",
              "aeskeygenassist"):
        # SHA-NI / XMM 族：操作数是 xmm 槽号（**负数编码** -(x+1)，不与
        # vreg 正数空间冲突）；仅地址实参是 vreg（正 int）
        return [], [x for x in ins[1:] if isinstance(x, int) and x >= 0]
    # v1.62 调试信息标记：line/dbgvar/dbgparam 不定义 vreg。dbgvar 的
    # vreg 登记为 use——让 copy_prop 替换后"变量->位置"绑定仍指向值的
    # 最终 vreg。dbgparam 同形（形参绑定）。
    if op == "line":
        return [], []
    if op == "dbgvar":
        return [], [ins[2]]
    if op == "dbgparam":
        return [], [ins[2]]
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
    """返回 [(h, b, lab)]:h=循环头下标,b=回边下标,lab=循环头标签

    ⚠ **同一个循环头可以有多条回边**：`continue`、以及循环体里多个 `if`
    分支各自 `jmp` 回头部，都会产生指向同一个 label 的回边。v2.58 及以前
    这里是"一条 jmp 一个 region"，于是同一个 h 会重复出现多次、每次只覆盖
    到**某一条**回边 —— 下游 pass 拿到的是**残缺的循环区间**。

    v2.59 的实测事故：`csv_parse` 的 while 头有 7 条回边（114/121/134/145/
    185/303/317）。`opt_licm` 处理 (h=56, b=185) 这个残缺区间时，看不到
    @298 对 `v14` 的第二次定义（它落在 (56, 317) 那段），于是把循环携带的
    值当成不变量外提 → 第一行解析出 5 列。

    现在按 h 合并、取**最远的回边**：区间 = [循环头, 最远回边]。这会把
    "跳出路径上的指令"也算进循环体（它们确实在回边之前），对优化只会更
    保守，不会更激进。
    """
    labs = label_index(fn)
    best = {}
    for i, ins in enumerate(fn.instrs):
        # v2.61：回边可以是 `jmp L`，也可以是 `jcc cc, a, b, L`
        # （循环旋转之后就是后者）—— 不认 jcc 会让旋转后的循环对
        # 所有依赖 loop_regions 的 pass 隐身。
        tgt = None
        if ins[0] == "jmp" and isinstance(ins[1], str):
            tgt = ins[1]
        elif ins[0] == "jcc" and isinstance(ins[4], str):
            tgt = ins[4]
        if tgt in labs:
            h = labs[tgt]
            if h < i:                      # 向后跳 = 回边
                cur = best.get(h)
                if cur is None or i > cur[0]:
                    best[h] = (i, tgt)
    return sorted((h, b, lab) for h, (b, lab) in best.items())


# ---------------------------------------------------------------------------
# 字符串长度外提 / 循环内 CSE：把 s[i] 与 len(s) 的 O(n²) 拉回 O(n)
#
# str 是零结尾字节串（SPEC §2.2），所以 `len(s)` 和 `s[i]` 的越界检查都要
# 走 `__str_len` 扫一遍。循环体里对同一个不变指针反复求长，总代价就是
# O(n²)（实测 16 KB 扫描 85.9 ms、32 KB 328 ms、1 MB 跑不完）。
#
# 这个 pass 只动**纯**运行时调用 `call d, __str_len, [p]`：
#   * p 在循环内没有定义（指针不变；str 不可变，内容也不会变）；
#   * d 全函数只定义一次，且所有使用都在循环体内（循环外读不到旧值）；
#   * 同一次扫描里对同一 p 的重复求长收敛成一条 mov（循环内 CSE）。
# 满足条件的调用提到循环头标签之前，只执行一次。
#
# 合并规则（v1.5.1）：循环前已有同指针 p 的 `call d0, __str_len, [p]` 且
#   * d0 全函数只定义一次（不会被改写）；
#   * 该调用与循环头之间没有「从更早位置跳来」的 label（即它支配循环头）；
# 则不重复求长，提一条 `mov d, d0`。str 不可变 ⇒ 同指针长度恒等。
# 这一步让 `let n = len(s)` 与 `while i < n { s[i] }` 的 guard 上界和
# 越界检查 bound 收敛到**同一个 vreg**，opt_bounds_elim 的「循环级动态」
# 证明（guard 的 hi 就是检查的 n）才能删除每字节两条分支——否则两层
# 各自求长，检查永远消不掉（strscan 实测卡在 4× 的根因）。
#
# 必须在**内联之前**跑：内联会把 __str_len 的扫描循环整个搬进循环体，
# 之后就再没有可外提的调用点了（性能报告 §4.1 的根因链）。
# ---------------------------------------------------------------------------

def opt_strlen_hoist(fn, rounds=6):
    """把循环内不变的 `len(s)` 提到循环外，同一指针只求一次。

    **三种形态都要认**（v2.62）：
      1. `('call', dst, '__str_len', [p])` —— 内联前的调用形态；
      2. `('bin','sub', t, p, ('imm',8))` + `('load', dst, t, ('imm',0))`
         相邻，都在循环内 —— 内联后的直读形态（b9_json 的 jnum/jws/jstr）；
      3. `('load', dst, t, ('imm',0))` 而 `t = p - 8` 在**循环外**算好。

    只认形态 1 是个长期漏洞：`len(s)` 降级/内联后变成 2/3，于是循环里
    每轮重读长度。后果有两层：
      * 每轮多 1-2 条指令；
      * **更要命**——`opt_bounds_elim` 的循环级证明要求 guard 的 hi 在循环
        内不被重定义，而 hi 就是这条 `load` 的结果。每轮重定义 ⇒ 证明失效
        ⇒ 每次 `s[p]` 的越界检查（2 条指令 + 1 分支）全部保留。
        b9_json 每字节一次下标，这是它 5.8× 差距的主要来源。

    **支配要求**（v2.61 两次实现都在这里让 b9 段错误）：外提是无条件执行，
    `p` 必须支配循环头 —— 要么定义在函数入口块（第一个 label 之前，如
    `args`/常量初始化），要么与循环头同一基本块（h 前最后一个 label 之后，
    且循环头没有其他前驱）。
    """
    if not fn.instrs:
        return fn
    def_count = {}
    for ins in fn.instrs:
        for d in vreg_mentions(ins)[0]:
            def_count[d] = def_count.get(d, 0) + 1

    def _sub_of(fn):
        """t -> p：t 由 ('bin','sub', t, p, ('imm',8)) 定义（长度前缀地址）"""
        m = {}
        for ins in fn.instrs:
            if (ins[0] == "bin" and ins[1] == "sub" and len(ins) == 5
                    and isinstance(ins[3], int) and isinstance(ins[4], tuple)
                    and ins[4] == ("imm", 8)):
                m[ins[2]] = ins[3]
        return m

    for _ in range(rounds):
        moved = False
        sub_of = _sub_of(fn)
        for (h, b, lab) in loop_regions(fn):
            region = fn.instrs[h:b + 1]
            defs_in_loop = set()
            for ins in region:
                defs_in_loop.update(vreg_mentions(ins)[0])
            first_lab = min([k for k, x in enumerate(fn.instrs)
                             if x[0] == "label"] or [len(fn.instrs)])
            last_lab = max([k for k, x in enumerate(fn.instrs[:h])
                            if x[0] == "label"] or [-1])
            multi_pred = any(x[0] in ("jmp", "jcc", "jz", "jnz")
                             and x[-1] == lab for x in fn.instrs[:h])

            def dominates(p):
                dp = [k for k, x in enumerate(fn.instrs[:h])
                      if p in vreg_mentions(x)[0]]
                if not dp:
                    return False
                if dp[0] < first_lab:
                    return True                     # 入口块，支配全函数
                return dp[0] > last_lab and not multi_pred

            cand = []                  # [(offs, dst, ptr, hoist)]
            skip = set()
            for off, ins in enumerate(region):
                if off in skip:
                    continue
                # ---- 形态 1：call __str_len ----
                if ins[0] == "call" and ins[2] == "__str_len" and len(ins) == 4:
                    dst, args = ins[1], ins[3]
                    if len(args) != 1 or not isinstance(args[0], int):
                        continue
                    p = args[0]
                    if p in defs_in_loop or def_count.get(dst, 0) != 1:
                        continue
                    if any(dst in vreg_mentions(x)[1]
                           for x in fn.instrs[:h] + fn.instrs[b + 1:]):
                        continue
                    cand.append(([off], dst, p, [ins]))
                    continue
                # ---- 形态 2：sub + load 相邻 ----
                if (ins[0] == "bin" and ins[1] == "sub" and len(ins) == 5
                        and isinstance(ins[3], int) and isinstance(ins[4], tuple)
                        and ins[4] == ("imm", 8) and off + 1 < len(region)):
                    nx = region[off + 1]
                    if (nx[0] == "load" and nx[2] == ins[2]
                            and isinstance(nx[3], tuple) and nx[3] == ("imm", 0)):
                        t, p, d = ins[2], ins[3], nx[1]
                        if p in defs_in_loop:
                            continue
                        if def_count.get(t, 0) != 1 or def_count.get(d, 0) != 1:
                            continue
                        if any(t in vreg_mentions(x)[1] for x in fn.instrs
                               if x is not nx):
                            continue
                        if any(d in vreg_mentions(x)[1]
                               for x in fn.instrs[:h] + fn.instrs[b + 1:]):
                            continue
                        if not dominates(p):
                            continue
                        cand.append(([off, off + 1], d, p, [ins, nx]))
                        skip.add(off + 1)
                        continue
                # ---- 形态 3：t 在循环外，循环内只有 load ----
                if (ins[0] == "load" and len(ins) == 4
                        and isinstance(ins[2], int) and ins[2] in sub_of
                        and isinstance(ins[3], tuple) and ins[3] == ("imm", 0)):
                    t, p, d = ins[2], sub_of[ins[2]], ins[1]
                    if t in defs_in_loop or p in defs_in_loop:
                        continue
                    if def_count.get(d, 0) != 1:
                        continue
                    if any(d in vreg_mentions(x)[1]
                           for x in fn.instrs[:h] + fn.instrs[b + 1:]):
                        continue
                    if not dominates(p):
                        continue
                    cand.append(([off], d, p, [ins]))
                    continue
            if not cand:
                continue

            first = {}                 # ptr -> 第一个 dst
            keep, keep_at, repl_at, drop = [], set(), {}, set()
            for offs, dst, p, hoist in cand:
                if p in first:
                    repl_at[offs[0]] = (dst, first[p])
                    for o in offs[1:]:
                        drop.add(o)
                else:
                    first[p] = dst
                    keep.append((offs, dst, p, hoist))
                    keep_at.update(offs)

            new_region = []
            for off, ins in enumerate(region):
                if off in repl_at:
                    d_dst, d_src = repl_at[off]
                    new_region.append(("mov", d_dst, d_src))
                elif off in drop or off in keep_at:
                    continue
                else:
                    new_region.append(ins)
            # 合并：循环前同指针的既有求长（见文件头「合并规则」）。
            jumps = [(idx, x[-1]) for idx, x in enumerate(fn.instrs)
                     if x[0] in ("jcc", "jnz", "jmp") and isinstance(x[-1], str)]
            hoisted = []
            for offs, dst, p, hoist in keep:
                merge_dst = None
                for j, x in enumerate(fn.instrs[:h]):
                    if (x[0] == "call" and x[2] == "__str_len" and len(x) == 4
                            and len(x[3]) == 1 and x[3][0] == p
                            and x[1] is not None and def_count.get(x[1], 0) == 1):
                        between = {y[1] for y in fn.instrs[j + 1:h]
                                   if y[0] == "label"}
                        unsafe = any(t in between and (src < j or src > b)
                                     for src, t in jumps)
                        if not unsafe:
                            merge_dst = x[1]
                        break
                    if (x[0] == "load" and len(x) == 4
                            and isinstance(x[2], int) and sub_of.get(x[2]) == p
                            and isinstance(x[3], tuple) and x[3] == ("imm", 0)
                            and def_count.get(x[1], 0) == 1):
                        merge_dst = x[1]
                        break
                if merge_dst is not None:
                    hoisted.append(("mov", dst, merge_dst))
                else:
                    hoisted.extend(hoist)
            fn.instrs = fn.instrs[:h] + hoisted + new_region + fn.instrs[b + 1:]
            moved = True
            break
        if not moved:
            break
    return fn


# LICM:循环不变量外提
# ---------------------------------------------------------------------------

LICM_SAFE = {"mov", "neg", "not", "cmpset", "movaddr"}


def _licm_safe(ins, readonly=False):
    if ins[0] in LICM_SAFE:
        return True
    if ins[0] == "load":
        # v2.60：**纯读循环里的 load 也能外提**。
        # 这是 vec/str 的热路径大头：`a[i]` 内联成
        #   load len, h, 1 / cmpset+jz / load data, h, 0 / load d, data, i
        # 其中前两个 load 的 base 是**句柄 h**，循环内不变 —— 每轮重读纯属浪费
        # （b4_array 两个读循环 400 万次、b7_sort 内层每轮两次）。
        #
        # 安全性靠 readonly：循环内既没有 call（可能通过参数改 h 指向的内存），
        # 也没有 store/store8（可能别名）。只对**整段循环零写**才开口子 ——
        # 不做指针别名推理，宁可少提。
        return readonly
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
            # 本循环是不是"纯读"：没有 call、没有 store/store8。
            # 只有纯读循环才允许外提 load（见 _licm_safe 的说明）。
            readonly = not any(
                i[0] in ("call", "callr", "syscall", "winapi", "ffi",
                         "store", "store8", "xchg", "atomic", "stlr",
                         "ffi", "spawn_child")
                for i in region)

            hoist_offs = []
            for off in range(1, len(region) - 1):     # 跳过循环头标签与回边
                ins = region[off]
                if not _licm_safe(ins, readonly):
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
    if op in ("mov", "neg", "not", "cmpset", "load", "load8", "load32", "movaddr"):
        return ins
    return None


def opt_cse(fn):
    """基本块内 GVN:纯表达式重复计算 -> mov。跨越副作用/控制流即失效。

    ⚠ QuIR 非 SSA,同一个 vreg 会被重新赋值(例如 `acc = acc + x` 的 acc)。
    因此只要某个 vreg 被重定义,不仅要作废"结果是它"的缓存,
    还要作废**所有把它当操作数**的缓存 -- 否则会把新值误当成旧表达式的结果。
    (这条规则由 parfor_sum 的回归测试接入后发现,见 BACKEND.md 教训记录。)
    """
    table = {}          # key -> vreg
    new = []
    for ins in fn.instrs:
        op = ins[0]
        if op in BRANCHES or op in ("label", "args", "call", "syscall",
                                    "ffi", "store", "store8"):
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


def _find_guard(fn, h, b):
    """宽松找循环 guard：h+1，或跳过标志位后的 h+4。

    `while a && b` 降级成两组 `jcc+jmp`，h+1 是标志位（与立即数比较），
    真正的上界在 h+4。_loop_shape 认不出这种（step 不在末尾），但
    opt_bounds_elim 只需要"guard 建立上界 + body 单调不减"。
    """
    ins = fn.instrs
    g1 = ins[h + 1] if h + 1 < b else None
    if g1 is not None and g1[0] == "jcc" and len(g1) > 4 and not _is_imm(g1[3]):
        return g1
    if h + 4 < b:
        g2 = ins[h + 4]
        if (g2[0] == "jcc" and len(g2) > 4 and not _is_imm(g2[3])
                and g1 is not None and g1[0] == "jcc"):
            return g2
    return None


def _monotone_incr(body, ivar):
    """body 内对 ivar 的每次重定义都是"加上非负常量"（含 tmp+mov 形态）。

    循环 guard 只建立"进入时 0 <= ivar < hi"。只要 body 里 ivar **只增不减**，
    这个上界在整个循环体内一直成立 —— 不需要完整的范围分析。

    v2.63：`opt_bounds_elim` 以前直接用"body 内不重定义归纳变量"当条件，
    于是 `if 数字 { p += 1 } else { go = 0 }` 这种（b9_json 的 jnum/jws/jstr）
    全被拒掉，每次 `s[p]` 的越界检查（2 条指令 + 1 分支，每字节一次）
    一条都消不掉。

    接受两种降级形态（与 _loop_shape 的 step 识别一致）：
      A: ('bin','add', ivar, ivar, ('imm', k))          k >= 0
      B: ('bin','add', t, ivar, ('imm', k)) ; ('mov', ivar, t)
    其他任何定义（减、赋常量、来自未知值）一律返回 False —— 保守。
    """
    n = len(body)
    i = 0
    while i < n:
        ins = body[i]
        if ivar not in vreg_mentions(ins)[0]:
            i += 1
            continue
        if (ins[0] == "bin" and ins[1] == "add" and ins[2] == ivar
                and ins[3] == ivar and _is_imm(ins[4]) and ins[4][1] >= 0):
            i += 1
            continue
        if (ins[0] == "bin" and ins[1] == "add" and isinstance(ins[2], int)
                and ins[2] != ivar and ins[3] == ivar
                and _is_imm(ins[4]) and ins[4][1] >= 0
                and i + 1 < n and body[i + 1] == ("mov", ivar, ins[2])):
            i += 2
            continue
        return False
    return True


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
    # v2.62：`while a && b` 降级成**两组** `jcc + jmp`，共享同一个出口：
    #   L: jcc e flag, ('imm',1), L2 ; jmp End ; L2: jcc l i, n, Body ; jmp End
    #     ; Body: ...
    # 以前只取 `ins[h+1]`，于是归纳变量被当成那个**标志位**（`go`）——
    # 后面的"body 内不重定义归纳变量"单调性检查、以及 opt_bounds_elim 的
    # 循环级证明全部失效（b9_json 的 `while go == 1 && p < n` 就是这种，
    # 它每次 `s[p]` 的越界检查因此一条都没消掉）。
    # 这里跳过"与立即数比较"的标志位条件，用真正带 vreg 上界的那条当 guard。
    gi = h + 1
    if (ins[gi][0] == "jcc" and len(ins[gi]) > 4 and _is_imm(ins[gi][3])
            and gi + 4 < b
            and ins[gi + 1][0] == "jmp" and ins[gi + 2][0] == "label"
            and ins[gi + 3][0] == "jcc" and ins[gi + 4][0] == "jmp"
            and ins[gi + 4][1] == ins[gi + 1][1]
            and ins[gi + 2][1] == ins[gi][4]
            and not _is_imm(ins[gi + 3][3])):
        gi += 3
    guard = ins[gi]
    if guard[0] != "jcc":
        return None
    ivar = guard[2]

    # 归纳步长两种降级形态:
    #   S1  ('bin','add', i, i, ('imm',1))
    #   S2  ('bin','add', tmp, i, ('imm',1)) ; ('mov', i, tmp)
    # v2.62：step 不一定紧贴回边 —— `while a && b` 的循环体末尾会先落一个
    # 分支汇合 label（`go = 0` 之后 label iend ; jmp L），step 在它前面。
    # 以前直接取 ins[b-1]，遇到 label 就返回 None（b9_json 的 jnum/jws/jstr
    # 全部识别失败）。
    ti = b - 1
    while ti > h + 2 and ins[ti][0] == "label":
        ti -= 1
    tail = ins[ti]
    if (tail[0] == "bin" and tail[1] == "add" and tail[2] == ivar
            and tail[3] == ivar and _is_imm(tail[4], 1)):
        step_ins, body_end = [tail], ti
    elif (ti - 1 > h and tail[0] == "mov" and tail[1] == ivar
          and isinstance(tail[2], int)):
        p = ins[ti - 1]
        if (p[0] == "bin" and p[1] == "add" and p[2] == tail[2]
                and p[3] == ivar and _is_imm(p[4], 1)):
            step_ins, body_end = [p, tail], ti - 1
        else:
            return None
    else:
        return None

    # 形态 B:guard 跳进循环体,紧跟着一条跳出的 jmp
    # ⚠ 偏移是相对 **gi**（guard 下标）的：jmp 在 gi+1、label 在 gi+2、
    #   body 从 gi+3 开始。v2.62 第一版把 `h+2/h+3/h+4` 直接换成 `gi+2/+3/+4`，
    #   多偏了 1 —— body 少第一条，opt_mod_inductive 的归纳削减匹配不上，
    #   b1_int 的 `%13` 退回 6 条魔数除法，循环体 9 → 21 条（+27% 时间）。
    if (gi + 1 < b and ins[gi + 1][0] == "jmp" and ins[gi + 2][0] == "label"
            and ins[gi + 2][1] == guard[4]):
        body = ins[gi + 3:body_end]
        return guard, body, step_ins, ins[gi + 1][1], True
    body = ins[gi + 1:body_end]
    return guard, body, step_ins, guard[4], False


def _non_imm_defs(fn, v, limit):
    """v 在 fn.instrs[:limit] 里的定义次数，且必须是 `mov v, imm` 形态。
    返回 1 表示"循环前恰好一次、且为常量 mov"——展开可安全采信；
    0（无定义）/ >1（多重定义）/ 非 mov-imm 定义都返回 != 1。"""
    n = 0
    ok = True
    for p in fn.instrs[:limit]:
        if v in vreg_mentions(p)[0]:
            n += 1
            if not (p[0] == "mov" and isinstance(p[2], tuple)
                    and p[2][0] == "imm"):
                ok = False
                break
    if n != 1 or not ok:
        return -1
    return 1


def opt_loop_unroll(fn, factor=4, max_body=64, min_trip=8, rounds=2):
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
            #
            # 常量溯源必须严谨（v1.5.1 修复）：曾经往回扫 60 条、把窗口内
            # 任何 `mov X, imm` 都收进表——LICM 外提改变定义布局后，guard
            # 上界的 vreg 会匹配到**别的常量**（实测：__memcpy 内联副本的
            # 字块循环 mw=8 被匹配成字节长度 66 → trip 错 → 展开越界拷贝
            # → 段错误）。现在两条铁律：
            #   * 窗口收紧到 12 条（lower_for 的 mov hi, imm 紧邻循环头）；
            #   * hi/lo 若是 vreg，其在循环前必须有**恰好一次**定义且该
            #     定义就是 mov imm——有算术/load 定义（如 mw = m >> 3）或
            #     多重定义一律不展开。
            consts = {}
            for j in range(h - 1, max(-1, h - 12), -1):
                p = fn.instrs[j]
                if p[0] == "mov" and isinstance(p[2], tuple) and p[2][0] == "imm":
                    consts.setdefault(p[1], p[2][1])
                elif p[0] in BRANCHES or p[0] == "label":
                    break
            lo = consts.get(ivar)
            hi_v = hi[1] if _is_imm(hi) else consts.get(hi)
            if lo is None or hi_v is None:
                continue
            # 定义唯一性验证（保守：宁可漏掉也不错换）
            if not _is_imm(hi) and _non_imm_defs(fn, hi, h) != 1:
                continue
            if not _is_imm(guard[2]) and _non_imm_defs(fn, guard[2], h) != 1:
                continue

            trip = hi_v - lo
            if trip <= 0 or trip % factor != 0 or trip < max(factor, min_trip):
                continue

            # 归纳变量在体内不能被重定义;体内不能有跳回循环头的 continue
            # 体内不能含 label（嵌套循环，v1.5.1 修复，实测段错误）：
            #   循环体内联过 memcpy 等运行时函数时 body 自带内层循环，
            #   展开 = renameset 复制内层循环多个副本 + 与 LICM 外提交互，
            #   实测触发 x64 发射层布局敏感 bug（licm 关同样展开却正常，
            #   A64 模拟器正常——纯 x64 编码/分配问题，根因待独立轮次）。
            #   嵌套循环展开收益低、风险高，直接不展开。
            bad = False
            for p in body:
                d, _ = vreg_mentions(p)
                if ivar in d:
                    bad = True
                    break
                if p[0] in ("jmp", "jz", "jnz", "jcc") and p[-1] == lab:
                    bad = True
                    break
                if p[0] == "label":
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
        "load": 5, "load8": 5, "load32": 5, "store": 1, "store8": 1,
        "movaddr": 1, "call": 6, "callr": 6, "cssub": 2, "syscall": 20,
        "winapi": 12, "ffi": 12, "args": 1, "winargs": 1, "spawn_child": 8,
        "xchg": 6}
_BIN_LAT = {"add": 1, "sub": 1, "and": 1, "or": 1, "xor": 1,
            "shl": 1, "shr": 1, "sar": 1,
            "mul": 3, "umulhi": 5, "div": 25, "mod": 25}
# 有副作用/访存的指令：必须保持原有相对顺序
# （winapi 是系统调用：CreateThread/WaitForSingleObject 与访存绝不能重排；
#   callr 是间接调用——调用前后重排会改变观测顺序，同理保序）
def check_suspicious_loops(fns):
    """编译期死循环体检（v1.16）：循环的 guard 变量若在循环体（回边前）
    从未被赋值，大概率是真死循环（如 while i < n 忘了 i += 1）——
    编译警告（不 fail：guard 可能依赖指针写/外部状态，存在合法误报）。
    位置：函数名 + 循环序号（IR 层无源码行号——行号传播登记 GAPS）。
    注意：**不能**走 _loop_shape——它要求循环尾部有归纳步进，
    而死循环恰恰没有步进（v1.16 首版的设计缺陷）。直接用 loop_regions：
    header label 的下一条 jcc 是 guard，回边 jmp 之前是循环体。"""
    warns = 0
    for fn in fns:
        seq = 0
        for h, b, lab in loop_regions(fn):
            seq += 1
            ins = fn.instrs
            if ins[h][0] != "label" or h + 1 >= len(ins):
                continue
            guard = ins[h + 1]
            if guard[0] != "jcc" or not isinstance(guard[2], int):
                continue
            if not _is_imm(guard[3]):
                continue                  # hi 非常量：跳过（误报率高）
            ivar = guard[2]
            # guard 变量在 [h+2, b)（循环体，回边前）全程无 def → 疑似死循环
            body = ins[h + 2:b]
            if any(ivar in vreg_mentions(p)[0] for p in body):
                continue
            print(f"warning: possible infinite loop in '{fn.name}' "
                  f"(loop #{seq}): guard variable never updated in body")
            warns += 1
    return warns




_EFF = ("call", "callr", "syscall", "winapi", "ffi", "spawn_child", "xchg", "ret",
        "store", "store8", "load", "load8", "load32",
        # v1.62 调试标记：line/dbgvar/dbgparam 是"语句边界 + 变量绑定"的
        # 位置钉。列表调度会把无依赖指令浮到基本块尾部——行号标记若可浮动，
        # 断点会落在语句第一条指令之后（值已变）。登记为效应指令后
        # 标记保持语句边界语义；仅 --dbg-info 构建携带标记，默认构建
        # 零影响（.text 逐字节不变）。
        "line", "dbgvar", "dbgparam",
        # vsum 读一整段内存（最多 count*8 字节）：必须与访存保持原序，
        # 否则调度器会把它挪到数组初始化之前（v1.8 实测：归约少一个元素）。
        "vsum", "vsumd", "vdotd", "vdot",
        # atomic 是读改写，mfence 是全屏障：都不可被调度器跨越或重排
        # （v1.10 实测纪律：atomic 忘登记 _EFF 会造成计数静默丢失）。
        # rdtsc 同理——它虽无副作用，但被挪过 call 会让测量差值变成
        # 垃圾（实测 mutex 段 2e6 次锁操作只报 18 cycles）。
        "atomic", "mfence", "rdtsc",
        # acquire/release 访存（v1.98）：与 load/store 同组——顺序语义是它们
        # 存在的唯一理由，调度器一旦跨越就白写了。
        "ldar", "stlr",
        # SHA-NI / XMM 族（v1.15）：xmm_ld/st 读内存，sha_* 有外部语义
        # （xmm 固定槽协议）——调度器一律不跨越、不重排
        "cpuid_sha", "cpuid_aes", "cpuid_pclmul", "xmm_ld", "xmm_st",
        "sha_nexte", "sha_rnds2", "sha_msg1", "sha_msg2", "xmm_paddd",
        "xmm_pxor", "xmm_pshufd", "xmm_palignr", "aesenc", "aesenclast",
        "aesdec", "aesdeclast", "aesimc", "aeskeygenassist",
        "xmm_mov", "pand_x", "por_x", "pshufb_x", "pclmul_x",
        "psrlw_i", "psllw_i", "psrlq_i", "psllq_i", "pslldq_i", "psrldq_i")
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


def _magic_u64(d):
    """无符号常数除法：返回 (M, s, add) 使 floor(n/d) 可算（n < 2^64）。

    Granlund-Montgomery：找最小的 s 使 2^(64+s) <= M*d <= 2^(64+s) + 2^s，
    此时 floor(n/d) = umulhi(n, M) >> s。

    **M 可能装不进 64 位**（d=7 就是），这时要用 libdivide 的修正式：
        t = umulhi(n, M - 2^64)
        q = (t + ((n - t) >> 1)) >> (s - 1)
    返回 add=True 表示走这条。只支持 s >= 1 的情形（d >= 3 都满足）。
    """
    for s in range(1, 64):
        M = ((1 << (64 + s)) + d - 1) // d
        if M < (1 << 64):
            if M * d - (1 << (64 + s)) <= (1 << s):
                return M, s, False
        else:
            M2 = M - (1 << 64)
            if 0 < M2 < (1 << 64):
                return M2, s, True
    return None


def opt_const_div(fn):
    """v2.61：常数除法 / 取模 → **无符号魔数乘法**（被除数已知非负时）。

    背景：stage-0 的 `('bin','div'/'mod', d, a, ('imm',C))` 一直是 `idiv`
    （x86 上 20-40 周期，还是微码化的）。`__str_from_i64` / `__print_i64`
    每转一个数就要做两次 `div 10` —— b5_string 的 50 万次 int→str 就是
    100 万次 idiv。

    这里换成 `umulhi + shr`（取模再加 `imul + sub`），3-4 周期。
    **只对 analyze_nonneg 能证明 a >= 0 的位置做** —— 有符号魔数除法要额外
    的符号修正链（+3 条），而且负数的 floor 语义容易写错；非负是安全的
    多数场景（转字符串、取模索引、哈希）。

    必须排在 `opt_mod_inductive` **之后**：归纳削减靠 `('bin','mod')` 的
    形态做匹配，先转成魔数就再也匹配不上了。
    """
    nn = analyze_nonneg(fn)
    out = []
    changed = False
    for ins in fn.instrs:
        if (ins[0] == "bin" and ins[1] in ("div", "mod")
                and len(ins) == 5 and isinstance(ins[4], tuple)
                and ins[4][0] == "imm"):
            dst, a, c = ins[2], ins[3], ins[4][1]
            if isinstance(a, int) and a in nn and isinstance(c, int) \
                    and 1 < c < (1 << 31):
                mg = _magic_u64(c)
                if mg is not None:
                    M, s, add = mg
                    t = fn.new_v()
                    out.append(("bin", "umulhi", t, a, ("imm", M)))
                    q = fn.new_v()
                    if add:
                        # M 装不进 64 位：q = (t + ((a - t) >> 1)) >> (s - 1)
                        u = fn.new_v()
                        out.append(("bin", "sub", u, a, t))
                        out.append(("bin", "shr", u, u, ("imm", 1)))
                        out.append(("bin", "add", q, t, u))
                        out.append(("bin", "shr", q, q, ("imm", s - 1)))
                    elif s:
                        out.append(("bin", "shr", q, t, ("imm", s)))
                    else:
                        out.append(("mov", q, t))
                    if ins[1] == "div":
                        out.append(("mov", dst, q))
                    else:
                        out.append(("bin", "mul", q, q, ("imm", c)))
                        out.append(("bin", "sub", dst, a, q))
                    changed = True
                    continue
        out.append(ins)
    if changed:
        fn.instrs = out
    return fn


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


def _const_before(fn, before, vreg):
    """在 instrs[before] 之前向前找 vreg 的唯一定义；必须是紧邻的 imm 载入，
    途中遇到 label / 分支（控制流汇合）返回 None——保守。"""
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


def analyze_ranges(fn):
    """保守范围分析：返回 (ranges, preset_nn)。

    ranges: {vreg: 证明上界}，所有值都 >= 0（在所有执行路径上成立）。
    preset_nn: 外部预置的非负 vreg（如强度削减写入的 fn.nn），只有非负
    性、没有上界，调用方做"非负判定"时要并进去。

    循环归纳变量由 ``i < hi`` 形状建立上界。guard 两种条件码都接受：
    for 形态 ``jcc ge i, hi, End``（真则退出）与 while 形态
    ``jcc l i, hi, Body``（真则进体）——两者 body 都在 ``i < hi`` 下执行。
    这正是长整数循环里消除有符号魔数除法修正链、以及
    ``opt_bounds_elim`` 消除越界检查的关键。
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

    # 识别严格递增循环：只接受一个常量初始化、一个循环步进定义、
    # 常量上界且无其他写入。上界和末次步进都纳入最大值，避免把循环后的
    # 归纳变量错误地当成仅 <= hi-1。
    for h, b, lab in loop_regions(fn):
        shape = _loop_shape(fn, h, b, lab)
        if shape is None:
            continue
        guard, body, step_ins, _exit, _while = shape
        ivar, hi_spec = guard[2], guard[3]
        if guard[1] not in ("l", "ge") or any(ivar in vreg_mentions(p)[0] for p in body):
            continue
        step = next((p[4][1] for p in step_ins
                     if p[0] == "bin" and p[1] == "add"
                     and _is_imm(p[4]) and p[3] == ivar), None)
        if step is None or step <= 0:
            continue
        init = _const_before(fn, h, ivar)
        if init is None:
            continue
        init_idx, lo = init
        hi_def = None
        if _is_imm(hi_spec):
            hi = hi_spec[1]
        else:
            hi_def = _const_before(fn, h, hi_spec)
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
            elif op == "bin" and p[1] in ("and", "mod"):
                # x & M（M >= 0）恒在 [0, M]；x % D（D > 0）恒在 [0, D-1]。
                # 这是环形下标 i & 63 / 取模散列最常见的形态，此前不建模，
                # 导致越界检查整窗保留（实测 64.7% 开销，见性能报告 §4.3）。
                a, b = p[3], p[4]
                if p[1] == "and":
                    if _is_imm(b) and 0 <= b[1] < limit:
                        ranges[p[2]] = max(ranges.get(p[2], -1), b[1])
                    elif _is_imm(a) and 0 <= a[1] < limit:
                        ranges[p[2]] = max(ranges.get(p[2], -1), a[1])
                else:
                    if _is_imm(b) and 0 < b[1] < limit:
                        ranges[p[2]] = max(ranges.get(p[2], -1), b[1] - 1)
                    elif _is_imm(a) and 0 < a[1] < limit:
                        ranges[p[2]] = max(ranges.get(p[2], -1), a[1] - 1)
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
    # nn 的成员 = preset ∪ ranges 的全部键（ranges 的值恒 >= 0）。
    # 返回拆开的两份：有上界的 ranges 供消除判定用，preset 只保证非负。
    return ranges, nn - set(ranges)


def analyze_nonneg(fn):
    """兼容包装：返回在所有执行路径上都 >= 0 的 vreg 集合（保守）。"""
    ranges, preset = analyze_ranges(fn)
    return set(ranges) | preset


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
# 模归纳削减：循环里的 `t % D` 魔数窗口 -> 累加器 + 单次条件回绕（cmov/sel）
#
# 形态来源：强度削减把 `t = ivar * C` 变成循环归纳变量（循环外初值 +
# 循环内 `t += C*S`，fn.nn 标记 t 非负）；常量除数的 `%` 在降级期展开成
# 魔数除法的 4 条连续指令（符号修正已被 opt_signed_divmod_simplify 收缩）：
#     q  = umulhi t, M        # floor(t / D)（魔数乘高位）
#     q  = sar   q, sh
#     qd = mul   q, D
#     r  = sub   t, qd        # r = t % D
# umulhi(5c) + mul(3c) 是 ~10 周期的串行依赖链，而 t 每迭代只递增 C'。
# 数学上 v = t % D 本身是归纳量：v' = v + C'，C' < D 时一次条件回绕即回 [0, D)：
#     v += C' ; v = (v >= D) ? v - D : v
# 变换后每迭代省掉 umulhi+sar+mul，换成 cmpset+sub+sel（CMOV，无分支）。
# 保守前提（缺一即跳过该窗口，绝不错换）：
#   * 4 条连续指令严格匹配形态，且 (M, sh) 验证确为 D 的魔数；
#   * t 非负（fn.nn / analyze_nonneg）-> v_init ∈ [0, D)；
#   * t 在循环内只有一条常量增量 `t += C'` 且 0 < C' < D；
#   * r（窗口结果）在函数内唯一定义；q / qd 不出窗口。
# ---------------------------------------------------------------------------

def _verify_magic_pair(M, s, d):
    """校验 (M, s) 确为 d 的魔数（与 qlm_native._verify_magic 同口径；
    为避免循环依赖在此复刻最小验证集）。"""
    if not (0 < M < (1 << 64)) or not (0 <= s < 64):
        return False
    UM = 1 << (64 + s)
    for x in (0, 1, 2, 3, d - 1, d, d + 1, 2**32 - 1, 2**32, 2**63 - 1,
              2**64 - 1, 2**64 - d, 2**64 - d - 1):
        if 0 <= x < (1 << 64) and (x * M) // UM != x // d:
            return False
    return True


def opt_mod_inductive(fn):
    # 非负来源合并：opt 级范围分析（含强度削减写入的 fn.nn）+
    # 降级期非负链条 fn.nnv（既有约定：无符号魔数除法同样以它跳过符号
    # 修正，本变换的前提与它完全一致——t 恒非负）。
    nn = (analyze_nonneg(fn) | set(getattr(fn, "nnv", ()))
          | set(getattr(fn, "nn", ())))
    ins = fn.instrs
    # 每条 vreg 的定义次数与所在指令集合（q/qd 不出窗口、r 唯一定义）
    def_count = {}
    at = {}
    for i, p in enumerate(ins):
        for d in vreg_mentions(p)[0]:
            def_count[d] = def_count.get(d, 0) + 1
        for x in set(vreg_mentions(p)[0]) | set(vreg_mentions(p)[1]):
            at.setdefault(x, set()).add(i)
    edits = []          # (h, body_idx, pre_instrs, body_instrs)
    for (h, b, lab) in loop_regions(fn):
        region = ins[h:b + 1]
        # t 的循环内定义：必须恰有一条 `bin add t, t, ('imm', C')`
        incs = {}
        for off, p in enumerate(region):
            for d in vreg_mentions(p)[0]:
                incs.setdefault(d, []).append(p)
        for off in range(len(region) - 3):
            p1, p2, p3, p4 = region[off:off + 4]
            # 形态：umulhi q,t,M ; sar q,q,sh ; mul qd,q,D ; sub r,t,qd
            if not (p1[0] == "bin" and p1[1] == "umulhi" and _is_imm(p1[4])
                    and p2[0] == "bin" and p2[1] == "sar" and _is_imm(p2[4])
                    and p2[2] == p2[3] == p1[2]
                    and p3[0] == "bin" and p3[1] == "mul" and _is_imm(p3[4])
                    and p3[3] == p1[2]
                    and p4[0] == "bin" and p4[1] == "sub" and p4[4] == p3[2]
                    and p4[3] == p1[3]):
                continue
            t, q, qd, r = p1[3], p1[2], p3[2], p4[2]
            M, sh, D = p1[4][1], p2[4][1], p3[4][1]
            if D <= 0 or not _verify_magic_pair(M, sh, D):
                continue                       # 不是真魔数：窗口不是 t % D
            if t not in nn:
                continue                       # t 非负未证：v_init 可能为负
            # t 的唯一定义必须是本循环内的常量自增
            tdefs = incs.get(t, [])
            if len(tdefs) != 1:
                continue
            td = tdefs[0]
            if not (td[0] == "bin" and td[1] == "add" and td[2] == td[3] == t
                    and _is_imm(td[4])):
                continue
            c = td[4][1]
            if not (0 < c < D):
                continue                       # 单次回绕不够（c >= D）或无进展
            # q / qd 只允许出现在本窗口（q 被窗口前三条的 def/use 合法引用：
            # umulhi 定义、sar 原地更新、mul 当乘数）；r 必须唯一定义
            if at[q] != {h + off, h + off + 1, h + off + 2} \
                    or at[qd] != {h + off + 2, h + off + 3}:
                continue
            if def_count.get(r, 0) != 1:
                continue
            # ---- 构造替换（preheader 初值 + 循环内累加/回绕）----
            v, vq, vqd = fn.new_v(), fn.new_v(), fn.new_v()
            pre = [
                ("bin", "umulhi", vq, t, ("imm", M)),
                ("bin", "sar", vq, vq, ("imm", sh)),
                ("bin", "mul", vqd, vq, ("imm", D)),
                ("bin", "sub", v, t, vqd),
            ]
            body = [
                ("mov", r, v),
                ("bin", "add", v, v, ("imm", c)),
                ("cssub", v, v, ("imm", D)),
            ]
            edits.append((h, h + off, pre, body))
            # t 在循环内的其他使用（窗口与增量自身之外）——用于判定增量是否可删
            win_span = {h + off + k for k in range(4)}
            upd_idx = h + region.index(td)
            other_t_uses = ({i for i in at[t] if h <= i <= b}
                            - win_span - {upd_idx})
            if not other_t_uses and not any(i > b for i in at[t]):
                # 窗口是循环内唯一使用，且循环后无读取：`t += C'` 整条死亡
                edits.append((h, upd_idx, None, None))
    if not edits:
        return fn
    # 统一按指令下标从大到小应用（replace 净增 1 条，若分趟应用会令后续
    # delete 下标漂移——曾把 acc 更新误删成结果 0）。preheader 插入点在
    # 循环头（最小下标），同轮最后执行，不受体部变更影响。
    pres = {}                      # h -> preheader 指令列表（同循环多窗口合并）
    for h, bi, pre, body in edits:
        if pre is not None:
            pres.setdefault(h, []).extend(pre)
    ops = []
    for h, bi, pre, body in edits:
        if body is not None:
            ops.append((bi, "replace", body))
        else:
            ops.append((bi, "delete", None))
    for h, pre in pres.items():
        ops.append((h, "insert", pre))
    for idx, kind, payload in sorted(ops, key=lambda o: -o[0]):
        if kind == "insert":
            ins = ins[:idx] + payload + ins[idx:]
        elif kind == "replace":
            ins = ins[:idx] + payload + ins[idx + 4:]
        else:
            ins = ins[:idx] + ins[idx + 1:]
    fn.instrs = ins
    return fn


# ---------------------------------------------------------------------------
# 死代码消除 / 复制传播
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 越界检查消除：用范围证明删掉必然通过的 bounds 窗口
#
# emit_bounds（qlm_native）生成固定窗口（__bounds_fail 可能已被内联展开，
# 所以首条 jcc 与 l_ok label 之间的内容不参与匹配，证明成立时整块删除）：
#     jcc ge idx, nval, l_fail      # idx >= n -> fail
#     jcc ge idx, 0, l_ok           # idx < 0 -> fail
#     ...fail 路径...
#     label l_ok
# 消除条件（下界+上界必须同时可证，一次性删整窗）：
#   静态：nval 是立即数 n 且 ranges[idx] < n（上界证明已含循环后的取值）；
#   动态：nval 与循环 guard 的 hi 是同一个 vreg、idx 就是该 guard 的归纳
#         变量、窗口严格落在循环体区间内（step 之后 ivar 可能 == hi，不碰），
#         且 idx 已证非负。hi 在循环内被重定义时放弃。
# label 引用计数兜底：窗口内任何 label 被窗口外跳转引用时放弃删除。
# ---------------------------------------------------------------------------

def opt_bounds_elim(fn):
    ins = fn.instrs
    ranges, _preset = analyze_ranges(fn)

    # 循环 guard 表：[(ivar, hi_vreg, hi_const, body_start, body_end)]。
    # 循环级证明是**局部**的：init 紧邻可追溯且 >= 0（下界）+ step 唯一且
    # > 0 + body 内无归纳变量重定义（单调）+ guard（上界）⇒ body 执行期间
    # 0 <= ivar < hi。不要求 ivar 全函数唯一定义（多个循环共享 i 的常见
    # 形态也能证明——每个循环各自成立即可）。窗口落在 body 区间内才可用。
    guards = []
    for h, b, lab in loop_regions(fn):
        shape = _loop_shape(fn, h, b, lab)
        if shape is None:
            # v2.63 宽松路径：step 落在 if/else 分支里（`if 数字 { p += 1 }
            # else { go = 0 }`），_loop_shape 认不出，但"guard 建立上界 +
            # body 单调不减"依然成立 —— 这正是 b9_json 的 jnum/jws/jstr。
            guard = _find_guard(fn, h, b)
            if guard is None:
                continue
            body_start, body_end = h + 1, b
            body, step_ins = ins[body_start:body_end], []
        else:
            guard, body, step_ins, _exit, _isw = shape
            body_start = b - len(step_ins) - len(body)
            body_end = b - len(step_ins)
        if guard[0] != "jcc" or guard[1] not in ("l", "ge"):
            continue
        ivar, hi_spec = guard[2], guard[3]
        if not isinstance(ivar, int):
            continue
        # v2.63：允许"只增不减"的重定义（见 _monotone_incr）。以前这里是
        # "body 内不重定义"，把 `if 数字 { p += 1 } else { ... }` 这种最常见的
        # 扫描循环全拒了 —— b9_json 每次 s[p] 的越界检查都因此留着。
        if not _monotone_incr(body, ivar):
            continue
        init = _const_before(fn, h, ivar)
        if init is None or not (0 <= init[1] < 2 ** 62):
            continue                        # 下界不可追溯（或为负）
        if _is_imm(hi_spec):
            guards.append((ivar, None, hi_spec[1], body_start, body_end))
        elif isinstance(hi_spec, int):
            if any(hi_spec in vreg_mentions(p)[0] for p in body + step_ins):
                continue                    # hi 在循环内被重定义，不可依赖
            hc = _const_before(fn, h, hi_spec)
            guards.append((ivar, hi_spec, hc[1] if hc else None,
                           body_start, body_end))

    # len 等值集合（v1.14）：s[i] 每次降级都会重新读 len——
    #   ('bin','sub',t,obj,('imm',8)) + ('load',v,t,('imm',0))
    # guard 里的 hi 与 bounds 里的 n 是**两个不同 vreg 但同一对象的 len**，
    # 直接比较 vreg 编号会让窗口证明失效（gzip 匹配循环这类 str 密集
    # 循环全部受害）。识别同对象的 len 读取对：obj 单定义（无重定义）
    # 且两对读取的 obj 相同 → load 的 vreg 等值。
    eq_map = {}                            # vreg -> 等值类代表（取最小 vreg 号）
    if guards:
        defs_count = {}
        def_at = {}
        for pi, p in enumerate(ins):
            d, _u = vreg_mentions(p)
            for dd in d:
                defs_count[dd] = defs_count.get(dd, 0) + 1
                def_at[dd] = pi
        # 收集所有 len 读取对：(load_vreg, obj)
        len_pairs = []
        for pi, p in enumerate(ins):
            if p[0] == "load" and isinstance(p[1], int) and isinstance(p[2], int) \
                    and p[3] == ('imm', 0) and p[2] - 1 >= 0:
                t = p[2]
                td = ins[def_at.get(t, -1)] if t in def_at else None
                if td is not None and td[0] == "bin" and td[1] == "sub" \
                        and td[2] == t and isinstance(td[3], int) \
                        and td[4] == ('imm', 8):
                    obj = td[3]
                    if defs_count.get(obj, 0) == 1:
                        len_pairs.append((pi, p[1], obj))
        # obj 相同的 load vreg 归入同一等值类
        by_obj = {}
        for pi, v, obj in len_pairs:
            by_obj.setdefault(obj, []).append(v)
        for obj, vs in by_obj.items():
            rep = min(vs)
            for v in vs:
                eq_map[v] = rep

    def _eq_rep(v):
        return eq_map.get(v, v)

    uses = {}
    for p in ins:
        if p[0] in ("jcc", "jnz", "jmp") and isinstance(p[-1], str):
            uses[p[-1]] = uses.get(p[-1], 0) + 1

    killed = 0
    i = len(ins) - 2
    while i >= 0:                           # 从后往前：删除不影响未扫下标
        p = ins[i]
        q = ins[i + 1]
        if not (p[0] == "jcc" and p[1] == "ge" and isinstance(p[2], int)
                and q[0] == "jcc" and q[1] == "ge" and q[2] == p[2]
                and _is_imm(q[3], 0)):
            i -= 1
            continue
        idx, nval, l_fail = p[2], p[3], p[4]
        l_ok = q[4]
        k = i + 2                           # 窗口尾：第一个 label l_ok
        while k < len(ins) and not (ins[k][0] == "label" and ins[k][1] == l_ok):
            k += 1
        if k >= len(ins):
            i -= 1
            continue
        # 窗口内的 label 只能被窗口内的跳转引用
        win_jumps = [ins[j][-1] for j in range(i, k + 1)
                     if ins[j][0] in ("jcc", "jnz", "jmp")]
        ok = True
        for t in set(t for t in win_jumps if isinstance(t, str)):
            if uses.get(t, 0) > win_jumps.count(t):
                ok = False
                break
        if not ok:
            i -= 1
            continue
        # 证明判定
        provable = False
        if _is_imm(nval):
            nv = nval[1]
            mx = ranges.get(idx)
            if mx is not None and mx < nv:
                provable = True             # 全局上界（已含循环后的取值）
            else:
                for (ivar, _hv, hc, s, e) in guards:
                    if ivar == idx and hc is not None \
                            and hc <= nv and s <= i < e:
                        provable = True     # 循环内：0 <= ivar < hi <= n 恒真
                        break
        elif isinstance(nval, int):
            nrep = _eq_rep(nval)
            for (ivar, hv, _hc, s, e) in guards:
                if ivar == idx and _eq_rep(hv) == nrep and s <= i < e:
                    provable = True         # 循环内：0 <= ivar < hi == n 恒真
                    break
        if not provable:
            i -= 1
            continue
        del ins[i:k + 1]
        killed += 1
        i -= 1
    return fn


def opt_bounds_dedupe(fn):
    """同一基本块内重复的越界检查只留第一次。

    `a[k] += 1` 的降级是「读一次 + 写一次」，各带一整套窗口（4 条分支），
    而两次检查的 (idx, n) 完全相同。范围证明覆盖不到的动态下标（切片长度
    是运行期 vreg）因此白付一倍。这里在**直线块内**做去重：
      * 遇到被跳转引用的 label 视为块边界，清空已检查集合（控制流可能汇入）；
      * idx / n 任一被重新定义就失效该条记录；
      * 重复窗口只删两条 jcc 与失败路径，保留 l_ok 标签（外部跳转仍合法）。
    """
    ins = fn.instrs
    uses = {}
    jmp_src = {}
    for j, p in enumerate(ins):
        if p[0] in ("jcc", "jnz", "jmp") and isinstance(p[-1], str):
            uses[p[-1]] = uses.get(p[-1], 0) + 1
            jmp_src.setdefault(p[-1], []).append(j)

    seen = {}
    killed = 0
    i = 0
    block_start = 0
    while i < len(ins) - 1:
        p, q = ins[i], ins[i + 1]
        if p[0] == "label":
            # 只有「从块外跳进来」（前向跨块）或回边（后向）才是块边界；
            # 窗口内部失败路径的前向跳转不破坏直线性。
            if any(j < block_start or j > i for j in jmp_src.get(p[1], ())):
                seen.clear()
                block_start = i + 1
            i += 1
            continue
        # 记录失效：本指令重定义 idx / n
        defs, _ = vreg_mentions(p)
        if defs and seen:
            for key in list(seen):
                if key[0] in defs or key[1] in defs:
                    del seen[key]
        if not (p[0] == "jcc" and p[1] == "ge" and isinstance(p[2], int)
                and q[0] == "jcc" and q[1] == "ge" and q[2] == p[2]
                and _is_imm(q[3], 0)):
            i += 1
            continue
        idx, nval, l_fail, l_ok = p[2], p[3], p[4], q[4]
        k = i + 2
        while k < len(ins) and not (ins[k][0] == "label" and ins[k][1] == l_ok):
            k += 1
        if k >= len(ins):
            i += 1
            continue
        win_jumps = [ins[j][-1] for j in range(i, k + 1)
                     if ins[j][0] in ("jcc", "jnz", "jmp")]
        ok = True
        for t in set(t for t in win_jumps if isinstance(t, str)):
            if uses.get(t, 0) > win_jumps.count(t):
                ok = False
                break
        if not ok:
            i += 1
            continue
        key = (idx, nval if not isinstance(nval, int) else nval)
        if key in seen:
            # 保留 l_ok 标签，只删两条 jcc 与失败路径
            del ins[i:k]
            ins.insert(i, ("label", l_ok))
            killed += 1
            continue
        seen[key] = i
        i = k + 1
    return fn


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
    if op == "callr":
        return ("callr", sub(ins[1]) if ins[1] is not None else None, S(ins[2]), L(ins[3]))
    if op == "cssub":
        return ("cssub", sub(ins[1]), S(ins[2]), S(ins[3]))
    if op == "ret":
        return ("ret", S(ins[1]) if ins[1] is not None else None)
    if op in ("load", "load8", "load32"):
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
    if op == "ffi":
        return ("ffi", sub(ins[1]) if ins[1] is not None else None,
                ins[2], ins[3], ins[4], ins[5], L(ins[6]))   # dll/sym 不是 vreg
    if op == "args":
        return ("args", [sub(x) for x in ins[1]])
    if op == "winargs":
        return ("winargs", [sub(x) for x in ins[1]])
    if op == "cpuid_sha":
        return ("cpuid_sha", sub(ins[1]))
    if op == "cpuid_aes":
        return ("cpuid_aes", sub(ins[1]))
    if op == "cpuid_pclmul":
        return ("cpuid_pclmul", sub(ins[1]))
    if op in ("xmm_mov", "pand_x", "por_x", "pshufb_x", "pclmul_x",
              "psrlw_i", "psllw_i", "psrlq_i", "psllq_i", "pslldq_i", "psrldq_i"):
        return ins                       # 全是槽号与立即数，不含 vreg
    if op in ("xmm_ld", "xmm_st", "sha_nexte", "sha_rnds2", "sha_msg1",
              "sha_msg2", "xmm_paddd", "xmm_pxor", "xmm_pshufd", "xmm_palignr",
              "aesenc", "aesenclast", "aesdec", "aesdeclast", "aesimc",
              "aeskeygenassist"):
        # xmm 槽是负数编码（非 vreg），只有地址实参是 vreg（正 int）
        return tuple(v if isinstance(v, int) and v < 0 else
                     (sub(v) if isinstance(v, int) else v) for v in ins)
    if op == "xchg":
        return ("xchg", sub(ins[1]), S(ins[2]), S(ins[3]))
    if op == "ldar":
        return ("ldar", sub(ins[1]), S(ins[2]))
    if op == "stlr":
        return ("stlr", S(ins[1]), S(ins[2]))
    if op == "atomic":
        # ('atomic', sub, dst, addr, a[, b])：addr/a/b 都是 vreg 位置。
        # 漏登记的后果（v1.10 实测）：copy_prop 塌掉 addr 的定义 mov，
        # atomic 里的 use 不被替换 -> 悬空 vreg -> 调度器把它排到定义前
        # -> 运行期地址是垃圾，段错误。
        return tuple(["atomic", ins[1], sub(ins[2]), S(ins[3]), S(ins[4])]
                     + ([S(ins[5])] if len(ins) > 5 else []))
    if op in ("mfence", "pause"):
        return ins
    # v1.62 调试标记：dbgvar/dbgparam 的 vreg 必须跟着 copy_prop 的
    # 别名替换走——否则"变量->位置"绑定会指向一个已被塌缩掉的 vreg，
    # 调试器读到的是未定义槽（实测：let f = 2.5 的绑定在替换后指向
    # 从未定义的 vreg，print f 直接失效）。
    if op == "dbgvar":
        return ("dbgvar", ins[1], sub(ins[2]))
    if op == "dbgparam":
        return ("dbgparam", ins[1], sub(ins[2]))
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

import os as _os


def _skip_pass(name):
    """QLM_SKIP_PASSES=a,b,c：调试用 pass 级跳过开关。
    二分优化器引入的坏变换时用（如：QLM_SKIP_PASSES=opt_bounds_elim）。

    opt_licm 自 v2.59 起**默认启用**。历史上它默认关闭（v1.5.1）的原因是
    "外提改变指令布局 → x64 分配器布局敏感段错误"。v2.59 把这个根因挖到
    了底：**不是分配器错，是编码器错** —— `mov byte [mem], reg` 在 reg
    编号 4..7（spl/bpl/sil/dil）时漏了 REX 前缀，被编码成 ah/ch/dh/bh，
    于是"存 sil"变成"存 ch"，写进去的是另一个寄存器的值。分配器把字节
    存储的**值**分到 rsi/rdi 时必然触发；被写错的值一旦是长度/偏移就是
    越界写（段错误），否则是静默错值。

    证据链：
      * `tools/qlm_licm_audit.qma`（Quelmara 写的审计工具）复算的活跃区间
        与线性扫描分配，与 `qlm_native.allocate()` 逐 vreg 完全一致
        （`build/licm/xcheck.py` 对拍），分配器本身没有区间重叠 / 槽复用；
      * 关掉那两行 REX 强制后，`tests/t144_licm_bytes.qma` 在 LICM=1 下
        立刻断言失败，LICM=0 下通过 —— 与"布局敏感"的现象吻合。

    逃生阀（按优先级）：
      QLM_SKIP_PASSES=opt_licm  /  QLM_DISABLE_LICM=1  /  QLM_ENABLE_LICM=0
    """
    if name in _os.environ.get("QLM_SKIP_PASSES", "").split(","):
        return True
    if name == "opt_licm":
        if "1" in _os.environ.get("QLM_DISABLE_LICM", "").split(","):
            return True
        if "0" in _os.environ.get("QLM_ENABLE_LICM", "").split(","):
            return True
    return False


def opt_all(fn, unroll=True):
    """单函数收尾优化(内联之后调用)"""
    # 字符串求长外提（若调用方没在 inline 前跑过，这里兜一次）
    if not _skip_pass("opt_strlen_hoist"):
        opt_strlen_hoist(fn)
    for _ in range(3):
        before = len(fn.instrs)
        if not _skip_pass("opt_copy_prop"):
            opt_copy_prop(fn)
        if not _skip_pass("opt_cse"):
            opt_cse(fn)
        if not _skip_pass("opt_licm"):
            opt_licm(fn)
        # 强度削减在展开之前：展开会把 `t = i*C` 复制成多份，
        # 反而让削减条件（体内只出现一次）失效。
        if not _skip_pass("opt_strength_reduce"):
            opt_strength_reduce(fn)
        if not _skip_pass("opt_signed_divmod_simplify"):
            opt_signed_divmod_simplify(fn)
        # 紧跟着做一次复制传播：把刚收缩出的 `a = x` / `q = t` 塌掉，
        # 否则循环展开会把这些 mov 复制多份，def_count > 1 就再也推不掉。
        if not _skip_pass("opt_copy_prop"):
            opt_copy_prop(fn)
        # 模归纳削减要在强度削减 + 收缩 + 复制传播之后（干净的 4 条窗口），
        # 展开之前（展开复制的是已变换形态，每段各回绕一次，语义正确）。
        if not _skip_pass("opt_mod_inductive"):
            opt_mod_inductive(fn)
        if not _skip_pass("opt_const_div"):
            opt_const_div(fn)
        if not _skip_pass("opt_cse"):
            opt_cse(fn)
        if not _skip_pass("opt_dce"):
            opt_dce(fn)
            opt_dce(fn)
        if len(fn.instrs) == before:
            break
    # 循环展开放收敛循环**之后**跑一次（v1.5.1 修复，实测段错误）：
    # 展开曾经放在收敛循环内，展开副本在下一轮被 LICM 的别名替换
    # 处理——alias 表在展开区域上把 vreg 错误污染（实测 rep * ulen
    # 变成 rep * 别的 vreg、内联 memcpy 的字块循环 guard 从字数变
    # 字节数）→ 展开次数错 → 越界拷贝 → 段错误。展开副本是"成品"，
    # 不该再被变换型 pass 触碰。
    if unroll and not _skip_pass("opt_loop_unroll"):
        opt_loop_unroll(fn)
        if not _skip_pass("opt_dce"):
            opt_dce(fn)
    # 越界检查消除：收敛完成后跑一次（窗口是纯控制流，删除后无新优化机会；
    # 放在展开之后，展开复制的每份窗口都能吃到证明）。
    if not _skip_pass("opt_bounds_elim"):
        opt_bounds_elim(fn)
    if not _skip_pass("opt_bounds_dedupe"):
        opt_bounds_dedupe(fn)
    # 调度放最后：避免打乱内联/CSE/展开的形态匹配
    if not _skip_pass("opt_schedule"):
        opt_schedule(fn)
    return fn


def run_pipeline(fns, inline=True, unroll=True):
    """全部函数的优化管线:字符串求长外提 -> 内联 -> 逐函数收敛"""
    for fn in fns:                       # 必须在内联之前（见 opt_strlen_hoist）
        opt_strlen_hoist(fn)
    if inline:
        from qlm_native import opt_inline     # 局部导入避免环依赖
        opt_inline(fns)
    for fn in fns:
        opt_all(fn, unroll=unroll)
    return fns


def stat_text(fns):
    """给 bench / 调试用的规模统计"""
    return " ".join(f"{f.name}:{len(f.instrs)}" for f in fns)
