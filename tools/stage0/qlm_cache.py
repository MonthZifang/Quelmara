#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""增量编译缓存（v1.87）——单元级内容寻址缓存 + 精确依赖闭包

## 它解决什么

Quelmara 的编译器是**整程序编译**：主文件 + import 闭包一次性解析、单态化、
降级、优化、分配、编码。没有目标文件格式，所以"改一行只重编一个函数"做不到；
但"什么都没改还全量重编"是纯粹的浪费——`quelmara test tests` 每跑一次都要把
两百个文件从头编一遍，改一个 std 模块又要全部重来。

本模块把**编译单元**（一个主文件 + 它的 import 闭包）当成缓存粒度：

    key = H(schema, 编译器指纹, target, 优化/调试开关, 主文件内容,
            源根目录清单指纹, QLM_* 环境快照)

命中条件（全部满足才算命中，任何一条不满足就重编）：
  1. 编译器指纹一致 —— `tools/stage0/*.py` 任何一个字节变了，全部失效；
  2. 主文件内容一致；
  3. **闭包内每个文件**的内容与记录时一致（逐文件 sha256）；
  4. 源根目录（std / [src].lib / [src].ref）的 `.qma` 清单一致 ——
     新增/删除同名文件会改变 import 解析结果，这一条堵住"遮蔽文件"；
  5. 产物 sha256 与记录一致（防半截写/外部损坏）。

## 依赖闭包怎么来的

**不用重新实现 import 解析**（那会和 `qlm.load_program` 的查找顺序漂移）。
编译期间挂一个 `sys.addaudithook`，把编译器真正 open 过的文件记下来——
这就是闭包的**定义**，不是近似。过滤器只排掉编译器自身的 `.py` 与缓存/构建
目录；`Quelmara.toml`、`read_asset` 嵌进去的资源文件都会自然进闭包。

记不到任何文件（异常路径/钩子被禁）就**不写缓存**——宁可不缓存，也不缓存
一个闭包不完整的条目。

## 边界（做不到的写在这里）

- **不是目标文件格式**：没有 `.qla`，所以做不到"函数级增量"，也做不到
  "只重编变了的模块再链接"。这里省掉的是**整个单元**的编译。
- **单文件内部不并行**：并行粒度是单元（`test -j`），不是函数/模块。
- **不跨机器共享**：缓存里存的是产物二进制，绑 target + 编译器版本。
- 改 `std/` 目录结构（增删文件）会让全部条目失效——这是第 4 条故意的。
"""

import hashlib
import json
import os
import shutil
import sys
import time

SCHEMA = 1
CACHE_DIRNAME = ".qlmcache"
CONFIG_NAME = "Quelmara.toml"

# 不进闭包的目录（相对项目根）：构建产物、缓存自身、VCS、解释器缓存
_EXCLUDE_DIRS = ("build", ".qlmcache", ".git", "__pycache__", ".workbuddy-ai",
                 ".openclaw", ".pytest_cache")
# 编译器自身：已由 compiler_fingerprint 覆盖，不必进闭包
_EXCLUDE_EXT = (".py", ".pyc", ".pyo")

_HASH_MEMO = {}          # (abspath, size, mtime_ns) -> sha256
_HOOK_INSTALLED = False
_RECORDING = None        # 记录中的 set；None = 不在记录
_RECORD_ROOT = None


# ---------------------------------------------------------------------------
# 路径与指纹
# ---------------------------------------------------------------------------

def project_root(src_path=None):
    """从源文件目录向上找 Quelmara.toml，找不到就用 cwd。

    刻意不复用 `qlm.find_config`：缓存命中路径必须**不导入编译器**
    （`import qlm` 在本机要 1.3 s，比缓存查表本身贵两个数量级）。
    查找规则与 `qlm.find_config` 一致：目录逐级向上，取最近的一份。
    """
    start = os.path.dirname(os.path.abspath(src_path)) if src_path else os.getcwd()
    d = start
    while True:
        if os.path.isfile(os.path.join(d, CONFIG_NAME)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()


def cache_root(root=None):
    """缓存根：`QLM_CACHE_DIR` > 项目根下 `.qlmcache`。

    `root` 是**项目根目录**（不是源文件路径）——两者的区别踩过一次：
    把目录当源文件传给 `project_root` 会再往上走一层，缓存就落到父工程里。
    放在项目根（而不是仓库根）是为了让夹具工程各用各的缓存——
    `fixtures/srcproj` 的改动不该让主仓库的条目失效。
    """
    env = os.environ.get("QLM_CACHE_DIR")
    if env:
        return os.path.abspath(env)
    return os.path.join(root or project_root(), CACHE_DIRNAME)


def file_sha(path):
    """内容 sha256（带 (size, mtime) 记忆，同一进程内重复查同一文件零成本）。"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    hit = _HASH_MEMO.get(key)
    if hit is not None:
        return hit
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    digest = h.hexdigest()
    _HASH_MEMO[key] = digest
    return digest


