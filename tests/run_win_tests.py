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
    probe = subprocess.run(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "bash", "-lc",
                            "python3 --version"], capture_output=True)
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

    print("== [6] 失败路径（assert） ==")
    test_assert_fail()

    print("== [7] Windows PE × Linux ELF 交叉验证 ==")
    test_cross_verify()

    print("-" * 52)
    print(f"PASS={PASS} FAIL={FAIL} SKIP={SKIP}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
