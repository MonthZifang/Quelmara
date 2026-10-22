#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对真实服务器跑一次 TLS 1.3 客户端握手（手动检查，不进 CI）。

用法：
    python tools/dev/tls_probe.py                 # 默认 cloudflare.com
    python tools/dev/tls_probe.py example.com
    python tools/dev/tls_probe.py example.com -v

流程：
 1. 生成临时探针 `build/_tls_probe.qma`（固定 x25519 私钥与 ClientHello random）；
 2. 探针输出 ClientHello 记录（hex）；
 3. Python socket 发到 host:443，收满服务器 flight（空闲 1 s 视为收完）；
 4. 探针解析 flight：验证服务器 Finished 与 CertificateVerify；
 5. 打印 ok / cv / 证书公钥。

`ok=1` = Finished 通过；`cv=1` = ECDSA-P256 验签通过，`cv=-1` = RSA 等未支持算法。
只依赖标准库；需要能访问目标 443 端口。
"""
import os
import socket
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
SRC = os.path.join(ROOT, "build", "_tls_probe.qma")
IN = os.path.join(ROOT, "build", "_tls_probe_in.txt")

PRIV = "49af42ba7f7994852d713ef2784bcbcaa7911de26adc5642cb634540e7ea5005"
RANDOM = "cb34ecb1e78163ba1c38c6dacb196a6dffa21a8d9912ec18a2ef6283024dece7"

PROBE = f'''module tlsprobe

import std.hex
import std.str
import std.x25519
import std.tls_client

const PRIV = "{PRIV}"

fn main() {{
    let a = args()
    if a[0] == "ch" {{
        let priv = hex_decode(PRIV)
        let pub = x25519_base(priv)
        let ch = tls_client_hello(a[1], pub, hex_decode("{RANDOM}"), "")
        print(hex_encode(ch))
    }} else {{
        let lines = str_split(read_text(a[1]), "\\n")
        let priv = hex_decode(str_trim(lines.get(0)))
        let ch = hex_decode(str_trim(lines.get(1)))
        let srv = hex_decode(str_trim(lines.get(2)))
        let r = tls_client_handshake(priv, ch, srv)
        print("ok=" + r.ok.to_str() + " cv=" + r.cv.to_str() +
              " err=" + r.err + " pub=" + hex_encode(r.cert_pub))
    }}
}}
'''


def probe(mode, arg):
    r = subprocess.run([sys.executable, CLI, "run", SRC, "--target", "win", mode, arg],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"探针失败（{mode}）")
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    res = [ln for ln in lines if ln.startswith("ok=")]
    if res:
        return res[-1]
    hexish = [ln for ln in lines if len(ln) > 40 and all(c in "0123456789abcdef" for c in ln)]
    if not hexish:
        raise SystemExit(f"探针没有输出（{mode}）：{r.stdout!r}")
    return hexish[-1]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    host = args[0] if args else "cloudflare.com"

    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    with open(SRC, "w", encoding="utf-8") as f:
        f.write(PROBE)

    ch_hex = probe("ch", host)
    ch = bytes.fromhex(ch_hex)
    if verbose:
        print(f"ClientHello: {len(ch)} 字节")

    try:
        s = socket.create_connection((host, 443), timeout=10)
    except OSError as ex:
        raise SystemExit(f"连接 {host}:443 失败：{ex}")
    s.settimeout(1.0)
    s.sendall(ch)
    buf = b""
    while True:
        try:
            d = s.recv(65536)
        except socket.timeout:
            break
        if not d:
            break
        buf += d
    s.close()
    if verbose:
        print(f"服务器 flight: {len(buf)} 字节，首记录 {buf[:5].hex()}")
    if len(buf) < 5:
        raise SystemExit("服务器没有返回数据")

    with open(IN, "w", encoding="ascii") as f:
        f.write(PRIV + "\n" + ch_hex + "\n" + buf.hex() + "\n")
    out = probe("hs", IN)
    print(f"{host}: {out}")
    return 0 if out.startswith("ok=1") else 1


if __name__ == "__main__":
    sys.exit(main())
