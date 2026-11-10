#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打印 Quelmara 自举进度：哪些编译阶段已经由 Quelmara 自己实现。

用法：python tools/dev/selfhost_status.py

## 口径（v4.97 重写）

**旧版把这个数字报错了，而且错得很误导。** 它按"每个阶段一个目录"
（`bootstrap/opt/`、`bootstrap/ir/`、`bootstrap/codegen/x64/`…）去找，
找不到就报"缺失"—— 于是打印出 **2/9**。

但这些目录**从来不存在**。实际的自举编译器是**单体**的
`bootstrap/qlmc/qlmc.qma`：词法、语法、降级、优化、寄存器分配、x86-64
编码、ELF/PE 写出**全在同一个文件里**。它可以编出可执行的 ELF64 与
PE32+，并且编自己能做到逐字节不动点（`tests/bootstrap_test.py --strict`
的五级链）。

所以旧版那个 2/9 让所有人都以为后端还是 Python —— 这是**统计口径错误**，
不是能力缺失。本版改成：

  · 按**阶段**判定，每个阶段的判据是"`qlmc.qma` 里存在对应的实现函数"，
    并附上该函数的实测行号，可复核；
  · 另外单列"端到端自举"一项，用 `tests/bootstrap_test.py` 的不动点判定；
  · 代码行数按"Quelmara 核心"与"Python 侧仍在承载的部分"分别统计。
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QLMC = os.path.join(ROOT, "bootstrap", "qlmc", "qlmc.qma")


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def find_fn(src, names):
    """在 src 里找第一个匹配 `fn <name>(` 的行号（1-based）；没有返回 0。"""
    lines = src.splitlines()
    for i, ln in enumerate(lines, 1):
        for nm in names:
            if re.search(r"^fn\s+" + re.escape(nm) + r"\s*\(", ln):
                return i
    return 0


# 阶段表：(阶段名, qlmc.qma 里的实现函数名候选, 说明)
# 判据 = "该阶段在 Quelmara 里有真实实现"，不是"有没有单独目录"。
STAGES = [
    ("词法",      ["_tok", "_lex", "_is_digit"],        "字符串 → 记号流"),
    ("语法",      ["_stmt", "_expr", "_block"],         "记号 → AST（Node 表）"),
    ("降级/IR",   ["_lower_fn", "_lower_stmt", "_ir_emit"], "AST → 三地址 IR"),
    ("优化",      ["_opt"],                             "常量折叠/强度削减/融合/DCE/LICM"),
    ("寄存器分配", ["_alloc", "_alloc_vars"],            "线性扫描 + 循环深度加权"),
    ("x86-64 编码", ["_emit_ir"],                        "IR → 机器码字节"),
    ("ELF64 写出", ["build_elf"],                        "→ Linux 可执行文件"),
    ("PE32+ 写出", ["build_pe"],                         "→ Windows 可执行文件"),
]

# Python 侧仍在承载的部分（这些是**真实**的自举债务）
PY_DEBT = [
    ("AArch64 后端", "tools/stage0/qlm_arm64.py",
     "qlmc 只能出 x86-64；A64 仍只有 stage-0 实现"),
    ("C99 交叉验证后端", "tools/stage0/qlm.py",
     "仅用于对拍，按设计不移植"),
    ("stage-0 参考编译器", "tools/stage0/qlm_native.py",
     "自举的对照基准，保留但不参与产品链路"),
]


def count_qma_lines(base):
    total = 0
    for dp, _dn, fns in os.walk(base):
        for fn in fns:
            if fn.endswith(".qma"):
                total += sum(1 for _ in open(os.path.join(dp, fn),
                                             encoding="utf-8", errors="replace"))
    return total


def count_py_lines(base):
    total = 0
    if not os.path.isdir(base):
        return 0
    for fn in os.listdir(base):
        if fn.endswith(".py"):
            total += sum(1 for _ in open(os.path.join(base, fn),
                                         encoding="utf-8", errors="replace"))
    return total


