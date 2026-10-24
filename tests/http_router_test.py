#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""std/http 路由表 + 中间件的端到端回归（v2.04）。

跑法：
    python tests/http_router_test.py            # 回归（约 2 s）
    python tests/http_router_test.py --bench    # 追加吞吐测量（keep-alive，4 线程）

做法：编译并启动 examples/http_router.qma（监听 127.0.0.1:8092），本进程用
socket 发真实 HTTP 请求，逐条断言状态行 / 头 / 体。覆盖：

  R1 路由命中：字面段、`:id` 参数、两段参数、尾部 `*` 通配
  R2 归一化：query 串不影响匹配（且能被 http_query 取到）、尾斜杠等价
  R3 404 / 405：未注册路径、路径命中但方法不符
  R4 中间件：`/admin` 前缀无令牌 -> 401（链在 handler 之前终止）；
              带令牌 -> 200；非 /admin 路径不受影响
  R5 请求体：POST + Content-Length，handler 读得到长度
  R6 gzip 协商：Accept-Encoding: gzip 时压、解压后与原体逐字节相同
  R7 keep-alive：同一连接连续两个请求都有响应
  R8 流水线：一次 send 两个请求，两个响应都回来
"""
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST, PORT = "127.0.0.1", 8092
SRC = os.path.join(ROOT, "examples", "http_router.qma")
EXE = os.path.join(ROOT, "build", "win_http_router.exe")

fails = []


def ok(msg):
    print(f"  [OK] {msg}")


def bad(msg):
    print(f"  [FAIL] {msg}")
    fails.append(msg)


def build():
    os.makedirs(os.path.dirname(EXE), exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/stage0/qlm_cli.py"),
                        "build", SRC, "--target", "win", "-o", EXE],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise SystemExit("构建 examples/http_router.qma 失败")


def connect(timeout=5):
    s = socket.create_connection((HOST, PORT), timeout=timeout)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


def read_response(sock, buf=b""):
    """读一个完整响应（按 Content-Length），返回 (status, headers, body, 剩余字节)。"""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            raise EOFError("连接在响应头之前关闭")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0]
    headers = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        headers[k.strip().lower()] = v.strip()
    need = int(headers.get("content-length", "0"))
    while len(rest) < need:
        chunk = sock.recv(65536)
        if not chunk:
            raise EOFError("连接在响应体中途关闭")
        rest += chunk
    return status, headers, rest[:need], rest[need:]


def request(path, method="GET", headers=None, body=b"", keep=False):
    s = connect()
    try:
        hdrs = [f"{method} {path} HTTP/1.1", f"Host: {HOST}:{PORT}"]
        hdrs += headers or []
        if body:
            hdrs.append(f"Content-Length: {len(body)}")
        if not keep:
            hdrs.append("Connection: close")
        s.sendall(("\r\n".join(hdrs) + "\r\n\r\n").encode() + body)
        return read_response(s)
    finally:
        s.close()


def expect(name, path, status_code, *, method="GET", headers=None, body=b"",
           contains=None, equals=None):
    try:
        st, hd, bd, _ = request(path, method, headers, body)
    except Exception as e:  # noqa: BLE001
        bad(f"{name}: 请求异常 {type(e).__name__}: {e}")
        return
    if f" {status_code} " not in st:
        bad(f"{name}: 期望 {status_code}，实际 {st!r} 体={bd[:80]!r}")
        return
    if equals is not None and bd != equals:
        bad(f"{name}: 体不符 {bd!r} != {equals!r}")
        return
    if contains is not None and contains not in bd:
        bad(f"{name}: 体里没有 {contains!r}（{bd[:120]!r}）")
        return
    ok(f"{name}: {status_code} {bd[:70]!r}")


def main() -> int:
    build()
    # --quiet：关掉访问日志中间件的 print（一次控制台 WriteFile 几十微秒，
    # 会盖住 HTTP 栈本身的成本；中间件本身照常执行）
    proc = subprocess.Popen([EXE, "--quiet"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        ready = False
        for _ in range(60):
            try:
                connect(timeout=1).close()
                ready = True
                break
            except OSError:
                time.sleep(0.1)
        if not ready:
            print("  [FAIL] 服务端口未就绪")
            return 1
        ok("服务就绪（8092）")

        print("== R1 路由命中 ==")
        expect("字面段 /", "/", 200, contains=b"Quelmara router")
        expect(":id 参数", "/users/42", 200, equals=b'{"id":"42","q":""}')
        expect("两段参数", "/users/42/posts/7", 200,
               equals=b'{"user":"42","post":"7"}')
        expect("尾部 * 通配", "/files/a/b.txt", 200, equals=b"/files/a/b.txt")

        print("== R2 归一化 ==")
        expect("query 不参与匹配", "/users/42?x=1&y=2", 200,
               equals=b'{"id":"42","q":"x=1&y=2"}')
        expect("尾斜杠等价", "/users/42/", 200, equals=b'{"id":"42","q":""}')
        expect("通配 + query", "/files/x?k=v", 200, equals=b"/files/x?k=v")

        print("== R3 404 / 405 ==")
        expect("未注册路径 -> 404", "/nope", 404, contains=b"not found")
        expect("方法不符 -> 405", "/users/42", 405, method="DELETE",
               contains=b"method not allowed")
        expect("通配路径方法不符 -> 405", "/files/a", 405, method="POST")

        print("== R4 中间件（/admin 鉴权） ==")
        expect("无令牌 -> 401", "/admin/stats", 401,
               equals=b'{"error":"unauthorized"}')
        expect("错误令牌 -> 401", "/admin/stats", 401,
               headers=["Authorization: Bearer nope"])
        expect("正确令牌 -> 200", "/admin/stats", 200,
               headers=["Authorization: Bearer s3cret"], contains=b'"accepted"')
        expect("非 /admin 路径不受影响", "/users/1", 200,
               equals=b'{"id":"1","q":""}')

        print("== R5 请求体 ==")
        expect("POST + 体长度", "/users", 201, method="POST", body=b"hello",
               equals=b'{"created":true,"len":5}')

        print("== R6 gzip 协商 ==")
        st, hd, gz, _ = request("/big", headers=["Accept-Encoding: gzip"])
        st2, hd2, plain, _ = request("/big")
        if " 200 " not in st or " 200 " not in st2:
            bad(f"gzip: 状态 {st!r} / {st2!r}")
        elif hd.get("content-encoding") != "gzip":
            bad(f"gzip: 没压缩（头 {hd}）")
        elif hd2.get("content-encoding") is not None:
            bad(f"gzip: 未声明 Accept-Encoding 却被压缩（{hd2}）")
        else:
            try:
                un = zlib.decompress(gz, 16 + zlib.MAX_WBITS)
            except Exception as e:  # noqa: BLE001
                un = b""
                bad(f"gzip: 解压失败 {e}")
            if un == plain and len(plain) > 256:
                ok(f"gzip: {len(plain)} B -> {len(gz)} B，解压逐字节相同")
            elif un != plain:
                bad(f"gzip: 解压结果与明文不同（{len(un)} vs {len(plain)}）")

        print("== R7 keep-alive ==")
        s = connect()
        try:
            s.sendall(b"GET /users/1 HTTP/1.1\r\nHost: x\r\n\r\n")
            st1, _, b1, rest = read_response(s)
            s.sendall(b"GET /users/2 HTTP/1.1\r\nHost: x\r\n\r\n")
            st2b, _, b2, _ = read_response(s, rest)
            if " 200 " in st1 and " 200 " in st2b and b1 == b'{"id":"1","q":""}' \
                    and b2 == b'{"id":"2","q":""}':
                ok("keep-alive: 同一连接两次请求都对")
            else:
                bad(f"keep-alive: {st1!r}/{st2b!r} {b1!r} {b2!r}")
        finally:
            s.close()

        print("== R8 流水线 ==")
        s = connect()
        try:
            s.sendall(b"GET /users/7 HTTP/1.1\r\nHost: x\r\n\r\n"
                      b"GET /files/p/q HTTP/1.1\r\nHost: x\r\n\r\n")
            st1, _, b1, rest = read_response(s)
            st2b, _, b2, _ = read_response(s, rest)
            if b1 == b'{"id":"7","q":""}' and b2 == b"/files/p/q":
                ok("流水线: 一次 send 两个请求，两个响应都对")
            else:
                bad(f"流水线: {b1!r} / {b2!r}")
        finally:
            s.close()

        if "--bench" in sys.argv:
            bench()

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    total = 20
    if fails:
        print(f"\nhttp_router FAIL（{len(fails)} 项）")
        for f in fails:
            print("  -", f)
        return 1
    print(f"\nhttp_router ok（{total} 项断言）")
    return 0


def server_stats():
    """读 /admin/stats：返回 (reqs, cpu_ns)。cpu_ns 是服务进程 CPU 时间。"""
    import json
    _, _, bd, _ = request("/admin/stats",
                          headers=["Authorization: Bearer s3cret"])
    d = json.loads(bd)
    return d["reqs"], d["cpu_ns"]


def bench():
    """吞吐 + **服务端每请求 CPU**。

    客户端是 4 个 Python 线程（GIL + syscall 很贵），所以 req/s 反映的是
    「客户端能推多快」；服务端真实成本看 cpu_ns 差值 ÷ 请求数——它不受客户端
    快慢影响，是本机测 HTTP 派发开销最干净的口径。
    """
    print("== B 吞吐（keep-alive，4 连接） ==")
    per, rounds = 1000, 4
    request("/users/42")                       # 预热
    r0, c0 = server_stats()
    errors = []

    def worker():
        try:
            s = connect(timeout=30)
            for _ in range(per):
                s.sendall(b"GET /users/42 HTTP/1.1\r\nHost: x\r\n\r\n")
                st, _, bd, _ = read_response(s)
                if " 200 " not in st or bd != b'{"id":"42","q":""}':
                    errors.append(st)
                    break
            s.close()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")

    t0 = time.perf_counter()
    ths = [threading.Thread(target=worker) for _ in range(rounds)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    dt = time.perf_counter() - t0
    r1, c1 = server_stats()
    if errors:
        bad(f"吞吐：出现 {len(errors)} 个错误（{errors[:2]}）")
        return
    n = per * rounds
    dn, dc = r1 - r0, c1 - c0
    print(f"  {n} 请求 / {dt*1000:.0f} ms = {n/dt:,.0f} req/s"
          f"（客户端口径，{dt/n*1e6:.1f} µs/往返）")
    if dn > 0:
        print(f"  服务端 CPU：{dc/1e6:.0f} ms / {dn} 请求 = {dc/dn/1000:.2f} µs/请求"
              f"（{dn} 条含 2 次 stats 调用）")
        ok(f"服务端每请求 CPU = {dc/dn/1000:.2f} µs")


if __name__ == "__main__":
    sys.exit(main())
