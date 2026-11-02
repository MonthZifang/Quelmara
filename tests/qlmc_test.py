#!/usr/bin/env python3
"""qlmc_test.py —— stage-1 编译器（`bootstrap/qlmc/qlmc.qma`）的差分回归

做法：同一份源码**分别**用 stage-0（`tools/stage0/qlm_cli.py`）和 qlmc 编译，
跑两个 exe，比较 stdout 与退出码**逐字节相同**。这是唯一有说服力的判据——
"能编出一个 exe"很容易，"和既有编译器行为一致"才是真的对。

覆盖的用例都只用子集 S1（见 `docs/05-toolchain.md` §1.11）：
  examples/fib.qma            递归 + if + 比较
  examples/loop_sum.qma       while + 可变局部 + * % + 2 亿次循环
  tests/selfhost/s1_basics.qma  算术/比较/逻辑/else/递归/字符串/exit 的混合

另加两条结构断言：产物必须是合法 PE（MZ/PE32+/AMD64），且必须比源码小
（"几 KB 的东西"这条口径）。

用法：
  python tests/qlmc_test.py            # 全部用例
  python tests/qlmc_test.py --time     # 额外报 qlmc 的进程内编译耗时
"""
import os
import shutil
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

# Linux 上跑 qlmc 产出的 PE **必须显式走 wine**：binfmt_misc 的 `MZ`
# handler 会把 argv[0] 重复塞进去，qlmc 于是把 `build` 当成源文件名，
# 报"打不开源文件 build"（v3.63 实测，与 tools/dev/qlmc_coverage.py 同因）。
def _exe_runner(exe):
    if os.name == "nt":
        return [exe]
    wine = shutil.which("wine")
    if wine is None:
        raise SystemExit("FAIL：Linux 上需要 wine 才能执行 qlmc 产出的 PE")
    return [wine, exe]
CLI = os.path.join(ROOT, "tools", "stage0", "qlm_cli.py")
QLMC = os.path.join(ROOT, "build", "qlmc.exe")
SRC_QLMC = os.path.join(ROOT, "bootstrap", "qlmc", "qlmc.qma")
BUILD = os.path.join(ROOT, "build")