def _stage0_dir():
    return os.path.dirname(os.path.abspath(__file__))


def compiler_fingerprint():
    """编译器指纹 = `tools/stage0/` 下全部 .py 的内容哈希。

    任何一个字节变了（包括别人的并行改动）所有缓存条目立即失效——
    这是"缓存不会掩盖编译器回归"的唯一保证，不许为了省几毫秒换成 mtime。
    """
    h = hashlib.sha256()
    d = _stage0_dir()
    for name in sorted(os.listdir(d)):
        if not name.endswith(".py"):
            continue
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        h.update((file_sha(os.path.join(d, name)) or "?").encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()[:32]


def _read_src_roots(root):
    """从 Quelmara.toml 的 [src] 段取三条根（默认值与 qlm.DEFAULT_CONFIG 一致）。"""
    lib, ref = "src/lib", "src/ref"
    cfg = os.path.join(root, CONFIG_NAME)
    if os.path.isfile(cfg):
        try:
            import tomllib
            with open(cfg, "rb") as f:
                sec = (tomllib.load(f) or {}).get("src", {}) or {}
            lib = sec.get("lib", lib)
            ref = sec.get("ref", ref)
        except Exception:                       # noqa: BLE001 —— 配置坏由编译器报
            pass
    return [os.path.join(root, "std"), os.path.join(root, lib),
            os.path.join(root, ref)]


def dir_fingerprint(root):
    """源根目录的 `.qma` 清单（相对路径 + 大小）。

    import 解析是"按候选顺序取第一个存在的文件"：新增一个更高优先级的
    同名文件会**改变解析结果但不改变任何已存在文件的内容**。所以清单必须
    进 key，否则缓存会拿旧模块的产物糊弄。
    """
    out = []
    for base in _read_src_roots(root):
        if not os.path.isdir(base):
            continue
        rel_base = os.path.relpath(base, root).replace(os.sep, "/")
        items = []
        for dirpath, dirnames, names in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in _EXCLUDE_DIRS)
            for n in sorted(names):
                if n.endswith(".qma"):
                    p = os.path.join(dirpath, n)
                    rel = os.path.relpath(p, base).replace(os.sep, "/")
                    try:
                        items.append(f"{rel}:{os.path.getsize(p)}")
                    except OSError:
                        items.append(rel)
        out.append(f"{rel_base}[{len(items)}]=" + ",".join(items))
    return "|".join(out)


def env_fingerprint():
    """QLM_* 环境快照：这些开关会改变代码生成（DCE/内联/LICM/跳 pass…）。

    全量纳入而不是逐个列举——漏一个就会产出"看起来命中、其实编错"的条目。
    顺带成了测试钩子：`QLM_CACHE_KEY_EXTRA=x` 能让整条缓存失效。
    """
    items = []
    for k in sorted(os.environ):
        if k.startswith("QLM_") and k not in ("QLM_NO_CACHE", "QLM_CACHE_DIR"):
            items.append(f"{k}={os.environ[k]}")
    return ";".join(items)


def unit_key(src_path, target, optimize=True, dbg=False, root=None):
    """算一个编译单元的缓存键，返回 (key, manifest)。"""
    root = root or project_root(src_path)
    src_abs = os.path.abspath(src_path)
    man = {
        "schema": SCHEMA,
        "compiler": compiler_fingerprint(),
        "target": target,
        "opt": bool(optimize),
        "dbg": bool(dbg),
        "src": os.path.relpath(src_abs, root).replace(os.sep, "/"),
        "src_sha": file_sha(src_abs),
        "roots": dir_fingerprint(root),
        "env": env_fingerprint(),
    }
    blob = json.dumps(man, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20], man


