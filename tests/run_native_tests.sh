#!/usr/bin/env bash
# Rosoto 自研原生后端 v0.1 回归测试
# 覆盖：正确性(双后端交叉验证) / 多核 clone / 单核降级 / divmod 语义 / 退出码(退出崩溃回归) / 静态 ELF
set -u
cd "$(dirname "$0")/.."
PASS=0; FAIL=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

NAT=python3\ tools/rosoto_native.py
NAT2=python3\ tools/rosoto_arm64.py
CBE=python3\ tools/rosoto.py

echo "[1] fib(25) 递归正确性 + 双后端交叉验证"
$NAT build examples/fib.ros -o build/nat_fib >/dev/null 2>&1
out=$(./build/nat_fib); rc=$?
[ $rc -eq 0 ] && ok "退出码 0（无退出崩溃）" || bad "退出码 $rc"
[ "$out" = "75025" ] && ok "fib(25)=75025" || bad "fib 输出 [$out]"

echo "[2] divmod 语义（正负/边界，160 行）双后端交叉验证"
$CBE build tests/divmod.ros --cc >/dev/null 2>&1; mv build/divmod build/c_divmod 2>/dev/null
./build/c_divmod > build/.dc 2>/dev/null
$NAT build tests/divmod.ros -o build/nat_divmod >/dev/null 2>&1
./build/nat_divmod > build/.dn; rc=$?
[ $rc -eq 0 ] && ok "退出码 0" || bad "退出码 $rc"
diff build/.dc build/.dn >/dev/null && ok "160 行全等（魔数除法 + idiv 回退语义一致）" || bad "divmod 输出不一致"

echo "[3] loop_sum 热循环（魔数优化路径）"
$NAT build examples/loop_sum.ros -o build/nat_loop >/dev/null 2>&1
out=$(./build/nat_loop); rc=$?
[ $rc -eq 0 ] && ok "退出码 0" || bad "退出码 $rc"
[ "$out" = "1199999988" ] && ok "结果 1199999988 与 C 后端一致" || bad "输出 [$out]"

echo "[4] parfor_sum 多核（raw clone + 共享内存归约）"
$NAT build examples/parfor_sum.ros -o build/nat_par >/dev/null 2>&1
out=$(./build/nat_par); rc=$?
[ $rc -eq 0 ] && ok "退出码 0" || bad "退出码 $rc"
[ "$out" = "11519999978" ] && ok "clone 多核归约 == pthread 后端结果" || bad "输出 [$out]"

echo "[5] 单核降级（tests/single_core/Rosoto.toml: multicore=false）"
cp examples/parfor_sum.ros tests/single_core/
$NAT build tests/single_core/parfor_sum.ros -o build/nat_par_1c >/dev/null 2>&1
out=$(timeout 120 ./build/nat_par_1c); rc=$?
[ $rc -eq 0 ] && ok "串行降级退出码 0" || bad "退出码 $rc"
[ "$out" = "11519999978" ] && ok "语义等价（结果不变）" || bad "输出 [$out]"

echo "[6] 静态裸 ELF（无 libc / 无解释器）"
if command -v readelf >/dev/null 2>&1; then
  readelf -l build/nat_fib 2>/dev/null | grep -q INTERP && bad "存在 PT_INTERP（动态链接）" || ok "无 PT_INTERP（自包含机器码）"
else
  head -c 4 build/nat_fib | grep -q ELF && ok "ELF 头有效" || bad "非 ELF"
fi

echo "[7] AArch64 发射器（自研模拟器执行级验证）"
for t in tests/t1.ros tests/dbg.ros; do
  n=$(basename $t .ros)
  $NAT2 build $t -o build/${n}_a64 >/dev/null 2>&1
  out=$(timeout 300 python3 tests/a64_emu.py build/${n}_a64 2>/dev/null)
  case $n in
    t1)  [ "$out" = "1" ]  && ok "a64 t1 => 1" || bad "a64 t1 [$out]";;
    dbg) [ "$out" = "18" ] && ok "a64 dbg => 18" || bad "a64 dbg [$out]";;
  esac
done
$NAT2 build examples/fib.ros -o build/fib_a64 >/dev/null 2>&1
out=$(timeout 600 python3 tests/a64_emu.py build/fib_a64 2>/dev/null)
[ "$out" = "75025" ] && ok "a64 fib(25) => 75025" || bad "a64 fib [$out]"
$NAT2 build tests/divmod.ros -o build/divmod_a64 >/dev/null 2>&1
timeout 600 python3 tests/a64_emu.py build/divmod_a64 > build/.dn64 2>/dev/null
diff build/.dc build/.dn64 >/dev/null && ok "a64 divmod 160 行与 x86/C 后端全等" || bad "a64 divmod 不一致"

