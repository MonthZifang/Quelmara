"""t197 驱动：**跨模块 const** 自检（v3.52）。

## 为什么是自检而不是差分

stage-0（`tools/stage0/`）**本身不支持跨模块 const**：

```
$ python tools/stage0/qlm_cli.py build tests/modconst/mc_main.qma --target win
[qlm] 编译错误：未定义变量 MC_INT
```

而且它连 `pub const` 都不认（`pub 只支持 fn/struct/enum/interface`）。
所以这个特性是 **qlmc 独有的**，没有"两边逐字节对比"的基准。

**注意方向**：这里 qlmc 比 stage-0 强。不去为了"能差分"而把 qlmc 也弄坏 ——
那等于把一个语言缺陷固化进自举链（同 `07-gaps.md` §7.41 的口径）。

## 判据

用 qlmc 编 `tests/modconst/mc_main.qma`，逐行断言输出。期望值由
`tests/modconst/mc_mod.qma` 里的 const 定义手工算出，不是跑一遍抄回来。

用法：
    python tests/modconst_test.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
SRC = os.path.join(ROOT, "tests", "modconst", "mc_main.qma")
EXE = os.path.join(ROOT, "build", "t197_modconst.exe")

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


# 期望输出：按 mc_mod.qma 的定义手工算出来
#   MC_INT = 42, MC_STR = "hello", MC_EMPTY = "", MC_NEG = -7,
#   MC_HEX = 0xC96C5795 = 3379320725
EXPECT = [
    "i=42",
    "s=hello",
    "e=0",
    "n=-7",
    "h=3379320725",
    "f=43",          # mc_add(1) = 1 + 42
    "c=xhello",      # mc_cat("x") = "x" + "hello"
    "l=5",           # len("hello")
    "v=85",          # 42*2+1
    "j=pre-hello",
    "eq=1",
]


def main():
    if not os.path.exists(QLMC):
        print("[build] build/qlmc.exe 不存在，先自举…")
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "stage0", "qlm_cli.py"),
             "build", os.path.join(ROOT, "bootstrap", "qlmc", "qlmc.qma"),
             "--target", "win", "-o", QLMC],
            capture_output=True, text=True, timeout=1200)
        if r.returncode != 0:
            print(r.stdout)
            print(r.stderr)
            raise SystemExit("[build] qlmc 自举失败")

    r = subprocess.run([QLMC, "build", SRC, "-o", EXE],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit(f"[build] 编译 mc_main 失败 rc={r.returncode}")
    ok(f"跨模块 const 编译通过（{os.path.getsize(EXE)} B）")

    p = subprocess.run([EXE], capture_output=True, text=True, timeout=60)
    print("--- 输出 ---")
    print(p.stdout)

    got = [ln for ln in p.stdout.splitlines() if ln.strip()]
    for i, want in enumerate(EXPECT):
        if i < len(got) and got[i] == want:
            ok(f"第 {i + 1} 行：{want}")
        else:
            bad(f"第 {i + 1} 行：期望 {want!r}，实际 {got[i] if i < len(got) else None!r}")

    if p.returncode == 0:
        ok("退出码 0")
    else:
        bad(f"退出码 {p.returncode}")

    print(f"\n=== t197 modconst: PASS={PASS} FAIL={FAIL} ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