# ---------------------------------------------------------------------------
# 闭包记录（审计钩子）
# ---------------------------------------------------------------------------

def _audit(event, args):
    """把编译期真正 open 过的文件记进闭包集合。"""
    rec = _RECORDING
    if rec is None or event != "open":
        return
    p = args[0] if args else None
    if isinstance(p, bytes):
        try:
            p = p.decode("utf-8")
        except UnicodeDecodeError:
            return
    if not isinstance(p, str) or not p:
        return
    if p.endswith(_EXCLUDE_EXT):
        return
    try:
        ap = os.path.abspath(p)
    except (OSError, ValueError):
        return
    rel = ap.replace(os.sep, "/")
    root = _RECORD_ROOT.replace(os.sep, "/") if _RECORD_ROOT else ""
    if root and rel.startswith(root + "/"):
        sub = rel[len(root) + 1:]
        if any(sub == d or sub.startswith(d + "/") for d in _EXCLUDE_DIRS):
            return
    else:
        # 项目外的文件只收源码/配置（例如绝对路径的 asset 根）
        if not ap.endswith((".qma", ".toml")):
            return
    rec.add(ap)


def _install_hook():
    global _HOOK_INSTALLED
    if not _HOOK_INSTALLED:
        sys.addaudithook(_audit)
        _HOOK_INSTALLED = True


class Closure(object):
    """`with Closure() as rec:` 包住一次编译，结束后 `rec.files()` 就是闭包。

    只记**普通文件**且能读到内容的——记不到就当没记，调用方据此放弃缓存。
    """

    def __init__(self, root=None):
        self.root = root
        self.paths = set()

    def __enter__(self):
        global _RECORDING, _RECORD_ROOT
        _install_hook()
        _RECORD_ROOT = self.root
        _RECORDING = self.paths
        return self

    def __exit__(self, *exc):
        global _RECORDING
        _RECORDING = None
        return False

    def files(self, root=None):
        """返回 [(相对项目根路径, sha256)]，按路径排序。"""
        root = root or self.root or os.getcwd()
        out = []
        for p in sorted(self.paths):
            if not os.path.isfile(p):
                continue
            sha = file_sha(p)
            if sha is None:
                continue
            try:
                rel = os.path.relpath(p, root).replace(os.sep, "/")
            except ValueError:                  # 跨盘符
                rel = p.replace(os.sep, "/")
            out.append((rel, sha))
        return out


# ---------------------------------------------------------------------------
# 读写条目
# ---------------------------------------------------------------------------

def _entry_dir(key, root):
    return os.path.join(cache_root(root), "entries", key)


def _meta_path(key, root):
    return os.path.join(_entry_dir(key, root), "meta.json")


def _artifact_path(key, root):
    return os.path.join(_entry_dir(key, root), "artifact")


