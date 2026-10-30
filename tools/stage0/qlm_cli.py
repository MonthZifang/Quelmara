#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quelmara 统一命令行入口（SPEC §8）
================================
  quelmara build <src>      编译（默认当前平台自研后端）
  quelmara run   <src>      编译并运行
  quelmara test  [path]     运行 test "name" { } 内建测试（默认当前平台自研后端）
  quelmara fmt   [path]     官方格式化器（--check 只检查）
  quelmara doc   [path]     文档生成（/// doc comment -> Markdown/JSON）
  quelmara bench <src>      基准测试 + 回归对比（--baseline / --update-baseline）
  quelmara debug <src|exe>  带调试信息构建 + 源码级调试器（v1.62，Windows PE）
  quelmara cache [--stat]   增量编译缓存（v1.90：查看 / 清空 / 按龄清理）
  quelmara link  <a.qla...> 链接多份 .qla -> 可执行文件（v2.09）
  quelmara qla   [--stat]   查看 / 校验 .qla 目标文件（v2.09）
  quelmara version          版本与后端能力

通用选项：
  --target native|win|arm64|c|both   代码生成后端（默认当前平台自研后端）
  -o, --out PATH                 输出路径
  --dump-ir                      打印 QuIR
  --no-opt                       关闭优化管线
  --no-cache                     跳过增量缓存，强制重编（等价 QLM_NO_CACHE=1）
  --dbg-info                     发射 .qlmdbg 调试节（仅 win 后端；默认构建
                                  逐字节不变，见 06-status.md）

设计原则：所有子命令都读取项目根目录的 Quelmara.toml（唯一全局资源开关）。
"""

import argparse
import concurrent.futures
import glob
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qlm_cache  # noqa: E402  —— 缓存模块不依赖编译器：命中路径不许导入 qlm

# 源码扩展名，与 `qlm.SRC_EXT` 同值。**刻意不 import qlm 去取**：`import qlm`
# 在本机要 1.3 s，而缓存命中的整条路径只该花几十毫秒；扩展名口径由
# `tools/dev/check_names.py` 门禁守着，两边不会漂。
SRC_EXT = ".qma"


def require_source(path):
    """扩展名校验：只有真的不是 `.qma` 时才导入 qlm 拿完整迁移提示。"""
    if os.path.splitext(path)[1].lower() == SRC_EXT:
        return
    from qlm import require_source as _rs
    _rs(path)

# 版本号口径：与 docs/versions/ 下的目录一致（vX.Y → "X.Y.0"，补丁 → "X.Y.Z"）
VERSION = "3.22.0"

def _default_target():
    """当前主机默认只选自研后端；不把 C99 当产品默认链路。"""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows" and machine in ("amd64", "x86_64", "x64"):
        return "win"
    if system == "linux":
        if machine in ("aarch64", "arm64"):
            return "arm64"
        if machine in ("amd64", "x86_64", "x64"):
            return "native"
    # Unsupported host: leave the default unset so an explicit --target c
    # remains usable for bootstrap/migration workflows.
    return None


DEFAULT_TARGET = _default_target()


# ---------------------------------------------------------------------------
# 后端适配层
# ---------------------------------------------------------------------------

def _build_native(src, out, dump_ir=False, optimize=True):
    import qlm_native as N
    blob, cfg = N.transpile_native(src, dump_ir=dump_ir, optimize=optimize)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    N.write_elf(out, blob)
    return out, len(blob), cfg


def _build_arm64(src, out, dump_ir=False, optimize=True):
    import qlm_arm64 as A
    # transpile_a64 只返回 (blob, cfg)：ELF 头/程序头由 write_elf_a64 写出。
    # 之前直接把 2 元组当 (out, size, cfg) 返回，CLI 一解包就 ValueError。
    blob, cfg = A.transpile_a64(src, dump_ir=dump_ir, optimize=optimize)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    A.write_elf_a64(out, blob)
    return out, len(blob), cfg


def _build_c(src, out, dump_ir=False, optimize=True, cc=True):
    import qlm as R
    c_code, cfg = R.transpile(src)
    base = os.path.splitext(os.path.basename(src))[0]
    out_c = os.path.join("build", base + ".c")
    os.makedirs("build", exist_ok=True)
    with open(out_c, "w", encoding="utf-8") as f:
        f.write(c_code)
    if not cc:
        return out_c, len(c_code), cfg
    cc_cmd = ["cc", "-std=gnu11", "-O2", "-pthread", "-o", out, out_c]
    subprocess.check_call(cc_cmd, stdout=subprocess.DEVNULL)
    return out, os.path.getsize(out), cfg


def _build_win(src, out, dump_ir=False, optimize=True, dbg=False):
    import qlm_pe as W
    pe, cfg = W.transpile_win(src, dump_ir=dump_ir, optimize=optimize, dbg=dbg)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    W.write_exe(out, pe)
    return out, len(pe), cfg


# 产物扩展名（docs/EXTENSIONS.md）：.qex = PE 可执行，.qel = ELF 可执行，.c = 交叉验证
OUT_EXT = {"win": ".qex", "native": ".qel", "arm64": ".qel", "c": ".c"}

BACKENDS = {
    "native": _build_native,
    "c": _build_c,
    "arm64": _build_arm64,
    "win": _build_win,
}


# 能进缓存的后端：C99 要走外部 cc、且只做交叉验证，不缓存
CACHEABLE = ("win", "native", "arm64")


class _NoRec(object):
    """占位：不缓存时也要能进 `with` 语句。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def build(src, target=DEFAULT_TARGET, out=None, dump_ir=False, optimize=True,
          dbg_info=False, cache=True):
    """编译一个单元，返回 `(out, size, cfg, info)`。

    `info` 说明这一趟是命中还是重编：`{"cache": "hit"|"miss"|"off",
    "why": 原因, "ms": 耗时, "key": 缓存键}`。

    `--dump-ir` 不进缓存（它的产物是 stdout）；`--no-cache` / `QLM_NO_CACHE=1`
    强制重编。缓存键、闭包、失效条件见 `qlm_cache.py` 模块头。
    """
    base = os.path.splitext(os.path.basename(src))[0]
    if target is None:
        raise RuntimeError("当前主机没有自研默认后端；请显式指定 --target c（仅交叉验证/自举）或安装受支持的目标工具链")
    if out is None:
        out = os.path.join("build", base + OUT_EXT.get(target, ""))
    if dbg_info and target != "win":
        raise RuntimeError("--dbg-info 只支持 --target win（.qlmdbg 调试节目前只随 PE 发出）")
    fn = BACKENDS[target]
    t0 = time.perf_counter()
    info = {"cache": "off", "why": "", "ms": 0.0, "key": ""}

    use_cache = (cache and target in CACHEABLE and not dump_ir
                 and not os.environ.get("QLM_NO_CACHE"))
    root = key = man = None
    if use_cache:
        try:
            root = qlm_cache.project_root(src)
            key, man = qlm_cache.unit_key(src, target, optimize, dbg_info, root)
            info["key"] = key
            hit = qlm_cache.fetch(key, man, out, root)
        except Exception as exc:              # noqa: BLE001
            # 缓存是加速件，不是正确性依赖：它自己出错必须让路给编译
            hit = None
            info["why"] = f"缓存异常 {type(exc).__name__}: {exc}"
        if hit:
            info.update(cache="hit", ms=(time.perf_counter() - t0) * 1000.0,
                        cfg=hit.get("cfg"))
            return out, hit.get("size", 0), hit.get("cfg") or {}, info
        info.update(cache="miss",
                    why=info["why"] or qlm_cache.LAST_REASON or "未命中")

    rec = qlm_cache.Closure(root) if key else _NoRec()
    with rec:
        if target == "win":
            # --dbg-info 只对 Windows PE 有意义（.qlmdbg 调试节 + qlm_dbg）
            out, size, cfg = fn(src, out, dump_ir=dump_ir, optimize=optimize,
                                dbg=dbg_info)
        else:
            out, size, cfg = fn(src, out, dump_ir=dump_ir, optimize=optimize)
    info["ms"] = (time.perf_counter() - t0) * 1000.0
    if key:
        # 闭包为空就不写缓存（记录失败的条目比没有缓存更危险）。
        # 写缓存失败绝不能影响"已经编好了"这个事实。
        try:
            qlm_cache.store(key, man, out, rec.files(root), info["ms"], root, cfg)
        except Exception:                     # noqa: BLE001
            pass
    return out, size, cfg, info


