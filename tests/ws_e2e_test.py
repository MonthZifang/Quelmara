#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WebSocket 端到端（v3.27）：真的握手、真的收发帧。

## 为什么需要它

v3.26 把 `std/ws` 从"连解析都过不去"修到"能编译、能 import"，
但**从来没验证过它真的能跑**。WebSocket 最容易错的地方全在线上：

* 握手摘要算法（SHA-1 + base64，RFC 6455 给了标准样例）；
* 帧头长度编码（7 位 / 7+16 / 7+64 三档）；
* **客户端必须掩码**（RFC 要求，服务端必须解掩码）；
* 分片与控制帧（ping/pong/close）。

这些没有一条能靠"编译通过"发现。

## 判据

起一个真实的 `ws_serve`，用 Python 客户端（手写帧，不用第三方库）：

  [1] 握手 101 + `Sec-WebSocket-Accept` 与 RFC 6455 标准样例一致
  [2] 文本帧往返（echo）
  [3] 长文本帧（> 125 字节，走 16 位长度档）
  [4] 二进制帧往返
  [5] 掩码解对了（客户端发的帧带掩码，服务端 echo 回来必须是明文）

跑法：python tests/ws_e2e_test.py
"""
import base64
import hashlib
import os
import socket
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm_pe  # noqa: E402

# 端口从 demo 源码里读（`ws_serve(8092, ...)`），别硬编码 ——
# demo 改端口时这里会自动跟上，不会变成"服务起了但连不上"的假失败。
def _port_of(src_path):
    import re
    with open(src_path, encoding="utf-8") as f:
        m = re.search(r"ws_serve\(\s*(\d+)", f.read())
    return int(m.group(1)) if m else 8092


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
PASS = FAIL = 0
PORT = 8092  # main() 里按 demo 源码覆盖


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def build_and_start(src, exe_name):
    out = os.path.join(ROOT, "build", exe_name)
    blob, _cfg = qlm_pe.transpile_win(src)
    qlm_pe.write_exe(out, blob)
    proc = subprocess.Popen([out], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    # 等端口就绪（最多 5 s）
    for _ in range(100):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=0.2)
            s.close()
            return proc
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise RuntimeError("服务没有在 5 s 内起来")


def read_until(sock, marker=b"\r\n\r\n", limit=65536):
    buf = b""
    while marker not in buf and len(buf) < limit:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf


def handshake(sock):
    """发标准握手请求，返回 (状态行, 头部字典)。"""
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\n"
           f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    sock.sendall(req.encode())
    raw = read_until(sock)
    head, _, rest = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0]
    hdrs = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            hdrs[k.strip().lower()] = v.strip()
    return status, hdrs, rest, key


def make_frame(opcode, payload, mask=True):
    """按 RFC 6455 组一帧（客户端发必须掩码）。"""
    n = len(payload)
    hdr = bytes([0x80 | opcode])
    if n < 126:
        hdr += bytes([(0x80 if mask else 0) | n])
    elif n < 65536:
        hdr += bytes([(0x80 if mask else 0) | 126]) + struct.pack(">H", n)
    else:
        hdr += bytes([(0x80 if mask else 0) | 127]) + struct.pack(">Q", n)
    if not mask:
        return hdr + payload
    key = os.urandom(4)
    masked = bytes(payload[i] ^ key[i % 4] for i in range(n))
    return hdr + key + masked


def recv_frame(sock, timeout=5.0):
    """读一帧，返回 (opcode, payload)。服务端发的不掩码。"""
    sock.settimeout(timeout)

    def rd(n):
        buf = b""
        while len(buf) < n:
            c = sock.recv(n - len(buf))
            if not c:
                raise ConnectionError("连接关闭")
            buf += c
        return buf

    b0, b1 = rd(2)
    opcode = b0 & 0x0F
    masked = b1 & 0x80
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack(">H", rd(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", rd(8))[0]
    key = rd(4) if masked else b""
    payload = rd(n) if n else b""
    if masked:
        payload = bytes(payload[i] ^ key[i % 4] for i in range(n))
    return opcode, payload


def main():
    global PORT
    src = os.path.join(ROOT, "examples", "ws_demo.qma")
    if not os.path.isfile(src):
        print("SKIP：examples/ws_demo.qma 不存在")
        return 0
    PORT = _port_of(src)

    print("== WebSocket 端到端 ==")
    proc = build_and_start(src, "ws_e2e.exe")
    try:
        # ---- [1] 握手 ----
        sock = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        status, hdrs, rest, key = handshake(sock)
        ok("握手返回 101") if "101" in status else bad(f"握手状态行：{status}")

        expect = base64.b64encode(
            hashlib.sha1((key + GUID).encode()).digest()).decode()
        got = hdrs.get("sec-websocket-accept", "")
        ok("Sec-WebSocket-Accept 正确（SHA-1+base64）") if got == expect \
            else bad(f"accept 不符：got={got!r} want={expect!r}")

        # on_open 会主动推一条 "hello from quelmara"
        try:
            op, payload = recv_frame(sock)
            if op == 0x1:
                ok(f"on_open 主动推送：{payload.decode('utf-8', 'replace')!r}")
            else:
                bad(f"on_open 推送的 opcode 不是文本：{op}")
        except Exception as e:  # noqa: BLE001
            bad(f"收 on_open 推送失败：{e}")

        # ---- [2] 文本帧往返 ----
        sock.sendall(make_frame(0x1, b"ping-quelmara"))
        op, payload = recv_frame(sock)
        if op == 0x1 and payload == b"ping-quelmara":
            ok("文本帧 echo 正确（掩码已解开）")
        else:
            bad(f"文本 echo：op={op} payload={payload!r}")

        # ---- [3] 长文本（走 16 位长度档） ----
        long_msg = ("Q" * 300).encode()
        sock.sendall(make_frame(0x1, long_msg))
        op, payload = recv_frame(sock)
        if op == 0x1 and payload == long_msg:
            ok(f"长文本帧（{len(long_msg)} B）echo 正确")
        else:
            bad(f"长文本 echo：op={op} len={len(payload)}")

        # ---- [4] 二进制帧 ----
        blob = bytes(range(256))
        sock.sendall(make_frame(0x2, blob))
        op, payload = recv_frame(sock)
        if op == 0x2 and payload == blob:
            ok("二进制帧 echo 正确（256 B 全字节）")
        else:
            bad(f"二进制 echo：op={op} len={len(payload)}")

        # ---- [5] 掩码真的被解了 ----
        # 发同一内容两次，掩码 key 不同；echo 必须都是明文
        for i in range(2):
            msg = f"mask-check-{i}".encode()
            sock.sendall(make_frame(0x1, msg))
            op, payload = recv_frame(sock)
            if payload != msg:
                bad(f"第 {i+1} 次掩码解密错误：{payload!r}")
                break
        else:
            ok("两次不同掩码 key 都能正确解出明文")

        sock.close()
    finally:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass

    print(f"\nWS_E2E: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
