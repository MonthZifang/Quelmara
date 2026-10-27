#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara Windows PE/COFF 后端回归（自研，无 CRT）
================================================
在 Windows 上直接执行 .exe；在非 Windows 上只做结构/构建检查并跳过执行。

覆盖：
  [1] PE 结构：MZ/PE32+/AMD64/console、导入仅 kernel32、无 CRT 符号、体积
  [2] 基础语义：hello / fib / loop_sum / 大整数打印 / UTF-8 中文
  [3] 语言 v0.2：t8 break/continue、t9 struct、t11 嵌套、t12 enum+match
  [4] 多核：parfor_sum / prime_parallel / game_loop / t10（CreateThread 归约）
  [5] 单核降级：Quelmara.toml multicore=false（同结果）
  [6] 失败路径：assert 退出码 1 + stderr 消息
  [7] 交叉验证：与 Linux 自研 ELF 后端输出逐字节比对（需要 WSL；无则 SKIP）
  [8] 调试链路：DWARF 互操作 / 调试器端到端 / 行覆盖率（仅 Windows）
  [9] AArch64 接口 vtable：ELF 构建 + 模拟器执行（跨平台，7 个接口用例）
"""

import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm_pe  # noqa: E402

PASS = FAIL = SKIP = 0
IS_WIN = os.name == "nt"


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def skip(msg):
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {msg}")


def build(src, out):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    blob, cfg = qlm_pe.transpile_win(src)
    qlm_pe.write_exe(out, blob)
    return blob, cfg


def run(exe, timeout=120, args=None):
    if not IS_WIN:
        return None
    p = subprocess.run([exe] + list(args or []), capture_output=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def pe_info(path):
    p = open(path, "rb").read()
    pe = struct.unpack_from("<I", p, 0x3C)[0]
    machine, nsec, _ts, _ps, _ns, optsz, _ch = struct.unpack_from("<HHIIIHH", p, pe + 4)
    opt = pe + 24
    magic = struct.unpack_from("<H", p, opt)[0]
    entry = struct.unpack_from("<I", p, opt + 16)[0]
    subsystem = struct.unpack_from("<H", p, opt + 68)[0]
    sh = opt + optsz
    secs = []
    for i in range(nsec):
        name, vs, va, rs, rp = struct.unpack_from("<8sIIII", p, sh + 40 * i)
        secs.append((name.rstrip(b"\x00").decode(), va, vs, rp, rs))
    return p, pe, machine, nsec, magic, entry, subsystem, secs


def rva2off(secs, rva):
    for _n, va, vs, rp, rs in secs:
        if va <= rva < va + max(vs, rs):
            return rp + (rva - va)
    return None


# ---------------------------------------------------------------------------
# [1] PE 结构
# ---------------------------------------------------------------------------


def test_pe_structure(out):
    p, _pe, machine, nsec, magic, entry, subsystem, secs = pe_info(out)
    ok(f"DOS/PE 头有效，{nsec} 个节，{len(p)} 字节") if p[:2] == b"MZ" else bad("MZ 头缺失")
    ok("machine=AMD64") if machine == 0x8664 else bad(f"machine={machine:#x}")
    ok("PE32+ (0x20b)") if magic == 0x20B else bad(f"magic={magic:#x}")
    ok("subsystem=console(3)") if subsystem == 3 else bad(f"subsystem={subsystem}")
    ok(f"入口 RVA 0x{entry:x} 落在 .text") if any(
        n == ".text" and va <= entry < va + max(vs, rs)
        for n, va, vs, _rp, rs in secs) \
        else bad(f"入口 RVA 0x{entry:x} 不在 .text")
    ok(f"体积 {len(p)}B < 128KB（无 CRT，省用）") if len(p) < 128 * 1024 else bad(f"体积 {len(p)}B 偏大")

    # 导入表：只允许 kernel32.dll；不得出现 CRT 符号
    imp_rva, imp_size = struct.unpack_from("<II", p, _pe + 24 + 112 + 8)
    off = rva2off(secs, imp_rva)
    if off is None:
        bad("找不到导入表")
        return
    names = []
    dll = b""

    def cstr(rva):
        o = rva2off(secs, rva)
        e = p.index(b"\x00", o)
        return p[o:e]

    cur = off
    while True:
        ilt, _ts, _fc, name, iat = struct.unpack_from("<IIIII", p, cur)
        if name == 0:
            break
        dll = cstr(name)
        e = rva2off(secs, ilt if ilt else iat)
        j = 0
        while True:
            v = struct.unpack_from("<Q", p, e + 8 * j)[0]
            if v == 0:
                break
            names.append(cstr(v + 2).decode("ascii"))
            j += 1
        cur += 20
    ok(f"导入 DLL = {dll.decode()}") if dll == b"kernel32.dll" else bad(f"导入 DLL 非 kernel32: {dll!r}")
    ok(f"导入 API {len(names)} 个，全部 kernel32: {', '.join(names)}") if all(
        n in {"GetStdHandle", "WriteFile", "ExitProcess", "VirtualAlloc",
              "CreateThread", "WaitForSingleObject", "CloseHandle", "SwitchToThread"}
        for n in names) \
        else bad(f"出现非预期导入: {names}")
    crt = [n for n in names if n.lower() in ("printf", "malloc", "exit", "memcpy", "puts")]
    ok("无 CRT 依赖（无 printf/malloc/exit）") if not crt else bad(f"CRT 依赖: {crt}")


# ---------------------------------------------------------------------------
# [2]-[6]
# ---------------------------------------------------------------------------


def case_output(name, src, expect_lines=None, expect_last=None):
    out = os.path.join(ROOT, "build", f"win_{name}.exe")
    build(os.path.join(ROOT, src), out)
    r = run(out, timeout=300)
    if r is None:
        skip(f"{name}: 非 Windows 平台，跳过执行")
        return
    rc, stdout, stderr = r
    text = stdout.decode("utf-8", "replace")
    ok(f"{name} 退出码 0") if rc == 0 else bad(f"{name} 退出码 {rc} stderr={stderr[:120]!r}")
    if expect_lines is not None:
        ok(f"{name} 输出 {len(expect_lines)} 行全等") if text.splitlines() == expect_lines \
            else bad(f"{name} 输出不符: {text.splitlines()!r}")
    if expect_last is not None:
        ok(f"{name} 末行 = {expect_last}") if text.strip().splitlines()[-1:] == [expect_last] \
            else bad(f"{name} 末行不符: {text.strip().splitlines()[-1:]!r}")


def case_selfcheck(name, src):
    out = os.path.join(ROOT, "build", f"win_{name}.exe")
    build(os.path.join(ROOT, src), out)
    r = run(out, timeout=600)
    if r is None:
        skip(f"{name}: 非 Windows 平台，跳过执行")
        return
    rc, stdout, stderr = r
    ok(f"{name} 自校验通过（assert 全过）") if rc == 0 \
        else bad(f"{name} 失败 rc={rc} stderr={stderr[-200:]!r}")


def test_log_streams():
    """std/log 的通道分流：stdout 只有 out-line*，stderr 只有 err-line。"""
    out = os.path.join(ROOT, "build", "win_log_streams.exe")
    build(os.path.join(ROOT, "tests/log_streams.qma"), out)
    r = run(out, timeout=120)
    if r is None:
        skip("log_streams: 非 Windows 平台，跳过执行")
        return
    rc, stdout, stderr = r
    so = stdout.decode("utf-8", "replace")
    se = stderr.decode("utf-8", "replace")
    ok("log_streams 退出码 0") if rc == 0 else bad(f"log_streams 退出码 {rc}")
    ok("log_streams：stdout 收到 info 行") if "out-line" in so and "out-line-2" in so \
        else bad(f"log_streams：stdout 缺 info 行 {so!r}")
    ok("log_streams：stderr 收到 warn 行") if "err-line" in se \
        else bad(f"log_streams：stderr 缺 warn 行 {se!r}")
    ok("log_streams：两路不串") if "err-line" not in so and "out-line" not in se \
        else bad(f"log_streams：串流了 stdout={so!r} stderr={se!r}")


def test_single_core():
    tmp = tempfile.mkdtemp(prefix="qlm_win_1c_")
    try:
        with open(os.path.join(tmp, "Quelmara.toml"), "w", encoding="utf-8") as f:
            f.write("[core]\nmulticore = false\nthreads = 1\n")
        shutil.copy(os.path.join(ROOT, "examples/parfor_sum.qma"), tmp)
        src = os.path.join(tmp, "parfor_sum.qma")
        out = os.path.join(ROOT, "build", "win_parfor_sum_1c.exe")
        blob, cfg = qlm_pe.transpile_win(src)
        qlm_pe.write_exe(out, blob)
        ok("单核配置被读取（multicore=False）") if cfg["core"]["multicore"] is False \
            else bad(f"配置未生效: {cfg['core']}")
        r = run(out)
        if r is None:
            skip("单核降级：非 Windows 平台，跳过执行")
        else:
            rc, stdout, stderr = r
            ok("单核降级结果不变") if rc == 0 and stdout.strip() == b"11519999978" \
                else bad(f"单核降级错误 rc={rc} out={stdout[:80]!r}")

        # spawn 在单核配置下必须退化为同步执行，结果不变
        shutil.copy(os.path.join(ROOT, "tests/t13_spawn.qma"), tmp)
        src2 = os.path.join(tmp, "t13_spawn.qma")
        out2 = os.path.join(ROOT, "build", "win_spawn_1c.exe")
        build(src2, out2)
        r = run(out2)
        if r is not None:
            rc, stdout, _ = r
            ok("spawn 单核降级结果不变") if rc == 0 and \
                stdout == b"6765\n81\n110\nspawn ok\n" \
                else bad(f"spawn 单核降级错误 rc={rc} out={stdout[:80]!r}")

        # chan 在单核配置下不跨线程，FIFO 语义必须保持
        shutil.copy(os.path.join(ROOT, "tests/single_core/t15_chan_seq.qma"), tmp)
        out3 = os.path.join(ROOT, "build", "win_chan_seq.exe")
        build(os.path.join(tmp, "t15_chan_seq.qma"), out3)
        r = run(out3)
        if r is not None:
            rc, stdout, _ = r
            ok("chan 单核降级 FIFO 正确") if rc == 0 and stdout == b"chan seq ok\n" \
                else bad(f"chan 单核降级错误 rc={rc} out={stdout[:80]!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_array_bounds():
    """越界必须 fail-fast（stderr + 非 0 退出码），不能静默读到相邻内存。"""
    out = os.path.join(ROOT, "build", "win_array_bounds.exe")
    build(os.path.join(ROOT, "tests/array_bounds.qma"), out)
    r = run(out)
    if r is None:
        skip("数组越界：非 Windows 平台")
        return
    rc, _stdout, stderr = r
    ok("数组越界 fail-fast（退出码非 0）") if rc != 0 else bad(f"数组越界未失败 rc={rc}")
    ok("数组越界消息写入 stderr") if b"index out of bounds" in stderr \
        else bad(f"stderr={stderr[:120]!r}")


def test_arena():
    """arena 必须真的回卷 bump 指针：1MB 上限下完成 ~4MB 分配量。"""
    out = os.path.join(ROOT, "build", "win_arena.exe")
    build(os.path.join(ROOT, "tests/arena_lowheap/arena.qma"), out)
    r = run(out, timeout=300)
    if r is None:
        skip("arena：非 Windows 平台，跳过执行")
        return
    rc, stdout, stderr = r
    ok("arena：1MB 上限下 4MB 分配量跑完（回收生效）") if rc == 0 \
        else bad(f"arena rc={rc} stderr={stderr[-160:]!r}")
    ok("arena 输出正确") if stdout == b"arena ok\n200000\n" \
        else bad(f"arena 输出 {stdout!r}")

    out2 = os.path.join(ROOT, "build", "win_no_arena.exe")
    build(os.path.join(ROOT, "tests/arena_lowheap/no_arena.qma"), out2)
    r = run(out2, timeout=300)
    rc, _stdout, stderr = r
    ok("无 arena 时 1MB 堆上限 fail-fast") if rc != 0 and b"heap_limit_mb" in stderr \
        else bad(f"无 arena 未 OOM rc={rc} stderr={stderr[:120]!r}")


def test_iface_rc():
    """接口装箱引用计数：1MB 上限下跑 20 万轮 × 3 次装箱（≥19MB 装箱量）。
    装箱不释放时会在中途 fail-fast；能跑完即证明 __iface_release 生效。"""
    out = os.path.join(ROOT, "build", "win_iface_rc.exe")
    build(os.path.join(ROOT, "tests/iface_lowheap/iface_rc.qma"), out)
    r = run(out, timeout=300)
    if r is None:
        skip("iface_rc：非 Windows 平台，跳过执行")
        return
    rc, stdout, stderr = r
    ok("iface_rc：1MB 上限下 19MB 装箱量跑完（引用计数回收）") if rc == 0 \
        else bad(f"iface_rc rc={rc} stderr={stderr[-160:]!r}")
    ok("iface_rc 输出正确") if stdout == b"iface rc ok\n" \
        else bad(f"iface_rc 输出 {stdout!r}")


def test_qlmc():
    """stage-1 编译器（`bootstrap/qlmc/qlmc.qma`）：与 stage-0 逐字节差分（v2.14）

    同一份源码分别用两个编译器编，比较 stdout 与退出码。覆盖子集 S1 的三组用例。
    """
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests/qlmc_test.py")],
                       capture_output=True, text=True, cwd=ROOT)
    tail = [ln for ln in (r.stdout or "").splitlines() if ln.startswith("PASS=")]
    if r.returncode == 0 and tail:
        ok(f"stage-1 编译器 qlmc 差分：{tail[-1]}")
    else:
        bad(f"qlmc 差分失败：{(r.stdout or '')[-500:]}{(r.stderr or '')[-300:]}")


def test_exitcode():
    """exit(运行期值) 的退出码必须真的传出去（v2.13）

    此前 emit_exit 把裸 int 当立即数，而 vreg 也是 int——`exit(变量)` 传的是
    vreg 号，于是 `let c = 3; exit(c)` 静默退 0。内部调用点（assert/越界）
    都传字面量 1，所以这条路径一直没被测到。
    """
    out = os.path.join(ROOT, "build", "win_exitcode.exe")
    build(os.path.join(ROOT, "tests/t142_exitcode.qma"), out)
    r = run(out)
    if r is None:
        skip("exit 退出码：非 Windows 平台，跳过执行")
        return
    rc, stdout, _ = r
    ok("exit(运行期值) 传播退出码 42") if rc == 42 \
        else bad(f"exit 退出码 {rc}（期望 42）")
    ok("exit 之前的输出已刷出") if stdout == b"before exit\n" \
        else bad(f"exit 输出 {stdout!r}")
    ok("exit 之后的语句不执行") if b"not reached" not in stdout \
        else bad("exit 之后仍在执行")


def test_assert_fail():
    out = os.path.join(ROOT, "build", "win_assert.exe")
    build(os.path.join(ROOT, "tests/win_assert.qma"), out)
    r = run(out)
    if r is None:
        skip("assert 失败路径：非 Windows 平台")
        return
    rc, stdout, stderr = r
    ok("assert 失败退出码 1") if rc == 1 else bad(f"assert 退出码 {rc}")
    ok("assert 消息写入 stderr") if b"expected fail" in stderr else bad(f"stderr={stderr!r}")
    ok("assert 前输出已刷出") if b"before assert" in stdout else bad(f"stdout={stdout!r}")
    ok("assert 后语句不执行") if b"unreachable" not in stdout else bad("assert 后仍继续执行")


def test_cross_verify():
    """与 Linux 自研 ELF 后端逐字节比对（通过 WSL；不可用则 SKIP）"""
    if not IS_WIN:
        skip("交叉验证：需要 Windows + WSL")
        return
    try:
        probe = subprocess.run(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "bash", "-lc",
                                "python3 --version"], capture_output=True)
    except OSError as _e:                    # wsl.exe 被策略/环境禁止启动
        skip(f"交叉验证：WSL 不可用（{_e.__class__.__name__}）")
        return
    if probe.returncode != 0:
        skip("交叉验证：WSL 不可用")
        return
    cases = ["tests/divmod.qma", "tests/t8.qma", "tests/t9.qma", "tests/t11.qma",
             "tests/t12.qma", "examples/inventory.qma", "examples/collatz.qma",
             "examples/game_loop.qma", "tests/t19_option.qma",
             "tests/t20_result_generic.qma", "tests/t21_slice.qma",
             "tests/t22_map.qma", "tests/t23_float.qma",
             "tests/t24_join_method.qma", "tests/t25_chan_close.qma",
             "tests/t26_select.qma", "tests/t27_str.qma",
             "tests/t28_toint.qma"]
    # 注意：hello 的 cores() 是编译期常量（Windows=物理核，WSL=4），不参与逐字节比对。
    drive = ROOT[0].lower()
    wsl_root = f"/mnt/{drive}/" + ROOT[3:].replace("\\", "/")
    for src in cases:
        name = os.path.splitext(os.path.basename(src))[0]
        out = os.path.join(ROOT, "build", f"win_{name}.exe")
        build(os.path.join(ROOT, src), out)
        win = run(out, timeout=300)
        cmd = (f"cd {wsl_root!r} && "
               f"python3 tools/stage0/qlm_native.py run {src} 2>/dev/null | grep -v '^\\[qlm'")
        nat = subprocess.run(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "bash", "-lc", cmd],
                             capture_output=True)
        if win is None or nat.returncode != 0:
            bad(f"{name} 交叉验证执行失败")
            continue
        ok(f"{name} PE 与 Linux ELF 输出逐字节一致") if win[1] == nat.stdout \
            else bad(f"{name} 输出不一致\n    win={win[1][:120]!r}\n    elf={nat.stdout[:120]!r}")


def test_chan_close_fail():
    """close 后 send / 重复 close 必须 fail-fast（stderr + 非 0 退出码）。"""
    for name, src, needle in (
            ("chan_close_fail", "tests/chan_close_fail.qma", "send on closed channel"),
            ("chan_double_close", "tests/chan_double_close.qma", "double close")):
        out = os.path.join(ROOT, "build", f"win_{name}.exe")
        build(os.path.join(ROOT, src), out)
        r = run(out)
        if r is None:
            skip(f"{name}：非 Windows 平台")
            continue
        rc, _stdout, stderr = r
        ok(f"{name} fail-fast（退出码非 0）") if rc != 0 else bad(f"{name} 未失败 rc={rc}")
        ok(f"{name} 消息写入 stderr") if needle.encode() in stderr \
            else bad(f"stderr={stderr[:120]!r}")


def test_str_failfast():
    """str 下标越界、非法十进制解析、@extern 声明都必须给出明确失败/诊断。"""
    out = os.path.join(ROOT, "build", "win_str_bounds.exe")
    build(os.path.join(ROOT, "tests/str_bounds.qma"), out)
    r = run(out)
    if r is None:
        skip("str 越界：非 Windows 平台")
    else:
        rc, _stdout, stderr = r
        ok("str 越界 fail-fast（退出码非 0）") if rc != 0 else bad(f"str 越界未失败 rc={rc}")
        ok("str 越界消息写入 stderr") if b"out of bounds" in stderr \
            else bad(f"stderr={stderr[:120]!r}")

    # 非法十进制：每种输入都必须退出码非 0，不能静默给出 0
    for i, lit in enumerate(("abc", "", "12x", " 12", "9223372036854775808")):
        src = os.path.join(ROOT, "build", f"win_badint_{i}.qma")
        with open(src, "w", encoding="utf-8") as f:
            f.write('fn main() {\n    print("%s".to_int())\n}\n' % lit)
        exe = os.path.join(ROOT, "build", f"win_badint_{i}.exe")
        build(src, exe)
        r = run(exe)
        if r is None:
            skip(f"to_int 非法输入 {lit!r}：非 Windows 平台")
            continue
        rc, _stdout, stderr = r
        ok(f"to_int({lit!r}) fail-fast") if rc != 0 \
            else bad(f"to_int({lit!r}) 未失败 rc={rc}")
        ok(f"to_int({lit!r}) 消息写入 stderr") if b"invalid decimal" in stderr \
            else bad(f"stderr={stderr[:120]!r}")

    # @extern("C")：自研后端不解析外部符号，必须给出人话诊断而不是 Python traceback
    src = os.path.join(ROOT, "build", "win_extern.qma")
    with open(src, "w", encoding="utf-8") as f:
        f.write('@extern("C")\nfn strlen2(s: str) -> int\n\n'
                'fn main() {\n    print("x")\n}\n')
    try:
        build(src, os.path.join(ROOT, "build", "win_extern.exe"))
    except SyntaxError as e:
        ok("@extern 在自研后端给出明确诊断") if "@extern" in str(e) \
            else bad(f"@extern 诊断内容不符：{e}")
    except Exception as e:                                   # noqa: BLE001
        bad(f"@extern 抛了非 SyntaxError：{type(e).__name__}: {e}")
    else:
        bad("@extern 在自研后端竟然编译成功（不链接外部符号不该成功）")


def import_table(path):
    """PE 导入表 -> {dll: [符号]}（v1.87 起可能多 DLL，@ffi 带显式 DLL 名）"""
    p, _pe, _m, _ns, _mg, _e, _s, secs = pe_info(path)
    imp_rva, _sz = struct.unpack_from("<II", p, _pe + 24 + 112 + 8)
    off = rva2off(secs, imp_rva)
    out = {}
    if off is None:
        return out

    def cstr(rva):
        o = rva2off(secs, rva)
        e = p.index(b"\x00", o)
        return p[o:e]

    cur = off
    while True:
        ilt, _ts, _fc, name, iat = struct.unpack_from("<IIIII", p, cur)
        if name == 0:
            break
        dll = cstr(name).decode("ascii")
        names = []
        e = rva2off(secs, ilt if ilt else iat)
        j = 0
        while True:
            v = struct.unpack_from("<Q", p, e + 8 * j)[0]
            if v == 0:
                break
            names.append(cstr(v + 2).decode("ascii"))
            j += 1
        out[dll] = names
        cur += 20
    return out


def test_ffi():
    """[3i2] FFI（v1.87）：@ffi 调用系统库——多 DLL 导入表 + Win64 寄存器类。

    覆盖点：
      1. t120_ffi 自校验（int/void/bool/f64/f32、栈传参、cstr 往返）；
      2. 导入表里真的出现 ucrtbase.dll / ntdll.dll（用户声明的 DLL，
         不再是 kernel32 白名单）；
      3. Linux ELF 后端对 @ffi 必须 fail-fast（静态 ET_EXEC 无动态链接器）。
    """
    out = os.path.join(ROOT, "build", "win_t120_ffi.exe")
    build(os.path.join(ROOT, "tests/t120_ffi.qma"), out)
    r = run(out)
    if r is None:
        skip("FFI：非 Windows 平台，跳过执行")
    else:
        rc, stdout, stderr = r
        ok("FFI：t120_ffi 自校验通过（断言全过）") if rc == 0 \
            else bad(f"t120_ffi rc={rc} stderr={stderr[-200:]!r}")
        ok("FFI：输出 ffi ok") if stdout == b"ffi ok\n" else bad(f"t120_ffi 输出 {stdout!r}")

    imp = import_table(out)
    ok(f"FFI：导入表含 {len(imp)} 个 DLL（{', '.join(sorted(imp))}）") \
        if {"kernel32.dll", "ucrtbase.dll", "ntdll.dll"} <= set(imp) \
        else bad(f"FFI：导入 DLL 不全：{sorted(imp)}")
    ok("FFI：ucrtbase 只带被声明的 3 个符号") \
        if sorted(imp.get("ucrtbase.dll", [])) == ["pow", "sqrt", "sqrtf"] \
        else bad(f"ucrtbase 符号 {imp.get('ucrtbase.dll')!r}")
    ok("FFI：ntdll 只带 RtlMoveMemory") \
        if imp.get("ntdll.dll") == ["RtlMoveMemory"] \
        else bad(f"ntdll 符号 {imp.get('ntdll.dll')!r}")

    # Linux ELF：静态 ET_EXEC 没有 PT_INTERP，外部符号无处解析——必须明确报错
    import qlm_native
    try:
        qlm_native.transpile_native(os.path.join(ROOT, "tests/t120_ffi.qma"))
    except SyntaxError as ex:
        ok("FFI：Linux ELF 目标给出明确诊断（无动态链接器）") \
            if "只在 Windows PE 后端实现" in str(ex) else bad(f"ELF 诊断不符：{ex}")
    except Exception as ex:                                    # noqa: BLE001
        bad(f"FFI：ELF 目标抛了非 SyntaxError：{type(ex).__name__}: {ex}")
    else:
        bad("FFI：ELF 目标竟然编译通过（静态产物解析不了外部符号）")


def test_net_reactor():
    """[3j] 高并发网络：IOCP reactor（v1.4）

    examples/echo_reactor.qma：serve() + 回调（on_connect/on_data/on_close）。
    客户端（本进程 Python 线程）：
      R1 50 并发连接 × 50 轮往返 —— reactor 对全部连接服务
      R2 200 次连接 churn（建→echo→关）—— rec freelist 回收/复用
    """
    import threading
    port = 19531
    src = os.path.join(ROOT, "examples", "echo_reactor.qma")
    out = os.path.join(ROOT, "build", "win_reactor.exe")
    build(src, out)
    if not IS_WIN:
        skip("IOCP reactor：非 Windows 平台，跳过执行")
        return
    proc = subprocess.Popen([out], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        # 等服务就绪（监听端口可连接）
        import socket
        import time
        ready = False
        for _ in range(50):
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=1)
                s.close()
                ready = True
                break
            except OSError:
                time.sleep(0.1)
        ok("reactor：服务端口就绪") if ready else bad("reactor：服务未就绪")

        results = {"ok": 0, "fail": 0}
        lock = threading.Lock()

        def client(tid, n):
            okc = failc = 0
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=10)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                for i in range(n):
                    msg = f"t{tid}-m{i}".encode()
                    s.sendall(msg)
                    if s.recv(100) == msg:
                        okc += 1
                    else:
                        failc += 1
                s.close()
            except Exception:
                failc += 1
            with lock:
                results["ok"] += okc
                results["fail"] += failc

        ths = [threading.Thread(target=client, args=(t, 50)) for t in range(50)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        ok("reactor：50 并发连接 × 50 往返全等（2500/2500）"
           ) if results["ok"] == 2500 and results["fail"] == 0 else \
            bad(f"reactor 并发回显 ok={results['ok']} fail={results['fail']}")

        churn_ok = True
        for i in range(200):
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=5)
                s.sendall(b"churn")
                if s.recv(50) != b"churn":
                    churn_ok = False
                s.close()
            except Exception:
                churn_ok = False
                break
        ok("reactor：200 次连接 churn（freelist 回收）全等"
           ) if churn_ok else bad("reactor：连接 churn 出现回声不符/失败")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_debug_chain():
    """v1.71：调试链路两条子回归各算一项（脚本内部逐条断言）。

    dwarf_test：独立 DWARF 读取器对照 .qlmdbg（行表/变量位置/结构体布局）
    dbg_test  ：qlm_dbg 跑完整命令链（断点/求值/单步/bt/退出码）
    cov_test   ：行 + 分支覆盖率（含增量合并与两种阈值门禁）
    fuzz_test  ：编译器前端模糊测试（Quelmara 变异器 + 崩溃分类）
    cache_test ：增量缓存（命中/失效/损坏/串行=并行）
    qla_test   ：`.qla` 目标文件（往返/函数级增量/二进制库/失败路径）
    """
    if not IS_WIN:
        skip("调试链路：仅 Windows（Windows 调试 API）")
        return
    for name, script in (("DWARF 互操作", "tests/dwarf_test.py"),
                         ("调试器端到端", "tests/dbg_test.py"),
                         ("行+分支覆盖率", "tests/cov_test.py"),
                         ("模糊测试", "tests/fuzz_test.py"),
                         ("增量缓存", "tests/cache_test.py"),
                         ("持久化 KV", "tests/kv_test.py"),
                         ("qla 目标文件", "tests/qla_test.py"),
                         ("解释器差分", "tests/interp_test.py")):
        try:
            r = subprocess.run([sys.executable,
                                os.path.join(ROOT, script)],
                               cwd=ROOT, capture_output=True, text=True,
                               timeout=600)
        except subprocess.TimeoutExpired:
            bad(f"{name}：超时")
            continue
        tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
        if r.returncode == 0:
            ok(f"{name}：{tail[0]}")
        else:
            bad(f"{name}：{tail[0]}  {r.stdout[-400:]}{r.stderr[-300:]}")


def test_a64_iface():
    """v1.90：AArch64 接口 vtable 的**执行级**回归。

    irdiff 只证明两个后端产出同一份 IR，证明不了 A64 发射层把 vtable 表项
    填对、BLR 跳对了方法。这里编译成 AArch64 ELF 后用 tests/a64_emu.py 真跑
    7 个接口用例（装箱 / 异构容器 / 跨接口同名方法 / 所有权 / 跨文件 /
    泛型 enum 载荷 / 1 MB 堆上限下的引用计数回收）。

    纯 Python 模拟器，整套约 70 s；`--quick` 可跳过最慢的低堆用例。
    """
    r = subprocess.run([sys.executable, os.path.join(ROOT,
                                                    "tests/a64_iface_test.py")],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    if r.returncode == 0:
        ok(f"AArch64 接口 vtable 执行级：{tail[0]}")
    else:
        bad(f"AArch64 接口 vtable 执行级：{tail[0]}  "
            f"{r.stdout[-400:]}{r.stderr[-300:]}")


def test_lsp():
    """v1.91：语言服务器整链（脚本内部逐条断言，全平台可跑）。

    子进程跑 `tests/lsp_test.py`：词法对拍 + 容错索引 + 索引语义 +
    真 JSON-RPC 协议 + 性能阈值，本项只汇总一条结果。
    """
    try:
        r = subprocess.run([sys.executable,
                            os.path.join(ROOT, "tests", "lsp_test.py")],
                           cwd=ROOT, capture_output=True, text=True,
                           timeout=900)
    except subprocess.TimeoutExpired:
        bad("语言服务器：超时")
        return
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    if r.returncode == 0:
        ok(f"语言服务器：{tail[0]}")
    else:
        bad(f"语言服务器：{tail[0]}  {r.stdout[-500:]}{r.stderr[-300:]}")


def main():
    print("== [1] PE/COFF 结构（自研写出器，无 CRT） ==")
    out = os.path.join(ROOT, "build", "win_hello.exe")
    build(os.path.join(ROOT, "examples/hello.qma"), out)
    test_pe_structure(out)

    print("== [2] 基础语义 ==")
    if IS_WIN:
        rc, stdout, _ = run(out)
        lines = stdout.decode().splitlines()
        ok("hello: 首行 Hello, Quelmara") if lines and lines[0] == "Hello, Quelmara" \
            else bad(f"hello 输出 {lines[:2]!r}")
        ok("hello: 字符串拼接 + 循环 3 tick") if lines[1].startswith("cores online: ") \
            and lines[2:] == ["tick 0", "tick 1", "tick 2"] else bad(f"hello 行 {lines!r}")
    else:
        skip("hello 执行")
    case_output("fib", "examples/fib.qma", ["75025"])
    case_output("loop_sum", "examples/loop_sum.qma", ["1199999988"])
    case_output("utf8", "tests/win_utf8.qma", ["你好，Quelmara", "中文 + 拼接 ✓", "0", "1", "2"])

    print("== [3] 语言 v0.2：struct / enum / match / break / continue ==")
    for t in ("tests/t8.qma", "tests/t9.qma", "tests/t11.qma", "tests/t12.qma"):
        case_selfcheck(os.path.splitext(os.path.basename(t))[0], t)
    case_selfcheck("traffic_light", "examples/traffic_light.qma")

    print("== [3b] 定长数组 [N]T（v0.6） ==")
    case_output("arrays", "tests/t16_arrays.qma", ["33", "arrays ok"])
    test_array_bounds()

    print("== [3c] 字符串：len / 字节下标 / 十进制解析（v0.12） ==")
    case_selfcheck("str", "tests/t27_str.qma")
    case_selfcheck("to_int", "tests/t28_toint.qma")
    test_str_failfast()

    print("== [3d] 命令行参数 args()/arg()（v1.0） ==")
    out = os.path.join(ROOT, "build", "win_args.qex")
    build(os.path.join(ROOT, "tests/t29_args.qma"), out)
    r = run(out, args=["alpha", "beta", "two words"])
    if r is None:
        skip("args：非 Windows 平台")
    else:
        rc, stdout, stderr = r
        lines = stdout.decode().splitlines()
        ok("args: 参数个数 = 3") if lines and lines[0] == "3" else bad(f"args 行 {lines!r}")
        ok("args: 逐个取值正确") if lines[1:4] == ["alpha", "beta", "two words"] \
            else bad(f"args 值 {lines[1:4]!r}")
        ok("arg(0) 与 args()[0] 一致") if len(lines) > 4 and lines[4] == "alpha" \
            else bad(f"arg(0) {lines[4:5]!r}")
        ok("args 自校验通过（assert）") if rc == 0 else bad(f"args rc={rc} stderr={stderr[-160:]!r}")

    print("== [3d2] std/cli flag 解析（v1.29） ==")
    out = os.path.join(ROOT, "build", "win_cli.qex")
    build(os.path.join(ROOT, "tests/t77_cli.qma"), out)
    r = run(out, args=["--name=qm", "-p", "9000", "--verbose", "--bad=xyz",
                       "file1.txt", "--out", "a b"])
    if r is None:
        skip("std/cli：非 Windows 平台")
    else:
        rc, stdout, stderr = r
        lines = stdout.decode().splitlines()
        expect = ["8", "qm", "8080", "9000", "1", "0", "7", "1",
                  "file1.txt", "a b", "--name=qm", "", "ok t77_cli"]
        if lines == expect:
            ok("cli: 计数/取值/短名/布尔/默认值/位置参数 全部正确")
        else:
            bad(f"cli 输出 {lines!r} != {expect!r}")
        ok("cli 自校验通过（assert）") if rc == 0 else bad(f"cli rc={rc} stderr={stderr[-160:]!r}")

    print("== [3e] 读文件 / 子串 / 单字节串（v1.0） ==")
    out = os.path.join(ROOT, "build", "win_io.qex")
    build(os.path.join(ROOT, "tests/t30_io.qma"), out)
    data_path = os.path.join(ROOT, "build", "io_input.txt")
    with open(data_path, "w", encoding="utf-8") as f:
        f.write("hello-io")
    r = run(out, args=[data_path])
    if r is None:
        skip("read_text：非 Windows 平台")
    else:
        rc, stdout, stderr = r
        lines = stdout.decode().splitlines()
        ok("read_text: 文件长度 8") if lines[:1] == ["8"] else bad(f"io 行 {lines!r}")
        ok("substr: 前 5 字节") if lines[1:2] == ["hello"] else bad(f"substr {lines[1:2]!r}")
        ok("substr: 偏移 6 取 2 字节") if lines[2:3] == ["io"] else bad(f"substr2 {lines[2:3]!r}")
        ok("chr(65) = A") if lines[3:4] == ["A"] else bad(f"chr {lines[3:4]!r}")
        ok("substr 空区间长度为 0") if lines[4:5] == ["0"] else bad(f"empty {lines[4:5]!r}")
        ok("回文判断（hello 取前 5 => 非回文）") if lines[5:6] == ["0"] else bad(f"pal {lines[5:6]!r}")
        ok("io 自校验通过（assert）") if rc == 0 else bad(f"io rc={rc} stderr={stderr[-160:]!r}")

    print("== [3f] 逻辑运算与 let 值语义（v1.0 回归） ==")
    case_selfcheck("logic", "tests/t31_logic.qma")

    print("== [3g] 位运算 / 子切片 / 字典序（v1.1） ==")
    case_selfcheck("bits", "tests/t32_bits.qma")
    case_selfcheck("subslice", "tests/t33_subslice.qma")

    print("== [3h] vec / 遍历 / 数组参数（v1.2） ==")
    case_selfcheck("vec", "tests/t34_vec.qma")
    case_selfcheck("iter", "tests/t35_iter.qma")
    case_selfcheck("arrparam", "tests/t36_arrparam.qma")
    case_selfcheck("vecagg", "tests/t37_vecagg.qma")

    print("== [3i] 函数名作值 + callr 间接调用（v1.4 地基） ==")
    case_selfcheck("callr", "tests/t38_callr.qma")

    print("== [3k] 标准库 P0 四件套：sha256 / str / url / json（v1.6） ==")
    case_selfcheck("t43_sha256", "tests/t43_sha256.qma")
    case_selfcheck("t44_str", "tests/t44_str.qma")
    case_selfcheck("t45_url", "tests/t45_url.qma")
    case_selfcheck("t46_json", "tests/t46_json.qma")
    case_selfcheck("t47_gzip", "tests/t47_gzip.qma")
    case_selfcheck("t48_aes", "tests/t48_aes.qma")

    print("== [3j] 语言特性 v1.8（宽度 / @simd / rc[T] / 所有权） ==")
    case_selfcheck("t49_width", "tests/t49_width.qma")
    case_selfcheck("t50_simd", "tests/t50_simd.qma")
    case_selfcheck("t51_rc", "tests/t51_rc.qma")
    case_selfcheck("t52_iface", "tests/t52_iface.qma")
    case_selfcheck("t53_regress", "tests/t53_regress.qma")
    case_selfcheck("t54_iface_dyn", "tests/t54_iface_dyn.qma")
    # v1.83：跨接口同名方法共存 + 跨文件 interface（fixtures/ifacexfile）
    case_selfcheck("t116_iface_multi", "tests/t116_iface_multi.qma")
    case_selfcheck("iface_xfile", "fixtures/ifacexfile/main.qma")
    case_selfcheck("t55_sync", "tests/t55_sync.qma")
    # v1.86：MPMC 栈（2 生产者 / 2 消费者）+ WaitGroup 退避等待
    case_selfcheck("t121_syncmpmc", "tests/t121_syncmpmc.qma")
    # v1.86：atomic 内建语义（x86 lock 前缀 / A64 LL-SC 同一份用例）
    case_selfcheck("t97_atomic", "tests/t97_a64atomic.qma")
    # v1.86：std/sync 双后端可移植性（无 spawn 的无争用路径）
    case_selfcheck("t122_syncport", "tests/t122_syncport.qma")
    case_selfcheck("t56_generic", "tests/t56_generic.qma")
    case_selfcheck("t57_vecnest", "tests/t57_vecnest.qma")
    case_selfcheck("t58_stdmin", "tests/t58_stdmin.qma")
    case_selfcheck("t59_simdf64", "tests/t59_simdf64.qma")
    case_selfcheck("t60_srclayout", "fixtures/srcproj/main.qma")
    case_selfcheck("t61_udp", "tests/t61_udp.qma")
    case_selfcheck("t62_pool_log", "tests/t62_pool_log.qma")
    case_selfcheck("t63_inflate", "tests/t63_inflate.qma")
    case_selfcheck("t64_math", "tests/t64_math.qma")
    case_selfcheck("t65_x25519", "tests/t65_x25519.qma")
    case_selfcheck("t66_tls13", "tests/t66_tls13.qma")
    case_selfcheck("t67_ecdsa", "tests/t67_ecdsa.qma")
    case_selfcheck("t68_x509", "tests/t68_x509.qma")
    case_selfcheck("t69_tls_client", "tests/t69_tls_client.qma")
    case_selfcheck("t70_times", "tests/t70_times.qma")
    case_selfcheck("t71_rsa", "tests/t71_rsa.qma")
    case_selfcheck("t72_rsa2048", "tests/t72_rsa2048.qma")
    case_selfcheck("t73_ghash", "tests/t73_ghash.qma")
    case_selfcheck("t74_set_deque", "tests/t74_set_deque.qma")
    case_selfcheck("t75_utf8", "tests/t75_utf8.qma")
    case_selfcheck("t76_codec", "tests/t76_codec.qma")
    case_selfcheck("t78_lru", "tests/t78_lru.qma")
    # 定容环形缓冲 + 最小堆（v2.05 补 pub）：绕回 / 哨兵 / 扩容 / 打包 key
    case_selfcheck("t129_ds", "tests/t129_ds.qma")
    # 轮询式定时器（v2.08 重写）：id 序列 / 到期顺序 / cancel / 2000 个扩容
    case_selfcheck("t132_timer", "tests/t132_timer.qma")
    # vec[T] 下标（v2.13 补实现）：局部 / 形参 / 嵌套 / str / 聚合 / 表达式位置
    case_selfcheck("t141_vecindex", "tests/t141_vecindex.qma")
    # 分片并行写 + 工作线程读共享 vec（v2.16：qlmc 并行后端的地基）
    case_selfcheck("t143_parshard", "tests/t143_parshard.qma")
    case_selfcheck("t79_sse", "tests/t79_sse.qma")
    case_selfcheck("t80_md5", "tests/t80_md5.qma")
    case_selfcheck("t81_generic_infer", "tests/t81_generic_infer.qma")
    case_selfcheck("t82_vecmap", "tests/t82_vecmap.qma")
    case_selfcheck("t83_resagg", "tests/t83_resagg.qma")
    case_selfcheck("t84_structnest", "tests/t84_structnest.qma")
    case_selfcheck("t85_narrowstore", "tests/t85_narrowstore.qma")
    case_selfcheck("t86_mapstruct", "tests/t86_mapstruct.qma")
    case_selfcheck("t87_callrelax", "tests/t87_callrelax.qma")
    case_selfcheck("t126_closure", "tests/t126_closure.qma")
    case_selfcheck("t91_defer", "tests/t91_defer.qma")
    case_selfcheck("t119_drop", "tests/t119_drop.qma")
    # 所有权负向：这三个必须被借用检查拦下（编译失败）
    for nm, why, needle in (
            ("own_use_after_drop", "use-after-drop", "所有权检查"),
            ("own_double_drop", "double-free", "所有权检查"),
            ("own_move_use", "move-then-use", "所有权检查"),
            ("iface_missing", "impl 缺方法", "缺少方法"),
            ("iface_rettype", "impl 返回类型不符", "返回类型与接口声明不一致"),
            ("iface_no_impl", "类型未实现接口", "没有实现接口"),
            # v1.83：impl 共存了，静态调用才是歧义（走接口值就没有歧义）
            ("iface_dup_method", "跨接口同名方法的静态调用歧义", "静态调用有歧义"),
            ("defer_let", "defer 跟带作用域的语句", "defer 只支持"),
            # Drop（v1.86）：签名与重复实现
            ("drop_arity", "析构函数多一个形参", "接口要求 1 个参数"),
            ("drop_dupe", "同一类型两次 impl Drop", "重复实现"),
            ("neg_str", "对 str 取负", "一元 - 不能用于 str"),
            ("constfn_str", "const fn 用 str 形参", "只支持 int / bool"),
            ("constfn_call", "const 右值调普通函数", "只能调用 const fn"),
            ("gstruct_noarg", "泛型 struct 裸写", "必须带类型实参"),
            ("gstruct_vecarg", "泛型 struct 容器实参", "只支持具名类型"),
            ("gstruct_arity", "泛型 struct 实参个数", "个类型实参"),
            ("interp_unclosed", "插值缺右花括号", "缺少右花括号"),
            ("interp_empty", "插值段为空", "插值表达式为空"),
            # 类型约束（v1.61）：六条负向，各自钉住一种违反形态
            ("bound_unknown", "未知约束名", "未知约束"),
            ("bound_struct_ord", "struct 不满足 Ord", "实参 P 不满足"),
            ("bound_body_exceed", "模板体超出声明约束", "约束只声明了"),
            ("bound_iface_missing", "接口约束缺 impl", "没有 `impl"),
            ("bound_struct_param", "泛型 struct 约束不满足", "泛型 struct Box"),
            ("bound_enum_eq", "enum 不满足 Eq", "实参 Color 不满足"),
            # 泛型 impl（v1.62）：五种违反形态
            ("gimpl_missing", "模板 impl 缺方法", "缺少方法"),
            ("gimpl_dup", "同一接口重复实现", "重复"),
            ("gimpl_rettype", "模板 impl 返回类型不符", "返回类型与接口声明不一致"),
            ("gimpl_notgeneric", "非泛型 struct 带类型实参", "不是泛型类型"),
            ("gimpl_generic_fn", "泛型函数里的 Box[T]", "暂不支持把类型参数"),
            # 泛型 enum（v1.63）
            ("genum_noarg", "泛型 enum 裸写", "必须带类型实参"),
            ("genum_arity", "泛型 enum 实参个数", "个类型实参"),
            ("genum_tparam", "泛型函数里的 Opt[T]", "暂不支持把类型参数"),
            ("genum_nonexhaustive", "泛型 enum match 不穷尽", "不穷尽"),
            # 泛型 enum 的 impl（v1.64）
            ("genumimpl_bound", "impl 模板约束不满足", "不满足 Show"),
            ("genumimpl_missing", "enum 模板 impl 缺方法", "缺少方法"),
            # 属性宏 @derive + 编译期反射（v1.77）：十种违反形态
            ("derive_unknown", "未知派生项", "未知派生项"),
            ("derive_generic", "泛型 struct 上派生", "不能直接 @derive"),
            ("derive_genenum", "泛型 enum 上派生", "不能直接 @derive"),
            ("derive_orphan", "@derive 后面不是声明", "只能用于紧随其后"),
            ("derive_field_enum", "enum 字段没派生", "没有派生 Json"),
            ("derive_f32", "f32 字段派生", "f32 不参与派生"),
            ("derive_partial", "未派生项不生成", "方法 show 未定义"),
            ("refl_oob", "反射下标越界", "越界"),
            ("refl_notstruct", "对 enum 做字段反射", "不是 struct"),
            ("refl_stridx", "反射下标写成字符串", "下标必须是 int"),
            # 通用 token 宏（v1.96）
            ("macro_arity", "宏实参个数不符", "需要 2 个实参"),
            ("macro_recursive", "宏体自递归", "宏展开超过"),
            ("macro_dup", "宏重复定义", "重复定义"),
            # 按值自包含的聚合（v1.88）：没有有限布局
            ("struct_self", "struct 按值自包含", "不能按值包含自身"),
            ("enum_self", "enum 按值自包含", "不能按值包含自身"),
            # @simd 点积（v1.85）：两数组/累加器类型不一致必须拦下
            ("simd_dot_mixed", "@simd 点积 int/f64 混用", "同类型"),
            # 所有权检查 v2（v1.84）：视图生命周期 / 写别名 / 跨线程四类违反
            ("own_slice_escape", "返回指向本帧栈的切片", "悬垂"),
            ("own_struct_escape", "含栈视图的结构体逃逸", "悬垂"),
            ("own_alias_write", "同基址重叠视图都写", "别名写"),
            ("own_spawn_rc", "rc 句柄跨线程", "跨线程"),
            ("own_nested_match", "match 臂里的栈视图逃逸（守 _own_parts）", "悬垂"),
            # FFI（v1.87）：形参/返回只接受标量；声明不能带函数体
            ("ffi_str_param", "@ffi 形参写 str", "FFI 只接受"),
            ("ffi_struct_param", "@ffi 形参写 struct", "FFI 只接受"),
            ("ffi_body", "@ffi 声明带函数体", "不能带函数体"),
            # 闭包（v1.95）：捕获槽只有 1 字；聚合捕获、写捕获变量、把裸函数名
            # 当闭包传（代码地址 vs 两字聚合）三种形态必须拦下
            ("closure_capture_struct", "闭包捕获 struct", "暂不支持捕获聚合"),
            ("closure_assign_capture", "闭包内写捕获变量", "不能给捕获变量"),
            ("closure_fnptr_param", "裸函数名当闭包传", "实参不是闭包"),
            # v2.12：reactor 搬进 std，内建 net_serve 必须给出迁移诊断
            ("net_serve_builtin", "net_serve 内建已迁到标准库", "迁到标准库")):
        try:
            build(os.path.join(ROOT, f"tests/bad/{nm}.qma"),
                  os.path.join(ROOT, "build", f"bad_{nm}.exe"))
        except SyntaxError as ex:
            ok(f"编译期拦下 {why}") if needle in str(ex) \
                else bad(f"{nm} 报错但信息不符（期望含 {needle!r}）：{ex}")
        else:
            bad(f"{nm} 应当编译失败却通过了")
    # 跨模块同名 / 模块版本负向（v1.99，多文件）
    for nm, needles in (
            ("modsame_ambig", ("在多个模块里都有",)),
            ("modver_major", ("版本不兼容",)),
            ("modver_nodecl", ("没有声明版本",))):
        try:
            build(os.path.join(ROOT, f"tests/bad/{nm}/main.qma"),
                  os.path.join(ROOT, "build", f"bad_{nm}.exe"))
        except SyntaxError as ex:
            ok(f"跨模块负例拦下 {nm}") if any(n in str(ex) for n in needles) \
                else bad(f"{nm} 报错但信息不符（期望含 {needles!r}）：{ex}")
        else:
            bad(f"{nm} 应当编译失败却通过了")
    # pub 可见性负向（v1.43，多文件）：跨模块引用非 pub 声明必须编译期拦下
    try:
        build(os.path.join(ROOT, "tests/bad/pub_hidden/main.qma"),
              os.path.join(ROOT, "build", "bad_pub_hidden.exe"))
    except SyntaxError as ex:
        ok("pub：非 pub 跨模块引用被拦下") if "非 pub" in str(ex) \
            else bad(f"pub_hidden 报错但信息不符（期望含 '非 pub'）：{ex}")
    else:
        bad("pub_hidden 应当编译失败却通过了")
    # pub 正例（v1.43，多文件）：pub 声明跨模块可用
    case_selfcheck("t88_pubvis", "fixtures/pubvis/main.qma")
    # 跨文件接口负向（v1.90，多文件）：两种违反形态
    #   ① 同名接口在两个模块里签名不一致 -> 接口冲突
    #   ② impl 引用了根本没声明的接口 -> 未声明的接口（宽松期占位不算声明）
    for nm, why, needle in (
            ("iface_xfile_conflict", "跨文件同名接口签名不一致", "接口冲突"),
            ("iface_xfile_undecl", "impl 引用未声明接口", "未声明的接口")):
        try:
            build(os.path.join(ROOT, f"tests/bad/{nm}/main.qma"),
                  os.path.join(ROOT, "build", f"bad_{nm}.exe"))
        except SyntaxError as ex:
            ok(f"编译期拦下 {why}") if needle in str(ex) \
                else bad(f"{nm} 报错但信息不符（期望含 {needle!r}）：{ex}")
        else:
            bad(f"{nm} 应当编译失败却通过了")
    # 限定语法正例（v1.44，多文件）：lib.fn()/lib.Enum.Variant/限定模式
    case_selfcheck("t89_qualified", "fixtures/qualified/main.qma")
    case_selfcheck("t90_mathfn", "tests/t90_mathfn.qma")
    case_selfcheck("t93_f64print", "tests/t93_f64print.qma")
    case_selfcheck("t92_httpc", "tests/t92_httpc.qma")
    case_selfcheck("t94_slice_narrow", "tests/t94_slice_narrow.qma")
    case_selfcheck("t95_hash512", "tests/t95_hash512.qma")
    # @simd f64 点积（v1.60）：acc += a[i] * b[i]，SSE2 mulpd 两路
    case_selfcheck("t96_simddot", "tests/t96_simddot.qma")
    # @simd int 点积（v1.83）：SSE2 3×pmuludq 拼 64x64->低 64 + paddq 两路
    case_selfcheck("t117_simdintdot", "tests/t117_simdintdot.qma")
    case_selfcheck("t98_constfn", "tests/t98_constfn.qma")
    case_selfcheck("t99_generic_struct", "tests/t99_generic_struct.qma")
    case_selfcheck("t100_interp", "tests/t100_interp.qma")
    # 类型约束（v1.61）：能力约束 + 接口约束 + 泛型 struct 约束
    case_selfcheck("t101_bounds", "tests/t101_bounds.qma")
    # 泛型 struct 的方法（v1.62）：模板 impl + 具体实例 impl + 动态派发
    case_selfcheck("t102_generic_impl", "tests/t102_generic_impl.qma")
    # 泛型 enum（v1.63）：Opt[T] / Either[A,B] / 嵌套实例 / vec 元素
    case_selfcheck("t103_generic_enum", "tests/t103_generic_enum.qma")
    # 泛型 enum 的方法（v1.64）：模板 impl + 类型约束 + 具体实例 impl
    case_selfcheck("t104_generic_enum_impl", "tests/t104_generic_enum_impl.qma")
    # 字符串有序比较（v1.66）：表达式路径 + 条件路径 + Ord 覆盖 str
    case_selfcheck("t105_strorder", "tests/t105_strorder.qma")
    # 静态文件服务的两块（v1.67）：std/mime + std/router
    case_selfcheck("t106_weblib", "tests/t106_weblib.qma")
    # 静态文件解析层（v1.68）：URL 解码 / 穿越防护 / Range
    case_selfcheck("t107_staticfile", "tests/t107_staticfile.qma")
    # 静态文件端到端（v1.69）：200/206/404/403 + 目录 index + 二进制正文
    case_selfcheck("t108_staticserve", "tests/t108_staticserve.qma")
    # Cookie（v1.70）：解析 / 编解码 / Set-Cookie 拼装
    case_selfcheck("t109_cookie", "tests/t109_cookie.qma")
    # 属性宏 @derive + 编译期反射（v1.72）：序列化 / 等价 / 展示 / refl_*
    case_selfcheck("t115_derive", "tests/t115_derive.qma")
    # 跨模块派生（v1.73）：pub struct 的派生函数必须继承 pub
    case_selfcheck("derivepub", "fixtures/derivepub/dpub_main.qma")
    # 跨模块同名声明 + 模块版本（v1.99）：per-module mangling 正例
    case_selfcheck("modsame", "fixtures/modsame/main.qma")
    # enum 派生 + f64 字段（v1.88）：{"$v":...} 约定 / 往返 / 精度
    case_selfcheck("t123_derive_enum", "tests/t123_derive_enum.qma")
    # 通用 token 宏（v1.96）：语句 / 表达式 / 生成声明 / 宏调宏 / 前向引用
    case_selfcheck("t124_macro", "tests/t124_macro.qma")
    # 运行时下标反射（v1.88）：常量折叠 + 按需查表
    case_selfcheck("t125_refl_dyn", "tests/t125_refl_dyn.qma")
    # 会话存储（v1.71）：TTL / 惰性过期 / 墓碑销毁
    case_selfcheck("t110_session", "tests/t110_session.qma")
    # multipart 解析（v1.72）：boundary / 字段与文件 / CRLF 正文
    case_selfcheck("t111_multipart", "tests/t111_multipart.qma")
    # HTTP 日期（v1.73）：IMF-fixdate 格式化 / 解析 / If-Modified-Since
    case_selfcheck("t112_httpdate", "tests/t112_httpdate.qma")
    # CSV（v1.74）：RFC 4180 解析 / 生成 / 往返
    case_selfcheck("t113_csv", "tests/t113_csv.qma")
    # 路径处理（v1.75）：join / clean / dir / base / ext / stem
    case_selfcheck("t114_path", "tests/t114_path.qma")
    # LICM 默认开启 + 字节存储的寄存器编码（v2.59）：store8 的值落在
    # rsi/rdi 时必须带 REX 前缀，否则编成 ah/ch/dh/bh
    case_selfcheck("t144_licm_bytes", "tests/t144_licm_bytes.qma")
    # 同一循环头多条回边（continue）：循环携带值不得被 LICM 当不变量
    case_selfcheck("t145_licm_multiedge", "tests/t145_licm_multiedge.qma")
    # 常数除法/取模的魔数乘法（v2.61）：商*C+余数==被除数 且 0<=余数<C
    case_selfcheck("t146_const_div", "tests/t146_const_div.qma")
    # int→str 的取位循环改用魔数乘（v2.64）：往返对拍 + 进位边界
    case_selfcheck("t147_itoa_magic", "tests/t147_itoa_magic.qma")
    # f64 住 XMM（v2.65）：循环/直线两条路径对拍 + 结构体/数组/调用/取负
    case_selfcheck("t148_f64_xmm", "tests/t148_f64_xmm.qma")
    # "算完再搬回变量"折成就地更新（v2.67）：别名/自反/循环携带/int64 两端
    case_selfcheck("t149_store_back", "tests/t149_store_back.qma")
    # 标志位循环 → break（v2.69）：可改 / 不可改 各四种形态
    case_selfcheck("t150_flag_loop", "tests/t150_flag_loop.qma")
    # UUID（v1.77）：v4 生成 / 校验 / 版本与变体位
    case_selfcheck("t115_uuid", "tests/t115_uuid.qma")
    # 所有权检查 v2（v1.84）：视图生命周期 / 写别名 / 跨线程的正例
    case_selfcheck("t116_ownview", "tests/t116_ownview.qma")
    case_selfcheck("t99_regex", "tests/t99_regex.qma")

    print("== [3i2] FFI：@ffi 调用系统库（v1.87） ==")
    test_ffi()
    # pub + 限定语法负向（多文件）：非 pub 跨模块引用必须编译失败
    # （限定调用可能先被通用 pub 检查或指向校验拦下，两种消息都算对）
    for nm, needles in (("pub_hidden", ("非 pub",)),
                        ("pub_hidden_q", ("非 pub", "无法解析"))):
        try:
            build(os.path.join(ROOT, f"tests/bad/{nm}/main.qma"),
                  os.path.join(ROOT, "build", f"bad_{nm}.exe"))
        except SyntaxError as ex:
            ok(f"pub 负例拦下 {nm}") if any(n in str(ex) for n in needles) \
                else bad(f"{nm} 报错但信息不符（期望含 {needles!r}）：{ex}")
        else:
            bad(f"{nm} 应当编译失败却通过了")
    # gzip 的唯一权威证明：Python zlib 逐字节解压
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests/gzip_interop.py")],
                       cwd=ROOT, capture_output=True, text=True, errors="replace")
    if r.returncode == 0:
        ok("gzip：zlib 解压逐字节一致（%d 个样本）"
           % sum(1 for ln in r.stdout.splitlines() if "[PASS]" in ln))
    else:
        bad(f"gzip zlib 互操作失败：{r.stdout[-300:]}{r.stderr[-200:]}")

    print("== [3i3] 持久化：std/fs + std/kv（v1.102） ==")
    # t127 在单进程内校验 API 语义；t128 钉住"void 早退不能污染退出码"
    case_selfcheck("kv", "tests/t127_kv.qma")
    case_output("mainret", "tests/t128_mainret.qma", ["mainret ok"])

    print("== [3i4] 日志：std/log 时间戳/通道 + std/logfile 轮转（v2.03） ==")
    # t131 自校验时间戳形态、时区、级别、文件通道、轮转与失败路径；
    # log_streams 单独钉住 stdout/stderr 分流（程序看不到自己的两个流）
    case_selfcheck("log", "tests/t131_log.qma")
    test_log_streams()

    print("== [3j] 高并发网络：IOCP reactor + 回调（v1.4） ==")
    test_net_reactor()

    print("== [4] 多核：CreateThread + 共享内存归约 ==")
    case_output("parfor_sum", "examples/parfor_sum.qma", ["11519999978"])
    case_selfcheck("prime_parallel", "examples/prime_parallel.qma")
    case_selfcheck("game_loop", "examples/game_loop.qma")
    case_selfcheck("t10", "tests/t10.qma")
    case_output("spawn", "tests/t13_spawn.qma", ["6765", "81", "110", "spawn ok"])
    case_output("chan", "tests/t15_chan.qma", ["749500", "chan ok"])
    case_selfcheck("chan_close", "tests/t25_chan_close.qma")
    case_selfcheck("select", "tests/t26_select.qma")
    test_chan_close_fail()
    case_selfcheck("result", "tests/t17_result.qma")
    case_selfcheck("option", "tests/t19_option.qma")
    case_selfcheck("result_generic", "tests/t20_result_generic.qma")
    case_selfcheck("slice", "tests/t21_slice.qma")
    case_selfcheck("map", "tests/t22_map.qma")
    case_selfcheck("float", "tests/t23_float.qma")
    case_selfcheck("join_method", "tests/t24_join_method.qma")

    print("== [5] 单核降级（Quelmara.toml multicore=false） ==")
    test_single_core()

    print("== [5b] arena 帧级回收（1MB 堆上限 / 4MB 分配量） ==")
    test_arena()

    print("== [5c] 接口装箱引用计数（1MB 堆上限 / 19MB 装箱量） ==")
    test_iface_rc()

    print("== [6] 失败路径（assert） ==")
    test_assert_fail()
    test_exitcode()

    print("== [7] Windows PE × Linux ELF 交叉验证 ==")
    test_cross_verify()

    print("== [8] 调试链路（--dbg-info / DWARF / qlm_dbg） ==")
    test_debug_chain()

    print("== [9] AArch64 接口 vtable（ELF + 模拟器执行级） ==")
    test_a64_iface()

    print("== [9b] stage-1 编译器（qlmc，子集 S2）差分 ==")
    test_qlmc()

    print("== [10] 语言服务器（索引对拍 / 补全 / 跳转 / 重命名 / 协议） ==")
    test_lsp()

    print("-" * 52)
    print(f"PASS={PASS} FAIL={FAIL} SKIP={SKIP}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
