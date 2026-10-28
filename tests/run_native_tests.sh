#!/usr/bin/env bash
# Quelmara 自研原生后端 v0.1 回归测试
# 覆盖：正确性(双后端交叉验证) / 多核 clone / 单核降级 / divmod 语义 / 退出码(退出崩溃回归) / 静态 ELF
set -u
cd "$(dirname "$0")/.."
PASS=0; FAIL=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

NAT=python3\ tools/stage0/qlm_native.py
NAT2=python3\ tools/stage0/qlm_arm64.py
CBE=python3\ tools/stage0/qlm.py

echo "[1] fib(25) 递归正确性 + 双后端交叉验证"
$NAT build examples/fib.qma -o build/nat_fib >/dev/null 2>&1
out=$(./build/nat_fib); rc=$?
[ $rc -eq 0 ] && ok "退出码 0（无退出崩溃）" || bad "退出码 $rc"
[ "$out" = "75025" ] && ok "fib(25)=75025" || bad "fib 输出 [$out]"

echo "[2] divmod 语义（正负/边界，160 行）双后端交叉验证"
$CBE build tests/divmod.qma --cc >/dev/null 2>&1; mv build/divmod build/c_divmod 2>/dev/null
./build/c_divmod > build/.dc 2>/dev/null
$NAT build tests/divmod.qma -o build/nat_divmod >/dev/null 2>&1
./build/nat_divmod > build/.dn; rc=$?
[ $rc -eq 0 ] && ok "退出码 0" || bad "退出码 $rc"
diff build/.dc build/.dn >/dev/null && ok "160 行全等（魔数除法 + idiv 回退语义一致）" || bad "divmod 输出不一致"

echo "[3] loop_sum 热循环（魔数优化路径）"
$NAT build examples/loop_sum.qma -o build/nat_loop >/dev/null 2>&1
out=$(./build/nat_loop); rc=$?
[ $rc -eq 0 ] && ok "退出码 0" || bad "退出码 $rc"
[ "$out" = "1199999988" ] && ok "结果 1199999988 与 C 后端一致" || bad "输出 [$out]"

echo "[4] parfor_sum 多核（raw clone + 共享内存归约）"
$NAT build examples/parfor_sum.qma -o build/nat_par >/dev/null 2>&1
out=$(./build/nat_par); rc=$?
[ $rc -eq 0 ] && ok "退出码 0" || bad "退出码 $rc"
[ "$out" = "11519999978" ] && ok "clone 多核归约 == pthread 后端结果" || bad "输出 [$out]"

echo "[5] 单核降级（tests/single_core/Quelmara.toml: multicore=false）"
cp examples/parfor_sum.qma tests/single_core/
$NAT build tests/single_core/parfor_sum.qma -o build/nat_par_1c >/dev/null 2>&1
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
for t in tests/t1.qma tests/dbg.qma; do
  n=$(basename $t .qma)
  $NAT2 build $t -o build/${n}_a64 >/dev/null 2>&1
  out=$(timeout 300 python3 tests/a64_emu.py build/${n}_a64 2>/dev/null)
  case $n in
    t1)  [ "$out" = "1" ]  && ok "a64 t1 => 1" || bad "a64 t1 [$out]";;
    dbg) [ "$out" = "18" ] && ok "a64 dbg => 18" || bad "a64 dbg [$out]";;
  esac
done
$NAT2 build examples/fib.qma -o build/fib_a64 >/dev/null 2>&1
out=$(timeout 600 python3 tests/a64_emu.py build/fib_a64 2>/dev/null)
[ "$out" = "75025" ] && ok "a64 fib(25) => 75025" || bad "a64 fib [$out]"
$NAT2 build tests/divmod.qma -o build/divmod_a64 >/dev/null 2>&1
timeout 600 python3 tests/a64_emu.py build/divmod_a64 > build/.dn64 2>/dev/null
diff build/.dc build/.dn64 >/dev/null && ok "a64 divmod 160 行与 x86/C 后端全等" || bad "a64 divmod 不一致"

# v1.86：atomic 内建在 A64 上走 LDAXR/STLXR（LL-SC 重试），
# 与 x86 的 lock xadd/cmpxchg 共用同一份用例（t97）。模拟器里独占监视器
# 恒成功，但状态字与重试分支是被真实执行过的。
$NAT2 build tests/t97_a64atomic.qma -o build/t97_a64 >/dev/null 2>&1
out=$(timeout 600 python3 tests/a64_emu.py build/t97_a64 2>/dev/null)
[ "$out" = "a64 atomic ok" ] && ok "a64 t97 atomic（LL-SC）=> a64 atomic ok" \
  || bad "a64 t97 atomic [$out]"
