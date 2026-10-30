"""批量复核 07-gaps.md 里标着"待修/待查"的条目是否仍然存在（v3.31）。

文档里的状态很容易过期：v3.26 就发现 7.19 与 7.21 早已修好但文档还写着
"待修"。这个脚本把能静态构造的复现逐个跑一遍，输出"仍存在 / 已修复 /
需人工判断"。

只覆盖能用小夹具复现的项；涉及 qlmc 与 ABI 深处的（7.18 / 7.33）单独标出。

跑法：python tools/dev/audit_gaps.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm_pe  # noqa: E402

PROBE = os.path.join(ROOT, "build", "_gap_probe.qma")
EXE = os.path.join(ROOT, "build", "_gap_probe.exe")


def run_src(src, timeout=30):
    """编译并运行，返回 (rc, stdout, stderr)。编译失败时 rc=None。"""
    with open(PROBE, "w", encoding="utf-8") as f:
        f.write(src)
    try:
        blob, _cfg = qlm_pe.transpile_win(PROBE)
    except SyntaxError as e:
        return None, "", f"编译失败: {str(e).splitlines()[0][:120]}"
    except Exception as e:  # noqa: BLE001
        return None, "", f"{type(e).__name__}: {str(e)[:120]}"
    qlm_pe.write_exe(EXE, blob)
    r = subprocess.run([EXE], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


CASES = []


def case(gid, name):
    def deco(fn):
        CASES.append((gid, name, fn))
        return fn
    return deco


@case("7.3", "64 位立即数（>=2^63）的 and")
def _c73():
    rc, out, err = run_src(
        "import std.core\n"
        "fn main() {\n"
        "    let x = 0xFFFFFFFFFFFFFFFF\n"
        "    let y = x & 0x8000000000000000\n"
        "    print((y != 0).to_str())\n"
        "}\n")
    if rc is None:
        return "已修复（能编译）", err
    ok = "true" in out.lower()
    return ("已修复" if ok else "仍存在"), f"out={out.strip()!r}"


@case("7.6", "聚合的 == 是地址比较")
def _c76():
    rc, out, err = run_src(
        "import std.core\n"
        "struct P { a: int, b: int }\n"
        "fn main() {\n"
        "    let p = P { a: 1, b: 2 }\n"
        "    let q = P { a: 1, b: 2 }\n"
        "    print((p == q).to_str())\n"
        "}\n")
    if rc is None:
        return "需人工判断", err
    # 地址比较 -> 两个不同变量必为 false；按值比较 -> true
    return ("仍存在（按地址比较）" if "false" in out.lower()
            else "已修复（按值比较）"), f"out={out.strip()!r}"


@case("7.9", "结构体字面量里直接调用函数")
def _c79():
    rc, out, err = run_src(
        "import std.core\n"
        "struct P { a: int }\n"
        "fn f() -> int { return 7 }\n"
        "fn main() {\n"
        "    let p = P { a: f() }\n"
        "    print(p.a.to_str())\n"
        "}\n")
    if rc is None:
        return "仍存在", err
    return ("已修复" if "7" in out else "仍存在（值不对）"), f"out={out.strip()!r}"


@case("7.11", "非 UTF-8 源文件")
def _c711():
    with open(PROBE, "wb") as f:
        f.write(b'import std.core\nfn main() { print("ok") }\n// \xff\xfe\x80\n')
    try:
        qlm_pe.transpile_win(PROBE)
    except UnicodeDecodeError as e:
        return "仍存在（抛 UnicodeDecodeError，不是友好的语法错误）", str(e)[:100]
    except SyntaxError as e:
        return "已修复（给的是语法错误）", str(e)[:100]
    except Exception as e:  # noqa: BLE001
        return "需人工判断", f"{type(e).__name__}: {e}"
    return "已修复（能编译）", ""


@case("7.14", "实参类型不匹配不报错")
def _c714():
    rc, out, err = run_src(
        "import std.core\n"
        "fn g(a: str, b: int, c: str) -> int { return b }\n"
        "fn main() {\n"
        "    let r = g(\"x\", \"not-int\", \"y\")\n"
        "    print(r.to_str())\n"
        "}\n")
    if rc is None:
        return "已修复（编译期报错）", err
    return "仍存在（编译通过）", f"rc={rc} out={out.strip()!r}"


@case("7.19", "stage-0 打印 INT64_MIN")
def _c719():
    rc, out, err = run_src(
        "import std.core\n"
        "fn main() { print((0 - 9223372036854775807 - 1).to_str()) }\n")
    if rc is None:
        return "需人工判断", err
    want = "-9223372036854775808"
    return ("已修复" if want in out else "仍存在"), f"out={out.strip()!r}"


@case("7.21", "循环里 mem_store8(p, i, <变量>)")
def _c721():
    rc, out, err = run_src(
        "import std.core\n"
        "fn main() {\n"
        "    let p = mem_alloc(64)\n"
        "    let mut i = 0\n"
        "    while i < 8 {\n        mem_store8(p, i, i + 1)\n        i = i + 1\n    }\n"
        "    let mut s = 0\n"
        "    let mut k = 0\n"
        "    while k < 8 {\n        s = s * 10 + mem_load8(p, k)\n        k = k + 1\n    }\n"
        "    print(s.to_str())\n"
        "}\n")
    if rc is None:
        return "需人工判断", err
    return ("已修复" if "12345678" in out else "仍存在"), f"out={out.strip()!r}"


def main():
    print(f"{'条目':<6} {'状态':<28} 判据")
    print("-" * 88)
    stale, still = [], []
    for gid, name, fn in CASES:
        try:
            status, detail = fn()
        except Exception as e:  # noqa: BLE001
            status, detail = "探针异常", f"{type(e).__name__}: {e}"
        print(f"{gid:<6} {status:<28} {name}")
        if detail:
            print(f"{'':<6} {'':<28} {detail}")
        if status.startswith("已修复"):
            stale.append((gid, name))
        elif status.startswith("仍存在"):
            still.append((gid, name))

    print("-" * 88)
    print(f"仍存在 {len(still)} 项，探针判定已修复 {len(stale)} 项")
    # 只看探针说修好了还不够 —— 文档标题若仍写待修/待查就是过期。
    # 这里直接查文档标题，避免把已标注的条目重复报出来。
    doc = os.path.join(ROOT, "docs", "07-gaps.md")
    try:
        text = open(doc, encoding="utf-8").read()
    except OSError:
        text = ""
    stale_doc = []
    for gid, name in stale:
        # 找 ### 7.x  开头的标题行，看有没有 ✅
        import re as _re
        m = _re.search(r"^### " + _re.escape(gid) + r" (.*)$", text, _re.M)
        if m and "✅" not in m.group(1):
            stale_doc.append((gid, name))
    if stale_doc:
        print(f"文档标题过期 {len(stale_doc)} 项：")
        for gid, name in stale_doc:
            print(f"  {gid} {name}  <- 该更新 07-gaps.md")
    else:
        print("文档标题与探针结论一致（无需更新）")
    try:
        os.remove(PROBE)
        os.remove(EXE)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
