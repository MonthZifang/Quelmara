#!/usr/bin/env bash
# =============================================================================
# Rosoto 核心运行时自测（mem / mt / store）
#   1. 发射三套运行时与自测程序（tools/rosoto_mem.py | rosoto_mt.py | rosoto_store.py）
#   2. gcc -fsyntax-only（默认标准 + -std=c99）
#   3. gcc -O2 -Wall -Wextra 编译
#   4. 运行自测：mem、mt 多核、mt 单核确定性（--multicore false）、store
#   5. 组合兼容：三套运行时拼接成单个编译单元（共享类型/符号自动去重）
#   6. CLI 负向用例（非法参数必须拒绝）
# 退出码 0 = 全部通过
# =============================================================================
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY=python3
WORK="$ROOT/build/corelib-test.$$"
mkdir -p "$WORK"

PASS=0; FAIL=0; SKIP=0
ok()   { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
skip() { echo "  [SKIP] $1"; SKIP=$((SKIP + 1)); }

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

command -v gcc >/dev/null 2>&1 || { echo "gcc 缺失，无法测试"; exit 1; }
command -v "$PY" >/dev/null 2>&1 || { echo "python3 缺失，无法测试"; exit 1; }

# -----------------------------------------------------------------------------
echo "== 1. 发射运行时（emit）与自测程序（selftest） =="
for mod in mem mt store; do
    if "$PY" "tools/rosoto_$mod.py" emit > "$WORK/$mod.rt.c" 2>"$WORK/$mod.emit.err"; then
        ok "rosoto_$mod.py emit"
    else
        fail "rosoto_$mod.py emit"; cat "$WORK/$mod.emit.err"
    fi
    if "$PY" "tools/rosoto_$mod.py" selftest > "$WORK/$mod.st.c" 2>"$WORK/$mod.st.err"; then
        ok "rosoto_$mod.py selftest"
    else
        fail "rosoto_$mod.py selftest"; cat "$WORK/$mod.st.err"
    fi
done

# -----------------------------------------------------------------------------
echo "== 2. 语法检查（gcc -fsyntax-only，含 -std=c99） =="
for f in "$WORK"/*.c; do
    b=$(basename "$f")
    if gcc -fsyntax-only "$f" 2>"$WORK/syn_$b.err"; then ok "syntax $b"; else fail "syntax $b"; cat "$WORK/syn_$b.err"; fi
    if gcc -std=c99 -fsyntax-only "$f" 2>>"$WORK/syn_$b.err"; then ok "syntax-c99 $b"; else fail "syntax-c99 $b"; cat "$WORK/syn_$b.err"; fi
done

# -----------------------------------------------------------------------------
echo "== 3. gcc -O2 -Wall -Wextra 编译 =="
if gcc -O2 -Wall -Wextra -o "$WORK/mem_st" "$WORK/mem.st.c" 2>"$WORK/cc_mem.log"; then
    ok "build mem selftest"
else
    fail "build mem selftest"; cat "$WORK/cc_mem.log"
fi
if gcc -O2 -Wall -Wextra -pthread -o "$WORK/mt_st" "$WORK/mt.st.c" 2>"$WORK/cc_mt.log"; then
    ok "build mt selftest"
else
    fail "build mt selftest"; cat "$WORK/cc_mt.log"
fi
if "$PY" tools/rosoto_mt.py selftest --multicore false > "$WORK/mt.single.c" 2>/dev/null &&
   gcc -O2 -Wall -Wextra -pthread -o "$WORK/mt_st_single" "$WORK/mt.single.c" 2>"$WORK/cc_mts.log"; then
    ok "build mt selftest（单核确定性模式）"
else
    fail "build mt selftest（单核确定性模式）"; cat "$WORK/cc_mts.log"
fi
if gcc -O2 -Wall -Wextra -o "$WORK/store_st" "$WORK/store.st.c" 2>"$WORK/cc_store.log"; then
    ok "build store selftest"
else
    fail "build store selftest"; cat "$WORK/cc_store.log"
fi

# -----------------------------------------------------------------------------
echo "== 4. 运行自测 =="
run_st() { # $1=bin $2=label $3=cwd（可选）
    local cwd="${3:-$WORK}"
    if (cd "$cwd" && timeout 120 stdbuf -oL "$1" > "$WORK/run_$(basename "$1").log" 2>&1); then
        ok "$2"
    else
        fail "$2（退出码 $?）"; tail -20 "$WORK/run_$(basename "$1").log"
    fi
}
run_st "$WORK/mem_st" "mem 自测（arena/slab/稳定引用/视图/大页/堆上限）"
run_st "$WORK/mt_st" "mt 自测（多核 work-stealing 默认开启）"
run_st "$WORK/mt_st_single" "mt 自测（单核确定性降级）"
run_st "$WORK/store_st" "store 自测（CRC/WAL/页存储/视图/异步 IO）" "$WORK"

# -----------------------------------------------------------------------------
echo "== 5. 组合兼容（mem+mt+store 拼接单编译单元，共享符号自动去重） =="
{
    cat "$WORK/mem.rt.c" "$WORK/mt.rt.c" "$WORK/store.rt.c"
    echo 'int main(void) { return 0; }'
} > "$WORK/combined.c"
if gcc -fsyntax-only "$WORK/combined.c" 2>"$WORK/combined.err"; then
    ok "组合编译单元语法通过（RosotoView/rosoto_now_ns 等共享定义去重）"
else
    fail "组合编译单元"; cat "$WORK/combined.err"
fi
if gcc -std=c99 -fsyntax-only "$WORK/combined.c" 2>>"$WORK/combined.err"; then
    ok "组合编译单元 -std=c99"
else
    fail "组合编译单元 -std=c99"; cat "$WORK/combined.err"
fi

# -----------------------------------------------------------------------------
echo "== 6. CLI 负向用例（非法参数必须拒绝） =="
neg() { # $1=label，其余为命令
    local label="$1"; shift
    if "$@" >/dev/null 2>&1; then
        fail "$label（非法输入未被拒绝）"
    else
        ok "$label"
    fi
}
neg "mem: 负数 heap-limit-mb 拒绝" "$PY" tools/rosoto_mem.py emit --heap-limit-mb -5
neg "mem: 非法 huge-pages 拒绝" "$PY" tools/rosoto_mem.py emit --huge-pages maybe
neg "mt: 非法 affinity 拒绝" "$PY" tools/rosoto_mt.py emit --affinity bogus
neg "mt: 越界 threads 拒绝" "$PY" tools/rosoto_mt.py emit --threads 99999999
neg "store: 非 2 的幂 page-size 拒绝" "$PY" tools/rosoto_store.py emit --page-size 3000
neg "store: 越界 wal-buf-kb 拒绝" "$PY" tools/rosoto_store.py emit --wal-buf-kb 1

# -----------------------------------------------------------------------------
echo
echo "结果: PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
[ "$FAIL" = 0 ] && exit 0 || exit 1
