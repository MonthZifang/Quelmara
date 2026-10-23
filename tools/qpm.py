#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qpm —— Quelmara Package Manager（v1.45：semver 区间）

设计：
  * 依赖声明：项目 Quelmara.toml 的 [deps] 段，`name = "spec"`：
      - 路径依赖：`path:../mylib`，或 v0 的前缀探测（./ ../ / 盘符）
      - git 依赖：`git:https://…#v1.2.3` 精确 tag/branch/sha，
        或 `https://…#^1.2.0` semver 区间（ls-remote 选最新满足 tag）
  * 布局：git 依赖 clone 到全局缓存 ~/.qpm/cache/<name>-<rev>，再复制到
    <project>/.qpm/deps/<name>/（Windows 无 symlink，复制保证构建不碰网络）；
    路径依赖在 lock 中记录绝对路径，编译器直接搜索。
  * 锁文件：<project>/.qpm/lock.toml，`name = "kind|src|rev|sha"`；
    区间依赖的 rev 是**解析后**的 tag（区间文本留在 Quelmara.toml）。
  * 编译器集成：qlm.py 的 _import_candidates 会搜索 <src_dir>/.qpm/deps/，
    `import jsonx.encoding` 解析为 .qpm/deps/jsonx/encoding.qma。
  * 未做（路线）：registry 服务、发布/上传、依赖传递冲突合并策略、
    包内 Quelmara.toml 的构建配置继承。

区间语法（^ ~ >= <= > < = * 通配、AND/OR、预发布门槛）见 tools/qpm_semver.py。
区间判定是语法式的：含运算符/通配段/分隔符才算区间，纯版本串按精确 tag
（v0 语义）——名字恰好长得像区间的 tag 会被当区间解析，失败即报错。

命令：
  python tools/qpm.py install            # 按 [deps] 拉取 + 写锁
  python tools/qpm.py add <name> <spec>  # 添加依赖并 install
  python tools/qpm.py remove <name>      # 移除依赖
  python tools/qpm.py list               # 列出依赖与锁定状态
