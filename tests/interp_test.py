#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解释器差分测试（v2.80）。

`bootstrap/interp/qlm_interp.qma` 是一个**用 Quelmara 写的树遍历解释器**：
不编译，直接跑 .qma。它的正确性判据只有一条 —— **同一份源码，解释执行的
输出必须与编译执行的输出逐字节相同**。这不是"差不多就行"：解释器一旦与
编译器的语义有偏差，它就成了第二个真相来源，后面所有的调试都会被它误导。

所以本测试对每个夹具做三件事：

  1. 用 `build/qlm_interp.exe` 解释执行 → (stdout, rc)
  2. 用 `build/qlmc.exe` 编译成 exe，再执行 → (stdout, rc)
  3. 逐字节比对两者（stdout 与 rc 都要一致）

另外钉住两条"边界行为"：
  - 语法错必须**非零退出**并给出带行号的诊断（不能静默当成空程序）
  - 找不到 main / 打不开文件必须非零退出

跑法：python tests/interp_test.py
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "bootstrap", "interp", "qlm_interp.qma")
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
INTERP = os.path.join(ROOT, "build", "qlm_interp.exe")
BUILD = os.path.join(ROOT, "build", "interp")

# 夹具：既能被 qlmc 编译，也能被解释器跑（都在解释器支持的子集里）
FIXTURES = [
    "t151_interp_arith.qma",
    "t152_interp_control.qma",
    "t153_interp_fn.qma",
]

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def want(cond, msg, detail=""):
    ok(msg) if cond else bad(f"{msg}{('（' + detail + '）') if detail else ''}")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, **kw)


def build_interp():
    """解释器源码变了就重编（用 qlmc，自举产物）"""
    if not os.path.isfile(QLMC):
        # CI 上主回归跑在 [9b] 之前，build/qlmc.exe 可能还不存在 —— 就地自举。
        # 慢（~90 s）但只有一次；不这么做这条测试在干净环境里必然红。
        print("[build] build/qlmc.exe 不存在，先自举（stage-0 -> qlmc）…")
        t0 = time.time()
        p = run([sys.executable,
                 os.path.join(ROOT, "tools", "stage0", "qlm_cli.py"),
                 "build", os.path.join(ROOT, "bootstrap", "qlmc", "qlmc.qma"),
                 "--target", "win", "-o", QLMC])
        if p.returncode != 0 or not os.path.isfile(QLMC):
            sys.stderr.write(p.stdout.decode("utf-8", "replace"))
            sys.stderr.write(p.stderr.decode("utf-8", "replace"))
            raise SystemExit("自举 qlmc 失败")
        print(f"[build] qlmc.exe  {os.path.getsize(QLMC)} B  {time.time() - t0:.1f} s")
    need = (not os.path.isfile(INTERP)
            or os.path.getmtime(SRC) > os.path.getmtime(INTERP))
    if not need:
        return
    t0 = time.time()
    p = run([QLMC, "build", SRC, "--target", "win", "-o", INTERP])
    if p.returncode != 0:
        sys.stderr.write(p.stdout.decode("utf-8", "replace"))
        sys.stderr.write(p.stderr.decode("utf-8", "replace"))
        raise SystemExit("解释器编译失败")
    print(f"[build] qlm_interp.exe  {os.path.getsize(INTERP)} B  "
          f"{time.time() - t0:.1f} s")


def diff_one(name):
    src = os.path.join(ROOT, "tests", name)
    if not os.path.isfile(src):
        bad(f"{name}: 夹具不存在")
        return
    # 1) 解释执行
    pi = run([INTERP, src])
    # 2) 编译执行
    exe = os.path.join(BUILD, name.replace(".qma", ".exe"))
    pc = run([QLMC, "build", src, "--target", "win", "-o", exe])
    if pc.returncode != 0:
        bad(f"{name}: 编译失败（夹具必须两个通道都能过）")
        return
    pe = run([exe])
    if pi.stdout != pe.stdout:
        bad(f"{name}: 输出不一致")
        a = pi.stdout.decode("utf-8", "replace").splitlines()
        b = pe.stdout.decode("utf-8", "replace").splitlines()
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                print(f"         第 {i + 1} 行：解释 {x!r} / 编译 {y!r}")
        if len(a) != len(b):
            print(f"         行数不同：解释 {len(a)} / 编译 {len(b)}")
        return
    if pi.returncode != pe.returncode:
        bad(f"{name}: 退出码不一致（解释 {pi.returncode} / 编译 {pe.returncode}）")
        return
    ok(f"{name}: {len(pi.stdout.splitlines())} 行输出逐字节一致，rc={pi.returncode}")


def main():
    os.makedirs(BUILD, exist_ok=True)
    build_interp()

    print("== 解释执行 vs 编译执行（逐字节） ==")
    for name in FIXTURES:
        diff_one(name)

    print("== 边界行为 ==")
    # 语法错：必须非零退出 + 带行号的诊断
    bad_src = os.path.join(BUILD, "syntax_err.qma")
    with open(bad_src, "w", encoding="utf-8") as f:
        f.write("fn main() {\n    let x = \n}\n")
    r = run([INTERP, bad_src])
    want(r.returncode != 0, "语法错：非零退出", f"rc={r.returncode}")
    msg = r.stderr.decode("utf-8", "replace")
    want("行 3" in msg or "行 2" in msg, "语法错：诊断带行号", msg.strip()[:80])

    # 没有 main：非零退出
    nomain = os.path.join(BUILD, "nomain.qma")
    with open(nomain, "w", encoding="utf-8") as f:
        f.write("fn helper(n: int) -> int {\n    return n\n}\n")
    r = run([INTERP, nomain])
    want(r.returncode != 0, "没有 main：非零退出", f"rc={r.returncode}")

    # 打不开的文件：非零退出
    r = run([INTERP, os.path.join(BUILD, "no_such_file.qma")])
    want(r.returncode != 0, "文件不存在：非零退出", f"rc={r.returncode}")

    # 没有参数：给用法
    r = run([INTERP])
    want(r.returncode != 0 and "用法" in r.stderr.decode("utf-8", "replace"),
         "无参数：打印用法并非零退出", f"rc={r.returncode}")

    print("-" * 56)
    print(f"INTERP: PASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
