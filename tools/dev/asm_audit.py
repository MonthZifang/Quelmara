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


def hot_loop(rows):
    """找"cmp 大常数 + jcc" 起头的热循环，返回到回边为止的指令序列。

    **要从后往前找**：运行库里也有 `cmp 常数` 的循环（memcpy/alloc 等），
    而且它们在 .text 前面。用户代码（main）在最后，热循环也在最后。
    v4.103 第一版从前往后找，五个基准都匹配到同一条运行库循环（都是 43 条），
    这是明显的识别错误。
    """
    for i in range(len(rows) - 1, -1, -1):
        txt = rows[i][1]
        if BIGCMP.search(txt):
            # 往下找 jcc，再往下找 jmp 回跳
            for j in range(i, min(i + 3, len(rows))):
                if re.search(r"\bj(g|l|le|ge|ne|e|b|a)\b", rows[j][1]):
                    start = j + 1
                    for k in range(start, min(start + 200, len(rows))):
                        if re.match(r"jmp\s+0x([0-9a-f]+)", rows[k][1]):
                            tgt = int(re.match(r"jmp\s+0x([0-9a-f]+)",
                                               rows[k][1]).group(1), 16)
                            if tgt <= rows[k][0]:
                                return rows[start:k + 1]
                    break
    return []


def audit(seq):
    n = len(seq)
    spill = 0
    for i in range(n - 1):
        a = STORE.search(seq[i][1])
        b = LOAD.search(seq[i + 1][1])
        if a and b and a.group(2) == b.group(3):
            spill += 1
    movrr = sum(1 for _, t in seq if MOVRR.search(t))
    return {"insn": n, "spill": spill, "movrr": movrr}


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
    rows.sort(key=lambda kv: -(kv[1]["spill"] + kv[1]["movrr"]))
    print(f"{'bench':22}{'循环指令':>9}{'溢出往返':>10}{'冗余mov':>9}{'浪费占比':>10}")
    print("-" * 62)
    for b, a in rows:
        waste = a["spill"] * 2 + a["movrr"]
        pct = 100.0 * waste / max(a["insn"], 1)
        print(f"{b:22}{a['insn']:9}{a['spill']:10}{a['movrr']:9}{pct:9.0f}%")
    shutil.rmtree(td, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
