#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qpm —— Quelmara Package Manager（v1.83：registry + 发布 + 传递依赖）

一句话：qpm 把 `[deps]` 解析成**一张扁平依赖图**，落到 `<project>/.qpm/deps/`，
编译器按 `import a.b` 直接找到 `.qpm/deps/a/b.qma`（`qlm.py::_qpm_candidates`）。

三种依赖来源（spec 形态，v1.83）：

    路径      path:../mylib | ./x | ../x | /abs | C:\\x
    git       git:https://…#v1.2.3 | https://…#^1.2.0 | git@host:u/r#rev
    registry  "^1.2.0" | "1.2.3" | "*"        （包名 = [deps] 的 key）

registry 协议（自研，v1.83）：

    <base>/index/<name>.json
        {"name": "alpha",
         "versions": {"1.2.0": {"deps": {"beta": "^1.0"},
                                "sha256": "<.qpk 的 sha256>",
                                "size": 1234, "yanked": false}}}
    <base>/packages/<name>-<version>.qpk
        qpm 打的确定性 tar.gz

    base 可以是本地目录（`path:` / `./` / `C:\\`）或 `http(s)://`。本地目录按文件
    复制；http 用 GET 取索引与包、PUT 发布（Bearer token 来自环境变量
    `QPM_TOKEN`）。索引按 `QPM_INDEX_TTL`（默认 300 s）缓存到 `~/.qpm/index/`。

    为什么要确定性打包：sha256 就是包的身份。同一份源码重新打包必须逐字节一致
    （mtime=0、uid/gid=0、路径排序、gzip 不带文件名与时间戳），否则"同版本不同
    哈希"会让锁文件失去意义，也让缓存无法按内容寻址。

锁文件 `.qpm/lock.toml`（v2，向后兼容 v1 的四段式读取）：

    [roots]
    alpha = "^1.0"
    [packages]
    alpha = "kind|src|rev|sha|version|tree|deps"

    * sha   registry = .qpk 的 sha256；git = commit sha；path = ""（内容看 tree）
    * tree  安装后目录内容哈希（relpath + 长度 + 内容，按路径排序），供 qpm verify
    * deps  "beta@^1.0;gamma@~2.1"（`;` 分隔，区间内部的逗号不受影响）

传递依赖与冲突合并（v1.83）：

    * 每个包自己的 `Quelmara.toml [deps]` 也读进来（registry 包直接用索引里的
      `deps` 字段，解析阶段不下载包体）。
    * 同名依赖的所有区间取**交集**，选满足全部区间的最大版本；新约束会让已选
      版本重选（贪心 + 定点迭代，最多 5000 步，不收敛即报错）。
    * git 依赖先归一化成具体 rev（区间先 ls-remote 选 tag）再比较；path 依赖
      要求绝对路径一致；同名依赖跨来源（registry / git / path 混用）直接报冲突。
    * **没有回溯**：区间无交集时报错，列出每条约束的来源与可用版本，不做
      "自动降级换版本"。这是刻意的——静默换版本比报错更难查。
    * 依赖环**不是错误**：扁平布局里每个包只落一份，环可以安装；只在 `tree` /
      `install` 时打一行提示。

命令：

    python tools/qpm.py install [--offline] [--locked] [--refresh] [--registry NAME]
    python tools/qpm.py add <name> <spec>
    python tools/qpm.py remove <name>
    python tools/qpm.py list | tree | verify
    python tools/qpm.py update [name]
    python tools/qpm.py publish [--registry NAME] [--dry-run]
    python tools/qpm.py yank <name> <version> [--registry NAME]
    python tools/qpm.py registry add <name> <url> | remove <name> | list

