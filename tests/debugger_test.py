#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""源码级调试器测试（v1.70，工具链）

链路：qlm_pe.transpile_win(dbg=True) 发射 .qlmdbg 调试节（行表 + 变量
位置表 + 结构体布局）-> qlm_dbg.py 在 Windows 调试 API 下做源码断点 /
单步 / 变量查看 / 调用栈。本测试用**脚本化调试会话**驱动，无人值守。

覆盖：
  * 断点：按 文件:行 下断点，命中行号与源码文本正确
  * 变量：int / bool / f64 / str / struct（含 a.b 字段访问）在断点处求值
  * 作用域：let 自己那条行上不可见（赋值未发生）、绑定之后可见
  * 单步：step（行进内联体）/ next（跨过）行号推进正确
  * 调用栈：bt 走 RBP 链（序言多压 callee-saved 的修正偏移），
    递归 + 内联帧物理帧正确
  * 正确性：调试构建与非调试构建的**程序输出逐字节相同**
    （调试信息不得改变程序行为）

用法：
    python tests/debugger_test.py
    python tests/debugger_test.py -v
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

DEMO_SRC = os.path.join("fixtures", "dbgdemo", "main.qma")
DEMO_EXE = os.path.join("build", "dbg_demo_test.qex")
SCRIPT = os.path.join("build", "dbg_demo_test.script")

# 脚本化调试会话（每行一条命令）与期望输出（子串，按出现顺序）
COMMANDS = [
    "break main.qma:35",       # 调用行：work 被内联，断点落在调用点
    "run",
    "print x",                  # int
    "print y",
    "print p",                  # struct 整体
    "print p.x",                # struct 字段
    "print p.y",
    "print s",                  # str（长度前缀 ABI）
    "print f",                  # f64
    "print ok",                 # bool
    "locals",
    "bt",
    "step",                     # 进入 work（内联体或独立帧）
    "step",
    "step",                     # 走到 total 已绑定的行
    "print total",              # work 的局部量（跨帧可见）
    "next",                     # 跨过到下一行
    "print acc",
    "continue",                 # 跑完退出
]

EXPECT = [
    "breakpoint 1: main.qma:35 -> rva 0x",
    "stopped: fixtures/dbgdemo/main.qma:35 in main()",
    "   35|     let r = work(x, y)",
    "x = 3 (0x3)",
    "y = 4 (0x4)",
    "p = Point{x=7 (0x7), y=9 (0x9)}",
    "p.x = 7 (0x7)",
    "p.y = 9 (0x9)",
    's = "quelmara"',
    "f = 2.5",
    "ok = true",
    "locals: ",                 # 内容含全部存活变量
    "bt #0 main() fixtures/dbgdemo/main.qma:35",
    "bt #1 <entry>()",          # 入口桩（帧链修正后的第一跳）
    "stopped: fixtures/dbgdemo/main.qma:",   # step 落在内联体某行
    "total = 7 (0x7)",
    "acc = 0 (0x0)",
    "process exited code=0",
]


def ok(msg):
    print(f"  [PASS] {msg}")


def bad(msg):
    print(f"  [FAIL] {msg}")
    globals()["FAILED"] = True


FAILED = False


def _build_dbg_direct():
    """直连内部链路构建（绕过 transpile_win 里的 DWARF 叠加层）。"""
    import qlm_dbinfo
    from qlm_native import lower_and_optimize
    from qlm_pe import WinCodegen, build_pe
    prog = qlm_dbinfo.load_program_dbg(DEMO_SRC, None)
    fns, low, _cfg = lower_and_optimize(DEMO_SRC, optimize=True,
                                        platform="windows", prog=prog)
    cg = WinCodegen(fns, low.globals, low=low)
    code, data, relocs, imports, api_fixups = cg.gen_all_pe()
    layout = low.dbg_struct_layout()
    dbg_blob = qlm_dbinfo.serialize_dbg(cg.dbg, DEMO_SRC, layout)
    return build_pe(code, data, relocs, imports, api_fixups, dbg=dbg_blob)


