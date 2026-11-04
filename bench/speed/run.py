#!/usr/bin/env python3
"""run.py —— Quelmara / C / Go / Python 四语言同题基准驱动器。

口径（很重要，别看错）：
  · 计时用**挂钟时间，取 N 次里的最小值**。本机 VBS 噪声 ±50%，最小值是唯一
    稳的统计量；单次数字没有意义。
  · 每个基准都打印**校验和**，四个语言必须逐字节相同 —— 不同就判 FAIL，
    说明其中一份写错了（或语言语义有分歧），此时时间数字一概不看。
  · 峰值内存用 `GetProcessMemoryInfo` 轮询采样（Windows），只对编译器那节有意义。

用法：
    python bench/speed/run.py                  # 全部语言 × 全部基准
    python bench/speed/run.py --reps 7         # 每个基准跑 7 次取最小
    python bench/speed/run.py --only b1_int b7_sort
    python bench/speed/run.py --langs quelmara go
    python bench/speed/run.py --langs quelmara0 c go python   # 跨平台（stage-0 后端）
    python bench/speed/run.py --markdown       # 直接出 markdown 表

环境：
    QLMC     qlmc.exe 路径（默认 build/qlmc.exe）
    ZIG      zig.exe 路径（用 `zig cc` 当 C 编译器；默认自动找 winget 安装位置）
    CC       C 编译器命令（优先于 ZIG，例如 "gcc -O2"）
"""
import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import time

# v2.54：跨平台。Windows 上跑四语言全量（qlmc 只有 win 后端）；
# Linux/macOS 只跑 C/Go/Python —— 那三个是可移植的，用来给"同一道题在不同
# 机器上是什么样"做参照（也就是"适配度"那一列）。
IS_WIN = os.name == "nt"
EXE = ".exe" if IS_WIN else ""
if IS_WIN:
    import ctypes.wintypes as wt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "build", "speed")

