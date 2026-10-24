#!/usr/bin/env python3
"""net_bench.py —— 服务端网络栈探针（v2.12，Python 只做压测客户端）

用法：
  python tools/dev/net_bench.py echo [--conns 4] [--reqs 500] [--reps 3] [--threads 1]
  python tools/dev/net_bench.py http [--conns 4] [--reqs 500] [--reps 3] [--threads 1]

`--threads n` 把 conns 条连接分给 n 个客户端线程（每线程各自顺序收发），
用于测**服务端多核吞吐**——单线程客户端在 4 条连接上就先把自己压满了。

口径（与 06-status.md 的其它数字同源）：
  * 每个连接**顺序**发一条、读回一条（量的是往返延迟 RTT，不是吞吐上限）。
  * 报告 min-of-reps 的「总 req/s」与 RTT 的 p50 / p99（微秒）。
  * 客户端和服务端在同一台机器上，回环本身有 ~30-40 µs 的固定成本，
    所以绝对值只能纵向比，别拿它当"网络性能"对外宣传。

服务端由调用方先起：
  build/echo_bench.exe                                  # echo 19532
  build/http_demo.exe                                   # http 8091
"""
import argparse
import socket
import statistics
import sys
import threading
import time

TARGETS = {
    "echo": ("127.0.0.1", 19532, b"ping-32-bytes-payload-0123456789"),
    "http": ("127.0.0.1", 8091, b"GET / HTTP/1.1\r\nHost: bench\r\n\r\n"),
    "cpu": ("127.0.0.1", 19533, b"ping-32-bytes-payload-0123456789"),
}


def one_round(host, port, payload, conns, reqs, threads=1):
    """conns 条长连接，每条顺序发 reqs 次；返回 (总秒数, RTT 列表微秒)。"""
    if threads <= 1:
        return _one_round(host, port, payload, conns, reqs)
    per = max(1, conns // threads)
    out = [None] * threads
    barrier = threading.Barrier(threads + 1)

    def run(i):
        barrier.wait()
        out[i] = _one_round(host, port, payload, per, reqs)

    ts = [threading.Thread(target=run, args=(i,)) for i in range(threads)]
    for t in ts:
        t.start()
    barrier.wait()
    t0 = time.perf_counter()
    for t in ts:
        t.join()
    dt = time.perf_counter() - t0
    rtts = []
    for r in out:
        rtts.extend(r[1])
    return dt, rtts


def _one_round(host, port, payload, conns, reqs):
    socks = []
    for _ in range(conns):
        s = socket.create_connection((host, port), timeout=10)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        socks.append(s)
    rtts = []
    t0 = time.perf_counter()
    for _ in range(reqs):
        for s in socks:
            a = time.perf_counter()
            s.sendall(payload)
            got = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    raise RuntimeError("对端关闭")
                got += chunk
                if payload.startswith(b"GET "):
                    if got.endswith(b"\r\n\r\n") or b"\r\n\r\n" in got:
                        break
                elif len(got) >= len(payload):
                    break
            rtts.append((time.perf_counter() - a) * 1e6)
    dt = time.perf_counter() - t0
    for s in socks:
        s.close()
    return dt, rtts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=sorted(TARGETS))
    ap.add_argument("--conns", type=int, default=4)
    ap.add_argument("--reqs", type=int, default=500)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--threads", type=int, default=1)
    args = ap.parse_args()

    host, port, payload = TARGETS[args.mode]
    best = None
    for rep in range(args.reps):
        try:
            dt, rtts = one_round(host, port, payload, args.conns, args.reqs,
                                 args.threads)
        except Exception as e:                        # noqa: BLE001
            print(f"连接 {host}:{port} 失败：{e}（服务端起没起？）")
            return 2
        n = (args.conns // args.threads if args.threads > 1 else args.conns) * args.reqs * args.threads
        rps = n / dt
        rtts.sort()
        p50 = rtts[len(rtts) // 2]
        p99 = rtts[int(len(rtts) * 0.99)]
        line = (f"rep{rep + 1}: {n} req in {dt * 1000:.0f} ms = {rps:,.0f} req/s"
                f" | RTT p50 {p50:.0f} us  p99 {p99:.0f} us  mean {statistics.mean(rtts):.0f} us")
        print(line)
        if best is None or rps > best[0]:
            best = (rps, p50, p99, statistics.mean(rtts))

    rps, p50, p99, mean = best
    print(f"BEST {args.mode}: {rps:,.0f} req/s | p50 {p50:.0f} us | p99 {p99:.0f} us"
          f" | mean {mean:.0f} us  (conns={args.conns}, reqs={args.reqs},"
          f" threads={args.threads})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
