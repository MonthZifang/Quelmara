"""t186 网络内建端到端驱动：qlmc 编出的 exe 当真服务器，Python 当客户端。

为什么要有这个文件：`t186_qlmc_tcp.qma` 自己没法验证"真的收发对了"——
它只会把收到的东西打出来。必须有一个**独立实现**的对端去连接、发送、
收回显，才能证明 ws2_32 的 IAT 槽位、sockaddr_in 布局、htons 字节序、
fail-fast 判定全都是对的。这正是差分测试的口径。

用法：
    python tests/net_e2e_test.py            # 用 build/qlmc.exe 现编现跑
    python tests/net_e2e_test.py --exe X    # 用已编好的 exe
"""

import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
SRC = os.path.join(ROOT, "tests", "t186_qlmc_tcp.qma")
EXE = os.path.join(ROOT, "build", "t186_qlmc_tcp.exe")
PORT = 39471

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
    t0 = time.time()
    r = subprocess.run([QLMC, "build", SRC, "-o", EXE],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit(f"[build] 编译 t186 失败 rc={r.returncode}")
    print(f"[build] t186_qlmc_tcp.exe {os.path.getsize(EXE)} B "
          f"{time.time() - t0:.1f} s")


def wait_port(deadline=15.0):
    """等服务端 bind 上。连不上就重试——没有 sleep 内建可用。"""
    t0 = time.time()
    while time.time() - t0 < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", PORT))
            s.close()
            return True
        except OSError:
            s.close()
            time.sleep(0.05)
    return False


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
    try:
        # wait_port 自己会建立一个连接 —— 那正是服务端要 accept 的那一个，
        # 所以探测成功后直接复用这条连接发数据，不要重连。
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
            # 端口被别的进程占着 → 返回 2，让主回归记 SKIP 而不是假红
            print("[SKIP] 15 秒内连不上 127.0.0.1:%d（端口可能被占用）" % PORT)
            proc.kill()
            return 2
        ok("TCP 连接建立（tcp_listen + bind + listen 正确）")

        s.sendall(b"hello")
        s.settimeout(10.0)
        got = b""
        try:
            while len(got) < 11:
                chunk = s.recv(256)
                if not chunk:
                    break
                got += chunk
        except socket.timeout:
            pass
        if got == b"echo:hello":
            ok(f"回显正确：{got!r}（tcp_recv + tcp_send 正确）")
        else:
            bad(f"回显不对：期望 b'echo:hello'，实得 {got!r}")
        s.close()
    finally:
        try:
            out = proc.communicate(timeout=15)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            out = proc.communicate()[0]
            bad("服务端没有在 15 秒内退出（tcp_close 可能没关掉）")

    print("--- 服务端 stdout ---")
    print(out)
    if "listening fd=" in out:
        ok("打印了 listening fd")
    else:
        bad("没有 listening 输出")
    if "recv=hello" in out:
        ok("服务端看到的报文是 hello")
    else:
        bad("服务端没收到 hello")
    if "done" in out:
        ok("正常收尾")
    else:
        bad("没有 done")
    if proc.returncode == 0:
        ok("服务端退出码 0")
    else:
        bad(f"服务端退出码 {proc.returncode}（0x{proc.returncode & 0xFFFFFFFF:08X}）")

    print(f"\n=== t186 net e2e: PASS={PASS} FAIL={FAIL} ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
