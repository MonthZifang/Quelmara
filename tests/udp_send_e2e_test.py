"""t192 驱动：UDP **发送侧**内建端到端差分（v3.49）。

背景：`udp_sendto` / `udp_sendto6` 在 v3.44 一上线就 `0xC0000005`，
当时查了约 40 轮没定位（docs/07-gaps.md §7.36）。v3.49 找到根因：
`_bi_udp_sendto` 的 v4 分支用 `OP_ADDRF ip` 再 `OP_COPY`，
而 `ADDRF` 的语义是 `dst = a 的**值** + imm`（把 a 当指针）。
`ip` 是普通 u32，`ADDRF ip, 0` 得到 `lea rX, [rIp]` = 地址 0x0100007F，
`COPY` 从那儿读 4 字节必然 AV。

本测试把修复钉死：Python 端是独立实现（标准库 socket），
正是差分口径 —— 服务端 exe 发三个 datagram，Python 端逐字节比对；
之后 Python 端回一个，exe 用 `udp_recvfrom_to` 收，验证同一 fd 双向可用。

用法：
    python tests/udp_send_e2e_test.py
    python tests/udp_send_e2e_test.py --exe X
"""

import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
SRC = os.path.join(ROOT, "tests", "t192_qlmc_udp_send.qma")
EXE = os.path.join(ROOT, "build", "t192_qlmc_udp_send.exe")
CLI_PORT = 39482

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
        raise SystemExit(f"[build] 编译 t192 失败 rc={r.returncode}")
    print(f"[build] t192_qlmc_udp_send.exe {os.path.getsize(EXE)} B")


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--exe":
        exe = argv[1]
    else:
        build()
        exe = EXE
    if not os.path.exists(exe):
        raise SystemExit(f"[build] 找不到 {exe}")

    # Python 端先绑好，避免 exe 发出去时还没人收（UDP 会丢包）
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", CLI_PORT))
    srv.settimeout(8.0)

    proc = subprocess.Popen([exe], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)

    got = []
    peer = None
    try:
        for _ in range(3):
            data, addr = srv.recvfrom(2048)
            got.append(data)
            peer = addr
    except socket.timeout:
        bad(f"只收到 {len(got)} 个 datagram（期望 3 个）")

    if got and got[0] == b"alpha":
        ok("udp_sendto 发出第 1 个 datagram（alpha）")
    else:
        bad(f"第 1 个 datagram 内容不对：{got[0] if got else None!r}")

    if len(got) > 1 and got[1] == b"bravo":
        ok("同一 fd 复用于第 2 个 datagram（bravo）")
    else:
        bad(f"第 2 个 datagram 内容不对：{got[1] if len(got) > 1 else None!r}")

    if len(got) > 2 and got[2] == b"charlie":
        ok("std/net/udp 的 udp_send_str 走通（charlie）")
    else:
        bad(f"第 3 个 datagram 内容不对：{got[2] if len(got) > 2 else None!r}")

    # 回一个，验证同一 fd 双向
    if peer:
        try:
            srv.sendto(b"pong", peer)
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

    if "n1=5" in out:
        ok("udp_sendto 返回发送字节数 5（alpha）")
    else:
        bad("n1 不是 5（返回值口径不对）")
    if "n2=5" in out:
        ok("udp_sendto 复用 fd 返回 5（bravo）")
    else:
        bad("n2 不是 5")
    if "n3=7" in out:
        ok("udp_send_str 返回 7（charlie）")
    else:
        bad("n3 不是 7")
    if "nbad=-1" in out:
        ok("地址非法时 udp_send_str 返回 -1（不崩）")
    else:
        bad("nbad 不是 -1")
    if "back=pong" in out:
        ok("同一 fd 收方向可用（udp_recvfrom_to 收到 pong）")
    else:
        bad("没收到 pong")
    if "done" in out:
        ok("正常收尾")
    else:
        bad("没有 done")
    if proc.returncode == 0:
        ok("退出码 0")
    else:
        bad(f"退出码 {proc.returncode}")

    srv.close()
    print(f"\n=== t192 udp send e2e: PASS={PASS} FAIL={FAIL} ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
