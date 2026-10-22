#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X.509 证书链验证测试（v1.26）。

Python 手工构造 root → intermediate → leaf 三级 P-256 证书链并签名，
Quelmara 侧用 std/x509 的 x509_verify_chain 验证。覆盖：
  * 正常链 + 域名匹配（含通配符只匹配一级标签）
  * 域名不匹配 / 通配符跨级
  * 过期证书
  * 中间证书缺失（leaf 直接对 root）
  * 篡改 leaf
  * 根证书自签
  * 有效期解析（UTCTime → Unix 秒）

用法：
    python tests/x509_chain_test.py
    python tests/x509_chain_test.py -v
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
SRC = os.path.join(ROOT, "build", "_x509_chain_probe.qma")
IN = os.path.join(ROOT, "build", "_x509_chain_in.txt")

# ---- secp256r1 ----
P = 2**256 - 2**224 + 2**192 + 2**96 - 1
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
A = P - 3
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
G = (GX, GY)

PROBE = '''module chainprobe

import std.hex
import std.str
import std.time
import std.x509

fn main() {
    let lines = str_split(read_text(args()[0]), "\\n")
    let leaf = hex_decode(str_trim(lines.get(0)))
    let inter = hex_decode(str_trim(lines.get(1)))
    let anchor = hex_decode(str_trim(lines.get(2)))
    let expired = hex_decode(str_trim(lines.get(3)))
    let tampered = hex_decode(str_trim(lines.get(4)))
    let now = wall_ms() / 1000

    let one = vec[str].new(1)
    one.push(inter)
    let none = vec[str].new(0)

    print(x509_verify_chain(leaf, one, anchor, "example.com", now).to_str())
    print(x509_verify_chain(leaf, one, anchor, "www.example.com", now).to_str())
    print(x509_verify_chain(leaf, one, anchor, "a.b.example.com", now).to_str())
    print(x509_verify_chain(leaf, one, anchor, "evil.com", now).to_str())
    print(x509_verify_chain(expired, one, anchor, "example.com", now).to_str())
    print(x509_verify_chain(leaf, none, anchor, "", now).to_str())
    print(x509_verify_chain(anchor, none, anchor, "", now).to_str())
    print(x509_verify_chain(tampered, one, anchor, "example.com", now).to_str())

    let v = x509_validity(leaf)
    print(v.get(0).to_str())
    print(len(x509_san(leaf)).to_str())

    // RSA 根：leaf2(EC) ← inter2(EC) ← root(RSA PKCS#1 v1.5)
    let rroot = hex_decode(str_trim(lines.get(5)))
    let rinter = hex_decode(str_trim(lines.get(6)))
    let rleaf = hex_decode(str_trim(lines.get(7)))
    let rone = vec[str].new(1)
    rone.push(rinter)
    print(x509_verify_chain(rleaf, rone, rroot, "example.com", now).to_str())
    print(x509_verify_chain(rroot, none, rroot, "", now).to_str())
    print(x509_verify_chain(rinter, none, rroot, "", now).to_str())
}
'''


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


# ---------------- RSA（1024 位，测试用） ----------------
def _is_prime(n, k=20):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(k):
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits):
    while True:
        n = random.getrandbits(bits) | (1 << (bits - 1)) | 1
        if _is_prime(n):
            return n


