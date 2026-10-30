#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""源文件编码错误与编译诊断出口（v3.32，收 07-gaps §7.11）。

## 两件事

### 1. 非 UTF-8 源文件要给友好诊断

以前抛裸的 `UnicodeDecodeError`：

    'utf-8' codec can't decode byte 0xff in position 45: invalid start byte

没有文件名、没有行号、不是 `SyntaxError`、`position 45` 还是**字节偏移**
不是行列。多文件构建时用户根本不知道是哪个文件。

现在给：

    bad.qma:3:4: 源文件不是合法的 UTF-8（字节 0xff 无法解码）。
    常见原因：编辑器按 GBK/ANSI 保存，或存成了 UTF-16。请转成 UTF-8（无 BOM）。

### 2. CLI 不再打 traceback

单源构建路径（`cmd_build -> build()`）不捕获 `SyntaxError`，用户看到的
是整段 Python traceback，真正的诊断埋在最后一行。多源并行路径
（`_build_unit`）反而捕得干净 —— "单源比多源难读"没道理。

现在统一在 `main()` 出口处理：只捕 `SyntaxError`（语言层编译错误，
预期内），其它异常仍带 traceback 抛出（那是编译器自己的 bug）。

## 判据

* 非 UTF-8 -> `SyntaxError`，消息含**文件名**与 `行:列`；
* 带 BOM 的文件**能正常编译运行**（BOM 不该让词法器报"非法字符"）；
* CLI 对四类编译错误都输出**一行**诊断、退出码 1、**无 traceback**；
* 正常程序退出码 0、无 traceback。

跑法：python tests/encoding_diag_test.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

import qlm_pe  # noqa: E402

BUILD = os.path.join(ROOT, "build")
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def write_bytes(name, data):
    os.makedirs(BUILD, exist_ok=True)
    p = os.path.join(BUILD, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def main():
    print("== 源文件编码诊断 ==")

    # ---- [1] 非 UTF-8：必须是 SyntaxError，且带文件名与行列 ----
    p = write_bytes("enc_bad.qma",
                    b'import std.core\nfn main() { print("x") }\n// \xc3\x28\n')
    try:
        qlm_pe.transpile_win(p)
        bad("非 UTF-8 文件竟然编译通过")
    except SyntaxError as e:
        msg = str(e)
        has_name = "enc_bad.qma" in msg
        has_pos = ":3:" in msg          # 第 3 行
        ok(f"非 UTF-8 -> SyntaxError（含文件名={has_name} 行列={has_pos}）") \
            if has_name and has_pos else bad(f"诊断缺信息：{msg[:120]}")
    except UnicodeDecodeError as e:
        bad(f"仍抛裸 UnicodeDecodeError：{e}")
    except Exception as e:  # noqa: BLE001
        bad(f"抛了 {type(e).__name__}：{e}")

    # ---- [2] 带 BOM 的文件必须能编译并运行 ----
    p = write_bytes("enc_bom.qma",
                    b'\xef\xbb\xbfimport std.core\nfn main() { print("bom ok") }\n')
    try:
        blob, _cfg = qlm_pe.transpile_win(p)
        exe = os.path.join(BUILD, "enc_bom.exe")
        qlm_pe.write_exe(exe, blob)
        r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and "bom ok" in r.stdout:
            ok("带 BOM 的源文件能正常编译运行")
        else:
            bad(f"BOM 文件运行异常 rc={r.returncode} out={r.stdout!r}")
    except SyntaxError as e:
        bad(f"BOM 文件编译失败（BOM 应被剥掉）：{str(e)[:120]}")

    # ---- [3] CLI：四类编译错误都要一行诊断、无 traceback ----
    cases = [
        ("语法错误", "fn main( { }"),
        ("未定义函数", "fn main() { nosuchfn() }"),
        ("类型不匹配",
         'fn g(a: int) -> int { return a }\n'
         'fn main() { print(g("s").to_str()) }'),
    ]
    for label, src in cases:
        sp = os.path.join(BUILD, "enc_cli.qma")
        with open(sp, "w", encoding="utf-8") as f:
            f.write(src)
        r = subprocess.run([sys.executable, CLI, "build", sp,
                            "--target", "win", "-o",
                            os.path.join(BUILD, "enc_cli.exe")],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 1:
            bad(f"CLI {label}：退出码 {r.returncode}（期望 1）")
        elif "Traceback" in r.stderr:
            bad(f"CLI {label}：仍打 traceback")
        elif "编译错误" not in r.stderr:
            bad(f"CLI {label}：诊断格式不对：{r.stderr.strip()[:100]}")
        else:
            ok(f"CLI {label}：一行诊断、无 traceback、退出码 1")

    # ---- [4] 正常程序：退出码 0、无 traceback ----
    sp = os.path.join(BUILD, "enc_ok.qma")
    with open(sp, "w", encoding="utf-8") as f:
        f.write('fn main() { print("fine") }\n')
    r = subprocess.run([sys.executable, CLI, "build", sp,
                        "--target", "win", "-o",
                        os.path.join(BUILD, "enc_ok.exe")],
                       capture_output=True, text=True, timeout=180)
    if r.returncode == 0 and "Traceback" not in r.stderr:
        ok("正常程序：退出码 0、无 traceback")
    else:
        bad(f"正常程序 rc={r.returncode} stderr={r.stderr[-200:]!r}")

    print(f"\nENCODING_DIAG: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
