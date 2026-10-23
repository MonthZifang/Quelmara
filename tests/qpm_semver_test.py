#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qpm semver 单测 + qpm install 端到端（v1.45）。

单测（纯函数，无网络无 git）：
  * 版本解析/比较（semver.org §11 全序链、build 不参与、非法输入报错）
  * 区间展开与求值（^ ~ 比较符 通配段 AND/OR、预发布门槛）
  * max_satisfying / select_tag

端到端（file:// 本地 git，离线）：
  * fixtures/qpm-demo 是真 git 仓库（tag v1.0.0 / v1.0.1；.git 不入库，
    缺失时本测试按 .gitignore 注释"演示时重建"自愈重建）
  * build/_qpm_semver_e2e/ 下建临时项目，`python tools/qpm.py install`
    断言锁文件解析到的 tag、.qpm/deps 布局、无满足 tag 时 fail-fast

用法：
    python tests/qpm_semver_test.py
    python tests/qpm_semver_test.py -v
    QPM_E2E_KEEP=1 python tests/qpm_semver_test.py   # 保留端到端临时目录
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "tools"))
import qpm_semver  # noqa: E402

DEMO = os.path.join(ROOT, "fixtures", "qpm-demo")
DEMO_URL = "file:///" + DEMO.replace("\\", "/")
WORK = os.path.join(ROOT, "build", "_qpm_semver_e2e")

VERBOSE = False
FAILS = []


def check(cond, label, detail=""):
    if cond:
        if VERBOSE:
            print(f"  ok   {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


def unit():
    print("== 单测：版本解析与比较 ==")
    V = qpm_semver.Version
    # semver.org §11 的全序链
    chain = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
             "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
    vs = [qpm_semver.parse_version(s) for s in chain]
    check(all(vs[i] < vs[i + 1] for i in range(len(vs) - 1)),
          "§11 全序链", "、".join(str(v) for v in vs))
    check(qpm_semver.parse_version("1.0.0+a") == qpm_semver.parse_version("1.0.0+b"),
          "build 不参与比较")
    check(qpm_semver.parse_version("v2.3.4").major == 2, "v 前缀可省")
    for bad in ["1.2", "1.2.3.4", "v1.2.x", "abc", "1.2.3-", "", "01.2.3"]:
        try:
            qpm_semver.parse_version(bad)
            check(False, f"非法版本 {bad!r} 必须报错")
        except qpm_semver.SemverError:
            check(True, f"非法版本 {bad!r} 报错") if VERBOSE else None
    check(qpm_semver.parse_tag("v1.0.0") is not None
          and qpm_semver.parse_tag("nightly") is None
          and qpm_semver.parse_tag("pkg-v1.2.3") is None
          and qpm_semver.parse_tag("v1.0") is None,
          "parse_tag：只认完整三段式（可选 v 前缀）")

    print("== 单测：区间求值 ==")
    cases = [
        # (version, range, expect)
        ("1.2.3", "^1.2.3", True), ("2.0.0", "^1.2.3", False),
        ("1.9.9", "^1.2.3", True),
        ("0.2.3", "^0.2.3", True), ("0.3.0", "^0.2.3", False),
        ("0.0.3", "^0.0.3", True), ("0.0.4", "^0.0.3", False),
        ("1.2.9", "~1.2.3", True), ("1.3.0", "~1.2.3", False),
        ("1.2.3", "~1.2", True), ("1.3.0", "~1.2", False),
        ("1.9.9", "~1", True), ("2.0.0", "~1", False),
        ("1.2.0", ">=1.2", True), ("1.1.9", ">=1.2", False),
        ("1.3.0", ">1.2", True), ("1.2.9", ">1.2", False),
        ("1.1.9", "<1.2", True), ("1.2.0", "<1.2", False),
        ("1.2.9", "<=1.2", True), ("1.3.0", "<=1.2", False),
        ("1.2.5", "1.2.x", True), ("1.3.0", "1.2.x", False),
        ("1.9.9", "1.*", True), ("2.0.0", "1.*", False),
        ("1.5.0", ">=1.0.0, <2.0.0", True), ("2.0.0", ">=1.0.0, <2.0.0", False),
        ("1.5.0", ">=1.0.0 <2.0.0", True),
        ("2.5.0", "^1 || ^2", True), ("3.0.0", "^1 || ^2", False),
        ("1.2.3", "1.2.3", True), ("1.2.4", "1.2.3", False),
        ("5.0.0", "*", True),
        # 预发布门槛
        ("2.0.0-rc1", "^1.2.3", False), ("1.0.0-rc1", "*", False),
        ("1.2.3-rc1", "^1.2.3-rc1", True), ("1.2.4", "^1.2.3-rc1", True),
        ("1.2.3-rc2", ">=1.2.3-rc1, <1.2.4", True),
        ("1.2.3-rc1", ">=1.2.3-rc2, <1.2.4", False),
    ]
    for ver, rng, expect in cases:
        got = qpm_semver.satisfies(ver, rng)
        check(got == expect, f"satisfies({ver!r}, {rng!r}) == {expect}",
              f"实得 {got}")
    for bad in ["^1.2.3.4", ">=", ">=x", "1.2.3-", "~x", "^ *bad*"]:
        try:
            qpm_semver.satisfies("1.0.0", bad)
            check(False, f"非法区间 {bad!r} 必须报错")
        except qpm_semver.SemverError:
            check(True, f"非法区间 {bad!r} 报错") if VERBOSE else None

    print("== 单测：max_satisfying / select_tag ==")
    pool = ["1.0.0", "1.2.0", "1.9.9", "2.0.0"]
    check(str(qpm_semver.max_satisfying(pool, "^1")) == "1.9.9", "max ^1")
    check(str(qpm_semver.max_satisfying(pool, "*")) == "2.0.0", "max *")
    check(qpm_semver.max_satisfying(pool, "^3") is None, "max 无满足 → None")
    tags = ["v1.0.0", "v1.0.1", "v1.1.0-rc1", "nightly"]
    sel = qpm_semver.select_tag(tags, "^1.0.0")
    check(sel == ("v1.0.1", qpm_semver.parse_version("1.0.1")),
          "select_tag：^1.0.0 → v1.0.1（预发布与杂 tag 排除）", f"实得 {sel}")
    check(qpm_semver.select_tag(tags, "^9") is None, "select_tag 无满足 → None")


def _git(args, cwd):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"测试夹具 git {args} 失败：\n{r.stderr}")


