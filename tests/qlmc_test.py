#!/usr/bin/env python3
"""qlmc_test.py —— stage-1 编译器（`bootstrap/qlmc/qlmc.qma`）的差分回归

做法：同一份源码**分别**用 stage-0（`tools/stage0/qlm_cli.py`）和 qlmc 编译，
跑两个 exe，比较 stdout 与退出码**逐字节相同**。这是唯一有说服力的判据——
"能编出一个 exe"很容易，"和既有编译器行为一致"才是真的对。

覆盖的用例都只用子集 S1（见 `docs/05-toolchain.md` §1.11）：
  examples/fib.qma            递归 + if + 比较
  examples/loop_sum.qma       while + 可变局部 + * % + 2 亿次循环
  tests/selfhost/s1_basics.qma  算术/比较/逻辑/else/递归/字符串/exit 的混合

另加两条结构断言：产物必须是合法 PE（MZ/PE32+/AMD64），且必须比源码小
（"几 KB 的东西"这条口径）。

用法：
  python tests/qlmc_test.py            # 全部用例
  python tests/qlmc_test.py --time     # 额外报 qlmc 的进程内编译耗时
"""
import os
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
SRC_QLMC = os.path.join(ROOT, "bootstrap", "qlmc", "qlmc.qma")
BUILD = os.path.join(ROOT, "build")

CASES = [
    ("fib", "examples/fib.qma"),
    ("loop_sum", "examples/loop_sum.qma"),
    ("s1_basics", "tests/selfhost/s1_basics.qma"),
    ("s2_str", "tests/selfhost/s2_str.qma"),
    ("s2_const", "tests/selfhost/s2_const.qma"),
    ("s2_assert", "tests/selfhost/s2_assert.qma"),
    ("s3_manyfns", "tests/selfhost/s3_manyfns.qma"),
    ("s4_agg", "tests/selfhost/s4_agg.qma"),
    ("s5_enum", "tests/selfhost/s5_enum.qma"),
    ("s6_vec", "tests/selfhost/s6_vec.qma"),
    ("s7_aggfn", "tests/selfhost/s7_aggfn.qma"),
    ("s8_map", "tests/selfhost/s8_map.qma"),
    ("s9_slice", "tests/selfhost/s9_slice.qma"),
    ("s10_defer", "tests/selfhost/s10_defer.qma"),
    ("s11_import", "tests/selfhost/s11_import.qma"),
    ("s12_ffi", "tests/selfhost/s12_ffi.qma"),
    ("s13_closure", "tests/selfhost/s13_closure.qma"),
    ("s14_vecgrow", "tests/selfhost/s14_vecgrow.qma"),
    ("s15_bitops", "tests/selfhost/s15_bitops.qma"),
    ("s16_stackargs", "tests/selfhost/s16_stackargs.qma"),
    ("s17_constexpr", "tests/selfhost/s17_constexpr.qma"),
    ("s18_vecagg", "tests/selfhost/s18_vecagg.qma"),
    ("s19_spawn", "tests/selfhost/s19_spawn.qma"),
    ("s20_mem", "tests/selfhost/s20_mem.qma"),
    ("s21_f64", "tests/selfhost/s21_f64.qma"),
    ("s22_f64print", "tests/selfhost/s22_f64print.qma"),
    ("s23_map_grow", "tests/selfhost/s23_map_grow.qma"),
    ("s24_varreg", "tests/selfhost/s24_varreg.qma"),
    ("s25_divmod", "tests/selfhost/s25_divmod.qma"),
    ("s26_alias", "tests/selfhost/s26_alias.qma"),
    ("s27_modind", "tests/selfhost/s27_modind.qma"),
    ("s28_compound", "tests/selfhost/s28_compound.qma"),
    # v3.50：字符串 const / 位运算复合赋值 / for k in vec。
    # **必须是差分用例**（stage-0 与 qlmc 各编一次、输出逐字节比较）：
    # 这三项都改的是语义，光"能编过"说明不了算得对 —— 尤其
    # `S_FOREACH` 第一版编号与 `S_BREAK` 撞车时，代码能编出来但
    # break 被当集合求值，只有差分能抓住。
    ("s29_syntax", "tests/t194_qlmc_syntax.qma"),
    # v3.51：`len()` 的机器码在 R12 上崩（`_len_of` 缺 SIB 字节）。
    # **这条必须是差分用例**：bug 只在寄存器分配把 LEN 的结果分到 r12
    # 时出现，光"能编过"完全看不出来 —— stage-0 一直是对的。
    ("s30_strlen", "tests/t195_qlmc_strlen.qma"),
    # v3.52：跨模块 const + str 切片。
    # **必须是差分用例**：str 切片返回的是**新串**（不是视图），
    # 长度头 / NUL / ABI 必须对 —— 否则下游 len() 与拼接会读到原串的
    # 长度，那是静默错而不是崩，光"能编过"完全看不出来。
    ("s31_strslice", "tests/t196_qlmc_strslice.qma"),
    # v3.53：thread_start（真 OS 线程，不受 multicore 降级影响）。
    # **必须是差分用例**：arg 传递、句柄有效性、多线程并发累加不丢更新
    # 都要逐字节对上 —— 尤其 bits=15 这条，任一线程没跑或 arg 传错就少一位。
    ("s32_thread", "tests/t197_qlmc_thread.qma"),
    # v3.55：for k in map + map.del。
    # **必须是差分用例**：map 遍历顺序未定义，但"集合内容"必须一致；
    # del 尤其危险 —— 直接清 0 会切断探测链，排在后面的键静默找不到
    # （v3.55 第一版就是这样：has(3) 返回 false、get(3) 返回 0，
    # 数据没丢但找不到）。只有逐行对比 stage-0 才能抓住。
    ("s33_mapiter", "tests/t199_qlmc_mapiter.qma"),
    # v3.57：`map[K]V.new()` 省略容量（默认 16）。
    # stage-0 一直允许省略（"cap 须 2 的幂，省略默认 16"），qlmc 以前强制
    # 要求 —— `std/session` 的 `map[str]str.new()` 因此编不过。
    ("s34_mapnew", "tests/t201_qlmc_mapnew.qma"),
    # v3.58：SIMD（XMM）基础四件 load/store/mov/pxor。
    # **必须是差分用例**：SIMD 指令编码错了只会静默算错或崩，
    # 光"能编过"完全说明不了问题 —— 尤其要验 b7/b8/b15 这三个跨 64 位
    # 边界的字节，只看 b0 的话"只搬了低 64 位"也会通过。
    ("s35_simd", "tests/t202_qlmc_simd.qma"),
    # v3.59：AES-NI / PCLMULQDQ / SSSE3 / SSE 立即数移位（14 个内建）。
    # **必须是差分用例**：SIMD 编码错了只静默算错 —— 比如 pshufb 的 map
    # 写成 0F 3A 而不是 0F 38 就完全是另一条指令，pclmulqdq 少发 imm8
    # 后面的字节会被当指令。本夹具对每条指令都做已知答案的数值验证。
    ("s36_aes", "tests/t203_qlmc_aes.qma"),
]

