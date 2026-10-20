#!/usr/bin/env bash
# =============================================================================
# Quelmara io_uring 网络后端自测
#   1. 用 tools/stage0/qlm_uring.py 发射 C 运行时（三种背压策略 + max_conns 极小值）
#   2. gcc -fsyntax-only 语法检查（含 -std=c99；无 <linux/io_uring.h> 也必须过）
#   3. 有 <linux/io_uring.h> 时 gcc -O2 编译，否则优雅降级跳过编译与回环
#   4. 真实回环：起 echo server，20 并发连接各发一段数据验证回显
#   5. 背压三策略烟测（drop/close/block）+ max_conns fail-fast 拒绝测试
# 退出码 0 = 全部通过（SKIP 为环境限制，不算失败）
# =============================================================================
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY=python3
WORK="$ROOT/build/uring-test.$$"
mkdir -p "$WORK"

PASS=0; FAIL=0; SKIP=0
ok()   { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
skip() { echo "  [SKIP] $1"; SKIP=$((SKIP + 1)); }

SERVER_PID=""
cleanup() {
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
    [ -n "$SERVER_PID" ] && wait "$SERVER_PID" 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

command -v gcc >/dev/null 2>&1 || { echo "gcc 缺失，无法测试"; exit 1; }
command -v "$PY" >/dev/null 2>&1 || { echo "python3 缺失，无法测试"; exit 1; }

# -----------------------------------------------------------------------------
echo "== 1. 发射 C 运行时 =="
for BP in drop close block; do
    if "$PY" tools/stage0/qlm_uring.py emit --max-conns 1000000 --backpressure "$BP" \
            > "$WORK/rt_$BP.c" 2>"$WORK/emit_$BP.err"; then
        ok "emit --backpressure $BP"
    else
        fail "emit --backpressure $BP"; cat "$WORK/emit_$BP.err"
    fi
done
# 极小 max_conns：用于 fail-fast 拒绝测试
if "$PY" tools/stage0/qlm_uring.py emit --max-conns 2 --backpressure drop \
        > "$WORK/rt_limit.c" 2>"$WORK/emit_limit.err"; then
    ok "emit --max-conns 2"
else
    fail "emit --max-conns 2"; cat "$WORK/emit_limit.err"
fi

# -----------------------------------------------------------------------------
echo "== 2. 语法检查（gcc -fsyntax-only） =="
for f in "$WORK"/rt_*.c; do
    b=$(basename "$f")
    if gcc -fsyntax-only "$f" 2>"$WORK/syn_$b.err"; then ok "syntax $b"; else fail "syntax $b"; cat "$WORK/syn_$b.err"; fi
    if gcc -std=c99 -fsyntax-only "$f" 2>>"$WORK/syn_$b.err"; then ok "syntax-c99 $b"; else fail "syntax-c99 $b"; cat "$WORK/syn_$b.err"; fi
done

# -----------------------------------------------------------------------------
# 头文件探测：<linux/io_uring.h> 不存在时优雅降级
HAVE_URING_H=1
if ! echo '#include <linux/io_uring.h>' | gcc -E - >/dev/null 2>&1; then
    HAVE_URING_H=0
fi

if [ "$HAVE_URING_H" = 0 ]; then
    skip "系统缺少 <linux/io_uring.h>：跳过 -O2 编译与回环测试（语法检查已通过）"
    echo
    echo "结果: PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
    [ "$FAIL" = 0 ] && exit 0 || exit 1
fi

# -----------------------------------------------------------------------------
echo "== 3. gcc -O2 编译（-Wall -Wextra 提示不视为失败） =="
for BP in drop close block; do
    if gcc -O2 -Wall -Wextra -o "$WORK/rt_$BP" "$WORK/rt_$BP.c" 2>"$WORK/cc_$BP.log"; then
        ok "build rt_$BP"
    else
        fail "build rt_$BP"; cat "$WORK/cc_$BP.log"
    fi
done
if gcc -O2 -o "$WORK/rt_limit" "$WORK/rt_limit.c" 2>"$WORK/cc_limit.log"; then
    ok "build rt_limit"
else
    fail "build rt_limit"; cat "$WORK/cc_limit.log"
fi

# -----------------------------------------------------------------------------
echo "== 4. 回环测试 =="
pick_port() {
    "$PY" - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}

start_server() { # $1=binary  $2=port
    "$1" "127.0.0.1:$2" > "$WORK/server.log" 2>&1 &
    SERVER_PID=$!
    for _ in $(seq 1 50); do
        if grep -q "QLM_URING_READY" "$WORK/server.log" 2>/dev/null; then
            return 0
        fi
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            # 内核未启用 io_uring（退出码 42）等环境问题
            wait "$SERVER_PID"; rc=$?
            SERVER_PID=""
            if [ "$rc" = 42 ] && grep -q "QLM_URING_UNAVAILABLE" "$WORK/server.log"; then
                return 42
            fi
            return 1
        fi
        sleep 0.1
    done
    return 1
}

stop_server() {
    [ -n "$SERVER_PID" ] || return 0
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
    SERVER_PID=""
}

# 20 并发连接各发一段数据，验证逐字节回显
run_echo_test() { # $1=port  $2=label
    if "$PY" - "$1" > "$WORK/client.log" 2>&1 <<'PY'
import socket, sys, threading

port = int(sys.argv[1])
errors = []

def worker(i):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        payload = ("quelmara-uring-echo-%d-" % i).encode() * 20
        s.sendall(payload)
        got = b""
        s.settimeout(5)
        while len(got) < len(payload):
            chunk = s.recv(4096)
            if not chunk:
                break
            got += chunk
        if got != payload:
            errors.append("conn %d echo mismatch: got %d/%d bytes" % (i, len(got), len(payload)))
        s.close()
    except Exception as e:  # noqa: BLE001
        errors.append("conn %d: %r" % (i, e))

ts = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
for t in ts: t.start()
for t in ts: t.join()
if errors:
    print("\n".join(errors))
    sys.exit(1)
PY
    then
        ok "$2 回环（20 并发，逐字节校验）"
    else
        fail "$2 回环（20 并发）"; cat "$WORK/client.log"
    fi
}

RUNTIME_UNAVAILABLE=0

for BP in drop close block; do
    PORT=$(pick_port)
    start_server "$WORK/rt_$BP" "$PORT"
    rc=$?
    if [ "$rc" = 42 ]; then
        RUNTIME_UNAVAILABLE=1
        break
    elif [ "$rc" != 0 ]; then
        fail "启动 rt_$BP 失败"; cat "$WORK/server.log"
        continue
    fi
    run_echo_test "$PORT" "backpressure=$BP"
    stop_server
done

if [ "$RUNTIME_UNAVAILABLE" = 1 ]; then
    skip "内核未启用 io_uring / 被 seccomp 拦截：跳过回环与背压测试"
    echo
    echo "结果: PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
    [ "$FAIL" = 0 ] && exit 0 || exit 1
fi

# -----------------------------------------------------------------------------
echo "== 5. 背压策略烟测（32MB 爆写，远超内核 socket 缓冲，确定性触发） =="
BPSIZE=33554432   # 32MB >> 内核 sndbuf/rcvbuf 吸收能力（约 4MB）

# 服务端退出后核对统计计数，证明对应背压路径真的被走到
check_stat() { # $1=label  $2=stat 名（要求 >0）
    val=$(grep -oE "$2=[0-9]+" "$WORK/server.log" | tail -1 | cut -d= -f2)
    if [ -n "$val" ] && [ "$val" -gt 0 ]; then ok "$1（$2=$val）"; else fail "$1（$2=${val:-未输出}）"; fi
}

# drop：爆写不读回显 -> 发送限额溢出丢余量，连接与服务都必须存活
PORT=$(pick_port)
if start_server "$WORK/rt_drop" "$PORT"; then
    if "$PY" - "$PORT" "$BPSIZE" > "$WORK/bp_drop.log" 2>&1 <<'PY'
import socket, sys
port, size = int(sys.argv[1]), int(sys.argv[2])
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2048)  # 小窗口：背压确定性触发
s.settimeout(10)
s.connect(("127.0.0.1", port))
blob = b"x" * 65536
sent = 0
try:
    while sent < size:                    # 爆写，不读回显 -> 触发 drop 背压
        sent += s.send(blob)
except OSError:
    pass                                  # drop 模式不应断开；写错误容忍
s.close()
c = socket.create_connection(("127.0.0.1", port), timeout=5)   # 新连接必须正常
c.sendall(b"ping-after-drop")
c.settimeout(5)
got = b""
while len(got) < len(b"ping-after-drop"):
    chunk = c.recv(4096)
    if not chunk:
        break
    got += chunk
assert got == b"ping-after-drop", "drop 后新连接回显异常: %r" % got
c.close()
print("sent %d bytes" % sent)
PY
    then ok "drop：爆写后服务存活、新连接回显正常"; else fail "drop 背压烟测"; cat "$WORK/bp_drop.log"; fi
else
    fail "启动 rt_drop 失败"
fi
stop_server
grep -q "QLM_URING_READY" "$WORK/server.log" && check_stat "drop 路径已触发" dropped

# close：爆写不读回显 -> 发送限额溢出主动断开，服务本身存活
PORT=$(pick_port)
if start_server "$WORK/rt_close" "$PORT"; then
    if "$PY" - "$PORT" "$BPSIZE" > "$WORK/bp_close.log" 2>&1 <<'PY'
import socket, sys
port, size = int(sys.argv[1]), int(sys.argv[2])
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2048)
s.settimeout(10)
s.connect(("127.0.0.1", port))
blob = b"x" * 65536
closed = False
sent = 0
try:
    while sent < size:
        sent += s.send(blob)