def _cache_tag(info):
    """一行缓存状态，供 build/run/test 打印。"""
    kind = info.get("cache")
    if kind == "hit":
        return f"缓存命中 {info.get('ms', 0):.0f} ms"
    if kind == "miss":
        return f"重编 {info.get('ms', 0):.0f} ms（{info.get('why') or '未命中'}）"
    return f"缓存关闭 {info.get('ms', 0):.0f} ms"


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

SELFHOST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "build", "selfhost")
EXE_SUFFIX = ".qex" if os.name == "nt" else ".qel"


def stage1_lexer():
    """stage-1 自举词法器：存在就优先用（这才是"用 Quelmara 写编译器"的落地）"""
    cand = os.path.join(SELFHOST_DIR, "qlm_lex" + EXE_SUFFIX)
    return cand if os.path.isfile(cand) else None


def cmd_lex(args):
    require_source(args.src)
    exe = None if args.stage0 else stage1_lexer()
    if exe:
        print(f"[qlm:stage1] {exe}")
        return subprocess.call([exe, args.src])
    print("[qlm:stage0] tools/dev/tokfmt.py")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "dev"))
    import tokfmt
    src = open(args.src, encoding="utf-8").read()
    sys.stdout.buffer.write(tokfmt.dump(src).encode("utf-8"))
    return 0


def _build_unit(job):
    """并行构建的一个单元（模块级函数：spawn 起进程时闭包过不去）。"""
    src, target, out, no_opt, dbg_info, cache = job
    try:
        o, size, _cfg, info = build(src, target, out, optimize=not no_opt,
                                    dbg_info=dbg_info, cache=cache)
        return src, o, size, info, None
    except Exception as exc:                  # noqa: BLE001
        return src, None, 0, {}, f"{type(exc).__name__}: {exc}"


def _qla_compile(src, out_qla, kind="program", reuse_path=None, lib_paths=(),
                 optimize=True):
    """v2.11：编译到 `.qla`（目标文件），返回 (arc, meta, 耗时 ms)。

    旧档案不兼容（换了编译器/配置/优化档）时**退回全量重编**并说明原因——
    `--incr` 是"省时间"的开关，不该因为档案过期就编译失败；而 `--lib-input`
    的档案不兼容仍然是硬错误（少一个库不能静默降级）。
    """
    import qlm_pe
    import qlm_qla
    t0 = time.perf_counter()
    reuse = None
    stale = ""
    if reuse_path and os.path.isfile(reuse_path):
        reuse = qlm_qla.Archive.load(reuse_path)
    libs = [qlm_qla.Archive.load(p) for p in lib_paths]
    try:
        arc, meta, _cfg = qlm_pe.emit_archive(src, optimize=optimize, kind=kind,
                                              libs=libs, reuse=reuse)
    except SyntaxError as exc:
        if reuse is None or "增量档案" not in str(exc):
            raise
        stale = str(exc).split("——")[0]
        arc, meta, _cfg = qlm_pe.emit_archive(src, optimize=optimize, kind=kind,
                                              libs=libs, reuse=None)
    arc.save(out_qla)
    if stale:
        meta = dict(meta)
        meta["stale"] = stale
    return arc, meta, (time.perf_counter() - t0) * 1000.0


def _qla_tag(meta):
    if meta and meta.get("stale"):
        return f"旧档案不兼容（{meta['stale']}）→ 全量重编"
    if not meta or not meta.get("nreused"):
        return "全量降级"
    return (f"复用 {meta['nreused']}/{meta['ntotal']} 函数"
            f"（IR {meta.get('irreused', 0)}/{meta.get('irtotal', 0)} 条）")


