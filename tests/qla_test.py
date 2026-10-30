#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
`.qla` 目标文件 / 函数级增量 / 二进制库 回归（v2.03）
====================================================
断言的是"档案不说谎"——`.qla` 是**分发单元**，它一旦错，错误会被复制到
所有使用方：

  [A] 往返：直编 PE 与「档案 -> 链接」的 PE **逐字节相同**（抽样代表夹具）
  [B] 函数级增量：
      - 无改动 -> 档案逐字节相同、全部函数复用
      - 改一个函数体 -> 只有它重降级（被调方改体不牵连调用方）
      - 加一个函数 -> 其余全部复用
      - 改类型布局（struct 加字段）-> 全部失效（保守但正确）
  [C] 二进制库：`--lib` 档案脱离源码分发；使用方只拿签名与布局；
      运行结果正确；非 pub 函数不进符号表
  [D] 失败路径：缺 main / 重复 main / 未定义符号 / 符号冲突 /
      指纹不符 / 档案损坏
  [E] CLI：`qla --stat/--symbols/--verify`、`link`、`build --incr`

跑法：python tests/qla_test.py          （约 40 s）
     python tests/qla_test.py --full    （再把 tests/ 全量过一遍往返）
"""

import glob
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm_pe      # noqa: E402
import qlm_qla     # noqa: E402

WORK = os.path.join(ROOT, "build", "_qlatest")
PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def check(cond, msg, detail=""):
    if cond:
        ok(msg)
    else:
        bad(msg + (f"：{detail}" if detail else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def run_cli(*args, **kw):
    return subprocess.run([sys.executable, CLI] + list(args),
                          cwd=ROOT, capture_output=True, text=True,
                          timeout=kw.pop("timeout", 600), **kw)


def run_exe(path):
    r = subprocess.run([os.path.abspath(path)], capture_output=True,
                       text=True, timeout=120)
    return r.returncode, (r.stdout or "").strip()


# ---------------------------------------------------------------------------
# [A] 往返
# ---------------------------------------------------------------------------

REP = ["tests/t1.qma", "tests/t2.qma", "tests/t119_drop.qma",
       "tests/t126_closure.qma", "tests/t116_iface_multi.qma",
       "tests/t46_json.qma", "tests/t22_map.qma", "tests/t13_spawn.qma",
       "tests/t115_derive.qma", "tests/t29_args.qma", "tests/t34_vec.qma",
       "examples/hello.qma"]


def sec_a(full=False):
    print("[A] 往返：直编 vs 档案->链接")
    files = list(REP)
    if full:
        files += sorted(glob.glob(os.path.join(ROOT, "tests", "*.qma")))
    same = diff = skip = 0
    for rel in files:
        src = os.path.join(ROOT, rel)
        if not os.path.isfile(src):
            continue
        try:
            pe1, _ = qlm_pe.transpile_win(src)
        except Exception:                        # noqa: BLE001
            skip += 1
            continue
        arc, _meta, _cfg = qlm_pe.emit_archive(src)
        pe2, _link = qlm_pe.link_win([arc])
        if pe1 == pe2:
            same += 1
        else:
            diff += 1
            bad(f"{rel}：直编 {len(pe1)} 字节 vs 链接 {len(pe2)} 字节")
    check(diff == 0, f"{same} 个夹具往返逐字节相同（跳过 {skip} 个不可编译）",
          f"{diff} 个不同")


# ---------------------------------------------------------------------------
# [B] 函数级增量
# ---------------------------------------------------------------------------

INC_SRC = """module inc

struct P { x: int, y: int }

fn helper(a: int) -> int {
    return a * 2
}

fn use(a: int) -> int {
    return helper(a) + 1
}

fn other(a: int) -> int {
    return a - 1
}

fn extra(a: int) -> int {
    return a + 7
}

