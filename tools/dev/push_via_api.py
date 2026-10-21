#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 GitHub REST API 推送当前树（github.com:443 被代理拦截时的备用通道）。

背景：本机代理只放行 api.github.com，`git push` 会 502；而远端 master 停在很早的
Rosoto 快照（.ros/旧名），增量 diff 套不上去（会 422 GitRPC::BadObjectState）。  # legacy-ok

做法：
1. `git ls-tree -r HEAD` 取**完整树**（path/mode/sha）；
2. 远端已有同 sha 的 blob 直接复用，其余逐个 POST /git/blobs；
3. POST /git/trees（**不带 base_tree**，即整棵树替换）；
4. POST /git/commits，parents = [远端 master]（快照提交，不重写远端历史；
   本地提交对象不在远端，不能当 parent —— 会 422）；
5. PATCH refs/heads/master。本地详细历史留在开发分支（如 rename/quelmara）。
"""
import base64
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

REPO = "MonthZifang/Rosoto"  # legacy-ok：GitHub 仓库名即此，非旧名残留
API = "https://api.github.com"


def sh(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw).stdout


def token():
    out = sh("git", "credential", "fill",
             input="protocol=https\nhost=github.com\n\n")
    for ln in out.splitlines():
        if ln.startswith("password="):
            return ln.split("=", 1)[1]
    raise SystemExit("没有可用的 GitHub 凭据（git credential fill 返回空）")


TOK = token()


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOK)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "quelmara-push")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"{method} {path} -> {e.code}: {detail}")


def main():
    head = sh("git", "rev-parse", "HEAD").strip()
    # 提交消息：优先用 build/_merge_msg.txt（整棵树的合并提交要写清来龙去脉）
    mp = pathlib.Path("build/_merge_msg.txt")
    msg = (mp.read_text(encoding="utf-8").rstrip("\n") if mp.exists()
           else sh("git", "log", "-1", "--format=%B").rstrip("\n"))
    an = sh("git", "log", "-1", "--format=%an").strip()
    ae = sh("git", "log", "-1", "--format=%ae").strip()
    ad = sh("git", "log", "-1", "--format=%aI").strip()

    ref = api("GET", f"/repos/{REPO}/git/ref/heads/master")
    base_sha = ref["object"]["sha"]
    base = api("GET", f"/repos/{REPO}/git/commits/{base_sha}")
    print(f"远端 master = {base_sha[:10]}")

    rtree = api("GET", f"/repos/{REPO}/git/trees/{base['tree']['sha']}?recursive=1")
    remote = {e["path"]: e["sha"] for e in rtree["tree"] if e["type"] == "blob"}
    print(f"远端已有 blob {len(remote)} 个")

    entries = []
    lines = subprocess.run(["git", "-c", "core.quotePath=false", "ls-tree", "-r", "-z", "HEAD"],
                           capture_output=True).stdout.split(b"\x00")
    rows = []
    for ln in lines:
        if not ln:
            continue
        meta, path = ln.split(b"\t", 1)
        mode, _typ, sha = meta.decode().split()
        rows.append((mode, path.decode("utf-8", "surrogateescape"), sha))
    print(f"本地文件 {len(rows)} 个")

    uploaded = 0
    for i, (mode, path, sha) in enumerate(rows, 1):
        if remote.get(path) == sha:
            entries.append({"path": path, "mode": mode, "type": "blob", "sha": sha})
            continue
        raw = subprocess.run(["git", "cat-file", "blob", sha], capture_output=True).stdout
        b = api("POST", f"/repos/{REPO}/git/blobs",
                {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        entries.append({"path": path, "mode": mode, "type": "blob", "sha": b["sha"]})
        uploaded += 1
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}（新上传 {uploaded}）")
    print(f"上传完成：新增/更新 blob {uploaded} 个")

    tree = api("POST", f"/repos/{REPO}/git/trees", {"tree": entries})
    print(f"tree = {tree['sha'][:10]}")
    commit = api("POST", f"/repos/{REPO}/git/commits",
                 # 单亲：只挂远端旧 head（本地提交对象不在远端，作 parent 会 422）
                 {"message": msg, "tree": tree["sha"], "parents": [base_sha],
                  "author": {"name": an, "email": ae, "date": ad},
                  "committer": {"name": an, "email": ae, "date": ad}})
    api("PATCH", f"/repos/{REPO}/git/refs/heads/master",
        {"sha": commit["sha"], "force": False})
    print(f"远端 master -> {commit['sha']}")

    sh("git", "update-ref", "refs/heads/master", commit["sha"])
    print("本地 master 已对齐（工作区内容不变）：", sh("git", "rev-parse", "HEAD").strip()[:10])
    return 0


if __name__ == "__main__":
    sys.exit(main())
