#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qpm semver —— 版本解析、区间求值与 tag 选择（v1.45）。

只依赖标准库，不碰网络/git：调用方（tools/qpm.py）负责 `git ls-remote --tags`
拿 tag 列表，本模块负责"哪些 tag 满足区间、选哪一个"。

区间语法（node-semver / Cargo 的实用子集）：

  *                任意正式版（不匹配预发布）
  1.2.3            精确版本
  ^1.2.3           >=1.2.3 <2.0.0（0.x：<0.(y+1).0；0.0.x：<0.0.(z+1)）
  ~1.2.3           >=1.2.3 <1.3.0（~1.2 → <1.3.0；~1 → <2.0.0）
  >=1.2 <2.0.0     比较符 + 部分版本（> 带部分版本时末位 +1；< 补 0）
  =1.2             精确（补 0）
  1.2.x / 1.*      通配段（1.2.x → >=1.2.0 <1.3.0）
  >=1.0, <2.0      逗号/空格 = AND
  ^1 || ^2         || = OR

版本文法：v?MAJOR.MINOR.PATCH[-prerelease][+build]（tag 的 `v` 前缀可省）。
比较遵循 semver.org §11：数字段数值比较；无预发布 > 有预发布；预发布标识逐段
比较（数值段按数、字母段按 ASCII、数值段 < 字母段）；+build 不参与比较。

预发布门槛（node-semver 同款）：带预发布的版本只满足"同一 X.Y.Z 上带预发布的
比较符"所在的 AND 组——`^1.2.3` 选不中 `2.0.0-rc1`，`*` 也选不中 `1.0.0-rc1`；
要预发布须显式写出来（`^1.2.3-rc1` / `>=1.2.3-rc1, <1.2.4`）。

已知边界（v1.45 如实登记）：
  * 只认整段 tag（可选 `v` 前缀）；`pkg-v1.2.3` 这类带前缀的 tag 不解析。
  * 预发布数字标识允许前导零（`1.0.0-01` 按数值 1 比较）——选 tag 不做语义警察。
  * 版本 core（X.Y.Z）按 semver 规范拒绝前导零（`01.2.3` 不合法）。
  * 区间/精确的判定在 qpm.py `_looks_like_range`，是语法式的：名字恰好长得像
    区间的 tag/branch（如 `1.x-dev`）会被当区间解析，失败即报错。