def cmd_build(args):
    if getattr(args, "dump_ir_json", False):
        args.dump_ir = "json"
    srcs = args.src if isinstance(args.src, list) else [args.src]
    if len(srcs) > 1 and args.out:
        print("[qlm] 多源构建不能用 -o（每个源各自落到 build/<名字>）")
        return 2
    if len(srcs) > 1 and args.dump_ir:
        print("[qlm] 多源构建不支持 --dump-ir（IR 输出会互相穿插）")
        return 2
    # v2.08：`.qla` 目标文件 / 函数级增量 / 二进制库输入
    want_qla = getattr(args, "emit_qla", False) or getattr(args, "lib", False)
    incr = getattr(args, "incr", False)
    lib_inputs = list(getattr(args, "lib_input", None) or [])
    if (want_qla or incr or lib_inputs) and args.target != "win":
        print("[qlm] `.qla` 目前只支持 --target win（IR 与 ABI 都按 PE/x86-64 固化）")
        return 2
    if (want_qla or incr or lib_inputs) and args.dbg_info:
        print("[qlm] `--dbg-info` 不走档案（链接产物不带 .qlmdbg，断点调试请直接构建）")
        return 2
    if (want_qla or incr or lib_inputs) and len(srcs) > 1:
        print("[qlm] `.qla` 构建一次只能给一个源（-j 并行是 exe 构建的功能）")
        return 2

    if want_qla or incr or lib_inputs:
        src = srcs[0]
        kind = "lib" if getattr(args, "lib", False) else "program"
        if args.out and (want_qla or args.out.endswith(".qla")):
            out_qla = args.out          # 只要档案：-o 指的就是档案路径
        else:
            out_qla = os.path.join("build",
                                   os.path.splitext(os.path.basename(src))[0]
                                   + ".qla")
        arc, meta, ms = _qla_compile(
            src, out_qla, kind=kind,
            reuse_path=out_qla if incr else None,
            lib_paths=lib_inputs, optimize=not args.no_opt)
        n = os.path.getsize(out_qla)
        print(f"[qlm] {src} -> {out_qla}  ({n} 字节, {len(arc.funcs)} 函数, "
              f"{arc.ninstrs()} 条 IR, kind={kind})")
        print(f"[qlm] {_qla_tag(meta)} | {ms:.0f} ms"
              + (f" | 未定义符号 {len(arc.undefined)}" if arc.undefined else ""))
        if want_qla:
            return 0
        # 不只要档案：接着链接出可执行文件
        import qlm_pe
        import qlm_qla
        arcs = [arc] + [qlm_qla.Archive.load(p) for p in lib_inputs]
        pe, _link = qlm_pe.link_win(arcs)
        if args.out and args.out.endswith(".qla"):
            out = os.path.splitext(args.out)[0] + ".qex"   # -o 指的是档案
        else:
            out = args.out or os.path.join(
                "build", os.path.splitext(os.path.basename(src))[0] + ".qex")
        qlm_pe.write_exe(out, pe)
        print(f"[qlm] 链接 {len(arcs)} 份档案 -> {out}  ({len(pe)} 字节)")
        return 0

    if len(srcs) > 1:
        jobs = args.jobs if getattr(args, "jobs", 0) > 0 else min(_default_jobs(),
                                                                 len(srcs))
        work = [(s, args.target, None, args.no_opt, args.dbg_info,
                 not args.no_cache) for s in srcs]
        print(f"[qlm] {len(srcs)} 个单元，并发 {jobs}，target={args.target}")
        if jobs > 1:
            with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as ex:
                results = list(ex.map(_build_unit, work))
        else:
            results = [_build_unit(w) for w in work]
        bad = 0
        hits = 0
        for src, out, size, info, err in results:
            if err:
                bad += 1
                print(f"[qlm] ❌ {src}: {err.splitlines()[0][:100]}")
                continue
            hits += 1 if info.get("cache") == "hit" else 0
            print(f"[qlm] ✅ {src} -> {out}  ({size} 字节) | {_cache_tag(info)}")
        print(f"[qlm] 完成 {len(srcs) - bad}/{len(srcs)}，缓存命中 {hits}")
        return 0 if bad == 0 else 1

    out, size, cfg, info = build(srcs[0], args.target, args.out,
                                 dump_ir=args.dump_ir, optimize=not args.no_opt,
                                 dbg_info=args.dbg_info, cache=not args.no_cache)
    print(f"[qlm] {srcs[0]} -> {out}  ({size} 字节, target={args.target}"
          f"{', dbg-info' if args.dbg_info else ''})")
    print(f"[qlm] config: {cfg.get('_path') or '(默认)'} | "
          f"multicore={cfg['core']['multicore']} "
          f"threads={cfg['core']['threads'] or 'auto'} "
          f"opt={cfg['build']['opt']} | {_cache_tag(info)}")
    return 0


def cmd_link(args):
    """quelmara link（v2.08）：多份 `.qla` -> 一个可执行文件。

    链接是**名字解析**：`call` / `fnaddr` / vtable 槽都按名字找定义，
    全局数据区按单元拼接，运行库 helper 同名去重（全进程一个堆）。
    """
    import qlm_pe
    import qlm_qla
    try:
        arcs = [qlm_qla.Archive.load(p) for p in args.inputs]
        pe, link = qlm_pe.link_win(arcs)
    except qlm_qla.LinkError as exc:
        print(f"[qlm-link] ❌ {exc}")
        return 1
    out = args.out or os.path.join(
        "build", os.path.splitext(os.path.basename(args.inputs[0]))[0] + ".qex")
    qlm_pe.write_exe(out, pe)
    units = " + ".join(a.unit for a in arcs)
    print(f"[qlm-link] {units} -> {out}  ({len(pe)} 字节, "
          f"{len(link.funcs)} 函数, {len(link.globals)} 个全局块)")
    return 0


