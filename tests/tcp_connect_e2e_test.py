"""t198 驱动：`tcp_connect` / `tcp_send_n_to` / `tcp_recv_to` 端到端差分（v3.54）。

三个内建一起测，因为它们都绕不开 Winsock 的两个坑：

1. **`int` 返回值必须符号扩展**。Win64 的 `int` 返回只写 `eax`，
   `SOCKET_ERROR` 在 64 位寄存器里是 `0x00000000FFFFFFFF` —— 直接和 -1 比
   永远不等。`tcp_connect` 里用 `shl 32` / `sar 32` 处理。
2. **`getaddrinfo` 成功是 0、失败是 EAI_* 正数**，不是 `< 0`。

Python 端是独立实现（标准库 socket），这正是差分口径。

## 覆盖的场景

* `tcp_connect("127.0.0.1", port)` —— IPv4 字面量直连
* `tcp_connect("localhost", port)` —— 走 DNS，Windows 常先给 `::1`，
  必须沿 `ai_next` 回退到 v4（或直接连上 v6）
* `tcp_send_n_to` —— 零拷贝发送 + 发送超时
* `tcp_recv_to` —— 接收超时（对端不发时必须返回空串，不能挂死）

用法：
    python tests/tcp_connect_e2e_test.py
    python tests/tcp_connect_e2e_test.py --exe X
"""

import os
import socket
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
SRC = os.path.join(ROOT, "tests", "t198_qlmc_tcp_connect.qma")
EXE = os.path.join(ROOT, "build", "t198_qlmc_tcp_connect.exe")
PORT = 39520

PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"[PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"[FAIL] {msg}")


def build():
    if not os.path.exists(QLMC):
        print("[build] build/qlmc.exe 不存在，先自举…")
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "stage0", "qlm_cli.py"),
             "build", os.path.join(ROOT, "bootstrap", "qlmc", "qlmc.qma"),
             "--target", "win", "-o", QLMC],
            capture_output=True, text=True, timeout=1200)
        if r.returncode != 0:
            print(r.stdout)
            print(r.stderr)
            raise SystemExit("[build] qlmc 自举失败")
    r = subprocess.run([QLMC, "build", SRC, "-o", EXE],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit(f"[build] 编译 t198 失败 rc={r.returncode}")
    print(f"[build] t198_qlmc_tcp_connect.exe {os.path.getsize(EXE)} B")


def make_listeners():
    """同时监听 v4 与 v6，这样 `localhost` 不管解析到哪个都能连上。

    只监听 v4 会让 Windows 的 `localhost`（常先给 `::1`）走回退路径 ——
    那是另一个测试点，不该混在这条里。
    """
    s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s4.bind(("127.0.0.1", PORT))
    s4.listen(8)
    s4.settimeout(0.5)
    s6 = None
    try:
        s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s6.bind(("::1", PORT))
        s6.listen(8)
        s6.settimeout(0.5)
    except OSError:
        s6 = None
    return s4, s6


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--exe":
        exe = argv[1]
    else:
        build()
        exe = EXE
    if not os.path.exists(exe):
        raise SystemExit(f"[build] 找不到 {exe}")

    s4, s6 = make_listeners()
    stop = threading.Event()

    def serve(s):
        while not stop.is_set():
            try:
                c, _ = s.accept()
            except OSError:
                continue
            try:
                c.settimeout(5)
                d = c.recv(1024)
                if d:
                    c.sendall(b"echo:" + d)
            except OSError:
                pass
            finally:
                try:
                    c.close()
                except OSError:
                    pass

    threads = [threading.Thread(target=serve, args=(s4,), daemon=True)]
    if s6:
        threads.append(threading.Thread(target=serve, args=(s6,), daemon=True))
    for t in threads:
        t.start()

    try:
        p = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    finally:
        stop.set()
        time.sleep(0.2)
        for s in (s4, s6):
            if s:
                try:
                    s.close()
                except OSError:
                    pass

    print("--- exe stdout ---")
    print(p.stdout)
    if p.stderr.strip():
        print("--- exe stderr ---")
        print(p.stderr)

    if "v4_ok=1" in p.stdout:
        ok("tcp_connect 连 127.0.0.1 成功（IPv4 字面量直连）")
    else:
        bad("tcp_connect 没连上 127.0.0.1")

    if "v4_echo=echo:ping" in p.stdout:
        ok("tcp_send_n_to / tcp_recv_to 收发正确（v4）")
    else:
        bad("v4 收发不对")

    if "v4_timeout_empty=1" in p.stdout:
        ok("tcp_recv_to 对端不发时返回空串（不挂死）")
    else:
        bad("tcp_recv_to 超时语义不对")

    if "dns_ok=1" in p.stdout:
        ok("tcp_connect 连 localhost 成功（走 DNS + ai_next 回退）")
    else:
        bad("tcp_connect 没连上 localhost")

    if "dns_echo=echo:pong" in p.stdout:
        ok("localhost 连接收发正确")
    else:
        bad("localhost 收发不对")

    if "badhost_neg=1" in p.stdout:
        ok("不存在的域名被拦下（getaddrinfo 非 0 → fail-fast）")
    else:
        bad("不存在的域名没被拦下")

    if p.returncode == 0:
        ok("退出码 0")
    else:
        bad(f"退出码 {p.returncode}")

    print(f"\n=== t198 tcp_connect e2e: PASS={PASS} FAIL={FAIL} ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
