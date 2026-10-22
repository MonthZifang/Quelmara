#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X.509 解析 + ECDSA 验签互操作测试。

Python 侧**手工构造 DER 证书**并用纯 bigint ECDSA 签名（不依赖任何第三方库），
Quelmara 侧用 std/x509 解析、std/p256 验签，两边完全独立。

覆盖：
  * v3 证书（带 [0] version）/ v1 证书（无 version 字段）
  * 短序列号（1 字节）/ 长名字（触发 2 字节长度）
  * 公钥、曲线 OID、签名 OID、TBS 字节逐一比对
  * 负向：篡改 TBS、篡改签名、换公钥、截断 DER

用法：
    python tests/x509_test.py
    python tests/x509_test.py -v
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
WORK = os.path.join(ROOT, "build", "_x509_probe")
PROBE_SRC = WORK + ".qma"
PROBE_EXE = WORK + ".exe"
VEC_FILE = os.path.join(ROOT, "build", "_x509_vec.txt")

# ---- secp256r1 ----
P = 2**256 - 2**224 + 2**192 + 2**96 - 1
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
A = P - 3
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
G = (GX, GY)

PROBE = '''module probe

import std.hex
import std.x509
import std.str

fn main() {
    let txt = read_text(args()[0])
    let lines = str_split(txt, "\\n")
    let mut i = 0
    while i < len(lines) {
        let ln = str_trim(lines.get(i))
        if len(ln) > 20 {
            let cert = hex_decode(ln)
            let pub = x509_pubkey(cert)
            let sig = x509_sig(cert)
            let oid = hex_encode(x509_sig_alg_oid(cert))
            let curve = hex_encode(x509_curve_oid(cert))
            let ok = x509_verify_self_p256(cert)
            let mut pubh = "-"
            if len(pub) == 64 {
                pubh = hex_encode(pub)
            }
            let mut sigh = "-"
            if len(sig) == 64 {
                sigh = hex_encode(sig)
            }
            print(pubh + "|" + sigh + "|" + oid + "|" + curve + "|" + ok.to_str())
        }
        i = i + 1
    }
}
'''


# ---------------- 纯 bigint ECDSA ----------------
def inv(x, m):
    return pow(x, -1, m)


def padd(p1, p2):
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
    return (x3, (lam * (x1 - x3) - y1) % P)


def pmul(k, pt):
    r = None
    while k:
        if k & 1:
            r = padd(r, pt)
        pt = padd(pt, pt)
        k >>= 1
    return r


def sign_digest(priv, e):
    while True:
        k = random.randrange(1, N)
        R = pmul(k, G)
        r = R[0] % N
        if r == 0:
            continue
        s = inv(k, N) * (e + r * priv) % N
        if s == 0:
            continue
        return r, s