# v1.86：std/sync 在 A64 上也要能跑（解锁走 STLR、栈锁走 LDAR/STLR）
$NAT2 build tests/t122_syncport.qma -o build/t122_a64 >/dev/null 2>&1
out=$(timeout 600 python3 tests/a64_emu.py build/t122_a64 2>/dev/null)
[ "$out" = "sync port ok" ] && ok "a64 t122 std/sync => sync port ok" \
  || bad "a64 t122 std/sync [$out]"

echo "[8] 语言 v0.2：break/continue + struct（双后端交叉验证）"
for t in tests/t8.qma tests/t9.qma tests/t10.qma tests/t11.qma; do
  n=$(basename $t .qma)
  $NAT run $t 2>/dev/null | grep -v '^\[qlm' > build/.x.$n; rc=${PIPESTATUS[0]}
  $CBE run $t 2>/dev/null | grep -v '^\[qlm' > build/.y.$n
  [ $rc -eq 0 ] && ok "$n 退出码 0" || bad "$n 退出码 $rc"
  diff build/.x.$n build/.y.$n >/dev/null && ok "$n 双后端输出全等" || bad "$n 双后端不一致"
done

echo "[9] v0.2 新示例（游戏/算法/工程/多核，含 assert 自校验）"
for t in examples/game_loop.qma examples/collatz.qma examples/inventory.qma examples/prime_parallel.qma examples/traffic_light.qma; do
  n=$(basename $t .qma)
  $NAT run $t >/dev/null 2>&1 && ok "native $n 自校验通过" || bad "native $n 失败"
  $CBE run $t >/dev/null 2>&1 && ok "C 后端 $n 自校验通过" || bad "C 后端 $n 失败"
done

echo "[10] AArch64：struct 帧槽 frameaddr（模拟器执行级验证）"
for t in tests/t9.qma tests/t11.qma; do
  n=$(basename $t .qma)
  $NAT2 build $t -o build/${n}_a64 >/dev/null 2>&1
  timeout 600 python3 tests/a64_emu.py build/${n}_a64 > build/.a64.$n 2>/dev/null
  diff build/.x.$n build/.a64.$n >/dev/null 2>/dev/null \
    && ok "a64 $n 与 x86 输出全等" || bad "a64 $n 不一致"
done

echo "[11] v0.4：spawn/join 任务并行 + arena 帧级回收"
$NAT build tests/t13_spawn.qma -o build/nat_spawn >/dev/null 2>&1
out=$(./build/nat_spawn); rc=$?
[ $rc -eq 0 ] && ok "spawn 退出码 0" || bad "spawn 退出码 $rc"
[ "$out" = "$(printf '6765\n81\n110\nspawn ok')" ] && ok "spawn 结果正确（fib/square/void 任务）" || bad "spawn 输出 [$out]"
$CBE run tests/t13_spawn.qma 2>/dev/null | grep -v '^\[qlm' > build/.spawn_c
[ "$out" = "$(cat build/.spawn_c)" ] && ok "spawn 自研后端 == C 后端" || bad "spawn 双后端不一致"

cp tests/t13_spawn.qma tests/single_core/
$NAT build tests/single_core/t13_spawn.qma -o build/nat_spawn_1c >/dev/null 2>&1
out1=$(./build/nat_spawn_1c); rc=$?
[ $rc -eq 0 ] && [ "$out1" = "$out" ] && ok "spawn 单核降级结果不变" || bad "spawn 单核降级 rc=$rc [$out1]"

$NAT build tests/arena_lowheap/arena.qma -o build/nat_arena >/dev/null 2>&1
out=$(./build/nat_arena); rc=$?
[ $rc -eq 0 ] && ok "arena：1MB 上限下 4MB 分配量跑完（回收生效）" || bad "arena rc=$rc [$out]"
[ "$out" = "$(printf 'arena ok\n200000')" ] && ok "arena 输出正确" || bad "arena 输出 [$out]"

$NAT build tests/arena_lowheap/no_arena.qma -o build/nat_noarena >/dev/null 2>&1
./build/nat_noarena >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "无 arena 时 1MB 堆上限 fail-fast" || bad "无 arena 竟然没有 OOM"

