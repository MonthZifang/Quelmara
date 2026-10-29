#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""std/net/dns 差分测试：Quelmara 的 DNS 报文构造/解析 vs Python 独立实现。

Python 侧**完全独立**地拼报文、解报文（不调用任何 Quelmara 代码），
两边对同一批输入产出逐字节可比的结论。

覆盖：
  * dns_build_query：报文头 / QNAME 标签编码 / QTYPE / QCLASS 逐字节比对
  * 边界：空名、超长段（>63）、连续点、开头点、超长总长、尾点形态
  * dns_parse_a：手工构造应答（单 A / 多 A / CNAME+A / 压缩指针 / 多 Question）
  * 负向：ID 不匹配、QR=0、RCODE!=0、ANCOUNT=0、截断、rdlen!=4、非 A 记录
  * dns_ip4_str / dns_resolv_ns 的文本层

用法：
    python tests/dns_test.py
    python tests/dns_test.py -v
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
WORK = os.path.join(ROOT, "build", "_dns_probe")
PROBE_SRC = WORK + ".qma"
PROBE_EXE = WORK + ".exe" if os.name == "nt" else WORK
VEC = os.path.join(ROOT, "build", "_dns_vec.txt")
VERBOSE = False


# ---------------------------------------------------------------------------
# Python 参考实现（独立于 Quelmara 侧）
# ---------------------------------------------------------------------------

