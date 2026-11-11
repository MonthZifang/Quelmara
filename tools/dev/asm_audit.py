#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审计 qlmc 产物里的**可优化模式**，按热循环给出改进空间。

## 为什么需要它

性能优化最容易踩的坑是"凭感觉改"。本项目已经吃过几次教训：
  · LICM 改了四版才正确，收益却是 0；
  · v4.103 的 peephole 少了一条 cmp，b35 反而慢 6%（布局效应）；
  · 一度把 CI 换机器误判成"11 项性能退化"。

所以先**量化**代码里的浪费，再决定改什么。

## 它统计什么（都是反汇编层面的客观事实）

| 模式 | 含义 | 典型来源 |
|---|---|---|
| `store→load` 同槽相邻 | 临时值被溢出后立刻读回 | 寄存器压力过高 |
| `mov rX, rY` 后立即用 | 冗余寄存器副本 | 分配器保守 |
| `cmp` 后紧跟同操作的位运算 | 冗余比较（位运算已设标志位） | 见 v4.103 |
| 循环体指令数 | 与 C 同题代码对比的基数 | — |

## 用法

    # 审计单个基准
    python tools/dev/asm_audit.py b34_bitops

    # 审计一批，按"浪费密度"排序
    python tools/dev/asm_audit.py --all

    # 指定编译器
    python tools/dev/asm_audit.py b35_branch --cc /tmp/qlmc_new.exe

## 口径

"热循环"的判定：找 `cmp rX, <大常数>` + `jcc` 之后、回边之前的那段。
大常数取 ≥ 100000（基准里的计数器上界都是百万/千万级）。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(ROOT, "bench", "speed", "quelmara")
DEFAULT_CC = os.path.join(ROOT, "build", "qlmc.exe")

INS = re.compile(r"^\s+([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(\S.*)$")
STORE = re.compile(r"mov\s+QWORD PTR \[rbp([+-])0x([0-9a-f]+)\],(\w+)")
LOAD = re.compile(r"mov\s+(\w+),QWORD PTR \[rbp([+-])0x([0-9a-f]+)\]")
MOVRR = re.compile(r"mov\s+(r\w+),(r\w+)$")
BIGCMP = re.compile(r"cmp\s+\w+,0x([0-9a-f]{5,})")


def build(cc, src, out):
    wine = shutil.which("wine") if os.name != "nt" else None
    cmd = ([wine, cc] if wine else [cc]) + ["build", src, "-o", out,
                                            "--target", "elf", "--no-bounds-check"]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def disasm(path):
    r = subprocess.run(["objdump", "-D", "-b", "binary", "-m", "i386:x86-64",
                        "-M", "intel", "--adjust-vma=0x400000", path],
                       capture_output=True, text=True)
    rows = []
    for ln in r.stdout.splitlines():
        m = INS.match(ln)
        if m:
            rows.append((int(m.group(1), 16), m.group(3).strip()))
    return rows


def backedges(rows):
    """收集所有回边 (lo, hi)，hi 是回跳指令的下标。"""
    out = []
    for i, (addr, txt) in enumerate(rows):
        m = re.search(r"j\w+\s+0x([0-9a-f]+)", txt)
        if not m:
            continue
        tgt = int(m.group(1), 16)
        if tgt > addr:
            continue
        lo = None
        for j, (a2, _) in enumerate(rows):
            if a2 >= tgt:
                lo = j
                break
        if lo is not None and lo < i:
            out.append((lo, i))
    return out


def hot_loop(rows):
    """找**最内层**热循环。

    v4.104 修正：原来靠"`cmp 大常数` + jcc"识别循环头，结果是
    `b17_bubble` / `b28_matrix` 都匹配到同一个运行库循环（都显示 43 条、
    7% 浪费），完全没有区分度。

    改成按**回边**识别，并优先选**跨度最小但指令数够多**的那个：
      · 纯运行库的小循环（分配器自旋等）指令太少，排除；
      · 嵌套循环取最内层（跨度最小），因为它才是热点。
    """
    cands = []
    for lo, hi in backedges(rows):
        seq = rows[lo:hi + 1]
        if len(seq) < 10:         # 太短的多半是运行库自旋，不是基准热循环
            continue
        addr_span = rows[hi][0] - rows[lo][0]
        cands.append((addr_span, len(seq), seq))
    if not cands:
        return []
    # **按"浪费密度"降序**取第一个。
    #
    # 迭代过程（都试过）：
    #   跨度最小  -> 全匹配到运行库 6 条自旋（无区分度）
    #   指令数最多 -> 匹配到外层循环（b34 显示 50 条 2%，而手工分析是
    #               最内层 20 条 45%，完全失真）
    #
    # 现在按"浪费占比"选 —— 这才是这个工具要回答的问题
    # （"哪个循环最值得优化"），而不是"哪个循环最大"。
    scored = []
    for span, n, seq in cands:
        a = audit(seq)
        waste = a["spill"] * 2 + a["movrr"]
        density = waste / max(a["insn"], 1)
        scored.append((density, waste, n, seq))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return scored[0][3]


