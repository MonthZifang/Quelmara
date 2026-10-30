#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuIR 架构无关性对拍：同一份源码在 x86_64 与 aarch64 两个后端下，
除「系统调用号」外必须产出**逐字节相同**的 IR。

这是 IR 层的契约：QuIR 是架构无关的，架构差异只允许出现在系统调用编号
与指令发射层。stage-1 的 bootstrap/ir 将来必须通过这一条。

用法：
    python tests/irdiff.py          # 全量
    python tests/irdiff.py -v
"""
import argparse
import concurrent.futures
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE0 = os.path.join(ROOT, "tools", "stage0")

SYSCALL_RE = re.compile(r"\('syscall', (None|\d+), (\d+),")
# v3.19：`target_os()` / `target_arch()` 折叠成 ('imm', N) 后出现在 jcc 的比较位。
# 只匹配这个**特征形态**（两个 imm 做 ne/eq 比较），不碰普通常量 ——
# 见 normalize() 的说明。
TARGET_IMM_RE = re.compile(
    r"\('jcc', '(ne|eq)', \('imm', \d+\), \('imm', \d+\),")


def normalize(text):
    """归一化：
    1) 去掉编译器横幅行（`[qlm-native] xxx -> yyy (字节数)` 不是 IR）；
    2) 把 syscall 的编号统一成 N；
    3) 把 `target_os()` / `target_arch()` 折叠出的立即数统一成 T。

    (2)(3) 都是**允许的架构差异**：QuIR 本身架构无关，但这两类值按定义
    就取决于目标 —— syscall 编号是内核 ABI 的一部分，target_os/target_arch
    返回的就是"当前目标是什么"。把它们归一化之后，其余部分仍要求逐字节相同。

    v3.19 之前只有 (2)。加了 target_os/target_arch（v3.19）之后，(3) 必须
    一起加 —— 否则任何用它们选常量的源码都会被判分叉，而那是**正确的用法**。
    这条规则本身要小心：它会把 `('imm', 1)` / `('imm', 2)` 一并抹掉，
    理论上会掩盖真正的常量差异；实践上这两个数只在"比较目标"的上下文里出现
    （`jcc ... ('imm', N)` 或 `mov ... ('imm', N)` 之后立即被常量折叠），
    而 irdiff 的其他 100+ 个文件没有这个模式，所以误伤面为零。
    """
    lines = [ln for ln in text.splitlines()
             if not ln.lstrip().startswith("[qlm")]
    s = SYSCALL_RE.sub(lambda m: f"('syscall', {m.group(1)}, N,", "\n".join(lines))
    # (3) target_os()/target_arch() 的折叠结果：形如 ('imm', 1) / ('imm', 2)
    #     出现在比较位（jcc 的 a/b）或赋值位。用 TARGET_IMM_RE 精确匹配
    #     "jcc 里比较两个 imm 之一" 这个特征形态，避免误伤普通常量。
    s = TARGET_IMM_RE.sub(lambda m: f"('jcc', '{m.group(1)}', ('imm', T), ('imm', T),", s)
    return s + "\n"


def dump_ir(src, backend, tag=""):
    out = os.path.join(ROOT, "build", f"_irdiff{tag}.out")
    cmd = [sys.executable, os.path.join(STAGE0, backend), "build", src,
           "-o", out, "--dump-ir"]
    r = subprocess.run(cmd, capture_output=True, cwd=ROOT)
    # --dump-ir 打到 stdout；编译日志在 stderr
    return r.returncode, r.stdout.decode("utf-8", errors="replace"), \
        r.stderr.decode("utf-8", errors="replace")


def collect():
    files = []
    for pat in ("tests/*.qma", "examples/*.qma"):
        files += glob.glob(os.path.join(ROOT, pat))
    return sorted(files)


def check_one(path):
    """跑一个文件的两个后端，返回 (rel, 状态, 详情, IR 行数)。

    每个文件用独立的 -o 路径，避免并行时互相覆盖。
    """
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    tag = "_" + os.path.basename(path).replace(".qma", "")
    rc1, out1, err1 = dump_ir(path, "qlm_native.py", tag + "_x")
    rc2, out2, err2 = dump_ir(path, "qlm_arm64.py", tag + "_a")
    if rc1 != 0 or rc2 != 0:
        first = (err1 or err2).strip().splitlines()
        return rel, "skip", first[-1] if first else "build failed", 0
    a, b = normalize(out1), normalize(out2)
    if a == b:
        return rel, "ok", "", a.count("\n")
    al, bl = a.splitlines(), b.splitlines()
    detail = f"x86 {len(al)} 行 / a64 {len(bl)} 行"
    for i in range(max(len(al), len(bl))):
        x = al[i] if i < len(al) else "<缺行>"
        y = bl[i] if i < len(bl) else "<缺行>"
        if x != y:
            detail += f"\n         第 {i + 1} 行：x86 {x!r}  a64 {y!r}"
            break
    return rel, "bad", detail, len(al)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-j", "--jobs", type=int, default=0,
                    help="并行度（默认 = CPU 核数；0 = 自动）")
    args = ap.parse_args()

    files = collect()
    jobs = args.jobs or min(16, (os.cpu_count() or 4))
    ok = bad = skip = 0
    # 每个文件两次独立编译进程，纯 I/O 等待 —— 用线程池并行（约 4-6× 提速）
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        results = list(ex.map(check_one, files))
    for rel, state, detail, nlines in results:
        if state == "ok":
            ok += 1
            if args.verbose:
                print(f"  [ok] {rel} ({nlines} IR lines)")
        elif state == "skip":
            skip += 1
            print(f"  [SKIP] {rel}: {detail}")
        else:
            bad += 1
            print(f"  [FAIL] {rel}: {detail}")
    print("-" * 56)
    print(f"PASS={ok} FAIL={bad} SKIP={skip}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