def cmd_qla(args):
    """quelmara qla（v2.08）：查看 / 校验 `.qla` 目标文件。"""
    import qlm_qla
    if args.symbols:
        print(f"[qlm-qla] {args.symbols} 的符号表：")
        print(qlm_qla.symbols(args.symbols))
        return 0
    if args.verify:
        try:
            arc = qlm_qla.Archive.load(args.verify)
        except Exception as exc:                      # noqa: BLE001
            print(f"[qlm-qla] ❌ {args.verify}: {exc}")
            return 1
        print(f"[qlm-qla] ✅ {args.verify} 校验通过"
              f"（{len(arc.funcs)} 函数 / {arc.ninstrs()} 条 IR）")
        return 0
    if not args.stat:
        print("[qlm-qla] 用法：qla --stat FILE | --symbols FILE | --verify FILE")
        return 2
    print(qlm_qla.describe(args.stat))
    return 0


def cmd_run(args):
    if getattr(args, "dump_ir_json", False):
        args.dump_ir = "json"
    out, size, cfg, info = build(args.src, args.target, args.out,
                                 dump_ir=args.dump_ir, optimize=not args.no_opt,
                                 dbg_info=args.dbg_info, cache=not args.no_cache)
    print(f"[qlm] exec {out}  ({_cache_tag(info)})")
    if args.target == "arm64":
        # AArch64 ELF 不能在 x86/Windows 主机上直接跑：走 tests/a64_emu.py
        # 模拟器（执行级验证，与 cmd_test 同一条路径）。
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        a64_emu = os.path.join(root, "tests", "a64_emu.py")
        if not os.path.isfile(a64_emu):
            print("[qlm] 找不到 tests/a64_emu.py，无法执行 arm64 产物")
            return 1
        return subprocess.call([sys.executable, a64_emu,
                                os.path.abspath(out)] + (args.args or []))
    rc = subprocess.call([os.path.abspath(out)] + (args.args or []))
    return rc


def cmd_cov(args):
    """quelmara cov（v1.83）：行 + 分支覆盖率。

    三段分工：`--dbg-info` 构建 → 调试器采集（Windows 调试 API，Python 侧）
    → **Quelmara 写的 `tools/qlm_cov.qma`** 汇总（行/分支/函数/文件 + 门禁）。
    `--append` 把本次命中累加进已有日志：多次运行（不同输入 / 不同测试）
    的覆盖率合并到一份，而不是互相覆盖。"""
    out, _size, _cfg, _info = build(args.src, "win", args.out,
                                   optimize=not args.no_opt, dbg_info=True,
                                   cache=not args.no_cache)
    print(f"[qlm] cov build -> {out}")
    hits = args.hits or os.path.join("build", "qlm_cov.tsv")
    os.makedirs(os.path.dirname(hits) or ".", exist_ok=True)
    import qlm_dbg
    dbg_argv = ["--cov-lines-only"] if args.lines_only else []
    append = bool(args.append) and os.path.isfile(hits)
    run_path = hits + ".run" if append else hits
    rc = qlm_dbg.main([out, "--cov", run_path] + dbg_argv
                      + list(args.args or []))
    if rc != 0:
        return rc
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    tool_src = os.path.join(root, "tools", "qlm_cov.qma")
    if not os.path.isfile(tool_src):
        print(f"[qlm] 找不到 {tool_src}（覆盖率工具是 Quelmara 写的）")
        return 1
    tool_exe = os.path.join("build", "qlm_cov.exe")
    if (not os.path.isfile(tool_exe)
            or os.path.getmtime(tool_exe) < os.path.getmtime(tool_src)):
        tool_exe, _s2, _c2, _i2 = build(tool_src, "win", tool_exe,
                                       cache=not args.no_cache)
    cmd = [os.path.abspath(tool_exe), os.path.abspath(out)]
    if append:
        cmd += [os.path.abspath(run_path), os.path.abspath(hits),
                "--merge-out", os.path.abspath(hits)]
    else:
        cmd.append(os.path.abspath(hits))
    if args.lines_only:
        cmd.append("--no-branch")
    if args.min is not None:
        cmd += ["--min", str(args.min)]
    if args.min_branch is not None:
        cmd += ["--min-branch", str(args.min_branch)]
    return subprocess.call(cmd)


def cmd_fuzz(args):
    """quelmara fuzz（v1.83）：编译器前端模糊测试。

    变异器是 Quelmara 写的（`tools/qlm_fuzz.qma`），判定与报告在
    `tools/stage0/qlm_fuzz.py`（要在进程里跑前端，且要限时/分类异常）。"""
    import qlm_fuzz
    argv = [args.src, "--cases", str(args.cases), "--seed", str(args.seed),
            "--timeout-ms", str(args.timeout_ms),
            "--max-seconds", str(args.max_seconds)]
    if args.out:
        argv += ["--out", args.out]
    if args.emit:
        argv.append("--emit")
    return qlm_fuzz.main(argv)


