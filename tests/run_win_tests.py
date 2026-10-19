#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rosoto Windows PE/COFF 后端回归（自研，无 CRT）
================================================
在 Windows 上直接执行 .exe；在非 Windows 上只做结构/构建检查并跳过执行。

覆盖：
  [1] PE 结构：MZ/PE32+/AMD64/console、导入仅 kernel32、无 CRT 符号、体积
  [2] 基础语义：hello / fib / loop_sum / 大整数打印 / UTF-8 中文
  [3] 语言 v0.2：t8 break/continue、t9 struct、t11 嵌套、t12 enum+match
  [4] 多核：parfor_sum / prime_parallel / game_loop / t10（CreateThread 归约）
  [5] 单核降级：Rosoto.toml multicore=false（同结果）
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
sys.path.insert(0, os.path.join(ROOT, "tools"))

import rosoto_pe  # noqa: E402

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
    blob, cfg = rosoto_pe.transpile_win(src)
    rosoto_pe.write_exe(out, blob)
    return blob, cfg


def run(exe, timeout=120):
    if not IS_WIN:
        return None
    p = subprocess.run([exe], capture_output=True, timeout=timeout)
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
              "CreateThread", "WaitForSingleObject", "CloseHandle"} for n in names) \
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
    tmp = tempfile.mkdtemp(prefix="rosoto_win_1c_")
    try:
        with open(os.path.join(tmp, "Rosoto.toml"), "w", encoding="utf-8") as f:
            f.write("[core]\nmulticore = false\nthreads = 1\n")
        shutil.copy(os.path.join(ROOT, "examples/parfor_sum.ros"), tmp)
        src = os.path.join(tmp, "parfor_sum.ros")
        out = os.path.join(ROOT, "build", "win_parfor_sum_1c.exe")
        blob, cfg = rosoto_pe.transpile_win(src)
        rosoto_pe.write_exe(out, blob)
        ok("单核配置被读取（multicore=False）") if cfg["core"]["multicore"] is False \
            else bad(f"配置未生效: {cfg['core']}")
        r = run(out)
        if r is None:
            skip("单核降级：非 Windows 平台，跳过执行")
        else:
            rc, stdout, stderr = r
            ok("单核降级结果不变") if rc == 0 and stdout.strip() == b"11519999978" \
                else bad(f"单核降级错误 rc={rc} out={stdout[:80]!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_assert_fail():
    out = os.path.join(ROOT, "build", "win_assert.exe")
    build(os.path.join(ROOT, "tests/win_assert.ros"), out)
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
    cases = ["tests/divmod.ros", "tests/t8.ros", "tests/t9.ros", "tests/t11.ros",
             "tests/t12.ros", "examples/inventory.ros", "examples/collatz.ros",
             "examples/game_loop.ros"]
    # 注意：hello 的 cores() 是编译期常量（Windows=物理核，WSL=4），不参与逐字节比对。
    drive = ROOT[0].lower()
    wsl_root = f"/mnt/{drive}/" + ROOT[3:].replace("\\", "/")
    for src in cases:
        name = os.path.splitext(os.path.basename(src))[0]
        out = os.path.join(ROOT, "build", f"win_{name}.exe")
        build(os.path.join(ROOT, src), out)
        win = run(out, timeout=300)
        cmd = (f"cd {wsl_root!r} && "
               f"python3 tools/rosoto_native.py run {src} 2>/dev/null | grep -v '^\\[rosoto'")
        nat = subprocess.run(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "bash", "-lc", cmd],
                             capture_output=True)
        if win is None or nat.returncode != 0:
            bad(f"{name} 交叉验证执行失败")
            continue
        ok(f"{name} PE 与 Linux ELF 输出逐字节一致") if win[1] == nat.stdout \
            else bad(f"{name} 输出不一致\n    win={win[1][:120]!r}\n    elf={nat.stdout[:120]!r}")


def main():
    print("== [1] PE/COFF 结构（自研写出器，无 CRT） ==")
    out = os.path.join(ROOT, "build", "win_hello.exe")
    build(os.path.join(ROOT, "examples/hello.ros"), out)
    test_pe_structure(out)

    print("== [2] 基础语义 ==")
    if IS_WIN:
        rc, stdout, _ = run(out)
        lines = stdout.decode().splitlines()
        ok("hello: 首行 Hello, Rosoto") if lines and lines[0] == "Hello, Rosoto" \
            else bad(f"hello 输出 {lines[:2]!r}")
        ok("hello: 字符串拼接 + 循环 3 tick") if lines[1].startswith("cores online: ") \
            and lines[2:] == ["tick 0", "tick 1", "tick 2"] else bad(f"hello 行 {lines!r}")
    else:
        skip("hello 执行")
    case_output("fib", "examples/fib.ros", ["75025"])
    case_output("loop_sum", "examples/loop_sum.ros", ["1199999988"])
    case_output("utf8", "tests/win_utf8.ros", ["你好，Rosoto", "中文 + 拼接 ✓", "0", "1", "2"])

    print("== [3] 语言 v0.2：struct / enum / match / break / continue ==")
    for t in ("tests/t8.ros", "tests/t9.ros", "tests/t11.ros", "tests/t12.ros"):
        case_selfcheck(os.path.splitext(os.path.basename(t))[0], t)
    case_selfcheck("traffic_light", "examples/traffic_light.ros")

    print("== [4] 多核：CreateThread + 共享内存归约 ==")
    case_output("parfor_sum", "examples/parfor_sum.ros", ["11519999978"])
    case_selfcheck("prime_parallel", "examples/prime_parallel.ros")
    case_selfcheck("game_loop", "examples/game_loop.ros")
    case_selfcheck("t10", "tests/t10.ros")

    print("== [5] 单核降级（Rosoto.toml multicore=false） ==")
    test_single_core()

    print("== [6] 失败路径（assert） ==")
    test_assert_fail()

    print("== [7] Windows PE × Linux ELF 交叉验证 ==")
    test_cross_verify()

    print("-" * 52)
    print(f"PASS={PASS} FAIL={FAIL} SKIP={SKIP}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