$NAT build tests/t15_chan.qma -o build/nat_chan >/dev/null 2>&1
out=$(timeout 120 ./build/nat_chan); rc=$?
[ $rc -eq 0 ] && ok "chan 退出码 0" || bad "chan 退出码 $rc"
[ "$out" = "$(printf '749500\nchan ok')" ] && ok "chan 多生产者 + FIFO 正确" || bad "chan 输出 [$out]"
$CBE run tests/t15_chan.qma 2>/dev/null | grep -v '^\[qlm' > build/.chan_c
[ "$out" = "$(cat build/.chan_c)" ] && ok "chan 自研后端 == C 后端" || bad "chan 双后端不一致"

$NAT build tests/single_core/t15_chan_seq.qma -o build/nat_chan_seq >/dev/null 2>&1
out=$(timeout 60 ./build/nat_chan_seq); rc=$?
[ $rc -eq 0 ] && [ "$out" = "chan seq ok" ] && ok "chan 单核降级 FIFO 正确" || bad "chan 单核降级 rc=$rc [$out]"

$NAT build tests/t16_arrays.qma -o build/nat_arrays >/dev/null 2>&1
out=$(timeout 60 ./build/nat_arrays); rc=$?
[ $rc -eq 0 ] && ok "数组退出码 0" || bad "数组退出码 $rc"
[ "$out" = "$(printf '33\narrays ok')" ] && ok "数组：len/读写/复合赋值/值拷贝/循环求和正确" || bad "数组输出 [$out]"
$CBE run tests/t16_arrays.qma 2>/dev/null | grep -v '^\[qlm' > build/.arr_c
[ "$out" = "$(cat build/.arr_c)" ] && ok "数组自研后端 == C 后端" || bad "数组双后端不一致"

$NAT build tests/array_bounds.qma -o build/nat_ab >/dev/null 2>&1
timeout 30 ./build/nat_ab >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "数组越界 fail-fast（退出码非 0）" || bad "数组越界未失败"

echo "[12] Result 枚举错误传播（?）"
$NAT run tests/t17_result.qma >/dev/null 2>&1 && ok "native Result/ ? 传播正确" || bad "native Result/ ? 失败"
$CBE run tests/t17_result.qma >/dev/null 2>&1 && ok "C Result/ ? 传播正确" || bad "C Result/ ? 失败"

echo "[13] option[T] 单态化 + match 解构"
$NAT run tests/t19_option.qma >/dev/null 2>&1 && ok "native option 构造/match 正确" || bad "native option 失败"
$CBE run tests/t19_option.qma >/dev/null 2>&1 && ok "C option 构造/match 正确" || bad "C option 失败"

echo "[14] result[T,E] 单态化 + ? 传播 + match 解构"
$NAT run tests/t20_result_generic.qma >/dev/null 2>&1 && ok "native result[T,E] 构造/?/match 正确" || bad "native result[T,E] 失败"
$CBE run tests/t20_result_generic.qma >/dev/null 2>&1 && ok "C result[T,E] 构造/?/match 正确" || bad "C result[T,E] 失败"
$NAT run tests/t20_result_generic.qma 2>/dev/null | grep -v '^\[qlm' > build/.res20_n
$CBE run tests/t20_result_generic.qma 2>/dev/null | grep -v '^\[qlm' > build/.res20_c
diff build/.res20_n build/.res20_c >/dev/null && ok "result[T,E] 自研后端 == C 后端" || bad "result[T,E] 双后端不一致"

echo "[15] 切片 []T（{ptr,len} 两字零拷贝视图 + 聚合 ABI）"
$NAT run tests/t21_slice.qma >/dev/null 2>&1 && ok "native 切片 构造/索引/传参/返回正确" || bad "native 切片 失败"
$CBE run tests/t21_slice.qma >/dev/null 2>&1 && ok "C 切片 构造/索引/传参/返回正确" || bad "C 切片 失败"
$NAT run tests/t21_slice.qma 2>/dev/null | grep -v '^\[qlm' > build/.sli21_n
$CBE run tests/t21_slice.qma 2>/dev/null | grep -v '^\[qlm' > build/.sli21_c
diff build/.sli21_n build/.sli21_c >/dev/null && ok "切片 自研后端 == C 后端" || bad "切片 双后端不一致"
$NAT build tests/slice_bounds.qma -o build/nat_sb >/dev/null 2>&1
timeout 30 ./build/nat_sb >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "切片越界 fail-fast（动态长度检查）" || bad "切片越界未失败"

