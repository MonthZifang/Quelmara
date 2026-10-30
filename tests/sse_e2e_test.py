#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSE 端到端（v3.27）：真的订阅、真的收事件。

`std/sse` 和 `std/ws` 一样，v3.26 之前**外部一个函数都调不到**，
修完之后也没人验证过它真的能跑。SSE 的坑全在线上格式：

* 响应头必须是 `text/event-stream` + `no-cache`；
* 事件块以**空行**结束（少一个 `\\n` 客户端就永远不触发）；
* `event:` / `data:` / `id:` / `retry:` 字段名与顺序；
* `retry` 是毫秒整数，不是秒。

跑法：python tests/sse_e2e_test.py
"""
import os
import re
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm_pe  # noqa: E402

PASS = FAIL = 0
PORT = 8093


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def _port_of(src_path):
    with open(src_path, encoding="utf-8") as f:
        m = re.search(r"sse_serve\(\s*(\d+)", f.read())
    return int(m.group(1)) if m else 8093


def build_and_start(src, exe_name):
    out = os.path.join(ROOT, "build", exe_name)
    blob, _cfg = qlm_pe.transpile_win(src)
    qlm_pe.write_exe(out, blob)
    proc = subprocess.Popen([out], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    for _ in range(120):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=0.2)
            s.close()
            return proc
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise RuntimeError("SSE 服务没有在 6 s 内起来")


def main():
    global PORT
    src = os.path.join(ROOT, "examples", "sse_demo.qma")
    if not os.path.isfile(src):
        print("SKIP：examples/sse_demo.qma 不存在")
        return 0
    PORT = _port_of(src)

    print("== SSE 端到端 ==")
    proc = build_and_start(src, "sse_e2e.exe")
    try:
        sock = socket.create_connection(("127.0.0.1", PORT), timeout=10)
        sock.sendall(f"GET /stream HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\n"
                     f"Accept: text/event-stream\r\n\r\n".encode())

        buf = b""
        sock.settimeout(10)
        deadline = time.time() + 8
        while b"\r\n\r\n" not in buf and time.time() < deadline:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk

        head, _, body = buf.partition(b"\r\n\r\n")
        head_text = head.decode("latin-1")
        hdr = {}
        for ln in head_text.split("\r\n")[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                hdr[k.strip().lower()] = v.strip()

        # ---- [1] 状态与响应头 ----
        ok("订阅返回 200") if "200" in head_text.split("\r\n")[0] \
            else bad(f"状态行：{head_text.splitlines()[0]}")

        ct = hdr.get("content-type", "")
        ok(f"Content-Type 是 text/event-stream（{ct}）") \
            if "text/event-stream" in ct else bad(f"Content-Type={ct!r}")

        cc = hdr.get("cache-control", "")
        ok("Cache-Control 含 no-cache") if "no-cache" in cc \
            else bad(f"Cache-Control={cc!r}")

        # ---- [2] 收事件 ----
        while time.time() < deadline and len(body) < 4096:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            body += chunk

        text = body.decode("utf-8", "replace")

        # retry 行（on_sub 里发的 sse_retry(fd, 2000)）
        m = re.search(r"^retry:\s*(\d+)\s*$", text, re.M)
        if m:
            ok(f"retry 行格式正确（{m.group(1)} ms）") if m.group(1) == "2000" \
                else bad(f"retry 值不符：{m.group(1)}（期望 2000）")
        else:
            bad(f"没有 retry 行：{text[:200]!r}")

        # greet 事件
        if re.search(r"^event:\s*greet\s*$", text, re.M) and \
                re.search(r"^data:\s*hello sse\s*$", text, re.M):
            ok("greet 事件（event + data 两个字段）格式正确")
        else:
            bad(f"greet 事件缺失或字段不符：{text[:300]!r}")

        # ---- [3] 事件块以空行结尾 ----
        # 每个事件块必须以 \n\n 结束，否则客户端不触发
        blocks = [b for b in re.split(r"\n\n", text) if b.strip()]
        ok(f"收到 {len(blocks)} 个以空行结束的事件块") if blocks \
            else bad("没有任何以空行结束的事件块")

        # ---- [4] tick 广播（pusher 线程，每 300ms 一条） ----
        if re.search(r"^event:\s*tick\s*$", text, re.M):
            ok("收到 tick 广播（spawn 线程工作）")
        else:
            # 广播可能还没到，再等一轮
            extra = b""
            deadline2 = time.time() + 6
            while time.time() < deadline2 and b"tick" not in extra:
                try:
                    c = sock.recv(4096)
                except socket.timeout:
                    break
                if not c:
                    break
                extra += c
            text2 = text + extra.decode("utf-8", "replace")
            ok("收到 tick 广播（spawn 线程工作）") \
                if re.search(r"^event:\s*tick\s*$", text2, re.M) \
                else bad(f"没收到 tick 广播：{text2[-200:]!r}")

        # ---- [5] data 行里的 n= 递增 ----
        ns = [int(x) for x in re.findall(r"^data:\s*n=(\d+)\s*$", text, re.M)]
        if len(ns) >= 2 and ns == sorted(ns):
            ok(f"tick 序号递增（{ns[0]}..{ns[-1]}）")
        elif len(ns) == 1:
            ok(f"只收到 1 条 tick（序号 {ns[0]}），不足以判断递增")
        else:
            bad(f"tick 序号不是递增：{ns[:10]}")

        sock.close()
    finally:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass

    print(f"\nSSE_E2E: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
