#!/usr/bin/env bash
# Quelmara 性能基线对比：自研后端 vs gcc -O2
set -u
cd "$(dirname "$0")/.."
t() {
  local best=999999999
  for _ in 1 2 3; do
    local s e
    s=$(date +%s%N); "$@" >/dev/null; e=$(date +%s%N)
    local ms=$(( (e-s)/1000000 ))
    [ $ms -lt $best ] && best=$ms
  done
  echo "$best ms"
}

echo "== 编译 =="
python3 tools/stage0/qlm_native.py build examples/loop_sum.qma -o build/p_native_loop >/dev/null 2>&1
python3 tools/stage0/qlm.py build examples/loop_sum.qma --cc >/dev/null 2>&1 && mv build/loop_sum build/p_c_loop 2>/dev/null
python3 tools/stage0/qlm_native.py build examples/parfor_sum.qma -o build/p_native_par >/dev/null 2>&1
python3 tools/stage0/qlm.py build examples/parfor_sum.qma --cc >/dev/null 2>&1 && mv build/parfor_sum build/p_c_par 2>/dev/null

echo
echo "loop_sum  (2 亿热循环)"
echo -n "  自研后端   : "; t ./build/p_native_loop
echo -n "  gcc -O2    : "; t ./build/p_c_loop
echo
echo "parfor_sum (6M 任务)"
echo -n "  自研后端   : "; t ./build/p_native_par
echo -n "  gcc -O2    : "; t ./build/p_c_par
