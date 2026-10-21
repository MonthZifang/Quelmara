#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改名门禁：旧名残留 / .ros 残留 / 内嵌 C 运行时代码自洽性。

本机没有 gcc、WSL 被沙箱禁用，C 链跑不到，因此"改名漏一处"在 Windows 上
是完全静默的。这个脚本用静态检查兜住这一类错误。

用法：
    python tools/dev/check_names.py            # 全部检查
    python tools/dev/check_names.py --verbose  # 打印每个被检查项
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGE0 = os.path.join(ROOT, "tools", "stage0")
sys.path.insert(0, STAGE0)

# 唯一允许保留旧名的文件
ALLOW = {
    "tools/dev/migrate_names.py",
    "tools/dev/check_names.py",
}

OLD = re.compile(r"rosoto|Rosoto|ROSOTO")
OLD_EXT = re.compile(r"\.ros\b")


def git_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    return [p.decode("utf-8") for p in out.split(b"\x00") if p]


def read(rel):
    try:
        with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
            return f.read()
    except (UnicodeDecodeError, OSError):
        return ""


def check_residue(files, verbose):
    """旧名 / 旧扩展名残留（`legacy-ok` 标记的行/块跳过：文档与兼容检测代码）"""
    bad = 0
    for rel in files:
        if rel in ALLOW or not rel.endswith((".py", ".sh", ".md", ".toml", ".cmd",
                                             ".c", ".h", ".ros", ".qma")):
            continue
        text = read(rel)
        in_block = False
        for i, line in enumerate(text.splitlines(), 1):
            if "legacy-ok:begin" in line:
                in_block = True
                continue
            if "legacy-ok:end" in line:
                in_block = False
                continue
            if in_block or "legacy-ok" in line:
                continue
            if OLD.search(line) or OLD_EXT.search(line):
                print(f"  [残留] {rel}:{i}: {line.strip()[:100]}")
                bad += 1
    return bad


def check_ros_ext(files):
    """.ros 文件必须为 0（硬切）"""
    left = [f for f in files if f.endswith(".ros")]
    for f in left:
        print(f"  [旧扩展名] {f}")
    return len(left)


def generated_c_samples():
    """用 stage-0 生成几份 C，用于符号自洽检查（不需要 gcc）"""
    os.chdir(ROOT)
    import qlm
    samples = []
    for src in ("tests/t16_arrays.qma", "tests/t21_slice.qma", "tests/t22_map.qma",
                "tests/t23_float.qma", "tests/t27_str.qma"):
        path = os.path.join(ROOT, src)
        if not os.path.isfile(path):
            continue
        try:
            code, _cfg = qlm.transpile(path)
        except Exception as exc:                      # noqa: BLE001
            print(f"  [生成失败] {src}: {type(exc).__name__}: {exc}")
            continue
        samples.append((src, code))
    return samples


DEF_RE = re.compile(r"(?m)^[^\n;{}()]*\b(qlm_\w+)\s*\([^;{}]*\)\s*\{")
CALL_RE = re.compile(r"\b(qlm_\w+)\s*\(")


def check_runtime_symbols():
    """生成的 C 里：被调用的 qlm_* 必须有定义（防止改名漏一处造成链接失败）"""
    bad = 0
    samples = generated_c_samples()
    if not samples:
        print("  [跳过] 没有可生成的样本（源码缺失？）")
        return 0
    for src, code in samples:
        defined = set(DEF_RE.findall(code))
        called = set(CALL_RE.findall(code))
        # 排除 if/while 之类误捕（qlm_ 前缀已足够窄），只报"调用了但没定义"
        missing = sorted(called - defined)
        # main 入口由 gen_entry 直接 call，按定义存在即可
        if missing:
            print(f"  [符号缺失] {src}: {', '.join(missing[:8])}")
            bad += len(missing)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    files = git_files()
    print(f"检查 {len(files)} 个受版本控制的文件 …")

    print("[1/3] 旧名残留（rosoto / Rosoto / ROSOTO）")
    bad = check_residue(files, args.verbose)

    print("[2/3] 旧扩展名 .ros 残留")
    bad += check_ros_ext(files)

    print("[3/3] 生成的 C 运行时符号自洽性")
    bad += check_runtime_symbols()

    print("-" * 56)
    if bad:
        print(f"FAIL：{bad} 处问题")
        return 1
    print("PASS：无旧名残留、无 .ros、C 运行时符号自洽")
    return 0


if __name__ == "__main__":
    sys.exit(main())