def _discover_tests(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, fs in os.walk(p):
                dirs[:] = [d for d in dirs
                           if d not in ("build", "__pycache__", ".git", "single_core")]
                files += [os.path.join(root, f) for f in fs if f.endswith(SRC_EXT)]
        elif os.path.isfile(p):
            files.append(p)
    out = []
    for f in sorted(files):
        with open(f, encoding="utf-8") as fh:
            if 'test "' in fh.read():
                out.append(f)
    return out


def _default_jobs():
    """并行构建的默认并发数：核数，但不超过 8（每个 worker 都是一个完整
    编译器进程，再多只是互相抢内存和文件缓存）。"""
    return max(1, min(os.cpu_count() or 1, 8))


def _test_out_path(f, target):
    """每个单元一个独立产物路径。

    并行时 `tests/a/x.qma` 与 `tests/b/x.qma` 会同时构建，按 basename
    落到 `build/x.qex` 会互相覆盖——产物被覆盖 = 跑到别人的程序，
    这是并行编译最容易踩的坑，所以路径里必须带文件身份。
    """
    base = os.path.splitext(os.path.basename(f))[0]
    tag = hashlib.sha256(os.path.abspath(f).encode("utf-8")).hexdigest()[:6]
    return os.path.join("build", "_test", f"{base}_{tag}{OUT_EXT.get(target, '')}")


def _can_exec(t, is_win, a64_emu):
    """本机能不能执行该后端的产物。"""
    host = "win" if is_win else "native"
    if t == host:
        return True
    if t == "arm64" and os.path.isfile(a64_emu):
        return True                     # A64 模拟器全平台可跑（执行级）
    if t == "c" and not is_win:
        return True                     # POSIX 默认有 cc
    return False


def _run_prod(t, out, a64_emu):
    """执行产物，返回 (returncode, stdout)；arm64 走模拟器。"""
    if t == "arm64":
        r = subprocess.run([sys.executable, a64_emu, os.path.abspath(out)],
                           capture_output=True, encoding="utf-8",
                           errors="replace", timeout=300)
        return r.returncode, r.stdout
    r = subprocess.run([os.path.abspath(out)], capture_output=True,
                       encoding="utf-8", errors="replace", timeout=300)
    return r.returncode, r.stdout


def _test_unit(job):
    """一个编译单元：逐 target 构建 + 执行 + 跨后端比对。

    **必须是模块级函数**：并行时由 `ProcessPoolExecutor` 用 spawn 起进程，
    闭包和 lambda 过不去。返回 (行, passed, failed, skipped)，
    行由父进程按文件顺序打印——并行不改变输出顺序。
    """
    f, targets, no_opt, is_win, a64_emu, cache = job
    lines, passed, failed, skipped = [], 0, 0, 0
    outs = {}
    for t in targets:
        tag = f"{f} [{t}]"
        try:
            out, _size, _cfg, _info = build(f, t, out=_test_out_path(f, t),
                                            optimize=not no_opt, cache=cache)
        except Exception as e:
            lines.append(f"  ⏭️  {tag} 构建不可用：{str(e).splitlines()[0][:80]}")
            skipped += 1
            continue
        if not _can_exec(t, is_win, a64_emu):
            lines.append(f"  ⏭️  {tag} 本机不能执行该产物（构建成功）")
            skipped += 1
            continue
        try:
            rc, stdout = _run_prod(t, out, a64_emu)
        except Exception as e:
            lines.append(f"  ❌ {tag} 执行异常：{e}")
            failed += 1
            continue
        if rc == 0:
            lines.append(f"  ✅ {tag}")
            passed += 1
            outs[t] = stdout
        else:
            lines.append(f"  ❌ {tag}（退出码 {rc}）")
            failed += 1
    # 跨后端输出一致性：所有可执行目标的 stdout 必须逐字节一致
    if len(outs) >= 2:
        vals = list(outs.values())
        if all(v == vals[0] for v in vals[1:]):
            lines.append(f"  ✅ {f} 跨后端输出一致（{' vs '.join(outs)}）")
            passed += 1
        else:
            lines.append(f"  ❌ {f} 跨后端输出不一致（{' vs '.join(outs)}）")
            failed += 1
    return lines, passed, failed, skipped


def cmd_test(args):
    paths = args.paths or ["tests", "examples"]
    files = _discover_tests(paths)
    if not files:
        print("[qlm-test] 没有找到 test \"name\" { } 测试块")
        return 1

    # 目标矩阵：--targets all / --targets a,b 优先，其次 --target 单数，最后默认。
    if getattr(args, "targets", None):
        ts = [t.strip() for t in args.targets.split(",") if t.strip()]
        targets = (["native", "win", "arm64", "c"] if ts == ["all"] else ts)
        bad = [t for t in targets
               if t not in ("native", "win", "arm64", "c")]
        if bad:
            print(f"[qlm-test] 未知目标：{', '.join(bad)}"
                  f"（可选 native/win/arm64/c/all）")
            return 1
    elif args.target == "both":
        targets = ["native", "c"]
    elif args.target:
        targets = [args.target]
    else:
        # 默认回归只验证当前平台的自研后端；C 后端必须显式指定。
        targets = [DEFAULT_TARGET]

    is_win = (os.name == "nt")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a64_emu = os.path.join(root, "tests", "a64_emu.py")

    jobs = getattr(args, "jobs", 0) or 0
    if jobs <= 0:
        jobs = min(_default_jobs(), len(files))
    cache = not getattr(args, "no_cache", False)
    work = [(f, targets, getattr(args, "no_opt", False), is_win, a64_emu, cache)
            for f in files]

    # 并行粒度是**单元**：每个 worker 独立编译独立文件（进程隔离，
    # 不共享 GIL、不共享编译器状态）。输出仍按文件顺序打印。
    if jobs > 1 and len(work) > 1:
        print(f"[qlm-test] {len(work)} 个文件 / {len(targets)} 个后端，"
              f"并发 {jobs}")
        with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as ex:
            results = list(ex.map(_test_unit, work))
    else:
        results = [_test_unit(j) for j in work]

    passed = failed = skipped = 0
    for lines, p, f_, s in results:
        for ln in lines:
            print(ln)
        passed += p
        failed += f_
        skipped += s
    print("-" * 48)
    print(f"PASS={passed} FAIL={failed} SKIP={skipped}")
    return 0 if failed == 0 else 1


def cmd_fmt(args):
    import qlm_fmt
    argv = list(args.paths or [])
    if args.check:
        argv.append("--check")
    if args.quiet:
        argv.append("-q")
    sys.argv = ["quelmara fmt"] + argv
    qlm_fmt.main()
    return 0


def cmd_doc(args):
    """quelmara doc（v1.92）：doc comment -> Markdown / JSON。

    退出码透传（`--check` 不一致、`--missing` 有缺文档都返回 1），
    因此可以直接当门禁：`quelmara doc std/ --missing`。"""
    import qlm_doc
    argv = list(args.paths or ["."])
    if args.out:
        argv += ["-o", args.out]
    if args.format:
        argv += ["--format", args.format]
    if args.title:
        argv += ["--title", args.title]
    if args.check:
        argv.append("--check")
    if args.missing:
        argv.append("--missing")
    if args.quiet:
        argv.append("-q")
    return qlm_doc.main(argv)


def _bench_key(target):
    """基线 key：平台/架构/后端 —— 跨平台基线必须按这个三元组分开存。"""
    return f"{platform.system().lower()}/{platform.machine().lower()}/{target}"


def _bench_norm(text):
    """输出归一化：去掉行尾空白与末行空行，避免换行风格造成假不一致。"""
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()


def _bench_run(exe, target, runs):
    """跑 runs 次，返回 (best_s, out_hash, first_line)。arm64 走自研模拟器。"""
    import hashlib
    if target == "arm64":
        emu = os.path.join(ROOT, "tests", "a64_emu.py")
        if not os.path.isfile(emu):
            return None, None, "(无 a64 模拟器)"
        cmd = [sys.executable, emu, exe]
    else:
        cmd = [os.path.abspath(exe)]
    times, out = [], ""
    for _ in range(max(1, runs)):
        t0 = time.perf_counter()
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        times.append(time.perf_counter() - t0)
        out = r.stdout
    norm = _bench_norm(out)
    return min(times), hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16], (
        norm.splitlines()[0][:60] if norm else "")