def ensure_demo_repo():
    """fixtures/qpm-demo 的 .git 不入库（.gitignore：演示时重建）——缺失则重建。"""
    if os.path.isdir(os.path.join(DEMO, ".git")):
        return
    os.makedirs(DEMO, exist_ok=True)
    hello = os.path.join(DEMO, "hello.qma")
    if not os.path.isfile(hello):
        with open(hello, "w", encoding="utf-8") as f:
            f.write("module pkg_demo\n\npub fn greet() -> str {\n"
                    "    return \"hello from pkg_demo\"\n}\n")
    _git(["init", "-q"], DEMO)
    _git(["add", "-A"], DEMO)
    _git(["-c", "user.email=qpm@local", "-c", "user.name=qpm",
          "commit", "-q", "-m", "init"], DEMO)
    _git(["tag", "v1.0.0"], DEMO)
    with open(hello, "a", encoding="utf-8") as f:
        f.write("\npub fn greet2() -> str {\n    return \"v2\"\n}\n")
    _git(["add", "-A"], DEMO)
    _git(["-c", "user.email=qpm@local", "-c", "user.name=qpm",
          "commit", "-q", "-m", "bump"], DEMO)
    _git(["tag", "v1.0.1"], DEMO)


def e2e():
    print("== 端到端：qpm install（file:// 本地 git）==")
    ensure_demo_repo()
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    home = os.path.join(WORK, "home")          # 隔离 ~/.qpm 全局缓存
    os.makedirs(home)
    env = dict(os.environ, HOME=home, USERPROFILE=home)

    def install(spec):
        with open(os.path.join(WORK, "Quelmara.toml"), "w", encoding="utf-8") as f:
            f.write("[deps]\n")
            f.write(f'pkg_demo = "{spec}"\n')
        return subprocess.run(
            [PY, os.path.join(ROOT, "tools", "qpm.py"), "install"],
            cwd=WORK, env=env, capture_output=True, text=True)

    def locked_tag():
        with open(os.path.join(WORK, ".qpm", "lock.toml"), encoding="utf-8") as f:
            m = re.search(r'pkg_demo = "git\|[^|]*\|([^|]*)\|', f.read())
        return m.group(1) if m else None

    def dep_ok():
        # 两个 tag 的布局不同（v1.0.0 在 pkg_demo/ 下，v1.0.1 在根），
        # 断言放宽为"副本里有 .qma 源文件"。
        d = os.path.join(WORK, ".qpm", "deps", "pkg_demo")
        return os.path.isdir(d) and any(
            f.endswith(".qma") for _r, _d, fs in os.walk(d) for f in fs)

    for spec, want in [
            (f"{DEMO_URL}#^1.0.0", "v1.0.1"),
            (f"{DEMO_URL}#~1.0.0", "v1.0.1"),
            (f"{DEMO_URL}#<1.0.1", "v1.0.0"),
            (f"{DEMO_URL}#1.0.x", "v1.0.1"),
            (f"{DEMO_URL}#>=1.0.0", "v1.0.1"),
            (f"git:{DEMO_URL}#^1.0.0", "v1.0.1")]:
        r = install(spec)
        ok = r.returncode == 0 and locked_tag() == want and dep_ok()
        check(ok, f"{spec} → {want}",
              f"rc={r.returncode} lock={locked_tag()} dep={dep_ok()} "
              f"err={r.stderr.strip()[:160]}")

    r = install(f"{DEMO_URL}#^2.0.0")
    check(r.returncode != 0 and "区间" in (r.stderr + r.stdout),
          "无满足 tag 的区间 fail-fast 且报出区间信息",
          f"rc={r.returncode} out={r.stderr.strip()[:160]}")

    # path: 前缀（修 05-toolchain 文档与 v0 实现的不一致）
    libdir = os.path.join(WORK, "mylib")
    os.makedirs(libdir)
    with open(os.path.join(libdir, "util.qma"), "w", encoding="utf-8") as f:
        f.write("module mylib\n\npub fn one() -> int {\n    return 1\n}\n")
    r = install("path:./mylib")
    check(r.returncode == 0
          and os.path.isfile(os.path.join(WORK, ".qpm", "deps", "pkg_demo",
                                          "util.qma")),
          "path: 前缀依赖", f"rc={r.returncode} err={r.stderr.strip()[:160]}")


def main():
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    VERBOSE = args.verbose
    unit()
    e2e()
    print("-" * 56)
    if FAILS:
        print(f"FAIL：{len(FAILS)} 项")
        for f in FAILS:
            print(f"  - {f}")
        rc = 1
    else:
        print("PASS：qpm semver 单测 + 端到端全绿")
        rc = 0
    if not os.environ.get("QPM_E2E_KEEP") and os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