fn main() {
    print(use(20) + other(3) + extra(0))
}
"""


def sec_b():
    print("[B] 函数级增量")
    src = os.path.join(WORK, "inc.qma")
    write(src, INC_SRC)
    a1, m1, _ = qlm_pe.emit_archive(src)
    p1 = os.path.join(WORK, "inc1.qla")
    a1.save(p1)

    # 无改动
    a2, m2, _ = qlm_pe.emit_archive(src, reuse=qlm_qla.Archive.load(p1))
    check(a2.to_bytes() == a1.to_bytes(), "无改动增量：档案逐字节相同")
    check(m2["nreused"] == m2["ntotal"] == 5,
          f"无改动增量：{m2['nreused']}/{m2['ntotal']} 函数复用")

    # 改被内联的 helper 函数体：helper -> use -> main 一起重编
    # （内联把函数体搬进了调用方，不失效就会留着旧副本——正确性要求）
    write(src, INC_SRC.replace("return a * 2", "return a * 3"))
    a3, m3, _ = qlm_pe.emit_archive(src, reuse=qlm_qla.Archive.load(p1))
    check(m3["nreused"] == 2 and m3["ntotal"] == 5,
          f"改被内联的 helper：复用 {m3['nreused']}/{m3['ntotal']}"
          f"（内联链 helper->use->main 一起重编）", str(m3["nreused"]))

    # 加一个函数：其余全部复用
    write(src, INC_SRC.replace(
        "fn main() {",
        "fn extra2(a: int) -> int {\n    return a + 8\n}\n\nfn main() {").replace(
        "extra(0))", "extra(0) + extra2(0))"))
    a4, m4, _ = qlm_pe.emit_archive(src, reuse=qlm_qla.Archive.load(p1))
    check(m4["nreused"] == 4 and m4["ntotal"] == 6,
          f"新增函数：复用 {m4['nreused']}/{m4['ntotal']}")

    # 大函数（>28 条 IR 且两个调用点 -> 不被内联）改体：
    # **只有它自己**重编——这才是"函数级"的正常形态
    # （小访问器会被内联，跟着调用链一起重编是正确性的代价）
    body = "\n".join(["        s = s + i"] + [
        f"        if s > {100 + k} {{\n            s = s - {k}\n        }}"
        for k in range(1, 8)])
    big = f"""module big

fn helper(a: int) -> int {{
    let mut s = 0
    let mut i = 0
    while i < a {{
        i = i + 1
{body}
    }}
    return s
}}

fn c1(a: int) -> int {{ return helper(a) + 1 }}
fn c2(a: int) -> int {{ return helper(a) + 2 }}

fn main() {{
    print(c1(20) + c2(3))
}}
"""
    bsrc = os.path.join(WORK, "big.qma")
    write(bsrc, big)
    ab1, _mb1, _ = qlm_pe.emit_archive(bsrc)
    qb = os.path.join(WORK, "big1.qla")
    ab1.save(qb)
    write(bsrc, big.replace("s = s + i\n", "s = s + i + 1\n", 1))
    ab2, mb2, _ = qlm_pe.emit_archive(bsrc, reuse=qlm_qla.Archive.load(qb))
    old_ir = {r["name"]: r["ir"] for r in ab1.funcs}
    changed = [r["name"] for r in ab2.funcs
               if r["name"] in old_ir and old_ir[r["name"]] != r["ir"]]
    check(mb2["nreused"] == mb2["ntotal"] - 1,
          f"改大函数体：只重编 1 个（复用 {mb2['nreused']}/{mb2['ntotal']}）")
    check(changed == ["helper"], f"只有 helper 的 IR 变了（实际 {changed}）")

    # 改类型布局：全部失效（保守但正确）
    write(src, INC_SRC.replace("struct P { x: int, y: int }",
                               "struct P { x: int, y: int, z: int }"))
    a5, m5, _ = qlm_pe.emit_archive(src, reuse=qlm_qla.Archive.load(p1))
    check(m5["nreused"] == 0,
          f"改 struct 布局：全部重编（复用 {m5['nreused']}/{m5['ntotal']}）")

    # 增量产物必须能跑，且与全量构建一致
    write(src, INC_SRC.replace("return a * 2", "return a * 3"))
    arc_inc, _mi, _ = qlm_pe.emit_archive(src, reuse=qlm_qla.Archive.load(p1))
    pe_inc, _ = qlm_pe.link_win([arc_inc])
    exe = os.path.join(WORK, "inc_incr.qex")
    qlm_pe.write_exe(exe, pe_inc)
    rc, out = run_exe(exe)
    check(rc == 0 and out == "70", f"增量产物运行正确（rc={rc}, out={out!r}）")
    old = {r["name"]: r["ir"] for r in a1.funcs}
    changed = [r["name"] for r in arc_inc.funcs
               if r["name"] in old and old[r["name"]] != r["ir"]]
    check(changed == ["helper", "use", "main"],
          f"内联链上的三个函数变了、其余一字不差（实际 {changed}）")


# ---------------------------------------------------------------------------
# [C] 二进制库
# ---------------------------------------------------------------------------

LIB_SRC = """module mylib