"""
import re

__all__ = ["SemverError", "Version", "parse_version", "parse_range",
           "satisfies", "max_satisfying", "parse_tag", "select_tag"]


class SemverError(ValueError):
    """区间/版本文本无法解析（fail-fast：由 qpm 转成 SystemExit）。"""


_VERSION_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")

# 区间里的部分版本：任一段可缺省或是通配（x / X / *）
_PARTIAL_RE = re.compile(
    r"^v?(?P<major>\d+|[xX*])(?:\.(?P<minor>\d+|[xX*]))?(?:\.(?P<patch>\d+|[xX*]))?"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")

_CMP_RE = re.compile(r"^(?P<op>\^|~|>=|<=|>|<|=)?\s*(?P<rest>.+)$")


class Version:
    """一个 semver 版本。比较按 semver.org §11 优先级，build 不参与。"""

    __slots__ = ("major", "minor", "patch", "prerelease", "build")

    def __init__(self, major, minor, patch, prerelease=(), build=""):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.prerelease = tuple(prerelease)
        self.build = build

    @property
    def _key(self):
        # 无预发布 > 有预发布：用 1/0 打头，元组比较天然搞定；
        # 预发布标识：数值段 (0, n, "") < 字母段 (1, 0, s)，段数少者小。
        if not self.prerelease:
            return (self.major, self.minor, self.patch, 1)
        ids = tuple((0, int(i), "") if i.isdigit() else (1, 0, i)
                    for i in self.prerelease)
        return (self.major, self.minor, self.patch, 0) + ids

    def __eq__(self, other):
        return isinstance(other, Version) and self._key == other._key

    def __lt__(self, other):
        return self._key < other._key

    def __le__(self, other):
        return self._key <= other._key

    def __gt__(self, other):
        return self._key > other._key

    def __ge__(self, other):
        return self._key >= other._key

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._key)

    def __str__(self):
        s = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            s += "-" + ".".join(self.prerelease)
        return s

    def __repr__(self):
        return f"Version({str(self)!r})"


def parse_version(text, what="版本"):
    """解析完整版本（X.Y.Z 三段必填；`v` 前缀与 +build 可选）。"""
    m = _VERSION_RE.match(text.strip()) if isinstance(text, str) else None
    if not m:
        raise SemverError(
            f"{what} {text!r} 不是合法 semver（期望 v?X.Y.Z[-pre][+build]）")
    pre = tuple(m.group("pre").split(".")) if m.group("pre") else ()
    return Version(int(m.group("major")), int(m.group("minor")),
                   int(m.group("patch")), pre, m.group("build") or "")


def _parse_partial(rest, what):
    m = _PARTIAL_RE.match(rest)
    if not m:
        raise SemverError(f"{what} {rest!r} 不是合法版本/区间段")

    def num(g):
        v = m.group(g)
        if v is None or v in ("x", "X", "*"):
            return None
        return int(v)

    pre = tuple(m.group("pre").split(".")) if m.group("pre") else ()
    return num("major"), num("minor"), num("patch"), pre, m.group("build") or ""


def _expand(op, rest, what):
    """一个比较符 -> [(op, Version), ...]（展开成下限/上限对）。"""
    major, minor, patch, pre, build = _parse_partial(rest, what)
    if major is None and op is not None:
        raise SemverError(f"{what} {rest!r}：比较符 {op!r} 需要具体版本，不能配通配")
    if op in (None, "="):
        if major is None:                       # * / x
            return []
        if minor is None:                       # "1"   -> >=1.0.0 <2.0.0
            return [(">=", Version(major, 0, 0)),
                    ("<", Version(major + 1, 0, 0))]
        if patch is None:                       # "1.2" -> >=1.2.0 <1.3.0
            return [(">=", Version(major, minor, 0)),
                    ("<", Version(major, minor + 1, 0))]
        return [("=", Version(major, minor, patch, pre, build))]
    if op == "^":
        lo = Version(major, minor or 0, patch or 0, pre, build)
        if major > 0 or minor is None:          # ^1 / ^1.2 -> <2.0.0
            hi = Version(major + 1, 0, 0)
        elif minor > 0 or patch is None:        # ^0.2 / ^0   -> <0.(y+1).0 / <1.0.0
            hi = Version(0, minor + 1, 0)
        else:                                   # ^0.0.3 -> <0.0.4
            hi = Version(0, 0, patch + 1)
        return [(">=", lo), ("<", hi)]
    if op == "~":
        if minor is None:                       # ~1 -> >=1.0.0 <2.0.0
            return [(">=", Version(major, 0, 0)),
                    ("<", Version(major + 1, 0, 0))]
        if patch is None:                       # ~1.2 -> >=1.2.0 <1.3.0
            return [(">=", Version(major, minor, 0)),
                    ("<", Version(major, minor + 1, 0))]
        return [(">=", Version(major, minor, patch, pre, build)),
                ("<", Version(major, minor + 1, 0))]
    if op == ">":
        if minor is None:                       # >1   -> >=2.0.0
            return [(">=", Version(major + 1, 0, 0))]
        if patch is None:                       # >1.2 -> >=1.3.0
            return [(">=", Version(major, minor + 1, 0))]
        return [(op, Version(major, minor, patch, pre, build))]
    if op == ">=":
        return [(op, Version(major, minor or 0, patch or 0, pre, build))]
    if op == "<":
        return [(op, Version(major, minor or 0, patch or 0, pre, build))]
    if op == "<=":
        if minor is None:                       # <=1   -> <2.0.0
            return [("<", Version(major + 1, 0, 0))]
        if patch is None:                       # <=1.2 -> <1.3.0
            return [("<", Version(major, minor + 1, 0))]
        return [(op, Version(major, minor, patch, pre, build))]
    raise SemverError(f"不支持的比较符 {op!r}")


def parse_range(text):
    """区间文本 -> OR 组列表；每组是 [(op, Version), ...]（AND）。"""
    if not isinstance(text, str):
        raise SemverError(f"区间 {text!r} 不是文本")
    s = text.strip()
    if not s:
        return [[]]
    groups = []
    for part in s.split("||"):
        comps = []
        for tok in re.split(r"[,\s]+", part.strip()):
            if not tok:
                continue
            m = _CMP_RE.match(tok)
            if not m:
                raise SemverError(f"区间 {text!r} 的比较符 {tok!r} 无法解析")
            comps.extend(_expand(m.group("op"), m.group("rest"),
                                 f"区间 {text!r} 的比较符"))
        groups.append(comps)
    return groups


def _cmp_ok(version, op, cv):
    if op == "=":
        return version == cv
    if op == ">":
        return version > cv
    if op == ">=":
        return version >= cv
    if op == "<":
        return version < cv
    if op == "<=":
        return version <= cv
    raise SemverError(f"内部错误：未知比较符 {op!r}")


def _set_ok(version, comps):
    """单个 AND 组是否满足。预发布门槛见模块 docstring。"""
    if not comps:                               # "*"：任意，但不含预发布
        return not version.prerelease
    for op, cv in comps:
        if not _cmp_ok(version, op, cv):
            return False
    if version.prerelease:
        for _op, cv in comps:
            if cv.prerelease and \
                    (cv.major, cv.minor, cv.patch) == \
                    (version.major, version.minor, version.patch):
                return True
        return False
    return True


def satisfies(version, range_text):
    """version（Version 或 "x.y.z" 文本）是否满足区间。"""
    if not isinstance(version, Version):
        version = parse_version(version)
    return any(_set_ok(version, comps) for comps in parse_range(range_text))


def max_satisfying(versions, range_text):
    """可迭代的版本里满足区间的最大者；无则 None。"""
    best = None
    for v in versions:
        if not isinstance(v, Version):
            v = parse_version(v)
        if satisfies(v, range_text) and (best is None or v > best):
            best = v
    return best


def parse_tag(tag):
    """git tag -> Version；不是版本形态（可选 `v` 前缀的完整 X.Y.Z）返回 None。"""
    if not tag:
        return None
    try:
        return parse_version(tag, f"tag {tag!r}")
    except SemverError:
        return None


def select_tag(tags, range_text):
    """从 tag 列表里选满足区间的最大版本。返回 (tag, Version)；无则 None。"""
    cands = []
    for t in tags:
        v = parse_tag(t)
        if v is not None and satisfies(v, range_text):
            cands.append((t, v))
    if not cands:
        return None
    return max(cands, key=lambda tv: tv[1]._key)
