#!/usr/bin/env bash
# Quelmara v0.1 原型回归测试
# 1) hello  2) parfor 多核正确性  3) Quelmara.toml 禁用多核降级  4) epoll echo 并发实测
set -u
cd "$(dirname "$0")/.."
PASS=0; FAIL=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

echo "[1] hello.qma"
out=$(python3 tools/stage0/qlm.py run examples/hello.qma 2>/dev/null)
echo "$out" | grep -q "Hello, Quelmara" && ok "greet/字符串拼接" || bad "greet 输出缺失"
echo "$out" | grep -q "tick 2" && ok "while 循环" || bad "while 输出缺失"

echo "[2] parallel_sum.qma（多核 parfor）"
out=$(python3 tools/stage0/qlm.py run examples/parallel_sum.qma 2>/dev/null)
echo "$out" | grep -q "match   = true" && ok "并行归约 == 串行结果" || bad "并行结果错误"
grep -q "pthread_create" build/parallel_sum.c && ok "生成 pthread 分块并行代码" || bad "未生成并行代码"

echo "[3] 单核降级（tests/single_core/Quelmara.toml: multicore=false）"
cp examples/parallel_sum.qma tests/single_core/parallel_sum.qma
out=$(python3 tools/stage0/qlm.py run tests/single_core/parallel_sum.qma 2>/dev/null)
echo "$out" | grep -q "match   = true" && ok "串行降级结果不变（语义等价）" || bad "串行降级结果错误"
grep -q "串行降级" tests/single_core/build/parallel_sum.c 2>/dev/null || grep -q "串行降级" build/parallel_sum.c \
  && ok "编译期降级为串行（无 pthread）" || bad "未降级"
if ! grep -q "pthread_create" build/parallel_sum.c; then ok "单核产物无线程池"; else bad "单核产物仍含 pthread"; fi

echo "[4] net.TcpServer（epoll echo 并发实测）"
python3 tools/stage0/qlm.py build examples/echo_server.qma --cc >/dev/null 2>&1 || bad "echo_server 编译失败"
./build/echo_server >/dev/null 2>&1 &
SRV=$!
sleep 0.5
python3 - <<'EOF'
import socket, sys
ok_all = True
# 20 个并发连接各发一段数据，验证回显
import threading
results = []
def client(i):
    try:
        s = socket.create_connection(("127.0.0.1", 9000), timeout=3)
        msg = f"ping-{i}\n".encode()
        s.sendall(msg)
        data = s.recv(64)
        results.append(data == msg)
        s.close()
    except Exception as e:
        results.append(False)
ths = [threading.Thread(target=client, args=(i,)) for i in range(20)]
[t.start() for t in ths]
[t.join() for t in ths]
sys.exit(0 if all(results) and results else 1)
EOF
[ $? -eq 0 ] && ok "20 并发连接 echo 全部正确" || bad "echo 并发测试失败"
kill $SRV 2>/dev/null

echo "[5] 语言 v0.2：break/continue + struct（含 assert 自校验）"
for t in tests/t8.qma tests/t9.qma tests/t10.qma tests/t11.qma \
         examples/game_loop.qma examples/collatz.qma examples/inventory.qma \
         examples/prime_parallel.qma; do
  n=$(basename $t .qma)
  if python3 tools/stage0/qlm.py run $t >/dev/null 2>&1; then ok "$n 自校验通过"; else bad "$n 失败"; fi
done

echo "----------------------------------------"
echo "PASS=$PASS FAIL=$FAIL"
[ $FAIL -eq 0 ]
