#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AArch64 接口动态分发（vtable）执行级回归（v1.90）
=================================================
`tests/irdiff.py` 只证明"两个后端产出同一份 IR"，证明不了 A64 发射层真的
把 vtable 表项填对、`BLR` 真的跳到了对的方法上。本测试补这一段：
**编译成 AArch64 ELF，用 tests/a64_emu.py 真跑**，比对程序输出。

覆盖（每条都是一次真实执行）：

  1. `t52_iface`            基本装箱 + 派发
  2. `t54_iface_dyn`        异构容器 vec[Shape] 逐个派发
  3. `t116_iface_multi`     同一类型在两个接口里有同名方法（两套槽位各走各的）
  4. `t118_iface_own`       所有权：提前 return / break / continue / 赋值替换 /
                            容器元素 / 返回值（释放过早会读到被复用的箱）
  5. `ifacexfile`           跨文件接口 + 跨文件 impl + 跨文件 vtable 槽位一致
  6. `t104_generic_enum_impl` 泛型 enum 装箱成接口值（enum 载荷走 vtable）
  7. `iface_rc_a64`         1 MB 堆上限下 1.14 MB 装箱量 + 900 KB 探针
                            （引用计数在 A64 上真的把箱还回去了）

跑法：
    python tests/a64_iface_test.py          # 全量（约 1 分钟，模拟器是纯 Python）
    python tests/a64_iface_test.py --quick  # 跳过第 7 项（低堆回收，最慢）
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE0 = os.path.join(ROOT, "tools", "stage0")
EMU = os.path.join(ROOT, "tests", "a64_emu.py")

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


# (标签, 源码, 期望 stdout 含有的标记, 是否慢)
CASES = [
    ("t52_iface", "tests/t52_iface.qma", "iface ok", False),
    ("t54_iface_dyn", "tests/t54_iface_dyn.qma", "iface dyn ok", False),
    ("t116_iface_multi", "tests/t116_iface_multi.qma", "iface multi ok", False),
    ("t118_iface_own", "tests/t118_iface_own.qma", "iface own ok", False),
    ("iface_xfile", "fixtures/ifacexfile/main.qma", "iface xfile ok", False),
    ("t104_generic_enum_impl", "tests/t104_generic_enum_impl.qma",
     "generic enum impl ok", False),
    ("iface_rc_a64", "tests/iface_lowheap_a64/iface_rc_a64.qma",
     "iface rc a64 ok", True),
]


def build_a64(src, out):
    cmd = [sys.executable, os.path.join(STAGE0, "qlm_arm64.py"),
           "build", src, "-o", out]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          timeout=300)


def run_emu(elf, timeout):
    cmd = [sys.executable, EMU, elf]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout)


def main():
    quick = "--quick" in sys.argv
    for label, src, marker, slow in CASES:
        if quick and slow:
            print(f"  [SKIP] {label}: --quick 跳过低堆回收用例")
            continue
        elf = os.path.join(ROOT, "build", f"a64iface_{label}")
        r = build_a64(os.path.join(ROOT, src), elf)
        if r.returncode != 0:
            tail = (r.stderr or r.stdout).strip().splitlines()
            bad(f"{label} A64 编译失败：{tail[-1] if tail else '无输出'}")
            continue
        # 模拟器纯 Python 解释执行：低堆用例 2500 轮约 20 s，留足余量
        try:
            e = run_emu(elf, timeout=600 if slow else 180)
        except subprocess.TimeoutExpired:
            bad(f"{label} 模拟器超时（疑似死循环或死锁）")
            continue
        if e.returncode != 0:
            bad(f"{label} 执行失败 rc={e.returncode} "
                f"out={e.stdout[-120:]!r} err={e.stderr[-160:]!r}")
            continue
        ok(f"{label} A64 执行通过（{marker}）") if marker in e.stdout \
            else bad(f"{label} 输出不含 {marker!r}：{e.stdout[-120:]!r}")

    print("-" * 52)
    print(f"PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
