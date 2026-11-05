#!/usr/bin/env python3
"""运行库汇编单测驱动 —— 把"12 分钟盲试"变成秒级反馈。

每个 tests/rt/*.qma 是一个独立程序，main 末尾 print 一个数字：
  0 = 全部断言通过
  >0 = 失败的断言数

用法：
  python tests/rt/run_rt_test.py            # 默认 wine + build/qlmc.exe
  QLMC=./myqlmc python tests/rt/run_rt_test.py --native   # 原生 ELF 直接跑

Exit code = 失败用例数。
"""
import os
import subprocess
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
QLMC = os.environ.get("QLMC") or os.path.join(ROOT, "build", "qlmc.exe")
IS_WIN = os.name == "nt"


def qlmc_runner():
    if IS_WIN:
        return [QLMC]
    wine = None
    try:
        import shutil
        wine = shutil.which("wine") or shutil.which("wine64")
    except Exception:
        pass
    return [wine, QLMC] if wine else [QLMC]


def main():
    args = sys.argv[1:]
    native = "--native" in args
    if native:
        args.remove("--native")
    runner = qlmc_runner()
    outdir = os.path.join(ROOT, "build", "rt_test")
    os.makedirs(outdir, exist_ok=True)
    fails = 0
    cases = sorted(glob.glob(os.path.join(HERE, "*.qma")))
    for src in cases:
        name = os.path.basename(src)[:-4]
        exe = os.path.join(outdir, name + ("" if not IS_WIN else ".exe"))
        r = subprocess.run(runner + ["build", src, "-o", exe, "--target", "elf"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(exe):
            print(f"[FAIL] {name}: 编译失败 " + (r.stdout + r.stderr).strip()[:120])
            fails += 1
            continue
        os.chmod(exe, 0o755)
        cmd = [exe] if not IS_WIN else exe
        rr = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = rr.stdout.strip().splitlines()
        got = int(out[0]) if out and out[0].lstrip("-").isdigit() else -999
        if got == 0 and rr.returncode == 0:
            print(f"[PASS] {name}")
        else:
            print(f"[FAIL] {name}: 断言失败数={got} rc={rr.returncode}")
            fails += 1
    print(f"\nRT 单测：{len(cases) - fails}/{len(cases)} 通过")
    return fails


if __name__ == "__main__":
    sys.exit(main())