"""
import os
import re
import shutil
import subprocess
import sys

import qpm_semver

ROOT = os.getcwd()
PROJ_TOML = os.path.join(ROOT, "Quelmara.toml")
DEPS_DIR = os.path.join(ROOT, ".qpm", "deps")
LOCK_FILE = os.path.join(ROOT, ".qpm", "lock.toml")
CACHE = os.path.join(os.path.expanduser("~"), ".qpm", "cache")


def _is_path_spec(spec):
    return spec.startswith("./") or spec.startswith("../") \
        or spec.startswith("/") or (len(spec) > 1 and spec[1] == ":")


def parse_spec(spec):
    """依赖 spec -> (kind, source, rev)。kind ∈ {"path", "git"}。

    形态（v1.45：显式前缀与 v0 的前缀探测等价，文档口径统一到这两种）：
      path:../mylib / ./x / ../x / /abs / C:\\x          路径依赖
      git:https://…#v1.2.3 / https://…#^1.2.0 / …         git 依赖（#rev 或 #区间）
    """
    if spec.startswith("path:"):
        return ("path", spec[len("path:"):], "")
    if spec.startswith("git:"):
        spec = spec[len("git:"):]
    elif _is_path_spec(spec):
        return ("path", spec, "")
    url, rev = spec, ""
    if "#" in spec:
        url, rev = spec.split("#", 1)
    return ("git", url, rev)


def _looks_like_range(rev):
    """rev 是 semver 区间还是精确 tag/branch/sha？语法式判定。

    区间必须"长得像区间"：运算符开头、含分隔符、或整段通配版本。
    纯版本串（`1.0.1` / `v1.0`）按精确 tag——v0 语义，名为 `1.0` 的
    tag 不会被误读成区间。
    """
    if not rev:
        return False
    if rev in ("*", "x", "X"):
        return True
    if rev[0] in "^~><=":
        return True
    if any(c in rev for c in ", \t"):
        return True
    if "||" in rev:
        return True
    return bool(re.match(r"^v?\d+\.(?:[xX*]|\d+\.(?:[xX*]|\d+\.(?:[xX*]))?)$", rev))


def ls_remote_tags(url):
    """git ls-remote --tags 的 tag 名列表（剥 refs/tags/ 与 ^{} 解引用）。"""
    out = _git(["ls-remote", "--tags", url])
    tags = []
    for ln in out.splitlines():
        _sha, _, ref = ln.partition("\t")
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            tags.append(ref[len("refs/tags/"):])
    return tags


def parse_deps():
    """从 Quelmara.toml 提取 [deps] 段（轻量行解析：key = "spec"）。"""
    if not os.path.isfile(PROJ_TOML):
        return {}
    deps, in_deps = {}, False
    with open(PROJ_TOML, encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if s.startswith("[") and s.endswith("]"):
                in_deps = s == "[deps]"
                continue
            if in_deps and "=" in s and not s.startswith("#"):
                m = re.match(r'"?([A-Za-z0-9_\-\.]+)"?\s*=\s*"([^"]*)"', s)
                if m:
                    deps[m.group(1)] = m.group(2)
    return deps


def set_dep(name, spec):
    """在 Quelmara.toml 追加/更新 [deps] 段（无则文件尾追加）。"""
    lines = []
    if os.path.isfile(PROJ_TOML):
        with open(PROJ_TOML, encoding="utf-8") as f:
            lines = f.read().splitlines()
    di = -1
    for i, ln in enumerate(lines):
        if ln.strip() == "[deps]":
            di = i
            break
    entry = f'{name} = "{spec}"'
    if di < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[deps]")
        lines.append(entry)
    else:
        j = di + 1
        replaced = False
        while j < len(lines) and not lines[j].strip().startswith("["):
            if re.match(rf'{re.escape(name)}\s*=', lines[j].strip()):
                lines[j] = entry
                replaced = True
            j += 1
        if not replaced:
            lines.insert(di + 1, entry)
    with open(PROJ_TOML, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def remove_dep(name):
    if not os.path.isfile(PROJ_TOML):
        return
    lines = []
    with open(PROJ_TOML, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, in_deps = [], False
    for ln in lines:
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            in_deps = s == "[deps]"
            out.append(ln)
            continue
        if in_deps and re.match(rf'{re.escape(name)}\s*=', s):
            continue
        out.append(ln)
    with open(PROJ_TOML, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def _git(args, cwd=None):
    r = subprocess.run(["git"] + args, cwd=cwd,
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"qpm: git {' '.join(args)} 失败：\n{r.stderr.strip()}")
    return r.stdout.strip()


def resolve_one(name, spec):
    """安装单个依赖，返回 lock 条目 (kind, source, rev, sha)。

    git 依赖的 rev 若是 semver 区间：先 ls-remote 列 tag，选满足区间的最大
    版本，rev 收敛为具体 tag 后再走 v0 的 clone/缓存/复制路径。
    """
    kind, source, rev = parse_spec(spec)
    if kind == "path":
        p = os.path.normpath(os.path.join(ROOT, source))
        if not os.path.isdir(p):
            raise SystemExit(f"qpm: 路径依赖 {name!r} 不存在：{p}")
        dst = os.path.join(DEPS_DIR, name)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(p, dst)
        print(f"  {name} <- path {p}")
        return ("path", p, "", "")

    # git 依赖：url[#rev 或 #semver 区间]
    url = source
    if rev and _looks_like_range(rev):
        tags = ls_remote_tags(url)
        sel = qpm_semver.select_tag(tags, rev)
        if sel is None:
            avail = "、".join(sorted(tags)) or "（无 tag）"
            raise SystemExit(
                f"qpm: {name!r} 的 semver 区间 {rev!r} 没有满足的 tag；"
                f"{url} 可用 tag：{avail}")
        print(f"  {name} <- git {url} 区间 {rev} → {sel[0]}")
        rev = sel[0]
    cache = os.path.join(CACHE, f"{name}-{re.sub(r'[^A-Za-z0-9_.\-]', '_', rev or 'main')}")
    if not os.path.isdir(os.path.join(cache, ".git")):
        os.makedirs(CACHE, exist_ok=True)
        if rev:
            _git(["clone", "--depth", "1", "--branch", rev, url, cache])
        else:
            _git(["clone", "--depth", "1", url, cache])
    else:
        _git(["fetch", "--depth", "1", "origin", rev or "HEAD"], cwd=cache)
    if rev:
        _git(["checkout", rev], cwd=cache)
    sha = _git(["rev-parse", "HEAD"], cwd=cache)
    dst = os.path.join(DEPS_DIR, name)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(cache, dst, ignore=shutil.ignore_patterns(".git"))
    print(f"  {name} <- git {url}#{rev or 'HEAD'} @ {sha[:12]}")
    return ("git", url, rev, sha)


def cmd_install():
    deps = parse_deps()
    if not deps:
        print("qpm: [deps] 为空，无事可做")
        return 0
    os.makedirs(DEPS_DIR, exist_ok=True)
    lock = {}
    for name, spec in deps.items():
        lock[name] = resolve_one(name, spec)
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write("# qpm lock —— 由 qpm install 生成，请勿手工编辑\n")
        for name, (kind, src, rev, sha) in lock.items():
            f.write(f'{name} = "{kind}|{src}|{rev}|{sha}"\n')
    print(f"qpm: {len(lock)} 个依赖已就绪，锁文件 {LOCK_FILE}")
    return 0


def cmd_add(args):
    if len(args) < 2:
        raise SystemExit(
            "qpm: add <name> <spec>（path:… / git:url#rev / url#semver 区间，"
            "如 \"^1.2.0\"）")
    name, spec = args[0], args[1]
    set_dep(name, spec)
    print(f"qpm: 已添加 {name} = \"{spec}\"")
    return cmd_install()


def cmd_remove(args):
    if not args:
        raise SystemExit("qpm: remove <name>")
    remove_dep(args[0])
    print(f"qpm: 已移除 {args[0]}")
    return 0


def cmd_list():
    deps = parse_deps()
    lock = {}
    if os.path.isfile(LOCK_FILE):
        with open(LOCK_FILE, encoding="utf-8") as f:
            for ln in f:
                m = re.match(r'([A-Za-z0-9_\-\.]+)\s*=\s*"([^"]*)"', ln.strip())
                if m:
                    lock[m.group(1)] = m.group(2).split("|")
    if not deps:
        print("qpm: [deps] 为空")
        return 0
    for name, spec in deps.items():
        lk = lock.get(name)
        if lk:
            print(f"  {name} = \"{spec}\"  [{lk[0]} {lk[2] or '-'} sha={lk[3][:12]}]")
        else:
            print(f"  {name} = \"{spec}\"  [未安装：qpm install]")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "install":
        return cmd_install()
    if cmd == "add":
        return cmd_add(args)
    if cmd == "remove":
        return cmd_remove(args)
    if cmd == "list":
        return cmd_list()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
