#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`std/` 下每个模块都必须能被单独 import 并构建（v3.26）。

## 为什么需要它

标准库有 70 个模块，但"文件在那儿"不等于"能用"：

* 模块里用了**关键字**当标识符（`let rc = ...`，`rc` 是 `rc[T]` 的关键字）
  —— 整个模块连**解析**都过不去；
* 模块跨模块调了对方**没 pub** 的函数 —— 编译期报"引用了非 pub 声明"；
* 模块自己一个 `pub` 都没有 —— 能编译，但**外部一个函数也调不到**。

第三种最隐蔽：`std/ws` 和 `std/sse` 就这么一直"存在"着，
`03-stdlib.md` 里还标着可用，实际谁也用不了。
v2.01 的审计发现过，但当时只修了一部分，这两个一直挂到 v3.26。

## 判据

对每个 `std/**/*.qma` 生成一个只 `import` 它的空程序，编译一次：

1. 编译失败 → FAIL（语法 / 非 pub 引用 / 依赖缺失）
2. 编译通过但**一个 `pub` 都没有** → FAIL（外部调不到）

第 2 条只对"有顶层函数的模块"生效 —— 纯常量 / 类型模块不算。

用法：
    python tools/dev/check_std_import.py          # 判定
    python tools/dev/check_std_import.py -v       # 列出每个模块的 pub 数

退出码：0 = 全部可用 / 1 = 有模块不可用。
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STD = os.path.join(ROOT, "std")
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

# 顶层函数定义（不含缩进）
TOP_FN = re.compile(r"^(?:pub\s+)?fn\s+(\w+)", re.M)
PUB_FN = re.compile(r"^pub\s+fn\s+(\w+)", re.M)


def std_modules():
    out = []
    for base, _dirs, files in os.walk(STD):
        for f in files:
            if f.endswith(".qma"):
                path = os.path.join(base, f)
                rel = os.path.relpath(path, ROOT).replace("\\", "/")
                out.append((rel[:-4].replace("/", "."), rel, path))
    return sorted(out)


def check(verbose=False):
    import qlm_pe

    probe = os.path.join(ROOT, "build", "_std_import_probe.qma")
    fails, ok_n = [], 0

    for mod, rel, path in std_modules():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        nfn = len(TOP_FN.findall(src))
        npub = len(PUB_FN.findall(src))

        with open(probe, "w", encoding="utf-8") as f:
            f.write(f'module _probe\nimport {mod}\nfn main() {{ }}\n')
        try:
            qlm_pe.transpile_win(probe)
        except SyntaxError as e:
            fails.append(f"{rel}: 编译失败 —— {str(e).splitlines()[0][:100]}")
            continue
        except Exception as e:  # noqa: BLE001
            fails.append(f"{rel}: {type(e).__name__} —— {str(e)[:100]}")
            continue

        # 有顶层函数却一个都没导出 -> 外部调不到
        if nfn > 0 and npub == 0:
            fails.append(f"{rel}: 有 {nfn} 个顶层函数但**一个 pub 都没有**"
                         f"（外部调不到）")
            continue

        ok_n += 1
        if verbose:
            print(f"  OK   {rel:<32} 顶层函数 {nfn:>3} / pub {npub:>3}")

    try:
        os.remove(probe)
    except OSError:
        pass
    return ok_n, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    ok_n, fails = check(args.verbose)
    total = ok_n + len(fails)
    if fails:
        print(f"\nstd 模块可用性检查 FAIL（{len(fails)}/{total} 个不可用）：")
        for f in fails:
            print("  -", f)
        print("\n修法：语法错误就改源码；缺 pub 就在对外 API 前加 pub。")
        return 1

    print(f"PASS：{total} 个 std 模块全部可单独 import 并构建，"
          f"且都有 pub 导出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