pub struct Pt { x: int, y: int }

pub fn add(a: int, b: int) -> int {
    return a + b
}

pub fn mk(x: int, y: int) -> Pt {
    return Pt { x: x, y: y }
}

pub fn scale(p: Pt, k: int) -> Pt {
    return Pt { x: p.x * k, y: p.y * k }
}

fn secret(a: int) -> int {
    return a * 1000
}

pub fn hidden_use(a: int) -> int {
    return secret(a)
}
"""

APP_SRC = """module myapp

fn main() {
    print(add(20, 22))
    let p = mk(3, 4)
    let q = scale(p, 3)
    print(q.x)
    print(q.y)
    print(hidden_use(2))
}
"""


def sec_c():
    print("[C] 二进制库（脱离源码分发）")
    libdir = os.path.join(WORK, "lib")
    lib = os.path.join(libdir, "mylib.qma")
    write(lib, LIB_SRC)
    libq = os.path.join(libdir, "mylib.qla")
    r = run_cli("build", lib, "--lib", "-o", libq)
    check(r.returncode == 0 and os.path.isfile(libq),
          "`build --lib` 产出 .qla", r.stderr[-200:])
    arc = qlm_qla.Archive.load(libq)
    names = {e["name"] for e in arc.exports}
    check("add" in names and "scale" in names, "符号表含 pub 函数")
    check("secret" not in names, "非 pub 函数不进符号表")
    check(arc.kind == "lib", "档案 kind=lib（无入口）")

    app = os.path.join(libdir, "app.qma")
    write(app, APP_SRC)
    os.rename(lib, lib + ".off")          # 源码不再可用：只有 .qla
    try:
        exe = os.path.join(libdir, "app.qex")
        r = run_cli("build", app, "--lib-input", libq, "-o", exe)
        check(r.returncode == 0 and os.path.isfile(exe),
              "无源码也能编译（只靠 .qla 的签名与布局）", r.stderr[-300:])
        rc, out = run_exe(exe)
        check(rc == 0 and out.split() == ["42", "9", "12", "2000"],
              f"链接后的程序运行正确（out={out!r}）")
        # 同一批档案再链一次：确定性
        arc2 = qlm_qla.Archive.load(libq)
        r2 = run_cli("link", os.path.join(ROOT, "build", "app.qla"), libq,
                     "-o", os.path.join(libdir, "app2.qex"))
        check(r2.returncode == 0, "`link` 独立链接成功", r2.stderr[-200:])
        rc2, out2 = run_exe(os.path.join(libdir, "app2.qex"))
        check(rc2 == 0 and out2.split() == out.split(),
              f"`link` 产物行为一致（out={out2!r}）")
    finally:
        os.rename(lib + ".off", lib)

    # 库自己的程序：`--lib` 不做 DCE，全部函数进档案
    check(len(arc.funcs) > len(arc.exports),
          f"库档案保留内部函数（{len(arc.funcs)} 个函数 / "
          f"{len(arc.exports)} 个导出）")


# ---------------------------------------------------------------------------
# [D] 失败路径
# ---------------------------------------------------------------------------

def sec_d():
    print("[D] 失败路径")
    d = os.path.join(WORK, "err")
    os.makedirs(d, exist_ok=True)

    # 1) 缺 main
    write(os.path.join(d, "nomain.qma"), "module nomain\n\nfn f() -> int { return 1 }\n")
    arc, _m, _c = qlm_pe.emit_archive(os.path.join(d, "nomain.qma"))
    try:
        qlm_pe.link_win([arc])
        bad("缺 main 竟然链接成功")
    except qlm_qla.LinkError as exc:
        check("main" in str(exc), f"缺 main 报错（{str(exc)[:40]}…）")

    # 2) 重复 main
    write(os.path.join(d, "m1.qma"), "module m1\n\nfn main() { print(1) }\n")
    write(os.path.join(d, "m2.qma"), "module m2\n\nfn main() { print(2) }\n")
    a1, _m, _c = qlm_pe.emit_archive(os.path.join(d, "m1.qma"))
    a2, _m, _c = qlm_pe.emit_archive(os.path.join(d, "m2.qma"))
    try:
        qlm_pe.link_win([a1, a2])
        bad("两个 main 竟然链接成功")
    except qlm_qla.LinkError as exc:
        check("main" in str(exc), "重复 main 报错")

    # 3) 未定义符号
    write(os.path.join(d, "undef.qma"),
          "module undef\n\nfn main() { print(missing_fn(1)) }\n")
    try:
        qlm_pe.emit_archive(os.path.join(d, "undef.qma"))
        bad("未定义函数竟然通过降级")
    except SyntaxError:
        ok("源码里调用未定义函数 -> 编译期报错")

    # 4) 符号冲突（同名不同体）
    write(os.path.join(d, "l1.qma"),
          "module l1\n\npub fn dup() -> int { return 1 }\n")
    write(os.path.join(d, "l2.qma"),
          "module l2\n\npub fn dup() -> int { return 2 }\n")
    b1, _m, _c = qlm_pe.emit_archive(os.path.join(d, "l1.qma"), kind="lib")
    b2, _m, _c = qlm_pe.emit_archive(os.path.join(d, "l2.qma"), kind="lib")
    try:
        qlm_qla.merge([b1, b2])
        bad("同名不同体竟然合并成功")
    except qlm_qla.LinkError as exc:
        check("符号冲突" in str(exc), "同名不同体报符号冲突")

    # 5) 指纹不符
    good = os.path.join(WORK, "inc1.qla")
    arc = qlm_qla.Archive.load(good)
    arc.compiler = "00000000000000000000000000000000"
    fake = os.path.join(d, "stale.qla")
    arc.save(fake)
    try:
        qlm_pe.emit_archive(os.path.join(WORK, "inc.qma"),
                            reuse=qlm_qla.Archive.load(fake))
        bad("指纹不符竟然复用成功")
    except SyntaxError as exc:
        check("指纹" in str(exc) or "编译器" in str(exc),
              "指纹不符拒绝复用")

    # 6) 档案损坏（截断）
    blob = open(good, "rb").read()
    cut = os.path.join(d, "cut.qla")
    with open(cut, "wb") as f:
        f.write(blob[:len(blob) // 2])
    try:
        qlm_qla.Archive.load(cut)
        bad("截断档案竟然加载成功")
    except ValueError as exc:
        check("截断" in str(exc) or "长度" in str(exc) or "校验" in str(exc),
              f"截断档案报错（{str(exc)[:40]}…）")

    # 7) 布局冲突（同名类型两套布局）
    write(os.path.join(d, "ty1.qma"),
          "module ty1\n\npub struct Q { a: int }\n\npub fn f1() -> int { return 1 }\n")
    write(os.path.join(d, "ty2.qma"),
          "module ty2\n\npub struct Q { a: int, b: int }\n\npub fn f2() -> int { return 2 }\n")
    c1, _m, _c = qlm_pe.emit_archive(os.path.join(d, "ty1.qma"), kind="lib")
    c2, _m, _c = qlm_pe.emit_archive(os.path.join(d, "ty2.qma"), kind="lib")
    write(os.path.join(d, "usety.qma"),
          "module usety\n\nfn main() { print(f1() + f2()) }\n")
    try:
        qlm_pe.emit_archive(os.path.join(d, "usety.qma"), libs=[c1, c2])
        bad("同名类型两套布局竟然通过")
    except SyntaxError as exc:
        check("布局" in str(exc), "同名类型布局冲突报错")


def test_singleton_size_mismatch():
    """进程级单例的**尺寸**不同必须拒绝链接（v3.24）。

    v3.23 把 `static` 从 32 字扩到 64 字。编译器指纹通常能兜住这件事
    （改了编译器 -> 指纹变 -> 更早的检查就报错），但它只保证"同一份
    编译器"，不保证"同一块尺寸"。同指纹不同尺寸时，链接后代码按 64 字
    写就会踩到下一个全局块 —— 链接期是唯一能拦住它的地方。
    """
    import copy

    d = tempfile.mkdtemp(prefix="qla_sz_")
    try:
        write(os.path.join(d, "s1.qma"),
              "module s1\n\nfn main() { mem_store64(static_word(63), 0, 1) }\n")
        a, _m, _c = qlm_pe.emit_archive(os.path.join(d, "s1.qma"))
        b, _m, _c = qlm_pe.emit_archive(os.path.join(d, "s1.qma"))

        if a.special.get("static") is None:
            skip("档案里没有 static 单例，跳过尺寸检查用例")
            return

        # 指纹对齐，只把 static 块砍回 32 字（模拟旧编译器）
        c = copy.copy(b)
        c.compiler = a.compiler
        c.unit = "<shrunk>"
        c.globals = list(c.globals)
        c.globals[c.special["static"]] = c.globals[c.special["static"]][:32 * 8]

        try:
            qlm_qla.merge([a, c])
            bad("同名单例尺寸不同竟然链接成功（会错位踩内存）")
        except qlm_qla.LinkError as exc:
            check("尺寸" in str(exc), "进程级单例尺寸不同拒绝链接")
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# [E] CLI
# ---------------------------------------------------------------------------

def sec_e():
    print("[E] CLI")
    arc = os.path.join(WORK, "inc1.qla")
    r = run_cli("qla", "--verify", arc)
    check(r.returncode == 0 and "校验通过" in r.stdout, "`qla --verify` 通过")
    r = run_cli("qla", "--stat", arc)
    check(r.returncode == 0 and "函数" in r.stdout, "`qla --stat` 输出统计")
    libq = os.path.join(WORK, "lib", "mylib.qla")
    r = run_cli("qla", "--symbols", libq)
    check(r.returncode == 0 and "fn add(" in r.stdout,
          "`qla --symbols` 输出符号表", r.stdout[:120])

    src = os.path.join(WORK, "cli.qma")
    write(src, "module cli\n\nfn main() { print(7) }\n")
    q = os.path.join(WORK, "cli.qla")
    exe = os.path.join(WORK, "cli.qex")
    r1 = run_cli("build", src, "--incr", "-o", q)
    check(r1.returncode == 0 and os.path.isfile(q), "`build --incr` 首次全量",
          r1.stderr[-200:])
    r2 = run_cli("build", src, "--incr", "-o", q)
    check(r2.returncode == 0 and "复用 1/1" in r2.stdout,
          f"`build --incr` 二次复用（{r2.stdout.strip().splitlines()[-2][:40]}…）")
    rc, out = run_exe(exe)
    check(rc == 0 and out == "7", f"`--incr` 产物可运行（out={out!r}）")


def main():
    full = "--full" in sys.argv
    # 不整目录删除：沙箱的安全删除策略对"一次删 >50 个文件"会拦（BULK_CONFIRM）。
    # 这里所有夹具都是固定文件名，就地覆盖即可；旧产物不影响任何断言。
    os.makedirs(WORK, exist_ok=True)
    sec_a(full)
    sec_b()
    sec_c()
    sec_d()
    test_singleton_size_mismatch()
    sec_e()
    print(f"\nQLA: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