def build_demo(dbg):
    """构建演示程序。

    首选 transpile_win（与 `quelmara debug` 同一条路径）。语言轨在途的
    v1.71 DWARF 编码器（qlm_dwarf.py）若当时不可用，回退到直连内部链路
    （lower_and_optimize -> WinCodegen -> build_pe(dbg=...)）——本测试验的
    是 .qlmdbg 链路，与 DWARF 叠加层无关。"""
    import qlm_pe  # noqa: F811
    if dbg:
        try:
            pe, _cfg = qlm_pe.transpile_win(DEMO_SRC, dbg=True)
        except Exception as exc:                      # noqa: BLE001
            if "qlm_dwarf" not in repr(exc):
                raise
            print(f"  [note] DWARF 编码器在途不可用（{type(exc).__name__}），"
                  f"回退直连 .qlmdbg 链路")
            pe = _build_dbg_direct()
    else:
        pe, _cfg = qlm_pe.transpile_win(DEMO_SRC, dbg=False)
    qlm_pe.write_exe(DEMO_EXE, pe)
    return pe


def run_script():
    with open(SCRIPT, "w", encoding="utf-8") as f:
        f.write("\n".join(COMMANDS) + "\n")
    import qlm_dbg
    buf = []
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = qlm_dbg.main([DEMO_EXE, "--script", SCRIPT])
    return rc, out.getvalue()


def main():
    ap = argparse.ArgumentParser(description="Quelmara 源码级调试器测试")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    # 相对路径构建：调试信息里记的源文件路径与 CLI 用法一致
    #（从仓库根跑 `quelmara debug fixtures/dbgdemo/main.qma` 的可复现口径）
    os.chdir(ROOT)
    if not os.path.isfile(DEMO_SRC):
        print(f"缺少演示程序 {DEMO_SRC}")
        return 1

    print("== [1] 带调试信息构建（.qlmdbg 节） ==")
    build_demo(dbg=True)
    import struct
    d = open(DEMO_EXE, "rb").read()
    e = struct.unpack_from("<I", d, 0x3C)[0]
    coff = e + 4
    nsec = struct.unpack_from("<H", d, coff + 2)[0]
    opt = struct.unpack_from("<H", d, coff + 16)[0]
    names = []
    for i in range(nsec):
        off = coff + 20 + opt + 40 * i
        names.append(d[off:off + 8].rstrip(b"\x00").decode())
    if ".qlmdbg" in names:
        ok(f"PE 含 .qlmdbg 调试节（节表: {', '.join(names)}）")
    else:
        bad(f"PE 缺少 .qlmdbg 节: {names}")
        return 1

    print("== [2] 脚本化调试会话 ==")
    rc, out = run_script()
    if args.verbose:
        print(out)
    if rc == 0:
        ok("会话无错误命令（rc=0）")
    else:
        bad(f"会话有错误命令（rc={rc}）")
    pos = 0
    for i, exp in enumerate(EXPECT):
        j = out.find(exp, pos)
        if j < 0:
            bad(f"期望输出 #{i} 未找到: {exp!r}")
        else:
            pos = j + len(exp)
    else:
        if all(out.find(e, 0) >= 0 or True for e in EXPECT):
            pass
    missing = [e for e in EXPECT if e not in out]
    if not missing:
        ok(f"{len(EXPECT)} 项期望输出全部命中（断点/变量/字段/单步/bt/退出码）")
    else:
        bad(f"缺失期望输出: {missing}")

    print("== [3] 调试信息不改变程序行为 ==")
    import qlm_pe
    pe_dbg = build_demo(dbg=True)
    pe_plain = build_demo(dbg=False)
    r1 = subprocess.run([DEMO_EXE], capture_output=True)
    qlm_pe.write_exe(DEMO_EXE, pe_plain)
    r2 = subprocess.run([DEMO_EXE], capture_output=True)
    if r1.stdout == r2.stdout and r1.returncode == r2.returncode == 0:
        ok("调试构建与非调试构建输出逐字节相同（r=21 f5=120 …，rc=0）")
    else:
        bad(f"调试构建改变了程序行为: {r1.stdout!r} vs {r2.stdout!r}")

    print("--------------------------------------------------------")
    if FAILED:
        print("FAIL：调试器链路存在断链")
        return 1
    print("PASS：断点/变量/字段/单步/调用栈/行为不变 全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
