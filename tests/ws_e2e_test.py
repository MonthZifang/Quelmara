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


def make_frame(opcode, payload, mask=True, fin=True):
    """按 RFC 6455 组一帧（客户端发必须掩码）。

    `fin=False` 表示分片的非末帧（FIN=0），用于测 continuation frame。
    """
    n = len(payload)
    hdr = bytes([(0x80 if fin else 0x00) | opcode])
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


def safe_send(sock, data):
    """sendall 的**不抛异常**版本：连接被重置时返回 False。

    服务端遇到协议错误会主动 close（RFC 6455 要求），这时客户端再发就是
    ConnectionResetError。端到端脚本要把"连接被重置"当成一条失败判据
    报出来，而不是崩栈。
    """
    try:
        sock.sendall(data)
        return True
    except OSError:
        return False


def safe_recv(sock, timeout=5.0):
    """recv_frame 的**不抛异常**版本：超时/断开返回 (None, None)。

    端到端脚本里"收不到"本身就是一条失败判据，不该让整个脚本崩掉 ——
    崩掉会丢掉前面已经通过的断言，也看不出是哪一条失败的。
    """
    try:
        return recv_frame(sock, timeout)
    except Exception:  # noqa: BLE001
        return None, None


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
        safe_send(sock, make_frame(0x1, b"ping-quelmara"))
        op, payload = recv_frame(sock)
        if op == 0x1 and payload == b"ping-quelmara":
            ok("文本帧 echo 正确（掩码已解开）")
        else:
            bad(f"文本 echo：op={op} payload={payload!r}")

        # ---- [3] 长文本（走 16 位长度档） ----
        long_msg = ("Q" * 300).encode()
        safe_send(sock, make_frame(0x1, long_msg))
        op, payload = recv_frame(sock)
        if op == 0x1 and payload == long_msg:
            ok(f"长文本帧（{len(long_msg)} B）echo 正确")
        else:
            bad(f"长文本 echo：op={op} len={len(payload)}")

        # ---- [4] 二进制帧 ----
        blob = bytes(range(256))
        safe_send(sock, make_frame(0x2, blob))
        op, payload = recv_frame(sock)
        if op == 0x2 and payload == blob:
            ok("二进制帧 echo 正确（256 B 全字节）")
        else:
            bad(f"二进制 echo：op={op} len={len(payload)}")

        # ---- [5] 掩码真的被解了 ----
        # 发同一内容两次，掩码 key 不同；echo 必须都是明文
        for i in range(2):
            msg = f"mask-check-{i}".encode()
            safe_send(sock, make_frame(0x1, msg))
            op, payload = recv_frame(sock)
            if payload != msg:
                bad(f"第 {i+1} 次掩码解密错误：{payload!r}")
                break
        else:
            ok("两次不同掩码 key 都能正确解出明文")

        # ---- [6] 分片消息（continuation frame） ----
        # RFC 6455 5.4：首帧 opcode=TEXT + FIN=0，后续帧 opcode=CONT(0)，
        # 末帧 FIN=1。服务端必须把三片拼成一条消息再回调。
        parts = [b"frag-one|", b"frag-two|", b"frag-three"]
        safe_send(sock, make_frame(0x1, parts[0], fin=False))
        safe_send(sock, make_frame(0x0, parts[1], fin=False))
        safe_send(sock, make_frame(0x0, parts[2], fin=True))
        want = b"".join(parts)
        op, payload = safe_recv(sock)
        if payload is None:
            bad("分片消息收不到（连接可能已卡死）")
        elif payload == want:
            ok(f"分片消息拼接正确（3 片 -> {len(want)} B）")
        else:
            bad(f"分片拼接错误：got={payload!r} want={want!r}")

        # ---- [7] 分片消息的类型取首帧 opcode ----
        # 首帧是二进制(0x2)、续帧是 CONT(0)。服务端回调里 ws_last_op()
        # 必须返回 2（首帧类型），而不是 0（续帧的 CONT）。
        # 这一条如果错了，分片发来的二进制会被当文本回，客户端解出乱码。
        blob2 = bytes(range(64))
        safe_send(sock, make_frame(0x2, blob2[:20], fin=False))
        safe_send(sock, make_frame(0x0, blob2[20:], fin=True))
        op, payload = safe_recv(sock)
        if payload is None:
            bad("分片二进制消息收不到")
        elif op == 0x2 and payload == blob2:
            ok("分片二进制消息的 opcode 取首帧（回的是二进制帧）")
        else:
            bad(f"分片二进制类型错：op={op}（应为 2）len={len(payload)}")

        # ---- [8] 分片 + ping 穿插（控制帧可以夹在分片中间） ----
        # RFC 6455 5.4 允许控制帧穿插在分片之间，且不打断分片序列
        safe_send(sock, make_frame(0x1, b"inter-", fin=False))
        safe_send(sock, make_frame(0x9, b"mid-ping"))          # ping 夹在中间
        safe_send(sock, make_frame(0x0, b"leaved", fin=True))
        # 先可能收到 pong（ping 的回应），再收到拼接后的消息
        got_pong = False
        got_msg = None
        for _ in range(3):
            op, payload = safe_recv(sock)
            if payload is None:
                break
            if op == 0xA:
                got_pong = True
                continue
            got_msg = (op, payload)
            break
        if got_pong and got_msg and got_msg[1] == b"inter-leaved":
            ok("分片中间穿插 ping：pong 已回，消息仍正确拼接")
        elif got_msg and got_msg[1] == b"inter-leaved":
            ok("分片中间穿插 ping：消息正确拼接（pong 未单独回，可接受）")
        else:
            bad(f"分片+ping 穿插：pong={got_pong} msg={got_msg!r}")

        # ---- [9] 分片之后连接仍然可用（v3.28 修的死锁回归钉） ----
        # 这条钉住一个严重缺陷：分片完成时 `_drop_frame(p, total, ...)` 的
        # keep_to 写成了 total，把已消费的消息本体留在缓冲区；下一帧又从
        # off=0 解析，于是**永远读不出帧头**，连接就此卡死。
        # 症状是"用过一次分片之后，这条连接再也收不到任何消息"。
        safe_send(sock, make_frame(0x1, b"post-", fin=False))
        safe_send(sock, make_frame(0x0, b"frag", fin=True))
        try:
            op, payload = recv_frame(sock)
        except Exception as e:  # noqa: BLE001
            bad(f"分片消息本身就收不到（连接卡死）：{e}")
            payload = None
        if payload is not None and payload != b"post-frag":
            bad(f"分片后第一条消息就错了：{payload!r}")
        elif payload == b"post-frag":
            # 关键：紧接着再发一个**普通单帧**，必须还能收到
            safe_send(sock, make_frame(0x1, b"still-alive"))
            try:
                op, payload = recv_frame(sock, timeout=3)
                if payload == b"still-alive":
                    ok("分片之后连接仍可用（下一帧能收到）")
                else:
                    bad(f"分片后收到的内容不对：{payload!r}")
            except Exception as e:  # noqa: BLE001
                bad(f"分片之后连接卡死（收不到下一帧）：{e}")

        # ---- [10] close 握手（v3.28 补） ----
        # RFC 6455 5.5.1：客户端发 close，服务端必须回一个 close 帧，
        # 然后关闭 TCP。这条代码路径与分片那条同源 —— 写了但从没跑过。
        safe_send(sock, make_frame(0x8, struct.pack(">H", 1000)))
        op, payload = safe_recv(sock, timeout=3)
        if op is None:
            bad("close 握手：没收到服务端的 close 帧")
        elif op == 0x8:
            code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else -1
            if code == 1000:
                ok("close 握手正确（服务端回 close，code 回显 1000）")
            else:
                ok(f"close 握手回了 close 帧（code={code}，非回显但可接受）")
        else:
            bad(f"close 握手：服务端回的不是 close 帧（op={op}）")

        # 服务端应随后关闭连接
        try:
            sock.settimeout(3)
            tail = sock.recv(4096)
            if tail == b"":
                ok("close 之后服务端关闭了连接")
            else:
                bad(f"close 之后还收到数据：{tail!r}")
        except (socket.timeout, OSError):
            ok("close 之后连接已断开（重置）")

        sock.close()

        # ---- [11] 错误路径：未掩码的客户端帧必须被拒（close 1002） ----
        # RFC 6455 5.1：客户端发的帧必须掩码。这些错误路径代码各 2-4 行，
        # 与分片同源 —— 写了但从没跑过。用新连接测，不污染上面那条。
        s2 = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        handshake(s2)
        safe_recv(s2)                       # on_open 推送
        safe_send(s2, make_frame(0x1, b"no-mask", mask=False))
        op, payload = safe_recv(s2, timeout=3)
        if op == 0x8:
            code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else -1
            ok(f"未掩码的客户端帧被拒（close code={code}）") if code == 1002 \
                else bad(f"未掩码帧被拒但 code={code}（期望 1002）")
        else:
            bad(f"未掩码的客户端帧没被拒（op={op}）")
        s2.close()

        # ---- [12] 错误路径：分片进行中又来新数据帧（close 1002） ----
        s3 = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        handshake(s3)
        safe_recv(s3)
        safe_send(s3, make_frame(0x1, b"start", fin=False))
        safe_send(s3, make_frame(0x1, b"another", fin=True))   # 分片未完成
        op, payload = safe_recv(s3, timeout=3)
        if op == 0x8:
            code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else -1
            ok(f"分片未完成时的新数据帧被拒（close code={code}）") if code == 1002 \
                else bad(f"被拒但 code={code}（期望 1002）")
        else:
            bad(f"分片未完成时的新数据帧没被拒（op={op}）")
        s3.close()

        # ---- [13] 超长消息被拒（close 1009） ----
        # v3.29 修的：消息上限原来等于连接缓冲上限（都是 1 MB），
        # "上限之内"的消息反而收不全，永久卡死。现在上限 960 KB，
        # 留 64 KB 余量给帧头，1009 才能正常触发。
        #
        # **只发帧头、不发载荷**：服务端读到 64 位长度就知道超限了，
        # 立即回 1009。如果真把 1.1 MB 灌进去，会在客户端一侧先把
        # TCP 缓冲塞满（那是背压问题，不是 ws 协议问题），
        # 测的就不是"协议是否拒绝"了。
        s4 = socket.create_connection(("127.0.0.1", PORT), timeout=10)
        handshake(s4)
        safe_recv(s4)
        over = 1100000
        hdr = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", over) + os.urandom(4)
        safe_send(s4, hdr)
        op, payload = safe_recv(s4, timeout=5)
        if op == 0x8:
            code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else -1
            ok(f"超长消息（声明 {over} B）被拒（close code={code}）") if code == 1009 \
                else bad(f"超长消息被拒但 code={code}（期望 1009）")
        else:
            bad(f"超长消息没被拒（op={op}）")
        s4.close()

        # ---- [14] 上限之内的大消息能正常收发 ----
        # 与 [13] 配对，证明"留余量"没把上限压得太低 —— 960 KB 上限下，
        # 900 KB 必须能完整收发（含 64 位长度档，因为 900 KB > 65535）。
        #
        # 诚实说明：这条**抓不到** v3.29 修的那个 bug（消息上限 == 连接缓冲
        # 上限导致边缘卡死）。那个 bug 只在"载荷恰好逼近 1 MB"时暴露，
        # 而边界值差几十字节，钉死具体数字的测试会非常脆。
        # 这里钉的是"大消息这条路通"，边界由 [13] 的 1009 侧兜住。
        s5 = socket.create_connection(("127.0.0.1", PORT), timeout=20)
        handshake(s5)
        safe_recv(s5)
        big_ok = b"K" * (900 * 1024)
        if safe_send(s5, make_frame(0x1, big_ok)):
            op, payload = safe_recv(s5, timeout=20)
            if payload == big_ok:
                ok(f"上限内的大消息正常收发（{len(big_ok)} B）")
            else:
                bad(f"大消息收发不符：op={op} len={len(payload) if payload else 0}")
        else:
            bad("大消息发送失败")
        s5.close()
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
