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
import shutil
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
# v3.47: 48  （函数名作值 + OP_CALLV 间接调用 + atomic/spin/sleep/acq-rel
#              + net_config —— 解开 std/sync 与 std/log 两个模块）
# v3.48: 49  （file_size / read_text —— 解开 std/staticfile）
# v3.49: 51  （udp_sendto / udp_sendto6 —— 解开 std/net/udp 与 std/net/udp6）
# v3.52: 51  （跨模块 const + str 切片 —— 障碍前移但没解开模块）
# v3.53: 54  （thread_start —— 一次解开 std/net/reactor + std/ws + std/sse）
# v3.54: 56  （tcp_connect + tcp_send_n_to + tcp_recv_to —— 解开 std/net 与
#              std/net/udp6；getaddrinfo 链表遍历 + SO_SNDTIMEO/SO_RCVTIMEO）
# v3.55: 58  （for k in map + map.del —— 解开 std/kv 与 std/set）
# v3.56: 59  （args() 源码级预置注入 —— 解开 std/cli）
# v3.57: 60  （map[K]V.new() 容量可省略（默认 16）—— 解开 std/session）
# v3.58: 60  （SIMD 基础四件 —— 基础设施，没解开模块）
# v3.59: 63  （AES-NI / PCLMULQDQ / SSSE3 / SSE 移位 14 个内建 ——
#              解开 std/aes、std/tls13，以及此前卡在同一处的那一个）
# v3.61: 64  （import 图拓扑排序 —— 被依赖的模块先 parse，解开 std/tls_net。
#              std/httpc_net 也前进了，从"未知类型 TlsClientResult"变成
#              "struct 重复声明 _Ck"（那是另一个问题，见 §7.40））
# v3.62: 67  （模块作用域：同名私有 struct/函数按模块隔离 ——
#              一次解开 std/httpc_net + std/http + std/logfile，见 §7.43）
# v3.63: 67  （**分母修正**：std/park_linux 是 Linux 专用模块，在 win 目标上
#              连 stage-0 都编不过（`syscall` 只在 Linux/arm64 后端存在），
#              不该计入"qlmc 对 std 的覆盖率"。分母 70 -> 69，真实缺口
#              从"3 个"变成"2 个"：std/csv（vec[vec[T]]）与 std/gen（泛型）。
#              **数字没涨，但口径变准了** —— 这比刷数字重要。）
# v3.71: 68  （vec[vec[T]] —— 类型码从"加法"改成"类型表下标"，解开 std/csv。
#              见 §7.18。剩下的 std/gen 需要泛型单态化，是另一个架构件）
# v3.73: 69  （泛型单态化 —— 收 §7.44。模板记 token 区间、调用点推实参类型、
#              重新 parse 出特化副本（改名 f__int / f__f64）、改写调用点。
#              **69/69 = 分母全绿**，std/ 下每个模块 qlmc 都编得过。
#              注意"编得过"只是必要条件：真实可用性由差分夹具
#              tests/selfhost/s40_generic.qma 保证（逐字节对照 stage-0））
BASELINE = 69

QLMC_SRC = "bootstrap/qlmc/qlmc.qma"
QLMC_EXE = os.path.join("build", "_qlmc_cov.exe")
OUT_EXE = os.path.join("build", "_qlmc_cov_out.exe")


def _exe_runner(exe):
    """返回调用 PE 产物的命令前缀。

    * Windows 上直接跑（`[exe, ...]`）；
    * Linux 上**必须显式走 `wine`**：`binfmt_misc` 注册的 `MZ` handler
      会把 argv[0] 重复塞进去，qlmc 于是把 `build` 当成源文件名，
      报"打不开源文件 build"（v3.63 实测）。

    这不是本工具的怪癖 —— 任何在 Linux 上跑 qlmc 产物的脚本都会撞到。
    """
    if os.name == "nt":
        return [exe]
    wine = shutil.which("wine")
    if wine is None:
        raise SystemExit(
            "FAIL：Linux 上需要 wine 才能执行 qlmc 产出的 PE 文件"
            "（apt install wine64）")
    return [wine, exe]


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


# **平台专用模块**：它们在任何编译器下都编不出 Windows 目标，
# 所以不该计入"qlmc 对 std 的覆盖率"分母 —— 否则分母里永远有 1 个
# 不可能项，覆盖率上限被钉在 69/70。
#
# 判据是**客观可验证**的：这些模块用 `syscall`（只在 Linux/arm64 后端
# 存在）或 `@ffi`（只在 PE 后端存在），在 Windows 目标上是声明期硬失败。
# `_verify_platform_exclusions()` 会真的用 stage-0 试一遍，**编得过就报错**
# —— 防止有人往这张表里塞"其实能编、只是 qlmc 编不过"的模块来刷数字。
PLATFORM_SPECIFIC = {
    "std/park_linux.qma": "syscall() 只在 Linux/arm64 后端实现（Windows 是声明期硬失败）",
}


def _verify_platform_exclusions(root):
    """用 stage-0 **带 `--lib`** 复核：表里每个模块必须真的编不过 win 目标。

    为什么用 CLI 子进程而不是直接调 `transpile_win`：那个函数没有 `--lib`
    概念，对 lib 模块会抛 `KeyError: 'main'` —— 那是"调用方式不对"，
    不是"编不过"。用它当判据会把任何模块都误判成"编不过"。

    真正的判据只有一条：**同一个 CLI 命令，qlmc 失败但 stage-0 也失败**。
    这样排除表才不可能变成"qlmc 编不过的都塞进来"的垃圾桶。
    """
    bad = []
    for mod, why in PLATFORM_SPECIFIC.items():
        path = os.path.join(root, mod)
        if not os.path.isfile(path):
            bad.append(f"{mod}：文件不存在（表过期了？）")
            continue
        r = subprocess.run(
            [sys.executable, os.path.join(root, "tools", "stage0", "qlm_cli.py"),
             "build", path, "--target", "win", "--lib", "-o",
             os.path.join(root, "build", "_cov_excl.exe")],
            capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            bad.append(f"{mod}：stage-0 **能**编出 win 目标 —— "
                       f"它不是平台专用，不该被排除（{why}）")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--no-baseline", action="store_true")
    args = ap.parse_args()

    exe = build_qlmc()
    allmods = sorted(glob.glob("std/**/*.qma", recursive=True))
    if not allmods:
        print("FAIL：找不到 std/**/*.qma")
        return 1

    # 先复核"平台专用"表，编得过就是表写错了
    bad_excl = _verify_platform_exclusions(ROOT)
    if bad_excl:
        print("FAIL：PLATFORM_SPECIFIC 表有问题：")
        for b in bad_excl:
            print(f"  {b}")
        return 1

    mods = [m for m in allmods if m.replace(os.sep, "/") not in PLATFORM_SPECIFIC]
    skipped = len(allmods) - len(mods)
    if skipped:
        print(f"（排除 {skipped} 个平台专用模块："
              f"{', '.join(sorted(PLATFORM_SPECIFIC))} —— 见 PLATFORM_SPECIFIC 说明）")

    ok, fails = 0, []
    for m in mods:
        r = subprocess.run(_exe_runner(exe) + ["build", m, "-lib", "-o", OUT_EXE],
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
