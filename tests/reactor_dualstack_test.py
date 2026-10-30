#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 reactor 双栈（v3.21）：同一端口同时接受 IPv4 与 IPv6 连接。

前置：需要 examples/http_router.qma 已编译（脚本自己编）。
判据：
  [1] IPv4 127.0.0.1 能连（双栈不破坏 v4）
  [2] IPv6 ::1 能连（这是本版新增的能力）
  [3] 两条连接拿到同一个路由结果

用法：python tests/reactor_dualstack_test.py
退出码：0 = 全过 / 1 = 失败 / 2 = 端口被占（SKIP）
"""
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8092
SRC = os.path.join(ROOT, "examples", "http_router.qma")
EXE = os.path.join(ROOT, "build", "win_http_router_ds.exe")

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
        raise SystemExit("构建 examples/http_router.qma 失败")


def port_free(host, port, family=socket.AF_INET):
    s = socket.socket(family, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def request(host, family):
    """向 (host, PORT) 发一个最小 HTTP GET，返回状态行。"""
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect((host, PORT))
        req = f"GET / HTTP/1.1\r\nHost: {host}:{PORT}\r\nConnection: close\r\n\r\n"
        s.sendall(req.encode())
        out = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
        return out.split(b"\r\n", 1)[0].decode("latin-1")
    finally:
        s.close()


def main():
    if not port_free("0.0.0.0", PORT):
        print(f"  端口 {PORT} 已被占用，跳过")
        return 2
    build()
    proc = subprocess.Popen([EXE, "--quiet"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        ready = False
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
                ready = True
                break
            except OSError:
                time.sleep(0.1)
        if not ready:
            bad("服务端口未就绪（6 s 内没起来）")
            return 1
        ok(f"服务就绪（{PORT}）")

        # [1] IPv4
        try:
            st4 = request("127.0.0.1", socket.AF_INET)
            if "200" in st4:
                ok(f"IPv4 127.0.0.1 -> {st4}")
            else:
                bad(f"IPv4 状态异常：{st4!r}")
        except OSError as e:
            bad(f"IPv4 连接失败：{e}")

        # [2] IPv6（本版新增）
        has_v6 = socket.has_ipv6
        if not has_v6:
            print("  [SKIP] 本机 Python 无 IPv6 支持")
        else:
            try:
                st6 = request("::1", socket.AF_INET6)
                if "200" in st6:
                    ok(f"IPv6 ::1 -> {st6}")
                else:
                    bad(f"IPv6 状态异常：{st6!r}")
            except OSError as e:
                bad(f"IPv6 连接失败：{e}（双栈没生效？）")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if FAILS:
        print(f"\nreactor_dualstack FAIL（{len(FAILS)} 项）")
        for f in FAILS:
            print("  -", f)
        return 1
    print(f"\nreactor_dualstack ok（{CHECKS} 项断言）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