def cmd_bench(args):
    """基准 + 跨平台基线。

    基线记录 key = 平台/架构/后端/源文件名：
      - 时间只在同一 key 内比较（换机器/换后端没有可比性）
      - 输出哈希则跨 key 比较：同一份源码在不同后端必须产出相同结果，
        这才是"跨平台"真正要守住的东西。
    """
    base_path = args.baseline or os.path.join(ROOT, "bench", "baseline.json")
    targets = ([t.strip() for t in args.targets.split(",") if t.strip()]
               if args.targets else [args.target])
    name = os.path.splitext(os.path.basename(args.src))[0]

    data = {}
    if os.path.isfile(base_path):
        with open(base_path, encoding="utf-8") as f:
            data = json.load(f)
    entries = data.setdefault("entries", {})
    data.setdefault("version", 1)

    print(f"[qlm-bench] {args.src}  targets={','.join(targets)}  runs={args.runs}")
    results = {}
    rc = 0
    for tg in targets:
        if tg == "c":
            print(f"  {tg:<7} 跳过（C99 只做交叉验证，不计入基线）")
            continue
        try:
            out, size, _cfg, _info = build(args.src, tg, None,
                                           optimize=not args.no_opt,
                                           cache=not args.no_cache)
        except Exception as exc:                      # noqa: BLE001
            print(f"  {tg:<7} 构建失败：{type(exc).__name__}: {exc}")
            rc = 2
            continue
        best, oh, first = _bench_run(out, tg, args.runs)
        if best is None:
            print(f"  {tg:<7} 无法执行：{first}")
            continue
        key = f"{_bench_key(tg)}/{name}"
        results[tg] = {"key": key, "best_ms": best * 1000.0, "size": size, "out": oh}
        print(f"  {tg:<7} size={size}B  best={best * 1000:.2f}ms  out={oh}  | {first}")

    # ---- 跨后端一致性：同一源码的输出哈希必须相同 ----
    hashes = {v["out"] for v in results.values()}
    if len(hashes) > 1:
        print("  [FAIL] 跨后端输出不一致：")
        for tg, v in results.items():
            print(f"         {tg}: {v['out']}")
        rc = 2
    elif hashes:
        print(f"  [ok]   跨后端输出一致（{len(results)} 个后端，sha={hashlib_short(hashes)}）")

    if args.update_baseline:
        for tg, v in results.items():
            entries[v["key"]] = {"best_ms": round(v["best_ms"], 3), "size": v["size"],
                                 "out": v["out"], "runs": args.runs,
                                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                 "version": VERSION}
        os.makedirs(os.path.dirname(base_path), exist_ok=True)
        with open(base_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        print(f"  baseline 已更新 -> {os.path.relpath(base_path, ROOT)}")
        return rc

    # ---- 与基线对比 ----
    if not entries:
        print(f"  （无基线 {os.path.relpath(base_path, ROOT)}，用 --update-baseline 建立）")
        return rc
    for tg, v in results.items():
        prev = entries.get(v["key"])
        if not prev:
            print(f"  {tg:<7} 无基线记录（{v['key']}）")
            continue
        if prev.get("out") and prev["out"] != v["out"]:
            print(f"  {tg:<7} [FAIL] 输出与基线不一致：{prev['out']} -> {v['out']}")
            rc = 2
        if prev.get("best_ms"):
            delta = (v["best_ms"] - prev["best_ms"]) / prev["best_ms"] * 100.0
            flag = "REGRESSION" if delta > args.threshold else ("faster" if delta < -args.threshold else "ok")
            print(f"  {tg:<7} 基线 {prev['best_ms']:.2f}ms -> {v['best_ms']:.2f}ms "
                  f"({delta:+.1f}%)  [{flag}]")
            if flag == "REGRESSION":
                rc = 2
    return rc


def hashlib_short(hashes):
    return ",".join(sorted(hashes))


def cmd_debug(args):
    """quelmara debug（v1.70）：带调试信息构建 + 启动源码级调试器。

    传 .qma 源文件 -> --dbg-info 构建（win 后端）后调试；
    传构建产物（.qex/.exe）-> 直接调试（须已带 .qlmdbg 节）。
    其余参数（--script / 程序参数）原样转给 qlm_dbg。"""
    src = args.src
    if src.endswith(SRC_EXT):
        if (args.target or "win") != "win":
            print("[qlm] 调试信息只支持 --target win（.qlmdbg 节目前只随 PE 发出）")
            return 1
        out, _size, _cfg, _info = build(src, "win", args.out,
                                       optimize=not args.no_opt, dbg_info=True,
                                       cache=not args.no_cache)
        print(f"[qlm] debug build -> {out}")
    else:
        out = src
    import qlm_dbg
    argv = [out]
    if args.script:
        argv += ["--script", args.script]
    if args.args:
        argv += ["--"] + args.args
    return qlm_dbg.main(argv)


def cmd_cache(args):
    """quelmara cache（v1.90）：查看 / 清空 / 按龄清理增量缓存。

    缓存位置：项目根（含 Quelmara.toml 的目录）下的 `.qlmcache/`；
    `QLM_CACHE_DIR` 可改到别处（测试与多工程隔离用）。
    """
    if args.clear:
        n = qlm_cache.clear()
        print(f"[qlm-cache] 已清空 {n} 个条目（{qlm_cache.cache_root()}）")
        return 0
    if args.prune is not None:
        days = args.prune if args.prune > 0 else 14
        n = qlm_cache.prune(days)
        print(f"[qlm-cache] 已清理 {n} 个超过 {days} 天未使用的条目")
    st = qlm_cache.stats()
    mb = st.get("bytes", 0) / (1024.0 * 1024.0)
    print(f"[qlm-cache] 目录: {st['dir']}")
    print(f"[qlm-cache] 条目: {st.get('entries', 0)} 个，占用 {mb:.2f} MiB")
    hits, miss = int(st.get("hit", 0)), int(st.get("miss", 0))
    total = hits + miss
    rate = (100.0 * hits / total) if total else 0.0
    print(f"[qlm-cache] 命中: {hits} / 未命中: {miss}（命中率 {rate:.0f}%），"
          f"累计省下约 {int(st.get('saved_ms', 0)) / 1000.0:.1f} s")
    if st.get("oldest"):
        print(f"[qlm-cache] 最近写入: "
              f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(st['newest']))}")
    return 0


