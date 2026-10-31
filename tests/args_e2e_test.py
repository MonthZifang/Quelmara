"""t200 驱动：`args()` 端到端差分（v3.56）。

## 判据

Python 端用 `subprocess` 直接传 argv（不经过 shell），逐个比对 stage-0 与
qlmc 编出的 exe 输出。**必须逐字比对**，因为 `args()` 的边界情况很多：
空参数表、含空格的参数、引号、`--flag=value` 形态。

## 一个反直觉的期望值

Windows 的 `GetCommandLineA` 会把带引号的参数**原样返回**（含反斜杠），
所以 `'"a b"'` 这个 argv 元素在两边都会解析成 `\\a` / `b\\` 两个 token。
这不是 bug —— stage-0 也是这样（已实测）。所以本测试**不写死"正确"的
期望值**，而是拿 stage-0 的输出当基准做差分。

用法：
    python tests/args_e2e_test.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
SRC = os.path.join(ROOT, "tests", "t200_qlmc_args.qma")
EXE_Q = os.path.join(ROOT, "build", "t200_qlmc_args_q.exe")
EXE_S0 = os.path.join(ROOT, "build", "t200_qlmc_args_s0.exe")

PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"[PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"[FAIL] {msg}")


CASES = [
    [],
    ["--out", "x.exe"],
    ["a b", "c"],
    ["-x=1", "--y", "2"],
    ["only"],
    ["", "empty-first"],
    ["a", "b", "c", "d", "e"],
]


def main():
    # stage-0 编一份做基准
    r0 = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "stage0", "qlm_cli.py"),
         "build", SRC, "--target", "win", "-o", EXE_S0],
        capture_output=True, text=True, timeout=600)
    if r0.returncode != 0:
        print(r0.stdout)
        print(r0.stderr)
        raise SystemExit(f"[build] stage-0 编译失败 rc={r0.returncode}")

    r1 = subprocess.run([QLMC, "build", SRC, "-o", EXE_Q],
                        capture_output=True, text=True, timeout=300)
    if r1.returncode != 0:
        print(r1.stdout)
        print(r1.stderr)
        raise SystemExit(f"[build] qlmc 编译失败 rc={r1.returncode}")
    ok("两边都编译通过")

    for argv in CASES:
        p0 = subprocess.run([EXE_S0] + argv, capture_output=True,
                            text=True, timeout=30)
        p1 = subprocess.run([EXE_Q] + argv, capture_output=True,
                            text=True, timeout=30)
        if p0.returncode != 0 or p1.returncode != 0:
            bad(f"argv={argv!r} 退出码 stage0={p0.returncode} qlmc={p1.returncode}")
            continue
        if p0.stdout == p1.stdout:
            ok(f"argv={argv!r} 输出一致（{len(p0.stdout.splitlines())} 行）")
        else:
            bad(f"argv={argv!r} 输出不同")
            a = p0.stdout.splitlines()
            b = p1.stdout.splitlines()
            for i in range(max(len(a), len(b))):
                x = a[i] if i < len(a) else "<missing>"
                y = b[i] if i < len(b) else "<missing>"
                if x != y:
                    print(f"     行{i}: stage0={x!r} qlmc={y!r}")

    # 参数个数必须对（独立于 stage-0 的硬断言）
    p = subprocess.run([EXE_Q, "p", "q", "r"], capture_output=True,
                       text=True, timeout=30)
    if "n=3" in p.stdout:
        ok("3 个参数时 n=3")
    else:
        bad(f"3 个参数时 n 不对：{p.stdout!r}")

    p = subprocess.run([EXE_Q], capture_output=True, text=True, timeout=30)
    if "n=0" in p.stdout:
        ok("无参数时 n=0")
    else:
        bad(f"无参数时 n 不对：{p.stdout!r}")

    print(f"\n=== t200 args e2e: PASS={PASS} FAIL={FAIL} ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
