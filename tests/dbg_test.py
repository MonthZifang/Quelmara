#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
源码级调试器端到端回归（v1.71）
==============================
不是"能启动就算过"：用固定靶（`fixtures/dbgdemo/main.qma`）跑完整命令链，
逐条断言输出。覆盖：

  行断点 / 断点编号与命中计数 / 删除断点
  变量求值（int / str / f64 / bool / struct 字段）与三种"不可读"语义
  （尚未初始化 / 已超出生命周期 / 未知）
  单步 next / finish / 调用栈 bt / 源码 list
  被调试进程的真实输出与退出码

跑法：python tests/dbg_test.py
"""

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "fixtures", "dbgdemo", "main.qma")
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
DBG = os.path.join(ROOT, "tools", "stage0", "qlm_dbg.py")

PASS = FAIL = 0

# 顺序即语义：断点 -> run -> 求值 -> 单步 -> 继续
SCRIPT = """\
break main.qma:30
break main.qma:11
break main.qma:12
break main.qma:37
run
print x
print y
locals
list
info break
next
print y
continue
print a
print b
print total
bt
locals
next
print total
print a
finish
next
print r
continue
print f5
print p.x
print s
print f
print ok
delete 1
info break
continue
quit
"""


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def want(out, needle, why):
    if needle in out:
        ok(why)
    else:
        bad(f"{why}（未找到 {needle!r}）")


def main():
    exe = os.path.join(ROOT, "build", "dbg_e2e.exe")
    r = subprocess.run([sys.executable, CLI, "build", SRC, "--target", "win",
                        "--dbg-info", "-o", exe],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        bad(f"构建失败: {r.stdout[-300:]} {r.stderr[-600:]}")
        return 1
    ok("--dbg-info 构建成功")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as f:
        f.write(SCRIPT)
        script = f.name
    try:
        p = subprocess.run([sys.executable, DBG, exe, "--script", script],
                           cwd=ROOT, capture_output=True, text=True,
                           timeout=180)
    finally:
        os.unlink(script)
    out = p.stdout + p.stderr

    # ---- 断点 ----
    want(out, "breakpoint 1: main.qma:30 -> rva 0x", "行断点 main.qma:30")
    want(out, "breakpoint 2: main.qma:11 -> rva 0x", "行断点 main.qma:11（work 内）")
    want(out, "breakpoint 4: main.qma:37 -> rva 0x", "行断点 main.qma:37")

    # ---- 命中与源码定位 ----
    want(out, "main.qma:30 in main()", "停在 main 第 30 行")
    want(out, "30|     let y = 4", "显示当前源码行")

    # ---- 变量求值 + 三种不可读语义 ----
    want(out, "x = 3 (0x3)", "print x = 3")
    want(out, "变量 'y' 尚未初始化", "声明行之前：y 尚未初始化（不猜值）")
    want(out, "locals: x=3 (0x3)", "locals 只列存活变量")

    # ---- list / info ----
    want(out, "> 30|     let y = 4", "list 标出当前行")
    want(out, "#1 main.qma:30 rva=0x", "info break 列断点")
    want(out, "hits=1", "断点命中计数")

    # ---- 单步 ----
    want(out, "main.qma:31 in main()", "next 到 31 行")
    want(out, "y = 4 (0x4)", "next 之后 y 可读")

    # ---- 进入 work ----
    want(out, "main.qma:11 in work()", "命中 work 内的断点")
    want(out, "a = 3 (0x3)", "形参 a = 3")
    want(out, "b = 4 (0x4)", "形参 b = 4")
    want(out, "变量 'total' 尚未初始化", "同一条语句里：total 尚未赋值")
    want(out, "bt #0 work()", "bt 顶帧是 work")
    want(out, "bt #1 main()", "bt 次帧是 main")
    want(out, "locals: a=3 (0x3), b=4 (0x4)", "work 帧 locals 完整")

    # ---- 生命周期边界（诚实模型：不显示被复用的过期值）----
    want(out, "main.qma:12 in work()", "next 到 12 行")
    want(out, "total = 7 (0x7)", "局部 total = 7（a+b）")
    want(out, "变量 'a' 已超出生命周期", "a 的最后使用之后不再显示（寄存器已复用）")

    # ---- finish ----
    want(out, "main.qma:35 in main()", "finish 回到调用点（35 行）")

    # ---- 复合类型 ----
    want(out, "r = 21 (0x15)", "work(3,4) = 21")
    want(out, "f5 = 120 (0x78)", "fact(5) = 120")
    want(out, "p.x = 7 (0x7)", "struct 字段 p.x")
    want(out, 's = "quelmara"', "str 变量按内容显示")
    want(out, "f = 2.5", "f64 变量按浮点显示")
    want(out, "ok = true", "bool 变量按 true 显示")

    # ---- 删除断点 ----
    want(out, "deleted breakpoint 1", "delete 1")
    want(out, "#4 main.qma:37 rva=0x", "删除后断点表保留 #2/#3/#4")

    # ---- 被调试进程的真实输出 ----
    for line in ("r=21", "f5=120", "p=7,9", "s=quelmara", "f=2.5", "ok=true"):
        want(out, line, f"程序输出 {line}")
    want(out, "process exited code=0", "进程正常退出（退出码 0）")

    print(f"\nDEBUGGER: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
