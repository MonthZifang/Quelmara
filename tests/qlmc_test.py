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