CASES = [
    ("fib", "examples/fib.qma"),
    ("loop_sum", "examples/loop_sum.qma"),
    ("s1_basics", "tests/selfhost/s1_basics.qma"),
    ("s2_str", "tests/selfhost/s2_str.qma"),
    ("s2_const", "tests/selfhost/s2_const.qma"),
    ("s2_assert", "tests/selfhost/s2_assert.qma"),
    ("s3_manyfns", "tests/selfhost/s3_manyfns.qma"),
    ("s4_agg", "tests/selfhost/s4_agg.qma"),
    ("s5_enum", "tests/selfhost/s5_enum.qma"),
    ("s6_vec", "tests/selfhost/s6_vec.qma"),
    ("s7_aggfn", "tests/selfhost/s7_aggfn.qma"),
    ("s8_map", "tests/selfhost/s8_map.qma"),
    ("s9_slice", "tests/selfhost/s9_slice.qma"),
    ("s10_defer", "tests/selfhost/s10_defer.qma"),
    ("s11_import", "tests/selfhost/s11_import.qma"),
    ("s12_ffi", "tests/selfhost/s12_ffi.qma"),
    ("s13_closure", "tests/selfhost/s13_closure.qma"),
    ("s14_vecgrow", "tests/selfhost/s14_vecgrow.qma"),
    ("s15_bitops", "tests/selfhost/s15_bitops.qma"),
    ("s16_stackargs", "tests/selfhost/s16_stackargs.qma"),
    ("s17_constexpr", "tests/selfhost/s17_constexpr.qma"),
    ("s18_vecagg", "tests/selfhost/s18_vecagg.qma"),
    ("s19_spawn", "tests/selfhost/s19_spawn.qma"),
    ("s20_mem", "tests/selfhost/s20_mem.qma"),
    ("s21_f64", "tests/selfhost/s21_f64.qma"),
    ("s22_f64print", "tests/selfhost/s22_f64print.qma"),
    ("s23_map_grow", "tests/selfhost/s23_map_grow.qma"),
    ("s24_varreg", "tests/selfhost/s24_varreg.qma"),
    ("s25_divmod", "tests/selfhost/s25_divmod.qma"),
    ("s26_alias", "tests/selfhost/s26_alias.qma"),
    ("s27_modind", "tests/selfhost/s27_modind.qma"),
    ("s28_compound", "tests/selfhost/s28_compound.qma"),
    # v3.50：字符串 const / 位运算复合赋值 / for k in vec。
    # **必须是差分用例**（stage-0 与 qlmc 各编一次、输出逐字节比较）：
    # 这三项都改的是语义，光"能编过"说明不了算得对 —— 尤其
    # `S_FOREACH` 第一版编号与 `S_BREAK` 撞车时，代码能编出来但
    # break 被当集合求值，只有差分能抓住。
    ("s29_syntax", "tests/t194_qlmc_syntax.qma"),
    # v3.51：`len()` 的机器码在 R12 上崩（`_len_of` 缺 SIB 字节）。
    # **这条必须是差分用例**：bug 只在寄存器分配把 LEN 的结果分到 r12
    # 时出现，光"能编过"完全看不出来 —— stage-0 一直是对的。
    ("s30_strlen", "tests/t195_qlmc_strlen.qma"),
    # v3.52：跨模块 const + str 切片。
    # **必须是差分用例**：str 切片返回的是**新串**（不是视图），
    # 长度头 / NUL / ABI 必须对 —— 否则下游 len() 与拼接会读到原串的
    # 长度，那是静默错而不是崩，光"能编过"完全看不出来。
    ("s31_strslice", "tests/t196_qlmc_strslice.qma"),
    # v3.53：thread_start（真 OS 线程，不受 multicore 降级影响）。
    # **必须是差分用例**：arg 传递、句柄有效性、多线程并发累加不丢更新
    # 都要逐字节对上 —— 尤其 bits=15 这条，任一线程没跑或 arg 传错就少一位。
    ("s32_thread", "tests/t197_qlmc_thread.qma"),
    # v3.55：for k in map + map.del。
    # **必须是差分用例**：map 遍历顺序未定义，但"集合内容"必须一致；
    # del 尤其危险 —— 直接清 0 会切断探测链，排在后面的键静默找不到
    # （v3.55 第一版就是这样：has(3) 返回 false、get(3) 返回 0，
    # 数据没丢但找不到）。只有逐行对比 stage-0 才能抓住。
    ("s33_mapiter", "tests/t199_qlmc_mapiter.qma"),
    # v3.57：`map[K]V.new()` 省略容量（默认 16）。
    # stage-0 一直允许省略（"cap 须 2 的幂，省略默认 16"），qlmc 以前强制
    # 要求 —— `std/session` 的 `map[str]str.new()` 因此编不过。
    ("s34_mapnew", "tests/t201_qlmc_mapnew.qma"),
    # v3.58：SIMD（XMM）基础四件 load/store/mov/pxor。
    # **必须是差分用例**：SIMD 指令编码错了只会静默算错或崩，
    # 光"能编过"完全说明不了问题 —— 尤其要验 b7/b8/b15 这三个跨 64 位
    # 边界的字节，只看 b0 的话"只搬了低 64 位"也会通过。
    ("s35_simd", "tests/t202_qlmc_simd.qma"),
    # v3.59：AES-NI / PCLMULQDQ / SSSE3 / SSE 立即数移位（14 个内建）。
    # **必须是差分用例**：SIMD 编码错了只静默算错 —— 比如 pshufb 的 map
    # 写成 0F 3A 而不是 0F 38 就完全是另一条指令，pclmulqdq 少发 imm8
    # 后面的字节会被当指令。本夹具对每条指令都做已知答案的数值验证。
    ("s36_aes", "tests/t203_qlmc_aes.qma"),
    # v3.61：**跨模块 struct**（收 §7.40）。导入方在自己的函数签名里直接用
    # 被导入模块声明的 struct。修法不是"补类型系统"，而是 import 图的
    # 拓扑排序 —— 被依赖的模块先 parse。**必须是差分用例**：字段偏移错位
    # 是静默的（不崩不报错、算出来是错的），光"能编过"说明不了任何事。
    ("s37_crossmod", "tests/selfhost/s37_crossmod.qma"),
    # v3.62：**模块作用域**（收 §7.43）。两个模块各自声明同名但签名/布局
    # 不同的私有函数与 struct，调用点必须绑到本模块那个。
    # **必须是差分用例**：`_fail` 有两种签名、`_Ck` 有两种布局，绑错是
    # 静默错编（字段偏移错位、str 当 int 传），不崩不报错只是结果错。
    ("s38_modscope", "tests/selfhost/s38_modscope.qma"),
    # v3.71：**vec[vec[T]]**（收 §7.18）。类型码从"加法"改成"类型表下标"，
    # 嵌套不再进位撞 TY_MAP。**必须是差分用例**：老写法下 vec[vec[str]]
    # = 0x10002 落进 TY_MAP 区间，`_lower_method` 把它当 map 处理 ——
    # 不崩、不报错、只是走错分支，只有逐字节差分能抓。
    ("s39_nestedvec", "tests/selfhost/s39_nestedvec.qma"),
    # v3.73：**泛型单态化**（收 §7.44）。同一模板两个类型实参（int/f64）、
    # 约束形态 `[T: Ord]`、从 `vec[T]` 形参推元素类型、特化副本间互相调用。
    # **必须是差分用例**：展开走"记 token 区间 -> 推类型 -> 重新 parse ->
    # 改写调用点"四步，任一步错都是静默错编（0 个函数 / 名字没换 /
    # 调用点没改写 / 类型绑错）。只有逐字节差分能抓。
    ("s40_generic", "tests/selfhost/s40_generic.qma"),
    # v3.75：**第 5 个及以后位置的 f64 形参**（收 §7.33）。Win64 前 4 个整型
    # 实参走寄存器、第 5 个起上栈；f64 住 XMM。以前分配器只在"区间内无调用"
    # 时才给 f64 分 XMM，于是 CALL 的返回值（区间必然含那次调用）被分到通用
    # 寄存器，一路按 int 语义搬运 —— 七参函数的第 6 个 f64 形参读出来是 0。
    # **必须是差分用例**：不崩、不报错，只是数值不对，只有逐字节比对能抓。
    ("s41_f64stk", "tests/selfhost/s41_f64stk.qma"),
    # v3.79：**比较 / 逻辑结果一律按 bool 打印**（收 §7.22）。
    # stage-0 曾经自己就不一致：编译期可折叠的比较折成 int（打 1），
    # 运行期的比较是 bool（打 true）。qlmc 为了对齐选了 int 口径 ——
    # 那是把一个不一致固化进契约。本版两边都修成 bool。
    # **必须是差分用例**：同一表达式形态的两种求值路径（折叠 / 运行期）
    # 必须给出同一种输出，只有逐字节比对能抓。
    ("s43_boolprint", "tests/selfhost/s43_boolprint.qma"),
    # v3.80：**第 7 个及以后实参走栈，顺序必须"先存栈、后摆寄存器"**（收 §7.8）。
    # stage-0 原来先搬前 6 个到 ARG_REGS 再存栈实参，而栈实参可能正住在
    # ARG_REGS 里 —— 被覆盖后读到别人的值。症状是"7 参 + 第 7 个是 str +
    # 调两次"直接 page fault。**必须是差分用例**：单次调用看不出来。
    ("s44_wideargs", "tests/selfhost/s44_wideargs.qma"),
    # v3.81：**AES 直接写在 main 里**（复核 §7.4 / §7.5）。
    # 原记录说这个形状会误编译（FIPS-197 向量最后一个字节丢），产品路径
    # 因为包了一层所以没事。v3.81 复核发现当前不复现 —— 把原复现件
    # （`build/_aes_sw.qma`，一直没入库）固化成正向差分夹具：
    # 直接调用 / 包一层 / 高寄存器压力三种形态都必须给出标准答案。
    # **必须是差分用例**：这类"少写一个字节"的缺陷不崩不报错，只有逐字节比对能抓。
    ("s45_aesmain", "tests/selfhost/s45_aesmain.qma"),
    # v3.82：**容器的元素/值类型不能丢**（收 §7.28）。
    # stage-0 有三处把元素类型弄丢后按 int/str 硬解释：`vec[f64]` / `map[K]f64`
    # 的元素、`len(map)` 在"同函数两张 map"/"同文件多个带 map 的函数"时。
    # 症状是**编得出、跑得完、答案错**（比编不过更麻烦）。
    ("s46_containerelem", "tests/selfhost/s46_containerelem.qma"),
    # v3.87：**标志位循环的语义**（收 §7.47）。
    # `while go == 1 && p < n` + 体内 `if/else` 改 `go` + 体内 `s[p]` ——
    # 三要素同时出现时曾观察到 qlmc 只跑一轮（stage-0 打 3、qlmc 打 1）。
    # 定位结论：**不是源码缺陷，是本地 `build/qlmc.exe` 陈旧** —— 那个二进制
    # 是 14:05 用一次已完全回退的 `_opt_flag_loop` 实验编出来的，而该 pass
    # 从未进入任何提交（`git log -S_opt_flag_loop` 为空）。从 HEAD 干净重建
    # 的 qlmc 对 12 行输出与 stage-0 逐字节一致。
    # 夹具保留作**回归**：它同时钉住 6 种标志位循环形态，任何"把 go = 0
    # 当 break"的优化都会在这里翻红。
    ("s47_flagloop", "tests/selfhost/s47_flagloop.qma"),
    # v3.90：**归纳削减的条件减回绕**（`OP_CSUBNS`，无分支）。
    # `(i*C) % D` 会被归纳削减成"递增计数器 + 条件回绕"。回绕以前是
    # `cmp/jl/sub` 分支，v3.90 换成 `sub/cmovns` 无分支（stage-0 一直是这样）。
    #
    # 为什么 v2.88 的同类尝试失败而这次成功：v2.88 用纯算术
    # `t=v-D; m=t>>63; m&=D; v=t+m`，要**两个 IR 级临时值**，b1_int 的
    # 寄存器池挤不下，溢出到帧槽后慢 6.6×。`cmovns` 的暂存是发射器专用的
    # RAX（不参与分配），**IR 层一个临时值都不多要**。
    #
    # 这个夹具钉的是**回绕的边界**：v 恰好等于 D、D-1、D+1、2D-1 时都必须
    # 只减一次。减错一次是静默错值，只有逐字节比对能抓。
    ("s48_csub", "tests/selfhost/s48_csub.qma"),
]