echo "[16] map[K]V（开放寻址 + 线性探测 + 墓碑 + 扩容）"
$NAT run tests/t22_map.qma >/dev/null 2>&1 && ok "native map set/get/has/del/扩容/墓碑正确" || bad "native map 失败"
$CBE run tests/t22_map.qma >/dev/null 2>&1 && ok "C map set/get/has/del/扩容/墓碑正确" || bad "C map 失败"
$NAT run tests/t22_map.qma 2>/dev/null | grep -v '^\[qlm' > build/.map22_n
$CBE run tests/t22_map.qma 2>/dev/null | grep -v '^\[qlm' > build/.map22_c
diff build/.map22_n build/.map22_c >/dev/null && ok "map 自研后端 == C 后端" || bad "map 双链不一致"
$NAT build tests/map_bounds.qma -o build/nat_mb >/dev/null 2>&1
timeout 30 ./build/nat_mb >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "map get 缺失键 fail-fast（退出码非 0）" || bad "map get 缺失键未失败"
$CBE build tests/map_bounds.qma --cc >/dev/null 2>&1; mv build/map_bounds build/c_mb 2>/dev/null
timeout 30 ./build/c_mb >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "C 侧 map get 缺失键 fail-fast" || bad "C 侧 map get 缺失键未失败"

echo "[17] 浮点 f64/f32（运算/比较/转换/格式化，双链一致）"
$NAT run tests/t23_float.qma >/dev/null 2>&1 && ok "native 浮点 运算/比较/转换/格式化正确" || bad "native 浮点 失败"
$CBE run tests/t23_float.qma >/dev/null 2>&1 && ok "C 浮点 运算/比较/转换/格式化正确" || bad "C 浮点 失败"
$NAT run tests/t23_float.qma 2>/dev/null | grep -v '^\[qlm' > build/.flt23_n
$CBE run tests/t23_float.qma 2>/dev/null | grep -v '^\[qlm' > build/.flt23_c
diff build/.flt23_n build/.flt23_c >/dev/null && ok "浮点 自研后端 == C 后端" || bad "浮点 双链不一致"

echo "[18] h.join() 方法式语法（脱糖为内置 join）"
$NAT run tests/t24_join_method.qma >/dev/null 2>&1 && ok "native h.join() 方法式 join 正确" || bad "native h.join() 失败"
$CBE run tests/t24_join_method.qma >/dev/null 2>&1 && ok "C h.join() 方法式 join 正确" || bad "C h.join() 失败"
$NAT run tests/t24_join_method.qma 2>/dev/null | grep -v '^\[qlm' > build/.jm24_n
$CBE run tests/t24_join_method.qma 2>/dev/null | grep -v '^\[qlm' > build/.jm24_c
diff build/.jm24_n build/.jm24_c >/dev/null && ok "join 方法式 自研后端 == C 后端" || bad "join 方法式 双链不一致"

echo "[19] chan.close()（v0.11）：排空/零值/fail-fast，双链一致"
$NAT run tests/t25_chan_close.qma >/dev/null 2>&1 && ok "native chan close 排空/零值正确" || bad "native chan close 失败"
$CBE run tests/t25_chan_close.qma >/dev/null 2>&1 && ok "C chan close 排空/零值正确" || bad "C chan close 失败"
$NAT run tests/t25_chan_close.qma 2>/dev/null | grep -v '^\[qlm' > build/.cc25_n
$CBE run tests/t25_chan_close.qma 2>/dev/null | grep -v '^\[qlm' > build/.cc25_c
diff build/.cc25_n build/.cc25_c >/dev/null && ok "chan close 自研后端 == C 后端" || bad "chan close 双链不一致"
$NAT build tests/chan_close_fail.qma -o build/nat_ccf >/dev/null 2>&1
timeout 30 ./build/nat_ccf >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "close 后 send fail-fast（退出码非 0）" || bad "close 后 send 未失败"
$NAT build tests/chan_double_close.qma -o build/nat_cdc >/dev/null 2>&1
timeout 30 ./build/nat_cdc >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "重复 close fail-fast（退出码非 0）" || bad "重复 close 未失败"
$CBE build tests/chan_close_fail.qma --cc >/dev/null 2>&1; mv build/chan_close_fail build/c_ccf 2>/dev/null
timeout 30 ./build/c_ccf >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "C 侧 close 后 send fail-fast" || bad "C 侧 close 后 send 未失败"
$CBE build tests/chan_double_close.qma --cc >/dev/null 2>&1; mv build/chan_double_close build/c_cdc 2>/dev/null
timeout 30 ./build/c_cdc >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "C 侧重复 close fail-fast" || bad "C 侧重复 close 未失败"