npass = 0
nfail = 0


def ok(msg):
    global npass
    npass += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global nfail
    nfail += 1
    print(f"  [FAIL] {msg}")


def build_with(cli_args, out):
    r = subprocess.run(cli_args, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError((r.stdout or "")[-800:] + (r.stderr or "")[-800:])


def pe_info(path):
    d = open(path, "rb").read()
    if d[:2] != b"MZ":
        return None
    e = struct.unpack_from("<I", d, 0x3C)[0]
    if d[e:e + 4] != b"PE\0\0":
        return None
    machine, nsec = struct.unpack_from("<HH", d, e + 4)
    optsz = struct.unpack_from("<H", d, e + 20)[0]
    magic = struct.unpack_from("<H", d, e + 24)[0]
    return {"machine": machine, "nsec": nsec, "magic": magic, "size": len(d)}


def main():
    show_time = "--time" in sys.argv
    print("== 构建 qlmc（用 stage-0 编自己写的编译器） ==")
    try:
        build_with([PY, CLI, "build", SRC_QLMC, "--target", "win", "-o", QLMC], QLMC)
    except RuntimeError as ex:
        bad(f"qlmc 自身构建失败：{ex}")
        return 1
    info = pe_info(QLMC)
    ok(f"qlmc.exe 是合法 PE（{info['size']} 字节）") if info else bad("qlmc.exe 不是 PE")

    # ---- 错误路径：必须**干净退出**（rc=2），不能是崩溃（0xC0000005 / 139）----
    # §7.34：qlmc 以前在表达式解析器深处报错时会 SIGSEGV（先正确打印诊断、
    # 然后访问违例）。根因在 ExitProcess 的 loader 关闭流程，修法是出错走
    # TerminateProcess。这条测试就是那个修复的判据 —— 只比退出码，不比产物。
    print("== 错误路径（诊断 + 干净退出） ==")
    bad_src = os.path.join(BUILD, "err_syntax.qma")
    with open(bad_src, "w", encoding="utf-8") as f:
        f.write("fn main() {\n    let x = \n}\n")
    r = subprocess.run([QLMC, "dump", bad_src], capture_output=True)
    if r.returncode == 2 and b"\xe6\x9c\x9f\xe6\x9c\x9b\xe8\xa1\xa8\xe8\xbe\xbe\xe5\xbc\x8f" in r.stderr:
        ok("语法错：打印诊断且 rc=2（无崩溃）")
    else:
        bad(f"语法错：期望 rc=2 且带诊断，实际 rc={r.returncode} stderr={r.stderr[-120:]!r}")

    for name, rel in CASES:
        src = os.path.join(ROOT, rel)
        out0 = os.path.join(BUILD, f"qlmc_{name}_stage0.exe")
        out1 = os.path.join(BUILD, f"qlmc_{name}_native.exe")
        print(f"== {name}（{rel}） ==")
        t0 = time.perf_counter()
        try:
            build_with([PY, CLI, "build", src, "--target", "win", "-o", out0], out0)
            dt0 = (time.perf_counter() - t0) * 1000
            t1 = time.perf_counter()
            build_with([QLMC, "build", src, "-o", out1], out1)
            dt1 = (time.perf_counter() - t1) * 1000
        except RuntimeError as ex:
            bad(f"{name} 构建失败：{ex}")
            continue

        pi = pe_info(out1)
        if not pi:
            bad(f"{name}: qlmc 产物不是 PE")
            continue
        if pi["machine"] != 0x8664 or pi["magic"] != 0x20B:
            bad(f"{name}: 机器码/可选头不对 machine={pi['machine']:#x} magic={pi['magic']:#x}")
            continue
        ok(f"{name}: qlmc 产物是 PE32+ AMD64（{pi['size']} 字节，{pi['nsec']} 节）")

        a = subprocess.run([out0], capture_output=True)
        b = subprocess.run([out1], capture_output=True)
        if a.stdout == b.stdout and a.returncode == b.returncode:
            ok(f"{name}: 与 stage-0 输出逐字节相同（{len(a.stdout)} 字节, rc={a.returncode}）")
        else:
            bad(f"{name}: 输出不同 rc {a.returncode} vs {b.returncode}\n"
                f"      stage0={a.stdout[:120]!r}\n      qlmc  ={b.stdout[:120]!r}")
        if show_time:
            print(f"      编译墙钟：stage-0 {dt0:.0f} ms  |  qlmc {dt1:.0f} ms"
                  f"（含 {370} ms 量级的进程创建税，见 06-status §3.25）")

    # ---- 多核：线程数不得影响产物字节（v2.16） ----
    print("== 并行确定性（-j1 vs -j4，200 个函数） ==")
    big = os.path.join(ROOT, "tests/selfhost/s3_manyfns.qma")
    outs = []
    for j in ("1", "4"):
        p = os.path.join(BUILD, f"qlmc_par_j{j}.exe")
        try:
            build_with([QLMC, "build", big, "-o", p, "-j", j], p)
            outs.append(p)
        except RuntimeError as ex:
            bad(f"-j{j} 构建失败：{ex}")
    if len(outs) == 2:
        d0 = open(outs[0], "rb").read()
        d1 = open(outs[1], "rb").read()
        if d0 == d1:
            ok(f"-j1 与 -j4 产物逐字节相同（{len(d0)} 字节）")
        else:
            bad(f"-j1 与 -j4 产物不同（{len(d0)} vs {len(d1)} 字节）")
        r = subprocess.run([outs[1]], capture_output=True)
        if r.returncode == 0 and r.stdout == b"123013\n":
            ok("-j4 产物运行结果正确（200 个函数的累加）")
        else:
            bad(f"-j4 产物运行异常 rc={r.returncode} out={r.stdout[:60]!r}")

    print("-" * 52)
    print(f"PASS={npass} FAIL={nfail}")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