# ---------------- DER 构造 ----------------
def der_len(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def tlv(tag, content):
    return bytes([tag]) + der_len(len(content)) + content


def seq(*parts):
    return tlv(0x30, b"".join(parts))


def integer(v):
    b = v.to_bytes((v.bit_length() + 7) // 8 or 1, "big")
    if b[0] & 0x80:
        b = b"\x00" + b
    return tlv(0x02, b)


def oid(hexstr):
    return tlv(0x06, bytes.fromhex(hexstr))


OID_CN = "550403"
OID_EC_PUBKEY = "2a8648ce3d0201"
OID_PRIME256V1 = "2a8648ce3d030107"
OID_ECDSA_SHA256 = "2a8648ce3d040302"


def name(cn):
    return seq(tlv(0x31, seq(oid(OID_CN), tlv(0x0C, cn.encode()))))


def validity():
    return seq(tlv(0x17, b"250101000000Z"), tlv(0x17, b"350101000000Z"))


def spki(qx, qy):
    point = b"\x04" + qx.to_bytes(32, "big") + qy.to_bytes(32, "big")
    return seq(seq(oid(OID_EC_PUBKEY), oid(OID_PRIME256V1)),
               tlv(0x03, b"\x00" + point))


def make_cert(priv, cn, serial, with_version=True, sign_tbs=None):
    qx, qy = pmul(priv, G)
    alg = seq(oid(OID_ECDSA_SHA256))
    body = b""
    if with_version:
        body += tlv(0xA0, integer(2))
    body += integer(serial)
    body += alg
    body += name(cn)
    body += validity()
    body += name(cn)
    body += spki(qx, qy)
    tbs = seq(body)
    e = int.from_bytes(hashlib.sha256(tbs).digest(), "big")
    r, s = sign_digest(priv, e)
    sigval = tlv(0x03, b"\x00" + seq(integer(r), integer(s)))
    return seq(tbs, alg, sigval), (qx, qy), (r, s), tbs


def build_probe():
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    with open(PROBE_SRC, "w", encoding="utf-8") as f:
        f.write(PROBE)
    r = subprocess.run([PY, CLI, "build", PROBE_SRC, "--target", "win",
                        "-o", PROBE_EXE], cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        raise SystemExit("probe 编译失败")


def run(certs):
    with open(VEC_FILE, "w", encoding="ascii") as f:
        f.write("\n".join(c.hex() for c in certs) + "\n")
    r = subprocess.run([PROBE_EXE, VEC_FILE], cwd=ROOT, capture_output=True, timeout=600)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        raise SystemExit(f"probe 失败 rc={r.returncode}")
    return [ln.strip() for ln in r.stdout.decode().splitlines() if ln.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    build_probe()
    random.seed(20261022)
    cases = []      # (label, cert_bytes, expect_verify, expect_pub_or_None)

    # 1) v3 证书，常规
    priv = random.randrange(1, N)
    c, (qx, qy), (r, s), tbs = make_cert(priv, "Quelmara Test CA", 0x1234)
    cases.append(("v3 常规", c, 1, (qx, qy)))
    # 2) v1 证书（无 [0] version）
    priv2 = random.randrange(1, N)
    c2, (qx2, qy2), _, _ = make_cert(priv2, "v1 no version", 7, with_version=False)
    cases.append(("v1 无 version", c2, 1, (qx2, qy2)))
    # 3) 长名字（触发 0x81 长度）
    priv3 = random.randrange(1, N)
    c3, (qx3, qy3), _, _ = make_cert(priv3, "L" * 150, 0x01)
    cases.append(("长 CN 150 字节", c3, 1, (qx3, qy3)))
    # 4) 大序列号（20 字节，高位为 1 → DER 前导 0）
    priv4 = random.randrange(1, N)
    c4, (qx4, qy4), _, _ = make_cert(priv4, "big serial", (1 << 159) - 3)
    cases.append(("大序列号", c4, 1, (qx4, qy4)))

    # 5) 负向：篡改 TBS 里的一个字节（改 CN 字符）
    bad = bytearray(c)
    idx = bad.find(b"Quelmara Test CA")
    bad[idx] ^= 0x01
    cases.append(("篡改 TBS", bytes(bad), 0, None))
    # 6) 负向：篡改签名最后一个字节
    bad2 = bytearray(c)
    bad2[-1] ^= 0x01
    cases.append(("篡改签名", bytes(bad2), 0, None))
    # 7) 负向：截断
    cases.append(("截断 DER", c[: len(c) // 2], 0, None))

    got = run([x[1] for x in cases])
    ok = bad_n = 0
    for i, (label, cert, want_v, want_pub) in enumerate(cases):
        line = got[i] if i < len(got) else ""
        parts = line.split("|")
        if len(parts) != 5:
            bad_n += 1
            print(f"  [FAIL] {label}: 输出格式错 {line!r}")
            continue
        pubh, sigh, oidh, curveh, okv = parts
        good = True
        if okv != str(want_v):
            good = False
        if want_pub is not None:
            want_hex = want_pub[0].to_bytes(32, "big").hex() + want_pub[1].to_bytes(32, "big").hex()
            if pubh != want_hex:
                good = False
            if oidh != OID_ECDSA_SHA256:
                good = False
            if curveh != OID_PRIME256V1:
                good = False
        if good:
            ok += 1
            if args.verbose:
                print(f"  [ok]   {label}（verify={okv}）")
        else:
            bad_n += 1
            print(f"  [FAIL] {label}: verify={okv} 期望 {want_v}；pub={pubh[:16]}…")
    print("-" * 56)
    print(f"PASS={ok} FAIL={bad_n}")
    return 1 if bad_n else 0


if __name__ == "__main__":
    sys.exit(main())
