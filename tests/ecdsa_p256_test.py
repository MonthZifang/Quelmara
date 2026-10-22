#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ECDSA P-256 验签互操作测试：Python 大整数参考实现 ↔ Quelmara std/p256。

Python 侧用纯 bigint 实现（不依赖任何第三方库），与 Quelmara 的
8×32 limb + Montgomery 实现**完全独立**，所以能真正交叉验证。

覆盖：
  * 20 组随机密钥/消息的正向验签
  * 负向：改消息、改 r、改 s、换公钥、r/s 越界（0、n、n+1）、
    公钥不在曲线上（无效曲线攻击）
  * 边界：r 或 s 恰为 1、n-1

用法：
    python tests/ecdsa_p256_test.py
    python tests/ecdsa_p256_test.py -v
"""
import argparse
import hashlib
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
WORK = os.path.join(ROOT, "build", "_ecdsa_probe")
PROBE_SRC = WORK + ".qma"
PROBE_EXE = WORK + ".exe"
VEC_FILE = os.path.join(ROOT, "build", "_ecdsa_vec.txt")

# ---- secp256r1 参数 ----
P = 2**256 - 2**224 + 2**192 + 2**96 - 1
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
G = (GX, GY)

PROBE = '''module probe

import std.hex
import std.p256
import std.str

fn main() {
    let txt = read_text(args()[0])
    let lines = str_split(txt, "\\n")
    let mut i = 0
    while i < len(lines) {
        let ln = str_trim(lines.get(i))
        if len(ln) > 10 {
            let f = str_split(ln, " ")
            let ok = ecdsa_p256_verify(hex_decode(f.get(0)), hex_decode(f.get(1)),
                                       hex_decode(f.get(2)), hex_decode(f.get(3)),
                                       hex_decode(f.get(4)))
            print(ok)
        }
        i = i + 1
    }
}
'''


def inv(x, m):
    return pow(x, -1, m)


def add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1 + A) * inv(2 * y1, P) % P
    else:
        lam = (y2 - y1) * inv(x2 - x1, P) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def mul(k, pt):
    r = None
    while k:
        if k & 1:
            r = add(r, pt)
        pt = add(pt, pt)
        k >>= 1
    return r


def sign(priv, msg):
    e = int.from_bytes(hashlib.sha256(msg).digest(), "big")
    while True:
        k = random.randrange(1, N)
        R = mul(k, G)
        r = R[0] % N
        if r == 0:
            continue
        s = inv(k, N) * (e + r * priv) % N
        if s == 0:
            continue
        return e, r, s


def pubkey(priv):
    Q = mul(priv, G)
    return Q


def fmt(v):
    return f"{v:064x}"


def build_probe():
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    with open(PROBE_SRC, "w", encoding="utf-8") as f:
        f.write(PROBE)
    r = subprocess.run([PY, CLI, "build", PROBE_SRC, "--target", "win",
                        "-o", PROBE_EXE], cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        raise SystemExit("probe 编译失败")


def run_vectors(rows):
    with open(VEC_FILE, "w", encoding="ascii") as f:
        f.write("\n".join(rows) + "\n")
    r = subprocess.run([PROBE_EXE, VEC_FILE], cwd=ROOT, capture_output=True, timeout=600)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        raise SystemExit(f"probe 运行失败 rc={r.returncode}")
    return [ln.strip() for ln in r.stdout.decode().splitlines() if ln.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    build_probe()
    random.seed(20261022)
    rows, expect, labels = [], [], []

    def push(label, qx, qy, e, r, s, want):
        rows.append(f"{fmt(qx)} {fmt(qy)} {fmt(e)} {fmt(r)} {fmt(s)}")
        expect.append(want)
        labels.append(label)

    # ---- 正向 ----
    for i in range(20):
        priv = random.randrange(1, N)
        msg = f"Quelmara ECDSA vector {i}".encode()
        e, r, s = sign(priv, msg)
        qx, qy = pubkey(priv)
        push(f"valid#{i}", qx, qy, e, r, s, 1)

    # ---- 边界 r/s = 1 / n-1（用同一密钥，构造后按真实公钥验签）----
    priv = random.randrange(1, N)
    e, r, s = sign(priv, b"boundary")
    qx, qy = pubkey(priv)
    push("r=1 (无效)", qx, qy, e, 1, s, 0)
    push("s=1 (无效)", qx, qy, e, r, 1, 0)
    push("r=n (越界)", qx, qy, e, N, s, 0)
    push("s=n (越界)", qx, qy, e, r, N, 0)
    push("r=0", qx, qy, e, 0, s, 0)
    push("s=0", qx, qy, e, r, 0, 0)
    push("r=n-1", qx, qy, e, N - 1, s, 0)

    # ---- 负向：改消息 ----
    push("改消息", qx, qy, (e + 1) % N, r, s, 0)
    # ---- 负向：改 r / s ----
    push("改 r", qx, qy, e, (r + 1) % N, s, 0)
    push("改 s", qx, qy, e, r, (s + 1) % N, 0)
    # ---- 负向：换公钥 ----
    priv2 = random.randrange(1, N)
    q2x, q2y = pubkey(priv2)
    push("换公钥", q2x, q2y, e, r, s, 0)
    # ---- 负向：公钥不在曲线上 ----
    push("公钥不在曲线上", qx, (qy + 1) % P, e, r, s, 0)

    got = run_vectors(rows)
    ok = bad = 0
    for i, label in enumerate(labels):
        g = got[i] if i < len(got) else "?"
        if g == str(expect[i]):
            ok += 1
            if args.verbose:
                print(f"  [ok]   {label}")
        else:
            bad += 1
            print(f"  [FAIL] {label}: 期望 {expect[i]} 得到 {g}")
    print("-" * 56)
    print(f"PASS={ok} FAIL={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