未做（路线，见 docs/07-gaps.md）：多 registry 并存解析（现在一个项目只从一个
registry 解析）、包签名/公信链、`build.rs` 类构建钩子、增量编译（`.qla`）。
"""
import argparse
import collections
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qpm_semver  # noqa: E402

CACHE = os.environ.get("QPM_CACHE") or os.path.join(
    os.path.expanduser("~"), ".qpm", "cache")
INDEX_TTL = int(os.environ.get("QPM_INDEX_TTL", "300"))
HTTP_TIMEOUT = 20

# 打包/复制时跳过的目录与后缀（与 .gitignore 的口径一致：只收源码与配置）
PACK_SKIP_DIRS = {".git", ".qpm", "__pycache__", ".openclaw", "build",
                  "node_modules", "target"}
PACK_SKIP_EXT = {".exe", ".qex", ".qpk", ".pyc", ".obj", ".o", ".pdb"}

_GIT_PREFIXES = ("http://", "https://", "file://", "git://", "ssh://", "git@")


# ---------------------------------------------------------------------------
# 1. 基础工具：哈希 / 确定性打包 / 原子写
# ---------------------------------------------------------------------------

def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _slug(text):
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", text)[:80] or "_"


def _iter_files(root):
    """打包/校验用：按相对路径排序的 (rel, abspath)，跳过构建产物与元数据。"""
    out = []
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in PACK_SKIP_DIRS)
        for n in sorted(names):
            if os.path.splitext(n)[1].lower() in PACK_SKIP_EXT:
                continue
            p = os.path.join(base, n)
            out.append((os.path.relpath(p, root).replace("\\", "/"), p))
    out.sort(key=lambda x: x[0])
    return out


def pack_tree(root):
    """确定性 tar.gz：同内容 → 同字节 → 同 sha256。"""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for rel, path in _iter_files(root):
            with open(path, "rb") as f:
                data = f.read()
            ti = tarfile.TarInfo(rel)
            ti.size = len(data)
            ti.mtime = 0
            ti.mode = 0o644
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            ti.type = tarfile.REGTYPE
            tf.addfile(ti, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0,
                       compresslevel=9) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def unpack_tree(blob, dst):
    """把 .qpk 解到 dst（先清空）。拒绝绝对路径 / .. / 非普通文件。"""
    _rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m in tf.getmembers():
            name = m.name.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or \
                    not (m.isfile() or m.isdir()):
                raise SystemExit(f"qpm: 包内容非法（成员 {m.name!r}），拒绝解包")
        try:
            tf.extractall(dst, filter="data")   # Python 3.12+
        except TypeError:                        # pragma: no cover - 老解释器
            tf.extractall(dst)


def tree_hash(root):
    """目录内容哈希：relpath\\0len\\0content 排序累加。用于 verify 与锁。"""
    h = hashlib.sha256()
    for rel, path in _iter_files(root):
        with open(path, "rb") as f:
            data = f.read()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(str(len(data)).encode("ascii"))
        h.update(b"\0")
        h.update(data)
    return h.hexdigest()


def _rmtree(path):
    """删目录：手写遍历删除，**不走 shutil.rmtree**。

    两个理由：
      1. Windows 上 shutil.rmtree 遇只读文件会抛错，得逐个清只读位；
      2. 某些运行环境把 shutil.rmtree 重定向到回收站（沙箱/安全软件），
         对成百上千个小文件会极慢甚至卡住——包管理器要的是"立刻删掉"。
    删不干净就改名挪开，绝不阻塞安装（留一个 `.old-<pid>` 比挂死好）。
    """
    if not os.path.isdir(path):
        return
    for base, dirs, files in os.walk(path, topdown=False):
        for name in files:
            p = os.path.join(base, name)
            try:
                os.chmod(p, 0o700)
            except OSError:
                pass
            try:
                os.unlink(p)
            except OSError:
                pass
        for name in dirs:
            p = os.path.join(base, name)
            try:
                os.rmdir(p)
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass
    if os.path.isdir(path):
        try:
            os.replace(path, f"{path}.old-{os.getpid()}")
        except OSError:
            pass


def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# 2. TOML 子集（[section] + key = "value"）——不引第三方依赖
# ---------------------------------------------------------------------------

def _toml_escape(value):
    """写 TOML 字符串：反斜杠与引号必须转义，否则 tomllib（编译器读配置用）
    会把 Windows 路径里的 `\\U` 当成非法十六进制转义直接报错。"""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _toml_unescape(value):
    out, i = [], 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            out.append(value[i + 1])
            i += 2
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def _parse_value(text):
    v = text.strip()
    if v.startswith('"'):
        end = v.rfind('"')
        return _toml_unescape(v[1:end] if end > 0 else v[1:])
    return v.split("#")[0].strip()


def read_toml(path):
    """{section: {key: value}}；只认 qpm 用到的子集，不处理数组/内联表。"""
    out = {}
    if not os.path.isfile(path):
        return out
    sec = ""
    with open(path, encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("[") and s.endswith("]"):
                sec = s[1:-1].strip()
                out.setdefault(sec, {})
                continue
            if "=" in s:
                k, _, v = s.partition("=")
                out.setdefault(sec, {})[k.strip().strip('"')] = _parse_value(v)
    return out


def _toml_lines(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def _section_bounds(lines, section):
    """返回 (header 行号, 段尾行号)；不存在返回 (-1, -1)。"""
    start = -1
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            if start >= 0:
                return start, i
            if s[1:-1].strip() == section:
                start = i
    return (start, len(lines)) if start >= 0 else (-1, -1)


def set_toml_value(path, section, key, value):
    lines = _toml_lines(path)
    start, end = _section_bounds(lines, section)
    entry = f'{key} = "{_toml_escape(value)}"'
    if start < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", entry]
    else:
        replaced = False
        for i in range(start + 1, end):
            if re.match(rf'^"?{re.escape(key)}"?\s*=', lines[i].strip()):
                lines[i] = entry
                replaced = True
                break
        if not replaced:
            lines.insert(end, entry)
    _atomic_write(path, ("\n".join(lines) + "\n").encode("utf-8"))


def remove_toml_key(path, section, key):
    lines = _toml_lines(path)
    start, end = _section_bounds(lines, section)
    if start < 0:
        return
    out = [ln for i, ln in enumerate(lines)
           if not (start < i < end
                   and re.match(rf'^"?{re.escape(key)}"?\s*=', ln.strip()))]
    _atomic_write(path, ("\n".join(out) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# 3. 工程
# ---------------------------------------------------------------------------

class Project:
    def __init__(self, root=None):
        self.root = os.path.abspath(root or os.getcwd())
        self.toml_path = os.path.join(self.root, "Quelmara.toml")
        self.deps_dir = os.path.join(self.root, ".qpm", "deps")
        self.lock_path = os.path.join(self.root, ".qpm", "lock.toml")

    @property
    def sections(self):
        return read_toml(self.toml_path)

    def deps(self):
        return dict(self.sections.get("deps", {}))

    def package(self):
        p = self.sections.get("package", {})
        return p.get("name", ""), p.get("version", "")

    def registries(self):
        """(默认 registry 名, {名: url})。"""
        r = dict(self.sections.get("registry", {}))
        default = r.pop("default", "")
        return default, r


# ---------------------------------------------------------------------------
# 4. spec 解析
# ---------------------------------------------------------------------------

Spec = collections.namedtuple("Spec", "kind source rev text")


def _is_path_spec(text):
    return text.startswith(("./", "../", ".\\", "..\\", "/")) or \
        (len(text) > 1 and text[1] == ":")


def parse_spec(name, spec):
    """依赖 spec → Spec(kind, source, rev)。

    kind ∈ {path, git, registry}；registry 的 source 是包名、rev 是区间文本。
    """
    text = (spec or "").strip()
    if text.startswith("path:"):
        return Spec("path", text[len("path:"):], "", text)
    if text.startswith("git:"):
        body = text[len("git:"):]
        url, rev = (body.split("#", 1) if "#" in body else (body, ""))
        return Spec("git", url, rev, text)
    if _is_path_spec(text):
        return Spec("path", text, "", text)
    if text.startswith(_GIT_PREFIXES):
        url, rev = (text.split("#", 1) if "#" in text else (text, ""))
        return Spec("git", url, rev, text)
    return Spec("registry", name, text or "*", text)


def _looks_like_range(rev):
    """rev 是 semver 区间还是精确 tag/branch/sha？语法式判定（v1.45 口径）。"""
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


# ---------------------------------------------------------------------------
# 5. git
# ---------------------------------------------------------------------------

def _git(args, cwd=None):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                       text=True, errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"qpm: git {' '.join(args)} 失败：\n{r.stderr.strip()}")
    return r.stdout.strip()


def ls_remote_tags(url):
    """git ls-remote --tags 的 tag 名（剥 refs/tags/ 与 ^{} 解引用）。"""
    tags = []
    for ln in _git(["ls-remote", "--tags", url]).splitlines():
        _sha, _, ref = ln.partition("\t")
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            tags.append(ref[len("refs/tags/"):])
    return tags


# ---------------------------------------------------------------------------
# 6. registry
# ---------------------------------------------------------------------------

def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "qpm/1.83"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return r.read()


def _http_put(url, data, token=""):
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "application/octet-stream")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return r.status


class Registry:
    """一个 registry 端点：本地目录或 http(s)。索引带 TTL 缓存。"""

    def __init__(self, url, name="", token="", offline=False, refresh=False,
                 log=print):
        self.url = url.rstrip("/")
        self.name = name
        self.token = token
        self.offline = offline
        self.refresh = refresh
        self.log = log or (lambda *a: None)
        self.is_local = not self.url.startswith(("http://", "https://"))
        self.root = None
        if self.is_local:
            body = self.url[len("path:"):] if self.url.startswith("path:") else self.url
            self.root = os.path.abspath(body)

    # -- 路径 ---------------------------------------------------------------
    def _cache_path(self, name):
        return os.path.join(CACHE, "index", _slug(self.url), f"{name}.json")

    def _local_path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    # -- 原始读写 -----------------------------------------------------------
    def _get(self, rel):
        if self.is_local:
            p = self._local_path(rel)
            if not os.path.isfile(p):
                raise FileNotFoundError(p)
            with open(p, "rb") as f:
                return f.read()
        try:
            return _http_get(f"{self.url}/{rel}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise FileNotFoundError(f"{self.url}/{rel}")
            raise SystemExit(f"qpm: registry {self.url} 返回 HTTP {e.code}（{rel}）")
        except urllib.error.URLError as e:
            raise SystemExit(f"qpm: 连不上 registry {self.url}（{e.reason}）；"
                             f"离线请加 --offline")

    def _put(self, rel, data):
        if self.is_local:
            _atomic_write(self._local_path(rel), data)
            return
        try:
            _http_put(f"{self.url}/{rel}", data, self.token)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"qpm: 发布到 {self.url} 失败：HTTP {e.code}（{rel}）"
                             f"{'；token 可能无效' if e.code in (401, 403) else ''}")

    # -- 索引 ---------------------------------------------------------------
    def index(self, name):
        """包索引（dict）或 None。离线只用缓存；在线按 TTL 刷新。"""
        cached = self._cache_path(name)
        use_cache = os.path.isfile(cached) and (
            self.offline or (not self.refresh
                             and (time.time() - os.path.getmtime(cached)) < INDEX_TTL))
        if not use_cache and not self.offline:
            try:
                data = self._get(f"index/{name}.json")
            except FileNotFoundError:
                return None
            _atomic_write(cached, data)
        if not os.path.isfile(cached):
            return None
        with open(cached, "rb") as f:
            try:
                return json.loads(f.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise SystemExit(f"qpm: 索引缓存损坏：{cached}（删掉重试）")

    # -- 包体 ---------------------------------------------------------------
    def blob(self, name, version, sha_expected):
        cache = os.path.join(CACHE, "registry",
                             f"{name}-{version}-{sha_expected[:12]}.qpk")
        data = None
        if os.path.isfile(cache):
            with open(cache, "rb") as f:
                data = f.read()
            if sha_expected and _sha256(data) != sha_expected:
                data = None                      # 缓存坏了，重新取
        if data is None:
            if self.offline:
                raise SystemExit(
                    f"qpm: --offline 但缓存里没有 {name} {version} 的包体"
                    f"（期望 {cache}）")
            data = self._get(f"packages/{name}-{version}.qpk")
        got = _sha256(data)
        if sha_expected and got != sha_expected:
            raise SystemExit(
                f"qpm: {name} {version} 的包哈希不符（索引 {sha_expected[:12]}…，"
                f"实得 {got[:12]}…），拒绝安装")
        _atomic_write(cache, data)
        return data

    # -- 发布 / 撤回 ---------------------------------------------------------
    def publish(self, name, version, blob, deps):
        idx = self.index(name) or {"name": name, "versions": {}}
        versions = dict(idx.get("versions") or {})
        if version in versions:
            raise SystemExit(
                f"qpm: {name} {version} 已存在于 {self.url}；"
                f"同版本不可覆盖（先 qpm yank，再发新版本）")
        entry = {"deps": dict(deps), "sha256": _sha256(blob),
                 "size": len(blob), "yanked": False}
        self._put(f"packages/{name}-{version}.qpk", blob)   # 先传包体，索引不指向空
        versions[version] = entry
        idx["name"] = name
        idx["versions"] = dict(sorted(
            versions.items(), key=lambda kv: qpm_semver.parse_version(kv[0])._key))
        self._put(f"index/{name}.json",
                  json.dumps(idx, ensure_ascii=False, indent=2, sort_keys=True)
                  .encode("utf-8"))
        return entry

    def yank(self, name, version):
        idx = self.index(name)
        if not idx or version not in (idx.get("versions") or {}):
            raise SystemExit(f"qpm: {name} {version} 不在 {self.url} 里")
        idx["versions"][version]["yanked"] = True
        self._put(f"index/{name}.json",
                  json.dumps(idx, ensure_ascii=False, indent=2, sort_keys=True)
                  .encode("utf-8"))


# ---------------------------------------------------------------------------
# 7. 依赖解析（传递依赖 + 区间交集 + 冲突报错）
# ---------------------------------------------------------------------------

Con = collections.namedtuple("Con", "kind source rev origin text")


class Pkg:
    __slots__ = ("name", "kind", "src", "rev", "sha", "version", "deps",
                 "tree", "base")

    def __init__(self, name, kind, src, rev, sha, version, deps, base=None):
        self.name = name
        self.kind = kind
        self.src = src
        self.rev = rev
        self.sha = sha
        self.version = version
        self.deps = deps or {}
        self.tree = ""
        self.base = base

    def ident(self):
        return (self.kind, self.src, self.rev)

    def __repr__(self):
        return f"Pkg({self.name} {self.version} {self.kind})"


class Resolver:
    """贪心 + 定点迭代。`run()` 返回自身：.packages / .edges / .warnings。"""

    def __init__(self, project, offline=False, refresh=False, log=print,
                 registry_name=""):
        self.project = project
        self.offline = offline
        self.refresh = refresh
        self.log = log or (lambda *a: None)
        self.cons = {}
        self.pins = {}
        self.edges = {}
        self.warnings = []
        self.queue = collections.deque()
        self._tags = {}
        self._regs = {}
        default_name, named = project.registries()
        self.registry_name = registry_name or default_name
        self.registry_urls = named
        self._default_reg = None

    # -- registry 选择 -------------------------------------------------------
    @property
    def packages(self):
        """name -> Pkg（解析结果；materialize / tree 共用）。"""
        return self.pins

    def default_registry(self):
        if self._default_reg is None:
            if not self.registry_name:
                raise SystemExit(
                    "qpm: 用到 registry 依赖但没配 registry。\n"
                    "      Quelmara.toml 里加：\n"
                    "        [registry]\n"
                    "        default = \"local\"\n"
                    "        local   = \"path:../qreg\"\n"
                    "      或命令行给 --registry <名字|URL|目录>")
            url = self.registry_urls.get(self.registry_name) or self.registry_name
            self._default_reg = Registry(
                url, name=self.registry_name,
                token=os.environ.get("QPM_TOKEN", ""),
                offline=self.offline, refresh=self.refresh, log=self.log)
        return self._default_reg

    # -- 约束归一化 ----------------------------------------------------------
    def _git_rev(self, url, rev, name):
        if not rev or not _looks_like_range(rev):
            return rev
        if url not in self._tags:
            if self.offline:
                raise SystemExit(
                    f"qpm: --offline 无法为 {name!r} 的区间 {rev!r} 列远端 tag")
            self._tags[url] = ls_remote_tags(url)
        sel = qpm_semver.select_tag(self._tags[url], rev)
        if sel is None:
            avail = "、".join(sorted(self._tags[url])) or "（无 tag）"
            raise SystemExit(f"qpm: {name!r} 的区间 {rev!r} 没有满足的 tag；"
                             f"{url} 可用 tag：{avail}")
        return sel[0]

    def _constraint(self, name, spec, origin, base):
        sp = parse_spec(name, spec)
        if sp.kind == "path":
            p = os.path.normpath(os.path.join(base or self.project.root, sp.source))
            if not os.path.isdir(p):
                raise SystemExit(f"qpm: 路径依赖 {name!r} 不存在：{p}"
                                 f"（来自 {origin}）")
            return Con("path", p, "", origin, sp.text)
        if sp.kind == "git":
            return Con("git", sp.source, self._git_rev(sp.source, sp.rev, name),
                       origin, sp.text)
        return Con("registry", self.default_registry().url, sp.rev or "*",
                   origin, sp.text)

    # -- 冲突文案 ------------------------------------------------------------
    def _absorb_pending(self, name):
        """把队列里同名但还没处理的约束先收进来——冲突信息要一次说全。

        只会在"已经确定失败"的路径上调用：多收约束只会更窄，不会让原本失败的
        组合变得可行，所以不存在"误报"。
        """
        keep = collections.deque()
        while self.queue:
            item = self.queue.popleft()
            if item[0] != name:
                keep.append(item)
                continue
            try:
                self.cons[name].append(self._constraint(*item))
            except SystemExit:
                pass
        self.queue.extend(keep)          # 原地改：run() 里持有同一个 deque
        return self.cons[name]

    def _conflict(self, name, cons, versions=None, kinds=None):
        lines = [f"qpm: 依赖冲突：{name}"]
        if kinds:
            lines.append("      同名依赖来自不同来源，qpm 不做跨来源合并：")
            for c in cons:
                lines.append(f"        {c.kind:<8} {c.source}   （来自 {c.origin}）")
        else:
            lines.append("      没有同时满足全部区间的版本：")
            for c in cons:
                lines.append(f"        需要 {c.rev:<14} （来自 {c.origin}）")
            if versions is not None:
                ok = sorted((v for v, e in versions.items() if not e.get("yanked")),
                            key=lambda v: qpm_semver.parse_version(v)._key)
                yk = sorted(v for v, e in versions.items() if e.get("yanked"))
                lines.append(f"      可用版本：{'、'.join(ok) or '（无）'}")
                if yk:
                    lines.append(f"      已 yank：{'、'.join(yk)}")
        lines.append("      处理：放宽其中一条区间，或改 qpm add 的 spec")
        raise SystemExit("\n".join(lines))

    # -- 选版本 --------------------------------------------------------------
    def _choose(self, name):
        cons = self.cons[name]
        kinds = {c.kind for c in cons}
        if len(kinds) > 1:
            self._conflict(name, self._absorb_pending(name), kinds=kinds)
        kind = cons[0].kind

        if kind == "registry":
            reg = self.default_registry()
            idx = reg.index(name)
            if idx is None:
                raise SystemExit(
                    f"qpm: registry 里没有包 {name!r}（{reg.url}）\n"
                    "      需要它的是："
                    + "、".join(sorted({c.origin for c in self._absorb_pending(name)})))
            versions = idx.get("versions") or {}
            ranges = [c.rev or "*" for c in cons]
            cands = []
            for vtext, ent in versions.items():
                if ent.get("yanked"):
                    continue
                try:
                    v = qpm_semver.parse_version(vtext)
                except qpm_semver.SemverError:
                    continue
                if all(qpm_semver.satisfies(v, r) for r in ranges):
                    cands.append((v, vtext, ent))
            if not cands:
                self._conflict(name, self._absorb_pending(name),
                               versions=versions)
            v, vtext, ent = max(cands, key=lambda x: x[0]._key)
            return Pkg(name, "registry", reg.url, vtext, ent.get("sha256", ""),
                       vtext, dict(ent.get("deps") or {}))

        if kind == "path":
            cons = self.cons[name]
            paths = {c.source for c in cons}
            if len(paths) > 1:
                self._conflict(name, self._absorb_pending(name), kinds=kinds)
            p = paths.pop()
            ver, deps = _pkg_meta(p)
            return Pkg(name, "path", p, "", "", ver, deps, base=p)

        cons = self.cons[name]
        pairs = {(c.source, c.rev) for c in cons}
        if len(pairs) > 1:
            self._conflict(name, self._absorb_pending(name), kinds=kinds)
        url, rev = pairs.pop()
        cache = self._git_cache(name, url, rev)
        sha = _git(["rev-parse", "HEAD"], cwd=cache)
        ver, deps = _pkg_meta(cache)
        return Pkg(name, "git", url, rev, sha, ver, deps, base=cache)

    def _git_cache(self, name, url, rev):
        cache = os.path.join(CACHE, f"{name}-{_slug(rev or 'HEAD')}")
        fresh = os.path.isdir(os.path.join(cache, ".git"))
        if not fresh:
            if self.offline:
                raise SystemExit(f"qpm: --offline 但 git 缓存缺失：{cache}")
            os.makedirs(CACHE, exist_ok=True)
            if rev:
                _git(["clone", "--depth", "1", "--branch", rev, url, cache])
            else:
                _git(["clone", "--depth", "1", url, cache])
        elif not self.offline and rev:
            _git(["fetch", "--depth", "1", "origin", rev], cwd=cache)
            _git(["checkout", rev], cwd=cache)
        return cache

    # -- 展开 ----------------------------------------------------------------
    def _expand(self, pkg):
        self.edges[pkg.name] = list(pkg.deps)
        out = []
        for child, spec in pkg.deps.items():
            if pkg.kind == "registry" and parse_spec(child, spec).kind == "path":
                raise SystemExit(
                    f"qpm: registry 包 {pkg.name} 声明了路径依赖 {child!r}"
                    f"（{spec}）——发布出去的包不能依赖本地路径")
            out.append((child, spec, pkg.name, pkg.base))
        return out

    # -- 主循环 --------------------------------------------------------------
    def run(self):
        roots = self.project.deps()
        queue = self.queue
        queue.extend((n, s, "<manifest>", self.project.root)
                     for n, s in roots.items())
        steps = 0
        while queue:
            steps += 1
            if steps > 5000:
                raise SystemExit("qpm: 依赖解析未收敛（5000 步），请检查区间是否互相拉扯")
            name, spec, origin, base = queue.popleft()
            c = self._constraint(name, spec, origin, base)
            self.cons.setdefault(name, []).append(c)
            self._absorb_pending(name)      # 同名约束一次收齐：选版本与冲突诊断都靠它
            pkg = self.pins.get(name)
            if pkg is None:
                pkg = self._choose(name)
                self.pins[name] = pkg
                queue.extend(self._expand(pkg))
            elif not self._satisfied(pkg, c):
                new = self._choose(name)
                if new.ident() != pkg.ident():
                    self.pins[name] = new
                    queue.extend(self._expand(new))

        for cyc in self._cycles():
            self.warnings.append(
                "依赖环 " + " → ".join(cyc) + "（扁平布局可安装，升级需人工确认）")
        return self

    def _satisfied(self, pkg, con):
        if pkg.kind != con.kind:
            return False
        if pkg.kind == "registry":
            return qpm_semver.satisfies(pkg.rev, con.rev or "*")
        if pkg.kind == "path":
            return pkg.src == con.source
        return (pkg.src, pkg.rev) == (con.source, con.rev)

    def _cycles(self):
        state, cycles = {}, []

        def dfs(node, stack):
            state[node] = 1
            stack.append(node)
            for child in self.edges.get(node, []):
                if state.get(child) == 1:
                    cycles.append(stack[stack.index(child):] + [child])
                elif child not in state:
                    dfs(child, stack)
            stack.pop()
            state[node] = 2

        for r in self.project.deps():
            if r not in state:
                dfs(r, [])
        seen, out = set(), []
        for c in cycles:
            key = frozenset(c)
            if key not in seen:
                seen.add(key)
                out.append(c)
        return out


def _pkg_meta(dirpath):
    """读一个包自己的 Quelmara.toml：([package].version, [deps])。"""
    secs = read_toml(os.path.join(dirpath, "Quelmara.toml"))
    return secs.get("package", {}).get("version", ""), dict(secs.get("deps", {}))


# ---------------------------------------------------------------------------
# 8. 锁文件
# ---------------------------------------------------------------------------

LOCK_HEADER = """# qpm lock v2 —— 由 qpm install 生成，请勿手工编辑
# [packages] 字段：kind|src|rev|sha|version|tree|deps
"""


def write_lock(project, res):
    lines = [LOCK_HEADER.rstrip("\n"), "", "[roots]"]
    for n, s in project.deps().items():
        lines.append(f'{n} = "{_toml_escape(s)}"')
    lines += ["", "[packages]"]
    for name, p in res.packages.items():
        deps = ";".join(f"{k}@{v}" for k, v in p.deps.items())
        raw = "|".join([p.kind, p.src, p.rev, p.sha, p.version, p.tree, deps])
        lines.append(f'{name} = "{_toml_escape(raw)}"')
    _atomic_write(project.lock_path,
                  ("\n".join(lines) + "\n").encode("utf-8"))


def read_lock(project):
    """{'roots': {...}, 'packages': {name: dict}}；无锁返回 None。"""
    if not os.path.isfile(project.lock_path):
        return None
    secs = read_toml(project.lock_path)
    pkgs = {}
    for name, raw in secs.get("packages", {}).items():
        f = raw.split("|")
        if len(f) < 4:
            raise SystemExit(f"qpm: 锁文件条目损坏：{name} = {raw!r}")
        f += [""] * (7 - len(f))
        pkgs[name] = {"kind": f[0], "src": f[1], "rev": f[2], "sha": f[3],
                      "version": f[4], "tree": f[5], "deps": f[6]}
    return {"roots": dict(secs.get("roots", {})), "packages": pkgs}


# ---------------------------------------------------------------------------
# 9. 落地 / 校验
# ---------------------------------------------------------------------------

def _copy_tree(src, dst):
    _rmtree(dst)
    shutil.copytree(src, dst, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*PACK_SKIP_DIRS))


def materialize(project, res, offline=False, log=print):
    os.makedirs(project.deps_dir, exist_ok=True)
    for name, p in res.packages.items():
        dst = os.path.join(project.deps_dir, name)
        if p.kind == "registry":
            reg = Registry(p.src, offline=offline,
                           token=os.environ.get("QPM_TOKEN", ""), log=log)
            unpack_tree(reg.blob(name, p.rev, p.sha), dst)
            log(f"  {name} {p.rev} <- registry {p.src}")
        elif p.kind == "path":
            _copy_tree(p.src, dst)
            log(f"  {name} <- path {p.src}")
        else:
            _copy_tree(p.base, dst)
            log(f"  {name} <- git {p.src}#{p.rev or 'HEAD'} @ {p.sha[:12]}")
        p.tree = tree_hash(dst)


def materialize_locked(project, lock, offline=False, log=print):
    """--locked：完全不解析，按锁落地；缺包体时报错而不是偷偷升级。"""
    res = Resolver(project, offline=offline, log=log)
    for name, e in lock["packages"].items():
        res.packages[name] = Pkg(name, e["kind"], e["src"], e["rev"], e["sha"],
                                 e["version"],
                                 _parse_lock_deps(e["deps"]),
                                 base=e["src"] if e["kind"] == "path" else None)
    materialize(project, res, offline=offline, log=log)
    for name, e in lock["packages"].items():
        res.packages[name].tree = e["tree"] or res.packages[name].tree
    return res


def _parse_lock_deps(text):
    out = {}
    for part in (text or "").split(";"):
        if "@" in part:
            n, _, r = part.partition("@")
            out[n.strip()] = r.strip()
    return out


def verify(project, strict=False):
    """锁 vs 清单 vs 磁盘。返回 (错误数, 警告数)。"""
    lock = read_lock(project)
    if lock is None:
        print("qpm: 没有锁文件，先 qpm install")
        return 1, 0
    errs = warns = 0
    if lock["roots"] != project.deps():
        print("qpm: 清单与锁不一致（Quelmara.toml 改过？跑 qpm install 同步）")
        errs += 1
    for name, e in lock["packages"].items():
        dst = os.path.join(project.deps_dir, name)
        if not os.path.isdir(dst):
            print(f"  FAIL {name}: 未安装（缺 {dst}）")
            errs += 1
            continue
        got = tree_hash(dst)
        if e["tree"] and got != e["tree"]:
            msg = f"{name}: 目录内容与锁不符（锁 {e['tree'][:12]}… 实得 {got[:12]}…）"
            if e["kind"] == "path" and not strict:
                print(f"  WARN {msg} —— path 依赖的源改过，跑 qpm install 同步")
                warns += 1
            else:
                print(f"  FAIL {msg}")
                errs += 1
        else:
            print(f"  ok   {name} {e['version'] or '-'} [{e['kind']}]")
    return errs, warns


def print_tree(res, roots=None):
    roots = roots if roots is not None else res.project.deps()

    def walk(name, prefix, path):
        p = res.packages.get(name)
        if p is None:
            print(f"{prefix}{name} (未解析)")
            return
        mark = ""
        if name in path:
            mark = "  ← 环"
        print(f"{prefix}{name} {p.version or p.rev or ''} "
              f"[{p.kind}]" + (f"  {p.src}" if p.kind != "registry" else "") + mark)
        if mark:
            return
        kids = list(p.deps.items())
        for i, (child, rng) in enumerate(kids):
            last = i == len(kids) - 1
            print(f"{prefix}{'└─ ' if last else '├─ '}{child} {rng}")
            walk(child, prefix + ("   " if last else "│  "), path + [name])

    for i, r in enumerate(roots):
        walk(r, "", [])


# ---------------------------------------------------------------------------
# 10. 命令
# ---------------------------------------------------------------------------

def cmd_install(project, args):
    manifest = project.deps()
    if not manifest:
        print("qpm: [deps] 为空，无事可做")
        return 0
    if args.locked:
        lock = read_lock(project)
        if lock is None:
            raise SystemExit("qpm: --locked 需要已有 .qpm/lock.toml；先跑 qpm install")
        if lock["roots"] != manifest:
            raise SystemExit(
                "qpm: --locked 但清单与锁不一致：\n"
                f"      清单 {manifest}\n      锁   {lock['roots']}\n"
                "      跑 qpm install 重新解析（会更新锁）")
        print(f"qpm: 按锁安装 {len(lock['packages'])} 个包（不解析、不升级）")
        materialize_locked(project, lock, offline=args.offline)
        print(f"qpm: {len(lock['packages'])} 个包已按锁就绪")
        return 0

    res = Resolver(project, offline=args.offline, refresh=args.refresh,
                   registry_name=args.registry).run()
    for w in res.warnings:
        print(f"qpm: 注意：{w}")
    materialize(project, res, offline=args.offline)
    write_lock(project, res)
    print(f"qpm: {len(res.packages)} 个包已就绪（含传递依赖），锁 {project.lock_path}")
    return 0


def cmd_add(project, args):
    rest = args.rest
    if len(rest) < 2:
        raise SystemExit('qpm: add <name> <spec>（如 "path:../mylib" / '
                         '"git:https://…#^1.2.0" / "^1.2.0"）')
    name, spec = rest[0], rest[1]
    set_toml_value(project.toml_path, "deps", name, spec)
    print(f'qpm: 已添加 {name} = "{spec}"')
    ns = argparse.Namespace(offline=False, locked=False, refresh=True, registry="")
    return cmd_install(project, ns)


def cmd_remove(project, args):
    rest = args.rest
    if not rest:
        raise SystemExit("qpm: remove <name>")
    remove_toml_key(project.toml_path, "deps", rest[0])
    dst = os.path.join(project.deps_dir, rest[0])
    _rmtree(dst)
    print(f"qpm: 已移除 {rest[0]}")
    return 0


def cmd_list(project, args):
    deps = project.deps()
    lock = read_lock(project) or {"packages": {}, "roots": {}}
    if not deps:
        print("qpm: [deps] 为空")
        return 0
    default, named = project.registries()
    print(f"registry: {default or '（未配置）'}"
          + (f"（{', '.join(f'{k}={v}' for k, v in named.items())}）" if named else ""))
    for name, spec in deps.items():
        e = lock["packages"].get(name)
        if e:
            print(f"  {name} = \"{spec}\"  [{e['kind']} {e['version'] or e['rev'] or '-'}"
                  f" tree={e['tree'][:8] or '-'}]")
        else:
            print(f"  {name} = \"{spec}\"  [未安装：qpm install]")
    extra = [n for n in lock["packages"] if n not in deps]
    if extra:
        print(f"  传递依赖：{', '.join(sorted(extra))}")
    return 0


def cmd_tree(project, args):
    if not project.deps():
        print("qpm: [deps] 为空")
        return 0
    res = Resolver(project).run()
    for w in res.warnings:
        print(f"qpm: 注意：{w}")
    print_tree(res)
    return 0


def cmd_verify(project, args):
    errs, warns = verify(project, strict=args.strict)
    print(f"qpm: 校验完成，错误 {errs}，警告 {warns}")
    return 1 if errs else 0


def cmd_update(project, args):
    print("qpm: 重新解析（忽略锁，按清单取最新满足版本）")
    ns = argparse.Namespace(offline=False, locked=False, refresh=True, registry="")
    return cmd_install(project, ns)


def cmd_publish(project, args):
    name, version = project.package()
    if not name or not version:
        raise SystemExit(
            "qpm: 发布需要 Quelmara.toml 里有：\n"
            "      [package]\n"
            '      name = "mylib"\n'
            '      version = "1.0.0"')
    try:
        qpm_semver.parse_version(version)
    except qpm_semver.SemverError as e:
        raise SystemExit(f"qpm: [package].version 不合法：{e}")
    reg = Resolver(project, registry_name=args.registry).default_registry()
    blob = pack_tree(project.root)
    deps = project.deps()
    print(f"qpm: 打包 {name} {version} —— {len(_iter_files(project.root))} 个文件，"
          f"{len(blob)} B，sha256 {_sha256(blob)[:16]}…")
    for d, s in deps.items():
        print(f"      依赖 {d} = {s}")
    if args.dry_run:
        print(f"qpm: --dry-run，未写入 {reg.url}")
        return 0
    entry = reg.publish(name, version, blob, deps)
    print(f"qpm: 已发布到 {reg.url}（sha256 {entry['sha256'][:16]}…）")
    return 0


def cmd_yank(project, args):
    rest = args.rest
    if len(rest) < 2:
        raise SystemExit("qpm: yank <name> <version>")
    reg = Resolver(project, registry_name=args.registry).default_registry()
    reg.yank(rest[0], rest[1])
    print(f"qpm: 已撤回 {rest[0]} {rest[1]}（新解析不再选它，锁住的仍可安装）")
    return 0


def cmd_registry(project, args):
    rest = args.rest
    if not rest or rest[0] == "list":
        default, named = project.registries()
        if not named:
            print("qpm: 未配置 registry")
            return 0
        for k, v in named.items():
            print(f"  {k} = \"{v}\"{'   ← default' if k == default else ''}")
        return 0
    if rest[0] == "add":
        if len(rest) < 3:
            raise SystemExit("qpm: registry add <name> <url|目录>")
        set_toml_value(project.toml_path, "registry", rest[1], rest[2])
        default, _ = project.registries()
        if not default:
            set_toml_value(project.toml_path, "registry", "default", rest[1])
        print(f"qpm: registry {rest[1]} = {rest[2]}")
        return 0
    if rest[0] == "remove":
        if len(rest) < 2:
            raise SystemExit("qpm: registry remove <name>")
        remove_toml_key(project.toml_path, "registry", rest[1])
        print(f"qpm: 已移除 registry {rest[1]}")
        return 0
    raise SystemExit("qpm: registry add|remove|list")


def build_parser():
    ap = argparse.ArgumentParser(prog="qpm", description="Quelmara 包管理器",
                                 add_help=True)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("install", help="解析 [deps]（含传递依赖）并落地 + 写锁")
    p.add_argument("--offline", action="store_true", help="只用缓存/本地，不联网")
    p.add_argument("--locked", action="store_true", help="按锁安装，不解析不升级")
    p.add_argument("--refresh", action="store_true", help="忽略索引 TTL，强制刷新")
    p.add_argument("--registry", default="", help="registry 名或 URL/目录")
    sub.add_parser("add", help="添加依赖并 install").add_argument("rest", nargs="*")
    sub.add_parser("remove", help="移除依赖").add_argument("rest", nargs="*")
    sub.add_parser("list", help="列出依赖与锁定状态")
    sub.add_parser("tree", help="打印依赖树")
    p = sub.add_parser("verify", help="校验锁 / 清单 / 磁盘内容")
    p.add_argument("--strict", action="store_true", help="path 依赖漂移也算错误")
    sub.add_parser("update", help="忽略锁重新解析")
    p = sub.add_parser("publish", help="打包并发布当前项目")
    p.add_argument("--registry", default="", help="registry 名或 URL/目录")
    p.add_argument("--dry-run", action="store_true", help="只打包，不上传")
    p = sub.add_parser("yank", help="撤回某个版本")
    p.add_argument("rest", nargs="*")
    p.add_argument("--registry", default="", help="registry 名或 URL/目录")
    p = sub.add_parser("registry", help="registry add|remove|list")
    p.add_argument("rest", nargs="*")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if not args.cmd:
        print(__doc__)
        return 1
    project = Project()
    table = {
        "install": cmd_install, "add": cmd_add, "remove": cmd_remove,
        "list": cmd_list, "tree": cmd_tree, "verify": cmd_verify,
        "update": cmd_update, "publish": cmd_publish, "yank": cmd_yank,
        "registry": cmd_registry,
    }
    return table[args.cmd](project, args)


if __name__ == "__main__":
    sys.exit(main())
