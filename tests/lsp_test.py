#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语言服务器回归（v1.91：LSP / 补全 / 跳转 / 重命名）
==================================================
五段，前四段是正确性，第五段是性能口径（数字写进 `06-status.md` §3.9）：

  A. **词法对拍**：`qlm_index.scan` 与编译器词法 `qlm.tokenize` 在全仓库
     `.qma` 上逐记号相等（kind + val）。这是"索引不会与编译器漂移"的硬约束：
     词法一改，这里立刻红。
  B. **容错索引**：`qlm.Parser` 解析不了的文件（`std/sse.qma` 拿 `rc` 当变量名）
     照样要有完整符号表——编辑器里的文件永远是半成品。`std/http.qma`（v2.06）与
     `std/timer.qma`（v2.08）修好之后改成正向钉住，防止退回。
  C. **索引语义**：跨文件定义、字段/变体补全、类型约束里的接口方法、
     重命名范围（本文件 / 跨文件）、诊断。
  D. **协议端到端**：起 `quelmara lsp` 子进程，走真的 JSON-RPC：
     initialize → didOpen → completion → definition → references → hover →
     documentSymbol → rename → 诊断推送 → shutdown/exit。
  E. **性能**：全仓库索引耗时、单文件索引耗时、补全延迟（p50/p95）。