# 基准表：(id, 一句话说明)
BENCHES = [
    ("b1_int", "整数运算：2000 万次 (i*7)%13 累加"),
    ("b2_float", "浮点运算：调和级数前 500 万项"),
    ("b3_recursion", "递归：朴素 fib(30)（约 270 万次调用）"),
    ("b4_array", "数组：200 万元素写入 + 顺序 + 跨步遍历"),
    ("b5_string", "字符串：20 万次 int→str→int"),
    ("b6_hash", "哈希表：10 万插入 + 10 万查找（手写开放寻址）"),
    ("b7_sort", "排序：20 万伪随机 int 快排（手写）"),
    ("b8_threads1", "并发：单线程 4000 万次整数运算"),
    ("b8_threads4", "并发：4 线程各 1000 万次（总量相同）"),
    ("b9_json", "JSON：2590 字节文档解析 2000 遍（手写递归下降）"),
    # ---- v3.95 起扩充（目标 75 项，对标 CLBG / Hew / Logicaffeine）----
    # 每一项都要求"三语言算法完全等价，只打印结果 + 耗时"，否则比出来的
    # 是算法差异而不是编译器差异。
    ("b10_ackermann", "递归：Ackermann(2,8) 深层非原始递归"),
    ("b11_nqueens", "回溯：8 皇后 × 2000 轮（数组标记）"),
    ("b12_gcd", "整数：3000 万次辗转相除"),
    ("b13_collatz", "分支预测 + 整数除法：Collatz 1..30 万"),
    ("b15_loopsum", "最朴素循环累加 2 亿次（循环开销基线）"),
    ("b17_bubble", "排序：冒泡 8 万（最坏分支 + 交换开销）"),
    ("b22_knapsack", "DP：0/1 背包 800 件 × 800 容量"),
    ("b27_sieve", "筛法：埃氏筛 5000 万（布尔数组）"),
    ("b28_matrix", "数值：矩阵乘法 300×300（朴素三重循环）"),
    ("b31_memcpy", "IO：大块内存拷贝 100MB"),
    ("b32_io_write", "IO：顺序写 100 万个整数到内存"),
    ("b33_startup", "启动：函数调用 + 初始化开销"),
    ("b34_bitops", "微基准：位运算 2000 万次"),
    ("b35_branch", "微基准：分支预测 2000 万次"),
    ("b36_call", "微基准：函数调用 1000 万次"),
    ("b37_swap", "算法：100 万次交换排序"),
    ("b38_prime", "算法：试除法判定 10 万个素数"),
    ("b39_hash_open", "哈希表：开放寻址 50 万插入+查找"),
    ("b40_binary_search", "搜索：二分查找 100 万次"),
    ("b42_matrix_transpose", "数值：矩阵转置 500x500"),
    ("b43_gcd_lcm", "数论：GCD/LCM 100 万次"),
    ("b44_stack_sim", "数据结构：栈模拟 100 万次"),
    ("b45_accumulate", "数值：多项式求值 100 万次"),
    ("b46_strcat", "字符串：10 万次字符串拼接"),
    ("b47_bitcount", "微基准：位计数 1000 万次"),
    ("b48_sum_matrix", "数值：矩阵行求和 500x500"),
    ("b49_floyd", "图算法：Floyd-Warshall 100 节点"),
    ("b50_permute", "算法：全排列 10! 求和"),
    ("b52_io_scan", "IO：顺序扫描 100 万个整数"),
    ("b53_thread_sim", "并发：模拟 4 路并行累加"),
    ("b54_merge_sort", "排序：归并排序 10 万"),
    ("b55_hash_chain", "哈希表：链地址法 20 万插入"),
    ("b56_sieve_opt", "筛法：线性筛 200 万"),
    ("b57_pow_mod", "数论：快速幂取模 100 万次"),
    ("b58_rec_sum", "递归：递归求和 100 万"),
    ("b59_mat_vec", "数值：矩阵向量乘 500x500"),
    ("b60_murmur", "微基准：MurmurHash 100 万次"),
    ("b61_cache_scan", "微基准：缓存扫描 1000 万次"),
    ("b62_pred_branch", "微基准：不可预测分支 500 万次"),
    ("b65_random_walk", "模拟：随机游走 200 万步"),
    ("b66_integrate", "数值：数值积分 100 万步"),
    ("b67_bubble_opt", "排序：冒泡排序 5000"),
    ("b68_bit_matrix", "数值：位矩阵旋转 256x256"),
    ("b69_hash_fib", "哈希：Fibonacci 散列 50 万次"),
    ("b70_lin_search", "搜索：线性搜索 100 万次"),
    ("b71_sum_squares", "数值：平方和 100 万"),
    ("b72_sort_insert", "排序：插入排序 1 万"),
    ("b73_graph_bfs", "图算法：BFS 1000 节点"),
    ("b74_accum_poly", "数值：多项式累加 500 万"),
    ("b75_fib_matrix", "数值：矩阵快速幂 fib 1000"),
    ("b76_io_line", "IO：逐行扫描 100 万行"),
    ("b77_rec_fib", "递归：fib(25) 朴素递归"),
    ("b78_sum_digits", "数值：数位求和 100 万"),
    ("b79_binary_tree", "数据结构：BST 插入 5 万"),
    ("b81_bit_reverse", "微基准：位反转 100 万次"),
    ("b82_array_fill", "微基准：数组填充 500 万"),
    ("b83_lcg_random", "微基准：LCG 随机数 1000 万"),
    ("b84_pair_swap", "数据结构：键值对交换 100 万"),
    ("b85_count_ones", "微基准：popcount 500 万"),
    ("b86_matrix_diag", "数值：矩阵对角线求和 1000x1000"),
    ("b14_fibiter", "迭代 fib(5000 万)：纯循环 vs 递归对照"),
    ("b16_leibniz", "浮点：Leibniz 级数 π，2000 万项"),
    ("b18_insertion", "排序：插入排序 8 万（最坏情况移动）"),
    ("b23_lcs", "DP：最长公共子序列 1500×1500（滚动数组）"),
    ("b26_maxsub", "DP：Kadane 最大子数组 2000 万"),
]


# ---------------------------------------------------------------- 峰值内存采样
# 只在 Windows 上可用（psapi）。非 Windows 时 `--mem` 会退化成 0 —— 别假装有数。
if IS_WIN:
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wt.DWORD),
            ("PageFaultCount", wt.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]


def _peak_ws(handle):
    if not IS_WIN:
        return 0
    pmc = PROCESS_MEMORY_COUNTERS()
    pmc.cb = ctypes.sizeof(pmc)
    if ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(pmc), pmc.cb):
        return int(pmc.PeakWorkingSetSize)
    return 0