echo "[20] chan select（v0.11）：轮询/yield、声明序优先、全关闭返回 0"
$NAT run tests/t26_select.qma >/dev/null 2>&1 && ok "native select 各场景正确" || bad "native select 失败"
$CBE run tests/t26_select.qma >/dev/null 2>&1 && ok "C select 各场景正确" || bad "C select 失败"
$NAT run tests/t26_select.qma 2>/dev/null | grep -v '^\[qlm' > build/.sel26_n
$CBE run tests/t26_select.qma 2>/dev/null | grep -v '^\[qlm' > build/.sel26_c
diff build/.sel26_n build/.sel26_c >/dev/null && ok "select 自研后端 == C 后端" || bad "select 双链不一致"

echo "[21] str 长度/字节下标/十进制解析（v0.12）：双链一致"
$NAT run tests/t27_str.qma >/dev/null 2>&1 && ok "native str len/下标正确" || bad "native str len/下标 失败"
$CBE run tests/t27_str.qma >/dev/null 2>&1 && ok "C str len/下标正确" || bad "C str len/下标 失败"
$NAT run tests/t28_toint.qma >/dev/null 2>&1 && ok "native str.to_int 正确（含边界/往返）" || bad "native str.to_int 失败"
$CBE run tests/t28_toint.qma >/dev/null 2>&1 && ok "C str.to_int 正确（含边界/往返）" || bad "C str.to_int 失败"
$NAT run tests/t27_str.qma 2>/dev/null | grep -v '^\[qlm' > build/.str27_n
$CBE run tests/t27_str.qma 2>/dev/null | grep -v '^\[qlm' > build/.str27_c
diff build/.str27_n build/.str27_c >/dev/null && ok "str 自研后端 == C 后端" || bad "str 双链不一致"
$NAT run tests/t28_toint.qma 2>/dev/null | grep -v '^\[qlm' > build/.tint28_n
$CBE run tests/t28_toint.qma 2>/dev/null | grep -v '^\[qlm' > build/.tint28_c
diff build/.tint28_n build/.tint28_c >/dev/null && ok "to_int 自研后端 == C 后端" || bad "to_int 双链不一致"
$NAT build tests/str_bounds.qma -o build/nat_sb >/dev/null 2>&1
timeout 30 ./build/nat_sb >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "str 越界 fail-fast（退出码非 0）" || bad "str 越界未失败"
$CBE build tests/str_bounds.qma --cc >/dev/null 2>&1; mv build/str_bounds build/c_sb 2>/dev/null
timeout 30 ./build/c_sb >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "C 侧 str 越界 fail-fast" || bad "C 侧 str 越界未失败"

# AArch64 发射层：同一份夹具走自研模拟器，验证 load8/neg/jcc 这几个新用到的指令
for t in tests/t27_str.qma tests/t28_toint.qma; do
  n=$(basename $t .qma)
  $NAT2 build $t -o build/${n}_a64 >/dev/null 2>&1 \
    && ok "a64 $n 编译通过" || bad "a64 $n 编译失败"
  timeout 600 python3 tests/a64_emu.py build/${n}_a64 > build/.a64str.$n 2>/dev/null
  $NAT run $t 2>/dev/null | grep -v '^\[qlm' > build/.natstr.$n
  diff build/.natstr.$n build/.a64str.$n >/dev/null \
    && ok "a64 $n 与 x86 输出全等" || bad "a64 $n 与 x86 不一致"
done
$NAT2 build tests/str_bounds.qma -o build/sb_a64 >/dev/null 2>&1
timeout 120 python3 tests/a64_emu.py build/sb_a64 >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && ok "a64 str 越界 fail-fast" || bad "a64 str 越界未失败"

echo "[22] @extern(\"C\")：自研后端必须明确拒绝（不静默产出坏二进制）"
if $NAT build tests/extern_decl.qma -o build/nat_ext 2>build/.ext_err; then
  bad "@extern 在自研后端竟然编译通过"