npass = 0
nfail = 0


def ok(msg):
    global npass
    npass += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global nfail
    nfail += 1
    print(f"  [FAIL] {msg}")


def build_with(cli_args, out):
    r = subprocess.run(cli_args, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError((r.stdout or "")[-800:] + (r.stderr or "")[-800:])


def pe_info(path):
    d = open(path, "rb").read()
    if d[:2] != b"MZ":
        return None
    e = struct.unpack_from("<I", d, 0x3C)[0]
    if d[e:e + 4] != b"PE\0\0":
        return None
    machine, nsec = struct.unpack_from("<HH", d, e + 4)
    optsz = struct.unpack_from("<H", d, e + 20)[0]
    magic = struct.unpack_from("<H", d, e + 24)[0]
    return {"machine": machine, "nsec": nsec, "magic": magic, "size": len(d)}


def main():
    show_time = "--time" in sys.argv
    print("== 构建 qlmc（用 stage-0 编自己写的编译器） ==")
    try:
        build_with([PY, CLI, "build", SRC_QLMC, "--target", "win", "-o", QLMC], QLMC)
    except RuntimeError as ex:
        bad(f"qlmc 自身构建失败：{ex}")
        return 1
    info = pe_info(QLMC)
    ok(f"qlmc.exe 是合法 PE（{info['size']} 字节）") if info else bad("qlmc.exe 不是 PE")

    # ---- 错误路径：必须**干净退出**（rc=2），不能是崩溃（0xC0000005 / 139）----
    # §7.34：qlmc 以前在表达式解析器深处报错时会 SIGSEGV（先正确打印诊断、
    # 然后访问违例）。根因在 ExitProcess 的 loader 关闭流程，修法是出错走
    # TerminateProcess。这条测试就是那个修复的判据 —— 只比退出码，不比产物。
    print("== 错误路径（诊断 + 干净退出） ==")
    bad_src = os.path.join(BUILD, "err_syntax.qma")
    with open(bad_src, "w", encoding="utf-8") as f:
        f.write("fn main() {\n    let x = \n}\n")
    r = subprocess.run(_exe_runner(QLMC) + ["dump", bad_src], capture_output=True)
    if r.returncode == 2 and b"\xe6\x9c\x9f\xe6\x9c\x9b\xe8\xa1\xa8\xe8\xbe\xbe\xe5\xbc\x8f" in r.stderr:
        ok("语法错：打印诊断且 rc=2（无崩溃）")
    else:
        bad(f"语法错：期望 rc=2 且带诊断，实际 rc={r.returncode} stderr={r.stderr[-120:]!r}")

    for name, rel in CASES:
        src = os.path.join(ROOT, rel)
        out0 = os.path.join(BUILD, f"qlmc_{name}_stage0.exe")
        out1 = os.path.join(BUILD, f"qlmc_{name}_native.exe")
        print(f"== {name}（{rel}） ==")
        t0 = time.perf_counter()
        try:
            build_with([PY, CLI, "build", src, "--target", "win", "-o", out0], out0)
            dt0 = (time.perf_counter() - t0) * 1000
            t1 = time.perf_counter()
            build_with(_exe_runner(QLMC) + ["build", src, "-o", out1], out1)
            dt1 = (time.perf_counter() - t1) * 1000
        except RuntimeError as ex:
            bad(f"{name} 构建失败：{ex}")
            continue

        pi = pe_info(out1)
        if not pi:
            bad(f"{name}: qlmc 产物不是 PE")
            continue
        if pi["machine"] != 0x8664 or pi["magic"] != 0x20B:
            bad(f"{name}: 机器码/可选头不对 machine={pi['machine']:#x} magic={pi['magic']:#x}")
            continue
        ok(f"{name}: qlmc 产物是 PE32+ AMD64（{pi['size']} 字节，{pi['nsec']} 节）")

        # 产物要在本机跑：Linux 上走 wine（binfmt 的 MZ handler 会重复
        # argv[0]），并且要补执行位 —— stage-0 写出来的文件默认没有 x 位。
        for _p in (out0, out1):
            try:
                os.chmod(_p, 0o755)
            except OSError:
                pass
        a = subprocess.run(_exe_runner(out0), capture_output=True)
        b = subprocess.run(_exe_runner(out1), capture_output=True)
        if a.stdout == b.stdout and a.returncode == b.returncode:
            ok(f"{name}: 与 stage-0 输出逐字节相同（{len(a.stdout)} 字节, rc={a.returncode}）")
        else:
            bad(f"{name}: 输出不同 rc {a.returncode} vs {b.returncode}\n"
                f"      stage0={a.stdout[:120]!r}\n      qlmc  ={b.stdout[:120]!r}")
        if show_time:
            print(f"      编译墙钟：stage-0 {dt0:.0f} ms  |  qlmc {dt1:.0f} ms"
                  f"（含 {370} ms 量级的进程创建税，见 06-status §3.25）")

    # ---- 多核：线程数不得影响产物字节（v2.16） ----
    print("== 并行确定性（-j1 vs -j4，200 个函数） ==")
    big = os.path.join(ROOT, "tests/selfhost/s3_manyfns.qma")
    outs = []
    for j in ("1", "4"):
        p = os.path.join(BUILD, f"qlmc_par_j{j}.exe")
        try:
            build_with(_exe_runner(QLMC) + ["build", big, "-o", p, "-j", j], p)
            outs.append(p)
        except RuntimeError as ex:
            bad(f"-j{j} 构建失败：{ex}")
    if len(outs) == 2:
        d0 = open(outs[0], "rb").read()
        d1 = open(outs[1], "rb").read()
        if d0 == d1:
            ok(f"-j1 与 -j4 产物逐字节相同（{len(d0)} 字节）")
        else:
            bad(f"-j1 与 -j4 产物不同（{len(d0)} vs {len(d1)} 字节）")
        try:
            os.chmod(outs[1], 0o755)
        except OSError:
            pass
        r = subprocess.run(_exe_runner(outs[1]), capture_output=True)
        if r.returncode == 0 and r.stdout == b"123013\n":
            ok("-j4 产物运行结果正确（200 个函数的累加）")
        else:
            bad(f"-j4 产物运行异常 rc={r.returncode} out={r.stdout[:60]!r}")

    print("-" * 52)
    print(f"PASS={npass} FAIL={nfail}")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