def py_build_query(name):
    """返回 bytes 或 None（非法名）。"""
    if not name or len(name) > 253:
        return None
    labels = []
    cur = bytearray()
    for ch in name.encode("ascii", "replace"):
        if ch == 46:                      # '.'
            if not cur or len(cur) > 63:
                return None
            labels.append(bytes(cur))
            cur = bytearray()
        else:
            cur.append(ch)
            if len(cur) > 63:
                return None
    if cur:
        labels.append(bytes(cur))
    if not labels:
        return None
    qn = bytearray()
    for lb in labels:
        qn.append(len(lb))
        qn.extend(lb)
    qn.append(0)
    hdr = bytes([0x12, 0x34, 0x01, 0x00, 0x00, 0x01,
                 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    return hdr + bytes(qn) + bytes([0x00, 0x01, 0x00, 0x01])


def py_skip_name(msg, off):
    p = off
    guard = 0
    while p < len(msg) and guard < 128:
        c = msg[p]
        if c == 0:
            return p + 1
        if c >= 192:
            return p + 2 if p + 1 < len(msg) else None
        p += c + 1
        guard += 1
    return None


def py_parse_a(msg):
    """返回网络序 u32 或 0。与 Quelmara 侧同一套校验规则。"""
    if len(msg) < 12:
        return 0
    if msg[0] != 0x12 or msg[1] != 0x34:
        return 0
    if not (msg[2] & 0x80):
        return 0
    if msg[3] & 0x0F:
        return 0
    qd = (msg[4] << 8) | msg[5]
    an = (msg[6] << 8) | msg[7]
    if an == 0:
        return 0
    p = 12
    for _ in range(qd):
        p = py_skip_name(msg, p)
        if p is None or p + 4 > len(msg):
            return 0
        p += 4
    for _ in range(an):
        p = py_skip_name(msg, p)
        if p is None or p + 10 > len(msg):
            return 0
        rtype = (msg[p] << 8) | msg[p + 1]
        rclass = (msg[p + 2] << 8) | msg[p + 3]
        rdlen = (msg[p + 8] << 8) | msg[p + 9]
        rd = p + 10
        if rtype == 1 and rclass == 1 and rdlen == 4:
            if rd + 4 > len(msg):
                return 0
            return msg[rd] | (msg[rd + 1] << 8) | (msg[rd + 2] << 16) | (msg[rd + 3] << 24)
        if rd + rdlen > len(msg):
            return 0
        p = rd + rdlen
    return 0


def py_resolv_ns(text):
    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if parts and parts[0] == "nameserver" and len(parts) > 1:
            return parts[1]
    return ""


def py_resolv_all(text):
    """返回全部 nameserver（顺序）。空/注释行跳过，行尾注释截断。"""
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if parts and parts[0] == "nameserver" and len(parts) > 1:
            out.append(parts[1])
    return out


def py_ip4_str(ip):
    return "%d.%d.%d.%d" % (ip & 0xFF, (ip >> 8) & 0xFF,
                            (ip >> 16) & 0xFF, (ip >> 24) & 0xFF)


# ---------------------------------------------------------------------------
# 夹具：手工构造应答报文
# ---------------------------------------------------------------------------

def mk_resp(answers, qd=1, rcode=0, ident=b"\x12\x34", qr=1, qname=b"\x07example\x03com\x00"):
    """answers: [(name_bytes, type, rclass, rdata)]"""
    flags = (0x80 if qr else 0x00) | 0x01
    hdr = ident + bytes([flags, rcode,
                         0, qd, 0, len(answers), 0, 0, 0, 0])
    body = bytearray()
    for _ in range(qd):
        body.extend(qname)
        body.extend(b"\x00\x01\x00\x01")
    for nm, rt, rc, rd in answers:
        body.extend(nm)
        body.extend(bytes([rt >> 8, rt & 0xFF, rc >> 8, rc & 0xFF]))
        body.extend(b"\x00\x00\x00\x3c")          # TTL
        body.extend(bytes([len(rd) >> 8, len(rd) & 0xFF]))
        body.extend(rd)
    return hdr + bytes(body)


def esc(b):
    """bytes -> Quelmara 侧能用的转义串（只放可打印 ASCII + \\x 转义）。"""
    out = []
    for c in b:
        if 32 <= c < 127 and c not in (34, 92):
            out.append(chr(c))
        else:
            out.append("\\x%02x" % c)
    return "".join(out)


# ---------------------------------------------------------------------------
# 探针程序
# ---------------------------------------------------------------------------

def build_probe(cases):
    """cases: [(id, kind, arg)] -> 生成 .qma 并编译。"""
    lines = ["import std.net.dns", "import std.hex", "", "fn main() {"]
    for cid, kind, arg in cases:
        if kind == "build":
            lines.append(f'    let q{cid} = dns_build_query("{esc(arg.encode())}")')
            lines.append(f'    print(len(q{cid}))')
            lines.append(f'    print(hex_encode(q{cid}))')
        elif kind == "parse":
            lines.append(f'    let r{cid} = "{esc(arg)}"')
            lines.append(f'    print(dns_parse_a(r{cid}))')
        elif kind == "ip4":
            lines.append(f'    print(dns_ip4_str({arg}))')
        elif kind == "resolv":
            lines.append(f'    print(dns_resolv_ns("{esc(arg.encode())}"))')
        elif kind == "resolvall":
            lines.append(f'    let ra{cid} = dns_resolv_all("{esc(arg.encode())}")')
            lines.append(f'    print(len(ra{cid}))')
            lines.append(f'    let mut ri{cid} = 0')
            lines.append(f'    while ri{cid} < len(ra{cid}) {{')
            lines.append(f'        print(ra{cid}.get(ri{cid}))')
            lines.append(f'        ri{cid} = ri{cid} + 1')
            lines.append('    }')
    lines.append("}")
    src = "\n".join(lines) + "\n"
    with open(PROBE_SRC, "w", encoding="utf-8") as f:
        f.write(src)
    return src


def run_probe():
    r = subprocess.run([PY, CLI, "build", PROBE_SRC, "--target", TARGET,
                        "-o", PROBE_EXE], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit("探针编译失败")
    r = subprocess.run([PROBE_EXE], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit("探针运行失败 rc=%d" % r.returncode)
    return r.stdout.split("\n")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

TARGET = "native"


def main():
    global VERBOSE, TARGET
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--target", default=None)
    args = ap.parse_args()
    VERBOSE = args.verbose
    if args.target:
        TARGET = args.target
    elif os.name == "nt":
        TARGET = "win"

    os.makedirs(os.path.dirname(WORK), exist_ok=True)

    cases = []
    expect = []
    cid = 0

    # ---- dns_build_query：合法名 ----
    for name in ("example.com", "a.b", "x", "a.b.c.d.e.f",
                 "verylonglabel0123456789012345678901234567890123456789012345678.com"):
        cid += 1
        cases.append((cid, "build", name))
        ref = py_build_query(name)
        expect.append(("build", name, ref))

    # ---- dns_build_query：非法名（两侧都该判非法）----
    for name in ("", ".", "a..b", ".a.b", "a." * 40,
                 "l" * 64 + ".com"):
        cid += 1
        cases.append((cid, "build", name))
        ref = py_build_query(name)
        expect.append(("build", name, ref))

    # ---- dns_parse_a：正向 ----
    qn = b"\x07example\x03com\x00"
    cname = b"\x05alias\x07example\x03com\x00"
    ip1 = bytes([93, 184, 216, 34])
    ip2 = bytes([1, 2, 3, 4])
    # 单 A，name 用压缩指针指回 Question（0xC00C）
    resp_ptr = mk_resp([(b"\xc0\x0c", 1, 1, ip1)])
    # CNAME 在前，A 在后（必须跳过 CNAME）
    resp_cname = mk_resp([(cname, 5, 1, b"\x05other\x03com\x00"),
                          (cname, 1, 1, ip2)])
    # 两条 A，取第一条
    resp_two = mk_resp([(b"\xc0\x0c", 1, 1, ip1), (b"\xc0\x0c", 1, 1, ip2)])
    # 两条 Question
    resp_qd2 = mk_resp([(b"\xc0\x0c", 1, 1, ip1)], qd=2)
    for tag, rb in (("ptr", resp_ptr), ("cname", resp_cname),
                    ("two", resp_two), ("qd2", resp_qd2)):
        cid += 1
        cases.append((cid, "parse", rb))
        expect.append(("parse", tag, py_parse_a(rb)))

    # ---- dns_parse_a：负向 ----
    negs = [
        ("short", b"\x12\x34\x81"),
        ("badid", mk_resp([(b"\xc0\x0c", 1, 1, ip1)], ident=b"\xde\xad")),
        ("qr0", mk_resp([(b"\xc0\x0c", 1, 1, ip1)], qr=0)),
        ("rcode", mk_resp([(b"\xc0\x0c", 1, 1, ip1)], rcode=3)),
        ("noans", mk_resp([])),
        ("rdlen3", mk_resp([(b"\xc0\x0c", 1, 1, b"\x01\x02\x03")])),
        ("txt", mk_resp([(b"\xc0\x0c", 16, 1, b"\x03abc")])),
        ("trunc", resp_ptr[:-3]),
        ("empty", b""),
    ]
    for tag, rb in negs:
        cid += 1
        cases.append((cid, "parse", rb))
        expect.append(("parse", tag, py_parse_a(rb)))

    # ---- dns_ip4_str ----
    for ip in (0x0100007F, 0x0101A8C0, 0xFFFFFFFF, 0):
        cid += 1
        cases.append((cid, "ip4", ip))
        expect.append(("ip4", str(ip), py_ip4_str(ip)))

    # ---- dns_resolv_ns ----
    rc = ("# comment\nnameserver 8.8.8.8\nnameserver 1.1.1.1\n"
          "search example.com\noptions ndots:5\n")
    rc2 = "  nameserver\t192.168.1.1\n"
    rc3 = "# only comments\n# nameserver 9.9.9.9\n"
    for tag, txt in (("basic", rc), ("tab", rc2), ("none", rc3)):
        cid += 1
        cases.append((cid, "resolv", txt))
        expect.append(("resolv", tag, py_resolv_ns(txt)))

    # ---- dns_resolv_all（v3.05：多 nameserver）----
    ra_cases = [
        ("multi", rc),
        ("one", rc2),
        ("none", rc3),
        ("empty", ""),
        ("blank", "\n\n  \n"),
        ("trailcomment", "nameserver 8.8.8.8 # primary\n"),
        ("mixed", "# c\nnameserver 1.1.1.1\nsearch x\nnameserver 9.9.9.9\n"),
    ]
    for tag, txt in ra_cases:
        cid += 1
        cases.append((cid, "resolvall", txt))
        expect.append(("resolvall", tag, py_resolv_all(txt)))

    # ---- 编译并运行探针 ----
    if VERBOSE:
        print("生成探针：%s（%d 个用例）" % (PROBE_SRC, len(cases)))
    build_probe(cases)
    out = run_probe()

    # ---- 逐项比对 ----
    pos = 0
    passed = failed = 0
    fails = []

    def take():
        nonlocal pos
        v = out[pos]
        pos += 1
        return v

    for kind, tag, ref in expect:
        if kind == "build":
            ln = take()
            hx = take()
            got_len = int(ln)
            got_hex = hx.strip()
            if ref is None:
                ok = (got_len == 0 and got_hex == "")
                want = "空（非法名）"
                got = "len=%d hex=%s" % (got_len, got_hex[:32])
            else:
                ok = (got_len == len(ref) and got_hex == ref.hex())
                want = "len=%d %s" % (len(ref), ref.hex()[:48])
                got = "len=%d %s" % (got_len, got_hex[:48])
        elif kind == "parse":
            got_v = int(take())
            ok = (got_v == ref)
            want = str(ref)
            got = str(got_v)
        elif kind == "ip4":
            got_s = take().strip()
            ok = (got_s == ref)
            want = ref
            got = got_s
        elif kind == "resolvall":
            cnt = int(take())
            got_list = [take().strip() for _ in range(cnt)]
            ok = (got_list == ref)
            want = repr(ref)
            got = repr(got_list)
        else:  # resolv
            got_s = take().strip()
            ok = (got_s == ref)
            want = repr(ref)
            got = repr(got_s)

        if ok:
            passed += 1
            if VERBOSE:
                print("  ✅ %-6s %-16s %s" % (kind, tag[:16], got))
        else:
            failed += 1
            fails.append((kind, tag, want, got))
            print("  ❌ %-6s %-16s 期望 %s，实际 %s" % (kind, tag[:16], want, got))

    print("-" * 56)
    print("PASS=%d FAIL=%d" % (passed, failed))
    if failed:
        for kind, tag, want, got in fails[:5]:
            print("  失败项 %s/%s: 期望 %s 实际 %s" % (kind, tag, want, got))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