def gen_rsa(bits=1024, e=65537):
    while True:
        p, q = _gen_prime(bits // 2), _gen_prime(bits // 2)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        if phi % e == 0:
            continue
        n = p * q
        if n.bit_length() == bits:
            return n, e, pow(e, -1, phi)


def rsa_sign_pkcs1_sha256(tbs, key):
    n, e, d = key
    k = (n.bit_length() + 7) // 8
    di = bytes.fromhex("3031300d060960864801650304020105000420")
    h = hashlib.sha256(tbs).digest()
    em = b"\x00\x01" + b"\xff" * (k - 3 - len(di) - len(h)) + b"\x00" + di + h
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def spki_rsa(n, e):
    return seq(seq(oid(OID_RSA), tlv(0x05, b"")),
               tlv(0x03, b"\x00" + seq(integer(n), integer(e))))


# ---------------- DER ----------------
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
OID_RSA = "2a864886f70d010101"
OID_SHA256_RSA = "2a864886f70d01010b"
OID_BASIC_CONSTRAINTS = "551d13"
OID_SAN = "551d11"


def name(cn):
    return seq(tlv(0x31, seq(oid(OID_CN), tlv(0x0C, cn.encode()))))


def utctime(s):
    return tlv(0x17, s.encode())


def validity(nb, na):
    return seq(utctime(nb), utctime(na))


def spki(qx, qy):
    point = b"\x04" + qx.to_bytes(32, "big") + qy.to_bytes(32, "big")
    return seq(seq(oid(OID_EC_PUBKEY), oid(OID_PRIME256V1)),
               tlv(0x03, b"\x00" + point))


def ext(oid_hex, val, critical=False):
    body = oid(oid_hex)
    if critical:
        body += tlv(0x01, b"\xff")
    body += tlv(0x04, val)
    return seq(body)


def extensions(*exts):
    return tlv(0xA3, seq(*exts))


def basic_constraints(ca):
    return seq(tlv(0x01, b"\xff") if ca else b"")


def san(*names):
    return seq(*[tlv(0x82, n.encode()) for n in names])


def make_cert(subject_cn, issuer_cn, subject_priv, signer_priv, serial,
              nb, na, exts=b""):
    qx, qy = pmul(subject_priv, G)
    alg = seq(oid(OID_ECDSA_SHA256))
    body = (tlv(0xA0, integer(2)) + integer(serial) + alg +
            name(issuer_cn) + validity(nb, na) + name(subject_cn) +
            spki(qx, qy) + exts)
    tbs = seq(body)
    e = int.from_bytes(hashlib.sha256(tbs).digest(), "big")
    r, s = sign_digest(signer_priv, e)
    sig = tlv(0x03, b"\x00" + seq(integer(r), integer(s)))
    return seq(tbs, alg, sig)


def make_cert_rsa(subject_cn, issuer_cn, subject_priv, rsa_key, serial,
                  nb, na, exts=b""):
    """主体用 EC 公钥，但由 RSA 根签发（混合链）。"""
    qx, qy = pmul(subject_priv, G)
    alg = seq(oid(OID_SHA256_RSA))
    body = (tlv(0xA0, integer(2)) + integer(serial) + alg +
            name(issuer_cn) + validity(nb, na) + name(subject_cn) +
            spki(qx, qy) + exts)
    tbs = seq(body)
    sig = rsa_sign_pkcs1_sha256(tbs, rsa_key)
    return seq(tbs, alg, tlv(0x03, b"\x00" + sig))


def make_root_rsa(cn, rsa_key, serial, nb, na):
    alg = seq(oid(OID_SHA256_RSA))
    n, _e, _d = rsa_key
    body = (tlv(0xA0, integer(2)) + integer(serial) + alg +
            name(cn) + validity(nb, na) + name(cn) +
            spki_rsa(n, 65537) +
            extensions(ext(OID_BASIC_CONSTRAINTS, basic_constraints(True), True)))
    tbs = seq(body)
    sig = rsa_sign_pkcs1_sha256(tbs, rsa_key)
    return seq(tbs, alg, tlv(0x03, b"\x00" + sig))


def build_probe():
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    with open(SRC, "w", encoding="utf-8") as f:
        f.write(PROBE)
    r = subprocess.run([PY, CLI, "build", SRC, "--target", "win",
                        "-o", os.path.join(ROOT, "build", "_x509_chain_probe.exe")],
                       cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        raise SystemExit("probe 编译失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    build_probe()
    random.seed(20261022)

    root_priv = random.randrange(1, N)
    inter_priv = random.randrange(1, N)
    leaf_priv = random.randrange(1, N)

    root = make_cert("Quelmara Root", "Quelmara Root", root_priv, root_priv, 1,
                     "200101000000Z", "400101000000Z",
                     extensions(ext(OID_BASIC_CONSTRAINTS, basic_constraints(True), True)))
    inter = make_cert("Quelmara Inter", "Quelmara Root", inter_priv, root_priv, 2,
                      "200101000000Z", "400101000000Z",
                      extensions(ext(OID_BASIC_CONSTRAINTS, basic_constraints(True), True)))
    leaf = make_cert("example.com", "Quelmara Inter", leaf_priv, inter_priv, 3,
                     "200101000000Z", "400101000000Z",
                     extensions(ext(OID_SAN, san("example.com", "*.example.com"))))
    expired = make_cert("example.com", "Quelmara Inter", leaf_priv, inter_priv, 4,
                        "100101000000Z", "110101000000Z",
                        extensions(ext(OID_SAN, san("example.com"))))

    rsa_key = gen_rsa(1024)
    rsa_root = make_root_rsa("Quelmara RSA Root", rsa_key, 9,
                             "200101000000Z", "400101000000Z")
    inter2_priv = random.randrange(1, N)
    leaf2_priv = random.randrange(1, N)
    rsa_inter = make_cert_rsa("Quelmara RSA Inter", "Quelmara RSA Root",
                              inter2_priv, rsa_key, 10,
                              "200101000000Z", "400101000000Z",
                              extensions(ext(OID_BASIC_CONSTRAINTS, basic_constraints(True), True)))
    rsa_leaf = make_cert("example.com", "Quelmara RSA Inter", leaf2_priv,
                         inter2_priv, 11, "200101000000Z", "400101000000Z",
                         extensions(ext(OID_SAN, san("example.com"))))

    bad = bytearray(leaf)
    idx = bad.find(b"example.com")
    bad[idx] ^= 0x01
    tampered = bytes(bad)

    with open(IN, "w", encoding="ascii") as f:
        for c in (leaf, inter, root, expired, tampered,
                  rsa_root, rsa_inter, rsa_leaf):
            f.write(c.hex() + "\n")

    r = subprocess.run([os.path.join(ROOT, "build", "_x509_chain_probe.exe"), IN],
                       cwd=ROOT, capture_output=True, timeout=600)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "replace"))
        raise SystemExit(f"probe 失败 rc={r.returncode}")
    got = [ln.strip() for ln in r.stdout.decode().splitlines() if ln.strip()]

    expect = ["1", "1", "0", "0", "0", "0", "1", "0",
              str(1577836800), "2",
              "1", "1", "1"]   # 2020-01-01 UTC；2 个 SAN；RSA 根三级链
    labels = ["正常链 + 域名", "通配符一级", "通配符跨级拒绝", "域名不匹配",
              "过期拒绝", "缺中间证书拒绝", "根自签", "篡改拒绝",
              "有效期解析", "SAN 数量",
              "RSA 根三级链", "RSA 根自签", "RSA 中间证书"]

    ok = 0
    bad_n = 0
    for i, (lab, want) in enumerate(zip(labels, expect)):
        gotv = got[i] if i < len(got) else "<missing>"
        if gotv == want:
            ok += 1
            if args.verbose:
                print(f"  [ok]   {lab} = {gotv}")
        else:
            bad_n += 1
            print(f"  [FAIL] {lab}: got={gotv} want={want}")
    print("-" * 56)
    print(f"PASS={ok} FAIL={bad_n}")
    return 1 if bad_n else 0


if __name__ == "__main__":
    sys.exit(main())
