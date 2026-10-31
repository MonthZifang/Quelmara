"""t193 驱动：UDP over IPv6 发送侧内建端到端差分（v3.49）。

`udp_sendto6` 与 v4 共用 `_bi_udp_sendto`，只有三处不同：
family 23、sockaddr 28 字节、地址 16 字节整块拷贝。本用例把 v6 路径钉住。

用法：
    python tests/udp6_send_e2e_test.py
    python tests/udp6_send_e2e_test.py --exe X
"""

import os
import socket
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
SRC = os.path.join(ROOT, "tests", "t193_qlmc_udp6_send.qma")
EXE = os.path.join(ROOT, "build", "t193_qlmc_udp6_send.exe")
CLI_PORT = 39483

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
    r = subprocess.run([QLMC, "build", SRC, "-o", EXE],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit(f"[build] 编译 t193 失败 rc={r.returncode}")
    print(f"[build] t193_qlmc_udp6_send.exe {os.path.getsize(EXE)} B")


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--exe":
        exe = argv[1]
    else:
        build()
        exe = EXE

    try:
        srv = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("::1", CLI_PORT))
        srv.settimeout(8.0)
    except OSError as e:
        print(f"[SKIP] 本机没有 IPv6 回环（{e}）")
        return 2

    proc = subprocess.Popen([exe], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)

    got = []
    peer = None
    try:
        for _ in range(2):
            data, addr = srv.recvfrom(2048)
            got.append(data)
            peer = addr
    except socket.timeout:
        bad(f"只收到 {len(got)} 个 datagram（期望 2 个）")

    if got and got[0] == b"v6alpha":
        ok("udp_sendto6 发出第 1 个 datagram（v6alpha）")
    else:
        bad(f"第 1 个 datagram 内容不对：{got[0] if got else None!r}")

    if len(got) > 1 and got[1] == b"v6bravo":
        ok("std/net/udp6 的 udp_send6 走通（v6bravo）")
    else:
        bad(f"第 2 个 datagram 内容不对：{got[1] if len(got) > 1 else None!r}")

    if peer:
        try:
            srv.sendto(b"pong6", peer)
        except OSError as e:
            bad(f"回包失败：{e}")

    try:
        out = proc.communicate(timeout=25)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        out = proc.communicate()[0]
        bad("exe 没有在 25 秒内退出")

    print("--- exe stdout ---")
    print(out)

    if "rawlen=16" in out:
        ok("ip6_parse 产出 16 字节网络序地址")
    else:
        bad("rawlen 不是 16")
    if "n1=7" in out:
        ok("udp_sendto6 返回 7（v6alpha）")
    else:
        bad("n1 不是 7")
    if "n2=7" in out:
        ok("udp_send6 返回 7（v6bravo）")
    else:
        bad("n2 不是 7")
    if "back=pong6" in out:
        ok("v6 同一 fd 收方向可用")
    else:
        bad("没收到 pong6")
    if "done" in out and proc.returncode == 0:
        ok("正常收尾，退出码 0")
    else:
        bad(f"收尾异常 rc={proc.returncode}")

    srv.close()
    print(f"\n=== t193 udp6 send e2e: PASS={PASS} FAIL={FAIL} ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
