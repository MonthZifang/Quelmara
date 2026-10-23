#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
覆盖率链路回归（v1.83：行 + 分支 + 函数级 + 增量合并）
=====================================================
`quelmara cov` 三段：`--dbg-info` 构建 → 调试器采集 → **Quelmara 写的
`tools/qlm_cov.qma`** 汇总。本测试只驱动命令行，断言报告数字、门禁与合并语义：

  1. `cov.qma`：5 行里 4 行、2 条边里 1 条；未覆盖行/分支都要点名
  2. `main.qma`：行与分支都 100%
  3. 行阈值门禁：`--min 90` 退出码 1
  4. 分支阈值门禁：`--min 70 --min-branch 90` 退出码 1（行达标、分支不达标）
  5. **增量合并**：`cov2.qma` 不带参数只走 else（75% 行 / 50% 分支），
     `--append -- 20` 累加第二次运行后应到 100% / 100%
  6. `--lines-only`：不下分支断点，分支显示 0/0 (—)

跑法：python tests/cov_test.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
HITS = os.path.join("build", "cov_test.tsv")

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def want(out, needle, why):
    ok(why) if needle in out else bad(f"{why}（未找到 {needle!r}）")


def want_rc(r, want_code, why):
    ok(why) if r.returncode == want_code \
        else bad(f"{why}（退出码 {r.returncode}，期望 {want_code}）")


def cov(src, extra=None):
    cmd = [sys.executable, CLI, "cov", src, "--hits", HITS] + (extra or [])
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          timeout=900)


def main():
    if os.name != "nt":
        print("  [SKIP] 覆盖率链路依赖 Windows 调试 API")
        return 0

    # ---- 1. 有未执行分支：行与分支都要检出 ----
    r = cov("fixtures/dbgdemo/cov.qma")
    out = r.stdout + r.stderr
    want(out, "行:   4/5 (80.0%)", "cov.qma：5 行里 4 行覆盖")
    want(out, "分支: 1/2 (50.0%)", "cov.qma：2 条边里 1 条（if 只走了 else）")
    want(out, "未覆盖行: 9", "cov.qma：`return 1` 那行（第 9 行）被列出")
    want(out, "未覆盖分支: 8->9", "cov.qma：第 8 行的 then 边（8->9）被列出")
    want_rc(r, 0, "默认阈值 80% 达标")

    # ---- 2. 函数级汇总 ----
    want(out, "pick", "cov.qma：函数级有 pick 行")
    want(out, "行 2/3 (66.7%)", "cov.qma：pick 的行覆盖 2/3 单独统计")
    want(out, "分支 1/2 (50.0%)", "cov.qma：pick 的分支覆盖单独统计")

    # ---- 3. 全走到 ----
    r = cov("fixtures/dbgdemo/main.qma")
    out = r.stdout + r.stderr
    want(out, "行:   24/24 (100.0%)", "main.qma：全部行覆盖")
    want(out, "分支: 2/2 (100.0%)", "main.qma：全部分支覆盖")
    want(out, "未覆盖行: （无）", "main.qma：无未覆盖行")
    want(out, "未覆盖分支: （无）", "main.qma：无未覆盖分支")

    # ---- 4. 行阈值当门禁 ----
    r = cov("fixtures/dbgdemo/cov.qma", ["--min", "90"])
    out = r.stdout + r.stderr
    want(out, "低于阈值 90%（行）", "--min 90：行不达标")
    want_rc(r, 1, "行不达标时退出码 1")

    # ---- 5. 分支阈值当门禁（行达标、分支不达标）----
    r = cov("fixtures/dbgdemo/cov2.qma", ["--min", "70", "--min-branch", "90"])
    out = r.stdout + r.stderr
    want(out, "低于分支阈值 90%", "--min-branch 90：分支不达标")
    want_rc(r, 1, "分支不达标时退出码 1")

    # ---- 6. 增量合并：两次运行的命中累加 ----
    r = cov("fixtures/dbgdemo/cov2.qma")          # 不带参数：只走 else
    out = r.stdout + r.stderr
    want(out, "行:   6/8 (75.0%)", "cov2 第一次：75% 行")
    want(out, "分支: 2/4 (50.0%)", "cov2 第一次：50% 分支")
    r = cov("fixtures/dbgdemo/cov2.qma", ["--append", "--", "20"])
    out = r.stdout + r.stderr
    want(out, "行:   8/8 (100.0%)", "cov2 累加第二次（n=20）后行覆盖 100%")
    want(out, "分支: 4/4 (100.0%)", "cov2 累加后分支覆盖 100%")
    want(out, "合并:", "cov2：报告了合并落盘（--merge-out）")

    # ---- 7. 只采行覆盖 ----
    r = cov("fixtures/dbgdemo/cov.qma", ["--lines-only"])
    out = r.stdout + r.stderr
    want(out, "分支: 0/0 (—)", "--lines-only：分支显示 0/0（不是 0%）")
    want(out, "行:   4/5 (80.0%)", "--lines-only：行覆盖不受影响")

    print(f"\nCOVERAGE: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
