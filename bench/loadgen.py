#!/usr/bin/env python3
"""loadgen.py —— Quelmara 网络栈负载测试（临时工具，Python 允许）

用法：python bench/loadgen.py <mode>
  short      短连接 RPS：每请求新建连接 GET /，2000 次
  long       长连接 keep-alive：单连接 2000 请求流水线式
  concur     并发长连接：100 连接 x 100 请求（十万连接模型的抽样验证）
  mem        服务器进程内存读数（配合上面任一模式后运行）

目标服务器：examples/http_demo.qex（127.0.0.1:8091）
"""
import socket
import sys
import time

HOST, PORT = "127.0.0.1", 8091
REQ = b"GET / HTTP/1.1\r\nHost: bench\r\n"


def short_conns(n=2000):
    t0 = time.perf_counter()
    for _ in range(n):
        s = socket.create_connection((HOST, PORT), timeout=5)
        s.sendall(REQ + b"Connection: close\r\n\r\n")
        while s.recv(4096):
            pass
        s.close()
    dt = time.perf_counter() - t0
    print(f"short: {n} conns in {dt:.2f}s = {n/dt:.0f} req/s"
          f"  ({dt/n*1e6:.0f} us/req incl. connect+close)")


def long_conn(n=2000):
    s = socket.create_connection((HOST, PORT), timeout=5)
    s.sendall(REQ + b"\r\n")          # keep-alive
    s.recv(4096)
    t0 = time.perf_counter()
    buf = b""
    got = 0
    s.sendall(REQ + b"\r\n" * n)      # 流水线：一次写 n 个请求
    s.settimeout(10)
    while got < n:
        c = s.recv(65536)
        if not c:
            break
        buf += c
        got = buf.count(b"HTTP/1.1 200")
    dt = time.perf_counter() - t0
    s.close()
    print(f"long: {n} pipelined reqs in {dt:.3f}s = {n/dt:.0f} req/s"
          f"  ({dt/n*1e6:.1f} us/req)")


def concur(conns=100, per=100):
    socks = []
    t0 = time.perf_counter()
    for _ in range(conns):
        s = socket.create_connection((HOST, PORT), timeout=5)
        s.sendall(REQ + b"\r\n")
        s.recv(4096)
        socks.append(s)
    t_conn = time.perf_counter() - t0
    t0 = time.perf_counter()
    for s in socks:
        s.sendall((REQ + b"\r\n") * per)
    total = conns * per
    buf = {i: b"" for i in range(conns)}
    done = 0
    socks[0].settimeout(10)
    while done < total:
        for i, s in enumerate(socks):
            try:
                c = s.recv(65536)
            except socket.timeout:
                continue
            if c:
                buf[i] += c
                done = sum(b.count(b"HTTP/1.1 200") for b in buf.values())
            else:
                done = total
    dt = time.perf_counter() - t0
    for s in socks:
        s.close()
    print(f"concur: {conns} keep-alive conns x {per} req = {total} reqs"
          f" in {dt:.2f}s = {total/dt:.0f} req/s"
          f"  (connect phase {t_conn:.2f}s = {conns/t_conn:.0f} conn/s)")


def mem():
    import subprocess
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq http_demo.qex",
                        "/FO", "CSV", "/NH"], capture_output=True, text=True)
    print("server memory:", r.stdout.strip())


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "short"
    {"short": short_conns, "long": long_conn,
     "concur": concur, "mem": mem}[mode]()
