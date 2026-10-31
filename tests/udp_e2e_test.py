"""t188 驱动：UDP 接收侧内建端到端差分。

验证 `udp_open` / `udp_bind` / `udp_recvfrom` / `udp_recvfrom_to`。
`udp_sendto` 本版未实现（见 CHANGELOG v3.44），所以只测接收侧。

Python 端是独立实现（标准库 socket），这正是差分口径：
服务端 exe 收三个 datagram，其中第三个故意不发，验证超时返回空串。

用法：
    python tests/udp_e2e_test.py
    python tests/udp_e2e_test.py --exe X
"""

import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
SRC = os.path.join(ROOT, "tests", "t188_qlmc_udp.qma")
EXE = os.path.join(ROOT, "build", "t188_qlmc_udp.exe")
SRV_PORT = 39480

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
        raise SystemExit(f"[build] 编译 t188 失败 rc={r.returncode}")
    print(f"[build] t188_qlmc_udp.exe {os.path.getsize(EXE)} B")


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--exe":
        exe = argv[1]
    else:
        build()
        exe = EXE
    if not os.path.exists(exe):
        raise SystemExit(f"[build] 找不到 {exe}")

    proc = subprocess.Popen([exe], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    time.sleep(0.6)

    cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        cli.sendto(b"alpha", ("127.0.0.1", SRV_PORT))
        time.sleep(0.25)
        cli.sendto(b"bravo", ("127.0.0.1", SRV_PORT))
        # 第三个故意不发，服务端应当超时拿到空串
    except OSError as e:
        print(f"[SKIP] 发不出去（{e}）")
        cli.close()
        proc.kill()
        return 2
    cli.close()

    try:
        out = proc.communicate(timeout=25)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        out = proc.communicate()[0]
        bad("服务端没有在 25 秒内退出（超时收没生效？）")

    print("--- 服务端 stdout ---")
    print(out)

    if "recv1=alpha" in out:
        ok("udp_recvfrom 收到第 1 个 datagram（alpha）")
    else:
        bad("没收到 alpha")
    if "recv2=bravo" in out:
        ok("udp_recvfrom_to 收到第 2 个 datagram（bravo）")
    else:
        bad("没收到 bravo")
    if "recv3len=0" in out:
        ok("超时（300ms）返回空串 —— 不挂死")
    else:
        bad("超时收的返回值不对")
    if "done" in out:
        ok("正常收尾")
    else:
        bad("没有 done")
    if proc.returncode == 0:
        ok("服务端退出码 0")
    else:
        bad(f"服务端退出码 {proc.returncode}")

    print(f"\n=== t188 udp e2e: PASS={PASS} FAIL={FAIL} ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
