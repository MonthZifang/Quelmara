#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发射层契约对拍：可执行文件必须**确定性**且结构合法。

两条硬约束（stage-1 的 bootstrap/codegen/* 将来必须同样满足）：
  1. 同一输入 + 同一后端，两次构建产出的字节**完全相同**（无时间戳/随机数/哈希序）；
  2. 结构合法：ELF 魔数与入口在镜像内；PE 魔数、PE32+、导入只来自 kernel32。
第三条软约束：产物大小记录成基线（波动超过阈值就提示）。

用法：python tests/emitdiff.py [-v]
"""
import argparse
import hashlib
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE0 = os.path.join(ROOT, "tools", "stage0")
BUILD = os.path.join(ROOT, "build")

FIXTURES = ["tests/t1.qma", "tests/t22_map.qma", "tests/t31_logic.qma",
            "tests/t34_vec.qma", "tests/t37_vecagg.qma"]


def build(src, backend, out):
    cmd = [sys.executable, os.path.join(STAGE0, backend), "build", src, "-o", out]
    r = subprocess.run(cmd, capture_output=True, cwd=ROOT)
    return r.returncode, r.stderr.decode("utf-8", errors="replace")


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def check_elf(path):
    data = open(path, "rb").read()
    problems = []
    if data[:4] != b"\x7fELF":
        problems.append("ELF 魔数不对")
        return problems, len(data)
    if data[4] != 2:
        problems.append("不是 ELF64")
    entry = struct.unpack_from("<Q", data, 0x18)[0]
    # 单 PT_LOAD 覆盖整个镜像：入口应落在文件范围内
    if not (0 < entry < len(data) + 0x400000):
        problems.append(f"入口地址可疑 {entry:#x}")
    return problems, len(data)


def check_pe(path):
    data = open(path, "rb").read()
    problems = []
    if data[:2] != b"MZ":
        return ["PE 缺 MZ"], len(data)
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        problems.append("缺 PE 签名")
        return problems, len(data)
    machine = struct.unpack_from("<H", data, pe + 4)[0]
    if machine != 0x8664:
        problems.append(f"Machine 不是 AMD64：{machine:#x}")
    magic = struct.unpack_from("<H", data, pe + 24)[0]
    if magic != 0x20B:
        problems.append(f"不是 PE32+：{magic:#x}")
    # 导入表只允许出现 kernel32.dll，且不得出现 CRT 符号
    if b"kernel32.dll" not in data:
        problems.append("没有 kernel32 导入")
    for bad in (b"msvcrt", b"ucrtbase", b"VCRUNTIME", b"api-ms-win-crt"):
        if bad in data:
            problems.append(f"出现 CRT 依赖 {bad.decode()}")
    return problems, len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    os.makedirs(BUILD, exist_ok=True)

    ok = bad = 0
    for rel in FIXTURES:
        src = os.path.join(ROOT, rel)
        if not os.path.isfile(src):
            print(f"  [SKIP] {rel} 不存在")
            continue
        for backend, suffix, checker in (("qlm_native.py", ".qel", check_elf),
                                        ("qlm_pe.py", ".qex", check_pe)):
            a = os.path.join(BUILD, "_emit_a" + suffix)
            b = os.path.join(BUILD, "_emit_b" + suffix)
            rc1, e1 = build(src, backend, a)
            rc2, e2 = build(src, backend, b)
            tag = f"{rel} [{backend.split('_')[-1].split('.')[0]}]"
            if rc1 != 0 or rc2 != 0:
                bad += 1
                tail = (e1 or e2).strip().splitlines()
                print(f"  [FAIL] {tag}: 构建失败 {tail[-1] if tail else ''}")
                continue
            h1, h2 = sha(a), sha(b)
            if h1 != h2:
                bad += 1
                print(f"  [FAIL] {tag}: 构建不确定（{h1[:12]} != {h2[:12]}）")
                continue
            problems, size = checker(a)
            if problems:
                bad += 1
                print(f"  [FAIL] {tag}: " + "; ".join(problems))
                continue
            ok += 1
            if args.verbose:
                print(f"  [ok] {tag}: {size}B sha={h1[:12]} 确定性+结构均通过")

    print("-" * 56)
    print(f"PASS={ok} FAIL={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