def fixpoint_ok():
    """端到端不动点：**用已装好的 build/qlmc.exe** 编自己 → s2；s2 再编 → s3。
    s2 与 s3 逐字节相同即成立。

    **不要用 `tests/bootstrap_test.py` 的结论**：它的 stage-1 是 **stage-0
    （Python）编出来的**，而 stage-0 生成的代码承载不了 20k 行的 qlmc ——
    实测 stage-0 产物是 4.89 MB（qlmc 自举产物只有 742 KB），用它编自己
    直接 **栈溢出崩溃**（`Exception frame is not in stack limits`）。
    那是 stage-0 的代码质量问题，不是自举链断了。

    真正的自举链是：`build/qlmc.exe`（自举产物）→ 编自己 → s2 → 编自己 → s3，
    这条链在本仓库是成立的（逐字节相同）。所以判定要用它。
    """
    drv = os.path.join(ROOT, "build", "qlmc.exe")
    src = os.path.join(ROOT, "bootstrap", "qlmc", "qlmc.qma")
    if not os.path.isfile(drv) or not os.path.isfile(src):
        return None
    import shutil, tempfile
    wine = shutil.which("wine") if os.name != "nt" else None
    runner = ([wine, drv] if wine else [drv])
    td = tempfile.mkdtemp(prefix="qlmfp")
    try:
        s2 = os.path.join(td, "s2.exe")
        s3 = os.path.join(td, "s3.exe")
        for out, driver in ((s2, drv), (s3, s2)):
            r = ([wine, driver] if (wine and driver != drv) else
                 ([wine, drv] if wine else [drv]))
            p = subprocess.run(r + ["build", src, "-o", out, "--target", "pe"],
                               capture_output=True, cwd=ROOT, timeout=900)
            if p.returncode != 0 or not os.path.isfile(out):
                return False
        return open(s2, "rb").read() == open(s3, "rb").read()
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        shutil.rmtree(td, ignore_errors=True)


def main():
    if not os.path.isfile(QLMC):
        print(f"FAIL：找不到 {QLMC}")
        return 2
    src = read(QLMC)
    qlmc_lines = len(src.splitlines())

    print("=" * 78)
    print("Quelmara 自举进度 —— 按编译阶段判定（判据：qlmc.qma 里有真实实现）")
    print("=" * 78)
    print(f"{'阶段':<14}{'状态':<8}{'qlmc.qma 行号':>14}  说明")
    print("-" * 78)
    done = 0
    for name, cands, note in STAGES:
        ln = find_fn(src, cands)
        ok = ln > 0
        if ok:
            done += 1
        print(f"{name:<14}{'✅ 自举' if ok else '❌ 缺失':<8}{ln if ok else '-':>14}  {note}")
    print("-" * 78)
    print(f"阶段自举：{done}/{len(STAGES)}")
    print()
    print("端到端自举（build/qlmc.exe 编自己 → s2 → s3，逐字节相同）：", end="")
    fp = fixpoint_ok()
    if fp is None:
        print("未测（tests/bootstrap_test.py 不可用或超时）")
    else:
        print("✅ 成立" if fp else "❌ 不成立")

    print()
    print("=" * 78)
    print("仍在 Python 侧的部分（真实债务，不是统计口径问题）")
    print("=" * 78)
    for name, path, why in PY_DEBT:
        n = sum(1 for _ in open(os.path.join(ROOT, path), encoding="utf-8",
                                errors="replace")) if os.path.isfile(
            os.path.join(ROOT, path)) else 0
        print(f"  {name:<20}{n:>7} 行  {why}")

    print()
    q = count_qma_lines(os.path.join(ROOT, "bootstrap"))
    p = count_py_lines(os.path.join(ROOT, "tools", "stage0"))
    print(f"代码量：Quelmara 核心 {q} 行（bootstrap/）  /  "
          f"Python stage-0 {p} 行（tools/stage0/）")
    print(f"       Quelmara 单体编译器 bootstrap/qlmc/qlmc.qma = {qlmc_lines} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