except OSError:
    closed = True                          # EPIPE/ECONNRESET：服务端已断开
if not closed:
    got = 0
    try:
        while True:
            chunk = s.recv(65536)
            if chunk == b"":               # EOF：服务端主动断开
                closed = True
                break
            got += len(chunk)
            if got >= size:
                break                      # 回显完整 = 服务端没断开 = 失败
    except OSError:
        closed = True
s.close()
assert closed, "close 背压未触发断开（已发送 %d 字节）" % sent
c = socket.create_connection(("127.0.0.1", port), timeout=5)   # 服务仍须可用
c.sendall(b"ping-after-close")
c.settimeout(5)
got = b""
while len(got) < len(b"ping-after-close"):
    chunk = c.recv(4096)
    if not chunk:
        break
    got += chunk
assert got == b"ping-after-close", "close 后新连接回显异常: %r" % got
c.close()
print("sent %d bytes" % sent)
PY
    then ok "close：爆写触发服务端断开、服务存活"; else fail "close 背压烟测"; cat "$WORK/bp_close.log"; fi
else
    fail "启动 rt_close 失败"
fi
stop_server
grep -q "QLM_URING_READY" "$WORK/server.log" && check_stat "close 路径已触发" bp_close

# block：慢读 + 爆写 32MB 全量回显一条不丢（任务级阻塞重试、reactor 不卡）
PORT=$(pick_port)
if start_server "$WORK/rt_block" "$PORT"; then
    if "$PY" - "$PORT" "$BPSIZE" > "$WORK/bp_block.log" 2>&1 <<'PY'