def audit(seq):
    """统计三类可优化模式。

    v4.111：把 `mov rX,rY` 细分成**真冗余**与**必要的参数/返回值搬运**。
    否则单独看总数会高估收益 —— `b9_json` 的 24 条 mov 里大半是
    `mov rcx,<self>` / `mov rdx,<index>` 这种调用的实参准备，那是必需的。

    判据：
      · `necessary`：该 mov 后面**紧邻**一条 `call`，或它写入的是
        rcx/rdx/r8/r9（x86-64 SysV 前四个实参寄存器）且下一两条内有 call
      · `redundant`：`mov X,Y` 之后紧接 `mov Z,X`（同一值连搬两次，
        可以合成 `mov Z,Y`）—— 这是最确定的浪费
      · `other`：其余，可能仍有价值但需人工判断
    """
    n = len(seq)
    spill = 0
    for i in range(n - 1):
        a = STORE.search(seq[i][1])
        b = LOAD.search(seq[i + 1][1])
        if a and b and a.group(2) == b.group(3):
            spill += 1
    redundant = 0
    necessary = 0
    other = 0
    ARGREGS = {"rcx", "rdx", "r8", "r9", "rdi", "rsi"}
    for i, (_, t) in enumerate(seq):
        m = MOVRR.search(t)
        if not m:
            continue
        dst, src = m.group(1), m.group(2)
        # 紧接下一条是 mov Z, dst ？
        chain = 0
        if i + 1 < n:
            m2 = MOVRR.search(seq[i + 1][1])
            if m2 and m2.group(2) == dst:
                chain = 1
        if chain == 1:
            redundant += 1
            continue
        # 后面 2 条内出现 call，且 dst 是实参寄存器 -> 必要
        near_call = 0
        for k in range(i + 1, min(i + 3, n)):
            if "call" in seq[k][1]:
                near_call = 1
                break
        if near_call == 1 and dst in ARGREGS:
            necessary += 1
        else:
            other += 1
    return {"insn": n, "spill": spill, "movrr": redundant + necessary + other,
            "redundant": redundant, "necessary": necessary, "other": other}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("benches", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--cc", default=DEFAULT_CC)
    ap.add_argument("--show", action="store_true", help="打印热循环指令")
    args = ap.parse_args()

    names = args.benches
    if args.all:
        names = sorted(f[:-4] for f in os.listdir(BENCH) if f.endswith(".qma"))
    if not names:
        ap.error("给一个基准名，或用 --all")

    td = tempfile.mkdtemp(prefix="asmau")
    rows = []
    for b in names:
        src = os.path.join(BENCH, b + ".qma")
        if not os.path.isfile(src):
            continue
        exe = os.path.join(td, b)
        r = build(args.cc, src, exe)
        if r.returncode != 0 or not os.path.isfile(exe):
            continue
        seq = hot_loop(disasm(exe))
        if not seq:
            continue
        a = audit(seq)
        rows.append((b, a))
        if args.show:
            print(f"--- {b} 热循环 {a['insn']} 条 ---")
            for addr, t in seq:
                print(f"  {addr:x}: {t}")
    rows.sort(key=lambda kv: -(kv[1]["spill"] * 2 + kv[1]["redundant"]))
    print(f"{'bench':22}{'循环指令':>9}{'溢出往返':>10}{'真冗余mov':>10}"
          f"{'必要搬参':>10}{'上限占比':>10}")
    print("-" * 72)
    for b, a in rows:
        waste = a["spill"] * 2 + a["redundant"]
        pct = 100.0 * waste / max(a["insn"], 1)
        print(f"{b:22}{a['insn']:9}{a['spill']:10}{a['redundant']:10}"
              f"{a['necessary']:10}{pct:9.0f}%")
    print()
    print("说明：`上限占比` = (溢出往返*2 + 真冗余mov) / 循环指令数。")
    print("      `必要搬参` 是调用实参准备，**不算浪费**（不计入上限）。")
    shutil.rmtree(td, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
