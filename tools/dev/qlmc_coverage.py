#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage-1 编译器（qlmc）对 `std/` 的覆盖率门禁（v3.37）。

## 为什么要这个

用户的要求是"`tools/stage0/*.py` 里的编译器核心全部改用自研语言"。
那件事的进度不能靠感觉，得有一个**会变的数字**。

最硬的指标是：**qlmc 能编译多少个 `std/` 模块**。它不是"能跑 hello
world"，而是"能不能吃下真实的标准库代码"——里面有 map / vec / 切片 /
闭包 / @ffi / 复杂控制流，是最诚实的检验。

## 判据

用 `qlmc build <mod> -lib -o /tmp/x.exe` 逐个编译 `std/**/*.qma`：

* 成功 -> 计入覆盖
* 失败 -> 记录原因（分类统计）

然后与 `BASELINE` 比较：

* 低于基线 -> **FAIL**（退化了）
* 等于基线 -> PASS
* 高于基线 -> PASS，并提示"该上调 BASELINE 了"

基线数字是**下限**，不是目标 —— 它的作用是防止"改坏了没人发现"。
提升覆盖率时把 BASELINE 一起上调（这是有意的摩擦：让人看见进步）。

用法：
    python tools/dev/qlmc_coverage.py            # 判定
    python tools/dev/qlmc_coverage.py -v         # 列出每个失败模块
    python tools/dev/qlmc_coverage.py --no-baseline  # 只看数字不判定

退出码：0 = 达到或超过基线 / 1 = 低于基线。
"""
import argparse
import collections
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "stage0"))

# 覆盖率下限。**只许上调，不许下调** —— 下调等于承认退化。
# v3.36: 0   （只有 program 模式，30 个模块卡在"没有 main"）
# v3.37: 37  （加了 -lib 模式 + mem_chr / str_from_mem 内建）
# v3.38: 39  （加 mem_diff / mem_xchg）
# v3.39: 43  （加 vec.pop()）
# v3.40: 44  （加 str_ptr / target_arch）
# v3.42: 45  （加 tcp_listen / tcp_accept / tcp_send / tcp_send_n / tcp_recv /
#              tcp_close —— ws2_32 的 IAT 槽位 + sockaddr_in 构造）
# v3.43: 46  （加 tcp_peer_raw —— getpeername + 20 字节视图）
BASELINE = 46

QLMC_SRC = "bootstrap/qlmc/qlmc.qma"
QLMC_EXE = os.path.join("build", "_qlmc_cov.exe")
OUT_EXE = os.path.join("build", "_qlmc_cov_out.exe")


def build_qlmc():
    import qlm_pe
    blob, _cfg = qlm_pe.transpile_win(QLMC_SRC)
    qlm_pe.write_exe(QLMC_EXE, blob)
    return os.path.abspath(QLMC_EXE)


def classify(msg):
    """把失败原因归到有限的几类，便于看趋势。"""
    if "未定义函数" in msg:
        return "缺内建: " + msg.split("未定义函数")[-1].strip()
    if "没有 main" in msg:
        return "没有 main（lib 模式也没解决）"
    if "vec 元素不支持嵌套" in msg:
        return "vec[vec[T]] 类型码撞区间（§7.18）"
    if "只支持 .push" in msg:
        return "vec 方法不全"
    if "const 初值" in msg:
        return "const 常量表达式"
    if "期望标点" in msg or "期望" in msg:
        return "语法子集缺口"
    if "未知类型" in msg:
        return "类型解析"
    return msg[:60]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--no-baseline", action="store_true")
    args = ap.parse_args()

    exe = build_qlmc()
    mods = sorted(glob.glob("std/**/*.qma", recursive=True))
    if not mods:
        print("FAIL：找不到 std/**/*.qma")
        return 1

    ok, fails = 0, []
    for m in mods:
        r = subprocess.run([exe, "build", m, "-lib", "-o", OUT_EXE],
                           capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            ok += 1
        else:
            last = (r.stdout + r.stderr).strip().splitlines()
            fails.append((m, last[-1] if last else "（无输出）"))

    total = len(mods)
    print(f"qlmc 覆盖 std/: {ok} / {total}")
    if fails:
        kinds = collections.Counter(classify(msg) for _m, msg in fails)
        print("失败原因分布：")
        for k, v in kinds.most_common():
            print(f"  {v:>3}  {k}")
        if args.verbose:
            print("\n逐模块：")
            for m, msg in fails:
                print(f"  {m}: {msg[:90]}")

    if args.no_baseline:
        return 0
    if ok < BASELINE:
        print(f"\nFAIL：覆盖率 {ok} 低于基线 {BASELINE}（退化了）")
        return 1
    if ok > BASELINE:
        print(f"\nPASS：覆盖率 {ok} 高于基线 {BASELINE} —— "
              f"该把 tools/dev/qlmc_coverage.py 的 BASELINE 上调到 {ok}")
        return 0
    print(f"\nPASS：覆盖率 {ok} 达到基线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