else
  grep -q '@extern' build/.ext_err && ok "@extern 自研后端给出明确诊断" \
      || bad "@extern 诊断内容不符：$(head -1 build/.ext_err)"
fi

echo "[23] args() 在自研后端（Linux/AArch64 入口口径，v2.90）"
# v2.89 及以前这条**只在 Windows 上被覆盖**（run_win_tests.py 带三个参数跑
# t29_args.qma），Linux/AArch64 的 lower_args 走的是另一条路径，于是
# "双重偏移"这个 bug 活了整整一年：args() 少一个参数、args()[0] 越界读。
# 下面三条把 Linux 侧口径钉死：个数 / 顺序 / 首元素，以及零参数不静默。
$NAT build tests/t29_args.qma -o build/nat_args >/dev/null 2>&1
out=$(./build/nat_args alpha beta "two words" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "args 退出码 0（无越界 SIGSEGV）" || bad "args 退出码 $rc"
[ "$out" = "$(printf '3\nalpha\nbeta\ntwo words\nalpha')" ] \
  && ok "args 个数/顺序/首元素正确（3 个参数，不含程序名）" || bad "args 输出 [$out]"
# 零参数：夹具里 assert(len(a)==3) 必须失败，且 arg(0) 越界 fail-fast 而不是读到垃圾
timeout 30 ./build/nat_args 2>/dev/null >/dev/null; rc=$?
[ $rc -ne 0 ] && ok "args 零参数 fail-fast（不静默返回垃圾）" || bad "args 零参数未失败"

echo "[24] POSIX 原生 socket（v2.92）：listen/accept/send/recv/connect 全链路"
# v2.91 及以前 `tcp_connect` 的**派发**里有一句无条件的 windows 检查，
# Linux 上一编 `import std.net` 就死在 "无法发射指令 ('winapi', … 'WSAStartup')"；
# 运行库那边 `__tcp_connect` 之前还用 `return` 提前退出了整个运行库生成。
# 下面把服务端（listen/accept）与客户端（connect）都跑一遍真连接。
$NAT build tests/net_echo_linux.qma -o build/net_echo_linux >/dev/null 2>&1 \
  && ok "POSIX 网络：echo 服务端编译通过" || bad "POSIX 网络：echo 服务端编译失败"
if [ -x build/net_echo_linux ]; then
  (./build/net_echo_linux > build/.netecho.out 2>&1 &)
  sleep 0.6
  python3 - <<'PYEOF'
import socket, sys, threading
res = []
def cli(i):
    try:
        s = socket.create_connection(("127.0.0.1", 19559), timeout=3)
        m = f"posix-{i}\n".encode()
        s.sendall(m)
        d = s.recv(64)
        res.append(d == m)
        s.close()
    except Exception:
        res.append(False)
ts = [threading.Thread(target=cli, args=(i,)) for i in range(3)]
[t.start() for t in ts]
[t.join() for t in ts]
sys.exit(0 if len(res) == 3 and all(res) else 1)
PYEOF
  [ $? -eq 0 ] && ok "POSIX 网络：3 连接 echo 全部正确（raw syscall）" \
               || bad "POSIX 网络：echo 回显失败"
  pkill -f net_echo_linux 2>/dev/null
fi

$NAT build tests/net_connect_linux.qma -o build/net_connect_linux >/dev/null 2>&1 \
  && ok "POSIX 网络：客户端编译通过" || bad "POSIX 网络：客户端编译失败"
if [ -x build/net_connect_linux ]; then
  python3 - >/dev/null 2>&1 <<'PYEOF' &
import socket
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 19560)); s.listen(1)
c, _ = s.accept()
d = c.recv(64)
c.sendall(b"pong:" + d)
c.close(); s.close()
PYEOF
  SRVPID=$!
  sleep 0.7
  out=$(timeout 30 ./build/net_connect_linux 2>&1); rc=$?
  wait $SRVPID 2>/dev/null
  [ $rc -eq 0 ] && ok "POSIX 网络：connect 退出码 0" || bad "POSIX 网络：connect rc=$rc"
  echo "$out" | grep -q "pong:ping-from-quelmara" \
    && ok "POSIX 网络：connect 收发明文正确" || bad "POSIX 网络：connect 输出 [$out]"
fi

echo "----------------------------------------"
echo "PASS=$PASS FAIL=$FAIL"
[ $FAIL -eq 0 ]