import socket, sys, threading, time
port, size = int(sys.argv[1]), int(sys.argv[2])
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2048)  # 小窗口：逼出 hold 挂起路径
s.settimeout(30)
s.connect(("127.0.0.1", port))
blob = (b"quelmara-block-0123456789;" * (size // 24 + 1))[:size]
recv_buf = bytearray()
err = []

def reader():
    try:
        while len(recv_buf) < size:
            chunk = s.recv(65536)
            if not chunk:
                break
            recv_buf.extend(chunk)
            time.sleep(0.001)              # 慢读：制造真实发送背压
    except Exception as e:  # noqa: BLE001
        err.append(repr(e))

t = threading.Thread(target=reader)
t.start()
sent = 0
while sent < size:                          # 爆写；block 背压下数据不许丢
    sent += s.send(blob[sent:sent + 65536])
t.join(60)
s.close()
assert not err, "block 读线程异常: %s" % err
assert bytes(recv_buf) == blob, "block 背压数据丢失/损坏: 收到 %d/%d 字节" % (len(recv_buf), size)
print("echoed %d bytes zero-loss" % sent)
PY
    then ok "block：32MB 全量回显零丢失"; else fail "block 背压烟测"; cat "$WORK/bp_block.log"; fi
else
    fail "启动 rt_block 失败"
fi
stop_server
grep -q "QLM_URING_READY" "$WORK/server.log" && check_stat "block 路径已触发" bp_block

# -----------------------------------------------------------------------------
echo "== 6. max_conns fail-fast 拒绝测试（max_conns=2） =="
PORT=$(pick_port)
if start_server "$WORK/rt_limit" "$PORT"; then
    if "$PY" - "$PORT" > "$WORK/limit.log" 2>&1 <<'PY'
import socket, sys, time
port = int(sys.argv[1])
held = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(2)]
time.sleep(0.5)                             # 等服务端 accept 完成并占满配额
s = socket.create_connection(("127.0.0.1", port), timeout=5)
s.settimeout(5)
data = s.recv(64)                           # fail-fast：新 fd 被服务端直接关闭
assert data == b"", "超限连接未被拒绝，收到: %r" % data
s.close()
for h in held:
    h.close()
PY
    then ok "max_conns=2：第 3 个连接被 fail-fast 拒绝"; else fail "max_conns 拒绝测试"; cat "$WORK/limit.log"; fi
else
    fail "启动 rt_limit 失败"
fi
stop_server

# -----------------------------------------------------------------------------
echo
echo "结果: PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
[ "$FAIL" = 0 ] && exit 0 || exit 1
