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

echo "[4] 网络栈可用性（C99 后端**不提供** tcp_* 内建，这里按 SKIP 记账）"
# v2.91：这一段以前编 `examples/echo_server.qma` 并起 9000 端口跑 20 并发回显。
# 但它编不过——而且**从来就没编过**：
#   · echo_server.qma 用的是 `net.TcpServer { on_connect: ... }` 这套 SPEC 里的
#     富对象模型，从未实现（v2.91 已改写为真实可用的 `serve(...)` 形式）；
#   · 就算改写了，C99 后端也没有任何 `tcp_*` 内建（`std/net.qma` 里 `tcp_listen`
#     /`tcp_accept`/`tcp_send`/`tcp_recv`/`tcp_close` 全靠自研后端发射，
#     C 后端只有 `tcp_nodelay` 一个），所以网络用例在 C 链路上**结构上不可能**通过。
# 如实做法是：能跑的照跑，跑不了的记 SKIP 并给出判据，而不是让它天天红着
# 把整条 C 回归的可信度一起拉下去。
if grep -q '"tcp_listen"' tools/stage0/qlm.py; then
  python3 tools/stage0/qlm.py build examples/echo_concurrent.qma --cc >/dev/null 2>&1 \
    && ok "C 后端已支持 tcp_*（echo_concurrent 编过）" \
    || bad "C 后端声明支持 tcp_* 但 echo_concurrent 编不过"
else
  echo "  ⏭  SKIP：C99 后端无 tcp_* 内建（网络回归走 tests/test_uring.sh 的 io_uring 链路）"
fi

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