def run_once(exe, args=None, sample_mem=False):
    """跑一次，返回 (挂钟秒, 峰值字节, stdout)。"""
    cmd = [exe] + (args or [])
    if not sample_mem:
        t0 = time.perf_counter()
        r = subprocess.run(cmd, capture_output=True, text=True)
        dt = time.perf_counter() - t0
        return dt, 0, r.stdout
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True)
    peak = 0
    # `p._handle` 是 Windows 专属；非 Windows 上 `--mem` 直接给 0（别假装有数）
    while p.poll() is None:
        if IS_WIN:
            peak = max(peak, _peak_ws(int(p._handle)))
        time.sleep(0.002)
    out, _ = p.communicate()
    return time.perf_counter() - t0, peak, out


def parse_out(out):
    """程序约定：若干行校验和 + 一行 `T` + 一行纳秒。返回 (校验和, 纳秒)。

    **为什么要在进程内计时**：本机 VBS 开着，光进程创建就 ~450 ms，而大部分基准
    的真实负载只有几毫秒到几十毫秒 —— 用挂钟量等于在量 CreateProcess。所以每个
    程序自己用单调时钟圈住负载，只把负载时间打出来。
    """
    lines = [l for l in (out or "").splitlines()]
    if "T" not in lines:
        return (out or "").strip(), None
    i = lines.index("T")
    ck = "\n".join(lines[:i]).strip()
    try:
        ns = int(lines[i + 1].strip())
    except (IndexError, ValueError):
        ns = None
    return ck, ns


# ---------------------------------------------------------------- 工具链探测
def find_zig():
    v = os.environ.get("ZIG")
    if v and os.path.exists(v):
        return v
    cands = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\zig.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
    ]
    if os.path.exists(cands[0]):
        return cands[0]
    for base, dirs, files in os.walk(cands[1]):
        if "zig.exe" in files:
            return os.path.join(base, "zig.exe")
    return shutil.which("zig")


def cc_command():
    """返回 (名字, 命令前缀列表)；找不到返回 (None, None)。"""
    env = os.environ.get("CC")
    if env:
        return env.split()[0], env.split()
    zig = find_zig()
    if zig:
        return "zig cc", [zig, "cc", "-O2"]
    for cand in ("gcc", "clang", "cc"):
        p = shutil.which(cand)
        if p:
            return cand, [p, "-O2"]
    return None, None


def go_exe():
    return shutil.which("go")


def qlmc_exe():
    p = os.environ.get("QLMC") or os.path.join(ROOT, "build", "qlmc.exe")
    return p if os.path.exists(p) else None


