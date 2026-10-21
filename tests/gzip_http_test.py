#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP gzip 端到端验证：连本地 Quelmara 服务，检查协商与解压结果。

前置：先跑 examples/http_gzip.qma（监听 127.0.0.1:18080）。

用法：
    python tests/gzip_http_test.py
"""
import socket
import sys
import zlib

HOST, PORT = "127.0.0.1", 18080


def request(path: str, accept_gzip: bool) -> bytes:
    s = socket.create_connection((HOST, PORT), timeout=5)
    heads = [f"GET {path} HTTP/1.1", f"Host: {HOST}:{PORT}", "Connection: close"]
    if accept_gzip:
        heads.append("Accept-Encoding: gzip")
    raw = ("\r\n".join(heads) + "\r\n\r\n").encode()
    s.sendall(raw)
    out = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        out += chunk
    s.close()
    return out


def split_response(raw: bytes):
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0]
    headers = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        headers[k.strip().lower()] = v.strip()
    return status, headers, body


def main() -> int:
    fails = 0

    # 1) 支持 gzip：应压缩，且解压后是 20 行文本
    raw = request("/", True)
    st, hd, body = split_response(raw)
    if "200" not in st:
        print(f"  [FAIL] /: 状态 {st!r}")
        fails += 1
    elif hd.get("content-encoding") != "gzip":
        print(f"  [FAIL] /: 没有 Content-Encoding: gzip（头 {hd}）")
        fails += 1
    else:
        try:
            plain = zlib.decompress(body, 16 + zlib.MAX_WBITS)
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] /: 解压失败 {e!r}")
            fails += 1
            plain = b""
        if plain:
            ok = plain.count(b"<p>") == 20 and b"quelmara gzip demo" in plain
            print(f"  [{'PASS' if ok else 'FAIL'}] / gzip: {len(body)}B -> {len(plain)}B, 行数={plain.count(b'<p>')}")
            fails += 0 if ok else 1

    # 2) 不支持 gzip：不压缩，body 是原文
    raw = request("/", False)
    st, hd, body = split_response(raw)
    ok = "content-encoding" not in hd and body.count(b"<p>") == 20
    print(f"  [{'PASS' if ok else 'FAIL'}] / 未协商: encoding={hd.get('content-encoding')!r} bytes={len(body)}")
    fails += 0 if ok else 1

    # 3) 小响应：即使支持 gzip 也不压
    raw = request("/small", True)
    st, hd, body = split_response(raw)
    ok = "content-encoding" not in hd and body == b"tiny"
    print(f"  [{'PASS' if ok else 'FAIL'}] /small: encoding={hd.get('content-encoding')!r} body={body!r}")
    fails += 0 if ok else 1

    # 4) 退出
    try:
        request("/quit", False)
    except Exception:  # noqa: BLE001
        pass

    print("-" * 56)
    print(f"FAIL={fails}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
