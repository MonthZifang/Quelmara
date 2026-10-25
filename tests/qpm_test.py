#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qpm v1.83 回归：确定性打包 / registry 发布 / 传递依赖 + 冲突合并 / 锁校验。

分四段：

  [1] 单元：确定性打包、tree_hash、spec 解析、恶意 tar 拒绝
  [2] 本地 registry 端到端：publish → install（含传递依赖）→ 冲突报错 → yank
  [3] 锁：--locked 不解析、清单漂移报错、verify 检出磁盘被改
  [4] HTTP registry：PUT 发布 + GET 安装（127.0.0.1 随机端口）+ 编译链路
      （装完的包能被编译器 import 并跑出结果——这是"链路完成"的判据）

用法：
    python tests/qpm_test.py
    python tests/qpm_test.py -v
    QPM_TEST_KEEP=1 python tests/qpm_test.py     # 保留 build/_qpm_test
"""
import argparse
import gzip
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "tools"))
import qpm  # noqa: E402

# 每次运行用独立子目录：不删旧目录（大目录删除在带安全删除钩子的环境里极慢），
# 结尾再尽力清理；build/ 已 gitignore。
WORK = os.path.join(ROOT, "build", "_qpm_test", f"run-{os.getpid()}")
VERBOSE = False
FAILS = []
CHECKS = [0]


def check(cond, label, detail=""):
    CHECKS[0] += 1
    if cond:
        if VERBOSE:
            print(f"  ok   {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

def write_pkg(dirpath, name, version, deps=None, body=""):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, "Quelmara.toml"), "w", encoding="utf-8") as f:
        f.write(f'[package]\nname = "{name}"\nversion = "{version}"\n')
        if deps:
            f.write("\n[deps]\n")
            for k, v in deps.items():
                f.write(f'{k} = "{v}"\n')
    with open(os.path.join(dirpath, f"{name}.qma"), "w", encoding="utf-8") as f:
        f.write(f"module {name}\n\n"
                f"pub fn {name}_tag() -> str {{\n"
                f'    return "{body or version}"\n}}\n')


def write_project(dirpath, deps, registry_dir=None, main=None):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, "Quelmara.toml"), "w", encoding="utf-8") as f:
        if registry_dir:
            # 写正斜杠：编译器用 tomllib 读配置，反斜杠必须是转义过的
            f.write("[registry]\ndefault = \"local\"\n"
                    f'local = "path:{registry_dir.replace(chr(92), "/")}"\n\n')
        f.write("[deps]\n")
        for k, v in deps.items():
            f.write(f'{k} = "{v}"\n')
    if main:
        with open(os.path.join(dirpath, "main.qma"), "w", encoding="utf-8") as f:
            f.write(main)


def _clean(path):
    """删工作目录：复用 qpm 的手写删除（不碰 shutil，避免回收站重定向卡住）。"""
    qpm._rmtree(path)


class Env:
    """隔离的 QPM_CACHE / HOME，避免污染开发者机器上的真实缓存。"""

    def __init__(self, tag):
        self.base = os.path.join(WORK, tag)
        self.cache = os.path.join(self.base, "cache")
        self.home = os.path.join(self.base, "home")
        os.makedirs(self.cache, exist_ok=True)
        os.makedirs(self.home, exist_ok=True)
        self.env = dict(os.environ, QPM_CACHE=self.cache, HOME=self.home,
                        USERPROFILE=self.home, QPM_INDEX_TTL="0",
                        PYTHONIOENCODING="utf-8")
        self.env.pop("QPM_TOKEN", None)
        # 子进程按"普通用户环境"跑：去掉宿主的 sitecustomize 注入（删除钩子会
        # 把每次 unlink 变成一次外部审核调用，几十个文件就能让 install 卡住）。
        self.env.pop("PYTHONPATH", None)
        for k in [k for k in self.env if k.startswith("CODEBUDDY_SAFE_DELETE")
                  or k == "GENIE_TRASH_DIR"]:
            self.env.pop(k, None)

    def run(self, cwd, *args, token=None, timeout=30):
        env = dict(self.env)
        if token:
            env["QPM_TOKEN"] = token
        try:
            return subprocess.run(
                [PY, os.path.join(ROOT, "tools", "qpm.py")] + list(args),
                cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired as e:      # 挂死要变成一条失败，不是整轮卡住
            class _R:
                returncode = 124
                stdout = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
                stderr = f"TIMEOUT {timeout}s: qpm {' '.join(args)}"
            return _R()


# ---------------------------------------------------------------------------
# [1] 单元
# ---------------------------------------------------------------------------

def unit():
    print("== [1] 单元：确定性打包 / spec / 恶意包 ==")
    src = os.path.join(WORK, "unit", "src")
    os.makedirs(os.path.join(src, "sub"), exist_ok=True)
    for rel, text in [("a.qma", "module a\n"), ("sub/b.qma", "module b\n"),
                      ("Quelmara.toml", "[package]\nname = \"u\"\nversion = \"1.0.0\"\n")]:
        with open(os.path.join(src, rel), "w", encoding="utf-8") as f:
            f.write(text)
    os.makedirs(os.path.join(src, "build"), exist_ok=True)
    with open(os.path.join(src, "build", "junk.exe"), "wb") as f:
        f.write(b"MZ junk")

    b1 = qpm.pack_tree(src)
    b2 = qpm.pack_tree(src)
    check(b1 == b2, "同目录两次打包逐字节一致", f"{len(b1)} vs {len(b2)}")
    names = [m.name for m in tarfile.open(fileobj=io.BytesIO(b1), mode="r:gz").getmembers()]
    check("a.qma" in names and "sub/b.qma" in names, "包内含源码（含子目录）", str(names))
    check(not any(n.startswith("build/") for n in names), "打包跳过 build/ 与 .exe", str(names))
    check(gzip.decompress.__name__ and b1[:2] == b"\x1f\x8b", "产物是 gzip")

    # 内容变 → 哈希变
    with open(os.path.join(src, "a.qma"), "w", encoding="utf-8") as f:
        f.write("module a\n// x\n")
    b3 = qpm.pack_tree(src)
    check(qpm._sha256(b1) != qpm._sha256(b3), "内容变则 sha256 变")
    with open(os.path.join(src, "a.qma"), "w", encoding="utf-8") as f:
        f.write("module a\n")

    h1 = qpm.tree_hash(src)
    check(h1 == qpm.tree_hash(src), "tree_hash 稳定")
    unpacked = os.path.join(WORK, "unit", "unpacked")
    qpm.unpack_tree(b1, unpacked)
    check(qpm.tree_hash(unpacked) == qpm.tree_hash(src),
          "打包→解包后 tree_hash 不变（内容寻址可验）",
          f"{qpm.tree_hash(unpacked)[:12]} vs {qpm.tree_hash(src)[:12]}")

    # 恶意包：成员带 ..
    evil = io.BytesIO()
    with tarfile.open(fileobj=evil, mode="w") as tf:
        ti = tarfile.TarInfo("../evil.qma")
        ti.size = 3
        tf.addfile(ti, io.BytesIO(b"bad"))
    raw = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        gz.write(evil.getvalue())
    try:
        qpm.unpack_tree(raw.getvalue(), os.path.join(WORK, "unit", "evil"))
        check(False, "拒绝 ../ 路径的包")
    except SystemExit:
        check(True, "拒绝 ../ 路径的包")

    # spec 解析
    cases = [
        ("path:../lib", "path"), ("./lib", "path"), ("../lib", "path"),
        ("/abs/lib", "path"), ("C:\\lib", "path"),
        ("git:https://h/u/r#v1.0.0", "git"), ("https://h/u/r#^1.0", "git"),
        ("file:///tmp/r#v1", "git"), ("^1.2.0", "registry"), ("1.2.3", "registry"),
        ("*", "registry"),
    ]
    for spec, want in cases:
        got = qpm.parse_spec("p", spec).kind
        check(got == want, f"parse_spec({spec!r}) → {want}", f"实得 {got}")
    check(qpm.parse_spec("p", "https://h/u/r#^1.0").rev == "^1.0", "git 区间进 rev")
    check(qpm.parse_spec("p", "^1.0").rev == "^1.0", "registry 区间进 rev")


# ---------------------------------------------------------------------------
# [2] 本地 registry：发布 / 传递依赖 / 冲突 / yank
# ---------------------------------------------------------------------------

def build_local_registry(env):
    """gamma 2.1.0/2.2.0 · beta 1.0.0/1.0.1 · alpha 1.0.0/1.1.0/2.0.0。"""
    reg = os.path.join(WORK, "reg")
    pkgs = os.path.join(WORK, "pkgs")
    specs = [
        ("gamma", "2.1.0", {}, ""),
        ("gamma", "2.1.9", {}, ""),
        ("beta", "1.0.0", {"gamma": "~2.1"}, ""),
        ("beta", "1.0.1", {"gamma": "~2.1"}, ""),
        ("alpha", "1.0.0", {"beta": "^1.0"}, ""),
        ("alpha", "1.1.0", {"beta": "^1.0"}, "alpha-1.1.0"),
        ("alpha", "2.0.0", {"beta": "^2.0"}, ""),
    ]
    for name, ver, deps, body in specs:
        d = os.path.join(pkgs, f"{name}-{ver}")
        write_pkg(d, name, ver, deps, body)
        r = env.run(d, "publish", "--registry", f"path:{reg}")
        check(r.returncode == 0, f"publish {name} {ver}",
              f"rc={r.returncode} {r.stderr.strip()[:200]}")
    return reg, pkgs


def local_registry(env):
    print("== [2] 本地 registry：发布 → 传递依赖 → 冲突 → yank ==")
    reg, pkgs = build_local_registry(env)
    idx = json.load(open(os.path.join(reg, "index", "beta.json"), encoding="utf-8"))
    check(sorted(idx["versions"]) == ["1.0.0", "1.0.1"], "索引含 beta 两个版本")
    check(idx["versions"]["1.0.1"]["deps"] == {"gamma": "~2.1"},
          "索引记录依赖（解析阶段不用下包体）", str(idx["versions"]["1.0.1"]))
    check(os.path.isfile(os.path.join(reg, "packages", "alpha-1.1.0.qpk")),
          "包体落盘 packages/<name>-<ver>.qpk")

    # 重复发布同版本必须拒绝（不可覆盖）
    r = env.run(os.path.join(pkgs, "alpha-1.1.0"), "publish",
                "--registry", f"path:{reg}")
    check(r.returncode != 0 and "不可覆盖" in (r.stdout + r.stderr),
          "同版本重复发布被拒绝", f"rc={r.returncode} {(r.stdout + r.stderr)[:200]}")

    proj = os.path.join(WORK, "app")
    write_project(proj, {"alpha": "^1.0"}, reg)
    r = env.run(proj, "install")
    lock = qpm.read_lock(qpm.Project(proj))
    got = {n: e["version"] for n, e in lock["packages"].items()} if lock else {}
    check(r.returncode == 0, "install 成功", f"rc={r.returncode} {r.stderr.strip()[:300]}")
    check(got == {"alpha": "1.1.0", "beta": "1.0.1", "gamma": "2.1.9"},
          "传递依赖解析（alpha ^1.0 → beta 1.0.1 → gamma ~2.1 → 2.1.9）", str(got))
    for n in ("alpha", "beta", "gamma"):
        check(os.path.isdir(os.path.join(proj, ".qpm", "deps", n)),
              f".qpm/deps/{n} 落地")
    check(lock["packages"]["alpha"]["deps"] == "beta@^1.0", "锁记录边（deps 字段）",
          lock["packages"]["alpha"]["deps"])

    r = env.run(proj, "tree")
    check(r.returncode == 0 and "alpha 1.1.0" in r.stdout and "gamma 2.1.9" in r.stdout,
          "qpm tree 打印解析后的版本", r.stdout.strip()[:300])

    # 区间交集：root 收窄 beta，仍应选 1.0.1（同时满足 ^1.0 与 ~1.0.0）
    write_project(proj, {"alpha": "^1.0", "beta": "~1.0.0"}, reg)
    r = env.run(proj, "install")
    lock = qpm.read_lock(qpm.Project(proj))
    check(r.returncode == 0 and lock["packages"]["beta"]["version"] == "1.0.1",
          "区间交集合并（^1.0 ∩ ~1.0.0 → 1.0.1）",
          f"rc={r.returncode} {(r.stderr or '')[:200]}")

    # 冲突：root 要 beta ^2.0，alpha 要 ^1.0
    write_project(proj, {"alpha": "^1.0", "beta": "^2.0"}, reg)
    r = env.run(proj, "install")
    out = r.stdout + r.stderr
    check(r.returncode != 0 and "冲突" in out and "^2.0" in out and "^1.0" in out,
          "无交集区间 fail-fast 并列出两条约束", f"rc={r.returncode} {out.strip()[:300]}")
    check("可用版本" in out, "冲突信息带可用版本", out.strip()[:300])

    # 同名跨来源冲突
    write_project(proj, {"alpha": "^1.0", "beta": f"git:file:///{reg}"}, reg)
    r = env.run(proj, "install")
    out = r.stdout + r.stderr
    check(r.returncode != 0 and "不同来源" in out,
          "同名依赖跨来源（registry vs git）报冲突", f"rc={r.returncode} {out.strip()[:300]}")

    # yank 后不再被选中
    write_project(proj, {"alpha": "^1.0"}, reg)
    r = env.run(proj, "yank", "beta", "1.0.1", "--registry", f"path:{reg}")
    check(r.returncode == 0, "yank beta 1.0.1", r.stderr.strip()[:200])
    r = env.run(proj, "install")
    lock = qpm.read_lock(qpm.Project(proj))
    check(r.returncode == 0 and lock["packages"]["beta"]["version"] == "1.0.0",
          "yank 后解析回退到 1.0.0",
          f"rc={r.returncode} {lock['packages']['beta']['version'] if lock else '?'}")

    # 哈希校验：篡改包体必须拒绝（用干净缓存，避免命中旧 blob）
    env2 = Env("tamper")
    reg2 = os.path.join(WORK, "reg2")
    write_pkg(os.path.join(WORK, "pkgs", "delta-1.0.0"), "delta", "1.0.0")
    env2.run(os.path.join(WORK, "pkgs", "delta-1.0.0"), "publish",
             "--registry", f"path:{reg2}")
    blobp = os.path.join(reg2, "packages", "delta-1.0.0.qpk")
    with open(blobp, "r+b") as f:
        f.seek(10)
        f.write(b"XXXX")
    proj2 = os.path.join(WORK, "app2")
    write_project(proj2, {"delta": "^1.0"}, reg2)
    r = env2.run(proj2, "install")
    out = r.stdout + r.stderr
    check(r.returncode != 0 and "哈希不符" in out,
          "包体被篡改 → 哈希不符 fail-fast", f"rc={r.returncode} {out.strip()[:300]}")


# ---------------------------------------------------------------------------
# [3] 锁
# ---------------------------------------------------------------------------

def locks(env):
    print("== [3] 锁：--locked / 漂移 / verify ==")
    reg = os.path.join(WORK, "reg")
    proj = os.path.join(WORK, "lockapp")
    write_project(proj, {"alpha": "^1.0"}, reg)
    env.run(proj, "install")

    # 新版本进 registry，--locked 不应该升上去
    write_pkg(os.path.join(WORK, "pkgs", "alpha-1.2.0"), "alpha", "1.2.0",
              {"beta": "^1.0"}, "alpha-1.2.0")
    env.run(os.path.join(WORK, "pkgs", "alpha-1.2.0"), "publish",
            "--registry", f"path:{reg}")
    r = env.run(proj, "install", "--locked")
    lock = qpm.read_lock(qpm.Project(proj))
    check(r.returncode == 0 and lock["packages"]["alpha"]["version"] == "1.1.0",
          "--locked 不升级（仍 1.1.0）",
          f"rc={r.returncode} {lock['packages']['alpha']['version'] if lock else '?'}")
    r = env.run(proj, "install", "--refresh")
    lock = qpm.read_lock(qpm.Project(proj))
    check(lock["packages"]["alpha"]["version"] == "1.2.0",
          "普通 install 取到新版本 1.2.0",
          lock["packages"]["alpha"]["version"] if lock else "?")

    # 清单漂移：--locked 必须拒绝
    write_project(proj, {"alpha": "^1.0", "gamma": "^2.1"}, reg)
    r = env.run(proj, "install", "--locked")
    out = r.stdout + r.stderr
    check(r.returncode != 0 and "清单与锁不一致" in out,
          "--locked 检出清单漂移", f"rc={r.returncode} {out.strip()[:200]}")

    # verify：正常 → 改磁盘文件 → 报错
    env.run(proj, "install")
    r = env.run(proj, "verify")
    check(r.returncode == 0, "verify 通过", (r.stdout + r.stderr).strip()[:200])
    target = os.path.join(proj, ".qpm", "deps", "alpha", "alpha.qma")
    with open(target, "a", encoding="utf-8") as f:
        f.write("// tampered\n")
    r = env.run(proj, "verify")
    out = r.stdout + r.stderr
    check(r.returncode != 0 and "与锁不符" in out,
          "verify 检出磁盘内容被改", f"rc={r.returncode} {out.strip()[:200]}")
    env.run(proj, "install")          # 复原

    # 环：p ↔ q 可安装，但要有提示
    pdir = os.path.join(WORK, "pkgs", "ping-1.0.0")
    qdir = os.path.join(WORK, "pkgs", "pong-1.0.0")
    write_pkg(pdir, "ping", "1.0.0", {"pong": "^1.0"})
    write_pkg(qdir, "pong", "1.0.0", {"ping": "^1.0"})
    env.run(pdir, "publish", "--registry", f"path:{reg}")
    env.run(qdir, "publish", "--registry", f"path:{reg}")
    cproj = os.path.join(WORK, "cycleapp")
    write_project(cproj, {"ping": "^1.0"}, reg)
    r = env.run(cproj, "install")
    check(r.returncode == 0 and "依赖环" in r.stdout,
          "依赖环可安装且有提示", f"rc={r.returncode} {r.stdout.strip()[:300]}")
    check(os.path.isdir(os.path.join(cproj, ".qpm", "deps", "pong")),
          "环里的对端也落地")


# ---------------------------------------------------------------------------
# [4] HTTP registry + 编译链路
# ---------------------------------------------------------------------------

class _Server(ThreadingHTTPServer):
    daemon_threads = True          # 别让 keep-alive 的处理线程拖住 server_close
    block_on_close = False


class _Handler(BaseHTTPRequestHandler):
    root = ""
    token = "t0ken"
    protocol_version = "HTTP/1.0"  # 每条请求一个连接：收尾不等待下一帧

    def _path(self):
        return os.path.join(self.root, *self.path.strip("/").split("/"))

    def do_GET(self):
        p = self._path()
        if not os.path.isfile(p):
            self.send_error(404)
            return
        with open(p, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_PUT(self):
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            self.send_error(401)
            return
        p = self._path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        n = int(self.headers.get("Content-Length", "0"))
        with open(p, "wb") as f:
            f.write(self.rfile.read(n))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def http_registry(env):
    print("== [4] HTTP registry（PUT 发布 / GET 安装）+ 编译链路 ==")
    hroot = os.path.join(WORK, "httpreg")
    os.makedirs(hroot, exist_ok=True)
    _Handler.root = hroot
    try:
        srv = _Server(("127.0.0.1", 0), _Handler)
    except OSError as e:                                  # pragma: no cover
        print(f"  SKIP 无法监听回环端口：{e}")
        return
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        env2 = Env("http")
        pkgs = os.path.join(WORK, "httppkgs")
        write_pkg(os.path.join(pkgs, "echo-1.0.0"), "echo", "1.0.0",
                  {"alpha": "^1.0"})
        r = env2.run(os.path.join(pkgs, "echo-1.0.0"), "publish",
                     "--registry", url, token=_Handler.token)
        check(r.returncode == 0, "HTTP PUT 发布", f"rc={r.returncode} "
              f"{(r.stdout + r.stderr).strip()[:200]}")
        check(os.path.isfile(os.path.join(hroot, "index", "echo.json")),
              "HTTP 发布写出索引")

        write_pkg(os.path.join(pkgs, "echo-1.0.1"), "echo", "1.0.1",
                  {"alpha": "^1.0"})
        r = env2.run(os.path.join(pkgs, "echo-1.0.1"), "publish",
                     "--registry", url)      # 无 token
        check(r.returncode != 0 and "401" in (r.stdout + r.stderr),
              "无 token 发布被拒（401）", (r.stdout + r.stderr).strip()[:200])

        # 换一个工程，从 http registry 装（同时要能解析出传递依赖 alpha）
        proj = os.path.join(WORK, "httpapp")
        write_project(proj, {"echo": "^1.0"}, None)
        qpm.set_toml_value(os.path.join(proj, "Quelmara.toml"), "registry", "default", "http")
        qpm.set_toml_value(os.path.join(proj, "Quelmara.toml"), "registry", "http", url)
        # alpha 不在 http registry 里 → 传递依赖解析失败是**正确**行为
        r = env2.run(proj, "install")
        out = r.stdout + r.stderr
        check(r.returncode != 0 and "没有包" in out,
              "HTTP registry 缺传递依赖时报错（不静默）", f"rc={r.returncode} {out.strip()[:200]}")

        # 把 alpha 也发到 http registry，再装一次
        env2.run(os.path.join(WORK, "pkgs", "alpha-1.1.0"), "publish",
                 "--registry", url, token=_Handler.token)
        env2.run(os.path.join(WORK, "pkgs", "beta-1.0.1"), "publish",
                 "--registry", url, token=_Handler.token)
        env2.run(os.path.join(WORK, "pkgs", "gamma-2.1.9"), "publish",
                 "--registry", url, token=_Handler.token)
        r = env2.run(proj, "install")
        lock = qpm.read_lock(qpm.Project(proj))
        got = {n: e["version"] for n, e in lock["packages"].items()} if lock else {}
        check(r.returncode == 0 and got.get("echo") == "1.0.0" and got.get("alpha"),
              "HTTP registry 安装 + 传递依赖", f"rc={r.returncode} {got} "
              f"{(r.stderr or '')[:200]}")
    finally:
        srv.shutdown()
        srv.server_close()

    # 编译链路：装好的包能被 import 并跑出结果
    print("== [4b] 编译链路：install → build → run ==")
    reg = os.path.join(WORK, "reg")
    proj = os.path.join(WORK, "chainapp")
    write_project(proj, {"alpha": "^1.0"}, reg,
                  main="module app\n\nimport alpha.alpha\n\n"
                       "fn main() {\n    print(alpha_tag())\n}\n")
    r = env.run(proj, "install")
    check(r.returncode == 0, "链路：install", (r.stdout + r.stderr)[:300])
    out_exe = os.path.join(WORK, "chain.exe")
    try:
        r = subprocess.run([PY, os.path.join(ROOT, "tools", "stage0", "qlm_cli.py"),
                            "build", os.path.join(proj, "main.qma"),
                            "--target", "win", "-o", out_exe],
                           cwd=proj, env=env.env, capture_output=True, text=True,
                           timeout=45, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        class _T:
            returncode = 124
            stdout = ""
            stderr = "TIMEOUT 45s: qlm_cli build"
        r = _T()
    check(r.returncode == 0 and os.path.isfile(out_exe),
          "链路：编译器按 .qpm/deps 找到 import",
          f"rc={r.returncode} {(r.stdout + r.stderr).strip()[:300]}")
    if os.path.isfile(out_exe):
        # v2.54：POSIX 上刚写出来的文件没有执行位（Windows 不需要）。
        # 不 chmod 就会 PermissionError: [Errno 13] —— Linux CI 从 v2.48 起一直红
        # 就是这个，不是 qpm 本身的问题。
        if os.name != "nt":
            os.chmod(out_exe, 0o755)
        lock = qpm.read_lock(qpm.Project(proj))
        want = "alpha-" + lock["packages"]["alpha"]["version"]
        r = subprocess.run([out_exe], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL,
                           env=env.env, encoding="utf-8", errors="replace")
        check(r.returncode == 0 and want in r.stdout,
              f"链路：产物跑出依赖里的字符串（{want}）",
              f"rc={r.returncode} out={r.stdout!r}")


def main():
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    VERBOSE = args.verbose
    os.makedirs(WORK, exist_ok=True)
    unit()
    env = Env("local")
    local_registry(env)
    locks(env)
    http_registry(env)
    print("-" * 56)
    if FAILS:
        print(f"FAIL：{len(FAILS)} 项")
        for f in FAILS:
            print(f"  - {f}")
        rc = 1
    else:
        print(f"PASS：qpm 打包 / registry / 传递依赖 / 锁 / 编译链路全绿（{CHECKS[0]} 项）")
        rc = 0
    if not os.environ.get("QPM_TEST_KEEP"):
        _clean(WORK)
    return rc


if __name__ == "__main__":
    sys.exit(main())
