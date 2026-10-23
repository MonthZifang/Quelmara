#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增量编译缓存回归（v1.90）
========================
断言"缓存命中不改变产物、失效条件一条不漏"——缓存出错比慢危险得多：

  1. 冷构建 → 重编；再构建 → 命中；两次产物**逐字节相同**
  2. 改主文件 → 未命中；**改回来 → 命中旧条目**（内容寻址，不是时间戳）
  3. 改被 import 的模块 → 未命中（闭包是精确的，不是"整个仓库"）
  4. 只改一个注释 → 未命中（内容哈希，不是 mtime）
  5. 换优化开关（`--no-opt`）→ 独立条目，各自都能命中
  6. `--no-cache` / `QLM_NO_CACHE=1` → 强制重编且不写条目
  7. 产物被截断 → 判为损坏、重编（不会把半截二进制交出去）
  8. `cache --stat` / `--clear` 行为
  9. 并行 `test -j 4` 与串行 `-j 1` 结果一致（含输出顺序）

跑法：python tests/cache_test.py
"""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")

# 夹具放在 build/ 下：不进库、不污染源码树，且自带 Quelmara.toml 让
# `project_root` 落在夹具自己身上（缓存目录 = 夹具内 .qlmcache）。
PROJ = os.path.join(ROOT, "build", "_cachetest_proj")
CACHE = os.path.join(PROJ, ".qlmcache")

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def setup():
    shutil.rmtree(PROJ, ignore_errors=True)
    os.makedirs(PROJ, exist_ok=True)
    write(os.path.join(PROJ, "Quelmara.toml"), "[build]\nopt = \"speed\"\n")
    write(os.path.join(PROJ, "dep.qma"),
          "module dep\n\npub fn dep_val() -> int {\n    return 41\n}\n")
    write(os.path.join(PROJ, "main.qma"),
          "module main\n\nimport dep\n\nfn main() {\n"
          "    print((dep_val() + 1).to_str())\n}\n")


def build(extra=None, env_extra=None):
    """返回 (stdout+stderr, 产物路径, 是否命中)。"""
    out = os.path.join(PROJ, "main.qex")
    cmd = [sys.executable, CLI, "build", "main.qma", "--target", "win",
           "-o", out] + (extra or [])
    env = dict(os.environ)
    env.pop("QLM_NO_CACHE", None)
    env.update(env_extra or {})
    r = subprocess.run(cmd, cwd=PROJ, capture_output=True, text=True, env=env,
                       timeout=300)
    text = r.stdout + r.stderr
    return text, out, "缓存命中" in text, r.returncode


def sha(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def entries():
    base = os.path.join(CACHE, "entries")
    return sorted(os.listdir(base)) if os.path.isdir(base) else []


def cache_cmd(args):
    r = subprocess.run([sys.executable, CLI, "cache"] + args, cwd=PROJ,
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr, r.returncode


def main():
    setup()

    # ---- 1. 冷 → 热，产物逐字节相同 ----
    text, out, hit, rc = build()
    ok("冷构建成功") if rc == 0 else bad(f"冷构建退出码 {rc}：{text[-200:]}")
    if hit:
        bad("首次构建不该命中")
    else:
        ok("首次构建 = 重编")
    first = sha(out) if os.path.isfile(out) else None

    text, out, hit, rc = build()
    ok("二次构建命中缓存") if hit else bad(f"二次构建未命中：{text[-160:]}")
    ok("命中产物与冷构建逐字节相同") if first and sha(out) == first \
        else bad("命中产物与冷构建不一致")

    # ---- 2. 改主文件 → 失效；改回 → 命中旧条目 ----
    main_qma = os.path.join(PROJ, "main.qma")
    src = open(main_qma, encoding="utf-8").read()
    write(main_qma, src + "\n// 只加一行注释\n")
    text, out, hit, rc = build()
    ok("改主文件 → 未命中") if not hit else bad("改主文件后仍命中")
    ok("改主文件 → 重编成功") if rc == 0 else bad(f"重编失败 {rc}：{text[-200:]}")

    write(main_qma, src)
    text, out, hit, rc = build()
    ok("改回原样 → 命中旧条目（内容寻址）") if hit else \
        bad(f"改回后未命中：{text[-160:]}")

    # ---- 3. 改被 import 的模块 → 失效（闭包精确到文件） ----
    dep = os.path.join(PROJ, "dep.qma")
    dsrc = open(dep, encoding="utf-8").read()
    write(dep, dsrc + "\n// dep 变了\n")
    text, out, hit, rc = build()
    ok("改被 import 的模块 → 未命中") if not hit else bad("改依赖后仍命中")
    ok("依赖改动后重编成功") if rc == 0 else bad(f"依赖改动重编失败 {rc}")
    write(dep, dsrc)

    # ---- 4. 闭包内容：条目里必须有 dep.qma，且不含没 import 的文件 ----
    metas = [json.load(open(os.path.join(CACHE, "entries", e, "meta.json"),
                            encoding="utf-8"))
             for e in entries()
             if os.path.isfile(os.path.join(CACHE, "entries", e, "meta.json"))]
    closed = {rel for m in metas for rel, _sha in m.get("closure", [])}
    ok("闭包含被 import 的 dep.qma") if any(c.endswith("dep.qma") for c in closed) \
        else bad(f"闭包缺 dep.qma：{sorted(closed)[:5]}")
    ok("闭包含主文件 main.qma") if any(c.endswith("main.qma") for c in closed) \
        else bad("闭包缺 main.qma")
    ok("闭包不含未 import 的 std/aes.qma") \
        if not any(c.endswith("std/aes.qma") for c in closed) \
        else bad("闭包混进了没 import 的 std/aes.qma（说明闭包退化成了整个仓库）")

    # ---- 5. 优化开关是独立条目 ----
    text, out, hit, rc = build(["--no-opt"])
    ok("--no-opt 首次 = 重编") if not hit and rc == 0 else bad(f"--no-opt 异常 {rc}")
    text, out, hit, rc = build(["--no-opt"])
    ok("--no-opt 二次命中（与默认开关分开存）") if hit else bad("--no-opt 二次未命中")

    # ---- 6. --no-cache / QLM_NO_CACHE=1 强制重编且不写条目 ----
    n_before = len(entries())
    text, out, hit, rc = build(["--no-cache"])
    ok("--no-cache 不命中") if not hit and "缓存关闭" in text else \
        bad(f"--no-cache 行为不对：{text[-120:]}")
    text, out, hit, rc = build(env_extra={"QLM_NO_CACHE": "1"})
    ok("QLM_NO_CACHE=1 不命中") if not hit else bad("QLM_NO_CACHE=1 仍命中")
    ok("强制重编不新增条目") if len(entries()) == n_before else \
        bad(f"条目数 {n_before} → {len(entries())}")

    # ---- 7. 产物损坏 → 判损坏并重编 ----
    text, out, hit, rc = build()
    # 同一份源可能有多条历史条目（改文件前后各一条），**全都要截断**：
    # 只截一条的话，下一次构建会命中另一条完好条目，测不到损坏检测。
    victims = []
    for e in entries():
        m = json.load(open(os.path.join(CACHE, "entries", e, "meta.json"),
                           encoding="utf-8"))
        if m.get("opt") and not m.get("dbg") and m.get("src") == "main.qma":
            victims.append(os.path.join(CACHE, "entries", e, "artifact"))
    if victims:
        for art in victims:
            with open(art, "r+b") as f:
                f.truncate(16)                 # 半截产物
        text, out, hit, rc = build()
        ok("产物被截断 → 判损坏并重编") if not hit and rc == 0 else \
            bad(f"损坏产物仍被使用：{text[-160:]}")
        ok("重编后产物恢复正常") if sha(out) == first else bad("重编产物与原始不一致")
    else:
        bad("找不到可用来做损坏测试的条目")

    # ---- 8. cache --stat / --clear ----
    text, rc = cache_cmd(["--stat"])
    ok("cache --stat 报告条目数") \
        if rc == 0 and f"条目: {len(entries())} 个" in text else \
        bad(f"--stat 输出异常：{text[-160:]}")
    n = len(entries())
    text, rc = cache_cmd(["--clear"])
    ok("cache --clear 清空") if "已清空" in text and not entries() else \
        bad(f"--clear 未清空（清前 {n} 条）")

    # ---- 9. 并行 == 串行 ----
    pdir = os.path.join(PROJ, "many")
    for i in range(4):
        write(os.path.join(pdir, f"t{i}.qma"),
              f'module t{i}\n\ntest "t{i}" {{\n    assert(1 + 1 == 2)\n}}\n')

    def run_test(jobs):
        r = subprocess.run([sys.executable, CLI, "test", pdir, "--target", "win",
                            "-j", str(jobs)], cwd=PROJ, capture_output=True,
                           text=True, timeout=600)
        lines = [ln for ln in (r.stdout + r.stderr).splitlines()
                 if not ln.startswith("[qlm-test]") and ln.strip()]
        return lines, r.returncode

    seq, rc1 = run_test(1)
    par, rc4 = run_test(4)
    ok("串行与并行输出逐行一致") if seq == par else \
        bad(f"输出不一致：串行 {len(seq)} 行 / 并行 {len(par)} 行")
    ok("并行与串行退出码一致") if rc1 == rc4 else bad(f"{rc1} vs {rc4}")
    ok("并行结果全 PASS") if any("PASS=4" in ln for ln in par) else \
        bad(f"并行结果异常：{par[-3:]}")

    print(f"\nCACHE: PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
