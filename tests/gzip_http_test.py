#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP gzip 端到端验证（v3.13）：自己编译、起服务、等就绪、跑断言、收尾。

v1.6 起这个文件就存在，但一直是"**手工先起** examples/http_gzip.qma（18080）"
的形态——于是它从来没进过任何自动门禁。v3.11 把 http_router_test.py 接进主回归时
留了这条尾巴（见 07-gaps.md §3），v3.13 收口：改成与 http_router_test.py 同构。

覆盖三件事（都是协商语义，不是压缩算法本身——算法在 gzip_inflate_test.py 里
对拍了 86 项）：
  1. 客户端支持 gzip  -> 响应带 Content-Encoding: gzip，解压后是 20 行正文
  2. 客户端不支持     -> 不压，正文原样
  3. 小响应           -> 即使支持也不压（压缩收益 < 开销）

用法：
    python tests/gzip_http_test.py

退出码：0 = 全过 / 1 = 有断言失败或服务起不来。
端口被占时返回 2，调用方（run_win_tests.py）据此记 SKIP 而不是 FAIL——
"端口被别的进程占了"和"gzip 协商坏了"是两件事，混在一起会训练出
"看到红就重跑"的习惯。
"""
import os
import socket
import subprocess
import sys
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

HOST, PORT = "127.0.0.1", 18080
SRC = os.path.join(ROOT, "examples", "http_gzip.qma")
EXE = os.path.join(ROOT, "build", "win_http_gzip.exe")

CHECKS = 0
FAILS = []


def ok(msg):
    global CHECKS
    CHECKS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    FAILS.append(msg)
    print(f"  [FAIL] {msg}")


def build():
    os.makedirs(os.path.dirname(EXE), exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/stage0/qlm_cli.py"),
                        "build", SRC, "--target", "win", "-o", EXE],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise SystemExit("构建 examples/http_gzip.qma 失败")


def port_free(host, port):
    s = socket.socket()
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def request(path: str, accept_gzip: bool) -> bytes:
    s = socket.create_connection((HOST, PORT), timeout=5)
    try:
        heads = [f"GET {path} HTTP/1.1", f"Host: {HOST}:{PORT}", "Connection: close"]
        if accept_gzip:
            heads.append("Accept-Encoding: gzip")
        s.sendall(("\r\n".join(heads) + "\r\n\r\n").encode())
        out = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
        return out
    finally:
        s.close()


def split_response(raw: bytes):
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0] if lines else ""
    headers = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        headers[k.strip().lower()] = v.strip()
    return status, headers, body


def run_checks() -> int:
    # 1) 支持 gzip：应压缩，且解压后是 20 行文本
    raw = request("/", True)
    st, hd, body = split_response(raw)
    if "200" not in st:
        bad(f"/: 状态 {st!r}")
    elif hd.get("content-encoding") != "gzip":
        bad(f"/: 没有 Content-Encoding: gzip（头 {hd}）")
    else:
        ok("/ 协商 gzip：响应带 Content-Encoding: gzip")
        try:
            plain = zlib.decompress(body, 16 + zlib.MAX_WBITS)
        except Exception as e:  # noqa: BLE001
            bad(f"/: 解压失败 {e!r}")
            plain = b""
        if plain:
            if plain.count(b"<p>") == 20 and b"quelmara gzip demo" in plain:
                ok(f"/ 解压正文正确：{len(body)}B -> {len(plain)}B，20 行")
            else:
                bad(f"/ 解压正文不符：{len(plain)}B，"
                    f"<p> 出现 {plain.count(b'<p>')} 次")

    # 2) 不支持 gzip：不压缩，body 是原文
    raw = request("/", False)
    st, hd, body = split_response(raw)
    if "content-encoding" not in hd and body.count(b"<p>") == 20:
        ok(f"/ 未协商：不压，原文 {len(body)}B / 20 行")
    else:
        bad(f"/ 未协商：encoding={hd.get('content-encoding')!r} bytes={len(body)}")

    # 3) 小响应：即使支持 gzip 也不压
    raw = request("/small", True)
    st, hd, body = split_response(raw)
    if "content-encoding" not in hd and body == b"tiny":
        ok("/small：小响应不压，正文 tiny")
    else:
        bad(f"/small: encoding={hd.get('content-encoding')!r} body={body!r}")

    return 0 if not FAILS else 1


def main() -> int:
    if not port_free(HOST, PORT):
        print(f"  端口 {PORT} 已被占用，跳过（环境问题，不是回归）")
        return 2
    build()
    proc = subprocess.Popen([EXE], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        ready = False
        for _ in range(60):
            try:
                socket.create_connection((HOST, PORT), timeout=1).close()
                ready = True
                break
            except OSError:
                time.sleep(0.1)
        if not ready:
            bad("服务端口未就绪（6 s 内没起来）")
            return 1
        ok(f"服务就绪（{PORT}）")
        run_checks()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if FAILS:
        print(f"\ngzip_http FAIL（{len(FAILS)} 项）")
        for f in FAILS:
            print("  -", f)
        return 1
    print(f"\ngzip_http ok（{CHECKS} 项断言）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