echo "[8] 语言 v0.2：break/continue + struct（双后端交叉验证）"
for t in tests/t8.ros tests/t9.ros tests/t10.ros tests/t11.ros; do
  n=$(basename $t .ros)
  $NAT run $t 2>/dev/null | grep -v '^\[rosoto' > build/.x.$n; rc=${PIPESTATUS[0]}
  $CBE run $t 2>/dev/null | grep -v '^\[rosoto' > build/.y.$n
  [ $rc -eq 0 ] && ok "$n 退出码 0" || bad "$n 退出码 $rc"
  diff build/.x.$n build/.y.$n >/dev/null && ok "$n 双后端输出全等" || bad "$n 双后端不一致"
done

echo "[9] v0.2 新示例（游戏/算法/工程/多核，含 assert 自校验）"
for t in examples/game_loop.ros examples/collatz.ros examples/inventory.ros examples/prime_parallel.ros examples/traffic_light.ros; do
  n=$(basename $t .ros)
  $NAT run $t >/dev/null 2>&1 && ok "native $n 自校验通过" || bad "native $n 失败"
  $CBE run $t >/dev/null 2>&1 && ok "C 后端 $n 自校验通过" || bad "C 后端 $n 失败"
done

echo "[10] AArch64：struct 帧槽 frameaddr（模拟器执行级验证）"
for t in tests/t9.ros tests/t11.ros; do
  n=$(basename $t .ros)
  $NAT2 build $t -o build/${n}_a64 >/dev/null 2>&1
  timeout 600 python3 tests/a64_emu.py build/${n}_a64 > build/.a64.$n 2>/dev/null
  diff build/.x.$n build/.a64.$n >/dev/null 2>/dev/null \
    && ok "a64 $n 与 x86 输出全等" || bad "a64 $n 不一致"
done

echo "[11] v0.4：spawn/join 任务并行 + arena 帧级回收"
$NAT build tests/t13_spawn.ros -o build/nat_spawn >/dev/null 2>&1
out=$(./build/nat_spawn); rc=$?
[ $rc -eq 0 ] && ok "spawn 退出码 0" || bad "spawn 退出码 $rc"
[ "$out" = "$(printf '6765\n81\n110\nspawn ok')" ] && ok "spawn 结果正确（fib/square/void 任务）" || bad "spawn 输出 [$out]"
$CBE run tests/t13_spawn.ros 2>/dev/null | grep -v '^\[rosoto' > build/.spawn_c
[ "$out" = "$(cat build/.spawn_c)" ] && ok "spawn 自研后端 == C 后端" || bad "spawn 双后端不一致"

cp tests/t13_spawn.ros tests/single_core/
$NAT build tests/single_core/t13_spawn.ros -o build/nat_spawn_1c >/dev/null 2>&1
out1=$(./build/nat_spawn_1c); rc=$?
[ $rc -eq 0 ] && [ "$out1" = "$out" ] && ok "spawn 单核降级结果不变" || bad "spawn 单核降级 rc=$rc [$out1]"

$NAT build tests/arena_lowheap/arena.ros -o build/nat_arena >/dev/null 2>&1
out=$(./build/nat_arena); rc=$?
[ $rc -eq 0 ] && ok "arena：1MB 上限下 4MB 分配量跑完（回收生效）" || bad "arena rc=$rc [$out]"
[ "$out" = "$(printf 'arena ok\n200000')" ] && ok "arena 输出正确" || bad "arena 输出 [$out]"

$NAT build tests/arena_lowheap/no_arena.ros -o build/nat_noarena >/dev/null 2>&1
./build/nat_noarena >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "无 arena 时 1MB 堆上限 fail-fast" || bad "无 arena 竟然没有 OOM"

$NAT build tests/t15_chan.ros -o build/nat_chan >/dev/null 2>&1
out=$(timeout 120 ./build/nat_chan); rc=$?
[ $rc -eq 0 ] && ok "chan 退出码 0" || bad "chan 退出码 $rc"
[ "$out" = "$(printf '749500\nchan ok')" ] && ok "chan 多生产者 + FIFO 正确" || bad "chan 输出 [$out]"
$CBE run tests/t15_chan.ros 2>/dev/null | grep -v '^\[rosoto' > build/.chan_c
[ "$out" = "$(cat build/.chan_c)" ] && ok "chan 自研后端 == C 后端" || bad "chan 双后端不一致"

$NAT build tests/single_core/t15_chan_seq.ros -o build/nat_chan_seq >/dev/null 2>&1
out=$(timeout 60 ./build/nat_chan_seq); rc=$?
[ $rc -eq 0 ] && [ "$out" = "chan seq ok" ] && ok "chan 单核降级 FIFO 正确" || bad "chan 单核降级 rc=$rc [$out]"

echo "----------------------------------------"
echo "PASS=$PASS FAIL=$FAIL"
[ $FAIL -eq 0 ]