跑法：python tests/lsp_test.py
"""

import glob
import json
import os
import queue
import statistics
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE0 = os.path.join(ROOT, "tools", "stage0")
CLI = os.path.join(STAGE0, "qlm_cli.py")
sys.path.insert(0, STAGE0)

import qlm  # noqa: E402
import qlm_index  # noqa: E402

PASS = FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def eq(got, want, why):
    if got == want:
        ok(why)
    else:
        bad(f"{why}（期望 {want!r}，实测 {got!r}）")


def want(cond, why, detail=""):
    if cond:
        ok(why)
    else:
        bad(f"{why}{('：' + detail) if detail else ''}")


def all_sources():
    pats = ["tests/*.qma", "tests/bad/*.qma", "std/*.qma", "examples/*.qma",
            "bench/*.qma", "fixtures/**/*.qma", "bootstrap/**/*.qma"]
    out = []
    for p in pats:
        out += glob.glob(os.path.join(ROOT, p), recursive=True)
    return sorted(set(out))


# ---------------------------------------------------------------------------
# A. 词法对拍
# ---------------------------------------------------------------------------


def test_lex_parity():
    files = all_sources()
    diff = toks = 0
    first = None
    for p in files:
        with open(p, encoding="utf-8") as f:
            src = f.read()
        try:
            a = [(t.kind, t.val) for t in qlm.tokenize(src, keep_comments=True)
                 if t.kind != "NL"]
            b = [(t.kind, t.val) for t in qlm_index.scan(src, keep_comments=True)]
        except SyntaxError:
            continue
        toks += len(b)
        if a != b:
            diff += 1
            if first is None:
                for i, (x, y) in enumerate(zip(a, b)):
                    if x != y:
                        first = f"{os.path.relpath(p, ROOT)} 第 {i} 个记号 {x} vs {y}"
                        break
                else:
                    first = f"{os.path.relpath(p, ROOT)} 长度 {len(a)} vs {len(b)}"
    want(len(files) > 100, f"词法对拍：扫到 {len(files)} 个源文件 / {toks} 个记号")
    eq(diff, 0, f"词法对拍：与 qlm.tokenize 逐记号一致（分叉 {diff} 个）"
       + (f"，首个分叉 {first}" if first else ""))


# ---------------------------------------------------------------------------
# B. 容错索引（编译器前端解析不了的文件）
# ---------------------------------------------------------------------------


def test_tolerant():
    ws = qlm_index.Workspace(ROOT)
    # 容错索引要证明的是"**解析不了**的文件也能给出完整符号表"。
    #
    # v3.26 之前这里用的是 std/sse.qma 与 std/ws.qma（它们曾把关键字 `rc`
    # 当变量名，整个文件过不了前端）。v3.26 把那两处修好了，于是它们变成
    # "能解析"—— 负向用例的前提消失。这里改成**现场构造**一个坏文件，
    # 不再依赖标准库的缺陷状态：那种依赖会让"修好标准库"反而打红回归。
    bad_src = (
        "module badcase\n\n"
        "pub fn alpha(a: int) -> int {\n"
        "    let rc = a\n"          # `rc` 是关键字 -> 解析必失败
        "    return rc\n"
        "}\n\n"
        "pub fn beta(b: int) -> int { return alpha(b) + alpha(b) }\n"
        "pub fn gamma(c: int) -> int { return beta(c) }\n"
        "pub fn delta(d: int) -> int { return gamma(d) }\n"
        "pub fn epsilon(e: int) -> int { return delta(e) }\n"
    )
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    bad_path = os.path.join(ROOT, "build", "lsp_tolerant_bad.qma")
    with open(bad_path, "w", encoding="utf-8") as f:
        f.write(bad_src)

    neg = [(bad_path, "`rc` 当变量名（关键字）")]
    for path, why in neg:
        if not os.path.isfile(path):
            ok(f"容错索引：{path} 不存在，跳过（{why}）")
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        parsed = True
        try:
            qlm.Parser(qlm.tokenize(src)).parse_program()
        except SyntaxError:
            parsed = False
        ix = ws.index(path, src)
        want(not parsed,
             f"容错索引：{os.path.basename(path)} 确实过不了 qlm.Parser（{why}）")
        want(len(ix.syms) >= 5,
             f"容错索引：{os.path.basename(path)} 仍给出 {len(ix.syms)} 个符号")

    # 反向钉住：修好之后必须**能过前端**（`std/http` 的 `rc` 是 v2.06 修的、
    # `std/timer` 的顶层 let 是 v2.07 收进函数的、`std/sse` / `std/ws` 的
    # `rc` 是 v3.26 修的）。这几条防"又退回只能靠容错索引"的状态 ——
    # 容错能力本身由上面的负向用例覆盖。
    pos = [("std/http.qma", "v2.06 修掉 `rc` 撞关键字"),
           ("std/timer.qma", "v2.08 把顶层 let 收进 mem 块"),
           ("std/sse.qma", "v3.26 修掉 `rc` 撞关键字"),
           ("std/ws.qma", "v3.26 修掉 `rc` 撞关键字")]
    for rel, why in pos:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            ok(f"容错索引：{rel} 不存在，跳过（{why}）")
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        parsed = True
        try:
            qlm.Parser(qlm.tokenize(src)).parse_program()
        except SyntaxError:
            parsed = False
        want(parsed, f"容错索引：{rel} 已能过 qlm.Parser（{why}）")
        ix = ws.index(path, src)
        want(len(ix.syms) >= 5 and len(ix.occs) > 20,
             f"容错索引：{rel} 给出 {len(ix.syms)} 个符号 / {len(ix.occs)} 处引用")


# ---------------------------------------------------------------------------
# C. 索引语义（夹具 fixtures/lspdemo）
# ---------------------------------------------------------------------------


def _fixture():
    return os.path.join(ROOT, "fixtures", "lspdemo", "main.qma")


def test_index_semantics():
    ws = qlm_index.Workspace(ROOT)
    ix = ws.index(_fixture())
    util = os.path.normpath(os.path.join(ROOT, "fixtures", "lspdemo", "util.qma"))
    names = {s.name for s in ix.syms}
    want({"Point", "Mode", "shift", "mode_name", "main", "util"} <= names,
         "索引：主文件顶层符号齐全（struct/enum/fn/import）",
         f"实得 {sorted(names)}")
    want(len(ix.diagnostics()) == 0, "索引：夹具无诊断")

    # 跨文件定义：util.make_box 解析到 util.qma
    occ = ix.occ_at(33, 20)
    want(occ is not None and occ.name == "make_box", "索引：定位到 `make_box`")
    want(occ is not None and occ.ref is not None and occ.ref.kind == "ext"
         and occ.ref.path == util,
         "索引：跨文件解析 `util.make_box` -> util.qma",
         repr(occ.ref) if occ else "None")

    # 字段补全：q. -> x/y（Point 的字段），且不给聚合的 to_str
    got = [n for n, k, _d in ix.completions(31, 15)]
    eq(got, ["x", "y"], "补全：`q.` 给 Point 的字段（不给聚合 to_str）")

    # 变体补全：Mode. -> Fast/Slow
    got = [n for n, k, _d in ix.completions(36, 25)]
    eq(got, ["Fast", "Slow"], "补全：`Mode.` 给枚举变体")

    # 模块补全：util. -> 只有 pub 声明
    got = [n for n, k, _d in ix.completions(33, 17)]
    eq(got, ["Color", "Box", "color_name", "area", "make_box"],
       "补全：`util.` 只给被导入模块的 pub 声明")

    # 局部补全：函数体里能看到形参与局部变量
    got = [n for n, k, _d in ix.completions(33, 12)]
    want("wx" in got and "hy" in got and "b" in got and "p" in got,
         "补全：作用域内局部变量（含形参）齐全", f"实得 {got[:8]}")

    # 引用：`Point` 的 5 处出现（声明 + 形参 + 返回 + 两处字面量）
    locs = ws.find_refs(ix.path, "Point", "struct")
    eq(len(locs), 5, "引用：`Point` 有 5 处（声明/形参/返回/两处字面量）")

    # 类型约束里的接口方法：`s.area()` 在 t101 里
    ix2 = ws.index(os.path.join(ROOT, "tests", "t101_bounds.qma"))
    got = [n for n, k, _d in ix2.completions(62, 16)]
    eq(got, ["area"], "补全：`[T: Shape]` 的 `s.` 给约束接口的方法")

    # 诊断：括号不配对 + 顶层重名
    bad_src = "module x\n\nfn a() {\n    let v = 1\n\nfn a() { }\n"
    ix3 = ws.index(os.path.join(ROOT, "build", "_lsp_bad.qma"), bad_src)
    diags = ix3.diagnostics()
    want(any("未闭合" in d["message"] for d in diags),
         "诊断：括号不配对报出来", str([d["message"] for d in diags]))
    lex_src = 'module y\nfn f() { print("oops) }\n'
    ix4 = ws.index(os.path.join(ROOT, "build", "_lsp_lex.qma"), lex_src)
    want(any("字符串未闭合" in d["message"] for d in ix4.diagnostics()),
         "诊断：未闭合字符串报出来（词法层）")

    # UTF-16 位置换算（LSP 默认编码）：非 BMP 字符占两个单元
    lm = qlm_index.LineMap("a\U0001F600b")
    eq((lm.to_utf16(0, 2), lm.from_utf16(0, 3)), (3, 2),
       "位置：非 BMP 字符按 UTF-16 双单元换算")


# ---------------------------------------------------------------------------
# D. 协议端到端
# ---------------------------------------------------------------------------


class Client:
    def __init__(self, root):
        self.proc = subprocess.Popen(
            [sys.executable, CLI, "lsp", "--root", root],
            cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        self.q = queue.Queue()
        self.notes = []
        self._id = 0
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        f = self.proc.stdout
        while True:
            headers = {}
            while True:
                line = f.readline()
                if not line:
                    self.q.put(None)
                    return
                line = line.decode("ascii", "replace").strip()
                if not line:
                    break
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()
            n = int(headers.get("content-length", "0"))
            body = f.read(n)
            try:
                msg = json.loads(body.decode("utf-8"))
            except Exception:
                self.q.put(None)
                return
            if "id" in msg:
                self.q.put(msg)
            else:
                self.notes.append(msg)

    def send(self, obj):
        data = json.dumps(obj).encode("utf-8")
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(data))
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def request(self, method, params, timeout=20):
        self._id += 1
        mid = self._id
        self.send({"jsonrpc": "2.0", "id": mid, "method": method,
                   "params": params})
        deadline = time.time() + timeout
        while True:
            left = max(0.1, deadline - time.time())
            msg = self.q.get(timeout=left)
            if msg is None:
                raise RuntimeError(f"服务在 {method} 期间关闭")
            if msg.get("id") == mid:
                return msg

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def diags(self, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            for m in list(self.notes):
                if m.get("method") == "textDocument/publishDiagnostics":
                    self.notes.remove(m)
                    return m["params"]["diagnostics"]
            time.sleep(0.02)
        return []

    def close(self):
        try:
            self.request("shutdown", None, timeout=5)
            self.notify("exit", None)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def test_protocol():
    root = ROOT
    path = _fixture()
    uri = qlm_index.path_to_uri(path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    c = Client(root)
    try:
        r = c.request("initialize", {
            "processId": os.getpid(), "rootUri": qlm_index.path_to_uri(root),
            "capabilities": {}})
        caps = (r.get("result") or {}).get("capabilities") or {}
        want(bool(caps.get("completionProvider")) and bool(caps.get("renameProvider")),
             "协议：initialize 声明补全/重命名能力")
        c.notify("initialized", {})
        c.notify("textDocument/didOpen", {"textDocument": {
            "uri": uri, "languageId": "quelmara", "version": 1, "text": text}})
        eq(c.diags(), [], "协议：didOpen 后无诊断（夹具本身合法）")

        # 补全
        r = c.request("textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": 31, "character": 15}})
        items = (r.get("result") or {}).get("items") or []
        eq([i["label"] for i in items], ["x", "y"], "协议：`q.` 补全两项字段")
        want(all(i.get("kind") == 5 for i in items),
             "协议：字段补全的 CompletionItemKind = Field(5)")

        # 跳转（跨文件）
        r = c.request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": 33, "character": 20}})
        locs = r.get("result") or []
        want(len(locs) == 1 and locs[0]["uri"].endswith("util.qma"),
             "协议：`util.make_box` 跳转到 util.qma",
             json.dumps(locs, ensure_ascii=False)[:200])

        # 引用
        r = c.request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": 11, "character": 8},
            "context": {"includeDeclaration": True}})
        eq(len(r.get("result") or []), 5, "协议：`Point` 引用 5 处")

        # 悬停
        r = c.request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": 15, "character": 4}})
        val = ((r.get("result") or {}).get("contents") or {}).get("value") or ""
        want("fn shift(" in val, "协议：hover 给出签名", val[:80])

        # 大纲
        r = c.request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
        syms = r.get("result") or []
        names = [s["name"] for s in syms]
        want({"Point", "Mode", "shift", "main"} <= set(names),
             "协议：documentSymbol 顶层齐全", str(names))
        pt = next((s for s in syms if s["name"] == "Point"), None)
        want(pt is not None and [k["name"] for k in pt.get("children", [])] == ["x", "y"],
             "协议：documentSymbol 里 Point 有 x/y 两个子项")

        # 重命名（本文件 + 跨文件）
        r = c.request("textDocument/rename", {
            "textDocument": {"uri": uri},
            "position": {"line": 33, "character": 20},
            "newName": "build_box"})
        changes = (r.get("result") or {}).get("changes") or {}
        util_uri = qlm_index.path_to_uri(
            os.path.join(ROOT, "fixtures", "lspdemo", "util.qma"))
        n_util = len(changes.get(util_uri, []))
        n_main = len(changes.get(uri, []))
        want(n_util >= 1 and n_main >= 1,
             f"协议：跨文件重命名同时改 util.qma（{n_util} 处）与 main.qma（{n_main} 处）")

        # 非法重命名被拒（带原因，不是静默 null）
        r = c.request("textDocument/rename", {
            "textDocument": {"uri": uri},
            "position": {"line": 33, "character": 20},
            "newName": "let"})
        eq((r.get("error") or {}).get("code"), -32602,
           "协议：关键字重命名被拒绝（-32602 带原因）")

        # 注释/字符串里不弹补全
        c.notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": 3},
            "contentChanges": [{"text": text + "\n// 注释里 q.\n"}]})
        r = c.request("textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": text.count("\n") + 1, "character": 8}})
        eq((r.get("result") or {}).get("items"), [],
           "协议：注释里不弹补全")
        c.diags()          # 吃掉这次 didChange 推的空诊断，别干扰下一段

        # 诊断推送：改成坏代码
        broken = text.replace("fn main() {", "fn main() {{", 1)
        c.notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": broken}]})
        d = c.diags()
        want(len(d) >= 1 and d[0]["severity"] == 1,
             "协议：改坏后推送 error 级诊断", str(d[:1]))

        # 未实现的方法要报 -32601（不静默）
        r = c.request("textDocument/formatting", {
            "textDocument": {"uri": uri}, "options": {"tabSize": 4}})
        eq((r.get("error") or {}).get("code"), -32601,
           "协议：未实现的方法返回 -32601")

        # 文档高亮
        r = c.request("textDocument/documentHighlight", {
            "textDocument": {"uri": uri},
            "position": {"line": 11, "character": 8}})
        eq(len(r.get("result") or []), 5, "协议：`Point` 文档高亮 5 处")
    finally:
        c.close()

    # 全局符号：只在小工作区里跑（ensure_all 的成本与仓库规模成正比）
    root2 = os.path.join(ROOT, "fixtures", "lspdemo")
    c2 = Client(root2)
    try:
        c2.request("initialize", {"processId": os.getpid(),
                                  "rootUri": qlm_index.path_to_uri(root2),
                                  "capabilities": {}})
        c2.notify("initialized", {})
        r = c2.request("workspace/symbol", {"query": "color"})
        names = [s["name"] for s in (r.get("result") or [])]
        want("color_name" in names and "Color" in names,
             "协议：workspace/symbol 跨文件查到 pub 声明", str(names))
    finally:
        c2.close()


# ---------------------------------------------------------------------------
# E. 性能
# ---------------------------------------------------------------------------


def test_perf():
    ws = qlm_index.Workspace(ROOT)
    files = all_sources()
    t0 = time.perf_counter()
    n = 0
    for p in files:
        try:
            ws.index(p)
            n += 1
        except Exception:
            continue
    total = (time.perf_counter() - t0) * 1000.0
    per = total / max(1, n)
    print(f"  [perf] 全仓库索引 {n} 个文件 {total:.0f} ms，均值 {per:.2f} ms/文件")
    want(n > 100 and per < 50, f"性能：均值 {per:.2f} ms/文件（阈值 50）")

    # 单文件（大文件）冷索引
    big = os.path.join(ROOT, "std", "httpc.qma")
    if os.path.isfile(big):
        with open(big, encoding="utf-8") as f:
            src = f.read()
        times = []
        for _ in range(5):
            t = time.perf_counter()
            qlm_index.Index(big, src)
            times.append((time.perf_counter() - t) * 1000.0)
        med = statistics.median(times)
        print(f"  [perf] std/httpc.qma（{src.count(chr(10)) + 1} 行）冷索引 "
              f"{med:.2f} ms（min {min(times):.2f}）")
        want(med < 60, f"性能：大文件冷索引 {med:.2f} ms（阈值 60）")

    # 补全延迟
    ix = ws.index(os.path.join(ROOT, "tests", "t101_bounds.qma"))
    lat = []
    for i in range(200):
        line, col = (62, 16) if i % 2 else (35, 12)
        t = time.perf_counter()
        ix.completions(line, col)
        lat.append((time.perf_counter() - t) * 1000.0)
    lat.sort()
    p50, p95 = lat[len(lat) // 2], lat[int(len(lat) * 0.95)]
    print(f"  [perf] 补全延迟 p50 {p50:.3f} ms / p95 {p95:.3f} ms（200 次）")
    want(p95 < 5, f"性能：补全 p95 {p95:.3f} ms（阈值 5）")


def main():
    print("== [A] 词法对拍（scan vs qlm.tokenize） ==")
    test_lex_parity()
    print("== [B] 容错索引（编译器前端解析不了的文件） ==")
    test_tolerant()
    print("== [C] 索引语义（fixtures/lspdemo） ==")
    test_index_semantics()
    print("== [D] 协议端到端（真 JSON-RPC 子进程） ==")
    test_protocol()
    print("== [E] 性能 ==")
    test_perf()
    print(f"\nPASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