def load_meta(key, root):
    try:
        with open(_meta_path(key, root), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def verify(key, man, root):
    """校验条目是否仍然有效。返回 (ok, 原因)。

    原因串会出现在 `--verbose` 输出里：命中要能解释，不命中也要能解释。
    """
    meta = load_meta(key, root)
    if not meta:
        return None, "无条目"
    if meta.get("schema") != SCHEMA:
        return None, "schema 变更"
    if meta.get("root") != root:
        return None, "项目根不同"
    art = _artifact_path(key, root)
    if not os.path.isfile(art):
        return None, "产物缺失"
    if os.path.getsize(art) != meta.get("size") or file_sha(art) != meta.get("sha"):
        return None, "产物损坏"
    for rel, sha in meta.get("closure") or []:
        p = rel if os.path.isabs(rel) else os.path.join(root, rel)
        cur = file_sha(p)
        if cur is None:
            return None, f"依赖缺失 {rel}"
        if cur != sha:
            return None, f"依赖已改 {rel}"
    return meta, "ok"


LAST_REASON = ""


def fetch(key, man, out, root):
    """命中则把产物拷到 out 并返回 meta；未命中返回 None。

    未命中的原因写进模块级 `LAST_REASON`，供 CLI 打印——"为什么没命中"
    和"命中"一样重要，不然用户只能怀疑缓存坏了。
    """
    global LAST_REASON
    meta, why = verify(key, man, root)
    LAST_REASON = why
    if meta is None:
        _bump("miss", 0, why, root)
        return None
    d = os.path.dirname(os.path.abspath(out))
    if d:
        os.makedirs(d, exist_ok=True)
    shutil.copyfile(_artifact_path(key, root), out)
    try:
        os.chmod(out, 0o755)
    except OSError:
        pass
    try:
        os.utime(_entry_dir(key, root), None)     # 记录"最近使用"，供 prune 判龄
    except OSError:
        pass
    _bump("hit", int(meta.get("build_ms") or 0), "", root)
    return meta


def _jsonable(obj):
    """把 cfg 压成可 JSON 的值（cfg 里可能混进 tuple/None，别让写缓存失败）。"""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def store(key, man, out, closure, build_ms, root, cfg=None):
    """把产物写进缓存。闭包为空直接拒绝——宁可没有缓存，也不要有洞的缓存。"""
    if not closure:
        return False
    try:
        size = os.path.getsize(out)
        sha = file_sha(out)
    except OSError:
        return False
    if sha is None:
        return False
    d = _entry_dir(key, root)
    tmp = d + ".tmp"
    try:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        shutil.copyfile(out, os.path.join(tmp, "artifact"))
        meta = dict(man)
        meta.update({
            "root": root,
            "size": size,
            "sha": sha,
            "closure": [list(x) for x in closure],
            "build_ms": int(build_ms),
            "cfg": _jsonable(cfg or {}),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1, sort_keys=True)
        shutil.rmtree(d, ignore_errors=True)
        os.replace(tmp, d)                       # 目录级原子替换
        return True
    except (OSError, TypeError, ValueError):
        shutil.rmtree(tmp, ignore_errors=True)
        return False


# ---------------------------------------------------------------------------
# 统计 / 清理
# ---------------------------------------------------------------------------

def _stats_path(root):
    return os.path.join(cache_root(root), "stats.json")


def _bump(kind, saved_ms, why="", root=None):
    """累计命中/未命中计数（写盘失败就丢掉，统计不能影响编译）。"""
    root = root or project_root()
    p = _stats_path(root)
    try:
        try:
            with open(p, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        st[kind] = int(st.get(kind, 0)) + 1
        st["saved_ms"] = int(st.get("saved_ms", 0)) + max(0, saved_ms)
        st["last"] = why or kind
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # 并行构建时多个 worker 会同时写这个文件：先写临时文件再原子替换，
        # 否则读者可能看到半截 JSON（统计可以丢，不能坏）
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except (OSError, ValueError):
        pass


def stats(root=None):
    root = root or project_root()
    base = os.path.join(cache_root(root), "entries")
    n = 0
    size = 0
    oldest = None
    newest = None
    if os.path.isdir(base):
        for name in os.listdir(base):
            p = os.path.join(base, name)
            if not os.path.isdir(p):
                continue
            n += 1
            for f in ("artifact", "meta.json"):
                try:
                    size += os.path.getsize(os.path.join(p, f))
                except OSError:
                    pass
            try:
                mt = os.path.getmtime(p)
                oldest = mt if oldest is None else min(oldest, mt)
                newest = mt if newest is None else max(newest, mt)
            except OSError:
                pass
    out = {"entries": n, "bytes": size, "oldest": oldest, "newest": newest,
           "dir": cache_root(root)}
    try:
        with open(_stats_path(root), encoding="utf-8") as f:
            out.update(json.load(f))
    except (OSError, ValueError):
        pass
    return out


def clear(root=None):
    root = root or project_root()
    d = cache_root(root)
    n = 0
    if os.path.isdir(d):
        n = len(os.listdir(os.path.join(d, "entries"))) \
            if os.path.isdir(os.path.join(d, "entries")) else 0
        shutil.rmtree(d, ignore_errors=True)
    return n


def prune(days=14, root=None):
    """删掉 `days` 天没用过的条目（`last_used` 由 store 更新，fetch 不写盘）。"""
    root = root or project_root()
    base = os.path.join(cache_root(root), "entries")
    if not os.path.isdir(base):
        return 0
    cut = time.time() - days * 86400.0
    n = 0
    for name in os.listdir(base):
        p = os.path.join(base, name)
        if not os.path.isdir(p):
            continue
        try:
            if os.path.getmtime(p) < cut:
                shutil.rmtree(p, ignore_errors=True)
                n += 1
        except OSError:
            pass
    return n
