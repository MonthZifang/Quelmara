"""t187 驱动：tcp_peer_raw 的字节级差分。

为什么需要这个：`tcp_peer_raw` 返回的是一个**手工拼出来的字节布局**
（端口网络序 / family / 地址），任何一处偏移错了都只是"读出垃圾数字"，
不会崩。必须有一个独立实现的对端去连接，再用 Python 自己算一遍期望值，
逐字节比对 —— 这正是差分口径。

用法：
    python tests/peer_e2e_test.py           # 现编现跑
    python tests/peer_e2e_test.py --exe X
"""

import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
SRC = os.path.join(ROOT, "tests", "t187_qlmc_peer.qma")
EXE = os.path.join(ROOT, "build", "t187_qlmc_peer.exe")
PORT = 39475

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
            capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            print(r.stdout)
            print(r.stderr)
            raise SystemExit("[build] qlmc 自举失败")
    r = subprocess.run([QLMC, "build", SRC, "-o", EXE],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit(f"[build] 编译 t187 失败 rc={r.returncode}")
    print(f"[build] t187_qlmc_peer.exe {os.path.getsize(EXE)} B")


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
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10.0)
    connected = False
    t0 = time.time()
    while time.time() - t0 < 15.0:
        try:
            s.connect(("127.0.0.1", PORT))
            connected = True
            break
        except OSError:
            time.sleep(0.05)
    if not connected:
        print("[SKIP] 15 秒内连不上 127.0.0.1:%d（端口可能被占用）" % PORT)
        proc.kill()
        return 2

    # 客户端这边的本地端口 —— 服务端看到的"对端端口"就是它
    local_port = s.getsockname()[1]
    s.sendall(b"hi")

    s.settimeout(10.0)
    try:
        s.recv(64)          # "ok"，只用来同步
    except socket.timeout:
        pass
    s.close()

    try:
        out = proc.communicate(timeout=15)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        out = proc.communicate()[0]
        bad("服务端没有在 15 秒内退出")

    print("--- 服务端 stdout ---")
    print(out)

    def field(name):
        for ln in out.splitlines():
            if ln.startswith(name + "="):
                try:
                    return int(ln.split("=", 1)[1])
                except ValueError:
                    return None
        return None

    if field("raw len") == 20:
        ok("peer_raw 返回 20 字节")
    else:
        bad(f"peer_raw 长度不对：{field('raw len')}")

    # 端口：网络序 = 高字节在前
    want_hi = (local_port >> 8) & 0xFF
    want_lo = local_port & 0xFF
    if field("b0") == want_hi and field("b1") == want_lo:
        ok(f"端口网络序正确：{want_hi} {want_lo}（本地端口 {local_port}）")
    else:
        bad(f"端口网络序错：期望 {want_hi} {want_lo}，"
            f"实得 {field('b0')} {field('b1')}")

    # family = 2（AF_INET）
    if field("fam") == 2:
        ok("family == 2（AF_INET）")
    else:
        bad(f"family 错：期望 2，实得 {field('fam')}")

    if field("b3") == 0:
        ok("b3 == 0（填充字节）")
    else:
        bad(f"b3 应为 0，实得 {field('b3')}")

    # 地址 = 127.0.0.1
    got_ip = [field("a%d" % i) for i in range(4)]
    if got_ip == [127, 0, 0, 1]:
        ok("对端地址 127.0.0.1")
    else:
        bad(f"对端地址错：期望 [127, 0, 0, 1]，实得 {got_ip}")

    if "done" in out:
        ok("正常收尾")
    else:
        bad("没有 done")
    if proc.returncode == 0:
        ok("服务端退出码 0")
    else:
        bad(f"服务端退出码 {proc.returncode}")

    print(f"\n=== t187 peer e2e: PASS={PASS} FAIL={FAIL} ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
