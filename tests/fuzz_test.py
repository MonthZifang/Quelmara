#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模糊测试链路回归（v1.83）
========================
`quelmara fuzz` 的两段：**变异器是 Quelmara 写的**（`tools/qlm_fuzz.qma`），
判定/报告在 `tools/stage0/qlm_fuzz.py`。本测试断言：

  1. 确定性：同 seed 两次生成的用例**逐字节相同**；不同 seed 不同
  2. 变异生效：至少有一例与种子源码不同，且用例数正确
  3. 分类器口径：合法源码 -> built；语法错 -> rejected；
     非 UTF-8 -> bug（编译器读文件时抛 UnicodeDecodeError，属已知缺陷，
     变异器主动避开 ASCII 之外的字节，所以正常 fuzz 不会撞上）
  4. 端到端：`fuzz <种子> --cases 8 --seed 5` 退出码 0 且报"无崩溃"

跑法：python tests/fuzz_test.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
SEED_SRC = os.path.join(ROOT, "fixtures", "dbgdemo", "cov.qma")

sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def gen(out_dir, cases, seed):
    """调变异器生成用例，返回目录路径。"""
    import qlm_cli
    import qlm_fuzz
    qlm_fuzz._gen_cases(SEED_SRC, out_dir, cases, seed, qlm_cli.build)
    return out_dir


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def main():
    import qlm_fuzz

    # ---- 1. 确定性 ----
    d1 = gen(os.path.join("build", "fuzz", "test_a"), 4, 7)
    d2 = gen(os.path.join("build", "fuzz", "test_b"), 4, 7)
    same = all(read_bytes(os.path.join(d1, f"case_{i:04d}.qma"))
               == read_bytes(os.path.join(d2, f"case_{i:04d}.qma"))
               for i in range(4))
    ok("同 seed 两次生成的用例逐字节相同") if same \
        else bad("同 seed 生成结果不确定（不可复现）")

    d3 = gen(os.path.join("build", "fuzz", "test_c"), 4, 8)
    diff = any(read_bytes(os.path.join(d1, f"case_{i:04d}.qma"))
               != read_bytes(os.path.join(d3, f"case_{i:04d}.qma"))
               for i in range(4))
    ok("不同 seed 生成不同用例") if diff else bad("不同 seed 得到同一批用例")

    # ---- 2. 变异生效 + 用例数 ----
    n = len([f for f in os.listdir(d1) if f.endswith(".qma")])
    ok(f"用例数 = 4（实际 {n}）") if n == 4 else bad(f"用例数 {n}，期望 4")
    seed_text = open(SEED_SRC, encoding="utf-8").read()
    mutated = sum(1 for i in range(4)
                  if read_bytes(os.path.join(d1, f"case_{i:04d}.qma"))
                  != seed_text.encode("utf-8"))
    ok(f"4 例全部被改动过（{mutated}/4）") if mutated == 4 \
        else bad(f"只有 {mutated}/4 例与种子不同")

    # 用例必须仍是合法 UTF-8（变异只落在 ASCII 字节上）
    decodable = True
    for i in range(4):
        try:
            read_bytes(os.path.join(d1, f"case_{i:04d}.qma")).decode("utf-8")
        except UnicodeDecodeError:
            decodable = False
    ok("用例全部是合法 UTF-8（变异避开多字节字符）") if decodable \
        else bad("用例出现非法 UTF-8")

    # ---- 3. 分类器口径 ----
    good = os.path.join("build", "fuzz", "cls_ok.qma")
    os.makedirs(os.path.dirname(good), exist_ok=True)
    with open(good, "w", encoding="utf-8") as f:
        f.write("fn main() {\n    print(\"ok\")\n}\n")
    kind, _ = qlm_fuzz._compile_frontend(good)
    ok("合法源码 -> built") if kind == "built" else bad(f"合法源码被判 {kind}")

    bad_src = os.path.join("build", "fuzz", "cls_bad.qma")
    with open(bad_src, "w", encoding="utf-8") as f:
        f.write("fn main() {\n    let x = \n}\n")
    kind, detail = qlm_fuzz._compile_frontend(bad_src)
    ok(f"语法错 -> rejected（{detail[:40]}）") if kind == "rejected" \
        else bad(f"语法错被判 {kind}")

    enc_src = os.path.join("build", "fuzz", "cls_enc.qma")
    with open(enc_src, "wb") as f:
        f.write(b"fn main() {\n    print(\"\xff\xfe\")\n}\n")
    kind, detail = qlm_fuzz._compile_frontend(enc_src)
    ok(f"非 UTF-8 -> bug（{detail.split(':')[0]}）") if kind == "bug" \
        else bad(f"非 UTF-8 被判 {kind}")

    # ---- 4. 端到端 ----
    r = subprocess.run([sys.executable, CLI, "fuzz", SEED_SRC,
                        "--cases", "8", "--seed", "5"],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    out = r.stdout + r.stderr
    ok("端到端退出码 0") if r.returncode == 0 \
        else bad(f"端到端退出码 {r.returncode}：{out[-400:]}")
    for needle, why in (("结果: 无崩溃", "端到端报告无崩溃"),
                        ("用例: 8/8", "端到端跑满 8 例"),
                        ("崩溃 0", "崩溃计数为 0")):
        ok(why) if needle in out else bad(f"{why}（未找到 {needle!r}）")

    print(f"\nFUZZ: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