# ---------------------------------------------------------------- 各语言构建
def build_all(langs, only):
    os.makedirs(OUT, exist_ok=True)
    built = {}          # (lang, bench) -> exe 或命令
    notes = {}

    if "quelmara" in langs:
        q = qlmc_exe()
        if not q:
            notes["quelmara"] = ("跳过：build/qlmc.exe 不存在（先自举："
                                 "python tools/stage0/qlm_cli.py build "
                                 "bootstrap/qlmc/qlmc.qma --target win -o build/qlmc.exe）")
        else:
            # v4.02：**Linux 上走 qlmc 的 ELF 后端**（v3.94 加的那个）。
            # 以前这里硬编码 PE，于是 posix 上 quelmara 列永远是空的 ——
            # 只能靠 quelmara0（stage-0）凑数。现在 qlmc 自己能出 ELF，
            # 两边同台比才有意义。
            #
            # qlmc 本身是 PE 产物，在 Linux 上要用 wine 跑；
            # 它**编出来**的可执行文件是原生 ELF，直接 exec 即可。
            ELF = (not IS_WIN)
            # qlmc 是 PE 产物，Linux 上要用 wine 跑它（**只包编译器本身**，
            # 它编出来的 ELF 是原生的，直接 exec）。binfmt 的 MZ handler 会
            # 把 argv[0] 重复塞进去，所以不能用 `./qlmc.exe` 的裸执行。
            wine = shutil.which("wine")
            runner = ([wine, q] if (ELF and wine) else [q])
            for b, _ in BENCHES:
                if only and b not in only:
                    continue
                src = os.path.join(HERE, "quelmara", b + ".qma")
                exe = os.path.join(OUT, "qlm_" + b + ("" if ELF else EXE))
                cmd = runner + ["build", src, "-o", exe]
                if ELF:
                    cmd += ["--target", "elf"]
                r = subprocess.run(cmd, capture_output=True, text=True)
                if r.returncode != 0:
                    notes.setdefault("quelmara", f"{b} 编译失败: " +
                                     (r.stdout + r.stderr).strip()[:200])
                    continue
                if ELF:
                    os.chmod(exe, 0o755)
                built[("quelmara", b)] = [exe]

    if "quelmara0" in langs:
        py = sys.executable
        cli = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
        # stage-0 的三个后端：win = PE、native = **ELF64（Linux）**、arm64。
        # **macOS 没有后端**（它需要 Mach-O），`--target native` 在 Darwin 上
        # 产出的仍是 ELF，执行时报 `OSError: [Errno 8] Exec format error`。
        # 与其假装跑过，不如明确跳过 —— 缺口记在 docs/07-gaps.md 的平台支持表里。
        tgt = "win" if IS_WIN else "native"
        if sys.platform == "darwin":
            notes["quelmara0"] = ("跳过：stage-0 的 native 后端是 ELF64，macOS 需要 "
                                  "Mach-O（本版没有）。qlmc 也只有 PE 后端。")
        # macOS 没有后端（见上）→ 整个循环跳过
        bench_ids = []
        if sys.platform != "darwin":
            bench_ids = [x for x, _ in BENCHES]
        for b in bench_ids:
            if only and b not in only:
                continue
            src = os.path.join(HERE, "quelmara", b + ".qma")
            exe = os.path.join(OUT, "qlm0_" + b + EXE)
            r = subprocess.run([py, cli, "build", src, "--target", tgt,
                                "-o", exe],
                               capture_output=True, text=True)
            if r.returncode != 0:
                notes.setdefault("quelmara0", f"{b} 编译失败: " +
                                 (r.stdout + r.stderr).strip()[:200])
                continue
            if not IS_WIN:
                # POSIX 上刚写出来的文件没有执行位（Windows 不需要）
                os.chmod(exe, 0o755)
            built[("quelmara0", b)] = [exe]

    if "c" in langs:
        name, cc = cc_command()
        if not cc:
            notes["c"] = "跳过：本机没有 C 编译器（gcc/clang/zig 都没有）"
        else:
            for b, _ in BENCHES:
                if only and b not in only:
                    continue
                src = os.path.join(HERE, "c", b + ".c")
                exe = os.path.join(OUT, "c_" + b + EXE)
                r = subprocess.run(cc + ["-o", exe, src],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    notes.setdefault("c", f"{b} 编译失败: " +
                                     (r.stdout + r.stderr).strip()[:200])
                    continue
                built[("c", b)] = [exe]

    if "go" in langs:
        if not go_exe():
            notes["go"] = "跳过：没有 go"
        else:
            for b, _ in BENCHES:
                if only and b not in only:
                    continue
                src = os.path.join(HERE, "go", b + ".go")
                exe = os.path.join(OUT, "go_" + b + EXE)
                if not os.path.exists(src):
                    continue
                r = subprocess.run([go_exe(), "build", "-o", exe, src],
                                   capture_output=True, text=True,
                                   cwd=os.path.join(HERE, "go"))
                if r.returncode != 0:
                    notes.setdefault("go", f"{b} 编译失败: " +
                                     (r.stdout + r.stderr).strip()[:200])
                    continue
                built[("go", b)] = [exe]

    if "python" in langs:
        py = sys.executable
        for b, _ in BENCHES:
            if only and b not in only:
                continue
            built[("python", b)] = [py, os.path.join(HERE, "python", b + ".py")]

    # ---- v3.99：数据驱动的多语言接入（v3.99 起从 c/go/python 扩到 11 种）----
    #
    # 每种语言只要在 `EXTRA_LANGS` 里登记 (扩展名, 找编译器, 拼构建命令,
    # 可选的自有 build 目录)，下面这段就统一处理。**没有编译器就明确跳过
    # 并记进 notes**，不假装测过。
    for lang in langs:
        if lang not in EXTRA_LANGS:
            continue
        ext, find_cc, mk_cmd, need_dir = EXTRA_LANGS[lang]
        cc = find_cc()
        if not cc:
            notes[lang] = f"跳过：没有找到 {lang} 的编译器（{EXTRA_HINT.get(lang, '')}）"
            continue
        for b, _ in BENCHES:
            if only and b not in only:
                continue
            src = os.path.join(HERE, lang, b + ext)
            if not os.path.exists(src):
                continue
            exe = os.path.join(OUT, lang + "_" + b + EXE)
            cmd = mk_cmd(cc, src, exe)
            r = subprocess.run(cmd, capture_output=True, text=True,
                               cwd=os.path.join(HERE, lang) if need_dir else None)
            if r.returncode != 0:
                notes.setdefault(lang, f"{b} 编译失败: " +
                                 (r.stdout + r.stderr).strip()[:200])
                continue
            built[(lang, b)] = [exe]

    return built, notes


# ---------------------------------------------------------------- 主流程
# quelmara   = qlmc（stage-1 自举编译器）编出来的产物，**只有 Windows PE 后端**
# quelmara0  = stage-0（参考编译器）编出来的产物，**win / linux / macos 都有后端**
#   加这一列是为了拿到"同一个语言在不同平台上"的数字（也就是适配度），
#   同时它和 quelmara 列在同一台 Windows 机器上的差就是**后端差距**。
LANGS = ["quelmara", "quelmara0", "c", "go", "python",
         "cpp", "rust", "zig", "nim", "d", "csharp", "ada", "fortran"]

# v3.99：数据驱动接入。每项 = (源码扩展名, 找编译器, 拼命令, 是否在语言目录里构建)
#
# **为什么用数据而不是每种语言写一段 if**：原来 c/go/python 各写了一段，
# 加第 4 种就要复制一遍 20 行。现在加语言只改这张表。
#
# 找编译器的顺序是"优先用 PATH 里第一个能跑通的"，找不到就 `None`
# → 上层明确跳过并在结果里写"Why"，**不假装测过**。
def _find(*names):
    def f():
        for n in names:
            p = shutil.which(n)
            if p:
                return p
        return None
    return f


EXTRA_LANGS = {
    # C++：与 C 同一套 bench.h（计时宏在头文件里）
    # C++ 复用 C 的 bench.h，所以要把 c/ 放进 include 路径
    "cpp": (".cpp", _find("g++", "clang++"),
            lambda cc, src, out: [cc, "-O2", "-I",
                                  os.path.join(HERE, "c"), "-o", out, src], False),
    # Rust：bench/*.rs 里自己做了单调时钟，rustc -O
    "rust": (".rs", _find("rustc"),
             lambda cc, src, out: [cc, "-O", "-o", out, src], False),
    # Zig：`zig build-exe -O ReleaseFast`
    "zig": (".zig", _find("zig"),
            lambda cc, src, out: [cc, "build-exe", "-O", "ReleaseFast",
                                  "-femit-bin=" + out, src], False),
    # Nim：`nim c -d:release --out:...`（要 --hints:off 免得刷屏）
    "nim": (".nim", _find("nim"),
            lambda cc, src, out: [cc, "c", "-d:release", "--hints:off",
                                  "--out:" + out, src], False),
    # D（LDC）
    "d": (".d", _find("ldc2"),
          lambda cc, src, out: [cc, "-O3", "-of=" + out, src], False),
    # C#（.NET）。**只支持 net6+ 的 top-level program**，且构建慢，
    # 所以单独放在 csharp/ 目录里用 `dotnet run` 不方便——改成
    # 预生成 .csproj 太复杂，这里用 `csc`/`dotnet script` 都不可靠，
    # 暂时只登记不启用（见 EXTRA_HINT）。
    "ada": (".adb", _find("gnatmake"),
            lambda cc, src, out: [cc, "-O2", "-o", out, src], False),
    "fortran": (".f90", _find("gfortran"),
                lambda cc, src, out: [cc, "-O2", "-o", out, src], False),
}

EXTRA_HINT = {
    "cpp": "g++ / clang++",
    "rust": "rustc（rustup component）",
    "zig": "zig（ziglang.org 下载版）",
    "nim": "nim（choosenim）",
    "d": "ldc2（D 的 LLVM 版）",
    "ada": "gnat（GNAT Community / gnatmake）",
    "fortran": "gfortran（gcc-fortran 包）",
}


def report_checksums(fails, rows):
    """校验和门禁：四种实现必须打印**逐字节相同**的校验和。

    不一致说明其中一份写错了（或语言语义有分歧），此时时间数字一概不看。
    """
    if fails:
        print("\n[FAIL] 这些基准的校验和在不同语言之间不一致：")
        for b in fails:
            r = next(x for x in rows if x["bench"] == b)
            print(f"  {b}")
            for l, o in r["out"].items():
                print(f"    {l:<10} {o!r}")
        return 1
    n = len(rows[0]["out"]) if rows else 0
    print(f"\n校验和：{len(rows)} 个基准 × {n} 个语言，全部一致。")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--langs", nargs="*", default=LANGS)
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--mem", action="store_true", help="同时采峰值内存（慢）")
    args = ap.parse_args()

    built, notes = build_all(args.langs, args.only)
    for k, v in notes.items():
        print(f"[{k}] {v}")

    if not built:
        print("没有任何可跑的基准。")
        return 1

    langs = [l for l in LANGS if any(k[0] == l for k in built)]
    rows = []
    fails = []
    for b, desc in BENCHES:
        if args.only and b not in args.only:
            continue
        if not any((l, b) in built for l in langs):
            continue
        rec = {"bench": b, "desc": desc, "t": {}, "mem": {}, "out": {}}
        for l in langs:
            if (l, b) not in built:
                continue
            cmd = built[(l, b)]
            best, bestmem, bestout, bestck = None, 0, None, None
            for _ in range(args.reps):
                dt, mem, out = run_once(cmd[0], cmd[1:], sample_mem=args.mem)
                ck, ns = parse_out(out)
                if ns is not None and (best is None or ns < best):
                    best, bestck, bestout = ns, ck, out
                bestmem = max(bestmem, mem)
            if best is None:      # 没按协议输出，退回挂钟
                best, bestck = int(dt * 1e9), (out or "").strip()
            rec["t"][l] = best / 1e9
            rec["mem"][l] = bestmem
            rec["out"][l] = bestck or ""
        # 校验和必须全部相同
        vals = set(rec["out"].values())
        if len(vals) > 1:
            fails.append(b)
        rows.append(rec)

    # ---- 输出 ----
    if args.markdown:
        print()
        head = "| 基准 | 规模/说明 | " + " | ".join(langs) + " | 最快/最慢 |"
        print(head)
        print("|" + "---|" * (len(langs) + 3))
        for r in rows:
            ts = [r["t"][l] for l in langs if l in r["t"]]
            ratio = (max(ts) / max(min(ts), 1e-9)) if len(ts) > 1 else 0
            cells = []
            for l in langs:
                cells.append(f"{r['t'][l]*1000:.1f}" if l in r["t"] else "—")
            print(f"| `{r['bench']}` | {r['desc']} | " + " | ".join(cells) +
                  f" | {ratio:.0f}× |")
        print("\n单位：毫秒（min of %d）" % args.reps)
        # **校验和门禁在 markdown 模式下也必须走**（CI 用的就是 --markdown）。
        # 以前这里直接 return 0，于是"某个语言写错了"在 CI 上是静默的 ——
        # 而校验和一致是整张表的前提，不一致时时间数字一概不能看。
        return report_checksums(fails, rows)

    print()
    w = 13
    print(f"{'基准':<{w}}" + "".join(f"{l:>13}" for l in langs) +
          f"{'最快/最慢':>11}")
    print("-" * (w + 13 * len(langs) + 11))
    for r in rows:
        ts = [r["t"][l] for l in langs if l in r["t"]]
        ratio = (max(ts) / min(ts)) if len(ts) > 1 else 0
        line = f"{r['bench']:<{w}}"
        for l in langs:
            line += (f"{r['t'][l]*1000:>12.1f} " if l in r["t"]
                     else f"{'—':>12} ")
        line += f"{ratio:>10.0f}×"
        print(line)
    print("-" * (w + 13 * len(langs) + 11))
    print(f"单位：毫秒（min of {args.reps}）。本机 VBS 噪声大，只做同表横向比较。")

    return report_checksums(fails, rows)


if __name__ == "__main__":
    sys.exit(main())