def cmd_lsp(args):
    """quelmara lsp（v1.91）：语言服务器。实现全在 `qlm_lsp.py`。

    这里只做参数转发，不重复定义行为——`lsp` 的选项（`--index` / `--check`
    / `--completions` …）与直接跑 `python tools/stage0/qlm_lsp.py` 完全一致。
    """
    import qlm_lsp
    argv = []
    for flag, val in (("--index", args.index), ("--symbols", args.symbols),
                      ("--at", args.at), ("--completions", args.completions),
                      ("--check", args.check), ("--root", args.root)):
        if val:
            argv += [flag, val]
    if args.trace:
        argv.append("--trace")
    if args.stdio:
        argv.append("--stdio")
    return qlm_lsp.main(argv)


def cmd_version(args):
    print(f"Quelmara {VERSION}  ——  自研后端优先 · 多核默认 · 网络原生 · 全平台")
    print(f"  后端: native(x86_64 裸 ELF64) / win(x86_64 PE/COFF，无 CRT) / "
          f"arm64(AArch64 ELF64) / c(C99 交叉验证，不是产品后端)")
    print(f"  优化: 常量折叠 / 强度削减 / 魔数除法 / 内联 / CSE-GVN / LICM / 循环展开 / "
          f"DCE / 复制传播 / 线性扫描寄存器分配")
    print(f"  工具: build / run / test / fmt / doc / bench / debug / cov / fuzz / cache / lsp / link / qla")
    return 0


def main(argv=None):
    # Windows 控制台默认 GBK：统一按 UTF-8 输出，避免 ✅/中文诊断直接抛
    # UnicodeEncodeError（工具链自己的输出不能因为代码页而崩）。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(prog="quelmara", description="Quelmara 语言工具链")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, src=True):
        if src:
            p.add_argument("src")
        p.add_argument("--target", default=DEFAULT_TARGET,
                       choices=["native", "c", "arm64", "win", "both"],
                       help="代码生成后端（默认当前平台自研后端；c 仅用于显式交叉验证）")
        p.add_argument("-o", "--out", default=None)
        p.add_argument("--no-opt", action="store_true", help="关闭优化管线")
        p.add_argument("--dump-ir", action="store_true", help="打印 QuIR")
        p.add_argument("--dump-ir-json", action="store_true",
                       help="打印 QuIR 的 JSON 形式（供 tools/*.qma 自研分析工具消费）")
        p.add_argument("--no-cache", action="store_true",
                       help="跳过增量缓存强制重编（等价 QLM_NO_CACHE=1）")
        p.add_argument("--dbg-info", action="store_true",
                       help="发射 .qlmdbg 调试节（行表+变量表，仅 win 后端；"
                            "不带此flag的默认构建逐字节不变）")

    p = sub.add_parser("build", help="编译（可一次给多个源，-j 并行）")
    common(p, src=False)
    p.add_argument("src", nargs="+", help="一个或多个 .qma（多源时各自落到 build/）")
    p.add_argument("-j", "--jobs", type=int, default=0,
                   help="多源并行构建的并发数（默认核数，上限 8；1 = 串行）")
    p.add_argument("--emit-qla", action="store_true",
                   help="编译到 .qla 目标文件（QuIR + 符号表，不发射机器码）")
    p.add_argument("--lib", action="store_true",
                   help="作为二进制库编译：不做 DCE，全部函数进 .qla（可脱离源码分发）")
    p.add_argument("--incr", action="store_true",
                   help="函数级增量：复用 build/<名字>.qla 里未变的函数 IR，"
                        "产出 .qex（并把新档案写回）")
    p.add_argument("--lib-input", action="append", default=None, metavar="Q.LA",
                   help="链接输入的二进制库 .qla（可重复；只取签名与类型布局）")

    p = sub.add_parser("link", help="链接多份 .qla -> 可执行文件（v2.08）")
    p.add_argument("inputs", nargs="+", help="一个或多个 .qla（第一个通常是程序档案）")
    p.add_argument("-o", "--out", default=None, help="输出路径（默认 build/<首个>.qex）")

    p = sub.add_parser("qla", help="查看 / 校验 .qla 目标文件（v2.08）")
    p.add_argument("--stat", default=None, metavar="FILE", help="统计与元数据")
    p.add_argument("--symbols", default=None, metavar="FILE", help="导出符号表")
    p.add_argument("--verify", default=None, metavar="FILE", help="校验校验和与格式")

    p = sub.add_parser("run", help="编译并运行")
    common(p)
    p.add_argument("args", nargs="*", help="传给程序的参数")

    p = sub.add_parser("test", help="运行 test \"name\" { } 内建测试")
    p.add_argument("paths", nargs="*", help="文件或目录（默认 tests/ examples/）")
    p.add_argument("--target", default=None,
                   choices=["native", "c", "arm64", "win", "both"],
                   help="单后端（默认：Windows=win，POSIX=native+c 交叉验证）")
    p.add_argument("--targets", default=None,
                   help="多后端矩阵：逗号分隔（native,win,arm64,c）或 all="
                        "全部后端；可执行的做执行级+跨后端输出比对，"
                        "不可执行的做构建级 SKIP")
    p.add_argument("--no-opt", action="store_true")
    p.add_argument("--no-cache", action="store_true",
                   help="跳过增量缓存强制重编")
    p.add_argument("-j", "--jobs", type=int, default=0,
                   help="并行编译并发数（默认核数，上限 8；1 = 串行）")

    p = sub.add_parser("fmt", help="官方格式化器")
    p.add_argument("paths", nargs="*")
    p.add_argument("--check", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("doc", help="文档生成（v1.92：/// doc comment -> Markdown/JSON）")
    p.add_argument("paths", nargs="*", help=".qma 文件或目录（默认当前目录）")
    p.add_argument("-o", "--out", default=None, help="输出文件（缺省打印 stdout）")
    p.add_argument("--format", choices=["md", "json"], default=None,
                   help="输出格式（缺省按 -o 扩展名，否则 md）")
    p.add_argument("--title", default=None, help="Markdown 一级标题")
    p.add_argument("--check", action="store_true",
                   help="配合 -o：只校验输出与源码一致（退出码 1 = 漂移）")
    p.add_argument("--missing", action="store_true",
                   help="公开声明缺 /// 文档即失败（门禁用）")
    p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("lex", help="词法分析（优先用 stage-1 自举词法器）")
    p.add_argument("src")
    p.add_argument("--stage0", action="store_true",
                   help="强制用 stage-0（Python）词法器，用于对拍")

    p = sub.add_parser("bench", help="基准测试 + 回归对比")
    common(p)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--baseline", default=None)
    p.add_argument("--update-baseline", action="store_true")
    p.add_argument("--threshold", type=float, default=10.0,
                   help="回归阈值（百分比，默认 10%%）")
    p.add_argument("--targets", default=None,
                   help="跨平台基线：逗号分隔的多个后端，如 win,native,arm64")

    p = sub.add_parser("cov", help="行 + 分支覆盖率（v1.83：调试器采集 + Quelmara 工具汇总）")
    p.add_argument("src", help=".qma 源文件")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--hits", default=None, help="命中日志输出路径（默认 build/qlm_cov.tsv）")
    p.add_argument("--min", type=int, default=None, help="行覆盖率阈值（百分比，默认 80）")
    p.add_argument("--min-branch", type=int, default=None,
                   help="分支覆盖率阈值（百分比，默认 0 = 不设门禁）")
    p.add_argument("--append", action="store_true",
                   help="把本次命中累加进 --hits 已有日志（多次运行合并）")
    p.add_argument("--lines-only", action="store_true",
                   help="只采集行覆盖（不下分支断点，更快）")
    p.add_argument("--no-opt", action="store_true")
    p.add_argument("--no-cache", action="store_true", help="跳过增量缓存强制重编")
    p.add_argument("args", nargs="*",
                   help="传给被覆盖程序的参数（`--` 之后；配合 --append 可累计多条输入路径）")

    p = sub.add_parser("fuzz", help="编译器前端模糊测试（v1.83，变异器用 Quelmara 写）")
    p.add_argument("src", help="种子源码（.qma）")
    p.add_argument("--cases", type=int, default=64, help="用例数（默认 64）")
    p.add_argument("--seed", type=int, default=1, help="变异种子（默认 1，确定性）")
    p.add_argument("--out", default=None, help="用例目录（默认 build/fuzz/seed<N>）")
    p.add_argument("--timeout-ms", type=int, default=2000,
                   help="单例耗时上限（毫秒，超过只报告不失败）")
    p.add_argument("--max-seconds", type=float, default=120.0,
                   help="总时长预算（秒）")
    p.add_argument("--emit", action="store_true",
                   help="连 x64 后端一起跑（更慢，能抓到发射层缺陷）")

    p = sub.add_parser("debug", help="源码级调试器（v1.70，--dbg-info 构建后调试）")
    p.add_argument("src", help=".qma 源文件（自动带调试信息构建）或构建产物")
    p.add_argument("--target", default="win",
                   choices=["native", "c", "arm64", "win", "both"],
                   help="调试信息只支持 win（默认 win）")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--no-opt", action="store_true")
    p.add_argument("--script", default=None,
                   help="命令脚本文件（每行一条命令，# 注释；测试/无人值守用）")
    p.add_argument("--no-cache", action="store_true", help="跳过增量缓存强制重编")
    p.add_argument("args", nargs="*", help="传给被调试程序的参数")

    p = sub.add_parser("cache", help="增量编译缓存（v1.90：查看 / 清空 / 按龄清理）")
    p.add_argument("--stat", action="store_true", help="显示条目数/体积/命中计数（默认动作）")
    p.add_argument("--clear", action="store_true", help="清空全部条目")
    p.add_argument("--prune", type=int, default=None, metavar="DAYS",
                   help="删掉超过 DAYS 天没用过的条目（默认 14）")

    p = sub.add_parser(
        "lsp", help="语言服务器（v1.91：补全/跳转/引用/重命名/悬停/大纲，stdio）")
    p.add_argument("--stdio", action="store_true",
                   help="标准输入输出传输（编辑器用；也是默认）")
    p.add_argument("--root", default=None, help="工作区根（默认当前目录）")
    p.add_argument("--trace", action="store_true", help="把协议消息打到 stderr")
    p.add_argument("--index", default=None, metavar="FILE",
                   help="只索引一个文件并打印统计（性能口径）")
    p.add_argument("--symbols", default=None, metavar="FILE", help="打印符号表")
    p.add_argument("--at", default=None, metavar="FILE:LINE:COL",
                   help="打印该位置的解析结果")
    p.add_argument("--completions", default=None, metavar="FILE:LINE:COL",
                   help="打印该位置的补全项")
    p.add_argument("--check", default=None, metavar="FILE",
                   help="打印诊断；有 error 时退出码 1")

    sub.add_parser("version", help="版本与能力")

    args = ap.parse_args(argv)
    handler = {"build": cmd_build, "run": cmd_run, "test": cmd_test,
               "fmt": cmd_fmt, "doc": cmd_doc, "bench": cmd_bench, "lex": cmd_lex,
               "debug": cmd_debug, "cov": cmd_cov, "fuzz": cmd_fuzz,
               "cache": cmd_cache, "link": cmd_link, "qla": cmd_qla,
               "lsp": cmd_lsp, "version": cmd_version}[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
